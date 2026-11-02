# 3a: history-tier market reliability by price bin (rule, ledger row 113)

**Status: RULE WRITTEN, NOT RUN.** No label has been read and no statistic that pairs a label with a
price has been computed. The run happens only after L21's dev run (ledger row 106, run as frozen once the
11-03 docs head lands) **and** the coordinator's explicit go. Two items need rulings before the run
(section 10).

- Lane L52, workstation, 2026-11-01. Branch `claude/pm-price-history-20261101`. Step 2 was accepted by
  master at `414510e02f75e38c238cc1d52321cdfabc696b54`.
- Assignment: the coordinator's step 3 GO, part 3a. This is lever 1 of the close-the-gap swarm and the
  history-tier analogue of L21 with more power. Ledger row **113** was assigned by the coordinator.
- **Tier: HISTORY. This is SELECTION evidence only.** It reads no dev-window date (07-31..09-29) and no
  date after 2026-05-26. It is never an edge claim, a model improvement or a fair-value result, and it
  is never reused as dev evidence.
- It measures how well the International Polymarket book mid works as a forecast. **It is not maker
  P&L.** Maker economics stay CLOSED.

## 1. The method is L21's, frozen; this file states only the deviations

- **Source:** L21's prereg revision 2, `docs/research/market-reliability-bin-2026-11-01/README.md` at
  `e541ad401110157c71b14b0bfa4589020bb6fe82` (ledger row 106).
- I read only that rule text, and no L21 output, receipt or result.
- Everything not changed below is adopted **verbatim** from it:
  - the bins (3e) and the thin-bin mark;
  - m̃ = m / Σ_ladder m on the full captured ladder, with C1 full-ladder quantities;
  - r = y − m̃, the descriptive set (4a), and the three arms A1/A2/A3 as cosine Δ (4b);
  - the training-score check and F3;
  - the three bootstraps with their draw counts and seeds (4c);
  - D3 Δ_edge = √0.05 = 0.2236 (5a), the verdict labels and the C2 gating order (5b);
  - the synthetic null and planted controls (8a, second and third bullets);
  - the F1/F2 crash and withholding behaviour and the rerun rule (9).

| L21 element | 3a | Why |
| --- | --- | --- |
| Price m = Gamma `p_market_yes` (display price) | m = **CLOB `/prices-history` book mid** at pinned local times (section 3) | This is the only history-tier price. It also *is* the book-mid arm that L21's O4 ruling asks for on [0, .10) (selection evidence only). |
| Window W57, 08-01..09-29 (dev) | **D: event dates 2025-12-01..2026-05-26**, built-ins (section 2) | History tier; no dev reuse. |
| All 24 local hours pooled | **07:00 and 10:00 local pooled** (deciding); 13:00 descriptive | Pinned before the observation cutoff. Section 3 gives the reason for 13:00. |
| Floor-impossible bands excluded (capture-time `high_so_far`) | Excluded **only if** an hourly observation extract up to 2026-05-26 is ruled available (open item O-2) | The history tier has no capture-time floor. Section 4 gives the fallback. |
| A2/A3 fitted leave-one-date-out (LODO) | **Leave-one-calendar-month-out (LOMO)** (section 5) | The coordinator's brief: cross-fit by month or market. Justified in section 5. |
| Positive control 8a (served R 1.774 / 1.526, dev layout) | Replaced by a **label-integrity control** and the **step-2 price-integrity receipt** (section 6) | 8a is tied to the dev layout and cannot be reproduced on history-tier dates. |
| US11; Toronto out (no layout price) | **Built-ins B12 = US11 + Toronto** | History holds Toronto prices; CYYZ is Toronto's WU station. |
| Ledger: dev reuse count + 1 | Row 113, type K, **reads no dev date** (section 9) | History tier. |

## 2. Population

**Deciding population: B12, event dates D = 2025-12-01..2026-05-26.** B12 is atlanta, austin, chicago,
dallas, denver, houston, los-angeles, miami, nyc, san-francisco, seattle and toronto.

**Outcome-free counts** come from the sealed step-2 run's own `events.jsonl` and `tokens.jsonl`. They use
dates, band counts and point counts only, with no price value and no label.

- 1,441 admitted events give 1,430 market-dates over 177 dates.
- By month: 2025-12 142, 2026-01 174, 2026-02 196, 2026-03 247, 2026-04 360, 2026-05 322.
- Every ladder has a non-empty history for every band.
- **Duplicate market-dates:** 11 market-dates (one per market except seattle) carry two admitted events.
  Both events of such a market-date are **excluded and counted**, because which ladder settled cannot be
  told without reading outcomes. That leaves **1,419 scored market-dates**.
- **Season split:** Dec-Feb has 512 events and Mar-May has 929.
  - austin, houston, los-angeles and san-francisco start on 2026-03-24, so they are Mar-May only.
  - denver has one Dec-Feb event.

**Labels: WU daily highs** (`daily_summary.csv`, native unit), exactly as every dev read uses them. The
venue-rule labels (`weather.backtesting.venue_rule_labels`) apply only from the 2026-10-23 events, and
every date in D is earlier, so the WU label *is* the venue-rule label here. Denver uses WU KBKF for the
whole window, because the KDEN venue rule applies only from the 10-23 events. y is the band indicator:
the band whose native range contains `native_high(row)` for the market-date. Band ranges are parsed from
the stored `band_label`/`question`, with "or below" and "or higher" bands open-ended. **The label access
path is open item O-1 (section 10).**

**Excluded and counted, never deciding**

- **2025 before December (NYC/London only).** Every built-in series except NYC starts on 2025-12-04 or
  later. NYC has 308 events in 2025-01-22..2025-11-30.
  - These are **described in their own table and never pooled.** They never enter D, a bootstrap, a
    fold or the verdict, and every line says "NYC 2025, descriptive".
  - London 2025 (309 events) is R1 and is handled as below.
- **R1/R2** (london, paris, seoul, tokyo, shanghai, munich, madrid, beijing, wellington, hong-kong):
  1,334 events up to 05-26.
  - A market-date enters a **descriptive** R table only where a label produced under *that market's
    venue rule* exists for that date in a reviewed extract. Otherwise it is excluded and counted.
  - Expected: none is held on the workstation (the WU folders there are the 11 US stations plus CYYZ),
    so all 1,334 are expected to be excluded and counted.
- Event dates after 05-26 never enter. The fetch guards already refuse 05-27..07-30, anything after
  09-29 and the MG-1 window, and 3a additionally refuses every date after 2026-05-26 in code.

## 3. Price: the history mid at pinned local times

**Source:** sealed run `C:\t\l52\history\run-20261102T004422Z`. SHA256SUMS sha256
`5073afd8f16ad4a7e9eb21b06df7bbaf78464f12ad4101b27440afc9ed31fe71`, manifest sha256
`fdb984606f3b7e39190383292ca296c411c57034fe94588d0d6f9683f86268a7`, receipt sha256
`a9966d9b7771ce6d203366f1774cb88201df9aa18fe35a13ab09cf0eb7d4be5c`. The run re-verifies SHA256SUMS
before reading and refuses on any mismatch.

**Pinned times:** T ∈ {07:00, 10:00, 13:00}, local wall-clock time on the event date, in the market's
`MarketSpec.timezone` (IANA, DST-aware through `zoneinfo`).

- **Deciding:** 07:00 and 10:00 pooled. One ladder snapshot per (market-date, T), so each market-date
  contributes at most two ladders.
- **13:00: descriptive only.** By 13:00 the day's high has often been printed in warm-season afternoons,
  so many bands are already settled by observation. Without a capture-time floor (section 4) those
  near-certain bands would dilute the deciding sums toward a KILL.

**Nearest point and side.** These are fixed now, before any read.

- **Deciding side = AFTER:** the first history point with timestamp t ≥ T and t − T ≤ **120 s**. The
  history is a regular 60 s grid at fidelity 1.
- **Justification:** the step-2 fidelity check (`fidcheck_v1.py` sha256 `177fad63…21cd4`, output sha256
  `1ea5c9af…bf55`) matched the captured book mid best on the after side:
  - after: 93.6% exact, 98.7% within 0.01, p90 |gap| 0.000;
  - before: 83.7% exact, 95.8% within 0.01, p90 0.005.
  - So the point stamped just after T is the best measurement of the mid *at* T.
- **Look-ahead:** at most 120 s, several hours before the afternoon high at 07:00 and 10:00. It is
  disclosed and judged immaterial.
- **BEFORE side** (the last point with t ≤ T and T − t ≤ 120 s): reported as a descriptive sensitivity
  row only.
- **Completeness:** a ladder enters only if **every** band has a point within tolerance on the chosen
  side and Σm > 0. Otherwise the ladder is excluded and counted per market and T.

**Mid caveat (stated in every report)**

- The history is the venue's sampled **book mid**: per fidcheck, median |history − captured mid| = 0.
  It is not a traded price (median |history − last trade| = 0.035, p90 0.64) and not the Gamma display
  price.
- In thin or wide-spread books, and so most of all in the tail bins, the mid can sit far from any price
  at which one could trade.
- How the venue samples a one-sided or empty book is undocumented here.
- So 3a measures the reliability of the **mid as a forecast**, not of an executable price.

## 4. Floor-impossible bands

L21 excludes floor-impossible bands using the capture-time floor. The history tier has no capture. The
floor needs the highest observed temperature up to T, which needs hourly observations for dates in D.

- **If O-2 rules an hourly-observation extract (dates ≤ 2026-05-26 only) available:** apply L21's rule
  exactly, with floor = the max observed temperature with observation time ≤ T. A band is impossible when
  `kind != "gte"` and `high < floor(floor + 0.5)`. C1 then applies (full-ladder m̃; impossible rows
  removed only from the scored sums and the bin tables).
- **Otherwise (fallback, fixed now):** the deciding read runs with no floor exclusion at 07:00 and 10:00
  and is labelled **floor-unadjusted**.
  - The direction of the bias is disclosed: settled-impossible bands carry m̃ ≈ 0 and y = 0, which adds
    to Σg² with little Σg·r, so the bias runs **toward a KILL**.
  - A KILL under the fallback is therefore reported as "KILL (floor-unadjusted; conservative toward
    KILL)". It does not close the question on its own for any downstream use (section 7).

## 5. Cross-fitting: leave-one-calendar-month-out (LOMO)

Choice: A2 (binned LODO mean residual in L21) and A3 (LODO β) are fitted **leaving out the whole calendar
month** of the scored date. There are 6 folds: 2025-12, 2026-01, 2026-02, 2026-03, 2026-04 and
2026-05 (to 05-26). Everything else in the fits is as in L21: the β grid 0.50..2.50 step 0.01, the
summed-Brier objective, ties to the β closest to 1, and per-bin mean residuals.

**Why month, not market**

1. **Dependence.** Neighbouring dates share weather regimes and trader positions, so LODO lets a fit see
   the days on either side of the scored date. Over 177 dates and six months that is no longer
   negligible. A month holds out the whole autocorrelated stretch.
2. **Season.** The question is whether a market-wide price correction carries over in time. Holding
   out a month makes every fit an out-of-season-block forecast, which is the transfer any later use
   would need.
3. **Leave-one-market-out leaks.** The training markets on the same dates share synoptic regimes and
   overlapping traders, so a market-held-out fit still sees same-date information. B12 is also very
   unbalanced (four markets are Mar-May only; denver has a single Dec-Feb event), so market folds would
   differ widely in size and season mix.
4. **Power.** Six folds of 142-360 events each keep every training set at 75% or more of D.

**Inside the bootstrap** (L21 4b, adapted)

- The fits are recomputed in every draw from per-(month, bin) sufficient statistics (A2) and
  per-(month, β) sums of Σg·r, Σg² and Σr² (A3).
- A resampled date's left-out set is every copy of every date in its calendar month.
- The bootstraps resample dates, as in L21: all B12 ladders of a date move together.
- The block-3 schemes use consecutive calendar dates in D.

## 6. Controls and gating (C2 order, enforced in code)

1. **Price integrity.**
   - SHA256SUMS of the sealed run re-verifies.
   - The step-2 fidelity receipt above is cited. It replaces L21's served-R positive control, which
     depends on the dev layout.
   - Failure means UNTESTABLE.
2. **Label integrity.** This is the new positive control. It uses labels only, never paired with a
   price:
   - every scored ladder has **exactly one** band with y = 1 in at least 99% of ladders;
   - the ladder's bands tile the line with no gap or overlap in 100% of ladders;
   - every scored market-date has a WU row.
   Failure means UNTESTABLE, and the counts are printed.
3. **Synthetic null and planted controls** (L21 8a, unchanged), on the real 3a population with seed
   20261024:
   - null, y ~ m̃: all three widest intervals include 0, and β̂ ∈ [0.90, 1.10];
   - planted, y ~ m̃^1.5: β̂ ∈ [1.35, 1.65], and A3's widest lower bound is > 0.
4. **Training-score check and F3** (L21 4b and 9, unchanged).
5. **Power gate on the realised SE:** Φ(0.2236 / SE − 1.96) ≥ 0.5 for **every** arm. SE is the max of
   the three bootstrap SDs.

No Δ value reaches stdout, the receipt or any file until steps 1-5 pass. On a failure the run writes
"B12-HIST: UNTESTABLE" with that step's own numbers and stops. F1/F2 crash safety and withholding apply
unchanged.

**Outcome-free power (method rule 16), from the counts in section 2**

| Tier | Assumption | SE | MDE80 | Power at 0.2236 |
| --- | --- | ---: | ---: | ---: |
| T2 (gating, as L21) | one unit per market-date (1,419), deff 2 | 0.0375 | 0.105 | 1.000 |
| T3 (worst, disclosed) | one unit per date (177) | 0.0752 | 0.211 | 0.845 |

L21's W57 T2 was 0.0565 / MDE80 0.158. Even 3a's worst tier passes the 0.5 gate. The run re-checks the
gate on the realised SE.

## 7. Kill and report criteria (fixed before any read)

**Verdicts.** These are L21 5b with the scope changed. Every verdict line says **B12-HIST** (built-ins,
history tier, D).

| Verdict | Condition |
| --- | --- |
| **UNTESTABLE** | Any of steps 1-5 fails. |
| **KILL at edge size** | A1's widest interval lies inside (−0.2236, +0.2236), **and** the A2 widest upper bound is < 0.2236, **and** the A3 widest upper bound is < 0.2236. Under the section 4 fallback the label carries "(floor-unadjusted; conservative toward KILL)". |
| **NOT KILLED** | Any arm misses its kill condition. It is SCREEN-POSITIVE (descriptive) if that arm's widest lower bound is > 0, or for A1 if |Δ|'s bound excludes 0. |

**What each verdict does (selection only)**

- **KILL:** a history-tier KILL is recorded. It **does not override** L21 row 106. If the dev verdict and
  this one disagree, dev wins, and the disagreement is reported as such. A floor-unadjusted KILL closes
  nothing on its own.
- **NOT KILLED:** this is selection evidence that a dev-window or forward prereg may cite. It is never an
  edge claim, never booked as model improvement (EF §1c), never maker evidence (S30/L10), and never a
  reason to reuse dev dates.
- **UNTESTABLE:** archived and recorded.

**Report spec.** Every table carries the mid caveat (section 3) and the 2025 line. Tables:

1. **Per-bin calibration, tails first.** Bins in the order [0, .02), [.95, 1], [.02, .05), [.90, .95),
   [.05, .10), [.80, .90), then [.10, .20) .. [.65, .80). Columns:
   - n_b, dates with an observation (thin if fewer than 30), mean m, mean m̃, ȳ_b;
   - d_b = ȳ_b − mean m̃_b with the widest-of-three interval;
   - the raw gap ȳ_b − mean m_b as a point column.
2. **Deciding arms:** Δ for A1/A2/A3 with point, all three intervals, the widest bounds, SE and power,
   plus β̂ per fold and the in-sample fractions.
3. **Per market** (12 rows): the bin table collapsed to tails ([0, .10) and [.90, 1]) and middle, plus
   Δ per arm with the date-clustered interval. Descriptive.
4. **Per season:** Dec-Feb and Mar-May, the full bin table and Δ per arm. Descriptive. Seasons with fewer
   than 30 dates in a bin are marked thin.
5. **Per pinned time:** 07:00 and 10:00 separately, and 13:00 (descriptive).
6. **Before-side sensitivity:** the deciding read on the BEFORE side, as a single descriptive row.
7. **NYC 2025, descriptive** (2025-01-22..11-30): the bin table and Δ per arm with the date-clustered
   interval. **Never pooled.** The line reads: "2025 history exists only for NYC (and London, R1); no
   2025 statement is made for any other market."
8. **R1/R2:** counts excluded by reason, and a descriptive table only where venue-rule labels exist.
9. **Exclusion ledger:** duplicate market-dates, incomplete ladders by market and T, missing WU rows,
   and floor-impossible rows when O-2 applies.
10. **Aggregates** (L21 4a): calibration intercept and slope, ECE, F_bin, and the crossed date × market
    interval (descriptive).

## 8. Run plan

- **Script:** `tools/research/pm_price_history/reliability_3a.py`, still to be written.
  - Its synthetic tests and a `--synthetic-only` dry run (no label opened) come first.
  - Its sha256 is pinned by a dated clarification to this rule before the go. It reuses L21's
    `run_reliability.py` statistic code by import or verbatim copy at `e541ad401` (decided at script
    review); no new statistic is written.
  - It does not import the `weather.reporting.scorecards` layout loader, because the population here is
    the sealed history run.
  - No network. Standard library plus numpy, pandas and pyarrow. No B-bound file is edited.
- **Refusals in code:**
  - any event date after 2026-05-26;
  - any label row dated after 2026-05-26 reaching the scorer;
  - a SHA256SUMS mismatch;
  - `--expect-sha` not equal to the script's own sha256.
- **Admission:** a run expected to exceed 1 min or 1 GB goes through
  `powershell -File scripts\ops\workstation_heavy.ps1 -Queue`. That wrapper's `weather_heavy` kind admits
  only allowlisted modules, so the coordinator either allowlists the module or grants a one-off direct-run
  exception with L21's pre-flight conditions (open item O-3).
- **One run.** The rerun rule is L21's: one rerun at a reviewed new sha after a mechanical failure,
  counted once.
- **Receipt:** input shas, the run's SHA256SUMS sha, the label extract sha, the script sha, the git tip,
  seeds, draw counts, library versions, the command line, `peak_working_set_mb` and `seconds`.
- **On KILL or UNTESTABLE:**
  - archive this rule, the script, the run JSON and stdout to
    `C:\archive\ruled-out\pm-history-reliability-3a\` with a `SHA256SUMS`;
  - append a CRLF line to `C:\archive\ruled-out\INDEX.md` by script;
  - nothing in the archive is ever deleted.

## 9. Ledger row 113 (text for the coordinator)

| row | date | lane | branch / code | rule | type | test | result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 113 | 2026-11-01 | L52 | `claude/pm-price-history-20261101` (rule committed before any label read or paired computation; number assigned by the coordinator); code `tools/research/pm_price_history/reliability_3a.py`, sha pinned by clarification before the go; price store: sealed step-2 run, SHA256SUMS `5073afd8f16ad4a7e9eb21b06df7bbaf78464f12ad4101b27440afc9ed31fe71` | `docs/research/pm-history-reliability-3a-2026-11-01/rule_3a.md` (sha256 in the freeze report) on L21 prereg rev 2 `e541ad401110157c71b14b0bfa4589020bb6fe82` (method adopted verbatim except section 1's table) | K | **3a: history-tier market reliability by price bin, B12, event dates 2025-12-01..2026-05-26.** Book mid from public `/prices-history` at 07:00/10:00 local (after side, ≤ 120 s), L21 bins and arms A1/A2/A3, LOMO cross-fit, kill at Δ_edge 0.2236. Labels: WU daily highs ≤ 05-26 (access O-1). Reads **no dev-window date**; selection evidence only, never edge; NYC 2025 descriptive, never pooled | pending (run after row 106's dev run and the coordinator's go) |

## 10. Open items needing rulings before the run

- **O-1, label access.**
  - The label files are `data/wunderground/<icao>/daily/daily_summary.csv` for the 11 US stations and
    CYYZ.
  - **Their date range cannot be established from name, manifest or folder:** the name carries no date,
    there is no manifest, and the folder is the rolling per-station collector path. **So they were not
    opened.**
  - File-system metadata only (not contents): on the workstation, every one of those files has an mtime
    of 2026-08-12. That suggests no row after 08-12, but it is not one of the permitted ways to establish
    a date range.
  - Proposal: a reviewed extractor, run once, reads each station file and **emits only rows dated ≤
    2026-05-26**. It never writes, prints or counts a later row, and refuses if it cannot parse a row's
    date.
    - Its output carries a per-file SHA256SUMS and a manifest stating the date range.
    - 3a reads only that extract.
    - Alternatively, master names an existing date-bounded label extract.
  - Writing this rule needed no label read.
- **O-2, hourly observations for the floor (section 4).** The same date-bounded extract approach, over
  hourly WU observations ≤ 2026-05-26, if master wants the floor applied. Otherwise the section 4
  fallback stands.
- **O-3, admission.** Allowlist the 3a module for `workstation_heavy.ps1`, or grant a one-off
  direct-run exception on L21's pre-flight terms.

## 11. 3b is not started

The K112-contingent atlas, planned at step 2, starts only if K112 reaches PASS/CONSISTENT, under its own
ledger row. It would score a v5.0-aware centre candidate against these Dec 2025..May 2026 mids, and it
must state the 2025 NYC/London-only limit. Nothing for 3b has been written or computed.
