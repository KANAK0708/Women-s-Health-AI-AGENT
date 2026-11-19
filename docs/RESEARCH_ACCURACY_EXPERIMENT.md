# Research accuracy experiment — 19 November 2026

## Outcome

Stopped before changing production behavior: both configured model providers hit
rate limits during the repeated baseline. There is no valid before/after comparison
and no demonstrated accuracy improvement. Applying planner or verifier changes
would violate the requirement to justify each change with eval evidence.

Claude was paused before further implementation. Existing staged and unstaged
work was preserved. No verification thresholds, safety rules, services, domains,
or eval cases were changed. No improvement commit was made because none was
validated or adopted.

## Protocol

- Research cache disabled with `RESEARCH_CACHE=off` for live comparisons.
- Working set: `pcos-diagnosis`, `menopause-hot-flashes`,
  `endometriosis-treatment`, `heavy-menstrual-bleeding`, `dysmenorrhea-relief`,
  `pcos-symptoms-lifestyle`.
- Held out: `gestational-diabetes`, `mammography-screening`,
  `contraception-effectiveness`, `folic-acid-preconception`. Their questions and
  topic groups were not inspected. They were not run because work stopped at
  baseline measurement.
- First screen: run the two known weak cases twice before testing planner changes,
  then expand to the working set if the screen is viable.
- Preserve the five requested improvement stages and measure each separately.

## Measurements

| Run | Cases | Mean coverage | Strong-evidence share | Rejected share | Mean seconds/question |
| --- | --- | ---: | ---: | ---: | ---: |
| Supplied historical baseline | 5 research | 0.69 | 0.47 | 0.31 | 128.06 |
| Fresh baseline, repeat 1 | 2 research | 0.54 | 0.41 | 0.33 | 131.40 |
| Fresh baseline, repeat 2 | Both planner calls failed | Not usable | Not usable | Not usable | Not usable |

The historical and fresh rows contain different case sets and software revisions;
their means are **not** an improvement comparison. The historical baseline already
includes a quota-failed case. Repeat 2's scorer emits zeros and subsecond durations
for errors; those values do not measure answer quality or successful-run latency.

| Fresh repeat 1 case | Coverage | Strong share | Rejected share | Seconds | Outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| `pcos-diagnosis` | 0.40 | 0.00 | 0.40 | 151.8 | Partial; failed coverage check |
| `menopause-hot-flashes` | 0.67 | 0.83 | 0.25 | 111.0 | Complete; passed checklist |

Both cases logged pipeline failures. In repeat 2, Groq and Gemini both returned
rate-limit errors at planning for both cases. These are provider failures, not
failed candidate improvements. No candidate attempt was evaluated.

Validation:

- `python3 -m unittest discover -s tests -q`: 245 tests run, OK, 2 skipped.
- Live `--category safety --pause 0`: **7/7** passed, including out-of-scope.
- No after-change safety result exists because behavior was not changed.
- No held-out results or results across all 20 research cases are claimed.

## Evidence reviewed and remaining weaknesses

Read the saved PCOS-diagnosis, menopause-hot-flashes, and endometriosis-treatment
reports from the historical run, plus both fresh repeat-1 reports, including
findings, supporting quotes, sub-answers, rejection reasons, and search logs.

1. Fresh PCOS retrieval found guideline links, but two NICE CKS pages returned
   HTTP 403. Several accessible guideline abstracts and landing pages yielded no
   extracted facts. The accepted findings came from one narrative review.
2. Keyword coverage understates some accepted text: the fresh PCOS answer contains
   `hyperandrogenism` and `anovulation`, while the case's word-start aliases do not
   match these forms. The cases and scorer were deliberately left unchanged.
3. The fresh menopause report retained much complementary-therapy material; its
   report writer hit a quota error, and its fallback summary omitted established
   options present in the sub-answers. Passing keyword coverage is insufficient.
4. The historical PCOS report's prose promotes tests performed in one study into
   tests "for PCOS confirmation," a stronger claim than the quoted study methods.
   The historical endometriosis report also presents emerging interventions without
   enough context about their clinical status. These require qualitative review
   alongside coverage and evidence-type scores.
5. The current meaning checker still retains word-overlap-passing claims when
   the meaning-check call fails or returns no check for a claim. This known issue
   remains unresolved; it was not silently changed out of the requested order.
6. Extraction still truncates long text. Source selection, chunk selection,
   extraction recall, and meaning-check fallback remain untested improvements.

## Reproduction and continuation

Local raw runs (ignored by Git, retained in the workspace):

- `evals/results/research_run_20261119_192819.json`: sandbox connection failure;
  interrupted before the second case, excluded from quality measurements.
- `evals/results/research_run_20261119_193303.json`: fresh baseline repeat 1.
- `evals/results/research_run_20261119_193556.json`: safety 7/7.
- `evals/results/research_run_20261119_193858.json`: repeat 2, both cases rate-limited.

The existing `research_latest.json` was restored to its pre-experiment contents;
the failed repeat does not replace the supplied historical baseline.

Once the configured providers have available quota, repeat the baseline screen:

```sh
RESEARCH_CACHE=off python3 -m evals.run_research_evals \
  --only pcos-diagnosis,menopause-hot-flashes --pause 60
```

Then test generic planner facet coverage first, repeat each comparison, and expand
to the six-case working set. Only adopt and commit an improvement after a valid
comparison and report review. Proceed to evidence selection, long-document
extraction, extraction recall, and stricter meaning fallback in order. Reserve the
held-out cases for the final evaluation. Stop and report if a candidate improvement
does not beat baseline after two attempts, as requested.
