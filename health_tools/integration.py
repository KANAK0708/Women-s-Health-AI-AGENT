"""Optional integration with the teammate's application after branches combine."""

from pathlib import Path

from .workflow import Orchestrator, ToolPolicy


def create_upstream_orchestrator(*, safety_check, policy: ToolPolicy | None = None,
                                 manifest_path: Path | None = None) -> Orchestrator:
    """Reuse HybridRetrievalEngine; never create a second clinical registry.

    The caller must supply a safety policy returning SafetyDecision, process the
    current message through the memory owner's context tracker as appropriate,
    handle consent/storage, and record clarification turns. No pass-through
    safety default is provided. Clinical adequacy of that policy is not certified.
    """
    # Lazy import keeps the standalone package free of application dependencies.
    from app.retrieval.engine import HybridRetrievalEngine
    from app.schemas.evidence import EducationalCategory

    engine = HybridRetrievalEngine(manifest_path=manifest_path)

    def retrieve(query, **kwargs):
        if "category" in kwargs:
            kwargs["category"] = EducationalCategory(kwargs["category"])
        return engine.retrieve(query, **kwargs)

    return Orchestrator(safety_check=safety_check, retrieve=retrieve, policy=policy)
