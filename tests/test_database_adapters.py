"""Unit tests for the Database Adapters (PostgreSQL + pgvector and Redis).

Verifies:
1. Session store factory gracefully falls back to EphemeralSessionStore when Redis is unreachable.
2. Retrieval engine factory gracefully falls back to HybridRetrievalEngine when PostgreSQL is unreachable.
3. RedisSessionStore ping handles invalid/unreachable hosts cleanly.
4. PgVectorHybridEngine ping handles invalid/unreachable hosts cleanly.
"""

import logging
import unittest

from app.retrieval.pg_vector_engine import PgVectorHybridEngine, get_retrieval_engine
from app.storage.redis_session_store import RedisSessionStore, get_session_store
from app.storage.session_store import EphemeralSessionStore


class TestDatabaseAdapters(unittest.TestCase):
    def setUp(self) -> None:
        # Suppress expected fallback warning logs during negative connectivity tests
        logging.disable(logging.ERROR)

    def tearDown(self) -> None:
        logging.disable(logging.NOTSET)
    def test_session_store_fallback(self) -> None:
        # With an invalid Redis URL, factory must fall back gracefully to EphemeralSessionStore
        store = get_session_store(redis_url="redis://127.0.0.1:9999/0")
        self.assertIsInstance(store, EphemeralSessionStore)

        # Standard operations succeed on the active store
        sess = store.create_session()
        self.assertIsNotNone(sess.session_id)
        fetched = store.get_session(sess.session_id)
        self.assertIsNotNone(fetched)

    def test_retrieval_engine_fallback(self) -> None:
        # With an invalid PostgreSQL URL, factory must fall back to local manifest HybridRetrievalEngine
        engine = get_retrieval_engine(database_url="postgresql://invalid:invalid@127.0.0.1:9999/invalid")
        bundle = engine.retrieve("What is PCOS?")
        self.assertGreaterEqual(len(bundle.scored_passages), 1)
        self.assertGreaterEqual(len(bundle.citations), 1)

    def test_redis_ping_on_unreachable_host(self) -> None:
        store = RedisSessionStore(redis_url="redis://127.0.0.1:9999/0")
        self.assertFalse(store.ping())

    def test_pg_vector_ping_on_unreachable_host(self) -> None:
        engine = PgVectorHybridEngine(database_url="postgresql://invalid:invalid@127.0.0.1:9999/invalid")
        self.assertFalse(engine.ping())


if __name__ == "__main__":
    unittest.main()

