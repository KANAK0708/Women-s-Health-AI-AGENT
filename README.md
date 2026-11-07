# Women's Health AI Agent

An evidence-grounded women's health education and care-navigation assistant focused on adult menstrual health and PCOS education (**what a condition is**, **recognized symptoms**, and **evidence-based lifestyle & prevention habits**).

## Implementation Plan and Team Diagrams

See the [implementation plan](docs/IMPLEMENTATION_PLAN.md) for the architecture, clinical safety workflow, evidence lifecycle, validation gates, roadmap, and first-sprint backlog. For an offline shareable version with eight rendered diagrams, open [the HTML handoff](docs/IMPLEMENTATION_PLAN.html) in a browser.

## Clinical Evidence Base (`clinical/evidence_manifest/`)

The manifest contains unverified development summaries, not clinically approved passages. Default retrieval excludes them. See the [provenance audit](docs/EVIDENCE_PROVENANCE_AUDIT.md) before any source is considered for approval.
The legacy records reference Monash, WHO, NICHD, ACOG, and CDC pages. Their stored
text, dates, locators, reviewer details, hashes, and reuse rights require review.

---

## Core Architecture: Memory & Retrieval

The system enforces two strictly isolated trust domains:

1. **Clinical Evidence & Hybrid Retrieval Engine (`app/retrieval/`, `clinical/evidence_manifest/`)**
   - **PostgreSQL + pgvector (`app/retrieval/pg_vector_engine.py`)**: Hybrid search combining PostgreSQL full-text search and `pgvector` cosine similarity, filtered by explicit approval, non-supersession, expiry, population, jurisdiction, topic anchors, and a PostgreSQL-specific score threshold.
   - **In-Memory Fallback (`app/retrieval/engine.py`, `app/retrieval/reranker.py`)**: Local hybrid search over `manifest.json` with the same eligibility and topic-anchor rules. Its IDF-based score differs from PostgreSQL's `ts_rank_cd` score; thresholds are calibrated separately. Expiry is inclusive on the date in both backends.
   - **Discovery Search (`tools.py`, `app/retrieval/engine.py`)**: Wikipedia and DuckDuckGo are for offline discovery only. Missing approved evidence produces an abstention in the application answer path.
   - **Offline Discovery & Database Sync (`pipelines/seed_evidence.py`, `pipelines/sync_to_postgres.py`)**: Stages candidates into review queues and synchronizes approved manifests into PostgreSQL.

2. **Ephemeral Patient Session Memory (`app/storage/`, `app/schemas/memory.py`)**
   - **Redis Store (`app/storage/redis_session_store.py`)**: Ephemeral session memory with Redis key TTL (default 30 minutes), logical expiry checks, and explicit deletion.
   - **In-Memory Store (`app/storage/session_store.py`)**: Zero-dependency in-memory session store fallback.
   - **TriState Context Tracking (`app/storage/context_tracker.py`)**: Uses explicit `TriState` (`yes`, `no`, `not_provided`) so missing pregnancy status, medication use, or age never silently become negative findings.
   - **Clarification Turn Cap**: Enforces a maximum of **2 focused clarification turns**.

3. **Claim-to-Passage Entailment Verification (`app/verification/`)**
   - **Citation Integrity & Factual Grounding (`app/verification/verifier.py`)**: Evaluates every generated clinical claim against cited passage tokens before displaying it to the user.
   - **Safety Extrapolation Filter**: Detects high-risk assertions (e.g., "cure", "guaranteed", unverified dosing) and polarity/negation contradictions, automatically triggering safe fallback or filtering unsupported claims.

---

## Infrastructure (PostgreSQL + pgvector & Redis)

Start the production-grade database services with Docker:
```bash
docker compose -f infra/docker-compose.yml up -d
```
Populate the PostgreSQL database from the clinical evidence manifest:
```bash
python pipelines/sync_to_postgres.py
```

---

## Repository Structure

```text
├── app/
│   ├── retrieval/
│   │   ├── engine.py          # HybridRetrievalEngine & GuardrailedEducationalSearch
│   │   ├── pg_vector_engine.py# PostgreSQL + pgvector Hybrid Engine
│   │   ├── filters.py         # Pre-retrieval hazard detection, scope guardrails & source eligibility
│   │   ├── reranker.py        # Hybrid lexical + vector scoring & bounded excerpt selection
│   │   └── exceptions.py      # UrgentEscalationRequired, ScopeViolationError, InsufficientEvidenceError
│   ├── schemas/
│   │   ├── evidence.py        # SourceMetadata, EvidencePassage, EducationalResponse
│   │   └── memory.py          # TriState, MinimalPatientContext, SessionMemory
│   ├── storage/
│   │   ├── consent.py         # ConsentPolicy & TTL rules
│   │   ├── context_tracker.py # Safe TriState context extraction & 2-turn clarification cap
│   │   ├── session_store.py   # EphemeralSessionStore with TTL & deletion cascades
│   │   └── redis_session_store.py # RedisSessionStore with native SETEX TTL
│   └── verification/
│       └── verifier.py        # ClaimVerifier, entailment checks & high-risk extrapolation filters
├── clinical/
│   └── evidence_manifest/
│       └── manifest.json      # Versioned, unverified development passages
├── docs/
│   ├── IMPLEMENTATION_PLAN.md # Engineering and clinical implementation plan
│   └── IMPLEMENTATION_PLAN.html # Offline shareable handoff with 8 SVG diagrams
├── evals/
│   ├── development/
│   │   └── seed_cases.json    # 50 clinician-labeled development benchmark cases
│   ├── rubric/
│   │   └── scoring.py         # Section 10 release gates scoring rubric
│   └── run_evals.py           # Automated evaluation runner
├── infra/
│   └── docker-compose.yml     # PostgreSQL + pgvector & Redis container orchestration
├── pipelines/
│   ├── seed_evidence.py       # Offline Wikipedia/DuckDuckGo staging pipeline
│   ├── sync_to_postgres.py    # PostgreSQL + pgvector manifest synchronizer
│   └── update_manifest.py     # Clinical manifest updater
├── tests/
│   ├── test_memory_and_retrieval.py # Retrieval & memory unit/integration test suite
│   ├── test_claim_verifier.py # Claim entailment & citation resolution test suite
│   └── test_database_adapters.py # PostgreSQL + pgvector & Redis fallback tests
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

2. **Configure environment variables**:
   Copy `.env.example` to `.env` and set your API keys (`GROQ_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`).

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
