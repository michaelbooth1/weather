# Codebase and rules audit — September 5, 2026

**Historical audit and September 4 findings addendum.** Audited source:
`06979f4a577bd20f00c9ef2606f1030d3218dd8a` on `codex/project-monitor`.
The source includes the portable preparation, W2/W4 additions and monitor;
it is ahead of production `6714b77d8bb57fa36b4d2dd33675cab971ef2432`.
Source publication, production adoption, portable qualification and live
authority remain separate facts.

Requested outcome: repeat the full repository audit, challenge assumptions and
rules, and add the results to the previous findings. This document retains the
previous twelve themes as A01–A12 and adds A13–A22. These are findings and proposed
repairs, not completed implementation. [Item 330](../items/item-330-maker-economics-refocus-master-plan.md)
owns subsequent work and disposition.

## Decision

The first audit's main conclusion survives: narrow the active system around
the maker economic decision. The second audit adds a more immediate priority:
**repair interpretation of temperature bands and qualify the actual event
resolution contract before trusting settlement-dependent results.**
Then repair evidence validation in quote policy and the monitor.

The system has strong protections at several execution boundaries, but those
protections are not consistently shared by research, reporting and display
consumers. A passing report, hash-shaped string, plausible temperature,
recently written file or green test suite is not sufficient evidence by itself.

No profitable opportunity, account income, new runtime failure or live-order
bypass was established by this audit. Its concrete defects were reproduced
with synthetic local inputs. They matter even though separate live gates can
reject a downstream attempt.

## Scope, method and limits

- Inventoried all 2,043 tracked paths; parsed tracked Python source and measured
  imports, repeated functions, large functions and documentation burden.
  The text inventory covers 1,977 eligible files, excluding unsupported file
  types and individual files over 2 MB. Binary model contents were not audited.
- Traced collection/persistence, source roles, model presentation and calibration,
  settlement/ledger readers, quote policy, incentives/accounting, operator UI,
  orchestration, deployment, retention, packaging, CI and agent rules.
  This is broad structural review plus targeted behavioral review, not a
  line-by-line correctness proof of every module.
- Compared the September 4 audit with the actual source changes. A01–A12 below
  preserve its meaning while stating today's disposition.
- Checked the current public NYC event Rules and official incentive documentation.
  No authenticated account, credential, order, heartbeat or cancel was used.
- Ran source inventory and tests only through the assigned non-capture
  workstation's repository admission wrapper. No heavy audit workload ran on
  the capture host. Existing production configuration edits were preserved.
- Inspected retention/release safeguards as source contracts. This audit did
  not perform a restore, reclaim evidence, measure current disk burn, certify
  capture health or independently reproduce earlier economic experiments.

Prior source qualification and full CI are useful background. The checks
below are the new evidence from this audit; neither substitutes for the other.

### Verification receipts

| Check | Result |
| --- | --- |
| Tracked-source inventory, source-root/admission/HEAD checks, Python AST parsing | 1 passed; no Python parse errors |
| Initial adversarial probes | 7 reproduced concerns; 1 suspicion rejected because nonfinite fee counts correctly fail closed |
| Expanded accounting, feasibility, policy, economics, config and monitor bundle | 290 passed, 47 subtests passed |
| Final witnesses plus native-market-unit and settlement-ledger tests | 31 passed; includes all 13 final witness tests |
| Final witness meaning | 12 assertions reproduce undesirable behavior across A13–A21; one verifies a rejected suspicion |
| Documentation, architecture, backlog and tracked witness checks | 54 passed; docs audit passed; regenerated backlog matches the committed view |

The bundles overlap; do not add their counts as distinct coverage.
The witness assertions intentionally describe the defective behavior on the
audited commit. A green witness is evidence of the defect, not a repair.

[The dated witness file](codebase-audit-2026-09-05-witnesses.py) is retained
outside normal test discovery. It performs no network or account activity and
uses temporary directories. To reproduce, use the audited source checkout,
copy this dated witness there, and run it explicitly with pytest under the
appropriate host wrapper. When implementing a repair, add the opposite
behavioral assertion to its ordinary owner tests; preserve this dated record.

Ignored receipt hashes, retained for comparison rather than assumed present
in a clean checkout:

| Receipt under `scratch/audit/` | SHA-256 |
| --- | --- |
| `inventory.json` | `056318c6904a6b2202d71fae0a039e5c30983f0f9dd41dfaa00f82080da572a0` |
| `summary.json` | `06e2b5bf912789015b7ee6f4a3e720d5dc48b4e101fdd7e91b6f477e0607c669` |
| `focused-audit.xml` | `8ab499a0daab06582aff7a5201d513fceb3401a8ee02da9aca58f358fb87ee59` |
| `temperature-audit.xml` | `23eb62ed638a50e2fb3073542675b3f69f8484cffadce070dfc4f135f3202d7d` |
| Witness source | `9d69e57fec35e9cca6b8832dc6430a22266d4a846ae1897cf3ae73e0d1ea9312` |

The witness hash identifies the final tracked file containing all thirteen
cases. The report and witness remain dated evidence after implementation changes.

## Previous findings, now dispositioned

These twelve themes originated in the September 4 task “Audit codebase and
workflows.” This table adds current evidence; it does not imply the original
audit inspected today's later source.

| ID | Previous finding | September 5 disposition and next action |
| --- | --- | --- |
| A01 | Narrow the active research portfolio to the maker economic decision | **PARTIAL.** Item 330 establishes the right objective and permits rewards-dependent profitability. W3's explicit-input calculator and W4's matcher exist, but actual opportunity, paid attribution and economic decision remain open. Require a named decision, bounded effort and stop condition for each active job. |
| A02 | Optional variant inference precedes primary snapshot persistence | **OPEN, reverified.** `SnapshotStore.write` still calls `build_live_variant_prediction_rows` before the main CSV append at source lines 864–884. An exception handler does not bound latency, memory or process termination. Persist a coherent primary evidence transaction first; run optional variants from its captured inputs. Do not infer current host participation from registry flags alone. |
| A03 | Daily orchestration mixes essentials, taker analysis and dated research | **PARTIAL.** One model-disagreement recurrence was disabled in earlier work; the 44-step registry still includes taker diagnostics and `june23_location_bias_repair`. Stage B is not universally enabled, so this is not a claim that 44 jobs execute daily. Reduce default imports and invocation obligations as well as Scheduler definitions. |
| A04 | Generated configuration is non-atomic and creates avoidable Git churn | **PARTIAL.** W2 fixed identity and a later metadata read/hash race. `location_config_refresh.write_json` still writes directly; the normal two-output route still publishes files separately and stamps the durable payload. Use atomic per-file replacement and one validated generation for consumers needing the pair. A21 adds missing pagination-completeness proof. |
| A05 | Explicit unknown markets silently fall back to Toronto | **CLOSED in audited source and previously adopted W2.** `spec_for_id` rejects explicit unknown IDs; `MarketConfig.__post_init__` checks identity/date/slug consistency. Keep those regressions. Do not reopen this as an unfixed defect. |
| A06 | Mutable Git checkout acts as production deployment | **OPEN.** Imported-source fingerprint changes still induce readoption; the large quiet-window merger compensates for that architecture. Build an immutable deployment-directory/activation migration, preserving recovery protection until proved. The expired August 23 executable exception remains a deletion candidate. |
| A07 | Mandatory guidance contains competing, stale or overbroad authority | **PARTIAL.** Mission/host/scope handoff selection is repaired; current prepared-source STATE is better. Production's old STATE and the later source's STATE still describe different source milestones. Root streak priority still conflicts with the findings' economic priority. A22 quantifies the mandatory reading burden. |
| A08 | Maintenance rules resist reductions and force ceremonial documentation edits | **CLOSED for the two reported defects.** The module-size ratchet allows reductions; the documentation transaction accepts a reasoned unchanged review bound to a committed blob. Preserve these improvements. Future rules should test the intended property, not a fixed debt count. |
| A09 | File splitting preserves dependency tangles and duplicated packaging | **OPEN.** Owner imports remain cyclic; direct dependency pins are authored in both packaging files. Delete dead imports and unnecessary facade exports before more splitting. Prefer one dependency source and generated environment locks; preserve artifact/SDK compatibility. |
| A10 | Statistical guidance blurs evidence, power and policy | **OPEN, reverified.** `quotable_edge` still uses observed-effect power as an extra candidate threshold. The findings still call a Gaussian simulation quantile a guaranteed lower bound without establishing the required tail ordering. Keep rejected experiments closed; correct the reasoning and scope of their claims. |
| A11 | Empirical model adjustments need retirement by demonstrated contribution | **OPEN.** Reuse `served_stage_ablation` and `model_stage_retirement`; do not add another framework. Protect mathematical and evidence contracts, evaluate optional empirical stages against the maker decision, and retain dependent historical artifacts. A13 challenges universal WU authority; A14 identifies a native-band correctness defect. |
| A12 | Storage and platform verification should focus on irrecoverable failures | **PARTIAL.** The off-site pilot now has a recorded restore proof in item 325, but that is not whole-mirror or reclaim proof. Expanded book CSV is still enabled. Main CI remains Ubuntu; the Windows/Linux hook job tests the hook, not the full Windows lifecycle. Prior native workstation qualification exists and should be reused, not described as absent. |

Owner anchors for the carry-forward findings:
[snapshot store](../../../src/weather/collection/snapshot_store.py),
[daily registry](../../../src/weather/operations/daily_refresh_registry.py),
[configuration refresh](../../../src/weather/operations/location_config_refresh.py),
[market configuration](../../../src/weather/market/market_config.py),
[quiet-window merger](../../../scripts/ops/quiet_window_merge.ps1),
[package boundaries](../../operations/package-boundaries.md),
[module-size tests](../../../tests/operations/test_module_size_audit.py),
[documentation transaction](../../../src/weather/operations/documentation_transaction.py),
[quotable edge](../../../src/weather/reporting/research/quotable_edge.py),
[storage configuration](../../../config/storage_pressure.json).

## Additional findings

Priority here expresses when to repair the affected use:
**P1 before relying on its settlement, readiness or financial conclusion;
P2 before extending or operationally depending on that surface.**
It does not claim a current live emergency.

### A13 — P1: the repository's universal WU resolution specification is not the event contract

**Verified source and current venue evidence.**
`MarketSpec` exposes `resolution_source`, but
`settlement_ledger.resolution_spec_for` always emits
`resolution_source_type="wunderground_history"` and fixed daily-window/rounding
rules. A fixture setting NYC's source to `noaa_hourly` still produces WU.

The [September 6 NYC event Rules](https://polymarket.com/event/highest-temperature-in-nyc-on-september-6-2026)
name NOAA hourly readings at LaGuardia as primary, WU as conditional fallback,
a next-day availability deadline and a revision cutoff. The repository's
prepared STATE already acknowledges this distinction. The defect is the
missing executable contract, not a newly discovered secret about the venue.

`location_config_refresh.normalized_event` retains an event-level source URL,
but drops event description and per-market description/source fields. Changing
hourly-versus-all-observation selection or revision rules without changing the
URL produces identical normalized metadata. Hashing that normalized output
therefore cannot prove unchanged resolution semantics.

**Consequence:** a WU proxy high/floor is not automatically an impossible-outcome
proof for an hourly-NOAA event. Reconciliation with the eventual exchange winner
can detect a disagreement after the fact; it does not repair earlier pricing,
training labels or inventory decisions. No actual mislabeled NYC settlement
was observed by this audit.

**Smallest coherent repair:** capture the raw Rules and their hash; bind an
event/condition/date-specific resolution specification containing source,
station, sampling rule, unit, rounding, revision cutoff, fallback and deadline.
Reject unsupported resolution contracts for settlement-dependent use. Preserve
historical WU proxy replay under its original semantics. Do not silently rewrite
old ledgers or globally replace WU with generic METAR/NOAA observations.

**Owner / plan:** market + backtesting + model/collection; W2, W5–W7.
**Acceptance:** rule-text changes alter the binding; an unsupported event cannot
obtain a settlement-dependent permission; fixtures cover primary/fallback,
missing source and revisions at the cutoff. Stage 0/1 no-fill qualification
remains a distinct experiment.

Source: [registry](../../../src/weather/market/market_registry.py), line 45;
[resolution specification](../../../src/weather/backtesting/settlement_ledger.py),
line 530; [metadata normalization](../../../src/weather/operations/location_config_refresh.py),
lines 171–224.

### A14 — P1: temperature-band parsers disagree and lose signs

**Reproduced in serving, ledger parsing and paper outcome scoring.**

- `PresentationMixin.market_bins` and `parse_band_label` use unsigned digit
  extraction. `-5 C or below` becomes an upper threshold of **+5**.
  The resulting ledger predicate says a 0 C settlement wins that negative band.
- The paper fallback uses `-?\\d+`, which interprets the separator in
  `80-81 F` as a minus sign: `("eq", 80, -81)`. With absent explicit band
  endpoints, a settlement of 80 is then scored as a loss.
- Similar fallback code is duplicated in the taker scoring/evaluation slices.
  Ordinary canonical rows with complete correct numeric endpoints avoid the
  second fallback defect; the signed-label defect is directly in serving.

**Smallest coherent repair:** one shared native-temperature-band parser, with
signed endpoints and an explicit distinction between a range separator and a
negative sign. Prefer validated numeric endpoints where available; compare them
with labels and reject contradictions. Reject inverted/ambiguous ranges rather
than emit a plausible band.

**Owner / plan:** market/model/backtesting; W2 and W11.
**Acceptance:** identical typed bands and outcomes across serving, settlement and
paper for positive/negative thresholds, signed ranges, zero, degree/unit
characters and supported dash spellings. Keep native-unit semantics; this is
not a Celsius/Fahrenheit conversion problem.

Source: [model presentation](../../../src/weather/model/model_presentation.py),
lines 152–183; [ledger parser](../../../src/weather/backtesting/settlement_ledger.py),
line 570; [paper parser and outcome](../../../src/weather/market/mm_paper_scoring.py),
lines 207–240 and 1802; [settlement IO](../../../src/weather/backtesting/settlement_io.py),
line 59.

### A15 — P2: future and negative ages can qualify paper quotes

**Reproduced.** `mm_policy.age_seconds` clamps future timestamps to zero.
Caller-provided book/watcher ages are checked against upper limits without
rejecting negative values. An otherwise fresh shadow fixture with a model
capture timestamp one year in the future and book/watcher ages of −3,600 seconds
still receives `quote_permission=True`; its model age becomes zero.

**Consequence:** corrupt clocks or inconsistent replay inputs can enter paper
quote generation as fresh evidence and bias subsequent strategy evaluation.
The same fixture keeps `live_trade_permission=False`; this finding does not
establish a live-executor bypass.

**Repair / acceptance:** use a shared age contract that checks finite numeric
types, explicit clock-skew tolerance and timestamp consistency. Negative ages
outside that tolerance and future capture observations must produce a named
non-countable/no-quote reason. A supplied age cannot contradict its timestamp.

**Owner / plan:** market evidence/policy, W5–W7.
Source: [quote policy](../../../src/weather/market/mm_policy.py), lines 614,
1024, 1367–1375 and 1494–1522.

### A16 — P2: stale or unsupported CLOB reports silently change quote parameters

**Reproduced.** `policy_overrides_from_recon` accepts numeric suggestions from a
file with schema `unknown` and timestamp January 2020. It applies
`quote_size=25` and `harvest_half_spread=0.001` with no freshness, schema,
market/condition, target-date or economics binding. `mm_policy` enables this
path by default and overlays these fields on the policy configuration.

**Consequence:** a global historical research report can silently change today's
quote sizing and spacing. Other caps may constrain the result; that does not
make the input current, scoped or intentionally selected.

**Repair / acceptance:** default this to explicit research opt-in, or require a
versioned, dated, market-scoped policy proposal with provenance, parameter
bounds and an expiry. Record before/after values and why they were adopted.
Unsupported, stale and cross-condition examples must apply no overrides.

**Owner / plan:** market/reporting, W3 and W12.
Source: [CLOB policy reader](../../../src/weather/market/clob_recon.py),
lines 597–632; [policy application](../../../src/weather/market/mm_policy.py),
line 603.

### A17 — P1: the monitor can report software readiness from contradictory or unbound evidence

**Two reproduced counterexamples.**

1. Current and accepted economics have different hashes; the drift receipt
   names two other hashes. With matching dates/platforms and `status=PASS`,
   the Economics row still passes and the aggregate says
   `READY FOR EXPLICIT APPROVAL`.
2. A readiness payload has an unsupported schema and three declared blockers
   while retaining a PASS label and permission booleans. The display still
   considers readiness passed.

The collector checks recency and some identity fields, which is useful, but
those checks do not establish that the producer's decision applies to the
displayed inputs. Run identity is checked only when the readiness payload
supplies it.

**Boundary:** this is a misleading monitor conclusion. The canonical live
candidate validator separately recomputes hashes and checks schemas, blockers,
accepted identity and drift contents. This audit did not bypass it.

**Repair / acceptance:** share a pure receipt-validation layer with authoritative
consumers; bind the displayed decision to exact source identities and scope.
Until validated, show “recorded PASS; not verified” and withhold aggregate
software readiness. Do not create another independent gate engine in the UI.

**Owner / plan:** reporting/market, W12 with W5.
Source: [control-room reducer](../../../src/weather/reporting/market/operator_control_room.py),
lines 212–306 and 392–400; compare
[live candidate validation](../../../src/weather/market/mm_live_candidate_cli.py),
lines 639–692.

### A18 — P1: legacy accounting is relabeled pUSD without verifying the cash asset

**Reproduced.** The trading reader validates `cash_asset` only for the new paid
pilot schema. A legacy `mm_exchange_adapter` report explicitly labeled USDC
on a different chain is accepted as current and complete, and its net 1.25
is returned for display. The UI labels all those financial amounts and reserves
as pUSD.

**Consequence:** a historical or incompatible cash report can be presented in
the wrong asset. The legacy `_usdc` field suffix does not itself establish
either USDC or pUSD, exactly as legacy `_c` temperature suffixes do not prove C.

**Repair / acceptance:** propagate cash-asset identity through all financial
views. Display verified native units; for unbound legacy reports show the
recorded values with unknown/historical currency or suppress the monetary
conclusion. Test wrong chain, token, decimals and missing identity in both
schemas. Keep paid-versus-estimated separation.

**Owner / plan:** reporting + accounting, W4/W12.
Source: [trading reader](../../../src/weather/reporting/market/operator_trading.py),
lines 62–95; [financial UI](../../../app/views/control_room.py),
lines 139–181.

### A19 — P2: an ordinary amount of retained history makes all runs disappear

**Reproduced.** With 1,025 small valid run summaries, `run_folders` returns an
empty list; `latest_run` consequently returns `(None, {})`. The user sees no
observed maker run even though the newest run exists. Readiness discovery has
a similar 256-file saturation policy.

The read bounds themselves are sensible. Treating overflow as absence is not.

**Repair / acceptance:** use a producer-owned current-run pointer/index, or a
bounded current-date selection with explicit pagination. Report saturation
distinctly from missing evidence and retain a usable selected-run route.
Never remove read limits or recursively parse the entire evidence tree on
every browser refresh.

**Owner / plan:** reporting, W12.
Source: [run discovery](../../../src/weather/reporting/market/operator_control_room.py),
lines 26–79.

### A20 — P2: one malformed subsystem can remove the entire monitor

**Reproduced reducer failure and traced rendering consequence.** A JSON object
whose nested `streak` value is a list raises `AttributeError`. The page loads
control, evaluation and all extras inside one try block, then returns on any
exception before rendering even the independent project/session panels.

This fails closed rather than showing false health, but it removes useful
monitoring during exactly the sort of data failure it should explain.

**Repair / acceptance:** validate nested shapes at each reader; isolate errors
per panel and keep unaffected observations visible. Include malformed nested
arrays/objects and partially written evidence in tests. Keep unknown state
explicit; do not turn parse errors into healthy empty defaults.

**Owner / plan:** reporting/app, W12.
Source: [host reducer](../../../src/weather/reporting/market/operator_control_room.py),
line 190; [page boundary](../../../app/views/control_room.py), lines 201–208.

### A21 — P2: event discovery returns success without proving pagination completed

**Reproduced at a deliberately small bound.** `fetch_gamma_events(limit=1,
max_pages=1)` receives one full page and returns ordinary rows/offsets.
Reaching `max_pages` is indistinguishable from finishing the query. The normal
default has a larger ceiling, but no explicit completeness result.

**Consequence:** a bounded or interrupted discovery design can publish a partial
universe as a normal refresh. This is not a claim that today's default 20-page
query actually truncates.

**Repair / acceptance:** require a terminal short page or an equivalent API
completion proof. A full page at the ceiling must return a clearly incomplete
result that cannot replace the complete discovery generation. Preserve the
previous known-good metadata and record the bounded failure.

**Owner / plan:** operations/market, W2.
Source: [Gamma pagination](../../../src/weather/operations/location_config_refresh.py),
lines 79–107; publication at lines 370–399.

### A22 — P2: the mandatory orientation is itself an unbounded maintenance dependency

**Measured.** At this source, the five routinely required research entry files
(root AGENTS, STATE, AGENT_CONTEXT, ESTABLISHED_FINDINGS and RETRACTED_AND_FALSE_LEADS)
total **33,359 whitespace-delimited words**. ESTABLISHED_FINDINGS alone is
2,831 lines / 26,243 words. Additional operations, delegation and scoped guidance
then applies. A 79-line STATE is still 1,163 words.

The source inventory is not a measure of agent runtime savings. It does establish
that “short distilled state” and “read all of this first” no longer fit together.
A bounded report-summary command was also rejected by the host hook during this
audit; it was moved to admitted workstation execution. Protection should remain,
but these false positives have a real workflow cost worth testing.

**Repair / acceptance:** make the mandatory starting material a short index of
current decisions, claim IDs, applicability, status, evidence and reopening
conditions. Archive detailed narratives without deleting them. Use a word/read
budget rather than line count. Put procedural scope in one canonical owner and
link it; retain adversarial tests for admission while adding representative
benign read-only commands to its regression corpus.

**Owner / plan:** operations/docs, W1/W12.
Do not add this historical audit to the mandatory read-all chain.

## Rules challenged: keep the property, change the overreach

These are recommendations, not permission to bypass the current contract.

| Rule family | Disposition | Reason and proposed boundary |
| --- | --- | --- |
| Canonical package/UI ownership; repository-root paths; Windows bootstrap files | **Keep** | They prevent ambiguous imports and working-directory dependence. Simplification belongs in domain owners, not new root wrappers. |
| Native settlement units | **Keep and test more deeply** | A14 shows the missing band semantics. Suffixes and unsigned regexes are not unit/type contracts. |
| WU is the universal primary settlement proxy | **Scope by event contract** | Keep historical WU evidence semantics; qualify actual Rules before claiming venue settlement/impossible outcomes. A13 gives a current counterexample. |
| Train/serve parity, effective print cutoffs, probability conservation, captured replay and release binding | **Keep** | These protect identifiable correctness properties. Changing a resolution source needs an explicit new contract and migration, not relaxation of old evidence. |
| International only; no paid providers; no live authority from implementation | **Keep** | These are owner scope/budget/authority decisions. Remove unwanted executable compatibility surfaces only after reader/evidence disposition. |
| Capture-host protected windows, shared lease, complete child-tree containment | **Keep pending measured redesign** | Capture has a separate resource budget. Workstation allowance does not make production parallelism safe. Make admission diagnostics precise rather than bypassing them. |
| Source integration changes production runtime; quiet-window/recovery rules | **Keep current protection, replace coupling** | Immutable deployment activation is the structural solution. Merely deleting the guard leaves the actual failure mode. |
| A capture streak is the overriding project objective | **Revise** | Protect actual gaps, usable execution intervals, settlement evidence and incident recovery. Contiguity should be required by a named consumer, not treated as the economic objective. |
| All research requires the same date × market uncertainty recipe | **Scope to the estimand and design** | Crossed dependence matters for fleet generalization. A fixed one-market experiment cannot acquire independent market clusters by convention. Prespecify the actual units and limitations; do not manufacture certainty. |
| Observed-effect power is independent evidence of adequacy | **Reject that interpretation** | It repackages the observed effect/SE. Use prospective power/MDE for design, intervals and predefined economic thresholds for inference. If retained as policy conservatism, label it as policy. |
| Gaussian simulation automatically lower-bounds a selected heavy-tail quantile | **Reject without proof** | Tail heaviness alone does not establish the needed quantile ordering for the selected statistic. Preserve the original frozen protocol; correct the explanatory claim in an explicit successor. |
| Every empirical model stage deserves indefinite production participation | **Reject** | Require a current decision contribution and a retirement route. Preserve necessary artifacts, not default execution of every old hypothesis. |
| Every report should recur daily | **Reject** | Essential evidence producers, current maker analysis and on-demand historical work need different lifecycles. Avoid another scheduler framework. |
| Module-size limits and mandatory edge removal on every related split | **Use as diagnostics, not success metrics** | A smaller file can preserve the same dependencies. Prefer reduced runtime import surface, ownership and behavioral tests over cosmetic repartitioning. |
| Exact warning counts and mandatory changed documentation | **Already repaired** | Keep the W1 behavior that accepts reductions and justified unchanged review. Do not rebuild those defects in another ratchet. |
| Preserve every branch forever versus guarded cleanup | **Reconcile** | Preserve required commits/evidence and dependencies; remove terminal owned worktrees through the existing guarded cleanup contract. Never sweep unowned state. |
| All ignored caches are expendable | **Reject** | Some depend on mutable or absent historical inputs. Require immutable rebuild identity/parity before treating them as disposable. |
| Ubuntu CI plus static Windows assertions proves operational Windows behavior | **Reject** | Retain Ubuntu coverage and existing native receipts; automate a small Windows lifecycle/locking/containment tier on a non-capture runner. |
| A normalized receipt with hashes proves the external event occurred | **Reject** | W4 is intentionally a pure matcher. An authenticated collector/normalizer must bind raw records to those hashes before any real income claim. Do not turn synthetic fixtures into operational evidence. |

For the observed-power distinction, see the original statistical analysis:
[Hoenig and Heisey, “The Abuse of Power”](https://sciences.ucf.edu/biology/pascencio/wp-content/uploads/sites/24/2016/11/HoenigHeisey2001.pdf).
This audit did not rerun historical hypothesis tests or allocate statistical alpha.

## What can be removed, and what must first be proved

| Surface | Proposed disposition | Required evidence |
| --- | --- | --- |
| `tools/research/fix_app.py`, `train_all.py`, `train_all2.py` | Delete inert retired-command stubs and their active harness entries | Current files only parse arguments, announce retirement and exit; remove live references in the same change |
| August 23 protected-window exception | Remove expired executable path | Retain historical authorization/incident receipts; preserve current generic admission/recovery |
| Recurring June 23 repair | Remove from default daily registry/mapping/import closure | Keep the dated result and an explicit reproducibility route if still consumed |
| Taker and closed research reports | Retire from active imports/default scheduling first | Inventory actual downstream finalization/ledger users; source deletion is a later consumer decision |
| Handwritten US order-submission adapter | Remove after bounded caller audit | Historical US readers/fixtures may remain; do not delete all of `mm_exchange.py` |
| Duplicate International HTTP execution path | Remove if current official-adapter path covers all active callers | Verify public imports/external use before deleting; preserve sealed SDK qualification |
| Manual hosted retraining workflow | Remove unless it has a separate owner/purpose | Its automatic schedule is already disabled; retain reproducible candidate-building commands |
| Empty deprecated registry shell | Remove only with reader/default-path migration | Do not replace explicit unknown-ID rejection with an implicit fallback |
| Optional/quarantined live variants | Disable default participation and retire unused loaders | Named consumer plus release/captured-input replay audit; registry flags are not actual runtime proof |
| Expanded order-book CSV projection | Stop future duplicate writes after consumer migration | Preserve raw canonical JSONL and distinguish nonidentical historical partitions |
| Incident-specific reconciliation implementations | Retire from ordinary launch surface after terminal disposition | Fresh integration/recovery/publication evidence; Git ancestry alone is insufficient |
| Repeated density-shape helper | Consolidate into the shared feature owner | Exact duplicate exists in training and serving; add one shared-contract parity check rather than maintain two copies |
| Large text renderers/facades | Simplify only alongside removed behavior/dependencies | No file-splitting campaign or new plugin/framework merely to lower line counts |

The density duplicate is in
[pooled density training](../../../src/weather/calibration/pooled_density_training.py),
line 187, and [variant runtime](../../../src/weather/model/variant_prediction_runtime.py),
line 939. Equal source today is useful evidence; it is not a permanent
train/serve parity guarantee.

## Architecture and effort priorities

The audited tracked-text totals include comments, blanks and local scoped
guidance: reporting 121,160 lines, operations 74,912 and market 67,882.
Several single functions span 700–900 lines, including paper/report rendering,
daily orchestration, provenance attestation and isolated subprocess handling.
These numbers identify review surfaces, not proved waste.

Deduplicated absolute import statements show 131 operations→reporting sites,
22 reporting→operations sites, 21 reporting→calibration sites and
18 calibration→reporting sites. These are owner-level dependencies, not a claim
of a runtime circular-import crash. Remove unused active imports and consume
small persisted result contracts before adding further facades.

Use the existing work packages in this order:

1. **Correctness repair:** A14 signed bands and shared parsing; A13 event Rules
   and settlement-contract qualification. Preserve the old replay semantics.
2. **Evidence truth:** A15/A16 quote inputs; A17/A18 readiness and currency;
   A19/A20 useful monitoring under history growth and malformed evidence.
3. **Publication:** A04/A21 atomic discovery generations with completion proof;
   finish the already identified production documentation transaction.
4. **Decision work:** one current condition, current campaign/rules/book evidence,
   capital feasibility, named competitor-score scenarios and actual normalized
   account/credit provenance. No new alpha-model programme is needed.
5. **Operational reduction:** A02/A03 primary capture first and a smaller active
   daily chain; delete inert/expired surfaces with consumer disposition.
6. **Structural migration:** A06 immutable deployment activation; A09/A11/A12
   dependency, empirical-stage and storage reduction; A22 shorter mandatory
   guidance and a focused Windows CI tier.

Do not count a lifecycle PASS, reward-accrual estimate or paper fill as economic
success. Conversely, a strategy need not make trading-only profit before
rewards are considered: item 330 explicitly permits rewards-dependent returns
when paid receipts and all costs support them. Official
[liquidity reward rules](https://docs.polymarket.com/programs/liquidity-rewards)
and [maker rebates](https://docs.polymarket.com/programs/maker-rebates)
describe distinct programmes; current exact-condition evidence and paid
attribution still determine the result.

A useful completion dashboard measures default jobs retired, primary-capture
latency and gaps, runtime imports removed, generated Git churn, proved restore
coverage, missing-accounting reasons, capital tied up, and progress toward the
predeclared economic decision. It must not equate code volume, report volume,
test counts or positive point estimates with success.

## Checks that prevented false findings

- Nonfinite fee counts are rejected by the existing numeric normalizer; the
  initial suspicion of a conversion crash was false.
- International paper diagnostics already exclude liquidity rewards from primary
  P&L. The old CLOB-depth competitor-score field must not be revived as a venue
  denominator, but this audit did not find it booking International reward income.
- W4 correctly distinguishes unpaid accrual from confirmed cash, checks exact
  micro-units and treats unknown attribution/completeness as unresolved. Its
  missing live provenance integration is a stated boundary, not hidden proof
  that cash was paid.
- The canonical live candidate path checks economics identities much more
  strictly than the monitor. A17 is not evidence that the execution gate accepts
  the same malformed inputs.
- The new monitor rejects stale observations, mixed run/date reports and wrong
  assets in its paid schema. A18 identifies the remaining legacy-schema gap.
- The paid weather client remains disabled. Its compatibility class is not
  evidence of active paid access.
- One restored off-site pilot does not establish a restorable whole mirror or
  permission to reclaim unrelated evidence.
- Failed historical experiments remain failed on their stated populations.
  Challenging overgeneralized prose does not reopen them or change their
  retained results.
