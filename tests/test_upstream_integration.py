"""Run when the teammate's app is importable; no model or network calls."""

import importlib.util
import unittest
from datetime import datetime, timedelta, timezone

from health_tools.handoff import adapt_session
from health_tools.workflow import SafetyDecision


@unittest.skipUnless(importlib.util.find_spec("app"), "Teammate app not present on this branch")
class UpstreamIntegrationTests(unittest.TestCase):
    def setUp(self):
        from app.schemas.evidence import EducationalResponse
        from health_tools.integration import create_upstream_orchestrator
        self.response_model = EducationalResponse
        # Software compatibility fixture only, not a medical policy.
        self.workflow = create_upstream_orchestrator(
            safety_check=lambda query, context: SafetyDecision("proceed")
        )

    def test_real_session_model(self):
        from app.schemas.memory import SessionMemory
        now = datetime.now(timezone.utc)
        session = SessionMemory(session_id="synthetic-integration", created_at=now,
                                expires_at=now + timedelta(minutes=10))
        context = adapt_session(session, now=now)
        self.assertEqual(context.pregnancy_status, "not_provided")
        self.assertTrue(context.context_available)

    def test_real_retrieval_bundle_and_output_model(self):
        result = self.workflow.run("What is PCOS and what are its symptoms?")
        self.assertEqual(result.events[-1], "EVIDENCE_COMPLETE", result.response)
        parsed = self.response_model.model_validate(result.response)
        self.assertTrue(parsed.claims)
        self.assertTrue(parsed.evidence)
        for claim in parsed.claims:
            self.assertIn(claim.text, parsed.answer)

    def test_cycle_output_matches_upstream_model(self):
        result = self.workflow.run("Calculate cycle intervals", period_start_dates=[
            "2026-08-01", "2026-09-05"], as_of="2026-11-06")
        parsed = self.response_model.model_validate(result.response)
        self.assertIn("35 days", parsed.answer)


if __name__ == "__main__":
    unittest.main()
