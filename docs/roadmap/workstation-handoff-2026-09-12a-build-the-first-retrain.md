# Workstation handoff `-09-12a` — build the all-market base retrain, and make it refuse

Written 2026-08-04 by the operations master agent on the production host. Read this on
`origin/master` and execute it.

**This is a large mission. It is not time-sensitive — nothing downstream is waiting on it tonight.
Prefer doing it thoroughly over doing it fast.**

## The situation

Release #1 **freezes** the June 10–13 per-market HGBs into the release pointer. It does not refit
them. And the reason is starker than "the scheduler is broken":

> **No scheduled job anywhere trains a per-market base HGB.** `nightly_retrain.planned_steps()`
> contains `weather.calibration.pooled_feature_model` but **not** `weather.calibration.feature_model`,
> the per-market base trainer. `release_candidate_contract._freeze_base_model_serving_graph()` copies
> seven components per market via `_copy_file_exclusive`; it freezes bytes and never fits.
> `.github/workflows/retrain.yml` has its schedule commented out and trains **toronto and nyc only**.

**There is nothing to restart. The all-market base step has to be written.** That is this mission.

It matters now because `-09-08a` established that the frozen HGB is **systematically cool**
(`-0.6641 °C-eq`, crossed interval `[-1.1164, -0.2482]`, wholly negative — one of only two results
that survive crossed clustering), that **no serving-side correction is admissible**, and therefore
that **the retrain is the only repair path.** We are about to freeze a model we know is wrong, with
no mechanism to ever refit it.

## Non-negotiable framing: the preflight must REFUSE today

The known blockers below are all still present. **A preflight that passes today is broken.** Your
acceptance criterion for your own work is:

> **The preflight refuses, today, on the production evidence, naming each blocker specifically.**

If it passes, you have built decoration. Prove refusal blocker-by-blocker.

## P1 — the all-market base retrain step

Write the step that does not exist: an all-market caller for the per-market base fit, with an
explicit market list from the live registry (12 markets, 1 C + 11 F), native settlement units
preserved, and per-market artifacts written to a candidate location — **never** over the frozen
release bytes.

**Do not wire it into any scheduled job.** Do not register a task. It must be runnable only by
explicit invocation until the operator says otherwise.

**Do not execute a fit in this mission.** Build it, prove the preflight refuses, stop.

## P2 — a fail-closed preflight covering every known contaminant

Each item below must be an independent, named, blocking check. State for each whether it refuses
today and on what evidence.

1. **Forecast archive coverage — the hard fail.** `data/forecast_history/*/manifest.json` has
   `season_window` **May 10 → Jun 30**, 52 days/year, 9 years. A late-July-aligned training window
   gets **zero rows**, so `forecast_high` / `forecast_gap` would **train missing and serve
   populated** — worse skew than the WU defect.
   **Coverage must be manifest-bound, not self-declared.** The consolidated stack already found
   exactly this: a run could *assert* coverage it did not have. Require an exact manifest-backed
   market/date/cutoff matrix **and** matching feature-record provenance before fitting is reachable.
   Ambient `forecast_daily.csv` must stay unreachable.
   **CAUTION: the archive is not training-only.** `model_features.py:1636` calls
   `load_forecast_daily(daily_path_for(spec))` on the *analog serving* path, so extending it changes
   live serving inputs. Extending it is **not** in scope here — the preflight must refuse, not repair.

2. **`forecast_high` is not point-in-time.** The trainer reads a 2-column stitched file while the PIT
   file goes unread. The fit is contaminated (evaluation is not). Bind the retrain to the PIT corpus.

3. **Train/serve parity.** See P3.

4. **Class support.** Seasonal alignment warms every label prior (+0.15 to +10.16 native degrees) but
   **Dallas 108 °F, Denver 101–102 °F, Houston 103–104 °F, Seattle 95 °F remain absent.**
   Reweighting cannot create an absent class. **Serving support must be declared as a contiguous
   native range separate from `model.classes_`.** Six settlement-above-max market-days are 10% of
   morning market-days but **48.41% of signed cool displacement** — this is not a rounding error, it
   is a large share of the exact defect the retrain exists to fix.

5. **Calibrator staleness.** Calibrated empirical weights `generated_at` **June 7**; LR fallbacks
   June 13; late-day June 15. Nightly only *copies* them, so **a changed HGB would inherit a
   calibrator fitted to the old distribution shape.** Require candidate-specific OOF recalibration;
   refuse if a candidate's base bytes changed and its calibrators did not.

6. **`rows[-1]` regime boundary `2026-07-31`** — artifact provenance, not target-date age. Refuse any
   training set that mixes artifacts across it.

## P3 — settle the train/serve parity binding

The gate exists and works: `weather.reporting.scorecards.train_serve_feature_parity`, on branch
`codex/workstation-train-serve-parity-gate-2026-09-03a` @ `af32501b`, **unmerged**. It reports
**BLOCK — 220 findings** (108 blind-feature missingness across 9 fields × 12 markets, 44 profile
provenance, 40 WU cutoff availability, 24 gust/shift, 4 stitched `forecast_high`), plus one exact
evidenced trusted-floor exception.

It already paid for itself: `wind_gust_kmh` and `wind_shift_3h_degrees` are populated by the training
builder and missing from the serving builder in all 12 markets. Neither is among the 19 active base
features, so it is **not** a current Brier claim — **the significance is forward.** Both are in the
training feature list, so **a retrain would fit them and serving would be blind to them**, baking in
fresh skew.

**My leaning, which you should test rather than accept:** bind it as a **blocking precondition on the
all-market base-retrain step**, not on the release path — the retrain lane is not live yet and this is
exactly the contamination it must refuse, whereas release-path binding is riskier and can wait.

Settle it with a written recommendation. If you disagree, say why.

## P4 — the cool bias, conditionally

`-09-09a` is separating **artifact age** from **temperature level** as the driver. Do not assume the
answer. Specify **both** branches:

- **age carries it** → the retrain repairs it, its value decays, and **retrain cadence** becomes a
  parameter this project has never set. Say how the spec sets it.
- **temperature carries it** → the retrain **reproduces** the defect, and the repair is **warm-tail
  class support** (see P2.4), not recency. Say what changes.

State which preflight checks differ between the two worlds.

## P5 — what remains

Close with an honest list of what is still missing before a first retrain is **worth spending**, and
what the confirmation would look like — including that per the re-based reservation, a confirmation
window must be **declared in `docs/operations/reserved-confirmation-window.md` at candidate freeze,
dated and sized, before any confirmation scoring**, and that **an undeclared window reserves nothing.**

## Deliverable

1. The all-market base retrain step (P1), unwired and unregistered.
2. The fail-closed preflight (P2), with **proof it refuses today, blocker by blocker.**
3. A written parity-binding recommendation (P3).
4. Both conditional branches for the cool bias (P4).
5. What remains (P5).
6. **A per-file roll-safety verdict**, by import closure — not the `SOURCE_PATTERNS` glob.
7. A `## What would falsify this` section.

## Constraints

**Do not execute a retrain or any model fit. Do not write to `artifacts/releases/`. Do not create,
move, or modify a release pointer. Do not register or modify any scheduled task.**

**Do not touch the release or PIT path.** The release #1 build runs on the production host tomorrow
night; a collision there is far more expensive than anything this mission delivers.

**Do not weaken the trusted observed-high floor.** It is load-bearing and is one of only two results
that survive crossed clustering.

**Reservation:** re-based by the operator on 2026-08-04 — **nothing is reserved today**, and the
window is armed but undated until a candidate is frozen.
`docs/operations/reserved-confirmation-window.md` remains the single source of truth and outranks this
document; **re-read it when you run**, and honour its five binding rules.

**Clustering.** Crossed date × market on any interval. If one crosses zero, say so in the same
sentence as the point estimate.

**Roll-safety.** Anything inside the capture loops' loaded-module closure rolls all three loops and
must land in a 01:00–04:00 quiet window. A wrong call risks the Toronto streak, which outranks
everything in this mission.

**Network:** `git fetch` and `git push` only. No provider calls, no new collection.

Push `codex/workstation-build-the-first-retrain-2026-09-12a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-05-workstation-build-the-first-retrain.md`.

## Prior work to reconcile, not redo

Three held branches bear on this. Read them before building; say plainly what you reused, what you
superseded, and why.

- `codex/workstation-make-the-first-retrain-count-2026-08-25a` @ `92bb5347`
- `codex/workstation-train-serve-parity-gate-2026-09-03a` @ `af32501b`
- `codex/workstation-consolidate-merge-queue-2026-09-01a` @ `450f03c5` — its lesson is the one to
  carry: *"wiring two independently-specified contracts together is where the real defect lives."*
  Neither branch was wrong on its own terms; the defect appeared only at the seam.

## How to disagree

If the all-market step should not be built the way this handoff describes, say so and build the
better thing. If some blocker cannot be checked mechanically, name it and say what the preflight
should do instead of pretending to cover it. A preflight that honestly declares a gap is worth far
more than one that silently assumes it away — that assumption is the exact shape of every major
defect this project has found in the last month.
