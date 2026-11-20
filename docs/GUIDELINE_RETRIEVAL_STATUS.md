# Guideline retrieval draft and upstream overlap

The standalone `health_tools.guidelines` module is a tested offline prototype.
It has no approved clinical content and is not connected to the agent.
`health_tools/data/guidelines.json` contains candidate URLs only. Candidates are
never searched. The demo registry contains clearly marked synthetic fixtures.

```bash
python3 -m health_tools.guidelines "period diary" --jurisdiction TEST --population adults --as-of 2026-11-06 --demo
python3 -m unittest discover -s tests -v
```

Passages require a unique ID, source URL/title/publisher/version, exact text,
locator, SHA-256 text hash, jurisdiction/population/language, review status,
reviewer, review interval, rights status, and rights basis. Approval metadata
must come from an actual authorized review process; editing JSON is not clinical
validation. The hash detects accidental text changes, not malicious registry edits.
Only an approved, permitted, current, exactly scoped passage can be returned.
Review due dates are exclusive. Query ranking is simple lexical overlap, not a
semantic or clinical confidence score. Registry paths are trusted configuration.

During implementation, teammate changes were fetched at `origin/main` commit
`bbe4ed3`. They include `app/retrieval`, `app/schemas/evidence.py`, an evidence
manifest, and workflow changes as well as memory. These were inspected through
Git without merging. The standalone prototype overlaps with that retrieval work.

Before agent integration, choose one registry/schema and adapt to the existing
`HybridRetrievalEngine` rather than operating two independent clinical corpora.
Review source approval/rights, integrity checks, expiry handling, citation support,
and external-search fallback in the upstream workflow. Preserve separation between
PubMed research records and approved guideline passages. No duplicate retrieval
integration has been made in this branch.
