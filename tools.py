"""Governed Retrieval and Guardrailed Educational Search Tools.

Updates from Prototype:
1. Removed `save_tool` (autonomous model file writing to `research_output.txt`) to prevent
   sensitive health queries from entering ungoverned plaintext storage.
2. Added `retrieve_approved_evidence_tool` backed by `HybridRetrievalEngine` over versioned,
   clinician-reviewed sources (`clinical/evidence_manifest/manifest.json`).
3. Scoped `wiki_tool` (Wikipedia) and `search_tool` (DuckDuckGo) strictly to educational
   queries covering:
   - What a condition is (definition/overview)
   - Recognized symptoms
   - Prevention and healthy lifestyle habits
"""

from langchain_core.tools import tool

from app.retrieval.engine import GuardrailedEducationalSearch, HybridRetrievalEngine
from app.retrieval.exceptions import (
    InsufficientEvidenceError,
    ScopeViolationError,
    UrgentEscalationRequired,
)

_retrieval_engine = HybridRetrievalEngine()
_educational_search = GuardrailedEducationalSearch()


@tool
def retrieve_approved_evidence_tool(query: str) -> str:
    """Retrieve approved, versioned clinical evidence passages with passage IDs and URLs
    for menstrual health and PCOS (definition, symptoms, lifestyle prevention, and warning signs).
    Always call this tool first before using external educational search.
    """
    try:
        bundle = _retrieval_engine.retrieve(query)
        return bundle.format_for_prompt()
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except InsufficientEvidenceError as missing:
        return f"[INSUFFICIENT_APPROVED_EVIDENCE] {missing}"


@tool
def wiki_tool(query: str) -> str:
    """Search Wikipedia ONLY for general educational background:
    1. What a condition or health term is (definition)
    2. Common symptoms
    3. General prevention and lifestyle measures
    Never use for medication dosages, prescriptions, or individual diagnosis.
    """
    try:
        return _educational_search.search_wikipedia(query)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception as exc:
        return f"[WIKIPEDIA_UNAVAILABLE] Unable to retrieve educational overview: {exc}"


@tool
def search_tool(query: str) -> str:
    """Search DuckDuckGo ONLY for general educational information:
    1. What a condition is (definition)
    2. Recognized symptoms
    3. Evidence-based lifestyle and prevention habits
    Never use for medication dosages, prescriptions, or individual diagnosis.
    """
    try:
        return _educational_search.search_duckduckgo(query)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception as exc:
        return f"[SEARCH_UNAVAILABLE] Unable to retrieve educational search results: {exc}"


EDUCATIONAL_TOOLS = [retrieve_approved_evidence_tool, wiki_tool, search_tool]
