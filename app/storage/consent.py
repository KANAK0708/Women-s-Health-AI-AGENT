"""Consent verification and data retention policies for patient session storage.

Implements Section 2 and Section 9 of the Implementation Plan:
- Application-controlled consent and retention (no autonomous LLM file writes).
- No durable conversation history unless explicitly consented.
- Short-lived session TTL by default.
"""

from dataclasses import dataclass

CURRENT_CONSENT_VERSION = "v1.0-2026-11"
DEFAULT_SESSION_TTL_MINUTES = 30


@dataclass(frozen=True)
class ConsentPolicy:
    """Defines what a session is permitted to retain based on user consent."""

    consent_version: str = CURRENT_CONSENT_VERSION
    allow_minimal_session_context: bool = True
    allow_durable_history: bool = False
    ttl_minutes: int = DEFAULT_SESSION_TTL_MINUTES

    def validate(self) -> None:
        if self.ttl_minutes <= 0 or self.ttl_minutes > 120:
            raise ValueError("Session TTL must be between 1 and 120 minutes.")
        if self.allow_durable_history:
            raise PermissionError(
                "Durable conversation history is disabled in Phase 1 pilot policy."
            )

