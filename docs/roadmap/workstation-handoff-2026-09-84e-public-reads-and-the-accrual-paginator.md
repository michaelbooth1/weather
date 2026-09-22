# Workstation handoff 2026-09-84e — public reads blocked by Cloudflare; accrual pages the whole universe

Written 2026-09-22 ~13:05 Eastern by the production agent, after the owner's fourth real `preflight` on
`7e6e1709c` (receipt `preflight-20260922T163321901214Z`, 16:33–16:46Z) — the first run to get past selection (a
band qualified at 16:33Z). It reached the twenty-read loops and exposed two defects that would also have ended a
`live` session at its close. No session ran on 2026-09-22; session 1 is 2026-09-23. This mission was dispatched to
the workstation as a chat prompt plus one addendum before this file existed; this file is the repo record and the
authority if the two differ. All 84a–85b boundaries bind. Branch `codex/re1-public-reads-ua-20260922`, stacked on
`7010a0b58` (84d), draft PR onto PR 84.

## 1. What the run showed (owner journal summary, statuses only)

| step | result | cause |
| --- | --- | --- |
| `open_orders` | 19/20; index 11 `RequestRejectedError` | `/data/orders` answered 200 ×19, **500 ×1** — venue-side transient |
| `positions` | 19/20; index 19 `HTTPError` | data-api transient; `fetch_current_positions` sends `User-Agent: weather-mm-live-probe/1` and passed |
| `balances` | **0/20 `HTTPError`** | `json_read` → `https://polygon.drpc.org`: **HTTP 403, `server: cloudflare`** |
| `geoblock` | **0/20 `HTTPError`** | `json_read` → `https://polymarket.com/api/geoblock`: **HTTP 403, `server: cloudflare`** |
| `accrual` | **0/10 `RuntimeError`** (run ended after ten) | `/rewards/user` 200 ×11 (one page each) but **`/rewards/user/markets` 200 ×536** — `list_user_earnings_and_markets_config` pages ~49 pages per call and `bounded_rows` refuses at 50 → `pagination_budget` |

The owner's browser on the same PC, tunnel down, gets 200 from the geoblock URL; a credential-free urllib probe with
the script's exact headers gets 403 from both hosts. `json_read` (`re1_transport.py`) sends `Accept` and
`Content-Type` only, so the request goes out as `Python-urllib/3.x`, which Cloudflare bot-blocks. The tunnel is not
involved: a tunnel up yields `{"blocked": true}` with HTTP 200, never a 403.

## 2. Changes

1. **`json_read` sends a fixed descriptive `User-Agent`**: `weather-re1-attended/<short commit>` from
   `code_identity()`, beside the existing headers. Prove it from the workstation *before* pushing with a real
   public probe — GET the geoblock URL and POST `eth_blockNumber` to the RPC exactly as `json_read` does, with the old
   headers and the new — and put the status table in the report. These are public, credential-free reads and the
   only network the mission may touch. If the new UA is still 403, try `Mozilla/5.0 (compatible;
   weather-re1-attended/<commit>)` and report; if both fail, stop and report. Do not change RPC provider, add API
   keys, or touch the SDK's own transport.
2. **Preflight probes the two public URLs once, first** (`run_preflight`, before the twenty-read loops): one read
   each; on failure a single message-bearing row `public_read_blocked: <url> -> HTTP <code>` and no read loops run.
   One line instead of forty.
3. **`OwnerVenue.accrual()` stops paging the universe.** Keep `list_user_earnings_for_day` (one page) and
   `get_total_earnings_for_user_for_day` as the accrual. Replace `market_configurations` with the configuration of
   the *selected condition only*: a per-condition SDK method if 0.6.0 has one, else the public
   `/rewards/markets/<condition_id>` read that `Re1PublicBooks` already performs (through `json_read`, so it gets the
   new header). Keep the key name; document the narrower content. **Do not raise the pagination or row budget.**
4. **Trace every reader of `accrual()` / `market_configurations`** — `re1_attended.py` session-end capture,
   `re1_owner_checks.py`, `re1_payout_evidence.py` (`collect_accrual`, the 85b linkage rule) — and make sure none
   still calls the universe paginator. If the 85a collector does, apply the same replacement there; 85b's "do not
   modify" boundary is lifted for that one change only.

Not changed: the 1-in-20 venue transients (recorded in the report, no code), the twenty-read design, all money
controls, selection, sizing, attempt accounting.

## 3. Tests

- `json_read` builds a `Request` carrying the `User-Agent` (monkeypatch `urlopen`, inspect the `Request`).
- Preflight probe failure prints exactly one `FAIL` row with the URL and code, runs no read loop, receipt `FAIL`.
- `accrual()` issues exactly one earnings-for-day call and one per-condition configuration read per invocation
  (fake client counts calls); a fake paginator with 60 pages is never consumed.
- 84d's tests stay green; the parity audit stays green (no selection or sizing code touched).

## 4. What not to do

- Do not touch `scratch\w\reward-test-attended-20260921`; do not run `preflight` or `live`; do not read `.env`.
- No workstation full suite between 09:00 and 19:00 Eastern on 2026-09-22 — focused tests now, the full suite after
  19:00 (84d's suite run may share it).

## 5. Report and adoption

Append a dated 84e section to `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`:
verdict in bold; the probe status table (old UA / new UA × two URLs); the exact header line; the per-condition
configuration source chosen and why; the reader trace (each reader, what it calls now); suite counts; what was NOT
done. Hand back with the tip. The production agent then names the session-1 tip; the owner creates a fresh worktree
at it (the old execution worktree stays as evidence), runs `preflight` with the tunnel down on 2026-09-23 morning,
and starts `live` by 13:59 Eastern on a PASS.
