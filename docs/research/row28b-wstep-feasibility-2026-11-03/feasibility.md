# Row 28b rule-4 w step: feasibility note (history-tier screen; its own later prereg)

Status: **feasibility note only, outcome-blind.** It is not a prereg, freezes nothing and reads nothing that decides.
Lane L59, WS, 2026-11-03, from origin/master `621d67f0f`.

- Read: counts and file presence only. Directory names of the L52 price store; the row-113 receipt's recorded
  integrity counts; manifest and count files; prereg and code text.
- Not read: no price, label or loss value; no data dated 2026-09-30 or later; nothing under `C:\t\l2\p2` or any panel
  store; no B-bound file.
- Scope pointer: the forward draft §7a (`claude/row28b-forward-prereg-draft-20261103` @ `1fed1b989`). The w step is a
  walk-forward log pool of market and B against the date-deranged placebo and the floor-only control (MIM §3
  rung 4, `MODEL_IMPROVEMENT_METHOD.md:93-97`; §5 rule 4, `:160-161`).

## Verdict: FEASIBLE-WITH-BUILD, at 07-12 only (INFEASIBLE at 13-16 on power)

- **13-16 is INFEASIBLE on power.** Under the stated rule-19 bound (§5), it fails rule 16's power ≥ 0.5 at the
  season's maximum size.
- **07-12 is FEASIBLE-WITH-BUILD, as a SCREEN.** It needs builds 1-5 (below) before a prereg can freeze. None needs a
  label, price or loss value.

## 0. Boundary: the season ends 2026-05-26

- **Which year the seal covers.** The sealed panel is **2026-05-27..07-30**.
  - Row-28 prereg `docs/research/row28-yearround-history-2026-11-02/prereg_row28.md:41` (on
    `claude/row28-yearround-history-20261102`) hard-excludes "2026-05-27..2026-07-30 (sealed panel)".
  - `DECISION_LOG.md:312` places Toronto 2026-05-27/28 "inside the sealed panel window".
  - `EXHAUSTION_REGISTER.md:87` gives panel B as 05-27..06-30, before the 2026-07-31 provenance boundary.
- **Consequence.** The season's tail 2026-05-27..05-31 overlaps the seal. The holdout season therefore **ends at
  2026-05-26 for every count in this note and in the later prereg**.
  - Row 28 ruled the same 2026 season as 2025-12-17..2026-05-26 (`prereg_row28.md:528`).
  - Row 113 used D = 2025-12-01..2026-05-26 (`C:\archive\ruled-out\pm-history-reliability-3a\rule\rule_3a.md:46`).

## 1. Holdout season: outside B's training seasons — YES

- **Season convention.** `season_year(d) = d.year + 1` if d is on or after Dec 17, else `d.year`
  (`docs/research/row28-yearround-history-2026-11-02/scripts/row28_run_v12.py:1447-1449`). So 2025-12-17..2026-05-26
  is **season-year 2026**.
- **B's training seasons.** Arm B trains on Dec 17-May 31 rows of season-years 2021-2025 (`prereg_row28.md:37`, `:219`;
  fold hold-out rule `:199-200`; forward draft §2, training_window "Dec 17 - May 31 of season-years 2021-2025").
  The 2026 fold is "never training" (`prereg_row28.md:38-39`).
- **Disclosed reuse.** Row 28 made the 2026 season descriptive-only because "K112's published dev Brier sums for 2026
  were seen; 2026 Jan–May was already spent as K112 dev data" (`prereg_row28.md:528`).
  - The season is outside B's training, but not fresh: it was already read for K112 dev scoring.
  - The later prereg must count this reuse (DEV_WINDOW_LEDGER) and label the screen selection evidence only. This is
    build 4.

## 2. Inputs for that season: ABSENT — build 1

- **K112** (`STATE_OF_PLAY.md:52`): "Dec-May NBM 07Z and P3d_N_fix inputs absent on WS".
- **Row 28's `not_implemented_descriptive`** includes "fold 2026 / V5.0 sliver (not built, section 1.1)" (committed
  `run/score_result.json`, sha256 `32932ebc…`). Prereg §1.1 gives the reason: "the PIT corpora end in 2025 and the
  12-24 window is covered only for 2021 and 2022" (`prereg_row28.md:92-95`).
  - So B's single builder has no record window for any season-year-2026 date.
  - This is not an integrity failure; the inputs were never built.
- **Present on the WS, but not sufficient.** `C:\t\l47b\corpus_2026.jsonl` (sha256 `d59718a7…`; `count.json` sha256
  `6605f57b…`) holds NBP 07Z rows for 146 target dates 2026-01-01..05-26 (`C:\t\l47b\fetch_dates.txt`).
  - Those are §7 / K112 inputs only (row-28 RUN_LOG line 75).
  - They do not cover 2025-12-17..12-31, and they are not the PIT forecast corpus at hours 7-20 that the B builder's
    coverage rule needs (`prereg_row28.md:63`).
- **Build 1.** Extend the PIT forecast corpora to season-year 2026 (2025-12-17..2026-05-26), from the free official
  NBM archive, inputs only, under the bound coverage rule.
  - Then emit B's frozen forward state (343b state sha) on those rows, outcome-blind.
  - **NBM version split:** V4.3 through 2026-05-05 and V5.0 from 05-06 (`prereg_row28.md:381-387`). The prereg must
    either end at 05-05 (pure V4) or keep 05-06..05-26 as a labelled V5.0 tail.

## 3. L52 price coverage, US10, 2025-12-17..2026-05-26 (counts of events only)

- **Source and method.** Store `C:\t\l52\history\run-20261102T004422Z\raw\<market>\<event date>\<event slug>` (owner GO
  11-01, `STATE_OF_PLAY.md:50`; book mid, history tier only). The counts are from directory names alone; no price file
  was opened.
- **Duplicates.** A "duplicate" date is one with more than one admitted event. Under row 113's rule (`rule_3a.md:55-57`)
  that market-date is excluded and counted.

| Market | Event dates | First | Last | Duplicate dates |
| --- | --- | --- | --- | --- |
| atlanta | 159 | 2025-12-17 | 2026-05-26 | 1 |
| austin | 63 | 2026-03-24 | 2026-05-26 | 1 |
| chicago | 124 | 2026-01-22 | 2026-05-26 | 1 |
| dallas | 160 | 2025-12-17 | 2026-05-26 | 1 |
| houston | 63 | 2026-03-24 | 2026-05-26 | 1 |
| los-angeles | 63 | 2026-03-24 | 2026-05-26 | 1 |
| miami | 124 | 2026-01-22 | 2026-05-26 | 1 |
| nyc | 161 | 2025-12-17 | 2026-05-26 | 1 |
| san-francisco | 63 | 2026-03-24 | 2026-05-26 | 1 |
| seattle | 159 | 2025-12-17 | 2026-05-26 | 0 |
| **US10** | **1,139** | | | **9** |

- **Totals.** 1,130 market-dates after duplicate exclusion, over 161 calendar dates. Denver (out): 63 event dates from
  2026-03-24.
- **Markets per date.** 4 (atlanta, dallas, nyc, seattle) from 12-17; 6 from 01-22; 10 from 03-24.
- **Not counted here: price completeness at the tested hours** (build 2). Row 113 kept 695 of 1,419 market-dates at its
  07/10-local completeness rule. Its per-market exclusions (`real_run.json`, sha256 `205c5ea4…`, lines 26-75) show
  completeness can remove about half. Rule 16 requires the full population rule, so these 1,130 are an upper bound,
  not the population.

## 4. Row 113's label-integrity cap: it RECURS at a 2% cap; a pre-registrable fix exists

- **Cap inputs (rule 17; counts only).** They come from row 113's recorded step-2 counts
  (`C:\archive\ruled-out\pm-history-reliability-3a\outputs\real_run.json:187-239`, `D_partial_counts_by_market_fold`,
  completeness threshold `settlement_ledger.py:34`, at least 18 WU rows).
  - Every partial day falls in 2026-03..05, inside this window. Row 113's D began 12-01, but it had no December
    partials.
  - **Partial WU days, US10:** atlanta 1, austin 2, chicago 1, dallas 3, houston 3, los-angeles 6, miami 4, nyc 1,
    san-francisco 3, seattle 3, so **27**. Missing WU days: 0. Denver (12) and Toronto (1) are out.
  - **Rate:** 27 / 1,130 = **2.39% > 2%**, so a 2% whole-run cap would fail again, as row 113's 2.82% did.
    The numerator is row 113's D count; the denominator is §3's L52 count. Build 3 recounts both on the final
    population.
  - These are completeness counts (row counts per WU day). No label value is needed or was read.
- **Pre-registrable fixes (any one, fixed before freeze, knowing the base rate):**
  - (a) Exclude partial WU days as named, counted, outcome-blind exclusions (completeness is a row count) instead of
    a whole-run HALT cap.
  - (b) Set the cap above the known rate, with the rate recorded in the prereg.
  - (c) A per-market cap with the per-market counts above recorded.
- **Precedent caution.** Row 113 itself has "no successor (no cap redesign, no subset, no 3b)" (`EXHAUSTION_REGISTER.md:488`).
  That binds the 3a market-reliability lever, not B's w step. Master should confirm that the fix applies to this new
  lever.

## 5. Power (rules 16 + 19): UNDERPOWERED at 13-16; a screen is plausible only at 07-12

- **No same-kind, same-distance recorded contrast exists** for B's w on Dec-May history. This would be the first.
  Rule 19 therefore needs a stated conservative bound.
- **Stated bound: row 82's recorded projection against the market** (`PREREGISTRATION_CHECKLIST.md:68-70`). At
  R ≈ 0.95 and 45 dates, power is **0.47 to 0.57 at 07-12** and **0.06 to 0.13 at 13-16**. The checklist says
  such a test "is a SCREEN or does not launch".
  - This is a model-against-market R contrast, not a w-against-placebo contrast. It is used as the bound because
    the recorded w contrasts are not at these hours, dates or this candidate.
  - Recorded w contrasts are context only: L11 dev (43 dates × 11 markets) composite pre-13 mean w 0.067, MDE80
    0.006, and at 13-16 MG-1 blend R 0.9858 against floor-only 0.9845 (`ESTABLISHED_FINDINGS.md:4349-4357`, §10ad).
    X44/X45 record blend − placebo and blend − floor-only intervals that straddle 0 (`EXHAUSTION_REGISTER.md:451-452`).
- **Scaling the bound with √N** (normal approximation; a bound, not a projection):
  - Row 82's dates carry 11 markets each; this season has 4-6 before 03-24 (§3), so the date counts below are
    optimistic for the early season.
  - **13-16:** power 0.13 at 45 dates needs about 250 dates for power 0.5; 0.06 needs about 1,050. The season has
    at most 161 calendar dates, before completeness. **13-16 fails rule 16's power ≥ 0.5 under this bound.**
  - **07-12:** power 0.47-0.57 at 45 dates needs about 40-50 dates for 0.5. It reaches 0.8 at roughly 80-100
    dates. Price completeness at 07/10 kept 695 of 1,419 market-dates in row 113 (`real_run.json`, counts only), so
    07-12 is plausibly at or above the 0.5 floor. It is a SCREEN, not POWERED, until build 2 counts it.
- **Rule 16.** The projection must be recomputed on the full population rule once build 2 exists. That rule is
  price-complete at the tested hours AND label-complete AND B-input-covered AND not a duplicate. No projection is
  final before then. After any look, report the realised/projected SD ratio (rule 19).
- **Consequence for the w step.** The forward draft decides B against S at 13-16. A w step at 13-16 on this season
  cannot be powered. The only feasible w screen is at 07-12, which requires B emission at 07-12 (the builder covers
  hours 7-20, `prereg_row28.md:63`). Whether a 07-12 w screen satisfies rule 4 for a 13-16 candidate is a master
  ruling (build 5).

## Builds (all outcome-blind)

1. PIT forecast corpora for season-year 2026 (2025-12-17..2026-05-26), plus B emission from the frozen 343b state on
   those rows; and the V4/V5.0 tail decision (end at 05-05 or label 05-06..05-26).
2. Price completeness at hours 07-12 (and 13-16, to record the gap) local per market-date, from L52 history point timestamps or counts only. This
   gives the rule-16 population count and the final N.
3. The label-integrity rule fixed before freeze from §4's recorded base rate (rule 17): option (a), (b) or (c).
4. Reuse disclosure: the season was read as K112 dev data (`prereg_row28.md:528`). The prereg needs a DEV_WINDOW_LEDGER
   row and the reuse count, the history-tier selection-evidence-only label (`STATE_OF_PLAY.md:50`), and an owner yes
   through master if SoP:50's data scope requires one.
5. A master ruling on whether a 07-12 w screen satisfies MIM rule 4 for B, whose forward comparison decides at 13-16;
   if not, the w step is INFEASIBLE on this season.

## Master rulings, 2026-11-03 (source: master, relayed by the coordinator; on tip `69c67177f`)

1. **Agreed: rule 4 needs w at the decision hours.** A 07-12 w screen is selection evidence only. It never satisfies
   rule 4 for a 13-16 claim. Build 5 is answered: no.
2. **B's 13-16 path to a market test is power-bound** on everything visible. The history season is infeasible, and a
   forward test at 45 dates has power 0.06-0.13. A B-S PASS at 13-16 is model improvement only.
3. **X93's "no successor" binds the 3a reliability lever only, not B's w.** Confirmed.
