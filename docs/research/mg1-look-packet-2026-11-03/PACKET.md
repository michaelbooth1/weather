# MG-1 look ruling packet (A1-A14, T1-T5), 2026-11-03

Read-only code and docs analysis by WS lane L56. No label, price, outcome, settlement or ledger value and no
data file was opened. Every citation is `git show` on an origin ref.

Code keys used below (file sha256 is of the blob at that commit):

- ML = `src/weather/calibration/mg1_look.py` @ claude/mg1-look-scoring-20261031 1179f990d2c350a5c6cc81755c4a77252e344c83 (16ecad3586f0d87e9f6148e4bef76630ea7727786fad7a569a431482ea70e00b)
- RW = `src/weather/mg1_reserved_window.py` @ 1179f990d2c350a5c6cc81755c4a77252e344c83 (7096dd2c0df1d5c9539d81831aa3b785301f0ed5c7d09e685139fb5dcbe8ec3b)
- BT = `src/weather/calibration/b_transfer.py` @ claude/b-transfer-writer-20261031 2e2f4a0e179cadc150717848e5b6766d11f02d4d (14601fc1ad0b1ba9e85bf7f016242ff03203ce54a7310d28c37e1c40dd051a45)
- BS = `src/weather/calibration/b_scorer.py` @ master 621d67f0fdbd05556725239cd09f07468c132241 (f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439)
- VR = `src/weather/backtesting/venue_label_reader.py` @ master 621d67f0fdbd05556725239cd09f07468c132241 (a4483777143446f309d569ad90e0b9fac695d371bbb1d62b6a7d6367e6a32b66)
- DS = `src/weather/reporting/scorecards/dev_scorecard.py` @ master 621d67f0fdbd05556725239cd09f07468c132241 (6447876a0956eac4f67132bc69dba48c26a672f7554ec46e8bfbe94ffe801b56)

## 1. Per-question table

Source of A1-A14: `docs/research/mg1-look-scoring-2026-10-31/scoring-note.md` section 3, lines 61-74, on
claude/mg1-look-scoring-20261031 @ 1179f990d2c350a5c6cc81755c4a77252e344c83 (file last changed by
7d093c614a92a9371bb7f30b9428df1508e3c10e; file sha256 434c45cf575e1645422a3f45d5ba98195b2bfd32af0033db3b1505ff374d7c01).
The "Question" column below is that file's question cell, verbatim. OWNER = the owner, not master, must decide.

| # | Question (verbatim) | Options | Current code | Recommendation (one-line reason) | OWNER |
| --- | --- | --- | --- | --- | --- |
| A1 | Which 11? Denver settles on KDEN from 2026-10-23 (the MG-2 C8 note), while MG-1 reads KBKF guidance. Does Denver stay in? | (a) keep Denver in support and scoring; (b) Denver in date support only, masked from scoring from the cutover; (c) score B's ten | ML:198-201 MARKETS has denver; VR:65 and VR:168-175 refuse denver from the cutover when model_scoring=True (default) | (b): the reader already refuses Denver for model scoring (owner 10-23), so scoring it either ABORTS the look or needs model_scoring=False against a KBKF-read model | YES (changes the signed rule's "US11" population and the 8/11 base) |
| A2 | Where do the labels and prices come from: their transfer, provenance and manifest? Should it reuse B's `b_transfer/1` or have its own? | (a) reuse b_transfer/1; (b) own MG-1 loader on the R24 frozen copy | ML:412-437 reads any `--labels`/`--market` parquet; ML:667-668 CLI args | (b): b_transfer cannot serve MG-1, it refuses without an MG-1 look receipt (BT:104-119, BT:231) | no |
| A3 | Is that format and that owner right? | (a) keep per-date `mg1_countable/1`; (b) add per-market-day flags | ML:231-268 per-date bool only (ML:242, ML:247) | (b): R11 (1)-(2) need a per-market mask, which a per-date bool cannot carry; master stays owner | no |
| A4 | Is "settled" a later instant, such as the label being final? | (a) local midnight after the 45th date in every market; (b) finality plus the R24 freeze | ML:271-278 (a); ML:605-608 refuses before it | (b): R24 (3) freezes after the last date's finality, so the look must also require the freeze receipt | no |
| A5 | Intended? | (a) bar −0.05·gap as written; (b) −0.05·\|gap\| | ML:507 (a), PROVISIONAL | (b): with gap ≤ 0 the bar turns positive and a worse-than-served MG-1 can pass materiality | YES (pass rule) |
| A6 | Does a late read that fell back count as an "MG-1 input" (so it voids)? `mg1.py` does not check `v2_status`; the eligibility text needs status `available`. | (a) as coded, used rows only; (b) any finite late read voids | ML:339-357: PIT on used rows; status only disclosed (ML:356) | (a) plus VOID on used rows whose status is not "available": a fallen-back read is the served input, and the eligibility text binds used rows | no |
| A7 | Is a look-log attestation acceptable? Nothing in code can prove that no earlier join happened. | (a) attestation; (b) attestation plus marker evidence | ML:365-366 always pass | (b): keep the attestation and record that no started marker or receipt existed (ML:113-115) | no |
| A8 | Clarification 1 turned §3 (c) shadow capture into a caveat. Does the replay VOID then lapse, or must a shadow vector exist? | (a) lapse without a shadow; (b) require a shadow | ML:390-400 (a) | (a): Clarification 1 already set aside the capture; where a shadow exists it still binds at 1e-12 | no |
| A9 | Should unpriced snapshots be dropped from the primary too, or the gap be computed on all rows somehow? | (a) as coded; (b) drop unpriced from primary | ML:412-437 priced = all bands finite (ML:432-434) | (a): the primary reads no price, and dropping on price availability selects on market data; disclose the priced share | YES (population) |
| A10 | Is `model_version` the release id of record? | (a) model_version; (b) add a served_release_id column | ML:220, ML:577-584 | (a) if the layout's model_version is the served release id; verify in the export schema | no |
| A11 | Is that the right definition? EF §1/§1f quote different panel figures. | (a) EF §10 table definition; (b) another EF figure | ML:216, ML:485-500 | (a): it is a reported lens, never a gate | no |
| A12 | Does falsifier 4 mean the crossed interval instead? | (a) point estimate (never fires); (b) crossed interval | ML:519-522 (a) | (b): as written it is inert under equal-cell weights | YES (falsifier meaning) |
| A13 | B's VOID 5 checks only receipt validity and timing, so an ABORTED or VOID MG-1 receipt lets B proceed. Intended? | (a) yes; (b) B requires a scored MG-1 receipt | ML:639-645 ABORTED writes a receipt; BS:515-520 checks validity and timing | (a): VOID 5 is a timing referee, and B's validity does not depend on MG-1's verdict | no |
| A14 | OK? | (a) zero or no cells not negative; (b) other | ML:506, ML:467-474 | (a): conservative and literal | no |

T1-T5: NOT FOUND. Searched with `git grep` and `git log --grep` and found no T1-T5 definition:

- origin/master docs and src (only `docs/operations/STATE_OF_PLAY.md` row 82, a title naming "b_transfer T1-T5");
- origin/claude/b-transfer-writer-20261031 (2 files, b_transfer.py and its test, no T questions);
- the b-look-prep-20261031 branches (all four), b-look-s0-s1-clarification-20261101, b-scorer-20261026;
- master `docs/research/b-look-prep-2026-10-31/` (including look-chain-clarification-DRAFT.md and
  look-day-dry-run-checklist.md);
- origin/claude/night-combo-20261103 and -20261103a (only SoP row 83 and unrelated swarm T-labels);
- the local rulings file (rulings.md lines 49, 62, 106, which name T1-T5 but do not define them).

They look like master-held questions not in the repo. Section 2 gives the code facts any T ruling needs.

## 2. R11 checks (rulings.md lines 9-15 and 49)

(a) Does A3 and a per-market mask fit A1 (Denver) and the b_transfer date rule?

- MG-1 side: `mg1_countable/1` is per-date (ML:231-268). `read_inputs` keeps every MARKETS row on a counted date
  (ML:292), so there is no market-day mask. Under R11 (1), a counted date can hold non-countable market-days, and
  those are scored. A missing label there raises after `looked_at_utc` is stamped (ML:119-131, ML:428-430). The
  look is then ABORTED and spent (ML:639-645), as R11 (2) says.
- Denver: with Denver in MARKETS, every Denver market-day from the cutover has no model-scoring label from the
  reader (VR:65, VR:168-175). It must be masked or the look aborts.
- b_transfer: one flag per date, and it refuses when the flag varies within a date across all 11 markets
  (BT:157-165, BT:61-67). A per-market-day export (A3's semantics) therefore refuses on any mixed date. Only a
  pre-collapsed per-date flag passes, and that collapse (B's date aggregation, T1-T5) is not specified in code.
- FIT: not yet. The mask needs per-market-day flags in `mg1_countable/1`. The b_transfer rule needs a named
  aggregation.

(b) The three B points:

1. CONFIRMED. BS:565 `bool(r["promotion_countable"])` per manifest date row, inside `read_manifest` (BS:554-569).
   BS:582-588 then ties the countable dates to the look date set.
2. CONFIRMED. `build_table` (BS:634-647) filters MARKETS, keep_dates and priced snapshots only, with no
   market-day mask.
3. NOT GUARANTEED by code. The scorecard Table raises on any scored snapshot without a winner (DS:138-140). In B
   that happens after the look is consumed (`look_guard`, BS:347-407) and after `outcomes_opened` (BS:763), so it
   ends ABORTED (BS:713-718) and spends B. b_transfer checks winners only on rows of countable dates (BT:199-201)
   and never sees the layout, so it cannot prove every layout snapshot on a countable date has a label row.

(c) Conflicts, plainly:

- C1: A3 per-market-day countability vs BT:157-165 per-date constancy. A mixed date refuses the transfer.
- C2: if B aggregates "any market-day countable" (as A3), a B market-day without a winner on such a date ABORTS
  B (point 3). If B aggregates "all 11 countable", B's 45 dates can differ from MG-1's A3 set.
- C3: MG-1's countable list (`mg1_countable/1`, master-written) and B's (the export flags via BT:168-180) are two
  independent derivations, and no code checks that they agree.
- C4: b_transfer passes `p_market_yes` through unchanged. It has no `capture_price` (R19, line 106 addendum), and
  ML:432 and BS:612-620 test finiteness only, not the [0,1] range.

## 3. A2/A9 vs R24 (3)/(4)

R24 (3): the look reads only the frozen copy, through `read_venue_labels`, inside its registered entry point.
R24 (4): the scope includes MG-1 and B/MG-2.

- MG-1: DOES NOT MATCH.
  - ML never calls `read_venue_labels`. The only definition is VR:135, and there is no caller on master or on
    1179f990d.
  - ML:422 reads a ready-made `row_key, winner` parquet from any path, and nothing checks it against the frozen
    folder.
  - The registered-entry part does hold: the first outcome read runs inside `join_outcomes`, which refuses
    unless RW:115 `registered_confirmation_entry()` returns the module (ML:123-126).
  - Missing: a loader that calls `read_venue_labels` on the frozen per-market CSVs. It would need
    `read_through` = the 45th date, `allow_reserved_window=True` (VR:157-161), and the A1 choice for Denver
    (VR:168-175). It would map `label_bucket` (VR:121) to each snapshot's band index, run through
    `Look.join_outcomes`, and record the freeze receipt sha.
- B/MG-2: DOES NOT MATCH either. BT:21-25 and BT:236 take a ready-made labels export. BS reads only transfer files.
- Prices (A9) are outside R24, which covers labels only. They still need R19's `capture_price` (C4).

## 4. Narrative

The A questions are code-local, and most can be ruled by master. Four change the signed rule's pass criteria or
population (A1, A5, A9, A12) and are flagged OWNER. The blocking items are structural.

1. MG-1 has no per-market mask and no pre-join hole check, so a label hole spends the look.
2. Its label input is not the R24 path.
3. b_transfer's per-date flag rule cannot accept A3's per-market-day semantics without a stated aggregation,
   which is the unfound T1-T5 subject.
4. Neither scorer can prove before consumption that every scored snapshot has a label.

Suggested order:

1. Rule A1 and A3 together. Add per-market-day flags to `mg1_countable/1` and the mask plus a key-only hole
   check before `join_outcomes`.
2. Specify B's date aggregation, and add a key-only layout coverage check to the transfer.
3. Build the R24 loader inside ML.
4. Apply R19's `capture_price` in the transfer.
