"""Data shapes for the research agent: internal documents, LLM outputs, final report."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal[
    "official_guidance", "professional_society", "guideline", "systematic_review",
    "rct", "narrative_review", "research_article", "consumer_health", "web",
]

# Lower number = stronger evidence; used to order documents and findings.
EVIDENCE_RANK: dict[str, int] = {
    "guideline": 0, "official_guidance": 0, "systematic_review": 1,
    "professional_society": 2, "rct": 3, "narrative_review": 4, "research_article": 5,
    "consumer_health": 6, "web": 7,
}

DISCLAIMER = (
    "Educational research summary built from the cited sources only. It is not a "
    "diagnosis or treatment plan; discuss your situation with a qualified clinician."
)


@dataclass
class Document:
    """A source the agent has read. `text` is the exact text quotes are checked against."""

    doc_id: str
    url: str
    title: str
    publisher: str
    source_type: str
    text: str
    published: str | None = None
    retrieved_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    locator: str = ""
    needs_fetch: bool = False  # True when only a link is known and the page must still be read
    pmcid: str | None = None   # Open-access Europe PMC full text available for this record

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def rank(self) -> int:
        return EVIDENCE_RANK.get(self.source_type, 9)


# ---- LLM structured outputs -------------------------------------------------

class SubQuestion(BaseModel):
    question: str = Field(description="One focused sub-question needed to answer the user")
    search_terms: str = Field(description="Plain phrase of 2-6 medical keywords, no boolean operators, no personal details")


class ResearchPlan(BaseModel):
    in_scope: bool = Field(description="True only if the question is about women's health")
    reason: str = Field(default="", description="If out of scope, a short reason")
    sub_questions: list[SubQuestion] = Field(default_factory=list, max_length=3)


class ExtractedFact(BaseModel):
    sub_question_index: int = Field(description="0-based index of the sub-question this fact answers")
    claim: str = Field(description="One plain-language factual statement")
    quote: str = Field(description="Verbatim sentence(s) copied exactly from the document that support the claim")


class ExtractedFacts(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=6)


class DraftSubAnswer(BaseModel):
    sub_question_index: int
    answer: str = Field(description="Answer citing findings like [F1]; every sentence must cite at least one finding")


class DraftConflict(BaseModel):
    description: str
    finding_ids: list[str]


class DraftReport(BaseModel):
    summary: str = Field(description="3-6 sentence overview; every sentence cites findings like [F1]")
    sub_answers: list[DraftSubAnswer] = Field(default_factory=list)
    conflicts: list[DraftConflict] = Field(default_factory=list)


class ClaimCheck(BaseModel):
    index: int = Field(description="Number of the claim being checked")
    quote_reports: str = Field(description="Exactly what outcome/result the QUOTE reports, keeping every qualifier (e.g. 'benefit in performance improvements', 'may')")
    claim_reports: str = Field(description="Exactly what outcome/result the CLAIM reports")
    differences: str = Field(description="Every added detail, dropped qualifier, changed outcome, or certainty change; 'none' if identical in meaning")
    faithful: bool = Field(description="True only if differences is 'none'")
    corrected_claim: str = Field(default="", description="If not faithful: one plain sentence saying only what the quote says")


class ClaimChecks(BaseModel):
    checks: list[ClaimCheck] = Field(default_factory=list)


class RefinedSearch(BaseModel):
    search_terms: list[str] = Field(default_factory=list, max_length=3)


# ---- Final report -----------------------------------------------------------

class Finding(BaseModel):
    id: str
    sub_question: str
    claim: str
    quote: str
    source_id: str
    source_url: str
    source_type: str
    published: str | None = None
    support_score: float


class Source(BaseModel):
    source_id: str
    title: str
    url: str
    publisher: str
    source_type: str
    published: str | None = None
    retrieved_at: str
    sha256: str


class SubAnswer(BaseModel):
    question: str
    answer: str
    finding_ids: list[str]


class Conflict(BaseModel):
    description: str
    finding_ids: list[str]


class ResearchReport(BaseModel):
    question: str
    status: Literal["complete", "partial", "no_evidence", "out_of_scope", "urgent", "blocked", "error"]
    summary: str = ""
    sub_answers: list[SubAnswer] = Field(default_factory=list)
    key_findings: list[Finding] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    search_log: list[str] = Field(default_factory=list)
    rejected_findings: int = 0
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    protocol_id: str | None = None
    models: dict[str, str] = Field(default_factory=dict)
    generated_at: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat())
    disclaimer: str = DISCLAIMER
