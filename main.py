"""Integrated development CLI for PCOS and menstrual-health education.

Uses the existing memory/retrieval subsystem and the tools-side orchestrator.
No LLM generation or automatic external-search fallback is enabled.
"""

import argparse
import json

from app.schemas.evidence import EducationalResponse
from app.workflow.service import HealthApplication
from health_tools.workflow import render_response

application = HealthApplication()
# Preserve these names for existing callers using the teammate's session store.
session_store = application.store


def process_health_query(
    query: str, *, session_id=None, use_external_search_on_gap=False,
    enable_llm_generation=False, allow_session_context=None, **tool_inputs,
):
    """Compatibility API returning (EducationalResponse, SessionMemory).

    Legacy LLM/search flags are retained for call compatibility only: this path
    always uses exact excerpts and explicit research authorization. Programmatic
    callers should supply allow_session_context explicitly; None preserves the
    existing store policy. The CLI always supplies an explicit choice.
    """
    result, session = application.process(
        query, session_id=session_id, allow_session_context=allow_session_context,
        **tool_inputs,
    )
    return EducationalResponse.model_validate(result.response), session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", "-q", help="One question; omit for interactive mode")
    parser.add_argument("--period-starts", nargs="+", help="Confirmed starts, oldest first, YYYY-MM-DD")
    parser.add_argument("--as-of", help="Local reference date for cycle arithmetic, YYYY-MM-DD")
    parser.add_argument("--remember", action="store_true", help="Retain minimal context in this process until expiry/deletion")
    parser.add_argument("--allow-external-research", action="store_true", help="Authorize sending separately supplied research terms to NCBI")
    parser.add_argument("--research-query", help="Research terms without personal identifiers")
    parser.add_argument("--jurisdiction", default="Global")
    parser.add_argument("--json", action="store_true", help="Print the structured EducationalResponse")
    args = parser.parse_args()
    options = dict(
        allow_session_context=args.remember,
        period_start_dates=args.period_starts, as_of=args.as_of,
        jurisdiction=args.jurisdiction, allow_external_research=args.allow_external_research,
        research_query=args.research_query,
    )
    if not args.json:
        print("Development build: evidence-review metadata and safety rules need clinical verification.")
    session_id = None
    interactive = args.query is None
    if interactive:
        print("PCOS and period-health assistant. /quit to exit; /forget to delete session context; /cancel to cancel a pending calculation.")
        print("Session context retention: " + ("on" if args.remember else "off"))
    try:
        while True:
            try:
                query = input("You: ").strip() if interactive else args.query
            except (EOFError, KeyboardInterrupt):
                break
            if interactive and query == "/quit":
                break
            if interactive and query == "/forget":
                if session_id:
                    application.forget(session_id)
                session_id = None
                print("Session context deleted.")
                continue
            result, session = application.process(query, session_id=session_id, **options)
            session_id = session.session_id
            if interactive:
                # Command-line task inputs belong to the first turn only.
                options["period_start_dates"] = None
                options["as_of"] = None
            if args.json:
                print(json.dumps(result.response, indent=2))
            else:
                print(render_response(result))
            if not interactive:
                break
    finally:
        if session_id:
            application.forget(session_id)


if __name__ == "__main__":
    main()
