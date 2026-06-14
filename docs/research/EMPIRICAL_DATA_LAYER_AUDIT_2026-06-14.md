# Empirical Data Layer Audit - 2026-06-14

## Scope

This audit covers historical outcomes, redundant observation sources, forecast archives, live capture cadence, and CLOB market microstructure inputs for the 12-market weather fleet. Verification artifacts are in `data/backtest/`, especially:

- `data_layer_audit_2015_2026_after_backfill.md`
- `data_layer_audit_2000_2026_after_backfill.md`
- `historical_coverage_2015_2026_after_backfill.json`
- `historical_coverage_2000_2026_after_backfill.json`
- `metar_coverage_2015_2026_after_backfill.json`
- `source_redundancy_2026_06_01_13_after_backfill.md`

## What Is Now Covered

- WU settlement-style daily history is complete for every market from 2015-01-01 through 2026-06-13.
- GHCNh raw station-year coverage is resolved for 2000-2026 after recording source-unavailable station-years separately.
- ERA5/Open-Meteo reanalysis raw coverage spans 2000-01-01 through 2026-06-13 for every market.
- METAR/ASOS is expanded from target-season-only coverage to full-year 2015-01-01 through 2026-06-13 for every market.
- Open-Meteo forecast history now stores hourly long rows plus daily rows by source and issue-time basis, including previous-run lead-day forecasts from 2021 onward.
- CLOB capture now records price history and a short WebSocket event sample by default.

## Remaining Useful Historical Gaps

### 1. Pre-2015 WU Is Still Sparse Outside Toronto

For the 2000-2026 audit window, US markets still lack roughly 4,835 WU daily rows each. This appears to be provider/history-id availability, not just a skipped fetch. Reanalysis and GHCNh now cover those years, but WU remains the closest match to the historical settlement-style target.

Model value: better settlement-label consistency for older backtests and source-bias estimation.

Next best action: treat pre-2015 US WU as unavailable unless alternate Weather Underground station/history IDs can be discovered and validated.

### 2. METAR Before 2015 Is Not Broadly Backfilled

METAR/ASOS is now strong for 2015-2026, but the full 2000-2026 audit still shows about 50% full-year METAR coverage because 2000-2014 was not fully expanded beyond the target season. The adapter now supports chunked, throttled backfills, so this is operationally feasible.

Model value: independent intraday high progression, settlement floor features, and station-vs-settlement bias features across more regimes.

Next best action: run the chunked METAR backfill for 2000-2014, then quantify station-specific sparse days.

### 3. Toronto GHCNh 2000-2012 Is Source-Unavailable For The Resolved Station

The selected Toronto GHCNh station `CAN06158731` has 2000-2012 station-year files recorded as HTTP 404/source-unavailable. Coverage now excludes those from refetch queues and records them in manifest metadata.

Model value: Toronto older-year source redundancy remains weaker than US markets.

Next best action: evaluate alternate Toronto-area GHCNh/ECCC stations, then compare daily high bias against WU before adopting one.

### 4. Latest Reanalysis Days Are Raw-Only

Reanalysis raw payloads exist through 2026-06-13, but normalized daily rows stop at 2026-06-08. Coverage now reports these as `raw_only_days`, currently 2026-06-09 through 2026-06-13.

Model value: not a historical gap for training once archive lag clears, but it matters for automated daily refresh expectations.

Next best action: schedule deferred reanalysis refreshes for the most recent 7-10 days.

### 5. Forecast Raw Payloads And Provider Issue Times Are Still Partial

Open-Meteo historical forecasts are now richer by source and issue-time basis, but live forecast rows still often fall back to capture time when a provider issue/update timestamp is unavailable.

Model value: separates true forecast changes from provider update lag and stale-source behavior.

Next best action: persist raw forecast payload hashes/files plus provider-issued timestamps for Weather.com, NWS, ECCC, and Open-Meteo captures.

### 6. Legacy CLOB Microstructure Cannot Be Fully Reconstructed

Price history and WebSocket event sampling are now default going forward. Older snapshot days still lack full depth/event streams, and historical `/books` state cannot be reconstructed after the fact.

Model value: order-book imbalance, spread, depth, cancel/update intensity, and price velocity can explain edge decay near settlement.

Next best action: backfill whatever Polymarket price-history granularity is available for legacy tokens, and mark unreconstructable book/event features as missing rather than zero.

### 7. Source Status And Latency Are Not First-Class Training Rows

The audit still recommends `source_status_long.csv`: source id, ok/stale/error, fetched_at, payload age, latency, payload hash, and row counts.

Model value: lets the model learn when apparent signal is actually stale-source behavior or capture failure.

Next best action: emit source-status rows on every live capture and include them in replay inputs.

### 8. Live Snapshot Field Fill Is Uneven

The 2015-2026 audit still flags low fill for fields such as ECCC forecast/SWOB-derived columns, trigger metadata, and Gamma best bid. Gamma best bid is especially weak as a bid-side signal; CLOB book/WS data should be canonical.

Model value: avoids silently training on mixed-quality source columns.

Next best action: migrate bid/ask/depth features to CLOB captures and keep Gamma as metadata.
