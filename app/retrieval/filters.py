"""Deterministic pre-filters and educational scope guardrails for retrieval.

Implements Section 4, Section 5, and Section 6 of the Implementation Plan:
- Source eligibility filtering (active, non-superseded, non-expired, adult population, jurisdiction).
- Pre-retrieval urgent safety hazard detection.
- Strict educational scope enforcement for DuckDuckGo and Wikipedia queries
  (limited to definition/'what it is', symptoms, and prevention/lifestyle).
"""

import re
from datetime import date
from typing import Optional

from app.retrieval.exceptions import MinorScopeError, ScopeViolationError, UrgentEscalationRequired
from app.schemas.evidence import EducationalCategory, EvidencePassage, SourceMetadata

# Urgent red-flag patterns checked deterministically on every turn before retrieval
URGENT_HAZARD_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"\b(faint(?:ed|ing)?|pass(?:ed)?\s+out|syncope|unconscious|dizz(?:y|iness|y)\s+and\s+bleeding|"
            r"soak(?:ing)?\s+through.*?(?:pad|tampon)s?|heavy\s+bleeding.*?(?:hour|clot)|"
            r"severe\s+(?:pelvic|abdominal)\s+pain|pregnan(?:t|cy).*?(?:bleeding|pain|cramp|faint)|"
            r"(?:bleeding|pain|cramp).*?pregnan(?:t|cy)|ectopic|chest\s+pain|shortness\s+of\s+breath)\b",
            re.IGNORECASE,
        ),
        "PROTO-URGENT-HEMORRHAGE-ECTOPIC-01",
        "Potential acute medical emergency detected (severe pain, heavy bleeding, fainting, or pregnancy complication). "
        "Please seek immediate emergency medical care or call your local emergency number right away.",
    ),
    (
        re.compile(
            r"\b(suicid(?:e|al)|kill\s+myself|self[-\s]?harm|want\s+to\s+die|end\s+my\s+life)\b",
            re.IGNORECASE,
        ),
        "PROTO-URGENT-CRISIS-02",
        "Immediate crisis support is available. Please contact your local emergency services or a crisis lifeline immediately.",
    ),
]

# Medicines people ask to start, stop or re-dose (generic and common brand names).
_DRUGS = (r"metformin|spironolactone|letrozole|clomi(?:d|phene)|inositol|myo-inositol|progesterone|provera|"
          r"norethisterone|medroxyprogesterone|tranexamic(?:\s+acid)?|ibuprofen|naproxen|mefenamic(?:\s+acid)?|"
          r"paracetamol|acetaminophen|iron(?:\s+(?:tablets?|pills?|supplements?))?|ferrous\s+\w+|folic\s+acid|"
          r"estrogen|oestrogen|estradiol|hrt|birth\s+control(?:\s+pills?)?|contraceptive(?:\s+pills?)?|the\s+pill|"
          r"levothyroxine|thyroxine|ozempic|semaglutide|antibiotics?|fluconazole|metronidazole|antidepressants?|sertraline")

# Disallowed clinical/diagnostic/prescription patterns outside educational scope
DISALLOWED_CLINICAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b(?:i[\s-]?pill|levonorgestrel|emergency\s+contracepti(?:on|ve)|morning[\s-]+after\s+pill|"
                   r"plan[\s-]?b|ulipristal|ella(?:one)?|after[\s-]sex\s+pill)\b|"
                   # Unprotected sex or a failed condom combined with asking what to take: an EC request.
                   r"\b(?:unprotected\s+sex|condom\s+(?:broke|burst|split|slipped|came\s+off))\b.{0,80}?"
                   r"\b(?:take|pill|tablet|prevent\s+(?:a\s+)?pregnancy)\b", re.IGNORECASE),
        "Emergency contraception advice is outside the validated educational corpus.",
    ),
    (
        re.compile(
            r"\b(should\s+i\s+stop\s+(?:taking|my)|stop\s+my\s+prescribed|"
            r"(?:change|double|increase|decrease|halve|adjust)\s+(?:the|my)?\s*(?:dose|dosage)|"
            r"what\s+dosage\s+of|prescribe\s+me|how\s+many\s+mg.*?(?:take|need|prescribe))\b|"
            # Changing, stopping or skipping a named medicine or "my pills/tablets/medication".
            rf"\b(?:stop|skip|quit|increase|decrease|double|halve|reduce|lower|raise|up|adjust|change|miss)\s+(?:taking\s+)?"
            rf"(?:my|the|her)\s+(?:[\w-]+\s+){{0,2}}?(?:{_DRUGS}|dose|dosage|pills?|tablets?|medications?|medicines?|meds|prescription)\b|"
            # "How much X should I take", "how many tablets can I take".
            r"\bhow\s+(?:much|many)\s+(?:[\w-]+\s+){0,4}?(?:should|can|do|must|could)\s+i\s+(?:take|use|have)\b|"
            # Starting a prescription medicine without a clinician.
            rf"\b(?:start|begin|get|take|buy|use)\s+(?:[\w-]+\s+){{0,3}}?(?:{_DRUGS})\b.{{0,40}}?\bwithout\s+(?:a\s+)?"
            r"(?:doctor|prescription|prescriber|gp|clinician)\b",
            re.IGNORECASE,
        ),
        "Medication initiation, stopping, or dosage adjustments require a prescribing clinician or pharmacist.",
    ),
    (
        re.compile(
            r"\b(ignore\s+(?:all\s+)?(?:previous\s+)?(?:safety|instructions|policies|rules)|"
            r"bypass\s+safety|system\s+prompt\s+override)\b",
            re.IGNORECASE,
        ),
        "Prompt injection or safety policy override attempt blocked.",
    ),
]


def check_urgent_hazards(query: str) -> None:
    """Raise UrgentEscalationRequired if query contains red-flag danger signals."""
    for pattern, protocol_id, urgent_message in URGENT_HAZARD_PATTERNS:
        if pattern.search(query):
            raise UrgentEscalationRequired(urgent_message, protocol_id=protocol_id)


def validate_educational_query_scope(query: str) -> str:
    """Validate that a query stays strictly within educational scope:
    - What a condition is (definition/overview)
    - Symptoms
    - Prevention & lifestyle measures

    Raises:
        UrgentEscalationRequired: If red-flag symptoms are present.
        ScopeViolationError: If the query requests prescription changes, dosing, or safety overrides.
    """
    cleaned = query.strip()
    if not cleaned:
        raise ScopeViolationError("Query cannot be empty.")

    check_urgent_hazards(cleaned)

    for pattern, reason in DISALLOWED_CLINICAL_PATTERNS:
        if pattern.search(cleaned):
            raise ScopeViolationError(reason)

    if mentions_minor(cleaned):
        raise MinorScopeError(MINOR_SCOPE_MESSAGE)

    return cleaned


MINOR_SCOPE_MESSAGE = ("This assistant only covers adults (18 and over), so I can't help with questions about someone "
                       "under 18. Please talk to a paediatrician, family doctor (GP) or school nurse.")

_UNDER_18 = r"(?:[1-9]|1[0-7])"
_MINOR_PATTERNS = re.compile(
    # "I'm 15", "im 13", "I am aged 16", "I just turned 14"
    rf"\b(?:i\s*am|i'm|i’m|im|i\s+just\s+turned|i\s+turned|aged|my\s+age\s+is)\s+(?:aged\s+)?{_UNDER_18}\b(?!\s*(?:%|weeks?|days?|months?|cm|kg|mg|lbs?|pads?|hours?))|"
    # "my 14 year old daughter", "a 15-year-old", "15 yo"
    rf"\b{_UNDER_18}\s*-?\s*(?:years?|yrs?|y/?o)\b(?:\s*-?\s*old)?|"
    # "my daughter is 16"
    rf"\b(?:daughter|son|child|kid|niece|sister|girl)\s+(?:is|who\s+is|aged)\s+{_UNDER_18}\b",
    re.IGNORECASE,
)


def mentions_minor(query: str) -> bool:
    """True when the question is about someone under 18 (stated as a number)."""
    return bool(_MINOR_PATTERNS.search(query or ""))


_DIAGNOSIS_REQUEST = re.compile(
    r"\bdiagnos(?:e|is)\s+(?:me|my|her|this)\b|\bdiagnos\w*\b.{0,30}\b(?:pcos|pcod|endometriosis|pmdd|fibroids|adenomyosis)\b|"
    r"\bdo\s+i\s+have\s+(?:pcos|pcod|endometriosis|pmdd|fibroids|adenomyosis|cancer|an?\s+\w+)\b|"
    r"\b(?:confirm|tell\s+me)\s+(?:that\s+|if\s+|whether\s+)?i\s+have\b|"
    r"\bwhat\s+(?:condition|disease|illness)\s+do\s+i\s+have\b|\bis\s+it\s+(?:pcos|endometriosis|cancer)\b",
    re.IGNORECASE,
)

DIAGNOSIS_NOTE = ("I can't diagnose you — only a clinician who can examine you and order tests can do that. "
                  "Here is general information that may help you talk it through with them.")


def is_diagnosis_request(query: str) -> bool:
    """True when someone asks to be told which condition they personally have."""
    return bool(_DIAGNOSIS_REQUEST.search(query or ""))


def build_constrained_educational_query(
    topic_or_query: str,
    focus: Optional[EducationalCategory] = None,
) -> str:
    """Sanitize and constrain a public search query (Wikipedia / DuckDuckGo)
    so it only retrieves educational definitions ('what it is'), symptoms,
    and prevention/lifestyle habits.
    """
    validated = validate_educational_query_scope(topic_or_query)

    # Strip commercial or prescription noise words
    sanitized = re.sub(
        r"\b(buy|order|cheap|price|dosage|mg|prescription|online\s+pharmacy)\b",
        "",
        validated,
        flags=re.IGNORECASE,
    ).strip()

    focus_keywords = {
        EducationalCategory.DEFINITION: "what is definition overview causes",
        EducationalCategory.SYMPTOMS: "symptoms signs clinical presentation",
        EducationalCategory.PREVENTION_LIFESTYLE: "prevention lifestyle habits diet exercise self-care",
        EducationalCategory.WHEN_TO_SEEK_CARE: "when to see a doctor warning signs",
    }

    suffix = focus_keywords.get(
        focus,
        "what is definition symptoms prevention lifestyle health education",
    )
    return f"{sanitized} {suffix}".strip()


def filter_eligible_sources(
    sources: list[SourceMetadata],
    *,
    reference_date: Optional[date] = None,
    jurisdiction: str = "Global",
    population: str = "adults_18+",
    life_stage_filter: Optional[str] = None,
    allow_unverified_for_development: bool = False,
) -> dict[str, SourceMetadata]:
    """Return a mapping of source_id -> SourceMetadata for approved, current, non-superseded sources."""
    if type(allow_unverified_for_development) is not bool:
        raise ValueError("Development evidence permission must be a boolean")
    today = reference_date or date.today()
    eligible: dict[str, SourceMetadata] = {}

    for src in sources:
        if src.approval_status != "approved" and not allow_unverified_for_development:
            continue
        if src.is_superseded:
            continue
        if src.expiry_date < today:
            continue
        if src.population != population:
            continue
        if src.jurisdiction not in (jurisdiction, "Global"):
            continue
        if life_stage_filter and life_stage_filter not in src.life_stage:
            continue
        eligible[src.source_id] = src

    return eligible


def filter_eligible_passages(
    passages: list[EvidencePassage],
    eligible_sources: dict[str, SourceMetadata],
    *,
    category: Optional[EducationalCategory] = None,
) -> list[EvidencePassage]:
    """Filter passages to those belonging to eligible sources and optional educational category."""
    results: list[EvidencePassage] = []
    for passage in passages:
        if passage.source_id not in eligible_sources:
            continue
        if category is not None and passage.category != category:
            continue
        results.append(passage)
    return results

