"""CLI: python3 -m health_tools.research "What helps period pain?" [--json]

Sends the question to Groq/Gemini and search terms to PubMed, Europe PMC,
MedlinePlus, and DuckDuckGo. Do not include personal identifiers.

Check which providers are working:  python3 -m health_tools.research --check
Use one provider only:              RESEARCH_PROVIDERS=groq python3 -m health_tools.research "..."
"""

import argparse
import sys

from .llm import ResearchLLMUnavailable, check_providers
from .pipeline import render_report, research


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?")
    parser.add_argument("--check", action="store_true", help="Send one tiny test request to each provider and exit")
    parser.add_argument("--json", action="store_true", help="Print the structured ResearchReport JSON")
    parser.add_argument("--quiet", action="store_true", help="Do not print progress to stderr")
    args = parser.parse_args()
    if args.check:
        try:
            results = check_providers()
        except ResearchLLMUnavailable as exc:
            sys.exit(str(exc))
        for label, ok, seconds, note in results:
            print(f"{'OK  ' if ok else 'FAIL'} {label:<32} {seconds:5.1f}s  {note}")
        sys.exit(0 if any(ok for _, ok, _, _ in results) else 1)
    if not args.question:
        parser.error("a question is required (or use --check)")
    try:
        progress = None if args.quiet else (lambda message: print(f"... {message}", file=sys.stderr, flush=True))
        report = research(args.question, progress=progress)
    except ResearchLLMUnavailable as exc:
        sys.exit(str(exc))
    print(report.model_dump_json(indent=2) if args.json else render_report(report))


if __name__ == "__main__":
    main()
