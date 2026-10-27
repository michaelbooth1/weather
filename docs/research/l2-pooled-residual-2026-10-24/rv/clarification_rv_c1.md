# R-V clarification RV-C1: re-decide R-V against the served arms (history only, one look)

Lane L2, 2026-10-27. Amends R-V rule `b0cf2a03224d2581f96c77b801dd5244353ca1f2025ab0802940dcf65e88e818`
(`rule_rv.md`).

This clarification is hashed and pushed before anything it decides exists: no Oct-Dec MOS/NBE value, no
P3d_V_fwd number and no SM_HV number. Dev-window ledger row 53 (`claude/l2-dev-ledger-rows-20261026`) is written
PENDING before the fetch.

**Authority.** Master's rulings of 10-27 (relayed by the coordinator):
- R-V's gate 1 PASS is recorded, but it measured against the dev arm P3d_N_fix. It does not establish a gain
  over the served arms.
- Two decision reads replace "gate 1 then gate 2": (a) for MG-2 and (b) for MG-3.
- Rulings D1 (a second fetch), D2 (key sets) and D3 (one run, shared folds) were accepted as proposed.

**Evidence class and limits.**
- History only: 2021-25 training labels. No 2026 row is read, and nothing after 2025-12-31 is fetched or used.
- No dev row, outcome, price or market row is read.
- No paid data, no new dependency, and no change to MG-2, MG-3's bound files, L3's or L8's branches.

## 1. Disclosure (what was seen before this clarification)

**Seen in R-V gate 1** (ledger row 43; `C:/t/l2/rv/loyo`, audit `c8b88c42…`, rows `2a91bb80…`). These are on
Aug-Sep 2021-25 h13-16, 13,108 rows, 300 dates:
- Gate 1a coverage 1.0 (NAM 2025 0.983). Gate 1b v_gap per-year means −0.70, −0.39, +0.21, +0.11 and +0.17,
  against a pooled −0.12.
- Brier differences, 13-16:

  | Pair | Estimate | 95% interval |
  | --- | --- | --- |
  | P3d_V − P3d_N_fix | −0.00447 | [−0.00651, −0.00255] |
  | P3d_V − P3d_I | −0.00527 | [−0.00740, −0.00304] |
  | P3d_I − P3d_N_fix | +0.0008 | [−0.0005, +0.0020] |

- P3d_V − P3d_N_fix by hour:

  | Hour | Estimate | 95% interval |
  | --- | --- | --- |
  | h13 | −0.0077 | [−0.0108, −0.0045] |
  | h14 | −0.0077 | [−0.0109, −0.0044] |
  | h15 | −0.0017 | [−0.0056, +0.0023] |
  | h16 | −0.0009 | [−0.0042, +0.0024] |

  Pooled: 13-14 −0.0077, 15-16 −0.0013. Log loss 13-16 −0.0171.
- P3d_V − P3d_I by hour: h13 −0.0088, h14 −0.0063, h15 −0.0033, h16 −0.0027.
- P3d_V − P3d_N_fix by market, 13-16 Brier:

  | Market | Estimate |
  | --- | --- |
  | atlanta | +0.0027 |
  | austin | −0.0087 |
  | chicago | +0.0030 |
  | dallas | −0.0088 |
  | denver | −0.0187 |
  | houston | +0.0047 |
  | los-angeles | −0.0007 |
  | miami | −0.0118 |
  | nyc | −0.0094 |
  | san-francisco | +0.0016 |
  | seattle | −0.0033 |

  Denver, Miami and NYC have an upper bound below 0.

**Also known:**
- C10: SM_N − P3d_N_fwd +0.00356 [+0.00185, +0.00523].
- SMH-1: SM_H − P3d_N_fwd 13-15 −0.01273 [−0.01625, −0.00936]; h15 +0.0029 [−0.0019, +0.0080].
- The C10 and SM-H row files that this run reuses as controls.

**Not seen:**
- any Oct-Dec MOS/NBE value;
- any v_gap on an Oct-Dec row;
- any P3d_V_fwd or SM_HV distribution or score;
- any P3d_N_fwd score on Aug-Sep rows.

## 2. Data: the second fetch (ruling D1)

**What is fetched.** The R-V fetcher (`rv_fetch`) is used unchanged except for its runtime window:
- source IEM `mos.py`; models GFS (MAV), NAM (MET) and NBE; the 11 R0 stations;
- fields, runs, lags and the composite exactly as in rule_rv.md "The column";
- one connection, ≥ 8 s between requests, back-off on throttling;
- **runtimes 09-30 00:00Z .. 12-31 23:59Z for 2021-25 only.** A year ≥ 2026 refuses.

**Output.** `C:\t\l2\rv\mos_octdec\`, with its own `manifest.json` (sha256 per file). The manifest's sha256 is
recorded in the RV-C1 audit.

**Merge with the existing corpus.** The existing Aug-Sep corpus is `C:\t\l2\rv\mos`, manifest `1e6e6b3d…`.
- The two corpora are loaded by `rv_load` and merged on (station, model, runtime, ftime).
- A key present in both with different values makes the run VOID. Equal duplicates are kept once.

**Gates 1a and 1b on the Oct-Dec rows (STOP before any fit, not a kill).** They are applied to the Oct-Dec
2021-25 h13-16 rows of the scored Oct-Dec frame (§3), with the same thresholds:
- 1a: `mos_x` coverage ≥ 0.95;
- 1b: no per-year mean of `v_gap` more than 1.5 °F from the Oct-Dec pooled mean.

Either failure STOPS RV-C1 before any fit. That is not a kill; it is reported for a ruling. Coverage and v_gap
moments on the full Aug-Dec training frame are reported only.

## 3. The two decision reads (ruling D2)

Shared by both reads:
- blocked leave-one-year-out by target year 2021-25;
- CS-1 Brier (sum p² − 2 p_y + 1); log loss reported only;
- `rg_loyo_summary`: date-clustered bootstrap, 2,000 draws, seed 20261024; the pooled group plus each hour;
  per market reported only;
- a scored row without a finite high_so_far or current_temp is excluded from every arm, and the count is reported.

### (a) MG-2 relevance, 13-16: `P3d_V_fwd − P3d_N_fwd`

**Training frame.** C10's forward frame:
- `forward_training_frame(C:\t\l2\records)`, all 9 FORWARD_CENTRES, Aug-Dec 2021-25, 103,609 rows;
- hours 13-16;
- `attach_training_nbm` (L9 NBM `1ae4bf52…`);
- `v_gap` from the merged corpus.

**Fold rule.** Each fold for held-out year y drops all of year y's Aug-Dec rows.

**Arms.** Both are served through the served state `c6cc39f7…` (`C:\t\l2\forward\state\p3d_n_state.pkl`)
with `hours[h]` replaced by the fold fit, exactly as in C10-sel §3:
- **P3d_N_fwd**, the comparator: exactly C10's arm. `fwd_hour_entry` on the fold rows, served by
  `state_distribution`.
- **P3d_V_fwd**, the candidate: the same `fit_pooled` call (market_id False, doy True, raw_columns False, bias by
  season) with `extra_hgb = ("v_gap",)`.
  - The entry is built as `mg3_hour_entry` builds it, with the shell's `extra_hgb` set to ["v_gap"].
  - It is served by `mg3_state_distribution`: `state_features` (including the shell's conversion) plus the
    extra column.
  - That path's export parity is the one proven in the SM-H freeze (ledger row 52).

**Scored rows.**
- **PRIMARY: C10's Oct-Dec 13-16 keys.**
  - `sm_h_frame` at hours 13-16 with the same NBM attach: 16,496 rows.
  - Keys (hour, year, market, date) must equal C10's `loyo_rows.jsonl`
    `2c555bdadb853d2da9d4269294fb255c4f982acceab0a7886c34629f366b4745`.
- **Reported only: gate 1's Aug-Sep 13-16 keys.**
  - `dev_training_frame` at hours 13-16 with the same NBM attach: 13,108 rows.
  - Keys must equal R-V gate 1's `loyo_rows.jsonl`
    `2a91bb80e7e1d82b885ae9e07b97b35a936864f57c629c7cdd6a02e5de4d37dd`.

**Decision.** P3d_V_fwd is an **adopt-candidate for MG-2's 13-16 if and only if** the upper 95% bound of
`P3d_V_fwd − P3d_N_fwd | 13-16 | brier` on the PRIMARY keys is below 0. Nothing else enters the decision.
- The Aug-Sep read is reported only.
- P3d_V − P3d_N_fix is reported only, as already seen in §1.

### (b) MG-3 relevance, 13-15: `SM_HV − SM_H`

**Frame.** The SM-H run's frame, built exactly as `sm_h_loyo` built it:
- `sm_h_frame` at hours 13-15, Oct-Dec 2021-25, 12,372 rows;
- L9 NBM;
- L13's HRRR `C:\t\l13\hrrr` (manifest `409f6f91…`, selections `055add5a…`, stations `52e8bb5f…`, with
  `sm_h_day_filter`);
- `v_gap` from the merged corpus.

**Fold rule.** Blocked LOYO on the Oct-Dec rows of the other four years, per hour, as in `sm_h_rows`.

**Arms.**
- **SM_H**, the comparator: `RK_ARMS["P3d_H"]`, i.e. `extra_hgb = (k_max, k_gap, k_tcdc)`.
- **SM_HV**, the candidate: `extra_hgb = (k_max, k_gap, k_tcdc, v_gap)`, with v_gap appended last. Everything
  else is the same.
- Both are scored with `_dist_from_fit` on the per-market union of the Oct-Dec bucket spaces, as in SM-H.

**Scored rows.** f6f96cbc's keys: SM-H `loyo_rows.jsonl`
`f6f96cbceb3d3435431847470008300725161b5c39215e11a65ef696fb392fd5`.

**Decision.** SM_HV is an **adopt-candidate for MG-3's 13-15 if and only if** the upper 95% bound of
`SM_HV − SM_H | 13-15 | brier` is below 0. San Francisco is in the scored rows, as in SM-H. MG-3 serves SF from
MG-2's arm (MG3-DC-1 §2.1), so SF's figure is reported separately for information.

## 4. Controls (any failure makes the run VOID; no score is read)

1. **Inputs.**
   - The NBM corpus, `c6cc39f7`, the HRRR files, the existing MOS manifest `1e6e6b3d…`, the C10 rows
     `2c555bda…` and `c69b1351…`, the SM-H rows `f6f96cbc…` and the R-V gate-1 rows `2a91bb80…` all match their
     shas.
   - The forward frame has 103,609 rows, years 2021-25.
   - There is no merge conflict between the corpora.
2. **Key identity.** Each scored set's keys equal its reference file exactly, with no row missing or extra.
3. **Tier 2 for (a), C10's control row for row.** The all-years refit of P3d_N_fwd in the shell must equal
   `c6cc39f7`'s `state_distribution` on every scored row (Oct-Dec and Aug-Sep) to 1e-9.
4. **V off for (a), master's control.**
   - Take the P3d_V_fwd builder with no extra column (`extra_hgb = ()`), refit on all years.
   - Serve it through the shell by `mg3_state_distribution`, the candidate's serving path.
   - It must equal `c6cc39f7`'s `state_distribution` on every scored row (Oct-Dec and Aug-Sep) to 1e-9.
5. **Comparator reproduction for (a).** The P3d_N_fwd fold rows on the Oct-Dec keys must equal C10's
   `fwd_rows.jsonl` `c69b1351e0a48cdb18abc24453364941615ece3fc873c54f331854d620aefe47` (`P3d_N_fwd_brier`) to
   1e-12.
6. **V off for (b).** The SM_H fold rows (SM_HV's builder without v_gap) must reproduce `f6f96cbc`'s
   `SM_H_brier` on every row to 1e-12.

Gates 1a and 1b on the Oct-Dec rows (§2) run first and STOP rather than VOID.

## 5. What follows (stated now, not part of the look)

- **(a) and/or (b) passes.** Gate 2, the dev read (ledger row 44), is re-registered against each passing served
  arm by its own clarification before any dev row is read.
  - (a): P3d_V_fwd vs `c6cc39f7` at 13-16 on 2026 Aug-Sep, where `c6cc39f7` is out of sample.
  - (b): SM_HV vs SM-H at 13-15.
- **Neither passes.** R-V CLOSES: MOS/NBE day-max is closed as a 13-16 input on the served arms. Gate 2 never
  runs, and no other MOS/NBE field, cycle, lag, source subset, weighting or transform is run on this family
  (rule_rv.md "PRE-REGISTERED KILL").
- **Forward parity is unchanged** (rule_rv.md): production captures no MOS or NBE. An adopt-candidate is evidence
  for a capture proposal, not a binding.
- **Ledger.** Row 53 is filled with the result and this file's sha.

## 6. Mechanics

- **Code.** `weather.calibration.pooled_residual_model.rv_c1` (CLI `rv-c1`) and the fetch window
  `rv_c1_fetch_windows` (CLI `rv-fetch --octdec`), on branch `claude/rv-c1-20261027`. The constant
  `RV_C1_SHA256` holds this file's sha256.
- **Run (ruling D3).**
  - The fetch runs first, as a network fetch with one connection, as for the Aug-Sep corpus.
  - Then **one** run through `scripts/ops/workstation_heavy.ps1 -Queue` computes (a) and (b) together. They
    share the held-out-year blocks and the seed; their fitted folds are separate.
- **Outputs.** `C:\t\l2\rv\c1\`, write-once:
  - `rvc1_audit.json`;
  - `rows_a_octdec.jsonl`;
  - `rows_a_augsep.jsonl`;
  - `rows_b.jsonl`.
