from app.economics import EconomicsEngine


def test_wait_is_zero_incremental_value():
    e = EconomicsEngine()
    case = {"amount": 2000, "nudge_incentive_cost": 0, "manual_recovery_ops_cost": 0}
    probs = {"WAIT": 0.7, "NUDGE": 0.8, "MANUAL_RECOVERY": 0.9}
    values = e.rank_incremental(case, probs)
    assert values["WAIT"] == 0
    assert abs(values["NUDGE"] - 195) < 1e-9
    assert abs(values["MANUAL_RECOVERY"] - 398) < 1e-9


def test_intervention_with_lower_probability_is_not_worth_it():
    e = EconomicsEngine()
    case = {"amount": 1000, "nudge_incentive_cost": 0}
    probs = {"WAIT": 0.8, "NUDGE": 0.7, "MANUAL_RECOVERY": 0.79}
    values = e.rank_incremental(case, probs)
    assert values["NUDGE"] < 0
    assert values["MANUAL_RECOVERY"] < 0
