from app.policy.gate import PolicyGate

def base(**kw):
    x={"subscription_status":"pending","amount":1999,"customer_opted_out":False,"invoice_status":"issued","payment_method_type":"international_card","native_retry_scheduled":True}; x.update(kw); return x

def test_wait_allowed():
    r=PolicyGate().evaluate(base(),"WAIT",0.5,True); assert r.decision=="APPROVED" and r.action=="WAIT"

def test_manual_blocked_when_native_retry_scheduled():
    r=PolicyGate().evaluate(base(),"MANUAL_RECOVERY",0.8,True); assert r.decision=="BLOCKED" and r.action=="WAIT"

def test_domestic_card_manual_blocked():
    r=PolicyGate().evaluate(base(payment_method_type="domestic_card",native_retry_scheduled=False),"MANUAL_RECOVERY",0.8,False); assert r.decision=="BLOCKED"

def test_high_amount_escalates():
    r=PolicyGate().evaluate(base(amount=9000,native_retry_scheduled=False),"MANUAL_RECOVERY",0.8,False); assert r.decision=="BLOCKED" and r.action=="ESCALATE"
