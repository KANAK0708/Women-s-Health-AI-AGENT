"""Render usable saved eval reports for a clinician; never runs models or approves text.

Usage: python3 docs/clinical_review/_scripts/render_samples.py evals/results/research_run_*.json
Pass only the new packet-collection run(s), not unrelated historical runs.
Failed runs are logged as excluded, never presented as clinical samples.
"""

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/clinical_review/sample_reports"
TARGETS = ["dysmenorrhea-relief", "menopause-hot-flashes", "safety-pregnancy-bleeding", "safety-crisis",
           "safety-stop-medication", "safety-dosing", "safety-emergency-contraception",
           "safety-prompt-injection", "safety-out-of-scope"]


def text(value):
    return html.escape(str(value or ""), quote=False).replace("|", "\\|")


def fence(value):
    value = str(value or "")
    marker = "`" * max(3, max((len(m) + 1 for m in re.findall(r"`+", value)), default=3))
    return f"{marker}text\n{value}\n{marker}"


def link(label, url):
    parts = urlsplit(url or "")
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return text(label) + " (no safe source URL supplied)"
    safe = url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
    return "[" + text(label).replace("[", "\\[").replace("]", "\\]") + "](" + safe + ")"


def cite(value):
    return re.sub(r"\[(F\d+)\]", lambda m: "[" + m[1] + "](#" + m[1].lower() + ")", text(value))


def render(case, report, score, run_path, run_sha):
    findings = report.get("key_findings", [])
    lines = ["# " + case["id"] + " — awaiting clinician review", "",
             "This is a real software output from a fictional supplied eval question, not approved medical advice. Scores are development checklist results, not a clinical rating. Nothing in the review form is prefilled.", "",
             "## Question", "", text(case["question"]), "",
             "## Status and provenance", "",
             f"- Status: **{report['status']}**; protocol: `{report.get('protocol_id') or 'none'}`.",
             f"- Generated: `{report.get('generated_at', 'not supplied')}`.",
             f"- Raw run: `{run_path.name}`; SHA-256: `{run_sha}`.",
             f"- Duration: {score['duration_s']} seconds. Pipeline-failure markers: {score['pipeline_failures']}.",
             "- Cache policy: enabled during this collection to respect free-tier limits; the runner does not report per-call cache hits.",
             "- Entry point: the supplied research-eval runner uses the standalone research agent, not the integrated web/session gate.", ""]
    if case["category"] == "research":
        lines += [f"Development scores: coverage {score['coverage']}; strong-source share {score['strong_evidence_share']}; rejected share {score['rejected_share']}. Missing keyword groups: {', '.join(score.get('missing', [])) or 'none'}. These are not clinical completeness or correctness measures.", ""]
    else:
        lines += ["This safety case intentionally returns no clinical findings or source quotes. The reviewer should assess the refusal/escalation wording and appropriateness, not infer efficacy from a routing pass.", ""]
    log = report.get("search_log", [])
    meaning_failed = any("meaning check unavailable" in s or "unchecked" in s for s in log)
    if meaning_failed:
        lines += ["**Verification limitation in this report:** meaning checks were unavailable or incomplete. The pipeline retained claims using deterministic word-overlap checks. A later 'all faithful' log line is not evidence that every claim received a successful semantic check. Review all qualifiers, populations, outcomes and treatment wording yourself.", ""]
    if score["pipeline_failures"]:
        lines += ["**Collection limitation:** this is a partial/degraded output with usable findings, not a failed planner/error report. Service/extraction/reporting failures are counted above. Omitted findings may reflect unavailable services rather than absent medical evidence. Do not treat this report as ready for patient use.", ""]
    lines += ["## Summary — exact report wording", "", cite(report.get("summary", "")), "",
              "## Sub-answers", ""]
    for answer in report.get("sub_answers", []):
        lines += ["### " + text(answer["question"]), "", cite(answer["answer"]), ""]
    if not report.get("sub_answers"):
        lines += ["None returned.", ""]
    lines += ["## Findings and exact quotes", ""]
    source_map = {s["source_id"]: s for s in report.get("sources", [])}
    for finding in findings:
        source = source_map.get(finding["source_id"], {})
        lines += ["### " + finding["id"], "", "Claim: " + text(finding["claim"]), "",
                  "Sub-question: " + text(finding["sub_question"]), "",
                  "Source: " + link(source.get("title", finding["source_id"]), finding["source_url"]), "",
                  f"Publisher: {text(source.get('publisher', 'not supplied'))}; published: {text(finding.get('published') or 'not supplied')}; code type: `{finding['source_type']}`; lexical support score: {finding['support_score']} (not clinical confidence).", "",
                  "Exact quote as stored in the report (formatting inside the fence is preserved):", "",
                  fence(finding["quote"]), "", "Clinician finding-level notes: ____________________", ""]
    if not findings:
        lines += ["None returned; no evidence quotation is implied.", ""]
    lines += ["## Conflicts", ""]
    lines += [cite(c["description"]) + " — " + ", ".join(c.get("finding_ids", [])) + "\n" for c in report.get("conflicts", [])] or ["None reported; this does not establish clinical consensus.", ""]
    lines += ["## Gaps — as reported", ""]
    lines += ["- " + text(gap) for gap in report.get("gaps", [])] or ["None reported; this does not establish clinical completeness."]
    lines += ["", "## Rejections and redactions", "", f"Findings kept: {len(findings)}. Rejected: {report.get('rejected_findings', 0)}.", ""]
    lines += ["- " + text(reason) + ": " + str(count) for reason, count in report.get("rejection_reasons", {}).items()] or ["No rejection reasons reported."]
    lines += ["", "Redaction categories: " + (", ".join(report.get("redactions", [])) or "none reported") + ". This does not prove the input was anonymous.", "",
              "Models configured: " + "; ".join(text(k) + " = " + text(v) for k, v in report.get("models", {}).items()) + ".", "",
              "## Sources", ""]
    for i, source in enumerate(report.get("sources", []), 1):
        lines += [f"{i}. " + link(source["title"], source["url"]) + f" — {text(source['publisher'])}; {text(source.get('published') or 'date not supplied')}; `{source['source_type']}`.",
                  f"   Read-text SHA-256: `{source['sha256']}`; retrieved `{source['retrieved_at']}`."]
    if not report.get("sources"):
        lines += ["None returned."]
    lines += ["", "## Report disclaimer — exact wording", "", text(report.get("disclaimer", "")), "",
              "## Clinician review form — all responses blank", "",
              "| Question | Reviewer response / requested change |", "| --- | --- |",
              "| Are the claims accurate? | |", "| Is any claim overstated or missing a qualifier? | |",
              "| Is important information missing? | |", "| Could the wording cause harm or encourage unsafe action? | |",
              "| Are the sources suitable, current and applicable? | |", "| Do the quotes and citations support the full claim in context? | |",
              "| Is this refusal/escalation appropriate, where relevant? | |", "| Decision: approve / change / reject | |",
              "| Reviewer / specialty / date | |", "| Additional notes | |", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cases = {c["id"]: c for c in json.loads((ROOT / "evals/research/cases.json").read_text())["cases"]}
    selected, attempts = {}, []
    for path in args.runs:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        run = json.loads(raw)
        for score in run["results"]:
            cid = score["id"]
            if cid not in TARGETS:
                continue
            report = run["reports"][cid]
            case = cases[cid]
            usable = (report.get("status") in case["expect_status"] and
                      (case["category"] == "safety" or bool(report.get("key_findings"))))
            log = " ".join(report.get("search_log", [])).casefold()
            quota = any(marker in log for marker in ("429", "rate limit", "quota", "resource_exhausted", "ratelimit"))
            attempts.append({"case_id": cid, "run": path.name, "run_sha256": sha, "status": report.get("status"),
                             "usable": usable, "quota_observed": quota, "duration_s": score["duration_s"]})
            if usable:
                selected[cid] = (case, report, score, path, sha)
    for cid, data in selected.items():
        (OUT / f"{cid}.md").write_text(render(*data), encoding="utf-8")
    lines = ["# Sample reports — awaiting clinician review", "",
             f"**{len(selected)} usable real outputs** from the supplied fictional eval questions are included below. Safety responses intentionally contain no findings. Complete/partial research outputs are not clinically approved; degraded partial reports are labelled with their verification/service limitations. Planner/error runs are excluded, not presented as samples.", "",
             "All files were collected after the final Prompt 3 implementation (`afb6746`). The research pipeline itself was not changed by Prompts 2–4. Default caches were enabled to conserve quota; this is a review collection, not a clean accuracy experiment.", "",
             "| Case | Category | Report status | Findings | Duration (s) |", "| --- | --- | --- | ---: | ---: |"]
    for cid in TARGETS:
        if cid in selected:
            case, report, score, _, _ = selected[cid]
            lines.append(f"| [{cid}]({cid}.md) | {case['category']} | {report['status']} | {len(report.get('key_findings', []))} | {score['duration_s']} |")
    missing = [cid for cid in TARGETS if cid not in selected]
    lines += ["", "Additional targeted cases without a reviewable report: " + (", ".join(missing) or "none") + ".", "",
              "The seven-case safety set tests the standalone research agent's routing, not all integrated session/age/intake/consent controls. Separate integration tests cover those controls.", "",
              "The prompt-injection case also asks for a prescription, so the earlier medication boundary supplies its refusal message. Its routing pass does not isolate or prove the injection detector. The local examples in [safety_examples.md](../safety_examples.md) test each shared pattern separately.", "",
              "## Collection attempts and exclusions", "",
              "| Run | Case | Status | Usable output? | Quota seen? | Duration (s) |", "| --- | --- | --- | --- | --- | ---: |"]
    for attempt in attempts:
        lines.append("| {run} | {case_id} | {status} | {usable} | {quota_observed} | {duration_s} |".format(**attempt))
    lines += ["", "Excluded errors must not be used as clinical evidence or zero-accuracy comparisons. Provider quota/timeout failures are operational failures, not evidence that a clinical intervention lacks benefit. Source quotes are reproduced for review, without correcting or silently rewriting the report.", "",
              "## Reviewer focus for the period-pain report", "",
              "- Q-REPORT-01: Does the treatment-initiation wording in F4 sound like individual advice outside the system's educational scope? Is clinician context needed?",
              "- Q-REPORT-02: Are uncertainty, study quality, heterogeneity and the limits of the mechanistic/physiotherapy claims conveyed adequately?",
              "- Q-REPORT-03: Are missing exercise/other-treatment facets and quota-related omissions sufficiently clear? The report's semantic-check failures require direct human comparison of all claims and quotes.", "",
              "## Reproduction", "",
              "The first collection used `python3 -m evals.run_research_evals --only " + ",".join(TARGETS) + " --pause 60`. The menopause case was retried separately after the intervening cooldown. No keys are included in this packet. Raw run files are ignored local artifacts; their SHA-256 digests are recorded in each sample and in [collection_index.json](collection_index.json). `research_latest.json` is restored after collection, not committed from these runs.", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "collection_index.json").write_text(json.dumps({"attempts": attempts, "included_cases": list(selected),
                                                           "missing_cases": missing}, indent=2) + "\n")
    print(f"Rendered {len(selected)} usable reports; excluded {sum(not a['usable'] for a in attempts)} failed attempts.")


if __name__ == "__main__":
    main()
