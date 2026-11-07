"""Optional live adapter tests using synthetic data only.

Set TEST_POSTGRES_ADMIN_URL and TEST_REDIS_URL to run these tests. PostgreSQL tests
create and drop a uniquely named disposable database. Redis tests delete only the
session keys they create; they never flush a shared database.
"""

import hashlib
import json
import os
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
from psycopg2 import sql
import redis

from app.retrieval.exceptions import InsufficientEvidenceError, ScopeViolationError
from app.retrieval.engine import HybridRetrievalEngine
from app.retrieval.pg_vector_engine import PgVectorHybridEngine
from app.schemas.evidence import EducationalCategory
from app.schemas.memory import TriState
from app.storage.consent import ConsentPolicy
from app.storage.redis_session_store import RedisSessionStore


def _manifest() -> dict:
    """Small synthetic registry; approval flags are test fixtures, not clinical claims."""
    specs = [
        ("global", "Global", "adults_18+", "2027-11-07", False, "approved"),
        ("us", "US", "adults_18+", "2027-11-07", False, "approved"),
        ("minor", "Global", "minors", "2027-11-07", False, "approved"),
        ("expired", "Global", "adults_18+", "2026-11-06", False, "approved"),
        ("boundary", "Global", "adults_18+", "2026-11-07", False, "approved"),
        ("superseded", "Global", "adults_18+", "2027-11-07", True, "approved"),
        ("unverified", "Global", "adults_18+", "2027-11-07", False, "unverified"),
    ]
    sources = []
    passages = []
    for label, jurisdiction, population, expiry, superseded, approval in specs:
        source_id = f"test-{label}"
        passage = {
            "passage_id": f"test-passage-{label}", "source_id": source_id,
            "title": "PCOS synthetic fixture", "url": f"https://example.test/{label}",
            "locator": "Synthetic section 1", "category": "what_it_is",
            "topic_tags": ["pcos", "synthetic"],
            "text": f"PCOS synthetic fixture passage {label}. No clinical claim is made.",
            "reviewed_at": "2026-11-07",
        }
        passages.append(passage)
        sources.append({
            "source_id": source_id, "publisher": "Synthetic test publisher",
            "title": "PCOS synthetic fixture", "canonical_url": passage["url"],
            "publication_date": "2026-11-01", "update_date": None,
            "ingestion_date": "2026-11-07", "review_date": "2026-11-07",
            "expiry_date": expiry, "jurisdiction": jurisdiction,
            "population": population, "life_stage": ["pcos"],
            "evidence_grade": None, "reviewer_id": "synthetic-test-only",
            "license": "synthetic-test-only",
            "content_hash": "sha256:" + hashlib.sha256(passage["text"].encode()).hexdigest(),
            "is_superseded": superseded, "approval_status": approval,
        })
    passages.append({
        **passages[0], "passage_id": "test-passage-symptoms",
        "category": "symptoms", "locator": "Synthetic section 2",
        "text": "PCOS synthetic symptoms fixture. No clinical claim is made.",
    })
    return {"manifest_version": "synthetic-test-1", "sources": sources, "passages": passages}


class TestLivePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admin_url = os.getenv("TEST_POSTGRES_ADMIN_URL")
        if not admin_url:
            raise unittest.SkipTest("TEST_POSTGRES_ADMIN_URL not set; live PostgreSQL tests skipped")
        parsed = urlsplit(admin_url)
        if parsed.scheme not in ("postgresql", "postgres"):
            raise unittest.SkipTest("TEST_POSTGRES_ADMIN_URL must be a PostgreSQL URL")
        cls.db_name = "wha_test_" + uuid.uuid4().hex[:12]
        cls.admin = psycopg2.connect(admin_url, connect_timeout=3)
        cls.admin.autocommit = True
        try:
            with cls.admin.cursor() as cur:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.db_name)))
        except Exception:
            cls.admin.close()
            raise
        cls.database_url = urlunsplit(parsed._replace(path="/" + cls.db_name))
        cls.engine = PgVectorHybridEngine(cls.database_url)
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.manifest_path = Path(cls.tempdir.name) / "synthetic_manifest.json"
        cls.manifest = _manifest()
        cls.manifest_path.write_text(json.dumps(cls.manifest), encoding="utf-8")
        cls.engine.sync_from_manifest(cls.manifest_path)

    @classmethod
    def tearDownClass(cls):
        if not hasattr(cls, "admin"):
            return
        try:
            with cls.admin.cursor() as cur:
                cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (cls.db_name,))
                cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(cls.db_name)))
        finally:
            cls.admin.close()
            cls.tempdir.cleanup()

    def test_retrieval_identity_and_eligibility(self):
        bundle = self.engine.retrieve("What is PCOS?", jurisdiction="US", reference_date=date(2026, 11, 7))
        self.assertEqual(bundle.manifest_version, "synthetic-test-1")
        passage_ids = {item.passage.passage_id for item in bundle.scored_passages}
        self.assertIn("test-passage-global", passage_ids)
        self.assertIn("test-passage-us", passage_ids)
        self.assertIn("test-passage-boundary", passage_ids)
        self.assertFalse(passage_ids.intersection({"test-passage-minor", "test-passage-expired", "test-passage-superseded", "test-passage-unverified"}))
        for scored, citation in zip(bundle.scored_passages, bundle.citations):
            self.assertEqual((scored.passage.passage_id, scored.passage.source_id), (citation.passage_id, citation.source_id))
            self.assertEqual((scored.passage.url, scored.passage.locator), (citation.url, citation.locator))
        symptoms = self.engine.retrieve("PCOS symptoms?", category=EducationalCategory.SYMPTOMS, reference_date=date(2026, 11, 7))
        self.assertEqual({p.passage.passage_id for p in symptoms.scored_passages}, {"test-passage-symptoms"})
        after_boundary = self.engine.retrieve("What is PCOS?", reference_date=date(2026, 11, 8))
        self.assertNotIn("test-passage-boundary", {p.passage.passage_id for p in after_boundary.scored_passages})
        global_only = self.engine.retrieve("What is PCOS?", reference_date=date(2026, 11, 7))
        self.assertNotIn("test-passage-us", {p.passage.passage_id for p in global_only.scored_passages})
        minors = self.engine.retrieve("PCOS", population="minors", reference_date=date(2026, 11, 7))
        self.assertEqual({p.passage.passage_id for p in minors.scored_passages}, {"test-passage-minor"})

    def test_local_and_database_eligibility_agree(self):
        local = HybridRetrievalEngine(manifest_path=self.manifest_path)
        kwargs = {"jurisdiction": "US", "reference_date": date(2026, 11, 7)}
        local_ids = {p.passage.passage_id for p in local.retrieve("What is PCOS?", **kwargs).scored_passages}
        db_ids = {p.passage.passage_id for p in self.engine.retrieve("What is PCOS?", **kwargs).scored_passages}
        self.assertEqual(local_ids, db_ids)
        for engine in (local, self.engine):
            with self.assertRaises(InsufficientEvidenceError):
                engine.retrieve("diesel tractor transmission gearbox", **kwargs)

    def test_relevance_and_punctuation(self):
        with self.assertRaises(InsufficientEvidenceError):
            self.engine.retrieve("diesel tractor transmission gearbox", reference_date=date(2026, 11, 7))
        with self.assertRaises(InsufficientEvidenceError):
            self.engine.retrieve("PCOS?", min_score_threshold=0.99, reference_date=date(2026, 11, 7))
        self.assertTrue(self.engine.retrieve("What??? is PCOS?!", reference_date=date(2026, 11, 7)).citations)
        with self.assertRaises(ScopeViolationError):
            self.engine.retrieve("what are the side effects of taking an ipill?")

    def test_manifest_update_and_removed_rows(self):
        updated = _manifest()
        updated["sources"] = [s for s in updated["sources"] if s["source_id"] != "test-us"]
        updated["passages"] = [p for p in updated["passages"] if p["source_id"] != "test-us"]
        updated["passages"][0]["text"] = "PCOS synthetic fixture passage updated. No clinical claim is made."
        self.manifest_path.write_text(json.dumps(updated), encoding="utf-8")
        self.engine.sync_from_manifest(self.manifest_path)
        with self.engine._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT text FROM clinical_passages WHERE passage_id = 'test-passage-global'")
                self.assertIn("updated", cur.fetchone()[0])
                cur.execute("SELECT count(*) FROM clinical_sources WHERE source_id = 'test-us'")
                self.assertEqual(cur.fetchone()[0], 0)
        # Keep class fixture stable for tests run in any order.
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.engine.sync_from_manifest(self.manifest_path)

    def test_checked_in_manifest_remains_unverified_after_ingestion(self):
        try:
            self.engine.sync_from_manifest(Path("clinical/evidence_manifest/manifest.json"))
            with self.assertRaises(InsufficientEvidenceError):
                self.engine.retrieve("What is PCOS?", reference_date=date(2026, 11, 7))
        finally:
            self.engine.sync_from_manifest(self.manifest_path)

    def test_failure_after_successful_initialization(self):
        self.assertTrue(self.engine.ping())
        original_url = self.engine.database_url
        try:
            self.engine.database_url = "postgresql://postgres:postgres@127.0.0.1:1/unreachable"
            with self.assertRaises(psycopg2.OperationalError):
                self.engine.retrieve("PCOS", reference_date=date(2026, 11, 7))
        finally:
            self.engine.database_url = original_url


class TestLiveRedis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.getenv("TEST_REDIS_URL")
        if not cls.url:
            raise unittest.SkipTest("TEST_REDIS_URL not set; live Redis tests skipped")
        cls.store = RedisSessionStore(redis_url=cls.url)
        if not cls.store.ping():
            raise unittest.SkipTest("TEST_REDIS_URL unavailable; live Redis tests skipped")
        cls.created_ids = []

    @classmethod
    def tearDownClass(cls):
        if not hasattr(cls, "created_ids"):
            return
        for session_id in cls.created_ids:
            cls.store.delete_session(session_id)

    def _create(self, **kwargs):
        session = self.store.create_session(**kwargs)
        self.created_ids.append(session.session_id)
        return session

    def test_create_update_isolation_and_deletion(self):
        first = self._create()
        second = self._create()
        first.context.age = 29
        first.context.is_adult = TriState.YES
        self.store.save_session(first)
        self.assertEqual(self.store.get_session(first.session_id).context.age, 29)
        self.assertIsNone(self.store.get_session(second.session_id).context.age)
        self.assertTrue(self.store.delete_session(first.session_id))
        self.assertIsNone(self.store.get_session(first.session_id))
        self.assertIsNotNone(self.store.get_session(second.session_id))

    def test_expiry_boundary_and_consent_opt_out(self):
        session = self._create(policy=ConsentPolicy(ttl_minutes=1))
        self.assertIsNotNone(self.store.get_session(session.session_id, now=session.expires_at - timedelta(microseconds=1)))
        self.store.save_session(session, now=session.expires_at - timedelta(microseconds=1))
        self.assertIsNone(self.store.get_session(session.session_id, now=session.expires_at))
        opted_out = self._create(policy=ConsentPolicy(allow_minimal_session_context=False))
        opted_out.context.age = 30
        self.store.save_session(opted_out)
        self.assertIsNone(self.store.get_session(opted_out.session_id).context.age)

    def test_failure_after_successful_initialization(self):
        self.assertTrue(self.store.ping())
        original_client = self.store._client
        try:
            self.store._client = redis.Redis.from_url("redis://127.0.0.1:1/15", socket_connect_timeout=1)
            with self.assertRaises(redis.exceptions.RedisError):
                self.store.get_session("sess-synthetic-missing")
        finally:
            self.store._client = original_client


if __name__ == "__main__":
    unittest.main()
