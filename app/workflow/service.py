"""Wire the teammate's session lifecycle and safety checks to tool orchestration.

The current upstream safety rules and evidence manifest are a development
baseline, not independently clinically validated policies or source approvals.
"""

from datetime import datetime, timezone

from app.retrieval.exceptions import ScopeViolationError, UrgentEscalationRequired
from app.retrieval.filters import validate_educational_query_scope
from app.schemas.evidence import EducationalResponse
from app.schemas.memory import MinimalPatientContext
from app.storage.consent import ConsentPolicy
from app.storage.context_tracker import ContextTracker
from app.storage.session_store import EphemeralSessionStore
from health_tools.workflow import Orchestrator, SafetyDecision, ToolPolicy, WorkflowResult


class HealthApplication:
    def __init__(self, *, store=None, retrieve=None, pubmed_search=None, policy=None):
        self.store = store if store is not None else EphemeralSessionStore()
        self.policy = policy or ToolPolicy()
        self._retrieve_callback = retrieve
        self._engine = None
        self._pubmed_search = pubmed_search

    def _retrieve(self, query, **kwargs):
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
            policy = None if allow_session_context is None else ConsentPolicy(
                allow_minimal_session_context=allow_session_context)
            session = self.store.create_session(policy=policy, now=current)
        elif allow_session_context is not None:
            session.allow_session_context = allow_session_context
            if not allow_session_context:
                session.context = MinimalPatientContext()

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

        dependencies = dict(safety_check=lambda message, context: decision,
                            retrieve=self._retrieve, policy=self.policy)
        if self._pubmed_search is not None:
            dependencies["pubmed_search"] = self._pubmed_search
        result = Orchestrator(**dependencies).run(query, session=turn, now=current, **tool_inputs)
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
        self.store.save_session(session, now=current)
        return result, session

    def forget(self, session_id: str) -> bool:
        return self.store.delete_session(session_id)
