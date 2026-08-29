from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from joblib import dump, load
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

ACTIONS = ["WAIT", "NUDGE", "MANUAL_RECOVERY"]
ID_COLUMNS = {"event_id", "subscription_id", "customer_id", "subscription_status", "world_seed", "action", "outcome"}


class CalibratedTLearner:
    """Action-specific bootstrap T-learner with OOB isotonic calibration.

    - bootstrap ensemble mean/std -> predictive estimate + model-variance proxy
    - out-of-bag aggregated predictions -> per-action isotonic calibration map
    """

    def __init__(self, model_dir: Optional[Path] = None, n_bootstrap: int = 8, random_seed: int = 20260820):
        self.model_dir = model_dir
        self.n_bootstrap = n_bootstrap
        self.random_seed = random_seed
        self.models: Dict[str, List[LogisticRegression]] = {}
        self.calibrators: Dict[str, IsotonicRegression] = {}
        self.columns: List[str] = []

    def _feature_frame(self, df: pd.DataFrame, fit: bool = False) -> pd.DataFrame:
        feature_cols = [c for c in df.columns if c not in ID_COLUMNS]
        x = df[feature_cols].copy()
        # Drop non-scalar metadata objects (e.g. diagnosis, generated_message)
        x = x.drop(columns=[c for c in x.columns if x[c].apply(lambda v: isinstance(v, (dict, list))).any()])
        cat_cols = [c for c in x.columns if x[c].dtype == object]
        x = pd.get_dummies(x, columns=cat_cols, drop_first=True)
        if fit:
            self.columns = x.columns.tolist()
        else:
            x = x.reindex(columns=self.columns, fill_value=0)
        return x.astype(float)

    def train(self, training_df: pd.DataFrame, action_col: str = "action", outcome_col: str = "outcome") -> None:
        self.models.clear(); self.calibrators.clear()
        rng = np.random.default_rng(self.random_seed)
        base = training_df.copy()
        feature_source = base.drop(columns=[c for c in [action_col, outcome_col] if c in base.columns])
        self._feature_frame(feature_source, fit=True)

        for action in ACTIONS:
            frame = base[base[action_col] == action].reset_index(drop=True).copy()
            if len(frame) < 40:
                raise ValueError(f"Insufficient training rows for {action}: {len(frame)}")
            y = frame[outcome_col].map({"SUCCESS": 1, "FAILURE": 0}).astype(int).to_numpy()
            x = self._feature_frame(frame, fit=False)
            ensemble=[]
            oob_preds=[[] for _ in range(len(frame))]
            for _ in range(self.n_bootstrap):
                indices = rng.integers(0, len(frame), size=len(frame))
                in_bag=np.zeros(len(frame),dtype=bool); in_bag[indices]=True
                xb=x.iloc[indices]; yb=y[indices]
                if len(np.unique(yb))<2:
                    continue
                model=LogisticRegression(max_iter=500,class_weight="balanced",solver="liblinear")
                model.fit(xb,yb)
                ensemble.append(model)
                oob=np.where(~in_bag)[0]
                if len(oob):
                    probs=model.predict_proba(x.iloc[oob])[:,1]
                    for idx,p in zip(oob,probs): oob_preds[idx].append(float(p))
            if not ensemble:
                raise RuntimeError(f"No valid bootstrap models trained for {action}")
            self.models[action]=ensemble

            # OOB calibration: one prediction per row from only models that did not train on that row.
            x_cal=[]; y_cal=[]
            for i,preds in enumerate(oob_preds):
                if preds:
                    x_cal.append(float(np.mean(preds))); y_cal.append(int(y[i]))
            if len(x_cal)>=20 and len(set(y_cal))==2:
                calibrator=IsotonicRegression(y_min=0.0,y_max=1.0,out_of_bounds='clip')
                calibrator.fit(x_cal,y_cal)
                self.calibrators[action]=calibrator

        if self.model_dir:
            self.model_dir.mkdir(parents=True, exist_ok=True)
            dump({'models':self.models,'calibrators':self.calibrators,'columns':self.columns,'n_bootstrap':self.n_bootstrap,'random_seed':self.random_seed}, self.model_dir/'calibrated_tlearner.joblib')

    def load(self, model_dir: Optional[Path] = None) -> None:
        path=(model_dir or self.model_dir)/'calibrated_tlearner.joblib'
        data=load(path)
        self.models=data['models']; self.calibrators=data.get('calibrators',{}); self.columns=data['columns']; self.n_bootstrap=data.get('n_bootstrap',8); self.random_seed=data.get('random_seed',20260820)

    def _calibrate(self, action: str, raw_mean: float) -> float:
        c=self.calibrators.get(action)
        return float(c.predict([raw_mean])[0]) if c is not None else float(raw_mean)

    def predict_proba(self, case: Dict[str, Any], action: str) -> Dict[str, Any]:
        if action=='ESCALATE' or action not in self.models:
            return {'mean':0.0,'std':0.0,'lower':0.0,'upper':0.0,'n_models':0,'calibrated':False}
        x=self._feature_frame(pd.DataFrame([case]),fit=False)
        raw=np.array([m.predict_proba(x)[0,1] for m in self.models[action]],dtype=float)
        raw_mean=float(raw.mean()); std=float(raw.std(ddof=1)) if len(raw)>1 else 0.0
        mean=self._calibrate(action,raw_mean)
        # Conservative interval around the calibrated center; the std remains the ensemble-dispersion proxy.
        lower=max(0.0,mean-1.96*std); upper=min(1.0,mean+1.96*std)
        return {'mean':mean,'std':std,'lower':lower,'upper':upper,'n_models':len(raw),'calibrated':action in self.calibrators}

    def predict_all_actions(self, case: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {a:self.predict_proba(case,a) for a in ACTIONS+['ESCALATE']}

    def predict_dataset(self, cases: List[Dict[str, Any]]) -> List[Dict[str, Dict[str, Any]]]:
        if not cases: return []
        frame=pd.DataFrame(cases); x=self._feature_frame(frame,fit=False)
        out_per={}
        for action in ACTIONS:
            matrix=np.vstack([m.predict_proba(x)[:,1] for m in self.models[action]])
            raw_means=matrix.mean(axis=0); stds=matrix.std(axis=0,ddof=1) if matrix.shape[0]>1 else np.zeros(matrix.shape[1])
            cal=self.calibrators.get(action)
            means=cal.predict(raw_means) if cal is not None else raw_means
            out_per[action]=[{'mean':float(mu),'std':float(sd),'lower':float(max(0.0,mu-1.96*sd)),'upper':float(min(1.0,mu+1.96*sd)),'n_models':int(matrix.shape[0]),'calibrated':cal is not None} for mu,sd in zip(means,stds)]
        result=[]
        for i in range(len(cases)):
            row={a:out_per[a][i] for a in ACTIONS}; row['ESCALATE']={'mean':0.0,'std':0.0,'lower':0.0,'upper':0.0,'n_models':0,'calibrated':False}; result.append(row)
        return result
