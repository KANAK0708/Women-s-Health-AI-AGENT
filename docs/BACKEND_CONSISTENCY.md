# Backend Consistency & Contract Specification

This document details the consistency guarantees, shared contracts, and intentional implementation differences between the local in-memory engines and the production database adapters (PostgreSQL + pgvector and Redis).

---

## 1. Preserved Contracts

All memory and retrieval implementations strictly adhere to the shared upstream schemas defined in `app/schemas/evidence.py` and `app/schemas/memory.py`:

### `RetrievalBundle`
Both `HybridRetrievalEngine` (local) and `PgVectorHybridEngine` (PostgreSQL) return a canonical `RetrievalBundle`:
* `manifest_version`: String identifier indicating the evidence registry version (`"development-manifest-v1"` or `"pgvector-live"`).
* `scored_passages`: List of `ScoredPassage` objects containing the passage text, category, metadata, lexical score, vector score, and composite score.
* `citations`: List of `EvidenceCitation` objects with IDs `e1`, `e2`, ..., exactly aligned 1-to-1 with `scored_passages`.
* **Zero Orphan Policy**: Every citation maps to an exact passage, and every passage has an identical citation matching `source_id`, `title`, `url`, `locator`, and `reviewed_at`. This satisfies `health_tools.handoff.adapt_retrieval` verification.

### `SessionMemory`
Both `EphemeralSessionStore` (local) and `RedisSessionStore` (Redis) manage `SessionMemory` models:
* `session_id`: Unique session string (UUID).
* `created_at` & `expires_at`: Strict timezone-aware UTC datetimes with `created_at < expires_at`.
* `allow_session_context`: Boolean consent flag. When `False`, context is suppressed and never stored.
* `context`: `MinimalPatientContext` containing tri-state values (`yes`, `no`, `not_provided`), age (integer 1–120), active topic, and clarification turn counter.
* `turn_count` & `audit_codes`: Monotonically incrementing turn count and append-only audit trail.

---

## 2. Equivalent Clinical Eligibility Rules

Both local and database engines deterministically enforce identical eligibility boundaries before considering relevance:

1. **Supersession**: Sources with `is_superseded = TRUE` (such as `src-legacy-pcos-2018`) are strictly excluded.
2. **Expiry**: Sources where `expiry_date < reference_date` (defaults to current date) are excluded.
3. **Target Population**: Guidelines are matched to target population (`adults_18+`). Pediatric requests are excluded.
4. **Jurisdiction**: Sources matching the requested jurisdiction or labeled `Global` are eligible.
5. **Topic Anchoring**: Query terms are checked against `topic_anchor_terms()` to prevent cross-topic hallucination (e.g., emergency contraception queries never return menstrual health passages).
6. **Relevance Thresholding**: Queries with scores below calibrated thresholds or with no qualifying passages raise `InsufficientEvidenceError`.
7. **Clinical Verification Gating**: Unreviewed development material is marked `approval_status = 'unverified'` and requires explicit development authorization (`allow_unverified_for_development = True` or `ALLOW_UNVERIFIED_EVIDENCE=true`).

---

## 3. Intentional Differences

While clinical eligibility rules are identical, the following differences are intentional and architectural:

| Dimension | Local In-Memory Engine (`HybridRetrievalEngine`) | Production Database Engine (`PgVectorHybridEngine`) | Rationale |
| :--- | :--- | :--- | :--- |
| **Storage Medium** | Loaded in-memory from `manifest.json` on disk. | Relational tables in PostgreSQL with pgvector extension. | Local mode requires zero infrastructure for quick local testing; PostgreSQL supports multi-worker production scale. |
| **Lexical Scoring** | BM25-inspired TF-IDF token matching with IDF penalization. | PostgreSQL Full-Text Search using `tsvector` and `ts_rank_cd`. | Utilizes native, indexed PostgreSQL full-text search capabilities for high throughput. |
| **Vector Scoring** | L2-normalized MD5 n-gram hashed embeddings with NumPy cosine dot product. | pgvector cosine distance operator `<=>` evaluated in SQL: `1.0 - (embedding <=> query_vec)`. | Offloads vector similarity calculation directly to the PostgreSQL query planner. |
| **Score Calibration** | Composite score formula: `0.55 * lexical + 0.35 * vector + 0.10 * intent_boost`. Default threshold: `0.14`. | Composite score formula: `0.60 * ts_rank_cd + 0.40 * vector`. Default threshold: `0.18`. | Calibrated specifically for PostgreSQL `ts_rank_cd` and pgvector distributions to cleanly reject unrelated queries while retaining high precision on clinical queries. |
| **Punctuation Handling**| Python regex tokenization (`re.findall(r"[a-z0-9]+")`). | Python regex tokenization converted into sanitized `to_tsquery` terms joined by `\|`. | Prevents PostgreSQL full-text syntax errors from special characters like `?`, `!`, `(`, `)`, `&`, `:`. |
| **Session Concurrency**| Single-process in-memory dictionary. | Distributed Redis key-value store with native TTL expiration. | Redis provides cross-process session isolation, horizontal scalability, and automatic TTL eviction. |
| **Failure Mode** | Returns in-memory results; raises on file absence. | Self-healing: auto-registers pgvector, and `get_retrieval_engine()` gracefully falls back to local engine if unreachable. | High availability: temporary database outages do not crash the agent. |

---

## 4. Evidence Provenance & Audit

All evidence in `clinical/evidence_manifest/manifest.json` has been audited for honesty:
* **Reviewer Identity**: Placeholder identifiers (e.g. `"clinician-lead-01"`) were replaced with `"pending-clinical-review"`.
* **Content Hashes**: Each source contains a genuine `sha256:` digest computed from the text of its passages.
* **Passage Text**: Described as development summaries pending clinical validation, not verbatim quotes.
* **Reuse Rights**: Specified as educational summaries for development under fair dealing/fair use.
* **System Version Notice**: All responses explicitly include the development build limitation.
