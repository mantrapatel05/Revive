# REVIVE — Razorpay Test Mode Integration & Lifecycle Mapping

## Production Concept Mapping

| REVIVE Concept | Razorpay API / Webhook Entity | Implementation in REVIVE |
|---|---|---|
| Inbound Event | `subscription.charged`, `payment.failed`, `invoice.paid` | Ingested via `POST /api/webhook/razorpay` |
| Webhook Verification | `X-Razorpay-Signature` HMAC-SHA256 digest | Verified via `app.events.signature.verify_razorpay_signature` using `RAZORPAY_WEBHOOK_SECRET` |
| Idempotency Boundary | Event ID / `x-razorpay-event-id` | Tracked via PostgreSQL `webhook_events` table; duplicates rejected before pipeline execution |
| Action: `WAIT` | Gateway Native Auto-Retry Schedule | Engine suppresses outbound interventions, allowing gateway cron retry to proceed (`NO_ACTION`) |
| Action: `NUDGE` | Customer Notification / SMS / Email | Prepares localized recovery notification with custom payment link (`EXECUTION_REQUESTED` / `PAYMENT_PENDING`) |
| Action: `MANUAL_RECOVERY` | Razorpay Payment Link API (`POST /v1/payment_links`) | Authorized via `ExecutionAuthorization`, creates actionable payment link (`EXECUTION_REQUESTED` / `PAYMENT_PENDING`) |
| Action: `ESCALATE` | Merchant Support Ticket / Manual Review Queue | Recorded in `approval_queue` for human risk officer review (`QUEUED`) |
| Execution Authorization | Internal Cryptographic Grant | 300s TTL token bound to `policy_version`, `model_version`, and `event_id` |
| Transactional Outbox | Durable Intent Queue | PostgreSQL `execution_intents` with atomic status updates (`EXECUTION_REQUESTED → CONFIRMED / FAILED`) |
| Reconciliation | Gateway Event / Status Inquiry (`GET /v1/payment_links/{id}`) | Lifecycle state machine: `PAYMENT_PENDING → CONFIRMED / FAILED / UNKNOWN` |
| Audit Ledger | Compliance & Decision History | Immutable JSONL append-only log (`data/audit_log.jsonl`) and PostgreSQL `audit_logs` ledger |

---

## Explicit 5-Step Payment Link & Recovery Lifecycle

Creating a Razorpay Payment Link represents initiating an externally actionable payment request—it does **NOT** prove that subscription revenue has been recovered. The lifecycle strictly distinguishes:

```text
[ 1. REVIVE Decision ]
         │
         ▼
[ 2. Policy Gate & Authorization ]
         │
         ▼
[ 3. Create Payment Link ] ─── (POST /v1/payment_links)
         │
         ▼
[ 4. Execution State: EXECUTION_REQUESTED (Initial Final State: PAYMENT_PENDING) ]
         │
         ├─────────────────────────────────────────┐
         │ (Customer completes checkout)           │ (Customer abandons / link expires)
         ▼                                         ▼
[ Inbound: payment_link.paid / payment.captured ]  [ Inbound: payment_link.expired / cancelled ]
         │                                         │
         ▼                                         ▼
[ 5. Reconciliation Subsystem ]            [ 5. Reconciliation Subsystem ]
         │                                         │
         ▼                                         ▼
   CONFIRMED                                     FAILED
 (Proof of Revenue Recovery)               (No Recovery / Link Closed)
```

---

## End-to-End Test Mode Lifecycle Flow

```text
[ Razorpay Test Mode / Inbound Source ]
              │
              │ 1. Inbound Webhook (signed payload)
              ▼
   POST /api/webhook/razorpay
              │
              │ 2. Verify HMAC-SHA256 signature
              ▼
   app.events.signature.verify_razorpay_signature()
              │
              │ 3. Check duplicate event ID in PostgreSQL
              ▼
   app.events.idempotency.record_event()
              │
              ├─[ Duplicate ] ───► HTTP 200 { status: "duplicate", action: "suppressed" }
              │
              ▼ [ New Event ]
   app.pipeline.RecoveryPipeline.process()
              │
              │ 4. Extract 10-feature vector & evaluate PSI drift
              ▼
   app.monitoring.drift.DriftDetector.detect_case_drift()
              │
              │ 5. Compute calibrated uplift & bootstrap intervals
              ▼
   app.models.calibrated_tlearner.CalibratedTLearner.predict_all_actions()
              │
              │ 6. Rank incremental net value with fatigue penalty
              ▼
   app.economics.EconomicsEngine.rank_incremental()
              │
              │ 7. Check deterministic policy constraints
              ▼
   app.policy.gate.PolicyGate.feasible()
              │
              │ 8. Generate Execution Authorization (TTL = 300s)
              ▼
   app.execution.authorization.ExecutionAuthorization.create()
              │
              │ 9. Enqueue durable outbox intent (status: PENDING)
              ▼
   app.execution.outbox.enqueue_execution_intent()
              │
              │ 10. Execute Live Payment Link Creation on Razorpay Test Mode
              ▼
   app.execution.live_executor.LiveExecutor._execute_manual_recovery()
              │
              ▼
   Razorpay API Response: plink_TT8lqqG4T7s42h (https://rzp.io/rzp/Ypx1OXIi)
              │
              │ 11. Record execution intent: status = EXECUTION_REQUESTED, final_state = PAYMENT_PENDING
              ▼
   app.execution.outbox.mark_intent_status()
              │
              │ 12. Record immutable audit entry
              ▼
   app.audit.logger.AuditLogger.log()
              │
              │ 13. [Asynchronous] Customer pays via Razorpay hosted checkout
              ▼
   Inbound Webhook: payment_link.paid / payment.captured
              │
              │ 14. Correlate payment_link_id & reconcile final state
              ▼
   app.execution.reconciliation.reconcile_webhook_event()
              │
              ▼
   Final State Updated: CONFIRMED (Recorded in PostgreSQL & Audit Log)
```

---

## Verification Evidence

Live execution against Razorpay Test Mode was validated with real test-mode API credentials:
- Ingested authentic HMAC-SHA256 signed webhook for event `evt_sub_test_001`.
- Checked idempotency: duplicate delivery was rejected with zero duplicate payment link calls and zero duplicate database intent rows.
- Generated live payment link `plink_TT8lqqG4T7s42h` with direct checkout URL `https://rzp.io/rzp/Ypx1OXIi`.
- Verified that Payment Link creation sets status `EXECUTION_REQUESTED` and `final_state = PAYMENT_PENDING`.
- Verified that provider payment events (`payment_link.paid`) transition state to `CONFIRMED` and correlate to the original case and decision ID.
- Verified that network failures or timeouts return `UNKNOWN` without fabricating false recovery confirmations.

---

## Decline Reason Diagnosis & Classification Architecture

Inbound payment failures from Razorpay webhooks (`payment.failed`, `subscription.pending`) carry raw decline reason strings, gateway error codes, or bank-specific failure descriptions. REVIVE parses and classifies decline reasons into three semantic categories before passing feature representations to the causal uplift model:

1. **Soft Decline (`soft`)**: Transient failures (e.g. low balance, gateway downtime, temporary bank timeout) where automated retry or customer nudge has high recovery probability.
2. **Hard Decline (`hard`)**: Permanent failures (e.g. card expired, account closed, invalid CVV/number) where retrying the existing instrument is guaranteed to fail.
3. **Risk Decline (`risk`)**: Suspected fraud, stolen cards, or compliance blocks where automated outreach is strictly blocked and escalated to human review.

### Deterministic `DECLINE_RULES` Mapping Table

| Razorpay Error / Reason Key | Decline Class | Recovery Implication | Automated Outreach Allowed? |
|---|---|---|---|
| `insufficient_funds` / `insufficient_fund` | `soft` | Customer balance low; eligible for Nudge or Wait | Yes (subject to fatigue cap) |
| `payment_timed_out` / `gateway_timeout` | `soft` | Network/switch timeout; retryable | Yes |
| `gateway_downtime` / `gateway_error` | `soft` | Temporary gateway issue; prefer native retry (`WAIT`) | Yes |
| `bank_declined` / `bank_offline` | `soft` | Issuer switch temporary reject | Yes |
| `authentication_failed` / `otp_not_entered` | `soft` | Customer dropped off during 3DS; eligible for Nudge link | Yes |
| `card_expired` / `expired_card` | `hard` | Expired card token; require card update nudge | Yes (NUDGE only; direct charge blocked) |
| `invalid_card` / `invalid_cvv` | `hard` | Malformed credentials; cannot recharge | Yes (NUDGE update link only) |
| `card_disabled` / `account_closed` | `hard` | Terminal account closure | No (manual resolution required) |
| `issuer_suspected_fraud` / `fraud_detected` | `risk` | Issuer anti-fraud alert; risk of chargeback | **NO — Strictly Blocked to `ESCALATE`** |
| `do_not_honor` / `stolen_card` / `lost_card` | `risk` | Stolen instrument or bank security block | **NO — Strictly Blocked to `ESCALATE`** |
| `compliance_block` / `security_violation` | `risk` | AML/KYC or regulatory halt | **NO — Strictly Blocked to `ESCALATE`** |

### Strict LLM Fallback for Unfamiliar Decline Codes

When a regional bank or new card network returns an unfamiliar or free-text error code (e.g. `custom_hdfc_switch_timeout_code_91` or `"Declined by issuer security sub-node 402"`):

1. **Groq LLM Invocation**: The pipeline calls Groq (`openai/gpt-oss-120b` or configured LLM) with a strict zero-shot system prompt constrained to classify into exactly one of `[soft_decline, hard_decline, risk_decline, unclear]`.
2. **Pydantic Schema Validation**: The raw JSON output is validated against `LLMDiagnosisOutput(decline_class: Literal[...], confidence: float, reasoning: str)`.
3. **Fail-Closed Guarantee**: If the LLM produces malformed JSON, invents categories, or times out, REVIVE **fails closed** to `{"decline_class": "unclear", "source": "llm_failed", "confidence": 0.0}` without unbounded retry loops, ensuring downstream policy routes safely to human review (`ESCALATE`).

#### Example Unfamiliar Code Resolution:
- **Inbound Event**: `{"error_code": "CUSTOM_AXIS_NODE_ERR_88", "error_description": "Cardholder daily velocity ceiling reached at switch"}`
- **LLM Diagnosis Output**:
  ```json
  {
    "decline_class": "soft",
    "reason": "CUSTOM_AXIS_NODE_ERR_88",
    "source": "llm",
    "confidence": 0.92,
    "reasoning": "Daily velocity limit is a transient rate-limit at issuer switch; customer is contactable after switch reset."
  }
  ```

---

## Claim Boundary

1. **Test Mode Execution Scope**: Real-execution wiring against Razorpay's REST API (`https://api.razorpay.com/v1/payment_links`) is implemented, operational, and verified in Test Mode. The engine creates authentic payment links with real merchant IDs and valid hosted checkout pages.
2. **Payment Link Semantics**: Payment Link creation initiates an actionable payment request (`EXECUTION_REQUESTED`). It is not treated as proof of payment recovery; final recovery state (`CONFIRMED`) is strictly established from subsequent provider evidence (webhooks or reconciliation inquiry).
3. **Production Boundary**: Live real-money settlement requires swapping test credentials for production API keys (`rzp_live_...`) with production merchant banking settlement rails and webhook secret rotation.
4. **Automated Recurring Subscriptions**: In Razorpay, automated merchant-initiated card re-authorization without customer 3DS intervention requires active e-Mandate / SI registration on the subscription entity. Where native retry is already scheduled by the gateway, REVIVE strictly respects the `WAIT` boundary to prevent double-debit collisions.
