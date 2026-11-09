# Memory/retrieval → orchestration handoff v1

## Owners

Memory/retrieval owner supplies consent-governed session context and eligible,
versioned passages with citations. Tools/orchestration owner selects additional
tools, asks necessary follow-ups, generates answers, validates evidence support,
and formats output. Safety policy and integration are jointly reviewed.

The `health_tools.handoff` adapter targets the interfaces inspected in
`origin/main` at commit `bbe4ed3`: `SessionMemory`, `RetrievalBundle`, and
`EducationalResponse`. These upstream classes remain canonical. The adapter's
snapshots are internal read-only inputs, not replacement storage/response schemas.
`origin/main` at that commit has now been merged into `tools`, and the CLI is wired
through `app/workflow/service.py`. The canonical memory/retrieval files remain
owned by the teammate; the tools side owns the service and output formatting.

## Handoff checklist for the memory/retrieval agent

1. Fetch `origin/tools` and read this document plus `health_tools/contracts.py`
   and `health_tools/handoff.py`. Integration is on `tools`; publishing it does
   not update the remote `main` branch.
2. Keep owning `app/storage`, `app/retrieval`, evidence ingestion/registry, and
   their canonical schemas. Tools, orchestration, generation, and formatting are
   owned by the tools agent; coordinate changes at the shared boundary.
3. Supply `SessionMemory` with explicit consent and timezone-aware creation/expiry
   timestamps. Preserve unknown context as `not_provided`.
4. Supply `RetrievalBundle` with a unique citation for each passage, matching
   source ID, title, URL, locator, and review date exactly.
5. Test the adapters against the actual upstream classes, including declined
   consent, expiry, unknown values, empty retrieval, and citation mismatches.
6. Flag interface changes before renaming fields or changing their meaning.
   Agree separately on confirmed period dates and per-fact provenance.
7. Do not treat these software contracts or passing tests as clinical approval.
   Keep approval/rights/freshness checks in retrieval, and keep research abstracts
   distinguishable from approved guidance.

The contract publication includes the cycle helper imported by `health_tools`
and its tests so the package can be imported and tested independently. PubMed
and the deferred guideline prototype are separate work, not prerequisites for
this handoff. The general `ToolResult` envelope in `contracts.py` is for tool
outputs; it does not replace the upstream `EducationalResponse` API schema.

## Input 1: session context

```python
from health_tools.handoff import adapt_session
context = adapt_session(session)  # SessionMemory or its model_dump(mode="json")
```

The adapter preserves `yes` / `no` / `not_provided`, rejects malformed or
contradictory age/adult fields, and suppresses context when consent is declined or
the session expires. Session identifiers, audit history, and storage timestamps
are not exposed in the snapshot. No memory is mutated. The current user message
is a separate input and must still be checked even if historical context is absent.

The existing memory schema has no confirmed period dates. Cycle tools accept
explicit caller-confirmed dates, or dates proposed and confirmed through the
separate pending-task controller. The storage protocol and development adapter
are described in [PENDING_TASK_CONTRACT.md](PENDING_TASK_CONTRACT.md). No profile
fields were added. Coordinate a shared adapter with the memory owner. The existing
profile fields also do not encode per-fact provenance; that remains a limitation.

## Input 2: retrieved evidence

```python
from health_tools.handoff import adapt_retrieval
evidence = adapt_retrieval(bundle)  # Her RetrievalBundle
```

Each snapshot preserves `e1`-style citation ID, passage/source IDs, exact text,
title, URL, section locator, review date, category, and manifest version.
Missing, duplicate, orphaned, or mismatched citation mappings fail explicitly.
Ranking scores are not passed as medical confidence. Empty evidence stays empty.
The retrieval owner remains responsible for rights, source approval, scope,
freshness, and passage integrity; the adapter does not certify those properties.

PubMed records remain research evidence in their own `ToolResult`. Never silently
convert them into approved guideline passages or reuse conflicting citation IDs.

## Output: existing EducationalResponse

Continue using the teammate's `EducationalResponse` on integration. The answer
owner should create one final object with these existing fields:

- `response_type`: education, clarification, urgent_guidance, out_of_scope, abstention.
- `answer`: the exact text to be shown to the user.
- `claims`: material statements with `evidence_ids`.
- `evidence`: citations derived from actual retrieved passages.
- `questions`, `next_steps`, `limitations`: explicit and bounded.

```python
from health_tools.handoff import validate_claim_references
validate_claim_references(claims, evidence)
```

This checks references only. It does not establish semantic support or ensure all
displayed medical claims were enumerated. Before a patient-facing release, validate
all displayed medical text, not merely the claims list; do not add unsupported
symptom/lifestyle defaults or overwrite citations to make a draft appear supported.
Dates/calculations should identify user-supplied inputs, not invent literature
citations. Semantic support validation and readable output rendering are next work.

## Failure policy

Malformed handoffs raise `ContractViolation` with messages that omit raw payloads.
The future workflow must catch this and return a controlled fallback; do not treat
malformed evidence as valid or substitute arbitrary web results automatically.
Adapters never persist, call models/APIs, or log health data.

## Verification

```bash
python3 -m unittest discover -s tests -v
```

Unit tests use structural fixtures mirroring the upstream schemas. The optional
`test_upstream_integration.py` suite was also run successfully against the actual
session model, retrieval engine/bundle, and response schema in an isolated snapshot
of `origin/main` at `bbe4ed3`. They also run in the merged application, alongside
service/CLI tests in `test_application_integration.py`.
The separate guideline prototype is deferred; use the teammate's retrieval engine
as the integration target rather than expanding a second clinical registry.

The tools-side orchestration and its integration factory are now available; see
[ORCHESTRATION.md](ORCHESTRATION.md) for wiring, failure handling, and demonstrations.
