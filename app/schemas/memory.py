"""Patient session memory and context schemas.

Implements Section 4, Section 8, and Section 9 of the Implementation Plan:
- Separate trust domain from the clinical evidence registry.
- Explicit TriState ('yes', 'no', 'not_provided') so missing context never
  silently becomes a negative clinical finding.
- Bounded clarification limit (maximum 2 turns).
- Ephemeral session storage with enforced TTL and redacted audit codes.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class TriState(str, Enum):
    """Explicit three-state representation to distinguish 'not_provided' from 'no'."""

    YES = "yes"
    NO = "no"
    NOT_PROVIDED = "not_provided"


class MinimalPatientContext(BaseModel):
    """Minimal, optional session context with strict clarification limits."""

    age: Optional[int] = Field(default=None, ge=1, le=120)
    is_adult: TriState = TriState.NOT_PROVIDED
    pregnancy_status: TriState = TriState.NOT_PROVIDED
    current_medications_mentioned: TriState = TriState.NOT_PROVIDED
    irregular_cycles_mentioned: TriState = TriState.NOT_PROVIDED
    severe_symptom_flag: TriState = TriState.NOT_PROVIDED
    active_topic: Optional[str] = None
    clarification_turns_used: int = Field(default=0, ge=0, le=2)

    def can_request_clarification(self) -> bool:
        """Enforce the maximum 2 focused clarification turns limit."""
        return self.clarification_turns_used < 2


class SessionMemory(BaseModel):
    """Ephemeral session state governed by explicit consent and TTL."""

    session_id: str
    consent_version: str = "v1.0"
    allow_session_context: bool = True
    created_at: datetime
    expires_at: datetime
    turn_count: int = 0
    context: MinimalPatientContext = Field(default_factory=MinimalPatientContext)
    audit_codes: list[str] = Field(
        default_factory=list,
        description="Redacted operational decision codes only; never raw health text.",
    )

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Check whether the session TTL has elapsed."""
        reference = now or datetime.now(timezone.utc)
        return reference >= self.expires_at
