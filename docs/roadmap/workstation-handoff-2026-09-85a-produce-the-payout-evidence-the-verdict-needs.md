# Workstation handoff 2026-09-85a — produce the payout evidence the RE-1 verdict needs

Written 2026-09-21 (evening) by the production agent after accepting 84c (`codex/reward-test-attended-20260921` @
`7e6e1709c`, PR 78). Same mission family as 84a–84c; all their boundaries bind unchanged. Run this in a **separate**
worktree: the execution worktree `scratch\w\reward-test-attended-20260921` stays at `7e6e1709c` for every session and
nothing in this mission may touch it.

## 1. The gap

`payout_verdict` in `re1_evidence.py` can only return `PAID_AS_MODELLED`, `PAID_DILUTED` or `NOT_PAID` when
`collect-payout` is given `--payment-evidence <file>` and `reconcile_incentive_payments` (in `mm_exchange_reports.py`)
accepts it with `valid`, `complete` and a matching scope. Without that file `paid` is `None`, `k` is `None` and the
verdict is `INCONCLUSIVE` — whatever the session showed. **Nothing in the repository produces that file.** The schema
`mm_paid_incentive_evidence` has a consumer, a registry entry and a documentation section
(`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`, "Offline paid-incentive reconciliation"), but no venue reader. The
first session is expected on 2026-09-22 (reward day 2026-09-22 UTC), so the venue's payout for it arrives around
2026-09-23; the file must be producible by then or the whole test answers nothing.

## 2. Work

### 2.1 An owner-run, read-only `collect-evidence` mode

Add `collect-evidence <prediction.json>` to `re1_attended_cli.py`, next to `collect-payout`. It loads credentials the
same way `preflight` does (in-process, `load_owner_credentials` in a read-only mode, secret guard on every output),
never signs an order, never cancels, never heartbeats, and writes exactly one new file
`payout-evidence-<UTC timestamp>.json` beside the prediction with `write_new` (never overwrite). The output must be an
`mm_paid_incentive_evidence` document that `reconcile_incentive_payments` accepts on its own — the test for this mission
is the round trip through the real reconciler, not a hand-written expectation of it.

The three sources, each recorded with the exact `request_scope` keys the reconciler demands, the request and response
`sha256` (use the same journal hook `OwnerVenue` already installs, so the hashes are of the bytes that actually
travelled), truthful `observed_at_utc` and `coverage_through_utc`, and honest `complete` / `pagination_complete` /
`payout_cycle_complete` flags:

1. **accruals** — the SDK 0.6.0 earnings calls `OwnerVenue.accrual` already uses (`list_user_earnings_for_day`,
   `list_user_earnings_and_markets_config`, `get_total_earnings_for_user_for_day`), scoped to the maker address and
   the accrual window `reward_day 00:00Z → +24h`, one row per asset in `ASSETS`. Statuses must map to the reconciler's
   vocabulary (`ESTIMATED` while the day is open, `ACCRUED` after it closes, `COMPLETED_ZERO` when the venue reports a
   closed day with nothing).
2. **distributions** — the venue's record of what it paid this maker for that day. Find the endpoint in the pinned SDK
   first, then in the venue's public API; document which you used and its exact query. **If no address-scoped
   distribution read exists, say so:** the source is recorded `status != OBSERVED`, the reconciler must then refuse
   the file, and the report states the reason. Never synthesize a distribution from an accrual or from a wallet credit.
3. **wallet_credits** — pUSD/USDC.e `Transfer` events *to* the maker for both `ASSETS` over the cash window, from the
   same public RPC `balances` uses (`eth_getLogs`, Transfer topic, `to` = maker, block range resolved from the window
   timestamps by binary search on block timestamps). `pagination_complete` is true only when every block in the range
   was covered, proved by the recorded block bounds; a provider range cap must be walked in chunks, and a chunk that
   fails leaves `complete=false`. Record `chain_id` 137 and the transaction hash as the credit id.

Cash window: `cash_start_utc` = accrual start; `cash_end_utc` = accrual end + 48 hours, or the later of that and the
time the distribution for the day is observed. `payout_cycle_complete` is false until a distribution for that day has
been observed or `cash_end_utc` has passed at collection time. The mode may be re-run; each run writes a new file and
the newest complete one is the one `collect-payout` is given.

### 2.2 The verdict path proves its own inputs

- A test builds the three sources from SDK 0.6.0 models and an `eth_getLogs` reply shaped like the real RPC (hex
  topics, hex data, `blockNumber`), feeds the produced document through `reconcile_incentive_payments` and then
  `payout_verdict`, and asserts `paid` is a number and `k` is computed. The same test with one block chunk missing must
  leave `paid` `None` and the verdict `INCONCLUSIVE` — never `0` and never `NOT_PAID`.
- A test proves the mode performs no writes to the venue: the fake client raises on any method that is not a read.
- `collect-payout` gains nothing except an explicit `payment_evidence_path` and its `sha256` in the printed result, so
  the report can cite the file it judged.
- Extend `test_re1_sdk_shapes.py` with the earnings reply models the reconciler will see, the same way 84c did for
  orders and trades.

### 2.3 What not to do

- Do not alter `re1_attended.py`, `re1_resilience.py`, `re1_owner_checks.py` or any submit/cancel/heartbeat path in
  `re1_transport.py`. Add the reader as a separate module (`re1_payout_evidence.py`) plus the CLI mode.
- Do not run the new mode yourself with the owner's credentials; do not read the root `.env` (variable names only, as
  in 84c). The owner runs `collect-evidence` after the payout arrives, and pastes the printed result.
- Do not check this branch out into the execution worktree. Sessions 1–3 run on `7e6e1709c`; this mission reads the
  session directory under the fixed `campaign_root()` from its own worktree.

## 3. Timing

The workstation heavy mutex and the live session cannot overlap. Finish the full suite tonight or after tomorrow's
session ends (from 19:00 Eastern 2026-09-22); **do not start a full suite between 09:00 and 19:00 Eastern tomorrow.**
Pushing the branch is safe at any time.

## 4. Boundaries and report

All 84a–84c boundaries are unchanged. Branch `codex/re1-payout-evidence-20260921` stacked on `7e6e1709c`, draft PR.
Append a dated 85a section to the same report: verdict first in bold; the endpoint used for each source with its exact
query and the SDK method or URL; the two round-trip tests; the run card for `collect-evidence` and `collect-payout`
with the evidence path; what was NOT done, including any source that could not be observed.
