"""Unit and integration tests for newly added medical APIs, expanded manifest,
enhanced hybrid reranking, Orchestrator routes, and LangChain tools.
"""

import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from app.retrieval.engine import HybridRetrievalEngine
from app.schemas.evidence import EducationalCategory
from app.workflow.service import HealthApplication
from health_tools.clinical_trials import search_clinical_trials
from health_tools.contracts import EvidenceSource, ToolResult
from health_tools.europepmc import search_europepmc
from health_tools.medlineplus import search_medlineplus
from health_tools.workflow import Orchestrator, SafetyDecision, ToolPolicy
from tools import (
    EDUCATIONAL_TOOLS,
    clinical_trials_tool,
    cycle_calculator_tool,
    europepmc_tool,
    guideline_registry_tool,
    medlineplus_tool,
    pubmed_tool,
)


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


MEDLINEPLUS_SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<nlmSearchResult>
  <count>1</count>
  <list num="1" start="0" per="3">
    <document rank="1" url="https://medlineplus.gov/polycysticovarysyndrome.html">
      <content name="title">&lt;span class="qt0"&gt;Polycystic Ovary Syndrome&lt;/span&gt;</content>
      <content name="organizationName">National Library of Medicine</content>
      <content name="altTitle">PCOS</content>
      <content name="FullSummary">&lt;p&gt;Polycystic ovary syndrome (PCOS) happens when a woman's ovaries or adrenal glands produce more male hormones than normal.&lt;/p&gt;</content>
      <content name="mesh">Polycystic Ovary Syndrome</content>
    </document>
  </list>
</nlmSearchResult>
"""

EUROPEPMC_SAMPLE_JSON = json.dumps({
    "hitCount": 1,
    "resultList": {
        "result": [
            {
                "id": "38000001",
                "source": "MED",
                "pmid": "38000001",
                "pmcid": "PMC1000001",
                "doi": "10.1000/pcos.2024",
                "title": "Evidence-based lifestyle interventions in PCOS: a systematic review.",
                "pubYear": "2024",
                "journalTitle": "Human Reproduction Update",
                "abstractText": "<p>Structured aerobic and resistance exercise improves insulin sensitivity in PCOS.</p>",
                "isOpenAccess": "Y",
            }
        ]
    },
}).encode("utf-8")

CLINICAL_TRIALS_SAMPLE_JSON = json.dumps({
    "totalCount": 1,
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT05551234",
                    "briefTitle": "Exercise and Nutrition in Polycystic Ovary Syndrome",
                    "officialTitle": "Randomized Trial of Structured Exercise and Nutrition in Adults With PCOS",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "lastUpdatePostDateStruct": {"date": "2026-09-15"},
                },
                "descriptionModule": {
                    "briefSummary": "This clinical trial evaluates a 16-week lifestyle intervention in adults with PCOS.",
                },
                "conditionsModule": {
                    "conditions": ["Polycystic Ovary Syndrome", "Insulin Resistance"],
                },
                "designModule": {
                    "phases": ["NA"],
                },
            }
        }
    ],
}).encode("utf-8")


class MedlinePlusTests(unittest.TestCase):
    @patch("health_tools.medlineplus.urlopen")
    def test_valid_search_and_html_stripping(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(MEDLINEPLUS_SAMPLE_XML)
        res = search_medlineplus("PCOS", max_results=2, timeout=5)
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.tool, "search_medlineplus")
        self.assertEqual(res.data["returned_count"], 1)
        self.assertEqual(res.sources[0].title, "Polycystic Ovary Syndrome")
        self.assertEqual(res.sources[0].url, "https://medlineplus.gov/polycysticovarysyndrome.html")
        self.assertNotIn("<p>", res.sources[0].excerpt)
        self.assertIn("male hormones", res.sources[0].excerpt)

    @patch("health_tools.medlineplus.urlopen")
    def test_empty_results_and_input_validation(self, mock_urlopen):
        for bad_q in ("", "   ", None, "x" * 501):
            self.assertEqual(search_medlineplus(bad_q).error.code, "invalid_query")
        self.assertEqual(search_medlineplus("PCOS", max_results=0).error.code, "invalid_limit")
        self.assertEqual(search_medlineplus("PCOS", timeout=0).error.code, "invalid_timeout")
        mock_urlopen.assert_not_called()

        mock_urlopen.return_value = _FakeHTTPResponse(b"<nlmSearchResult><count>0</count><list/></nlmSearchResult>")
        empty = search_medlineplus("unmatched query")
        self.assertEqual(empty.status, "insufficient_data")


class EuropePMCTests(unittest.TestCase):
    @patch("health_tools.europepmc.urlopen")
    def test_valid_search_and_metadata(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(EUROPEPMC_SAMPLE_JSON)
        res = search_europepmc("PCOS lifestyle", max_results=2, timeout=5)
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.tool, "search_europepmc")
        self.assertEqual(len(res.sources), 1)
        self.assertEqual(res.sources[0].source_id, "europepmc:MED:38000001")
        self.assertTrue(res.data["articles"][0]["is_open_access"])
        self.assertNotIn("<p>", res.sources[0].excerpt)

    @patch("health_tools.europepmc.urlopen")
    def test_validation_and_network_errors(self, mock_urlopen):
        self.assertEqual(search_europepmc("").error.code, "invalid_query")
        self.assertEqual(search_europepmc("PCOS", max_results=9).error.code, "invalid_limit")
        mock_urlopen.assert_not_called()

        mock_urlopen.side_effect = HTTPError("https://example.org", 429, "Too Many Requests", {}, None)
        err = search_europepmc("PCOS")
        self.assertEqual(err.status, "error")
        self.assertEqual(err.error.code, "rate_limited")
        self.assertTrue(err.error.retryable)


class ClinicalTrialsTests(unittest.TestCase):
    @patch("health_tools.clinical_trials.urlopen")
    def test_valid_study_parsing(self, mock_urlopen):
        mock_urlopen.return_value = _FakeHTTPResponse(CLINICAL_TRIALS_SAMPLE_JSON)
        res = search_clinical_trials("PCOS", max_results=2, timeout=5)
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.tool, "search_clinical_trials")
        self.assertEqual(res.sources[0].source_id, "clinicaltrials:NCT05551234")
        self.assertEqual(res.sources[0].url, "https://clinicaltrials.gov/study/NCT05551234")
        self.assertIn("RECRUITING", res.sources[0].title)

    @patch("health_tools.clinical_trials.urlopen")
    def test_validation_and_invalid_nct_id(self, mock_urlopen):
        self.assertEqual(search_clinical_trials("").error.code, "invalid_query")
        self.assertEqual(search_clinical_trials("PCOS", timeout=99).error.code, "invalid_timeout")
        mock_urlopen.assert_not_called()

        bad_payload = json.dumps({
            "totalCount": 1,
            "studies": [{"protocolSection": {"identificationModule": {"nctId": "BAD_ID", "briefTitle": "T"}}}],
        }).encode("utf-8")
        mock_urlopen.return_value = _FakeHTTPResponse(bad_payload)
        self.assertEqual(search_clinical_trials("PCOS").error.code, "invalid_response")


class ExpandedManifestAndRerankerTests(unittest.TestCase):
    def setUp(self):
        self.engine = HybridRetrievalEngine(allow_unverified_for_development=True)
        self.app = HealthApplication(allow_unverified_for_development=True)

    def test_new_womens_health_topics_retrieve_and_verify_100(self):
        queries = [
            ("What is PMS and PMDD, what are the symptoms, and what lifestyle habits help?", "psg-pms-"),
            ("How is PMDD diagnosed and evaluated?", "psg-pms-eval-01"),
            ("What are uterine fibroids, what are their symptoms, and what lifestyle habits help?", "psg-fib-"),
            ("What are the symptoms of leiomyomas?", "psg-fib-sym-01"),
            ("What is perimenopause and menopause, what are the symptoms, and how to manage hot flashes?", "psg-meno-"),
            ("When should I see a doctor for postmenopausal bleeding in menopause?", "psg-meno-care-01"),
            ("How is endometriosis diagnosed and evaluated?", "psg-endo-eval-01"),
            ("When should I see a doctor for PCOS warning signs?", "psg-pcos-care-01"),
            ("How is heavy menstrual bleeding evaluated by a doctor?", "psg-hmb-eval-01"),
        ]
        for query, expected_prefix in queries:
            with self.subTest(query=query):
                result, session = self.app.process(query, allow_session_context=True)
                self.assertEqual(result.response["response_type"], "education", f"Failed on query: {query} -> {result.response}")
                self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)
                passage_ids = [c["passage_id"] for c in result.response["evidence"]]
                self.assertTrue(
                    any(pid.startswith(expected_prefix) for pid in passage_ids),
                    f"Expected prefix {expected_prefix} in {passage_ids} for query '{query}'",
                )

    def test_elliptical_followup_works_for_new_topics(self):
        _, session = self.app.process("What are uterine fibroids?", allow_session_context=True)
        self.assertEqual(session.context.active_topic, "Uterine Fibroids")
        followup, session = self.app.process("What about the symptoms?", session_id=session.session_id)
        self.assertEqual(followup.response["response_type"], "education")
        self.assertTrue(followup.response["symptoms"])
        self.assertIn("CLAIM_VERIFICATION_PASSED_100", session.audit_codes)


class OrchestratorAndLangChainToolsIntegrationTests(unittest.TestCase):
    def test_orchestrator_routes_new_external_sources_with_privacy_guard(self):
        medline_mock = Mock(return_value=ToolResult(
            tool="search_medlineplus",
            status="ok",
            sources=(EvidenceSource(
                "medlineplus:1:pcos", "Polycystic Ovary Syndrome",
                "https://medlineplus.gov/polycysticovarysyndrome.html",
                "NIH / MedlinePlus", "2026-11-12T00:00:00Z", "Summary text",
            ),),
        ))
        epmc_mock = Mock(return_value=ToolResult(
            tool="search_europepmc",
            status="ok",
            sources=(EvidenceSource(
                "europepmc:MED:1", "Europe PMC PCOS Review",
                "https://europepmc.org/article/MED/1",
                "Europe PMC", "2026-11-12T00:00:00Z", "Abstract text", "2025",
            ),),
        ))
        trials_mock = Mock(return_value=ToolResult(
            tool="search_clinical_trials",
            status="ok",
            sources=(EvidenceSource(
                "clinicaltrials:NCT05551234", "PCOS Trial [RECRUITING]",
                "https://clinicaltrials.gov/study/NCT05551234",
                "NIH / ClinicalTrials.gov", "2026-11-12T00:00:00Z", "Study summary", "2026-09-15",
            ),),
        ))
        app = HealthApplication(
            medlineplus_search=medline_mock,
            europepmc_search=epmc_mock,
            clinical_trials_search=trials_mock,
        )

        # Without allow_external_research, none of the external APIs are called
        for q in ("Search MedlinePlus for PCOS", "Search Europe PMC for endometriosis", "Find clinical trials for PCOS"):
            res, _ = app.process(q)
            self.assertEqual(res.response["response_type"], "clarification")
        medline_mock.assert_not_called()
        epmc_mock.assert_not_called()
        trials_mock.assert_not_called()

        # With explicit permission and separate non-identifying research_query, each tool runs
        res_ml, _ = app.process(
            "Search MedlinePlus for PCOS",
            allow_external_research=True,
            research_query="Polycystic Ovary Syndrome",
        )
        self.assertEqual(res_ml.response["response_type"], "education")
        self.assertIn("TOOL_MEDLINEPLUS", res_ml.events)
        medline_mock.assert_called_once_with("Polycystic Ovary Syndrome", max_results=3, timeout=10)

        res_epmc, _ = app.process(
            "Search Europe PMC for endometriosis",
            allow_external_research=True,
            research_query="endometriosis review",
        )
        self.assertEqual(res_epmc.response["response_type"], "education")
        self.assertIn("TOOL_EUROPEPMC", res_epmc.events)
        epmc_mock.assert_called_once_with("endometriosis review", max_results=3, timeout=10)

        res_ct, _ = app.process(
            "Find recruiting clinical trials for PCOS",
            allow_external_research=True,
            research_query="PCOS lifestyle",
        )
        self.assertEqual(res_ct.response["response_type"], "education")
        self.assertIn("TOOL_CLINICAL_TRIALS", res_ct.events)
        trials_mock.assert_called_once_with("PCOS lifestyle", max_results=3, timeout=10)

    def test_orchestrator_offline_guideline_registry_route(self):
        workflow = Orchestrator(
            safety_check=lambda *a: SafetyDecision("proceed"),
            retrieve=Mock(),
        )
        res = workflow.run(
            "Search the guideline registry for period diary",
            jurisdiction="TEST",
            population="adults_18+",
            as_of="2026-11-06",
            allow_demo_guidelines=False,
        )
        self.assertIn("TOOL_GUIDELINES", res.events)

    def test_langchain_tools_enforce_scope_and_safety_before_execution(self):
        self.assertEqual(len(EDUCATIONAL_TOOLS), 9)
        for tool_obj in (medlineplus_tool, pubmed_tool, europepmc_tool, clinical_trials_tool, guideline_registry_tool):
            with self.subTest(tool=tool_obj.name):
                blocked = tool_obj.invoke("Should I stop taking my prescribed medicine?")
                self.assertIn("[SCOPE_POLICY_BLOCK]", blocked)
                urgent = tool_obj.invoke("I have severe pelvic pain and fainted")
                self.assertIn("[URGENT_PROTOCOL=", urgent)

        calc_out = cycle_calculator_tool.invoke({
            "period_start_dates": ["2026-08-01", "2026-09-04", "2026-10-06"],
            "as_of": "2026-11-06",
        })
        self.assertIn("34, 32 days", calc_out)


if __name__ == "__main__":
    unittest.main()

