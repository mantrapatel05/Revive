# REVIVE 6.0 — Causal Policy Evaluation

REVIVE 6.0 moves from predictive recovery modeling toward incremental treatment-effect reasoning.

For action `a`:

`τ_a(x) = E[Y(a) - Y(WAIT) | X=x]`

The synthetic environment provides controlled counterfactual outcome probabilities. Real historical causal claims require consistency, positivity/overlap and a valid identification strategy such as no unmeasured confounding or randomized/ignorable treatment assignment.

## OPE

Implemented:
- IPS
- SNIPS
- Doubly Robust
- overlap diagnostics
- effective sample size
- bootstrap confidence-interval utility

## Decision Replay

Decision records persist a feature snapshot plus model/policy/scenario versions so historical decisions can be compared with the current policy.

## Merchant Utility

Risk appetite, customer fatigue, churn-risk penalty and support cost influence action ranking.

## Evidence Boundary

Synthetic counterfactuals validate implementation. OPE experiments demonstrate estimator behavior. Neither should be presented as production causal evidence.
