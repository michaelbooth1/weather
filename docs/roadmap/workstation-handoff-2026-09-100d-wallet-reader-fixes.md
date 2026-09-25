# Workstation handoff 2026-09-100d — wallet reader fixes from the first live use

Written 2026-09-25 by the production agent after the first real use of the 100a reader
(`codex/wallet-public-reader-20260925` @ `1e89fc250`, served by the owner at 192.168.1.106:8765, called from the production PC
192.168.1.247). The LAN path, token, IP allowlist, cash, fills, activity and open orders all worked. Three defects:

1. **No marks at all, even for live markets.** `/summary` returned every position with `bid/ask/mid = null` and errors
   `book_mark_unavailable`, `reward_terms_unavailable` — including the live Chicago 68-69°F Sep 25 YES. The wallet holds ~104
   positions, ~100 of them long-resolved dust (MrBeast view-count markets, May-July Toronto/Hong Kong/Seoul temperature bands,
   settled losers like Chicago Sep 24 NO). A book + reward read per position exhausts the 30-request/minute budget, so every
   mark fails. Probable cause; confirm from the journal.
2. **Cold `/summary` exceeds the production client's 5 s timeout** (first call failed with `wallet_reader_client_failed`; a
   direct 60 s call succeeded and the next was served from cache in 0.03 s).
3. **Cached failures block retries:** after one failed composite read, `/summary` and `/open-orders` both returned
   `{"error": "read_unavailable"}` for the cache window, even for the open-orders route that has its own upstream read.

## 1. Fixes (same branch, on top of `1e89fc250`)

- **Classify positions before marking.** Use the data-api position fields (`redeemable`, `curPrice`, `endDate`/closed status via
  gamma `closed`/`active` for the condition, in one batched `/markets?condition_ids=` read) to split `live` from `resolved`.
  Mark (book + reward terms) **only live positions**; report resolved ones in a separate `resolved_positions` list with
  `redeemable`, size and last price, no upstream book reads. Add `--include-resolved` on the client if the owner wants them.
- **Budget per request, not per wallet:** a composite read must plan its upstream calls first and, if the plan exceeds the
  remaining minute budget, degrade (mark the first N live positions by value, flag the rest `budget_deferred`) instead of
  failing everything.
- **Cache per upstream read, not per composite:** a failed book read must not poison `/open-orders` or cash; a failure is
  cached only for its own key, and for at most 10 s.
- **Client timeout:** raise the production client default to 20 s (keep the 5 s floor configurable) and let the server
  return partial results with per-field errors rather than one opaque failure. Keep `wallet_reader_client_failed` but add a
  non-secret reason code (`timeout`, `http_<status>`, `refused`, `config`) so the caller knows what happened.
- Keep every 100a safety property unchanged: allowlist, GET only, no private key, SecretGuard, LAN/IP/token checks.

## 2. Tests (fixtures only)

A 104-position fixture (4 live, 100 resolved) marks exactly the live ones within budget; resolved positions make no book
reads; budget overflow degrades to `budget_deferred`; a failed book read leaves `/open-orders` and cash available; failure
cache TTL ≤ 10 s; client reason codes; cold composite latency bounded by the plan, not by the wallet size.

## 3. Boundaries and deliverables

No real account run by the agent (the owner restarts `serve` on the new tip). No `.env`. Report:
`docs/roadmap/agent-report-2026-09-100d-wallet-reader-fixes.md` (verdict first, tests, the tip). Push is authorized. The
production agent lands the final tip (roll-sensitive: schema registry) in the next quiet window after the bounded suite.
