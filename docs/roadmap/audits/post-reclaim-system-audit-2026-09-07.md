# Whole-system audit for the post-reclaim plan - 2026-09-07

This is a dated review, not a runtime attestation or execution authorization.
The operator requested a review of the codebase and recent work, followed by a
plan that improves the model, economics or research after the separately owned
storage reclaim. [Item 331](../items/item-331-post-reclaim-model-economics-and-research-plan.md)
owns that plan and its ongoing dispositions.

## Conclusion

The repository has substantial useful infrastructure, a completed attended
International Stage 0/1 lifecycle result, and several verified repairs awaiting
reconciliation. It does not yet have a demonstrated profitable opportunity,
paid incentive reconciliation, an inventory-complete economic session, or a new
proved forecast improvement. Storage headroom is necessary for continued
capture; it does not itself resolve those evidence gaps or memory admission.

The highest-value sequence is to accept measured reclaim, reconcile selected
existing repairs, fix native-band correctness, make one opportunity and its
cash accounting measurable, and restore trustworthy model comparison. Model
research should then answer one falsifiable question using admissible evidence.
Broad retraining, another no-fill lifecycle test and a wholesale architecture
rewrite do not address the present gaps.

## Scope and limitations

Three independent read-only reviews covered model/research, economics, and
architecture/recent integration. The parent reviewed operational constraints,
reclaim handoff, source dispositions and sequencing. Inspection used bounded
source reads, tests as specifications, canonical findings/retractions, Git
history, retained result documentation and fresh GitHub metadata. It did not
read every historical correspondence file or millions of runtime objects.

No new test suite, training, replay, production census, account query or live
exchange action was performed for the findings. Reported CI and attended-test
results are retained evidence, not reruns. Source-provable defects below have
not had their affected historical volume measured. This is not a penetration
test or an assertion that uninspected execution paths are defect-free.

| Surface | Reviewed evidence and coverage | Limit |
| --- | --- | --- |
| Production baseline | Fetched `origin/master` and local master `6714b77d8bb57fa36b4d2dd33675cab971ef2432`; root status | Two existing generated-config modifications preserved; no runtime adoption in this audit |
| Recent portable work | Documentation/source tip `8739902fe`, cumulative parent `ca64296fb944a65c0ccfbf0e9a17b2d913413a68`; 62 changed files relative to master | Actual completed test was on `c6ee36147c52269ac76328aded186b2658978325`; a later documentation tip is not a fresh host qualification |
| Model, sources, calibration, backtesting | Band parsing, feature/source contracts, WU cutoffs/floors, training corpora, replay identity and CLI, packaged PIT evaluation | These source trees, including reporting, do not differ between master and reviewed portable tip; no fit or outcome rescore |
| Market/execution/accounting | W3 feasibility, economics capture, official adapter, fill reports, paid-credit matcher/bridge, current Stage 0/1 and old Stage 2 donor | Current account balance, payout eligibility and selected market were not refreshed |
| Collection/operations/storage | Snapshot transaction ordering, configuration refresh, health repairs, load/lease/Job contracts, archive/reclaim handoff and documentation transaction | No heavy scan, Scheduler mutation, compression, deletion or production worker restart |
| App, reporting, architecture and CI | Read-only Control Room reducer and fixtures, owner boundaries, workflow matrix, dependency declarations, queued monitor/correctness repairs | Display issue is not evidence of live-order bypass; no full UI/security audit |
| Research evidence | Established findings, retractions, replay and Gate 3 traces, reservation and delegation contracts | No new statistical decision, reserved-date consumption or positive model claim |

## Recent work: preserve the result, distinguish its disposition

The GitHub snapshot returned 23 open PRs. Many are stacked dependencies,
documentation carriers or preserved incident history, not 23 independent
runtime changes. Conflicts and exact-head checks must be refreshed at execution.

| Work | Evidence at review | Implication |
| --- | --- | --- |
| W1 governance, W2 identity, W3 calculator | Guarded production integrations through master `6714b77d8`; retained recovery receipts | Adopted source. W3 is still a pure calculator without a qualified current economic opportunity |
| Portable lifecycle/capital/credential/parent repairs, PRs 31-37 within [PR 6](https://github.com/michaelbooth1/weather/pull/6) | Cumulative `ca64296fb` [CI 34073216796](https://github.com/michaelbooth1/weather/actions/runs/34073216796) passed. Actual test source `c6ee36147` had source and merged-head Linux CI, each 4,706 tests/921 subtests, 260 skips | Retain the successful exact attempt; source integration, portable qualification and capture adoption remain separate |
| September 6 attended result | Stage 0, cancel-all, dead-man and offline bundle PASS; two 0.005 pUSD BUY probes, no fills/positions/open orders; 39 artifact hashes independently retained; dead-man observed after 10.359 seconds | Real lifecycle proof. It does not establish maker fills, rewards, rebates, settlement, inventory exits or profit. Do not repeat it as the next milestone |
| [PR 24](https://github.com/michaelbooth1/weather/pull/24) / [PR 25](https://github.com/michaelbooth1/weather/pull/25) | Economics read/hash race repair and offline paid-credit matcher already in the cumulative portable tree; reviewed and CI-tested | Reuse rather than rebuild. No automatic real accrual/payment linkage follows |
| [PRs 26-28](https://github.com/michaelbooth1/weather/pull/28) | Monitor, system audit and corrective stack. PR 28 `0a0804f07` [CI 34002217279](https://github.com/michaelbooth1/weather/actions/runs/34002217279) passed. PR 26 conflicts with advancing PR 6 | Reconcile the stack on its topic, preserve later capital/lifecycle semantics, review the cumulative diff and test the resulting head |
| [PR 30](https://github.com/michaelbooth1/weather/pull/30) | Transient execution-tape status-read repair `7e7516f46`, [CI 34031461447](https://github.com/michaelbooth1/weather/actions/runs/34031461447) passed | Existing bounded reliability repair awaiting guarded adoption |
| [PRs 29/38](https://github.com/michaelbooth1/weather/pull/38) | Watchdog diagnostics; PR 38 `e0400c4f4`, [CI 34138125883](https://github.com/michaelbooth1/weather/actions/runs/34138125883) passed; pinned diagnostic deployment documented | Preserve the referenced deployed directory. Reconcile exact integration; do not blindly redeploy |
| [PRs 18, 22, 23](https://github.com/michaelbooth1/weather/pull/23) and [PR 21](https://github.com/michaelbooth1/weather/pull/21) | Archive encryption/suffix/restore stack and provisional round-trip proof; signed-in restore had 17 checks PASS | One 513,522,801-byte provisional file was independently recovered. Production source identity, broader archive durability and reclaim do not follow |
| [PR 39](https://github.com/michaelbooth1/weather/pull/39) | Separately owned active compression/reclaim work; review repairs were still changing its tip | Earlier green CI cannot qualify the later head. This audit neither duplicates nor executes it |
| PRs 7/8 | PIT foundation and collector NO-GO; PR 7 conflicting | Assess/reuse loaded-process identity/BOM/release work for F3 separately from the collector NO-GO; no generic retrain revival |
| PRs 11/12/14 | MAX_PATH and default-off paper companion with subsequent repairs | Dormant until needed by a specific economic question; never deploy the original companion without its repairs |
| PRs 9/10/13/15 | Older settlement, reconciliation, control-plane and mission-runner stacks; 9/13 conflicting | Disposition individually against current contracts. An old branch name or passing old CI is not a present requirement |

## Findings

### F1. P1: serving strips negative signs from native temperature bands

[`model_presentation.py:167`](../../../src/weather/model/model_presentation.py)
uses unsigned digit extraction. `-2 C` becomes positive 2, `-5 C or below`
becomes a tail ending at positive 5, and `-3--2 F` yields endpoints 3 and 2.
The result feeds probability projection and persisted band identity. The
reviewed unit test at `tests/model/test_market_units.py:71` uses positive bands.
This is a concrete source defect in the reviewed adopted baseline, independent
of model quality; historical impact is unmeasured. PR 28 commit `016e1c92c`
already adds `weather.units.parse_temperature_band` and routes serving,
settlement IO and market consumers through it. Reconcile that repair, then
close the remaining replay paths and cross-consumer coverage; do not build a
second parser.

### F2. P1: replay drops valid zero and legacy endpoint parsing loses signs

[`replay.py:252`](../../../src/weather/backtesting/replay.py) uses
`bin_value_c or bin_value`, so numeric zero can become missing. The value then
reaches numeric comparisons in `model_presentation.py:734`. Legacy upper
endpoint recovery in `replay.py:155` and `settlement_io.py:65` also uses unsigned
parsing. Preserve zero through explicit missing checks and prefer validated
typed endpoints over fallback label parsing. Repairing derived interpretation
does not authorize rewriting original tapes. F1/F2 are owned by
[item 332](../items/item-332-signed-native-temperature-band-correctness.md).

### F3. P1 for served-runtime claims: prediction identity is not a restorable runtime

[`model_identity.py:25`](../../../src/weather/model/model_identity.py) manually
lists source files but omits direct serving dependencies such as
`calibration_runtime.py`, `model_distribution_constants.py` and
`model_distribution_signals.py`. Line 100 hashes current disk files.
Snapshot capture has a real stale-code guard (`snapshot_store.py:2201`) and
retains inputs/identities (line 3010), but an identity does not preserve missing
loaded source, dependency or artifact bytes.

This is an instrumentation limitation, not evidence of wrong current
predictions. The historical finding that none of 63 decision-stratum identities
was fully restorable is already recorded in
[the replay investigation](../../operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md).
Do not repeat exhausted Git-blob reconstruction. PR 7's
`codex/workstation-model-pit-foundation-2026-09-79a` already contains loaded-process
identity v0.3, deterministic BOM and release bindings with retained mutation
controls. Its current conflict needs bounded reconciliation and review; the
separate collector NO-GO does not invalidate this useful source foundation.
Assess and reuse it with existing release/CAS machinery before adding anything.
Distinguish same-environment experiments from actual served reproduction.

### F4. P2: replay's aggregate PASS does not require fidelity to pass

[`replay_backtest.py:752`](../../../src/weather/backtesting/replay_backtest.py)
gates aggregate Brier and optional corpus identity. Fidelity failure prints
`CHECK CORPUS`, then the aggregate gate still runs near line 871. Fidelity itself
uses mean L1 at line 203; concentrated divergences can be hidden by averaging.
The existing gate is a diagnostic regression check, not sufficient improvement
or reproduction evidence. Require a faithful incumbent control, declared
inclusion and per-row error diagnostics before interpreting candidate deltas.
The candidate's own identity may intentionally differ from the incumbent.

### F5. P2: packaged inference cannot yet make the governing paired claim

[`point_in_time_evaluation.py:2518`](../../../src/weather/reporting/validation/point_in_time_evaluation.py)
already provides streaming materialization, embargoed whole-date folds and
fold-local fitting. Its resampling at line 2544 treats dates as the resampled
axis and outputs separate lane/variant absolute intervals near line 2844.
Model-versus-market claims require paired crossed date-by-market uncertainty
under `AGENT_CONTEXT.md`. Extend this evaluator with that comparison and
candidate-specific power; retain its existing outputs as diagnostics.
[Item 333](../items/item-333-reproducible-runtime-and-paired-model-comparison.md)
owns F3-F5 without taking over release promotion.

### F6. P1 before settlement-dependent economics: WU proxy and venue Rules differ

[`settlement_ledger.py:530`](../../../src/weather/backtesting/settlement_ledger.py)
through line 548 fixes the WU source/rounding contract. Retained Rules for the
tested September 7 NYC event name NOAA hourly evidence first and WU fallback
under stated timing conditions. The completed no-fill test did not need to
resolve a position. A filled position does. Capturing rule text in PR 28 does
not implement its semantics.

Keep WU labels as the model proxy and qualify exact event-specific venue
settlement separately, including station, date/timezone, rounding, revisions,
fallback deadline and exceptional resolution. Never silently relabel old
training evidence or treat all weather markets as sharing NYC's rules.

### F7. P1 before cash claims: fee capture and realized-fee reporting are disconnected

The reviewed portable tree captures `feeSchedule` in
[`exchange_economics.py:497`](https://github.com/michaelbooth1/weather/blob/ca64296fb944a65c0ccfbf0e9a17b2d913413a68/src/weather/market/exchange_economics.py#L497)
and rejects unsupported exponents near line 881. The adapter exposes
`fee_rate_bps` (`mm_official_adapter.py:1002`), while realized taker fees use the
fill scalar divided by 10,000 (`mm_exchange_reports.py:112`). Retained public
projections contain contradictory legacy versus current schedule fields.
The no-fill test cannot settle their economic meaning. This is an unclosed
lineage risk, not an observed mischarge. Bind fills and exits to effective
schedule and actual verified cash fees. The current field contract is documented
in [market details](https://docs.polymarket.com/market-data/market-details).

### F8. P1 before paid-profit claims: supplied-receipt matching has no complete live evidence producer

The existing paid-credit matcher requires accrual, distribution and a unique
confirmed credit (`mm_exchange_reports.py:853` in the reviewed portable tree).
The activity bridge explicitly disclaims accrual linkage, account completeness
and economic proof (`mm_paid_credit_activity.py:358`). Adapter `rewards()`
returns campaign/rebate evidence, not a complete normalized payout lifecycle.
Neither the feasibility calculator nor activity bridge has a complete runtime
consumer in the reviewed `src`/`app` trees.

Start with a one-day interface/field feasibility check. The documented
[daily earnings endpoint](https://docs.polymarket.com/api-reference/rewards/get-earnings-for-user-by-date)
requires authenticated pagination; earnings do not establish wallet payment.
If available evidence cannot attribute a transfer to a programme/earned period,
report unresolved attribution. Do not manufacture an ID, date join or match
based only on equal amounts. Preserve the existing conservative matcher and
cash identity and add only missing producers/normalizers/consumer reports.

### F9. P2: incomplete campaign capture can look like no campaign

`exchange_economics.py:381` defaults missing `data` to an empty list and accepts
missing/blank terminal cursor; line 464 silently overwrites duplicate condition
rows. The documented [current rewards response](https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations)
requires data/count/limit/cursor and identifies `LTE=` as terminal. PR 28
repairs Gamma event discovery pagination, not this current-rewards response
validation. Reuse applicable patterns while adding explicit response-shape,
terminal-cursor and duplicate-condition checks here.

The collector at line 121 keeps response hash/length without the raw body and
individual response provenance needed for independent normalization replay.
The September 6 scratch projections explicitly have the same limitation.
Capture a bounded exact-condition raw bundle, preserve configured and paid
asset identities separately, and distinguish verified zero from incomplete,
unsupported or stale evidence.

### F10. P1 before inventory: the old Stage 2 donor is not the current successor

At donor Git object `ad85019972a0e67c6081d4a17da9572428470cdd`,
`mm_live_stage2.py:318` requires platform v0.4, lines 1161-1164 cap the entire
wallet at 100, and lines 1562-1574 accept confirmed-fill inventory. Lines
1696-1701 leave exit/settlement economics incomplete. Current Stage 0/1 uses
newer schema and existing-wallet allocation contracts; portable authority
remains restricted to those stages.

Reuse the donor's bounded one-submit/fill reconciliation machinery only after
adapting current host, capital, parent/child, deadline and cleanup contracts.
Cancelling orders does not close positions. Preparation needs an explicit
inventory exit/settlement/redemption policy and fixture qualification; execution
needs a separate owner request and current gates.

### F11. P1 for coherent configuration: publication has two distinct gaps

[`location_config_refresh.py:66`](../../../src/weather/operations/location_config_refresh.py)
directly overwrites JSON; `main` publishes locations and event metadata
sequentially near lines 387-390. PR 28 repairs individual-file atomicity and
pagination, but not a reader's exposure to different generations of the pair.
Use one manifest/pointer binding both exact files and registry identity.
Interrupted publication must preserve the previous complete generation;
concurrent refresh/registry changes must refuse or retry coherently. Preserve
the user's current generated files throughout reconciliation.

### F12. P2 capture reliability: optional variant inference precedes primary persistence

[`snapshot_store.py:865`](../../../src/weather/collection/snapshot_store.py)
calls `build_live_variant_prediction_rows` before the primary append at line
886. Exception handling does not bound hangs, latency or memory. This ordering
is present in master and the reviewed portable tree and is not repaired by PR
28. It is not attributed here as the cause of a recent incident.

Design a coherent committed primary captured-input transaction, followed by
bounded optional work referring to that identity. A simple statement reorder
could create disagreement among CSV/JSON/sidecars. Inject optional-worker failure
and termination; prove primary survival, explicit missing variants, replay
binding, and acceptable capture latency/resource impact.

### F13. P2: Control Room readiness can be overstated; repair already exists

[`operator_control_room.py:231`](../../../src/weather/reporting/market/operator_control_room.py)
calls same-target-date evidence current; economics acceptance near lines
295-304 principally uses platform/date/status. Its passing fixture at
`tests/reporting/test_operator_control_room.py:155` uses fixed older timestamps
and minimal economics fields. This proves a misleading display path, not a
live execution bypass or observed false approval. PRs 26/28 already add
freshness, run identity, canonical economics validation, native cash and bounded
discovery. Reconcile and adopt these repairs; do not build a second monitor.

### F14. P2: Windows lifecycle CI and current-status ownership need focused repair

The primary CI workflow uses Ubuntu; the Windows/Linux matrix covers only the
host-load hook. Real Job/CTRL_BREAK/share-mode/process-tree tests in
`test_international_live_session_runner.py:1741-1799` require Windows. Recent
447/201-check native qualification and the actual successful attended test are
valuable evidence. Add a bounded, change-triggered Windows fixture lane for
actual child-to-parent receipts and containment failures; a whole Windows
suite or another exchange test is unnecessary.

Latest reviewed item 330 still describes preparation/no-live/pending W5 in its
title, early authority paragraphs and later matrix/checklist, although its
state-of-play sibling records completion. PR 6's title/body also lag its final
scope. Production's pending documentation transaction remains present with
seven listed integration tips through `6714b77d8`. Its presence alone does not
exclude a separate matching completion receipt; reconcile through the canonical
transaction command rather than deleting the pending file.

Source registries also retain old diagnostics, including
`june23_location_bias_repair`. Source presence is not proof of current scheduled
execution. Dependency pins are duplicated and architecture ratchets permit
transitional edges. These are bounded maintenance opportunities after concrete
consumer tracing, not justification for general refactoring now.

## Storage and evidence limits that govern the plan

The separately retained September 7 11:51 Toronto review reports
30,877,573,120 bytes free (28.76 GiB). Ordinary capture-host heavy admission has
a 50 GiB floor; that is an admission boundary, not a comfortable target. A
100 GiB objective mentioned in reclaim planning is not a measured runway.
Fresh commit/memory admission remains independent; a daytime sample exceeded
the 70% commit ceiling even before new heavy work.

September 5/6 tiering receipts reported about 15.10 GiB total volume free-space
increase, but concurrent capture means that is not isolated per-file savings.
The old replay-cache inventory was logical size, not fresh allocated bytes.
Twenty split CSV/gzip pairs may have disjoint rows and must remain preserved.
The one-file NTFS compression request preserves bytes and paths; it was not
evidence of execution or a scheduled overnight guarantee. Its latest source
review was still active. The one independently restored provisional archive
file is roughly 0.48 GiB and cannot solve the host's capacity problem alone.

Accept actual allocated-byte reduction, hash/identity preservation, deadlines,
resource peaks and capture recovery from the storage owner. Measure complete
day cycles before forecasting net growth or adding recurring workloads. A
partial or refused reclaim can still leave useful workstation engineering
available; it cannot license an under-reserved capture-host suite or training.

Five Toronto folder settlement views for August 28-September 1 were previously
confirmed missing. Fleet scope and authoritative ledger reconciliation are not
yet measured. Deduplicate market/date revisions; neither folder flags nor raw
ledger row counts establish eligible market-days. The public execution producer
was previously CONNECTED/integrity PASS with `price_path_usable=false`; connection
health is not continuous price-path proof.

## Economic and research interpretation

Liquidity rewards pay for qualifying resting liquidity; maker rebates require
executed maker liquidity. Both programmes currently document a one-unit minimum
payout, so a short session may establish eligibility without paid evidence.
Use current campaign size/spread/asset terms, adjusted-midpoint provenance and
competitor-score scenarios; anonymous aggregate depth cannot identify the
nonlinear per-maker denominator.
([Liquidity rewards](https://docs.polymarket.com/programs/liquidity-rewards),
[maker rebates](https://docs.polymarket.com/programs/maker-rebates), checked September 7.)

The fee scale should be checked before extending duration. Conditional on the
documented weather coefficient 0.05 and rebate fraction 25%, 20 maker shares
at 0.50 imply about 0.0625 pUSD rebate-equivalent accrual; roughly 160 pUSD of
such turnover reaches one pUSD. This calculation is not observed income or a
promise of payout. Do not churn orders, force taker fills or raise caps to
chase a threshold. [Fees](https://docs.polymarket.com/trading/fees).

The existing research record rules out generic sharpening/offset/calibration
claims and does not show that simply filling more features closes the gap.
Market shrinkage consumes the benchmark and is not independent forecast alpha.
The PIT heating candidate was never fitted: its Gate 3 stop did not test its
mechanism. Do not reuse its fail-on-any-row gate or retired decision number.

The WU observation-envelope candidate has safety-cleared research provenance,
not a measured improvement. Its later outcome-free power exercise returned
NO-GO with eleven date clusters; a favorable resampling scenario is not a
calendar/sample-size entitlement. A useful next experiment first re-establishes
admissible support, faithful paired control and candidate-specific power.
Free PIT source/season coverage should be a bounded preflight, not a new
automatic full retrain. The canonical Open-Meteo Previous Runs fetcher still
requests temperature only; reconcile the separately staged richer PIT corpus
and unavailable full-contract fields. Other live station/forecast collectors
already carry additional fields.

The plan therefore seeks three concrete results: correct native-band behavior,
a reproducible model comparison with an honest outcome, and an opportunity
report that can reconcile real inventory and paid incentives. Any can produce
useful progress; none is assumed profitable or statistically positive.

## Closing update: the separate reclaim source review finished

After the main audit, the storage owner completed its review at
`a62ba9c3162ebf3be48da82e6548b62201537023`. The retained
`scratch/handoffs/storage-reclaim-audit-20260907.md` records 141 native/focused
checks and [exact-source CI 34157297426](https://github.com/michaelbooth1/weather/actions/runs/34157297426)
with 4,348 tests and 921 subtests passing. The GitHub result was independently
checked. This supersedes the earlier "review active" PR 39 snapshot above,
not the requirement for production qualification.

The disposition is conditional GO for an attended one-file pilot, with fresh
admission and protection of the existing tiering window; no automatic task,
production compression, deletion or measured pilot savings is established.
The later bounded volume sample is 26,476,851,200 bytes free, approximately
24.7 GiB. The older 28.76 GiB observation above remains a dated sample.
The storage owner's revised commands supersede its initial implementation
receipt. Item 331 still starts at the actual execution handback, with the same
success/partial/refusal paths; source qualification alone does not reach T0.
