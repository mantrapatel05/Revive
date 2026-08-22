from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid


@dataclass(frozen=True)
class ExecutionAuthorization:
    decision_id: str
    case_id: str
    action: str
    policy_version: str
    model_version: str
    expires_at: datetime
    authorized: bool

    @staticmethod
    def create(case_id: str, action: str, policy_version: str, model_version: str) -> "ExecutionAuthorization":
        return ExecutionAuthorization(
            decision_id=str(uuid.uuid4()),
            case_id=case_id,
            action=action,
            policy_version=policy_version,
            model_version=model_version,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            authorized=True,
        )

    def is_valid(self, current_policy_version: str, current_model_version: str) -> bool:
        return self.authorized and self.expires_at > datetime.now(timezone.utc) and self.policy_version == current_policy_version and self.model_version == current_model_version
