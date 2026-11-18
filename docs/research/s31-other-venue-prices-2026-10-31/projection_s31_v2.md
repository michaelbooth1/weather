# S31 v2 coverage projection and power at edge (2026-10-31)

Status: the outcome-blind projection that `rule_s31_v2.md` §6-§7 requires before the freeze (ledger row 102,
lane L14). It reads quote presence and timestamps only: no bid, ask, price, volume or outcome value was read.
The rule (sha256 `4495b6526e69698bab8bc5e9e0943b2adbd17526a3dc7b8a9fabd30d501b3315`) is not edited.

## 1. What was run

`python -m weather.calibration.s31_v2 project --layout C:\swarm\v3layout --out C:\t\l14v2\proj` ran directly as
a light script, with PYTHONPATH set to the run tree's `src`.

| item | value |
| --- | --- |
| commit | `ed417c8363ec58f29be5a971f74e8a26c7ace485` |
| `s31_v2.py` sha256 | `1fe2d815b363df37b83a7ab7545863beac06a9cb1404c75ac8d847ecc8c1ab45` |
| `s31_p0.py` sha256 | `d3f24f103e02eddd0156a36404c7ca7606ee5a640ba9e2a723b01980873f39cb` (unchanged) |
| output `s31_v2_projection.json` sha256 | `fd7be619a24dc14202ae00285a8c8abd06436a7d4b6e240dc09fe3bcd6ffb2a4` |
| inputs | v1's pinned twin extracts (`s31_p0.INPUT_SHA256`), checked |
| wall time | about 24 s |
| peak memory | working set 515 MB; peak commit 1,384 MB |

The output was byte-identical on three reruns. The peak commit exceeds the 1 GB light-script line, while the
working set stays under it. This is disclosed rather than hidden.

Field allowlists (proved by `tests/calibration/test_s31_v2.py`):
- **Candles:** `job`, `run_id`, `ticker` and `end_period_ts`, plus the presence of `yes_bid_close` and
  `yes_ask_close`. Every JSON float token maps to a sentinel.
- **Snapshots:** the 8 allowlisted columns of the manifest-verified `inputs_snapshots.parquet`. No other layout
  file is opened.

## 2. Coverage projection (counts only; an upper bound)

| quantity | count |
| --- | --- |
| V0 events kept | 329 of 329 |
| scored dates | 43 (08-15..09-29) |
| KAL fit snapshots (08-14 + scored, all markets) | 85,825 |
| KAL-market scored snapshots | 53,269 on 43 dates |
| covered fit snapshots (k ≥ 5) | **51,734**: 46,760 with 6 bins, 4,974 with 5 bins |
| missing bin when 5 quoted | lower tail 1,017, interior 2,201, upper tail 1,756 |
| uncovered: fewer than 5 of 6 bins present | 2,819 |
| uncovered: not a KAL market / no finite cutoff | 31,271 / 1 |
| donors: cells under 2 covered dates | 0 snapshots |
| donors: band-count mismatches | 0 (snapshot, seed) pairs |
| donors: snapshots with no seed | 0 |
| seeds dropped entirely | none (20 of 20 kept; each has 50,463 snapshots on 43 dates) |
| **projected population** | **50,463 snapshots on 43 dates**; floors (20 dates, 1,000 snapshots, J_MIN 10) met |

**The caveat that matters.** This is a loose upper bound. The projection cannot apply the value checks
(0 < bid ≤ ask < 1, spread ≤ 0.20).

Row 99's value-checked run found 5,696 snapshots with all six bins valid. Presence alone finds 46,760 with all
six present. So the value checks, not quote absence, removed about 88% of six-bin coverage in v1. Most likely
this is zero bids, or wide spreads in the tail bins. That is a reading of counts only.

The k = 5 rule tolerates one invalid bin per event. How many of the 46,760 have exactly one invalid bin cannot
be known without reading values. The realised v2 coverage lies between v1's 5,696 and the 51,734 here.

## 3. Power at edge (rule §7)

The inputs are as follows.
- **Scratch script.** `C:\t\l14v2\power\s31_v2_power.py`, sha256
  `da6a725951d5860d3eac818d7fdf92bb0d65961aef6f5a1550a426b5a852aca7`. Its output `power_out.json` has sha256
  `8121d5b67ed1d8c59628a35d0031166d99e7517ea5e09154810ba210c2c9e04e`.
- **Row 78 rows.** `mr_sweep_rows.jsonl`, sha256 `c1bfe405…5b73`, the same file as Clarification 1.
- **REV-2 serial dependence.** The circular block-3 run (B 2000, seed 20261024) on row 78's per-date d_t gives
  ρ = 0.2719 and ratio = 1.1128. VIF = max(1, 1.7470, 1.2384) = **1.7470**.

| case | N dates | S_full / S_proj per date | σ_proj | SE | power at Δ_edge 0.224 |
| --- | --- | --- | --- | --- | --- |
| **primary: the projection** | 43 | 1,238.8 / 1,173.6 | 0.09748 | 0.01965 | **≈ 1.00** (z = 9.44) |
| sensitivity: v1's value-checked floor (5,696 / 43 per date) at the 20-date floor | 20 | 1,238.8 / 132.5 | 0.29016 | 0.08576 | 0.74 |

## 4. Decision under rule §7

Power at edge is at least 0.5, on the projection and on the pessimistic floor alike, and the floors are met.
**Freeze is eligible.**

The rule sha is pinned in `s31_v2.RULE_SHA256` only after master's or the coordinator's admit. Until then
`run` refuses. The P0 has not been run.

Two disclosures go with that:
- The realised N is reported at run, and it can only be lower than the projection.
- Power at edge says the run can tell "KILL at edge size" from a survivor. It says nothing about smaller
  effects. Clarification 1's SCREEN class, MDE80 0.054 at N 43, still stands.
