"""Run the research-agent eval suite (development checklist, not clinical validation).

Examples:
  python3 -m evals.run_research_evals --category safety          # fast, no research calls
  python3 -m evals.run_research_evals --only pcos-diagnosis,pmdd
  python3 -m evals.run_research_evals --limit 5 --pause 60
  python3 -m evals.run_research_evals --rescore evals/results/research_run_20261119_170000.json

Research cases call Groq, Gemini, PubMed, Europe PMC, MedlinePlus and web search.
Cases run one at a time with a pause between research cases to stay under free-tier
limits; results are saved after every case, so an interrupted run keeps its progress.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evals.research.scoring import score_case, summarize  # noqa: E402

CASES_PATH = ROOT_DIR / "evals" / "research" / "cases.json"
RESULTS_DIR = ROOT_DIR / "evals" / "results"


def load_cases(path: Path, *, only=None, category=None, limit=None) -> list[dict]:
    cases = json.loads(path.read_text())["cases"]
    if only:
        wanted = set(only)
        unknown = wanted - {c["id"] for c in cases}
        if unknown:
            raise SystemExit(f"Unknown case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in wanted]
    if category:
        cases = [c for c in cases if c["category"] == category]
    return cases[:limit] if limit else cases


def print_table(results: list[dict], summary: dict) -> None:
    print(f"\n{'case':38} {'status':13} {'pass':5} {'cover':6} {'find':5} {'strong':7} {'time':>6}  missing")
    for r in results:
        print(f"{r['id'][:38]:38} {str(r['status'])[:13]:13} {'yes' if r['passed'] else 'NO':5} "
              f"{r.get('coverage', ''):<6} {r.get('findings', ''):<5} {r.get('strong_evidence_share', ''):<7} "
              f"{r['duration_s']:>5}s  {', '.join(r.get('missing', []))}"
              + (f"  [{r['pipeline_failures']} pipeline failures]" if r["pipeline_failures"] else ""))
    print("\n" + "\n".join(f"{k}: {v}" for k, v in summary.items()))


def save(run: dict, path: Path) -> None:
    run["summary"] = summarize(run["results"])
    path.write_text(json.dumps(run, indent=2))
    latest = {k: run[k] for k in ("suite", "started_at", "models", "summary", "results")}
    (RESULTS_DIR / "research_latest.json").write_text(json.dumps(latest, indent=2))


def rescore(path: Path, cases_path: Path) -> dict:
    run = json.loads(path.read_text())
    cases = {c["id"]: c for c in json.loads(cases_path.read_text())["cases"]}
    run["results"] = [score_case(cases[r["id"]], run["reports"][r["id"]], r["duration_s"])
                      for r in run["results"] if r["id"] in cases]
    run["summary"] = summarize(run["results"])
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--only", type=lambda s: [x.strip() for x in s.split(",") if x.strip()])
    parser.add_argument("--category", choices=("research", "safety"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pause", type=float, default=45, help="Seconds between research cases (default 45)")
    parser.add_argument("--rescore", type=Path, help="Re-score a saved research_run_*.json without calling any API")
    args = parser.parse_args()

    if args.rescore:
        run = rescore(args.rescore, args.cases)
        print_table(run["results"], run["summary"])
        return

    from health_tools.research.llm import ResearchLLMUnavailable, build_llms
    from health_tools.research.pipeline import ResearchAgent

    cases = load_cases(args.cases, only=args.only, category=args.category, limit=args.limit)
    try:
        fast, long = build_llms()
    except ResearchLLMUnavailable as exc:
        raise SystemExit(str(exc))
    agent = ResearchAgent(fast, long)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    out_path = RESULTS_DIR / f"research_run_{started:%Y%m%d_%H%M%S}.json"
    run = {"suite": json.loads(args.cases.read_text())["suite_name"], "started_at": started.isoformat(),
           "models": {"plan_and_report": fast.name, "extraction": long.name},
           "results": [], "reports": {}}
    print(f"Running {len(cases)} cases -> {out_path.relative_to(ROOT_DIR)}")

    previous_research = False
    for number, case in enumerate(cases, 1):
        if case["category"] == "research" and previous_research and args.pause > 0:
            time.sleep(args.pause)
        print(f"[{number}/{len(cases)}] {case['id']} ...", flush=True)
        start = time.monotonic()
        try:
            report = agent.run(case["question"]).model_dump(mode="json")
        except Exception as exc:  # Keep going: one crash must not lose the rest of the run.
            report = {"status": "error", "summary": f"{type(exc).__name__}: {exc}", "search_log": [f"run failed: {exc}"]}
        result = score_case(case, report, time.monotonic() - start)
        run["results"].append(result)
        run["reports"][case["id"]] = report
        save(run, out_path)
        print(f"    {'PASS' if result['passed'] else 'FAIL'} status={result['status']}"
              + (f" coverage={result['coverage']} missing={result['missing']}" if case["category"] == "research" else ""),
              flush=True)
        previous_research = case["category"] == "research"

    print_table(run["results"], run["summary"])


if __name__ == "__main__":
    main()
