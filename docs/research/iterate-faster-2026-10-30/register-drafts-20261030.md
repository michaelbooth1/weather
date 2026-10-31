# Register drafts, 2026-10-30 (L3): ready-to-paste text for master's review

> **Draft, not canonical.** Nothing here has been applied to `EXHAUSTION_REGISTER.md`, `LEVER_INVENTORY_2026-10-26.md`,
> `ESTABLISHED_FINDINGS.md` or `FINDINGS_DIGEST.md`. Master reviews and lands it. Verdicts and numbers are copied
> from the pushed ledger notes on `claude/successor-batch-20261030` @ `7e1531f7e37c0b9856d877d14a8bcc12cd3d35ac`
> (rows 85-91 are not yet on `master`). Receipt hashes are the sha256 of the local receipt files and match the
> hashes in those notes. Reopen cells marked *(drafted)* are L3's wording where the row's rule carries no written
> kill line. Master confirms or replaces them.

Base: `origin/master` @ `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`. Format follows X54 in
`99be9e8136aac12bb0b6f938d0d6f5a46731b438`.

**Numbering.** `master` ends at X43. X44-X62 are on `99be9e81…`. X63-X70 are on
`claude/docs-owner-20261030` @ `e759a55d10e31dd48559ef99b9d2959c41271fd3`, which `claude/docs-sop-20261030b` and
`claude/ws-docs-batch-20261030` also carry. The lines below take X71-X81 on the assumption that those branches
land first. Renumber if the landing order differs.

**Shared constants.**

- Market-residual statistic: rule `rule_mr_sweep.md` sha256
  `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`. It uses the calibration-matched paired
  Δ = ρ_c − ρ_pl over 20 derangements and 10,000 date-cluster draws (seed 20261024). Each row uses BH q = 0.10
  over its own K.
- All the P0 runs ran from a clean tree, without `--allow-dirty`, as one `workstation_heavy -Queue` run each.

## 1. EXHAUSTION_REGISTER §6 lines

| # | Ruled out | Numbers [95% CI] | Window / N | Conditions (arm, inputs, dating, rule) | Verdict | Reopen if | Record |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X71 | C1 (successor batch): R-ODC `low_so_far` + `t_minus_low` added to the season-matched L6 OWN HGB at 07-12 | arm − SM-L6 incumbent ΔBrier −0.0000426 [−0.000312, +0.000215]; 2022 CI-worse [+0.000086, +0.000918]; Spearman ρ(t_minus_low, RATE-0712) 0.887 ≥ 0.80 (redundant); control reproduces SM-L6 LOYO −0.0052457 exactly | history LOYO Oct-Dec 2021-25, 07-12, 375 dates (not a dev read) | MG-2 l6_stack frozen coefficients; inputs IEM METAR `obs.parquet` and the NBM text PIT corpus, no Open-Meteo-derived reader (§10w met by construction); proposal §2 C1 sha256 `ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458`; code `claude/successor-c1-run-20261030` @ `105f1696b7f0130e9f5bd472fba456034eac12e4`, module sha256 `efcbc0b6e7b1246cc718e9ede53cb8ae85b92a07fca5fd5c7fbe19ad963ef59b` (key-dtype fix after a pre-output crash at `ece13f3d905ec42036a36024591115e001916aa0`); receipt `C:\t\l3succ\c1\c1.json` `c881a5bba59c36f6dd409b055910ee2ba83a36833735ca679bd8475c053dbe14`; `c1_result.md` `1c5ca61c633e08a27795ff6deac4ad895d472806b6d915e7b30a0a932e2aef78` | DROP (null; redundant with RATE-0712, row 81) | *(drafted)* an overnight-low construct with \|ρ\| < 0.80 against RATE-0712 and a stated cool-season mechanism, under a new rule | ledger row 85 |
| X72 | C2 (successor batch): R-PD (L6 own-obs HGB stacked on NBM) at 00-06 in Oct-Dec | dB +0.003318 [+0.000363, +0.006119] (arm worse than the MG-1 analogue); 2023 (v4.1) +0.009241 [+0.002407, +0.016086]; only h00 improves −0.00478 [−0.00765, −0.00187], h02-h06 CI > 0; positive control reproduced gate 1 exactly (−0.004722492619806772) | history LOYO Oct-Dec 2021-25, 00-06, 460 dates, 35,036 rows (not a dev read) | predawn_0006 gate-1 loop unchanged with LOYO_MONTHS (10, 11, 12); proposal §2 C2 sha256 `ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458`; code `claude/successor-c2-run-20261030` @ `73ee618f14880fb8e50071f16f58ebcbc29aade4`, module sha256 `e246ea350d9909ed8652af003d3b006471cb9dcbab082999b74a9bbba4351695`; receipt `C:\t\l3succ\c2\c2.json` `cf9300dbf6a16de33a48cd145a2fd7b75d3d611f76474cbbad9bf1b323709182` | DROP (harm; the Aug-Sep R-PD gain, X31, does not carry to Oct-Dec) | *(drafted)* a stated mechanism for an Oct-Dec own-obs gain beyond h00, under a new rule; the Aug-Sep gain is not a reopen reason | ledger row 86 |
| X73 | Marine `MAR-SST` (CO-OPS / NDBC water temperature, sign +) against the MARKET at 07-12 | obs+90 Δ −0.0817 [−0.1508, −0.0105]; p 0.987; BH q 0.987; rho_c −0.0791 vs placebo +0.0026; obs+180 −0.0825 [−0.1519, −0.0121]; houston −0.256 (CI below 0) | dev 07-12, 43 dates, 11,783 snapshots; sf/sea/la/nyc/mia/hou | type D, K = 2 at obs+90 (primary) and obs+180 (sensitivity); rule `rule_marine_p0.md` sha256 `a374f771612e6b0e2b9f392db6a1688a23a2296a4cc2b5cdc98aaa42bb37c230`; code `claude/marine-p0-run-20261030` @ `93e382ae26e8dbd7a7a5bed9dcfaf2cc16bbc121`, module sha256 `845de35a92aaa58effceb741a6984917d839206a8b094cf95aa06f7423d26037`; receipt `C:\t\l3marine\p0\marine_p0.json` `3c6f0542e1c59f8d10148817e43659cc321f7f2c15d39a6db398ce7112cd59ee`; served, MG-1 and w = 0 controls PASS | KILL (wrong-signed; a reversed sign is not a survivor and is not re-tested) | *(drafted)* a new marine construct with the mechanism written first, on dates disjoint from dev | ledger row 87 |
| X74 | Marine `MAR-ONSHORE` (onshore wind component, sign −) against the MARKET at 07-12 | obs+90 Δ −0.0391 [−0.0852, +0.0081]; p 0.953; BH q 0.987; obs+180 −0.0449 [−0.0935, +0.0055]; no market CI above 0 | as X73 | as X73 | KILL (null, wrong-signed) | as X73 | ledger row 87 |
| X75 | R-Q B: captured GEFS member-high spread `GEFS-SPREAD80` (`day_member_high_spread_80`, type S, sign +) against the MARKET at 00-06 | Δ +0.0004 [−0.0223, +0.0224]; p 0.501; BH q 0.501; rho_c −0.0021 vs placebo −0.0025; denver −0.102 [−0.226, −0.003] | dev 00-06, 43 dates, 23,668 snapshots, 11 markets | captured replay inputs (replay-inputs-le0929); K = 1 (own arm); rule `rule_rqb_spread_p0.md` sha256 `844c2eb516da7dcff92ba25a150e8b12a1c7ead47289aaa8ed066e82357415d3`; code `claude/rqb-spread-p0-run-20261030` @ `c46408d3bbaaea3dc8bbd3c7b9ef0244b03ae04e`, module sha256 `ae9d2bf36f60561f9521e463f908525bedd6c8bfb105c720535e9949de9304e9`, `mr_gate.py` `7cabd012f1dff6e28b6eddb566e60b2589d3afe0c064f0fefab9d25b6c18dfc4`; receipt `C:\t\l3rqb\p0\rqb_spread_p0.json` `6728bedc9e9450b004fdb8c1d4086bff4b172376bb4f078963e6b0596e790acf`; controls PASS | KILL (null vs the market; the ap5 recorder question is not earned) | *(drafted)* a different captured GEFS-spread construct or hour block with a stated reason the market lacks it, under a new rule | ledger row 88 |
| X76 | IEM MOS `MOS-GFS` (MAV n_x, type C) against the MARKET at 07-12 | Δ +0.0039 [−0.0507, +0.0623]; p 0.456; BH q 0.456; rho_c +0.0078 vs placebo +0.0038; +1 h sensitivity identical in verdict | dev 07-12, 43 dates, 21,695 snapshots, 11 markets | A-IEM-2 IEM MOS archive (forecast-only); availability modelled, not a capture receipt; K = 2; rule `rule_mos_p0.md` sha256 `952cfc52968e8d7dee8be685ecbf71f14bfccc1a6e8cd28d149bd0a58112ebc2`, amendment 1 `eafbfca4b3ab3b9e1ded9378bdcade6ceb20183bb54d58c3632dca7579c01f2e`; code `claude/mos-p0-run-20261030` @ `4136df139765c2411ef2574953815ca1734f697c`, module sha256 `5899c3b8c6e0a1835b46f5f303d83ea491e7c6ba88882bd4dad1af9c2a6e5873`; receipt `C:\t\l3mos\p0\mos_p0.json` `c4528812b3402b63410342161c2584f9ba9808534c0c245927693cfdcfd0ebcb`; controls PASS | KILL (null vs the market; the MOS-against-the-market family is CLOSED on dev) | a captured MOS feed (the IEM MOS forward recorder) plus a new rule on dates disjoint from dev | ledger row 89 |
| X77 | IEM MOS `MOS-NAM` (MET n_x, type C) against the MARKET at 07-12 | Δ +0.0378 [−0.0070, +0.0822]; p 0.0486; BH q 0.097 (BH-rejected) but the pre-declared Δ lower bound is below 0, so it fails survival; rho_c +0.0458 vs placebo +0.0079; atlanta +0.267 [+0.100, +0.425], houston +0.246 [+0.051, +0.441] (report-only) | as X76 | as X76; +1 h sensitivity identical (no NAM run changes) | KILL (near miss; not rescued; no w gate) | Reopen if a mechanism specific to NAM-MOS (it worked where GFS-MOS was null) is written first and a forward test passes the (f) power gate at half the dev effect. | ledger row 89 |
| X78 | MRMS `MRMS-MAXDBZ25` (max(max_dbz_25km, 0), within-market z clipped to ±3, type D sign −) against the MARKET at 13-16 | Δ +0.0165 [−0.0252, +0.0561]; p 0.227; BH q 0.227; rho_c +0.0063 vs placebo −0.0102; unclipped (descriptive) +0.0149 [−0.0245, +0.0544]; 50 km (descriptive) +0.0039 | dev 13-16, 43 dates, 13,984 snapshots, 11 markets; no zero-tilt markets | NOAA MRMS composite reflectivity station table `station_refl.parquet` `3446d1a6d134b6059b4ca7d1e3694bc7cc3a033bae6a65ba73850c49acee97be`, F2 join (valid + 5 min ≤ capture, age ≤ 40 min); K = 2; serve parity NONE; rule `rule_mrms_p0.md` sha256 `b0f170a5a69b93c040d3b7092e5c3f2ce2eb9a626978ad77f2b2f69e02fa091e`, amendment 1 (clip, synthetic sign control) `cb30891fbee3800e78c01c63e2036453d24e741619300cc626748e3881e51711`; code `claude/mrms-p0-run-20261030` @ `a9ba4d12b7d561db6696b4e6ead705d775811fbd`, module sha256 `167dfc5b0151e3c878718400163e2c73b2e00524c3020f8b0a9f1e4f6ab33b4f`; receipt `C:\t\l3mrms\p0\mrms_p0.json` `507395ec694a4cd6bbf9921a9d9f303704c2fbbef47a38068382868a155272e0`; served, MG-1, w = 0 and synthetic sign controls PASS (pos +0.515 [+0.480, +0.550], neg −0.360 [−0.430, −0.291]) | KILL (null vs the market) | a new construct needing a re-fetch, under a new rule with the mechanism written first; a survivor earns only the owner question on the held capture change (via master) | ledger row 91 |
| X79 | MRMS `MRMS-ECHO35` (1[max_dbz_25km ≥ 35], F2's construct; clipped z, type D sign −) against the MARKET at 13-16 | Δ +0.0170 [−0.0182, +0.0514]; p 0.181; BH q 0.227; rho_c +0.0082 vs placebo −0.0087; unclipped (descriptive) +0.0226 [−0.0179, +0.0607]; 50 km (descriptive) +0.0023 | as X78 | as X78 | KILL (null vs the market; with X78 closes MRMS against the market at 13-16 for echo max and flag at 25 km; X7's against-the-model lead is unaffected) | as X78 | ledger row 91 |
| X80 | Toronto `GEM-SEAMLESS` (captured Open-Meteo `eccc_gem.day_model_highs.gem_seamless`, type C) against the MARKET at 07-12 | Δ −0.1278 [−0.2790, +0.0359]; p 0.942; BH q 0.942; rho_c −0.1724 [−0.3247, −0.0085] vs placebo −0.0446 | Toronto dev 07-12, 46 scored dates, 2,213 score snapshots; WU labels, native °C | K = 2; rule `rule_toronto_eccc_p0.md` sha256 `b8718b46d0244054be26834a0a35d28f0ff2ed45d8056e0393334ce5df4b0b0d`, controls-only amendment 1 `40b90e72d14285900c883b0b66d7136da87781f3b758e0807785d639acf71141`; code `claude/toronto-eccc-p0-run-20261030` @ `c57a080c5da4e9fc576317e7014384f16634aeb1`, module sha256 `63221f6f00ee5a0af31e2eb426458baf1819a03c1a1cbf90afe0e292c8bbf5e4`; receipt `C:\t\l8tor\eccc_p0\toronto_eccc_p0.json` `07de0b0dbfe9fbba1ed9dd83198d05014b5f7702b40360c2a159e45ca09e95ce`; controls (amendment 1 result, ledger commit `63669344920aca41135d8bac28ac83dea83dfeaa`, code @ `ad6d71af6cd7176c68d58edd5a88508238a167c2`, module sha256 `65acdba9da8989db17690056fef5668bf070580c9ced5c9bec4d479279613fa3`; receipt `C:\t\l8tor\eccc_ctrl\toronto_eccc_p0_controls.json` `a7192707f9ac582885522d0e4dc1020ee3e0079ad13f680fa83b3839e696d49a`): w = 0 identity PASS, row 77 reproduction PASS (max |diff| 0.0), synthetic SYN+ SURVIVE +0.3909 [+0.3165, +0.4648], SYN- −0.2758 [−0.3598, −0.1940] | KILL (null vs the market; GEM's negative ρ is descriptive) | a new rule on dates disjoint from 2026-08-01..09-29; Datamart HRDPS/RDPS stay BLOCKED on the recorder, not killed | ledger row 90 and its amendment 1 result |
| X81 | Toronto `CITYPAGE-FH` (captured ECCC citypage `forecast_high_native`, type C; already a served consensus vote) against the MARKET at 07-12 | Δ −0.0733 [−0.2450, +0.1030]; p 0.792; BH q 0.942; rho_c −0.1185 vs placebo −0.0452 | as X80 | as X80 | KILL (null vs the market) | as X80 | ledger row 90 and its amendment 1 result |

Row 90 is final (master deconflict, 2026-10-30): the controls-only amendment passed and the KILL stands.

**X5 (existing line; rows are never deleted).** Replace the Reopen cell
`ENS spread as spread information (R9 family)` with:

> COVERED at family level (2026-10-30): spread information against the market is closed by row 88 (X75, captured
> GEFS member spread at 00-06) and X54/X55 (`OM-MM-SPREAD`, `OM-GM-SPREAD`, multi-model dispersion, all hours,
> rule `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`, receipt
> `C:\t\l3\mr\sweep1\mr_sweep.json` `02c4663097797be5a8ad2d18380486a2a95cffc5da4593f9e0e645553e93aac2`); ECMWF ENS
> member spread itself was never scored, so reopen only with a stated reason it differs from those, under a new rule

Also change the Verdict cell to `KILL (null); reopen COVERED (row 88, X54, X55)`.

## 2. LEVER_INVENTORY_2026-10-26 fixes

The inventory is dated evidence. These go in as **status-cell replacements plus one dated correction note** under
the header note. No other cell changes.

- **Row 9** (day-specific sharpness information). Status cell becomes:
  **KILLED (X54/X55)** for multi-model dispersion against the market (`OM-MM-SPREAD` +0.0004 [−0.0017, +0.0021],
  `OM-GM-SPREAD` +0.0011 [−0.0015, +0.0030], ledger row 78), with GEFS member spread killed at 00-06 by row 88 (X75)
  and NBM-published spread as a scale modulator by R-S (X37). The earlier "closed by rule extension, not by
  measurement" text stays below as history.
- **Row 17** (MRMS). Correction: "no 2021-25 history" is wrong. The station table `3446d1a6…` carries Aug-Sep 2024
  and 2025 plus 2026-07-31..09-29 (ledger row 91 correction). Status cell becomes:
  **KILLED against the market at 13-16 (row 91; X78/X79)**. F2's against-the-model lead (X7) is unchanged.
- **Row 18** (MOS/NBE). Status cell becomes: **KILLED (row 89; X76/X77)**. The MOS-against-the-market family is
  closed on dev at 07-12, and MOS-NAM's near miss carries master's reopen line (X77). X42 (h13-15 SM-H input)
  already closed the 13-15 cell.
- **Row 1b** (row 1's second clause, "ECCC GEM/HRDPS citypage as the native control"; the inventory has no
  literal 1b label). Status for that clause becomes: **KILLED (row 90; X80/X81)**. Production's
  captured Open-Meteo GEM and ECCC citypage are null against the Toronto market on dev (controls amendment
  passed, `63669344920aca41135d8bac28ac83dea83dfeaa`). Datamart HRDPS/RDPS stay BLOCKED on the recorder. The NBM part of row 1 is X64/X65.
- **X51 / row 22** (AIFS / GraphCast / AIGFS). Status cell becomes: **BLOCKED (UNTESTABLE)** for GraphCast (X51)
  and AIFS (X50): the captured value is null in every record (ledger row 78). This resolves flag F5 in F4's
  favour for the dev window. It is not a kill and reopens when the capture defect is fixed (L2) and forward values
  accrue. AIGFS stays null (X52).

## 3. ESTABLISHED_FINDINGS notes

Append to the R-S paragraph (line 4614 on `1a78e1ba0…`, after "...observed-state predictors are not covered."):

> *Note (2026-10-30):* "multi-model dispersion is not covered" was true for the scale-modulator form R-S tested.
> The market-residual form is now covered: X54/X55 (`OM-MM-SPREAD`, `OM-GM-SPREAD`; ledger row 78, rule
> `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`) are null against the market at all hours, and
> GEFS member spread is null against the market at 00-06 (row 88, X75).

Append to the R-Q "Not claimed" bullet (line 4687 on `1a78e1ba0…`):

> *Note (2026-10-30):* the exclusion of multi-model dispersion holds for R-Q's scale-modulator form only. X54/X55
> now cover multi-model dispersion as a market residual (null), and row 88 (X75) covers R-Q B's captured GEFS
> spread as a market residual at 00-06 (null).

## 4. FINDINGS_DIGEST line ("Closed threads" table)

| Thread | One-line reason | Pointer |
| --- | --- | --- |
| Free-data market-residual batch, 2026-10-30 (marine, GEFS spread 00-06, IEM MOS 07-12, MRMS 13-16; Toronto GEM/citypage) and the successor LOYO batch (C1, C2) | Every candidate null or wrong-signed against the market (best: MOS-NAM Δ +0.0378 [−0.0070, +0.0822], fails the lower bound); C1 and C2 DROP on Oct-Dec 2021-25 history | register §6 X71-X81; ledger rows 85-91 |

## 5. Standing rule (master's ruling, 2026-10-30)

Master, adding the synthetic sign control to row 91's amendment, said:
"This is now a standing rule for any P0 using a newly built table or a new tilt form."

The coordinator's restatement of the rule, for the "Evaluation and statistics rules that bind every claim" section
of the digest and for the market-residual method:

> Any P0 on a newly ported or built table carries, in its first run, the w = 0 identity, the served/MG-1
> reproduction, and a synthetic positive/negative sign control: a candidate built from the realised market residual
> plus Gaussian noise (SD = that residual's σ, seed pre-declared), oriented to PASS with Δ > 0 under the declared
> type and sign, and its negation, which must read Δ < 0. If either synthetic fails, the run is VOID: fix, disclose,
> and re-run once under the same rule, with the fix diff to master first.

First applications: row 91 amendment 1 (`cb30891fbee3800e78c01c63e2036453d24e741619300cc626748e3881e51711`; both
synthetic controls PASS) and row 90 amendment 1 (`40b90e72d14285900c883b0b66d7136da87781f3b758e0807785d639acf71141`;
all controls PASS, receipt `a7192707f9ac582885522d0e4dc1020ee3e0079ad13f680fa83b3839e696d49a`).
