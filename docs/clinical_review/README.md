# Clinical review packet — not approved

Prepared 19 November 2026 for a qualified clinician to review. This packet does
not certify clinical accuracy, approve evidence, authorize treatment, or establish
readiness for patient use. All review decisions and sign-off fields are blank.
The code snapshot is identified in [snapshot.json](snapshot.json).

## Intended use and current behaviour

The intended audience is adults seeking general education about menstrual,
gynecologic, reproductive, obstetric, menopause and related women's-health
questions. It is not a diagnostic service, treatment selector, prescribing tool,
fertility predictor or emergency assessment service. A clinician must decide
whether its boundaries and messages are adequate for any proposed setting.

The main assistant retrieves passages from a local evidence manifest. All current
sources are unverified development records. Strict retrieval excludes them;
development settings can show them explicitly. The browser console currently
enables development evidence by default. The intake flow asks symptom questions
and lists things a doctor may consider; those rules and statements are also
development content and are not governed by approved manifest passages.

After a permitted evidence-gap turn, the assistant may offer separate literature
research. It runs only after explicit consent for that request. The integrated
web/CLI path rechecks the main safety, age and intake decisions, then the research
agent checks safety again, removes some personal details, plans a search, reads
sources, extracts quotes, checks claims, and writes a cited report. These checks
do not establish clinical truth. The standalone research API/CLI does not apply
all main-assistant age/intake/consent controls; this difference is a review question.

## How to use the packet

1. Read [safety_rules.md](safety_rules.md), including the questions for the
   reviewer. Use [safety_examples.md](safety_examples.md) to inspect observed
   wording behaviour and [exact_rules.md](exact_rules.md) to check exact patterns
   and messages against the linked code. Review the complete question/cause
   wording in [intake_content.md](intake_content.md).
2. Review every row in [allowed_sources.md](allowed_sources.md). A domain's
   evidence label is a code heuristic, not your approval of the whole site.
3. Read [privacy.md](privacy.md), particularly the search-backend and cache
   limitations. Clinical, privacy and governance reviewers may need to coordinate.
4. Check all 10 source records and 40 stored development passages in
   [evidence_manifest.md](evidence_manifest.md) against the original publications.
   Recorded dates, section names and reviewer fields are not proof of review.
5. Review the real runs indexed in [sample_reports/README.md](sample_reports/README.md).
   Follow each source link and compare each claim with its quote and the original
   context. Complete the blank form in each report. Safety cases intentionally
   have no findings. Do not treat an eval score as a clinical rating.
6. Complete [review_checklist.md](review_checklist.md), record requested changes,
   and sign individual items below. Approval, if eventually granted by an
   authorized reviewer, needs its own governed process and does not follow from
   editing this packet.

## Sign-off — leave blank until human review

Decision vocabulary: **approve / change / reject**. No decision is preselected.

| Item | Reviewer | Decision | Date | Notes |
| --- | --- | --- | --- | --- |
| Intended audience and exclusions | | | | |
| Urgent symptom and crisis rules | | | | |
| Blocked topics and medication boundaries | | | | |
| Minor and unknown-age handling across entry points | | | | |
| Symptom-intake questions, escalation and possible causes | | | | |
| Allowed sources and evidence labels | | | | |
| All manifest source metadata and passages | | | | |
| Personal-data handling and consent | | | | |
| Research verification and failure behaviour | | | | |
| Each sample report and safety response | | | | |
| Disclaimer and user-facing language | | | | |
| Suitability for the proposed clinical setting | | | | |

## Limits of preparation

The collection contains eight real outputs: one partial period-pain research
report and all seven safety cases. The partial report has four findings but also
quota/service failures and unavailable semantic checks, which are prominently
labelled. A ninth target, menopause hot flashes, failed on the first attempt and
returned no findings after a later retry; both attempts are excluded from the
samples and logged separately. The packet meets the requested 8–10-case range,
but does not claim a successful second research-topic report or broad clinical
coverage. A future collection with available provider capacity is needed for
that additional topic.

The packet records software behaviour and open questions, not clinical
conclusions. Prompt 1's accuracy changes were not adopted because repeated live
baselines were blocked by provider quotas. Prompts 2 and 3 changed display and
integration, not the research verifier or clinical rules. The latest integration
checks had 288 unit tests passing (2 skipped), research safety 7/7, and unchanged
main eval results: 28/50 in strict mode and 49/50 with development fixtures.
Existing release gates remain blocked. These are software checks, not validation
of medical advice. See [the integration notes](../RESEARCH_ASSISTANT_INTEGRATION.md)
and [the accuracy experiment](../RESEARCH_ACCURACY_EXPERIMENT.md).

The packet scripts in [_scripts/](_scripts/) only reproduce code/manifest
appendices, local examples and saved-report formatting. They do not change
approval fields, safety patterns or application behaviour. Snapshot hashes allow
later drift checks; they are not evidence of clinical review.
