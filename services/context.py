from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from uuid import uuid4


@dataclass(frozen=True)
class ExecutionContext:
    source: str
    budget_seconds: float = 15.0
    request_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    monotonic_start: float = field(default_factory=time.monotonic)

    @property
    def deadline(self):
        return self.monotonic_start + self.budget_seconds

    @property
    def remaining_time(self):
        return max(0, self.deadline - time.monotonic())

    def require_time(self):
        if self.remaining_time <= 0:
            raise TimeoutError('Request deadline exhausted before submission')


from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT = ContextVar('execution_context', default=None)

def current_context():
    return _CURRENT.get()

@contextmanager
def use_context(context):
    token=_CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
