"""Razorpay Test Mode lifecycle smoke demo.

Default mode is safe/local: it creates a signed subscription.pending webhook payload and
passes it through REVIVE's actual FastAPI webhook inbox + worker path.
Set RAZORPAY_PLAN_ID, RAZORPAY_CUSTOMER_ID and Razorpay test credentials to optionally
create a real test subscription before the webhook demonstration.
"""
import os, sys, json, time, hmac, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
import app.api.webhooks as webhook_module
from app.main import app
from scripts.worker import main_once
from app.db import get_conn
from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

SECRET=os.getenv('RAZORPAY_WEBHOOK_SECRET','demo-test-secret')
webhook_module.RAZORPAY_WEBHOOK_SECRET=SECRET

def maybe_create_real_subscription():
    plan=os.getenv('RAZORPAY_PLAN_ID'); customer=os.getenv('RAZORPAY_CUSTOMER_ID')
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and plan and customer): return None
    import requests
    payload={'plan_id':plan,'customer_id':customer,'total_count':12,'quantity':1,'start_at':int(time.time())+60}
    r=requests.post('https://api.razorpay.com/v1/subscriptions',auth=(RAZORPAY_KEY_ID,RAZORPAY_KEY_SECRET),json=payload,timeout=10)
    r.raise_for_status(); return r.json()

def main():
    sub=maybe_create_real_subscription(); sid=sub['id'] if sub else 'sub_demo_revive'
    payload={'event':'subscription.pending','payload':{'subscription':{'entity':{'id':sid,'customer_id':os.getenv('RAZORPAY_CUSTOMER_ID','cust_demo'),'amount':1999,'charge_attempt_count':1,'status':'pending'}}},'created_at':int(time.time())}
    raw=json.dumps(payload,separators=(',',':')).encode(); sig=hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest(); eid=f'evt_demo_{int(time.time()*1000)}'
    with TestClient(app) as client:
        r=client.post('/api/webhook/razorpay',content=raw,headers={'content-type':'application/json','x-razorpay-signature':sig,'x-razorpay-event-id':eid})
        print('Webhook response:',r.status_code,r.json())
        duplicate=client.post('/api/webhook/razorpay',content=raw,headers={'content-type':'application/json','x-razorpay-signature':sig,'x-razorpay-event-id':eid})
        print('Duplicate response:',duplicate.status_code,duplicate.json())
    processed=main_once(limit=20); print('Worker processed:',processed)
    with get_conn() as conn:
        row=conn.execute('SELECT status FROM webhook_events WHERE event_id=?',(eid,)).fetchone(); print('Final inbox status:',row['status'] if row else 'missing')
    if sub: print('Real Test Mode subscription:',sid)
    else: print('No real credentials/plan configured; local signed webhook demo completed.')
if __name__=='__main__': main()
