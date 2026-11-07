import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from health_tools.pending_tasks import (
    MAX_TASK_TURNS, advance_cycle_task, new_cycle_task, request_input,
)


class PendingTaskLogicTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        self.task = new_cycle_task("fixture", self.now + timedelta(minutes=30), now=self.now)

    def test_dates_then_reference_then_confirmation(self):
        first = advance_cycle_task(self.task, "2026-08-01 and 2026-09-05", now=self.now)
        self.assertEqual(first.event, "TASK_REFERENCE_REQUESTED")
        second = advance_cycle_task(first.task, "2026-11-07", now=self.now)
        self.assertEqual(second.event, "TASK_CONFIRMATION_REQUESTED")
        self.assertEqual(second.task.period_start_dates, ("2026-08-01", "2026-09-05"))
        self.assertEqual(second.task.as_of, "2026-11-07")
        self.assertEqual(advance_cycle_task(second.task, "confirm", now=self.now).action, "execute")

    def test_combined_input_and_correction_requires_fresh_confirmation(self):
        result = advance_cycle_task(self.task, "2026-08-01, 2026-09-05; as of 2026-11-07", now=self.now)
        self.assertTrue(result.task.awaiting_confirmation)
        corrected = advance_cycle_task(result.task, "2026-08-02, 2026-09-06", now=self.now)
        self.assertEqual(corrected.action, "ask")
        self.assertEqual(corrected.task.period_start_dates, ("2026-08-02", "2026-09-06"))
        self.assertTrue(corrected.task.awaiting_confirmation)

    def test_ambiguous_invalid_duplicate_unordered_and_future_dates_are_not_accepted(self):
        for message in (
            "01/08/2026, 05/09/2026", "2026-02-30, 2026-03-30",
            "2026-08-01, 2026-08-01", "2026-09-05, 2026-08-01",
            "2026-11-08, 2026-12-01 as of 2026-11-07",
            "born 2001-01-01, appointment 2026-09-05",
        ):
            with self.subTest(message=message):
                result = advance_cycle_task(self.task, message, now=self.now)
                self.assertEqual(result.action, "ask")
                self.assertEqual(result.task.period_start_dates, ())
                self.assertFalse(result.task.awaiting_confirmation)

    def test_cancel_expiry_turn_limit_and_topic_change(self):
        self.assertEqual(advance_cycle_task(self.task, "/cancel", now=self.now).event, "TASK_CANCELLED")
        self.assertEqual(advance_cycle_task(self.task, "confirm", now=self.task.expires_at).event, "TASK_EXPIRED")
        full = replace(self.task, turns_used=MAX_TASK_TURNS)
        self.assertEqual(advance_cycle_task(full, "01/02/2026", now=self.now).event, "TASK_TURN_LIMIT")
        self.assertEqual(advance_cycle_task(self.task, "What is PCOS? I am 25.", now=self.now).action, "topic_change")

    def test_premature_confirmation_never_executes(self):
        result = advance_cycle_task(self.task, "yes", now=self.now)
        self.assertEqual(result.action, "ask")
        self.assertFalse(result.task.awaiting_confirmation)

    def test_no_requires_review_before_later_yes(self):
        ready = request_input(replace(self.task, period_start_dates=("2026-08-01", "2026-09-05"), as_of="2026-11-07"))
        rejected = advance_cycle_task(ready.task, "no", now=self.now)
        self.assertFalse(rejected.task.awaiting_confirmation)
        review = advance_cycle_task(rejected.task, "yes", now=self.now)
        self.assertEqual(review.action, "ask")
        self.assertEqual(review.event, "TASK_CONFIRMATION_REQUESTED")

    def test_deadline_is_not_extended_and_is_capped_by_session(self):
        self.assertEqual(self.task.expires_at, self.now + timedelta(minutes=5))
        updated = advance_cycle_task(self.task, "2026-08-01, 2026-09-05", now=self.now + timedelta(minutes=1))
        self.assertEqual(updated.task.expires_at, self.task.expires_at)
        short = new_cycle_task("fixture", self.now + timedelta(minutes=2), now=self.now)
        self.assertEqual(short.expires_at, self.now + timedelta(minutes=2))


if __name__ == "__main__":
    unittest.main()
