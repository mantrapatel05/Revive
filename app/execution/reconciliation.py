import logging
from enum import Enum
import hashlib
from app.execution.razorpay import RazorpayAdapter, RazorpayAPIError

logger = logging.getLogger(__name__)

class ReconciliationState(str, Enum):
    UNKNOWN='unknown'
    CONFIRMED='confirmed'
    FAILED='failed'


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

    Returns UNKNOWN on any API error or timeout — never silently retries
    a money-moving action on an UNKNOWN result.
    """
    if not payment_link_id:
        logger.warning("reconcile_payment_live called with empty payment_link_id")
        return ReconciliationState.UNKNOWN

    adapter = adapter or RazorpayAdapter()
    try:
        result = adapter.fetch_payment_link(payment_link_id)
        status = result.get("status", "").lower()
        if status == "paid":
            logger.info("Payment link %s confirmed PAID", payment_link_id)
            return ReconciliationState.CONFIRMED
        elif status in {"cancelled", "expired"}:
            logger.info("Payment link %s status: %s → FAILED", payment_link_id, status)
            return ReconciliationState.FAILED
        else:
            # Status is "created" or "partially_paid" etc. — not yet resolved.
            logger.info("Payment link %s status: %s → UNKNOWN (pending)", payment_link_id, status)
            return ReconciliationState.UNKNOWN
    except RazorpayAPIError as exc:
        # Fail safe: return UNKNOWN, never guess or silently retry.
        logger.error("Razorpay API error during reconciliation for %s: %s", payment_link_id, exc)
        return ReconciliationState.UNKNOWN
    except Exception as exc:
        logger.error("Unexpected error during reconciliation for %s: %s", payment_link_id, exc)
        return ReconciliationState.UNKNOWN
