# REVIVE: Risk-Aware Incremental Revenue Recovery Engine

## System Overview

REVIVE is an enterprise-grade revenue recovery decision engine designed for recurring subscription payments on payment gateways (specifically Razorpay). In high-volume subscription commerce, payment failures are typically handled by static cron-based retry schedules or aggressive blanket notifications. Both approaches introduce severe operational inefficiencies: blanket retries incur unnecessary transaction processing and SMS/notification costs, while premature manual outreach creates customer contact fatigue and elevates churn risk.

REVIVE formulates subscription recovery as a constrained causal decision problem. Rather than estimating absolute recovery probability, the engine models **incremental recovery uplift** over the payment gateway's native retry trajectory (`WAIT`). Every intervention is evaluated under bootstrap uncertainty quantification, subjected to non-negotiable deterministic safety policies, and executed through an idempotent, fail-closed outbox subsystem.

---

## Architectural Topology

```text
[ Razorpay Inbound Webhook ]
            │
            ▼
[ Cryptographic HMAC-SHA256 & Idempotency Gate ] ─── (Duplicate Event) ──> HTTP 200 / ACK (No-op)
            │
            ▼ (Verified Unique)
[ Feature Extraction & Real-Time Drift Detection ] ── (OOD Anomaly: z > 3.0) ──> [ ESCALATE to Ops ]
            │
            ▼ (In-Distribution)
[ Causal Uplift ML Engine (Calibrated T-Learner) ]
    ├─ Bootstrap Ensemble Mean: P(Success | Action)
    ├─ Uncertainty Variance: sigma(Action)
    └─ Out-of-Bag (OOB) Isotonic Probability Calibration
            │
            ▼
[ Incremental Economic Optimization ]
    ├─ Baseline: Delta(Action) = E[Net(Action)] - E[Net(WAIT)]
    ├─ Merchant Risk Margin: Risk Adjustment (z * sigma)
    └─ Customer Fatigue Penalty: -lambda * ContactCount
            │
            ▼
[ Deterministic Policy Governance Gate ]
    ├─ Hard Constraints: Opt-Outs, Amount Ceilings, Native Retry Collisions
    └─ Feasibility Mask: [ WAIT, NUDGE, MANUAL_RECOVERY, ESCALATE ]
            │
            ▼
[ Execution & Reconciliation Subsystem ]
    ├─ Version-Validated Authorization Token
    ├─ Circuit Breaker Protection (Closed / Half-Open / Open)
    ├─ Live Razorpay Test Mode Executor (POST /v1/payment_links)
    └─ Durable Transactional Outbox & Reconciler
            │
            ▼
[ SQLite Decision Store & Append-Only Audit Logger ]
```

---

## Core Capabilities (Implemented & Verified)

### 1. Causal Uplift Modeling with Uncertainty Quantification
- **Architecture**: Action-specific T-Learner built on an 8-fold bootstrap ensemble of logistic regression estimators.
- **Uncertainty Tracking**: Computes both predictive mean $P(\text{Recovery} \mid a)$ and epistemic uncertainty $\sigma(a)$ across all actions: `WAIT`, `NUDGE`, `MANUAL_RECOVERY`, `ESCALATE`.
- **Isotonic Calibration**: Employs Out-of-Bag (OOB) isotonic regression mapping to ensure predicted probabilities match empirical observation frequencies across the entire risk surface.

### 2. Incremental Economic Objective Formulation
- **Marginal Net Value**: Decisions optimize incremental net yield over the counterfactual baseline (`WAIT`), preventing unnecessary interventions on subscriptions that would have recovered natively:
  $$\Delta \text{Value}(a) = \left( P(a) \cdot \text{Amount} - \text{Cost}(a) \right) - \left( P(\text{WAIT}) \cdot \text{Amount} \right)$$
- **Merchant Utility Tuning**: Supports parameterized risk tolerances (`CONSERVATIVE`, `BALANCED`, `AGGRESSIVE`) via penalty parameter $z \in [0.0, 2.0]$.
- **Customer Fatigue Mitigation**: Integrates an explicit INR 50.00 penalty for invasive outreach on accounts exceeding 2 communications in a rolling 7-day window.

### 3. Deterministic Safety & Governance Policy Gate
- **Hard Constraint Boundaries**: Interventions are strictly constrained by business rules that supersede model recommendations:
  - Immediate escalation for customer opt-outs (`customer_opted_out == True`).
  - Prohibition of automated intervention during active native retries (`native_retry_scheduled == True`).
  - Mandatory human approval for transactions exceeding merchant risk thresholds (INR 5,000.00).
- **Adversarial Integrity**: Verified 0 unsafe automated actions across 100 synthetic adversarial stress tests.

### 4. Enterprise Execution & Reliability Architecture
- **Cryptographic Webhook Ingestion**: Authentic HMAC-SHA256 signature verification over incoming payloads using `RAZORPAY_WEBHOOK_SECRET`.
- **Strict Ingestion Idempotency**: Atomic SQLite transaction locking ensures duplicate webhook deliveries receive HTTP 200 confirmations without duplicate downstream processing or secondary payment link creation.
- **Live Razorpay Test Mode Execution**: Real API integration creating hosted Payment Links (`POST /v1/payment_links`) in Razorpay Test Mode for `MANUAL_RECOVERY` workflows.
- **Runtime Authorization & Version Gate**: Strict validation of `ExecutionAuthorization` tokens verifying non-expired TTLs and exact matching of active `policy_version` and `model_version` before execution.
- **Fault-Tolerant Circuit Breaker**: State-machine circuit breaker with configurable failure thresholds ($N=3$), probe request gating in `HALF_OPEN` state, and exponential backoff recovery.
- **Live Distribution Shift Interception**: In-memory drift detection over 13 numeric features; automatically halts automated execution and routes anomalous vectors ($z > 3.0$ or boundary violations) straight to human escalation.

---

## Empirical Benchmark & Verification Results

All metrics are derived from the held-out evaluation dataset generated via the verified evaluation framework:

```text
========================================================================================
POLICY BENCHMARK SUMMARY
========================================================================================
Strategy                Expected Net Value (INR)    Realized Net Value (INR)
----------------------------------------------------------------------------------------
Platform Native (WAIT)  124,795.48                  114,758.00
Rule-Based Heuristic    200,355.55                  185,983.60
Unconstrained ML-Only   243,564.93                  253,416.60
REVIVE Decision Engine  141,418.54                  128,646.20
Constrained Oracle      142,541.45                  130,840.60
Theoretical Oracle      248,235.15                  264,436.60
----------------------------------------------------------------------------------------
Safe Policy Capture:    93.67% (Deterministic across seeds; 97.45% under zero-fatigue baseline)
Mean Decision Regret:   INR 2.93 per case
Adversarial Failures:   0 / 100 unsafe automated actions
Unit & Integration Test Coverage: 22 passed, 0 failed, 0 xfailed
========================================================================================
```

### Analysis of Benchmark Metrics
1. **Unconstrained ML vs. Safe Policy**: Unconstrained ML achieves higher gross recovery by aggressively executing manual recovery actions on every failure. REVIVE intentionally trades ~INR 102,000 in gross recovery to respect merchant safety constraints, avoid duplicate charges, and protect customer relationships.
2. **Safe Policy Capture (93.67%)**: Evaluated strictly against the Constrained Oracle (the theoretical optimum under identical policy boundaries). The differential between the zero-fatigue baseline (97.45%) and the production policy (93.67%) is attributable to the active INR 50.00 customer fatigue penalty, which correctly suppresses aggressive outreach on over-contacted users.

---

## Known System Limitations & Boundary Constraints

To maintain complete architectural integrity, the current implementation acknowledges the following boundaries:

1. **Synthetic Counterfactual Calibration vs. Production Customer Elasticity**:
   - The causal model is trained against a calibrated synthetic simulator modeling subscription transition dynamics. Real-world consumer elasticity to nudges and manual recovery links will exhibit distribution variance that requires ongoing production recalibration.
2. **Razorpay Test Mode Execution Scope**:
   - Live execution in Test Mode creates authentic hosted Payment Links (`POST /v1/payment_links`) and validates invoice/subscription statuses via live REST endpoints. Automated recurring card re-authorization without customer 3DS intervention is not supported in Razorpay Test Mode sandbox environments.
3. **Single-Node Embedded Storage**:
   - The persistence layer utilizes embedded SQLite (`revive.db`) with Write-Ahead Logging (WAL). While suitable for single-node deployments and low-to-medium volume processing (< 500 events/sec), enterprise multi-region scale requires migration to distributed transactional datastores (e.g., PostgreSQL with distributed Redis/Kafka locks).
4. **Communication Channel Mocking**:
   - The `MANUAL_RECOVERY` path generates verified Razorpay Payment Links. The `NUDGE` path is currently isolated to a simulated communication dispatcher rather than an integrated SMS/WhatsApp carrier gateway (e.g., Twilio, Gupshup, Meta Cloud API).
5. **Offline Batch Retraining Boundary**:
   - Model parameters are fit via offline batch retraining (`scripts/train_model.py`). Online real-time policy updates via contextual bandits or continuous reinforcement learning are not currently active in the core execution path.

---

## Future Architectural Roadmap

- [ ] **Distributed Event Pipeline**: Transition the SQLite inbox/outbox worker to a distributed event broker (Kafka / Amazon SQS) with distributed lock leasing.
- [ ] **Multi-Gateway Abstraction Layer**: Generalize the execution adapter to unify Razorpay, Stripe Billing, Adyen, and Chargebee under a vendor-agnostic recovery protocol.
- [ ] **Multi-Touch Customer Fatigue Kernels**: Implement exponential decay kernels tracking customer interaction frequency across omnichannel touchpoints (Email, SMS, WhatsApp, In-App).
- [ ] **Safe Off-Policy Contextual Bandits**: Deploy continuous contextual bandits with safe Thompson Sampling operating strictly within deterministic policy guardrails.
- [ ] **Automated Human Approval Workflows**: Implement webhooks dispatching pending high-value approval requests directly to merchant Slack/Teams channels with interactive signing tokens.

---

## Quickstart & Cold-Start Reproducibility

### 1. Environment Setup

```bash
# Initialize virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (Command Prompt):
.venv\Scripts\activate.bat
# Linux / macOS:
source .venv/bin/activate

# Install runtime dependencies
pip install -r requirements.txt

# Configure environment variables (defaults work out-of-the-box with zero paid dependencies)
# Linux / macOS:
cp .env.example .env
# Windows (CMD):
copy .env.example .env
# Windows (PowerShell):
Copy-Item .env.example .env
```

### 2. Cold-Start Pipeline Execution (REQUIRED Before API Boot)

When cloning fresh or running after `make clean`, the following three steps are strictly required to generate datasets, fit models, and populate benchmark figures before launching the API:

```bash
# [REQUIRED] Step 1: Generate development and held-out evaluation datasets (creates data/generated/eval_cases.csv)
python scripts/generate_data.py

# [REQUIRED] Step 2: Fit bootstrap ensemble and calibrate isotonic regressors (creates models/calibrated_tlearner.joblib)
python scripts/train_model.py

# [REQUIRED] Step 3: Compute expected net recovery benchmark (creates data/evaluation/final_results.json)
python scripts/evaluate_final.py
```

### 3. Launch the API & Control Room Terminal (REQUIRED)

```bash
uvicorn app.main:app --reload --port 8000
```
Access the financial operations terminal at `http://localhost:8000`.

---

## Verification & Audit Test Suites (OPTIONAL / AUDIT)

These suites validate safety bounds, reliability mechanics, and gateway integrations:

```bash
# 1. Execute full unit and reliability test suite (22 tests)
pytest -v

# 2. Run reliability circuit breaker and authorization TTL drills
pytest tests/test_reliability_drills.py -v

# 3. Execute 100 adversarial stress cases (verifies 0 unsafe actions)
python scripts/run_adversarial.py

# 4. Verify deterministic policy boundary invariants
python scripts/run_property_tests.py

# 5. Rehearse live webhook failure ingestion & idempotency lock
python scripts/rehearse_failure_injection.py

# 6. Run Doubly Robust Off-Policy Evaluation (OPE)
python scripts/evaluate_ope.py

# 7. Execute live Razorpay Test Mode lifecycle smoke test (requires test keys in .env)
python scripts/test_razorpay_lifecycle.py
```

---

## Makefile Automation Reference

| Target | Command | Description |
|---|---|---|
| `make setup` | `python -m pip install -r requirements.txt` | Install runtime dependencies |
| `make data` | `python scripts/generate_data.py` | Generate synthetic data splits |
| `make train` | `python scripts/train_model.py` | Fit calibrated T-Learner ensemble |
| `make evaluate` | `python scripts/evaluate_final.py` | Run ground-truth policy benchmark |
| `make safety` | `python scripts/run_adversarial.py && python scripts/run_property_tests.py` | Run adversarial and property test suites |
| `make test` | `pytest -q` | Run full test suite |
| `make api` | `uvicorn app.main:app --reload --port 8000` | Launch FastAPI server and dashboard |
| `make clean` | `rm -rf data/generated data/evaluation models/*.joblib revive.db .pytest_cache` | Purge generated artifacts |

---

## Documentation Index

- [Architectural Decision Log (`docs/DECISIONS.md`)](docs/DECISIONS.md) — Comprehensive technical decision history across engine versions.
- [Deterministic Policy Specification (`docs/POLICY_SPEC.md`)](docs/POLICY_SPEC.md) — Formal specification of hard governance rules and feasibility masks.
- [Model Card (`docs/MODEL_CARD.md`)](docs/MODEL_CARD.md) — Calibrated T-Learner architecture, feature schemas, and calibration metrics.
- [Evaluation Integrity (`docs/EVALUATION_INTEGRITY.md`)](docs/EVALUATION_INTEGRITY.md) — Evaluation methodology, oracle formulations, and fatigue trade-off analysis.
- [Razorpay Domain Mapping (`docs/RAZORPAY_MAPPING.md`)](docs/RAZORPAY_MAPPING.md) — Webhook schema translation, event lifecycles, and claim boundaries.
- [Failure Postmortem & State Machine (`docs/FAILURE_POSTMORTEM.md`)](docs/FAILURE_POSTMORTEM.md) — Failure taxonomy, circuit breaker specifications, and retry semantics.
- [Control Room Specification (`docs/DASHBOARD.md`)](docs/DASHBOARD.md) — UI architecture, state streaming, and human-in-the-loop review operations.
- [Technical Defense & QA Preparation (`docs/QA_PREP.md`)](docs/QA_PREP.md) — Detailed technical justification for architectural and causal trade-offs.
