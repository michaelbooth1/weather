# Workstation handoff 2026-09-100a — read-only public wallet reader

Written 2026-09-25 by the production agent at the owner's request. Serves RE-1 inventory decisions and ends the dependence on
pasted screenshots. Design: [positions review](audits/positions-review-2026-09-25.md) "Wallet reader".

## 1. Build (branch `codex/wallet-public-reader-20260925` from `origin/master`)

A keyless, read-only module `src/weather/market/wallet_public_reader.py` with a CLI (`python -m weather.market.wallet_public_reader`):

- **Inputs:** the public wallet address from `--address` or a local untracked file `config/local/wallet_public.json`
  (`{"address": "0x…"}`; add `config/local/` to `.gitignore`). Never read `.env` or any credential file; never import
  `py_clob_client` or any signing library.
- **Reads (GET only, host allowlist enforced in code):** Polymarket data-api `/positions`, `/trades`, `/activity` for the address;
  gamma market metadata and reward terms (`rewardsMinSize`, `rewardsMaxSpread`, rate) for each held condition; public CLOB
  `/book` for each held token; the pUSD balance via a public Polygon JSON-RPC `eth_call balanceOf` (contract address from
  gamma or config, not hard-coded guesses).
- **Output:** append one JSON object per run to `data/wallet_public/<UTC-date>.jsonl` with `schema_version`, `captured_at_utc`,
  balance, positions (size, avg price, current bid/ask/mid, mark value, reward minimum), recent trades, and per-source HTTP
  status. Register the schema in the schema registry. Bounded: at most ~20 GETs per run, 10 s timeout each, ≥ 60 s between runs.
- **Summary mode:** `--summary` prints cash, each position with its mark and unrealized P&L, and campaign P&L against the bleed
  limit (cash < 60 or campaign < −40 → print `BLEED_LIMIT`), so the owner and agents read one line instead of screenshots.

## 2. Tests

Unit tests with recorded fixtures only (no network in tests): parsing of each endpoint; host allowlist refuses any other host
and any non-GET; a structural test that the module imports no signing client and opens no `.env`; the bleed-limit arithmetic.

## 3. Boundaries and deliverables

No keys, no orders, no cancels, no authenticated endpoints; open orders and reward earnings stay in the app. Do not run it
during a live RE-1 session unless the owner agrees a cadence. No production-host scheduling (disk is Red). Report:
`docs/roadmap/agent-report-2026-09-100a-wallet-public-reader.md` (verdict first, one sample `--summary` run with the address
redacted, tests, the tip). An MCP wrapper is a later, separate step. Push is authorized.
