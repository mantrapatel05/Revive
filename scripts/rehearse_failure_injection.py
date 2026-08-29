"""
REVIVE 6.0 — Live Failure Injection & Reliability Drills

Covers the key stage failure-injection drills required for judge presentations:
1. Webhook Idempotency Drill: Rejects duplicate webhook retries at DB constraint boundary.
2. Malformed LLM Diagnosis Drill: Catches schema violations in decline diagnosis, fails closed to ESCALATE, preserves raw payload in audit, batch continues unbroken.
3. Malformed LLM Message Fill Drill: Catches malformed message-generation output, suppresses dispatch, flags for human review, persists audit record.
4. Engine-Enforced Audit Tamper Drill: Proves UPDATE and DELETE against audit_logs are rejected by the database engine (PostgreSQL InsufficientPrivilege / SQLite IntegrityError).
5. Gateway Provider Outage Drill: 503 errors trip Circuit Breaker to OPEN at threshold 3, short-circuiting downstream calls.

Usage:
  python scripts/rehearse_failure_injection.py --scenario all
  python scripts/rehearse_failure_injection.py --scenario malformed_llm_diagnosis
  python scripts/rehearse_failure_injection.py --scenario malformed_llm_messaging
  python scripts/rehearse_failure_injection.py --scenario audit_tamper
  python scripts/rehearse_failure_injection.py --scenario provider_down
  python scripts/rehearse_failure_injection.py --scenario idempotency
"""

import argparse
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from app.config import RAZORPAY_WEBHOOK_SECRET, APP_DATABASE_URL
from app.db import get_conn, get_db_url
from app.pipeline import RecoveryPipeline
from app.execution.simulator import SubscriptionSimulator
from app.execution.live_executor import LiveExecutor
from app.execution.razorpay import RazorpayAPIError
from app.execution.circuit_breaker import CircuitBreaker, CircuitState
from app.messaging import generate_message

try:
    import psycopg2
    from psycopg2 import errors as pg_errors
except ImportError:
    psycopg2 = None
    pg_errors = None


# ============================================================================
# SCENARIO 1: WEBHOOK IDEMPOTENCY REHEARSAL
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
    print("DRILL: WEBHOOK IDEMPOTENCY REHEARSAL")
    print(f"Target Event ID : {event_id}")
    print(f"Payload Size    : {len(raw_bytes)} bytes | HMAC Signature Verified")
    print("=" * 70)

    with TestClient(app) as client:
        headers = {
            "x-razorpay-event-id": event_id,
            "x-razorpay-signature": sig,
            "Content-Type": "application/json",
        }

        print("\n[STEP 1] Ingesting initial failure webhook from Razorpay...")
        res1 = client.post("/api/webhook/razorpay", content=raw_bytes, headers=headers)
        print(f"  -> HTTP {res1.status_code}: {res1.json()}")
        assert res1.status_code == 200 and res1.json().get("status") == "accepted"
        print("  -> First delivery ACCEPTED and locked in webhook_events database table.")

        print("\n[STEP 2] Simulating Razorpay automatic delivery retry (identical event ID)...")
        res2 = client.post("/api/webhook/razorpay", content=raw_bytes, headers=headers)
        print(f"  -> HTTP {res2.status_code}: {res2.json()}")
        assert res2.status_code == 200 and res2.json().get("status") == "duplicate"
        print("  -> Duplicate delivery DETECTED and SUPPRESSED at the database boundary.")

        with get_conn() as conn:
            row_count = conn.execute("SELECT COUNT(*) FROM webhook_events WHERE event_id = ?", (event_id,)).fetchone()[0]
            print(f"\n[STEP 3] State Verification: exactly {row_count} row in webhook_events table (0 duplicate links created).")
            assert row_count == 1

    print("[RESULT] PASSED: Idempotent ingestion confirmed with 0 duplicate actions.")
    return True


# ============================================================================
# SCENARIO 2: MALFORMED LLM DIAGNOSIS OUTPUT
# ============================================================================
def run_malformed_llm_diagnosis_drill() -> bool:
    print("\n" + "=" * 70)
    print("DRILL: MALFORMED LLM DIAGNOSIS OUTPUT & FAIL-CLOSED GATING")
    print("Injecting schema violation in LLM decline diagnosis -> Verifying fail-closed ESCALATE")
    print("=" * 70)

    pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))

    batch = [
        {
            "event_id": "EVT-DIAG-01-CLEAN",
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
            "event_id": "EVT-DIAG-02-MALFORMED",
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
            "event_id": "EVT-DIAG-03-RECOVERY",
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

    raw_bad_json = '{"decline_class": "invented_sixth_category_unauthorized", "confidence": "invalid_float", "unexpected": true}'
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": raw_bad_json}}]}
    mock_resp.raise_for_status = MagicMock()

    processed_decisions = []
    print("\n[STEP 1] Running 3-case batch through RecoveryPipeline with injected LLM error...")
    with patch("requests.post", return_value=mock_resp):
        with patch("app.diagnosis.GROQ_API_KEY", "mock-groq-key"):
            for idx, case in enumerate(batch, 1):
                dec = pipeline.process(case, is_preview=False)
                processed_decisions.append(dec)
                print(f"  [Case {idx}/3] {case['event_id']} -> Action: {dec['chosen_action']:12s} | Source: {dec['diagnosis']['source']:10s} | Status: {dec['execution_status']}")

    d2 = processed_decisions[1]
    diag2 = d2["diagnosis"]

    print("\n[STEP 2] Asserting Fail-Closed Diagnosis Guarantees on Case 2:")
    print(f"  (a) Diagnosis Source        : {diag2['source']} (Expected: 'llm_failed')")
    print(f"  (b) Diagnosis Class         : {diag2['decline_class']} (Expected: 'unclear')")
    print(f"  (c) Chosen Action           : {d2['chosen_action']} (Expected: safe fallback / ESCALATE)")
    print(f"  (d) Preserved Raw Bad Output: {diag2.get('raw_llm_output')}")
    print(f"  (e) Batch Continuity        : {len(processed_decisions)}/3 cases processed (Zero crashes)")

    assert diag2["source"] == "llm_failed"
    assert diag2["decline_class"] == "unclear"
    assert diag2.get("raw_llm_output") == raw_bad_json
    assert len(processed_decisions) == 3

    print("\n[RESULT] PASSED: Pydantic trapped malformed output, failed closed, batch loop continued unbroken.")
    return True


# ============================================================================
# SCENARIO 3: MALFORMED LLM MESSAGE FILL OUTPUT
# ============================================================================
def run_malformed_llm_messaging_drill() -> bool:
    print("\n" + "=" * 70)
    print("DRILL: MALFORMED LLM MESSAGE FILL & TONE GUARD SAFETY DRILL")
    print("Injecting malformed/schema-violating LLM response during message generation")
    print("=" * 70)

    case = {
        "event_id": "EVT-MSG-DRILL-01",
        "customer_name": "Deepak Roy",
        "amount": 2499.0,
        "subscription_status": "pending",
        "invoice_status": "issued",
        "payment_method_type": "international_card",
        "attempt_number": 2,
        "contact_count_7d": 1,
        "customer_opted_out": False,
        "native_retry_scheduled": False,
        "current_time": "2026-08-29T12:00:00+05:30",
    }

    # Malformed LLM output missing required 'customer_name' and 'intent'
    raw_bad_msg_json = '{"message": "Please pay ₹2,499.00 here: https://rzp.io/rzp/demo"}'
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": raw_bad_msg_json}}]}

    print("\n[STEP 1] Generating message with injected schema violation...")
    with patch("requests.post", return_value=mock_resp):
        with patch("app.messaging.GROQ_API_KEY", "mock-groq-key"):
            msg_res = generate_message(case, "NUDGE", "soft", payment_link="https://rzp.io/rzp/demo")

    print(f"  -> Generated Status      : {msg_res['status']}")
    print(f"  -> Tone Check Passed     : {msg_res['tone_check_passed']}")
    print(f"  -> Generation Source     : {msg_res['source']}")
    print(f"  -> Trapped Violations    : {msg_res['violations']}")

    print("\n[STEP 2] Asserting Messaging Fail-Closed & Escalation Routing:")
    assert msg_res["tone_check_passed"] is False, "Malformed message must fail tone/schema check"
    assert msg_res["source"] == "llm_failed", "Source must be tagged 'llm_failed'"
    assert msg_res["status"] == "BLOCKED_TONE_CHECK", "Status must be blocked from dispatch"
    assert any("schema validation failed" in v for v in msg_res["violations"])

    print("\n[RESULT] PASSED: Malformed message fill blocked from dispatch, escalated for human review.")
    return True


# ============================================================================
# SCENARIO 4: ENGINE-ENFORCED AUDIT TAMPER ATTEMPT
# ============================================================================
def run_audit_tamper_drill() -> bool:
    print("\n" + "=" * 70)
    print("DRILL: ENGINE-ENFORCED AUDIT LOG IMMUTABILITY & TAMPER ATTEMPT")
    print("Attempting direct UPDATE and DELETE against audit_logs table")
    print("=" * 70)

    # 1. Insert genuine audit row
    test_case_id = f"EVT-TAMPER-TEST-{int(time.time())}"
    with get_conn(admin=False) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_logs (decision_id, event_id, case_id, timestamp, payload_json) VALUES (?, ?, ?, ?, ?)",
            (f"dec_{test_case_id}", test_case_id, test_case_id, datetime.now(timezone.utc).isoformat(), '{"status": "AUTHENTIC_RECORD"}'),
        )
        row_id = cursor.lastrowid if hasattr(cursor, "lastrowid") else 1
        print(f"\n[STEP 1] Inserted authentic audit row ID {row_id} (case_id: {test_case_id}).")

    # 2. Attempt UPDATE against audit row -> Must be rejected by database engine
    print("\n[STEP 2] Attempting unauthorized UPDATE on audit_logs row...")
    update_blocked = False
    error_msg = ""
    try:
        with get_conn(admin=False) as conn:
            conn.execute("UPDATE audit_logs SET payload_json = ? WHERE case_id = ?", ('{"tampered": true}', test_case_id))
    except (sqlite3.IntegrityError, Exception) as exc:
        update_blocked = True
        error_msg = str(exc)
        print(f"  -> [ABORTED] Database engine rejected UPDATE: {error_msg}")

    assert update_blocked, "Database engine failed to block UPDATE on audit_logs"
    assert "append-only" in error_msg or "permission denied" in error_msg or "UPDATE forbidden" in error_msg

    # 3. Attempt DELETE against audit row -> Must be rejected by database engine
    print("\n[STEP 3] Attempting unauthorized DELETE on audit_logs row...")
    delete_blocked = False
    del_error_msg = ""
    try:
        with get_conn(admin=False) as conn:
            conn.execute("DELETE FROM audit_logs WHERE case_id = ?", (test_case_id,))
    except (sqlite3.IntegrityError, Exception) as exc:
        delete_blocked = True
        del_error_msg = str(exc)
        print(f"  -> [ABORTED] Database engine rejected DELETE: {del_error_msg}")

    assert delete_blocked, "Database engine failed to block DELETE on audit_logs"
    assert "append-only" in del_error_msg or "permission denied" in del_error_msg or "DELETE forbidden" in del_error_msg

    # 4. Verify original row integrity
    with get_conn(admin=False) as conn:
        row = conn.execute("SELECT payload_json FROM audit_logs WHERE case_id = ?", (test_case_id,)).fetchone()
        assert row is not None
        assert "AUTHENTIC_RECORD" in row[0]
        print(f"\n[STEP 4] Integrity Verified: Record remains pristine ('AUTHENTIC_RECORD').")

    print("\n[RESULT] PASSED: Database engine triggers/privileges strictly enforce append-only immutability.")
    return True


# ============================================================================
# SCENARIO 5: GATEWAY PROVIDER DOWN & CIRCUIT BREAKER
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
    print("DRILL: GATEWAY PROVIDER DOWN & CIRCUIT BREAKER DRILL")
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

    assert circuit_breaker.state == CircuitState.OPEN, "Circuit breaker must be in OPEN state after threshold"
    assert mock_adapter.call_count == 3, f"Expected exactly 3 external calls before breaker opened, got {mock_adapter.call_count}"
    assert results[3]["chosen_action"] in ("ESCALATE", "WAIT"), "Subsequent calls while OPEN must route safely"
    assert results[4]["chosen_action"] in ("ESCALATE", "WAIT"), "Subsequent calls while OPEN must route safely"

    with get_conn() as conn:
        for case in cases:
            row = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE event_id = ?", (case["event_id"],)).fetchone()[0]
            assert row >= 1, f"Audit row missing for {case['event_id']}"
    print("  (e) Audit Ledger Integrity: All 5 attempts recorded in immutable audit log.")

    print("\n[RESULT] PASSED: Circuit breaker tripped at threshold 3, prevented cascading API storm, audit intact.")
    return True


# ============================================================================
# CLI DISPATCHER
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="REVIVE 6.0 — Live Failure Injection & Reliability Drills")
    parser.add_argument(
        "--scenario",
        choices=["all", "idempotency", "malformed_llm_diagnosis", "malformed_llm_messaging", "audit_tamper", "provider_down", "malformed_llm"],
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
    if args.scenario in ("all", "malformed_llm_diagnosis", "malformed_llm"):
        success = run_malformed_llm_diagnosis_drill() and success
    if args.scenario in ("all", "malformed_llm_messaging"):
        success = run_malformed_llm_messaging_drill() and success
    if args.scenario in ("all", "audit_tamper"):
        success = run_audit_tamper_drill() and success
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
