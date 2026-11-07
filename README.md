# Women's Health AI Agent

An evidence-grounded women's health education assistant for adult menstrual health and PCOS. This is a development build; source-review metadata and safety rules require independent clinical verification.

## Integrated tools workflow

The CLI now connects session context and hybrid evidence retrieval to cycle
calculations, explicitly authorized PubMed research, and citation-based output.
Session retention is off by default in the CLI; use `--remember` to opt in.
No API key or model call is needed for local evidence and calculations.

```bash
python3 main.py --query "What is PCOS and what are its symptoms?"
python3 main.py --query "What are PCOS symptoms?"
python3 main.py --query "Calculate my cycle intervals" --period-starts 2026-08-01 2026-09-05 2026-10-08 --as-of 2026-11-06
python3 main.py --query "Find PCOS research" --allow-external-research --research-query "PCOS systematic review"
python3 main.py --remember
python3 -m unittest discover -s tests -v
```

In interactive mode use `/quit` to exit or `/forget` to delete the active session.
Use `--json` for the structured response. External research sends only the
separately provided research query to NCBI; exclude personal details.
See [the orchestration guide](docs/ORCHESTRATION.md) and
[the shared team contract](docs/TEAM_CONTRACT.md) for ownership and integration.
The standalone `workflow_demo` commands remain synthetic demonstrations.

Answers now select the requested sections rather than displaying the whole
retrieval bundle. Missing sections are identified explicitly. Follow-ups such as
`What about exercise?` use the active topic only when session context is available.


## Implementation Plan and Team Diagrams

See the [implementation plan](docs/IMPLEMENTATION_PLAN.md) for the architecture, clinical safety workflow, evidence lifecycle, validation gates, roadmap, and first-sprint backlog. For an offline shareable version with eight rendered diagrams, open [the HTML handoff](docs/IMPLEMENTATION_PLAN.html) in a browser.

## Clinical Evidence Base (`clinical/evidence_manifest/`)

The manifest contains versioned, clinician-approved passages across adult menstrual and reproductive health:
- **Monash University Guidelines (2023)**: Rotterdam criteria, adult PCOS diagnostic evaluation, metabolic lifestyle interventions.
- **World Health Organization (WHO, 2025)**: Global PCOS prevalence (8–13%), hyperandrogenism, clinical symptoms.
- **WHO Fact Sheet on Endometriosis (2023)**: Pathophysiology, dyspareunia, chronic pelvic pain, and supportive non-pharmacological care.
- **NIH NICHD Menstrual Guidelines (2024)**: Normal menstrual cycle range (21–35 days), bleeding duration (2–7 days), self-care, and emergency warning signs.
- **ACOG Clinical Consensus (2024)**: Primary vs. secondary dysmenorrhea, prostaglandin mechanisms, topical thermal therapy, and exercise evidence.
- **CDC Public Health Guide (2024)**: Heavy menstrual bleeding (>80 mL or >7 days), blood clot evaluation, iron-rich nutrition, and vitamin C pairing.

---

## Core Architecture: Memory & Retrieval

The system enforces two strictly isolated trust domains:

1. **Clinical Evidence & Hybrid Retrieval Engine (`app/retrieval/`, `clinical/evidence_manifest/`)**
   - **Pre-Filtering (`app/retrieval/filters.py`)**: Filters the supplied manifest by non-supersession (`is_superseded == False`), expiry date, adult population (`adults_18+`), and jurisdiction before running similarity search.
   - **Hybrid Lexical + Vector Reranker (`app/retrieval/reranker.py`)**: Combines IDF-weighted lexical matching with vector cosine similarity and educational intent boosting (`what_it_is`, `symptoms`, `prevention_and_lifestyle`), returning bounded excerpts (`4–6` passages) with verifiable `passage_id` and `source_id` citations.
   - **Guardrailed Educational Search (`tools.py`, `app/retrieval/engine.py`)**: Scopes Wikipedia and DuckDuckGo strictly to **definitions ("what it is")**, **symptoms**, and **lifestyle prevention**—blocking prescriptions, medication dosing, and prompt injection attempts.
   - **Offline Discovery Staging (`pipelines/seed_evidence.py`)**: Uses guardrailed Wikipedia and DuckDuckGo searches to stage candidate educational summaries with SHA-256 hashes into `clinical/evidence_manifest/staging_queue.json` for clinical review.

2. **Ephemeral Patient Session Memory (`app/storage/`, `app/schemas/memory.py`)**
   - **TriState Context Tracking (`app/storage/context_tracker.py`)**: Uses explicit `TriState` (`yes`, `no`, `not_provided`) so missing pregnancy status, medication use, or age never silently become negative findings.
   - **Clarification Turn Cap**: Enforces a maximum of **2 focused clarification turns**.
   - **Ephemeral TTL & Deletion Cascades (`app/storage/session_store.py`)**: Short-lived in-memory sessions with enforced TTL expiry, explicit user deletion cascades, and redacted operational audit codes (no autonomous plaintext file writes or raw health logs).

3. **Claim-to-Passage Checks (`app/verification/`)**
   - **Citation and Token Checks (`app/verification/verifier.py`)**: Uses token overlap and rules; this does not establish semantic entailment or clinical correctness.
   - **Final Answer Gate (`app/workflow/service.py`)**: Every excerpt claim must pass before display. Partial repairs, rejected claims, or verifier errors replace the whole answer with an abstention; unsupported display text is not retained.

---

## Repository Structure

```text
├── app/
│   ├── retrieval/
│   │   ├── engine.py          # HybridRetrievalEngine & GuardrailedEducationalSearch
│   │   ├── filters.py         # Pre-retrieval hazard detection, scope guardrails & source eligibility
│   │   ├── reranker.py        # Hybrid lexical + vector scoring & bounded excerpt selection
│   │   └── exceptions.py      # UrgentEscalationRequired, ScopeViolationError, InsufficientEvidenceError
│   ├── schemas/
│   │   ├── evidence.py        # SourceMetadata, EvidencePassage, EducationalResponse
│   │   └── memory.py          # TriState, MinimalPatientContext, SessionMemory
│   ├── storage/
│   │   ├── consent.py         # ConsentPolicy & TTL rules
│   │   ├── context_tracker.py # Safe TriState context extraction & 2-turn clarification cap
│   │   └── session_store.py   # EphemeralSessionStore with TTL & deletion cascades
│   └── verification/
│       └── verifier.py        # ClaimVerifier, entailment checks & high-risk extrapolation filters
├── clinical/
│   └── evidence_manifest/
│       └── manifest.json      # Development evidence manifest; review metadata unverified
├── docs/
│   ├── IMPLEMENTATION_PLAN.md # Engineering and clinical implementation plan
│   └── IMPLEMENTATION_PLAN.html # Offline shareable handoff with 8 SVG diagrams
├── evals/
│   ├── development/
│   │   └── seed_cases.json    # 50 supplied development cases; clinical labels unverified
│   ├── rubric/
│   │   └── scoring.py         # Section 10 release gates scoring rubric
│   └── run_evals.py           # Automated evaluation runner
├── pipelines/
│   └── seed_evidence.py       # Offline Wikipedia/DuckDuckGo staging pipeline
├── tests/
│   ├── test_memory_and_retrieval.py # Retrieval & memory unit/integration test suite
│   └── test_claim_verifier.py # Claim entailment & citation resolution test suite
├── main.py                    # Controlled workflow entrypoint
├── tools.py                   # Guardrailed LangChain retrieval & educational search tools
└── REQUIREMENTS.txt           # Python dependencies
```

---

## Setup & Usage

1. **Activate virtual environment**:
   ```powershell
   .\venv\Scripts\activate
   ```

2. **Credentials**:
   Local evidence retrieval and cycle arithmetic need no API keys. PubMed can
   run at low volume without a key; optional `NCBI_API_KEY` and `NCBI_EMAIL` must
   be set in the process environment. This path does not invoke an LLM or load
   model credentials from `.env`.

3. **Run the unit and integration test suite**:
   ```powershell
   .\venv\Scripts\python.exe -m unittest discover -s tests -v
   ```

4. **Run the interactive educational assistant**:
   ```powershell
   .\venv\Scripts\python.exe main.py
   ```

---

## Clinical Disclaimer

This assistant provides general educational information on menstrual health and PCOS for adults (18+) and cannot establish an individual medical diagnosis, interpret personal lab results, or direct medication changes. Always consult a qualified healthcare professional.
