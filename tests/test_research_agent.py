import sys
import unittest
import unittest.mock

from health_tools.contracts import EvidenceSource, ToolResult
from health_tools.research.allowlist import is_allowed, source_type_for
from health_tools.research.pipeline import ResearchAgent, render_report, scrub_terms
from health_tools.research.schema import (
    DraftConflict, DraftReport, DraftSubAnswer, Document, ExtractedFact, ExtractedFacts,
    RefinedSearch, ResearchPlan, SubQuestion,
)
from health_tools.research.sources import pubmed_documents
from health_tools.research.verify import claim_supported, keep_cited_sentences, quote_in_document
from health_tools.research.web_reader import ReaderError, extract_text, fetch_page

GUIDE_TEXT = (
    "Dysmenorrhea is painful menstruation. Regular aerobic exercise reduced menstrual pain "
    "intensity in several randomized trials. Heat therapy applied to the lower abdomen can "
    "relieve cramps. About 45% to 95% of menstruating women report period pain."
)
STUDY_TEXT = "In a small study, ginger capsules were associated with lower pain scores during menstruation."


class FakeLLM:
    def __init__(self, name, handlers, max_input_chars=20000):
        self.name, self.handlers, self.max_input_chars = name, handlers, max_input_chars
        self.calls = []

    def ask(self, schema, system, user):
        self.calls.append(schema.__name__)
        return self.handlers[schema.__name__](user)


def plan(_):
    return ResearchPlan(in_scope=True, sub_questions=[
        SubQuestion(question="What helps period pain?", search_terms="dysmenorrhea management 2024 my"),
        SubQuestion(question="Does diet help period pain?", search_terms="dysmenorrhea diet"),
    ])


def extract(user):
    if "Guide" in user:
        return ExtractedFacts(facts=[
            ExtractedFact(sub_question_index=0, claim="Regular aerobic exercise reduced menstrual pain intensity.",
                          quote="Regular aerobic exercise reduced menstrual pain intensity in several randomized trials."),
            ExtractedFact(sub_question_index=0, claim="Heat therapy cures period pain completely.",
                          quote="Heat therapy applied to the lower abdomen can relieve cramps."),
            ExtractedFact(sub_question_index=0, claim="Yoga eliminates cramps.",
                          quote="Yoga was shown to eliminate all menstrual cramps in every woman."),  # hallucinated quote
            ExtractedFact(sub_question_index=0, claim="About 60% of women report period pain.",
                          quote="About 45% to 95% of menstruating women report period pain."),  # wrong number
        ])
    if "Ginger" in user:
        return ExtractedFacts(facts=[ExtractedFact(
            sub_question_index=1, claim="Ginger capsules were associated with lower menstrual pain scores in a small study.",
            quote=STUDY_TEXT)])
    return ExtractedFacts()


def report(_):
    return DraftReport(
        summary="Aerobic exercise reduced menstrual pain [F1]. This sentence has no citation. Ginger may help [F9].",
        sub_answers=[DraftSubAnswer(sub_question_index=0, answer="Exercise helps [F1].")],
        conflicts=[DraftConflict(description="none really", finding_ids=["F1", "F99"])],
    )


class Searches:
    def __init__(self):
        self.terms = []

    def official(self, terms):
        self.terms.append(terms)
        if "dysmenorrhea management" in terms:
            return [Document(doc_id="who:1", url="https://www.who.int/pain", title="Guide",
                             publisher="WHO", source_type="official_guidance", text=GUIDE_TEXT)]
        if "ginger" in terms:
            return [Document(doc_id="pubmed:2", url="https://pubmed.ncbi.nlm.nih.gov/2/", title="Ginger trial",
                             publisher="PubMed", source_type="rct", text=STUDY_TEXT, published="2023")]
        return []


def make_agent(searches, plan_fn=plan):
    fast = FakeLLM("fake-fast", {"ResearchPlan": plan_fn, "DraftReport": report,
                                 "RefinedSearch": lambda _: RefinedSearch(search_terms=["ginger dysmenorrhea"])})
    long = FakeLLM("fake-long", {"ExtractedFacts": extract})
    agent = ResearchAgent(fast, long, searches={"fake": searches.official},
                          page_fetcher=lambda url, doc_id=None: (_ for _ in ()).throw(ReaderError("offline")),
                          fulltext_fetcher=lambda pmcid: (_ for _ in ()).throw(ReaderError("offline")))
    return agent, fast, long


class VerifyTests(unittest.TestCase):
    def test_quote_must_be_verbatim(self):
        self.assertTrue(quote_in_document("“Heat therapy applied to the lower abdomen can relieve cramps.”", GUIDE_TEXT))
        self.assertTrue(quote_in_document("Dysmenorrhea is painful menstruation ... can relieve cramps", GUIDE_TEXT))
        self.assertFalse(quote_in_document("Heat therapy always relieves cramps.", GUIDE_TEXT))
        self.assertFalse(quote_in_document("cramps", GUIDE_TEXT))  # too short to be evidence

    def test_claim_support_rules(self):
        quote = "About 45% to 95% of menstruating women report period pain."
        self.assertTrue(claim_supported("45% to 95% of menstruating women report period pain.", quote)[0])
        self.assertFalse(claim_supported("60% of women report period pain.", quote)[0])
        self.assertFalse(claim_supported("Heat cures cramps.", "Heat can relieve cramps.")[0])
        self.assertFalse(claim_supported("Metformin improves ovulation.", quote)[0])

    def test_uncited_sentences_dropped(self):
        text, cited = keep_cited_sentences("One [F1]. Two. Three [F7].", {"F1"})
        self.assertEqual(text, "One [F1].")
        self.assertEqual(cited, ["F1"])


class AllowlistAndReaderTests(unittest.TestCase):
    def test_allowlist(self):
        self.assertTrue(is_allowed("https://www.nichd.nih.gov/health/topics/pcos"))
        self.assertFalse(is_allowed("http://www.who.int/page"))
        self.assertFalse(is_allowed("https://who.int.evil.example/page"))
        self.assertFalse(is_allowed("https://evilwho.int/page"))
        self.assertFalse(is_allowed("https://user@www.who.int/page"))
        self.assertEqual(source_type_for("https://www.acog.org/x"), "professional_society")
        self.assertEqual(source_type_for("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"), "research_article")
        self.assertEqual(source_type_for("https://www.nichd.nih.gov/health"), "official_guidance")

    def test_fetch_refuses_other_domains_without_network(self):
        with self.assertRaises(ReaderError):
            fetch_page("https://example.com/")

    def test_extract_text_skips_scripts_and_prefers_main(self):
        html = ("<html><head><title>PCOS</title><script>var x='secret';</script></head><body>"
                "<nav>Menu Home</nav><main><p>" + "PCOS is a common hormonal condition. " * 20 +
                "</p></main><footer>Cookies</footer></body></html>")
        title, text = extract_text(html)
        self.assertEqual(title, "PCOS")
        self.assertIn("PCOS is a common hormonal condition.", text)
        for junk in ("secret", "Menu", "Cookies"):
            self.assertNotIn(junk, text)

    def test_pubmed_skips_retracted(self):
        def fake_search(terms, max_results, timeout):
            sources = tuple(EvidenceSource(source_id=f"pubmed:{i}", title=f"T{i}", url=f"https://pubmed.ncbi.nlm.nih.gov/{i}/",
                                           publisher="NCBI / PubMed", retrieved_at="now", excerpt="Abstract text.")
                            for i in (1, 2))
            data = {"articles": [
                {"source_id": "pubmed:1", "publication_types": ["Systematic Review"], "related_notices": []},
                {"source_id": "pubmed:2", "publication_types": [], "related_notices": [{"type": "RetractionIn"}]},
            ]}
            return ToolResult(tool="search_pubmed", status="ok", data=data, sources=sources)
        docs = pubmed_documents("pcos", search=fake_search)
        self.assertEqual([d.doc_id for d in docs], ["pubmed:1"])
        self.assertEqual(docs[0].source_type, "systematic_review")

    def test_scrub_terms(self):
        self.assertEqual(scrub_terms("my PCOS since 2019 age 34 me@x.com"), "PCOS since age")


class PipelineTests(unittest.TestCase):
    def test_end_to_end_only_verified_findings_survive(self):
        searches = Searches()
        agent, fast, _ = make_agent(searches)
        result = agent.run("What helps period pain, and does diet help?")

        self.assertEqual(result.status, "complete")
        claims = [f.claim for f in result.key_findings]
        self.assertEqual(len(claims), 2)
        self.assertIn("Regular aerobic exercise reduced menstrual pain intensity.", claims)
        self.assertTrue(any("Ginger" in c for c in claims))
        self.assertEqual(result.rejected_findings, 3)  # cure wording, fake quote, wrong number
        # Official guidance ranks first; ginger came from the second (refined) search round.
        self.assertEqual(result.key_findings[0].source_type, "official_guidance")
        self.assertIn("ginger dysmenorrhea", searches.terms)
        self.assertNotIn("2024", searches.terms[0])
        # Uncited and unknown-citation sentences removed from the summary.
        self.assertEqual(result.summary, "Aerobic exercise reduced menstrual pain [F1].")
        self.assertEqual(result.conflicts, [])
        self.assertEqual(len(result.sources), 2)
        self.assertEqual(len(result.sources[0].sha256), 64)
        self.assertEqual(result.models["extraction"], "fake-long")
        self.assertIn("Findings", render_report(result))

    def test_urgent_question_stops_before_any_llm_call(self):
        agent, fast, long = make_agent(Searches())
        result = agent.run("I am pregnant with severe pelvic pain and fainted")
        self.assertEqual(result.status, "urgent")
        self.assertTrue(result.protocol_id)
        self.assertEqual(fast.calls + long.calls, [])

    def test_dosing_question_blocked(self):
        agent, fast, _ = make_agent(Searches())
        self.assertEqual(agent.run("Should I stop taking my metformin?").status, "blocked")
        self.assertEqual(fast.calls, [])

    def test_out_of_scope(self):
        agent, _, long = make_agent(Searches(), plan_fn=lambda _: ResearchPlan(in_scope=False, reason="Not women's health."))
        result = agent.run("How do I fix my car engine?")
        self.assertEqual(result.status, "out_of_scope")
        self.assertEqual(long.calls, [])

    def test_no_evidence_gives_no_answer(self):
        class Empty(Searches):
            def official(self, terms):
                return []
        agent, _, _ = make_agent(Empty())
        result = agent.run("What helps period pain?")
        self.assertEqual(result.status, "no_evidence")
        self.assertEqual(result.key_findings, [])
        self.assertEqual(len(result.gaps), 2)


if __name__ == "__main__":
    unittest.main()


# ---- Fixes: summary fact-check, background quotes, duplicates, study type ----

from health_tools.research.sources import classify_publication_types, lookup_study_type
from health_tools.research.verify import cites_other_work, near_duplicate

HEAT_TEXT = (
    "Compared to no treatment, heat therapy is likely to reduce pain intensity during acute episodes. "
    "Heat therapy reduces pain intensity during acute episodes compared with no treatment. "
    "NSAIDs are effective for treating dysmenorrhea, as demonstrated by a meta-analysis of 35 randomized controlled trials (5). "
    "Yoga improved menstrual discomfort and mood in women with dysmenorrhea."
)


def heat_plan(_):
    return ResearchPlan(in_scope=True, sub_questions=[SubQuestion(question="Does heat help period pain?", search_terms="heat dysmenorrhea")])


def heat_extract(_):
    return ExtractedFacts(facts=[
        ExtractedFact(sub_question_index=0, claim="Heat therapy is likely to reduce pain intensity during acute episodes compared to no treatment.",
                      quote="Compared to no treatment, heat therapy is likely to reduce pain intensity during acute episodes."),
        ExtractedFact(sub_question_index=0, claim="Heat therapy reduces pain intensity during acute episodes.",
                      quote="Heat therapy reduces pain intensity during acute episodes compared with no treatment."),
        ExtractedFact(sub_question_index=0, claim="NSAIDs are effective for treating dysmenorrhea.",
                      quote="NSAIDs are effective for treating dysmenorrhea, as demonstrated by a meta-analysis of 35 randomized controlled trials (5)."),
        ExtractedFact(sub_question_index=0, claim="Yoga improved menstrual discomfort and mood.",
                      quote="Yoga improved menstrual discomfort and mood in women with dysmenorrhea."),
    ])


def heat_report(_):
    return DraftReport(
        summary=("Heat therapy is likely to reduce pain intensity during acute episodes [F1]. "
                 "Yoga improved menstrual discomfort and mood [F1]. "  # misattributed: yoga is only in F2
                 "Heat therapy is a proven cure that eliminates cramps permanently for everyone [F1]."),
        sub_answers=[DraftSubAnswer(sub_question_index=0, answer="Heat likely reduces pain intensity. [F1] Yoga improved discomfort. [F2]")],
    )


class FixTests(unittest.TestCase):
    def _agent(self, lookup):
        fast = FakeLLM("fast", {"ResearchPlan": heat_plan, "DraftReport": heat_report,
                                "RefinedSearch": lambda _: RefinedSearch()})
        long = FakeLLM("long", {"ExtractedFacts": heat_extract})
        search = lambda terms: [Document(doc_id="web:0", url="https://pmc.ncbi.nlm.nih.gov/articles/PMC1/",
                                         title="Heat paper", publisher="pmc", source_type="research_article",
                                         text="snippet", needs_fetch=True)]
        fetch = lambda url, doc_id=None: Document(doc_id=doc_id, url=url, title="Heat therapy review", publisher="pmc",
                                                  source_type="research_article", text=HEAT_TEXT)
        return ResearchAgent(fast, long, searches={"web": search}, page_fetcher=fetch, study_type_lookup=lookup)

    def test_all_four_fixes_end_to_end(self):
        result = self._agent(lambda url: ("systematic_review", False)).run("Does heat help period pain?")
        claims = [f.claim for f in result.key_findings]
        # Fix 2: background sentence citing "(5)" is rejected.
        self.assertFalse(any("NSAIDs" in c for c in claims))
        self.assertEqual(result.rejection_reasons.get("background statement citing other papers"), 1)
        # Fix 3: the shorter restatement of the heat finding is merged away.
        self.assertEqual(sum("Heat therapy" in c for c in claims), 1)
        self.assertEqual(result.rejection_reasons.get("near-duplicate of a stronger finding"), 1)
        # Fix 4: real study design from the paper lookup, not the domain.
        self.assertEqual(result.sources[0].source_type, "systematic_review")
        self.assertEqual(result.key_findings[0].source_type, "systematic_review")
        # Fix 1: misattributed and over-claiming summary sentences are removed.
        self.assertEqual(result.summary, "Heat therapy is likely to reduce pain intensity during acute episodes [F1].")
        self.assertEqual(result.sub_answers[0].finding_ids, ["F1", "F2"])
        self.assertIn("Rejected during verification", render_report(result))

    def test_retracted_web_paper_is_not_read(self):
        result = self._agent(lambda url: ("rct", True)).run("Does heat help period pain?")
        self.assertEqual(result.status, "no_evidence")
        self.assertTrue(any("retracted" in line for line in result.search_log))

    def test_reference_markers(self):
        self.assertTrue(cites_other_work("first-line therapy (2, 6)."))
        self.assertTrue(cites_other_work("widely endorsed [10, 21]."))
        self.assertTrue(cites_other_work("as Smith et al. showed"))
        self.assertFalse(cites_other_work("(OR 4.37, 95% CI 3.76 to 5.09; 35 RCTs, I(2) = 53%)"))

    def test_near_duplicate_is_strict(self):
        self.assertFalse(near_duplicate("NSAIDs work better than placebo for pain relief",
                                        "NSAIDs work better than paracetamol for pain relief"))
        self.assertFalse(near_duplicate("Pain fell by 30% with heat", "Pain fell by 50% with heat"))
        self.assertTrue(near_duplicate("Heat therapy reduces menstrual pain intensity.",
                                       "Local heat therapy reduces menstrual pain intensity during acute episodes."))

    def test_trailing_citations_stay_with_their_sentence(self):
        text, cited = keep_cited_sentences("Placebo claim. [F1] Paracetamol claim. [F2]", {"F1", "F2"})
        self.assertEqual(text, "Placebo claim [F1]. Paracetamol claim [F2].")

    def test_publication_type_classification(self):
        self.assertEqual(classify_publication_types(["Meta-Analysis", "Journal Article"]), "systematic_review")
        self.assertEqual(classify_publication_types(["systematic-review", "Review"]), "systematic_review")
        self.assertEqual(classify_publication_types(["Review", "Journal Article"]), "narrative_review")
        self.assertEqual(classify_publication_types(["Journal Article"], "A systematic review of yoga"), "systematic_review")
        self.assertEqual(classify_publication_types(["Practice Guideline"]), "guideline")

    def test_study_type_lookup_retries_and_ignores_other_urls(self):
        from health_tools.contracts import ToolError
        calls = []

        def flaky(query, max_results, timeout):
            calls.append(query)
            if len(calls) == 1:
                return ToolResult(tool="search_europepmc", status="error", error=ToolError("timeout", "t", True))
            return ToolResult(tool="search_europepmc", status="ok", data={"articles": [
                {"title": "Heat", "publication_types": ["Systematic Review", "Retracted Publication"]}]})

        self.assertEqual(lookup_study_type("https://pmc.ncbi.nlm.nih.gov/articles/PMC12876241/", search=flaky),
                         ("systematic_review", True))
        self.assertEqual(calls, ["PMCID:PMC12876241", "PMCID:PMC12876241"])
        self.assertEqual(lookup_study_type("https://www.who.int/news", search=flaky), (None, False))


# ---- Live-run fixes: model fallback sizing, quota cooldown, rewrite pass, plain terms ----

from health_tools.research import llm as llm_module


class FakeChat:
    def __init__(self, error=None, result=None):
        self.error, self.result, self.seen = error, result, []

    def with_structured_output(self, schema):
        chat = self

        class Runner:
            def invoke(self, messages):
                chat.seen.append(len(messages[1][1]))
                if chat.error:
                    raise chat.error
                return chat.result
        return Runner()


class LiveRunFixTests(unittest.TestCase):
    def setUp(self):
        llm_module._cooldown_until.clear()

    def test_fallback_gets_input_sized_for_it_and_quota_cools_down(self):
        gemini = FakeChat(error=RuntimeError("429 RESOURCE_EXHAUSTED quota"))
        groq = FakeChat(result=ExtractedFacts())
        client = llm_module.LangChainStructuredLLM([(gemini, "gemini", 40_000), (groq, "groq", 12_000)])
        user = "Sub-questions\n<document>\n" + "x" * 39_000 + "\n</document>"
        client.ask(ExtractedFacts, "sys", user)
        self.assertGreater(gemini.seen[0], 38_000)
        self.assertLessEqual(groq.seen[0], 12_000)
        client.ask(ExtractedFacts, "sys", user)  # Gemini skipped during cooldown
        self.assertEqual(len(gemini.seen), 1)
        self.assertEqual(len(groq.seen), 2)

    def test_all_models_failing_reports_every_error(self):
        client = llm_module.LangChainStructuredLLM([(FakeChat(error=ValueError("bad")), "a", 100),
                                                    (FakeChat(error=TimeoutError("slow")), "b", 100)])
        with self.assertRaises(RuntimeError) as ctx:
            client.ask(ExtractedFacts, "sys", "user")
        self.assertIn("a: ValueError", str(ctx.exception))
        self.assertIn("b: TimeoutError", str(ctx.exception))

    def test_boolean_search_syntax_is_removed(self):
        self.assertEqual(scrub_terms("Dysmenorrhea/therapy OR Heat therapy AND Exercise"),
                         "Dysmenorrhea therapy Heat therapy Exercise")
        self.assertEqual(scrub_terms('"dysmenorrhea"[MeSH] yoga'), "dysmenorrhea yoga")

    def test_rewrite_pass_replaces_unsupported_summary(self):
        drafts = iter([
            DraftReport(summary="Heat therapy is likely to reduce pain intensity during acute episodes [F1]. "
                                "Heat therapy is a proven permanent cure for every woman [F1]."),
            DraftReport(summary="Heat therapy is likely to reduce pain intensity during acute episodes [F1]. "
                                "Yoga improved menstrual discomfort and mood [F2]."),
        ])
        fast = FakeLLM("fast", {"ResearchPlan": heat_plan, "DraftReport": lambda _: next(drafts),
                                "RefinedSearch": lambda _: RefinedSearch()})
        long = FakeLLM("long", {"ExtractedFacts": heat_extract})
        search = lambda terms: [Document(doc_id="who:1", url="https://www.who.int/heat", title="Heat", publisher="WHO",
                                         source_type="official_guidance", text=HEAT_TEXT)]
        result = ResearchAgent(fast, long, searches={"s": search}).run("Does heat help period pain?")
        self.assertEqual(fast.calls.count("DraftReport"), 2)
        self.assertEqual(result.summary, "Heat therapy is likely to reduce pain intensity during acute episodes [F1]. "
                                         "Yoga improved menstrual discomfort and mood [F2].")
        rewrite = next(l for l in result.search_log if l.startswith("report rewrite"))
        self.assertIn("1 unsupported / 0 overlong sentences", rewrite)
        self.assertIn("; 0 / 0,", rewrite)


class SecondLiveRunFixTests(unittest.TestCase):
    def test_same_quote_findings_are_merged(self):
        def extract_twice(_):
            quote = "Compared to no treatment, heat therapy is likely to reduce pain intensity during acute episodes."
            return ExtractedFacts(facts=[
                ExtractedFact(sub_question_index=0, claim="Heat therapy likely reduces pain intensity during acute episodes.", quote=quote),
                ExtractedFact(sub_question_index=0, claim="Heat was identified as reducing acute pain compared to no treatment.", quote=quote),
            ])
        fast = FakeLLM("fast", {"ResearchPlan": heat_plan, "DraftReport": lambda _: DraftReport(summary=""),
                                "RefinedSearch": lambda _: RefinedSearch()})
        long = FakeLLM("long", {"ExtractedFacts": extract_twice})
        search = lambda terms: [Document(doc_id="who:1", url="https://www.who.int/heat", title="Heat", publisher="WHO",
                                         source_type="official_guidance", text=HEAT_TEXT)]
        result = ResearchAgent(fast, long, searches={"s": search}).run("Does heat help period pain?")
        self.assertEqual(len(result.key_findings), 1)

    def test_search_errors_are_logged_not_hidden(self):
        def broken(terms):
            raise RuntimeError("rate_limited: NCBI returned HTTP 429")
        agent, _, _ = make_agent(Searches())
        agent.searches = {"pubmed": broken}
        result = agent.run("What helps period pain?")
        self.assertTrue(any("ERROR rate_limited" in line for line in result.search_log))

    def test_pubmed_rate_limit_is_retried_once(self):
        from health_tools.contracts import ToolError
        from health_tools.research import sources
        calls = []

        def flaky(terms, max_results, timeout):
            calls.append(terms)
            if len(calls) == 1:
                return ToolResult(tool="search_pubmed", status="error", error=ToolError("rate_limited", "429", True))
            return ToolResult(tool="search_pubmed", status="insufficient_data")

        with unittest.mock.patch.object(sources.time, "sleep"):
            self.assertEqual(sources.pubmed_documents("pcos", search=flaky), [])
        self.assertEqual(len(calls), 2)

    def test_pmc_web_hits_are_read_through_europe_pmc(self):
        from health_tools.research import sources

        class FakeDDGS:
            def __init__(self, timeout=None):
                pass

            def text(self, query, max_results):
                return [{"href": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12876241/", "title": "Heat therapy", "body": "snippet"}]

        fake_module = type(sys)("ddgs")
        fake_module.DDGS = FakeDDGS
        with unittest.mock.patch.dict(sys.modules, {"ddgs": fake_module}):
            docs = sources.web_documents("heat dysmenorrhea")
        self.assertEqual(docs[0].pmcid, "PMC12876241")
        self.assertFalse(docs[0].needs_fetch)
        self.assertEqual(docs[0].text, "")  # search snippets are never treated as source text


class WebSearchRetryTests(unittest.TestCase):
    def _run(self, behaviours):
        from health_tools.research import sources
        queries = []

        class FakeDDGS:
            def __init__(self, timeout=None):
                pass

            def text(self, query, max_results):
                queries.append(query)
                outcome = behaviours[len(queries) - 1]
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        fake_module = type(sys)("ddgs")
        fake_module.DDGS = FakeDDGS
        with unittest.mock.patch.dict(sys.modules, {"ddgs": fake_module}), \
                unittest.mock.patch.object(sources.time, "sleep"):
            return sources.web_documents("dysmenorrhea exercise"), queries

    def test_no_results_falls_back_to_plain_terms(self):
        hit = [{"href": "https://www.nhs.uk/conditions/period-pain/", "title": "Period pain", "body": "b"}]
        docs, queries = self._run([Exception("No results found."), hit])
        self.assertEqual(queries, ["dysmenorrhea exercise women's health", "dysmenorrhea exercise"])
        self.assertEqual(docs[0].url, "https://www.nhs.uk/conditions/period-pain/")

    def test_no_results_everywhere_is_empty_not_error(self):
        docs, _ = self._run([Exception("No results found.")] * 3)
        self.assertEqual(docs, [])

    def test_real_failures_raise_after_retries(self):
        from health_tools.research.sources import SearchError
        with self.assertRaises(SearchError):
            self._run([TimeoutError("timed out")] * 3)


# ---- Third live-run fixes: meaning check, readability, coverage ----

from health_tools.research.pipeline import long_sentences
from health_tools.research.schema import ClaimCheck, ClaimChecks


def checks_flagging(index, corrected):
    def handler(user):
        n = user.count("CLAIM:")
        return ClaimChecks(checks=[
            ClaimCheck(index=i, quote_reports="q", claim_reports="c",
                       differences="dropped qualifier" if i == index else "none",
                       faithful=i != index, corrected_claim=corrected if i == index else "")
            for i in range(n)])
    return handler


class MeaningAndCoverageTests(unittest.TestCase):
    def _agent(self, checker, report=lambda _: DraftReport(summary="")):
        fast = FakeLLM("fast", {"ResearchPlan": heat_plan, "DraftReport": report,
                                "RefinedSearch": lambda _: RefinedSearch()})
        long = FakeLLM("long", {"ExtractedFacts": heat_extract, "ClaimChecks": checker})
        search = lambda terms: [Document(doc_id="who:1", url="https://www.who.int/heat", title="Heat", publisher="WHO",
                                         source_type="official_guidance", text=HEAT_TEXT)]
        return ResearchAgent(fast, long, searches={"s": search}), long

    def test_drifted_claim_is_reworded_to_match_quote(self):
        fixed = "Yoga improved menstrual discomfort and mood in women with dysmenorrhea."
        agent, long = self._agent(checks_flagging(2, fixed))  # index 2 = the yoga fact after filtering
        result = agent.run("Does heat help period pain?")
        self.assertIn("ClaimChecks", long.calls)
        self.assertIn(fixed, [f.claim for f in result.key_findings])
        self.assertTrue(any("reworded 1" in l for l in result.search_log))

    def test_unrepairable_claim_is_dropped(self):
        agent, _ = self._agent(checks_flagging(2, "Yoga cures all menstrual pain forever."))
        result = agent.run("Does heat help period pain?")
        self.assertFalse(any("Yoga" in f.claim for f in result.key_findings))
        self.assertEqual(result.rejection_reasons.get("claim changed the quote's meaning"), 1)

    def test_long_sentence_detection(self):
        self.assertEqual(long_sentences("Short one [F1]. Another short one [F2]."), [])
        self.assertEqual(len(long_sentences("A; b; c [F1].")), 1)
        self.assertEqual(len(long_sentences(" ".join(["word"] * 45) + " [F1].")), 1)

    def test_every_finding_ends_up_in_a_sub_answer(self):
        agent, _ = self._agent(lambda user: ClaimChecks(checks=[
            ClaimCheck(index=i, quote_reports="q", claim_reports="c", differences="none", faithful=True)
            for i in range(user.count("CLAIM:"))]))
        result = agent.run("Does heat help period pain?")
        cited = {i for a in result.sub_answers for i in a.finding_ids}
        self.assertEqual(cited, {f.id for f in result.key_findings})
