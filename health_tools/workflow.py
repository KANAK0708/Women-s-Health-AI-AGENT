"""Bounded orchestration over injected safety, memory, retrieval, and tools.

This first version uses deterministic routing and exact evidence excerpts, not
an autonomous LLM planner. The application's reviewed safety policy is required.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .contracts import ToolResult
from .cycle_history import analyze_cycle_history
from .handoff import ContextSnapshot, EvidenceSnapshot, adapt_retrieval, adapt_session, validate_claim_references
from .pubmed import search_pubmed
from .answer_selection import FACETS, question_focus, select_passages
from .conversation import conversational_reply
from .cycle_help import CYCLE_HELP, asks_how_calculator_works, medical_part_of_calculator_question


@dataclass(frozen=True)
class SafetyDecision:
    action: str  # proceed | urgent | out_of_scope | unable_to_assess
    message: str = ""
    protocol_id: str | None = None

    def __post_init__(self):
        if self.action not in {"proceed", "urgent", "out_of_scope", "unable_to_assess"}:
            raise ValueError("Invalid safety decision")
        if self.action != "proceed" and (not isinstance(self.message, str) or not self.message.strip()):
            raise ValueError("A stopped workflow needs an explicit message")
        if self.action == "urgent" and not self.protocol_id:
            raise ValueError("Urgent decisions require a protocol ID")


@dataclass(frozen=True)
class ToolPolicy:
    enabled: frozenset[str] = frozenset({"cycle_history", "pubmed", "approved_retrieval"})
    max_tool_calls: int = 2
    max_passages: int = 5
    max_passage_chars: int = 12000
    pubmed_max_results: int = 3
    pubmed_timeout_seconds: float = 10

    def __post_init__(self):
        if not isinstance(self.enabled, frozenset) or not self.enabled <= {"cycle_history", "pubmed", "approved_retrieval"}:
            raise ValueError("Unknown or mutable tool configuration")
        for value, maximum in ((self.max_tool_calls, 3), (self.max_passages, 6),
                               (self.max_passage_chars, 20000), (self.pubmed_max_results, 5)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid tool bound")
        if isinstance(self.pubmed_timeout_seconds, bool) or not isinstance(self.pubmed_timeout_seconds, (int, float)) or not 0 < self.pubmed_timeout_seconds <= 30:
            raise ValueError("Invalid PubMed timeout")


@dataclass(frozen=True)
class WorkflowResult:
    response: dict
    events: tuple[str, ...]  # Codes only; no prompts, dates, or exception contents.
    tool_results: tuple[ToolResult, ...] = ()  # Sensitive: not operational logs.
    clarification_requested: bool = False


def select_intent(query: str) -> str:
    """Small transparent router; not a clinical or safety classifier."""
    lowered = query.casefold()
    if asks_how_calculator_works(query):
        return "cycle_explanation"
    if re.search(r"\b(calculate|calculations?|compute|analyse|analyze|summarize|summary)\b", lowered) and re.search(r"\b(periods?|cycles?|dates?)\b", lowered):
        return "cycle_history"
    if re.search(r"\b(pubmed|research|studies|papers|systematic review)\b", lowered):
        return "research"
    return "education"


class Orchestrator:
    def __init__(
        self, *, safety_check: Callable[[str, ContextSnapshot], SafetyDecision],
        retrieve: Callable, policy: ToolPolicy | None = None,
        pubmed_search: Callable = search_pubmed,
    ):
        if not callable(safety_check) or not callable(retrieve) or not callable(pubmed_search):
            raise ValueError("Safety, retrieval, and research dependencies must be callable")
        self.safety_check = safety_check
        self.retrieve = retrieve
        self.policy = policy or ToolPolicy()
        self.pubmed_search = pubmed_search

    def run(
        self, query: str, *, session=None, now: datetime | None = None,
        period_start_dates: list[str] | None = None, as_of: str | None = None,
        jurisdiction: str = "Global", population: str = "adults_18+",
        allow_external_research: bool = False, research_query: str | None = None,
    ) -> WorkflowResult:
        """Run one turn. No storage writes; caller records clarifications in memory.

        research_query is a caller-reviewed non-identifying query, never copied
        automatically from the raw user message. No automatic external fallback.
        Safety/context extraction for the current turn belongs to the application.
        """
        events = []
        outputs = []
        calls = 0
        cycle_help = ""
        response = {
            "request_id": f"req-{uuid.uuid4().hex[:10]}", "response_type": "abstention",
            "disposition": "unable_to_assess", "topic": "PCOS and menstrual health",
            "what_it_is": "", "symptoms": [], "prevention_and_lifestyle": [],
            "answer": "", "claims": [], "questions": [], "next_steps": [],
            "limitations": [], "evidence": [], "protocol_id": None,
            "system_version": "tools-orchestration-v0.3.3",
        }

        def finish(message, *, event, kind="abstention", disposition="unable_to_assess", question=False):
            if cycle_help and cycle_help not in message:
                message += "\n\n" + cycle_help
            response.update(answer=message, response_type=kind, disposition=disposition)
            events.append(event)
            return WorkflowResult(response, tuple(events), tuple(outputs), question)

        def call_tool(name, operation):
            nonlocal calls
            if name not in self.policy.enabled or calls >= self.policy.max_tool_calls:
                events.append("TOOL_POLICY_BLOCK")
                return None
            calls += 1
            events.append("TOOL_" + name.upper())
            return operation()

        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            return finish("Please supply a question of 1–4000 characters.", event="INVALID_QUERY")
        # Always check the current message even when historical memory is malformed.
        context_error = False
        try:
            context = adapt_session(session, now=now)
        except Exception:
            context = ContextSnapshot(unavailable_reason="invalid_context")
            context_error = True
        try:
            decision = self.safety_check(query, context)
            if not isinstance(decision, SafetyDecision):
                raise ValueError("Invalid safety result")
        except Exception:
            return finish("The safety check is unavailable. I cannot assess this request; please contact a qualified healthcare professional for health concerns.", event="SAFETY_UNAVAILABLE")
        events.append("SAFETY_CHECKED")
        if decision.action != "proceed":
            response["protocol_id"] = decision.protocol_id
            kind, disposition = {
                "urgent": ("urgent_guidance", "emergency"),
                "out_of_scope": ("out_of_scope", "unable_to_assess"),
                "unable_to_assess": ("abstention", "unable_to_assess"),
            }[decision.action]
            return finish(decision.message, event="SAFETY_STOP", kind=kind, disposition=disposition)
        if context_error:
            return finish("Session context could not be validated. Please retry without stored context.", event="CONTEXT_INVALID")
        if context.is_adult == "no" or (context.age is not None and context.age < 18):
            return finish("This workflow supports adult education only. Please consult an appropriate healthcare professional.", event="MINOR_SCOPE", kind="out_of_scope")

        acknowledgement = conversational_reply(query)
        if acknowledgement:
            response["questions"] = [acknowledgement]
            # Social acknowledgements do not consume medical clarification turns.
            return finish(acknowledgement, event="CONVERSATION_ACKNOWLEDGED", kind="clarification", disposition="educational")

        def clarify(message):
            if context.clarification_turns_used >= 2:
                return finish("Required information is still missing, so I cannot complete this request.", event="CLARIFICATION_LIMIT")
            response["questions"] = [message]
            return finish(message, event="CLARIFICATION_REQUESTED", kind="clarification", question=True)

        intent = select_intent(query)
        events.append("INTENT_" + intent.upper())
        if intent == "cycle_explanation":
            cycle_help = CYCLE_HELP
            medical_query = medical_part_of_calculator_question(query)
            if medical_query is None:
                return finish(CYCLE_HELP, event="CYCLE_EXPLAINED", kind="education", disposition="educational")
            query = medical_query
        if intent == "cycle_history":
            if period_start_dates is None:
                return clarify("Please provide confirmed period start dates from oldest to newest (YYYY-MM-DD), plus your local reference date.")
            if as_of is None:
                return clarify("What local date should I use as the reference date (YYYY-MM-DD)?")
            result = call_tool("cycle_history", lambda: analyze_cycle_history(period_start_dates, as_of=as_of))
            if result is None:
                return finish("Cycle calculations are disabled or the tool-call limit was reached.", event="CYCLE_UNAVAILABLE")
            outputs.append(result)
            response["limitations"] = list(result.limitations)
            if result.status == "error":
                return clarify(result.error.message)
            if result.status == "insufficient_data":
                return clarify("Please provide at least two confirmed period start dates to calculate an interval.")
            data = result.data
            answer = (
                f"Recorded intervals: {', '.join(map(str, data['cycle_lengths_days']))} days.\n"
                f"Average recorded interval: {data['mean_cycle_length_days']} days.\n"
                f"Difference between longest and shortest: {data['interval_range_days']} days.\n"
                f"Time since the last recorded start: {data['days_since_last_recorded_start']} days."
            )
            return finish(answer, event="CYCLE_COMPLETE", kind="education", disposition="educational")

        if intent == "research":
            if allow_external_research is not True or not isinstance(research_query, str) or not research_query.strip():
                return clarify("May I search PubMed using research terms you have reviewed to exclude personal details? Supply those terms separately.")
            try:
                result = call_tool("pubmed", lambda: self.pubmed_search(
                    research_query, max_results=self.policy.pubmed_max_results,
                    timeout=self.policy.pubmed_timeout_seconds,
                ))
                if result is not None and (not isinstance(result, ToolResult) or result.tool != "search_pubmed"):
                    raise ValueError("Invalid research result")
            except Exception:
                return finish("Research search is unavailable. No answer was generated from missing research.", event="RESEARCH_FAILED")
            if result is None:
                return finish("PubMed search is disabled or the tool-call limit was reached.", event="RESEARCH_BLOCKED")
            outputs.append(result)
            response["limitations"] = list(result.limitations)
            if result.status != "ok":
                return finish("PubMed could not provide research records for this request. You can try again later or revise the research terms.", event="RESEARCH_INCOMPLETE")
            # Bibliography only: research abstracts are not promoted to clinical claims.
            if not result.sources:
                return finish("No research citations were returned.", event="RESEARCH_EMPTY")
            lines = ["Research records retrieved (not a clinical recommendation):"]
            for source in result.sources:
                lines.append(f"{source.title} ({source.publication_date or 'date not supplied'})\n{source.url}")
            return finish("\n\n".join(lines), event="RESEARCH_COMPLETE", kind="education", disposition="educational")

        if not isinstance(jurisdiction, str) or not jurisdiction.strip() or population != "adults_18+":
            return finish("A supported jurisdiction and adult population must be configured.", event="INVALID_RETRIEVAL_SCOPE")
        focus = question_focus(query, active_topic=context.active_topic)
        if focus.needs_topic:
            return clarify("Which topic would you like explained first—PCOS, periods, or cycle calculations?")
        try:
            retrieval_options = dict(jurisdiction=jurisdiction, population=population,
                                     max_excerpts=self.policy.max_passages)
            requested_categories = {FACETS[facet][0] for facet in focus.facets}
            if len(requested_categories) == 1:
                retrieval_options["category"] = next(iter(requested_categories))
            bundle = call_tool("approved_retrieval", lambda: self.retrieve(
                focus.retrieval_query, **retrieval_options))
            if bundle is None:
                return finish("Approved-evidence retrieval is disabled or its call limit was reached.", event="RETRIEVAL_BLOCKED")
            evidence = adapt_retrieval(bundle)
            if len(evidence.passages) > self.policy.max_passages or any(
                len(item.text) > self.policy.max_passage_chars for item in evidence.passages
            ):
                raise ValueError("Retrieval exceeded configured bounds")
            if not evidence.passages:
                return finish("I do not have matching approved evidence to answer this question.", event="EVIDENCE_EMPTY")
            selected, missing = select_passages(evidence, focus)
            if not selected:
                labels = ", ".join(FACETS[facet][1].lower() for facet in missing)
                return finish(f"I do not have a retrieved passage covering {labels} for this question.", event="FOCUSED_EVIDENCE_EMPTY")
            filtered = EvidenceSnapshot(evidence.manifest_version, tuple(item for _, item in selected))
            self._populate_evidence(response, filtered, selected, missing)
            if cycle_help:
                response["answer"] += "\n\n" + cycle_help
            events.append("ANSWER_FOCUSED")
        except Exception:
            return finish("Approved evidence could not be validated or retrieved. I cannot provide an evidence-based answer for this request.", event="RETRIEVAL_FAILED")
        return finish(response["answer"], event="EVIDENCE_COMPLETE", kind="education", disposition="educational")

    @staticmethod
    def _populate_evidence(response: dict, evidence: EvidenceSnapshot, selected, missing):
        claims = [dict(id=f"c{index}", text=item.text, evidence_ids=[item.citation_id])
                  for index, item in enumerate(evidence.passages, 1)]
        validate_claim_references(claims, evidence)
        citations = [dict(id=item.citation_id, source_id=item.source_id, passage_id=item.passage_id,
                          title=item.title, url=item.url, locator=item.locator, reviewed_at=item.reviewed_at)
                     for item in evidence.passages]
        # Build locally before updating: a failed validation cannot leak a partial answer.
        categories = {"what_it_is", "symptoms", "prevention_and_lifestyle", "when_to_seek_care"}
        if any(item.category not in categories for item in evidence.passages):
            raise ValueError("Unsupported evidence category")
        definitions = [item.text for item in evidence.passages if item.category == "what_it_is"]
        response.update(
            claims=claims, evidence=citations,
            what_it_is="\n\n".join(definitions),
            symptoms=[item.text for item in evidence.passages if item.category == "symptoms"],
            prevention_and_lifestyle=[item.text for item in evidence.passages if item.category == "prevention_and_lifestyle"],
            answer="\n\n".join(
                f"{FACETS[facet][1]}\n[{item.citation_id}] {item.text}" for facet, item in selected),
            limitations=[
                "Exact retrieved excerpts are shown; individual applicability has not been established.",
                "This response does not establish a diagnosis or prescribe treatment.",
                f"Evidence manifest: {evidence.manifest_version}",
            ],
        )
        if missing:
            note = "Not covered by the retrieved evidence: " + ", ".join(FACETS[facet][1].lower() for facet in missing) + "."
            response["answer"] += "\n\n" + note
            response["limitations"].append(note)


def render_response(result: WorkflowResult) -> str:
    """Plain-text view of the same final object; no second model/claim rewrite."""
    response = result.response
    sections = [response["answer"]]
    if response["evidence"]:
        sections.append("Sources:\n" + "\n".join(
            f"[{item['id']}] {item['title']} — {item['locator']}\n{item['url']}"
            for item in response["evidence"]))
    visible_limits = [item for item in response["limitations"] if item not in response["answer"]]
    if visible_limits:
        sections.append("Limitations:\n" + "\n".join(f"- {item}" for item in visible_limits))
    return "\n\n".join(sections)
