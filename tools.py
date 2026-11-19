"""Governed Retrieval and Guardrailed Educational & Biomedical Research Tools.

Provides LangChain-compatible `@tool` functions with deterministic pre-retrieval
safety and scope guardrails (`validate_educational_query_scope`):
1. `retrieve_approved_evidence_tool` — Governed hybrid retrieval over `clinical/evidence_manifest/manifest.json`.
2. `medlineplus_tool` — Official NIH MedlinePlus consumer health topic summaries.
3. `pubmed_tool` — NCBI PubMed peer-reviewed biomedical literature and systematic reviews.
4. `europepmc_tool` — EMBL-EBI Europe PMC open-access biomedical literature search.
5. `clinical_trials_tool` — ClinicalTrials.gov API v2 registered study lookup.
6. `guideline_registry_tool` — Offline versioned clinical guideline registry lookup.
7. `cycle_calculator_tool` — Deterministic menstrual cycle interval and range calculator.
8. `wiki_tool` — Guardrailed Wikipedia educational background search.
9. `search_tool` — Guardrailed DuckDuckGo educational web search.
"""

from langchain_core.tools import tool

from app.retrieval.engine import GuardrailedEducationalSearch, HybridRetrievalEngine
from app.retrieval.exceptions import (
    InsufficientEvidenceError,
    ScopeViolationError,
    UrgentEscalationRequired,
)
from app.retrieval.filters import validate_educational_query_scope
from health_tools.clinical_trials import search_clinical_trials
from health_tools.contracts import ToolResult
from health_tools.cycle_history import analyze_cycle_history
from health_tools.europepmc import search_europepmc
from health_tools.guidelines import DEMO_REGISTRY, DEFAULT_REGISTRY, search_guidelines
from health_tools.medlineplus import search_medlineplus
from health_tools.pubmed import search_pubmed

_retrieval_engine = None
_educational_search = None


def _get_retrieval_engine():
    global _retrieval_engine
    if _retrieval_engine is None:
        _retrieval_engine = HybridRetrievalEngine()
    return _retrieval_engine


def _get_educational_search():
    global _educational_search
    if _educational_search is None:
        _educational_search = GuardrailedEducationalSearch()
    return _educational_search


def _format_tool_result(label: str, result: ToolResult) -> str:
    """Format a structured ToolResult into a citation-preserving prompt block."""
    if result.status == "error":
        msg = result.error.message if result.error else "Service unavailable."
        return f"[{label}_ERROR] {msg}"
    if result.status == "insufficient_data" or not result.sources:
        return f"[{label}_EMPTY] No matching records found."

    lines = [f"[Authoritative Source: {label}]"]
    for idx, src in enumerate(result.sources, start=1):
        meta = f" ({src.publication_date})" if src.publication_date else ""
        locator = f" | {src.locator}" if src.locator else ""
        excerpt = f"\nSummary: {src.excerpt}" if src.excerpt else ""
        lines.append(
            f"[{idx}] {src.title}{meta} — {src.publisher}{locator}\n"
            f"URL: {src.url}{excerpt}"
        )
    if result.limitations:
        lines.append("Limitations: " + " ".join(result.limitations))
    return "\n\n".join(lines)


@tool
def retrieve_approved_evidence_tool(query: str) -> str:
    """Retrieve approved, versioned clinical evidence passages with passage IDs and URLs
    for menstrual health, PCOS, endometriosis, dysmenorrhea, heavy menstrual bleeding,
    PMS/PMDD, uterine fibroids, and menopause (definition, assessment, symptoms,
    lifestyle prevention, and warning signs).
    Always call this tool first before using external educational search.
    """
    try:
        validate_educational_query_scope(query)
        bundle = _get_retrieval_engine().retrieve(query)
        return bundle.format_for_prompt()
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except InsufficientEvidenceError as missing:
        return f"[INSUFFICIENT_APPROVED_EVIDENCE] {missing}"
    except Exception:
        return "[RETRIEVAL_UNAVAILABLE] Unable to retrieve evidence."


@tool
def medlineplus_tool(query: str) -> str:
    """Search NIH MedlinePlus for official, plain-language consumer health topic summaries
    covering what a condition is, common symptoms, and preventive self-care.
    Do not include personal identifiers in the query.
    """
    try:
        cleaned = validate_educational_query_scope(query)
        res = search_medlineplus(cleaned, max_results=3)
        return _format_tool_result("NIH_MEDLINEPLUS", res)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[MEDLINEPLUS_UNAVAILABLE] Unable to retrieve MedlinePlus health topics."


@tool
def pubmed_tool(query: str) -> str:
    """Search NCBI PubMed for peer-reviewed biomedical research articles and systematic reviews.
    Supply non-identifying medical search terms only.
    """
    try:
        cleaned = validate_educational_query_scope(query)
        res = search_pubmed(cleaned, max_results=3)
        return _format_tool_result("NCBI_PUBMED", res)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[PUBMED_UNAVAILABLE] Unable to retrieve PubMed records."


@tool
def europepmc_tool(query: str) -> str:
    """Search EMBL-EBI Europe PMC for open-access biomedical literature, clinical reviews,
    and women's health research papers. Supply non-identifying medical search terms only.
    """
    try:
        cleaned = validate_educational_query_scope(query)
        res = search_europepmc(cleaned, max_results=3)
        return _format_tool_result("EUROPE_PMC", res)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[EUROPEPMC_UNAVAILABLE] Unable to retrieve Europe PMC literature."


@tool
def clinical_trials_tool(query: str) -> str:
    """Search ClinicalTrials.gov API v2 for registered clinical studies on women's health
    conditions (e.g., PCOS, endometriosis, dysmenorrhea, uterine fibroids).
    Supply non-identifying condition/topic terms only.
    """
    try:
        cleaned = validate_educational_query_scope(query)
        res = search_clinical_trials(cleaned, max_results=3)
        return _format_tool_result("CLINICALTRIALS_GOV", res)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[CLINICAL_TRIALS_UNAVAILABLE] Unable to retrieve ClinicalTrials.gov studies."


@tool
def guideline_registry_tool(
    query: str,
    jurisdiction: str = "Global",
    population: str = "adults",
    allow_demo: bool = False,
) -> str:
    """Search the offline versioned clinical guideline passage registry with SHA-256
    integrity verification and strict jurisdiction/population filtering.
    """
    try:
        cleaned = validate_educational_query_scope(query)
        registry_path = DEMO_REGISTRY if allow_demo else DEFAULT_REGISTRY
        res = search_guidelines(
            cleaned,
            jurisdiction=jurisdiction,
            population=population,
            registry_path=registry_path,
            allow_demo=allow_demo,
        )
        return _format_tool_result("GUIDELINE_REGISTRY", res)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[GUIDELINE_REGISTRY_UNAVAILABLE] Unable to search offline guideline registry."


@tool
def cycle_calculator_tool(period_start_dates: list[str], as_of: str) -> str:
    """Calculate menstrual cycle intervals, mean/median cycle length, variation range,
    and days elapsed since the last period from confirmed YYYY-MM-DD start dates.
    """
    try:
        res = analyze_cycle_history(period_start_dates, as_of=as_of)
        if res.status == "error":
            return f"[CYCLE_CALCULATION_ERROR] {res.error.message if res.error else 'Invalid dates.'}"
        if res.status == "insufficient_data":
            return "[CYCLE_CALCULATION_INSUFFICIENT] Provide at least two confirmed period start dates (YYYY-MM-DD)."
        d = res.data
        return (
            f"Recorded intervals: {', '.join(map(str, d['cycle_lengths_days']))} days.\n"
            f"Average recorded interval: {d['mean_cycle_length_days']} days.\n"
            f"Difference between longest and shortest: {d['interval_range_days']} days.\n"
            f"Time since the last recorded start: {d['days_since_last_recorded_start']} days."
        )
    except Exception:
        return "[CYCLE_CALCULATION_UNAVAILABLE] Unable to compute cycle intervals."


@tool
def wiki_tool(query: str) -> str:
    """Search Wikipedia ONLY for general educational background:
    1. What a condition or health term is (definition)
    2. Common symptoms
    3. General prevention and lifestyle measures
    Never use for medication dosages, prescriptions, or individual diagnosis.
    """
    try:
        validate_educational_query_scope(query)
        return _get_educational_search().search_wikipedia(query)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[WIKIPEDIA_UNAVAILABLE] Unable to retrieve educational overview."


@tool
def search_tool(query: str) -> str:
    """Search DuckDuckGo ONLY for general educational information:
    1. What a condition is (definition)
    2. Recognized symptoms
    3. Evidence-based lifestyle and prevention habits
    Never use for medication dosages, prescriptions, or individual diagnosis.
    """
    try:
        validate_educational_query_scope(query)
        return _get_educational_search().search_duckduckgo(query)
    except UrgentEscalationRequired as urgent:
        return f"[URGENT_PROTOCOL={urgent.protocol_id}] {urgent}"
    except ScopeViolationError as violation:
        return f"[SCOPE_POLICY_BLOCK] {violation}"
    except Exception:
        return "[SEARCH_UNAVAILABLE] Unable to retrieve educational search results."


EDUCATIONAL_TOOLS = [
    retrieve_approved_evidence_tool,
    medlineplus_tool,
    pubmed_tool,
    europepmc_tool,
    clinical_trials_tool,
    guideline_registry_tool,
    cycle_calculator_tool,
    wiki_tool,
    search_tool,
]
