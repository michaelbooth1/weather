# Rule B-1 Clarification 3 (DRAFT): the look runs at S1 through a pinned wrapper, 2026-11-01

- **Status:** DRAFT by lane L22 for master's ruling and adversarial review (d). Not in force, not signed, and not
  an owner decision. Numbered 3 after the two dated B-1 clarifications: the MG-1 look receipt (2026-10-26,
  `docs/research/mg2-composite-binding-2026-10-25/b1-clarification-mg1-look-receipt-2026-10-26.md`) and the L6_G
  disclosure (2026-10-29, `docs/research/gefs-members-l11-2026-10-26/b1-clarification-l6g-exemption-2026-10-29.md`).
- **Authority sought:** master. It answers finding D4-1 of the 2026-11-01 formal review, which master confirmed
  adversarially.
- **History only:** synthetic fixtures only. No outcome, label, price, market, 88a, panel or settlement row for
  any date was read to write this.
- **What changes:** how B's one look is invoked, which scorer sha VOID 2 and VOID 3 accept, and when a mechanical
  VOID spends the look. Nothing else changes: the estimand, the keep/kill rule, the markets, the dates, the
  interval, the bound hashes, the embargo and VOID 1, 4, 6 and 7. No B-bound file is edited. This file is filed
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
  is a NEW module and is not a B-bound file.
  - wrapper: `src/weather/calibration/b_look_wrapper.py`, sha256
    `7a2672d20c0490966e10d488f61d3087dd90a13ad138c12b78e8f71824a4fcd4`, at commit
    `5f5ca5129b3707a4869b626508d6a589618972da`;
  - S0 to S1 checker (unchanged): `src/weather/calibration/b_scorer_entry_edit.py`, sha256
    `a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c`;
  - test: `tests/calibration/test_b_look_end_to_end_s0_s1.py`, sha256
    `bbc1a3f28bedc1ec7014263a7d5fe03cd04371381990a27fad9b4a61b6874109`.
- **Running `python -m weather.calibration.b_scorer look` directly** is no longer an accepted look. Its markers
  would still consume the rule, so the look log must show the wrapper command.
- **S0 bytes:** `--s0` is any copy of `b_scorer.py` whose sha256 equals the rule's `b_scorer_sha256`, for
  example `git show 7da85e8cc3e9cecd00ab931cf5eca14ed12eb7a7:src/weather/calibration/b_scorer.py`. The wrapper
  checks the sha, so where the bytes come from does not matter.

## 3. What the wrapper verifies, and what it accepts for VOID 2 and VOID 3

The wrapper does these steps in order.

1. **MG-1 receipt first.** If MG-1's look receipt is absent, the wrapper hands straight to `b_scorer.look`.
   `look_guard` refuses first, as B-1 §9 step 1 requires, and consumes nothing.
2. **S0 to S1.** The wrapper refuses, consuming nothing, unless all of these hold:
   - the `--s0` bytes hash to the rule's `b_scorer_sha256`;
   - the running scorer's file bytes are its `module_sha256()`;
   - `b_scorer_entry_edit.s1_problems(S0, S1)` is empty: exactly the one assignment line changed, set to a 64-hex
     literal;
   - the recorded value equals the running `MG1_LOOK_ENTRY_SHA256`.

   A scorer left at S0 is refused here ("S1 is identical to S0"). So is any other edit.
3. **VOID 2.** While the look runs, `bound_hash_problems` reads that verified S1 for `b_scorer_sha256`, and only
   for that field, when the rule holds S0. Every other bound hash is checked unchanged.
4. **VOID 3.** A PASS control receipt is accepted when it was made at S0 or at that verified S1. Its scorecard
   sha and verdict are checked unchanged.
   - This makes VOID 3 consistent with the 10-26 clarification line 82, which says the control is re-run at S1.
   - It also accepts the existing S0 receipt `bcontrol4` (`17b293a7…`, PASS at `f941628a…`; 10-26 clarification
     §6). Master rules whether a re-run at S1 is still required. The recommendation is not required: the
     S0-to-S1 diff is one constant that the control code never reads.
5. **Receipt.** After `b_scorer.look` returns, the wrapper writes `b_look_wrapper_receipt.json` beside B's
   receipt, in mode "x". It holds S0, S1, the recorded MG-1 entry sha, the `b_scorer_entry_edit` sha, the wrapper
   sha, the rule sha, the sha of B's look receipt and B's decision.

- **How it is implemented:** the wrapper swaps `b_scorer.bound_hash_problems` and `b_scorer.control_problems` for
  scoped versions for the duration of the call, and restores them afterwards (test-pinned). `b_scorer.py`'s bytes
  are untouched.
- **What reviewers should check:** this is in-process substitution of two functions. The pinned wrapper sha is
  what makes it auditable.
- **What the look record shows:** B's own `b_look.json` and receipt record `b_scorer_sha256` = S1, because that
  is the running scorer. The wrapper receipt ties S1 back to the bound S0.

## 4. Markers are not spent by a mechanical VOID

- **The constraint:** `look_guard` writes the markers before any VOID is evaluated. That cannot change without
  editing `b_scorer.py`, so the wrapper cannot reorder it.
- **What the wrapper does instead:** it runs a preflight BEFORE calling `b_scorer.look`, inside the step 3-4
  acceptance and using `b_scorer`'s own functions. The preflight reads no label, price or transfer file.
- **Mechanical conditions (refused, nothing written or consumed):** each depends only on code bytes, the dev
  control receipt or the recorded MG-1 entry sha, never on a B date's data.
  - VOID 2, every bound hash;
  - VOID 3;
  - VOID 5's entry-sha check alone: the receipt's `entry_point.source_sha256` differs from the running
    `MG1_LOOK_ENTRY_SHA256`.
- **Substantive conditions (left to `b_scorer.look`, which spends the look as before):** VOID 1, VOID 4, the rest
  of VOID 5 (a hand-made or edited receipt, an unbound receipt, a transfer not after `looked_at_utc`), VOID 6 and
  VOID 7.
- **Why this is safe:** a preflight refusal reveals nothing about any outcome, so fixing the wiring and re-running
  cannot be steered by results.
- **Where it departs from B-1:** it does depart from B-1 §6 ("VOID: the dates are spent") for these three
  conditions. **Master rules** whether to accept the preflight. The alternative is to delete the preflight and
  keep "any VOID spends the look". If the preflight is rejected, D4-1 is still closed by §3, and the proposed
  wording for B-1 §6 is: "A VOID that `b_look_wrapper`'s preflight would raise is a refusal, not a look; every
  other VOID spends the dates."
- **Tests:**
  - a control at a third sha is refused, no marker or output is written, and the same look then scores once the
    control is fixed;
  - a recorded pre-look read (VOID 4) still spends the look.

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
- **Recommendation: Reading A.**
  - It fixes VOID 5's expected entry point before any MG-1 outcome is joined.
  - Under Reading B the constant is filled after the receipt exists, so it can be copied from the receipt itself.
    The entry-sha check then cannot fail by construction, and only `mg1_look.receipt_problems`' registered-sha
    check is left.
  - Reading A also gives S1 two weeks to be dry-run through the wrapper on synthetic inputs before 12-13.
- **Reading B stays workable:** the wrapper behaves the same under it.
- **Under either reading:**
  - the S1 commit records `python -m weather.calibration.b_scorer_entry_edit --s0 <S0> --s1 <S1>` output, as the
    10-26 clarification §4 requires;
  - the wrapper re-verifies it at the look.
- **Master rules.**

## 6. Fix to the look-chain DRAFT's closed list

- **Where the draft lives:** `docs/research/b-look-prep-2026-10-31/look-chain-clarification-DRAFT.md`, on
  `origin/claude/b-look-prep-20261031-retip-r2`, not on master. It is not edited here, to avoid a conflicting copy.
- **What is wrong:** its row 2 names `python -m weather.calibration.b_scorer look` pinned at `f941628a…`. That
  cannot score (§1).
- **Replacement row 2:**

| # | Step | Entry point | Pinned sha256 | Reads | Writes |
| --- | --- | --- | --- | --- | --- |
| 2 | B look | `python -m weather.calibration.b_look_wrapper look --s0 <S0>` | wrapper `7a2672d20c0490966e10d488f61d3087dd90a13ad138c12b78e8f71824a4fcd4`; `b_scorer.py` S1 = the entry-edit-verified successor of S0 `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439` (S1's own sha is recorded by the §5 clarification); `b_scorer_entry_edit.py` `a08c1eaa09d26d38e0481dfcd651d7dc46d11ce524ca29d913bb4a1a50a0005c` | B-1 §9 inputs, the one transfer, the S0 bytes | `b_look.json`, `b_look_receipt.json`, `b_look_wrapper_receipt.json`, consumed markers |

- **Draft §3, the extractor bullet:** "the running `b_scorer` sha equals the one B's look recorded" stays
  correct. Both are S1, and `b_look_per_date` compares `b_look.json`'s `b_scorer_sha256` with the running
  `module_sha256()`.
- **Draft §5:** the sentence about the sentinel should cite this clarification's §5 ruling.

## 7. Scope limits and follow-ups

- **No B-bound file was edited, and none needs to be.** The one residual that only a B-bound edit could remove is
  the marker order inside `look_guard`. §4 works around it from outside.
- **Offline-module admission:** the wrapper has no entry yet in the three mirrored lists:
  - `.codex/hooks/pre_tool_use_host_load.py`;
  - `scripts/ops/workload_admission.ps1`;
  - `tests/operations/test_r0_full_year_admission.py`.

  Add the entries only on master's direction, as for `b_look_per_date` (d33921025266c0e96794857640da53e5a3272787).
- **A crash inside `b_scorer.look`:** the look ends ABORTED, B's receipt is written as before, and no wrapper
  receipt is written.
- **Green evidence:** the same test file at `5f5ca5129b3707a4869b626508d6a589618972da`, run through
  `workstation_heavy.ps1 -Queue`, gave 12 passed:
  - the end-to-end look scores PASS through the wrapper;
  - D4-1 stays pinned on the direct path (VOID [2, 3] at S1, VOID [5] at S0);
  - the four refusals consume nothing.
