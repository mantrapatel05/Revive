from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PolicyCheck:
    check_id: str
    description: str
    passed: bool
    is_hard: bool
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyResult:
    decision: str
    action: Optional[str]
    checks: List[PolicyCheck]
    hard_failures: List[str]
    soft_penalties: List[str]
    policy_id: str

    @property
    def reasons(self) -> List[str]:
        return self.hard_failures + self.soft_penalties


class PolicyGate:
    """Deterministic authorization boundary; it never executes money actions."""

    def __init__(self, max_auto_action_amount: float = 3000.0, min_recovery_probability: float = 0.20,
                 require_human_above: float = 10000.0, max_customer_nudges_7d: int = 2):
        self.max_auto_action_amount = float(max_auto_action_amount)
        self.min_recovery_probability = float(min_recovery_probability)
        self.require_human_above = float(require_human_above)
        self.max_customer_nudges_7d = int(max_customer_nudges_7d)

    @classmethod
    def from_merchant_config(cls, config: Any) -> "PolicyGate":
        return cls(
            max_auto_action_amount=float(getattr(config, 'max_auto_action_amount', 3000.0)),
            require_human_above=float(getattr(config, 'require_human_above', 10000.0)),
            max_customer_nudges_7d=int(getattr(config, 'max_customer_nudges_7d', 2))
        )

    def evaluate_action(self, case: Dict[str, Any], action: str, probability_mean: float,
                        native_retry_scheduled: bool = False) -> PolicyResult:
        checks: List[PolicyCheck] = []
        hard: List[str] = []
        soft: List[str] = []

        state = case.get("subscription_status", "unknown")
        state_ok = state in {"pending", "halted"}
        checks.append(PolicyCheck("SUB-STATE-001", "Subscription state is recoverable", state_ok, True, {"state": state}))
        if not state_ok:
            hard.append("Subscription state is not eligible")

        if action == "WAIT":
            wait_ok = state == "pending"
            checks.append(PolicyCheck("WAIT-STATE-001", "Native retry exists for pending subscriptions", wait_ok, True, {"state": state}))
            if not wait_ok:
                hard.append("Native retry is not available in halted state")

        if action in {"NUDGE", "MANUAL_RECOVERY"}:
            opted_out = bool(case.get("customer_opted_out", False))
            checks.append(PolicyCheck("CUST-OPT-001", "Customer has not opted out", not opted_out, True, {"opted_out": opted_out}))
            if opted_out:
                hard.append("Customer opted out")
            amount = float(case.get("amount", 0.0))
            ceiling = min(self.max_auto_action_amount, self.require_human_above)
            amount_ok = amount <= ceiling
            checks.append(PolicyCheck("FIN-AUTO-002", "Amount within automatic action ceiling", amount_ok, True, {"amount": amount, "limit": ceiling}))
            if not amount_ok:
                if amount > self.require_human_above:
                    hard.append(f"Amount exceeds human approval threshold (₹{self.require_human_above:,.0f})")
                else:
                    hard.append("Amount exceeds automatic action ceiling")

        if action == "MANUAL_RECOVERY":
            attempt = int(case.get("attempt_number", 0))
            retry_ok = attempt < 4
            checks.append(PolicyCheck("RET-LIMIT-001", "Manual recovery attempt budget available", retry_ok, True, {"attempt": attempt, "max": 4}))
            if not retry_ok:
                hard.append("Manual recovery attempt budget exhausted")
            invoice_ok = case.get("invoice_status") == "issued"
            checks.append(PolicyCheck("INV-ELIG-001", "Invoice is issued and chargeable", invoice_ok, True, {"invoice_status": case.get("invoice_status")}))
            if not invoice_ok:
                hard.append("Invoice is not in issued state")
            domestic_card = case.get("payment_method_type") == "domestic_card"
            card_ok = not domestic_card
            checks.append(PolicyCheck("PM-ELIG-001", "Payment method supports manual charge path", card_ok, True, {"payment_method_type": case.get("payment_method_type")}))
            if not card_ok:
                hard.append("Manual charging a domestic card is unsupported")
            duplicate_ok = not native_retry_scheduled
            checks.append(PolicyCheck("DUP-NATIVE-001", "No conflicting native retry is scheduled", duplicate_ok, True, {"native_retry_scheduled": native_retry_scheduled}))
            if not duplicate_ok:
                hard.append("Native retry is already scheduled")
            prob_ok = float(probability_mean) >= self.min_recovery_probability
            checks.append(PolicyCheck("PROB-MIN-001", "Recovery probability exceeds minimum", prob_ok, True, {"probability": probability_mean, "threshold": self.min_recovery_probability}))
            if not prob_ok:
                hard.append("Estimated recovery probability is below automation threshold")

        if int(case.get("contact_count_7d", 0)) > self.max_customer_nudges_7d and action in {"NUDGE", "MANUAL_RECOVERY"}:
            soft.append(f"Contact frequency exceeds 7-day budget ({self.max_customer_nudges_7d} touches)")

        if hard:
            return PolicyResult("BLOCKED", None, checks, hard, soft, "P-BLOCK")
        return PolicyResult("APPROVED", action, checks, hard, soft, "P-APPROVE")

    def feasible(self, case: Dict[str, Any], predictions: Dict[str, Dict[str, Any]], native_retry_scheduled: bool = False) -> Dict[str, PolicyResult]:
        out: Dict[str, PolicyResult] = {}
        for action in ["WAIT", "NUDGE", "MANUAL_RECOVERY"]:
            raw = predictions.get(action, {})
            prob = float(raw.get("mean", 0.0)) if isinstance(raw, dict) else float(raw)
            out[action] = self.evaluate_action(case, action, prob, native_retry_scheduled)
        # ESCALATE is always a valid safety outcome.
        out["ESCALATE"] = PolicyResult("APPROVED", "ESCALATE", [], [], [], "P-ALWAYS-ALLOWED")
        return out

    def evaluate(self, case: Dict[str, Any], action: str, probability: float, native_retry_scheduled: bool = False) -> PolicyResult:
        result = self.evaluate_action(case, action, float(probability), native_retry_scheduled)
        if result.decision == "APPROVED":
            return result
        fallback = "WAIT" if case.get("subscription_status") == "pending" and native_retry_scheduled else "ESCALATE"
        return PolicyResult("BLOCKED", fallback, result.checks, result.hard_failures, result.soft_penalties, result.policy_id)
