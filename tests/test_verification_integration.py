import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.verification.verifier import VerificationDecision
from app.workflow.service import HealthApplication


class VerificationIntegrationTests(unittest.TestCase):
    def run_with_report(self, decision, **counts):
        report = SimpleNamespace(decision=decision, total_claims=counts.get("total", 0),
                                 supported_claims_count=counts.get("supported", 0),
                                 unsupported_claims_count=counts.get("unsupported", 0))
        verifier = Mock()
        verifier.verify.return_value = report
        app = HealthApplication(claim_verifier=verifier, allow_unverified_for_development=True)
        result, session = app.process("What is PCOS?", allow_session_context=False)
        verifier.verify.assert_called_once()
        return result, session

    def assert_no_unverified_text(self, result):
        self.assertEqual(result.response["response_type"], "abstention")
        self.assertEqual(result.response["claims"], [])
        self.assertEqual(result.response["evidence"], [])
        self.assertEqual(result.response["what_it_is"], "")
        self.assertEqual(result.response["symptoms"], [])
        self.assertEqual(result.response["prevention_and_lifestyle"], [])
        self.assertNotIn("Retrieved evidence excerpts", result.response["answer"])

    def test_repaired_claim_list_does_not_leave_unverified_display_text(self):
        result, session = self.run_with_report(VerificationDecision.REPAIRED)
        self.assert_no_unverified_text(result)
        self.assertIn("CLAIM_VERIFICATION_FALLBACK", session.audit_codes)

    def test_rejected_answer_is_not_displayed(self):
        result, _ = self.run_with_report(VerificationDecision.FALLBACK_REQUIRED)
        self.assert_no_unverified_text(result)

    def test_accept_with_missing_claim_coverage_is_rejected(self):
        result, _ = self.run_with_report(VerificationDecision.ACCEPT)
        self.assert_no_unverified_text(result)

    def test_verifier_exception_fails_closed_without_exception_text(self):
        verifier = Mock()
        verifier.verify.side_effect = RuntimeError("sensitive-payload")
        result, session = HealthApplication(claim_verifier=verifier, allow_unverified_for_development=True).process("What is PCOS?")
        self.assert_no_unverified_text(result)
        self.assertIn("CLAIM_VERIFICATION_UNAVAILABLE", session.audit_codes)
        self.assertNotIn("sensitive-payload", str(result))

    def test_real_verifier_accepts_exact_excerpts(self):
        result, session = HealthApplication(allow_unverified_for_development=True).process("What is PCOS?")
        self.assertEqual(result.response["response_type"], "education")
        self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)

    def test_urgent_and_calculation_routes_do_not_depend_on_claim_verifier(self):
        verifier = Mock()
        app = HealthApplication(claim_verifier=verifier, allow_unverified_for_development=True)
        urgent, _ = app.process("I have severe pelvic pain and fainted.")
        self.assertEqual(urgent.response["response_type"], "urgent_guidance")
        cycle, _ = app.process("Calculate cycle intervals", period_start_dates=["2026-08-01", "2026-09-05"], as_of="2026-11-06")
        self.assertEqual(cycle.response["response_type"], "education")
        verifier.verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
