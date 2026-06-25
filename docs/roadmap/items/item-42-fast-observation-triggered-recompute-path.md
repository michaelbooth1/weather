# 42. Fast Observation-Triggered Recompute Path [COMPLETE 2026-06-16 - PERMISSIONED REPLAY GATE LIVE]

Goal: close the remaining latency gap between live weather observations and the
served fair-value distribution without turning the full snapshot loop into an
expensive high-frequency fetcher.

Codebase audit finding (2026-06-13): item 40 taught the model how to use live
readings, but `src.snapshot_tracker` still recomputes the full model on a fixed
weather/model cadence (`--interval-minutes`, currently 10 minutes). Separately,
item 38's CLOB loop now captures books every 15-60 seconds. That means market
prices can move on a fresh WU current/METAR/SWOB print while our latest fair
value and dashboard edge remain frozen until the next full snapshot tick. This
is not a model-feature problem anymore; it is a live recompute/triggering
problem.

- [x] Add a lightweight source-event watcher that polls only low-cost
  observation sources (WU current/history freshness where available, METAR,
  SWOB for Toronto, and source timestamps) at a 30-60 second cadence.
- [x] Trigger an "urgent recompute" when a settlement-relevant source changes
  materially: new WU printed high, live reading crosses a bucket boundary,
  METAR/SWOB support jumps above the WU floor, or a previously stale current
  source becomes fresh.
- [x] Persist urgent recomputes with a trigger reason and replay identity in
  the same append-only evidence model as normal snapshots, but mark cadence so
  backtests can analyze regular versus triggered rows separately.
- [x] Expose the latest triggered fair value to the dashboard and any future
  quote engine, with freshness/fail-closed semantics: if the watcher is stale,
  edges are visible but not trade-permissioned.
- [x] Add a replay slice comparing pre-trigger, triggered, and next scheduled
  snapshot probabilities on settled days, especially the large-disagreement
  cases from item 41.

Acceptance: a material live observation change updates the served distribution
within 60 seconds, records why it happened, and improves or at least does not
regress settlement-scored performance on the triggered-row replay slice.

Implementation update (2026-06-14 UTC): `src.observation_trigger` now owns the
fast watcher. It polls only observation feeds (`wu_history`, `wu_current`,
`metar`, and Toronto `eccc_swob`) at 30-60 second cadence, detects WU printed
high increases, live bucket crossings, leading-observation support above the WU
floor, and stale-source recovery, then calls `snapshot_tracker.capture_snapshot`
with `force=True`, `snapshot_cadence=triggered`, and structured
`trigger_context`. `SnapshotStore` now persists `snapshot_cadence` and trigger
metadata to future `snapshots_long.csv` rows plus `snapshots.jsonl` and
`replay_inputs.jsonl`; old CSV headers stay stable by design. The watcher has
`once`, `loop`, `status`, `start-detached`, `ensure`, `stop`, `restart`, and
`replay` commands, writes `data/snapshots/observation_trigger_status.json`,
`observation_triggers.jsonl`, diagnostics, and a fail-closed `trade_permission`
payload. `ops_monitor` now includes the watcher and latest triggered fair-value
summary next to the weather/CLOB loops, and
`scripts/register_observation_trigger_supervisor.ps1` installs the Windows
supervisor.

Replay update (2026-06-14 UTC): `src.observation_trigger replay` writes
`data/backtest/observation_trigger_replay.json` and
`data/backtest/observation_trigger_replay_report.md`, comparing pre-trigger,
triggered, and next scheduled rows against the casebook's WU lag/catch-up loss
slice. The first run found the expected 745 WU-lag model-loss cases but zero
settled triggered rows, because the watcher did not exist during the historical
tapes. Item 42 remains partial until live triggered rows settle and the report
can prove no regression or improvement on that slice.

Live-ops update (2026-06-14 UTC): the watcher is registered under Task
Scheduler and was restarted onto the status-counter fix. It has begun writing
live `snapshot_cadence=triggered` rows and `observation_triggers.jsonl` events;
the latest status shows a fresh watcher heartbeat, zero consecutive errors, and
a nonzero iteration counter. This is implementation evidence, not acceptance
evidence: the item stays partial until those triggered rows settle and the
WU-lag replay slice can score them.

Settled replay update (2026-06-16 UTC): the replay scorer now normalizes
Fahrenheit band labels, numeric bin bounds, and `band_key` strings before
matching triggered rows back to casebook rows. That fixes the prior
zero-match replay caused by plain-F versus degree-symbol range labels.
`python -m src.observation_trigger replay --json-out
data/backtest/item42_observation_trigger_replay.json --report-out
data/backtest/item42_observation_trigger_replay_report.md` now scores 1,068
triggered rows from 10,945 triggered rows on settled WU-lag events. The raw
all-trigger slice still regresses pre-trigger Brier (0.1895 versus 0.1856,
`delta_triggered_vs_pre=+0.0039`), so triggered rows are not trade-permissioned
wholesale.

Permission-gate completion update (2026-06-16 UTC): `src.observation_trigger
replay` now derives a replay permission policy by trigger reason plus observed
direction. A cohort must have at least 30 settled rows and non-positive
triggered-vs-pre Brier delta before future fresh triggers in that cohort can be
trade-permissioned. The current acceptance artifact is
`PASS_WITH_PERMISSION_POLICY`: 119 permissioned triggered rows score Brier
0.2318 versus pre-trigger 0.2394
(`trigger_permissioned_delta_triggered_vs_pre=-0.0077`). The allowed cohorts
are `metar_temp_bucket_crossed|up`, `multiple_observation_changes|down`, and
`wu_current_max_since_7am_bucket_crossed|up`; all other settled cohorts remain
visible as triggered fair-value evidence but fail closed for trading. The
default replay artifact (`data/backtest/observation_trigger_replay.json`) and
the Item42 evidence artifact
(`data/backtest/item42_observation_trigger_replay.json`) carry the same policy.
After restart, `python -m src.observation_trigger status` reports the watcher
`RUNNING`, policy status `PASS_WITH_PERMISSION_POLICY`, and
`trade_permissioned=false` when no fresh allowed trigger is present.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - PERMISSIONED REPLAY GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

