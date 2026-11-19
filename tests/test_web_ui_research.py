"""Offline HTTP tests: no model, literature service or listening socket required."""

import io
import json
import os
import unittest
from unittest.mock import patch

import web_ui
from dev.research_demo import STATUSES, demo_report
from health_tools.research.schema import ResearchReport


class FakeSocket:
    def __init__(self, request):
        self.request = io.BytesIO(request)
        self.response = bytearray()

    def makefile(self, mode, *args):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


def get(path):
    connection = FakeSocket(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
    web_ui.WebUIHandler(connection, ("127.0.0.1", 12345), object())
    headers, body = bytes(connection.response).split(b"\r\n\r\n", 1)
    return int(headers.split()[1]), json.loads(body)


class ResearchDemoTests(unittest.TestCase):
    def test_demo_is_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(web_ui, "_research_agent") as agent:
            status, payload = get("/api/research/demo")
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "Not found"})
        agent.assert_not_called()

    def test_demo_requires_exact_opt_in(self):
        for value in ("0", "true", "yes"):
            with self.subTest(value=value), patch.dict(os.environ, {"WEB_UI_DEMO": value}):
                self.assertEqual(get("/api/research/demo")[0], 404)

    def test_enabled_demo_has_schema_valid_reports_without_research(self):
        with patch.dict(os.environ, {"WEB_UI_DEMO": "1"}), \
                patch.object(web_ui, "_research_agent") as agent, \
                patch.object(web_ui, "_start_research_job") as start:
            for state in sorted(STATUSES):
                with self.subTest(status=state):
                    status, payload = get("/api/research/demo?status=" + state)
                    self.assertEqual(status, 200)
                    self.assertTrue(payload["done"])
                    report = ResearchReport.model_validate(payload["report"])
                    self.assertEqual(report.status, state)
                    self.assertIn("Synthetic", report.disclaimer)
                    self.assertTrue(payload["rendered"])
            agent.assert_not_called()
            start.assert_not_called()

    def test_invalid_status_fails_without_starting_a_job(self):
        with patch.dict(os.environ, {"WEB_UI_DEMO": "1"}), \
                patch.object(web_ui, "_start_research_job") as start:
            status, payload = get("/api/research/demo?status=made_up")
        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "Unknown demo status."})
        start.assert_not_called()

    def test_fixture_covers_quotes_conflicts_gaps_and_evidence_tiers(self):
        complete = demo_report()
        self.assertIn("<script>", complete.key_findings[0].quote)
        self.assertIn("<img", complete.key_findings[0].quote)
        self.assertTrue(complete.sources[2].url.startswith("javascript:"))
        self.assertEqual({f.source_type for f in complete.key_findings}, {"guideline", "rct", "research_article"})
        self.assertTrue(complete.conflicts)
        self.assertTrue(complete.gaps)
        self.assertGreater(len(demo_report("partial").gaps), len(complete.gaps))
        self.assertEqual(demo_report("urgent").key_findings, [])
        self.assertEqual(demo_report("urgent").sources, [])


if __name__ == "__main__":
    unittest.main()
