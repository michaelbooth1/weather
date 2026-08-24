# 67. Authenticated Exchange Adapter And MM-2 Pilot Harness [PARTIAL 2026-08-23 - FIXED-SCOPE STAGE 0/1 SOFTWARE INTEGRATED; LIVE EVIDENCE OPEN]

Goal: implement the smallest live-order execution path that can run the MM-2
pilot without weakening the existing paper/risk gates.

Source: market-making roadmap items 43-46 and 55-57 built the keyless
policy/orchestration/risk foundation, while item 45 defines the platform and
account gates required before any live order can be submitted.

Why this is missing: items 43-46, 55-57, and 44 build the keyless policy,
orchestration, lifecycle, budget, cockpit, and paper-scoring system. Item 45
defines live gates and platform/account verification. There is still no
roadmap owner for the authenticated exchange adapter that places, cancels,
heartbeats, reconciles, redeems, and proves real order lifecycle behavior.
Item 45's software gates are now ready: live-pilot requires current
live-readiness, data-layer audit, and platform-verification artifacts before
any adapter may submit an order.

Why this matters: authenticated exchange access is the first point where a
software defect can spend real funds or leave live orders open. The adapter and
pilot evidence must prove lifecycle, reconciliation, and paid-vs-predicted
behavior before any size increase.

- [x] Keep credentials, private keys, API secrets, wallet addresses, and
  allowance settings outside the repo; add read-only account diagnostics before
  any trading verb can run.
- [x] Add a signed CLOB adapter for post-only order create, cancel, cancel-all,
  heartbeat/dead-man behavior, order query, balances, allowances, positions,
  and redemption/reward status.
- [x] Preserve dry-run, read-only, and keyless paper modes as the default; live
  mode must require explicit operator flags plus current item-45 gates.
- [x] Reconcile user WebSocket fills/order updates and REST open-order queries
  into the existing `order_lifecycle.jsonl`, `budget_ledger.jsonl`, and risk
  event artifacts.
- [ ] Implement the MM-2 day-one probes: heartbeat-lapse throwaway order,
  min-size/tick/post-only rejection checks, one tiny two-sided quote, cancel-all
  verification, balance-reserve reconciliation, and user WebSocket lifecycle
  verification.
- [x] Re-prove the exact selected SDK against the current official post-only,
  heartbeat, account-reader, user-stream, cancellation, and asynchronous
  settlement contract before credentialed integration. The selected
  `polymarket-client==0.6.0` source and published wheel passed the keyless
  contract audit on 2026-08-14; production wallet and exchange evidence
  remain separate open gates.
- [ ] Review and bind the fixed-scope, host-owned Stage 0/1 wrapper on the
  production execution host. Do not add a generic repository live
  mutation CLI to close this item.
- [x] Add report-side paid-vs-predicted reconciliation for maker rebates,
  liquidity rewards, redemptions, fees, pUSD/USDC balances, and settlement P&L
  before any size increase.
- [ ] Collect real paid-vs-predicted evidence from the pilot account
  across maker rebates, liquidity rewards, redemptions, fees, pUSD/USDC
  balances, and settlement P&L before any size increase.
- [x] Emit a pilot report comparing live fills, markouts, cancellations,
  heartbeat behavior, and rewards/rebates against the simultaneous paper
  counterfactual.

Acceptance: live orders cannot be submitted unless platform/account checks,
paper gates, SLO gates, risk caps, and operator confirmations pass; every live
order has a reconciled lifecycle from intent through cancel/fill/settlement;
and MM-2 remains min-size, bounded, and auditable until its pilot evidence
passes.

## 2026-08-14 unified-client migration

The live extra now pins the official `polymarket-client==0.6.0`; the obsolete
CLOB-v2 package is no longer an executable dependency. The adapter uses the
unified typed account, book, reward, signed-order, post, and cancellation
surfaces. It preserves the one-submit capability by calling local
`create_limit_order(..., post_only=True)` followed by exactly one `post_order`,
never the allowance-recovering convenience placement method. Signed-order
proof now includes GTC and post-only fields.

Two explicit shims close gaps without creating a second trading client. A
public relayer `/deployed` preflight proves the exact Safe/deposit wallet exists
before `SecureClient.create`, preventing that constructor from deploying a
wallet during Stage 0. A one-purpose authenticated sender implements the
current bodyless `POST /heartbeats` contract and requires the exact
`{status: "ok"}` response. Public tick, neg-risk, and fee endpoints are also
cross-checked against the typed book. Bootstrap schema v0.3 removes obsolete
rotating-ID fields. Mutation remains unavailable without authoritative
account-wide user-event health and exact-scope position readers.

Keyless evidence passed against both the checked source and the isolated
published wheel. Repository verification covers the adapter, protocol shim,
credential factory, Stage 0/1 lifecycle, bounded pilot CLI, readiness gates,
and exact dependency pin. Still open: deploy the fixed-purpose wrapper on the
production host, install the live extra there, run doctor and Stage 0,
then collect the two small Stage 1 cancellation proofs before a rebate-producing
quote is considered.

Exchange harness update (2026-06-16 UTC): `weather.market.mm_exchange`
introduces the keyless item-67 adapter boundary. The CLI wrapper
`python -m src.mm_exchange --run-folder ...` reads a live-pilot run folder,
verifies item-45 live-readiness/data-layer/platform gates, reports credential
environment presence without logging values, refuses live trading verbs unless
`--allow-live` and a future concrete trading adapter are present, and writes
`exchange_reconciliation.json` plus `exchange_reconciliation.md`. A read-only
fixture adapter reconciles exchange open orders and user-stream fill/cancel/
reject events into `order_lifecycle.jsonl`, `budget_ledger.jsonl`,
`fills_long.csv`, and `risk_events.jsonl`, so the artifact plumbing is testable
without keys or network side effects. The harness also emits MM-2 probe status
rows for heartbeat/dead-man, min-size/tick/post-only, tiny two-sided quote,
user-stream lifecycle, balance-reserve, and reward/rebate checks. Remaining
open work: concrete signed global/US exchange clients, real heartbeat and
post-only probes, read-only account endpoint implementations, redemption and
paid-vs-predicted reward/rebate reconciliation, and the live-vs-paper pilot
report. Focused tests:
`python -m pytest tests/market/test_mm_exchange.py tests/market/test_market_making_run.py tests/market/test_mm_risk.py tests/market/test_mm_policy.py tests/market/test_mm_paper.py tests/operations/test_schema_registry.py -q`
passed (`53` tests).

Request-plan and pilot-report update (2026-06-16 UTC): `mm_exchange` now emits
platform-specific adapter request diagnostics. For Polymarket US, the harness
builds redacted signed-request plans for preview/create post-only orders,
cancel, cancel-all, open-order query, positions, balances, rewards, and
redemption-status reads using the documented `X-PM-*` header shape and
`timestamp + method + path` signature payload. For Polymarket global, it builds
redacted CLOB request plans for heartbeat, post-only order submit, cancel,
cancel-all, open-order query, positions/balances, rewards, and redemption
status, while explicitly blocking order placement until a pre-signed EIP-712
order payload from the official CLOB client and an injected L2 header signer are
present. Reconciliation now also writes `mm2_probe_status.json`,
`mm2_pilot_report.json`, and `mm2_pilot_report.md`; the pilot report compares
live fill count/size/notional, cancellations/rejections, markouts, actual
reward/rebate evidence, and paper counterfactual expected reward/rebate fields,
and marks missing evidence explicitly. Updated focused tests:
`python -m pytest tests/market/test_mm_exchange.py -q` passed (`6` tests).
Remaining open work is intentionally live-adapter work: concrete signed
global/US clients, real heartbeat/post-only/cancel-all probes against a live
account, authenticated account endpoint reads, redemptions, and final
paid-vs-predicted settlement P&L reconciliation.

Signed-adapter software update (2026-06-16 UTC): `mm_exchange` now includes
`PolymarketUSHTTPAdapter` and `PolymarketGlobalHTTPAdapter` classes with
injected signers and transports, so tests exercise real request construction
without environment secrets or network side effects. The US adapter signs
post-only order create/preview, cancel, cancel-all, order query, balances,
positions, rewards, and redemption-status request paths through the documented
`X-PM-*` shape. The global adapter signs CLOB heartbeat, post-only submit,
cancel, cancel-all, order query, balances/positions, rewards, and redemption
request paths through `POLY_*` headers and refuses order placement unless the
caller provides a pre-signed EIP-712 order payload. Updated focused tests:
`python -m pytest tests/market/test_mm_exchange.py -q` passed (`8` tests).
Remaining item-67 work is now live-evidence and reconciliation work: real
account probes, user WebSocket lifecycle evidence, paid-vs-predicted
redemption/reward/settlement P&L, and final MM-2 acceptance.

Financial-reconciliation software update (2026-06-16 UTC): `mm_exchange` now
adds `financial_reconciliation` to `mm2_pilot_report.json` and renders a
`Financial Reconciliation` section in `mm2_pilot_report.md`. The payload
compares paper-expected rebate/reward score against actual reward/rebate
snapshots, fees, redemption status, settlement P&L, starting/ending pUSD/USDC
balances, balance delta, and total P&L after fees/incentives. Missing balance,
fee, redemption, settlement-P&L, or reward evidence is explicitly listed as
`financial:*` missing evidence, so a pilot cannot silently look complete before
post-settlement account data exists. The fixture-backed test proves the complete
path with read-only evidence and no committed secrets:
`python -m pytest tests/market/test_mm_exchange.py -q` passed (`8` tests).
Remaining open work is live evidence: real heartbeat/post-only/cancel-all
probes, user WebSocket lifecycle evidence from the pilot account, and actual
paid-vs-predicted payout/redemption/P&L snapshots.

## 2026-06-18 audit disposition

The Python audit found the software harness implemented through keyless safety,
signed request construction with injected signers/transports, live-gate
enforcement, read-only fixture reconciliation, pilot-report emission, and
financial reconciliation reporting. The unchecked MM-2 probe and
paid-vs-predicted boxes require a live pilot account, credentials kept
outside the repo, and real exchange lifecycle/account evidence. They remain
open deliberately; closing them without live-account artifacts would weaken the
acceptance criteria.

## 2026-06-24 evidence-only disposition

No live probe was run. The current host has no live credential refs in
the environment:

- Polymarket US missing: `POLYMARKET_US_KEY_ID`,
  `POLYMARKET_US_SECRET_KEY_STORAGE_REF`.
- Polymarket global missing: `POLYMARKET_API_KEY`,
  `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`,
  `POLYMARKET_FUNDER_ADDRESS`, `POLYMARKET_PRIVATE_KEY_STORAGE_REF`.
- No forbidden direct secret env vars were present.

The existing evidence harness remains healthy:

- `python -m pytest -q tests\market\test_mm_exchange.py` -> 8 passed.

Because no live pilot account or external credential material is available,
the MM-2 heartbeat, post-only/min-size/tick, tiny two-sided quote, cancel-all,
user WebSocket lifecycle, and paid-vs-predicted payout evidence remain blocked.
No market-risk code changes were made.

2026-06-24 continuation check:

- Rechecked the live credential environment; the same Polymarket US/global
  credential references remain absent, and no forbidden direct secret env vars
  are present.
- Inspected the eight newest `data/mm_runs/**/preflight.json` files. They are
  `paper-live-forward` runs rather than `live-pilot` runs, and all report
  `live_readiness.ok = false`.
- No live exchange CLI invocation was run because the existing harness requires
  both a passing `live-pilot` run folder and external credential references
  before live verbs can be enabled.

## 2026-08-14 International-only pilot disposition

The credential-absence disposition above is historical and is no longer the
owning blocker. The operator approved an International Polymarket pilot on the
production execution host. Polymarket US is outside product scope and must
never be used.

The current Stage 0/1 contract is exactly one International condition/token, a
finite non-raisable 100 pUSD-equivalent wallet cap, forced post-only behavior,
no naked sells, and all existing lower risk ceilings preserved. Mutation stays
disabled unless authoritative user-event health, user-event, open-order, and
exact-position readers are present. The official-client adapter must not expose
a generic command-line live-mutation path.

Stage 0/1 remains proof-gated on an immutable exact-tip full suite and a
reviewed fixed-scope wrapper. A separate bounded Stage 2
lifecycle implementation is not integration-ready or live-ready. The two
unchecked live-evidence bullets above remain open until a tiny real lifecycle
and paid-vs-predicted settlement/rebate record are reconciled without weakening
any gate or increasing any ceiling.

## 2026-08-13 International pilot authorization and hardening

The operator explicitly authorized work toward a small real-world live test
with approximately 100 pUSD total risk capital, on International
Polymarket only. The canonical staged protocol and stop conditions now live in
`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`.

Current host evidence still blocks orders: the platform-verification artifact
is the fail-safe template, current live-readiness evidence is absent,
International credential references are absent, continuous execution capture
is approved but not yet producing rows, the International economics pivot is
not adopted in production, and the latest paper run has zero quote-permission
rows. No live exchange call was attempted.

Software hardening on `codex/international-live-probe` now makes the live-pilot
gate International-only, caps the requested and recorded wallet budget at 100,
requires exactly one market, and prevents CLI overrides from raising the
existing 25 daily-loss, 25 event-notional, 10 band-notional, or 120-second TTL
ceilings. It also corrects the International heartbeat request plan to the
pinned client's `/v1/heartbeats` endpoint. The generic API reference still
shows a different path, so exact-version contract verification is a live gate.
The hand-built HTTP adapter remains a
diagnostic boundary. A pinned adapter boundary around the official
`py-clob-client-v2==1.1.0` client is prepared for post-only placement, account
reads, cancellation, and dead-man heartbeat. It accepts an already-authenticated
client and becomes mutation-capable only when authoritative user-event and
position readers are supplied and explicitly verified. Placement also requires
a correctly chained heartbeat acknowledged within the freshness limit, a fresh
book/min-size/tick/neg-risk snapshot for the adapter's single allowed token, an
account outside closed-only mode, and authoritative owned inventory for every
sell. Price, size, and notional are rechecked inside the adapter. A post-only
response must be an execution-free `live` order; any ambiguous, matched, or
trade-bearing response triggers cancel-all and a hard stop. Credential
resolution and the lifecycle core are now prepared below; heartbeat
supervision for an ordinary maker run remains blocked. The bounded Stage 0 and
one-submit Stage 1 paths now have authoritative live-reader wiring and a
credential-reference-only operator CLI, described below.

The same audit removed direct International API key, API secret, and passphrase
values from the credential gate. All authentication material now requires
external storage references; only the public funder address may be present
directly. The later credential work below selected Windows Credential Manager
references without provisioning or reading a real secret.

The wallet/SDK topology is not closed. The pinned CLOB v2 client supplies the
required rotating dead-man heartbeat, but unresolved upstream deposit-wallet
identity reports mean it is not proof that a newly isolated wallet can place an
order. The newer unified SDK owns wallet setup and a typed account-wide user
stream but, in the audited public surface, does not expose that REST dead-man
heartbeat. Stage 0 must prove one exact-version topology end to end before any
wallet is funded; no UI workaround is an accepted prerequisite.

Platform verification is therefore advanced to
`mm_platform_verification_v0.5`. In addition to the prior API lifecycle and
secret-redaction proof, it is International-only and requires exact production
hosts, consistent signature name/ID, valid private-key signer, order signer,
funder and API-key-owner addresses, an explicit wallet-identity consistency
proof, and the complete rotating dead-man heartbeat contract. The tracked
template remains fail-safe. Versions v0.2 through v0.4 are legacy and cannot pass a new
live-pilot preflight.

The former gate sequence was circular for a first-ever lifecycle order: full
platform verification required live fill/final-state and dead-man cancellation
evidence, while the ordinary live path required full platform verification.
`weather.market.mm_live_bootstrap` now defines the separate
`mm_platform_bootstrap_v0.3` read-only contract. It is International-only,
bound to one token and condition, expires within one hour, and requires wallet,
account, SDK, book, fee, a non-posting signed-order topology preview,
account-wide stream, heartbeat-chain, cancel-all-to-zero, budget, and
secret-hygiene proof. It can authorize only the
future dedicated Stage 1 lifecycle-probe command; the ordinary maker runner
does not consume it and still requires v0.5.

The exact SDK audit also found that `create_and_post_order` can perform two
network posts through its internal order-version refresh loop. The prepared
adapter therefore signs with `create_order` and invokes `post_order` exactly
once. A version mismatch fails closed and consumes the one-submit capability.

`weather.market.mm_live_lifecycle_probe` prepares the mutation core. The generic
`weather.market.mm_live_pilot_cli` deliberately does not expose Stage 0 or Stage
1; a separately reviewed, host-owned fixed-scope wrapper must call those
library functions. The lifecycle core accepts only a passing bootstrap gate for
the exact
adapter token plus the literal Stage 1 confirmation, requires zero starting
orders, derives a minimum-size BUY at the minimum tick, verifies that the order
appears in both open-order truth and the authoritative user stream, then proves
either cancel-all or heartbeat-lapse cancellation and a terminal user event.
Every failure attempts cancel-all. Both modes require separate runs; neither
can execute on this host until credential references are provisioned and the
selected SDK/wallet topology is verified.

The lifecycle core now also requires a new append-only journal path before any
mutation. It flushes authorization, bootstrap hash, exact intent, placement,
exchange observation, cancellation, terminal-state, cleanup, and failure-phase
events; the PASS result binds the journal SHA-256. Raw SDK exception text is
not serialized. This closes the prior crash-path evidence hole.

The two Stage 1 modes can no longer be promoted by manually copying their PASS
booleans. `build_stage1_lifecycle_bundle` rereads and hashes both journals,
requires distinct orders and files, rejects any scoped trade lifecycle event,
and derives the no-fill/cancel/heartbeat evidence. Full v0.4 verification embeds
that content-bound bundle and must agree with its derived fields. This closes
both a lagging-position false no-fill and a self-asserted lifecycle-proof hole.

`weather.market.mm_credentials` now implements the intended production secret
boundary without provisioning or reading a real credential. It accepts only
`wincred://` references to Windows Credential Manager generic credentials,
rejects direct secret environment variables, redacts the in-memory bundle's
representation, and constructs the pinned client with server time and retries
disabled. The public funder and validated signature-type ID come from the
bootstrap gate. Credential Manager targets must be provisioned interactively;
no secret-bearing writer or command-line setup path is provided.

The payout audit also retired two fixture-only shortcuts. Current reward-market
metadata no longer counts as rebate evidence, and a quote-intent rebate estimate
is no longer compared with a wallet-level payout. The prepared adapter can use
the official public `/rebates/current` response, and the v0.2 reconciliation
artifact validates the completed payout cycle against the exact maker, date,
and condition. It accepts a completed empty response as measured zero. Total
P&L remains incomplete unless zero ending positions, external cash flows,
non-overlapping settlement/fee/incentive bases, and the balance-delta identity
all reconcile to the documented fee precision.

Live-evidence hardening update (2026-08-13 UTC): the prepared International
adapter now normalizes the official order/trade shapes at the exact pilot
maker, condition, and token boundary. It recognizes `type=CANCELLATION`, keeps
pre-confirmation trade states pending, attributes maker fills through the
matching `maker_orders` row, and books a final fill only at `CONFIRMED`.
Financial completion now rejects unobserved empty-position lists, configured
fee rates presented as paid fees, implicit reuse of one balance as both
endpoints, and disagreement among the maker/condition scopes of position, fee,
and rebate evidence.

Operator-surface hardening update (2026-08-13 UTC): the canonical `python -m
weather.market.mm_live_pilot_cli` surface is limited to non-mutating preparation
and offline bundle verification. Its read-only identity-preparation
command derives the selected signature ID and refuses a structurally invalid
public manifest. Stage 0 and Stage 1 remain tested library functions and
require a separately reviewed, host-owned wrapper with fixed public scope; the
generic parser rejects both command names. A keyless doctor checks
the exact SDK, Windows resolver, credential-reference shapes/count, direct-secret
absence, funder identity, market identifiers, and budget without resolving any
credential value. All authentication is resolved in memory from Windows
Credential Manager references. Stage 0 preserves
the active-stream proof while binding the final journal hash after a clean stop.
Each Stage 1 library invocation has one submit capability, always attempts
account-wide cancel-all and exact-scope zero-position reconciliation, and emits
its PASS result only after cleanup succeeds. A separate offline command rereads
both results and journals to build the lifecycle bundle. This keeps the bounded
test reviewable without adding a generic mutation CLI; it does not enable the
ordinary maker runner.

Wallet-topology and credential-preparation update (2026-08-13
UTC): current official documentation distinguishes existing Gnosis Safe
signature type 2 from the new deposit-wallet/POLY_1271 type 3 flow. The pinned
SDK also gives them different signed-order identities: type 2 uses the EOA as
API owner and order signer with the distinct Safe as maker/funder; type 3 uses
the EOA as API owner and the distinct deposit wallet as order signer, maker,
and funder. The former equality gate was therefore wrong for type 3 and
insufficiently explicit for both. Stage 0, bootstrap, and full v0.5 promotion
now accept only these two exact topologies and recompute their address
relationships instead of trusting a generic consistency boolean.

The operator supplied an external credential file for a funded type-2 Safe.
Without emitting values or making a network request, an isolated environment
with the exact pinned SDK proved that the private key derives the declared EOA,
the SDK selects that EOA as the type-2 order signer, and the configured Safe
funder is distinct. The source file remains outside the repository and its ACL
was restricted to the current account, SYSTEM, and Administrators. No credential
was imported during the offline proof. A one-time credential importer is
prepared to validate the same topology, create only new Credential Manager
targets, roll back partial writes, ignore unused relayer/RPC/self-assertion
fields, and emit only a public reference manifest plus a secret-free receipt.
Live account authentication and every order mutation remain blocked until the
production execution host passes the fresh Stage 0 gates.

Public candidate-selection hardening update (2026-08-13 UTC): a bounded live
test can no longer depend on a hand-copied condition or stale token. The new
read-only `weather.market.mm_live_candidate_cli` binds a current validated
International economics snapshot to current CLOB books, limits selection to
built-in weather markets, requires positive fee and maker-rebate parameters,
central probability, a non-crossed tight book, and exact agreement between the
book and economics min-size/tick rules. Candidate-plan v0.2 additionally
streams and hashes the complete one-market paper quote tape and requires a
still-current successful `market_harvest` row for the exact condition/token.
Its expiry is the earlier of five minutes and the paper quote TTL. It emits an
explicitly non-authorizing, minimum-tick Stage 1 intent and ranked alternates;
`run_stage1` revalidates that binding before credential resolution. Book rule
drift, extreme or crossed books, stale economics, missing paper permission, and
no eligible candidate all block. The related location refresh now has a
`--metadata-only` mode so public preparation can write an external event
snapshot without rewriting tracked configuration. This selects the lifecycle
probe only; it does not implement the Stage 2 maker quote or prove reward
scoring, fills, rebates, or profit.

Refreshed-stack audit update (2026-08-14 UTC): the failed frozen stack was not
waived. Its live-pilot commits were replayed on current master plus the green
per-run International economics branch. Live-pilot budget/policy normalization
now has a dedicated pure owner module, returning the general run orchestrator
below the 2,000-line architecture ratchet. Capability issuance, lifecycle
execution, and lifecycle-bundle assembly each independently revalidate the
finite positive requested budget, isolated-wallet cap, 100 pUSD operator cap,
and 10 pUSD per-order cap instead of trusting upstream PASS booleans. The
focused live/economics/architecture matrix passes; an immutable exact-tip full
suite and reviewed production-host deployment remain mandatory before use.

## 2026-08-14 production execution-host decision

The operator designated the existing 16 GB production PC as the live
International execution host. The former separate-host transfer blocker is
therefore closed. The code, exact reviewed tip, runtime environment, capture
evidence, and credential references remain on one PC; host designation does
not by itself pass any exchange or risk gate.

The same checkout must recover capture and public execution supervision, pass
the keyless doctor, and use a newly reviewed fixed-scope wrapper sealed to the
fresh condition, token, budget, and output paths. The wrapper remains intentionally
unwritten until fresh candidate selection because prebuilding a parameterized
mutation surface would recreate the generic live CLI that this item forbids.

Current integration disposition (2026-08-14 UTC):

The predecessor refreshed Stage 0/1 tip and its stacked bounded Stage 2
successor each passed separate immutable exact-tip full suites. This Stage 0/1
branch has since merged current production and is therefore a new, unproved
exact tip; its scheduled full suite must pass before integration. The earlier
proofs establish software consistency only, not live evidence or integration
authority. Stage 0/1 must land first; Stage 2 must then merge current production
and pass a fresh suite on that combined tree before production-host use. The
two unchecked live-evidence bullets above remain open until a tiny real
lifecycle and paid-vs-predicted settlement/rebate record are reconciled without
weakening any gate or increasing any ceiling. Exact suite measurements live
only in `docs/operations/ESTABLISHED_FINDINGS.md` §§8k and 8n.

## 2026-08-15 current integration disposition

The refreshed International Stage 0/1 tip passed its immutable exact-tip suite,
merged through the guarded workflow, and is in production history. Continuous
public execution capture is also adopted. Those milestones retire the former
software-integration blocker but create no order authority and supply no
own-account fill, fee, rebate, position, or P&L evidence.

The paper-only market-harvest lane, unified official client, and pUSD payout-
asset contract now share one current-master cumulative parent. Focused tests and
the isolated real-wheel SDK contract pass. The first one-market paper attempt
failed closed on both the expected v0.2-to-v0.3 economics schema mismatch and a
missing model-independent CLOB-feature fallback. The parent now derives harvest
features directly from current public books without model rows. The attempt
emitted no quote permission and changed no live state; collect a fresh external
v0.3 snapshot and rerun after the protected window without accepting a baseline.
The cumulative parent still needs an immutable exact-tip full suite and guarded
integration. Bounded Stage 2 remains a successor and must be refreshed only
after that parent lands. The two live-evidence checklist bullets remain open
until the staged lifecycle is run on this PC under the
canonical pilot envelope.

The subsequent one-market retry proved the paper market-harvest route but did
not produce a safe Stage 1 candidate: candidate-plan v0.2 correctly refused the
late-day extreme books under its fixed midpoint interval. This closes no live
evidence checkbox and requires no code/risk relaxation. After parent
integration, candidate selection should be repeated from a fresh paper tick
only when a market naturally satisfies the existing gates. See
`docs/operations/ESTABLISHED_FINDINGS.md` section 8q for the sole quantitative
record.

## 2026-08-19 production disposition

The cumulative parent passed one exact-tip 18/18-chunk suite with 4,489 tests,
then merged through the guarded roll-sensitive path as
`3c326ac1c03b415877da33dc254b39d32f576de4`. All three core capture workers
recovered with current source identities and the merge was published through
`WeatherOneShotPush`. This lands the unified official client, pUSD contract,
paper harvest route, and keyless Stage 0/1 software. It does not provide order
authority, credentials, a safe current candidate, or any own-account evidence.

The fixed-scope Stage 2 successor did not integrate. Its focused host wrapper
resolved imports from production rather than its exact worktree, so the full
suite and guarded merge correctly refused. A corrected diagnostic passed its
73 focused tests, but a fresh exact-tip full-suite receipt remains mandatory.

## 2026-08-22 interrupt-safety cumulative disposition

Production remains at `cfdad9e5225f4dad86eaeddae7631893cd6c5350`. The exact
documentation closeout commit `e0d54db06699fc1c6e104dbdc3ccd4800cb16dd7`
and interrupt-cleanup commit `da32c0895bb5b40c842b35232ff266c7968d4439`
are preserved as ancestors of `codex/stage1-readiness-cumulative-20260822`.
That cumulative branch is pending, not landed, and has no live authority.

The cleanup change routes `KeyboardInterrupt` and other `BaseException` exits
through lifecycle and command cleanup, repeats cancel-all and exact-scope
zero-state reconciliation at the command boundary, emits type-only failure
evidence, and re-raises without retrying the submit. A forced process kill or
power loss still depends on the separately proved heartbeat-lapse path. Before
any Stage 0 or Stage 1 wrapper is sealed to production, the exact cumulative
tip must pass its own immutable full suite, guarded integration, capture
recovery, publication, and production-identity proof. Focused tests on either
parent commit are not a substitute. No exchange mutation occurred in preparing
this branch.

## 2026-08-23 production adoption

The exact cumulative source tip
`a6327ccf52499ed8d9ab0c34580fcd013ca7f094` passed its immutable integration
preflight and all 19/19 bounded suite chunks: 4,698 tests, zero failures,
errors, or skips. Guarded merge
`0af64ecf36287a8e88aa1f85cbfa2ff540adb03b` recovered all three core capture
workers and the execution-tape producer, then published with local and remote
master equal. The receipt explicitly grants
`NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY`.

Production now contains the interrupt-cleanup path, repository-owned
fixed-scope wrapper sealer, no-argument fixed-session launcher and runner, and
the pinned process-local SDK overlay contract. This closes the software and
production-adoption blocker only. The unchecked live-evidence bullets remain
open: no fresh safe candidate, production-bound Stage 0 identity/doctor,
authenticated bootstrap, supervised Stage 1 cancellation probes, order, fill,
fee, rebate, position, settlement, or P&L evidence exists. The old prepared
host templates must not substitute for a newly sealed current attempt.

## 2026-08-23 credential reconciliation repair

The owner-approved live-readiness closure subsequently landed at
`4feef39a44f920affcb05387a8882fb5f735cfa0` with capture and execution-tape
recovery plus remote acknowledgement. An attended credential-import attempt
then passed every offline source, signer, and topology check but refused before
mutation because one or more fixed Credential Manager entries already existed;
it wrote and overwrote zero entries.

The follow-up repair adds an explicit compare-only mode with a separate literal
confirmation. It requires all four fixed entries to exist and match the
independently retained source, reads and compares every value only in-process,
and never calls the writer or deleter. A versioned secret-free receipt
distinguishes four new writes from four exact existing-value verifications, and
the fixed-scope sealer accepts only either truthful all-four tuple. This local
vault proof remains separate from authenticated doctor, account, eligibility,
candidate, Stage 0/1, and live lifecycle evidence; no exchange call or order is
part of credential reconciliation.

Immutable attempt `credential-reconcile-0824-a1` stopped during its
deterministic integration preflight before the full suite or merge. The three
failed assertions represented two governance omissions in the cumulative tip:
the intentional process-local `eth_account` dependency boundary was absent
from the optional-import architecture allowlist, and the sealer's growth from
1,999 to 2,039 lines lacked the corresponding ownership entry, document row,
and warning-count ratchet. The attempt's exact tasks were closed and disabled;
production remained at
`4feef39a44f920affcb05387a8882fb5f735cfa0`, and no credential, exchange, or
order mutation occurred.

The reviewed `manual_reviewed_change` repair preserves the credential importer
and its pinned hash. It adds only the architecture allowlist entry and truthful
large-module ownership metadata, document row, and 23-module ratchet. The
original FAIL receipt remains immutable; tests and integration must run under
a fresh successor attempt before the compare-only reconciliation can be used.
