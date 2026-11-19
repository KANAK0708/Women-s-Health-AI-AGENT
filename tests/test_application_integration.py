import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from app.schemas.evidence import EducationalResponse
from app.schemas.memory import TriState
from app.workflow.service import HealthApplication
from health_tools.contracts import EvidenceSource, ToolResult


ROOT = Path(__file__).resolve().parents[1]


class ApplicationIntegrationTests(unittest.TestCase):
    def test_real_education_retrieval_and_schema(self):
        app = HealthApplication(allow_unverified_for_development=True)
        result, session = app.process("What is PCOS and what are its symptoms?", allow_session_context=True)
        response = EducationalResponse.model_validate(result.response)
        self.assertEqual(response.response_type.value, "education")
        self.assertTrue(response.claims)
        self.assertTrue(response.evidence)
        self.assertIn("RETRIEVAL_SUCCESS", session.audit_codes)
        self.assertEqual(session.context.pregnancy_status, TriState.NOT_PROVIDED)

    def test_urgent_message_preempts_all_tools_even_with_consent_off(self):
        retrieve, research = Mock(), Mock()
        app = HealthApplication(retrieve=retrieve, pubmed_search=research)
        result, session = app.process(
            "I might be pregnant and have severe pelvic pain and fainted.",
            allow_session_context=False,
        )
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertIsNotNone(result.response["protocol_id"])
        self.assertEqual(session.context.severe_symptom_flag, TriState.NOT_PROVIDED)
        self.assertIsNone(app._engine)
        retrieve.assert_not_called()
        research.assert_not_called()

    def test_current_minor_context_applies_without_retention(self):
        retrieve = Mock()
        app = HealthApplication(retrieve=retrieve)
        result, session = app.process("I am 15 years old. What is PCOS?", allow_session_context=False)
        self.assertEqual(result.response["response_type"], "out_of_scope")
        self.assertEqual(session.context.is_adult, TriState.NOT_PROVIDED)
        retrieve.assert_not_called()

    def test_medication_boundary_before_research(self):
        research = Mock()
        app = HealthApplication(pubmed_search=research)
        result, _ = app.process("Research: should I stop taking my prescribed medicine?",
                                allow_external_research=True, research_query="PCOS")
        self.assertEqual(result.response["response_type"], "out_of_scope")
        research.assert_not_called()

    def test_followups_recorded_and_bounded_by_real_memory(self):
        app = HealthApplication(allow_unverified_for_development=True)
        session_id = None
        for expected in ("clarification", "clarification", "abstention"):
            result, session = app.process("What about exercise?", session_id=session_id,
                                          allow_session_context=True)
            session_id = session.session_id
            self.assertEqual(result.response["response_type"], expected)
        self.assertEqual(session.context.clarification_turns_used, 2)
        result, _ = app.process("Calculate cycle intervals", session_id=session_id,
                                period_start_dates=["2026-08-01", "2026-09-05"], as_of="2026-11-06")
        self.assertEqual(result.response["response_type"], "education")

    def test_opt_out_and_deletion(self):
        app = HealthApplication(allow_unverified_for_development=True)
        _, session = app.process("I am 25 years old. What is PCOS?", allow_session_context=True)
        self.assertEqual(session.context.age, 25)
        sid = session.session_id
        _, session = app.process("What is PCOS?", session_id=sid, allow_session_context=False)
        self.assertIsNone(session.context.age)
        self.assertFalse(session.allow_session_context)
        self.assertTrue(app.forget(sid))
        self.assertIsNone(app.store.get_session(sid))

    def test_expired_session_starts_fresh(self):
        app = HealthApplication(allow_unverified_for_development=True)
        now = datetime.now(timezone.utc)
        _, previous = app.process("I am 25 years old. What is PCOS?", now=now,
                                   allow_session_context=True)
        previous_id = previous.session_id
        _, current = app.process("What is PCOS?", session_id=previous_id,
                                 now=now + timedelta(hours=1), allow_session_context=True)
        self.assertNotEqual(current.session_id, previous_id)
        self.assertIsNone(current.context.age)

    def test_research_integrates_without_forwarding_raw_question(self):
        callback = Mock(return_value=ToolResult(
            tool="search_pubmed", status="ok",
            sources=(EvidenceSource("pubmed:1", "Fixture research", "https://pubmed.ncbi.nlm.nih.gov/1/",
                                    "PubMed", "2026-11-06T00:00:00Z", "Fixture abstract"),),
        ))
        app = HealthApplication(pubmed_search=callback)
        result, _ = app.process("Find research; my name is Private Example.",
                                allow_external_research=True, research_query="PCOS review")
        self.assertEqual(result.response["response_type"], "education")
        self.assertIn("Fixture research", result.response["answer"])
        callback.assert_called_once_with("PCOS review", max_results=3, timeout=10)

    def test_missing_research_permission_never_calls_api(self):
        callback = Mock()
        result, _ = HealthApplication(pubmed_search=callback).process("Find PCOS research")
        self.assertEqual(result.response["response_type"], "clarification")
        callback.assert_not_called()

    def test_retrieval_failure_has_no_external_fallback(self):
        callback = Mock()
        app = HealthApplication(retrieve=Mock(side_effect=RuntimeError("private payload")), pubmed_search=callback)
        result, _ = app.process("What is PCOS?")
        self.assertEqual(result.response["response_type"], "abstention")
        self.assertNotIn("private payload", str(result))
        callback.assert_not_called()

    def test_cli_json_education_and_cycle(self):
        for args, expected in (
            (["--query", "What is PCOS?"], "What it is\n"),
            (["--query", "Calculate cycle", "--period-starts", "2026-08-01", "2026-09-05", "--as-of", "2026-11-06"], "35 days"),
            (["--query", "Find PCOS research"], "May I search PubMed"),
        ):
            with self.subTest(args=args):
                run = subprocess.run([sys.executable, "main.py", *args, "--json", "--development-evidence"],
                                     cwd=ROOT, capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stderr)
                data = json.loads(run.stdout)
                EducationalResponse.model_validate(data)
                self.assertIn(expected, data["answer"])

    def test_interactive_forget_and_exit(self):
        run = subprocess.run([sys.executable, "main.py", "--remember", "--development-evidence"], cwd=ROOT,
                             input="What is PCOS?\n/forget\n/quit\n", capture_output=True,
                             text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Session context deleted.", run.stdout)
        self.assertIn("What it is\n", run.stdout)


if __name__ == "__main__":
    unittest.main()
