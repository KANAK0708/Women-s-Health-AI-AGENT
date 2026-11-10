import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.workflow.service import HealthApplication
from health_tools.answer_selection import question_focus
from health_tools.workflow import Orchestrator, SafetyDecision, render_response


def fixture_bundle(facets=("assessment", "definition", "symptoms", "lifestyle", "care")):
    descriptions = {
        "assessment": ("what_it_is", "Diagnostic Criteria in Adults"),
        "definition": ("what_it_is", "Overview and Definition"),
        "symptoms": ("symptoms", "Common Symptoms"),
        "lifestyle": ("prevention_and_lifestyle", "Lifestyle Recommendations"),
        "care": ("when_to_seek_care", "Care Navigation"),
    }
    scored, citations = [], []
    for index, facet in enumerate(facets, 1):
        category, locator = descriptions[facet]
        passage = dict(passage_id=f"p{index}", source_id=f"s{index}", title="Synthetic source",
                       url=f"https://example.org/{facet}", locator=locator,
                       reviewed_at="2026-11-06", category=category, text=f"Exact {facet} fixture text.")
        citation = {key: value for key, value in passage.items() if key not in {"text", "category"}}
        citation["id"] = f"e{index}"
        scored.append(SimpleNamespace(passage=passage))
        citations.append(citation)
    return SimpleNamespace(manifest_version="fixture-v1", scored_passages=scored, citations=citations)


class AnswerSelectionTests(unittest.TestCase):
    def workflow(self, facets=("assessment", "definition", "symptoms", "lifestyle", "care")):
        retrieval = Mock(return_value=fixture_bundle(facets))
        return Orchestrator(safety_check=lambda *a: SafetyDecision("proceed"), retrieve=retrieval), retrieval

    def test_symptoms_only_answer_and_citations(self):
        workflow, retrieval = self.workflow()
        result = workflow.run("What are PCOS symptoms?")
        response = result.response
        self.assertEqual(response["symptoms"], ["Exact symptoms fixture text."])
        self.assertEqual(response["what_it_is"], "")
        self.assertEqual(response["prevention_and_lifestyle"], [])
        self.assertEqual(len(response["claims"]), 1)
        self.assertEqual(response["claims"][0]["evidence_ids"], ["e3"])
        self.assertEqual(response["evidence"][0]["id"], "e3")
        self.assertNotIn("Exact assessment", render_response(result))
        self.assertNotIn("Exact lifestyle", render_response(result))
        self.assertEqual(retrieval.call_args.kwargs["category"], "symptoms")

    def test_definition_does_not_substitute_diagnostic_criteria(self):
        workflow, _ = self.workflow()
        response = workflow.run("What is PCOS?").response
        self.assertEqual(response["what_it_is"], "Exact definition fixture text.")
        self.assertNotIn("assessment fixture", response["answer"])

    def test_explicit_assessment_question(self):
        workflow, _ = self.workflow()
        response = workflow.run("How is PCOS diagnosed?").response
        self.assertEqual(response["what_it_is"], "Exact assessment fixture text.")
        self.assertNotIn("definition fixture", response["answer"])

    def test_mixed_definition_and_symptoms_excludes_other_sections(self):
        workflow, retrieval = self.workflow()
        response = workflow.run("What is PCOS and what are its symptoms?").response
        self.assertEqual(len(response["claims"]), 2)
        self.assertEqual(len(response["evidence"]), 2)
        self.assertEqual(response["prevention_and_lifestyle"], [])
        self.assertNotIn("Exact assessment", response["answer"])
        self.assertNotIn("category", retrieval.call_args.kwargs)

    def test_lifestyle_only(self):
        workflow, _ = self.workflow()
        response = workflow.run("How can I manage PCOS with diet and exercise?").response
        self.assertEqual(response["prevention_and_lifestyle"], ["Exact lifestyle fixture text."])
        self.assertEqual(response["symptoms"], [])

    def test_care_question_does_not_also_select_general_signs(self):
        workflow, _ = self.workflow()
        response = workflow.run("What PCOS warning signs mean I should see a doctor?").response
        self.assertIn("When to seek care", response["answer"])
        self.assertEqual(response["symptoms"], [])

    def test_partial_coverage_is_explicit(self):
        workflow, _ = self.workflow(("symptoms",))
        response = workflow.run("What are PCOS symptoms and lifestyle habits?").response
        self.assertEqual(response["response_type"], "education")
        self.assertEqual(response["prevention_and_lifestyle"], [])
        self.assertIn("Not covered by the retrieved evidence: lifestyle and habits.", response["answer"])
        self.assertEqual(len(response["claims"]), 1)

    def test_no_matching_section_abstains_without_irrelevant_citations(self):
        workflow, _ = self.workflow(("definition",))
        response = workflow.run("What are PCOS symptoms?").response
        self.assertEqual(response["response_type"], "abstention")
        self.assertEqual(response["claims"], [])
        self.assertEqual(response["evidence"], [])
        self.assertNotIn("Exact definition", response["answer"])

    def test_repeated_passages_are_not_dumped(self):
        workflow, _ = self.workflow(("symptoms", "symptoms", "definition"))
        response = workflow.run("What are PCOS symptoms?").response
        self.assertEqual(len(response["claims"]), 1)
        self.assertEqual(response["answer"].count("Exact symptoms fixture text."), 1)

    def test_overview_selects_three_sections_when_requested(self):
        workflow, _ = self.workflow()
        response = workflow.run("Give a general overview of PCOS").response
        self.assertEqual(len(response["claims"]), 3)
        self.assertNotIn("assessment fixture", response["answer"])

    def test_ambiguous_followup_does_not_retrieve_without_topic(self):
        workflow, retrieval = self.workflow()
        result = workflow.run("What about exercise?")
        self.assertEqual(result.response["response_type"], "clarification")
        retrieval.assert_not_called()

    def test_only_elliptical_queries_use_remembered_topic(self):
        focus = question_focus("What about exercise?", active_topic="PCOS (Polycystic Ovary Syndrome)")
        self.assertEqual(focus.facets, ("lifestyle",))
        self.assertIn("PCOS", focus.retrieval_query)
        explicit = question_focus("What are menstrual symptoms?", active_topic="PCOS")
        self.assertEqual(explicit.retrieval_query, "What are menstrual symptoms?")
        unrelated = question_focus("How do I fix a tractor?", active_topic="PCOS")
        self.assertNotIn("PCOS", unrelated.retrieval_query)

    def test_real_followup_uses_consented_topic_and_verifies_answer(self):
        app = HealthApplication(allow_unverified_for_development=True)
        _, session = app.process("What is PCOS?", allow_session_context=True)
        result, session = app.process("What about exercise?", session_id=session.session_id)
        self.assertEqual(result.response["response_type"], "education")
        self.assertEqual(result.response["symptoms"], [])
        self.assertTrue(result.response["prevention_and_lifestyle"])
        self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)

    def test_real_symptoms_request_has_no_definition_or_lifestyle(self):
        result, session = HealthApplication(allow_unverified_for_development=True).process("What are PCOS symptoms?")
        self.assertEqual(result.response["response_type"], "education")
        self.assertEqual(result.response["what_it_is"], "")
        self.assertEqual(result.response["prevention_and_lifestyle"], [])
        self.assertEqual(len(result.response["claims"]), 1)
        self.assertEqual(len(result.response["evidence"]), 1)
        self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)

    def test_followup_after_optout_or_deletion_asks_for_topic(self):
        for remembered in (False, True):
            with self.subTest(remembered=remembered):
                app = HealthApplication(allow_unverified_for_development=True)
                _, session = app.process("What is PCOS?", allow_session_context=remembered)
                sid = session.session_id
                if remembered:
                    app.forget(sid)
                result, _ = app.process("What about exercise?", session_id=sid,
                                        allow_session_context=remembered)
                self.assertEqual(result.response["response_type"], "clarification")

    def test_urgent_message_preempts_focus_selection(self):
        retrieval = Mock()
        app = HealthApplication(retrieve=retrieval)
        result, _ = app.process("What about symptoms? I have severe pelvic pain and fainted.")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        retrieval.assert_not_called()


if __name__ == "__main__":
    unittest.main()
