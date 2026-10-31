# Data layer v2 platform contract

Owner of the data layer v2 **platform registry** (plan PL-3, built in stage S1): the
`platform` block of [`config/capture_families.json`](../../config/capture_families.json),
what reads it, and the ratchets that keep it true. The build sequence, family table and
budgets stay in the [data layer v2 plan](DATA_LAYER_V2_PLAN.md); storage semantics stay
in [data storage classes](data-storage-class-contract.md). This file holds no status.

## Registry shape

`config/capture_families.json` has three top-level blocks with separate readers:

| Block | Read by | Contents |
| --- | --- | --- |
| `families` | `weather.market.maker_evidence_family.load_family`, `weather.reporting.market.capture_family_status`, `register_maker_evidence_family_capture.ps1`, `status.ps1` | Passive capture families (see [passive maker evidence capture](passive-maker-evidence-capture.md#capture-families)). Unchanged by S1. |
| `core_recorder_only` | the core 88a recorder only (`weather.market.maker_evidence_pilot.load_recorder_only`, called by `weather.market.maker_evidence_capture` every cycle) | Data layer v2 S2 recorder-only rows (VR-1 pilot) and the S9 `rewards_sweep` switch; see [Recorder-only rows](#recorder-only-rows). |
| `platform` | `scripts/ops/roll_verdict.ps1`, `scripts/ops/staleness_sweep.ps1`, `scripts/ops/status.ps1` (health only), `tests/operations/test_capture_registry.py` | `roll_closures`, `evidence_families`, `storage_pending`, `embargo`, `contract`. Never selects, ranks or enumerates a market. |

`load_family` records the whole-file SHA-256 as `config_sha256` when a family recorder
starts, so any edit to this file (including the `platform` block) changes that value at
the recorder's next start. That is a provenance change, not a behaviour change.

### `roll_closures`

The capture closures whose recorded `runtime_identity.source_scope_files` decide a roll
verdict, in order. Fields: `id`, `status_path` (repo-relative, must match
`^data/[A-Za-z0-9_./-]+\.json$`, no `..`), `task`, `arming`, and for optional rows
`worker_status` and `writer_lock`.

- `arming: always` — the closure is always required; a missing or stale status is a
  verdict problem.
- `arming: while_armed_or_active` — required only while the task exists and is not
  Disabled, or its writer lock exists, or its worker status exists with a state other than
  `STOPPED` (an unreadable worker status counts as not active). The row must name its
  `task`; a row without one is malformed. Today only the execution tape.

Readers fail closed: an unreadable, empty or malformed list makes `roll_verdict.ps1`
print `UNDECIDABLE: capture closure registry unreadable: ...` and exit 1, and makes the
staleness sweep raise a `closure/registry` CRITICAL. Neither ever falls back to a
shorter list. `status.ps1` applies the same acceptance rule (`Get-CaptureRegistryHealth`) and,
when it fails, adds a `CAPTURE_REGISTRY:` WARN (not a flag: capture itself is unaffected) and
reports `capture_registry` in `-Json` output.

The rows reproduce the pre-S1 hand list exactly, including the retired
`clob-enrichment` closure (dropping it changes verdict output and is a separate reviewed
change). `tests/operations/test_roll_verdict_script.py` runs the pre-S1 script (frozen
byte-for-byte in `tests/fixtures/roll_verdict/`) and the registry script over the same
closure-evidence fixtures and requires identical output and exit codes. The one listed
exception (`STRICT_MODE_FIXED` there) is a sparse `{}` worker status: under inherited strict mode
the pre-S1 script threw on it and dropped the optional closure, while production (no strict
mode) required it; the registry script now requires it in both. An empty or absent runtime
identity in a closure status reports `no source_scope_files in <path> (runtime identity empty or
absent)` and drops that closure, so with no live closure the verdict is UNDECIDABLE.

### `evidence_families`

One row per running evidence producer: `id`, `plan_family` (plan family ids), `task`
(a `config/scheduled_tasks.json` name; `<PascalId>` expands through
`capture_family_status.task_name` for every family in `families`), `entry_module`,
`status_path`, `adoption` (how new code reaches the running process), `roll_class`,
`ram_cap`, `byte_budget`, `request_budget`, `embargo_scope`, `licence`, and `storage`
(example paths with the storage-classes `artifact_family` each must classify to).

Budgets are either `not_declared` or a reference: `module:SYMBOL` resolving to a positive
integer, or `families.<family>.<field>`. No number is copied into the registry.

### `storage_pending`

Paths the registry knows are unclassified or misclassified by
`weather.operations.storage_classes` today, with what they need. The list is
**shrink-only**: the ratchet fails when a pending path becomes correctly classified (delete
its row) and fails when any registered evidence or status path is unclassified and not
listed. Adding a pending row is a reviewed change.

## Recorder-only rows

The `core_recorder_only` block (data layer v2 S2+S9) names venue markets the core 88a
recorder captures beside the built-ins. It is read only from the default path inside
`maker_evidence_capture` (plan addendum 3: no task-argument change), re-read every cycle,
and its whole-file SHA-256 is stamped as `config_sha256` on every pilot universe row and in
`status.json` `recorder_only`.

- **Row:** exactly `id`, `location_id`, `series` (`highest` or `lowest`), `slug_prefix`
  (`<series>-temperature-in-<city>-on`), `tz` (IANA), `horizons` (`[0, 1, 2]`) and
  `band_policy` (`top10_reward_ranked`: the built-ins' top ten per city, three reserved per
  horizon); an optional `note`. At most `MAX_ROWS` rows (`maker_evidence_pilot`); a larger
  universe is a code change with re-derived RAM, REST and cap.
- **Built-ins are untouchable.** The 12 built-ins stay enumerated from `all_specs()`. A row
  naming a built-in id or location, a built-in slug prefix, or a `families` prefix is
  refused, so no config state can change the built-ins' selection. Owner Q16 (2026-10-15):
  pilot bands are outside the 10-01 maker-P&L pre-registration's 12-market stratum; every
  pilot row carries `stratum` to say so.
- **Journal isolation.** Every pilot read and event lands in a `pilot` partition
  (`discovery-pilot`, `ranking_books-pilot`, `books-pilot`, `rewards-pilot`,
  `rewards_current-pilot`, `universe-pilot-<id>`) and its public trades on the separate
  `pilot_trades` channel (`trades-pilot.jsonl`, one extra socket of at most 100 tokens).
  Pilot tokens never join the raw update stream. The built-in journals the shadow panel reads
  (`books`, `ranking_books`, `trades`) never hold a pilot token.
- **Failure scope.** A malformed block turns the pilot off for that cycle
  (`recorder_only.state = CONFIG_ERROR`, one `recorder_only_config_error` event per distinct
  error); a failed pilot cycle is `DEGRADED` with its own counters. Neither fails nor changes
  a built-in cycle. A red disk band switches the pilot off.
- **Switches, all config-only and landed off.** `pilot` (`on`/`off`, default `off`):
  rows are validated either way, captured only when `on`. `rewards_sweep` (`on`/`off`,
  default `off`): the VR-4 sweep; off, per-condition reward records fall back to the
  15-minute recheck. `built_in_reward_cadence` (`legacy`/`event_driven`, default `legacy`):
  built-in bands keep the pre-S9 every-minute reward read; `event_driven` takes effect only
  from `BUILT_IN_LEGACY_UNTIL` (UTC 2026-10-31T00:00Z, the end of the 88a panel hold) and is
  ignored before it (a scratch dry run excepted). An absent or malformed block means no
  pilot, no sweep and legacy built-ins. Switching on after verification is a config edit:
  no restart, the block is re-read every cycle.

## Embargo

The embargo windows have exactly two code owners, and the registry only names them
(`platform.embargo`); no date is written into the registry (the ratchet rejects any ISO
date in the `platform` block):

- `maker_core.shadow.admission:EMBARGO_WINDOWS` — full and outcome windows.
- `weather.mg1_reserved_window:window` — the MG-1 reserved range (D0 to a provisional
  last date that may only move later; the
  [reserved confirmation window](reserved-confirmation-window.md) owns the dating).

Every evidence family declares `embargo_scope: capture_outcome_blind`: capture writes
are allowed inside a window, reads of outcome content are not. The copy below exists so
readers of this contract see the windows; `test_contract_embargo_table_agrees_with_the_code_owners`
fails if it disagrees with the code owners (embargo-agreement ratchet). When a window
changes, change the code owner first, then this table.

<!-- embargo-table:start -->
| Owner | First day | Last day | Scope |
| --- | --- | --- | --- |
| maker_core | 2026-09-30 | 2026-10-15 | full |
| maker_core | 2026-10-15 | 2026-11-13 | outcome |
| mg1 | 2026-10-15 | 2026-11-28 | mg1_reserved |
<!-- embargo-table:end -->

## Ratchets

| Test | Fails when |
| --- | --- |
| `tests/operations/test_capture_registry.py` | the closure rows differ from the frozen pre-S1 list; a registered task is not in `scheduled_tasks.json`; an evidence or status path is unclassified (and not pending) or classifies to a different family than declared; a pending row is no longer pending; a budget or embargo reference does not resolve; the `platform` block holds a date; the embargo table above disagrees with the code; the existing `families` readers reject the file |
| `tests/operations/test_roll_verdict_script.py` | the registry script's verdict output or exit code differs from the pre-S1 script for any fixture shape, or an unreadable registry yields anything but UNDECIDABLE |
| `tests/operations/test_status_capture_registry_health.py` | status's registry-health check rejects the current registry or accepts a shape `roll_verdict.ps1` refuses |
| `tests/market/test_maker_evidence_pilot.py` | the built-ins' per-city selection differs with the pilot on, off, malformed or absent; a row can name a built-in or family market; a pilot read, file or token reaches a built-in journal; a pilot failure fails the built-in cycle |
| `tests/market/test_maker_evidence_rewards.py` | the S9 trigger reads a band outside first selection, a terms or sweep change, the stale recheck or the backstop; the cycle cap stops serving built-ins first; the sweep commits before its terminal cursor or raises; change-only rows lose their per-segment baseline; grouped fsync seals a journal it has not synced |
| `tests/operations/test_status_maker_evidence_code_identity.py` | status's running-vs-disk 88a code identity (owner Q11) misreports CURRENT, STALE or UNKNOWN, or the 88a-R restart helper acts without a verified core pid or touches the Scheduler |
| `tests/operations/test_staleness_sweep_script.py` | the sweep's closure list differs from the registry for any arming shape, or an unreadable registry is not CRITICAL |

## Redeploy

The platform block is read fresh on every run; nothing long-running imports it.

| Consumer | Adopts a change | Verify after landing |
| --- | --- | --- |
| `roll_verdict.ps1` | next invocation (on demand, including `quiet_window_merge.ps1`) | run it from the production checkout for a docs-only branch: same `closures:` line and verdict as before landing |
| `staleness_sweep.ps1` (`WeatherStalenessSweep`) | its next scheduled run | the first post-landing sweep has no `closure/registry` finding and the same `closure/*` rows as the last pre-landing sweep |
| `status.ps1` (`CAPTURE_REGISTRY` warn) | next status run | no `CAPTURE_REGISTRY:` warn; `-Json` shows `capture_registry.ok = true` with the five closure ids |
| family recorders (`families` readers) | next recorder start | `config_sha256` in the family status changes; no other field does |
| core 88a recorder (`core_recorder_only`) | its next cycle (a config edit); new **code** only by the explicit 88a-R restart (owner Q11) | `status.json` `recorder_only.config_sha256` equals the file's SHA-256; `status.ps1` shows `code CURRENT` |

## Registry finding (recorded, ids not changed)

S0(e) ([stations and licences](../research/data-layer-v2-s0-2026-10-15/s0ef-stations-and-licences.md))
found that `config/locations.json` WMO ids disagree with the DWD catalogue for Munich
(EDDM: 10866 in locations, 10870 in DWD) and São Paulo (SBGR: 83075 vs 83779), and that
Kuala Lumpur (WMKK), Chengdu (ZUUU) and Taipei (RCSS) have no DWD entry (DWD nearest
proxies 48647, 56187, 58968). S1 records this only; correcting an id is a separate
reviewed change, because the ids feed settlement-proxy and forecast lookups.

## Deferred from S1

- **`storage_classes` rows** for the supervisor status files and `maker_shadow` tapes (the
  `storage_pending` list). `src/weather/operations/storage_classes.py` is reached through
  deferred imports from the snapshot loop's closure, so editing it is not roll-free and
  needs its own verdict; S1 changes no `src/` file.
  The evidence host's `data/evidence` paths (S4) are classified instead in a commit stacked on
  S3, so they ride S3's roll-sensitive landing (`evidence_journal_segment`, `evidence_raw_cas`,
  and `operator_status_json` for status files and kill receipts).
- **`scheduled_tasks.json` rows:** none needed in S1 (every registered task already has a
  row, and the ratchet enforces it); the evidence-host task arrives with its stage.
- **Retiring `clob-enrichment`** from `roll_closures`.
