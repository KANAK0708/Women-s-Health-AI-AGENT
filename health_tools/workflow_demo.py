"""Offline software demonstration only. Contains no clinical safety policy."""

import argparse
from types import SimpleNamespace

from .workflow import Orchestrator, SafetyDecision, render_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["education", "cycle", "clarification", "safety"])
    args = parser.parse_args()
    passage = dict(passage_id="demo:p1", source_id="demo:s1", title="SYNTHETIC fixture",
                   url="https://example.org", locator="Demo paragraph", reviewed_at="2026-11-06",
                   category="what_it_is", text="This synthetic passage demonstrates evidence formatting, not medical advice.")
    citation = {key: value for key, value in passage.items() if key not in {"text", "category"}}
    citation["id"] = "e1"
    bundle = SimpleNamespace(manifest_version="demo-v1", citations=[citation],
                             scored_passages=[SimpleNamespace(passage=passage)])
    # This stub is intentionally confined to the explicit demonstration entry point.
    safety = lambda query, context: SafetyDecision("proceed")
    if args.scenario == "safety":
        safety = lambda query, context: SafetyDecision("unable_to_assess", "Demonstration: safety policy stopped the workflow.")
    workflow = Orchestrator(safety_check=safety, retrieve=lambda *a, **k: bundle)
    query = "What is PCOS?"
    options = {}
    if args.scenario in {"cycle", "clarification"}:
        query = "Calculate my cycle intervals"
    if args.scenario == "cycle":
        options = dict(period_start_dates=["2026-08-01", "2026-09-05", "2026-10-08"], as_of="2026-11-06")
    result = workflow.run(query, **options)
    print("DEVELOPMENT DEMO — synthetic fixtures; no clinical safety assessment.\n")
    print(render_response(result))
    print("\nWorkflow events: " + ", ".join(result.events))


if __name__ == "__main__":
    main()
