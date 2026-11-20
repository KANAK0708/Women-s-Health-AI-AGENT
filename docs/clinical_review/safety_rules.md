# Safety rules — clinician decisions required

This documents the code as it stands. None of these rules, thresholds, examples
or messages is clinically approved by this packet. “No match” means only that a
particular software rule did not fire; it is not a judgement that a question is
safe. Exact patterns/messages are preserved in [exact_rules.md](exact_rules.md).
Each shared pattern has three triggering and three nonmatching examples in
[safety_examples.md](safety_examples.md); that file also has 19 intake examples.

## 1. Shared urgent checks

Source: [app/retrieval/filters.py](../../app/retrieval/filters.py),
`URGENT_HAZARD_PATTERNS`. These run on the original question before research
redaction. Urgent checks take precedence over the blocked-topic patterns.

**U1, `PROTO-URGENT-HEMORRHAGE-ECTOPIC-01`:** a single case-insensitive pattern
matches faint/fainted/fainting; passed/pass out; syncope; unconscious; specific
dizziness-and-bleeding wording; soaking through pads/tampons; heavy bleeding
followed by hour/clot wording; severe pelvic/abdominal pain; pregnancy near
bleeding/pain/cramp/faint wording; ectopic; chest pain; or shortness of breath.
This is string matching, without a clinical interview or general negation check.
The exact expression and emergency message are in appendix U1.

**U2, `PROTO-URGENT-CRISIS-02`:** matches suicide/suicidal, kill myself, self-harm,
want to die, or end my life. The message asks the user to contact local emergency
services or a crisis lifeline immediately. It supplies no specific helpline or
local emergency number. Exact wording is in appendix U2.

The context tracker rechecks these urgent hazards on each turn, including topic
changes. Urgent decisions can still be returned during a session-store failure.
The integrated research path refuses to construct a model after a main urgent
decision. Bare `ResearchAgent.run()` repeats the shared patterns, but does not
run all main-assistant intake checks.

## 2. Blocked topics

Source: the same file, `DISALLOWED_CLINICAL_PATTERNS`.

| Rule | What it matches | Exact user-facing explanation |
| --- | --- | --- |
| B1 | i-pill, levonorgestrel, emergency contraception/contraceptive, morning-after pill | Emergency contraception advice is outside the validated educational corpus. |
| B2 | Specified stop-taking, change/double/increase/decrease/halve/adjust dose/dosage, prescribe-me and how-many-mg phrases | Medication initiation, stopping, or dosage adjustments require a prescribing clinician or pharmacist. |
| B3 | Specified ignore-safety/instructions/policies/rules, bypass-safety and system-prompt-override phrases | Prompt injection or safety policy override attempt blocked. |

The main assistant represents a shared-policy refusal as `out_of_scope`; the
bare research pipeline uses `blocked`. The integrated research gate returns
`blocked` for these policy stops. These are display/status differences, not
different pattern lists. Educational questions about an entire named topic can
also match B1. B2's refusal message is broader than the wording its regex catches.

## 3. Adult eligibility and missing context

Sources: [context_tracker.py](../../app/storage/context_tracker.py),
[workflow.py](../../health_tools/workflow.py), and
[memory.py](../../app/schemas/memory.py).

The age recognizer accepts specific first-person phrases (`I am`, `I'm`, `age is`,
`aged`) followed by a 1–3 digit number. Ages in 1–120 set an age/adult flag. The
workflow stops when `is_adult == 'no'` or a known age is below 18. Its exact message:

> This workflow supports adult education only. Please consult an appropriate healthcare professional.

“I am 16 years old. What is PCOS?” and “I'm 17. What is menopause?” set minor
context. “What is PCOS in women over 40?” does not set the user's own age. Unknown
age remains `not_provided`; it is not a verified-adult check. Current-turn age is
processed even when retention is off; retained context is used only under the
existing session consent rules. Bare research invocation lacks this age gate.

## 4. Extra symptom-intake escalation

Sources: [symptom_intake.py](../../health_tools/symptom_intake.py) and the
application's `_intake_step` in [service.py](../../app/workflow/service.py).
This development questionnaire recognizes personal symptom reports and parses
answers about location, timing, duration, severity, pregnancy, other symptoms,
bleeding, cycle history and discharge. It does not run for every general
educational question. Its full parsing expressions and exact `red_flags` function
are in the appendix, because their wording changes which cases escalate.

All six conditions below produce `PROTO-INTAKE-RED-FLAG-01`. Reasons are combined
if several conditions match. Read these as implementation rules requiring
clinical review, not endorsed triage thresholds.

The full question wording, complaint-specific ordering, and every possible-cause
statement with its selecting conditions are in [intake_content.md](intake_content.md).

| Condition in parsed answers | Meaning in plain language | Exact reason added to the user message |
| --- | --- | --- |
| `complaint in {'pain', 'bleeding'}` and `pregnancy in {'yes', 'possible'}` | Pain/bleeding with recognized pregnancy possibility | pain or bleeding when you are or might be pregnant can be a sign of a problem such as an ectopic pregnancy |
| Parsed severity `>= 8` | 8/10 or greater; “very severe” maps to 9, “severe” to 8 | severe pain needs to be checked the same day |
| `fever` in other symptoms and complaint pain/discharge/bleeding | Fever accompanying specified complaints | pain or discharge with a fever can mean an infection that needs prompt treatment |
| `right side` in location and vomiting or fever in other symptoms | Right-sided pain context with vomiting/fever | lower right pain with fever or vomiting needs checking for appendicitis |
| `dizziness or fainting` in other symptoms and complaint pain/bleeding | Dizziness with specified complaints | feeling faint with pain or bleeding can mean significant blood loss |
| Amount starts with `very heavy` | Parser-recognized soaking/hourly/large-clot/flooding wording | soaking through a pad or tampon every hour or two is very heavy bleeding |

Exact shared message template (the placeholder below denotes the reasons joined
by `; `; the appendix preserves the executable expression):

> Based on what you've told me, please get medical care now — go to urgent care or an emergency department, or call your local emergency number if it's severe or you feel faint.
>
> Why: {joined reasons}.
>
> I can't examine you, so it's safest to be seen in person.

Intake can ask up to eight turns. Its summary includes possible causes and
safety-net advice outside the manifest/claim-verification process. The exact
safety-net messages are in the appendix. With memory off it requests missing
answers together instead of remembering replies. Main urgent/minor/policy stops
take precedence and clear pending tasks/intakes.

## 5. Other safeguards and their limits

| Control and source | Behaviour / user-facing result |
| --- | --- |
| Input bounds, `service.py`, `workflow.py`, research `_safety` | Main input must be 1–4000 characters; research 3–2000. Main: “Please supply a question of 1–4000 characters.” Research: “Please ask a question of 3-2000 characters.” Invalid data does not run tools. |
| Safety/storage failures, `service.py`, `workflow.py` | Safety failures abstain; main urgent checks remain available during storage failure. One message: “The safety check is unavailable. Please contact a qualified healthcare professional for health concerns.” Another: “Session storage is unavailable. No stored context or pending dates were used; please retry later.” |
| Evidence eligibility, `filters.py`, local/PG retrieval engines | Approval (unless explicitly in development mode), currency, supersession, adult population and jurisdiction gates. Empty/failed evidence produces an abstention rather than an automatic web answer. Eligibility metadata is not proof of clinical approval. |
| Final main-answer verifier, `app/verification/verifier.py`, `service.py` | Resolves citations and checks lexical support/high-risk words/polarity. The application requires every displayed claim to pass and otherwise says: “I could not verify the retrieved answer, so I cannot provide an evidence-based response for this request.” This is a rule-based check, not clinical entailment proof. |
| Research consent gate, `deep_research.py`, `service.py`, `web_ui.py`, `main.py` | Exact `consent is True`; no offer on main safety/minor/task stops or absent keys; repeats main checks with tools disabled before research. Refusal begins “Deep research requires explicit consent for this request.” Provider configuration checks do not establish available quota. |
| Research planner, `pipeline.py` | Model classifies women's-health scope. Out-of-scope reason may be model-written; default: “This research mode only covers women's health topics.” This happens after a consented external planner call. |
| Research extraction/report prompts, `pipeline.py` | Instruct models to ignore document instructions, skip dosing, avoid diagnosis/personal treatment advice, copy quotes and cite claims. These instructions are not exhaustive deterministic clinical filters. |
| Research deterministic checks, `verify.py`, `sources.py`, `pipeline.py` | Quotes must be found in text read, with normalization/ellipsis and compact-character fallbacks; claim numbers and high-risk terms must occur in quotes; background citations, duplicates and recognized retractions are removed; report sentences must cite and overlap supported findings. These checks can miss altered clinical meaning. |
| Research semantic check, `_check_meaning` | Checks population/outcome/qualifiers/certainty and may repair a claim. On model failure, word-overlap-passing claims are kept; omitted checks are also kept. The Groq fallback can perform this check. This known limitation remains unchanged. |
| Research no-evidence handling, `pipeline.py` | “No statement could be verified against the sources that were read, so no answer is given.” No-evidence due provider failures is not proof the topic has no evidence. |
| Cycle/task controls, `cycle_history.py`, `pending_tasks.py` | Confirmed dates, chronological/unique/valid inputs, explicit reference date, at least two starts for an interval, at most 366 entries; no silent sorting or clinical normal/abnormal classification. Pending conversation tasks require confirmation, expire within five minutes and have six-turn bounds. |
| Offline guideline registry, `guidelines.py` | Requires approved/permitted/current exact-scope passages and matching text hashes; empty eligible results do not authorize unreviewed substitution. The clinical registry currently contains candidate URLs, not reviewed clinical passage content; demo passages are synthetic. |
| Reader and report display, research reader/allowlist and `web_ui.html` | Allowed HTTPS hosts and redirects, bounded page/PDF input, text extraction and nonexecuting report DOM; source links are HTTP(S) only. These are technical protections, not clinical validation. |
| Tool wrappers and separate entry points | `tools.py` reapplies shared regex checks to wrapper calls. Raw search adapters require callers to remove identifiers and obtain permission. `ResearchAgent.run`, the research module CLI and developer demos do not provide all integrated main-app controls. `workflow_demo.py` intentionally uses a pass-through demo safety stub and must not be mistaken for a clinical entry point. |

## 6. Disclaimer being reviewed

Research is also bounded to three sub-questions, two search rounds, eight read
documents and twelve findings. Web/PDF reading is capped at 60,000 text characters
and 60 PDF pages; extraction sees only the first model-budget segment (40,000
characters for the configured Gemini role, 12,000 for Groq fallback). Relevant
recommendations later in a document can be missed. The blocked accuracy work did
not implement chunking. Reviewer judgement is needed about missing facets and
any resulting false impression of completeness.

Exact research disclaimer from [schema.py](../../health_tools/research/schema.py):

> Educational research summary built from the cited sources only. It is not a diagnosis or treatment plan; discuss your situation with a qualified clinician.

The main response also says the development build's source-review metadata and
safety rules have not been independently verified. Intake summary disclaimers
state that only an examining clinician can determine the cause, and that its
questions/red flags/possible causes await clinician review. A disclaimer cannot
compensate for clinically unsafe content; its adequacy is a reviewer decision.

## QUESTIONS FOR THE REVIEWER — not proposed code fixes

- **Q-SAFETY-01:** Are the urgent and crisis triggers complete, and are their care
  destinations/time frames appropriate? Consider sudden one-sided pain/vomiting,
  infection symptoms, postpartum complications, and severe mood symptoms without
  the exact crisis words. Which additional scenarios require formal evaluation?
- **Q-SAFETY-02:** Is it acceptable that “I have no chest pain”, “I do not want to
  die”, denied-pregnancy pain, and educational ectopic questions can trigger
  emergency messaging? How should negation, historical symptoms and quoted text
  be assessed without missing danger?
- **Q-SAFETY-03:** Should the current blanket emergency-contraception block be
  retained? Its message calls the corpus “validated” although all manifest
  sources are unverified. What wording and safe referral are appropriate?
- **Q-SAFETY-04:** Are the medication boundaries adequate? “milligrams”, “how much”,
  and initiation requests need not match B2; research dosing exclusion is mainly
  a model instruction. Which educational drug-class discussions are appropriate?
- **Q-SAFETY-05:** Is eight turns too long before intake completion? Are severity
  mappings, the 8/10 cutoff, right/left asymmetry and the heavy-bleeding parser
  clinically appropriate? “do not have a fever” currently escalates where “no
  fever” does not.
- **Q-SAFETY-06:** In intake, `read_slot` can store “not sure” for pregnancy, while
  the urgent combination checks only “yes” or “possible”. Should these uncertainty
  answers lead to the same decision? No code was changed here.
- **Q-SAFETY-07:** Is unknown age acceptable? How should third-person/minor
  questions and unrecognized age phrasing be handled? Should standalone research
  and raw tool entry points share the integrated age/consent/intake gate?
- **Q-SAFETY-08:** Are the intake “Things a doctor may consider” lists appropriate
  for adult education, supported by reviewed evidence and unlikely to be read
  as diagnosis? Review every branch of `_possibilities` in the linked source.
- **Q-SAFETY-09:** Is retaining claims when semantic checking is unavailable or
  incomplete acceptable? Are exact-quote UI assurances, lexical scores, source
  tiers and normalized/noncontiguous quote matching adequately explained?
- **Q-SAFETY-10:** Are the disclaimer, generic emergency/crisis referrals,
  literacy level, supported languages and geographical scope sufficient for the
  proposed audience? What local contact/urgent-care governance is required?

All decisions remain blank in the packet sign-off table. This document records
questions for a human review process; it does not implement a change in policy.
