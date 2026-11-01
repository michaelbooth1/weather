# S31 P0 Clarification 1 (2026-10-31): final ledger row 99, sigma_d, MDE and power

Status: clarification to `rule_s31_p0.md` (DRAFT, sha256
`d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e`, under master's review). The rule file is
not edited, so that sha stays the reviewed one; this file amends it. Lane L14, outcome-free: no venue price
and no outcome was read to write it.

## 1. Ledger row

The P0's final ledger row is **99**, not 93. It was drafted as 93 (`18fd48ac9`); L15 renumbered it at assembly
because L17's 93 was pushed first. Every reference in `rule_s31_p0.md` to "row 93" means row 99. On this branch
`docs/operations/DEV_WINDOW_LEDGER.md` is aligned to `origin/master`, which carries row 99. Row 99's "sha256
pending" rule cell resolves to the rule sha above, plus this clarification's sha, which the commit records.

## 2. Planning sigma_d (master accepted it as the planning value)

- Source: ledger row 78 (rule_mr_sweep `85f8192c`) on dev dates, through its per-date rows for the OM-HRRR
  candidate.
  - Receipt `mr_sweep.json` has sha256 `02c4663097797be5a8ad2d18380486a2a95cffc5da4593f9e0e645553e93aac2`.
  - Rows `mr_sweep_rows.jsonl` has sha256 `c1bfe4056b486e8b1f3defb0a692bb38fc3544a03bb87c6c05d27cd08eb25b73`.
- Statistic: d_t = rho_c,t − mean_j rho_pl,j,t per date. N = 43 dates, mean d = 0.00634.
- Pooled sigma_d = 0.07569. Row 78's rows pool all 11 markets and have no per-market rows. The KAL arms use 7
  cities, so sigma_d is inflated by sqrt(11/7) = 1.2536, giving **sigma_d(KAL) = 0.09488**. This assumes
  per-date variance scales as 1/markets. It is disclosed as an approximation.
- Serial dependence: lag-1 rho = 0.2719 and the block-3 ratio = 1.1255. The block-3 moving-block bootstrap uses
  10,000 draws with seed 20261024. VIF = max(1, (1+rho)/(1−rho), ratio²) = 1.7470.

## 3. (f) power gate fields (fills rule §7(d) and §7(f))

| field | value |
| --- | --- |
| sigma_d | 0.09488 (row 78 per-date OM-HRRR, sqrt(11/7) KAL inflation; file shas in §2) |
| rho | 0.2719 |
| VIF | 1.7470 |
| N | 43 scored dates (08-15..09-29 dates with row-78 rows; the KAL arms' realised N is reported at run) |
| SE | 0.01912 |
| MDE80 = 2.802·sigma_d·sqrt(VIF)/sqrt(N) | **0.0536** |
| delta (planning effect) | 0.04 |
| power at delta (normal, two-sided 0.05) | **0.55**, so it clears power ≥ 0.5 |
| class | **SCREEN**: delta 0.04 < MDE80 0.0536 |
| N80 | 78 dates |
| intervals on planning d (pooled 11, 95%) | date-clustered [−0.0163, +0.0290]; block-3 [−0.0191, +0.0318] |

Power at smaller effects is 0.075, 0.120, 0.180, 0.257 and 0.348 for delta = 0.01, 0.015, 0.02, 0.025 and 0.03.
Power first reaches 0.5 near delta = 0.0375.

**Consequence.** On the accepted planning value, this P0 is a SCREEN. A pass is a screen signal, not a powered
kill-or-keep. A null result kills the S31 KAL arms only for effects of about 0.054 or more. FEX-MEAN inherits
the same planning value; its realised N, and therefore its power, is reported at run and can only be lower.

## 4. Sensitivity (not the plan value; master's choice)

Row 78's own pooled bootstrap gives OM-HRRR Δ = −0.002244 with a 95% interval of [−0.011612, +0.007532]. That
implies a pooled SE of about 0.00488, an effective sigma of about 0.0320, and about 0.0401 after KAL inflation.
On that basis, SE is about 0.00809 and MDE80 about 0.0227, so power is about 0.70 at delta = 0.02 and above
0.99 at delta = 0.04, and the class at delta = 0.04 would be POWERED. The two bases differ because the
per-date d_t variance counts within-date rho noise that the sweep's pooled-sums estimator averages over
markets. The plan uses the more conservative per-date value, as master accepted.

## 5. Finding disclosed while computing this (not an S31 result)

In row 78, OM-GFS and OM-HRRR are identical on all 43 dates, with identical per-date sums. In the features
table, `mm_gfs_seamless == mm_ncep_hrrr_conus` on 110,692 of 110,692 rows. Either Open-Meteo `gfs_seamless`
serves HRRR over CONUS or there is a capture defect. Either way, row 78's K counts one signal twice. S31 does
not use either column; this is reported to master for the owning lane.

## 6. Provenance (R13 archive, never cleaned)

All three files are in `C:\archive\ruled-out\_s31-intake\clarification1\`. The scratch originals stay outside
the archive root.

| file | sha256 |
| --- | --- |
| `s31_power_plan.py` | `8f779f7139a189600c4520dba0dd562b3558cf205abd42adc7d162f4843c5fda` |
| `s31_power_plan_out.json` | `a7a2bfe35f3be0ca74629b36e99f4b5682869782d50d8b585cb581da529dcbeb` |
| `s31_clar1_numbers.py` (delta, N80, intervals, sensitivity) | `0da632eaee3ddcd9955784a67209618b16302007f1b839c35b3092f20715143e` |

## 7. Fetch module

The module that rule §6 calls `weather.research.s31_venue_fetch` lives at
`weather.sources.free_screens.s31_venue_fetch`. There is no `weather.research` package, and `weather.sources`
owns provider fetches (`src/weather/AGENTS.md`). Its contract is rule §6 plus master's 2026-10-31 conditions:

- dev windows end no later than the local end of 09-29;
- late items are dropped unparsed and recorded;
- R13 raw archive;
- no auth;
- allowlists A, B and C;
- at most 1 request per second;
- writes only under `--out`.

Nothing is fetched until master has reviewed the module.
