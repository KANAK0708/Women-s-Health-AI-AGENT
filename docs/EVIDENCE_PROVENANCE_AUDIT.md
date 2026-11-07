# Evidence provenance audit — 7 November 2026

The checked-in manifest is a **development fixture**, not a clinically approved
evidence release. All seven source records now have `approval_status: unverified`.
Default local and PostgreSQL retrieval exclude them. Tests can opt into unverified
material only with an explicit development flag and must not use that mode for
patient answers.

The 18 stored passages read as summaries or composites. No source snapshot,
exact quotation comparison, section locator verification, signed clinical review,
or reuse-rights record accompanies them. Legacy `review_date`, `reviewed_at`,
publication/update dates, and section labels are **unverified assertions**. They
must not be displayed as proof of clinical review. The old `content_hash` values
could not be tied to canonical source snapshots or the stored passage collection;
they have been replaced with `UNVERIFIED`. The fake reviewer identifiers,
license assertions, and evidence grades have also been replaced with explicit
unverified values. Passage text is retained solely for reproducible software
tests and audit; no claim has been newly clinically endorsed.

| Manifest source | Audit finding |
|---|---|
| [Monash PCOS guideline page](https://www.monash.edu/medicine/mchri/pcos/guideline) | The page now discusses PMOS terminology and links to the 2023 guideline. The manifest's 2024 update date, chapter locators, paraphrases, and reuse terms need source-level verification. |
| [WHO PCOS fact sheet](https://www.who.int/news-room/fact-sheets/detail/polycystic-ovary-syndrome) | The current page is dated 22 January 2026; the manifest's 2025 publication date and passage wording do not establish provenance. |
| [NICHD menstruation topic](https://www.nichd.nih.gov/health/topics/menstruation) | This is a topic landing page. The manifest's four detailed section labels and combined self-care text need an exact supporting page and locator. |
| Legacy PCOS example.org record | Placeholder URL; already superseded and excluded. It remains only as a regression fixture. |
| ACOG dysmenorrhea record | The manifest's claimed 2024 clinical-consensus URL was not accessible in this audit. The [ACOG patient FAQ](https://www.acog.org/womens-health/faqs/dysmenorrhea-painful-periods) is a different document; it cannot validate the stored text or the claimed license. |
| [CDC heavy menstrual bleeding page](https://www.cdc.gov/female-blood-disorders/about/heavy-menstrual-bleeding.html) | The old URL redirects here. The current page is dated 15 May 2024, whereas the manifest says 10 April 2024. The detailed nutrition passage was not verified on that page. |
| [WHO endometriosis fact sheet](https://www.who.int/news-room/fact-sheets/detail/endometriosis) | The current page is dated 15 October 2025, rather than the manifest's 2023 date. The detailed lifestyle paragraph and its locator need verification. |

## Release procedure

For each source, capture the exact version and permitted storage/use terms; verify
canonical URL, date, jurisdiction, population, every passage and locator, and a
content hash of the captured snapshot. Record the qualified reviewer's identity,
review decision and date in an auditable approval system. Only then publish a new
manifest version with `approval_status: approved`. A URL, synthetic test flag,
model judgment, or legacy review field alone cannot authorize approval.

The current schema retains legacy date and citation fields to preserve
`RetrievalBundle` and downstream citation contracts. Any future removal or
redefinition of `reviewed_at` needs coordination with the tools owner, whose
`health_tools.handoff.adapt_retrieval` currently requires it.
