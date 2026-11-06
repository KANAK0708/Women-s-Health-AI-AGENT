"""Ephemeral, TTL-governed session memory store with explicit deletion cascades.

Implements Section 3, Section 8, and Section 9 of the Implementation Plan:
- Strictly isolated from the non-patient clinical evidence registry.
- Enforces TTL expiry on read and write.
- Provides immediate user-triggered deletion cascade.
- Stores only MinimalPatientContext and redacted audit codes (no raw chat logs).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.schemas.memory import MinimalPatientContext, SessionMemory
from app.storage.consent import CURRENT_CONSENT_VERSION, DEFAULT_SESSION_TTL_MINUTES, ConsentPolicy


class EphemeralSessionStore:
    """In-memory TTL-enforced session store for minimal patient context."""

    def __init__(self, default_ttl_minutes: int = DEFAULT_SESSION_TTL_MINUTES) -> None:
        self._default_ttl_minutes = default_ttl_minutes
        self._sessions: dict[str, SessionMemory] = {}

    def create_session(
        self,
        *,
        policy: Optional[ConsentPolicy] = None,
        now: Optional[datetime] = None,
    ) -> SessionMemory:
        """Create a new ephemeral session governed by a validated ConsentPolicy."""
        active_policy = policy or ConsentPolicy(ttl_minutes=self._default_ttl_minutes)
        active_policy.validate()

        current_time = now or datetime.now(timezone.utc)
        self.purge_expired(now=current_time)

        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        session = SessionMemory(
            session_id=session_id,
            consent_version=active_policy.consent_version or CURRENT_CONSENT_VERSION,
            allow_session_context=active_policy.allow_minimal_session_context,
            created_at=current_time,
            expires_at=current_time + timedelta(minutes=active_policy.ttl_minutes),
            context=MinimalPatientContext(),
            audit_codes=["SESSION_CREATED"],
        )
        self._sessions[session_id] = session
        return session

    def get_session(
        self,
        session_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[SessionMemory]:
        """Retrieve an active session if it exists and has not expired."""
        current_time = now or datetime.now(timezone.utc)
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(now=current_time):
            self.delete_session(session_id)
            return None
        return session

    def save_session(
        self,
        session: SessionMemory,
        *,
        now: Optional[datetime] = None,
    ) -> SessionMemory:
        """Save updated session state if within TTL and consent allows context."""
        current_time = now or datetime.now(timezone.utc)
        if session.is_expired(now=current_time):
            self.delete_session(session.session_id)
            raise ValueError(f"Session {session.session_id} has expired and was purged.")

        if not session.allow_session_context:
            # If user opted out of session context, reset minimal context on each turn
            session.context = MinimalPatientContext()
            session.audit_codes.append("CONTEXT_OPT_OUT_ENFORCED")

        self._sessions[session.session_id] = session
        return session

    def delete_session(self, session_id: str) -> bool:
        """Explicitly wipe a session and all associated minimal context (deletion cascade)."""
        removed = self._sessions.pop(session_id, None)
        if removed is not None:
            removed.context = MinimalPatientContext()
            removed.audit_codes.clear()
            return True
        return False

    def purge_expired(self, *, now: Optional[datetime] = None) -> int:
        """Purge all expired sessions and return count of purged sessions."""
        current_time = now or datetime.now(timezone.utc)
        expired_ids = [
            sid for sid, sess in self._sessions.items() if sess.is_expired(now=current_time)
        ]
        for sid in expired_ids:
            self.delete_session(sid)
        return len(expired_ids)

    @property
    def active_session_count(self) -> int:
        self.purge_expired()
        return len(self._sessions)

