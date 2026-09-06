# International Market-Making Live Pilot

Status: canonical runbook. This runbook records the operator's 2026-08-13
authorization to work toward a bounded International Polymarket live test. It
does not make a blocked gate pass and it never authorizes Polymarket US.

## Purpose and claim boundary

The first live session is an exchange-lifecycle probe, not a profitability
proof. It tests whether the production path can place only resting liquidity,
observe the authenticated order lifecycle, stop safely, and reconcile account
state. Profitability requires repeated maker fills and subsequent paid-rebate,
markout, position, and settlement reconciliation.
The claim boundary and frozen economics decision rule are preregistered in
[`INTERNATIONAL_MM_PILOT_PREREGISTRATION.md`](../research/INTERNATIONAL_MM_PILOT_PREREGISTRATION.md).

## Current production disposition

The portable execution-host extension, fixed-scope Stage 0/1 sealer, session
runner, process-local pinned SDK overlay, and interrupt-cleanup path are
integrated production software. The Stage 0 structural scope and Stage 1
lifecycle design below must be present on the exact source selected for the
session. Normally that authority is production-adopted canonical `master`;
the narrow pre-adoption portable exception is owned by
[portable source authority](PORTABLE_LIVE_EXECUTION_HOST.md#source-authority).
Reconcile an existing portable clone's reviewed changes before selecting or
changing its branch. Read the current adopted tip, exact-head CI/review,
operator authority, and prior attempt disposition from Git and
[`STATE_OF_PLAY.md`](STATE_OF_PLAY.md), not from a dated hash copied here.
Integration receipts grant no credential or live-exchange authority and do not
prove current execution-host qualification or a successful Stage 0/1 protocol.

**Stage 0/1 execution is currently HOLD until every action-time gate below
passes.** The explicit execution-host profile,
truthful Stage 0 authenticated-write confirmation contract, and canonical
fixed-session manifest builder are implemented by the fixed-scope software
described here. On adopted master, both profiles require
`HEAD == master == cached origin/master == live canonical refs/heads/master`.
`capture_colocated_v1` is master-only. If the current portable source decision
uses the named topic exception, require exact local `HEAD`/local branch/cached
branch/live branch equality plus synchronized ancestral master and the full
[source-authority contract](PORTABLE_LIVE_EXECUTION_HOST.md#source-authority).
The fixed-session manifest builder and dated Stage 0/1-only substitute-gate
decision below are preparation
only. Neither is temporal, credential, exchange-mutation, or trading
authorization.

The portable exception removes only master promotion. It does not make the
branch production-adopted or claim production-host integration, capture
recovery, or Scheduler state, and it does not remove any money, SDK,
credential, identity, geography, account, balance, allowance, zero-state,
order, cancellation, deadline, cleanup, or attended-confirmation gate.

### Stage-scoped candidate-gate redesign qualification

The stage-scoped replacement is implemented by the canonical Stage 0 scope and
Stage 1 lifecycle-plan modules. Naming a branch in code is not live authority:
do not use an exact tip for Stage 0 or Stage 1 until the test, review, publication,
exact-head CI, synchronized-ref, portable-update, and explicit exact-tip owner
authority steps in [`STATE_OF_PLAY.md`](STATE_OF_PLAY.md) pass. Code history
establishes that the fixed
`0.05` maximum book spread and `0.20-0.80` midpoint interval were introduced as
conservative pilot-selection heuristics. No measured optimization, loss model,
protocol rule, or venue rule established either value. They must not be called
optimal or safety invariants. The current venue-specific liquidity-reward
spread is separately collected in the economics snapshot and is not this
constant. The paper policy's separate `0.08` maximum harvest spread is also an
unvalidated Stage 2 experiment parameter; it is not Stage 0 safety evidence.

Relaxing a maker-quote spread rule can expose Stage 2 to thin or stale top
levels, unstable midpoint estimates, informed flow, rapid repricing, and loss
of reward eligibility. Those risks do not justify blocking Stage 0, which
submits no order. The direct Stage 1 lifecycle protections are fresh exact
book/rule evidence, a minimum-tick nonmarketable BUY, post-only enforcement,
one-submit capability, the fixed capital cap, attended deadlines, and final
cancel/reconciliation.

The replacement contract is:

- **Stage 0:** choose and bind a current built-in condition/token using
  generated event metadata, an exact plan-time Gamma rebind of active/closed
  event and full condition/token identity, and current structural book
  evidence. Best bid/ask, spread, and midpoint may rank otherwise valid scopes,
  but never exclude one.
  Economics acceptance, paper permission, reward/rebate eligibility, and a
  positive fee are not inputs or hard blocks.
- **Stage 1:** bind the same generated metadata plus plan-time Gamma identity
  rebind and the exact Stage 0 condition/token to a fresh lifecycle plan.
  Require the current book and official tick, neg-risk, and nonnegative fee rule, a minimum-tick
  nonmarketable post-only BUY whose minimum notional is at most 10 pUSD, plus
  the direct capital, geography, account, cancellation, and cleanup gates. A
  current fee of zero is valid lifecycle evidence, not proof of profitability.
  Do not import Stage 2 profitability heuristics as lifecycle safety.
- **Stage 2:** own quote-quality and economics thresholds. A hard numeric rule
  here must come from current venue evidence or a documented measured decision
  rule with explicit risks and review triggers.

The first-pilot numbers are classified as follows. None is an empirical
optimum unless a cited measurement says so:

| Value | Owner and classification | Current authority and review trigger |
| --- | --- | --- |
| `0.05` selector spread, `0.20-0.80` midpoint, and `0.08` paper harvest spread | Stage 2 experimental heuristics, introduced without a measured derivation | May rank or parameterize paper experiments. They have no Stage 0/1 authority. Replace or promote only after a preregistered spread-bucket fill, markout, settlement, and reward study. |
| 10 pUSD order/request and 100 pUSD test allocation | Explicit owner-approved first-test envelope; the owner authorized using the existing wallet on September 6 | Hard at every order boundary. The existing-wallet mode caps the test allocation, not total wallet cash. It authorizes only the sealed Stage 0/1 attempt: two single-submit BUY probes, each at most 10 pUSD, with a stop on any fill. The separate isolated-wallet mode retains its whole-balance ceiling. |
| 300-second Stage 0/1 plan | Derived session-containment bound | Hard and executable: 240-second portable session + 20-second cleanup reserve + at most 40 seconds consumed by preparation/revalidation. Composition requires at least 260 seconds remaining and sealing contains cleanup before expiry. Recalculate if any envelope changes or observed preparation latency approaches 40 seconds. |
| 15-second current-Gamma request timeout | Stage 0/1 plan-generation operational budget, not a venue rule or quote heuristic | Fail closed when exact current event identity cannot be obtained. It preserves room inside the enforced 40-second preparation margin for book/rule reads and composition; review against observed endpoint latency if it approaches the budget. |
| 5-second heartbeat cadence, 7.5-second acknowledgment lease, and 10-second market-rule lease | First-pilot operational safety margins from the August 13 lifecycle design | Hard only while an order lifecycle is active. Re-measure when venue heartbeat behavior changes or observed network/signing/rule latency approaches a margin. |
| 60-second geography receipt | Conservative action-time eligibility lease | Hard and rechecked at mutation/submit. Review if network egress or physical-location topology can change inside the lease, or if attended preparation latency approaches it. |
| 10-15-second dead-man observation window | Explicit Stage 1 experiment parameter, not a venue SLA | An observation outside the window makes that experiment inconclusive; it does not establish a universal exchange rule. Review after the first measured response or new official evidence. |
| 2-second post-cancel quiescence | Conservative late-fill observation parameter from the August 24/27 hardening | Keep for the first pilot, but do not treat exact equality as standalone safety proof. Semantic stream, REST order/trade, collateral, position, and zero-state reconciliation remain authoritative; replace with measured convergence evidence. |
| At least two scoped user-stream events | Unexplained protocol-shape heuristic from the August 24/27 hardening | Removed as authority. Event count remains telemetry; semantic placement, cancellation/no-trade, terminal REST, collateral, and zero-state evidence decide the result. |

Do not repair this defect by changing five cents to another guessed number.
The separate Stage 0 scope and Stage 1 lifecycle-plan gates now implement this
contract in the selected source. The commands below describe that
interface, but remain on HOLD for any exact tip that has not passed every
dynamic qualification and action-time gate described above. See
[`ESTABLISHED_FINDINGS.md`](ESTABLISHED_FINDINGS.md#8y-the-five-cent-live-candidate-spread-ceiling-is-an-unvalidated-pilot-heuristic).

**Geographic eligibility is an action-time fact, not a repository or timezone
inference.** This repository does not assert the operator's or execution host's
physical location. Polymarket blocks specified locations and forbids VPN,
proxy, or similar circumvention. Before any Stage 1 order, obtain a fresh
official geoblock result and an attended no-circumvention attestation; an
unblocked egress classification that disagrees with physical location is not
authority.
The protocol never solicits, accepts, or stores an operator-supplied city,
state/province, or country. It uses only the exact attended eligibility and
no-circumvention literal plus Polymarket's credential-free geoblock response.

Use International Polymarket only (`polymarket_global`). The live pilot must
reject every other platform identifier.

The current native trading and rebate settlement unit is `pUSD`. Stage 0,
Stage 1, and full platform verification must all bind that exact unit. Legacy
schema fields ending in `_usdc` remain compatibility names for one-dollar
amounts; they do not authorize reading a USDC.e balance as the trading
collateral balance or treating an unwrapped asset as pUSD.

## Pilot capital contract

`weather.market.mm_pilot_capital` owns the shared validation used by identity
preparation, the keyless doctor, sealing, Stage 0 collection/loading, Stage 1
capability issuance, uncached collateral reads and lifecycle bundle validation.
The current identity is v0.4 and bootstrap is v0.6; older versions remain
registered historical evidence and cannot authorize a fresh attempt.

For an existing wallet, the public declaration must contain
`pilot_capital_mode="existing_wallet_test_allocation"`,
`pilot_test_allocation_pusd=100`, `isolated_pilot_wallet=false`, and
`pilot_wallet_max_funding_usdc=null`. Mixed, missing, nonfinite or over-limit
contracts fail closed. Legacy `_usdc` funding fields retain their whole-wallet
meaning and are never silently reinterpreted as test allocations. The keyless
CLI uses `--test-allocation 100 --confirm-existing-wallet-allocation`;
`--wallet-cap 100 --confirm-isolated-wallet` selects the separate isolated mode.
Neither preparation path reads credentials or moves funds.

## Immutable pilot envelope

- The attended Stage 0/1 test may use an existing wallet with an explicit
  **100 pUSD testing allocation**. Its total cash may exceed that allocation.
  This is a software limit on this exact test, not a segregated subaccount or
  a claim that existing holdings are part of the test. Record actual cash
  separately; never label the existing wallet isolated.
- The first Stage 0/1 request is exactly **10 pUSD**. One sealed attempt permits
  at most two single-submit BUY probes, each at most 10 pUSD (at most 20 pUSD
  gross submitted notional across the attempt, below the 100 pUSD allocation).
  A fill or failed reconciliation stops the sequence. This allocation grants
  no repeat loop, general maker-run authority or Stage 2 promotion.
- The separate isolated-wallet contract still caps total funded cash at
  **100 pUSD**. Stage 2 and the ordinary live-pilot runner retain that contract
  and all existing readiness/risk gates; the Stage 0/1 allocation is not a
  substitute for those proofs.
- Exactly one weather market per run.
- Existing ceilings may be lowered but not raised: **25** daily loss, **25**
  event notional, **10** band notional, and **120 seconds** quote TTL.
  `weather.market.market_making_live_pilot` owns this mode-specific normalization;
  the general run orchestrator delegates to it before evaluating any gate.
- The Stage 0/1 lifecycle envelope is profile-bound. `capture_colocated_v1`
  retains a 120-second session envelope and `portable_execution_v1` uses a
  240-second session envelope. Each public Stage 0 scope or Stage 1 lifecycle
  plan lasts exactly 300 seconds: the portable maximum plus the 20-second
  cleanup reserve and at most 40 seconds for composition/revalidation.
  Composition enforces the 40-second maximum and both composition and sealing
  require cleanup to end before plan expiry. Recalculate the plan lease if any
  part of that envelope changes.
- Smallest current exchange-valid share size and current tick size, read from
  the selected book immediately before the order.
- Post-only limit orders only. No marketable retry after a post-only rejection.
- No naked sell. A sell requires verified owned outcome inventory; otherwise
  express the complementary side with a backed buy.
- No overnight or unattended first session. End with cancel-all plus an
  authenticated query proving zero open orders.
- For Stage 2, do not assume liquidity rewards. Model the current documented
  maker rebate only after market-level fee eligibility is verified. Treat an
  unpaid or sub-threshold estimate as unrealized. This is not a Stage 0/1 gate.

## Prerequisites

All must be current for the target date and selected market:

1. Continuous execution capture remains running on the dedicated capture PC
   and has produced rows. A `capture_colocated_v1` session validates that state
   locally. A `portable_execution_v1` session does not consume or claim remote
   capture-host health; its lifecycle receipt is therefore not simultaneous
   capture-health or streak evidence.
2. Generated `location_market_events` metadata proposes the target-date
   built-in event, condition, and ordered token map. Both plan generators
   rebind that full identity to a current Gamma response and require the event
   and every mapped market to remain active, open, and order-book enabled; an
   old generated file may be used only when that exact current comparison still
   passes. The plan retains the normalized status/identity contract, recomputed
   current and staged contract hashes, and a check timestamp no more than the
   already-budgeted 40-second preparation margin before plan creation. Its
   loader requires exact semantic equality with the separately bound staged
   metadata; a constrained plan must contain exactly one event proof. Stage 0
   additionally binds a current structural CLOB book. Stage 1
   binds the exact Stage 0 condition/token to a current book and official tick,
   neg-risk, and nonnegative fee rule. Neither
   stage requires economics acceptance, a paper run, the portable substrate
   preflight, spread/midpoint limits, reward/rebate eligibility, or a positive
   fee; those remain Stage 2/paper evidence.
3. Before the first lifecycle order, `mm_platform_bootstrap_v0.6` passes for
   the exact token and condition. This non-order, at-most-one-hour-old artifact
   proves the wallet identity and explicit capital contract, numeric collateral
   balance and allowance each backing the requested budget, a content-bound
   account snapshot, an observed zero open-order count, fresh pre-mutation
   geographic eligibility, current book/min size/tick/neg-risk, the current
   nonnegative fee rule (which may be zero), a non-posting signed-order preview bound to the exact EOA/API
   owner, order signer, funder/maker, signature type, and token (raw signature
   discarded), account-wide user stream, two current bodyless heartbeat
   acknowledgments,
   cancel-all-to-zero, SDK contract, and secret hygiene. It cannot authorize a
   general maker run.
4. Credential references are present outside the repository. The API key,
   API secret, passphrase, and private key must all enter by storage reference;
   their values are forbidden in environment variables, command lines, logs,
   config, or artifacts. The public funder address may be supplied directly.
   On a Windows execution host the prepared resolver is `wincred://`, backed by
   the current user's Windows Credential Manager generic credentials. Provision
   entries through the interactive Credential Manager UI or the one-time,
   outside-repository importer documented below; never put a secret in
   `cmdkey /pass`, PowerShell history, a scheduled-task argument, or a reference
   URI. The loader does not print target names or resolved values.
5. The official International CLOB client `polymarket-client==0.6.0` is
   supplied only by the sealed, validated process-local external SDK overlay
   and wrapped by a tested adapter; it is not installed into the shared
   production venv. Its pinned client owns post-only placement, CLOB account
   reads, cancellation, and dead-man heartbeats. The existing hand-built
   request-plan adapter remains diagnostic and cannot authorize capital.
   `SecureClient.create` may deploy a missing default deposit wallet, so the
   wrapper must first prove the exact supplied Safe/deposit wallet already
   exists through the public relayer `/deployed` endpoint. Placement stays
   disabled until authoritative user-event and position readers are present
   and explicitly verified, a bodyless `/heartbeats` request has returned the
   exact `{status: "ok"}` acknowledgment within 7.5 seconds, and matching
   book/min-size/tick/neg-risk/fee-rule endpoint evidence has been read within 10
   seconds.
6. **Dated Stage 0/1 readiness decision: approved 2026-08-23; exact Git
   authority must be proved from `STATE_OF_PLAY.md` and the live remote.** The general readiness
   prerequisite is circular for the evidence-generating probes because
   `mm_platform_verification_v0.6` embeds
   both Stage 1 lifecycle proofs. For Stage 0/1 only, the operator approved the
   following exact non-circular substitute gates: current exact-tip production
   inventory; public credential references; target-date generated event
   metadata and stage-specific current public book/rule evidence; fixed non-raisable
   10 pUSD order and 100 pUSD testing allocation (or isolated-wallet funding)
   caps; execution-host, clock, reboot, and
   workload-lease health plus capture/tape/streak health when using the
   colocated profile; zero unknown open orders and zero starting
   positions; successful Stage 0 bootstrap before Stage 1; fresh geographic
   eligibility; and every stage-specific, hash-bound attended confirmation.
   This decision is not self-executing and cannot clear the HOLD until the
   complete implementation receives exact-tip reproof. For the capture profile
   that means production-adopted master. For the portable profile, only the
   literal remote topic branch, exact tip, host, and principal currently
   authorized in [`STATE_OF_PLAY.md`](STATE_OF_PLAY.md) may substitute under
   the branch/master equality and ancestry contract above. A redesign tip has
   no such authority unless every dynamic qualification check passes. The
   ordinary maker-run live-readiness, target-date data-layer,
   production release, full risk, and v0.6 platform gates remain unchanged for
   Stage 2.
7. A simultaneous one-market paper counterfactual is required before Stage 2
   quote-economics claims, not before Stage 0 or Stage 1. The following command is only an interface
   illustration for a host that already owns the canonical default capture
   tree; it is **not** the portable-host command:

   ```text
   .\venv\Scripts\python.exe -m weather.market.market_making_run --date <YYYY-MM-DD> --budget-usdc 25 --mode paper-live-forward --permission-profile market_harvest --markets <market-id> --once
   ```

   On a clean portable executor, do not run that abbreviated form. A future
   Stage 2 attempt must use a reviewed attempt-local paper/economics procedure;
   do not insert those artifacts into a Stage 0 scope or Stage 1 lifecycle plan.

   `market_harvest` assembles rows from current event metadata, CLOB tokens,
   books, and features. When no prebuilt feature file exists, it projects the
   current midpoint, spread, depth, and age directly from the latest public
   book capture and uses only the latest token-registry capture; retained token
   history cannot duplicate current quote intents. It does not reintroduce
   model snapshot rows as the fallback.
   It retains active-event, source/watcher, information
   event, CLOB continuity/freshness, economics, minimum-size, tick, cadence,
   current-high, budget, and notional gates while omitting only model-row and
   model-freshness permission dependencies. Model promotion remains unchanged,
   model probability fields remain empty, assumed reward remains zero, and
   `live_trade_permission` is always false. Zero quote-permission rows block a
   maker-quote/economics claim; they do not block Stage 0 or Stage 1. Paper,
   economics-acceptance, drift, and substrate-preflight artifacts are
   Stage 2/paper-only and are absent from both plan schemas. Stage 0, account state,
   current market rules, the literal confirmation, and the one-submit adapter
   capability remain independent mutation gates.
8. Select exactly one immutable execution-host profile. For
   `capture_colocated_v1`, the complete plan-derived execution window
   **plus the fixed 20-second cooperative-cleanup reserve** must remain inside
   the target date and **[00:30, 09:00) America/Toronto**; 08:59:40 is the
   latest execution cutoff. For `portable_execution_v1`, the same bounded
   window and cleanup reserve must remain within one local execution date in
   the immutable plan's market timezone, and the market target date must
   be that execution date or its immediately following date. The capture PC's
   timetable is not a portable constraint. Both profiles hold the exclusive
   shared lease. The distinct
   admission-only workstation wrapper also holds the same host-global mutex,
   so recognized offline heavy work cannot overlap a launched portable stage;
   it is not a third live profile and creates no live evidence. The portable
   lane accepts only canonical attended International Stage 0/1 workloads and
   is refused on the dedicated capture host. Provision or relocate it only via
   [`PORTABLE_LIVE_EXECUTION_HOST.md`](PORTABLE_LIVE_EXECUTION_HOST.md).
9. Geographic eligibility passes immediately before credential resolution and
   again submit-adjacent for Stage 1. Query the official public
   `GET https://polymarket.com/api/geoblock` endpoint, retain only
   `blocked/country/region`, observation time, and a redacted decision hash
   (never the IP or a reversible IP commitment), and require `blocked=false`.
   Separately require the attended operator to
   attest that the operator and execution host are physically in an eligible
   location and that no VPN, proxy, remote-location service, or other
   circumvention is in use. An unavailable endpoint, `blocked=true`, a
   physically blocked location, or disagreement between the endpoint and the
   attended attestation is a hard stop. See the official
   [geographic-restrictions API](https://docs.polymarket.com/api-reference/geoblock)
   and [current geographic-restrictions policy](https://help.polymarket.com/en/articles/13364163-geographic-restrictions).

   The sealed implementation is
   `weather.market.mm_geographic_eligibility`. Each check sends an uncached,
   credential-free request to that exact endpoint and writes a create-only
   `mm_geographic_eligibility_receipt_v0.1` with a 60-second freshness window,
   the raw response byte count, a recomputable hash of the retained
   `blocked/country/region` decision, and a self-hash over the complete receipt.
   It validates the returned source address but never retains that address.
   The attended literal is
   `INTERNATIONAL_POLYMARKET_PHYSICALLY_PRESENT_IN_ELIGIBLE_JURISDICTION_NO_VPN_PROXY_REMOTE_HOST_OR_CIRCUMVENTION`.
   Refusing or mistyping it blocks before live mutation. Stage 0 writes distinct
   precredential and pre-mutation receipts; each Stage 1 mode writes distinct
   precredential and submit-adjacent receipts. All are sealed output paths,
   source-hash-bound execution artifacts. Any failed check spends its receipt
   namespace and requires review rather than an in-place overwrite. The sealed
   Stage 1 attestor returns the submit-adjacent PASS receipt to the lifecycle;
   after the fresh rules and collateral calls, the lifecycle recomputes its
   self-hash and freshness immediately before the order-submit boundary. A
   missing attestor, malformed receipt, or receipt that expires while those
   calls run blocks before `place_order`.

## Stage 0/1 preparation and launch sequence

The first attended test is **Stage 0 heartbeat/account-wide cancel-all, Stage 1
cancel-all, then Stage 1 dead-man**. Keep the exact **10 pUSD request and 100
pUSD testing allocation**, one market, and one minimum-size, minimum-tick, post-only
BUY per Stage 1 mode. All [pilot ceilings](#immutable-pilot-envelope) and
[prerequisites](#prerequisites) remain binding. This sequence locates the full
command blocks below; it does not grant live or Stage 2 authority.

**Prepare before the session without credentials:** reconcile and qualify the
chosen source, follow [host provisioning and the offline audit](PORTABLE_LIVE_EXECUTION_HOST.md),
audit the installed public SDK, and finish admitted heavy work. Prepare the
[private attempt namespace and public identity](#attempt-namespace-and-public-identity).
Retain the chosen event's public Gamma response and generate its host-local
[event metadata](#event-metadata-and-stage-discovery). These setup inputs do
not have the plans' 300-second lease; current Git, host, SDK, identity and event
binding still must pass at the session. Prepare the command blocks and review
their intended paths now; create expiring plans only when ready to consume them.

**At the attended session:**

1. Use the prepared, unspent attempt and the retained host/principal-bound v0.4
   [credential installation receipt](#credential-provisioning-and-fresh-comparison)
   and public reference manifest. A clean creation or exact comparison is valid
   provenance without an age expiry. Each live stage resolves the current vault
   entries and repeats signer/account authentication checks.
2. Run [discovery](#event-metadata-and-stage-discovery) through
   `weather.market.mm_live_stage0_scope`, then
   `weather.market.mm_live_stage1_lifecycle_plan` for that exact condition/token.
   Before their 300-second leases expire, build all three
   [fixed manifests](#fixed-session-manifests-and-launcher-review) with
   `weather.operations.international_live_session_launcher_sealer prepare-manifest`.
   Review each manifest and build-receipt hash independently, then use
   `prepare-launcher`. Finish this review before creating any live plan.
3. With explicit current live authority, run the
   [fresh Stage 0 scope and reviewed no-argument launcher](#fresh-stage-0-scope-and-attended-launch)
   as one uninterrupted block. Use only the manifest's staged metadata and
   exact selected condition/token. Stage 0 submits no order; its authenticated
   heartbeat and account-wide cancel-all writes require the attended literals.
4. Only after Stage 0 passes, invoke the
   [fresh Stage 1 helper](#fresh-stage-1-plans-and-attended-launches) for
   `stage1_cancel_all`, then `stage1_dead_man`. Each helper creates a separate
   current lifecycle plan immediately before its reviewed launcher. The
   bootstrap must remain current; every unknown state, failed receipt or
   unexpected fill stops the attempt and enters reconciliation.
5. After both modes pass, construct the
   [offline lifecycle bundle](#offline-stage-1-lifecycle-bundle) with
   `weather.market.mm_live_pilot_cli bundle`. Neither a lifecycle PASS nor
   zero-fee acceptance qualifies settlement accounting or maker economics.

**The live-plan bottleneck is 40 seconds, not five minutes of operator time.**
For portable execution, a 300-second plan must leave at least 260 seconds at
composition: the fixed 240-second session plus 20-second cleanup. Its clock
starts after the current Gamma rebind; subsequent book/rule reads and process
startup consume the margin before composition begins. Complete human review
before the selector, then flow directly into the launcher. Later 180-second
launch, 120-second precredential and 60-second premutation reserves are
additional checks, not extensions. Preserve any spent namespace; a failed or
late attempt needs review and a new namespace, never edited timestamps or a
larger guessed limit. A backup market requires fresh discovery and three new
manifests. The current date, setup time and selected event belong in the
operator plan linked from [`STATE_OF_PLAY.md`](STATE_OF_PLAY.md).

The current Gamma plan contract verifies identity/status and ordered
condition/token mapping; it does not parse the event's full settlement-source
hierarchy. Retain and review the actual venue rules separately. A venue rule
that names NOAA first and WU only as a fallback is not equivalent to the
configured WU settlement proxy. Record that distinction without relabeling WU
evidence or treating a lifecycle PASS as settlement/model qualification. Stage
0 submits no order; an unexpected Stage 1 fill is a stop and reconciliation
outcome, not a successful no-fill lifecycle test.

## Staged protocol

### Stage 0: no-order account proof

Stage 0 never submits an order, but it does send authenticated heartbeat and
cancel-all/cleanup writes. Its v0.2 command, v0.7 execution, and v0.4 session-run
receipts therefore record `order_submit_attempted=false` separately from
`authenticated_exchange_write_attempted=true`; generic exchange mutation is
also true. Calling Stage 0 fully read-only is incorrect.

- Fill the public `mm_stage0_client_identity_v0.4` manifest. It binds only the
  International platform, chain, pinned SDK, public wallet topology,
  explicit existing-wallet test allocation or isolated-wallet funding cap,
  and the literal
  `INTERNATIONAL_POLYMARKET_STAGE0_HEARTBEAT_AND_ACCOUNT_WIDE_CANCEL_ALL_NO_ORDER`.
  The literal means no order submit while allowing the required authenticated
  heartbeat and unconditional account-wide cancel-all cleanup writes; it does
  not mean read-only. The manifest exists to
  construct the authenticated client needed to collect Stage 0; it is not
  evidence that any account check passed and cannot authorize an order.
- Authenticate and subscribe to the entire user account stream.
- Require the reader thread to remain active. A historical PONG from a stopped
  or failed reader is not liveness, and ordinary account events do not satisfy
  the independent server-PONG deadline.
- Query balance, allowance, positions, and open orders.
- Require no unknown open orders. If any exist, stop and reconcile them.
- Require an exact-condition position query and zero starting outcome inventory.
- Revalidate the chosen active event and full condition/token map against
  current Gamma, then bind the chosen condition/token plus current book
  identity, minimum order size, tick size, and neg-risk state immediately
  before mutation. Best bid/ask, spread, midpoint, fee, reward, and economics
  do not authorize or block this no-order proof.

The Stage 0 command receipt retains only allowlisted bootstrap phase names,
never raw SDK exception text or response bodies. It records the authenticated
account-wide user-stream subscription separately from per-operation heartbeat
and cancel-all attempt counts. `exchange_mutation_attempted` becomes true only
at one of those REST mutation call boundaries; a context or authenticated
WebSocket subscription by itself does not claim that an account mutation was
attempted. A failed pre-mutation run therefore identifies its last entered
read/check phase while preserving zero heartbeat, cancel-all, and order counts.
The command receipt is canonical for these facts and the fixed wrapper copies
them into its execution receipt. The session runner validates those copies
against the canonical command receipt and carries them into its child-execution
facts. This is an additive tightening of command schema v0.2: a historical v0.2
PASS receipt without the complete phase, user subscription fact, and exact
`heartbeat=2` / `cancel_all=1` counts is not an eligible Stage 1 predecessor.

### Stage 1: dead-man and cancel proof

- Start the exchange heartbeat and require acknowledged 5-second cadence.
- Send the current bodyless `POST /heartbeats`; every response must equal
  `{status: "ok"}`. A malformed acknowledgment or response older than 7.5
  seconds disarms placement.
- Submit one minimum-tick, smallest-valid, nonmarketable post-only BUY with
  notional no more than 10 pUSD. If an ask exists, the minimum tick must remain
  strictly below it; do not derive safety from midpoint or spread.
- After the pre-submit host attestor, force an uncached authenticated collateral
  balance/allowance read. The balance and minimum allowance must each back the
  exact 10 pUSD request. Only the isolated-wallet mode additionally caps the
  entire balance; existing-wallet mode validates the separately declared
  testing allocation without capping cash held for other purposes. Record the normalized snapshot hash before
  submit, refresh again after cancellation, and require exact balance/allowance
  hash equality for a no-fill result.
- Require both the placement response and authenticated stream/open-order
  observation.
- Treat every scoped trade lifecycle state, including `MATCHED`, `MINED`, and
  `RETRYING`, as an unexpected Stage 1 outcome. Send cancel-all, reconcile, and
  stop; zero positions from a potentially lagging account API is not sufficient
  no-fill evidence.
- A cancellation event is terminal no-fill evidence only when it carries an
  exact zero `size_matched`. Missing, invalid, or nonzero matched size fails.
  Continue observing the authoritative stream for a bounded post-cancel
  quiescence interval, then require the authenticated REST order to be terminal
  with zero matched size and no associated trade, plus an exact-scope account
  trade listing with no row for the order.
- Continue the bodyless heartbeat at no more than five-second intervals during
  placement and observation. Before either cancellation proof, acknowledge one
  fresh heartbeat and prove the order is still open. Otherwise a slow
  observation could let the dead-man timer cancel the order and falsely credit
  cancel-all.
- The immediate response must be successful, carry an order ID, report `live`,
  and carry no trade IDs or transaction hashes. Any other response is an
  ambiguous or taker-like outcome: send cancel-all, reconcile, and stop.
- Intentionally stop heartbeats once from that fresh acknowledgment and probe
  for automatic cancellation no earlier than 10 seconds and no later than 15
  seconds, then query until the order is absent. This is a fail-closed empirical
  lifecycle check, not a guaranteed current venue SLA: the current official
  heartbeat endpoint documents the bodyless request and acknowledgment but
  omits a cancellation timeout, while the official agent-skills guidance still
  states 10 seconds plus a five-second buffer alongside obsolete heartbeat-ID
  examples. If the 10-15 second observation is not proven, cancel all,
  reconcile, stop, and do not let the attempt authorize Stage 2.
- Repeat with one order, invoke cancel-all, and require zero open orders.

This stage is a successful live test only if no fill occurs and every required
stream, REST, collateral, cancellation, and final-state proof passes.

After both distinct probes pass, construct
`mm_stage1_lifecycle_bundle_v0.3` with
`weather.market.mm_live_lifecycle_probe.build_stage1_lifecycle_bundle`. The
builder rereads both lifecycle journals and both final authenticated user-stream
journals, verifies their hashes and scoped cancellation rows, requires distinct
journal files and order IDs, and derives the no-fill,
cancel-all, and heartbeat-lapse facts. It independently requires the exact
10 pUSD bootstrap request, a test capital limit no higher than 100 pUSD, and each
reported order at or below 10 pUSD; upstream PASS booleans do not substitute
for these numeric checks. Do not hand-author those facts. The tracked bundle
template is deliberately fail-safe.

Stage 1 is the only order mutation allowed from the bootstrap artifact. Its
completed, content-bound lifecycle bundle upgrades platform proof to
`mm_platform_verification_v0.6`. The ordinary `market_making_run` live-pilot
path continues to require that stronger artifact and must never accept the
bootstrap artifact. Version v0.6 embeds the bundle and its SHA-256, rechecks
the two probe identities and budgets, and requires its flattened private-stream,
cancel-all, and heartbeat claims to match the bundle's derived facts. The
fail-closed `weather.market.mm_live_pilot_cli` preparation surface exposes only
identity preparation, the keyless doctor, and offline bundle construction.
Exchange-mutating Stage 0 and Stage 1 remain library boundaries for a separately
reviewed, host-owned fixed-scope wrapper; the generic CLI cannot invoke
them. Those library boundaries wire the prepared bootstrap collector and
lifecycle orchestrator to credential-by-reference loading, the pinned official
client, the account-wide user stream, and the exact position reader. Stage 1
requires the literal confirmation
`INTERNATIONAL_POLYMARKET_STAGE1_LIFECYCLE_PROBE`, a passing bootstrap bound to
the exact adapter funder, condition, token, and SDK, zero starting orders, and
one cancellation mode per run. Every starting, ending, and failure-cleanup
position check must carry the exact maker/condition request URL, HTTP status,
and response hash; an unbound empty list is not zero-position evidence.
The upgraded proof may satisfy the private-stream lifecycle requirement with a
verified no-fill path: REST zero starting orders, authenticated placement and
cancellation events with zero matched size, a bounded post-cancel quiescence
interval, terminal zero-match REST order and account-trade reconciliation,
absence of every scoped trade lifecycle event in the final stream journals,
zero ending orders, and zero exact-scope positions. It
must not invent an initial WebSocket order snapshot, which the protocol does
not document, and it does not claim that a fill path has been tested. Actual
fill, settlement, fee, and payout evidence remains a Stage 3 requirement.
The capability permits exactly one network submit and is consumed before the
SDK call, so
Stage 0, the ordinary runner, or a retry after
an ambiguous response cannot call the adapter's order method directly.
The adapter also clamps its effective per-order notional limit to **10 pUSD**
even if a direct library caller requests more; callers may only lower it.
Capability issuance and the lifecycle executor independently revalidate the
finite positive requested budget, explicit capital contract, and 100 pUSD operator
ceiling before any order mutation.
It also requires a new, non-existing journal path. Before placement it writes
and flushes the authorization, bootstrap hash, exact intent, and budget; after
placement it appends exchange observation, cancellation, zero-open-order, and
terminal-stream events. Success also requires zero ending positions. A failed
phase records separate zero-open-order and zero-position cleanup verdicts plus
only its exception type, never raw SDK exception text or credentials. The returned
result binds the completed journal SHA-256. A missing, unwritable, reused, or
later modified journal prevents bundle construction.
`weather.market.mm_credentials` prepares the reference resolver and pinned
client factory. The factory accepts only the narrow public Stage 0 identity
manifest; requiring the later observed bootstrap here would create an
impossible dependency cycle. The returned raw SDK client is still not order
authorization: only `weather.market.mm_live_lifecycle_probe`, with a passing
observed bootstrap and its separate literal confirmation, may perform Stage 1.
`weather.market.mm_credential_import_cli` is the separate one-time migration
boundary for an already supplied external credential file. It is not imported
by the live runner and cannot authorize an order.

### Execution-host preparation

The final sequence runs from one exact remote-synchronized source containing
the reviewed Stage 0 scope and Stage 1 lifecycle design. Use adopted master on
the dedicated capture PC under `capture_colocated_v1`; on a separately
provisioned PC under `portable_execution_v1`, use clean adopted master or the
currently authorized named topic under
[portable source authority](PORTABLE_LIVE_EXECUTION_HOST.md#source-authority). Follow
[`PORTABLE_LIVE_EXECUTION_HOST.md`](PORTABLE_LIVE_EXECUTION_HOST.md) for every
second-PC deployment or later relocation. Stage 0/1 event metadata, structural
scope/lifecycle plans, credentials, and attempt manifests must be regenerated
on the chosen execution host. Stage 2 economics and paper evidence are separate
and must also be regenerated there when that stage is authorized. Never put a secret value in the
command line, environment, identity manifest, output path, or shell history.

For `capture_colocated_v1`, plan the entire plan-derived execution window
and fixed 20-second cleanup reserve inside **[00:30, 09:00)
America/Toronto**; 08:59:40 is the latest execution cutoff, and no heavy job may
overlap. After boot and network recovery, prove all capture workers and the
public execution-tape producer recovered. For `portable_execution_v1`, the
execution and cleanup tail may run while the target is the selected market's
current or immediately following local date, but it must remain within one
market-local execution date. The host/principal must match the tracked active
assignment and pass its offline execution-only status before identity or
credential preparation. Recognized
heavy work on that PC must run through `scripts/ops/workstation_heavy.ps1`.
The wrapper and portable launcher each own their full child tree in a kill-on-
close Windows Job and contend for the same host-global mutex. Finish heavy work
before sealing to avoid spending an inert reviewed attempt; the mechanical
exclusion begins when either compliant runtime acquires the mutex and lasts
through complete child-tree cleanup. An obsolete or manually bypassed launcher
is not made compliant by this protocol.
For both profiles, log in as the Windows user who owns Credential Manager,
clear pending reboot state, and ensure no other local live stage holds the
lease. On master, both profiles must prove
`HEAD == master == cached origin/master == live canonical refs/heads/master`.
On the portable topic exception, require the complete branch equality and
synchronized-master ancestry contract in
[source authority](PORTABLE_LIVE_EXECUTION_HOST.md#source-authority).
The portable profile must also match the exact tracked host/principal and the
operator-recorded reviewed, exact-head CI-green authorization. Do not trade
merely because Windows restarted successfully or because a branch was pushed.

Do not continue merely because a public endpoint classifies the host's egress
as unblocked. Eligibility also follows the attended operator's and execution
host's real physical location. A session in a blocked location must stop;
VPN/proxy/location circumvention is not an allowed workaround.

After that host audit, prepare the public identity and one target-date
event-metadata snapshot on the selected host. The generator below may run
before credential setup. Select the retained public credential receipt/reference
sources for an existing installation, or provision a new installation as below;
only after those pass, discover a structural Stage
0 scope and derive a Stage 1 lifecycle plan for that exact condition/token.
Run all three manifest builds before the discovery plans' 300-second leases
expire. The
canonical keyless doctor runs later, only inside each sealed wrapper. Do not
hand-pick a condition/token pair or retain one from a prior day.

The `--metadata-only` refresh leaves the tracked location registry byte-for-byte
unchanged. Both selectors are public, authenticate nowhere, make no exchange
mutation, and emit non-authorizing self-hashed plans. Spread/midpoint and paper
or economics artifacts are not accepted by either CLI.

#### Attempt namespace and public identity

```powershell
$ErrorActionPreference = "Stop"
function Get-VerifiedPilotLocalPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  $suppliedRoot = [IO.Path]::GetPathRoot($Path)
  if (-not [IO.Path]::IsPathRooted($Path) -or
      $suppliedRoot -cnotmatch '\A[A-Za-z]:\\\z') {
    throw "live-pilot paths must be absolute local-drive paths"
  }
  $fullPath = [IO.Path]::GetFullPath($Path)
  $pathRoot = [IO.Path]::GetPathRoot($fullPath)
  $drive = [IO.DriveInfo]::new($pathRoot)
  if ($drive.DriveType -notin @(
      [IO.DriveType]::Fixed,
      [IO.DriveType]::Removable
    )) {
    throw "live-pilot paths must use fixed or removable local media"
  }
  $cursor = $pathRoot
  foreach ($component in $fullPath.Substring($pathRoot.Length).Split(
      [char[]]@(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
      ),
      [StringSplitOptions]::RemoveEmptyEntries
    )) {
    $cursor = Join-Path $cursor $component
    if (-not (Test-Path -LiteralPath $cursor)) { break }
    $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "live-pilot path contains a redirected entry"
    }
  }
  return $fullPath
}
$pilotTargetDate = "replace-with-target-date"
$pilotExecutionHostProfile = "portable_execution_v1" # or capture_colocated_v1
if ($pilotExecutionHostProfile -eq "portable_execution_v1") {
  $pilotExpectedSessionSeconds = 240
} elseif ($pilotExecutionHostProfile -eq "capture_colocated_v1") {
  $pilotExpectedSessionSeconds = 120
} else {
  throw "unsupported execution-host profile"
}
$pilotAttemptId = "pilot-" + [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$pilotLocalApplicationData = [Environment]::GetFolderPath("LocalApplicationData")
if ([string]::IsNullOrWhiteSpace($pilotLocalApplicationData) -or
    -not [IO.Path]::IsPathRooted($pilotLocalApplicationData) -or
    [IO.Path]::GetPathRoot($pilotLocalApplicationData) -cnotmatch
      '\A[A-Za-z]:\\\z') {
  throw "current-user local application-data path is unavailable"
}
$pilotStateRoot = Get-VerifiedPilotLocalPath (
  # Keep this root intentionally short. Snapshot CAS filenames include the
  # complete event slug and a SHA-256 digest, and supported Windows hosts may
  # still enforce the legacy 260-character filesystem limit.
  Join-Path $pilotLocalApplicationData "WLive"
)
$null = New-Item -ItemType Directory -Path $pilotStateRoot -Force `
  -ErrorAction Stop
$pilotStateRoot = Get-VerifiedPilotLocalPath $pilotStateRoot
$pilotPublicRoot = Join-Path $pilotStateRoot "public"
$pilotAttemptsParent = Join-Path $pilotStateRoot "attempts" # init-attempt validates it
$pilotAttemptRoot = Join-Path $pilotAttemptsParent $pilotAttemptId
$pilotEventMetadata = Join-Path $pilotPublicRoot ($pilotAttemptId + "-location-market-events.json")
$pilotStage0DiscoveryPlan = Join-Path $pilotPublicRoot ($pilotAttemptId + "-stage0-discovery.json")
$pilotStage1DiscoveryPlan = Join-Path $pilotPublicRoot ($pilotAttemptId + "-stage1-discovery.json")
$pilotIdentitySource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-identity.json")
$pilotIdentityReceipt = Join-Path $pilotPublicRoot ($pilotAttemptId + "-identity-receipt.json")
$pilotCredentialProvisioningManifest = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-provisioning-references.json")
$pilotCredentialProvisioningReceipt = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-provisioning-receipt.json")
$pilotCredentialManifestSource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-verified-references.json")
$pilotCredentialReceiptSource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-verified-receipt.json")
New-Item -ItemType Directory -Path $pilotPublicRoot -Force | Out-Null
New-Item -ItemType Directory -Path $pilotAttemptsParent -Force | Out-Null
$pilotPublicRoot = Get-VerifiedPilotLocalPath $pilotPublicRoot
$pilotAttemptsParent = Get-VerifiedPilotLocalPath $pilotAttemptsParent
$attemptInit = .\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer init-attempt `
  --attempt-root $pilotAttemptRoot | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $attemptInit.status -ne "PASS") {
  throw "private fixed-session attempt initialization blocked"
}
```

Prepare the public identity now, before starting the expiring discovery
sequence. The command derives the numeric signature ID and writes no identity
if any public gate fails. Only these two documented topologies are accepted:

| Wallet class | Signature | Private-key/API client signer | Signed-order signer field | Funder/maker |
| --- | --- | --- | --- | --- |
| Existing Gnosis Safe | `POLY_GNOSIS_SAFE` / `2` | private-key EOA | same EOA | distinct Safe |
| New deposit wallet | `POLY_1271` / `3` | private-key EOA | deposit wallet | same deposit wallet |

The supplied funded-wallet configuration declares the first topology. Offline
validation on 2026-08-13 with the exact pinned SDK proved that its private key
derives its public EOA, that the SDK selects that EOA as the type-2 order signer,
and that the configured Safe funder is distinct. This is not exchange
authentication or order evidence; Stage 0 must still prove it against live
account reads on the selected execution host. Do not switch topology after a failed probe:

```powershell
$ErrorActionPreference = "Stop"
$pilotFunderAddress = "replace-with-public-funder-address"
$pilotWalletType = "gnosis_safe"
$pilotSignatureType = "POLY_GNOSIS_SAFE"

$identityPreparationOutput = .\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli prepare-identity `
  --funder-address $pilotFunderAddress `
  --wallet-type $pilotWalletType `
  --signature-type $pilotSignatureType `
  --budget 10 `
  --test-allocation 100 `
  --identity-out $pilotIdentitySource `
  --receipt-out $pilotIdentityReceipt `
  --confirm-international-platform `
  --confirm-existing-wallet-allocation `
  --confirmation INTERNATIONAL_POLYMARKET_PREPARE_STAGE0_IDENTITY
$identityPreparationExit = $LASTEXITCODE
$identityPreparation = $identityPreparationOutput |
  ConvertFrom-Json -ErrorAction Stop
if ($identityPreparationExit -ne 0 -or
    $identityPreparation.status -cne "PASS") {
  throw "public identity preparation blocked"
}
```

#### Credential provisioning and fresh comparison

**Normal retries require no backup file, import, or repeated comparison.**
Select the existing public receipt
and reference manifest for this Windows installation and token principal:

```powershell
$pilotCredentialManifestSource = Get-VerifiedPilotLocalPath "replace-with-retained-public-reference-manifest-json"
$pilotCredentialReceiptSource = Get-VerifiedPilotLocalPath "replace-with-retained-public-installation-receipt-json"
```

Continue at [event metadata and stage discovery](#event-metadata-and-stage-discovery).
The builder and sealers validate these files and bind their unchanged bytes to
the new attempt. No credential value is read during this public preparation.

The v0.4 receipt is **installation provenance**, not a claim about today's vault
contents or exchange access. Both exact clean tuples below are accepted. Keep
the original timestamp; a valid timezone-aware timestamp must not be in the
future. Age alone never invalidates it. Earlier receipt versions lacking the
host/principal binding remain historical audit inputs and cannot authorize
live preparation.

At every Stage 0/1 launch, the current user resolves all four vault entries.
The private key must derive the sealed public signer, and the client must match
the funder and wallet/signature type. Stage 0's authenticated collateral and
open-order reads precede its heartbeat/cancel sequence. Stage 1 repeats the
authenticated open-order query before obtaining a submission capability, and
refreshes collateral before submission. Rejected or missing credentials cannot
be replaced by an old PASS. Polymarket's [authentication contract](https://docs.polymarket.com/getting-started/api#authentication)
binds private CLOB requests to the signer address and current API credentials;
it is those requests that establish current access.

The September 6 credential-rule review separates the risks as follows:

| Rule | Decision and reason |
| --- | --- |
| Two-hour installation-receipt expiry | Removed. No protocol or measured basis was established for that interval; an old receipt cannot prove current authentication, and a recent one cannot replace it. |
| Comparison immediately after clean creation | Removed. The successful importer already validates the source and records the complete creation result. |
| Host/principal binding and exact creation/comparison tuple | Kept. Credential Manager storage belongs to that Windows installation/user, and partial writes, rollback or a different installation do not establish its provenance. |
| Current signer/funder/type and authenticated account checks | Kept at each launch. They detect the wrong wallet, absent or revoked credentials and account state that changed since an earlier success. |
| Protected secret storage and explicit recovery | Kept. Routine launches consume references; backups and credential replacement remain separate deliberate operations. |
| New attempt, source/host binding, current market/geography, deadlines and exclusive live workload | Kept within their owning contracts. They prevent consumed authority from being replayed, stale identities/rules from being used, and execution from overlapping work that could prevent cleanup. |
| 100 pUSD allocation, 10 pUSD order limit and stop-on-fill | Kept as the operator's explicit test envelope, not an empirical optimum. |

**Setup or recovery only:** after identity preparation passes, create the four
secret values as Windows Credential Manager generic credentials on a new
installation, or explicitly compare a retained source when investigating an
existing installation. Never recover by automatically overwriting vault entries.
If an external source file is used, keep it outside
the repository and remove inherited broad ACLs. The importer validates the
private key/address and exact wallet/signature topology, refuses existing fixed
targets, rolls back partial writes, rejects unrelated relayer/RPC/live-flag
fields, and emits only a public reference manifest and secret-free receipt. It
activates the same complete hash-pinned process-local SDK overlay used by the
live wrappers before deriving the signer; the shared production environment
intentionally does not supply `eth_account`.

Create a dedicated source containing exactly these nine keys. Do not copy the
project `.env`: unrelated keys, duplicate keys, empty values, and shell-quoted
values are deliberately rejected. Replace every placeholder with one
unquoted, non-empty value; the values shown here are names/placeholders only:

```text
POLYMM_API_KEY=<api-key>
POLYMM_API_SECRET=<api-secret>
POLYMM_API_PASSPHRASE=<api-passphrase>
POLYMM_PRIVATE_KEY=<private-key>
POLYMM_CLOB_HOST=https://clob.polymarket.com
POLYMM_CHAIN_ID=137
POLYMM_WALLET_ADDRESS=<public-signer-address>
POLYMM_FUNDER_ADDRESS=<public-funder-address>
POLYMM_SIGNATURE_TYPE=POLY_GNOSIS_SAFE
```

For the alternate deposit-wallet topology, use its reviewed public addresses
and `POLYMM_SIGNATURE_TYPE=POLY_1271`. Save the nine-line file as UTF-8 (a BOM
is accepted); Windows PowerShell 5.1's default UTF-16 output is not accepted.
Before passing `--confirm-source-acl-private`, create one dedicated
non-reparse directory, remove inherited entries from both it and the file, and
verify that every effective allow entry belongs only to the current token user,
LocalSystem, or local Administrators. This rejects broad read access as well as
broad write. The importer independently rejects any redirected ancestor and
reads one retained, identity-checked source generation:

```powershell
$ErrorActionPreference = "Stop"
$credentialParent = Join-Path $pilotStateRoot "private"
New-Item -ItemType Directory -Path $credentialParent -Force -ErrorAction Stop |
  Out-Null
$credentialParent = Get-VerifiedPilotLocalPath $credentialParent
$credentialRoot = Join-Path $credentialParent (
  "weather-live-credential-source-" + $pilotAttemptId
)
$null = New-Item -ItemType Directory -Path $credentialRoot -ErrorAction Stop
$credentialRoot = Get-VerifiedPilotLocalPath $credentialRoot
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$null = & icacls.exe $credentialRoot /inheritance:r /grant:r `
  "*${currentSid}:(OI)(CI)(F)" "*S-1-5-18:(OI)(CI)(F)" `
  "*S-1-5-32-544:(OI)(CI)(F)"
if ($LASTEXITCODE -ne 0) { throw "could not install private source-directory ACLs" }
$credentialSource = Join-Path $credentialRoot "pilot.env.txt"
# Create the exact nine-line file in a trusted editor, save it as UTF-8, then
# continue only after this check.
if (-not (Test-Path -LiteralPath $credentialSource -PathType Leaf)) {
  throw "credential source file is absent"
}
$null = & icacls.exe $credentialSource /inheritance:r
if ($LASTEXITCODE -ne 0) { throw "could not remove inherited credential ACLs" }
$null = & icacls.exe $credentialSource /grant:r `
  "*${currentSid}:(R,W)" "*S-1-5-18:(F)" "*S-1-5-32-544:(F)"
if ($LASTEXITCODE -ne 0) { throw "could not install private credential ACLs" }
$allowedSids = @($currentSid, "S-1-5-18", "S-1-5-32-544")
$unexpectedReaders = @(
  foreach ($aclPath in @($credentialRoot, $credentialSource)) {
    (Get-Acl -LiteralPath $aclPath).Access | ForEach-Object {
      $sid = $_.IdentityReference.Translate(
        [Security.Principal.SecurityIdentifier]
      ).Value
      if (
        $_.AccessControlType -eq "Allow" -and
        $sid -notin $allowedSids
      ) { "$aclPath => $sid" }
    }
  }
)
if ($unexpectedReaders.Count -ne 0) {
  throw "credential source has a non-private allow ACL"
}
$currentUserCanRead = @(
  (Get-Acl -LiteralPath $credentialSource).Access | Where-Object {
    $_.AccessControlType -eq "Allow" -and
    $_.IdentityReference.Translate(
      [Security.Principal.SecurityIdentifier]
    ).Value -ceq $currentSid -and
    ($_.FileSystemRights -band
      [Security.AccessControl.FileSystemRights]::Read) -ne 0
  }
).Count -gt 0
if (-not $currentUserCanRead) {
  throw "current token user cannot read the credential source"
}
```

The following blocks are for setup/recovery, not normal retries. Choose the
provisioning branch before executing it. Set the Boolean below to
`$true` only for a new host/principal whose four fixed targets are known empty.
Set it to `$false` for an explicitly reviewed comparison of an existing
installation. Never turn
a generic create failure into the reuse branch; stop and review it.

```powershell
$ErrorActionPreference = "Stop"
$provisionNewCredentialTargets = $true # reviewed choice; do not infer from failure
if ($provisionNewCredentialTargets) {
  .\venv\Scripts\python.exe -m weather.market.mm_credential_import_cli `
    --source-env $credentialSource `
    --manifest-out $pilotCredentialProvisioningManifest `
    --receipt-out $pilotCredentialProvisioningReceipt `
    --sdk-overlay-manifest .\scripts\ops\international_live_templates\sdk_overlay_manifest.json `
    --sdk-overlay-manifest-sha256 2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13 `
    --confirm-source-acl-private `
    --confirmation INTERNATIONAL_POLYMARKET_IMPORT_CREDENTIALS
  if ($LASTEXITCODE -ne 0) { throw "create-only credential import blocked" }
  $credentialProvisioningReceipt = Get-Content `
    -LiteralPath $pilotCredentialProvisioningReceipt -Raw |
    ConvertFrom-Json -ErrorAction Stop
  if ($credentialProvisioningReceipt.status -cne "PASS" -or
      $credentialProvisioningReceipt.credential_mode -cne "create_new" -or
      $credentialProvisioningReceipt.credential_value_count_written -ne 4) {
    throw "create-only credential import receipt did not pass exactly"
  }
  $pilotCredentialManifestSource = $pilotCredentialProvisioningManifest
  $pilotCredentialReceiptSource = $pilotCredentialProvisioningReceipt
}
```

An occupancy refusal is not permission to overwrite or delete an existing
target. Clean creation can proceed directly to public receipt review and source
cleanup; no second comparison is required. **Only for an explicitly requested
independent comparison**, use distinct new output paths and run:

```powershell
$ErrorActionPreference = "Stop"
$pilotCredentialManifestSource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-verified-references.json")
$pilotCredentialReceiptSource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-verified-receipt.json")
.\venv\Scripts\python.exe -m weather.market.mm_credential_import_cli `
  --source-env $credentialSource `
  --manifest-out $pilotCredentialManifestSource `
  --receipt-out $pilotCredentialReceiptSource `
  --sdk-overlay-manifest .\scripts\ops\international_live_templates\sdk_overlay_manifest.json `
  --sdk-overlay-manifest-sha256 2044d0570d38c34057c520ab19bfcc114c751fe8c76f97091b605acc1deecd13 `
  --confirm-source-acl-private `
  --verify-existing-exact `
  --confirmation INTERNATIONAL_POLYMARKET_VERIFY_EXISTING_EXACT_CREDENTIALS
if ($LASTEXITCODE -ne 0) { throw "compare-only credential verification blocked" }
$credentialComparisonReceipt = Get-Content `
  -LiteralPath $pilotCredentialReceiptSource -Raw |
  ConvertFrom-Json -ErrorAction Stop
if ($credentialComparisonReceipt.status -cne "PASS" -or
    $credentialComparisonReceipt.credential_mode -cne "verify_existing_exact" -or
    $credentialComparisonReceipt.credential_store_mutation_attempted -ne $false) {
  throw "compare-only credential receipt did not pass exactly"
}
```

This mode requires all four fixed entries to exist, reads their values only in
the importer process, compares all four to the independently retained source,
and never calls the credential writer or deleter. It emits no target-specific
match result, secret-derived hash, or credential value. Any absent, unreadable,
or unequal entry fails generically and requires manual provenance review; it
must never fall back automatically to creation, overwrite, or deletion.

Do not proceed unless the v0.4 receipt is an exact clean `PASS` with no
rollback and one of these truthful tuples:

- `credential_mode=create_new`, four written, zero existing verified, and
  credential-store mutation attempted;
- `credential_mode=verify_existing_exact`, zero written, four existing
  verified, and no credential-store mutation attempted.

Both tuples are accepted by the session manifest builder and fixed-scope
sealer as installation provenance when the v0.4 receipt belongs to the current
execution host and Windows token principal. Neither expires by age. Keep the
public receipt/reference pair after deleting the temporary private source.
Use that same retained pair for later attempts; never rewrite its timestamp or
describe it as a new check of the vault. Missing provenance or a different
host/principal requires explicit setup/recovery, not a fabricated replacement.

The latter proves only point-in-time local vault equivalence to the validated
source. It does not prove exchange authentication, current account state,
geographic eligibility, or live-trading authorization. Do not persist the
manifest references in User or Machine environment.

The hash-sealed launcher parses the public reference manifest, sets the five
required values only in its child-process scope, clears all direct-secret names,
and restores its own prior process environment afterward. The required variables are
`POLYMARKET_API_KEY_STORAGE_REF`,
`POLYMARKET_API_SECRET_STORAGE_REF`,
`POLYMARKET_API_PASSPHRASE_STORAGE_REF`,
`POLYMARKET_PRIVATE_KEY_STORAGE_REF`, and the public
`POLYMARKET_FUNDER_ADDRESS`. The first four values must be references, not the
credentials themselves. Do not install the live extra into the shared production
venv. The repository manifest instead validates the complete fixed external
SDK overlay and all 34 offline wheels before and after process-local import; the
runtime rejects any version or import origin other than the pinned 0.6.0 tree.
Git does not contain that external substrate. Use the non-secret export/import
tool in the
[`portable execution-host runbook`](PORTABLE_LIVE_EXECUTION_HOST.md) before
credential preparation on each new PC; never include credentials in its bundle.
After successful creation or exact verification, independent verification of
the public receipt and reference manifest, and operator verification of the
external source's retained copy, delete the source credential file using the
approved secure-deletion procedure. The importer never deletes it
automatically.

#### Event metadata and stage discovery

The metadata generator below can run during public preparation before
credential comparison. For a selected city, supply a retained, unmodified
Gamma `/events?slug=<exact-event-slug>` response to `--events-json`: it must be
an event list (or an object containing `events`), not the single event object
returned by `/events/slug/...`. Preserve its capture URL, time and raw hash.
The canonical generator may produce metadata with only that event populated;
other built-in locations need not have target-date events. Discovery remains
unconstrained within that generated event's books. Never edit condition/token
IDs into metadata or add an unsupported `--market` selector flag.

```powershell
$ErrorActionPreference = "Stop"
$pilotEventListSource = "replace-with-absolute-retained-public-Gamma-events-list-json"
$pilotEventListSource = Get-VerifiedPilotLocalPath $pilotEventListSource
if (-not (Test-Path -LiteralPath $pilotEventListSource -PathType Leaf)) {
  throw "retained public Gamma event-list source is absent"
}
.\venv\Scripts\python.exe -m weather.operations.location_config_refresh `
  --locations .\config\locations.json `
  --event-metadata $pilotEventMetadata `
  --events-json $pilotEventListSource `
  --metadata-only
if ($LASTEXITCODE -ne 0) { throw "event metadata refresh failed" }
```

Only after credential provenance and public identity validation pass, start the
expiring selectors and manifest builds. The Stage 0 selector may softly rank valid books, but it
does not reject a scope for spread, midpoint, depth, economics, paper
permission, rewards, rebate, or fee. The Stage 1 selector stays on the exact
Stage 0 condition/token and accepts a current official fee rate of zero:

```powershell
$ErrorActionPreference = "Stop"
.\venv\Scripts\python.exe -m weather.market.mm_live_stage0_scope `
  --event-metadata $pilotEventMetadata `
  --target-date $pilotTargetDate `
  --plan-out $pilotStage0DiscoveryPlan
if ($LASTEXITCODE -ne 0) { throw "Stage 0 structural scope discovery blocked" }

$pilotStage0Plan = Get-Content -LiteralPath $pilotStage0DiscoveryPlan -Raw |
  ConvertFrom-Json
if (
  $pilotStage0Plan.schema_version -cne "mm_live_stage0_scope_plan_v0.1" -or
  $pilotStage0Plan.status -cne "PASS" -or
  $pilotStage0Plan.selection_is_trading_authorization -or
  [DateTimeOffset]::Parse([string]$pilotStage0Plan.expires_at_utc) -le
    [DateTimeOffset]::UtcNow
) {
  throw "Stage 0 discovery plan did not pass"
}
$pilotMarketId = [string]$pilotStage0Plan.selected.location_id
$pilotConditionId = [string]$pilotStage0Plan.selected.condition_id
$pilotTokenId = [string]$pilotStage0Plan.selected.token_id

.\venv\Scripts\python.exe -m weather.market.mm_live_stage1_lifecycle_plan `
  --event-metadata $pilotEventMetadata `
  --target-date $pilotTargetDate `
  --expected-condition-id $pilotConditionId `
  --expected-token-id $pilotTokenId `
  --plan-out $pilotStage1DiscoveryPlan
if ($LASTEXITCODE -ne 0) { throw "Stage 1 lifecycle discovery blocked" }

$pilotStage1Plan = Get-Content -LiteralPath $pilotStage1DiscoveryPlan -Raw |
  ConvertFrom-Json
if (
  $pilotStage1Plan.schema_version -cne
    "mm_live_stage1_lifecycle_plan_v0.1" -or
  $pilotStage1Plan.status -cne "PASS" -or
  $pilotStage1Plan.selection_is_trading_authorization -or
  [string]$pilotStage1Plan.selected.condition_id -cne $pilotConditionId -or
  [string]$pilotStage1Plan.selected.token_id -cne $pilotTokenId -or
  [DateTimeOffset]::Parse([string]$pilotStage1Plan.expires_at_utc) -le
    [DateTimeOffset]::UtcNow
) {
  throw "Stage 1 lifecycle discovery plan did not pass exact scope"
}
```

#### Fixed session manifests and launcher review

The manifest builder stages the discovery plan appropriate to each stage and
the exact event-metadata bytes that plan binds. Discovery is preparation only:
the fixed-scope sealer refuses a discovery artifact at the live-plan boundary.
Each stage also has its own copies of the public credential receipt and
reference manifest. Stage 1 binds those copies to Stage 0 by equal reviewed
hashes and freshly verified, byte-identical regular files. Their paths may
differ; an absent, redirected, changed or differently hashed prior copy fails
the lineage gate. The original Stage 0 seal and execution receipts stay bound.
After independent review of all three manifests and outer launchers, create a
new exact-scope Stage 0 plan in its fixed inbox. After Stage 0 passes, create a
new exact-scope Stage 1 lifecycle plan in each mode's fixed inbox immediately
before that reviewed launcher. Every live plan lasts exactly 300 seconds.

The fresh Stage 0 plan first content-binds an exact current Gamma comparison,
including auditable event/market active, closed, and order-book status fields,
the full ordered condition/token contract, and its staged/current hashes,
then rereads the public book and binds its condition, token, minimum size, tick,
neg-risk state, and book hash. Best bid/ask are
diagnostics; empty, crossed, extreme, or wide books do not block the no-order
bootstrap. The fresh Stage 1 plan repeats the current Gamma identity comparison,
then rereads the exact book and official tick, neg-risk, and fee endpoints. It
requires a minimum-tick BUY to remain below any
current best ask, post-only intent, and minimum-order notional no greater than
10 pUSD. The fee rule must be finite and nonnegative, but may be zero. Neither
plan accepts economics, accepted-baseline, drift, paper, substrate-preflight,
spread/midpoint, reward, or rebate inputs. Stage 2 must make a separate current
quote/economics decision after Stage 1 passes.

With identity and public credential preparation complete, prepare the final
Stage 0, both Stage 1 modes, and bundle construction in
advance and run consecutively; an expired bootstrap is a stop, not a reason to
edit timestamps or reuse an earlier gate.

Do not invoke Stage 0 or Stage 1 with `python -m`: the parser intentionally has
no exchange-mutation commands. Do not hand-edit a copy of the old host template.
The repository-owned manifest builder and sealers are the only supported path.
The builder rereads the current public inventory and requires the exact
canonical Git executable and hash, the canonical HTTPS origin URL with no local
trust/proxy override, no ambient `WEATHER_MARKET_REGISTRY`, and a bounded live
query of the profile-authorized ref against that literal canonical URL. On
adopted master, both profiles require exact `HEAD`/local/cached/live master
equality; the capture profile is master-only. The portable topic exception
requires its exact branch equality and synchronized-master ancestry under
[source authority](PORTABLE_LIVE_EXECUTION_HOST.md#source-authority).
A stale cached ref, malformed result,
timeout, unavailable remote, detached checkout, dirty tree, master drift, or
missing ancestry blocks. It derives the Git tree, interpreter, template,
complete live source, and session-bootstrap hashes, and hardcodes 10 pUSD plus
the profile-bound 120-second colocated or 240-second portable session envelope. It
accepts no typed target, condition, token, budget, duration, output, or plan
override. Scope comes only from the complete stage-specific discovery gate after it
revalidates the still-current, unconstrained, self-hashed, non-authorizing
International/pUSD stage plan, its exact generated event-metadata binding, and
the stage-specific current structural or lifecycle-safety contract.
It never opens Credential Manager or calls the exchange.

The earlier `init-attempt` command creates a new external root with ACL
inheritance disabled and FullControl granted only to the current user, SYSTEM,
and Administrators, then validates the root plus `inputs`, `incoming`, and
`session`. A pre-existing root is spent and cannot be adopted. `prepare-manifest`
exclusively copies the reviewed public source files byte-for-byte into these
stage-specific canonical names. Every stage receives the exact generated event
metadata its plan binds; no stage receives economics acceptance, drift, paper,
or substrate-preflight copies:

| Stage | Event metadata | Discovery plan | Manifest / build receipt | Live-plan inbox |
| --- | --- | --- | --- | --- |
| `stage0` | `inputs/stage0-location-market-events.json` | `inputs/stage0-discovery-plan.json` (structural scope) | `inputs/stage0-session-manifest.json` / `inputs/stage0-session-manifest-build-receipt.json` | `incoming/fresh-stage0-candidate.json` |
| `stage1_cancel_all` | `inputs/stage1-cancel-all-location-market-events.json` | `inputs/stage1-cancel-all-discovery-plan.json` (lifecycle safety) | `inputs/stage1_cancel_all-session-manifest.json` / `inputs/stage1-cancel-all-session-manifest-build-receipt.json` | `incoming/fresh-stage1_cancel_all-candidate.json` |
| `stage1_dead_man` | `inputs/stage1-dead-man-location-market-events.json` | `inputs/stage1-dead-man-discovery-plan.json` (lifecycle safety) | `inputs/stage1_dead_man-session-manifest.json` / `inputs/stage1-dead-man-session-manifest-build-receipt.json` | `incoming/fresh-stage1_dead_man-candidate.json` |

Identity, credential installation receipt, and reference-manifest copies retain their
existing canonical names. The `candidate` filenames and receipt fields are
compatibility names only: Stage 0 carries an
`mm_live_stage0_scope_plan_v0.1`; Stage 1 carries an
`mm_live_stage1_lifecycle_plan_v0.1`.

Each copy, manifest, raw sidecar, and build receipt is exclusive-new. A partial
failure spends that stage namespace. The optional
`--reviewed-status-flags-json` source must be a JSON list whose rows have exactly
`sha256` and a 12-500 character `review`; it is also copied to the corresponding
stage-specific `inputs/*-reviewed-status-flags.json`. Omit the option only when
the reviewed list is empty. The option is forbidden for
`portable_execution_v1`, because capture-host exceptions cannot be transferred
to an execution-only PC.

Prepare Stage 0 from its structural discovery plan and both Stage 1 modes from
the exact-scope lifecycle discovery plan while all are current. The distinct workload strings prevent one stage from reusing
another stage's host lease:

```powershell
$ErrorActionPreference = "Stop"
$pilotManifestStages = @(
  [pscustomobject]@{ Stage = "stage0"; Workload = $attemptInit.lease_workloads.stage0; Plan = $pilotStage0DiscoveryPlan },
  [pscustomobject]@{ Stage = "stage1_cancel_all"; Workload = $attemptInit.lease_workloads.stage1_cancel_all; Plan = $pilotStage1DiscoveryPlan },
  [pscustomobject]@{ Stage = "stage1_dead_man"; Workload = $attemptInit.lease_workloads.stage1_dead_man; Plan = $pilotStage1DiscoveryPlan }
)

foreach ($row in $pilotManifestStages) {
  .\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer prepare-manifest `
    --stage $row.Stage `
    --discovery-plan $row.Plan `
    --identity-source $pilotIdentitySource `
    --credential-import-receipt-source $pilotCredentialReceiptSource `
    --credential-reference-manifest-source $pilotCredentialManifestSource `
    --event-metadata-source $pilotEventMetadata `
    --attempt-root $pilotAttemptRoot `
    --lease-workload $row.Workload `
    --execution-host-profile $pilotExecutionHostProfile
  if ($LASTEXITCODE -ne 0) { throw "fixed-session manifest preparation blocked for $($row.Stage)" }
}
```

Each output manifest is `international_live_fixed_session_manifest_v0.5`; its
`manifest_sha256` is the semantic hash, while the adjacent `.sha256` binds the
exact pretty-printed bytes. Independently inspect each staged copy, build
receipt, semantic hash, raw hash, and sidecar. Record six reviewed raw hashes
out of band: all three manifests and all three canonical build receipts. Do not
pipe `Get-FileHash` directly into launcher creation. Then turn each reviewed
manifest/receipt pair into a no-argument outer launcher:

```powershell
$ErrorActionPreference = "Stop"
$stage0ManifestSha256 = "replace-with-independently-reviewed-stage0-raw-sha256"
$cancelAllManifestSha256 = "replace-with-independently-reviewed-cancel-all-raw-sha256"
$deadManManifestSha256 = "replace-with-independently-reviewed-dead-man-raw-sha256"
$stage0BuildReceiptSha256 = "replace-with-independently-reviewed-stage0-build-receipt-sha256"
$cancelAllBuildReceiptSha256 = "replace-with-independently-reviewed-cancel-all-build-receipt-sha256"
$deadManBuildReceiptSha256 = "replace-with-independently-reviewed-dead-man-build-receipt-sha256"

$stage0LauncherPreparation = .\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer prepare-launcher `
  --session-manifest (Join-Path $pilotAttemptRoot "inputs\stage0-session-manifest.json") `
  --expected-session-manifest-sha256 $stage0ManifestSha256 `
  --expected-manifest-build-receipt-sha256 $stage0BuildReceiptSha256
if ($LASTEXITCODE -ne 0 -or
    ($stage0LauncherPreparation | ConvertFrom-Json -ErrorAction Stop).status -cne "PASS") {
  throw "stage0 launcher preparation blocked"
}

$cancelAllLauncherPreparation = .\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer prepare-launcher `
  --session-manifest (Join-Path $pilotAttemptRoot "inputs\stage1_cancel_all-session-manifest.json") `
  --expected-session-manifest-sha256 $cancelAllManifestSha256 `
  --expected-manifest-build-receipt-sha256 $cancelAllBuildReceiptSha256
if ($LASTEXITCODE -ne 0 -or
    ($cancelAllLauncherPreparation | ConvertFrom-Json -ErrorAction Stop).status -cne "PASS") {
  throw "cancel-all launcher preparation blocked"
}

$deadManLauncherPreparation = .\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer prepare-launcher `
  --session-manifest (Join-Path $pilotAttemptRoot "inputs\stage1_dead_man-session-manifest.json") `
  --expected-session-manifest-sha256 $deadManManifestSha256 `
  --expected-manifest-build-receipt-sha256 $deadManBuildReceiptSha256
if ($LASTEXITCODE -ne 0 -or
    ($deadManLauncherPreparation | ConvertFrom-Json -ErrorAction Stop).status -cne "PASS") {
  throw "dead-man launcher preparation blocked"
}
```

Launcher preparation derives the build-receipt path from the stage; there is no
path override. It validates the receipt's exact manifest raw/semantic hashes,
sidecar, production, scope, staged public-input hashes, host/principal-bound credential
evidence, canonical paths, the fixed 10 pUSD limit, and the profile-bound
120-second colocated or 240-second portable session envelope, and
no-credential/no-live-mutation facts. The
launcher review records the canonical receipt path/hash, and the launcher locks
that exact receipt through child exit. A hand-authored manifest and recomputed
sidecar are unsupported and cannot produce a launcher without the matching
canonical builder receipt.

The canonical keyless doctor runs inside each sealed fixed-scope wrapper before
the supervised prompt and before credential resolution. The hash-bound
PowerShell launcher validates the public credential-reference manifest and
stages only its reference names in the child process; the Python doctor then
validates the exact SDK version, Windows resolver availability, reference URI
shapes and completeness, direct-secret absence, public-funder/identity equality,
target/condition/token formats, and requested budget without opening Credential
Manager or authenticating to the exchange. Its receipt contains counts and gate
names, never reference targets. Do not invoke the standalone `doctor` command:
references are deliberately not persisted, and operators must not manually set
or persist them to make that command pass. Do not proceed unless the wrapper's
doctor receipt is `PASS` with an empty `missing` list.

The outer session launcher composes the
`international_live_fixed_scope_seal_spec_v0.5` plan-bounded spec and invokes
the fixed-scope sealer; operators do not hand-author or directly invoke that
inner surface. The sealer never opens Credential Manager or runs the generated
launcher. It independently validates the inert SDK overlay, stage-specific
plan semantic hash and 300-second lease, exact event-metadata binding,
profile/date containment including the shared 20-second cleanup reserve, all
public inputs, every imported live-source hash, exact Git authority and
ancestry, and new contained output paths. Stage 0 validates structural scope;
Stage 1 validates the direct lifecycle intent and exact successful predecessor
lineage. It does not consume paper TTL, economics acceptance, spread/midpoint,
reward/rebate eligibility, or a positive-fee requirement. It creates a fixed
no-argument Python wrapper,
a hash-bound inner PowerShell launcher, an
`international_live_fixed_scope_seal_v0.6` receipt, and its SHA-256 sidecar.
A partial or failed build, seal, or run spends that stage namespace; create a new
attempt rather than overwriting it.

#### Fresh Stage 0 scope and attended launch

The discovery plans are not the live plans. Use only the exact event-metadata
copies already staged in each independently reviewed manifest. Immediately
before Stage 0, verify the immutable launcher review and write a new structural
scope plan to its fixed compatibility-named inbox:

```powershell
$ErrorActionPreference = "Stop"
$stage0ReviewPath = Join-Path $pilotAttemptRoot "session\stage0-launcher-review.json"
$stage0ReviewHash = (Get-FileHash -LiteralPath $stage0ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant()
$stage0ReviewSidecar = $stage0ReviewPath + ".sha256"
$stage0ExpectedSidecar = $stage0ReviewHash + "  " +
  [IO.Path]::GetFileName($stage0ReviewPath) + "`n"
if ([IO.File]::ReadAllText($stage0ReviewSidecar, [Text.Encoding]::ASCII) -cne
    $stage0ExpectedSidecar) { throw "Stage 0 launcher-review sidecar mismatch" }
$stage0Review = Get-Content -LiteralPath $stage0ReviewPath -Raw | ConvertFrom-Json
$stage0ManifestPath = Join-Path $pilotAttemptRoot "inputs\stage0-session-manifest.json"
$stage0EventMetadata = Join-Path $pilotAttemptRoot "inputs\stage0-location-market-events.json"
if (
  $stage0Review.status -cne "PASS" -or
  [string]$stage0Review.stage -cne "stage0" -or
  -not $stage0Review.no_argument_surface -or
  (Test-Path -LiteralPath $stage0Review.candidate_inbox) -or
  (Get-FileHash -LiteralPath $stage0ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    ([string]$stage0Review.session_manifest.sha256).ToLowerInvariant() -or
  (Get-FileHash -LiteralPath $stage0Review.launcher.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    ([string]$stage0Review.launcher.sha256).ToLowerInvariant()
) {
  throw "Stage 0 immutable launcher review did not pass"
}

.\venv\Scripts\python.exe -m weather.market.mm_live_stage0_scope `
  --event-metadata $stage0EventMetadata `
  --target-date $pilotTargetDate `
  --expected-condition-id $pilotConditionId `
  --expected-token-id $pilotTokenId `
  --plan-out ([string]$stage0Review.candidate_inbox)
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 structural scope blocked" }

$stage0PlanHash = (Get-FileHash -LiteralPath $stage0Review.candidate_inbox -Algorithm SHA256).Hash.ToLowerInvariant()
$stage0Plan = Get-Content -LiteralPath $stage0Review.candidate_inbox -Raw |
  ConvertFrom-Json
if (
  $stage0Plan.schema_version -cne "mm_live_stage0_scope_plan_v0.1" -or
  $stage0Plan.status -cne "PASS" -or
  $stage0Plan.selection_is_trading_authorization -or
  [string]$stage0Plan.selected.condition_id -cne $pilotConditionId -or
  [string]$stage0Plan.selected.token_id -cne $pilotTokenId -or
  [DateTimeOffset]::Parse([string]$stage0Plan.expires_at_utc) -le
    [DateTimeOffset]::UtcNow
) {
  throw "fresh Stage 0 plan did not pass exact scope"
}
if (
  (Get-FileHash -LiteralPath $stage0ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $stage0ReviewHash -or
  (Get-FileHash -LiteralPath $stage0Review.candidate_inbox -Algorithm SHA256).Hash.ToLowerInvariant() -cne $stage0PlanHash
) {
  throw "Stage 0 launcher review or scope plan changed before invocation"
}
& ([string]$stage0Review.launcher.path)
if ($LASTEXITCODE -ne 0) { throw "Stage 0 reviewed launcher failed" }
```

#### Fresh Stage 1 plans and attended launches

After Stage 0 passes, run this exact helper once for each Stage 1 mode. Each
plan binds that manifest's exact staged event metadata and the Stage 0
condition/token. The files retain compatibility `candidate` names, but their
schema and authority are strictly lifecycle-plan only:

```powershell
$ErrorActionPreference = "Stop"
function Invoke-FreshReviewedStage1 {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("stage1_cancel_all", "stage1_dead_man")]
    [string]$Stage
  )
  $reviewPath = Join-Path $pilotAttemptRoot (
    "session\" + $Stage + "-launcher-review.json"
  )
  $reviewHash = (Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $reviewSidecar = $reviewPath + ".sha256"
  $expectedSidecar = $reviewHash + "  " +
    [IO.Path]::GetFileName($reviewPath) + "`n"
  if ([IO.File]::ReadAllText($reviewSidecar, [Text.Encoding]::ASCII) -cne
      $expectedSidecar) { throw "$Stage launcher-review sidecar mismatch" }
  $review = Get-Content -LiteralPath $reviewPath -Raw | ConvertFrom-Json
  $manifestPath = Join-Path $pilotAttemptRoot (
    "inputs\" + $Stage + "-session-manifest.json"
  )
  $metadataName = if ($Stage -eq "stage1_cancel_all") {
    "stage1-cancel-all-location-market-events.json"
  } else {
    "stage1-dead-man-location-market-events.json"
  }
  $eventMetadata = Join-Path $pilotAttemptRoot ("inputs\" + $metadataName)
  if (
    $review.status -cne "PASS" -or
    [string]$review.stage -cne $Stage -or
    -not $review.no_argument_surface -or
    (Test-Path -LiteralPath $review.candidate_inbox) -or
    (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
      ([string]$review.session_manifest.sha256).ToLowerInvariant() -or
    (Get-FileHash -LiteralPath $review.launcher.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne
      ([string]$review.launcher.sha256).ToLowerInvariant()
  ) {
    throw "$Stage immutable launcher review did not pass"
  }

  .\venv\Scripts\python.exe -m weather.market.mm_live_stage1_lifecycle_plan `
    --event-metadata $eventMetadata `
    --target-date $pilotTargetDate `
    --expected-condition-id $pilotConditionId `
    --expected-token-id $pilotTokenId `
    --plan-out ([string]$review.candidate_inbox)
  if ($LASTEXITCODE -ne 0) { throw "$Stage lifecycle-plan selection blocked" }

  $planHash = (Get-FileHash -LiteralPath $review.candidate_inbox -Algorithm SHA256).Hash.ToLowerInvariant()
  $plan = Get-Content -LiteralPath $review.candidate_inbox -Raw |
    ConvertFrom-Json
  if (
    $plan.schema_version -cne "mm_live_stage1_lifecycle_plan_v0.1" -or
    $plan.status -cne "PASS" -or
    $plan.selection_is_trading_authorization -or
    [string]$plan.selected.condition_id -cne $pilotConditionId -or
    [string]$plan.selected.token_id -cne $pilotTokenId -or
    $plan.selected.stage1_intent.side -cne "BUY" -or
    -not $plan.selected.stage1_intent.post_only -or
    [decimal]$plan.selected.stage1_intent.notional_pusd -gt [decimal]10 -or
    [decimal]$plan.selected.fee_rate_bps -lt [decimal]0 -or
    [DateTimeOffset]::Parse([string]$plan.expires_at_utc) -le
      [DateTimeOffset]::UtcNow
  ) {
    throw "$Stage fresh lifecycle plan did not pass direct safety"
  }
  if (
    (Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $reviewHash -or
    (Get-FileHash -LiteralPath $review.candidate_inbox -Algorithm SHA256).Hash.ToLowerInvariant() -cne $planHash
  ) {
    throw "$Stage launcher review or lifecycle plan changed before invocation"
  }
  & ([string]$review.launcher.path)
  if ($LASTEXITCODE -ne 0) { throw "$Stage reviewed launcher failed" }
}

Invoke-FreshReviewedStage1 -Stage "stage1_cancel_all"
Invoke-FreshReviewedStage1 -Stage "stage1_dead_man"
```

Never reuse or rename an earlier scope/lifecycle plan, call a launcher out of
predecessor order, or pause past the plan's 300-second lease. A changed token
or event-metadata mapping requires a new attempt and three new manifests; a
changed current book/rule state requires a new still-bound live plan. The
launcher passes only the reviewed manifest hash and fixed plan path to the
composer; no scope or ceiling is accepted at the live boundary. Before writing
plan/spec/composition/intent artifacts, the composer derives a plan-bounded
window of at most 120 seconds for
`capture_colocated_v1` or 240 seconds for `portable_execution_v1` and
rejects unless that window plus the full 20-second cleanup tail remains within
one profile-valid local date. The colocated profile requires the target date
and complete **[00:30, 09:00) America/Toronto** containment. The portable
profile requires one selected-market-local execution date and a target equal
to that date or its immediately following date. It repeats the check at the execution
boundary and requires at least 90 seconds for the colocated profile or 180
seconds for the portable profile still available immediately before launch.
The manifest builder and fixed-scope sealer repeat the bounded, profile-aware
live remote proof at their validation and publication boundaries; the composer
repeats it after all protected-file checks immediately before launching, and
the sealed wrapper repeats it before credentials. A cached master or topic ref
match alone is never launch authority. For the portable exception, every
boundary repeats exact topic equality plus synchronized-master ancestry; for
the capture profile every boundary remains exact master-only. The composer then writes an immutable ARMED intent and atomically claims the terminal
receipt and sidecar paths. The no-argument launcher and parent runner hold
deny-write/delete handles for the reviewed runner, production sources, public
credential inputs, plan, complete predecessor lineage, external SDK
overlay, interpreter, and status-attestation helper closure. They rehash after
acquiring those handles and retain them through child exit. The parent sends
cooperative cleanup at the sealed execution stop, allows only the same
sealer-owned 20-second grace already reserved by every window check, and then
uses kill-on-close containment if required. For the colocated profile the
reserved end may equal 09:00; it must never exceed it.

The fixed launcher additionally proves the active shared lease is still held
with write sharing denied and binds the lease record to the canonical
PowerShell owner's PID and Windows process-creation token. The Python process
must be either its direct child or the child of exactly one hash-bound venv
`python.exe` redirector. The sealed venv `pyvenv.cfg` resolves the separately
hash-bound base Python process image; the launcher locks all three files, and
the wrapper requires strict owner-before-redirector-before-runtime creation
order. Every one of the three host attestations must carry the same complete
lineage proof. A stale/reused PID, permissive or absent lease handle, extra
process hop, changed config/image/hash, uninspectable process, or cross-stage
interpreter-binding mismatch fails before credentials. The seal and terminal
execution receipts carrying this mandatory evidence are v0.6 and v0.7,
respectively; earlier receipt versions cannot authorize a new attempt.

The wrapper displays the exact stage/mode, target, condition, token, 10 pUSD
request, 100 pUSD capital limit and its explicit allocation/funding declaration,
execution cutoff, cleanup reserve, and contained
process end before its literal confirmation. The
Stage 0 display also states `order_submit_expected=false`, an authenticated
heartbeat write is expected, and cancel-all cleanup is expected with
`ACCOUNT_WIDE` scope so those writes cannot be mistaken for read-only
activity. The
prompt is bounded by the same absolute cutoff. The portable profile requires
120 seconds remaining before entering credential context and 60 seconds
immediately before an authenticated mutation boundary. The stage,
physical-location/no-circumvention, and mutation-specific attended
confirmations all consume the same plan-derived cutoff; no prompt resets
or extends it. The fresh-plan helper must therefore flow directly into
the reviewed launcher, and hesitation is a stop-and-refresh event. After
confirmation it rechecks Git/source identity, profile-specific host status,
clock/reboot state, the applicable time boundary, and the plan before credential
resolution. The window guard also runs inside every host attestation. Stage 1
therefore repeats it submit-adjacent, checks the cutoff before the
adapter call, and binds the deadline into its one-use capability; the adapter
checks again after signing immediately before the actual `post_order` network
boundary. A hash-bound journal proves that ordering.

Do not invoke the inner fixed-scope launcher directly. Independently compare the
outer session launcher's hash with its review receipt, then invoke that launcher
with no arguments. Plan selection and successful sealing are preparation,
not execution authorization. Every `run_stage1` call still revalidates the
lifecycle plan before credential resolution, can perform exactly one network submit,
writes PASS only after final cancel-all/zero-state cleanup, and serializes
exception types rather than raw SDK messages.
Console interrupts and other process-level Python exits enter that same cleanup
path: Stage 1 first journals and attempts cancel-all/zero-state reconciliation,
then the command boundary independently repeats cleanup, finalizes the user
stream and client, writes a type-only FAIL receipt, and re-raises. The generated
host wrapper catches that `BaseException`, emits only its type, and stops; it
must never print a traceback or retry the submit. A forced process kill or power
loss cannot run Python cleanup and remains dependent on the independently proved
heartbeat-lapse cancellation.

#### Offline Stage 1 lifecycle bundle

Only after both Stage 1 calls pass, build the content-bound bundle offline. The
builder rereads and hashes both lifecycle journals rather than trusting copied
booleans:

```powershell
$ErrorActionPreference = "Stop"
$pilotStage0ManifestPath = Join-Path $pilotAttemptRoot "inputs\stage0-session-manifest.json"
$pilotStage0Manifest = Get-Content -LiteralPath $pilotStage0ManifestPath -Raw | ConvertFrom-Json
$pilotReviewedProductionTip = [string]$pilotStage0Manifest.production.commit
if ($pilotReviewedProductionTip -cnotmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
  throw "reviewed production tip is not a Git object ID"
}
$pilotBundleRoot = Join-Path $pilotAttemptRoot "bundle"
$pilotStage1Bundle = Join-Path $pilotBundleRoot "stage1-lifecycle-bundle.json"
$pilotStage1BundleReceipt = Join-Path $pilotBundleRoot "stage1-lifecycle-bundle-receipt.json"

.\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli bundle `
  --bootstrap (Join-Path $pilotAttemptRoot "stage0\bootstrap.json") `
  --expected-production-tip $pilotReviewedProductionTip `
  --target-date $pilotTargetDate `
  --condition-id $pilotConditionId `
  --token-id $pilotTokenId `
  --budget 10 `
  --cancel-all-result (Join-Path $pilotAttemptRoot "stage1-cancel-all\result.json") `
  --cancel-all-seal-receipt (Join-Path $pilotAttemptRoot "seal\stage1-cancel-all-seal-receipt.json") `
  --cancel-all-command-receipt (Join-Path $pilotAttemptRoot "stage1-cancel-all\command-receipt.json") `
  --cancel-all-execution-receipt (Join-Path $pilotAttemptRoot "stage1-cancel-all\wrapper-execution-receipt.json") `
  --cancel-all-run-receipt (Join-Path $pilotAttemptRoot "session\stage1_cancel_all-run-receipt.json") `
  --dead-man-result (Join-Path $pilotAttemptRoot "stage1-dead-man\result.json") `
  --dead-man-seal-receipt (Join-Path $pilotAttemptRoot "seal\stage1-dead-man-seal-receipt.json") `
  --dead-man-command-receipt (Join-Path $pilotAttemptRoot "stage1-dead-man\command-receipt.json") `
  --dead-man-execution-receipt (Join-Path $pilotAttemptRoot "stage1-dead-man\wrapper-execution-receipt.json") `
  --dead-man-run-receipt (Join-Path $pilotAttemptRoot "session\stage1_dead_man-run-receipt.json") `
  --bundle-out $pilotStage1Bundle `
  --receipt-out $pilotStage1BundleReceipt `
  --confirmation INTERNATIONAL_POLYMARKET_STAGE1_BUILD_BUNDLE
if ($LASTEXITCODE -ne 0) { throw "offline Stage 1 lifecycle bundle construction blocked" }
```

These are the canonical attempt-local Stage 0/1 layouts emitted by the sealed
launchers. The two bundle outputs are new under the same protected
`$pilotAttemptRoot`; a FAIL receipt is evidence to stop and investigate, never
permission to retry a submit.

`weather.market.mm_live_bootstrap.collect_platform_bootstrap_payload` is the
prepared Stage 0 evidence collector. It converts the CLOB's integer atomic
collateral balance and allowances to six-decimal settlement units, enforces the
explicit capital contract and sufficient backing, validates a public Data API position
query scoped to the exact proxy wallet and condition, content-binds that query
and the full account snapshot, locally constructs and hashes a signed minimum
BUY without posting it, discards the raw signature, requires a live user-stream
PONG, obtains and binds the separate fresh pre-mutation geography receipt,
exercises two bodyless five-second heartbeat acknowledgements, and sends
cancel-all followed by a zero-order query. The WebSocket does not document an
initial account snapshot, so the gate does not invent one: REST establishes the
starting state, PONG establishes transport liveness, and the first Stage 1 order event proves
the authenticated event path.

### Stage 2: one-band maker quote

- Require a current passing `mm_platform_verification_v0.6`, including the
  Stage 1 automatic heartbeat-lapse cancellation and cancel-all-to-zero proof.
  The full gate repeats the numeric balance, allowance, actual-wallet-cap,
  zero-open-order-count, and account-snapshot-hash checks; Stage 0 booleans are
  not carried forward as financial proof.
- Select one band under a separately preregistered Stage 2 decision rule whose
  thresholds are measured or bound to current venue requirements. Until that
  evidence exists, spread, midpoint/centrality, and depth may rank or warn but
  cannot independently claim quote safety or profitability.
- Place one or two smallest-valid backed post-only orders for one TTL only.
- A post-only cross rejection is a stop-and-refresh event, never permission to
  chase price.
- Cancel at TTL, stale evidence, user-stream silence, heartbeat failure,
  reconciliation mismatch, unexpected fill state, risk limit, or operator stop.

### Stage 3: evidence and settlement

For every accepted order, retain intent, signed-request hash (never the secret
or raw private key), exchange order ID, stream events, REST reconciliation,
fill/trade IDs, transaction hashes when available, balances, positions,
markouts, fees, rebate estimate, paid rebate, redemption, and final settlement
P&L. Reconcile the paid rebate after the daily cycle; the program's current
minimum payout threshold means one tiny session may produce no payment.

Normalize the official account stream fail-closed. An order cancellation is
`event_type=order`, `type=CANCELLATION`; do not inspect only the first field.
Order and taker events require the exact top-level pilot maker. For maker-side
trades, bind the pilot maker address to its `maker_orders` row; the top-level
`maker_address` can describe the counterparty and must not reject our fill.
Retain `trader_side`. `MATCHED`, `MINED`, and `RETRYING` are pending lifecycle
evidence, not fills for final accounting. Only `CONFIRMED` creates a settled
fill row; `FAILED` creates no fill. Any taker role, out-of-scope token/condition,
unknown status, or maker row that cannot be attributed to the pilot order is a
stop condition.

Position and rebate reconciliation use content-bound official responses. Zero
positions require `GET https://data-api.polymarket.com/positions` with the exact
`user`, `market`, `sizeThreshold=0`, `limit=500`, and `offset=0` scope plus a
recorded response hash. Pagination parameters are part of the proof; an
unbounded or partially inspected result is not an exact zero.
Rebate evidence likewise requires the exact public `/rebates/current` request,
HTTP success, and a response hash; a caller-supplied list is not endpoint proof.

`weather.market.mm_user_stream.OfficialUserStreamReader` is the prepared
account-wide transport boundary. It accepts the already-resolved API values in
memory, journals only an explicit normalized-field allowlist plus a SHA-256 of
the raw server event, and has no CLI or
automatic startup. A transport disconnect, unknown event, malformed JSON, or
out-of-scope maker/token/condition ends the session without reconnecting. PONG
is transport-heartbeat evidence, not an order event; missing inbound server
PONGs fail on their own deadline even if other account events continue to
arrive, and a stopped reader cannot satisfy Stage 0. The caller
must cancel all and reconcile to zero before any new session; silent reconnect
during an outstanding order is forbidden.

The legacy report's rebate calculation uses the public official
`GET /rebates/current?date=...&maker_address=...` response for the completed next
payout cycle. It counts only rows matching the
pilot's exact date, maker address, and condition ID; sum `rebated_fees_usdc`.
The program document calls the payout asset pUSD while this API document calls
that amount USDC and returns an `asset_address`. Preserve both documented terms
as an explicit conflict: the field name is an accrual amount, not proof of the
wallet asset actually credited. Require the returned address to equal the
current official pUSD collateral proxy from the contracts page, then require
the observed wallet balance delta before calling a rebate paid.
Current reward-campaign metadata is eligibility evidence, not payout evidence.
A completed exact-scope query with no matching row is a reconciled zero, not a
missing value. Before the payout cycle is complete, even a positive current
row remains provisional. Record the query timestamp and query a UTC day only on
a later UTC date; a same-day `/rebates/current` response cannot be labeled a
completed payout cycle. The subsequent wallet cash identity still decides
whether an accrued amount was actually paid, including the `$1` minimum.

The current weather curve implies a useful scale check for the `$1` payout
minimum. At `p=0.50`, the documented `0.05` fee curve and `25%` rebate produce
`$0.003125` per filled share, so roughly `$160` of maker fill notional is needed
to accrue `$1`. At `p=0.10` the corresponding notional is about `$88.89`; at
`p=0.90` it is `$800`. The `$100` pilot envelope is a capital cap, not a claim
that one fill or one session can prove rebate profitability. Turnover and
price mix determine whether the payout threshold is reachable.

Do not call total P&L reconciled merely because settlement, fees, and a rebate
field are present. Require starting and ending balances, zero ending
positions, explicit external cash flows, a settlement-P&L basis that excludes
fees and incentives, and equality of the cash-flow identity to `0.00001`
pUSD. Otherwise the report remains incomplete; it must not infer profit by
adding fields whose accounting bases may overlap.

An empty positions list proves zero only when it is the result of an observed
query explicitly scoped to the exact maker and condition. A configured market
fee rate is not an actual fee measurement. Actual fee evidence must cover every
pilot trade and exit, including any taker or flattening fee, and its maker and
condition scope must equal the position and rebate scopes. A lone current
balance must never be reused as both the starting and ending balance.
The fee amount must be derived from the complete confirmed-trade event set and
bind that set with a SHA-256; a configured rate or an unbound manually entered
amount is not actual fee evidence. Bind each confirmed fill's trade/order IDs,
transaction hash, maker, condition, token, liquidity role, price, size, and fee
rate. Makers pay zero. For every taker or flattening fill, independently compute
`shares * (fee_rate_bps / 10000) * price * (1 - price)` and round to five pUSD
decimal places before summing. The reported amount and content hash must match
that calculation exactly.

### Offline paid-incentive reconciliation

`weather.market.mm_exchange_reports.reconcile_incentive_payments` accepts
supplied normalized evidence and performs no account, wallet or network read.
Its schema IDs are registered as `mm_paid_incentive_evidence`,
`mm_paid_incentive_reconciliation` and `mm_paid_incentive_pilot_report` in
`weather.schema_registry`. The legacy adapter/report schema remains unchanged.
The new path is an offline accounting contract; it does not implement a venue
reader or grant readiness, credential, exchange or live authority.

For retained raw activity and Polygon responses, the separate
[activity-to-credit bridge](paid-credit-activity-evidence.md) can derive exact
unique pUSD Transfer matches. It retains activity labels as DERIVED and does
not invent an accrual/distribution link or feed this matcher automatically.

The evidence object contains `schema_version`, `scope`, `as_of_utc`, `sources`,
`accruals`, `distributions`, `wallet_credits` and
`excluded_external_credit_ids`. The exact `scope` keys are `maker_address`,
`condition_id`, `cash_asset`, `accrual_start_utc`, `accrual_end_utc`,
`cash_start_utc` and `cash_end_utc`. IDs use canonical lowercase EVM hex.
The asset marker is the exact Polygon chain ID `137`, official pUSD collateral
proxy address from `mm_official_adapter`, symbol `pUSD` and integer decimals
`6`. Historical `_usdc` output suffixes retain native pUSD values; no exchange
rate or conversion is inferred from a field name.

All times must carry a UTC offset and normalize to UTC. Accrual and cash
windows are half-open; the accrual window must end no later than the cash
window, and the cash window must end no later than `as_of_utc`. Each of the
three source entries records `status=OBSERVED`,
`query_scope=exact_account_asset_period`, request/response SHA-256 hashes,
`observed_at_utc`, `coverage_through_utc`, and strict boolean `complete`,
`pagination_complete` and `payout_cycle_complete` markers. Its `request_scope`
must name the exact maker and cash asset, `condition_scope=account`, and
`period_start_utc`/`period_end_utc`: the accrual window for accruals, accrual
start through cash end for distributions, and the cash window for wallet
credits. Coverage cannot extend beyond observation, and observation cannot
extend beyond the evidence's as-of time. Missing/unsupported receipts are
invalid; partial pagination or coverage remains unresolved and cannot prove
a cash zero. These hashes retain supplied provenance, not an independent
authentication of a caller's completeness assertions.

Every row includes maker, native asset, observed time, source-record SHA-256,
and a decimal-string `amount`. Accrual rows name a stable `accrual_id`,
programme (`maker_rebate` or `liquidity_reward`), condition (or explicit `null`
for portfolio accrual), earned period and status `ESTIMATED`, `ACCRUED` or
`COMPLETED_ZERO`. Only completed-zero rows may have zero amount.
Distribution rows name `distribution_id`, `accrual_id`, the same programme
and condition, and `PAID` with `credit_id` or `PENDING` with `credit_id=null`.
Wallet rows name chain ID, transaction hash, integer log index, credited time
and `CONFIRMED`, `PENDING` or `FAILED`. A credit ID is the canonical
`137:<transaction_hash>:<log_index>` string. A confirmed credit must lie in
the cash window, follow the earned period and precede its wallet observation.
A distribution can be observed before later chain settlement; retrospective
matching uses the explicit identity after both are observed.

Match only the declared distribution-to-credit identity with exactly equal
native micro-units. Never guess a match from equal amounts. The same credit
cannot fund two distributions, cross both programmes or also appear among
external-flow exclusions. Total matched distributions cannot exceed the final
accrual. An identical normalized row is idempotent; conflicting reuse of a
record ID is invalid. Duplicate hashes and observation times remain in result
provenance. A missing confirmed credit, unattributed wallet credit, or paid
portfolio/other-condition distribution keeps selected-condition cash
unresolved. Results retain accrual, distribution and matched-payment states
and exact amount strings separately for each programme.

A positive unpaid accrual, including an amount below a payout threshold,
does not become cash. Complete closed-window evidence can establish paid
zero while reporting that accrual as unpaid; `accruals_fully_paid` remains
false. Estimated accrual and unknown accrual attribution are recorded
separately from cash completeness. A fully observed empty query can establish
zero; an unobserved, partially covered or missing query cannot. This helper
does not assert a current payout threshold or campaign entitlement.

To include matched payments in financial reports, pass
`incentive_schema_version=schema_version("mm_paid_incentive_reconciliation")`
to `build_financial_reconciliation` or `build_pilot_report_payload`, with the
evidence under `rewards.paid_incentive_evidence`. Supplying that block without
the selector, or an unsupported selector/schema, fails closed and cannot fall
back to the legacy rebate scalar. Old rebate-only helpers reject the new block.
The pilot payload uses its separate schema; its renderer rejects new paid
fields under a legacy schema and explicitly displays paid liquidity rewards
and the pUSD asset marker.

The financial identity still requires complete confirmed-trade fee evidence,
observed zero closing positions and gross settlement P&L that excludes fees
and incentives. Financial identity, balances, actual-fee evidence, redemption
and position evidence must each bind the exact maker, condition, native asset
and `cash_period={start_utc, end_utc}`. The position query's `observed_at_utc`
must be at or after cash end and no later than the incentive evidence's as-of
time. The identity additionally requires
`external_cash_flows_exclude_incentives=true` and
`external_cash_flow_credit_ids` equal to the sorted excluded credit IDs.

For this explicit version, raw starting/ending cash, external flows, gross
settlement P&L, redemption and actual fees must be decimal strings with at
most twelve whole and six fractional digits. Signed flows and P&L are
supported; wallet balances, fees and redemption are nonnegative. Floats, exponent notation,
nonfinite values and excess precision/magnitude are rejected. The new identity
uses integer native micro-units throughout and exports exact six-decimal
strings in `native_cash_identity`:

`ending_cash - starting_cash - external_flows = gross_settlement_pnl + paid_maker_rebate + paid_liquidity_reward - actual_fees`

The existing ten-micro-unit (`0.00001` pUSD) residual tolerance is preserved;
redemption is validated separately and is not added to gross P&L again.
Legacy arithmetic and its report fields retain their compatibility behavior.
A financial reconciliation with paid liquidity rewards and no fills may be
complete, while the pilot still lacks live fills, markouts and paper
counterfactual quotes. It does not establish profitable execution or readiness.

`MATCHED` is not settlement. Follow every trade through the authenticated
stream and REST reads until `CONFIRMED` or `FAILED`; a placement response may
return trade IDs before transaction hashes exist. Do not book inventory, fees,
or P&L from an intermediate exchange status alone.

## SDK decision record

The 2026-08-14 migration pins the official unified
`polymarket-client==0.6.0`. The published wheel and its source were checked
against the exact client construction, typed account readers, local limit-order
signing, single-order post, cancellation, and L2 HMAC contracts. Current
heartbeat documentation defines a bodyless `POST /heartbeats` with the exact
`{status: "ok"}` acknowledgment but does not state a cancellation timeout.
Official agent-skills guidance retains the empirical 10-second timeout plus up
to five seconds of buffer while also showing obsolete heartbeat-ID examples;
therefore the pilot keeps its 10-15 second observation as a fail-closed probe,
not a venue guarantee. Because the unified SDK does not expose the current REST
method, `weather.market.mm_official_transport` provides only that one
authenticated request; it is intentionally not a generic secret-bearing HTTP
client.

Two unified-client conveniences are unsafe for this bounded pilot. First,
`SecureClient.create` can deploy a missing default deposit wallet. Client
construction is therefore forbidden until a repository-owned public
`/deployed` check proves the exact supplied Safe or deposit wallet already
exists. Second, `place_limit_order` can recover missing allowance and retry.
The adapter instead calls local `create_limit_order(..., post_only=True)` and
then exactly one `post_order`. It verifies the signed token, signer, maker,
signature type, signature shape, GTC type, and post-only flag before that sole
submit. A rejection or ambiguous response is a stop-and-reconcile event, never
permission for an automatic approval or retry.

The direct account-wide WebSocket reader remains the authoritative user-event
boundary, while the unified SDK owns authenticated REST reads and order
signing/submission. Before any credentialed Stage 0/1 session, the fixed-scope
wrapper must validate the sealed external wheel closure, activate that exact
overlay process-locally and pass the keyless doctor. Stage 0 then collects its
bootstrap on the selected execution host; Stage 1 requires that host-local
passing predecessor and its exact lineage. A portable session does not require
or accept a copied capture-host Stage 0 proof. Installing the live extra into
the shared checkout remains forbidden. The successful source/wheel audit is
not wallet or exchange evidence.

The supplied Safe wallet's local cryptographic topology is proven, but its live
exchange behavior is still unproven. Stage 0 must show that the exact signer,
Safe/deposit-wallet funder, signature type, and API-key owner satisfy the
topology table above. A balance read is not sufficient: the same identity
must pass authenticated user-stream subscription, heartbeat, a signed-order
preview or non-posting contract probe, and cancel-all. Do not rely on a manual
UI-trade workaround or silently switch wallet/signature models after a failure.

Official references reviewed through 2026-08-23:

- <https://docs.polymarket.com/trading/overview>
- <https://docs.polymarket.com/api-reference/authentication>
- <https://github.com/Polymarket/py-sdk/tree/c8fb84bb51e60f790239056be7be0f5cc337d2e0>
- <https://github.com/Polymarket/agent-skills/blob/main/order-patterns.md>
- <https://github.com/Polymarket/py-sdk>
- <https://docs.polymarket.com/getting-started/migrate-from-previous-sdks>
- <https://docs.polymarket.com/api-reference/trade/send-heartbeat>
- <https://docs.polymarket.com/trading/fees>
- <https://docs.polymarket.com/api-reference/market-data/get-fee-rate>
- <https://docs.polymarket.com/programs/maker-rebates>
- <https://docs.polymarket.com/programs/liquidity-rewards>
- <https://docs.polymarket.com/trading/orders/create>
- <https://docs.polymarket.com/api-reference/trade/get-order-scoring-status>
- <https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker>
- <https://docs.polymarket.com/api-reference/geoblock>
- <https://help.polymarket.com/en/articles/13364163-geographic-restrictions>

## Stop conditions

Cancel all and do not resume on any of the following:

- for Stage 0/1, current event identity, bound book/rules, user-stream, or
  heartbeat evidence is unavailable or stale; for Stage 2, any separately
  required source, watcher, execution-capture, book, or economics evidence is
  unavailable or stale;
- required current min size, tick, neg-risk, nonnegative fee rule, wallet,
  allowance, or platform state is unavailable or drifts; for Stage 2 only,
  missing market fee/reward eligibility also stops the quote;
- any order is accepted as taker or without post-only protection;
- open orders, positions, reserves, or local lifecycle disagree with exchange
  truth;
- unknown order, unexpected partial fill, unbacked sell, or risk-cap breach;
- cancel-all is not followed by zero open orders;
- under `capture_colocated_v1`, the contained interval leaves the target date
  or **[00:30, 09:00) America/Toronto**, the host enters a protected window, or
  capture health degrades;
- under `portable_execution_v1`, the contained interval crosses its
  selected-market-local execution date, the target is neither that date nor
  its immediately following date, or execution-only status, exact host binding,
  clock, reboot, capture-host exclusion, or exclusive lease stops passing;
- official geoblock state is unavailable or blocked, physical eligibility is
  unconfirmed, or endpoint and attended physical-location attestations disagree.

## Decision after the pilot

- **Plumbing pass:** all lifecycle and shutdown proofs complete, even with no
  fill. Proceed to repeated bounded maker sessions.
- **Economics pass:** repeated maker fills show spread plus paid rebates exceeds
  adverse-selection markouts, inventory/settlement loss, and all costs under the
  simultaneous counterfactual. Only then consider more time or markets; capital
  remains capped until a new dated operator decision.
- **Fail:** any safety/reconciliation defect, taker execution, unexplained cash
  delta, or incomplete evidence. Fix and repeat Stage 1; do not explain it away
  as a small sample.

## Update when

Update when the approved capital envelope, platform, official SDK integration,
live gates, risk ceilings, probe sequence, or stop conditions change.
