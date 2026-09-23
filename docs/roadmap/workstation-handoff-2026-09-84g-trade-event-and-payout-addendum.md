# Workstation handoff 2026-09-84g — the first real trade message, and the payout addendum

Written 2026-09-23 by the production agent after RE-1 session 1 (`0a7531baf`, first real reward session). Two bounded
changes on `codex/re1-public-reads-ua-20260922` (PR 85), stacked on `0a7531baf`. Both must land and pass before session 2.

## 1. What happened in session 1 (all UTC 2026-09-23; evidence under `%USERPROFILE%\.weather-re1m-20260921\session-1\`)

- 01:47 two BUY legs posted (YES 0.49, NO 0.48, 20 shares). 42 quoted minutes; `P_many` 0.105, `P_single` 0.125; venue
  site showed 0.12 earned (first evidence the share model tracks the venue). Reward rate 54 -> 53; size/spread unchanged.
- 02:30:05 both orders `LIVE`, `size_matched` 0 (REST order reads). Heartbeats all `ok`.
- **02:30:07.44 `user-stream.jsonl`: `stream_failed`, `exception_type: RuntimeError`** — the venue pushed the trade message
  for our fill (5.6 NO shares at 0.48, partial) and normalization raised. The raw message was not retained.
- Next `control()` -> `OwnerVenue.events()` saw state `FAILED` with a non-network failure type and raised
  `RuntimeError('user_stream_invalid_event')` (`re1_transport.py` ~327); the main loop died (`failure_type:
  RuntimeError`, `evidence_complete: false`), cleanup cancelled both orders (`cleanup_ok: true`), the terminal order
  read showed the match and `reason` was relabelled `fill`. No `fill` journal row exists.
- **Most likely cause (INFERRED from code; confirm from `terminal_trades` in the journal):** a complementary match — a
  taker BUY YES at 0.52 against our maker BUY NO at 0.48. The trade message's top-level `asset_id` is the taker's token
  (YES). `PairStream._normalize_event` passes that token as `token_id`; `normalize_official_user_event`
  (`mm_official_adapter.py`) then keeps only `maker_orders` rows whose `asset_id == observed_token`, finds none (ours is
  NO) and raises "official maker trade event does not identify the pilot maker order". Every fixture trade was
  same-token, so no test could see it.

## 2. Change A — a trade message is a fill, never a crash

1. First, read `session-1/journal.jsonl` `terminal_trades` (and `terminal_order`) to confirm the real trade shape:
   top-level `asset_id`, `trader_side`, `outcome`, and each `maker_orders[]` row's `asset_id`, `outcome`, `side`,
   `maker_address`, `order_id`, `matched_amount`, `price`. Build the test fixture from those field names and the
   complementary-match relationship; **never copy `owner`, API keys or any credential-like field into a fixture or the
   report** (redact them).
2. In `re1_transport.py` (RE-1-owned code only; do not change the Stage 2 normalizer's behaviour for Stage 2 callers),
   make `PairStream` normalize a `trade` message by selecting `maker_orders` rows whose `order_id` is one of the
   session's known order ids **or** whose `maker_address` is the funder and whose `asset_id` is either token of the
   pair — independent of the top-level `asset_id`. A message whose market is ours but whose rows cannot be matched is
   still a fill signal: journal it (guard-cleaned, credential fields removed, plus `raw_event_sha256`) as
   `unmatched_trade_event` and end the session with `HoldEnd('fill')`.
3. In `Session.check_fills` / `OwnerVenue.events`: if the stream fails with a non-network failure **and** the failing
   message was a `trade` for our market, end with `HoldEnd('fill')` after a forced REST order read of both legs
   (journal `fill` with the order rows), not with `RuntimeError`. Any other invalid event still fails closed as now.
4. The stream journal must retain the guard-cleaned failing message (credential fields removed) on `stream_failed`, so
   the next unknown shape is diagnosable.
5. Do not change quoting, sizing, selection, attempt accounting, fill-ends-session, or any money control.

## 3. Change B — implement the owner-approved payout addendum

Implement `docs/research/liquidity-reward-epoch-addendum-2026-09-23.md` exactly, in `re1_evidence.py` `payout_verdict`
and `re1_payout_evidence.py` `link_reward_payment`, printing the **frozen** verdict and the **amended** verdict side by
side (`verdict_frozen`, `verdict_amended`): `BELOW_PAYOUT_MINIMUM` with `ACCRUED_AS_MODELLED / ACCRUED_DILUTED /
ACCRUED_LOW` on `k_accrued`; `NOT_PAID` only on the addendum's conditions; USDC.e (`0x2791…4174`) and pUSD
(`0xC011…2DFB`) credits both eligible under the unchanged exact-amount unique-credit rule; adequacy = at least 95% of
elapsed minutes sampled, cleanup proven, min size and max spread unchanged (rate changes integrated), `SHORT` flag under
180 two-sided minutes (reported, not voided, cannot give `NOT_PAID` alone).

## 4. Tests

- A complementary-match maker trade (top-level `asset_id` = YES, our maker row on NO) ends the session as `fill` with a
  `fill` row, no `RuntimeError`, cleanup proven; same-token match likewise; a partial fill likewise; a trade for another
  market still fails closed; an unmatched trade for our market ends as `fill` with `unmatched_trade_event` journaled.
- The stream journal retains a redacted failing message; a test asserts no credential-named key survives.
- Addendum: one case per verdict row, both assets, the 95% rule, rate change vs size/spread change, `SHORT`, and a
  session-1-shaped input (`P_many` 0.105, accrued 0.12, paid 0) giving frozen `INCONCLUSIVE` / amended
  `BELOW_PAYOUT_MINIMUM` + `ACCRUED_AS_MODELLED` + `SHORT`.
- All RE-1 suites green with `--basetemp` at a short path outside the repo (`C:\pt\...`, create `C:\pt` first).

## 5. Boundaries and report

No `preflight`, `live`, `cancel-only` or `collect-*` run by the agent; no `.env` read; read the session-1 files only
(never write under the campaign root). Do not touch `scratch\w\re1-session1-20260923` or the 09-21 worktree. If the 86b
sampler or the overnight full suite holds the workstation lock, wait for it; do not stop it. Append a dated 84g section to
`docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`: verdict first in bold; the confirmed
trade shape (redacted field names and token relationship); the exact code path that raised; the fix; test counts; the
published tip. Hand back the tip as soon as focused tests pass. The owner then moves the session worktree to that tip,
runs `preflight`, and session 2 starts on a clean reward day (a UTC day with no other RE-1 earnings).
