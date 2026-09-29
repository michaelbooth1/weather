# Agent report 2026-09-100a — authenticated read-only wallet reader with a LAN API

**IMPLEMENTED; offline verification PASS. Real-account startup remains owner-only
and untested. Production roll verdict UNDECIDABLE on this workstation; do not
treat this report as runtime-adoption authority.**

Answers the [revised handoff 100a](workstation-handoff-2026-09-100a-wallet-public-reader.md).
Branch: `codex/wallet-public-reader-20260925`. Fetched base:
`df99f7fa` (`origin/master`, revised handoff). Verified implementation tip:
`17cc66768dbc54ed1894886ddb8d1f581f1d5e04`. Subsequent commits add this report
and regenerate the correspondence index; obtain the final published tip with
`git ls-remote origin refs/heads/codex/wallet-public-reader-20260925`.

## Delivered and safety boundary

- `wallet_reader.py` supplies `serve`, positions/marks, balance, account orders,
  fills, recent public history, reward reads and summary arithmetic.
- `wallet_reader_security.py` follows the reference `load_owner_credentials`
  shape: validated non-reparse common-root file, `dotenv_values(...,
  interpolate=False)`, eight named fields only, discard the mapping, suppress
  parser diagnostics, never export environment variables or touch WinCred.
  The parser necessarily builds the temporary mapping; no private-key entry is
  selected, inspected, retained or used. The builder never opened the real file.
- The independent `SecretGuard` preserves RE-1's remove-auth-fields then
  refuse-residual-secret behavior without importing that unmerged branch's
  signing/execution graph. It additionally strips normalized auth names and
  other participants' `owner` API-key fields. No signing SDK is imported.
- `wallet_reader_transport.py` is the sole upstream socket boundary: exact
  host/path/query allowlist, GET only, direct L2 HMAC, no redirects, proxies,
  retry/fallback/credential derivation, heartbeat, or balance-update call.
- `wallet_reader_server.py` binds an explicit RFC1918 IPv4 and authenticates
  every route with a constant-time bearer comparison plus an exact source-IP
  allowlist. No CORS; browser-origin requests refused. Unknown methods/paths
  never reach upstream. Error responses/logging cannot echo exception text.
- The production `wallet_reader_client.py` reads only ignored local client
  config, constrains LAN URL and routes, uses a five-second timeout and emits
  guarded JSON. Firewall script is owner-run, Private profile, one exact remote
  IP and TCP port, with `-WhatIf` and exact-rule `-Unregister` support.
- Every actual upstream request has an append-only intent/result journal entry:
  time, method, host, path, HTTP status and body SHA256; no headers or body.
  The schema registration is **additive-only**: `wallet_reader_request_v1`.

Reference implementation inspected as source only:
`origin/codex/re1-wallet-200-20260923:src/weather/market/re1_transport.py` and its
`re1_attended.py` SecretGuard. Endpoint/query contracts were checked against the
installed public SDK source, never imported. HMAC matches the official
[L2 authentication specification](https://docs.polymarket.com/getting-started/api).

## Exact upstream allowlist

All rows permit **GET only**. All unlisted combinations fail before any socket.
Origins are literal HTTPS, with no explicit port, userinfo, alternate spelling,
or path suffix. Unknown query names are rejected.

| Origin | Path | Allowed query names | L2 headers |
| --- | --- | --- | --- |
| `https://clob.polymarket.com` | `/data/orders` | `next_cursor` | Yes |
| same | `/data/trades` | `next_cursor`, `maker_address`, `after` | Yes |
| same | `/balance-allowance` | `asset_type=COLLATERAL`, `signature_type` | Yes |
| same | `/rewards/user` | `date`, `signature_type`, `next_cursor` | Yes |
| same | `/rewards/user/total` | `date`, `signature_type` | Yes |
| same | `/rewards/user/percentages` | `signature_type` | Yes |
| same | `/book` | `token_id` | No |
| same | `/rewards/markets/<0x + 64 hex>` | none | No |
| `https://data-api.polymarket.com` | `/positions` | `user`, `limit`, `offset`, `sizeThreshold` | No |
| same | `/trades` | `user`, `limit`, `offset`, `takerOnly` | No |
| same | `/activity` | `user`, `limit`, `offset`, `start`, `sortBy`, `sortDirection` | No |
| `https://gamma-api.polymarket.com` | `/markets` | `condition_ids`, `limit` | No |

In particular, mutating **GET** `/balance-allowance/update` is refused alongside
`/order`, `/orders`, `/cancel-all`, `/auth/*`, and both heartbeat paths. Account
queries are bound to the configured funder; open-order and position identities
are checked. The same process shares a rolling 30-request/minute budget and
30-second cache of successes **and failures**. No upstream polling runs by itself.

## Verification

All fixtures are synthetic; socket connect/bind is prohibited in reader tests.
No real `.env`, client config, account or venue was contacted by those tests.

- **127 passed**: `tests/market/test_wallet_reader.py`,
  `tests/operations/test_schema_registry.py`,
  `tests/operations/test_import_architecture.py`.
- **29 passed**: `tests/operations/test_agent_docs_audit.py`,
  `tests/reporting/test_correspondence_index.py`,
  `tests/reporting/test_roadmap_backlog.py`. This invokes the actual repository
  audit via its existing test entry point; the wrapper rejects that CLI when
  incorrectly classified as a `weather_heavy` module.
- `compileall -q app src tests`: PASS through the workstation heavy wrapper.
- PowerShell parser: firewall script PASS, no execution or firewall mutation.
- `git diff --check`: PASS.

Coverage includes every non-GET against each allowed path; unknown host/path,
cancel/auth/heartbeat and balance-update rejection; query/account scope; HMAC
vector and public-header isolation; redirect/proxy refusal; failure caching,
concurrent cache coalescing, minute-budget boundary; bounded malformed and
oversized replies; credential selection with a mapping that rejects any
private-key lookup; synthetic dotenv parsing without interpolation/export or
parser output; topology pins; secrets in replies/logs/exceptions; endpoint
parsing; pagination/repeated cursor; mismatched identities; missing marks;
exact bleed thresholds; LAN auth/IP/method/origin rejection; in-memory HTTP
handler; client timeout/GET/redaction; structural import and firewall checks.

The initial sandbox-principal test launch was refused by the existing host/principal
gate; re-running the unchanged wrapper as the attending principal passed. No
assignment or gate was modified. An initial oversized pytest parameter ID was
shortened; the tracking ratchet passed once the exact new files were staged.

Reproduce from this branch's worktree with the existing project interpreter,
using the canonical [workstation wrapper](../development.md#separate-non-capture-workstation):

```powershell
# Set these to the absolute worktree and existing project interpreter paths.
$readerRepo = (Get-Location).Path
$readerPython = (Resolve-Path ..\..\..\venv\Scripts\python.exe).Path
$readerArgs = @('-m','pytest','tests/market/test_wallet_reader.py','tests/operations/test_schema_registry.py','tests/operations/test_import_architecture.py','-q','--basetemp',"$readerRepo\scratch\wallet-reader-tests")
$readerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $readerArgs -Compress)))
& "$readerRepo\scripts\ops\workstation_heavy.ps1" -Kind pytest -PythonPath $readerPython -ArgumentsBase64 $readerEncoded -RepoRoot $readerRepo
```

This reproduction assumes the created `scratch/w/wallet-public-reader-20260925`
worktree under the main checkout; set the interpreter path explicitly for another
layout. Use a task-specific `--basetemp`, then remove only that resolved directory.
The host policies remain binding; workstation tests are not capture-host qualification.

## Owner start commands and interpretation

The complete setup/config procedure is in the [wallet-reader runbook](../operations/wallet-reader.md).
Only the owner provisions the reader token and production client JSON, starts the
service, and runs the firewall command. With `$readerPython` set as above, these
IPs are **examples**, to replace with the actual workstation and production PC:

```powershell
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765 -WhatIf
.\scripts\ops\register_wallet_reader_firewall.ps1 -AllowIp 192.168.1.30 -Port 8765
& $readerPython -m weather.market.wallet_reader serve --bind 192.168.1.20 --allow 192.168.1.30 --port 8765 --signature-type 3
# Production checkout, after owner creates config/local/wallet_reader_client.json:
python -m weather.market.wallet_reader_client summary
```

`--signature-type` is an explicit owner confirmation (2 Safe / 3 deposit wallet),
because the handoff does not permit loading that additional credential field.
Add `--campaign-capital <net contributions>` only after reconciling the dedicated
wallet baseline. Without it, cash/positions still work and campaign P&L remains
unknown. No initial-capital guess is taken from the 200 pUSD cap. Paid rewards
already in cash are not double-counted; reward accrual is not treated as paid.
Public history is recent/bounded, never used to manufacture realized campaign P&L.

Marks are two-sided midpoints, not liquidation proceeds. Missing marks make P&L
unavailable. Cold composite requests can exceed the client's five-second timeout;
retry after the read completes to use the cache. The owner accepts **unencrypted
HTTP bearer token and account data over the LAN**; TLS is optional later work.

## Roll disposition and exclusions

Executed `scripts/ops/roll_verdict.ps1 -Branch codex/wallet-public-reader-20260925
-Base origin/master`: exit 1, **UNDECIDABLE: no live closure evidence**, listing
the absent snapshot, CLOB, observation-trigger and enrichment status files.
No production closure was read or fabricated. Per-file disposition:

| Changed files | Roll disposition |
| --- | --- |
| `src/weather/schema_registry_recent_data.py` | Additive-only schema; registry family is roll-sensitive under the delegation contract. Actual closure membership must be re-proved on production by the roll tool. |
| `src/weather/market/wallet_reader.py`, `wallet_reader_security.py`, `wallet_reader_transport.py`, `wallet_reader_server.py`, `wallet_reader_client.py` | New modules; exact closure verdict unavailable on workstation, no live closure claim. |
| `tests/market/test_wallet_reader.py` | Test-only; exact production closure verdict unavailable. |
| `.env.example`, `.gitignore` | Template/ignore changes; exact production closure verdict unavailable. |
| `scripts/ops/register_wallet_reader_firewall.ps1` | PowerShell, roll-free class under the delegation contract; not executed. |
| `README.md`, `docs/README.md`, `docs/documentation-maintenance.md`, `docs/operations/README.md`, `docs/operations/config-inventory.md`, `docs/operations/wallet-reader.md`, this report and generated `docs/roadmap/correspondence-index.md` | Documentation, roll-free class. |

No real-account run, real credential-file read, private-key load, signing client,
order, cancel, heartbeat, authenticated probe, firewall registration, Scheduler
registration, production write, restart, deployment or merge was performed.
Only the topic branch and its report are published. No statistical/economic
finding or market-edge claim is made; clustering is inapplicable to these
deterministic fixture checks.
