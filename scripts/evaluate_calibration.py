import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.models.calibrated_tlearner import CalibratedTLearner
from app.execution.simulator import SubscriptionSimulator
from app.config import DATA_DIR, MODEL_DIR, RESULTS_DIR


def main():
    model=CalibratedTLearner(MODEL_DIR); model.load(); df=pd.read_csv(DATA_DIR/'eval_cases.csv'); sim=SubscriptionSimulator(42); rows=[]
    for _,r in df.iterrows():
        c=r.to_dict()
        for a in ['WAIT','NUDGE','MANUAL_RECOVERY']:
            p=model.predict_proba(c,a)['mean']; y=int(sim.execute(c,a).success); rows.append((p,y))
    bins=np.linspace(0,1,11); out=[]; brier=[]
    for lo,hi in zip(bins[:-1],bins[1:]):
        g=[x for x in rows if lo<=x[0]<(hi if hi<1 else hi+1e-9)]
        if g: out.append({'bin_mid':float((lo+hi)/2),'count':len(g),'pred':float(np.mean([x[0] for x in g])),'observed':float(np.mean([x[1] for x in g]))})
    brier=float(np.mean([(p-y)**2 for p,y in rows])); RESULTS_DIR.mkdir(parents=True,exist_ok=True); (RESULTS_DIR/'calibration.json').write_text(json.dumps({'brier':brier,'bins':out},indent=2)); print(json.dumps({'brier':brier,'bins':out},indent=2))
if __name__=='__main__': main()
