"""Hybrid lexical + vector scoring and bounded excerpt reranking.

Implements Section 6 of the Implementation Plan:
- Combines lexical term matching (BM25-inspired) with vector cosine similarity.
- Boosts passages matching the user's educational intent (definition / 'what it is',
  symptoms, prevention & lifestyle).
- Caps candidate pool (~20) and returns bounded excerpts (4 to 8 passages).
"""

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.schemas.evidence import EducationalCategory, EvidencePassage

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for",
    "from", "have", "how", "i", "in", "is", "it", "me", "my", "of", "on", "or",
    "should", "tell", "that", "the", "their", "them", "this", "to", "what", "when",
    "where", "which", "who", "why", "with", "you", "your", "about",
}

SYNONYM_EXPANSIONS: dict[str, list[str]] = {
    "pcod": ["pcos", "polycystic", "ovary", "syndrome"],
    "pcos": ["polycystic", "ovary", "syndrome", "hormonal", "androgens", "ovulation"],
    "period": ["menstrual", "menstruation", "cycle", "bleeding", "periods"],
    "periods": ["menstrual", "menstruation", "cycle", "bleeding", "irregular"],
    "cramps": ["dysmenorrhea", "cramping", "pelvic", "pain", "menstrual"],
    "prevent": ["prevention", "lifestyle", "habits", "exercise", "diet", "self-care"],
    "prevention": ["lifestyle", "habits", "exercise", "diet", "management"],
    "symptom": ["symptoms", "signs", "irregular", "hirsutism", "acne"],
}

# These words describe the question, not the condition or product being asked about.
GENERIC_QUERY_TERMS = {
    "side", "effect", "effects", "taking", "take", "symptom", "symptoms",
    "sign", "signs", "definition", "overview", "explain", "prevention",
    "prevent", "lifestyle", "manage", "management", "treatment", "pill",
    "medicine", "medication", "health", "problem", "problems", "condition",
}


@dataclass(frozen=True)
class ScoredPassage:
    """A passage paired with its hybrid retrieval and reranking score."""

    passage: EvidencePassage
    lexical_score: float
    vector_score: float
    intent_boost: float
    final_score: float


def tokenize(text: str, *, expand_synonyms: bool = False) -> list[str]:
    """Tokenize lowercase alphanumeric terms, removing common stopwords."""
    raw_tokens = re.findall(r"[a-z0-9]+", text.lower())
    filtered = [t for t in raw_tokens if t not in STOPWORDS and len(t) > 1]
    if not expand_synonyms:
        return filtered

    expanded = list(filtered)
    for token in filtered:
        if token in SYNONYM_EXPANSIONS:
            expanded.extend(SYNONYM_EXPANSIONS[token])
    return expanded


def topic_anchor_terms(query: str) -> list[str]:
    """Return distinctive topic terms required in a supporting passage."""
    normalized = re.sub(r"\bi[\s-]?pill\b", "ipill", query.lower())
    return sorted(set(tokenize(normalized)) - GENERIC_QUERY_TERMS)


def compute_hashed_embedding(text: str, dim: int = 256) -> np.ndarray:
    """Compute a deterministic L2-normalized character/word n-gram embedding vector."""
    vec = np.zeros(dim, dtype=np.float32)
    tokens = tokenize(text, expand_synonyms=True)
    if not tokens:
        return vec

    features: list[str] = list(tokens)
    # Add word bigrams and character 4-grams for morphological resilience
    for i in range(len(tokens) - 1):
        features.append(f"{tokens[i]}_{tokens[i + 1]}")
    for token in tokens:
        if len(token) >= 4:
            for j in range(len(token) - 3):
                features.append(token[j : j + 4])

    for feat in features:
        digest = hashlib.md5(feat.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "little") % dim
        sign = 1.0 if (digest[2] & 1) == 0 else -1.0
        vec[idx] += sign

    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec /= norm
    return vec


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Return cosine similarity in [0.0, 1.0] between two normalized vectors."""
    sim = float(np.dot(vec_a, vec_b))
    return max(0.0, min(1.0, sim))


def detect_educational_intents(query: str) -> set[EducationalCategory]:
    """Infer which educational pillars the user is asking about."""
    q_lower = query.lower()
    intents: set[EducationalCategory] = set()

    if any(k in q_lower for k in ("what is", "what are", "define", "meaning", "overview", "explain", "know about")):
        intents.add(EducationalCategory.DEFINITION)
    if any(k in q_lower for k in ("symptom", "sign", "feel like", "experience", "irregular", "cramp", "acne", "hair")):
        intents.add(EducationalCategory.SYMPTOMS)
    if any(k in q_lower for k in ("prevent", "lifestyle", "habit", "diet", "exercise", "manage", "self-care", "help", "reduce")):
        intents.add(EducationalCategory.PREVENTION_LIFESTYLE)
    if any(k in q_lower for k in ("doctor", "urgent", "hospital", "when to seek", "warning")):
        intents.add(EducationalCategory.WHEN_TO_SEEK_CARE)

    # Default: if the user asks a broad topic question (e.g., "PCOS"), cover all three core pillars
    if not intents:
        intents.update(
            {
                EducationalCategory.DEFINITION,
                EducationalCategory.SYMPTOMS,
                EducationalCategory.PREVENTION_LIFESTYLE,
            }
        )
    return intents


def rerank_passages(
    query: str,
    candidates: list[EvidencePassage],
    *,
    max_candidates: int = 20,
    max_excerpts: int = 6,
    min_score_threshold: float = 0.12,
    preferred_category: Optional[EducationalCategory] = None,
) -> list[ScoredPassage]:
    """Score, filter, and rerank passages using hybrid lexical + vector similarity."""
    if not candidates:
        return []

    query_tokens = tokenize(query, expand_synonyms=True)
    anchors = topic_anchor_terms(query)
    if not query_tokens or not anchors:
        return []

    query_vec = compute_hashed_embedding(query)
    active_intents = {preferred_category} if preferred_category else detect_educational_intents(query)

    # Precompute document frequencies across candidate pool for IDF weighting
    num_docs = len(candidates)
    doc_freq: dict[str, int] = {}
    doc_token_sets: list[set[str]] = []

    for passage in candidates:
        combined_text = f"{passage.title} {' '.join(passage.topic_tags)} {passage.text}"
        t_set = set(tokenize(combined_text, expand_synonyms=False))
        doc_token_sets.append(t_set)
        for token in t_set:
            doc_freq[token] = doc_freq.get(token, 0) + 1

    scored_pool: list[ScoredPassage] = []
    unique_query_tokens = set(query_tokens)

    for idx, passage in enumerate(candidates):
        t_set = doc_token_sets[idx]
        if not t_set.intersection(anchors):
            continue
        tag_tokens = set(tokenize(" ".join(passage.topic_tags), expand_synonyms=False))

        # 1. Lexical IDF-weighted overlap score
        matched_weight = 0.0
        total_weight = 0.0
        for q_tok in unique_query_tokens:
            df = doc_freq.get(q_tok, 0)
            idf = math.log(1.0 + (num_docs - df + 0.5) / (df + 0.5))
            total_weight += idf
            if q_tok in t_set:
                tag_multiplier = 1.35 if q_tok in tag_tokens else 1.0
                matched_weight += idf * tag_multiplier

        lexical_score = (matched_weight / total_weight) if total_weight > 0 else 0.0
        lexical_score = min(1.0, lexical_score)

        # 2. Vector similarity score
        passage_vec = (
            np.array(passage.embedding, dtype=np.float32)
            if passage.embedding is not None
            else compute_hashed_embedding(f"{passage.title} {' '.join(passage.topic_tags)} {passage.text}")
        )
        vector_score = cosine_similarity(query_vec, passage_vec)

        # 3. Educational intent boost (only applied when there is base lexical/vector relevance)
        base_score = 0.60 * lexical_score + 0.40 * vector_score
        intent_boost = 0.12 if (base_score >= 0.08 and passage.category in active_intents) else 0.0

        final_score = base_score + intent_boost
        if final_score >= min_score_threshold:
            scored_pool.append(
                ScoredPassage(
                    passage=passage,
                    lexical_score=round(lexical_score, 4),
                    vector_score=round(vector_score, 4),
                    intent_boost=round(intent_boost, 4),
                    final_score=round(final_score, 4),
                )
            )

    scored_pool.sort(key=lambda item: item.final_score, reverse=True)
    shortlist = scored_pool[:max_candidates]
    return shortlist[:max_excerpts]

