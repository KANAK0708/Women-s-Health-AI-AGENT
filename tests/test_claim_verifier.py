"""Unit and integration tests for the Claim-to-Passage Entailment Verification subsystem.

Verifies:
1. Factual grounding: claims with high term overlap against cited passages pass with status=SUPPORTED.
2. Citation integrity: unresolvable evidence IDs (e.g. 'e99') or unindexed passages are flagged.
3. High-risk claim detection: claims asserting 'cure', 'guaranteed', or '100%' without source support trigger FALLBACK_REQUIRED.
4. Polarity checking: claims asserting a condition 'can be prevented' when source states 'cannot be prevented' are rejected.
5. Tolerance & repair: minor low-overlap claims are filtered out when the majority are valid.
6. End-to-end workflow verifies that process_health_query attaches verification audit codes.
"""

import unittest
from datetime import date

from app.schemas.evidence import (
    ClaimItem,
    EducationalCategory,
    EducationalResponse,
    EvidenceCitation,
    EvidencePassage,
)
from app.verification.verifier import (
    ClaimVerifier,
    VerificationDecision,
    VerificationStatus,
)
from main import process_health_query


class TestClaimVerifier(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = ClaimVerifier(min_support_threshold=0.50, min_acceptable_ratio=0.80)
        self.sample_passage = EvidencePassage(
            passage_id="psg-test-pcos-01",
            source_id="src-test-who",
            title="PCOS Overview and Guidelines",
            url="https://example.org/pcos-overview",
            locator="Section 1",
            category=EducationalCategory.DEFINITION,
            topic_tags=["pcos", "definition"],
            text=(
                "Polycystic ovary syndrome (PCOS) is a hormonal condition affecting women "
                "of reproductive age. While the genetic basis cannot be prevented, lifestyle "
                "management with aerobic exercise and balanced nutrition reduces metabolic risk."
            ),
            reviewed_at=date(2026, 11, 1),
        )
        self.sample_citation = EvidenceCitation(
            id="e1",
            source_id="src-test-who",
            passage_id="psg-test-pcos-01",
            title="PCOS Overview and Guidelines",
            url="https://example.org/pcos-overview",
            locator="Section 1",
            reviewed_at="2026-11-01",
        )

    def test_supported_claim_passes(self) -> None:
        response = EducationalResponse(
            request_id="req-test-1",
            topic="PCOS",
            answer="PCOS is a hormonal condition affecting women of reproductive age.",
            claims=[
                ClaimItem(
                    id="c1",
                    text="PCOS is a hormonal condition affecting women of reproductive age.",
                    evidence_ids=["e1"],
                )
            ],
            evidence=[self.sample_citation],
        )
        report = self.verifier.verify(response, [self.sample_passage])
        self.assertEqual(report.decision, VerificationDecision.ACCEPT)
        self.assertEqual(report.supported_claims_count, 1)
        self.assertEqual(report.unsupported_claims_count, 0)
        self.assertEqual(report.support_ratio, 1.0)
        self.assertEqual(report.results[0].status, VerificationStatus.SUPPORTED)

    def test_unresolved_citation_id_fails(self) -> None:
        response = EducationalResponse(
            request_id="req-test-2",
            topic="PCOS",
            answer="Sample answer.",
            claims=[
                ClaimItem(
                    id="c1",
                    text="PCOS is a hormonal condition affecting women.",
                    evidence_ids=["e99"],  # Does not exist in response.evidence
                )
            ],
            evidence=[self.sample_citation],
        )
        report = self.verifier.verify(response, [self.sample_passage])
        self.assertEqual(report.results[0].status, VerificationStatus.UNRESOLVED_CITATION)
        self.assertIn("does not resolve", report.results[0].rationale)

    def test_high_risk_extrapolation_triggers_fallback(self) -> None:
        response = EducationalResponse(
            request_id="req-test-3",
            topic="PCOS",
            answer="This tea provides a guaranteed 100% cure for PCOS.",
            claims=[
                ClaimItem(
                    id="c1",
                    text="This treatment provides a guaranteed cure for all PCOS symptoms.",
                    evidence_ids=["e1"],
                )
            ],
            evidence=[self.sample_citation],
        )
        report = self.verifier.verify(response, [self.sample_passage])
        self.assertEqual(report.decision, VerificationDecision.FALLBACK_REQUIRED)
        self.assertEqual(report.results[0].status, VerificationStatus.HIGH_RISK_EXTRAPOLATION)
        self.assertTrue(
            "cure" in report.results[0].rationale or "guaranteed" in report.results[0].rationale
        )

    def test_polarity_contradiction_detected(self) -> None:
        response = EducationalResponse(
            request_id="req-test-4",
            topic="PCOS",
            answer="The genetic basis of PCOS can be prevented easily.",
            claims=[
                ClaimItem(
                    id="c1",
                    text="The genetic basis of PCOS can be prevented with early action.",
                    evidence_ids=["e1"],
                )
            ],
            evidence=[self.sample_citation],
        )
        report = self.verifier.verify(response, [self.sample_passage])
        self.assertEqual(report.decision, VerificationDecision.FALLBACK_REQUIRED)
        self.assertEqual(report.results[0].status, VerificationStatus.CONTRADICTION)

    def test_repaired_claim_filters_minor_unsupported_item(self) -> None:
        # 4 supported claims and 1 unsupported general claim (ratio = 4/5 = 0.80 >= 0.80 threshold)
        response = EducationalResponse(
            request_id="req-test-5",
            topic="PCOS",
            answer="PCOS overview.",
            claims=[
                ClaimItem(
                    id="c1",
                    text="PCOS is a hormonal condition affecting women of reproductive age.",
                    evidence_ids=["e1"],
                ),
                ClaimItem(
                    id="c2",
                    text="Aerobic exercise and balanced nutrition reduce metabolic risk.",
                    evidence_ids=["e1"],
                ),
                ClaimItem(
                    id="c3",
                    text="Lifestyle management with aerobic exercise reduces metabolic risk.",
                    evidence_ids=["e1"],
                ),
                ClaimItem(
                    id="c4",
                    text="Polycystic ovary syndrome affects women of reproductive age.",
                    evidence_ids=["e1"],
                ),
                ClaimItem(
                    id="c5",
                    text="Some completely unmentioned irrelevant widget artifact.",
                    evidence_ids=["e1"],
                ),
            ],
            evidence=[self.sample_citation],
        )
        report = self.verifier.verify(response, [self.sample_passage])
        self.assertEqual(report.decision, VerificationDecision.REPAIRED)
        self.assertEqual(len(report.repaired_claims), 4)
        self.assertNotIn("c5", [c.id for c in report.repaired_claims])

    def test_workflow_integrates_claim_verification(self) -> None:
        from unittest.mock import patch
        from app.retrieval.engine import HybridRetrievalEngine
        import main

        # Exercise verifier wiring only with explicitly marked development evidence.
        development_engine = HybridRetrievalEngine(allow_unverified_for_development=True)
        with patch.object(main, "retrieval_engine", development_engine):
            response, session = process_health_query(
                "What is PCOS and what are its symptoms?",
                enable_llm_generation=False,
            )
        self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)
        self.assertGreaterEqual(len(response.claims), 1)
        for claim in response.claims:
            self.assertTrue(len(claim.evidence_ids) > 0)


if __name__ == "__main__":
    unittest.main()
