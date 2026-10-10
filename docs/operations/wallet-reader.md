# Read-only wallet LAN API

Status: canonical runbook. Owns the owner-started wallet reader, client, credential
selection, valuation assumptions, and narrowly scoped firewall rule.
Read when replacing account screenshots with read-only account data. Live orders
belong to the attended trading runbooks; this service cannot submit or cancel.

## Owner setup

Install the pinned project requirements before starting; `python-dotenv` is a
direct runtime dependency of the credential loader, not an optional SDK extra.

The owner supplies existing L2 credentials in the **common Git checkout's** `.env`.
The reader selects only `POLYMM_API_KEY`, `POLYMM_API_SECRET`,
`POLYMM_API_PASSPHRASE`, `POLYMM_WALLET_ADDRESS` (L2 signer address),
`POLYMM_FUNDER_ADDRESS` (held assets), `POLYMM_CLOB_HOST`, `POLYMM_CHAIN_ID`,
and `POLYMM_READER_TOKEN`. Host and chain must match the RE-1 pins.
The owner generates 32 random bytes, hex-encodes them, and saves that 64-character
reader token in `.env`. Use `.env.example` for names only. Do not paste tokens
into commands, reports, or chat. No WinCred, environment export, SDK construction,
key derivation, or private-key lookup occurs. The dotenv parser reads into memory
with interpolation disabled, selects the named fields, and discards the mapping.
This is the RE-1 loader shape with the private-key selection removed.

The reader runs on the **workstation** only (it holds L2 credentials; the capture
host stays credential-free). Start it from a **dedicated linked worktree** at a
reviewed `master` commit, never from the main checkout: the main checkout's
`data\` is the write-protected workstation mirror (deny-write ACL), and the reader
journals every upstream GET under `<checkout>\data\wallet_reader\` *before*
sending it. From the main checkout that journal write fails, no upstream call is
made, and every read answers `503 read_unavailable` (the 2026-09-30 outage). A
stale checkout without `src/weather/market/wallet_reader.py` cannot start it.
Use the main checkout's interpreter (set `$python` to its absolute
`venv\Scripts\python.exe` path) with the worktree as the working directory; the
root `weather/__init__.py` shim then imports the worktree's `src`, and `.env` is
still read from the common checkout. The addresses below are examples: find the real values with
[the restart checklist](#is-it-running-restart-after-a-stop-or-reboot).

```powershell
# Workstation IP 192.168.1.20 (example only).
# Confirm existing wallet type: 2 = Safe; 3 = deposit wallet. Never guess it.
& $python -m weather.market.wallet_reader serve --bind 192.168.1.20 --port 8765 --signature-type 3
# Optional narrowing to one caller (production PC 192.168.1.30, example only):
& $python -m weather.market.wallet_reader serve --bind 192.168.1.20 --allow 192.168.1.30 --port 8765 --signature-type 3
```

**Caller admission (owner decision 2026-10-09).** By default `serve` admits any
caller whose source is a literal RFC1918 IPv4 (`10/8`, `172.16/12`, `192.168/16`)
or loopback (`127/8`), so both of the owner's PCs can read. Public, link-local,
CGNAT, multicast and every IPv6 source are refused twice: at connection accept
(`verify_request`) and again in the request `dispatch`. `--allow <RFC1918 IPv4>`
is optional and, when given, narrows admission to that exact address as before.
The bearer token, the GET-only route and query allowlist, the rolling rate cap and
the lock are unchanged; every caller still needs the token.

The **bind** stays a literal RFC1918 IPv4: never wildcard (`0.0.0.0`), public,
IPv6 or loopback. Loopback is deliberately not bindable: the reader exists for
LAN reads, a loopback-only listener cannot serve the production PC, and a
same-machine caller does not need it. A client on the workstation itself connects
to the workstation's own LAN IP (the bind address); Windows sends that traffic with
the LAN IP as its source, which the default admits. Loopback admission only matters
for a source that genuinely arrives as `127.x`.

On the workstation this command runs as the host-local S4U at-logon scheduled
task `\WeatherWalletReader` (inventoried in `config/scheduled_tasks.json`). Its
task name, `python.exe` action and `-m weather.market.wallet_reader serve`
arguments are the identity the heavy-workload residual scan allowlists
([host load policy](HOST_LOAD_POLICY.md)); renaming the task or changing its
action makes stale-marker recovery count it as residual heavy work again.

Optionally add `--campaign-capital <net-contributed-pUSD>` only after reconciling
the dedicated campaign wallet's initial equity plus deposits minus withdrawals.
For RE-1, the owner should pass equity at the **2026-09-22 campaign start**,
adjusted for subsequent deposits and withdrawals. Reconcile that starting equity
on the same cash-plus-live-marks basis used now, keeping historical resolved dust
outside both sides so it cancels; do not use lifetime cost basis or lifetime deposits.
Also supply `--campaign-start-utc <timezone-aware-ISO-instant>` for the exact
reconciled baseline instant. Positive resolved lots require acquisition evidence
relative to that instant; omitting it makes campaign P&L incomplete when such lots
exist. A calendar date, settlement/end date or position's last price cannot date
its acquisition. Campaign acquisitions after that instant add their unredeemed
terminal value to current equity; historical dust remains outside the baseline.
No wallet cap is assumed to be starting capital. Without this value campaign P&L
is `null`/`INCOMPLETE`, although cash below the limit still yields `BLEED_LIMIT`.
A foreground run stops with Ctrl+C. For normal use,
[the logon task](#start-at-logon-check-and-restart) runs the same command
automatically.

The owner, in an elevated PowerShell session, previews then registers the
remote-IP/port rule on the workstation. Registration refuses an existing rule
of the same name instead of silently replacing it. `-AllowIp` is optional: given,
the rule `WeatherWalletReader-<ip>-<port>` admits that one remote PC; omitted, the
rule `WeatherWalletReader-anylan-<port>` admits the three RFC1918 ranges:

```powershell
.\scripts\ops\register_wallet_reader_firewall.ps1 -Port 8765 -WhatIf   # any-LAN rule
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -WhatIf
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765
# Preview/remove only that exact named rule:
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -Unregister -WhatIf
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -Unregister
```

**How the firewall interacts with any-LAN admission.** The Windows inbound rule
filters before `serve` sees a connection. An existing exact-IP rule
(`WeatherWalletReader-<production-ip>-8765`) therefore still blocks every *other
remote* PC at the OS level, whatever `serve` would admit. Same-machine traffic
(the workstation calling its own LAN IP or loopback) is not filtered by an inbound
rule at all. With only the owner's two PCs, the existing exact-IP rule already
admits both (the production PC through the rule, the workstation as same-machine
traffic), so **the owner can keep it**; register the any-LAN rule only if a third
LAN PC must read. `serve` without `--allow` is still required for the workstation
itself to be admitted.

Every LAN route requires the same bearer token and an admitted source.
Browser Origin / Fetch Metadata requests are refused; no CORS headers are added.
**Plain HTTP carries the token and account data unencrypted over the home LAN.**
This is the owner's accepted scope; TLS is a separate optional improvement.

## Start at logon, check, and restart

The workstation task `WeatherWalletReader` starts the reader one minute after the
owner logs on (DECISION_LOG 2026-09-30). It runs as the owner under S4U with
limited rights, so no window opens and no password is stored. It keeps running
after logoff and has no time limit. A reboot or power loss stops it until the
owner's next logon. If nobody logs on after a boot, it does not start. The task
does not retry a failed start. A crash leaves the reader down until the next
logon or a manual start, and the production client then reports `refused` or
`timeout`. The task carries only `--bind`, the optional `--allow`, `--port` and
`--signature-type`; without `-AllowIp` it omits `--allow` (any-LAN default). Campaign flags need a foreground run instead.

After registering the firewall rule, the owner creates a dedicated detached
worktree at the reviewed commit and registers the task from it in an elevated
PowerShell at the main checkout. The task runs the main checkout's
`venv\Scripts\python.exe` (`-PythonPath`, default: the common checkout's venv)
with the worktree as its working directory, so its journal lands in the
worktree's own `data\wallet_reader\`. With `-AllowIp` the registrar requires the
exact `WeatherWalletReader-<ip>-<port>` rule; without it, any
`WeatherWalletReader-*-<port>` rule (exact-IP or anylan), because the firewall
still scopes the remote PCs. The registrar refuses a bind address this
PC does not hold, a missing matching firewall rule, the main checkout (or any
non-linked checkout), a worktree whose `HEAD` is not `-ExpectedCommit` or has
uncommitted tracked changes, a missing interpreter, a reader module that does not
import from `<worktree>\src`, an unwritable `data\wallet_reader\` (checked by
creating and deleting a probe file; a real run creates the folder), and an
existing task. `-WhatIf` prints the planned interpreter, working directory,
commit and journal path. To change any value, or to move to a newer reviewed
commit, unregister and register again (the task description records the commit):

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
git fetch origin
$sha = git rev-parse origin/master   # the reviewed commit
git worktree add --detach "..\weather-wallet-reader-$($sha.Substring(0,8))" $sha
$wt = (Resolve-Path "..\weather-wallet-reader-$($sha.Substring(0,8))").Path
# Default any-LAN admission (add -AllowIp 192.168.1.30 to narrow to one caller):
& "$wt\scripts\ops\register_wallet_reader_logon_task.ps1" -RepoRoot $wt -ExpectedCommit $sha -Bind 192.168.1.20 -SignatureType 3 -WhatIf
& "$wt\scripts\ops\register_wallet_reader_logon_task.ps1" -RepoRoot $wt -ExpectedCommit $sha -Bind 192.168.1.20 -SignatureType 3
Start-ScheduledTask -TaskName WeatherWalletReader   # start now instead of at next logon
& "$wt\scripts\ops\register_wallet_reader_logon_task.ps1" -Unregister   # stops and removes it
```

**Restart serve after updating.** A running reader keeps the code it started
with; a newer reviewed commit (for example the any-LAN default) takes effect only
after the owner, on the workstation, in an elevated PowerShell at the main checkout:
(1) creates the new detached worktree at the reviewed `origin/master` commit as
above; (2) unregisters the old task (`-Unregister`, which also stops the running
reader; confirm `Get-NetTCPConnection -LocalPort 8765 -State Listen` is empty);
(3) registers from the new worktree, omitting `-AllowIp` for any-LAN or passing
it to narrow; (4) `Start-ScheduledTask -TaskName WeatherWalletReader`; (5) checks
from both PCs with the client (step 1 below). A foreground reader is restarted with
Ctrl+C and the new command line from the new worktree.

Keep the worktree while the task points at it. After re-registering on a newer
worktree, the older worktree (and its `data\wallet_reader\` journal, which is
account-read evidence) is retired only deliberately, never deleted casually.

1. **Check.** On the workstation, a live reader shows one listener:
   `Get-NetTCPConnection -LocalPort 8765 -State Listen`. From the production PC,
   `& $python -m weather.market.wallet_reader_client summary` should return JSON.
   Next, `Get-ScheduledTaskInfo -TaskName WeatherWalletReader` shows the
   `LastTaskResult`. `267009` (0x41301) means running, and `1` means the reader
   refused to start.
2. **Find the values.** Never copy the example IPs.
   - `--bind`: the workstation's own LAN IPv4, from
     `Get-NetIPAddress -AddressFamily IPv4`.
   - `--allow` (optional; omit for any-LAN): the one caller's LAN IPv4. An
     exact-IP firewall rule records it in its name,
     `WeatherWalletReader-<allow-ip>-<port>`. List the rules with
     `Get-NetFirewallRule -Name 'WeatherWalletReader-*' | Select-Object Name, Enabled`.
   - `--signature-type`: the existing wallet's type. The owner's `.env` records it
     as `POLYMM_SIGNATURE_TYPE`; serve does not read that field, so pass it
     explicitly.

   If DHCP changed either PC's address, register the firewall rule and the task
   again, and update the client's `url` too. The client config is described
   under [production client](#production-client).
3. **Diagnose.** Run the `serve` command above in a PowerShell window with those
   values. Success prints nothing; the process simply keeps serving. Failure
   prints only `{"error": "wallet_reader_failed"}` and exits 1, because details
   are suppressed. Recheck that the bind IP belongs to this PC, that port 8765 is
   free, that the `.env` fields exist, and that `--campaigns` JSON validates.
   If the reader listens but production gets `http_503` on every read and
   `<checkout>\data\wallet_reader\` gains no new lines, the journal cannot be
   written (for example a reader started from the write-protected main checkout):
   re-register from a dedicated worktree as above.
   Stop it with Ctrl+C, then `Start-ScheduledTask -TaskName WeatherWalletReader`.
4. **Confirm.** Repeat step 1.

## Production client

For multiple campaigns in one wallet, optional `serve --campaigns <json>` uses
the [portfolio ledger](portfolio-ledger.md) and reports campaign-specific P&L and
limits. Its default owner-discretionary lots are outside bot bleed limits.
This mode adds a `campaigns` book and replaces the single-baseline status; it
does not enable enforcement or change the GET-only safety boundary.

The owner creates ignored `config/local/wallet_reader_client.json` on the client
checkout containing `{"url":"http://192.168.1.20:8765","token":"<owner token>"}`.
Do not commit it. This bearer token is separate from the venue's L2 credentials.
The URL host must be a literal RFC1918 or loopback IPv4; on the workstation itself
use its own LAN IP (the bind address), since the reader never binds loopback.
The client refuses public/DNS/IPv6 URLs, redirects and extra config fields, uses no
ambient proxy, and sends only these fixed GET routes. The default timeout is
20 seconds; `--timeout` accepts 5 through 120 seconds:

```powershell
& $python -m weather.market.wallet_reader_client summary
& $python -m weather.market.wallet_reader_client open-orders
& $python -m weather.market.wallet_reader_client positions
& $python -m weather.market.wallet_reader_client positions --include-resolved --timeout 20
& $python -m weather.market.wallet_reader_client trades --since 1790294400
& $python -m weather.market.wallet_reader_client rewards --date 2026-09-25
& $python -m weather.market.wallet_reader_client settlement --since 1790294400
```

The server also supports `/health` and `/balance` with the same authentication.
`/health` proves the server responds, not venue access. No query parameters are
accepted except `since` on trades and settlement, `date` on rewards, and
`include_resolved=true` or `false` on summary/positions, and `fresh=1` on
open-orders. Defaults are the last 24
hours (trades), the last 7 days (settlement), the current UTC day, and hidden
resolved rows. Unknown paths and methods never reach upstream.
**Fresh open orders.** `GET /open-orders?fresh=1` always queries the venue and
never answers from the 30-second cache; its result is still stored in the cache so
cached readers benefit. Every fresh call (each page) counts against the same
rolling 30-per-60-second cap and is refused (`503 read_unavailable`) over it,
exactly like other reads; token and source checks are unchanged. Only the S0
section 5 time-to-zero loop uses it, through the Python helper
`weather.market.wallet_reader_client.open_order_count(fresh=True)` (returns the
open-order count; `fresh=False` uses the cached path). Every other caller and the
CLI keep the cached `/open-orders`.

Client failures retain `wallet_reader_client_failed` and add a safe `reason`:
`timeout`, `http_<status>`, `refused`, or `config`; raw exceptions stay suppressed.

## Data, bounds, and interpretation

The sole upstream request gate in `wallet_reader_transport.py` owns the exact
host/path/query allowlist. It permits GET only, including the read
`/balance-allowance` but **not** the mutating GET `/balance-allowance/update`.
It attaches L2 HMAC headers only to private CLOB read paths. Public CLOB books,
market reward configuration, data-api positions/trades/activity and Gamma metadata
receive no auth headers. Redirects, proxies, arbitrary URLs and retries are absent.

Each successful upstream read is cached for 30 seconds; failures for 10 seconds,
only under their own host/path/query key. There is no composite-response cache.
The entire server shares a lock and a rolling cap of 30 attempts per 60 seconds.
Each attempt has a four-second socket timeout and a two-million-byte response
limit; cursor walks stop after five pages and explicitly refuse incomplete data.
The service is serial, so concurrent clients do not multiply the budget.
Summary/positions admit at most 24 new GETs within the remaining minute budget,
with a 16-second planning deadline; each socket timeout is clipped to the time
remaining. No new socket opens after that deadline. This bounds fan-out, not
an absolute wall-clock guarantee for DNS, a trickling body, disk I/O, or a queued
LAN request. No network polling runs by itself.

Summary reads cash and orders first. Inventory discovery uses bounded pages and
Gamma only for holdings not already redeemable, in batches of at most 20 distinct
condition IDs (`limit` equals batch size). A failed or malformed batch leaves
only its own conditions unclassified; successful batches are retained. It then
plans book/reward calls for live positions
in descending reported value (size times last price, falling back to entry price).
Cached reads cost no network budget. Positions that do not fit carry
`budget_deferred`; other fields remain available. Summary field failures use
an `errors` map, missing values are null, and position failures remain on each row.
The `plan` object reports admitted/used GETs and planned/deferred live rows.

Each upstream attempt and completion appends to
`data/wallet_reader/<UTC-date>.jsonl`: registered schema, UTC time, GET, host,
path (no query), status and response-body SHA256. Transport failures have unknown
status/body hash. No headers, bodies, raw exceptions or credential values are
journaled. Redaction follows RE-1 SecretGuard's auth-field removal and refusal of
residual secrets; the reader also strips other participants' `owner` API-key fields.

Summary cash is CLOB collateral balance divided by one million; it is not a
fresh allowance update. Open orders must match the configured funder. Positions
must match the funder and unique token IDs. A redeemable position or Gamma
`closed=true` is resolved; Gamma `closed=false, active=true` establishes live.
An expired end date or zero last price alone does not establish resolution.
Uncertain rows remain in `unclassified_positions` and prevent live and campaign totals.
Resolved positions never request books or rewards. They carry size, redeemable
status and last price in a separate `resolved_positions` list, shown only with
`--include-resolved`; `resolved_count` is always present. The `/positions` response
is an object with these lists, errors, status and plan, rather than a bare list.
Best bid/ask for live positions are taken across all
positive-size levels; mark is the two-sided midpoint, **not executable proceeds**.
Missing/one-sided/crossed books leave live marks and campaign P&L unavailable. Gamma
provides reward size/spread, and public CLOB supplies current market reward terms.
Missing reward terms are flagged separately from missing marks.

Summary `marked_positions_pusd` and `unrealized_pnl_pusd` cover **live positions
only**. Live unrealized P&L is size times (midpoint minus average entry price),
before any unrepresented fees. `mark_basis` is `live_two_sided_mid`.
Resolved holdings use last price only when terminal (0 or 1). Their separate
`resolved_pnl_vs_cost_pusd` sums terminal marked value minus cost; it is `null`
if any resolved value is unavailable and zero for an empty resolved list.
`resolved_count` and this informational total remain visible even when resolved
rows are hidden. Resolved P&L does not enter live totals or campaign P&L; this
comparison is not a realized-P&L ledger or proof of redemption. Positive resolved
holdings also appear in summary's always-visible `unredeemed_positions`, with
title, outcome, size, `terminal_value_pusd`, and `campaign_scope`. A terminal 0/1
data-api price or token-matched closed Gamma outcome price values the lot; conflicting
terminal prices or nonterminal prices leave its value unknown. `redeemable=false`
alone is not proof of redemption. Zero-size or absent lots add nothing to cash.

When a baseline instant and positive resolved lots exist, summary attempts a
bounded complete `/activity` walk from Unix zero, oldest first, at most five
100-row pages within the existing 24-GET/16-second composite budget. It runs after
live marking and uses the existing cache, GET allowlist and journal. The latest
100 rows from `/trades` are never treated as complete history. Only account- and
token-matched trade history whose buys minus sells reconcile exactly to the held
quantity can establish age. Every acquisition in the remaining inventory must
fall on the same side of the baseline (strictly after is campaign); mixed-age
inventory is unknown rather than assigned a speculative FIFO age. Splits, merges,
redemptions, missing/duplicate/future records, quantity mismatches, read failures
or exhausted pagination/budget leave acquisition unproved. A fully sold lot can
reset the age of a later acquisition. No extra history requests occur without a
baseline or without positive resolved lots.

`unredeemed_campaign_value_pusd` sums known campaign terminal values; historical
dust stays only in the resolved informational comparison. Unknown age produces
`unredeemed_acquisition_time_unknown`; any unknown unredeemed terminal value
produces `unredeemed_terminal_value_unknown` in `incomplete_reasons`. Either makes
campaign P&L null and status `INCOMPLETE`. `bleed_limit_reached` independently
preserves a known cash-limit breach even when status must be incomplete.
Missing resolved information does not hide available live marks.
Campaign P&L is cash plus **live marked inventory and campaign unredeemed terminal
value**, minus the explicit net contribution baseline. It includes paid rewards
already in cash and does not add unverified reward accrual. It is meaningful only for a dedicated campaign
wallet with a reconciled baseline; unrelated holdings/transfers invalidate that
interpretation. Cash < 60 or known campaign P&L < -40 yields `BLEED_LIMIT`.
Other missing campaign information yields `INCOMPLETE`, never a trading go-ahead.
## Settlement watcher (`/settlement`)

`/settlement?since=<unix seconds>` covers every market currently held (data-api
positions) or filled since `since` (authenticated CLOB `/data/trades` for the funder),
inside one 24-GET/16-second composite plan using only the allow-listed routes above:
positions, fills, and Gamma `/markets` in chunks of at most 20 conditions. Per market:

- venue `resolution_state`: `resolved` only when Gamma says `closed` and every outcome
  price is exactly 0 or 1 summing to 1; otherwise `closed_awaiting_terminal_price`,
  `open`, `unknown` or `metadata_unavailable`. Also `umaResolutionStatus`, the declared
  `resolutionSource` and `venue_outcome_basis` (`weather_gov`, `wunderground`, `other`);
- `venue_winning_outcome`, and per held token its size, `redeemable` flag and terminal price;
- `settlement_proxy`: the latest-revision row of the local WU settlement ledger
  `<settlement root>/<location>/ledger.jsonl` for the event (settlement high and its
  native `settlement_unit`, winning band, source and the ledger's own reconciliation
  status). The location comes from `config/location_market_events.json` event slug
  prefixes; non-weather markets are `proxy_not_applicable`. The root defaults to
  `data/settlements`; `serve --settlement-root <dir>` points elsewhere. Each location's
  file is streamed once per request with no size cap (memory is bounded by a 1 MiB per-line limit;
  longer lines are skipped); no settlement or model module is imported.

Flags: `disagreements` (the proxy's winning band and the venue's winner disagree about
this band, compared by label text), `unredeemed_winners` (a held token whose terminal
price is 1) and `resolved_unreconciled` (a venue-resolved holding with no proxy label
or a ledger status other than `match`). The weather.gov page itself is **not** fetched:
for a `weather_gov` basis the venue's resolved outcome *is* the weather.gov outcome.
A reader on the workstation reads the workstation's ledger copy, which may lag
production; a missing label shows as `proxy_label_absent`, never as agreement.
Failures leave `status: PARTIAL` with an `errors` map; nothing is inferred.

The owner restarts the service after adopting reader changes (`Stop-ScheduledTask`
then `Start-ScheduledTask -TaskName WeatherWalletReader`); implementation and
tests do not access an account or restart a real reader.

Authenticated trade pages are bounded/exhaustive or fail; public trades/activity
are explicitly the latest 100 rows, not a complete ledger. Reward earnings and
percentages are account reads, not payment verification. Data sources may lag and
are cached independently; a summary is not an atomic exchange snapshot.

## Update when

Update with any route, allowed query, credential field, valuation rule, cache,
budget, CLI, journal schema, firewall, or logon-task behavior change. Unit tests are entirely
offline with synthetic credentials; real-account startup and firewall mutation
belong to the owner.
