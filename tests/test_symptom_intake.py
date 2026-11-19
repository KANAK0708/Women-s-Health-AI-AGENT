import unittest

from app.storage.session_store import EphemeralSessionStore
from app.workflow.service import HealthApplication
from health_tools.conversation import conversational_reply
from health_tools.symptom_intake import detect_complaint, read_slot


class DetectionTests(unittest.TestCase):
    def test_personal_symptom_reports_start_an_intake(self):
        for text, complaint in [
            ("why am i getting stomach pain idk why it is paining", "pain"),
            ("it is not my period phase but still my stomach is paining", "pain"),
            ("I have been bleeding between periods", "bleeding"),
            ("my period is late by 2 weeks", "cycle"),
            ("I get itching and white discharge", "discharge"),
            ("I feel bloated and nauseous every morning", "general"),
        ]:
            self.assertEqual(detect_complaint(text), complaint, text)

    def test_information_questions_do_not(self):
        for text in ("When should I see a doctor for postmenopausal bleeding?", "what are the symptoms of PCOS",
                     "can I take ibuprofen for cramps?", "how do I know if I have endometriosis?", "tell me about period pain"):
            self.assertIsNone(detect_complaint(text), text)

    def test_reading_answers(self):
        self.assertEqual(read_slot("cycle_timing", "it is not my period phase but it hurts", asked=True), "not related to periods")
        self.assertEqual(read_slot("location", "lower belly, a bit more on the right", asked=True), "lower belly, right side")
        self.assertEqual(read_slot("severity", "maybe 7", asked=True), "7/10")
        self.assertIsNone(read_slot("severity", "maybe 7", asked=False))  # a bare number only counts as an answer to that question
        self.assertEqual(read_slot("duration", "since 3 days", asked=True), "3 days")
        self.assertEqual(read_slot("other_symptoms", "bloating, no fever", asked=True), "bloating")
        self.assertEqual(read_slot("other_symptoms", "none", asked=True), "none")
        self.assertEqual(read_slot("pregnancy", "not sure", asked=True), "not sure")
        self.assertEqual(read_slot("pregnancy", "no", asked=True), "no")


class ConversationTests(unittest.TestCase):
    def test_identity_and_capabilities(self):
        self.assertIn("women's health education assistant", conversational_reply("who are you?"))
        self.assertIn("not a doctor", conversational_reply("are you a doctor"))
        self.assertIn("Here's what I can help with", conversational_reply("what can you do?"))
        self.assertIsNone(conversational_reply("what is PCOS?"))


class IntakeFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = HealthApplication(store=EphemeralSessionStore(), retrieve=lambda *a, **k: None)
        self.sid = None

    def say(self, text, *, remember=True):
        result, session = self.app.process(text, session_id=self.sid, allow_session_context=remember)
        self.sid = session.session_id
        return result

    def test_full_intake_ends_in_a_summary_and_sets_topic(self):
        self.assertIn("INTAKE_STARTED", self.say("why am I getting stomach pain").events)
        for answer in ("lower belly, left side", "not related to my period", "3 days", "5", "bloating, no fever"):
            self.assertEqual(self.say(answer).response["response_type"], "clarification", answer)
        final = self.say("no")
        self.assertIn("INTAKE_SUMMARY", final.events)
        self.assertIn("here's what you've told me", final.response["answer"])
        self.assertIn("When to get help", final.response["answer"])
        self.assertEqual(final.response["disposition"], "routine_review")

    def test_details_in_the_first_message_are_not_asked_again(self):
        result = self.say("I have lower right belly pain for 2 days, not related to my period")
        self.assertIn("0 to 10", result.response["answer"])  # skips location, timing and duration

    def test_red_flag_ends_the_intake_with_urgent_guidance(self):
        self.say("my lower belly is hurting")
        self.say("right side")
        result = self.say("I have a fever and I'm vomiting")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertEqual(result.response["protocol_id"], "PROTO-INTAKE-RED-FLAG-01")
        self.assertIn("appendicitis", result.response["answer"])

    def test_pain_with_possible_pregnancy_is_urgent(self):
        self.say("my stomach is paining")
        for answer in ("lower belly", "not related", "today", "4", "none"):
            self.say(answer)
        self.assertEqual(self.say("maybe").response["response_type"], "urgent_guidance")

    def test_existing_safety_rules_still_win(self):
        self.say("my stomach is paining")
        result = self.say("I'm pregnant and fainted with severe pelvic pain")
        self.assertEqual(result.response["response_type"], "urgent_guidance")
        self.assertNotIn("INTAKE_QUESTION", result.events)

    def test_cancel_and_topic_change(self):
        self.say("my stomach is paining")
        self.assertIn("INTAKE_CANCELLED", self.say("never mind").events)
        self.say("my stomach is paining")
        result = self.say("what is PCOS?")
        self.assertNotIn("INTAKE_QUESTION", result.events)
        self.assertNotIn("INTAKE_REASKED", result.events)

    def test_small_talk_keeps_the_intake_going(self):
        self.say("my stomach is paining")
        result = self.say("thanks")
        self.assertIn("To keep going", result.response["answer"])
        self.assertIn("INTAKE_QUESTION", self.say("lower belly").events)

    def test_memory_off_asks_everything_at_once(self):
        result = self.say("my stomach is paining", remember=False)
        self.assertIn("INTAKE_SINGLE_TURN", result.events)
        self.assertIn("Session memory is off", result.response["answer"])

    def test_forget_deletes_the_intake(self):
        self.say("my stomach is paining")
        self.app.forget(self.sid)
        self.assertIsNone(self.app.intakes.get(self.sid, now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))


if __name__ == "__main__":
    unittest.main()
