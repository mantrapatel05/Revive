from __future__ import annotations
from typing import Dict, Any, List
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

class TwoModelUplift:
    """Action-vs-WAIT uplift estimator.

    For each intervention, fit one success model on WAIT examples and one on the intervention.
    Uplift is predicted as P(success|action) - P(success|WAIT).
    This is an honest uplift framing; it is not claimed to be a fully causal estimator
    without randomized/ignorable treatment assignment.
    """
    ACTIONS = ["NUDGE", "MANUAL_RECOVERY"]
    ID_COLS = {"event_id", "subscription_id", "customer_id", "subscription_status", "action", "outcome", "world_seed"}

    def __init__(self):
        self.models: Dict[str, tuple] = {}
        self.columns: List[str] = []

    def _prepare(self, df: pd.DataFrame, fit=False):
        cols=[c for c in df.columns if c not in self.ID_COLS]
        x=df[cols].copy()
        cats=[c for c in x.columns if x[c].dtype == object]
        x=pd.get_dummies(x, columns=cats, drop_first=True)
        if fit: self.columns=x.columns.tolist()
        else: x=x.reindex(columns=self.columns, fill_value=0)
        return x.astype(float)

    def fit(self, train_df: pd.DataFrame):
        base=train_df.copy()
        self._prepare(base, fit=True)
        wait=base[base.action=='WAIT'].copy()
        for action in self.ACTIONS:
            treated=base[base.action==action].copy()
            if len(wait)<20 or len(treated)<20: continue
            yw=wait.outcome.map({'SUCCESS':1,'FAILURE':0}).astype(int)
            yt=treated.outcome.map({'SUCCESS':1,'FAILURE':0}).astype(int)
            mw=GradientBoostingClassifier(random_state=42).fit(self._prepare(wait), yw)
            mt=GradientBoostingClassifier(random_state=42).fit(self._prepare(treated), yt)
            self.models[action]=(mw,mt)
        return self

    def predict_uplift(self, case: Dict[str, Any], action: str) -> float:
        if action not in self.models: return 0.0
        mw,mt=self.models[action]
        x=self._prepare(pd.DataFrame([case]))
        return float(mt.predict_proba(x)[0,1]-mw.predict_proba(x)[0,1])

    def predict_all(self, case: Dict[str, Any]) -> Dict[str,float]:
        out={'WAIT':0.0,'ESCALATE':0.0}
        for a in self.ACTIONS: out[a]=self.predict_uplift(case,a)
        return out

try:
    from causalml.inference.meta import BaseSClassifier  # type: ignore
    CAUSALML_AVAILABLE=True
except Exception:
    BaseSClassifier=None
    CAUSALML_AVAILABLE=False
