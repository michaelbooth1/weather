# R-ODC gate 2: design for master's review (2026-10-28)

- **Status:** DESIGN ONLY, for master's review. No G2 code exists, and none is written before master rules on
  this file. G2 is held until Sun 2026-11-01. `rule_rodc.md` (sha256
  `40ea3a94d08601dc7c571e59fdf38c893ec9a313bdcbcebde214e1db3f9daf93`) is not edited here. Line cites `Lnnn`
  are to that file.
- **Ruling it implements (master, 10-28):** "G2 must use a comparator fit for the season it scores, or report vs
  MG-1 as primary". The ruling is also recorded in [the gate 1 run note](gate1-run-note-2026-10-28.md).
- **Written blind.** No outcome, label or price after 2026-09-29 is read for this design, and none will be read
  for G2. Its only outcome rows are the Oct-Dec 2021-25 history rows gate 1 already read (key set `08704eff…`,
  24,734 rows).
- **Gate 1 context:** PASS, dR(G1 vs COMP) −0.0248 [−0.0276, −0.0220] (`gate1.json` `6f26c5a2…`, ledger row 65).
  It is labelled "vs the Aug-Sep-centred frozen blend (item 341)": COMP's P3d_H was fitted on Aug-Sep rows only
  (L90), so part of that dR may be COMP's season error rather than R-ODC skill.

## (a) The G2 arms as declared

| Element | Declared | Cite |
| --- | --- | --- |
| G2 | G1 with exactly two columns appended to `extra_hgb`; nothing chosen at run time | L106-108 |
| `low_so_far` | `ols_floor_ladder.overnight_lows` (file sha256 `6e6d100f…` at `f5002b086`), first element, on the record's own history rows (minute_of_day ≤ cutoff·60); the run refuses unless the max of that row set equals high_so_far | L110-114 |
| `dewpoint_c` | the record's own `dewpoint_c` field at the cutoff; NaN stays NaN | L115 |
| Nothing else | no other column, transform, window or interaction; `DEV_KEEP_X` unchanged | L116-117 |
| Serve parity | not established by this rung; a pass needs a separate serve-parity check before any forward test | L118-119 |
| Selection contamination | the pair was chosen by X13 on the same Oct-Dec 2021-25 rows, so a pass is selection-contaminated history evidence | L147-161 |
| Nested LOYO | per outer year y: inner 4-fold blocked LOYO of G1 and G2 on the other four years; NEST(y) = G2 if the inner pooled mean Brier(G2) − Brier(G1) < 0, else G1; NEST(y) is fitted on the four years and scored on y | L163-174 |
| Pass rule as declared | upper 95% bound of dR(NEST vs G1) < 0 AND of dR(NEST vs COMP) < 0 | L176-180 |
| Reported | G2-selection count (0-5); each hour, held-out year and the 5 primary markets; plain non-nested G2 vs G1 | L181-184 |
| Fail | the two columns are closed for P3d_H at Oct-Dec 07-12; G1 alone carries gate 1 forward | L185-186 |

The declared design already has a season-fit comparator in its primary: G1 is the Oct-Dec refit under LOYO
(L99-101). The ruling bites only on the second pass condition, NEST vs COMP (L180), whose comparator is
Aug-Sep-fitted (L90).

## (b) Comparator options

### (i) A season-fit comparator

- **What exists:** G1 itself. Its P3d_H is fitted on Oct-Dec centres only, under blocked LOYO, so every scored
  year is out of fold (L99-101). Gate 1 has already scored it on the same key set. No new fit kind and no new
  outcome read is needed: G2 reads the same history rows.
- **What stays Aug-Sep inside G1:** the blend weights w_h (`c7b8ebc0…`, L83, L102-103) and the L6 partner
  (L84). Both are frozen and identical in G1, G2 and NEST. G2 vs G1 is therefore a paired comparison that
  isolates the two columns: whatever season error is in the weights or the L6 partner is in both arms.
- **A fully season-fit comparator** (Oct-Dec P3d_H, Oct-Dec blend weights and an Oct-Dec L6 partner, all out of
  fold) does not exist.
  - Building it means a new weight fit on Oct-Dec 2021-25 under LOYO and an out-of-fold L6 partner. The
    season-matched L6 state `800072c7…` is trained on all Oct-Dec 2021-25 (ledger row 49), so it is in-sample
    for every LOYO year.
  - It reads no outcome after 2026-09-29, and only history rows already read. So it is pre-registrable in
    principle, but it is a new candidate with its own selection, not a comparator. It would need its own row and
    its own design.
  - It is not needed to answer G2's question, which is whether the two columns help.

### (ii) MG-1 as primary

- The MG-1 analogue is already scored on the same keys (`gate1.json` `reported_mg1`: COMP vs MG-1 −0.0249).
- **Against it as primary:** MG-1 is not a G2 ancestor. NEST vs MG-1 mixes three things: the refit, the blend
  and the columns. It cannot say whether the two columns help, which is G2's question (L24).
- Whether MG-1 is itself fit for Oct-Dec is not established here (open point 4).

### Recommendation: (i), with G1 as the season-fit comparator

- **PRIMARY and only gating condition:** the upper 95% bound of dR(NEST vs G1) < 0.
  - G1 is season-fit (Oct-Dec LOYO), and it is G2's exact parent.
  - Everything frozen is shared between the two arms, so the result is attributable to the two columns.
- **Demoted to reported, never gating, labelled with the item 341 caveat:** dR(NEST vs COMP).
- **Reported beside it:** dR(NEST vs MG-1).
- **Why not keep L180 as a gate:** its comparator is not fit for Oct-Dec. Under the ruling it cannot gate. It
  also adds nothing to the column question, because G1 already beat COMP (gate 1).
- **How the change is recorded:** it narrows the declared pass rule. It needs a dated Clarification to
  `rule_rodc.md` (new raw sha) or a separate G2 rule file, before any G2 code (open point 1).

## (c) Endpoint, population, interval, pass and kill rules

- **Endpoint:** dR = mean_cell(Brier_arm − Brier_ref) / mean_cell(Brier_ref), with ref = G1. Cells are
  (local_date, market), pooled over h07-12 and the 11 markets. Brier is the multi-bucket Brier, as in L125-130.
- **Population:**
  - exactly gate 1's scored key set (`08704eff…`, 24,734 rows, 375 date clusters);
  - target dates 2021-2025 Oct-Dec only, with the refusal of L37 (no target year ≥ 2026, no date after
    2025-12-31);
  - history only. No outcome after 2026-09-29 is read.
- **Support:** fold support and open edges as in R-ODC C2/C2.4.
  - Each inner and outer fit uses the support of its own training years, applied identically to G1, G2 and NEST.
- **Interval:** date-clustered `dev_scorecard.ratio_interval` with `r0_ols_floor_challenger._date_weights`, 2,000
  draws, seed 20261027 (L128-129).
- **PASS:** the upper 95% bound of dR(NEST vs G1) < 0.
- **FAIL (kill):** anything else.
  - The two columns are closed for P3d_H at Oct-Dec 07-12 (L185).
  - G1 alone carries gate 1 forward.
  - Reopening needs fresh dates, because the history is spent for this pair (L159-161).
- **VOID:** any of the following:
  - the gate 1 reproduction control fails (section (d));
  - the `overnight_lows` assertion refuses on any row (L114);
  - any bound sha differs.
  A VOID run is not re-run without master.
- **A pass is not edge evidence.** It is selection-contaminated history evidence (L159-161). It earns only the
  serve-parity check (L118-119) and a forward pre-registration.
- **Power (L188-200):** MDE80 for G2 − G1 is not estimated in advance. A null is reported as a null at this power.

## (d) Code that would be needed (none written)

All new code goes in `src/weather/calibration/rodc_octdec.py` on a child of `claude/rodc-run-env-20261027`
(`9403d87bc`). Gate 1 code paths stay byte-identical.

- **Functions:**
  - `g2_columns(frame)`
    - Builds `low_so_far` via `overnight_lows`, first element, and asserts its max equals high_so_far,
      refusing otherwise.
    - Passes `dewpoint_c` through with NaN kept.
    - Refuses unless `ols_floor_ladder.py` hashes to `6e6d100f…`.
  - `G2_ARM`: `RK_ARMS["P3d_H"]` with `extra_hgb` = (k_max, k_gap, k_tcdc, low_so_far, dewpoint_c).
    - Same `_rung_entry` and `MEAN_HGB_PARAMS`, one fit per hour.
  - `nested_fold(frame, outer_year)`
    - Runs inner blocked LOYO of G1 and G2 on the four other years, each with its own fold support.
    - Pools the inner G2 − G1 mean and selects an arm.
    - Fits the selected arm on the four years and scores year y.
    - Records the selection and the inner mean.
  - `gate2(...)`
    - Writes `gate2.json` once (`_write_once`), plus a rows file.
    - The primary is dR(NEST vs G1); the reported values are NEST vs COMP, NEST vs MG-1, plain G2 vs G1, the
      selection count, and breakdowns by hour, year and the 5 primary markets.
    - It also writes counts, row stats and every pin.
- **Stop check (control):** the run's own non-nested G1 must reproduce gate 1's G1 rows (`gate1_rows.csv.gz`
  `5239e6a1…`) to 1e-12 before anything is scored. A mismatch is VOID.
- **Tests:**
  - `low_so_far`: correct value; the assertion refuses on a broken row set.
  - `dewpoint_c`: NaN passthrough.
  - G2's column list is exactly the declared five.
  - Inner folds never contain the outer year (leakage test).
  - Selection logic at the inner mean < 0, = 0 and > 0 (equality picks G1).
  - Per-fold support uses training years only.
  - `gate2.json` key types are JSON-safe (the C2.5 class of bug).
- **Synthetic end-to-end:** extend `tests/calibration/test_rodc_gate1_synthetic.py` (claude/rodc-gate1-test-20261027,
  `5451e8f3c`).
  - Same layout: 2 markets, 5 years, hours 07-12, monkeypatched readers, the outlier row.
  - A planted column effect must give NEST = G2 in every outer fold. A null column must give a non-PASS.
  - Runs via the wrapper `-Kind pytest`.
- **Pins recorded before the run:**

  | What | Pin |
  | --- | --- |
  | rule | the clarified rule's sha (open point 1) |
  | env | the env commit and module sha |
  | 2021-23 seal | `7dad81ce…` |
  | 2024-25 seal | `fe2dad2c…` |
  | land rule | `22069bee…` |
  | trainer records | `eb7ff73bc` |
  | NBM corpus | `1ae4bf52…` |
  | `ols_floor_ladder.py` | `6e6d100f…` |
  | COMP | P3d_H `e9276477…`, weights `c7b8ebc0…`, L6 part `07a67425…` |
  | gate 1 | `gate1.json` `6f26c5a2…`, rows `5239e6a1…` |

- **Running it:**
  - One run only, through the worktree's own `workstation_heavy.ps1 -Queue -MinAvailableMemoryGB 3`.
  - Expected size: about 10× gate 1's fits (5 outer × (8 inner + 2 outer) fit sets × 6 hours).
  - Arguments are built by a script whose output is checked as canonical base64 before submission.

## (e) Open points (listed, not guessed)

1. **How to record the narrowed pass rule.** Options: a dated Clarification in `rule_rodc.md` (its sha changes,
   and gate 1's pin stays as recorded), or a separate G2 rule file. Master's call.
2. **COMP's L6 partner season.** `rule_rodc.md` names HGB `0e89b32d…` with part `07a67425…` (L84). Ledger row 49
   names HGB `800072c7…` with the same part. Which HGB the frozen blend serves, and what season it was trained
   on, is not verified here. It does not change G2 vs G1, but it does change how NEST vs COMP may be read.
3. **The blend weights' season.** w_h `c7b8ebc0…` is shared by every arm. That keeps G2 vs G1 paired, but no G2
   arm is season-fit in the blend layer. Is that acceptable as "fit for the season" for a column test?
4. **MG-1's Oct-Dec fitness.** Not established here. It affects only how the reported NEST vs MG-1 is read.
5. **Inner-fold support.** Inner fits train on three years, so more rows fall outside support than in gate 1
   (168 of 24,734). Should the out-of-support count per fold be reported or capped?
6. **Determinism.** Whether `MEAN_HGB_PARAMS` fixes `random_state` was not checked for this design. The 1e-12
   G1 stop check assumes deterministic fits.
7. **Ledger row.** G2 needs its own DEV_WINDOW_LEDGER row, allocated by the coordinator.
8. **Serve parity.** A pass still needs the separate serve-parity check of both columns (L118-119). Its
   design and owner are open.
