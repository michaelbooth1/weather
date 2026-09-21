# Workstation handoff 2026-09-84c — make the session survive six hours, and prove the account path before money

Host: the 32 GB workstation. Issued by the production operations agent, 2026-09-21. Successor to `2026-09-84b`
(`codex/reward-test-attended-20260921` @ `54b56d21b`). Everything in the 84a and 84b handoffs that this file does not
change still applies, including all of 84a section 0. `2026-09-84c` is a mission label.

## 1. Review verdict on 84b

**The money controls are accepted as built.** The production agent read `re1_attended.py`, `re1_attended_cli.py`,
`re1_transport.py`, `re1_evidence.py` and `re1_rehearsal.py` at `54b56d21b`. The single submit boundary, the signed-order
binding, the post-signing ask re-read, the capital and count limits, the expiry on every order, the cancel on every
exit, the refusal to cancel a stranger's orders before the empty-account proof, the secret guard and the read-only
collector are what the handoff asked for. Do not weaken any of them in this mission.

**The script is not yet fit for its purpose, which is a 360-minute measurement.** Two problems, neither about money:

1. **One transient error anywhere ends the session, and most of them then lock the campaign for good.** In live mode
   the loop makes roughly two authenticated order reads per second for six hours, each with a 0.5-second total timeout
   (`httpx.Timeout(.5)` on every SDK transport, including the order post and the cancels), plus a geoblock read every
   30 seconds and a user-stream health check every second, and the script retries none of them. Any timeout, reset or
   websocket reconnect raises a non-`HoldEnd` exception, which ends the session and sets `evidence_complete=false`;
   `reserve_attempt` then refuses every later session with `prior_attempt_needs_owner_reconciliation`, and no
   reconciliation path exists. Over some 45,000 requests a single half-second stall is close to certain. The expected
   result of running this tip is one short INCONCLUSIVE session and a locked campaign.
2. **No line of the authenticated path has ever executed.** Both rehearsals used `RehearsalVenue`. The first live run
   would be the first execution of: the private `SecureClient._create` bootstrap, the request/response hooks, the new
   `/v1/heartbeats` rotating-id contract (Stage 1 uses a different acknowledgement), the two-token user stream, the
   balance and allowance read, the positions read, and the shape of the real `post_order` reply. `Session.submit`
   accepts only `response.get('ok') is True`, while the Stage 1 adapter accepts `ok` **or** `success` and `orderID`
   **or** `order_id` for the same reply; if the pinned SDK says `success`, every real session would place an order,
   reject its own acknowledgement and cancel at minute zero, three times. The production host does not have the SDK
   installed, so this could not be checked here.

## 2. Work

### 2.1 An owner-run, read-only preflight mode (`preflight`)

Needs the owner's confirmation in your session, because it loads the credentials; it is the same permission the owner
already gave `collect-payout`. It places nothing and consumes no attempt. The agent never runs it.

It does, in order, journaled under the campaign root with the secret guard: proxy and host checks; credential topology;
client bootstrap; user stream to readiness; `open_orders`; `positions` for a condition the public selection currently
ranks first; `balances` in both assets plus allowance; geoblock; `scoring` on an empty list if the SDK allows it;
`accrual` for today; then, **only if open orders are zero**, six heartbeats at the five-second cadence, recording each
acknowledgement verbatim. It repeats each read 20 times and prints a latency table (min, median, p95, max per call) and
a PASS/FAIL line per step with the exception type on failure. Any mutation other than the heartbeat is refused by the
existing transport guard in read-only mode; extend that guard to allow exactly `POST /v1/heartbeats`, or send it
through the existing separate sender, and test that nothing else passes.

### 2.2 Reply shapes checked against the pinned SDK, not against hand-written dictionaries

For `post_order`, `cancel_order`, `cancel_all`, `get_order`, `list_open_orders`, `list_account_trades`, the scoring
call and the heartbeat: a table in the report of each field the controller reads, the SDK 0.6.0 model and field it
comes from (file and line in the installed package), and the test that builds the reply from the **SDK's own model
class** and passes it through `_plain_sdk_value`. Accept the same alternatives the Stage 1 adapter accepts
(`ok`/`success`, `orderID`/`order_id`); reuse its `_value` helper rather than writing a third reading. State the exact
status strings for a resting, cancelled, expired and matched order and where each is handled.

### 2.3 Survive transient failures without loosening a single stop

The rule: **a read may fail; a fact may not go stale.** Each safety fact keeps its own last-success time, reads are
retried inside that budget, and exceeding the budget ends the session with a named `HoldEnd` reason, as now.

| Fact | Cadence | Ends the session when |
| --- | --- | --- |
| Geoblock not blocked | every 30 s | `blocked` is not `false` on any successful read, or no successful read for 45 s (unchanged) |
| Heartbeat acknowledged | every 5 s, **on its own daemon thread** | no acknowledgement for 8 s. The thread also stops sending if the main loop has not ticked for 20 s, so a hung process loses its orders at the venue |
| Our orders resting and unfilled | user stream continuously, plus an order read every 10 s (not every second) | any fill (unchanged); an order not resting; no successful order read for 30 s |
| User stream alive | continuous | down for more than 30 s. While it is down the 10-second order read is the fill detector |
| Market data for the minute row | every 60 s | no successful snapshot for 5 minutes. A missed minute is journaled as missed and earns no credit; end conditions are evaluated on every successful snapshot |
| Scoring and accrual reads (M1, M2) | every 30 min | never; a failure is journaled as a missing sample |

Set SDK timeouts from the preflight table (three times the p95, never under 2 seconds); 0.5 seconds goes. Submits are
still never retried. Cancels may be retried; they are idempotent. The response-journaling hook must never raise: a
body that is not JSON is recorded by length and SHA-256. Expected transport failures end the session as a named
`HoldEnd`, not as `exception`.

### 2.4 What counts as a session, and how a blocked campaign is reopened

- An attempt that made **zero submits** is not one of the three sessions. Keep its marker and journal; allow at most
  six attempt markers in total so a fault cannot loop.
- After an attempt that submitted, the next session is refused only when safety is unproven: cleanup not proven, a fill
  seen, or a submit without a known order id. Incomplete evidence alone makes that session INCONCLUSIVE in the
  collector (unchanged) and does not block the next one.
- Add an owner-only `reconcile` mode for the blocked cases: it reads open orders, positions in that attempt's two
  tokens and the attempt's order ids, prints them, and the owner types a displayed phrase. It writes an immutable
  reconciliation receipt beside the attempt; `reserve_attempt` accepts a blocked attempt only with that receipt and
  only if the account shows zero open orders at that moment. A filled session still counts as one of the three, and the
  inventory is still held to settlement.

### 2.5 Tests and rehearsal

Fault-injection tests on a fake clock: a timeout on each read type at each point in the loop is survived inside the
budget and ends the session beyond it, always with zero open orders; the heartbeat thread stops when the main loop
stalls; the hook survives a non-JSON body; a zero-submit attempt does not consume a session; `reconcile` unblocks only
with a receipt and an empty account. One accelerated 360-minute rehearsal with a venue that fails 2% of reads at random
(seeded) must reach the fixed end. Focused tests, then the full suite once on the final tip through
`scripts/ops/workstation_heavy.ps1`. Mission `2026-09-83d` yields the mutex to this mission.

## 3. Order of events for the owner

1. Owner runs `preflight` (target: the morning of 2026-09-22). You read the journal and fix what it shows.
2. Owner runs `live` no earlier than a clean preflight on the final tip. The 13:00 Eastern start stands if that is
   achieved by then; the session must still end before 00:00Z, so the last possible start is 13:59 Eastern. Otherwise
   the first session moves to 2026-09-23. **Do not shorten any check to make the time.**

## 4. Boundaries and report

All 84a and 84b boundaries are unchanged. No limit in 84a section 3 is widened; the three-session cap and the
2026-09-30 end stand. Append a dated 84c section to the same report: verdict first in bold; the reply-shape table; the
budget table as implemented with the test for each row; the fault-injection rehearsal hash; the updated run card with
`preflight` and `reconcile`; after the owner's preflight, its latency table and every FAIL line; what was NOT done.
