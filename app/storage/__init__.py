"""Session Memory and Patient Context Storage package."""

from app.storage.consent import (
    CURRENT_CONSENT_VERSION,
    DEFAULT_SESSION_TTL_MINUTES,
    ConsentPolicy,
)
from app.storage.context_tracker import ContextTracker
from app.storage.session_store import EphemeralSessionStore


def __getattr__(name):
    if name in {"RedisSessionStore", "get_session_store"}:
        from app.storage import redis_session_store
        return getattr(redis_session_store, name)
    raise AttributeError(name)

__all__ = [
    "CURRENT_CONSENT_VERSION",
    "ConsentPolicy",
    "ContextTracker",
    "DEFAULT_SESSION_TTL_MINUTES",
    "EphemeralSessionStore",
    "RedisSessionStore",
    "get_session_store",
]


