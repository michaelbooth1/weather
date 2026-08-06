# Release #1 — lock evidence, 2026-08-04

Recorded **2026-08-04 18:50 EDT / 22:50 UTC** on the production host, by the operations master
agent, with the operator present.

`data/` is gitignored, so **this committed file is the lock record.** The canonical artifact at
`data/backtest/release_admissibility/clock.json` is not version-controlled.

## Both clocks read 14, from the same start date

### Operational capture clock — `scripts\ops\streak.ps1`

```text
TORONTO CODE-SOAK STREAK: 14 / 14 contiguous complete days
  day 1        : 2026-07-21
  most recent  : 2026-08-03  (complete)
  CAPTURE CLOCK FULL: 14 contiguous complete days. This is necessary,
  NOT sufficient -- run the PIT preselection to find out if the window
  is actually admissible (strict-readability is a separate gate).
```

### Release-admissibility clock — `release_admissibility_clock grade-range`

Run over `2026-07-21 → 2026-08-03`, `--ledger-root data/settlements`, `--snapshots-root
data/snapshots`:

```text
contiguous_pass_days : 14
streak_start_date    : 2026-07-21
as_of_date           : 2026-08-03
latest_status        : PASS
latest_reason_code   : release_admissible
receipt_count        : 14
market_id            : toronto
clock_sha256         : 462ae2d4ffb5cf1cd5c5dc4075959d15f3f1b6f68e97c7431f442f4dcc39befb
receipt_set_sha256   : 11ad5c85360f069bf71eed3e6758ce135f46ef6afd20bdaa5c37be21ca8b36c7
```

**All 14 receipts `PASS` / `release_admissible`, with no exceptions** — including `2026-07-24`, the
repaired lost write.

For continuity, the same command at 13 days on 2026-08-03 21:42 gave
`clock_sha256 152d8ddd…`, `receipt_set_sha256 776a5845…`, `receipt_count 13`. Both hashes changed as
expected on the 14th receipt.

**The two clocks agree at 14 from `2026-07-21`. The lock condition is met.**

## Fleet coverage across the 14 locked dates — one shortfall, recorded not smoothed

| Date | markets | complete |
| --- | ---: | ---: |
| 2026-07-21 | 12 | **11** |
| 2026-07-22 … 2026-08-03 (13 dates) | 12 | 12 |

The single shortfall is **Miami on `2026-07-21`**:

```text
market_id           : miami
quality_grade       : partial
quality_reason      : collection coverage incomplete: 1 gap(s), max 15 min
max_gap_minutes     : 15.2965557
snapshot_count      : 156     capture_ratio : 1.083
promotion_countable : True
settlement_source   : daily_summary
```

`2026-07-21 11:23` is when the host suffered its most recent unclean shutdown, which is also why the
streak starts that day. The gap is almost certainly that event.

**It does not affect the lock.** Both clocks are Toronto-scoped and Toronto is `complete` on 07-21
(191 snapshots, capture_ratio 1.33).

> ### RETIRED 2026-08-04 23:35 — this was not a build risk
>
> This section originally read *"Verify F-family admission of `2026-07-21` before spending build
> time. Preselection is its own verifier (§7b), so §3a run first will answer it."* **Both halves of
> that were wrong**, and they are corrected here rather than deleted.
>
> **1. §3a does not verify F-family coverage.** Runbook §7b splits the check: preselection's
> exclusion list covers the two *replay* defect classes, while pooled fit names an F-family coverage
> gap ~25 min in. §3a is Toronto-scoped and never reads a Miami folder at all.
>
> **2. A single market's `partial` cannot cause the refusal.** In
> `src/weather/calibration/pooled_feature_assembly.py`, `build_family_dataset` accumulates
> `available_target_dates` as a **union across every F market**, and `build_market_records` populates
> it at line ~798 *before* any grade filtering:
>
> ```python
> if _available_target_dates is not None:
>     _available_target_dates.update(
>         local_date.isoformat() for local_date in dates if by_date.get(local_date)
>     )
> ```
>
> The refusal at line ~914 (`pooled training corpus does not cover every preselected fleet date`)
> tests `included_target_dates - available_target_dates` — a **date-level** test, not a per-market
> one. `2026-07-21` is covered by the ten other complete F markets regardless of Miami. Miami's
> `partial` can at worst drop Miami's own rows.
>
> The original §7a-bis reasoning still holds and is the general rule: `build_family_dataset` computes
> live from settled market data, so a date is "missing" precisely until it settles. All 14 are settled.

## Preselection VERIFIED on the real window — 2026-08-04 23:31 UTC

Run as a **dry run to a scratch root** (`C:\tmp\preselect-dryrun-2026-08-04`), deliberately *not* to
the staged root — see the arming warning below. 14 Toronto folders, `2026-07-21 → 2026-08-03`.

```text
status  : PASS      elapsed: 1.02 min
lock    : fcb687e207acdc0cff3f4dfce549cb61a10002354d4ddb8d81cf5bdb89e02705
window  : 2026-07-21 -> 2026-08-03, window_days 14, missing_calendar_dates []
rows    : 29,062 accepted, market_days_read 14
labels  : settlement_label_authority.ledger_authority = 14  (no sidecar fallback)
replay  : entries 14, skipped 0
```

**`skipped: 0` — zero exclusions.** Replay defect classes 1 and 2 from §7b (duplicate pinned replay
identities, `too_few_replay_inputs`) are **clean across all 14 dates**, including `2026-08-02` and
`2026-08-03`, which mirror lag made structurally uncheckable from the workstation.

This is the first time production preselection has ever passed on real evidence; the rehearsal
reached only 13 days and correctly refused.

> **The dry run proves admissibility. It does not arm the build, and must not be reused as if it
> did** — the staged corpus is hash-bound to its own paths, and §3a requires the source be built
> inside the build window, not staged early.

### Arming is a side effect of the output path — know this before running §3a again

`training_window.ps1` is disarmed **only because
`data/analysis/point_in_time/production_source_2026-07-16` does not exist.** `WeatherTrainingWindow`
is `Ready` and fires at 01:00 nightly, aborting `0x2` on the absent root. Writing §3a's outputs to
that exact path plus a verifying staging receipt **arms the first real release build for the next
01:00**, unattended. Use a scratch root for verification; use the staged root only when a build is
actually intended for that night.

### Dated hazard — the window must never auto-extend past 2026-08-05

Reserved confirmation dates begin **2026-08-06** (`docs/operations/reserved-confirmation-window.md`,
the single source of truth). Reading a reserved date destroys it permanently. Any build run on or
after 2026-08-07 must pin `--window-end` explicitly; a window allowed to roll forward to "latest
settled" will begin consuming reserved dates. Dates through `2026-08-05` are unaffected.

## Repository state at snapshot

```text
HEAD          : 56771bb7  config: commit the scheduled location refresh drift
unpushed      : 0
git status    : 2 modified (config/location_market_events.json, config/locations.json)
```

The two modified files are the routine `WeatherLocationConfigRefresh` 6-hourly drift, which
accumulates roughly four times a day and is committed as a build step. **The tree was NOT clean at
the moment of this snapshot**, and the release build's clean-source-tree gate fails on its first
command unless it is — commit the drift immediately before starting a build.

## What this lock does and does not mean

- **Does:** the 14-day contiguous complete Toronto window exists and is release-admissible on both
  independent code paths. This is the gate that has never previously been open in this project's
  history.
- **Does not:** guarantee the window is *admissible to preselection*. `streak.ps1` says so itself —
  strict-readability is a separate gate and PIT preselection is the only thing that answers it.
- **Does not:** start the build. See §7a: multi-hour, ~71 min no-retry floor, never yet run past
  preselection on real evidence.

## Deferred deliberately

The observed-floor fail-closed flip (runbook §2 item 5) was **not** done — it requires a code change
plus re-registering both chain tasks, and it arms a new chain hard-stop. Full reasoning in
`release-one-floor-flip-deferred-2026-08-04.md`.
