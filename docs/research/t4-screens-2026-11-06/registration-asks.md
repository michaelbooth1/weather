# T008 proposed pre-read registrations

DRAFT FOR MASTER LANDING. No data read is authorised by this document. Master assigns row IDs;
do not reserve an occupied numeric row or count these proposals as landed. The branch base is
`22b3dd835e72f69d9e9fee5744a5c570c7f9a5eb`. See [intake](README.md) for definition sources and caveats.

## Proposed ledger row text

Paste into DEV_WINDOW_LEDGER only after resolving the stated intake questions and recording
the actual standalone rule sha and code pin. Pending means not run, not a candidate verdict.
Each candidate is one new K row. Published reuse count: at least 212; master reconciles other
landings before assigning the three actual denominators (213/214/215 only if none intervened).

| # | Date | Lane | Branch @ tip | Rule (sha256 or commit) | Type | Candidate | Headline delta [95%] | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MASTER ASSIGNS | 2026-11-06 | T008-H2 | codex/t4-screens-20261106; intake base 22b3dd835e72f69d9e9fee5744a5c570c7f9a5eb | proposed-screen plan docs/research/t4-screens-2026-11-06/registration-asks.md; standalone executable rule and sha required before read | K | Dev-only H2 market screen, proposed v0.5.12 vector with pre_lockin_same_day_floor enabled, disabled twin as ablation; US11 h00-16, burn-in 08-01..08-14, score 08-15..09-29; separate from signed October H2. Intake mechanism and identity unresolved. Outcome-free replay/receipt/mass/full-donor power checks first, then market-residual P0, w only if P0 survives, tradability under its own later registration. No October or trial data | pending; no data read | pending; HOLD until standalone rule frozen and intake admitted |
| MASTER ASSIGNS | 2026-11-06 | T008-NBM | codex/t4-screens-20261106; intake base 22b3dd835e72f69d9e9fee5744a5c570c7f9a5eb | proposed-screen plan docs/research/t4-screens-2026-11-06/registration-asks.md; standalone executable rule and sha required before read | K | Proposed type-C v2_mean tilt on captured normalised market mid, US11 h07-12, same burn-in/scored dates. Receipt-valid parser v2 only. X22 is a different log-pool; this member inherited a rule closure, requiring explicit intake mechanism and price-input ruling. Outcome-free coverage and full-donor power first; P0 before w; no rerun of exhausted log-pools | pending; no data read | pending; HOLD, inherited closure not yet reopened |
| MASTER ASSIGNS | 2026-11-06 | T008-RP2 | codex/t4-screens-20261106; intake base 22b3dd835e72f69d9e9fee5744a5c570c7f9a5eb | proposed-screen plan docs/research/t4-screens-2026-11-06/registration-asks.md; new standalone dev rule and sha required; frozen history rule 2a438306214ece68e6e58d6f288765dc8addace7d21b89a02a22141e9c2d3e70 unchanged | K | Existing R-P2 class-matched P3d_N_fix versus capture-time market, US11 h07-12, same burn-in/scored dates. Prior history screen PASS is model-relative only. No corpus expansion or year-round refit. Existing-state parity, trial-season training coverage and full-donor power checked outcome-free before registered P0; w only for survivor | pending; dev stays unread | pending; HOLD for intake/season feasibility and new rule |

## Proposed rule details to freeze before resumption

These are reviewable design choices, not a claim that all three can be admitted.

- S0 must name why the market lacks the information at the specified hour. Refuse an exhausted
  family without a new mechanism; preserve CLOSED-BY-RULE versus measured KILL distinctions.
- Data: dev scorecard default folds, 43 scored dates, 11 US markets, native Fahrenheit;
  these are the documented nominal layout, **not newly measured coverage**. No post-September-29
  read, no sealed store, no maker tape, no MG-2/B outputs, no historical-price download.
- Freeze exact candidate-vector mappings and market price source before reading. H2 and NBM
  identities above need master's confirmation. For NBM distinguish book mid from display price.
- Outcome-free checks: hashes and source versions, finite values, exact target dates, receipt
  at or before capture, availability basis response_received_at for NBM; no parser v1.
  Replay must bind immutable state and captured inputs. Fail on unexpected mass, cutoff or
  parity differences. H2 is a controlled intervention, not a claim to reproduce old served bytes.
- Positive control before scoring: reproduce served R 1.774 all hours and 1.526 at 00-16 on the
  default scorecard; MG-1 07-12 excess 0.011957. Declare tolerances in the executable rule.
  Reproduce w=0 identity, planted positive/negative P0 and synthetic-null controls; a failed
  control means NOT INTERPRETABLE, never KILL for lack of information.
- Fair comparator: identical rows, same calibration and trusted floor; preserve a raw market
  comparator and an explicit market-plus-floor control. A floor improvement cannot be counted
  as candidate information. Do not substitute raw R0 or an unbound near-twin state.
- First compute the full population: candidate covered AND all 20 donors covered under all
  seeds, matching band support and snapshot mapping. Derange disagreement across dates within
  market/hour using seeds 20260921 through 20260940. Choose donor policy before freezing;
  no silent covered-donor repair after a zero-population result (method rule 16).
- No scored launch below power 0.5. Projection must use that population, same-contrast SD or
  a stated conservative bound, and a declared edge-size bar with derivation. Nominal 43 dates
  do not establish power. Report realised population and realised/projected SD afterward.
  Do not reuse R-P2's model-relative variance as taker-P&L variance.
- P0 proposed batch K=3, BH q=0.10 including refused/untestable arms as p=1 (no denominator
  shrink after results). Statistic: correlation(c-m,y-m) minus mean calibration-matched
  disagreement-placebo correlation. Pair bootstrap draws across candidate/placebo; proposed
  10,000 date-clustered draws, seed 20261024, with block-3 and crossed date/market intervals
  beside. The wider date/block-3 bound governs. Freeze a significant-but-sub-economic result's
  disposition before scoring. No retrospective edge-size threshold selection.
- P0 survival requires BH rejection and positive lower paired bound; a powered miss stops at
  P0, with exact scope stated. Insufficient power or integrity is UNTESTABLE, not a measured kill.
  Emit per-date rows and coverage for every arm, including failed/empty populations.
- Only P0 survivors reach walk-forward log-pool w, gap one day, grid 0..1, on their frozen
  local-hour population. Proposed MR-gate thresholds: mean w >=0.05; blend R upper <1;
  paired blend-minus-placebo and blend-minus-floor-only Brier uppers <0. Fix bootstrap and
  zero/missing-mass conventions in the executable rule. Report each local hour and 07-12.
- Only w survivors earn a separately registered executable-price dev replay. Freeze latency,
  depth, costs, capital, event selection and capture-gap policy before that read. Stop on first kill.
- A later T4 draft requires this full sequence plus trial-season coverage and a viable trial
  by December 28, D0 <= November 20, and the charter's net-profit/Holm rule. This document
  grants no trial-date read, standing accrual, model landing or live-order authority.

## OPEN QUESTIONS for the master

Land actual rows and reuse-count update through the morning light path, with the executable
rules' shas recorded before the first data read; then explicitly resume this task. Resolve H2
identity, NBM type-C/book-mid source and inherited closure, the three S0 mechanisms, existing
R-P2 state/season scope, and outcome-free power inputs first. Until then no screen has run.
