import pandas as pd
import numpy as np
from app.evaluation.ope import estimate_ips, estimate_snips, estimate_dr, overlap_diagnostics
from app.economics import MerchantConfig, EconomicsEngine
from app.decision.replay import stable_hash

def test_ope_estimators_finite():
    rewards=np.array([1.,2.,3.,4.]); acts=np.array([0,1,2,0]); beh=np.tile(np.array([.4,.3,.2,.1]),(4,1)); pol=beh.copy(); pred=np.ones((4,4))*2
    empty=pd.DataFrame(index=range(4))
    assert np.isfinite(estimate_ips(empty,pol,beh,acts,rewards)['ips'])
    assert np.isfinite(estimate_snips(empty,pol,beh,acts,rewards)['snips'])
    assert np.isfinite(estimate_dr(empty,pol,beh,acts,rewards,pred)['dr'])
    assert 'overall' in overlap_diagnostics(empty,beh,acts,['WAIT','NUDGE','MANUAL_RECOVERY','ESCALATE'])

def test_merchant_profiles_change_utility():
    case={'amount':2000,'contact_count_7d':5}
    aggressive=EconomicsEngine(merchant_config=MerchantConfig(risk_mode='AGGRESSIVE',customer_fatigue_penalty=0))
    brand=EconomicsEngine(merchant_config=MerchantConfig(risk_mode='CONSERVATIVE',customer_fatigue_penalty=200))
    assert aggressive.incremental_net_value(case,'NUDGE',.8,.3) != brand.incremental_net_value(case,'NUDGE',.8,.3)

def test_hash_stable():
    assert stable_hash({'a':1}) == stable_hash({'a':1})
