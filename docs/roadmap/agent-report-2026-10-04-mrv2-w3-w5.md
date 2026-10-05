# Agent report — 2026-10-04 maker replay v2 W3/W4/W5

**Verdict: W3, W4 and W5 are BUILT and pass every measured gate (all MEASURED) under the owner-approved rule 1
(2026-10-04): S3 PASS (runtime(250)/runtime(40) = 11.89 s / 2.05 s = 5.82 ≤ 7.5, linear), S5 PASS (0 divergences on
re-run), S7 PASS (report 1.9 MB, sidecar 408 MB per date at B = 170), S9 PASS (first run; no money path changed since),
S8 reported.** The first S3 run under "every book record wakes" was superlinear (11.0) and stopped the mission; the
owner then approved: a re-sent unchanged book is not an own event, but every book record refreshes the freshness clock.
That rule is now the engine's only behaviour (the diagnostic switch is gone), the reference schedule shares it, and the
DRAFT registration (§5 rule 1, C1) and engineering plan say so.

**Book change (exact):** `kernel.book_state(book)` = `(yes_bids, yes_asks, no_bids, no_asks, post_only_available)` of
the decoded book — every level of all four sides, each side merged by price, zero sizes dropped, sorted (bids high to
low, asks low to high), exact Decimal price and size. `as_of_utc` is excluded. A band wakes iff its `book_state` after
the instant differs from before it (an invalid book drops the state and counts as a change). **Freshness clock:**
`kernel.freshness_clock(state)` = the latest book record's `as_of_utc`; every valid book record, changed or not,
becomes the latest book and re-arms the gap timer (`as_of` + 60 s) without calling `decide()`. A re-fetch with a newer
`as_of` keeps a quiet book fresh; a silent feed, or a re-projection carrying the old `as_of`, goes stale on time.

Branch `codex/mrv2-w3-w5-20261004`, based on integration branch `codex/maker-replay-v2-build-20261003` at
`ae08de20` (origin had not moved). Spec: `docs/research/maker-replay-v2-engineering-plan-DRAFT.md` (W3–W5, S3, S5,
S7, S8, S9) and `docs/roadmap/agent-report-2026-10-03-mrv2-w0-w1.md`. W2 belongs to another session and was not
touched. Reserved confirmation window: NONE RESERVED (checked at run time). Fictional fixtures only.

## What was built (all new modules under `src/maker_core/replay/v2/`; no frozen file edited)

- `money.py` — C5: every portfolio amount is quantized to 1e-6 in a context that traps `Inexact`; an amount 1e-6
  cannot hold raises `MoneyError` (never rounds). Report quotients are rounded once (`round_once`).
- `kernel.py` — the frozen engine's ingest/print/tick logic behind hooks, with Session A's correction: re-entry after
  `INFO_PULL` reads the view's payload `as_of_utc`, and pull digests hash the latest payload SHA-256s; no capture time
  of an elidable record is read or hashed. Book capture time (never elided) is still read.
- `engine.py` (W3) — per-condition wakes: lazy per-band timers validated against current state on pop; record wakes
  by comparing each touched condition's record signature across the instant; coverage wakes only on a state change;
  exact running totals (reserve, inventory, per-event, per-factor, active-band count) with a debug recompute assertion
  (`RunningTotalsMismatch`) on every portfolio read; run-length intervals.
- `lockstep.py` — run plans, v0.1/v0.2 day sources, decode-once, group-record expansion to seen members, and one parse
  per day driving several engines.
- `reference.py` (W4) — the frozen loop restricted to the wake set: global instant heap, brute-force wake detection
  for every condition at every instant, recomputed portfolios, per-instant spans merged afterwards. Tests only.
- `score.py`, `pull.py`, `pipeline.py`, `report.py` (W5) — streaming band-day scorer (integer microseconds, exact
  sums, one rounding per band-day), compact midpoint series, the frozen pull endpoint read from intervals, base passes
  plus lockstep matched-clock rounds, and the per-cell report: cell sums, band-day table, frozen inference with
  k = 0.3, §12 small-cluster bound (`estimate − t(0.95, G−1) × SE`), Clarification 3 fields through the frozen
  `registered_decision`, and a hash-bound sidecar (merged excluded intervals, per-pass decision-stream SHA-256).
- Tools: `tools/research/maker_replay_v2/{sources,dense,bench}.py`; `run.py` gains `s3 s5 s7 s8 s9` (four added
  lines). `dense.py` is a quoting-dense fictional day, because `informed-v0` almost never quotes on W0's day.
- Tests: `tests/maker_core/test_replay_v2_engine.py` and `test_replay_v2_report.py` (25 tests), all with debug on.
  Digest-invariance test: **`test_decision_digest_invariant_under_coverage_regrouping_and_view_elision`** (v0.1
  per-condition coverage with repeats, v0.2 groups with repeats elided, v0.2 one group per condition: identical
  decisions, intervals, fills, cash); plus `test_reentry_and_pull_digests_ignore_a_repeated_views_capture_time`, which
  also shows the frozen engine's decisions do change on the same input.

## Measurements (MEASURED; fictional; fresh process each, serial, under `workstation_heavy.ps1 -Kind weather_heavy`)

Final results are at head `63d6c54c` code (rule 1 = book changes). Result SHA-256s are of each measurement's JSON.

**S3 — runtime vs B: PASS (linear).** W0 day, first 360 min, T = 2,000, one `informed-v0` strictly-through pass over
pre-decoded records, best of 3:

| B (union) | live bands (mean) | book records | wakes | wakes/band-min | pass s | µs/wake | traced peak/pass |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 40 | 31.0 | 11,148 | 25,329 | 2.27 | 2.05 | 80.7 | 3.8 MB |
| 85 | 64.8 | 46,268 | 49,968 | 2.14 | 3.77 | 75.5 | 7.1 MB |
| 120 | 92.6 | 66,300 | 70,765 | 2.12 | 5.22 | 73.8 | 9.9 MB |
| 170 | 127.7 | 137,976 | 100,018 | 2.18 | 7.96 | 79.6 | 15.8 MB |
| 250 | 186.3 | 268,880 | 142,877 | 2.13 | 11.89 | 83.2 | 19.2 MB |

Ratio 250/40 = **5.82** (≤ 7.5, and below the 6.25 band ratio). Wakes per band-minute are flat (2.1–2.3) although book
records per band grow with B. Under the earlier "every record" rule the same runs gave 2.49 / 5.79 / 7.02 / 14.58 /
27.49 s (ratio 11.0, wakes/band-min 2.27 → 5.06). SHA-256: `0e0f3f90…` (40), `50856869…` (85), `15390fa5…` (120),
`e4e2093d…` (170), `ec1d0728…` (250).

**S5 — v2 engine vs reference, re-run: PASS, zero divergences** (`d4b3ea02…`). B ∈ {12, 40, 170} × T ∈ {2,000,
20,000} × three windows (W0 90 min across the 04:00 UTC horizon roll; W0 90 min across 10:00 settlements; dense
30 min): 18 cases, 338,931 records, **349 engines compared (all 4 policies × both bounds) and 205 matched-clock
trials**, each on decisions, intervals, fills, cash, settlements, final legs, inventory, exclusions and the clock
match. The first run (old rule) also passed: 353 engines, 209 trials, 0 divergences. v2 ran 3.7–12x faster than the
reference at B = 170.

**S7 — scored report and sidecar per date at 170: PASS** (`d7754c8b…`). One full fictional day (821,681 v0.2 records,
union 170, 127.7 live), the whole pipeline: 8 base passes plus 10 matched-clock trials (both bounds MATCHED in 6
attempts), 579 s. Scored report **1,914,792 bytes** (limit 1 GiB/16 = 64 MiB). Sidecar **408,141,863 bytes**, 1,701,101
records (limit 8 GiB/16 = 512 MiB: within, at 76%). Registered decision on the fixture: UNDERPOWERED (one date).
Process peak 3.74 GB, of which 3.09 GB was the in-memory fixture before the passes.

**S8 — `informed-v0` quoted fraction, v2 schedule vs frozen loop (report only)** (`a2131149…`). W0 60 min from 10:00
and dense 10 min, strictly-through:

| fixture | B | T | v2 fraction (quotes) | frozen fraction (quotes) | v2 / frozen decisions |
| --- | ---: | ---: | ---: | ---: | ---: |
| w0 | 40 | 2,000 | 0 (0) | 0 (0) | 3,816 / 160,360 |
| w0 | 40 | 20,000 | 0 (0) | 0 (0) | 4,336 / 201,120 |
| w0 | 85 | 2,000 | 0 (0) | 0 (0) | 7,460 / 697,000 |
| w0 | 85 | 20,000 | 0.0001 (1) | 0.0001 (1) | 9,416 / 766,360 |
| w0 | 170 | 2,000 | 0.0003 (2) | 0.0003 (2) | 15,316 / 2,727,310 |
| w0 | 170 | 20,000 | 0.0012 (9) | 0.0004 (9) | 21,059 / 2,927,570 |
| dense | 40 | 2,000 | 0.0126 (4) | 0.0031 (5) | 719 / 100,400 |
| dense | 40 | 20,000 | 0.0026 (1) | 0.0005 (1) | 728 / 107,120 |
| dense | 85 | 2,000 | 0.0049 (1) | 0.0014 (5) | 1,573 / 447,355 |
| dense | 85 | 20,000 | 0.0012 (1) | 0.0002 (1) | 1,551 / 453,730 |
| dense | 170 | 2,000 | 0.0020 (2) | 0.0006 (4) | 3,099 / 1,771,400 |
| dense | 170 | 20,000 | 0.0038 (2) | 0.0008 (6) | 3,163 / 1,786,190 |

The v2 fraction is at least the frozen loop's in every row (2.3–4x on the dense day, where the frozen loop's
other-band ticks cancel resting legs). Whether it falls with B is not identifiable here: 0–9 quotes per row and the
fixtures change with B. The frozen loop took up to 811 s for 10 dense minutes at B = 170; v2 took 0.7 s.

**S9 — exact money: PASS** (`d82d810b…`, first run; rule 1 touched no money path, so not re-run). 16 carried fictional
days, dense fixture at B = 48, T = 20,000, 60 min/day, prints at 1e-4 share resolution up to 10^7 shares at ticks
0.01–0.99, caps 10^12; all 8 base engines in lockstep with the recompute assertion on every decision: 1,521,338
decisions, 1,898 fills, no Inexact trap, and final cash, reserve and inventory equal to independent recomputation.

## Findings

1. **Rule 1 (resolved by the owner, 2026-10-04).** "Every book record wakes" was superlinear because the exporter
   re-projects every live band's latest book at every books row (`maker_replay_bundle.py:420`) and the rows grow with
   D; it also re-created C1's stale-book cancellation through a band's own re-projections. Now a band wakes only on a
   book change, with live parity as the motivation (the venue streams book changes). Tests:
   `test_unchanged_resends_cause_no_decisions_and_keep_resting_informed_legs`,
   `test_a_quiet_resend_keeps_the_book_fresh_without_deciding`, `test_a_changed_book_wakes`,
   `test_a_silent_feed_goes_stale_on_schedule`, `test_book_state_excludes_only_the_clock`.
2. **Re-entry after `INFO_PULL` now reads the freshness clock** (the book's `as_of`) instead of the book's capture
   time, so a re-projection captured after the pull is not fresh re-entry evidence; the view's `as_of` was already used.
3. **C5 holds only for unit loadings.** The weather plugin's exposure loadings are 1, so factor exposures are exact. A
   fractional loading can make an exposure unrepresentable at 1e-6; the engine then refuses (`MoneyError`), pinned by
   `test_factor_exposure_that_one_millionth_cannot_hold_is_refused_not_rounded`. The registration should say so.
4. **Interpretations made where §5 is silent** (both engines share them, documented in `kernel.py`): view and event
   wakes (rule 4) apply to `informed-v0` only, as the frozen engine scheduled them; a descriptor or settlement record is
   not an own event (settlement still splits intervals); a terms record that refreshes stale terms counts as a change.
5. **Merge note:** W2 also extends `tools/research/maker_replay_v2/run.py`; expect a small conflict there.

## Frozen-bytes proof

`git diff --name-only 664c8943 HEAD -- <the 188 paths 664c8943 changed against master's merge base>` lists only
`docs/roadmap/correspondence-index.md` (generated, not hashed — as at the base). Over the v1 hashed set
(`src/maker_core`, `src/weather/market/maker_plugin`, `pyproject.toml`) the diff from `664c8943` is additions only.
v1's manifest `source_hashes()` inventory would gain the new `src/maker_core/replay/v2/*.py` files (Session A finding 5).

## Roll verdict (static)

New modules imported only by tests and `tools/`; no `src`, `app` or `scripts` closure imports them. Roll-free in
practice; production must still run `roll_verdict.ps1` on the integration branch before any landing.

## Tests, audits and CI

Focused v2 tests (25) and the repo-wide audits (schema registry, import architecture, path policy, module size,
admission tests, agent docs audit) passed under the wrapper; GitHub CI on the PR is reported in the PR.

## What was NOT done

No production, calibration, panel or settlement data; no registration, Scheduler change, venue call, order, merge,
or edit of the frozen exam tree. W2, W6–W8 not started.
