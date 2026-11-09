import json
import unittest

from health_tools import EvidenceSource, ToolError, ToolResult, analyze_cycle_history


class CycleHistoryTests(unittest.TestCase):
    def calculate(self, dates):
        return analyze_cycle_history(dates, as_of="2026-11-06")

    def test_known_intervals_and_elapsed_time(self):
        result = self.calculate(["2026-08-01", "2026-09-05", "2026-10-08"])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["cycle_lengths_days"], [35, 33])
        self.assertEqual(result.data["mean_cycle_length_days"], 34)
        self.assertEqual(result.data["median_cycle_length_days"], 34)
        self.assertEqual(result.data["interval_range_days"], 2)
        self.assertEqual(result.data["days_since_last_recorded_start"], 29)
        self.assertEqual(result.data["completed_interval_count"], 2)

    def test_leap_year(self):
        result = self.calculate(["2024-02-01", "2024-03-01"])
        self.assertEqual(result.data["cycle_lengths_days"], [29])

    def test_year_boundary(self):
        result = self.calculate(["2025-12-20", "2026-01-20"])
        self.assertEqual(result.data["cycle_lengths_days"], [31])

    def test_empty_and_single_start_do_not_invent_cycle(self):
        for dates in ([], ["2026-11-06"]):
            with self.subTest(dates=dates):
                result = self.calculate(dates)
                self.assertEqual(result.status, "insufficient_data")
                self.assertIsNone(result.data["mean_cycle_length_days"])
                self.assertEqual(result.data["cycle_lengths_days"], [])

    def test_invalid_inputs(self):
        cases = [
            ("2026-01-01", "invalid_input"),
            ([None], "invalid_date"),
            (["2026-02-29"], "invalid_date"),
            (["20260101"], "invalid_date"),
            (["2026-1-01"], "invalid_date"),
            (["2026-01-01", "2026-01-01"], "duplicate_dates"),
            (["2026-02-01", "2026-01-01"], "unordered_dates"),
            (["2026-11-07"], "future_date"),
            (["2026-01-01"] * 367, "too_many_entries"),
        ]
        for dates, code in cases:
            with self.subTest(code=code, dates=str(dates)[:60]):
                result = self.calculate(dates)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.error.code, code)
                self.assertEqual(result.data, {})

    def test_invalid_reference_date(self):
        for value in ("bad", "2026-02-30", 123):
            self.assertEqual(
                analyze_cycle_history([], as_of=value).error.code, "invalid_as_of"
            )

    def test_input_is_not_mutated(self):
        dates = ["2026-02-01", "2026-01-01"]
        self.calculate(dates)
        self.assertEqual(dates, ["2026-02-01", "2026-01-01"])


class ContractTests(unittest.TestCase):
    def test_json_round_trip_with_source(self):
        source = EvidenceSource(
            source_id="example:1", title="Example", url="https://example.org",
            publisher="Example", retrieved_at="2026-11-06T00:00:00Z", excerpt="Text",
        )
        result = ToolResult(tool="example", status="ok", sources=(source,))
        decoded = json.loads(json.dumps(result.to_dict()))
        self.assertEqual(decoded["sources"][0]["source_id"], "example:1")
        self.assertEqual(decoded["schema_version"], "1.0")

    def test_errors_are_explicit(self):
        for kwargs in (
            {"status": "error"},
            {"status": "ok", "error": ToolError("failure", "Failed")},
            {"status": "unknown"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ToolResult(tool="example", **kwargs)


if __name__ == "__main__":
    unittest.main()
