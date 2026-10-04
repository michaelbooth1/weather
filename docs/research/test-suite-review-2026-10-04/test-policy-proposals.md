# Proposals: test policy and anti-regrowth (test-suite review K, role 21)

Status: **decided by the owner on 2026-10-04** (see the [decision log](../../operations/DECISION_LOG.md)).
P1 kept (the ratchet lands with PR #205). P2 **approved with a condition**: it takes effect only once a CI
Windows lane covers the Windows-only tests CI never runs today (about 303 cases, including the reconciler's
70); until then a local full suite stays required for changes touching Windows-executing scripts. P3, P4 and P5
approved. P3's mechanism (hook exemption, FIFO queue, wait log) is an explicit follow-up. The adopted text lives
in [development.md](../../development.md), [HOST_LOAD_POLICY.md](../../operations/HOST_LOAD_POLICY.md),
[WORKSTATION_SESSION_PREAMBLE.md](../../operations/WORKSTATION_SESSION_PREAMBLE.md) and
[tests/AGENTS.md](../../../tests/AGENTS.md); this file is the record and is historical evidence from now on.

Evidence comes from the other K roles. Raw data lives outside the repository in
`C:\wt\workstation-chat\k-data\<role>\` on the workstation (not durable; the role-22 report will carry the
numbers that matter).

## Decisions requested (as submitted)

| # | Proposal | Owner of the text if approved | Effect |
| --- | --- | --- | --- |
| P1 | Anti-regrowth ratchet (four mechanical rules, one guideline) | `tests/AGENTS.md`, `tests/hygiene_ratchet.py` | Blocks new instances only; today's 1,628 counted instances are baselined |
| P2 | Definition of done: focused + affected tests locally, CI as full-suite evidence | `docs/development.md` | Removes the local full run that duplicates CI |
| P3 | Workstation lease: small focused runs exempt; full suites queue FIFO with a wait log; xdist only on the workstation | `docs/operations/HOST_LOAD_POLICY.md`, `scripts/ops/workstation_heavy.ps1` | Ends lease starvation; capture-host rules unchanged |
| P4 | Preamble wording to match P2 and P3 | `docs/operations/WORKSTATION_SESSION_PREAMBLE.md` | Wording only |
| P5 | Mutation-informed assertion guideline | `tests/AGENTS.md`, `docs/development.md` | Guidance for new and edited tests |

Each can be approved alone. P4 depends on P2 and P3. P3's xdist clause depends on role 11's result.

## P1. Anti-regrowth ratchet

**Problem.** The suite grew by accretion: 465 modules, about 7,250 cases. Role 7 found 2,030 static `.ps1`
text-substring asserts in 43 files (one such pattern hid an inert kill path for 27 days, EF §10g), 494
private-helper coupling sites, and 651 tests that start a process (552 of them PowerShell; P0-2). P0-1 found
that **no test file cites an EF, RF or HWGTW id**: the incident each test guards is recorded nowhere near
the test, which is why the review had to reconstruct it doc-side. Nothing stops any of these from growing.

**Mechanism.** `tests/hygiene_ratchet.py` counts four rules per test module with Python `ast` (no regex over
code). `tests/hygiene_ratchet_baseline.json` records today's counts. `tests/test_hygiene_ratchet.py` fails only
when a module's count rises above its baseline entry; a module with no entry is allowed 0. **Lowering a count
never fails**, and deleting a file never fails (a renamed file is a new path and must comply). That is deliberate: in P0-3's 7-day CI window
inventory ratchets fired at 22 commits, every time for an inventory reason rather than a real defect, so a new
ratchet must not add a stale-entry failure mode. `python -m tests.hygiene_ratchet --tighten` records a decrease; `--report` prints counts.
Raising a baseline entry is a reviewed decision, visible in the diff.

| Rule | Counts | Baseline today |
| --- | --- | ---: |
| `guards_declaration` | module docstring has no `Guards:` line (1 per module) | 465 modules (all) |
| `ps1_substring_without_execution` | asserts probing text read from a `.ps1` (`in`, `count`, `find`, `startswith`, `re.search`...) in a module that never runs PowerShell | 810 asserts in 19 modules |
| `private_src_import` | `_name` imported from `src/` packages or `app` (`from weather.x import _y`, `import weather._x`) | 99 in 44 modules |
| `unmarked_spawning_test` | test functions that start `git` or PowerShell (directly, through a same-module helper or fixture, or an autouse fixture) without `pytest.mark.spawns` | 254 tests in 49 modules |

Detector checks: the PowerShell/git spawn detection reproduces P0-1's census exactly (all 39
PowerShell-spawning and all 21 git-fixture files) and adds 4 files that run `git ls-files` or similar; the
private-import count equals role 7's `from_import` count (99). The `.ps1` count is lower than role 7's 2,030
because modules that also execute PowerShell are exempt by the rule's definition (1,794 text asserts in 40
modules before that exemption).

**Conventions chosen (lightest workable):**

- *Guards tag.* One docstring line, `Guards: <what>`, where `<what>` names an EF/RF/HWGTW id, an incident, an
  owning document section, or a contract (at least 8 characters). A docstring was chosen over a `GUARDS = ...`
  constant because it costs no runtime name, reads naturally, and survives every linter. The ratchet checks
  presence, not truth; review checks truth.
- *Execution twin.* A module that runs PowerShell (a `subprocess` call with a PowerShell command line, or the
  shared host from PR #201) may still assert on script text. The rule is module-level on purpose: per-script
  pairing cannot be resolved statically without false failures.
- *Cost marker.* `@pytest.mark.spawns` on the test, its class, or the module `pytestmark`; registered in
  `pytest.ini` (no `--strict-markers` yet; role 15 recommends it). It enables `-m "not spawns"` for a fast
  inner loop on any host and lets the bounded suite and xdist planner treat spawning tests separately.
- *`pytest.raises(match=...)` only on fail-closed gates: guideline, not a rule.* Whether the code under test is
  a fail-closed gate (where the refusal reason is the contract) is semantic; no AST proxy (exception class name,
  module, message shape) separates it from incidental message pinning without false results. The tool reports
  the count (708 uses in 106 modules) so a reviewer can see the trend. Guideline text: pin the message only
  when two refusals of the same exception type must be told apart, or when the message is an operator-facing
  contract; otherwise assert the exception type and the absence of side effects.

**Known limits.** Helpers imported from another test module and command lines built in another module are
not followed; a function that spawns Python and mentions `"git"` elsewhere is over-counted (marking it is the
cheap fix). The ratchet is a regrowth brake, not a proof.

**Not done here.** The new ratchet test should join PR #200's `ratchet` marker list (and its audit-job file
list) once #200 lands; it is not marked now because #200's meta-test requires the list and the marker to match.
#199, #200 and this PR each add a `markers =` key to `pytest.ini`; whichever lands later joins them.

## P2. Definition of done: focused + affected tests, CI as full-suite evidence

**Current text** ([development.md, Definition of done](../../development.md#definition-of-done)): focused
tests, then "broader checks match the change risk", and the focused-verification section asks for "the full
suite for cross-owner changes ... on a workstation or through CI". In practice agents run the full suite
locally as well as in CI.

**Proposed text.**

1. **Focused tests** for the owner package, as today.
2. **Affected tests** from `python -m weather.operations.affected_tests --base origin/master --format paths`
   (PR #204, role 12), run through the host's normal pytest route. The selection always includes the
   repository ratchets; any `conftest.py`, pytest configuration or dependency-pin change selects the full suite.
3. **The pull request's CI is the full-suite evidence.** Nobody runs the full suite locally only to duplicate
   CI.
4. **Local full suite only where CI cannot see the tests:** the Windows-executing script tests that are in no
   Windows-qualification shard (role 15: 303 cases, concentrated in the reconciler execution, scheduler RPC,
   monitoring fixes and workload-admission files), which today are proven only by the bounded production-host
   suite or a Windows workstation full run; and anything a handoff explicitly requires.

**Evidence.** Role 12: culprit-commit recall 13 of 16 failing test files across the 8 non-flake incidents of
P0-3's window; the 3 misses were a cross-branch conflict whose tests existed only on feature branches, which CI
caught. Every ratchet fire is caught because ratchets are always selected. Median selection over the last 30
merged PRs: 23.5 test files (5% of files, 7% of functions). Linux CI runs the full suite in about 9 minutes;
the Windows full run is 46-50 minutes and the P0-2 instrumented run held the shared lease for 3,989 s.

**Risk.** A cross-branch semantic conflict is left to CI (as today for anything not run locally). A
Windows-only regression in an unsharded file is still invisible to PR CI; item 4 keeps today's rule for it,
and role 15 recommends shards for the highest-value of those files.

## P3. HOST_LOAD_POLICY: workstation lease scope, FIFO queue, xdist

**Capture-host rules are unchanged.** The bounded suite, the 00:30-09:00 window, the 25-file chunk cap, serial
execution and the ban on direct full runs all stay exactly as written.

**Problem on the workstation.** `workstation_heavy.ps1` takes one host-global mutex and refuses immediately
("blocked by another heavy or portable live lease"); callers poll. There is no queue and no record of waiting.
During K, role 11's xdist trial was refused more than 100 times over about two hours while other full runs
held the lease, and P0-2's single admitted run held it for 66 minutes. A one-file focused run waits behind a
full suite exactly as long as another full suite would.

**Proposed text.**

1. **Exempt small focused runs.** A pytest invocation on the workstation naming at most 25 test files, none of
   which carries the `serial` marker (role 11: tests that touch host-global state such as the heavy-workload
   mutex, `%ProgramData%`, Scheduler, registry, fixed ports or global git config), and not using xdist, does not
   need `workstation_heavy.ps1`. It still uses an explicit `--basetemp` that is deleted afterwards. Exemption
   never applies to the live-execution lane: while a portable live stage holds the mutex, no pytest runs.
2. **Full and large runs queue FIFO.** `workstation_heavy.ps1` gains a wait mode: a caller takes a ticket in a
   queue file beside the mutex, waits for its turn (bounded by a caller-supplied maximum wait), and appends one
   JSON line per enqueue, start, finish and give-up to a wait log (`data\logs\heavy_workload_waits.jsonl` in the
   admitting checkout: caller, kind, argument hash, enqueue/start/end times). The refusal-on-busy behaviour stays
   the default for callers that do not opt in; polling loops in agent scripts are replaced by the wait mode.
3. **xdist only on the workstation.** `pytest -n` with `--dist loadfile`, applied to `-m "not serial"`, with
   the `serial` set run afterwards in one process, is allowed only through `workstation_heavy.ps1` on the
   workstation, and only once role 11 shows an identical pass set (same test ids, same outcomes) against a serial
   run. It is never allowed on the capture host and is not proposed for CI here.

**Risk.** Exempt focused runs can overlap a wrapped heavy run, so the workstation can be briefly busier; the
25-file cap and the `serial` exclusion keep host-global side effects inside the lease. The queue is new code
in a capture-safety script family, so it needs its own execution tests and Defender review.

## P4. Workstation preamble wording

Replace the sentence that routes "pytest beyond a few files" through the wrapper with: "Focused pytest of at
most 25 files with no `serial`-marked test runs directly (explicit `--basetemp`, deleted afterwards). Full
suites, larger selections, xdist, compileall, training and replay go through `scripts\ops\workstation_heavy.ps1`,
which queues them in order." Replace "Include the repo-wide audits ... and wait for the PR's full GitHub CI"
with "Run focused and affected tests (development.md); the PR's CI is the full-suite evidence. Wait for it to
finish green."

## P5. Mutation-informed assertion guideline

**Evidence (role 6).** 104 hand mutants over 27 hot functions in 10 packages: 45 killed, 51 survived although
covered, 8 never executed. Kill rate 43% overall; 54 real gaps after removing equivalent mutants. The surviving
faults cluster in a few shapes:

- **Boundaries** (`<=` vs `<`, `>=` vs `>`): `maker_core` spread and depth gates, settlement `resolve_outcome`
  `gte`, band containment, the capture-health memory floor.
- **Dropped guards and branches**: the quote-starvation BLOCK in the maker countability gate, the touch-buffer
  check, venue `min_order_size`, the eccc_swob source in the physical floor, the empty-ask check.
- **Constants and fallbacks**: depth floor 75 to 50, fallback status `failed` to `missing`, missing
  `fetched_at` reported as age 0.
- **Statistics consumed but never checked**: the bootstrap interval survives no-resampling and one-sided-alpha
  mutants under 71 tests that only consume it.

Most of those tests execute the line and assert something else. Coverage was never the gap; the oracle was.

**Proposed guideline** (for new tests, and for tests touched in a change):

1. For each gate or threshold under test, assert both sides of the boundary: the value exactly at the
   threshold and one step past it, with the expected outcome for each.
2. For each guard clause, have one case where only that guard should fire, and assert the specific outcome (not
   just "not PASS").
3. Assert the computed value of a statistic or numeric output against an independent expectation, not only that
   it exists or is ordered.
4. When a test is written for an incident, name the mutation it kills in the `Guards:` line or the test
   docstring (for example "kills: spread >= changed to >").
5. Prefer one strong case per partition over many cases in the same partition (role 5 found the suite's
   overlap is input partitions, not duplicates; role 15 found a 448-case parametrize costing under a second).

This is guidance, not a ratchet: mutation testing is too slow to gate PRs. A periodic, admitted mutation sample
on the workstation (role 6's harness) can measure progress per package.
