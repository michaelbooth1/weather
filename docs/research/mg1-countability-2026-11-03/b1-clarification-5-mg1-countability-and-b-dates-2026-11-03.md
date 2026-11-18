# Rule B-1 Clarification 5: MG-1's countability reading and B's date aggregation (T1-T5), 2026-11-03

- **Status:** master ruling, not an owner decision. It lands in the 11-04 docs head.
- **Numbering:** master's conflict ruling C1 (2026-11-01) set the numbers: 4 is R19's coverage counts, 5 is
  this R11 reading, 6 is the look chain, and 7 is the S1 MG-1 entry sha. R11 item (5) and the 11-03 relay still
  say "B-1 Clarification 4"; this is that file.
  - Clarification 3 is `docs/research/b-look-s0-s1-2026-11-01/b1-clarification-3-s0-s1-look-wrapper.md`.
  - Clarification 4 is `docs/research/b-coverage-2026-11-02/b1-clarification-4-coverage-counts-2026-11-02.md`,
    which is on its branch and not yet on master.
- **Companion:** [MG-1 Clarification 2](../morning-guidance-read-mg1-clarification-2-2026-11-03.md) records R11
  items (1)-(7) and the A rulings.
- **Sources:**
  - R11 (2026-11-01): master's rulings file, WS copy sha256
    `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`, lines 9-15 and 45-62; C1 is at line 692.
  - The T rulings (2026-11-03): host file `C:\tmp\agent-kit\rulings-20261103-mg1-b.md`, sha256
    `28c4f298c9d128189468ab62562ebb79e055a6c42328315c8182178642b01906`. They are quoted below from the
    coordinator's verbatim copy of master's condensed messages.
- **History only:** no outcome, label, price, market, settlement or ledger value was read to write this.
- **What changes:** how B reads MG-1's MG1_LAST moves, and how B's per-date countable flag is formed and checked
  (T1-T5).
- **Nothing else changes:** the estimand, the keep/kill rule, the 10 markets, the bound files, the hashes and the
  thresholds.

## 1. The B-1 reading of R11 item (5)

R11 item (5), verbatim: "MG-1 Clarification 2 / B-1 Clarification 4: the 10-26 'ONLY permitted edit' sentence
guards the entry sha. B-1 expects MG1_LAST to move (rule.md:119-120), and no B sha covers
mg1_reserved_window.py."

- **The sentence.** The 10-26 clarification
  (`docs/research/mg2-composite-binding-2026-10-25/b1-clarification-mg1-look-receipt-2026-10-26.md` §4, lines
  74-76) and the `b_scorer.py` comment (lines 126-131 at S0) say that before the MG-1 look the only permitted
  edit to `mg1_look.py` or `mg1_reserved_window.py` is the scoring addition plus re-registration. It exists to
  fix the MG-1 entry sha that VOID 5 checks (`MG1_LOOK_ENTRY_SHA256`).
- **MG1_LAST is expected to move.** B-1's Branch 1 date rule
  (`docs/research/mg2-composite-binding-2026-10-25/rule.md` lines 119-120) takes "the first 45 countable dates
  after `weather.mg1_reserved_window.MG1_LAST`" and says it "moves later whenever MG1_LAST does".
- **No B sha covers `mg1_reserved_window.py`.** It is outside B's release binding (`rule.md` §"Release binding",
  lines 535-550) and outside the bound `b_scorer.py` S0
  (`f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439`).
- **Reading.** An MG1_LAST extension commit under R11 (4) is not an edit that the sentence forbids, and it does
  not void B. It changes `mg1_reserved_window.py`'s MG1_LAST only, not the MG-1 entry sha. The entry sha is
  still set from the re-registered `mg1_look.py` by the dated sha clarification (number 7) before the MG-1 look.
- **L6_G (DECISION_LOG row 2026-10-30, item (2)).** L6_G accrues on B's dates as a screen only. It looks only
  after every test that claims its dates has looked. This file changes no L6_G date, rule or hash.

## 2. T rulings (2026-11-03), verbatim

> T RULINGS: the SoP's "T1-T5" (1f8f49d8a, 10-31) were never written down anywhere. This sitting DEFINES them; it does not reconstruct an older list.
> - T1: a B date counts iff EVERY B market-day (10 markets, Denver out since master 10-25) is promotion_countable. b_scorer has no mask (BS:634-647) and is B-bound, so ALL is the only rule under which every scored snapshot can have a label. Non-countable dates move B's 45th date later, never earlier.
> - T2: a reader refusal or a missing label row makes the date non-countable for B and masks that market-day for MG-1. Never a VOID.
> - T3: key-only layout coverage check in b_transfer before publish. Mismatch: refuse, look held.
> - T4: R19 addendum (rulings.md:106, capture_price, sidecar [n_rows, n_priced]) plus a [0,1] range check. Out of range: refuse, held.
> - T5: both lists come from the same ledger (latest revision), each records its ledger sha. BT:157-165 constancy applies to B's collapsed flag over B's 10 markets only. A key-only MG-1 vs B cross-check is descriptive, never a gate.

Code keys (from the 11-03 code packet, `docs/research/mg1-look-packet-2026-11-03/PACKET.md` @
`c0f11fdd58ef6d5477192a3a701dee9ace2170bf`):

- BS = `src/weather/calibration/b_scorer.py` at S0 on master `621d67f0fdbd05556725239cd09f07468c132241`;
- BT = `src/weather/calibration/b_transfer.py` on `claude/b-transfer-writer-20261031` @
  `2e2f4a0e179cadc150717848e5b6766d11f02d4d`.

## 3. What this fixes in B's procedure

- **One date rule (T1).** B's per-date `promotion_countable` in the transfer manifest (BS:565) is ALL over B's
  10 markets. Denver never enters B's flag.
  - The look dates are still the input-countable dates from D0 through the 45th countable one, with no skipping
    (BS:582-588).
  - A non-countable date moves B's 45th date later.
- **Refusals and holes (T2, T3).**
  - A label reader refusal or a missing label row makes the date non-countable for B, never a VOID.
  - The transfer writer refuses to publish when a layout snapshot on a countable date has no label row (a
    key-only check). The look is then held, not consumed.
  - With T1, this is what makes every scored B snapshot carry a label. A missing label inside `build_table`
    would otherwise abort B after its look is consumed.
- **Prices (T4).**
  - The writer derives `p_market_yes` only through `b_price_coverage.capture_price`, writes NaN otherwise, and
    checks each snapshot's [n_rows, n_priced] against its sidecar (R19 addendum).
  - It also refuses a price outside [0, 1].
  - Either failure refuses the transfer and holds the look.
- **Ledger and cross-check (T5).**
  - MG-1's countable list and B's come from the same settlement ledger (latest revision), and each records the
    ledger sha.
  - The writer's within-date constancy check (BT:157-165) applies to B's collapsed flag over its 10 markets.
  - A key-only comparison of the two lists is reported, never a gate.
- **The build** goes to the `b_transfer` writer head (T1, T3, T4 and a B label loader on the 12-13 frozen copy
  through `read_venue_labels`), for master review by 12-01. `b_scorer.py` is not edited.
