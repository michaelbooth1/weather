# L48 station filter and selection spec: DRAFT (not frozen)

Status: **draft for master**. Written while holding on the coordinator's relay (2026-11-01). It freezes nothing and
authorises no fetch. It becomes binding only when master approves it and a ledger row is assigned (row: TBD,
coordinator assigns). The gate in `s0.md` §7 stays a draft as well.

Every criterion below uses station metadata, NBP header presence, report timestamps, report-type counts or the
presence of a T-group. **None of them reads a temperature value, a daily maximum, a label or a price**, so the filter
cannot select stations by outcome.

## 1. Universe (fixed now, from S0)

The 1,365 ex-Gulf candidates in `s0_candidate_ids.txt`. The S0 funnel is in `s0.md` §2:

- CONUS `K` ICAO;
- IEM `*_ASOS` network, online with the archive still open;
- archive begins on or before 2021-01-01;
- a block in all five sampled NBP versions;
- not flagged AWOS by IEM;
- state is not `GM`.

**The 11 market stations** (KATL KAUS KBKF KDAL KHOU KLAX KLGA KMIA KORD KSEA KSFO) are **removed from the pool
universe**, leaving 1,354. They enter both arms as the base rows, never as pool rows.

## 2. Selection order (outcome-free, fixed before any fetch)

Sort the 1,354 by `sha256("L48-station-pool-v1|" + ICAO)` as lowercase hex, ascending. This order is the only
source of selection. A station's score, error or label never changes its place.

## 3. Per-station filter (applied after that station's IEM fetch, before any label is built)

Window: local dates Aug 1..Dec 31 of 2021-2025, 765 local days. IEM `report_type=3` (routine) and `=4` (special) are
fetched separately, as in `s0.md` §4 step 2.

A station **survives** only if all five of these hold:

| ID | Criterion | Threshold |
| --- | --- | --- |
| F1 | IEM returns a non-empty routine file for each of the 5 years | all 5 |
| F2 | Routine reports with a non-missing `tmpf` whose raw text carries a remark T-group `T[01]ddd[01]ddd` | share ≥ 0.95 over the window, and ≥ 0.90 in each year |
| F3 | Label-complete local days: routine reports with a non-missing `tmpf` (presence only), at least 18 of them, and no gap over 180 min including the gaps from local midnight to the first report and from the last report to the next midnight | ≥ 0.90 of the 765 days, and ≥ 0.80 in each year |
| F4 | Mean special (`report_type=4`) reports per local day | ≤ 20 (the S0 AWOS-like stations ran about 47 a day) |
| F5 | Modal minute of the routine reports | a single minute holds ≥ 0.80 of the routine reports (hourly ASOS pattern) |

Days that fail F3 at a surviving station are dropped from the corpus. That is the same `label_complete` rule as
`new_city_corpus`, and it uses timestamps only.

## 4. Stopping rule (N = 300, coordinator recommendation)

Fetch stations in the §2 order, apply §3 to each as it completes, and **stop when 300 have survived**. The 300
survivors are the pool. Because each station's filter is independent of the others, this gives exactly the first 300
survivors of the full ordered list, without fetching all 1,354. That saves about 16 h of IEM fetch if about 75% pass.

Every station fetched is logged, whether it passes or fails, with its F1-F5 values, and the log is committed. A
station that fails is never refetched or re-tested under a looser threshold. A transient HTTP failure gets at most 3
retries, then the station counts as failing F1.

- **Dose arm (reported, not deciding):** the first 100 survivors in the same order, nested inside the 300.
- **Fallback:** if all 1,354 are exhausted with fewer than 300 survivors, the pool is every survivor. That is
  reported, and no threshold is relaxed.

## 5. NBP side

The NBP extractor (S1) runs only for the 300 survivors plus the 11 markets, on L9's 675 dates. A station-date with no
block, or whose parser v2 output is not `available` with a finite mean and stddev, is dropped from the rows. The
count is reported per NBM version as control C-d. A missing block never drops a station after selection.

## 6. Not used for selection

These are listed so nobody adds them later. Each would be outcome-adjacent or a researcher degree of freedom:

- distance to a market;
- climate zone;
- NBM error;
- label agreement with WU;
- historical temperature range;
- hand-picked "similar" stations.

Spatial neighbours of the markets are allowed. LOYO removes the held-out year from every station, so a
same-date neighbour row never trains the fold it is scored in.

## 7. Storage

Raw IEM files go under `C:\t\l48\corpus\raw\iem\<icao>\{routine,special}\<year>.csv` with `receipts.jsonl` (URL,
bytes, sha256, UTC time). The filter log goes to `C:\t\l48\corpus\filter_log.jsonl`. Both are copied to this branch
in summary form after S1.
