# 64. Canonical Settlement History Provenance Guardrails [NEW - AUDIT FOLLOW-UP]

Goal: make it impossible to silently blend nearby station data into canonical
settlement history.

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
The correct policy is: use validated nearby station roots as source-trust and
redundant-history features, retain source id and distance, and do not blend
them into canonical settlement history without provenance.

Tasks:

- [ ] Define canonical versus supplemental source roles in the historical schema
  and audit reports.
- [ ] Add reader/writer tests proving canonical daily summaries do not include
  supplemental station rows unless an explicit composite view is requested.
- [ ] Add a composite-view helper that exposes canonical + supplemental coverage
  as a separate artifact with lineage columns, never as the canonical CSV.
- [ ] Update backfill/rebuild commands so supplemental roots cannot target
  canonical output paths.
- [ ] Add a data-layer audit gate that flags any canonical source row whose
  source id/station id does not match the registered canonical station.

Acceptance: canonical settlement history remains a faithful record of the
market's resolution source, while supplemental history is available through
separate provenance-preserving views and features.
