from enum import Enum

class SubscriptionState(str, Enum):
    CREATED = "created"
    AUTHENTICATED = "authenticated"
    ACTIVE = "active"
    PENDING = "pending"
    HALTED = "halted"
    PAUSED = "paused"
    CANCELLED = "cancelled"

class SubscriptionStateMachine:
    EVENT_TO_STATE = {
        "subscription.authenticated": SubscriptionState.AUTHENTICATED,
        "subscription.activated": SubscriptionState.ACTIVE,
        "subscription.charged": SubscriptionState.ACTIVE,
        "subscription.pending": SubscriptionState.PENDING,
        "subscription.halted": SubscriptionState.HALTED,
        "subscription.paused": SubscriptionState.PAUSED,
        "subscription.resumed": SubscriptionState.ACTIVE,
        "subscription.cancelled": SubscriptionState.CANCELLED,
    }

    TRANSITIONS = {
        SubscriptionState.CREATED: {SubscriptionState.AUTHENTICATED, SubscriptionState.CANCELLED},
        SubscriptionState.AUTHENTICATED: {SubscriptionState.ACTIVE, SubscriptionState.CANCELLED},
        SubscriptionState.ACTIVE: {SubscriptionState.PENDING, SubscriptionState.PAUSED, SubscriptionState.CANCELLED},
        SubscriptionState.PENDING: {SubscriptionState.ACTIVE, SubscriptionState.HALTED, SubscriptionState.PENDING},
        SubscriptionState.HALTED: {SubscriptionState.ACTIVE, SubscriptionState.CANCELLED},
        SubscriptionState.PAUSED: {SubscriptionState.ACTIVE, SubscriptionState.CANCELLED},
        SubscriptionState.CANCELLED: set(),
    }

    @classmethod
    def from_event(cls, event_type: str, default: SubscriptionState = SubscriptionState.ACTIVE):
        return cls.EVENT_TO_STATE.get(event_type, default)

    @classmethod
    def can_transition(cls, current: SubscriptionState, target: SubscriptionState) -> bool:
        return target in cls.TRANSITIONS.get(current, set())
