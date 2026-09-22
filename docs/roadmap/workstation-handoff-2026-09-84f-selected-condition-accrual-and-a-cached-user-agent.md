# Workstation handoff 2026-09-84f — selected-condition accrual and a cached User-Agent

Written 2026-09-22 by the production agent after verifying the 84e handback (`codex/re1-public-reads-ua-20260922`
@ `c190fb10b`, PR 85, stacked on `7010a0b58`). 84e delivered two of its four items: `json_read` now sends
`User-Agent: weather-re1-attended/<nine commit characters>` (real probes 403 -> 200 on both public URLs), and
`preflight` probes both URLs once before any credential load and prints a single `public_read_blocked` row. Both
are correct and stay. **The accrual paginator change (84e §2.3–2.4) did not land: `OwnerVenue.accrual()` still
pages the whole reward-market universe, so the next owner `preflight` on `c190fb10b` fails the accrual reads
exactly as the 16:33Z run did, and `collect-evidence` on 09-26 fails the same way.** This mission finishes that
work on the same branch and removes one hazard the 84e header introduced. Session 1 stays 2026-09-23: the owner
preflights tomorrow morning on the tip this mission publishes.

## 1. What is still wrong on `c190fb10b`

1. `re1_transport.py` `OwnerVenue.accrual(day)` calls `list_user_earnings_and_markets_config(date=day)` through
   `bounded_rows`. The venue answers `/rewards/user/markets` for the whole reward-market universe (about 49 pages
   per call in the owner's 16:33Z run — 536 responses over 11 calls), so `bounded_rows` raises `pagination_budget`
   at 50 cursors every time. `preflight` measures `accrual` 20 times and needs all 20 to pass; `live` samples it
   every 30 minutes and at close (`re1_attended.py`, `sample('accrual')` / `sample('final_accrual')`, each miss
   sets `evidence_failed`); `collect-payout` (`re1_attended_cli.py`) reads it once.
2. `re1_payout_evidence.py` `collect_accruals` does the same through `read_pages` with the same 50-page budget;
   `require` turns that into an INVALID collection, so the 85b verdict path can never run.
3. `json_read` now calls `code_identity()` on **every** request. That spawns two git subprocesses per public read
   (about 100 ms here; it lands inside the `balances` and `geoblock` latency figures) and, worse, raises
   `preflight_requires_clean_tip` for any untracked file that appears in the worktree during a six-hour `live`
   session — one stray file would fail every geoblock and balance read from then on. The header value is right;
   compute it once.

## 2. Changes — three, all bounded, on the same branch

1. **Selected-condition configuration instead of the universe** (`re1_transport.py`). `accrual()` keeps `rows`
   (`list_user_earnings_for_day`, 11 pages of `/rewards/user` today, fine), `total_earnings` and `percentages`
   unchanged, and keeps the key name `market_configurations`, but fills it from one public read of
   `https://clob.polymarket.com/rewards/markets/<self.condition>` through `json_read` — the exact endpoint and
   shape `mm_stage2_selection.py` `reward()` already validates (`data` list of at most one row, `count == len(data)`,
   `next_cursor == 'LTE='`, integer `limit` in 1..500). Apply the same shape checks and raise
   `RuntimeError('condition_config_unreadable')` otherwise; the value is the `data` list (zero or one row). The
   condition's reward configuration is a public fact (rate, min size, max spread); the user-scoped breakdown that
   `/rewards/user/markets` adds is already in `rows`. Do not raise the page or row budgets, do not add a market
   filter to the SDK call, do not change RPC providers or add keys. `self.condition` is always set where `accrual`
   is reached (preflight line 129, live, `collect-payout` line 150); if it is `None`, raise
   `RuntimeError('condition_required')` rather than paging anything.
2. **Same replacement in `collect_accruals`** (`re1_payout_evidence.py`): read the selected condition's
   configuration once through the venue's `json_read` path, journal it under `/rewards/markets/<condition>` so
   `last_response_hash` still binds it, keep `retained['market_configurations']` as the list, and do not touch
   `read_pages`, the `rows` read, totals, activity or wallet reads. Trace `link_reward_payment` and the reconciler
   to confirm neither consumes `market_configurations`; say so in the report with the line numbers. 85b's
   do-not-modify boundary is lifted for this one function only.
3. **Header computed once** (`re1_transport.py`): a module-level cached helper (`functools.lru_cache` or an
   explicit `_USER_AGENT` filled on first use) that calls `code_identity()` exactly once per process; `json_read`
   uses it. The value and format stay `weather-re1-attended/<first nine of HEAD>`; the clean-tree requirement is
   still enforced by that first call (which in every mode happens at the `proxy_host_tip` / identity step).

## 3. Tests

- `tests/market/test_re1_transport.py`: an `accrual` fixture whose fake client fails the test if
  `list_user_earnings_and_markets_config` is ever called; asserts one `json_read` to
  `https://clob.polymarket.com/rewards/markets/<condition>` and that `market_configurations` is that row list;
  shape-check cases (two rows, `next_cursor` not `LTE=`, `count` mismatch) raise `condition_config_unreadable`;
  `condition=None` raises `condition_required`. A test that ten `json_read` calls invoke `code_identity` once.
- `tests/market/test_re1_payout_evidence.py`: drop `list_user_earnings_and_markets_config` from the allowed
  read set at line 60 so the universe paginator becomes a failing call; add the per-condition read to the mock
  transport and assert the retained configuration and its journal hash.
- `tests/market/test_re1_owner_checks.py`: the preflight fixture's `accrual` stays a fake; confirm the 20/20
  accrual reads still pass and the parity audit is untouched.
- Existing suites green; `test_re1_attended_parity_audit.py` unchanged.

## 4. What not to do

- No change to selection, sizing, attempt accounting, `re1_attended.py`, `re1_resilience.py`,
  `re1_public_books.py`, `bounded_rows`, `read_pages`, the reconciler or the 85b rule.
- No checkout into `scratch\w\reward-test-attended-20260921`; no `preflight` or `live` run by an agent; no root
  `.env` read (variable names only); no secret printed.
- No workstation full suite before 19:00 Eastern today. After 19:00, run **one** full suite on the final 84f tip
  through `scripts/ops/workstation_heavy.ps1`; because the branch is stacked, that single run qualifies 84d, 84e and
  84f together, and the separate 19:05 run on `7010a0b58` is no longer needed.

## 5. Boundaries and report

Same branch `codex/re1-public-reads-ua-20260922`, new commits on `c190fb10b`, PR 85 stays. Append a dated 84f
section to `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`: verdict first in
bold; the exact per-condition URL and the shape checks; the reader trace with line numbers; the `code_identity`
call count proof; focused and full-suite counts; the published tip; what was NOT done. Hand back the tip the moment
the focused tests pass, before the full suite, so the production agent can name the session tip tonight; report
the full-suite result separately when it finishes.

The production agent then names the session-1 tip; the owner makes a fresh worktree at it (the 09-21 execution
worktree stays untouched as evidence), runs `preflight` with the tunnel down on 2026-09-23 morning, retries every
quarter hour on `NO QUALIFYING BAND`, and starts `live` by 13:59 Eastern on a PASS.
