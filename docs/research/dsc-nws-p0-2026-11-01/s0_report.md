# DSC-NWS P0: S0 report (R28a, lane L40, 2026-11-01, revision 2)

S0 was an inputs-only screen. No P0 statistic or outcome was computed, and no data dated 2026-09-30 or later
was read. It supports [rule_dsc_nws_p0.md](rule_dsc_nws_p0.md).

**Revision 2** applies master's review of `1aff095c8`:

- **Item 2:** W1's n is now gated on the snapshot's own METAR record receipt. That re-ran the inputs-only
  compute.
- **Item 3:** v is relabelled to the layout NBM v2 mean that S0 already used, so no re-run was needed for it.
- **Item 9:** the register rows are added.

The revision 2 numbers replace revision 1's for W1. FADE and GAP are unchanged.

## Receipts

| item | sha256 |
| --- | --- |
| run-env source (`C:\wt\l3loyoenv`, clean at `8bb0f9563582885c4d01d34b67476f2563260e43`) | — |
| layout manifest `C:/swarm/v3layout` | `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22` |
| replay inputs SHA256SUMS (`replay-inputs-le0929`) | `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` |
| row 30 nowcast `C:\t\l3\l6cap\nowcasts.parquet` | `3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3` |
| extraction `extract_s0.py` (nws_grid, Open-Meteo; one run per market, serial) | `c70dee7b4673aa31d4577e6638abf41a6ada73407d2b25ef17c101f3f9af6310` |
| extraction `extract_metar_v1.py` (rev 2; metar receipt fields; one run per market, serial) | `188dab675a773e0fad80ccbfe7ed535d8dae6eebe5858ea2a1a6e8b7f7e8b2f6` |
| compute `s0_compute.py` (rev 1) / output `s0.json` | `bafc2bfbfe1b4b43aed83e9c1fde3fb0fefdf144242387254bac4c8ea8075c4f` / `fdac48109b6bb608049cbd06e1bda5783d7869cda1cbfd758e58975e8eccb21b` |
| compute `s0_compute_v2.py` (rev 2, adds the METAR gate) / output `s0.json` | `83be1508c8a5550774fe381875eeb5e456bbb8dfcc3bca0706b4625c0e991e44` / `025b478075cec1759936b7f69fbf452d94941c73c218630148d8d2a393792952` |

- **Extraction coverage:**
  - `extract_s0.py` matched 28,809 of the 28,815 layout snapshots at 07-12.
  - `extract_metar_v1.py` matched 28,809 as well.
  - Both found 0 malformed lines.
  - The per-market METAR extract shas are recorded in the rev 2 `s0.json`.
- **Light-script rule:** every script ran directly with `python -I -B`, each run under 1 min and under 1 GB,
  with its sha recorded first. No pytest, training or replay was run.
- **Label disclosure:** `mr_gate.build_tables` loads `sc.Table`, so labels for dev dates ≤ 09-29 were loaded in
  both computes. They were never accessed. μ_m (market prices) was read for the FADE values and the population.

## (a) The W1 nowcast: capture time, per snapshot, record receipt

- **Coverage:** `n_own` covers 27,868 of the 28,815 layout snapshots at 07-12 (0.967). There are 0 rows outside
  07-12.
- **Not last-in-hour:** 3,710 of 3,713 market-date-hour cells have more than one snapshot (mean 7.5), each with
  its own n.
- **Previous-day max:** D−1's last capture falls between 23:xx and about 02:00 local, so the previous day's max
  is known before D 07:00. That D−1 record is not re-gated (rule §8).
- **Units:** n and v (layout `v2_mean`) are both °F. Median |n − v| is 1.74 °F.
- **No 00-06 nowcast exists** (`l6.HOURS` = 7..12), so **W1-0006 is dropped**.

**METAR record receipt gate (review item 2, `rule_mr_sweep` §2).** It requires `ok`, `fetched_at` ≤ t_c,
`report_time` ≤ t_c and `target_date_match`. Applied to the 27,868 fit and 21,111 scored W1-covered snapshots:

| failure | fit | scored |
| --- | --- | --- |
| any (dropped) | **4,139** | **3,215** |
| `ok` not true | 0 | 0 |
| `fetched_at` > t_c | 0 | 0 |
| `report_time` > t_c | 4,139 | 3,215 |
| `target_date_match` not true | 0 | 0 |

- **Why `report_time` fails:** every failing `report_time` is a top of hour (minute 0). It runs 0-7.5 min
  (median 3.2 min) after captures taken at :52-:59. That is the nominal hour stamp of a routine METAR whose
  record was fetched before t_c.
- **The rule's check is kept as written anyway**, as the review requires.

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

## (c) Realised population (method rule 16; revision 2; the rule's C0 targets)

The population is covered scored snapshots whose 20 placebo donors are also covered, under every seed.

| arm | fit covered | scored covered | population (snapshots / dates) | donor failures (per-seed max / sum) | projected SE | power at edge / at 2 × SE |
| --- | --- | --- | --- | --- | --- | --- |
| W1-0712 | 23,729 | 17,896 | 9,432 / 43 | 2,001 / 39,535 | 0.0288 | ≥ 0.9999 / 0.973 |
| NWS-FADE-0712 | 28,796 | 21,693 | 21,391 / 43 | 26 / 434 | 0.0191 | ≥ 0.9999 / ≥ 0.9999 |
| NWS-GAP-0712 | 28,796 | 21,693 | 21,391 / 43 | 26 / 434 | 0.0191 | ≥ 0.9999 / ≥ 0.9999 |

- **Floor:** all three pass (20 dates, 1,000 snapshots).
- **W1 by market:**

  | market | snapshots |
  | --- | --- |
  | Seattle | 1,134 |
  | San Francisco | 1,087 |
  | Los Angeles | 1,064 |
  | Chicago | 1,015 |
  | Austin | 990 |
  | Houston | 972 |
  | Dallas | 816 |
  | Atlanta | 792 |
  | NYC | 725 |
  | Denver | 558 |
  | Miami | 279 |

- **Power reference:** RATE-0712 (row 81), SE 0.02296 at N 14,820.

## (d) Redundancy screen (pooled Spearman, covered fit snapshots at 07-12; revision 2)

| pair | ρ | n | verdict |
| --- | --- | --- | --- |
| NWS-GAP vs NWS-FADE | −0.490 (per market −0.31 to −0.58) | 28,796 | keep GAP |
| W1 vs DIS-HN-0712 \|H − N\| | −0.035 | 23,700 | keep |
| W1 vs OM-MM-SPREAD | +0.003 | 23,700 | keep |

These pairs were computed for information only and decide nothing:

- W1/FADE 0.102;
- W1/GAP 0.138;
- |GAP| vs DIS-HN 0.094;
- FADE vs MM-SPREAD −0.081.

**FADE and GAP both tilt away from NWS.** After their signs, the raw ρ of −0.490 is an effective signal
correlation of **+0.49**.

**Result: K = 3** (W1-0712, NWS-FADE-0712, NWS-GAP-0712).

## (e) Proposed EXHAUSTION_REGISTER rows (unnumbered; the 11-03 docs head assigns X numbers after X91)

| candidate | result | data | verdict | note |
| --- | --- | --- | --- | --- |
| W1-0006: L6 OWN nowcast vs NBM v2 disagreement at 00-06 (R28a; ledger row 95's W1 family) | no capture-time 00-06 n exists; the L6 OWN model is defined and fit only for local 07-12 (`l6.HOURS`) | dev 08-15..09-29, US11 (S0 inputs only) | **UNTESTABLE** (register §6) | Reopen on a survivor of the R28a DSC-NWS P0, or on a new Oct-Dec rule that discloses the A0 fallback count instead of gating at 0.90. |
| DIS-NWS: \|NWS grid high − NBM\| or \|NWS grid high − HRRR\| as a market-residual S (widening) arm | not built | — | **CLOSED-BY-RULE** (method rule 15), reopenable | It extends the model-disagreement family. Siblings: ledger row 81's DIS-HN-0712/DIS-NG-0712 and X54/X55 (OM-MM-SPREAD, OM-GM-SPREAD), all KILL. Reopen on a survivor of the R28a P0. |
| NWS level tilt: follow the NWS grid high (D, σ = +1 on nws_max − μ_m) | not built | — | **REFUSED AT INTAKE** (method rule 14), not KILL | It is the "already priced" prior with no named mechanism, and S16 already scores the NWS high as a centre. The fade direction is tested instead (R28a NWS-FADE-0712). |

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
