"""Consent text and local availability checks; importing this makes no API calls."""

import os
from pathlib import Path

RESEARCH_CONSENT_TEXT = (
    "Starting research consents to send your question, after rule-based removal of "
    "personal details, to Groq and Google Gemini; search terms go to PubMed, Europe "
    "PMC, MedlinePlus and DuckDuckGo, and pages are requested from allowed medical "
    "source sites (including WHO, NICE, ACOG, RCOG and CDC). Redaction can miss "
    "details; please leave out personal information. This is educational research, "
    "not a diagnosis or treatment plan."
)
GAP_EVENTS = frozenset({
    "EVIDENCE_EMPTY", "FOCUSED_EVIDENCE_EMPTY", "RETRIEVAL_FAILED",
    "CLAIM_VERIFICATION_FALLBACK", "CLAIM_VERIFICATION_UNAVAILABLE",
})
RESEARCH_AUDIT_CODES = frozenset({"RESEARCH_OFFERED", "RESEARCH_ACCEPTED"})


def research_available() -> bool:
    """Check configuration locally, without constructing clients or probing quotas."""
    configured = {}
    try:
        from dotenv import dotenv_values
        configured = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass
    def value(name):
        return (os.environ.get(name, configured.get(name)) or "").strip()
    keys = [value("GROQ_API_KEY"), value("GEMINI_API_KEY") or value("GOOGLE_API_KEY")]
    return any(key and not key.startswith("your_") for key in keys)


def build_research_agent():
    from health_tools.research import ResearchAgent
    from health_tools.research.llm import build_llms
    fast, long = build_llms()
    return ResearchAgent(fast, long)


def research_preflight_allowed(result) -> bool:
    """Only main-workflow safety-approved educational/literature turns qualify."""
    events = set(result.events)
    # With tools disabled, approved retrieval must stop at RETRIEVAL_BLOCKED.
    # Literature requests can instead ask for the old bibliography tool's consent;
    # that clarification is superseded by this turn's explicit deep-research consent.
    return (("INTENT_EDUCATION" in events and "RETRIEVAL_BLOCKED" in events)
            or (bool(events & {"INTENT_RESEARCH", "INTENT_MEDLINEPLUS", "INTENT_EUROPEPMC"})
                and "CLARIFICATION_REQUESTED" in events))
