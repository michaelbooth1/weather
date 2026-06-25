# Python And Runtime Log Audit - 2026-06-24

## Scope

Audit window: `2026-06-23T22:36:53.1966279-04:00` through
`2026-06-24T22:36:53.1966279-04:00`
(`2026-06-24T02:36:53.1966279Z` through
`2026-06-25T02:36:53.1966279Z`).

Repo root: `C:\Users\micha\Desktop\github\weather`

Scope covered Python under `app/`, `src/`, `tests/`, `tools/`, `scripts/`, and
`weather/`; runtime logs and status artifacts under `data/logs/`,
`data/snapshots/`, `data/backtest/`, `data/taker_runs/`, `data/mm_runs/`, and
`data/ops/`; and roadmap ownership under `docs/roadmap/ROADMAP.md`,
`docs/roadmap/active-backlog.md`, and `docs/roadmap/items/`.

## Commands Run

| Command | Result |
| --- | --- |
| `git status --short` | Clean at audit start. |
| `rg --files -g "*.py"` | 696 Python files: `app` 10, `scripts` 1, `src` 413, `tests` 237, `tools` 30, `weather` 1. |
| `.\venv\Scripts\python.exe -m compileall -q app src tests tools weather` | PASS. |
| `.\venv\Scripts\python.exe -m ruff check src\weather app tests tools scripts weather --select F821,F822,F823,F811,F841,E9,B012 --exclude venv --exclude artifacts --exclude data --output-format=concise` | FAIL: 118 findings (`F821` 69, `F811` 45, `F841` 4). |
| `.\venv\Scripts\python.exe -m weather.operations.daily_refresh status` | PASS command execution; latest status `ok`, generated `2026-06-24T08:17:51.772278+00:00`. |
| `.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status` | PASS command execution; loop running/current-code, but snapshot cadence proof `BLOCK`. |
| `.\venv\Scripts\python.exe -m weather.market.market_microstructure status` | PASS command execution; loop running, no consecutive errors. |
| `.\venv\Scripts\python.exe -m weather.operations.observation_trigger status` | PASS command execution; loop running, no consecutive errors. |
| `.\venv\Scripts\python.exe -m weather.operations.taker_bot_daily_roll status` | PASS command execution; current process alive, previous stale heartbeat run quarantined. |
| `.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status` | PASS command execution; process alive, but status runtime identity is stale relative to audit HEAD. |
| `.\venv\Scripts\python.exe -m weather.reporting.roadmap_backlog --fail-on-lint` | PASS after roadmap edits; regenerated `docs/roadmap/active-backlog.md` and `data/backtest/roadmap_backlog.json`. |

## Executive Summary

No P0 outage was found. The strongest uncovered issue is an audit-regression
gap: compileall is clean, but focused static checks and last-24-hour logs show
fresh Python runtime hazards in daily-refresh and Streamlit dashboard paths.
Those are now owned by new item 313.

The live collection stack is running and current-code, but its fleet cadence
proof still blocks all 12 markets. That is already owned by items 157, 161, and
307. The daily trading loops also still show the stale/hung process risk
described by item 312; item 312 was updated with the new maker/taker evidence.

Several scary console-log lines are historical disk/encoding incidents, not
current blockers. They should remain separated by item 306 log hygiene, while
current-window traceback ownership is folded into item 313.

## Findings

| Severity | Finding | Evidence | Current impact | Roadmap disposition |
| --- | --- | --- | --- | --- |
| P1 | Daily-refresh step code can hit undefined `utc_now()`. | `ruff F821`; `src/weather/operations/daily_refresh_steps.py:237` and `src/weather/operations/daily_refresh_steps.py:468` call `utc_now()` while the module imports only `date`, `datetime`, and `timedelta` from `datetime`. | `daily_refresh status` works, but a full run reaching reanalysis refresh or event-metadata validation can fail at runtime. | New item 313 created. |
| P1 | Single-market Streamlit dashboard has a current-window runtime exception. | `data/logs/streamlit_stderr.log` at `2026-06-24 13:51:12.363`; traceback at `app/views/single_market.py:682` with `UnboundLocalError` for `pd`; local `import pandas as pd` at `app/views/single_market.py:462` shadows the module import. | A per-market dashboard route can crash during live rendering. | New item 313 created. |
| P1 | Snapshot fleet cadence proof remains blocked for all markets. | `data/snapshots/loop_status.json`; `snapshot_cadence_proof.status=BLOCK`, `blocked_market_count=12`, `total_gap_count=24`, `max_gap_minutes=512.87`, root cause `unknown_snapshot_gap`. | Current live-forward evidence/trading permission remains blocked despite the loop now running current code. | Covered by active items 157, 161, and 307; no new item. |
| P1 | Bot daily-roll process-alive status is not enough to prove countable current-code evidence. | Taker status reported a quarantined previous run with `STALE_HEARTBEAT_METADATA`; maker status reported pid `34772` running commit `3242e26399be`/fingerprint `dc31a4c70a4f0228` while audit HEAD was `fb2da2283d88`. | A live bot can remain stale, hung, or non-countable until manual intervention. | Covered by item 312; item 312 updated with this evidence. |
| P2 | Exchange-economics target-date gate blocks current maker/taker paper evidence. | Recent maker/taker run summaries show `exchange_economics_gate.status=BLOCK` because verified date `2026-06-23` does not match target date `2026-06-24`. | Correct fail-closed behavior; zero quotes/trades are expected while the economics snapshot is stale. | Covered by completed items 300 and 309; no new item. |
| P2 | Source-family degradation still blocks one market from trading evidence. | `data/snapshots/loop_status.json`; source family degradation shows `metar` blocking one market and `trading_evidence_allowed=false`. | One-market source state blocks promotion/trading evidence even though model review remains allowed. | Covered by active item 136 and existing source-status gates; no new item. |
| P3 | Event-day manifest has an unresolved type annotation name. | `ruff F821`; `src/weather/operations/event_day_manifest.py:233` annotates `target_date: date | None` while importing only `datetime` and `timezone`. | Low runtime risk because annotations are postponed, but it keeps the high-signal static gate noisy. | Covered by new item 313. |
| P3 | Current-window console files still include historical disk/encoding failures. | `data/taker_runs/daily_roll_console.log` and `data/mm_runs/daily_roll_console.log` include older `No space left on device` and `UnicodeDecodeError` traces. | These are not current blockers, but they can confuse manual log audits if read without current-window status. | Covered by completed item 306; item 313 adds traceback signature ownership for future current-window audits. |

## Log And Status Health

Streamlit: `streamlit_stdout.log` shows the app serving on port 8501, while
`streamlit_stderr.log` has one current-window uncaught app execution traceback
for the single-market page.

Snapshot collection: the snapshot loop is running with `consecutive_errors=0`
and current-code runtime guard status, but fleet cadence proof is `BLOCK` across
12 markets. The status recommends
`python -m weather.collection.snapshot_tracker --restart`.

CLOB microstructure: `python -m weather.market.market_microstructure status`
reported the loop running, recent heartbeats/books, and `consecutive_errors=0`.

Observation trigger: `python -m weather.operations.observation_trigger status`
reported the loop running with no consecutive errors, but trade permission is
policy-blocked.

Daily refresh: latest status is `ok` and rollup freshness is `PASS`, but the
latest status is not proof that every full-run step can execute because
`daily_refresh_steps.py` contains an uncovered `utc_now()` dependency.

Taker daily roll: current process pid `9560` is alive and activity liveness is
passing, with `artifact_liveness.status=POLICY_NO_EDGE`; the previous stale
heartbeat quarantine is evidence for item 312.

Maker daily roll: process pid `34772` is alive, but the status artifact records
stale runtime identity commit `3242e26399be` while the audit HEAD was
`fb2da2283d88`. The latest run summary was preflight-blocked by the exchange
economics target-date gate, so no live-forward paper quotes should count.

Daily-roll console logs: old disk-full and encoding tracebacks were present in
current files, but the structured status artifacts separate current health from
historical incidents. This stays under item 306 unless a repeated signature
appears in the current window.

## Static-Check Summary

`compileall` passed, so there is no broad syntax/import-loader failure across
the audited Python tree.

The focused ruff profile failed with 118 findings:

- `F821`: 69 undefined-name findings. The highest-risk findings are
  `daily_refresh_steps.py` missing `utc_now()` and the `event_day_manifest.py`
  `date` annotation. Many `daily_refresh_cli.py` `F821` findings are caused by
  dependency-injected globals configured by `daily_refresh.py`; `daily_refresh
  status` and `daily_refresh --help` both executed successfully.
- `F811`: 45 redefinition findings, mostly in calibration compatibility or
  re-export-style modules. These need an explicit baseline or cleanup so real
  redefinitions are not hidden.
- `F841`: 4 unused-local findings in market/reporting/test paths. None was tied
  to a last-24-hour runtime failure, but they add avoidable audit noise.

## ROADMAP Changes Made

- Created item 313, `Python Runtime Audit Regression Gate`, for the uncovered
  daily-refresh/static-check/Streamlit/log-signature regression gap.
- Updated item 312 with current maker/taker stale daily-roll evidence.
- Updated `ROADMAP.md` with the item 313 primary row and this audit report link.

## Items Not Created

- No new snapshot-cadence item: items 157, 161, and 307 already own the current
  cadence proof block and restart-runaway stabilization.
- No new bot-supervisor item: item 312 directly owns stale fingerprints,
  hung/no-write loops, and auto-restart supervision for taker and maker.
- No new exchange-economics item: items 300 and 309 own the gate and snapshot
  workflow, and the current block is expected fail-closed behavior.
- No new historical-log item: item 306 owns separation of current-window health
  from archived disk/encoding incidents.
- No new source-family degradation item: item 136 and existing source-status
  gates already own source-state thresholds and degradation handling.

## Follow-Up Verification

After implementing item 313, run:

```powershell
.\venv\Scripts\python.exe -m compileall -q app src tests tools weather
.\venv\Scripts\python.exe -m ruff check src\weather app tests tools scripts weather --select F821,F822,F823,F811,F841,E9,B012 --exclude venv --exclude artifacts --exclude data --output-format=concise
.\venv\Scripts\python.exe -m weather.operations.daily_refresh status
.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker --status
.\venv\Scripts\python.exe -m weather.operations.taker_bot_daily_roll status
.\venv\Scripts\python.exe -m weather.operations.market_making_daily_roll status
.\venv\Scripts\python.exe -m weather.reporting.roadmap_backlog --fail-on-lint
```
