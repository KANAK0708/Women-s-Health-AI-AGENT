"""Bounded NIH MedlinePlus consumer health topic retrieval via NLM Web Service.

No LLM, memory, persistence, or third-party Python dependencies are used.
Queries the official U.S. National Library of Medicine MedlinePlus Web Service
for authoritative patient-education summaries on women's health conditions.
"""

import argparse
import html
import json
import math
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .contracts import EvidenceSource, ToolError, ToolResult


BASE_URL = "https://wsearch.nlm.nih.gov/ws/query"
MAX_RESPONSE_BYTES = 2_000_000
LIMITATIONS = (
    "MedlinePlus summaries provide general consumer health education, not individualized medical diagnosis or treatment.",
    "External search results are not automatically promoted to clinically verified claims.",
    "Consult a qualified healthcare professional for personal medical evaluation.",
)
_request_lock = threading.Lock()
_last_request = 0.0
_TAG_RE = re.compile(r"<[^>]+>")


class _ResponseError(Exception):
    pass


def _strip_html(raw_text: str) -> str:
    """Remove HTML tags and normalize whitespace from MedlinePlus XML fields."""
    unescaped = html.unescape(raw_text or "")
    cleaned = _TAG_RE.sub(" ", unescaped)
    return " ".join(cleaned.split())


def _request(params: dict[str, str], timeout: float) -> bytes:
    """Fixed-host GET with bounded read and process-local rate pacing (<1.4 req/sec)."""
    global _last_request
    url = f"{BASE_URL}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "User-Agent": "WomenHealthResearchTools/0.1",
            "Accept": "application/xml, text/xml",
        },
    )
    with _request_lock:
        remaining = 0.75 - (time.monotonic() - _last_request)
        if remaining > 0:
            time.sleep(remaining)
        _last_request = time.monotonic()
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise _ResponseError("oversized response")
    return body


def search_medlineplus(query: str, max_results: int = 3, *, timeout: float = 10) -> ToolResult:
    """Search NIH MedlinePlus health topics and return up to five consumer health summaries.

    Sends the query to NLM. Caller must remove personal health identifiers and
    obtain any required permission before invocation.
    """
    def fail(code: str, message: str, retryable: bool = False) -> ToolResult:
        return ToolResult(
            tool="search_medlineplus",
            status="error",
            limitations=LIMITATIONS,
            error=ToolError(code, message, retryable),
        )

    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return fail("invalid_query", "Supply a nonempty health topic query of at most 500 characters.")
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
                "db": "healthTopics",
                "term": query.strip(),
                "retmax": str(max_results),
            },
            timeout,
        )
        root = ET.fromstring(raw)
        if root.tag != "nlmSearchResult":
            raise _ResponseError("unexpected XML root")

        count_text = (root.findtext("count") or "0").strip()
        if not count_text.isdigit():
            raise _ResponseError("invalid count")
        total = int(count_text)

        docs = root.findall("./list/document")
        if len(docs) > max_results:
            docs = docs[:max_results]

        data: dict = {"total_matches": total, "returned_count": 0, "topics": []}
        if not docs or total == 0:
            return ToolResult(
                tool="search_medlineplus",
                status="insufficient_data",
                data=data,
                limitations=LIMITATIONS + ("No MedlinePlus health topics matched this query.",),
            )

        sources: list[EvidenceSource] = []
        retrieved_at = datetime.now(timezone.utc).isoformat()

        for idx, doc in enumerate(docs, start=1):
            url = (doc.get("url") or "").strip()
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise _ResponseError("invalid document URL")

            fields: dict[str, list[str]] = {}
            for content in doc.findall("content"):
                name = (content.get("name") or "").strip()
                text = _strip_html("".join(content.itertext()))
                if name and text:
                    fields.setdefault(name, []).append(text)

            title = fields.get("title", [""])[0]
            if not title:
                raise _ResponseError("missing topic title")

            summary = (
                fields.get("FullSummary", [""])[0]
                or fields.get("snippet", [""])[0]
            )
            organization = fields.get("organizationName", ["NIH / MedlinePlus"])[0]
            alt_titles = fields.get("altTitle", [])
            mesh_terms = fields.get("mesh", [])

            source_id = f"medlineplus:{idx}:{parsed.path.rstrip('/').split('/')[-1] or idx}"
            topic_record = {
                "source_id": source_id,
                "title": title,
                "url": url,
                "organization": organization,
                "also_called": alt_titles,
                "mesh_headings": mesh_terms,
                "summary": summary or None,
            }
            data["topics"].append(topic_record)
            sources.append(
                EvidenceSource(
                    source_id=source_id,
                    title=title,
                    url=url,
                    publisher=organization,
                    retrieved_at=retrieved_at,
                    excerpt=summary or "",
                    publication_date=None,
                    locator="MedlinePlus Health Topic Summary",
                )
            )

        data["returned_count"] = len(sources)
        return ToolResult(
            tool="search_medlineplus",
            status="ok",
            data=data,
            sources=tuple(sources),
            limitations=LIMITATIONS,
        )
    except HTTPError as exc:
        if exc.code == 429:
            return fail("rate_limited", "MedlinePlus returned HTTP 429 (rate limit); try again later.", True)
        retryable = 500 <= exc.code <= 599
        return fail("http_error", f"MedlinePlus returned HTTP {exc.code}.", retryable)
    except (TimeoutError, socket.timeout):
        return fail("timeout", "MedlinePlus request timed out.", True)
    except (URLError, OSError):
        return fail("network_error", "Could not reach MedlinePlus.", True)
    except (ValueError, TypeError, ET.ParseError, _ResponseError):
        return fail("invalid_response", "MedlinePlus returned an incomplete or invalid response.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search NIH MedlinePlus health topics.")
    parser.add_argument("query", help="Health topic terms only; do not include personal identifiers")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()
    result = search_medlineplus(args.query, args.max_results)
    print(json.dumps(result.to_dict(), indent=2))
    if result.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()

