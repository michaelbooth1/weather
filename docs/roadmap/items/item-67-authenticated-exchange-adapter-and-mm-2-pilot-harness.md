# 67. Authenticated Exchange Adapter And MM-2 Pilot Harness [PARTIAL 2026-08-13 - BOUNDED INTERNATIONAL PILOT AUTHORIZED; GATES BLOCK]

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
- [x] Add report-side paid-vs-predicted reconciliation for maker rebates,
  liquidity rewards, redemptions, fees, pUSD/USDC balances, and settlement P&L
  before any size increase.
- [ ] Collect real paid-vs-predicted evidence from an eligible live account
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
global/US clients, real heartbeat/post-only/cancel-all probes against an
eligible account, authenticated account endpoint reads, redemptions, and final
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
eligible-account probes, user WebSocket lifecycle evidence, paid-vs-predicted
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
probes, user WebSocket lifecycle evidence from an eligible account, and actual
paid-vs-predicted payout/redemption/P&L snapshots.

## 2026-06-18 audit disposition

The Python audit found the software harness implemented through keyless safety,
signed request construction with injected signers/transports, live-gate
enforcement, read-only fixture reconciliation, pilot-report emission, and
financial reconciliation reporting. The unchecked MM-2 probe and
paid-vs-predicted boxes require an eligible live account, credentials kept
outside the repo, and real exchange lifecycle/account evidence. They remain
open deliberately; closing them without live-account artifacts would weaken the
acceptance criteria.

## 2026-06-24 evidence-only disposition

No live probe was run. The current host has no eligible live credential refs in
the environment:

- Polymarket US missing: `POLYMARKET_US_KEY_ID`,
  `POLYMARKET_US_SECRET_KEY_STORAGE_REF`.
- Polymarket global missing: `POLYMARKET_API_KEY`,
  `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`,
  `POLYMARKET_FUNDER_ADDRESS`, `POLYMARKET_PRIVATE_KEY_STORAGE_REF`.
- No forbidden direct secret env vars were present.

The existing evidence harness remains healthy:

- `python -m pytest -q tests\market\test_mm_exchange.py` -> 8 passed.

Because no eligible live account or external credential material is available,
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
  both an eligible `live-pilot` run folder and external credential references
  before live verbs can be enabled.

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
`mm_platform_verification_v0.4`. In addition to the prior API lifecycle and
secret-redaction proof, it is International-only and requires exact production
hosts, fresh content-bound and IP-redacted official physical geoblock evidence,
explicit real-location and no-circumvention confirmations, consistent
signature name/ID, valid private-key signer, order signer,
funder and API-key-owner addresses, an explicit wallet-identity consistency
proof, and the complete rotating dead-man heartbeat contract. The tracked
template remains fail-safe. Versions v0.2 and v0.3 are legacy and cannot pass a new
live-pilot preflight.

The former gate sequence was circular for a first-ever lifecycle order: full
platform verification required live fill/final-state and dead-man cancellation
evidence, while the ordinary live path required full platform verification.
`weather.market.mm_live_bootstrap` now defines the separate
`mm_platform_bootstrap_v0.1` read-only contract. It is International-only,
bound to one token and condition, expires within one hour, and requires wallet,
account, SDK, book, fee, a non-posting signed-order topology preview,
account-wide stream, heartbeat-chain, cancel-all-to-zero, budget, and
secret-hygiene proof. It can authorize only the
future dedicated Stage 1 lifecycle-probe command; the ordinary maker runner
does not consume it and still requires v0.4.

The exact SDK audit also found that `create_and_post_order` can perform two
network posts through its internal order-version refresh loop. The prepared
adapter therefore signs with `create_order` and invokes `post_order` exactly
once. A version mismatch fails closed and consumes the one-submit capability.

`weather.market.mm_live_lifecycle_probe` prepares the mutation core, and
`weather.market.mm_live_pilot_cli` exposes only its two bounded one-submit modes.
It accepts only a passing bootstrap gate for the exact
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

Physical-eligibility hardening update (2026-08-13 UTC): International is not a
synonym for eligible. The official endpoint returned `blocked=true`,
`country=CA`, `region=ON` from this production host, matching Polymarket's
documented Ontario restriction. The prepared path therefore cannot mutate from
this host. It rejects configured HTTP proxies, never retains the returned IP,
requires the operator's real-location/no-circumvention confirmations, embeds a
fresh content-bound response in Stage 0, rechecks country/region when issuing
the one-submit capability, and fetches once more after consuming that
capability immediately before submit. Work may continue here in read-only,
paper, research, and preparation modes; a real test must run on a genuinely
eligible physical host without VPN or proxy circumvention.

Operator-surface hardening update (2026-08-13 UTC): Stage 0 and the two distinct
Stage 1 lifecycle modes now have a canonical `python -m
weather.market.mm_live_pilot_cli` surface. Its read-only identity-preparation
command fetches the official geoblock response, discards the detected IP,
derives the selected signature ID, and refuses a blocked/proxied or structurally
invalid public manifest. The Stage 0/1 commands accept only public identifiers,
budget, confirmation literals, and new artifact paths. A keyless doctor checks
the exact SDK, Windows resolver, credential-reference shapes/count, direct-secret
absence, funder identity, market identifiers, and budget without resolving any
credential value. All authentication is resolved in memory from Windows
Credential Manager references. Stage 0 preserves
the active-stream proof while binding the final journal hash after a clean stop.
Each Stage 1 invocation has one submit capability, always attempts account-wide
cancel-all and exact-scope zero-position reconciliation, and emits its PASS
result only after cleanup succeeds. A separate offline command rereads both
results and journals to build the lifecycle bundle. This makes the bounded test
operator-executable on an eligible host; it does not enable the ordinary maker
runner and does not make the Ontario host eligible.
