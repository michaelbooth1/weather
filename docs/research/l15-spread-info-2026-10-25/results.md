# L15 rung R-S results: NBM TXNSD spread information on P3d_N_fix (KILLED at gate 2)

Pre-registered rule: `rule_rs.md` (sha256 `70908316df5066fe5d000fa8d84d0ec2b1f384285a1d3f68b311b9d24cf93ff9`,
committed at 8f80ea821 before any row was joined to an outcome). Plan: `plan.md`
(sha256 `523d334e65e6a7af335ec2f98734a26e6368d33654816a4f198f9014fac00483`).
Module `weather.calibration.spread_information_rung` (sha256 `e32809f4…`), run through
`workstation_heavy.ps1` on the 32 GB workstation. Outputs live outside the repository under `C:\t\l15\`.

## Verdict

**KILL.** Gate 1 (training LOYO, 07-12) passed. Gate 2 (dev 07-12 vs the unmodulated arm) failed: the
date-clustered dR is a null. Per the rule, the NBM-published-spread family is closed: NBP TXNSD, NBP p90-p10
and NBS XND/TSD as a P3d_N_fix scale modulator. The 13-16 secondary LOYO also failed. Gate 3 (vs L6) was not
reached.

## Gate 1: nested LOYO 2021-25, 07-12 (S minus unmodulated, Brier; negative is better)

The R-A beta=0 control reproduced the R-A LOYO rows exactly (19,657 rows, max abs diff 0.0).
Bootstrap: 2000 draws, seed 20261024.

| hour | dBrier | 95% CI | dLog | frozen dev beta |
| --- | --- | --- | --- | --- |
| h07 | -0.00137 | [-0.00217, -0.00057] | -0.00928 | 0.45 |
| h08 | -0.00089 | [-0.00164, -0.00004] | -0.00693 | 0.40 |
| h09 | -0.00093 | [-0.00158, -0.00025] | -0.00952 | 0.35 |
| h10 | -0.00097 | [-0.00174, -0.00016] | -0.00710 | 0.35 |
| h11 | -0.00082 | [-0.00182, +0.00033] | -0.00684 | 0.35 |
| h12 | -0.00097 | [-0.00182, -0.00009] | -0.00621 | 0.35 |
| pooled | -0.00099 | [-0.00171, -0.00026] | -0.00765 | |

Training modulation is mean-zero (pooled mean m +0.0002). Result file sha256 `d6dc1d66…`.

## Gate 2: dev 2026-08-15..09-29, 07-12, S vs unmodulated (dR, date-clustered; negative is better)

The control file `dev_P3d_N_fix.jsonl` is byte-identical to the pre-registered `cd0034b9…`. Mass is
preserved, and below-floor mass changed by at most 1.4e-17. On dev the modulation is mean m -0.0064 and
mean |m| 0.103 (the flag is false). There are 21,664 common snapshots, 473 market-days and 43 dates.
Seed 20260921.

| group | dR | 95% CI |
| --- | --- | --- |
| h07 | +0.00302 | [-0.00588, +0.01184] |
| h08 | +0.00405 | [-0.00357, +0.01146] |
| h09 | -0.00019 | [-0.00720, +0.00638] |
| h10 | +0.00094 | [-0.00604, +0.00755] |
| h11 | -0.00175 | [-0.01013, +0.00696] |
| h12 | -0.00012 | [-0.00881, +0.00808] |
| 07-12 | **+0.00067** | **[-0.00604, +0.00722]** (FAIL: the upper bound is not below 0) |

Per market, only San Francisco has a CI that excludes zero (-0.0164 [-0.0331, -0.0024]). The other eleven
markets are nulls of mixed sign. Selection evidence only: excess vs market is P3d_N_fix 0.01022, S 0.01026
and L6 0.00814 (MG-1 control 0.01196). Score file sha256 `c3e8f0b2…`.

## Secondary: 13-16 LOYO (fails, so no dev run)

| hour | dBrier | 95% CI |
| --- | --- | --- |
| h13 | -0.00080 | [-0.00164, +0.00006] |
| h14 | -0.00042 | [-0.00110, +0.00030] |
| h15 | +0.00003 | [-0.00022, +0.00030] |
| h16 | +0.00028 | [-0.00021, +0.00077] |
| pooled | -0.00023 | [-0.00060, +0.00017] |

## Reading

- A small training-period gain of about 0.001 Brier did not transfer to 2026 dev.
- One plausible cause is that dev carries NBM v5.0. Its TXNSD distribution is compressed (25% of values are
  1), and the trailing anomaly only partly normalises it.
- This does not explain the L6-vs-P3d_N_fix gap (+0.039 dR in L6's favour). Published NBM spread, used as a
  modulator on the HGB scale, adds nothing measurable on dev.
- The next spread rung needs information that is not a re-expression of the NBM published spread. Per the
  plan, that is GEFS member spread (P4). It should be pre-registered with a 00-06 variant alongside 07-12.
