"""Custom exceptions for the Retrieval and Evidence Governance subsystem."""


class RetrievalError(Exception):
    """Base exception for retrieval pipeline errors."""


class ScopeViolationError(RetrievalError):
    """Raised when a query requests disallowed actions (prescriptions, dosages, diagnosis)."""


class UrgentEscalationRequired(RetrievalError):
    """Raised when deterministic red-flag hazard rules trigger before retrieval."""

    def __init__(self, message: str, protocol_id: str = "PROTO-URGENT-001") -> None:
        super().__init__(message)
        self.protocol_id = protocol_id


class InsufficientEvidenceError(RetrievalError):
    """Raised when no approved, current, in-scope passages meet coverage thresholds."""
