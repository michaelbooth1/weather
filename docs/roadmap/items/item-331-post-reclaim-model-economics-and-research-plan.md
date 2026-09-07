# 331. Post-Reclaim Model Economics And Research Plan [PARTIAL 2026-09-07 - APPROVED; SOURCE PREPARATION IN PROGRESS]

Goal: turn verified storage headroom into correct model outputs, a measurable
maker-economics decision, and one reproducible research result without restoring
the overnight workload that exhausted the host.

Owner/package: operations owns the baseline, admission and integration;
collection owns primary evidence; market/reporting owns economics; model and
validation own correctness and research. One integration owner coordinates
shared files. The operator owns capital, live execution, statistical allocation
and promotion decisions.

Source: the operator's September 7 request for a full review and forward plan
after another agent's reclaim work, and the
[whole-system audit](../audits/post-reclaim-system-audit-2026-09-07.md).
The audit distinguishes source-proved defects, retained measurements and
unmeasured hypotheses. This plan was prepared from fetched master
`6714b77d8bb57fa36b4d2dd33675cab971ef2432` without altering the two existing
production generated-config changes or the storage agent's work.

Why this matters: recent work has proved lifecycle behavior and built useful
calculators, accounting and operational repairs. The gaps now concern usable
evidence, real inventory/cash, replay fidelity and a few concrete correctness
defects. More unqualified machinery or an automatic retrain would consume the
recovered capacity without answering the operator's questions.

Acceptance: every package below has its stated result or an evidence-backed
bounded disposition with a continuing owner. Deliver (1) a sustainable admitted
operating baseline, (2) signed/zero band correctness, (3) a reproducible model
comparison or explicit inadequate-evidence result, and (4) an economic
continue/redesign/stop/inconclusive decision at the scope actually supported.
Positive alpha, profitable trading and arbitrary calendar deadlines are not
required to close the plan honestly.

## Authority and existing ownership

On September 7 the owner approved this plan and explicitly authorized working
now to prepare as much as possible, with independent double-checking and full
implementation authority. Source, fixtures, documentation, review and admitted
workstation verification proceed before reclaim where they do not depend on
production evidence. The storage owner's execution remains separate; production
adoption retains its guarded admission and recovery contract. The September 6
Stage 0/1 attempt is completed evidence and is not rerun. Stage 2, longer live sessions, capital changes,
unattended activity, statistical alpha and release promotion require their own
operator decisions and existing gates. Preserve the already agreed 100 pUSD
test allocation and 10 pUSD order limit as the planning starting point; any
Stage 2 applicability and aggregate inventory/loss envelope must be explicit.

Reuse [item 330](item-330-maker-economics-refocus-master-plan.md) for W0-W12 and
economic G1-G4; [item 325](item-325-tiered-data-retention-and-verified-archive-offload.md)
for storage; [item 324](item-324-bounded-daily-settlement-refresh-resource-admission-and-step-isolation.md)
for the daily chain; [item 67](item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md)
for execution; and [item 321](item-321-model-production-readiness-evidence-integrity-and-staged-release-program.md)
for release/evidence ownership. This item owns sequencing and cross-package
decisions, not replacement implementations. New independently bounded work is
[item 332](item-332-signed-native-temperature-band-correctness.md) and
[item 333](item-333-reproducible-runtime-and-paired-model-comparison.md).

## 1. Entry gate: accept what reclaim actually achieved

T0 means the storage owner's terminal handback is reviewed, not an assumed
overnight date or a scheduled-task success code. The pilot's failure/refusal is
a valid handback. Storage mutations and their exact source remain that owner's
scope. Do not rerun, expand or reschedule them from this plan.

- [ ] Obtain the exact request, reviewed source/CI, attempt and terminal
  receipt; record allocated bytes before/after, logical-byte/hash/identity
  preservation, elapsed time, peak resources, deadline/teardown and worker
  recovery. Compression savings and restore-backed deletion are different proofs.
- [ ] Refresh disk, physical RAM, commit and capture health at the point of
  admission. Verify the actual tiering/maintenance schedule and shared lease;
  a small pilot must not displace a more valuable already scheduled reclaim.
- [ ] Classify the outcome below and record the admitted workload envelope.
- [ ] Measure complete capture/day-roll cycles and scheduled work before
  projecting sustainable net growth. Keep receipt sizes and scratch peaks in
  the estimate. A single burst or logical directory size is not a runway model.

| Outcome | Consequence |
| --- | --- |
| Verified savings and all ordinary admission conditions pass | Permit only specifically budgeted capture-host evidence/integration work. Prefer workstation tests/replay/training. Reclaim is not authority to turn recurring work back on |
| Savings are real but ordinary disk or memory admission still fails | Capture remains the priority. Continue source/fixture/report work on the admitted non-capture workstation; defer production hashing, bulk census and suites. Storage owner scopes the next measured tranche |
| Reclaim refused, failed, identity mismatched or receipt incomplete | Preserve the failed attempt and source. Follow its bounded recovery path. Do not assume a copy is restorable or delete evidence. Continue independent workstation engineering where its own admission permits |

The ordinary 50 GiB disk floor is an admission minimum, not the target reserve.
Choose a working reserve from measured high-growth day cycles, restoration/
rollback scratch needs and the intended unattended interval, with a conservative
margin. Until that evidence exists, report the reserve as provisional and add
no recurring heavy task. Disk recovery cannot satisfy a failing RAM/commit check.

## 2. Ordered work packages

Effort below is engineering time, not promised calendar delivery. Evidence,
admission, review, settlement and payout time can dominate. Keep at most two
implementation packages active: one economics and one correctness/measurement
package. A single integration owner serializes shared-contract adoption.

| Package / owner | Inputs and dependencies | Concrete result and cheapest refusal test | Effort |
| --- | --- | --- | --- |
| P0 - Source and operating baseline; operations, W0/W1 | Reclaim handback; current Git/CI/dependency and host receipts | One per-PR disposition: adopted, reconcile/adopt, defer with trigger, or preserved history. Refresh PR 6 and the conflicting 26-28 stack; reuse 24/25/28/30/38 repairs. Complete the production documentation transaction against actual integrations. Stop on a red/unreviewed resulting head or failed recovery | 1-2 days, integration windows separate |
| P1 - Usable evidence and labels; collection/backtesting, items 324/321 | Bounded current ledgers/manifests/summaries exported under admission | Deduplicated market/date coverage, exclusions, runtime regimes, source/replay support and price-path quality. Reconcile the five Toronto folder omissions with authoritative ledgers before selecting repair. Separate WU proxy from venue settlement. If evidence is missing, return exact gaps without fabricating labels | 1-2 days |
| P2 - Native band correctness; item 332 | PR 28 shared parser/consumer repair and synthetic fixtures; independent of successful reclaim | Reconcile existing signed-band repair; close remaining replay zero/legacy endpoints and cross-consumer C/F coverage, then bounded impact census. Old source fails negative controls; repaired source preserves positive behavior and mass | 0.5-1 day residual repair, reconciliation/adoption separate |
| P3a - Coherent identity/config; market/operations, W2 | Reconciled PR 28; exact registry and metadata inputs | One generation-bound publication/read contract; crash/concurrent refresh retains the previous complete generation | 2-3 days |
| P3b - Exact event Rules; market/backtesting, W2/W6 | Retained current Rules and source timing evidence for one supported economic event; coordinates with P3a | Executable station/date/rounding/revision/fallback/exception contract. Ambiguity blocks inventory. Keep WU training/proxy labels distinct | 2-3 days; evidence acquisition separate |
| P4 - Exact opportunity qualification; market/reporting, W3/G1 | A small current condition shortlist, raw campaigns, synchronized complementary books, adjusted midpoint, Rules and fee/asset evidence; P3 before inventory | Existing calculator produces a retained feasible/capital-limited/duration-limited/competition-limited/no-campaign decision. Reject incomplete pages, conflicting campaigns, unsupported fees/assets, stale books or aggregate-cap breaches. Preserve rejected opportunities | 1-2 days after inputs |
| P5 - Payment and cash evidence; market/reporting, W4/G2 | One-day official-interface-to-field feasibility spike alongside P4; existing matcher/activity bridge | Replayable raw inputs feed conservative normalization and the existing matcher; join earnings, scoring, fill/exit fees, transfers, inventory/redemption, external flows and operating costs. If programme/period attribution cannot be established, report it unresolved before larger implementation | 2-4 days after spike |
| P6 - Forward runtime and paired comparison; item 333 | P1/P2; PR 7 identity/BOM/release implementation assessment and reconciliation; selected captured inputs | Reuse existing runtime foundation; prove faithful incumbent control and forward restoration; paired crossed delta with calibrated inference/support/power. Diagnostic replay cannot masquerade as served fidelity or improvement | Estimate residual gaps first; provisionally 4-7 days total |
| P7 - Protect primary capture and trim recurring work; collection/operations, W8/W11 | Current consumer/variant/job inventory; P0; measured resources | Primary transaction survives optional inference hang/crash/kill. Variants reference committed inputs in bounded work. Disable/remove only retired work with identified consumers and preserved finalization. Measure latency, RAM, bytes and duration before/after | 3-5 days capture slice; 1-2 days first job slice |
| P8 - Current inventory-capable successor; item 67/W5/W6 | P3/P4/P5; current portable capital/SDK/parent/manifest contracts | Reuse donor's one-submit/fill machinery with explicit inventory exits and current host authority. Partial/ambiguous/cancel-race/failed-exit fixtures pass through actual producer and parent. Add bounded Windows lifecycle CI with this change. No exchange execution during preparation | 2-4 days plus 2-3 days CI slice |
| P9 - One model/research decision; model/validation | P1/P2/P6; preserved hypothesis and outcome-free power | First investigate the WU observation envelope under its existing frozen safety mechanism; alternatively finish the PIT source/season preflight if envelope support is unavailable. Produce comparison implementation and a draft protocol ready for the required allocation decision, or a specific NO-GO before fitting/scoring | 2-3 days setup; accrual unknown |
| P10 - Economic calibration and forward decision; W6/W7 | P4/P5/P8; separate exact Stage 2 authorization | Smallest qualifying genuine maker exposure, complete position and payout closeout, then a frozen prospective study sized from attainable opportunities and variability. No campaign/payment, loss, unmeasurable attribution and inconclusive power are distinct outcomes | Venue/attendance driven; bounded below |

P7's optional-inference isolation is already scoped by item 330 W8 and is not
a new framework. Schedule it earlier if measurement proves it impairs selected
primary evidence. Do not make the whole integration queue, fleet retrain or
release programme prerequisites for a bounded economic candidate unnecessarily.

## 3. First two days, first ten working days, and the later decision

**At T0 / first admitted window:** accept the storage handback and measured
admission outcome; preserve capture and its scheduled reclaim work. Finish any
actual integration documentation debt and select the smallest dependency-valid
source tranche. Do not cram storage, a full suite, training and all integrations
into one night. Use the canonical roll verdict for each exact tip; roll-sensitive
adoption uses the 01:00-04:00 guarded path and recovery receipt. A published
topic alone does not change capture source.

**First two working days:** complete the P0 inventory, start P1's bounded
evidence census, implement P2 with synthetic tests, and do P5's one-day evidence
feasibility spike. P4 may inspect a small public shortlist through the authorized
collection host. If production admission fails, the census waits; source and
fixture work still progresses on the workstation. No default recurring job is
re-enabled.

**Working days 3-5:** select one economic condition only if its fully backed
plan is feasible. Finish the missing P3/P4/P5 slices and make the existing
calculator/matcher produce one usable decision report. Start P6 with the
smallest faithful incumbent control. At the first review, stop an economic
candidate whose programme, capital, minimum size, duration or payment evidence
cannot support the question; do not compensate with automatic larger orders.

**Working days 6-10:** complete the priority measurement/capture slice and
prepare P8 only when P4/P5 justify exposure. Produce the P9 support/power
decision. Some packages can extend beyond this horizon; preserve their explicit
dependencies and do not call a passed fixture a measured result. P7 and native
Windows CI accompany the specific changes they protect.

**After readiness, within a separately approved calibration envelope:** begin
with the existing one-TTL progression on one exact band. A fill must be
reconciled and closed through its predefined backed resale or settlement/
redemption path. A no-fill result is valid and does not justify price chasing.
A reviewed longer successor may use 2-4 hours of attendance if opportunity
analysis supports it, with explicit order count, turnover, duration, capital,
aggregate inventory and loss limits. Duration does not guarantee a payout.

Item 330's proposed discovery ceiling remains at most five attended sessions
and two completed payout cycles within fourteen calendar days after readiness,
subject to the operator's smaller envelope. Include late settlement and payout
closeout after quoting stops. Permit one mechanism-specific redesign; do not
reset this budget after each plumbing change. These are planning limits, not
authorization or a statistical sample-size claim.

The later forward study has a proposed thirty-day exposure ceiling after
freezing, with actual independent dates/opportunities determined from discovery.
If adequate information cannot fit, report infeasible confirmation or narrow
the question. No requirement says that a profitable answer must arrive within
thirty days.

## 4. What the economic report must decide

One report binds exact inputs, rules/code regime, candidate selection, capital,
quote/score time, confirmed own fills, multihorizon markouts, inventory exits,
settlement, paid transfers and costs. Include all eligible rejected/no-quote/
no-fill/failed sessions in opportunity denominators. Public tape supports price
paths; it cannot identify our queue position or prove our fills.

Show four accounting views over the **same realized cohort**:

1. Trading P&L after actual trading/exit fees.
2. Trading P&L plus paid maker rebates.
3. Trading P&L plus both paid incentive programmes.
4. The third view after attributable operating costs and disclosed operator time.

Also report unpaid accrual, unresolved payment attribution, external cash
flows, capital-hours, maximum commitment, drawdown and inventory still held.
Do not add incentives already included in cash twice. Cancellation and flat
open-order count are not inventory closure. Report no-quoting/zero-capital as
the economic baseline; a hypothetical alternative policy cannot reuse imaginary
fills as a causal comparison.

Before confirmation, freeze inclusion, selection/policy, costs, settlement,
payment deadlines, supported population, practical hurdle and review schedule.
Use dependence-aware uncertainty; many quotes on one date are not many
independent confirmations, and one market does not establish fleet generality.
Continue only when the prespecified result and risk/cash gates support the
agreed hurdle; stop on a loss/operational bound or evidence of insufficient
economics; overlapping bounds are inconclusive. Scale is a new decision.

## 5. What model and research work may claim

Correctness fixes need deterministic proofs, not a new alpha allocation.
Research comparisons need pinned inputs/labels/regimes and a faithful control.
Keep weather-only skill, market-informed risk controls and maker economics
separate. Preserve native units, probability mass, effective WU cutoffs,
trusted observed floors, train/serve parity and release binding.

For the observation envelope, reuse the previously defined observable rule:
recover a missing tail only if no current row exists at or after that minute.
Reconfirm cutoff/revision safety, undefined support and sharpening exposure;
recompute conditional, outcome-free design simulations from frozen arm vectors
and admissible cluster occupancy, with their assumptions stated. Candidate-
dependent outcome or benchmark-price joins follow protocol/allocation approval;
a failed computation can still spend a look. Keep dates separated by artifact
provenance. A prior eleven-date NO-GO or favorable hypothetical resampling does
not authorize a sample size or fitting. Calibrate the proposed inference with
null/coverage and attainable acceptance/rejection controls before interpreting it.

For the PIT alternative, first verify the separately staged corpus and current
free issue-qualified fields across exact markets, dates, leads and seasons.
Classify legacy analog/stitched indexes separately from candidate-honest
training. A reduced-field candidate requires a new explicit research contract;
do not weaken the existing full production gate or substitute settled data.

Stop when coverage, support, fidelity or attainable power cannot answer the
question. A precise NO-GO with a reopening trigger is progress. Do not revive
global offsets/sharpening, repeat already measured feature-completeness claims,
mine irrecoverable historical runtime blobs, spend a retired decision number or
assume retraining proves edge. Read the live reserved-window contract before
each dated operation; this plan grants no exemption.

## 6. Resource and maintenance budget

Keep production focused on capture, settlement and the minimum evidence needed
for the selected question. Heavy implementation, testing, fitting and replay use
the separate non-capture workstation's exact host/principal wrapper and shared
live/heavy mutex. No inference, test or training command may bypass admission
because it is part of this plan. Do not overlap heavy work with an attended live
stage, and finish heavy work before sealing an attempt.

Capture-host ad-hoc heavy work is admitted, serial and time-gated 00:30-09:00;
the existing Stage-A exception retains its absolute teardown. Use bounded
manifest-selected exports, not whole-tree scans. Full production pytest remains
forbidden; use the repository bounded suite only when separately justified
and admitted. Do not move heavy work into protected windows or loosen ceilings.

For each retained recurring job record purpose, current consumer, actual action,
enabled state, last meaningful result, measured duration/peak RAM/I/O/disk, and
keep/on-demand/retire disposition. Review one small change at a time and compare
complete before/after cycles. Preserve daily-learning freshness, real settlement
finalization, raw/ledger/order evidence, and historical readers. A stale report
timestamp or task exit code alone does not justify deletion.

Deferred: broad facade splitting, generic mission orchestration, a new dashboard,
blanket branch/worktree cleanup, inactive companion deployment, automatic
training/release campaigns, paid providers and expanded trading capital. Reopen
only when a selected package has a concrete unmet dependency.

## Completion ledger

- [ ] T0: storage outcome accepted and sustainable workload envelope recorded.
- [ ] P0/P1: selected source baseline, documentation and usable evidence reconciled.
- [ ] P2: item 332 correctness acceptance and adoption disposition complete.
- [ ] P3-P5: exact opportunity and accounting result produced, or specific
  infeasibility recorded under item 330 with a reopening trigger.
- [ ] P6: item 333 comparison/reproduction proof or bounded evidence refusal.
- [ ] P7: primary capture/resource improvement measured; first recurring-job
  tranche accepted or explicitly retained with its consumer.
- [ ] P8: successor and Windows fixture qualification complete or deferred
  because no measurable opportunity warrants it; live authority remains separate.
- [ ] P9: one reproducible research result or support/power NO-GO recorded.
- [ ] P10: economic decision and all position/payment closeout complete, or
  an explicit no-exposure/infeasible-study disposition with the continuing owner.

At each package closeout record the exact source, verification, adopted versus
proposed state, immutable evidence references, measured resource cost, decision
and reopening condition. Update this item and the owning subsystem item, then
regenerate the active backlog. Do not duplicate volatile counts in entry points.
