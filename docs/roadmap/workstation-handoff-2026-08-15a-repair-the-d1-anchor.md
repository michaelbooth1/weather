# Workstation handoff 2026-08-15a — repair the D1 anchor (build only, no scoring)

`-08-14a` could not evaluate replication: no new dates existed yet. That was a scheduling error in my
prompt, not yours — August 1's labels arrive with the 04:30 mirror on August 3, and the mission ran
on August 2. The July 31 byte-identical reproduction is a useful determinism proof and nothing more.

Its **secondary diagnosis is the valuable output**, and this mission acts on it.

## What the diagnosis found

On qualified D1 rows the candidate's mean native distribution was `P(D0)=0.529727`,
`P(D1)=0.105475`, `P(D>=2)=0.364799`. The realized state was exactly D1, and the model put five times
as much mass on no-continuation — and **less mass on D1 than on D>=2**.

The continuation distribution is **non-monotone over its own support**. In 89 of 98 D1 snapshots the
winning band sat one band above the floor; on the 58 qualified above-floor cases winner probability
fell `0.443133 -> 0.123093` while floor-band probability rose `0.363760 -> 0.577260`, and those 58
snapshots produced 63 of the slice's 65 newly-severe rows. The nine qualified cases whose winner
stayed *inside* the floor band improved by `-0.003194`.

So D1 is not intrinsically unrepresentable. Mass is being dumped at the origin and stripped from the
adjacent state precisely when the adjacent state crosses a band boundary.

## The mission — build only

Repair the anchor with **ordinal smoothing over the D-support**, so that adjacent continuation states
are not starved relative to distant ones. Fit and freeze it.

**Do not score it. Do not read any date outside July 22–26.** The scoring pass is `-08-16a` and it
must have dates this mission has not touched.

- Development and selection stay entirely inside **July 22–26**, using the same forward-chained
  folds and market-day grouping as `-08-13a`.
- The gate stays frozen at `floor_available and floor_removed_mass > 0.20`. This mission changes the
  continuation distribution's shape, **not** where the lane applies.
- All hard-floor stages stay frozen and untouched. The floor remains a control, never a tunable.
- Keep the smoothing parameterization coarse and pre-declared, for the same reason the gate threshold
  was coarse: a finely tuned smoother has relocated the overfitting into the smoother.

Freeze the resulting artifact in its own commit and report its SHA-256. `-08-16a` will score exactly
that artifact.

## Pre-register before fitting

1. The smoothing form and the coarse parameter set you will select from, declared before any fit.
2. The selection rule, on July 22–26 validation folds only.
3. An explicit statement that no fresh date will be read, scored, or enumerated by this mission.

## What I want back

1. The frozen repaired artifact's SHA-256, and the frozen smoothing parameter.
2. Development-fold evidence that the non-monotonicity is actually gone: report the mean
   `P(D0) / P(D1) / P(D>=2)` on qualified D1 rows before and after. If `P(D1)` still sits below
   `P(D>=2)`, the repair has not done its job and I would rather know that than see a Brier number.
3. Whether the repair costs anything on D0 rows, which were the ungated candidate's best slice
   (`-0.010914`, severe 1,629 → 484). A repair that fixes D1 by breaking D0 is not a repair.
4. Any reason to believe the smoothing helps the development folds only because it was selected on
   them. Say so plainly if you suspect it.

## Constraints — unchanged

- Base on `codex/workstation-floor-informativeness-replication-2026-08-14a` @ `703075f7`. It and all
  its parents are held and unmerged on purpose. Do not merge any of them.
- **July 27–31 is off limits to this mission.** July 27–30 is burned; July 31 is reserved for the
  `-08-16a` scoring pass and must not be read here.
- **Do not read, enumerate, evaluate, or substitute 2026-08-06 → 08-19.** Final confirmation set.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch, commit, and the frozen artifact SHA-256. Expect it to be
held.

**Do not proceed to scoring.** `-08-16a` will score this artifact and the existing `-08-13a`
candidate together, on the same pre-declared dates, on or after 2026-08-05 — the first morning on
which July 31 plus August 1, 2, and 3 are all available.
