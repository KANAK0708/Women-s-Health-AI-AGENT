"""Read-only adapters for the teammate's memory and retrieval interfaces.

No application imports at module load: standalone tools remain usable before
upstream is merged. These adapters do not confer medical approval on evidence.
"""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class ContractViolation(ValueError):
    """An upstream payload cannot be used safely by the orchestration layer."""


class RetrievalBundleLike(Protocol):
    manifest_version: str
    scored_passages: list
    citations: list


def _payload(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if callable(getattr(value, "model_dump", None)):
        return value.model_dump(mode="json")
    raise ContractViolation("Expected a mapping or Pydantic model")


def _required_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation("Required text is missing")
    return value


def _timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ContractViolation("Invalid timestamp") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractViolation("Timezone-aware timestamp required")
    return value


@dataclass(frozen=True)
class ContextSnapshot:
    """Minimum read-only context; unknown values remain explicitly unknown."""

    context_available: bool = False
    unavailable_reason: str | None = None
    age: int | None = None
    is_adult: str = "not_provided"
    pregnancy_status: str = "not_provided"
    current_medications_mentioned: str = "not_provided"
    irregular_cycles_mentioned: str = "not_provided"
    severe_symptom_flag: str = "not_provided"
    active_topic: str | None = None
    clarification_turns_used: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def adapt_session(session: Any, *, now: datetime | None = None) -> ContextSnapshot:
    """Accept SessionMemory/model_dump; suppress declined or expired context.

    The caller still supplies the current user message separately. This function
    does not update memory, decide medical urgency, or authorize persistence.
    """
    if session is None:
        return ContextSnapshot(unavailable_reason="no_session")
    payload = _payload(session)
    consent = payload.get("allow_session_context")
    if type(consent) is not bool:
        raise ContractViolation("Explicit session-context consent flag required")
    if not consent:
        return ContextSnapshot(unavailable_reason="consent_declined")
    reference = _timestamp(now if now is not None else datetime.now(timezone.utc))
    created = _timestamp(payload.get("created_at"))
    expires = _timestamp(payload.get("expires_at"))
    if created >= expires or created > reference:
        raise ContractViolation("Invalid session time interval")
    if reference >= expires:
        return ContextSnapshot(unavailable_reason="session_expired")
    context = _payload(payload.get("context"))
    values = {}
    for key in ("is_adult", "pregnancy_status", "current_medications_mentioned",
                "irregular_cycles_mentioned", "severe_symptom_flag"):
        value = context.get(key, "not_provided")
        if value not in ("yes", "no", "not_provided"):
            raise ContractViolation("Invalid three-state context value")
        values[key] = value
    age = context.get("age")
    if age is not None and (type(age) is not int or not 1 <= age <= 120):
        raise ContractViolation("Invalid age")
    if age is not None and values["is_adult"] != "not_provided":
        if (age >= 18) != (values["is_adult"] == "yes"):
            raise ContractViolation("Age and adult context disagree")
    turns = context.get("clarification_turns_used", 0)
    if type(turns) is not int or not 0 <= turns <= 2:
        raise ContractViolation("Invalid clarification count")
    topic = context.get("active_topic")
    if topic is not None:
        _required_text(topic)
    return ContextSnapshot(context_available=True, age=age, active_topic=topic,
                           clarification_turns_used=turns, **values)


@dataclass(frozen=True)
class PassageSnapshot:
    citation_id: str
    passage_id: str
    source_id: str
    title: str
    url: str
    locator: str
    reviewed_at: str
    category: str
    text: str


@dataclass(frozen=True)
class EvidenceSnapshot:
    manifest_version: str
    passages: tuple[PassageSnapshot, ...]

    def to_dict(self) -> dict:
        value = asdict(self)
        value["passages"] = list(value["passages"])
        return value


def adapt_retrieval(bundle: RetrievalBundleLike) -> EvidenceSnapshot:
    """Copy RetrievalBundle, validating one-to-one passage/citation identities.

    Relevance scores are deliberately omitted: they are not clinical confidence.
    Source eligibility, rights, freshness, and review remain retrieval-owner duties.
    """
    version = _required_text(bundle.manifest_version)
    citations = {}
    citation_ids = set()
    for raw in bundle.citations:
        citation = _payload(raw)
        for key in ("id", "passage_id", "source_id", "title", "url", "locator", "reviewed_at"):
            _required_text(citation.get(key))
        if citation["passage_id"] in citations or citation["id"] in citation_ids:
            raise ContractViolation("Duplicate citation identity")
        citations[citation["passage_id"]] = citation
        citation_ids.add(citation["id"])
    passages = []
    seen = set()
    for scored in bundle.scored_passages:
        passage = _payload(scored.passage)
        for key in ("passage_id", "source_id", "title", "url", "locator", "reviewed_at", "category", "text"):
            _required_text(passage.get(key))
        pid = passage["passage_id"]
        if pid in seen or pid not in citations:
            raise ContractViolation("Duplicate or uncited passage")
        citation = citations[pid]
        for key in ("source_id", "title", "url", "locator", "reviewed_at"):
            if citation[key] != passage[key]:
                raise ContractViolation("Passage and citation metadata disagree")
        passages.append(PassageSnapshot(
            citation_id=citation["id"], **{key: passage[key] for key in (
                "passage_id", "source_id", "title", "url", "locator", "reviewed_at", "category", "text"
            )}
        ))
        seen.add(pid)
    if seen != set(citations):
        raise ContractViolation("Citation has no retrieved passage")
    return EvidenceSnapshot(version, tuple(passages))


def validate_claim_references(claims: list[dict], evidence: EvidenceSnapshot) -> None:
    """Structural validation only; does NOT verify semantic claim support.

    Callers must separately check all displayed medical statements for support.
    A valid citation reference alone never establishes answer correctness.
    """
    if not isinstance(claims, list):
        raise ContractViolation("Claims must be a list")
    allowed = {item.citation_id for item in evidence.passages}
    seen = set()
    for raw in claims:
        claim = _payload(raw)
        identifier = _required_text(claim.get("id"))
        _required_text(claim.get("text"))
        if identifier in seen:
            raise ContractViolation("Duplicate claim ID")
        refs = claim.get("evidence_ids")
        if not isinstance(refs, list) or not refs or any(
            not isinstance(ref, str) or ref not in allowed for ref in refs
        ):
            raise ContractViolation("Claim has missing or unknown evidence references")
        seen.add(identifier)
