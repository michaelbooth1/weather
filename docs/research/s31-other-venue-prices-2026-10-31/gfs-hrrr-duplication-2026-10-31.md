# `gfs_seamless` = `ncep_hrrr_conus`: docs evidence, where the pair was counted twice, and K corrections (2026-10-31)

Lane L14, for master. This task came from Clarification 1 §5. It uses three inputs only: Open-Meteo's official
documentation, a grep over `docs/` and `src/` at `origin/master` `035f5bb19`, and arithmetic on the p-values
already recorded in the row 78 receipt. No data was re-read or re-run, and no venue was contacted. Working files
are in `C:\archive\ruled-out\_s31-intake\gfs-hrrr\` (§5). The draft findings note for master to land is
`ef_draft_gfs_seamless_is_hrrr.md`.

**This was already closed.** EXHAUSTION_REGISTER X63 (master ruling 2026-10-30) records it as NOT A DEFECT:
"seamless = HRRR within ~57 h", and the 2-day capture window keeps target hours inside that horizon. L2's live
probe (`1081d6d7…`) is the measurement. Clarification 1 §5 re-raised the question without first checking X63.
This file adds the provider's own wording, and the K and labelling consequences that X63 did not list.

## 1. Documentation evidence (0)

- URL: <https://open-meteo.com/en/docs/gfs-api>, fetched 2026-10-31. HTTP 200, 510,079 bytes, sha256
  `c88ac6fbb5e8c349194499abbfe7708f40a4c78f5a19016e12622df6c148655f`, archived (§5).
- The "Data Sources" section says the API "combines them with high-resolution HRRR forecasts". In that
  sentence, "them" is the global NOAA GFS forecast.
- The same section limits the high-resolution data to the United States; elsewhere only GFS is used.
- The model-selection note defines a "Seamless" model as combining all of one provider's models into a single
  prediction.
- The HRRR horizon in the page's model table is 18 h, or 48 h for the 00, 06, 12 and 18Z runs.
- The docs do not give the exact handover lead. L2's probe measured about 57 h (X63), which is consistent with a
  48 h run horizon plus run age.

**Reading.** Over CONUS, inside HRRR's horizon, `gfs_seamless` is HRRR by provider design. It is GFS only beyond
that horizon or outside the United States. Toronto (CYYZ) lies inside the HRRR grid (register S6), so the same
holds there for any `gfs_seamless` read at short leads.

## 2. Where the pair was counted as two sources (b)

| Where | What counted both | Effect | Verdict change |
| --- | --- | --- | --- |
| Ledger row 78, rule_mr_sweep `85f8192c` §3, register X46 `OM-GFS` and X47 `OM-HRRR` | Both are separate candidates in one BH family of K = 17. | Identical Δ, p and per-date sums, so one signal was tested twice. Effective K = 16. | **None** (§3). |
| Register X54 `OM-MM-SPREAD` (`open_meteo_multimodel.day_high_spread`) | The range over {gfs_seamless, HRRR, NBM, NAM}. | **None on value.** A max − min is unchanged by a duplicate member, so this is really a 3-model range. Only the label overstates the member count. | None |
| Register X55 `OM-GM-SPREAD` (`open_meteo_global_models`) | Neither column: its members are IFS, AIFS, AIGFS and GraphCast (`model_features.py` global aliases). | None | None |
| Register X6, L4 inverse-MSE blend (NBM, "GFS", IFS, ICON; rule `96dee78c…`; `l4_blend_candidate.py`) | Only `gfs_seamless` (Previous Runs day-1); HRRR is not a separate member. | No double count. Over CONUS at day-1 leads, the "GFS" member is plausibly HRRR, so the label is suspect, not the K. | None |
| Ledger row 9, register X4, F4 `f4_gfs_seamless` (`free-source-screens-2026-10-23.md`) | `gfs_seamless` was scored as a new member after HRRR "already tested and excluded" (EF §10q). | Within its 00-12 capture window, F4's "GFS" read is a re-test of captured Open-Meteo HRRR, not a GFS read. There was no BH, and the read was null. | None. The label should say HRRR-in-horizon. |
| Ledger row 79, rule_forecast_tracking §overlap (TRK-HRRR, PROJ-HRRR; register X66, X68) | Its overlap list says "OM-\* except HRRR: no overlap". | OM-GFS is the same series as OM-HRRR, so the overlap list is incomplete. K = 5 is its own family and contains no GFS arm. | None |
| Served and research features, `src/weather/model/model_features.py` (`open_meteo_multimodel` block) | `open_meteo_gfs_high_delta` and `open_meteo_hrrr_high_delta` are separate columns. | They are identical within the horizon. HGB pickles under `artifacts/models/hgb/` list both names. For trees a duplicate column changes only split tie-breaking and the importance split, not the fitted function class. Register S6 says the served model selects no HRRR column. | None (no BH) |
| Same block: `reference_high` (median of the four highs when `forecast_high` is missing) and `open_meteo_multimodel_run_to_run_high_change` (median vs median) | Medians over {seamless, HRRR, NBM, NAM}. | HRRR gets double weight in a 4-value median, so the result is no longer a 3-model median. The range features (`open_meteo_multimodel_high_spread`, `open_meteo_multimodel_next_3h_spread`) are unaffected. | None (no test used them as a family member) |
| `model_features.py` `_guidance_highs` / `build_us_guidance_replay_diagnostics`, `reporting/research/guidance_extract.py`, `reporting/source_gates/official_guidance_sparse_coverage.py` | `open_meteo_gfs` and `open_meteo_hrrr` appear as separate per-source rows. | Diagnostics report the same MAE twice. These are not tests. | None |
| `model_sources.py` `fetch_open_meteo_multimodel` (`/v1/gfs`, models gfs_seamless, ncep_hrrr_conus, ncep_nbm_conus, ncep_nam_conus) | The request asks for both models and keeps a separate key for each. | This is the origin of the pair. The code is correct; the provider blends. | None |

**Not covered.** History-side corpora use Open-Meteo **Previous Runs** `gfs_seamless` day-1:
`forecast_training_corpus.py` `DEFAULT_MODEL`, `openmeteo_previous_runs.py`, `l5_corpus.py`, the MG-2
`pit_previous_runs_gfs_seamless_day1` input, `NEW_CITY_MODEL_LANE.md` and `PIT_FORECAST_TRAINING_CORPUS.md`.
Whether the archived seamless series for 2021-2025 also switched to HRRR at short leads, and from what date, is
**not established** by the docs or by X63. Settling it would need a data read, which this task forbids. If
the composition changed during those years, the "GFS" history would be a time-varying blend. That would be a
train/serve parity question for the owning lane, not a K question. I flag it and do not claim it.

## 3. K corrections (c): arithmetic on recorded p-values

Only one BH family contains both members: **row 78** (K = 17, q = 0.10, UNTESTABLE p = 1).

- Input: the receipt's per-candidate `p0.p_one_sided` and recorded `bh_q`, from `mr_sweep.json` sha256
  `02c4663097797be5a8ad2d18380486a2a95cffc5da4593f9e0e645553e93aac2`.
- Check: recomputing BH at K = 17 reproduces every recorded q exactly.
- Correction: BH with OM-HRRR removed (K = 16).

| Candidate | p | q (K = 17, recorded = recomputed) | q (K = 16) |
| --- | --- | --- | --- |
| MET-COOLING | 0.0478 | 0.8125 | 0.7647 |
| OM-NAM | 0.1199 | 0.8833 | 0.8314 |
| OM-GM-SPREAD | 0.1559 | 0.8833 | 0.8314 |
| OM-MM-SPREAD | 0.3176 | 0.9774 | 1.0000 |
| MET-MAX | 0.3588 | 0.9774 | 1.0000 |
| MET-COVER | 0.3761 | 0.9774 | 1.0000 |
| OM-BEST | 0.6288 | 0.9774 | 1.0000 |
| OM-AIGFS | 0.6593 | 0.9774 | 1.0000 |
| NBM-SKEW | 0.6830 | 0.9774 | 1.0000 |
| OM-IFS | 0.6877 | 0.9774 | 1.0000 |
| OM-GFS (= OM-HRRR) | 0.6899 | 0.9774 | 1.0000 |
| MET-DEWDEP | 0.8122 | 1.0000 | 1.0000 |
| GEFS-MEMBER-CENTRE | 0.9896 | 1.0000 | 1.0000 |
| GEFS-CONTROL | 0.9933 | 1.0000 | 1.0000 |
| OM-AIFS, OM-GRAPHCAST (UNTESTABLE) | 1 | 1.0000 | 1.0000 |

- **No BH rejection at K = 17 or at K = 16.** The smallest q moves from 0.8125 to 0.7647, still far above 0.10.
- MET-COOLING would need p ≤ 0.10/16 = 0.00625 to be rejected, and it has 0.0478.
- **No verdict changes**, so no dated clarification to any row is required. X46 and X47 should be read as one
  candidate.
- Some q values rise to 1.0 at K = 16. That is the BH step-up cap at a smaller m, not a change of evidence.

No other family in `docs/` holds both members in one multiplicity adjustment:

- row 79: K = 5, HRRR only;
- row 9 (F4): no BH, gfs_seamless only;
- X6: one blend candidate;
- every other `docs/` and `src/` hit for either model id in the grep is a single-member use, or a diagnostic
  with no BH (§2).

## 4. Suggested record changes (master's to land; not edited here)

- Register X46 and X47: annotate "same series as X47 / X46 (X63); effective K for row 78 = 16; no verdict
  change".
- Register X54: annotate "range over three distinct series (seamless = HRRR in horizon)".
- Register X4 and X6: annotate that within-horizon "GFS" is HRRR for CONUS markets.
- Row 79 rule overlap note: OM-GFS overlaps the HRRR arms exactly as OM-HRRR does. This is a reading note on a
  frozen rule, not an edit.
- New EF section from `ef_draft_gfs_seamless_is_hrrr.md`.

## 5. Provenance (R13 archive `C:\archive\ruled-out\_s31-intake\gfs-hrrr\`; scratch kept outside)

| File | sha256 |
| --- | --- |
| `open-meteo_docs_gfs-api_20261031.html` (official docs page) | `c88ac6fbb5e8c349194499abbfe7708f40a4c78f5a19016e12622df6c148655f` |
| `l14_gfshrrr_bh.py` (BH arithmetic, reads only the receipt JSON) | `c19035ef98c54d32e2b4824a394d8137e8605d6a73192a4486df8ca11f12682e` |
| `l14_gfshrrr_bh_out.json` | `100c798c0d07822668711fff888fa96e5cf4333622fdc6aad4709a5368c95537` |
