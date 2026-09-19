# Audit dimension: market-live

Market package B: live execution, exchange clients, credentials, taker, CLOB capture.
Auditor run: 2026-09-18 (production host, protected near-close window; read-only).

## 1. Scope and method

Tools used: Read, Grep, Glob (always with an explicit path under src/, tests/, docs/,
scripts/, tools/, app/, config/), plus the whitelisted git commands (`git log`,
`git show`, `git branch`, `git ls-files`, `git ls-tree`) and one non-recursive `ls`.
Nothing was executed, no test was run, no file under `data/` was opened, no network was
used. Every structural claim below was traced in the cited lines, not inferred from a
grep hit alone. Where a claim rests on a project document rather than code it is
labelled doc_claimed.

Files I took from `src/weather/market/` (flat package, 73 modules):

Read in full or in the load-bearing parts:
- `mm_official_adapter.py` (full) - the only network order-submit path
- `mm_credentials.py` (full)
- `mm_official_transport.py` (full)
- `mm_user_stream.py` (class body)
- `mm_live_lifecycle_probe.py` (`execute_stage1_lifecycle_probe`, collateral snapshot)
- `mm_live_pilot_cli.py` (context builder, cleanup, `run_stage0`, `run_stage1`)
- `mm_live_bootstrap.py` (heartbeat / cancel-all section)
- `mm_exchange.py` (constants, credential diagnostics, adapters, reconciliation, CLI)
- `live_sdk_overlay.py` (validation + activation)
- `market_making_live_pilot.py` (full)
- `execution_tape_capture.py` (seed loading, connection loop, fleet, run loop)
- `execution_tape_store.py` (ingest path, seed-error accounting)
- `market_microstructure_capture.py` (ClobClient, store, status, fleet parallel capture, WS sampler)
- `market_microstructure.py` (book audit, effective gap, `run_book_loop`)
- `market_microstructure_constants.py` (full)
- `market_making_run_support.py` (preflight book audit, lifecycle events, live gate)
- `polymarket_client.py`, `clob_recon.py`, `live_forward_gate.py`, `order_book_tape.py`,
  `mm_geographic_eligibility.py`, `mm_credential_import_cli.py`, `mm_risk.py`,
  `taker_bot.py`, `taker_bot_strategy_registry.py`, `mm_paper.py` (structure + targeted sections)

Outside the package: `src/weather/execution_host.py` (full),
`config/international_live_execution_host.json` (full),
`scripts/ops/international_live_templates/` (listing; `stage1_cancel_all.py.tmpl` head and
tail; `stage0.py.tmpl` phase map; `sdk_overlay_manifest.json` full),
`docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md` (full),
`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` (lines 1-140, 800-860, 1895-1940),
`docs/operations/STATE_OF_PLAY.md` (full, plus the 2026-08-31 version via
`git show 1acf9ebbc:`), `docs/roadmap/items/item-330-*.md` (sections),
`src/weather/operations/international_live_wrapper_sealer.py` (Git proof section only),
`pyproject.toml`, `.env.example`, `AGENTS.md` (lines 40-100).

## 2. Bottom line

The part of this dimension that could lose money is the best-engineered code I read in
the repository. An accidental live order is not a realistic failure mode. The real
problems are elsewhere:

1. The public execution tape (the project's self-described non-backfillable stream) has a
   12-market blast radius on a single market's metadata defect.
2. The CLOB book-gap audit relaxes its own threshold from the slowest iteration the loop
   has ever had, so the stall that makes a gap also excuses it.
3. The live lane was abandoned mid-flight on 2026-09-04 and its residue (assigned host,
   provisioned credentials, a plaintext credential source awaiting deletion, a funded
   wallet, stale runbooks) is no longer tracked by any current canonical document.
4. There is no state of the host registry that means "live is off".

Health grade for the dimension: B. No critical or high finding.

## 3. What actually prevents an accidental live order (verified)

Traced end to end. Every item is code, not documentation.

- One submit call site. `self.client.post_order(signed_order)` at
  `mm_official_adapter.py:1398` is the only network order submit under `src/`, `scripts/`,
  `tools/` and `app/` (Grep for `post_order|place_order|place_limit_order|create_limit_order|SecureClient`
  over each tree). It is reached only through `OfficialPolymarketGlobalAdapter.place_order`,
  whose only caller is `mm_live_lifecycle_probe.py:778`.
- Single-use capability. `place_order` requires the opaque object returned by
  `authorize_stage1_lifecycle` (`mm_official_adapter.py:1314-1321`), marks it consumed
  before signing (`:1334`), and a second `authorize` on the same adapter raises (`:748-749`).
  At most one POST per adapter instance.
- Hard notional clamp. `MAX_STAGE1_ORDER_NOTIONAL = Decimal("10")` (`:26`);
  the constructor takes `min(requested, 10)` (`:651-654`); `price * size` above it raises
  (`:1268-1269`). The probe orders the minimum size at the minimum tick
  (`_minimum_probe_intent`), so real exposure is cents.
- Wallet cap enforced against the observed balance, not only config:
  `_action_time_collateral_snapshot` rejects `balance_usdc > wallet_cap` and
  `wallet_cap > MAX_OPERATOR_PILOT_BUDGET_USDC` (`mm_live_lifecycle_probe.py:356-366`);
  the sealed wrapper re-checks `10 <= balance <= 100` (`stage1_cancel_all.py.tmpl:1574`).
- Post-only, no marketable retry, no allowance mutation: the adapter deliberately avoids
  the SDK's `place_limit_order` convenience (`mm_official_adapter.py:1340-1350`), verifies
  signer, maker, token, signature type, GTC and `post_only is True` on the signed order
  before the POST (`:1094-1165`), and re-checks heartbeat age, user-stream health, tick,
  minimum size and crossing after signing (`:1363-1381`).
- Starting state must be zero open orders and zero positions
  (`mm_live_lifecycle_probe.py:533-544`), which is the practical duplicate-order guard
  across processes. All output paths are create-only and must not pre-exist.
- Ambiguous submit is handled: an exception from `post_order` sets
  `ambiguous_order_submit`, sends cancel-all, and re-raises (`:1397-1405`); a response
  that is not an execution-free `live` order triggers cancel-all (`:1419-1424`). The probe
  then cancels again in its `except BaseException` (`mm_live_lifecycle_probe.py:1076-1101`)
  and the CLI cancels a third time and proves zero orders and zero exact-scope positions
  (`mm_live_pilot_cli.py:603-673`, `:1191-1194`). The exchange-side heartbeat dead-man is
  the last resort.
- Attended by construction. `run_stage0`/`run_stage1` require a callable attestor that
  cannot arrive through argparse (`mm_live_pilot_cli.py:904-906`, `:1087-1089`). The sealed
  wrapper reads the confirmation literal from the physical console with
  `msvcrt.kbhit/getwch` (`stage1_cancel_all.py.tmpl:322-325`, `:1491-1493`), so piped stdin
  from a headless agent tool cannot supply it. The template ships with
  `TEMPLATE_SEALED = False` (`:24`) and refuses to run unsealed (`:162-164`).
- Host binding. The wrapper and `execution_host.py` hash the Windows `MachineGuid` and the
  process token SID and compare them with the tracked registry
  (`execution_host.py:67-71`, `:140-144`, `:285-308`); the registry reader rejects
  duplicate keys, BOMs, reparse points, oversize files and mid-read changes (`:147-221`).
- Git proof. The sealer requires HEAD == local branch == cached origin == live origin ==
  reviewed commit, synchronized master, and master as an ancestor of the reviewed tip
  (`international_live_wrapper_sealer.py:778-812`).
- US separation is enforced in code: `SUPPORTED_PLATFORM_IDS = {"polymarket_global"}`
  (`market_making_preflight.py:135`, used at `:489`); the Stage 0 identity gate pins
  `https://clob.polymarket.com`, chain 137 and `polymarket_global`
  (`mm_credentials.py:287-300`).
- The taker bot is paper only. No module matching `taker_*.py` imports `requests`,
  `urlopen`, `websocket` or the SDK (Grep); the only URL is a fee-provenance string.
- `mm_exchange.py`'s `--execution-mode live --allow-live` is inert:
  `adapter_from_fixture` can only return `NullExchangeAdapter` or `FixtureExchangeAdapter`
  (`:1076-1079`), both `supports_trading = False`, so `trading_verbs_enabled` (`:1263-1269`)
  can never be true.

Secret handling (verified): secrets enter only as `wincred://` references
(`mm_credentials.py:32-37`, `:242-258`); any directly populated
`POLYMARKET_API_KEY/SECRET/PASSPHRASE/PRIVATE_KEY` environment variable fails the gate
(`mm_exchange.py:360-383`); credential holders have redacting `__repr__`/`__slots__`
(`mm_credentials.py:63-77`, `mm_live_pilot_cli.py:465-476`, `mm_official_transport.py:207-208`,
`mm_user_stream.py:95-100`); receipts, journals and stderr carry only
`type(exc).__name__` (`mm_live_pilot_cli.py:638-639`, `:1068`,
`stage1_cancel_all.py.tmpl:1608-1629`, `mm_credential_import_cli.py:947`); the user-stream
background thread swallows raw transport text (`mm_user_stream.py:267-276`). A pattern
Grep for hard-coded secrets over `src/`, `scripts/` and `config/` found nothing;
`.env` is gitignored and `.env.example` holds placeholders only.

## 4. Findings

### market-live-1 (medium) - Execution tape: one market's metadata defect stops all 12 markets

Basis: verified_in_code. Known status: new.

`load_market_day_seeds` iterates all selected markets and raises
`ExecutionTapeSeedError` on the first problem in any one of them: not exactly one active
event for that market's local date (`execution_tape_capture.py:141-144`), slug mismatch
(`:146-149`), any condition with `active is False` or `closed is True` (`:153-155`), a
condition without two tokens (`:162-165`), a missing location (`:130-131`), or metadata
older than 36 h (`:79-82`). `run_live_capture` catches that exception and stops the whole
connection fleet (`:562-567`: `fleet.stop(); fleet = None; active_signature = None`), then
retries every 60 s. Production runs a single producer for `--market all`
(`docs/operations/OPERATIONS_DESIGN.md:32`, `execution_tape_supervisor.py:150`, `:213`).
So while one market's seed is invalid, the eleven healthy markets capture nothing.

The dark time is accounted honestly (`execution_tape_store.py:1224-1243`, status
`DISCONNECTED_SEED_ERROR` at `:1438-1439`), so this is not a silent failure. It is a
blast-radius failure, the same shape as the project's recorded "one transient error killed
all 12 markets" settlement incident, in the one stream the project calls non-backfillable.
The only test of the loader is a single-market happy path
(`tests/market/test_execution_tape_capture.py:735-765`); no test covers one bad market
among several. I could not read live status, so I do not claim it has happened.

Recommendation: validate per market, subscribe the valid ones, record the invalid market
as its own dark interval. Keep the fleet-wide stop only for unreadable or stale metadata.

### market-live-2 (medium) - CLOB gap audit raises its own threshold from the loop's lifetime-worst iteration

Basis: verified_in_code. Known status: new (the mechanism is deliberate, its cost is unrecorded).

`fleet_effective_book_gap_seconds` returns
`max(threshold, max(elapsed_values) + last_sleep + 60)` where `elapsed_values` includes
`max_iteration_elapsed_seconds` (`market_microstructure.py:604-634`). `run_book_loop`
maintains that field as a running maximum for the life of the process
(`:1744-1750`), computed from wall-clock `now_fn() - loop_started` (`:1684`), with no cap and
no decay, and it is updated for every non-exception iteration including ones where every
market errored or timed out. Status starts fresh only at process start (`:1532-1566`).
The function feeds both the fleet observability audit (`:655`) and the maker preflight
continuity gate (`market_making_run_support.py:684-707`). The behaviour is pinned by
`tests/market/test_market_microstructure.py:2118-2127`; there is no upper-bound test.

Consequence: a single iteration that spans a host stall (memory pressure, suspend, a hung
status write) of N seconds sets the threshold to at least N + sleep + 60 for the rest of the
process's life. The gap that stall produced, and every smaller gap that day and on later
days, then audits as `ok`. `docs/roadmap/items/item-37-*.md:101-104` records this as a fix
for "retroactive false CLOB tape gaps" (2026-06-15). It is the project's own documented
defect shape: silencing a false alarm created a false silence.

Recommendation: bound the loop-aware allowance (for example the per-market timeout plus
interval plus buffer), use the recent window only, and report gaps above the nominal 120 s
separately from gaps above the loop-aware threshold so a relaxed pass is visible.

### market-live-3 (medium) - Live-lane residue is untracked after the 2026-09-04 no-live decision

Basis: doc_claimed (git history) plus live_state of the repo; the workstation itself was not inspected.
Known status: new.

Chronology, all from tracked files:
- 2026-08-13: owner authorizes working toward a bounded live test
  (`INTERNATIONAL_MM_LIVE_PILOT.md:3-5`).
- 2026-08-29: `config/international_live_execution_host.json` set to `ASSIGNED`
  (commit `839279b84`); still `ASSIGNED` on master today (line 4).
- 2026-08-31: two real attempts, `pilot-20260831T134425424Z` and
  `pilot-20260831T145154800Z`. The second resolved real credentials and reached an
  authenticated user-stream subscription, then failed before any heartbeat, cancel-all or
  order; the failing check is unrecoverable because the receipt kept only `RuntimeError`
  (`git show 1acf9ebbc:docs/operations/STATE_OF_PLAY.md`, rows "Verification" and "Live money").
  The same version records that all four WinCred targets were provisioned on the second PC
  and that the root plaintext `.env` was "moved intact outside Git" pending "the approved
  deletion procedure" (row "Credentials").
- 2026-09-04: owner instruction "no live trading"
  (`item-330-maker-economics-refocus-master-plan.md:107-117`); `STATE_OF_PLAY.md:18-19`
  repeats it.

Since then `STATE_OF_PLAY.md` has been rewritten (its rule is rewrite, never append) and a
Grep of the current file for `credential|stage 0|stage 1|portable|lifecycle` returns
nothing. No current canonical document says whether the plaintext credential source was
deleted, whether the WinCred entries still exist, or what the pilot wallet holds. The two
live runbooks were last touched 2026-08-30/31, do not mention the 09-04 instruction
(Grep: no match), still describe Stage 0/1 as "HOLD until every action-time gate below
passes" (`INTERNATIONAL_MM_LIVE_PILOT.md:33`), defer authority to a `STATE_OF_PLAY.md`
section that no longer exists (`:24-31`), and still call the portable extension "an unmerged
candidate" (`:21`) although `git branch -a --merged master` lists
`codex/portable-execution-host-clean-20260827`.

Why it matters: Windows generic credentials are returned by `CredReadW` to any process
running as that user with no prompt (`mm_credentials.py:94-136`). The workstation is where
coding agents run with broad shell authority. The documented loss bound is the 100 pUSD
wallet cap, so this is bounded, but a wallet private key in a plaintext file plus an
agent-readable vault, tracked nowhere, is exactly the kind of thing that is forgotten.

Recommendation: record one explicit disposition (credentials removed or retained, source
file deleted or location, wallet balance, host assignment) in a current canonical file,
and add the 09-04 decision to the top of both live runbooks.

### market-live-4 (medium) - The host registry has no "live is off" state

Basis: verified_in_code. Known status: new.

`load_execution_host_assignment` accepts exactly two statuses (`execution_host.py:264`).
`ASSIGNED` enables the portable lane for the named host and principal (`:285-308`).
`UNASSIGNED` enables the capture-colocated lane on the dedicated capture PC, because
`require_current_capture_execution_assignment` passes precisely when the status is
`UNASSIGNED` (`:311-329`). `PORTABLE_LIVE_EXECUTION_HOST.md:487-490` confirms the intent:
assigning a portable host is what disables the capture lane. The sealer also accepts the
portable profile on `master` (`international_live_wrapper_sealer.py:619-629`,
`stage1_cancel_all.py.tmpl:184-186`), and master now contains the portable code and the
assignment.

So the standing owner decision "no live trading" cannot be expressed in the one tracked
file that is described as "the sole role authority". It lives only in prose. The remaining
barriers are real (console-typed literal, a compare-only credential receipt younger than
two hours, host and principal hashes, create-only namespaces), so this is not an open
door. It is a missing kill switch.

Recommendation: add a third status (for example `DISABLED`) that both
`require_current_*` functions refuse, make it the default, and let the sealer refuse to
seal under it.

### market-live-5 (medium) - The live lane's own gate machinery is now its dominant failure mode

Basis: doc_claimed for the attempts, verified for sizes. Known status: known_open (the failures are recorded; the diagnosis is mine, labelled inferred).

Sizes from `git ls-tree -l HEAD`: in `src/weather/market/` alone the live lane is about
0.5 MB of Python (`mm_live_candidate_cli.py` 74 KB, `mm_live_lifecycle_probe.py` 72 KB,
`live_sdk_portability.py` 65 KB, `mm_official_adapter.py` 63 KB, `mm_live_pilot_cli.py` 62 KB,
`mm_live_bootstrap.py` 43 KB, `mm_credential_import_cli.py` 36 KB, plus credentials,
overlay, transport, geography, user stream). The sealed Stage 1 wrapper template is 72 KB
and Stage 0 is 40 KB; `international_live_wrapper_sealer.py` exceeds 3,000 lines; the
runbook is about 1,940 lines. The order being protected is the minimum size at the
minimum tick.

Both real attempts on 2026-08-31 were consumed by the protocol's own checks before any
exchange write, the cause of the second is permanently unknown, every attempt namespace is
single-use, and a session needs a credential receipt under 2 h old, a substrate preflight
under 600 s, a candidate plan under 300 s and a 240 s execution envelope
(`PORTABLE_LIVE_EXECUTION_HOST.md:558-573`). Item 330 still lists Stage 0/1 as required
evidence for the maker-economics decision (`item-330-*.md:225`, `:243`). If live is ever
re-authorized, the likeliest outcome on current evidence is another spent attempt that
fails inside the harness rather than a result about the exchange.

Recommendation: before any re-authorization, run the whole sealed path end to end against a
recorded fake exchange on the portable host until it passes twice in a row, and make every
gate failure name its check in the receipt.

### market-live-6 (low) - A partial `/books` response is recorded as a clean capture

Basis: verified_in_code. Known status: new. Confidence: medium (server behaviour not observable offline).

`ClobClient._post_order_books` returns `[]` for any unexpected payload shape and nothing
compares the number of returned books with the number of requested tokens
(`market_microstructure_capture.py:690-714`). `capture_status_from_result` reports `OK`
whenever `books > 0` (`:898-906`), `raw_book_refresh_ok` is `books > 0` (`:1609`), and the
cadence audit counts a timestamp if any one book row carries it
(`market_microstructure.py:498-519`). A capture that returned 18 of 22 tokens is
indistinguishable from a full one in status, in the fleet SLA and in the gap audit.

Recommendation: record `requested_tokens`, `returned_books` and the missing token ids in
the status row and treat a shortfall as `PARTIAL`.

### market-live-7 (low) - Dead trading-capable adapters and a `live_posted` label with nothing behind it

Basis: verified_in_code. Known status: new.

`PolymarketUSHTTPAdapter` and `PolymarketGlobalHTTPAdapter` declare
`supports_trading = True`, default to a real `RequestsTransport`, and implement
`place_order`/`cancel_all` (`mm_exchange.py:885-975`, `:978-1073`). Nothing in `src/` or
`scripts/` constructs them; only `tests/market/test_mm_exchange.py` does. The US one
contradicts the International-only rule in `AGENTS.md:50-52`, and the Global one hand-rolls
signing that the runbook calls diagnostic only (`INTERNATIONAL_MM_LIVE_PILOT.md:137-138`).
Separately, `market_making_run` in `live-pilot` mode writes lifecycle rows with transition
`live_posted` (`market_making_run_support.py:1198-1215`) although the run declares
`"posts_orders": False` (`market_making_run.py:856-857`) and has no adapter; its report
says "verify live gates before any adapter consumes them" (`:1260`) and no such adapter
exists. `mm_exchange.local_live_orders` then treats those rows as live orders (`:1082-1086`).
Today this is unreachable because the live-pilot gates have never passed; it is a latent
evidence-mislabel.

Recommendation: delete both HTTP adapters or strip their mutation verbs; rename the
transition to `live_intended` until a real adapter posts.

### market-live-8 (low) - SDK trust rests on first use; an unhashed `live` extra and an ambient copy exist

Basis: verified_in_code for the pin, doc_claimed for provenance. Known status: known_accepted in part.

The overlay is pinned by a full-tree manifest (2,260 files, 41 MB), a 34-wheel name and
hash manifest and the core wheel hash, validated before and after import, and activation
refuses if any `polymarket` package is already importable
(`live_sdk_overlay.py:225-287`, `:440-502`, `:457-460`). That proves immutability, not
provenance: nothing in the repository ties `core_wheel_sha256` to the reviewed upstream
commit cited in `INTERNATIONAL_MM_LIVE_PILOT.md:1928`. The private key is handed to this
package (`mm_credentials.py:392-396`). Two softer edges: `pyproject.toml:21-24` still offers
`live = ["polymarket-client==0.6.0"]` with a version pin only, which the runbook forbids
installing (`:837-838`), and `build_unified_clob_client` on its own checks only the version
string before importing (`mm_credentials.py:381-386`), so the hash guarantee holds only
through the sealed wrapper. The 2026-08-31 state file notes an ambient SDK in the
workstation's development checkout.

Recommendation: record how the wheel hash was derived from the reviewed upstream source,
remove the `live` extra, and have `build_unified_clob_client` require a recorded overlay
activation.

### market-live-9 (low) - Paper taker fee model cites the US exchange's fee page

Basis: verified_in_code. Known status: new. Taker is paused, so impact is small.

`DEFAULT_CONFIG` sets `taker_fee_rate: 0.05`, effective 2026-03-30, with
`taker_fee_provenance_url: "https://docs.polymarket.us/fees"`
(`taker_bot_strategy_registry.py:98-102`). The standing decision is International only, and
the live runbook cites `docs.polymarket.com/trading/fees` for the same purpose. Every
historical paper taker P&L carries a fee whose documented source is the wrong venue.
I could not check either page.

Recommendation: re-source the fee from the International schedule (or from
`exchange_economics`) and note which paper results used the old provenance.

## 5. Observations that are not findings

- CLOB book capture is REST polling at 60 s, 15 s near close
  (`market_microstructure_constants.py:11-12`). The managed loop forbids WebSocket and price
  history (`market_microstructure.py:1069-1075`). The only continuous WebSocket in
  production is the execution tape, which carries `last_trade_price` observations. Book
  dynamics between polls are not captured. This is a design limit for queue-position and
  adverse-selection work, not a bug.
- The enrichment WebSocket sample is 1 second or 5 messages
  (`market_microstructure_constants.py:25-26`), sends
  `{"operation": "subscribe", "assets_ids": [...]}` (`market_microstructure_capture.py:1876`)
  where the execution tape sends `{"assets_ids": [...], "type": "market"}`
  (`execution_tape_capture.py:221`), has no reconnect, and its errors are swallowed into a
  status field (`:1171-1172`). I could not determine offline whether it returns anything
  useful. Open question below.
- The execution tape subscribes only to each market's current local-date event
  (`execution_tape_capture.py:127`). Trading on date D's market before D and after local
  midnight is not on the tape. By design.
- Execution tape transport is sound: exponential backoff 1 s to 30 s
  (`:441-476`), 30 s inbound-silence timeout (`:370-375`), per-route subscription
  confirmation before `mark_connected` (`:394-409`), `mark_disconnected` in `finally`
  (`:424-432`), fsynced appends. No sequence numbers exist on that channel, so trades
  during a disconnect are lost but the interval is recorded.
- `authorize_stage1_lifecycle` accepts signature types 0-3
  (`mm_official_adapter.py:728`) while the client builder accepts only 2 and 3
  (`mm_credentials.py:374-375`). Harmless; the stricter check runs first.
- Stage 0's recovery cancel-all is itself gated on a geography receipt younger than 60 s
  and swallows the failure (`mm_live_bootstrap.py:406-415`). Stage 0 places no order, so
  this is acceptable; Stage 1's safety cancel is unconditional.
- I initially suspected the paper reward diagnostics were dead for International
  (`mm_paper.py:739-742`). They are not: the International branch returns an explicit
  zero-reward assumption first (`:701-738`). Not reported.
- Geography: the precredential geoblock check runs before credential resolution in Stage 0
  (`stage0.py.tmpl:954-956`). The second 08-31 attempt reached an authenticated stream, so
  that check must have passed from the portable host on that date (inferred). The project's
  own plan lists "Ontario restrictions" as a hard gate
  (`docs/research/MARKET_MAKING_PLAN.md:460-461`).

## 6. Strengths

1. One capability-gated, single-use, hard-clamped order path with signed-order identity
   proof and post-sign re-checks (`src/weather/market/mm_official_adapter.py`).
2. Credentials by reference only, direct-secret environment variables rejected, redacting
   reprs, type-only exception reporting through every layer
   (`src/weather/market/mm_credentials.py`, `mm_exchange.py:360-383`,
   `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl:1608-1629`).
3. Full-tree hash pin of the third-party SDK with pre and post import validation and
   ambient-package refusal (`src/weather/market/live_sdk_overlay.py`).
4. Host and principal binding with a strict registry reader, and a console-keyboard
   confirmation that headless tools cannot satisfy (`src/weather/execution_host.py`,
   stage templates).
5. Execution-tape transport with reconnect, silence detection, subscription proof, fsync
   and explicit dark-time accounting (`src/weather/market/execution_tape_capture.py`,
   `execution_tape_store.py`).

Also worth stating: the taker bot contains no network or order code at all, and US is
rejected by `SUPPORTED_PLATFORM_IDS`.

## 7. Not covered

- `mm_live_candidate_cli.py` (74 KB), `live_sdk_portability.py` (65 KB),
  `portable_live_candidate_preflight.py`: structure only.
- `mm_credential_import_cli.py`: function map and output hygiene only, not the
  create-only file handling.
- `execution_tape_store.py` beyond the ingest and seed-error paths (part rotation,
  dedupe identity rules).
- `stage0.py.tmpl` body and both PowerShell launcher templates; the two sealers in
  `src/weather/operations/` apart from the Git-proof section.
- Taker internals (`taker_bot_*`): confirmed paper-only, did not audit strategy, sizing or
  scoring logic.
- `market_microstructure_features.py`, `exchange_economics*.py`, `mm_policy.py`,
  `mm_paper*.py`: belong to the sibling market dimension.
- The third-party SDK itself (outside the repository), and the actual state of the
  workstation (WinCred entries, plaintext file, wallet balance).
- No tests were run and no live status file under `data/` was read, so nothing here is a
  claim about what production is doing right now.

## 8. Open questions for the owner

1. Were the four WinCred entries and the plaintext credential source removed after
   2026-09-04? What does the pilot wallet hold?
2. Should `config/international_live_execution_host.json` stay `ASSIGNED` while live is
   not authorized, given that the only other value enables the capture-host lane?
3. Has the execution tape ever reported `DISCONNECTED_SEED_ERROR`, and for how long?
   (`seconds_seed_error_dark` in its status file answers this.)
4. What is the current `max_iteration_elapsed_seconds` in `clob_loop_status.json`? If it is
   far above about 100 s, the book-gap audit has been running relaxed since that iteration.
5. Does the 15-minute enrichment WebSocket sample ever return rows? If not, remove it.
6. Is the 0.05 taker fee correct for International weather markets?
