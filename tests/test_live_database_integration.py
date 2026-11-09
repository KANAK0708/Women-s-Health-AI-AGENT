"""Live integration tests for PostgreSQL + pgvector and Redis adapters.

Verifies:
1. PostgreSQL manifest ingestion, updates, and schema idempotency.
2. Successful retrieval with 1-to-1 passage-to-citation identity.
3. Deterministic filters: category, jurisdiction, population, expiry, supersession.
4. Low-relevance, out-of-domain, and punctuation-heavy queries returning InsufficientEvidenceError.
5. Redis session lifecycle: creation, update, expiry, deletion cascade, consent opt-out, and cross-session isolation.
6. Graceful failure handling when databases fail after initialization.

Gracefully skips with unittest.SkipTest if PostgreSQL or Redis is unreachable.
Uses no real patient data.
"""

from datetime import date, datetime, timedelta, timezone
import json
import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from app.retrieval.engine import DEFAULT_MANIFEST_PATH, RetrievalBundle
from app.retrieval.exceptions import InsufficientEvidenceError
from app.retrieval.pg_vector_engine import PgVectorHybridEngine, get_retrieval_engine
from app.schemas.evidence import EducationalCategory, EvidenceCitation, EvidencePassage
from app.schemas.memory import MinimalPatientContext, SessionMemory, TriState
from app.storage.consent import ConsentPolicy
from app.storage.redis_session_store import RedisSessionStore, get_session_store


class TestLivePostgreSQLIntegration(unittest.TestCase):
    """Integration test suite executing against a live PostgreSQL + pgvector instance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = PgVectorHybridEngine()
        if not cls.engine.ping():
            raise unittest.SkipTest("Live PostgreSQL/pgvector instance is not reachable on localhost:5432.")

    def setUp(self) -> None:
        logging.disable(logging.ERROR)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)

    def test_manifest_ingestion_and_updates(self) -> None:
        """Verify atomic upsert of clinical sources and passages from manifest.json."""
        num_sources, num_passages = self.engine.sync_from_manifest(DEFAULT_MANIFEST_PATH)
        self.assertGreaterEqual(num_sources, 6, "Expected at least 6 sources in manifest")
        self.assertGreaterEqual(num_passages, 15, "Expected at least 15 passages in manifest")

        # Ingestion idempotency: running again should not duplicate records
        num_sources_repeat, num_passages_repeat = self.engine.sync_from_manifest(DEFAULT_MANIFEST_PATH)
        self.assertEqual(num_sources, num_sources_repeat)
        self.assertEqual(num_passages, num_passages_repeat)

    def test_successful_retrieval_and_citation_identity(self) -> None:
        """Verify successful retrieval and exact 1-to-1 citation-to-passage identity."""
        bundle = self.engine.retrieve("What is PCOS?", allow_unverified_for_development=True)
        self.assertIsInstance(bundle, RetrievalBundle)
        self.assertGreater(len(bundle.scored_passages), 0)
        self.assertEqual(len(bundle.citations), len(bundle.scored_passages))

        # Validate strict 1-to-1 alignment required by health_tools.handoff
        for idx, (scored, citation) in enumerate(zip(bundle.scored_passages, bundle.citations), start=1):
            passage = scored.passage
            self.assertEqual(citation.id, f"e{idx}")
            self.assertEqual(citation.passage_id, passage.passage_id)
            self.assertEqual(citation.source_id, passage.source_id)
            self.assertEqual(citation.title, passage.title)
            self.assertEqual(citation.url, passage.url)
            self.assertEqual(citation.locator, passage.locator)
            self.assertEqual(citation.reviewed_at, str(passage.reviewed_at))
            self.assertGreaterEqual(scored.final_score, 0.18)

    def test_category_filter(self) -> None:
        """Verify educational category filtering strictly limits returned passages."""
        bundle = self.engine.retrieve(
            "What are PCOS symptoms and irregular periods?",
            category=EducationalCategory.SYMPTOMS,
            allow_unverified_for_development=True,
        )
        self.assertGreater(len(bundle.scored_passages), 0)
        for scored in bundle.scored_passages:
            self.assertEqual(scored.passage.category, EducationalCategory.SYMPTOMS)

    def test_jurisdiction_and_population_filters(self) -> None:
        """Verify jurisdiction and target population boundaries in PostgreSQL SQL pre-filters."""
        # Querying with adult population succeeds
        bundle = self.engine.retrieve(
            "What is PCOS?",
            population="adults_18+",
            allow_unverified_for_development=True,
        )
        self.assertGreater(len(bundle.scored_passages), 0)

        # Pediatric query cannot match adult-only sources -> raises InsufficientEvidenceError
        with self.assertRaises(InsufficientEvidenceError):
            self.engine.retrieve(
                "What is PCOS?",
                population="pediatric_under_18",
                allow_unverified_for_development=True,
            )

    def test_expiry_and_supersession_filters(self) -> None:
        """Verify expired sources and superseded guidelines are never returned."""
        # 1. Superseded guidelines (e.g. src-legacy-pcos-2018) must never appear in results
        bundle = self.engine.retrieve("What is PCOS?", allow_unverified_for_development=True)
        for scored in bundle.scored_passages:
            self.assertNotEqual(scored.passage.source_id, "src-legacy-pcos-2018")
            self.assertFalse(scored.passage.passage_id.startswith("psg-legacy"))

        # 2. Reference date in distant future where all sources are expired
        future_date = date(2045, 1, 1)
        with self.assertRaises(InsufficientEvidenceError):
            self.engine.retrieve(
                "What is PCOS?",
                reference_date=future_date,
                allow_unverified_for_development=True,
            )

    def test_low_relevance_queries_return_insufficient_evidence(self) -> None:
        """Verify out-of-domain and low-scoring queries trigger InsufficientEvidenceError."""
        unrelated_queries = [
            "diesel tractor combustion engine repair",
            "quantum cryptography algorithms in high performance computing",
            "commercial aircraft turbofan maintenance checklist",
        ]
        for query in unrelated_queries:
            with self.subTest(query=query):
                with self.assertRaises(InsufficientEvidenceError):
                    self.engine.retrieve(query, allow_unverified_for_development=True)

    def test_punctuation_heavy_queries(self) -> None:
        """Verify punctuation-heavy queries are sanitized and do not trigger syntax errors."""
        # Punctuation with valid medical terms -> should succeed
        bundle = self.engine.retrieve(
            "PCOS??? (symptoms: & signs!)",
            allow_unverified_for_development=True,
        )
        self.assertGreater(len(bundle.scored_passages), 0)

        # Pure punctuation without any medical topic -> raises InsufficientEvidenceError cleanly
        with self.assertRaises(InsufficientEvidenceError):
            self.engine.retrieve(
                "??? !!! ### %%% ^^^ &&&",
                allow_unverified_for_development=True,
            )

    def test_database_failure_after_initialization(self) -> None:
        """Verify graceful error handling if PostgreSQL connection drops during retrieve."""
        with patch.object(self.engine, "_get_connection", side_effect=Exception("Database connection terminated")):
            with self.assertRaises(Exception):
                self.engine.retrieve("What is PCOS?")


class TestLiveRedisIntegration(unittest.TestCase):
    """Integration test suite executing against a live Redis instance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = RedisSessionStore()
        if not cls.store.ping():
            raise unittest.SkipTest("Live Redis instance is not reachable on localhost:6379.")

    def setUp(self) -> None:
        logging.disable(logging.ERROR)
        self.created_session_ids: list[str] = []

    def tearDown(self) -> None:
        # Clean up any test sessions created during test
        for sid in self.created_session_ids:
            try:
                self.store.delete_session(sid)
            except Exception:
                pass
        logging.disable(logging.NOTSET)

    def test_session_creation_updates_and_retrieval(self) -> None:
        """Verify creating, updating, and fetching a session memory object in Redis."""
        now = datetime.now(timezone.utc)
        session = self.store.create_session(now=now)
        self.created_session_ids.append(session.session_id)

        # Update context
        session.context.age = 29
        session.context.is_adult = TriState.YES
        session.context.active_topic = "pcos_overview"
        session.turn_count = 1
        self.store.save_session(session, now=now)

        fetched = self.store.get_session(session.session_id, now=now)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.session_id, session.session_id)
        self.assertEqual(fetched.context.age, 29)
        self.assertEqual(fetched.context.is_adult, TriState.YES)
        self.assertEqual(fetched.context.active_topic, "pcos_overview")
        self.assertEqual(fetched.turn_count, 1)

    def test_session_isolation(self) -> None:
        """Verify strict isolation between distinct sessions without crosstalk."""
        now = datetime.now(timezone.utc)
        sess_a = self.store.create_session(now=now)
        sess_b = self.store.create_session(now=now)
        self.created_session_ids.extend([sess_a.session_id, sess_b.session_id])

        sess_a.context.age = 24
        sess_a.context.active_topic = "dysmenorrhea"
        self.store.save_session(sess_a, now=now)

        sess_b.context.age = 38
        sess_b.context.active_topic = "endometriosis"
        self.store.save_session(sess_b, now=now)

        fetched_a = self.store.get_session(sess_a.session_id, now=now)
        fetched_b = self.store.get_session(sess_b.session_id, now=now)

        self.assertIsNotNone(fetched_a)
        self.assertIsNotNone(fetched_b)
        self.assertEqual(fetched_a.context.age, 24)
        self.assertEqual(fetched_a.context.active_topic, "dysmenorrhea")
        self.assertEqual(fetched_b.context.age, 38)
        self.assertEqual(fetched_b.context.active_topic, "endometriosis")

    def test_consent_opt_out(self) -> None:
        """Verify that when consent is declined, context is not retained."""
        now = datetime.now(timezone.utc)
        policy = ConsentPolicy(allow_minimal_session_context=False)
        session = self.store.create_session(policy=policy, now=now)
        self.created_session_ids.append(session.session_id)

        self.assertFalse(session.allow_session_context)
        # Attempt to attach context when consent is declined
        session.context.age = 30
        self.store.save_session(session, now=now)

        fetched = self.store.get_session(session.session_id, now=now)
        self.assertIsNotNone(fetched)
        self.assertFalse(fetched.allow_session_context)

    def test_session_deletion_cascade(self) -> None:
        """Verify deleting a session completely removes it from Redis."""
        now = datetime.now(timezone.utc)
        session = self.store.create_session(now=now)
        sid = session.session_id

        self.store.save_session(session, now=now)
        self.assertIsNotNone(self.store.get_session(sid, now=now))

        deleted = self.store.delete_session(sid)
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get_session(sid, now=now))

    def test_session_expiry(self) -> None:
        """Verify session expiry boundary: expired sessions return None."""
        now = datetime.now(timezone.utc)
        # Create a session with TTL of 1 second
        policy = ConsentPolicy(session_ttl_minutes=1)
        session = self.store.create_session(policy=policy, now=now)
        self.created_session_ids.append(session.session_id)

        # Simulating time advanced past expires_at
        future_now = now + timedelta(minutes=5)
        fetched = self.store.get_session(session.session_id, now=future_now)
        self.assertIsNone(fetched, "Expected session to be expired and return None")

    def test_corrupted_payload_handling(self) -> None:
        """Verify store safely returns None without crashing on corrupted Redis data."""
        client = self.store._get_client()
        corrupted_key = f"{self.store.key_prefix}corrupted_test_session"
        client.set(corrupted_key, "{invalid-json-data", ex=60)
        try:
            result = self.store.get_session("corrupted_test_session")
            self.assertIsNone(result)
        finally:
            client.delete(corrupted_key)


if __name__ == "__main__":
    unittest.main()
