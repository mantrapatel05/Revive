# Judge Q&A Preparation

## Why not just rules?
Rules enforce hard constraints. ML estimates heterogeneous action outcomes. REVIVE optimizes risk-adjusted incremental value instead of applying the same intervention to every case.

## How do you know the synthetic benchmark is honest?
The Razorpay lifecycle is grounded in documented platform semantics. Recovery probabilities and outcomes are explicitly synthetic and are not represented as production statistics.

## What happens if the model recommends a forbidden action?
The model has no execution authority. The deterministic policy gate removes infeasible actions before optimization.

## Why can ML-only beat REVIVE?
Because ML-only is unconstrained. REVIVE deliberately trades some theoretical value for hard safety guarantees. Safe Policy Capture measures how much of the best constrained policy value REVIVE captures.

## How do you prevent duplicate money actions?
Webhook event IDs are deduplicated, execution intents use unique decision IDs, and ambiguous results go through reconciliation rather than blind retry.

## What if the provider times out after accepting the action?
Execution becomes UNKNOWN and is reconciled against provider state.

## How is uncertainty handled?
Bootstrap ensemble dispersion is converted into a conservative lower-confidence value for decisioning; probability calibration is handled separately.

## Why single-process + SQLite? (superseded — see Postgres migration)
The challenge rewards proof of engineering judgment, not infrastructure volume. The project keeps distributed complexity out until a measured requirement exists.

## What is the strongest limitation?
The recovery probability environment is synthetic. The project therefore claims decision-system rigor and test-mode integration, not production recovery-rate claims.

## Why is SubscriptionStateMachine not wired into the live webhook path?
The `SubscriptionStateMachine` class was built as a formal specification of legal state transitions (e.g. `CREATED -> AUTHENTICATED -> ACTIVE`). Currently, state transitions are validated inline within the pipeline. Formal integration of this class into the reconciliation boundary is a known integration gap, not an oversight, and it remains in the codebase as the canonical transition specification for future enforcement.

---

## Real Generated Message Examples (Post-Governor Stage Exhibits)

Every message below is generated **only after** Governor/Policy Gate approval, selected deterministically by `(action, decline_class)`, personalized under strict 2-sentence constraints, and passed through automated tone safety validation:

### Example 1: Nudge for Soft Decline (Transient Delay / Low Balance)
- **Scenario / Case**: Customer *Ananya Deshmukh*, Amount: ₹1,999.00, Decline Reason: `insufficient_funds`
- **Action**: `NUDGE` | **Diagnosis**: `soft` | **Channel**: `whatsapp`
- **Template Intent**: `payment_retry_link`
- **Tone Check**: `PASS` (0 prohibited words, 2 sentences)
- **Verbatim Message (Read Aloud)**:
  > *"Hi Ananya Deshmukh, your subscription renewal of ₹1,999.00 experienced a temporary processing delay. You can complete your renewal securely using this link: https://rzp.io/rzp/plink_TVDe77AbC99"*

### Example 2: Nudge for Hard Decline (Card Expired)
- **Scenario / Case**: Customer *Rohan Verma*, Amount: ₹2,499.00, Decline Reason: `card_expired`
- **Action**: `NUDGE` | **Diagnosis**: `hard` | **Channel**: `sms`
- **Template Intent**: `card_expired_reminder`
- **Tone Check**: `PASS` (0 prohibited words, 2 sentences)
- **Verbatim Message (Read Aloud)**:
  > *"Hi Rohan Verma, your subscription payment of ₹2,499.00 could not be processed as your card on file has expired. Please update your payment details here: https://rzp.io/rzp/plink_TVDe88XyZ12"*

### Example 3: Manual Recovery Checkout Link (Direct Action)
- **Scenario / Case**: Customer *Vikram Mehta*, Amount: ₹4,999.00, Decline Reason: `gateway_timeout`
- **Action**: `MANUAL_RECOVERY` | **Diagnosis**: `soft` | **Channel**: `whatsapp`
- **Template Intent**: `payment_link_direct`
- **Tone Check**: `PASS` (0 prohibited words, 1 sentence)
- **Verbatim Message (Read Aloud)**:
  > *"Hi Vikram Mehta, here is your secure checkout link for ₹4,999.00 to keep your subscription active: https://rzp.io/rzp/plink_TVDe99Direct7"*

### Example 4: Hard Decline Payment Method Update
- **Scenario / Case**: Customer *Priya Sundaram*, Amount: ₹1,499.00, Decline Reason: `card_disabled`
- **Action**: `MANUAL_RECOVERY` | **Diagnosis**: `hard` | **Channel**: `whatsapp`
- **Template Intent**: `update_payment_method`
- **Tone Check**: `PASS` (0 prohibited words, 2 sentences)
- **Verbatim Message (Read Aloud)**:
  > *"Hi Priya Sundaram, we were unable to process your payment of ₹1,499.00. Please update your payment method to avoid subscription interruption: https://rzp.io/rzp/plink_TVDe44Update8"*

### Example 5: Blocked Coercive Tone Injection (Fail-Closed Exhibit)
- **Scenario / Case**: Synthetic prompt injection attempting to coerce customer
- **Attempted Text**: *"You must pay immediately or your account will face legal action and penalty."*
- **Tone Check**: `FAIL` (`Prohibited coercive keyword: 'must'`, `'immediately'`, `'legal action'`, `'penalty'`)
- **Governor Enforcement**: Action immediately demoted to `ESCALATE`; message blocked from transmission and logged to audit ledger with status `BLOCKED_TONE_CHECK`.

---

## Reviewer Script: Live Stage Failure Injections (3:30–4:15 Slot)

Use these one-command triggers during the live 5-minute presentation to prove REVIVE's fail-closed reliability live in front of the judges:

### 1. All-in-One Live Drill (Recommended for Stage)
- **Exact Command**:
  ```bash
  python scripts/rehearse_failure_injection.py --scenario all
  ```
- **Spoken Script (Read Aloud as it executes)**:
  > *"Judges, let's inject live failures right now into REVIVE's runtime:*
  > *First, duplicate webhooks: Razorpay fires an identical retry, and REVIVE rejects it at the database constraint boundary with zero duplicate link dispatches.*
  > *Second, malformed LLM output: when the model produces invalid JSON or schema violations, Pydantic catches it immediately, fails closed to ESCALATE without crashing the batch, and preserves the raw payload for audit.*
  > *Third, malformed message generation: schema errors or tone violations immediately suppress dispatch and flag for human review.*
  > *Fourth, audit tamper attempt: connecting as our runtime role and attempting an UPDATE or DELETE is immediately aborted by database engine triggers — proving our log is 100% append-only.*
  > *Fifth, gateway outage: consecutive 503 errors trip our circuit breaker to OPEN, short-circuiting downstream API calls to prevent cascading storms.*
  > *Zero crashes, zero double debits, and 100% deterministic safety."*

---

### 2. Scenario 1: Malformed LLM Diagnosis Output
- **Exact Command**:
  ```bash
  python scripts/rehearse_failure_injection.py --scenario malformed_llm_diagnosis
  ```
- **Spoken Script**:
  > *"Here we simulate a live LLM hallucination where the classifier returns malformed JSON with an invalid category. Notice that rather than guessing or retrying in an infinite loop, Pydantic raises, the governor immediately fails closed to human review (ESCALATE), the raw payload is saved in the audit log for inspection, and the rest of the batch continues without interruption."*

---

### 3. Scenario 2: Malformed LLM Message Fill Output
- **Exact Command**:
  ```bash
  python scripts/rehearse_failure_injection.py --scenario malformed_llm_messaging
  ```
- **Spoken Script**:
  > *"Here we simulate an LLM message fill returning malformed JSON or violating tone constraints. The tone safety guard catches the schema violation, suppresses customer dispatch, sets status to BLOCKED_TONE_CHECK, and routes the case to human review while recording the full attempt in the audit ledger."*

---

### 4. Scenario 3: Engine-Enforced Audit Tamper Attempt (10-Second Demo)
- **Exact Command**:
  ```bash
  python scripts/rehearse_failure_injection.py --scenario audit_tamper
  ```
- **Spoken Script**:
  > *"Judges often ask: 'How do we know nobody edited this audit log?' Let's try to edit it right now. We issue direct UPDATE and DELETE queries against an existing audit record. The database engine immediately aborts the transaction with an IntegrityError / InsufficientPrivilege exception — proving that immutability is enforced at the database engine level, not by application honor code."*

---

### 5. Scenario 4: Provider Down & Circuit Breaker Trip
- **Exact Command**:
  ```bash
  python scripts/rehearse_failure_injection.py --scenario provider_down
  ```
- **Spoken Script**:
  > *"Here we simulate Razorpay's API throwing consecutive 503 Service Unavailable errors. Watch the state machine: attempts 1 through 3 fail gracefully, triggering the circuit breaker from CLOSED to OPEN. Requests 4 and 5 are instantly short-circuited without making any external network requests, preventing cascading gateway stampedes while logging immutable records to the audit ledger."*

---

### 6. Scenario 5: Webhook Idempotency & Delivery Retry Suppression
- **Exact Command**:
  ```bash
  python scripts/rehearse_failure_injection.py --scenario idempotency
  ```
- **Spoken Script**:
  > *"When payment gateways retry delivery over unstable networks, race conditions can trigger duplicate charges. Here we send two simultaneous identical webhook events: the first is accepted, while the second is detected and suppressed at the unique database index before reaching any decision code."*
