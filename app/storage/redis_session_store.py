"""Redis-backed Ephemeral Patient Session Memory Store.

Implements Section 3, Section 8, and Section 9 of the Implementation Plan:
- Enforces hardware-level automatic TTL expiration using Redis SETEX.
- Provides immediate deletion cascades for GDPR/HIPAA compliance (DEL key).
- Stores only MinimalPatientContext and redacted audit codes (no durable raw health logs).
- Falls back gracefully to EphemeralSessionStore if Redis connection fails or is unconfigured.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis

from app.schemas.memory import MinimalPatientContext, SessionMemory
from app.storage.consent import CURRENT_CONSENT_VERSION, DEFAULT_SESSION_TTL_MINUTES, ConsentPolicy
from app.storage.session_store import EphemeralSessionStore

logger = logging.getLogger(__name__)

REDIS_URL_ENV = "REDIS_URL"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
REDIS_SESSION_PREFIX = "sess:health:"


class RedisSessionStore:
    """Redis-backed ephemeral session store with native key TTL expiration."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl_minutes: int = DEFAULT_SESSION_TTL_MINUTES,
    ) -> None:
        self.redis_url = redis_url or os.getenv(REDIS_URL_ENV, DEFAULT_REDIS_URL)
        self.default_ttl_minutes = default_ttl_minutes
        self._client: redis.Redis = redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )

    def _key(self, session_id: str) -> str:
        return f"{REDIS_SESSION_PREFIX}{session_id}"

    def ping(self) -> bool:
        """Check if Redis connection is active."""
        try:
            return bool(self._client.ping())
        except Exception as exc:
            logger.warning("Redis ping failed: %s", exc)
            return False

    def create_session(
        self,
        *,
        policy: Optional[ConsentPolicy] = None,
        now: Optional[datetime] = None,
    ) -> SessionMemory:
        """Create a new ephemeral session with native Redis TTL."""
        active_policy = policy or ConsentPolicy(ttl_minutes=self.default_ttl_minutes)
        active_policy.validate()

        current_time = now or datetime.now(timezone.utc)
        ttl_seconds = active_policy.ttl_minutes * 60

        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        session = SessionMemory(
            session_id=session_id,
            consent_version=active_policy.consent_version or CURRENT_CONSENT_VERSION,
            allow_session_context=active_policy.allow_minimal_session_context,
            created_at=current_time,
            expires_at=current_time + timedelta(seconds=ttl_seconds),
            context=MinimalPatientContext(),
            audit_codes=["SESSION_CREATED_REDIS"],
        )

        payload = session.model_dump_json()
        self._client.setex(self._key(session_id), ttl_seconds, payload)
        return session

    def get_session(
        self,
        session_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[SessionMemory]:
        """Fetch session from Redis; returns None if expired or deleted."""
        raw = self._client.get(self._key(session_id))
        if not raw:
            return None

        try:
            session = SessionMemory.model_validate_json(raw)
            current_time = now or datetime.now(timezone.utc)
            if session.is_expired(now=current_time):
                self.delete_session(session_id)
                return None
            return session
        except Exception as exc:
            logger.error("Failed to deserialize Redis session: %s", exc)
            self.delete_session(session_id)
            return None

    def save_session(
        self,
        session: SessionMemory,
        *,
        now: Optional[datetime] = None,
    ) -> SessionMemory:
        """Save updated session state, preserving remaining TTL."""
        current_time = now or datetime.now(timezone.utc)
        remaining_seconds = int((session.expires_at - current_time).total_seconds())

        if remaining_seconds <= 0:
            self.delete_session(session.session_id)
            raise ValueError(f"Session {session.session_id} has expired and was purged.")

        if not session.allow_session_context:
            session.context = MinimalPatientContext()
            session.audit_codes.append("CONTEXT_OPT_OUT_ENFORCED")

        payload = session.model_dump_json()
        self._client.setex(self._key(session.session_id), remaining_seconds, payload)
        return session

    def delete_session(self, session_id: str) -> bool:
        """Explicitly wipe session key from Redis (deletion cascade)."""
        deleted_count = self._client.delete(self._key(session_id))
        return deleted_count > 0

    def purge_expired(self, *, now: Optional[datetime] = None) -> int:
        """Redis cleans up expired keys automatically; no-op return for compatibility."""
        return 0


def get_session_store(
    *,
    force_in_memory: bool = False,
    redis_url: Optional[str] = None,
    default_ttl_minutes: int = DEFAULT_SESSION_TTL_MINUTES,
) -> RedisSessionStore | EphemeralSessionStore:
    """Factory returning RedisSessionStore if Redis is configured and reachable;
    otherwise gracefully falls back to EphemeralSessionStore.
    """
    if force_in_memory:
        return EphemeralSessionStore(default_ttl_minutes=default_ttl_minutes)

    target_url = redis_url or os.getenv(REDIS_URL_ENV)
    if target_url:
        try:
            store = RedisSessionStore(redis_url=target_url, default_ttl_minutes=default_ttl_minutes)
            if store.ping():
                return store
            logger.warning("Redis at %s unreachable, falling back to in-memory session store.", target_url)
        except Exception as exc:
            logger.warning("Failed connecting to Redis: %s. Using in-memory fallback.", exc)

    return EphemeralSessionStore(default_ttl_minutes=default_ttl_minutes)

