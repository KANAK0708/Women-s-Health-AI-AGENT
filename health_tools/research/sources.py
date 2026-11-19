"""Search adapters that turn existing API tools and web search into Documents."""

import re
import threading
import time

from collections.abc import Callable

from health_tools.contracts import ToolResult
from health_tools.europepmc import search_europepmc
from health_tools.medlineplus import search_medlineplus
from health_tools.pubmed import search_pubmed

from .allowlist import is_allowed, source_type_for
from .schema import Document

SearchFn = Callable[[str], list[Document]]

_PUBLICATION_TYPES = (  # checked in order: strongest design first
    ("practice guideline", "guideline"), ("guideline", "guideline"),
    ("systematic review", "systematic_review"), ("systematic-review", "systematic_review"),
    ("meta-analysis", "systematic_review"),
    ("randomized controlled trial", "rct"),
    ("review", "narrative_review"),
)
_RETRACTION_NOTICES = {"RetractionIn", "ExpressionOfConcernIn"}
_RETRACTION_TYPES = {"retracted publication", "retraction of publication", "expression of concern"}


def classify_publication_types(publication_types: list[str], title: str = "") -> str:
    """Map PubMed / Europe PMC publication types (falling back to the title) to a source type."""
    lowered = [item.casefold() for item in publication_types or []]
    for needle, kind in _PUBLICATION_TYPES:
        if any(needle in item for item in lowered):
            return kind
    title = title.casefold()
    if "systematic review" in title or "meta-analysis" in title:
        return "systematic_review"
    if "guideline" in title:
        return "guideline"
    return "research_article"


def _retracted(publication_types: list[str]) -> bool:
    return any(t.casefold() in _RETRACTION_TYPES for t in publication_types or [])


_PMC_URL = re.compile(r"^https://(?:pmc\.ncbi\.nlm\.nih\.gov|www\.ncbi\.nlm\.nih\.gov/pmc)/articles/(PMC\d+)")
_PUBMED_URL = re.compile(r"^https://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
_EUROPEPMC_URL = re.compile(r"^https://europepmc\.org/(?:abstract|article)/(MED|PMC)/(PMC\d+|\d+)", re.I)


def lookup_study_type(url: str, *, search=search_europepmc) -> tuple[str | None, bool]:
    """For a paper URL (PMC, PubMed, Europe PMC) return (source_type, retracted).

    Returns (None, False) for other URLs or when the lookup fails, so callers keep
    their domain-based type.
    """
    query = None
    if match := _PMC_URL.match(url):
        query = f"PMCID:{match.group(1)}"
    elif match := _PUBMED_URL.match(url):
        query = f"EXT_ID:{match.group(1)} AND SRC:MED"
    elif match := _EUROPEPMC_URL.match(url):
        source, ident = match.group(1).upper(), match.group(2).upper()
        query = f"PMCID:{ident}" if source == "PMC" else f"EXT_ID:{ident} AND SRC:MED"
    if query is None:
        return None, False
    for _ in range(2):  # Europe PMC times out intermittently; one retry.
        result = search(query, max_results=1, timeout=20)
        if _ok(result) and result.data.get("articles"):
            article = result.data["articles"][0]
            types = article.get("publication_types", [])
            return classify_publication_types(types, article.get("title", "")), _retracted(types)
        if not (result.error and result.error.retryable):
            break
    return None, False


def _ok(result: ToolResult) -> bool:
    return isinstance(result, ToolResult) and result.status == "ok"


class SearchError(Exception):
    """A search API failed; the message is shown in the run log."""


_PUBMED_LOCK = threading.Lock()
_WEB_LOCK = threading.Lock()  # NCBI allows ~3 requests/second without an API key


def _call(search, terms: str, max_results: int, *, lock=None, timeout: float = 10) -> ToolResult | None:
    """Run a search, retrying once on retryable errors. Returns None when nothing matched;
    raises SearchError when the service failed, so the failure is logged, not hidden."""
    for attempt in range(2):
        if lock is not None:
            with lock:
                result = search(terms, max_results=max_results, timeout=timeout)
                time.sleep(0.4)
        else:
            result = search(terms, max_results=max_results, timeout=timeout)
        if _ok(result):
            return result
        if result.status == "insufficient_data":
            return None
        if not (result.error and result.error.retryable) or attempt:
            raise SearchError(f"{result.error.code}: {result.error.message}" if result.error else "search failed")
        time.sleep(1.5)


def pubmed_documents(terms: str, *, search=search_pubmed, max_results: int = 3) -> list[Document]:
    result = _call(search, terms, max_results, lock=_PUBMED_LOCK)
    if result is None:
        return []
    articles = {a["source_id"]: a for a in result.data.get("articles", [])}
    docs = []
    for src in result.sources:
        article = articles.get(src.source_id, {})
        if any(n.get("type") in _RETRACTION_NOTICES for n in article.get("related_notices", [])):
            continue  # Never cite retracted papers or ones under an expression of concern.
        if not src.excerpt:
            continue
        docs.append(Document(
            doc_id=src.source_id, url=src.url, title=src.title, publisher=src.publisher,
            source_type=classify_publication_types(article.get("publication_types", []), src.title),
            text=src.excerpt, published=src.publication_date, retrieved_at=src.retrieved_at,
            locator="PubMed abstract",
        ))
    return docs


def europepmc_documents(terms: str, *, search=search_europepmc, max_results: int = 3) -> list[Document]:
    result = _call(search, terms, max_results, timeout=20)  # Europe PMC is often slow
    if result is None:
        return []
    articles = {a["source_id"]: a for a in result.data.get("articles", [])}
    docs = []
    for src in result.sources:
        article = articles.get(src.source_id, {})
        pmcid = article.get("pmcid") if article.get("is_open_access") else None
        types = article.get("publication_types", [])
        if (not src.excerpt and not pmcid) or _retracted(types):
            continue
        kind = classify_publication_types(types, src.title)
        docs.append(Document(
            doc_id=src.source_id, url=src.url, title=src.title, publisher=src.publisher,
            source_type=kind, text=src.excerpt, published=src.publication_date,
            retrieved_at=src.retrieved_at, locator="Europe PMC abstract", pmcid=pmcid,
        ))
    return docs


def medlineplus_documents(terms: str, *, search=search_medlineplus, max_results: int = 2) -> list[Document]:
    result = _call(search, terms, max_results)
    if result is None:
        return []
    return [
        Document(doc_id=src.source_id, url=src.url, title=src.title, publisher=src.publisher,
                 source_type="consumer_health", text=src.excerpt, retrieved_at=src.retrieved_at,
                 locator="MedlinePlus health topic summary")
        for src in result.sources if src.excerpt
    ]


def web_documents(terms: str, *, max_results: int = 25, keep: int = 4) -> list[Document]:
    """DuckDuckGo search; only allowlisted HTTPS links are kept (as links to read later)."""
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    hits, last_error = None, None
    # Try the topic-anchored query first, then the plain terms. "No results found" is an
    # empty result, not a failure; other errors get one spaced-out retry.
    attempts = [f"{terms} women's health", terms, terms]
    for attempt, query in enumerate(attempts):
        with _WEB_LOCK:  # one search at a time: parallel queries trigger rate limits
            try:
                hits = DDGS(timeout=15).text(query, max_results=max_results) or []
                last_error = None
            except Exception as exc:
                hits, last_error = None, exc
            time.sleep(1.0)
        if hits:
            break
        if last_error is not None and "no results" not in str(last_error).casefold() and attempt < 2:
            time.sleep(2.0)
    if hits is None and last_error is not None and "no results" not in str(last_error).casefold():
        raise SearchError(f"web search failed after retry: {type(last_error).__name__}: {str(last_error)[:80]}")
    hits = hits or []
    docs, seen = [], set()
    for hit in hits:
        url = (hit.get("href") or hit.get("url") or "").split("#")[0]
        if not url or url in seen or not is_allowed(url):
            continue
        seen.add(url)
        if pmc := _PMC_URL.match(url):
            # PMC blocks automated page reads; fetch the same paper's full text from Europe PMC.
            docs.append(Document(
                doc_id=f"web:{len(docs)}", url=url, title=hit.get("title") or url, publisher="PMC",
                source_type="research_article", text="", locator="Europe PMC open-access full text",
                pmcid=pmc.group(1),
            ))
            if len(docs) >= keep:
                break
            continue
        docs.append(Document(
            doc_id=f"web:{len(docs)}", url=url, title=hit.get("title") or url,
            publisher=url.split("/")[2], source_type=source_type_for(url),
            text=hit.get("body") or "", locator="Web page text", needs_fetch=True,
        ))
        if len(docs) >= keep:
            break
    return docs


DEFAULT_SEARCHES: dict[str, SearchFn] = {
    "pubmed": pubmed_documents,
    "europepmc": europepmc_documents,
    "medlineplus": medlineplus_documents,
    "web": web_documents,
}
