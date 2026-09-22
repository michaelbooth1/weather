# Workstation handoff 2026-09-86a — settlement truth after the source switch

Written 2026-09-22 by the production agent. Read-only measurement; no serving, training, label, config or
settlement-ledger change. Runs on the workstation in parallel with the RE-1 campaign and must not disturb it.

## 1. Why

EF §10c: around 2026-08-23 the venue's `resolutionSource` for the captured markets moved from Weather Underground
to `weather.gov/wrh/timeseries?site=<icao>` (same stations). Band agreement WU vs venue winner was 921/921 before
and 131/132 after, but **156 of 288 post-switch market-days have no WU label at all**, exact-degree agreement for
the 11 Fahrenheit markets is unmeasured, and nothing in `src/` knows the NWS source exists. Settled,
promotion-countable date volume is what the model work is starved of (digest items 6 and 10). If a free source that
reproduces the venue's winning band exists, those days are recoverable; if WU and the venue disagree at the degree
level, our training labels are wrong after 08-23. Either answer changes what the model track does next.

## 2. What to measure (all free, keyless, public; no paid source, no scraping around access controls)

1. **Candidate truth series per station-day**, for every captured market-day from 2026-07-01 to yesterday:
   (a) the existing WU label (`data/backtest/market_day_labels.csv` if present on the workstation, else say so);
   (b) IEM ASOS 1-minute maximum (`weather.sources.asos_one_minute`); (c) IEM METAR hourly/6-hourly maximum
   (`weather.sources.metar_history`); (d) `api.weather.gov/stations/<icao>/observations` where history reaches.
   Use each market's own local calendar day and native unit exactly as `MarketSpec` defines it. Record what the
   `wrh/timeseries` page itself is backed by if that can be learned from public documentation; do not call any
   undocumented endpoint or use a token embedded in a web page.
2. **Venue truth**: the winning band per market-day from the captured event metadata / reconciliation already in
   the repository (`config/location_market_events.json`, the settlement ledger); list its source.
3. **Agreement tables**, before and after 2026-08-23 separately: each candidate vs the venue winning band (band
   level), each candidate vs WU (exact degree, native unit, and signed difference), with counts, not rates alone.
   Name every disagreement (market, date, values).
4. **Recovery count**: how many of the post-switch market-days with no WU label would receive a label from the best
   candidate, and how many of those match the venue winner.
5. **Rules text**: whether the venue's binding Rules text for a current weather event names the NWS source
   (public Gamma event read; quote the sentence, retain the response hash).

## 3. Rules

- Branch `codex/settlement-truth-source-20260922` from `origin/master`; own worktree; commit a script under
  `tools/` (or a module under `src/weather/` only if it is reusable and tested) plus the report. Nothing adopted.
- Light network only: throttle to one request per second per host; cache responses under the worktree's ignored
  `data/`; never write to the RE-1 session worktree or campaign root.
- **Stop all network and heavy work before the owner starts RE-1 `live`, and while any `live` session runs**;
  no full suite before 19:00 ET 2026-09-22 (the scheduled 19:01 run on `475a626e4` owns that slot) and none during
  a live session. Focused tests only, through `scripts/ops/workstation_heavy.ps1` if heavy.
- No `.env` read, no credentials, no exchange mutation. Statistics: counts with denominators; say "not
  distinguishable" where it is; no model is scored (any candidate needs a pre-registration first).

## 4. Report

`docs/roadmap/agent-report-2026-09-86a-settlement-truth-after-the-source-switch.md`: verdict first in bold (one of:
a free source reproduces the venue winner at ≥ the WU rate and recovers N days / WU and the venue disagree at the
degree level on N days / undecidable, with why); the agreement tables; the recovery count; the Rules sentence; what
was NOT done. Hand back the branch tip. The production agent owns any EF/digest update and any adoption proposal.
