# REVIVE 6.0 — Risk-Aware Incremental Revenue Recovery

REVIVE is a revenue-recovery decision engine for failed Razorpay subscription payments. It compares intervention value against the platform's native recovery path, models uncertainty, applies hard deterministic safety constraints, and selects the best safe action.

## Decision Loop

```text
Razorpay event
  → verified + idempotent
  → subscription state
  → action-specific recovery estimates
  → uncertainty + risk adjustment
  → hard policy filter
  → incremental economics
  → WAIT / NUDGE / MANUAL_RECOVERY / ESCALATE
  → durable execution / reconciliation
  → audit
```

## Quickstart (Cold-Start Reproducibility)

Follow these steps on a clean machine to install, train, evaluate, and run the Control Room dashboard.

### 1. Environment Setup

```bash
python -m venv .venv
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# Optional: copy environment template (no keys required for synthetic/local engine)
cp .env.example .env
```

### 2. Data & Model Pipeline (REQUIRED before launching API)

Running these three commands generates synthetic datasets, fits the calibrated T-learner models, and computes the ground-truth policy benchmark:

```bash
# 1. Generate dev and held-out evaluation cases
python scripts/generate_data.py

# 2. Train bootstrap logistic regression ensemble with OOB isotonic calibration
python scripts/train_model.py

# 3. Compute expected-value benchmark and Safe Policy Capture metrics
python scripts/evaluate_final.py
```

### 3. Launch Dashboard & API

```bash
uvicorn app.main:app --reload --port 8000
```
Open **`http://localhost:8000`** in your browser to access the REVIVE Control Room terminal.

---

### 4. Safety & Verification Test Suite (Optional)

```bash
# Run 100 adversarial edge cases (opted-out, exhausted retries, excessive amount)
python scripts/run_adversarial.py

# Verify hard policy boundaries
python scripts/run_property_tests.py

# Run full pytest test suite
pytest -q
```

---

## Makefile Shortcuts

If `make` is available on your system, you can use the corresponding shortcuts:

| Target | Command | Purpose |
|---|---|---|
| `make setup` | `pip install -r requirements.txt` | Install project dependencies |
| `make data` | `python scripts/generate_data.py` | **[Required]** Generate evaluation datasets |
| `make train` | `python scripts/train_model.py` | **[Required]** Train calibrated T-Learner |
| `make evaluate` | `python scripts/evaluate_final.py` | **[Required]** Run final benchmark |
| `make safety` | `run_adversarial.py && run_property_tests.py` | Run adversarial & property tests |
| `make test` | `pytest -q` | Run test suite |
| `make api` | `uvicorn app.main:app --reload` | Start FastAPI server & Dashboard |
| `make clean` | `rm -rf data/generated data/evaluation models/*.joblib revive.db` | Clean generated artifacts |

---

## What the Benchmark Means

- `WAIT` represents the platform-native retry / control path.
- Synthetic outcomes provide a controlled evaluation environment with counterfactual ground truth.
- **Safe Policy Capture** measures REVIVE's performance against a constrained oracle under identical hard constraints.
- Realized recovery is reported alongside expected value to isolate policy quality from stochastic sample variance.

## Verified Benchmark Results

```text
                    Expected Net Value       Realized Net
Native              ₹124,795.48              ₹114,758.00
Rule-based           ₹200,355.55              ₹185,983.60
ML-only              ₹243,564.93              ₹253,416.60
REVIVE              ₹141,418.54              ₹128,646.20
Constrained Oracle  ₹142,541.45              ₹130,840.60
Oracle              ₹248,235.15              ₹264,436.60

Safe Policy Capture: 93.67%
Mean decision regret: ₹2.93 / case
Adversarial unsafe automated actions: 0 / 100
```

## Advanced Evaluation & Analysis Suite

```bash
python scripts/evaluate_ci.py                 # Bootstrap confidence intervals
python scripts/evaluate_calibration.py        # Probability calibration & Brier score
python scripts/evaluate_risk_sensitivity.py   # Risk mode parameter sweep (z=0, 1, 2)
python scripts/evaluate_scenarios.py          # Scenario-level breakdown
python scripts/statistical_tests.py           # Statistical significance tests
python scripts/evaluate_ope.py                # Doubly Robust Off-Policy Evaluation
python scripts/reliability_drills.py          # Circuit breaker & outbox safety drills
python scripts/evaluate_causal.py             # Causal uplift evaluation
python scripts/evaluate_utility_profiles.py   # Merchant utility & fatigue analysis
python scripts/test_razorpay_lifecycle.py     # Live Test Mode lifecycle verification
```

## Documentation

- [`docs/DECISIONS.md`](docs/DECISIONS.md) — Architectural decision log
- [`docs/POLICY_SPEC.md`](docs/POLICY_SPEC.md) — Deterministic policy specification
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md) — Calibrated T-Learner model card
- [`docs/EVALUATION_INTEGRITY.md`](docs/EVALUATION_INTEGRITY.md) — Benchmark integrity & metrics
- [`docs/RAZORPAY_MAPPING.md`](docs/RAZORPAY_MAPPING.md) — Razorpay domain mapping & claim boundaries
- [`docs/FAILURE_POSTMORTEM.md`](docs/FAILURE_POSTMORTEM.md) — Failure modes & recovery state machine
- [`docs/DASHBOARD.md`](docs/DASHBOARD.md) — Control Room specifications
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — 5-minute walkthrough guide
- [`docs/QA_PREP.md`](docs/QA_PREP.md) — Technical defense & edge-case Q&A
