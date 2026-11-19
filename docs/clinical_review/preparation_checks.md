# Preparation checks — not clinical validation

Prepared against application commit `afb6746` on 19 November 2026. The packet
contains no clinical sign-off and does not change source approval or safety.

| Preparation check | Observed result |
| --- | --- |
| Manifest source/passages inventory | All 10 sources and all 40 exact stored development passages reproduced. All 10 source approval values remain `unverified`. |
| Allowed-domain inventory | All 22 configured domains included, with blank reviewer decision columns. |
| Exact shared safety patterns/messages | Both urgent patterns and all three blocked-topic patterns reproduced from live code constants, with exact protocol IDs and messages. |
| Intake content | All 11 question slots, complaint plans, 20 possible-cause statement branches, six escalation conditions and summary safety-net text included for review. |
| Local behaviour examples | 30 named-pattern examples, 19 isolated intake examples and six wording-concern assertions checked locally; no external calls or rule changes. |
| Saved-report formatting | Eight outputs included. All seven safety cases passed. Every included question, finding quote and source URL checked against its raw saved report. This is a copying/fidelity check, not a clinical support judgement. |
| Failed collection attempts | Menopause first attempt: planner `error`, quota observed, 0.6 s. Later retry: `no_evidence`, quota observed, 490.8 s. Both excluded from sample reports and logged in the collection index. |
| Partial period-pain sample | Four findings; coverage 0.75, strong-type share 0.75, rejected share 0.50, 485.9 s, eight pipeline-failure markers. Semantic-check unavailability is prominently labelled. These figures are not clinical quality ratings. |
| Code/data integrity | All 36 source/data file hashes in `snapshot.json` match. Separate before/after checks also cover the manifest, eval cases, safety filters, intake rules, research verifier and restored `research_latest.json`. |
| Main application unit suite | `python3 -m unittest discover -s tests -q`: 288 tests, OK, 2 skipped. |
| Packet links and decisions | Local links resolve; per-report reviewer response/decision cells and sign-off fields are blank. |
| Provider-key check | No provider-key-shaped strings found in the packet; `.env` is not copied or committed. |
| Git scope | Packet documentation and its reproduction scripts only. No production code, safety rules, approval/review fields, eval cases or result baselines changed. |

The first sample collection used the nine specified eval IDs with `--pause 60`.
The second collection retried only the quota-failed menopause case after the
intervening cooldown. Default research caches were enabled; no claim of fresh
uncached accuracy measurement is made. Raw run digests and per-case outcomes are
in [sample_reports/collection_index.json](sample_reports/collection_index.json).
Raw failed reports are not included as samples. Provider error text and account
identifiers are not reproduced in the clinical packet.

The 31 numbered open questions cover safety, source inclusion, provenance,
privacy, and report wording/verification. They are questions for authorized human
review, not automatic fixes or implicit decisions. The development eval release
gates documented in the README remain blocked.
