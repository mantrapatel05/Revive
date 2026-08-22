from dataclasses import dataclass
from math import exp
from typing import Optional

@dataclass(frozen=True)
class MerchantConfig:
    risk_mode: str = "BALANCED"
    max_auto_action_amount: float = 3000.0
    max_customer_nudges_7d: int = 2
    allow_manual_recovery: bool = True
    require_human_above: float = 10000.0
    customer_fatigue_penalty: float = 50.0
    churn_penalty: float = 100.0
    support_cost_per_escalation: float = 20.0

@dataclass(frozen=True)
class ActionCosts:
    WAIT: float = 0.0
    NUDGE: float = 5.0
    MANUAL_RECOVERY: float = 2.0
    ESCALATE: float = 10.0

class EconomicsEngine:
    ACTIONS = ("WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE")

    def __init__(self, costs: Optional[ActionCosts] = None, merchant_config: Optional[MerchantConfig] = None):
        self.costs = costs or ActionCosts()
        self.merchant = merchant_config or MerchantConfig()
        self.risk_z = {"CONSERVATIVE": 2.0, "BALANCED": 1.0, "AGGRESSIVE": 0.0}.get(self.merchant.risk_mode, 1.0)

    def action_cost(self, case: dict, action: str) -> float:
        base = float(getattr(self.costs, action))
        if action == "NUDGE": base += float(case.get("nudge_incentive_cost", 0.0))
        elif action == "MANUAL_RECOVERY": base += float(case.get("manual_recovery_ops_cost", 0.0))
        elif action == "ESCALATE": base += float(case.get("escalation_ops_cost", 0.0)) + self.merchant.support_cost_per_escalation
        return base

    def time_discount(self, days: float, annual_rate: float = 0.10) -> float:
        return exp(-annual_rate * max(0.0, float(days)) / 365.0)

    def expected_days(self, case: dict, action: str) -> float:
        if action == "WAIT": return float(case.get("wait_expected_days", 0.0))
        if action == "NUDGE": return float(case.get("nudge_expected_days", 0.0))
        if action == "MANUAL_RECOVERY": return float(case.get("manual_expected_days", 0.0))
        return 0.0

    def expected_net_value(self, case: dict, action: str, probability: float, expected_days: float = 0.0) -> float:
        amount = float(case.get("amount", 0.0))
        return probability * amount * self.time_discount(expected_days) - self.action_cost(case, action)

    def incremental_net_value(self, case: dict, action: str, action_probability: float,
                              wait_probability: float, expected_days: float = 0.0,
                              risk_penalty: float = 0.0) -> float:
        if action == "WAIT": return 0.0
        amount = float(case.get("amount", 0.0))
        intervention = action_probability * amount * self.time_discount(expected_days)
        control = wait_probability * amount * self.time_discount(float(case.get("wait_expected_days", 0.0)))
        fatigue = 0.0
        count = int(case.get("contact_count_7d", 0))
        if action in {"NUDGE", "MANUAL_RECOVERY"} and count > self.merchant.max_customer_nudges_7d:
            fatigue = self.merchant.customer_fatigue_penalty * (count - self.merchant.max_customer_nudges_7d)
        churn = self.merchant.churn_penalty if action in {"NUDGE", "MANUAL_RECOVERY"} and self.merchant.risk_mode == "AGGRESSIVE" else 0.0
        return intervention - control - self.action_cost(case, action) - fatigue - churn - risk_penalty

    def rank_incremental(self, case: dict, probabilities: dict, uncertainty: dict | None = None, risk_z: float | None = None) -> dict[str, float]:
        wait = float(probabilities.get("WAIT", 0.0))
        uncertainty = uncertainty or {}
        z = self.risk_z if risk_z is None else float(risk_z)
        values = {"WAIT": 0.0}
        for action in ["NUDGE", "MANUAL_RECOVERY"]:
            p = max(0.0, float(probabilities.get(action, 0.0)) - z * float(uncertainty.get(action, 0.0)))
            values[action] = self.incremental_net_value(case, action, p, wait, expected_days=float(case.get("nudge_expected_days", 0.0)) if action == "NUDGE" else float(case.get("manual_expected_days", 0.0)))
        values["ESCALATE"] = -self.action_cost(case, "ESCALATE")
        return values
