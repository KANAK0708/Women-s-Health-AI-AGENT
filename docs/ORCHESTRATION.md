# Tools orchestration v0.3

This is the tools owner's first controlled workflow. It builds on the shared
contract and consumes the teammate's existing retrieval interface. It does not
replace memory, source ingestion, or the retrieval engine. `main.py` now uses
`app/workflow/service.py` to connect this orchestration to the existing context
tracker, session store, and retrieval engine. It is not a clinically validated agent.

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

## Focused answers

`health_tools/answer_selection.py` identifies definition, assessment, symptoms,
lifestyle, and care-navigation sections using explicit English patterns. Single
category questions pass the category to the existing retrieval API; mixed
questions use one bounded retrieval call and select from its result.

Only the highest-ranked matching passage per requested section is shown. Text is
kept intact, with its original citation ID and locator. Diagnostic/assessment
locators are excluded from general definitions unless assessment was requested.
Unselected passages are removed from both claims and visible citations. Examples:

```bash
python3 main.py --query "What are PCOS symptoms?"
python3 main.py --query "What is PCOS and what are its symptoms?"
python3 main.py --query "How can I manage PCOS with diet and exercise?"
```

These produce symptoms only, definition plus symptoms, and lifestyle only,
respectively. Explicit broad overviews can include all three sections. When some
requested sections are missing, the response labels those gaps; when all are
missing, it abstains instead of substituting a different category.

Elliptical follow-ups such as `What about exercise?` add the consented active topic
to the retrieval query only. They do not rewrite the user message passed to safety
checks. Without an available topic the workflow asks for one. Explicit topic
changes and unrelated questions do not automatically inherit the prior topic.
Retention opt-out, deletion, and expiry remove this follow-up context.

Selection is category/locator matching, not a general semantic answer-completeness
test. A matching paragraph may still contain context beyond a narrow question;
it is not shortened because that could remove qualifiers. Retrieval ranking and
clinical applicability still need evaluation. No LLM paraphrasing is introduced.

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

## Run the integrated application

```bash
python3 main.py --query "What is PCOS and what are its symptoms?"
python3 main.py --query "Calculate cycle intervals" --period-starts 2026-08-01 2026-09-05 --as-of 2026-11-06
python3 main.py --query "Find PCOS research" --allow-external-research --research-query "PCOS systematic review"
python3 main.py --remember
```

The CLI keeps session context only with `--remember`; `/forget` deletes it and
`/quit` exits. Session state is also deleted on CLI exit. `--json` prints the same
typed response as JSON. With retention enabled, cycle inputs can now be collected
over replies and require explicit confirmation before calculation. `/cancel`
clears that pending task. Only ISO date lists are parsed, not arbitrary narratives.
See [PENDING_TASK_CONTRACT.md](PENDING_TASK_CONTRACT.md) for conversation examples,
expiry/consent behavior, and the interface for a shared storage adapter.

Current-turn context is processed in a deep copy, so an explicitly stated minor
age still applies when retention is off. Only consented context is copied back
into the existing session store. Clarification counts are recorded through the
existing ContextTracker. Stateless requests cannot enforce a cross-turn count.

The application bridges the current upstream keyword safety/scope checks before
any tool. This is software integration, not clinical validation of those checks.
Source review metadata is not independently verified; development status remains
visible in responses. Local answers use exact excerpts, not generated summaries.

The latest `main` changes (through `9075800`) are integrated on `tools`: expanded
evidence, updated scope rules, development evaluations, and ClaimVerifier.
`HealthApplication` runs the verifier before returning an evidence answer. All
displayed claims must pass; partial repairs and failures replace the entire answer
with an abstention, clearing claims, citations, and medical text fields. Verifier
outages also stop the evidence answer. Calculations, bibliographies, and urgent
messages do not depend on a research-claim verifier.

ClaimVerifier uses token overlap and rules. It is not a general semantic
entailment model or clinical proof. Exact excerpt construction and citation
identity checks remain in place; source applicability still needs review.

Run the provided development scenarios separately from unit tests:

```bash
python3 -m evals.run_evals
```

The runner now rejects the disabled `--llm` mode, exits nonzero on failed checks,
does not count missing scenario families as passes, and records the case-file
hash and actual mode in results. These 50 cases check expected routing and
citation shape, not medical correctness. Labels and clinical review claims have
not been independently verified. Passing them is not release approval.

The legacy `process_health_query` function still returns
`(EducationalResponse, SessionMemory)`. Its old LLM and external-fallback flags are
accepted for call compatibility but do not enable those paths. Programmatic callers
must specify their consent choice; `None` retains the teammate's original default.

## Integration instructions for the memory/retrieval agent

The application service now performs the wiring below. For other entry points,
reuse your existing classes:

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

- Clinical review of the integrated safety/context policy is still required.
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
- Cycle-input follow-ups use a separate, bounded pending-task controller; the
  initial adapter is process-local. Shared storage, atomic distributed consumption,
  and natural-language date interpretation remain outside this increment.
- The separate `guidelines.py` prototype stays local/deferred. There is one
  intended production retrieval owner: `app/retrieval`.

`test_upstream_integration.py` now runs with the merged application classes.
`test_application_integration.py` exercises the real service, CLI, session opt-out,
deletion, expiry, clarification limits, and pre-tool safety routing. PubMed failures
and research routing use mocks in the automated suite to avoid network dependence.
