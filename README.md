# REVIVE 6.0 — Risk-Aware Incremental Revenue Recovery

REVIVE is a decision engine for failed Razorpay subscription payments. It compares intervention value against the platform's native recovery path, models uncertainty, applies hard safety constraints, and selects the best safe action.

## Decision loop

```text
Razorpay event
  → verified + idempotent
  → subscription state
  → action-specific recovery estimates
  → uncertainty + risk adjustment
  → hard policy filter
  → incremental economics
  → WAIT / NUDGE / MANUAL_RECOVERY / ESCALATE
  → audit
```

## Quickstart

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python scripts/generate_data.py
python scripts/train_model.py
python scripts/evaluate_final.py
python scripts/run_adversarial.py
python scripts/run_property_tests.py
pytest -q

uvicorn app.main:app --reload
```

## What the benchmark means

- `WAIT` represents the platform-native retry/control path.
- Synthetic outcomes are an evaluation environment, not Razorpay production statistics.
- Safe Policy Capture compares REVIVE against a constrained oracle under the same hard constraints.
- The optional OPE module is experimental and is not used to manufacture the primary benchmark result.

## Architecture docs

- `docs/POLICY_SPEC.md`
- `docs/MODEL_CARD.md`
- `docs/EVALUATION_INTEGRITY.md`
- `docs/RAZORPAY_MAPPING.md`
- `docs/FAILURE_POSTMORTEM.md`

## Verified benchmark

The evaluation is run from a clean generated dataset with five evaluation worlds and 200 held-out cases.

```text
                    Expected Net Value       Realized Net
Native              ₹124,795.48              ₹114,758.00
Rule-based           ₹200,355.55              ₹185,983.60
ML-only              ₹243,564.93              ₹253,416.60
REVIVE              ₹141,418.54              ₹128,646.20
Constrained Oracle  ₹142,541.45              ₹130,840.60
Oracle              ₹248,235.15              ₹264,436.60

Safe Policy Capture: 93.67%
Mean decision regret: reported in final_results.json
Adversarial unsafe automated actions: 0 / 100
```

The primary policy metric uses **true expected simulator value**, not one sampled outcome. Realized recovery is shown separately because stochastic outcomes can make a weaker policy look better on a single draw.

## Advanced Evidence Suite

```bash
python scripts/evaluate_ci.py
python scripts/evaluate_calibration.py
python scripts/evaluate_risk_sensitivity.py
python scripts/evaluate_scenarios.py
python scripts/statistical_tests.py
python scripts/evaluate_ope.py
python scripts/reliability_drills.py
python scripts/generate_report.py
python scripts/evaluate_causal.py
python scripts/evaluate_utility_profiles.py
```

## Optional Explainability

Install `shap` separately to enable local SHAP explanations; the core installation does not require it.

## Documentation

- `docs/DECISIONS.md`
- `docs/OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/EVALUATION_INTEGRITY.md`
- `docs/RELIABILITY.md`
- `docs/DASHBOARD.md`
- `docs/FAILURE_POSTMORTEM.md`
- `docs/RAZORPAY_MAPPING.md`
- `docs/QA_PREP.md`

## Peak additions

- `/api/explain/{case_id}`: optional SHAP local explanation when `shap` is installed.
- Human approval queue: `/api/approvals` and `/api/approvals/{id}/resolve`.
- `scripts/test_razorpay_lifecycle.py`: signed webhook + inbox + worker lifecycle smoke test; optional real Test Mode subscription creation.
- `scripts/reliability_drills.py`: reliability safety properties.
- `scripts/statistical_tests.py`: paired expected-value comparisons across seeds.
- `scripts/evaluate_ci.py`: bootstrap confidence interval.
- `scripts/evaluate_calibration.py`: calibration/Brier report.
- `scripts/evaluate_risk_sensitivity.py`: risk-mode sensitivity.
- `scripts/evaluate_scenarios.py`: failure-scenario breakdown.
- `scripts/evaluate_ope.py`: experimental doubly robust OPE on synthetic historical logs.
- `app/models/uplift.py`: action-vs-WAIT uplift estimator; causal claims require appropriate treatment-assignment assumptions.
- `scripts/generate_report.py`: one-command evaluation report.
- `scripts/evaluate_causal.py`: causal evaluation suite.
- `scripts/evaluate_utility_profiles.py`: merchant utility profile evaluations.

Causal claims are bounded by explicit identification assumptions.
