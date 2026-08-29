# REVIVE

REVIVE is a risk-aware recovery decision engine for failed Razorpay subscription payments. It detects a failed-payment event, estimates the incremental value of possible recovery actions, applies deterministic safety rules, and either creates a bounded recovery workflow or escalates the case for review.

The system is deliberately designed so that an AI recommendation is never permission to move money. Models estimate outcomes; economics ranks alternatives; policy authorizes; the execution layer is the only component allowed to create an external recovery action.

## What it does today

For a failed subscription payment, REVIVE evaluates four actions:

| Action | Meaning |
| --- | --- |
| `WAIT` | Preserve the gateway's native retry path. |
| `NUDGE` | Generate a recovery message; live delivery integration is not yet enabled. |
| `MANUAL_RECOVERY` | For an eligible live case, create a Razorpay Test Mode Payment Link. |
| `ESCALATE` | Stop automation and create a human-review request. |

The decision flow is:

```text
Razorpay webhook
  -> HMAC verification + idempotent inbox
  -> worker transforms the event into a recovery case
  -> decline diagnosis + live drift screening
  -> calibrated action estimates + uncertainty
  -> incremental-value ranking against WAIT
  -> deterministic policy gate
  -> authorization + durable execution intent
  -> Test Mode Payment Link, wait, or human escalation
  -> provider reconciliation + append-only audit record
```

## Design principles

- **Incremental economics:** interventions are valued against `WAIT`, not against doing nothing in the abstract.
- **Deterministic safety boundary:** hard policy constraints supersede model and LLM recommendations.
- **Fail closed:** invalid authorization, missing Test Mode credentials, provider errors, and detected distribution shift route the case to a safe outcome rather than a simulator fallback.
- **Idempotent side effects:** repeated webhook delivery is accepted without creating a duplicate downstream action.
- **Explicit uncertainty:** the model produces per-action probability and bootstrap uncertainty; risk mode affects ranking, not policy bypass.
- **Auditable outcomes:** decisions retain feature snapshots, model/policy versions, evidence, authorization state, and execution context.

## Safety controls

The policy gate evaluates action feasibility using case facts, not generated text. Current controls include:

- customer opt-out protection;
- recoverable subscription-state checks;
- native-retry collision prevention;
- automatic-action amount ceilings and configurable human-review threshold;
- recovery-attempt budget;
- issued-invoice and payment-method eligibility checks;
- minimum recovery-probability threshold;
- contact-fatigue penalty;
- authorization TTL and model/policy version validation;
- circuit-breaker protection for manual recovery; and
- live-case drift detection, which routes out-of-distribution cases to `ESCALATE`.

See [Policy Specification](docs/POLICY_SPEC.md) for the policy rules and identifiers.

## Evaluation: what the numbers mean

REVIVE's batch benchmark uses a **synthetic simulator with counterfactual ground truth**. It is intended to compare recovery policies reproducibly; it is not evidence of production revenue recovered from Razorpay merchants.

The checked-in evaluation snapshot (`data/evaluation/final_results.json`) uses 200 held-out synthetic cases and five simulator seeds:

| Strategy | Mean expected net value | Mean realized net value |
| --- | ---: | ---: |
| Native / `WAIT` | INR 112,305.16 | INR 107,865.80 |
| Rule-based baseline | INR 178,299.12 | INR 175,999.40 |
| ML-only, unconstrained | INR 228,005.53 | INR 248,109.20 |
| **REVIVE** | **INR 122,409.35** | **INR 116,737.00** |
| Constrained oracle | INR 124,321.78 | INR 115,766.00 |
| Absolute oracle | INR 233,707.97 | INR 255,644.00 |

- **Safe Policy Capture:** 84.09% — incremental value captured by REVIVE relative to the constrained oracle above the native `WAIT` baseline.
- **Mean decision regret:** INR 6.01 per synthetic case.
- **Adversarial safety:** 0 unsafe automated actions in the 100-case adversarial suite.

ML-only is intentionally shown as an unconstrained reference, not as the desired operating policy: it may maximize raw simulated value by selecting actions that violate merchant safety constraints.

For methodology and limitations, read [Evaluation Integrity](docs/EVALUATION_INTEGRITY.md), [Model Card](docs/MODEL_CARD.md), and [Causal Evaluation](docs/CAUSAL_EVALUATION.md).

## Local quick start

### Prerequisites

- Python 3.11+ (the project is currently exercised with Python 3.12)
- `pip`
- Optional: Docker and Docker Compose for the development PostgreSQL service

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

For the local synthetic workflow, Razorpay and Groq credentials are not required.

Generate data, train the model, and calculate the dashboard benchmark:

```powershell
python scripts/generate_data.py
python scripts/train_model.py
python scripts/evaluate_final.py
```

Start the Control Room:

```powershell
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000). Useful local endpoints include:

- `GET /api/health` — process health.
- `GET /api/evaluation` — checked-in/current benchmark results.
- `POST /api/run-case` — evaluate an event ID from `data/generated/eval_cases.csv`.
- `GET /api/replay/{case_id}` — synthetic counterfactual action values.
- `GET /api/audit` — recent non-preview decision records.
- `GET /api/approvals/pending` — unresolved escalation requests.
- `GET` / `PUT /api/merchant-config` — persisted merchant risk and intervention controls.

Example case evaluation:

```powershell
Invoke-RestMethod http://localhost:8000/api/run-case `
  -Method Post `
  -ContentType 'application/json' `
  -Body '{"event_id":"EVT-00557","risk_mode":"BALANCED"}'
```

`risk_mode` is a request-scoped preview. It does not change the persisted merchant configuration or transform the preview into a live payment action.

## Razorpay Test Mode workflow

REVIVE supports a bounded live path for webhook-derived cases. Set credentials only in `.env` or deployment secrets:

```dotenv
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
ENABLE_TESTMODE_EXECUTION=true
```

The expected live sequence is:

1. Razorpay delivers a signed webhook to `POST /api/webhook/razorpay`.
2. REVIVE verifies the raw-body HMAC and stores the event once in its durable inbox.
3. The worker processes the unique event as `is_live=true`.
4. Only a policy-approved `MANUAL_RECOVERY` case may create a Test Mode Payment Link.
5. Link creation means **payment pending**, not recovered revenue.
6. A later Razorpay event or provider query must reconcile the outcome as confirmed, failed, or unknown.

Never commit these credentials. A public deployment should keep the webhook endpoint signature-protected, rate-limited, and separate from the judge-facing demo surface.

## Verification

Run the core quality gates after behavioral changes:

```powershell
pytest -q
python scripts/run_adversarial.py
python scripts/run_property_tests.py
python scripts/reliability_drills.py
python scripts/evaluate_ope.py
python scripts/evaluate_calibration.py
python scripts/evaluate_ci.py
python scripts/evaluate_risk_sensitivity.py
python scripts/evaluate_scenarios.py
python scripts/evaluate_causal.py
python scripts/evaluate_utility_profiles.py
```

Latest verification performed on 2026-08-29:

- `pytest -q`: **62 passed**.
- Adversarial, property, reliability, OPE, calibration, confidence-interval, risk-sensitivity, scenario, causal, and merchant-utility scripts were run as part of the verification pass.
- The local signed-webhook lifecycle smoke test currently requires follow-up: it accepted the initial event and suppressed its duplicate, but failed its final assertion because the target inbox event remained `PENDING` after the worker pass. Do not claim end-to-end Test Mode payment-link proof until this script and an actual Test Mode run both pass.

Run the live smoke test only when you intentionally want to exercise Test Mode and have reviewed the configured credentials:

```powershell
python scripts/test_razorpay_lifecycle.py
```

## Repository map

| Area | Location |
| --- | --- |
| HTTP API and Control Room | `app/api/`, `frontend/index.html` |
| Recovery orchestration | `app/pipeline.py`, `app/agents/` |
| Economics, policy, and diagnosis | `app/economics.py`, `app/policy/`, `app/diagnosis.py` |
| Webhooks, execution, and reconciliation | `app/events/`, `app/execution/`, `scripts/worker.py` |
| Audit, approvals, receipts, and configuration | `app/audit/`, `app/approval.py`, `app/receipt.py`, `app/db.py` |
| Training and evaluation | `app/models/`, `app/evaluation/`, `scripts/` |
| Tests | `tests/` |

## Operational boundaries

- The primary benchmark is synthetic; it must not be presented as measured production revenue.
- Live execution creates a customer-facing Test Mode Payment Link; it does not directly charge a customer or claim recovery before reconciliation.
- `NUDGE` message generation exists, but no production email/SMS delivery provider is wired.
- SQLite is the default local persistence implementation. The repository includes Docker Compose/PostgreSQL development scaffolding, but production scaling and multi-node locking require an explicit deployment hardening pass.
- The optional LLM is used for diagnosis/recommendation fallback. Deterministic policy and execution controls remain authoritative when it is unavailable.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Policy Specification](docs/POLICY_SPEC.md)
- [Model Card](docs/MODEL_CARD.md)
- [Evaluation Integrity](docs/EVALUATION_INTEGRITY.md)
- [Razorpay Mapping and Claim Boundaries](docs/RAZORPAY_MAPPING.md)
- [Reliability Model](docs/RELIABILITY.md)
- [Failure Postmortem](docs/FAILURE_POSTMORTEM.md)
- [Live Failure Injection Guide](docs/LIVE_FAILURE_INJECTION.md)
- [Demo Script](docs/DEMO_SCRIPT.md)
- [QA Preparation](docs/QA_PREP.md)
