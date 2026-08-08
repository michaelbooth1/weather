# Taker paused and pruned — 2026-08-07

**Operator decision: focus 100% on the market maker.** The taker bot is stopped, its scheduled
tasks are disabled, and its run tree was pruned. This records exactly what was deleted, what was
deliberately kept, and the one policy step that was bypassed.

## What changed

| | Before | After |
| --- | ---: | ---: |
| `data/taker_runs` | 26.67 GB / 5,379 files | **7.51 GB / 905 files** |
| C: free | 111.7 GB | **130.4 GB** |
| Taker resident memory | 710 MB | **0** |
| `WeatherTakerBotDailyRoll` / `…Supervisor` | Ready | **Disabled** |

Daily burn drops from ~13.8 GB/day to ~11 GB/day, so headroom goes from ~8 days to ~12.

## The premise was wrong — it was never 74.7 GB

`workstation-disk-and-mirror-scope.md` and the roadmap both carried **74.7 GB**, measured
2026-08-03. The tree was **26.67 GB** when measured on 2026-08-07; roughly 48 GB had already gone
by some other path. **Re-measure before planning a cleanup around a quoted number.**

## What was deleted, and why each was safe

1. **`incremental_state.sqlite3` + `-wal` — 195 files, 6.27 GB.**
   `storage_classes.py` classifies these as `taker_incremental_checkpoint` /
   **`ANALYSIS_PROJECTION`**, `rebuildable_taker_incremental_index`, rebuild source "append-only
   taker orders and counterfactual CSV tapes". Code-owned classification, not a judgement call.
2. **`_quarantine` trees — 45 dates, 4,278 files, 12.86 GB.**
   Quarantine is where `quarantine_unhealthy_taker_run_folder` moves a run whose
   `artifact_health` is **not ok** — retired, incomplete runs, moved out of the active path on
   purpose. **Verified empirically that no reader can see them**, rather than inferred:

   | Reader | Sees | Of which quarantined |
   | --- | ---: | ---: |
   | `trading_evidence.py` (`*/*/run_summary.json`) | 55 | **0** |
   | `settled_day_root_cause.py` (`<date>/taker-*`) | 54 | **0** (536 hidden) |

   536 of 590 run folders were quarantined. Both readers see **exactly the same counts after the
   deletion as before it.**
3. **3 orphaned `run_summary.json.*.tmp` — 20 MB.** Interrupted atomic writes.

## What was deliberately KEPT

Everything else under `taker_runs` is classified `taker_run_evidence` / **`CANONICAL_EVIDENCE`**,
`permanent_taker_strategy_evidence`, *"not rebuildable because fills, account snapshots, and
decisions are live-only"*, behind a `canonical_evidence_review_gate`. That is the live record of
what the taker actually did and **it was not touched** — including
`counterfactual_orders_long.csv` (4.06 GB), which an earlier note wrongly described as
free-to-delete replay tape. **The code-owned classification wins over that note.**

Deleting the remaining 7.51 GB is available but it is a one-way door on live-only data, and it
would take the two readers above to zero. It needs an explicit decision, not a cleanup.

## Policy step bypassed — stated plainly

`data-retention-policy.md` says *"Do not delete `snapshots`, `mm_runs`, `taker_runs` … unless a
reviewed cleanup manifest names the exact files"* and requires
`python -m weather.operations.cleanup_preflight --manifest <cleanup.json>`. **That manifest
workflow was not run.** The operator authorised the cleanup directly. What replaced it was: the
code-owned storage class for every deleted family, and a before/after reader count proving no
consumer lost an input. **If this is repeated, use the manifest.**

## Restarting the taker

Re-enable `WeatherTakerBotDailyRollSupervisor` **and** `WeatherTakerBotDailyRoll`. Nothing else was
changed — no config, no code, no strategy registry. The supervisor rebuilds
`incremental_state.sqlite3` from the CSV tapes, so the deleted checkpoints cost only rebuild time.
Note that the **CSV tapes for quarantined runs are gone**, so those specific runs are not
reconstructible — they were unhealthy and unread, which is why they went.
