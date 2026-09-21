# Workstation handoff 2026-09-83d — bind the 82a trace to the old parser and finish layers 2 and 3

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21. Successor to
`2026-09-83c`, whose handback is accepted: **layer 1 (`codex/integrate-1-research-20260921` @ `c04200081`) is READY FOR
HOST QUALIFICATION; layers 2 and 3 stopped correctly.** The production agent confirmed the cause on the pushed
branches. The 83c handoff's trial merge checked text conflicts only, not imports across branches; that gap was the
production agent's. `2026-09-83d` is a mission label.

**Priority: mission `2026-09-84b` (the attended reward test) goes first on this workstation.** Do not take the
heavy-work mutex while 84b is waiting for it or using it. This mission's focused tests are small; its two full suites
run only when 84b does not need the mutex. The production host adopts layer 1 tonight whatever happens here.

## 1. Start from this — do not re-derive it

- `tools/research/nbm_target_trace/run.py` line 25 imports `_slot_index_for_target`; Part A renamed it
  `_slot_index_for_target_v1`. `tests/reporting/test_nbm_target_trace.py` imports the tool, so collection fails on
  `codex/integrate-2-parser-20260921` (`c6c58155f`) and `codex/integrate-3-reuse-20260921` (`19e99a683`).
- Your reading is right and is adopted: an alias in the live parser would hide a change of meaning. The trace's T1 stage
  (lines 228-229) calls `parse_nbp_station_tmax`, which on these layers defaults to version 2, while deriving the chosen
  group with the version-1 helper and hard-coding token 0. The 82a study measured the **version-1** parser; its tool
  must keep doing so explicitly. The live default stays version 2.
- The tool retains 132 station blocks and `evidence/picks.csv` (the T1 table). Those make a network-free check possible.

## 2. Ownership granted for this mission

`tools/research/nbm_target_trace/run.py` (the parser binding in the import and the T1 stage only),
`tools/research/nbm_target_trace/README.md` (the sentence that says which parser T1 calls),
`tests/reporting/test_nbm_target_trace.py` (additions only; existing tests stay unchanged). Nothing else in the
research tools, and nothing under `tools/research/nbm_target_trace/evidence/`.

## 3. Work

1. On `codex/integrate-2-parser-20260921`, make T1 bind version 1 explicitly for **both** calls: the payload parse
   (`parse_nbp_station_tmax_v1`, or `parser_version=1`) and the group helper (`_slot_index_for_target_v1`). Prefer
   explicit names at the call sites over local aliases, so a reader sees which rule the study measured. Change the
   README sentence from "the unchanged repository parser" to say version 1, the rule in production when 82a ran.
2. Add one test, network-free: for every retained block and the three target offsets, the version-1 binding reproduces
   the parser-derived columns of the retained `picks.csv` exactly — `chosen_group`, `chosen_token`, `valid_time_utc`,
   `period_kind`, `period_date`, `p50`, `reason`, and `classification` — for all 396 rows. Do not call `observations()`
   or any fetch; if `classification` cannot be derived without observations, derive it from the same fields T1 uses and
   say so. **If any row differs, stop: that means Part A's `_v1` functions are not the rule 82a measured, which is a
   finding about Part A, not something to fix in the test.**
3. Add one small test that the tool does not reach the version-2 default: T1's parse of the retained 13Z KLGA block for
   the local issue date returns the version-1 reading that 82a recorded as wrong, not the version-2 reading.
4. Merge the repaired layer 2 into `codex/integrate-3-reuse-20260921` with a merge commit (no rebase; the pushed tips
   stay ancestors). Do not re-run the 82a study and do not regenerate its evidence.
5. Checks at each of the two tips, as in 83c section 4.3: full suite through `scripts/ops/workstation_heavy.ps1` with a
   fresh `--basetemp` you delete afterwards, compileall, docs audit, roadmap check, the parity CLI (the accepted BLOCK:
   four of four known, zero unexpected, zero coverage blockers), and the roll tool's output retained. The collection
   error hid everything behind it, so **this is the first time these two layers run the suite at all**: report every
   failure. Repair only what lies inside files owned by missions 83a, 83b, 83c or this one; report the rest with its
   cause.

## 4. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full, with every 83c boundary unchanged: no candidate,
fit, score or outcome read; never weaken the observed-high floor; nothing under `artifacts/`; no network weather
request; no credentials or exchange calls; a failing gate is reported, never relaxed; push, never merge to `master`. Do
not merge missions 80b or 84a/84b into these branches. Layer 1 is frozen at `c04200081`: do not add commits to it.

## 5. What would stop or change the plan

- A `picks.csv` row does not reproduce under version 1 => stop; report the rows and both values.
- The full suite on layer 2 shows a failure outside owned files => report; push what you have; layer 3 still gets its
  own run so the production agent sees the whole list at once.

## 6. Report

Append a dated 83d section to the 83c report on `codex/integrate-3-reuse-20260921` (do not rewrite the 83c text):
verdict first in bold, per layer; the two new tip hashes and the exact commits the suites ran on; full-suite counts;
the 396-row reproduction result; every failure seen with its cause; the roll tool output; what was NOT done.
