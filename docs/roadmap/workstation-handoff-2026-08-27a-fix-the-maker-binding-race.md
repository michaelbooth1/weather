# Workstation handoff 2026-08-27a — fix the maker scoring binding race

Run this now. **Repair and tests only: no fit, no retrain, no candidate, no scoring of held
candidates, no fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## A live production defect, found while checking lock readiness

The daily chain has been truncated since **2026-08-02**. `daily_refresh_status.json` recorded ten
steps and stopped:

```
market_day_labels_finalize   ok      <- step 4
maker_paper_score            error   <- step 9, chain dies here
```

```
RuntimeError: maker scoring input size_bytes binding mismatch:
data\mm_runs\2026-08-02\20260802T110502196750Z\quote_intents_long.csv
```

`mm_paper_scoring.py:463` `_validated_explicit_input_binding` demands **exact equality** on both
`size_bytes` and `mtime_ns` between the parent's captured binding and the isolated child's
revalidation. `WeatherMarketMakingDailyRoll` fires at **07:05** and appends to that day's
`quote_intents_long.csv`; the chain reads it at ~10:03. The file grew between capture (10:03:16) and
validation (10:04:07).

**A live-appending file cannot satisfy an exact-size binding.** This recurs every day.

## Why it matters far more than one MM step

`continue_on_error` does not help — `daily_refresh.py:1377` breaks the loop whenever the failing step
is in `STAGE_A_ISOLATED_STEPS`. Stage B then recorded `status=skipped, steps=0`.

So everything from step 10 onward has been dark: `settlement_source_audit`,
**`observed_floor_safety_monitor`** (which is on the release lock-day checklist),
**`clob_order_book_tiering`** (the disk lever), `settled_day_analysis_barrier`, `promotion_refresh`,
`data_retention_inventory`, **`daily_learning`**, and the rest.

The capture streak is unaffected — `market_day_labels_finalize` is upstream of the break — so this is
urgent but not an emergency.

## The fix I think is right, and the one I want you to challenge

Do **not** fix it by excluding the active day. `ACTIVE_DAY_EVIDENCE_MODE =
"active_day_live_forward"` includes the current day **deliberately**, for the MM live-forward gate.
Excluding it would silently retire evidence the MM track depends on.

My proposal is a **byte-prefix binding** for append-only active-day inputs: bind and then read
exactly the `size_bytes` captured at enumeration. The prefix is deterministic, reproducible, and
still fully hash-attestable — it just stops demanding that a live file never grow.

Challenge it before you build it. Specifically:

1. Is `quote_intents_long.csv` genuinely append-only under all writer paths, including the daily roll
   and any mid-day restart? If it can be rewritten or reordered, prefix binding is unsound and I want
   to know that instead of shipping it.
2. Does a truncated final line break `iter_csv_rows`? A byte prefix can land mid-row.
3. Is `mtime_ns` still meaningful under prefix semantics, or does it have to go?
4. Would a sealed snapshot-copy into the child workspace be safer than a prefix, and what does it
   cost in bytes on a disk-constrained host?

If your answer differs from mine, take yours and say why. I would rather be corrected here than
merge an unsound integrity check into the trading evidence path.

## Also in scope

The blast radius is its own defect. One isolated-step failure taking out fourteen unrelated
downstream steps plus the entire evening stage is the
`chain-fail-closed-blast-radius` problem in its most expensive form.

**Specify** — do not implement — what it would take for an isolated-step failure to fail *that step*
without truncating the chain. Which steps genuinely must hard-stop the pipeline, and which are
independent? I want the reasoning before any change to fail-closed behaviour, because fail-closed is
usually right and I am not going to weaken it casually.

## What I want back

1. The fix, with tests, on a branch off `master` @ `fbe0d93c`.
2. Your answers to the four challenges above, including any that killed my proposal.
3. A test that reproduces the race — a file that grows between binding capture and validation — and
   fails without the fix.
4. The blast-radius specification, as analysis only.
5. Which files you touched are roll-sensitive under `SOURCE_PATTERNS`.

## Constraints — unchanged

- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03 or 2026-08-06 → 08-19.**
  Fixtures and synthetic run folders only — do **not** read live `data/mm_runs` content.
- **Do not fit, refresh, backfill, or write any artifact, sidecar, prior, cache, or archive.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Merge timing is mine. Nothing roll-sensitive
merges on lock night, so this lands after the lock regardless of how quickly it is ready.
