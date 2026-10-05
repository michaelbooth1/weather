# DRAFT, UNSIGNED, DEVELOPMENT: morning-route pre-registration (captured NBM v2 guidance read)

> **DRAFT. UNSIGNED. DEVELOPMENT ONLY.** Written by swarm agent D-MORNING on 2026-10-04 at about 01:45 America/Toronto,
> at master-agent's request. Nothing here is frozen. Nothing here is a reservation, an Î± allocation, a serving change,
> a config change or a merge. Owner approval is required before any part of it takes effect. Every number below
> comes from a development read on dates that 79a, 81a and 111h already inspected. **None of these numbers is evidence.**
> Reservation status re-read: **NONE RESERVED** (`docs/operations/reserved-confirmation-window.md`).
>
> The pre-registration this draft becomes must be committed, pushed and verified on its remote branch before its
> first eligible date. Once it is frozen, its bytes must not change. This draft can be edited until the owner signs it.

## 0. What this is, and what it is not

- **This is not a discovery.** Under a fixed name and a fixed form, this is the known 79a/81a/111h route:
  "the served model under-uses NBM station guidance that production already captures."
  - EF Â§10h (79a): band probabilities read straight off the captured NBM percentiles, with no fitted parameter,
    beat served on matched morning rows.
  - EF Â§10j (81a): scored on every morning row, the gain halves (C1 âˆ’0.006672). Eleven market clusters cap
    confirmation power: about 40% for 81a-sized effects, so under the crossed rule it was not confirmable at any
    season length.
  - 111h = EF 10p (landed on origin/master at 09ff617f, merged into this branch): with parser-v2 values the
    route helps 00-12, harms 13-16 and 17-23, and closes "all hours" for 81a's C1 form. 111h also prohibits choosing
    an hour gate on its table.
- **What the swarm added:**
  - The registered control `r-t5-inc-c1` uses captured `v2_mean` in T5's Gaussian form, with zero parameters, at all
    hours. It scores 00-16 **âˆ’0.0100 [âˆ’0.0179, âˆ’0.0035]** against served (from stratum, all rows, development).
  - T5's NBH candidate adds **no** 00-16 increment over it: paired +0.0027 [âˆ’0.0037, +0.0098], 5/11 markets.
  - T7 c1 shows that captured v2_mean, in a history-fitted Gaussian, carries about 90% of the MOS-consensus morning
    gain.
  - So the morning route needs no new source. It needs the served path to read guidance it already has.
- **This draft fixes** one zero-parameter candidate (MG-1), its serving dependency, its estimand, its power, its
  falsifiers and an INACTIVE reservation proposal. **New dates only.**

## 1. Candidate rule MG-1, fixed verbatim (c1's form, no hour gate)

This is the registered text of `r-t5-inc-c1` (registry sha256 `9bf12872â€¦3f`), restated for prospective use with
production field names. The constants are the only "parameters", and all of them are fixed a priori.

> **MG-1.** At snapshot *t* for a US11 market, local target date *D*:
> - **Eligibility.** The captured parser-v2 NBM read for (station, *D*) must have status `available`. Its bulletin
>   must be the newest one with issue time â‰¤ *t* (24 h lookback) whose v2 parse holds *D*'s maximum. Its
>   availability time is the first time production held the bulletin bytes (`response_received_at`, else
>   `fetched_at`, else `first_seen_at`), and that time must be â‰¤ `captured_at_utc`, asserted. Finite `v2_mean` and
>   `v2_stddev` are required, and so is a captured floor.
> - **Floor.** F = max of the finite captured `guidance_physical_floor`, `high_so_far` and `trusted_current_max`
>   (81a's floor), and B = floor(F + 0.5).
> - **Rule.** Î¼ = `v2_mean`, Ïƒ = max(`v2_stddev`, 1) in native Â°F. X ~ Normal(Î¼, Ïƒ), discretised on integers
>   (mass on [k âˆ’ 0.5, k + 0.5)). H = max(B, X). Band probability = P(H âˆˆ band):
>   - a band's lower edge is âˆ’âˆž if it is `lte` or its low â‰¤ B, else low âˆ’ 0.5;
>   - its upper edge is +âˆž if it is `gte`, else high + 0.5;
>   - a non-`gte` band with high < B gets 0.
>
>   Then renormalise and apply the 81a floor mask. Code reference: `t5_nbh_latest.band_probs`.
> - **Fallback.** If the read is not eligible, or the floored mass is 0, the captured served vector is used unchanged.
> - **Scope.** No fitted parameter, no validity-flag drop, no recency or age rule, no hour gate, no pool with served.
>   It is applied at every local hour.

**Differences from 81a/111h C1, stated so nobody mistakes MG-1 for a re-run of them:**
- MG-1 uses a Gaussian from mean/stddev, where C1 used a linear CDF through five quantiles with normal tails.
- MG-1 does not drop sets that sit partly below the floor. It collapses them onto the floor bucket (H = max(B, X)),
  where C1 fell back to served.

The second difference is why MG-1's afternoon is near-neutral, where 111h C1 harmed it. Development, from stratum:
13-16 âˆ’0.0005 [âˆ’0.0092, +0.0077] and 17-23 +0.0082 [âˆ’0.0078, +0.0205].

**No hour gate (DESIGN rule 8 / the 111h prohibition).** No secondary gated arm is proposed.
- A gate fixed from the bulletin schedule alone would be "active only while the newest bulletin holding today's
  maximum was issued at 00/01/07Z of the issue day, i.e. before 12Z" (EF Â§10l). In local time that ends at 08:00
  Eastern and 05:00 Pacific, mid-morning. It would cut the 06-12 rows where the development read is largest.
- MG-1 already handles the stale afternoon through the floor collapse.
- If the owner still wants a gated arm, it must be a separate secondary arm with its own Î±. Its gate must be written
  only as the schedule-defined condition above, never as local hours read from any table.

**Excluded alternatives (one candidate, one primary, no multiplicity):**
- T7 c1, the same centre with 48 history-fitted b_h/s_h. It scored 00-16 âˆ’0.0122 in development, but it adds a frozen
  parameter file and more parity surface.
- 81a C2, the 50/50 pool.
- Any MOS, NBE or NBH centre. These need new capture, and R-T5-INC/T7 show they add little in the morning.

## 2. Serveability dependency: parser repair first, then a versioned guidance-read stage

**MG-1 is not serveable today.** The swarm read `v2_mean` from the 111h re-derivation (parser HEAD `2e17ce0eb`).
Production still runs parser v1. From the 12Z/13Z/19Z cycles, v1 takes tomorrow morning's **minimum** as today's
maximum: 67% of NBM manifest rows, with no exceptions (EF Â§10k). The v2 repair (83a/83b, `codex/nbm-target-fix-20260921`
@ `2e17ce0eb`, plus the reuse index `62e8ff044`) is built but **not landed**. Mission 83c's stacked integration is
the open step (EF Â§10l).

The serving path is therefore two changes, in this order. Each is versioned.

1. **Land the parser repair** (roll-sensitive, so quiet window only; after 10-13 under the exam-period merge policy).
   - Parser version 2 is recorded per manifest row, and replay dispatches on the recorded version, so old bytes
     replay under v1.
   - The four provenance columns stay diagnostics and are not selectable (83b Part A).
   - **Parity effect:**
     - The served headline model selects no NBM column (EF Â§10h), so its output should not change. A captured-input
       replay of one day must show this before landing.
     - The shadow variant `pooled_f_candidate_miami_current_fallback_v0_1` (artifact `feature_model_hgb_f_pooled_v0_3.pkl`
       selects all 15 `nbm_prob_tmax_*`) was trained on v1-parsed values. After landing it sees v2 values, which is a
       train/serve skew. It must be re-versioned, quarantined or disabled. It is already promotion-blocked.
   - The feature builder's floor-drop of individual NBM values still applies to the *model features*. MG-1 does not
     read those filtered features. It reads the unfiltered v2 read: `v2_mean`, `v2_stddev`, cycle key, issue time,
     valid time and availability time.
   - **Capture requirement:** those unfiltered values must be stored per snapshot as non-selectable diagnostics, or
     be reproducible by deterministic replay from the retained bulletin bytes plus the manifest row. 83b states the
     second already holds.
2. **Add a guidance-read serving stage `nbm_v2_guidance_read_v1`.**
   - It is a post-model distribution stage, so it needs no retrain and no training-feature change.
   - The stage version, parser version 2, the constants (Ïƒ floor 1 Â°F, 24 h lookback, integer discretisation,
     H = max(B, X), floor fields) and the code hash bind into the release manifest.
   - Captured-input replay must reproduce the stage's vector from stored inputs.
   - **During the evaluation window the stage runs in shadow:** it is computed and stored, not served. Served
     therefore stays the comparator.
   - Serving it would be a later promotion through the existing readiness and release gates, after a pass. A pass
     does not authorise promotion by itself.

**Comparator binding.** "Served" means the captured served vector of whatever release served that snapshot, with its
release id recorded.
- If a serving change that touches 00-16 lands inside the window, the look reports pre- and post-change segments
  beside the primary.
- The D-DEFECT evening re-anchoring would change 17-23 and possibly 13-16. The owner should sequence it outside the
  window, or accept that it changes the all-hours guardrail's comparator.

**Owner option (not the default, stated for completeness).** 111h shows that v2 values can be re-derived PIT by replay
from the retained national bulletins, using production's first-seen time. That would allow evaluation from 2026-10-15
without landing. It would evaluate a research re-derivation (the 111h extractor, including its last+1-day indexing
quirk), not the live serving path. The default below requires the live v2 path.

## 3. Dates and season

**First eligible date** = the first local target date *D* that satisfies all of the following:
- (a) *D* â‰¥ **2026-10-15**, i.e. after 2026-10-14, the exam settlement date;
- (b) parser v2 was landed and verified in production before the first T+0 snapshot of *D* in the earliest US
  timezone (Eastern 00:00). Verification means all three capture workers recovered, and manifests for a full prior
  day show `parser_version = 2` with v2 provenance on every US NBM row;
- (c) the MG-1 shadow stage and the unfiltered v2 diagnostics are being captured;
- (d) *D* is after the freeze commit's Toronto date;
- (e) *D* is promotion-countable.

The evaluation counts each countable date after that, with no skipping and no choice.
- **Realistic earliest:** the post-exam batch is ordered (STATE_OF_PLAY critical path 3), and 83c is not yet in it,
  so expect late October at the earliest.
- **Freeze timing:** the freeze must not be timed around convenient dates (reservation file, binding rule 5).

**Season statement.**
- Every eligible date is **out of season.** Per DESIGN Â§6 and EF Â§1c lineage (with EF Â§1b.4 and Â§2), mid-October onward
  is outside the season the served model was trained on. It is also outside the Augâ€“Sep window where 79a, 81a, 111h and
  the swarm measured this route.
- The calendar leaves enough dates. The US daily-high markets list every day, and the planned N of 45 countable dates
  from late October ends around mid-December, later if countable days are missed.
- The season does **not** guarantee the effect transports. Out-of-season, the served model runs about 1 Â°F cool
  (EF Â§2), which might widen the guidance advantage. Autumn guidance spread and diurnal shape differ, which might narrow
  it. This draft predicts neither.
- US DST ends 2026-11-01. Parser v2 is correct in both standard and daylight time (EF Â§10l), and there is no hour gate,
  so the bulletin-to-local-hour shift needs no rule.
- The settlement label is the venue winner. The venue resolves on weather.gov WRH hourly data (EF Â§10c).

## 4. Estimand

**Primary (maker-relevant): MG-1 minus served, mean Brier, US11, local hours 00:00â€“16:59, all rows with explicit
served fallback.**
- Population: promotion-countable market-days.
- Brier is the mean binary squared error over the complete band support.
- Weights: equal snapshot weights within a market-day, then equal market-day weights, with no hour reweighting.
- **Fixed-market date-clustered inference:** the 11 markets are fixed, and dates are resampled as clusters
  (multinomial date bootstrap, 2,000 draws, seed fixed at freeze). The interval is a percentile 95% interval,
  one-sided Î± 0.025.
- **Pass** = the 95% upper bound < 0 **and** â‰¥ 8/11 markets have a negative per-market mean delta **and** the
  estimate is â‰¤ âˆ’5% of the window's own 00-16 served âˆ’ market gap (the EF Â§1d bar).

**Reported beside it, with no Î±:**
- the crossed date Ã— market estimate and interval (81a's statistics, seed 20260921);
- **17-23 reported separately.** It is cosmetic for the maker but real for Brier, and its market Brier is about 0.0008,
  so ratios there are not interpreted;
- the blocks 00-05/06-09/10-12/13-16;
- all hours;
- matched rows, labelled "selected on availability";
- ratio to market, and absolute candidate âˆ’ market;
- the tail lens on the window's own rows (EF tail definition; this panel's share stated);
- the per-market table;
- coverage and fallback reasons;
- served release ids.

**The 2026-09-30 DECISION_LOG guardrails, verbatim** (row 2026-09-30, swarm items):

> fixed-market date-clustered estimand for FUTURE pre-registrations only, with guardrails (never 111h, never
> re-reading 79a/81a/111h, crossed estimate reported beside, per-market and sign-consistency, new dates only,
> amendment states its motivation)

How this draft meets them:
- **Future and new dates only:** Â§3.
- **No 111h re-read:** never 111h, and no 79a/81a/111h date is re-read. All evaluation dates are â‰¥ 2026-10-15.
- **Crossed estimate beside:** yes.
- **Per-market and sign consistency:** part of the pass rule (â‰¥ 8/11).
- **Motivation for the estimand change:** under crossed clustering the 11 market clusters set a variance floor that no
  number of dates removes. EF Â§10j showed this, and the planning in Â§5 reproduces it. The maker quotes exactly these 11
  markets, so the decision-relevant claim is "does MG-1 beat served on our markets over future dates". The claim is
  not about a hypothetical population of markets. The cost is stated: a pass does not generalise to new markets.

## 5. Power (plug-in planning on the BEFORE stratum only; development, sizing, never evidence)

**Method:** registry `d-morning-plan1`; code `tools/research/model_parity/d-morning_power.py`; output
`C:\swarm\out\d-morning\power.json`; HARNESS_SHA256 `8db69adcâ€¦9f74`.
- Population: the before stratum (2026-08-01..08-22), 230 market-days, 21 dates Ã— 11 markets.
- MG-1 = `r-t5-inc-c1` rebuilt exactly. Before-stratum 00-16 estimate âˆ’0.01216 (crossed [âˆ’0.0209, âˆ’0.0037]), 10/11
  markets negative (San Francisco +0.012).
- The harness crossed MDE80 on the before stratum is **0.01246**.
- Planning effects for 00-16: e = half the before-stratum estimate, **0.00608** (the planning effect, per DESIGN
  "effect halved"); 81a-sized **0.006672**; and the full **0.01216**, which is optimistic.
- One-sided Î± 0.025, 2,000 draws, seed 20261004.

| N new dates | Fixed-market MDE80 | Fixed: power at 0.00608 (interval / + â‰¥8 of 11) | Fixed: power at 0.00667 (interval / joint) | Crossed MDE80 | Crossed: power at 0.00608 / 0.00667 / 0.01216 |
|---|---|---|---|---|---|
| 20 | 0.0066 | 0.75 / 0.59 | 0.83 / 0.67 | 0.0123 | 0.28 / 0.33 / 0.79 |
| 24 | â€” | 0.83 / 0.65 | 0.89 / 0.73 | â€” | â€” |
| 30 | 0.0051 | 0.90 / 0.70 | 0.95 / 0.78 | 0.0117 | 0.28 / 0.33 / 0.83 |
| 35 | â€” | 0.94 / 0.76 | 0.98 / 0.84 | â€” | â€” |
| **45** | **0.0044** | **0.98 / 0.80** | **0.995 / 0.86** | 0.0107 | **0.34 / 0.41** / 0.89 |
| 90 | 0.0031 | ~1 / â€” | ~1 / â€” | 0.0097 | 0.41 / 0.47 / 0.94 |
| unlimited | â†’ 0 | â€” | â€” | **0.0085** | **0.54 / 0.62** / 0.97 |

- **The EF Â§10j cap, stated honestly.**
  - Under the crossed estimand, an 81a-sized effect has **41% power at 45 dates**, which reproduces EF Â§10j's ~40%.
  - It has only **62% power with unlimited dates**. The market-only floor MDE80 is 0.0085, larger than every
    half-effect.
  - **80% is unattainable on the crossed estimate** for any effect up to about the full development size. It is reached
    only at the full âˆ’0.0122 after about 30 dates.
- **The fixed-market estimand removes that floor.**
  - The interval condition alone reaches 80% at about 22â€“24 dates for the half effect.
  - With the â‰¥ 8/11 sign condition, joint power reaches **80% at 45 countable dates**. San Francisco's opposite sign
    in development makes the sign rule the binding condition.
  - **Planned N = 45 countable dates, with one look.**
- **Limits of these numbers:**
  - These are plug-in figures from 21 August dates. Out-of-season variance and effect may differ.
  - The from-stratum âˆ’0.0100 is not used to size anything: those dates were read before, so DESIGN rule 7 forbids
    using them for sizing.
  - Coverage in development was 99.3%. The planning does not divide by fill again.
- **17-23, which gets no Î±:**
  - Before-stratum development estimate +0.0020. Crossed MDE80 0.0203.
  - Fixed-market MDE80 at 45 dates 0.0053.
  - Evening harm of about +0.006 or more would likely show in the reported interval.

## 6. Falsifiers and validity conditions (declared up front)

**Falsifiers.** Each one closes or limits the route, and no amendment may rescue it on the same dates.
1. **Route closed.** The primary 00-16 fixed-market estimate is â‰¥ 0, or its 95% upper bound is â‰¥ 0 at N = 45. The
   morning guidance-read route is then closed for US11 under the current rules.
2. **Immaterial.** The estimate is above âˆ’5% of the window's own 00-16 served âˆ’ market gap (the EF Â§1d bar). The effect
   is then real but too small to justify a serving change.
3. **Not fleet-wide.** Fewer than 8 of 11 markets are negative. Report which markets; no serving proposal.
4. **Crossed disagreement.** The crossed point estimate has the opposite sign to the fixed-market one. The result is
   then reported as market-specific, not a pass.
5. **Harm guardrails.**
   - If the all-hours fixed-market interval lies entirely above 0, there is no all-row serving proposal.
   - If 17-23's interval lies entirely above 0, it is reported as evening harm.
   - **In both cases no hour gate may be added post hoc.** A gate needs its own pre-registration on new dates, fixed
     from the bulletin schedule alone.

**Validity conditions.** If one fails, the look is VOID: no pass and no fail. The dates are spent and are not re-run.
- **PIT:** any MG-1 input with availability after `captured_at_utc`, or with `v2_period_kind` other than maximum.
- **Coverage:** 00-16 MG-1 coverage below 90% of snapshots (development 99.3%).
- **Replay:** captured-input replay does not reproduce the shadow vector on 100% of snapshots, to within 1e-12.
- **Window leakage:** any reserved-window date was read before the look.
- **Parser:** a parser version other than 2 appears on any eligible row.

## 7. Proposed reservation block (81a form). INACTIVE; owner decision required

> **PROPOSED, NOT ACTIVE.** Reserve the first 45 promotion-countable local target dates on or after
> {first eligible date per Â§3, â‰¥ 2026-10-15}, for the frozen morning guidance-read candidate MG-1
> (`nbm_v2_guidance_read_v1`, parser v2), bound to {this file's SHA-256 and freeze commit}.
> - **Primary:** equal market-day mean MG-1-minus-served Brier, US11, 00:00â€“16:59 local, all rows with served fallback,
>   promotion-countable, fixed-market date-clustered inference.
> - **Beside the primary:** the crossed date Ã— market estimate, 17-23 separately, and per-market signs (â‰¥ 8/11 required).
> - **Î±:** one-sided 0.025 for the single candidate. There are no interim outcome looks. The sealed pre-boundary
>   campaign ledger is not spent.
> - **Reserved dates:** do not read, enumerate outcomes, score, or substitute them for any NBM guidance-read candidate,
>   or modify MG-1, without a new explicit owner decision. Accrue 45 countable dates with the fixed 11-market support.
>   No model fitting or selection.

**Collisions the owner must resolve before activation:**
- **The trigger does not fit.** The reservation file's trigger is "first retrain candidate frozen". MG-1 is a
  serving-stage candidate, not a retrain, so applying the reservation mechanism to it is itself an owner decision.
- **The reservation is absolute today.** The file's binding rules make a declared window absolute. That would stop MM
  paper scoring on those dates, and it collides with the 88a desk-study decision panel (UTC 10-15..10-30, retention
  hold).
- **A narrow scope is defensible.** Reserve the dates only against reading or modifying the morning guidance-read
  family. MG-1 is zero-parameter and frozen, so unrelated research cannot fit to it. That narrow scope still needs an
  explicit owner exemption recorded in the reservation file.
- **Fallback if not activated:** if the owner declines, run the evaluation as a development read on new dates. It is
  then labelled as such, and no confirmation is claimed.

## 8. What this draft does NOT claim

- **The development reads are not evidence.**
  - The from-stratum âˆ’0.0100 [âˆ’0.0179, âˆ’0.0035] (00-16, all rows) is a development read on 2026-08-23..09-29. 79a, 81a
    and 111h had already inspected those dates. It is not a holdout, a confirmation or evidence of edge (DESIGN rule 7).
  - The before-stratum âˆ’0.0122 was likewise inspected by 81a/111h. It is used here only to size the plan.
- **No market parity.** MG-1 still trails the market in development. From-stratum candidate âˆ’ market is positive in
  every block, with every interval above 0 (00-16 +0.0142 [+0.0100, +0.0188]). A Brier gain over served is not a gain
  over market prices.
- **No serving result.** MG-1 has never run on the live path. Every value came from a research re-derivation of v2.
- **The power figures are plug-in plans.** They are not achieved power, and they assume August variance holds out of
  season.
- **The closed threads stay closed.** Nothing here re-opens recalibration, hour gating, NBH capture for the morning
  (R-T5-INC closes it), or the 111h all-hours C1 verdict. MG-1 is a different, frozen form, and it is evaluated only on
  new dates.
- **No authorisation.** Nothing here authorises landing, serving, promotion, a reservation, Î±, Scheduler work or live
  activity.

## Sources

- `C:\swarm\out\r-t5-inc\report.md` (c1, paired T5 âˆ’ c1)
- `C:\swarm\out\t7\report.md` (T7 c1)
- `C:\swarm\out\refute-pit-t7\c1_shift_results.json` (T7's history-fitted c1, not MG-1, re-scored at +1 h/+2 h
  availability: 00-16 stays LEAD, âˆ’0.0120/âˆ’0.0114)
- `docs/research/guidance-all-hours-preregistration-2026-09-29.md`
- `docs/roadmap/agent-report-2026-09-111h-guidance-all-hours.md`
- `docs/research/morning-guidance-candidate-preregistration-2026-09-21.md` (81a reservation form)
- `docs/operations/ESTABLISHED_FINDINGS.md` Â§1c, Â§1d, Â§2, Â§10c, Â§10h, Â§10j, Â§10k, Â§10l
- `docs/operations/DECISION_LOG.md` (2026-09-30)
- `docs/roadmap/audits/exam-premortem-2026-10-02.md` Â§D
- `C:\swarm\DESIGN.md` rules 7 and 8, Â§6
