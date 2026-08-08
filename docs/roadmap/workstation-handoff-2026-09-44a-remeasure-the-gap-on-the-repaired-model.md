# Workstation handoff 2026-09-44a — re-measure the gap on the repaired model

Written 2026-08-08 by the production agent. Read on `origin/master` and execute.
**This is the top model item.** `-09-43a` changed the serving input surface, and **every number we
use to describe the model was measured before that change.**

## 1. Goal

**Re-measure the market gap, and the findings that hang off it, on the repaired serving surface** —
then say plainly which established findings still stand, which moved, and which are now unciteable.

## 2. Why this, and why now

`-09-43a` routed 9 of the 10 dead base features and **821 of 840 admitted replay distributions
changed**, mean L1 0.223. §4 states the consequence in its own words: *"the cool bias, the market
gap, the severity tail and the centre-displacement work were all measured on a model missing 10 of
19 base inputs at all times."*

So we are in the worst possible position for a project whose objective is "beat the market": **we
changed the model and we do not know what it did to the gap.** Until this runs, §1, §2, §4d and the
centre-displacement work are all quoting a model that no longer exists.

`-09-43a` did measure a served delta, but only on **5 date clusters**, and its Brier interval
crossed zero at power 0.131. **That is not the measurement this mission is for.** The replay corpus
carries far more date support and is the one place adequate power has ever been plausible.

## 3. The repair is PARTIAL — do not assume otherwise

This is the single easiest way to get this mission wrong. Measured fleet population after repair:

| Feature | State |
| --- | --- |
| `dewpoint_c`, `wind_speed_kmh`, `hours_at_peak`, `warming_rate_2h`, `rise_from_7am` | live fleet-wide, 75.9–99.2% |
| `humidity` | **Toronto only** in the retained corpus (8.70% fleet) — old AviationWeather envelopes never kept `rh`. Fleet-wide only *going forward* |
| `pressure`, `pressure_trend_3h` | **0.00% everywhere.** Toronto gets them going forward; **the 11 F markets never will** |
| `wind_group` | dead in all 12, untouched |

**`pressure` is not a defect to fix.** METAR publishes altimeter/sea-level pressure; the trained
feature is *station* pressure, materially different at Denver's altitude. Aliasing passes a presence
check and is false in substance. If your analysis wants to "fix" it, stop — that is the trap
`-09-43a` deliberately avoided.

**Consequence for your design:** the F markets and Toronto now have *different* input completeness.
Do not pool them into one "repaired" bucket without saying so. A Toronto-only result is directional
by §5 and can never be a confirmation.

## 4. P0 — the primary endpoint

**Market gap on the repaired serving surface, on the replay corpus, versus the same corpus on the
pre-repair surface.** Paired, same rows, same cutoffs.

- Report the gap as §1 and §4e report it (**served, in-season, excluding 1.0**) so it is directly
  comparable to **1.4233x**. If you must change the estimator, report BOTH.
- **Crossed date × market clustering, and report power before interpreting any point.**
  **"Not powered" is a valid verdict** and beats a directional story. Recent fits ran at
  0.054–0.146 and could conclude nothing; say so again if that is what you find.
- A **positive control is mandatory**: pre-repair code must reproduce the recorded incumbent
  distributions exactly, as `-09-43a`'s 840/840 did. If it does not, your regimes are mixed and
  the comparison is void.

## 5. P1 — the findings that hang off it

For each, state **stands / moved / now unciteable**, with the interval and power:

1. **§1 skill decomposition** — is it still 98.88% resolution / 1.12% reliability? The repair added
   *information*, so this is where it should show up if anywhere.
2. **§2 cool bias** — −0.6641 C-eq. `-09-43a` measured centre **+0.0335** C-eq, ~5% of it, not
   powered. Does the corpus resolve it?
3. **§4d severe tail** — 4.26% of rows carrying 60.2% of loss.
4. **Centre displacement** — 74.97% of oracle excess loss. **Never weaken or bypass the serving
   floor to move this**; §3 records it as the one shipped win and centre displacement was traced to
   mass below it.

## 6. P2 — the training question the repair created

`pressure` and `pressure_trend_3h` can never be known at serve in the 11 F markets. Per the
unknowable-at-serve rule they should be **dropped from F-market training** rather than left as
learned coefficients fed a constant forever.

**Measure the cost of removing them; do not promote anything.** If the fit is not powered — likely —
say so and stop. This is a P2: **do not let it consume the mission.** If P0 is at risk, drop this.

## 7. Method — binding

- **Crossed date × market clustering** on every comparison; power before interpretation.
- **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`). `-09-43a` had to
  classify regime per captured runtime commit, **not** per folder and never by target-date age —
  its first attempt correctly blocked its own positive control for exactly this. Reuse that.
- Ledger rows are **not** market-days — deduplicate to `(market, target_date)`, then apply
  `promotion_countable`.
- **`pytest -q` on master is GREEN now** — 3,349 passed, 0 failed, as of 2026-08-08. The four
  failures `STATE_OF_PLAY` used to name are fixed, and two of them never failed. **If something is
  red, it is yours.** That is a change from every previous handoff.

## 8. Boundaries

`DELEGATION_CONTRACT.md` §2 in full.

- **Fit no promotable candidate, promote nothing, collect nothing, make no provider call.** P2's
  fit is a measurement, not a candidate.
- Do not write production `data/`, run the chain, settle a date, or restart anything.
- **Do not declare the confirmation window.** Check `reserved-confirmation-window.md` at run time;
  it wins over this handoff.
- Expect `roll_verdict.ps1` **exit 3** if you touch the model modules. It does not block you:
  production merges in the 01:00–04:00 quiet window, and **pushing a branch never rolls anything.**

## 9. What would falsify this mission

- **The gap did not move.** Then the missing 28% of inputs was worth nothing, which is a real and
  valuable answer — it redirects the whole model effort away from inputs and onto resolution.
- **It is not powered.** Report it. Do not convert a directional point into a story.
- **The gap got worse.** Stop and say so before anything else is built on the repair; that becomes
  a serving decision, not a measurement.
- **The pre-repair positive control does not reproduce.** Then the comparison is void and the
  finding is about provenance, not about the model.

## 10. Branch and report

- Branch: `codex/workstation-remeasure-the-gap-on-the-repaired-model-2026-09-44a`
- Report: `docs/roadmap/agent-report-2026-08-09-workstation-remeasure-the-gap.md`

Base on **`origin/master`**. As of tonight's 01:20 merge it carries `-09-43a` (and with it `-09-33a`,
`-38a`, `-39a`, `-41a`, `-42a`), the chain fix, and the schema-literal fix. **Confirm master
actually contains `-09-43a` before you start** — if the merge did not run, base on
`origin/codex/workstation-repair-the-blind-feature-block-2026-09-43a` and say which you used.

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll verdict
from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand. I hand-derived
one today from the closure status files, got "0 closure files", and would have called a
roll-sensitive change roll-free.
**Commit and push whenever you finish, at whatever hour.**
