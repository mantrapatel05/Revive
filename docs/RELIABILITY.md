# REVIVE 6.0 — Reliability Engineering & Failure Boundaries

## Reliability Architecture

REVIVE implements fail-closed reliability patterns across every execution and persistence boundary. The system guarantees that external side effects (moving money, sending customer communications) cannot be executed without explicit authorization, cannot be duplicated on webhook retries, and cannot result in blind retries during network failures.

## Core Reliability Components

### 1. Ingestion Idempotency & Signature Verification
- Ingested webhooks verify HMAC-SHA256 digests (`X-Razorpay-Signature`) against `RAZORPAY_WEBHOOK_SECRET`.
- Incoming event IDs are recorded into a persistent PostgreSQL `inbox_events` table before pipeline execution.
- Duplicate event deliveries are acknowledged with HTTP 200 and suppressed with zero secondary intents.

### 2. Execution Authorization & Version Gate
- Any side-effecting recovery action (`MANUAL_RECOVERY`) requires an `ExecutionAuthorization` object.
- The authorization token contains a unique `auth_id`, `event_id`, `action`, cryptographic `policy_version`, `model_version`, and a 300-second TTL timestamp.
- The inbound authorization gate validates:
  1. Current time does not exceed authorization timestamp + TTL.
  2. Active system `policy_version` matches authorized `policy_version`.
  3. Active system `model_version` matches authorized `model_version`.
- Any mismatch or stale token immediately rejects execution and routes the case to `ESCALATE` with `execution_status: "BLOCKED"`.

### 3. Transactional Outbox Pattern
- Recovery intents are written to a durable PostgreSQL `execution_intents` table before external dispatch.
- Decouples decisioning from network execution, ensuring crash resilience and operational auditability.

### 4. Circuit Breaker Subsystem
- Protects downstream payment gateway APIs from cascading failure loops.
- **`CLOSED`**: All requests allowed. Consecutive network failures increment failure count.
- **`OPEN`**: Tripped after 3 consecutive failures. Rejects external requests immediately for a 60-second cooldown window.
- **`HALF_OPEN`**: Allows exactly one probe request. A successful probe resets state to `CLOSED`; a failed probe returns state to `OPEN`.

### 5. Reconciliation State Machine
- External gateway timeouts or HTTP 5xx responses never trigger blind retries.
- The system transitions the intent to `UNKNOWN` and schedules asynchronous status queries (`GET /v1/payments/{id}`) against gateway truth until resolving to `CONFIRMED` or `FAILED`.

## Reliability Test Suite Coverage

The reliability test suite (`tests/test_reliability_drills.py`) exercises:
1. Circuit breaker transitions (`CLOSED → OPEN → HALF_OPEN → CLOSED`).
2. Single-probe concurrency in `HALF_OPEN`.
3. Inbound authorization rejection on expired TTL (>300s).
4. Inbound authorization rejection on `policy_version` or `model_version` mismatch.
5. Ingestion idempotency on duplicate Razorpay webhook deliveries.
6. Reconciliation state machine transitions on ambiguous network timeouts.
