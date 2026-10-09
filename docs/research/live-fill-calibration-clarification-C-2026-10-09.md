# Live Fill-Calibration Clarification C (DRAFT - UNSIGNED)

**Status: DRAFT - UNSIGNED.** Nothing here is in force until the owner signs it
by hash in a signature record, as for the four signed files. Until then the
signed texts govern, and the code at the tip below must not be used for
session 1.

Owns: the semantic changes the fix round on the live code makes to the
signed live fill-calibration texts. Read when: reviewing or signing that fix
round, or running session 0 on its code.

- Signed texts amended, at the hashes in the
  [signature record](live-fill-calibration-signature-2026-10-09.md):
  - pre-registration `live-fill-calibration-preregistration-2026-10-09.md` (PR);
  - session-0 spec `live-fill-calibration-session0-spec-2026-10-09.md` (S0).
- Neither signed file is edited. This file only adds to them.
- Source of each change: the independent code review
  `docs/research/live-fill-calibration-code-review-2026-10-09.md`, PASS WITH
  REQUIRED FIXES. It is on branch `claude/lfc-code-review-20261009` @ `f88074d56`.
  Its findings are cited as F-n and its section 7 open questions as Q-n.
- Code: branch `claude/live-fill-calibration-code-m-20261009`, fix-round commits
  `a96f951b4` and `c2043fefa` on top of `45000b66b`. Names below are the code's
  (`weather.market.lfc_constants`, `weather.market.lfc_cli`,
  `weather.market.lfc_pilot`).
- Data seen while drafting: none. No 88a, panel or settlement data, and no
  session-0 artefact.

## C1. Session-0 requote window [4.5, 6.5] c (Q-1)

Amends S0 §3, Quote row, which is silent on requotes, and PR §6, Submits row.

- Session 0 requotes a leg when its distance from the mid leaves
  [4.5, 6.5] c, which is d - 0.5 to d + 1.5 around d = 5 c. This is RE-1's
  [1, 3] c shape moved around the session-0 offset (`SESSION0_REQUOTE_WINDOW`).
- Requotes stay enabled, so session 0 also tests:
  - the requote L gate;
  - the cancel read-lag path (C9);
  - `cancel_acknowledgment`.
- PR §6 caps (≤ 10 submits, ≤ 4 requotes) still apply.

## C2. Owner-listed candidate events: at least 3, off-panel only (Q-2)

Amends S0 §2, first sentence.

- "Lists the International Polymarket CLOB markets" now means "evaluates the
  events the owner lists".
- The owner lists them with `--event-slug`, repeatable. The script refuses
  unless at least **3 distinct** event slugs are given
  (`session0_requires_three_candidate_events`).
- Rules 1-5 stay mechanical and unchanged, so every candidate must be off-panel.
- The full table of every listed slug goes to `session0/selection.json` and is
  hashed, as in S0 §2.

## C3. Unacknowledged intents stay in L; adoption at reconcile (F-5)

Amends PR §6, L ledger: "only orders and fills carrying this campaign's script
order IDs count".

**Still in L.** An intent is persisted before its POST. If no order ID came
back, the intent still counts in L at full resting cost
(size × limit price).

**Adoption.** `reconcile` adopts the intent onto the one venue order that
matches all of these:
- token;
- side BUY;
- price;
- `original_size`;
- `expiration` equal to that intent's persisted request, which is
  session end + 60 s.

That order may be resting **or already terminal**, cancelled orders included.

**Where adoption looks:**
1. First, the session journal's raw `sdk_response` rows for `POST /order`.
2. Then, the account's open orders.

**Ledger record.** Adoption is a new ledger event, `leg_adopt`. That needs a
ledger schema bump to `lfc_ledger_v0.2`; v0.1 rows still verify. After
adoption the leg resolves like any acknowledged leg, and its fills count by
that order ID.

**Ambiguity adopts nothing.** Any of these leaves the intent in L:
- the intent file is missing or unusable;
- the journal is unreadable;
- a candidate order cannot be read;
- two orders match;
- one order matches two intents;
- no order matches.

While any intent is unacknowledged:
- the session it belongs to is not closed;
- `reconcile` exits non-zero;
- `live` refuses to start (`ledger_unacknowledged_intent_needs_reconcile`).

**Manual fallback** if adoption keeps refusing: the owner gets a written fix,
plus a further clarification for that case. The campaign does not continue
past an unresolved intent.

## C4. The 5 × 2 s trade re-read also at reconcile (F-6)

Amends PR §6: "any reconciliation mismatch in L" stops the campaign.

**Before a mismatch is recorded.** `reconcile` compares venue trades with the
ledger up to 5 times, 2 s apart, as the session cleanup already does. In each
round it first re-reads `size_matched` from each disagreeing order, because the
order read is authoritative.

**What counts as a mismatch.** Only a disagreement that survives this re-read.
If the re-read itself disagrees with a recorded terminal `size_matched`, that
alone is a mismatch.

**Bounds on the trade read:**
- trades after the ledger genesis only (SDK `after`);
- at most 50 pages and 25 000 rows;
- at most 60 s.

A read that hits a bound fails closed. It ends `reconcile` with an error, never
with a mismatch.

## C5. session0_passed = every required sub-run, 0c binding, new run 0g (F-1)

Amends S0 §3 (Duration), S0 §4 and S0 §5, and PR §9 ("Session 1 may not
start until session 0 has passed").

**New sub-run 0g: venue-only dead-man.** It runs like 0d, with one
difference:
- 0d: heartbeat sends stop 120 s after posting; the main loop stays alive.
- 0g: the same, but the script's own 8 s stale cleanup is also off, so only
  the venue's `/v1/heartbeats` dead-man can cancel.

The 20 s main-loop watchdog stays on. Exposure is bounded four ways:
- size is the market minimum (S0 §3);
- the run lasts at most 10 min;
- there is a hard cap of 30 s after the drop, which is the 15 s venue window
  (10 s + 5 s buffer, PR §7 layer 3) plus a 15 s margin;
- a 0g requote is never sent. It ends the run as
  `venue_deadman_requote_needed`, which does not pass, so 0g is repeated.

**How 0g ends:**
- **Pass:** the first terminal read of every leg is journalled
  (`lfc_venue_deadman_first_terminal`) with no cancel from us since the drop.
  The run ends `venue_deadman_cancelled`.
- **Fail:** at the 30 s cap, any of our orders still rests. The run ends
  `venue_deadman_not_observed`, and the **campaign ledger records a halt**,
  which stops the campaign for good under PR §6. This is stricter than the
  S0 §5 fail rule. Resuming would need a new ledger and a further
  clarification. **Owner decision point:** sign this as written, or ask for the
  softer "blocks session 1 until fixed and repeated".
- **Either way:** the cleanup then cancels as usual. It is journalled as
  `lfc_session0_safety_cancel` with `part_of_proof: false`, so it is never
  proof.

**0d journal.** Before the cleanup cancel, 0d journals the first terminal read
of every leg (`lfc_first_terminal_order_read`). The RE-1 cleanup then journals
the per-leg `cleanup_cancel_response`. The owner can then tell a
venue-cancelled leg from a script-cancelled one.

**Mechanical pass gate.** For each required run, the ledger needs an
uncounted session that ended with an accepted reason and `cleanup_ok` true.
0f stays optional.

| Run | Accepted end reason |
| --- | --- |
| 0a | `fixed_end` |
| 0b | `foreign_open_order` |
| 0c | `reconciled_after_crash` (via `reconcile`) |
| 0d | `heartbeat_stale` or `order_no_longer_resting` |
| 0e | `l_budget_refused` |
| 0g | `venue_deadman_cancelled` |

**Owner attestation.** `lfc_cli session0-attest --s0-2-seconds S` writes
`session0/pass.json` once:
- schema `lfc_session0_pass_v0.1`;
- the owner types `attest session0 <first 6 hex of ledger.previous>`;
- the file binds to that ledger row (`ledger_sequence`,
  `ledger_previous_sha256`);
- it names one passing session per required run, each ended at or before that
  row;
- it records S0-2 as measured on **0c**.

It refuses if any run is missing or if S > 20.

**0c is binding.** S0-2 measured on 0c is the gate for every unattended
session. Session 1 may not start unless the mechanical gate holds and
`pass.json` is valid with S0-2 on 0c ≤ 20 s. If 0c measures above 20 s, the
attendance model must be re-signed. S0-1..S0-8 are still judged by the owner,
with the S0 §5 commands, before attesting.

**Duration.** S0 §3's total grows by ≤ 10 min for 0g.

## C6. 0b end label (F-2)

Amends S0 §4, 0b row, and S0-3.

During 0b the owner's foreign order is on a token outside the session. It can
reach the script in two ways, and both end `foreign_open_order`:
- the 30 s account read;
- first, through a user-stream failure. In that case
  `stream.failed_event` is an order event on a non-session token with our maker
  address, or the forced account read finds a foreign order. The journal
  records `lfc_foreign_open_order` with `source: user_stream`.

Any other user-stream failure ends with its own code
(`user_stream_invalid_event` or `unknown_user_event`), never the generic
`exception`. Such a 0b run does not pass and is repeated.

## C7. S0-6 with a PARTIAL positions read (F-4)

Amends S0 §5, S0-6 row.

S0-6 compares position **sizes only**. A reader `status` of `OBSERVED` passes.
A `PARTIAL` read passes only if all of these hold:
- `inventory_complete` is `true`;
- `unclassified_positions` is `[]`;
- there are no top-level `errors`;
- every row has a token ID and a readable size.

Marks and resolved values are ignored. The reader status is reported
separately (`positions_reader_status`). Anything else fails S0-6.

## C8. fee_rate_bps == 0 (F-8), and every market rule each minute (F-9)

Amends PR §6, Venue terms row, and S0 §2 rule 5.

**Where the fee is checked.** Every token of the selected market must read
`fee_rate_bps` == 0 at each of these points:
- preflight and live selection (both profiles);
- each session-0 candidate (`fee_rate_nonzero` / `fee_rate_unreadable`);
- every submit, before signing (`lfc_fee_rule`, ends the session);
- every minute.

A non-zero or unreadable fee fails closed. PR §6's L formula keeps no fee
term, and this rule is what makes that safe.

**Each minute.** Every market rule of our tokens is compared with the rules
at the opening selection:
- tick size;
- minimum order size;
- fee;
- `neg_risk`.

Any change ends the session `market_rules`, and a bad fee alone ends it with
its fee code. This is stricter than PR §6, which checked only at submit.

## C9. Other semantic changes made by the fix round

1. **Cancel not terminal (F-3; PR §6 Events row and L ledger).**
   - After a cancel, the order is re-read until terminal, up to 10 times about
     1 s apart.
   - Only a terminal read releases resting cost.
   - If the order never reads terminal, the leg stays in L at full resting
     cost and the session ends `cancel_not_terminal` through the cleanup.
2. **Account read freshness (F-7).** The 90 s budget of the account-wide
   open-orders read starts at the first post, not at the session start. This
   is not a semantic change; it is listed for completeness.
3. **Preflight shows the ledger state (F-10).** `preflight` prints
   `open_sessions`, `unresolved_legs`, the L figures and `stop_reason`, which
   is what a live start would refuse on. The owner runs `reconcile` after any
   end that was not clean.
4. **CLI names (S0 §5, last paragraph).**
   - New command: `session0-attest --s0-2-seconds S`.
   - New run: `--run 0g`.
   - `--event-slug` needs ≥ 3 distinct values with `--session0`.
   - `verify` reports `session0_passed`, `session0_runs_missing` and
     `session0_attestation`.
   - `wallet-verify` reports `positions_reader_status`.

## Signature

Owner signs by hash in a separate signature record, as on 2026-10-09.

- Owner: ______________________  Date (UTC): ____________
- Data seen at signature: ______ (expected: none)
