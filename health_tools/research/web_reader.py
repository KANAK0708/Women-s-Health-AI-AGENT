"""Polite, allowlist-only page reader that returns exact page text.

- HTTPS on allowlisted domains only, checked again after every redirect.
- Honors robots.txt, rate-limits per host, caps response size, caches pages.
- Extracts readable text with the standard library (no LLM rewriting), so
  quotes can be checked verbatim against what the page actually says.
"""

import re
import threading
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from dataclasses import asdict

from . import cache
from .allowlist import host_of, is_allowed, source_type_for
from .schema import Document

USER_AGENT = "WomensHealthResearchAgent/0.1 (educational research; respects robots.txt)"
MAX_BYTES = 3_000_000
MAX_PDF_BYTES = 20_000_000
MAX_PDF_PAGES = 60
MAX_TEXT_CHARS = 60_000
MIN_HOST_INTERVAL = 1.0
EUROPEPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


class ReaderError(Exception):
    """A page could not be read; the message is safe to show."""


class _AllowlistRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed(newurl):
            raise ReaderError("Redirect left the allowed domains.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_AllowlistRedirects)
_lock = threading.Lock()
_last_hit: dict[str, float] = {}
_robots: dict[str, RobotFileParser | None] = {}
_cache: dict[str, Document] = {}


def _throttle(host: str) -> None:
    with _lock:
        wait = _last_hit.get(host, 0) + MIN_HOST_INTERVAL - time.monotonic()
        _last_hit[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def _get(url: str, timeout: float) -> tuple[bytes, str]:
    _throttle(host_of(url))
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,text/plain;q=0.8"})
    try:
        with _opener.open(request, timeout=timeout) as response:
            if not is_allowed(response.geturl()):
                raise ReaderError("Final URL is outside the allowed domains.")
            content_type = response.headers.get("Content-Type", "")
            limit = MAX_PDF_BYTES if "pdf" in content_type.lower() else MAX_BYTES
            body = response.read(limit + 1)
    except HTTPError as exc:
        raise ReaderError(f"HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ReaderError("Network error or timeout") from exc
    if len(body) > (MAX_PDF_BYTES if "pdf" in content_type.lower() else MAX_BYTES):
        raise ReaderError("Page too large.")
    return body, content_type


def robots_allows(url: str, timeout: float = 8) -> bool:
    host = host_of(url)
    if host not in _robots:
        parser = RobotFileParser()
        try:
            body, _ = _get(f"https://{host}/robots.txt", timeout)
            parser.parse(body.decode("utf-8", "replace").splitlines())
            _robots[host] = parser
        except ReaderError:
            _robots[host] = None  # No readable robots.txt: treat as allowed.
    parser = _robots[host]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "button", "iframe", "template"}
_BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "br", "tr", "table",
          "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "dd", "dt", "figcaption"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.main_depth = 0
        self.in_title = False
        self.title = ""
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip_depth += 1
        elif tag in ("main", "article"):
            self.main_depth += 1
        elif tag == "title":
            self.in_title = True
        if tag in _BLOCK:
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in ("main", "article") and self.main_depth:
            self.main_depth -= 1
        elif tag == "title":
            self.in_title = False
        if tag in _BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip_depth:
            self._emit(data)

    def _emit(self, text):
        self.all_parts.append(text)
        if self.main_depth:
            self.main_parts.append(text)


def _tidy(text: str) -> str:
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)[:MAX_TEXT_CHARS]


def extract_text(html: str) -> tuple[str, str]:
    """Return (title, readable text), preferring <main>/<article> when substantial."""
    parser = _TextExtractor()
    parser.feed(html)
    main = _tidy("".join(parser.main_parts))
    body = _tidy("".join(parser.all_parts))
    return " ".join(parser.title.split()), main if len(main) >= 500 else body


def extract_pdf_text(body: bytes) -> tuple[str, str, int]:
    """Return (title, text, pages read) from a PDF; many guidelines are only published as PDFs."""
    try:
        import logging
        from io import BytesIO

        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed-PDF chatter; failures raise below
    except ImportError:
        raise ReaderError("PDF support needs the pypdf package.") from None
    try:
        reader = PdfReader(BytesIO(body))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ReaderError("PDF is encrypted.")
        pages = reader.pages[:MAX_PDF_PAGES]
        raw = "\n".join(page.extract_text() or "" for page in pages)
        title = ((reader.metadata or {}).get("/Title") or "").strip() if reader.metadata else ""
    except ReaderError:
        raise
    except Exception:
        raise ReaderError("PDF could not be read.") from None
    raw = re.sub(r"(\w)-\n(\w)", r"\1\2", raw)  # re-join words hyphenated across line breaks
    text = _tidy(raw)
    if not title:
        title = next((line for line in text.splitlines() if len(line) > 10), "")[:200]
    return title, text, len(pages)


def fetch_page(url: str, *, timeout: float = 10, doc_id: str | None = None) -> Document:
    """Read one allowlisted page and return its exact text."""
    if not is_allowed(url):
        raise ReaderError("URL is outside the allowed domains.")
    if url in _cache:
        return _cache[url]
    key = cache.make_key("page", url)
    if (hit := cache.get("pages", key, cache.PAGE_TTL)) is not None:
        doc = Document(**hit)
        if doc_id:
            doc.doc_id = doc_id
        _cache[url] = doc
        return doc
    if not robots_allows(url):
        raise ReaderError("robots.txt disallows this page.")
    body, content_type = _get(url, timeout)
    is_pdf = "pdf" in content_type.lower() or body[:5] == b"%PDF-"
    if is_pdf:
        title, text, pages = extract_pdf_text(body)
        locator = f"PDF text, pages 1-{pages}"
    elif content_type and not re.search(r"html|xml|text/plain", content_type, re.I):
        raise ReaderError("Unsupported content type.")
    else:
        title, text = extract_text(body.decode("utf-8", "replace"))
        locator = "Web page text"
    if len(text) < 200:
        raise ReaderError("Page had too little readable text.")
    doc = Document(
        doc_id=doc_id or f"web:{host_of(url)}", url=url, title=title or url,
        publisher=host_of(url), source_type=source_type_for(url), text=text,
        locator=locator,
    )
    _cache[url] = doc
    cache.put("pages", key, asdict(doc))
    return doc


def fetch_europepmc_fulltext(pmcid: str, *, timeout: float = 30) -> str:
    """Return open-access full text for a PMC ID (body sections), or raise ReaderError."""
    if not re.fullmatch(r"PMC\d{1,10}", pmcid or ""):
        raise ReaderError("Invalid PMCID.")
    key = cache.make_key("fulltext", pmcid)
    if (hit := cache.get("fulltext", key, cache.PAGE_TTL)) is not None:
        return hit
    body, _ = _get(EUROPEPMC_FULLTEXT.format(pmcid=pmcid), timeout)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise ReaderError("Full text was not valid XML.") from None
    parts = []
    for section in root.iter("sec"):
        title = section.find("title")
        if title is not None and "".join(title.itertext()).strip():
            parts.append("\n" + " ".join("".join(title.itertext()).split()))
        for para in section.findall("p"):
            parts.append(" ".join("".join(para.itertext()).split()))
    text = _tidy("\n".join(parts))
    if len(text) < 500:
        raise ReaderError("No usable full text.")
    cache.put("fulltext", key, text)
    return text
