import pytest
from unittest.mock import MagicMock, patch
from app.messaging import generate_message, check_tone, TEMPLATE_INTENTS
from app.pipeline import RecoveryPipeline
from app.execution.simulator import SubscriptionSimulator


def test_deterministic_template_selection():
    case = {"customer_name": "Aarav Sharma", "amount": 2499.0}
    link = "https://rzp.io/rzp/plink_12345"

    # Soft decline nudge -> payment_retry_link
    msg_soft = generate_message(case, "NUDGE", "soft", payment_link=link)
    assert msg_soft["template_intent"] == "payment_retry_link"
    assert "₹2,499.00" in msg_soft["content"]
    assert link in msg_soft["content"]
    assert msg_soft["tone_check_passed"] is True
    assert msg_soft["status"] == "APPROVED_FOR_SEND"

    # Hard decline nudge -> card_expired_reminder
    msg_hard = generate_message(case, "NUDGE", "hard", payment_link=link)
    assert msg_hard["template_intent"] == "card_expired_reminder"
    assert "card on file has expired" in msg_hard["content"]
    assert msg_hard["tone_check_passed"] is True


def test_tone_check_blocks_coercive_language():
    # Coercive words must fail tone check
    coercive_msg_1 = "You must pay immediately or face legal action."
    ok1, violations1 = check_tone(coercive_msg_1)
    assert ok1 is False
    assert any("must" in v for v in violations1)
    assert any("immediately" in v for v in violations1)
    assert any("legal action" in v for v in violations1)

    coercive_msg_2 = "Final warning: your subscription has defaulted."
    ok2, violations2 = check_tone(coercive_msg_2)
    assert ok2 is False
    assert any("final warning" in v for v in violations2)


def test_tone_check_blocks_exceeding_two_sentences():
    three_sentence_msg = "Hello Priya. Your renewal is pending. Please click here to pay."
    ok, violations = check_tone(three_sentence_msg)
    assert ok is False
    assert any("Exceeds maximum allowable sentence length" in v for v in violations)


def test_polite_two_sentence_message_passes():
    good_msg = "Hi Rahul, your subscription renewal of ₹1,499.00 experienced a temporary delay. You can complete your renewal here: https://rzp.io/rzp/demo."
    ok, violations = check_tone(good_msg)
    assert ok is True
    assert len(violations) == 0


def test_tone_check_failure_fails_closed_in_pipeline(monkeypatch):
    """If generated message fails tone safety check, pipeline must fail closed to ESCALATE without sending."""
    sim = SubscriptionSimulator(42)
    pipeline = RecoveryPipeline(simulator=sim)

    # Monkeypatch generate_message to simulate a coercive LLM output
    bad_msg = {
        "timestamp": "2026-08-28T20:00:00Z",
        "channel": "whatsapp",
        "action": "NUDGE",
        "template_intent": "payment_retry_link",
        "content": "You must pay immediately or your account will be penalized and terminated.",
        "source": "llm",
        "tone_check_passed": False,
        "violations": ["Prohibited coercive keyword: 'must'", "Prohibited coercive keyword: 'immediately'"],
        "status": "BLOCKED_TONE_CHECK",
    }
    monkeypatch.setattr("app.pipeline.generate_message", lambda *args, **kwargs: bad_msg)

    case = {
        "event_id": "EVT-TONE-FAIL-01",
        "amount": 1999.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "current_time": "2026-08-28T12:00:00+05:30",
    }

    decision = pipeline.process(case, is_preview=True)
    # The action must be downgraded to ESCALATE
    assert decision["chosen_action"] == "ESCALATE"
    assert decision["generated_message"]["status"] == "BLOCKED_TONE_CHECK"
    assert decision["generated_message"]["tone_check_passed"] is False


def test_audit_logs_message_metadata():
    case = {"customer_name": "Vikram Mehta", "amount": 4999.0}
    msg = generate_message(case, "MANUAL_RECOVERY", "soft", payment_link="https://rzp.io/rzp/vikram_pay", channel="whatsapp")
    assert "timestamp" in msg
    assert msg["channel"] == "whatsapp"
    assert msg["action"] == "MANUAL_RECOVERY"
    assert msg["status"] == "APPROVED_FOR_SEND"
    assert "Vikram Mehta" in msg["content"]
    assert "https://rzp.io/rzp/vikram_pay" in msg["content"]


def test_llm_message_pydantic_validation_fails_closed(monkeypatch):
    """When LLM returns malformed JSON or schema violation, generate_message must fail closed to tone_check_passed=False."""
    import app.messaging as messaging
    monkeypatch.setattr(messaging, "GROQ_API_KEY", "mock_key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    # Missing required 'customer_name' and 'intent'
                    "content": '{"message": "Hi"}'
                }
            }
        ]
    }
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: mock_resp)

    case = {"customer_name": "Deepak Roy", "amount": 2499.0}
    msg = generate_message(case, "NUDGE", "soft", payment_link="https://rzp.io/rzp/demo")
    assert msg["tone_check_passed"] is False
    assert msg["source"] == "llm_failed"
    assert msg["status"] == "BLOCKED_TONE_CHECK"
    assert any("schema validation failed" in v for v in msg["violations"])
