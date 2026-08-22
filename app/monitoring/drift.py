from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "amount",
    "attempt_number",
    "days_since_last_success",
    "prior_recoveries_count",
    "payment_method_age_days",
    "customer_tenure_days",
    "previous_success_rate",
    "previous_recovery_rate",
    "contact_count_7d",
    "nudge_incentive_cost",
    "manual_recovery_ops_cost",
    "escalation_ops_cost",
    "wait_expected_days",
]


def calculate_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    expected = pd.Series(expected).dropna().astype(float)
    actual = pd.Series(actual).dropna().astype(float)
    if len(expected) == 0 or len(actual) == 0:
        return 0.0
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0] = -np.inf
    edges[-1] = np.inf
    e, _ = np.histogram(expected, bins=edges)
    a, _ = np.histogram(actual, bins=edges)
    if e.sum() == 0 or a.sum() == 0:
        return 0.0
    ep = np.clip(e / e.sum(), 1e-6, None)
    ap = np.clip(a / a.sum(), 1e-6, None)
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def detect_drift(training_df: pd.DataFrame, new_df: pd.DataFrame, feature_cols: List[str], threshold: float = 0.2) -> Dict[str, object]:
    scores = {}
    for col in feature_cols:
        if col not in training_df or col not in new_df:
            continue
        if pd.api.types.is_numeric_dtype(training_df[col]):
            scores[col] = calculate_psi(training_df[col], new_df[col])
    drifted = {k: v for k, v in scores.items() if v > threshold}
    return {"drift_scores": scores, "drifted_features": drifted, "drift_detected": bool(drifted)}


class DriftDetector:
    """Fast in-memory per-case drift detector using precomputed training reference statistics."""

    def __init__(self, training_path: Path | str | None = None, threshold: float = 0.2):
        self.threshold = threshold
        self.reference_stats: Dict[str, Dict[str, float]] = {}
        if training_path is not None:
            self.load_reference(training_path)

    def load_reference(self, training_path: Path | str) -> None:
        p = Path(training_path)
        if not p.exists():
            return
        df = pd.read_csv(p)
        self.reference_stats = {}
        for col in NUMERIC_FEATURES:
            if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                s = df[col].dropna().astype(float)
                if len(s) > 0:
                    std_val = float(s.std())
                    self.reference_stats[col] = {
                        "min": float(s.min()),
                        "max": float(s.max()),
                        "mean": float(s.mean()),
                        "std": std_val if std_val > 0 else 1.0,
                    }

    def detect_case_drift(self, case: dict) -> dict[str, Any]:
        """Check if an incoming live case deviates significantly from the training distribution.

        Flags drift if any feature exceeds extreme bounds (z-score > 3.0 or beyond observed training min/max).
        """
        if not self.reference_stats:
            return {"drift_detected": False, "drifted_features": {}, "drift_scores": {}}

        drifted = {}
        scores = {}
        for col, stats in self.reference_stats.items():
            if col not in case:
                continue
            try:
                val = float(case[col])
            except (ValueError, TypeError):
                continue

            z_score = abs(val - stats["mean"]) / stats["std"]
            scores[col] = float(z_score)

            # Flag if value is outside training range or has z-score > 3.0
            if val < stats["min"] or val > stats["max"] or z_score > 3.0:
                drifted[col] = {
                    "value": val,
                    "min": stats["min"],
                    "max": stats["max"],
                    "mean": stats["mean"],
                    "std": stats["std"],
                    "z_score": float(z_score),
                }

        return {
            "drift_detected": bool(drifted),
            "drifted_features": drifted,
            "drift_scores": scores,
        }
