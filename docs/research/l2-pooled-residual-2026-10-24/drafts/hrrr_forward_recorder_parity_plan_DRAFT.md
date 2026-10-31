# DRAFT: HRRR forward recorder and the parity it must prove (R-K)

**Status: DRAFT, design only.**
- Drafted by lane L2 on 2026-10-25. It builds on L13's plan §8 (`C:\t\l13\hrrr_plan.md` sha `afe24c5f…`) and
  R-K (`rule_rk.md` sha `21b5dfe1…7221`, Clarification RK-1).
- No production code, capture loop, Scheduler task or venv is touched.
- Landing a recorder is roll-sensitive if any capture loop imports it (plan §8.6), so it needs its own head,
  `roll_verdict.ps1` and a quiet-window merge.

## 1. Why a recorder is needed: production's Open-Meteo HRRR does not give parity

**What production captures.** It already captures Open-Meteo HRRR, inside the `open_meteo_multimodel` source of
every snapshot. Checked read-only on a ≤ 09-29 replay snapshot (atlanta, 2026-09-09):
- `data.day_model_highs.ncep_hrrr_conus`: the daily high. This is what layout v3's `hrrr_high` and L3's R-N rule
  read (`guidance_extract.py`: `hrrr_high` from `day_model_highs`, `hrrr_issued_at: None`,
  `hrrr_issue_status: "not_exposed_by_open_meteo"`).
- `data.day_rows[*].models.ncep_hrrr_conus`: **an hourly path** (24 local hours, `valid_time`, `temp_native`,
  `cloud_cover`, …).
- `data.fetched_at`: the API fetch time. The source is cached. In the example, a 16:01Z snapshot carried a payload
  fetched at 14:39Z.
- `model_run_age_status: "not_exposed_by_open_meteo_gfs"`: no model cycle is exposed.

**Does it help parity for the remaining-window max? Mostly no.** It cannot stand in for the R-K input, because:
1. **No cycle identity.** Open-Meteo does not expose which HRRR cycle produced the hourly values. R-K's feature is
   defined by point-in-time cycle selection (newest cycle with every needed fh available + 10 min ≤ h:00). Without
   the cycle, neither the selection rule nor its latency can be reproduced or verified.
2. **No training history.** `historical_archive_available: False`. P3d_H is fitted on 2021-25 native AWS HRRR
   point values. A serve-time input from a different product, with no matching history, breaks train/serve feature
   parity by construction.
3. **Different product.** Open-Meteo's HRRR is Open-Meteo's own regridded, interpolated and rounded series. R-K
   uses the native 3 km grid at the station's nearest cell (plan §1), decoded bit-exact against eccodes. A
   systematic offset would pass straight into `k_max` and `k_gap`.
4. **Cache staleness.** `fetched_at` can lag capture by more than an hour, so the as-of time of the values is the
   fetch time, not the snapshot time.

**Where it does help:**
- **Forward and dev agreement diagnostic (inputs only).** On the same snapshots, compare the native `k_max` with
  the Open-Meteo remaining-window max (max of `temp_native` over `valid_time` in [h:00, 17:00 local]). This bounds
  how far a fallback would sit from the trained input. If agreement were tight (for example |Δ| ≤ 1 °F on ≥ 95% of
  rows), the Open-Meteo path could serve as a pre-declared degraded fallback when the recorder misses a cycle, with
  `k_miss` semantics.
- **What it cannot be:** the primary input, and a gap-filler for training.
- **Rule needed:** this diagnostic needs its own short descriptive rule. It reads only inputs, captured ≤ 09-29 for
  dev.

## 2. What the recorder must capture (all as-of-capture)

These are per cycle and message, written once, append-only, in L13's manifest record shape plus the fields below.

| Field | Meaning |
| --- | --- |
| `cycle_utc` | HRRR cycle (hourly) |
| `fh` | forecast hour |
| `valid_utc` | `cycle_utc + fh` |
| `key`, `idx_record` | AWS object key and idx line (identity check, as `rk_hrrr_columns`) |
| `grib_last_modified`, `idx_last_modified`, `grib_etag` | publication time and version, from the listing |
| `listed_at_utc` | when the recorder saw the object in the listing |
| `retrieved_at_utc` | wall clock when the message bytes arrived. **This is the PIT time at serve.** |
| `msg_sha256`, `msg_bytes`, `data_template` | integrity |
| `points{ICAO: {nearest, block3x3}}` | decoded values, same geometry and units as the research corpus |

**Variables:** exactly R-K's, `TMP:2 m above ground` and `TCDC:entire atmosphere`. No others without a ruling.

**Cycles:** every hourly cycle whose fhs can reach [h:00, 17:00 local] for h = 13..16, for every market. In
practice that is cycles from about 15Z to 23Z, fh up to about f6.

**Per snapshot**, at each served 13-16 snapshot, the feature builder must record:
- the cycle selected by the shared `select_cycle`, over recorder rows with `retrieved_at_utc` ≤ snapshot;
- the fhs used and the valid window [h:00, 17:00 local];
- `window_truncated` and depth;
- `hrrr_msg_sha256[]`;
- the computed `k_max`, `k_tcdc` and `k_miss`.

These are stamped into the snapshot payload for captured-input replay and release binding.

**Raw retention** (plan §8.4): the points plus sha256 by default (the research shape). Raw messages are about
60 MB/day and need a storage-pressure ruling.

## 3. Parity to prove before any forward pre-registration is scored

Each check is pass or fail, measured on recorder output, and recorded with shas.

| # | Check | Tolerance |
| --- | --- | --- |
| P1 | Decoder and geometry: recorder vs research fetcher (`hrrr_point_fetch.py`) on the same archived cycles (at least 3 cycles × all 12 stations × TMP and TCDC) | **byte-identical** point records: `nearest` and `block3x3` exactly equal; `msg_sha256` equal |
| P2 | Decoder vs eccodes on committed fixture messages | max abs diff **0.0** (as plan §7) |
| P3 | Cycle selection: the forward `select_cycle` on `retrieved_at_utc` vs the training rule on `LastModified` + 10 min, same snapshots | **same cycle on ≥ 99%** of forward snapshots. Any disagreement must be the forward rule choosing an *older* cycle (conservative), never a newer one. |
| P4 | Latency margin: `retrieved_at_utc` − max(`grib_last_modified`, `idx_last_modified`) | **≤ 10 min on ≥ 99%** of used messages. If this fails, the training margin is widened to the observed 99th percentile, R-K's training corpus is re-selected and P3d_H re-fitted under a new rule. |
| P5 | Feature parity: `k_max`, `k_tcdc` from the recorder vs from the research fetcher replayed on the same cycles and fhs | **exactly equal** (0.0 °F, 0.0 %) |
| P6 | Forward coverage: snapshots at 13-16 with `k_miss` = 0 | **≥ 0.95** per market over the forward window (the gate 1 threshold) |
| P7 | Replay: re-deriving each served snapshot's HRRR columns from the stamped `hrrr_msg_sha256[]` | **byte-identical** columns |

Separately, the agreement diagnostic of §1 against Open-Meteo is reported, not gated.

## 4. Sequencing (proposal)

1. **Shared package:** promote the decoder, geometry, idx/range reader and `select_cycle` into one owned package
   (plan §8.1), imported by both the research fetcher and the recorder. Prove P1 and P2 offline.
2. **Recorder head:** a separate, roll-sensitive head. It lands in the quiet window by `roll_verdict.ps1` and
   `quiet_window_merge.ps1`.
3. **Shadow capture:** forward shadow capture only, with no serving. Prove P3-P7 on the first 14 days. If any check
   fails, fix it and restart the count.
4. **P3d_H forward pre-registration:** written and sha-recorded before the first counted forward day (companion
   draft §4). It is scored only after its day floor is reached.

## 5. Out of scope

- 07-12 HRRR.
- DPT and wind.
- Any paid source.
- Any new dependency: the decoder is pure numpy, already validated.
- Any change to the production venv.
