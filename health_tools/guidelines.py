"""Offline search over a trusted, versioned passage registry.

Registry paths are developer configuration, never model/user-selected paths.
Approval metadata is an administrative control, not proof of clinical correctness.
"""

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import EvidenceSource, ToolError, ToolResult


DEFAULT_REGISTRY = Path(__file__).with_name("data") / "guidelines.json"
DEMO_REGISTRY = Path(__file__).with_name("data") / "guidelines_demo.json"
LIMITATIONS = (
    "Retrieval matches approved registry passages; relevance is not a clinical applicability assessment.",
    "Results are limited to the selected jurisdiction, population, language, and registry version.",
    "No diagnosis, treatment selection, or urgent-symptom assessment is performed.",
)
STOP_WORDS = {"a", "an", "the", "and", "or", "of", "to", "for", "is", "are", "my", "what", "how", "i", "in", "on", "with", "does", "do", "can"}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold())) - STOP_WORDS


def _date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Expected ISO date")
    return date.fromisoformat(value)


def _load(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Registry too large")
    registry = json.loads(raw)
    if not isinstance(registry, dict) or registry.get("schema_version") != "1.0":
        raise ValueError("Invalid registry")
    if registry.get("kind") not in {"clinical", "demo"}:
        raise ValueError("Invalid registry kind")
    if not isinstance(registry.get("version"), str) or not registry["version"].strip():
        raise ValueError("Missing version")
    passages = registry.get("passages")
    if not isinstance(passages, list):
        raise ValueError("Invalid passages")
    ids = set()
    for item in passages:
        if not isinstance(item, dict):
            raise ValueError("Invalid passage")
        for key in ("passage_id", "title", "url", "publisher", "source_version", "locator", "text", "jurisdiction", "population", "language"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError("Missing passage metadata")
        if item["passage_id"] in ids:
            raise ValueError("Duplicate passage ID")
        ids.add(item["passage_id"])
        url = urlsplit(item["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Invalid source URL")
        if item.get("status") not in {"draft", "approved", "superseded"}:
            raise ValueError("Invalid approval status")
        if item.get("rights_status") not in {"pending", "permitted"}:
            raise ValueError("Invalid rights status")
        if hashlib.sha256(item["text"].encode("utf-8")).hexdigest() != item.get("sha256"):
            raise ValueError("Passage content hash mismatch")
        if item["status"] == "approved":
            for key in ("reviewer", "rights_basis"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    raise ValueError("Missing review metadata")
            if _date(item["reviewed_on"]) >= _date(item["review_due"]):
                raise ValueError("Invalid review interval")
    return registry


def search_guidelines(
    query: str, *, jurisdiction: str, population: str, language: str = "en",
    max_results: int = 3, as_of: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY, allow_demo: bool = False,
) -> ToolResult:
    """Return exact eligible passages ranked by lexical query overlap.

    Registry path and allow_demo are trusted application settings. Do not expose
    them as model-callable arguments. No network, memory, or persistence access.
    Scope labels must match exactly; no automatic cross-jurisdiction fallback.
    """
    def fail(code: str, message: str) -> ToolResult:
        return ToolResult(tool="search_guidelines", status="error", limitations=LIMITATIONS,
                          error=ToolError(code, message))

    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return fail("invalid_query", "Supply a nonempty query of at most 500 characters.")
    if any(not isinstance(value, str) or not value.strip() for value in (jurisdiction, population, language)):
        return fail("invalid_scope", "Specify jurisdiction, population, and language explicitly.")
    if type(max_results) is not int or not 1 <= max_results <= 5:
        return fail("invalid_limit", "max_results must be an integer from 1 to 5.")
    try:
        today = date.today() if as_of is None else _date(as_of)
    except ValueError:
        return fail("invalid_as_of", "as_of must be a valid YYYY-MM-DD date.")
    try:
        registry = _load(Path(registry_path))
    except OSError:
        return fail("registry_unavailable", "The configured evidence registry could not be read.")
    except (ValueError, TypeError, KeyError):
        return fail("invalid_registry", "The evidence registry failed validation; no passages were returned.")
    demo = registry["kind"] == "demo"
    if demo and not allow_demo:
        return fail("demo_disabled", "Synthetic demonstration evidence is disabled.")
    limitations = LIMITATIONS
    if demo:
        limitations = ("SYNTHETIC DEMO ONLY: these passages are software fixtures, not medical evidence.",) + limitations
    terms = _tokens(query)
    ranked = []
    for item in registry["passages"]:
        if item["status"] != "approved" or item["rights_status"] != "permitted":
            continue
        if not _date(item["reviewed_on"]) <= today < _date(item["review_due"]):
            continue
        if any(item[key] != value for key, value in (
            ("jurisdiction", jurisdiction), ("population", population), ("language", language)
        )):
            continue
        overlap = terms & _tokens(item["title"] + " " + item["text"])
        if overlap:
            ranked.append((len(overlap) / len(terms), item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["passage_id"]))
    selected = ranked[:max_results]
    now = datetime.now(timezone.utc).isoformat()
    sources = tuple(EvidenceSource(
        source_id=item["passage_id"], title=item["title"], url=item["url"],
        publisher=item["publisher"], retrieved_at=now, excerpt=item["text"],
        locator=item["locator"],
    ) for _, item in selected)
    data = {
        "registry_version": registry["version"], "demo": demo,
        "returned_count": len(selected),
        "passages": [{
            "source_id": item["passage_id"], "text": item["text"],
            "source_version": item["source_version"], "sha256": item["sha256"],
            "reviewed_on": item["reviewed_on"], "review_due": item["review_due"],
            "jurisdiction": item["jurisdiction"], "population": item["population"],
            "language": item["language"], "lexical_overlap_score": score,
        } for score, item in selected],
    }
    if not selected:
        limitations += ("No matching eligible passages; do not substitute unreviewed sources.",)
    return ToolResult(tool="search_guidelines", status="ok" if selected else "insufficient_data",
                      data=data, sources=sources, limitations=limitations)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--population", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--max-results", type=int, default=3)
    parser.add_argument("--as-of")
    parser.add_argument("--demo", action="store_true", help="Use synthetic software fixtures only")
    args = parser.parse_args()
    result = search_guidelines(
        args.query, jurisdiction=args.jurisdiction, population=args.population,
        language=args.language, max_results=args.max_results, as_of=args.as_of,
        registry_path=DEMO_REGISTRY if args.demo else DEFAULT_REGISTRY, allow_demo=args.demo,
    )
    print(json.dumps(result.to_dict(), indent=2))
    if result.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()
