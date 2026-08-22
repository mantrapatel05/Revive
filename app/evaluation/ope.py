from __future__ import annotations
import numpy as np
import pandas as pd

def _weights(policy_probs, behavior_probs, actions):
    return policy_probs[np.arange(len(actions)), actions] / np.maximum(behavior_probs[np.arange(len(actions)), actions], 1e-12)

def estimate_ips(historical_df, policy_probs, behavior_probs, actions, rewards):
    x = _weights(policy_probs, behavior_probs, actions) * rewards
    return {"ips": float(np.mean(x)), "ips_std": float(np.std(x, ddof=1) / np.sqrt(len(x)))}

def estimate_snips(historical_df, policy_probs, behavior_probs, actions, rewards):
    w = _weights(policy_probs, behavior_probs, actions)
    denom = max(float(w.sum()), 1e-12)
    return {"snips": float(np.sum(w * rewards) / denom), "weight_sum": denom}

def estimate_dr(historical_df, policy_probs, behavior_probs, actions, rewards, outcome_model_pred):
    w = _weights(policy_probs, behavior_probs, actions)
    mu = outcome_model_pred[np.arange(len(actions)), actions]
    dr = mu + w * (rewards - mu)
    return {"dr": float(np.mean(dr)), "dr_std": float(np.std(dr, ddof=1) / np.sqrt(len(dr)))}

def overlap_diagnostics(historical_df, behavior_probs, actions, action_names):
    out = {}
    for i, name in enumerate(action_names):
        mask = actions == i
        vals = behavior_probs[mask, i]
        if len(vals):
            out[name] = {
                "count": int(mask.sum()),
                "min_behavior_prob": float(vals.min()),
                "mean_behavior_prob": float(vals.mean()),
                "max_inverse_propensity": float(1.0 / max(vals.min(), 1e-12)),
            }
    taken = behavior_probs[np.arange(len(actions)), actions]
    inv = 1.0 / np.maximum(taken, 1e-12)
    ess = float(inv.sum() ** 2 / max((inv ** 2).sum(), 1e-12))
    out["overall"] = {"effective_sample_size": ess, "max_inverse_propensity": float(inv.max())}
    return out

def bootstrap_ci(values, estimator=np.mean, n_bootstrap=1000, alpha=0.95, seed=42):
    values = np.asarray(values)
    rng = np.random.default_rng(seed)
    estimates = [float(estimator(rng.choice(values, size=len(values), replace=True))) for _ in range(n_bootstrap)]
    return float(np.quantile(estimates, (1-alpha)/2)), float(np.quantile(estimates, 1-(1-alpha)/2))
