"""Local synthetic offer-to-report browser demo; never calls external services.

Run: python3 -m dev.research_offer_demo --port 8766
Ask "What is PCOS?", then accept the offer. All evidence gaps and reports here
are synthetic; this launcher is separate from the production entry point.
"""

from app.retrieval.engine import RetrievalBundle
from app.storage.session_store import EphemeralSessionStore
from app.workflow.service import HealthApplication
from dev.research_demo import demo_report
import web_ui


class SyntheticAgent:
    def run(self, question, progress=None):
        if progress:
            progress("Synthetic display fixture only; no external calls.")
        report = demo_report("complete")
        report.question = question
        return report


class SyntheticApplication(HealthApplication):
    def process(self, *args, **kwargs):
        result, session = super().process(*args, **kwargs)
        offer = result.response.get("research_offer")
        if offer:
            offer["reason"] = "Synthetic demo: the evidence gap is simulated. This button uses a local report fixture; no external services will be called."
        return result, session


def main():
    web_ui.app_instance = SyntheticApplication(
        store=EphemeralSessionStore(), research_availability=lambda: True,
        retrieve=lambda query, **kwargs: RetrievalBundle(query, "synthetic-demo", [], []),
    )
    web_ui._research_agent = SyntheticAgent
    web_ui.HTML_PAGE = web_ui.HTML_PAGE.replace("<title>Women's Health AI Agent</title>",
                                               "<title>Synthetic research offer demo</title>")
    web_ui.main()


if __name__ == "__main__":
    main()
