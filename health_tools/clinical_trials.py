"""Bounded ClinicalTrials.gov study retrieval via ClinicalTrials.gov REST API v2.

No LLM, memory, persistence, or third-party Python dependencies are used.
Searches registered clinical trials on women's health conditions.
"""

import argparse
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


BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
MAX_RESPONSE_BYTES = 2_000_000
LIMITATIONS = (
    "ClinicalTrials.gov records describe research protocols and are not clinical treatment recommendations.",
    "Listing a study on ClinicalTrials.gov does not mean it has been evaluated or endorsed by the U.S. federal government.",
    "Discuss clinical trial eligibility and risks with a qualified healthcare professional.",
)
_request_lock = threading.Lock()
_last_request = 0.0
_NCT_RE = re.compile(r"^NCT[0-9]{8}$")


class _ResponseError(Exception):
    pass


def _clean(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


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


def search_clinical_trials(query: str, max_results: int = 3, *, timeout: float = 10) -> ToolResult:
    """Search ClinicalTrials.gov API v2 for registered clinical studies (up to 5 results).

    Sends the query to ClinicalTrials.gov. Caller must remove personal health
    identifiers and obtain any required permission before invocation.
    """
    def fail(code: str, message: str, retryable: bool = False) -> ToolResult:
        return ToolResult(
            tool="search_clinical_trials",
            status="error",
            limitations=LIMITATIONS,
            error=ToolError(code, message, retryable),
        )

    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return fail("invalid_query", "Supply a nonempty clinical trial query of at most 500 characters.")
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
                "query.term": query.strip(),
                "pageSize": str(max_results),
                "countTotal": "true",
                "format": "json",
            },
            timeout,
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise _ResponseError("invalid payload")

        studies = payload.get("studies", [])
        if not isinstance(studies, list):
            raise _ResponseError("invalid studies list")
        studies = studies[:max_results]
        total = payload.get("totalCount", len(studies))
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise _ResponseError("invalid totalCount")

        data: dict = {"total_matches": total, "returned_count": 0, "studies": []}
        if not studies:
            return ToolResult(
                tool="search_clinical_trials",
                status="insufficient_data",
                data=data,
                limitations=LIMITATIONS + ("No registered clinical trials matched this query.",),
            )

        sources: list[EvidenceSource] = []
        retrieved_at = datetime.now(timezone.utc).isoformat()

        for study in studies:
            if not isinstance(study, dict):
                raise _ResponseError("invalid study entry")
            protocol = study.get("protocolSection")
            if not isinstance(protocol, dict):
                raise _ResponseError("missing protocolSection")

            ident = protocol.get("identificationModule") or {}
            status_mod = protocol.get("statusModule") or {}
            desc_mod = protocol.get("descriptionModule") or {}
            cond_mod = protocol.get("conditionsModule") or {}
            design_mod = protocol.get("designModule") or {}

            nct_id = _clean(ident.get("nctId"))
            if not _NCT_RE.fullmatch(nct_id):
                raise _ResponseError("invalid NCT ID")

            title = _clean(ident.get("officialTitle") or ident.get("briefTitle"))
            if not title:
                raise _ResponseError("missing study title")

            overall_status = _clean(status_mod.get("overallStatus")) or "UNKNOWN"
            last_update = _clean((status_mod.get("lastUpdatePostDateStruct") or {}).get("date")) or None
            brief_summary = _clean(desc_mod.get("briefSummary")) or None
            conditions = [
                _clean(c) for c in (cond_mod.get("conditions") or []) if _clean(c)
            ]
            phases = [
                _clean(p) for p in (design_mod.get("phases") or []) if _clean(p)
            ]

            source_id = f"clinicaltrials:{nct_id}"
            url = f"https://clinicaltrials.gov/study/{nct_id}"

            study_record = {
                "nct_id": nct_id,
                "source_id": source_id,
                "title": title,
                "url": url,
                "overall_status": overall_status,
                "conditions": conditions,
                "phases": phases,
                "last_update_date": last_update,
                "brief_summary": brief_summary,
            }
            data["studies"].append(study_record)
            sources.append(
                EvidenceSource(
                    source_id=source_id,
                    title=f"{title} [{overall_status}]",
                    url=url,
                    publisher="NIH / ClinicalTrials.gov",
                    retrieved_at=retrieved_at,
                    excerpt=brief_summary or "",
                    publication_date=last_update,
                    locator=f"NCT ID: {nct_id} ({overall_status})",
                )
            )

        data["returned_count"] = len(sources)
        return ToolResult(
            tool="search_clinical_trials",
            status="ok",
            data=data,
            sources=tuple(sources),
            limitations=LIMITATIONS,
        )
    except HTTPError as exc:
        if exc.code == 429:
            return fail("rate_limited", "ClinicalTrials.gov returned HTTP 429 (rate limit); try again later.", True)
        retryable = 500 <= exc.code <= 599
        return fail("http_error", f"ClinicalTrials.gov returned HTTP {exc.code}.", retryable)
    except (TimeoutError, socket.timeout):
        return fail("timeout", "ClinicalTrials.gov request timed out.", True)
    except (URLError, OSError):
        return fail("network_error", "Could not reach ClinicalTrials.gov.", True)
    except (ValueError, TypeError, _ResponseError):
        return fail("invalid_response", "ClinicalTrials.gov returned an incomplete or invalid response.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search ClinicalTrials.gov studies.")
    parser.add_argument("query", help="Study condition/terms only; do not include personal identifiers")
    parser.add_argument("--max-results", type=int, default=3)
    args = parser.parse_args()
    result = search_clinical_trials(args.query, args.max_results)
    print(json.dumps(result.to_dict(), indent=2))
    if result.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()

