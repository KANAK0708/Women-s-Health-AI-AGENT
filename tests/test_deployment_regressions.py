import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.retrieval.engine import HybridRetrievalEngine
from app.retrieval.exceptions import InsufficientEvidenceError
from app.retrieval.pg_vector_engine import PgVectorHybridEngine, get_retrieval_engine
from app.storage.session_store import EphemeralSessionStore
from app.workflow.service import HealthApplication


class DeploymentRegressions(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_local_factory_and_application_are_strict_by_default(self):
        local = HybridRetrievalEngine()
        factory = get_retrieval_engine(force_in_memory=True)
        for engine in (local, factory):
            self.assertFalse(engine.allow_unverified_for_development)
            with self.assertRaises(InsufficientEvidenceError):
                engine.retrieve("What is PCOS?")
        response, _ = HealthApplication().process("What is PCOS?")
        self.assertEqual(response.response["response_type"], "abstention")
        self.assertEqual(response.response["evidence"], [])
        self.assertIn("do not have matching approved evidence", response.response["answer"])

    def test_explicit_development_evidence_is_visible(self):
        response, _ = HealthApplication(allow_unverified_for_development=True).process("What is PCOS?")
        self.assertEqual(response.response["response_type"], "education")
        self.assertIn("Unverified development fixture evidence", " ".join(response.response["limitations"]))

    def test_string_false_is_not_a_permission(self):
        with self.assertRaises(ValueError):
            HybridRetrievalEngine(allow_unverified_for_development=False).retrieve(
                "PCOS", allow_unverified_for_development="false")

    def test_postgresql_inherits_explicit_policy_and_closes_connection(self):
        for permission in (False, True):
            with self.subTest(permission=permission):
                engine = PgVectorHybridEngine(allow_unverified_for_development=permission)
                engine._schema_ready = True
                conn = Mock()
                cursor = conn.cursor.return_value.__enter__ = Mock(return_value=Mock())
                conn.cursor.return_value.__exit__ = Mock(return_value=False)
                cursor.return_value.fetchall.return_value = []
                engine._get_connection = Mock(return_value=conn)
                with self.assertRaises(InsufficientEvidenceError):
                    engine.retrieve("PCOS")
                self.assertIs(cursor.return_value.execute.call_args.args[1]["allow_unverified"], permission)
                conn.close.assert_called_once()

    def test_service_does_not_use_an_unrelated_main_global_engine(self):
        trap = Mock()
        with patch.dict(sys.modules, {"main": SimpleNamespace(retrieval_engine=trap)}):
            response, _ = HealthApplication(allow_unverified_for_development=True).process("What is PCOS?")
        trap.retrieve.assert_not_called()
        self.assertEqual(response.response["response_type"], "education")

    def test_memory_outage_preserves_urgent_routing(self):
        store = Mock()
        store.get_session.side_effect = RuntimeError("secret connection URL")
        retrieve = Mock()
        app = HealthApplication(store=store, retrieve=retrieve)
        result, _ = app.process("I have severe pelvic pain and fainted.", session_id="fixture")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertNotIn("secret connection URL", str(result))
        retrieve.assert_not_called()

    def test_memory_outage_and_save_failure_fail_closed(self):
        for operation in ("get", "save"):
            with self.subTest(operation=operation):
                store = EphemeralSessionStore()
                _, session = HealthApplication(store=store).process("hello")
                method = "get_session" if operation == "get" else "save_session"
                with patch.object(store, method, side_effect=RuntimeError("secret payload")):
                    result, _ = HealthApplication(store=store).process("hello", session_id=session.session_id)
                self.assertEqual(result.response["response_type"], "abstention")
                self.assertNotIn("secret payload", str(result))

    def test_offline_startup_does_not_require_optional_database_sdks(self):
        code = '''
import os, sys
for key in ('DATABASE_URL', 'REDIS_URL', 'ALLOW_UNVERIFIED_EVIDENCE'):
    os.environ.pop(key, None)
for name in ('redis', 'psycopg2', 'psycopg2.extras', 'pgvector', 'pgvector.psycopg2'):
    sys.modules[name] = None
import main
assert main.application._engine is None
result, _ = main.application.process('hello', allow_session_context=False)
assert 'Hello.' in result.response['answer']
assert main.application._engine is None
'''
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_live_suites_require_test_urls_before_constructing_clients(self):
        from test_live_database_integration import TestLivePostgreSQLIntegration, TestLiveRedisIntegration
        with patch.dict(os.environ, {"DATABASE_URL": "application", "REDIS_URL": "application"}, clear=True):
            for suite in (TestLivePostgreSQLIntegration, TestLiveRedisIntegration):
                with self.assertRaises(unittest.SkipTest):
                    suite.setUpClass()


if __name__ == "__main__":
    unittest.main()
