# Live Fill-Calibration Clarification D (DRAFT - UNSIGNED)

**Status: DRAFT - UNSIGNED.** Nothing here is in force until the owner signs it
by hash in a signature record, as for clarification C. Until then the signed
texts and signed clarification C govern.

Owns: the attestation flag added by delta review N-10, three wording
precisions on clarification C, and the scope of the owner's wallet-snapshot
statement. Read when: signing it, attesting session 0, or judging S0-6 or L.

- Amends signed clarification C,
  `live-fill-calibration-clarification-C-2026-10-09.md`, sha256
  `4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054`, signed
  by the owner 2026-10-10T00:28Z
  ([C signature record](live-fill-calibration-clarification-C-signature-2026-10-09.md)).
  Sections touched: C3, C5 ("0d journal", "Mechanical pass gate", "Owner
  attestation") and C9.4.
- Also clarifies, without editing: the session-0 spec (S0) §5, S0-6, and the
  pre-registration (PR) §5 Baselines and §6 L ledger, at the hashes in the
  [signature record](live-fill-calibration-signature-2026-10-09.md).
- No signed file is edited. This file only adds to them.
- Code: the pinned session-0 tip `6c45aaa14` (`weather.market.lfc_cli`,
  `weather.market.lfc_pilot`). Sources: delta review N-6 and N-10 on branch
  `claude/lfc-code-review-20261009`; the delta-2 review (PASS at `468607b13`)
  for D2-D4; the owner's statement relayed 2026-10-09 ~20:35 for D5.
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
- `T` is the UTC time at which the open-order helper first read 0 on the
  passing 0c run. It is ISO 8601 with an explicit `Z` or `+00:00`.
- The script reads the `recorded_at_utc` of the last complete row of that
  0c session's `journal.jsonl` (the last journal row, L0).
- **Timestamp-gap rule:** the attestation refuses unless L0 ≤ T and
  `S ≥ T − L0` (equality passes). The refusal codes are
  `session0_s0_2_timestamps_invalid` (a missing or non-UTC time, or T before
  L0) and `session0_s0_2_below_timestamp_gap`. The existing `S ≤ 20` rule is
  unchanged (`session0_s0_2_above_20_seconds`).
- The prompt prints both times before the owner types the phrase. A refused
  attestation writes nothing.
- `pass.json` keeps schema `lfc_session0_pass_v0.1` and adds
  `s0_2_0c_last_journal_row_utc` and `s0_2_0c_helper_zero_utc`. `verify`
  re-checks both against the 0c journal.

**Why this is conservative.** The journal writes a heartbeat row about every
2 s, so L0 is at or a little before the kill. `T − L0` is therefore at least
the true kill-to-zero time. In practice the owner types
`S = ceil(max(measured seconds, T − L0))`. If that is above 20, S0-2 fails
and 0c is repeated (S0 §5 fail rule).

## D2. Adoption tolerates only an unterminated last journal line (N-6)

Amends C3 "Where adoption looks", item 1, and "Ambiguity adopts nothing".

Add to C3: when `reconcile` reads the session journal's `POST /order`
`sdk_response` rows, the only unreadable line it tolerates is the **last**
line, and only when it is **unterminated** (no final newline): a write cut off
by the crash. That line is ignored. Any other unparseable line makes the
journal unreadable, and the intent stays in L as C3 already says. The same
rule applies to the 0c last-journal-row read in D1.

## D3. "0d journal" reads "0d and 0g journal"

Amends C5, the paragraph headed "**0d journal.**".

The heading and its first sentence read "0d and 0g". Both runs journal the
first terminal read of every leg (`lfc_first_terminal_order_read`, one read
attempt per leg) before the cleanup cancel, and both journal
`lfc_session0_safety_cancel` with `part_of_proof: false`. The rest of the
paragraph is unchanged.

## D4. 0e: "no leg intent recorded"

Amends C5 "Mechanical pass gate", the sentence "0e must have posted nothing".

It reads: "0e must have **no leg intent recorded**". The gate checks that the
0e ledger session has no leg at all, so an intent persisted before a POST
fails 0e even if the POST never happened. S0-5 (no submit at all) is
unchanged.

## D5. Scope of the owner's wallet-snapshot statement (S0-6, L)

Clarifies S0-6, PR §5 Baselines and PR §6 L ledger. It adds no new check.

The owner's statement (relayed 2026-10-09 ~20:35), verbatim: "Just snapshot my
wallet before and after the run, you don't need to know any before or after. I
will not trade during that window."

- **Snapshots:** at T − 24 h and T − 40 min, before and after each session,
  and after settlement. The ledger-bound `baseline --label t24|t40` and the
  owner-private wallet-reader snapshots are both kept. Only their SHA-256
  hashes leave the workstation.
- **No-trade window:** from the first snapshot to the last, the owner places
  no manual order and cancels nothing.
- **What is judged:** L and S0-6 are judged only against this campaign's order
  IDs and the baselines (S0-6: positions outside our tokens unchanged against
  the latest T − 40 min baseline). The owner's activity outside the window is
  never read or reconciled. This narrows nothing in PR §6: L already counts
  only our order IDs.
- **0b exception (owner decision point).** Run 0b needs two owner orders: the
  foreign test order before the pre-part preflight, and again after both legs
  rest. These are the only owner orders allowed inside the window. They are
  far from the mid and are cancelled (by the owner, then by the script's
  account-wide cleanup). If either fills, S0-6 fails and the next start
  refuses `wallet_activity_outside_pilot`. Sign as written, or rule otherwise.
- The 0g manual-trading pause (C5) is unchanged and is stricter: no owner
  order or cancel at all from before 0g until its result is read.

## D6. Open points, not amended here

These are owner decision points recorded for the signature; D changes nothing
about them.

1. **Wallet-reader cache and S0-2.** The reader caches a successful read for
   30 s. The S0 §5 time-to-zero loop (poll every 2 s) therefore cannot show
   zero within 20 s once it has read a non-zero value. The
   [session-0 runbook](live-fill-calibration-session0-runbook-2026-10-09.md)
   uses one fresh read 15 s after the kill or drop, with no read in the 30 s
   before. S0-2 then passes only if that read is 0. Sign this method, or ask for
   another.
2. **Reader topology.** At `6c45aaa14` the reader allows one exact source IP
   (the capture host). By owner decision (2026-10-09 ~20:45) the one reader on
   port 8765 is restarted on code that accepts any LAN caller
   (`claude/wallet-reader-any-lan-20261009`). The pinned client still refuses
   loopback, so its URL is the workstation's LAN IP. The reader's
   30-per-60 s cap and 30 s cache are then shared with the capture host.
3. **After-settlement snapshot.** Session-0 markets end ≥ 7 days after the
   session. Is the after-settlement snapshot needed when no session-0 order
   filled?

## Signature

Owner signs by hash in a separate signature record, as for clarification C.

- Owner: ______________________  Date (UTC): ____________
- Data seen at signature: ______ (expected: none)
