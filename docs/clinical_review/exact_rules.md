# Exact safety and privacy rule appendix

This appendix preserves machine expressions as they currently exist. See [safety_rules.md](safety_rules.md) for plain-language explanations, observed examples and reviewer questions. No expression was edited.

## Shared urgent patterns

### U1: `PROTO-URGENT-HEMORRHAGE-ECTOPIC-01`

Case-insensitive regular expression:

```regex
\b(faint(?:ed|ing)?|pass(?:ed)?\s+out|syncope|unconscious|dizz(?:y|iness|y)\s+and\s+bleeding|soak(?:ing)?\s+through.*?(?:pad|tampon)s?|heavy\s+bleeding.*?(?:hour|clot)|severe\s+(?:pelvic|abdominal)\s+pain|pregnan(?:t|cy).*?(?:bleeding|pain|cramp|faint)|(?:bleeding|pain|cramp).*?pregnan(?:t|cy)|ectopic|chest\s+pain|shortness\s+of\s+breath)\b
```

Exact user message:

> Potential acute medical emergency detected (severe pain, heavy bleeding, fainting, or pregnancy complication). Please seek immediate emergency medical care or call your local emergency number right away.

### U2: `PROTO-URGENT-CRISIS-02`

Case-insensitive regular expression:

```regex
\b(suicid(?:e|al)|kill\s+myself|self[-\s]?harm|want\s+to\s+die|end\s+my\s+life)\b
```

Exact user message:

> Immediate crisis support is available. Please contact your local emergency services or a crisis lifeline immediately.

## Shared blocked-topic patterns

### B1

```regex
\b(?:i[\s-]?pill|levonorgestrel|emergency\s+contracepti(?:on|ve)|morning[\s-]+after\s+pill)\b
```

Exact user message:

> Emergency contraception advice is outside the validated educational corpus.

### B2

```regex
\b(should\s+i\s+stop\s+(?:taking|my)|stop\s+my\s+prescribed|(?:change|double|increase|decrease|halve|adjust)\s+(?:the|my)?\s*(?:dose|dosage)|what\s+dosage\s+of|prescribe\s+me|how\s+many\s+mg.*?(?:take|need|prescribe))\b
```

Exact user message:

> Medication initiation, stopping, or dosage adjustments require a prescribing clinician or pharmacist.

### B3

```regex
\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:safety|instructions|policies|rules)|bypass\s+safety|system\s+prompt\s+override)\b
```

Exact user message:

> Prompt injection or safety policy override attempt blocked.

## Adult-age recognition

From [context_tracker.py](../../app/storage/context_tracker.py):

```regex
\b(?:i\s+am|i'm|age\s+is|aged)\s+(\d{1,3})\s*(?:years?\s*old|yo|yrs?)?\b
```

A recognized age from 1 to 120 sets adult eligibility; the workflow refuses a context with `is_adult == 'no'` or `age < 18`. Missing context remains unknown, not adult-confirmed.

## Symptom-intake escalation

From [symptom_intake.py](../../health_tools/symptom_intake.py); exact functions:

```python
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
```

Exact safety-net text included in intake summaries:

> Get urgent care now if the pain becomes severe or sudden, you faint or feel very dizzy, you have a fever with the pain, you're vomiting and can't keep fluids down, or there's any chance you're pregnant and you have pain or bleeding.

> Book a doctor's appointment if it lasts more than a few days, keeps coming back, gets worse, or affects your daily life.

## All intake parsing and trigger context

These expressions decide whether a personal symptom report enters intake and how answers become the values used above. They are included because parsing can change escalation. This is code text, not a clinician-endorsed questionnaire.

```python
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
                          r"\bsymptoms of\b|\bsigns of\b|\btell me about\b|\bexplain\b", re.I)


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
```

## Research redaction expressions

From [privacy.py](../../health_tools/research/privacy.py). Applied in this order; repeated 'date' and 'age' labels are separate patterns.

### email → `[email]`

```regex
\b[\w.+-]+@[\w-]+\.[\w.-]+\b
```

### link → `[link]`

```regex
\bhttps?://\S+|\bwww\.\S+
```

### date → `[date]`

```regex
\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b
```

### date → `[date]`

```regex
\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:,?\s+\d{4})?\b
```

### phone → `[phone]`

```regex
(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)
```

### age → `I am [age]`

```regex
\b(?:i\s*am|i'm|im|i’m|i\s+turned)\s+(?:a\s+)?\d{1,2}(?:\s*-?\s*(?:years?|yrs?|y/?o))?(?:\s*-?\s*old)?\b
```

### age → `my age is [age]`

```regex
\bmy\s+age\s+is\s+\d{1,2}\b
```

### name → `\1 [name]`

```regex
\b((?i:my\s+name\s+is|i\s+am\s+called|call\s+me))\s+[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?
```

### location → `\1 [location]`

```regex
\b((?i:i\s+live\s+in|i'm\s+from|i\s+am\s+from|based\s+in))\s+[A-Z][\w'-]+(?:,?\s+[A-Z][\w'-]+){0,2}
```

### id number → `[number]`

```regex
\b\d{6,}\b
```

## Claim/quote safeguards — exact constants and expressions

Research `MIN_SUPPORT = 0.5`, `MIN_QUOTE_CHARS = 25`, `MIN_SENTENCE_SUPPORT = 0.6`, `MAX_NEW_TERMS = 3`.

High-risk tokens shared by the main and research verifier (sorted for readability, exact token text):

```text
100%
completely eliminates
curable
cure
cures
curing
guarantee
guaranteed
permanent solution
replaces your doctor
safe to double
stop your medicine
```

Main verifier's negation tokens:

```text
cannot
neither
never
no
nor
not
without
```

Background-reference pattern used to exclude research quotes:

```regex
\[\s*\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\s*\]|(?<![A-Za-z])\(\s*\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\s*\)|\bet al\.?
```

Recognized retraction notices/types, exact text:

```text
['ExpressionOfConcernIn', 'RetractionIn']
['expression of concern', 'retracted publication', 'retraction of publication']
```

The main claim verifier's exact claim-checking method follows. Its default overlap threshold is 0.55; the application still requires all claims supported and decision ACCEPT, rejecting partial repair. These lexical checks are not clinical proof.

```python
    def _verify_single_claim(
        self,
        claim: ClaimItem,
        citation_map: dict[str, EvidenceCitation],
        passage_map: dict[str, EvidencePassage],
    ) -> ClaimVerificationResult:
        """Verify an individual ClaimItem against its cited passage(s)."""
        claim_text = claim.text.strip()
        if not claim_text:
            return ClaimVerificationResult(
                claim_id=claim.id,
                claim_text=claim_text,
                status=VerificationStatus.UNSUPPORTED,
                support_score=0.0,
                cited_evidence_ids=claim.evidence_ids,
                matched_passage_ids=[],
                rationale="Claim text is empty.",
            )

        if not claim.evidence_ids:
            return ClaimVerificationResult(
                claim_id=claim.id,
                claim_text=claim_text,
                status=VerificationStatus.UNRESOLVED_CITATION,
                support_score=0.0,
                cited_evidence_ids=[],
                matched_passage_ids=[],
                rationale="Claim does not cite any evidence IDs.",
            )

        # Resolve citations to actual passages
        resolved_passages: list[EvidencePassage] = []
        matched_passage_ids: list[str] = []

        for eid in claim.evidence_ids:
            citation = citation_map.get(eid)
            if not citation:
                return ClaimVerificationResult(
                    claim_id=claim.id,
                    claim_text=claim_text,
                    status=VerificationStatus.UNRESOLVED_CITATION,
                    support_score=0.0,
                    cited_evidence_ids=claim.evidence_ids,
                    matched_passage_ids=[],
                    rationale=f"Cited evidence ID '{eid}' does not resolve to an approved citation in the response.",
                )
            passage = passage_map.get(citation.passage_id)
            if passage:
                resolved_passages.append(passage)
                matched_passage_ids.append(passage.passage_id)
            else:
                return ClaimVerificationResult(
                    claim_id=claim.id,
                    claim_text=claim_text,
                    status=VerificationStatus.UNRESOLVED_CITATION,
                    support_score=0.0,
                    cited_evidence_ids=claim.evidence_ids,
                    matched_passage_ids=[],
                    rationale=f"Cited passage ID '{citation.passage_id}' was not found in the retrieved evidence bundle.",
                )

        combined_passage_text = " ".join(p.text for p in resolved_passages)

        # 1. High-Risk Extrapolation Check
        claim_lower = claim_text.lower()
        passage_lower = combined_passage_text.lower()

        for high_risk in HIGH_RISK_CLAIM_TOKENS:
            if re.search(r"\b" + re.escape(high_risk) + r"\b", claim_lower):
                if not re.search(r"\b" + re.escape(high_risk) + r"\b", passage_lower):
                    return ClaimVerificationResult(
                        claim_id=claim.id,
                        claim_text=claim_text,
                        status=VerificationStatus.HIGH_RISK_EXTRAPOLATION,
                        support_score=0.0,
                        cited_evidence_ids=claim.evidence_ids,
                        matched_passage_ids=matched_passage_ids,
                        rationale=f"Claim asserts unsupported high-risk token '{high_risk}' not found in source text.",
                    )

        # 2. Polarity / Negation Inversion Check
        claim_has_neg = any(tok in claim_lower.split() for tok in NEGATION_TOKENS)
        passage_has_neg = any(tok in passage_lower.split() for tok in NEGATION_TOKENS)

        # Specifically check "prevented" vs "cannot be prevented"
        if "can be prevented" in claim_lower and "cannot be prevented" in passage_lower:
            return ClaimVerificationResult(
                claim_id=claim.id,
                claim_text=claim_text,
                status=VerificationStatus.CONTRADICTION,
                support_score=0.0,
                cited_evidence_ids=claim.evidence_ids,
                matched_passage_ids=matched_passage_ids,
                rationale="Polarity contradiction: passage states condition cannot be prevented, while claim asserts it can.",
            )

        # 3. Lexical Entailment & Groundedness Score
        claim_tokens = set(tokenize(claim_text, expand_synonyms=False))
        if not claim_tokens:
            claim_tokens = set(claim_lower.split())

        passage_tokens = set(tokenize(combined_passage_text, expand_synonyms=True))
        overlap = claim_tokens.intersection(passage_tokens)
        support_score = round(len(overlap) / len(claim_tokens), 4) if claim_tokens else 0.0

        if support_score >= self.min_support_threshold:
            status = VerificationStatus.SUPPORTED
            rationale = f"Claim is verified with {support_score * 100:.1f}% grounded term overlap."
        else:
            status = VerificationStatus.UNSUPPORTED
            missing_terms = list(claim_tokens - passage_tokens)[:5]
            rationale = (
                f"Low term overlap ({support_score * 100:.1f}% < {self.min_support_threshold * 100:.1f}%). "
                f"Missing key terms: {missing_terms}"
            )

        return ClaimVerificationResult(
            claim_id=claim.id,
            claim_text=claim_text,
            status=status,
            support_score=support_score,
            cited_evidence_ids=claim.evidence_ids,
            matched_passage_ids=matched_passage_ids,
            rationale=rationale,
        )
```
