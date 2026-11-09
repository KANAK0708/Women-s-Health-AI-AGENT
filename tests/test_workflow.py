import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from health_tools.contracts import EvidenceSource, ToolError, ToolResult
from health_tools.workflow import Orchestrator, SafetyDecision, ToolPolicy, render_response


def fixture_bundle():
    passage = dict(passage_id="p1", source_id="s1", title="Synthetic source",
                   url="https://example.org", locator="Section 1", reviewed_at="2026-11-06",
                   category="what_it_is", text="Synthetic evidence text.")
    citation = {key: value for key, value in passage.items() if key not in {"text", "category"}}
    citation["id"] = "e1"
    return SimpleNamespace(manifest_version="fixture-v1", citations=[citation],
                           scored_passages=[SimpleNamespace(passage=passage)])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.safety = Mock(return_value=SafetyDecision("proceed"))
        self.retrieve = Mock(return_value=fixture_bundle())
        self.research = Mock(return_value=ToolResult(
            tool="search_pubmed", status="ok",
            sources=(EvidenceSource("pubmed:1", "Synthetic paper", "https://pubmed.ncbi.nlm.nih.gov/1/",
                                    "PubMed", "2026-11-06T00:00:00Z", "Do not promote this abstract to advice."),),
            limitations=("Research only.",),
        ))
        self.workflow = Orchestrator(safety_check=self.safety, retrieve=self.retrieve,
                                     pubmed_search=self.research)

    def test_education_uses_exact_evidence_without_inventing_other_sections(self):
        result = self.workflow.run("What is PCOS?")
        self.assertEqual(result.response["response_type"], "education")
        self.assertEqual(result.response["claims"][0]["text"], "Synthetic evidence text.")
        self.assertEqual(result.response["symptoms"], [])
        self.assertEqual(result.response["prevention_and_lifestyle"], [])
        self.assertIn("Synthetic evidence text.", render_response(result))
        self.safety.assert_called_once()
        self.research.assert_not_called()

    def test_safety_runs_before_tools_and_stops_all_routes(self):
        self.safety.return_value = SafetyDecision("urgent", "Reviewed urgent message.", "test-protocol")
        for query in ("What is PCOS?", "Find research", "Calculate cycle dates"):
            result = self.workflow.run(query)
            self.assertEqual(result.response["response_type"], "urgent_guidance")
            self.assertEqual(result.response["protocol_id"], "test-protocol")
        self.retrieve.assert_not_called()
        self.research.assert_not_called()

    def test_failed_or_invalid_safety_result_stops(self):
        for bad in (RuntimeError("private health details"), None):
            if isinstance(bad, Exception):
                self.safety.side_effect = bad
            else:
                self.safety.side_effect = None
                self.safety.return_value = bad
            result = self.workflow.run("What is PCOS?")
            self.assertEqual(result.events[-1], "SAFETY_UNAVAILABLE")
            self.assertNotIn("private health details", str(result))
        self.retrieve.assert_not_called()

    def test_cycle_route(self):
        result = self.workflow.run("Calculate my cycle intervals", period_start_dates=[
            "2026-08-01", "2026-09-05", "2026-10-08"], as_of="2026-11-06")
        self.assertIn("35, 33 days", result.response["answer"])
        self.assertEqual(result.response["evidence"], [])
        self.assertEqual(result.tool_results[0].tool, "analyze_cycle_history")
        self.retrieve.assert_not_called()

    def test_cycle_never_extracts_dates_from_raw_text(self):
        result = self.workflow.run("Calculate cycle dates 2026-08-01 and 2026-09-05")
        self.assertTrue(result.clarification_requested)
        self.assertEqual(result.tool_results, ())

    def test_cycle_requires_reference_date(self):
        result = self.workflow.run("Calculate cycle", period_start_dates=["2026-08-01", "2026-09-05"])
        self.assertEqual(result.response["response_type"], "clarification")
        self.assertIn("local date", result.response["answer"])

    def test_invalid_dates_request_correction(self):
        result = self.workflow.run("Calculate cycle", period_start_dates=["bad"], as_of="2026-11-06")
        self.assertTrue(result.clarification_requested)
        self.assertEqual(result.tool_results[0].status, "error")

    def test_research_requires_consent_and_separate_terms(self):
        for args in ({}, {"allow_external_research": True}, {"research_query": "PCOS"}):
            result = self.workflow.run("Find research about my private history", **args)
            self.assertEqual(result.response["response_type"], "clarification")
        self.research.assert_not_called()

    def test_research_uses_only_reviewed_query_and_does_not_make_clinical_claims(self):
        result = self.workflow.run("Find research about private history", allow_external_research=True,
                                   research_query="PCOS systematic review")
        self.research.assert_called_once_with("PCOS systematic review", max_results=3, timeout=10)
        self.assertIn("Synthetic paper", result.response["answer"])
        self.assertNotIn("promote this abstract", result.response["answer"])
        self.assertEqual(result.response["claims"], [])
        self.assertEqual(result.response["evidence"], [])
        self.assertEqual(result.tool_results[0].sources[0].source_id, "pubmed:1")

    def test_research_failure_is_not_retried(self):
        self.research.return_value = ToolResult(tool="search_pubmed", status="error",
                                               error=ToolError("timeout", "Unavailable", True))
        result = self.workflow.run("Find research", allow_external_research=True, research_query="PCOS")
        self.assertEqual(result.response["response_type"], "abstention")
        self.assertEqual(self.research.call_count, 1)
        self.retrieve.assert_not_called()

    def test_disabled_tools(self):
        workflow = Orchestrator(safety_check=self.safety, retrieve=self.retrieve,
                                pubmed_search=self.research, policy=ToolPolicy(enabled=frozenset()))
        for query, args in (
            ("What is PCOS?", {}),
            ("Find research", {"allow_external_research": True, "research_query": "PCOS"}),
            ("Calculate cycle", {"period_start_dates": ["2026-08-01", "2026-09-05"], "as_of": "2026-11-06"}),
        ):
            result = workflow.run(query, **args)
            self.assertIn("TOOL_POLICY_BLOCK", result.events)
        self.retrieve.assert_not_called()
        self.research.assert_not_called()

    def test_no_automatic_web_fallback_for_missing_evidence(self):
        self.retrieve.side_effect = RuntimeError("private query")
        result = self.workflow.run("What is PCOS?")
        self.assertEqual(result.response["response_type"], "abstention")
        self.assertNotIn("private query", str(result))
        self.research.assert_not_called()

    def test_mismatched_evidence_and_size_limits_fail_closed(self):
        bundle = fixture_bundle()
        bundle.citations[0]["url"] = "https://wrong.example.org"
        self.retrieve.return_value = bundle
        result = self.workflow.run("What is PCOS?")
        self.assertEqual(result.response["claims"], [])
        self.assertEqual(result.response["evidence"], [])
        workflow = Orchestrator(safety_check=self.safety, retrieve=Mock(return_value=fixture_bundle()),
                                policy=ToolPolicy(max_passage_chars=1))
        self.assertEqual(workflow.run("What is PCOS?").events[-1], "RETRIEVAL_FAILED")

    def test_unknown_category_does_not_leak_partial_answer(self):
        bundle = fixture_bundle()
        bundle.scored_passages[0].passage["category"] = "invented"
        self.retrieve.return_value = bundle
        result = self.workflow.run("What is PCOS?")
        self.assertEqual(result.response["claims"], [])
        self.assertNotIn("Synthetic evidence text.", result.response["answer"])

    def test_invalid_context_still_checks_current_message_for_safety(self):
        result = self.workflow.run("What is PCOS?", session={"allow_session_context": "bad"})
        self.safety.assert_called_once()
        self.assertEqual(result.events[-1], "CONTEXT_INVALID")
        self.retrieve.assert_not_called()

    def test_clarification_budget_and_no_session_mutation(self):
        session = {"allow_session_context": True, "created_at": "2026-11-06T11:00:00+00:00",
                   "expires_at": "2026-11-06T13:00:00+00:00", "context": {"clarification_turns_used": 2}}
        original = copy.deepcopy(session)
        result = self.workflow.run("Calculate cycle", session=session,
                                   now=datetime(2026, 11, 6, 12, tzinfo=timezone.utc))
        self.assertEqual(result.events[-1], "CLARIFICATION_LIMIT")
        self.assertFalse(result.clarification_requested)
        self.assertEqual(session, original)

    def test_policy_validation(self):
        for options in ({"enabled": {"pubmed"}}, {"max_tool_calls": 0},
                        {"max_passages": True}, {"pubmed_timeout_seconds": float("nan")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ToolPolicy(**options)


if __name__ == "__main__":
    unittest.main()
