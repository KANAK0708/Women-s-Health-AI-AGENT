"""Test the actual HTTP consent/safety/session boundary without listening sockets."""

import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import web_ui
from test_deep_research_integration import application
from test_web_ui_research import get, request


class WebResearchConsentTests(unittest.TestCase):
    def setUp(self):
        self.app, self.factory, self.agent = application()
        self.patches = [patch.object(web_ui, "app_instance", self.app),
                        patch.object(web_ui, "_research_agent", self.factory),
                        patch.object(web_ui, "_jobs", {}),
                        patch.object(web_ui.threading, "Timer", Mock()),
                        patch.object(web_ui.threading, "Thread", side_effect=lambda *, target, daemon: SimpleNamespace(start=target))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_consent_required_and_truthy_values_do_not_count(self):
        for consent in (None, False, "true", 1):
            status, data = request("POST", "/api/research", {"question": "What is PCOS?", "consent": consent})
            self.assertEqual(status, 400)
        self.factory.assert_not_called()
        self.assertEqual(web_ui._jobs, {})

    def test_offer_then_accept_records_same_session_and_serves_report_once(self):
        status, answer = request("POST", "/api/query", {"query": "What is PCOS?", "allow_session_context": True})
        self.assertEqual(status, 200)
        self.assertTrue(answer["response"]["research_offer"]["available"])
        self.factory.assert_not_called()
        sid = answer["session_id"]
        status, job = request("POST", "/api/research", {"question": answer["response"]["research_offer"]["question"],
                                                       "consent": True, "session_id": sid, "allow_session_context": True})
        self.assertEqual(status, 202)
        self.assertEqual(job["session_id"], sid)
        status, report = get("/api/research/" + job["job_id"])
        self.assertEqual(status, 200)
        self.assertTrue(report["done"])
        self.assertIn("report", report)
        self.assertNotIn("expires", report)
        self.assertIn("RESEARCH_ACCEPTED", self.app.store.get_session(sid).audit_codes)
        self.assertEqual(get("/api/research/" + job["job_id"])[0], 404)

    def test_direct_unsafe_http_request_never_builds_a_model(self):
        status, job = request("POST", "/api/research", {"question": "I am pregnant and bleeding", "consent": True})
        self.assertEqual(status, 202)
        status, data = get("/api/research/" + job["job_id"])
        self.assertEqual(data["report"]["status"], "urgent")
        self.assertFalse(data["report"]["key_findings"])
        self.factory.assert_not_called()

    def test_forget_deletes_session_job_and_prevents_late_publication(self):
        targets = []
        with patch.object(web_ui.threading, "Thread", side_effect=lambda *, target, daemon: SimpleNamespace(start=lambda: targets.append(target))):
            _, job = request("POST", "/api/research", {"question": "What is PCOS?", "consent": True,
                                                      "allow_session_context": True})
        self.assertEqual(len(web_ui._jobs), 1)
        status, data = request("POST", "/api/forget", {"session_id": job["session_id"]})
        self.assertEqual(status, 200)
        self.assertTrue(data["deleted"])
        self.assertEqual(web_ui._jobs, {})
        self.assertIsNone(self.app.store.get_session(job["session_id"]))
        targets[0]()
        self.factory.assert_not_called()
        self.assertEqual(get("/api/research/" + job["job_id"])[0], 404)

    def test_expired_job_cannot_be_read(self):
        web_ui._jobs["expired"] = {"expires": time.monotonic() - 1, "done": True, "events": [], "report": {}}
        self.assertEqual(get("/api/research/expired")[0], 404)
        self.assertNotIn("expired", web_ui._jobs)

    def test_expiry_timer_preserves_remaining_session_lifetime(self):
        _, session = self.app.process("What is PCOS?", allow_session_context=True)
        session.expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        self.app.store.save_session(session)
        with patch.object(web_ui.threading, "Timer") as timer:
            _, job = request("POST", "/api/research", {"question": "What is PCOS?", "consent": True,
                                                      "session_id": session.session_id, "allow_session_context": True})
            seconds, expire = timer.call_args.args
            self.assertLessEqual(seconds, 5)
            self.assertGreater(seconds, 0)
            self.assertTrue(timer.return_value.daemon)
            timer.return_value.start.assert_called_once()
            expire()
        self.assertNotIn(job["job_id"], web_ui._jobs)

    def test_forget_failure_is_reported_honestly_and_job_is_removed(self):
        web_ui._jobs["pending"] = {"expires": time.monotonic() + 30, "session_id": "sid"}
        with patch.object(self.app, "forget", side_effect=RuntimeError("storage down")):
            status, data = request("POST", "/api/forget", {"session_id": "sid"})
        self.assertEqual(status, 503)
        self.assertNotIn("deleted", data)
        self.assertEqual(web_ui._jobs, {})


if __name__ == "__main__":
    unittest.main()
