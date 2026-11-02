# L50: outcome-free input coverage on the sealed pre-boundary panel (2026-11-01)

Dated research evidence (lane L50, close-the-gap 2026-11-01). It counts NBM v2 / L6 **inputs** on the
sealed pre-boundary panel (target dates 2026-06-03..2026-07-30, D=50, M=12; governed by
[CAMPAIGN_LEDGER.md](../../operations/CAMPAIGN_LEDGER.md)). Read it before you propose the panel as a
confirmation reserve for a development winner. No label, settlement value, price, panel band row or
`promotion_countable` flag was opened. No score was computed.

## What was read, and what was not

The workstation copy of the closed-market-day archive (`data/archive/closed_market_days/v0.1`) holds
261 folders for 2026-05-27..2026-07-11. That is a partial mirror; the panel itself has 524 market-days
and lives on the production host.

- **Read:** the parquet schema (column names only) of each family. From `forecast_payloads_long`, these
  input-metadata columns only: `snapshot_id, captured_at_utc, source, status, payload_hash,
  payload_bytes, source_url, raw_payload_path, fetched_at`. From `features_long`, `cutoff_hour` and
  whether `high_so_far` is null (never its value). Also whether CAS blobs exist, and the first 400 bytes
  (the issue header) of each NBP-sized blob in `data/forecast_payload_cas`.
- **Not opened, because the file mixes inputs with outcome or served fields:** `replay_inputs`, whose
  `sources` is one JSON column holding every source, including station and WU surfaces, next to
  `recorded_distribution`. The MG-2 allow-list ([mg2_input_allowlist.py](../../../src/weather/calibration/mg2_input_allowlist.py))
  exists because these files carry forbidden keys. Also not opened: `snapshots_long`, `components_long`,
  `forecasts_long`, `clob_features_long`, and any settlement or ledger file. **Any METAR or P3d input
  count for the panel therefore needs an allow-list export on the host**, like `mg2_input_export`.

Scripts (each takes its roots as arguments): `tools/research/l50_preboundary_coverage/`:
`l50_schema_probe.py` (sha256 `c0baec51…`), `l50_cov_v2.py` (`02c04696…`) and `l50_blobs_v1.py`
(`54f9cb6a…`). Outputs in this folder: `coverage_rows.json` (one row per date x market) and
`meta.json`.

## Findings

1. **NBM capture did not exist before 2026-06-23.** The `nbm_probabilistic_tmax` source first appears
   in code on 2026-06-21 (`2e3672d99`). In the archive, every US folder from 06-23 on has NBM rows, and
   no folder before 06-23 has any (90 of 90 US folders dated 06-23 or later have them; 0 of 136 before 06-23). The first
   captured cycle is `blend.20260623/19`. That cycle does not hold the 06-23 maximum (EF §10k/§10l), so
   **the first target date with a usable captured NBM v2 input is 06-24.** This is structural and holds
   on every host.
2. **No captured NBM bytes for 06-23..07-12 are on the workstation.** The archive rows point to
   per-snapshot JSON copies on the former capture machine (`raw_payload_path`). None of their 10,429
   payload hashes is in the workstation CAS. Whether the host kept those copies is UNVERIFIED.
3. **The workstation CAS holds every NBP bulletin from `20260713T13Z` to `20260812T07Z`.** That is 178
   blobs, NBM V5.0 (the same version as dev), with all six cycles (00/01/07/12/13/19Z) every day except
   08-09 12Z. So the bytes cover target dates **07-14..07-30 (17 calendar dates)** completely. The 07-13
   target has no qualifying cycle on the workstation.
4. **Toronto has no NBM** (US only), so any NBM, L6 or MG-2 arm has M ≤ 11.
5. **The L6 nowcast input is missing for the panel.** `data/research/upstream_obs/obs.parquet` covers
   2021-25 Aug-Dec and 2026 from 07-30T00Z only. A free IEM fetch for 2026-06-01..07-30 would be needed.
   It is a METAR history fetch, outcome-adjacent, and must be ruled first.
6. **Snapshot timing for 07-12..07-30 is not on the workstation.** The archive stops at 07-11.

### Coverage table (structural: captured NBM v2 available for the target at capture time)

A snapshot counts when a captured NBP cycle was seen (fetched) at or before its capture time and holds
the target's maximum (cycle date D-1, or D at 00/01/07Z). The bytes were not parsed.

| Panel span | Calendar dates | Panel stratum | NBM captured? | Bytes on WS | WS archive US market-days / snapshots with v2 |
| --- | ---: | --- | --- | --- | --- |
| 06-03..06-23 | 21 | B (in-season) | **no** (source did not exist) | n/a | 0 / 0 of 20,482 (142 market-days) |
| 06-24..06-30 | 7 | B | yes, 6 to 7 US markets in the WS archive | **no** | 42 of 42 / 4,681 of 4,871 |
| 07-01..07-11 | 11 | C (out-of-season) | yes | **no** | 42 of 42 / 6,267 of 6,267 |
| 07-12..07-13 | 2 | C | unknown on WS | no (07-13 has none) | not on WS |
| 07-14..07-30 | 17 | C | yes (WS was the fetcher) | **yes, complete** | snapshot folders not on WS |

The panel's 50 dates are a subset of these 58 calendar dates. Which 8 are excluded is decided by
`promotion_countable` admission, which this lane did not read. Per-market detail is in
`coverage_rows.json`. In the WS archive, LA, Miami, NYC and SF have no folders after 06-18.

## Which arms could be scored

| Arm | Panel dates it could use |
| --- | --- |
| MG-1, L6, the MG-2 07-12 half, or any captured NBM v2 arm | at most 06-24..07-30 (≤ 37 calendar dates, of which ≤ 7 in-season B), US only (M ≤ 11). Today on WS bytes alone: 07-14..07-30 (≤ 17), C only. L6 also needs the IEM obs fetch. |
| P3d / P3d_N (13-16) | inputs sit in `replay_inputs` (mixed); count only through a host allow-list export |
| Non-NBM arms (L47 FLOOR_MIX on the replay HGB, a Toronto arm) | not limited by NBM; limited by the replay instrument |
| Emulated NBM (NOAA `noaa-nbm-grib2-pds` NBP history with S3 LastModified availability, as LOYO did) | could cover all 50 dates for US markets. It is NOT captured-input replay, so it needs a master ruling. |

## Alpha and power arithmetic (planning, not a measurement)

- Budget: 13 of 20 decisions left. Per decision α = 0.0025 two-sided, quantile q = 3.1098893
  (amendment A1). MDE multiplier ×1.4104552 against unadjusted.
- Reference MDEs after the ledger and A1 (CAMPAIGN_LEDGER post-ledger × 1.0223929), as a share of each
  endpoint's gap: in-season 1.018% (23 dates), out-of-season 9.814% (27), tail 4.983%, primary window
  09-14 13.216% (49 dates).
- Crude scaling, assuming MDE ∝ √(1/D) · √(1/M) and nothing else changing. **This is an assumption.**
  The panel's crossed variance is not additive in this simple way.
  - In-season, with only 06-24..06-30 (≤ 7 dates, M 11): × √(23/7)·√(12/11) ≈ 1.89, so about 1.9%.
  - Out-of-season, with 07-14..07-30 (≤ 17 dates, M 11): × √(27/17)·√(12/11) ≈ 1.32, so about 12.9%.
  - A 07-12-only window, using the 09-14 primary window as its proxy: ≈ 16.6% of gap at 34 dates (assumed panel dates inside the 37 calendar dates 06-24..07-30); ≈ 23.4%
    at 17 dates.
- Power at α 0.0025 for the 07-12 window at 34 dates (SE ≈ 16.6 / (3.110 + 0.842) ≈ 4.2% of gap): a
  true 5%-of-gap step has power ≈ Φ(5/4.2 − 3.11) ≈ 0.03; 10% ≈ 0.23; 15% ≈ 0.68; 25% ≈ 1.00. Dev already caps
  centre fixes near 25% and tempering near 12% (close-the-gap synthesis). **So on NBM-dependent arms the
  panel can confirm only a large step. It cannot confirm a parity-sized 07-12 improvement.**
- Unaffected: the panel's in-season all-hours and tail endpoints for arms that do not need NBM, at the
  ledger's own MDEs.

## Unsure

- The register's B row says "05-27..06-30". The ledger and the 08-09 report say target dates
  06-03..07-30. The register row looks wrong.
- Whether the host kept the per-snapshot NBM JSON for 06-23..07-12, and whether it holds snapshot
  folders for 07-12..07-30, are not checked. Settling both needs an outcome-free host inventory of
  `forecast_payloads` only.
- The coverage is structural (cycle and timing). It does not parse bytes with the pinned parser.
