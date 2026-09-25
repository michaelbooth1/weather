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

The owner creates ignored `config/local/wallet_reader_client.json` on the client
checkout containing `{"url":"http://192.168.1.20:8765","token":"<owner token>"}`.
Do not commit it. This bearer token is separate from the venue's L2 credentials.
The client refuses public/DNS URLs, redirects and extra config fields, uses no
ambient proxy, and sends only these fixed GET routes with a five-second timeout:

```powershell
& $python -m weather.market.wallet_reader_client summary
& $python -m weather.market.wallet_reader_client open-orders
& $python -m weather.market.wallet_reader_client positions
& $python -m weather.market.wallet_reader_client trades --since 1790294400
& $python -m weather.market.wallet_reader_client rewards --date 2026-09-25
```

The server also supports `/health` and `/balance` with the same authentication.
`/health` proves the server responds, not venue access. No query parameters are
accepted except `since` on trades and `date` on rewards. Defaults are the last
24 hours and the current UTC day. Unknown paths and methods never reach upstream.

## Data, bounds, and interpretation

The sole upstream request gate in `wallet_reader_transport.py` owns the exact
host/path/query allowlist. It permits GET only, including the read
`/balance-allowance` but **not** the mutating GET `/balance-allowance/update`.
It attaches L2 HMAC headers only to private CLOB read paths. Public CLOB books,
market reward configuration, data-api positions/trades/activity and Gamma metadata
receive no auth headers. Redirects, proxies, arbitrary URLs and retries are absent.

Each successful or failed upstream read is cached for 30 seconds. The entire
server shares a lock and a rolling cap of 30 network attempts per 60 seconds.
Each attempt has a four-second socket timeout and a two-million-byte response
limit; cursor walks stop after five pages and explicitly refuse incomplete data.
The service is serial, so concurrent clients do not multiply the budget. Cold
composite routes can exceed the client's five-second timeout: retry after the
current read finishes; its results remain cached. No network polling runs by itself.

Each upstream attempt and completion appends to
`data/wallet_reader/<UTC-date>.jsonl`: registered schema, UTC time, GET, host,
path (no query), status and response-body SHA256. Transport failures have unknown
status/body hash. No headers, bodies, raw exceptions or credential values are
journaled. Redaction follows RE-1 SecretGuard's auth-field removal and refusal of
residual secrets; the reader also strips other participants' `owner` API-key fields.

Summary cash is CLOB collateral balance divided by one million; it is not a
fresh allowance update. Open orders must match the configured funder. Positions
must match the funder and unique token IDs. Best bid/ask are taken across all
positive-size levels; mark is the two-sided midpoint, **not executable proceeds**.
Missing/one-sided/crossed books leave marks and aggregate P&L unavailable. Gamma
provides reward size/spread, and public CLOB supplies current market reward terms.
Missing reward terms are flagged separately from missing marks.

Unrealized P&L is size times (midpoint minus average entry price), before any
unrepresented fees. Campaign P&L is cash plus marked inventory minus the explicit
net contribution baseline, which includes paid rewards already in cash and does
not add unverified reward accrual. It is meaningful only for a dedicated campaign
wallet with a reconciled baseline; unrelated holdings/transfers invalidate that
interpretation. Cash < 60 or known campaign P&L < -40 yields `BLEED_LIMIT`.
Other missing campaign information yields `INCOMPLETE`, never a trading go-ahead.

Authenticated trade pages are bounded/exhaustive or fail; public trades/activity
are explicitly the latest 100 rows, not a complete ledger. Reward earnings and
percentages are account reads, not payment verification. Data sources may lag and
are cached independently; a summary is not an atomic exchange snapshot.

## Update when

Update with any route, allowed query, credential field, valuation rule, cache,
budget, CLI, journal schema, or firewall behavior change. Unit tests are entirely
offline with synthetic credentials; real-account startup and firewall mutation
belong to the owner.
