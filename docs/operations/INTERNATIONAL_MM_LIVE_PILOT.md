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

The fixed-scope Stage 0/1 sealer, session runner, process-local pinned SDK
overlay, and interrupt-cleanup path are integrated production software. The
portable execution-host extension remains an unmerged candidate, but an
operator-authorized portable-only exception permits the exact reviewed branch
`codex/portable-execution-host-clean-20260827` to supply live code for
`portable_execution_v1` before master adoption. Read the current exact branch
tip, exact-head CI/review status, operator authorization, and production master
baseline from Git and [`STATE_OF_PLAY.md`](STATE_OF_PLAY.md), not from a dated
hash copied here.
Their integration receipts grant no credential or live-exchange authority, and
no Stage 0 or Stage 1 protocol has passed. Failed precredential launcher
attempts and their exact disposition are recorded in
[`STATE_OF_PLAY.md`](STATE_OF_PLAY.md).

**Stage 0/1 execution is currently HOLD until every action-time gate below
passes.** The explicit execution-host profile,
truthful Stage 0 authenticated-write confirmation contract, and canonical
fixed-session manifest builder are implemented by the fixed-scope software
described here. `capture_colocated_v1` still requires exact production-adopted
canonical `master`. For `portable_execution_v1`, use
[`STATE_OF_PLAY.md`](STATE_OF_PLAY.md) and fresh Git proof to require the exact
owner-authorized, reviewed, CI-green remote branch named above; local `HEAD`,
its local branch tip, cached origin branch, and live canonical branch tip must
be identical, while local/cached/live canonical master are synchronized and
that master is an ancestor of the topic tip. The fixed-session manifest
builder and dated Stage 0/1-only substitute-gate decision below are preparation
only. Neither is temporal, credential, exchange-mutation, or trading
authorization.

The portable exception removes only master promotion. It does not make the
branch production-adopted or claim production-host integration, capture
recovery, or Scheduler state, and it does not remove any money, SDK,
credential, identity, geography, account, balance, allowance, zero-state,
order, cancellation, deadline, cleanup, or attended-confirmation gate.

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

## Immutable pilot envelope

- Dedicated isolated wallet funded with no more than **100 pUSD**
  of the exchange-supported settlement collateral verified during preflight.
- The first Stage 0/1 request is exactly **10 pUSD**. Any later authorized run
  budget must remain no more than its wallet cap and no more than **100 pUSD**.
- Exactly one weather market per run.
- Existing ceilings may be lowered but not raised: **25** daily loss, **25**
  event notional, **10** band notional, and **120 seconds** quote TTL.
  `weather.market.market_making_live_pilot` owns this mode-specific normalization;
  the general run orchestrator delegates to it before evaluating any gate.
- The Stage 0/1 lifecycle envelope is profile-bound. `capture_colocated_v1`
  retains a 120-second session envelope and 120-second public paper proof.
  `portable_execution_v1` uses a 240-second session envelope and a 600-second
  public paper proof; the latter is candidate-freshness evidence, not an order
  TTL or permission to leave an order resting for 600 seconds.
- Smallest current exchange-valid share size and current tick size, read from
  the selected book immediately before the order.
- Post-only limit orders only. No marketable retry after a post-only rejection.
- No naked sell. A sell requires verified owned outcome inventory; otherwise
  express the complementary side with a backed buy.
- No overnight or unattended first session. End with cancel-all plus an
  authenticated query proving zero open orders.
- Do not assume liquidity rewards. Model the current documented maker rebate
  only after market-level fee eligibility is verified. Treat an unpaid or
  sub-threshold estimate as unrealized.

## Prerequisites

All must be current for the target date and selected market:

1. Continuous execution capture remains running on the dedicated capture PC
   and has produced rows. A `capture_colocated_v1` session validates that state
   locally. A `portable_execution_v1` session does not consume or claim remote
   capture-host health; its lifecycle receipt is therefore not simultaneous
   capture-health or streak evidence.
2. The International economics snapshot passes and matches the live platform.
3. Before the first lifecycle order, `mm_platform_bootstrap_v0.4` passes for
   the exact token and condition. This non-order, at-most-one-hour-old artifact
   proves the isolated wallet identity, recorded cap, numeric collateral
   balance and allowance each backing the requested budget, a content-bound
   account snapshot, an observed zero open-order count, fresh pre-mutation
   geographic eligibility, current book/min size/tick/neg-risk, market fee
   eligibility, a non-posting signed-order preview bound to the exact EOA/API
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
   book/min-size/tick/neg-risk/fee endpoint evidence has been read within 10
   seconds.
6. **Dated Stage 0/1 readiness decision: approved 2026-08-23; exact Git
   authority must be proved from `STATE_OF_PLAY.md` and the live remote.** The general readiness
   prerequisite is circular for the evidence-generating probes because
   `mm_platform_verification_v0.6` embeds
   both Stage 1 lifecycle proofs. For Stage 0/1 only, the operator approved the
   following exact non-circular substitute gates: current exact-tip production
   inventory; public credential references; target-date public book, paper, and
   International economics evidence; current market rules; fixed non-raisable
   10 pUSD order and 100 pUSD wallet caps; execution-host, clock, reboot, and
   workload-lease health plus capture/tape/streak health when using the
   colocated profile; zero unknown open orders and zero starting
   positions; successful Stage 0 bootstrap before Stage 1; fresh geographic
   eligibility; and every stage-specific, hash-bound attended confirmation.
   This decision is not self-executing and cannot clear the HOLD until the
   complete implementation receives exact-tip reproof. For the capture profile
   that means production-adopted master. For the portable profile only, the
   exact reviewed, CI-green, owner-authorized
   `codex/portable-execution-host-clean-20260827` remote branch may substitute
   under the branch/master equality and ancestry contract above. The ordinary
   maker-run live-readiness, target-date data-layer,
   production release, full risk, and v0.6 platform gates remain unchanged for
   Stage 2.
7. A simultaneous one-market paper counterfactual has quote permission and is
   writing auditable artifacts. The following command is only an interface
   illustration for a host that already owns the canonical default capture
   tree; it is **not** the portable-host command:

   ```text
   .\venv\Scripts\python.exe -m weather.market.market_making_run --date <YYYY-MM-DD> --budget-usdc 25 --mode paper-live-forward --permission-profile market_harvest --markets <market-id> --once
   ```

   On a clean portable executor, do not run that abbreviated form. Use the
   attempt-local public-substrate sequence below, including every explicit
   snapshot, observation, metadata-validation, economics, run-root, run-id,
   and 600-second quote-TTL binding.

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
   `live_trade_permission` is always false. Zero quote-permission rows means no
   live test. The Stage 1 selector must read the retained `run_config.json` and
   `quote_intents_long.csv`, stream and hash the complete quote tape, and bind a
   still-current successful row for the exact selected condition and token.
   The resulting plan remains non-authorizing; Stage 0, account state, current
   market rules, the literal confirmation, and the
   one-submit adapter capability remain independent mutation gates.
8. Select exactly one immutable execution-host profile. For
   `capture_colocated_v1`, the complete candidate-derived execution window
   **plus the fixed 20-second cooperative-cleanup reserve** must remain inside
   the target date and **[00:30, 09:00) America/Toronto**; 08:59:40 is the
   latest execution cutoff. For `portable_execution_v1`, the same bounded
   window and cleanup reserve must remain within one local execution date in
   the immutable candidate's market timezone, and the market target date must
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

## Staged protocol

### Stage 0: no-order account proof

Stage 0 never submits an order, but it does send authenticated heartbeat and
cancel-all/cleanup writes. Its v0.2 command, v0.6 execution, and v0.4 session-run
receipts therefore record `order_submit_attempted=false` separately from
`authenticated_exchange_write_attempted=true`; generic exchange mutation is
also true. Calling Stage 0 fully read-only is incorrect.

- Fill the public `mm_stage0_client_identity_v0.3` manifest. It binds only the
  International platform, chain, pinned SDK, public wallet topology,
  isolated-wallet declaration, capital cap, and the literal
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
- Read the chosen book, market fee eligibility, min order size, tick size, and
  closed-only state immediately before mutation.

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
- Submit one far-from-mid, smallest-valid, post-only buy with notional no more
  than the band cap.
- After the pre-submit host attestor, force an uncached authenticated collateral
  balance/allowance read. The balance must back the exact 10 pUSD request and
  remain at or below the isolated-wallet 100 pUSD funding cap; the minimum
  allowance must back 10 pUSD. Record the normalized snapshot hash before
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
10 pUSD bootstrap request, a wallet cap no higher than 100 pUSD, and each
reported order at or below 10 pUSD; upstream PASS booleans do not substitute
for these numeric checks. Do not hand-author those facts. The tracked bundle
template is deliberately fail-safe.

Stage 1 is the only order mutation allowed from the bootstrap artifact. Its
completed, content-bound lifecycle bundle upgrades platform proof to
`mm_platform_verification_v0.6`. The ordinary `market_making_run` live-pilot
path continues to require that stronger artifact and must never accept the
bootstrap artifact. Version v0.5 embeds the bundle and its SHA-256, rechecks
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
finite positive requested budget, isolated-wallet cap, and 100 pUSD operator
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

The final sequence runs from one clean, exact remote-synchronized checkout. It
may be the production-adopted master checkout on the dedicated capture PC under
`capture_colocated_v1`, or the exact operator-authorized portable branch on a
separately provisioned Windows PC under `portable_execution_v1`. Follow
[`PORTABLE_LIVE_EXECUTION_HOST.md`](PORTABLE_LIVE_EXECUTION_HOST.md) for every
second-PC deployment or later relocation. Public metadata, economics, paper
evidence, candidate selection, credentials, and attempt manifests must be
regenerated on the chosen execution host. Never put a secret value in the
command line, environment, identity manifest, output path, or shell history.

For `capture_colocated_v1`, plan the entire candidate-derived execution window
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
lease. The capture profile must prove `HEAD == master == cached origin/master ==
live canonical refs/heads/master`. The portable profile must prove
`HEAD == local codex/portable-execution-host-clean-20260827 == cached
origin/codex/portable-execution-host-clean-20260827 == live canonical
refs/heads/codex/portable-execution-host-clean-20260827`; it must separately
prove local master equals cached and live canonical master and is an ancestor
of that branch tip. It must also match the exact tracked host/principal and the
operator-recorded reviewed, exact-head CI-green authorization. Do not trade
merely because Windows restarted successfully or because a branch was pushed.

Do not continue merely because a public endpoint classifies the host's egress
as unblocked. Eligibility also follows the attended operator's and execution
host's real physical location. A session in a blocked location must stop;
VPN/proxy/location circumvention is not an allowed workaround.

After that host audit, prepare the identity and public credential
receipt/reference sources first;
they do not bind a market. Only after both preparations pass, discover the
exact Stage 0/1 scope from fresh public data and a successful one-market paper
tick, then run all three manifest builds without pausing past the plan expiry.
The canonical keyless doctor runs later, only inside each sealed wrapper. Do not
hand-pick a condition/token pair or retain one from a prior day. The first unconstrained
selector output is **discovery only**: it supplies a reviewed scope for
session-manifest preparation, but its null `expected_bootstrap_scope` means
the sealer correctly refuses it as a live candidate.
The metadata refresh's `--metadata-only` mode leaves the tracked location
registry byte-for-byte unchanged. The selector authenticates nowhere and can
neither place nor cancel an order; it requires a passing content-bound
International economics snapshot, a current paper-only market-harvest quote,
and current book rules, then emits a content-hashed plan that explicitly is not
trading authorization:

Collection is not baseline acceptance. The operator must inspect and explicitly
accept the exact snapshot, verify the supplied drift report is `PASS` with
`rescore_required=false`, then acknowledge the exact target date, selected
condition/token, accepted-snapshot file hash, and drift-report file hash. The
first selector call without that literal is intentionally a review-only BLOCK;
copying a file into place cannot satisfy informed acceptance. A refreshed
baseline, different candidate, token, or date requires a new review and literal.
The review and approved plans must use distinct exclusive-new paths; never aim
the review-only call at a fixed session candidate inbox or overwrite either
artifact.

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
$pilotMarketId = "replace-with-one-built-in-market-id"
$pilotExecutionHostProfile = "portable_execution_v1" # or capture_colocated_v1
if ($pilotExecutionHostProfile -eq "portable_execution_v1") {
  $pilotExpectedSessionSeconds = 240
  $pilotPaperQuoteTtlSeconds = 600
  $pilotPaperQuoteTtlConfig = "quote_ttl_seconds=600"
} elseif ($pilotExecutionHostProfile -eq "capture_colocated_v1") {
  $pilotExpectedSessionSeconds = 120
  $pilotPaperQuoteTtlSeconds = 120
  $pilotPaperQuoteTtlConfig = "quote_ttl_seconds=120"
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
# Snapshot CAS leaves can approach the legacy Windows path limit. Keep later
# stage refreshes in this compact, attempt-bound sibling namespace.
$pilotStageRefreshBase = Join-Path $pilotStateRoot "r"
$pilotStageRefreshParent = Join-Path $pilotStageRefreshBase $pilotAttemptId
$pilotDiscoveryPlan = Join-Path $pilotPublicRoot ($pilotAttemptId + "-discovery.json")
$pilotIdentitySource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-identity.json")
$pilotIdentityReceipt = Join-Path $pilotPublicRoot ($pilotAttemptId + "-identity-receipt.json")
$pilotCredentialProvisioningManifest = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-provisioning-references.json")
$pilotCredentialProvisioningReceipt = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-provisioning-receipt.json")
$pilotCredentialManifestSource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-verified-references.json")
$pilotCredentialReceiptSource = Join-Path $pilotPublicRoot ($pilotAttemptId + "-credential-verified-receipt.json")
$pilotSubstrateRoot = Join-Path $pilotPublicRoot ($pilotAttemptId + "-candidate-substrate")
$pilotEventMetadata = Join-Path $pilotSubstrateRoot "location-market-events.json"
$pilotEventValidation = Join-Path $pilotSubstrateRoot "event-metadata-validation.json"
$pilotObservationStatus = Join-Path $pilotSubstrateRoot "observation-status.json"
$pilotSnapshotsRoot = Join-Path $pilotSubstrateRoot "snapshots"
$pilotEconomicsSnapshot = Join-Path $pilotSubstrateRoot "exchange-economics.json"
$pilotAcceptedEconomics = Join-Path $pilotSubstrateRoot "exchange-economics-accepted.json"
$pilotEconomicsDrift = Join-Path $pilotSubstrateRoot "exchange-economics-drift.json"
$paperRunId = "pilot-paper-" + [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$paperRunsRoot = Join-Path $pilotSubstrateRoot "paper-runs"
$paperRunFolder = Join-Path $paperRunsRoot (Join-Path $pilotTargetDate $paperRunId)

New-Item -ItemType Directory -Path $pilotPublicRoot -Force | Out-Null
New-Item -ItemType Directory -Path $pilotAttemptsParent -Force | Out-Null
New-Item -ItemType Directory -Path $pilotStageRefreshBase -Force | Out-Null
$pilotPublicRoot = Get-VerifiedPilotLocalPath $pilotPublicRoot
$pilotAttemptsParent = Get-VerifiedPilotLocalPath $pilotAttemptsParent
$pilotStageRefreshBase = Get-VerifiedPilotLocalPath $pilotStageRefreshBase
if (Test-Path -LiteralPath $pilotStageRefreshParent) {
  throw "attempt-bound stage refresh namespace must be new"
}
New-Item -ItemType Directory -Path $pilotStageRefreshParent `
  -ErrorAction Stop | Out-Null
$pilotStageRefreshParent = Get-VerifiedPilotLocalPath $pilotStageRefreshParent
if (Test-Path -LiteralPath $pilotSubstrateRoot) {
  throw "candidate substrate namespace must be new"
}
New-Item -ItemType Directory -Path $pilotSubstrateRoot -ErrorAction Stop |
  Out-Null
$pilotSubstrateRoot = Get-VerifiedPilotLocalPath $pilotSubstrateRoot
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
  --wallet-cap 100 `
  --identity-out $pilotIdentitySource `
  --receipt-out $pilotIdentityReceipt `
  --confirm-international-platform `
  --confirm-isolated-wallet `
  --confirmation INTERNATIONAL_POLYMARKET_PREPARE_STAGE0_IDENTITY
$identityPreparationExit = $LASTEXITCODE
$identityPreparation = $identityPreparationOutput |
  ConvertFrom-Json -ErrorAction Stop
if ($identityPreparationExit -ne 0 -or
    $identityPreparation.status -cne "PASS") {
  throw "public identity preparation blocked"
}
```

Only after identity preparation passes, create the four secret values as
Windows Credential Manager generic credentials. Compare-only verification of
entries created by an earlier reviewed import is not provisioning and does not
replace the identity gate. If an external source file is used, keep it outside
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

Choose the provisioning branch before executing it. Set the Boolean below to
`$true` only for a new host/principal whose four fixed targets are known empty.
Set it to `$false` only when a prior reviewed clean create receipt for this same
host/principal proves those targets were intentionally provisioned. Never turn
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
}
```

An occupancy refusal is not permission to overwrite or delete an existing
target. Whether the selected branch just provisioned the four entries or a
prior reviewed import did so, use distinct new verified-output paths and opt in
explicitly to the compare-only path required by the session builder:

```powershell
$ErrorActionPreference = "Stop"
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

Both tuples remain valid importer evidence, so a clean installation can retain
its create-new receipt as provisioning history. The first-session manifest
builder and fixed-scope sealer are stricter: they accept only a v0.4
`verify_existing_exact` tuple generated for the current execution host and
Windows token principal within two hours, with all four existing entries
verified, zero written, and `credential_store_mutation_attempted=false`. A
create-new, legacy, stale, other-host, or other-principal receipt cannot be
staged or sealed; run the attended compare-only path into a new output
namespace first.

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

Only now start the expiring discovery and manifest-build sequence:

```powershell
$ErrorActionPreference = "Stop"
.\venv\Scripts\python.exe -m weather.operations.location_config_refresh `
  --locations .\config\locations.json `
  --event-metadata $pilotEventMetadata `
  --metadata-only
if ($LASTEXITCODE -ne 0) { throw "event metadata refresh failed" }

.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation `
  --target-date $pilotTargetDate `
  --markets $pilotMarketId `
  --locations .\config\locations.json `
  --event-metadata $pilotEventMetadata `
  --json-out $pilotEventValidation `
  --report-out (Join-Path $pilotSubstrateRoot "event-metadata-validation.md") `
  --max-age-hours 2 `
  --require-pass
if ($LASTEXITCODE -ne 0) { throw "event metadata validation blocked" }

.\venv\Scripts\python.exe -m weather.operations.observation_trigger once `
  --market $pilotMarketId `
  --target-date $pilotTargetDate `
  --source-cache-root (Join-Path $pilotSubstrateRoot "observation-source-cache") `
  --status-out $pilotObservationStatus `
  --events-out (Join-Path $pilotSubstrateRoot "observation-events.jsonl") `
  --diagnostics-out (Join-Path $pilotSubstrateRoot "observation-diagnostics.jsonl") `
  --trigger-queue-root (Join-Path $pilotSubstrateRoot "observation-trigger-queue") `
  --dry-run `
  --strict
if ($LASTEXITCODE -ne 0) { throw "selected-market observation collection blocked" }

.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker `
  --force `
  --market $pilotMarketId `
  --date $pilotTargetDate `
  --snapshots-root $pilotSnapshotsRoot `
  --event-metadata $pilotEventMetadata `
  --result-json (Join-Path $pilotSubstrateRoot "weather-capture-result.json") `
  --require-pass
if ($LASTEXITCODE -ne 0) { throw "selected-market weather/source capture blocked" }

.\venv\Scripts\python.exe -m weather.market.market_microstructure capture `
  --market $pilotMarketId `
  --date $pilotTargetDate `
  --snapshots-root $pilotSnapshotsRoot `
  --event-metadata $pilotEventMetadata `
  --outcomes all `
  --no-price-history `
  --no-websocket-events `
  --clob-features `
  --require-pass
if ($LASTEXITCODE -ne 0) { throw "selected-market CLOB capture blocked" }

.\venv\Scripts\python.exe -m weather.market.exchange_economics collect-global `
  --event-metadata $pilotEventMetadata `
  --snapshot $pilotEconomicsSnapshot `
  --target-date $pilotTargetDate `
  --max-age-hours 2
if ($LASTEXITCODE -ne 0) { throw "International economics collection failed" }

# Stop here and inspect the complete current snapshot. This is a human decision,
# not a collector side effect. Accept only after the economics and payout-asset
# conflict are understood.
.\venv\Scripts\python.exe -m weather.market.exchange_economics accept `
  --snapshot $pilotEconomicsSnapshot `
  --accepted-snapshot $pilotAcceptedEconomics `
  --json-out $pilotEconomicsDrift `
  --target-date $pilotTargetDate `
  --max-age-hours 2 `
  --acknowledge-payout-asset-conflict
if ($LASTEXITCODE -ne 0) { throw "reviewed economics acceptance failed" }

.\venv\Scripts\python.exe -m weather.market.market_making_run `
  --date $pilotTargetDate `
  --budget-usdc 25 `
  --mode paper-live-forward `
  --permission-profile market_harvest `
  --markets $pilotMarketId `
  --snapshots-root $pilotSnapshotsRoot `
  --observation-status $pilotObservationStatus `
  --event-metadata-validation $pilotEventValidation `
  --exchange-economics-snapshot $pilotEconomicsSnapshot `
  --runs-root $paperRunsRoot `
  --run-id $paperRunId `
  --config $pilotPaperQuoteTtlConfig `
  --once `
  --require-preflight-pass
if ($LASTEXITCODE -ne 0) { throw "strict paper market-harvest tick blocked" }

$pilotSubstratePreflight = Join-Path $pilotSubstrateRoot "portable-candidate-preflight.json"
.\venv\Scripts\python.exe -m weather.market.portable_live_candidate_preflight `
  --market $pilotMarketId `
  --target-date $pilotTargetDate `
  --event-metadata $pilotEventMetadata `
  --event-metadata-validation $pilotEventValidation `
  --snapshots-root $pilotSnapshotsRoot `
  --observation-status $pilotObservationStatus `
  --economics-snapshot $pilotEconomicsSnapshot `
  --accepted-economics-snapshot $pilotAcceptedEconomics `
  --economics-drift-report $pilotEconomicsDrift `
  --paper-run-config (Join-Path $paperRunFolder "run_config.json") `
  --paper-preflight (Join-Path $paperRunFolder "preflight.json") `
  --paper-quote-intents (Join-Path $paperRunFolder "quote_intents_long.csv") `
  --json-out $pilotSubstratePreflight
if ($LASTEXITCODE -ne 0) { throw "portable public candidate substrate audit blocked" }

# The first selector call is deliberately review-only: without the exact
# candidate/date/evidence literal it writes BLOCK and returns 1.
$pilotDiscoveryReviewPlan = $pilotDiscoveryPlan + ".review.json"
.\venv\Scripts\python.exe -m weather.market.mm_live_candidate_cli `
  --economics-snapshot $pilotEconomicsSnapshot `
  --accepted-economics-snapshot $pilotAcceptedEconomics `
  --economics-drift-report $pilotEconomicsDrift `
  --target-date $pilotTargetDate `
  --paper-run-config (Join-Path $paperRunFolder "run_config.json") `
  --paper-quote-intents (Join-Path $paperRunFolder "quote_intents_long.csv") `
  --substrate-preflight $pilotSubstratePreflight `
  --plan-out $pilotDiscoveryReviewPlan
if ($LASTEXITCODE -ne 1) { throw "economics acceptance review plan had an unexpected result" }

$pilotReviewPlan = Get-Content -LiteralPath $pilotDiscoveryReviewPlan -Raw | ConvertFrom-Json
if (
  $pilotReviewPlan.status -ne "BLOCK" -or
  $pilotReviewPlan.missing -notcontains "explicit_candidate_economics_baseline_acknowledgment"
) { throw "selector did not stop for informed economics acceptance" }
Get-Content -LiteralPath $pilotAcceptedEconomics -Raw
Get-Content -LiteralPath $pilotEconomicsDrift -Raw
$pilotEconomicsAcknowledgment = Read-Host "After reviewing both files, paste the exact required economics acknowledgment"
if ($pilotEconomicsAcknowledgment -cne [string]$pilotReviewPlan.economics_acceptance.required_operator_acknowledgment) {
  throw "economics acknowledgment was not exact"
}

.\venv\Scripts\python.exe -m weather.market.mm_live_candidate_cli `
  --economics-snapshot $pilotEconomicsSnapshot `
  --accepted-economics-snapshot $pilotAcceptedEconomics `
  --economics-drift-report $pilotEconomicsDrift `
  --economics-baseline-acknowledgment $pilotEconomicsAcknowledgment `
  --target-date $pilotTargetDate `
  --paper-run-config (Join-Path $paperRunFolder "run_config.json") `
  --paper-quote-intents (Join-Path $paperRunFolder "quote_intents_long.csv") `
  --substrate-preflight $pilotSubstratePreflight `
  --plan-out $pilotDiscoveryPlan
if ($LASTEXITCODE -ne 0) { throw "approved discovery candidate selection blocked" }

$pilotPlan = Get-Content -LiteralPath $pilotDiscoveryPlan -Raw | ConvertFrom-Json
if (
  $pilotPlan.status -ne "PASS" -or
  $pilotPlan.selection_is_trading_authorization -or
  [DateTimeOffset]::Parse($pilotPlan.expires_at_utc) -le [DateTimeOffset]::UtcNow
) {
  throw "Stage 1 public candidate selection did not pass"
}
$pilotConditionId = [string]$pilotPlan.selected.condition_id
$pilotTokenId = [string]$pilotPlan.selected.token_id
```

The manifest builder stages the unconstrained discovery plan, but the fixed-scope
sealer never accepts it as a live candidate. After the three exact-scope session
manifests and outer launchers are independently reviewed, run a **new**
one-market paper tick and selector immediately before Stage 0, using new output
paths plus `--expected-condition-id $pilotConditionId` and
`--expected-token-id $pilotTokenId`, and write that constrained plan only to the
Stage 0 launcher's fixed candidate inbox. Repeat a new paper tick and the same
constrained selector immediately before each Stage 1 mode. Every plan expires
at the earlier of five minutes or the selected paper row's quote TTL. The
canonical paper tick uses 120 seconds for `capture_colocated_v1` and passes
`--config quote_ttl_seconds=600` for `portable_execution_v1`. The portable
no-network substrate-preflight receipt binds its own path plus the exact
absolute paths and SHA-256 hashes of all 12 consumed artifacts; all 13 file
identities must be distinct. It is accepted for no more than 600 seconds,
while the constrained candidate plan still expires after at most 300 seconds.
Refresh the economics snapshot too when its own gate expires. A constrained refresh must
select the exact reviewed scope or block;
it cannot silently switch markets after discovery or authenticated bootstrap.
Stage 0 still rereads the exact book and fails closed on any condition, token,
min-size, tick, neg-risk, fee, or closed-state drift. The constrained candidate
binds `fee_rate` exactly to the current endpoint as
`fee_rate_bps / 10000` and binds the exact Boolean neg-risk state. Stage 1
repeats both comparisons when preparing the intent and again after the host
attestor, immediately before its submit-deadline event. A zero fee or any
fee/neg-risk drift therefore fails before `submit_started` and `post_order`.
The candidate's minimum-tick intent is only a far-from-mid lifecycle probe and
will normally not qualify for
liquidity rewards or provide maker-fill economics evidence. Stage 2 must use a
separate current quote decision after Stage 1 passes.

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
query of the profile-authorized ref against that literal canonical URL. The
capture profile remains master-only. On the pre-adoption exception path, the
portable profile accepts only `codex/portable-execution-host-clean-20260827`,
and only when local `HEAD`, the
local branch, cached origin branch, and live canonical branch object ID are
identical; local/cached/live master must also be synchronized and that master
must be an ancestor of the branch. A stale cached ref, malformed result,
timeout, unavailable remote, detached checkout, dirty tree, master drift, or
missing ancestry blocks. It derives the Git tree, interpreter, template,
complete live source, and session-bootstrap hashes, and hardcodes 10 pUSD plus
the profile-bound 120-second colocated or 240-second portable session envelope. It
accepts no typed target, condition, token, budget, duration, output, or candidate
override. Scope comes only from the complete candidate-discovery gate after it
revalidates the still-current, unconstrained, self-hashed, non-authorizing
International/pUSD plan, economics PASS, paper permission and no-mutation
evidence, evidence hashes and row count, and current book/risk/intent contract.
It never opens Credential Manager or calls the exchange.

The earlier `init-attempt` command creates a new external root with ACL
inheritance disabled and FullControl granted only to the current user, SYSTEM,
and Administrators, then validates the root plus `inputs`, `incoming`, and
`session`. A pre-existing root is spent and cannot be adopted. `prepare-manifest`
exclusively copies the reviewed public source files byte-for-byte into these
stage-specific canonical names. Each stage also receives immutable
`*-accepted-economics-snapshot.json` and `*-economics-drift-report.json` copies;
their raw hashes and the candidate/date-specific acknowledgment are carried in
the v0.4 candidate, v0.4 session manifest, and v0.4 seal spec and revalidated by
the fixed-scope sealer:

| Stage | Identity | Import receipt | Reference manifest | Discovery copy | Manifest / build receipt | Candidate inbox |
| --- | --- | --- | --- | --- | --- | --- |
| `stage0` | `inputs/stage0-identity.json` | `inputs/stage0-credential-import-receipt.json` | `inputs/stage0-credential-reference-manifest.json` | `inputs/stage0-discovery-plan.json` | `inputs/stage0-session-manifest.json` / `inputs/stage0-session-manifest-build-receipt.json` | `incoming/fresh-stage0-candidate.json` |
| `stage1_cancel_all` | `inputs/stage1-identity.json` | `inputs/stage1-cancel-all-credential-import-receipt.json` | `inputs/stage1-cancel-all-credential-reference-manifest.json` | `inputs/stage1-cancel-all-discovery-plan.json` | `inputs/stage1_cancel_all-session-manifest.json` / `inputs/stage1-cancel-all-session-manifest-build-receipt.json` | `incoming/fresh-stage1_cancel_all-candidate.json` |
| `stage1_dead_man` | `inputs/stage1-dead-man-identity.json` | `inputs/stage1-dead-man-credential-import-receipt.json` | `inputs/stage1-dead-man-credential-reference-manifest.json` | `inputs/stage1-dead-man-discovery-plan.json` | `inputs/stage1_dead_man-session-manifest.json` / `inputs/stage1-dead-man-session-manifest-build-receipt.json` | `incoming/fresh-stage1_dead_man-candidate.json` |

Each copy, manifest, raw sidecar, and build receipt is exclusive-new. A partial
failure spends that stage namespace. The optional
`--reviewed-status-flags-json` source must be a JSON list whose rows have exactly
`sha256` and a 12-500 character `review`; it is also copied to the corresponding
stage-specific `inputs/*-reviewed-status-flags.json`. Omit the option only when
the reviewed list is empty. The option is forbidden for
`portable_execution_v1`, because capture-host exceptions cannot be transferred
to an execution-only PC.

Prepare all three manifests from the same reviewed discovery plan while it is
still current. The distinct workload strings prevent one stage from reusing
another stage's host lease:

```powershell
$ErrorActionPreference = "Stop"
$pilotManifestStages = @(
  [pscustomobject]@{ Stage = "stage0"; Workload = $attemptInit.lease_workloads.stage0 },
  [pscustomobject]@{ Stage = "stage1_cancel_all"; Workload = $attemptInit.lease_workloads.stage1_cancel_all },
  [pscustomobject]@{ Stage = "stage1_dead_man"; Workload = $attemptInit.lease_workloads.stage1_dead_man }
)

foreach ($row in $pilotManifestStages) {
  .\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer prepare-manifest `
    --stage $row.Stage `
    --discovery-plan $pilotDiscoveryPlan `
    --identity-source $pilotIdentitySource `
    --credential-import-receipt-source $pilotCredentialReceiptSource `
    --credential-reference-manifest-source $pilotCredentialManifestSource `
    --accepted-economics-snapshot-source $pilotAcceptedEconomics `
    --economics-drift-report-source $pilotEconomicsDrift `
    --attempt-root $pilotAttemptRoot `
    --lease-workload $row.Workload `
    --execution-host-profile $pilotExecutionHostProfile
  if ($LASTEXITCODE -ne 0) { throw "fixed-session manifest preparation blocked for $($row.Stage)" }
}
```

Each output manifest is `international_live_fixed_session_manifest_v0.4`; its
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
sidecar, production, scope, staged public-input hashes, compare-only credential
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

The outer session launcher composes the candidate-bounded seal spec and invokes
the fixed-scope sealer; operators do not hand-author or directly invoke that
inner surface. The sealer never opens Credential Manager or runs the generated
launcher. It independently validates the inert SDK overlay helper, candidate
semantic hash, a paper TTL no greater than 600 seconds, same-target-date
containment including the shared 20-second cleanup reserve for
`capture_colocated_v1`, and current-or-next target-date eligibility with one
market-local execution date for `portable_execution_v1`,
including complete **[00:30, 09:00) America/Toronto** containment for the
colocated profile,
all public inputs, every imported live-source hash, exact production ancestry,
and new contained output paths. It creates a fixed no-argument Python wrapper,
a hash-bound inner PowerShell launcher, an
`international_live_fixed_scope_seal_v0.6` receipt, and its SHA-256 sidecar.
Each Stage 1 mode also requires the exact successful predecessor lineage. A
partial or failed build, seal, or run spends that stage namespace; create a new
attempt rather than overwriting it.

The discovery plan is not the candidate. Immediately before Stage 0, create a
new paper run and a new constrained selector output at the outer launcher's
fixed inbox. This is the required discovery-then-fresh-candidate sequence:

```powershell
$ErrorActionPreference = "Stop"
$stage0ReviewPath = Join-Path $pilotAttemptRoot "session\stage0-launcher-review.json"
$stage0ReviewSidecarPath = $stage0ReviewPath + ".sha256"
$stage0ReviewHash = (Get-FileHash -LiteralPath $stage0ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedStage0ReviewSidecar = $stage0ReviewHash + "  " + [IO.Path]::GetFileName($stage0ReviewPath) + "`n"
if ([IO.File]::ReadAllText($stage0ReviewSidecarPath, [Text.Encoding]::ASCII) -cne
    $expectedStage0ReviewSidecar) {
  throw "Stage 0 launcher-review sidecar does not bind the exact review bytes"
}
$stage0Review = Get-Content -LiteralPath $stage0ReviewPath -Raw | ConvertFrom-Json
$expectedStage0CandidateInbox = [IO.Path]::GetFullPath(
  (Join-Path $pilotAttemptRoot "incoming\fresh-stage0-candidate.json")
)
$expectedStage0ManifestPath = [IO.Path]::GetFullPath(
  (Join-Path $pilotAttemptRoot "inputs\stage0-session-manifest.json")
)
if (
  $stage0Review.status -cne "PASS" -or
  [string]$stage0Review.stage -cne "stage0" -or
  -not $stage0Review.no_argument_surface -or
  [IO.Path]::GetFullPath([string]$stage0Review.candidate_inbox) -cne
    $expectedStage0CandidateInbox -or
  [IO.Path]::GetFullPath([string]$stage0Review.session_manifest.path) -cne
    $expectedStage0ManifestPath
) {
  throw "Stage 0 outer-launcher review did not pass"
}
$observedStage0LauncherHash = (Get-FileHash -LiteralPath $stage0Review.launcher.path -Algorithm SHA256).Hash.ToLowerInvariant()
if ($observedStage0LauncherHash -cne ([string]$stage0Review.launcher.sha256).ToLowerInvariant()) {
  throw "Stage 0 outer launcher differs from its immutable review"
}
if ((Get-FileHash -LiteralPath $expectedStage0ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
    ([string]$stage0Review.session_manifest.sha256).ToLowerInvariant()) {
  throw "Stage 0 session manifest differs from its immutable review"
}
$stage0Manifest = Get-Content -LiteralPath $stage0Review.session_manifest.path -Raw | ConvertFrom-Json
if (
  [string]$stage0Manifest.scope.execution_host_profile -cne $pilotExecutionHostProfile -or
  [int]$stage0Manifest.scope.max_session_seconds -ne $pilotExpectedSessionSeconds
) {
  throw "Stage 0 manifest does not preserve the selected execution-host profile"
}
if (Test-Path -LiteralPath $expectedStage0CandidateInbox) {
  throw "Stage 0 fixed candidate inbox is already spent"
}

$freshStage0Id = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$freshStage0Parent = Join-Path $pilotStageRefreshParent "s0"
New-Item -ItemType Directory -Path $freshStage0Parent -Force `
  -ErrorAction Stop | Out-Null
$freshStage0Parent = Get-VerifiedPilotLocalPath $freshStage0Parent
$freshStage0Root = Join-Path $freshStage0Parent $freshStage0Id
$freshStage0EventMetadata = Join-Path $freshStage0Root "location-market-events.json"
$freshStage0Validation = Join-Path $freshStage0Root "event-metadata-validation.json"
$freshStage0Observation = Join-Path $freshStage0Root "observation-status.json"
$freshStage0Snapshots = Join-Path $freshStage0Root "snapshots"
$freshStage0PaperRuns = Join-Path $freshStage0Root "paper-runs"
$freshStage0PaperRunId = "pilot-stage0-paper-" + $freshStage0Id
$freshStage0PaperFolder = Join-Path $freshStage0PaperRuns (Join-Path $pilotTargetDate $freshStage0PaperRunId)
if (Test-Path -LiteralPath $freshStage0Root) { throw "Stage 0 refresh namespace must be new" }
New-Item -ItemType Directory -Path $freshStage0Root -ErrorAction Stop |
  Out-Null
$freshStage0Root = Get-VerifiedPilotLocalPath $freshStage0Root

.\venv\Scripts\python.exe -m weather.operations.location_config_refresh `
  --locations .\config\locations.json `
  --event-metadata $freshStage0EventMetadata `
  --metadata-only
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 metadata refresh failed" }

.\venv\Scripts\python.exe -m weather.operations.event_metadata_validation `
  --target-date $pilotTargetDate `
  --markets $pilotMarketId `
  --locations .\config\locations.json `
  --event-metadata $freshStage0EventMetadata `
  --json-out $freshStage0Validation `
  --report-out (Join-Path $freshStage0Root "event-metadata-validation.md") `
  --max-age-hours 2 `
  --require-pass
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 metadata validation blocked" }

.\venv\Scripts\python.exe -m weather.operations.observation_trigger once `
  --market $pilotMarketId `
  --target-date $pilotTargetDate `
  --source-cache-root (Join-Path $freshStage0Root "observation-source-cache") `
  --status-out $freshStage0Observation `
  --events-out (Join-Path $freshStage0Root "observation-events.jsonl") `
  --diagnostics-out (Join-Path $freshStage0Root "observation-diagnostics.jsonl") `
  --trigger-queue-root (Join-Path $freshStage0Root "observation-trigger-queue") `
  --dry-run `
  --strict
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 observation capture blocked" }

.\venv\Scripts\python.exe -m weather.collection.snapshot_tracker `
  --force --market $pilotMarketId --date $pilotTargetDate `
  --snapshots-root $freshStage0Snapshots `
  --event-metadata $freshStage0EventMetadata `
  --result-json (Join-Path $freshStage0Root "weather-capture-result.json") `
  --require-pass
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 weather capture blocked" }

.\venv\Scripts\python.exe -m weather.market.market_microstructure capture `
  --market $pilotMarketId --date $pilotTargetDate `
  --snapshots-root $freshStage0Snapshots `
  --event-metadata $freshStage0EventMetadata `
  --outcomes all --no-price-history --no-websocket-events --clob-features `
  --require-pass
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 CLOB capture blocked" }

.\venv\Scripts\python.exe -m weather.market.market_making_run `
  --date $pilotTargetDate `
  --budget-usdc 25 `
  --mode paper-live-forward `
  --permission-profile market_harvest `
  --markets $pilotMarketId `
  --snapshots-root $freshStage0Snapshots `
  --observation-status $freshStage0Observation `
  --event-metadata-validation $freshStage0Validation `
  --exchange-economics-snapshot $pilotEconomicsSnapshot `
  --runs-root $freshStage0PaperRuns `
  --run-id $freshStage0PaperRunId `
  --config $pilotPaperQuoteTtlConfig `
  --once `
  --require-preflight-pass
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 strict paper tick blocked" }

.\venv\Scripts\python.exe -m weather.market.portable_live_candidate_preflight `
  --market $pilotMarketId --target-date $pilotTargetDate `
  --event-metadata $freshStage0EventMetadata `
  --event-metadata-validation $freshStage0Validation `
  --snapshots-root $freshStage0Snapshots `
  --observation-status $freshStage0Observation `
  --economics-snapshot $pilotEconomicsSnapshot `
  --accepted-economics-snapshot $pilotAcceptedEconomics `
  --economics-drift-report $pilotEconomicsDrift `
  --paper-run-config (Join-Path $freshStage0PaperFolder "run_config.json") `
  --paper-preflight (Join-Path $freshStage0PaperFolder "preflight.json") `
  --paper-quote-intents (Join-Path $freshStage0PaperFolder "quote_intents_long.csv") `
  --json-out (Join-Path $freshStage0Root "portable-candidate-preflight.json")
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 public substrate audit blocked" }

.\venv\Scripts\python.exe -m weather.market.mm_live_candidate_cli `
  --economics-snapshot $pilotEconomicsSnapshot `
  --accepted-economics-snapshot $pilotAcceptedEconomics `
  --economics-drift-report $pilotEconomicsDrift `
  --economics-baseline-acknowledgment $pilotEconomicsAcknowledgment `
  --target-date $pilotTargetDate `
  --paper-run-config (Join-Path $freshStage0PaperFolder "run_config.json") `
  --paper-quote-intents (Join-Path $freshStage0PaperFolder "quote_intents_long.csv") `
  --substrate-preflight (Join-Path $freshStage0Root "portable-candidate-preflight.json") `
  --expected-condition-id $pilotConditionId `
  --expected-token-id $pilotTokenId `
  --plan-out ([string]$stage0Review.candidate_inbox)
if ($LASTEXITCODE -ne 0) { throw "fresh Stage 0 constrained candidate selection blocked" }

$stage0CandidateHash = (Get-FileHash -LiteralPath $stage0Review.candidate_inbox -Algorithm SHA256).Hash.ToLowerInvariant()
$stage0Candidate = Get-Content -LiteralPath $stage0Review.candidate_inbox -Raw | ConvertFrom-Json
if (
  $stage0Candidate.status -cne "PASS" -or
  $stage0Candidate.selection_is_trading_authorization -or
  [string]$stage0Candidate.selected.location_id -cne $pilotMarketId -or
  [string]$stage0Candidate.selected.event_date -cne $pilotTargetDate -or
  [string]$stage0Candidate.paper_quote_evidence.run_id -cne $freshStage0PaperRunId -or
  [int]$stage0Candidate.selected.paper_quote_proof.quote_ttl_seconds -ne $pilotPaperQuoteTtlSeconds -or
  [string]$stage0Candidate.selection_policy.expected_bootstrap_scope.condition_id -cne $pilotConditionId -or
  [string]$stage0Candidate.selection_policy.expected_bootstrap_scope.token_id -cne $pilotTokenId -or
  [string]$stage0Candidate.plan_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
  [DateTimeOffset]::Parse([string]$stage0Candidate.expires_at_utc) -le [DateTimeOffset]::UtcNow
) {
  throw "fresh Stage 0 constrained candidate did not pass exact scope"
}

# Do not cross this boundary while any HOLD in this runbook remains unresolved.
# After dated operator approval clears every HOLD, invoke only the reviewed path:
if (
  (Get-FileHash -LiteralPath $stage0ReviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $stage0ReviewHash -or
  (Get-FileHash -LiteralPath $stage0Review.launcher.path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $observedStage0LauncherHash -or
  (Get-FileHash -LiteralPath $stage0Review.candidate_inbox -Algorithm SHA256).Hash.ToLowerInvariant() -cne $stage0CandidateHash
) {
  throw "Stage 0 review, launcher, or candidate changed before invocation"
}
Write-Host "Stage 0 launcher-review SHA-256: $stage0ReviewHash"
Write-Host "Stage 0 candidate SHA-256: $stage0CandidateHash"
& ([string]$stage0Review.launcher.path)
if ($LASTEXITCODE -ne 0) { throw "Stage 0 reviewed launcher failed" }
```

Run this exact helper once for each Stage 1 mode. It creates a distinct refresh
root and paper run, verifies the stage-specific launcher review sidecar and
launcher/manifest hashes, writes only to that review's new fixed candidate
inbox, captures and rechecks the candidate's raw hash, and then invokes only the
reviewed no-argument launcher:

```powershell
$ErrorActionPreference = "Stop"
function Invoke-FreshReviewedStage1 {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("stage1_cancel_all", "stage1_dead_man")]
    [string]$Stage
  )

  $stageLabel = if ($Stage -eq "stage1_cancel_all") {
    "Stage 1 cancel-all"
  } else {
    "Stage 1 dead-man"
  }
  $reviewPath = Join-Path $pilotAttemptRoot ("session\" + $Stage + "-launcher-review.json")
  $reviewSidecarPath = $reviewPath + ".sha256"
  $reviewHash = (Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant()
  $expectedReviewSidecar = $reviewHash + "  " + [IO.Path]::GetFileName($reviewPath) + "`n"
  if ([IO.File]::ReadAllText($reviewSidecarPath, [Text.Encoding]::ASCII) -cne
      $expectedReviewSidecar) {
    throw "$stageLabel launcher-review sidecar does not bind the exact review bytes"
  }
  $review = Get-Content -LiteralPath $reviewPath -Raw | ConvertFrom-Json
  $expectedCandidateInbox = [IO.Path]::GetFullPath(
    (Join-Path $pilotAttemptRoot ("incoming\fresh-" + $Stage + "-candidate.json"))
  )
  $expectedLauncherPath = [IO.Path]::GetFullPath(
    (Join-Path $pilotAttemptRoot ("session\" + $Stage + "-launch.ps1"))
  )
  $expectedManifestPath = [IO.Path]::GetFullPath(
    (Join-Path $pilotAttemptRoot ("inputs\" + $Stage + "-session-manifest.json"))
  )
  if (
    $review.status -cne "PASS" -or
    [string]$review.stage -cne $Stage -or
    -not $review.no_argument_surface -or
    [IO.Path]::GetFullPath([string]$review.candidate_inbox) -cne $expectedCandidateInbox -or
    [IO.Path]::GetFullPath([string]$review.launcher.path) -cne $expectedLauncherPath -or
    [IO.Path]::GetFullPath([string]$review.session_manifest.path) -cne $expectedManifestPath
  ) {
    throw "$stageLabel review does not bind its canonical stage paths"
  }
  $launcherHash = (Get-FileHash -LiteralPath $expectedLauncherPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($launcherHash -cne ([string]$review.launcher.sha256).ToLowerInvariant()) {
    throw "$stageLabel outer launcher differs from its immutable review"
  }
  if ((Get-FileHash -LiteralPath $expectedManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne
      ([string]$review.session_manifest.sha256).ToLowerInvariant()) {
    throw "$stageLabel session manifest differs from its immutable review"
  }
  $sessionManifest = Get-Content -LiteralPath $expectedManifestPath -Raw | ConvertFrom-Json
  if (
    [string]$sessionManifest.stage -cne $Stage -or
    [string]$sessionManifest.scope.execution_host_profile -cne $pilotExecutionHostProfile -or
    [int]$sessionManifest.scope.max_session_seconds -ne $pilotExpectedSessionSeconds
  ) {
    throw "$stageLabel manifest does not preserve the selected execution-host profile"
  }
  if (Test-Path -LiteralPath $expectedCandidateInbox) {
    throw "$stageLabel fixed candidate inbox is already spent"
  }

  $freshId = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
  $stagePathCode = switch ($Stage) {
    "stage1_cancel_all" { "s1a" }
    "stage1_dead_man" { "s1d" }
    default { throw "unsupported Stage 1 refresh path scope" }
  }
  $freshParent = Join-Path $pilotStageRefreshParent $stagePathCode
  New-Item -ItemType Directory -Path $freshParent -Force `
    -ErrorAction Stop | Out-Null
  $freshParent = Get-VerifiedPilotLocalPath $freshParent
  $freshRoot = Join-Path $freshParent $freshId
  $freshEventMetadata = Join-Path $freshRoot "location-market-events.json"
  $freshValidation = Join-Path $freshRoot "event-metadata-validation.json"
  $freshObservation = Join-Path $freshRoot "observation-status.json"
  $freshSnapshots = Join-Path $freshRoot "snapshots"
  $freshPaperRuns = Join-Path $freshRoot "paper-runs"
  $freshPaperRunId = "pilot-" + $Stage + "-paper-" + $freshId
  $freshPaperFolder = Join-Path $freshPaperRuns (Join-Path $pilotTargetDate $freshPaperRunId)
  if (Test-Path -LiteralPath $freshRoot) {
    throw "$stageLabel refresh namespace must be new"
  }
  New-Item -ItemType Directory -Path $freshRoot -ErrorAction Stop |
    Out-Null
  $freshRoot = Get-VerifiedPilotLocalPath $freshRoot

  .\venv\Scripts\python.exe -m weather.operations.location_config_refresh `
    --locations .\config\locations.json `
    --event-metadata $freshEventMetadata `
    --metadata-only
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel metadata refresh failed" }

  .\venv\Scripts\python.exe -m weather.operations.event_metadata_validation `
    --target-date $pilotTargetDate `
    --markets $pilotMarketId `
    --locations .\config\locations.json `
    --event-metadata $freshEventMetadata `
    --json-out $freshValidation `
    --report-out (Join-Path $freshRoot "event-metadata-validation.md") `
    --max-age-hours 2 `
    --require-pass
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel metadata validation blocked" }

  .\venv\Scripts\python.exe -m weather.operations.observation_trigger once `
    --market $pilotMarketId `
    --target-date $pilotTargetDate `
    --source-cache-root (Join-Path $freshRoot "observation-source-cache") `
    --status-out $freshObservation `
    --events-out (Join-Path $freshRoot "observation-events.jsonl") `
    --diagnostics-out (Join-Path $freshRoot "observation-diagnostics.jsonl") `
    --trigger-queue-root (Join-Path $freshRoot "observation-trigger-queue") `
    --dry-run `
    --strict
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel observation capture blocked" }

  .\venv\Scripts\python.exe -m weather.collection.snapshot_tracker `
    --force `
    --market $pilotMarketId `
    --date $pilotTargetDate `
    --snapshots-root $freshSnapshots `
    --event-metadata $freshEventMetadata `
    --result-json (Join-Path $freshRoot "weather-capture-result.json") `
    --require-pass
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel weather/source capture blocked" }

  .\venv\Scripts\python.exe -m weather.market.market_microstructure capture `
    --market $pilotMarketId `
    --date $pilotTargetDate `
    --snapshots-root $freshSnapshots `
    --event-metadata $freshEventMetadata `
    --outcomes all `
    --no-price-history `
    --no-websocket-events `
    --clob-features `
    --require-pass
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel CLOB capture blocked" }

  .\venv\Scripts\python.exe -m weather.market.market_making_run `
    --date $pilotTargetDate `
    --budget-usdc 25 `
    --mode paper-live-forward `
    --permission-profile market_harvest `
    --markets $pilotMarketId `
    --snapshots-root $freshSnapshots `
    --observation-status $freshObservation `
    --event-metadata-validation $freshValidation `
    --exchange-economics-snapshot $pilotEconomicsSnapshot `
    --runs-root $freshPaperRuns `
    --run-id $freshPaperRunId `
    --config $pilotPaperQuoteTtlConfig `
    --once `
    --require-preflight-pass
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel strict paper tick blocked" }

  .\venv\Scripts\python.exe -m weather.market.portable_live_candidate_preflight `
    --market $pilotMarketId `
    --target-date $pilotTargetDate `
    --event-metadata $freshEventMetadata `
    --event-metadata-validation $freshValidation `
    --snapshots-root $freshSnapshots `
    --observation-status $freshObservation `
    --economics-snapshot $pilotEconomicsSnapshot `
    --accepted-economics-snapshot $pilotAcceptedEconomics `
    --economics-drift-report $pilotEconomicsDrift `
    --paper-run-config (Join-Path $freshPaperFolder "run_config.json") `
    --paper-preflight (Join-Path $freshPaperFolder "preflight.json") `
    --paper-quote-intents (Join-Path $freshPaperFolder "quote_intents_long.csv") `
    --json-out (Join-Path $freshRoot "portable-candidate-preflight.json")
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel public substrate audit blocked" }

  .\venv\Scripts\python.exe -m weather.market.mm_live_candidate_cli `
    --economics-snapshot $pilotEconomicsSnapshot `
    --accepted-economics-snapshot $pilotAcceptedEconomics `
    --economics-drift-report $pilotEconomicsDrift `
    --economics-baseline-acknowledgment $pilotEconomicsAcknowledgment `
    --target-date $pilotTargetDate `
    --paper-run-config (Join-Path $freshPaperFolder "run_config.json") `
    --paper-quote-intents (Join-Path $freshPaperFolder "quote_intents_long.csv") `
    --substrate-preflight (Join-Path $freshRoot "portable-candidate-preflight.json") `
    --expected-condition-id $pilotConditionId `
    --expected-token-id $pilotTokenId `
    --plan-out $expectedCandidateInbox
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel constrained candidate selection blocked" }

  $candidateHash = (Get-FileHash -LiteralPath $expectedCandidateInbox -Algorithm SHA256).Hash.ToLowerInvariant()
  $candidate = Get-Content -LiteralPath $expectedCandidateInbox -Raw | ConvertFrom-Json
  if (
    $candidate.status -cne "PASS" -or
    $candidate.selection_is_trading_authorization -or
    [string]$candidate.selected.location_id -cne $pilotMarketId -or
    [string]$candidate.selected.event_date -cne $pilotTargetDate -or
    [string]$candidate.paper_quote_evidence.run_id -cne $freshPaperRunId -or
    [int]$candidate.selected.paper_quote_proof.quote_ttl_seconds -ne $pilotPaperQuoteTtlSeconds -or
    [string]$candidate.selection_policy.expected_bootstrap_scope.condition_id -cne $pilotConditionId -or
    [string]$candidate.selection_policy.expected_bootstrap_scope.token_id -cne $pilotTokenId -or
    [string]$candidate.plan_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
    [DateTimeOffset]::Parse([string]$candidate.expires_at_utc) -le [DateTimeOffset]::UtcNow
  ) {
    throw "$stageLabel constrained candidate did not pass exact scope and freshness"
  }
  if (
    (Get-FileHash -LiteralPath $reviewPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $reviewHash -or
    (Get-FileHash -LiteralPath $expectedLauncherPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $launcherHash -or
    (Get-FileHash -LiteralPath $expectedCandidateInbox -Algorithm SHA256).Hash.ToLowerInvariant() -cne $candidateHash
  ) {
    throw "$stageLabel review, launcher, or candidate changed before invocation"
  }
  Write-Host "$stageLabel launcher-review SHA-256: $reviewHash"
  Write-Host "$stageLabel candidate SHA-256: $candidateHash"
  & $expectedLauncherPath
  if ($LASTEXITCODE -ne 0) { throw "$stageLabel reviewed launcher failed" }
}

# Run immediately after Stage 0, in predecessor order. Each call refreshes and
# then launches without a pause that spends the candidate's 300-second plan.
Invoke-FreshReviewedStage1 -Stage "stage1_cancel_all"
Invoke-FreshReviewedStage1 -Stage "stage1_dead_man"
```

Never append another capture to a prior refresh root, copy or rename an earlier
candidate, or call a Stage 1 launcher without that stage's immediately
preceding strict refresh and raw-hash recheck.
If the two-hour economics gate has expired or any economics/token identity has
changed, stop this attempt. A refreshed snapshot requires a new accepted
snapshot, drift report, review-only candidate, exact acknowledgment, and three
new manifests because the old manifest-bound hashes cannot be reused. The
launcher passes only the reviewed manifest
hash and fixed candidate path to the composer; no scope or ceiling is accepted at
the live boundary. Before writing candidate/spec/composition/intent artifacts,
the composer derives a candidate-bounded window of at most 120 seconds for
`capture_colocated_v1` or 240 seconds for `portable_execution_v1` and
rejects unless that window plus the full 20-second cleanup tail remains within
one profile-valid local date. The colocated profile requires the target date
and complete **[00:30, 09:00) America/Toronto** containment. The portable
profile requires one candidate-market-local execution date and a target equal
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
credential inputs, candidate, complete predecessor lineage, external SDK
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
request, 100 pUSD wallet cap, execution cutoff, cleanup reserve, and contained
process end before its literal confirmation. The
Stage 0 display also states `order_submit_expected=false`, an authenticated
heartbeat write is expected, and cancel-all cleanup is expected with
`ACCOUNT_WIDE` scope so those writes cannot be mistaken for read-only
activity. The
prompt is bounded by the same absolute cutoff. The portable profile requires
120 seconds remaining before entering credential context and 60 seconds
immediately before an authenticated mutation boundary. The stage,
physical-location/no-circumvention, and mutation-specific attended
confirmations all consume the same candidate-derived cutoff; no prompt resets
or extends it. The fresh-candidate helper must therefore flow directly into
the reviewed launcher, and hesitation is a stop-and-refresh event. After
confirmation it rechecks Git/source identity, profile-specific host status,
clock/reboot state, the applicable time boundary, and the candidate before credential
resolution. The window guard also runs inside every host attestation. Stage 1
therefore repeats it submit-adjacent, checks the cutoff before the
adapter call, and binds the deadline into its one-use capability; the adapter
checks again after signing immediately before the actual `post_order` network
boundary. A hash-bound journal proves that ordering.

Do not invoke the inner fixed-scope launcher directly. Independently compare the
outer session launcher's hash with its review receipt, then invoke that launcher
with no arguments. Candidate selection and successful sealing are preparation,
not execution authorization. Every `run_stage1` call still revalidates the
candidate before credential resolution, can perform exactly one network submit,
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
collateral balance and allowances to six-decimal settlement units, rejects a
balance above the isolated-wallet cap, validates a public Data API position
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
- Select one central band whose current market spread, depth, fee eligibility,
  source freshness, book freshness, watcher freshness, and current-high trust
  gates pass.
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

Use the public official `GET /rebates/current?date=...&maker_address=...`
response for the completed next payout cycle. Count only rows matching the
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
overlay process-locally, pass the keyless doctor, and obtain the production-host
Stage 0 proof. Installing the live extra into the shared checkout remains
forbidden. The successful source/wheel audit is not wallet or exchange evidence.

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

- book, source, watcher, execution-capture, user-stream, or heartbeat stale;
- market fee eligibility, min size, tick, wallet, allowance, or platform drift;
- any order is accepted as taker or without post-only protection;
- open orders, positions, reserves, or local lifecycle disagree with exchange
  truth;
- unknown order, unexpected partial fill, unbacked sell, or risk-cap breach;
- cancel-all is not followed by zero open orders;
- under `capture_colocated_v1`, the contained interval leaves the target date
  or **[00:30, 09:00) America/Toronto**, the host enters a protected window, or
  capture health degrades;
- under `portable_execution_v1`, the contained interval crosses its
  candidate-market-local execution date, the target is neither that date nor
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
