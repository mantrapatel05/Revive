import pandas as pd
from app.pipeline import RecoveryPipeline
from app.execution.simulator import SubscriptionSimulator

df = pd.read_csv('data/generated/eval_cases.csv')
case = df[df.event_id == 'EVT-00837'].iloc[0].to_dict()

pipeline = RecoveryPipeline(simulator=SubscriptionSimulator(42))
decision = pipeline.process(case)
print('Decision:', decision['policy_decision'])
print('Reasons:', decision['policy_reasons'])
print('Checks:')
for c in decision['policy_checks']:
    if not c.get('passed', True):
        print(f" - Failed: {c.get('description', '')}")
