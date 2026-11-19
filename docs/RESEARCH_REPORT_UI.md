# Research report display

The chat now renders the structured `ResearchReport` returned by a research job.
The plain `rendered` response remains the fallback when no structured report is
present. The report schema and research pipeline are unchanged.

The card starts with the summary, followed by sub-answers, disagreement and gap
callouts, an evidence legend, and numbered sources. Citation buttons reveal the
exact quote, source title, publisher, publication year, evidence label, and source
link. They work with click, mouse hover, Enter/Space, and Escape. A close button
returns focus to the citation. The full findings list and verification details
are closed by default. The verification section includes rejection counts and
reasons, redaction categories, models, generation time, and a scrollable search
log. The disclaimer is always the last element of the report card.

Evidence labels describe source types, not clinical approval or a guarantee of
quality. Missing publication years and metadata are shown as unavailable rather
than inferred. Urgent reports show an emergency callout without findings;
blocked, out-of-scope, no-evidence, and error reports show plain explanations.
Partial reports explicitly note unanswered sub-questions.

All report content is inserted with DOM creation and text nodes. Links accept
only absolute HTTP/HTTPS URLs without embedded credentials, and open with
`target="_blank" rel="noopener noreferrer"`. No frameworks, fonts, CDNs, external
assets, or new dependencies were added.

## Local fixtures

```sh
WEB_UI_DEMO=1 python3 web_ui.py --port 8765
```

Open <http://127.0.0.1:8765/?research_demo=complete>. The fixture selector covers
all seven report statuses. Add `&research_demo_theme=light` to inspect the light
palette even when the system uses dark mode. This override is applied only after
a successful demo response. Normal chat follows the existing system preference.

`GET /api/research/demo?status=complete` returns a finished synthetic report without
initializing a model, starting a job, or making an external request. The endpoint
returns 404 unless `WEB_UI_DEMO` is exactly `1`. Invalid fixture statuses return
400. The fixtures are marked as synthetic in the page, log, and disclaimer; they
are not clinically verified samples. One quote contains literal `<script>` and
`<img onerror=...>` text. The third source deliberately contains a `javascript:`
URL to exercise link rejection. Do not enable the demo endpoint for deployment.

## Verification

- `python3 -m unittest discover -s tests -q`: 263 tests, OK, 2 skipped.
- Five new offline HTTP/fixture tests cover default-off gating, exact opt-in,
  all schema-valid fixture statuses without research calls, invalid statuses,
  and the malicious-text fixtures. They use an in-memory HTTP connection.
- The inline JavaScript passed `node --check`.
- Browser checks used 1280px desktop and 375px mobile widths, in dark and light
  palettes. The 375px document measured exactly 375px wide with no horizontal
  overflow, including the long search log and open quote panel.
- Verified citation click, native keyboard activation and Escape, disclosure
  keyboard toggling and `aria-expanded`, partial-gap handling, all seven statuses,
  disclaimer placement, and source `target`/`rel` attributes.
- The browser DOM contained zero script/image elements within the report even
  while displaying their literal markup in the quote. It contained no links
  with non-HTTP(S) schemes; the third source remained plain text.
- No live model or literature calls were needed for display testing. This work
  makes no new claim about research accuracy or clinical validation.

## Screenshots

All screenshots contain synthetic fixtures only.

- [Desktop citation](screenshots/research-reports/desktop-citation.jpg): dark
  desktop layout with an open exact-quote panel and source metadata.
- [Mobile citation](screenshots/research-reports/mobile-citation.jpg): open quote
  wrapping within a 375px dark layout.
- [Mobile light palette](screenshots/research-reports/mobile-light.jpg): the same
  literal HTML quote in the light palette at 375px.
- [Mobile urgent](screenshots/research-reports/mobile-urgent.jpg): emergency
  styling, explanation, and disclaimer without findings.
- [Verification details](screenshots/research-reports/mobile-verification.jpg):
  model/time metadata, bounded search log, and disclaimer in the mobile layout.
