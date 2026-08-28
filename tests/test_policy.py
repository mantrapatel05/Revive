from datetime import datetime, timezone, timedelta
from app.policy.gate import PolicyGate, check_quiet_hours, check_daily_contact_cap, IST_TIMEZONE


def base(**kw):
    x = {
        "subscription_status": "pending",
        "amount": 1999,
        "customer_opted_out": False,
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "native_retry_scheduled": True,
        "contacted_today": False,
    }
    x.update(kw)
    return x


def test_wait_allowed():
    r = PolicyGate().evaluate(base(), "WAIT", 0.5, True)
    assert r.decision == "APPROVED" and r.action == "WAIT"


def test_manual_blocked_when_native_retry_scheduled():
    r = PolicyGate().evaluate(base(), "MANUAL_RECOVERY", 0.8, True)
    assert r.decision == "BLOCKED" and r.action == "WAIT"


def test_domestic_card_manual_blocked():
    r = PolicyGate().evaluate(base(payment_method_type="domestic_card", native_retry_scheduled=False), "MANUAL_RECOVERY", 0.8, False)
    assert r.decision == "BLOCKED"


def test_high_amount_escalates():
    r = PolicyGate().evaluate(base(amount=9000, native_retry_scheduled=False), "MANUAL_RECOVERY", 0.8, False)
    assert r.decision == "BLOCKED" and r.action == "ESCALATE"


def test_quiet_hours_blocks_customer_facing_at_2000_ist():
    # 20:00 IST is outside 08:00–19:00 IST
    t_2000 = datetime(2026, 8, 28, 20, 0, 0, tzinfo=IST_TIMEZONE)

    ok_nudge, reason_nudge = check_quiet_hours("NUDGE", t_2000)
    assert not ok_nudge
    assert reason_nudge == "outside_quiet_hours"

    ok_manual, reason_manual = check_quiet_hours("MANUAL_RECOVERY", t_2000)
    assert not ok_manual
    assert reason_manual == "outside_quiet_hours"

    case = base(native_retry_scheduled=False)
    res_nudge = PolicyGate().evaluate_action(case, "NUDGE", 0.8, False, current_time=t_2000)
    assert res_nudge.decision == "BLOCKED"
    assert "outside_quiet_hours" in res_nudge.hard_failures

    res_manual = PolicyGate().evaluate_action(case, "MANUAL_RECOVERY", 0.8, False, current_time=t_2000)
    assert res_manual.decision == "BLOCKED"
    assert "outside_quiet_hours" in res_manual.hard_failures


def test_quiet_hours_allows_customer_facing_during_permitted_window():
    # 12:00 IST is inside 08:00–19:00 IST
    t_1200 = datetime(2026, 8, 28, 12, 0, 0, tzinfo=IST_TIMEZONE)

    ok_nudge, reason_nudge = check_quiet_hours("NUDGE", t_1200)
    assert ok_nudge
    assert reason_nudge is None

    ok_manual, reason_manual = check_quiet_hours("MANUAL_RECOVERY", t_1200)
    assert ok_manual
    assert reason_manual is None


def test_daily_contact_cap_blocks_same_day_repeat_contact():
    case_contacted = base(contacted_today=True, native_retry_scheduled=False)

    ok_nudge, reason_nudge = check_daily_contact_cap(case_contacted, "NUDGE")
    assert not ok_nudge
    assert reason_nudge == "daily_contact_cap"

    ok_manual, reason_manual = check_daily_contact_cap(case_contacted, "MANUAL_RECOVERY")
    assert not ok_manual
    assert reason_manual == "daily_contact_cap"

    res_nudge = PolicyGate().evaluate_action(case_contacted, "NUDGE", 0.8, False)
    assert res_nudge.decision == "BLOCKED"
    assert "daily_contact_cap" in res_nudge.hard_failures

    res_manual = PolicyGate().evaluate_action(case_contacted, "MANUAL_RECOVERY", 0.8, False)
    assert res_manual.decision == "BLOCKED"
    assert "daily_contact_cap" in res_manual.hard_failures


def test_wait_never_blocked_by_quiet_hours_or_daily_cap():
    t_2000 = datetime(2026, 8, 28, 20, 0, 0, tzinfo=IST_TIMEZONE)
    case = base(contacted_today=True, subscription_status="pending", native_retry_scheduled=True)

    # Pure functions
    ok_quiet, reason_quiet = check_quiet_hours("WAIT", t_2000)
    assert ok_quiet
    assert reason_quiet is None

    ok_cap, reason_cap = check_daily_contact_cap(case, "WAIT")
    assert ok_cap
    assert reason_cap is None

    # Gate evaluation
    res_wait = PolicyGate().evaluate_action(case, "WAIT", 0.5, True, current_time=t_2000)
    assert res_wait.decision == "APPROVED"
    assert res_wait.action == "WAIT"
    assert len(res_wait.hard_failures) == 0

    # ESCALATE is also never blocked
    ok_esc_quiet, _ = check_quiet_hours("ESCALATE", t_2000)
    assert ok_esc_quiet
    ok_esc_cap, _ = check_daily_contact_cap(case, "ESCALATE")
    assert ok_esc_cap


def test_coexistence_with_7d_fatigue_penalty():
    # 7-day fatigue count > 2 is a soft penalty, while daily cap is a hard stop
    case_fatigue = base(contact_count_7d=3, contacted_today=False, native_retry_scheduled=False)
    res = PolicyGate().evaluate_action(case_fatigue, "NUDGE", 0.8, False)
    assert res.decision == "APPROVED"
    assert any("7-day budget" in s for s in res.soft_penalties)
    assert len(res.hard_failures) == 0

    # Both present: hard failure blocks, soft penalty recorded
    case_both = base(contact_count_7d=3, contacted_today=True, native_retry_scheduled=False)
    res_both = PolicyGate().evaluate_action(case_both, "NUDGE", 0.8, False)
    assert res_both.decision == "BLOCKED"
    assert "daily_contact_cap" in res_both.hard_failures
    assert any("7-day budget" in s for s in res_both.soft_penalties)
