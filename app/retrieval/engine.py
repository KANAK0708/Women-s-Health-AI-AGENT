"""Hybrid Retrieval Engine and Guardrailed Educational Search (Wikipedia & DuckDuckGo).

Implements:
1. Governed local retrieval over versioned clinical evidence (`clinical/evidence_manifest/manifest.json`).
2. Guardrailed Wikipedia & DuckDuckGo lookup strictly scoped to:
   - What a condition is (definition/overview)
   - Recognized symptoms
   - Prevention & healthy lifestyle habits
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from langchain_community.tools import DuckDuckGoSearchRun, WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper

from app.retrieval.exceptions import InsufficientEvidenceError
from app.retrieval.filters import (
    build_constrained_educational_query,
    filter_eligible_passages,
    filter_eligible_sources,
    validate_educational_query_scope,
)
from app.retrieval.reranker import ScoredPassage, compute_hashed_embedding, rerank_passages
from app.schemas.evidence import (
    EducationalCategory,
    EvidenceCitation,
    EvidencePassage,
    SourceMetadata,
)

DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2] / "clinical" / "evidence_manifest" / "manifest.json"
)


@dataclass
class RetrievalBundle:
    """Bounded set of retrieved passages and formatted citations for a query."""

    query: str
    manifest_version: str
    scored_passages: list[ScoredPassage]
    citations: list[EvidenceCitation]

    def get_passages_by_category(self, category: EducationalCategory) -> list[EvidencePassage]:
        return [sp.passage for sp in self.scored_passages if sp.passage.category == category]

    def format_for_prompt(self) -> str:
        """Render bounded excerpts with explicit passage_id and source metadata."""
        lines: list[str] = []
        for idx, sp in enumerate(self.scored_passages, start=1):
            p = sp.passage
            lines.append(
                f"[Excerpt e{idx} | passage_id={p.passage_id} | source_id={p.source_id} | "
                f"category={p.category.value} | locator={p.locator} | reviewed={p.reviewed_at}]\n"
                f"Title: {p.title} ({p.url})\n"
                f"Content: {p.text}"
            )
        return "\n\n".join(lines)


class HybridRetrievalEngine:
    """Governed hybrid retrieval; only explicitly approved sources are eligible by default."""

    def __init__(self, manifest_path: Optional[Path] = None, *, allow_unverified_for_development: bool = False) -> None:
        self.manifest_path = manifest_path or DEFAULT_MANIFEST_PATH
        self.allow_unverified_for_development = allow_unverified_for_development
        self.manifest_version: str = "unknown"
        self.sources: list[SourceMetadata] = []
        self.passages: list[EvidencePassage] = []
        self._load_manifest()

    def _load_manifest(self) -> None:
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Evidence manifest not found at {self.manifest_path}")

        raw_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.manifest_version = raw_data.get("manifest_version", "unknown")
        self.sources = [SourceMetadata.model_validate(s) for s in raw_data.get("sources", [])]

        loaded_passages: list[EvidencePassage] = []
        for p_raw in raw_data.get("passages", []):
            passage = EvidencePassage.model_validate(p_raw)
            if passage.embedding is None:
                vec = compute_hashed_embedding(
                    f"{passage.title} {' '.join(passage.topic_tags)} {passage.text}"
                )
                passage.embedding = vec.tolist()
            loaded_passages.append(passage)

        self.passages = loaded_passages

    def retrieve(
        self,
        query: str,
        *,
        category: Optional[EducationalCategory] = None,
        jurisdiction: str = "Global",
        population: str = "adults_18+",
        reference_date: Optional[date] = None,
        max_excerpts: int = 6,
        min_score_threshold: float = 0.14,
    ) -> RetrievalBundle:
        """Validate scope, filter eligible sources/passages, rerank, and return bounded excerpts."""
        cleaned_query = validate_educational_query_scope(query)

        eligible_sources = filter_eligible_sources(
            self.sources,
            reference_date=reference_date,
            jurisdiction=jurisdiction,
            population=population,
            allow_unverified_for_development=self.allow_unverified_for_development,
        )
        eligible_passages = filter_eligible_passages(
            self.passages,
            eligible_sources,
            category=category,
        )

        scored = rerank_passages(
            cleaned_query,
            eligible_passages,
            max_candidates=20,
            max_excerpts=max_excerpts,
            min_score_threshold=min_score_threshold,
            preferred_category=category,
        )

        if not scored:
            raise InsufficientEvidenceError("No eligible passages met the local relevance threshold")

        citations: list[EvidenceCitation] = []
        for idx, item in enumerate(scored, start=1):
            p = item.passage
            citations.append(
                EvidenceCitation(
                    id=f"e{idx}",
                    source_id=p.source_id,
                    passage_id=p.passage_id,
                    title=p.title,
                    url=p.url,
                    locator=p.locator,
                    reviewed_at=str(p.reviewed_at),
                )
            )

        return RetrievalBundle(
            query=cleaned_query,
            manifest_version=self.manifest_version,
            scored_passages=scored,
            citations=citations,
        )


class GuardrailedEducationalSearch:
    """Strictly scoped Wikipedia & DuckDuckGo educational lookup for:
    1. Definition ('what this is')
    2. Recognized symptoms
    3. Prevention and healthy lifestyle habits
    """

    def __init__(self, doc_content_chars_max: int = 1600) -> None:
        self._wiki = WikipediaQueryRun(
            api_wrapper=WikipediaAPIWrapper(
                top_k_results=2,
                doc_content_chars_max=doc_content_chars_max,
            )
        )
        self._ddg = DuckDuckGoSearchRun()

    def search_wikipedia(
        self,
        topic: str,
        focus: Optional[EducationalCategory] = None,
    ) -> str:
        """Query Wikipedia strictly for definition, symptoms, or prevention."""
        constrained = build_constrained_educational_query(topic, focus=focus)
        result = self._wiki.invoke(constrained)
        return (
            f"[Educational Source: Wikipedia | Query: '{constrained}']\n"
            f"Note: Use only for general definition, symptoms, and lifestyle prevention.\n"
            f"{result}"
        )

    def search_duckduckgo(
        self,
        query: str,
        focus: Optional[EducationalCategory] = None,
    ) -> str:
        """Query DuckDuckGo strictly for definition, symptoms, or lifestyle prevention."""
        constrained = build_constrained_educational_query(query, focus=focus)
        result = self._ddg.invoke(constrained)
        return (
            f"[Educational Source: DuckDuckGo Search | Query: '{constrained}']\n"
            f"Note: Use only for general definition, symptoms, and lifestyle prevention.\n"
            f"{result}"
        )

