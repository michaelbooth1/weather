# Ledger row 92: Oct-Dec LOYO batch, X36's per-market centre shift on the SM-L6 incumbent at 07-12. History only.

Written 2026-10-30 by lane L3, before any row of this rung exists. The batch was relayed by the coordinator: X13, X18,
X20, X36 under the §10w and no-rebuild gates. Development evidence only; no edge claim, no promotion.

- No outcome, price or label dated after 2025-12-31 is read, so nothing from the 2026 dev window, 88a, the panel or
  09-30..10-15 is read.
- No cache is rebuilt or re-downloaded.
- No reader on the EF §10w +1 h path is used (see Gates).

## 1. Batch kill check (§5 rule 1; register X1-X70, ledger rows to 91, STATE_OF_PLAY, same-day lanes)

| Item | Register reopen text | Finding | Disposition |
| --- | --- | --- | --- |
| X18 R-G, X20 R-J (trajectory columns) | Aug-Sep only (R10): an Oct-Dec rung | the successor proposal `ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458` §1 marks them EXCLUDED, because trajectory/tracking was killed 10-30 (X66-X70; RATE-0712, ledger row 81) and reopens only via the frozen RISE-T3R3 replication (row 80); coordinator ruling 2026-10-30: no override | **ruled out by family, not run** |
| X13 L9 ladder (overnight low, dewpoint on OLS + floor) | overnight low and dewpoint help in Oct-Dec: an Oct-Dec rung under R10 | that Oct-Dec rung has been run: R-ODC (overnight low + dewpoint, Oct-Dec 07-12) rows 65, 69, 70 (history PASS, small, against an Aug-Sep-centred comparator); then C1 (row 85) put `low_so_far` + `t_minus_low` on the live incumbent SM-L6 and it DROPPED (−0.0000426 [−0.000312, +0.000215], ρ 0.887 with RATE-0712); dewpoint is already in L6 OWN (`td`) and MET-DEWDEP was killed against the market 10-30 (row 78); OLS + floor is not a served arm in Oct-Dec | **covered by family (rows 65, 69, 70, 85), not run** |
| X36 R-M (per-market additive centre shift at 07-12) | a new training corpus (for example Oct-Dec under R10) shows a fitted per-market shift beyond ±1 °F | not killed by name or family since 10-26. X8-X10 (L5 per-market debias on MG-1) are Aug-Sep dev. The Oct-Dec corpus has never been fitted for a per-market shift | **eligible: this rule** |

**Prior (stated now): low.** The SM-L6 OWN HGB carries the station code as a feature, so a per-market Oct-Dec bias
can already be absorbed in the nowcast. Only the frozen MG-2 l6_stack blend with NBM could leave a market-level
residual. R-M's Aug-Sep fit gave shifts within ±0.4 °F.

## 2. Gates (§10w and no rebuild)

- **Readers.** The rows, labels and incumbent are those of C1's incumbent (ledger row 85) through the same functions:
  - `cool_season_audit.l6_rows` and `season_matched_l6.training_rows` / `fit_state` / `stack_brier`;
  - IEM METAR `upstream_obs/obs.parquet` sha256 `37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2`
    (UTC valid times, local dates by tz_convert; label = the obs day max `dmax`);
  - selection `a23f4cba11c0ec1666e7069cc89c93f699e5573546c048be4e398070cc1fb199`;
  - NBM text PIT corpus `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd` (UTC issue /
    LastModified);
  - MG-2 l6_stack frozen coefficients `4bc51e031ce10862d44ffdc57a6a6ca92bd46d98412bfc0e087b681a01b0c398`.
- **§10w.** No `forecast_training_corpus`, `open_meteo_archives`, `reanalysis_history`, `historical_fallbacks` or
  `forecast_history` feature is read. This is met by construction, as for C1. L11's DST audit (`results-dst-audit-octdec.md`
  on `claude/permarket-bias-20261026` @ `f84ba000c95ebc6de018a5f3b142891aaa42013c`) found 0 misaligned Oct-Dec
  rows on the NBM-cycle and WU-cutoff paths.
- **No rebuild.** The module only reads those existing files and writes one receipt under its `--out`. It refuses
  each pinned input whose sha256 differs. a399941e is not needed.

## 3. Population and arm

- **Rows:** `l6_rows` restricted to months 10-12, 2021-25, local hours 07-12, 11 US markets (CYYZ excluded). The
  scored rows are those where the unshifted stack is finite, the set C1 scored (24,381 rows, 375 dates).
- **Arm A0 (incumbent, s = 0):** the SM-L6 LOYO stack. For held-out year Y:
  - the OWN HGB is fitted on Oct-Dec of the other four years (`fit_state`);
  - the nowcast is `mg_serve_core.l6_own_nowcast`;
  - mu = v + a_h + b_h (n − v) with the frozen coefficients;
  - σ = max(s, 1);
  - integer-bucket Brier `rz_hrrr_spread.bucket_brier(mu, σ, R, dmax)` (floor at R).
- **Arm A (shift):** identical, with mu replaced by mu + s_m(Y) for market m. Width, floor and coefficients are
  unchanged, and at s = 0 it is A0 byte-for-byte.

## 4. Fitting (strictly nested; one family)

- **Inner predictions.** For each pair {X, Y} of distinct years, one HGB is fitted on Oct-Dec of the three years
  outside {X, Y}, so there are 10 inner fits and 5 outer fits.
- **Fit for held-out Y.** For each market m:
  - take the inner predictions of every X ≠ Y from the fit outside {X, Y}, pooled over X and h07-h12;
  - s_m(Y) is the minimiser of their mean Brier over the grid {−4.0, −3.9, …, +4.0}, which contains 0.0;
  - on a tie, the s closest to 0 wins.
- **Apply.** s_m(Y) is applied to the outer (Arm A0) prediction of Y.
- **Exclusions.** No other grid, hour grouping, market grouping, shrinkage, width parameter or objective runs.
- **Caveat (stated now, from the module's synthetic test before any real row).** s is the Brier-optimal centre
  shift of the floored, renormalised pmf, not a pure mean bias. With the floor active, an unbiased synthetic
  centre (σ = 2, error SD 1.5) fits s = −0.7. A fitted |s| > 1 °F can therefore partly reflect the floor and width
  interaction. R1 is read as written; this caveat is reported beside it.

## 5. Decision

- **R1 (X36's reopen condition, read first).** It is met if at least one market has |s_m(Y)| > 1.0 °F with the same
  sign in at least 3 of the 5 folds.
- **R2 (gate 1, as R-M).**
  - Statistic: Δ = mean per row of Brier(A) − Brier(A0), pooled over markets and h07-h12, with a date-clustered
    95% CI (`upstream_obs_screen.cluster_ci`, as C1).
  - PASS if the upper bound < 0 and no year and no month has a CI lower bound > 0.
- **Verdict.**
  - **PASS only if R1 and R2 both hold.** A PASS is not promotable (R10). It earns only a forward pre-registration
    for an Oct-Dec per-market shift on SM-L6, sent to master.
  - **KILL otherwise.** X36 stays closed, and the closure now also covers the Oct-Dec season on the SM-L6
    incumbent. No other grid, hour block, shrinkage, objective, grouping or window runs under any name.
- **Reported:**
  - s_m(Y) for all 55 cells;
  - Δ per market, year, month and hour;
  - dates-paired σ_d, lag-1 and block-3 SE (`successor_odc_low.daily_stats`).

## 6. Controls (in the same run; any failure makes the run VOID, the fix diff goes to the coordinator first, and one re-run follows under this rule)

- **C-a, reproduction.** Arm A0 against the MG-1 analogue (`season_matched_l6.tables(...)["oct_dec"]["pooled"]`)
  must equal C1's receipt (`C:\t\l3succ\c1\c1.json`
  `c881a5bba59c36f6dd409b055910ee2ba83a36833735ca679bd8475c053dbe14`):
  - estimate −0.005245663923351247 and n_rows 24,381, to |diff| ≤ 1e-12;
  - which ties back to the SM-L6 LOYO result `07ef7810d81e434c93e08e552d3ca2df0ec195790a52b6431e578ab3ce515919`.
- **C-b, identity.** Arm A with every s = 0 equals Arm A0 on every row (max |diff| = 0).
- **C-c, synthetic planted bias (synthetic-control rule, master 2026-10-30).**
  - Plant: on a copy, every Austin mu (inner and outer) is moved by −2.0 °F; nothing else changes.
  - The fitted shift must move by +1.5..+2.5 °F against the unplanted Austin fit, s_austin,planted(Y) −
    s_austin(Y), in all 5 folds. The difference is used, so a large natural Austin shift cannot void the run.
  - The Austin-only Δ (A − A0 on the planted copy) must have its CI upper bound < 0.
  - The planted negation (+2.0 °F) must move the fit by −2.5..−1.5 °F in all 5 folds.
- **C-d, training score.** No fitted s_m(Y) may worsen its own inner mean Brier against s = 0. Since 0 is in the
  grid, this can only fail through a bug; it is reported anyway.

## 7. Run

One run, through `workstation_heavy -Queue -Kind weather_heavy`, after coordinator admission:
- clean tree, no `--allow-dirty`;
- OMP/MKL/OPENBLAS = 10, `-MinAvailableMemoryGB 3`;
- output under `C:/t/l3rmod/`, write-once.

The result note goes to ledger row 92, and the result goes to the coordinator. It is not market-facing and does not
touch B's inputs.
