import sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.config import DATA_DIR, MODEL_DIR
from app.models.calibrated_tlearner import CalibratedTLearner

def main():
    df=pd.read_csv(DATA_DIR/'training_data.csv')
    model=CalibratedTLearner(MODEL_DIR,n_bootstrap=8)
    model.train(df)
    print('saved calibrated_tlearner.joblib')
if __name__=='__main__': main()
