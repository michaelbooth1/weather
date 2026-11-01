# DSC-NWS P0: S0 report (R28a, lane L40, 2026-11-01)

S0 was an inputs-only screen. No label, outcome or P0 statistic was computed, and no data dated 2026-09-30 or
later was read. It supports [rule_dsc_nws_p0.md](rule_dsc_nws_p0.md).

## Receipts

| item | sha256 |
| --- | --- |
| run-env source (`C:\wt\l3loyoenv`, clean at `8bb0f9563582885c4d01d34b67476f2563260e43`) | — |
| layout manifest `C:/swarm/v3layout` | `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22` |
| replay inputs SHA256SUMS (`replay-inputs-le0929`) | `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` |
| row 30 nowcast `C:\t\l3\l6cap\nowcasts.parquet` | `3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3` |
| extraction script `extract_s0.py` (scratch, one run per market, serial) | `c70dee7b4673aa31d4577e6638abf41a6ada73407d2b25ef17c101f3f9af6310` |
| screen script `s0_compute.py` (scratch, `python -I -B`, 16 s) | `bafc2bfbfe1b4b43aed83e9c1fde3fb0fefdf144242387254bac4c8ea8075c4f` |
| output `s0.json` | `fdac48109b6bb608049cbd06e1bda5783d7869cda1cbfd758e58975e8eccb21b` |

- **Extraction coverage:** 28,809 of 28,815 layout snapshots at 07-12 matched, with 0 malformed lines.
- **Light-script rule:** every script ran directly, in under 1 min and under 1 GB, with its sha recorded
  first. No pytest, training or replay was run.

## (a) The W1 nowcast is capture-time and per snapshot

- **Coverage:** `n_own` covers 27,868 of the 28,815 layout snapshots at 07-12 (0.967). There are 0 rows outside
  07-12.
- **Not last-in-hour:** 3,710 of 3,713 market-date-hour cells have more than one snapshot (mean 7.5), each with
  its own n.
- **Previous-day max:** D−1's last capture falls between 23:xx and about 02:00 local, so the previous day's max
  is known before D 07:00 on every date.
- **Units and scale:** n and v are both °F. Median |n − v| is 1.74 °F.
- **No 00-06 nowcast exists** (`l6.HOURS` = 7..12), so **W1-0006 is dropped**.
- **Caveat:** the receipt check uses METAR observation time (+10 min) within the snapshot's own record, not
  the METAR `fetched_at`.

## (b) NWS maxTemperature: presence and staleness, 07-12

- **Presence:** given `ok`, presence is 1.000 at every hour, with at most one `max_temp_native` per record.
- **Receipts:** 0 receipts are after the capture time.
- **Coverage:** 28,796 of 28,815 fit snapshots are covered (0.998-1.000 by hour).
- **`stale` flag:** True on 10 fit snapshots, all `cache_status` fallback (0.0006 at hour 9 and 0.0014 at
  hour 10). They are not filtered (rule §2).

Provider update age on the fit table:

| local hour | median age (h) | share > 6 h | share > 12 h |
| --- | --- | --- | --- |
| 07 | 3.79 | 0.212 | 0.0008 |
| 08 | 4.23 | 0.309 | 0 |
| 09 | 3.96 | 0.362 | 0 |
| 10 | 4.56 | 0.415 | 0 |
| 11 | 5.15 | 0.403 | 0.031 |
| 12 | 2.61 | 0.337 | 0.021 |

Scored dates are similar.

## (c) Realised population (method rule 16)

The population is covered scored snapshots whose 20 placebo donors are also covered, under every seed.

| arm | fit covered | scored covered | population (snapshots / dates) | donor failures (per-seed max / sum) |
| --- | --- | --- | --- | --- |
| W1-0712 | 27,868 | 21,111 | 12,945 / 43 | 958 / 18,469 |
| NWS-FADE-0712 | 28,796 | 21,693 | 21,391 / 43 | 26 / 434 |
| NWS-GAP-0712 | 28,796 | 21,693 | 21,391 / 43 | 26 / 434 |

- **Floor:** all three pass (20 dates, 1,000 snapshots).
- **W1's population is thinned by donor failures.** The smallest markets are Miami (312) and Denver (565);
  the largest is Chicago (1,696).
- **Power:** see rule §5.2. It is ≥ 0.9999 at the edge for every arm.

## (d) Redundancy screen (pooled Spearman, covered fit snapshots at 07-12)

| pair | ρ | n | verdict |
| --- | --- | --- | --- |
| NWS-GAP vs NWS-FADE | −0.490 (per market −0.31 to −0.58) | 28,796 | keep GAP |
| W1 vs DIS-HN-0712 \|H − N\| | −0.034 | 27,838 | keep |
| W1 vs OM-MM-SPREAD | +0.004 | 27,838 | keep |

These pairs were computed for information only and decide nothing:

- W1/FADE 0.106;
- W1/GAP 0.134;
- |GAP| vs DIS-HN 0.094;
- FADE vs MM-SPREAD −0.081.

**Result: K = 3** (W1-0712, NWS-FADE-0712, NWS-GAP-0712).

**Disclosure:** μ_m (market prices) was read for the FADE values and the population. Labels were loaded but
never accessed. The screen values come from L40's own extraction of the same capture fields, not from the
pinned `record_features`.

## Foreign S0 (report only, not a gate on this rule)

**Questions:** is the International Polymarket CLOB `prices-history` fidelity ≤ 5 min, and is the series a book
mid or the last trade?

- **L14-B receipts were insufficient.** `C:\t\l14thin` requested `fidelity=60` and dropped `p`, so they cannot
  answer either question. The file with sha `608203df` was not located by sha.
- **New requests:** 13 public GETs (cap 20) on dev-era events: London, Paris, Tokyo and Shanghai "highest"
  2026-09-14, middle band. Each event got a gamma `closed=true` lookup, data-api trades (limit 500) and
  `prices-history` at `fidelity=1`, with windows ending ≤ 2026-09-15.
  - v1 (`foreign_s0_fetch.py`, sha `189ddc489cd3ce6a7add2c07aa7a7d6679b4c4afcb1a300b3aee49a6fa94c155`) used
    1 request and got an empty gamma list, because closed markets need `closed=true`.
  - v2 (`foreign_s0_fetch_v2.py`, sha `df750f763e34781a4d27a5da3f3138adfc2537a7367f479e46ca98eb7fe42e9a`)
    used 12. Raw bodies are in `C:\t\L40\foreign_raw_v2`, manifest sha
    `c34e6114f90a358c4b6bd72e8adde05ca7f278c4ee3e5510771e1b891db42313`.
- **Fidelity: PASS.** All four series have points at a median gap of 60 s and a maximum gap of 155-156 s.
- **Mid vs last trade: not last trade.**
  - The history point equals the prevailing last trade of that token only 312/3,585 (London), 60/1,995
    (Paris), 20/1,447 (Tokyo) and 34/635 (Shanghai) times. Each count is over the window the fetched trades
    cover.
  - Prices move in half-cent steps on a 0.001-tick book, which is consistent with a mid of quotes.
  - Mid itself is not proven without a book snapshot.
  - Verdict under the brief's rule: **no FAIL**, so no post-B forward item is triggered. Mid is recorded as
    likely, not proven.
