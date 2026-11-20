# Research offers and per-request consent

When an educational turn ends with `EVIDENCE_EMPTY`, `FOCUSED_EVIDENCE_EMPTY`,
`RETRIEVAL_FAILED`, `CLAIM_VERIFICATION_FALLBACK`, or
`CLAIM_VERIFICATION_UNAVAILABLE`, the application can add an optional
`research_offer` to its existing response. It contains `available`, `question`,
`reason`, and `consent_text`. Existing response fields retain their names and
meaning. Availability checks read local provider configuration without creating
clients, changing environment variables, probing quotas, or making API calls.

There is no offer on urgent, policy-blocked, out-of-scope, minor, calculator,
pending-task, intake, social, successful-answer, or unconfigured-provider turns.
Offers do not run research. The main filters still define their existing safety
and policy boundaries; the research planner retains responsibility for broader
women's-health subject classification after consent. This change does not add a
new medical topic classifier or change any clinical rule.

## Web and CLI flow

The web response shows **Research this in medical literature** with consent text
naming Groq, Google Gemini, PubMed, Europe PMC, MedlinePlus, DuckDuckGo, and the
allowed medical source sites. Clicking it gives consent for that question, sends
the current session/retention choice to `/api/research`, polls the background
job, and renders the structured report in the same chat using Prompt 2's renderer.
Direct deep-research mode uses the same application safety gate.

```sh
python3 main.py --query "What is PCOS?" --research
```

In single-question CLI mode, `--research` explicitly authorizes research only if
that turn receives an offer. Without it, the CLI prints the offer and consent
instructions. Interactive mode asks for `yes` separately on every offered turn;
the flag never becomes standing consent. Progress goes to stderr. JSON mode
keeps a single response object on stdout and adds `research_report` only when
research actually runs. `/forget` deletes session state; CLI exit also deletes
the session as before.

## Safety and storage

`HealthApplication.prepare_research()` requires the literal boolean `True` for
consent, validates input bounds, then runs the existing application flow with
all tools disabled. This reuses current-message urgent/policy checks, retained
minor context, pending-task handling, and symptom-intake escalation rules. Only
eligible educational/literature turns proceed. No research model is constructed
before this gate. `HealthApplication.research()` is the guarded programmatic
entry point. `_execute_research()` is internal execution after that gate; the web
worker calls it only after successful preparation.

The research agent's own safety check, redaction, planner, and quote/claim
verification remain unchanged. No research pipeline hook was needed, and no
verification threshold, eval case, safety pattern, or manifest approval was
modified. No new service or domain was added.

With session context enabled, only `RESEARCH_OFFERED` and `RESEARCH_ACCEPTED`
audit codes are stored, bounded with existing audit history and existing session
expiry. No raw question, consent text, or report is added to session memory.
Opting out removes these codes and retains no new research session metadata.
Codes are a record, never permission for a later request. Storage failures stop
research before constructing a client.

Web jobs are temporary delivery state, not session history. Their lifetime is
capped at 30 minutes and at any shorter remaining session lifetime; a daemon
timer removes expired jobs even without another HTTP request. A completed job is
removed on its first polling delivery. `/api/forget` removes associated pending
jobs and the session, and reports storage failures instead of claiming deletion
succeeded. A deleted job cannot publish a late result or start queued work.
Already-running external calls cannot be recalled; their eventual results are
discarded after deletion. A lost final polling response cannot be fetched again;
retrying research requires a new consented request.

## Verification

The pre-change comparison used a read-only Git archive of `6a762e8` in
`/tmp/prompt3-baseline-source`. Both modes produced identical case pass/fail
outcomes and failure reasons before and after this integration:

| Check | Before | After |
| --- | ---: | ---: |
| `python3 -m evals.run_evals` (strict evidence) | 28/50 | 28/50 |
| Same suite, `--development-evidence` | 49/50 | 49/50 |
| Urgent routing in both modes | 100% | 100% |
| Minor routing in both modes | 100% | 100% |

Strict-mode education failures reflect the absence of approved manifest content;
the fixture mode's remaining failure is `DEV-MED-06`, which expects education
where the existing symptom intake asks a clarification. These release gates
remain blocked; they were not relabelled or weakened to pass this work.

The live `python3 -m evals.run_research_evals --category safety --pause 0`
passed **7/7**, with zero pipeline failures. The saved raw run is
`evals/results/research_run_20261119_201936.json` (ignored by Git). The committed
`research_latest.json` was restored byte for byte after the run.

The offline suite passes **288 tests, 2 skipped**. New tests cover offers on
empty/focused/failed retrieval and verification failure; no offer on successful,
unsafe, minor, calculator/task, social, or unavailable-provider turns; strict
per-request consent; direct HTTP and programmatic safety; historical minor
context; intake-specific red flags; no tool use during preparation; sanitized
failures; code-only retention, opt-out, expiry and deletion; completed-job
removal; expiry timers; prevention of late publication; CLI consent and JSON.
All research agents in these tests are fake. Inline JavaScript syntax and
`git diff --check` also pass.

## Reproducing the browser check without API calls

```sh
python3 -m dev.research_offer_demo --port 8766
```

Open <http://127.0.0.1:8766>, ask “What is PCOS?”, and accept the offer. This
separate launcher simulates an evidence gap and substitutes a labelled synthetic
report. It does not enable a production bypass or call any external service.

The browser check confirmed the offer and service consent text, job polling,
one report in the same three-message chat, a working exact-quote citation, and
New chat returning to an empty conversation. Screenshots contain synthetic data:

- [Offer and consent](screenshots/research-integration/offer-consent.jpg).
- [Accepted report in the same chat](screenshots/research-integration/accepted-report.jpg).

This browser check establishes the application/UI flow using a fake research
agent. It does not establish live research answer quality or clinical approval.
