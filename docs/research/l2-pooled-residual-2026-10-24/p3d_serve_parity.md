# P3d serve-parity check (lane L2, 2026-10-25): eligibility condition 1 of the MG-2 afternoon pick rule

Pick rule: C:\t\mg2\afternoon_pick_rule.md, sha256 5898bfb01e3eafc3f9ce731dee237fd05f342d873456e5d1e156b15550c5818e.
Condition 1 says every input must be available in the capture at serve time, with the same cutoff semantics.

Sources:
- Code: `weather.calibration.pooled_residual_model` (`dev_training_frame`, `dev_fits`, `dev_emit_distributions`, `MeanModel.features`).
  - Branch claude/pooled-residual-model-20261024; file sha 20bbf46f…7da, identical in the run worktree C:\wt\l2run.
- Vectors: C:\t\l2\p3d_dev\dev_P3d.jsonl, sha256 f3b02bf0a32bbe0fe1cf6c75837e63750333c9b3b24ee19f1746b8bb0f1ef65b.

Every check below reads code, captured inputs and forecasts only. No label or outcome was read.

## Verdict

**Condition 1 FAILS strictly, on one input: forecast_high.**
- P3d trains on, and is scored with, the Open-Meteo Previous Runs `temperature_2m_previous_day1` from `gfs_seamless`. That value comes from the PIT dev corpus 57232fde…, resolved at the cutoff, so it is the run issued about one day before the target date.
- The capture does not record that value.
  - The capture does hold `open_meteo_multimodel.day_model_highs.gfs_seamless`, but that is the current run at capture time: a different lead.
  - No serve-path module calls the Previous Runs endpoint. In `src/`, `PREVIOUS_RUNS_URL` appears only in the training and history modules.
- The difference is large. On these 13-16 rows, the layout's served `forecast_high` minus the PIT value has MAE 2.26 °F, a mean of +1.03 °F, and is at least 1 °F apart on 72% of rows.
- **Arm A has exactly the same gap.**
  - L3 dev_rule "main features at serve" uses the same `pit_2026` forecast source, and arm A is scored on the same 79,403 snapshots.
  - So condition 1, applied as written, also removes arm A's forecast input. It does not separate P3d from arm A.
  - The input is free and public, and it was issued before the cutoff, so it could be computed at serve time if the capture added a Previous Runs fetch. That is a serving change, and it needs a ruling.

All other inputs pass, with the same semantics as arm A.

## Input-by-input

The model has these features, and the `x_` columns are kept to `x_high_so_far` and `x_current_temp`: (high_so_far − mu0), (current_temp − mu0), g, max(g, 0), mu0 − normal, lat, lon, elev, normal, bias, doy_sin and doy_cos. The anchor is mu0 = forecast_high + bias (or the normal if there is no forecast), and g = high_so_far − mu0. P3d is pooled, so there is no market id.

| Input | Source at dev scoring | In capture at serve? | Same cutoff semantics? |
| --- | --- | --- | --- |
| forecast_high | PIT corpus 57232fde… (Previous Runs gfs_seamless day1), resolved at the cutoff hour | **No** (see verdict) | Issued before the cutoff: yes. Captured: no. |
| high_so_far (feature, g, and the floor) | Captured METAR rows (`sources.metar.data.rows`) from the last replay snapshot captured in [h:00, h+1:00). Keyed on the raw DDHHMMZ group, restricted to the local target date, only rows observed at or before h:00, max since local midnight. The code is L3's `scan_replay_observations`; its main path is unchanged between 171717d5f (which I used) and eaed66d6a. | Yes | Yes. It is the trainer's definition (max of target-date rows with minute ≤ h·60). L3 clarification 3: it equals L8's `running_max_since_midnight` on all 9,224 replay hours. P3d's snapshot set is identical to arm A's (79,403, symmetric difference 0). |
| current_temp | Same snapshot: latest kept METAR row at or before h:00 | Yes | Yes |
| cutoff hour h | Snapshot's effective `cutoff_hour`, emitted only if local_hour ≥ h | Yes (snapshot metadata) | Yes |
| target date → doy_sin, doy_cos, nearest Aug-Sep centre for the normal | Snapshot `target_date` | Yes | n/a (calendar) |
| lat, lon, elev | `config/locations.json` | Static config | n/a |
| bias (per market, Aug-Sep), normal (per market and centre), OLS, mean HGB, scale HGB, z set, p_clim, bucket space | Fitted once on Aug-Sep 2021-25 trainer records (union 744289be… of b455bd53…; 45,873 rows; no 2026 row) | Model state, not a captured input | n/a |

## Shared caveats (the same for arm A; descriptive)

1. **Training source for high_so_far and current_temp.**
   - Training reads them from WU history rows, in whole °F.
   - Serving reads them from METAR, in tenths from the T-group.
   - These are the same station reports. L3 dev_rule records this as a documented mismatch.
2. **Within-hour snapshot choice.**
   - Every snapshot in an hour takes its features from the last capture in [h:00, h+1:00).
   - The rows are restricted to those observed at or before h:00, so no observation after the cutoff is used.
   - But a snapshot taken early in the hour may not yet have received a report observed at or before h:00 that arrives late. I have not quantified this, and it affects both candidates equally.
3. **The fitted model is for Aug-Sep.**
   - The dev vector comes from a fit on Aug-Sep 2021-25, and the normal is looked up at Aug-Sep centres.
   - A forward shadow in Oct-Nov would need a refit on the matching season. That would be the P3 recipe with P3d's features, on Oct-Dec plus Aug-Sep, which has no dev read.
   - Arm A's dev fit (centre 09-07) has the same property.

## Dev vectors handed to L3's harness

- `C:\t\l2\p3d_dev\dev_P3d.jsonl`
  - sha256 f3b02bf0a32bbe0fe1cf6c75837e63750333c9b3b24ee19f1746b8bb0f1ef65b.
  - 79,403 rows, cutoffs 07-20, 11 markets.
  - Keys {distribution, market, snapshot_id, target_date}: the same format as `C:\t\l3\dev_l8\dev_l8_high_so_far_ols_floor.jsonl`.
  - Every distribution sums to 1. The snapshot set equals arm A's.
- `C:\t\l2\p3d_dev\dev_emit_audit.json`, sha256 068729a2b2869ec53fa65922be2d60c5ca678ca98395cd53f0c7f3aef871151c.
- Declare the candidate with `--trained-through 2025-12-31`.
- It is byte-identical to the file scored in L2 amendment 3 (C:\t\l2\dev\dev_P3d.jsonl).
