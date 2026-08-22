from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List


def calculate_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    expected=pd.Series(expected).dropna().astype(float)
    actual=pd.Series(actual).dropna().astype(float)
    if len(expected)==0 or len(actual)==0: return 0.0
    edges=np.unique(np.quantile(expected, np.linspace(0,1,bins+1)))
    if len(edges)<3: return 0.0
    e,_=np.histogram(expected,bins=edges); a,_=np.histogram(actual,bins=edges)
    ep=np.clip(e/e.sum(),1e-6,None); ap=np.clip(a/a.sum(),1e-6,None)
    return float(np.sum((ap-ep)*np.log(ap/ep)))


def detect_drift(training_df: pd.DataFrame, new_df: pd.DataFrame, feature_cols: List[str], threshold: float=0.2) -> Dict[str,object]:
    scores={}
    for col in feature_cols:
        if col not in training_df or col not in new_df: continue
        if pd.api.types.is_numeric_dtype(training_df[col]):
            scores[col]=calculate_psi(training_df[col],new_df[col])
    drifted={k:v for k,v in scores.items() if v>threshold}
    return {"drift_scores":scores,"drifted_features":drifted,"drift_detected":bool(drifted)}
