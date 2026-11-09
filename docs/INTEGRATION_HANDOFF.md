# Integration Handoff Guide for Tools & Orchestration

This guide outlines how to connect the database adapters (`PgVectorHybridEngine` and `RedisSessionStore`) to the orchestration layer in `app/workflow/service.py` on the `tools` branch.

---

## 1. Quick Integration in `app/workflow/service.py`

In `app/workflow/service.py`, `HealthApplication` accepts optional `store` and `retrieve` parameters in its `__init__`:

```python
from app.retrieval.pg_vector_engine import get_retrieval_engine
from app.storage.redis_session_store import get_session_store
from app.workflow.service import HealthApplication

# Instantiate with auto-detecting factories (falls back to local engines if DBs are unreachable)
app = HealthApplication(
    store=get_session_store(),
    retrieve=get_retrieval_engine().retrieve,
)
```

Alternatively, `HealthApplication.__init__` can be defaulted to use the factories directly:

```python
class HealthApplication:
    def __init__(self, *, store=None, retrieve=None, pubmed_search=None, policy=None, claim_verifier=None):
        # Auto-detects Redis if reachable; otherwise falls back to EphemeralSessionStore
        self.store = store if store is not None else get_session_store()
        self.policy = policy or ToolPolicy()
        self._retrieve_callback = retrieve
        self._engine = None
        self._pubmed_search = pubmed_search
        self._claim_verifier = claim_verifier

    def _retrieve(self, query, **kwargs):
        if "category" in kwargs:
            kwargs["category"] = EducationalCategory(kwargs["category"])
        if self._retrieve_callback is not None:
            return self._retrieve_callback(query, **kwargs)
        # Auto-detects PostgreSQL if reachable; otherwise falls back to local manifest engine
        if self._engine is None:
            self._engine = get_retrieval_engine()
        return self._engine.retrieve(query, **kwargs)
```

---

## 2. Preserved Boundaries & Guarantees

When using `get_session_store()` and `get_retrieval_engine()`, all established clinical and safety contracts remain strictly preserved:

1. **Pre-Tool Safety Gates**:
   - `ContextTracker.update_from_user_turn` and `validate_educational_query_scope` run before any tool is invoked.
   - Any `UrgentEscalationRequired` or `ScopeViolationError` immediately short-circuits the turn into safe emergency guidance or care referral.

2. **User Privacy & Session Consent**:
   - `session.allow_session_context` is honored. When `False`, no conversational context is retained in Redis.
   - Calling `app.forget(session_id)` permanently removes the session key from Redis.
   - Sessions expire according to configured TTL (default: 30 minutes).

3. **Citation & Passage 1-to-1 Identity**:
   - Both local and PostgreSQL retrieval engines return a canonical `RetrievalBundle` with `e1`, `e2`, ... citation IDs matching the passages 1-to-1.
   - Passes all `health_tools.handoff.adapt_retrieval` validation checks.

4. **Claim Verification & Fallback**:
   - `_verify_answer` runs `ClaimVerifier` against candidate educational responses and retrieved excerpts.
   - Unsupported claims or verifier failures trigger safe abstention fallback (`CLAIM_VERIFICATION_FALLBACK`).

5. **External Research Authorization**:
   - PubMed searches are never run automatically on raw user queries. Explicit consent and de-identified search terms are required.

---

## 3. Environment Configuration

To point to specific PostgreSQL or Redis instances, configure standard environment variables in `.env`:

```env
# PostgreSQL connection string with pgvector extension enabled
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/womens_health_ai

# Redis connection string
REDIS_URL=redis://localhost:6379/0

# Set to 'true' for development evaluations; 'false' for strict clinical production mode
ALLOW_UNVERIFIED_EVIDENCE=true
```

If neither database is running, both factories automatically and gracefully fall back to local in-memory engines (`EphemeralSessionStore` and `HybridRetrievalEngine`).
