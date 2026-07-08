# Chain Duration: Structural Fix Design (2026-07-08)

## Problem, measured

The daily refresh chain (42 steps, `weather.operations.daily_refresh`) is a single
~15–16h process in a 24h slot:

| Segment | Steps | Measured |
| --- | --- | --- |
| Settlement truth + gates | 1–22 (`reanalysis_recent_refresh` → `fleet_observability`) | 2.65h (dominant: `maker_paper_score` 77m, `closed_day_parquet_incremental` 32m, `public_wu_settlement_restore` 13m) |
| `promotion_refresh` | 23 | 4.14h (full 261-day corpus, candidate + current replay) |
| `active_variant_shadow` | 25 | 8.61h (14-date window = 154 market-days × ~10 contract-passes) |
| Learning + retention tail | 26–42 | ~1h |

Failures this class has already caused:

- 2026-07-04: silent chain death, whole analysis day lost.
- 2026-07-06: 16.6h run held the long-job lock through 03:30 (retrain LongJobBusy)
  and 09:30, and spanned midnight (broke date invariants).
- 2026-07-07: Task Scheduler killed the chain at the PT8H limit **mid
  `promotion_refresh`** — retrained model left unvalidated, no shadow rows for the
  day, MM starved next day on the `model_freshness` preflight (132 intents, 0 posted).

And it gets worse mechanically: the corpus grows ~+12 market-days/day and
`promotion_refresh` is full-history by design. At ~57s/market-day that is
**+11 min/day, +1.3h/week**; the chain crosses even the PT20H limit around
mid-August. Raising limits is not a fix; recomputation growth is the disease.

## Root cause

One process serializes two different kinds of work:

1. **Settlement truth** (labels, reconciliation, gates, trading evidence) — fast,
   time-critical, everything downstream depends on it.
2. **Evidence recomputation** (candidate/current/variant replays) — slow, and
   ~95% of it is *recomputation of unchanged inputs*: a market-day's pinned
   snapshots and settlement label never change after reconciliation, and the
   model artifacts change only on retrain nights.

A kill anywhere destroys everything after it; the lock couples the slowest step
to the retrain schedule; O(corpus) work is redone daily for inputs that are
immutable.

## Fix: three phases

### Phase 1 — Replay result cache (kills both duration and growth)

Both heavy steps already iterate per-market-day corpus folders and stamp
identity per row (`pooled_candidate_replay.py` iterates
`folders_from_manifest(...)`, stamps `candidate_artifact_hash`;
`execute_registry_prediction_exports` replays each registry contract over the
same folders). Cache each (market-day × model-identity) replay result and
aggregate from cache, replaying only misses.

**Cache key** (all parts already exist in the codebase):

```
(event_slug,
 inputs_fp   = sha256(pinned snapshot_ids + settlement label fields + admission fields),
 model_fp    = artifact_hash (candidate/current pkl) or variant contract fingerprint,
 config_fp   = sha256(row-affecting replay knobs),
 REPLAY_CACHE_SCHEMA_VERSION)
```

- `inputs_fp` comes from the corpus entry (`_entry_for_folder` pins exact
  `snapshot_ids`, settlement bucket/high, winning band, admission flags).
  Reconciliation retro-changes or newly pinned snapshots change the fingerprint
  → that day is recomputed. Correct by construction.
- `model_fp`: retrain produces a new `artifact_hash` → full replay for the new
  artifact once; every other day is a cache hit.
- Code changes are handled by an explicit `REPLAY_CACHE_SCHEMA_VERSION` bump,
  **not** the global source fingerprint (which changes on every edit and would
  nuke the cache daily). Forgotten-bump risk is covered by the sentinel below.

**Layout**: `data/backtest/replay_cache/<event_slug>/<consumer>__<model_fp12>__<inputs_fp12>__<config_fp12>.json`
holding the day's replay rows + per-day aggregate + full key metadata.
Write atomically (temp + rename). Size is trivial: the whole-corpus
`f_family_promotion_refresh.json` is 6.3MB, so per-day entries are ~25KB.

**Integration points** (two):

1. `run_pooled_candidate_replay`: before replaying a folder, probe cache; on
   hit, load rows; on miss, replay + write. Aggregation code is unchanged — it
   reduces over the same row structure.
2. `execute_registry_prediction_exports`: same probe per (contract, folder).

**Determinism sentinel** (guards stale-cache classes): each night, re-replay
one random cached market-day per consumer and byte-compare rows against the
cache. Mismatch → flush that consumer's cache, raise a P0 learning. This makes
an unbumped schema version self-detecting within a day.

**Dedupe bonus**: the 03:30 retrain's promotion validation replays the new
candidate over the full corpus — that populates the cache, so the 09:30 chain's
`promotion_refresh` cache-hits on the same `artifact_hash` and finishes in
minutes. Today those are two separate ~4h replays of identical work within
six hours of each other.

**Steady-state cost after Phase 1**: ~12 new market-days × all active
model-identities ≈ **~1h/day total** for both heavy steps, flat in corpus size.
Full-corpus cost is paid only once per new artifact (retrain nights, inside the
retrain's existing 6h budget).

### Phase 2 — Split the chain into two scheduled stages

Split exactly at the seam the 07-07 kill exposed (after step 22):

- **Stage A "settlement truth"** (steps 1–22): 09:30, PT4H, ~2.7h. Ends with
  the barrier already evaluated (step 20) and `fleet_observability` written.
  Writes a stage manifest (target date, barrier verdict, completed-at).
- **Stage B "evidence & learning"** (steps 23–42): with Phase 1, ~2–3h, PT8H.
  Registered as its own task (`WeatherEveningEvidenceRefresh`). Trigger:
  Stage A's final step fires `schtasks /run` on it (prompt start), plus two
  fallback time-triggers (14:00, 17:00) guarded by a start-gate that exits 0
  with a `skip_reason` when the Stage-A manifest for the target date is
  missing/stale or Stage B already completed for that date (IgnoreNew covers
  overlap).

Both stages and the retrain keep sharing the long-job lock — serialization is
preserved; nothing runs concurrently that doesn't today.

Existing machinery makes this cheap: `STEP_ORDER` slicing, resume filtering,
and `carried_forward_steps` already support running a tail with carried heads;
the incremental status flush and stage manifests give each stage its own
resume seed. `daily_learning`'s consistency checks were already redesigned
(2026-07-07) to anchor on artifacts (`_settled_analysis_anchor`), not run
identity, so consuming two runs' artifacts is compatible as-is.

**What failure looks like after the split**: a Stage B kill costs only Stage B
(rerun from `promotion_refresh`, ~2–3h, label truth intact); Stage A rerun is
2.7h; nothing spans midnight (done by ~15:00–17:00 daily), so the lock is free
at 03:30 by ~10 hours of margin and MM's `model_freshness` preflight is green
before its 19:30 roll.

### Phase 3 (optional, after 1+2) — Process isolation for the heavy steps

Run `promotion_refresh` and `active_variant_shadow` as child processes inside
Stage B (JSON-artifact handoff, WS cap via `SetProcessWorkingSetSizeEx` at
spawn through `long_job_guard`). The parent stays ~200MB; the July-3/July-6
memory-squeeze class (replay heap starving collectors) becomes impossible
rather than mitigated. The retrain already invokes promotion validation as a
subprocess; this applies the same pattern in-chain.

## Rejected alternatives

- **Keep raising ExecutionTimeLimit**: growth crosses any limit; a kill still
  costs the whole tail; PT20H (set 2026-07-08) is a stopgap only.
- **Parallelize the two replays**: the 16GB box can't — July-6 showed one
  replay + collectors is already the memory ceiling.
- **Window the promotion corpus** like shadow: promotion gates are
  deliberately full-history; windowing weakens the promotion evidence base.
  The cache achieves the same cost profile without discarding history.
- **Move heavy replays into the 03:30 retrain**: concentrates all heavy work
  in one window; a kill there starves both learning and validation.

## End-state daily timeline

```
09:30–12:10  Stage A: labels, reconciliation, gates, trading evidence, barrier
12:15–15:00  Stage B: delta replays (cache), scorecards, daily_learning, retention
15:00        MM/taker preflights see fresh model artifacts (roll 19:30 / 00:05)
03:30–07:00  Retrain: integrity gate → experiment queue → retrain →
             full-corpus validation of new candidate (populates cache)
09:30 next   Stage B promotion_refresh cache-hits the new artifact — no duplicate 4h replay
```

## Rollout

1. **Cache write-only soak** (1–2 days): replays write cache, aggregation still
   from fresh compute; sentinel compares cache vs computed. Proves determinism.
2. **Read path on for `promotion_refresh`**: assert aggregate equality vs the
   soak baseline (delta_vs_market identical), then keep the sentinel nightly.
3. **Read path on for shadow contracts.**
4. **Stage split**: second task registration + stage bounds + run-trigger +
   start-gate + tests (registry/resume tests already cover slicing semantics).
5. **Subprocess isolation** (Phase 3) when convenient.

Reversibility: every phase is flag-gated (`--replay-cache=off`, single-task
mode retained); the cache directory is disposable at any time (worst case =
today's full recompute).

Retention: fold `replay_cache/` into `data_retention_inventory` — prune entries
whose (event_slug, model_fp) is no longer referenced by the corpus manifest or
the active variant registry.

## Risks

| Risk | Handling |
| --- | --- |
| Stale cache after unbumped schema change | nightly sentinel re-replay + flush + P0 learning |
| Cache corruption / partial write | atomic rename; unreadable entry = miss (fail-closed recompute) |
| Retro label/snapshot changes | `inputs_fp` from pinned snapshot_ids + label fields — changed day recomputes |
| Retrain and chain writing same key | atomic rename, identical content, last-writer-wins is a no-op |
| Stage B never triggers | dual fallback time-triggers + skip markers surfaced in `daily_learning` input coverage |
| Disk growth | ~25KB/day/model-identity; retention-pruned |

## Effort

- Phase 1: ~1–2 days (cache module + 2 integration points + sentinel + tests) — **do first, it removes the growth bomb**
- Phase 2: ~1 day (task registration, stage bounds, start-gate, tests)
- Phase 3: ~1 day, independent
