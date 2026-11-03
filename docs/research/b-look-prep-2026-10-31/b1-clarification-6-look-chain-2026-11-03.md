# Rule B-1 Clarification 6: the look chain, 2026-11-03 (DRAFT)

- **Status: DRAFT by lane L16, 2026-11-03, for master review.** It is not in force, not signed, and not an owner
  decision. It is due before 2026-11-29 (rulings file line 738).
- **Before landing, fill every placeholder.** Every `docs/**/b1-clarification-*.md` file is a permanent B-1
  record under R14 (`config/frozen_bindings.json` `record_globs` on `claude/r14-frozen-bindings-20261101` @
  `440ed60934349608fe60f6e144e2b355fb888a9c`). Once this file lands, it cannot be edited. So every `<PIN: …>`
  below must be replaced with its value, or deliberately left to a later dated clarification, in the landing
  commit itself.
- **Numbering:** this is file 6 under master's conflict ruling C1 (rulings file line 692): 4 = R19 coverage
  counts, 5 = R11, 6 = look chain, 7 = S1 MG-1 entry sha. It is a new file outside the bound directory and
  replaces the in-place DRAFT `look-chain-clarification-DRAFT.md`, which is not edited (C1).
- **Sources:**
  - Master rulings 2026-11-01 (R11, R14, R19, R24, R28b, C1): WS copy `C:\t\rulings-20261101\rulings.md`, sha256
    `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`. It is cited below as "rulings:<line>".
  - Master rulings 2026-11-03 (A1-A14, T1-T5): host file `C:\tmp\agent-kit\rulings-20261103-mg1-b.md`, sha256
    `28c4f298c9d128189468ab62562ebb79e055a6c42328315c8182178642b01906`. It is quoted from the WS coordinator's
    verbatim condensed copy (`C:\t\mg1-b-rulings-20261103\rulings_condensed.md`, sha256
    `f1ded718b1fc8e7fc5598b59b12f6557276abfd2b341accaa7d51ff44cbad016`) and cited below as "11-03:<line>".
  - Master's 10-31 rulings (i) to (iii) on the per-date extractor and the sentinel, as recorded in
    `look-chain-clarification-DRAFT.md` and `look-day-dry-run-checklist.md` (this directory).
  - B-1 Clarification 3 (`docs/research/b-look-s0-s1-2026-11-01/b1-clarification-3-s0-s1-look-wrapper.md`) and
    Clarification 5 (`docs/research/mg1-countability-2026-11-03/b1-clarification-5-mg1-countability-and-b-dates-2026-11-03.md`
    on `claude/mg1-b-rulings-docs-20261103`).
- **History only:** no outcome, label, price, settlement, ledger or panel value was read to write this. It cites
  code and docs only.
- **What changes:** this file fixes the closed, ordered list of look-day steps for B, with their entry points and
  pinned shas. It also adds the receipt-commit step that the R14 release record needs.
- **Nothing else changes:** B-1's estimand, keep/kill rule, markets, VOID conditions, one-look markers,
  embargo, thresholds and every bound file stay as bound. `B_FORWARD_TEST_DESIGN.md` and
  `docs/research/mg2-composite-binding-2026-10-25/` are not edited.

## 1. Look-day sequence (closed list)

The look session runs these steps and no others, in this order, each once. Pre-session steps 0a to 0c run on the
host on look morning. Steps 1 to 6 are the look session itself. The sequence follows R24 (3) (rulings:240, 289),
R19 (rulings:111) and master's 10-31 ruling (i): R24 freeze, then `b_transfer`, then the B look through the
wrapper, then the post-look extractor.

Every `<PIN: …>` is a sha256 from §2's closed list. Each command is typed as one bare line (Clarification 3 §5).

### Pre-session (host, look morning, lease held)

0a. **MG-1 receipt check.** The MG-1 look receipt exists, and B's own check passes on it:
`python -m weather.calibration.mg1_look check-receipt --receipt <mg1 look receipt.json>`. Log its sha256.

0b. **R24 freeze** (rulings:289, about 07:20 on 12-13, lease free, before 09:00). This runs after the last
date's finality: `python -m weather.backtesting.venue_label_audit freeze --look b --through <latest date final in all 10 B markets>`.
Log the sha256 of `freeze_receipt.json` and every per-market sha it lists, before the look starts.
- The module is `venue_label_audit.py` `<PIN: venue_label_audit>`. It is on `claude/r24-freeze-keys-20261103`
  @ `a1676b09f5db89dda5f02a4da083d0b1352f36e4` and not yet on master.
- Its receipt must carry `markets[m].label_dates` and `skipped_dates`, which §3 needs.
- **`--through` (master ruling B4, 2026-11-03).** The 12-13 B freeze uses `--through` = the latest date with
  finality in all 10 B markets on freeze morning. It freezes everything settled, not a guessed 45th date.
  - The 45th date is then fixed pre-read in step 0c, from the ledger plus the frozen keys
    (`b_transfer.select_dates` at `9217788ea41390acc370249da54cb3974664306c`).
  - If the 45th date is after `through`, the transfer HOLDS. Nothing is read, and master re-freezes on a later
    morning.
  - The label read never parses a frozen label after the 45th date (§3).

0c. **Label transfer, with its self-checks.** This step reads the input-window manifest produced earlier by
`python -m weather.calibration.mg2_inputs concat --layout <per-date layout> … --out <window>` over the
input-countable dates. That module is B-bound and is used read-only.
`python -m weather.calibration.b_transfer write --market <export market.parquet> --input-window <window manifest.json> --ledger-root <settlements root> --frozen-labels <data\venue_rule_labels\frozen\b> --coverage-root <data\exports\mg2-inputs\_b_coverage> --d0 <D0> --mg1-look-receipt <mg1 look receipt.json> --out <new transfer directory> [--sidecar-override <master override.json>]`
- The module is `b_transfer.py` `<PIN: b_transfer>`.
- It must run as its own `__main__`, or it refuses the label read.
- Log the sha256 of `b_transfer_manifest.json`.
- A refusal or hold here means the look is held, not consumed (§3).

0d. **Concatenate the 45 countable dates** (R19, rulings:111). This is `mg2_inputs concat` over exactly the
transfer manifest's dates: `<PIN: concat command and window>`.

0e. **Drop list** (R19, rulings:82, 111). Run
`python -m weather.calibration.b_drop_list materialize --window <step 0d window> --out <drop list>` before the
MG-2 score.
- The module is `b_drop_list.py` `<PIN: b_drop_list>`. It is on `claude/r19-b-coverage-20261101` @
  `55e5147e1158b1e547b038727bf898adc665a3fe`, an ancestor of combo A' `a026af7f6`, which the night sequencer lands
  from 00:35 on 11-04 (master 2026-11-03).
- Log the drop-list sha256. `look_guard` writes it into the consumed marker.

### Look session

1. **MG-2 score.** Run `python -m weather.calibration.mg2_composite score …` with the MG-2 binding's arguments
   on the step 0d window. The module is `mg2_composite.py`, at its MG-2 binding pin. It writes `mg2_look.json`.

2. **B look, through the wrapper only** (Clarification 3 §2 and §5):
   `python -m weather.calibration.b_look_wrapper look --s0 <scratch copy of S0 bytes> --rule … --mg2-rule … --release-binding … --layout <step 0d window> --vectors … --mg2-look <mg2_look.json> --transfer <step 0c directory> --drop-list <step 0e> --control-receipt … --mg1-look-receipt <mg1 look receipt.json> --out <look out>`
   - Never run `python -m weather.calibration.b_scorer look` directly.
   - This step writes `b_look.json`, `b_look_receipt.json`, `b_look_wrapper_receipt.json`,
     `b_look_wrapper_rule.md` and the consumed markers.
   - Log the instant of the receipt write (UTC).

3. **Per-date extractor** (master's 10-31 ruling (i)). Run it within 60 minutes of step 2's receipt, in the same
   operator session (rule (A), `look-chain-clarification-DRAFT.md` §4):
   `python -m weather.calibration.b_look_per_date --look-out <look out> --layout <step 0d window> --vectors … --transfer <step 0c directory> --drop-list <step 0e>`
   - Log `extracted_at_utc`.
   - If the gap exceeds 60 minutes, label the per-date output 'late'. That never blocks B.

4. **Post-look analysis, ruling (b).** Run it only on a scored verdict:
   `python -m weather.calibration.b_post_look_serial --per-date <b_per_date.json> --b-look <b_look.json> --out <new path>`

5. **SPECI / floor-zeroed-band disclosure** (non-deciding; draft on `claude/b-speci-disclosure-20261101` @
   `468aa514cd8b3efc89458c44555ffb884fade8e2`, §3). Run it only on a scored verdict.
   - Command: `python -m weather.calibration.b_floor_disclosure --look-out <look out> --layout <step 0d window> --vectors … --transfer <step 0c directory> --drop-list <step 0e>`.
   - Module: `src/weather/calibration/b_floor_disclosure.py` `<PIN: b_floor_disclosure>`.
   - It writes `b_floor_disclosure.json` and `b_floor_disclosure_receipt.json` beside B's look, with mode "x".
   - SPECI attribution is given only from a flag in B's bytes (master 2026-11-03). B's layout, vectors and
     transfer carry none, so the sub-count is reported NOT_COMPUTED with the columns checked. The module never
     opens MG-2's bundle.
   - If no pinned implementation exists at the look, the disclosure is reported as NOT COMPUTED, and nothing
     about B changes (draft §3, "Code").

6. **Commit the receipt and the release record** (R14 (4), rulings:494, 547).
   Commit B's receipt (b_look_receipt.json) byte-exact, in the same head as the release record: copy it unmodified to its repo path, add the line '<receipt_path> -text' at the end of .gitattributes in that head, and set receipt_path to that path and receipt_sha256 to the sha256 of those bytes; the R14 guard refuses the record otherwise.
   - The record is `docs/research/b-look-record/b-look-record.md`. It has key: value lines `rule_sha256` (B's rule
     sha `e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030`), `receipt_path`, `receipt_sha256`
     and `decision_log_row`, and no outcome values.
   - Master lands it only after the look, per-date and post-look receipts all exist, and after checking the
     receipt sha256 against the copy in the WS never-cleaned archive (rulings:547).
   - The guard is `receipt_attribute_problem` and the record checks in `tests/operations/test_frozen_bindings.py`
     on `claude/r14-frozen-bindings-20261101` @ `440ed609…` (lines 105-156).
   - the b_post_look_serial SchemaSpec lives in src/weather/schema_families/b_post_look_serial.py from blook-r3. master-ruling-b-post-look.md:154 is superseded on location only.
     (Commit `b787e96363d33041701bdfc18525da5fe9081f1a`
     on master; `src/weather/schema_registry_data.py` does not carry it.)

## 2. Closed list of expected shas

The look-day checklist verifies every row below on the host before step 0c, with `Get-FileHash -Algorithm
SHA256` on the production checkout. Any mismatch stops the session before the transfer, and nothing is consumed.

| Module | Role | Expected sha256 | State |
| --- | --- | --- | --- |
| `src/weather/calibration/b_transfer.py` | step 0c | `<PIN: b_transfer>` | candidate `f43efe9473af5679a378109c4f391c81dfea33ef3e2e703272937f326b65bf07` at `claude/b-transfer-writer-t134-20261103` @ `9217788ea41390acc370249da54cb3974664306c`; master review due 12-01 (11-03:29); not pinned |
| `src/weather/calibration/b_look_per_date.py` (the extractor) | step 3 | `a28d2e65e8ae0ca4239bec7b641ed4d0fcb3758d2e31c6970a2ed29b68762d66` | frozen at `818232cfd8b5b3b06bf6235ac450b2ac49413f38` |
| `tests/calibration/test_b_look_per_date.py` | extractor test | `b54cd895ff731db3ededd1b9242cb2e86efae49358dcda100a40447f6f893fce` | corrects the DRAFT's `92f738ef…` (rulings:541; `master-ruling-b-post-look.md` revision 2026-10-31) |
| `src/weather/calibration/b_scorer.py` | step 2 (inside the wrapper) | S1 `<PIN: b_scorer S1, from Clarification 7>`; S0 `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439` for `--s0` | S1 is set by the Clarification 7 commit |
| `src/weather/calibration/b_look_wrapper.py` | step 2 | `<PIN: wrapper successor of a77617a4…, from Clarification 7>` | the same path, `src/weather/calibration/b_look_wrapper.py`, after the S1 commit changes only line 82 (`MG1_LOOK_ENTRY_PIN = PIN_UNSET`) from `a77617a4e0091ac0167c590a295afb457bcfdc8659518edc37cb45d0f4216f1c` (Clarification 3 lines 81-84; R14 `s1_edit`). No branch carries it yet. |
| `src/weather/calibration/b_scorer_entry_edit.py` | step 2 | `a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c` | pinned |
| `src/weather/calibration/b_post_look_serial.py` | step 4 | `0c485d6e347dc11c95a7cf756e760e292db12536e663c61c1eda5d9650d80bed` | frozen at `fa380db09980692f6afe50eb48b949b6c21aa88a` |
| `tests/calibration/test_b_post_look_serial.py` | step 4 test | `42976969d7e7c2518fafa4adc44abb0f2f8bbab4b2e8676d53da5eae73730a66` | re-pinned 2026-10-31 |
| `src/weather/calibration/b_floor_disclosure.py` (SPECI / floor disclosure) | step 5 | `<PIN: b_floor_disclosure>` | candidate `4f7f742607becac9c163f01438fc4b9c6aed5e1b0afc7b6db359500b0f18cfa4` at `claude/b-speci-disclosure-20261103` @ `1a0a04f9dd729e4773b3da39df48cc045782209b`; lands in a suite-gated RF combo before 11-25 |
| `tests/calibration/test_b_floor_disclosure.py` | step 5 test | `<PIN: test_b_floor_disclosure>` | candidate `d2ba535ffc2f64c6344d925f5adc0bf8ef84e8374fe5fb4c6bf0f2a59f839d5a` at the same commit |
| `src/weather/calibration/mg1_look.py` | step 0a, VOID 5 | `<PIN: mg1_look re-registered>` = `MG1_LOOK_ENTRY_SHA256` | candidate on `claude/mg1-look-scoring-r11-20261103`; set by Clarification 7 |
| `src/weather/backtesting/venue_label_audit.py` | step 0b | `<PIN: venue_label_audit>` | on master by 11-20 (rulings:265) |
| `src/weather/calibration/b_drop_list.py` | step 0e | `<PIN: b_drop_list>` | R19 head `55e5147e1`, in combo A' `a026af7f6` (lands from 00:35 11-04) |

Host dry-run checklist additions, before step 0c:
- [ ] Hash every file in the table and compare it to the expected sha256. Stop on any mismatch or placeholder.
- [ ] Confirm that `b_scorer.py` is S1 and passes
  `python -m weather.calibration.b_scorer_entry_edit --s0 <S0 copy> --s1 src\weather\calibration\b_scorer.py`.
- [ ] Confirm that the wrapper's `MG1_LOOK_ENTRY_PIN` and `b_scorer.py`'s `MG1_LOOK_ENTRY_SHA256` hold the same
  value, and that it equals `MG1_CONFIRMATION_ENTRY_POINTS["weather.calibration.mg1_look"]`.
- [ ] Confirm that `python -m weather.schema_registry audit --strict` is clean on the production checkout.
- [ ] Record the hashes in the look log before any step runs.

## 3. Hold and refuse semantics of the transfer (step 0c)

"Held" means nothing is published, the look is not consumed, and master rules outcome-blind before a re-run.
"Refused" is a held transfer whose reason is on stdout, or in `<out>.refusal.json` where stated.

- **T1 (11-03:19).** A date counts if and only if all 10 B market-days (Denver out) are `promotion_countable`
  in the ledger's latest revision. Each market ledger's sha256 is in the manifest (T5, 11-03:23).
- **Pre-read T3 (master 2026-11-03).** The 45th date is fixed before any label is read. It comes from the frozen
  manifest's `label_dates` and the freeze receipt's `markets[m].label_dates` / `skipped_dates`. Keys only; no
  CSV is parsed.
  - A missing field refuses, naming the field.
  - A predicted skip makes that date non-countable for B (T2, 11-03:20). It is never a VOID, and it moves the
    45th date later, never earlier.
  - A date in neither list, or any metadata inconsistency, HOLDS (`UNEXPLAINED_ABSENCE_HOLDS = True`). Master
    closed this question on 2026-11-03 (Q1).
- **Freeze bound (B4, master 2026-11-03).** The freeze covers every date settled in all 10 B markets on freeze
  morning (step 0b).
  - The 45th date is fixed pre-read from the ledger plus the frozen keys.
  - If the 45th date is after the freeze's `through`, the transfer HOLDS: nothing is read, and master re-freezes
    on a later morning.
  - `read_venue_labels`' `read_through` is the 45th date, so frozen labels after it are never parsed.
  - Code note for master's 11-20 review: at `9217788ea` the writer passes `read_through` = each read date, every
    one of which is at or before the 45th date. That is the same bound or tighter.
- **Post-read refusal.** Two cases refuse, publish nothing, and never move the 45th date:
  - a reader refusal that the metadata did not predict;
  - a B snapshot whose label no band maps to.
  The writer then writes `<out>.refusal.json` (schema `b_transfer_refusal/1`), with mode "x". It holds date,
  market and reason, and no value.
- **T3 layout coverage (11-03:21).** A key-only check runs before publish. If a layout snapshot on a countable
  date has no label row, the transfer refuses and the look is held.
- **T4 prices (11-03:22; R19 addendum, rulings:69).**
  - `p_market_yes` comes only through `capture_price` (finite and in [0, 1], else NaN).
  - A finite price outside [0, 1] refuses (`REFUSE_FINITE_OUT_OF_RANGE = True`).
  - If any snapshot's `[n_rows, n_priced]` differs from its date's `b_price_coverage/1` sidecar, the transfer
    refuses.
- **False sidecar flags hold.** A false `match`, `bundle.ready_marker_matches` or `sources.<m>.match` flag
  holds the transfer. Only master's override file passed as `--sidecar-override` releases one:
  `{"schema": "b_transfer_sidecar_override/1", "dated": "YYYY-MM-DD", "outcome_blind": true, "releases": [{"date": "YYYY-MM-DD", "flag": "<flag name>", "reason": "..."}]}`.
  - It releases only the exact (date, flag) pairs it names.
  - A malformed override refuses. So does one not marked `outcome_blind`, or one dated after the transfer.
  - The manifest records the override's sha256 and the released flags.

## 4. MG-1 receipt and VOID 5

- **Two new receipt fields.** The re-registered `mg1_look` receipt (`claude/mg1-look-scoring-r11-20261103`,
  `RECEIPT_FIELDS`) adds two fields:
  - `label_freeze_receipt_sha256`, the R24 freeze receipt the MG-1 look read its labels through (A2, 11-03:11);
  - `flags`, the sorted flags the look raised, for example `label_refusal_unpredicted_by_metadata`.
- **The listed fields are unchanged:** `schema`, `entry_point`, `mg1_rule_sha256`, `window`, `dates_scored`,
  `looked_at_utc`, `completed_at_utc`, `result`, `mg1_py_sha256`, `repo_commit`, `host` and `body_sha256`.
  `body_sha256` covers the two new fields.
- **The check.** B's VOID 5 calls the running `mg1_look.receipt_problems` (`b_scorer.py` line 520). So the
  receipt must be written by the same re-registered `mg1_look.py` whose sha is `MG1_LOOK_ENTRY_SHA256`.
- **VOID 5 timing (A13 (a), 11-03:16; packet A13).** VOID 5 is a timing referee.
  - It checks that the receipt is valid, that its entry sha equals `MG1_LOOK_ENTRY_SHA256`, that the manifest
    binds it by sha256, and that the transfer comes after the receipt's own `looked_at_utc`. It never uses a file
    time.
  - An ABORTED or VOID MG-1 receipt lets B proceed. B's validity does not depend on MG-1's verdict.

## 5. The `MG1_LOOK_ENTRY_SHA256` sentinel

- **Ruling (iii).** Master's 10-31 ruling (iii) is recorded only as cited text:
  - `look-day-dry-run-checklist.md` lines 41-45: "the `UNRECORDED` sentinel BY DESIGN (master ruling (iii),
    2026-10-31)", with the constant set "once MG-1's look receipt exists (2026-11-29..12-12)";
  - `look-chain-clarification-DRAFT.md` line 66.
  - Its verbatim source is host `loop-plan.md` line 1341, per `docs/roadmap/audits/state-review-2026-11-01/findings.md`
    row D4-1. That file is not in the repository, so its exact wording could not be quoted here.
- **Superseded on timing.** Master adopted Reading A on 2026-11-01 (Clarification 3 §5): the constant is set
  before the MG-1 look, from the re-registered `mg1_look.py` source sha.
  - It is set in one commit with the wrapper's `MG1_LOOK_ENTRY_PIN`, which is Clarification 7 (C1).
  - Until then, every look is VOID 5 by design (`b_scorer.py` lines 127-133), and the wrapper refuses every look.

## 6. Per-date claim table (R28b (3), rulings:435, 477, 736) — DRAFT

**Rule 9.** "No outcome, label or price on a date is read until every test that claims that date has taken its
look." Claims rank by freeze time, and a later-frozen test never reads a date before every earlier-frozen
claimant of it has looked. A claim binds only over its own scope (markets, dates, inputs): MG-1's covers
NBM-derived reads only (`docs/operations/MODEL_IMPROVEMENT_METHOD.md` lines 171-176). After B, rule 9 is per
date, and dates from 11-02 on stay claimed until 01-26 or later (R28b (3), rulings:435).

Rows are in rule-9 order (freeze time). Lines cite `origin/master` `621d67f0f` unless a branch is named.

| # | Claimant | Frozen (rule-9 rank) | Dates claimed | Look | Source |
| --- | --- | --- | --- | --- | --- |
| 1 | MG-1 (scope: NBM-derived reads only) | prereg signed 2026-10-04 (DECISION_LOG:107); window bound 2026-10-16 (DECISION_LOG:227) | 2026-10-15 .. `MG1_LAST` 2026-11-28, provisional; it only moves later (DECISION_LOG:227; `weather.mg1_reserved_window`) | one look on the look morning after the last date's finality and the R24 freeze (11-29 or later; A4, 11-03:13; rulings:287, 738) | `mg1_reserved_window.py`; MG-1 Clarification 2 |
| 2 | Evening-fix read (evening lock-in fix scoring) | signed 2026-10-13 (DECISION_LOG:183) | local targets 2026-10-16 .. 10-27; the outcome-blind extension may add 10-28 only, never 10-29 (DECISION_LOG:295) | Stage 1 (`--no-market`) ran 11-02 (DECISION_LOG:300). Stage 2 (condition 3, prices) only after MG-1's look receipt exists (DECISION_LOG:295) | Clarification 1 `docs/research/evening-lockin-fix-scoring-clarification-1-2026-10-31.md`; R24 (4), rulings:242 |
| 3 | B (and MG-2, one look) | BOUND 2026-10-28 (`B_FORWARD_TEST_DESIGN.md`:28) | D0 2026-10-29; the first 45 countable dates with no skipping; the 45th is 2026-12-12 if all count, moving later per non-countable date (`B_FORWARD_TEST_DESIGN.md`:106-114) | 12-13: freeze about 07:20, then this file's §1 chain (rulings:289) | `B_FORWARD_TEST_DESIGN.md` §3; this file |
| 4 | L6_G (screen on B's dates) | FROZEN 2026-10-30 (DECISION_LOG:288; prereg line 1) | D0 2026-10-31; N = 45 countable dates with no skipping (`l6g_forward_prereg_FROZEN_2026-10-30.md`:9, 106) | a single look after B (on or after 12-13), after every test that claims its dates (prereg:40; method:170) | `docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_FROZEN_2026-10-30.md` |
| 5 | Row 72 (R-ODC P1) | FROZEN 2026-10-30, after 13:00 EDT (`rodc-forward-prereg-2026-10-29/prereg-draft.md`:1-8) | D0 2026-10-31; the first 45 countable dates; a non-countable date is skipped (prereg-draft:86-92) | after the 45th countable date and on or after the B look receipt (prereg-draft:93) | `docs/research/rodc-forward-prereg-2026-10-29/prereg-draft.md` |
| 6 | F8-MH | frozen 2026-10-31 (`f8-mh-forward-2026-10-31/freeze.md`:3) | D0 2026-11-02; window 2026-11-02 .. 2027-01-25 (85 local dates) (freeze.md:84-86) | one look in the 01-26 window: on or after PT-1's look (on or after 2027-01-27) and after B/MG-2, MG-1, L6_G and row 72 (freeze.md:87-88) | `docs/research/f8-mh-forward-2026-10-31/freeze.md` |
| 7 | T+1 (A1-A3) | NOT frozen: DRAFT rev 11 (`claude/t1-forward-prereg-20261030` @ `8f8158d1f`, README:3) | from the first target date after its freeze commit; A1/A3 dates inside MG-1's window are also MG-1's (README:374-379) | first readable look after B's 12-13 look, MG-1's look (A1/A3) and row 72's look; F8-MH and PT-1 dates are not read there. Final look at 82 or more countable dates and after the PT-1 and F8-MH looks (README:385-399) | `docs/research/t1-forward-prereg-2026-10-30/README.md` on that branch |
| 8 | PT-1 | **NOT RUNNABLE (R21, master 11-01), claims no date** (rulings:188, 196, 201) | **none** (R21, rulings:188, 201). The draft (`PT_D0: UNSET`, `COOL_SEASON_PAPER_TEST_PREREG.md`:6-10) is never bound | — (it has no look) | terminal record `docs/research/pt1-not-runnable-2026-11-03/receipt.md` (sha `<PLACEHOLDER until L59's docs head lands>`) |
| 9 | Row-28b forward (candidate claimant) | NOT frozen: DRAFT (`claude/row28b-forward-prereg-draft-20261103` @ `1fed1b989`, `prereg_row28b_forward.md`:8-9); it freezes only after the owner OKs a 12-17 embargo line | D0 2026-12-17; N = 45 forward dates (12-17..01-30 if none drops) (prereg:52-53) | not before PT-1's and F8-MH's (01-26) looks and every earlier-frozen claimant; not before 2027-01-31 (prereg:54, 63-65) | `docs/research/row28b-forward-prereg-draft-2026-11-03/prereg_row28b_forward.md` on that branch |

Notes:
- **Rows 4 and 5: L6_G ranks before row 72 (master ruling 2026-11-03).** The freeze commit's committer time is
  the only recorded freeze time:
  - L6_G: `475ddf81e15ab520ea861bd3ba9dc8af00ac9a56`, 2026-10-30T13:58:00-04:00;
  - row 72: `b6b855b4c14cc58ad98d3ebc797f6a5f3ee550d2`, 2026-10-30T13:59:20-04:00 (on
    `claude/rodc-forward-prereg-draft-20261029`; DEV_WINDOW_LEDGER:117).
  - Master's copy `f60b9d1aa` (14:43:22-04:00) is a byte copy and does not move row 72.
- **MG-1's scope.** The evening-fix read does not cover MG-1's anchor path (DECISION_LOG:218, A6). Its stage-2
  price read still waits for MG-1's receipt (DECISION_LOG:295).
- **MG-3** is not a claimant; it was dropped (DECISION_LOG 2026-10-30; T+1 README:403).
- **T+2 sibling** is not a claimant now: NO-GO, DEFERRED (master, 2026-11-03), not killed (§6 "T+2 go/no-go").
- **Rule-9 scope.** DECISION_LOG:309 (vi) put per-date vs per-(date, market) to the 11-03 sitting. R28b (3) says
  per date after B. I found no 11-03 text that changes this.

### Ranking of post-B uses

`<MASTER SLOT: rank the post-B uses of the B dates (R28b, rulings:477)>`

### T+2 go/no-go

**T+2 sibling: NO-GO, DEFERRED (master, 2026-11-03), not killed.**

- **Packet:** `claude/r28b-t2-presence-check-20261103` @ `201e58151`,
  `docs/research/r28b-t2-presence-check-2026-11-03/gonogo_packet.md`, sha256
  `985a3e121743547e85c8708267388a952f1266e9a6a3c40f1543f2582eeb6c0c`. The branch's later commit `2fde4f245`
  records this decision.
- **Reasons:**
  - Rule 6 fails at the N it can reach: 60-75 dates give power 0.25-0.30 at 1.5x.
  - It is last in the rule-9 queue.
  - The A2 ENS recorder gap.
  - Zero census lead-2 evidence (FD:88).
- **Reopen triggers** (any one):
  1. T+1's final look PASSES.
  2. A same-kind T+2 SD exists.
  3. Master accepts a look date that allows about 170+ countable dates (around May 2027 or later).
- **Claim table:** T+2 claims no date now (§6 notes).

## 7. Open items and blockers (not invented here)

- **B1. SPECI-disclosure module: built, not landed.** `b_floor_disclosure.py` is on
  `claude/b-speci-disclosure-20261103` @ `1a0a04f9d…`, from L51's accepted draft (`468aa514…`). It lands in a
  suite-gated RF combo before 11-25, and its sha replaces step 5's placeholder in the landing commit. If nothing
  is pinned by the look, the disclosure is NOT COMPUTED.
- **B2. Pins not yet fixed (expected; master 2026-11-03).** Every pin is filled in the landing commit (the 11-25
  docs head), and every pinned module must be on master by then:
  - `venue_label_audit.py`: combo C, 11-04/05;
  - `mg1_look.py`: 11-12/13;
  - S1 `b_scorer.py` and the wrapper successor (Clarification 7): 11-22..25;
  - `b_transfer.py`, `b_drop_list.py` and the concat command: by 11-20 (b_transfer's review moves to 11-20).
- **B3. R14** lands in combo C, 11-04/05 (master 2026-11-03).
- **B4. Freeze `--through`: CLOSED** by master 2026-11-03 (step 0b, §3).
- **Q1. Gap semantics: CLOSED** by master 2026-11-03. A date in `skipped_dates` is T2 (non-countable). A date in
  neither list, or any metadata inconsistency, holds.
- **Master slots in §6:** the ranking of post-B uses is open. The T+2 go/no-go is filled: NO-GO, DEFERRED
  (master, 2026-11-03).
- **Naming rule:** every B-1 clarification is named `b1-clarification-*.md` and lives outside the bound directory
  (rulings:541). This file complies.
