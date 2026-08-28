import json
from unittest.mock import MagicMock, patch
import pytest
from app.diagnosis import diagnose, DECLINE_RULES, normalize_reason, LLMDiagnosisOutput
from app.pipeline import RecoveryPipeline
from app.execution.simulator import SubscriptionSimulator


def test_normalize_reason():
    assert normalize_reason(" Insufficient Funds ") == "insufficient_funds"
    assert normalize_reason("CARD-EXPIRED") == "card_expired"
    assert normalize_reason("Issuer Suspected Fraud") == "issuer_suspected_fraud"


def test_deterministic_rule_diagnosis_soft():
    event = {"failure_reason": "insufficient_funds", "failure_source": "customer"}
    diag = diagnose(event)
    assert diag["source"] == "rule"
    assert diag["decline_class"] == "soft"
    assert diag["confidence"] == 1.0
    assert "insufficient_funds" in diag["reason"]


def test_deterministic_rule_diagnosis_hard():
    event = {"failure_reason": "card_expired", "failure_source": "customer"}
    diag = diagnose(event)
    assert diag["source"] == "rule"
    assert diag["decline_class"] == "hard"
    assert diag["confidence"] == 1.0


def test_deterministic_rule_diagnosis_risk():
    event = {"error_code": "issuer_suspected_fraud", "failure_source": "bank"}
    diag = diagnose(event)
    assert diag["source"] == "rule"
    assert diag["decline_class"] == "risk"
    assert diag["confidence"] == 1.0


def test_unfamiliar_code_llm_fallback_success(monkeypatch):
    """Test unfamiliar bank decline code invoking Groq LLM with valid Pydantic response."""
    monkeypatch.setattr("app.diagnosis.GROQ_API_KEY", "mock-groq-key")

    mock_llm_json = {
        "decline_class": "soft_decline",
        "confidence": 0.85,
        "reasoning": "Special bank code 91 indicates temporary switch outage, classified as soft decline."
    }
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(mock_llm_json)}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response) as mock_post:
        event = {"failure_reason": "custom_hdfc_switch_timeout_code_91", "failure_source": "bank"}
        diag = diagnose(event)
        assert mock_post.called
        assert diag["source"] == "llm"
        assert diag["decline_class"] == "soft"
        assert diag["confidence"] == 0.85
        assert "Special bank code 91" in diag["reasoning"]


def test_llm_validation_failure_fails_closed(monkeypatch):
    """Test that malformed/invalid LLM output fails closed (unclear, confidence 0.0, source llm_failed) without retrying."""
    monkeypatch.setattr("app.diagnosis.GROQ_API_KEY", "mock-groq-key")

    # Invented category that violates the 4-category Pydantic schema
    mock_llm_json = {
        "decline_class": "maybe_recoverable_invented_category",
        "confidence": 0.99,
        "reasoning": "Invented category should fail schema validation"
    }
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": json.dumps(mock_llm_json)}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response):
        event = {"failure_reason": "weird_unknown_bank_code_xyz", "failure_source": "bank"}
        diag = diagnose(event)
        assert diag["source"] == "llm_failed"
        assert diag["decline_class"] == "unclear"
        assert diag["confidence"] == 0.0
        assert "LLM schema validation failure" in diag["reasoning"]


def test_pipeline_wires_diagnosis_into_decision():
    sim = SubscriptionSimulator(42)
    pipeline = RecoveryPipeline(simulator=sim)
    case = {
        "event_id": "EVT-DIAG-001",
        "amount": 1999.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "failure_reason": "insufficient_funds",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
    }
    decision = pipeline.process(case, is_preview=True)
    assert "diagnosis" in decision
    assert decision["diagnosis"]["source"] == "rule"
    assert decision["diagnosis"]["decline_class"] == "soft"
    assert decision["features"]["decline_class"] == "soft"


def test_risk_decline_blocks_customer_outreach():
    sim = SubscriptionSimulator(42)
    pipeline = RecoveryPipeline(simulator=sim)
    case = {
        "event_id": "EVT-FRAUD-001",
        "amount": 1999.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "failure_reason": "issuer_suspected_fraud",
        "attempt_number": 1,
        "contact_count_7d": 0,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
    }
    decision = pipeline.process(case, is_preview=True)
    assert decision["diagnosis"]["decline_class"] == "risk"
    # Risk decline must not execute automated NUDGE or MANUAL_RECOVERY
    assert decision["chosen_action"] in ("WAIT", "ESCALATE")
    assert decision["feasible_actions"]["MANUAL_RECOVERY"] == "BLOCKED"
    assert decision["feasible_actions"]["NUDGE"] == "BLOCKED"
