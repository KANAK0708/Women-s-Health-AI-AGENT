"""Build code/manifest appendices for the clinical-review packet; no API calls.

Run from the repository root: python3 docs/clinical_review/_scripts/build_snapshot.py
This writes documentation only. It never writes the manifest or application code.
"""

import ast
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs/clinical_review"

from app.retrieval.filters import DISALLOWED_CLINICAL_PATTERNS, URGENT_HAZARD_PATTERNS
from app.storage.context_tracker import AGE_PATTERN
from health_tools.research.allowlist import ALLOWED_DOMAINS, _GUIDELINE_PATHS
from health_tools.research.privacy import _RULES
from health_tools.symptom_intake import _SEEK_CARE, red_flags, _score
from health_tools import symptom_intake
from app.verification.verifier import HIGH_RISK_CLAIM_TOKENS, NEGATION_TOKENS, ClaimVerifier
from health_tools.research import verify, sources


def write(name, content):
    (OUT / name).write_text(content.rstrip() + "\n", encoding="utf-8")


def literal(value):
    text = str(value)
    fence = "`" * (max((len(part) for part in __import__("re").findall(r"`+", text)), default=0) + 1)
    return fence + text + fence


def table_cell(value):
    return str(value).replace("|", "&#124;").replace("\n", " ")


SITES = {
    "who.int": ("World Health Organization", "International public-health background and guidance."),
    "cdc.gov": ("US Centers for Disease Control and Prevention", "Public-health education, screening and prevention material."),
    "nih.gov": ("US National Institutes of Health, including NICHD", "Government health education; the more specific NCBI mapping takes precedence."),
    "ncbi.nlm.nih.gov": ("NCBI / National Library of Medicine, including PubMed and PMC", "Literature records and papers; being hosted by NIH does not make a paper official guidance."),
    "womenshealth.gov": ("US Office on Women's Health", "Women-focused public-health education."),
    "nice.org.uk": ("UK National Institute for Health and Care Excellence", "Clinical guidance and related public information."),
    "nhs.uk": ("UK National Health Service", "Public-facing health explanations and care information."),
    "fda.gov": ("US Food and Drug Administration", "Regulatory safety and medical-product information."),
    "healthdirect.gov.au": ("Healthdirect Australia", "Australian public-facing health information."),
    "acog.org": ("American College of Obstetricians and Gynecologists", "Specialist obstetric and gynecologic education and guidance."),
    "rcog.org.uk": ("Royal College of Obstetricians and Gynaecologists", "Specialist obstetric and gynecologic education and guidance."),
    "figo.org": ("International Federation of Gynecology and Obstetrics", "International professional-society material."),
    "asrm.org": ("American Society for Reproductive Medicine", "Professional reproductive-health and fertility material."),
    "endocrine.org": ("Endocrine Society", "Professional endocrine-health material relevant to reproductive conditions."),
    "menopause.org": ("The Menopause Society", "Professional menopause education and guidance."),
    "eshre.eu": ("European Society of Human Reproduction and Embryology", "Professional reproductive-health material."),
    "medlineplus.gov": ("MedlinePlus / US National Library of Medicine", "Consumer health explanations; not assigned the same tier as formal guidelines."),
    "mayoclinic.org": ("Mayo Clinic", "Consumer-facing condition explanations."),
    "clevelandclinic.org": ("Cleveland Clinic", "Consumer-facing condition explanations."),
    "europepmc.org": ("Europe PMC", "Biomedical literature and open-access records."),
    "ebi.ac.uk": ("EMBL European Bioinformatics Institute", "Europe PMC full-text API and literature hosting."),
    "cochranelibrary.com": ("Cochrane Library", "Evidence synthesis and systematic reviews."),
}
assert set(SITES) == set(ALLOWED_DOMAINS), "Review descriptions when domains change"
lines = ["# Allowed research sources — reviewer decisions blank", "",
         "These are the current code settings, not clinical approvals. The inclusion rationale below is an explanation inferred from the configured source role, not a recorded clinician decision or verification of each site's content.", "",
         "Source: [allowlist.py](../../health_tools/research/allowlist.py). All 22 configured domains are listed, including subdomain access.", "",
         "| Domain | Code evidence type | What the site is | Intended reason for inclusion (review required) | Reviewer decision |",
         "| --- | --- | --- | --- | --- |"]
for domain, kind in ALLOWED_DOMAINS.items():
    name, why = SITES[domain]
    lines.append(f"| {domain} | `{kind}` | {name} | {why} | |")
lines += ["", "## How a page becomes a guideline", "",
          "The code checks HTTPS, rejects URL credentials and nonstandard ports, and allows exact hosts or their subdomains. The most specific configured domain wins. It then searches the host/path string against these exact case-insensitive patterns:", ""]
for domain, pattern in _GUIDELINE_PATHS.items():
    lines += [f"### {domain}", "", "```regex", pattern.pattern, "```", ""]
lines += ["A matching path is labelled `guideline`; other pages keep their domain's default type. This is a URL heuristic, not confirmation that the page is a current, applicable guideline. PubMed/Europe PMC adapters also infer study type from publication metadata or title text (see [sources.py](../../health_tools/research/sources.py)). They look for guideline, systematic-review/meta-analysis, trial, and review labels; these labels do not independently establish study quality.", "",
          "The focused guideline search uses WHO, NICE, ACOG, RCOG and CDC, through DuckDuckGo. Generic searches can read any of the configured domains. The reader rechecks the allowlist on redirects and the final URL, checks robots.txt, limits response size and pages, and strips navigation/script content. An unreadable robots.txt is treated as allowed. These technical controls do not validate clinical relevance, translation, or permission to reuse text.", "",
          "Evidence display tiers: Strong = guideline / official_guidance / systematic_review; Moderate = professional_society / rct / narrative_review; Limited = research_article / consumer_health / web. A tier is a source-type label, not clinical approval.", "",
          "## QUESTIONS FOR THE REVIEWER", "",
          "- Q-SOURCE-01: Is a whole government or society domain a suitable basis for a Strong/Moderate label, including press releases and public information pages?",
          "- Q-SOURCE-02: Could broad WHO publication paths or words in paper titles incorrectly label non-guidelines as guidelines? Should currency, jurisdiction, population and formal methodology be checked separately?",
          "- Q-SOURCE-03: Are professional societies, consumer sites, general NIH/EBI subdomains and Cochrane pages appropriate as currently ranked? Review every row above.",
          "- Q-SOURCE-04: The main evidence manifest contains a Monash PCOS guideline URL, but `monash.edu` is not in the research allowlist. Should the research agent be able to read the primary guideline directly? No domain has been added here.",
          "- Q-SOURCE-05: Which materials require specific rights, language, update and conflict-of-interest review? Should unavailable/restricted guidance leave an explicit clinical gap rather than a substitute source?",
          "- Q-SOURCE-06: Is it appropriate to omit visible non-English URL paths from search results, while otherwise lacking a reliable document-language check? What local-language sources are needed?", ""]
write("allowed_sources.md", "\n".join(lines))

manifest = json.loads((ROOT / "clinical/evidence_manifest/manifest.json").read_text())
lines = ["# Evidence manifest — development / unverified", "",
         "This is a readable copy of metadata and stored development passages, not a clinical assessment of their truth. No source or passage was approved by preparing this packet. Metadata dates, titles, locators, review claims, hashes and reuse rights are not independently verified here.", "",
         "Source: [manifest.json](../../clinical/evidence_manifest/manifest.json).", "",
         f"Manifest version: `{manifest['manifest_version']}`. Provenance status: `{manifest['provenance_status']}`.", "",
         "Exact manifest notice:", "", "> " + manifest["provenance_notice"], "",
         f"There are **{len(manifest['sources'])} source records** and **{len(manifest['passages'])} passages**. Approval counts: `{dict(Counter(s['approval_status'] for s in manifest['sources']))}`. All source evidence-grade fields are absent/null. A stored review date or hash is not proof of review.", "",
         "Strict retrieval excludes unverified sources. Development settings can explicitly include unverified fixtures but still exclude superseded/expired sources. The browser console starts with development evidence enabled and defaults POST requests to it; the CLI requires its development flag unless configured elsewhere. These settings do not change approval status.", "",
         "## Source and passage review", "",
         "Reviewer decision fields below intentionally remain blank. Text labelled 'stored passage' is reproduced exactly from the local manifest; it is not claimed to be a verbatim quote from the linked publisher.", ""]
for source in manifest["sources"]:
    sid = source["source_id"]
    passages = [p for p in manifest["passages"] if p["source_id"] == sid]
    lines += [f"## {sid}", "", f"**{source['title']}**", "", f"Publisher: {source['publisher']}", "",
              f"Recorded URL: [{source['canonical_url']}]({source['canonical_url']})", "",
              "| Metadata field | Recorded value (unverified) |", "| --- | --- |"]
    for key, value in source.items():
        if key not in {"source_id", "title", "publisher", "canonical_url"}:
            lines.append(f"| {key} | {table_cell(json.dumps(value, ensure_ascii=False))} |")
    lines += ["", f"Passages: {len(passages)}. **Reviewer / decision / date / notes:** ____________________", ""]
    for p in passages:
        lines += [f"### {p['passage_id']}", "", f"Category: `{p['category']}`. Recorded review date: `{p['reviewed_at']}`.", "",
                  f"Recorded locator: {p['locator']}", "", f"Topic tags: {', '.join(p['topic_tags'])}", "",
                  "Stored development passage (not a verified publisher quote):", "", *["> " + line for line in p["text"].splitlines()], "",
                  "Accuracy / source match / applicability / rights / changes needed: ____________________", ""]
lines += ["## QUESTIONS FOR THE REVIEWER", "",
          "- Q-EVIDENCE-01: Do each URL, title, date and section locator actually identify the intended source? In particular, confirm the recorded ACOG menstrual-pain document and the PMS/PMDD record whose date differs from the URL year.",
          "- Q-EVIDENCE-02: Are each development summary and all its numbers, qualifiers and warning signs supported by the original document? What exact publisher passages and reuse permissions should replace these summaries?",
          "- Q-EVIDENCE-03: Are all sources correctly assigned to `Global` and `adults_18+`, or do jurisdiction/population limits need explicit review?",
          "- Q-EVIDENCE-04: Is enabling these unverified summaries by default in a development browser console sufficiently separated from any patient-facing use?",
          "- Q-EVIDENCE-05: Should intake 'possible causes' and safety-net text be governed by the same reviewed evidence process? They currently sit outside this manifest.",
          "- Q-EVIDENCE-06: The `example.org` legacy record is superseded and expired. Is keeping this clearly nonclinical test record in the same manifest appropriate?", ""]
write("evidence_manifest.md", "\n".join(lines))

lines = ["# Exact safety and privacy rule appendix", "",
         "This appendix preserves machine expressions as they currently exist. See [safety_rules.md](safety_rules.md) for plain-language explanations, observed examples and reviewer questions. No expression was edited.", "",
         "## Shared urgent patterns", ""]
for i, (pattern, protocol, message) in enumerate(URGENT_HAZARD_PATTERNS, 1):
    lines += [f"### U{i}: `{protocol}`", "", "Case-insensitive regular expression:", "", "```regex", pattern.pattern, "```", "", "Exact user message:", "", "> " + message, ""]
lines += ["## Shared blocked-topic patterns", ""]
for i, (pattern, message) in enumerate(DISALLOWED_CLINICAL_PATTERNS, 1):
    lines += [f"### B{i}", "", "```regex", pattern.pattern, "```", "", "Exact user message:", "", "> " + message, ""]
lines += ["## Adult-age recognition", "", "From [context_tracker.py](../../app/storage/context_tracker.py):", "", "```regex", AGE_PATTERN.pattern, "```", "",
          "A recognized age from 1 to 120 sets adult eligibility; the workflow refuses a context with `is_adult == 'no'` or `age < 18`. Missing context remains unknown, not adult-confirmed.", "",
          "## Symptom-intake escalation", "", "From [symptom_intake.py](../../health_tools/symptom_intake.py); exact functions:", "", "```python", inspect.getsource(_score).rstrip(), "", inspect.getsource(red_flags).rstrip(), "```", "",
          "Exact safety-net text included in intake summaries:", ""]
for text in _SEEK_CARE:
    lines += ["> " + text, ""]
lines += ["## All intake parsing and trigger context", "",
          "These expressions decide whether a personal symptom report enters intake and how answers become the values used above. They are included because parsing can change escalation. This is code text, not a clinician-endorsed questionnaire.", ""]
intake_source = (ROOT / "health_tools/symptom_intake.py").read_text()
cut = intake_source.index("# ---- state and transitions")
lines += ["```python", intake_source[:cut].rstrip(), "```", "",
          "## Research redaction expressions", "", "From [privacy.py](../../health_tools/research/privacy.py). Applied in this order; repeated 'date' and 'age' labels are separate patterns.", ""]
for label, pattern, replacement in _RULES:
    lines += [f"### {label} → {literal(replacement)}", "", "```regex", pattern.pattern, "```", ""]
lines += ["## Claim/quote safeguards — exact constants and expressions", "",
          f"Research `MIN_SUPPORT = {verify.MIN_SUPPORT}`, `MIN_QUOTE_CHARS = {verify.MIN_QUOTE_CHARS}`, `MIN_SENTENCE_SUPPORT = {verify.MIN_SENTENCE_SUPPORT}`, `MAX_NEW_TERMS = {verify.MAX_NEW_TERMS}`.", "",
          "High-risk tokens shared by the main and research verifier (sorted for readability, exact token text):", "", "```text", "\n".join(sorted(HIGH_RISK_CLAIM_TOKENS)), "```", "",
          "Main verifier's negation tokens:", "", "```text", "\n".join(sorted(NEGATION_TOKENS)), "```", "",
          "Background-reference pattern used to exclude research quotes:", "", "```regex", verify._REFERENCE_MARKER.pattern, "```", "",
          "Recognized retraction notices/types, exact text:", "", "```text", repr(sorted(sources._RETRACTION_NOTICES)), repr(sorted(sources._RETRACTION_TYPES)), "```", "",
          "The main claim verifier's exact claim-checking method follows. Its default overlap threshold is 0.55; the application still requires all claims supported and decision ACCEPT, rejecting partial repair. These lexical checks are not clinical proof.", "",
          "```python", inspect.getsource(ClaimVerifier._verify_single_claim).rstrip(), "```", ""]
write("exact_rules.md", "\n".join(lines))

lines = ["# Symptom-intake wording — development content for review", "",
         "This content is outside the approved-evidence manifest. It is reproduced from [symptom_intake.py](../../health_tools/symptom_intake.py), not endorsed or rewritten. Review its questions, conditional cause lists and safety-net wording for appropriateness and source support.", "",
         "## Questions", "", "| Slot | Exact question | Reviewer decision / changes |", "| --- | --- | --- |"]
for key, value in symptom_intake.QUESTIONS.items():
    lines.append(f"| {key} | {table_cell(value)} | |")
lines += ["", "## Order by complaint", ""]
for complaint, plan in symptom_intake.PLANS.items():
    lines.append(f"- {complaint}: " + " → ".join(plan))
lines += ["", "## Possible-cause statements and exact branch conditions", "",
          "The conditions below are copied as code expressions so their limits remain explicit. They describe what the software selects, not a clinician's differential diagnosis. All review fields are blank.", ""]
function_source = inspect.getsource(symptom_intake._possibilities)
function = ast.parse(function_source).body[0]

def causes(nodes, conditions=()):
    for node in nodes:
        if isinstance(node, ast.If):
            condition = ast.get_source_segment(function_source, node.test)
            causes(node.body, conditions + (condition,))
            causes(node.orelse, conditions + ("ELSE of: " + condition,))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "append" and call.args:
                phrase = ast.literal_eval(call.args[0])
                lines.extend(["### Statement", "", phrase, "", "Selected under:", "", "```python", "\nAND ".join(conditions), "```", "",
                              "Reviewer / decision / required source or change: ____________________", ""])

causes(function.body)
lines += ["## Exact safety-net statements", ""]
for phrase in _SEEK_CARE:
    lines += [phrase, "", "Reviewer / decision / required change: ____________________", ""]
write("intake_content.md", "\n".join(lines))

paths = ["app/retrieval/filters.py", "app/storage/context_tracker.py", "app/workflow/service.py",
         "health_tools/symptom_intake.py", "health_tools/workflow.py", "health_tools/deep_research.py",
         "health_tools/research/allowlist.py", "health_tools/research/privacy.py", "health_tools/research/pipeline.py",
         "health_tools/research/verify.py", "health_tools/research/sources.py", "health_tools/research/cache.py",
         "health_tools/research/web_reader.py", "health_tools/research/schema.py", "app/verification/verifier.py",
         "clinical/evidence_manifest/manifest.json", "evals/research/cases.json", "web_ui.py", "web_ui.html", "main.py",
         "tools.py", "health_tools/research/__main__.py", "health_tools/research/llm.py", "health_tools/handoff.py",
         "health_tools/guidelines.py", "health_tools/pending_tasks.py", "health_tools/cycle_history.py",
         "health_tools/integration.py", "health_tools/workflow_demo.py", "app/storage/redis_session_store.py",
         "app/storage/session_store.py", "app/storage/consent.py", "app/workflow/task_store.py",
         "app/retrieval/config.py", "app/retrieval/engine.py", "app/retrieval/pg_vector_engine.py"]
snapshot = {"code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "packet_status": "prepared_for_clinician_review_not_approved",
            "files_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}
write("snapshot.json", json.dumps(snapshot, indent=2))
print(f"Generated appendices: {len(ALLOWED_DOMAINS)} domains, {len(manifest['sources'])} sources, {len(manifest['passages'])} passages; no clinical decisions made.")
