# Backward-compatible API shim for older local tests/examples.
from pathlib import Path
from .calibrated_tlearner import CalibratedTLearner


class TLearner(CalibratedTLearner):
    def __init__(self, model_path=None):
        model_path = Path(model_path) if model_path is not None else None
        model_dir = model_path.parent if model_path is not None else None
        super().__init__(model_dir=model_dir, n_bootstrap=4)
        self.legacy_model_path = model_path

    def train(self, training_df, action_col='action', outcome_col='outcome'):
        super().train(training_df, action_col, outcome_col)
        if self.legacy_model_path:
            # Save the modern artifact at the legacy path too for compatibility.
            from joblib import dump
            dump({'models':self.models,'calibrators':self.calibrators,'columns':self.columns,'n_bootstrap':self.n_bootstrap,'random_seed':self.random_seed}, self.legacy_model_path)

    def load(self):
        if self.legacy_model_path and self.legacy_model_path.exists():
            from joblib import load
            data=load(self.legacy_model_path)
            self.models=data['models']; self.calibrators=data.get('calibrators',{}); self.columns=data['columns']; self.n_bootstrap=data.get('n_bootstrap',4); self.random_seed=data.get('random_seed',20260820)
        else:
            super().load()

    def predict(self, case):
        preds=self.predict_all_actions(case)
        return {a:float(preds[a]['mean']) for a in ['WAIT','NUDGE','MANUAL_RECOVERY','ESCALATE']}
