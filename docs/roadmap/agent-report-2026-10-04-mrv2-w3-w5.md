# Agent report — 2026-10-04 maker replay v2 W3/W4/W5

**Verdict: W3, W4 and W5 are BUILT and correct (S5 PASS, S9 PASS, MEASURED), but S3 is SUPERLINEAR, so the
mission STOPPED at S3 and S7/S8 were NOT RUN.** runtime(250)/runtime(40) = 27.49 s / 2.49 s = **11.0**, against
the ≤ 7.5 rule. The engine is linear in its own events (77–98 µs per wake at every B); the superlinearity comes from
the registered rule 1 ("a book record for the condition" wakes it) meeting the exporter's book re-projection: each
condition receives `ceil(2D/100)` book records a minute, so wakes per band-minute rise from 2.27 (B = 40) to 5.06
(B = 250). With re-projected unchanged books not waking (a diagnostic switch, off by default), the ratio is **5.85**
(linear). Fixing it needs a decision on rule 1 (see Findings 1–2); no code here changes the registered rule.

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
- Tests: `tests/maker_core/test_replay_v2_engine.py` (17) and `test_replay_v2_report.py` (4), all with debug on.
  Digest-invariance test: **`test_decision_digest_invariant_under_coverage_regrouping_and_view_elision`** (v0.1
  per-condition coverage with repeats, v0.2 groups with repeats elided, v0.2 one group per condition: identical
  decisions, intervals, fills, cash); plus `test_reentry_and_pull_digests_ignore_a_repeated_views_capture_time`, which
  also shows the frozen engine's decisions do change on the same input.

## Measurements (MEASURED; fictional; fresh process each, serial, under `workstation_heavy.ps1 -Kind weather_heavy`)

Run order: S5, S9, then S3 (correctness before cost); S3 then stopped the mission. Result SHA-256s are of each
measurement's JSON.

**S5 — v2 engine vs reference: PASS, zero divergences** (`4dd74585…`). B ∈ {12, 40, 170} × T ∈ {2,000, 20,000} ×
three windows (W0 90 min across the 04:00 UTC horizon roll; W0 90 min across 10:00 settlements; dense 30 min): 18
cases, 338,931 records, **353 engines compared (all 4 policies × both bounds per case) and 209 matched-clock trials**,
each on decisions, intervals, fills, cash, settlements, final legs, inventory, exclusions and the clock match. v2 ran
3.1–5.2x faster than the reference at B = 170 (e.g. 198 s vs 640 s for all passes of one case).

**S9 — exact money: PASS** (`d82d810b…`). 16 carried fictional days, dense fixture at B = 48, T = 20,000, 60 min/day,
prints at 1e-4 share resolution up to 10^7 shares at ticks 0.01–0.99, caps 10^12; all 8 base engines in lockstep with
the recompute assertion on every decision: 1,521,338 decisions, 1,898 fills, no Inexact trap, and final cash,
reserve and inventory equal to independent recomputation for every engine (373.6 s).

**S3 — runtime vs B: SUPERLINEAR → STOP.** W0 day, first 360 min, T = 2,000, one `informed-v0` strictly-through pass
over pre-decoded records, best of 3:

| B (union) | live bands (mean) | book rows/min | wakes | wakes/band-min | pass s | µs/wake | traced peak/pass | diag: changed-book-only pass s (wakes/band-min) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 40 | 31.0 | 1 | 25,329 | 2.27 | 2.49 | 98.3 | 3.8 MB | 2.60 (2.27) |
| 85 | 64.8 | 2 | 72,597 | 3.11 | 5.79 | 79.7 | 7.1 MB | 3.96 (2.14) |
| 120 | 92.6 | 2 | 102,405 | 3.07 | 7.02 | 68.6 | 9.9 MB | 6.42 (2.12) |
| 170 | 127.7 | 3 | 189,208 | 4.12 | 14.58 | 77.1 | 15.9 MB | 9.75 (2.18) |
| 250 | 186.3 | 4 | 339,621 | 5.06 | 27.49 | 80.9 | 19.2 MB | 15.19 (2.13) |

Ratio 250/40: **11.04 (registered rule; fails ≤ 7.5)**; diagnostic switch 5.85 (passes). Process peaks (0.3–3.9 GB)
include the in-memory fixture, not the pass. SHA-256: `f42777e5…` (40), `5a26f1ea…` (85), `dd4e5e3a…` (120),
`8f664902…` (170), `fa5dee97…` (250).

**S7, S8: NOT RUN** (stopped at S3). Smoke runs only (not measurements): a 10-minute B = 12 S7 gave a 170 kB report
and 271 kB sidecar; the frozen loop took 229 s for 3 minutes of the dense day at B = 170 against 0.5 s for v2.

## Findings that need a decision

1. **Rule 1 makes cost superlinear in B.** The exporter projects every live condition's latest book at every books row
   (`maker_replay_bundle.py:420`), and the number of rows grows with D, so "a book record for the condition" is not a
   constant ~3 per band-minute as §5 estimates (measured 4.1 at B = 170 in this window). Candidate amendment: a book record wakes only if
   its payload differs from the condition's previous book (equivalently, elide byte-identical book projections in
   v0.2). Measured above as the diagnostic (`V2Config.repeat_book_wakes=False`); it is not a scored setting.
2. **The C1 coupling defect survives through re-projections.** A re-projected unchanged book is older than the 10 s
   freshness gate, so waking on it gives `BOOK_STALE_OR_FUTURE` and cancels resting `informed-v0` legs — the same
   cancellation C1 attributes to other bands' events, now caused by the band's own repeated book. The amendment in 1
   removes both.
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

Focused v2 tests (22) and the repo-wide audits (schema registry, import architecture, path policy, module size,
admission tests, agent docs audit) passed under the wrapper; GitHub CI on the PR is reported in the PR.

## What was NOT done

No production, calibration, panel or settlement data; no registration, Scheduler change, venue call, order, merge,
or edit of the frozen exam tree. W2, W6–W8 not started. S7 and S8 not run (STOP at S3).
