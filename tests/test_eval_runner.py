import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from evals.run_evals import main, run_benchmark
from evals.rubric.scoring import CaseEvaluationResult, compute_suite_report


class EvaluationRunnerTests(unittest.TestCase):
    def test_empty_suite_does_not_pass(self):
        self.assertFalse(compute_suite_report([]).all_release_gates_pass)

    def test_missing_families_do_not_pass(self):
        report = compute_suite_report([CaseEvaluationResult(
            case_id="fixture", category="in_scope_education", query="fixture", passed=True,
            citations_count=1,
        )])
        self.assertFalse(report.gate_immediate_danger_pass)
        self.assertFalse(report.gate_minor_routing_pass)
        self.assertFalse(report.all_release_gates_pass)

    def test_llm_mode_cannot_silently_run_exact_excerpt_workflow(self):
        with self.assertRaisesRegex(ValueError, "LLM generation is disabled"):
            run_benchmark(enable_llm=True)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["--llm"])
        self.assertEqual(raised.exception.code, 2)

    @patch("evals.run_evals.run_benchmark")
    def test_failure_exit_status(self, benchmark):
        for failed, gates_pass, expected in ((1, True, 1), (0, False, 1), (0, True, 0)):
            with self.subTest(failed=failed, gates_pass=gates_pass):
                benchmark.return_value = (SimpleNamespace(failed_cases=failed, all_release_gates_pass=gates_pass), [])
                self.assertEqual(main([]), expected)


if __name__ == "__main__":
    unittest.main()
