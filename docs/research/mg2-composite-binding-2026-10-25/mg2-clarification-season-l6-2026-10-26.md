# MG-2 Clarification C9 (DRAFT): season-matched L6 own-model HGB in the 07-12 arm, 2026-10-26

- **Status:** master-reviewed 10-26; FINAL at the binding commit. It is **Clarification C9**, the next number
  after C8 in rule §8. Not bound until the binding commit, and dated before D0.
- **Authority:** master's ruling of 2026-10-26, relayed by the coordinator, under the pre-declared decision
  in rule `81649748…` below. The ruling allows no carve-out by hour or market.
- **History only:** no outcome, label, price or market row dated after 2026-09-29 was read. The scored
  history is 2021-25.
- **What changes:** only the L6 own-model HGB that produces the nowcast N for the pre-13 stack at 07-12.
  Nothing else in MG-2 changes:
  - the stack form and its coefficients;
  - MG-1;
  - the post-13 half (P3d_N);
  - the floor;
  - the switch hour;
  - the gate.

## 1. Why: CS-1 (1a)

Lane L3's cool-season transfer audit CS-1 scored the frozen Aug-Sep L6 stack on Oct-Dec 2021-25 at 07-12. It
did not transfer.

- **Rule:** `C:/t/l3/coolseason/rule_cs.md`, sha256 `ac9c74332876c53a7e721b1acf6b3abaf692e45592d68d022c4a432210b71f30`.
- **Ledger:** `DEV_WINDOW_LEDGER.md` row 45 (first pushed as row 40; renumbered 2026-10-27).
- **Result:** `C:/t/l3/coolseason/part1a.json`, sha256 `98d80635666fafca107072b8fae2026b8924a6a8500c2968c599807e246166b7`.
- **Coverage:** `coverage.json`, sha256 `8da25c96b61645431037001e4f319c2f4ecdc68d3a02618d51ca68b6a26097a9`.
- **Code:** `weather.calibration.cool_season_audit`, branch `claude/cool-season-audit-20261026` @ `b62c7dc38`.

| Frozen L6 stack (HGB `0e89b32d…`) vs MG-1 analogue, 07-12 | dB | 95% (date-clustered) |
| --- | ---: | --- |
| Aug-Sep 2021-25 (in-sample for the HGB) | −0.0159 | [−0.0188, −0.0130] |
| Oct | −0.0001 | [−0.0049, +0.0044] |
| Nov | +0.0131 | [+0.0071, +0.0192] |
| Dec (1st-16th) | +0.0180 | [+0.0094, +0.0268] |
| **Oct-Dec** | **+0.0090** | **[+0.0057, +0.0126]** |

Nowcast RMSE against the day maximum went from 2.59 °F (Aug-Sep) to 4.53 °F (Oct-Dec).

## 2. The pre-registered test: SM-L6

- **Rule:** `C:/t/l3/sml6/rule_sml6.md`, sha256 `81649748d82319d248f9ce9b2c57e4450ecf9a796b5ff2407e2138d4c7798fc3`.
  It was written before any fit, and ledger row 46 (first pushed as row 41) was pushed PENDING before any fit (ledger branch
  `claude/l3-dev-ledger-rows-20261025` @ `04a73c7a9`).
- **Code:** `weather.calibration.season_matched_l6`, `claude/cool-season-audit-20261026` @ `c7b489ba5`.
- **Arm:** the same `upstream_obs_screen.OWN` features (= `mg_serve_core.L6_OWN_COLUMNS`), the same station
  encoding and the same `HGB_PARAMS` (`random_state` 0) as the frozen state `0e89b32d…`. Only the training
  months change, from Aug-Sep to Oct-Dec 2021-25 (29,905 rows).
- **Fixed parts:** the MG-2 l6_stack coefficients are frozen as bound (§4 below); only the HGB is swapped.
- **Evaluation:** leave-one-year-out by year on Oct-Dec 07-12 against the MG-1 analogue, normal(NBM mean,
  max(sd, 1)) floored, with integer buckets. The interval is a date-clustered bootstrap (2,000 draws, seed
  20261026).

**Pre-declared decision rule (master's, verbatim from rule `81649748…`):**

> - If the Oct–Dec pooled upper bound of dB is below 0, MG-2's 07-12 arm becomes the season-matched L6 stack for all B dates.
> - Otherwise MG-2's 07-12 arm is MG-1 for every B date from 11-01, and the frozen Aug–Sep L6 stays for 10-28..10-31.
> - Either way, a dated MG-2 clarification is written before the binding commit.

**Result:** `C:/t/l3/sml6/loyo.json`, sha256 `07ef7810d81e434c93e08e552d3ca2df0ec195790a52b6431e578ab3ce515919`.
The pooled upper bound is −0.0025 < 0, so the rule selects **the season-matched L6 stack for all B dates**.

| 07-12 vs MG-1 analogue | Season-matched (LOYO) dB | 95% | Frozen Aug-Sep L6, same rows |
| --- | ---: | --- | ---: |
| **Oct-Dec pooled (primary)**, 24,381 rows, 375 dates | **−0.0052** | **[−0.0080, −0.0025]** | +0.0090 [+0.0054, +0.0126] |
| Oct | −0.0016 | [−0.0060, +0.0027] | −0.0001 |
| Nov | −0.0064 | [−0.0108, −0.0020] | +0.0131 |
| Dec (1st-16th) | −0.0097 | [−0.0159, −0.0033] | +0.0180 |
| Nov-Dec | −0.0075 | [−0.0113, −0.0038] | +0.0148 |
| h07 | +0.0042 | [+0.0012, +0.0071] | |
| h08 | +0.0033 | [+0.0003, +0.0064] | |
| h09 | −0.0019 | [−0.0050, +0.0011] | |
| h10 | −0.0089 | [−0.0123, −0.0053] | |
| h11 | −0.0145 | [−0.0180, −0.0110] | |
| h12 | −0.0139 | [−0.0183, −0.0094] | |
| 2021 / 2022 / 2023 / 2024 / 2025 | −0.0028 / −0.0037 / −0.0072 / −0.0105 / −0.0020 | 2023 and 2024 exclude 0 | |

- **By market:** the history covers 11 markets, Denver included. Denver is in the history but is not a B
  market (rule §8 C8 leaves it out of the 10-market gate); its figure is +0.0035 [−0.0043, +0.0114]. The
  primary above is the 11-market pooled figure, unchanged. Of the 10 B markets, Chicago is +0.0253
  [+0.0155, +0.0353] and NYC +0.0114 [+0.0004, +0.0219]; the other eight have a negative point estimate or an
  interval spanning 0.
- **Nowcast RMSE (Oct-Dec):** 3.44 °F season-matched, against 4.50 °F frozen and 2.91 °F for NBM.
- **Control:** the frozen state on the same rows reproduces CS-1's point estimate (+0.0090) exactly. Its
  interval differs only in the bootstrap's date set.

## 3. The bound L6 state

| Field | Value |
| --- | --- |
| File | `l6_own_state_octdec.pkl` (sidecar `l6_own_state_octdec.json`), from `season_matched_l6 final` |
| sha256 | **`800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db`** (file bytes; sidecar `497bdfec3beecac52c184e9a33530aa76a19f93a8d7d2580e14e51ca45caf80a`). Fit at commit `c7b489ba5`, module `cf398143…`, LOYO result `07ef7810…`, 29,905 rows 2021-10-01..2025-12-31 |
| Schema | `l6_own_state/1` (`mg_serve_core.L6_STATE_SCHEMA`); columns `mg_serve_core.L6_OWN_COLUMNS` |
| Load | `weather.model.mg_serve_core.load_l6_own_state(path, sha256)`. It refuses unless the file bytes hash to the bound sha, then checks schema and columns before use |
| Serve | `mg_serve_core.l6_own_nowcast(state, features)`: N = r + model prediction on the OWN columns. No per-run refit |
| Fit | `make_model(OWN)` on every `build_history` row of months 10-12, history ≤ 2025-12-31. It refuses unless the LOYO decision selected this arm |

- **Replaces:** the Aug-Sep 2021-25 IEM-history HGB named in rule §1 ("L6 own-obs nowcast"). That HGB is
  refitted per run by `mg2_composite.captured_nowcast` and frozen as `0e89b32d…` by L3. It applies on every
  B date, 10-28..10-31 included (master: no carve-out).
- **Serve inputs:** unchanged. The captured METAR rows are read by `mg2_composite.captured_nowcast`.
- **Dev pin:** the captured dev nowcast pin `3806687c…` describes the Aug-Sep HGB.
  - Under this clarification, the reader's dev reproduction check binds the season-matched dev nowcast
    instead. That is the same captured dev serve features (`C:/t/l3/l6cap/serve_features.parquet`,
    `0d5c30b3…`) through the new state.
  - The file is `nowcasts_season_dev.parquet`, sha256
    `714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a` (27,868 rows, the rows and columns of
    `3806687c…`), emitted by lane L3 for L2's MG-3 weight refit (`season_matched_l6 dev-emit` @ `40ed3cf1f`).
    Control: the frozen Aug-Sep state reproduces `3806687c…` on the same features with gap 0.
- **Serving code:** wiring the frozen state into `mg2_composite`'s pre-13 path is a serving-code change.
  Lane L8 makes it on `claude/mg2-l6-wiring-20261026 @ bf0cc429ae18765f63fc0e1cf7c69972b93de938` (code
  `88d5437ee`, plus one docs-only commit adding B-1 §8, the hermetic-climatology limit): the state loads
  through `load_l6_own_state` with sha verification, with a parity test, plus the BOUND_FIELDS fix. L3 does not
  make this change.
  - At that tip the b_scorer sha256 is `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439`
    (unchanged since `53bf81f9c`; it supersedes `c27e710d…`).
  - The B control receipt bcontrol4 `17b293a73df23696044be594480e3dde7a2e09a882c80fef695d39cea8f7bc6c` is PASS
    (it supersedes `c67ba81a…`).
  - The captured dev nowcast pin `714fa14e…` is now a code constant at that tip.
  - In L8's rehearsal (mg2_checks `0e1b98478d66c7cffa6e528aecba8001763601e08b0ac4c60a1a71eb1bb58434`), the nowcast
    replay at `800072c7…` reproduced `714fa14e…` exactly.

## 4. Unchanged: the stack coefficients

- **What stays:** the l6_stack coefficients a_h and b_h (h = 07..12) stay exactly as bound:
  - part sha256 `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9`;
  - file `mg2_coefficients.json`, sha256 `4bc51e031ce10862d44ffdc57a6a6ca92bd46d98412bfc0e087b681a01b0c398`.
- **No refit:** they are not refitted.
- **Known limitation:** a_h and b_h were fitted on Aug-Sep 2026 dev snapshots, on the nowcast of the Aug-Sep
  HGB. SM-L6 applies them unchanged to a different HGB in a different season. The LOYO result above is
  conditional on that mismatch. A stack refit was not tested and is not part of this clarification.

## 5. B-1: pre-declared secondary descriptive reads (the primary is unchanged)

Master ruled that the flags in §2 become secondary descriptive reads in B-1. They are reported beside the
primary and carry no α. They cannot pass, fail or change the arm.

- **R1:** hours 07 and 08 separately (SM-L6 history: both above 0).
- **R2:** Chicago and NYC separately (SM-L6 history: both above 0).
- **R3:** hours 13-16 vs 07-12 (pre-declared in rule `81649748…`).
- **R4:** target dates in October vs November-December (pre-declared in rule `81649748…`).

## 6. Scope limits stated

- **Unscored days:** Dec 17-31 is unscored in history. The NBM corpus and L2's records end on 12-16 each
  year, so no history figure covers B dates after 12-16.
- **Shared years:** the Oct-Dec LOYO folds hold out one year at a time, but the coefficients come from 2026
  dev. All history is 2021-25.
- **The 13-16 half:** CS-1 (1a) scored P3d_N's dev fit `dff5d797…` (Aug-Sep training), which transfers
  (Oct-Dec −0.306 [−0.316, −0.296]). The bound forward state `c6cc39f7…` trains on Aug-Dec, so it was not
  separately audited. Because `c6cc39f7…` trains through December, a LOYO on it would not be out-of-sample
  on Oct-Dec anyway. This clarification does not touch the post-13 half.

## 7. Bookkeeping

- **B-1's FILL list:** it gains the season-matched L6 state sha256 (§3) and the season-matched captured
  dev nowcast sha256 (§3). L8's B-1 clarification (LF sha256
  `cfff97c45e37cd0239269a9d6cd637f51269deac1c1e8152325050f3c0095ac1`, at `bf0cc429a`; it supersedes `1c96f5e4…`)
  carries these items.
- **Release binding:** `release-binding.json` records the L6 state sha256 next to the l6_stack part sha256.
  `emit` and `score` refuse on a mismatch.
- **Ledger:** row 46 (SM-L6; first pushed as row 41, renumbered 2026-10-27 for a collision with L2 rows 40-44)
  carries the result and the decision. Rules `ac9c7433…` and `81649748…` keep their bytes; the ledger note maps
  their "row 40/41" to 45/46.
