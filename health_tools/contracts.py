"""Shared JSON-serializable results. Tools never access user memory directly."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class EvidenceSource:
    """Provenance for retrieved text; inclusion does not imply clinical approval."""

    source_id: str
    title: str
    url: str
    publisher: str
    retrieved_at: str
    excerpt: str
    publication_date: str | None = None
    locator: str | None = None


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: Literal["ok", "insufficient_data", "error"]
    data: dict[str, Any] = field(default_factory=dict)
    sources: tuple[EvidenceSource, ...] = ()
    limitations: tuple[str, ...] = ()
    error: ToolError | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.status not in {"ok", "insufficient_data", "error"}:
            raise ValueError("Invalid tool result status")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("An error result must contain an error; other results must not")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready copy, including nested provenance and errors."""
        result = asdict(self)
        result["sources"] = list(result["sources"])
        result["limitations"] = list(result["limitations"])
        return result
