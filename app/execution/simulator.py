from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any

from app.economics import EconomicsEngine


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    recovered_amount: float
    cost: float
    action: str
    detail: str
    probability: float
    time_to_recovery: float


class SubscriptionSimulator:
    ACTIONS = ("WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE")

    def __init__(self, seed: int = 42):
        self.seed = int(seed)
        self.economics = EconomicsEngine()

    def _rng(self, *parts: Any) -> random.Random:
        material = "|".join(map(str, (self.seed, *parts))).encode()
        digest = hashlib.sha256(material).hexdigest()
        return random.Random(int(digest[:16], 16))

    def latent_state(self, case: dict) -> dict[str, float]:
        rng = self._rng("latent", case["event_id"])
        sr = float(case.get("previous_success_rate", 0.5))
        rr = float(case.get("previous_recovery_rate", 0.2))
        tenure = min(1.0, float(case.get("customer_tenure_days", 180)) / 1000.0)
        return {
            "liquidity": min(0.99, max(0.01, rng.betavariate(2 + 2 * sr, 2 + 2 * (1 - rr)))),
            "pm_health": min(0.99, max(0.01, rng.betavariate(2.5 + min(2.0, float(case.get("payment_method_age_days", 30)) / 180), 2.5 + 0.5 * float(case.get("attempt_number", 1))))),
            "responsiveness": min(0.99, max(0.01, rng.betavariate(2 + 2 * rr + tenure, 2 + (1 - tenure)))),
        }

    def probability(self, case: dict, action: str, latent: dict | None = None) -> float:
        latent = latent or self.latent_state(case)
        source = case.get("failure_source", "unknown")
        reason = case.get("failure_reason", "unknown")
        attempt = int(case.get("attempt_number", 1))
        amount = float(case.get("amount", 0.0))
        state = case.get("subscription_status", "pending")
        if action == "ESCALATE":
            return 0.0
        if action == "WAIT" and state != "pending":
            return 0.0
        if state not in {"pending", "halted"}:
            return 0.0

        if action == "WAIT":
            if source in {"gateway", "network"}:
                base = 0.72
            elif reason == "insufficient_funds":
                base = 0.36 if attempt <= 2 else 0.14
            else:
                base = 0.08
            base *= max(0.45, 1 - 0.10 * (attempt - 1))
            p = base * (0.65 + 0.35 * latent["liquidity"]) * (0.70 + 0.30 * latent["pm_health"])
        elif action == "NUDGE":
            base = 0.65 if reason == "card_expired" else 0.30
            p = base * (0.50 + 0.50 * latent["responsiveness"]) * (0.50 + 0.50 * latent["pm_health"])
        elif action == "MANUAL_RECOVERY":
            if reason == "card_expired":
                base = 0.05
            elif source in {"gateway", "network"}:
                base = 0.80
            elif reason == "insufficient_funds":
                base = 0.60 if attempt <= 2 else 0.30
            else:
                base = 0.20
            p = base * (0.70 + 0.30 * latent["liquidity"])
        else:
            p = 0.0

        if amount > 5000:
            p *= 0.90
        p *= max(0.50, 1 - 0.10 * (attempt - 1))
        return max(0.0, min(0.95, p))

    def _action_cost(self, action: str, case: dict) -> float:
        return self.economics.action_cost(case, action)

    def _time_to_recovery(self, case: dict, action: str) -> float:
        if action == "WAIT":
            return float(self._rng("delay", case["event_id"], action).choice([1, 2, 3]))
        if action == "NUDGE":
            return float(self._rng("delay", case["event_id"], action).choice([1, 2]))
        if action == "MANUAL_RECOVERY":
            return 0.0
        return 0.0

    def execute(self, case: dict, action: str, forced_probability: float | None = None) -> ExecutionResult:
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        latent = self.latent_state(case)
        p = self.probability(case, action, latent) if forced_probability is None else float(forced_probability)
        rng = self._rng("outcome", case["event_id"], action, int(case.get("attempt_number", 1)))
        success = rng.random() < p
        amount = float(case.get("amount", 0.0))
        cost = self._action_cost(action, case)
        recovered = amount if success else 0.0
        days = self._time_to_recovery(case, action) if success else 0.0
        if action == "ESCALATE":
            return ExecutionResult(False, 0.0, cost, action, "queued for human review", p, 0.0)
        return ExecutionResult(success, recovered, cost, action, "recovered" if success else "not recovered", p, days)

    def get_true_probability(self, case: dict, action: str) -> float:
        return self.probability(case, action, self.latent_state(case))

    def get_counterfactuals(self, case: dict) -> dict[str, ExecutionResult]:
        return {action: self.execute(case, action) for action in self.ACTIONS}

    def oracle_action(self, case: dict):
        values = self.expected_values(case)
        action = max(values, key=values.get)
        return action, values[action], values

    def expected_values(self, case: dict) -> dict[str, float]:
        return {
            a: self.economics.expected_net_value(
                case,
                a,
                self.get_true_probability(case, a),
                self._time_to_recovery(case, a),
            ) for a in self.ACTIONS
        }
