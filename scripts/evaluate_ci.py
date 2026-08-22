import json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.execution.simulator import SubscriptionSimulator
from app.policy.gate import PolicyGate
from app.pipeline import RecoveryPipeline
from app.config import DATA_DIR, RESULTS_DIR

SEEDS=[42,7,2024,1337,999,1234,5678,9012,3456,7890]

def run(seed):
    cases=pd.read_csv(DATA_DIR/'eval_cases.csv').to_dict('records')
    pipe=RecoveryPipeline(model=None,policy=PolicyGate(),simulator=SubscriptionSimulator(seed),risk_mode='BALANCED')
    return sum(pipe.process(c,source='sim')['net_recovered'] for c in cases)

def bootstrap_ci(values,n_boot=2000,alpha=.95):
    rng=np.random.default_rng(42); vals=np.asarray(values,float); means=[rng.choice(vals,len(vals),replace=True).mean() for _ in range(n_boot)]
    return float(np.quantile(means,(1-alpha)/2)),float(np.quantile(means,1-(1-alpha)/2))

def main():
    vals=[run(s) for s in SEEDS]; lo,hi=bootstrap_ci(vals); out={'mean':float(np.mean(vals)),'std':float(np.std(vals)),'ci_95':[lo,hi],'seeds':SEEDS}; RESULTS_DIR.mkdir(parents=True,exist_ok=True); (RESULTS_DIR/'ci_results.json').write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
