# L48 station-pooled corpus: LOYO gate 1 verdict (row 109): **KILL**

Date: 2026-11-02, 13:05 EST (WS clock). Rule: `rule_station_pool.md`, sha256
`33d5c67ab499e7efde18b7a9f08cd970134df7d0416853925335eea0b1210938`. Training-only blocked LOYO over 2021-25 Aug-Sep,
hours 07..12, scored on the 11 markets. **No dev data was read.** The rule's dev stage (§8) is not run.

**Verdict: KILL.** The only kill condition that fired is **#3**: one market is CI-worse.

## Run identity

| Item | Value |
| --- | --- |
| Module | `src/weather/calibration/station_pool_corpus.py` sha256 `229157eda294dfbf89c16d82b239c86e5aeaae534023fe881c414501036f2013` (build and LOYO, both run through `workstation_heavy.ps1 -Kind weather_heavy -Queue`) |
| Fetch script | `tools/research/station_pool_fetch_v2.py` sha256 `98ddd33e9671c0ca723a7d735e0c4513e74fd64c76827551cdda82fd40c2ef5c` (direct, light) |
| Corpus | `corpora/a57e10a60fce936a98cd8478423b502496afa7347967eaaac1d452e453aad39f`: 528,503 pool rows, 300 stations, 88,101 station-days; 26.9x the 19,657 base rows (pool100 is 8.97x) |
| LOYO rows | `loyo_rows.jsonl` sha256 `cb313205f45faf5b17bf970b69bc80c408d8a6cdf93cca2a4a3f24dbcdbab377` |
| LOYO report | `loyo_report.json` sha256 `ce4a610acd43de5ebeb1f1bed542463c125f292d578d71af7112939fe7cfa83f` |

## Controls

| Control | Result |
| --- | --- |
| C-0 (gating) | PASS. `P3d_N_11m` reproduces R-A's `loyo_rows.jsonl` `P3d_N_fix_brier`: 19,657 of 19,657 rows, identical keys, max abs diff 0.0 |
| C-b (gating) | PASS. Zero-pool identity on h07 with held-out year 2021: 660 rows, max abs diff 0.0 |
| C-d (gating) | PASS. 3,300 of 3,300 extracted market blocks equal L9's `block_sha256` |
| C-d (descriptive) | Pool parse rate is 1.0 in every year and version (V4.0 for 2021-22, V4.1 2023, V4.2 2024, V4.3 2025). Rows dropped for no NBM: 103, all in 2022. Pool mean y−fh at h07 by version: V4.0 −0.14, V4.1 −0.69, V4.2 −0.63, V4.3 −0.82 °F (SD about 2.3-2.6). The 11 markets by year: −0.67, −0.12, −0.21, −0.42, −0.53 |
| C-a | The METAR-path F matches the records (WU) F on 99.6-99.9% of rows, by hour; mean difference ≤ 0.003 °F |
| C-c | The METAR venue label agrees with the WU label on 97.8% of 3,270 market-days; mean difference −0.026 °F |
| D-x (pool, X36) | Per-station in-sample mean(y−fh) at h07: mean −0.48, SD 0.51, p10 −1.04, p90 +0.15 °F; 12.7% of stations lie beyond ±1 °F. Descriptive only |

## Gate statistic: d = Brier(`P3d_N_pool`) − Brier(`P3d_N_11m`), 07-12, mean per row

The base Brier mean is 0.85156, over n = 19,657 rows on 300 dates.

| Quantity | Value | Kill condition |
| --- | --- | --- |
| Point | **−0.00185** | 1: ≥ −0.0005? no |
| Date-clustered 95% CI | [−0.00345, −0.00026] | |
| Block-3 95% CI | [−0.00355, −0.00007] | 2: wider upper ≥ 0? no (−0.00007) |
| Markets CI-worse | **los-angeles** | 3: **yes, KILL** |
| Years with d > 0 | 1 (2021) | 4: more than 1? no |
| Log loss d (reported) | −0.0168 [−0.0336, −0.0035] | |

### Per market

| Market | d | 95% CI |
| --- | --- | --- |
| nyc | −0.0121 | [−0.0174, −0.0071] |
| houston | −0.0083 | [−0.0126, −0.0043] |
| austin | −0.0079 | [−0.0126, −0.0029] |
| chicago | −0.0078 | [−0.0123, −0.0030] |
| denver | −0.0057 | [−0.0117, 0.0001] |
| atlanta | −0.0053 | [−0.0097, −0.0007] |
| miami | −0.0025 | [−0.0084, 0.0034] |
| dallas | −0.0009 | [−0.0064, 0.0050] |
| seattle | +0.0032 | [−0.0015, 0.0079] |
| san-francisco | +0.0051 | [−0.0008, 0.0118] |
| **los-angeles** | **+0.0217** | **[0.0158, 0.0278]** |

### Per year (= per NBM version)

2021 +0.0014; 2022 −0.0011; 2023 −0.0027; 2024 −0.0029; 2025 −0.0041.

### Per hour

h07 −0.0025, h08 −0.0011, h09 −0.0003, h10 −0.0006, h11 −0.0015, h12 −0.0051.

### Dose arm `P3d_N_pool100` (descriptive, never gating)

d = −0.00223, clustered CI [−0.00366, −0.00072], block-3 CI [−0.00380, −0.00051]. Los-angeles is CI-worse here too.

### D-x: mean held-out residual y−ŷ, °F (11m arm → pool arm)

- **los-angeles: −0.09 → −0.43.** Pooling makes the prediction about 0.33 °F too warm, which is consistent with a coastal
  marine-layer station being pulled toward inland stations.
- The other markets move by −0.10 to +0.12: seattle +0.10, nyc +0.12, miami −0.10.

## Deviations and disclosures

- **Survivors: 56.7% vs about 75% projected.** 300 of 529 pool stations fetched survived the frozen F1-F5 filter. S0 had
  projected about 75%. The failures are real F2/F4/F5 cases: no T-group (AWOS-like), about 40-60 specials a day,
  half-hourly patterns, and empty stations. No threshold was relaxed, and the order was not exhausted.
- **Power loss** 2026-11-02 03:36 EST killed the IEM fetch. Audit `C:\t\audit-20261102\AUDIT.md` verified 4,714 of 4,714
  receipted files, and the run resumed in place at KDWA under a coordinator ruling (`run_notes.md`).
- v1 of the fetch script aborted on its first guard check: the RSS probe was mistyped, and nothing was fetched. v2 fixes
  only that.
- The branch-local allowlist entry (@94fdcc47) is not mirrored in the `.codex` hook, as instructed. The admission
  parity tests would therefore fail on this branch.

## Archive

The run is archived under `C:\archive\ruled-out\station-pool-n300\`; the folder's README and `SHA256SUMS` describe it.
The raw IEM files and the NBP blocks file are not copied; they are listed there by sha.
