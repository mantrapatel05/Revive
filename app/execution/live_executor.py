"""Live executor for real Razorpay Test Mode execution.

Routes live (webhook-driven) cases through the actual Razorpay API instead of
the deterministic simulator. Returns the same ExecutionResult dataclass so
downstream audit logging needs zero changes.
"""
import logging
from app.execution.simulator import ExecutionResult
from app.execution.razorpay import RazorpayAdapter, RazorpayAPIError
from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

logger = logging.getLogger(__name__)


class LiveExecutor:
    ACTIONS = ("WAIT", "NUDGE", "MANUAL_RECOVERY", "ESCALATE")

    def __init__(self, adapter: RazorpayAdapter | None = None):
        if adapter:
            self.adapter = adapter
        elif RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            self.adapter = RazorpayAdapter()
        else:
            self.adapter = None

    @property
    def credentials_available(self) -> bool:
        return self.adapter is not None

    def execute(self, case: dict, action: str) -> ExecutionResult:
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown action: {action}")

        if not self.credentials_available:
            # Fail closed: caller should have already escalated, but guard here too.
            raise RazorpayAPIError(
                "Razorpay credentials missing — cannot execute live action. "
                "Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env"
            )

        amount = float(case.get("amount", 0.0))

        if action == "WAIT":
            logger.info("[LIVE] WAIT decision for %s — no external call", case.get("event_id"))
            return ExecutionResult(
                success=False, recovered_amount=0.0, cost=0.0,
                action="WAIT", detail="live: waiting for native retry",
                probability=0.0, time_to_recovery=0.0,
                status="NO_ACTION", provider="razorpay",
            )

        if action == "ESCALATE":
            logger.info("[LIVE] ESCALATE decision for %s — queued for human review", case.get("event_id"))
            return ExecutionResult(
                success=False, recovered_amount=0.0, cost=10.0,
                action="ESCALATE", detail="live: queued for human review",
                probability=0.0, time_to_recovery=0.0,
                status="QUEUED", provider="razorpay",
            )

        if action == "NUDGE":
            return self._execute_nudge(case, amount)

        if action == "MANUAL_RECOVERY":
            return self._execute_manual_recovery(case, amount)

        # Should never reach here due to the action check above
        raise ValueError(f"Unhandled action: {action}")

    def _execute_nudge(self, case: dict, amount: float) -> ExecutionResult:
        """Create an actionable Razorpay Payment Link for customer nudge recovery workflow.
        
        Semantics:
        Payment link creation requests an external payment recovery action (EXECUTION_REQUESTED).
        It does NOT mean payment has recovered. Final state remains PAYMENT_PENDING until provider
        evidence (webhook or status inquiry) establishes actual payment completion.
        """
        amount_paise = int(amount * 100)
        description = (
            f"REVIVE Nudge: Payment recovery for {case.get('event_id', 'unknown')} — "
            f"subscription {case.get('subscription_id', 'unknown')}"
        )

        customer = None
        customer_id = case.get("customer_id")
        if customer_id and customer_id != "unknown":
            customer = {"contact": customer_id}

        logger.info(
            "[LIVE] Creating Customer Nudge Payment Link for %s, amount ₹%.2f",
            case.get("event_id"), amount,
        )

        result = self.adapter.create_payment_link(
            amount_paise=amount_paise,
            description=description,
            customer=customer,
        )

        link_id = result.get("id", "")
        short_url = result.get("short_url", "")
        logger.info(
            "[LIVE] Nudge Payment Link created: id=%s url=%s", link_id, short_url,
        )

        return ExecutionResult(
            success=False,
            recovered_amount=0.0,
            cost=1.0,
            action="NUDGE",
            detail=f"live: payment_link created id={link_id} url={short_url}",
            probability=0.0,
            time_to_recovery=0.0,
            status="EXECUTION_REQUESTED",
            payment_link_id=link_id,
            payment_link_url=short_url,
            provider_response=result,
            provider="razorpay",
        )

    def _execute_manual_recovery(self, case: dict, amount: float) -> ExecutionResult:
        """Create an actionable Razorpay Payment Link for manual recovery workflow.
        
        Semantics:
        MANUAL_RECOVERY = create an actionable Test Mode payment request for the failed
        payment/recovery workflow. It does NOT mean "money recovered immediately".
        Status is strictly EXECUTION_REQUESTED; final recovery state remains PAYMENT_PENDING
        until provider evidence proves payment success.
        """
        amount_paise = int(amount * 100)
        description = (
            f"REVIVE recovery for {case.get('event_id', 'unknown')} — "
            f"subscription {case.get('subscription_id', 'unknown')}"
        )

        customer = None
        customer_id = case.get("customer_id")
        if customer_id and customer_id != "unknown":
            customer = {"contact": customer_id}

        logger.info(
            "[LIVE] Creating Payment Link for %s, amount ₹%.2f",
            case.get("event_id"), amount,
        )

        result = self.adapter.create_payment_link(
            amount_paise=amount_paise,
            description=description,
            customer=customer,
        )

        link_id = result.get("id", "")
        short_url = result.get("short_url", "")
        logger.info(
            "[LIVE] Payment Link created: id=%s url=%s", link_id, short_url,
        )

        return ExecutionResult(
            success=False,
            recovered_amount=0.0,
            cost=2.0,  # matches EconomicsEngine ActionCosts.MANUAL_RECOVERY default
            action="MANUAL_RECOVERY",
            detail=f"live: payment_link created id={link_id} url={short_url}",
            probability=0.0,
            time_to_recovery=0.0,
            status="EXECUTION_REQUESTED",
            payment_link_id=link_id,
            payment_link_url=short_url,
            provider_response=result,
            provider="razorpay",
        )
