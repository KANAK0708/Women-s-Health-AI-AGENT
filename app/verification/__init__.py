"""Claim-to-Passage Entailment Verification subsystem.

Implements Section 6, Section 8, and Section 10 of the Implementation Plan:
- Verifies that every material claim maps to a valid citation ID ('e1', 'e2', etc.).
- Verifies that cited citation IDs resolve to retrieved, non-superseded passage IDs.
- Performs lexical and semantic entailment checks between claim text and passage text.
- Rejects unsupported high-risk claims (e.g. 'cure', 'guaranteed', unverified dosages).
"""

from app.verification.verifier import (
    ClaimVerificationResult,
    ClaimVerifier,
    VerificationDecision,
    VerificationReport,
    VerificationStatus,
)

__all__ = [
    "ClaimVerificationResult",
    "ClaimVerifier",
    "VerificationDecision",
    "VerificationReport",
    "VerificationStatus",
]

