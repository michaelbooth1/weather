# T008: T4 model-screen intake and pre-read handback

Dated research note. This records document review, candidate identity and proposed registrations;
it contains no new scored data. Base: `22b3dd835e72f69d9e9fee5744a5c570c7f9a5eb`.
The master's task requires returning proposed rows before any read requiring registration.
All three are therefore **HOLD BEFORE DATA READ**, neither KILL nor SURVIVE.

## Definitions, existing evidence and cheapest tests

### H2 market arm

The located H2 is [evening-fix signed text, section 3.2](../evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md):
v0.5.12 minus the same model with `pre_lockin_same_day_floor=False`, US11, local hours 00-16.
It is a model-versus-model non-inferiority secondary with margin +0.0005 Brier,
not a market-edge test. The task does not identify a separate H2 market-vector rule.

[Item 337](../../roadmap/items/item-337-no-metar-observed-floor-gap.md) records H2 NOT TESTED:
the transferred Stage-1 replay lacks the v3 arm. Stage 1's -0.04854 [-0.05532, -0.04211]
is the 17-23 primary, **not an H2 number**. The signed October window is closed to this task.
[Clarification 1 section 5](../evening-lockin-fix-scoring-clarification-1-2026-10-31.md)
holds Stage 2 until the MG-1 look receipt; this assignment does not move that read.

Cheapest tier: identity/intake, then outcome-free dev replay feasibility and changed-vector count.
A dev-only H2 market arm needs a new pending ledger row and a frozen standalone rule before data.
Proposed interpretation: score the v4 vector against the market and v3 as an ablation;
master must confirm this, rather than silently substituting H2 non-inferiority for edge.
The floor-only control is essential: [EF 10ad](../../operations/ESTABLISHED_FINDINGS.md#10ad-against-the-market-the-models-add-nothing-blend-weight-about-0-and-the-dead-bucket-mechanism-is-closed-fleet-wide-once-the-floor-is-dated-by-receipt--lane-l11-workstation-2026-10-25)
and register X23-X25 already close attributing floor-only gains to model information.
No new market-missing-information mechanism has yet been established for this arm.

### NBM tilt on the market mid

Proposed identity: the [MR sweep type-C construction, sections 1 and 4](../mr-sweep-2026-10-30/rule_mr_sweep.md),
with x = capture-valid `v2_mean`, applied to normalised captured market probabilities.
It uses the market centre and variance, s_b=(x-mu_m)(z_b-mu_m)/sigma_m^2,
then an exponential tilt. This is a proposed interpretation of the task's short name,
not evidence that the original MR sweep tested it.

That rule's exclusions explicitly omit NBM centre by extension from X22. X22 measures a
P3d_N log-pool: mean w 0.0051, R 1.0013 [0.9992, 1.0075], MDE80 0.0038;
X21 measures MG-1 mean w 0.008, R 1.0017 [0.9990, 1.0077].
Neither is a measurement of this type-C tilt. Under method rule 15 its inherited closure
is **CLOSED-BY-RULE (reopenable)**, not a fresh measured KILL.

Cheapest tier: intake requires a new mechanism explaining why the market lacks the public NBM
centre at the chosen hour (method rules 2 and 14). The assignment names the test but supplies
no such mechanism. If admitted, outcome-free availability/version/donor-population and power
checks precede one registered market-residual P0. Do not rerun the exhausted log-pools.
The historical price series is a mid and only history-tier selection evidence; the
scorecard `p_market_yes` is not proven executable or a CLOB mid. Confirm the intended price arm
before registration; do not silently relabel the Gamma/display comparator as a book mid.

### R-P2 versus market

Definition: L48 climate-class-matched extra training rows for P3d_N_fix, two fits per fold,
marine within 25 km of the open-ocean coastline versus continental. Frozen prereg
`docs/research/climate-similar-pooling-rp2-2026-11-02/prereg_rp2.md` on
`origin/claude/station-pooled-corpus-s0-20261101`, sha256
`2a438306214ece68e6e58d6f288765dc8addace7d21b89a02a22141e9c2d3e70`, plus Clarification 1.
It explicitly keeps dev unread. The draft successor must not edit that frozen rule.

[EF 10ar](../../operations/ESTABLISHED_FINDINGS.md#10ar-station-pooling-r-p-l48-is-killed-at-loyo-gate-1-by-los-angeles-class-matched-pooling-r-p2-passes-its-screen-but-cannot-be-confirmed-at-size-lane-l48-ledger-rows-108-c--109-k-2026-11-02)
and X95 record history screen PASS: delta Brier -0.00390 [-0.00545, -0.00225]
block-3, no market CI-worse. This is versus the 11-market model, **not market prices**.
The 180-306-date planning requirement concerns that history model contrast, not taker P&L.
The prior is design-informed by the same history, not independent confirmation.

Cheapest tier: intake and outcome-free existing-state/replay/season-coverage feasibility.
No new corpus, year-round refit or row-28b work is allowed. An existing Aug-Sep fit does not
establish train/serve coverage through a November-December T4 trial. If it can be screened
as-is, a new ledger row and standalone rule are needed before dev; P0 precedes w.
X104's year-round pooling arm is a different measured member: its San Francisco and Seattle
harm does not by itself kill this Aug-Sep member. No substitution of the killed arm is proposed.

## Data gate and execution order

No layout, labels, tapes, model state, price files, replay bundles or sealed-store content was
opened. Only repository documents and the named task documents were read. No heavy command ran.
The existing dirty main checkout was left unchanged; work is isolated at `C:\wt\codex-t4`.

Proposed data scope after registration is only burn-in 2026-08-01..08-14 and scored
2026-08-15..09-29, US11. This task does not use the released September 30-October 14 window:
that release is local-target-date, weather kill-only, excludes Austin October 3 and does not
open general MG-2/B or maker reads. COMMON also forbids UTC event dates October 15 onward;
the proposed scope avoids both boundary conventions. MG-1's reserved guidance dates start
October 15; no sealed panel and no maker shadow are in scope.

Method sections 4 and 5 require rule sha and a pending ledger row before scoring; rule 5.3
requires the row before market-residual P0. The task additionally requires a pre-read handback.
The [proposed rows](registration-asks.md) are **not landed registrations or executable preregs**.
No new results, sample counts, power estimates, p-values or w were produced.

On resumption: confirm identity and intake mechanism, land rows and freeze executable rules;
then outcome-free coverage, receipt/version checks, probability-mass and replay controls,
full donor-population power projection; stop if infeasible. Historical model checks, if needed,
remain blocked LOYO and use existing data only. Market-facing candidates go first to P0,
then w versus placebo and floor-only, then a separately registered dev tradability replay.
Preserve native units, train/serve parity, effective WU print cutoff and as-of receipt semantics;
`last_in_hour` cannot support a positive market result. Never relax a failed control.

## T4 consequence and records

No survivor exists yet, so no T4 preregistration draft is asserted. A later survivor needs the
[charter](../../operations/EDGE_TRIAL_CHARTER.md): frozen strategy/simulator/scorer before trial
reads; forward D0 no later than November 20; final look no later than December 28; at least
20 dates and candidate-specific power at half the dev effect; date-clustered one-sided 95%
lower bound of net P&L above zero and the declared economic minimum, Holm across the family.
Freeze looks, block length, claimants and alpha treatment before accrual.
Use captured CLOB executable depth after measured p95-or-worse latency, fee 0.05*p*(1-p)
per share, slippage at least one cent or depth walk whichever is worse, displayed-depth and
capital caps, a declared capture-gap refusal rule, and actual venue payouts. Mid prices alone
cannot provide a tradability verdict.

There are **zero newly killed candidates** to add to the exhaustion register. Blocked intake
packages (plan, document-only script and its sha256, input hashes, outputs and receipt) are
under `C:\t\codex\T008\out\intake-v1\`. Existing archives are not modified.
COMMON restricts writes to task/worktree roots, so a future kill's copy to the canonical
`C:\archive\ruled-out` needs the master to arrange it; task-local copies stay retained.

## OPEN QUESTIONS

1. Land the three proposed pending rows with collision-free IDs, update the reuse denominator,
   then resume T008. The published denominator is at least 212, not a newly recomputed count.
2. Confirm H2 means a dev v4 market arm with the v3 ablation; the signed October H2 stays closed.
3. Confirm NBM means the type-C `v2_mean` tilt and identify the captured book-mid input; supply
   or rule on its new market-information mechanism and inherited closure before admission.
4. For R-P2, identify an existing parity-clean fitted state and input scope adequate for the
   proposed trial season, or accept an intake feasibility stop. Do not commission corpus work.
5. Resolve the same market-information intake requirement for H2 and R-P2. Pooling can improve
   a model without adding information beyond the market; that alone is insufficient under rule 14.
