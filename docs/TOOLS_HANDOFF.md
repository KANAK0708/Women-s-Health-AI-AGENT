# Tools foundation — integration contract

Scope: PCOS and menstrual-health education. This increment provides date
arithmetic, PubMed research retrieval, and a shared result envelope. It does not
implement clinical advice, approved-guideline retrieval, or safety routing.
It is not wired into `main.py` yet.

## Ownership boundary

- Tools owner: explicit input validation, calculations, retrieval, provenance,
  failures, and tool tests.
- Memory owner: consent, storage, confirmation, correction, deletion, session/user
  isolation, and supplying only relevant context to the workflow.
- Shared workflow: mandatory safety/context checks, tool routing, answer
  generation, citation validation, and bounded retries.

Tools do not read/write memory, files, or logs. PubMed sends research queries to
NCBI; cycle calculations remain offline. The legacy `tools.py` and its save tool remain unchanged; this
increment does not make the existing agent safe for patient use.

## Shared result envelope (version 1.0)

`ToolResult.to_dict()` returns JSON-ready fields:

| Field | Meaning |
| --- | --- |
| `tool` | Stable tool name |
| `status` | `ok`, `insufficient_data`, or `error` |
| `data` | Tool-specific facts; empty on validation errors |
| `sources` | Source ID, title, URL, publisher, retrieval timestamp, exact excerpt, optional publication date and locator |
| `limitations` | Constraints the answer layer must preserve |
| `error` | Code, non-sensitive message, retryable flag; present only for errors |
| `schema_version` | Contract version; currently `1.0` |

Source provenance does not imply clinical approval. The later evidence registry
must enforce source eligibility before retrieval. These dataclasses are internal
Python contracts, not a replacement for request validation at an eventual API.

## analyze_cycle_history

```python
from health_tools import analyze_cycle_history

result = analyze_cycle_history(
    ["2026-08-01", "2026-09-05", "2026-10-08"],
    as_of="2026-11-06",
).to_dict()
```

Only supply user-confirmed starts of separate periods, oldest first. Do not
infer dates from ambiguous text or treat spotting as a new period automatically.
The memory layer should pass the user's local reference date explicitly; if
omitted, the calculation uses the machine's local date.

Duplicate, unordered, invalid, and future dates are rejected rather than repaired.
At most 366 entries are accepted. Empty/single-date input returns
`insufficient_data`; two starts yield one interval, with a limitation on describing
variability. Statistics describe recorded intervals only. Missing periods can
inflate intervals. Time since the last start is excluded from completed-interval
statistics. No diagnosis, normal/abnormal classification, or prediction is made.

## Run locally

No dependencies or credentials needed for this package:

```bash
python3 -m health_tools --as-of 2026-11-06 2026-08-01 2026-09-05 2026-10-08
python3 -m unittest discover -s tests -v
```

The demo prints supplied health dates to the terminal; use synthetic dates when
sharing terminal output. No persistence is performed by this package.

## Next increments

1. Agree on approved source selection and evidence metadata with the team.
2. PubMed retrieval is implemented; evaluate relevance and clinical applicability
   separately from the engineering tests before integrating it into answers.
3. Implement approved guideline ingestion/retrieval after rights and review.
4. Add framework adapters once tool contracts are stable.
5. Integrate mandatory safety/context checks and evidence validation before
   exposing tools in the patient-facing answer path.

## search_pubmed

```python
from health_tools.pubmed import search_pubmed

result = search_pubmed("PCOS menstrual irregularity systematic review", max_results=3)
```

Command-line demo (requires internet, no API key required for low-volume use):

```bash
python3 -m health_tools.pubmed "PCOS menstrual irregularity systematic review" --max-results 1
```

- Query: nonempty string, at most 500 characters. Caller supplies research terms
  without names, identifying history, or other personal data. This tool does not
  automatically de-identify text. It searches PubMed generally; the workflow must
  enforce the product's PCOS/period scope.
- Limit: integer 1–5. Uses ESearch best-match ranking followed by EFetch XML.
- No automatic retries. Timeout defaults to 10 seconds per request, maximum 30;
  this is a socket timeout, not a whole-workflow deadline. Bound the overall
  workflow separately before production use.
- Two API requests maximum; response bodies capped at 2 MB each. Calls are paced
  below three requests/second within one process. Multiple workers/processes
  require a shared rate limiter for NCBI's IP-level limits.
- `NCBI_EMAIL` may contain the developer's contact email and `NCBI_API_KEY` an
  optional key. Set them in the process environment; this standalone module does
  not load `.env`. Neither value is included in returned results or error text.
- Results preserve search order, exact extracted abstract text with section
  labels, PMID links, publication types, and linked correction/retraction notices
  present in the record. This is not a comprehensive retraction-screening service.
- Missing abstracts are explicit `citation_only` records with empty excerpts;
  never interpret a title as supporting evidence. Books/unsupported or incomplete
  responses fail explicitly instead of silently returning partial results.
- `ok` means retrieval succeeded, not that the findings are clinically approved.
  No full text is retrieved, and no quality score is invented.
- Empty search results return `insufficient_data`. HTTP, rate-limit, network,
  timeout, and malformed-response errors return sanitized structured failures.

NCBI's disclaimer/copyright notice must remain visible in an eventual product:
[NCBI disclaimer](https://www.ncbi.nlm.nih.gov/About/disclaimer.html).
Abstracts may be copyrighted; retrieval does not grant unrestricted reuse rights.
Reference documentation:
[E-utilities parameters](https://www.ncbi.nlm.nih.gov/books/NBK25499/),
[usage requirements](https://www.ncbi.nlm.nih.gov/books/NBK25497/).
