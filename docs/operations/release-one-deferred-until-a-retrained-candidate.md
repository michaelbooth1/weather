# DECISION 2026-08-06 — release #1 is deferred until a retrained candidate exists

Status: **canonical decision.** Taken by the production agent under explicit operator authority
granted 2026-08-06 ("full authority to change any parts of the project, including what we
freeze"). Supersedes release #1's standing position as priority 1.

## The decision

**Do not build release #1 on the June HGB artifacts.** Build it once a retrained candidate
exists, so the release freezes a model fitted on the season it is serving.

## Why — the evidence, not the argument

**1. We would be freezing the model at its worst configuration for the season we trade.**
`-09-31a` measured the base HGB against settlement, both strata out-of-sample, crossed
date × market, 12,289 snapshots on D=50 / M=12 / 524 market-days:

| | In-season (May 27 – Jun 30) | Out-of-season (Jul 1 – Jul 30) |
| --- | ---: | ---: |
| Base HGB centre − settlement | **−0.1848** | **−1.0193** |
| Market implied centre − settlement | +0.0699 | +0.0642 |

C−B = **−0.8346 C-eq [−1.4378, −0.2159]**, power 83.17%. The market's contrast is **−0.0057
[−0.1643, +0.1520]** — flat, so this is not the weather.

**Every date we now serve is out-of-season.** The archive stops at June 30 (§4b); it is August.
Freezing these artifacts freezes a model measured a full degree cool exactly where it is used.

**2. Release #1 does not unblock promotion, so deferring does not block the MM path.**
`hourly_model_performance` BLOCKs on `early_hour_brier_regression` — early-hour Brier trails the
market by **0.0205 against a 0.0030 tolerance, in all 12 markets** — and its own remediation line
reads `keep promotion blocked`. That is a model-skill refusal. **No release pointer touches it;
a better model does.**

**3. The lock does not expire, so deferral costs nothing structural.**
`RELEASE_ONE_BUILD_RUNBOOK.md` §3a: *"the source's latest target date must be no more than seven
days old — so the source must be built inside the window, not staged early."* That is a **rolling
recency requirement on the source build**, not a countdown from the 2026-08-04 lock. The 14-day
lock condition is met and stays met while capture continues. Settlement resumes with the
2026-08-05 backfill.

**4. Freezing now would corrupt the first retrain's confirmation.**
The reserved confirmation window arms at candidate freeze and measures candidate against
incumbent. With a knowingly defective incumbent, the first retrain's headline gain would be
substantially **repaired plumbing reported as model improvement** — the precise failure this
project has already retracted results for.

## What this does NOT claim

- **It does not claim the retrain will close the market gap.** `-09-31a`'s severity-tail contrast
  is **underpowered at 47.65%** with its interval crossing zero. We know the centre moves; we have
  not shown it moves the loss where the loss concentrates.
- **It does not retire release #1.** The release machinery is built, rehearsed, and correct. This
  is a sequencing decision about *what it freezes*, nothing more.

## What has to be true to reverse this

Reverse and build immediately if any of these hold — do not defer on inertia:

- The archive extension proves impossible or unexpectedly long (`-09-33a` P0 falsifier fires).
- Release #1 turns out to be **necessary** for promotion — currently **unestablished**, and
  testable once settlement is healthy enough for promotion refresh to actually run.
- Settlement lapses far enough that the seven-day source-recency rule can no longer be met, making
  the release harder to build later than now.

## Consequences to act on

1. **The archive extension is now the critical path** (`-09-33a`, then the production backfill).
2. **The retrain follows it**, on the `-09-20a` lane, against the code-owned 12,600-cell gate.
3. **Release #1 follows the candidate**, freezing a model fitted on the serving season.
4. Nothing is reserved today; the confirmation window is declared at candidate freeze, per
   `reserved-confirmation-window.md`, which continues to win over every other document.

## Update this file when

Release #1 is built, or one of the reversal conditions above fires.
