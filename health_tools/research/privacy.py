"""Remove personal details from a question before it is sent to external services.

The safety check runs locally on the original text. Everything sent to Groq, Gemini
and search services uses the redacted version. Rule-based, so it can miss details
phrased unusually; the UI still asks people to leave personal details out.

Kept on purpose: general population ages ("women over 40") and clinical numbers,
which change the medical answer. Removed: first-person ages, dates, contact
details, links, long ID numbers, and self-identifying names and places.
"""

import re

_MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

# Order matters: dates before phone numbers, so "2026-10-03" is a date, not a phone.
_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
    ("link", re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I), "[link]"),
    ("date", re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"), "[date]"),
    ("date", re.compile(rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTHS}(?:,?\s+\d{{4}})?\b", re.I), "[date]"),
    ("phone", re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)"), "[phone]"),
    # First-person ages only; "women over 40" or "a 45-year-old" stay, since age changes the answer.
    ("age", re.compile(r"\b(?:i\s*am|i'm|im|i’m|i\s+turned)\s+(?:a\s+)?\d{1,2}(?:\s*-?\s*(?:years?|yrs?|y/?o))?(?:\s*-?\s*old)?\b", re.I), "I am [age]"),
    ("age", re.compile(r"\bmy\s+age\s+is\s+\d{1,2}\b", re.I), "my age is [age]"),
    # Lead phrase is case-insensitive; the name/place itself must be Capitalized.
    ("name", re.compile(r"\b((?i:my\s+name\s+is|i\s+am\s+called|call\s+me))\s+[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?"), r"\1 [name]"),
    ("location", re.compile(r"\b((?i:i\s+live\s+in|i'm\s+from|i\s+am\s+from|based\s+in))\s+[A-Z][\w'-]+(?:,?\s+[A-Z][\w'-]+){0,2}"), r"\1 [location]"),
    ("id number", re.compile(r"\b\d{6,}\b"), "[number]"),
]


def redact(question: str) -> tuple[str, list[str]]:
    """Return (redacted question, sorted kinds of detail removed)."""
    text, kinds = question or "", set()
    for kind, pattern, replacement in _RULES:
        text, count = pattern.subn(replacement, text)
        if count:
            kinds.add(kind)
    return " ".join(text.split()), sorted(kinds)
