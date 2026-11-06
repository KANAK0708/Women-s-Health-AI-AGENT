# Tools orchestration v0.1

This is the tools owner's first controlled workflow. It builds on the shared
contract and consumes the teammate's existing retrieval interface. It does not
replace memory, source ingestion, or the retrieval engine, and does not modify
the old `main.py`. It is not yet a deployed or clinically validated agent.

## Implemented behavior

1. Validate the request and adapt consented, unexpired historical context.
2. Run an injected safety policy on the current message before any tool. If
   context is malformed, still check the message using an empty context, then
   stop. Missing/failing safety policies never permit tool execution.
3. Route calculation requests to cycle arithmetic; research requests to PubMed;
   other questions to the teammate's approved-evidence retrieval interface.
4. Ask focused questions when required tool inputs are missing. Respect the
   memory owner's two-turn clarification count; do not mutate it locally.
5. Require explicit authorization plus separately reviewed, non-identifying
   terms for PubMed. Never forward raw health questions automatically.
6. Enforce enabled-tool lists, call-count limits, result-count/size limits, and
   PubMed request timeouts. No automatic retry loops or arbitrary web fallback.
7. Produce a dictionary compatible with `EducationalResponse`. Education uses
   exact retrieved excerpts and one-to-one citations. Missing categories stay
   empty; no generic symptoms or lifestyle advice is inserted.
8. Render that same answer object as plain text without a second model rewrite.

The intent router is deliberately small, English-only, and deterministic. It is
not a medical classifier or a general language understanding system. Safety and
clinical applicability remain separate responsibilities. Research output is a
bibliography, not a clinical synthesis; full records stay in `tool_results`.

## Run offline demonstrations

```bash
python3 -m health_tools.workflow_demo education
python3 -m health_tools.workflow_demo cycle
python3 -m health_tools.workflow_demo clarification
python3 -m health_tools.workflow_demo safety
python3 -m unittest discover -s tests -v
```

Demo entry points use synthetic evidence and a stub safety decision. Never use
their pass-through stub for a patient-facing application. They are explicitly
isolated from the integration factory, which requires a supplied safety policy.

Standalone tools remain available:

```bash
python3 -m health_tools --as-of 2026-11-06 2026-08-01 2026-09-05 2026-10-08
python3 -m health_tools.pubmed "PCOS menstrual irregularity systematic review" --max-results 1
```

PubMed uses NCBI ESearch/EFetch. Rate limits, copyright/disclaimer requirements,
and optional credentials are described in [TOOLS_HANDOFF.md](TOOLS_HANDOFF.md).

## Integration instructions for the memory/retrieval agent

After combining branches, reuse your existing classes:

```python
from app.schemas.evidence import EducationalResponse
from health_tools.integration import create_upstream_orchestrator
from health_tools.workflow import render_response

# safety_policy(query, ContextSnapshot) must return SafetyDecision and must
# implement the application's reviewed safety/scope protocol.
workflow = create_upstream_orchestrator(safety_check=safety_policy)

# Your application obtains consent, updates current-turn context, and supplies
# the resulting session. It also handles urgent exceptions from context tracking.
result = workflow.run(user_question, session=session, jurisdiction="IN")
response = EducationalResponse.model_validate(result.response)
print(render_response(result))

# Persist only under your consent/lifecycle rules. If clarification_requested is
# true, use your ContextTracker.record_clarification_turn before the next turn.
```

Do not send raw queries as `research_query`: review/remove identifiers first and
get permission for external research. Keep user-confirmed period dates separate
until a shared memory schema extension is agreed. Catch initialization failures
and apply the application's controlled fallback.

The response and `tool_results` contain sensitive user/evidence content and are
not telemetry. `events` contain fixed decision codes only; storage is still an
application decision. Trace codes are not a substitute for incident monitoring.

## Limits and remaining work

- An actual reviewed safety/context policy and workflow wiring are required.
  The existing upstream keyword checks have not been clinically validated here.
- Source approval, rights, applicability, and freshness are delegated to retrieval.
  The tools layer cannot turn registry metadata into clinical signoff.
- Exact excerpt generation avoids invented paraphrases. It does not establish
  relevance, applicability, or completeness. Future LLM synthesis needs separate
  claim-support validation across all displayed medical text.
- PubMed timeouts are per socket operation; retrieval/safety callbacks are
  synchronous. Add whole-request deadlines/cancellation at the application boundary.
- The routing is one-tool-per-turn today. The call budget prevents future
  expansion from becoming unbounded; it does not implement multi-tool planning.
- Multiturn follow-up choices rely on the caller supplying the clarified inputs;
  no automatic natural-language date extraction or session writes occur.
- The separate `guidelines.py` prototype stays local/deferred. There is one
  intended production retrieval owner: `app/retrieval`.

Optional tests in `test_upstream_integration.py` use actual upstream classes when
`app` is present. On the tools-only branch they are explicitly skipped. Compatibility
testing may also be run in an isolated checkout of the inspected upstream commit;
that does not merge or change the application's default entry point.
