"""Small on-disk JSON cache for searches, fetched pages and model answers.

Repeat and similar questions skip slow network calls and save free-tier quota.
Keys are SHA-256 hashes of everything that affects the result (for model calls:
model names, prompt, input and output schema), so changing a prompt never
reuses a stale answer. Entries expire after a TTL.

Location: .cache/research/ in the project (override with RESEARCH_CACHE_DIR).
Disable with RESEARCH_CACHE=off.
"""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

DAY = 86_400
SEARCH_TTL = 3 * DAY
PAGE_TTL = 7 * DAY
LLM_TTL = 30 * DAY


def _root() -> Path | None:
    if os.environ.get("RESEARCH_CACHE", "").casefold() in {"off", "0", "false", "no"}:
        return None
    default = Path(__file__).resolve().parents[2] / ".cache" / "research"
    return Path(os.environ.get("RESEARCH_CACHE_DIR", default))


def make_key(*parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path(namespace: str, key: str) -> Path | None:
    root = _root()
    return None if root is None else root / namespace / key[:2] / f"{key}.json"


def get(namespace: str, key: str, ttl: float):
    path = _path(namespace, key)
    if path is None or not path.exists():
        return None
    try:
        entry = json.loads(path.read_text("utf-8"))
        if time.time() - entry["saved_at"] > ttl:
            return None
        return entry["value"]
    except (OSError, ValueError, KeyError):
        return None  # A corrupt entry is treated as a miss and overwritten later.


def put(namespace: str, key: str, value) -> None:
    path = _path(namespace, key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so concurrent readers never see a half-written file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"saved_at": time.time(), "value": value}, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass  # Caching is best-effort; never fail a research run over it.
