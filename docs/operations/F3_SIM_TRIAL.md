# F3-SIM-1 protocol

Status: draft protocol, not frozen. Read when auditing the simulated fair trial.
This file owns the proposed estimand, arms and statistical rules. The binding values will be in the
[prereg](../research/f3-sim-trial-2026-11/PREREG.md) and its freeze receipt.
[F3_ROLLOUT](F3_ROLLOUT.md) owns gate definitions; [the runbook](f3-maker-expansion.md) owns execution.
No December live expansion or order authority is granted. Any edge claim is conditional on the pre-declared
reward-envelope transfer from F2's US stratum. Existing [charter](EDGE_TRIAL_CHARTER.md) requirements remain binding;
the proposed amendments require their literal decision tokens before freeze.

## Estimand, unit, cluster, universe and dates

- **Unit:** the city-family-date (CFD) = (city, family, `event_date_local`). Its cash flows: fill costs, payouts on the
  venue winner, simulated rewards for the UTC days they accrue, simulated rebates, fees (maker 0), minus the cost reserve
  r_c × filled cost. Operating cost $0 (owner time unmonetised).
- **Cluster:** the event date d. **Π_d** = Σ net over the arm's CFDs with event date d. **Estimand:** μ = E[Π_d] in
  pUSD/day for a $300 sleeve; also reported per band-day.
- **Universe:** T5-R on U36-H; diagnostics as listed in §5.3.
- **Dates:** event dates **11-17..12-24, N = 38** (IR-3).
- **Coverage exclusion (outcome-blind):** a CFD whose quoting interval has Tier A heartbeat coverage < 95% is excluded; the
  base rate over 11-17..11-22 is computed from heartbeats only and recorded at freeze (P1-X7; S7).
- **Inside included CFDs:** an unknown-book minute earns no reward, and any trade at or through our price fills us.
  A condition-day whose VR-5 pagination is incomplete is **excluded outcome-blind and counted** (S8).

## Arms

| Arm | α | Content |
|---|---|---|
| **T5-R** | **0.05 or 0.0375 (OD-02)** | §4.4: F2's quote and book check, U36-H, T+1, 24 h net of G-NWP, no model, no fair-value guard |
| D-6H | none | T5-R restricted to F2's window 14:00–20:00Z |
| D-VAL | none | the other valuation (settlement twin if MTM-surrogate is primary, or MTM twin if settlement is) |
| D-LOW | none | T5-R's policy on the 44 lowest city-families of U80; books with no mid score 0 (k_L = 0); no own-order mid composition. **Envelope cell (N-C, pre-declared):** the 8-cell grid is highest-only, so a two-sided lowest book uses the **highest cell of the same UTC block and region group**, and every D-LOW reward line is labelled `envelope_cell: borrowed_highest` (diagnostic only) |
| D-T1 | none | T5-R subtotal on the default T1 highest rows (January planning only) |
| D-PERCOND | none | T5-R with the $1 minimum applied per condition-day |
| D-QUEUE | none | T5-R with `back_strict_through` instead of `back_at_price` |
| D-UNRES | none | unresolved lots at full loss instead of final mid |

Diagnostics are never adoptable on this evidence. T5-M (model-guided) and T5-L (lowest farming) are Later (L-1).

## Simulator economics: charter §2 map

| Charter item | Implementation |
|---|---|
| Prices | VR-11 Tier A YES books; NO = YES mirror (hourly mirror check) |
| Latency | decision at t sees rows with `received_at_utc ≤ t − L_in`; posts live at t + L_post; cancels at t + L_cancel; each ≥ F0/F2's measured p95 (T1 `ReplayConfig` refuses less) |
| Fees and rebates | maker fee 0; rebate 0.25 × 0.05·p(1−p) × our fee-weighted share of maker volume, aggregated to the account-day before the $1 threshold; fee fields asserted daily |
| Rewards | per minute: M from the book **plus our own resting orders**; S_us from §2.2's formula; C(t) = captured competitor Q (paired upper bound); **share(t) = S_us / (S_us + C(t) + ΔC(τ))** with ΔC(τ) the cell's **additive** envelope (M3), so an empty band scores at most the envelope share after τ_r; daily accrual = rate × Σ share / 1,440; k = 1; minutes with min size > 20 or no terms score 0. **$1 minimum per account-day primary** (S2); per-condition is D-PERCOND |
| Fills | back of queue at our price (`back_at_price` primary; `back_strict_through` is D-QUEUE); complementary mints on the NO token consume the YES book at 1 − q; stale pick-off overlay: if M crosses our resting price within our cancel latency, we fill (π = 1) |
| Adverse selection | from the tape's real trades, plus the cost reserve r_c(cell) = max(2%, UB80 of the per-filled-$ CF-vs-live markout gap on F2 learning sessions); cells F2 does not calibrate take 1.5 × r_c(US); f is reported, never fitted on trial dates |
| Capital | the F2 replica (§4.5) |
| Settlement | venue resolution; unresolved at 12-27 12:00 → final mid (primary) / full loss (D-UNRES) |
| Accuracy gate | §5.8 |

The quote offset, caps and sleeve basis come from F2's freeze receipt, never a remembered example.
WP-11 keeps excluded CFDs in the simulated capital trajectory. World B re-scores on the frozen world-A
trajectory; it does not reselect bands. Payout/redeem lags, maximum book age, `mirror_v1` route policy,
competition rule and midpoint rules are pinned explicitly in prereg economics before freeze.

## Worlds A and B

PASS requires the arm to pass in **both** worlds (intersection–union: p = max(p_A, p_B)).

| World | k (paid ÷ simulated reward) | Envelope | m (live ÷ simulated adverse markout) | Fixed when |
|---|---|---|---|---|
| A (frozen) | min(1, L80(k_learn)), else 1.0 | q20 fitted at freeze on calibration scopes | max(1, U80(m_learn)), else 2.0 | prereg freeze; F2 learning evidence cut 11-15 18:00 |
| B (live-calibrated) | same formula on all F0/F2 sessions to 12-22 | every cell's ΔC scaled by the F2 realised/predicted ratio over all sessions (the analog's measured bias transfers to every cell) | same formula; 2.0 if < 10 fills | frozen code at the final look |

## Transfer grid and held-out rule

Every T5-R stratum is a transfer from F2's US stratum, so the rule is pre-declared **before any entry is counted**:
- **Grid (8 cells):** highest pre-day × 4 UTC blocks (00–06, 06–12, 12–18, 18–24Z) × 2 region groups: **AEA**
  (UTC offset < +5: Americas, Europe, Africa, Middle East, Turkey, Moscow) and **AP** (offset ≥ +5: South Asia, SE Asia,
  China, Japan, Korea, Taiwan, Wellington). The city → group map is explicit in `config/f3/strata.json`.
- **Entry:** a band empty (C ≤ 1) for ≥ 10 min that then gains a new qualifying two-sided level set sized 20–100 within
  ±2¢ of M; ΔC_others(τ) is measured for τ = 1..120 excluding the entrant's levels.
- **Fit:** additive ΔC = A(1 − e^(−τ/τ_r)) and proportional ΔC = κ·S_entrant(1 − e^(−τ/τ_r)) per cell; the dose-response
  test (F2 at 20 shares against RE-1 at 75) picks the shape; the trial uses the lower-20% share envelope.
- **Cell validity:** ≥ 20 public entries in the calibration scopes **and** a held-out check (fit on odd-numbered entries,
  predict the even ones) with median realised/predicted share in [0.67, 1.5]. **Otherwise the cell's reward is 0.**
- **US validation (P1-X2):** on F2's bands (actual book minus own orders), median session realised/predicted share in
  [0.67, 1.5] and ≥ 70% of sessions within 2×. Failure is a KILL.
- **Reporting:** the prereg and every look report show simulated reward by cell. **Verdict wording:** "…conditional on
  the pre-declared reward-envelope transfer from F2's US stratum."

## Kill test

Operationalises the reuse study's one-week kill test (`design/reuse-report-20261108.md`):
- **K-A (own evidence, LFC lane; Wed 11-18):** Σ F0/F2 paid reward ÷ the ×0.1 planning-scale prediction for the same
  band-minutes ≥ 0.5. It needs only LFC-lane paid rewards, so it keeps its date.
- **K-B (public screen; Thu 11-19 18:00, G1):** it needs the `F3-CAL` pack (exported Tue 11-17, pulled Wed 11-18 01:30)
  and the envelope fits (Wed 11-18 after 15:30). Over the calibration days with VR-11 books (11-14..11-16), the median share of covered U36-H
  CFDs whose simulated reward (envelope lower-20%) is ≥ 3 × their simulated fill-loss cost at settlement is ≥ 0.25.
- **Either fails → KILL:** no T5-R freeze; the kill is recorded; capture continues; F3 trading work stops.

## Accuracy gate

- **Population:** every F0 and F2 session through 12-22, plus RE-1 sessions (09-23..09-25) if their books replay through
  the adapter (IR-14). **The binding gate replays every session through `f3_inputs` on VR-11 Tier A books and VR-5
  trades** for the F2 bands (Tier A covers the built-in rewarded YES tokens). Sessions before VR-11 coverage (F0, the
  first learning sessions) count only with an `adapter_parity_receipt_v1` PASS: on overlap minutes where the 88a and VR-11
  polls fall within 10 s of each other, the adjusted mid is equal and the in-band competitor Q is within ±5% on ≥ 99% of
  compared minutes, and ≥ 99% of trades match; otherwise they are reported separately and excluded.
- **Tolerances (one set):** Σ paid ÷ Σ simulated reward in [0.7, 1.3]; fill events |Δ| ≤ max(3, 30%) and ≥ 70% of live
  fills matched within ±5 min on the same band and leg; mean 30-min markout per filled share within 1.0¢; cash
  conservation ≤ 0.00001 pUSD and position identity exact.
- **Minimums:** ≥ 8 sessions, ≥ 6 filled orders, ≥ $3 paid reward. Missing sessions are excluded and counted (never
  "FAIL whole gate"). The report prints the gate's own 80% interval for paid ÷ simulated.
- **Pre-gate (P1-X1, Thu 11-19 18:00; G1):** the same tolerances on F0 + learning sessions with relaxed minimums (the
  relaxed minimums are ruled by the master before the read, `WS-HANDOFF/README.md` §7 K-17).
- It is a check, never a fit: no simulator parameter changes after the freeze. **Gate not met → no PASS.**

K-17 pre-gate minimums remain a master technical input; this draft supplies none.

## Alpha

`F3-OD-02-a: YES` makes T033 cash-diagnostic for December and gives T5-R one-sided alpha 0.05.
`F3-OD-02-b: YES` retains T033's 0.0125 and gives T5-R 0.0375, with the family Holm step after
T033's final look opens. Option b is the declared default. Diagnostics spend no alpha and cannot be adopted.

## Valuation and power

The pre-declared settlement basis for OD-07 and P1-X5 is **`mde_settlement_lots`**, with
**`bands_assumed = 5.5` [A]**, 50 shares per band-day [A] and s per share 0.47 [A]. The capital arithmetic
is 300 / (19.6 + 1.75 × 20), about 5.5 [D], using an assumed filled cost of 20 per band-day [A].
The number of independent b-sample outcomes counts one per (city, family, event date) with at least one
T5-R counterfactual fill; several fills on that event count once. Bands are never estimated from trial-date prices.

MTM marks each lot at fill + 120 minutes. The statistic is mean(MTM net) minus b-hat times filled shares.
Joint resampling of trial dates and b-sample events keeps b-hat uncertainty inside the arm's alpha.
The b sample uses admitted calibration scopes plus development-dated built-in books; the F2-fill transfer
check and K-20 treatment must be stated before freeze. No quarantined study values enter it.

Witness projections below are [D] calculations from WP-12's formula under [A] planning inputs:
alpha 0.05, 38 dates, 50 shares/band-day, s 0.47, MTM day SD 2.5. They are not measurements of a trial.

| Assumed bands [A] | Independent b outcomes [A] | Settlement MDE [D], pUSD/day | MTM MDE [D], pUSD/day | MTM / settlement [D] | Rule choice |
|---|---|---|---|---|---|
| 5.5 | 209 | 22.2 | 22.3 | 1.00 | settlement |
| 5.5 | about 260–310 | 22.2 | about 18.3–20.0 | about 0.82–0.90 | settlement |
| 5.5 | 445 | 22.2 | 15.3 | 0.69 | MTM-surrogate |
| 5.5 | 900 | 22.2 | 10.8 | 0.48 | MTM-surrogate |
| 15 | 209 / 445 / 900 | 36.7 | 60.6 / 41.6 / 29.2 | 1.65 / 1.13 / 0.80 | settlement |

At alpha 0.0375 the MDEs multiply by 1.054 [D]; ratios stay unchanged.
The EF §10r date-mean SD anchor is printed beside the lots basis and decides nothing: it must never
be diversified across bands again. Its derived 15-band MDEs at alpha 0.05 are 28.5/day and 64.6/day
using the central and upper anchors, respectively [D].

`F3-OD-07-rule: YES` selects MTM-surrogate only if the outcome-free projection gives
MDE_MTM ≤ 0.7 × MDE_settlement; otherwise settlement. `F3-OD-07-settlement: YES`, or silence,
selects settlement only. Always print both MDEs and Var(b-hat). A settlement estimate above zero remains
required. P1-X5 compares the selected MDE to 25/day; failure means SCREEN_ONLY.
The assumed b sample about 260–310 does not meet the approximately 430-outcome crossover [D/A].

## Frozen elements

Every design §5.11 element is mapped to a key, producer and receipt in
[PREREG §18](../research/f3-sim-trial-2026-11/PREREG.md#18-frozen-element-checklist).
Missing producers or schema destinations must be resolved before freeze. Source fields and nulls in the draft
are not authority to fill or freeze a value.

## Looks

| Look | Event dates | Read on | Rule (non-binding futility; no α spent) | To owner |
|---|---|---|---|---|
| L0 plumbing | 11-17..11-22 | Mon 11-23 | heartbeat coverage, determinism, counts only (S7) | no |
| L1 harm-7 | 11-17..11-23 | Tue 12-01 | stop if the 95% upper bound of μ (world A) < 0 | only a stop |
| **L2 futility-14** | 11-17..11-30 | **Thu 12-03** | stop if the 90% upper bound < 0; **early-warning numbers to the owner** (kill-only) | **yes** |
| L3 futility-21 | to 12-07 | Thu 12-10 | stop if the 90% upper bound < $1.50/day | only a stop |
| L4 futility-31 | to 12-17 | Sun 12-20 | stop if conditional power < 0.10 | only a stop |
| **Final** | 11-17..12-24 | **Mon 12-28, from 18:00** (resolutions captured by 12-27 12:00; under K-2 (a) the last dates' sealed accrual, the binding gate and world B all start at 18:00, because they read inside the look window and the gate reads F2's confirmation records only after T033's own look opens) | PASS rule, both worlds, binding accuracy gate; Holm step under option (b) | **yes** |

## PASS rule and verdict matrix

**PASS (all of):** the one-sided lower bound of μ > 0 at T5-R's α, in **both** worlds, using the wider of the block-1 and
block-3 moving-block bootstrap (B = 10,000); point estimate ≥ $1.50/day; settlement point estimate > 0; binding accuracy
gate PASS; `f3 replay-check` on two random dates PASS.

<!-- verdict-matrix:start -->
| T5-R outcome | Accuracy gate | Reading |
|---|---|---|
| PASS in both worlds (settlement primary) | PASS | **Edge under the 11-05 definition**, scoped to T5-R, U36-H and these dates, conditional on the pre-declared envelope transfer |
| PASS in both worlds (MTM-surrogate primary) | PASS | **"MTM-surrogate PASS"**: edge as above, with the surrogate named; the owner reads it under OD-22 |
| PASS in world A only | PASS | no edge: "the simulation's assumptions are not supported by live data" |
| Any PASS | FAIL or not met | no edge: "simulator not shown accurate" |
| No PASS, positive point estimate | PASS | no edge; reported with power and MDE |
| Harm, futility or kill-test stop | any | kill recorded (register, archive) |
<!-- verdict-matrix:end -->

## Read scopes and sub-tokens

WP-03 owns dated admission in `maker_core.shadow.admission`; WP-02 consumes it without another date table.
`F3-OD-04-b1: YES`, `F3-OD-04-b2: YES` and `F3-OD-04-c: YES` admit only the stated calibration/LFC purposes.
Run `f3 claimants --scopes calibration` before the first calibration read (P1-E1b).
`F3-OD-03-a: YES` covers U80 trial reads by frozen code with sealed outputs; the master resolves K-2 admission.
`F3-OD-03-b: YES` covers the binding gate/world B inside the LFC lane only after the final window opens.
Read the reserved-window status and run-time claimant list again before any read. Decisions in
[the gate inventory](F3_ROLLOUT.md#decision-inventory) are proposed, not activated here.

## Freeze, accrual, sealed outputs and look guard

The master lands only PREREG.md, with exactly one embedded JSON block and its hash line, via the docs light path
before noon. Freeze time is the landing merge's committer time. The freeze receipt binds that Markdown blob
and the extracted JSON separately; the JSON cannot contain its enclosing Markdown's hash.
Dry-run both the docs light path (`-CheckOnly`) and governance freeze (`--check-only`) by Fri 11-20.
The freeze refuses any non-coverage trial-date read in the chain; a master attestation also covers unlogged host reads.

Before freeze, trial-date plumbing reads heartbeat coverage only, never policy-dependent counts.
After freeze, nightly coverage accrual remains counts-only. Under default K-2(a), sealed simulation accrual happens
inside admitted look windows. K-2(b) needs an explicit master ruling and WP-03 admission change before use.
Only `f3 look` opens sealed outputs; it requires its look admission, freeze receipt, intact read log and claimant check.
Every read carries the prereg hash. No re-cut follows a read; clarifications are dated and outcome-blind.
Rehearse seven-date final accrual, binding gate, world B and inference by Sun 12-20 on calibration inputs.

## Governance integration and exit codes

Phase B incorporates WP-02's reviewed DOC TEXT and validator, WP-12's scoring/reporting and WP-15's gate receipts.
Until the package entry point exists, `f3 ...` denotes a planned governance command, not an executable invocation.
The engine router is executable as `python -m weather.backtesting.f3_cli --help`.
Exit codes: 0 success, 2 gate not passed, 3 refusal, 4 missing/invalid input, 1 error; routed codes pass through.

## Update this file when

Update after a reviewed protocol clarification or approved pre-freeze rule change; reconcile prereg hashes and
the matching producing WP. Frozen statistical rules cannot be silently edited.
