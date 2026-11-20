"""Groq + Gemini structured-output clients with automatic fallback.

- "fast" (planning, gap refinement, report writing): Groq first, Gemini fallback.
- "long" (reading full documents and extracting facts): Gemini first, Groq fallback.

Models are configurable with GROQ_MODEL / GEMINI_MODEL in .env.
RESEARCH_PROVIDERS=groq (or gemini) runs with one provider only, for example when the
other is down or for a single-provider baseline, without editing .env.
"""

import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"


class ResearchLLMUnavailable(RuntimeError):
    pass


class StructuredLLM(Protocol):
    name: str
    max_input_chars: int

    def ask(self, schema: type[T], system: str, user: str) -> T: ...


QUOTA_COOLDOWN_SECONDS = 60          # free-tier limits are mostly per minute
DAILY_QUOTA_COOLDOWN_SECONDS = 3600  # a per-day limit won't reset in a minute; stop retrying for an hour
OUTAGE_COOLDOWN_SECONDS = 120        # 503/504/timeouts: skip the model briefly instead of waiting on it every call
MAX_QUOTA_WAIT_SECONDS = 90  # wait at most this long when every model is cooling down
_cooldown_until: dict[str, float] = {}  # model label -> monotonic time it may be retried

PROVIDERS = ("groq", "gemini")


def _is_quota_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".casefold()
    return any(marker in text for marker in ("429", "resource_exhausted", "ratelimit", "rate limit", "quota"))


def _is_outage(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".casefold()
    return isinstance(exc, TimeoutError) or any(marker in text for marker in (
        "503", "504", "500 internal", "unavailable", "overloaded", "deadline", "timed out", "timeout"))


def _cooldown_seconds(exc: Exception) -> float | None:
    """How long to skip a model after this error; None for errors unrelated to capacity."""
    if _is_quota_error(exc):
        text = str(exc).casefold()
        return DAILY_QUOTA_COOLDOWN_SECONDS if ("perday" in text or "per day" in text or "daily" in text) else QUOTA_COOLDOWN_SECONDS
    if _is_outage(exc):
        return OUTAGE_COOLDOWN_SECONDS
    return None


def _fit(user: str, max_chars: int) -> str:
    """Trim the message to a model's input budget, keeping the document wrapper closed."""
    if len(user) <= max_chars:
        return user
    cut = user[: max_chars - 40]
    return cut + "\n[...truncated]\n</document>" if "<document>" in cut else cut


class LangChainStructuredLLM:
    """Tries each chat model in order with structured output.

    Each model gets input sized to its own limit, so a Groq fallback is never sent a
    40k-character document meant for Gemini. A model that hits a quota/rate limit is
    skipped for QUOTA_COOLDOWN_SECONDS instead of failing every following call.
    """

    def __init__(self, models: list[tuple[object, str, int]]):
        self.models = [m for m in models if m[0] is not None]
        if not self.models:
            raise ResearchLLMUnavailable("No language model configured.")
        self.name = " -> ".join(label for _, label, _ in self.models)
        self.max_input_chars = self.models[0][2]

    def ask(self, schema, system, user):
        import time

        from . import cache
        key = cache.make_key(self.name, schema.__name__, schema.model_json_schema(), system, user)
        if (hit := cache.get("llm", key, cache.LLM_TTL)) is not None:
            try:
                return schema.model_validate(hit)
            except ValueError:
                pass  # Schema changed shape; ask again.
        result = self._ask_models(schema, system, user)
        cache.put("llm", key, result.model_dump(mode="json"))
        return result

    def _ask_models(self, schema, system, user):
        import time

        # If every model is cooling down after a rate limit, wait for the first one to
        # come back instead of failing at once (limits reset within about a minute).
        soonest = min(_cooldown_until.get(label, 0) for _, label, _ in self.models)
        wait = soonest - time.monotonic()
        if 0 < wait <= MAX_QUOTA_WAIT_SECONDS:
            time.sleep(wait)
        errors = []
        for model, label, max_chars in self.models:
            if _cooldown_until.get(label, 0) > time.monotonic():
                errors.append(f"{label}: skipped while cooling down after a quota or outage error")
                continue
            try:
                result = model.with_structured_output(schema).invoke(
                    [("system", system), ("human", _fit(user, max_chars))])
                if isinstance(result, dict):
                    result = schema.model_validate(result)
                if not isinstance(result, schema):
                    raise ValueError("no structured output")
                return result
            except Exception as exc:
                if (cooldown := _cooldown_seconds(exc)) is not None:
                    _cooldown_until[label] = time.monotonic() + cooldown
                errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:120]}")
        raise RuntimeError(" | ".join(errors))


def build_llms() -> tuple[StructuredLLM, StructuredLLM]:
    """Return (fast, long) clients. Needs GROQ_API_KEY and/or GEMINI_API_KEY."""
    try:
        from pathlib import Path

        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    groq_key = "" if groq_key.startswith("your_") else groq_key
    gemini_key = "" if gemini_key.startswith("your_") else gemini_key
    providers = _selected_providers()
    groq_key = groq_key if "groq" in providers else ""
    gemini_key = gemini_key if "gemini" in providers else ""
    groq = gemini = None
    groq_name = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    gemini_name = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    if groq_key:
        from langchain_groq import ChatGroq
        groq = ChatGroq(model=groq_name, api_key=groq_key, temperature=0, max_retries=2, timeout=60)
    if gemini_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        gemini = ChatGoogleGenerativeAI(model=gemini_name, google_api_key=gemini_key, temperature=0, max_retries=1, timeout=60)
    if groq is None and gemini is None:
        raise ResearchLLMUnavailable("Set GROQ_API_KEY and/or GEMINI_API_KEY in .env to enable research mode"
                                     f" (RESEARCH_PROVIDERS allows: {', '.join(providers) or 'none'}).")

    groq_entry = (groq, f"groq:{groq_name}", 12_000)        # free-tier token limits
    gemini_entry = (gemini, f"gemini:{gemini_name}", 40_000)  # long context: whole papers
    fast = LangChainStructuredLLM([groq_entry, gemini_entry])
    long = LangChainStructuredLLM([gemini_entry, groq_entry])
    return fast, long


def _selected_providers() -> tuple[str, ...]:
    raw = os.environ.get("RESEARCH_PROVIDERS", "").strip().casefold()
    if not raw:
        return PROVIDERS
    return tuple(p for p in (part.strip() for part in raw.split(",")) if p in PROVIDERS)


def check_providers(timeout: float = 30) -> list[tuple[str, bool, float, str]]:
    """Send one tiny structured request to each configured provider: (label, ok, seconds, note).

    Uses a synthetic prompt (no medical or personal text), no retries, and never reports key values.
    """
    import time

    class Ready(BaseModel):
        ready: bool

    fast, long = build_llms()
    results, seen = [], set()
    for model, label, _ in fast.models + long.models:
        if label in seen:
            continue
        seen.add(label)
        for attr in ("max_retries", "timeout"):
            if hasattr(model, attr):
                try:
                    setattr(model, attr, 0 if attr == "max_retries" else timeout)
                except (AttributeError, ValueError, TypeError):
                    pass
        start = time.monotonic()
        try:
            model.with_structured_output(Ready).invoke("Reply with ready=true.")
            results.append((label, True, time.monotonic() - start, "ok"))
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            kind = "quota" if _is_quota_error(exc) else "outage" if _is_outage(exc) else "error"
            results.append((label, False, time.monotonic() - start, f"{kind}: {type(exc).__name__}"))
    return results
