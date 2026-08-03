# Workstation handoff 2026-08-29a — how much lookahead is in `forecast_high`?

Run this now. **Measurement only: no fetch, no network, no archive write, no fit, no candidate, no
fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## What you found, and why I am not moving on from it

`-08-28a` was scoped as a feasibility study and returned something more important than feasibility.
I verified it on the host rather than take it on report:

- `forecast_history.py:341` writes historical-forecast rows with `issue_time=""` and
  `issue_time_basis="stitched_continuous_archive"`.
- The file the trainer actually reads, `data/forecast_history/cyyz/forecast_daily.csv`, is **7.8 KB
  with exactly two columns**: `local_date,forecast_high_c`. No issue time, no lead, no model. The
  provenance is discarded before the feature exists.
- `forecast_daily_by_issue.csv` — **411 KB**, fixed leads 1–7, 2021+ — sits beside it **unread**.
- Both `feature_model.py:875` (training) and `model_features.py:1636` (analog serving) call the same
  `load_forecast_daily`.

Since the stitched series splices the first hours of successive runs, a daily maximum can carry runs
issued *during* the target day — after a 09:00–14:00 row's cutoff. So `forecast_high` and
`forecast_gap`, split on in **154 of 168 bundles**, are fitted on values we cannot prove were
knowable at the row's cutoff.

**We do not know whether that matters.** That is the entire mission.

## Measure it

Everything needed is already on disk. No network, no provider, no reserved dates: archive coverage
is **May 10 → June 30 only**, so this lives entirely on prior-year spring data.

1. **Size the lookahead.** For 2021–2025, compare the stitched `forecast_daily.csv` value against the
   fixed-lead rows in `forecast_daily_by_issue.csv` for the same market and target date. Report the
   distribution of the difference — by market, by lead, and with an interval. If the stitched value
   is systematically closer to the settled outcome than any honest lead, that is the lookahead, and I
   want it in degrees.
2. **Say which direction it biases.** If the stitched forecast is warm-biased or cool-biased relative
   to a true cutoff-time forecast, say so explicitly. A model fitted on optimistic forecasts learns
   to over-trust `forecast_gap`; whether that pushes the served centre cool is exactly the open
   question in [`base-hgb-is-cool-root-cause`], and I want it answered on evidence, not by analogy.
3. **Bound the consequence.** Given the measured difference and the split usage, how much model
   quality is plausibly at stake? An honest interval that crosses zero is a completely acceptable
   answer and would let me stop worrying about this.

## What I do not want

Do not conclude that this explains the cool bias because the story fits. We have eliminated three
mechanisms this month by measuring them, and each time the intuitive story was wrong — blindness even
moved the centre in the *opposite* direction from the defect. Hold this to the same standard.

Do not fit anything, and do not build a candidate. Four already contend for scarce dates.

## Also worth an answer

Is there any *other* feature built from a source whose provenance is discarded the same way? The
two-column `forecast_daily.csv` was invisible until someone looked at the actual file. If there are
more like it, I would rather find them in one pass than one incident at a time.

## What I want back

1. The lookahead magnitude, by market and lead, with intervals.
2. Its direction, and whether it is consistent with the observed cool displacement or against it.
3. A bounded estimate of what it costs, or a clear statement that the interval crosses zero.
4. Any other feature whose provenance is discarded before use.
5. Your recommendation: does this change the first-retrain plan, or is it a footnote?

## Sequencing

Measurement only. The corpus rebuild you specified in `-08-28a` stands as the plan; this decides how
urgent it is and whether the 2021–2025 PIT restriction is buying something real or just costing us
sample size.

## Constraints — unchanged

- Base on `master` @ `027f65bf`.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.** This mission needs none of them.
- **No network access. No provider query.** Read only what is already on disk.
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. A clean negative — the stitched value is
indistinguishable from an honest lead — is a genuinely good outcome and should be reported just as
prominently as a positive.
