import logging
from datetime import datetime, timezone
from app.agents.recovery_agent import RecoveryAgent
from app.policy.gate import PolicyGate
from app.execution.simulator import SubscriptionSimulator
from app.execution.live_executor import LiveExecutor
from app.execution.razorpay import RazorpayAPIError
from app.audit.logger import AuditLogger
from app.economics import EconomicsEngine, MerchantConfig
from app.decision.versioning import versions
from app.decision.replay import stable_hash, DecisionStore
from app.execution.authorization import ExecutionAuthorization
from app.execution.outbox import enqueue_execution_intent
from app.execution.circuit_breaker import CircuitBreaker
from app.db import init_db
from app.approval import create_approval_request
from app.config import DATA_DIR
from app.monitoring.drift import DriftDetector
from app.diagnosis import diagnose
from app.messaging import generate_message

logger = logging.getLogger(__name__)


class RecoveryPipeline:
    RISK_MODES = {"CONSERVATIVE": 2.0, "BALANCED": 1.0, "AGGRESSIVE": 0.0}

    def __init__(self, model=None, simulator=None, policy=None, agent=None, audit=None, risk_mode=None, merchant_config=None, decision_store=None, drift_detector=None):
        init_db()
        self.model = model
        self.simulator = simulator or SubscriptionSimulator()
        if merchant_config is not None:
            self.merchant_config = merchant_config
        else:
            self.merchant_config = MerchantConfig.load_persisted()
            if risk_mode is not None:
                self.merchant_config = MerchantConfig.from_dict({**self.merchant_config.to_dict(), "risk_mode": risk_mode})

        self.policy = policy or PolicyGate.from_merchant_config(self.merchant_config)
        self.agent = agent or RecoveryAgent()
        self.audit = audit or AuditLogger()
        self.economics = EconomicsEngine(merchant_config=self.merchant_config)
        self.risk_mode = self.merchant_config.risk_mode
        self.risk_z = self.RISK_MODES.get(self.risk_mode, 1.0)
        self.circuit_breaker = CircuitBreaker()
        self.live_executor = LiveExecutor()
        self.decision_store = decision_store or DecisionStore()
        self.drift_detector = drift_detector or DriftDetector(DATA_DIR / 'training_data.csv')

    def update_merchant_config(self, new_config: MerchantConfig | dict) -> MerchantConfig:
        if isinstance(new_config, dict):
            merged = {**self.merchant_config.to_dict(), **new_config}
            self.merchant_config = MerchantConfig.from_dict(merged)
        else:
            self.merchant_config = new_config

        self.merchant_config.save_persisted()
        self.economics = EconomicsEngine(merchant_config=self.merchant_config)
        self.risk_mode = self.merchant_config.risk_mode
        self.risk_z = self.RISK_MODES.get(self.risk_mode, 1.0)
        self.policy.max_auto_action_amount = self.merchant_config.max_auto_action_amount
        self.policy.require_human_above = self.merchant_config.require_human_above
        self.policy.max_customer_nudges_7d = self.merchant_config.max_customer_nudges_7d
        return self.merchant_config

    def _predictions(self, case: dict, source: str):
        if self.model is not None and source == "ml":
            return self.model.predict_all_actions(case)
        return {
            a: {"mean": self.simulator.get_true_probability(case, a), "std": 0.0, "lower": self.simulator.get_true_probability(case, a), "upper": self.simulator.get_true_probability(case, a), "n_models": 0}
            for a in ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"]
        }

    def process(self, case: dict, source: str = "ml", risk_mode: str | None = None, is_preview: bool = False) -> dict:
        is_live = bool(case.get("is_live", False))
        distribution_shift_flagged = False
        drift_details = None

        effective_risk_mode = str(risk_mode).upper() if risk_mode is not None else self.risk_mode
        effective_risk_z = self.RISK_MODES.get(effective_risk_mode, self.risk_z)

        # 1. Inbound Authorization Gate: verify version & TTL validity if inbound auth is provided
        inbound_auth = case.get("authorization")
        if inbound_auth is not None:
            curr_v = versions()
            auth_valid = False
            if hasattr(inbound_auth, "is_valid"):
                auth_valid = inbound_auth.is_valid(curr_v["policy_version"], curr_v["model_version"])
            elif isinstance(inbound_auth, dict):
                exp = inbound_auth.get("expires_at")
                if isinstance(exp, str):
                    try:
                        exp = datetime.fromisoformat(exp)
                    except Exception:
                        exp = None
                auth_valid = (
                    bool(inbound_auth.get("authorized", False))
                    and (exp is not None and exp > datetime.now(timezone.utc))
                    and inbound_auth.get("policy_version") == curr_v["policy_version"]
                    and inbound_auth.get("model_version") == curr_v["model_version"]
                )
            if not auth_valid:
                logger.warning(
                    "[AUTH] Inbound authorization invalid or version mismatched for case %s — blocking execution to ESCALATE",
                    case.get("event_id"),
                )
                probs = {a: 0.0 for a in ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"]}
                uncertainty = {a: 0.0 for a in probs}
                incremental = {"WAIT": 0.0, "NUDGE": 0.0, "MANUAL_RECOVERY": 0.0, "ESCALATE": -self.economics.action_cost(case, "ESCALATE")}
                feasibility = self.policy.feasible(case, {a: {"mean": 0.0, "std": 0.0} for a in probs}, False)
                decision = {
                    "event_id": case["event_id"],
                    "case_id": case["event_id"],
                    "amount": float(case.get("amount", 0.0)),
                    "state": case.get("subscription_status"),
                    "recommended_action": "ESCALATE",
                    "recommendation_source": "authorization_guard",
                    "recommendation_reason": "Inbound authorization expired or policy/model version mismatched",
                    "probabilities": probs,
                    "uncertainty": uncertainty,
                    "risk_mode": effective_risk_mode,
                    "risk_z": effective_risk_z,
                    "preview": is_preview,
                    "incremental_values": incremental,
                    "feasible_actions": {a: r.decision for a, r in feasibility.items()},
                    "chosen_action": "ESCALATE",
                    "policy_action": "ESCALATE",
                    "policy_decision": "BLOCKED",
                    "policy_id": "AUTH-VER-001",
                    "policy_reasons": ["Inbound authorization expired or policy/model version mismatched"],
                    "policy_checks": [],
                    "execution_status": "BLOCKED",
                    "recovered_amount": 0.0,
                    "intervention_cost": 10.0,
                    "net_recovered": -10.0,
                    "incremental_realized_value": -10.0,
                    "time_to_recovery": 0.0,
                    "execution_intent_id": None,
                    "approval_id": create_approval_request(
                        case["event_id"],
                        float(case.get("amount", 0.0)),
                        "Inbound authorization expired or policy/model version mismatched",
                        {
                            "case": case,
                            "probabilities": probs,
                            "uncertainty": uncertainty,
                            "chosen_action": "ESCALATE",
                            "policy_reasons": ["Inbound authorization expired or policy/model version mismatched"],
                        },
                    ) if not is_preview else None,
                    "authorization": None,
                    "distribution_shift_flagged": False,
                    "drift_details": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **versions(),
                }
                decision["decision_id"] = stable_hash({"event_id": case["event_id"], "versions": versions(), "action": "ESCALATE"})[:20]
                decision["features"] = {k: v.__dict__ if hasattr(v, "__dict__") else v for k, v in case.items()}
                if not is_preview:
                    self.decision_store.save(decision)
                    self.audit.log(decision)
                return decision

        # 2. Check distribution shift on live cases before model scoring
        if is_live and self.drift_detector is not None:
            drift_res = self.drift_detector.detect_case_drift(case)
            if drift_res.get("drift_detected", False):
                distribution_shift_flagged = True
                drift_details = drift_res
                logger.warning(
                    "[DRIFT] Distribution shift detected for live case %s: %s — routing straight to ESCALATE",
                    case.get("event_id"), drift_res.get("drifted_features"),
                )

        # 2.5 Decline Diagnosis (Deterministic rule table + Groq LLM fallback)
        diagnosis = diagnose(case)
        case["diagnosis"] = diagnosis
        case["decline_class"] = diagnosis.get("decline_class", "soft")

        if distribution_shift_flagged:
            # When out-of-distribution, ML recovery estimates lack empirical support.
            # Fail safe: route directly to ESCALATE for human review.
            probs = {a: 0.0 for a in ["WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE"]}
            uncertainty = {a: 0.0 for a in probs}
            incremental = {"WAIT": 0.0, "NUDGE": 0.0, "MANUAL_RECOVERY": 0.0, "ESCALATE": -self.economics.action_cost(case, "ESCALATE")}
            rec_action = "ESCALATE"
            rec = {
                "action": "ESCALATE",
                "source": "drift_detector",
                "reason": f"Distribution shift detected in features: {list(drift_details.get('drifted_features', {}).keys())}",
            }
            feasibility = self.policy.feasible(case, {a: {"mean": 0.0, "std": 0.0} for a in probs}, bool(case.get("native_retry_scheduled", False)))
            feasible = [a for a, r in feasibility.items() if r.decision == "APPROVED"]
            best_action = "ESCALATE"
        else:
            predictions = self._predictions(case, source)
            probs = {a: float(predictions[a]["mean"]) for a in predictions}
            uncertainty = {a: float(predictions[a].get("std", 0.0)) for a in predictions}
            native_retry_scheduled = bool(case.get("native_retry_scheduled", False))
            feasibility = self.policy.feasible(case, predictions, native_retry_scheduled)
            feasible = [a for a, r in feasibility.items() if r.decision == "APPROVED"]

            incremental = self.economics.rank_incremental(case, probs, uncertainty, effective_risk_z, effective_risk_mode)
            rec = self.agent.decide(case, probs)
            rec_action = rec["action"]

            # Abstain when the best non-WAIT action is not robustly positive.
            candidates = {a: v for a, v in incremental.items() if a in feasible}
            best_action = max(candidates, key=candidates.get) if candidates else "ESCALATE"
            best_value = candidates.get(best_action, float("-inf"))
            if best_action != "WAIT" and best_value <= 0:
                best_action = "WAIT" if "WAIT" in feasible else "ESCALATE"
            if best_action == "MANUAL_RECOVERY" and not self.circuit_breaker.allow_request():
                best_action = "WAIT" if "WAIT" in feasible else "ESCALATE"

        if is_live and not is_preview:
            execution = self._execute_live(case, best_action, feasible)
            # Update best_action if _execute_live downgraded it (e.g. missing creds)
            best_action = execution.action
            execution_status = execution.status
            if best_action in {"MANUAL_RECOVERY", "NUDGE"}:
                final_state = {"state": "PAYMENT_PENDING", "reason": "payment_not_yet_observed"}
            elif best_action == "WAIT":
                final_state = {"state": "NO_ACTION", "reason": "waiting_for_native_retry"}
            elif best_action == "ESCALATE":
                final_state = {"state": "QUEUED", "reason": "queued_for_human_review"}
            else:
                final_state = {"state": "UNKNOWN", "reason": "unknown_action"}
        else:
            # --- Synthetic benchmark path (or preview path) ---
            execution = self.simulator.execute(case, best_action)
            execution_status = "SUCCESS" if execution.success else ("NO_RECOVERY" if best_action in {"WAIT", "ESCALATE"} else "FAILURE")
            final_state = {"state": "CONFIRMED" if execution.success else ("NO_RECOVERY" if best_action in {"WAIT", "ESCALATE"} else "FAILED"), "source": "simulator"}

        # Post-Governor Message Generation for authorized customer-facing actions
        generated_message = None
        if best_action in {"MANUAL_RECOVERY", "NUDGE"}:
            diag_class = case.get("decline_class") or (case.get("diagnosis", {}).get("decline_class") if isinstance(case.get("diagnosis"), dict) else "soft")
            link_url = getattr(execution, "payment_link_url", None) or f"https://rzp.io/rzp/{case.get('event_id', 'pay')}"
            generated_message = generate_message(case, best_action, diag_class, payment_link=link_url)

            # Tone-safety fail closed
            if not generated_message.get("tone_check_passed", True):
                logger.warning(
                    "[TONE_GUARD] Message tone check failed for case %s: %s — routing to ESCALATE",
                    case.get("event_id"), generated_message.get("violations")
                )
                best_action = "ESCALATE"
                if is_live and not is_preview:
                    final_state = {"state": "QUEUED", "reason": "blocked_by_tone_check"}
                    execution_status = "BLOCKED_TONE_CHECK"

        if best_action == "MANUAL_RECOVERY" and not is_preview:
            if is_live:
                self.circuit_breaker.record_success() if execution.status == "EXECUTION_REQUESTED" else self.circuit_breaker.record_failure()
            else:
                self.circuit_breaker.record_success() if execution.success else self.circuit_breaker.record_failure()

        decision_id = stable_hash({"event_id": case["event_id"], "versions": versions(), "action": best_action})[:20]

        authorization = None
        intent_id = None
        if best_action in {"MANUAL_RECOVERY", "NUDGE"} and not is_preview:
            authorization = ExecutionAuthorization.create(
                case["event_id"],
                best_action,
                versions()["policy_version"],
                versions()["model_version"],
                decision_id=decision_id,
            )
            intent_payload = {
                "case": case,
                "authorization": authorization.__dict__,
                "payment_link_id": getattr(execution, "payment_link_id", None),
                "payment_link_url": getattr(execution, "payment_link_url", None),
                "generated_message": generated_message,
            }
            intent_id = enqueue_execution_intent(authorization, intent_payload)
            if is_live:
                from app.execution.outbox import mark_intent_status
                mark_intent_status(
                    intent_id,
                    execution.status,
                    {
                        "status": execution.status,
                        "payment_link_id": getattr(execution, "payment_link_id", None),
                        "payment_link_url": getattr(execution, "payment_link_url", None),
                        "final_state": final_state,
                    },
                )

        if is_live and not is_preview:
            wait_net = 0.0  # No simulator counterfactual for live cases
        else:
            wait_exec = self.simulator.execute(case, "WAIT") if best_action != "WAIT" else None
            wait_net = (wait_exec.recovered_amount - wait_exec.cost) if wait_exec else 0.0
        net = execution.recovered_amount - execution.cost

        approval_id = None
        if best_action == "ESCALATE" and not is_preview:
            reasons_list = []
            if rec_action in feasibility and feasibility[rec_action].decision == "BLOCKED":
                reasons_list.extend(feasibility[rec_action].reasons)
            for a, r in feasibility.items():
                if r.decision == "BLOCKED" and r.reasons:
                    for re in r.reasons:
                        if re not in reasons_list:
                            reasons_list.append(re)
            if not reasons_list and rec.get("reason"):
                reasons_list = [rec["reason"]]
            escalation_reason = "; ".join(reasons_list) if reasons_list else "Policy gate routed to ESCALATE"

            escalation_payload = {
                "case": case,
                "probabilities": probs,
                "uncertainty": uncertainty,
                "chosen_action": best_action,
                "recommended_action": rec_action,
                "policy_reasons": reasons_list,
                "feasible_actions": {a: r.decision for a, r in feasibility.items()},
                "incremental_values": incremental,
            }
            approval_id = create_approval_request(
                case_id=case["event_id"],
                amount=float(case.get("amount", 0.0)),
                reason=escalation_reason,
                payload=escalation_payload,
            )

        execution_res_dict = {
            "status": execution.status if is_live else ("SUCCESS" if execution.success else "FAILURE"),
            "action": best_action,
            "payment_link_id": getattr(execution, "payment_link_id", None),
            "payment_link_url": getattr(execution, "payment_link_url", None),
            "provider": getattr(execution, "provider", "razorpay" if is_live else "simulator"),
            "provider_response": getattr(execution, "provider_response", None),
            "detail": getattr(execution, "detail", ""),
        }

        decision = {
            "event_id": case["event_id"],
            "case_id": case["event_id"],
            "amount": float(case.get("amount", 0.0)),
            "state": case.get("subscription_status"),
            "recommended_action": rec_action,
            "recommendation_source": rec["source"],
            "recommendation_reason": rec["reason"],
            "probabilities": probs,
            "uncertainty": uncertainty,
            "risk_mode": effective_risk_mode,
            "risk_z": effective_risk_z,
            "preview": is_preview,
            "incremental_values": incremental,
            "feasible_actions": {a: r.decision for a, r in feasibility.items()},
            "chosen_action": best_action,
            "policy_action": best_action,
            "policy_decision": "BLOCKED" if (best_action != rec_action and rec_action in feasibility and feasibility[rec_action].decision == "BLOCKED") else (feasibility[best_action].decision if best_action in feasibility else "APPROVED"),
            "policy_id": (feasibility[rec_action].policy_id if (best_action != rec_action and rec_action in feasibility and feasibility[rec_action].decision == "BLOCKED") else (feasibility[best_action].policy_id if best_action in feasibility else "P-APPROVE")),
            "policy_reasons": (feasibility[rec_action].reasons if (best_action != rec_action and rec_action in feasibility and feasibility[rec_action].reasons) else (feasibility[best_action].reasons if best_action in feasibility else [])),
            "policy_checks": ([c.__dict__ for c in feasibility[rec_action].checks] if (best_action != rec_action and rec_action in feasibility and feasibility[rec_action].checks) else ([c.__dict__ for c in feasibility[best_action].checks] if best_action in feasibility else [])),
            "blocked_reasons": {a: feasibility[a].reasons for a in feasibility if feasibility[a].reasons},
            "all_policy_checks": {a: [c.__dict__ for c in feasibility[a].checks] for a in feasibility},
            "execution_status": execution_status,
            "execution_result": execution_res_dict,
            "final_state": final_state,
            "payment_link_id": getattr(execution, "payment_link_id", None),
            "payment_link_url": getattr(execution, "payment_link_url", None),
            "recovered_amount": execution.recovered_amount,
            "intervention_cost": execution.cost,
            "net_recovered": net,
            "incremental_realized_value": net - wait_net,
            "time_to_recovery": execution.time_to_recovery,
            "execution_detail": getattr(execution, "detail", ""),
            "execution_intent_id": intent_id,
            "approval_id": approval_id,
            "authorization": authorization.__dict__ if authorization else None,
            "distribution_shift_flagged": distribution_shift_flagged,
            "drift_details": drift_details,
            "diagnosis": diagnosis,
            "generated_message": generated_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **versions(),
        }
        decision["decision_id"] = stable_hash({"event_id": case["event_id"], "versions": versions(), "action": best_action})[:20]
        decision["features"] = dict(case)
        if not is_preview:
            self.decision_store.save(decision)
            self.audit.log(decision)
        return decision

    def _execute_live(self, case: dict, best_action: str, feasible: list) -> "ExecutionResult":
        """Execute a live (webhook-driven) case through real Razorpay API.

        Fail-closed behavior:
        - Missing credentials → ESCALATE
        - NotImplementedError (e.g. NUDGE not wired) → WAIT
        - RazorpayAPIError → ESCALATE
        """
        from app.execution.simulator import ExecutionResult

        if not self.live_executor.credentials_available:
            logger.error(
                "[LIVE] Razorpay credentials missing for case %s — "
                "failing closed to ESCALATE (not falling back to simulator)",
                case.get("event_id"),
            )
            return ExecutionResult(
                success=False, recovered_amount=0.0, cost=10.0,
                action="ESCALATE",
                detail="live: credentials missing, failed closed to ESCALATE",
                probability=0.0, time_to_recovery=0.0,
            )

        try:
            return self.live_executor.execute(case, best_action)
        except NotImplementedError as exc:
            logger.warning(
                "[LIVE] Action %s not wired for live execution (%s) — "
                "falling back to WAIT for case %s",
                best_action, exc, case.get("event_id"),
            )
            fallback = "WAIT" if "WAIT" in feasible else "ESCALATE"
            return ExecutionResult(
                success=False, recovered_amount=0.0, cost=0.0,
                action=fallback,
                detail=f"live: {best_action} not yet wired, fell back to {fallback}",
                probability=0.0, time_to_recovery=0.0,
            )
        except RazorpayAPIError as exc:
            logger.error(
                "[LIVE] Razorpay API error for case %s action %s: %s — "
                "failing closed to ESCALATE",
                case.get("event_id"), best_action, exc,
            )
            return ExecutionResult(
                success=False, recovered_amount=0.0, cost=10.0,
                action="ESCALATE",
                detail=f"live: Razorpay API error, failed closed to ESCALATE: {exc}",
                probability=0.0, time_to_recovery=0.0,
            )
