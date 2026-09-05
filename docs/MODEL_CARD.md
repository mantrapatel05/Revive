# Model Card — REVIVE Calibrated Causal Uplift Models

**Primary Architecture:** Action-specific bootstrap logistic-regression ensemble (Calibrated T-Learner) with Out-of-Bag (OOB) isotonic calibration.

**Alternative Architecture:** Implemented two-stage Calibrated X-Learner (`app/models/calibrated_xlearner.py`) with counterfactual residual imputation, Ridge CATE regressors, and propensity-weighted combination.

**Actions Modeled:** `WAIT`, `NUDGE`, `MANUAL_RECOVERY` (with safe deterministic fallback to `ESCALATE`).

**Outputs:** Calibrated recovery probability $P(\text{Success} \mid X, a)$, bootstrap dispersion $\sigma(a)$, conservative Lower Confidence Bound (LCB) with parameter $z$, and 95% uncertainty intervals.

**Training Regimen:** Synthetic subscription-failure events evaluated across 5 development worlds (12,000 total observations: 4,000 per action). Out-of-Bag predictions fit isotonic calibrators. Held-out evaluation datasets are strictly isolated from fitting.

## Empirical Meta-Learner Study (T-Learner vs. X-Learner)

In Phase 5.1, we evaluated whether replacing the Calibrated T-Learner with an X-Learner improved causal policy performance:

| Metric | Calibrated T-Learner (Baseline) | Calibrated X-Learner (Candidate) | Difference |
|---|---|---|---|
| **Safe Policy Capture** | **93.67%** | **90.22%** | -3.45% (T-Learner wins) |
| **Expected Net Recovery** | **INR 141,418.54 ± 1,229.23** | **INR 140,806.69 ± 1,250.06** | -INR 611.85 |
| **Realized Net Recovery** | **INR 128,646.20** | **INR 128,000.00** | -INR 646.20 |
| **Adversarial Safety Violations** | **0 / 100** | **0 / 100** | Parity (Passed) |

**Empirical Finding & Architectural Decision:**
The training dataset is perfectly balanced across actions ($1 : 1 : 1$, 4,000 rows each) because the development data generation simulates complete counterfactual worlds for every case. The X-Learner's theoretical advantage over the T-Learner occurs primarily in observational settings where the control group heavily dominates treatment groups (e.g. 99:1 imbalance ratio where the control outcome model $\mu_0$ has significantly lower estimation variance). Under balanced action distributions, the X-Learner's two-stage residual imputation and secondary Ridge CATE fitting introduces compound variance and shrinkage bias without providing sample-efficiency leverage.

Following the non-negotiable pass/fail gate (retain X-Learner only if Safe Policy Capture strictly improves without safety regression), **the Calibrated T-Learner is retained as the canonical production model**, while `CalibratedXLearner` remains fully supported in the codebase (`--model xlearner`) for observational replay and future imbalanced dataset regimes.

## Uncertainty & Governance Boundary

Bootstrap dispersion serves as a model-variance proxy rather than a full representation of aleatoric and epistemic uncertainty. All model predictions function solely as inputs to the deterministic policy gate; ML outputs cannot unilaterally authorize money movements or external gateway executions.
