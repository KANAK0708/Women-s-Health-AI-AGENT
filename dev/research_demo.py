"""Synthetic report fixtures for WEB_UI_DEMO=1. No API calls or real evidence."""

from health_tools.research.schema import Conflict, Finding, ResearchReport, Source, SubAnswer

STATUSES = {"complete", "partial", "urgent", "blocked", "out_of_scope", "no_evidence", "error"}
DEMO_DISCLAIMER = (
    "Synthetic display fixture, not medical evidence. Educational research summaries "
    "are not a diagnosis or treatment plan; discuss your situation with a qualified clinician."
)


def demo_report(status: str = "complete") -> ResearchReport:
    if status not in STATUSES:
        raise ValueError("Unknown demo status")
    report = ResearchReport(
        question="Synthetic demo: how are research findings presented?", status=status,
        summary="The first fixture describes a possible benefit [F1]. "
                "The second fixture describes uncertainty [F2][F3].",
        generated_at="2026-11-19T12:00:00+05:30", disclaimer=DEMO_DISCLAIMER,
        rejected_findings=2, rejection_reasons={"quote not found in source": 1, "duplicate": 1},
        redactions=["email", "first-person age"],
        models={"plan_and_report": "synthetic / no model called", "extraction": "synthetic / no model called"},
        search_log=["DEMO ONLY: no searches, external calls or verification were performed.",
                    "Synthetic query: " + "long-search-term-" * 24],
    )
    for number, kind in enumerate(("guideline", "rct", "research_article"), 1):
        source_id, finding_id = f"demo:{number}", f"F{number}"
        # The third fixture deliberately tests rejection of executable link schemes.
        url = (f"https://example.org/synthetic-source-{number}" if number != 3
               else "javascript:window.demoUrlRan = true")
        claim = ("The first fixture describes a possible benefit." if number == 1
                 else "This fixture describes uncertainty.")
        quote = ("Synthetic quote: <script>window.demoScriptRan = true</script> "
                 '<img src=x onerror="window.demoImageRan = true"> & literal HTML.' if number == 1
                 else "Synthetic quote: the evidence is uncertain and may not apply to every population.")
        report.sources.append(Source(
            source_id=source_id, title=f"Synthetic source {number} — not medical evidence",
            url=url, publisher="Example publisher (fixture)", source_type=kind,
            published="2024", retrieved_at=report.generated_at, sha256="0" * 64,
        ))
        report.key_findings.append(Finding(
            id=finding_id, sub_question="What does this fixture show?", claim=claim,
            quote=quote, source_id=source_id, source_url=url, source_type=kind,
            published="2024", support_score=1.0,
        ))
    report.sub_answers = [SubAnswer(
        question="What does this fixture show?",
        answer="The first fixture describes a possible benefit [F1]. "
               "This fixture describes uncertainty [F2].",
        finding_ids=["F1", "F2"],
    ), SubAnswer(
        question="How certain is the synthetic evidence?",
        answer="This fixture describes uncertainty [F3].", finding_ids=["F3"],
    )]
    report.conflicts = [Conflict(description="The synthetic sources differ in certainty.", finding_ids=["F1", "F2"])]
    report.gaps = ["Long-term outcomes are not covered by these synthetic fixtures."]
    if status == "partial":
        report.gaps.append("A requested sub-question has no verified finding.")
    if status not in {"complete", "partial"}:
        report.summary = {
            "urgent": "Synthetic emergency display: seek urgent medical care now. "
                      "This is a display test, not a live assessment.",
            "blocked": "Synthetic display: this question cannot be answered in educational research mode.",
            "out_of_scope": "Synthetic display: this question is outside women's health research.",
            "no_evidence": "Synthetic display: no statement could be verified, so no answer is given.",
            "error": "Synthetic display: research is unavailable. Please try again later.",
        }[status]
        report.key_findings = []
        report.sources = []
        report.sub_answers = []
        report.conflicts = []
        report.gaps = []
        report.redactions = []
        report.rejected_findings = 0
        report.rejection_reasons = {}
    return report
