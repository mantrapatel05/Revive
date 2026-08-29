"""
REVIVE 6.0 — Post-Governance Message Generation Subsystem

Runs ONLY AFTER the Policy Gate approves a customer-facing action and BEFORE execution.
1. Deterministic template selection: TEMPLATE_INTENTS[(action, diagnosis_class)]
2. Constrained LLM personalization with deterministic fallback
3. Automated tone-check safety guard (keyword blocklist + max 2 sentences)
4. Comprehensive audit logging of all messages (sent or blocked)
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

from app.config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger("revive.messaging")

TEMPLATE_INTENTS: Dict[Tuple[str, str], str] = {
    ("NUDGE", "hard"): "card_expired_reminder",
    ("NUDGE", "hard_decline"): "card_expired_reminder",
    ("NUDGE", "soft"): "payment_retry_link",
    ("NUDGE", "soft_decline"): "payment_retry_link",
    ("NUDGE", "unclear"): "general_payment_link",
    ("MANUAL_RECOVERY", "soft"): "payment_link_direct",
    ("MANUAL_RECOVERY", "soft_decline"): "payment_link_direct",
    ("MANUAL_RECOVERY", "hard"): "update_payment_method",
    ("MANUAL_RECOVERY", "hard_decline"): "update_payment_method",
    ("MANUAL_RECOVERY", "unclear"): "payment_link_direct",
}

DEFAULT_TEMPLATES: Dict[str, str] = {
    "card_expired_reminder": "Hi {customer_name}, your subscription payment of ₹{amount:,.2f} could not be processed as your card on file has expired. Please update your payment details here: {payment_link}",
    "payment_retry_link": "Hi {customer_name}, your subscription renewal of ₹{amount:,.2f} experienced a temporary processing delay. You can complete your renewal securely using this link: {payment_link}",
    "payment_link_direct": "Hi {customer_name}, here is your secure checkout link for ₹{amount:,.2f} to keep your subscription active: {payment_link}",
    "update_payment_method": "Hi {customer_name}, we were unable to process your payment of ₹{amount:,.2f}. Please update your payment method to avoid subscription interruption: {payment_link}",
    "general_payment_link": "Hi {customer_name}, please complete your subscription payment of ₹{amount:,.2f} via this secure link: {payment_link}",
}

# Blocklist of coercive, demanding, threatening, or high-pressure phrases
TONE_BLOCKLIST: List[str] = [
    "must",
    "immediately",
    "legal action",
    "final warning",
    "urgent",
    "penalized",
    "penalty",
    "consequences",
    "defaulted",
    "defaulter",
    "police",
    "court",
    "arrest",
    "lawsuit",
    "blacklisted",
    "seize",
    "demand",
    "threat",
    "harass",
    "debt collection",
    "recovery agent",
]


def check_tone(message_text: str) -> Tuple[bool, List[str]]:
    """
    Evaluates generated message against tone safety guidelines.
    1. Rejects presence of coercive/threatening blocklist words.
    2. Rejects messages longer than 2 sentences.
    """
    violations: List[str] = []
    text_lower = message_text.lower()

    for word in TONE_BLOCKLIST:
        # Word boundary match
        if re.search(r"\b" + re.escape(word) + r"\b", text_lower):
            violations.append(f"Prohibited coercive keyword: '{word}'")

    # Sanitize URLs and decimal currency numbers before counting sentences
    clean_text = re.sub(r"https?://\S+", "[LINK]", message_text)
    clean_text = re.sub(r"\d+\.\d+", "[NUMBER]", clean_text)

    # Sentence count check (max 2 sentences)
    sentences = [s.strip() for s in re.split(r"[.!?]+(?:\s+|$)", clean_text) if s.strip()]
    if len(sentences) > 2:
        violations.append(f"Exceeds maximum allowable sentence length (found {len(sentences)}, max 2)")

    return len(violations) == 0, violations


from pydantic import BaseModel, Field, ValidationError

class MessageGenerationOutput(BaseModel):
    message: str = Field(min_length=10, max_length=500)
    customer_name: str
    intent: str

def generate_message(
    case: Dict[str, Any],
    action: str,
    diagnosis_class: str,
    payment_link: str = "https://rzp.io/rzp/pay_demo",
    channel: str = "whatsapp",
) -> Dict[str, Any]:
    """
    Generates and tone-checks customer communication message after Governor approval.
    """
    customer_name = str(case.get("customer_name") or case.get("customer_id") or "Valued Customer")
    amount = float(case.get("amount", 0.0))

    # 1. Deterministic template intent selection
    norm_class = str(diagnosis_class).lower().replace("_decline", "")
    template_intent = (
        TEMPLATE_INTENTS.get((action, norm_class))
        or TEMPLATE_INTENTS.get((action, diagnosis_class))
        or "general_payment_link"
    )
    raw_template = DEFAULT_TEMPLATES.get(template_intent, DEFAULT_TEMPLATES["general_payment_link"])

    # Base deterministic message
    formatted_base = raw_template.format(
        customer_name=customer_name,
        amount=amount,
        payment_link=payment_link,
    )

    generated_text = formatted_base
    generation_source = "template"
    llm_validation_failed = False
    raw_llm_output = None
    extra_violations: List[str] = []

    # 2. Narrow LLM personalization if Groq key available
    if GROQ_API_KEY:
        system_prompt = (
            "You are a polite, respectful customer communication assistant for subscription billing.\n"
            f"Generate a friendly, concise message for intent: '{template_intent}'.\n"
            "STRICT CONSTRAINTS:\n"
            "1. MUST NOT exceed 2 sentences.\n"
            "2. MUST NOT contain pressuring, demanding, or shaming language (e.g. avoid 'must', 'immediately', 'warning').\n"
            "3. MUST address only the named customer.\n"
            f"4. MUST keep amounts in INR format (e.g. ₹{amount:,.2f}) and preserve the payment link exactly: {payment_link}.\n"
            "5. Output ONLY a valid JSON object matching this schema:\n"
            "   {\n"
            "     \"message\": \"<the generated message>\",\n"
            "     \"customer_name\": \"<customer name>\",\n"
            "     \"intent\": \"<intent>\"\n"
            "   }"
        )

        user_content = (
            f"Customer: {customer_name}, Amount: ₹{amount:,.2f}, Payment Link: {payment_link}, Intent: {template_intent}"
        )

        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 120,
                    "response_format": {"type": "json_object"},
                },
                timeout=5,
            )
            if r.status_code == 200:
                raw_llm_output = r.json()["choices"][0]["message"]["content"].strip()
                parsed = json.loads(raw_llm_output)
                validated = MessageGenerationOutput.model_validate(parsed)
                if payment_link in validated.message:
                    generated_text = validated.message
                    generation_source = "llm"
                else:
                    llm_validation_failed = True
                    extra_violations.append("Payment link missing in generated LLM message")
        except ValidationError as val_err:
            llm_validation_failed = True
            extra_violations.append(f"LLM output schema validation failed: {str(val_err)}")
            logger.warning("[MESSAGING] LLM schema validation error: %s", val_err)
        except Exception as exc:
            logger.info("[MESSAGING] LLM personalization fallback to template: %s", exc)

    # 3. Tone-check guard
    tone_ok, violations = check_tone(generated_text)
    if llm_validation_failed:
        tone_ok = False
        violations.extend(extra_violations)
        generation_source = "llm_failed"

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "action": action,
        "template_intent": template_intent,
        "content": generated_text,
        "source": generation_source,
        "tone_check_passed": tone_ok,
        "violations": violations,
        "status": "APPROVED_FOR_SEND" if tone_ok else "BLOCKED_TONE_CHECK",
    }

    if not tone_ok:
        logger.warning("[TONE_GUARD] Message failed tone validation: %s", violations)

    return log_entry
