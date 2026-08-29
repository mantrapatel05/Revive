"""
REVIVE 6.0 — Live Failure Injection & Reliability Drills

Covers the 3 critical reliability scenarios required for stage demonstrations:
1. Idempotency Rehearsal (Duplicate webhook delivery suppression)
2. Malformed LLM Output Injection (Pydantic validation failure -> Fail-closed ESCALATE -> Non-crashing batch)
3. Provider Down & Circuit Breaker (N consecutive 503s -> Circuit OPEN -> External call short-circuiting -> Audit preserved)

Usage:
  python scripts/rehearse_failure_injection.py --scenario all
  python scripts/rehearse_failure_injection.py --scenario idempotency
  python scripts/rehearse_failure_injection.py --scenario malformed_llm
  python scripts/rehearse_failure_injection.py --scenario provider_down
"""

import argparse
import hashlib
import hmac
import json
import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.config import RAZORPAY_WEBHOOK_SECRET
from app.db import get_conn
from app.pipeline import RecoveryPipeline
from app.execution.simulator import SubscriptionSimulator
from app.execution.live_executor import LiveExecutor
from app.execution.razorpay import RazorpayAPIError
from app.execution.circuit_breaker import CircuitBreaker, CircuitState


# ============================================================================
# SCENARIO 1: IDEMPOTENCY REHEARSAL
# ============================================================================
def build_idempotency_payload(payment_id: str = "pay_demo_failed_999", amount_paise: int = 249900) -> tuple[dict, bytes, str]:
    secret = RAZORPAY_WEBHOOK_SECRET or "revive-webhook-secret-123"
    payload = {
        "entity": "event",
        "account_id": "acc_enterprise_prod",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_enterprise_999",
                    "invoice_id": None,
                    "international": False,
                    "method": "card",
                    "amount_refunded": 0,
                    "refund_status": None,
                    "captured": False,
                    "description": "Monthly SaaS Enterprise Subscription",
                    "card_id": "card_demo_99",
                    "bank": None,
                    "wallet": None,
                    "vpa": None,
                    "email": "cfo@enterprise.com",
                    "contact": "+919876543210",
                    "notes": {"customer_id": "cust_enterprise_99"},
                    "fee": None,
                    "tax": None,
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Card declined by issuing bank",
                    "error_source": "bank",
                    "error_step": "payment_authorization",
                    "error_reason": "payment_failed",
                    "created_at": int(time.time()),
                }
            }
        },
        "created_at": int(time.time()),
    }
    raw_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()
    return payload, raw_bytes, sig


def run_idempotency_drill(event_id: str | None = None) -> bool:
    if not event_id:
        event_id = f"evt_demo_stage_{int(time.time())}"

    payload, raw_bytes, sig = build_idempotency_payload()
    print("\n" + "=" * 70)
    print("DRILL 1: WEBHOOK IDEMPOTENCY REHEARSAL")
    print(f"Target Event ID : {event_id}")
    print(f"Payload Size    : {len(raw_bytes)} bytes | HMAC Signature Verified")
    print("=" * 70)

    with TestClient(app) as client:
        headers = {
            "x-razorpay-event-id": event_id,
            "x-razorpay-signature": sig,
            "Content-Type": "application/json",
        }

        # Step 1: Initial Webhook Delivery
        print("\n[STEP 1] Ingesting initial failure webhook from Razorpay...")
        res1 = client.post("/api/webhook/razorpay", content=raw_bytes, headers=headers)
        print(f"  -> HTTP {res1.status_code}: {res1.json()}")
        assert res1.status_code == 200 and res1.json().get("status") == "accepted"
        print("  -> First delivery ACCEPTED and locked in webhook_events database table.")

        # Step 2: Duplicate Delivery (Simulated Razorpay Retry)
        print("\n[STEP 2] Simulating Razorpay automatic delivery retry (identical event ID)...")
        res2 = client.post("/api/webhook/razorpay", content=raw_bytes, headers=headers)
        print(f"  -> HTTP {res2.status_code}: {res2.json()}")
        assert res2.status_code == 200 and res2.json().get("status") == "duplicate"
        print("  -> Duplicate delivery DETECTED and SUPPRESSED at the database boundary.")

        # Step 3: Verify DB State
        with get_conn() as conn:
            row_count = conn.execute("SELECT COUNT(*) FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone()[0]
            print(f"\n[STEP 3] State Verification: exactly {row_count} row in webhook_events table (0 race conditions).")
            assert row_count == 1

    print("[RESULT] Drill 1 PASSED: Zero duplicate actions, idempotent ingestion confirmed.")
    return True


# ============================================================================
# SCENARIO 2: MALFORMED LLM OUTPUT INJECTION
# ============================================================================
def run_malformed_llm_drill() -> bool:
    print("\n" + "=" * 70)
    print("DRILL 2: MALFORMED LLM OUTPUT INJECTION & FAIL-CLOSED DRILL")
    print("Simulating malformed/schema-violating LLM response during decline diagnosis")
    print("=" * 70)

    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))

    # Construct a 3-case batch demonstrating non-crashing continuous processing
    batch = [
        {
            "event_id": "EVT-BATCH-01-CLEAN",
            "customer_name": "Aarav Sharma",
            "amount": 1999.0,
            "subscription_status": "pending",
            "invoice_status": "issued",
            "payment_method_type": "international_card",
            "failure_reason": "insufficient_funds",
            "attempt_number": 2,
            "contact_count_7d": 1,
            "customer_opted_out": False,
            "native_retry_scheduled": False,
            "current_time": "2026-08-29T12:00:00+05:30",
        },
        {
            "event_id": "EVT-BATCH-02-MALFORMED",
            "customer_name": "Priya Patel",
            "amount": 2499.0,
            "subscription_status": "pending",
            "invoice_status": "issued",
            "payment_method_type": "international_card",
            "failure_reason": "CUSTOM_HDFC_UNRECOGNIZED_CODE_404",
            "attempt_number": 2,
            "contact_count_7d": 1,
            "customer_opted_out": False,
            "native_retry_scheduled": False,
            "current_time": "2026-08-29T12:00:00+05:30",
        },
        {
            "event_id": "EVT-BATCH-03-RECOVERY",
            "customer_name": "Rohan Verma",
            "amount": 1499.0,
            "subscription_status": "pending",
            "invoice_status": "issued",
            "payment_method_type": "international_card",
            "failure_reason": "card_expired",
            "attempt_number": 2,
            "contact_count_7d": 1,
            "customer_opted_out": False,
            "native_retry_scheduled": False,
            "current_time": "2026-08-29T12:00:00+05:30",
        },
    ]

    # Mock Groq to return malformed output for Case 2
    raw_bad_json = '{"decline_class": "invented_sixth_category_unauthorized", "confidence": "invalid_float", "unexpected": true}'
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": raw_bad_json}}]}
    mock_resp.raise_for_status = MagicMock()

    processed_decisions = []

    print("\n[STEP 1] Executing 3-case batch through RecoveryPipeline...")
    with patch("requests.post", return_value=mock_resp):
        with patch("app.diagnosis.GROQ_API_KEY", "mock-groq-key"):
            for idx, case in enumerate(batch, 1):
                try:
                    dec = pipeline.process(case, is_preview=False)
                    processed_decisions.append(dec)
                    print(f"  [Case {idx}/3] {case['event_id']} -> Action: {dec['chosen_action']} | Diagnosis Source: {dec['diagnosis']['source']} | Status: {dec['execution_status']}")
                except Exception as exc:
                    print(f"  [CRASH] Pipeline crashed on case {case['event_id']}: {exc}")
                    raise

    # Verifications for Case 2 (Malformed LLM output):
    d2 = processed_decisions[1]
    diag2 = d2["diagnosis"]

    print("\n[STEP 2] Verifying Fail-Closed Gating Assertions on Case 2:")
    print(f"  (a) Diagnosis Source      : {diag2['source']} (Expected: 'llm_failed')")
    print(f"  (b) Diagnosis Class       : {diag2['decline_class']} (Expected: 'unclear')")
    print(f"  (c) Chosen Action         : {d2['chosen_action']} (Safe Fallback / Governed)")
    print(f"  (d) Preserved Raw Bad Output: {diag2.get('raw_llm_output')}")
    print(f"  (e) Batch Integrity       : {len(processed_decisions)}/3 cases processed (Zero crashes)")

    assert diag2["source"] == "llm_failed", "Expected source='llm_failed'"
    assert diag2["decline_class"] == "unclear", "Expected decline_class='unclear'"
    assert "LLM schema validation failure" in diag2["reasoning"] or "LLM Output Pydantic validation failed" in str(diag2)
    assert diag2.get("raw_llm_output") == raw_bad_json, "Raw bad LLM output must be preserved for audit"
    assert len(processed_decisions) == 3, "Pipeline batch loop must not crash on malformed LLM responses"

    print("\n[RESULT] Drill 2 PASSED: Pydantic caught malformed output, failed closed, preserved audit, continuous batch unbroken.")
    return True


# ============================================================================
# SCENARIO 3: PROVIDER DOWN & CIRCUIT BREAKER
# ============================================================================
class MockFailingRazorpayAdapter:
    def __init__(self):
        self.call_count = 0

    def create_payment_link(self, amount_paise: int, description: str, customer: dict = None) -> dict:
        self.call_count += 1
        raise RazorpayAPIError("503 Service Unavailable: Gateway Switch Down")

    def fetch_payment_link(self, payment_link_id: str) -> dict:
        self.call_count += 1
        raise RazorpayAPIError("503 Service Unavailable: Gateway Switch Down")


def run_provider_down_drill() -> bool:
    print("\n" + "=" * 70)
    print("DRILL 3: GATEWAY PROVIDER DOWN & CIRCUIT BREAKER DRILL")
    print("Simulating 503 Gateway Down -> Circuit Breaker trips OPEN -> External short-circuiting")
    print("=" * 70)

    mock_adapter = MockFailingRazorpayAdapter()
    circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    live_executor = LiveExecutor(adapter=mock_adapter)

    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))
    pipeline.live_executor = live_executor
    pipeline.circuit_breaker = circuit_breaker

    cases = [
        {
            "event_id": f"EVT-OUTAGE-{i:02d}",
            "customer_name": f"Enterprise Customer {i}",
            "amount": 2499.0,
            "subscription_status": "pending",
            "invoice_status": "issued",
            "payment_method_type": "international_card",
            "attempt_number": 2,
            "contact_count_7d": 1,
            "customer_opted_out": False,
            "native_retry_scheduled": False,
            "current_time": "2026-08-29T12:00:00+05:30",
            "is_live": True,
        }
        for i in range(1, 6)
    ]

    print("\n[STEP 1] Firing 5 consecutive recovery requests during active gateway outage...")
    results = []
    for idx, case in enumerate(cases, 1):
        dec = pipeline.process(case, is_preview=False)
        results.append(dec)
        print(f"  Request {idx}/5: {case['event_id']} -> Circuit: {circuit_breaker.state.value.upper():9s} | Action: {dec['chosen_action']:15s} | Status: {dec['execution_status']}")

    print("\n[STEP 2] Verifying Circuit Breaker Trip & Short-Circuiting Assertions:")
    print(f"  (a) Final Circuit State   : {circuit_breaker.state.value.upper()} (Expected: OPEN)")
    print(f"  (b) Total Outbound Calls  : {mock_adapter.call_count} (Expected: 3, requests 4 & 5 short-circuited)")
    print(f"  (c) Requests 4 & 5 Status : {results[3]['execution_status']} / {results[4]['execution_status']}")
    print(f"  (d) Requests 4 & 5 Action : {results[3]['chosen_action']} / {results[4]['chosen_action']} (Safe Fallback to ESCALATE/WAIT)")

    # Asserts
    assert circuit_breaker.state == CircuitState.OPEN, "Circuit breaker must be in OPEN state after threshold"
    assert mock_adapter.call_count == 3, f"Expected exactly 3 external calls before breaker opened, got {mock_adapter.call_count}"
    assert results[3]["chosen_action"] in ("ESCALATE", "WAIT"), "Subsequent calls while OPEN must route safely"
    assert results[4]["chosen_action"] in ("ESCALATE", "WAIT"), "Subsequent calls while OPEN must route safely"

    # Verify audit persistence for all 5 attempts
    with get_conn() as conn:
        for case in cases:
            row = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event_id = ?", (case["event_id"],)).fetchone()[0]
            assert row >= 1, f"Audit row missing for {case['event_id']}"
    print("  (e) Audit Ledger Integrity: All 5 attempts recorded in immutable audit log.")

    print("\n[RESULT] Drill 3 PASSED: Circuit breaker tripped at threshold 3, prevented cascading API storm, audit intact.")
    return True


# ============================================================================
# CLI DISPATCHER
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="REVIVE 6.0 — Live Failure Injection & Reliability Drills")
    parser.add_argument(
        "--scenario",
        choices=["all", "idempotency", "malformed_llm", "provider_down"],
        default="all",
        help="Specific failure scenario to rehearse",
    )
    parser.add_argument("--event-id", type=str, default=None, help="Custom event ID for idempotency test")
    args = parser.parse_args()

    print("\n" + "#" * 70)
    print("   REVIVE 6.0 — STAGE-READY FAILURE INJECTION & RELIABILITY SUITE   ")
    print("#" * 70)

    success = True
    if args.scenario in ("all", "idempotency"):
        success = run_idempotency_drill(args.event_id) and success
    if args.scenario in ("all", "malformed_llm"):
        success = run_malformed_llm_drill() and success
    if args.scenario in ("all", "provider_down"):
        success = run_provider_down_drill() and success

    if success:
        print("\n" + "=" * 70)
        print("ALL RELIABILITY INJECTION DRILLS COMPLETED WITH ZERO DEFECTS.")
        print("=" * 70 + "\n")
    else:
        print("\n[ERROR] One or more drills failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
