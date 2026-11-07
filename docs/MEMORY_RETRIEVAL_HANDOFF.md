# Memory and retrieval handoff to the tools branch

Branch: `codex/retrieval-relevance-provenance` (based on `main` at `64aadd7`).
The tools branch is currently `169fa86`; merge this branch into `tools` before
wiring the adapters. This change does not replace `app/workflow/service.py` or
the tools branch's `main.py`.

## Contracts and behavior

- `RetrievalBundle`, `SessionMemory`, citation IDs, passage IDs, and response fields
  are unchanged. `SourceMetadata` gains `approval_status` with safe default
  `unverified`; PostgreSQL migration adds the same column. This is the only
  source-schema addition the tools owner needs to account for.
- Both retrieval backends require explicit source approval, current date
  (`expiry_date >= reference_date`), matching population and jurisdiction,
  non-supersession, and a distinctive topic anchor. Category filtering is
  equivalent. Neither returns an unrelated menstrual passage for i-pill.
- PostgreSQL uses `ts_rank_cd` plus pgvector and a default `0.12` hybrid-score
  floor; local retrieval uses IDF plus hashed embeddings and a `0.14` floor.
  Rankings and numerical scores are intentionally different. These floors are
  software starting points, not clinically calibrated relevance guarantees.
- The checked-in manifest is unverified, so production-mode retrieval abstains
  until a new evidence release has genuinely approved sources. Development
  fixtures can opt in with `HybridRetrievalEngine(allow_unverified_for_development=True)`
  or `PgVectorHybridEngine.retrieve(..., allow_unverified_for_development=True)`;
  never enable either for patient answers.
- PostgreSQL ingestion mirrors the supplied manifest snapshot, including
  deleting rows removed from that snapshot. Run it only against the intended
  registry. It records `manifest_version` for `RetrievalBundle`.
- Redis and in-memory sessions retain the existing `SessionMemory` contract,
  consent opt-out and expiry-at-boundary behavior. Configured startup failures
  currently fall back to local storage; failures after initialization propagate.

## Wiring in `app/workflow/service.py`

Keep the current service's safety check, consent lifecycle, focused answer
selection, original citation IDs, final-answer verifier, and explicit PubMed
authorization. Inject the adapters using a lazy retrieval callback so urgent
routing does not initialize PostgreSQL:

```python
from app.retrieval.pg_vector_engine import get_retrieval_engine
from app.storage.redis_session_store import get_session_store
from app.workflow.service import HealthApplication

engine = None

def retrieve(query, **kwargs):
    global engine
    if engine is None:
        engine = get_retrieval_engine()
    return engine.retrieve(query, **kwargs)

application = HealthApplication(store=get_session_store(), retrieve=retrieve)
```

The service currently creates/loads a session before its safety policy runs.
If Redis fails after initialization, that can delay urgent guidance. The tools
owner should run a current-turn urgent check before session-store access, then
use the service's reviewed fallback for other store failures. Do not catch a
database exception and turn it into a fabricated evidence answer. Also keep the
existing no-automatic-web-fallback behavior on `tools`.

## Verification

`tests/test_live_database_integration.py` uses synthetic evidence in a disposable
PostgreSQL database and isolated Redis session keys. Set
`TEST_POSTGRES_ADMIN_URL` and `TEST_REDIS_URL` explicitly to run it; absent
services are reported as skips. The development evaluation suite's existing
education labels assume approved sources, so the production-mode run now fails
those cases by abstaining. This is an honest release block until provenance is
reviewed, not a reason to set the legacy manifest to approved.
