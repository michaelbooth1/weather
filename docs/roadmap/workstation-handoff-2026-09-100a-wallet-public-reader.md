# Workstation handoff 2026-09-100a — authenticated read-only wallet reader with a LAN API

Written 2026-09-25 by the production agent; **revised the same day on the owner's instruction**: authenticated reads (open
orders, reward earnings), credentials from the workstation `.env` used safely, and a local API the production PC can call over
the home LAN. Owner decision recorded in DECISION_LOG 2026-09-25. Context: [positions review](audits/positions-review-2026-09-25.md).

**The one rule that makes this safe:** the reader can *read* the account and can never *change* it. The L2 API key that
authenticates reads can also cancel orders, so "read-only" must be structural (code that cannot issue anything but an
allowlisted GET), not a convention. The private key is never loaded.

## 1. Credentials (follow the RE-1 pattern exactly)

- Reuse the loader shape of `load_owner_credentials` in `src/weather/market/re1_transport.py` (branch
  `origin/codex/re1-wallet-200-20260923`): `dotenv_values(common_repository_root() / '.env', interpolate=False)` in memory, via
  `validate_regular_nonreparse_file`; never export to `os.environ`, never echo parser errors, never copy the file, never touch
  WinCred. Wrap loaded secrets in the same `SecretGuard` so no log line, response body or exception text can contain them.
- **Load only** `POLYMM_API_KEY`, `POLYMM_API_SECRET`, `POLYMM_API_PASSPHRASE`, `POLYMM_WALLET_ADDRESS`, `POLYMM_FUNDER_ADDRESS`,
  `POLYMM_CLOB_HOST`, `POLYMM_CHAIN_ID`, plus the new `POLYMM_READER_TOKEN` (below). **Never read `POLYMM_PRIVATE_KEY`**: select
  keys by name from the parsed mapping and drop the rest immediately. Refuse to start if `CLOB_HOST`/`CHAIN_ID` differ from the
  RE-1 pins.
- The agent building this **must not open `.env`**. Read `.env.example` for names and add the new
  `POLYMM_READER_TOKEN=` line (and a comment) to `.env.example`; the owner generates the value (32 random bytes, hex) and puts it
  in `.env`. Tests use fixture values, never real ones.

## 2. Reader core (`src/weather/market/wallet_reader.py`)

- Uses L2 HMAC headers only (no signing library for orders, no `Account.from_key`). If the pinned `polymarket` SDK is used, use
  only its read methods through a wrapper that exposes nothing else; otherwise build L2 headers directly.
- **Endpoint allowlist, GET only, enforced in one function every request passes through:** CLOB open orders for the funder,
  trades/fills, balance-allowance (read), reward earnings / user reward percentages, public `/book` and `/rewards/markets/<id>`;
  data-api `/positions`, `/trades`, `/activity`; gamma market metadata. Anything else — any non-GET, any `cancel`, `order`,
  `heartbeat`, `auth`/key-derivation path, or other host — raises before a socket opens. Test this exhaustively.
- Never call the heartbeat endpoint (RE-1 owns it). Cache each upstream read for 30 s; at most ~30 upstream GETs per minute.
- Journal every upstream request (method, path, status, sha256 of body; never headers) to `data/wallet_reader/<UTC-date>.jsonl`.

## 3. LAN API (`python -m weather.market.wallet_reader serve`)

- stdlib `http.server` (or an already-pinned dependency; add nothing heavy). Bind to the workstation's **LAN IPv4 only**
  (`--bind <ip> --port 8765`), never `0.0.0.0` or a public interface. Refuse to start if the bind address is not RFC 1918.
- **Auth:** every request needs `Authorization: Bearer <POLYMM_READER_TOKEN>`, compared in constant time; also refuse any
  client IP not in `--allow <production-PC-IP>`. No CORS, no browser use.
- **GET routes only:** `/health` (no auth detail), `/summary` (cash, positions with bid/ask/mid marks, open orders, unrealized
  and campaign P&L, `BLEED_LIMIT` when cash < 60 or campaign < −40), `/positions`, `/open-orders`, `/trades?since=`,
  `/balance`, `/rewards?date=`. Any other method or path returns 404/405 without touching upstream. Responses are account data,
  never credentials (`SecretGuard` scrubs).
- Register the Windows Firewall inbound rule in a small `scripts/ops/register_wallet_reader_firewall.ps1 -AllowIp <ip>
  -Port 8765` (remote address scoped to that IP, Private profile only), with `-WhatIf` and `-Unregister`; the owner runs it.
- Plain HTTP on the home LAN is acceptable to the owner for now; note it in the report (the token and account data cross the
  LAN unencrypted) and leave TLS as an optional later step.

## 4. Production-side client (`src/weather/market/wallet_reader_client.py`)

A tiny GET-only client and CLI (`python -m weather.market.wallet_reader_client summary|open-orders|positions|trades|rewards`)
that reads `{"url": "http://<workstation-ip>:8765", "token": "…"}` from the untracked `config/local/wallet_reader_client.json`
(add `config/local/` to `.gitignore`), 5 s timeout, prints JSON. The production agent uses this instead of screenshots.

## 5. Tests (fixtures only, no network, no real credentials)

Allowlist refuses every non-allowlisted method, path and host (including `DELETE /order`, `/orders` cancel-all, heartbeat,
`/auth/*`); the loader never touches `POLYMM_PRIVATE_KEY` even when present in a fixture `.env`; `SecretGuard` scrubs secrets
from responses, logs and exceptions; server rejects missing/wrong token, non-allowed client IP, non-RFC1918 bind, non-GET;
`/summary` arithmetic and `BLEED_LIMIT`; a structural test that the module imports no order-signing code.

## 6. Boundaries and deliverables

The agent never runs the reader against the real account or opens `.env`; the owner starts `serve` and runs the firewall
script. No orders, cancels or signing — ever — from this code. Running it during an RE-1 session is fine (reads only, no
heartbeat) but keep the 30 s cache. Report: `docs/roadmap/agent-report-2026-09-100a-wallet-reader.md` (verdict first, the
allowlist table, test list, the owner's start commands, the tip). Push is authorized.
