# Lever inventory: model-improvement levers not yet exhausted (2026-10-25)

> **Dated evidence, 2026-10-25 (filed 2026-10-26); not current state.** Copied unchanged from the coordinator's draft
> (raw sha256 `f92fde4d05a463e823efdfd443a361be3719de5522e6f97c4626a4b8d6cbc034`); only this note was added. Paths under
> `C:\t\` and `C:\swarm\` are workstation-local and not in the repository. Since it was written: master ruled on
> flags F3 and F4 (R9, R10; ESTABLISHED_FINDINGS §10af), and the F1, F5 and F6 corrections are in the
> [exhaustion register](EXHAUSTION_REGISTER.md), ESTABLISHED_FINDINGS §10h and §10s, and RETRACTED_AND_FALSE_LEADS.
> The ranking is the drafter's; master or the owner picks what runs.

Read-only research inventory for the owner's 2026-10-25 "option B" decision ("We exhaust all options on model improvements
and we aren't there yet"). Workstation, no git checkout modified, no heavy job, no outcome/label/price after 2026-09-29 read.
Every number is quoted from the cited record (development / selection evidence unless stated); re-verify before a decision.

Sources read: `AGENTS.md`; `FINDINGS_DIGEST.md` and `ESTABLISHED_FINDINGS.md` / `RETRACTED_AND_FALSE_LEADS.md` on
`origin/claude/docs-head-20261026` (§10af, §10ag) and `origin/claude/docs-head-20261025` (§10y-§10ae);
`EXHAUSTION_REGISTER.md` (byte-identical on `origin/master`, `origin/claude/stack-l11-20261025` and docs-head-20261026;
"S6/S7" read as the register's source rows S6 HRRR single run and S7 HRRR time-lagged, with all of §1-§5 read);
`MODEL_IMPROVEMENT_METHOD.md` (docs-head-20261025); L2 records under `docs/research/l2-pooled-residual-2026-10-24/` on
`origin/claude/rung0712-20261025` (rung0712, rungh, rungi, rungj, p3dn_diag); MG-2 rule on
`origin/claude/mg2-c7-asof-gate-20261025`; `docs/research/morning-loss-diagnosis-2026-10-24.md` (stack-l11, incl. the
10-25 AFD/A1/A2/B addendum); swarm T6/SYNTHESIS (`origin/master`); `C:\t\l12\fetch_plan.md`; `C:\t\l13\hrrr_plan.md`;
STATE_OF_PLAY (docs-head-20261026).

## Where the remaining loss is (the yardstick for every row)

| Block (local) | Best current arm | Excess Brier vs market | Source |
| --- | --- | --- | --- |
| 00-05 | MG-1 (MG-2 serves MG-1 unchanged here) | +0.0102 (1.18x) | EF §10q ladder (111h table, 11 US) |
| 06-09 | MG-1 | +0.0114 (1.20x) | EF §10q |
| 07-12 | L6 (MG-2 pre-13) / P3d_N_fix | +0.0081 [+0.0062, +0.0101] / +0.0101 [+0.0080, +0.0123] | R-H `rungh/rh_summary.md` |
| 13-16 | P3d_N_fix (incumbent P3d_N slightly better) | +0.0083 [+0.0068, +0.0098] | R-H |
| 17-23 | lock-in v3/v4 | not interpretable (market Brier ~0.0008) | EF §10q |

Two facts bound every 07-12 centre lever:
- **Re-centring P3d_N_fix on the market median removes ~25% of its 07-12 excess (+0.0102 -> +0.0077); ~15% for L6.**
  Re-centring and tempering together still leave **+0.0065** (P3d) / +0.0064 (L6) (`rungi/ri_summary.md`, alternative
  reading). So even the market's own centre removes at most ~0.0025 (P3d) / ~0.0012 (L6) Brier at 07-12; about two
  thirds of the 07-12 excess is day-specific sharpness/shape, not centre. Read every "centre" row below against
  that ceiling.
- The dev window cannot confirm small steps: 07-12 MDE80 is about 0.005-0.006 on 11 clusters (EF §10y), versus a 5%
  bar of about 0.0012 at 00-16 (EXREG §1 row 16). Levers of 0.0005-0.002 must be batched (EXREG L14) or read forward.

## Ranked inventory (expected value per cost)

EV = expected reduction of Brier excess vs market on the named block, pooled over the block's markets, with the
evidence behind the guess. "Now" = can start today on the workstation with data already on disk. "Indep." = can run
in parallel with the other rows without sharing a decision or rows (all dev reads still need a DEV_WINDOW_LEDGER row).

| # | Lever | Family | Status (cite) | Expected size vs market (evidence) | Cost | Needs | Now? | Indep.? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Toronto NBM/HRRR guidance: MG-1 on the CYYZ NBP bulletin, then the L6/P3d_N ladder; add ECCC GEM/HRDPS citypage as the native control** | per-city; input/source | **UNTESTED.** Register says "no coverage"/"none for Toronto" (EF §10h; EXREG S1-S7, S13), but the NBP bulletin carries CYYZ (`C:\t\l9\nbm_dl\probe\nbptx_20231117_07.txt` line 90778, "CYYZ NBM V4.1 NBP GUIDANCE"), NBS/NBH carry CYYZ (`C:\t\l12\nbs_nbh\raw\nbs\20210801\nbs.t04z.blocks`), HRRR covers CYYZ (`hrrr_plan.md` §1). Only production's guidance capture is US-only (`official_guidance_collection.py`: NBM is `official_us_guidance`). Toronto has never had a guidance control (EXREG §2). | Toronto rows only: MG-1 closed 40-58% of each US 00-12 block, about -0.014 Brier (EF §10q). A similar Toronto read is about -0.01 on 1/12 of the fleet (about -0.001 fleet-pooled). It also adds the 12th market cluster to every NBM-family read (EF §1d power floor). | Small: NBP CYYZ station blocks by HTTP Range (L9 fetcher, `tools/research/ols_floor_ladder_nbm_fetch.py`) for 2026-08..09 plus 2021-25 07Z/01Z, well under 1 GB, hours. A Toronto dev scorecard (Toronto prices and WU labels exist: L11 Toronto r4 read 08-10..09-29, EF §10ad). | Free NOAA fetch (no ask, owner 10-24); a pre-registration; °C native units (1 °C buckets); Toronto forward needs a CYYZ capture change (production, roll-sensitive) | yes (fetch first) | **yes**: Toronto rows only, never read by a model lane |
| 2 | **Pre-dawn 00-06 block: atlas it, then extend the L6 own-obs stack / P3d_N pooled residual to cutoffs 00-06** | timing; centre model | **UNTESTED.** No lane has worked 00-06 since §10q; MG-2 serves MG-1 unchanged at 00-06 (MG-2 rule §1); R-H covered only 07-16; P3d/arm A predict only from the 07:00 cutoff (EF §10ab scope). | Largest untouched excess (+0.0102 at 00-05, +0.0114 at 06-09). L6 beat MG-1 by -0.0036 at 07-12 (MG-2 rule §6); a similar pre-dawn gain is -0.001 to -0.003. Prior caution: the R-H 07-12 loss is full size at h07, before daytime obs, so the pre-dawn information may be what the market already holds. | Low: captured v2 (01Z/07Z), captured METAR, the existing `upstream_obs_screen` nowcast and L6 a_h/b_h code; one atlas run, then one emit + score. P3d_N needs cutoff 00-06 training rows (01Z PIT NBP: a ~1 GB L9-style fetch). | Rule with sha before rows; ledger row; first the atlas (re-centre on market median at 00-06, as R-H did) to bound it | **yes** (L6 form); P3d_N form after a 01Z fetch | **yes**: disjoint hours |
| 3 | **HRRR 13-16 hourly TMP+TCDC remaining-window path as an input to P3d_N** | input/source; timing | **PARTLY.** Open-Meteo HRRR daily high T8/T9 null (15-16 +0.0024 / +0.0017 over t3-r3; EXREG S6, S7; SYN §1.3). The hourly path is **explicitly excluded** from the R-J trajectory kill (EF §10af). L13 corpus 2021-25 running (`C:\t\l13\hrrr\status.json`: 589/765 days, 34.7 GB). | Target cell: P3d_N_fix loses on cold-path afternoons, +0.0183 [+0.0139, +0.0225], 47% of the 13-16 excess (EF §10ag). If HRRR explains a third of that cell: about -0.001 to -0.0015 at 13-16. Against it: R-G/R-J show the HGB already absorbs observed-path information (EF §10af). | Medium: corpus done in ~2.5 h. **The 2026 dev slice is missing**: L13 refuses dates outside 2021-25 by plan, and the swarm's 2026 HRRR (`C:\swarm\data\hrrr_aws`) is 12Z/18Z f00-f12 only. About 61 days x 29 slots x 2.1 MB = ~4 GB (~40 min). Serve parity needs the forward recorder (plan §8; roll-sensitive, later). | The "separately pre-registered" HRRR rule (R-J text) must be written; the 2026 fetch; grid point = nearest + 3x3 (KSFO: Open-Meteo uses an adjacent point, +4.29 °F bias, `a-hrrr-aws.md`) | rule now; data in ~3 h | **yes** (13-16 only) |
| 4 | **Venue-rule labels (routine METAR only, T-group tenths °C half-up) as training and scoring target; Denver retargeted to KDEN** | label/settlement mechanics | **PARTLY / IN FLIGHT.** EF §10x; SoP critical path item 1; branches `claude/venue-rule-labels-*`. Denver >= 10-23 is "unsupported for model scoring" until a KDEN model passes (SoP). KDEN vs KBKF: 9/61 exact, 38/61 in a different 2 °F band, mean -1.08 °F (`docs/research/denver-kden-vs-kbkf-2026-10-23.md`). | Fleet Brier small: SPECI exclusion flips the 2 °F band on 9 of 671 station-days (1.3%), so about 0.0003-0.0008 pooled. Denver: without a KDEN model one of the 11 forward clusters is lost (worse than any Brier lever for the edge test's power). | Medium: label path code exists on branches; a KDEN model needs KDEN PIT NBP (in the NBP station list) and IEM KDEN history (free). | Owner decisions already made (10-23); the host WU-vs-venue measurement after C | partly (KDEN fetch + LOYO fit now) | yes (label lane) |
| 5 | **Per-market centre bias at 07-12 on L6 and P3d_N_fix (Dallas +0.0173, Austin +0.0159, Seattle +0.0152 vs pooled +0.0101)**, walk-forward on prior dev dates only | per-city; centre model | **PARTLY.** On MG-1, per-market debias (A1, v2+NWS) is KILL/null: -0.0001 [-0.0042, +0.0045] (morning-loss addendum 10-25), Dallas -0.0040 [-0.0103, +0.0023]. A per-hour pooled shift on MG-1 is null (+0.007 dR, EF §10ab intercept twin). Never run on L6 or P3d_N_fix. The R-I kill forbids per-market **width** maps, not centre (rule_ri). EXREG S28/L7 "rolling per-market centre correction NOT TESTED" is stale for MG-1. | Prior is low: at most about -0.0005 to -0.0015 pooled (three markets carry ~1.6x the mean excess; a bias explains part of it at most). Bounded by the 25% re-centring ceiling. | Very low: no data, hours. | Rule + ledger row | **yes** | partly: shares 07-12 rows with any other 07-12 lane; disjoint from 1-3 |
| 6 | **NBS TXN (fresher hourly cycle) as a centre input to P3d_N at 07-12** (TXNSD is a width input; see flag F3) | input/source; timing/freshness | **PARTLY.** T6: NBS latest-cycle zero-parameter read, NBS-specific increment over captured v2 at 00-16 **+0.0003 [-0.0004, +0.0011]**, a precise null (SYN §1.3; EXREG S4 TESTED-NO-INCREMENT). Never inside P3d_N or L6, never per hour at 07-12. L12 corpus running (`C:\t\l12\fetch.log`: 10,350 of 24,480 objects, ETA ~6 h); 2026 dev NBS exists (`C:\swarm\data\nbs\nbs_tidy.parquet`, 07-25..09-29). | Low: T6's c2 control shows TXN carries no information beyond v2_mean at 00-16. Expect <= 0.0005 at 07-12. R-H ranks it top of its family without citing T6 (flag F2). | Low once L12 lands: one P3d_N rung. | Rule; L12 completion | after L12 (~6-12 h) | yes |
| 7 | **NBH hourly TMP path at 13-16 into P3d_N** (the NBM analogue of row 3) | input/source; timing | **PARTLY.** NBH closed beyond MG-1 at **00-16** (EF §10q, +0.0027 [-0.0037, +0.0098]); at 13-16 only vs t3-r3 (+0.0019 [-0.0027, +0.0073]); never vs P3d_N. Corpus: L12 (2021-25) plus swarm 2026 (`C:\swarm\data\nbh`). | Low: about -0.0005 at 13-16; overlaps row 3 on the same cold-path cell. | Low once L12 lands. | Rule | after L12 | partly: same cell as row 3; run as one rule with two arms, or in sequence |
| 8 | **Afternoon stack of P3d_N with the no-source remaining-rise pmf t3-r3 at 13-16** | blend (afternoon) | **UNTESTED.** R-F tested blends only at 07-12 (EF §10af). t3-r3 beat served at 13-16 by -0.0116 and its prereg was SIGNED 10-16 (SoP), but nobody has compared it with, or stacked it on, P3d_N. R-J closes floor features as columns, not a stack. | -0.0005 to -0.001 at 13-16: t3-r3 targets "will a lagging afternoon still reach its high", exactly the R-H cold-path cell, but P3d_N's high_so_far regression already carries part of it. | Low: t3-r3 vectors exist on the workstation (swarm `C:\swarm`), P3d_N vectors exist (`C:\t\l2`). | Rule; walk-forward weight; must use the as-of-capture vectors (C7) | **yes** | yes (13-16; independent of row 3 if read on its own rule) |
| 9 | **Day-specific sharpness information (state-dependent spread from ensemble spread, NBM v2_stddev and its 1 °F floor, multi-model dispersion)** | centre/shape model ("anything else") | **CLOSED BY RULE EXTENSION, NOT BY MEASUREMENT** (flag F3). R-I measured only a per-hour global temperature on dev Aug-Sep and then closed "conditional trigger, per-market map, scale variant" for every NBM-anchored arm (`rungi/rule_ri.md` §PRE-REGISTERED KILL). Dispersion as a signal: blind null (EF §1e, L20 never re-run on the staged corpus). | Potentially the largest remaining 07-12 component (about +0.0065 is left after re-centring and tempering). Prior is weak: conditional reshaping lost to global on its own training score (EF §1g, stratum B only), and the walk-forward temperature did not transfer (R-I). | Low once ruled. | **Owner/coordinator ruling** that a new information input to spread is not "width recalibration" | no (ruling) | yes |
| 10 | **Season gating for the forward (Oct-Dec) season: overnight low, dewpoint** | per-regime; timing (season) | **CLOSED BY RULE ON AUG-SEP DEV ONLY** (flag F4). R-G (07-12) and R-J (all hours) kill trajectory/floor columns on NBM arms on 2026 Aug-Sep dev. LOYO 2021-25 shows the overnight low **helps in Oct-Dec** (-0.028 nats, 11 markets) and dewpoint helps Oct-Dec (-0.014), both harm Aug-Sep (EF §10ac). The forward MG-2/edge-test dates are all Oct-Jan. A season-gated variant is "a lead only, no pre-registration" (coordinator 10-25). | Unknown; LOYO -0.028 nats is about -0.001 to -0.002 Brier at 07-12, in Oct-Dec only. No 2026 dev date can test it (all <= 09-29 are Aug-Sep). | Low code; forward-only evidence, or a LOYO Oct-Dec read. | Owner ruling on the R-G/R-J kill scope; forward read | no (ruling) | yes |
| 11 | **Standard-time / DST alignment audit of training rows for Nov-Dec** (Open-Meteo hourly labels fixed-offset; archive readers +1 h on standard-time dates) | label/settlement; timing | **PARTLY.** EF §10w and §1m (calendar-extension hours shifted 1 h on standard-time dates). Not traced into the P3d_N / L6 / L9 training corpora that the forward Oct-Dec season uses. | Protective: unknown; a 1 h cutoff shift in training mis-states high_so_far at the cutoff on every Nov-Dec training row. | Very low: code and metadata trace, no outcome read. | none | **yes** | yes |
| 12 | **MG-2 binding (C6 bookkeeping, C7 as-of-capture gate) and forward accrual** | conduit for every lever (forward evidence) | **DRAFTED.** Rule DRAFT, `d0: UNSET`, awaiting the single Fable review (mg2 rule header, §8 C6/C7). C7 costs +0.0004 at 13-16 and flips no gate (EF §10ag). | Model vs MG-1, not vs market: dev 13-16 -0.0151 [-0.0192, -0.0113], 00-16 -0.0048 (C7). Against the market P3d_N is still R 1.28 at 13-16 (EF §10ad), so MG-2 alone does not reach parity. | Low now; 45 forward dates. | Fable review, binding commit, §4.3 owner branch | coordinator | yes |
| 13 | **Marine / buoy (NDBC SST, onshore wind) for the coastal residual (Seattle among the worst 07-12 markets)** | input/source; per-city | **UNTESTED** (EXREG S27; live marine dark since 06-13). AFD, the other coastal candidate, is KILL (+0.0012 [+0.0003, +0.0020], morning-loss addendum 10-25). R-H onshore tag null within each coastal market at 07-12. | Low: about 0.3-0.85 °F of centre MAE in SF/SEA/LA/NYC/MIA is unexplained (morning-loss Analysis 5), but no captured tag localises it. <= 0.0005 pooled. | Low-medium: NDBC historical stdmet is free and archived for years. | Rule; serve-time marine capture is dark (production) | yes (fetch) | yes |
| 14 | **Multi-source centre inside L6/P3d_N (NWS grid high, HRRR high, Open-Meteo forecast_high beside NBM)** | centre model; input | **PARTLY.** All tested on the MG-1 family and null: L4 inverse-MSE blend of NBM/GFS/IFS/ICON -0.0002 [-0.0045, +0.0047] (EF §10y); A1 v2+NWS debias null; T18 hrrr_high + forecast_high -0.0005 [-0.0013, +0.0004] (SYN §1.3). The post-hoc 4-source blend reached a centre MAE of 1.48 vs NBM 1.60 (morning-loss Analysis 5) but was never scored as a Brier lever on L6/P3d_N. | <= 0.001 at 07-12, inside the 25% centre ceiling. | Medium: no 2021-25 NWS gridpoint history in the corpora (NDFD archive is free but large), so dev-fit only. | Rule | yes (dev-fit form) | partly (07-12 rows, same as row 5) |
| 15 | **NBM capture-freshness audit at 07-12** (07Z NBP S3 LastModified ranges 07:55-11:43Z, EF §10ac; captured `v2_available_at`) | timing/freshness | **UNTESTED** as a capture property. R-H excess is flat h07-h12, which argues against a large effect. "Fresher NBP cycle" is structurally impossible (13Z/19Z hold no same-day max, EF §10l); fresher NBS/NBH are rows 6-7. | Small: <= 0.0003, on Eastern 07-08 h rows when the 07Z bulletin is late. | Very low: metadata only. | none | **yes** | yes |
| 16 | **Tenths-°C to whole-°F aliasing in MG-1/L6 bucket mapping** (each °F integer is reachable from 5 or 6 METAR tenths, so 2 °F bands get 11 or 12 tenths) | label/settlement mechanics | **PARTLY.** T16 rounding headroom NULL (SYN §1.3). P3d_N already trains on `wu_whole_f_tgroup:half_up` (MG-2 rule §1); MG-1/L6 use a continuous Gaussian on integer buckets. Matters more after the venue switch to T-group METAR (EF §10x). | Very small: about +/-4-5% relative band mass, about 1e-4 to 5e-4 Brier. | Very low. | Rule | yes | yes |
| 17 | **MRMS convective reflectivity at 13-16 as a P3d_N input** (outflow-cooled "cold-path" afternoons) | input/source; per-regime | **PARTLY.** F2 lead -0.0005 [-0.0010, -0.0001], 7/11 over t3-r3, below the 5% bar (EF §10y). Never over P3d_N. 2026 station rows exist (4.14 GB reduced to 32,208 rows); no 2021-25 history. | <= 0.0005 at 13-16. | Medium: dev-fit only unless an MRMS history pull is made (large). | Rule | yes (dev-fit) | partly (same 13-16 cell as rows 3, 7, 8) |
| 18 | **MOS/NBE (IEM) at 13-14 over P3d_N** | input/source | **PARTLY.** t7-r2 13-14 -0.0063 over MG-1 but -0.0031 [-0.0077, +0.0017] over t3-r3 (post-hoc slice; SYN §1.3). Never over P3d_N. Data on the workstation (swarm IEM MOS 2026-05..09). | <= 0.0005. | Low. | Rule | yes | partly (13-16 cell) |
| 19 | **DWD MOSMIX (US and EU stations), forward shadow** | input/source; per-city (°C cities) | **UNTESTED**: not scorable on dev (the open server keeps ~2 days, EF §10y). | Unknown; an independent statistical post-processing chain. | Low bytes (~2.8 MB/day), but 45+ days of forward capture before any read. | Master ruling on who captures (the workstation is not a capture host) | no | yes |
| 20 | **More markets / foreign °C cities (M1 lane: Europe first; MOSMIX, ECMWF ENS)** | per-city; power | **IN FLIGHT** (SoP: R1/R2 recorders, M1 model lane). No served model, no guidance capture yet (EXREG §2, L9). | Not a Brier lever per market. It is the only lever on the 3.2% MDE floor set by market count (EF §1d). | High: capture, labels, 30+ days. | Owner scope (given 10-23); capture | no | yes |
| 21 | **GEFS true member mean** (F4 scored the served "GEFS mean", which is the control run, EF §10s) | input/source | **UNTESTED as labelled** (F4's +0.0054 harm is the control run). | Low: the ECMWF ENS 51-member mean is null (-0.0000, EF §10y). | Low-medium: Open-Meteo ensemble members. | Rule | yes | yes |
| 22 | **AIFS / GraphCast / AIGFS individually** | input/source | **PARTLY.** AIGFS null in F4; F4 says AIFS and GraphCast were never captured, contradicting EXREG S11/S29 "CAPTURED-NOT-SCORED" (flag F5). | Low (IFS and ENS nulls). | Low-medium. | Rule | partly | yes |
| 23 | **Batching sub-MDE steps into one pre-registered package (rows 5, 8, 14-18)** | method | **NEVER USED** (EXREG L14; EF §1d). | Additive only: a package of 4-6 steps of 0.0003-0.001 each could reach the 0.002-0.004 needed for one confirmable read. | Low: a rule. | Coordinator rule | yes | n/a |
| 24 | **T+1 / T+2 markets: a day-2 NBM read against the T+1 book** | anything else (market class) | **NEVER MEASURED** (EXREG §1 row 28, L8). Parser v2 handles target = tomorrow at every cycle (EF §10k). | Unknown. T+1 books are less informed, which may favour guidance. | Medium; 88a data. | Owner (88a development paused, SoP) | no | yes |
| 25 | **Station-vs-grid offset for grid inputs** (diurnally varying offset, e.g. KSFO marine layer; 3x3 block vs nearest point) | input/source mechanics | **PARTLY**, descriptive only (`a-hrrr-aws.md`: Open-Meteo HRRR at KSFO +4.29 °F bias; nearest-point bias -3.9 °F vs METAR). A constant offset is absorbed by the (market, season) bias in P3d_N. | Small; fold into row 3's design (choose point and block by LOYO). | none extra | inside row 3 | with row 3 | — |
| 26 | Mesonets / PWS (S21), WU history re-enable (S22), other venues' prices (S31) | input/source | **UNTESTED**; owner calls (EXREG §5 order 13). F1's 1-minute ASOS harm also killed every paid observation feed (EF §10y). | Low. | Owner. | Owner | no | yes |
| 27 | Served-path-only levers: the remaining no-op stages (L17), 110g re-fit (L19), the `high_so_far` parity repair (L8 lane), the R0 rebuild | served model | Open (EXREG L17, L19; morning-loss addendum; SoP). | Irrelevant to the edge test if MG-2 or its successor replaces the served centre; listed for completeness. | — | — | — | — |
| 28 | **Cool-season P3d_N refit (own pre-registration and freeze; Oct-Dec under R10)** (added 2026-10-26 from master's PT-1 item 6 ruling) | centre model; timing (season) | **UNTESTED.** A new model, not part of MG-2 or PT-1 (PT-1 trades 07-12 on MG-2's pre-13 half, which the refit would not touch). | Unknown; no Oct-Dec selection evidence yet | Medium: fresh rule, LOYO on Oct-Dec 2021-25, freeze | R10 rule; ledger row | No | Yes |

Excluded as closed (not re-proposed): width/temperature recalibration (R-I, EF §1c); trajectory/floor features at 07-12
(R-G) and h13-14 (R-J); dead-bucket (EF §10ad); MG-1 vs L6 blends (R-F); NBH beyond MG-1 at 00-16 (EF §10q); upstream
ASOS (L6 KILL); AFD (KILL); 1-minute ASOS (F1 KILL); soundings mixed-layer cap (F3 KILL); ECMWF ENS mean (G2-a KILL);
B1/B2 corpus GFS linear (KILL); full-year R0 (EF §10z). HRRR 07-12 bulk stays paused: R-H's HRRR-NBM tags do not
localise the 07-12 loss (+0.0105 / +0.0091 / +0.0074), and HRRR is the worst centre to the market (MAE 1.85,
morning-loss Analysis 5).

## Flags: levers the docs treat as closed (or uncovered) that are not

- **F1. Toronto is not uncovered by NBM or HRRR.** "None for Toronto" (EF §10h) and EXREG S1-S7 "no coverage" describe
  production's US-only guidance capture, not the sources. NBP, NBS and NBH all carry CYYZ, and HRRR's CONUS grid
  contains it (evidence in row 1). Every "Toronto has no guidance" statement should be re-worded to "not captured".
- **F2. NBS TXN is booked two ways.** EXREG S4 and the digest's closed-threads table treat NBS as a precise null at
  00-16 (T6 c2). R-H hypothesis 2 ranks NBS TXN as the top 07-12 centre candidate without citing that control. Neither
  is complete: T6 was zero-parameter and pooled 00-16; NBS inside P3d_N at 07-12 is untested (row 6). The prior is low,
  so L12's 16 h fetch should not be read as an expected win.
- **F3. The R-I kill reaches beyond what R-I measured.** R-I measured one family (per-hour temperature, 07-12, Aug-Sep
  dev) and then barred conditional triggers, per-market maps and scale variants on every NBM-anchored arm. That shuts
  out any new spread information (row 9), the component that holds about two thirds of the 07-12 excess. TXNSD,
  ensemble spread and the 1 °F stddev floor in MG-1/L6 are all inside the bar.
- **F4. The R-G/R-J closure rests only on Aug-Sep.** The forward season is Oct-Dec, where LOYO shows the overnight low
  and dewpoint help (EF §10ac). Closed for Aug-Sep dev, untested for the season that will be scored.
- **F5. The exhaustion register is stale in both directions** (it was last rewritten 10-14). Rows now tested but still
  shown NOT TESTED: S12 ICON (L4 KILL), S18 AFD (KILL, on the unlanded stack-l11 branch), S20 1-minute ASOS (F1 KILL),
  S28 rolling per-market correction (A1 KILL, on MG-1). Contradictions: F4 says AIFS and GraphCast were never captured,
  but S11/S29 say CAPTURED-NOT-SCORED. `DATA_LAYER_V2_PLAN.md` (docs-head-20261025, line 155) labels
  "Grids/MOS/AFD/soundings/RTMA" TESTED-UNDERPOWERED/NULL, though RTMA/URMA were never tested (EXREG S32).
- **F6. "GEFS mean harm" (F4, EF §10y) is the GEFS control run** (EF §10s), so the member mean is untested (row 21).
- **F7. Neither running corpus can score the dev window as planned.** L12 and L13 cover 2021-25 only. 2026 NBS/NBH exist
  in `C:\swarm\data` (07-25..09-29); 2026 HRRR there is 12Z/18Z f00-f12 only, so the 13-16 hourly path needs a ~4 GB
  2026-08..09 fetch with the L13 configuration before any dev read.
- **F8. The 00-06 block is open by omission.** No document closes it. MG-2 serves MG-1 there, and no atlas or lane has
  looked at it since EF §10q, although it carries the largest remaining excess (row 2).
- **F9. The NBH closure is 00-16 only** (EF §10q). The user-listed closure "NBH beyond MG-1 at 00-16" is correct as
  scoped; NBH at 13-16 against P3d_N is open (row 7).
- **F10. ETA note:** `C:\t\l12\fetch.log` reports eta_h ~6.1-6.2 at 19:54 local (10,350 of 24,480 objects), not ~12 h.
  L13 is 589 of 765 days at 19:55 local, consistent with ~2.5 h left.

## Start now: five independent levers

Each can start today on the workstation, touches disjoint rows or hours, and needs its rule sha256 and a
DEV_WINDOW_LEDGER row before any scored row. Heavy steps go through `scripts/ops/workstation_heavy.ps1`, and network
fetches stay serial (L12 and L13 are already downloading).

1. **Toronto guidance lane (row 1).** Fetch NBP CYYZ blocks (2026-08..09; 2021-25 07Z/01Z) with the L9 range-read
   fetcher, build a Toronto dev scorecard, then score MG-1-CYYZ against Toronto served and the market, with ECCC
   citypage as the native control. Toronto rows have never been read by a model lane.
2. **Pre-dawn 00-06 (row 2).** Run the R-H-style atlas at 00-06 first (re-centring ceiling, winner-bucket mass), then
   an L6 own-obs stack at cutoffs 00-06 on captured v2 and METAR. No fetch is needed for the L6 form.
3. **HRRR 13-16 path (row 3).** Write the separately pre-registered HRRR rule now. Queue the 2026-08..09 dev-slice
   fetch for when L13 finishes (~2.5 h), then add the path to P3d_N on the as-of-capture vectors.
4. **Per-market centre bias on L6/P3d_N at 07-12 (row 5).** Walk-forward, prior dates only, no data needed. The
   prior is low, but it is the cheapest test of R-H hypothesis 4, and the R-I kill does not cover a centre bias.
5. **Standard-time alignment audit (row 11).** A code and metadata trace of the P3d_N, L6 and L9 training rows for
   Nov-Dec. It protects the forward season and reads no outcome.

Rows 9 (spread information) and 10 (Oct-Dec season gating) are the two biggest potential levers, but both need an
owner or coordinator ruling on the scope of the R-I and R-G/R-J kills first. Raise that ruling in parallel.
