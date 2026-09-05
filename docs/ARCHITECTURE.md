# REVIVE 6.0 — Architectural Specification

## System Overview

REVIVE 6.0 is an enterprise revenue recovery decision engine that evaluates failed recurring subscription payments on payment gateways (such as Razorpay). The engine formulates recovery as a constrained causal decision problem, estimating heterogeneous treatment effects over the default gateway retry baseline (`WAIT`), enforcing non-negotiable safety policies, and executing side-effecting operations through an idempotent outbox.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           EVENT INGESTION LAYER                         │
│  - POST /api/webhook/razorpay                                           │
│  - HMAC-SHA256 Signature Verification (X-Razorpay-Signature)            │
│  - Idempotent Inbox: PostgreSQL webhook_events UNIQUE(event_id)         │
│  - Duplicate → HTTP 200 {status: duplicate} suppressed                 │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  INBOUND AUTHORIZATION GATE (fail-closed)               │
│  - ExecutionAuthorization TTL = 300s, bound to                           │
│    policy_version + model_version + event_id + action                   │
│  - Invalid/expired/mismatched → immediate ESCALATE (AUTH-VER-001)       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              DECLINE DIAGNOSIS + DRIFT GATING (pre-model)               │
│  - Diagnosis: DECLINE_RULES exact match → Groq LLM fallback             │
│    (soft / hard / risk / unclear, Pydantic-validated, fail-closed)     │
│  - Drift: DriftDetector on live cases only —                            │
│    z-score > 3.0 or value outside [min,max] training range              │
│  - PSI batch drift util threshold 0.20 (monitoring)                      │
│  - Drift flagged → immediate ESCALATE, no ML scoring                    │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    CAUSAL T-LEARNER INFERENCE ENGINE                    │
│  - Action-Specific Bootstrap Ensemble (8 Base Logistic Estimators)     │
│  - Out-of-Bag (OOB) Isotonic Probability Calibration                    │
│  - Bootstrap Standard Deviation Dispersion Proxy: σ(a, x)               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   COUNTERFACTUAL ECONOMICS & ARBITRATION                │
│  - Expected Net Value: V(a, x) = P_cal(a, x) * Amount - Cost(a, x)      │
│  - Incremental Net Value: ΔV(a, x) = V(a, x) - V(WAIT, x)               │
│  - Customer Fatigue Penalty (₹50 if contact_count_7d > 2)               │
│  - Lower Confidence Bound (LCB) Risk Discounting: ΔV - z * σ            │
│    (z=2.0 Conservative, 1.0 Balanced, 0.0 Aggressive)                   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   DETERMINISTIC SAFETY POLICY GATE                      │
│  - Hard Checks (12): CUST-OPT-001, SUB-STATE-001, WAIT-STATE-001,       │
│    FIN-AUTO-002, RET-LIMIT-001, INV-ELIG-001, PM-ELIG-001,               │
│    DUP-NATIVE-001, PROB-MIN-001, TIME-QUIET-001, FREQ-DAILY-001,         │
│    RISK-DECLINE-001 (risk_decline → block)                               │
│  - Permitted Action Subspace Filtering (Feasible Actions Only)          │
│  - Abstain: best non-WAIT ΔV ≤ 0 → WAIT or ESCALATE                     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              POST-GOVERNOR MESSAGING + AUTHORIZATION                    │
│  - Template selection: TEMPLATE_INTENTS[(action, decline_class)]        │
│  - Tone Safety Guard: blocklist + ≤2 sentences; fail-closed → ESCALATE │
│  - ExecutionAuthorization created (TTL 300s) and validated              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    TRANSACTIONAL OUTBOX & EXECUTION                     │
│  - Atomic TX: decision_records + execution_intents PENDING              │
│    (Unique Decision Hash Key; ON CONFLICT DO NOTHING)                   │
│  - Claim: PENDING → PROCESSING (FOR UPDATE SKIP LOCKED)                 │
│  - Circuit Breaker: CLOSED → OPEN (3 fails, 60s cooldown) → HALF_OPEN  │
│    (single probe; success→CLOSED, fail→OPEN)                            │
│  - Live Razorpay Adapter: POST /v1/payment_links → plink_* / rzp.io URL│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    RECONCILIATION & AUDIT LEDGER                        │
│  - EXECUTION_REQUESTED → PAYMENT_PENDING (link created)                 │
│  - Ambiguous / Timeout → UNKNOWN → Reconciliation Queue                 │
│    GET /v1/payment_links/{id} → CONFIRMED / FAILED                      │
│  - Webhook correlation: payment_link.paid / payment.captured → CONFIRMED│
│  - Immutable Ledger: feature snapshot + model/policy/scenario versions  │
│    audit_logs (SELECT+INSERT only; UPDATE/DELETE revoked)                │
└─────────────────────────────────────────────────────────────────────────┘
```

## Architectural Boundaries

### 1. Ingestion Boundary
All external incoming events must be verified against HMAC-SHA256 signatures before entering the decision pipeline. Events are registered into PostgreSQL `webhook_events` with a `UNIQUE(event_id)` constraint; duplicate event IDs are acknowledged with HTTP 200 `{status: duplicate}` and suppressed without triggering redundant decision runs or outbox intents. See `app/events/signature.py:verify_razorpay_signature` and `app/db.py:enqueue_webhook_event`.

### 2. Probabilistic vs Deterministic Authority Boundary
The machine learning subsystem (Calibrated T-Learner) is strictly advisory. It computes estimated probabilities and uncertainty dispersion. It possesses zero execution authority. The deterministic policy gate evaluates all hard constraints and filters the action subspace before economics selection occurs.

### 3. Execution Boundary
External side effects (creating Razorpay payment links, triggering nudges) require an `ExecutionAuthorization` token. The authorization is cryptographically bound to the active `policy_version`, `model_version`, `event_id`, and `action`, with a strict 300-second TTL. Stale or version-mismatched authorizations are rejected before any network call.

### 4. Reconciliation Boundary
External gateway timeouts or ambiguous network responses never trigger blind retries. Instead, the execution record transitions to `UNKNOWN` and enters a dedicated reconciliation loop that queries gateway state truth before resolving to `CONFIRMED` or `FAILED`.

## Persistence Topology

The reference implementation intentionally uses a single Python process and PostgreSQL 16 as the sole persistence backend to ensure reproducible execution without distributed infrastructure complexity (Kafka, Redis, Kubernetes).

| Table | Purpose | Key Constraint |
| --- | --- | --- |
| `webhook_events` | Idempotent inbox for inbound Razorpay events | `UNIQUE(event_id)` — duplicate delivery suppressed before pipeline execution |
| `decision_records` | Immutable decision ledger with feature snapshot + versions | `UNIQUE(decision_id)` |
| `execution_intents` | Durable outbox queue for side-effecting actions | `UNIQUE(decision_id)`, `PENDING → PROCESSING → EXECUTION_REQUESTED/CONFIRMED/FAILED/UNKNOWN` |
| `audit_logs` | Append-only audit trail | `revive_app` has `SELECT, INSERT` only; `UPDATE`/`DELETE` revoked at engine level |
| `approval_queue` | Human-review queue for `ESCALATE` cases | Pending/resolved lifecycle |
| `merchant_config` | Persisted risk and intervention controls | Single-row (`id=1`) merchant overrides |

Migrations are applied via the `revive_admin` role (`schema.sql` + `scripts/migrate_db.py` / `make db-migrate`); runtime uses the restricted `revive_app` role. Legacy paths `data/decisions.db` / `data/audit_log.jsonl` are superseded — see `app/db.py:PostgresConnection` and `app/audit/logger.py`.
