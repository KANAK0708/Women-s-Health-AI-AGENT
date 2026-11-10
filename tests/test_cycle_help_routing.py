import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from app.workflow.service import HealthApplication
from health_tools.workflow import Orchestrator, SafetyDecision, select_intent


class CycleHelpRoutingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        self.app = HealthApplication(allow_unverified_for_development=True)
        self.sid = None

    def send(self, message, **kwargs):
        result, session = self.app.process(message, session_id=self.sid,
                                           allow_session_context=True, now=self.now, **kwargs)
        self.sid = session.session_id
        return result

    def test_reported_question_explains_both_parts_without_starting_task(self):
        self.send("hi")
        with patch("health_tools.workflow.analyze_cycle_history") as calculate:
            result = self.send("what are pcos and how does cycle calculation works?")
        self.assertTrue(result.response["what_it_is"])
        self.assertTrue(result.response["evidence"])
        self.assertIn("How cycle calculation works", result.response["answer"])
        self.assertIn("35 days", result.response["answer"])
        self.assertNotIn("TASK_DATES_REQUESTED", result.events)
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))
        calculate.assert_not_called()

    def test_reverse_order_preserves_symptoms_question(self):
        result = self.send("How does cycle calculation work and what are PCOS symptoms?")
        self.assertTrue(result.response["symptoms"])
        self.assertIn("How cycle calculation works", result.response["answer"])

    def test_calculator_explanation_needs_no_medical_retrieval_or_calculation(self):
        retrieve = Mock()
        workflow = Orchestrator(safety_check=lambda *a: SafetyDecision("proceed"), retrieve=retrieve)
        result = workflow.run("How do I calculate my cycle?")
        self.assertIn("CYCLE_EXPLAINED", result.events)
        self.assertEqual(result.tool_results, ())
        retrieve.assert_not_called()

    def test_direct_calculation_request_still_collects_inputs(self):
        for query in ("Calculate my cycle", "Can you calculate my cycle?", "Explain PCOS and calculate my cycle"):
            self.assertEqual(select_intent(query), "cycle_history")
        result = self.send("Can you calculate my cycle?")
        self.assertIn("TASK_DATES_REQUESTED", result.events)

    def test_invalid_non_iso_dates_keep_active_task_in_correction_flow(self):
        self.send("Calculate cycle intervals")
        for text in ("03-09-2026 and 29-20-2026", "28-09-2026"):
            result = self.send(text)
            self.assertIn("TASK_INPUT_AMBIGUOUS", result.events)
            self.assertIn("YYYY-MM-DD", result.response["answer"])
            self.assertEqual(result.response["evidence"], [])
            self.assertIsNotNone(self.app.pending_tasks.get(self.sid, now=self.now))

    def test_date_without_task_or_after_expiry_never_reaches_retrieval(self):
        retrieve = Mock()
        self.app = HealthApplication(retrieve=retrieve)
        result = self.send("28-09-2026")
        self.assertIn("NO_PENDING_TASK", result.events)
        self.send("Calculate cycle intervals")
        self.now += timedelta(minutes=5)
        result = self.send("28-09-2026")
        self.assertIn("NO_PENDING_TASK", result.events)
        self.assertIn("may have expired", result.response["answer"])
        retrieve.assert_not_called()

    def test_corrected_dates_still_require_confirmation(self):
        self.send("Calculate cycle intervals")
        self.send("03-09-2026 and 29-20-2026")
        proposed = self.send("2026-09-03, 2026-09-28; as of 2026-11-10")
        self.assertIn("TASK_CONFIRMATION_REQUESTED", proposed.events)
        result = self.send("confirm")
        self.assertIn("Recorded intervals: 25 days.", result.response["answer"])

    def test_urgent_symptoms_preempt_help_request(self):
        result = self.send("How does cycle calculation work? I have severe pelvic pain and fainted.")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertNotIn("How cycle calculation works", result.response["answer"])

    def test_missing_approved_pcos_evidence_does_not_hide_software_help(self):
        self.app = HealthApplication(allow_unverified_for_development=False)
        result = self.send("what are pcos and how does cycle calculation works?")
        self.assertEqual(result.response["response_type"], "abstention")
        self.assertEqual(result.response["evidence"], [])
        self.assertIn("How cycle calculation works", result.response["answer"])


if __name__ == "__main__":
    unittest.main()
