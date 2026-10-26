# L11 item 2: Standard-time / DST alignment audit of the Oct-Dec training rows (2026-10-25)

Lane L11, branch `claude/permarket-bias-20261026`. This lever was relayed by the coordinator as lever 2 of 2 (lever
inventory row 11; EF §10w, §1m). It is a code and timestamp trace only.

**Read:** inputs and timestamps.
- the three Oct-Dec PIT corpora;
- the L9 NBM corpus;
- WU observation timestamps;
- WU temperatures at or before each record's cutoff, for the high_so_far recompute only;
- the L2 records' input columns.

**Not read:** `final_bucket`, daily summaries, outcomes and prices. Nothing dated after 2025 was read.

## Verdict

**Zero misaligned training rows.** Across the fall-back change (2021-11-07, 2022-11-06, 2023-11-05, 2024-11-03 and
2025-11-02), three things are aligned on every one of the 57,736 Oct-Dec trainer records:
- the local-hour cutoff;
- NBM cycle selection;
- the WU print cutoff.

The records cover 11 markets x the 5 centres 10-10, 10-25, 11-09, 11-24 and 12-09, x 14 cutoff hours. They break down
by regime as follows:
- 31,878 on standard-time dates;
- 25,088 on daylight-time dates;
- 770 on the change day itself.

The §10w defect (fixed-offset Open-Meteo labels read as wall time) **does not reach these corpora or records**.

## What was checked

| Path | Code trace | Measured check | Rows (std / dst / change) | Misaligned |
| --- | --- | --- | ---: | ---: |
| WU obs timestamps, Oct-Dec 2021-25, 11 stations | trainer `minute_of_day` comes from the stored `local_time` (`model_climatology` cache) | stored `local_date`/`local_time` and `valid_time_local` against `valid_time_utc` read in the market's IANA zone | 89,079 / 51,743 / 1,509 | **0** |
| PIT union 674b12ac (cd0ba2bb, 23ac87fa, 74807fbe), hourly | the collector maps fixed-offset labels with label minus `utc_offset_seconds` (`resolve_provider_times`) and pads the request by one day for the edge hour (manifest `request_padding`) | `valid_time_local` against the UTC instant in the zone; local date is the target date; each profile has 23/24/25 distinct hours spanning local 00:00..23:00 | 73,128 / 45,672 / 1,375 | **0** |
| PIT union, daily rows | `_feature_as_of` = the local cutoff hour in the zone | `feature_as_of_utc` against the local cutoff; `available_at` and `issue_time` are at or before it; `forecast_high_native` against the local-day hourly max | 42,658 / 26,642 / 770 | **0** |
| WU print cutoff in the records | `build_historical_feature_record`: obs with `minute_of_day` <= cutoff x 60 | (a) the pre-cutoff obs set from stored wall time equals the set from UTC-derived local time; (b) the record's `high_so_far` equals the recompute; (c) `minutes_since_cutoff` equals `wall_offset_for(date, hour)` | 31,878 / 25,088 / 770 | **0** on (a), (b) and (c) |
| NBM cycle selection (P3d_N anchor) | `ols_floor_ladder.nbm_at_cutoff`: `_cutoff_instant` uses ZoneInfo | the cycle chosen at the true cutoff; also the cycle a fixed daylight-offset cutoff would choose | 31,878 / 25,088 / 770 | **0** (the 07Z cycle is chosen on every row; a 1 h cutoff error would change no selection) |
| §10w-affected record columns | `reanalysis_*` and live-source columns are in the record schema | non-null count on 9 sampled record files | 9,450 rows | all null; none is a P3d_N / L3 / R0 feature |

## Detail and caveats

- **Fall-back day:**
  - The first measured pass flagged 77 WU rows and 110 PIT rows on the change days. These were false positives from
    Python's PEP 495 rule: an ambiguous `fold=1` instant never compares equal across zones.
  - A re-check on UTC timestamps found 0 of 1,509 WU and 0 of 1,375 PIT change-day rows misaligned.
  - The repeated 01:xx wall hour gives duplicate `minute_of_day` values. They sit before every cutoff (07 and later),
    so high_so_far is unaffected.
- **NBM Tmax window (descriptive, not a misalignment):**
  - The NBP Tmax column in the corpus is valid at +1 d 00Z in both regimes and in all 11 markets.
  - Its local end therefore moves by 1 h across the change: 20:00 EDT becomes 19:00 EST.
  - This is the product definition, and serving reads the same parser, so train and serve agree.
- **Scope limit:**
  - Only the trainer records and corpora used by P3d_N, P3d_N_fix and L3 were audited.
  - Not audited: the Open-Meteo training readers that §10w lists (`forecast_history.local_valid_datetime`, reanalysis
    readers). Their only path into these records is the reanalysis columns, which are null here.
  - The fix for those readers (`a399941e`) stays as §10w describes.
- **Data root:**
  - WU obs were read from the main checkout's `data/wunderground`, the only populated copy.
  - The exact record-level high_so_far recompute (0 mismatches on 57,736 rows) shows the records were built from the
    same timestamps.

## Provenance

- Script `C:\t\l11pb\dst\dst_audit.py` (sha256 7013343c9bb0d1e9df383b17700362cc8453b8adefb63647d4b8f28de38dc9a6).
- Output `dst_audit.json` (438cf4f71c3ff81f78b218804f2e504f0fd21690c927b8f26ac0a1ab339248dc).
- Fall-back re-check `change_check.py` (0b74b60128217dcca0d021fe0e4573ec8a7e97831521320032b8cdc36791794a).
- Null check `rean_check.py` (bb288714af559b0f8be542105e8d5d3ee9acbc66e8f4c83bd9a8bec9cef0ba27).
- All three were direct, single-threaded and read-only runs, logged in `C:\t\l11\jobs\direct_runs.log`.
- Code traced at `C:\wt\l11pbrun` (L2 l2run eb7ff73bc plus this branch).
- Corpora `cd0ba2bb004dc89f…`, `23ac87fa5f058f8e…` and `74807fbef1ba33ce…`; NBM corpus `1ae4bf52…`; records
  `C:\t\l2\records`.
