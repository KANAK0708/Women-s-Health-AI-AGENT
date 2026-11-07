"""Transparent English question focus and passage selection, without rewriting.

This is category/locator matching, not semantic completeness or medical judgment.
The retrieval owner still determines source eligibility and topic relevance.
"""

import re
from dataclasses import dataclass

from .handoff import EvidenceSnapshot


FACETS = {
    "definition": ("what_it_is", "What it is"),
    "assessment": ("what_it_is", "How it is assessed"),
    "symptoms": ("symptoms", "Symptoms"),
    "lifestyle": ("prevention_and_lifestyle", "Lifestyle and habits"),
    "care": ("when_to_seek_care", "When to seek care"),
}
_TOPIC = re.compile(r"\b(pcos|pcod|polycystic|periods?|menstr\w*|endometriosis|dysmenorrhea|menorrhagia)\b", re.I)
_ASSESSMENT_LOCATOR = re.compile(r"diagnos\w*|criteria|clinical (?:assessment|evaluation)", re.I)


@dataclass(frozen=True)
class QuestionFocus:
    facets: tuple[str, ...]
    retrieval_query: str
    needs_topic: bool = False


def question_focus(query: str, *, active_topic: str | None = None) -> QuestionFocus:
    """Recognize requested sections; enrich only clearly elliptical follow-ups."""
    lowered = query.casefold()
    requested = set()
    care = bool(re.search(r"warning signs|red flags|when\b.*\b(?:doctor|care|help|medical)", lowered))
    if care:
        requested.add("care")
    if re.search(r"\bsymptoms?\b|\bacne\b|hair (?:growth|thinning)|\bbloating\b", lowered) or (
        not care and re.search(r"\bsigns?\b", lowered)
    ):
        requested.add("symptoms")
    if re.search(r"\b(?:lifestyle|habits?|diet|exercise|nutrition|sleep|prevent\w*|manag\w*)\b|self[- ]care|period tracking", lowered):
        requested.add("lifestyle")
    if re.search(r"\b(?:diagnos\w*|criteria|assessment|evaluat\w*)\b", lowered):
        requested.add("assessment")
    if re.search(r"\b(?:define|definition|overview)\b|what does\b.*\bmean\b|what is (?:pcos|pcod|polycystic|menstruation|a period|endometriosis|it|this)\b|what are periods\b", lowered):
        requested.add("definition")
    broad = bool(re.search(r"\btell me about\b|\bgeneral overview\b|\beverything\b|\ball about\b|\b(?:explain|tell|teach)(?: me)? all\b", lowered))
    bare_topic = bool(re.fullmatch(r"\s*(?:(?:please )?explain (?:me )?)?(?:pcos|pcod|periods|menstrual health)[.!? ]*", lowered))
    if re.search(r"\btell me about\b|\bgeneral overview\b", lowered) or bare_topic or (
        broad and not requested.intersection({"symptoms", "lifestyle", "assessment", "care"})
    ):
        requested.update(("definition", "symptoms", "lifestyle"))
    has_requested_focus = bool(requested)
    if not requested:
        requested.add("definition")

    elliptical = bool(re.match(r"\s*(?:and\b|also\b|what about\b|how about\b|tell me more\b|what else\b)", lowered))
    singular_reference = has_requested_focus and bool(re.search(r"\b(?:it|its|the condition|the topic)\b", lowered))
    plural_reference = bool(re.search(r"\b(?:them|those|these|both|all of them)\b", lowered))
    elliptical = elliptical or singular_reference or plural_reference
    generic = re.sub(r"[^a-z ]", " ", lowered).strip()
    elliptical = elliptical or generic in {
        "symptoms", "what are the symptoms", "what are its symptoms", "what is it",
        "how is it diagnosed", "how can i manage it", "what are the signs",
        "when should i see a doctor", "what does it mean",
    }
    needs_topic = elliptical and not _TOPIC.search(query)
    # A single active topic cannot disambiguate a plural reference to a menu,
    # multiple conditions, symptoms, or tools. Ask rather than silently picking.
    if needs_topic and plural_reference:
        return QuestionFocus(tuple(f for f in FACETS if f in requested), query, True)
    if broad and not _TOPIC.search(query) and re.fullmatch(
        r"\s*(?:please )?(?:explain|tell|teach)(?: me)? (?:everything|all)[.!? ]*", lowered
    ):
        needs_topic = True
    if needs_topic and isinstance(active_topic, str) and _TOPIC.search(active_topic):
        return QuestionFocus(tuple(f for f in FACETS if f in requested), f"{active_topic}: {query}")
    return QuestionFocus(tuple(f for f in FACETS if f in requested), query, needs_topic)


def select_passages(evidence: EvidenceSnapshot, focus: QuestionFocus):
    """Pick the highest-ranked passage per requested facet; preserve text/IDs.

    Assessment/diagnostic locators do not substitute for a definition. No paragraph
    is truncated or paraphrased. Missing facets are reported rather than filled.
    """
    categories = {category for category, _ in FACETS.values()}
    if any(item.category not in categories for item in evidence.passages):
        raise ValueError("Unsupported evidence category")
    selected = []
    missing = []
    for facet in focus.facets:
        category, _ = FACETS[facet]
        match = None
        for item in evidence.passages:
            if item.category != category:
                continue
            assessment = bool(_ASSESSMENT_LOCATOR.search(item.locator))
            if category == "what_it_is" and assessment != (facet == "assessment"):
                continue
            match = item
            break
        if match is None:
            missing.append(facet)
        else:
            selected.append((facet, match))
    return tuple(selected), tuple(missing)
