# dysmenorrhea-relief — awaiting clinician review

This is a real software output from a fictional supplied eval question, not approved medical advice. Scores are development checklist results, not a clinical rating. Nothing in the review form is prefilled.

## Question

What helps menstrual cramps, and does exercise make a difference?

## Status and provenance

- Status: **partial**; protocol: `none`.
- Generated: `2026-11-19T20:37:42.823353+05:30`.
- Raw run: `research_run_20261119_202936.json`; SHA-256: `3511e3ee3a49038ce5df77ad4e2494a134a0c559cd0e3f5b87a0c484269dc568`.
- Duration: 485.9 seconds. Pipeline-failure markers: 8.
- Cache policy: enabled during this collection to respect free-tier limits; the runner does not report per-call cache hits.
- Entry point: the supplied research-eval runner uses the standalone research agent, not the integrated web/session gate.

Development scores: coverage 0.75; strong-source share 0.75; rejected share 0.5. Missing keyword groups: heat. These are not clinical completeness or correctness measures.

**Verification limitation in this report:** meaning checks were unavailable or incomplete. The pipeline retained claims using deterministic word-overlap checks. A later 'all faithful' log line is not evidence that every claim received a successful semantic check. Review all qualifiers, populations, outcomes and treatment wording yourself.

**Collection limitation:** this is a partial/degraded output with usable findings, not a failed planner/error report. Service/extraction/reporting failures are counted above. Omitted findings may reflect unavailable services rather than absent medical evidence. Do not treat this report as ready for patient use.

## Summary — exact report wording

Medicinal plants, drugs, and acupressure may relieve dysmenorrhea pain by reducing prostaglandins, mediating nitric oxide, increasing beta‑endorphin, blocking calcium channels, and enhancing uterine circulatory flow [F1](#f1). Meta‑analysis shows physiotherapy treatment reduces menstrual pain compared with no intervention or placebo [F2](#f2). Physiotherapy techniques such as isometric exercises, massage therapy, yoga, electrotherapy, connective tissue manipulation, stretching, kinesio tape, progressive relaxation exercises and aerobic dance are used to treat primary dysmenorrhea [F3](#f3). Empiric treatment with nonsteroidal anti-inflammatory drugs, with or without hormonal options, can be initiated for suspected primary dysmenorrhea [F4](#f4).

## Sub-answers

### What are the evidence‑based pharmacologic and non‑pharmacologic treatments for primary dysmenorrhea?

Medicinal plants, drugs, and acupressure may relieve dysmenorrhea pain by reducing prostaglandins, mediating nitric oxide, increasing beta‑endorphin, blocking calcium channels, and enhancing uterine circulatory flow [F1](#f1). Meta‑analysis shows physiotherapy treatment reduces menstrual pain compared with no intervention or placebo [F2](#f2). Physiotherapy techniques such as isometric exercises, massage therapy, yoga, electrotherapy, connective tissue manipulation, stretching, kinesio tape, progressive relaxation exercises and aerobic dance are used to treat primary dysmenorrhea [F3](#f3). Empiric treatment with nonsteroidal anti-inflammatory drugs, with or without hormonal options, can be initiated for suspected primary dysmenorrhea [F4](#f4).

## Findings and exact quotes

### F1

Claim: Medicinal plants, drugs, and acupressure may relieve dysmenorrhea pain by reducing prostaglandins, mediating nitric oxide, increasing beta‑endorphin, blocking calcium channels, and enhancing uterine circulatory flow.

Sub-question: What are the evidence‑based pharmacologic and non‑pharmacologic treatments for primary dysmenorrhea?

Source: [An update and systematic review on the treatment of primary dysmenorrhea.](https://pubmed.ncbi.nlm.nih.gov/30521155/)

Publisher: NCBI / PubMed; published: 2019 Jan 31; code type: `systematic_review`; lexical support score: 0.9 (not clinical confidence).

Exact quote as stored in the report (formatting inside the fence is preserved):

```text
Medicinal plants, drugs, and acupressure seem to suppress pain by reducing the level of prostaglandins, mediating nitric oxide, increasing beta-endorphin levels, blocking the calcium channel, and enhancing circulatory flow through the uterine pathway
```

Clinician finding-level notes: ____________________

### F2

Claim: Meta‑analysis shows physiotherapy treatment reduces menstrual pain compared with no intervention or placebo.

Sub-question: What are the evidence‑based pharmacologic and non‑pharmacologic treatments for primary dysmenorrhea?

Source: [Efficacy of Physiotherapy Treatment in Primary Dysmenorrhea: A Systematic Review and Meta-Analysis.](https://pubmed.ncbi.nlm.nih.gov/34360122/)

Publisher: NCBI / PubMed; published: 2021 Jul 23; code type: `systematic_review`; lexical support score: 0.8 (not clinical confidence).

Exact quote as stored in the report (formatting inside the fence is preserved):

```text
Meta-analysis shows benefits of physiotherapy treatment for pain relief compared with no intervention or placebo (MD: -1.13, 95% CI: -1.61 to -0.64, I2: 88%).
```

Clinician finding-level notes: ____________________

### F3

Claim: Physiotherapy techniques such as isometric exercises, massage therapy, yoga, electrotherapy, connective tissue manipulation, stretching, kinesio tape, progressive relaxation exercises and aerobic dance are used to treat primary dysmenorrhea.

Sub-question: What are the evidence‑based pharmacologic and non‑pharmacologic treatments for primary dysmenorrhea?

Source: [Efficacy of Physiotherapy Treatment in Primary Dysmenorrhea: A Systematic Review and Meta-Analysis.](https://pubmed.ncbi.nlm.nih.gov/34360122/)

Publisher: NCBI / PubMed; published: 2021 Jul 23; code type: `systematic_review`; lexical support score: 0.77 (not clinical confidence).

Exact quote as stored in the report (formatting inside the fence is preserved):

```text
The main techniques were isometric exercises, massage therapy, yoga, electrotherapy, connective tissue manipulation, stretching, kinesio tape, progressive relaxation exercises and aerobic dance.
```

Clinician finding-level notes: ____________________

### F4

Claim: Empiric treatment with nonsteroidal anti-inflammatory drugs, with or without hormonal options, can be initiated for suspected primary dysmenorrhea.

Sub-question: What are the evidence‑based pharmacologic and non‑pharmacologic treatments for primary dysmenorrhea?

Source: [Menstrual Disorders: Dysmenorrhea.](https://europepmc.org/article/MED/43037958)

Publisher: EMBL-EBI / Europe PMC; published: 2026; code type: `narrative_review`; lexical support score: 1.0 (not clinical confidence).

Exact quote as stored in the report (formatting inside the fence is preserved):

```text
Empiric treatment with nonsteroidal anti-inflammatory drugs with or without hormonal options can be initiated for suspected primary dysmenorrhea.
```

Clinician finding-level notes: ____________________

## Conflicts

None reported; this does not establish clinical consensus.

## Gaps — as reported

- How does regular exercise affect the severity of menstrual cramps?
- What non‑drug approaches besides exercise are effective for relieving menstrual pain?

## Rejections and redactions

Findings kept: 4. Rejected: 4.

- claim is not supported by the quote: 2
- quote not found in source: 1
- near-duplicate of a stronger finding: 1

Redaction categories: none reported. This does not prove the input was anonymous.

Models configured: plan_and_report = groq:openai/gpt-oss-120b -&gt; gemini:gemini-3.5-flash; extraction = gemini:gemini-3.5-flash -&gt; groq:openai/gpt-oss-120b.

## Sources

1. [An update and systematic review on the treatment of primary dysmenorrhea.](https://pubmed.ncbi.nlm.nih.gov/30521155/) — NCBI / PubMed; 2019 Jan 31; `systematic_review`.
   Read-text SHA-256: `551dd12b822b5113c5db1c928ae9f7f68aa37d2a3c83f2b258f3bb497932397f`; retrieved `2026-11-19T14:59:42.904981+00:00`.
2. [Efficacy of Physiotherapy Treatment in Primary Dysmenorrhea: A Systematic Review and Meta-Analysis.](https://pubmed.ncbi.nlm.nih.gov/34360122/) — NCBI / PubMed; 2021 Jul 23; `systematic_review`.
   Read-text SHA-256: `66963f45abf2cb6fa5269b52790f5d65d194e9e97b2bfac9ece775e01f6055d0`; retrieved `2026-11-19T14:59:42.904981+00:00`.
3. [Menstrual Disorders: Dysmenorrhea.](https://europepmc.org/article/MED/43037958) — EMBL-EBI / Europe PMC; 2026; `narrative_review`.
   Read-text SHA-256: `b9ede80c6376bb9158e8273e5ccb84d7892db67c97d301de3b470893c9f80528`; retrieved `2026-11-19T14:59:59.431173+00:00`.

## Report disclaimer — exact wording

Educational research summary built from the cited sources only. It is not a diagnosis or treatment plan; discuss your situation with a qualified clinician.

## Clinician review form — all responses blank

| Question | Reviewer response / requested change |
| --- | --- |
| Are the claims accurate? | |
| Is any claim overstated or missing a qualifier? | |
| Is important information missing? | |
| Could the wording cause harm or encourage unsafe action? | |
| Are the sources suitable, current and applicable? | |
| Do the quotes and citations support the full claim in context? | |
| Is this refusal/escalation appropriate, where relevant? | |
| Decision: approve / change / reject | |
| Reviewer / specialty / date | |
| Additional notes | |
