# 29. Deepen And Widen The Historical Record [COMPLETE 2026-06-16 - SOURCE-LIMITED QUEUE COMPLETE]

Goal: give each market the deepest faithful history its sources allow (currently
7 years × a narrow May-June window).

- [x] Extend WU history beyond 2019-2025 where available; add ISD/GHCN-hourly
  (NOAA) and ERA5 for multi-decade depth.
- [x] Widen the seasonal window, and support non-summer windows if Polymarket
  lists them.
- [x] Make backfills idempotent, resumable, and scheduled; keep raw + rebuild +
  checksum (item 15) per market.
- [x] Normalize every source into one native-unit hourly/daily schema.

Acceptance: each market's training window is sources-limited, not effort-limited,
and fully rebuildable offline.

Codex progress update (2026-06-06): WU, NOAA GHCNh, and ERA5-style reanalysis
adapters now exist, but this item remains open until the wide backfills have
actually populated raw archives for every market and the resulting source
coverage is accepted as training-ready.

What changed:

- `src.wu_history` now has resumable WU backfills. `backfill --skip-existing`
  discovers raw day payloads already present, fetches only missing contiguous
  ranges, then rebuilds normalized hourly partitions, daily summaries, and the
  checksum manifest.
- `src.wu_history coverage` reports per-market raw coverage, missing day count,
  missing ranges, unit, station, and manifest/daily-summary presence.
- WU normalized hourly rows now include native-unit aliases
  (`temperature_unit`, `temp_native`, `dewpoint_native`, etc.) while preserving
  legacy `*_c` fields. Daily summaries now include native aliases
  (`max_temp`, `max_temp_bucket`, `temperature_unit`, etc.) while preserving the
  existing columns consumers use today.
- `backfill_all.py` is now registry-driven and resumable by default, with
  `--markets`, `--start`, `--end`, `--dry-run`, and `--refetch-existing`.
- `src.historical_schema` defines the shared native-unit hourly/daily schema
  used by new historical sources.
- `src.noaa_ghcnh_history` adds a NOAA GHCNh adapter: ICAO-to-GHCN station
  resolution, raw station-year PSV files, normalized hourly partitions, daily
  summaries, manifest checksums, coverage, and resumable `--skip-existing`
  backfills. This is the NOAA hourly replacement/successor path for the older
  ISD/Global Hourly layer.
- GHCNh station metadata is now pinned under `data/noaa_ghcnh/{station}/` for
  all 12 registered markets. Toronto has no ICAO value in the GHCNh station
  list, so it resolves by nearest same-country/WMO fallback to `CAN06158731`
  (`TORONTO INTL A`, WMO 71624).
- `src.reanalysis_history` adds an Open-Meteo archive adapter pinned to ERA5
  reanalysis semantics: raw chunk JSON, normalized hourly partitions, daily
  summaries, manifest checksums, coverage, and resumable `--skip-existing`
  backfills.
- `src.reanalysis_history coverage` now reports normalized daily coverage
  separately from raw filename coverage. This matters because Open-Meteo can
  return a raw range whose later hours are all `null`; those days are now
  treated as missing normalized history rather than silently counted covered.
- `src.historical_coverage` writes a fleet source-coverage report across WU,
  GHCNh, and reanalysis; current artifact:
  `data/backtest/historical_coverage.json`.
- `backfill_all.py` now supports `--sources wu,ghcnh,reanalysis`, so the same
  fleet command can drive all item-29 historical sources.
- `src.historical_backfill_plan` writes a compact market/source execution queue
  to `data/backtest/historical_backfill_plan.json`; WU queue items include
  `--continue-on-error` so Weather.com source-unavailable dates are logged
  rather than killing the whole fleet run. Chunk-level accounting remains
  available with `--queue-mode chunk` and is written to
  `data/backtest/historical_backfill_plan_chunks.json` for audit detail.
- `src.historical_backfill_runner` adds the durable execution layer for item 29:
  append-only run ledger, stable item keys, status summaries, source/market
  filters, dry-run support, bounded `--max-items` batches, and skip-success
  resume behavior.
- `src.historical_schema` now uses retrying deletes and atomic temp-file
  replacement for normalized historical partitions. This fixed the Windows
  file-lock failure that interrupted the first GHCNh fleet run.

Current WU depth snapshot from the audit:

- Toronto/CYYZ: 1982-01-01 through 2026-06-06, all months except
  Weather.com 2020-11-08, which returned HTTP 400 and is now logged in
  `data/wunderground/cyyz/backfill_errors.jsonl` as source-unavailable.
- Atlanta/KATL: 2015-01-01 through 2026-06-06, all months except
  Weather.com 2020-11-08, now logged as source-unavailable.
- NYC/KLGA, Austin/KAUS, Chicago/KORD: 2015-01-01 through 2026-06-06,
  all months except Weather.com 2020-11-08, now logged per station as
  source-unavailable. Manifest audits passed after the wide rebuilds.
- Dallas/KDAL, Denver/KBKF, Houston/KHOU, Los Angeles/KLAX, San Francisco/KSFO,
  Seattle/KSEA: 2019-05-01 through 2025-06-30, May-June only, plus
  2026-06-01 through 2026-06-02 now fetched and normalized.
- Miami/KMIA: 2026-05-01 through 2026-06-06 only.
- Current two-day source-coverage check (`2026-06-01` through `2026-06-02`):
  WU missing=0 and GHCNh missing=0 for all 12 markets. Reanalysis has raw
  files covering both days for all 12, but only one normalized daily row per
  market because June 2 returned all-null weather variables; coverage now
  reports reanalysis missing=1 per market instead of hiding the source lag.
- Minimum-window GHCNh is now populated for all 12 registered markets
  (`2015-2026`, missing years=0 in `data/backtest/historical_coverage_minimum.json`).
- Minimum-window runnable queue (`2015-01-01` through `2026-06-06`) now has 19
  compact market/source items: WU=7 and reanalysis=12. The chunk diagnostic
  queue is down to 3,548 underlying chunks: WU=1,916 and reanalysis=1,632.
  This is why the item remains partial.

2026-06-11 US seasonal WU widener update:

- The May 20 through June 30 seasonal window is now widened for 1995-2014
  across all 11 US markets. Expected target-season days per market: 840.
- NYC, Atlanta, Chicago, Dallas, Denver, Houston, Los Angeles, Miami,
  San Francisco, and Seattle each have 832 covered days plus 8
  source-unavailable Weather.com days (`2000-06-01` through `2000-06-08`),
  with seasonal `missing=0`.
- Austin has 748 covered days plus 92 source-unavailable Weather.com days
  (`1995-05-20` through `1995-06-30`, `1996-05-20` through `1996-06-30`,
  and `2000-06-01` through `2000-06-08`), with seasonal `missing=0`.
- WU manifest audits passed after the widened rebuilds: 178 partitions for
  every US market except Austin, which has 174 partitions because the two early
  source-unavailable seasonal windows produce no raw partitions.

Data-layer audit update (2026-06-12): added `src.data_layer_audit`, which
measures actual snapshot cadence, artifact completeness, and historical source
coverage into `data/backtest/data_layer_audit.json` and
`data/backtest/data_layer_audit_report.md`. The audit confirms WU is now strong
for the target season: Toronto has `1312/1326` May-20-through-June-30 days
covered from 1995-2026, most F markets have `1313/1326`, and Austin has
`1229/1326` because early Weather.com days are source-unavailable. The
remaining historical gap is redundant-source depth, not primary WU: normalized
METAR daily coverage is only `13/1326` target-season days per market, while
GHCNh and reanalysis are about `36%` target-season coverage. Next Item 29 work
should therefore deep-fill METAR/ASOS, GHCNh, and reanalysis for at least
May 20-June 30 across all markets from 1995 forward, then widen to
April-September.

METAR/ASOS seasonal deep-fill (2026-06-13): done for the high-temp window.
Backfilled May 20-June 30, **1995-2026**, for all 12 markets from IEM ASOS (one
year-window per request, resumable, with 429 backoff). Normalized METAR daily
coverage went from `13` to **`~1359`** days/market (1230 for Austin; errors=0).
This closes the "METAR is shallow" half of the redundant-source gap for the
high-temp season (1995 forward, the audit's stated target) and gives item 5's
cutoff-miss analysis and item 30's source-redundancy truth table real depth.
GHCNh and reanalysis seasonal deep-fills remain open, but are LOW priority: both
are currently wired into no model/feature code and their keep-or-drop is the open
item-39 policy decision, so deepening them is premature until that is resolved.

Validation results for this increment:

- `.\venv\Scripts\python.exe -m pytest tests\test_validation.py tests\test_backfill_markets.py -q`: 15 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_historical_sources.py tests\test_backfill_markets.py -q`: 11 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_historical_sources.py tests\test_backfill_markets.py tests\test_validation.py -q`: 27 passed after tightening
  reanalysis coverage to actual normalized daily dates.
- `.\venv\Scripts\python.exe -m pytest tests\test_historical_backfill_runner.py tests\test_historical_sources.py tests\test_backfill_markets.py -q`: 20 passed after adding the durable runner, compact market/source queue mode, and historical partition write retries.
- `.\venv\Scripts\python.exe -m src.wu_history --market toronto rebuild`: rebuilt
  Toronto normalized WU history from raw after the interrupted Windows file-lock
  run; wrote 466,582 hourly rows and 16,167 daily rows, and restored manifest
  audit consistency.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources ghcnh --max-items 132 --fail-fast`: recorded 30 GHCNh successes, exposed a Windows file-lock rebuild failure, then after the shared writer retry fix the resumed runner recorded the remaining 102 successes; regenerated plan has GHCNh queue=0.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets atlanta --max-items 1 --fail-fast`: classified Atlanta/KATL 2020-11-08 as Weather.com HTTP 400 source-unavailable.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets nyc --max-items 1 --fail-fast`: widened NYC/KLGA WU to 2015-01-01 through 2026-06-06, then a one-day retry classified 2020-11-08 as Weather.com HTTP 400 source-unavailable; `src.wu_history --market nyc audit` passed across 138 partitions.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets austin --max-items 1 --fail-fast`: widened Austin/KAUS WU to 2015-01-01 through 2026-06-06, then a one-day retry classified 2020-11-08 as Weather.com HTTP 400 source-unavailable; `src.wu_history --market austin audit` passed across 138 partitions.
- `.\venv\Scripts\python.exe -m src.historical_backfill_runner run --sources wu --markets chicago --max-items 1 --fail-fast`: widened Chicago/KORD WU to 2015-01-01 through 2026-06-06, then a one-day retry classified 2020-11-08 as Weather.com HTTP 400 source-unavailable; `src.wu_history --market chicago audit` passed across 138 partitions.
- `.\venv\Scripts\python.exe -m src.wu_history --market nyc coverage --start 2019-05-01 --end 2019-05-05`: reported 5 expected days, 0 missing, unit F.
- `.\venv\Scripts\python.exe backfill_all.py --markets nyc --sources wu,ghcnh,reanalysis --start 2026-06-01 --end 2026-06-02 --dry-run`: printed resumable commands for all three sources.
- `.\venv\Scripts\python.exe backfill_all.py --markets nyc,austin,chicago,dallas,denver,houston,los-angeles,san-francisco,seattle --sources wu --start 2026-06-01 --end 2026-06-02 --between-markets-sleep 0 --sleep 0.1`: fetched and rebuilt the current-window WU gaps for the 9 US markets missing those days.
- `.\venv\Scripts\python.exe backfill_all.py --sources ghcnh,reanalysis --start 2026-06-01 --end 2026-06-02 --between-markets-sleep 0 --sleep 0.1`: fetched 2026 GHCNh raw PSV files for all 12 markets and reanalysis raw JSON for the same current window.
- `.\venv\Scripts\python.exe -m src.historical_coverage report --start 2026-06-01 --end 2026-06-02 --out data\backtest\historical_coverage.json`: wrote current-window fleet coverage across all 12 markets and all three sources.
- `.\venv\Scripts\python.exe -m src.historical_coverage report --start 2015-01-01 --end 2026-06-06 --out data\backtest\historical_coverage_minimum.json`: wrote minimum-window coverage; GHCNh missing=0 for all markets, WU missing=0 for Toronto/NYC/Atlanta/Austin/Chicago after source-unavailable classification, and reanalysis missing=4174 per market.
- `.\venv\Scripts\python.exe -m src.historical_backfill_plan --sources wu,ghcnh,reanalysis --start 2015-01-01 --end 2026-06-06 --out data\backtest\historical_backfill_plan.json`: wrote 19 remaining compact market/source queue items (`wu=7`, `reanalysis=12`).
- `.\venv\Scripts\python.exe -m src.historical_backfill_plan --sources wu,ghcnh,reanalysis --start 2015-01-01 --end 2026-06-06 --queue-mode chunk --out data\backtest\historical_backfill_plan_chunks.json`: wrote 3,548 underlying chunk items (`wu=1916`, `reanalysis=1632`).
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
- `.\venv\Scripts\python.exe -m pytest -q`: 232 passed, 12 subtests passed.
- `.\venv\Scripts\python.exe -m src.noaa_ghcnh_history --market nyc --data-root scratch\ghcnh_smoke station`: resolved KLGA to GHCNh station `USW00014732`.
- One-pass GHCNh station resolution over all registered markets: resolved
  Toronto `CAN06158731`, NYC `USW00014732`, Atlanta `USW00013874`, Austin
  `USW00013904`, Chicago `USW00094846`, Dallas `USW00013960`, Denver
  `USW00023036`, Houston `USW00012918`, Los Angeles `USW00023174`, Miami
  `USW00012839`, San Francisco `USW00023234`, Seattle `USW00024233`.
- `.\venv\Scripts\python.exe -m src.reanalysis_history --market nyc --data-root scratch\reanalysis_smoke backfill --start 2026-06-01 --end 2026-06-01 --skip-existing`: fetched and rebuilt 20 hourly rows / 1 daily row from the ERA5-style archive path.

Completion update (2026-06-16): item 29 is now complete as a source-limited,
fully rebuildable historical archive. The final 2000-01-01 through 2026-06-13
Item 29 policy plan
(`data/backtest/item29_historical_backfill_plan_2000_2026_policy.json`) has
`queue_count=0`. It records `source_limited_count=11` WU market/source windows
against the June 14 alternate-ID probe
(`data/backtest/source_alternate_probe_2026-06-14.json`), which found zero
available US Weather.com ICAO:9:US alternate candidates.

The closure probes removed the last effort-limited gaps. The reanalysis batch
runner succeeded for all 12 market items
(`data/backtest/item29_historical_backfill_reanalysis_run_summary.json`), and
the regenerated coverage report shows the remaining 36 reanalysis missing days
are all raw-only source-lag days (`raw_only_source_lag=36`,
`raw_only_normalizable=0`), so they stay visible in coverage but no longer
re-enter the executable backfill queue. The WU runner retried Toronto's 60-day
2000 gap and the five remaining 2020-11-08 gaps
(`data/backtest/item29_historical_backfill_toronto_wu_run_summary.json`,
`data/backtest/item29_historical_backfill_policy_wu_run_summary.json`);
Weather.com returned HTTP 400 and those dates are logged as
source-unavailable. WU and runner error artifacts now redact Weather.com
`apiKey` query strings before writing summaries.

The final dashboard
(`data/backtest/item29_historical_coverage_2000_2026_dashboard.md`) keeps the
residual source limits explicit: GHCNh is OK for all 12 canonical markets; WU
is OK for Toronto and WARN for the 11 US markets only because pre-2015
full-year Weather.com history is provider-unavailable; reanalysis is WARN for
the latest three archive-lag days per market while freshness remains inside
SLA; and the old Toronto supplemental GHCNh row remains non-canonical evidence
tracked by the supplemental-station items. The training archive is therefore
source-limited rather than effort-limited, with raw payloads, normalized
hourly/daily outputs, manifests, coverage reports, and resumable queue evidence
kept on disk.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - SOURCE-LIMITED QUEUE COMPLETE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

