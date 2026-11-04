# Clarification 2 to the R-ODC / X13 released-cell P0 rule (ledger row 103, lane L16, 2026-10-31)

Applies to `rule_rodc_released_p0.md` (sha256 `9bff5c02762a27ef604219b305e6a8043497cbf0316ec2403b879f4ed09a2f11`)
and Clarification 1 (sha256 `064c4f267fab1e70d5b046c00da2b9796adae77031918ce08caee2030cd48be6`). Neither is edited.
Where this clarification differs from either, this clarification wins.

These are master's rulings of 2026-10-31, relayed by the coordinator, including master's amendment to point 2(d).
They were written before parity2 ran and before any look. No released label or price has been read for this test.
Parity1 is the only history result read so far: the history lows of D and D−1 and the trainer cache, with no
labels and no prices.

## 1. C-c, the zero-tilt control (replaces the earlier ruling 2)

- **The deciding statistic stays the frozen pin `mr_sweep` (8bb0f9563), unedited.** That keeps row 80 and S31
  comparable. The candidate tilt is renormalised to sum(m) with no EPS clip. The placebo is clipped to [EPS, 1] and
  then renormalised to sum(m). Both paths stay exactly as frozen.
- **C-c passes only if both identities hold:** candidate(g = 0) = m, and placebo(g = 0) = clip_renorm(m). Here
  clip_renorm(m) = clip(m, EPS, 1) renormalised to sum(m) per snapshot.
  - "Exactly" is implemented to floating-point resolution: max |difference| ≤ 1e-15. Bitwise equality cannot be
    reached on the frozen path, because the tilt computes sum(m) · (m / sum(m)) / Σ(m / sum(m)).
  - The receipt records how many bands are bitwise unequal on each side.
- **The receipt discloses the number of snapshots that have any band with m < EPS.**
- **One sensitivity, which does not decide anything.**
  - Δ and the D3 label are recomputed on the subset of each arm's population snapshots where every band has
    m ≥ EPS.
  - The recomputation uses the same c and the same placebos.
  - The BH step runs over the two arms' sensitivity p-values.
- **KILL guard.**
  - If the full-set label is "KILL at edge size" and the sensitivity label is not, the arm's label becomes
    **"UNRESOLVED (EPS-path sensitive)"**, not KILL.
  - Otherwise the full-set label stands.
  - The guard is applied before the parity suffix of point 2.
- **Module pin:** `CC_PATH_RULING = "master 10-31 C-c: frozen statistic; exact identities as above; m<EPS count;
  all-m>=EPS sensitivity guards KILL"`.

## 2. Train/serve parity of the lows: one bounded fix, no iteration

Master rules that the serve-side "implausible" filter is a defect. That filter drops temperatures below 30 °F and
above 125 °F (`feature_store.plausible_native_temperature`, as applied in `odc_metar_features.kept_rows`). Lows
below 30 °F are routine in Chicago and Denver from October.

**(a) parity2 confirms the mechanism.** It is one `-Queue` job, `parity2 --out C:\t\l16\rodc\parity2`.

- **Inputs and guards:** the same as parity1. It reads history ≤ 2025-12-31 only, the IEM ASOS partitions are
  checked against their manifests, and the receipts are exclusive-create.
- **It computes two tables in the same run:**
  - *filter off:* the serve-side filter is disabled, keeping every finite temperature. This table confirms the
    mechanism and decides nothing.
  - *trainer rule:* the look's construction under point (b). **This table decides.**
- **Kept-window counts recorded per market:** rows below 30 °F, and rows below −40 °F.

**(b) The trainer's plausibility rule: there is none, so the native-unit physical bound is used.**

- **The trainer path of the cache lows applies no plausibility filter:**
  - `src/weather/model/model_climatology.py`, `ClimatologyMixin.historical_target_cache` (blob
    `a4eeabf191b7cd2326005ad10c2ea9ef81d32d0a`, sha256
    `2d69cb04616fddd29b77c4387fa1cf6bc1d708c96883ebffb711fe15b0c4f43d`). It reads WU history rows with
    `feature_store.row_temp_native` and keeps every row that has a local time.
  - `src/weather/model/feature_store.py`, `row_temp_native` (blob `c11b3ca94747b3c1603cbbff9c4eebd4ad83cb4a`).
    It returns the first numeric temperature field, with no bound.
  - `src/weather/calibration/ols_floor_ladder.py`, `overnight_lows` (blob
    `eedd3d32f5044cf797ba0b053afec83d580974be`, sha256
    `6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e`). It drops only `None` temperatures.
  - These blobs are identical at the L9 cache build commit 8167b89a8.
- **The look's serve-side construction therefore uses the native-unit physical bound.** A temperature is kept if
  it is finite and ≥ −40 (°F, which equals −40 °C), and dropped otherwise. There is no upper bound, because the
  trainer has none.
- **Scope:** this rule is applied in every market the look scores, for both arms. It covers the odc low_so_far, the
  odc current temperature and the X13 lows.
- **How it is applied:** in the row 103 driver only, as a scoped in-process override of the predicate that
  `odc_metar_features.kept_rows` calls.
  - `odc_metar_features.py` is row 72's frozen code and is not edited. A test proves that it is blob-unchanged
    (`1cc4d565468bf4959137a8f6f6cec5b10adfce24`, the blob at 0e11b018f).
  - The dewpoint path is unchanged.
- **X13 lows are WU whole degrees** (master review of ad94217fd, fix 2). Each X13 input temperature is rounded
  with `mg_serve_core.wu_whole_f(v, "half_up")`, as arm 1 already is, because the trainer rows are WU whole
  degrees. The fit is unaffected, because its history comes from the cache.

**(c) The fit is unchanged.** The look still reads `coef.json` sha256
`24bdb0a66c07c4af6d7771b806d8d4f281a1fb9174445f4d289b974248c7e7d8`. Its X13 Denver cells stay in the file, but
the look does not read them (point d).

**(d) Markets after the fix**, decided now, before parity2 runs.

- **Denver is excluded from X13 now, unconditionally** (master's amendment).
  - The main reason is the station mismatch: the WU settlement station is KBKF and the METAR station is KDEN.
    R-ODC already excludes Denver for the same reason (DL 10-23).
  - **Both arms therefore score the US10**, the US11 without Denver.
  - parity2 still reports Denver's rows descriptively. They decide nothing.
- **Chicago and every other US10 market** follow (a) and (b). A US10 market that still fails on the trainer-rule
  table (MAE > 0.5 °F or |bias| > 0.3 °F) adds the suffix " [parity-limited; kill scope: this construction only]"
  to each arm that reads that comparison. That market is not excluded.
- **The look refuses without the parity2 receipt**, read by its sha256. The parity1 receipt cannot be used for the
  look.

## 3. Power at the US10 N, recorded before any Δ

- **The rule's projected power is recomputed at the US10 N.** It is Φ(0.2236 / SE − 1.96), with
  SE = 0.034994 · √(N_row80 / N_arm).
  - 0.034994 is row 80's wider per-date SE.
  - N_row80 is the population snapshot count in row 80's archived rows (sha256 `54fd5966…`).
  - N_arm is the arm's covered snapshots on the release layout: hours 07-12, US10, Austin 10-03 dropped. It is
    counted from features and coefficients only, so no price or label is involved.
- **The projection is printed and recorded before the r80 table is built.** The binding gate is still the in-run
  power of Clarification 1 point 5.
