from datetime import datetime, timezone
import json
from app.db import enqueue_webhook_event, get_conn

def is_duplicate_event(event_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute('SELECT 1 FROM webhook_events WHERE event_id=?', (event_id,)).fetchone()
        return row is not None

def record_event(event_id: str, event_type: str, payload: dict) -> bool:
    return enqueue_webhook_event(
        event_id,
        event_type,
        json.dumps(payload, separators=(',', ':'), ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(),
    )
