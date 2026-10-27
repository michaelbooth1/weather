# Exhaustion register

Status: canonical living register. Created 2026-10-14 from a Fable-drafted read-only audit, with its citations
checked against the docs, config and code at `c2771ab02`. Nothing here is a new measurement; every number is quoted
from its owning section and cited. **The owner keeps the no-go decision personally.**

- **Owns:** the list of things that must be exhausted before anyone may say, as nearly as possible, that we cannot
  match or beat the market from free information. For each item it holds the verdict on whether earlier conclusions
  survive the serving-bug fixes, the free-source inventory, the open method leads, and one exit criterion with a
  closing test and an owner/due date.
- **Read when:** proposing a no-go, a "this is closed" or a "nothing left to try" claim; choosing the next research
  mission; re-citing a pre-10-09 gap number; deciding whether a data source has been tried.
- **Do not use for:** the measured results themselves (the [findings digest](FINDINGS_DIGEST.md) and established
  findings own them), unanswered questions in general ([open questions](OPEN_QUESTIONS.md)), owner decisions
  ([decision log](DECISION_LOG.md)) or today's state ([state of play](STATE_OF_PLAY.md)).
- **Update when:** a row's closing test reads out (set its verdict or status and cite the EF/RF section the result
  moved to); a source is captured, scored or declined; a serving defect is found or repaired (re-run §1 for the
  measurements it touches); an owner/due changes. Rows are never deleted; a closed row says how it closed.

Abbreviations: "EF" = [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md), "RF" =
[RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md), "FD" = [FINDINGS_DIGEST.md](FINDINGS_DIGEST.md),
"OQ" = [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md), "FP" = [forward-plan-2026-09-23.md](forward-plan-2026-09-23.md),
"SOP" = [STATE_OF_PLAY.md](STATE_OF_PLAY.md), "DL" = [DECISION_LOG.md](DECISION_LOG.md),
"SYN" = [the model-parity swarm synthesis](../research/model-parity-swarm-2026-10-04/SYNTHESIS.md),
"FREE audit" = [the free weather data-source audit](../research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md).

The owner's question (2026-10-14 ~16:30 EDT, relayed by master-agent): "how do we really know we can't match or beat
the market? We recently served a bug fix wouldn't that taint a lot of our previous tests? And have we exhaused all
leads on new data sources? [...] When I say exhausted all options I want mean it as close as possible". Two challenges
drive the register: (1) whether the recent serving-bug fixes taint the earlier "model does not beat the market" tests;
(2) whether free data sources have really been exhausted.

---

## 0. The defect timeline the whole register depends on

### 0.1 Corrections made when the register was created (2026-10-14)

| Commonly assumed | Docs and code say | Source |
| --- | --- | --- |
| The late-day lock-in repair is "not yet served" | **It is served.** lockin-anchor-v3 (#191, `ML_MODEL_VERSION` v0.5.11) reached `master` on **2026-10-06** (`094f5b393`). The M0 METAR observation-time keying fix (#189) and lockin-anchor-v4 (#246, v0.5.12) landed in N3, which reached `master` as `6ad52c89f` on **2026-10-09 01:20 EDT**. The **scorer** is not landed: `claude/evening-fix-scorer-20261013` @ `8cdcb62ec` must land before 10-28, and its first and only read is 2026-10-29. The prereg's "live since N3 merge night" (§0.1) disagrees with its own table, which lists v3 as a separate 10-06 merge. | evening-fix prereg §0.1, §0.2, §7 (`docs/research/evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md`); `git show 6ad52c89f^1:src/weather/model/model_constants.py` (v0.5.11); DL 2026-10-05, 10-06, 10-08, 10-13 rows |
| Lock-in defect "live since about 2026-06-30" | Confirmed. `PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False` came in commit `5735b573a` on 2026-06-30 and is still set (`src/weather/model/model_constants.py`). All five late-day lock-ins and the calibration taper received `None` from then until the v3 re-anchoring on METAR (10-06). | EF §10e, §10q |
| NBM parser defect found 09-21 (`-09-82a`) | Confirmed. The repair (parser v2, `-09-83a/b/c`) **lands 10-18** (#190, owner 10-13). The served headline model selects **no NBM column**, so served output was never affected; only the promotion-blocked shadow variant and the guidance *candidates* were. | EF §10k, §10l, §10h; SOP "Model" line; DL 2026-10-13 |
| Serving floor 2026-07-31 | Confirmed (served ratio 1.6639 -> 1.4980). | EF §3 |
| Blind-feature repair | Confirmed. The routing defect ran from 06-30 and was repaired 2026-08-08 (`-09-43a`), with 9 of 10 fields routed. `pressure` and `pressure_trend_3h` stay dead in the 11 F markets by design; `wind_group` is dead in all 12 (owed). | EF §4 |
| WU live inputs disabled 2026-06-30 | Confirmed (same commit as above). The **served** WU history fetch is still disabled: `fetch_wu_history` calls `paid_weather_provider_disabled("wu_history")` (`src/weather/model/model_sources.py`). | EF §4, §10e |
| 2026-07-31 provenance boundary | Confirmed. It is artifact provenance, with anchor commit `b77cfbed` (2026-07-30), and never a date cutoff. | EF §5; RF §2 |
| Non-committed served bytes | Confirmed. Only 89 of 413 captured fingerprints match a reachable blob, and 0 of 368 decision rows are exactly reconstructable. This is a replay-trust defect, not a served-quality defect. | EF §1k (`-09-76a`) |

Two further defects matter for taint:

- **M0, METAR rows keyed by AWC `reportTime`.** A D-1 23:5x report entered day D's running max on 0.3-0.6% of
  station-days Aug-Sep (2.2% Oct-Dec, up to 5.4% at KLGA). It was fixed in N3 (#189). It corrupted the *floor* used
  by 79a/81a/111h/swarm candidates on those station-days. EF §10q.
- **The afternoon residual-centering artifact (110g).** Its contexts were fitted in-sample in June on a pipeline not
  served since 06-30. The owner decided to disable it on 2026-09-25 (EF §2). The switch
  (`artifacts/misc/afternoon_residual_centering.json`, `"enabled": false`, artifact commit `481eabf4d`) reached
  `master` on **2026-09-28 01:22** in `fbf4d436c`, a roll-sensitive merge.
  - **Reload: done.** The loader reads the artifact every time the model is constructed (`docs/architecture.md`;
    `toronto_model.py`). No release pointer is bound on the host (release case A,
    [the upgrade runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md) G6), so the global artifact is the one served. The
    roll-sensitive merges of 10-06 and 10-09 recreated the workers in any case.
  - The direct activation receipt is runtime data under `data/` (cited by `docs/roadmap/work/W-0004.yaml`, still
    `verified: false`). The register did not read it.

### 0.2 Defect timeline (what was live when)

| Defect | Live from | Live until | Hours / rows it touches | Owner section |
| --- | --- | --- | --- | --- |
| Served realized-band zeros (serialization) | before 2026-06-15 | commit `28d1c146`, 2026-06-15 | 8.486% of F rows before; 0 after | EF §1k (`-09-68a`); RF |
| WU live history/current disabled -> 10 of 19 features imputed | 2026-06-30 | 2026-08-08 (`-09-43a`; 2 F-market fields and `wind_group` still dead) | every hour, every market | EF §4 |
| Late-day lock-ins (5 stages) + calibration taper no-op | 2026-06-30 | **2026-10-06** (v3 on `master`, `094f5b393`); v4 floor + M0 on **2026-10-09** (N3) | 17-23 local mainly; S3-S5 cover 13-19 h | EF §10e, §10q |
| Replay floor rebuilt, not recorded (replay instrument only) | always (replay) | n/a | B: 81.132% of comparable rows differ from served; C: 0% | EF §1k (`-09-65a`, `-09-66a`) |
| `high_so_far` not a running max (WU series drops rows) | WU-live period (pre 06-30) | moot after 06-30 (WU dark); unrepaired | B: 906 falls, 40.62% in peak/settlement window | EF §1k (`-09-70a`..`-09-73a`) |
| Serving floor defect (pre-fix) | before 2026-07-31 | 2026-07-31 | evening mostly (2.2% of the gain landed 09-14) | EF §3 |
| Training contamination (`forecast_high` not PIT) | all fits (June) | unrepaired; priced as not the lever | fit-time only | EF §6, §0a |
| NBM parser v1 reads next-morning minimum after 13Z | always (capture) | parser v2 lands 10-18 | 67% of captured NBM rows; served model unaffected | EF §10k, §10l |
| M0 METAR `reportTime` keying | always (capture) | 2026-10-09 (#189) | 0.3-0.6% station-days Aug-Sep | EF §10q |
| Afternoon residual-centering contexts stale (110g) | 2026-06-30 (pipeline change) | 2026-09-28 (`fbf4d436c`; disabled and reloaded, §0.1) | afternoon centre | EF §2 |
| `trusted_current_max` null on 100% of extract rows; 31 rows with floor 10 F above METAR max | Aug-Sep extract | UNKNOWN | floor mask | EF §10q |
| Served bytes never committed | through at least 2026-08 | **not closed**: N3 bound no immutable release (host release case A); MG-1 substitutes per-row release-bind hashes (DL 2026-10-08) | replay reproducibility only | EF §1k (`-09-76a`) |

### 0.3 Which panels carry which defects

| Panel | Dates | Hours | Instrument | Defects live |
| --- | --- | --- | --- | --- |
| **B** in-season sealed pre-boundary | 23 dates, 05-27..06-30 (front segment 06-03..06-23 is 21 of them), 204 market-days, 4,636 snapshots | all | **replay** on captured inputs (not served output) | replay floor divergence (cosmetic in mean, 0.57% of gap); `high_so_far` falls; 28 inherited zeros (2.6% of G); blind features in the control arm; contamination. **WU was live, so the lock-in stages had inputs: the evening defect is NOT in B.** |
| **C** out-of-season sealed pre-boundary | 27 dates, **07-01..07-30**, 320 market-days, 7,653 snapshots | all | replay | **All 27 dates are after 06-30, so the lock-in/taper no-op is in C**, in every all-hours and every 17-23 number; blind features (control arm); 1 inherited zero. |
| Floor-fix pre/post panel | D=8, M=11, 85 market-days (exact dates not stated in EF §3) | all | served snapshots | lock-in no-op in both arms; blind features in both arms |
| 79a served surface | targets 08-01..09-19, 503 market-days, 12 markets | served output | lock-in no-op (17-23, and S3-S5 at 13-19); blind features 08-01..08-07; M0; 110g centering live; parser v1 in the *candidate* only |
| 111h / swarm table | targets 08-01..09-29, 626 market-days, **11 US markets (no Toronto)**, 110,807 snapshots | served output + parser-v2 extract | lock-in no-op in the served arm (the swarm *emulated* its repair as rung r1); M0 in the floor; 110g centering live to 09-28 |
| Workstation research lineage (§1m) | 2024-2025 Previous Runs corpora; 2026 06-03..08-09 | point-forecast regression | not the served model at all; `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN` |

Stratum dates: `docs/roadmap/agent-report-2026-08-06-workstation-seasonal-distance-two-stratum.md`.

**The standing caveat on every "served" headline number from the sealed panel:** §1's 1.423246x is labelled "served",
but `-09-44a`'s paired replay produced it (control "re-run rather than read", EF §4), and replay does not reproduce
served output (0 of 368 decision rows exactly; EF §1k). The only numbers measured on literally served output are §3,
`-09-66a`, §10h/§10j/§10p and the swarm table.

---

## 1. Which conclusions survive the bug fixes

Verdict key:
- **STANDS:** the conclusion holds for the thing it measured, and nothing landed since changes it.
- **TAINTED:** the number or claim includes a now-repaired defect and must be re-measured before anyone re-cites it.
- **PARTLY:** the verdict text says which part.

"Re-measure" names what would settle it.

| # | Claim (FD line) | Measured when / on what | Known defects live in what it measured | Verdict | What re-measurement would settle it |
| --- | --- | --- | --- | --- | --- |
| 1 | **Gap to market, in-season, 1.423246x [1.2426, 1.6590]** (EF §1, §4, `-09-44a` 2026-08-09) | Replay on stratum **B** (23 dates, 204 md), repaired input surface (the routing-repaired arm), paired control re-run; "served" label, replay instrument | Replay floor divergence (cosmetic, 0.57% of gap, `-09-66a`); `high_so_far` falls on the decision path; inherited zeros 2.6% of G; contamination. **Not** the evening no-op (WU live in June). Blind features: both arms measured, null. | **STANDS** as the in-season gap of the frozen artifacts. **TAINTED as a description of the model served today.** The served path has changed three times since: floor 07-31, 110g disable 09-28, lock-in v3 10-06 / v4 + M0 10-09. No served-vs-market ratio exists for the post-10-09 path at any hour. The last served-output read (Aug-Sep, 11 US markets) was 1.73x all-hours with the defect live, and ~1.34x with the fix *emulated* (development, EF §10q ladder). EF §10p prints 1.77x for a related all-hours figure, so EF disagrees with itself here. | A served-vs-market ratio on new dates after 10-09, per hour block, with crossed and fixed-market intervals, 12 markets. In-season (May 10 - Jun 30) cannot be re-measured before 2027; out-of-season can start now. |
| 2 | **Out-of-season gap 1.526x -> 1.542x; "we serve out-of-season"** (EF §1b.4, §1c) | Replay on stratum **C** (07-01..07-30) | **Evening no-op on all 27 dates** (the all-hours ratio includes 17-23 defect loss); blind features (control arm) | **TAINTED** (the number). The structural point **STANDS**: the archive is May 10-Jun 30, so August onward is out of season (EF §4b). | Same as row 1, out-of-season stratum, after 10-09. |
| 3 | **Recalibration bounded at 16.494% of the gap, not distinguishable from zero** (EF §1c, `-09-56a`) | Fit on B, score on **C**; four leakage-safe monotone families; power 0.458, MDE 13.3pp | C carries the evening no-op: mass above a known high on 17-23 rows is the defect itself, and it inflates the gap denominator. Blind features in the surface. | **PARTLY.** "Calibration is not the workstream" very likely survives: neither landed repair is a monotone map, and the §10q ladder still leaves 00-16 at 1.29x after both repairs. The **number** (8.829% / 16.494%) is a property of the defective surface; do not re-cite it for the post-10-09 path. | Repeat the §1c design on post-10-09 served output: fit on one half of new dates, score on the other, same four families, training score checked first. |
| 4 | **Shrinking toward the market closes 65.1% of the gap on the disagreement set; full replacement 85.6%** (EF §1c) | C stratum, rows with \|model-market\| >= 0.30 | Evening-defect rows that meet the gate are disagreement rows where the market is right | **TAINTED in magnitude.** The method rule **STANDS**: shrinkage is a measurement, never a candidate. | Re-run the shrinkage controls post-10-09, only as the locator of missing information, separately per hour block. |
| 5 | **114 pre-registered cells, zero with a positive point estimate; overall edge -0.01915 [-0.02444, -0.01443]** (EF §1b.2, `-09-46a`) | **B and C pooled**: D=50, M=12, 524 md, 12,289 snapshots, 06-03..07-30; the stratum is a cell dimension (`docs/roadmap/quotable-edge-preregistration-2026-09-46a.md`); positive control 840/840 | The evening no-op sits in every C cell (all after 06-30), at 17-23 and in all-hours cells; B cells are clean of it | **PARTLY.** The structure, "we match the market only where we already agree with it", is corroborated on served output: by §10h (morning 1.44-1.48x before any evening hour) and by §10q (00-16 still 1.29x after both repairs). The **per-cell map** of the C cells is tainted, especially 17-23 and the disagreement cells. "Model-skewed quoting is retired" **STANDS** until a post-fix cell shows a lower bound above zero. | Re-run the 114-cell map, pre-registered, on post-10-09 served output over >= 45 countable dates, one look. |
| 6 | **Input repair did not move the gap (precise null, 1.423260 -> 1.423246)** (EF §4, `-09-44a`) | Paired delta on identical rows, D=50 both strata | Shared defects cancel by pairing. The full repair (humidity, F-market pressure) is "unmeasurable until v3 parsers have been capturing for a while" (EF §4). | **STANDS** for what it measured. **Not exhausted:** RF says "full free-source parity has never actually been measured". Toronto ECCC fields were absent from `-09-26a`, and two months of v3 captures now exist. | Measure the full free-source parity (humidity, pressure, trends) on captured data since 08-08, paired, crossed, with a severe-tail endpoint. |
| 7 | **Cool bias -0.64387 C-eq; seasonal coverage root cause (B -0.18 vs C -1.02, contrast -0.8346 [-1.4378, -0.2159])** (EF §2) | Base-HGB centre vs settlement, D=50 replay | The base HGB centre is pre-lock-in, so the evening defect does not enter. The 110g centering is disabled in the served artifact since 09-28 (§0.1). | **STANDS** for the frozen June artifacts (unchanged since the fits of 06-10..06-13). The served October centre is unmeasured; the bias is a function of seasonal distance, so its current value is UNKNOWN. | A served centre-vs-settlement read on post-10-09 dates, by market (heterogeneous by design, EF §2). |
| 8 | **Loss concentrated: 4.387% of band rows carry 64.140% of excess; tail = centre overconfidence, AUROC 0.90260** (EF §1, §1f) | D=49-50 both strata, 5,930 tail rows | Evening-defect rows that meet both gates (served SE > market SE and disagreement >= 0.30) are tail rows. On the Aug-Sep table the tail carries 90.4% of the 17-23 excess, and the lock-in restoration alone removes 84.4% of that tail (SYN §4). | **TAINTED.** The concentration figure, the centre/shoulder split and the AUROC all include defect rows from C. The in-season B part is clean, but EF does not report it separately. EF §10q (the "in-season panel's figure") and EF §1/§1f (D=50, both strata) disagree about which panel the 4.387% / 64.140% comes from. | Recompute the tail definition, concentration and the §1f predictor on post-10-09 served output. Also run the never-done §1f caveat-3 check (rank-based disagreement gate). |
| 9 | **Conditional reshaping loses to global smoothing on its own training score; distribution reshaping closed** (EF §1g, `-09-60a`) | **B only** (in-season) | None of the serving defects (B ends 06-30); replay floor | **STANDS** for B. Its "whole family capped by §1c's bound" leg is **PARTLY** (inherits row 3). | Nothing cheap; re-derive after row 3 is re-measured. |
| 10 | **Centre not width; never sharpen globally; never weaken the floor** (EF §1, §2, §1g) | B (beta=0.55 < 1); the floor absorption interval excludes zero | Same as row 9 | **STANDS**. | — |
| 11 | **Serving floor moved the served ratio 1.6639 -> 1.4980 [-0.3553, -0.0698]; ~2.2% in 09-14** (EF §3) | Served snapshots, D=8, M=11, 85 md (dates not stated in EF §3) | Lock-in no-op and blind features in both arms | **STANDS** as a record. **As the "positive control for any skill tracker"**, it is now reproducible only on pre-10-09 data. The evening serving path changed on 10-06/10-09, so a tracker must be validated on the pre-fix window, not on today's output. | Re-base the positive control: reproduce §3 on its own dates, then run the tracker forward. |
| 12 | **The gap is already there in the morning (1.44-1.48x at 06-09) and widens intraday** (EF §10h) | Served surface 08-01..09-19, 12 markets | M0 (0.3-0.6% of station-days); blind features 08-01..07; 110g centering live; lock-in no-op (17-23, plus S3-S5 at 13-19 h, so the morning figure is clean) | **STANDS** for mornings. The 13-16 figures (1.789 / 1.715) carry a small lock-in effect (restoration moves 13-16 by -0.0006, S3-S5 by -0.0020; EF §10q) and the live 110g centering. | A post-10-09 per-block ratio (row 1). |
| 13 | **Raw NBM read beats served by 0.012-0.015 Brier in the morning, still 1.15-1.22x market; halves to -0.0067 on every row; not confirmable at any season length under crossed clustering** (EF §10h, §10j) | Served surface mornings; parser v1 rows that passed the floor (mostly genuine 01Z/07Z maxima); 111h census: 81 of 7,031 eligible 06-09 rows (1.15%) used a wrong-period minimum (EF §10p) | Parser v1 (small, counted); M0. The power cap is structural (11 US clusters). | **STANDS**. The "any season length" cap is a property of the crossed rule. FP item 7 proposes fixed-market inference for decisions; under it, the signed MG-1 prereg reaches 0.80 at 45 dates at the half effect (SYN §8). | MG-1 forward read: signed `b044e0f1`; D0 >= the first countable date after #190 lands 10-18; 45 countable dates. |
| 14 | **NBM at all hours closed: pooled -0.000924 [-0.006083, +0.003924]; afternoon harm 13-16 +0.0060, 17-23 +0.0155** (EF §10p, `2026-09-111h`) | 111h table, parser v2 extract, served arm with the lock-in defect live | The 17-23 harm is measured against a *defective* served arm. Post-fix, the served arm improves by -0.0252 there (EF §10q), so stale whole-day guidance would look worse still. At 13-16 the restoration moves served by only -0.0006 (S3-S5 by -0.0020; EF §10q). | **STANDS**: the fix strengthens the closure rather than weakening it. An hour-gated candidate remains open and may not pick its hours on this table. | HG-1 as its own alpha arm on new dates (SYN §8). The owner held it until the evening fix was live, which it now is. |
| 15 | **Two serving repairs close 54% [35, 70] of the Aug-Sep gap (1.73x -> 1.34x); evening is a serving defect, cosmetic for the maker** (EF §10q) | Development on already-read dates; band-level **emulation**, not replay; 11 US markets | M0 in the floor. The emulation anchor was superseded: max(history_max, guidance_floor) became the v3 observed same-day high (RF 2026-10-05). The v3 replay (<= 09-29) checked floor safety, not Brier. | **STANDS as a development read; not yet confirmed on any new date.** The v3/v4 rule actually served differs from the emulated rung, so the 85% figure is a prior, not a prediction. | The signed evening-fix scorer: window 10-16..10-27, one look 10-29, NEW vs OLD replay against market, 17-23 primary (prereg §2-3). |
| 16 | **No external free source adds information beyond captured NBM v2 plus the two repairs** (EF §10q; RF "Capture NBH … false lead") | Same table. Increments are measured over the MG-1 / no-source controls **with rung r1 already emulated**, so the evening taint is handled by construction. | M0; emulation; 11 US markets, one season (Aug-Sep); hunter-chosen candidate forms. The intervals **do not exclude the 5% bar**, which is block-specific (about -0.0012 at 00-16, -0.0013 at 06-09, -0.0011 at 10-12; SYN §1.1): NBH +0.0027 [-0.0037, +0.0098] (EF §10q); MOS/NBE -0.0015 [-0.0049, +0.0019]; ECMWF +0.0031 [-0.0025, +0.0091]; HRRR latest 06-09 -0.0005 [-0.0058, +0.0039]; GOES 10-12 -0.0011 [-0.0026, +0.0002], **vs served**, not over MG-1 (all SYN §1.3). Only NBS is a precise null at 00-16: +0.0003 [-0.0004, +0.0011] (SYN §1.3). | **PARTLY.** "No increment was *demonstrated*, and there is no capture case on this evidence" **STANDS**. "No increment *exists*" is **not established at the 5% bar** for NBH, MOS/NBE, ECMWF, HRRR and cloud. It is established for NBS (00-16) and, by placebo, for NWS revision direction. Nothing was tested for **Toronto** (no NBM there) or outside Aug-Sep. | A per-source paired increment over MG-1 with a pre-declared MDE at the 5% bar, on new dates, with fixed-market inference. Toronto needs its own control (no NBM). |
| 17 | **The 11/12 extra free PIT fields are tested, not untested: NWP-anchored residual +0.2751 C^2 [-0.0234, +0.6186], INCONCLUSIVE_UNDERPOWERED x3, never harmful; pooled refit worsened the centre** (EF §1m; RF "stale since 09-02") | Workstation research lineage 2026-09-01..04 (unmerged); point-forecast regression on an NWP anchor; 2024-2025 and 2026 pre/post; research baseline Brier 0.0779 (not served) | **None of the serving defects** (it is not the served model). The corpora carry `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`. | **STANDS** as TESTED-UNDERPOWERED (powers 0.06-0.39). Spent evaluations may not be reused. The preflight (`codex/48h-residual-preflight-20260911`) was built but never executed. | A new pre-committed design on unspent years (the settled 2026 season, then 2027); OQ Q-16. |
| 18 | **No free source satisfies the v2 point-in-time contract** (EF §1m, research 82a) | Documentation review only (no provider called) | n/a | **STANDS** as a *contract* property. It does not say the Previous Runs corpora are unusable for research; they were used three times (row 17). | Only provider-owned availability evidence (OQ Q-17 CLOSED). |
| 19 | **Own-information dispersion signals: blind null (power ~0.11), PIT source stopped 2026-06-23** (EF §1e, `-09-58a`) | B, 11-14 date clusters after warm-up | None of the serving defects. The thinness came from the PIT fetch, which was then re-run and **staged, not adopted** (1,645,056 rows, 12 fields x leads 1-7, 06-03..08-09). | **STANDS** as blind. **Not exhausted:** the re-fetched corpus has never been used to re-run the screen. The §1h protocol (12 named features, frozen, SHA `336150be…`) was **closed unused** because Gate 3 fired on a replay artifact: "the surface-heating mechanism was not tested in either direction" (EF §1j). | Execute the §1h protocol on the staged corpus with Gate 3 replaced (EF §1k `-09-68a`: never re-register it unchanged). Decision 10 stays retired, so this needs a new ledger row. |
| 20 | **Training contamination is not the lever: B - A = -0.000107 [-0.001588, +0.001349], power 0.066** (EF §6, `-09-42a`) | A/B/C fit on the 09-14 primary and all hours | n/a (fit-time) | **STANDS** as "not demonstrated". It is underpowered, so it does not prove the PIT file is worthless. | Fold into any retrain lane (row 24) rather than testing it alone. |
| 21 | **The gap does not vanish in-season; served in-season 1.4233 [1.2428, 1.6589], base lane 1.7466** (EF §4e) | B/C seasonal-distance corpus | B clean; C carries the evening no-op (out-of-season rows only) | **STANDS** for in-season B. | Row 1. |
| 22 | **The instrument is sound: repair adds no zeros, served floor cosmetic in the mean, labels flat (ceiling ~13%)** (EF §1k `-09-64a`..`-09-67a`) | B and C | Checked one by one; none explains the gap | **STANDS**. | — |
| 23 | **Replay does not reproduce served output; never commission reproduction** (EF §1k `-09-74a`..`-09-76a`) | Decision stratum B, 368 rows | Non-committed bytes | **STANDS**. No release binding closes the commit-discipline defect going forward: N3 bound no immutable release (host release case A), and MG-1 uses per-row release-bind hashes instead (DL 2026-10-08). | Not a forecast question. A forward check that today's served fingerprints resolve to `master` blobs. |
| 24 | **Retrain: archive covers May 10 - Jun 30; season window blocks it; 14 cells unfillable; the PIT wall is 9 of 21 fields** (EF §4b, §4g, §0a, §4f) | Production archive, probes 2026-08-07/09 | n/a | **STANDS**. **Not exhausted:** no retrain has ever completed (`base_retrain` reached preflight once, EF §4a-bis). The §1d season-matched refit proxy reads 24.893% [-20.5%, +55.2%] of the out-of-season gap; it is unpowered and was never tested as a candidate. **Waived for the 12-21 decision (owner 2026-10-21, DL row 2026-10-21 "Retrain under the programme"); best case a futility-only R0 from 11-17** ([item 339](../roadmap/items/item-339-edge1-model-edge-preregistration.md)). | A season-matched retrain on temperature PIT (all years) plus the 12 fields (2024-2025) with the §4g exclusion list, scored under a pre-registration on the C-type stratum. |
| 25 | **13 of ~26 serving post-processing stages are no-ops since 06-30** (EF §10e) | Code trace; 28 served payloads read for the lock-in/taper | The lock-ins and taper are now repaired (10-06/10-09) | **STANDS** for what was read. The forecast consequence of the **other ~7 no-op stages** was never measured and is **UNKNOWN**. | One served stage-vector read per remaining no-op stage, then a paired emulation as in §10q. |
| 26 | **Primary objective (09-14) has no powered measurement; ~504 withdrawn; 3.2% MDE floor from 12 market clusters** (EF §1b.1, §1d, §5) | Design simulations on the sealed cluster structure | n/a | **STANDS** (structural). | Only more markets, a paired design or batching can change it (EF §1d). FP item 7 (fixed-market inference) changes what is confirmable. |
| 27 | **Blending the model with the market hurts (older clean-regime panel)** (EF §1) | Older panel, clean regime, global blend | Unknown older-surface defects (pre-06-15 zeros possible) | **STANDS only for its panel**. EF §1c's citation hazard already fences it from row 4. | — |
| 28 | **T+1/T+2: the served model has no output; the tape is T+0 only** (FD; t12 prereg §Premises) | Code and 293 event folders | n/a | **STANDS**: nothing about T+1/T+2 forecasting has ever been measured. | See §3 lead L8. |

**Count (28 rows):**

| Verdict | Number | Rows |
| --- | --- | --- |
| TAINTED | 3 | 2, 4, 8 (rows 2 and 4 keep a STANDS leg) |
| PARTLY | 3 | 3, 5, 16 |
| Split STANDS/TAINTED | 1 | 1 |
| STANDS | 21 | 6, 7, 9-15, 17-28 (row 9 has a PARTLY leg) |

An explicit "Not exhausted" note is on 3 rows (6, 19, 24). Rows 15, 17, 23 and 25 flag open work in other words.

**What the taint is and is not.**
- The evening no-op entered every measurement that pooled 17-23 hours on dates after 2026-06-30, plus the 13-19 h
  stages S3-S5 to a small degree. That covers stratum C, every all-hours served read from August on, and every tail
  statistic that includes C.
- It did **not** enter the in-season B figures (WU was live in June). The central conclusion, "1.42x in-season,
  information not calibration", is intact for June.
- The NBM parser defect touched no served number.
- What the fixes do create is a **gap in the record**: there is no served-vs-market number for the path served since
  10-09. The one development estimate of it (1.34x all-hours, 1.29x for 00-16) still sits well above parity.

---

## 2. Free data-source inventory

**Scope.** The 12 served markets are **11 US** (Atlanta, Austin, Chicago, Dallas, Denver, Houston, Los Angeles, Miami,
NYC, San Francisco, Seattle) **plus Toronto**. The venue lists 51 cities in `config/locations.json`. The foreign WRH
cities (London, Paris, Seoul, Shanghai, Tokyo) and Hong Kong are venue markets with a known settlement source
(EF §10c). They have **no served forecast, no capture of guidance, and no test of anything**. OQ Q-14 is the capture
census; Taipei and Jinan were its "ingest-now" picks. Every row below is therefore NOT TESTED for the foreign cities.

**Served consensus composition** (`src/weather/model/model_features.py`, `model_sources.py`). The served
`forecast_source_count` / `forecast_disagreement` consensus is the median of these votes:
- `open_meteo` best_match;
- `eccc_citypage`;
- `nws_hourly`;
- `global_ensemble` (Open-Meteo ensemble, `gfs_seamless`, i.e. GEFS);
- `open_meteo_global_models`: ECMWF IFS, ECMWF AIFS, NCEP AIGFS and GFS GraphCast, as one clustered vote.

The US multimodel feed (GFS seamless, HRRR, NBM, NAM) feeds diagnostics only.

**Binding constraints:**
- no paid provider (EF §6; AGENT_CONTEXT);
- train/serve point-in-time parity (EF §0a, §4f);
- any "improvement" must clear the 3.2% floor and be pre-registered (EF §1d, §5).

**Status key:**

| Status | Meaning |
| --- | --- |
| TESTED-NO-INCREMENT | The interval excludes the 5% bar, or a placebo beats it. |
| TESTED-UNDERPOWERED | The interval includes the bar ("null" in the swarm's words, but not precise). |
| TESTED-DEV-LEAD | A development lead awaiting a forward read. |
| CAPTURED-NOT-SCORED | The data reaches the host (often inside a pooled consensus vote), but its own increment was never scored. |
| BLOCKED | Blocked by PIT, parity or history. |
| NOT TESTED | Never scored. |

| # | Source | US 11 | Toronto | Status and citation | Notes |
| --- | --- | --- | --- | --- | --- |
| S1 | **NBM v2** (NBP text bulletin, parser-fixed, captured) | yes | **source covers CYYZ; not captured** (production's NBM capture is US-only; "none for Toronto" in EF §10h is capture fill, not coverage: RF "Toronto has no NBM", [lever inventory](LEVER_INVENTORY_2026-10-26.md) F1) | **TESTED-DEV-LEAD**: MG-1 zero-parameter read 00-16 -0.0100 [-0.0179, -0.0035], 10/11; still 1.29x after both repairs (EF §10q). Forward prereg signed (`b044e0f1`); D0 after #190 lands 10-18. | The served model selects no NBM column. From 12Z the newest bulletin holding today's max is 07Z, so afternoon guidance is 5-24 h old by construction (EF §10l). |
| S2 | NBM hour-gated (HG-1) | yes | no | **NOT TESTED**. Rule 8 forbade picking hours on the table; the owner held it until the evening fix was live, which it now is. | SYN §8 D-HG; needs its own alpha arm. |
| S3 | **NBH** (hourly blend) | yes | source covers CYYZ; not captured ([lever inventory](LEVER_INVENTORY_2026-10-26.md) F1) | **TESTED-UNDERPOWERED, wrong sign**: 00-16 increment over MG-1 +0.0027 [-0.0037, +0.0098], 5/11 (EF §10q; SYN §1.3; RF) | Declined for capture (DL 10-04). The interval includes the -0.0012 bar. |
| S4 | **NBS** (short-range blend) | yes | source covers CYYZ; not captured ([lever inventory](LEVER_INVENTORY_2026-10-26.md) F1) | **TESTED-NO-INCREMENT** at 00-16: +0.0003 [-0.0004, +0.0011] (SYN §1.3) | The one precise null among the sources. 13-16 fails Bonferroni and LOMO. **2026-10-26 ([lever inventory](LEVER_INVENTORY_2026-10-26.md) F2):** the null is a zero-parameter, pooled 00-16 read; NBS TXN inside P3d_N at 07-12 is untested (lane L12 fetch), with a low prior. |
| S5 | **MOS / NBE** (MAV/MET/MEX/LAV + NBE; MET is NAM-MOS) | yes | no | **TESTED-UNDERPOWERED**: 00-16 -0.0015 [-0.0049, +0.0019]. 13-14 -0.0063 [-0.0119, -0.0006] is post-hoc and not an increment over t3-r3 (-0.0031 [-0.0077, +0.0017]) (SYN §1.3) | ~90% of its morning gain is the captured-v2 control. |
| S6 | **HRRR** single run (production captures `hrrr_high`, latency ~2.5-3.5 h) | yes | grid contains CYYZ; not captured for Toronto ([lever inventory](LEVER_INVENTORY_2026-10-26.md) F1) | **TESTED-UNDERPOWERED**: HRRR-latest 06-09 -0.0005 [-0.0058, +0.0039], 3/8 (SYN §1.3); 79a error kernel 1.308/1.251x market (EF §10h) | The served model selects no HRRR column (EF §10h). |
| S7 | HRRR multi-run / time-lagged ensemble | yes | no | **TESTED-UNDERPOWERED / NULL**: T9 "adds nothing as centre or spread" (SYN §1.3, §6.2; no interval quoted) | — |
| S8 | **RAP** | yes | partial | **NOT TESTED** | Named only in `docs/research/MARKET_MAKING_RESEARCH_AUDIT_2026-06-13.md`; not in EF/SYN. |
| S9 | **GFS** (direct) / **GEFS** ensemble | yes | yes | GFS: **BLOCKED as a PIT source** (no historical first-availability; research 82a, EF §1m). As a forecast it enters only via Open-Meteo `forecast_high` (79a kernel 1.516/1.456x). **GEFS: CAPTURED-NOT-SCORED**: it is the served `global_ensemble` vote, never scored alone. **2026-10-26:** lane G's F4 "GEFS mean" harm (+0.0054 [+0.0016, +0.0100], EF §10y) scored the control-run column (EF §10s caveat), so the 30-member mean is still untested ([lever inventory](LEVER_INVENTORY_2026-10-26.md) F6, row 21). | The 20 settled Open-Meteo fields contributed nothing to the fit (EF §6), but that fit dropped them (EF §4). |
| S10 | **ECMWF IFS** open data | yes | yes | **TESTED-UNDERPOWERED, wrong sign**: 00-16 +0.0031 [-0.0025, +0.0091] (SYN §1.3) | Already captured through Open-Meteo (SYN §5) and part of the `open_meteo_global_models` vote. ECMWF **ENS** open data: **TESTED, KILL (null)** 2026-10-24: G2-a −0.0000 [−0.0033, +0.0031] over MG-1 at 00-12, G2-b −0.0002 [−0.0005, +0.0001] over t3-r3 at 13-16 (EF §10y). |
| S11 | **ECMWF AIFS** (free open data) | yes | yes | **CAPTURED-NOT-SCORED**: `ecmwf_aifs025` is in the `open_meteo_global_models` vote (`model_sources.py`). **Contradiction (2026-10-26, [lever inventory](LEVER_INVENTORY_2026-10-26.md) F5):** EF §10y's F4 row says AIFS and GraphCast were never captured; the code lists both in the vote. Unresolved: read it as "not in lane G's member capture" until a capture trace settles it | `docs/roadmap/items/item-189-ecmwf-ml-nwp-ensemble-members.md` (DORMANT). |
| S12 | **ICON** (DWD, via Open-Meteo) | yes | yes | **TESTED inside a blend, KILL (null)** 2026-10-24: the L4 inverse-MSE blend of NBM, GFS, IFS and ICON, −0.0002 [−0.0045, +0.0047] over MG-1 at 07-12 (EF §10y). Not tested alone | Named in the FREE audit; the Open-Meteo per-model decomposition was never done. |
| S13 | **GEM / HRDPS / RDPS** (ECCC) | n/a | **yes: the only guidance family native to Toronto** | **CAPTURED-NOT-SCORED**: `eccc_citypage` is a served consensus vote. GEM/HRDPS gridded readers exist (`src/weather/sources/eccc_gridded.py`), probed in FREE audit §9. | Toronto's NBM-family guidance is not captured (the sources cover CYYZ; RF "Toronto has no NBM"), and no guidance increment has ever been scored for it. ECCC SWOB is used for observations (EF §4). |
| S14 | **Open-Meteo individual models** (the served consensus above) | yes | yes | **PARTLY / TESTED-UNDERPOWERED**: temperature PIT is served; the 7-run forecast-high SD was a **blind null** (power 0.113, EF §1e); the per-model increment was **never scored** | Composition as listed above the table. |
| S15 | **Open-Meteo Previous Runs, 12 PIT fields** (leads 1-7) | yes | yes | **TESTED-UNDERPOWERED** x3 (research 88a/100h/90a, EF §1m); the pooled refit worsened the centre (86a, power 0.148); the staged 2026 fetch was **not adopted** (EF §1e) | History: temperature 2021-2025; ten fields 2024-2025; `precipitation_probability` 2025 only. The §1h protocol on these fields was never executed (EF §1j). |
| S16 | **NWS gridpoint forecast** (captured; `nws_hourly` consensus vote; an NWS-grid column exists) | yes | n/a | **TESTED-UNDERPOWERED** as a point kernel (1.429/1.372x market, EF §10h); not in the served column set | — |
| S17 | **NWS forecast revisions** (direction) | yes | n/a | **TESTED-NO-INCREMENT**: "classifier LEAD is a blur artefact; placebo beats it" (T12, SYN §1.3) | — |
| S18 | **Area Forecast Discussion** text | yes | n/a | **TESTED, KILL (harm)** 2026-10-25: L5 AFD features vs matched coastal intercepts at 07-12 +0.0012 [−0.0006, +0.0040], date-clustered [+0.0003, +0.0020], mostly Los Angeles (EF §10ah) | Rule `e146655a…`. |
| S19 | **METAR / SPECI** (served floor source) + **remaining-rise rule** | yes | yes (CYYZ :00) | Floor: served. Remaining-rise t3-r3 is a **TESTED-DEV-LEAD** at 13-16: -0.0116 [-0.0190, -0.0052], 10/11. It is fragile: WEAK at +1 h, NULL at +2 h, and it fails the family-wise z -3.26. The D2 draft is unsigned, with 17% power at the half effect (EF §10q; OQ Q-19). The SPECI event study is **unpowered** (EF §10h). | Observation clock measured (89b): station-specific routine minutes. Capture-host `data/metar` history stops 2026-06-30 (FD). |
| S20 | **5-minute / 1-minute ASOS** (IEM, NCEI) | yes | n/a | **TESTED, KILL (harm)** 2026-10-24 as an input: F1 1-minute ASOS running high +0.0044 [+0.0017, +0.0076] over t3-r3 at 13-16 (EF §10y); this also kills the paid observation feeds. Before that, It was used only for settlement mechanics: 1-min data was acquired as a label, the 1-min true max as a target was HARM, and rounding headroom was NULL (T16, SYN §6.2). | Directly relevant to t3-r3's freshness sensitivity (-40% per hour of staleness). |
| S21 | **Mesonets / PWS** (MADIS, Synoptic, WU PWS pages) | yes | yes | **NOT TESTED** | Synoptic was deferred because it needs a token (FREE audit). Neighbour METAR is S23. OD15 (DL 2026-10-06) accepts a scraped WU public-page token under the no-paid rule; see S22. |
| S22 | **WU history itself** (the settlement proxy) | yes | yes | **BLOCKED for serving since 06-30.** `fetch_wu_history` is still gated by `paid_weather_provider_disabled` (`model_sources.py`), and v3/v4 anchor on METAR instead. The settled-day public-page collector exists (`src/weather/sources/wu_history.py`, daily step `public_wu_settlement_restore`). OD24 (DL 2026-10-07) kept it off until the redaction change, which reached `master` on 2026-10-11 (`2745f00da`). **OWNER-QUESTION:** no doc or config records whether production re-enabled it; that is runtime state. **NOT TESTED** as an input since 06-30. | The original lock-in anchor. Q-21 (intraday vs daily summary) needs it. |
| S23 | **Neighbouring stations** | yes | yes | **TESTED-UNDERPOWERED**: WEAK ~0, HARM at 06-09; 13-16 -0.0006 (7/11) (T13, SYN §1.3) | — |
| S24 | **12Z soundings** | yes | yes | **TESTED-UNDERPOWERED** at 17-23 only: -0.00073 [-0.0032, +0.0008], 2 markets (T11, SYN §1.3). 00-16 not reported. | Mixed-layer / inversion as an afternoon-cap signal for 13-16: **NOT TESTED**. |
| S25 | **GOES satellite / cloud** (with METAR cloud) | yes | yes | **TESTED-UNDERPOWERED**: 10-12 -0.0011 [-0.0026, +0.0002] vs served (T14, SYN §1.3). The point sits on the bar. | — |
| S26 | **Radar / MRMS** | yes | yes | **CAPTURED-NOT-SCORED**: MRMS precipitation is captured (`src/weather/sources/mrms_precip.py`) and was "never screened" (swarm `t20.md`, `COMPLETENESS.md`) | — |
| S27 | **Marine / buoy** (onshore flow, lake breeze) | coastal | yes (lake) | The served geometry proxies (`onshore_flow`, `lake_breeze_proxy`) survive. **Live marine data has been dark since 2026-06-13**: the sidecar refresh is unscheduled (`docs/research/missing-information-review-2026-09-21.md`). `marine_water_contrast` is `disabled_unpinned` (`src/weather/calibration/pooled_training.py`). Increment: **NOT TESTED**. | — |
| S28 | **Climatology / persistence** | yes | yes | **TESTED-NO-INCREMENT / HARM** standalone: t3-r1 HARM 13-23; t3-r2 WEAK 00-09, HARM 13-23 (SYN §1.3). As a per-market centre correction: **TESTED on MG-1, KILL (null)** 2026-10-25: L5 A1 v2+NWS per-market debias −0.0001 [−0.0042, +0.0045] at 07-12 (EF §10ah). On every NBM-anchored arm (P3d_N_fix, L6, the MG-1 and P3d_N families): **KILL at gate 1** 2026-10-26, L11's R-M +0.00013 [−0.00027, +0.00055] (§6 X36). | — |
| S29 | **ML weather models** | yes | yes | AIGFS: **TESTED, KILL (null)** 2026-10-24, F4 +0.0003 over MG-1 at 00-12 (EF §10y). GraphCast: **CAPTURED-NOT-SCORED** (`gfs_graphcast025` is in the `open_meteo_global_models` vote; EF §10y says never captured: see the S11 contradiction). Pangu is named in item 189 and not captured. FourCastNet: **NOT TESTED**, named nowhere. | — |
| S30 | **Venue order flow and prices as information** | yes | yes | Shrinkage: **measured, forbidden as edge** (EF §1c, §5). As a maker fair value: **hypothesis, NOT TESTED** (EF §1c "the MM question is OPEN"). Market Brier falls at informative METARs (T17, descriptive). Public-flow timing: 94a/95a, OQ Q-06/Q-07. | Maker replay v2 is the live path (SOP). |
| S31 | **Other prediction markets' prices** (e.g. Kalshi) | yes | yes | **NOT TESTED**. Reading prices is not trading, but "International only" is the owner's rule, so any probe needs an owner call first. | — |
| S32 | **RTMA / URMA analyses**, **NAM**, **HREF / SREF** ensembles | yes | partial | NAM: **CAPTURED-NOT-SCORED** (US multimodel feed, diagnostics only); NAM-MOS is scored under S5. RTMA probed and URMA named (FREE audit §5): **NOT TESTED** (DATA_LAYER_V2_PLAN's "Grids/MOS/AFD/soundings/RTMA ... TESTED-UNDERPOWERED/NULL" row is wrong for RTMA/URMA, corrected there 2026-10-26). HREF / SREF: **NOT TESTED**, named nowhere. | — |
| S33 | **Own lagged forecast error** (forecast tracker residuals) | yes | yes | **TESTED-UNDERPOWERED / blind**: lagged five-day error SD, power 0.103 (EF §1e) | Never re-run on the staged corpus. |

**Inventory tally (US 11).** S9 and S32 are split across statuses, so the counts sum to 35 entries over 33 rows.

| Status | Count | Rows |
| --- | --- | --- |
| TESTED-NO-INCREMENT | 3 | S4, S17, S28 standalone |
| TESTED-UNDERPOWERED | 12 | S3, S5, S6, S7, S10, S14, S15, S16, S23, S24, S25, S33 |
| TESTED-DEV-LEAD | 2 | S1, S19 |
| BLOCKED | 2 | S9 GFS as PIT, S22 for serving |
| CAPTURED-NOT-SCORED | 6 | S9 GEFS, S11, S13, S26, S29, S32 NAM |
| NOT TESTED | 10 | S2, S8, S12, S18, S20, S21, S27, S30 as fair value, S31, S32 RTMA/URMA/HREF/SREF |

**Toronto** shares the Open-Meteo consensus votes but has never had a guidance increment scored. Its one native family
(S13) is captured but unscored. **For the foreign cities the inventory is empty.**

---

## 3. Method leads not yet exhausted

| # | Lead | What the docs say | Status |
| --- | --- | --- | --- |
| L1 | **Post-fix forward measurement of the served model against the market, all hours** | The fix has been served since 10-06 (v3) and 10-09 (v4 + M0). Only the 17-23 block has a registered read (evening-fix scorer, 10-16..10-27, read 10-29). The daily model-vs-market scoreboard (learning lane) has been blocked since 08-13 (OQ Q-11), so **no running tracker exists**. A tracker must reproduce §3's numbers as its positive control, on pre-10-09 data. | Partly registered (17-23). The all-hours served ratio on new dates is **unregistered**. |
| L2 | **MG-1 forward read** | Signed `b044e0f1`; narrow reservation; D0 after #190 lands 10-18; 45 countable dates; fixed-market joint power 0.80 at the half effect (SYN §8; DL 10-04). | Registered, waiting on the parser landing. |
| L3 | **Hour-gated NBM (HG-1)** | Held until the evening fix was live, which it now is. A separate alpha arm; it may not choose its hours on the 111h table (EF §10p; SYN §8). | Unregistered. |
| L4 | **The 13-16 block (1.81x after both repairs; 15-16 post-hoc 2.53x)** | The largest residual. S3-S5 recover only -0.0020. 58% of 15-16 snapshots have not rolled over, which is a remaining-rise problem. t3-r3 helps but is fragile and freshness-bound (EF §10q; OQ Q-19). Fresh observations (S20), soundings for the afternoon cap (S24) and ECCC/HRDPS for Toronto (S13) are untested there. | The D2 draft is unsigned and underpowered at the half effect; owner option in D2 §6. |
| L5 | **The 00-12 residual (+0.010 to +0.014, 1.18-1.26x)** | "Nothing tested closes it". It needs a hypothesis with a no-source control before any new capture (OQ Q-20). | No candidate. |
| L6 | **Fitted spread forms on captured v2 (T18 EMOS / RV-1)** | Indistinguishable from MG-1 in 00-16 (-0.0034 [-0.0078, +0.0007]); better all-day. Held until the evening fix was live. It shares the reserved dates with MG-1, so either sign one per family or split alpha (SYN §8-9). | Held; unregistered. |
| L7 | **Per-market / per-season specialisation** | The cool bias is heterogeneous by market (no global offset, EF §2). Per-market isotonic was tested and closed (EF §1c). The season-matched refit proxy, 24.9% [-20.5, +55.2], was never tested as a candidate (EF §1d). The retrain never completed (EF §4a-bis). The 12-field pooled refit worsened the centre, underpowered (EF §1m). The rolling per-market centre correction (FP item 8) has not been run. | Open; blocked on a retrain lane that has never run end to end. |
| L8 | **T+1 / T+2 markets** | The served model has no T+1/T+2 output, and the tape is T+0 only. T+1/T+2 books exist only in 88a (frozen until after 10-14). The maker fair value is a frozen single read (10-15). The NWP-timing market-only prereg (10-02) is frozen and awaits the 88a transfer. Parser v2 "target = tomorrow is right at every cycle" (EF §10k), so a day-2 NBM read is mechanically available. | **Never measured.** A T+1/T+2 forecast-vs-market read is a new pre-registration. |
| L9 | **Foreign cities** | No served model. Settlement sources are known (EF §10c). OQ Q-14 census: Taipei and Jinan first; 147 "later" on settlement alignment. | Nothing exists. |
| L10 | **Blending with the market as a pull / fair-value signal, not an edge** | EF §1c leaves the MM use open. Informed-maker design; maker replay v2 (signature target 10-22..23, SOP); T17 descriptive. 95a METAR pulls catch 1.18x of large moves on T+0 only. | On the maker critical path, not a forecast test. |
| L11 | **Full free-source parity re-measurement** | "Full free-source parity has never actually been measured" (RF: the ECCC verifier was wrong). The retained corpus cannot show the humidity/pressure repair (EF §4), and two months of v3 captures now exist. `wind_group` is dead in all 12; the F-market pressure drop is owed in training. | Cheap; never done. |
| L12 | **The §1h PIT-field protocol** | Frozen, hashed and executable on the staged corpus. It was closed unused on a replay artifact; the mechanism was "not tested in either direction" (EF §1h-§1j). Gate 3 must be replaced (EF §1k `-09-68a`). Decision 10 is retired, so a new ledger row is needed. | Never executed. |
| L13 | **Tail re-split under a rank-based disagreement gate** | EF §1f caveat 3: the >=0.30 absolute gate mechanically favours high-probability bands; "re-run the position split … before building on the centre story". | Never done; costs nothing; no alpha. |
| L14 | **Batching of sub-3.2% improvements** | EF §1d: steps below the floor are individually unconfirmable and must be accumulated. Never used. | Method only. |
| L15 | **Fixed-market, date-clustered inference for decisions** | FP item 7 (owner decision pending on the two-tier ship rule). It changes what is confirmable; the MG-1 prereg already uses it. | Owner decision pending. |
| L16 | **Re-derive the retired 74.97% centre-oracle ceiling** | Unciteable, with no replacement (EF §1). It needs a new estimator on the repaired surface. | Never done. |
| L17 | **The other ~7 silent no-op post-processing stages** | EF §10e: 13 of ~26 stages are no-ops; only the lock-ins and taper have been read and repaired. | Unmeasured. |
| L18 | **Item 337 no-METAR floor (Toronto) and Q-21 WU intraday vs summary** | The owner's yes is conditional on the host replay >= 10-15 (DL 10-13). Q-21 needs WU history back (S22, OWNER-QUESTION). | Pending. |
| L19 | **110g afternoon-centering stage** | Disabled pending "a separate measurement" (EF §2); disabled and reloaded since 09-28 (§0.1). Whether a re-fitted centering helps the post-10-09 path is unmeasured. | Unmeasured. |
| L20 | **Own-information dispersion at usable power** | `-09-58a` was blind; the fetch that made it blind has since been run and staged (EF §1e). | Never re-run. |
| L21 | **Captured-but-unscored consensus members** | GEFS, AIFS, AIGFS, GraphCast, ECCC citypage and MRMS reach the host (§2), but only as pooled votes or diagnostics. | Never scored one at a time. |

---

## 4. Maker-pillar leads (brief)

- **The informed-fill fraction `f` is unidentified, not underpowered.** Book deltas cannot distinguish cancels from
  executions, so only forward own-account evidence answers it (EF §1b.3, §8c). Zero-edge break-even holds in 45.94% of
  scenarios at $0 reward and 88.99% at $1/band/day; viability is dominated by `f`.
- **No profitability result exists.** RE-1 realized net is **-36.97 pUSD** over five fills and one paid reward day
  (+2.13 vs ~2.03 modelled, k ~ 1.05). The reward share model holds in scale. Share halves within 2-4 minutes of
  posting. Empty bands fill; contested bands require the depth rule (EF §10m; FD).
- **Fees.** Weather takers pay `0.05 x p(1-p)` per share and makers pay 0; 25% of taker fees fund maker rebates.
  **No rebate has ever been received** (EF §10o). Public maker markout is +0.19 c/share at 5 min and -0.43 c to
  settlement (item 330).
- **Reward pool.** About 2,800/day same-day and ~4,800 across all active markets; our share is unmeasured. The
  10 pUSD per-band cap makes a reward-eligible 20-share two-sided quote (~19.60) impossible, and same-day bands flip
  to a 100-share minimum (EF §10a).
- **Cash is limited per market, not across markets.** Simultaneous fills beyond cash are an unmeasured venue behaviour
  (EF §10n; OQ Q-12, Q-13).
- **The maker-P&L desk study is not powerable at delta = 1.0:** N_req = 706 event dates from a 4-date pilot,
  UNDECIDABLE_AT_DELTA; the embargo end stays 11-13 (EF §10r, DL 10-14).
- **Timing.** METAR minutes are station-specific (89b). METAR +-2 min pulls catch 1.18x the large moves of the best
  fixed clock, on T+0 only. NBM/GFS/HRRR pulls are <= baseline (OQ Q-07). The T+1/T+2 NWP-timing study is frozen
  awaiting 88a.
- **Critical path:**
  - maker replay v2 (signature 10-22..23, look by 11-15);
  - forward paper shadow active 24/7;
  - LFC session 0 on Fri 10-16 (DL 2026-10-13 row; SOP).
- **Kill rules (FP):**
  - **K1:** the best pull policy's net value per band-day has a date-clustered upper bound below zero -> stop the
    maker build, keep capture.
  - **K2:** the median settled reward on T+1 bands at a fundable size is below the owner's floor -> stop. The floor is
    unset, so K2 is inactive.
  - **K3:** once quoting, realized fill losses exceed twice the shadow prediction -> pause and re-derive.
  - Plus the RE-1 stop rule.
- **Open questions:** Q-01..Q-07, Q-12 and Q-13 are all OPEN; Q-15/Q-22 are answered.

---

## 5. Exit criteria, in recommended order

**Order principle:**
1. free reads on data we already hold;
2. the registered forward reads;
3. one-source-at-a-time increments with a pre-declared MDE at the 5% bar;
4. the expensive structural work.

Rows marked **URGENT** are the ones the bug fixes make stale. "Not set" in the Owner / due column means no document
schedules it yet: the owner or master-agent sets it when the row is registered.

| Order | Row(s) | Pre-registerable exit criterion and closing test | Owner / due | Cost | Flag |
| --- | --- | --- | --- | --- | --- |
| 1 | L1 / rows 1, 2, 12 | **Re-arm a served-vs-market daily scoreboard** on all post-10-09 dates: per hour block, 12 markets, crossed and fixed-market intervals. Positive control: reproduce §3's 1.6639 -> 1.4980 on its own pre-10-09 window to all printed digits. **Closes** when 45 countable dates are in and the per-block ratios are published with MDEs. This re-bases rows 1-2 and makes every later row interpretable. | master (learning-lane unblock, OQ Q-11) + workstation (analysis) / not set | free (the data exists) | **URGENT** |
| 2 | L13 / row 8 | Re-run the §1f position split under a rank-based disagreement gate on the sealed panel, with B and C reported separately. Then recompute the tail definition on post-10-09 served output. **Closes** when the centre/shoulder share and AUROC are re-stated per stratum with the defect rows removed. | workstation / not set | free, no alpha | **URGENT** |
| 3 | L11 / row 6 | Measure full free-source parity (humidity, the F-market pressure drop, trends, `wind_group`) on captures since 08-08, paired and crossed: severe-tail SSE and pooled Brier with MDE. **Closes** when both intervals are reported. A tail-SSE lower bound > 0 keeps the lever; otherwise drop it as correctness-only. | workstation / not set | low | — |
| 4 | row 15 | **Evening-fix scorer** as signed: window 10-16..10-27, one look 10-29, NEW vs OLD replay vs market at 17-23, materiality <= -5% of the window's OLD-minus-market gap, safety count zero. **Closes** on the read. | master lands `8cdcb62ec` before 10-28 / read 2026-10-29 | registered | **URGENT** (first post-fix evidence) |
| 5 | L2 / row 13 | **MG-1** as signed: 45 countable dates from D0 (after #190, 10-18), 00-16 primary, fixed-market joint rule. **Closes** on its single look. | master (#190 lands 10-18) / look at the 45th countable date after D0 | registered | — |
| 6 | rows 3, 4, 5 | On the same >= 45 post-10-09 dates, under one pre-registration with one look: (a) the 114-cell edge map; (b) the §1c recalibration bound (fit on odd dates, score on even, same four families, training score first); (c) the shrinkage locator per block. **Closes** when (a) has no cell with a lower bound > 0 across >= 20 dates and (b)'s upper bound is reported. Any cell with a lower bound > 0 reopens row 5. | workstation (prereg) + owner signature / prereg not drafted; look after 45 post-10-09 countable dates | low | **URGENT** |
| 7 | L12 / row 19 | Execute the §1h protocol on the staged 12-field corpus, with Gate 3 replaced by a rate gate (a crossed interval on the zero rate, not fail-on-any-row), under a new ledger row, q = 3.1098893. **Closes** when the primary and tail intervals are both reported. A NO_GO_UNDERPOWERED_EFFECT_FIELD verdict closes it as "untestable on this corpus". | workstation + owner (ledger row) / not set | medium (workstation) | — |
| 8 | L3 | HG-1 as a separate alpha arm on new dates after MG-1's D0, gated from the NBM schedule only (`captured_at_utc` < 12:00Z). **Closes** on one look. | workstation (prereg) + owner signature / after MG-1 D0 (>= 10-18) | low | — |
| 9 | L4 / S19, S20 | D2 (t3-r3) signed at the **full** effect, with METAR freshness < 1 h as a validity condition and a pre-declared 5-minute ASOS freshness arm. **Closes** on one look; a VOID on freshness closes the rule as unservable. | owner (D2 §6 signature, OQ Q-19) / not set | low-medium | — |
| 10 | L6 | RV-1 (or T18) vs MG-1 on dates after MG-1's reservation, at 00-16 and 17-23 with the lock-in on top. **Closes** when the RV-1 - MG-1 interval excludes the 5% bar either way. | workstation + owner signature / after MG-1's reservation | low | — |
| 11 | row 16 / S3, S5, S6, S10, S25 | One source at a time: a paired increment over MG-1 on new dates, with the **MDE pre-computed at the 5% bar** (~ -0.0012 at 00-16). A source whose MDE is above the bar is marked UNTESTABLE, not NULL. **Closes** per source when the interval excludes the bar. Order by cheapness: HRRR (already captured), ECMWF via Open-Meteo (already captured), GOES/cloud, MOS/NBE (IEM text, ~5-6 MB/month), NBH last (0.68 GB/day). | workstation / not set | low-medium each | — |
| 12 | L21; S9-GEFS, S11, S13, S26, S29, S32-NAM (captured, unscored) and S12, S8, S32 (never opened) | Captured sources: score each one's own increment on data already held, then on new dates as in order 11. Never-opened sources: a 30-day captured shadow column first, then the same test. **Toronto first, with GEM/HRDPS and the NBP CYYZ bulletin**, because it has never had a guidance control (its NBM-family guidance exists but is not captured; RF "Toronto has no NBM"). **Closes** per source as in order 11. | workstation; master for any new capture (owner yes) / not set | medium | — |
| 13 | S18, S21, S22, S27, S31 | Owner decision whether to open each at all: AFD text, mesonets/PWS, WU history re-enable (OWNER-QUESTION), the marine refresh, other venues' prices. Each needs a stated mechanism and a no-source control before capture (OQ Q-20 rule). **Closes** by owner decline or by an order-11 test. | owner / not set | owner call | — |
| 14 | L8 | T+1/T+2: a day-2 NBM v2 read vs the 88a T+1 book mid, market-only first (the frozen 10-02 study), then forecast-vs-market under a new prereg once >= 20 T+1 dates are captured. **Closes** on the registered looks. | workstation; master (88a transfer) / after the 88a freeze | medium | — |
| 15 | L7 / row 24 | Run a season-matched retrain lane end to end once: temperature PIT all years + the 12 fields 2024-2025, the §4g exclusion list, the PIT file read by the trainer. Score it on a pre-registered out-of-season stratum against the frozen artifacts, with the §1d 24.9% proxy as the prior. **Closes** on one look; a null closes "retrain as the lever". **Waived for the 12-21 decision (owner 2026-10-21, DL row 2026-10-21 "Retrain under the programme"); best case a futility-only R0 from 11-17** ([item 339](../roadmap/items/item-339-edge1-model-edge-preregistration.md)). | owner + master (retrain lane) / not set | high | — |
| 16 | L17, L19 | Read one served stage vector per remaining no-op stage, and emulate repairs as in §10q. For 110g: verify the activation receipt (W-0004) and measure a re-fitted centering. **Closes** when each stage is shown inert, or repaired and scored. | workstation; master (receipt) / not set | low-medium | — |
| 17 | L9 | Foreign cities: capture plus settlement alignment per Q-14. **Closes** when the Q-14 census names each city's aligned settlement source and >= 30 days of capture exist. Each city then enters orders 11-12 with its own control. No forecast claim is made before that. | owner (scope) + master (capture) / not set | high | — |
| 18 | §4 maker rows | Maker replay v2 signed -> shadow -> K1/K2/K3 as written in FP; K2 needs the owner's floor. **Closes** on the kill rules, or on a powered P&L read. The 10-14 power rule says that needs ~706 event dates at delta 1.0, so set a larger delta or a different estimand first. | T1 track + owner (K2 floor) / signature 10-22..23, look by 11-15 | on the critical path | — |

**What "as nearly as possible" would then mean.** After orders 1-12:
- every free source that plausibly carries same-day information for the 11 US markets will have either a precise null
  at the 5% bar or a registered forward read;
- Toronto will have had its first guidance control;
- the served model will have a post-fix gap figure at every hour.

No amount of this work can settle three structural limits, which are already written down:
- the 3.2% MDE floor set by 12 market clusters (EF §1d);
- the in-season figure, which cannot be re-measured before May 2027 (EF §4b);
- the maker-side `f`, which only own-account fills identify (EF §1b.3).

---

## 6. Ruled out since 2026-10-21 (every null and kill, with its reopen condition)

Added 2026-10-26 on the owner's question (2026-10-25 ~19:57, verbatim): "we are recording each thing we rule out yes?
All of it is useful in some way potentially". One row per null, kill, stop or bounded effect. Numbers are quoted from
the cited EF section; re-verify there before reuse. Rows are never deleted; a reopened row says which new rule took it.

**Common conditions** unless a row says otherwise: "dev" = the development scorecard, scored 2026-08-15..09-29, 43
dates x 11 US markets = 473 market-days, burn-in 08-01..08-14, nothing dated after 09-29 read; intervals 95%,
date-clustered unless "crossed" (date x market), 2,000 draws, seed 20260921; dR = candidate − reference in the
scorecard's R units; "capture-time" = each row uses only data received by its own capture; `last_in_hour` = the last
replay snapshot of the hour (allowed only for MG-2 vs MG-1). Each rule was committed before its rows existed.

| # | Ruled out | Numbers [95% CI] | Window / N | Conditions (arm, inputs, dating, rule) | Verdict | Reopen if | Record |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X1 | Full-year R0 retrain as the R0 fix | +0.90 [+0.73, +1.08] nats vs forecast + floor, +1.02 [+0.86, +1.18] vs OLS + floor at 07-12 | R0's Oct-Dec rows, 5 US markets, centre 11-24 | HGB leaf 20 + floor, full-year union corpus `621bcd8e…`; rule `008c662b…` | KILL (not adopted) | the retrain lane gains fields the corpus lacks | EF §10z |
| X2 | 1-minute ASOS running high (F1) | +0.0044 [+0.0017, +0.0076] over t3-r3 at 13-16 | dev | paired over t3-r3; degraded 5-min whole °C +10 min | KILL (harm); kills paid obs feeds | a receipt-faster obs feed with a new mechanism | EF §10y; S20 |
| X3 | 12Z soundings mixed-layer cap (F3) | −0.0001 [−0.0003, +0.0000] at 13-16 | dev | over t3-r3 | KILL (null) | never as a cap; only a new sounding mechanism | EF §10y |
| X4 | Captured Open-Meteo members (F4: GFS, NAM, AIGFS; GEFS "mean") | spans 0 over MG-1 at 00-12; GEFS +0.0054 [+0.0016, +0.0100] | dev | MG-1 recentred halfway | KILL (null; GEFS harm) | the GEFS 30-member mean (the harm scored the control run, EF §10s) | EF §10y; S9, S29 |
| X5 | ECMWF ENS mean (G2-a, G2-b) | −0.0000 [−0.0033, +0.0031] at 00-12; −0.0002 [−0.0005, +0.0001] at 13-16 | dev | over MG-1 / t3-r3; 51-member mean, bias-adjusted | KILL (null) | ENS spread as spread information (R9 family) | EF §10y; S10 |
| X6 | L4 multi-model inverse-MSE blend (NBM, GFS, IFS, ICON) | −0.0002 [−0.0045, +0.0047] over MG-1 at 07-12 | dev | rule `96dee78c…` | KILL (null at 07-12); h15-23 parked | an afternoon rule on its h15-23 gain against P3d_N | EF §10y; S12 |
| X7 | F2 MRMS echo flag (not killed) | −0.0005 [−0.0010, −0.0001] over t3-r3 at 13-16 | dev | ≥ 35 dBZ within 25 km | sub-bar LEAD; capture change held (DL 10-24) | owner releases the capture change, or it enters a batched package (L14) | EF §10y |
| X8 | L5 arm A: per-market debias (A1), linear + overnight-low anomaly (A2) | A1 −0.0001 [−0.0042, +0.0045]; A2 −0.0016 [−0.0059, +0.0033] (crossed) | dev 07-12 | vs MG-1; rule `53fd0bc5…` | KILL (null) | a centre source outside MG-1's family; never a subset re-cut | EF §10ah; S28 |
| X9 | L5 arm B: full-year GFS day-1 linear (B1), (v2 + B1)/2 (B2) | B1 +0.0169 [+0.0069, +0.0269]; B2 +0.0021 [−0.0032, +0.0084] (crossed) | dev 07-12 | vs MG-1; corpus `621bcd8e…`; addendum `42d30a2f…` | KILL (B1 harm, B2 null) | a corpus with more than the one GFS regressor | EF §10ah |
| X10 | AFD text features (L5) | +0.0012 [−0.0006, +0.0040]; date-clustered [+0.0003, +0.0020] | dev 07-12, coastal | vs matched coastal intercepts; rule `e146655a…` | KILL (harm) | none planned | EF §10ah; S18 |
| X11 | Upstream ASOS ring observations (L6) | −0.0005 [−0.0012, +0.0003], MDE80 0.0011 | dev 07-12 | vs the own-obs twin; rule `6687c8df…` | KILL (null) | an arm without NBM (NBM already carries it) | EF §10ab |
| X12 | L3 arm A (OLS + floor) at 07-12 | +0.080 [+0.020, +0.142] vs MG-1 | dev 07-12 | OLS + floor + L8 running max; rule `fa72409a…` | LOSES at 07-12 (wins from 13:00, later replaced by P3d_N) | none at 07-12 | EF §10ab |
| X13 | L9 ladder: overnight low, dewpoint, hour-pooled slopes | −0.0124 [−0.0189, −0.0060] (Aug-Sep CI-worse); −0.0009 [−0.0078, +0.0073]; +0.0632 [+0.0518, +0.0741] nats | blocked LOYO 2021-25, 103,609 rows | on OLS + floor; rule `3b4976dc…` | KILL (all three) | overnight low and dewpoint help in Oct-Dec: an Oct-Dec rung under R10 | EF §10ac |
| X14 | L8 HGB with the high_so_far parity fix as a candidate | fix − base 00-16 −0.0088 [−0.0171, −0.0008] (crossed spans 0); fix − MG-1 +0.2232 | dev 00-16 | rule `55cf6989…`; ledger row 33 (L8 branch) | KEEP vs base, NOT BOUND | an HGB serving arm re-enters a candidate (then it is a precondition) | EF §10ah |
| X15 | R-A: NBM-anchored baseline B_N and P3d_N_fix vs MG-1 at 07-12 | B_N −0.0094 [−0.0504, +0.0324]; P3d_N_fix −0.0320 [−0.0663, +0.0041] | dev, 21,664 snapshots | capture-time P3d_N_fix; rule `0b6be0d6…` | NULL vs MG-1 (HGB layer admitted over B_N) | a new NBM-family input (NBS TXN) or a larger window, under a new rule | EF §10af |
| X16 | R-D: MG-1 / P3d_N_fix hour-wise blend | −0.0467 [−0.0665, −0.0257] vs MG-1 | dev 07-12 | walk-forward weight; rule `7d497e3c…` | WIN vs MG-1, SUPERSEDED (wrong incumbent) | only if MG-1 becomes the pre-13 arm again | EF §10af; RF "R-D blend" |
| X17 | R-F: blends against L6 | blend(MG-1, P3d_N_fix) − L6 +0.0243 [−0.0033, +0.0523]; blend(L6, P3d_N_fix) − L6 −0.0096 [−0.0187, +0.0003] | dev 07-12 | L6 frozen part `07a67425…`; rule `cca30734…` | NULL | L6 re-fitted or replaced, or a 07-12 arm with a new input | EF §10af |
| X18 | R-G: morning trajectory columns at 07-12 | gate 3a −0.0093 [−0.0199, −0.0000]; gate 3b −0.0048 [−0.0113, +0.0012] | dev 07-12 (Aug-Sep) | B_G and P3d_G on capture-time inputs; rule `a8cf6564…` | STOP at gate 3b; gate 4 not scored | Aug-Sep only (R10): an Oct-Dec rung with LOYO Oct-Dec 2021-25, forward-only promotion | EF §10af |
| X19 | R-I: per-hour temperature (width) on P3d_N_fix | LOYO −0.00045 [−0.00094, −0.0000084]; dev −0.0022 [−0.0156, +0.0104] | LOYO 2021-25; dev 07-12 | walk-forward τ 1.40-1.88; rule `b8a3d79c…` | KILL; fitted temperature/scale maps closed for NBM arms (R9) | spread INFORMATION is a separate open family (R9): own rule, full ladder, no global sharpening, floor never weakened | EF §10af |
| X20 | R-J: trajectory columns at 13-14 | LOYO −0.0335 [−0.0377, −0.0295]; dev −0.0025 [−0.0207, +0.0158] | LOYO 2021-25; dev 13-14 (Aug-Sep) | rule `e948c0a2…`; HRRR hourly path excluded | KILL | Aug-Sep only (R10); the HRRR hourly path is R-K (pre-registered) | EF §10af |
| X21 | Log-pool market blend: MG-1 and the pre-13 composite | MG-1 R 1.0017 [0.9990, 1.0077], w 0.008; composite R 0.9998 [0.9938, 1.0063], w 0.067, MDE80 0.006 | dev 07-12, 473 market-days | walk-forward pool, capture-time market; rule `e29c9a84…`, clarification `46e1fac2…` | NOTHING (MG-1); INCONCLUSIVE (composite) | a candidate with unblended R within ~0.05 of 1 at the block (today 1.16-1.30) | EF §10ad |
| X22 | NBM 07-12 blend (P3d_N with the market) | R 1.0013 [0.9992, 1.0075], w 0.0051, MDE80 0.0038 | dev 07-12 | `last_in_hour` P3d_N (flatters it, so firmer); rule `94b1603a…` | NOTHING | as X21 | EF §10ad |
| X23 | 13-16 blend gain as model information | MG-1 blend 0.9858, composite 0.9843 vs floor-only 0.9845 | dev 13-16 | market + hard floor control | NOTHING (the gain is the floor) | a 13-16 candidate beats market + floor alone | EF §10ad |
| X24 | Dead-bucket NO buying, US (r4; r3 early and late) | r4 $0.03/day [0.00, 0.09], 21 trades, MDE80 0.06; r3 $0.00 [0.00, 0.00] | 48 dates 08-10..09-29, $25 `print_d1` | capture-time dating, rule `fac8cd72…`; stage C gross bound $18.35/day (rule `177e9acf…`) not executable | CLOSED (not worth pursuing) | observation receipt latency falls well below book repricing, or a slower-repricing venue/market class | EF §10ad, §10ah; RF "Dead-bucket stage A" |
| X25 | Dead-bucket NO buying, Toronto (r4-toronto) | $0.00/day [0.00, 0.00], 0 trades; label-free 2 of 312 with a NO ask ≥ 0.005 | 51 labelled dates 08-10..09-29 | native °C, capture-time; rule `12902246…` | CLOSED | as X24, per city | EF §10ad |
| X26 | P3d_N receipt look-ahead (`last_in_hour`) | fix costs +0.0004 [+0.0001, +0.0007] at 13-16 (~3%); 8,077 of 9,332 rows used a later snapshot | dev 13-14 / 13-16 | P3d_N vs P3d_N_fix, fit fixed | BOUNDED: no MG-2 gate flips, pick survives; C7 as-of gate DRAFTED (`525effe62`), pending | the live serve path differs from the as-of dev path, or C7 is not adopted before MG-2 D0 | EF §10ag |
| X27 | R-H atlas: width, regime tags and HRRR−NBM tags as the 07-12 lever | position 0 carries +0.0093 of L6's +0.0081; re-centring removes ~25% (P3d) / ~15% (L6); no regime tag separates | 57 dates, 626 market-days | capture-time market; atlas `ff7ee231…` | SELECTION EVIDENCE: about two thirds of the 07-12 excess is sharpness, not centre | re-run per new arm; spread information is next (R9) | EF §10ag |
| X28 | L10 gap atlas: any pooled block at R ≤ 1 | best composite 07-12 R 1.159 [1.070, 1.266] (primary five) | dev | MG-1, arm A, P3d, composite | NONE at R ≤ 1 | re-run per new candidate | EF §10ah |
| X29 | Fresh development dates before 07-31 (P2) | 07-12..07-30 lies in the sealed panel (7 of 20 spent) | — | master ruling 2026-10-25 | NONE available | a candidate wins on dev: a sealed-panel confirmation proposed with its budget cost | EF §10ah |
| X30 | R-P (L14): NBH remaining-hours max as a 13-16 centre shift on B_N and P3d_N_fix | gate 2 LOYO B_P − B_N 13-16 −0.0093 [−0.0118, −0.0067] (Brier, 300 dates); fitted slope b = 0 in 40% (B_N) and 55% (P3d_N_fix) of fits, intercept a −0.2..−0.3 °F. **Gate 3 dev:** P3d_P − P3d_N_fix 13-16 dR +0.0141 [−0.0043, +0.0341], pass = false; harm at 15-16 +0.0425 [+0.0058, +0.0804] and h16 +0.0793 [+0.0351, +0.1263]; R vs market 1.307 (P3d_N_fix 1.293); MDE ≈ 0.027 | LOYO 2021-25; dev 13-16, 43 dates, 473 market-days, 13,970 snapshots; score sha256 `3e278836…` | rule `ed3236fa…` + RP-1 `f71a566a…` + RP-2 `70d4f01f…`; branch `claude/nbh-centre-1316-20261026` @ `ba11dd107` | KILL at gate 3 (dev): the LOYO intercept shift reversed on 2026. Lesson: a pooled LOYO intercept win is a bias correction, not information. Disclosure: production never captured NBH | NBH is captured forward and a rule with a slope term (not an intercept) passes LOYO by hour and market | EF §10ak |
| X31 | R-PD (L3): L6 own-obs nowcast stacked on NBM at 00-06 | gate 1 nested LOYO −0.0047 [−0.0073, −0.0022]; gate 2 dev 00-06 −0.0232 [−0.0520, +0.0047] (crossed [−0.0676, +0.0180]) | LOYO 2021-25; dev 00-06 (underpowered at 00-06) | rule `e010d166…` + PD-1 `fa874b10…` | CLOSED: gate 2 NULL after the LOYO pass | a larger 00-06 dev window (more dates or markets) or a forward read under its own rule | EF §10ak; L3 ledger rows (renumber at merge-forward) |
| X32 | R-N (L3): HRRR 2 m max stacked on NBM at 00-06 | gate 1 LOYO −0.0062 [−0.0092, −0.0032]; gate 2 dev −0.0105 [−0.0482, +0.0239] (crossed [−0.0660, +0.0454]) | LOYO 2021-25; dev 00-06 (underpowered) | rule `c1694f75…` + RN-1 `e4869491…` (nearest land cell) + PD-1 `fa874b10…` | CLOSED: gate 2 NULL after the LOYO pass | as X31, or HRRR captured forward under a forward rule | EF §10ak |
| X33 | R-L (L2): NBS TXN as a 07-12 centre input to P3d_N | gate 1a coverage 0.433 (8,517 of 19,657 training rows; threshold 0.95); every miss `column_absent` | training 2021-25 h07-12; nothing fitted or scored | rule `3ce9a6f2…`; branch `claude/rung0712-20261025` @ `1dd4145a1` | STOPPED at gate 1a, NOT a kill (inputs only). Format fact: NBS omits the target day's TXN max in cycles from 13Z on | R-L2 (pre-registering): newest cycle that carries the target day's TXN (in practice ≤ 12Z), which is an older centre at late cutoffs | EF §10ak |
| X34 | R-R (L2): HRRR hourly path as a 07-12 centre input (not a rule-out; recorded for its conditions) | gate 2 LOYO B_H − B_N −0.0092 [−0.0112, −0.0073]; gate 3 P3d_H − P3d_N_fix −0.0598 [−0.0813, −0.0401]; gate 4 blend_l6_H − L6 −0.0402 [−0.0603, −0.0198]; R vs market 1.112 [1.072, 1.159] | LOYO 2021-25; dev 07-12, 21,664 snapshots | rule `e3d92e1a…` + RN-1; branch `claude/rung0712-20261025` @ `4fccf23f7` (summary commit `b0dcb200`) | WIN on dev vs L6; still worse than the market; not an edge, not promotable (no captured-forward HRRR). Dev read by every rung since R-A, and R-R chosen because R-K won | promotion needs the HRRR forward recorder, forward parity and its own forward pre-registration ([plan draft](../research/l2-pooled-residual-2026-10-24/drafts/hrrr_forward_recorder_parity_plan_DRAFT.md)) | EF §10ak |
| X35 | R-L2 (L2): NBS TXN at 07-12, newest cycle that carries the target-day TXN | gate 2 LOYO B_L − B_N −0.0279 [−0.0308, −0.0248]; gate 3 dev P3d_L − P3d_N_fix −0.0123 [−0.0283, +0.0038] (FAIL); selected cycle 3-5 h stale at h10-h12 | LOYO 2021-25; dev 07-12, 21,664 snapshots | rule `a1f95786…`; branch `claude/rung0712-20261025` @ `6488c7a31` | KILL at gate 3: NBS TXN closed as a 07-12 centre input under R-L's and R-L2's cycle rules. Median |n_txn − anchor| is 1.0 °F in training vs 0.0 °F on dev; **corrected 2026-10-26:** the dev training-identical anchor equals the captured `usable_v2_mean` on 28,514 of 28,814 07-12 dev rows (about 99%; `dev_emit_audit.json` field `dev_corpus_vs_captured_nbm_by_hour`), so the anchor choice does not explain it: it is a 2021-25 vs 2026 difference between L9's NBM corpus and NBS TXN (rounding, version or cycle timing). **Mechanism (2026-10-26):** dev gap ≈ 0 is an NBM v5.0 NBS product change (08-12Z TXN carried forward from 07Z, equal to the NBP 07Z mean on ~95% of dev rows vs ≤ 0.45 in v4.x); labels verified (`claude/rs-spread-20261026` @ `e8ece032c`, `docs/research/l2-pooled-residual-2026-10-24/rungl2/nbs_label_check.md` (sha256 `41e5d1af…`) and `anchor_diag.md` (`68a97bbb…`)). R-L3 DROPPED, no rule written; an outcome-free input-only diagnostic (\|n_txn − L9 nbm\| by year x hour) is running | the diagnostic identifies a training-side anchor defect (rounding, version or timing) that a fresh, differently named rule could correct on the training side | EF §10ak |
| X36 | R-M (L11): per-market additive centre shift at 07-12 (one °F shift per market, no width parameter) | gate 1 nested LOYO, shift − no shift on P3d_N_fix, +0.00013 [−0.00027, +0.00055] Brier; Miami harm +0.00252 [+0.00092, +0.00421]; fitted per-market shifts all within ±0.4 °F | LOYO 2021-25, 19,657 rows, 300 date clusters, 2,000 draws, seed 20261024; gate 2 (dev) and gate 3 (vs L6) not run | rule `91e25610…` (committed `78fb338de` before any row); result `results-rm.md` on `claude/permarket-bias-20261026` @ `f84ba000c` | KILL at gate 1 (pre-registered): per-market centre bias is closed for every NBM-anchored arm (P3d_N_fix, L6, the MG-1 family and the P3d_N family); no other grid, hour block, shrinkage, objective, market grouping or rolling window runs under any rung name | a new training corpus (for example Oct-Dec under R10) shows a fitted per-market shift beyond ±1 °F | S28; `docs/research/permarket-bias-l11-2026-10-26/results-rm.md` (that branch) |
| X37 | R-S (L15): NBM-published spread (NBP TXNSD anomaly) as a scale modulator on P3d_N_fix at 07-12 | gate 1 nested LOYO 07-12 −0.00099 [−0.00171, −0.00026] (PASS); gate 2 dev 07-12 dR +0.00067 [−0.00604, +0.00722] (FAIL); secondary 13-16 LOYO −0.00023 [−0.00060, +0.00017] (fail, no dev run); only San Francisco's per-market CI excludes 0 | LOYO 2021-25, 19,657 rows; dev 2026-08-15..09-29, 43 dates, 473 market-days, 21,664 snapshots | rule `70908316…` (committed `8f80ea821` before any outcome join); result `results.md` (sha256 `604b0a0f…`) on `claude/spread-info-20261026` @ `efd95d8b9`; score `c3e8f0b2…` | KILL at gate 2 (pre-registered): the NBM-published-spread predictor family is closed for P3d_N_fix, L6 and every NBM-anchored arm (NBP TXNSD, NBP p90 − p10, NBS XND/TSD at fresher cycles) under any transform, anomaly window, grid, hour grouping or rung name. Likely cause (reading, not a gate): NBM v5.0 TXNSD on dev is compressed (25% of values equal 1). **Note:** L2 `rule_rs` `5fb593f4…` (scale-HGB variant) withdrawn before fit, 2026-10-26: same family | not covered by the kill (rule text): GEFS member spread, multi-model dispersion, observed-state predictors, each under its own rule. Reopen the family itself only if a future NBM version publishes uncompressed spread, or for Oct-Dec under R10 (coordinator, 2026-10-26) | EF §10ak queue (merge-forward) |
| X38 | R-Z (L3): HRRR 3x3 neighbourhood spread anomaly (z = ln sd of the 9-cell day-max, minus the training-years mean per market and hour) as a day-specific width multiplier at 00-06 and 07-12 | P0 screen, pooled nested-LOYO Spearman rho(anomaly, abs(dmax − mu)): 07-12 +0.023 (19,357 rows; 1 opposite-sign year, 2025); 00-06 +0.037 (11,341 rows; 2 opposite-sign years, 2023 and 2024); both below the 0.05 bar (00-06 also fails the opposite-sign rule) | history 2021-25 Aug-Sep only; z coverage passed (1.0 at 00-06) | rule `rule_rz.md` sha256 `36fa7726…`; P0 result `p0.json` `02b16373…` (module `7d82fd2c…`); code `claude/rz-hrrr-spread-20261026` @ `d4ac9e414`; arms MG-1 analogue (00-06), L6 stack (07-12) | CLOSED at P0, 2026-10-26: this construct as a width multiplier at 00-06 and 07-12, no gate 1 run. Distinct from S7 (time-lagged HRRR), X34 (HRRR as a 07-12 centre input), X27 (HRRR − NBM tag) and X37 (NBM-published spread). **Lead only, chosen after seeing the results, not a lever:** San Francisco rho +0.24 (07-12) / +0.32 (00-06), Seattle +0.08 / +0.12 | not closed: 13-16 (L2's pending proposal); a per-market SF/Seattle rule needs its own pre-registration on new evidence | DEV_WINDOW_LEDGER row 37 on `claude/l3-dev-ledger-rows-20261025` @ `be88fc78a` |

**Still open, not ruled out (2026-10-26):** R-K, the HRRR 13-16 hourly path as a P3d_N input (rule `21b5dfe1…`
pre-registered on `claude/rung0712-20261025` @ `4a850183f`; gate 2 LOYO PASS −0.0139 [−0.0166, −0.0112] on training
years only, an interim result and not an edge; 2026 dev rows pending, lanes L12/L13); NBS TXN inside
P3d_N at 07-12 only if the running input-only anchor diagnostic finds a training-side defect (R-L2 KILL, R-L3 dropped, X35); the HRRR 07-12 path (R-R dev WIN, X34) pending a forward
recorder; spread information other than NBM-published spread (R9; GEFS member spread R-Q running; X37); Oct-Dec rungs (R10); Toronto guidance; the 00-06 block; the GEFS
member mean. Ranking: the [lever inventory](LEVER_INVENTORY_2026-10-26.md).
