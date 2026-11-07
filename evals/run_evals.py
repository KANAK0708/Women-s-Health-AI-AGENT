"""Runner for the supplied development scenarios, not a clinical validation.

Checks expected routing, protocol IDs, and citation shape. These checks do not
establish clinical accuracy, source approval, or readiness for patient use.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evals.rubric.scoring import (

    CaseEvaluationResult,
    SuiteSummaryReport,
    compute_suite_report,
    evaluate_single_case,
)
from main import process_health_query

EVALS_DIR = Path(__file__).resolve().parent
SEED_CASES_PATH = EVALS_DIR / "development" / "seed_cases.json"
RESULTS_DIR = EVALS_DIR / "results"


def run_benchmark(
    *,
    cases_path: Path = SEED_CASES_PATH,
    output_dir: Path = RESULTS_DIR,
    enable_llm: bool = False,
    verbose: bool = False,
) -> tuple[SuiteSummaryReport, list[CaseEvaluationResult]]:
    """Execute the benchmark suite and generate the release gate report."""
    if enable_llm:
        raise ValueError("LLM generation is disabled in the integrated workflow; evaluate exact excerpts instead.")
    if not cases_path.exists():
        raise FileNotFoundError(f"Evaluation cases not found at {cases_path}")

    raw = json.loads(cases_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = raw.get("cases", [])

    results: list[CaseEvaluationResult] = []

    print(f"\n🚀 Running {raw.get('suite_name', 'Evaluation Suite')} ({len(cases)} cases)...")
    print("Mode: deterministic exact excerpts; development checks only, not clinical validation.")
    print("-" * 75)

    for idx, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        query = case["query"]

        t_start = time.perf_counter()
        try:
            # Run without external web search fallback on benchmark to test exact approved manifest & boundaries
            resp, session = process_health_query(
                query,
                enable_llm_generation=enable_llm,
                use_external_search_on_gap=False,
            )
            audit_codes = session.audit_codes
        except Exception as exc:
            from app.schemas.evidence import Disposition, EducationalResponse, ResponseType
            resp = EducationalResponse(
                request_id=f"err-{idx}",
                response_type=ResponseType.ABSTENTION,
                disposition=Disposition.UNABLE_TO_ASSESS,
                topic=query,
                what_it_is="Workflow exception during evaluation.",
                answer=f"Evaluation execution failure: {exc}",
            )
            audit_codes = [f"CRASH_EXCEPTION: {exc}"]

        t_end = time.perf_counter()
        latency_ms = (t_end - t_start) * 1000.0

        eval_res = evaluate_single_case(case, resp, audit_codes, latency_ms)
        results.append(eval_res)

        status_icon = "✅ PASS" if eval_res.passed else "❌ FAIL"
        if verbose or not eval_res.passed:
            print(f"[{idx:02d}/{len(cases):02d}] {status_icon} | {case_id} | {case['category']} ({latency_ms:.1f}ms)")
            if not eval_res.passed:
                for reason in eval_res.failure_reasons:
                    print(f"    ↳ Reason: {reason}")
        else:
            print(f"[{idx:02d}/{len(cases):02d}] {status_icon} | {case_id} | {case['category']}")

    report = compute_suite_report(results)
    _print_summary(report)
    _export_results(report, results, output_dir, suite_metadata={
        "version": raw.get("version"),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "mode": "deterministic_exact_excerpts",
        "limitations": [
            "Provided development labels have not been independently clinically validated here.",
            "Routing and citation-shape checks do not establish medical correctness or source approval.",
        ],
    })
    return report, results


def _print_summary(rep: SuiteSummaryReport) -> None:
    print("\n" + "=" * 75)
    print(" WOMEN'S HEALTH AI AGENT — DEVELOPMENT CHECKS")
    print("=" * 75)
    print(f"Total Cases Evaluated: {rep.total_cases}")
    print(f"Passed: {rep.passed_cases} | Failed: {rep.failed_cases} | Overall Pass Rate: {rep.overall_pass_rate * 100:.1f}%\n")

    def gate_line(name: str, passed: bool, val: float, target: str) -> str:
        icon = "✅ PASS" if passed else "❌ FAIL"
        return f"  [{icon}] {name:<35} : {val * 100:>6.1f}% (Target: {target})"

    print("Configured Development Checks:")
    print(gate_line("Seed urgent-scenario routing", rep.gate_immediate_danger_pass, rep.immediate_danger_sensitivity, "100.0%"))
    print(gate_line("Medication & Policy Guardrails", rep.gate_medication_boundary_pass, rep.medication_boundary_rate, "100.0%"))
    print(gate_line("Minor (Under 18) Scope Routing", rep.gate_minor_routing_pass, rep.minor_routing_rate, "100.0%"))
    print(gate_line("Citation shape (HTTPS / ID)", rep.gate_citation_validity_pass, rep.citation_validity_rate, "100.0%"))
    print(gate_line("Expected education routing", rep.gate_in_scope_education_pass, rep.in_scope_education_rate, ">= 95.0%"))
    print("-" * 75)

    if rep.all_release_gates_pass:
        print("All configured development checks passed. This is not clinical validation or release approval.")
    else:
        print("⚠️ RELEASE GATES BLOCKED. Review failures above before proceeding.")
    print("=" * 75 + "\n")


def _export_results(
    report: SuiteSummaryReport,
    results: list[CaseEvaluationResult],
    output_dir: Path,
    suite_metadata: dict | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    export_payload = {
        "timestamp_utc": timestamp,
        "suite": suite_metadata or {},
        "summary": {
            "total_cases": report.total_cases,
            "passed_cases": report.passed_cases,
            "failed_cases": report.failed_cases,
            "overall_pass_rate": report.overall_pass_rate,
            "gates": {
                "immediate_danger_sensitivity": report.immediate_danger_sensitivity,
                "immediate_danger_passed": report.gate_immediate_danger_pass,
                "medication_boundary_rate": report.medication_boundary_rate,
                "medication_boundary_passed": report.gate_medication_boundary_pass,
                "minor_routing_rate": report.minor_routing_rate,
                "minor_routing_passed": report.gate_minor_routing_pass,
                "citation_validity_rate": report.citation_validity_rate,
                "citation_validity_passed": report.gate_citation_validity_pass,
                "in_scope_education_rate": report.in_scope_education_rate,
                "in_scope_education_passed": report.gate_in_scope_education_pass,
                "all_release_gates_passed": report.all_release_gates_pass,
            },
        },
        "cases": [
            {
                "case_id": r.case_id,
                "category": r.category,
                "query": r.query,
                "passed": r.passed,
                "failure_reasons": r.failure_reasons,
                "actual_response_type": r.actual_response_type,
                "actual_disposition": r.actual_disposition,
                "protocol_id": r.actual_protocol_id,
                "citations_count": r.citations_count,
                "latency_ms": r.latency_ms,
                "audit_codes": r.audit_codes,
            }
            for r in results
        ],
    }

    latest_path = output_dir / "latest_run.json"
    archive_path = output_dir / f"run_{timestamp}.json"

    latest_path.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")
    archive_path.write_text(json.dumps(export_payload, indent=2), encoding="utf-8")
    print(f"Results exported to {latest_path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run 50-case development evaluation suite.")
    parser.add_argument("--llm", action="store_true", help="Enable LLM generation during evaluation.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed per-case logs.")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    if args.llm:
        parser.error("LLM generation is disabled in the integrated workflow.")
    report, _ = run_benchmark(verbose=args.verbose, output_dir=args.output_dir)
    return 0 if report.failed_cases == 0 and report.all_release_gates_pass else 1


if __name__ == "__main__":
    sys.exit(main())
