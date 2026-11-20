"""Guided symptom intake: ask one question at a time until the problem is clear.

Pure conversation logic: no storage, no model calls, nothing sent anywhere.
The service stores the intake state between turns (when session context is on)
and runs its normal safety checks on every message before this code runs.

DEVELOPMENT CONTENT — REQUIRES CLINICIAN REVIEW. The red-flag rules in
`red_flags()` and the wording in `_POSSIBILITIES` / `_SEEK_CARE` are a
development baseline written without clinical review. They are educational,
never a diagnosis, and must be reviewed before real users rely on them.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import datetime

MAX_INTAKE_TURNS = 8
SCHEMA_VERSION = "intake-1.0"

# ---- detecting a personal symptom report ------------------------------------

# Someone describing what they are experiencing, not asking a general question
# ("when should I see a doctor for X?" is information-seeking, not a report).
_FIRST_PERSON = re.compile(
    r"\bi\s*(?:'?m|am|'?ve|have)?\s*(?:been\s+)?(?:having|getting|feeling|bleeding|spotting|in pain|hurting|cramping|"
    r"noticing|noticed|suffering|dealing with|experiencing)\b|"
    r"\bi\s+(?:have|had|get|got|keep|feel|felt|notice|noticed|started|still have)\b|\bi'?ve\s+(?:got|had|been|noticed)\b|"
    r"\bwhy\s+(?:am|do|did|does|is|are)\s+(?:i|my)\b|\bwhat'?s\s+(?:wrong|happening|going on)\s+with\s+(?:me|my)\b|"
    r"\bmy\s+[\w-]+(?:\s+[\w-]+)?\s+(?:is|are|has|have|keeps?|feels?|hurts?|started|won'?t|isn'?t|aren'?t|was)\b|"
    r"\b(?:hurts|paining|aching)\s+(?:me|my)\b|\bmy\s+(?:stomach|belly|tummy|back|period|periods|cycle)\b",
    re.I,
)
_COMPLAINTS: list[tuple[str, re.Pattern[str]]] = [
    ("bleeding", re.compile(r"\b(?:bleed\w*|spotting|blood(?:y)?|clots?)\b", re.I)),
    ("pain", re.compile(r"\b(?:pain\w*|aches?|aching|achy|hurts?|hurting|cramp\w*|sore(?:ness)?|stabbing|throbbing)\b", re.I)),
    ("cycle", re.compile(r"\b(?:missed (?:my |a )?periods?|late periods?|periods? (?:is |are )?(?:late|irregular|stopped|missing)|"
                         r"no periods?|irregular periods?|haven'?t (?:had|got|gotten) (?:my |a )?period)\b", re.I)),
    ("discharge", re.compile(r"\b(?:discharge|itch\w*|vaginal (?:smell|odou?r)|smells? (?:bad|fishy)|fishy)\b", re.I)),
    ("general", re.compile(r"\b(?:bloat\w*|nause\w*|vomit\w*|dizz\w*|exhausted|fatigue|tired all the time|hot flash\w*|night sweats|mood swings)\b", re.I)),
]
# Educational questions ("what are the symptoms of PCOS?") are not personal reports.
_EDUCATIONAL = re.compile(r"^\s*(?:what|how|why) (?:is|are|does|do|can) (?:pcos|pcod|endometriosis|pms|pmdd|fibroids|menopause|perimenopause|a period|periods)\b|"
                          r"\bsymptoms of\b|\bsigns of\b|\btell me about\b|\bexplain\b|"
                          # "diagnose me with PCOS": answered with non-diagnostic education about the named condition.
                          r"\bdiagnos\w*\b.{0,30}\b(?:pcos|pcod|endometriosis|pmdd|fibroids|adenomyosis|menopause|perimenopause)\b", re.I)


def detect_complaint(message: str) -> str | None:
    """Return the complaint type when someone describes their own symptoms."""
    if not isinstance(message, str) or not _FIRST_PERSON.search(message) or _EDUCATIONAL.search(message):
        return None
    for complaint, pattern in _COMPLAINTS:
        if pattern.search(message):
            return complaint
    return None


# ---- slots: what we ask, and how we read answers ----------------------------

_PREGNANCY_Q = "Is there any chance you could be pregnant? (yes, no, or not sure)"
_OTHER_Q = ("Have you noticed anything else with it — fever, vomiting, burning when you pee, unusual discharge, "
            "bleeding, or feeling dizzy? It's fine to say none.")

QUESTIONS: dict[str, str] = {
    "location": "Where exactly is the pain — lower belly, upper belly, one side (left or right), your back, or all over?",
    "cycle_timing": "Does it seem linked to your cycle — before your period, during it, mid-cycle, or not related to your period at all?",
    "duration": "How long has this been going on — since today, a few days, weeks, or longer? Does it come and go?",
    "severity": "On a scale of 0 to 10, how bad is it at its worst? (0 is no pain, 10 is the worst you can imagine)",
    "pregnancy": _PREGNANCY_Q,
    "other_symptoms": _OTHER_Q,
    "bleeding_timing": "When does the bleeding happen — between periods, after sex, after menopause, or is your period heavier or longer than usual?",
    "amount": "How heavy is it — light spotting, like a normal period, or soaking through a pad or tampon every hour or two?",
    "last_period": "When did your last period start, roughly? (for example 'about 6 weeks ago')",
    "usual_cycle": "Are your periods usually regular, or have they always varied?",
    "discharge_desc": "Can you describe it — colour, smell, and whether there's itching or burning?",
}

PLANS: dict[str, tuple[str, ...]] = {
    "pain": ("location", "cycle_timing", "duration", "severity", "other_symptoms", "pregnancy"),
    "bleeding": ("bleeding_timing", "amount", "duration", "pregnancy", "other_symptoms"),
    "cycle": ("last_period", "usual_cycle", "pregnancy", "other_symptoms"),
    "discharge": ("discharge_desc", "duration", "other_symptoms", "pregnancy"),
    "general": ("duration", "cycle_timing", "severity", "other_symptoms", "pregnancy"),
}

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "a": 1, "an": 1, "a couple of": 2, "couple of": 2, "a few": 3, "few": 3}
_UNSURE = re.compile(r"^\s*(?:i\s+)?(?:don'?t know|dont know|not sure|unsure|no idea|idk|skip|pass|maybe not sure)\b", re.I)
_NONE = re.compile(r"^\s*(?:no(?:ne|pe|thing)?(?: else)?|not really|nothing else|no other symptoms|nah)\b[\s.!]*$", re.I)


def _location(text: str) -> str | None:
    t = text.casefold()
    parts = []
    if re.search(r"\b(?:lower|bottom|pelvi\w*|below (?:my )?(?:belly button|navel)|groin|down there|under (?:my )?belly)\b", t):
        parts.append("lower belly")
    elif re.search(r"\b(?:upper|top of|above (?:my )?(?:belly button|navel)|under (?:my )?ribs|stomach area|chest)\b", t):
        parts.append("upper belly")
    if re.search(r"\bright\b", t):
        parts.append("right side")
    elif re.search(r"\bleft\b", t):
        parts.append("left side")
    if re.search(r"\b(?:lower )?back\b", t):
        parts.append("back")
    if re.search(r"\b(?:all over|whole (?:belly|stomach|abdomen)|everywhere|middle|around (?:my )?(?:belly button|navel)|center|centre)\b", t):
        parts.append("all over / centre")
    return ", ".join(parts) or None


def _cycle_timing(text: str) -> str | None:
    t = text.casefold()
    if re.search(r"\bnot (?:my |during |in (?:my )?)?(?:period|periods)\b|not (?:related|linked|connected)|no (?:link|relation)|"
                 r"\bnot\b.*\bperiod (?:phase|time)\b|random(?:ly)?|any ?time|doesn'?t (?:seem )?(?:match|follow)|unrelated", t):
        return "not related to periods"
    if re.search(r"\bmid[- ]?cycle|middle of (?:my )?cycle|ovulat\w*|between periods", t):
        return "mid-cycle"
    if re.search(r"\bbefore (?:my |the )?period|premenstrual|week before|days before", t):
        return "before periods"
    if re.search(r"\b(?:during|on|with) (?:my |the )?period|when i(?:'m| am)? (?:on )?(?:my )?period|period (?:pain|cramps)", t):
        return "during periods"
    if re.search(r"\bafter (?:my |the )?period", t):
        return "after periods"
    if re.search(r"\bno periods?\b|menopause|don'?t have periods", t):
        return "no periods / after menopause"
    return None


def _duration(text: str) -> str | None:
    t = text.casefold()
    m = re.search(r"\b(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|a couple of|couple of|a few|few|an?)\s*(hour|day|week|month|year)s?\b", t)
    if m:
        n, unit = m.group(1), m.group(2)
        value = int(n) if n.isdigit() else _NUMBER_WORDS.get(n, n)
        return f"{value} {unit}{'' if value == 1 else 's'}"
    if re.search(r"\b(?:today|this morning|tonight|this evening|just started|few hours|an hour ago)\b", t):
        return "started today"
    if re.search(r"\b(?:yesterday|last night)\b", t):
        return "since yesterday"
    if re.search(r"\b(?:long time|ages|for months|for years|always|on and off|comes and goes|keeps coming back)\b", t):
        return "long-standing or recurring"
    return None


def _severity(text: str, *, asked: bool) -> str | None:
    t = text.casefold()
    m = re.search(r"\b(10|[0-9])\s*(?:/|out of)\s*10\b", t) or (re.fullmatch(r"\D*\b(10|[0-9])\b\D*", t) if asked else None)
    if m:
        return f"{m.group(1)}/10"
    for words, label in ((r"unbearable|worst (?:pain )?(?:ever|of my life)|excruciating|can'?t (?:stand|move|walk)", "very severe"),
                         (r"\bsevere|really bad|very bad|terrible|intense", "severe"),
                         (r"\bmoderate|medium|quite bad|pretty bad", "moderate"),
                         (r"\bmild|slight|a little|not (?:that|too) bad|manageable|dull", "mild")):
        if re.search(words, t):
            return label
    return None


def _pregnancy(text: str, *, asked: bool) -> str | None:
    t = text.casefold().strip()
    if re.search(r"\b(?:i'?m|i am|currently) pregnant\b|positive (?:pregnancy )?test", t):
        return "yes"
    if re.search(r"\b(?:not pregnant|no chance|can'?t be pregnant|negative (?:pregnancy )?test|not sexually active|"
                 r"haven'?t had sex|post-?menopaus\w*|had a hysterectomy)\b", t):
        return "no"
    if re.search(r"\b(?:might be|could be|maybe|possibl\w*|not sure|unsure|don'?t know|late period)\b", t) and (asked or "pregnan" in t):
        return "possible"
    if asked and re.fullmatch(r"(?:yes|yeah|yep|y)\W*", t):
        return "yes"
    if asked and re.fullmatch(r"(?:no|nope|nah|n)\W*", t):
        return "no"
    return None


_OTHER = [
    ("fever", r"\bfever\w*|high temperature|chills"),
    ("vomiting", r"\bvomit\w*|throwing up|threw up|can'?t keep (?:anything|food|water) down"),
    ("nausea", r"\bnause\w*|feel(?:ing)? sick"),
    ("burning when peeing", r"burn\w* (?:when|while) (?:i )?(?:pee|urinat\w*)|pain(?:ful)? (?:when|while) (?:i )?(?:pee|urinat\w*)|peeing (?:a lot|often)"),
    ("unusual discharge", r"\bdischarge"),
    ("bleeding", r"\bbleed\w*|spotting"),
    ("dizziness or fainting", r"\bdizz\w*|faint\w*|light-?headed|passed out"),
    ("diarrhoea or constipation", r"\bdiarr?h\w*|constipat\w*|loose stools?"),
    ("bloating", r"\bbloat\w*"),
    ("pain during sex", r"pain(?:ful)? (?:during|with|after) sex|dyspareunia"),
]


def _other_symptoms(text: str, *, asked: bool) -> str | None:
    t = text.casefold()
    found = [label for label, pattern in _OTHER if re.search(pattern, t)]
    # "no fever" mentions a symptom only to deny it.
    found = [label for label in found if not re.search(r"\bno\s+" + re.escape(label.split()[0]), t)]
    if found:
        return ", ".join(found)
    if asked and _NONE.search(t):
        return "none"
    return None


def _bleeding_timing(text: str) -> str | None:
    t = text.casefold()
    if re.search(r"after (?:having )?sex|after intercourse", t):
        return "after sex"
    if re.search(r"after (?:the )?menopause|post-?menopaus\w*|haven'?t had a period (?:for|in) (?:a )?year", t):
        return "after menopause"
    if re.search(r"between (?:my )?periods|mid[- ]?cycle|spotting", t):
        return "between periods"
    if re.search(r"heav(?:y|ier)|longer|lasts? (?:more than|over) (?:a )?week", t):
        return "heavier or longer periods"
    return None


def _amount(text: str) -> str | None:
    t = text.casefold()
    if re.search(r"soak\w*|every hour|every 1|clots? (?:the size|bigger|large)|gushing|flooding|through (?:my )?clothes", t):
        return "very heavy (soaking pads or tampons)"
    if re.search(r"spot\w*|light|a little|few drops|brown", t):
        return "light / spotting"
    if re.search(r"normal|like a period|moderate|medium", t):
        return "like a normal period"
    return None


def _last_period(text: str) -> str | None:
    duration = _duration(text)
    if duration and re.search(r"ago|back|since|last", text, re.I):
        return duration + " ago"
    m = re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b", text)
    return m.group(0) if m else None


def _usual_cycle(text: str) -> str | None:
    t = text.casefold()
    if re.search(r"\birregular|always varied|never regular|all over the place|unpredictable", t):
        return "usually irregular"
    if re.search(r"\bregular|like clockwork|every month|on time", t):
        return "usually regular"
    return None


def _free_text(text: str) -> str | None:
    cleaned = " ".join(text.split())
    return cleaned[:120] if 0 < len(cleaned) <= 300 else None


def read_slot(slot: str, text: str, *, asked: bool) -> str | None:
    """Read one slot from a message. `asked` means this was the question just asked."""
    if asked and _UNSURE.search(text):
        return "not sure"
    readers = {
        "location": lambda: _location(text),
        "cycle_timing": lambda: _cycle_timing(text),
        "duration": lambda: _duration(text),
        "severity": lambda: _severity(text, asked=asked),
        "pregnancy": lambda: _pregnancy(text, asked=asked),
        "other_symptoms": lambda: _other_symptoms(text, asked=asked),
        "bleeding_timing": lambda: _bleeding_timing(text),
        "amount": lambda: _amount(text),
        "last_period": lambda: _last_period(text),
        "usual_cycle": lambda: _usual_cycle(text),
        "discharge_desc": lambda: _free_text(text) if asked else None,
    }
    value = readers[slot]()
    if (value is None and asked and slot in {"location", "bleeding_timing", "amount", "last_period", "usual_cycle"}
            and not _looks_like_question(text)):
        value = _free_text(text)  # Accept their own words for descriptive questions, but never a new question.
    return value


def _looks_like_question(text: str) -> bool:
    return bool(re.search(r"\?\s*$", text) or re.match(
        r"\s*(?:what|how|why|when|where|who|which|can|could|is|are|does|do|should|tell me|explain)\b", text, re.I))


# ---- state and transitions ---------------------------------------------------

@dataclass(frozen=True)
class SymptomIntake:
    session_id: str
    expires_at: datetime
    complaint: str
    answers: tuple[tuple[str, str], ...] = ()
    asking: str | None = None
    turns_used: int = 0
    first_message: str = ""
    schema_version: str = SCHEMA_VERSION

    @property
    def answer_map(self) -> dict[str, str]:
        return dict(self.answers)

    def with_answers(self, updates: dict[str, str]) -> "SymptomIntake":
        merged = {**self.answer_map, **updates}
        return replace(self, answers=tuple(merged.items()))


@dataclass(frozen=True)
class IntakeTransition:
    action: str  # ask | summary | urgent | cancel | topic_change
    intake: SymptomIntake | None = None
    message: str = ""
    event: str = ""
    protocol_id: str | None = None
    topic: str = ""
    next_steps: tuple[str, ...] = field(default_factory=tuple)


_CANCEL = re.compile(r"^\s*(?:/?cancel|stop|never ?mind|forget it|leave it|i'?m fine now|it'?s fine now)\b", re.I)
_NEW_QUESTION = re.compile(r"^\s*(?:what|how|why|when|can|could|is|are|does|do|should|tell me|explain)\b.*\?\s*$|^\s*(?:tell me about|explain)\b", re.I)

_ACKS = ["Got it.", "Thanks, that helps.", "Okay, thank you.", "Thanks for telling me.", "Understood."]
_OPENERS = {
    "pain": "I'm sorry you're dealing with that pain — let's work out what's going on together. I'll ask a few quick questions.",
    "bleeding": "Thanks for telling me — unexpected bleeding is worth understanding properly. I'll ask a few quick questions.",
    "cycle": "Changes in your cycle can be worrying — let's look at it together. I'll ask a few quick questions.",
    "discharge": "That sounds uncomfortable — let's figure out what might be going on. I'll ask a few quick questions.",
    "general": "I'm sorry you're not feeling well — let's work out what's going on. I'll ask a few quick questions.",
}


def _missing(intake: SymptomIntake) -> list[str]:
    have = intake.answer_map
    return [slot for slot in PLANS[intake.complaint] if slot not in have]


def _prefill(intake: SymptomIntake, text: str, *, asked_slot: str | None) -> SymptomIntake:
    """Fill every slot the message answers, including ones not asked yet."""
    updates = {}
    have = intake.answer_map
    for slot in PLANS[intake.complaint]:
        if slot in have and slot != asked_slot:
            # Extra detail volunteered later ("right side") refines where the pain is.
            if slot == "location" and (extra := _location(text)):
                merged = [p for p in have[slot].split(", ")] + [p for p in extra.split(", ") if p not in have[slot]]
                updates[slot] = ", ".join(dict.fromkeys(merged))
            continue
        value = read_slot(slot, text, asked=slot == asked_slot)
        if value:
            updates[slot] = value
    return intake.with_answers(updates)


def start_intake(session_id: str, expires_at: datetime, complaint: str, message: str) -> IntakeTransition:
    intake = _prefill(SymptomIntake(session_id, expires_at, complaint, first_message=message[:300]), message, asked_slot=None)
    if (flag := red_flags(intake)) is not None:
        return flag
    nxt = _missing(intake)
    if not nxt:
        return summarize(intake)
    intake = replace(intake, asking=nxt[0], turns_used=1)
    return IntakeTransition("ask", intake, f"{_OPENERS[complaint]}\n\n{QUESTIONS[nxt[0]]}", "INTAKE_STARTED")


def advance_intake(intake: SymptomIntake, message: str) -> IntakeTransition:
    text = message or ""
    if _CANCEL.search(text):
        return IntakeTransition("cancel", None, "Okay, I've stopped the questions. If the symptoms continue or get worse, "
                                "please see a doctor. What would you like to do next?", "INTAKE_CANCELLED")
    before = intake.answer_map
    updated = _prefill(intake, text, asked_slot=intake.asking)
    answered_current = intake.asking is not None and intake.asking in updated.answer_map and (
        intake.asking not in before or updated.answer_map[intake.asking] != before[intake.asking])
    learned_something = updated.answer_map != before
    if not learned_something and _NEW_QUESTION.search(text):
        return IntakeTransition("topic_change", None, "", "INTAKE_TOPIC_CHANGE")
    updated = replace(updated, turns_used=intake.turns_used + 1)
    if (flag := red_flags(updated)) is not None:
        return flag
    remaining = _missing(updated)
    if not remaining or updated.turns_used >= MAX_INTAKE_TURNS:
        return summarize(updated)
    nxt = remaining[0]
    if not answered_current and intake.asking == nxt:
        # Didn't catch the answer: rephrase rather than repeat word for word.
        return IntakeTransition("ask", replace(updated, asking=nxt),
                                f"Sorry, I didn't quite catch that. {QUESTIONS[nxt]} (You can also say 'not sure'.)",
                                "INTAKE_REASKED")
    ack = _ACKS[updated.turns_used % len(_ACKS)]
    return IntakeTransition("ask", replace(updated, asking=nxt), f"{ack} {QUESTIONS[nxt]}", "INTAKE_QUESTION")


# ---- red flags (DEVELOPMENT RULES: require clinician review) ----------------

URGENT_PROTOCOL = "PROTO-INTAKE-RED-FLAG-01"


def _score(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"(\d+)/10", value)
    if m:
        return int(m.group(1))
    return {"very severe": 9, "severe": 8, "moderate": 5, "mild": 2}.get(value)


def red_flags(intake: SymptomIntake) -> IntakeTransition | None:
    """Return an urgent transition when the answers so far need prompt care."""
    a = intake.answer_map
    other = a.get("other_symptoms", "")
    severity = _score(a.get("severity"))
    pregnancy = a.get("pregnancy")
    location = a.get("location", "")
    reasons = []
    if intake.complaint in {"pain", "bleeding"} and pregnancy in {"yes", "possible"}:
        reasons.append("pain or bleeding when you are or might be pregnant can be a sign of a problem such as an ectopic pregnancy")
    if severity is not None and severity >= 8:
        reasons.append("severe pain needs to be checked the same day")
    if "fever" in other and intake.complaint in {"pain", "discharge", "bleeding"}:
        reasons.append("pain or discharge with a fever can mean an infection that needs prompt treatment")
    if "right side" in location and ("vomiting" in other or "fever" in other):
        reasons.append("lower right pain with fever or vomiting needs checking for appendicitis")
    if "dizziness or fainting" in other and intake.complaint in {"pain", "bleeding"}:
        reasons.append("feeling faint with pain or bleeding can mean significant blood loss")
    if a.get("amount", "").startswith("very heavy"):
        reasons.append("soaking through a pad or tampon every hour or two is very heavy bleeding")
    if not reasons:
        return None
    message = ("Based on what you've told me, please get medical care now — go to urgent care or an emergency "
               "department, or call your local emergency number if it's severe or you feel faint.\n\nWhy: "
               + "; ".join(reasons) + ".\n\nI can't examine you, so it's safest to be seen in person.")
    return IntakeTransition("urgent", None, message, "INTAKE_RED_FLAG", URGENT_PROTOCOL)


# ---- summary (DEVELOPMENT CONTENT: requires clinician review) ----------------

_LABELS = {
    "location": "Where", "cycle_timing": "Timing", "duration": "How long", "severity": "How bad",
    "other_symptoms": "Other symptoms", "pregnancy": "Chance of pregnancy", "bleeding_timing": "When it happens",
    "amount": "How heavy", "last_period": "Last period", "usual_cycle": "Usual cycle", "discharge_desc": "Description",
}

_SEEK_CARE = [
    "Get urgent care now if the pain becomes severe or sudden, you faint or feel very dizzy, you have a fever "
    "with the pain, you're vomiting and can't keep fluids down, or there's any chance you're pregnant and you "
    "have pain or bleeding.",
    "Book a doctor's appointment if it lasts more than a few days, keeps coming back, gets worse, or affects "
    "your daily life.",
]


def _possibilities(intake: SymptomIntake) -> tuple[list[str], str]:
    """Educational list of things a doctor may consider, plus a topic for follow-ups."""
    a = intake.answer_map
    location, timing = a.get("location", ""), a.get("cycle_timing", "")
    other = a.get("other_symptoms", "")
    severity = _score(a.get("severity")) or 0
    items: list[str] = []
    topic = "Menstrual Health"
    if intake.complaint in {"pain", "general"}:
        if timing == "during periods":
            items.append("Period cramps (dysmenorrhea) — very common, caused by the womb contracting")
            if severity >= 6 or "long-standing" in a.get("duration", ""):
                items.append("Conditions such as endometriosis or fibroids, which can make periods more painful")
        elif timing == "mid-cycle":
            items.append("Ovulation pain — a one-sided twinge or ache around the middle of the cycle, usually short-lived")
        elif timing == "before periods":
            items.append("Premenstrual symptoms (PMS), which can include cramping, bloating and tenderness")
            topic = "Premenstrual Syndrome (PMS and PMDD)"
        if "upper belly" in location:
            items.append("Digestive causes such as indigestion, gastritis or gallbladder problems — these are outside "
                         "what I cover in detail, so a general doctor is the right place to start")
        elif timing in {"not related to periods", "not sure", ""} or not timing:
            if "burning when peeing" in other:
                items.append("A urinary tract (bladder) infection, especially with burning or needing to pee often")
            if "diarrhoea or constipation" in other or "bloating" in other or not other or other == "none":
                items.append("Bowel causes such as constipation, trapped wind or irritable bowel")
            if "lower belly" in location or "left side" in location or "right side" in location:
                items.append("An ovarian cyst, which can cause one-sided pelvic pain")
            if "unusual discharge" in other or "fever" in other or "pain during sex" in other:
                items.append("A pelvic infection, which needs prompt testing and treatment")
            if "right side" in location:
                items.append("Appendicitis is important to rule out if the pain gets worse or spreads, or if fever or vomiting start")
    elif intake.complaint == "bleeding":
        timing_b = a.get("bleeding_timing", "")
        if timing_b == "after menopause":
            items.append("Any bleeding after menopause should be checked by a doctor soon, even if it's light")
        elif timing_b == "after sex":
            items.append("Changes or inflammation of the cervix, or an infection — a check-up and up-to-date cervical screening help")
        elif timing_b == "between periods":
            items.append("Hormonal changes, contraception side effects, polyps or infection")
        else:
            items.append("Heavy menstrual bleeding, which can be linked to fibroids, polyps or hormonal changes — it's also worth checking iron levels")
            topic = "Heavy Menstrual Bleeding (Menorrhagia)"
    elif intake.complaint == "cycle":
        if a.get("pregnancy") in {"possible", "not sure"}:
            items.append("Pregnancy — a home pregnancy test is a sensible first step")
        items.append("Stress, weight change, intense exercise, thyroid problems, PCOS or perimenopause, which can all change cycles")
        if a.get("usual_cycle") == "usually irregular":
            topic = "PCOS (Polycystic Ovary Syndrome)"
    elif intake.complaint == "discharge":
        desc = a.get("discharge_desc", "").casefold()
        if "itch" in desc or "thick" in desc or "white" in desc:
            items.append("A yeast (thrush) infection, which often causes itching and thick white discharge")
        if "fish" in desc or "grey" in desc or "gray" in desc:
            items.append("Bacterial vaginosis, which often causes a thin discharge with a fishy smell")
        items.append("A sexually transmitted infection — testing is simple and confidential")
    if not items:
        items.append("Several everyday causes are possible, and a doctor can narrow them down with a short examination")
    return items, topic


def summarize(intake: SymptomIntake) -> IntakeTransition:
    a = intake.answer_map
    told = [f"- {_LABELS[slot]}: {a[slot]}" for slot in PLANS[intake.complaint] if slot in a]
    items, topic = _possibilities(intake)
    sections = [
        "Thank you — here's what you've told me:\n" + "\n".join(told),
        "Things a doctor may consider\n" + "\n".join(f"- {item}" for item in items),
        "When to get help\n" + "\n".join(f"- {line}" for line in _SEEK_CARE),
        "I can't diagnose what's causing this, but I can explain any of these topics from reviewed sources — just ask "
        "(for example \"tell me about period cramps\"). Writing down when it happens and what helps can also be useful for a doctor.",
    ]
    return IntakeTransition("summary", None, "\n\n".join(sections), "INTAKE_SUMMARY", topic=topic,
                            next_steps=tuple(_SEEK_CARE))


def single_turn_prompt(complaint: str, message: str) -> str:
    """When session context is off we can't remember answers, so ask everything at once."""
    intake = _prefill(SymptomIntake("", datetime.max, complaint), message, asked_slot=None)
    remaining = _missing(intake)
    lines = "\n".join(f"- {QUESTIONS[slot]}" for slot in remaining)
    return (f"{_OPENERS[complaint]}\n\nSession memory is off, so I can't remember answers between messages. "
            "Turn on session context in settings for a step-by-step conversation, or describe everything in one "
            "message, for example: \"I have lower right belly pain for 2 days, about 5/10, not related to my period, "
            "no fever, not pregnant.\"\n\nWhat I'd like to know:\n" + lines)
