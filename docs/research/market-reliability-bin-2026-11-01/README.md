# Market reliability by bin on our markets: pre-registration (DRAFT)

**Status: DRAFT, NOT FROZEN.** Nothing in this file is binding until master reviews it, pins the run
script's sha256 and writes the ledger row. No reliability score, calibration curve, Brier or log score,
or any other statistic that pairs labels with prices has been computed. The only computation so far is
the presence-only count in [`presence_count.py`](presence_count.py) (section 6).

- Lane L21, workstation, 2026-11-01. Branch `claude/market-reliability-bin-prereg-20261101`, cut from
  `origin/master` `3f3fe50a1f61ac37f225839b2bdc8f9fd0a1dcbf`.
- Scope: the owner approved this on 2026-11-01 at about 10:45, relayed by master, verbatim "yes approved".
  It is a dev-only measurement and an owner-opened exception to the 10-23 model-only scope.
- It reverses the BARRED verdict of the workstation kill check `market-reliability-killcheck-20261101.md`
  (sha256 `c62dd52e…`). That verdict stood only because of the scope, and the owner has now opened the scope.
- What it measures: how well the International Polymarket price works as a forecast. **It is not maker
  P&L.** Maker economics stay CLOSED, and nothing here prices fills, spread or adverse selection.

## 1. Question and the only possible outcomes

The question: on dev dates, is the market's YES price miscalibrated by bin by enough to matter at edge
size? "Enough" means that recalibrating the market alone would remove at least 5% of its own Brier score.

This is a **kill-only** read. It can end in exactly one of these ways:

| Outcome | Meaning |
| --- | --- |
| **KILL at edge size** | Defined in section 5. The verdict is archived and recorded, and the question is closed. |
| **NOT KILLED** | Earns only a follow-up pre-registration. It is never an edge claim, a model improvement or a fair-value result. |
| **UNTESTABLE** | The power gate fails, or the training-score or positive control fails. The verdict is archived and recorded. |

## 2. Kill check and overlap: why this is not already answered

**What the brief asked for**

- **The market's own reliability by bin, on our markets.** Nothing in the register, EF, RF or the ledger
  measures it. STATE_OF_PLAY line 51 says: "**Market price reliability by bin on our 12:** never measured;
  BARRED by the 10-23 model-only scope; **owner question pending**."
- **EF §1c, the bar against booking shrinkage as improvement** (ESTABLISHED_FINDINGS line 700):
  "**Never book a market-shrinkage delta as model improvement.**"
  - Relation: this read blends nothing into our model. It recalibrates the market against itself, so no
    result can be booked as model improvement or edge. This README repeats that bar in sections 1 and 5.
  - EF §1c's recalibration bound (8.829% [−2.467%, +16.494%]) covers maps of our *model* (isotonic, and
    q ∝ p^β with β = 0.55). It is not a market measurement.
- **The MG-1 log-pool exponent question** (register X21): "MG-1 R 1.0017 [0.9990, 1.0077], w 0.008".
  - The kill check's rule quote (rule.md:20): "- g_w = m'^(1-w) * c'^w with w >= 0." Also rule.md:80:
    "no temperature scaling, no recentring".
  - Relation: MG-1's pool fixes the market exponent at 1 − w and forbids temperature scaling. Whether
    m^β with β ≠ 1 beats m was therefore never asked. Arm A3 asks exactly that, and the answer only
    informs whether a future pool should free the market exponent.
- **S30** (register line 232): "Shrinkage: **measured, forbidden as edge** (EF §1c, §5). As a maker fair
  value: **hypothesis, NOT TESTED**".
  - Relation: S30 concerns shrinking *our* forecast toward the market. This read does not shrink anything
    and is not a fair-value test. Maker economics are closed.
- **L10** (register line 268): "**Blending with the market as a pull / fair-value signal, not an edge** …
  On the maker critical path, not a forecast test."
  - Relation: L10 is the maker use. This read is a forecast-calibration test of the market alone, with no
    blend.
- **X24** (register line 429): "r4 $0.03/day [0.00, 0.09], 21 trades … CLOSED (not worth pursuing)".
  **X25** (line 430): "$0.00/day [0.00, 0.00], 0 trades … CLOSED".
  - Relation: these are the dead-bucket floor-impossible mispricings. The deciding population drops
    floor-impossible bands (section 3c), so X24/X25 are not measured again as calibration.

**Neighbours, none of which is a market reliability result on our markets**

- **Register rows 3 and 4, and RF "Recalibration will close the gap — FALSE BY DECOMPOSITION".** These
  decompose the *model* (98.88% resolution, 1.12% reliability).
- **X90, B2** (ledger row 105): "power 0.45 < 0.5 on confirmed WRH dates; 2-fold cross-fit rejected as
  design-shopping". Same family, but thin cities beyond our 12. It is UNTESTABLE, not killed, so it
  neither blocks nor answers this question.
- **X45**: "VOID: a miscalibrated-market artefact of the date-deranged placebo, per review". This is a
  reading of a placebo artefact, not a measurement.
- **R-I / X37.** Temperature maps on NBM-anchored model arms only (scope R9).
- **EF line 1539, centre bias only, 06-03..07-30**: "| **Market** implied centre − settlement | +0.0699 |
  +0.0642 | −0.0057 [−0.1643, +0.1520] |". It is not by bin and not on dev.
- **Register row 5 and L8.** Model skew, and NWP timing.
- **Intake prior (method rule 14).** Every free public signal looks already priced (register §6 X44-X91).
  The expected result is a KILL. This read checks that expectation directly on the price.

## 3. Population, price source and selection

### 3a. Markets

| Market | Status | Why |
| --- | --- | --- |
| atlanta, austin, chicago, dallas, denver, houston, los-angeles, miami, nyc, san-francisco, seattle | **Deciding (US11)** | They are the 11 markets of the dev layout. |
| denver | In | Its dev labels are WU KBKF. The KDEN venue rule applies from 10-23 events only (STATE_OF_PLAY line 60), and that is outside dev. |
| toronto (the 12th) | **Out of the deciding read** | The layout holds no Toronto price (dev scorecard doc: "Toronto has none here"). See open choice O3. |

### 3b. Dates

- The window is local target date ≤ **2026-09-29** (layout `date` = `target_date`; the count found 0
  mismatches and 0 rows after 09-29).
- No row from 09-30..10-15 is read. Austin 10-03 lies outside the window and stays excluded.
- **Primary window W57** is the 57 layout dates 08-01..09-29 (08-16, 09-01 and 09-02 are absent from the
  layout). W43, 08-15..09-29, is the alternative (open choice O1).

### 3c. Price store and code

All local and public; no Polymarket US, no paid source, no fetch.

**Store**

- The workstation dev layout `C:\swarm\v3layout\`, schema `harness_v3_layout/1`, built 2026-10-19,
  harness sha256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`.
- `market.parquet`, sha256 `72d262a71fc75a227d369d5c7d89ded018d0113a26201d37a55b3e0b719d5318`,
  1,218,877 rows. Columns: `row_key, band_index, date, market, p_market_yes`.
- `inputs_snapshots.parquet`, sha256 `0199a026d22ad0ca2076d59818cf489dc529acb2d1f034490c78007bef34578f`.
- `inputs_bands.parquet`, sha256 `78222f8c10e43d1e95b681ff8ebb8b6e5e7670ab70abdf0565880b8f3c187e80`.
- `labels.parquet`, sha256 `1ea636e9e655670012bc3b5d5ef02aec9feda65cc7839434631bbb09c65f067e`, taken from
  the manifest. **Opened only at the single run.**

**Price**

- **m = `p_market_yes`**, the International Polymarket Gamma YES price per band captured with each
  snapshot. This is the same m as the dev scorecard and the mr_sweep. It is never a CLOB
  `last_trade_price` (`rule_rodc_released_p0.md`:74).
- m is used raw and not renormalised, except in arm A3, which uses m̃ = m / Σ_ladder m.

**Code**

- Reader: `weather.reporting.scorecards.dev_scorecard_data.load_layout` (read-only import).
- y: the band indicator `band_index == labels.winner`, exactly as in `dev_scorecard.py` (around line 142).
- Floor-impossible flag: `dev_scorecard.py` lines 149-153 (read-only import). The floor is the max of
  `guidance_physical_floor`, `high_so_far` and `trusted_current_max` at capture time. A band is
  impossible when `kind != "gte"` and `high < floor(floor + 0.5)`.
- **The deciding population excludes impossible bands** (open choice O2). They enter only as a
  descriptive sensitivity row.

### 3d. Snapshot selection, time of day and dedup

1. One snapshot per (market, local target date, local hour 0-23): the **last captured** in that hour, by
   `captured_at_local`, with ties broken by the largest `row_key`.
2. A ladder enters only if the market file holds all `n_bands` of its bands. The count dropped 0 ladders.
3. All 24 local hours are pooled for the deciding read. Blocks 00-06, 07-12, 13-16 and 17-23 are
   descriptive only (open choice O7).
4. The unit of observation is a (snapshot, band) pair. All inference clusters on dates (section 4).

### 3e. Bins

The bins are on m, left-closed, and the last bin is closed on both sides:

```
[0, .02) [.02, .05) [.05, .10) [.10, .20) [.20, .35) [.35, .50) [.50, .65) [.65, .80) [.80, .90) [.90, .95) [.95, 1]
```

These edges are fixed before any read. A bin with fewer than 30 dates carrying an observation is
reported but marked thin. Bins are not merged after the read.

## 4. Statistic and uncertainty

Let r = y − m for each (snapshot, band) row of the deciding population.

### 4a. Descriptive (non-deciding)

These are reported with their intervals. None of them can decide anything.

- Per bin b: n_b, mean m, observed frequency ȳ_b, and **d_b = ȳ_b − mean m_b**, each with the widest of
  the three intervals in 4c.
- Aggregates:
  - linear calibration intercept and slope (OLS y = a + b·m);
  - ECE = Σ_b (n_b / n) |d_b|;
  - the in-sample oracle binned fraction F_bin = Σ_b n_b d_b² / Σ r²;
  - Pearson correlation of g and r for each arm.
- The same per-bin table per hour block, and with floor-impossible bands included.

### 4b. Deciding statistic: three arms, each a cosine Δ (K = 3)

For an adjustment direction g on every row:

```
Δ = Σ g·r / sqrt(Σ g² · Σ r²)
```

**Why this form.** For q = m + c·g with the oracle-best c, the market's summed multi-category Brier falls
by exactly Δ² · Σ r². Δ² is therefore the *exact* fraction of market Brier removed. The oracle c is
generous to the adjustment, so a kill is conservative.

| Arm | g | Fitting |
| --- | --- | --- |
| **A1 linear** | m − (ladder mean of m) | Zero parameters. This is a slope or temperature direction. |
| **A2 binned** | the leave-one-date-out (LODO) mean residual r̄ in m's bin (3e), from all other dates | LODO |
| **A3 power (MG-1 exponent)** | q_β − m̃, with q_β ∝ m̃^β renormalised on the ladder | β is chosen by LODO from grid 0.50..2.50, step 0.01, minimising the summed Brier of the other dates. Ties go to the β closest to 1. |

**Sign**

- A1 is two-sided: miscalibration in either direction counts, so |Δ| is the quantity.
- A2 and A3 are one-sided: a negative Δ means the fitted correction hurts out of sample.

**Inside the bootstrap**

- LODO fits are recomputed inside every draw, from per-(date, bin) sufficient statistics (A2) and from
  per-(date, β) sums of Σ g·r, Σ g² and Σ r² (A3).
- A resampled date's left-out set is every copy of that date.

**Training-score check** (EF §1c "Check the training score first")

- Report the in-sample Brier fraction for A2 and A3.
- If the in-sample A3 Brier at β̂ exceeds the in-sample Brier at β = 1, or the in-sample A2 fraction is
  negative, that is an implementation fault and the read is **UNTESTABLE** until it is fixed.

### 4c. Uncertainty: the wider of date-clustered and block-3 (S31 Clarification 5 scheme)

| Bootstrap | Draws B | Seed |
| --- | ---: | --- |
| Date-clustered iid: resample the window's dates with replacement | 10,000 | `numpy.random.default_rng(20261024)` |
| Non-circular moving block-3 on consecutive layout dates | 10,000 | `default_rng(20261024)`, a separate generator |
| Circular block-3 | 2,000 | `default_rng(20261024)`, a separate generator |

- Intervals are the 2.5 and 97.5 percentiles.
- **Deciding bounds:** the widest upper bound (the max of the three uppers) and, for A1, the widest lower
  bound (the min of the three lowers).
- The reported SE is the max of the three SDs.
- Crossed date × market clustering (EF §5) is reported as a fourth, descriptive interval (open choice O8).

## 5. Kill rule

### 5a. Edge size: D3 Δ_edge = √0.05 = 0.2236

The quote is from register §6, "Edge size, market-residual P0s" (lines 393-395): "the best linear use of
a signal correlated ρ with the market residual cuts the squared error by ρ² … B's 5% gain therefore
needs ρ ≥ √0.05 = 0.224".

**Which applies, and why.** Both apply, and they coincide.

- The brief offers the D3 Δ or the Brier-equivalent 5% cut.
- With the cosine form in 4b, Δ² is the exact oracle Brier fraction, not a linear approximation.
- So Δ < 0.2236 is the same statement as "recalibration removes < 5% of market Brier".
- The rule is stated in Δ so that it reuses D3 and the S31 labels unchanged.

### 5b. Labels (F8 / B2 / S31 Clarification 2 vocabulary)

**UNTESTABLE**, if any of these holds:

- the power gate (section 6) fails;
- the positive control (section 8a) does not reproduce;
- the training-score check fails;
- a null or planted synthetic control fails.

**KILL at edge size** requires all of the following:

- **A1:** widest interval inside (−0.2236, +0.2236);
- **A2:** widest upper < 0.2236;
- **A3:** widest upper < 0.2236.

**NOT KILLED** applies if any arm misses its kill condition.

- It is labelled SCREEN-POSITIVE (descriptive only) if that arm's widest lower bound is > 0, or for A1 if
  |Δ|'s bound excludes 0.
- Otherwise it is NOT KILLED, NOT SCREEN-POSITIVE.
- Either way it earns only a follow-up pre-registration on another window, and never an edge claim.

### 5c. The comparison bars, and what each verdict does and does not touch

| Bar | Quote | Effect of a KILL here | Effect of a survive here |
| --- | --- | --- | --- |
| EF §1c shrinkage | "**Never book a market-shrinkage delta as model improvement.**" | None. Shrinkage stays a measurement. | None. A market-recalibration Δ is not model improvement and cannot be booked as one. |
| MG-1 exponent (X21) | "MG-1 R 1.0017 [0.9990, 1.0077], w 0.008"; rule "- g_w = m'^(1-w) * c'^w with w >= 0." | No future pool needs a free market exponent (A3). | A follow-up prereg may test a pool with a free market exponent. MG-1's frozen rule is untouched. |
| S30 / L10 | "As a maker fair value: **hypothesis, NOT TESTED**"; "On the maker critical path, not a forecast test." | Untouched; maker economics are closed. | Untouched; a forecast-calibration result is not maker evidence. |
| X24 / X25 | "CLOSED (not worth pursuing)"; "CLOSED" | Untouched. Impossible bands are excluded. | Untouched, for the same reason. |

## 6. Power and MDE, outcome-free (method rule 16)

**Script:** [`presence_count.py`](presence_count.py), sha256
`2ba7f2aecd863411a4acc1aa4786bd42e98ee98f5c7e0fa8d0d6ae87c19cc082`. The sha was recorded before the run.

**What it reads**

- Snapshot columns `row_key, market, date, target_date, local_hour, captured_at_local, n_bands`.
- Market columns `row_key, band_index`.
- Price availability from the parquet footer's `null_count` only. No price value is decoded.
- `labels.parquet` is never opened.

**How it ran**

- It applies the full population rule in 3b-3d. The impossible-band exclusion needs `high_so_far`, so it
  is not applied and the counts are an upper bound on bands (see O2).
- The run took 0.62 s with a peak of 327 MB. The rerun was byte-identical.
- Output sha256 `aecbfcc824d851dd8850857f0d05b1e07096a0836cf08a298774cd68a3fe7b6b`, kept on the
  workstation at `C:\t\mrbin\presence_v1.json`.

**Formulas:** power = Φ(0.2236 / SE − 1.96) and MDE80 = 2.8016 · SE.

| Window | Dates | Market-days | Market-date-hours | Band rows | p_market_yes nulls |
| --- | ---: | ---: | ---: | ---: | ---: |
| W57 08-01..09-29 | 57 | 626 | 14,969 | 164,659 | 0 |
| W43 08-15..09-29 | 43 | 473 | 11,352 | 124,872 | 0 |

**Variance tiers**

| Tier | SE assumption | W57 SE / MDE80 / power | W43 SE / MDE80 / power |
| --- | --- | --- | --- |
| T1 empirical | X59 MET-MAX, the widest US mr_sweep interval on this layout: [−0.0395, +0.0571], 43 dates; half-width / 1.96 × √(43 / dates) × √2 for widest-of-three | 0.0303 / 0.085 / 1.000 | 0.0349 / 0.098 / 1.000 |
| **T2 (gating)** | Bernoulli-correlation bound: one independent unit per market-day (all hours and bands of a market-day fully dependent), Var(ρ̂) ≤ 1/n, × deff 2 for cross-market dependence and widest-of-three | **0.0565 / 0.158 / 0.977** | 0.0650 / 0.182 / 0.930 |
| T2b | as T2 but VIF = 1 + (M̄ − 1) · 0.28 (M̄ = 10.98, VIF 3.80) | 0.0779 / 0.218 / 0.819 | 0.0896 / 0.251 / 0.704 |
| T3 (worst, disclosed) | one unit per date | 0.1325 / 0.371 / 0.393 | 0.1525 / 0.427 / 0.311 |

**Gate: PASS** at 0.5, on T2 (0.977) and also on T1 and T2b.

- T3 assumes all 11 markets and all 24 hours on a date are one draw. That contradicts the observed
  cross-market independence behind X59's interval, so T3 is disclosed but does not gate. This follows the
  B2 draft's tiering.
- **The run re-checks the gate on the realised SE before reading Δ.** If the realised widest SE gives
  power < 0.5 at 0.2236, the verdict is **UNTESTABLE**, whatever Δ is.
- Per-block market-date-hours in W57: 00-06 4,345; 07-12 3,738; 13-16 2,504; 17-23 4,382.
- Austin has 56 W57 dates; every other market has 57.
- **Half-split sensitivity** (29 scored dates): T2 0.805, T2b about 0.53. LODO is not chosen for power.

## 7. Multiplicity: DEV_WINDOW_LEDGER

- The published dev reuse count is **203** (2026-11-01), so this read is **204**.
- **Proposed ledger row 106**, type **K**. Rows 1-105 are taken on `origin/master` and on every recent
  remote branch checked on 2026-11-01.
- It is written before the run and counted from opening, one row for the three arms, as rows 93-105 were.
- The kill-only rule needs no adjustment for the three arms: each arm alone must clear its kill bar, and
  a survive claims nothing.
- Row text is drafted for master to add at freeze. This draft does not edit the ledger.

## 8. Pre-registration checklist sections

### (a) Positive control

These must reproduce before Δ is read, on the same layout sha and with `dev_scorecard` default folds.

- **Served versus market R 1.774 (all hours) and 1.526 (00-16).** This is the ledger row 18 control:
  1.774 [1.566, 2.052] and 1.526 [1.369, 1.721]. It must match to 3 decimals.
- **Synthetic null.** Labels are drawn from the categorical m̃ on the real population, seed 20261024. All
  three arms' widest intervals must include 0, and A3's β̂ must lie in [0.90, 1.10].
- **Synthetic planted.** Labels are drawn from q ∝ m̃^1.5. A3's β̂ must lie in [1.35, 1.65], and A3's
  widest lower bound must be > 0.
- If any control fails, the verdict is UNTESTABLE.

### (b) Comparator fairness

The comparator is the market's own raw price m.

**Floor**

- The floor-impossible bands are excluded from the deciding population, so neither m nor any arm gets
  credit for a band the capture-time floor had already ruled out.
- With them included, the result is a descriptive row only.

**Calibration**

- m is left exactly as captured, with no renormalisation, except A3's documented m̃.
- Every fitted arm (A2, A3) is out of sample by LODO, so no arm enjoys an in-sample calibration
  advantage over m.
- A1 has no parameters.
- The oracle c in 4b favours the adjustment, which makes a kill conservative.

### (c) Targeted loss slice

- The slice is the market's own Brier on all bands of complete ladders, all hours, W57.
- The loss atlas `4d094a63eb25…` (ledger row 18, served atlas) locates our model's loss, not the
  market's, so no market slice is pre-targeted. The deciding read is pooled on purpose, and hour blocks
  are descriptive.
- **Expected size:** |Δ| below 0.10 on every arm (intake prior, rule 14). The kill bar is 0.2236.

### (d) MDE and clusters

- **57 date clusters**, 626 market-day units and 14,969 market-date-hours in W57.
- T2 gating: SE 0.0565, **MDE80 0.158**, power at 0.2236 = 0.977.
- W43 has 43 date clusters, MDE80 0.182 and power 0.930. Section 6 gives all the tiers.

### (e) Dev-window reuse

- DEV_WINDOW_LEDGER reuse count **203**; this row counts as **204** (proposed row 106, type K, counted from
  opening).

### Keep / kill rule

The rule is section 5b in full.

- KILL at edge size requires all three: A1's widest interval inside ±0.2236, and the A2 and A3 widest
  upper bounds below 0.2236.
- If any arm misses, the result earns only a follow-up prereg.
- UNTESTABLE applies if any of these fails: the power gate, the positive control, the synthetic controls,
  or the training-score check.

## 9. Run and archive plan

**Run**

- One run, after master pins this README and the run script's sha256.
- The run script is not yet written; it goes beside this file and must not import any B-bound module
  except read-only. It reads the layout through `load_layout`.
- It reads `labels.parquet` only inside that run. Workstation-light, if < 1 min and < 1 GB, else
  `scripts\ops\workstation_heavy.ps1 -Queue`.

**On KILL or UNTESTABLE**

- Copy this README, both scripts, the run JSON and stdout into
  `C:\archive\ruled-out\market-reliability-bin\` with a `SHA256SUMS`.
- Append a CRLF line to `C:\archive\ruled-out\INDEX.md` through a script, never `sed -i`.
- Add the register §6 row and the ledger result.
- Nothing in the archive is ever deleted.

## 10. Open design choices for master

| # | Choice | Draft default |
| --- | --- | --- |
| O1 | Window: W57 (all 57 dev layout dates) or W43 (mr_sweep's 08-15..09-29) | W57. Both pass the gate. |
| O2 | Exclude floor-impossible bands. This reads a `high_so_far`-derived flag at run time, and fix 10's capture-parity defect means the flag is the capture-time one. | Exclude, with "include" as a descriptive row. |
| O3 | Toronto: excluded, or a separate descriptive arm from the 2.97 GB book tapes `data\inbox\tapes-toronto-0801-0929` (book mid, heavy queue, about 60 dates, T2 power about 0.41) | Excluded. |
| O4 | US price: `p_market_yes` (Gamma; its exact semantics, mid versus last, are not documented here) or the book mid from the 32.5 GB US tapes (`dead_bucket.stream_summary`) | `p_market_yes`, matching the dev scorecard and the mr_sweep. |
| O5 | Fitting: LODO, or a chronological half split | LODO. The half split's T2b power is about 0.53. |
| O6 | Arms: K = 3, or fewer (for example A3 alone, the MG-1 question) | K = 3 |
| O7 | All hours pooled as deciding, with blocks descriptive, or a deciding 07-12 block | Pooled |
| O8 | Add the crossed date × market interval (EF §5) as a deciding interval beside the D3 widest-of-three | Descriptive only |
| O9 | Variance tier for the gate | T2 |
