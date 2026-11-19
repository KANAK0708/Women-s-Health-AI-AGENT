"""Bounded Europe PMC biomedical literature retrieval via EMBL-EBI REST API.

No LLM, memory, persistence, or third-party Python dependencies are used.
Retrieves peer-reviewed open-access biomedical articles and systematic reviews.
"""

import argparse
import html
import json
import math
import re
import socket
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import EvidenceSource, ToolError, ToolResult


BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
MAX_RESPONSE_BYTES = 2_000_000
LIMITATIONS = (
    "Europe PMC results are scientific literature records, not approved clinical recommendations or personalized medical advice.",
    "Abstracts may be incomplete; study quality and applicability require clinical evaluation.",
    "Consult a qualified healthcare professional before acting on research findings.",
)
_request_lock = threading.Lock()
_last_request = 0.0
_TAG_RE = re.compile(r"<[^>]+>")


class _ResponseError(Exception):
    pass


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    unescaped = html.unescape(value)
    return " ".join(_TAG_RE.sub(" ", unescaped).split())


def _request(params: dict[str, str], timeout: float) -> bytes:
    """Fixed-host GET, bounded read, and rate pacing."""
    global _last_request
    url = f"{BASE_URL}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": "WomenHealthResearchTools/0.1",
            "Accept": "application/json",
        },
    )
    with _request_lock:
        remaining = 0.35 - (time.monotonic() - _last_request)
        if remaining > 0:
            time.sleep(remaining)
        _last_request = time.monotonic()
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise _ResponseError("oversized response")
    return body


def search_europepmc(query: str, max_results: int = 3, *, timeout: float = 10) -> ToolResult:
    """Search Europe PMC for biomedical papers and reviews (up to 5 results).

    Sends the query to EMBL-EBI Europe PMC. Caller must remove personal health
    identifiers and obtain any required permission before invocation.
    """
    def fail(code: str, message: str, retryable: bool = False) -> ToolResult:
        return ToolResult(
            tool="search_europepmc",
            status="error",
            limitations=LIMITATIONS,
            error=ToolError(code, message, retryable),
        )

    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return fail("invalid_query", "Supply a nonempty research query of at most 500 characters.")
    if type(max_results) is not int or not 1 <= max_results <= 5:
        return fail("invalid_limit", "max_results must be an integer from 1 to 5.")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or not 0 < timeout <= 30
    ):
        return fail("invalid_timeout", "timeout must be a finite number above 0 and at most 30 seconds.")

    try:
        raw = _request(
            {
                "query": query.strip(),
                "format": "json",
                "resultType": "core",
                "pageSize": str(max_results),
            },
            timeout,
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise _ResponseError("invalid payload")

        hit_count = payload.get("hitCount")
        if not isinstance(hit_count, int) or isinstance(hit_count, bool) or hit_count < 0:
            raise _ResponseError("invalid hitCount")

        result_list = payload.get("resultList", {})
        if not isinstance(result_list, dict):
            raise _ResponseError("invalid resultList")
        items = result_list.get("result", [])
        if not isinstance(items, list):
            raise _ResponseError("invalid result array")
        items = items[:max_results]

        data: dict = {"total_matches": hit_count, "returned_count": 0, "articles": []}
        if not items or hit_count == 0:
            return ToolResult(
                tool="search_europepmc",
                status="insufficient_data",
                data=data,
                limitations=LIMITATIONS + ("No Europe PMC records matched this query.",),
            )

        sources: list[EvidenceSource] = []
        retrieved_at = datetime.now(timezone.utc).isoformat()

        for item in items:
            if not isinstance(item, dict):
                raise _ResponseError("invalid article item")
            rec_id = _clean_text(item.get("id") or item.get("pmid") or item.get("pmcid"))
            source_code = _clean_text(item.get("source") or "MED")
            title = _clean_text(item.get("title"))
            if not rec_id or not title:
                raise _ResponseError("missing article id or title")

            abstract = _clean_text(item.get("abstractText")) or None
            pub_year = _clean_text(str(item.get("pubYear") or "")) or None
            journal = _clean_text(
                item.get("journalTitle")
                or (item.get("journalInfo", {}) or {}).get("journal", {}).get("title")
            ) or None
            doi = _clean_text(item.get("doi")) or None
            pmcid = _clean_text(item.get("pmcid")) or None
            pmid = _clean_text(item.get("pmid")) or None

            url = f"https://europepmc.org/article/{source_code}/{rec_id}"
            source_id = f"europepmc:{source_code}:{rec_id}"

            record = {
                "id": rec_id,
                "source_id": source_id,
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": title,
                "url": url,
                "journal": journal,
                "publication_date": pub_year,
                "abstract": abstract,
                "is_open_access": item.get("isOpenAccess") == "Y",
                "publication_types": [
                    _clean_text(t) for t in ((item.get("pubTypeList") or {}).get("pubType") or [])
                    if isinstance(t, str) and _clean_text(t)
                ],
            }
            data["articles"].append(record)
            sources.append(
                EvidenceSource(
                    source_id=source_id,
                    title=title,
                    url=url,
                    publisher="EMBL-EBI / Europe PMC",
                    retrieved_at=retrieved_at,
                    excerpt=abstract or "",
                    publication_date=pub_year,
                    locator="Abstract" if abstract else "Citation metadata only",
                )
            )

        data["returned_count"] = len(sources)
        return ToolResult(
            tool="search_europepmc",
            status="ok",
            data=data,
            sources=tuple(sources),
            limitations=LIMITATIONS,
        )
    except HTTPError as exc:
        if exc.code == 429:
            return fail("rate_limited", "Europe PMC returned HTTP 429 (rate limit); try again later.", True)
        retryable = 500 <= exc.code <= 599
        return fail("http_error", f"Europe PMC returned HTTP {exc.code}.", retryable)
    except (TimeoutError, socket.timeout):
        return fail("timeout", "Europe PMC request timed out.", True)
    except (URLError, OSError):
        return fail("network_error", "Could not reach Europe PMC.", True)
    except (ValueError, TypeError, _ResponseError):
        return fail("invalid_response", "Europe PMC returned an incomplete or invalid response.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Europe PMC biomedical literature.")
    parser.add_argument("query", help="Research terms only; do not include personal identifiers")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()
    result = search_europepmc(args.query, args.max_results)
    print(json.dumps(result.to_dict(), indent=2))
    if result.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()

