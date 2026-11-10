import unittest
from unittest.mock import Mock

from app.workflow.service import HealthApplication
from health_tools.answer_selection import question_focus
from health_tools.workflow import Orchestrator, SafetyDecision


class TopicClarificationTests(unittest.TestCase):
    def test_exact_reported_message_asks_for_topic_without_retrieval(self):
        retrieve = Mock()
        app = HealthApplication(retrieve=retrieve)
        _, session = app.process("my name is jay and i am 21 years old", allow_session_context=True)
        result, session = app.process("explain me everything sbout them", session_id=session.session_id)
        self.assertEqual(result.response["response_type"], "clarification")
        self.assertIn("Which topic", result.response["answer"])
        self.assertEqual(session.context.age, 21)
        self.assertEqual(result.response["evidence"], [])
        retrieve.assert_not_called()

    def test_plural_reference_is_not_guessed_from_one_active_topic(self):
        self.assertTrue(question_focus("explain everything about them", active_topic="PCOS").needs_topic)

    def test_singular_reference_uses_only_available_topic(self):
        known = question_focus("explain everything about it", active_topic="PCOS")
        self.assertFalse(known.needs_topic)
        self.assertIn("PCOS", known.retrieval_query)
        self.assertEqual(known.facets, ("definition", "symptoms", "lifestyle"))
        self.assertTrue(question_focus("explain everything about it").needs_topic)
        self.assertEqual(question_focus("How do I repair it?", active_topic="PCOS").retrieval_query, "How do I repair it?")
        self.assertEqual(question_focus("What is the weather in this city?", active_topic="PCOS").retrieval_query, "What is the weather in this city?")

    def test_broad_explicit_request_and_topic_choice_produce_overview(self):
        for query in ("explain me everything about PCOS", "PCOS", "explain PCOS"):
            with self.subTest(query=query):
                result, session = HealthApplication(allow_unverified_for_development=True).process(query)
                self.assertEqual(result.response["response_type"], "education")
                self.assertTrue(result.response["what_it_is"])
                self.assertTrue(result.response["symptoms"])
                self.assertTrue(result.response["prevention_and_lifestyle"])
                self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)

    def test_narrow_everything_request_stays_narrow(self):
        self.assertEqual(question_focus("explain everything about PCOS symptoms").facets, ("symptoms",))

    def test_clarification_then_topic_choice(self):
        app = HealthApplication(allow_unverified_for_development=True)
        _, session = app.process("my name is jay and i am 21 years old", allow_session_context=True)
        result, session = app.process("explain me everything sbout them", session_id=session.session_id)
        self.assertEqual(result.response["response_type"], "clarification")
        result, _ = app.process("PCOS", session_id=session.session_id)
        self.assertEqual(result.response["response_type"], "education")
        self.assertTrue(result.response["symptoms"])
        self.assertTrue(result.response["prevention_and_lifestyle"])

    def test_cycle_calculations_choice_enters_task_flow(self):
        result, _ = HealthApplication(allow_unverified_for_development=True).process("cycle calculations", allow_session_context=True)
        self.assertIn("TASK_DATES_REQUESTED", result.events)

    def test_missing_topic_and_safety_failure_never_retrieve(self):
        retrieve = Mock()
        workflow = Orchestrator(retrieve=retrieve, safety_check=lambda *a: SafetyDecision("proceed"))
        self.assertEqual(workflow.run("explain everything").response["response_type"], "clarification")
        app = HealthApplication(retrieve=retrieve)
        result, _ = app.process("explain them, I have severe pelvic pain and fainted")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
