# Data layer v2: S0 measurement pack receipts (workstation, 2026-10-15)

Receipts for step S0 of the [data layer v2 plan](../../operations/DATA_LAYER_V2_PLAN.md). Items (b), (c) and (i) were
measured on the workstation under the `workstation_heavy.ps1 -Queue` lease. Item (a) was measured on 2026-10-16 from one
public connection; it has its own file. The desk items (d), (e), (f), (h), (j) and
(k) were done by read-only agents, and each has its own file here. The host stat (g) is still owed.

**Embargo compliance.** Every measured input is a workstation copy whose mtime and target date fall before
2026-09-30. Nothing dated 2026-09-30..10-15 was read. No live observation, METAR, TAF, forecast or settlement source was
fetched. Network use was limited to documentation and terms pages, station catalogues, and HEAD or anonymous S3 LIST
calls on objects dated before 09-30. The bench scripts and their raw JSON outputs are kept on the workstation in
`C:\wt\workstation-chat\l-data\s0bench\`.

| File | Items |
| --- | --- |
| [s0d-open-meteo-field-map.md](s0d-open-meteo-field-map.md) | (d) every served Open-Meteo request, its fields and members, where it is stored, and what is not requested |
| [s0ef-stations-and-licences.md](s0ef-stations-and-licences.md) | (e) MOSMIX ids for 51 airports, AMeDAS for RJTT, TAF TX/TN, AWC limits; (f) licence sheet |
| [s0hjk-s3-prereg-sockets.md](s0hjk-s3-prereg-sockets.md) | (h) S3 `data_run/` feasibility; (j) 88a freeze check; (k) websocket counts; `last_good_sources.json` writer |
| [s0a-l2-delta-bytes.md](s0a-l2-delta-bytes.md) | (a) L2 delta bytes per (token, hour) from one public market-channel connection, 2026-10-16 |

## Results

### (a) L2 deltas are several GB/day raw and heavy-tailed (details in the s0a file)

One public market-channel connection, 792 tokens (12 built-ins × event days 10-15..10-17), 2026-10-16 00:09Z-12:56Z.
The run ended on the reconnect abort rule. Full hours were 01Z-11Z; 13Z-23Z were not sampled.

- **Volume.** Raw payload is ≈3.1 GB/day for the T+0 exec-tape universe (264 tokens) and ≈7.0 GB/day with T+1.
  `price_change` is over 98% of it.
- **Budget.** The per-(token, hour) budget that binds in <5% of token-hours is **1.8 MB** (T+0) or **1.9 MB**
  (T+0+T+1). For <1% it is 7.7 MB or 5.7 MB.
- **Tail.** A p95 budget would drop 45% (T+0) or 26% (T+0+T+1) of the bytes.
- **Peak.** 2,255 frames/s.
- **Not measured.** The post-gzip ratio, and the US daytime hours.

### (b) Book write-on-change is lossless; about half the book rows repeat

Input: the three 2026-08-05 events that have `order_books.jsonl` on the workstation (San Francisco, Seattle,
Toronto): 246,224 captures, 882 MB, median per-token interval 15.0 s.

- **50.3%** of consecutive per-token captures have identical quote content (bids, asks, tick size, minimum order size,
  neg-risk flag, last trade price). **44.7%** have an identical venue `hash`.
- The venue hash **never** stayed the same while the content changed (0 of 246,158 pairs). On 5.6% of pairs the hash
  changed but the content did not. So the hash is a safe change key, and content comparison catches about 5.6 points
  more repeats.
- A write-on-change journal, with a per-token heartbeat of 0, 300, 900 or 3,600 s, replays to the exact content at
  every original capture: **0 mismatches** in all four cases. It keeps 48.4-49.0% of the bytes. A 3,600 s heartbeat
  added no rows, because every token changed at least hourly that day.
- This is the reconstruction test that §9 Q5 required. The byte saving is on plaintext; the saving after hourly gzip
  (VR-6) is not measured.

### (c) Codec bench: LZX beats LZNT1 by 3.0-7.3x; xz beats gzip by 1.2-3.4x

Input: 64 MiB line-aligned samples of four July/August `data/snapshots` families, plus three whole forecast CAS blobs
(26-33 MiB). NTFS results come from `compact.exe` on copies, measured with `GetCompressedFileSizeW`. Every round trip
was verified byte-identical.

| Family | gzip-6 | gzip-9 | bz2-9 | xz-6 (MiB/s) | xz-9e | LZNT1 | WOF XPRESS8K | WOF XPRESS16K | WOF LZX |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clob_diagnostics jsonl | 40.6 | 47.4 | 74.7 | 58.3 (26.6) | 83.8 | 3.91 | 9.67 | 14.6 | 28.4 |
| observation_triggers jsonl | 13.3 | 13.9 | 24.4 | 44.8 (20.3) | 50.4 | 2.20 | 3.52 | 4.22 | 7.16 |
| loop diagnostics jsonl | 26.4 | 28.9 | 41.8 | 32.0 (17.3) | 45.2 | 3.22 | 5.74 | 7.96 | 16.3 |
| clob_loop console log | 11.0 | 11.5 | 13.3 | 13.2 (16.0) | 14.3 | 2.91 | 5.97 | 7.44 | 9.70 |
| forecast CAS blob (3) | 6.8-8.1 | 7.3-8.6 | 14.0-16.9 | 14.3-17.1 (3.8-4.0) | 15.5-18.6 | 2.29-2.58 | 3.5-4.0 | 3.8-4.5 | 7.0-8.2 |

- **CP-5:** the plan's gate, LZX at least 1.5x better than LZNT1, is met on every family tested (3.0-7.3x).
- **CP-1:** stdlib xz-6 beats gzip-6 by 1.2-3.4x. It runs at 16-27 MiB/s on JSONL but only about 4 MiB/s on the
  pretty-printed forecast blobs.
- A 64 MiB dictionary (`lzma6_dict64m`) gained nothing over preset 6 at this sample size. zstd was not available.
- Timings are from a 32-thread workstation and are indicative only.

### (i) Import time and memory: OpenBLAS commit dominates

Each module was imported 3 times in a fresh interpreter (3.11.9, numpy 2.4.6 with scipy-openblas 0.3.31,
`MAX_THREADS=24`, 32 logical CPUs).

| Module | Wall s | Modules loaded | Working set MiB | Private (commit) MiB |
| --- | ---: | ---: | ---: | ---: |
| `weather.collection.snapshot_tracker` | 0.95-0.98 | 872 | 97 | 814 |
| `weather.operations.observation_trigger` | 0.97-0.99 | 876 | 99 | 816 |
| `weather.market.market_microstructure` | 0.32-0.34 | 455 | 47 | 775 |
| `weather.operations.execution_tape_supervisor` | 0.31-0.35 | 463 | 47 | 774 |
| `weather.market.execution_tape_capture` | 0.19-0.20 | 274 | 32 | 23 |
| `weather.market.maker_evidence_capture` | 0.17-0.18 | 276 | 32 | 23 |
| `weather.market.maker_shadow` | 0.13-0.14 | 137 | 28 | 19 |

- `import numpy` alone commits 756 MiB of private memory with no thread cap. That falls to **113 MiB** with
  `OPENBLAS_NUM_THREADS=4` and **17 MiB** with `OPENBLAS_NUM_THREADS=1`. The cost is OpenBLAS's per-thread buffers,
  about 30 MiB per thread, sized from the CPU count up to the build's cap of 24.
- In the repository only `experiment_executor.py:1201-1203` sets a BLAS thread cap. The capture workers do not.
- **Host lead (not measured on the host):** each numpy-importing capture process likely commits about
  min(logical CPUs, 24) × 30 MiB. Ops can confirm with a stat-only read of the processes' private bytes and the host's
  logical CPU count. If it holds, setting `OPENBLAS_NUM_THREADS=1` in those tasks' environment frees that commit
  without a code change.
- For the evidence host (PL-6), the 88a and execution-tape import set costs about 23 MiB of commit and loads in
  0.2 s, so long-lived children are cheap. Any child that imports numpy or pandas needs the thread cap.

### (d) Open-Meteo: what we already store (details in the s0d file)

- The 12 built-in markets make six Open-Meteo requests per market, and the full responses are already kept per event
  under `data/snapshots/<event>/forecast_payloads/sha256/`. All requests are hourly, `forecast_days=2`, in native
  units.
- No run identity is stored, so FC-11 writes `run_init` as null or `blend_unresolved`.
- **Finding:** `fetch_global_ensemble` (`model_sources.py:2209-2290`) labels the unsuffixed `temperature_2m` column
  as the "ensemble mean" and uses it for `day_max`. On stored 2026-08-10 San Francisco payloads, that column is not the
  member mean: the mean absolute gap is 0.26-0.54 °F (max 1.26 °F), and its rank among the 30 members moves between
  0.17 and 0.73. It matches a member value exactly in 28-37 of 48 hours. GEFS has 1 control and 30 perturbed members,
  and the payload has 31 columns. The column is the **GEFS control run**. Train and serve read the same column, so
  parity holds, but the feature name is wrong. A true member mean or a member-high median is an untested candidate.
- FC-3 should shadow only what is not served: per-model fields other than temperature, the models we do not request
  (ICON, UKMO, Météo-France, JMA, CMA, KMA), ensemble members beyond GEFS temperature, daily max/min, and
  15-minute temperature.

### (e)/(f) Stations and licences (details in the s0ef file)

- All 51 settlement airports have a DWD MOSMIX id. Shanghai's MOSMIX point (58362) is 42 km from Pudong, and London's
  is 7.7 km off. Paris, Seoul and Tokyo (47671) are exact. Haneda's AMeDAS station is 44166.
- **Plan corrections:**
  - DWD's current legal notice gives **CC BY 4.0**; no DWD page read mentions GeoNutzV.
  - AWC caps a request at **400 results** and keeps **30 days** of history. It documents no `hours` or `ids` limit, and
    the TAF endpoint has no `hours` parameter.
  - HKO data may be used commercially only when taken through DATA.GOV.HK; material from HKO's own website needs
    written permission.
- The proposed no-token substitute for the Synoptic comparison (IEM vs AWC, 6 stations × 3 days in 09-24..09-29) was
  run **IEM side only** (2026-10-15). The IEM requests were bounded by `sts=2026-09-24T00:00Z` and
  `ets=2026-09-29T00:00Z`, with a client check that no row was at or after 09-30. Row counts: EGLC 240, LFPB 214,
  RKSI 240, RJTT 240, ZSPD 243, KLGA 152; the files are kept on the workstation only. **The AWC side was skipped: its
  date bound cannot be verified.** `/api/data/metar` accepts `date`, but neither its OpenAPI spec nor `/data/api/`
  says how `date` and `hours` combine. Inside the embargo, a request that is not provably date-bounded could return
  current reports, so master-agent declined a probe (2026-10-15). Revisit after 2026-11-13; by then 09-24..09-29 has
  left AWC's 30-day window, so a later comparison needs other days.
- **Side finding:** `config/locations.json` WMO numbers disagree with the DWD catalogue for Munich and São Paulo, and
  three stations (Kuala Lumpur, Chengdu, Taipei) have no DWD entry. Not edited.

### (h)/(j)/(k) and `last_good_sources.json` (details in the s0hjk file)

- **(h)** FC-10 is feasible on the workstation only:
  - `data_run/<model>/YYYY/MM/DD/hhmmZ/<var>.om`, 70 models, no KMA, no ensemble members.
  - 90-day expiry, at most one run per 3 h.
  - Range reads are supported, so whole files need not be downloaded.
  - It needs the `omfiles` wheel (GPL-2.0-only library, CC BY data) plus a small HTTP range shim.
  - Bytes per point are not measured.
- **(j)** The 10-01 maker-P&L pre-registration freezes no 88a code. The freeze was DECISION_LOG 10-03/10-07, "until
  after 2026-10-14", and has lapsed. The pilot can land. A dated clarification that pilot bands are outside Part 2's
  "all 12 markets" stratum would remove the one ambiguity.
- **(k)** Measured at commit `9fc1ff062`, which is before #177's make-before-break swap:
  - The host steady state is about 5-6 market-channel sockets: execution tape 3, 88a trades 2-3, plus 0-1 for 88a
    updates.
  - The pilot adds about 1 trade socket.
  - Any 88a universe change re-slices **every** trade socket. A separate pilot stream would isolate built-in prints.
- **`last_good_sources.json`** (`model_sources.py:596-619`):
  - Every snapshot pass reloads the whole file and rewrites it with `write_json_atomic`, even when nothing changed.
  - The ~36 MB size is the embedded NBM bulletin text (`nbm_probabilistic_tmax.py:359-371`).
  - At the 10-minute default cadence that is an estimated 5.2 GB/day of writes per US station, about 57 GB/day across
    the 11. The host cadence is not confirmed; two host mtime reads about 10 minutes apart would settle it.
  - Fixes: strip `raw_payload.text` (FC-8, S8(c)), and skip the save when the cache is unchanged.

## Still owed

- (a) follow-up: the US daytime hours (13Z-23Z) and a second weekday, before the VR-2 budget is fixed; the post-gzip
  ratio of `price_change` JSON.
- (g) Host stat: one pre-09-30 closed event's `observation_payloads` size, and the `last_good_sources.json` rewrite
  cadence.
- Host check of capture-process private bytes against the OpenBLAS lead in (i).
- FC-10 bytes per point on a pre-09-30 run, before its budget is set.
