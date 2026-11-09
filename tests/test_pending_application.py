import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from app.workflow.service import HealthApplication
from health_tools.pending_tasks import MAX_TASK_TURNS


class PendingApplicationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        self.app = HealthApplication()
        self.sid = None

    def send(self, message, **options):
        inputs = dict(session_id=self.sid, allow_session_context=True, now=self.now)
        inputs.update(options)
        result, session = self.app.process(message, **inputs)
        self.sid = session.session_id
        return result, session

    def propose(self):
        self.send("Calculate cycle intervals")
        return self.send("2026-08-01, 2026-09-05; as of 2026-11-07")

    def test_collect_confirm_calculate_once(self):
        with patch("health_tools.workflow.analyze_cycle_history", wraps=__import__("health_tools").analyze_cycle_history) as calculator:
            first, _ = self.send("Calculate cycle intervals")
            self.assertIn("TASK_DATES_REQUESTED", first.events)
            proposed, session = self.send("2026-08-01, 2026-09-05; as of 2026-11-07")
            self.assertIn("TASK_CONFIRMATION_REQUESTED", proposed.events)
            self.assertIn("2026-08-01", proposed.response["answer"])
            self.assertEqual(session.context.clarification_turns_used, 0)
            calculator.assert_not_called()
            calculated, _ = self.send("confirm")
            self.assertIn("35 days", calculated.response["answer"])
            self.assertIn("TASK_CONFIRMED", calculated.events)
            self.assertEqual(calculator.call_count, 1)
            self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))
            replayed, _ = self.send("confirm")
            self.assertIn("NO_PENDING_TASK", replayed.events)
            self.assertEqual(calculator.call_count, 1)

    def test_correction_is_calculated_only_after_new_confirmation(self):
        self.propose()
        corrected, _ = self.send("2026-08-02, 2026-09-06")
        self.assertIn("TASK_CONFIRMATION_REQUESTED", corrected.events)
        result, _ = self.send("yes")
        self.assertEqual(result.tool_results[0].data["period_start_dates"], ["2026-08-02", "2026-09-06"])

    def test_reference_date_collected_separately(self):
        self.send("Calculate cycle intervals")
        reference, _ = self.send("2026-08-01, 2026-09-05")
        self.assertIn("TASK_REFERENCE_REQUESTED", reference.events)
        confirmation, _ = self.send("2026-11-07")
        self.assertIn("TASK_CONFIRMATION_REQUESTED", confirmation.events)
        result, _ = self.send("confirm")
        self.assertEqual(result.tool_results[0].data["as_of"], "2026-11-07")

    def test_cancel_clears_pending_inputs(self):
        self.propose()
        result, _ = self.send("/cancel")
        self.assertIn("TASK_CANCELLED", result.events)
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))
        result, _ = self.send("yes")
        self.assertIn("NO_PENDING_TASK", result.events)

    def test_topic_change_clears_task_and_answers_current_question(self):
        self.propose()
        result, _ = self.send("What are PCOS symptoms?")
        self.assertTrue(result.response["symptoms"])
        self.assertIn("TASK_TOPIC_CHANGED", result.events)
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))

    def test_urgent_turn_clears_task_before_any_calculation(self):
        self.propose()
        result, _ = self.send("I have severe pelvic pain and fainted.")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))

    def test_opt_out_clears_task_and_no_dates_persist(self):
        self.propose()
        result, session = self.send("confirm", allow_session_context=False)
        self.assertIn("NO_PENDING_TASK", result.events)
        self.assertFalse(session.allow_session_context)
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))
        self.assertEqual(result.tool_results, ())

    def test_forget_clears_task(self):
        self.propose()
        old_id = self.sid
        self.app.forget(old_id)
        self.assertIsNone(self.app.pending_tasks.get(old_id, now=self.now))
        result, _ = self.send("confirm")
        self.assertIn("NO_PENDING_TASK", result.events)
        self.assertNotEqual(self.sid, old_id)

    def test_task_and_session_expiry(self):
        for elapsed in (timedelta(minutes=5), timedelta(hours=1)):
            with self.subTest(elapsed=elapsed):
                self.sid = None
                self.propose()
                self.now += elapsed
                result, _ = self.send("confirm")
                self.assertIn("NO_PENDING_TASK", result.events)
                self.assertEqual(result.tool_results, ())

    def test_sessions_do_not_share_tasks(self):
        self.propose()
        first_id = self.sid
        self.sid = None
        other, _ = self.send("confirm")
        self.assertIn("NO_PENDING_TASK", other.events)
        self.assertIsNotNone(self.app.pending_tasks.get(first_id, now=self.now))

    def test_input_turn_limit_clears_task(self):
        self.send("Calculate cycle intervals")
        for _ in range(MAX_TASK_TURNS):
            result, _ = self.send("01/02/2026")
            self.assertIn("TASK_INPUT_AMBIGUOUS", result.events)
        result, _ = self.send("01/02/2026")
        self.assertIn("TASK_TURN_LIMIT", result.events)
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))

    def test_no_retention_does_not_create_task(self):
        result, _ = self.send("Calculate cycle intervals", allow_session_context=False)
        self.assertIn("Enable session context", result.response["answer"])
        self.assertIsNone(self.app.pending_tasks.get(self.sid, now=self.now))

    def test_pending_storage_failure_never_blocks_urgent_message(self):
        broken = Mock()
        broken.delete.side_effect = RuntimeError("sensitive payload")
        app = HealthApplication(pending_task_store=broken)
        result, _ = app.process("I have severe pelvic pain and fainted.")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertNotIn("sensitive payload", str(result))

    def test_task_storage_outage_blocks_stale_confirmation(self):
        broken = Mock()
        broken.purge_expired.side_effect = RuntimeError("sensitive payload")
        app = HealthApplication(pending_task_store=broken)
        result, session = app.process("Calculate cycle intervals")
        self.assertIn("TASK_STORAGE_UNAVAILABLE", result.events)
        result, _ = app.process("confirm", session_id=session.session_id)
        self.assertIn("TASK_STORAGE_UNAVAILABLE", result.events)
        self.assertEqual(result.tool_results, ())
        self.assertNotIn("sensitive payload", str(result))

    def test_real_interactive_cli_collects_and_confirms_dates(self):
        root = Path(__file__).resolve().parents[1]
        run = subprocess.run([sys.executable, "main.py", "--remember"], cwd=root,
                             input="Calculate cycle intervals\n2026-08-01, 2026-09-05\n2026-11-07\nconfirm\n/quit\n",
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Please confirm", run.stdout)
        self.assertIn("Recorded intervals: 35 days.", run.stdout)


if __name__ == "__main__":
    unittest.main()
