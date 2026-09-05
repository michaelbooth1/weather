# Operator monitor

Status: canonical. The existing Streamlit Control Room and Roadmap are the
project and trading monitor. They observe evidence and expose no order, cancel,
credential, promotion or risk-setting controls.

## Launch and connect evidence

Use `scripts/launch/start_weather_dashboard.cmd` from a normal checkout with
its venv. The launcher binds to loopback, disables file watching and opens
`http://localhost:8501/?market=control`; `?roadmap` remains compatible.
An already-listening port is reused; restart the dashboard to change its inputs.
Remote/phone access requires a separately configured authenticated serving path.

Optional PowerShell launcher arguments:

| Argument | Meaning |
| --- | --- |
| `-RepoRoot` | Dashboard source checkout; defaults to the launcher's checkout |
| `-PythonPath` | Existing interpreter for an isolated worktree; defaults to that checkout's venv |
| `-DataRepoRoot` | Explicit repository whose `data/mm_runs` and `data/backtest` are observed |
| `-AttemptRoot` | One explicitly selected local portable attempt; never auto-discovered |
| `-CaptureStatusPath` | Explicit capture-host JSON observation instead of local collection |
| `-PortableStatusPath` | Public portable host-status JSON receipt |
| `-Port`, `-NoBrowser` | Local port and browser-opening preference |

The four evidence-source arguments map respectively to
`WEATHER_MONITOR_DATA_REPO`, `WEATHER_MONITOR_ATTEMPT_ROOT`,
`WEATHER_MONITOR_CAPTURE_STATUS`, and `WEATHER_MONITOR_PORTABLE_STATUS`.
They are server startup configuration, not browser inputs. Use absolute paths.
Do not point a workstation monitor at the frozen mirror as current evidence.
No credentials or attempt inputs need to be copied to the dashboard.

For a supplied capture observation, retain a timezone-aware producer timestamp.
`host_status_snapshot()` annotates its returned `payload` with `checked_at_utc`;
that payload can be retained as the supplied JSON observation. The legacy
minute-only `status.ps1` field `ts` alone cannot prove freshness after copying.
The portable host receipt already carries `checked_at_utc`.

## Observation contract

- Control Room refreshes every ten seconds while its browser session is active.
  Project context, run discovery and Roadmap refresh on a sixty-second cadence.
- On the assigned capture machine, a single server-wide background collector
  calls the canonical host diagnostic, with a sixty-second subprocess bound and
  five minutes between completed collections. Browser polls do not start duplicate
  diagnostics or wait for collection. Other hosts need an explicitly supplied
  capture observation. A collection error is visible, never an empty healthy host.
- The canonical host diagnostic records its normal disk-trend sample. The
  dashboard does not modify trading/session evidence, capture controls or Scheduler.
- Observation freshness uses timezone-aware producer time, never file/folder mtime.
  Missing, undated, expired, future and stale inputs are distinct. The general
  pilot checklist uses a ten-minute display horizon; account reconciliation uses
  sixty seconds. These display horizons do not replace executor freshness gates.
- Maker-run discovery reads at most 1,024 summary paths and parses the newest
  24 candidates. Readiness discovery is capped at 256 files. Exceeding discovery
  bounds yields no selected evidence. JSON reads are capped at 2 MiB per file.
  File mtime ranks bounded discovery candidates; it cannot make one current.
- Reports must match the selected run ID and target date. Accounting and exchange
  reports from different observation times are not combined. Recognized schemas
  are required for exchange/accounting and portable receipts.
- A copied historical result stays historical. Neither a zero count nor a finished
  session proves current account exposure. Unknown values render as an em dash.

## Portable session observer

For the selected attempt the reader examines only the three fixed stage paths:
`session/<stage>-run-intent.json`, `session/<stage>-run-receipt.json` and their
hash sidecars; Stage 1 `result.json` and `lifecycle.jsonl` under
`stage1-cancel-all` and `stage1-dead-man`. It never opens `inputs`, `incoming`,
credential files, manifests, launchers or exchange endpoints.

Receipt bytes must match their sidecars, stage and supported schema. A terminal
receipt must bind to the selected intent/candidate and portable profile, with
consistent start/finish times. These checks provide display integrity; the
observer does not rerun or substitute for the canonical execution validator.

A fresh launch intent is **LAUNCH RECORDED**, not proof that a process is running.
After its deadline, missing/invalid terminal evidence is **OUTCOME UNKNOWN** and
cleanup review remains visible. A finished result is labeled as historical.
Result fields are reported observations, not a fresh account query.

Journal reads take at most 128 KiB of trailing complete lines and show at most
100 events. Partial trailing writes are ignored until complete. Only known
scalar display fields are projected; arbitrary payloads and credential values
are not rendered.

## Results and project progress

The existing `exchange_reconciliation.json` and `mm2_pilot_report.json` own the
trade and financial observations. Orders, fills and positions are bounded to
100 displayed rows per family. Results show trading P&L, fees, paid maker rebates,
paid liquidity rewards and estimated fill rebates separately, in pUSD.
Paid incentives require the explicit paid-incentive schema, complete matched
credit reconciliation and verified cash basis. Net reconciled P&L stays unknown
until the report's financial reconciliation and cash identity are complete.
Estimates are never included in paid totals.

Project context comes from `STATE_OF_PLAY.md` and item 330 in the dashboard
checkout. The source commit and note date are visible; recent commits do not
establish runtime adoption. Roadmap's historical completion ratio describes the
whole repository, separately from current maker work and profitability.

## Update this file when

Update when source configuration, observation paths, reader bounds, refresh or
freshness policy, accounting presentation, access or launcher behavior changes.
