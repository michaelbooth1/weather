# S0(h), S0(j), S0(k) + last_good_sources receipt — 2026-10-15

Code: commit `9fc1ff062` (master plus the 10-15 docs batch), read only. Line numbers are for that commit.
Compliance: no data, panel, settlement, snapshot or 88a content was opened for any date. The only file content read
under `data/` was none: the `last_good_sources.json` files were stat'ed, not opened. S3 access was limited to anonymous
LIST and one HEAD, all on keys dated 2026-09-20 or July 2026. No object body was fetched and no Polymarket connection
was made. No pytest or heavy command was run.

---

## (h) FC-10: Open-Meteo S3 `data_run/` feasibility

**Sources:** `open-meteo/open-data` README (raw.githubusercontent, fetched 10-15), `python-omfiles` README,
pyproject and `src/fsspec_backend.rs`, examples `xarray_data_run.py` and `select_by_coordinates.py`, the PyPI JSON
metadata for `omfiles`, the `om-file-format` README, anonymous S3 `ListObjectsV2` on `openmeteo` (us-west-2), and one
HEAD.

**Layout (documented, README §Data Organization).** `data_run/<model>/<YYYY>/<MM>/<DD>/<hhmm>Z/<variable>.om` plus
`data_run/<model>/<run>/meta.json`, which is written when the run is complete. Each variable is one file holding the
full run as a time-series-optimised array `[ny, nx, ntime]`. data_run is the last step after `data_spatial/` and `data/`.
It keeps "only 13 pressure levels and model levels below 200 m" and "at most one model run every 3 hours". Timesteps
are at native model resolution, not interpolated, and backward-sum variables drop the first step.

**Retention.** The README says 3 months. The HEAD confirms it with the header
`x-amz-expiration: ... rule-id="DeleteRunDataOlderThan90Days"`. The earliest listed day prefixes are 2026-07-12 for
ecmwf_ifs025 and 2026-07-13 for ncep_gfs013. Anything older than 90 days cannot be backfilled from AWS.

**Models.** A LIST of `data_run/` returned 70 model prefixes, including:
- ncep_gfs013/025, ncep_aigfs025, ncep_hrrr_conus(+15min), ncep_nbm_conus, ncep_nam_conus, ncep_rrfs_*,
  ncep_hgefs025_ensemble_mean;
- ecmwf_ifs025, ecmwf_ifs, ecmwf_aifs025_single, ecmwf_ec46_*, ecmwf_seas5_*;
- dwd_icon / icon_eu / icon_d2 (and native variants);
- ukmo_global_deterministic_10km, ukmo_uk_deterministic_2km;
- cmc_gem_gdps_15km, cmc_gem_rdps_10km, cmc_gem_hrdps(+west);
- jma_gsm, jma_msm;
- meteofrance_arpege_* and arome_*;
- cma_grapes_global;
- knmi / dmi / metno / meteoswiss / italia_meteo / geosphere / chmi.

KMA is not there: there is no `kma_gdps` prefix in data_run, and the 09-20 listing was empty. Per-member ensembles are
not published ("Climate, flood, satellite and ensemble models are not published on AWS"); only ensemble means are.

**Run identity.** The run is the directory `YYYY/MM/DD/hhmmZ` (forecast reference time), so identity is exact for each
single model. The S3 `LastModified` gives an AWS availability time for each run, for example on 2026-09-20 (meta.json
LastModified):

| model / run | files | run total | temperature_2m.om | meta.json LastModified |
| --- | --- | --- | --- | --- |
| ncep_gfs013 00Z | 30 | 8.76 GB | 552,133,744 B | 05:54:40Z |
| ecmwf_ifs025 00Z | 115 | 4.08 GB | 57,985,696 B (also `temperature_2m_max/min.om` ~54-56 MB) | 07:42:32Z |
| ecmwf_aifs025_single 00Z | 99 | 2.00 GB | 31,003,520 B | 05:39:05Z |
| dwd_icon 00Z | 108 | 15.41 GB | 207,255,552 B | 03:49:59Z |
| ncep_hrrr_conus 12Z | 108 | 3.17 GB | 55,228,544 B | 13:53:19Z |
| ncep_nbm_conus 12Z | 23 | 1.93 GB | 180,040,304 B | 13:17:03Z |
| ukmo_global_deterministic_10km 00Z | 99 | 15.44 GB | 253,064,200 B | 07:27:21Z |
| jma_gsm 00Z | 79 | 0.41 GB | 7,808,456 B | 09:33:22Z |
| ncep_aigfs025 00Z | 88 | 2.18 GB | 34,239,008 B | 04:22:01Z |
| cmc_gem_gdps_15km 00Z | 24 | 4.00 GB | 212,598,640 B | 05:49:29Z |

HRRR and NBM run hourly, but data_run keeps every 3 h: the 09-20 listing shows 00, 03, …, 21Z. GEM GDPS has 00/12Z only.
data_run is the last product written, so it is not a first-availability clock for the API.

**Format and point reads.** `.om` is a chunked, compressed array format. Compressed chunks come first, then a chunk
lookup table (LUT), metadata, and a 24-byte trailer pointing to the root variable (om-file-format README). Chunks are
typically 1-4 KiB, and the README says a single-location read of the 9 GiB ERA5-Land file needs about 16 KiB. The HEAD
on `data_run/ncep_gfs013/2026/09/20/0000Z/temperature_2m.om` returned `Accept-Ranges: bytes` and
`Content-Length: 552133744`. **So point extraction with HTTP range reads is possible without downloading whole files.**

Bytes per point:
- **Not measured:** fetching object bodies was out of scope for this item.
- Expected: trailer + root metadata + a LUT slice + 1-2 chunks per point/variable/run, about 4-64 KiB in 3-5 range
  GETs. With the upstream examples' fsspec `blockcache` at 64 KiB blocks, that is likely about 128-256 KiB per
  point-variable-run.
- Example estimate: 51 stations × ~10 models × 4 runs × 2-3 variables × 16-64 KiB ≈ 65-300 MB/day. The plan's 15-30
  MB/day needs small blocks and coalescing; nearby stations share chunks.

**Python reader.**
- `omfiles` 1.2.0 (PyPI, uploaded 2026-04-23) is a Rust/pyo3 extension that requires only `numpy>=1.21`.
- There is a `cp310-abi3-win_amd64` wheel (869,558 B), which works on the 3.11.9 venv.
- The workstation venv has numpy 2.4.6 and requests 2.34.2. omfiles, fsspec and s3fs are not installed, and omfiles is
  not in `requirements.txt`. **It is a new wheel**: fine on the workstation, and on the host only with an owner wheel
  pin.
- The `fsspec` extra pulls `s3fs`, which brings aiobotocore/botocore/aiohttp, a heavy tree. This can probably be
  avoided. `src/fsspec_backend.rs` (sync backend, about lines 93-146) calls only `fs.size(path)` and
  `fs.cat_file(path, start=, end=)`, so a roughly 20-line duck-typed object doing plain HTTPS Range GETs against
  `https://openmeteo.s3.amazonaws.com/<key>` with `requests` should satisfy `OmFileReader.from_fsspec`. This is
  **untested**; the first step of the build is to verify it.
- **Licence note:** the data is CC-BY-4.0, but the `omfiles` library is **GPL-2.0-only** (pyproject `license`). That
  is harmless for an internal workstation tool, but should be recorded on the S0(f) licence sheet.
- Grid lookup needs `meta.json`/`crs_wkt` plus `omfiles.grids` (the `grids` extra needs pyproj for projected domains
  such as HRRR, NBM and ICON-D2). Regular lat/lon globals can be indexed by hand.

**Verdict: FEASIBLE for a workstation-only extractor.** These constraints come with it:
- the 90-day expiry, so it must run at least weekly and cannot backfill beyond about 90 days;
- at most 3-hourly runs;
- single-model exact runs only; the API's seamless blends are not reproduced, and there are no ensemble members and no
  KMA;
- one new wheel (omfiles) plus a small custom range-read shim, avoiding s3fs;
- the per-point byte cost must be measured on a pre-09-30 run before the budget is set.

---

## (j) The 2026-10-01 maker-P&L pre-registration and an 88a code freeze

**Document.** `docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md`. It is not on master; it lives
on branch `codex/maker-pnl-adverse-selection-20261001`:
- frozen at `574f8369b`;
- Clarification 1 appended at `67e44273b`;
- the branch head `fb7405231` adds Clarification 2 as a separate file, signed 10-09 per
  `docs/research/live-fill-calibration-signature-2026-10-09.md:13`.

Line numbers below are for the file at `fb7405231`. Lines 1-159 are byte-identical to the frozen `574f8369b` text,
because Clarification 1 only appends.

**Finding: the pre-registration does NOT freeze 88a code identity or behaviour.** No clause names
`maker_evidence_capture.py`, `maker_evidence_store.py`, a code hash, or any code or universe change. These are the
clauses that bind 88a:
- :26-27: "every band that 88a captured (`data/maker_evidence/`) and that is **local T+1 or T+2**". The stratum is
  defined by what 88a captured.
- :111-112: "event date is 2026-10-17..2026-10-30 (14 dates), all 12 markets, same stratum and rules."
- :116-117: "production must retain the 88a sealed segments for UTC 2026-10-15..2026-10-30 … A pruned segment is a
  coverage gap, never imputed." (Also DECISION_LOG.md:90.)
- :147: "Unsealed 88a segments are never read."
- :148-149: "A band-day is excluded … if fewer than 90% of its local quote-day minutes have a book capture."
- :62: fills come from "88a's public trade channel (`last_trade_price` events)".
- :6-7: "Any change after an input is read requires a dated clarification below." The Part 2 inputs are unread, so a
  clarification is still possible.
- Clarification 2 (signed): it drops LFC campaign band-days. It does not touch 88a code.
- DECISION_LOG.md:189 (10-14): the power rule gave N_req = 706 → `UNDECIDABLE_AT_DELTA`. Part 2 is descriptive only
  and issues no verdict.

**Where the freeze actually lives: DECISION_LOG, not the pre-registration.**
- DECISION_LOG.md:102 (10-03): it holds 88a capture code and behaviour changes (#118, #172, #177, #182) "until after
  2026-10-14 so the unread panel is captured by one 88a code version". That panel was the exam panel, 09-30..10-13.
- DECISION_LOG.md:137 (10-07, the owner's clarification): "the freeze covers 88a capture code and behaviour … and the
  bytes of `maker_evidence_capture.py`, `maker_evidence_store.py` and the 88a schema record until after 10-14".
- STATE_OF_PLAY.md:22-23 still lists it: "…wait until after 2026-10-14".
- By its own terms the freeze **has lapsed as of 10-15**. STATE_OF_PLAY should be refreshed. No later row extends it to
  10-30.
- DECISION_LOG.md:163 already accepts a short 88a capture gap inside the 10-15..10-30 panel window (Python cutover).

**What this means for S2 / VR-1 P1.** Under the plan's own test (DATA_LAYER_V2_PLAN.md:117: "if one exists, S2 waits
until after 10-30 or gets an owner amendment"), **no pre-registration freeze exists**, and the DECISION_LOG freeze has
expired. The pilot can land. These conditions keep the Part 2 panel clean:
1. **Inclusion ambiguity.** :26 says "every band that 88a captured" and :111 says "all 12 markets". Pilot cities
   (London, Shanghai, Paris, Seoul, Tokyo) are not in `market_registry.REGISTRY`, which holds only the 12 built-ins
   (`market_registry.py:104-394`). The Part 2 transfer manifest should name the 12 market ids. The cleanest fix is a
   short dated clarification before any Part 2 read stating that pilot bands are out of scope. The gap default at
   :152-153 cannot be used for this, because it excludes changes to "inclusion".
2. **Built-in selection unchanged.** `select_universe` ranks top-10 per city (`maker_evidence_public.py:194-212`), so
   new cities do not displace built-in bands. Keep the plan's ratchet. Note the hard bound "condition universe exceeds
   memory bound" at >1200 conditions (`maker_evidence_capture.py:148-149`), which fails the whole cycle, and the
   `MAX_RAW_BYTES = 500_000_000` latch (`maker_evidence_store.py:20`), which stops built-in capture too.
3. **Coverage.** An 88a restart gap counts against the 90% rule at :148. That allows about 144 min per local quote-day,
   shared with every other gap.
4. **Trade-print continuity.** See (k): adding pilot tokens re-slices *all* trade sockets on every universe change.
   Built-in prints, which are the fill input at :62, then see a few seconds' gap per swap. A separate `PublicStream` for
   pilot tokens would avoid this. Otherwise measure swap frequency before landing.

---

## (k) Polymarket websocket connections by process

All capture sockets use one endpoint: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
(`market_microstructure_constants.py:9`). Nothing at steady state uses `/ws/user` (`:10`); only `mm_user_stream.py:37`
does, for live MM.

### Execution tape (`execution_tape_capture.py`)

**Steady state: 3 sockets.**
- There is one socket per partition group: a `threading.Thread` per group (`:494-509`), each calling
  `websocket.create_connection(CLOB_WS_URL)` (`:310-311`, `:347`).
- Groups are built by `partition_market_days` (`:186-211`), up to `DEFAULT_MAX_TOKENS_PER_CONNECTION = 100` (`:48`),
  never splitting a market-day.
- Seeds are T+0 only: one event per built-in market at its local date (`:124-127`).
- With 12 markets × 11 conditions × 2 tokens = 264 tokens, that is 4 market-days (88 tokens) per group, so **3
  sockets**. The 11 conditions/event count comes from the git-tracked `config/location_market_events.json` at
  `713e27cf3` (2026-09-25), the pre-embargo copy.
- Each socket sends a 10 s PING (`:379-381`).
- Reconnects use per-socket backoff from 1 s to 30 s (`:46-47`, `:466-476`).

**Swaps: break-before-make.**
- `run_live_capture` stops the old fleet before starting the new one: `fleet.stop()` at `:570-571`, then
  `ConnectionFleet(...).start()` at `:577-585`.
- `stop` waits for a single 10 s total deadline across all threads (`:517-521`) and does not raise. A thread stuck in
  its 30 s connect (`:45`) can therefore outlive the deadline, giving a **transient overlap of up to 3 old + 3 new**.
  The normal case is 0 sockets for about 1-2 s.
- A swap fires on any change to `seed_set_sha256`. Its payload includes `target_date` and `source_generated_at_utc`
  (`execution_tape_store.py:326-339`).
- Expected swaps are about **8/day**: one per local-midnight rollover in 4 time zones (Eastern incl. Toronto, Central,
  Mountain, Pacific), plus one per `WeatherLocationConfigRefresh` regeneration, every 6 h
  (`scripts/ops/quiet_window_merge.ps1:3391`).
- Every swap restarts all 3 sockets.

### 88a recorder (`maker_evidence_capture.py` + `maker_evidence_stream.py` + `maker_evidence_socket.py`)

`maker_evidence_public.py` is HTTP only: REST to gamma-api and clob (`:20-21`) through `requests`. It opens no
websocket. Two `PublicStream`s are created (`maker_evidence_capture.py:230`).

- **Trades channel, always on.**
  - It opens ceil(tokens/100) sockets (`maker_evidence_stream.py:14`, `:46-49`), each through
    `maker_evidence_socket.connect()` with a 4 s connect timeout (`maker_evidence_socket.py:50-58`).
  - Tokens are both tokens of every selected condition (`maker_evidence_capture.py:305`, `:312`).
  - The universe is up to 10 conditions per city × 12 cities plus extras (`maker_evidence_public.py:194-212`), so at
    most about 240 tokens → **3 sockets**.
  - At the measured 96 conditions it is 192 tokens → **2 sockets**.
- **Updates (L2) channel.**
  - It runs only while an `extra_conditions` update window is open (≤30 min windows, `:63-80`).
  - It is off when the disk band is red/critical or the stream cap is hit (`:273-275`).
  - It opens ceil(update tokens/100) sockets, **normally 0, otherwise usually 1**.
- **Steady total: 2-3 sockets (+0-1 during an update window).**
- **Swaps: strict break-before-make, never overlapping.**
  - `trades.replace(tokens)` runs every 60 s cycle (`:312`). If the sorted token tuple differs at all, `replace` calls
    `stop()` and then starts new threads (`maker_evidence_stream.py:38-49`).
  - `stop()` joins each thread for 8 s and **raises** `RuntimeError` instead of overlapping (`:51-58`). That error
    becomes a DEGRADED cycle through `maker_evidence_capture.py:316-321`.
  - Tokens are globally sorted and sliced by 100, so any re-rank of any city's top-10, an event closing, or a day roll
    re-slices **all** trade sockets.
  - The gap per swap is about ≤1 s (recv timeout) + close (1 s) + connect (≤4 s). The swap frequency is **not
    measured**. `stream_lifecycle` connect/disconnect events (`maker_evidence_stream.py:69`, `:114`) on pre-09-30 88a
    days would give it.
- There is one process per writer lock (`maker_evidence_store.py:69-71`). The scheduled task's PT5M repetition cannot
  start a second recorder.

### Others

- The CLOB book loop opens no websocket by default (`DEFAULT_LOOP_INCLUDE_WS_EVENTS = False`,
  `market_microstructure_constants.py:20`).
- The retired enrichment loop defaults `include_ws_events=True` (`market_microstructure.py:1801`). It would open one
  1-second socket per market per pass (`market_microstructure_capture.py:1824-1857`).

### Totals

- **Host steady state today: about 5-6 market-channel sockets**: exec tape 3 + 88a trades 2-3, plus 0-1 for 88a updates.
- **VR-1 P1** (+5 cities × ≤10 conditions = +100 tokens) adds about 1 trade socket.
- **VR-1 P2** (all T+1/T+2 bands) would exceed the 1200-condition hard bound (`maker_evidence_capture.py:148`) and need
  dozens of sockets.

---

## Extra: `data\wunderground\<icao>\last_good_sources.json`

**Writer.** `SourceFetchMixin.save_last_good_sources` (`src/weather/model/model_sources.py:596-619`).
- It takes a writer lock (20 × 50 ms attempts, `:601-610`), re-loads the whole file (`:611`), `merged.update(cache)`,
  and calls `write_json_atomic(cache_path, merged)` (`:615`).
- `write_json_atomic` serialises the **whole** payload with `json.dumps(indent=2, sort_keys=True)` to a temp file and
  then replaces the target (`src/weather/io.py:353-368`).
- **So every save rewrites the whole file**, and it is unconditional. `blend_with_last_good` calls it at the end of
  every pass whether or not anything changed (`:760-879`, call at `:878`).
- Path: `spec.data_root / "last_good_sources.json"` (`:621-625`), where `data_root` = `data/wunderground/<icao>`
  (`market_registry.py:50-52`).

**Callers.**
- Every snapshot pass: `fetch_live_sources` → `blend_with_last_good(...)` (`model_sources.py:243`), called from
  `snapshot_tracker.py:221`. Scheduled cadence is a 10-minute default interval (`snapshot_tracker.py:731`, `:857`).
- Observation-triggered snapshots (`observation_trigger.py:792`, `cadence="triggered"`) take the same path.
- The observation trigger's own fetch uses a **different** 8 MiB-capped cache,
  `<snapshots>/observation_source_cache/<market>.json` (`observation_trigger.py:100-101`, `:144-151`, `:354-364`). It
  does not write this file.

**Why it is ~36 MB on US stations (from code, file not opened).**
- The NBM source payload embeds `raw_payload` = `nbp_raw_payload(...)`, which carries `"text": str(text)`: the whole
  national NBP bulletin, about 35 MB (`src/weather/sources/nbm_probabilistic_tmax.py:359-371`, `:507`, `:521`, `:539`,
  `:584`).
- `blend_with_last_good` caches `item["data"]` verbatim (`model_sources.py:768-772`).
- cyyz has no NBM, which fits its ~0.5 MB.
- This is the "strip `raw_payload`" lead already in FC-8 / S8(c).

**Bytes/day (estimate; host mtimes not available to this agent).**
- Writes: at least 144 scheduled passes/day × ~36 MB ≈ **5.2 GB/day per US station**, ≈ **57 GB/day for the 11 US
  stations**, plus one more full rewrite per triggered snapshot.
- Reads: at least 2 full loads + JSON parses per pass (`:761`, `:611`), plus one more per Open-Meteo-family source via
  `cached_source_for_reuse` (`:517`). That is ≥72 MB parsed per pass, ≥10 GB/day/station.
- The workstation copies under `data\wunderground\` are stale (mtime
  2026-08-12, katl 36,107,482 B, cyyz 463,435 B), so they confirm size only, not cadence.
- **To confirm on the host (stat only):** compare two mtime readings about 10 min apart on one US station.
- **Fix candidates:**
  - strip `raw_payload.text`, keeping the hash and URL, which already identify the bulletin;
  - skip the save when the merged cache is unchanged.
