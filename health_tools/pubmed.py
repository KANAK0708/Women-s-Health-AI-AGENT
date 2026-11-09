"""Bounded PubMed research retrieval via NCBI ESearch and EFetch.

No LLM, memory, persistence, or third-party Python dependencies are used.
"""

import argparse
import json
import math
import os
import socket
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .contracts import EvidenceSource, ToolError, ToolResult


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
MAX_RESPONSE_BYTES = 2_000_000
LIMITATIONS = (
    "PubMed results are research records, not approved clinical recommendations or personalized medical advice.",
    "Abstracts may be missing or incomplete; full text has not been retrieved or reviewed.",
    "Search ranking does not establish study quality, consensus, or applicability.",
)
_request_lock = threading.Lock()
_last_request = 0.0


class _ResponseError(Exception):
    pass


def _request(endpoint: str, params: dict[str, str], timeout: float) -> bytes:
    """Fixed-host POST, bounded read, and process-local pacing below 3 req/sec."""
    global _last_request
    request = Request(
        BASE_URL + endpoint,
        data=urlencode(params).encode("utf-8"),
        headers={
            "User-Agent": "WomenHealthResearchTools/0.1",
            "Content-Type": "application/x-www-form-urlencoded",
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


def _text(element: ET.Element | None) -> str:
    return "" if element is None else " ".join("".join(element.itertext()).split())


def search_pubmed(query: str, max_results: int = 3, *, timeout: float = 10) -> ToolResult:
    """Search a non-identifying research query and return up to five abstracts.

    Sends the query to NCBI. Caller must remove personal health identifiers and
    obtain any required permission before invocation. Optional NCBI_API_KEY and
    NCBI_EMAIL are read from the environment, never returned in results/errors.
    Two requests maximum, no automatic retries. Timeout applies per request.
    """
    def fail(code: str, message: str, retryable: bool = False) -> ToolResult:
        return ToolResult(
            tool="search_pubmed", status="error", limitations=LIMITATIONS,
            error=ToolError(code, message, retryable),
        )

    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return fail("invalid_query", "Supply a nonempty research query of at most 500 characters.")
    if type(max_results) is not int or not 1 <= max_results <= 5:
        return fail("invalid_limit", "max_results must be an integer from 1 to 5.")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        return fail("invalid_timeout", "timeout must be a finite number above 0 and at most 30 seconds.")

    common = {"db": "pubmed", "tool": "women_health_research_tools"}
    for env_name, param in (("NCBI_API_KEY", "api_key"), ("NCBI_EMAIL", "email")):
        value = os.environ.get(env_name)
        if value:
            common[param] = value
    stage = "search"
    try:
        raw = _request("esearch.fcgi", {
            **common, "term": query.strip(), "retmode": "json",
            "retmax": str(max_results), "sort": "relevance",
        }, timeout)
        search = json.loads(raw)
        if not isinstance(search, dict) or search.get("error"):
            raise _ResponseError("search error")
        found = search.get("esearchresult")
        if not isinstance(found, dict) or found.get("errorlist"):
            raise _ResponseError("invalid search result")
        ids = found.get("idlist")
        count = found.get("count")
        if not isinstance(ids, list) or len(ids) > max_results or any(
            not isinstance(pmid, str) or not pmid.isascii() or not pmid.isdigit() for pmid in ids
        ) or len(set(ids)) != len(ids):
            raise _ResponseError("invalid IDs")
        if not isinstance(count, (str, int)) or isinstance(count, bool) or not str(count).isascii() or not str(count).isdigit():
            raise _ResponseError("invalid count")
        total = int(count)
        if total < len(ids) or (total > 0 and not ids):
            raise _ResponseError("inconsistent count")
        data = {"total_matches": total, "returned_count": 0, "articles": []}
        if not ids:
            return ToolResult(tool="search_pubmed", status="insufficient_data", data=data,
                              limitations=LIMITATIONS + ("No records matched this query.",))

        stage = "abstract retrieval"
        raw = _request("efetch.fcgi", {
            **common, "id": ",".join(ids), "retmode": "xml", "rettype": "abstract",
        }, timeout)
        root = ET.fromstring(raw)
        if root.tag != "PubmedArticleSet" or root.find(".//ERROR") is not None:
            raise _ResponseError("invalid article response")
        records = {}
        for node in root.findall("PubmedArticle"):
            pmid = _text(node.find("MedlineCitation/PMID"))
            if pmid not in ids or pmid in records:
                raise _ResponseError("unexpected article ID")
            records[pmid] = node
        # Book records require a separate parser; never silently claim full retrieval.
        if set(records) != set(ids):
            raise _ResponseError("missing or unsupported records")

        sources = []
        retrieved_at = datetime.now(timezone.utc).isoformat()
        for pmid in ids:
            node = records[pmid]
            article = node.find("MedlineCitation/Article")
            if article is None:
                raise _ResponseError("missing article")
            title = _text(article.find("ArticleTitle"))
            if not title:
                raise _ResponseError("missing title")
            sections = []
            for section in article.findall("Abstract/AbstractText"):
                text = _text(section)
                label = section.get("Label")
                if text:
                    sections.append(f"{label}: {text}" if label else text)
            abstract = "\n".join(sections) or None
            pubdate = article.find("Journal/JournalIssue/PubDate")
            publication_date = _text(pubdate) or None
            if pubdate is not None and pubdate.find("Year") is not None:
                publication_date = " ".join(filter(None, (
                    _text(pubdate.find("Year")), _text(pubdate.find("Month")),
                    _text(pubdate.find("Day")),
                )))
            source_id = f"pubmed:{pmid}"
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            notices = [
                {"type": item.get("RefType"), "pmid": _text(item.find("PMID")) or None}
                for item in node.findall("MedlineCitation/CommentsCorrectionsList/CommentsCorrections")
            ]
            record = {
                "pmid": pmid, "source_id": source_id, "title": title, "url": url,
                "journal": _text(article.find("Journal/Title")) or None,
                "publication_date": publication_date,
                "publication_types": [_text(item) for item in article.findall("PublicationTypeList/PublicationType")],
                "abstract": abstract, "abstract_available": abstract is not None,
                "evidence_kind": "research_abstract" if abstract else "citation_only",
                "related_notices": notices,
            }
            data["articles"].append(record)
            sources.append(EvidenceSource(
                source_id=source_id, title=title, url=url, publisher="NCBI / PubMed",
                retrieved_at=retrieved_at, excerpt=abstract or "",
                publication_date=publication_date,
                locator="Abstract" if abstract else "Citation metadata only",
            ))
        data["returned_count"] = len(sources)
        return ToolResult(tool="search_pubmed", status="ok", data=data,
                          sources=tuple(sources), limitations=LIMITATIONS)
    except HTTPError as exc:
        if exc.code == 429:
            return fail("rate_limited", f"NCBI {stage} returned HTTP 429 (rate limit); try again later.", True)
        retryable = 500 <= exc.code <= 599
        hint = " Try again later." if retryable else " Check API access and request settings."
        return fail("http_error", f"NCBI {stage} returned HTTP {exc.code}.{hint}", retryable)
    except (TimeoutError, socket.timeout):
        return fail("timeout", "NCBI request timed out.", True)
    except (URLError, OSError):
        return fail("network_error", "Could not reach NCBI.", True)
    except (ValueError, TypeError, ET.ParseError, _ResponseError):
        return fail("invalid_response", "NCBI returned an incomplete, unsupported, or invalid response.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search PubMed; sends your research query to NCBI.")
    parser.add_argument("query", help="Research terms only; do not include personal identifiers")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()
    result = search_pubmed(args.query, args.max_results)
    print(json.dumps(result.to_dict(), indent=2))
    if result.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()
