# REVIVE — Failure Postmortem

## 1. Sampled Oracle Evaluation

**Problem:** one stochastic run could make a worse policy appear better.

**Fix:** primary benchmark now uses true expected value.

**Lesson:** separate expected policy quality from realized randomness.

## 2. Calibration Naming

**Problem:** bootstrap standard deviation was not actual probability calibration.

**Fix:** added development/OOB calibration.

**Lesson:** uncertainty and calibration are different.

## 3. Slow Bootstrap Inference

**Problem:** naive per-case/per-model inference was too expensive.

**Fix:** batch/vectorize prediction and avoid unnecessary inference overhead.

**Lesson:** statistical sophistication must remain operationally practical.

## 4. Ambiguous External Result

**Problem:** a timeout may occur after an external provider accepted an operation.

**Fix:**

```text
UNKNOWN
 ↓
RECONCILIATION
 ↓
CONFIRMED / FAILED
```

**Lesson:** request failure does not imply operation failure.

## 5. Duplicate Webhook

**Problem:** delivery retries can duplicate business processing.

**Fix:** event-ID inbox/idempotency boundary.

**Lesson:** at-least-once delivery requires idempotent effects.

## 6. ML Overriding Safety

**Problem:** high confidence could recommend a prohibited action.

**Fix:** deterministic policy gate before execution.

**Lesson:** model confidence cannot override hard safety.

## 7. Overengineering

**Problem:** infrastructure complexity can grow without improving the demonstrated system.

**Fix:** retain single-process + SQLite until evidence demands otherwise. (superseded — see Postgres migration)

**Lesson:** production-minded ≠ maximum infrastructure.

## 5.1 Failure Drills & Test Suite Verification
All drills are actively tested and passing (22 passed, 0 failed, 0 xfailed):

1. **Duplicate Webhook Delivery**: Tested via `test_duplicate_event_id_ignored` and `scripts/rehearse_failure_injection.py` — atomic idempotency lock suppresses duplicate execution intents.
2. **Invalid Signature Verification**: Tested via `test_signature_verification_success` & `test_tampered_payload_rejected` — HMAC-SHA256 digests rejected with HTTP 401.
3. **Stale Execution Authorization (TTL Expiry)**: Tested via `test_stale_authorization_rejected` — tokens with past `expires_at` are rejected.
4. **Model & Policy Version Mismatch**: Tested via `test_model_policy_version_mismatch_blocked` — authorizations from mismatched versions are safely blocked to `ESCALATE`.
5. **Circuit Breaker Trip on N Failures**: Tested via `test_circuit_breaker_opens_after_n_failures` — transitions from `CLOSED` to `OPEN` after 3 consecutive failures.
6. **Circuit Breaker Half-Open Single Probe**: Tested via `test_circuit_breaker_half_open_single_probe` — permits exactly one probe request after timeout elapses.
7. **Circuit Breaker Recovery on Probe Success**: Tested via `test_circuit_breaker_half_open_success_closes` — successful probe resets state to `CLOSED`.
8. **Real-Time Distribution Shift (OOD)**: Tested via `test_drift_detector_flags_anomalies` — feature vectors exceeding $z > 3.0$ or boundary ranges route directly to `ESCALATE`.
9. **Gateway Timeout & Ambiguous Operation**: Reconciler state machine transitions `UNKNOWN → RECONCILIATION → CONFIRMED/FAILED` preventing blind duplicate retries.
10. **Deterministic Safety Boundary Collisions**: Tested across 100 adversarial cases with 0 unsafe automated actions.
