from __future__ import annotations
from typing import Any, Dict
import pandas as pd

class SHAPExplainer:
    """Optional local explanations for the action-specific linear models.

    SHAP is imported lazily so the core REVIVE installation does not depend on it.
    For the logistic bootstrap ensemble we explain the first model in the requested action.
    """
    def __init__(self, calibrated_model):
        self.model = calibrated_model

    def explain_case(self, case: Dict[str, Any], action: str, top_k: int = 8) -> Dict[str, Any]:
        try:
            import shap  # optional
        except ImportError as exc:
            return {"available": False, "reason": "Install shap to enable local explanations."}
        if action not in self.model.models:
            return {"available": False, "reason": f"No model for {action}"}
        frame = pd.DataFrame([case])
        X = self.model._feature_frame(frame, fit=False)
        model = self.model.models[action][0]
        explainer = shap.LinearExplainer(model, X)
        values = explainer.shap_values(X)
        if isinstance(values, list):
            values = values[1]
        vals = values[0]
        ranked = sorted(zip(X.columns.tolist(), vals.tolist()), key=lambda x: abs(x[1]), reverse=True)[:top_k]
        return {"available": True, "action": action, "features": [{"feature": k, "shap": float(v)} for k, v in ranked]}
