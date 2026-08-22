from app.execution.simulator import SubscriptionSimulator
from app.pipeline import RecoveryPipeline


def test_pipeline_prefers_best_feasible_action_over_blocked_recommendation():
    sim = SubscriptionSimulator(42)
    pipeline = RecoveryPipeline(simulator=sim, model=None)
    case = {
        "event_id": "EVT-POLICY-1",
        "amount": 4999,
        "attempt_number": 4,
        "failure_source": "customer",
        "failure_reason": "card_expired",
        "subscription_status": "halted",
        "payment_method_type": "international_card",
        "invoice_status": "issued",
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "previous_success_rate": 0.5,
        "previous_recovery_rate": 0.7,
        "customer_tenure_days": 500,
        "payment_method_age_days": 30,
        "nudge_incentive_cost": 0,
        "manual_recovery_ops_cost": 2,
    }
    result = pipeline.process(case, source="sim")
    assert result["policy_action"] in {"NUDGE", "WAIT", "ESCALATE"}
    assert "MANUAL_RECOVERY" in result["feasible_actions"]
