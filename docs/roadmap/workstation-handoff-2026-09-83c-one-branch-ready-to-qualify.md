# Workstation handoff 2026-09-83c — close the 83b leftovers and hand production one qualified stack

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Follows mission `2026-09-83b`: Part A `codex/nbm-target-fix-20260921` @ `2e17ce0eb`, Part B
`codex/nbp-bulletin-reuse-20260921` @ `62e8ff044`. Both handbacks are accepted as **PARTIAL, stopped correctly**; the
code was reviewed by the production agent and is accepted as built, subject to the small items below. `2026-09-83c` is
a mission label.

## 1. Goal

Every remaining blocker in 83b was a file outside the mission's ownership. This mission grants that ownership, then
asks for the merge conflicts to be resolved on the workstation, where the full suite may run, so that the production
host qualifies finished branches instead of resolving conflicts at night.

**No forecast candidate is proposed or scored in this mission.**

## 2. Start from this — do not re-derive it

- Three research branches are stacked, each containing the one before it: `codex/missing-information-checks-20260921`
  (79a) ⊂ `codex/morning-guidance-candidate-20260921` (81a) ⊂ `codex/nbm-target-trace-20260921` (82a, `2e8406366`).
  None is on `master` yet. The 82a tip already reconciles
  `test_workstation_offline_allowlist_narrowly_admits_cold_archive_stage_and_restore` by admitting an **exact set** of
  three `tools.research.*.run` module names beside the `weather.` prefix rule. That exact-name pattern is the accepted
  precedent.
- Part A adds its own allowlist line for `tools.research.nbm_target_fix` but not the matching test entry, and its tool
  is a top-level script under `tools/research/`, so the research-tool inventory test sees it. Those are the two
  full-suite failures.
- A trial merge on the production host (`git merge-tree`, nothing written) found these content conflicts. Research
  stack with Part A: `.codex/hooks/pre_tool_use_host_load.py`, `scripts/ops/workload_admission.ps1`,
  `tests/operations/test_codex_host_load_hook.py`. Part A with Part B: `src/weather/model/model_sources.py`, and an
  add/add on the 83b report, because the 83b handoff gave both parts the same report file name (the production
  agent's error).
- In `model_sources.py` A wraps the NBM parse in a `try` and B adds `cycle_age_at_use_hours` just after it. They
  conflict textually, not in intent.
- `origin/master` is `e28530af6`.

## 3. Decisions made by the production agent

- **Ownership granted for this mission:** `tools/research/research_harness.py` (the `SCRIPT_INVENTORY` entry only),
  `tests/operations/test_workload_admission_script.py` (the exact-name set only), and
  `src/weather/operations/storage_classes.py` (the one new family only) with their tests and owning documents.
- The allowlist test is reconciled by **adding the exact module name to the exact-name set**, as 82a did. Never a
  prefix, never a wildcard, never `tools.` as a whole.
- The inventory entry uses a **network-free** smoke kind that already exists in `SCRIPT_INVENTORY`. Do not add a new
  smoke kind.
- The storage family is registered exactly as your Part B report specifies: `forecast_payload_cas/nbp_cycle_index/**/*.json`,
  class `analysis_projection`, rebuildable from the original receipt and verified blob, deletion only by a reviewed
  exact-path cleanup manifest.
- Keeping feature schema v1.17 is accepted for the reason you gave.

## 4. Work

### 4.1 Three branches, each a superset of the one before, each from `origin/master`

| Branch | Contents | Expected roll class |
| --- | --- | --- |
| `codex/integrate-1-research-20260921` | `origin/master` + merge of `codex/nbm-target-trace-20260921` | roll-free (say if the tool disagrees) |
| `codex/integrate-2-parser-20260921` | integrate-1 + merge of Part A + the two test/inventory repairs | roll-sensitive |
| `codex/integrate-3-reuse-20260921` | integrate-2 + merge of Part B + the storage registration | roll-sensitive |

Use merge commits; do not rebase or rewrite any existing branch, and leave the five source branches as they are. The
production host will adopt one layer at a time, so **each layer must stand alone**: full suite green at each tip.

Conflict rules: in the allowlist, the host-load hook, the exact-name test set and the hook test, keep **every**
branch's entries (union), one per line, no duplicates. For the 83b report, keep both: on integrate-3 rename Part B's
copy to `agent-report-2026-09-83b-workstation-finish-the-guidance-repair-part-b.md` and fix the links to its receipts.
In `model_sources.py`, keep A's `try`/`NBPClockError` handling and B's `cycle_age_at_use_hours`; a clock-rejected payload carries `issued_at`, so it must also receive
`cycle_age_at_use_hours`. Add one test on integrate-3 that the combined call site does both on a reused bulletin: a
version-2 parse, truthful reuse attribution, original-capture `cycle_age_hours` in the raw wrapper and use-time age in
the diagnostic feature.

### 4.2 Small repairs found in review

- **Part A, `tools/research/nbm_target_fix.py::window`:** `healthy_unavailable` is printed as a literal `0`. Compute it
  from the rows (an empty candidate list must produce a row marked unavailable and be counted, not an `IndexError`).
  Re-generate `window.csv` only if its content changes.
- **Part B, cost on a real bulletin.** The probes used a 39 KB fixture and a 1 MB padded body. On the capture host every
  reuse runs `_complete_nbp` over the full national text and re-hashes the blob, 11 markets per pass. Using one
  national file you already hold from 83a's cache (**do not download one**), measure for a single reuse: wall seconds
  and `tracemalloc` peak for (a) blob read and hash, (b) `_complete_nbp`, (c) the whole `fetch_reusable_nbp` call; and
  the same for today's path with the download stubbed to return the same bytes. Report the table. **If (b) exceeds one
  second, skip the re-scan on the reuse path** — the index was written only after the scan passed, its key binds the
  policy and station set, and the hash binds the bytes — keep the scan on first fetch, and add a test that a blob whose
  hash does not match the index is never reused. If (b) is under one second, change nothing.
- **Part B, `_nbp_reuse_stations()`** is evaluated up to five times per fetch. Evaluate it once per call and pass it
  down. State whether `all_specs()` reads from disk on each call.

### 4.3 Checks, at each of the three tips

Full suite through `scripts/ops/workstation_heavy.ps1` with a fresh `--basetemp` you delete afterwards; compileall;
docs audit; roadmap check; the parity CLI on integrate-2 and integrate-3 (the accepted BLOCK: four of four known, zero
unexpected, zero coverage blockers — anything else is a finding); `scripts/ops/roll_verdict.ps1 -Branch <b> -Base
origin/master` output retained even though the workstation cannot decide it.

## 5. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. As in 83a and 83b: no candidate, fit, score or
outcome read; never weaken or bypass the observed-high floor; nothing under `artifacts/`; no network weather request
at all in this mission; no credentials, no exchange calls; if a gate fails, report it and its cause, never relax or
re-baseline it; push the three branches, never merge to `master`. Mission `2026-09-80b` is still running on the
workstation on its own branch: do not merge it into these branches, and if it holds the heavy-work mutex, wait for it.

## 6. What would stop or change the plan

- A conflict outside the files named in section 2 => stop at that layer, push what is green, report the file.
- The full suite fails at integrate-1 for a reason that exists on `origin/master` too => report it as a master defect
  with the test name; do not repair it here.
- A third full-suite failure appears at integrate-2 or integrate-3 => report; repair only if it is inside the files
  this mission owns.

## 7. Report

`docs/roadmap/agent-report-2026-09-83c-workstation-one-branch-ready-to-qualify.md` on integrate-3 (or the highest layer
reached), per contract §5: verdict first in bold, per layer (READY FOR HOST QUALIFICATION / PARTIAL and why / BLOCKED
and why); the three tip hashes; full-suite counts per tip; every conflict and how it was resolved, file by file; the
Part B cost table and what you did about it; the roll tool output per tip; what was NOT done; reproduction commands.
