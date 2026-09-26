# Agent report 2026-09-110a — maker core Phase 0

**PASS — offline foundation implemented; 661 focused tests pass, zero failures,
errors or skips; compileall passes. No execution authority or profitability claim.**

Answers [handoff 110a](workstation-handoff-2026-09-110a-maker-core-phase0.md),
using the approved [design](../operations/informed-maker-design-2026-09-25.md).
Branch: `codex/maker-core-phase0-20260925`.
Fetched base: `2190e64e7664b8ee0dda558eb894aa1a458985e5`.
Verified implementation tip: `f625585b94ad758c5e491e1b0a43343aa1b6f1ef`.
The report and generated correspondence-index follow-up are separate commits;
the final published tip is the head of this branch, not a contracts tag.

## Delivered module map

| Path | Delivered |
| --- | --- |
| `src/maker_core/contracts/__init__.py` | Frozen v0.1 dataclasses and Protocols, UTC/probability/joint/expiry validation, immutable mappings |
| `src/maker_core/contracts/conformance.py` | Provider conformance with injected fixture clock, missing/expired inputs, historical repeatability after future ingestion, joint checks and price-contamination probes |
| `src/maker_core/quoting/rewards.py` | Copied reward kernels and their local helper dependencies; no weather import |
| `src/maker_core/quoting/prices.py` | Copied frozen RE-1 proposer plus qualified-mid, outward tick and touch-buffer helpers |
| `src/maker_core/quoting/policy.py` | Pure hash-bound `decide`, informed/blind profiles, reason codes, ranking, advisory inventory fee rule |
| `src/maker_core/evidence/journal.py` | Exclusive-create, flushed hash-chain writer, recursive secret guard, chain/clock/terminal verification and optional external digest |
| `src/maker_core/{portfolio,venue,runtime,replay}/__init__.py` | Docstring-only placeholders |
| `tests/maker_core/fixtures/fictional_domain.py` | Four-Protocol fictional biased-coin plugin with captured-input filtering and expiry |
| `tests/maker_core/` | Conformance, differential, policy, recorded-price and journal tests; deterministic fictional lifecycle replay through settlement |
| `docs/operations/maker-core-contracts.md` | Plugin implementation guide, conformance, additive-only publication, policy units/defaults, journal and deferred interfaces |

Contracts: `MarketDescriptor`, `UniverseSnapshot`, `MarketUniverse`, `OutcomeView`,
`Unavailable`, `FairValueProvider`, `InfoEvent`, `InformationClock`, `SettlementFact`,
`Pending`, `SettlementResolver`, `ExposureModel`, and `CONTRACTS_VERSION = "0.1"`.
No market-price field is added to `OutcomeView`. No tag was created; production
owns `maker-core-contracts-v0.1` after landing.

## Policy and import boundaries

The informed policy keeps the qualified market mid as centre. It implements
book/terms freshness, one-sided/crossed rejection, pull/decided events, width and
asymmetry, size/depth selection, conservative net screening, explicit cash/event/
factor/wallet caps, T+1/T+2 selection, ranking and the fee-aware inventory rule.
Cancellation precedes cooldowns. `blind_re1` freezes outward 1.5-cent pricing,
[1,3]-cent hold/requote, one band, bounded sizes and first-fill termination.

The spec does not numerically define stale sigma or calibration-grade trust.
The exposed offline defaults are documented in the contract: added sigma 0.01
per hour in quadrature, none/shadow/scored size ceilings 30/50/75, and no
unscored leg tightening. Cash/caps and a conservative trade-hazard bound remain
required caller inputs; there is no fabricated hazard or live cap authority.
Expired views refuse; explicit missing-input `Unavailable` uses blind width.

The new AST ratchet in `tests/operations/test_import_architecture.py` checks:
no weather imports in core; SDK/HTTP imports only in venue; environment/vault
reads only in the future credential owner; no venue/runtime imports in quoting
or portfolio; future weather plugins import only core contracts. Relative
imports, aliases and literal dynamic imports are checked; computed dynamic
imports are rejected. The fictional plugin is checked too. Setuptools already
discovers the package; path policy and `pyproject.toml` need no changes.

## Verification and evidence limits

All tests ran serially under `scripts/ops/workstation_heavy.ps1` on the
workstation. The editable checkout could not create `data/logs/heavy_workload.lock`;
the failed admission launched no Python child. Verification used a detached
worktree with an empty local runtime directory and the identical repository-owned
wrapper. No load gate, ACL or runtime-data path was changed to make it run.
The owner's pre-existing `.env.example` modification was excluded throughout.

| Verification | Result |
| --- | --- |
| Contracts/conformance | 17 passed |
| Journal/secret guard | 8 passed |
| Copied reward/price kernel differential checks | 477 passed |
| Pure policy and fictional lifecycle replay | 37 passed |
| Recorded RE-1 price parity | 13 passed |
| Existing reward-share tests, unchanged | 24 passed |
| Existing execution-tape markout tests, unchanged | 49 passed |
| Import architecture, including new ratchet/discovery | 25 passed |
| Existing path-policy test | 1 passed |
| Documentation audit tests, including `audit_repo()` | 10 passed |
| `compileall -q app src tests` | PASS |
| `git diff --check` | PASS |

The reward grid includes missing/zero/subminimum size, negative distances,
spread boundaries, midpoint interval edges, one-sided and crossed books and
tick/minimum combinations. The price grid covers all four sizes, half-tick
midpoints and identical refusal behavior against a frozen source copy from
`2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8`.

Local campaign journals were available read-only. A bounded projection retains
public quote inputs and prices for attempts 1–12, plus source selection/journal
SHA-256 values. All twelve selections reproduce quote prices through
`blind_re1`; eight also match first-minute recorded journal prices. Four attempts
have no minute-price record. Clocks and identity are synthetic in this price-only
replay: no claim of full account/session/transport parity. No account responses,
credentials, auth fields or raw journals were copied into the repository.

This is deterministic engineering verification, not economic inference; no
date clusters, market clusters, effect estimate or confidence interval applies.
No new panel was scored. The reserved-window contract read NONE RESERVED.

Reproduce from a workstation checkout using the literal wrapper form in
[development](../development.md#separate-non-capture-workstation); encode these Python
argument arrays as base64 JSON, set absolute checkout/interpreter paths, and
choose an explicit temporary directory inside that checkout:

```text
-m pytest tests/maker_core tests/operations/test_import_architecture.py tests/operations/test_path_policy.py tests/market/test_reward_share_estimate.py tests/market/test_execution_tape_markout.py tests/operations/test_agent_docs_audit.py -q --basetemp=<absolute-temporary-test-directory>
-m compileall -q app src tests
```

After the report's first commit, regenerate and check with
`python -m weather.reporting.roadmap.correspondence_index`, then its `--check`
mode, as required by the roadmap guide. The docs audit is also run through its
test under the workstation wrapper after index regeneration.

## Roll expectation and deferred work

**Expected ROLL-FREE, not a production verdict.** Per-file groups:
every new `src/maker_core/**` file is isolated from existing runtime imports;
every `tests/maker_core/**` file and the edited import ratchet is test-only;
all remaining changed files are documentation/index files. No existing
`src/weather/**` file changes. Production must obtain the actual closure verdict
with `scripts/ops/roll_verdict.ps1 -Branch codex/maker-core-phase0-20260925`.
The protected reward module retains Git blob
`7777b8003c31c73eb2410f2111d57c2e807f99c1`, equal to the fetched base.

Paper-maker owner docs and OPERATIONS_DESIGN mark `mm_policy`,
`market_making_run*`, `mm_paper*` retired. Stage 2 hold `88aa7e43a` is fixtures
only. No code was deleted. Production owns any disabled-task unregistration
with backups in a separate operation.

Deferred by phase: weather/YouTube plugins, real evidence loader/scorer, measured
hazard, portfolio accounting, venue/credential adapters, session controller,
shadow operation and live qualification. No venue calls, credentials, `.env`
access, production data, production writes, scheduled-task changes, restarts,
master merge, contract tag, or live trading occurred. Push of this topic and
report is the authorized handback; production acceptance/adoption remains pending.
