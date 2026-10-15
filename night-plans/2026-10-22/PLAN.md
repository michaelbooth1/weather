# 10-22 night (2026-10-21 -> 2026-10-22): A9 leftovers, then DLv2 S2+S9

Workstation summary for master. Master lands; nothing here is a merge. Integration branches only.
The order was decided by master-agent on 2026-10-15 at 16:3x EDT, following the workstation's proposal.

## Order

1. **A9 leftovers first.** These are the units the 10-21 H-block did not finish before 03:15. It writes them to its
   10-22 leftovers file (plan `claude/o9-a9-plan-20261015`, r6 `6a27044f5`, §7). They run under the shared lease
   with the same 03:15 outer deadline. Anything still unfinished goes back to master; it is never stretched past 03:15.
2. **DLv2 S2+S9** via `scripts/ops/quiet_window_merge.ps1`, inside 01:00-04:00, and only once the lease is free.
   If there are no A9 leftovers, S2+S9 goes first. Get the verdict from `scripts\ops\roll_verdict.ps1 -Branch <b>`
   first; it is expected to be ROLL-SENSITIVE (88a recorder modules).
3. **Restart step: the following night, 10-23, 00:30-01:00.** First run
   `scripts\ops\restart_maker_evidence_capture.ps1` as a report, then run it with `-Apply`. The existing PT5M trigger
   restarts the recorder. Then `status.ps1 -Json` must show `maker_evidence_code` CURRENT. Never run
   `register_maker_evidence_capture.ps1`: it writes PT1M over the live PT5M.

Prerequisites: stack6 (10-18), then S1 `658592038`, then the roll_verdict fix `d69842131` must have landed first.
S2+S9 is based on S1.

## Head

| Branch | Sha | Notes |
| --- | --- | --- |
| `claude/dlv2-s2-s9-pilot-20261015` | `e2d48d849` | on S1 `658592038`; pilot ships DISABLED; built-in reward cadence per §Data hold |

## Data hold (until UTC 10-30)

The code freeze lapsed after 10-14. The data hold stays until UTC 10-30:
- add files only;
- never write to held segments;
- the 12 built-ins are enumerated from `all_specs()`;
- config adds recorder-only rows only.

Built-in reward-read cadence: **legacy (every minute) until 2026-10-31T00:00Z** (master's default).
No current reader of the built-in `/rewards/markets/<cid>` rows was found (panel reads books/trades only;
the shadow runner reads rewards from its own feed), but later analysis of the held capture cannot be ruled
out. `BUILT_IN_LEGACY_UNTIL` and the `built_in_reward_cadence` switch (default `legacy`) are in
`maker_evidence_pilot.py`; setting `event_driven` has no effect before the cutoff, so the flip after 10-30 is
config-only. A test pins the pre-S9 built-in cadence and record shape over 3 cycles.

Data-hold checks: appends only to the current segment; grouped fsync opens `O_WRONLY|O_APPEND` without
`O_CREAT` (tested); no held-segment writes (compression/maintenance unchanged from S1); built-ins from
`all_specs()`, config rows naming a built-in refused; config diff vs S1 is only the `core_recorder_only` block.

Isolation: real `capture()` loop with the pilot on, pilot cycle failure in cycle 1 and pilot trade-socket
close in cycle 2: 3 cycles, 0 failed; built-in discovery/ranking/reward/book reads every cycle; status shows
pilot `DEGRADED`. Ships `pilot: off`, `rewards_sweep: off`, `built_in_reward_cadence: legacy`.

## Pilot switch-on

This is a separate event from the code roll. It is a config-only change, made only after the 24 h verification:
- req/s ≤ 0.4;
- the latch fraction;
- no pilot token in the panel journals.

## Dry-run measurements (workstation, public endpoints only)

2026-10-15 20:41:36Z-21:43:43Z (62 min), pilot + sweep + event-driven built-ins on via the dry-run-only
`--recorder-only-config`, scratch root `l-data/s2s9-dryrun/scratch/run-20261015`, nothing under `data/`.

- 1,518 requests, all HTTP 200, zero 429s; 0.407 req/s overall, **0.374 req/s steady state** (budget 0.4).
  Steady state by endpoint: core books 0.085, pilot books 0.034, core rewards 0.107, pilot rewards 0.024,
  sweep 0.040, core Gamma 0.050, pilot Gamma 0.034.
- With shipped legacy built-in cadence (until 10-30) the built-ins stay at about 2 req/s, so the 0.4 budget
  is met only after the cadence flip.
- Sweep: 4 passes x 38 pages, 18,679-18,800 conditions per pass; 14-16% changed and 699-1,047 removed between
  passes (about 15 min apart).
- Bytes: pilot (5 cities, 72 tokens) about 4.3 MB per city-day gzip (gate <=10); sweep about 2.8 MB/day gzip
  (estimate <=10). Pilot trade socket about 6k messages / 3.9 MB per 5 min.
- **Open finding:** the run died on a Windows `PermissionError` in `atomic_json` replacing `status.json`
  (`maker_evidence_store.py:45-49`, unchanged from S1), most likely while a reader held the file. Production has
  the same exposure (a `status.ps1` or cockpit read at the wrong moment). Candidate fix: bounded retry on
  `PermissionError`; roll-sensitive 88a change, needs an owner decision. Not on this branch.
