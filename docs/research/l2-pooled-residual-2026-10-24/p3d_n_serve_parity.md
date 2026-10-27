# P3d_N serve-parity check (lane L2, 2026-10-25): MG-2 pick rule eligibility condition 1

- Pick rule: `C:\t\mg2\afternoon_pick_rule.md`, sha256 deb3eae31fb19cc96c90d1a9267f292e8a819fae1784c7b8b950071be99ceffb (Clarification 2).
- L2 rule: `C:\t\l2\rule.md`, amendment 5, sha256 b3f017bbf3d634b142e0d2eb2b1ae7ba38fd65b74b069c3cfee2d8cc5d19de68.
- Code: `weather.calibration.pooled_residual_model dev-emit-n`.
  - Branch claude/pooled-residual-model-20261024 @ 064aabe6a.
  - Run from the local, never-pushed worktree C:\wt\l2run. It adds L3 @ ecd8c9ba6, L9 @ ac4f354da, and `observed_running_max.py` blob 40c84103 from fe4782e66 (sha256 c057e454…).
- Output: `C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl`, sha256 721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec.
- Audit: `C:\t\l2\p3d_n_dev\dev_emit_audit.json`, sha256 ee806337a8e8527c6d574c03522ecda596a6f9f26d254e3018a8c12d18e6fabb.

Everything here was built from code, captured inputs and forecasts. No label, outcome or price was read, and no row was scored. I did not open `control_refit_armA.json` or any A_N vector.

## Verdict

**Condition 1 PASSES.** Every model input at dev is computed from captured fields, with the serve-time cutoff semantics, and nothing is imputed at dev. The lead-1 Previous Runs forecast no longer enters P3d_N anywhere, in training or at dev.

## Input-by-input

| Input | Dev / serve source | Captured? | Cutoff semantics | Check |
| --- | --- | --- | --- | --- |
| nbm_mean (anchor, mu0 = nbm_mean + bias) | Layout `v2_mean`, through `r0_ols_floor_devfit.usable_v2_mean` (v2_mean and v2_stddev finite, `v2_available_at` ≤ `captured_at_utc`): A_N's rule | Yes | The `v2_cycle_key` is the target date's 07Z NBP cycle at every cutoff 07-20, available at capture | **13-16 (pick block):** the 2026 corpus 85746b7a… through L9's `nbm_at_cutoff` equals the emitted value exactly on 18,598 of 18,598 snapshots. **12 and 17-20:** also 100% exact. **07-11:** exact on 23,652 of 23,952; on the other 300, the corpus has no value by h:00 (its S3 LastModified is later than the capture's `v2_available_at`), and none of them has a different value. No snapshot lacked a usable v2_mean, so nothing was imputed at dev. |
| high_so_far (feature, g, and the floor) | `observed_running_max.running_max_since_midnight(station={}, metar=sources.metar.data, ..., cutoff_hour=h, now=capture time, metar_only=True)` on the last replay snapshot captured in [h:00, h+1:00) | Yes | Captured METAR rows observed on the target local date at or before h:00 and at or before capture: the trainer's definition | Floor equal to P3d's main high_so_far on every emitted row (0 differ), and so equal to L8's value (L3 clarification 3). A missing value means the row is not emitted (15 rows: Denver 8, Seattle 7, the same gaps as P3d). |
| current_temp | Latest captured METAR row observed at or before h:00 on the same snapshot (L3 `observations_at_cutoff`) | Yes | Same | Missing means the row is not emitted |
| cutoff hour h, target date (doy, nearest Aug-Sep centre for the normal) | Snapshot `cutoff_hour` and `target_date`; emitted only if local_hour ≥ h | Yes (metadata) | Same | n/a |
| lat, lon, elev | `config/locations.json` | Static | n/a | n/a |
| bias, normal, OLS, mean and scale HGB, z set, p_clim, bucket space | Fitted once on 45,873 Aug-Sep 2021-25 trainer records. nbm_mean comes from L9 corpus 1ae4bf52… (07Z, LastModified ≤ cutoff): 45,870 rows, plus 3 imputed with forecast_high under L9's IMPUTE rule (training only). No 2026 row. | Model state | n/a | n/a |

**Rows:**
- 79,403 snapshots, the same set as P3d and arm A (symmetric difference 0).
- Cutoffs 07-20, 11 markets.
- Every distribution sums to 1.
- Same format as `dev_P3d.jsonl`. Declare it with `--trained-through 2025-12-31`.

## Residual mismatches (descriptive; A_N shares every one)

1. **high_so_far and current_temp sources.**
   - Training reads them from WU history rows, in whole °F.
   - Serving reads captured METAR, in tenths.
   - These are the same station reports.
2. **Within-hour snapshot choice.**
   - Every snapshot in an hour takes its METAR features from the last capture in [h:00, h+1:00).
   - The rows are still restricted to observations at or before h:00, but a late-arriving report could reach an early-hour snapshot.
   - I have not quantified this.
3. **NBM availability at 07-11 only.**
   - Training takes the 07Z value only if its LastModified is at or before h:00.
   - Serving takes it if it was available before the snapshot was captured.
   - At 13-16 the 07Z cycle is always available, and the two agree exactly on every row.
4. **The fit is Aug-Sep.**
   - It is fitted on Aug-Sep 2021-25, and the normal is looked up at Aug-Sep centres.
   - An Oct-Nov forward shadow needs a refit on the matching season.
