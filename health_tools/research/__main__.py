"""CLI: python3 -m health_tools.research "What helps period pain?" [--json]

Sends the question to Groq/Gemini and search terms to PubMed, Europe PMC,
MedlinePlus, and DuckDuckGo. Do not include personal identifiers.
"""

import argparse
import sys

from .llm import ResearchLLMUnavailable
from .pipeline import render_report, research


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true", help="Print the structured ResearchReport JSON")
    args = parser.parse_args()
    try:
        report = research(args.question)
    except ResearchLLMUnavailable as exc:
        sys.exit(str(exc))
    print(report.model_dump_json(indent=2) if args.json else render_report(report))


if __name__ == "__main__":
    main()
