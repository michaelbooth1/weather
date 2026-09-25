# Model lanes audit — 2026-09-25

- **Owns:** a read-only inventory of every forecast-model improvement lane, the missing paths the findings imply, what is
  stale or broken in the model pipeline now, and a ranked plan.
- **Read when:** choosing model work, before any model evaluation, or before re-arming training.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or measured results (digest, EF).

Auditor: Fable read-only subagent. The production agent verified the load-bearing serving claims (marked **verified**).

## Verdict

The programme is losing track of levers it already pulled more than it is missing levers. Four completed September research
results live only on unmerged workstation branches and are cited nowhere in canon. Two live serving facts contradict canon:
a June-fitted, in-sample afternoon centering stage runs 15:00-18:00 (**verified** `artifacts/misc/afternoon_residual_centering.json`
`enabled: true`, `start_hour 15`, `end_hour 18`) although EF §2 says not to implement a serving-side offset; and the
production forecast archive feeding the analog path has been frozen since 2026-06-23 (**verified**: newest file in
`data/forecast_history` is 06-23). The T+1/T+2 bands RE-1 quotes are not modelled at all (**verified**:
`src/weather/collection/snapshot_tracker.py:147-148` skips future-dated events).

## Lane inventory (condensed)

| Lane | Status | Next / blocker |
| --- | --- | --- |
| NBM parser L1 | landed `29e161e7d` | — |
| NBM L2 `abd648c7c`, L3 `cee879c45` | built, roll-sensitive | disk + quiet window; start the L2 forward clock on landing |
| NBM zero-parameter morning candidates (79a/81a) | reports landed; falsifier fired | post-fix dates; no numbered item owns the layers |
| 12-field PIT re-fetch (06-03..08-09) | staged in `C:\tmp`, never adopted | serving change (analog path) |
| 12-field seasonal challenger (research 09-02) | `INCONCLUSIVE_UNDERPOWERED`, **not in canon** | record it (UNVERIFIED by production agent) |
| Multiyear PIT corpora (13.8 M + 11.2 M rows, workstation) | branch-only, not in canon | record locations |
| Multiyear NWP-residual test + completion + replication | `INCONCLUSIVE_UNDERPOWERED`, not in canon | record; new test needs more year support |
| PIT v2 free-source contract | NO-GO, not in canon | closes "better free PIT source" |
| Identity binding | three unmerged generations (`4050f1ee`, v0.3 local, `42657a1f4`) | pick one; disk-gated merge |
| First retrain | on master, training DISABLED; no Sept-Dec corpus in any year | owner re-arm decision |
| Season archive window | code fixed; production data never re-fetched | data-only fetch but a serving change |
| Observation-envelope defect (`high_so_far` narrows) | candidate closed; defect still served | no owner |
| Train/serve parity gate | landed; fixture narrowing and `forecast_high` estimator skew owed | correctness backlog |
| Afternoon residual centering | **live, contradicts canon** | measure in isolation; disable if not earned (owner) |
| Settlement source (WRH vs hard-coded WU) | 86a undecidable; 359/360 band match | forward plan item 10, Q-09 |
| 95b signed band parser | built, roll-sensitive | next quiet window |
| Station obs (`wind_group`/`cloud_group` dead in F markets) | correctness owed | batch into one roll |
| Timing outputs (89b, 95a) | descriptive; T+0 only | forward plan item 6 |
| **T+1/T+2 horizon** | **does not exist** | missing path 1 |
| Learning lane / scoreboard | 95c merged; 09:30 run still stale; pause flag lands tonight | verify the 09-26 run |
| 95d universe | census only; no model or station history for new cities | owner disposition |

## Missing paths

1. **T+1/T+2 own-information fair value** for the bands the maker quotes: a zero-parameter NBM-percentile read (tomorrow's
   maximum is parsed correctly at every cycle, EF §10k) plus PIT lead-1 `forecast_high`, scored on 88a T+1/T+2 mids and
   settlements. No item exists. Owner decision (forward plan decision 5, "quoting without fair value").
2. **Record the September research results** (seasonal challenger, NWP residual + completion + replication, PIT-v2 NO-GO,
   corpus locations); fix EF §1g's "untested" sentence.
3. **The live afternoon cool shift**: measure in isolation from persisted stage snapshots; disable via `enabled: false` if
   it does not earn its place (serving change, owner).
4. **Forecast-archive re-activation** as a pre-registered forward shadow (replay cannot adjudicate, EF §1k).
5. **Autumn coverage**: every corpus has zero Sept-Dec rows; a free collection is the prerequisite for any retrain this season.
6. **Identity generation choice** before forward evaluations of served changes.
7. **Mission-id collision**: research 86a/87a/88a/89a/90a/100c/100i (Sept 2-4) reuse ids now used for other missions.

## Broken or stale now (and what it corrupts)

Replay ≠ served (corrupts any replay-scored B-stratum candidate: score against captured served output only); NBM
wrong-period rows before L2 (corrupt NBM features on 12/13/19Z cycles); WU labels vs WRH settlement (filter
`promotion_countable`); served HGB is June-fitted plus the afternoon shift (fine for "better than served", not "better than
the model"); identity unbound; archive frozen (third change co-located with the WU cutoff). Early-hour Brier trails the
market by 0.0230 on 1,137 market-days (point estimate, not crossed-clustered).

## Ranked plan (auditor's proposal)

1. Verify the 09-26 Stage A with the pause flag (learning PASS, `daily_learning.json` moves).
2. 95b, then NBM L2, then L3, one per quiet window as disk allows.
3. Docs mission (workstation, roll-free): record the September research results, the afternoon stage, identity generations,
   the id collision.
4. Pre-register the T+1 zero-parameter fair value; first look after 10-08 with panel B (owner decision).
5. Afternoon centering: bounded stage-snapshot export in the window, score on the workstation, pre-register disable if not
   earned (owner decision).
6. Trace `forecast_high=None` in the analog builder; if material, plan a re-fetch as a forward shadow (owner decision).
7. Pick one identity generation; queue after L3.
8. Autumn PIT collection (only if training may be re-armed this season; owner decision).
9. Batch correctness fixes for one later roll.
10. 95d: new cities get no model; any fair value there is zero-parameter free guidance.

Non-negotiables: crossed date×market intervals, pre-registration before scoring, no pooling across 2026-07-31, score only
against captured served output, never weaken the floor.

## Unverified

The research results' numbers (branches exist; reports not re-read by the production agent); whether 09-25's Stage A ran
95c code; effect of `forecast_high=None`; Brier effect of the afternoon stage; that workstation corpora still exist.
