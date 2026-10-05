# DRAFT, UNSIGNED, DEVELOPMENT: hour-gated guidance composite pre-registration (gate fixed from the NBM bulletin schedule)

> **DRAFT. UNSIGNED. NOT FROZEN.** Written by swarm agent D-HG on 2026-10-04 at about 03:00 America/Toronto, as the
> Phase-4 item DESIGN rule 8 allows. It is not a reservation, an α allocation, a serving change, a config change or a
> merge. Owner approval is required before any part of it takes effect.
>
> **Rule 8 / EF §10p compliance.** The gate in §1 comes from the NOAA NBM text-bulletin (NBP) issuance schedule and
> product definition alone, as recorded in EF §10k and §10l. It was **not** chosen, tuned, compared or scored on the 111h
> table or on any table. D-HG scored nothing. It registered no rule, called no harness `score()`, and read no candidate
> deltas, no per-hour results and no block results to set the gate. The only table reads were the list of the 11 market
> names, used to assign time zones. The 111h block results (EF §10p) and the swarm's block results are **not** used
> anywhere in this draft: not for the gate, not for the effect size, not for power.
>
> Reservation status re-read: **NONE RESERVED** (`docs/operations/reserved-confirmation-window.md`).

## 0. Why this exists, and how it relates to MG-1

- EF §10p (111h) closed the US all-hours guidance route. Overnight and morning guidance helps, and the stale bulletin
  hurts once the day is under way. 111h named an hour-gated guidance candidate as "the obvious next idea", ruled that it
  "needs a new pre-registration on new dates", and ruled that "these results may not be used to choose its hours".
- The swarm's morning draft, D-MORNING's **MG-1** (`d-morning-v2-guidance-prereg-draft.md`), deliberately has **no**
  hour gate. It handles the afternoon through the floor collapse H = max(B, X). That draft says that if the owner wants a
  gated arm, it must be a separate arm with its own α, and its gate must be written only as a schedule-defined condition.
  **This document is that arm, HG-1.**
- HG-1 uses MG-1's exact read inside the gate and leaves served unchanged outside it. Outside the gate, HG-1 − served is
  0 by construction. The question HG-1 answers: *is the gain of the captured NBM v2 guidance read, restricted to the
  hours when NBM's newest issuance still forecasts today's maximum, real on new dates?*

## 1. The gate, derived from the bulletin schedule only

**Schedule facts (EF §10k, §10l; NOAA NBP product key; no table involved):**

1. NBP `TXN` values valid at 00Z are maxima. For mainland US stations, the 00Z maximum belongs to the preceding local
   date. The NBM maximum window for local date D is **12Z on D to 00Z on D+1** (parser v2 selects the 00Z token whose
   12Z window start and 00Z label fall on D).
2. NOAA publishes complete `TXN` rows at 00/01/07/12/13/19Z (02Z and 18Z return 404).
3. Bulletins issued at 00/01/07Z on UTC date D carry D's maximum. Bulletins issued at 12/13/19Z on D do **not**: once
   the maximum window has opened, NBM stops issuing a forecast of that maximum. The 19Z bulletin on D−1 does carry D's
   maximum.
4. So the last NBM issuance that forecasts D's maximum is the 07Z cycle on D. From 12Z on D the newest bulletin holding
   D's maximum is 07Z, so afternoon and evening guidance is 5 to 24 hours old by construction (EF §10l).

**Gate G (fixed, one form only):**

> **G.** A T+0 snapshot for local target date D is **inside the gate** iff `captured_at_utc` < **12:00:00Z on calendar
> date D** (the opening of NBM's maximum window for D). Equivalently, the snapshot is taken before NBM's issuance
> schedule stops forecasting D's maximum.

- **What the gate depends on:** only the snapshot's capture time and target date, both already captured. It needs no
  new capture, has no parameter, reads no table, has no local-hour list, and uses no age threshold.
- **Local clock, by arithmetic from UTC (not chosen):**

| Market time zone (markets) | Gate open, local, until DST ends 2026-11-01 | Gate open, local, from 2026-11-01 |
|---|---|---|
| Eastern (atlanta, miami, nyc) | 00:00–07:59 | 00:00–06:59 |
| Central (austin, chicago, dallas, houston) | 00:00–06:59 | 00:00–05:59 |
| Mountain (denver) | 00:00–05:59 | 00:00–04:59 |
| Pacific (los-angeles, san-francisco, seattle) | 00:00–04:59 | 00:00–03:59 |

  NBM cycles are in UTC, so the local close moves one hour earlier when DST ends. That is a property of the schedule.
  No rule is added for it.
- **Guidance is present for the whole gate.** At local midnight (04Z–08Z on D) the newest D-maximum bulletin is 19Z
  D−1, 00Z D or 01Z D, and the 07Z D bulletin follows. MG-1's eligibility rule (newest bulletin issued ≤ t, ≤ 24 h old,
  v2 parse holds D's maximum) selects among these.
- **Sensitivity reported beside the primary, with no α:** the publication form G′. G′ closes the gate at the first
  production availability time (`response_received_at`, else `fetched_at`, else `first_seen_at`) of any NBP bulletin
  issued at or after 12Z on D, rather than at 12:00Z itself. G′ differs from G only by the 12Z bulletin's publication
  and fetch latency. It is reported as a sensitivity and is not a second candidate.

**Excluded gate forms, and why (all excluded a priori, none scored):**
- **Any local-hour list,** for example "06-09" or "00-12". Choosing one would require reading a table, which rule 8 and
  EF §10p forbid.
- **A bulletin-age threshold** ("use guidance while the bulletin is ≤ k hours old"). k would be a free parameter, and
  any value of it would be chosen with knowledge of 111h.
- **"While the newest D-maximum bulletin is a same-day 00/01/07Z issuance".** This is true all day from 07Z, so it is not
  a gate.
- **Gating to 13Z or 19Z bulletin arrivals.** Those bulletins hold no D maximum (fact 3), so they carry nothing to gate
  on.

## 2. Candidate HG-1, fixed verbatim

> **HG-1.** At T+0 snapshot *t* for a US11 market and local target date *D*:
> - **Inside gate G:** apply **MG-1** exactly as fixed in `d-morning-v2-guidance-prereg-draft.md` §1, with the same
>   eligibility, floor, Gaussian read, discretisation and fallback. In summary:
>   - μ = `v2_mean`, σ = max(`v2_stddev`, 1) °F, X ~ N(μ, σ) on integers;
>   - B = floor(F + 0.5), where F is 81a's floor (max of the finite captured `guidance_physical_floor`, `high_so_far`
>     and `trusted_current_max`);
>   - band probability = P(max(B, X) ∈ band), renormalised, then the 81a floor mask;
>   - ineligible reads, or zero floored mass, fall back to served.
> - **Outside gate G:** the captured served vector, unchanged. The 81a floor mask is applied as in every candidate, which
>   is the zero-parameter floor rung.
> - **Nothing else.** No fitted parameter, no pool with served, no recency rule, and no second gate.

If the owner rejects MG-1's Gaussian form before freeze, HG-1 inherits whichever single zero-parameter read is frozen
instead. It never gets a different read from MG-1. 81a's C1 form is not an HG-1 variant. It would be a second
candidate, with its own α.

## 3. Serveability

Serveability class: **zero-parameter serving stage, with a landing dependency.**
- HG-1 inherits all of MG-1's dependencies (MG-1 §2):
  - the parser v2 repair (83a/83b, `2e17ce0eb`, plus the reuse index `62e8ff044`) must land first. Production still
    runs v1, which after 13Z reads tomorrow's minimum (EF §10k);
  - the live shadow variant that selects `nbm_prob_tmax_*` must be re-versioned, quarantined or disabled;
  - the unfiltered v2 read must be stored per snapshot, or be reproducible from retained bytes plus the manifest row.
- **Stage:** HG-1 is a post-model stage `nbm_v2_guidance_read_gated_v1`. It is MG-1's stage plus the gate predicate.
  The gate constant (12:00Z on D), the stage version, parser version 2 and the code hash bind into the release manifest.
- **During the evaluation window it runs in shadow:** it is computed and stored, not served, and captured-input replay
  must reproduce it.
- **The gate needs no new capture.** It reads `captured_at_utc` and the target date only.
- **Interaction with other proposals:**
  - The D-DEFECT evening re-anchoring (S1/S2/S6/S7) and the D-RUNG1C S3–S5 bundle change 13-23 local. That is outside
    gate G in every US time zone, so they cannot change HG-1 − served (0 outside the gate).
  - Inside the gate the comparator is served. A serving change that touches 00-08 local inside the window gets the
    pre-/post-change segments reported beside the primary, as in MG-1 §2.

## 4. Dates and season

**First eligible date** = the first local target date D that meets all of the following:
- (a) D ≥ **2026-10-15**, i.e. strictly after 2026-10-14;
- (b) parser v2 landed and verified in production before the first T+0 snapshot of D in the Eastern time zone. This uses
  MG-1 §3(b)'s definition: all three capture workers recovered, and a full prior day of manifests with
  `parser_version = 2` and v2 provenance on every US NBM row;
- (c) the HG-1 shadow stage and the unfiltered v2 diagnostics are captured point in time for D;
- (d) D falls after the freeze commit's America/Toronto date;
- (e) D is promotion-countable.

Every countable date after the first eligible date counts, with no skipping or selection. The freeze must not be timed
around convenient dates.

**Season.**
- All eligible dates are **out of season** (DESIGN §6, EF §1c lineage). They lie outside the August–September window
  where 79a, 81a, 111h and the swarm read this route, so transport of the effect is not assumed.
- After 2026-11-01, gate G covers one local hour fewer in every zone (table in §1). That is about 33% of 00-16 local
  hours, down from about 39%, on an equal-market average with uniform snapshot cadence. Clock arithmetic only.
- US daily-high markets list every day, so the calendar allows the planned N.

## 5. Estimand

**Primary:**
- **Quantity:** HG-1 minus served, mean Brier over the complete band support, US11, **T+0 snapshots inside gate G**,
  all rows with explicit served fallback.
- **Population:** promotion-countable market-days.
- **Weights:** equal snapshot weights within a market-day, then equal market-day weights.
- **Inference:** fixed-market, date-clustered. The 11 markets are fixed, and dates are resampled as clusters (2,000
  draws, seed fixed at freeze). The interval is a percentile 95% interval at one-sided α (§7).
- **Why the population is the gate:** the gate is fixed a priori from the schedule, so restricting the population to it
  is not a data-driven selection. Outside G the delta is identically 0, so a wider population only dilutes the estimate.

**Pass** requires all three of the following:
- the 95% upper bound < 0;
- ≥ 8/11 markets with a negative per-market mean delta;
- an estimate ≤ −5% of the window's own **in-gate** served − market gap (EF §1d bar).

**Reported beside the primary, with no α:**
- the crossed date × market estimate and interval (81a statistics, seed 20260921);
- HG-1 − served over **00:00–16:59 local**. This is the maker block, directly comparable with MG-1's primary;
- all hours;
- **17-23 separately**, which is identically 0 by construction and stated as such;
- gate form G′ (§1);
- the pre- and post-DST segments;
- matched rows, labelled "selected on availability";
- the ratio to market and absolute HG-1 − market;
- the tail lens (EF definition, with the window's own share stated);
- per-market table;
- coverage and fallback reasons;
- served release ids.

**The 2026-09-30 DECISION_LOG guardrails, verbatim** (row 2026-09-30, swarm items):

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never
> re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only,
> amendment states its motivation)

How this draft meets them:
- **Future pre-registration, new dates only:** §4. All dates are ≥ 2026-10-15.
- **Never 111h, no re-reading 79a/81a/111h:** no date those missions read is scored. The gate was set without the 111h
  table. Power uses only 81a's published interval and D-MORNING's published ratio (§6), not a re-read.
- **Crossed estimate reported beside:** yes.
- **Per-market and sign consistency:** part of the pass rule (≥ 8/11).
- **Motivation for the estimand change:** EF §10j shows that 11 market clusters set a variance floor under crossed
  clustering that no number of dates removes. The maker quotes these 11 markets, so the decision question is whether
  HG-1 beats served on these markets over future dates. A pass does not generalise to new markets.

## 6. Power and MDE80 (sizing only; computed **without** scoring the gate on any table)

Scoring HG-1 on the 111h table, even on its before stratum, would score an hour gate on that table, which rule 8
forbids. **No plug-in power for HG-1 was computed.** The figures below are an analogy built from published numbers only:
- 81a's C1, US, 06:00–09:59, 42 dates, crossed: −0.006672 [−0.011525, −0.002373] (EF §10j). From that interval, the
  crossed SE ≈ 0.00233 and the crossed MDE80 ≈ 0.0065 at 42 dates.
- The fixed-market to crossed MDE80 ratio from D-MORNING's published MG-1 plan is 0.41 at 45 dates and 0.54 at 20
  dates.
- **Planning effect:** half of 81a's C1, **0.00334** per in-gate row ("effect halved", DESIGN §6), with the full 81a
  effect 0.00667 beside it. Neither the 111h block results nor the swarm's block results are used.

| N countable dates | Fixed-market MDE80, ratio 0.41 / 0.54 | Interval-only power at 0.00334, ratio 0.41 / 0.54 | Same at 0.00667 |
|---|---|---|---|
| 45 | 0.0026 / 0.0034 | 0.95 / 0.78 | ≈1 / ≈1 |
| **60** | **0.0022 / 0.0030** | **0.99 / 0.89** | ≈1 / ≈1 |
| 90 | 0.0018 / 0.0024 | ≈1 / 0.97 | ≈1 / ≈1 |
| crossed, any N | market floor; EF §10j: 37% (C1) at half effect with unlimited dates | **80% unattainable** | — |

- **What this means:**
  - The ≥ 8/11 sign condition is **not sized**: per-market power cannot be estimated without scoring the gate. In
    D-MORNING's plan it was the binding condition, cutting joint power from 0.98 to 0.80 at 45 dates. Expect the same
    here, or worse, because the gate holds fewer rows per market-day than 00-16, and fewest in the Pacific (4–5 local
    hours).
  - **80% joint power cannot be shown** for HG-1 at any N before the look. It may be unattainable within one season.
  - Under the crossed estimand, 80% is unattainable at the planning effect (EF §10j cap; 11 market clusters, about 40%
    power for 81a-sized effects).
- **Planned N = 60 countable dates, one look.** This is the interval-only 80% point under the pessimistic ratio, plus a
  margin for the sign rule. From late October, 60 dates run to about late December. The owner may instead set N = 45 to
  align with MG-1's window (§7), accepting about 0.78 interval-only power at the pessimistic ratio.
- **Limits:**
  - 81a's window (06:00–09:59) is not gate G. The gate runs from midnight to 04:00–08:00 local, so it includes overnight
    rows that 81a never covered and excludes 81a's later rows in the west.
  - Out-of-season variance and effect are unknown.
  - These figures are an analogy, not achieved or plug-in power.

## 7. Multiplicity with MG-1 (owner choice before freeze)

HG-1 and MG-1 draw on the same dates and the same guidance read, and HG-1 equals MG-1 inside the gate. Running both as
confirmatory arms is a two-candidate family. The owner chooses exactly one option **before** freeze:
- **(A) MG-1 alone (D-MORNING default).** HG-1 is not frozen, and this draft lapses.
- **(B) HG-1 alone.** One-sided α 0.025. Pick B if the owner prefers the strictly no-afternoon-harm construction to
  MG-1's floor-collapse handling.
- **(C) Both on the same window.** Bonferroni, one-sided α 0.0125 each, with N = max of the two plans. Both MG-1's
  power and HG-1's fall. Neither draft has re-sized for this.
- **(D) Sequential.** HG-1 runs on a later window that starts after MG-1's last date, with its own α 0.025.

Whatever the option, no gate may be added to MG-1 after unblinding, and HG-1's gate may never be changed after
unblinding.

## 8. Falsifiers and validity conditions

**Falsifiers.** None may be rescued by amendment on the same dates.
1. **Route closed.** The primary estimate is ≥ 0, or its upper bound is ≥ 0 at planned N. The schedule-gated guidance
   route is then closed for US11 under current rules.
2. **Immaterial.** The estimate is above −5% of the in-gate served − market gap.
3. **Not fleet-wide.** Fewer than 8/11 markets are negative. Report the markets; no serving proposal follows.
4. **Crossed disagreement.** The crossed point estimate has the opposite sign. The result is then reported as
   market-specific, not a pass.
5. **DST split.** The pre- and post-2026-11-01 segments have opposite-sign point estimates. This is reported, not a
   failure. It forbids any later local-hour re-gating on these dates.

**Validity conditions.** If one fails, the look is VOID: no pass and no fail. The dates are spent and are not re-run.
- **PIT:** any MG-1 input inside the gate has availability later than `captured_at_utc`, or `v2_period_kind` ≠ maximum.
- **Gate integrity:**
  - any in-gate row has HG-1 ≠ MG-1 after the floor;
  - any out-of-gate row has HG-1 ≠ served after the floor;
  - a gate is evaluated on any clock other than `captured_at_utc`.
- **Coverage:** in-gate eligible read on fewer than 90% of in-gate snapshots.
- **Replay:** captured-input replay does not reproduce the shadow vector on 100% of snapshots to within 1e-12.
- **Parser:** a parser version other than 2 appears on any eligible row.
- **Window leakage:** any reserved date is read before the look.

## 9. Proposed reservation block (81a form). INACTIVE; owner decision required

> **PROPOSED, NOT ACTIVE.** Reserve the first {60 | 45 under option C} promotion-countable local target dates on or after
> {first eligible date per §4, ≥ 2026-10-15; under option D, the day after MG-1's last reserved date} for the frozen
> schedule-gated guidance-read candidate HG-1 (`nbm_v2_guidance_read_gated_v1`, gate G = captured_at_utc < 12:00Z on
> target date D, parser v2), bound to {this file's SHA-256 and freeze commit}.
> - **Primary:** equal market-day mean HG-1-minus-served Brier, US11, T+0 snapshots inside gate G, all rows with served
>   fallback, promotion-countable, fixed-market date-clustered inference.
> - **Beside the primary:** the crossed date × market estimate, 00-16 local, 17-23 (identically 0), gate form G′, and
>   per-market signs (≥ 8/11 required).
> - **α:** one-sided 0.025 (0.0125 under option C). There are no interim outcome looks. The sealed pre-boundary
>   campaign ledger is not spent.
> - **Reserved dates:** do not read, enumerate outcomes, score, or substitute them for any NBM guidance-read or
>   hour-gated guidance candidate, or modify HG-1 or its gate, without a new explicit owner decision. Accrue N
>   countable dates with the fixed 11-market support. No model fitting or selection.

**Collisions the owner must resolve before activation** (the same as MG-1 §7):
- The reservation file's trigger is "first retrain candidate frozen", and HG-1 is a serving stage.
- A declared window is absolute today. It would collide with MM paper scoring and with the 88a desk-study panel
  (UTC 10-15..10-30).
- A narrow, family-scoped exemption is defensible, because HG-1 is zero-parameter and frozen. It must be recorded in
  the reservation file.
- If the owner declines, the run is a labelled development read on new dates, and no confirmation is claimed.

## 10. What this draft does NOT claim

- **No result.** There is no development number for HG-1, by design: none was computed. Any HG-1 figure computed on the
  111h table, or on dates 79a/81a/111h read, would breach rule 8 and must not be cited for or against this draft.
- **No evidence that gating helps.** This draft makes no prediction about whether HG-1 beats MG-1, or whether the
  in-gate effect transports out of season.
- **No market parity claim.** A Brier gain over served is not a gain over market prices.
- **No authorisation.** Nothing here authorises landing, serving, promotion, a reservation, α, Scheduler work or live
  activity.
- **Closed threads stay closed:** the 111h all-hours route, NBH capture for the morning (R-T5-INC), recalibration, and
  any local-hour re-gating on read dates.

## Sources

- `docs/operations/ESTABLISHED_FINDINGS.md` §1c, §1d, §10j, §10k, §10l, §10p
- `docs/roadmap/agent-report-2026-09-111h-guidance-all-hours.md` §12 (hour-gated candidate "not authorized", "none was
  computed")
- `docs/research/guidance-all-hours-preregistration-2026-09-29.md` (no hour gate)
- `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md` (81a reservation form)
- `docs/research/model-parity-swarm-2026-10-04/d-morning-v2-guidance-prereg-draft.md` (MG-1, its §2 dependencies and
  its §5 power table, used only for the published fixed-to-crossed ratio)
- `docs/operations/DECISION_LOG.md` (row 2026-09-30, swarm items)
- `docs/operations/reserved-confirmation-window.md` (NONE RESERVED)
- `C:\swarm\DESIGN.md` §1 rules 7–9, §6
