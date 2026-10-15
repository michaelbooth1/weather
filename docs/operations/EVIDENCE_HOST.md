# Evidence host (Data Layer v2 PL-1, PL-4, PL-5, PL-6)

Status: canonical. Owns the `WeatherEvidenceHost` supervisor, its per-family child
processes, the evidence journal layout under `data/evidence/`, the point-in-time
(PIT) reader and fetch-side embargo guard, and the first families (OB-1, OB-2,
OB-3, FC-1, FC-4, VR-3) and the S5 light batch lane (LB-1, VR-5). Read when running, registering, extending or reading the
evidence host, or adding a family to it. Family purpose, budgets and the build
sequence belong to [the Data Layer v2 plan](DATA_LAYER_V2_PLAN.md); the `platform`
registry row belongs to [the platform contract](DATA_LAYER_V2_CONTRACT.md). This
document grants no registration, run or trading authority:
[the state of play](STATE_OF_PLAY.md) does.

## What it is

One long-lived `python -m weather.evidence.host run` parent supervises one child
(`python -m weather.evidence.child --family <id>`) per enabled family in
`config/evidence_host.json`. Every request is a public, free, read-only GET
(AWC, api.weather.gov, HKO, JMA, ECCC, DWD, Open-Meteo metadata, Polymarket Gamma,
and for the light lane the Iowa Environmental Mesonet ASOS archive and the public
Polymarket data-api trades and CLOB prices-history routes).
The package imports no order, wallet, signing or credential module and reads no
`.env`; `tests/evidence/test_evidence_child_host.py` ratchets that, and that no
capture loop's static import closure reaches `src/weather/evidence/` (so every
change under it is roll-free; the roll verdict still decides each branch).

`weather.evidence` is outside the eight owner packages the import-architecture
ratchet parses ([package boundaries](package-boundaries.md)); it may import
`weather.operations`, `weather.market` and `maker_core` helpers, but nothing in
an owner package may import it.

## Journal layout (PL-1)

Paths below are illustrative; `data/` is ignored runtime state. The root is the
config's `root` (default `data/evidence`).

| Path | What |
| --- | --- |
| `<family>/<UTC day>/<hour>-<segment>/<partition>.jsonl[.gz]` | `rows` (one row per new or changed item, keyed per family), `heartbeat` (one row per poll: item count, changed, unchanged, batch hash) and `events` (start, stop, pause, resume, gap, cap, guard, warn) |
| `<family>/<day>/<hour>-<segment>/manifest.json` | seal: per-file records, bytes, sha256 of the gzip-6 content, torn-tail flag; written after the gzip is re-read and verified |
| `<family>/<day>/day_seal.json` | daily seal chained to the previous day by `prev_seal_sha256` |
| `<family>/status.json`, `<family>/ledger.jsonl` | PL-5 throttled status and one ledger row per sealed day |
| `cas/sha256/<prefix>/<sha256>.blob` | raw bytes stored once (MOSMIX KMZ, SWOB XML) and referenced by `raw_ref` |
| `identity/<sha256>.json.gz` | PL-4 code/config identity: `{path: git blob sha1}` for loaded repo modules and the config files |
| `host_status.json`, `kill_receipts/`, `control/` | PL-6 supervisor status, cap-kill receipts, `host.stop` and `<family>.restart` control files |

Segments roll at the hour and seal on roll, on stop, and on the next start after a
crash (open `.jsonl` folders are sealed first; first-seen state for the last
`STATE_LOOKBACK_HOURS` is rebuilt from sealed rows). One writer lock per family
refuses a second writer; a clock running backwards raises. A per-hour byte budget
(`hour_byte_budget_mib`) writes one `cap` row and drops the rest of that hour.
`weather.evidence.journal.verify_seal_chain` checks a family's chain.

Every row carries the envelope from `weather.evidence.envelope`: `first_seen_utc`,
`provider_time`, `run_init`, `availability_basis`, `parser_version`, `raw_ref`,
`event_date`, plus `config_sha256` and `code_manifest_sha`. Schemas are registered
in `weather/schema_families/evidence_host.py`.

## Reading: PIT and embargo

`weather.evidence.reader.read(family, as_of_utc, purpose, days=..., root=...)` is the
only reader. Purposes are `capture_check`, `outcome_join` and `candidate=<id>`.

- Rows with `first_seen_utc` after `as_of` are invisible to every purpose.
- Embargo windows come only from their code owners,
  `maker_core.shadow.admission.EMBARGO_WINDOWS` and `weather.mg1_reserved_window`.
  A FULL-window day refuses every purpose before any file is opened; an OUTCOME or
  MG-1 reserved day refuses `outcome_join` and `candidate=` and allows
  `capture_check`. A row whose `event_date` falls in a window is dropped on any day.
- For `candidate=` reads, `archive_proxy` and `stitched_no_issue` rows are refused;
  `provider_stamp` and `s3_lastmodified` rows need an explicit
  `pit_margin_seconds` and are tagged `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`.

Fetchers enforce the embargo too: `weather.evidence.embargo.embargo_guard` refuses
any `backfill` or `sweep` request for an embargoed event date and journals a
`guard` row; `live` mode refuses any event date older than yesterday (UTC).
`capture` mode (light-lane outcome-blind capture, per the contract's rule that
capture writes are allowed inside a window) refuses every FULL-window day
(`fetch_event_date_full_window`) and allows OUTCOME and MG-1 reserved days as
`allowed_outcome_blind_capture` with the scopes recorded.

## Families

`config/evidence_host.json` owns the channels, intervals, caps and budgets; read it
rather than a copy here. Each family module under `weather.evidence.families`
exposes `build(cfg, locations)` returning its channels.

- **OB-1 `ob1_metar`:** AWC METAR/SPECI first-seen log for every configured station
  (`metar_recent` each minute, required; hourly `metar_sweep`, optional). A
  400-result reply writes a `cap` row.
- **OB-2 `ob2_nws`:** api.weather.gov latest observations for the US stations.
- **OB-3 `ob3_native`:** HKO max/min and current readings, JMA AMeDAS, ECCC SWOB
  (only file names not yet journalled; raw XML to the CAS).
- **FC-1 `fc1_openmeteo_meta`:** Open-Meteo model run metadata, quiet 12:00-18:00,
  with a daily call meter; a 429 writes a `cap` row and stops the poll.
- **FC-4 `fc4_mosmix`:** DWD MOSMIX-L per configured station; KMZ to the CAS, rows
  keyed by issue time.
- **VR-3 `vr3_gamma`:** Gamma temperature events (journal only): active events
  every 15 minutes and a closed-event sweep 00:30-01:00 for days 2-4 back, each
  date through the fetch guard first. An active event dated inside a FULL embargo window is
  dropped before journalling (`embargo_full_dropped` in the heartbeat meta).

Adding a family: a module with `build`, a config block, schemas in
`weather/schema_families/evidence_host.py`, tests under `tests/evidence/`, and a
plan family id on the `evidence_host` row of `config/capture_families.json`.

## Light lane (S5)

`light_lane` in `config/evidence_host.json` lists one-shot tasks, each a module under
`weather.evidence.tasks` exposing `run(ctx, days=None)` and journalling under its own
family id through the same writer, fetcher, telemetry and guard as a child
(`weather.evidence.batch`). A `LightLaneSupervisor` thread inside the host starts
every enabled task once per host-local day inside `run_local` (00:30-01:00), one at
a time, each in the same kill-on-close Job with `ram_cap_mib` (at most 256) and a
wall bound `wall_seconds` (at most 600; the task stops itself 30 s earlier with a
`cap` row). A cap kill writes a kill receipt; a timeout is a `wall_bound_kill`.
The lane takes no workload lease and adds no scheduled task.

- **LB-1 `lb1_labels`:** shadow label panel, partition `label_panel`, one row per
  `location|local day|max-or-min` with `metar_all` (IEM routine and special
  reports, fetched as separate `report_type` 3 and 4 requests), `metar_hourly`
  (routine reports with a numeric SLP group; foreign cities resolve on
  `metar_all`) and the `ob1_finality_proxy` (`awc_proxy_of_wrh`: the OB-1 state
  when the next local day's first report was first seen). It writes no settlement
  label. Every UTC day a request touches passes the guard in `capture` mode; the
  re-read day journals a `cor` event where the proxy differs from `metar_all`.
  WRH (owner Q4): at most one `wrh_read` row per US station-day where `metar_all`
  and `metar_hourly` disagree at the degree, behind the strict `backfill` guard
  (every window refused). The WRH page renders through a page-embedded third-party
  token that no decision covers yet, so the row records `status=pending_route` and
  nothing is fetched until a route is ruled. Not built yet: WU daily, the IEM
  6-hour composite, 1-minute ASOS, CLI/CF6, HKO Daily Extract, ECCC climate-daily,
  the venue winner and the Stage-A read step.
- **VR-5 `vr5_trades`:** conditions from the VR-3 journal (`capture_check`) for the
  configured `location_ids` and event days 1-3 back, each guarded in `capture`
  mode. `trades` rows (data-api `/trades?market=`, paged) keep `proxyWallet`
  (public on-chain identifiers; owner Q3 = A) and drop profile fields; no `user=`
  filter is ever sent. `prices_history` (CLOB, 1-minute fidelity) covers closed
  markets only, once per token, raw reply to the CAS. Bounded by
  `max_requests_per_run`, the hourly request budget and at most 4 MiB/s.

`python -m weather.evidence.batch task --task <id> [--day YYYY-MM-DD ...]` runs one
task in-process (each `--day` still guarded); `python -m weather.evidence.batch run`
runs the lane once now under the same containment.

## Caps and pauses (PL-5, PL-6)

- Each child runs inside `weather.operations.long_job_guard.run_isolated_subprocess`:
  created suspended in a kill-on-close Job with a hard process commit limit
  (`ram_cap_mib`) before any user code runs, with `OPENBLAS_NUM_THREADS=1`.
  `WeatherMemoryCommitGuard` does not cover `-m weather.*` workers, so this cap is
  the only bound.
- A cap kill writes `kill_receipts/<stamp>-<family>-<hex>.json`
  (`evidence_kill_receipt_v1`); after `max_cap_kills_per_day` the family stays down
  until the next UTC day. Crashes back off from 5 s doubling to 300 s.
- The parent writes `host.stop` and exits if its own private bytes pass
  `parent_ram_cap_mib` (at most 64).
- The declared worst case (`declared_caps_bytes`) is the parent cap plus every
  enabled child cap plus the largest enabled light-lane task cap (tasks run one at
  a time); `host_status.json` reports it.
- Optional channels pause inside `optional_pause_local` (09:30-11:55, the Stage-A
  chain), when available memory is below `min_available_mib` plus the declared
  child caps, and on a red disk band; every channel pauses on a critical disk band
  or inside its own `quiet_local`. Pause and resume are journalled.
- `python -m weather.evidence.host kill-receipt` runs a deliberate over-cap child
  and must print `"killed": true`.

## Commands and registration

```powershell
.\venv\Scripts\python.exe -m weather.evidence.host status
.\venv\Scripts\python.exe -m weather.evidence.host stop        # children seal and exit; respawns exit 0
.\venv\Scripts\python.exe -m weather.evidence.host start       # removes the stop file
.\venv\Scripts\python.exe -m weather.evidence.host restart --family ob1_metar
.\venv\Scripts\python.exe -m weather.evidence.child --family ob1_metar --max-iterations 3
```

New code reaches a running family only through `restart --family` (owner Q11:
explicit restart; `status.json` reports running-vs-disk identity drift).
`scripts/ops/register_evidence_host.ps1` registers `WeatherEvidenceHost`
(S4U/Limited, idle priority, IgnoreNew, 1-minute respawn). Registering it on the
capture host is an explicit owner/production act; the repository change does not
arm it.

## Update when

Update when a family, channel class, journal file, envelope field, purpose,
embargo rule, cap or pause rule, light-lane task, CLI subcommand or the registrar
contract changes.
