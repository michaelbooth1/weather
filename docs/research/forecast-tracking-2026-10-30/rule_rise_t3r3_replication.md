# RISE-T3R3 replication: a single pre-registered test on fresh dates (ledger row 80, lane L8, 2026-10-30)

**Frozen:** 2026-10-30, before any fresh date (any target date after 2026-09-29) is read for any purpose.

Master ruled that the row 79 KILL was a near miss: underpowered, not null. This rule is the replication master
ordered, and it is a single test.

## 1. Selection disclosure

RISE-T3R3 was chosen **best-of-5** from ledger row 79 (rule `rule_forecast_tracking.md`
`6c4c28aa…270d` on `claude/ledger-79-forecast-tracking-20261030`, result at `72299a4e1fed87ce34512ecdec43c25c31e3a599`).

On the dev window it had the smallest raw p: Δ +0.0447 [−0.0040, +0.0965], one-sided p 0.0345, 43 dates. It
failed BH at q = 0.10 (q 0.155), and its lower bound was below 0.

The five row 79 arms share T_obs, the running max and HRRR, so their positive points are not independent.

RISE-T3R3 is MET-MAX (row 78 sweep) shifted by a station × month × hour constant. The row 79 rule lists that
overlap.

## 2. The test (single; no multiplicity correction)

- **Arm:** RISE-T3R3, type C, x = RM + E[rise].
  - RM is the running max of the receipt-dated METAR rows of local date D observed at or before t_c.
  - E[rise] is the mean of the t3-r3 pmf for (station, month of D, local hour of t_c).
- **Validity:** exactly as row 79 §2.
  - The METAR receipt is at or before t_c.
  - The observation time comes from the raw DDHHMMZ group.
  - The freshness limit is 75 min.
- **Snapshots:** local hours 13-16 only.
- **Statistic:** L3 `rule_mr_sweep.md` §5 (`85f8192c…1956`), run through `mr_sweep.p0_candidate` at pin
  `8bb0f9563582885c4d01d34b67476f2563260e43`.
  - Calibration-matched disagreement placebo: 20 seeds, 20260921 + j, donors within (market, local hour).
  - 10,000 date-cluster bootstrap draws, seed 20261024.
  - Δ = ρ_c − mean ρ_pl, with its one-sided p.
- **Decision:** **REPLICATED iff the one-sided p < 0.05.** This is a single test: there is no BH and no Holm.
  Otherwise the verdict is NOT REPLICATED.
- **Also reported, not deciding:** Δ, its 95% interval, ρ_c, the c-deranged diagnostic and the per-market Δ.
- **Market:** m = the layout's `p_market_yes` (Gamma YES). The tapes' CLOB `last_trade_price` is never used.
- **Tables:** fit table = score table = the fresh dates. A type C arm has no fitted parameter. Only the tilt
  scale σ_s and the placebo donors use the fit table, and both are label-free.
- **Testability floor (replaces L3's 20 dates / 1,000 snapshots for this single test):** at least 10 scored
  dates and at least 1,000 population snapshots. Below that floor the verdict is UNTESTABLE, and an UNTESTABLE
  result is not extended by adding dates.

## 3. Dates, in order of availability (one look, no extension, no optional stopping)

1. **If the owner says yes to Q3** (opening 2026-09-30..10-14): the dates are the 14 target dates
   **2026-10-01..10-14**.
   - The look happens once, after the layout and replay inputs for all 14 exist.
   - Dates without labels or layout rows are dropped, not replaced.
2. **Otherwise:** the first **45** countable forward T+0 dates under the owner's **Q2** answer.
   - The look happens once, **after the claiming tests' looks** (MG-1, then B-1/MG-2).
   - Forward dates are never read before that.
3. **Whichever path is taken**, there is only one look.
   - The 14-date result is final. It is not topped up with forward dates.
   - A NOT REPLICATED or UNTESTABLE verdict closes RISE-T3R3 as a candidate.

**Reserved window:** RISE-T3R3 reads no NBM station guidance. The MG-1 reservation (10-15..11-28) therefore does
not bind it, and t3-r3 is exempt from the retrain window. This rule changes nothing about MG-1, B-1 or MG-3.

## 4. Frozen code and data

### Driver

`C:/t/l8ftr/rep.py`, sha256 `e85732d1726fba9b52d1d1d8fa1e9b0dda8b0f92f2c2eb6da55fe450a14a0a8e`.

- It imports row 79's driver `C:/t/l8ftr/ftr.py`, sha256
  `ab8ced550699d74d734fcd73cfde152e46922ab0983d5228e92086425abaaeaf`, and checks that sha.
- The `look` stage refuses to run without the owner's recorded approval.
- It refuses a second look and refuses dates outside the registered set.
- It lifts the dev scorecard's 2026-09-29 date guard **only** to the registered last date. For path 1 that is
  10-14, which is below the 10-23 WU label rule.

### t3-r3 table

`C:/t/l8ftr/out_rep/t3_table_m8_12.json`, sha256 `1080145c4d4ba454fe83a2f3cb6ded9844c28bd5eefe898659b89056f84ebe8a`.

- **Scope:** 220 cells, covering 11 stations × months 8-12 × hours 13-16.
- **History:** IEM routine non-COR METAR, local dates <= 2026-07-31 (Aug-Dec 2024 and 2025; last history date
  2025-12-31).
- **Construction:** fixed by `tools/research/model_parity/t3_baselines.py`.
- **Months 8-9:** byte-identical to row 79's table (`9abe6882…40e4e`), checked by the driver.
- **Months 10-12:** added so that the fresh dates have cells. They read only 2024-25 history; no fresh date and
  no 2026 date was read to build them.

### Controls already run (no label, no price, no fresh date)

- **Feature check (`devcheck`, inputs only):** the replication feature path reproduces row 79's RISE-T3R3 values on
  all 18,599 dev 13-16 snapshots.
  - The coverage pattern is identical and the maximum absolute difference is 0.0.
  - Output `devcheck.json`.
- **Synthetic check (no real data):** `p0_candidate` with fit table = score table on 14 synthetic dates. It
  detects a planted signal (p 0.001) and passes a null (p 0.28).

### Data plumbing

- **Path 1:** a HARNESS v3 layout (`harness_v3_layout/1`, the builder behind the dev layout,
  `harness_sha256 8db69adc…9f74`) covering only 10-01..10-14, plus the replay inputs in the same record schema.
- **Path 2:** the forward layout, labels and replay plumbing are named in a clarification. It must be committed
  before any forward date is read, and it may change data plumbing only: never the arm, the statistic, α, the
  table, the dates rule or the decision. The driver refuses path 2 until that clarification exists.

## 5. Expected power (honest)

**Method:**

- Row 79's dev effect is Δ = 0.0447, and its SE is 0.0256 from the bootstrap interval (0.0246 from the p).
- The SE scales as √(43 / n).
- Power is for a one-sided test at α = 0.05: 1 − Φ(1.645 − δ / SE_n).

| true δ | SE / power at 14 dates | SE / power at 45 dates |
| --- | --- | --- |
| 0.0447 (dev point, taken at face value) | 0.0449 / **0.26** | 0.0251 / **0.56** |
| 0.0335 (shrunk 25%) | 0.0449 / 0.18 | 0.0251 / 0.38 |
| 0.0224 (shrunk 50%) | 0.0449 / 0.13 | 0.0251 / 0.23 |
| 0 | 0.05 | 0.05 |

**Winner's curse:** the 0.0447 is the best of five correlated estimates, picked after the fact. Its expectation
is biased upward, so a realistic true effect is smaller, and the shrunk rows are the honest planning numbers.

What follows from that:

- **The 14-date path is badly underpowered** (about 0.13-0.26). Its NOT REPLICATED result would be weak evidence
  of no effect, and is stated as such in advance.
- **Even 45 dates give at most about 0.56.**
- Seasonality also matters. October afternoon rises are smaller, which the month-10 cells absorb, but the
  market's error structure may differ from Aug-Sep.

## 6. Outputs

- **Receipt:** run-env HEAD (the pin, clean), rep and ftr shas, t3 sha, layout manifest sha, the registered and
  scored dates, malformed replay lines, the full `p0_candidate` result and the verdict.
- **Per-date rows:** written by `p0_candidate`.
- **Evidence class:** a replication of a dev-window lead. It is never a promotion or edge claim on its own.
