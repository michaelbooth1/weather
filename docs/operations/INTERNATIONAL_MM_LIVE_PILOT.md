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

As of 2026-08-19, the cumulative paper/client/pUSD parent is integrated at
merge `3c326ac1c03b415877da33dc254b39d32f576de4` after an exact 4,489-test
suite and guarded capture recovery. The fixed-scope Stage 2 successor is not
integrated: its host focused wrapper resolved imports from production rather
than its exact worktree, so the full suite and merge correctly refused. No
current candidate or trading authorization exists. A corrected focused
diagnostic is not a replacement for a new immutable full-suite receipt.

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
- Requested run budget no more than the wallet cap and no more than **100**.
- Exactly one weather market per run.
- Existing ceilings may be lowered but not raised: **25** daily loss, **25**
  event notional, **10** band notional, and **120 seconds** quote TTL.
  `weather.market.market_making_live_pilot` owns this mode-specific normalization;
  the general run orchestrator delegates to it before evaluating any gate.
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

1. Continuous execution capture is running and has produced rows. This remains
   ahead of the paper harvest lane in the approved sequence.
2. The International economics snapshot passes and matches the live platform.
3. Before the first lifecycle order, `mm_platform_bootstrap_v0.3` passes for
   the exact token and condition. This non-order, at-most-one-hour-old artifact
   proves the isolated wallet identity, recorded cap, numeric collateral
   balance and allowance each backing the requested budget, a content-bound
   account snapshot, an observed zero open-order count, current
   book/min size/tick/neg-risk, market fee
   eligibility, a non-posting signed-order preview bound to the exact EOA/API
   owner, order signer, funder/maker, signature type, and token (raw signature
   discarded), account-wide
   user stream, two current bodyless heartbeat acknowledgments,
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
   installed from the `live` dependency extra and wrapped by a tested adapter.
   Its pinned client owns post-only placement, CLOB account reads,
   cancellation, and dead-man heartbeats. The existing hand-built request-plan
   adapter remains diagnostic and cannot authorize capital.
   `SecureClient.create` may deploy a missing default deposit wallet, so the
   wrapper must first prove the exact supplied Safe/deposit wallet already
   exists through the public relayer `/deployed` endpoint. Placement stays
   disabled until authoritative user-event and position readers are present
   and explicitly verified, a bodyless `/heartbeats` request has returned the
   exact `{status: "ok"}` acknowledgment within 7.5 seconds, and matching
   book/min-size/tick/neg-risk/fee endpoint evidence has been read within 10
   seconds.
6. Current live-readiness, data-layer, fleet, risk, release, and explicit
   confirmation gates all pass without overrides or exceptions.
7. A simultaneous one-market paper counterfactual has quote permission and is
   writing auditable artifacts. The separately authorized route is:

   ```powershell
   .\venv\Scripts\python.exe -m weather.market.market_making_run --date <YYYY-MM-DD> --budget-usdc 25 --mode paper-live-forward --permission-profile market_harvest --markets <market-id> --once
   ```

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
8. The session is outside the host's protected 12:00-18:00 local capture window.

## Staged protocol

### Stage 0: read-only account proof

- Fill the public `mm_stage0_client_identity_v0.2` manifest. It binds only the
  International platform, chain, pinned SDK, public wallet topology,
  isolated-wallet declaration, and capital cap. It exists to construct the
  authenticated client needed to collect Stage 0; it is not evidence that any
  account check passed and cannot authorize an order.
- Authenticate and subscribe to the entire user account stream.
- Require the reader thread to remain active. A historical PONG from a stopped
  or failed reader is not liveness, and ordinary account events do not satisfy
  the independent server-PONG deadline.
- Query balance, allowance, positions, and open orders.
- Require no unknown open orders. If any exist, stop and reconcile them.
- Require an exact-condition position query and zero starting outcome inventory.
- Read the chosen book, market fee eligibility, min order size, tick size, and
  closed-only state immediately before mutation.

### Stage 1: dead-man and cancel proof

- Start the exchange heartbeat and require acknowledged 5-second cadence.
- Send the current bodyless `POST /heartbeats`; every response must equal
  `{status: "ok"}`. A malformed acknowledgment or response older than 7.5
  seconds disarms placement.
- Submit one far-from-mid, smallest-valid, post-only buy with notional no more
  than the band cap.
- Require both the placement response and authenticated stream/open-order
  observation.
- Treat every scoped trade lifecycle state, including `MATCHED`, `MINED`, and
  `RETRYING`, as an unexpected Stage 1 outcome. Send cancel-all, reconcile, and
  stop; zero positions from a potentially lagging account API is not sufficient
  no-fill evidence.
- Continue the bodyless heartbeat at no more than five-second intervals during
  placement and observation. Before either cancellation proof, acknowledge one
  fresh heartbeat and prove the order is still open. Otherwise a slow
  observation could let the dead-man timer cancel the order and falsely credit
  cancel-all.
- The immediate response must be successful, carry an order ID, report `live`,
  and carry no trade IDs or transaction hashes. Any other response is an
  ambiguous or taker-like outcome: send cancel-all, reconcile, and stop.
- Intentionally stop heartbeats once from that fresh acknowledgment, observe
  automatic cancellation no earlier than the documented ten-second timeout and
  within the timeout-plus-five-second cancellation-check window, then query
  until the order is absent. If this is not proven, stop the pilot.
- Repeat with one order, invoke cancel-all, and require zero open orders.

This stage is a successful live test even if no fill occurs.

After both distinct probes pass, construct
`mm_stage1_lifecycle_bundle_v0.2` with
`weather.market.mm_live_lifecycle_probe.build_stage1_lifecycle_bundle`. The
builder rereads both append-only journals, verifies their hashes and critical
events, requires distinct journal files and order IDs, and derives the no-fill,
cancel-all, and heartbeat-lapse facts. It independently rejects a bootstrap
wallet/request cap above 100 pUSD and either reported order above 10 pUSD;
upstream PASS booleans do not substitute for these numeric checks. Do not
hand-author those facts. The
tracked bundle template is deliberately fail-safe.

Stage 1 is the only order mutation allowed from the bootstrap artifact. Its
completed, content-bound lifecycle bundle upgrades platform proof to
`mm_platform_verification_v0.5`. The ordinary `market_making_run` live-pilot
path continues to require that stronger artifact and must never accept the
bootstrap artifact. Version v0.4 embeds the bundle and its SHA-256, rechecks
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
cancellation events, absence of every scoped trade lifecycle event, zero ending
orders, and zero exact-scope positions. It
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

### Production-host preparation

The final sequence runs from this production checkout. There is no
source-transfer or second-machine deployment step. Public metadata, economics,
and book selection must be rerun for the live session. Never put a secret value
in the command line, environment, identity manifest, output path, or shell
history.

Plan the first lifecycle session outside both the 12:00-18:00 graded window and
the 18:00-00:30 near-close protection window. After boot and network recovery,
log in once so Credential Manager and `WeatherOneShotPush` are
available, prove master equals origin at the reviewed exact tip, prove all
capture workers and the public execution-tape producer recovered, clear the
pending reboot state, and ensure no heavy scheduled job can overlap the session.
Do not trade merely because Windows restarted successfully.

Select the exact Stage 1 market from fresh public data and a successful
one-market paper tick before creating the identity. Do not hand-pick a
condition/token pair or retain one from a prior day.
The metadata refresh's `--metadata-only` mode leaves the tracked location
registry byte-for-byte unchanged. The selector authenticates nowhere and can
neither place nor cancel an order; it requires a passing content-bound
International economics snapshot, a current paper-only market-harvest quote,
and current book rules, then emits a content-hashed plan that explicitly is not
trading authorization:

```powershell
$pilotTargetDate = "replace-with-target-date"
$pilotMarketId = "replace-with-one-built-in-market-id"
$paperRunId = "pilot-paper-" + [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$paperRunsRoot = "C:\pilot\paper-runs"
$paperRunFolder = Join-Path $paperRunsRoot (Join-Path $pilotTargetDate $paperRunId)

.\venv\Scripts\python.exe -m weather.operations.location_config_refresh `
  --locations .\config\locations.json `
  --event-metadata C:\pilot\location-market-events.json `
  --metadata-only

.\venv\Scripts\python.exe -m weather.market.exchange_economics collect-global `
  --event-metadata C:\pilot\location-market-events.json `
  --snapshot C:\pilot\exchange-economics.json `
  --target-date $pilotTargetDate `
  --max-age-hours 2

.\venv\Scripts\python.exe -m weather.market.market_making_run `
  --date $pilotTargetDate `
  --budget-usdc 25 `
  --mode paper-live-forward `
  --permission-profile market_harvest `
  --markets $pilotMarketId `
  --exchange-economics-snapshot C:\pilot\exchange-economics.json `
  --runs-root $paperRunsRoot `
  --run-id $paperRunId `
  --once

.\venv\Scripts\python.exe -m weather.market.mm_live_candidate_cli `
  --economics-snapshot C:\pilot\exchange-economics.json `
  --target-date $pilotTargetDate `
  --paper-run-config (Join-Path $paperRunFolder "run_config.json") `
  --paper-quote-intents (Join-Path $paperRunFolder "quote_intents_long.csv") `
  --plan-out C:\pilot\stage1-candidate.json

$pilotPlan = Get-Content -LiteralPath C:\pilot\stage1-candidate.json -Raw | ConvertFrom-Json
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

The plan expires at the earlier of five minutes or the selected paper row's
quote TTL (currently at most 120 seconds). If it expires, run a new one-market
paper tick and selector with new output paths; refresh the economics snapshot
too when its own gate expires. After Stage 0, repeat the paper tick and selector
immediately before Stage 1 with `--expected-condition-id $pilotConditionId` and
`--expected-token-id $pilotTokenId`. That constrained refresh must select the
exact Stage 0 scope or block; it cannot silently switch markets after the
authenticated bootstrap.
Stage 0 still rereads the exact book and fails closed on any condition, token,
min-size, tick, neg-risk, fee, or closed-state drift. The plan's minimum-tick
intent is only a far-from-mid lifecycle probe and will normally not qualify for
liquidity rewards or provide maker-fill economics evidence. Stage 2 must use a
separate current quote decision after Stage 1 passes.

Next create the public identity. The command derives the numeric signature ID
and writes no identity if any public gate fails. Only these two documented
topologies are accepted:

| Wallet class | Signature | EOA/API owner | Order signer | Funder/maker |
| --- | --- | --- | --- | --- |
| Existing Gnosis Safe | `POLY_GNOSIS_SAFE` / `2` | private-key EOA | same EOA | distinct Safe |
| New deposit wallet | `POLY_1271` / `3` | private-key EOA | deposit wallet | same deposit wallet |

The supplied funded-wallet configuration declares the first topology. Offline
validation on 2026-08-13 with the exact pinned SDK proved that its private key
derives its public EOA, that the SDK selects that EOA as the type-2 order signer,
and that the configured Safe funder is distinct. This is not exchange
authentication or order evidence; Stage 0 must still prove it against live
account reads on the production host. Do not switch topology after a failed probe:

```powershell
$pilotFunderAddress = "replace-with-public-funder-address"
$pilotWalletType = "gnosis_safe"
$pilotSignatureType = "POLY_GNOSIS_SAFE"

.\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli prepare-identity `
  --funder-address $pilotFunderAddress `
  --wallet-type $pilotWalletType `
  --signature-type $pilotSignatureType `
  --budget 10 `
  --wallet-cap 100 `
  --identity-out C:\pilot\identity.json `
  --receipt-out C:\pilot\identity-receipt.json `
  --confirm-international-platform `
  --confirm-isolated-wallet `
  --confirmation INTERNATIONAL_POLYMARKET_PREPARE_STAGE0_IDENTITY
```

Only after identity preparation passes, provision the four secret
values as Windows Credential Manager generic credentials. If an external
source file is used, keep it outside the repository, remove inherited broad
ACLs. The importer validates the private
key/address and exact wallet/signature topology, refuses existing fixed targets,
rolls back partial writes, ignores unrelated relayer/RPC/live-flag fields, and
emits only a public reference manifest and secret-free receipt:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_credential_import_cli `
  --source-env C:\secure\pilot.env.txt `
  --manifest-out C:\pilot\credential-references.json `
  --receipt-out C:\pilot\credential-import-receipt.json `
  --confirm-source-acl-private `
  --confirmation INTERNATIONAL_POLYMARKET_IMPORT_CREDENTIALS
```

Do not proceed unless the receipt is `PASS`, reports exactly four entries, and
has no rollback. Do not persist its references in User or Machine environment.
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
After a successful import, independent
keyless doctor, and operator verification of the external source's retained
copy, delete the source credential file using the approved secure-deletion
procedure. The importer never deletes it automatically.

Run the keyless doctor before Stage 0. It validates the exact SDK version,
Windows resolver availability, reference URI shapes and completeness, direct-
secret absence, public-funder/identity equality, target/condition/token formats,
and the requested budget without opening Credential Manager or authenticating to
the exchange. Its receipt contains counts and gate names, never reference targets:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli doctor `
  --identity C:\pilot\identity.json `
  --target-date $pilotTargetDate `
  --condition-id $pilotConditionId `
  --token-id $pilotTokenId `
  --budget 10 `
  --sdk-overlay-manifest .\scripts\ops\international_live_templates\sdk_overlay_manifest.json `
  --sdk-overlay-manifest-sha256 <reviewed-manifest-sha256> `
  --receipt-out C:\pilot\doctor-receipt.json `
  --confirmation INTERNATIONAL_POLYMARKET_STAGE0_KEYLESS_DOCTOR
```

Do not proceed unless the doctor receipt is `PASS` with an empty `missing` list.

Prepare the identity and run the keyless doctor only after the surrounding
setup is complete. The final Stage 0, both Stage 1 modes, and bundle construction
should be prepared in advance and run consecutively; an expired bootstrap is a
stop, not a reason to edit timestamps or reuse an earlier gate.

Do not invoke Stage 0 or Stage 1 with `python -m`: the parser intentionally has
no exchange-mutation commands. Do not hand-edit a copy of the old host template.
The repository-owned sealer is the only supported way to create the external
fixed-scope Stage 0, Stage 1 cancel-all, and distinct Stage 1 dead-man wrappers. First inventory the exact
production Git, template, and source hashes; this command writes nothing and
returns `BLOCK` until the interrupt-cleanup hardening commit is an ancestor:

```powershell
.\venv\Scripts\python.exe -m weather.operations.international_live_wrapper_sealer inventory `
  --stage stage0
```

Author one reviewed
`international_live_fixed_scope_seal_spec_v0.2` JSON object with the inventory
hashes, synchronized `master` commit/tree, explicit budget, exact scope, current
candidate hash, no-more-than-30-minute window, new attempt root, public input
hashes, and item-by-item reviews for any accepted status-flag hashes. Inputs use
the canonical paths under `inputs/` from the sealer contract; credential
evidence is represented only by public receipt/manifest paths and hashes. Then
seal it:

The top-level keys are exactly `schema_version`, `stage`, `prepared_at_local`,
`production`, `scope`, `inputs`, `reviewed_status_flags`, `template_sha256`, and
`source_sha256`. `production` binds `root`, `branch`, `commit`, `tree`, and
`python`; `scope` binds the target, condition, token, budget, window, attempt
root, and lease workload. Stage 0 inputs are `identity`, `scope_plan`,
`credential_import_receipt`, and `credential_reference_manifest`; each Stage 1
mode additionally binds `bootstrap`, `stage0_receipt`, `stage0_seal_receipt`,
`stage0_run_receipt` and its sidecar, `stage0_wrapper_execution_receipt`, and its
own fresh `candidate_plan`. Every
input record has only `path` and `sha256`. Dead-man additionally requires the
complete validated cancel-all seal, run receipt and sidecar, execution receipt,
command receipt, result, and lifecycle journal; a failed or unknown cancel-all
run can never advance.

```powershell
.\venv\Scripts\python.exe -m weather.operations.international_live_wrapper_sealer seal `
  --spec C:\pilot\inputs\stage0-seal-spec.json
```

The sealer never opens Credential Manager or runs the generated launcher. It
independently validates the inert SDK overlay helper, candidate semantic hash, scope,
120-second paper TTL, run-window containment, all public inputs, every imported
live-source hash, exact production ancestry, and that every wrapper, receipt,
sidecar, and runtime output path is new and contained. It creates a fixed
no-argument Python wrapper, a hash-bound no-argument PowerShell launcher, an
`international_live_fixed_scope_seal_v0.3` receipt, and its SHA-256 sidecar.
Each Stage 1 mode uses a separate fresh spec and candidate, plus the exact
successful Stage 0 bootstrap, command, seal, wrapper execution, parent run
receipt, and sidecar lineage. A partial or failed seal
spends that attempt namespace; create a new attempt instead of overwriting it.

Because the candidate lasts at most 120 seconds, the normal path is a
pre-reviewed `international_live_fixed_session_manifest_v0.2` plus its adjacent
raw-file SHA-256 sidecar. Before candidate selection, turn that independently
reviewed raw hash into a no-argument launcher and immutable review receipt:

```powershell
.\venv\Scripts\python.exe -m weather.operations.international_live_session_launcher_sealer `
  --session-manifest C:\pilot\inputs\stage0-session-manifest.json `
  --expected-session-manifest-sha256 <independently-reviewed-raw-sha256>
```

Write the newly selected candidate only to the review receipt's fixed inbox,
independently compare the generated launcher's hash with that receipt, then run
the launcher with no arguments. It passes the reviewed manifest hash and fixed
candidate path to the composer; no scope or ceiling is accepted at the live
boundary. The composer derives a candidate-bounded window of at most 120
seconds, requires at least 90 seconds still available immediately before
launch, writes an immutable ARMED intent, and atomically claims the terminal
receipt and sidecar paths before the child. The no-argument launcher and parent
runner hold deny-write/delete handles for the reviewed runner, production
sources, public credential inputs, candidate, and complete predecessor lineage;
they rehash after acquiring those handles and retain them through child exit.
The parent sends cooperative cleanup at the sealed stop, allows only the fixed
20-second cleanup grace, and then uses kill-on-close containment if required.

The wrapper displays the exact stage/mode, target, condition, token, 10 pUSD
request, 100 pUSD wallet cap, and cutoff before its literal confirmation. The
prompt is bounded to preserve a 60-second pre-credential reserve. After
confirmation it rechecks Git/source identity, host/capture/status/clock/reboot
state, the full current window, and the candidate before credential resolution.
Stage 1 repeats host attestation submit-adjacent, checks the cutoff before the
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
.\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli bundle `
  --bootstrap C:\pilot\stage0-bootstrap.json `
  --expected-production-tip <reviewed-production-git-oid> `
  --target-date $pilotTargetDate `
  --condition-id $pilotConditionId `
  --token-id $pilotTokenId `
  --budget 10 `
  --cancel-all-result C:\pilot\cancel-all-result.json `
  --cancel-all-seal-receipt C:\pilot\cancel-all-seal-receipt.json `
  --cancel-all-command-receipt C:\pilot\cancel-all-command-receipt.json `
  --cancel-all-execution-receipt C:\pilot\cancel-all-execution-receipt.json `
  --cancel-all-run-receipt C:\pilot\cancel-all-run-receipt.json `
  --dead-man-result C:\pilot\dead-man-result.json `
  --dead-man-seal-receipt C:\pilot\dead-man-seal-receipt.json `
  --dead-man-command-receipt C:\pilot\dead-man-command-receipt.json `
  --dead-man-execution-receipt C:\pilot\dead-man-execution-receipt.json `
  --dead-man-run-receipt C:\pilot\dead-man-run-receipt.json `
  --bundle-out C:\pilot\stage1-bundle.json `
  --receipt-out C:\pilot\stage1-bundle-receipt.json `
  --confirmation INTERNATIONAL_POLYMARKET_STAGE1_BUILD_BUNDLE
```

All paths shown above are illustrative and must be replaced with a protected
operator-owned directory. Every output and journal path must be new. A FAIL
receipt is evidence to stop and investigate, never permission to retry a submit.

`weather.market.mm_live_bootstrap.collect_platform_bootstrap_payload` is the
prepared Stage 0 evidence collector. It converts the CLOB's integer atomic
collateral balance and allowances to six-decimal settlement units, rejects a
balance above the isolated-wallet cap, validates a public Data API position
query scoped to the exact proxy wallet and condition, content-binds that query
and the full account snapshot, locally constructs and hashes a signed minimum
BUY without posting it, discards the raw signature, requires a live user-stream
PONG, exercises two bodyless five-second heartbeat acknowledgements, and sends
cancel-all followed
by a zero-order query. The WebSocket does not document an initial account
snapshot, so the gate does not invent one: REST establishes the starting state,
PONG establishes transport liveness, and the first Stage 1 order event proves
the authenticated event path.

### Stage 2: one-band maker quote

- Require a current passing `mm_platform_verification_v0.5`, including the
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
`{status: "ok"}` acknowledgment. Because the unified SDK does not expose that
REST method, `weather.market.mm_official_transport` provides only that one
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
signing/submission. Before any credentialed Stage 0/1 session, the exact wheel
must be installed through the `live` extra in this checkout, the fixed-scope
host wrapper must pass the keyless doctor, and the production-host Stage 0
proof must pass. The successful source/wheel audit is not wallet or
exchange evidence.

The supplied Safe wallet's local cryptographic topology is proven, but its live
exchange behavior is still unproven. Stage 0 must show that the exact signer,
Safe/deposit-wallet funder, signature type, and API-key owner satisfy the
topology table above. A balance read is not sufficient: the same identity
must pass authenticated user-stream subscription, heartbeat, a signed-order
preview or non-posting contract probe, and cancel-all. Do not rely on a manual
UI-trade workaround or silently switch wallet/signature models after a failure.

Official references reviewed through 2026-08-14:

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

## Stop conditions

Cancel all and do not resume on any of the following:

- book, source, watcher, execution-capture, user-stream, or heartbeat stale;
- market fee eligibility, min size, tick, wallet, allowance, or platform drift;
- any order is accepted as taker or without post-only protection;
- open orders, positions, reserves, or local lifecycle disagree with exchange
  truth;
- unknown order, unexpected partial fill, unbacked sell, or risk-cap breach;
- cancel-all is not followed by zero open orders;
- host enters the protected capture window or capture health degrades.

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
