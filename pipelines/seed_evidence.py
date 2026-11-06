"""Offline educational evidence discovery & staging pipeline using Wikipedia & DuckDuckGo.

Implements Section 6 of the Implementation Plan:
- Uses guardrailed Wikipedia and DuckDuckGo searches strictly scoped to:
  1. Definition ('what_it_is')
  2. Recognized symptoms ('symptoms')
  3. Prevention and lifestyle measures ('prevention_and_lifestyle')
- Writes candidate records with SHA-256 content hashes into a clinician staging
  queue (`clinical/evidence_manifest/staging_queue.json`) so discovery search
  never bypasses clinical approval.
"""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from app.retrieval.engine import GuardrailedEducationalSearch
from app.schemas.evidence import EducationalCategory

STAGING_QUEUE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clinical"
    / "evidence_manifest"
    / "staging_queue.json"
)


def compute_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def discover_topic_for_staging(
    topic: str,
    *,
    search_client: GuardrailedEducationalSearch | None = None,
    output_path: Path = STAGING_QUEUE_PATH,
) -> list[dict[str, Any]]:
    """Fetch definition, symptoms, and prevention candidates from Wikipedia & DuckDuckGo
    and write them to the clinician review queue.
    """
    client = search_client or GuardrailedEducationalSearch()
    today_str = str(date.today())

    pillars = [
        EducationalCategory.DEFINITION,
        EducationalCategory.SYMPTOMS,
        EducationalCategory.PREVENTION_LIFESTYLE,
    ]

    staged_items: list[dict[str, Any]] = []
    for category in pillars:
        try:
            wiki_text = client.search_wikipedia(topic, focus=category)
        except Exception as exc:
            wiki_text = f"Wikipedia fetch unavailable: {exc}"

        try:
            ddg_text = client.search_duckduckgo(topic, focus=category)
        except Exception as exc:
            ddg_text = f"DuckDuckGo fetch unavailable: {exc}"

        combined = f"{wiki_text}\n\n{ddg_text}".strip()
        staged_items.append(
            {
                "topic": topic,
                "category": category.value,
                "staged_at": today_str,
                "approval_status": "PENDING_CLINICAL_REVIEW",
                "content_hash": compute_sha256(combined),
                "candidate_text": combined,
            }
        )

    existing: list[dict[str, Any]] = []
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    existing.extend(staged_items)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return staged_items


if __name__ == "__main__":
    items = discover_topic_for_staging("Polycystic ovary syndrome")
    print(f"Staged {len(items)} educational items to {STAGING_QUEUE_PATH}")
