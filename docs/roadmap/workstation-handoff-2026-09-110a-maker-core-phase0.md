# Workstation handoff 2026-09-110a — maker core, Phase 0 (foundation)

Written 2026-09-25 by the production agent. The owner approved the
[informed maker design](../operations/informed-maker-design-2026-09-25.md) and its decisions 1-5, 7, 9, 10 (DECISION_LOG
2026-09-25): package `src/maker_core/`; v0 centre = size-qualified market mid (fair value sets width, asymmetry, size, veto);
publish contracts v0.1 now, additive-only after; retire the paused paper maker and freeze the Stage 2 hold build as fixtures;
shadow runs on the workstation. **All live trading is paused.** Read the design document first; it is the spec. Mission id
110a (101a and 100a-100i are taken).

## 1. Build (branch `codex/maker-core-phase0-20260925` from `origin/master`)

1. **Package and boundary.** New top-level package `src/maker_core/` with subpackages `contracts/`, `quoting/`, `portfolio/`,
   `venue/`, `runtime/`, `evidence/`, `replay/` (only `contracts`, `quoting`, `evidence` get real code in Phase 0; the others
   are stubs with docstrings). Confirm `pyproject.toml` discovery and the path-policy tests accept it; fix only what they
   require. Add `docs/operations/package-boundaries.md` (or extend the existing boundary doc if one exists) with the edges.
2. **Ratchet** in `tests/operations/test_import_architecture.py` (beside
   `test_package_dependency_edges_follow_documented_ratchet`, line ~1109): no `weather` import anywhere under
   `src/maker_core/`; no `polymarket`, `py_clob_client`, `eth_account`, `dotenv` or `os.environ` credential read outside
   `maker_core/venue/` and `maker_core/runtime/credentials.py`; a future `src/weather/market/maker_plugin/` may import only
   `maker_core.contracts` (write the rule now; the directory comes in Phase 1).
3. **Contracts v0.1** (`maker_core/contracts/`): exactly the dataclasses and Protocols in the design's "Plugin contract"
   section (`MarketDescriptor`, `UniverseSnapshot`, `MarketUniverse`, `OutcomeView`, `Unavailable`, `FairValueProvider`,
   `InfoEvent`, `InformationClock`, `SettlementFact`, `Pending`, `SettlementResolver`, `ExposureModel`), plus
   `CONTRACTS_VERSION = "0.1"`. Validation in `__post_init__` (probabilities in [0,1], `stdev > 0`, `valid_until > as_of`,
   joint sums to 1 within 1e-9, UTC-aware datetimes). No market price fields on `OutcomeView`.
4. **Conformance kit** (`maker_core/contracts/conformance.py`): a function any plugin's test suite calls with its provider
   instances and a fixture clock; checks point-in-time behaviour (same `as_of` → same output), `Unavailable` rather than guesses,
   `valid_until` honoured, joint consistency, and that a provider handed a market-price input refuses or ignores it (the
   "never consume the mid" rule).
5. **Fictional-domain reference plugin** (`tests/maker_core/fixtures/fictional_domain.py`): a toy domain (e.g. "coin flips
   with a known bias") implementing all four Protocols; it passes the conformance kit. This is the template handed to the
   YouTube team.
6. **Quoting kernels** (`maker_core/quoting/rewards.py`, `prices.py`): copy (do not move or edit) the reward kernels from
   `src/weather/market/reward_share_estimate.py:134-330` (`order_score`, `q_min`, `share_of`, `side_score`,
   `evaluate_sample`) and the price helpers from RE-1 `reward_quote.py` (qualified mid, outward tick snap, touch buffer). Add
   differential tests proving identical outputs to the originals on a fixture grid. **Do not modify
   `reward_share_estimate.py`**: 88a imports it on production and editing it would roll the evidence worker.
7. **`decide()` skeleton + `blind_re1` profile** (`maker_core/quoting/policy.py`): a pure function
   `decide(inputs) -> QuoteDecision` with reason codes and input hashes, implementing the design's `informed_v0` rules 1-8
   behind a profile object, and the `blind_re1` profile (d0 1.5 c, [1,3] c requote window, one band, first fill ends,
   sizes 20/30/50/75). Unit tests per rule. If RE-1 attempt journals are available on the workstation (campaign root
   `C:\Users\Michael\.weather-re1m-20260921`, read-only), add a parity test replaying their recorded inputs through
   `blind_re1` and matching the recorded quote prices; if not available, say so and add the test skeleton.
8. **Evidence journal** (`maker_core/evidence/journal.py`): lift the hash-chained journal and secret guard (from
   `mm_stage2_hold.py` HoldJournal and RE-1) with `write_new` semantics; tests for chain integrity and secret scrubbing.
9. **Retire the paper maker** (docs only in this mission): mark `mm_policy` / `market_making_run*` / `mm_paper*` as retired in
   their owner docs and OPERATIONS_DESIGN; do not delete code or touch scheduled tasks (the production agent unregisters the
   disabled tasks with backups). Freeze note for the Stage 2 hold build (`88aa7e43a`) as fixtures only.
10. **Contracts publication**: a short `docs/operations/maker-core-contracts.md` (how a domain plugin implements v0.1, the
    conformance kit, the fictional plugin as template, additive-only rule). Tag nothing yet; the production agent tags
    `maker-core-contracts-v0.1` after landing.

## 2. Verification

Focused tests via `scripts/ops/workstation_heavy.ps1`: the new `tests/maker_core/**`, `tests/operations/test_import_architecture.py`,
path-policy tests, the reward-share and markout tests (unchanged), docs audit. compileall. Report the roll expectation
(new files only should be ROLL-FREE; the production agent takes the real verdict).

## 3. Boundaries and deliverables

No venue calls, no credentials, no `.env`, no production data or writes, no scheduled tasks, no live anything. Report:
`docs/roadmap/agent-report-2026-09-110a-maker-core-phase0.md` (verdict first, module map, ratchet rules, contract listing,
differential/parity test results, what was deferred, the tip). Push is authorized.
