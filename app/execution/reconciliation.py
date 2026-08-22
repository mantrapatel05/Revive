from enum import Enum
import hashlib

class ReconciliationState(str, Enum):
    UNKNOWN='unknown'
    CONFIRMED='confirmed'
    FAILED='failed'

def reconcile_payment(case_id: str, action: str) -> ReconciliationState:
    # Synthetic deterministic stand-in. Real integration should query the provider.
    h=int(hashlib.sha256(f'{case_id}|{action}'.encode()).hexdigest()[:8],16)%10
    return ReconciliationState.CONFIRMED if h<7 else ReconciliationState.FAILED
