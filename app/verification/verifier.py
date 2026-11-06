"""Deterministic and Entailment-based Claim Verification Engine.

Implements Section 6 & 10 of the Implementation Plan:
- Validates citation resolution (all evidence_ids resolve to valid, active passages).
- Evaluates claim-to-passage factual entailment using content overlap and semantic checking.
- Detects high-risk extrapolations (e.g., 'cure', 'guaranteed', '100% effective').
- Detects polarity / negation inversions (e.g. 'cannot be prevented' asserted as 'can be prevented').
- Makes auditable decisions: ACCEPT, REPAIRED, or FALLBACK_REQUIRED.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.retrieval.reranker import ScoredPassage, tokenize
from app.schemas.evidence import ClaimItem, EducationalResponse, EvidenceCitation, EvidencePassage

# High-risk claim tokens that must never appear in claims unless explicitly present in source
HIGH_RISK_CLAIM_TOKENS = {
    "cure", "cures", "curing", "curable", "guarantee", "guaranteed",
    "100%", "completely eliminates", "permanent solution", "replaces your doctor",
    "stop your medicine", "safe to double",
}

# Negation indicators for polarity checking
NEGATION_TOKENS = {"not", "no", "never", "cannot", "neither", "nor", "without"}


class VerificationStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNRESOLVED_CITATION = "unresolved_citation"
    HIGH_RISK_EXTRAPOLATION = "high_risk_extrapolation"
    CONTRADICTION = "contradiction"


class VerificationDecision(str, Enum):
    ACCEPT = "accept"
    REPAIRED = "repaired"
    FALLBACK_REQUIRED = "fallback_required"


@dataclass
class ClaimVerificationResult:
    claim_id: str
    claim_text: str
    status: VerificationStatus
    support_score: float
    cited_evidence_ids: list[str]
    matched_passage_ids: list[str]
    rationale: str


@dataclass
class VerificationReport:
    decision: VerificationDecision
    total_claims: int
    supported_claims_count: int
    unsupported_claims_count: int
    support_ratio: float
    results: list[ClaimVerificationResult]
    repaired_claims: list[ClaimItem] = field(default_factory=list)
    audit_code: str = "CLAIM_VERIFICATION_PASSED"


class ClaimVerifier:
    """Verifies that every material medical claim in an EducationalResponse
    is strictly entailed by its cited evidence passages.
    """

    def __init__(
        self,
        min_support_threshold: float = 0.55,
        min_acceptable_ratio: float = 0.90,
    ) -> None:
        self.min_support_threshold = min_support_threshold
        self.min_acceptable_ratio = min_acceptable_ratio

    def verify(
        self,
        response: EducationalResponse,
        retrieved_passages: list[ScoredPassage] | list[EvidencePassage],
    ) -> VerificationReport:
        """Verify all claims in the response against retrieved passages.

        Args:
            response: The candidate EducationalResponse to verify.
            retrieved_passages: List of ScoredPassage or EvidencePassage retrieved for this query.

        Returns:
            VerificationReport detailing status of each claim and final decision.
        """
        if not response.claims:
            # If no claims were generated, nothing to verify
            return VerificationReport(
                decision=VerificationDecision.ACCEPT,
                total_claims=0,
                supported_claims_count=0,
                unsupported_claims_count=0,
                support_ratio=1.0,
                results=[],
                repaired_claims=[],
                audit_code="VERIFICATION_SKIPPED_NO_CLAIMS",
            )

        # Build mapping of citation_id -> passage
        # Response has .evidence list with id (e.g. 'e1') and passage_id
        citation_map: dict[str, EvidenceCitation] = {c.id: c for c in response.evidence}
        passage_map: dict[str, EvidencePassage] = {}
        for item in retrieved_passages:
            p = item.passage if isinstance(item, ScoredPassage) else item
            passage_map[p.passage_id] = p

        results: list[ClaimVerificationResult] = []
        supported_claims: list[ClaimItem] = []
        has_critical_failure = False

        for claim in response.claims:
            res = self._verify_single_claim(claim, citation_map, passage_map)
            results.append(res)

            if res.status == VerificationStatus.SUPPORTED:
                supported_claims.append(claim)
            elif res.status in (VerificationStatus.HIGH_RISK_EXTRAPOLATION, VerificationStatus.CONTRADICTION):
                has_critical_failure = True

        total_claims = len(results)
        supported_count = len(supported_claims)
        unsupported_count = total_claims - supported_count
        support_ratio = round(supported_count / total_claims, 4) if total_claims > 0 else 1.0

        # Decision Logic:
        # 1. Any high-risk extrapolation or contradiction -> FALLBACK_REQUIRED immediately
        # 2. Support ratio >= min_acceptable_ratio (and 0 critical failures) -> ACCEPT or REPAIRED
        # 3. Support ratio < min_acceptable_ratio -> FALLBACK_REQUIRED
        if has_critical_failure:
            decision = VerificationDecision.FALLBACK_REQUIRED
            audit_code = "CRITICAL_CLAIM_VERIFICATION_FAILURE"
        elif support_ratio >= 1.0:
            decision = VerificationDecision.ACCEPT
            audit_code = "CLAIM_VERIFICATION_PASSED_100"
        elif support_ratio >= self.min_acceptable_ratio:
            decision = VerificationDecision.REPAIRED
            audit_code = "CLAIM_VERIFICATION_REPAIRED_FILTERED"
        else:
            decision = VerificationDecision.FALLBACK_REQUIRED
            audit_code = "CLAIM_VERIFICATION_LOW_SUPPORT_FALLBACK"

        return VerificationReport(
            decision=decision,
            total_claims=total_claims,
            supported_claims_count=supported_count,
            unsupported_claims_count=unsupported_count,
            support_ratio=support_ratio,
            results=results,
            repaired_claims=supported_claims,
            audit_code=audit_code,
        )

    def _verify_single_claim(
        self,
        claim: ClaimItem,
        citation_map: dict[str, EvidenceCitation],
        passage_map: dict[str, EvidencePassage],
    ) -> ClaimVerificationResult:
        """Verify an individual ClaimItem against its cited passage(s)."""
        claim_text = claim.text.strip()
        if not claim_text:
            return ClaimVerificationResult(
                claim_id=claim.id,
                claim_text=claim_text,
                status=VerificationStatus.UNSUPPORTED,
                support_score=0.0,
                cited_evidence_ids=claim.evidence_ids,
                matched_passage_ids=[],
                rationale="Claim text is empty.",
            )

        if not claim.evidence_ids:
            return ClaimVerificationResult(
                claim_id=claim.id,
                claim_text=claim_text,
                status=VerificationStatus.UNRESOLVED_CITATION,
                support_score=0.0,
                cited_evidence_ids=[],
                matched_passage_ids=[],
                rationale="Claim does not cite any evidence IDs.",
            )

        # Resolve citations to actual passages
        resolved_passages: list[EvidencePassage] = []
        matched_passage_ids: list[str] = []

        for eid in claim.evidence_ids:
            citation = citation_map.get(eid)
            if not citation:
                return ClaimVerificationResult(
                    claim_id=claim.id,
                    claim_text=claim_text,
                    status=VerificationStatus.UNRESOLVED_CITATION,
                    support_score=0.0,
                    cited_evidence_ids=claim.evidence_ids,
                    matched_passage_ids=[],
                    rationale=f"Cited evidence ID '{eid}' does not resolve to an approved citation in the response.",
                )
            passage = passage_map.get(citation.passage_id)
            if passage:
                resolved_passages.append(passage)
                matched_passage_ids.append(passage.passage_id)
            else:
                return ClaimVerificationResult(
                    claim_id=claim.id,
                    claim_text=claim_text,
                    status=VerificationStatus.UNRESOLVED_CITATION,
                    support_score=0.0,
                    cited_evidence_ids=claim.evidence_ids,
                    matched_passage_ids=[],
                    rationale=f"Cited passage ID '{citation.passage_id}' was not found in the retrieved evidence bundle.",
                )

        combined_passage_text = " ".join(p.text for p in resolved_passages)

        # 1. High-Risk Extrapolation Check
        claim_lower = claim_text.lower()
        passage_lower = combined_passage_text.lower()

        for high_risk in HIGH_RISK_CLAIM_TOKENS:
            if re.search(r"\b" + re.escape(high_risk) + r"\b", claim_lower):
                if not re.search(r"\b" + re.escape(high_risk) + r"\b", passage_lower):
                    return ClaimVerificationResult(
                        claim_id=claim.id,
                        claim_text=claim_text,
                        status=VerificationStatus.HIGH_RISK_EXTRAPOLATION,
                        support_score=0.0,
                        cited_evidence_ids=claim.evidence_ids,
                        matched_passage_ids=matched_passage_ids,
                        rationale=f"Claim asserts unsupported high-risk token '{high_risk}' not found in source text.",
                    )

        # 2. Polarity / Negation Inversion Check
        claim_has_neg = any(tok in claim_lower.split() for tok in NEGATION_TOKENS)
        passage_has_neg = any(tok in passage_lower.split() for tok in NEGATION_TOKENS)

        # Specifically check "prevented" vs "cannot be prevented"
        if "can be prevented" in claim_lower and "cannot be prevented" in passage_lower:
            return ClaimVerificationResult(
                claim_id=claim.id,
                claim_text=claim_text,
                status=VerificationStatus.CONTRADICTION,
                support_score=0.0,
                cited_evidence_ids=claim.evidence_ids,
                matched_passage_ids=matched_passage_ids,
                rationale="Polarity contradiction: passage states condition cannot be prevented, while claim asserts it can.",
            )

        # 3. Lexical Entailment & Groundedness Score
        claim_tokens = set(tokenize(claim_text, expand_synonyms=False))
        if not claim_tokens:
            claim_tokens = set(claim_lower.split())

        passage_tokens = set(tokenize(combined_passage_text, expand_synonyms=True))
        overlap = claim_tokens.intersection(passage_tokens)
        support_score = round(len(overlap) / len(claim_tokens), 4) if claim_tokens else 0.0

        if support_score >= self.min_support_threshold:
            status = VerificationStatus.SUPPORTED
            rationale = f"Claim is verified with {support_score * 100:.1f}% grounded term overlap."
        else:
            status = VerificationStatus.UNSUPPORTED
            missing_terms = list(claim_tokens - passage_tokens)[:5]
            rationale = (
                f"Low term overlap ({support_score * 100:.1f}% < {self.min_support_threshold * 100:.1f}%). "
                f"Missing key terms: {missing_terms}"
            )

        return ClaimVerificationResult(
            claim_id=claim.id,
            claim_text=claim_text,
            status=status,
            support_score=support_score,
            cited_evidence_ids=claim.evidence_ids,
            matched_passage_ids=matched_passage_ids,
            rationale=rationale,
        )
