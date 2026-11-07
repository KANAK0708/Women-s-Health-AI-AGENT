"""PostgreSQL + pgvector Hybrid Retrieval Engine.

Implements Section 3 and Section 6 of the Implementation Plan:
- Stores approved clinical sources and versioned passages in PostgreSQL.
- Uses pgvector (vector cosine distance '<=>') combined with PostgreSQL Full-Text Search (tsvector + ts_rank_cd).
- Enforces deterministic pre-filters (non-superseded, non-expired, adult population, jurisdiction) in SQL.
- Provides atomic ingestion from manifest.json.
- Gracefully falls back to local in-memory HybridRetrievalEngine when PostgreSQL is unconfigured or unreachable.
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2.extras import RealDictCursor

from app.retrieval.engine import HybridRetrievalEngine, RetrievalBundle
from app.retrieval.exceptions import InsufficientEvidenceError
from app.retrieval.filters import validate_educational_query_scope
from app.retrieval.reranker import ScoredPassage, compute_hashed_embedding
from app.schemas.evidence import (
    EducationalCategory,
    EvidenceCitation,
    EvidencePassage,
)

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/womens_health_ai"
EMBEDDING_DIM = 256

SCHEMA_SQL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS clinical_sources (
    source_id TEXT PRIMARY KEY,
    publisher TEXT NOT NULL,
    title TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    publication_date DATE NOT NULL,
    update_date DATE,
    ingestion_date DATE NOT NULL,
    review_date DATE NOT NULL,
    expiry_date DATE NOT NULL,
    jurisdiction TEXT NOT NULL DEFAULT 'Global',
    population TEXT NOT NULL DEFAULT 'adults_18+',
    life_stage TEXT[] NOT NULL DEFAULT '{{menstrual_health,pcos}}',
    evidence_grade TEXT,
    reviewer_id TEXT NOT NULL,
    license TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_superseded BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_sources_eligibility 
ON clinical_sources (is_superseded, expiry_date, population);

CREATE TABLE IF NOT EXISTS clinical_passages (
    passage_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES clinical_sources(source_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    locator TEXT NOT NULL,
    category TEXT NOT NULL,
    topic_tags TEXT[] NOT NULL DEFAULT '{{}}',
    text TEXT NOT NULL,
    reviewed_at DATE NOT NULL,
    embedding vector({EMBEDDING_DIM}),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(text, ''))
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_passages_tsv ON clinical_passages USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_passages_category ON clinical_passages(category);
"""


class PgVectorHybridEngine:
    """Production-grade PostgreSQL + pgvector hybrid retrieval engine."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or os.getenv(DATABASE_URL_ENV, DEFAULT_DATABASE_URL)

    def _get_raw_connection(self) -> psycopg2.extensions.connection:
        return psycopg2.connect(self.database_url, connect_timeout=3)

    def _get_connection(self) -> psycopg2.extensions.connection:
        conn = self._get_raw_connection()
        try:
            register_vector(conn)
        except Exception:
            # Self-healing: if extension was not yet registered, ensure it exists
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            register_vector(conn)
        return conn

    def ping(self) -> bool:
        """Check if PostgreSQL database is reachable."""
        try:
            with self._get_raw_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    return True
        except Exception as exc:
            logger.warning("PostgreSQL ping failed: %s", exc)
            return False

    def init_schema(self) -> None:
        """Create tables, indexes, and pgvector extension if they do not exist."""
        with self._get_raw_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
            conn.commit()

    def sync_from_manifest(self, manifest_path: Path) -> tuple[int, int]:
        """Atomically upsert all sources and passages from a manifest.json file."""
        self.init_schema()
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))

        sources_data = raw.get("sources", [])
        passages_data = raw.get("passages", [])

        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Upsert Sources
                for s in sources_data:
                    cur.execute(
                        """
                        INSERT INTO clinical_sources (
                            source_id, publisher, title, canonical_url,
                            publication_date, update_date, ingestion_date, review_date,
                            expiry_date, jurisdiction, population, life_stage,
                            evidence_grade, reviewer_id, license, content_hash, is_superseded
                        ) VALUES (
                            %(source_id)s, %(publisher)s, %(title)s, %(canonical_url)s,
                            %(publication_date)s, %(update_date)s, %(ingestion_date)s, %(review_date)s,
                            %(expiry_date)s, %(jurisdiction)s, %(population)s, %(life_stage)s,
                            %(evidence_grade)s, %(reviewer_id)s, %(license)s, %(content_hash)s, %(is_superseded)s
                        )
                        ON CONFLICT (source_id) DO UPDATE SET
                            publisher = EXCLUDED.publisher,
                            title = EXCLUDED.title,
                            canonical_url = EXCLUDED.canonical_url,
                            update_date = EXCLUDED.update_date,
                            review_date = EXCLUDED.review_date,
                            expiry_date = EXCLUDED.expiry_date,
                            is_superseded = EXCLUDED.is_superseded,
                            content_hash = EXCLUDED.content_hash;
                        """,
                        s,
                    )

                # 2. Upsert Passages
                for p in passages_data:
                    embedding = p.get("embedding")
                    if not embedding:
                        vec = compute_hashed_embedding(f"{p['title']} {' '.join(p.get('topic_tags', []))} {p['text']}")
                        embedding = vec.tolist()

                    cur.execute(
                        """
                        INSERT INTO clinical_passages (
                            passage_id, source_id, title, url, locator,
                            category, topic_tags, text, reviewed_at, embedding
                        ) VALUES (
                            %(passage_id)s, %(source_id)s, %(title)s, %(url)s, %(locator)s,
                            %(category)s, %(topic_tags)s, %(text)s, %(reviewed_at)s, %(embedding)s
                        )
                        ON CONFLICT (passage_id) DO UPDATE SET
                            title = EXCLUDED.title,
                            url = EXCLUDED.url,
                            locator = EXCLUDED.locator,
                            category = EXCLUDED.category,
                            topic_tags = EXCLUDED.topic_tags,
                            text = EXCLUDED.text,
                            reviewed_at = EXCLUDED.reviewed_at,
                            embedding = EXCLUDED.embedding;
                        """,
                        {**p, "embedding": embedding},
                    )

            conn.commit()

        return len(sources_data), len(passages_data)

    def retrieve(
        self,
        query: str,
        *,
        category: Optional[EducationalCategory] = None,
        jurisdiction: str = "Global",
        population: str = "adults_18+",
        reference_date: Optional[date] = None,
        max_excerpts: int = 6,
        min_score_threshold: float = 0.12,
    ) -> RetrievalBundle:
        """Perform hybrid (tsvector + pgvector) search with clinical pre-filters."""
        cleaned_query = validate_educational_query_scope(query)
        today = reference_date or date.today()
        query_vec = compute_hashed_embedding(cleaned_query).tolist()

        # Build sanitized tsquery words
        ts_terms = " | ".join(w for w in cleaned_query.replace("'", " ").split() if len(w) > 2)
        if not ts_terms:
            ts_terms = "pcos | menstrual"

        category_filter = "AND p.category = %(category)s" if category else ""

        sql = f"""
        SELECT 
            p.passage_id, p.source_id, p.title, p.url, p.locator, p.category,
            p.topic_tags, p.text, p.reviewed_at,
            ts_rank_cd(p.tsv, to_tsquery('english', %(ts_terms)s)) AS lexical_score,
            (1.0 - (p.embedding <=> %(query_vec)s::vector)) AS vector_score,
            (
                0.60 * coalesce(ts_rank_cd(p.tsv, to_tsquery('english', %(ts_terms)s)), 0.0) +
                0.40 * (1.0 - (p.embedding <=> %(query_vec)s::vector))
            ) AS hybrid_score
        FROM clinical_passages p
        JOIN clinical_sources s ON p.source_id = s.source_id
        WHERE s.is_superseded = FALSE
          AND s.expiry_date >= %(today)s
          AND s.population = %(population)s
          AND s.jurisdiction IN (%(jurisdiction)s, 'Global')
          {category_filter}
        ORDER BY hybrid_score DESC
        LIMIT %(limit)s;
        """

        params: dict[str, Any] = {
            "query_vec": query_vec,
            "ts_terms": ts_terms,
            "today": today,
            "population": population,
            "jurisdiction": jurisdiction,
            "limit": max_excerpts,
        }
        if category:
            params["category"] = category.value

        with self._get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        if not rows:
            raise InsufficientEvidenceError(
                f"No approved clinical passages in PostgreSQL met coverage threshold for query: '{cleaned_query}'."
            )

        scored_passages: list[ScoredPassage] = []
        citations: list[EvidenceCitation] = []

        for idx, row in enumerate(rows, start=1):
            passage = EvidencePassage(
                passage_id=row["passage_id"],
                source_id=row["source_id"],
                title=row["title"],
                url=row["url"],
                locator=row["locator"],
                category=EducationalCategory(row["category"]),
                topic_tags=row["topic_tags"],
                text=row["text"],
                reviewed_at=row["reviewed_at"],
            )

            scored = ScoredPassage(
                passage=passage,
                lexical_score=round(float(row["lexical_score"]), 4),
                vector_score=round(float(row["vector_score"]), 4),
                intent_boost=0.0,
                final_score=round(float(row["hybrid_score"]), 4),
            )
            scored_passages.append(scored)

            citations.append(
                EvidenceCitation(
                    id=f"e{idx}",
                    source_id=passage.source_id,
                    passage_id=passage.passage_id,
                    title=passage.title,
                    url=passage.url,
                    locator=passage.locator,
                    reviewed_at=str(passage.reviewed_at),
                )
            )

        return RetrievalBundle(
            query=cleaned_query,
            manifest_version="pgvector-live",
            scored_passages=scored_passages,
            citations=citations,
        )


def get_retrieval_engine(
    *,
    force_in_memory: bool = False,
    database_url: Optional[str] = None,
) -> PgVectorHybridEngine | HybridRetrievalEngine:
    """Factory returning PgVectorHybridEngine if PostgreSQL is configured and reachable;
    otherwise gracefully falls back to local manifest HybridRetrievalEngine.
    """
    if force_in_memory:
        return HybridRetrievalEngine()

    target_url = database_url or os.getenv(DATABASE_URL_ENV)
    if target_url:
        try:
            engine = PgVectorHybridEngine(database_url=target_url)
            if engine.ping():
                return engine
            logger.warning("PostgreSQL at %s unreachable, falling back to local manifest retrieval engine.", target_url)
        except Exception as exc:
            logger.warning("Failed connecting to PostgreSQL: %s. Using local fallback.", exc)

    return HybridRetrievalEngine()

