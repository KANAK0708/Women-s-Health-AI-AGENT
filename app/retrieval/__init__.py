"""Retrieval and Evidence Governance package."""

from app.retrieval.engine import (
    GuardrailedEducationalSearch,
    HybridRetrievalEngine,
    RetrievalBundle,
)
from app.retrieval.exceptions import (
    InsufficientEvidenceError,
    RetrievalError,
    ScopeViolationError,
    UrgentEscalationRequired,
)
from app.retrieval.filters import (
    build_constrained_educational_query,
    check_urgent_hazards,
    filter_eligible_passages,
    filter_eligible_sources,
    validate_educational_query_scope,
)
from app.retrieval.reranker import ScoredPassage, rerank_passages


def __getattr__(name):
    if name in {"PgVectorHybridEngine", "get_retrieval_engine"}:
        from app.retrieval import pg_vector_engine
        return getattr(pg_vector_engine, name)
    raise AttributeError(name)

__all__ = [
    "GuardrailedEducationalSearch",
    "HybridRetrievalEngine",
    "InsufficientEvidenceError",
    "PgVectorHybridEngine",
    "RetrievalBundle",
    "RetrievalError",
    "ScopeViolationError",
    "ScoredPassage",
    "UrgentEscalationRequired",
    "build_constrained_educational_query",
    "check_urgent_hazards",
    "filter_eligible_passages",
    "filter_eligible_sources",
    "get_retrieval_engine",
    "rerank_passages",
    "validate_educational_query_scope",
]


