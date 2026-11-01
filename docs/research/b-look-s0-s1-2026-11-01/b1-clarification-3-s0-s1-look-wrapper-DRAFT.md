# Rule B-1 Clarification 3 (DRAFT): the look runs at S1 through a pinned wrapper, 2026-11-01

- **Status:** DRAFT by lane L22 for master's ruling and adversarial review (d). Not in force, not signed, and not
  an owner decision. Numbered 3 after the two dated B-1 clarifications: the MG-1 look receipt (2026-10-26,
  `docs/research/mg2-composite-binding-2026-10-25/b1-clarification-mg1-look-receipt-2026-10-26.md`) and the L6_G
  disclosure (2026-10-29, `docs/research/gefs-members-l11-2026-10-26/b1-clarification-l6g-exemption-2026-10-29.md`).
- **Authority sought:** master. It answers finding D4-1 of the 2026-11-01 formal review, which master confirmed
  adversarially.
- **History only:** synthetic fixtures only. No outcome, label, price, market, 88a, panel or settlement row for
  any date was read to write this.
- **What changes:** how B's one look is invoked, which scorer sha VOID 2 and VOID 3 accept, and that a
  VOID 2 or 3 found before `look_guard` is a refusal, not a spent look. Nothing else changes: the estimand, the
  keep/kill rule, the markets, the dates, the interval, the bound hashes, the embargo and VOID 1, 4, 5, 6 and 7. No B-bound file is edited. This file is filed
  outside `docs/research/mg2-composite-binding-2026-10-25/` and does not edit `B_FORWARD_TEST_DESIGN.md`.

## 1. Why: D4-1, reproduced

References are to origin/master `3f3fe50a1f61ac37f225839b2bdc8f9fd0a1dcbf`.

- B-1 binds `b_scorer_sha256: f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439` (S0;
  `B_FORWARD_TEST_DESIGN.md` line 343).
- The 10-26 clarification §4 (lines 82-83) says the one permitted post-binding scorer edit sets
  `MG1_LOOK_ENTRY_SHA256`, giving S1. It says B's look runs at S1 and the control is re-run at the new sha.
- `b_scorer.py` as built cannot do that:
  - **VOID 2:** `bound_hash_problems` compares `module_sha256()` (S1) with the rule's S0 (lines 439-440).
  - **VOID 3:** `control_problems` compares a control re-run at S1 with the rule's S0 (lines 547-548).
  - **Left at S0, VOID 5 fires instead:** the sentinel `MG1_LOOK_ENTRY_UNRECORDED` (lines 132-133) matches no
    receipt (lines 523-526).
  - **The checker is not on the look path:** `b_scorer_entry_edit.py` is called by nothing on that path.
  - **A VOID spends the look:** `look_guard` writes the one-look markers (lines 398-407) before
    `_look_body` (line 720) evaluates any VOID.
  - **The tests miss it:** they fill `b_scorer_sha256` with the runtime sha and monkeypatch
    `MG1_LOOK_ENTRY_SHA256` (`tests/calibration/test_b_scorer.py` lines 60 and 86). No test binds a rule at S0
    while the file is at S1.
- **Red test:** `tests/calibration/test_b_look_end_to_end_s0_s1.py` at commit
  `b3dacb7afb179318093e80237b87cb2932352ecf`. It builds a synthetic end-to-end look inside `tmp_path`:
  - the rule bound at S0;
  - a temp copy of the scorer edited to S1 by exactly the permitted line, which `b_scorer_entry_edit` passes;
  - a receipt written by `mg1_look` running as the registered entry point;
  - a fixture git binding commit, a transfer, a drop list, and a control re-run at S1;
  - the look run through `look_guard`.

  No sha constant is monkeypatched. The result was:
  `VOID [2, 3]: '2': "... ['b_scorer_sha256']", '3': "... ['control ran at another scorer sha']"`.
  Every other bound hash and VOID 5 passed, so the fault is exactly D4-1.

## 2. Ruling sought: `b_scorer.py` keeps one permitted edit; a new pinned wrapper runs the look

- **The scorer edit:** `b_scorer.py`'s only permitted post-binding edit stays the `MG1_LOOK_ENTRY_SHA256` line
  (S0 to S1). This clarification adds no other scorer edit.
- **The look entry point:** B's one look runs only as
  `python -m weather.calibration.b_look_wrapper look --s0 <S0 bytes> <the b_scorer look arguments>`. The wrapper
  is a NEW module, not a B-bound file.
  - wrapper as reviewed (pre-S1, entry pin UNSET): `src/weather/calibration/b_look_wrapper.py`, sha256
    `95985e8018fc9c181bd69d44d5574da82511e4ec3197477206becfc0bc275c07`, at commit
    `2acf3954505affee29bfda60c0cdc5cbc9b1d090`;
  - S0 to S1 checker (unchanged; pinned by the wrapper): `src/weather/calibration/b_scorer_entry_edit.py`,
    sha256 `a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c`;
  - test: `tests/calibration/test_b_look_end_to_end_s0_s1.py`, sha256
    `48271dd2ff2ec35e4f67905199c1747f0fb1bb006cac040c5dcb1ed98e85118c`.
- **The wrapper sha the look runs at:** the commit that creates S1 (§5) changes one more line besides
  `b_scorer.py`'s constant: the wrapper's `MG1_LOOK_ENTRY_PIN`, set to the same value. So the look runs at a
  successor of the reviewed wrapper that differs from `95985e80…` in exactly that one line. The §5 clarification
  records that successor's sha256 and S1's sha256, and the look-chain closed list pins both (§6).
- **Running `python -m weather.calibration.b_scorer look` directly** is no longer an accepted look. Its markers
  would still consume the rule, so the look log must show the wrapper command. Deny-listing the direct command is
  deferred to master (§7).
- **S0 bytes:** `--s0` is any copy of `b_scorer.py` whose sha256 is the pinned S0, for example
  `git show 7da85e8cc3e9cecd00ab931cf5eca14ed12eb7a7:src/weather/calibration/b_scorer.py`. The wrapper checks the
  sha, so where the bytes come from does not matter.

## 3. What the wrapper pins and verifies, and what it accepts for VOID 2 and VOID 3

**Pins.** These are the wrapper's own constants, so changing one changes the wrapper's pinned sha:

| Constant | Value | Source |
| --- | --- | --- |
| `B1_RULE_SHA256` | `e8bad6e8ce9988180e41e5f9589e180326a8c1886f6043f182187de38a2a6030` | DECISION_LOG 2026-10-28 (line 281), equal to the bytes of `docs/operations/B_FORWARD_TEST_DESIGN.md` on master (test-pinned) |
| `B_SCORER_S0_SHA256` | `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439` | B-1 `b_scorer_sha256` (line 343) |
| `B_SCORER_ENTRY_EDIT_SHA256` | `a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c` | 10-26 clarification §4 |
| `MG1_LOOK_ENTRY_PIN` | `PIN_UNSET` (refuses) until the S1 commit | §5 |
| `ACCEPT_S0_CONTROL` | `False` | 10-26 clarification line 82; master's option (step 4) |

**Order.** The wrapper does these steps in order.

1. **MG-1 receipt first.** If MG-1's look receipt is absent, the wrapper refuses before anything else, as B-1 §9
   step 1 requires.
2. **Pins and S0 to S1.** All files are read once. The wrapper refuses, consuming nothing, unless all of these
   hold:
   - the rule file hashes to `B1_RULE_SHA256`. An edited rule has a new raw sha, so it would have a new
     `look_guard` marker key and could start a second look; it is refused (finding m2);
   - `--s0` hashes to `B_SCORER_S0_SHA256`;
   - `MG1_LOOK_ENTRY_PIN` is set;
   - `b_scorer_entry_edit.py` hashes to its pin and is executed from those bytes;
   - `s1_problems(S0, S1)` is empty;
   - the recorded value equals `MG1_LOOK_ENTRY_PIN`.

   S1 therefore cannot be re-edited to match whatever MG-1's receipt says without changing the wrapper's pinned
   sha (finding M1). A scorer left at S0 is refused ("S1 is identical to S0"), and so is any other edit.
3. **Execution from verified bytes.** Only after step 2 are the verified S1 bytes compiled (`compile`, so no
   `.pyc` is used) and executed as a fresh module. `b_scorer` is never imported first. The wrapper then checks:
   - the file still hashes to S1;
   - the rule's `b_scorer_sha256` is S0.

   The running scorer is exactly the verified bytes (finding m1).
4. **VOID 2 and VOID 3 acceptance.** While the look runs:
   - `bound_hash_problems` reads S1 for `b_scorer_sha256`, and only for that field. Every other bound hash is
     checked unchanged.
   - `control_problems` accepts a PASS control made at S1. The receipt is accepted at S0 only when
     `ACCEPT_S0_CONTROL` is True. Its scorecard sha and verdict are checked unchanged.
   - **Default, S1 only:** this follows the 10-26 clarification line 82, "re-run at the new scorer sha". The
     existing `bcontrol4` (`17b293a7…`, PASS at S0; 10-26 clarification §6 lines 128-129) is then not accepted,
     and the control is re-run at S1 on the dev window before the look.
   - **Master's option:** accept `bcontrol4` at S0. The S0-to-S1 diff is one constant that the control path never
     reads. Choosing this is a reviewed one-line change of `ACCEPT_S0_CONTROL`, which changes the wrapper sha.
5. **Receipt.** After `b_scorer.look` returns, the wrapper writes `b_look_wrapper_receipt.json` beside B's
   receipt (mode "x", LF). It holds:
   - the wrapper sha and `accept_s0_control`;
   - the rule sha;
   - the entry-edit verdict (S0, S1, recorded entry sha, checker sha);
   - the sha of MG-1's receipt;
   - the preflight inputs (the shas of MG-2's rule, the release binding, `mg2_look.json`, the vectors and the
     control, plus the control's made-at scorer sha);
   - the sha of B's look receipt and B's decision.

   If an exception escapes after this call consumed the look, the wrapper writes the same receipt with
   `b_decision` ABORTED and re-raises (finding m4). A refusal by `look_guard` before it consumes the look writes
   no wrapper receipt.

- **How it is implemented:** the wrapper swaps the executed module's `bound_hash_problems` and
  `control_problems` for scoped versions for the duration of the call, and restores them afterwards
  (test-pinned). `b_scorer.py`'s bytes are untouched.
- **What reviewers should check:** this is in-process substitution of two functions. The pinned wrapper sha is
  what makes it auditable.
- **What the look record shows:** B's own `b_look.json` and receipt record `b_scorer_sha256` = S1, because that
  is the running scorer. The wrapper receipt ties S1 back to the bound S0.

## 4. Preflight: which VOIDs are refused before `look_guard`

- **The constraint:** `look_guard` writes the fixed marker before `_look_body` evaluates any VOID. That cannot
  change without editing `b_scorer.py`.
- **What the wrapper does instead:** before calling `b_scorer.look`, inside the step 4 acceptance, it evaluates
  VOID 2 and VOID 3 with `b_scorer`'s own `bound_hash_problems` and `control_problems`. If either fails, the
  wrapper refuses, `look_guard` does not run, and nothing is written.
- **What the preflight reads:**
  - the rule and MG-2's rule;
  - the release binding and the git blobs at the binding commit;
  - `mg2_look.json`;
  - the bytes of the forward vectors and of the emit audit beside them;
  - the dev control receipt.

  It never reads a B date's label or price, and it opens no transfer file. It does hash the forward vectors
  (`b_scorer.py` lines 431 and 443-447), so it is not "code bytes only".
- **VOID 5 is not in the preflight.**
  - An MG-1 entry-sha mismatch is the 10-26 §4 tripwire: MG-1 was looked at with code other than the code
    pre-recorded.
  - With the entry pin in place, a non-spending refusal would leave no repair route except editing the pinned
    wrapper. It would also leave no record that the tripwire fired, and its message would disclose the receipt's
    entry sha.
  - Letting `b_scorer.look` evaluate it and spend the dates is the tighter choice. It records the VOID
    permanently and keeps B-1 §6 intact for VOID 5 (test-pinned).
- **Every other VOID spends the dates through `b_scorer.look`, as before:** VOID 1, VOID 4, all of VOID 5,
  VOID 6 and VOID 7.
- **Where it departs from B-1:** it does depart from B-1 §6 ("VOID: the dates are spent") for VOID 2 and VOID 3
  found before `look_guard`.
- **Master rules** whether to accept the preflight. Proposed wording for B-1 §6 if it is accepted: "A preflight
  refusal by `b_look_wrapper` at the sha pinned in Clarification 3 (as amended by the §5 commit) is not a look: no
  consumed marker, `b_look.json` or B look receipt exists, and no transfer file was opened. Once `look_guard` has
  written the fixed marker, every VOID, 2, 3 and 5 included, spends the dates."
- **If master rejects it:** delete `preflight` from the wrapper (a reviewed sha change). D4-1 is still closed by
  §3, and B-1 §6 stands unamended.
- **Tests:**
  - a control at a third sha, and a control at S0 under the default, are refused with no marker or output;
  - the same look then scores once the control is re-receipted at S1;
  - an `mg2_look.json` rule-sha mismatch (a non-scorer bound hash) gives exactly `bound_hash_problems`' own list,
    `['mg2_look.rule_sha256']`, and nothing is spent;
  - VOID 4, a VOID 5 entry mismatch, and an abort after consumption all spend the look.

## 5. Timing: is the entry sha set before the MG-1 look, or after its receipt?

- **Reading A, before the MG-1 look.** Sources:
  - the 10-26 clarification §4 lines 74-78: the scoring addition's "commit sha recorded in a dated B-1
    clarification BEFORE the MG-1 look (MG1_LAST 11-28)", and that clarification's commit sets the constant;
  - the `b_scorer.py` comment, lines 127-131, which says the same.
- **Reading B, after MG-1's receipt exists.** Sources:
  - the look-day checklist (`docs/research/b-look-prep-2026-10-31/look-day-dry-run-checklist.md` on
    `origin/claude/b-look-prep-20261031-retip-r2` `6ee5d1ce15ab726818ea6f1e356eeadc6d6d10ee`, lines 41-45):
    "Master writes the dated B-1 clarification that sets the constant once MG-1's look receipt exists
    (2026-11-29..12-12)", citing master ruling (iii) of 2026-10-31;
  - the look-chain draft §5 on the same branch.
- **What the two readings share:** under both, the value is the re-registered `mg1_look.py` source sha256. That
  sha is known as soon as the master-reviewed scoring addition lands, before any MG-1 outcome exists.
- **Under either reading, one commit:**
  - sets `b_scorer.py`'s constant (S1) and the wrapper's `MG1_LOOK_ENTRY_PIN` to the same value;
  - records the `python -m weather.calibration.b_scorer_entry_edit --s0 <S0> --s1 <S1>` output;
  - records the new S1 and wrapper sha256s.
- **Recommendation: Reading A.**
  - It fixes VOID 5's expected entry point before any MG-1 outcome is joined.
  - Under Reading B the value is chosen after the receipt exists and can be copied from it, so the entry check
    cannot fail by construction (the pin binds S1 to the wrapper, but both are set after the fact). Only
    `mg1_look.receipt_problems`' registered-sha check is left.
  - Reading A also leaves time for the S1 control re-run (§3 step 4, default) and a synthetic dry run through the
    pinned wrapper before 12-13.
- **Master rules.**

## 6. Fix to the look-chain DRAFT's closed list

- **Where the draft lives:** `docs/research/b-look-prep-2026-10-31/look-chain-clarification-DRAFT.md`, on
  `origin/claude/b-look-prep-20261031-retip-r2`, not on master. It is not edited here, to avoid a conflicting copy.
- **What is wrong:** its row 2 names `python -m weather.calibration.b_scorer look` pinned at `f941628a…`. That
  cannot score (§1).
- **Replacement row 2:**

| # | Step | Entry point | Pinned sha256 | Reads | Writes |
| --- | --- | --- | --- | --- | --- |
| 2 | B look | `python -m weather.calibration.b_look_wrapper look --s0 <S0>` | wrapper = the §5 successor of `95985e8018fc9c181bd69d44d5574da82511e4ec3197477206becfc0bc275c07` (one line: `MG1_LOOK_ENTRY_PIN`), sha recorded by the §5 commit; `b_scorer.py` S1 = the entry-edit-verified successor of S0 `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439`, sha recorded by the §5 commit; `b_scorer_entry_edit.py` `a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c` | B-1 §9 inputs, the one transfer, the S0 bytes | `b_look.json`, `b_look_receipt.json`, `b_look_wrapper_receipt.json`, consumed markers |

- **Draft §3, the extractor bullet:** "the running `b_scorer` sha equals the one B's look recorded" stays
  correct. Both are S1, and `b_look_per_date` compares `b_look.json`'s `b_scorer_sha256` with the running
  `module_sha256()`.
- **Draft §5:** the sentence about the sentinel should cite this clarification's §5 ruling.

## 7. Scope limits and follow-ups

- **No B-bound file was edited, and none needs to be.** The one residual that only a B-bound edit could remove is
  the marker order inside `look_guard`. §4 works around it from outside.
- **Deferred to master (M3, M4):** the wrapper has no entry yet in the three mirrored offline-module lists:
  - `.codex/hooks/pre_tool_use_host_load.py`;
  - `scripts/ops/workload_admission.ps1`;
  - `tests/operations/test_r0_full_year_admission.py`.

  As a result `workstation_heavy.ps1` refuses it. Once it is admitted, a direct `b_scorer look` should be denied
  there. Add the entries only on master's direction, as for `b_look_per_date`
  (`d33921025266c0e96794857640da53e5a3272787`).
- **Evidence:**
  - red: commit `b3dacb7afb179318093e80237b87cb2932352ecf` (§1);
  - green: commit `2acf3954505affee29bfda60c0cdc5cbc9b1d090`, run through `workstation_heavy.ps1 -Queue`, gave 23
    passed in the test file. With the hygiene ratchet, import-architecture and entry-edit tests it was 125 passed.
