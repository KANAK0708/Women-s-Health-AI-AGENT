import json
import tempfile
import unittest
from pathlib import Path

from evals.research.scoring import answer_text, phrase_found, score_case, summarize
from evals.run_research_evals import CASES_PATH, load_cases, rescore

CASE = {
    "id": "dysmenorrhea-relief", "category": "research", "question": "q",
    "expect_status": ["complete", "partial"],
    "must_cover": [
        {"label": "NSAIDs", "any": ["nsaid", "ibuprofen"]},
        {"label": "heat", "any": ["heat"]},
        {"label": "exercise", "any": ["exercise", "yoga"]},
        {"label": "hormonal contraception", "any": ["hormonal contracept", "birth control"]},
    ],
    "must_not": ["cure"],
}


def report(status="complete", claims=("NSAIDs such as ibuprofen relieve pain.", "Heat therapy reduces pain.", "Yoga helps."),
           types=("systematic_review", "consumer_health", "rct"), rejected=1, log=()):
    return {
        "status": status, "summary": "", "sub_answers": [],
        "key_findings": [{"claim": c, "source_type": t} for c, t in zip(claims, types)],
        "rejected_findings": rejected, "sources": [{}, {}], "search_log": list(log),
    }


class ScoringTests(unittest.TestCase):
    def test_research_case_scores(self):
        result = score_case(CASE, report(), 12.34)
        self.assertEqual(result["coverage"], 0.75)
        self.assertEqual(result["missing"], ["hormonal contraception"])
        self.assertEqual(result["strong_evidence_share"], 0.33)
        self.assertEqual(result["rejected_share"], 0.25)
        self.assertTrue(result["passed"])
        self.assertEqual(result["duration_s"], 12.3)

    def test_fails_on_low_coverage_few_findings_bad_status_or_violation(self):
        self.assertFalse(score_case(CASE, report(claims=("Heat helps.",), types=("rct",)), 1)["passed"])
        self.assertFalse(score_case(CASE, report(status="no_evidence"), 1)["passed"])
        bad = report(claims=("NSAIDs cure pain.", "Heat helps.", "Yoga helps."))
        self.assertEqual(score_case(CASE, bad, 1)["violations"], ["cure"])
        self.assertFalse(score_case(CASE, bad, 1)["passed"])

    def test_phrases_match_word_starts_only(self):
        text = answer_text(report(claims=("Human papillomavirus causes most cervical cancer.",)))
        # Phrases are prefixes at word starts: the cases file uses "pap test", not "pap".
        self.assertFalse(phrase_found("pap test", text))
        self.assertTrue(phrase_found("papillomavirus", text))
        self.assertFalse(phrase_found("virus", text))  # never matches mid-word
        self.assertTrue(phrase_found("contracept", "oral contraceptives help"))
        self.assertFalse(phrase_found("cin", "medicine"))

    def test_safety_case_and_pipeline_failures(self):
        safety = {"id": "s", "category": "safety", "question": "q", "expect_status": ["urgent"]}
        self.assertTrue(score_case(safety, {"status": "urgent"}, 0.1)["passed"])
        self.assertFalse(score_case(safety, {"status": "complete"}, 0.1)["passed"])
        failing = report(log=["round 1 | web | 'x' -> ERROR timeout", "extraction failed for u: 429", "ok line"])
        self.assertEqual(score_case(CASE, failing, 1)["pipeline_failures"], 2)

    def test_summary(self):
        safety = {"id": "s", "category": "safety", "question": "q", "expect_status": ["urgent"]}
        rows = [score_case(CASE, report(), 10), score_case(safety, {"status": "urgent"}, 0)]
        summary = summarize(rows)
        self.assertEqual(summary["pass_rate"], 1.0)
        self.assertEqual(summary["safety_passed"], "1/1")
        self.assertEqual(summary["mean_coverage"], 0.75)


class RunnerTests(unittest.TestCase):
    def test_cases_file_is_well_formed(self):
        cases = load_cases(CASES_PATH)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        for case in cases:
            self.assertIn(case["category"], {"research", "safety"})
            self.assertTrue(case["expect_status"])
            if case["category"] == "research":
                self.assertGreaterEqual(len(case["must_cover"]), 2, case["id"])

    def test_filters(self):
        self.assertTrue(all(c["category"] == "safety" for c in load_cases(CASES_PATH, category="safety")))
        self.assertEqual([c["id"] for c in load_cases(CASES_PATH, only=["pmdd"])], ["pmdd"])
        self.assertEqual(len(load_cases(CASES_PATH, limit=2)), 2)
        with self.assertRaises(SystemExit):
            load_cases(CASES_PATH, only=["no-such-case"])

    def test_rescore_saved_run_without_api_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / "cases.json"
            cases_path.write_text(json.dumps({"suite_name": "t", "cases": [CASE]}))
            run_path = Path(tmp) / "run.json"
            run_path.write_text(json.dumps({"results": [{"id": CASE["id"], "duration_s": 5.0}],
                                            "reports": {CASE["id"]: report()}}))
            run = rescore(run_path, cases_path)
        self.assertEqual(run["results"][0]["coverage"], 0.75)
        self.assertEqual(run["summary"]["research_passed"], "1/1")


if __name__ == "__main__":
    unittest.main()
