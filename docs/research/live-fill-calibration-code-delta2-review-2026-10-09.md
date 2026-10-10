# Delta review 2: LFC fix round 2 (N-1, N-2, N-3, N-6, 0g pause) and clarification C at `ab4968afe`

Reviewed range: `origin/claude/live-fill-calibration-code-m-20261009` `c2043fefa..468607b13` (one commit, 5 files:
`lfc_cli.py`, `lfc_constants.py`, `lfc_pilot.py`, `test_lfc_cli.py`, `test_lfc_pilot.py`). Clarification C read at
`ab4968afe` (`origin/claude/live-fill-calibration-clarification-c-20261009`, one commit on top of `33bc652cd`, edits
only that file). Method: `git diff`, `git show`, `git cat-file -p` with `--no-optional-locks`; read-only; no pytest, no
live command, no `.env`/`config/local`, no `data\`. Line numbers are `git show 468607b13:<path>` numbers. The test
changes were read, not run.

## Verdict: PASS

Every claimed fix is real and I found nothing new introduced on the order path, the cancel path or the ledger. The only
remaining items are three wording precisions in clarification C, none of which touches a limit; the owner may sign C
as it stands or after those edits (either way the signed hash is the one at signature time).

- **C ready to sign: yes** (hash `4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054` verified at
  `ab4968afe`).
- N-10: **yes**, back the 0c stopwatch with recorded timestamps, in `session0-attest` only (section 4).

---

## 1. Claimed fixes against the code

| Claim | Where | Real? | Notes |
| --- | --- | --- | --- |
| N-1: every run but 0e requires two distinct tokens each with a venue order id; 0e must have posted nothing | `lfc_cli.py:113-136` (`session0_band_posted`, `session0_runs_passed`) | Yes | `{ledger.legs[k]['token_id'] for k in session['legs'] if ledger.legs[k]['order_id']}` with `len >= 2`; both keys exist on every leg row (`lfc_ledger.py:185-187`, `order_id` initialised `None`, set by `leg_ack` or `leg_adopt` at 191-194). 0e: `not session['legs']`. Gate is the same one `session0_mechanical`, `session0_attest` (851) and `session0_passed` use |
| N-2: `cancels_since_drop` counts each cancel before send; non-zero fails 0g | `lfc_pilot.py:618-623` (`call` override), `756` | Yes | Counted in `PilotSession.call` when `self.dropped` and name is `cancel`/`cancel_all`, before `super().call` sends. Every pre-cleanup cancel goes through `call`: the only `venue.cancel` outside cleanup is `Session.cancel_leg` -> `required('cancel', ...)` -> `call` (`re1_attended.py:505-507`); `retry_read` re-enters `call` per attempt, so each request is counted. The cleanup's `recover('cleanup_cancel')` and `cancel_remaining` (`re1_attended.py:220,564`) use `_recover`, which bypasses `call`, so the safety cancel is not counted, exactly as the comment and C5 say. Pass requires `rows and all terminal and cancels_since_drop == 0` (756); the journal row carries the measured count (751). `self.dropped` is set before `super().__init__` (`428-431`), so the override cannot see a missing attribute |
| N-3: one pre-read attempt per leg, no retries, failure journalled | `lfc_pilot.py:805-816` | Yes | Direct `self.venue.order(oid)` once per `known` leg; any `BaseException` -> `rows[oid] = None` plus `lfc_first_terminal_order_read_unavailable`; then `super().cleanup()` |
| N-6: adoption tolerates only an unterminated last journal line | `lfc_cli.py:649-670` | Yes | `break` only when `number == len(lines) - 1 and not data.endswith(b'\n')`; a terminated unparseable last line or any earlier bad line still returns `None` -> `adoption_journal_unreadable` (725). The caller then falls through to the open-orders source with `[]` (727-729). Test covers both tails |
| preflight `--run 0g` prints the manual-trading pause | `lfc_cli.py:328-329, 381-382`, `lfc_constants.py:78-81` | Yes | Printed by `confirmation` and `run_preflight` only when `profile.run == '0g'`; the text names UI cancels and "PAUSED ... until its result is read" |

### Can N-1 fail a legitimately passing run?

No run that produced its signed object fails it:

- 0a `fixed_end`, 0d, 0g: unreachable without both legs acknowledged (`fixed_end` needs the band; 0d/0g need active
  orders).
- 0b: a foreign order detected during the second leg's `control(force=True)` leaves one acknowledged token and is
  refused, which is the point (S0-3's object is a foreign order while *our band* rests). The runbook consequence is
  already in C5 and in the `lfc_cli` docstring: the owner places the foreign order after both legs rest.
- 0c: both legs acknowledged in the normal case; a lost ack bound by `leg_adopt` carries an `order_id` and counts. A
  kill between the first and second POST (a window of a few seconds, minutes before the owner's planned kill) would
  fail the gate, and that run did not have two orders resting either; the cost is one re-run.
- 0e: `_gate` raises `HoldEnd('l_budget_refused')` from `authorize_post` (`489-494, 541`) before `_pending` is set and
  before `post_intent` records the intent inside the venue's submit hook (`558-567`), so a genuine 0e has
  `session['legs'] == []`. The existing 0e test asserts `not venue.calls and submits == 0`.
- Requotes do not hurt: a replaced leg is a new intent on the same token with its own id; the distinct-token count stays 2.

### Can N-1 let a bad run pass?

Not through anything the ledger can see. The one residual is a 0b where both legs were acknowledged, both were then
requoted away, and the foreign order was detected in the sub-second gap with nothing of ours resting; the ledger has
no timing to exclude it. That is what S0-3's owner judgement by the S0 §5 commands and the journal is for; not a code
requirement.

### Can N-3's no-retry make the safety cancel skip a leg?

No. `rows` is only journalled (`813-814`); `Session.cleanup` cancels every id in `self.active` and then cancel-all,
and consults neither `rows` nor `venue_deadman_observed` (`re1_attended.py:561-572`). The `except BaseException` also
keeps a Ctrl-C arriving during the read from aborting before the first cancel. Worst case added in front of the cancel
is now one transport read timeout per leg (two legs), down from three attempts plus pauses per leg.

### Nothing new introduced

- No change to quote, size, caps, dates, the L formula, the GTD, `cancel_leg`, `Session.cleanup`, the ledger schema or
  the hash chain. `lfc_constants.py` changes are comments plus one new string constant.
- `PilotSession.call` is a pure pass-through outside the 0d/0g post-drop state (`self.dropped` is set only in
  `_session0_flags`, which `PilotProfile` confines to session 0), so RE-1 and counted sessions are unaffected.
- `run_preflight` creates a second `SecretGuard()` for the pause notice; harmless.
- Tests: the N-1 parametrisation covers `none`/`one`/`intent`/`band` per run, including 0e with a band (must fail) and
  the end-to-end 0b before/after-band cases through `finish_session`; the N-2 test forces a post-drop cancel past the
  guard and asserts the run cannot end `venue_deadman_cancelled`; the 0g pass test asserts no counted cancel after
  the drop across the whole run including cleanup, which is consistent with the `_recover` bypass above.

## 2. Clarification C against the code

All four R-2 wording fixes are in and exact: (a) requotes allowed before the drop, never after, ending
`venue_deadman_requote_needed` (code `625-629`); (b) pass = every leg terminal with no cancel request from this
process since the drop, with the measured count named and the manual-trading pause as what excludes an owner cancel
(`743-758`); (c) fee at submit is per submitted leg, both tokens every minute (`550`, `582-587`); (d) the cap is
"≥ 30 s + one control cycle, read at the first checkpoint at or after 30 s, safety cancel within one control cycle
plus read latency" (`760-780`). C5 states the PR §7 layer 2 weakening explicitly and bounds it as required; Q-C2
keeps the permanent halt (`777`). The header cites fix round 2 `468607b13` and the delta review at `287434ca4`, which
exists on `origin/claude/lfc-code-review-20261009` with that file. The three signed LFC files are byte-identical at
`ab4968afe` (section 5).

Remaining wording items, all non-blocking (the code is stricter than or equal to the text in each case):

- **W-1 (C3).** "the journal is unreadable" adopts nothing is still true, but N-6 narrowed what "unreadable" means: a
  journal whose only defect is an unparseable, newline-less last line is treated as readable with that line ignored.
  Add one clause to C3's ambiguity list, e.g. "an unparseable last line without a trailing newline (a crash mid-write)
  is ignored; any other unparseable line makes the journal unreadable". The ids taken from intact lines are still
  verified against the venue order on every field, so no limit moves.
- **W-2 (C5, "0d journal").** The pre-cancel first-terminal read is journalled for 0d **and** 0g (`800`); the
  paragraph says "0d journals". Change to "0d and 0g journal".
- **W-3 (C5, mechanical gate).** "0e must have posted nothing" is checked as "0e recorded no leg intent"
  (`not session['legs']`). Say "recorded no leg intent (it refuses before any intent is persisted)". Stricter in code
  than in text; no exposure.

Ready to sign as is or after these three edits; if edited, re-hash and sign the new hash.

## 3. Hashes

`git cat-file -p <commit>:<path>` piped to a file, SHA-256 of the bytes:

| File | Commit | SHA-256 | Match |
| --- | --- | --- | --- |
| `live-fill-calibration-preregistration-2026-10-09.md` | `82936d68` | `122d08e4ede30706284fce80d1479536e554526945d005d71f86e7ab49c20975` | Yes |
| `live-fill-calibration-panel-clarifications-2026-10-09.md` | `82936d68` | `29d37a47709d4f207ff457a1e48fd6e1d3b8c0c091175bc925e7d3be33c52284` | Yes |
| `live-fill-calibration-session0-spec-2026-10-09.md` | `82936d68` | `9c331b1f63f8a11afa8b83a314a32b165aa70e45d0eeafe6e5195aafefa7c5f2` | Yes |
| `maker-pnl-adverse-selection-clarification-2-2026-10-09.md` | `fb740523` | `7f1e9c454db9984ef60bc878ce457057d62603d5eab33a9c982f34537c892b9e` | Yes |
| `live-fill-calibration-clarification-C-2026-10-09.md` | `ab4968afe` | `4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054` | Yes (as stated) |

The three LFC signed files hash identically at `ab4968afe`. The code branch at `468607b13` does not carry the
`docs/research` files at all (it branched before them), so it cannot have altered them.

## 4. N-10: should the 0c stopwatch be backed by recorded helper timestamps?

**Yes.** S0-2 ≤ 20 s is the one number that gates every unattended session, and today `pass.json` holds only the
owner-typed figure (`lfc_cli.py:852-857`): it is unfalsifiable after the fact. Both ends can be fixed from artefacts on
the same host clock: the kill instant is bounded from below by the last `recorded_at_utc` in the 0c session journal
(the control loop writes at least once per control cycle, ≤ 1 s), and the S0 §5 open-order helper (the wallet-reader
`open-orders` route `wallet-verify` already reads, `642`) can print the UTC time of its first `0` read. Record both in
`pass.json` (`s0_2_kill_bound_utc`, `s0_2_zero_read_utc`) and have `session0_attest` refuse when `s0_2_seconds` is
below their difference minus the helper's poll interval. The derived figure over-estimates by at most one control
cycle, so the direction is conservative. Scope: `lfc_cli` only, no order-path code, landed before `session0-attest`
(not needed for the sub-runs). The owner still types the figure; the timestamps make it checkable, they do not replace
the owner's judgement. If it does not land, the owner-typed method is the signed S0 §5 one and is acceptable; this is
not a reason to delay session 0.

## 5. Runbook notes carried forward (not code)

- The cleanup's cancels are journalled as `cleanup_cancel_request`, so a 0g reader grepping for "cancel_request"
  rows after the test flag will see the safety cancel; read `own_cancel_requests_since_drop` on
  `lfc_venue_deadman_first_terminal` and the position of that row before `lfc_session0_safety_cancel` instead.
- `evidence_complete: false` on a REST-path 0d/0g pass remains expected (N-4), now also stated in C5.
- Pinned worktree for `session0-attest` and session 1 must be at `468607b13` (or later reviewed tip); the sub-runs
  may run on it from the start.
