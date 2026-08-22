import sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app.execution.simulator import SubscriptionSimulator
from app.pipeline import RecoveryPipeline
from app.policy.gate import PolicyGate
from app.evaluation.baselines import baseline_rule_based
from app.economics import EconomicsEngine
from app.config import DATA_DIR
SEEDS=[42,7,2024,1337,999,1234,5678,9012,3456,7890]

def expected_rewards(strategy):
    df=pd.read_csv(DATA_DIR/'eval_cases.csv'); out=[]; econ=EconomicsEngine()
    for seed in SEEDS:
        sim=SubscriptionSimulator(seed); pipe=RecoveryPipeline(model=None,policy=PolicyGate(),simulator=sim)
        total=0.0
        for _,r in df.iterrows():
            c=r.to_dict()
            if strategy=='native': a='WAIT'
            elif strategy=='rule': a=baseline_rule_based(c)
            else: a=pipe.process(c,source='sim')['chosen_action']
            total += econ.expected_net_value(c,a,sim.get_true_probability(c,a),econ.expected_days(c,a))
        out.append(total)
    return np.asarray(out,float)

def main():
    revive=expected_rewards('revive'); native=expected_rewards('native'); rule=expected_rewards('rule')
    r1=stats.ttest_rel(revive,native); r2=stats.ttest_rel(revive,rule)
    print(f'Expected-value REVIVE vs Native: t={r1.statistic:.4f}, p={r1.pvalue:.6f}')
    print(f'Expected-value REVIVE vs Rule:   t={r2.statistic:.4f}, p={r2.pvalue:.6f}')
    print('Interpretation: a non-significant result means the benchmark does not establish a statistically reliable difference on this synthetic seed set.')
if __name__=='__main__': main()
