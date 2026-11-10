import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from app.workflow.service import HealthApplication
from health_tools.conversation import conversational_reply
from health_tools.workflow import Orchestrator, SafetyDecision


class ConversationTests(unittest.TestCase):
    def test_social_and_context_only_turns(self):
        for query in ("hello", "Hi!", "thank you", "I am 21 years old",
                      "my name is jay and i am 21 years old", "Hi, my name is Jay. I am 21 years old."):
            with self.subTest(query=query):
                self.assertIsNotNone(conversational_reply(query))

    def test_health_content_is_never_swallowed_by_name_or_greeting(self):
        for query in ("Hi, what are PCOS symptoms?", "my name is Jay and I have irregular periods",
                      "I am 21 years old and have severe pelvic pain", "I am not pregnant",
                      "hello can you calculate my cycle?", "my name is Jay. What is PCOS?",
                      "my name is Jay PCOS", "call me a doctor"):
            with self.subTest(query=query):
                self.assertIsNone(conversational_reply(query))

    def test_exact_reported_introduction_updates_age_without_retrieval(self):
        retrieval = Mock()
        app = HealthApplication(retrieve=retrieval)
        result, session = app.process("my name is jay and i am 21 years old", allow_session_context=True)
        self.assertIn("introducing yourself", result.response["answer"])
        self.assertEqual(session.context.age, 21)
        self.assertEqual(session.context.is_adult, "yes")
        self.assertEqual(result.response["evidence"], [])
        self.assertEqual(result.response["claims"], [])
        self.assertEqual(session.context.clarification_turns_used, 0)
        self.assertNotIn("jay", session.model_dump_json())
        retrieval.assert_not_called()

    def test_introduction_with_question_still_answers_question(self):
        result, _ = HealthApplication(allow_unverified_for_development=True).process("My name is Jay and I am 21 years old. What are PCOS symptoms?")
        self.assertTrue(result.response["symptoms"])
        self.assertTrue(result.response["evidence"])

    def test_safety_and_minor_scope_preempt_acknowledgement(self):
        app = HealthApplication(retrieve=Mock())
        urgent, _ = app.process("Hi, my name is Jay and I have severe pelvic pain and fainted.")
        self.assertEqual(urgent.response["response_type"], "urgent_guidance")
        minor, _ = app.process("my name is Jay and I am 15 years old")
        self.assertEqual(minor.response["response_type"], "out_of_scope")
        app._retrieve_callback.assert_not_called()

    def test_opt_out_does_not_retain_age(self):
        result, session = HealthApplication(allow_unverified_for_development=True).process("my name is jay and i am 21 years old", allow_session_context=False)
        self.assertIn("introducing yourself", result.response["answer"])
        self.assertIsNone(session.context.age)

    def test_greeting_does_not_lose_pending_dates_or_treat_age_as_reference_date(self):
        app = HealthApplication(allow_unverified_for_development=True)
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        _, session = app.process("Calculate cycle intervals", allow_session_context=True, now=now)
        _, session = app.process("2026-08-01, 2026-09-05; as of 2026-11-07", session_id=session.session_id, now=now)
        before = app.pending_tasks.get(session.session_id, now=now)
        result, session = app.process("my name is jay and i am 21 years old", session_id=session.session_id, now=now)
        self.assertIn("TASK_CONVERSATION_ACKNOWLEDGED", result.events)
        self.assertEqual(app.pending_tasks.get(session.session_id, now=now), before)
        result, _ = app.process("confirm", session_id=session.session_id, now=now)
        self.assertIn("35 days", result.response["answer"])

    def test_standalone_orchestrator_does_not_retrieve_for_greetings(self):
        retrieve = Mock()
        workflow = Orchestrator(safety_check=lambda *args: SafetyDecision("proceed"), retrieve=retrieve)
        self.assertIn("CONVERSATION_ACKNOWLEDGED", workflow.run("hello").events)
        retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
