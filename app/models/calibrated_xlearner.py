from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from joblib import dump, load
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, Ridge

ACTIONS = ["WAIT", "NUDGE", "MANUAL_RECOVERY"]
ID_COLUMNS = {"event_id", "subscription_id", "customer_id", "subscription_status", "world_seed", "action", "outcome"}


class CalibratedXLearner:
    """Action-specific bootstrap X-learner with OOB isotonic calibration.

    Implements Künzel et al. (2019) X-learner for multi-treatment causal uplift:
    Stage 1: Response functions mu_0 (WAIT) and mu_a (NUDGE, MANUAL_RECOVERY)
    Stage 2: Imputed counterfactual treatment effects (D_1 = Y_1 - mu_0(X_1), D_0 = mu_a(X_0) - Y_0)
    Stage 3: CATE regression estimators tau_1(X) and tau_0(X)
    Stage 4: Propensity-weighted CATE combination tau_a(X) = e_a * tau_0 + (1 - e_a) * tau_1
    Stage 5: Reconstruction of P(a|X) = clip(mu_0(X) + tau_a(X), 0, 1) with bootstrap variance & OOB calibration.
    """

    def __init__(self, model_dir: Optional[Path] = None, n_bootstrap: int = 8, random_seed: int = 20260820):
        self.model_dir = model_dir
        self.n_bootstrap = n_bootstrap
        self.random_seed = random_seed
        self.base_models: Dict[str, List[LogisticRegression]] = {}
        self.effect_models: Dict[str, List[Dict[str, Any]]] = {}  # action -> list of {tau0, tau1, propensity}
        self.calibrators: Dict[str, IsotonicRegression] = {}
        self.columns: List[str] = []

    def _feature_frame(self, df: pd.DataFrame, fit: bool = False) -> pd.DataFrame:
        feature_cols = [c for c in df.columns if c not in ID_COLUMNS]
        x = df[feature_cols].copy()
        cat_cols = [c for c in x.columns if x[c].dtype == object]
        x = pd.get_dummies(x, columns=cat_cols, drop_first=True)
        if fit:
            self.columns = x.columns.tolist()
        else:
            x = x.reindex(columns=self.columns, fill_value=0)
        return x.astype(float)

    def train(self, training_df: pd.DataFrame, action_col: str = "action", outcome_col: str = "outcome") -> None:
        self.base_models.clear()
        self.effect_models.clear()
        self.calibrators.clear()
        rng = np.random.default_rng(self.random_seed)
        base = training_df.copy()
        feature_source = base.drop(columns=[c for c in [action_col, outcome_col] if c in base.columns])
        self._feature_frame(feature_source, fit=True)

        # Stage 1: Fit base models per action
        for action in ACTIONS:
            frame = base[base[action_col] == action].reset_index(drop=True).copy()
            if len(frame) < 40:
                raise ValueError(f"Insufficient training rows for {action}: {len(frame)}")
            y = frame[outcome_col].map({"SUCCESS": 1, "FAILURE": 0}).astype(int).to_numpy()
            x = self._feature_frame(frame, fit=False)
            ensemble = []
            for _ in range(self.n_bootstrap):
                indices = rng.integers(0, len(frame), size=len(frame))
                xb = x.iloc[indices]
                yb = y[indices]
                if len(np.unique(yb)) < 2:
                    continue
                model = LogisticRegression(max_iter=500, class_weight="balanced", solver="liblinear")
                model.fit(xb, yb)
                ensemble.append(model)
            if not ensemble:
                raise RuntimeError(f"No valid bootstrap models trained for {action}")
            self.base_models[action] = ensemble

        # Stage 2-4: Fit X-learner second stage for treatments (NUDGE, MANUAL_RECOVERY) against control (WAIT)
        control_frame = base[base[action_col] == "WAIT"].reset_index(drop=True).copy()
        x_0 = self._feature_frame(control_frame, fit=False)
        y_0 = control_frame[outcome_col].map({"SUCCESS": 1, "FAILURE": 0}).astype(int).to_numpy()

        for action in ["NUDGE", "MANUAL_RECOVERY"]:
            treat_frame = base[base[action_col] == action].reset_index(drop=True).copy()
            x_1 = self._feature_frame(treat_frame, fit=False)
            y_1 = treat_frame[outcome_col].map({"SUCCESS": 1, "FAILURE": 0}).astype(int).to_numpy()

            effects = []
            for b_idx in range(self.n_bootstrap):
                m0 = self.base_models["WAIT"][min(b_idx, len(self.base_models["WAIT"]) - 1)]
                m1 = self.base_models[action][min(b_idx, len(self.base_models[action]) - 1)]

                # Counterfactual imputation
                mu0_on_1 = m0.predict_proba(x_1)[:, 1]
                mu1_on_0 = m1.predict_proba(x_0)[:, 1]

                d_1 = y_1 - mu0_on_1
                d_0 = mu1_on_0 - y_0

                # Bootstrap resampling
                idx_1 = rng.integers(0, len(x_1), size=len(x_1))
                idx_0 = rng.integers(0, len(x_0), size=len(x_0))

                tau1 = Ridge(alpha=1.0)
                tau1.fit(x_1.iloc[idx_1], d_1[idx_1])

                tau0 = Ridge(alpha=1.0)
                tau0.fit(x_0.iloc[idx_0], d_0[idx_0])

                # Propensity score model e_a(X) = P(A=a | A in {WAIT, a})
                x_prop = pd.concat([x_0, x_1], ignore_index=True)
                y_prop = np.concatenate([np.zeros(len(x_0)), np.ones(len(x_1))])
                prop_model = LogisticRegression(max_iter=300, solver="liblinear")
                prop_model.fit(x_prop, y_prop)

                effects.append({"tau0": tau0, "tau1": tau1, "propensity": prop_model})

            self.effect_models[action] = effects

        # Stage 5: Out-of-Bag Isotonic Calibration
        for action in ACTIONS:
            frame = base[base[action_col] == action].reset_index(drop=True).copy()
            x_all = self._feature_frame(frame, fit=False)
            y_all = frame[outcome_col].map({"SUCCESS": 1, "FAILURE": 0}).astype(int).to_numpy()

            if action == "WAIT":
                matrix_wait = np.vstack([m.predict_proba(x_all)[:, 1] for m in self.base_models["WAIT"]])
                raw_preds = matrix_wait.mean(axis=0)
            else:
                matrix_wait = np.vstack([m.predict_proba(x_all)[:, 1] for m in self.base_models["WAIT"]])
                wait_raw_means = matrix_wait.mean(axis=0)
                treat_preds = []
                for ef in self.effect_models[action]:
                    e = ef["propensity"].predict_proba(x_all)[:, 1]
                    t0 = ef["tau0"].predict(x_all)
                    t1 = ef["tau1"].predict(x_all)
                    cate = e * t0 + (1.0 - e) * t1
                    treat_preds.append(np.clip(wait_raw_means + cate, 0.0, 1.0))
                raw_preds = np.vstack(treat_preds).mean(axis=0)

            if len(raw_preds) >= 20 and len(set(y_all)) == 2:
                calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
                calibrator.fit(raw_preds, y_all)
                self.calibrators[action] = calibrator

        if self.model_dir:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            dump(
                {
                    "base_models": self.base_models,
                    "effect_models": self.effect_models,
                    "calibrators": self.calibrators,
                    "columns": self.columns,
                    "n_bootstrap": self.n_bootstrap,
                    "random_seed": self.random_seed,
                },
                self.model_dir / "calibrated_xlearner.joblib",
            )

    def load(self, model_dir: Optional[Path] = None) -> None:
        path = (model_dir or self.model_dir) / "calibrated_xlearner.joblib"
        data = load(path)
        self.base_models = data["base_models"]
        self.effect_models = data["effect_models"]
        self.calibrators = data.get("calibrators", {})
        self.columns = data["columns"]
        self.n_bootstrap = data.get("n_bootstrap", 8)
        self.random_seed = data.get("random_seed", 20260820)

    def _raw_predict(self, case: Dict[str, Any], action: str) -> float:
        x = self._feature_frame(pd.DataFrame([case]), fit=False)
        if action == "WAIT":
            return float(np.mean([m.predict_proba(x)[0, 1] for m in self.base_models["WAIT"]]))
        if action not in self.effect_models:
            return 0.0

        p_wait = float(np.mean([m.predict_proba(x)[0, 1] for m in self.base_models["WAIT"]]))
        cates = []
        for ef in self.effect_models[action]:
            e = ef["propensity"].predict_proba(x)[0, 1]
            t0 = ef["tau0"].predict(x)[0]
            t1 = ef["tau1"].predict(x)[0]
            cate = e * t0 + (1.0 - e) * t1
            cates.append(cate)
        cate_mean = float(np.mean(cates))
        return float(np.clip(p_wait + cate_mean, 0.0, 1.0))

    def _calibrate(self, action: str, raw_mean: float) -> float:
        c = self.calibrators.get(action)
        return float(c.predict([raw_mean])[0]) if c is not None else float(raw_mean)

    def predict_proba(self, case: Dict[str, Any], action: str) -> Dict[str, Any]:
        if action == "ESCALATE" or (action != "WAIT" and action not in self.effect_models):
            return {"mean": 0.0, "std": 0.0, "lower": 0.0, "upper": 0.0, "n_models": 0, "calibrated": False}

        x = self._feature_frame(pd.DataFrame([case]), fit=False)
        if action == "WAIT":
            raw = np.array([m.predict_proba(x)[0, 1] for m in self.base_models["WAIT"]], dtype=float)
            raw_mean = float(raw.mean())
            std = float(raw.std(ddof=1)) if len(raw) > 1 else 0.0
        else:
            raw_wait = np.array([m.predict_proba(x)[0, 1] for m in self.base_models["WAIT"]], dtype=float)
            raw_preds = []
            for ef in self.effect_models[action]:
                e = ef["propensity"].predict_proba(x)[0, 1]
                t0 = ef["tau0"].predict(x)[0]
                t1 = ef["tau1"].predict(x)[0]
                cate = e * t0 + (1.0 - e) * t1
                raw_preds.append(float(np.clip(raw_wait.mean() + cate, 0.0, 1.0)))
            raw = np.array(raw_preds, dtype=float)
            raw_mean = float(raw.mean())
            std = float(raw.std(ddof=1)) if len(raw) > 1 else 0.0

        mean = self._calibrate(action, raw_mean)
        lower = max(0.0, mean - 1.96 * std)
        upper = min(1.0, mean + 1.96 * std)
        return {
            "mean": mean,
            "std": std,
            "lower": lower,
            "upper": upper,
            "n_models": len(raw),
            "calibrated": action in self.calibrators,
        }

    def predict_all_actions(self, case: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {a: self.predict_proba(case, a) for a in ACTIONS + ["ESCALATE"]}

    def predict_dataset(self, cases: List[Dict[str, Any]]) -> List[Dict[str, Dict[str, Any]]]:
        if not cases:
            return []
        frame = pd.DataFrame(cases)
        x = self._feature_frame(frame, fit=False)

        # Predict WAIT
        matrix_wait = np.vstack([m.predict_proba(x)[:, 1] for m in self.base_models["WAIT"]])
        wait_raw_means = matrix_wait.mean(axis=0)
        wait_stds = matrix_wait.std(axis=0, ddof=1) if matrix_wait.shape[0] > 1 else np.zeros(matrix_wait.shape[1])
        cal_wait = self.calibrators.get("WAIT")
        wait_means = cal_wait.predict(wait_raw_means) if cal_wait is not None else wait_raw_means

        out_per = {
            "WAIT": [
                {
                    "mean": float(mu),
                    "std": float(sd),
                    "lower": float(max(0.0, mu - 1.96 * sd)),
                    "upper": float(min(1.0, mu + 1.96 * sd)),
                    "n_models": int(matrix_wait.shape[0]),
                    "calibrated": cal_wait is not None,
                }
                for mu, sd in zip(wait_means, wait_stds)
            ]
        }

        # Predict Treatments
        for action in ["NUDGE", "MANUAL_RECOVERY"]:
            treat_preds = []
            for ef in self.effect_models[action]:
                e = ef["propensity"].predict_proba(x)[:, 1]
                t0 = ef["tau0"].predict(x)
                t1 = ef["tau1"].predict(x)
                cate = e * t0 + (1.0 - e) * t1
                treat_preds.append(np.clip(wait_raw_means + cate, 0.0, 1.0))
            matrix_treat = np.vstack(treat_preds)
            treat_raw_means = matrix_treat.mean(axis=0)
            treat_stds = (
                matrix_treat.std(axis=0, ddof=1) if matrix_treat.shape[0] > 1 else np.zeros(matrix_treat.shape[1])
            )
            cal_treat = self.calibrators.get(action)
            treat_means = cal_treat.predict(treat_raw_means) if cal_treat is not None else treat_raw_means

            out_per[action] = [
                {
                    "mean": float(mu),
                    "std": float(sd),
                    "lower": float(max(0.0, mu - 1.96 * sd)),
                    "upper": float(min(1.0, mu + 1.96 * sd)),
                    "n_models": int(matrix_treat.shape[0]),
                    "calibrated": cal_treat is not None,
                }
                for mu, sd in zip(treat_means, treat_stds)
            ]

        result = []
        for i in range(len(cases)):
            row = {a: out_per[a][i] for a in ACTIONS}
            row["ESCALATE"] = {
                "mean": 0.0,
                "std": 0.0,
                "lower": 0.0,
                "upper": 0.0,
                "n_models": 0,
                "calibrated": False,
            }
            result.append(row)
        return result
