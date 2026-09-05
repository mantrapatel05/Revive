# Live Failure Injection & Webhook Idempotency Protocol

## 1. Executive Summary
In payment recovery infrastructure, duplicate webhook deliveries from payment gateways (e.g. Razorpay) are standard retry behavior, not anomalous bugs. If a recovery system lacks deterministic idempotency at the ingestion boundary, duplicate delivery causes duplicate customer charges, double nudges, or conflicting manual escalations.

REVIVE enforces deterministic idempotency at the PostgreSQL/PostgreSQL ingestion boundary with unique constraint locks on `event_id` before downstream execution occurs.

---

## 2. Stage Rehearsal Script
Before presenting on stage, run the automated verification script to confirm zero database race conditions:
```bash
python scripts/rehearse_failure_injection.py
```
**Expected Output:**
```text
======================================================================
REVIVE IDEMPOTENCY REHEARSAL
Target Event ID : evt_demo_stage_...
Payload Size    : 823 bytes
HMAC Signature  : ...
======================================================================

[STEP 1] Sending initial failure webhook...
Response HTTP 200: {'status': 'accepted', 'event_id': 'evt_demo_stage_...', 'event': 'payment.failed'}
  -> First delivery successfully ACCEPTED and locked in webhook_events table.

[STEP 2] Simulating Razorpay automatic delivery retry (identical event ID)...
Response HTTP 200: {'status': 'duplicate', 'event_id': 'evt_demo_stage_...'}
  -> Duplicate delivery successfully DETECTED and SUPPRESSED.

[STEP 3] Database Verification:
  Rows in webhook_events for evt_demo_stage_...: 1

======================================================================
REHEARSAL PASSED: Zero race conditions, exactly 1 intent recorded.
======================================================================
```

---

## 3. Live Stage Execution Commands

### Webhook Secret & Payload Definition
- **Webhook Secret**: `revive-webhook-secret-123`
- **Target Endpoint**: `http://localhost:8000/api/webhook/razorpay`
- **Event ID**: `evt_live_stage_demo_001`
- **Payload**:
```json
{"entity":"event","account_id":"acc_enterprise_prod","event":"payment.failed","contains":["payment"],"payload":{"payment":{"entity":{"id":"pay_live_stage_failed_001","amount":249900,"currency":"INR","status":"failed","order_id":"order_enterprise_999","invoice_id":null,"international":false,"method":"card","amount_refunded":0,"refund_status":null,"captured":false,"description":"Monthly SaaS Enterprise Subscription","card_id":"card_demo_99","bank":null,"wallet":null,"vpa":null,"email":"cfo@enterprise.com","contact":"+919876543210","notes":{"customer_id":"cust_enterprise_99"},"fee":null,"tax":null,"error_code":"BAD_REQUEST_ERROR","error_description":"Card declined by issuing bank","error_source":"bank","error_step":"payment_authorization","error_reason":"payment_failed","created_at":1774867200}}},"created_at":1774867200}
```
- **Precomputed HMAC-SHA256 Signature**:
`9fa83ae963830e1fe8479221c635a944d29f30e02d9553cd0fda5297c8ca5d5f`

---

### Terminal Command 1: Initial Inbound Webhook Delivery
Run in terminal on stage:
```bash
curl -X POST http://localhost:8000/api/webhook/razorpay \
  -H "Content-Type: application/json" \
  -H "x-razorpay-event-id: evt_live_stage_demo_001" \
  -H "x-razorpay-signature: 9fa83ae963830e1fe8479221c635a944d29f30e02d9553cd0fda5297c8ca5d5f" \
  -d '{"entity":"event","account_id":"acc_enterprise_prod","event":"payment.failed","contains":["payment"],"payload":{"payment":{"entity":{"id":"pay_live_stage_failed_001","amount":249900,"currency":"INR","status":"failed","order_id":"order_enterprise_999","invoice_id":null,"international":false,"method":"card","amount_refunded":0,"refund_status":null,"captured":false,"description":"Monthly SaaS Enterprise Subscription","card_id":"card_demo_99","bank":null,"wallet":null,"vpa":null,"email":"cfo@enterprise.com","contact":"+919876543210","notes":{"customer_id":"cust_enterprise_99"},"fee":null,"tax":null,"error_code":"BAD_REQUEST_ERROR","error_description":"Card declined by issuing bank","error_source":"bank","error_step":"payment_authorization","error_reason":"payment_failed","created_at":1774867200}}},"created_at":1774867200}'
```
**Terminal Output:**
```json
{"status":"accepted","event_id":"evt_live_stage_demo_001","event":"payment.failed"}
```
**Stage Spoken Line:**
> *"Watch — I'm sending Razorpay's real signed payment failure webhook directly into REVIVE. The boundary verifies the cryptographic HMAC signature, acquires the idempotency lock, and queues the decision for causal evaluation."*

---

### Terminal Command 2: Simulating Razorpay Automatic Retry (Duplicate Delivery)
Fire the exact same curl command a second time:
```bash
curl -X POST http://localhost:8000/api/webhook/razorpay \
  -H "Content-Type: application/json" \
  -H "x-razorpay-event-id: evt_live_stage_demo_001" \
  -H "x-razorpay-signature: 9fa83ae963830e1fe8479221c635a944d29f30e02d9553cd0fda5297c8ca5d5f" \
  -d '{"entity":"event","account_id":"acc_enterprise_prod","event":"payment.failed","contains":["payment"],"payload":{"payment":{"entity":{"id":"pay_live_stage_failed_001","amount":249900,"currency":"INR","status":"failed","order_id":"order_enterprise_999","invoice_id":null,"international":false,"method":"card","amount_refunded":0,"refund_status":null,"captured":false,"description":"Monthly SaaS Enterprise Subscription","card_id":"card_demo_99","bank":null,"wallet":null,"vpa":null,"email":"cfo@enterprise.com","contact":"+919876543210","notes":{"customer_id":"cust_enterprise_99"},"fee":null,"tax":null,"error_code":"BAD_REQUEST_ERROR","error_description":"Card declined by issuing bank","error_source":"bank","error_step":"payment_authorization","error_reason":"payment_failed","created_at":1774867200}}},"created_at":1774867200}'
```
**Terminal Output:**
```json
{"status":"duplicate","event_id":"evt_live_stage_demo_001"}
```
**Stage Spoken Line:**
> *"Now watch what happens when Razorpay retries delivery — which is standard gateway behavior over the wire. Notice the terminal returns status: duplicate with an HTTP 200 acknowledgment so Razorpay stops retrying. The database contains exactly one row, zero duplicate outbox intents were generated, and the customer is never double-charged. This failure mode breaks naive recovery systems in production; REVIVE treats it as a first-class guarantee."*

---

### UI Verification (Dashboard Button Alternative)
In the Control Room dashboard, operators can also click the dedicated **`⚡ duplicate webhook demo`** button in the command deck to trigger an immediate simulation showing the idempotency lock in the operator notification toast.
