import json,sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.pipeline import RecoveryPipeline
from app.policy.gate import PolicyGate
from app.execution.simulator import SubscriptionSimulator
from app.config import DATA_DIR,RESULTS_DIR

def main():
    df=pd.read_csv(DATA_DIR/'eval_cases.csv'); pipe=RecoveryPipeline(model=None,policy=PolicyGate(),simulator=SubscriptionSimulator(42)); out={}
    for scenario,g in df.groupby('failure_reason'):
        vals=[]
        for _,r in g.iterrows(): vals.append(pipe.process(r.to_dict(),source='sim')['net_recovered'])
        out[scenario]={'count':len(vals),'net_recovered':float(sum(vals)),'avg_net':float(sum(vals)/len(vals)) if vals else 0.0}
    RESULTS_DIR.mkdir(parents=True,exist_ok=True); (RESULTS_DIR/'scenario_breakdown.json').write_text(json.dumps(out,indent=2)); print(json.dumps(out,indent=2))
if __name__=='__main__': main()
