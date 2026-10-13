# Proposal: affected tests as the local definition of done (test-suite review K, role 12)

Status: **PROPOSAL awaiting owner decision. Not in force.** Dated 2026-10-04; historical evidence once decided.
The current definition of done is [development.md](../../development.md#definition-of-done) until the owner says
otherwise. The tool itself is described in [development.md](../../development.md#affected-test-selection).

## Proposal

Change the local verification step of the definition of done from "focused tests, then broader checks matching
risk (often the full suite)" to:

1. **Focused tests** for the owner package, as today.
2. **Affected tests**: `python -m weather.operations.affected_tests --base origin/master --format paths`, run
   through the host's normal pytest route (workstation wrapper or capture-host bounded runner). The list always
   includes the repository ratchets; any `conftest.py`, pytest configuration or dependency-pin change turns it
   into the full suite.
3. **CI's full suite on the pull request is the full-suite evidence.** Nobody runs the full suite locally just
   to prove a change, except where a rule already requires it (Windows-executing script tests still need the
   bounded production-host suite; cross-host missions keep their handoff's own checks).

The full suite is unchanged and still runs on every pull request and every `master` push. The proposal only
removes the local full run that duplicates CI.

## Evidence (measured 2026-10-04 on the workstation)

Method and raw data: `C:\wt\workstation-chat\k-data\12\` (scripts `culprit_recall.py`, `replay_recall.py`,
`pr_selection_size.py`; results `*.json`). CI history is P0-3's 500-run window (2026-09-27..10-04).

**Recall against what really failed.** For each non-flake CI incident, the culprit commit (the commit that
introduced the break) was selected alone against its first parent, with the graph at that commit:

| Incident | Failing tests | Selected by the culprit commit |
| --- | --- | --- |
| 110q economics tick-mix merge (real defect) | 3 files, 65 tests | yes, via a direct import of `exchange_economics` |
| 111a plugin runtime `Sources` signature (real defect) | 3 files | **no** (see misses) |
| compress closed token tapes, CSV writer (real defect) | 2 files | yes |
| 110o-10 DORMANT roadmap status (real defect) | 1 file | yes |
| events snapshot moved to data root (test defect) | 3 files | yes |
| 111e exam executable, Linux limits (test defect) | 2 files | yes |
| NBM parser v2 landing (test defect) | 1 file | yes |
| 91a -VerifyRetained, Windows-only (test defect) | 1 file | yes (changed test file) |

Culprit-commit recall: **13 of 16 failing test files**. Every inventory/ratchet fire in the window (24 SHA-level
fires: correspondence index, ops-script task inventory, module size, schema registry, research inventory,
repo-health) is caught by construction, because the ratchets and the always-run audit commands are always
selected. At pull-request level (branch head against its merge base, the way CI would run it), every one of the
57 non-flake (SHA, failing test) pairs was selected, but large branches select most of the suite, so that number
says little.

**Misses and why.** The 111a break was a cross-branch semantic conflict: master changed
`maker_plugin_sources.Sources`, and the tests that broke (`test_maker_replay_bundle.py`,
`test_maker_fair_value_score.py`, `test_maker_replay_night.py`) existed only on seven feature branches. No
selection on the culprit commit can see a test that is not in its tree. The pull-request run of each branch did
select them (they were changed test files there), and CI's full suite caught them. This is the class of failure
the proposal leaves to CI.

**Selection size, last 30 merged pull requests.** Median 23.5 test files of about 450 (5.2%), median 7% of test
functions; 24 of 30 PRs select at most 25% of test functions; no PR selected the full suite through a trigger.
Large selections come from genuine import hubs (`schema_registry` and its data, `storage_classes` through
`event_day_manifest`, `release_serving`): integration batches selected 64% and 93% of test functions.

**Coverage cross-check.** Not done: P0-2's coverage run (`.coverage` with per-test contexts) had not been
admitted by the workstation lease when this was written. It should be repeated when that file exists.

## Known limits

- Static only: dynamic imports with computed names, computed paths and subprocesses launched by name are
  invisible. Product-code file references and function-level imports reach only tests within two import hops of
  the referring module (otherwise every hub selects everything); a far test that depends on such a path is a
  possible miss. The output lists every changed file that reaches no test.
- PowerShell is text-scanned: a line that runs `-m weather.x` or names a script is an edge; a module named in an
  allowlist is a mention only.
- Windows-only tests are selected like any other, but CI's Linux job skips them, so their evidence remains the
  bounded production-host suite.

## Decision requested

Approve, amend, or reject replacing the local full-suite step with focused + affected tests and CI full-suite
evidence. If approved, `development.md`'s definition of done is rewritten in a separate change.
