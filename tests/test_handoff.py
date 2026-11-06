import copy
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from health_tools.handoff import (
    ContractViolation, adapt_retrieval, adapt_session, validate_claim_references,
)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
        self.session = {
            "allow_session_context": True, "created_at": "2026-11-06T11:00:00+00:00",
            "expires_at": "2026-11-06T13:00:00+00:00",
            "context": {"pregnancy_status": "not_provided", "age": 25, "is_adult": "yes"},
        }
        self.passage = dict(passage_id="p1", source_id="s1", title="Synthetic fixture",
                            url="https://example.org", locator="Section 1",
                            reviewed_at="2026-11-06", category="what_it_is", text="Synthetic text.")
        self.citation = {key: value for key, value in self.passage.items()
                         if key not in ("category", "text")}
        self.citation["id"] = "e1"

    def bundle(self):
        return SimpleNamespace(manifest_version="test-v1",
                               scored_passages=[SimpleNamespace(passage=self.passage)],
                               citations=[self.citation])

    def test_unknown_is_preserved_and_session_not_modified(self):
        before = copy.deepcopy(self.session)
        context = adapt_session(self.session, now=self.now)
        self.assertTrue(context.context_available)
        self.assertEqual(context.pregnancy_status, "not_provided")
        self.assertEqual(self.session, before)
        self.assertNotIn("session_id", context.to_dict())

    def test_declined_consent_does_not_expose_context(self):
        self.session["allow_session_context"] = False
        self.session["context"] = "must not be read"
        context = adapt_session(self.session, now=self.now)
        self.assertFalse(context.context_available)
        self.assertIsNone(context.age)

    def test_expiry_boundary(self):
        self.session["expires_at"] = self.now.isoformat()
        context = adapt_session(self.session, now=self.now)
        self.assertEqual(context.unavailable_reason, "session_expired")
        self.assertIsNone(context.age)

    def test_no_session(self):
        self.assertEqual(adapt_session(None).unavailable_reason, "no_session")

    def test_invalid_session_contracts(self):
        for key, value in (("allow_session_context", "yes"), ("created_at", "bad"),
                           ("expires_at", "2026-11-06T13:00:00")):
            with self.subTest(key=key):
                session = copy.deepcopy(self.session)
                session[key] = value
                with self.assertRaises(ContractViolation):
                    adapt_session(session, now=self.now)
        for change in ({"pregnancy_status": False}, {"age": True},
                       {"clarification_turns_used": 3}, {"is_adult": "no"}):
            with self.subTest(change=change):
                session = copy.deepcopy(self.session)
                session["context"].update(change)
                with self.assertRaises(ContractViolation):
                    adapt_session(session, now=self.now)

    def test_pydantic_style_payload_supported(self):
        payload = self.session
        class ModelFixture:
            def model_dump(self, *, mode):
                assert mode == "json"
                return copy.deepcopy(payload)
        self.assertEqual(adapt_session(ModelFixture(), now=self.now).age, 25)

    def test_evidence_preserves_exact_text_and_ids(self):
        evidence = adapt_retrieval(self.bundle())
        self.assertEqual(evidence.passages[0].text, self.passage["text"])
        self.assertEqual(evidence.passages[0].citation_id, "e1")
        self.passage["text"] = "Changed later"
        self.assertEqual(evidence.passages[0].text, "Synthetic text.")

    def test_mismatched_citation_rejected(self):
        self.citation["url"] = "https://other.example.org"
        with self.assertRaises(ContractViolation):
            adapt_retrieval(self.bundle())

    def test_duplicate_and_orphan_citations_rejected(self):
        for mode in ("duplicate", "orphan", "missing"):
            with self.subTest(mode=mode):
                bundle = self.bundle()
                if mode == "duplicate":
                    bundle.citations.append(self.citation)
                elif mode == "orphan":
                    bundle.scored_passages = []
                else:
                    bundle.citations = []
                with self.assertRaises(ContractViolation):
                    adapt_retrieval(bundle)

    def test_empty_evidence_is_explicit(self):
        bundle = self.bundle()
        bundle.citations = []
        bundle.scored_passages = []
        self.assertEqual(adapt_retrieval(bundle).passages, ())

    def test_claim_reference_validation(self):
        evidence = adapt_retrieval(self.bundle())
        validate_claim_references([{"id": "c1", "text": "Example", "evidence_ids": ["e1"]}], evidence)
        for refs in ([], ["invented"], [None]):
            with self.subTest(refs=refs), self.assertRaises(ContractViolation):
                validate_claim_references([{"id": "c1", "text": "Example", "evidence_ids": refs}], evidence)


if __name__ == "__main__":
    unittest.main()
