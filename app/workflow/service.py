"""Wire the teammate's session lifecycle and safety checks to tool orchestration.

The current upstream safety rules and evidence manifest are a development
baseline, not independently clinically validated policies or source approvals.
"""

from dataclasses import replace
from datetime import datetime, timezone

from app.retrieval.exceptions import ScopeViolationError, UrgentEscalationRequired
from app.retrieval.filters import validate_educational_query_scope
from app.schemas.evidence import EducationalCategory, EducationalResponse
from app.schemas.memory import MinimalPatientContext
from app.storage.consent import ConsentPolicy
from app.storage.context_tracker import ContextTracker
from app.storage.session_store import EphemeralSessionStore
from app.workflow.task_store import InMemoryPendingTaskStore
from health_tools.pending_tasks import (
    PendingTaskStore, TaskTransition, advance_cycle_task, is_task_reply,
    new_cycle_task, request_input,
)
from health_tools.conversation import conversational_reply
from health_tools.workflow import Orchestrator, SafetyDecision, ToolPolicy, WorkflowResult, select_intent


class HealthApplication:
    def __init__(self, *, store=None, retrieve=None, pubmed_search=None, policy=None, claim_verifier=None,
                 pending_task_store: PendingTaskStore | None = None):
        self.store = store if store is not None else EphemeralSessionStore()
        self.policy = policy or ToolPolicy()
        self._retrieve_callback = retrieve
        self._engine = None
        self._pubmed_search = pubmed_search
        self._claim_verifier = claim_verifier
        self.pending_tasks = pending_task_store if pending_task_store is not None else InMemoryPendingTaskStore()
        self._pending_store_failed = False

    def _drop_pending(self, session_id):
        try:
            self.pending_tasks.delete(session_id)
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
            limitations=[], system_version="tools-orchestration-v0.3.1",
        ).model_dump(mode="json")
        # Task I/O has its own bounded turn count. It does not consume the two
        # medical-context clarification turns owned by ContextTracker.
        return WorkflowResult(response, ("SAFETY_CHECKED", transition.event))

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
            return self._task_response(TaskTransition("cancel", message="There is no pending cycle calculation. Start a new calculation before sending dates or confirmation.", event="NO_PENDING_TASK")), query, tool_inputs, ()
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
        if self._retrieve_callback is not None:
            return self._retrieve_callback(query, **kwargs)
        # Initialization is lazy: an urgent response must not depend on a working
        # manifest, embeddings, or network search client.
        if self._engine is None:
            from app.retrieval.engine import HybridRetrievalEngine
            self._engine = HybridRetrievalEngine()
        return self._engine.retrieve(query, **kwargs)

    def process(
        self, query, *, session_id=None, allow_session_context=None,
        now=None, **tool_inputs,
    ) -> tuple[WorkflowResult, object]:
        """Process one turn; existing memory classes keep ownership of storage.

        None preserves the upstream default for programmatic callers. User-facing
        entry points must pass an explicit retention choice (CLI defaults to off).
        Current-turn facts are processed in a copy even when retention is off.
        """
        if allow_session_context is not None and type(allow_session_context) is not bool:
            raise ValueError("allow_session_context must be a boolean or None")
        current = now or datetime.now(timezone.utc)
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
                            retrieve=retrieve_turn, policy=self.policy)
        if self._pubmed_search is not None:
            dependencies["pubmed_search"] = self._pubmed_search
        pending_result = None
        routed_query, routed_inputs, task_events = query, tool_inputs, ()
        if isinstance(query, str) and query.strip() and len(query) <= 4000:
            try:
                if self._pending_store_failed:
                    raise RuntimeError("Pending task flow disabled after storage failure")
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
        result.response["limitations"].append(
            "Development build: source-review metadata and safety rules have not been independently verified."
        )
        # Validate exactly what will be rendered, before committing state.
        EducationalResponse.model_validate(result.response)
        if result.clarification_requested:
            ContextTracker.record_clarification_turn(turn, result.response["questions"][0])
        session.turn_count = turn.turn_count
        session.audit_codes = (turn.audit_codes + list(result.events))[-100:]
        if "EVIDENCE_COMPLETE" in result.events:
            session.audit_codes.append("RETRIEVAL_SUCCESS")
        session.context = turn.context if session.allow_session_context else MinimalPatientContext()
        try:
            self.store.save_session(session, now=current)
        except Exception:
            self._drop_pending(session.session_id)
            raise
        return result, session

    def forget(self, session_id: str) -> bool:
        pending_deleted = self._drop_pending(session_id)
        deleted = self.store.delete_session(session_id)
        if not pending_deleted:
            raise RuntimeError("Session context was deleted, but pending-task deletion could not be confirmed.")
        return deleted
