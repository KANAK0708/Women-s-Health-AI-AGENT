"""Evidence, citation, and response contracts for the Women's Health AI Agent.

Implements Section 2, Section 6, and Section 8 of the Implementation Plan:
- Governed source metadata with supersession, expiry, jurisdiction, and population.
- Versioned evidence passages with verbatim text and section locators.
- Non-diagnostic EducationalResponse schema focused on:
  1. Definition ('what_it_is')
  2. Recognized symptoms ('symptoms')
  3. Prevention & lifestyle habits ('prevention_and_lifestyle')
"""

from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EducationalCategory(str, Enum):
    DEFINITION = "what_it_is"
    SYMPTOMS = "symptoms"
    PREVENTION_LIFESTYLE = "prevention_and_lifestyle"
    WHEN_TO_SEEK_CARE = "when_to_seek_care"


class ResponseType(str, Enum):
    EDUCATION = "education"
    CLARIFICATION = "clarification"
    URGENT_GUIDANCE = "urgent_guidance"
    OUT_OF_SCOPE = "out_of_scope"
    ABSTENTION = "abstention"


class Disposition(str, Enum):
    EDUCATIONAL = "educational"
    ROUTINE_REVIEW = "routine_review"
    PROMPT_REVIEW = "prompt_review"
    EMERGENCY = "emergency"
    UNABLE_TO_ASSESS = "unable_to_assess"


class SourceMetadata(BaseModel):
    """Governed metadata for an approved clinical or public-health source."""

    source_id: str
    publisher: str
    title: str
    canonical_url: str
    publication_date: date
    update_date: Optional[date] = None
    ingestion_date: date
    review_date: date
    expiry_date: date
    jurisdiction: str = Field(default="Global", description="e.g., Global, US, UK, IN")
    population: str = Field(default="adults_18+", description="Target validated population")
    life_stage: list[str] = Field(default_factory=lambda: ["menstrual_health", "pcos"])
    evidence_grade: Optional[str] = Field(
        default=None,
        description="Explicit grade supplied by the source; never inferred if absent.",
    )
    reviewer_id: str
    license: str
    content_hash: str
    is_superseded: bool = False


class EvidencePassage(BaseModel):
    """A single versioned, verbatim excerpt from an approved source."""

    passage_id: str
    source_id: str
    title: str
    url: str
    locator: str = Field(description="Exact section or page locator")
    category: EducationalCategory
    topic_tags: list[str] = Field(default_factory=list)
    text: str = Field(description="Exact verbatim text from the source")
    reviewed_at: date
    embedding: Optional[list[float]] = Field(default=None, exclude=True)


class ClaimItem(BaseModel):
    """A material educational statement mapped to supporting passage IDs."""

    id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceCitation(BaseModel):
    """Public citation metadata returned with the response."""

    id: str
    source_id: str
    passage_id: str
    title: str
    url: str
    locator: str
    reviewed_at: str


class EducationalResponse(BaseModel):
    """Typed, non-diagnostic response contract (replaces prototype HealthResponse)."""

    request_id: str
    response_type: ResponseType = ResponseType.EDUCATION
    disposition: Disposition = Disposition.EDUCATIONAL
    topic: str
    what_it_is: str = Field(
        default="",
        description="Clear, plain-language explanation of what the condition or topic is.",
    )
    symptoms: list[str] = Field(
        default_factory=list,
        description="Commonly recognized symptoms from educational sources.",
    )
    prevention_and_lifestyle: list[str] = Field(
        default_factory=list,
        description="Evidence-based lifestyle, wellness, and preventive habits.",
    )
    answer: str = Field(
        description="Unified plain-language summary whose claims map to evidence IDs."
    )
    claims: list[ClaimItem] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(
        default_factory=lambda: [
            "This educational information cannot establish an individual medical diagnosis.",
            "Consult a qualified healthcare professional for persistent or severe symptoms.",
        ]
    )
    evidence: list[EvidenceCitation] = Field(default_factory=list)
    protocol_id: Optional[str] = None
    system_version: str = "v1.0.0-pilot"
