"""
REVIVE 6.0 — Decline Diagnosis Subsystem

Classifies Razorpay subscription and payment decline signals into:
1. Deterministic Rule Matching (DECLINE_RULES table) -> source: "rule"
2. Strict LLM Fallback (Groq / Pydantic validation) -> source: "llm" or "llm_failed"
3. Fail-Closed Gating: Validation errors or unclear reasons fail closed without unbounded retries.
"""

import json
import logging
import re
from typing import Any, Dict, Literal, Optional
import requests
from pydantic import BaseModel, Field, ValidationError

from app.config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger("revive.diagnosis")

DECLINE_RULES: Dict[str, str] = {
    # --- Soft declines (transient, recoverable via retry / customer funds / gateway cron) ---
    "insufficient_funds": "soft",
    "insufficient_fund": "soft",
    "low_balance": "soft",
    "payment_timed_out": "soft",
    "gateway_timeout": "soft",
    "gateway_downtime": "soft",
    "gateway_error": "soft",
    "network": "soft",
    "network_error": "soft",
    "bank_declined": "soft",
    "bank_offline": "soft",
    "bank_technical_error": "soft",
    "authentication_failed": "soft",
    "otp_not_entered": "soft",
    "pending": "soft",
    "issuer_timeout": "soft",
    "temporary_failure": "soft",

    # --- Hard declines (permanent, card expired, account closed, invalid credentials) ---
    "card_expired": "hard",
    "expired_card": "hard",
    "invalid_card": "hard",
    "invalid_card_number": "hard",
    "invalid_cvv": "hard",
    "card_disabled": "hard",
    "card_inactive": "hard",
    "account_closed": "hard",
    "account_does_not_exist": "hard",
    "halted": "hard",
    "currency_unsupported": "hard",

    # --- Risk / Fraud declines (fraud suspected, lost/stolen card, compliance block, do not honor) ---
    "issuer_suspected_fraud": "risk",
    "fraud_detected": "risk",
    "risk_threshold_exceeded": "risk",
    "do_not_honor": "risk",
    "stolen_card": "risk",
    "lost_card": "risk",
    "pickup_card": "risk",
    "compliance_block": "risk",
    "restricted_card": "risk",
    "security_violation": "risk",
    "velocity_exceeded": "risk",
}


class LLMDiagnosisOutput(BaseModel):
    decline_class: Literal[
        "soft_decline", "hard_decline", "risk_decline", "unclear",
        "soft", "hard", "risk"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


def normalize_reason(raw: Any) -> str:
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    s = re.sub(r"[\s\-_]+", "_", s)
    return s


def llm_diagnose_fallback(event: Dict[str, Any], raw_reason: str) -> Dict[str, Any]:
    """
    LLM diagnosis fallback via Groq API with temperature 0-0.3 and strict Pydantic validation.
    Fails closed on any error, returning decline_class='unclear' and source='llm_failed'.
    """
    if not GROQ_API_KEY:
        logger.info("[DIAGNOSIS] Groq API key unconfigured; failing closed with unclear diagnosis")
        return {
            "decline_class": "unclear",
            "reason": raw_reason,
            "source": "llm_failed",
            "confidence": 0.0,
            "reasoning": "LLM diagnosis key unavailable; fail-closed default applied.",
        }

    system_prompt = (
        "You are a financial payment decline classifier for subscription recovery.\n"
        "Classify the provided payment decline reason into EXACTLY ONE of the following four categories:\n"
        "- 'soft_decline': transient, retryable, temporary bank/network/balance/timeout issues\n"
        "- 'hard_decline': permanent failure, expired card, invalid number, closed account\n"
        "- 'risk_decline': fraud suspected, lost/stolen card, compliance block, do not honor\n"
        "- 'unclear': unfamiliar, ambiguous, or insufficient information\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. Do not invent a fifth category.\n"
        "2. Use 'unclear' if genuinely unclear.\n"
        "3. Do not guess.\n"
        "4. Respond ONLY with a valid JSON object matching this schema:\n"
        "   {\n"
        "     \"decline_class\": \"soft_decline\" | \"hard_decline\" | \"risk_decline\" | \"unclear\",\n"
        "     \"confidence\": <float between 0.0 and 1.0>,\n"
        "     \"reasoning\": \"<concise explanation>\"\n"
        "   }"
    )

    user_payload = {
        "event_id": event.get("event_id", "unknown"),
        "failure_reason": raw_reason,
        "failure_source": event.get("failure_source"),
        "error_code": event.get("error_code"),
        "error_description": event.get("error_description"),
        "payment_method_type": event.get("payment_method_type"),
        "amount": event.get("amount"),
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=10,
        )
        response.raise_for_status()
        res_data = response.json()
        raw_text = res_data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(raw_text)

        # Strict Pydantic validation (No retry loops, fail closed)
        validated = LLMDiagnosisOutput.model_validate(parsed)

        # Normalize class name
        class_map = {
            "soft_decline": "soft",
            "hard_decline": "hard",
            "risk_decline": "risk",
            "soft": "soft",
            "hard": "hard",
            "risk": "risk",
            "unclear": "unclear",
        }
        normalized_class = class_map.get(validated.decline_class, "unclear")

        return {
            "decline_class": normalized_class,
            "reason": raw_reason,
            "source": "llm",
            "confidence": float(validated.confidence),
            "reasoning": validated.reasoning,
        }

    except ValidationError as val_err:
        logger.error("[DIAGNOSIS_AUDIT] LLM Output Pydantic validation failed: %s | Raw response: %s", val_err, locals().get("raw_text", "None"))
        return {
            "decline_class": "unclear",
            "reason": raw_reason,
            "source": "llm_failed",
            "confidence": 0.0,
            "reasoning": f"LLM schema validation failure: {str(val_err)}",
        }
    except Exception as exc:
        logger.error("[DIAGNOSIS_AUDIT] LLM request error: %s | Raw response: %s", exc, locals().get("raw_text", "None"))
        return {
            "decline_class": "unclear",
            "reason": raw_reason,
            "source": "llm_failed",
            "confidence": 0.0,
            "reasoning": f"LLM invocation failed: {str(exc)}",
        }


def diagnose(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Diagnoses an inbound recovery event.
    1. Looks up decline reason in DECLINE_RULES table.
    2. If found -> returns source: "rule" with confidence: 1.0.
    3. If unfamiliar -> calls Groq LLM fallback with strict Pydantic validation (source: "llm" or "llm_failed").
    """
    raw_candidates = [
        event.get("failure_reason"),
        event.get("error_code"),
        event.get("error_description"),
        event.get("reason"),
        event.get("failure_source"),
    ]

    matched_key = None
    for cand in raw_candidates:
        if cand:
            norm = normalize_reason(cand)
            if norm in DECLINE_RULES:
                matched_key = norm
                break

    if matched_key is not None:
        return {
            "decline_class": DECLINE_RULES[matched_key],
            "reason": matched_key,
            "source": "rule",
            "confidence": 1.0,
            "reasoning": f"Matched deterministic Razorpay decline rule for '{matched_key}'.",
        }

    # Unfamiliar reason -> invoke LLM fallback
    primary_reason = str(event.get("failure_reason") or event.get("error_code") or event.get("error_description") or event.get("reason") or "unknown_decline")
    return llm_diagnose_fallback(event, primary_reason)
