# Workstation handoff 2026-09-81a — freeze and read the morning guidance candidate

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Follows mission `2026-09-79a`, whose handback is accepted as a descriptive result. `2026-09-81a` is a mission label.

## 1. Goal

Turn 79a's lead into a **pre-registered candidate with no fitted parameters**, find out whether the lead survives when the
rows without guidance are scored too, explain why the guidance is missing on most snapshots, and say how many new dates a
confirmation needs. Nothing in this mission serves, trains or promotes anything.

## 2. Start from this — do not re-derive it

Read `AGENTS.md`, `docs/operations/STATE_OF_PLAY.md`, `docs/operations/FINDINGS_DIGEST.md`, then the 79a completion
report and its aggregate JSON on this branch (`docs/research/missing-information-summary-2026-09-79a.json`).

- 79a, morning (before 10:00 local), matched snapshots, before / from 2026-08-23: NBM-quantile band probabilities score
  better than the served model by −0.0123 [−0.0230, −0.0036] / −0.0152 [−0.0251, −0.0061] Brier (raw; 218 / 239
  market-days, 20 / 22 dates, 11 markets) and −0.0147 / −0.0148 with the observed floor (149 / 166, 19 / 22, 9). Still
  1.15–1.22 x the market. The builder is `methods.band_probabilities`: linear CDF through p10..p90, normal tails from the
  captured mean and standard deviation, half-degree band edges. **It has no fitted parameter.**
- **That read is conditional on guidance being present**: fill is 24.6–38.3% of snapshots, Toronto has none, and the
  feature builder writes an NBM value only when it is physically valid against the observed floor
  (`src/weather/model/model_features.py`, the `nbm_probabilistic_tmax` block). A candidate is scored on every row.
- After 10:00 there are almost no NBM rows (5–14 market-days a bucket) and the ones that exist score 0.16–0.18, i.e.
  nearly all mass on a wrong band. Cause unknown: stale issue, next-day target, or the validity filter.
- The active Atlanta artifact selects 27 columns per cutoff and no NBM / NWS-grid / HRRR column (79a check 4b).
- `docs/operations/reserved-confirmation-window.md` read **NONE RESERVED** at issue. Re-read its status line first.
- Data: reuse the hash-verified 79a export already on the workstation (`extracted-1`, plan hash in the 79a report). Do not
  fetch new production data; if you need a file the export lacks, name it in the report.

## 3. Work, in this order

- **P0 — why is guidance missing (trace, not a grep).** From `weather.sources.nbm_probabilistic_tmax` through the feature
  builder to `features_long.csv`: what decides whether a snapshot carries `nbm_prob_tmax_*`? Report fill by local hour,
  by market and by date, split into "never fetched", "fetched but dropped as invalid against the floor", "fetched for a
  different target date" as far as the export allows. Explain the after-10:00 rows. State the smallest capture or feature
  change that would raise coverage. **Propose it; do not change `src/`.**
- **P1 — pre-registration, committed before any score.** `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md`.
  Freeze, with the file's SHA-256 written into every later output header:
  - **C1**: on a snapshot with a complete, valid NBM set, the NBM-quantile band distribution with the observed floor
    applied; otherwise the served distribution unchanged.
  - **C2**: fixed 50 / 50 linear pool of the served distribution and C1's NBM distribution, floor applied, renormalised;
    otherwise the served distribution unchanged. No other weight is tried.
  - Population: every snapshot 06:00–09:59 local on `promotion_countable` market-days; primary = the 11 US markets,
    secondary = all 12. Estimand: equal-weight market-day mean of (candidate − served) Brier; ratio to market beside it.
    Crossed date x market bootstrap, 2,000 draws, strata kept separate and also pooled (pooling is declared here, once).
  - Confirmation on **new** dates only, starting the day after the freeze commit. Derive the number of date clusters
    needed for 80% power at **half** the development effect, and the calendar date that implies at 12 market-days a day
    and the fill you measured in P0. Write the exact reservation text you propose for
    `reserved-confirmation-window.md` and the α you propose to allocate. **Do not edit that file or any α ledger.**
- **P2 — development read, only after P1's commit hash exists.** Score C1 and C2 on the 79a export. It is labelled
  development, never confirmation: 79a has already looked at the guidance-present subset of these dates. Report n, date
  clusters, market clusters, intervals, power and MDE for every number; share of rows where the candidate differs from
  served; the same table for 10:00–12:59 as a declared secondary.
- **P3 — where it would sit.** One page: the stage in the serving path where a morning guidance stage would go, and how it
  keeps probability mass, the observed-high floor, train/serve parity, captured-input replay and release binding. Design
  only. Put the pure function and its tests under `tools/research/morning_guidance/`.

## 4. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. In addition:

- The market is never an input to a candidate. Pooling with or shrinking toward `market_yes` is a measurement only.
- No fitted weight, no tuned spread, no per-market choice, no second candidate invented after a result. If C1 and C2 both
  fail, the report says so; it does not propose C3 from the same dates.
- No `src/`, `config/`, `artifacts/`, serving, Scheduler or capture change. No model fit. Free public sources only. No
  credentials, no exchange calls, no live or authenticated Polymarket access.
- Never weaken the observed-high floor. Never read `.weathersync.cred` or any credential file.
- Files you own: `tools/research/morning_guidance/**`, `tests/**/test_morning_guidance*`, the pre-registration, your report.
  The 79a allowlist entry already admits `tools.research.missing_information.run`; if you need a new entry point, add it
  the same way (hook, wrapper and the two tests together) and say so in the report.
- Commit and push your branch freely; never merge to `master`.

## 5. What would falsify the lead

- On all morning rows, C1 − served has an interval that includes zero in either stratum, or is smaller than half the 79a
  matched effect ⇒ the 79a result was mostly a property of the rows where guidance happened to be present.
- P0 shows most missing rows were **dropped as invalid against the floor** ⇒ 79a scored NBM only where it was not already
  refuted; restate the effect size accordingly.
- The confirmation needs more than about 45 new dates ⇒ say it is not affordable this season and name the cheapest
  independent alternative (for example the IEM NBS history you already downloaded, against older served dates).
- C2 is worse than C1 and than served ⇒ the two forecasts share their errors; pooling is not the route.

## 6. Branch and report

- Branch: `codex/morning-guidance-candidate-20260921`, from `origin/codex/nbm-candidate-handoff-20260921`.
- Report: `docs/roadmap/agent-report-2026-09-81a-workstation-morning-guidance-candidate.md`, per contract §5 — verdict
  first in bold; the pre-registration commit hash and file hash **before** the first score's timestamp; measured values
  with full support; per-file roll verdict (the production host returned ROLL-FREE for the 79a branch; yours will be
  re-run here); what was NOT done; reproduction commands with workstation paths.
