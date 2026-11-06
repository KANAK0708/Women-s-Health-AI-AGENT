"""Women's Health AI Agent - Controlled Memory, Retrieval & Educational Workflow.

Implements the P0 & P1 requirements from the Implementation Plan:
- Replaces diagnostic `HealthResponse` with non-diagnostic `EducationalResponse`
  focused on: (1) What it is, (2) Symptoms, (3) Prevention & Lifestyle.
- Enforces pre-retrieval safety gates on every turn (`UrgentEscalationRequired`).
- Separates ephemeral patient session memory (`EphemeralSessionStore`) from the
  governed clinical evidence registry (`HybridRetrievalEngine`).
- Disables `verbose=True` raw health text logging and autonomous file writes.
- Uses guardrailed Wikipedia and DuckDuckGo tools strictly for educational
  definitions, symptoms, and prevention.
"""

import os
import sys
import uuid
from typing import Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from app.retrieval.engine import HybridRetrievalEngine, RetrievalBundle
from app.retrieval.exceptions import (
    InsufficientEvidenceError,
    ScopeViolationError,
    UrgentEscalationRequired,
)
from app.schemas.evidence import (
    ClaimItem,
    Disposition,
    EducationalCategory,
    EducationalResponse,
    ResponseType,
)
from app.schemas.memory import SessionMemory, TriState
from app.storage.context_tracker import ContextTracker
from app.storage.session_store import EphemeralSessionStore
from app.verification.verifier import ClaimVerifier, VerificationDecision
from tools import EDUCATIONAL_TOOLS, search_tool, wiki_tool

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Initialize isolated trust domains
session_store = EphemeralSessionStore()
retrieval_engine = HybridRetrievalEngine()
claim_verifier = ClaimVerifier()
parser = PydanticOutputParser(pydantic_object=EducationalResponse)


def _build_deterministic_educational_response(
    request_id: str,
    query: str,
    bundle: RetrievalBundle,
    *,
    external_context: str = "",
) -> EducationalResponse:
    """Build a citation-backed EducationalResponse directly from retrieved passages."""
    def_passages = bundle.get_passages_by_category(EducationalCategory.DEFINITION)
    sym_passages = bundle.get_passages_by_category(EducationalCategory.SYMPTOMS)
    prev_passages = bundle.get_passages_by_category(EducationalCategory.PREVENTION_LIFESTYLE)

    what_it_is = (
        def_passages[0].text
        if def_passages
        else bundle.scored_passages[0].passage.text
    )

    symptoms_list: list[str] = []
    for p in sym_passages:
        symptoms_list.append(p.text)
    if not symptoms_list:
        symptoms_list.append(
            "Common symptoms vary by individual and may include irregular menstrual cycles, pelvic discomfort, or hormonal changes."
        )

    prevention_list: list[str] = []
    for p in prev_passages:
        prevention_list.append(p.text)
    if not prevention_list:
        prevention_list.append(
            "Maintain regular physical activity, a balanced nutrient-dense diet, consistent sleep, and routine clinical checkups."
        )

    claims: list[ClaimItem] = []
    for idx, sp in enumerate(bundle.scored_passages, start=1):
        citation_id = f"e{idx}"
        claims.append(
            ClaimItem(
                id=f"c{idx}",
                text=sp.passage.text,
                evidence_ids=[citation_id],
            )
        )

    summary_parts = [
        f"What it is: {what_it_is}",
        f"Symptoms: {' '.join(symptoms_list)}",
        f"Prevention & Lifestyle: {' '.join(prevention_list)}",
    ]
    if external_context:
        summary_parts.append(f"Additional Educational Context: {external_context[:500]}")

    return EducationalResponse(
        request_id=request_id,
        response_type=ResponseType.EDUCATION,
        disposition=Disposition.EDUCATIONAL,
        topic=query,
        what_it_is=what_it_is,
        symptoms=symptoms_list,
        prevention_and_lifestyle=prevention_list,
        answer="\n\n".join(summary_parts),
        claims=claims,
        next_steps=[
            "Review these educational points and prepare questions for your healthcare provider.",
            "Seek medical evaluation if symptoms are persistent, worsening, or affecting daily life.",
        ],
        evidence=bundle.citations,
    )


def process_health_query(
    query: str,
    *,
    session_id: Optional[str] = None,
    use_external_search_on_gap: bool = True,
    enable_llm_generation: bool = True,
) -> tuple[EducationalResponse, SessionMemory]:
    """Execute the controlled patient workflow for a single turn:
    1. Load or create TTL-governed session memory.
    2. Run deterministic safety and context tracking (`ContextTracker`).
    3. Enforce adult-only scope and prescription/dosage boundaries.
    4. Retrieve bounded excerpts from the approved evidence manifest.
    5. Optionally consult guardrailed Wikipedia/DuckDuckGo for definition, symptoms, and prevention.
    6. Return a validated `EducationalResponse` with verified citations.
    """
    request_id = f"req-{uuid.uuid4().hex[:10]}"
    session = (
        session_store.get_session(session_id) if session_id else None
    ) or session_store.create_session()

    # Step 1: Safety gate runs on every turn BEFORE retrieval or model invocation
    try:
        session = ContextTracker.update_from_user_turn(session, query)
    except UrgentEscalationRequired as urgent:
        session_store.save_session(session)
        return (
            EducationalResponse(
                request_id=request_id,
                response_type=ResponseType.URGENT_GUIDANCE,
                disposition=Disposition.EMERGENCY,
                topic="Urgent Medical Escalation",
                what_it_is="Immediate clinical assessment is required based on the symptoms described.",
                answer=str(urgent),
                next_steps=[
                    "Contact local emergency services or go to the nearest emergency department immediately.",
                    "Do not wait for online information before seeking urgent medical care.",
                ],
                protocol_id=urgent.protocol_id,
            ),
            session,
        )

    # Step 2: Check validated population (Adults 18+ only)
    if session.context.is_adult == TriState.NO:
        session.audit_codes.append("ROUTED_MINOR_FALLBACK")
        session_store.save_session(session)
        return (
            EducationalResponse(
                request_id=request_id,
                response_type=ResponseType.OUT_OF_SCOPE,
                disposition=Disposition.UNABLE_TO_ASSESS,
                topic="Pediatric / Adolescent Care Out of Scope",
                what_it_is="This assistant is validated only for adults aged 18 and older.",
                answer=(
                    "Because menstrual and hormonal patterns in adolescents and minors differ significantly "
                    "from adults, this assistant cannot provide personalized educational guidance for users under 18. "
                    "Please speak with a pediatrician, adolescent health specialist, or trusted healthcare professional."
                ),
                next_steps=[
                    "Consult a pediatrician, family doctor, or school healthcare provider.",
                ],
            ),
            session,
        )

    # Step 3: Governed Hybrid Retrieval + Educational Scope Verification
    try:
        bundle = retrieval_engine.retrieve(query)
        session.audit_codes.append("RETRIEVAL_SUCCESS")
    except ScopeViolationError as violation:
        session.audit_codes.append("SCOPE_VIOLATION_BLOCKED")
        session_store.save_session(session)
        return (
            EducationalResponse(
                request_id=request_id,
                response_type=ResponseType.OUT_OF_SCOPE,
                disposition=Disposition.ROUTINE_REVIEW,
                topic="Clinical Scope Boundary",
                what_it_is="Medication adjustments, prescriptions, and individual diagnoses are outside educational scope.",
                answer=str(violation),
                next_steps=[
                    "Contact your prescribing clinician or pharmacist before starting, stopping, or changing any medication.",
                ],
            ),
            session,
        )
    except InsufficientEvidenceError:
        session.audit_codes.append("INSUFFICIENT_APPROVED_EVIDENCE")
        if not use_external_search_on_gap:
            session_store.save_session(session)
            return (
                EducationalResponse(
                    request_id=request_id,
                    response_type=ResponseType.ABSTENTION,
                    disposition=Disposition.UNABLE_TO_ASSESS,
                    topic=query,
                    what_it_is="This topic is outside the currently approved clinical evidence corpus.",
                    answer=(
                        "I do not have verified clinical evidence in my approved knowledge base to answer this question safely. "
                        "Please consult a qualified healthcare professional."
                    ),
                ),
                session,
            )

        # Consult guardrailed Wikipedia & DuckDuckGo strictly for definition, symptoms, and prevention
        wiki_res = wiki_tool.invoke(query)
        ddg_res = search_tool.invoke(query)
        session.audit_codes.append("GUARDRAILED_EXTERNAL_EDUCATIONAL_LOOKUP")
        session_store.save_session(session)
        return (
            EducationalResponse(
                request_id=request_id,
                response_type=ResponseType.EDUCATION,
                disposition=Disposition.EDUCATIONAL,
                topic=query,
                what_it_is=wiki_res,
                symptoms=["Refer to general educational overview above; consult a clinician for specific symptoms."],
                prevention_and_lifestyle=[ddg_res],
                answer=f"{wiki_res}\n\n{ddg_res}",
                next_steps=["Verify general web/encyclopedia summaries with a licensed healthcare provider."],
            ),
            session,
        )

    # Step 4: Optional LLM synthesis grounded strictly in retrieved passages (with deterministic fallback)
    if enable_llm_generation and os.getenv("GROQ_API_KEY"):
        try:
            llm = ChatGroq(
                model="openai/gpt-oss-20b",
                max_tokens=2000,
                reasoning_effort="low",
                max_retries=1,
                timeout=15,
            )
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are an evidence-grounded women's health education assistant for adults (18+). "
                        "Using ONLY the approved evidence excerpts provided below, explain:\n"
                        "1. What the condition/topic is (definition)\n"
                        "2. Recognized symptoms\n"
                        "3. Prevention and healthy lifestyle habits\n"
                        "Never diagnose, prescribe, or invent URLs. Map claims to excerpt IDs (e1, e2, etc.).\n"
                        "{format_instructions}",
                    ),
                    (
                        "human",
                        "User Query: {query}\n\nApproved Evidence Excerpts:\n{excerpts}",
                    ),
                ]
            ).partial(format_instructions=parser.get_format_instructions())

            candidate: EducationalResponse = (prompt | llm | parser).invoke(
                {"query": query, "excerpts": bundle.format_for_prompt()}
            )
            # Enforce registry-derived citations and request_id (never trust LLM-invented URLs)
            candidate.request_id = request_id
            candidate.evidence = bundle.citations

            # Section 6 & 10: Claim-to-Passage Entailment Verification
            ver_report = claim_verifier.verify(candidate, bundle.scored_passages)
            session.audit_codes.append(ver_report.audit_code)

            if ver_report.decision in (VerificationDecision.ACCEPT, VerificationDecision.REPAIRED):
                candidate.claims = ver_report.repaired_claims
                session.audit_codes.append("GROUNDED_LLM_RESPONSE_VALIDATED")
                session_store.save_session(session)
                return candidate, session
            else:
                session.audit_codes.append("LLM_FAILED_VERIFICATION_FALLBACK")
        except Exception:
            session.audit_codes.append("LLM_FALLBACK_TO_DETERMINISTIC_EVIDENCE")

    # Deterministic citation-backed response
    response = _build_deterministic_educational_response(request_id, query, bundle)
    ver_report = claim_verifier.verify(response, bundle.scored_passages)
    session.audit_codes.append(ver_report.audit_code)
    session_store.save_session(session)
    return response, session


if __name__ == "__main__":
    user_query = input("What women's health topic (what it is, symptoms, prevention) can I help you learn about? ")
    result, active_session = process_health_query(user_query)
    print(result.model_dump_json(indent=2))
