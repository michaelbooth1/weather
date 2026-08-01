# Workstation lock-window sweep — 2026-08-02

## Baseline and scope

The work started from exact `origin/master` commit
`697fe0d08e9e86dbe0c8b1e3b163acb82dfd4988` on topic branch
`codex/workstation-lock-window-sweep-2026-08-02a`. The clean branch baseline
was pushed before the sweep began.

All operational output is below the single declared run root
`C:\Users\Michael\Documents\github\weather\scratch\runs\lock-window-sweep-2026-08-02a`.
The main clone's `data/` tree was mounted into the isolated worktree only for
read access, and the junction was removed after the sweep. No source tape,
ledger, settlement label, model artifact, release, or pointer was written.

The three requested checks were independent:

1. the production bounded replay reader's duplicate pinned-identity scan;
2. the ordinary grade-only promotion-corpus `min_snapshots=1` decision, with a
   bounded replay-only inventory when an unsettled date had no label yet; and
3. the canonical `build_family_dataset(unit="F",
   included_target_dates=...)` coverage gate, anchored to `2026-08-04`, the day
   after the requested lock window.

`PASS` means that defect class is absent. `FAIL` means the defect class is
present. `NOT ASSESSABLE` means the required Toronto folder is not in this
mirror; it is not treated as a pass.

## Per-date sweep

| Date | Scope | Duplicate pinned identities | `too_few_replay_inputs` | F-family coverage | Evidence note |
| --- | --- | --- | --- | --- | --- |
| 2026-07-14 | lead-in | PASS | PASS | PASS | 167 bounded identities; 167 admitted replay inputs |
| 2026-07-15 | lead-in | PASS | PASS | PASS | 169 bounded identities; 169 admitted replay inputs |
| 2026-07-16 | lead-in | PASS | PASS | PASS | 193 bounded identities; 193 admitted replay inputs |
| 2026-07-17 | lead-in | PASS | PASS | PASS | 172 bounded identities; 172 admitted replay inputs |
| 2026-07-18 | lead-in | PASS | PASS | PASS | 205 bounded identities; 205 admitted replay inputs |
| 2026-07-19 | lead-in | PASS | PASS | PASS | 165 bounded identities; 165 admitted replay inputs |
| 2026-07-20 | lead-in | PASS | PASS | PASS | 180 bounded identities; 180 admitted replay inputs |
| 2026-07-21 | lock | PASS | PASS | PASS | 191 bounded identities; 191 admitted replay inputs |
| 2026-07-22 | lock | PASS | PASS | PASS | 197 bounded identities; 197 admitted replay inputs |
| 2026-07-23 | lock | PASS | PASS | PASS | 207 bounded identities; 207 admitted replay inputs |
| 2026-07-24 | lock | PASS | PASS | PASS | 195 admitted inputs; one tape identity lacks replay input, but the corpus is not too few |
| 2026-07-25 | lock | PASS | PASS | PASS | 195 bounded identities; 195 admitted replay inputs |
| 2026-07-26 | lock | PASS | PASS | PASS | 185 bounded identities; 185 admitted replay inputs |
| 2026-07-27 | lock | PASS | PASS | PASS | 158 bounded identities; 158 admitted replay inputs |
| 2026-07-28 | lock | PASS | PASS | PASS | 193 bounded identities; 193 admitted replay inputs |
| 2026-07-29 | lock | PASS | PASS | PASS | 189 bounded identities; 189 admitted replay inputs |
| 2026-07-30 | lock | PASS | PASS | PASS | 184 bounded identities; 184 admitted replay inputs |
| 2026-07-31 | lock | PASS | PASS | **FAIL** | duplicate scan passed; 189 bounded inputs; settlement label pending; F corpus missing date |
| 2026-08-01 | lock | PASS | PASS | **FAIL** | duplicate scan passed; 32 bounded inputs; settlement label pending; F corpus missing date |
| 2026-08-02 | lock | **NOT ASSESSABLE** | **NOT ASSESSABLE** | **FAIL** | Toronto folder absent from mirror; F corpus missing date |
| 2026-08-03 | lock | **NOT ASSESSABLE** | **NOT ASSESSABLE** | **FAIL** | Toronto folder absent from mirror; F corpus missing date |

## Lock-window verdict

**The `2026-07-21` through `2026-08-03` lock window is NOT CLEAN in this
mirror.**

The canonical F-family builder refuses four preselected fleet dates:
`2026-07-31`, `2026-08-01`, `2026-08-02`, and `2026-08-03`. If that state is
unchanged at build time, it is a lock-day blocker. The finding begins at the
mirror's current evidence horizon; it is not a scattered recurrence among the
settled July dates. Every date from `2026-07-14` through `2026-07-30` passes all
three checks.

No duplicate pinned replay identity or `too_few_replay_inputs` defect was found
in any present folder from `2026-07-14` through `2026-08-01`. The last two dates
cannot be declared clean for those classes until their Toronto folders exist.
The pending settlement labels on July 31 and August 1 are outside the three
requested defect classes: the bounded duplicate scan and replay-input inventory
both complete before that unrelated admission stop.

As a method control, the same sweep reproduced every independently confirmed
June finding exactly: all seven duplicate dates, both `too_few_replay_inputs`
dates, and all six F-family coverage-gap dates.

Evidence:

- `lock_window_sweep.json`, SHA-256
  `0904c4f49c754766a5a792a783065191100178ff248a4a6e3575eb1415d30f82`;
- `sweep_method_controls.json`, SHA-256
  `b4662c8ae5759722253b803a7a1dbb291dd3424690d1def90ca59093b4dd9a6b`;
- `mission1_verdict.md` records this verdict before the source edit began.

## Diagnostic fix

Only after the sweep and verdict were complete, the contradictory empty-input
message in
`src/weather/reporting/validation/point_in_time_evaluation.py` was fixed. The
combined condition is split without changing the upper-bound logic:

```python
if not entries:
    raise BoundedReadError("replay manifest is empty")
if len(entries) > max_market_days:
    raise BoundedReadError(
        f"market-day bound exceeded: {len(entries)} > {max_market_days}"
    )
```

An empty replay manifest now says it is empty and still creates neither the
Parquet source nor its manifest. No bounds, output, or admission semantics were
changed.

### Declared roll footprint

**This merge is roll-sensitive.**
`src/weather/calibration/residual_distribution_v1.py` imports
`RollingOriginFold`, `build_fit_receipt`, and the rolling-fold builders from the
changed module. That direct import places
`point_in_time_evaluation.py` on the calibration path even though this patch
changes only an exception message. Time the merge accordingly.

No model artifact, calibration artifact, release, serving route, active
pointer, scheduler, capture process, mirror, or ACL was changed.

## Verification

- empty-manifest regression: `1 passed`;
- `tests/reporting/test_point_in_time_preselection_source.py`:
  `34 passed, 1 skipped`;
- point-in-time evaluation plus residual-distribution roll-footprint tests:
  `27 passed`;
- `git diff --check`: PASS.

Before the topic worktree was created, the clone-local
`config/storage_pressure.json` drift was restored to committed state
`6312e88d`; master was clean when fast-forwarded to `697fe0d0`. No tracked or
untracked `config/` change remains in this branch.

No PR was opened. Nothing was merged or pushed to master, promoted, activated,
served, scheduled, captured, mirrored, or unlocked.
