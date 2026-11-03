# MG-1 look scoring: build note and open questions for master (lane L8, 2026-10-31)

**Status: DRAFT for master's review, due 11-20. Not frozen, not run on any real data.** This is a dated research
note, not canonical guidance and not an owner decision. No outcome, price or label dated after 2026-09-29 was read
to write it. The tests are synthetic only.

## 1. What was built

- **Branch:** `claude/mg1-look-scoring-20261031`, off `origin/master` `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`.
- **The scoring addition** in `src/weather/calibration/mg1_look.py`: `score()` and `main run`. It is the only edit
  the B-1 receipt clarification of 2026-10-26 (section 4, "The VOID 5 referee") permits.
- **Re-registration:** `MG1_CONFIRMATION_ENTRY_POINTS` in `src/weather/mg1_reserved_window.py` now holds the new
  source sha256.
- **Two schemas** registered in `src/weather/schema_families/mg1_look.py`: `mg1_look_result/1` and
  `mg1_countable/1`. The strict source audit needs them.
- **Synthetic tests** in `tests/calibration/test_mg1_look.py`. The one test that pinned "`run` refuses" is replaced.
- **Not changed:** `b_scorer.py`. `MG1_LOOK_ENTRY_SHA256` stays the sentinel. Master's dated B-1 clarification
  sets it.

**Sources:**
- the MG-1 pre-registration at `02c410a5`, sha256 `b044e0f1…`: §3, §4 and §6;
- Clarification 1 (2026-10-16);
- `docs/operations/reserved-confirmation-window.md`.

## 2. Order of the look

Each step runs only after the one before it passes.

1. **Before any read:**
   - `Look(rule)` checks the signed rule sha and that the look has not run.
   - The countable-date list is checked. It must start at D0, skip no calendar date, hold exactly 45 countable dates,
     and end on the 45th. The 45th must be on or before the recorded `MG1_LAST`.
   - The window must have closed.
   - The 45th date must have ended in every US11 market.
   - There must be no existing result.
2. **Label-free inputs:** the layout snapshots and bands are read. `screen_inputs` refuses any label or price
   column.
3. **The MG-1 vector:** `free_source_candidates.mg1.predict`. That is the `mg1.py` whose sha the receipt records.
4. **The outcome-blind VOID checks of §6:** PIT, coverage, parser, replay and window leakage, plus the fallback
   reasons.
5. **The outcome read:** `join_outcomes` stamps `looked_at_utc`, writes the start marker, and then reads the labels
   and prices.
6. **Scoring:**
   - Primary: MG-1 minus served, 00-16, all rows with served fallback.
   - Cells: equal snapshots within each (date, market) cell, then equal cells.
   - Interval: fixed-market date bootstrap, 2,000 draws, seed 20261004, percentile 95%.
   - Pass rule (§4):
     - U < 0;
     - at least 8 of the 11 markets negative;
     - estimate ≤ −5% of the window's own 00-16 served − market gap.
   - Falsifiers 1-5.
   - Everything §4 lists as "reported beside", with no alpha.
7. **Write:** the result (mode "x"), then the receipt.
   - A VOID still writes both.
   - Any failure after step 5 writes an ABORTED result and receipt, then re-raises.

## 3. Ambiguities flagged to master (not resolved; each is a PROVISIONAL constant or branch in the code)

| # | Spec text | What the code does for now | Question for master |
| --- | --- | --- | --- |
| A1 | "US11", "the fixed 11-market support" (§4, §7) | B-1's ten markets plus `denver` | Which 11? Denver settles on KDEN from 2026-10-23 (the MG-2 C8 note), while MG-1 reads KBKF guidance. Does Denver stay in? |
| A2 | "The settlement label is the venue winner" (§3) | `--labels` (`row_key, winner`) and `--market` parquet files, read only at the join | Where do the labels and prices come from: their transfer, provenance and manifest? Should it reuse B's `b_transfer/1` or have its own? |
| A3 | Countable dates (§3, Clarification 1 §3-4; master owns countability) | An `mg1_countable/1` JSON written by master. It has one row per calendar date, with `promotion_countable`, `parser_v2_verified` and `shadow_stage_captured` | Is that format and that owner right? |
| A4 | "after the 45th counted date has settled" (§4) | The window has closed, AND it is past the latest US11 market-local midnight after the 45th date | Is "settled" a later instant, such as the label being final? |
| A5 | "estimate ≤ −5% of the window's own 00-16 served − market gap" | The bar is −0.05·gap, as written. If gap ≤ 0 (served beat the market), the bar becomes ≥ 0 | Intended? |
| A6 | PIT VOID: "any MG-1 input with availability after `captured_at_utc`" | Counted only on the snapshots MG-1 used. `mg1.predict` already sends a late-available read to served fallback. Finite-v2 rows that were late, and used rows whose `v2_status` is not "available", are disclosed and do not void | Does a late read that fell back count as an "MG-1 input" (so it voids)? `mg1.py` does not check `v2_status`; the eligibility text needs status `available`. |
| A7 | Window-leakage VOID | Reported as "attested in the look log by master"; always passes in code | Is a look-log attestation acceptable? Nothing in code can prove that no earlier join happened. |
| A8 | Replay VOID: "does not reproduce the shadow vector" | With `--shadow`, it must match to 1e-12 or the look is VOID. With no captured shadow vector, the check is reported as not applicable and does not void | Clarification 1 turned §3 (c) shadow capture into a caveat. Does the replay VOID then lapse, or must a shadow vector exist? |
| A9 | Population "all rows with explicit served fallback" | The primary reads no price, so it uses every snapshot. Market-relative quantities (the gap, the ratios, the tail lens) use only priced snapshots, meaning every band has a finite capture-time price | Should unpriced snapshots be dropped from the primary too, or the gap be computed on all rows somehow? |
| A10 | "served release ids" (§2, §4) | Value counts of the first column present among `served_release_id`, `release_id` and `model_version`. The MG-2 layout has only `model_version` | Is `model_version` the release id of record? |
| A11 | "the tail lens … (EF tail definition)" | The EF §10 table definition: served SE > market SE and \|p_served − p_market\| ≥ 0.30, on priced 00-16 band rows | Is that the right definition? EF §1/§1f quote different panel figures. |
| A12 | Falsifier 4: crossed point estimate of opposite sign | Evaluated as written. Under equal-cell weighting the crossed point estimate equals the fixed-market one, so this can never fire | Does falsifier 4 mean the crossed interval instead? |
| A13 | VOID and failures after the join | VOID: result plus receipt. A failure after the join (for example a missing label): ABORTED result plus receipt, then re-raise. A refusal before the join writes nothing and spends nothing | B's VOID 5 checks only receipt validity and timing, so an ABORTED or VOID MG-1 receipt lets B proceed. Intended? |
| A14 | Per-market sign rule, "≥ 8/11 negative" | A market with no cells, or a mean delta of exactly 0, does not count as negative | OK? |

**Also noted:**
- The comment at `b_scorer.py` line 131 still says the registered `1e691c58` "cannot score: its `run` refuses". That
  file is B-bound, so it is left alone; the dated clarification can supersede the comment.
- `mg1.predict` loops per snapshot. On about 50k forward snapshots that is well under a minute.

## 4. Pins (not frozen)

The registered `mg1_look.py` sha256 is the value in `MG1_CONFIRMATION_ENTRY_POINTS`
(`src/weather/mg1_reserved_window.py`), which a test pins to the file's bytes. The value first recorded in this
table was superseded by the 1179f990d re-registration and again by the Clarification 2 head (section 5).

Any answer to A1-A14 that changes `mg1_look.py` changes this sha and needs a new re-registration.

## 5. Clarification 2 head (lane L56, 2026-11-03; branch `claude/mg1-look-scoring-r11-20261103`)

Master's rulings of 2026-11-03 (MG-1 Clarification 2, with R11) are built on top of this branch.
Synthetic tests only.

**Owner questions.** A1, A5 and A12 stay owner questions, open. Each is one constant: `A1_DENVER_SCORED`
(True), `A5_BAR` ("as_written") and `A12_FALSIFIER_4` ("point"). Both branches of each are built and tested,
the result records the values in force, and `owner_constants()` refuses any value outside the two branches.
With A1 False, Denver leaves both the support and the scored markets, and `MIN_NEGATIVE_MARKETS` stays 8.

**A3: countability and the hole check.**
- `mg1_countable/1` rows carry `markets{m: bool}` over the support. `promotion_countable` must equal
  "some support market-day counts".
- `read_inputs` drops non-countable market-days before the join.
- A countable market-day with no layout rows raises `MG1LookHeld` before `looked_at_utc`. Nothing is
  consumed.
- `write_countable` writes the list once (mode "x"). It derives the date flag and accepts null caveats with a
  text reason in `caveat_reasons`.

**A6: v2_status hold.** A used row whose `v2_status` is not "available" holds the look before the join. Only the
count is reported.

**A7: absence record.** The result records that the start marker and the receipt were absent when the look
began.

**A4: when the look may run.** `score` refuses until two conditions hold:
- the 45th date has ended in every scored market;
- the R24 freeze receipt exists and is valid:
  - it is `venue_label_freeze_receipt_v1`, look `mg1`;
  - its `through` is at or after the 45th date;
  - it was frozen after the 45th date ended in every scored market;
  - every scored market's frozen CSV, manifest and WU summary match their recorded sha256.

The format is the one on `claude/r24-venue-label-audit-20261101`. Once that module lands, a test should pin
the schema string to its schema family.

**A2: labels.** `load_venue_labels` calls `read_venue_labels` on the frozen copy with:
- `read_through` = the 45th date;
- `allow_reserved_window=True`;
- `model_scoring=False` for Denver only.

`winner_band` maps `label_bucket` to the snapshot's band index (lte, range, gte). The look receipt gains
`label_freeze_receipt_sha256`.

**T2: refused labels.** A label the reader refuses masks its market-day after the join. It is disclosed in
`label_masked` (count, reasons, market-day keys) and never voids or aborts the look. A bucket that falls in
zero or several bands of its ladder still aborts.

**CLI.** `--labels` is replaced by `--label-freeze`.
