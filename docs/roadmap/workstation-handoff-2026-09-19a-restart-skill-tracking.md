# Workstation handoff 2026-09-19a — restart skill tracking

**Goal: a durable, honest time series of model-versus-market skill, so the first retrain can be
judged against a real pre-retrain baseline.** Every existing skill series died between 2026-06-25 and
2026-07-10. The one that still runs scores zero rows. We are about to change the model for the first
time since June with nothing to compare against.

Branch from refreshed `origin/master`. Branch name:
`codex/workstation-restart-skill-tracking-2026-09-19a`.

## The state you are starting from — measured on the host 2026-08-05

| Artifact | Last updated | Verdict |
| --- | --- | --- |
| `data/backtest/model_history_cache.json` | **Jun 25** | 41 days stale |
| `data/backtest/location_daily_brier_week_2026-06-16_to_2026-06-22.*` | Jun 22 window | last weekly Brier ever produced |
| `data/backtest/proper_scoring_reliability_scorecard.json` | **Jul 9** | stale |
| `data/backtest/daily_learning.json` | **Jul 10** | dead; `nightly_retrain_status.daily_learning` is `{}` |
| `data/backtest/live_variant_settlement_scorecard.json` | Aug 4 — **fresh** | `BLOCK`, 12 blockers, **9200 of 9200 eligible partitions failed validation**, `eligible_prediction_coverage: 0.0` |

And the model itself has not moved: `artifacts/models/hgb/*.pkl` are **June 10–13**, calibration is
July 12, `artifacts/releases/` is **empty**, and `nightly_retrain_status.candidate_release` is
`{"activation": "NONE", "status": "BLOCK", "reason": "captured_input_replay_parity_blocked"}`.

So the honest current answer to "did the model improve last month" is **the model did not change**.
The only measured change was to the *serving path* — the 2026-07-31 floor fix, 1.664x → 1.498x
versus market. That is exactly why this tracker matters now: **the first retrain is the next change,
and there is no baseline to judge it against.**

## P0 — repair before you rebuild

Do not write a new scoring stack until you have established whether the existing one is repairable.
`src/weather/reporting/scorecards/model_history.py` already scores from snapshots plus the settlement
ledger and maintains `model_history_cache.json`. Determine why it stopped and whether it is the right
spine. Two concrete leads, both found on the host, neither yet confirmed as defects:

1. It has **no CLI** — it is a library for the Streamlit dashboard. Nothing schedules it. That alone
   may explain the June 25 cache.
2. It imports `TORONTO_TZ` from `model_constants` and uses it at lines 31, 90, 197 and 678 for
   `as_of` and `generated_at`. The retained timezone repair threaded `spec.tz` per market because a
   global Toronto clock put 8 cities on the wrong day. **Verify whether this module still has that
   defect**, and whether it can silently misassign a market-day near local midnight.

Also diagnose the fresh-but-empty `live_variant_settlement_scorecard`: 9200 of 9200 partitions
failing validation with full expected snapshot coverage is a contract mismatch, not missing data.
Name the mismatch. A daily job that reports `BLOCK` with `0.0` coverage is worse than no job — it
looks like tracking.

## P1 — what the series must measure

**Model versus market, never model alone.** The standing finding is that we trail the market; a
model-only Brier series can improve while the gap widens, and the gap is the objective.

Per countable market-day, record at minimum: model Brier, market Brier, their ratio, the resolution /
reliability decomposition, and the market-day identity. Then aggregate weekly.

Binding rules, all of which have already cost this project a retracted result:

- **Admission bar is `promotion_countable`, not `quality_grade == "complete"`.** The complete-only
  bar starved a previous corpus.
- **Authority is `data/settlements/<market>/ledger.jsonl`,** not `market_day_labels.csv`.
- **Every interval must use crossed date × market clustering.** Exchangeable market-day resampling
  produces intervals that are too narrow and has already retracted headline results, including a
  24.69% claim that crosses zero under correct clustering. An uncertainty-free point estimate is not
  acceptable output.
- **Never pool across the `2026-07-31` artifact regime boundary.** It is artifact provenance, not
  target-date age. Segment, and label each segment with the artifact regime it belongs to.
- **Report the 09:00–14:00 slice as its own series.** It is the primary objective and the window
  where the model is feature-blind; an aggregate that hides it is the metric we already decided to
  stop chasing.

## P2 — the tracker must report its own power

This is the requirement that makes it trustworthy rather than reassuring.

We have roughly 34 date clusters, not hundreds. Most week-over-week deltas will be statistically
indistinguishable from zero. **When a delta is not distinguishable, the tracker must say so in those
words and must not present the point estimate as a movement.** Print the effective cluster count
alongside every number, and state the minimum detectable effect for that week.

The failure mode being designed against is specific and has happened here: a leakage-driven "win"
was reported as real, and a 24.69% interval was published that crossed zero. A tracker that cannot
say "this week tells us nothing" will eventually manufacture the same error automatically, on a
schedule.

## P3 — durability and shape

- **Append-only.** A dated row, once written, is never rewritten by a later run; corrections arrive
  as new revisions carrying `supersedes`, matching the settlement ledger's own revision discipline.
- **Backfill the full available history**, so the pre-retrain baseline exists before the retrain
  lands, and so the 2026-07-31 serving change sits inside the series rather than before it.
- **Positive controls — the series must reproduce results we already trust:** the 07-31 floor fix
  moving served performance 1.664x → 1.498x, and the frozen-HGB cool centre bias of −0.6641 C-eq
  with a crossed 95% interval of [−1.1164, −0.2482]. If your series cannot reproduce those, the
  series is wrong, not the retained findings.
- Deliver it as a **CLI plus a scheduled-task registration script**, not a dashboard-only library.
  That is the defect that killed the last one. Do not register anything.

Estimate the runtime and the host cost of a nightly refresh. The host is 16 GB with three capture
loops at `AboveNormal`, a live `HOST_LOAD_POLICY`, and a chain that already defers heavy steps under
memory pressure. If a full nightly recompute is too heavy, design an incremental refresh and say so.

## Boundaries

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled
  task, write nothing under `data/` on the production host, never write to the mirror or
  `D:\weather-mirror`.
- Never read or expose `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. **Backfill must not read, enumerate, replay or score a
  reserved date** — check the file, do not assume it is still empty when you run.
- Do not weaken the trusted observed-high floor, do not relax the promotion gate for `harvest_only`
  rows, do not change providers or paid tiers.
- Per-file roll verdict from retained capture-loop import closures, not the `SOURCE_PATTERNS` glob.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-restart-skill-tracking.md`.

## What would falsify this mission

- Finding that `model_history.py` is sound and merely unscheduled would make this a scheduling task,
  not a rebuild — that is the cheapest possible outcome, so test it first.
- Finding a skill series that *is* current somewhere would falsify the premise; the five artifacts
  above are the ones inspected, so show the counter-example.
- Finding that the 07-31 floor improvement does not reproduce under crossed clustering would be a
  significant finding about that result, not a bug in the tracker — report it as such rather than
  tuning until it matches.
- Finding that per-market timezone handling in the existing scorecard is already correct would close
  the P0 lead 2; say so explicitly either way.
