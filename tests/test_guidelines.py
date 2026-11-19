import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from health_tools.guidelines import DEMO_REGISTRY, search_guidelines


class GuidelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "registry.json"
        self.registry = json.loads(DEMO_REGISTRY.read_text())

    def search(self, query="period diary", **kwargs):
        self.path.write_text(json.dumps(self.registry))
        options = dict(jurisdiction="TEST", population="adults", as_of="2026-11-06",
                       registry_path=self.path, allow_demo=True)
        options.update(kwargs)
        return search_guidelines(query, **options)

    def test_exact_text_and_provenance(self):
        result = self.search()
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.data["demo"])
        self.assertEqual(result.sources[0].excerpt, self.registry["passages"][0]["text"])
        self.assertIn("SYNTHETIC", result.limitations[0])

    def test_demo_requires_explicit_permission(self):
        self.assertEqual(self.search(allow_demo=False).error.code, "demo_disabled")

    def test_scope_filters(self):
        for option in ({"jurisdiction": "IN"}, {"population": "minors"}, {"language": "hi"}):
            with self.subTest(option=option):
                self.assertEqual(self.search(**option).status, "insufficient_data")

    def test_ineligible_passages_never_return(self):
        original = copy.deepcopy(self.registry)
        for change in (
            {"status": "draft"}, {"status": "superseded"}, {"rights_status": "pending"},
            {"review_due": "2026-11-06"}, {"reviewed_on": "2026-12-01"},
        ):
            with self.subTest(change=change):
                self.registry = copy.deepcopy(original)
                self.registry["passages"][0].update(change)
                result = self.search()
                self.assertEqual(result.status, "insufficient_data")
                self.assertEqual(result.sources, ())

    def test_integrity_and_review_errors_fail_closed(self):
        original = copy.deepcopy(self.registry)
        for change in ({"text": "tampered"}, {"reviewer": ""}, {"review_due": "bad"},
                       {"rights_basis": ""}, {"url": "file:///private"}):
            with self.subTest(change=change):
                self.registry = copy.deepcopy(original)
                self.registry["passages"][0].update(change)
                self.assertEqual(self.search().error.code, "invalid_registry")

    def test_duplicate_ids_fail_closed(self):
        self.registry["passages"].append(copy.deepcopy(self.registry["passages"][0]))
        self.assertEqual(self.search().error.code, "invalid_registry")

    def test_unrelated_or_stopword_queries_do_not_return_evidence(self):
        for query in ("astronomy", "what is the"):
            self.assertEqual(self.search(query).status, "insufficient_data")

    def test_ranking_and_result_limit(self):
        other = copy.deepcopy(self.registry["passages"][0])
        other.update(passage_id="demo:other", title="Unrelated fixture", text="Period entry.")
        other["sha256"] = hashlib.sha256(other["text"].encode()).hexdigest()
        self.registry["passages"].append(other)
        result = self.search(max_results=1)
        self.assertEqual(result.data["returned_count"], 1)
        self.assertEqual(result.sources[0].source_id, "demo:period-diary:1")

    def test_default_registry_has_no_approved_clinical_evidence(self):
        result = search_guidelines("PCOS", jurisdiction="IN", population="adults")
        self.assertEqual(result.status, "insufficient_data")
        self.assertFalse(result.data["demo"])

    def test_bad_inputs_and_missing_registry(self):
        for query, options, code in (
            ("", {}, "invalid_query"), ("period", {"max_results": True}, "invalid_limit"),
            ("period", {"as_of": "bad"}, "invalid_as_of"),
            ("period", {"jurisdiction": ""}, "invalid_scope"),
            ("period", {"registry_path": self.path.parent / "missing"}, "registry_unavailable"),
        ):
            with self.subTest(code=code):
                self.assertEqual(self.search(query, **options).error.code, code)


if __name__ == "__main__":
    unittest.main()
