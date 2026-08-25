import argparse
import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.config import DATA_DIR, MODEL_DIR
from app.models.calibrated_tlearner import CalibratedTLearner
from app.models.calibrated_xlearner import CalibratedXLearner

def main():
    parser = argparse.ArgumentParser(description="Train REVIVE causal uplift models")
    parser.add_argument("--model", choices=["tlearner", "xlearner"], default="tlearner", help="Model architecture to train")
    args = parser.parse_args()

    df = pd.read_csv(DATA_DIR / 'training_data.csv')
    if args.model == "xlearner":
        model = CalibratedXLearner(MODEL_DIR, n_bootstrap=8)
        model.train(df)
        print('saved calibrated_xlearner.joblib')
    else:
        model = CalibratedTLearner(MODEL_DIR, n_bootstrap=8)
        model.train(df)
        print('saved calibrated_tlearner.joblib')

if __name__ == '__main__':
    main()
