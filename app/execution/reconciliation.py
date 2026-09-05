import logging
from enum import Enum
import hashlib
import json
from datetime import datetime, timezone
from app.execution.razorpay import RazorpayAdapter, RazorpayAPIError
from app.db import get_conn
from app.execution.outbox import mark_intent_status
from app.audit.logger import AuditLogger

logger = logging.getLogger(__name__)

class ReconciliationState(str, Enum):
    EXECUTION_REQUESTED = 'EXECUTION_REQUESTED'
    PAYMENT_PENDING = 'PAYMENT_PENDING'
    CONFIRMED = 'CONFIRMED'
    FAILED = 'FAILED'
    UNKNOWN = 'UNKNOWN'


# --- Synthetic/benchmark stand-in (used when is_live is False) ---
def reconcile_payment(case_id: str, action: str) -> ReconciliationState:
    """Deterministic hash-based reconciliation for synthetic evaluation cases.

    This is the original stand-in used by the benchmark/evaluation path.
    Do NOT use for live cases — use reconcile_payment_live() instead.
    """
    h=int(hashlib.sha256(f'{case_id}|{action}'.encode()).hexdigest()[:8],16)%10
    return ReconciliationState.CONFIRMED if h<7 else ReconciliationState.FAILED


# --- Live reconciliation (queries actual Razorpay API) ---
def reconcile_payment_live(payment_link_id: str, adapter: RazorpayAdapter | None = None) -> ReconciliationState:
    """Check actual payment status via Razorpay API for a live Payment Link.

    Semantics:
    - Returns CONFIRMED only when Razorpay proves status is 'paid'.
    - Returns PAYMENT_PENDING when the link exists in 'created' or 'issued' status (customer has not paid yet).
    - Returns FAILED when link is 'cancelled' or 'expired'.
    - Returns UNKNOWN on any API error, timeout, or unrecognized status — never guesses or silently retries.
    """
    if not payment_link_id:
        logger.warning("reconcile_payment_live called with empty payment_link_id")
        return ReconciliationState.UNKNOWN

    adapter = adapter or RazorpayAdapter()
    try:
        result = adapter.fetch_payment_link(payment_link_id)
        status = result.get("status", "").lower()
        if status == "paid":
            logger.info("Payment link %s confirmed PAID via provider inquiry", payment_link_id)
            return ReconciliationState.CONFIRMED
        elif status in {"cancelled", "expired"}:
            logger.info("Payment link %s status: %s → FAILED", payment_link_id, status)
            return ReconciliationState.FAILED
        elif status in {"created", "partially_paid", "issued"}:
            logger.info("Payment link %s status: %s → PAYMENT_PENDING (customer has not yet paid)", payment_link_id, status)
            return ReconciliationState.PAYMENT_PENDING
        else:
            logger.info("Payment link %s status: %s → UNKNOWN", payment_link_id, status)
            return ReconciliationState.UNKNOWN
    except RazorpayAPIError as exc:
        # Fail safe: return UNKNOWN, never guess or silently retry.
        logger.error("Razorpay API error during reconciliation for %s: %s", payment_link_id, exc)
        return ReconciliationState.UNKNOWN
    except Exception as exc:
        logger.error("Unexpected error during reconciliation for %s: %s", payment_link_id, exc)
        return ReconciliationState.UNKNOWN


# --- Inbound Webhook Reconciliation ---
def reconcile_webhook_event(payload: dict, event_id: str | None = None) -> dict:
    """Correlate an incoming Razorpay payment event to an existing execution and update final state.

    Correlates via payment_link_id, payment_id, order_id, or subscription_id.
    Guarantees that final_state becomes CONFIRMED only upon provider evidence.
    """
    event_type = payload.get("event", "")
    # Razorpay webhook nests objects directly under payload, e.g. payload.payment_link = {entity:'payment_link', id:'plink_...'}
    # Some docs show extra entity wrapper, handle both
    def _unwrap(obj):
        if isinstance(obj, dict) and isinstance(obj.get("entity"), dict):
            return obj.get("entity", {})
        return obj if isinstance(obj, dict) else {}

    plink_obj = _unwrap(payload.get("payload", {}).get("payment_link", {}))
    pay_obj = _unwrap(payload.get("payload", {}).get("payment", {}))
    sub_obj = _unwrap(payload.get("payload", {}).get("subscription", {}))
    inv_obj = _unwrap(payload.get("payload", {}).get("invoice", {}))

    payment_link_id = plink_obj.get("id") or pay_obj.get("payment_link_id") or inv_obj.get("payment_link_id")
    payment_id = pay_obj.get("id")
    subscription_id = sub_obj.get("id") or pay_obj.get("subscription_id")

    # Determine final state based on explicit provider event evidence
    if event_type in {"payment_link.paid", "payment.captured", "invoice.paid", "order.paid"}:
        final_state_val = ReconciliationState.CONFIRMED
        reason = f"Observed provider payment success event: {event_type}"
    elif event_type in {"payment_link.cancelled", "payment_link.expired"}:
        final_state_val = ReconciliationState.FAILED
        reason = f"Observed provider link cancellation/expiry: {event_type}"
    elif event_type in {"payment.failed"}:
        final_state_val = ReconciliationState.FAILED
        reason = f"Observed provider payment failure event: {event_type}"
    else:
        final_state_val = ReconciliationState.UNKNOWN
        reason = f"Unmapped provider event: {event_type}"

    # Correlate with existing execution intent in PostgreSQL
    matched_intent = None
    with get_conn() as conn:
        if payment_link_id:
            matched_intent = conn.execute(
                "SELECT * FROM execution_intents WHERE payload_json::text LIKE ? OR result_json::text LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{payment_link_id}%", f"%{payment_link_id}%"),
            ).fetchone()
        if not matched_intent and subscription_id:
            matched_intent = conn.execute(
                "SELECT * FROM execution_intents WHERE case_id LIKE ? OR payload_json::text LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{subscription_id}%", f"%{subscription_id}%"),
            ).fetchone()

    matched_case_id = matched_intent["case_id"] if matched_intent else (subscription_id or "unknown")
    matched_decision_id = matched_intent["decision_id"] if matched_intent else None

    # Update durable execution intent status
    if matched_intent:
        mark_intent_status(
            matched_intent["id"],
            final_state_val.value,
            {
                "final_state": {
                    "state": final_state_val.value,
                    "source": "razorpay_webhook",
                    "provider_event_id": event_id,
                    "payment_id": payment_id,
                    "payment_link_id": payment_link_id,
                    "reason": reason,
                }
            },
        )

    # Record immutable audit ledger entry for reconciliation
    AuditLogger().log({
        "event": "reconciliation",
        "decision_id": matched_decision_id,
        "case_id": matched_case_id,
        "event_id": event_id,
        "payment_link_id": payment_link_id,
        "payment_id": payment_id,
        "provider_event_id": event_id,
        "execution_result": {
            "status": "EXECUTION_REQUESTED",
            "payment_link_id": payment_link_id,
        },
        "final_state": {
            "state": final_state_val.value,
            "source": "razorpay_webhook",
            "reason": reason,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "status": "reconciled",
        "final_state": final_state_val.value,
        "case_id": matched_case_id,
        "decision_id": matched_decision_id,
        "payment_link_id": payment_link_id,
        "payment_id": payment_id,
        "reason": reason,
    }
