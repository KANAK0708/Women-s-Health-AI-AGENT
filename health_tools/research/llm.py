"""Groq + Gemini structured-output clients with automatic fallback.

- "fast" (planning, gap refinement, report writing): Groq first, Gemini fallback.
- "long" (reading full documents and extracting facts): Gemini first, Groq fallback.

Models are configurable with GROQ_MODEL / GEMINI_MODEL in .env.
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


QUOTA_COOLDOWN_SECONDS = 300
_cooldown_until: dict[str, float] = {}  # model label -> monotonic time it may be retried


def _is_quota_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".casefold()
    return any(marker in text for marker in ("429", "resource_exhausted", "ratelimit", "rate limit", "quota"))


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
        errors = []
        for model, label, max_chars in self.models:
            if _cooldown_until.get(label, 0) > time.monotonic():
                errors.append(f"{label}: skipped after quota error")
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
                if _is_quota_error(exc):
                    _cooldown_until[label] = time.monotonic() + QUOTA_COOLDOWN_SECONDS
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
        raise ResearchLLMUnavailable("Set GROQ_API_KEY and/or GEMINI_API_KEY in .env to enable research mode.")

    groq_entry = (groq, f"groq:{groq_name}", 12_000)        # free-tier token limits
    gemini_entry = (gemini, f"gemini:{gemini_name}", 40_000)  # long context: whole papers
    fast = LangChainStructuredLLM([groq_entry, gemini_entry])
    long = LangChainStructuredLLM([gemini_entry, groq_entry])
    return fast, long
