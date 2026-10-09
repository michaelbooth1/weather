# Delta review: LFC fix round 1 (F-1..F-10, fee rule) and clarification C

Reviewed range: `origin/claude/live-fill-calibration-code-m-20261009` `45000b66b..c2043fefa` (two commits: `a96f951b4`
fix round, `c2043fefa` three-candidate rule). Clarification C read at `33bc652cd` (branch
`claude/live-fill-calibration-clarification-c-20261009`, one file added on top of the prereg tip `c57a6d075`).
Method: code and git diffs only (read-only; no pytest, no worktree, no live command, no `.env`/`config/local`, no
`data\`). Line numbers are `git show c2043fefa:<path>` line numbers. The workstation's "672+109+168 passed, 19/19
mutants killed" is a claim; I read the new tests but ran nothing.

## Verdict: PASS-WITH-REQUIRED-FIXES

Every finding of the first review is genuinely fixed and I found no new defect that can lose money beyond L or leave
an order resting past the GTD. The required fixes are small and none touches the order path: one line in the
mechanical session-0 pass gate (R-1), and four text corrections to clarification C before the owner signs it (R-2).
Session-0 sub-runs 0a..0g may run on `c2043fefa` as is; R-1 must be on the pinned tip before `session0-attest` and
before session 1, because that is the only code it changes.

---

## 1. Finding-by-finding

| Earlier finding | Fix on the branch | Verdict |
| --- | --- | --- |
| F-1 HIGH dead-man unproven; 0d cannot discriminate; gate accepts 0a alone | (a) `session0_passed` = every required sub-run with its accepted reason and `cleanup_ok` + owner attestation bound to the ledger with S0-2 on 0c <= 20 s (`lfc_cli.py:104-156`, `lfc_constants.py:74-78`); (b) 0d journals `lfc_first_terminal_order_read` before the cleanup cancel and `lfc_session0_safety_cancel part_of_proof=false` (`lfc_pilot.py:790-805`); (c) 0c binding via `s0_2_seconds_0c` (`lfc_cli.py:148-150,826-828`). Plus run 0g, the venue-only dead-man (section 2) | Fixed; see N-1 (gate hole) and N-2..N-5 |
| F-2 MED 0b ends `exception` | `PilotSession.check_fills` intercepts `RuntimeError('user_stream_invalid_event')` and `HoldEnd('unknown_user_event')`; `_stream_foreign_check` reads `stream.failed_event` (set by `PairStream._normalize_event`, `re1_transport.py:264-266`; `_clean_event` keeps `event_type`/`asset_id`/`id`/`maker_address`) and forces an account read; ends `foreign_open_order` or the stream's own code (`lfc_pilot.py:624-660`) | Fixed. Verified the only non-transport stream failure raised by `OwnerVenue.events` is `user_stream_invalid_event` (`re1_transport.py:380-390`); transport failures reconnect as before |
| F-3 MED cancelled leg kept in L on a `LIVE` lag read | `Session.cancel_leg` now calls the `cancel_terminal_row` hook after the open-orders poll (`re1_attended.py:197-199,522`); `PilotSession.cancel_terminal_row` re-reads up to 10 x 1 s, fill -> `fill`, never terminal -> `cancel_not_terminal` with the leg left in L and in `active` (`lfc_pilot.py:597-616`) | Fixed; RE-1 behaviour unchanged (hook returns the row) |
| F-4 MED S0-6 needs `OBSERVED` | `positions_inventory_readable`: `OBSERVED`, or `PARTIAL` with `inventory_complete is True`, `unclassified_positions == []`, no `errors`, a token id and finite size on every row; sizes only; `positions_reader_status` reported (`lfc_cli.py:509-534,576-577`) | Fixed and still a real proof: the reader's holdings list is complete-or-refused (`wallet_reader.py:189-207`, 5 x 100 pages else `positions_incomplete` -> `errors` -> `inventory_complete` stays False, `221-229`); `inventory_complete` is cleared only by an unclassified row (`278-279`); `PARTIAL` with those three fields clean can only come from per-row mark/value errors (`311-312`), which S0-6 does not use. Note `errors` is a dict in the reader (`{}`), the test fakes a list; `not positions.get('errors')` handles both |
| F-5 MED lost ack never resolvable | `leg_adopt` event, ledger v0.2 (`lfc_ledger.py:43-44,141-158,186-191,332-342`); `adopt_intents` (`lfc_cli.py:676-731`); `start_gates` refuses `ledger_unacknowledged_intent_needs_reconcile` (`172-174`); `reconcile` exits 1 and does not close the session while any intent is unresolved (`783-790,814-815`) | Fixed; section 3 |
| F-6 MED `reconcile` single trade read, whole history | `reconcile_trades_bounded` 5 x 2 s with an order re-read first (`lfc_cli.py:734-759`); `trades_after` = ledger genesis epoch and a 60 s wall-clock budget on `bounded_rows` (`re1_transport.py:284-297,413-418`; set in `PilotSession.__init__` `lfc_pilot.py:447-450` and `reconcile_ledger` `lfc_cli.py:765-767`). A budget hit raises `read_time_budget`/`pagination_budget` out of `reconcile` (non-zero exit, no mismatch) and, in the session cleanup, into `_recover` -> `evidence_failed`, no mismatch (`lfc_pilot.py:816,828-830`) | Fixed |
| F-7 LOW account read budgeted from session start | `initial=posted_at` (`lfc_pilot.py:691-693`) | Fixed |
| F-8 LOW session 0 does not pin fee 0 | `fee_refusal` in `session0_candidate` (`lfc_pilot.py:227-229`) and the whole fee rule (section 4) | Fixed |
| F-9 LOW tick/min size not re-checked per minute | `minute_extra` compares `(tick_size, min_order_size, fee_rate_bps, neg_risk)` of both tokens with the opening rules every minute (`lfc_pilot.py:148-154,577-587`) | Fixed; N-9 |
| F-10 LOW preflight hides ledger state | `run_preflight` prints `ledger_state` (`lfc_cli.py:359-367`) | Fixed |
| Q-2 >= 3 candidate events | `check_flags` refuses fewer than 3 distinct (`strip().lower()`) slugs (`lfc_cli.py:92-94`, `lfc_constants.py:63`) | Fixed |
| F-11, F-12 | Runbook / hand-check items, not code | Open (checklist) |

## 2. Run 0g, the venue-only dead-man

Mechanism (`lfc_pilot.py:703-773`, `re1_resilience.py:99-104,146-163`): 120 s after both legs rest, `drop_sends()`
then `disable_stale_cleanup()` (refused unless sends are already dropped). The heartbeat thread keeps stepping: the
20 s `main_loop_stalled` watchdog is untouched, only the 8 s `heartbeat_stale` branch is skipped (`step` 102,
`check` 151-152). On every control checkpoint, `check_fills` runs first (WS `order` event or the 10 s REST read of
each active order; any non-LIVE -> `_venue_deadman_observe`), then `extra_checks` -> `_venue_deadman_deadline`.

- **Leak into counted sessions: none.** `disable_stale_cleanup` is reachable only from `_session0_flags` under
  `profile.run == '0g'`; `PilotProfile` requires `session0 == (run is not None)` (`lfc_pilot.py:93`), `check_flags`
  refuses `--run` without `--session0`, a session-0 session is `counted: False`, one session per process, and the
  flag lives on the per-session `HeartbeatLoop` instance. RE-1 never sets it.
- **Hard cap: real but not pre-emptive.** `_venue_deadman_deadline` fires on the first control checkpoint at or
  after 30 s post-drop (`SESSION0_VENUE_WINDOW_SECONDS + SESSION0_VENUE_MARGIN_SECONDS`), reads each active order
  once, and either observes (all terminal) or records a ledger `halt` and ends `venue_deadman_not_observed`. Every
  other exit from `control()` (fixed end, geoblock, stream, fill, stalled loop) also ends through the cleanup. The
  detection margin over the 10 s REST cadence is >= 10 s; the WS event is faster. Time from the cap to the safety
  cancel is one control cycle (<= 1 s) plus read latency; in a degraded network each `required` read may spend its
  30 s transient budget first (N-3).
- **Safety cancel always runs on a Python exit.** `run()`'s `finally: cleanup()` plus `atexit`; signal handlers map
  SIGINT/SIGTERM/SIGBREAK to KeyboardInterrupt. `PilotSession.cleanup` journals the pre-cancel reads and the
  `part_of_proof: false` marker, then `Session.cleanup` cancels each active order, cancel-all, polls to empty, reads
  terminal orders/positions/trades (`re1_attended.py:542-615`). `cancel_all` on an already-empty account returns
  `canceled: []` and an empty `not_canceled`, which `cancel_ack_ids` accepts (`mm_stage2_hold.py:239-245`), so a 0g
  pass gets `cleanup_ok: true`. On a hard kill (taskkill/power loss) nothing runs: the venue dead-man or the GTD
  (end + 60 s, <= 11 min for 0g) is the backstop, exactly the signed PR §7 layer 3, and that is what the run tests.
- **A 0g requote is impossible after the drop** (`cancel_leg` raises `venue_deadman_requote_needed`,
  `lfc_pilot.py:618-622`), so no cancel request of ours can contaminate the window. Before the drop requotes are
  allowed (C5 says otherwise, R-2a); a replaced leg is out of `active` and does not enter the proof rows.
- **Worst-case resting time and size during 0g.** Pre-drop: 120 s under every normal guard (same as 0d). Post-drop,
  venue working: ~10-15 s then terminal. Post-drop, venue not cancelling: 30 s cap + one control cycle + read latency
  (healthy network ~31-33 s; degraded: plus up to 60 s of `required` budgets and up to 20 s of observe re-reads),
  then our cancel. Process dead and venue not cancelling: until GTD, <= 11 min. Size: `min_order_size` <= 20 shares
  per leg (`SESSION0_MAX_SIZE`), two legs at mid -/+ 5 c, band reserve <= 0.98 x size <= 19.6 pUSD, gated by L before
  the post; a fill during the window is a maker fill at the limit and is counted in L by `size_matched x price`.
- **What the pass proves.** "Every leg read terminal with no cancel request from this process since the drop." It
  cannot tell a dead-man cancel from any other external cancel (the owner cancelling in the UI, a venue-side cancel
  for another reason). The S0 manual-trading pause is what closes that gap; C5 should say so (R-2b).

## 3. Lost-ack adoption

`adopt_intents` (`lfc_cli.py:676-731`): for each intent without an order id it needs the persisted
`submit-N.intent.json` whose request matches the ledger leg (token, price, size, BUY); candidates are (1) order ids
from the session journal's `sdk_response` rows for `POST /order` (`_post_order_ids` 626-644; the hook writes
top-level `event/method/path/response`, `re1_transport.py:340-352`, `mm_stage2_hold.py:66-72`) and (2) open orders;
each is read from the venue and must match token, BUY, price, `original_size` and `expiration == request.expiration`
(= session end + 60 s). Anything ambiguous or unreadable adopts nothing for that intent.

- **Foreign (owner) order adopted as ours?** Source (1) is ours by construction. Source (2) requires an exact GTD
  expiration to the second equal to our session end + 60 s; a UI order is GTC (`expiration` 0/absent -> no match).
  Two matches -> `adoption_ambiguous`; one order matching two intents -> both refused. I could not construct a
  false adoption.
- **Double counting?** No. A `leg_adopt` moves the intent to `open` at the same full resting cost; the same
  `reconcile` pass then takes its terminal read (`772-775`) and `traded_shares` attributes trades to the id once.
  `_apply` refuses an id already in `by_order` and an intent already bound (`lfc_ledger.py:186-191`); an adopted leg
  cannot be `ack`ed again (test). `wallet-verify`'s venue_L uses `our_order_ids()`, which now includes it.
- **Conservative failure modes.** A lost ack whose order was cancelled by cleanup `cancel_all` before any journal
  response leaves `adoption_no_matching_order` for good: the intent stays in L at full cost, `reconcile` exits 1,
  `live` refuses. That is the documented manual fallback (C3). N-6 notes one avoidable refusal.

## 4. `fee_rate_bps == 0` fails closed on a missing or unknown field

`fee_refusal` (`lfc_pilot.py:123-131`): any exception reading `rules[token]['fee_rate_bps']` (missing token, missing
key, `None`, bool, non-numeric, NaN via `_decimal`, `reward_quote.py:22-29`) -> `fee_rate_unreadable`; an empty token
list -> `fee_rate_unreadable`; anything != 0 -> `fee_rate_nonzero`. `require_zero_fee` (`134-145`) raises
`fee_rate_unreadable` when the selected row has no `snapshot.rules`/`token_ids` and is applied to both the session-0
and the counted selection in `_selector` (`lfc_cli.py:280-294`), which `run_preflight` and `run_live` both use
(`360,407`). `session0_candidate` refuses the candidate (`227-229`); `authorize_post` ends the session before signing
(`550-554`); `minute_extra` ends it each minute (`583-587`). The rule read is `/fee-rate` `base_fee` per token from
the public snapshot (`mm_stage2_selection.py:243`), the same field RE-1 has used live. Yes: fail-closed.

## 5. Clarification C against the code

| Item | Matches code? | Within signed intent? | Notes |
| --- | --- | --- | --- |
| C1 requote window [4.5, 6.5] c | Yes (`lfc_constants.py:88`) | Yes; S0 silent, PR §6 caps intact | - |
| C2 >= 3 distinct owner-listed events | Yes (`lfc_cli.py:92-94`) | Yes; rules 1-5 unchanged | - |
| C3 intents stay in L; adoption | Yes (section 3) | Yes; L only ever moves from an upper bound to a venue-proven figure | Section 3 |
| C4 5 x 2 s at reconcile, bounded reads | Yes (`lfc_cli.py:734-759`, `re1_transport.py:284-297,413-418`) | Yes; a mismatch is still a permanent halt, only its recording waits for a re-read | A trades-vs-order disagreement that survives 5 re-reads is still recorded; the order re-read cannot hide it (`trade_mismatches` is recomputed) |
| C5 0g, pass gate, attestation, 0c binding | Mostly (`lfc_pilot.py:703-805`, `lfc_cli.py:104-156,820-856`) | **Deliberately weakens PR §7 layer 2 (the 8 s script cleanup) for one uncounted run, for <= 30 s + read latency, at min size; the 20 s watchdog, the GTD and the L gate stay; the fail rule is stricter than S0 §5.** Must be signed as such | Text errors: "a 0g requote is never sent" (pre-drop requotes are allowed and harmless); the cap is "at least 30 s, cancel follows within one control cycle plus read latency", not an exact 30 s; the proof is "no cancel from this process", not "venue dead-man" (R-2) |
| C6 0b label | Yes (`lfc_pilot.py:624-660`) | Yes | "Any other user-stream failure ends with its own code": true for the two codes named; transport failures still reconnect and, if persistent, end `user_stream_stale`/`transport_unavailable` as before |
| C7 PARTIAL rule | Yes (`lfc_cli.py:509-534`) | Yes; sizes are the signed S0-6 object | - |
| C8 fee rule, every rule each minute | Yes except one word | Stricter than PR §6 | At submit only the submitted leg's token is checked (`550`), both tokens each minute; "every token ... at every submit" overstates (R-2c). "A bad fee alone ends with its fee code" is unreachable at the minute check (a fee change is also a rule change -> `market_rules`); harmless |
| C9.1-C9.4 | Yes | Yes | - |

Nothing in C weakens a hard limit except the explicit, bounded 0g exception above, which is the purpose of the run.

**Q-C2 recommendation: halt the campaign permanently, as drafted.** Reasons: (1) the halt is recorded only on a
positive observation, our orders read LIVE at >= 30 s after the drop with every read succeeding; a transport failure
during the window ends the run without a halt (`required` -> `venue_deadman_order_stale`), so a repeat is already
allowed for the non-informative case; (2) a true negative means the v1 heartbeat endpoint does not cancel, which is a
venue fact that a repeat cannot change and that invalidates the signed attendance model, so continuation needs a
re-signed design anyway; (3) "block until a repeat passes" invites a retry-until-pass lottery on the one assumption
the unattended model rests on. Two consequences the re-opening clarification must handle: `session0/pass.json` is
bound to the ledger chain, so a new ledger means the whole of session 0 again; and `Ledger.create` pins the budget to
`LFC.BUDGET_PUSD` with no carry-forward, so the old campaign's `L_filled` must be subtracted from the new budget by a
constant change, not by prose.

## 6. Signed files

Byte-exact (`git cat-file -p <commit>:<path> | sha256sum`):

| File | Commit | SHA-256 | Match |
| --- | --- | --- | --- |
| `docs/research/live-fill-calibration-preregistration-2026-10-09.md` | `82936d68` | `122d08e4ede30706284fce80d1479536e554526945d005d71f86e7ab49c20975` | Yes |
| `docs/research/live-fill-calibration-panel-clarifications-2026-10-09.md` | `82936d68` | `29d37a47709d4f207ff457a1e48fd6e1d3b8c0c091175bc925e7d3be33c52284` | Yes |
| `docs/research/live-fill-calibration-session0-spec-2026-10-09.md` | `82936d68` | `9c331b1f63f8a11afa8b83a314a32b165aa70e45d0eeafe6e5195aafefa7c5f2` | Yes |
| `docs/research/maker-pnl-adverse-selection-clarification-2-2026-10-09.md` | `fb740523` (`codex/maker-pnl-adverse-selection-20261001`) | `7f1e9c454db9984ef60bc878ce457057d62603d5eab33a9c982f34537c892b9e` | Yes |

The three LFC files are byte-identical at the prereg tip `c57a6d075` and at `33bc652cd` (clarification C adds one
file, edits none). Clarification C at `33bc652cd`:
`d8a280c1adcbb6c2feb77d3841bc09aaf7a4b87d8e5d475e0696a346a72c7a41`, as stated.

---

## Findings (new, by severity)

**N-1 MED (required) - The mechanical pass gate does not require that a sub-run posted anything.**
`lfc_cli.py:111-117` (`session0_runs_passed`) checks reason and `cleanup_ok` only. A 0b run can end
`foreign_open_order` before our band is posted (the owner's order event reaches the stream during the first
`control(force=True)` of `submit`, `lfc_pilot.py:624-660`), cleanup then runs with `submits == 0` after
`empty_account_proven` and returns `cleanup_ok: true` (`re1_attended.py:556-560` is skipped, cancel-all on an empty
account acks), so 0b "passes" without S0-3's object, our orders resting. 0a cannot reach `fixed_end` unposted, 0d/0g
need active orders, 0e must be unposted. Fix: in `session0_runs_passed` require `run == '0e' or session['legs']`
(one condition), and assert it in `test_session0_a_wrong_reason_or_unclean_cleanup_does_not_pass_its_run`.
Affects only `session0-attest` and session 1, not the sub-runs.

**N-2 LOW - `cancels_since_drop` is a constant.** `lfc_pilot.py:431,744,749`: initialised to 0, never incremented;
`own_cancel_requests_since_drop` in `lfc_venue_deadman_first_terminal` is therefore by construction, not measured.
The guard that makes it true is `cancel_leg` (`618-622`). Either increment it there before raising, or drop the field
and point the owner at the absence of `cancel_request` rows after `lfc_session0_test_flag` (what the test checks).

**N-3 LOW - Read retries in front of the safety cancel.** `lfc_pilot.py:796-801`: the 0d/0g pre-cancel reads use
`_recover` (3 attempts x read timeout + 0.5 s per leg) before `Session.cleanup` sends the first cancel; in a degraded
network that is tens of seconds added to the one path that must be fastest, at min size. One attempt is enough (the
cleanup's own `terminal_order` reads follow). Related, not new in kind: `cancel_terminal_row` (`600-608`) and
`_venue_deadman_reads` (`727-732`) loop with `_alive()` only, so the sibling leg's fill, geoblock and stream are not
checked for up to 10 x (1 s + 30 s transient budget); L is unchanged during the loop (both legs are counted), so this
is a latency, not an exposure.

**N-4 LOW - A REST-path 0d/0g pass reports `evidence_complete: false`.** `re1_attended.py:417-419` sets
`evidence_failed` before raising `order_no_longer_resting`; the WS path (`404-405`) does not. The gate ignores it;
the owner reading the result line should not. Note it in the runbook or clear the flag in `_venue_deadman_observe`.

**N-5 LOW - The 30 s cap and the "venue" attribution are overstated in C5.** See section 2 and R-2.

**N-6 LOW - A truncated last journal line blocks adoption entirely.** `lfc_cli.py:631-636`: any unparseable line
returns `None` -> `adoption_journal_unreadable`, and the open-orders source is then not consulted. A crash mid-write
(the 0c scenario) leaves exactly that. Tolerate an unparseable final line when the file does not end in `\n`, or fall
through to source (2) with the journal refusal recorded. Conservative as is.

**N-7 LOW - `opening_rules` come from the selection-time snapshot.** `lfc_pilot.py:443-446` uses the table row's
snapshot (up to 30 min old), not the opening or submit snapshot. A legitimate rule change in between is accepted by
`submit` and then ends the session `market_rules` at the first minute. Safe, spurious; use `submit_snapshot` of the
first post or the opening snapshot.

**N-8 LOW - `_intent_request` leaks a `KeyError` for an intent file without `expiration`.** `lfc_cli.py:709`
evaluates `request['expiration']` outside the `_adoption_match` try; our own writer always sets it
(`re1_attended.py:480-481`), so this only matters for a hand-edited file, where failing the whole `reconcile` is
acceptable.

**N-9 LOW - Submit-time fee check is per leg.** `lfc_pilot.py:550`; the minute check covers both tokens. C8 wording
(R-2c).

**N-10 LOW - The 0c measurement is owner-typed.** `--s0-2-seconds` (`lfc_cli.py:77-79`) is the owner's stopwatch
from the kill to the open-order helper reading 0; the code cannot measure it. Same as the earlier review's F-1c;
record the helper's timestamps in the attestation phrase or body so the number is checkable.

No HIGH. No finding changes the signed quote, sizes, caps, dates or L formula.

## Required before signing C / before session0-attest

- **R-1 (code, one line)**: N-1.
- **R-2 (clarification C text)**: (a) C5 "a 0g requote is never sent" -> "after the drop, a requote is never sent;
  the run ends `venue_deadman_requote_needed`"; (b) C5 pass definition -> "every leg read terminal with no cancel
  request from this process since the drop; the S0 manual-trading pause is what excludes an owner cancel"; (c) C8
  "every token ... at every submit" -> "the submitted leg's token at every submit, both tokens every minute"; (d) C5
  cap -> "at least 30 s after the drop, read at the next control checkpoint; the safety cancel follows within one
  control cycle plus read latency".
- Recommended, not required: N-2, N-3 (single attempt), N-4 (runbook line), N-6, N-7.

## Before-session-0 checklist (updated)

1. Code: F-1..F-10 and the fee rule landed at `c2043fefa` and re-reviewed here. R-1 (N-1) landed on the branch and the
   pinned worktree moved to that tip **before `session0-attest`**; sub-runs may start on `c2043fefa`.
2. Clarification C signed by hash after R-2, with the owner's Q-C2 decision recorded (recommendation: halt as
   drafted, with the re-opening consequences in section 5 noted).
3. Workstation: detached worktree at the reviewed tip, clean (`git status --porcelain` empty, untracked included);
   the preflight receipt commit printed equals that tip (F-11); interpreter with the pinned `polymarket` 0.6.0;
   `config/local/wallet_reader_client.json` present in the worktree; wallet-reader server reachable on the LAN; no
   heavy job (the live mutex is the heavy-work mutex); laptop sleep off.
4. P2 runtime import scan re-run on the tip and recorded (expected: `exchange_economics` absent).
5. Owner: manual trading paused from session 0's T-40 min and **not resumed until after 0g's result is read** (a
   manual cancel during 0g would counterfeit the proof); `init-ledger` once; `baseline --label t40` within 90 min of
   start; `preflight --session0 --run 0a --event-slug x3 ...` PASS same UTC day; `.env` topology unchanged.
6. 88a `--extra-conditions` and shadow-scope files supplied; at least three distinct off-panel event slugs; the owner
   checks rules 1-2 by eye before `go <6 hex>`; every candidate reads `fee_rate_bps` 0 in `selection.json`.
7. The S0 verify commands rehearsed once with no orders (open-order helper prints `0`); the toast verified by hand
   (F-12).
8. Run order and gates: 0a, 0b (owner's foreign order placed only after both legs rest, N-1), 0c (kill; stopwatch from
   the kill to the helper reading 0; `reconcile` closes it), 0d, 0e, 0g (read `lfc_venue_deadman_first_terminal`
   `seconds_after_drop` and the absence of `cancel_request` rows after the drop; `evidence_complete=false` from the
   REST path is expected, N-4), 0f optional. After any non-clean end run `reconcile` before the next run.
9. `session0-attest --s0-2-seconds S` only when `verify` shows `session0_runs_missing: []`, S <= 20, and the owner
   has judged S0-1..S0-8 with the S0 §5 commands.
10. Session 1 may not start until `verify` shows `session0_passed: true` on the R-1 tip and clarification C is signed.
