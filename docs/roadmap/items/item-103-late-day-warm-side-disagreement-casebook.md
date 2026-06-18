# 103. Late-Day Warm-Side Disagreement Casebook [COMPLETE 2026-06-18 - WARM-SIDE CASEBOOK SLICE LIVE]

Goal: evaluate and improve late-day decisions where the model prices a warmer
band than the current high-so-far or the market, especially after source
redundancy is degraded.

Source: `docs/research/MODEL_LIVE_REVIEW_2026-06-16.md`. At the latest June 16
snapshot, NYC, Dallas, Los Angeles, San Francisco, and Seattle had model top
bands above high-so-far. NYC and San Francisco were the clearest model-market
disagreements, while Dallas had the weakest trust score among active F-family
markets. June 16 was not settled during the audit, so these should be reviewed
after settlement rather than labeled as misses immediately.

Why this is missing: the current replay reports identify aggregate candidate
gaps, but the live audit needs a same-day casebook for "can still get there"
late-day calls, with source-health context and post-settlement scoring.

## Design

Extend the existing disagreement casebook rather than creating a new artifact:

1. Add a `late_day_warm_side_cases` section to
   `data/backtest/disagreement_casebook.json`. It scans every snapshot group
   after 14:00 local time and captures rows where the model's top band is still
   above the live high-so-far.
2. Score each captured snapshot against three baselines when settlement is
   available: model top band, market top band, and the current-high lock-in
   band. Leave the same cases open when `settlement.json` or the ledger is not
   yet available.
3. Keep the grouping dimensions explicit in each case: local heating-window
   bucket, forecast-high gap, cooling trend bucket, source-freshness bucket,
   market-top disagreement, warm-bin distance, and coastal/marine context.
4. Build summary slices over one-bin and two-bin warm calls after 14:00 local
   time, split by source health and coastal/marine context. This supports the
   June 16 watch list immediately and converts to settlement scoring as soon as
   final labels land.
5. Render the slice in the Markdown report so same-day reviews can see which
   markets are open, which have settled, and whether misses are concentrated in
   coastal or marine-influenced markets.

- [x] Create a casebook slice for late-day snapshots where model top band is
  above high-so-far, grouped by remaining local daylight/heating window,
  forecast high gap, current cooling trend, coastal/marine context, source
  failure state, and market disagreement.
- [x] Add post-settlement scoring for NYC, Dallas, Los Angeles, San Francisco,
  Seattle, and any other captured market against the final winning bands. The
  current local June 16 folders have no settlement labels yet, so those cases
  remain open until `settlement.json` or ledger rows land.
- [x] Compare model, market, and current-high lock-in baselines for one-bin and
  two-bin warm-side calls after 14:00 local market time.
- [x] Add a late-day source-health interaction: separate all-fresh warm calls
  from calls made while Open-Meteo or other independent forecast sources are
  unavailable.
- [x] If warm-side misses concentrate in coastal or marine-influenced markets,
  route the findings into marine/lake-breeze feature work rather than applying
  a broad probability shrink. The casebook now exposes that interaction slice;
  no broad probability shrink was applied without settled evidence.

Acceptance: late-day warm-side model-market disagreements are settlement-scored
as a named slice, and future active-day reviews can say whether these calls are
real edge, underpriced continuation, or over-warm tail risk.

Implementation status (2026-06-16): `weather.reporting.disagreement_casebook`
now emits `late_day_warm_side_cases_v0.1` inside the normal casebook payload and
Markdown report. The slice is snapshot-level, starts at 14:00 local time,
captures model-top-above-high-so-far calls, and stores warm-bin distance,
forecast-gap bucket, cooling-trend bucket, source-freshness state,
market-top disagreement, and coastal/marine context. When settlement labels are
available it scores model-top, market-top, and current-high lock-in baselines;
without settlement labels it keeps cases open.

Verification:

- `python -m pytest tests/reporting/test_disagreement_casebook.py`
- `python -m pytest tests/reporting/test_disagreement_casebook.py tests/reporting/test_source_redundancy.py tests/sources/test_eccc_gridded.py`
- Live June 16 smoke with CLOB disabled found 191 open warm-side snapshots, 147
  with Open-Meteo unavailable, and 0 settled cases because no June 16
  settlement labels are present in the worktree yet.
