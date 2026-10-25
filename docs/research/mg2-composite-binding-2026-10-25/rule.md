# MG-2 composite: forward pre-registration (captured-input replay, outcome-blind accrual)

- **Status:** DRAFT for the single Fable review. `d0: UNSET` and the binding commit is not made. Nothing
  here is bound until the coordinator relays the Fable result and the binding commit sets D0.
- **Written:** 2026-10-25, before any forward MG-2 vector exists. No outcome, label, price or market row
  dated after 2026-09-29 has been read for MG-2.
- **Code:** `weather.calibration.mg2_composite` on `claude/mg2-composite-binding-20261025`.
- **Coordinator rulings it implements:**
  - design fixed, master APPROVED 2026-10-25;
  - option 3 (outcome-blind accrual) now;
  - option 2 (owner exemption) adds only the read clause in §4.3.
- **Dev numbers are selection evidence only.** Every development figure below sizes this look and
  chose the design. None of them is evidence for the forward claim, and none can pass, fail or promote
  MG-2. They come from dates many lanes have read (`DEV_WINDOW_LEDGER.md` row 20).

## 1. The candidate (frozen)

Each snapshot is assigned by its local hour. `SWITCH_HOUR = 13` is fixed here and in code; the rule
block below must agree with the code, or every subcommand refuses.

| Local hour | Distribution | Code |
| --- | --- | --- |
| 00-12 | **Pre-13 half.** MG-1 plus lane L6's own-observations stack. At 07-12, where the own-obs nowcast N exists: mu = v2_mean + a_h + b_h (N − v2_mean) and sigma = max(v2_stddev, 1), with MG-1's floor and band mapping. MG-1 exactly otherwise. | `free_source_candidates.l6_stack.predict` |
| 13-23 | **Post-13 half.** Arm A: L3's OLS + hard floor on (forecast_high, high_so_far, current_temp), discretised on integer native buckets. high_so_far comes from lane L8's `running_max_since_midnight`. MG-1 is used where arm A has no distribution, or no mass on a band the rule-4 floor allows. | `mg2_composite.arm_a_distribution` |

The coefficients are bound as two parts, each by the sha256 of its canonical JSON (`part_sha`), so arm A
can be re-frozen without touching L6:

- **L6 stack (frozen):** `l6_coefficients_sha256` `313d1743d35ed705a4406fb415748c8e161d170033bb963ec6b56f5caf922895`.
  It holds a_h, b_h for h = 07..12, fitted once on every dev snapshot through 2026-09-29. This is the
  last walk-forward fold extended to the end of the dev window.
- **Arm A (PENDING):** `arm_a_coefficients_sha256: PENDING`, and arm A's forecast input
  `forecast_high_source: PENDING` (§1a).
  - The dev fit is one OLS (beta and residual sd) per market × cutoff hour 07-20, on the Aug-Sep
    2021-25 PIT corpus `b455bd53…` at centre 2026-09-07, with forecast_high from Open-Meteo Previous
    Runs. Its part sha is `dba2cbc4…`.
  - It is **not** bound: that forecast input is not in the capture (§1a). The part is re-frozen on the
    captured-forecast analogue once master rules on L3's refit. Its sha is then written here by a dated
    Clarification before D0 (§8).
- **L6 own-obs nowcast:** the HGB of `upstream_obs_screen` (fixed parameters, `random_state` 0), fitted
  on the Aug-Sep 2021-25 IEM history. It is pinned by the dev nowcast sha256 `d2453d0d…`, which the
  frozen refit must reproduce (§7).
- **Shared function:** `weather.model.observed_running_max`, sha256
  `bd05d6d601b9c5886783fc6c77d8cc6c95150f0d4577aa73562159c402e010c5`, identical to L8's `f6ee3351e`.

Nothing in serving, capture, release or Scheduler imports MG-2. The import fails closed from production
packages and on the capture host, and a test pins that.

### 1a. Serve parity: every input from the capture at replay time

**Requirement.** Every input to a forward MG-2 vector is read from the capture at replay time, with no
external fetch. `require_forward_parity` enforces this. Forward `emit` and `score` refuse unless every
rule-named input is registered (`mg2_composite.SOURCES`) as `captured`, and arm A's coefficients are not
`PENDING`. Tests pin it, including an AST scan that finds no network import or URL in the binding.

| Input | Source | Captured? |
| --- | --- | --- |
| Snapshots and bands, MG-1's NBM v2 centre, spread and `guidance_physical_floor` | captured replay inputs layout | yes |
| high_so_far (L8 `running_max_since_midnight`), current_temp | captured METAR rows in the replay snapshots | yes |
| Arm A forecast_high (`forecast_high_source`) | dev: Open-Meteo Previous Runs `gfs_seamless` `previous_day1` from a PIT corpus | **no**: no serve-path module fetches it (L2 P3d serve-parity note). PENDING. |
| L6 own-station observations for `n_own` (`own_obs_source`) | dev: IEM ASOS own-station observations, a free fetch | **no**: not read from the capture. PENDING. |

**Consequence today.** Both named sources are PENDING, so MG-2 cannot emit a forward vector and its
accrual cannot start. D0 is set only after:
- a dated Clarification (§8) names a captured reader for each named input;
- arm A's re-frozen part sha is recorded;
- the L6 nowcast is re-established on captured observations, if its coefficients change.

The dev-window control replay (`--control`, dates ≤ 2026-09-29) still uses the dev sources. Its audit
records them as not captured.

## 2. The comparator

The comparator is MG-1 (`r-t5-inc-c1`, `loss_atlas.mg1_frame`) on the same snapshots and cells. MG-1
itself falls back to the served vector of record.

## 3. Population, dates and the single look

- **Scorer:** `mg2_composite score`, which is the dev scorecard's own `Table` and `score_rows`. It
  computes:
  - per-snapshot band Brier;
  - equal snapshot weights within a (date, market) cell, then equal cells;
  - the rule-4 floor mask;
  - served fallback for snapshots neither vector covers.
- **Markets:** the fixed 11 US markets.
- **Countable dates:** promotion-countable local target dates, counted from the branch's start date with
  no skipping. N = **45** countable dates.
- **Exactly one look.** There is no interim outcome look. The look's output carries a receipt, and a
  second look is not run.
- **Branch is fixed before any read**, by whether a dated owner decision id is recorded (§4.3) before
  MG-1's look completes:
  - **Branch 2 (owner exemption):**
    - The look's dates are the first 45 countable dates from **D0**, the first local target date after
      the binding commit.
    - Earliest read: the later of two events. One is the settlement of the 45th date. The other is the
      completion of MG-1's look.
    - Example: D0 = 2026-10-28 with every date countable makes the 45th date 2026-12-11, so the read is
      on or after 2026-12-12. That is after MG-1's provisional last date, 2026-11-28.
  - **Branch 1 (no exemption, post-window fallback):**
    - The look's dates are the first 45 countable dates after `weather.mg1_reserved_window.MG1_LAST`.
      Today that is from 2026-11-29; it moves later whenever MG1_LAST does.
    - Earliest read: after the 45th has settled. Today that is the 45th date 2027-01-12, with the read
      on or after 2027-01-13.
  - Whichever branch is in force, the other branch's dates are never scored by MG-2.

## 4. The MG-1 reserved window, and how MG-2 handles it

### 4.1 The governing clauses (quoted)

**Scope row**, `docs/operations/reserved-confirmation-window.md` (identical in §7 of the MG-1
pre-registration at `02c410a5`):

> Reserved **only** against reading or modifying the morning guidance-read (forecast-scoring) family: do not score, enumerate outcomes for, or join to an outcome the MG-1 vector or any other candidate that reads NBM station guidance into band probabilities (including the held RV-1 and HG-1), do not substitute reserved dates for such a candidate, and do not modify MG-1, without a new explicit owner decision.

The exemption in the same row: "outcome-blind operational checks (coverage, PIT, replay reproduction,
parser version) are permitted."

**MG-1 pre-registration §6** (void conditions):

> **Window leakage:** before the look, any MG-1 vector or any morning guidance-read-family candidate was joined to an outcome (winner, settlement or Brier) on a reserved date, or MG-1 was modified (§7 scope). Uses §7 leaves untouched do not void the look.

**MG-1 pre-registration §5** (inference):

> **One look**, after the 45th counted date has settled. No interim outcome look.

### 4.2 Why MG-2 is in the reserved family, and what MG-2 does now (option 3)

**Why it is in the family:** MG-2 reads NBM station guidance into band probabilities in three places:
- before 13:00, through MG-1's centre and spread;
- in every hour, through the rule-4 floor, which includes `guidance_physical_floor`;
- after 13:00, through the MG-1 fallback.

Any MG-2 − MG-1 comparison also joins the MG-1 vector to outcomes.

**What MG-2 does now:** inside the window it uses only the permitted outcome-blind checks.

- **Accrual:** from D0, `mg2_composite emit` replays the composite from captured inputs at the frozen
  hashes, and `mg2_composite check` runs four checks:
  - coverage;
  - PIT;
  - replay reproduction;
  - parser version.
- **Input guard:** the accrual reads `inputs_snapshots.parquet` and `inputs_bands.parquet` only, and
  refuses label or market columns. It never opens label, settlement, price or market files.
- **No outcome contact:** no MG-2 vector is joined to a winner, settlement or Brier, scored, or used to
  enumerate outcomes on a reserved date.
- **Scorer guard:** the scorer refuses any target date on or before `MG1_LAST` (or every date from the
  floor while the window is open-ended), unless this rule carries a dated owner decision id. This is
  test-pinned.

MG-2 does not modify MG-1.

### 4.3 The read clause (option 2), inactive until a dated owner decision exists

An explicit owner decision, recorded with a dated id `OD-YYYY-MM-DD-<slug>`, may exempt MG-2's
reserved-window dates. Branch 2 is then in force:

- **Single look, strictly after MG-1's.** The scorer refuses until:
  - an MG-1 look receipt is given, and
  - the recorded MG-1 window has closed.
- **Recording.** The owner decision is recorded in a dated Clarification to this file, which sets only
  `owner_decision_id`, plus the owner's DECISION_LOG row and the reservation file's status line and
  table. Those edits are the owner's; this lane edits neither file.
- **Timing.** That Clarification may be dated after D0, because it changes no estimand, gate, N, input,
  code or coefficient, only permission to read. It must be dated before MG-1's look completes;
  otherwise Branch 1 is in force.

## 5. Forward gate (primary)

**Estimand:** Δ = mean over equal (date, market) cells of [Brier(MG-2) − Brier(MG-1)].

**Interval:**
- Fixed-market, date-clustered percentile 95% interval (the scorecard's `w_date`: 2,000 draws,
  seed 20260921).
- Each gate is one-sided at α 0.025.
- The crossed date × market interval is reported beside it.

**Pass** requires both:
- **G1, no worse than MG-1 overall, 00-16:** the upper bound of Δ(00-16) < **+0.0010**. This
  non-inferiority margin is about 27% of the dev 00-16 gain.
- **G2, better than MG-1 at 13-16:** the upper bound of Δ(13-16) < **0**.

**Fail** is anything else. The two gates form an intersection-union test, so no multiplicity adjustment
applies.

**Sizing** for N = 45 forward dates uses the dev-window variance. Per N, I took a date-cluster bootstrap
of the dev cells (2,000 draws, seed 20261025), with MDE80 = (1.960 + 0.842) × SE:

| Gate | Dev point (selection only) | SE at N = 45 | MDE80 | Power at dev point | Power at half the dev point |
| --- | ---: | ---: | ---: | ---: | ---: |
| G2: 13-16 superiority | −0.01037 | 0.00213 | 0.0060 | 0.998 | 0.683 |
| G1: 00-16 non-inferiority (margin +0.0010) | −0.00368 | 0.00078 | 0.0022 | > 0.999 | 0.951 |

At a true Δ(00-16) of exactly 0, G1's power is 0.247.

Caveats on the sizing:
- **Winner's curse.** The dev point is a selected estimate and shrinks forward. The half-effect column is
  the honest planning figure: at N = 45, G2 is powered at about 68% for half the dev effect.
- **Season.** The variance is Aug-Sep. Oct-Jan variance may differ.

N = 60 would raise G2's half-effect power to 0.80 and delay each read by 15 dates. N stays 45, matching
MG-1's count.

## 6. Secondary measures (no α; reported beside the gate)

Each half is scored separately against MG-1 on the same cells:
- **Pre-13:** Δ(00-12) and Δ(07-12).
- **Post-13:** Δ(13-16) and Δ(17-23).

Also reported:
- per hour 07-16;
- per-market signs;
- dR = Δ over mean_cell(Brier_market);
- the crossed interval.

The dev values, selection only:

| Block | Δ | 95% |
| --- | ---: | --- |
| 00-12 | −0.00169 | [−0.00258, −0.00082] |
| 07-12 | −0.00362 | [−0.00552, −0.00179] |
| 13-16 | −0.01037 | [−0.01474, −0.00639] |
| 17-23 | −0.03584 | [−0.04077, −0.03135] |
| h13 | +0.00048 | [−0.00369, +0.00460] |

h13 is the one hour with no dev gain; it is reported, not gated.

## 7. Void conditions

If any of these fails, the look is VOID: no pass and no fail. The dates are spent and not re-run.

- **PIT:**
  - any MG-1-path input with `v2_available_at` after `captured_at_utc`;
  - `v2_period_kind` other than maximum;
  - an arm A METAR row observed after the snapshot's cutoff hour, or a cutoff later than the snapshot's
    local hour;
  - an L6 market row used before valid + 10 min.
- **Coverage:** fewer than 90% of 00-16 snapshots have an MG-2 vector (dev 99.4%).
- **Replay:** `check` does not reproduce the emitted vectors on 100% of snapshots to within 1e-12.
- **Nowcast replay:** the frozen L6 refit does not reproduce the dev nowcast `d2453d0d…` when run on the
  dev window.
- **Parser:** a parser version other than 2 on any MG-1-path row, or a forward layout that does not
  expose the parser version.
- **Hashes:** any coefficients, function, code or rule hash differs from the release binding.
- **Window leakage:** before the look, any MG-2 vector was joined to an outcome on an MG-1 reserved date
  without the §4.3 decision, or MG-1 was modified.

## 8. Clarification clause (afternoon slot only)

A historical-fit arm A′ may replace arm A in the post-13 slot through a dated Clarification before D0.
A′ is arm A plus an NBM mean regressor, fitted on lane L9's PIT NBM corpus, which is pending.

- **What stays:** the switch hour, the pre-13 half, the comparator, floor, calibration, gates, N and
  void conditions.
- **What the Clarification records:** A′'s frozen coefficients sha256 and code sha, re-frozen before D0.

**Captured-source Clarification (required before D0).** A dated Clarification must also be made before
D0 to satisfy §1a. It records:
- the captured reader registered for `forecast_high_source`, and for `own_obs_source`;
- arm A's (or A′'s) coefficients refitted on that captured forecast, with their part sha;
- if the L6 nowcast moves to captured observations, its refit, its new control sha and the L6 part sha;
- if any refit changes the candidate, the §5 sizing re-run on the refitted design. N stays 45 unless that
  Clarification changes it before D0.

Neither may be an external fetch. This Clarification also adds the readers' code files to the release
binding.

After D0 nothing in §1-§7 changes. The only exception is the §4.3 owner-decision Clarification, which
changes permission, not design.

## 9. Input overlap with MG-1 (recorded explicitly)

| Input | MG-1 | MG-2 before 13:00 | MG-2 from 13:00 |
| --- | --- | --- | --- |
| NBM v2 `v2_mean`, `v2_stddev`, `v2_available_at` (captured) | centre and spread | identical centre plus stack, identical spread | only through the MG-1 fallback |
| `guidance_physical_floor` (NBM-derived), `high_so_far`, `trusted_current_max` (rule-4 floor F) | B = floor(F + 0.5) | identical | identical (rule-4 mask), plus arm A's own floor at half-up of the L8 running max |
| Own-station ASOS (IEM, free, PIT valid + 10 min) | none | L6 nowcast N | none |
| METAR captured rows; L8 running max | none | none | current_temp, high_so_far |
| Open-Meteo Previous Runs `gfs_seamless` `previous_day1` (free, PIT by cutoff) | none | none | forecast_high |

**Not captured inputs.** The IEM row and the Open-Meteo row are the dev sources. Both came from later
free fetches, not from capture:
- the IEM own-station observations;
- the Open-Meteo Previous Runs forecast.

They are not allowed forward (§1a). Each is replaced by a captured reader through the §8
captured-source Clarification before D0, and until then the forward path refuses.

## (a) Positive control

The dev controls reproduced, and are the replay positive control for the forward code:
- pre-13 composite = L6 own-obs twin on every band, max abs 0.0;
- post-13 = arm A where arm A is used, MG-1 elsewhere, max abs 0.0;
- Δ(07-12) = −0.0036243, L6's control exactly.

The forward `emit` on dev dates must reproduce L3's dev arm A distributions exactly, and `check` must
reproduce its own emission to 1e-12.

## (b) Comparator fairness

MG-1 gets the same floor as MG-2: the rule-4 floor mask, B = floor(F + 0.5). It also gets the same
calibration, which is none, because MG-1 has no calibration stage and MG-2 adds none. Both use the same
served fallback and the same cells.

## (c) Targeted loss slice

The slice is 13-16 local, the arm A slot.
- Loss atlas `46a66f7b7727` attributes 76.1% of the 00-16 excess (0.0256) to the centre.
- Dev Δ(13-16) is −0.01037 (dR −0.3662), selection only.

## (d) MDE and clusters

- **MDE80 at N = 45:** 0.0060 (13-16) and 0.0022 (00-16).
- **Clusters:** 45 date clusters × 11 markets, fixed-market date-clustered (dev sizing on 43 date
  clusters).

## (e) Dev-window reuse

`DEV_WINDOW_LEDGER.md` row 20. The reuse count at the sizing read was 21; row 21, L8's parity fix
scored 2026-10-24, was recorded late. The forward look reads no dev-window date.

## Release binding

Release binding is recorded in `release-binding.json` in the binding commit. It holds:

- the binding commit sha;
- the sha256 of every code file MG-2 executes:
  - `mg2_composite.py`
  - `l6_stack.py`
  - `mg1.py`
  - `upstream_obs_screen.py`
  - `r0_ols_floor_challenger.py`
  - `observed_running_max.py`
  - `dev_scorecard.py`
  - `dev_scorecard_data.py`
  - `loss_atlas.py`
- the function sha256 above;
- the L6 and arm A coefficient part sha256s above;
- the two named input sources;
- this file's raw sha256.

Forward `emit` and `score` refuse on any mismatch.

**Flagged, not resolved here:** the retrain window is armed, not dated, and holds dates against
retrain-family candidates. Arm A is an OLS challenger to R0. If that window is declared and arm A is
ruled to be in the retrain family, the overlap needs an owner ruling.

```mg2_rule_v1
switch_hour: 13
d0: UNSET
n_forward_dates: 45
owner_decision_id: NONE
l6_coefficients_sha256: 313d1743d35ed705a4406fb415748c8e161d170033bb963ec6b56f5caf922895
arm_a_coefficients_sha256: PENDING
forecast_high_source: PENDING
own_obs_source: PENDING
function_sha256: bd05d6d601b9c5886783fc6c77d8cc6c95150f0d4577aa73562159c402e010c5
noninferiority_margin_00_16: 0.0010
```
