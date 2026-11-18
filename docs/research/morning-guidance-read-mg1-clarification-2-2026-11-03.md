# MG-1 pre-registration — Clarification 2 (2026-11-03): countable dates, market-day mask and look inputs

Status: **master ruling, not an owner decision**, except A1, A5 and A12, which are **owner questions, open**. This
is a separate dated amendment file, as [the MG-1 pre-registration](morning-guidance-read-mg1-preregistration-2026-10-04.md)
requires. That file's signed bytes (SHA-256 `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665`,
DECISION_LOG row 2026-10-04) and [Clarification 1](morning-guidance-read-mg1-clarification-1-2026-10-16.md) are
unchanged. Its B-1 counterpart is
[B-1 Clarification 5](mg1-countability-2026-11-03/b1-clarification-5-mg1-countability-and-b-dates-2026-11-03.md).

## Sources

- **R11**: master ruling of 2026-11-01. Ruling items (1)-(7) and the master actions are quoted from the WS copy of
  master's rulings file, sha256 `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`, lines 9-15 and
  45-62.
- **A and T rulings**: master's 2026-11-03 sitting. The host file is
  `C:\tmp\agent-kit\rulings-20261103-mg1-b.md`, sha256
  `28c4f298c9d128189468ab62562ebb79e055a6c42328315c8182178642b01906`. The text below is quoted from the
  coordinator's verbatim copy of master's condensed messages.
- **Question text**: A1-A14 are the questions in `docs/research/mg1-look-scoring-2026-10-31/scoring-note.md` §3
  (lines 61-74), on `claude/mg1-look-scoring-20261031` @ `1179f990d2c350a5c6cc81755c4a77252e344c83`, file sha256
  `434c45cf575e1645422a3f45d5ba98195b2bfd32af0033db3b1505ff374d7c01`.
- **Code packet**: the code citations master read are in
  `docs/research/mg1-look-packet-2026-11-03/PACKET.md` on `claude/mg1-look-packet-20261103` @
  `c0f11fdd58ef6d5477192a3a701dee9ace2170bf`, sha256
  `bcc6b1de5485c681d5e5a7cadacbe3e29b411703a8eccf60e6e26b206a7ecd7c`.

**Motivation:** the look code (`weather.calibration.mg1_look`) needs fixed answers on countability, the scored
population and the label input before it is re-registered.

**When written:** before any MG-1 outcome is read. No label, price, outcome, settlement or ledger value was read
to write this file.

## 1. R11 ruling items (1)-(7), verbatim

> R11 MASTER RULING (applies owner 10-16 option 2 BOUND, DL:227, and Clarification 1 §4; not an owner decision).
> (1) Date rule A3: local date D counts toward MG-1's 45 iff at least one support market-day (support per A1) has the ledger's promotion_countable true; §4 scores only countable market-days. Basis: §4:194 presumes counted dates can hold non-countable market-days; EF §0d counted 08-07 at 11/12. The all-labels ops flag (daily_refresh_settled_day.py:267) is fleet-wide and not MG-1's population. Disclosed: master saw 2026-10-30 denver SOURCE_DISAGREEMENT (10-31 18:05) first.
> (2) The scoring addition carries a per-market mask (dropped before the join) and refuses before the join when a countable market-day has no layout rows; as coded, a missing label ABORTS and spends the look.
> (3) Counts-only host tool. P1 11-14 (panel closed), P2 11-27: date status only. P3, at the first admitted morning at least two days after the 45th date, writes the final list from the ledger as it then stands; pending counts as non-countable (DL:226). P0: whole-date evidence before P1 (evening-fix receipt) acts at once.
> (4) Extend on any non-countable or pending date, never shorten: one commit covering MG1_LAST, the reservation status line and rows 25/26/39, and the DLv2 row.
> (5) MG-1 Clarification 2 / B-1 Clarification 4: the 10-26 'ONLY permitted edit' sentence guards the entry sha. B-1 expects MG1_LAST to move (rule.md:119-120), and no B sha covers mg1_reserved_window.py.
> (6) No NBM-band candidate touches dates after 11-28 while any date is pending.
> (7) The 10-26 inputs-only export rule covers 10-15..10-27.

**Numbering.** Item (5) says "B-1 Clarification 4". Master's conflict ruling C1 (same rulings file, line 692)
renumbered the clarifications: 4 is R19's coverage counts, and 5 is this R11 reading. The B-1 side of item (5)
is therefore in B-1 Clarification 5.

## 2. R11 schedule and open points (master actions and unresolved items, lines 45-62)

These are summarised here, not quoted. The rulings file is the authority.

- **P0 (11-02/03).** Master takes one thing only from the evening-fix countability step: the 10-16..10-28 dates
  with zero promotion-countable US11 market-days. Per-market detail stays unreported. A listed date extends
  MG1_LAST within two nights.
- **P1 (11-14), P2 (11-27), P3.** P1 and P2 run `mg1_countable` under the lease, in report mode only. P3 runs on
  the first admitted morning at least two days after the 45th date (11-30 if nothing moves) and runs `--final`.
  - On any non-countable or pending date, master commits the MG1_LAST extension (roll_verdict first; RS goes
    through the quiet-window merge, RF through the light path).
  - If nothing moves, master writes a dated no-move note.
- **The mg1_look scoring head.** It carries the mask, the pre-join hole check and `write_countable`, and lands by
  11-12/13. Head 2 (`mg1_countable`) stacks on it on the next RF night. The re-registered `mg1_look.py` sha256 is
  recorded in a dated B-1 clarification before the look.
- **Owner FYI.** Sent only if triggered: if MG1_LAST would reach 12-12 or later (14 or more non-countable dates),
  MG-1's look would fall on or after B's earliest look day, 12-13.
- **Still unresolved in R11.** The roll class of an MG1_LAST commit (`config/capture_families.json` references
  `weather.mg1_reserved_window:window`), and the outcome-blind source for `parser_v2_verified` and
  `shadow_stage_captured` per date (null with a reason is accepted).

## 3. A rulings (2026-11-03), verbatim

> OWNER (master carries these itself in its chat with the owner; don't ask in the WS chat): A1 Denver, A5 bar sign, A12 falsifier 4. Build both branches behind one constant per question, so each answer is a one-line change recorded before the look.

> - A2 (b): own MG-1 label loader in mg1_look on the R24 look-morning frozen copy only, via read_venue_labels (read_through = 45th date, allow_reserved_window=True, label_bucket -> band index, freeze receipt sha in the look receipt). Not b_transfer.
> - A3 (b), confirmed with R11 (1)-(2): D counts iff at least one support market-day is promotion_countable. mg1_countable/1 gains markets{m: bool}. read_inputs drops non-countable market-days before the join. KEY-ONLY hole check BEFORE looked_at_utc is stamped and before any outcome read: a hole means held, never consumed.
> - A4 (b): finality of the 45th date in every scored market AND the R24 freeze receipt exists; refuse until both.
> - A6 (a) plus an outcome-blind pre-join count of used rows whose v2_status is not "available". Non-zero means held, not consumed; master rules from the count alone.
> - A7 (b): attestation plus a marker/receipt-absence record.
> - A8 (a). A9 (a) as written, priced share disclosed (owner FYI). A10 (a) if the export schema shows model_version = served release id, else a key-only served_release_id column before the look. A11 (a). A13 (a). A14 (a).

Status by question:

| # | Subject | Status |
| --- | --- | --- |
| A1 | Denver in the US11 support and scoring | **owner question, open**. One constant in `mg1_look`; both branches are built and tested |
| A2 | Labels | ruled (b): own loader on the R24 frozen copy through `read_venue_labels` |
| A3 | Countable dates | ruled (b): `mg1_countable/1` gains `markets{m: bool}`; mask before the join; key-only hole check before `looked_at_utc` |
| A4 | "Settled" | ruled (b): finality of the 45th date in every scored market and the R24 freeze receipt |
| A5 | Materiality bar sign | **owner question, open**. One constant in `mg1_look`; both branches are built and tested |
| A6 | PIT on used rows | ruled (a), plus the pre-join `v2_status` count (non-zero holds the look) |
| A7 | Window leakage | ruled (b): attestation plus a marker and receipt absence record |
| A8 | Replay without a shadow vector | ruled (a) |
| A9 | Unpriced snapshots | ruled (a) as written, with the priced share disclosed. **Owner FYI:** this sets the primary population, so master reports it to the owner as information, not as a question |
| A10 | Served release id | ruled (a) if the export schema shows `model_version` is the served release id; otherwise a key-only `served_release_id` column before the look |
| A11 | Tail lens | ruled (a) |
| A12 | Falsifier 4 | **owner question, open**. One constant in `mg1_look`; both branches are built and tested |
| A13 | An ABORTED or VOID MG-1 receipt and B | ruled (a) |
| A14 | The 8/11 sign rule | ruled (a) |

Each owner answer is recorded in a dated note before the look. Until then, the open constants keep the
behaviour `mg1_look` has at `1179f990d`.

## 4. What this changes

- **Countable dates and the scored population.** They are read as in §1 (1)-(2) and A3. A counted date can hold
  non-countable market-days, and those are dropped before the join.
- **Hole check.** A countable market-day with no layout rows holds the look before it is consumed (key-only, R11
  (2)). It never aborts the look.
- **Labels.** The look reads labels only from the R24 look-morning frozen copy (A2). The look receipt records
  the freeze receipt sha.
- **When the look may run.** It waits for A4's finality and freeze conditions.
- **Unchanged:** the estimand, the pass rule, the falsifiers, the void conditions, D0, the 45-date count and the
  reservation. A1, A5 and A12 are the only open readings, and they stay open until the owner answers.
