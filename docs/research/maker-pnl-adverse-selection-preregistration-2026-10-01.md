# Maker P&L sign under adverse selection, T+1/T+2 stratum — pre-registration (2026-10-01)

Status: **FROZEN at the commit that adds this file, before any input below is transferred or read.** The owner asked
for this study on 2026-10-01; it is swarm item 10, "fill-toxicity desk study, top research priority"
([DECISION_LOG](../operations/DECISION_LOG.md) 2026-09-30). The owner chose the pilot plus forward-panel structure and
ruled that raw 88a capture on the exam's calibration days is readable. Any change after an input is read requires a dated
clarification below. Each clarification states whether data had been seen and why the change is being made.

**Related, not replaced.** The 89a desk study ([pre-registration](fill-toxicity-desk-study-preregistration-2026-09-23.md))
asks a different question: whether loss is *concentrated* around events on **same-day** bands. Its panel A is spent
(`INCONCLUSIVE`, 0 of 480) and its panel B (09-25..10-08, same-day) is scored once after 10-08. This study simulates only
**T+1/T+2** quote-minutes, the population 89a's Clarification 12 says it does not simulate. It never computes anything on
same-day minutes, so 89a panel B is not pre-read.

**The swarm range is not an input.** "+1.7 to -5.7 pUSD per band-day"
([swarm audit](../roadmap/audits/swarm-audit-2026-09-30.md) item 10) has no derivation anywhere in the repository. It sets
no threshold here, and the result is never described as "inside" or "outside" it.

## Question

For the maker we would actually run, does adverse selection on its fills outweigh spread plus reward, making P&L per
band-day negative? That maker is RE-1's quote under the owner's selection amendment (EF §10m).

## Stratum (frozen)

- **Bands:** every band that 88a captured (`data/maker_evidence/`) and that is **local T+1 or T+2** at the quote minute:
  the event date minus the market's local date is 1 or 2. Same-day minutes are discarded on parse, before any statistic.
- **Quote:** two-sided, **75 shares per leg**, each leg at a **1.5 c target distance** from the size-adjusted midpoint
  (levels below the band's reward minimum size excluded). The price is snapped outward to the tick, as RE-1 quotes.
  The YES bid and the NO bid are both buys. The leg is re-placed at full size at each book sample. The sampling clock,
  5-minute maximum rest across missing samples, and partial-fill lifecycle are those of 89a's Clarifications 2 and 3.
- **Admissible quote-minute.** All of the following must hold:
  - both sides are displayed and the book is not crossed;
  - the size-adjusted midpoint is in [0.10, 0.90];
  - **displayed depth is at least max(75, reward minimum size) on each side within the maximum spread** (the owner's
    amendment);
  - reward terms are captured at or before the minute and are at most 60 minutes old (88a reward records, 89a
    Clarification 11 decoding);
  - the reward minimum size is at most 75, and 1.5 c is within the maximum spread.

  A non-admissible minute has no quote, fills, reward or exposure.
- **Band-day:** a condition on one local quote date, included if it has at least 60 admissible minutes. Its value is the
  **sum** over its admissible minutes. A per-60-quote-minute rate is reported beside it.

## Estimand

For band-day `b`, horizon `h`:

    NP_h(b) = Rew(b) + Spread(b) - AS_h(b)
    Spread(b) = sum over fills of q * |m_t - p|                 (half-spread captured against the markout mid at fill)
    AS_h(b)   = - sum over fills of q * s * (m_{t+h} - m_t)     (s = +1 YES bid, -1 NO bid in YES-price terms)

- `Rew(b)` = sum over admissible minutes of `rate/1440 x share_many x k_share`. `share_many` comes from the canonical
  estimator (`weather.market.reward_share_estimate`), scoring the virtual quote against the displayed book.
- **Primary `k_share = 0.3`.** Displayed books do not show competitors' reaction to our posting. Mission 111f measured
  k 0.27-0.32 over about one-hour sessions, and the signed Clarification 2 uses 0.3. Sensitivities, never replacing the
  primary: `k_share` = 0.5 and 1.0 (1.0 is the paid-day k ≈ 1.05 from EF §10m, measured with competition already
  present).
- **Fills:**
  - primary rule: conservative (a public print strictly through the leg price, filling `min(print size, remaining)`);
  - sensitivity: optimistic (at or through the leg price);
  - prints come from 88a's public trade channel (`last_trade_price` events).
- **Markout mid:** two-sided top-of-book midpoint from 88a books, the last sample at or before the target, within 120 s.
  The settlement mark is 1 or 0 from the settlement ledger's `polymarket_winning_band` (venue resolution). A fill whose
  event has no ledger row leaves the settlement panel and is counted.
- **Horizons:**
  - primary: **S = settlement** (inventory held to resolution, as RE-1 held it);
  - secondary: +5, +30 and +120 minutes against the markout mid.

  A horizon-`h` fill missing its mark leaves that horizon's panel with its band-day's whole value for that horizon
  (loss and exposure removed together, the same idea as 89a Clarification 7).
- **Excluded from the primary, reported beside it:** maker rebates (pool share unmeasured, EF §10o; makers pay no fee),
  capital cost of the posted collateral, and simultaneous-fill limits across markets (EF §10n).
- **Primary estimand:** `θ = mean over band-days of NP_S(b)`, in pUSD per band-day.
- **Key secondary:** the flip ratio `AS_S / (Rew + Spread)`; above 1 means adverse selection flips the sign. Also reported:
  `θ` at each mid horizon, every component separately, the per-market table, and both fill rules.

## Inference

- **Primary interval:** a 90% date-clustered bootstrap (dates resampled, 10,000 draws, seed 20261001). This is the
  fixed-market date-clustered form the owner allowed for future pre-registrations on 2026-09-30. Its guardrails apply:
  - the crossed date × market interval is reported beside it;
  - per-market point estimates are reported;
  - only new dates are used.
- **Sign consistency:** among markets with at least 5 band-days, at least two thirds must have a point estimate of the
  verdict's sign. Otherwise the verdict carries `_NOT_SIGN_CONSISTENT` and acts as `INCONCLUSIVE`. If the crossed
  interval crosses zero while the primary does not, the verdict carries `_NOT_ROBUST_TO_MARKET_CLUSTERING`; the flag is
  reported, not overridden.
- **Clusters:** fewer than 10 date clusters gives `UNDERPOWERED`, which forces `INCONCLUSIVE` (the binding rule of
  `execution_tape_markout.py` and 89a).
- **α:** this study draws nothing from the [campaign ledger](../operations/CAMPAIGN_LEDGER.md), which governs only the
  sealed forecast panel.

## Part 1 — variance pilot (descriptive; cannot decide)

- **Dates:** quote-minutes on local dates 2026-09-24..2026-09-28 (88a starts 2026-09-25 06:34Z) for bands whose **event
  date is 2026-09-26..2026-09-29**. That gives at most 4 date clusters.
- **Never read:** any 88a UTC day from 2026-09-30 on, and any band whose event date is 2026-09-30 or later. That would
  read the exam's quote panel (09-30..10-13) or settlements of its dates.
- **Output:** everything in the estimand section, with the 90% intervals above and a t-interval across date means
  (df = number of dates − 1) beside them. The label is fixed: `PILOT_INCONCLUSIVE_BY_CONSTRUCTION`. No pilot number may
  be cited as the maker's P&L sign.
- **Its only function** is `σ_d`: the across-date standard deviation of the date-mean `NP_S`, used by the power rule.
- **Owner-discretionary stratum, descriptive only:** fills of the owner's manual orders recorded by the 110x journal
  (`data/manual_order_journal/`, UTC dates up to 2026-09-29, events up to 2026-09-29). Their journal-computed markouts
  and allocated reward are reported in a separate, labelled table. They are **never pooled** with the simulation and never
  enter `σ_d` or any verdict, keeping the journal's boundary that its output stays outside automated evidence.

## Part 2 — decision panel

- **Dates:** T+1/T+2 quote-minutes for bands whose **event date is 2026-10-17..2026-10-30** (14 dates), all 12 markets,
  same stratum and rules.
- **Read order:** the panel is read only after its last event settles **and** after the second exam candidate's single
  look (scheduled 2026-10-31, STATE_OF_PLAY). Its quote panel 10-16..10-29 overlaps these dates. Nothing in the panel is
  read before both.
- **Retention:** production must retain the 88a sealed segments for UTC 2026-10-15..2026-10-30 and the settlement ledger
  rows until transfer. A pruned segment is a coverage gap, never imputed.
- **Power rule (fixed now; run on the pilot before any panel read):**
  - `σ_up` = the upper 90% chi-square bound on the pilot's `σ_d`;
  - `δ = 1.0 pUSD per band-day`, the minimum effect that matters for the sign question. It is fixed here, not taken from
    the pilot.
  - `N_req = ceil(((1.645 + 0.842) · σ_up / δ)²)`, which is 80% power for the 90% two-sided interval to exclude zero
    when |θ| = δ.

  The branch is fixed by `N_req`:

  | `N_req` | Panel |
  | --- | --- |
  | ≤ 14 | the panel stays 14 dates |
  | 15-28 | extended to `N_req` consecutive event dates from 2026-10-17, recorded as a dated clarification before any panel read |
  | > 28 | declared `UNDECIDABLE_AT_DELTA`; run descriptive only, with the achieved MDE reported |

  If the pilot has fewer than 2 surviving dates, `σ_d` is undefined and the panel runs at 28 dates.
- **Verdict (primary, NP at S, `k_share` 0.3, conservative fills):**

  | Verdict | Condition |
  | --- | --- |
  | `MAKER_NEGATIVE` (adverse selection flips the sign) | 90% upper bound of θ < 0 |
  | `MAKER_POSITIVE` | 90% lower bound of θ > 0 |
  | `INCONCLUSIVE` | otherwise, with the achieved MDE stated |

  Flags as in the inference section. A sensitivity (`k_share` 1.0, optimistic fills, rebates) that changes the verdict
  is reported as such and never replaces it.

## Exclusions and defects

- Undecodable records follow 89a Clarifications 9 and 10. Unsealed 88a segments are never read.
- A band-day is excluded, with its reason listed, if fewer than 90% of its local quote-day minutes have a book capture.
  This covers the 2026-09-29 19:50-20:05 power-outage gap.
- The owner's own resting orders appear in the displayed book as competition (this lowers our share, which is
  conservative). Their prints count like any other print.
- **Default for gaps:** an implementation choice that changes no estimand, threshold, horizon, inclusion or date is made by
  the implementer. Take the option that lowers `Rew` or raises `AS`, document it in the report, and continue.

## Inputs and transfer

Production exports the inputs and copies them to the workstation by scp, never through git. The exact selection,
refusals and checksums are in the [transfer manifest](maker-pnl-adverse-selection-transfer-manifest-2026-10-01.md). The
analysis records this file's freezing commit and the manifest's `SHA256SUMS` hash in its report.

## Clarification 1 (2026-10-01, before any input is transferred or read; owner-approved)

**Data seen: none.** No input named in the transfer manifest had been transferred or read when this clarification was
committed. The pilot, the panel and the 110x journal stratum are all unread. The owner approved these four changes on
2026-10-01 after reviewing the frozen design. They bind exactly like the rules above and supersede them where they differ.
The 111f share table cited in point 4 is prior repository evidence, already committed, not an input of this study.

### 1. Both fill rules bind a positive verdict

The frozen text calls the strictly-through rule "conservative". That holds only if fills are benign. If fills are toxic,
fewer fills means less adverse selection, so strictly-through is the *optimistic* rule for the sign question. The two
rules are renamed by what they do:

- **strictly-through** (formerly "conservative"): a print strictly through the leg price fills; fewer fills;
- **at-price** (formerly "optimistic"): a print at or through the leg price fills; more fills.

Both use the same bootstrap draws (same seed, same resampled dates). **`MAKER_POSITIVE` requires the 90% lower bound of
θ above zero under both rules.** `MAKER_NEGATIVE` still reads the strictly-through rule (the frozen primary), and the
at-price result is reported beside it. When the two rules' intervals do not exclude zero on the same side, the verdict
carries `_FILL_RULE_DEPENDENT`; the flag is reported, not overridden. The power rule (point 3) and `σ_d` use
strictly-through.

### 2. RE-1-faithful reported stratum: the first fill ends the band-day

The frozen quote re-places both legs at full size at every book sample, so a band-day can accumulate unbounded inventory.
RE-1 did not quote that way: a session stopped on its fills. A second stratum is reported beside the continuous one:

- Same bands, admissible minutes, quote, prices, reward terms, markouts, horizons and exclusions as the continuous stratum.
- **Band-day inclusion** (at least 60 admissible minutes) is decided on the untruncated admissible minutes, so whether a
  band-day enters never depends on when or whether it filled.
- **The first qualifying print** of the band-day, in venue-timestamp order, fills `min(print size, 75)` on its leg. Both
  legs are withdrawn at that print's timestamp. Later prints fill nothing, including prints at the same timestamp, and no
  quote is re-placed that band-day. Inventory is therefore at most 75 shares per band-day.
- **Reward** accrues on admissible minutes before the minute that contains the first fill. That minute and every later
  minute earn nothing (the option that lowers `Rew`). A band-day with no fill quotes all its admissible minutes, as in the
  continuous stratum.
- The per-60-quote-minute rate uses the minutes actually quoted.
- Every estimand, both fill rules, every `k_share`, and the interval and flags are computed for this stratum. Its label
  from the verdict table in point 4 is reported as `RE1_FAITHFUL_<label>` and never replaces the primary. A disagreement
  with the primary is reported as such. It does not enter `σ_d` or the power rule.

### 3. Power rule, undecidable panels, and δ

**The quantile.** `σ_d` is the sample standard deviation (denominator `n − 1`) of the pilot's date-mean `NP_S` under the
primary (continuous stratum, strictly-through, `k_share` 0.3), over the `n` surviving pilot dates. `σ_up` is its
**one-sided** 90% upper confidence bound:

    σ_up = σ_d · sqrt((n − 1) / c),   c = the 0.10 lower-tail quantile of chi-square with n − 1 degrees of freedom

It is not the upper end of a two-sided 90% interval, which would use the 0.05 quantile. For example, `n = 4` gives
`c ≈ 0.584` and `σ_up ≈ 2.27 σ_d`. `N_req` keeps its frozen formula, with `z` values 1.645 and 0.842 and no
t-correction. The report states `n`, `σ_d`, `c`, `σ_up` and `N_req`.

**`UNDECIDABLE_AT_DELTA` (`N_req` > 28).** The panel runs on its base 14 event dates, 2026-10-17..2026-10-30. It is not
extended, because an extension cannot reach the required size. Every estimand, interval, stratum and flag is computed and
reported, and the outcome is labelled `UNDECIDABLE_AT_DELTA`. The verdict table is **not** applied:
- no `MAKER_POSITIVE`, `MAKER_NEGATIVE` or `INCONCLUSIVE` label is issued;
- no point estimate or interval may be cited as the maker's P&L sign.

**Achieved MDE (every panel outcome).** `MDE = (1.645 + 0.842) · SE`, where `SE` is the standard deviation of the
10,000 date-clustered bootstrap draws of θ under the primary. It is reported in pUSD per band-day beside δ. Beside it
goes the planned MDE `(1.645 + 0.842) · σ_up / sqrt(N)` at the panel's date count `N`. This definition also serves the
frozen "achieved MDE stated" for `INCONCLUSIVE`.

**δ = 1.0 pUSD per band-day is kept, on a design basis.** It is derived from the frozen quote, not from any data:

- **One lot's half-spread.** One full fill of the 75-share lot at the 1.5 c target distance captures
  75 × 0.015 = 1.125 pUSD of half-spread. δ = 1.0 is 1.33 c per share on one lot, below the 1.5 c half-spread the quote
  is built to earn. A true θ smaller than δ is smaller than the edge of a single full fill. It cannot be told apart from
  the quote-construction choice itself, and is not worth deciding the sign for.
- **Capital at risk.** RE-1's reserve model caps posted collateral per band at 75 pUSD (EF §10n). δ = 1.0 is about 1.3%
  of that cap per band-day. Edges smaller than that are within the range the excluded terms could move: capital cost,
  unmeasured rebates and simultaneous-fill limits.

Neither the pilot, the swarm range, nor any RE-1 or 111f number sets δ.

### 4. Decay-curve k, and what `MAKER_NEGATIVE` means

**Decay-curve `k` (reported beside `k_share` 0.3; never a verdict input).** The reward term for a minute uses `k(τ)` in
place of `k_share`:

    k(τ) = curve(τ) / curve(0)                    for τ = 0..59
    k(τ) = mean of curve(50..59) / curve(0)       for τ ≥ 60

- `curve(τ)` is `mean_share_many` by minute since posting, from `series_re1_journal_books.curve` in
  `docs/roadmap/agent-report-2026-09-111f-reaction-diagnostic-amendment-1.json` on branch
  `codex/reaction-diagnostic-20260930`. Its committed LF blob has sha256
  `30e68a615649430cd3f43e3b06a2efd3440c80c6259243dc9e6182bb4e67be91`. The τ ≥ 60 tail value is about 0.215.
- **τ** is whole minutes since the band-day's first admissible minute. It never resets across withdrawals or
  non-admissible gaps. Resetting would return k to 1 after every gap; not resetting lowers `Rew`.
- It applies to both strata and both fill rules.
- **Caveat, reported with it:** the curve thins from 9 episodes at minute 0 to 2 at minute 59. Its later minutes mix
  fewer, longer sessions from one campaign on 3 dates and 4 markets.

**Verdict table.** It supersedes the Part 2 table. The primary is the continuous stratum, NP at S, `k_share` 0.3.

| Verdict | Condition | Reads as |
| --- | --- | --- |
| `MAKER_POSITIVE` | 90% lower bound of θ > 0 under **both** strictly-through and at-price | positive even under the pessimistic choices below |
| `MAKER_NEGATIVE` | 90% upper bound of θ < 0 under strictly-through | **"not shown positive" under stacked pessimism**, not "the maker loses money" |
| `INCONCLUSIVE` | otherwise, with the achieved MDE stated | — |
| `UNDECIDABLE_AT_DELTA` | `N_req` > 28 (point 3) | no sign label; descriptive only |

`MAKER_NEGATIVE` is read under stacked pessimism:

- `k_share` 0.3, which already removes about 70% of modelled share;
- rebates excluded;
- the settlement horizon holds every fill to resolution;
- the owner's resting orders count as competition;
- every implementation gap is resolved toward lower `Rew` or higher `AS`.

It therefore means the maker is **not shown positive** under those assumptions. It is never reported as proof that the
maker loses money. The report places the `k_share` 1.0, decay-curve `k`, at-price and rebate sensitivities next to it.

The flags `_NOT_SIGN_CONSISTENT`, `_NOT_ROBUST_TO_MARKET_CLUSTERING` and `_FILL_RULE_DEPENDENT`, and the
`UNDERPOWERED` rule, apply as stated above. `_NOT_SIGN_CONSISTENT` and `UNDERPOWERED` still force `INCONCLUSIVE`.
