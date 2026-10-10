# Live Fill-Calibration Clarification D (DRAFT - UNSIGNED)

**Status: DRAFT - UNSIGNED.** Nothing here is in force until the owner signs it
by hash in a signature record, as for clarification C. Until then the signed
texts and signed clarification C govern.

Owns: the attestation flag added by delta review N-10, the wording precisions
on clarification C, the replacement of C8 (maker-fee class rule), the S0 §5
open-order read, the scope of the owner's wallet-snapshot statement and the
owner approvals of 2026-10-09 evening. Read when: signing it, attesting
session 0, or judging S0-2, S0-6, C8 or L.

- Amends signed clarification C,
  `live-fill-calibration-clarification-C-2026-10-09.md`, sha256
  `4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054`, signed
  by the owner 2026-10-10T00:28Z
  ([C signature record](live-fill-calibration-clarification-C-signature-2026-10-09.md)).
  Sections touched: C3, C5 ("0d journal", "Mechanical pass gate", "Owner
  attestation"), C8 (replaced) and C9.4.
- Also clarifies, without editing: the session-0 spec (S0) §1, §5, S0-2 and
  S0-6, and the pre-registration (PR) §5 Baselines and §6 L ledger, at the
  hashes in the [signature record](live-fill-calibration-signature-2026-10-09.md).
- No signed file is edited. This file only adds to them.
- **Code: the pinned session-0 tip `acd052a2d`**
  (`acd052a2d0c38e701e951f7e5efd53d0a7e11781`, branch
  `claude/lfc-pinned-ext-20261009`; `weather.market.lfc_cli`,
  `weather.market.lfc_pilot`, `weather.market.lfc_fees`,
  `weather.market.wallet_reader_client`). It replaces `6c45aaa14`. Every
  file:line below is at `acd052a2d`.
- **D is signed only after the Fable delta-3 review over
  `468607b13..acd052a2d`** passes.
- Sources: delta review N-6 and N-10 and the delta-2 review (PASS at
  `468607b13`; W-2, W-3) on branch `claude/lfc-code-review-20261009`; the
  owner's statement relayed 2026-10-09 ~20:35 for D5; the owner approvals of
  2026-10-09 evening for D9.
- Data seen while drafting: none. No 88a, panel or settlement data, and no
  session-0 artefact.

## D1. Attestation needs the 0c helper-zero time (N-10)

Amends C5 "Owner attestation" and C9.4 "New command". Owner-approved
2026-10-09 (N-10); this records the flag the C signature record deferred to D.

The command is now:

```powershell
& $python -m weather.market.lfc_cli session0-attest --s0-2-seconds S --s0-2-helper-zero-utc T
```

- Both flags are required.
- `T` (`--s0-2-helper-zero-utc`) is the UTC time at which the open-order
  helper first read 0 on the passing 0c run. It is ISO 8601 with an explicit
  `Z` or `+00:00`; anything else is refused.
- The script reads `recorded_at_utc` of the last complete row of that 0c
  session's `journal.jsonl` (`session0_0c_last_journal_utc`,
  `lfc_cli.py:176`). This is L0.
- **Timestamp-gap rule, as implemented** (`session0_s0_2_timestamps`,
  `lfc_cli.py:198-207`):
  - `session0_s0_2_timestamps_invalid` when either time is missing, unparsable
    or not UTC, or when T is before L0;
  - otherwise `session0_s0_2_below_timestamp_gap` when `S < T − L0`, compared
    exactly to the microsecond (`lfc_cli.py:205`). So it passes only when
    `S ≥ T − L0`; equality passes.
  - The existing `S ≤ 20` rule is unchanged (`session0_s0_2_above_20_seconds`).
- This is stricter than the delta-2 review's "minus the helper's poll
  interval" (S may not fall below the gap at all). The stricter rule is kept.
- The prompt prints both times before the owner types the phrase. A refused
  attestation writes nothing.
- `pass.json` keeps schema `lfc_session0_pass_v0.1`. Its S0-2 fields are
  `s0_2_seconds_0c`, `s0_2_0c_last_journal_row_utc` and
  `s0_2_0c_helper_zero_utc` (`lfc_cli.py:996-997`). `verify` re-checks the gap
  rule from those fields and that `s0_2_0c_last_journal_row_utc` still equals
  the 0c journal's last row (`lfc_cli.py:234-237`).

**Why this is conservative: the true write cadence.** The kill falls after L0,
so `T − L0` is at least the true kill-to-zero time. How far L0 can sit before
the kill depends on what writes journal rows:

- **Heartbeat thread** (`re1_resilience.HeartbeatLoop.step`): each send
  journals a `heartbeat_request` row and then a `heartbeat_response` row
  (`re1_resilience.py:110`, `:112`). After an acknowledged send the next send
  is due 2 s later (`re1_resilience.py:124`); after a failed one, 1 s later
  (`:108`). The thread wakes every 0.1 s (`:138`). `lfc_pilot.py:18` states the
  same 2 s figure in its docstring. In 0c the sends run until the kill.
- **Main loop** (`re1_attended.Session.run`): it sleeps at most 1 s per cycle
  (`re1_attended.py:696`) but writes **no** row per cycle. Its periodic rows are
  `market_snapshot` and `minute`, once per 60 s (`re1_attended.py:650`, `:659`,
  `:679`). Other rows (geoblock reads every 30 s, user events, fills) are
  irregular.

So with heartbeats running, L0 is at most about 2 s plus one send's latency
before the kill. (The delta-2 review's "at least once per control cycle,
≤ 1 s" does not hold: the main loop journals nothing per cycle. The heartbeat
rows give the bound instead.) The owner types
`S = ceil(max(measured seconds, T − L0))`. If that is above 20, S0-2 fails and
0c is repeated (S0 §5 fail rule).

## D2. Adoption tolerates only an unterminated last journal line (N-6)

Amends C3 "Where adoption looks", item 1, and "Ambiguity adopts nothing".

Add to C3: when `reconcile` reads the session journal's `POST /order`
`sdk_response` rows, the only unreadable line it tolerates is the **last**
line, and only when it is **unterminated** (no final newline): a write cut off
by the crash. That line is ignored. Any other unparseable line makes the
journal unreadable, and the intent stays in L as C3 already says. The same
rule applies to the 0c last-journal-row read in D1.

## D3. "0d journal" reads "0d and 0g journal" (W-2)

Amends C5, the paragraph headed "**0d journal.**".

The heading and its first sentence read "0d and 0g". Both runs journal the
first terminal read of every leg (`lfc_first_terminal_order_read`, one read
attempt per leg) before the cleanup cancel, and both journal
`lfc_session0_safety_cancel` with `part_of_proof: false`. The rest of the
paragraph is unchanged.

## D4. 0e: "recorded no leg intent" (W-3)

Amends C5 "Mechanical pass gate", the sentence "0e must have posted nothing".

It reads: "0e must have **recorded no leg intent (it refuses before any intent
is persisted)**". The gate checks that the 0e ledger session has no leg at all
(`not session['legs']`, `lfc_cli.py:154`), so an intent persisted before a
POST fails 0e even if the POST never happened. S0-5 (no submit at all) is
unchanged.

## D5. Scope of the owner's wallet-snapshot statement (S0-6, L)

Clarifies S0-6, PR §5 Baselines and PR §6 L ledger. It adds no new check.

The owner's statement (relayed 2026-10-09 ~20:35), verbatim: "Just snapshot my
wallet before and after the run, you don't need to know any before or after. I
will not trade during that window."

- **Snapshots:** at T − 24 h and T − 40 min, and before and after each session.
  An after-settlement snapshot is taken only if a session-0 order filled (D9).
  The ledger-bound `baseline --label t24|t40` and the owner-private
  wallet-reader snapshots are both kept. Only their SHA-256 hashes leave the
  workstation.
- **No-trade window:** from the first snapshot to the last, the owner places
  no manual order and cancels nothing, except the two 0b test orders (D9).
- **What is judged:** L and S0-6 are judged only against this campaign's order
  IDs and the baselines (S0-6: positions outside our tokens unchanged against
  the latest T − 40 min baseline). The owner's activity outside the window is
  never read or reconciled. This narrows nothing in PR §6: L already counts
  only our order IDs.
- **0b orders.** Run 0b needs two owner orders: the foreign test order before
  the pre-part preflight, and again after both legs rest. They are on a market
  outside the session (C6), far from the mid, and are cancelled (by the owner,
  then by the script's account-wide cleanup). If either fills, S0-6 fails and
  the next start refuses `wallet_activity_outside_pilot`.
- The 0g manual-trading pause (C5) is unchanged and is stricter: no owner
  order or cancel at all from before 0g until its result is read.

## D6. S0 §5 open-order reads: the fresh endpoint, every 3 s

Clarifies S0 §5 (the time-to-zero helper) and S0-2. Replaces the earlier draft's
open point D6.1 (one fresh read 15 s after the kill).

1. **Method.** The S0 §5 time-to-zero loop reads the wallet reader's no-cache
   endpoint `GET /open-orders?fresh=1` through
   `weather.market.wallet_reader_client.open_order_count(fresh=True)` (the
   default), **every 3 s**, from the kill (0c) or the drop (0d), until it reads
   0 or 21 s have passed. Each fresh read always queries the venue (it bypasses
   the reader's 30 s success cache and 10 s failure cache) and stores its
   result in the cache. T is the UTC time the read that returned 0 completed.
   The 3 s interval only makes the measured time longer, never shorter.
2. **Rate cap.** Every fresh read (each page) counts in the reader's single
   30-per-60-s upstream cap, which is shared with the capture host's 5-minute
   wallet journal reads. The 20 s loop makes at most 8 fresh reads (one page
   each while the account has few orders), so it stays within the cap. Over the
   cap a read is refused (`503 read_unavailable`) and the helper prints `ERR`;
   the loop does not count `ERR` as 0.
3. **Reader topology.** The pinned tip carries the any-LAN reader change
   (`b818d187c`, cherry-picked as `388043de5`): `serve` admits any RFC1918 or
   loopback IPv4 caller, and the client accepts an RFC1918 or loopback URL
   host. The bind stays a literal RFC1918 address, so the workstation's client
   URL is `http://<workstation LAN IP>:8765`. By owner decision (2026-10-09
   ~20:45) the one reader on port 8765 is restarted on that code; its cap and
   cache are shared with the capture host.

## D7. C8 replaced: the maker-fee class rule

Replaces C8. Implemented in `weather.market.lfc_fees` (`classify`,
`maker_fee_refusal`) and called from `lfc_pilot` and `lfc_cli`.

The CLOB V2 order signed by polymarket-client 0.6.0 has no fee field; fees are
charged at match time. On weather markets Gamma `makerBaseFee`/`takerBaseFee`,
CLOB `mbf`/`tbf` and `/fee-rate` `base_fee` read 1000. **They are NOT the maker
charge**: they are recorded only, never compared to 0. At selection, before
every submit and every minute, the selected market must be exactly one of:

- **WEATHER_TAKER_ONLY** (maker fee 0), proven by Gamma `feesEnabled` true,
  `feeType` == `"weather_fees"`, `feeSchedule.takerOnly` true and CLOB
  `/clob-markets` `fd.to` true (agreeing), with
  `base_fee` == `takerBaseFee` == `tbf` and `makerBaseFee` == `mbf`;
- **FEE_FREE**: `feesEnabled` false; no `feeType`, `feeSchedule` or `fd`; base
  fields absent or 0; and `base_fee` 0.

The schedule rate (0.05), exponent and `rebateRate` (25%) are recorded and
cross-checked Gamma against CLOB, never required. Any non-zero builder fee
field on the market, a builder or fee argument on the order, or a signed
builder other than bytes32 zero refuses. Session 0 and every open market of its
event must be FEE_FREE. Anything else, or any change of class or fee field
mid-session, ends the session fail-closed. Codes: `fee_fields_unreadable`,
`fee_fields_inconsistent`, `fee_schedule_unknown`, `maker_fee_nonzero`,
`builder_fee_nonzero`, `session0_not_fee_free`,
`session0_event_not_fee_free`, `fee_class_changed`; on the signed order
`order_builder_nonzero` and `order_fee_field_present`. Any other mid-session
fee-field change ends as `market_rules`.

## D8. Known limit: session 0 does not exercise neg-risk signing

The session-0 picks are plain binary markets (`neg_risk: false`), not neg-risk
markets. Session 0 therefore exercises the CTF-exchange signing path only, not
the neg-risk exchange path. Session 1 is the first neg-risk signing, under the
existing hard limits (PR §6 and RE-1, unchanged).

## D9. Owner scope: approvals of 2026-10-09 evening

Relayed by master-agent; recorded here for the signature.

1. "I hold no positions, 10-12 confirmed." Session 0 runs on UTC
   **2026-10-12**, starting about **15:00Z**.
2. **No after-settlement snapshot if nothing filled.** If no session-0 order
   filled, the end-of-session snapshot suffices (answers the earlier open point
   on after-settlement snapshots).
3. **The two 0b test orders** (the foreign order on a market outside the
   session, per C6) may be placed inside the no-trade window as part of the
   test.

## D10. The session-0 deadline is enforced in code

Implements S0 §1 ("before 2026-10-15T00:00Z"); adds no rule.
`lfc_cli live` and `lfc_cli preflight` with `--session0` refuse with
`session0_deadline_passed` when the CLI clock is at or after
`SESSION0_DEADLINE_UTC` = 2026-10-15T00:00:00Z (`lfc_constants.py:65`;
`session0_deadline_refusal`, `lfc_cli.py:122-127`, called at `:497` and
`:530`). The check runs before the campaign root, the live mutex or any
credential is touched. Counted runs are unaffected.

## Signature

Owner signs by hash in a separate signature record, as for clarification C,
after the Fable delta-3 review over `468607b13..acd052a2d`.

- Owner: ______________________  Date (UTC): ____________
- Data seen at signature: ______ (expected: none)
