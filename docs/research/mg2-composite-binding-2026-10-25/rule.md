# MG-2 composite: forward pre-registration (captured-input replay, outcome-blind accrual)

- **Status:** DRAFT for the single Fable review. `d0: UNSET` and the binding commit is not made. Nothing
  here is bound until the coordinator relays the Fable result and the binding commit sets D0.
- **Written:** 2026-10-25, before any forward MG-2 vector exists. No outcome, label, price or market row
  dated after 2026-09-29 has been read for MG-2.
- **Code:** `weather.calibration.mg2_composite` and `weather.calibration.mg2_p3d_n` on
  `claude/mg2-composite-binding-v2-20261025`.
- **Coordinator rulings it implements:**
  - design fixed, master APPROVED 2026-10-25;
  - option 3 (outcome-blind accrual) now;
  - option 2 (owner exemption) adds only the read clause in §4.3.
- **Dev numbers are selection evidence only.** Every development figure below sizes this look and
  chose the design. None of them is evidence for the forward claim, and none can pass, fail or promote
  MG-2. They come from dates many lanes have read (`DEV_WINDOW_LEDGER.md` row 32; §8 C6).

## 1. The candidate (frozen)

Each snapshot is assigned by its local hour. `SWITCH_HOUR = 13` is fixed here and in code; the rule
block below must agree with the code, or every subcommand refuses.

| Local hour | Distribution | Code |
| --- | --- | --- |
| 00-12 | **Pre-13 half.** MG-1 plus lane L6's own-observations stack. At 07-12, where the own-obs nowcast N exists: mu = v2_mean + a_h + b_h (N − v2_mean) and sigma = max(v2_stddev, 1), with MG-1's floor and band mapping. MG-1 exactly otherwise. | `free_source_candidates.l6_stack.predict` |
| 13-23 | **Post-13 half.** P3d_N: lane L2's pooled residual model on the captured NBM 07Z `v2_mean` plus an in-fold (market, season) bias (pick `1ce2b5b4…`; L2 `claude/pooled-residual-model-20261024` @ `d914ae21b`). One pooled fit per cutoff hour: OLS on [1, g, max(g, 0)], an HGB on the residual, an HGB scale, and a kernel over standardised errors. The result is floor-censored at the half-up METAR-only running max (§8 C1), with a 2% climatology mix. MG-1 is used where P3d_N has no distribution, or no mass on a band the rule-4 floor allows. | `mg2_p3d_n.serve_distribution` |

The two halves are bound separately:

- **L6 stack:** `l6_coefficients_sha256`, the sha256 of its canonical JSON (`part_sha`). It holds a_h,
  b_h for h = 07..12, fitted once on every dev snapshot through 2026-09-29, the last walk-forward fold
  extended to the end of the dev window. The dev part was `313d1743…`, fitted on the IEM nowcast. It is
  re-frozen on the captured-METAR nowcast (§8 captured-source Clarification): the bound part is
  `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9`, fitted by `mg2_composite freeze`
  on the captured dev nowcast that reproduces L3's `3806687c…` byte for byte (§7).
- **P3d_N (frozen):** `p3d_n_state_sha256`
  `c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780`. This is the sha256 of the bytes of
  L2's frozen `p3d_n_state.pkl` (schema `mg2_p3d_n_state/1`), checked before unpickling.
  - The state is L2's forward-window refit under **L2's Clarification 3** (§8):
    - Aug-Dec 2021-25 training;
    - conversion `wu_whole_f_tgroup:half_up`;
    - late-report rule `last_in_hour`.
  - L2 exported it from its own branch with `pooled_residual_model forward-fit`.
  - The state's `fit_kind` must be `forward`. Forward `emit` refuses a `dev` fit.
  - The dev fit (Aug-Sep 2021-25, 45,873 rows) is used only for the control replay (§(a)). Its state
    sha `dff5d797…` is never bound.
- **L6 own-obs nowcast:** the HGB of `upstream_obs_screen` (fixed parameters, `random_state` 0), fitted
  on the Aug-Sep 2021-25 IEM history.
  - Its serve-time inputs are the captured METAR rows, read by `mg2_composite.captured_nowcast`, which
    mirrors L3 @ `ecd8c9ba6`.
  - It is pinned by L3's captured dev nowcast sha256 `3806687c…`, which the reader must reproduce on the
    dev window (§7).
- **Shared function:** `weather.model.observed_running_max`, sha256
  `8cc4d8ec13a64419961d96b3f648420fcd55f2c4cd3da7ca431b773c8bfc224a`: L8's `f6ee3351e` plus the
  `metar_only` switch of §8 Clarification C1 (the default path is unchanged; L8's file was `bd05d6d6…`).
  The previous sha `c057e454…` differs only in the module docstring, reworded by the stack merge of
  `23cc02915`; no code line changed.

Nothing in serving, capture, release or Scheduler imports MG-2. The import fails closed from production
packages and on the capture host, and a test pins that.

### 1a. Serve parity: every input from the capture at replay time

**Requirement.** Every input to a forward MG-2 vector is read from the capture at replay time, with no
external fetch. `require_forward_parity` enforces this. Forward `emit` and `score` refuse unless every
rule-named input is registered (`mg2_composite.SOURCES`) as `captured`, and the P3d_N state sha is not
`PENDING`. Tests pin it, including an AST scan that finds no network import or URL in the binding.

| Input | Source | Captured? |
| --- | --- | --- |
| Snapshots and bands, MG-1's NBM v2 centre, spread and `guidance_physical_floor` | captured replay inputs layout | yes |
| P3d_N forecast input (`forecast_high_source: captured_nbm_v2_mean_07z`) | the snapshot's NBM 07Z `v2_mean`, used only when `v2_mean` and `v2_stddev` are finite and `v2_available_at` ≤ `captured_at_utc` | yes |
| P3d_N high_so_far (floor) and current_temp | captured METAR rows in the replay snapshots: the METAR-only running max (§8 C1) and the latest row observed by the cutoff | yes |
| L6 own-station observations for `n_own` (`own_obs_source: captured_metar_l6_own`) | captured METAR rows, used from valid + 10 min; dewpoint from the T-group; previous-day max from D−1's last snapshot | yes |

The retired dev sources (Open-Meteo Previous Runs for the former arm A, and the free IEM fetch for L6)
stay registered as `external`, and forward emission refuses them.

**Consequence today.** P3d_N's state is bound (§8 C3-binding). D0 is still set only after:
- the L6 part is re-frozen on the captured-METAR nowcast and its sha recorded;
- the Fable review, the binding commit and the input transfer (binding plan).

The dev-window control replay (`--control`, dates ≤ 2026-09-29) may load the dev P3d_N fit.

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
- **Countable dates:** local target dates that are both:
  - **input-countable.** The date's outcome-free input bundle is verified by its deadline, and the
    outcome-blind `check` passes on it. This is recorded in the append-only receipt ledger before any
    look (binding plan §9.4).
  - **promotion-countable.**

  They are counted from the branch's start date with no skipping. N = **45** countable dates. A
  non-countable date moves the 45th date one day later and never voids the look.
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

**Per-date checks.** The PIT, coverage, replay and parser checks run per date, before the look,
outcome-blind. A date that fails one is non-countable (§3) and is replaced by the next countable date.
These checks void the look only in two cases:
- a check fails on a date already in the counted 45, for example on recomputation at the look;
- an input-transfer receipt (binding plan §9.3) is missing or altered for a counted date.

- **PIT:**
  - any MG-1-path input with `v2_available_at` after `captured_at_utc`;
  - `v2_period_kind` other than maximum;
  - a P3d_N METAR row observed after the snapshot's cutoff hour, or a cutoff later than the snapshot's
    local hour;
  - under a `receipt_by` late-report rule, a replay snapshot captured after cutoff + grace;
  - on the `as_of_capture` path (§8 C4), a replay snapshot captured after the row's own capture time;
  - an L6 METAR row used before valid + 10 min.
- **Coverage:** fewer than 90% of 00-16 snapshots have an MG-2 vector (dev 99.4%).
- **Replay:** `check` does not reproduce the emitted vectors on 100% of snapshots to within 1e-12.
- **Nowcast replay:** the captured-METAR reader does not reproduce L3's captured dev nowcast `3806687c…`
  when run on the dev window.
- **P3d_N replay:** the serve function, given the dev state, does not reproduce L2's dev emission
  `dev_P3d_N.jsonl` (`721ae2cd…`) on every row to |dp| ≤ 1e-12.
- **Parser:** a parser version other than 2 on any MG-1-path row, or a forward layout that does not
  expose the parser version.
- **Hashes:** any coefficients, function, code or rule hash differs from the release binding.
- **Window leakage:** before the look, any MG-2 vector was joined to an outcome on an MG-1 reserved date
  without the §4.3 decision, or MG-1 was modified.

## 8. Clarification clause (afternoon slot only)

**Clarification C2 (2026-10-25, coordinator relay of the MG-2 pick; dated before D0): the post-13 arm
is P3d_N.** The pick result `1ce2b5b4…` selected L2's P3d_N for the 13-23 slot. It replaces the former
arm A (L3's OLS + floor on an Open-Meteo forecast), and the planned arm A′ is dropped.
- **What stays:** the switch hour, the pre-13 half, the comparator, the rule-4 floor, calibration (none),
  gates, N and void conditions.
- **The serve code:** `mg2_p3d_n.serve_distribution` copies L2's predictive math from `d914ae21b`.
- **How the copy is pinned:**
  - the control replay must reproduce L2's dev emission (§7);
  - a golden test pins the copy to distributions computed by L2's own code at that commit;
  - the binding never imports L2's module.

**Captured-source Clarification (2026-10-25; required before D0).** It satisfies §1a:
- **`forecast_high_source: captured_nbm_v2_mean_07z`.**
  - P3d_N's forecast input is the snapshot's own NBM 07Z `v2_mean`.
  - It is used only where `v2_mean` and `v2_stddev` are finite and `v2_available_at` ≤
    `captured_at_utc`; otherwise P3d_N has no distribution and MG-1 is used.
  - The hour's inputs are taken from the last replay snapshot in [h:00, h+1:00), L2's rule.
  - **The floor:** high_so_far is the METAR-only running max (C1).
  - **current_temp:** the latest METAR row observed at or before h:00.
- **`own_obs_source: captured_metar_l6_own`.** The L6 nowcast reads captured METAR rows:
  - temperature and dewpoint from the T-group (erratum, rule `deb3eae3…`);
  - rows usable from valid + 10 min, maximum age 90 min;
  - the previous-day max from D−1's last captured snapshot (at least 20 routine rows).
  - This is `mg2_composite.captured_nowcast`, matching L3 @ `ecd8c9ba6`.
  - The L6 stack is re-frozen on its dev output, and the new part sha replaces the rule block's.
- **Neither is an external fetch.** The readers' code files (`mg2_p3d_n.py`, `mg2_composite.py`,
  `r0_ols_floor_challenger.py`) are in the release binding.
- **Sizing.** If a refit changes the candidate, the §5 sizing is re-run on the refitted design. N stays
  45 unless a Clarification changes it before D0.

**L2's Clarification 3 (owned by L2; dated before D0): the forward-window P3d_N refit.** It records:
- the training window, Aug-Nov or Aug-Dec 2021-25;
- the rounding rule for converting serve-time high_so_far and current_temp to WU whole °F (the state's
  `conversion.rule_id`, which `mg2_p3d_n.CONVERSION_RULES` must implement);
- the late-report rule (`last_in_hour`, or `receipt_by` with its grace in minutes);
- the frozen state sha, which becomes `p3d_n_state_sha256`.

The dev control runs with the conversion disabled.

**Clarification C3-binding (2026-10-25, coordinator relay of L2's Clarification 3; dated before D0):
P3d_N's forward state is bound.**
- **L2's rule:** `C:\t\l2\rule.md`, sha256 `fa4257dffe192016da9b72d261a786e894dbc6478a9b4ebb6c3762fe15ee7eea`.
- **The frozen artifacts:**
  - state `p3d_n_state.pkl`, sha256 `c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780`, with
    `fit_kind` forward;
  - sidecar `f5409444a4ce823f6396f538aa6ff2efbf1710e9d646f503ceb00931914e4b3e`;
  - frozen record `5d53f5569b02e0d1bdf5c22341075e88ca893347da9fe16a4c650c7c8245a410`.
  - These are local runtime evidence and not committed. Each sha was re-verified from the file bytes at
    binding.
- **Training:** Aug-Dec 2021-25, with centres 08-08 to 12-09 (9).
  - At serve, the bias, normal and buckets come from the nearest centre by month-day; a tie goes to the
    first centre.
  - The buckets are each market's sorted union across the centres.
  - p_clim is not floor-censored.
- **Conversion `wu_whole_f_tgroup:half_up`** (`mg2_p3d_n.wu_whole_f_tgroup_half_up`):
  - It applies to serve-time high_so_far and current_temp, before g, the floor and the features.
  - Step 1: the T-group tenths t are recovered from the captured `temp_native` (C × 1.8 + 32). A value
    more than 1e-6 °F off that grid is refused.
  - Step 2: WU whole °F = floor(32 + 9t/50 + 1/2), computed in exact rationals.
  - The evidence `wu_rounding.json` is `0a67338f…`: half-up matched 227,969 of 227,999 training-year rows
    and 352 of 354 exact ties.
- **Late report `last_in_hour`** (grace null):
  - At cutoff h, P3d_N uses METAR rows observed at or before h:00, as received in the last capture
    snapshot in [h:00, h+1:00). This is the dev and pick semantics.
  - Its roles, and the no-look-ahead arm, are set by C4.
- **No scoring.** The forward state is never scored on 2026 dev dates (L2's Clarification 3). The only
  2026 use before D0 is a single-row load-and-serve smoke test.

**Clarification C4 (2026-10-25, coordinator ruling, with master's partial veto; dated before D0): two
input paths and their roles.** `last_in_hour` (C3-binding) looks ahead on *receipt* within the hour, but
never on *observation*:
- a vector for a 13:05 snapshot can use a report observed at 12:59 that is first received in the 13:40
  capture;
- no row observed after h:00 is ever used;
- a live process at 13:05 would see less.

The forward emission therefore runs two paths on the same forward rows:
- **`last_in_hour`: `mg2_vectors.parquet`.**
  - **PRIMARY for the MG-2 vs MG-1 gate** (§5). It reproduces what was picked, and the gate is symmetric,
    because MG-1 is scored on the same snapshot rows.
  - DESCRIPTIVE for any comparison against the market.
- **`as_of_capture`: `mg2_vectors_asof_capture.parquet`** (arm `p3d_n_asof_capture`).
  - Each row reads only the latest replay snapshot captured at or before that row's own
    `captured_at_utc`. No METAR row received after that snapshot can enter, and only rows observed at or
    before h:00 count. The composite is otherwise identical: the same pre-13 half, MG-1 fallback and
    rule-4 floor.
  - **PRIMARY for every comparison against the market:** the blend R, every edge read and the formal
    edge test. A 13:05 price cannot be beaten with rows that arrive at 13:40, and look-ahead biases
    toward a false edge.
  - DESCRIPTIVE for the MG-1 gate: it is reported beside it and never feeds the gate.
- **Enforcement:**
  - `score` refuses any vectors file other than `mg2_vectors.parquet`.
  - The emit audit records `vector_roles`.
  - `emit_rows(inputs="as_of_capture")` refuses any window that starts on or before 2026-09-29, so the
    arm is never computed on a dev row.
  - Tests pin that a late-arriving row (observed 12:59, received 13:40) does not reach a 13:20 row, and
    that the gate cannot read the as-of vectors.

**Clarification C5 (2026-10-25, coordinator ruling; dated before D0): training coverage.**
- **The rule:** P3d_N covers a forward target date only if its month-day lies within its training
  coverage, **08-01..12-16 inclusive** (L2's Clarification 3 (a)).
- **Outside the coverage:** the afternoon slot falls back to MG-1, which covers late December and
  January.
  - Each such row is logged in `mg2_post_coverage_fallback.jsonl` and in the audit's
    `coverage_fallback`.
  - It applies to both C4 paths.
- **The centre distance:** the nearest-centre month-day distance does not wrap across the year end. An
  early-January date would otherwise pick the 08-08 centre. The coverage rule makes this harmless, so
  `nearest_centre` is not patched.
- **Kept regardless of D0:** the rule stays even if D0 places all 45 dates within 12-16, in which case it
  never triggers.
- **A noted gap:** L2's covered dates have a gap at 09-30..10-02 that lies inside the coverage range.
  These dates are served from the 09-22 or 10-10 centre, and no forward date falls in it.

**Clarification C1 (2026-10-25, master's ruling; dated before D0): `high_so_far` is the METAR-only
running max.** Weather Underground-sourced station rows do not travel to the workstation (binding plan
§9), so MG-2's `high_so_far` (P3d_N's feature and its floor) is defined on captured METAR alone:
`observed_running_max.running_max_since_midnight(station={}, metar=sources.metar.data, ...,
metar_only=True)`, on the snapshot's own `sources.metar.data`, cutoff h and now = capture time.
- `metar_only` defaults to False, so the serve path is unchanged. Whenever the station surface is
  METAR-sourced, the METAR-only value equals the serve value
  (`tests/model/test_high_so_far_parity_shadow.py`).
- The capture carries no `sources.station` key, so the dev emission already used METAR rows only; the
  control replay re-confirms the dev vectors under C1.
- `function_sha256` below is the edited `observed_running_max.py` (the `metar_only` switch).
- The rule-4 floor F is MG-1's and unchanged: it reads the served `high_so_far` column of
  `features_long.csv`, not this value.

**Clarification C6 (2026-10-25, bookkeeping; dated before D0): ledger row numbers.** The stack merge of
`23cc02915` kept the other lanes' rows 20-31 in `DEV_WINDOW_LEDGER.md` and renumbered MG-2's two rows:
the MG-2 dev read is row 32 (was 20) and L8's parity fix is row 33 (was 21). This rule now cites rows 32
and 33. The frozen dev rule (`dev_rule.md`, `18e4c1ad…`) is not edited; its "row 20" means row 32. No
number, input or decision changes.

**Clarification C7 (2026-10-25, master's ruling; dated before D0): the forward gate is as-of-capture.**
It supersedes C4's gate role for `last_in_hour` and changes nothing else.
- **Why:** MG-1 is scored at capture time, but the `last_in_hour` path keeps the last snapshot in
  [h:00, h+1:00) and so lets P3d_N read rows received up to 60 minutes after the row's own capture
  (C4). Lane L2's diagnostic found that asymmetry (branch `claude/rung0712-20261025` @ `fb58fec5d`,
  `docs/research/l2-pooled-residual-2026-10-24/p3dn_diag/diag_summary.md`, score `ceb4b3ac…`).
- **Forward rows (the gate):** the MG-2 vs MG-1 gate (§5, G1 and G2) scores
  `mg2_vectors_asof_capture.parquet`. Its P3d_N half comes from `emit_rows(inputs="as_of_capture")`:
  each row reads only the latest replay snapshot captured at or before its own `captured_at_utc`. MG-1,
  the pre-13 half, the MG-1 fallback and the rule-4 floor are unchanged.
- **The market arm:** C4's use stays as it is. The as-of-capture vectors remain PRIMARY for every
  comparison against the market, so the gate and the market arm now read the same vectors.
- **`last_in_hour` (`mg2_vectors.parquet`):** still emitted on forward rows, DESCRIPTIVE only, and never
  scored by the gate.
- **Dev rows:** the as-of-capture path is never computed on a dev row (C4). The dev control replay
  (§(a)) stays on `last_in_hour`, which reproduces the dev control vectors `8f3e5895…` exactly; it is a reproduction check,
  not a gate.
- **Expected size (dev re-score by L2, selection evidence only):** with the fix, G1 is −0.0048
  [−0.0065, −0.0033] and G2 (13-16) −0.0151 [−0.0192, −0.0113], against −0.0049 and −0.0155 on
  `last_in_hour`. No gate flips; the fix costs about +0.0004, roughly 3% of the effect.
- **Enforcement:**
  - `score` refuses any vectors file other than `mg2_vectors_asof_capture.parquet`.
  - It also refuses one whose sha256 is not the `asof_capture.vectors_sha256` of a forward
    `mg2_emit_audit.json` beside it, so a renamed `last_in_hour` file cannot pass.
  - The forward emit audit records `gate_vectors`.
  - `tests/calibration/test_mg2_c7_gate.py` pins the refusal and the acceptance.

**Clarification C8 (2026-10-25, master's ruling, not the owner's; dated before D0): Denver leaves the
gate.** The G1/G2 gate population (§5) is the 10 markets without Denver.
- **Why:** Denver settles on KDEN from the 2026-10-23 events, while MG-1 and MG-2 model KBKF. Denver
  dates from 10-23 are unsupported for model scoring until a KDEN model passes the gates
  (`docs/operations/DECISION_LOG.md`, 2026-10-23, "Denver settles on KDEN from the 10-23 events";
  `docs/operations/STATE_OF_PLAY.md`; study `docs/research/denver-kden-vs-kbkf-2026-10-23.md`). Every
  forward date is after 10-23.
- **Scope:** only the gate population changes. Emission, the vectors, the dev control replay, the margin
  and the switch hour are unchanged, and Denver rows are still emitted (DESCRIPTIVE).
- **Expected size (dev, 08-15..09-29, `last_in_hour` per C7, selection evidence only):** the composite's
  own dev run on L2's dev P3d_N distributions and the captured nowcast; component controls are exact (max
  abs 0). The dev control replay with the C7 and C8 code still reproduces the dev control vectors
  `8f3e5895…` exactly (max abs 0).

| Gate | 11 markets (473 cells) | 10 markets, no Denver (430 cells) |
| --- | --- | --- |
| G1 Δ(00-16) | −0.0049 [−0.0064, −0.0034] | −0.0049 [−0.0065, −0.0034] |
| G2 Δ(13-16) | −0.0155 [−0.0195, −0.0117] | −0.0150 [−0.0189, −0.0115] |

- **Enforcement:**
  - `mg2_composite.GATE_EXCLUDED_MARKETS = ("denver",)`.
  - `score` restricts every layout frame to the gate population before it builds the table, and records
    `gate_excluded_markets`.
  - The dev sizing reports `gate_groups` beside the 11-market groups.
  - `tests/calibration/test_mg2_c8_gate.py` pins that Denver rows never reach the gate.

After D0 nothing in §1-§7 changes. The only exception is the §4.3 owner-decision Clarification, which
changes permission, not design.

## 9. Input overlap with MG-1 (recorded explicitly)

| Input | MG-1 | MG-2 before 13:00 | MG-2 from 13:00 |
| --- | --- | --- | --- |
| NBM v2 `v2_mean`, `v2_stddev`, `v2_available_at` (captured) | centre and spread | identical centre plus stack, identical spread | only through the MG-1 fallback |
| `guidance_physical_floor` (NBM-derived), `high_so_far`, `trusted_current_max` (rule-4 floor F) | B = floor(F + 0.5) | identical | identical (rule-4 mask), plus P3d_N's own floor at half-up of the L8 running max |
| NBM 07Z `v2_mean` (captured), as P3d_N's forecast input | centre | identical | P3d_N's g and mu0, plus the MG-1 fallback |
| Captured METAR rows, L6 reader (valid + 10 min, T-group dewpoint) | none | L6 nowcast N | none |
| Captured METAR rows; L8 running max, METAR-only (§8 C1) | none | none | current_temp, high_so_far |

MG-2 now shares NBM `v2_mean` with MG-1 in both halves, which strengthens §4.2's family membership.
The former dev sources (the IEM fetch and Open-Meteo Previous Runs) are retired and refused forward (§1a).

## (a) Positive control

These are the replay positive controls for the forward code:
- **P3d_N serve control, passed 2026-10-25.**
  - The setup: `mg2_p3d_n control` refit L2's dev fit with L2's own code at `d914ae21b`, exported it
    through `write_state` and `load_state`, and re-emitted it on the captured replay rows with
    `serve_distribution`.
  - The result: all 79,403 rows of `dev_P3d_N.jsonl` were reproduced, with no missing or extra row, no
    bucket-set mismatch, and max |dp| = 0.0.
  - The output is byte-identical to `721ae2cd…` after line-ending normalisation (L2's file is CRLF).
  - The dev state's sha is recorded in the control output as never bound.
- **Earlier dev controls** (on the former arm A design; selection only):
  - pre-13 composite = L6 own-obs twin on every band, max abs 0.0;
  - Δ(07-12) = −0.0036243, L6's control exactly.
- **The L6 captured reader** must reproduce L3's `3806687c…` on the dev window (§7).
- **Self-reproduction:** `check` must reproduce its own emission to 1e-12.

The §5-§6 dev figures were measured on the arm A composite. The 13-23 figures are re-run on P3d_N under
the captured-source Clarification before D0.

## (b) Comparator fairness

MG-1 gets the same floor as MG-2: the rule-4 floor mask, B = floor(F + 0.5). It also gets the same
calibration, which is none, because MG-1 has no calibration stage and MG-2 adds none. Both use the same
served fallback and the same cells.

## (c) Targeted loss slice

The slice is 13-16 local, the P3d_N slot. The two figures below are from the arm A design.
- Loss atlas `46a66f7b7727` attributes 76.1% of the 00-16 excess (0.0256) to the centre.
- Dev Δ(13-16) is −0.01037 (dR −0.3662), selection only.

## (d) MDE and clusters

- **MDE80 at N = 45:** 0.0060 (13-16) and 0.0022 (00-16).
- **Clusters:** 45 date clusters × 11 markets, fixed-market date-clustered (dev sizing on 43 date
  clusters).

## (e) Dev-window reuse

`DEV_WINDOW_LEDGER.md` row 32 (§8 C6). The reuse count at the sizing read was 21; row 33, L8's parity
fix scored 2026-10-24, was recorded late. The forward look reads no dev-window date.

## Release binding

Release binding is recorded in `release-binding.json` in the binding commit. It holds:

- the binding commit sha;
- the sha256 of every code file MG-2 executes:
  - `mg2_composite.py`
  - `l6_stack.py`
  - `mg1.py`
  - `upstream_obs_screen.py`
  - `mg2_p3d_n.py` (the P3d_N serve function, state loader and replay reader)
  - `r0_ols_floor_challenger.py` (the METAR cutoff reader and the L6 captured-METAR parser)
  - `r0_ols_floor_devfit.py`
  - `observed_running_max.py`
  - `dev_scorecard.py`
  - `dev_scorecard_data.py`
  - `loss_atlas.py`
  - `mg2_inputs.py` and `mg2_input_allowlist.py` (the input receiver, the label-free layout builder and
    the bundle allow-list; plan §9)
  - `guidance_extract_parser.py` (the pinned v2 parser client)
- the function sha256 above;
- the L6 coefficient part sha256 and the P3d_N state sha256 above;
- the two named input sources;
- this file's raw sha256.

Forward `emit` and `score` refuse on any mismatch.

**Flagged, not resolved here:** the retrain window is armed, not dated, and holds dates against
retrain-family candidates. P3d_N is a pooled refit on historical data. If that window is declared and
P3d_N is ruled to be in the retrain family, the overlap needs an owner ruling.

```mg2_rule_v1
switch_hour: 13
d0: UNSET
n_forward_dates: 45
owner_decision_id: NONE
l6_coefficients_sha256: 07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9
p3d_n_state_sha256: c6cc39f7b57f668557415d28ec37ac291694f4b429e572a3c178fb74e5a9c780
forecast_high_source: captured_nbm_v2_mean_07z
own_obs_source: captured_metar_l6_own
function_sha256: 8cc4d8ec13a64419961d96b3f648420fcd55f2c4cd3da7ca431b773c8bfc224a
noninferiority_margin_00_16: 0.0010
```
