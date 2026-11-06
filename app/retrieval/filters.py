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

from app.retrieval.exceptions import ScopeViolationError, UrgentEscalationRequired
from app.schemas.evidence import EducationalCategory, EvidencePassage, SourceMetadata

# Urgent red-flag patterns checked deterministically on every turn before retrieval
URGENT_HAZARD_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"\b(faint(?:ed|ing)?|pass(?:ed)?\s+out|syncope|unconscious|dizz(?:y|iness)\s+and\s+bleeding|"
            r"soak(?:ing)?\s+through.*pad|heavy\s+bleeding.*hour|severe\s+(?:pelvic|abdominal)\s+pain|"
            r"pregnant.*(?:bleeding|pain|faint)|ectopic|chest\s+pain|shortness\s+of\s+breath)\b",
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

# Disallowed clinical/diagnostic/prescription patterns outside educational scope
DISALLOWED_CLINICAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(should\s+i\s+stop\s+(?:taking|my)|stop\s+my\s+prescribed|change\s+my\s+dose|"
            r"what\s+dosage\s+of|prescribe\s+me|how\s+many\s+mg\s+should\s+i\s+take)\b",
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

    return cleaned


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
) -> dict[str, SourceMetadata]:
    """Return a mapping of source_id -> SourceMetadata for approved, current, non-superseded sources."""
    today = reference_date or date.today()
    eligible: dict[str, SourceMetadata] = {}

    for src in sources:
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
