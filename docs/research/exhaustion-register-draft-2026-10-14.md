# Exhaustion register — draft for the owner (2026-10-14)

Status: DRAFT, read-only audit of the canonical docs. Nothing here is a measurement; every number is quoted from
the owning section and cited. The owner keeps the no-go call. "EF" = `docs/operations/ESTABLISHED_FINDINGS.md`,
"RF" = `docs/operations/RETRACTED_AND_FALSE_LEADS.md`, "FD" = `docs/operations/FINDINGS_DIGEST.md`,
"OQ" = `docs/operations/OPEN_QUESTIONS.md`, "FP" = `docs/operations/forward-plan-2026-09-23.md`,
"SOP" = `docs/operations/STATE_OF_PLAY.md`, "DL" = `docs/operations/DECISION_LOG.md`,
"SYN" = `docs/research/model-parity-swarm-2026-10-04/SYNTHESIS.md`.

Question being answered: *what must still be exhausted before we can say, as nearly as possible, that we cannot
match or beat the market from free information?* Two owner challenges drive it: (1) do the recent serving-bug fixes
taint the earlier "model does not beat the market" tests; (2) have we really exhausted free data sources.

---

## 0. Corrections to the brief, and the defect timeline the whole register depends on

### 0.1 Corrections verified against the docs

| Brief said | Docs say | Source |
| --- | --- | --- |
| The late-day lock-in repair is "not yet served" | **It is served.** lockin-anchor-v3 (#191, `ML_MODEL_VERSION` v0.5.11, merge `094f5b393` 2026-10-06), the M0 METAR observation-time keying fix (#189) and lockin-anchor-v4 (#246, v0.5.12) all landed in N3; N3 reached `master` as `6ad52c89f` on **2026-10-09 01:20 EDT**. What is not landed is the **scorer** (`claude/evening-fix-scorer-20261013` @ `8cdcb62ec`, must land before 10-28; first and only read 2026-10-29). | evening-fix prereg §0.1, §0.2, §7 (`docs/research/evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md`); DL 2026-10-05, 10-06, 10-08, 10-13 rows; SOP open commitments |
| Lock-in defect "live since about 2026-06-30" | Confirmed: `PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False` by commit `5735b573a` on 2026-06-30, so all five late-day lock-ins and the calibration taper received `None` from then until N3 (10-09). | EF §10e, §10q |
| NBM parser defect found 09-21 (`-09-82a`) | Confirmed. Repair (parser v2) built (`-09-83a/b/c`), **lands 10-18** (#190, owner 10-13). The served headline model selects **no NBM column**, so served output was never affected; only the promotion-blocked shadow variant and the guidance *candidates* were. | EF §10k, §10l, §10h; SOP "Model" line; DL 2026-10-13 |
| Serving floor 2026-07-31 | Confirmed (served ratio 1.6639 -> 1.4980). | EF §3 |
| Blind-feature repair | Confirmed: routing defect since 06-30, repaired 2026-08-08 (`-09-43a`), 9 of 10 routed; `pressure`/`pressure_trend_3h` stay dead in the 11 F markets by design; `wind_group` dead in all 12 (owed). | EF §4 |
| WU live inputs disabled 2026-06-30 | Confirmed (same commit as above). | EF §4, §10e |
| 2026-07-31 provenance boundary | Confirmed: artifact provenance, anchor commit `b77cfbed` (2026-07-30), never a date cutoff. | EF §5; RF §2 |
| Non-committed served bytes | Confirmed: 324 of 413 captured fingerprints match no reachable blob; 0 of 368 decision rows exactly reconstructable. A replay-trust defect, not a served-quality defect. | EF §1k (`-09-76a`) |

Two further defects the brief did not list but which matter for taint:

- **M0 — METAR rows keyed by AWC `reportTime`**: a D-1 23:5x report entered day D's running max on 0.3-0.6% of
  station-days Aug-Sep (2.2% Oct-Dec, up to 5.4% at KLGA); fixed in N3 (#189). It corrupted the *floor* used by
  79a/81a/111h/swarm candidates on those station-days. EF §10q.
- **The afternoon residual-centering artifact (110g)**: its contexts were fitted in-sample in June on a pipeline not
  served since 06-30; `component.enabled=false` by owner decision 2026-09-25, but "production activation requires the
  model reload". Whether the reload has happened is **UNKNOWN** from the docs read. EF §2.

### 0.2 Defect timeline (what was live when)

| Defect | Live from | Live until | Hours / rows it touches | Owner section |
| --- | --- | --- | --- | --- |
| Served realized-band zeros (serialization) | before 2026-06-15 | commit `28d1c146`, 2026-06-15 | 8.486% of F rows before; 0 after | EF §1k (`-09-68a`); RF |
| WU live history/current disabled -> 10 of 19 features imputed | 2026-06-30 | 2026-08-08 (`-09-43a`; 2 F-market fields and `wind_group` still dead) | every hour, every market | EF §4 |
| Late-day lock-ins (5 stages) + calibration taper no-op | 2026-06-30 | **2026-10-09** (N3) | 17-23 local mainly; S3-S5 cover 13-19 h | EF §10e, §10q |
| Replay floor rebuilt, not recorded (replay instrument only) | always (replay) | n/a | B: 81.1% of rows differ from served; C: 0% | EF §1k (`-09-65a`, `-09-66a`) |
| `high_so_far` not a running max (WU series drops rows) | WU-live period (pre 06-30) | moot after 06-30 (WU dark); unrepaired | B: 906 falls, 40.6% in peak/settlement window | EF §1k (`-09-70a`..`-09-73a`) |
| Serving floor defect (pre-fix) | before 2026-07-31 | 2026-07-31 | evening mostly (2.2% of the gain landed 09-14) | EF §3 |
| Training contamination (`forecast_high` not PIT) | all fits (June) | unrepaired; priced as not the lever | fit-time only | EF §6, §0a |
| NBM parser v1 reads next-morning minimum after 13Z | always (capture) | parser v2 lands 10-18 | 67% of captured NBM rows; served model unaffected | EF §10k, §10l |
| M0 METAR `reportTime` keying | always (capture) | 2026-10-09 (#189) | 0.3-0.6% station-days Aug-Sep | EF §10q |
| Afternoon residual-centering contexts stale (110g) | 2026-06-30 (pipeline change) | disabled 2026-09-25; reload status UNKNOWN | afternoon centre | EF §2 |
| `trusted_current_max` null on 100% of extract rows; 31 rows with floor 10 F above METAR max | Aug-Sep extract | UNKNOWN | floor mask | EF §10q |
| Served bytes never committed | through at least 2026-08 | release binding since (UNKNOWN whether N3 closes it) | replay reproducibility only | EF §1k (`-09-76a`) |

### 0.3 Which panels carry which defects

| Panel | Dates | Hours | Instrument | Defects live |
| --- | --- | --- | --- | --- |
| **B** in-season sealed pre-boundary | 23 dates, June (front segment 06-03..06-23 is 21 of them), 204 market-days, 4,636 snapshots | all | **replay** on captured inputs (not served output) | replay floor divergence (cosmetic in mean, 0.57% of gap); `high_so_far` falls; 28 inherited zeros (2.6% of G); blind features in the control arm; contamination. **WU was live, so the lock-in stages had inputs: the evening defect is NOT in B.** |
| **C** out-of-season sealed pre-boundary | 27 dates, 06-24..07-30, 320 market-days, 7,653 snapshots | all | replay | **24 of 27 dates are after 06-30: the lock-in/taper no-op is in C**, in every all-hours and every 17-23 number; blind features (control arm); 1 inherited zero. |
| Floor-fix pre/post panel | D=8, M=11, 85 market-days (late July / early Aug; exact dates not stated in EF) | all | served snapshots | lock-in no-op in both arms; blind features in both arms |
| 79a served surface | targets 08-01..09-19, 503 market-days, 12 markets | served output | lock-in no-op (matters 17-23 only); blind features 08-01..08-07; M0; afternoon-centering stale; parser v1 in the *candidate* only |
| 111h / swarm table | targets 08-01..09-29, 626 market-days, **11 US markets (no Toronto)**, 110,807 snapshots | served output + parser-v2 extract | lock-in no-op in the served arm (the swarm *emulated* its repair as rung r1); M0 in the floor; afternoon-centering stale to 09-25 |
| Workstation research lineage (§1m) | 2024-2025 Previous Runs corpora; 2026 06-03..08-09 | point-forecast regression | not the served model at all; `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN` |

**The standing caveat on every "served" headline number from the sealed panel:** §1's 1.423246x is labelled "served"
but was produced by `-09-44a`'s paired replay (control "re-run rather than read", EF §4), and replay does not reproduce
served output (0 of 368 decision rows exactly; EF §1k). The only numbers measured on literally served output are §3,
`-09-66a`, §10h/§10j/§10p and the swarm table.

---

## 1. Which conclusions survive the bug fixes

Verdict key: **STANDS** = conclusion holds for the thing it measured and nothing landed since changes it;
**TAINTED** = the number or claim includes a now-repaired defect and must be re-measured before re-citing;
**PARTLY** = says which part. "Re-measure" names what would settle it.

| # | Claim (FD line) | Measured when / on what | Known defects live in what it measured | Verdict | What re-measurement would settle it |
| --- | --- | --- | --- | --- | --- |
| 1 | **Gap to market, in-season, 1.423246x [1.2426, 1.6590]** (EF §1, §4, `-09-44a` 2026-08-09) | Replay on stratum **B** (June, 23 dates, 204 md), repaired input surface, paired control re-run; "served" label, replay instrument | Replay floor divergence (cosmetic, 0.57% of gap, `-09-66a`); `high_so_far` falls on the decision path; inherited zeros 2.6% of G; contamination. **Not** the evening no-op (WU live in June). Blind features: both arms measured, null. | **STANDS** as the June in-season gap of the frozen artifacts. **TAINTED as a description of the model served today**: the served path has changed four times since (floor 07-31, routing 08-08, lock-in v3/v4 + M0 10-09, 110g disable 09-25) and no served-vs-market ratio exists for the post-10-09 path at any hour. The last served-output read (Aug-Sep, 11 US markets) was 1.77x all-hours with the defect live and ~1.34x *emulated* post-fix (development, EF §10q). | A served-vs-market ratio on new dates after 10-09, per hour block, crossed and fixed-market intervals, 12 markets. In-season (May 10 - Jun 30) cannot be re-measured before 2027; out-of-season can start now. |
| 2 | **Out-of-season gap 1.526x -> 1.542x; "we serve out-of-season"** (EF §1b.4, §1c) | Replay on stratum **C** (06-24..07-30) | **Evening no-op on 24 of 27 dates** (all-hours ratio includes 17-23 defect loss); blind features (control arm) | **TAINTED** (the number). The structural point — the archive is May 10-Jun 30 so August-onward is out of season (EF §4b) — **STANDS**. | Same as row 1, out-of-season stratum, after 10-09. |
| 3 | **Recalibration bounded at 16.494% of the gap, not distinguishable from zero** (EF §1c, `-09-56a`) | Fit on B, score on **C**; four leakage-safe monotone families; power 0.458, MDE 13.3pp | C carries the evening no-op (mass above a known high on 17-23 rows is the defect itself and inflates the gap denominator); blind features in the surface | **PARTLY.** "Calibration is not the workstream" very likely survives — neither landed repair is a monotone map, and the §10q ladder still leaves 00-16 at 1.29x after both repairs. The **number** (8.829% / 16.494%) is a property of the defective surface and must not be re-cited for the post-10-09 path. | Repeat the §1c design on post-10-09 served output (fit on one half of new dates, score on the other, same four families, training score checked first). |
| 4 | **Shrinking toward the market closes 65.1% of the gap on the disagreement set; full replacement 85.6%** (EF §1c) | C stratum, rows with \|model-market\| >= 0.30 | Evening defect rows are exactly >=0.30 disagreement rows where the market is right | **TAINTED in magnitude**; the method rule (shrinkage is a measurement, never a candidate) **STANDS**. | Re-run the shrinkage controls post-10-09 — only as the locator of missing information, and separately per hour block. |
| 5 | **114 pre-registered cells, zero with a positive point estimate; overall edge -0.01915 [-0.02444, -0.01443]** (EF §1b.2, `-09-46a`) | Pre-boundary sealed panel (exact strata not stated in EF: **UNKNOWN** whether B+C or C only); positive control 840/840 | If C rows are in: evening no-op in every 17-23 cell and every all-hours cell; blind features (post-repair surface presumably — UNKNOWN) | **PARTLY.** The structure — "we match the market only where we already agree with it" — is corroborated on served output by §10h (morning 1.44-1.48x before any evening hour) and by §10q (00-16 still 1.29x after both repairs). The **per-cell map**, especially 17-23 and the disagreement cells, is tainted. "Model-skewed quoting is retired" **STANDS** until a post-fix cell shows a lower bound above zero. | Re-run the 114-cell map, pre-registered, on post-10-09 served output over >= 45 countable dates, one look. |
| 6 | **Input repair did not move the gap (precise null, 1.423260 -> 1.423246)** (EF §4, `-09-44a`) | Paired delta on identical rows, D=50 both strata | Shared defects cancel by pairing; the full repair (humidity, F-market pressure) is "unmeasurable until v3 parsers have been capturing for a while" (EF §4) | **STANDS** for what it measured. **Not exhausted:** RF ("full free-source parity has never actually been measured") — Toronto ECCC fields were absent from `-09-26a`, and two months of v3 captures now exist. | Measure the full free-source parity (humidity, pressure, trends) on captured data since 08-08, paired, crossed; severe-tail endpoint. |
| 7 | **Cool bias -0.64387 C-eq; seasonal coverage root cause (B -0.18 vs C -1.02, contrast -0.8346 [-1.4378, -0.2159])** (EF §2) | Base-HGB centre vs settlement, D=50 replay | Centre of the base HGB is pre-lock-in, so the evening defect does not enter; the afternoon-centering artifact (110g) changes the *served* centre if reloaded (UNKNOWN) | **STANDS** for the frozen June artifacts (unchanged since fits of 06-10..06-13). The served October centre is unmeasured; the bias is a function of seasonal distance, so the current value is UNKNOWN. | A served centre-vs-settlement read on post-10-09 dates by market (heterogeneous by design, EF §2). |
| 8 | **Loss concentrated: 4.387% of band rows carry 64.140% of excess; tail = centre overconfidence, AUROC 0.90260** (EF §1, §1f) | D=49-50 both strata, 5,930 tail rows | **Evening defect rows are tail rows by construction** (served SE > market SE and disagreement >= 0.30); on the Aug-Sep table the tail carries 90.4% of the 17-23 excess (SYN §4) and the lock-in restoration alone removes 84% of that tail | **TAINTED**: the concentration figure, the centre/shoulder split and the AUROC all include defect rows from C. The in-season B part is clean but not reported separately in EF. | Recompute the tail definition, concentration and the §1f predictor on post-10-09 served output; and run the never-done §1f caveat-3 check (rank-based disagreement gate). |
| 9 | **Conditional reshaping loses to global smoothing on its own training score; distribution reshaping closed** (EF §1g, `-09-60a`) | **B only** (in-season) | None of the serving defects (B predates 06-30); replay floor | **STANDS** for B. Its "whole family capped by §1c's bound" leg is **PARTLY** (inherits row 3). | Nothing cheap; re-derive after row 3 is re-measured. |
| 10 | **Centre not width; never sharpen globally; never weaken the floor** (EF §1, §2, §1g) | B (beta=0.55 < 1); floor absorption interval excludes zero | Same as row 9 | **STANDS**. | — |
| 11 | **Serving floor moved the served ratio 1.6639 -> 1.4980 [-0.3553, -0.0698]; ~2.2% in 09-14** (EF §3) | Served snapshots, D=8, M=11, 85 md, late Jul / early Aug | Lock-in no-op and blind features in both arms | **STANDS** as a record. **As the "positive control for any skill tracker"** it is now only reproducible on pre-10-09 data: the evening serving path changed on 10-09, so a tracker must be validated on the pre-fix window, not on today's output. | Re-base the positive control: reproduce §3 on its own dates, then run the tracker forward. |
| 12 | **The gap is already there in the morning (1.44-1.48x at 06-09) and widens intraday** (EF §10h) | Served surface 08-01..09-19, 12 markets | M0 (0.3-0.6% of station-days); blind features 08-01..07; afternoon-centering stale; lock-in no-op (17-23 only, so the morning figure is clean) | **STANDS** for mornings. The afternoon figures (1.789 / 1.715 at 13-16) are clean of the lock-in but may carry the 110g artifact. | A post-10-09 per-block ratio (row 1). |
| 13 | **Raw NBM read beats served by 0.012-0.015 Brier in the morning, still 1.15-1.22x market; halves to -0.0067 on every row; not confirmable at any season length under crossed clustering** (EF §10h, §10j) | Served surface mornings; parser v1 rows that passed the floor (mostly genuine 01Z/07Z maxima); 111h census: 81 of 7,031 eligible 06-09 rows (1.15%) used a wrong-period minimum | Parser v1 (small, counted); M0; the power cap is structural (11 US clusters) | **STANDS**. The "any season length" cap is a property of the crossed rule; FP item 7 proposes fixed-market inference for decisions, under which the signed MG-1 prereg reaches 0.80 at 45 dates at the half effect (SYN §8). | MG-1 forward read (signed `b044e0f1`; D0 >= first countable date after #190 lands 10-18; 45 countable dates). |
| 14 | **NBM at all hours closed: pooled -0.000924 [-0.006083, +0.003924]; afternoon harm 13-16 +0.0060, 17-23 +0.0155** (EF §10p, `2026-09-111h`) | 111h table, parser v2 extract, served arm with the lock-in defect live | The 17-23 harm is measured against a *defective* served arm; post-fix the served arm improves by -0.0252 there, so stale whole-day guidance would look worse still. At 13-16 the restoration moves served by only -0.0006 (S3-S5 by -0.0020). | **STANDS** (the fix strengthens, not weakens, the closure). An hour-gated candidate remains open and may not pick its hours on this table. | HG-1 as its own alpha arm on new dates (SYN §8; held by owner until the evening fix was live — it now is). |
| 15 | **Two serving repairs close 54% [35, 70] of the Aug-Sep gap (1.73x -> 1.34x); evening is a serving defect, cosmetic for the maker** (EF §10q) | Development on already-read dates; band-level **emulation**, not replay; 11 US markets | M0 in the floor; the emulation anchor was superseded (max(history_max, guidance_floor) -> v3 observed same-day high, RF 2026-10-05); the v3 replay (<= 09-29) checked floor safety, not Brier | **STANDS as a development read; not yet confirmed on any new date.** The v3/v4 rule actually served differs from the emulated rung, so the 85% figure is a prior, not a prediction. | The signed evening-fix scorer: window 10-16..10-27, one look 10-29, NEW vs OLD replay against market, 17-23 primary (prereg §2-3). |
| 16 | **No external free source adds information beyond captured NBM v2 plus the two repairs** (EF §10q; RF "Capture NBH … false lead") | Same table; increments measured over MG-1 / no-source controls **with rung r1 already emulated**, so the evening taint is handled by construction | M0; emulation; 11 US markets, one season (Aug-Sep); hunter-chosen candidate forms; intervals **do not exclude the 5% bar** (00-16 bar ~ -0.0012) for NBH [+0.0027, CI -0.0037..+0.0098], MOS/NBE [-0.0015, -0.0049..+0.0019], ECMWF [+0.0031, -0.0025..+0.0091], HRRR latest 06-09 [-0.0005, -0.0058..+0.0039], GOES 10-12 [-0.0011, -0.0026..+0.0002]. Only NBS is a precise null at 00-16 [+0.0003, -0.0004..+0.0011]. | **PARTLY.** "No increment was *demonstrated*, and there is no capture case on this evidence" **STANDS**. "No increment *exists*" is **not established at the 5% bar** for NBH, MOS/NBE, ECMWF, HRRR and cloud; it is established for NBS (00-16) and, by placebo, for NWS revision direction. Nothing was tested for **Toronto** (no NBM there) or outside Aug-Sep. | Per-source paired increment over MG-1 with a pre-declared MDE at the 5% bar, on new dates, fixed-market inference; Toronto needs its own control (no NBM). |
| 17 | **The 11/12 extra free PIT fields are tested, not untested: NWP-anchored residual +0.2751 C^2 [-0.0234, +0.6186], INCONCLUSIVE_UNDERPOWERED x3, never harmful; pooled refit worsened the centre** (EF §1m; RF "stale since 09-02") | Workstation research lineage 2026-09-01..04 (unmerged); point-forecast regression on a NWP anchor; 2024-2025 and 2026 pre/post; research baseline Brier 0.0779 (not served) | **None of the serving defects** (it is not the served model). Corpora carry `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`. | **STANDS** as TESTED-UNDERPOWERED (powers 0.06-0.39). Spent evaluations may not be reused; the preflight (`codex/48h-residual-preflight-20260911`) was built and never executed. | A new pre-committed design on unspent years (settled 2026 season, then 2027); OQ Q-16. |
| 18 | **No free source satisfies the v2 point-in-time contract** (EF §1m, research 82a) | Documentation review only (no provider called) | n/a | **STANDS** as a *contract* property. It does not say the Previous Runs corpora are unusable for research — they were used three times (row 17). | Only provider-owned availability evidence (OQ Q-17 CLOSED). |
| 19 | **Own-information dispersion signals: blind null (power ~0.11), PIT source stopped 2026-06-23** (EF §1e, `-09-58a`) | B, 11-14 date clusters after warm-up | None of the serving defects; the thinness was the PIT fetch, which was then re-run and **staged, not adopted** (1,645,056 rows, 12 fields x leads 1-7, 06-03..08-09) | **STANDS** as blind. **Not exhausted**: the re-fetched corpus has never been used to re-run the screen, and the §1h protocol (12 named features, frozen, SHA `336150be…`) was **closed unused** because Gate 3 fired on a replay artifact — "the surface-heating mechanism was not tested in either direction" (EF §1j). | Execute the §1h protocol with Gate 3 replaced (EF §1k `-09-68a`: never re-register it unchanged) on the staged corpus; decision 10 stays retired, so it needs a new ledger row. |
| 20 | **Training contamination is not the lever: B - A = -0.000107 [-0.001588, +0.001349], power 0.066** (EF §6, `-09-42a`) | A/B/C fit on the 09-14 primary and all hours | n/a (fit-time) | **STANDS** as "not demonstrated"; underpowered, so it does not prove the PIT file is worthless. | Fold into any retrain lane (row 24) rather than test alone. |
| 21 | **The gap does not vanish in-season; served in-season 1.4233 [1.2428, 1.6589], base lane 1.7466** (EF §4e) | B/C seasonal-distance corpus | B clean; C carries the evening no-op (out-of-season rows only) | **STANDS** for in-season B. | Row 1. |
| 22 | **The instrument is sound: repair adds no zeros, served floor cosmetic in the mean, labels flat (ceiling ~13%)** (EF §1k `-09-64a`..`-09-67a`) | B and C | Checked one by one; none explains the gap | **STANDS**. | — |
| 23 | **Replay does not reproduce served output; never commission reproduction** (EF §1k `-09-74a`..`-09-76a`) | Decision stratum B, 368 rows | Non-committed bytes | **STANDS**. Whether release binding since N3 closes the commit-discipline defect going forward is **UNKNOWN** from the docs read. | Not a forecast question; a forward check that today's served fingerprints resolve to `master` blobs. |
| 24 | **Retrain: archive covers May 10 - Jun 30; season window blocks it; 14 cells unfillable; the PIT wall is 9 of 21 fields** (EF §4b, §4g, §0a, §4f) | Production archive, probes 2026-08-07/09 | n/a | **STANDS**. **Not exhausted**: no retrain has ever completed (`base_retrain` reached preflight once, EF §4a-bis); the §1d season-matched refit proxy reads 24.893% [-20.5%, +55.2%] of the out-of-season gap — unpowered, never tested as a candidate. | A season-matched retrain on temperature PIT (all years) + the 12 fields (2024-2025) with the §4g exclusion list, scored under a pre-registration on the C-type stratum. |
| 25 | **13 of ~26 serving post-processing stages are no-ops since 06-30** (EF §10e) | Code trace; 28 served payloads read for the lock-in/taper | The lock-in and taper are now repaired (10-09) | **STANDS** for what was read. The forecast consequence of the **other ~7 no-op stages** was never measured and is **UNKNOWN**. | One served stage-vector read per remaining no-op stage, then a paired emulation as in §10q. |
| 26 | **Primary objective (09-14) has no powered measurement; ~504 withdrawn; 3.2% MDE floor from 12 market clusters** (EF §1b.1, §1d, §5) | Design simulations on the sealed cluster structure | n/a | **STANDS** (structural). | Only more markets, a paired design, or batching (EF §1d); FP item 7 (fixed-market inference) changes what is confirmable. |
| 27 | **Blending the model with the market hurts (older clean-regime panel)** (EF §1) | Older panel, clean regime, global blend | Unknown older-surface defects (pre-06-15 zeros possible) | **STANDS only for its panel** and is already fenced from row 4 by EF §1c's citation hazard. | — |
| 28 | **T+1/T+2: the served model has no output; the tape is T+0 only** (FD; t12 prereg §Premises) | Code and 293 event folders | n/a | **STANDS**: nothing about T+1/T+2 forecasting has ever been measured. | See §3 lead L8. |

**Count:** 28 rows. Fully **TAINTED**: 3 (rows 2, 4, 8). **PARTLY**: 4 (rows 3, 5, 16, and row 1's "current model" use).
**STANDS**: 21, of which 7 carry an explicit "not exhausted" note (rows 6, 15, 17, 19, 23, 24, 25).

**What the taint is and is not.** The evening no-op entered every measurement that pooled 17-23 hours on dates after
2026-06-30 — i.e. stratum C, every all-hours served read from August on, and every tail statistic that includes C.
It did **not** enter the in-season B figures (WU was live in June), so the central "1.42x in-season, information not
calibration" conclusion is intact for June. The NBM parser defect touched no served number. What the fixes do create
is a **gap in the record**: there is no served-vs-market number for the path actually served since 10-09, and the
one development estimate of it (1.34x all-hours, 1.29x for 00-16) still sits well above parity.

---

## 2. Free data-source inventory

Scope: the 12 served markets are **11 US** (Atlanta, Austin, Chicago, Dallas, Denver, Houston, Los Angeles, Miami,
NYC, San Francisco, Seattle) **plus Toronto**. The venue lists 51 cities in `config/locations.json`; the foreign WRH
cities (London, Paris, Seoul, Shanghai, Tokyo) and Hong Kong are venue markets with a known settlement source
(EF §10c) but **no served forecast, no capture of guidance, and no test of anything** (OQ Q-14 is the capture census;
Taipei and Jinan were the "ingest-now" picks). Every row below is therefore NOT TESTED for the foreign cities.

Binding constraints: no paid provider (EF §6; AGENT_CONTEXT); train/serve point-in-time parity (EF §0a, §4f); any
"improvement" must clear the 3.2% floor and be pre-registered (EF §1d, §5). Status key:
**TESTED-NO-INCREMENT** (interval excludes the 5% bar or placebo beats it), **TESTED-UNDERPOWERED** (interval
includes the bar; "null" in the swarm's words but not precise), **TESTED-DEV-LEAD** (development lead awaiting a
forward read), **BLOCKED** (PIT/parity/history), **NOT TESTED**.

| # | Source | US 11 | Toronto | Status and citation | Notes |
| --- | --- | --- | --- | --- | --- |
| S1 | **NBM v2** (NBP text bulletin, parser-fixed, captured) | yes | **no coverage** ("none for Toronto", EF §10h) | **TESTED-DEV-LEAD**: MG-1 zero-parameter read 00-16 -0.0100 [-0.0179, -0.0035], 10/11; still 1.29x after both repairs (EF §10q); forward prereg signed (`b044e0f1`), D0 after #190 lands 10-18 | Served model selects no NBM column. From 12Z the newest bulletin holding today's max is 07Z, so afternoon guidance is 5-24 h old by construction (EF §10l). |
| S2 | NBM hour-gated (HG-1) | yes | no | **NOT TESTED** (rule 8 forbade picking hours on the table; held by owner until the evening fix was live — it now is) | SYN §8 D-HG; needs its own alpha arm. |
| S3 | **NBH** (hourly blend) | yes | no | **TESTED-UNDERPOWERED, wrong sign**: 00-16 increment over MG-1 +0.0027 [-0.0037, +0.0098], 5/11 (EF §10q; RF) | Declined for capture (DL 10-04). The interval includes the -0.0012 bar. |
| S4 | **NBS** (short-range blend) | yes | no | **TESTED-NO-INCREMENT** at 00-16: +0.0003 [-0.0004, +0.0011] (SYN §1.3) | The one precise null among the sources. 13-16 fails Bonferroni and LOMO. |
| S5 | **MOS / NBE** (MAV/MET/MEX/LAV + NBE) | yes | no | **TESTED-UNDERPOWERED**: 00-16 -0.0015 [-0.0049, +0.0019]; 13-14 -0.0063 [-0.0119, -0.0006] is post-hoc and not an increment over t3-r3 (-0.0031 [-0.0077, +0.0017]) (EF §10q) | ~90% of its morning gain is the captured-v2 control. |
| S6 | **HRRR** single run (production captures `hrrr_high`, latency ~2.5-3.5 h) | yes | no (HRRR is CONUS) | **TESTED-UNDERPOWERED**: HRRR-latest 06-09 -0.0005 [-0.0058, +0.0039], 3/8; 79a error kernel 1.308/1.251x market (EF §10h, §10q) | Served model selects no HRRR column (EF §10h). |
| S7 | HRRR multi-run / time-lagged ensemble | yes | no | **TESTED-UNDERPOWERED / NULL** (T9 "adds nothing as centre or spread", SYN §6.2; no interval quoted) | — |
| S8 | **RAP** | yes | partial | **NOT TESTED** | Not named anywhere in EF/SYN. |
| S9 | **GFS** (direct) / **GEFS** ensemble | yes | yes | GFS: **BLOCKED as a PIT source** (no historical first-availability, research 82a, EF §1m); as a forecast it enters only via Open-Meteo `forecast_high` (79a kernel 1.516/1.456x). **GEFS: NOT TESTED.** | The 20 settled Open-Meteo fields contributed nothing to the fit (EF §6) — but that fit dropped them (EF §4). |
| S10 | **ECMWF IFS** open data | yes | yes | **TESTED-UNDERPOWERED, wrong sign**: 00-16 +0.0031 [-0.0025, +0.0091] (EF §10q) | "Already captured through Open-Meteo" (SYN §5). ECMWF **ENS** open data: **NOT TESTED**. |
| S11 | **ECMWF AIFS** (free open data) | yes | yes | **NOT TESTED** | Not named anywhere. |
| S12 | **ICON** (DWD, via Open-Meteo) | yes | yes | **NOT TESTED** as a separate source | Open-Meteo per-model decomposition never done. |
| S13 | **GEM / HRDPS / RDPS** (ECCC) | n/a | **yes — the only guidance family native to Toronto** | **NOT TESTED** | Toronto has no NBM; nothing guidance-shaped has ever been tested for it. ECCC SWOB is used for observations only (EF §4). |
| S14 | **Open-Meteo individual models** (multi-model consensus in served `forecast_source_count`, `forecast_disagreement`) | yes | yes | **PARTLY**: temperature PIT is served; the 7-run forecast-high SD was a **blind null** (power 0.113, EF §1e); per-model decomposition **NOT TESTED** | Which models feed the consensus is not stated in EF: UNKNOWN. |
| S15 | **Open-Meteo Previous Runs, 12 PIT fields** (leads 1-7) | yes | yes | **TESTED-UNDERPOWERED** x3 (research 88a/100h/90a, EF §1m); pooled refit worsened the centre (86a, power 0.148); staged 2026 fetch **not adopted** (EF §1e) | History: temperature 2021-2025; ten fields 2024-2025; `precipitation_probability` 2025 only. The §1h protocol on these fields was never executed (EF §1j). |
| S16 | **NWS gridpoint forecast** (captured; "NWS-grid column" exists) | yes | n/a | **TESTED-UNDERPOWERED** as a point kernel (1.429/1.372x market, EF §10h); not in the served column set | — |
| S17 | **NWS forecast revisions** (direction) | yes | n/a | **TESTED-NO-INCREMENT**: "classifier LEAD is a blur artefact; placebo beats it" (T12, SYN §6.2) | — |
| S18 | **Area Forecast Discussion** text | yes | n/a | **NOT TESTED** | Not named anywhere. |
| S19 | **METAR / SPECI** (served floor source) + **remaining-rise rule** | yes | yes (CYYZ :00) | Floor: served. Remaining-rise t3-r3: **TESTED-DEV-LEAD** at 13-16 -0.0116 [-0.0190, -0.0052], 10/11, fragile (WEAK at +1 h, NULL at +2 h, fails family-wise z -3.26); D2 draft unsigned, 17% power at the half effect (EF §10q; OQ Q-19). SPECI event study **unpowered** (EF §10h). | Observation clock measured (89b): station-specific routine minutes; capture-host `data/metar` history stops 2026-06-30 (FD). |
| S20 | **5-minute / 1-minute ASOS** (IEM, NCEI) | yes | n/a | **NOT TESTED** as an input. Used only for settlement mechanics (1-min true max as a target: HARM; rounding headroom: NULL — T16, SYN §6.2) | Directly relevant to t3-r3's freshness sensitivity (-40% per hour of staleness). |
| S21 | **Mesonets / PWS free tiers** (MADIS, Synoptic free tier, WU PWS pages) | yes | yes | **NOT TESTED** | OD15 (DL 2026-10-06) declares a scraped WU public-page token acceptable under the no-paid rule; whether WU history has been re-enabled on it is **UNKNOWN** (OQ Q-21 still says "WU history dark since 06-30"). |
| S22 | **WU history itself** (the settlement proxy) | yes | yes | **BLOCKED since 06-30 by the paid-provider flag**; OD15 opens a free route; **NOT TESTED** since | The original lock-in anchor; Q-21 (intraday vs daily summary) needs it. |
| S23 | **Neighbouring stations** | yes | yes | **TESTED-UNDERPOWERED**: WEAK ~0, HARM at 06-09; 13-16 -0.0006 (7/11) (T13, SYN §1.3) | — |
| S24 | **12Z soundings** | yes | yes | **TESTED-UNDERPOWERED** at 17-23 only (-0.00073 [-0.0032, +0.0008], 2 markets); 00-16 not reported (T11) | Mixed-layer / inversion as an afternoon-cap signal for 13-16 **NOT TESTED**. |
| S25 | **GOES satellite / cloud** (with METAR cloud) | yes | yes | **TESTED-UNDERPOWERED**: 10-12 -0.0011 [-0.0026, +0.0002] vs served (T14) — the point sits on the bar | — |
| S26 | **Radar** | yes | yes | **NOT TESTED** | Not named anywhere. |
| S27 | **Marine / buoy** (onshore flow, lake breeze) | coastal | yes (lake) | Served geometry proxies (`onshore_flow`, `lake_breeze_proxy`) survive; live marine data status **UNKNOWN** (memory says the feature went dark; no EF section read confirms); increment **NOT TESTED** | — |
| S28 | **Climatology / persistence** | yes | yes | **TESTED-NO-INCREMENT / HARM** standalone (t3-r1 HARM 13-23; t3-r2 WEAK 00-09, HARM 13-23, SYN §1.3). As a rolling per-market centre correction (FP item 8): **NOT TESTED** | — |
| S29 | **ML weather models** (GraphCast, Pangu, FourCastNet via free mirrors; AIFS) | yes | yes | **NOT TESTED** | No free mirror is named or evaluated in the docs. |
| S30 | **Venue order flow and prices as information** | yes | yes | Shrinkage: **measured, forbidden as edge** (EF §1c, §5); as a maker fair value: **hypothesis, NOT TESTED** (EF §1c "the MM question is OPEN"); market Brier falls at informative METARs (T17, descriptive); public-flow timing (94a/95a, OQ Q-06/Q-07) | Maker replay v2 is the live path (SOP). |
| S31 | **Other prediction markets' prices** (e.g. Kalshi) | yes | yes | **NOT TESTED**; reading prices is not trading, but "International only" is the owner's rule — needs an owner call before any probe | — |
| S32 | **RTMA / URMA analyses**, **NAM**, **HREF/SREF** ensembles | yes | partial | **NOT TESTED** | Not named anywhere. |
| S33 | **Own lagged forecast error** (forecast tracker residuals) | yes | yes | **TESTED-UNDERPOWERED / blind** (lagged five-day error SD, power 0.103, EF §1e) | Never re-run on the staged corpus. |

**Inventory tally (US 11):** TESTED-NO-INCREMENT 4 (S4, S17, S28 standalone, and NWS-revision placebo);
TESTED-UNDERPOWERED 11 (S3, S5, S6, S7, S10, S14 partial, S15, S16, S23, S24, S25, S33); TESTED-DEV-LEAD 2 (S1, S19);
BLOCKED 2 (S9 as PIT, S22); **NOT TESTED 12** (S2, S8, S9-GEFS, S11, S12, S13, S18, S20, S21, S26, S29, S31, S32 —
counting S32's three families as one). **For Toronto every guidance-shaped source is NOT TESTED**, and the one
native family (S13) has never been opened. For the foreign cities the inventory is empty.

---

## 3. Method leads not yet exhausted

| # | Lead | What the docs say | Status |
| --- | --- | --- | --- |
| L1 | **Post-fix forward measurement of the served model against the market, all hours** | Fix served since 10-09 (prereg §0.1). Only the 17-23 block has a registered read (evening-fix scorer, 10-16..10-27, read 10-29). The daily model-vs-market scoreboard (learning lane) has been blocked since 08-13 (OQ Q-11), so **no running tracker exists**; §3's numbers are the positive control it must reproduce (on pre-10-09 data). | Partly registered (17-23); the all-hours served ratio on new dates is **unregistered**. |
| L2 | **MG-1 forward read** | Signed `b044e0f1`; narrow reservation; D0 after #190 lands 10-18; 45 countable dates; fixed-market joint power 0.80 at the half effect (SYN §8; DL 10-04). | Registered, waiting on the parser landing. |
| L3 | **Hour-gated NBM (HG-1)** | Held until the evening fix is live (now true); separate alpha arm; may not choose hours on the 111h table (EF §10p; SYN §8). | Unregistered. |
| L4 | **The 13-16 block (1.81x after both repairs; 15-16 post-hoc 2.53x)** | Largest residual; S3-S5 recover only -0.0020; 58% of 15-16 snapshots have not rolled over (a remaining-rise problem); t3-r3 helps but is fragile and freshness-bound (EF §10q; OQ Q-19). Fresh observations (S20), soundings for the afternoon cap (S24) and ECCC/HRDPS for Toronto are untested there. | D2 draft unsigned, underpowered at the half effect; owner option in D2 §6. |
| L5 | **The 00-12 residual (+0.010 to +0.014, 1.18-1.26x)** | "Nothing tested closes it"; needs a hypothesis with a no-source control before any new capture (OQ Q-20). | No candidate. |
| L6 | **Fitted spread forms on captured v2 (T18 EMOS / RV-1)** | Indistinguishable from MG-1 in 00-16 (-0.0034 [-0.0078, +0.0007]); better all-day; held until the evening fix was live; shares the reserved dates with MG-1 (sign one per family or split alpha) (SYN §8-9). | Held; unregistered. |
| L7 | **Per-market / per-season specialisation** | Cool bias is heterogeneous by market (no global offset, EF §2); per-market isotonic tested and closed (EF §1c); season-matched refit proxy 24.9% [-20.5, +55.2] never tested as a candidate (EF §1d); the retrain never completed (EF §4a-bis); 12-field pooled refit worsened the centre, underpowered (EF §1m). Rolling per-market centre correction (FP item 8) not run. | Open; blocked on a retrain lane that has never run end to end. |
| L8 | **T+1 / T+2 markets** | Served model has no T+1/T+2 output; tape is T+0 only; T+1/T+2 books exist only in 88a (frozen until after 10-14); the maker fair value is a frozen single read (10-15); the NWP-timing market-only prereg (10-02) is frozen and awaits the 88a transfer. Parser v2 "target = tomorrow is right at every cycle" (EF §10k), so a day-2 NBM read is mechanically available. | **Never measured**; a T+1/T+2 forecast-vs-market read is a new pre-registration. |
| L9 | **Foreign cities** | No served model; settlement sources known (EF §10c); OQ Q-14 census (Taipei, Jinan first; 147 "later" on settlement alignment). | Nothing exists. |
| L10 | **Blending with the market as a pull / fair-value signal, not an edge** | EF §1c leaves the MM use open; informed-maker design; maker replay v2 (signature target 10-22..23, SOP); T17 descriptive; 95a METAR pulls catch 1.18x of large moves on T+0 only. | On the maker critical path, not a forecast test. |
| L11 | **Full free-source parity re-measurement** | "Full free-source parity has never actually been measured" (RF, ECCC verifier was wrong); the retained corpus cannot show the humidity/pressure repair (EF §4); two months of v3 captures now exist. `wind_group` dead in all 12; F-market pressure owed as a training drop. | Cheap, never done. |
| L12 | **The §1h PIT-field protocol** | Frozen, hashed, executable on the staged corpus; closed unused on a replay artifact; the mechanism "not tested in either direction" (EF §1h-§1j). Gate 3 must be replaced (EF §1k `-09-68a`). Decision 10 is retired; a new ledger row is needed. | Never executed. |
| L13 | **Tail re-split under a rank-based disagreement gate** | EF §1f caveat 3: the >=0.30 absolute gate mechanically favours high-probability bands; "re-run the position split … before building on the centre story". | Never done; costs nothing; no alpha. |
| L14 | **Batching of sub-3.2% improvements** | EF §1d: steps below the floor are individually unconfirmable and must be accumulated; never used. | Method only. |
| L15 | **Fixed-market, date-clustered inference for decisions** | FP item 7 (owner decision pending on the two-tier ship rule); changes what is confirmable (MG-1 prereg already uses it). | Owner decision pending. |
| L16 | **Re-derive the retired 74.97% centre-oracle ceiling** | Unciteable with no replacement (EF §1); needs a new estimator on the repaired surface. | Never done. |
| L17 | **The other ~7 silent no-op post-processing stages** | EF §10e: 13 of ~26 stages are no-ops; only the lock-ins and taper have been read and repaired. | Unmeasured. |
| L18 | **Item 337 no-METAR floor (Toronto) and Q-21 WU intraday vs summary** | Owner yes conditional on the host replay >= 10-15 (DL 10-13); Q-21 needs WU history back (OD15 route). | Pending. |
| L19 | **110g afternoon-centering stage** | Disabled pending "a separate measurement" (EF §2); reload status UNKNOWN. | Unmeasured. |
| L20 | **Own-information dispersion at usable power** | `-09-58a` blind; the fetch that made it blind has been run and staged (EF §1e). | Never re-run. |

---

## 4. Maker-pillar leads (brief)

- **Informed-fill fraction `f` is unidentified, not underpowered** — book deltas cannot distinguish cancels from
  executions; only forward own-account evidence answers it (EF §1b.3, §8c). Zero-edge break-even holds in 45.94% of
  scenarios at $0 reward, 88.99% at $1/band/day; viability is dominated by `f`.
- **No profitability result exists**: RE-1 realized net **-36.97 pUSD** over five fills and one paid reward day
  (+2.13 vs ~2.03 modelled, k ~ 1.05); the reward share model holds in scale; share halves within 2-4 minutes of
  posting; empty bands fill, contested bands require the depth rule (EF §10m; FD).
- **Fees**: weather takers pay `0.05 x p(1-p)` per share, makers 0, 25% of taker fees fund maker rebates — **no rebate
  has ever been received** (EF §10o). Public maker markout +0.19 c/share at 5 min, -0.43 c to settlement (item 330).
- **Reward pool** ~2,800/day same-day, ~4,800 all active; our share unmeasured; the 10 pUSD per-band cap makes a
  reward-eligible 20-share two-sided quote (~19.60) impossible and same-day bands flip to a 100-share minimum (EF §10a).
- **Cash is limited per market, not across markets** — simultaneous fills beyond cash are an unmeasured venue behaviour
  (EF §10n; OQ Q-12, Q-13).
- **The maker-P&L desk study is not powerable at delta = 1.0** (N_req = 706 event dates from a 4-date pilot;
  UNDECIDABLE_AT_DELTA; embargo end stays 11-13) (EF §10r, DL 10-14).
- **Timing**: station-specific METAR minutes (89b); METAR +-2 min pulls catch 1.18x the large moves of the best fixed
  clock on T+0 only; NBM/GFS/HRRR pulls <= baseline (OQ Q-07). The T+1/T+2 NWP-timing study is frozen awaiting 88a.
- **Critical path now**: maker replay v2 (signature 10-22..23, look by 11-15), forward paper shadow active 24/7,
  LFC session 0 on 10-14 (SOP).
- **Kill rules (FP)**: **K1** the best pull policy's net value per band-day has a date-clustered upper bound below zero
  -> stop the maker build, keep capture. **K2** median settled reward on T+1 bands at a fundable size below the owner's
  floor -> stop (floor unset; K2 inactive). **K3** once quoting, realized fill losses exceed twice the shadow
  prediction -> pause and re-derive. Plus the RE-1 stop rule.
- **Open questions**: Q-01..Q-07, Q-12, Q-13 all OPEN; Q-15/Q-22 answered.

---

## 5. Proposed exit criterion per row, in recommended order

Order principle: free reads on data we already hold first; then the registered forward reads; then one-source-at-a-time
increments with a pre-declared MDE at the 5% bar; then the expensive structural work. Rows marked **URGENT** are the
ones the bug fixes make stale.

| Order | Row(s) | Pre-registerable exit criterion | Cost | Flag |
| --- | --- | --- | --- | --- |
| 1 | L1 / rows 1, 2, 12 | **Re-arm a served-vs-market daily scoreboard** on all post-10-09 dates: per hour block, 12 markets, crossed and fixed-market intervals; positive control = reproduce §3's 1.6639 -> 1.4980 on its own pre-10-09 window to all printed digits. **Closes** when 45 countable dates are in and the per-block ratios are published with MDEs. It re-bases rows 1-2 and makes every later row interpretable. | free (data exists; learning lane unblock, OQ Q-11) | **URGENT** |
| 2 | L13 / row 8 | Re-run the §1f position split under a rank-based disagreement gate on the sealed panel, B and C reported separately; then recompute the tail definition on post-10-09 served output. **Closes** when the centre/shoulder share and AUROC are re-stated per stratum with the defect rows removed. | free, no alpha | **URGENT** |
| 3 | L11 / row 6 | Measure full free-source parity (humidity, F-market pressure drop, trends, `wind_group`) on captures since 08-08, paired, crossed; severe-tail SSE and pooled Brier with MDE. **Closes** when both intervals are reported; a tail SSE lower bound > 0 keeps the lever, else drop it as correctness-only. | low | — |
| 4 | row 15 | **Evening-fix scorer** as signed: window 10-16..10-27, one look 10-29, NEW vs OLD replay vs market at 17-23, materiality <= -5% of the window's OLD-minus-market gap; safety count zero. **Closes** on the read. | registered | **URGENT** (first post-fix evidence) |
| 5 | L2 / row 13 | **MG-1** as signed: 45 countable dates from D0 (after #190, 10-18), 00-16 primary, fixed-market joint rule. **Closes** on its single look. | registered | — |
| 6 | rows 3, 4, 5 | On the same >= 45 post-10-09 dates (one pre-registration, one look): (a) the 114-cell edge map, (b) the §1c recalibration bound (fit on odd dates / score on even, same four families, training score first), (c) the shrinkage locator per block. **Closes** when (a) has no cell with a lower bound > 0 across >= 20 dates and (b)'s upper bound is reported; any cell with lower bound > 0 reopens row 5. | low | **URGENT** |
| 7 | L12 / row 19 | Execute the §1h protocol on the staged 12-field corpus with Gate 3 replaced by a rate gate (crossed interval on the zero rate, not fail-on-any-row), new ledger row, q = 3.1098893. **Closes** when the primary and tail intervals are both reported; a NO_GO_UNDERPOWERED_EFFECT_FIELD verdict closes it as "untestable on this corpus". | medium (workstation) | — |
| 8 | L3 | HG-1 as a separate alpha arm on new dates after MG-1's D0, gate from the NBM schedule only (`captured_at_utc` < 12:00Z). **Closes** on one look. | low | — |
| 9 | L4 / S19, S20 | D2 (t3-r3) signed at the **full** effect with METAR freshness < 1 h as a validity condition, plus a 5-minute ASOS freshness arm pre-declared. **Closes** on one look; a VOID on freshness closes the rule as unservable. | low-medium | — |
| 10 | L6 | RV-1 (or T18) vs MG-1 on dates after MG-1's reservation, 00-16 and 17-23 with the lock-in on top. **Closes** when RV-1 - MG-1's interval excludes the 5% bar either way. | low | — |
| 11 | row 16 / S3, S5, S6, S10, S25 | One source at a time, paired increment over MG-1 on new dates, **MDE pre-computed at the 5% bar (~ -0.0012 at 00-16)**; a source with MDE above the bar is marked UNTESTABLE, not NULL. **Closes** per source when the interval excludes the bar. Order by cheapness: HRRR (already captured), ECMWF via Open-Meteo (already captured), GOES/cloud, MOS/NBE (IEM text, ~5-6 MB/month), NBH last (0.68 GB/day). | low-medium each | — |
| 12 | S13, S12, S11, S9-GEFS, S8, S32 (never opened) | For each: a 30-day captured shadow column, then the same paired increment test. **Toronto first with GEM/HRDPS**, because it has no NBM and has never had a guidance control. **Closes** per source as in order 11. | medium | — |
| 13 | S18, S21, S26, S29, S31 | Owner decision whether to open at all (AFD text, mesonets/PWS, radar, ML models, other venues' prices). Each needs a stated mechanism and a no-source control before capture (OQ Q-20 rule). **Closes** by owner decline or by order-11 test. | owner call | — |
| 14 | L8 | T+1/T+2: a day-2 NBM v2 read vs the 88a T+1 book mid, market-only first (frozen 10-02 study), then forecast-vs-market under a new prereg once >= 20 T+1 dates are captured. **Closes** on the registered looks. | medium (after 88a freeze) | — |
| 15 | L7 / row 24 | A season-matched retrain lane run end to end once (temperature PIT all years + 12 fields 2024-2025, §4g exclusion list, PIT file read by the trainer), scored on a pre-registered out-of-season stratum against the frozen artifacts; the §1d 24.9% proxy is the prior. **Closes** on one look; a null closes "retrain as the lever". | high | — |
| 16 | L17, L19 | Read one served stage vector per remaining no-op stage; emulate repairs as in §10q; confirm the 110g reload state. **Closes** when each stage is either shown inert or repaired and scored. | low-medium | — |
| 17 | L9 | Foreign cities: capture + settlement alignment per Q-14 before any forecast claim; no exit criterion is definable until a model exists. | high | — |
| 18 | §4 maker rows | Maker replay v2 signed -> shadow -> K1/K2/K3 as written in FP; K2 needs the owner's floor. **Closes** on the kill rules or on a powered P&L read (which the 10-14 power rule says needs ~706 event dates at delta 1.0 — so set a larger delta or a different estimand first). | on the critical path | — |

**What "as nearly as possible" would then mean.** After orders 1-12, every free source that plausibly carries
same-day information for the 11 US markets will have either a precise null at the 5% bar or a registered forward
read, Toronto will have had its first guidance control, and the served model will have a post-fix gap figure at every
hour. The three things no amount of this can settle are structural and already written down: the 3.2% MDE floor set
by 12 market clusters (EF §1d), the in-season figure that cannot be re-measured before May 2027 (EF §4b), and the
maker-side `f` that only own-account fills identify (EF §1b.3).
