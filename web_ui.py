"""Interactive Browser Test UI for the Women's Health AI Agent.

Uses Python's standard-library `http.server` (zero external web dependencies)
to serve a local testing dashboard at http://127.0.0.1:8000.
"""

import argparse
import json
import webbrowser
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from app.workflow.service import HealthApplication
from health_tools.research import ResearchAgent, render_report
from health_tools.research.llm import ResearchLLMUnavailable, build_llms
from health_tools.workflow import render_response

HTML_PAGE = (Path(__file__).with_name("web_ui.html")).read_text(encoding="utf-8")

app_instance = HealthApplication(allow_unverified_for_development=True)
_agent = None


def _research_agent() -> ResearchAgent:
    """Build the research agent on first use so the UI starts without API keys."""
    global _agent
    if _agent is None:
        fast, long = build_llms()
        _agent = ResearchAgent(fast, long)
    return _agent


class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return  # Keep terminal output clean

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path in ("/", "/index.html"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/query":
            params = parse_qs(parsed.query)
            query = (params.get("q") or params.get("query") or ["What is PCOS?"])[0]
            app_instance.allow_unverified_for_development = True
            result, session = app_instance.process(query, allow_session_context=False)
            self._send_json({
                "session_id": session.session_id,
                "events": list(result.events),
                "rendered": render_response(result),
                "response": result.response,
            })
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(min(length, 100_000))
        data = json.loads(raw_body.decode("utf-8") or "{}")

        if self.path == "/api/forget":
            sid = data.get("session_id")
            if sid:
                try:
                    app_instance.forget(sid)
                except Exception:
                    pass
            self._send_json({"deleted": True})
            return

        if self.path == "/api/research":
            if data.get("consent") is not True:
                self._send_json({"error": "Research mode needs explicit consent to send the question to external services."},
                                status=HTTPStatus.BAD_REQUEST)
                return
            try:
                report = _research_agent().run(str(data.get("question", "")))
            except ResearchLLMUnavailable as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                return
            except Exception:
                self._send_json({"error": "Research failed unexpectedly. Please try again."},
                                status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"report": report.model_dump(mode="json"), "rendered": render_report(report)})
            return

        if self.path == "/api/query":
            app_instance.allow_unverified_for_development = bool(data.get("development_evidence", True))
            result, session = app_instance.process(
                data.get("query", ""),
                session_id=data.get("session_id"),
                allow_session_context=bool(data.get("allow_session_context", False)),
                period_start_dates=data.get("period_start_dates"),
                as_of=data.get("as_of"),
                allow_external_research=bool(data.get("allow_external_research", False)),
                research_query=data.get("research_query"),
                research_source=data.get("research_source"),
            )
            self._send_json({
                "session_id": session.session_id,
                "events": list(result.events),
                "rendered": render_response(result),
                "response": result.response,
            })
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open browser automatically")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), WebUIHandler)
    print(f"Women's Health AI Agent browser console running at: {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

