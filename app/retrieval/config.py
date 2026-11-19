"""One approval policy for local, PostgreSQL, and application entry points."""

import os


def development_evidence_enabled(value: bool | None = None) -> bool:
    if value is not None:
        if type(value) is not bool:
            raise ValueError("Development evidence setting must be a boolean")
        return value
    return os.getenv("ALLOW_UNVERIFIED_EVIDENCE", "false").strip().lower() in {"true", "1", "yes"}
