import requests, json
import psycopg2

BASE = 'http://localhost:8000'
s = requests.Session()

print('1. /api/evaluation')
r = s.get(f'{BASE}/api/evaluation')
print(r.status_code, list(r.json().keys()) if r.status_code == 200 else r.text)

print('\n2. /api/audit')
r = s.get(f'{BASE}/api/audit?limit=2')
print(r.status_code, 'Logs retrieved:', len(r.json().get('logs', [])))

print('\n3. GET /api/merchant-config')
r = s.get(f'{BASE}/api/merchant-config')
print(r.status_code, r.json())

print('\n4. PUT /api/merchant-config')
cfg = r.json().get('config', {})
cfg['max_auto_action_amount'] = 3000
r = s.put(f'{BASE}/api/merchant-config', json=cfg)
print(r.status_code, r.json())

print('\n5. /api/random-case')
r = s.get(f'{BASE}/api/random-case')
case_id = r.json()['event_id']
print(r.status_code, case_id)

print('\n6. /api/replay/{id}')
r = s.get(f'{BASE}/api/replay/{case_id}')
print(r.status_code, list(r.json().keys()) if r.status_code == 200 else r.text)

print('\n7. /receipt/{id}')
r = s.get(f'{BASE}/receipt/{case_id}')
print(r.status_code, 'Content-Type:', r.headers.get('content-type'), 'Length:', len(r.text))

print('\n8. /api/approvals/pending and resolve')
conn = psycopg2.connect('postgresql://revive_admin:revive_dev_password@localhost:5433/revive')
cur = conn.cursor()
cur.execute("INSERT INTO approval_queue(decision_id, case_id, requested_action, status, created_at) VALUES('test-dec', 'test-case', 'MANUAL_RECOVERY', 'PENDING', '2026-08-30T00:00:00Z') RETURNING id;")
app_id = cur.fetchone()[0]
conn.commit()

r = s.get(f'{BASE}/api/approvals/pending')
print('Pending approvals:', r.status_code, len(r.json().get('approvals', [])))

r = s.post(f'{BASE}/api/approvals/{app_id}/resolve', json={'decision': 'APPROVED', 'reviewer': 'test'})
print('Resolve approval:', r.status_code, r.json())

cur.execute("DELETE FROM approval_queue WHERE id = %s;", (app_id,))
conn.commit()
