"""Wire the teammate's session lifecycle and safety checks to tool orchestration.

The current upstream safety rules and evidence manifest are a development
baseline, not independently clinically validated policies or source approvals.
"""

from dataclasses import replace
from datetime import datetime, timezone

from app.retrieval.exceptions import InsufficientEvidenceError, ScopeViolationError, UrgentEscalationRequired
from app.retrieval.filters import validate_educational_query_scope
from app.retrieval.config import development_evidence_enabled
from app.schemas.evidence import Disposition, EducationalCategory, EducationalResponse, ResponseType
from app.schemas.memory import MinimalPatientContext
from app.storage.consent import ConsentPolicy
from app.storage.context_tracker import ContextTracker
from app.storage.redis_session_store import get_session_store
from app.storage.session_store import EphemeralSessionStore
from app.workflow.task_store import InMemoryPendingTaskStore
from health_tools.pending_tasks import (
    PendingTaskStore, TaskTransition, advance_cycle_task, is_task_reply,
    new_cycle_task, request_input,
)
from health_tools.conversation import conversational_reply
from health_tools.deep_research import (
    GAP_EVENTS, RESEARCH_AUDIT_CODES, RESEARCH_CONSENT_TEXT, build_research_agent,
    research_available, research_preflight_allowed,
)
from health_tools.symptom_intake import (
    QUESTIONS as INTAKE_QUESTIONS, SCHEMA_VERSION as INTAKE_SCHEMA, IntakeTransition,
    advance_intake, detect_complaint, single_turn_prompt, start_intake,
)
from health_tools.workflow import Orchestrator, SafetyDecision, ToolPolicy, WorkflowResult, select_intent


class HealthApplication:
    def __init__(self, *, store=None, retrieve=None, pubmed_search=None,
                 medlineplus_search=None, europepmc_search=None,
                 clinical_trials_search=None, guideline_search=None,
                 policy=None, claim_verifier=None,
                 pending_task_store: PendingTaskStore | None = None, allow_unverified_for_development=None,
                 intake_store=None, research_agent_factory=None, research_availability=None):
        self.store = store if store is not None else get_session_store()
        self.policy = policy or ToolPolicy()
        self._retrieve_callback = retrieve
        self._engine = None
        self._pubmed_search = pubmed_search
        self._medlineplus_search = medlineplus_search
        self._europepmc_search = europepmc_search
        self._clinical_trials_search = clinical_trials_search
        self._guideline_search = guideline_search
        self._claim_verifier = claim_verifier
        self.pending_tasks = pending_task_store if pending_task_store is not None else InMemoryPendingTaskStore()
        # Symptom-intake state is kept apart from cycle-calculation tasks.
        self.intakes = intake_store if intake_store is not None else InMemoryPendingTaskStore()
        self._pending_store_failed = False
        self.allow_unverified_for_development = development_evidence_enabled(allow_unverified_for_development)
        self._research_agent_factory = research_agent_factory or build_research_agent
        self._research_availability = research_availability or research_available

    def _drop_pending(self, session_id):
        try:
            self.pending_tasks.delete(session_id)
            self.intakes.delete(session_id)
            return True
        except Exception:
            # Do not allow a later confirmation to reuse state after an outage.
            self._pending_store_failed = True
            return False

    @staticmethod
    def _task_response(transition):
        from uuid import uuid4
        asking = transition.action == "ask"
        unavailable = transition.action == "unavailable"
        response = EducationalResponse(
            request_id=f"req-{uuid4().hex[:10]}", topic="Cycle calculation inputs",
            response_type="abstention" if unavailable else "clarification" if asking else "education",
            disposition="unable_to_assess" if unavailable else "educational",
            answer=transition.message, questions=[transition.message] if asking else [],
            limitations=[], system_version="tools-orchestration-v0.3.3",
        ).model_dump(mode="json")
        # Task I/O has its own bounded turn count. It does not consume the two
        # medical-context clarification turns owned by ContextTracker.
        return WorkflowResult(response, ("SAFETY_CHECKED", transition.event))

    @staticmethod
    def _intake_response(transition: IntakeTransition):
        from uuid import uuid4
        kind, disposition = {
            "ask": ("clarification", "educational"),
            "cancel": ("clarification", "educational"),
            "summary": ("education", "routine_review"),
            "urgent": ("urgent_guidance", "emergency"),
        }[transition.action]
        limitations = []
        if transition.action in {"summary", "urgent"}:
            limitations = [
                "This is not a diagnosis. Only a clinician who can examine you can tell what is causing your symptoms.",
                "Development build: the symptom questions, red-flag rules and possible causes are pending clinician review.",
            ]
        response = EducationalResponse(
            request_id=f"req-{uuid4().hex[:10]}", topic=transition.topic or "Symptom check",
            response_type=kind, disposition=disposition, answer=transition.message,
            questions=[transition.message] if transition.action == "ask" else [],
            next_steps=list(transition.next_steps), limitations=limitations,
            protocol_id=transition.protocol_id, system_version="symptom-intake-v0.1",
        ).model_dump(mode="json")
        # Intake turns have their own bounded count and don't use the two
        # medical-context clarification turns owned by ContextTracker.
        return WorkflowResult(response, ("SAFETY_CHECKED", transition.event))

    def _intake_step(self, query, session, turn, decision, *, now):
        """Guided symptom questions, one at a time. Returns a result or None to continue normally."""
        key = session.session_id
        if (decision.action != "proceed"
                or turn.context.is_adult == "no"
                or (turn.context.age is not None and turn.context.age < 18)):
            self.intakes.delete(key)  # Safety responses always win and end any intake.
            return None
        intent = select_intent(query)
        if not session.allow_session_context:
            self.intakes.delete(key)
            complaint = detect_complaint(query) if intent == "education" else None
            if complaint is None:
                return None
            transition = start_intake(key, session.expires_at, complaint, query)
            if transition.action == "ask":
                # No memory between turns: ask for everything in one message instead.
                transition = IntakeTransition("ask", None, single_turn_prompt(complaint, query), "INTAKE_SINGLE_TURN")
            return self._intake_response(transition)

        self.intakes.purge_expired(now=now)
        intake = self.intakes.get(key, now=now)
        if intake is not None and (intake.session_id != key or getattr(intake, "schema_version", None) != INTAKE_SCHEMA):
            self.intakes.delete(key)
            intake = None
        if intake is not None:
            acknowledgement = conversational_reply(query)
            if acknowledgement and intake.asking:
                return self._intake_response(IntakeTransition(
                    "ask", intake, f"{acknowledgement.split('?')[0].split('.')[0]}. To keep going: {INTAKE_QUESTIONS[intake.asking]}",
                    "INTAKE_CONVERSATION_ACKNOWLEDGED"))
            transition = advance_intake(intake, query)
            if transition.event == "INTAKE_REASKED" and intent != "education":
                transition = IntakeTransition("topic_change", None, "", "INTAKE_TOPIC_CHANGE")  # e.g. a calculator request
            if transition.action == "ask":
                self.intakes.save(transition.intake, now=now)
                return self._intake_response(transition)
            self.intakes.delete(key)
            if transition.action == "topic_change":
                return None
        else:
            if intent != "education" or self.pending_tasks.get(key, now=now) is not None:
                return None
            complaint = detect_complaint(query)
            if complaint is None:
                return None
            transition = start_intake(key, session.expires_at, complaint, query)
            if transition.action == "ask":
                self.intakes.save(transition.intake, now=now)
        if transition.action == "summary" and transition.topic:
            turn.context.active_topic = transition.topic  # so "tell me more" follow-ups have a topic
        return self._intake_response(transition)

    def _pending_step(self, query, session, turn, decision, tool_inputs, *, now):
        """Return an optional response and possibly confirmed tool inputs."""
        key = session.session_id
        if (decision.action != "proceed"
                or turn.context.is_adult == "no"
                or (turn.context.age is not None and turn.context.age < 18)):
            self.pending_tasks.delete(key)
            return None, query, tool_inputs, ()
        self.pending_tasks.purge_expired(now=now)
        if not session.allow_session_context:
            self.pending_tasks.delete(key)
            if is_task_reply(query):
                return self._task_response(TaskTransition("cancel", message="Session context is off; there are no pending dates to confirm. Enable session context for follow-up inputs, or supply confirmed dates and a reference date together.", event="NO_PENDING_TASK")), query, tool_inputs, ()
            return None, query, tool_inputs, ()
        task = self.pending_tasks.get(key, now=now)
        events = ()
        if task is not None:
            if task.session_id != key or task.expires_at > session.expires_at or task.schema_version != "1.0":
                self.pending_tasks.delete(key)
                return self._task_response(TaskTransition("cancel", message="Pending inputs could not be validated. Start a new calculation.", event="TASK_STATE_INVALID")), query, tool_inputs, ()
            acknowledgement = conversational_reply(query)
            if acknowledgement:
                return self._task_response(TaskTransition(
                    "ask", message=acknowledgement + " Your pending calculation is unchanged; you can continue or type /cancel.",
                    event="TASK_CONVERSATION_ACKNOWLEDGED")), query, tool_inputs, ()
            transition = advance_cycle_task(task, query, now=now)
            if transition.action == "ask":
                self.pending_tasks.save(transition.task, now=now)
                return self._task_response(transition), query, tool_inputs, ()
            self.pending_tasks.delete(key)
            if transition.action == "execute":
                inputs = {**tool_inputs, "period_start_dates": list(transition.task.period_start_dates), "as_of": transition.task.as_of}
                return None, "Calculate cycle intervals", inputs, (transition.event,)
            if transition.action == "cancel":
                return self._task_response(transition), query, tool_inputs, ()
            events = (transition.event,)

        if select_intent(query) == "cycle_history" and "cycle_history" in self.policy.enabled and (
            tool_inputs.get("period_start_dates") is None or tool_inputs.get("as_of") is None
        ):
            # Explicit API inputs are already caller-confirmed. Conversation
            # extraction is always proposed and confirmed before calculation.
            task = new_cycle_task(key, session.expires_at, now=now,
                                  dates=tool_inputs.get("period_start_dates") or (), as_of=tool_inputs.get("as_of"))
            transition = request_input(task)
            self.pending_tasks.save(transition.task, now=now)
            result = self._task_response(transition)
            return replace(result, events=events + result.events), query, tool_inputs, ()
        if is_task_reply(query):
            return self._task_response(TaskTransition("cancel", message="There is no pending cycle calculation; it may have expired or been cancelled. Start with 'calculate cycle intervals', then use YYYY-MM-DD dates and confirm them. No dates were used.", event="NO_PENDING_TASK")), query, tool_inputs, ()
        return None, query, tool_inputs, events

    def _verify_answer(self, result, bundles):
        """Gate the exact final answer; never repair only a hidden claims list."""
        from app.verification.verifier import ClaimVerifier, VerificationDecision

        if "EVIDENCE_COMPLETE" not in result.events:
            return result
        try:
            candidate = EducationalResponse.model_validate(result.response)
            if not candidate.claims or not candidate.evidence or len(bundles) != 1:
                raise ValueError("Missing verification inputs")
            if self._claim_verifier is None:
                self._claim_verifier = ClaimVerifier()
            report = self._claim_verifier.verify(candidate, bundles[0].scored_passages)
            # The upstream verifier is lexical/rule based, not a clinical proof.
            # Every displayed claim must pass; a partial repair is insufficient.
            if (report.decision == VerificationDecision.ACCEPT
                    and report.total_claims == len(candidate.claims)
                    and report.supported_claims_count == len(candidate.claims)
                    and report.unsupported_claims_count == 0):
                return replace(result, events=result.events + ("CLAIM_VERIFICATION_PASSED_100",))
            event = "CLAIM_VERIFICATION_FALLBACK"
        except Exception:
            event = "CLAIM_VERIFICATION_UNAVAILABLE"
        fallback = EducationalResponse(
            request_id=result.response["request_id"], topic=result.response["topic"],
            response_type="abstention", disposition="unable_to_assess",
            answer="I could not verify the retrieved answer, so I cannot provide an evidence-based response for this request.",
            system_version=result.response["system_version"],
        ).model_dump(mode="json")
        return replace(result, response=fallback, events=result.events + (event,))

    def _retrieve(self, query, **kwargs):
        if "category" in kwargs:
            kwargs["category"] = EducationalCategory(kwargs["category"])
        kwargs.setdefault("allow_unverified_for_development", self.allow_unverified_for_development)
        if self._retrieve_callback is not None:
            return self._retrieve_callback(query, **kwargs)
        # Initialization is lazy: an urgent response must not depend on a working
        # manifest, embeddings, or network search client.
        if self._engine is None:
            from app.retrieval.pg_vector_engine import get_retrieval_engine
            self._engine = get_retrieval_engine(allow_unverified_for_development=self.allow_unverified_for_development)
        try:
            return self._engine.retrieve(query, **kwargs)
        except InsufficientEvidenceError:
            from app.retrieval.engine import RetrievalBundle
            return RetrievalBundle(query=query, manifest_version=getattr(self._engine, "manifest_version", "unknown"),
                                   scored_passages=[], citations=[])

    def _session_failure(self, query, *, now, session_id=None):
        """Keep raw-message urgent routing available during a memory outage."""
        if session_id:
            self._drop_pending(session_id)
        temporary_store = EphemeralSessionStore()
        session = temporary_store.create_session(policy=ConsentPolicy(allow_minimal_session_context=False), now=now)
        response = EducationalResponse(
            request_id="req-" + session.session_id.removeprefix("sess-"), topic="Session unavailable",
            response_type="abstention", disposition="unable_to_assess",
            answer="Session storage is unavailable. No stored context or pending dates were used; please retry later.",
            system_version="tools-orchestration-v0.3.3",
        )
        if isinstance(query, str) and query.strip() and len(query) <= 4000:
            try:
                validate_educational_query_scope(query)
            except UrgentEscalationRequired as urgent:
                response.response_type = ResponseType.URGENT_GUIDANCE
                response.disposition = Disposition.EMERGENCY
                response.answer = str(urgent)
                response.protocol_id = urgent.protocol_id
            except ScopeViolationError as scope:
                response.response_type = ResponseType.OUT_OF_SCOPE
                response.disposition = Disposition.ROUTINE_REVIEW
                response.answer = str(scope)
            except Exception:
                pass  # Controlled abstention; no raw exception or tool call.
        # Do not retain a parallel copy of history or write into the failed store.
        temporary_store.delete_session(session.session_id)
        return WorkflowResult(response.model_dump(mode="json"), ("SESSION_STORAGE_UNAVAILABLE",)), session

    def process(
        self, query, *, session_id=None, allow_session_context=None,
        now=None, _research_preflight=False, **tool_inputs,
    ) -> tuple[WorkflowResult, object]:
        """Process one turn; existing memory classes keep ownership of storage.

        None preserves the upstream default for programmatic callers. User-facing
        entry points must pass an explicit retention choice (CLI defaults to off).
        Current-turn facts are processed in a copy even when retention is off.
        """
        if allow_session_context is not None and type(allow_session_context) is not bool:
            raise ValueError("allow_session_context must be a boolean or None")
        current = now or datetime.now(timezone.utc)
        try:
            session = self.store.get_session(session_id, now=current) if session_id else None
            if session is None:
                if session_id:
                    self._drop_pending(session_id)
                policy = None if allow_session_context is None else ConsentPolicy(
                    allow_minimal_session_context=allow_session_context)
                session = self.store.create_session(policy=policy, now=current)
            elif allow_session_context is not None:
                session.allow_session_context = allow_session_context
                if not allow_session_context:
                    session.context = MinimalPatientContext()
                    self._drop_pending(session.session_id)
        except Exception:
            return self._session_failure(query, now=current, session_id=session_id)

        # Retention consent applies to saved history, not comprehension of the
        # current message. Never flip the actual stored consent flag to process it.
        turn = session.model_copy(deep=True)
        if not session.allow_session_context:
            turn.context = MinimalPatientContext()
        turn.allow_session_context = True
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            decision = SafetyDecision("unable_to_assess", "Please supply a question of 1–4000 characters.")
        else:
            try:
                ContextTracker.update_from_user_turn(turn, query)
                validate_educational_query_scope(query)
                decision = SafetyDecision("proceed")
            except UrgentEscalationRequired as urgent:
                decision = SafetyDecision("urgent", str(urgent), urgent.protocol_id)
            except ScopeViolationError as scope:
                decision = SafetyDecision("out_of_scope", str(scope))
            except Exception:
                decision = SafetyDecision("unable_to_assess", "The safety check is unavailable. Please contact a qualified healthcare professional for health concerns.")

        bundles = []

        def retrieve_turn(*args, **kwargs):
            bundle = self._retrieve(*args, **kwargs)
            bundles.append(bundle)
            return bundle

        dependencies = dict(safety_check=lambda message, context: decision,
                            retrieve=retrieve_turn,
                            policy=ToolPolicy(enabled=frozenset()) if _research_preflight else self.policy)
        if self._pubmed_search is not None:
            dependencies["pubmed_search"] = self._pubmed_search
        if self._medlineplus_search is not None:
            dependencies["medlineplus_search"] = self._medlineplus_search
        if self._europepmc_search is not None:
            dependencies["europepmc_search"] = self._europepmc_search
        if self._clinical_trials_search is not None:
            dependencies["clinical_trials_search"] = self._clinical_trials_search
        if self._guideline_search is not None:
            dependencies["guideline_search"] = self._guideline_search
        pending_result = None
        routed_query, routed_inputs, task_events = query, tool_inputs, ()
        if isinstance(query, str) and query.strip() and len(query) <= 4000:
            try:
                if self._pending_store_failed:
                    raise RuntimeError("Pending task flow disabled after storage failure")
                pending_result = self._intake_step(query, session, turn, decision, now=current)
                if pending_result is None:
                    pending_result, routed_query, routed_inputs, task_events = self._pending_step(
                        query, session, turn, decision, tool_inputs, now=current)
            except Exception:
                self._pending_store_failed = True
                # A pending-store outage must never replace an urgent/scope
                # response or permit confirmation of potentially stale inputs.
                if decision.action == "proceed" and turn.context.is_adult != "no":
                    pending_result = self._task_response(TaskTransition(
                        "unavailable", message="Pending calculation storage is unavailable. No pending inputs were used; please retry in a new session.",
                        event="TASK_STORAGE_UNAVAILABLE"))
        else:
            self._drop_pending(session.session_id)
        result = pending_result or Orchestrator(**dependencies).run(
            routed_query, session=turn, now=current, **routed_inputs)
        if task_events:
            result = replace(result, events=task_events + result.events)
        if (not session.allow_session_context and isinstance(query, str) and select_intent(query) == "cycle_history"
                and result.clarification_requested):
            note = "Enable session context for a multi-turn calculation, or supply confirmed start dates and a reference date together."
            result.response["answer"] += "\n\n" + note
        if decision.action == "out_of_scope":
            # Preserve the upstream medication/policy boundary care disposition.
            result.response["disposition"] = "routine_review"
        result = self._verify_answer(result, bundles)
        if _research_preflight:
            if research_preflight_allowed(result):
                result = replace(result, events=result.events + ("RESEARCH_ACCEPTED",))
        elif (decision.action == "proceed" and pending_result is None
              and select_intent(query) == "education"
              and turn.context.is_adult != "no"
              and not (turn.context.age is not None and turn.context.age < 18)
              and result.response["response_type"] == "abstention"
              and GAP_EVENTS.intersection(result.events)):
            try:
                available = self._research_availability()
            except Exception:
                available = False
            if available:
                result.response["research_offer"] = dict(
                    available=True, question=query,
                    reason="Approved evidence could not answer or support this question.",
                    consent_text=RESEARCH_CONSENT_TEXT,
                )
                result = replace(result, events=result.events + ("RESEARCH_OFFERED",))
        result.response["limitations"].append(
            "Development build: source-review metadata and safety rules have not been independently verified."
        )
        if self.allow_unverified_for_development:
            result.response["limitations"].append("Unverified development fixture evidence is enabled for software testing only.")
        # Validate exactly what will be rendered, before committing state.
        EducationalResponse.model_validate(result.response)
        if result.clarification_requested:
            ContextTracker.record_clarification_turn(turn, result.response["questions"][0])
        session.turn_count = turn.turn_count
        audit = turn.audit_codes + list(result.events)
        if not session.allow_session_context:
            audit = [code for code in audit if code not in RESEARCH_AUDIT_CODES]
        session.audit_codes = audit[-100:]
        if "EVIDENCE_COMPLETE" in result.events:
            session.audit_codes.append("RETRIEVAL_SUCCESS")
        session.context = turn.context if session.allow_session_context else MinimalPatientContext()
        try:
            self.store.save_session(session, now=current)
        except Exception:
            self._drop_pending(session.session_id)
            return self._session_failure(query, now=current, session_id=session.session_id)
        return result, session

    def prepare_research(self, question, *, consent=False, session_id=None,
                         allow_session_context=False, now=None):
        """Return (stop report or None, session) after the main safety/retention gate.

        Consent belongs to this invocation only; an audit code never authorizes a
        later call. Raw questions and reports are not written into session memory.
        """
        from health_tools.research.schema import ResearchReport

        def stop(status, message, protocol_id=None):
            return (ResearchReport(question=question if isinstance(question, str) else "",
                                   status=status, summary=message, protocol_id=protocol_id), None)

        if consent is not True:
            return stop("blocked", "Deep research requires explicit consent for this request. " + RESEARCH_CONSENT_TEXT)
        # The research pipeline accepts at most 2000 characters. Reject locally
        # before consuming session state or constructing any external client.
        if not isinstance(question, str) or not 3 <= len(question.strip()) <= 2000:
            return stop("blocked", "Please ask a question of 3-2000 characters.")
        if type(allow_session_context) is not bool:
            return stop("blocked", "Session context permission must be a boolean.")
        result, session = self.process(
            question, session_id=session_id, allow_session_context=allow_session_context,
            now=now, _research_preflight=True,
        )
        if "RESEARCH_ACCEPTED" not in result.events:
            kind = result.response["response_type"]
            status = ("urgent" if kind == "urgent_guidance" else "out_of_scope"
                      if "MINOR_SCOPE" in result.events else "blocked")
            report, _ = stop(status, result.response["answer"], result.response.get("protocol_id"))
            return report, session
        return None, session

    def _execute_research(self, question, *, progress=None, agent_factory=None):
        """Internal execution: callers must complete prepare_research first."""
        from health_tools.research.schema import ResearchReport
        try:
            agent = (agent_factory or self._research_agent_factory)()
            return agent.run(question, progress=progress)
        except Exception:
            return ResearchReport(question=question, status="error",
                                  summary="Research is unavailable. Please try again later.")

    def research(self, question, *, consent=False, session_id=None,
                 allow_session_context=False, progress=None, now=None):
        """Consent-gated programmatic entry point; no stored acceptance is reused."""
        report, _ = self.prepare_research(
            question, consent=consent, session_id=session_id,
            allow_session_context=allow_session_context, now=now,
        )
        return report if report is not None else self._execute_research(question, progress=progress)

    def forget(self, session_id: str) -> bool:
        pending_deleted = self._drop_pending(session_id)
        try:
            deleted = self.store.delete_session(session_id)
        except Exception:
            raise RuntimeError("Session deletion could not be confirmed because storage is unavailable.") from None
        if not pending_deleted:
            raise RuntimeError("Session context was deleted, but pending-task deletion could not be confirmed.")
        return deleted
