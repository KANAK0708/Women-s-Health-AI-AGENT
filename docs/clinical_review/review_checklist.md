# Clinical review checklist — no decisions entered

For each item, record a reviewer, a decision (**approve / change / reject**), the
reason and any required validation. Blank means not reviewed, never approved.
The README's sign-off table is the final record for this packet; code/manifest
approval needs a separate authorized process.

## Intended population and scope

- [ ] Is adult educational use appropriate for the proposed setting and audience?
- [ ] What must the system refuse, clarify or refer rather than answer?
- [ ] Is unknown age acceptable, and what should happen with third-person/minor
  questions and age phrasing that the recognizer does not understand?
- [ ] Should the standalone research CLI/API and raw tool calls be exposed at all,
  given their different age, intake and consent controls?
- [ ] Do the intake's possible-cause lists or research treatment statements cross
  from general education into diagnosis or treatment selection?
- [ ] Which topics need extra caution: pregnancy/postpartum, acute pain/bleeding,
  contraception, fertility, cancer screening, PMDD/crisis, medications, menopause
  and postmenopausal bleeding, or others the reviewer identifies?

## Urgent and crisis handling

- [ ] Review every exact U1/U2 pattern and message, not just the passing safety
  cases. Are important symptoms, synonyms, spelling variants or languages absent?
- [ ] Are emergency destinations and time frames adequate and locally appropriate?
- [ ] How should negated, historical, third-person or educational mentions be
  handled without missing danger or giving inappropriate crisis messages?
- [ ] Are all six intake escalation conditions clinically appropriate, including
  numeric severity, pregnancy uncertainty, fever, right/left wording and bleeding
  amount? Review “not sure” versus “possible” and the negated-fever examples.
- [ ] Is an eight-turn intake safe for the proposed use? Are missing/unknown
  answers and unclear symptom wording handled appropriately?
- [ ] Is the crisis wording adequate when symptoms are severe but the exact
  suicide/self-harm phrases are not used? What human escalation is required?
- [ ] Are the two urgent sample reports appropriate despite having no findings?

## Blocked topics and medications

- [ ] Is the blanket emergency-contraception block appropriate? Does “validated
  educational corpus” misdescribe the current unverified state?
- [ ] Are medication initiation, stopping and dose changes comprehensively
  recognized? Review the “mg”/“milligrams”/“how much” examples.
- [ ] Which general medication-class discussions are appropriate for research,
  and which require a clinician/pharmacist referral?
- [ ] Is prompt-injection handling sufficient, including untrusted publisher text?

## Source choice, provenance and rights

- [ ] Complete the decision column for all 22 domains. Are any unsuitable, too
  broad, insufficiently current, commercially conflicted, or inaccessible?
- [ ] Do source-type badges overstate quality or applicability? Is a government
  page necessarily Strong evidence, and a society page necessarily Moderate?
- [ ] Can URL paths/title keywords misclassify non-guidelines as guidelines?
- [ ] Are important primary sources absent, including the Monash PCOS guideline
  domain present in the manifest but absent from the research allowlist?
- [ ] Confirm every manifest source URL, document identity, date, locator,
  jurisdiction, population, evidence grade, review claim and reuse right.
- [ ] Compare all 40 local development summaries with the actual source context.
  Which claims need replacement, qualification or removal through governance?
- [ ] Is the expired/superseded legacy test record appropriately segregated?
- [ ] Is unverified development evidence clearly separated from patient use,
  including the browser console's default development setting?

## Claim verification and sample reports

- [ ] Complete every report form and compare every finding, quote and source.
- [ ] Does the displayed claim preserve population, intervention/comparator,
  outcome, direction, uncertainty, study limitations and relevant clinical context?
- [ ] Does summary wording such as “can be initiated” sound like personal
  medication advice? Is there sufficient clinician/diagnostic context?
- [ ] Are dosage instructions reliably excluded, or only discouraged by a prompt?
- [ ] Are keyword coverage, lexical overlap, numeric-token matching, source tiers
  and “verified” labels being mistaken for clinical assurance?
- [ ] Are normalized/ellipsis/compact-character quote matches acceptable, and
  could noncontiguous text or altered units/ranges/negation change meaning?
- [ ] Is keeping claims after failed or incomplete semantic checks acceptable?
  Does “all faithful” in a later log line misleadingly imply a successful check?
- [ ] Are retractions, expressions of concern, abstract-only evidence and failed
  full-text retrieval handled adequately for the intended use?
- [ ] Are treatment options, prevention, contraindications, alternative diagnoses,
  uncertainty and when-to-seek-care information adequately covered where relevant?
- [ ] Are gaps/conflicts and provider-related omissions clear? A failed provider
  does not establish that no medical evidence exists.
- [ ] Is a report taking about eight minutes acceptable for this research mode,
  and could waiting delay someone who needs human care?

## Privacy, consent and retention

- [ ] Can users understand the exact data and recipients named in consent?
- [ ] Does `ddgs` automatic backend selection require additional recipient
  disclosure or a differently governed search configuration?
- [ ] Is English rule-based redaction adequate, including lowercase/non-Latin
  names, age/date variants, addresses, distinctive narratives and public-source
  text sent to models?
- [ ] Are provider contracts, jurisdiction, retention, training use and deletion
  responsibilities acceptable? They were not assessed by this packet.
- [ ] Are cache outputs and persistent expired cache files compatible with the
  intended retention and `/forget` promise? What deletion process is needed?
- [ ] Are raw intake snippets, screenshots, eval artifacts and browser copies
  sufficiently minimized, access-controlled and separated from patient records?
- [ ] Is the local development console segregated from any remote patient service?
- [ ] Are repeat consent, opting out, expiry, storage failures and in-flight
  deletion limitations explained adequately?

## Language and sign-off

- [ ] Is the exact disclaimer adequate without implying it makes unsafe content
  acceptable? Are “verified”, “approved”, “validated” and “Strong evidence” used
  in ways a lay reader will understand correctly?
- [ ] Are literacy level, accessibility, language coverage and inclusive wording
  suitable for the proposed audience?
- [ ] What further scenarios and independent clinical assessments are required?
- [ ] Have requested changes been reviewed and re-evaluated before any approval?
- [ ] Have all decisions, reviewers, dates, unresolved issues and limits of any
  eventual approval been recorded explicitly in the sign-off table?

## Open-question register

| Reference | Reviewer / decision / evidence required | Due date / disposition |
| --- | --- | --- |
| Q-SAFETY-01–10: urgent rules, boundaries, age/intake and verification | | |
| Q-SOURCE-01–06: domain inclusion, ranking and guideline classification | | |
| Q-PRIVACY-01–06: recipients, redaction, retention and entry points | | |
| Q-EVIDENCE-01–06: identity, summary fidelity, population and governance | | |
| Q-REPORT-01–03: treatment wording, certainty and omitted facets | | |

Reviewer name / specialty / date: ____________________

Additional questions or required changes: ____________________
