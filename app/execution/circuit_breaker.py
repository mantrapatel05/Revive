import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self._half_open_probe = False

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.last_failure_time is not None and time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._half_open_probe = False
            else:
                return False
        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_probe:
                return False
            self._half_open_probe = True
        return True

    def record_success(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self._half_open_probe = False

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        self._half_open_probe = False
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self._half_open_probe = False
