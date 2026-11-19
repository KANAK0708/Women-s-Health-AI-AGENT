# Privacy and external calls — current behaviour, not a compliance assessment

Sources: [privacy.py](../../health_tools/research/privacy.py),
[pipeline.py](../../health_tools/research/pipeline.py),
[sources.py](../../health_tools/research/sources.py),
[llm.py](../../health_tools/research/llm.py),
[cache.py](../../health_tools/research/cache.py),
[consent.py](../../app/storage/consent.py),
[service.py](../../app/workflow/service.py),
[web_ui.py](../../web_ui.py), and [tools.py](../../tools.py).
This packet does not assert anonymity, regulatory compliance, provider retention
terms, encryption at rest, or suitability for patient data.

## What is removed before integrated research calls

Safety and current-turn age checks use the original question locally. After that,
the research pipeline applies ordered, rule-based substitutions. The exact regex
and replacement for every rule are in [exact_rules.md](exact_rules.md).

| Detail | What the current rule recognizes | Replacement |
| --- | --- | --- |
| Email | Conventional email-like strings | `[email]` |
| Links | HTTP/HTTPS and `www.` links | `[link]` |
| Dates | ISO dates, specified slash/dot numeric dates, English month/day phrases | `[date]` |
| Phone | Certain long digit/punctuation/space sequences | `[phone]` |
| First-person age | Specified “I am/I'm/im/I turned…” and “my age is…” forms | `I am [age]` or `my age is [age]` |
| Name | Specified self-identifying phrases followed by one or two capitalized words | Original lead phrase plus `[name]` |
| Place | Specified “I live in/I'm from/I am from/based in…” phrases with capitalized words | Original lead phrase plus `[location]` |
| Long ID-like number | Six or more consecutive digits | `[number]` |

Matched categories, rather than removed original values, are recorded in
`redactions[]`. Date rules precede the phone rule. General population ages such
as “women over 40”, third-person age phrases such as “a 45-year-old”, and clinical
numbers are deliberately retained. Symptoms, condition names and health concerns
remain because they are needed to research the question.

Planner-written search terms are additionally stripped of email-like text,
numbers, first-person pronouns, boolean operators and certain search syntax by
`scrub_terms`. This is not a general identifier detector. It can also remove
clinically useful numbers from search terms. It does not guarantee the planner
cannot introduce or retain identifying information.

## Which services can receive what

| Recipient / code path | Information sent |
| --- | --- |
| Groq | Usually the redacted question for planning; sub-questions, findings and rewrite feedback for reporting; potentially document excerpts and claim/quote pairs when acting as the long-model fallback. |
| Google Gemini | Usually document title/text segments, planned sub-questions, and claim/quote pairs for extraction and meaning checks; potentially the redacted question/reporting inputs when acting as the fast-model fallback. |
| NCBI PubMed (`eutils.ncbi.nlm.nih.gov`) | Medical search terms, record identifiers, and tool metadata. Optional configured NCBI contact email/API credentials are included for that service; they are not patient details. |
| Europe PMC / EMBL-EBI (`www.ebi.ac.uk`) | Medical search terms, article identifiers/PMCID, and full-text requests. |
| MedlinePlus / NLM (`wsearch.nlm.nih.gov`) | Medical search terms and request parameters. |
| Web search through `ddgs` | Medical terms, women's-health/guideline search context and site filters. The application calls this DuckDuckGo search, but the installed package uses automatic backend selection; see the recipient caveat below. |
| Allowed publisher/source hosts | Requested page/PDF URLs, robots.txt requests, client network metadata and user-agent. Requests may follow only allowed redirects. Full text read from these sites may then be supplied to the configured model providers. |
| ClinicalTrials.gov, on the separate bibliography/tool path | Separately authorized medical research terms. It is not one of `DEFAULT_SEARCHES` in the deep-research pipeline. |
| Wikipedia / legacy educational search wrappers | Constrained terms when explicitly invoked through those wrappers. These are separate interfaces, not an automatic approved-evidence fallback. They do not inherit the full research redaction/session gate automatically. |

**Recipient caveat observed in the installed environment:** `ddgs` version
`9.16.1` has `backend='auto'` as its search default. Its available text backend
keys are `brave`, `duckduckgo`, `grokipedia`, `mojeek`, `startpage`, `wikipedia`
and `yahoo`; the application does not select a fixed backend. Not every backend
is necessarily contacted in a particular run. This was established by local
inspection of the installed package's `_search_sync` and `_get_engines` methods,
without a network call. Earlier saved run logs also show attempted Startpage
requests. Current consent text names DuckDuckGo but does not enumerate these
possible additional recipients. This is an open privacy/consent question, not a
new recipient added by this packet. The observed package version, backend keys
and method-source hashes are recorded in
[search_dependency_snapshot.json](search_dependency_snapshot.json).

Requests also disclose ordinary network connection metadata. This packet has not
audited provider logging, cross-border processing, data residency, retention,
training use, contractual terms or downstream subprocessors. No deletion at an
external provider is promised by `/forget`.

## Consent and entry-point differences

The integrated `/api/research`, `HealthApplication.research`, and main CLI require
consent for the current request. An earlier acceptance audit code never
authorizes a new run. Offers alone make no model/search call. The web consent
text names the configured providers and warns that rule-based redaction can
miss details.

The standalone `python3 -m health_tools.research` command, bare `ResearchAgent`
and raw research/search tools rely on their callers for authorization and, in
some cases, non-identifying input. They are not equivalent to the integrated
session-aware gate. The bare agent still has its own regex safety and redaction
steps, but not the main adult/intake checks. Review which entry points may be
exposed in the proposed setting.

## Local storage, expiry and deletion

| Location | What can remain | Expiry/deletion behaviour |
| --- | --- | --- |
| Main session store | Minimal age/adult/pregnancy/other context and operational codes, including offered/accepted codes only with context consent. No new raw-question/report history is added by research integration. | Default 30-minute policy; configurable 1–120 minutes. Redis uses native TTL. Process-local expiry is enforced on read/write/purge, not by an independent erasure timer. `/forget` deletes the session and pending tasks/intakes. |
| Pending cycle tasks and symptom intakes | Confirmed/proposed dates; parsed symptom answers; intake's `first_message` is up to 300 characters and some answer slots can retain short free text. | Task TTL is at most five minutes/session expiry; intake inherits session expiry and turn bounds. These process-local stores purge on access/activity; they are not durable clinical records or guaranteed immediate wall-clock erasure. Context opt-out does not save a multi-turn intake. |
| Web research jobs | Progress and, until delivered, report JSON with the original question. | Removed on first completed polling delivery, `/api/forget`, or a timer capped at 30 minutes and the remaining session TTL. A forgotten running job cannot publish its result; already-dispatched calls cannot be recalled. |
| Browser chat | Original question, response and displayed research report in the current page DOM. | New chat clears the displayed messages after confirmed server deletion. The code does not promise deletion of browser/OS history, screenshots, copied text or other user-created copies. |
| `.cache/research` | Search documents, page/full text, and model outputs. File names hash cache inputs; values are JSON, not encrypted or de-identified by the cache. Model outputs may contain health context or identifiers missed by redaction. | Search freshness TTL 3 days; pages/full text 7 days; model outputs 30 days. Expired files are treated as misses but are not automatically unlinked. `/forget` does not erase this cache. `RESEARCH_CACHE=off` prevents these disk reads/writes for a run. |
| Page reader's process cache | Fetched `Document` objects keyed by URL. | Lives for the process; its in-memory `_cache` is not cleared by `/forget`. Primarily public page content, not raw research questions. |
| Eval runs and this packet | Eval question, report, quotes, redaction categories and logs. | Saved research runs are local ignored JSON files; they are not session-governed and `/forget` does not remove them. This packet uses the supplied fictional eval questions, never patient conversations. It is a deliberate review artifact kept in Git. |

## Known redaction limitations

- This is an English-oriented pattern list, not anonymization or a general named
  entity recognizer. Lowercase names, different name scripts, unrecognized place
  phrasing, addresses, occupations, relationships, distinctive narratives and
  unusual date/age formats may remain.
- Third-person age is intentionally kept, even if it could identify a person.
  Medical details and combinations of otherwise ordinary facts may re-identify
  someone. Some long clinical numeric sequences could instead be removed as
  phone/ID-like text.
- Publisher text and search-result text are external content. They can contain
  names or identifiers and are not all passed through the question redactor
  before being provided to models.
- Search logs may contain terms and provider error details. New web/service
  errors are sanitized, but older research exceptions are partially included in
  saved logs. Review what is exposed or retained; hashed cache keys are not a
  confidentiality guarantee.
- The browser console is a local development HTTP server, defaulting to loopback,
  with no reviewed clinical authentication/authorization design. Any different
  network deployment and access to session/job identifiers needs separate review.

## QUESTIONS FOR THE REVIEWER

- **Q-PRIVACY-01:** What personal health information may be sent to which
  providers, in which jurisdiction, under what agreement and retention terms?
  Is rule-based redaction sufficient for the intended audience and languages?
- **Q-PRIVACY-02:** Does current consent accurately name all possible web-search
  recipients given `ddgs` automatic backend selection? Which actual recipients
  should be allowed and disclosed?
- **Q-PRIVACY-03:** Are on-disk model/cache outputs, residual identifiers and
  nondeletion of expired cache files compatible with the intended retention and
  `/forget` promises? What operational deletion controls are required?
- **Q-PRIVACY-04:** Are raw intake snippets and process-local expiry semantics
  acceptable? What needs stronger minimization, access control or deletion?
- **Q-PRIVACY-05:** Should standalone research commands/tools be restricted to
  developers, or brought under the same consent/adult/intake controls as the
  main assistant? Who is accountable for authorizing each external call?
- **Q-PRIVACY-06:** Is the local development console clearly segregated from any
  patient-facing service, and what separate security/privacy assessment is needed
  before such deployment?
