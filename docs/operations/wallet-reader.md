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

Start from the reviewed topic worktree with the project's existing interpreter
(set `$python` to its absolute `venv\Scripts\python.exe` path). Substitute the
actual two LAN IPs for the illustrative RFC1918 addresses below:

```powershell
# Workstation IP 192.168.1.20; production PC IP 192.168.1.30 (examples only).
# Confirm existing wallet type: 2 = Safe; 3 = deposit wallet. Never guess it.
& $python -m weather.market.wallet_reader serve --bind 192.168.1.20 --allow 192.168.1.30 --port 8765 --signature-type 3
```

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
Use Ctrl+C to stop. There is no Scheduler registration or background installer.

The owner, in an elevated PowerShell session, previews then registers the exact
remote-IP/port rule on the workstation. Registration refuses an existing rule
of the same name instead of silently replacing it:

```powershell
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -WhatIf
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765
# Preview/remove only that exact named rule:
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -Unregister -WhatIf
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -Unregister
```

Binding accepts a literal RFC1918 IPv4, never wildcard, loopback or public IP.
Every LAN route requires the same bearer token and exact allowed source IP.
Browser Origin / Fetch Metadata requests are refused; no CORS headers are added.
**Plain HTTP carries the token and account data unencrypted over the home LAN.**
This is the owner's accepted scope; TLS is a separate optional improvement.

## Production client

For multiple campaigns in one wallet, optional `serve --campaigns <json>` uses
the [portfolio ledger](portfolio-ledger.md) and reports campaign-specific P&L and
limits. Its default owner-discretionary lots are outside bot bleed limits.
This mode adds a `campaigns` book and replaces the single-baseline status; it
does not enable enforcement or change the GET-only safety boundary.

The owner creates ignored `config/local/wallet_reader_client.json` on the client
checkout containing `{"url":"http://192.168.1.20:8765","token":"<owner token>"}`.
Do not commit it. This bearer token is separate from the venue's L2 credentials.
The client refuses public/DNS URLs, redirects and extra config fields, uses no
ambient proxy, and sends only these fixed GET routes. The default timeout is
20 seconds; `--timeout` accepts 5 through 120 seconds:

```powershell
& $python -m weather.market.wallet_reader_client summary
& $python -m weather.market.wallet_reader_client open-orders
& $python -m weather.market.wallet_reader_client positions
& $python -m weather.market.wallet_reader_client positions --include-resolved --timeout 20
& $python -m weather.market.wallet_reader_client trades --since 1790294400
& $python -m weather.market.wallet_reader_client rewards --date 2026-09-25
```

The server also supports `/health` and `/balance` with the same authentication.
`/health` proves the server responds, not venue access. No query parameters are
accepted except `since` on trades, `date` on rewards, and `include_resolved=true`
or `false` on summary/positions. Defaults are the last 24 hours, the current UTC
day, and hidden resolved rows. Unknown paths and methods never reach upstream.
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
The owner restarts the service after adopting reader changes; implementation and
tests do not access an account or restart a real reader.

Authenticated trade pages are bounded/exhaustive or fail; public trades/activity
are explicitly the latest 100 rows, not a complete ledger. Reward earnings and
percentages are account reads, not payment verification. Data sources may lag and
are cached independently; a summary is not an atomic exchange snapshot.

## Update when

Update with any route, allowed query, credential field, valuation rule, cache,
budget, CLI, journal schema, or firewall behavior change. Unit tests are entirely
offline with synthetic credentials; real-account startup and firewall mutation
belong to the owner.
