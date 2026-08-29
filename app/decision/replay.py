import hashlib, json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.db import get_conn

def stable_hash(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(body).hexdigest()

class DecisionStore:
    def save(self, record: Dict[str, Any]) -> str:
        decision_id = str(record["decision_id"])
        case_id = str(record.get("case_id", record.get("event_id", decision_id)))
        features = record.get("features") or record.get("case_snapshot") or {}
        with get_conn() as conn:
            conn.execute("""INSERT INTO decision_records
                (decision_id, case_id, feature_json, action, policy_version, model_version, prompt_version, scenario_version, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(decision_id) DO NOTHING""",
                (decision_id, case_id, json.dumps(features, default=str), record.get("chosen_action"),
                 record.get("policy_version"), record.get("model_version"), record.get("prompt_version"),
                 record.get("scenario_version"), datetime.now(timezone.utc).isoformat()))
        return decision_id

    def get_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM decision_records WHERE decision_id=?", (decision_id,)).fetchone()
        if not row: return None
        out = dict(row)
        raw_features = out.pop("feature_json")
        out["features"] = raw_features if isinstance(raw_features, dict) else json.loads(raw_features)
        return out

    def replay_with_current(self, decision_id: str, pipeline) -> Dict[str, Any]:
        old = self.get_decision(decision_id)
        if old is None: raise ValueError("Decision not found")
        case = dict(old["features"])
        case["event_id"] = old["case_id"]
        new = pipeline.process(case)
        return {"old_decision": old, "new_decision": new}
