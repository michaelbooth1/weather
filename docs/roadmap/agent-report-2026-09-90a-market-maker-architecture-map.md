# 90a — market-maker architecture map and migration plan

**Verdict: design deliverable complete; implementation and live qualification not performed.**
One International Polymarket maker is feasible by extracting the existing shared kernels and
consolidating the venue and session boundaries. Do not start RE-2 or unattended quoting until
the migration gates below pass. This report grants no live authority and makes no profitability claim.

This dated report answers handoff 90a. It owns a source-based map and proposed migration,
not current operating instructions. Read the [delegation contract](../operations/DELEGATION_CONTRACT.md),
[package boundaries](../operations/package-boundaries.md) and
[live-executor contract](../operations/PORTABLE_LIVE_EXECUTION_HOST.md) for standing authority.

## Evidence and work boundary

Written 2026-09-24 on the workstation. The owner explicitly permitted code reading and report
writing during RE-1 session 5, overriding the handoff's start restriction for this analysis only.
No tests, compilation, workstation-heavy jobs, venue calls, credentials, campaign data,
RE-1 checkout, production host or mirror were used for this report. The session end time is
not permission to resume heavy work: that requires explicit owner confirmation.

Source was read from cached Git objects after the earlier requested fetch. These are immutable
analysis snapshots, not assertions about the running executor's tip:

| Key | Source | Exact commit |
| --- | --- | --- |
| M | fetched `origin/master`; report branch base | `198f7ccbcd8e80271693462425582097d22b298b` |
| H | `origin/codex/reward-test-attended-handoff-20260921`; handoff 90a | `7014b637e228228fab763a7febea82c8852b6809` |
| R | 84h, `origin/codex/re1-wallet-200-20260923` | `51975cfccec806054a20267a1576ee92fc93796f` |
| S | `origin/codex/stage2-hold-build-20260921` | `88aa7e43a71d5870575261280b45c9deae667668` |
| E | 88a, `origin/codex/maker-evidence-capture-20260923` | `7953d26081f8e135be52760e24f3e5554693def9` |
| D | 89a plus 89c, `origin/codex/fill-toxicity-desk-study-20260923` | `d3dff0f2b1783741e2c4927cf74e8032bd17b02b` |

Report branch: `codex/maker-architecture-map-20260924`. Only this report is changed.
R includes a different `mm_stage2_selection.py` and `reward_quote.py` from S: the sized
treatment is explicit and the sealed twenty-share proposer remains separate. Do not combine
branches by copying whichever file looks newest. E and D are examined as separate research
stacks; their runtime integration is not presumed.

Evidence notation `R:module.py:line` means `src/weather/market/module.py` in the pinned R
commit, recoverable with `git show <commit>:<path>`. Test names below are under `tests/market/`
unless a different directory is written. Local branch files need not contain R/E/D modules.
The inventory is a static ownership/caller map, not a claim of exhaustive runtime reachability.
CLI entrypoints are callers too. Shared modules retain non-maker consumers.

## Module map

Domain column: **N** = domain-neutral (possibly Polymarket-, Windows-, or experiment-specific),
**W** = weather-specific, **X** = mixed and must split at a plugin boundary.
Layer numbers are venue **1**, universe **2**, value/information clock **3**, quoting **4**,
portfolio **5**, safety/evidence **6**. Multiple numbers identify existing mixing, not the target.
Stack labels: **P** paper/shadow worker, **L** Stage 0/1 plumbing, **S** sealed Stage 2 hold,
**R** attended RE-1, **E** public maker evidence, **D** toxicity desk study, **F** feasibility research,
**C** shared capture substrate. Callers are principal consumers, not new authority.
Test keys identify the regression groups below; some coverage is through the calling module,
not a same-named test file. An import/caller index follows the design.

### Quoting, research and weather worker (R snapshot)

| Module | Purpose | Domain; layer | Callers / stacks | Tests |
| --- | --- | --- | --- | --- |
| `reward_quote.py` | Decimal proposal, qualified midpoint, actual-token touch checks, frozen/sized treatments | N; 4/5 | hold, selection, sizing; S/R | Q, S, R |
| `reward_share_estimate.py` | Quadratic reward kernels plus raw tape estimator, date/event sampling and reports | X; 4/6 | reward_quote, E public estimates, D simulation, CLI; F/S/R/E/D | Q, E, D |
| `maker_incentive_feasibility.py` | Decimal scoring, capital and scenario feasibility, weather identity validation | X; 2/4/5 | reward simulation; F | F |
| `maker_opportunity_capture.py` | Bound public opportunity packets, reward pages and token discovery | X; 1/2/6 | CLI, packet validation; F | F |
| `maker_opportunity_inputs.py` | Validate captured packet provenance, books and allocations | N; 1/6 | reward simulation; F | F |
| `maker_reward_simulation.py` | Scenario presets and feasibility simulation | N; 4/5/6 | research/UI consumers; F | F |
| `mm_policy.py` | Quotes, risk-limited size, weather guards, freshness, event gates, input assembly and CLI | X; 3/4/5/6 | worker, paper, live helpers; P/L | P, W |
| `mm_risk.py` | Inventory, Kelly/capital, negative-risk transitions and weather correlation grouping | X; 3/5 | policy and paper; P | P |
| `info_event_calendar.py` | Weather print/model schedules, exceptions and quote-event gating | X; 3/4/6 | policy, worker, event scoring; P | W |
| `market_making_run.py` | Weather worker run/loop, preflight, tapes, projections and release lineage | X; 2/3/4/5/6 | CLI/supervision; P | P, W |
| `market_making_run_constants.py` | Run paths, modes, columns and pilot bounds | X; 6 | worker, adapter, pilot, projections; P/L/S | P, L |
| `market_making_run_support.py` | Weather input joins, preflight, lifecycle ledger and budget reservations | X; 2/3/5/6 | worker and portable preflight; P/L | P, L |
| `market_making_live_pilot.py` | Construct worker policies for pilot/harvest modes | X; 4/5/6 | worker; P/L | P |
| `market_making_model_variants.py` | Weather model variants, external variant alignment and quote comparison | W; 3/4/6 | worker and paper; P | P |
| `market_making_preflight.py` | Platform/wallet gates alongside weather data-layer gates and remediation | X; 3/6 | readiness, worker, bootstrap, credentials; P/L | P, L, V |
| `market_making_readiness.py` | Combine runtime, date, source and paper evidence into readiness | X; 3/6 | CLI/UI; P/L | P |
| `market_making_evidence.py` | Classify active-day versus historical worker evidence | W; 6 | worker and readiness; P | P |
| `live_forward_gate.py` | Per-market data gates and countable-forward evidence | X; 3/6 | worker/readiness; P | P |
| `live_observation_normalization.py` | Monotonic weather-high ledger, revisions and band probability checks | W; 3 | policy and worker; P | W, P |
| `mm_paper.py` | Offline quote/fill evaluation, rewards diagnostics, PnL and report orchestration | X; 4/5/6 | CLI/UI; P | P |
| `mm_paper_scoring.py` | Quote legs, trade identity, queue fills, markouts and temperature settlement | X; 3/4/6 | paper and aggregation; P | P |
| `mm_paper_aggregation.py` | Bounded SQLite spill/index and cross-run aggregation | N; 6 | paper; P | P |
| `mm_paper_constants.py` | Paper paths/defaults/report columns | X; 6 | paper, scoring, reports; P | P |
| `mm_paper_evidence.py` | Run eligibility and per-market forward evidence credit | X; 6 | paper/scoring; P | P |
| `mm_paper_reports.py` | Paper report, promotion evidence and weather known-edge map | X; 3/6 | paper/UI; P | P |
| `mm_scoring_projection.py` | Bound scoring projections, append-prefix identity and backfill | N; 6 | worker, paper scoring, CLI; P | P |
| `clob_recon.py` | Passive execution/markout slices and policy diagnostics | X; 4/6 | paper, optional policy overrides, CLI; P/F | P, C |
| `execution_tape_markout.py` | Public-print side inference, markouts, clustered intervals, weather close/settlement | X; 2/3/6 | D, CLI; F/D | D, C |

### Venue, authority and lifecycle (R snapshot)

| Module | Purpose | Domain; layer | Callers / stacks | Tests |
| --- | --- | --- | --- | --- |
| `mm_exchange.py` | Fixture/null adapters, HTTP request plans, legacy adapters, reconciliation harness | X; 1/6 | paper, credentials diagnostics, CLI; P/L | V, P |
| `mm_exchange_reports.py` | Fees, rebate/position evidence, financial and incentive reconciliation | N; 1/6 | exchange, paper, Stage2 rewards, RE1 payout; P/S/R | V |
| `mm_official_adapter.py` | SDK normalization, exact positions, scoped reads, gated placement and verified cancel | N; 1/6 | live CLI, Stage2, RE1 OwnerVenue; L/S/R | V, L, S, R |
| `mm_official_transport.py` | HMAC heartbeat and public SDK-gap reads | N; 1 | live CLI/credentials, RE1 heartbeat subclass; L/S/R | V, R |
| `mm_user_stream.py` | Authenticated account stream, readiness, health and journal | N; 1/6 | live CLI, Stage2/RE1 subclasses; L/S/R | V, S, R |
| `mm_credentials.py` | WinCred references, secret hygiene, SDK client identity and construction | N; 1/6 | live CLI/importer; L | V, L |
| `mm_credential_import_cli.py` | Create-only guarded credential import and compare evidence | N; 6 | owner CLI; L | V |
| `mm_geographic_eligibility.py` | Attended eligibility and public geoblock evidence | N; 6 | attendance/bootstrap/lifecycle/hold; L/S | V, L, S |
| `mm_pilot_capital.py` | Pilot declaration, collateral/allowance and exact wallet envelope | N; 5/6 | live bootstrap/adapter/CLI; L/S | V, L |
| `mm_liquidity_earnings_evidence.py` | Bound paginated earnings evidence normalization | N; 1/6 | reports and Stage2 rewards; P/S/R | V |
| `mm_paid_credit_activity.py` | Link captured reward activity to confirmed cash transfers | N; 1/6 | incentive reconciliation; P/R | V, R |
| `mm_live_attendance.py` | Digest-bound attended confirmation | N; 6 | portable/live launch support; L | L |
| `mm_live_envelope.py` | Explicit immutable Stage1/hold envelope selection | N; 6 | live, official adapter, Stage2; L/S | L, S |
| `mm_live_bootstrap.py` | Account/topology, balance, geography, stream and market bootstrap | X; 1/5/6 | live CLI; L | L, V |
| `mm_live_candidate_cli.py` | Weather candidate discovery, accepted economics and paper-substrate binding | W; 2/4/6 | CLI, portable preflight, live lineage; L | L |
| `mm_live_stage0_scope.py` | Weather event metadata and one-token Stage0 scope binding | W; 2/6 | CLI, lifecycle plan, live CLI; L | L |
| `mm_live_stage1_lifecycle_plan.py` | Bound weather token/condition lifecycle plan | W; 2/6 | CLI and live CLI; L | L |
| `mm_live_lifecycle_probe.py` | Bounded Stage1 cancel/dead-man protocol and chained lifecycle evidence | N; 1/6 | live CLI and Stage2 validation; L/S | L, S |
| `mm_live_pilot_cli.py` | Identity/doctor/bootstrap/probe/bundle commands and cleanup | X; 1/2/6 | owner CLI; L | L, V |
| `portable_live_candidate_preflight.py` | Exact weather inputs/economics/token preflight | W; 2/3/6 | CLI and candidate binding; L | L |
| `live_sdk_overlay.py` | Explicit SDK overlay activation and identity | N; 6 | import/live launcher support; L | V |
| `live_sdk_portability.py` | Offline SDK/wheelhouse portability checks | N; 6 | provisioning CLI/tooling; L | V |

### Hold and attended experiment (R snapshot; S remains a frozen profile)

| Module | Purpose | Domain; layer | Callers / stacks | Tests |
| --- | --- | --- | --- | --- |
| `mm_stage2_entrypoint.py` | Keyless doctors, campaign reservation, sealed hold and terminal validation | N; 6 | sealed launcher; S | S |
| `mm_stage2_hold.py` | Durable journal primitives, public proposal binding, held scoring and hold controller | N; 4/5/6 | entrypoint/rehearsal; primitives reused throughout RE1; S/R | S, R |
| `mm_stage2_selection.py` | Weather discovery/ranking, public book reads, frozen versus 84h local-day selection | X; 1/2/4 | selection tools, hold, RE1; S/R | S, R |
| `mm_stage2_user_stream.py` | Pair-scoped stream subclass and hold-journal verification | N; 1/6 | Stage2 entrypoint; S | S, V |
| `mm_stage2_rewards.py` | SDK reward reads, prediction loading and paid-evidence verdict | N; 1/6 | rewards tooling, RE1 OwnerVenue; S/R | S, R |
| `mm_stage2_rehearsal.py` | Fake clock/venue/adapter and deterministic hold rehearsal | N; 6 | rehearsal CLI, RE1 fixtures; S/R | S, R |
| `re1_attended.py` | Secret guard, held-score observer, replacement prices and bounded session controller | N; 4/5/6 | attended CLI/owner checks/rehearsal; R | R |
| `re1_attended_cli.py` | Rehearse, explicit live, cancel-only and collection commands | N; 6 | owner CLI; R | R |
| `re1_evidence.py` | Fixed campaign root, host mutex, attempt markers, replay, adequacy and payout verdict | N; 6 | CLI/owner checks/payout; R | R |
| `re1_owner_checks.py` | Exact source preflight, bounded latency proof and owner-bound reconciliation | N; 6 | owner CLI; R | R |
| `re1_payout_evidence.py` | SDK/RPC read journal, accrual/cash linkage and frozen evidence reconciliation | N; 1/6 | post-session owner CLI; R | R, V |
| `re1_rehearsal.py` | Clock and public/venue fixtures around Stage2 fakes | N; 6 | attended CLI, checks/tests; R | R |
| `re1_resilience.py` | Read budgets/freshness and independent heartbeat/main-loop watchdog | N; 1/6 | session; R | R |
| `re1_sizing.py` | Explicit 20/30/50/75-share affordability and reserve caps | N; 4/5 | selection, proposer, session, transport; R | R, Q |
| `re1_transport.py` | Owner SDK factory, pair stream, rotating heartbeat, venue wrapper and checked single post | N; 1/6 | live/cancel/collect/check commands; R | R, V |

### Shared universe and capture substrate (R snapshot)

| Module | Purpose | Domain; layer | Callers / stacks | Tests |
| --- | --- | --- | --- | --- |
| `market_registry.py` | Built-in weather market specs and slug lookup | W; 2 | selection, policy, capture, research; all weather stacks | W, L, C, D |
| `market_config.py` | Weather event slug/date/config construction | W; 2 | discovery/worker/capture; all weather stacks | W, L, C |
| `location_config.py` | Weather location metadata/config access | W; 2 | Stage0 scope, registry/config consumers; L/C | W, L |
| `market_day_labels.py` | Settlement-ledger finalization CLI, label quality and resolved-market reconciliation | W; 2/6 | daily-refresh steps and CLI; shared settlement substrate | W |
| `market_latest_inputs.py` | Bounded latest snapshot/book/history joins and freshness diagnostics | X; 3/6 | taker CLI; adjacent shared-input boundary, not a separate maker stack | W |
| `polymarket_client.py` | Public market client with weather-configured event defaults | X; 1/2 | microstructure capture/loop; C | C, W |
| `market_microstructure_constants.py` | Venue URLs plus weather tape schemas and capture defaults | X; 1/6 | capture, streams, tape readers; C/L/S/R/E | C, V |
| `market_microstructure_capture.py` | ClobClient, token/band metadata, book/history/WS normalization and stores | X; 1/2/6 | capture loop, live discovery; C/L | C, L |
| `market_microstructure.py` | Weather capture supervision, liveness, tape audit and orchestration | X; 2/6 | supervisor/CLI, worker preflight; C/P | C, P |
| `market_microstructure_features.py` | Weather band joins, book/WS/history features | X; 3/6 | policy/worker/capture/release verification; C/P | C, W |
| `execution_tape_store.py` | Rotating execution evidence, market-day routes, identities and gap records | N; 1/6 | execution capture; C | C |
| `execution_tape_capture.py` | Weather seeds, partitioned public stream capture and fixtures | X; 1/2/6 | capture CLI/supervisor; C | C |
| `order_book_tape.py` | Full-book representation choice, raw/CSV/archive provenance | N; 6 | offline book consumers; C/P/F | C |
| `exchange_economics.py` | Venue terms/provenance, weather snapshot collection, drift and acceptance | X; 1/2/6 | worker/paper/candidate and CLI; P/L/F | V, P, F |
| `exchange_economics_sources.py` | Strict public response/provenance budgets and reward-page validation | N; 1/6 | economics/opportunity/earnings; P/L/F/R | V, F |
| `exchange_economics_run_capture.py` | Bind legs to captured run economics and preserve snapshot evidence | N; 6 | economics facade; P | V, P |
| `snapshot_cadence_quality.py` | Cadence quality and probability adjustment for weather rows | X; 3/6 | policy/shared forecast evaluation; P | W, P |
| `storage_pressure_policy.py` | Validated capture write-pressure policy | N; 6 | microstructure capture; C | C |
| `worker_release_binding.py` | Model/replay hash, probability and tape lineage enforcement | X; 3/6 | worker and other weather evaluation; P | W |

### Branch additions

| Module and ref | Purpose | Domain; layer | Callers / stacks | Tests |
| --- | --- | --- | --- | --- |
| E `maker_evidence_capture.py` | Weather-plus-extra universe, RE1-aware bounded capture orchestration | X; 1/2/6 | capture CLI; E | E |
| E `maker_evidence_public.py` | Public reader, reward modeling and universe selection | X; 1/2/4 | evidence capture; E | E, Q |
| E `maker_evidence_socket.py` | Bounded websocket frames/connection | N; 1 | evidence stream; E | E |
| E `maker_evidence_stream.py` | Public book/trade stream and storage | N; 1/6 | evidence capture; E | E |
| E `maker_evidence_store.py` | Exclusive writer, bounded evidence segments, body hashes and disk bands | N; 6 | E capture/stream/inspect/archive; E | E |
| E `maker_evidence_archive.py` | Compress closed evidence segments | N; 6 | evidence capture; E | E |
| E `maker_evidence_inspect.py` | Offline coverage/integrity inspection | N; 6 | inspection CLI; E | E |
| D `fill_toxicity_desk_study.py` | Weather event panel, settlement binding and report orchestration | W; 2/3/6 | study CLI; D | D |
| D `fill_toxicity_inputs.py` | Defect-aware capture reads, terms/books/trades/weather staging and coverage | X; 1/3/6 | desk study; D | D |
| D `fill_toxicity_model.py` | Frozen quote simulation and weather information/placebo windows | X; 3/4 | study/inputs; D | D, Q |
| D `fill_toxicity_panels.py` | Minute panel accumulation and statistics | N; 6 | desk study; D | D |
| D `fill_toxicity_statistics.py` | Clustered inference, reward/latency summaries and decision rules | N; 6 | study/panels; D | D |

The remaining R market package modules are the `taker_*` family and package marker `__init__.py`.
They are not alternative maker stacks. Preserve their imports of shared weather policy, risk,
capture and release helpers; a maker extraction must not silently migrate taker decisions.
This perimeter deliberately includes adjacent capture/config/readiness modules so that a
"maker-only" move cannot hide a production import-closure change.

## Duplicated and overlapping responsibilities

These are consolidation targets, not a claim that all algorithms are interchangeable. Line
evidence is at the pinned snapshots above. Keep compatibility serializers and frozen profiles.

| Responsibility | Source evidence | Required disposition |
| --- | --- | --- |
| Venue order/read boundary | R `mm_exchange.py:978` GlobalHTTPAdapter; `mm_official_adapter.py:588`; `re1_transport.py:296,437` OwnerVenue | One International SDK-backed venue port. Legacy HTTP/US adapters stay compatibility fixtures, never selectable for a new live lane. RE1 uses the official adapter for reads/cancel but implements checked signing/post itself: consolidate that path only after parity. |
| Heartbeat ownership/protocol | R `mm_official_transport.py:181`; `re1_transport.py:42`; `re1_resilience.py:76`; `mm_stage2_hold.py:382` | Separate one venue protocol implementation from safety watchdog scheduling. Preserve RE1 rotating-ID resynchronization without treating a challenge as an acknowledgment; frozen Stage1 behavior is not silently upgraded. |
| User-stream lifecycle/scoping | R `mm_user_stream.py:44,255`; `mm_stage2_user_stream.py:54,78`; `re1_transport.py:212,233,365` | These subclass and reuse normalization, not three independent parsers. Extract explicit account/pair scope policy, one normalizer and reconnect supervisor; retain unknown-account/fill failure semantics. |
| Public HTTP/book/reward reads | R `market_microstructure_capture.py:673`; `mm_stage2_selection.py:126`; `maker_opportunity_capture.py:112`; `exchange_economics.py:377`; E `maker_evidence_public.py:38,146`; R `re1_transport.py:119,142` | One bounded public read/provenance service, separate consumers/cadences. Do not make a live quote depend on research archive availability. |
| Universe and candidate selection | R `mm_live_candidate_cli.py:1059`; `mm_live_stage0_scope.py:988`; `mm_live_stage1_lifecycle_plan.py:333`; `mm_stage2_selection.py:27`; E `maker_evidence_capture.py:100`, `maker_evidence_public.py:194` | Weather plugin owns discovery/date/identity; quoting owns economic ranking; safety owns authorized scope. The Stage0 plumbing choice and RE1 reward ranking are different profiles, not competing default selectors. |
| Reward quadratic and Q-min | R `maker_incentive_feasibility.py:196,209`; `reward_share_estimate.py:134,155` | Actual Decimal/float duplicate formulas; units differ (probability versus cents). Extract a versioned neutral kernel with differential boundary tests before changing numerical representation. |
| Held score / qualified midpoint / own-depth subtraction | R `reward_quote.py:124`; `mm_stage2_hold.py:202`; `re1_attended.py:75`; E `maker_evidence_public.py:181` | Shared estimator already reused; held observers duplicate qualified-mid and own-depth logic. Keep proposal scoring (no own order yet), held scoring (subtract own) and plain-mid sensitivity distinct. |
| Price snapping / quote generation | R `reward_quote.py:132`; `re1_attended.py:132`; `mm_policy.py:1344,1352,1461`; D `fill_toxicity_model.py:123` | Common tick/touch kernel and policy state transitions. Frozen desk-study simulation is a consumer, never live authority. Weather edge quote versus reward-only profile remains explicit. |
| Deprecated reward approximation | R `mm_paper_scoring.py:809,818` | Linear score helper differs from International quadratic. Primary reward estimates are deliberately zero pending payout reconciliation. Do not "deduplicate" by reviving this historical estimator or adding predicted rewards to realized PnL. |
| Risk and reservations | R `mm_risk.py:274,384,516`; `market_making_run_support.py:1134,1357`; `mm_pilot_capital.py:19`; `re1_sizing.py:9,17`; `re1_attended.py:163` | One atomic wallet reservation owner, plus explicit profile caps. Weather correlations become plugin exposure factors. Preserve distinct allowance, available collateral, wallet envelope and order liability. |
| Session lifecycle/cancel/reconcile | R `market_making_run_support.py:1138,1177`; `mm_live_lifecycle_probe.py:451`; `mm_stage2_hold.py:309`; `re1_attended.py:142,389,408,495` | Paper ledger, plumbing probe, sealed hold and re-quoting are different modes over common event/state contracts. Migrate one profile at a time; do not replace frozen protocols with the most permissive controller. |
| Journals / immutable serialization | R `mm_live_lifecycle_probe.py:67`; `mm_stage2_hold.py:32,48,58`; `re1_attended.py:64`; `re1_payout_evidence.py:70`; E `maker_evidence_store.py:94` | RE1 GuardedJournal already extends HoldJournal. Extract an append-only journal primitive with locking/redaction/hash chaining; keep each historical schema, header and profile digest reproducible. Public capture segments are not live mutation journals. |
| Attempt and campaign reservation | R `mm_stage2_entrypoint.py:52`; `re1_evidence.py:66,97`; `mm_live_pilot_cli.py:136,449` | Common durable reservation state, but separate lane-specific budgets, namespace, lineage and approval. Never recycle a spent attempt during migration. |
| SDK/JSON/position normalization and closed-order failure | R `mm_exchange.py:317`; `mm_official_adapter.py:78,187,553,1481`; `re1_owner_checks.py:235`; `mm_live_bootstrap.py:137` | Normalize in venue; malformed/missing differs from empty. Closed-order reads may fail SDK decoding; retain typed failure plus raw redacted evidence. A historical-order failure is not a fabricated cancellation. Account closed-only mode is a different concept. |
| Earnings, cash linkage and verdicts | R `mm_exchange_reports.py:793`; `mm_liquidity_earnings_evidence.py:160`; `mm_paid_credit_activity.py:358`; `mm_stage2_rewards.py:176`; `re1_payout_evidence.py:227,395`; `re1_evidence.py:211` | Share readers and normalized facts, keep frozen verdict policies separate. Accrued, paid, ambiguous and incomplete are distinct. Do not collapse daily wallet credits into condition attribution without the reviewed rule. |
| Execution/markout reconstruction | R `clob_recon.py:316`; `mm_paper_scoring.py:1207,1643,1915`; `execution_tape_markout.py:133,437`; D `fill_toxicity_inputs.py:247`, `fill_toxicity_desk_study.py:244` | Shared identity/side/time facts and provenance; distinct inferred fills, public prints and actual maker fills remain labeled. No rewrite of historical research definitions. |
| Weather information and observation rules | R `info_event_calendar.py:237,270,431,521`; `mm_policy.py:386,462,519`; `live_observation_normalization.py:194`; D `fill_toxicity_inputs.py:357,457` | Weather plugin provides facts, schedules and exposure factors. Quoting applies neutral freshness/cooldown policy; research windows stay versioned consumers. Trusted observed-high and WU cutoff rules must survive. |
| Capture storage / coverage | R `execution_tape_store.py:404,554`; `market_microstructure_capture.py:751`; E `maker_evidence_store.py:94`; D `fill_toxicity_inputs.py:29,78,284` | Reuse low-level bounded storage/integrity mechanisms where contracts match; keep append/rotation and offline defect-tolerance policies separate. A research skip rule must never weaken a mutation journal. |

`exchange_economics.py:1334,1456` and `exchange_economics_run_capture.py:28,212` are a
facade/extracted implementation pair, not justification for another rewrite. Similarly, shared
reward imports and journal subclasses are evidence of existing reuse. The highest-risk duplication
is at mutation, reservation and failure interpretation boundaries, not repeated tiny formatting helpers.

## Proposed package and interfaces

Proposed paths are design names, not commands or files claimed to exist. Keep the canonical
`weather.market` owner. Initially add subpackages and leave existing imports/CLIs as facades.
No new top-level `src/*.py` wrappers, new live selector or environment override.

| Layer | Proposed owner beneath `src/weather/market/` | Responsibility / dependencies |
| --- | --- | --- |
| 1 Venue | `maker/venue/` (`polymarket`, `normalization`, `streams`, `rewards`) | The only SDK/HTTP mutation boundary; public and account reads with provenance; no weather imports. Credentials injected through existing authorized bootstrap. |
| 2 Universe plugin | `maker/plugins/weather/universe` plus `maker/contracts` | Weather registry, event-day/timezone, tokens, native settlement rules, reward terms, close/settle uncertainty. Plugin returns descriptors, never order authority. |
| 3 Value/clock plugin | `maker/plugins/weather/value`, `information`, `exposure` | Captured/release-bound probability view, weather schedules and observed facts, decidedness and exposure factors. WU remains settlement proxy; METAR/NBM are supporting inputs. |
| 4 Quoting | `maker/quoting/` (`rewards`, `prices`, `policy`, `state`) | Pure proposal and state-transition kernels; versioned parameters, typed books and plugin facts, no weather labels or SDK. |
| 5 Portfolio | `maker/portfolio/` (`ledger`, `limits`, `reservation`) | One wallet, atomic multi-leg reservation and aggregate exposure; venue balance truth plus filled inventory and unresolved mutations. |
| 6 Safety/evidence | `maker/runtime/`, `maker/evidence/` | One mutation coordinator, source/host/profile/attendance gates, watchdogs, attempts, reconcile, cleanup, immutable journals and versioned verdicts. Offline reports remain separate callers. |

Common contracts carry `domain_id`, `event_id`, `condition_id`, token/outcome identity, collateral
asset and amount units explicitly. Do not overload weather slugs or `_c` fields. Domain neutrality
does not require removing the `weather` Python namespace or hiding Polymarket-specific mechanics.

Signatures below specify boundaries only; no implementation is part of 90a:

```text
MarketUniverse.discover(as_of_utc: Instant, scope: DiscoveryScope) -> UniverseSnapshot
MarketUniverse.describe(condition_id: ConditionId, as_of_utc: Instant) -> MarketDescriptor
MarketUniverse.settlement(contract: MarketDescriptor, evidence: EvidenceRef) -> SettlementFact

ValuePlugin.evaluate(market: MarketDescriptor, inputs: CapturedInputs,
                     as_of_utc: Instant) -> ValueView | Unavailable
InformationPlugin.observe(market: MarketDescriptor, inputs: CapturedInputs,
                          as_of_utc: Instant) -> InformationState
ExposurePlugin.factors(market: MarketDescriptor, position: Position) -> ExposureVector

Venue.books(tokens: tuple[TokenId, ...], deadline: Deadline) -> ObservedBooks
Venue.rules(condition: ConditionId, deadline: Deadline) -> ObservedMarketRules
Venue.account(scope: AccountScope, deadline: Deadline) -> AccountObservation
Venue.order(order_id: OrderId, deadline: Deadline) -> OrderObservation | ReadFailure
Venue.subscribe(scope: AccountScope, cursor: StreamCursor | None) -> AccountEventStream
Venue.heartbeat(state: HeartbeatState, deadline: Deadline) -> HeartbeatObservation
Venue.reward_terms(condition: ConditionId, as_of_utc: Instant) -> ObservedRewardTerms
Venue.reward_evidence(query: RewardQuery, deadline: Deadline) -> PaginatedEvidence
Venue.submit_once(intent: BoundOrderIntent, capability: MutationCapability,
                  checkpoint: SafetyCheckpoint) -> SubmitOutcome
Venue.cancel(order_ids: tuple[OrderId, ...], capability: CancelCapability) -> CancelOutcome

Quoter.propose(market: MarketDescriptor, books: ObservedBooks, value: ValueView | None,
               information: InformationState, state: QuoteState,
               policy: FrozenQuotePolicy, now: ClockReading) -> QuoteDecision
RewardScorer.score(books: ObservedBooks, own: OwnOrderState,
                   terms: ObservedRewardTerms, model: ScoreModelVersion) -> RewardEstimate

Portfolio.reserve(plan: QuotePlan, observation: AccountObservation,
                  limits: LimitSet, expected_revision: Revision) -> Reservation | Refusal
Portfolio.apply(event: ExecutionFact, expected_revision: Revision) -> PortfolioSnapshot
Portfolio.reconcile(observed: AccountObservation, evidence: EvidenceRef) -> ReconcileResult

Runtime.authorize(scope: RequestedScope, proofs: SafetyProofs) -> SessionCapability
Runtime.step(observation: RuntimeObservation, decision: QuoteDecision) -> StepReceipt
Runtime.cancel_only(scope: OwnedOrders, proofs: CancelProofs) -> CleanupReceipt
Journal.append(event: EvidenceEvent, expected_sequence: int) -> DurableReceipt
Evidence.replay(inputs: EvidenceBundle, policy: VerdictPolicyVersion) -> Verdict
```

`UniverseSnapshot` records completeness, source hashes, effective/observed time and plugin
version; incomplete discovery cannot silently win ranking. `MarketDescriptor` records tick,
lot/order minimum, reward minimum/spread, neg-risk topology, native settlement unit, close time
and settlement time separately. Unknown settlement time is explicit, not copied from close.
Universe consumes venue facts; the venue does not import the plugin. A material terms/token
change invalidates the descriptor and any pending capability.

`ValueView` holds outcome probabilities, uncertainty, captured-input/release hashes, validity
deadline and availability; unavailable is not probability zero. A reward-only profile may
explicitly accept no fair-value estimate, but no missing view may bypass its risk/information
requirements. Weather mass, train/serve parity, observed-high floor and effective WU print cutoff
are plugin invariants. Native units stay attached to settlement and observations.

`InformationState` distinguishes scheduled event time, source publication time, locally observed
time and detector time, with freshness, confidence, affected tokens and decidedness. Use UTC
instants and monotonic elapsed deadlines; plugin event-day rules handle DST. A future view-count
plugin could emit uploads/view-count updates behind these contracts. No YouTube repository,
model or maker logic was assumed or inspected. A deterministic fictional plugin is enough to
test that the core has no dependency on temperature, stations, dates encoded in slugs or cities.

Quoting policy is a versioned state machine: hold inside the leave-alone band; compute the
midpoint from reward-size-qualified depth while all touch levels still constrain submission;
pull immediately on stale/decided/adverse information; require cooldown and fresh facts before
re-entry; debounce favorable flicker without delaying a safety pull; allow per-side asymmetric
reaction and bounded requotes/orders/time. Every decision includes reason codes and input hashes.
Unsafe information always wins over reward maximization. Existing RE1 constants become its
frozen profile; future thresholds and whether a policy is profitable require separate evidence.

The portfolio reserves both BUY legs atomically before the first post. It counts resting orders,
partial fills, held-to-settlement inventory, reserved replacement orders, and uncertain submits
against market, event, domain and wallet caps. Netting requires explicit verified venue collateral
semantics; complementary outcomes do not automatically free cash. Generic factor aggregation
consumes plugin exposures; cross-domain independence is not assumed. Unknown account orders
block new risk. A new domain must not create another wallet ledger or heartbeat owner.

Safety owns one serialized wallet mutation coordinator. Read-only and cancel-only capabilities
cannot place orders. Signing may read metadata, so a submit checkpoint and actual-token book
check remain after signing, immediately before the single raw post. Ambiguous submit outcomes
enter reconciliation, never blind retry. Cancellation acknowledgment and fresh account/position
observations are separate facts. A cancel-all action must be explicitly wallet-scoped; per-domain
controllers must not erase another domain's orders accidentally. Historical-order decode failure
is retained as a failure, never coerced to canceled/zero. Existing profiles decide whether held
inventory is permitted; generic cleanup must not invent liquidation authority.

Evidence binds source/profile/plugin/terms versions, account/condition scope, observed and send
times, sequence, hashes and terminal completeness. Mutation intent must be durable before
sending; failure of evidence must still enter the authorized cleanup path. Paid reward verdicts
use complete paginated accrual and cash provenance, asset identity/finality/window completeness,
and explicit ambiguity. Neither modeled share nor an earnings balance proves payment or edge.

## Migration order and acceptance gates

Each row is a separately reviewable change. The implementation integrator must choose reviewed
branch ancestors and preserve history; this report does not merge R/S/E/D or adopt runtime code.
No migration is installed into a running RE1 checkout. Authorize a new source-bound attempt only
after the migrated exact tip is qualified; old journals and spent markers remain immutable.

| Step | Change | Required gate before the next step |
| --- | --- | --- |
| 0 | Pin adopted base, R/S/E/D dependencies and frozen profiles; record source/fixture identities | Run existing R and S regression groups on their exact qualification checkout after owner confirms no RE1. Record baseline failures instead of weakening assertions. Inventory transitive capture/taker users. |
| 1 | Add neutral contracts and plugin boundary; no active caller switch | Import-boundary tests prohibit core imports of weather registry/units/collection and plugin imports of credentials/venue mutation. Fictional second-domain fixtures fit without editing core. Existing entrypoints behave identically. |
| 2 | Extract score/price/held-observation kernels behind old import facades | Q/F/R/S differential fixtures preserve units, midpoint thresholds, duplicate depth, own-order subtraction, outward tick rounding and numeric tolerances. Retain old serializer/profile digests. Do not reactivate paper reward PnL. |
| 3 | Implement weather universe/value/information adapter around existing owners | Same selected identities and local dates, observed-high guards, release/captured-input checks and native-unit settlement. Clock tests distinguish scheduled, published and detected information and DST. Old CLIs still accept the same frozen schemas. |
| 4 | Consolidate public reads and SDK normalization, then account streams/heartbeat | V/L/S/R suites prove exact SDK shapes, bounded pagination, typed closed-order failure, account-wide fill scope, reconnect freshness, rotating heartbeat and watchdog budgets. No new mutation route enabled. |
| 5 | Consolidate mutation port with explicit frozen capabilities and compatibility entrypoints | Full RE1 single-post/signed-field/fresh-ask and cancel-race regression; Stage1/hold gates preserved. Lost ack never re-posts. Read-only/cancel-only cannot submit. Unknown orders do not get silently canceled by an unrelated scope. |
| 6 | Introduce one wallet reservation ledger and neutral policy controller, initially replay-only | Two-domain concurrent proposals cannot exceed any cap or reserve the same cash; ambiguous mutation/fill/cancel transitions stay charged. Crash/restart, partial second-leg failure, held inventory and emergency cleanup are exercised. Match RE1 frozen decisions. |
| 7 | Move shared journal/attempt primitives and reporting behind versioned facades | Replay existing synthetic frozen artifacts byte-for-byte where identity is contractual. Historical verdict and amended verdict remain distinct. E/D offline data defects never weaken live journal checks. No attempt recycling or unbound namespaces. |
| 8 | Switch qualified attended entrypoint to common core; retire duplicate live construction paths | Every RE1 regression remains green, full affected checks pass, exact-head review/CI and source/host/attendance authority are renewed. Maintain explicit historical replay profiles and compatibility imports for shared consumers. |
| 9 | Assess RE2/unattended readiness only after foundation adoption | Operator review of risk limits, evidence, fault drills and readiness/release gates. New domains/strategies and unattended operation require their own explicit authorization; architecture completion alone is insufficient. |

For **every** implementation branch, the production integrator obtains the verdict from
`scripts\ops\roll_verdict.ps1 -Branch <branch>` on production; this workstation does not infer
closure membership from filenames. Exit 1 is unresolved, not roll-free; exit 2 depends on the
specified dormant loop remaining down; exit 3 needs guarded quiet-window integration.
Use the [integration runbook](../operations/INTEGRATION_ATTEMPT_RUNBOOK.md) and guarded merge
path, preserving capture recovery checks. Moving a helper imported by policy/capture can change
fingerprints even if behavior is identical. A package move or schema change is not automatically
roll-free. The present report is Markdown only; its actual production merge verdict still belongs
to that tool. Push is source publication, not production adoption.

After each step, retain an isolated prior checkout for diagnosis rather than resetting published
history or changing a running session. A regression returns the branch to repair. Operational
rollback is a separately reviewed change/adoption, with old receipts intact.

## Regression net (specified, not run for 90a)

The following groups reference existing tests. Tests must run after explicit owner confirmation
that RE1 has ended and through the workstation heavy wrapper with a short `--basetemp`.
The capture host retains its separate admitted bounded-suite policy. This report records no
new pass counts and no runtime verification of proposed interfaces.

| Key | Existing regression files / families | Contract to preserve |
| --- | --- | --- |
| Q | `test_reward_quote.py`, `test_reward_share_estimate.py` | Size-qualified versus true touch; frozen size; cents/probability distinction; score boundaries and missing/invalid inputs. |
| F | `test_maker_incentive_feasibility.py`, `test_maker_opportunity_capture.py`, `test_maker_reward_simulation.py` | Decimal capital/scoring, public provenance and bounded scenario inputs. |
| R | All `test_re1_*.py` at R (listed below) | Session/requote/cancel/fill races; parity; scope/host/confirmation; durable attempt state; SDK/sign/post; read/watchdog budgets; complete payout lineage. |
| S | `test_mm_stage2_hold.py`, `test_mm_stage2_rehearsal.py`, `test_mm_stage2_rewards.py`, `test_mm_stage2_selection.py`, plus `stage2_fakes.py` | Hold-only behavior differs from RE1; pair authorization, heartbeat, two cancellation acknowledgments, fixed treatment and sealed lane. |
| L | All `test_mm_live_*.py`, `test_portable_live_candidate_preflight.py`, `test_mm_pilot_capital.py` | Plumbing/source/economics lineage, native account topology, action-time proofs, deadlines and cleanup. |
| V | `test_mm_exchange.py`, `test_mm_exchange_reports.py`, `test_mm_official_transport.py`, `test_mm_user_stream.py`, `test_mm_credentials.py`, `test_mm_credential_import_cli.py`, `test_mm_geographic_eligibility.py`, `test_mm_liquidity_earnings_evidence.py`, `test_mm_paid_credit_activity.py`, `test_mm_paid_incentive_reconciliation.py`, `test_exchange_economics.py`, `test_exchange_economics_sources.py`, `test_live_sdk_overlay.py`, `test_live_sdk_portability.py`, `test_polymarket_sdk_contract.py` | Official adapter coverage is in exchange and lifecycle suites, not an assumed same-named adapter test. Preserve no-secret, no-read-as-mutation, pagination and native-asset facts. |
| P | All `test_market_making_*.py`; `test_mm_policy.py`, `test_mm_risk.py`, `test_mm_paper.py`, `test_mm_paper_scoring.py`, `test_mm_scoring_projection.py`, `test_mm_countability_postmortem.py`, `test_mm_input_age_postmortem.py` | Weather paper outputs, ledger reservations, projections, eligibility/countability, simulated fills and zero unverified reward PnL. |
| W | `test_info_event_calendar.py`, `test_worker_release_binding.py`, `test_worker_release_binding_streaming.py`, plus shared universe/input tests in the caller index | Weather clock, native units, probability mass, observed-high/revision and captured-input release binding. Preserve downstream model/taker suites when these owners change. |
| C | `test_market_microstructure.py`, `test_market_microstructure_features.py`, `test_execution_tape_capture.py`, `test_execution_tape_markout.py`, `test_order_book_tape.py`; affected operations supervision tests | Public capture identity, ordered tapes/gaps, bounded IO and provenance; no live capture run needed for deterministic unit qualification. |
| E | E `test_maker_evidence_capture.py` | Public evidence budgets, storage, scope and stopped/closed segments. |
| D | D `test_fill_toxicity_desk_study.py` plus Q/C | Frozen panels and selection/coverage; undecodable capture intervals use event-day boundaries for missing neighbors; strict settlement failures and union gap exclusion preserved. |

R files: `test_re1_addendum.py`, `test_re1_attended.py`, `test_re1_attended_parity_audit.py`,
`test_re1_evidence.py`, `test_re1_owner_checks.py`, `test_re1_payout_evidence.py`,
`test_re1_resilience.py`, `test_re1_sdk_shapes.py`, `test_re1_sizing.py`, `test_re1_transport.py`.

The boundary net also includes `test_stage2_handoff_constraints.py`,
`tests/operations/test_stage2_child_evidence.py`, `tests/operations/test_stage2_session_sealing.py`,
and the affected `tests/operations/test_international_live_*.py` launcher/sealer/runner tests.
Preserve `tests/operations/test_import_architecture.py` when moving owners; source tree moves must not
break package or non-maker consumers. These are qualification requirements, not executed checks.

Particularly important existing counterexamples:

- R `test_re1_attended.py:244,303`: fill racing cancel cannot re-enter; lost submit acknowledgment
  checks inventory and marks evidence incomplete.
- R `test_re1_transport.py:173,199,331`: corrupt signed fields refuse, ask moving after signing
  refuses, and the post-signing book is retained before post.
- R `test_re1_resilience.py:80,94,158`: REST fill detector during stream outage, independent
  watchdog during a stalled main loop, and unreadable historical order without invented empty-account proof.
- R `test_re1_attended_parity_audit.py:62,90,171`: corrected selection/minute midpoint and old
  own-depth subtraction counterexamples. Similar function names do not imply equivalent scoring.
- R `test_re1_sizing.py:122,155,162`: sealed proposer cannot widen, wallet drop stops submission,
  and exact reserve/size ceilings remain binding.
- R `test_re1_payout_evidence.py:289,406,479,531`: terminal pagination, ambiguous duplicate credits,
  incomplete empty reads and query-start cash-window boundaries cannot be converted to paid/not-paid proof.
- R `test_mm_stage2_hold.py:104,114,144`: failed explicit cancel is still no-go, terminal state
  does not substitute for both acknowledgments, and hold-mode drift cancels without requoting.

New tests required by the proposed architecture are behavioral: second-domain contract fixtures;
cross-domain simultaneous cash reservation; event/domain/global caps; uncertain-post persistence;
partial-fill/replacement accounting; arbitrary event identities and DST; safety pull versus
favorable flicker; cooldown/requote exhaustion; terms changes; cold restart before/after post;
and inability of research/plugin/read-only objects to acquire mutation capability. Do not write
tests that merely assert the new directory layout or mirror implementation functions.

## Risks, owner decisions and review checklist

No question below blocks this report. Before an implementation handoff, the owner/integration
agent must fix: (1) the adopted dependency order and qualification tip; (2) initial market/event/
domain/wallet caps and held-inventory treatment; (3) whether any future profile may operate with
unavailable fair value and what information pulls remain mandatory; (4) cross-domain emergency
cancel scope and recovery authority; (5) evidence retention and the exact criteria for RE2 or
unattended evaluation. Numerical thresholds are not supplied by architectural convenience.

Main risks are source-bound profile drift, confusing public/inferred fills with our executions,
silent numeric-unit changes, shared-wallet double reservation, closed-order read ambiguity,
unreviewed historical verdict changes, and production fingerprint roll caused by transitive imports.
Separate source timestamps from detection delay to avoid look-ahead in research. Do not use the
frozen workstation mirror as evidence of current production data. An observed candidate or green
suite does not prove economic edge, payout, current exchange behavior or permission to trade.

Every new maker handoff/review should answer:

- Is this responsibility domain-neutral, or explicitly behind a universe/value/information/exposure
  plugin? Can a fictional non-weather event use the core without new city/station/band branches?
- Does venue logic have one owner, including closed-order quirks, pagination, stream scoping and
  heartbeat? Are public, authenticated read, cancel-only and submit capabilities distinct?
- Are amounts/assets/ticks/native units/time semantics explicit? Are source freshness, release
  identity and unavailable values preserved rather than coerced to zero or defaults?
- Is there one wallet ledger with atomic multi-leg reservations and market/event/domain/global
  caps? Are pending/unknown submissions and filled inventory still counted?
- Does re-quoting preserve immediate safety pulls, exact post-signing touch checks, bounded
  budgets, no blind submit retry and explicit cleanup/reconciliation evidence?
- Can old RE1 and sealed hold fixtures replay with their original profiles and verdicts? Are schema,
  journal, attempt and source identities unchanged unless a separately versioned contract says otherwise?
- Do weather observed-high, WU cutoff, native settlement and model release invariants remain behind
  the plugin? Does research tolerance stay out of live safety evidence?
- Are the exact dependency base, affected regression suites and production tool roll verdict recorded?
  Is runtime adoption separately authorized, with no change to an active RE1 checkout?

## Verification and handback

Verification for this report is source inspection, cached-commit comparison and Markdown diff
review only. Tests and all heavy/network-heavy work remain paused pending explicit owner
confirmation that session 5 ended. No code, schema, config, scheduler or runtime state changed.
No canonical item/backlog/index was changed; this is the requested dated correspondence.

89c was already pushed at `d3dff0f2b1783741e2c4927cf74e8032bd17b02b`. The separate 91a
draft was pushed at `07cc2987f4c292415d5035ba866afdf648d79387`; its testing and qualification
remain unfinished. Completion of this source-analysis report must not be read as completion of 91a.

The report branch is documentation-only and requires no implementation test to substantiate its
claims. The eventual production adoption verdict belongs to the guarded production tools. The
current live session, campaign evidence and worker states were neither inspected nor changed.

Per-file roll assessment: the only changed file is
`docs/roadmap/agent-report-2026-09-90a-market-maker-architecture-map.md`; Markdown is roll-free
under the delegation contract, with no Python closure member changed. No retained production
closure was accessed and no production tool verdict was run here. The production agent must
record its actual tool verdict before adoption. No schema registration changed. No registration,
production write, restart, merge, capture run, candidate generation or model fitting occurred.
There are no measured economic samples or intervals in this design report.

Reproduce the source comparison from a repository checkout that has the pinned objects
(all commands below are Git reads; no runtime data paths are needed):

```powershell
git show 7014b637e228228fab763a7febea82c8852b6809:docs/roadmap/workstation-handoff-2026-09-90a-market-maker-architecture-map.md
git ls-tree -r --name-only 51975cfccec806054a20267a1576ee92fc93796f src/weather/market tests/market
git diff 88aa7e43a71d5870575261280b45c9deae667668 51975cfccec806054a20267a1576ee92fc93796f -- src/weather/market/mm_stage2_selection.py src/weather/market/reward_quote.py
git show 51975cfccec806054a20267a1576ee92fc93796f:src/weather/market/re1_transport.py
git show 7953d26081f8e135be52760e24f3e5554693def9:src/weather/market/maker_evidence_capture.py
git show d3dff0f2b1783741e2c4927cf74e8032bd17b02b:src/weather/market/fill_toxicity_inputs.py
git grep -n -E 'weather[.]market' 51975cfccec806054a20267a1576ee92fc93796f -- 'src/**/*.py' 'app/**/*.py' 'tests/**/*.py'
```

The branch publication tip is supplied in the handback; the pinned source commits above define
the analysis independently of later branch movement. Missing cached objects require an authorized
fetch after any applicable workload restriction, not substitution with local runtime evidence.

## Static named-reference caller and test index

Supplement to the semantic map: qualified `weather.market.<module>` references in tracked Python source/app/tests at R, plus references originating in E maker-evidence and D desk-study additions. Names below are repository-relative without `.py`; market source names omit `src/weather/market/`. This bounded textual index includes test monkeypatch targets and import references, not only invocations; it excludes dynamic/parent-import aliases and does not prove test coverage. A dash means no such reference found, not no consumer. CLI and indirect consumers are in the semantic map. No Python code was executed.

| Ref / module | Source/app named references | Test named references |
| --- | --- | --- |
| R `clob_recon.py` | `mm_paper`, `mm_policy`, `src/weather/schema_registry_data` | `tests/market/test_clob_recon`, `tests/market/test_quote_evidence_age` |
| R `exchange_economics.py` | `maker_opportunity_capture`, `mm_live_candidate_cli`, `portable_live_candidate_preflight`, `src/weather/reporting/market/maker_opportunity_report`, `src/weather/reporting/market/operator_control_room`, `src/weather/schema_registry_data` | `tests/market/test_maker_opportunity_capture`, `tests/market/test_mm_live_candidate_cli`, `tests/operations/test_location_config_generation` |
| R `exchange_economics_run_capture.py` | `exchange_economics` | — |
| R `exchange_economics_sources.py` | `exchange_economics`, `maker_opportunity_capture`, `maker_opportunity_inputs`, `mm_liquidity_earnings_evidence`, `mm_stage2_rewards`, `mm_stage2_selection` | `tests/market/test_maker_opportunity_capture`, `tests/market/test_mm_liquidity_earnings_evidence` |
| R `execution_tape_capture.py` | `execution_tape_store`, `src/weather/operations/execution_tape_supervisor` | `tests/market/test_execution_tape_capture`, `tests/operations/test_execution_tape_supervisor`, `tests/operations/test_location_config_generation` |
| R `execution_tape_markout.py` | — | — |
| R `execution_tape_store.py` | `execution_tape_capture`, `src/weather/operations/execution_tape_supervisor`, `src/weather/schema_registry_recent_data` | `tests/market/test_execution_tape_capture`, `tests/operations/test_execution_tape_supervisor` |
| R `info_event_calendar.py` | `market_making_run`, `mm_paper`, `mm_policy`, `src/weather/schema_registry_data` | `tests/market/test_info_event_calendar` |
| R `live_forward_gate.py` | `market_making_run`, `src/weather/schema_registry_data` | `tests/market/test_market_making_run`, `tests/market/test_mm_paper` |
| R `live_observation_normalization.py` | `market_making_run`, `market_making_run_support`, `mm_policy`, `src/weather/operations/observation_trigger`, `taker_bot_strategy_registry` | `tests/operations/test_observation_trigger` |
| R `live_sdk_overlay.py` | `mm_credential_import_cli`, `mm_live_pilot_cli`, `re1_evidence`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | `tests/market/test_polymarket_sdk_contract` |
| R `live_sdk_portability.py` | `src/weather/schema_registry_data` | `tests/operations/test_portable_live_sdk_script` |
| R `location_config.py` | `mm_live_stage0_scope`, `src/weather/operations/config_inventory`, `src/weather/operations/event_metadata_validation`, `src/weather/operations/location_config_refresh`, `src/weather/operations/release_candidate_contract`, `src/weather/release_artifacts`, `src/weather/reporting/source_gates/source_family_inventory`, `src/weather/schema_registry_data` | `tests/market/test_location_config`, `tests/market/test_mm_live_stage0_scope`, `tests/market/test_mm_live_stage1_lifecycle_plan`, `tests/operations/test_location_config_generation` |
| R `maker_incentive_feasibility.py` | `maker_reward_simulation`, `reward_share_estimate`, `src/weather/reporting/market/maker_opportunity_report` | `tests/market/test_maker_incentive_feasibility`, `tests/market/test_reward_share_estimate` |
| R `maker_opportunity_capture.py` | `app/views/liquidity_simulator`, `maker_opportunity_inputs`, `src/weather/reporting/market/maker_opportunity_report`, `src/weather/schema_registry_recent_data` | `tests/market/test_maker_opportunity_capture`, `tests/market/test_maker_reward_simulation` |
| R `maker_opportunity_inputs.py` | `maker_reward_simulation`, `src/weather/reporting/market/maker_opportunity_report` | `tests/market/test_maker_opportunity_capture` |
| R `maker_reward_simulation.py` | `app/views/liquidity_simulator`, `src/weather/schema_registry_recent_data` | `tests/market/test_maker_reward_simulation` |
| R `market_config.py` | `clob_recon`, `exchange_economics`, `execution_tape_capture`, `info_event_calendar`, `maker_evidence_capture`, `maker_incentive_feasibility`, `maker_opportunity_capture`, `market_making_preflight`, `market_making_run`, `market_making_run_support`, `market_microstructure`, `market_microstructure_capture`, `mm_live_bootstrap`, `mm_live_candidate_cli`, `mm_live_pilot_cli`, `mm_live_stage0_scope`, `mm_live_stage1_lifecycle_plan`, `mm_stage2_selection`, `polymarket_client`, `portable_live_candidate_preflight`, `reward_share_estimate`, `src/weather/backtesting/backtest`, `src/weather/backtesting/replay`, `src/weather/backtesting/replay_ablation`, `src/weather/backtesting/replay_backtest`, `src/weather/backtesting/settled_days`, `src/weather/backtesting/settlement_io`, `src/weather/backtesting/settlement_ledger`, `src/weather/backtesting/tape_scoring`, `src/weather/calibration/afternoon_residual_centering`, `src/weather/calibration/family_secondary_artifacts`, `src/weather/calibration/forecast_error_model`, `src/weather/calibration/model_ensemble`, `src/weather/calibration/probability_calibration`, `src/weather/calibration/settlement_lag_model`, `src/weather/collection/collection_health`, `src/weather/collection/forecast_archive`, `src/weather/collection/forecast_tracker`, `src/weather/collection/snapshot_store`, `src/weather/collection/snapshot_tracker`, `src/weather/model/model_constants`, `src/weather/model/toronto_model`, `src/weather/operations/closed_day_projection_tiering`, `src/weather/operations/closed_market_day_archive`, `src/weather/operations/daily_refresh_reporting_steps`, `src/weather/operations/event_day_archive_coverage`, `src/weather/operations/event_day_manifest`, `src/weather/operations/event_metadata_validation`, `src/weather/operations/observation_trigger`, `src/weather/operations/release_admissibility_clock`, `src/weather/operations/release_candidate_contract`, `src/weather/operations/replay_status_backfill`, `src/weather/operations/settled_day_freshness`, `src/weather/operations/verified_cold_archive`, `src/weather/reporting/candidate_lifecycle/model_market_disagreement_audit`, `src/weather/reporting/candidate_lifecycle/price_free_model_learning`, `src/weather/reporting/casebooks/disagreement_casebook`, `src/weather/reporting/data_quality/data_auditor`, `src/weather/reporting/data_quality/data_layer_audit_collectors`, `src/weather/reporting/data_quality/feature_quality_quarantine`, `src/weather/reporting/hourly/hourly_model_scoring`, `src/weather/reporting/location_analysis/location_trust`, `src/weather/reporting/promotion/promotion_corpus`, `src/weather/reporting/research/blind_feature_repair`, `src/weather/reporting/scorecards/captured_input_parity_evidence`, `src/weather/reporting/scorecards/inactive_release_forward_shadow`, `src/weather/reporting/scorecards/model_history`, `src/weather/reporting/scorecards/winner_rank_parity`, `src/weather/reporting/serving_gates/model_scoring_liveness`, `src/weather/reporting/serving_gates/runtime_identity_evidence`, `src/weather/reporting/source_gates/source_redundancy`, `src/weather/reporting/validation/point_in_time_evaluation`, `taker_bot_strategy_registry`, `worker_release_binding` | `tests/collection/test_collection_robustness`, `tests/market/test_execution_tape_capture`, `tests/market/test_market_config`, `tests/market/test_market_making_run`, `tests/market/test_market_microstructure`, `tests/market/test_mm_live_stage1_lifecycle_plan`, `tests/market/test_worker_release_binding`, `tests/operations/test_closed_day_projection_tiering`, `tests/operations/test_daily_refresh`, `tests/operations/test_international_live_session_runner`, `tests/operations/test_location_config_generation`, `tests/operations/test_settled_day_freshness`, `tests/reporting/test_captured_input_parity_evidence` |
| R `market_day_labels.py` | `src/weather/operations/daily_refresh`, `src/weather/operations/daily_refresh_reporting_steps`, `src/weather/operations/daily_refresh_source_steps`, `src/weather/operations/daily_refresh_trading_steps` | `tests/market/test_market_day_labels` |
| R `market_latest_inputs.py` | `taker_bot_cli` | `tests/market/test_market_latest_inputs` |
| R `market_making_evidence.py` | `market_making_readiness`, `market_making_run`, `src/weather/operations/market_making_daily_roll`, `src/weather/operations/market_making_preflight_recovery`, `src/weather/reporting/market/mm_input_age_postmortem` | `tests/market/test_market_making_evidence`, `tests/market/test_market_making_run` |
| R `market_making_live_pilot.py` | `market_making_run` | `tests/market/test_market_making_live_pilot` |
| R `market_making_model_variants.py` | `market_making_run`, `src/weather/schema_registry_data` | `tests/market/test_market_making_run` |
| R `market_making_preflight.py` | `exchange_economics`, `live_forward_gate`, `market_making_readiness`, `market_making_run`, `mm_credential_import_cli`, `mm_credentials`, `mm_live_bootstrap`, `mm_live_pilot_cli`, `src/weather/reporting/fleet/fleet_observability_inventory`, `src/weather/schema_registry_data` | `tests/market/test_market_making_readiness`, `tests/market/test_market_making_run` |
| R `market_making_readiness.py` | `mm_paper`, `mm_paper_reports`, `src/weather/schema_registry_recent_data` | `tests/market/test_market_making_readiness` |
| R `market_making_run.py` | `src/weather/operations/market_making_daily_roll`, `src/weather/operations/market_making_preflight_recovery`, `src/weather/schema_registry_data` | `tests/market/test_market_making_run`, `tests/market/test_worker_release_binding`, `tests/operations/test_market_making_daily_roll` |
| R `market_making_run_constants.py` | `market_making_live_pilot`, `market_making_preflight`, `market_making_readiness`, `market_making_run`, `market_making_run_support`, `mm_exchange`, `mm_live_bootstrap`, `mm_live_lifecycle_probe`, `mm_live_pilot_cli`, `mm_official_adapter`, `mm_pilot_capital`, `mm_scoring_projection`, `src/weather/operations/market_making_daily_roll`, `src/weather/operations/market_making_tape_encoding`, `src/weather/reporting/market/operator_control_room` | `tests/market/test_market_making_readiness`, `tests/market/test_mm_live_envelope`, `tests/market/test_mm_paper`, `tests/operations/test_path_policy` |
| R `market_making_run_support.py` | `market_making_readiness`, `market_making_run`, `portable_live_candidate_preflight`, `src/weather/operations/market_making_preflight_recovery`, `src/weather/schema_registry_data`, `taker_bot_strategy_registry` | `tests/market/test_market_making_csv_encoding`, `tests/market/test_market_making_run`, `tests/market/test_mm_exchange`, `tests/market/test_quote_evidence_age` |
| R `market_microstructure.py` | `market_making_preflight`, `market_making_run`, `market_making_run_support`, `src/weather/operations/capture_recovery_check`, `src/weather/operations/loop_jsonl_repair`, `src/weather/operations/market_making_preflight_recovery`, `src/weather/operations/ops_monitor`, `src/weather/reporting/daily/daily_flow_analysis`, `src/weather/reporting/data_quality/data_layer_audit`, `src/weather/reporting/fleet/fleet_observability_inventory`, `src/weather/reporting/market/trading_evidence`, `src/weather/schema_registry_data`, `taker_bot_cli`, `taker_evidence_starvation` | `tests/market/test_market_making_run`, `tests/market/test_market_microstructure`, `tests/operations/test_nightly_retrain`, `tests/operations/test_taker_bot_daily_roll`, `tests/reporting/test_fleet_observability` |
| R `market_microstructure_capture.py` | `market_microstructure`, `mm_live_candidate_cli`, `mm_live_stage0_scope`, `mm_live_stage1_lifecycle_plan`, `order_book_tape`, `src/weather/operations/closed_day_projection_registry`, `src/weather/operations/closed_day_projection_tiering`, `src/weather/schema_registry_data` | `tests/market/test_market_microstructure`, `tests/market/test_order_book_tape`, `tests/operations/test_closed_day_projection_tiering` |
| R `market_microstructure_constants.py` | `execution_tape_capture`, `maker_evidence_socket`, `market_microstructure`, `market_microstructure_capture`, `mm_user_stream`, `order_book_tape`, `src/weather/operations/closed_day_projection_tiering` | `tests/market/test_order_book_tape`, `tests/operations/test_closed_day_projection_tiering` |
| R `market_microstructure_features.py` | `live_observation_normalization`, `market_latest_inputs`, `market_making_model_variants`, `market_making_preflight`, `market_making_run`, `market_making_run_support`, `market_microstructure`, `market_microstructure_capture`, `mm_policy`, `src/weather/calibration/pooled_candidate_replay`, `src/weather/calibration/pooled_candidate_replay_diagnostics`, `src/weather/calibration/pooled_feature_assembly`, `src/weather/model/variant_prediction_runtime`, `src/weather/reporting/data_quality/data_layer_audit_collectors`, `src/weather/reporting/market/trading_evidence`, `src/weather/reporting/research/reanalysis_synoptic_band_ablation`, `src/weather/reporting/source_gates/source_family_inventory`, `taker_bot_strategy_registry`, `worker_release_binding` | `tests/calibration/test_pooled_feature_model`, `tests/market/test_market_latest_inputs`, `tests/market/test_market_microstructure`, `tests/market/test_market_microstructure_features`, `tests/reporting/test_source_family_inventory` |
| R `market_registry.py` | `exchange_economics`, `execution_tape_capture`, `execution_tape_markout`, `fill_toxicity_desk_study`, `info_event_calendar`, `maker_evidence_capture`, `maker_incentive_feasibility`, `maker_opportunity_capture`, `market_config`, `market_making_run`, `market_making_run_support`, `market_microstructure`, `market_microstructure_capture`, `market_microstructure_features`, `mm_live_candidate_cli`, `mm_live_pilot_cli`, `mm_live_stage0_scope`, `mm_live_stage1_lifecycle_plan`, `mm_policy`, `mm_stage2_selection`, `polymarket_client`, `src/weather/backtesting/backtest`, `src/weather/backtesting/replay`, `src/weather/backtesting/replay_ablation`, `src/weather/backtesting/replay_backtest`, `src/weather/backtesting/settled_days`, `src/weather/backtesting/settlement_io`, `src/weather/backtesting/settlement_ledger`, `src/weather/calibration/afternoon_residual_centering`, `src/weather/calibration/base_model_candidate`, `src/weather/calibration/family_secondary_artifacts`, `src/weather/calibration/feature_training_policy`, `src/weather/calibration/forecast_error_model`, `src/weather/calibration/forecast_training_contract`, `src/weather/calibration/model_ensemble`, `src/weather/calibration/pooled_candidate_replay`, `src/weather/calibration/pooled_candidate_replay_diagnostics`, `src/weather/calibration/pooled_feature_assembly`, `src/weather/calibration/probability_calibration`, `src/weather/calibration/residual_distribution_corpus`, `src/weather/calibration/settlement_lag_model`, `src/weather/collection/collection_health`, `src/weather/collection/data_ingestion`, `src/weather/collection/forecast_payload_cas`, `src/weather/collection/forecast_tracker`, `src/weather/collection/historical_backfill_plan`, `src/weather/collection/live_variant_predictions`, `src/weather/collection/snapshot_tracker`, `src/weather/model/residual_distribution_v1`, `src/weather/model/toronto_model`, `src/weather/model/variant_prediction_runtime`, `src/weather/operations/all_shadow_release_bootstrap`, `src/weather/operations/base_retrain`, `src/weather/operations/config_inventory`, `src/weather/operations/daily_refresh`, `src/weather/operations/daily_refresh_reporting_steps`, `src/weather/operations/daily_refresh_source_steps`, `src/weather/operations/daily_refresh_trading_steps`, `src/weather/operations/density_live_replay_parity`, `src/weather/operations/event_metadata_validation`, `src/weather/operations/international_live_session_launcher_sealer`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/operations/observation_trigger`, `src/weather/operations/point_in_time_staging_receipt`, `src/weather/operations/release_admissibility_clock`, `src/weather/operations/release_candidate_contract`, `src/weather/operations/settled_day_freshness`, `src/weather/reporting/candidate_lifecycle/model_market_disagreement_audit`, `src/weather/reporting/candidate_lifecycle/price_free_model_learning`, `src/weather/reporting/casebooks/disagreement_casebook`, `src/weather/reporting/casebooks/severe_tail_ex_ante`, `src/weather/reporting/data_quality/data_auditor`, `src/weather/reporting/data_quality/data_layer_audit`, `src/weather/reporting/data_quality/data_layer_audit_collectors`, `src/weather/reporting/data_quality/feature_quality_quarantine`, `src/weather/reporting/fleet/fleet_observability_inventory`, `src/weather/reporting/hourly/hourly_model_scoring`, `src/weather/reporting/location_analysis/location_trust`, `src/weather/reporting/market/maker_opportunity_report`, `src/weather/reporting/promotion/promotion_corpus`, `src/weather/reporting/promotion/promotion_gauntlet`, `src/weather/reporting/promotion/readers`, `src/weather/reporting/research/blind_feature_repair`, `src/weather/reporting/research/item186_soil_antecedent_settlement_gate`, `src/weather/reporting/research/profit_edge_analysis`, `src/weather/reporting/research/reanalysis_synoptic_band_ablation`, `src/weather/reporting/research/skill_gap_decomposition`, `src/weather/reporting/scorecards/model_history`, `src/weather/reporting/scorecards/train_serve_feature_parity`, `src/weather/reporting/scorecards/winner_rank_parity`, `src/weather/reporting/source_gates/forecast_smoke_slice_prep`, `src/weather/reporting/source_gates/nbm_probabilistic_tmax_settlement_scoring`, `src/weather/reporting/source_gates/source_family_inventory`, `src/weather/reporting/source_gates/source_redundancy`, `src/weather/schema_registry_data`, `src/weather/sources/canonical_history_guardrails`, `src/weather/sources/forecast_history`, `src/weather/sources/forecast_training_corpus`, `src/weather/sources/historical_coverage`, `src/weather/sources/marine_water_contrast`, `src/weather/sources/metar_history`, `src/weather/sources/noaa_ghcnh_history`, `src/weather/sources/official_guidance_collection`, `src/weather/sources/open_meteo_archives`, `src/weather/sources/reanalysis_history`, `src/weather/sources/reanalysis_synoptic`, `src/weather/sources/supplemental_station_validation`, `src/weather/sources/wu_history`, `taker_bot_strategy_registry`, `taker_edge_permission` | `tests/backtesting/test_replay_ablation`, `tests/backtesting/test_settlement_ledger`, `tests/calibration/test_base_model_candidate`, `tests/calibration/test_forecast_error_model`, `tests/calibration/test_lock_blocker_end_to_end`, `tests/calibration/test_pooled_candidate_replay`, `tests/calibration/test_pooled_candidate_replay_streaming`, `tests/calibration/test_pooled_feature_model`, `tests/calibration/test_pooled_feature_preselection_exclusion`, `tests/collection/test_collection_robustness`, `tests/market/test_fill_toxicity_desk_study`, `tests/market/test_market_config`, `tests/market/test_market_making_run`, `tests/market/test_mm_stage2_selection`, `tests/market/test_re1_attended`, `tests/market/test_re1_attended_parity_audit`, `tests/market/test_re1_sizing`, `tests/model/test_continuous_density`, `tests/model/test_current_blend`, `tests/model/test_feature_model_ablation`, `tests/operations/test_base_retrain`, `tests/operations/test_nightly_retrain`, `tests/operations/test_settlement_backfill_scripts`, `tests/operations/test_structure_inventory`, `tests/reporting/test_fleet_observability`, `tests/reporting/test_source_family_inventory`, `tests/reporting/test_train_serve_feature_parity`, `tests/sources/test_asos_one_minute`, `tests/sources/test_eccc_gridded`, `tests/sources/test_forecast_training_variants`, `tests/sources/test_historical_fallbacks`, `tests/sources/test_historical_sources`, `tests/sources/test_marine_context`, `tests/sources/test_marine_water_contrast`, `tests/sources/test_metar_cutoff_miss`, `tests/sources/test_metar_history`, `tests/sources/test_mrms_precip`, `tests/sources/test_official_guidance_collection`, `tests/sources/test_open_meteo_archives`, `tests/sources/test_reanalysis_synoptic` |
| R `mm_credential_import_cli.py` | `src/weather/schema_registry_data` | — |
| R `mm_credentials.py` | `mm_credential_import_cli`, `mm_live_bootstrap`, `mm_live_candidate_cli`, `mm_live_pilot_cli`, `mm_live_stage0_scope`, `mm_live_stage1_lifecycle_plan`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | `tests/market/test_mm_credentials`, `tests/market/test_mm_live_pilot_cli`, `tests/operations/test_international_live_session_launcher_sealer` |
| R `mm_exchange.py` | `mm_credentials`, `mm_live_pilot_cli`, `src/weather/schema_registry_data` | `tests/market/test_mm_exchange` |
| R `mm_exchange_reports.py` | `mm_exchange`, `mm_stage2_rewards`, `re1_payout_evidence`, `src/weather/reporting/market/operator_trading`, `src/weather/schema_registry_data` | `tests/market/test_mm_exchange`, `tests/market/test_re1_payout_evidence`, `tests/market/test_re1_sdk_shapes`, `tests/reporting/test_operator_monitor` |
| R `mm_geographic_eligibility.py` | `mm_live_attendance`, `mm_live_bootstrap`, `mm_live_lifecycle_probe`, `mm_live_pilot_cli`, `mm_stage2_hold`, `mm_stage2_rehearsal`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | `tests/market/stage2_fakes` |
| R `mm_liquidity_earnings_evidence.py` | `mm_stage2_rewards`, `src/weather/schema_registry_data` | — |
| R `mm_live_attendance.py` | `mm_stage2_entrypoint` | `tests/market/test_mm_live_attendance`, `tests/operations/test_stage2_child_evidence` |
| R `mm_live_bootstrap.py` | `mm_live_pilot_cli`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | `tests/market/test_mm_live_bootstrap`, `tests/operations/test_international_live_session_runner` |
| R `mm_live_candidate_cli.py` | `portable_live_candidate_preflight`, `src/weather/schema_registry_data` | — |
| R `mm_live_envelope.py` | `market_making_live_pilot`, `mm_live_candidate_cli`, `mm_live_pilot_cli`, `mm_official_adapter`, `mm_policy`, `mm_stage2_entrypoint`, `mm_stage2_hold`, `mm_stage2_rehearsal`, `mm_stage2_rewards`, `mm_stage2_user_stream`, `src/weather/operations/international_live_session_launcher_sealer`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | `tests/market/stage2_fakes`, `tests/market/test_mm_live_envelope`, `tests/market/test_mm_stage2_hold`, `tests/market/test_mm_stage2_rewards`, `tests/operations/test_stage2_child_evidence`, `tests/operations/test_stage2_session_sealing` |
| R `mm_live_lifecycle_probe.py` | `mm_live_pilot_cli`, `mm_stage2_hold`, `mm_stage2_rehearsal`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | `tests/market/test_mm_live_lifecycle_probe`, `tests/market/test_mm_live_pilot_cli`, `tests/operations/test_international_live_session_runner` |
| R `mm_live_pilot_cli.py` | `src/weather/schema_registry_data` | — |
| R `mm_live_stage0_scope.py` | `mm_live_pilot_cli`, `mm_live_stage1_lifecycle_plan`, `src/weather/operations/international_live_session_launcher_sealer`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | — |
| R `mm_live_stage1_lifecycle_plan.py` | `mm_live_pilot_cli`, `src/weather/operations/international_live_session_launcher_sealer`, `src/weather/operations/international_live_wrapper_sealer`, `src/weather/schema_registry_data` | — |
| R `mm_official_adapter.py` | `market_making_preflight`, `mm_credentials`, `mm_exchange_reports`, `mm_live_bootstrap`, `mm_live_lifecycle_probe`, `mm_live_pilot_cli`, `mm_paid_credit_activity`, `mm_stage2_entrypoint`, `mm_stage2_hold`, `mm_stage2_user_stream`, `mm_user_stream`, `re1_attended`, `re1_payout_evidence`, `re1_transport` | `tests/market/stage2_fakes`, `tests/market/test_mm_exchange`, `tests/market/test_mm_live_envelope`, `tests/market/test_mm_stage2_rewards`, `tests/market/test_re1_sdk_shapes`, `tests/operations/test_stage2_child_evidence` |
| R `mm_official_transport.py` | `mm_credentials`, `mm_live_pilot_cli`, `mm_live_stage1_lifecycle_plan`, `re1_transport` | `tests/market/test_mm_official_transport`, `tests/market/test_polymarket_sdk_contract` |
| R `mm_paid_credit_activity.py` | — | `tests/market/test_mm_paid_credit_activity` |
| R `mm_paper.py` | `mm_scoring_projection`, `src/weather/schema_registry_data`, `src/weather/schema_registry_recent_data` | `tests/market/test_mm_paper` |
| R `mm_paper_aggregation.py` | `mm_paper` | — |
| R `mm_paper_constants.py` | `mm_paper`, `mm_paper_reports`, `mm_paper_scoring` | — |
| R `mm_paper_evidence.py` | `mm_paper`, `mm_paper_scoring` | — |
| R `mm_paper_reports.py` | `mm_paper` | — |
| R `mm_paper_scoring.py` | `mm_paper`, `mm_paper_aggregation`, `src/weather/schema_registry_data`, `src/weather/schema_registry_recent_data` | `tests/market/test_mm_paper`, `tests/market/test_mm_paper_scoring`, `tests/market/test_mm_scoring_projection`, `tests/market/test_native_band_scoring` |
| R `mm_pilot_capital.py` | `mm_credentials`, `mm_live_bootstrap`, `mm_live_lifecycle_probe`, `mm_live_pilot_cli`, `mm_official_adapter`, `mm_stage2_hold`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer` | `tests/market/test_mm_pilot_capital`, `tests/market/test_stage2_handoff_constraints` |
| R `mm_policy.py` | `exchange_economics`, `live_forward_gate`, `market_making_live_pilot`, `market_making_model_variants`, `market_making_preflight`, `market_making_readiness`, `market_making_run`, `market_making_run_constants`, `market_making_run_support`, `mm_exchange`, `mm_exchange_reports`, `mm_live_bootstrap`, `mm_live_candidate_cli`, `mm_live_stage0_scope`, `mm_live_stage1_lifecycle_plan`, `mm_official_adapter`, `mm_paper`, `mm_paper_evidence`, `mm_paper_reports`, `mm_paper_scoring`, `portable_live_candidate_preflight`, `src/weather/operations/market_making_preflight_recovery`, `src/weather/reporting/market/mm_input_age_postmortem`, `src/weather/schema_registry_data`, `src/weather/schema_registry_recent_data`, `taker_bot_strategy_registry` | `tests/market/test_market_making_live_pilot`, `tests/market/test_mm_live_envelope`, `tests/market/test_mm_policy`, `tests/market/test_quote_evidence_age` |
| R `mm_risk.py` | `mm_policy`, `src/weather/schema_registry_data`, `taker_bot_sizing` | `tests/market/test_mm_risk` |
| R `mm_scoring_projection.py` | `market_making_run`, `mm_paper_scoring`, `src/weather/operations/daily_refresh_trading_steps`, `src/weather/operations/market_making_daily_roll`, `src/weather/schema_registry_recent_data` | `tests/market/test_mm_paper`, `tests/market/test_mm_scoring_projection`, `tests/operations/test_daily_refresh`, `tests/operations/test_market_making_daily_roll` |
| R `mm_stage2_entrypoint.py` | `src/weather/operations/international_live_session_runner` | `tests/market/test_mm_stage2_rewards` |
| R `mm_stage2_hold.py` | `mm_stage2_entrypoint`, `mm_stage2_rehearsal`, `mm_stage2_rewards`, `mm_stage2_selection`, `re1_attended`, `re1_attended_cli`, `re1_evidence`, `re1_owner_checks`, `re1_payout_evidence`, `re1_resilience`, `src/weather/operations/international_live_session_launcher_sealer`, `src/weather/operations/international_live_session_runner`, `src/weather/schema_registry_data` | `tests/market/test_mm_live_attendance`, `tests/market/test_mm_stage2_hold`, `tests/market/test_mm_stage2_rehearsal`, `tests/market/test_mm_stage2_rewards`, `tests/market/test_mm_stage2_selection`, `tests/market/test_re1_attended_parity_audit`, `tests/market/test_re1_evidence`, `tests/market/test_re1_payout_evidence`, `tests/market/test_re1_resilience`, `tests/market/test_re1_sdk_shapes`, `tests/market/test_re1_sizing`, `tests/operations/test_stage2_child_evidence`, `tests/operations/test_stage2_session_sealing` |
| R `mm_stage2_rehearsal.py` | `mm_live_pilot_cli`, `re1_attended_cli`, `re1_rehearsal` | `tests/market/test_mm_stage2_rehearsal` |
| R `mm_stage2_rewards.py` | `mm_stage2_entrypoint`, `mm_stage2_rehearsal`, `re1_transport` | `tests/market/test_mm_stage2_rewards` |
| R `mm_stage2_selection.py` | `mm_stage2_entrypoint`, `mm_stage2_rehearsal`, `re1_attended`, `re1_rehearsal`, `src/weather/operations/international_live_session_launcher_sealer`, `src/weather/operations/international_live_session_runner`, `src/weather/operations/international_live_wrapper_sealer` | `tests/market/test_mm_stage2_rehearsal`, `tests/market/test_mm_stage2_selection`, `tests/market/test_re1_attended`, `tests/market/test_re1_attended_parity_audit`, `tests/market/test_re1_sizing`, `tests/operations/test_stage2_session_sealing` |
| R `mm_stage2_user_stream.py` | `mm_stage2_entrypoint` | `tests/market/test_mm_user_stream`, `tests/operations/test_stage2_child_evidence` |
| R `mm_user_stream.py` | `mm_live_pilot_cli`, `mm_stage2_user_stream`, `re1_transport`, `src/weather/schema_registry_data` | `tests/market/test_mm_user_stream`, `tests/operations/test_stage2_child_evidence` |
| R `order_book_tape.py` | `reward_share_estimate`, `src/weather/operations/clob_raw_tape_tiering` | `tests/market/test_order_book_tape`, `tests/market/test_reward_share_estimate`, `tests/operations/test_clob_raw_tape_tiering`, `tests/operations/test_cold_archive_catalog` |
| R `polymarket_client.py` | `market_microstructure`, `market_microstructure_capture`, `src/weather/collection/snapshot_tracker`, `src/weather/operations/event_metadata_validation` | `tests/collection/test_collection_robustness` |
| R `portable_live_candidate_preflight.py` | `src/weather/schema_registry_data` | — |
| R `re1_attended.py` | `re1_attended_cli`, `re1_evidence`, `re1_owner_checks`, `re1_rehearsal`, `re1_transport` | `tests/market/test_re1_addendum`, `tests/market/test_re1_attended`, `tests/market/test_re1_evidence`, `tests/market/test_re1_owner_checks`, `tests/market/test_re1_payout_evidence`, `tests/market/test_re1_resilience`, `tests/market/test_re1_sdk_shapes`, `tests/market/test_re1_sizing` |
| R `re1_attended_cli.py` | — | `tests/market/test_re1_evidence`, `tests/market/test_re1_sizing` |
| R `re1_evidence.py` | `re1_attended_cli`, `re1_owner_checks`, `re1_payout_evidence` | `tests/market/test_re1_addendum`, `tests/market/test_re1_evidence`, `tests/market/test_re1_payout_evidence`, `tests/market/test_re1_resilience`, `tests/market/test_re1_sizing` |
| R `re1_owner_checks.py` | `re1_attended_cli`, `re1_transport` | `tests/market/test_re1_owner_checks`, `tests/market/test_re1_resilience`, `tests/market/test_re1_transport` |
| R `re1_payout_evidence.py` | `re1_attended_cli`, `re1_evidence`, `src/weather/schema_registry_data` | `tests/market/test_re1_sdk_shapes` |
| R `re1_rehearsal.py` | `re1_attended_cli`, `re1_owner_checks` | `tests/market/test_re1_attended`, `tests/market/test_re1_sizing` |
| R `re1_resilience.py` | `re1_attended` | `tests/market/test_re1_resilience` |
| R `re1_sizing.py` | `mm_stage2_selection`, `re1_attended`, `re1_attended_cli`, `re1_owner_checks`, `re1_transport` | `tests/market/test_re1_sizing` |
| R `re1_transport.py` | `re1_attended_cli`, `re1_evidence`, `re1_owner_checks`, `re1_payout_evidence` | `tests/market/test_re1_addendum`, `tests/market/test_re1_evidence`, `tests/market/test_re1_owner_checks`, `tests/market/test_re1_payout_evidence`, `tests/market/test_re1_sdk_shapes`, `tests/market/test_re1_transport` |
| R `reward_quote.py` | `mm_stage2_hold`, `mm_stage2_rehearsal`, `mm_stage2_rewards`, `mm_stage2_selection`, `mm_stage2_user_stream`, `re1_attended`, `re1_sizing` | `tests/market/test_re1_sizing`, `tests/market/test_reward_quote` |
| R `reward_share_estimate.py` | `maker_evidence_public`, `mm_stage2_hold`, `re1_attended`, `reward_quote` | `tests/market/test_reward_quote`, `tests/market/test_reward_share_estimate` |
| R `snapshot_cadence_quality.py` | `mm_policy`, `src/weather/collection/live_variant_predictions`, `src/weather/collection/snapshot_store`, `src/weather/collection/snapshot_store_backfill`, `taker_bot_strategy_evaluation` | — |
| R `storage_pressure_policy.py` | `market_microstructure_capture`, `src/weather/operations/config_inventory`, `src/weather/schema_registry_recent_data` | `tests/market/test_market_microstructure`, `tests/market/test_storage_pressure_policy` |
| R `worker_release_binding.py` | `market_making_run`, `src/weather/backtesting/replay_fidelity`, `taker_bot_cli`, `taker_bot_finalization` | `tests/backtesting/test_replay_fidelity`, `tests/market/test_worker_release_binding`, `tests/market/test_worker_release_binding_streaming` |
| E `maker_evidence_archive.py` | `maker_evidence_capture`, `maker_evidence_store` | `tests/market/test_maker_evidence_capture` |
| E `maker_evidence_capture.py` | — | `tests/market/test_maker_evidence_capture` |
| E `maker_evidence_inspect.py` | — | `tests/market/test_maker_evidence_capture` |
| E `maker_evidence_public.py` | `maker_evidence_capture` | `tests/market/test_maker_evidence_capture` |
| E `maker_evidence_socket.py` | `maker_evidence_stream` | `tests/market/test_maker_evidence_capture` |
| E `maker_evidence_store.py` | `maker_evidence_archive`, `maker_evidence_capture`, `maker_evidence_inspect`, `maker_evidence_public`, `maker_evidence_stream` | `tests/market/test_maker_evidence_capture` |
| E `maker_evidence_stream.py` | `maker_evidence_capture` | — |
| D `fill_toxicity_desk_study.py` | — | — |
| D `fill_toxicity_inputs.py` | — | — |
| D `fill_toxicity_model.py` | `fill_toxicity_desk_study`, `fill_toxicity_inputs` | `tests/market/test_fill_toxicity_desk_study` |
| D `fill_toxicity_panels.py` | `fill_toxicity_desk_study` | `tests/market/test_fill_toxicity_desk_study` |
| D `fill_toxicity_statistics.py` | — | — |
