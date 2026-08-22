import json
from app.db import get_conn

class AuditLogger:
    def log(self, record: dict):
        with get_conn() as conn:
            conn.execute(
                '''INSERT INTO audit_logs(decision_id,event_id,case_id,timestamp,payload_json)
                   VALUES (?,?,?,?,?)''',
                (record.get('decision_id'), record['event_id'], record.get('case_id', record['event_id']), record['timestamp'], json.dumps(record, default=str)),
            )

    def recent(self, limit: int = 50):
        with get_conn() as conn:
            rows = conn.execute(
                'SELECT payload_json FROM audit_logs ORDER BY id DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]
