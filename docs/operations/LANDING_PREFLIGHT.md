# Landing preflight (non-binding workstation check)

Status: canonical runbook. Owns `weather.operations.landing_preflight` and its
`landing_preflight_*` helper modules, the `landing_preflight_v0.1` verdict and the
`landing_night_plan_v0.1` plan schema.

Read when a workstation is about to hand production a head for a landing night.
The preflight judges the head on the night's **cumulative** merge: current
`origin/master`, then every head scheduled earlier that night, then the head. It
catches the cross-PR traps that make first-attempt landings fail (a conflict with
an earlier head, a test fixture another PR changes, an EOF blank line, a
generated-index conflict, a ratchet `Guards:` line) before the capture host spends
a lease on them.

**The verdict is pre-evidence, never a gate.** Every verdict carries
`binding: false`. Production's own gates still decide:
`scripts\ops\roll_verdict.ps1 -Branch <b>` is the only roll verdict
([delegation contract](DELEGATION_CONTRACT.md) §3),
`scripts\ops\quiet_window_merge.ps1` and the
[integration attempt receipts](INTEGRATION_ATTEMPT_RUNBOOK.md) bind the landing,
and the bounded suite stays the host's test gate. A PASS here grants nothing.

## Where it runs

- **Workstation only.** It refuses to run on the dedicated capture host: it
  compares the SHA-256 of the machine GUID with
  `dedicated_capture_execution_host_id` in
  `config/international_live_execution_host.json` and stops with ERROR (exit 2) on
  a match or when the identity cannot be read. Never run it on the capture host.
- It never modifies the caller's checkout, index, `HEAD`, branches or remote
  configuration. The synthetic merges live in a scratch object store that borrows
  the caller's objects through `alternates`; the checks run in a detached scratch
  worktree; both are removed in a `finally` unless `--keep-scratch`.
- Unless `--no-fetch`, it runs `git fetch --no-auto-maintenance origin`, which
  updates the caller's `refs/remotes/origin/*` and `FETCH_HEAD` (never `--prune`).
  Every git call carries `-c maintenance.auto=false -c gc.auto=0` and no hooks, so
  no `gc`, `prune` or `worktree prune` runs on a shared clone.
- It never takes the capture-host lease. Focused test runs (at most 25 files, no
  serial or PowerShell-spawning file) run directly; anything larger goes through the landing tree's
  `scripts\ops\workstation_heavy.ps1 -RepoRoot <scratch worktree> -Queue`, which
  takes the **workstation** heavy lease ([host load policy](HOST_LOAD_POLICY.md)).
  It never starts a direct full pytest. A queue timeout (wrapper exit 75) is
  NOT_RUN.
- Every pytest run's `--basetemp` is `<SystemDrive>\lpf\<pid>\<tag>` on Windows
  (inside the scratch elsewhere), whatever `--scratch` says, and is removed after
  the run. A basetemp under a deep scratch pushed the reconciler execution tests'
  temp files past MAX_PATH: 35 false failures on 2026-10-05 that pass on a short
  path. Failure details keep the message (4,000 characters) and the untruncated
  failing source line (`assert_line`).
- Two Windows launcher tests are known load-sensitive
  (`LOAD_SENSITIVE_TESTS`: the cooperative ctrl-break and caller-stdin tests).
  When one fails only a start-up precondition (marker before the deadline,
  debugger text, the script-started marker), it is re-run alone. It becomes
  `WARN known_load_sensitive` only if it passes, or misses a precondition again;
  a cooperative, forced, exit-code, cleanup-time or budget assert is FAIL and is
  never re-run.
- The default scratch root is `<SystemDrive>\lpf-s` on Windows: short, and
  outside `%TEMP%`, whose real-time scanning timed spawning tests out in the
  2026-10-05 dog-food.
- Checks run with `GIT_ALTERNATE_OBJECT_DIRECTORIES` set to the scratch store's
  objects and the caller's objects. The scratch worktree's objects otherwise sit
  behind alternates, and a test that `git clone --shared`s the repository and
  pushes between its own clones hit "missing object". On a real clone that test
  passes. LFS content is never smudged in the scratch worktree, so checks also run
  with `GIT_LFS_SKIP_PUSH=1`.
- The child environment is offline and scrubbed with the bounded suite's
  sensitive-name rules (tokens, proxies, wallet and exchange names,
  `SETTLEMENT_LEDGER_ROOT`), plus `GIT_ALLOW_PROTOCOL=file`,
  `GIT_CONFIG_NOSYSTEM=1` and `GIT_NO_REPLACE_OBJECTS=1`. It makes no `gh` call.

## Commands

```powershell
# One head after the heads landing earlier tonight (the convenience form):
.\venv\Scripts\python.exe -m weather.operations.landing_preflight `
    --head origin/codex/my-branch --expect-head <sha40> `
    --earlier 191@<sha40> --earlier 226@<sha40> --tests affected --out <verdict.json>

# The same against a night plan (its canonical hash is bound into the receipt):
.\venv\Scripts\python.exe -m weather.operations.landing_preflight `
    --head <sha40> --night-plan <night.json> --expect-plan-sha256 <sha256> --tests affected

# Resolve refs and print the plan only; judges nothing (exit 6):
.\venv\Scripts\python.exe -m weather.operations.landing_preflight --head <ref> --earlier ... --dry-run
```

| Option | Meaning |
| --- | --- |
| `--head <ref>`, `--expect-head <sha40>` | The head to judge; `--expect-head` freezes it to an exact SHA |
| `--night-plan <json>`, `--expect-plan-sha256 <sha256>` | The night's ordered plan (below); the expected hash may be the canonical content hash or the file-bytes hash |
| `--earlier <n@sha40>` (repeatable) | Builds a plan from heads landing earlier, in order; use instead of `--night-plan` |
| `--base <ref>` (default `origin/master`), `--expect-base <sha40>` | The landing base; a local `master` behind `origin/master` is judged against `origin/master` |
| `--span-base <sha>` | Start of the `git diff --check` span (default: base). When re-running mid-night, pass the night's first-integration base: production checks `first_integration..HEAD` |
| `--tests affected\|changed\|none\|full` | Test selection for the head (below). `none` can never exit 0 |
| `--closure-snapshot <json>` | Production's capture closure snapshot for the roll-class prediction; without it the class comes from the static import graph alone and says so |
| `--declared-roll-class <class>`, `--no-execution-tape` | The class the head is scheduled under (else the plan slot's); drop the execution-tape entry modules from the static graph |
| `--out`, `--scratch`, `--keep-scratch`, `--no-fetch`, `--repo`, `--python` | Verdict path, scratch root, keep the scratch for inspection, skip the fetch, caller repository (read-only), interpreter for the worktree checks (default: the repository venv) |
| `--queue-timeout-seconds` (14400), `--check-timeout-seconds` (900), `--pr-list <json>` | Wrapper queue wait, per-check timeout, optional triage export used only for annotations |

The last stdout line is the handback line, for example
`landing_preflight PASS_NO_TESTS tests=none(skipped) binding=false sha256=<receipt> head=<sha> earlier=[...] base=<sha> plan=<sha256> landing=<sha> git=<version>`.
Paste it, with the verdict JSON, into the handback.

## Exit codes and verdicts

| Exit | Verdict | Meaning |
| ---: | --- | --- |
| 0 | `PASS` | Every check passed or warned and the selected tests ran and passed |
| 1 | `FAIL` | A check failed (diff check, an audit, a ratchet, a test); `failing_checks` names it and each failure carries `introduced_by` |
| 2 | `ERROR` | A precondition or check could not run: capture host, git older than 2.38, under 10 GiB free on the scratch volume, an unresolved or moved ref, a malformed plan, a crashed check |
| 3 | `CONFLICT` | The cumulative merge conflicts at some step. Any conflict, including one confined to a generated index, is exit 3; later phases are skipped |
| 4 | `TESTS_NOT_RUN` or `PASS_NO_TESTS` | Tests did not run (queue timeout, wrapper absent), or `--tests none` with every other check satisfied. Deliberately not 0: no test ran |
| 5 | `SUPERSEDED` | The head is already in base, or an earlier head tonight already contains it: it lands through that head |
| 6 | `DRY_RUN` | `--dry-run`: refs resolved, nothing judged |

Precedence when several apply: FAIL > ERROR > NOT_RUN > PASS. WARN rows are listed
in `verdict.warnings` and never block.

## What it checks

The `checks` object holds one row per check with `status` (PASS, FAIL, WARN, SKIP,
ERROR, INFO, NOT_RUN), a summary, details, attribution and evidence.

| Phase | Checks |
| --- | --- |
| Preconditions | `host_identity`, `git_version`, `disk_floor`, `refs` (fetch, resolve, `--expect-*`, head drift of earlier slots) |
| Chain | `already_landed`, `containment` (a head stacked on an earlier head is INFO; an earlier head containing this one is SUPERSEDED; a plan landing a head before its own ancestor is `order_inverted` FAIL), `merge_chain` (two-parent synthetic commits with a pinned date, so identical inputs give an identical `landing_commit`; a conflict is attributed pairwise: base alone, then base plus each earlier head) |
| Objects | `diff_check` (`git diff --check` over the span and per step, attributed), `whitespace_only` (INFO evidence: no non-whitespace change, no added/renamed/binary file, expected ROLL-FREE), `schema_additive`, `roll_class`, `landing_path`, `docs_transaction` (blob ids of the four required docs as of the final planned tip) |
| Worktree | `worktree`, `import_probe`, `agent_docs_audit`, `correspondence_index` (`--check`), `roadmap_backlog` (`--fail-on-lint --check`), `schema_registry` (no unregistered versions), `shard_coverage`, `ps1_param_defaults`, `ratchets` |
| Tests | `tests`, `windows_scripts` |

**Ratchets.** The file list is the union of the `-m ratchet` lists in the base,
pre-head and landing `ci.yml` plus a static list, so a head cannot shrink the gate
it is judged by; dropped files are warned. PowerShell-spawning ratchets are
deferred to `windows_scripts`, never the direct run.

**Tests.** `affected` runs `weather.operations.affected_tests` from the landing
tree with `--base <chain before the head> --head <landing commit>`; if that module
is absent or changed in the night span, the selection is unioned with a
changed-tests-plus-direct-importers fallback and warned. A selection over the
wrapper's cap escalates to `full` (through the wrapper), never a silent partial.
`changed` runs the changed test files, `full` the whole suite through the wrapper,
`none` nothing. Each failure is classed statically, without a second run:
`interaction` when an earlier head changed the failing test file or the test
reaches both the head's and an earlier head's changes, else `head`. It names the
step that introduced it and carries the plan's `known_fix` for that step. If the night span changes the wrapper or
its lease scripts, the base tree's copies run instead (warned).

**Roll class.** `roll_class` predicts EXPECTED-ROLL-FREE, EXPECTED-ROLL-SENSITIVE
or EXPECTED-UNDECIDABLE (schedule as roll-sensitive) from the closure snapshot
plus the static import graph of the capture-loop entry modules; any
`schema_registry*` change is sensitive. Every row is `binding: false`;
`roll_verdict.ps1` on the production tree decides. `landing_path` maps the class to
DOCS_LIGHT, ROLL_FREE_GUARDED (00:30–09:00) or ROLL_SENSITIVE (01:00–04:00 quiet
window).

## Night-plan schema (`landing_night_plan_v0.1`)

```json
{
  "schema": "landing_night_plan_v0.1",
  "night": "2026-10-07",
  "slots": [
    {"kind": "91a", "head": "91a cold-snapshot nightly", "sha": null, "prs": []},
    {"kind": "rs_guarded_merge", "head": "codex/branch-a", "sha": "<sha40>", "prs": [191]},
    {"kind": "rf_guarded_merge", "head": "codex/branch-b", "sha": "<sha40>", "prs": [226],
     "known_fix": "regenerate the correspondence index"},
    {"kind": "docs_light", "head": null, "sha": null, "prs": []}
  ],
  "plan_sha256": "<canonical hash>"
}
```

- A slot lands a head only when it carries a 40-hex `sha`; the head is matched by
  SHA. Slots before the head's slot are the earlier heads; a head absent from the
  plan is judged after every landing slot (warned).
- A slot without `sha` is accepted only when it names no head, or when its `kind`
  never lands a head (`91a`, `replay`, `retry_unbooked`, or `docs_light` without
  `prs`). Any other slot naming a `head` or `prs` without a `sha` is refused with
  ERROR, never silently dropped.
- `plan_sha256` is the SHA-256 of the plan's canonical JSON without the
  `plan_sha256` key: sorted keys, separators `(",", ":")`, `ensure_ascii=False`,
  UTF-8. An embedded hash that does not match the content is refused.
- Other keys (`label`, `master_sha`, `generated_at`, `source`) are carried, hashed
  and otherwise ignored.

## Verdict schema (`landing_preflight_v0.1`)

Top-level keys: `schema`, `generated_at`, `git_version`, `python`, `host`,
`elapsed_s`, `inputs`, `plan_sha256`, `closure_snapshot_sha256`, `chain` (one row
per step: label, sha, role, result, conflicts with `fix_class`, pairwise
attribution), `landing`, `checks`, `verdict` (`status`, `exit_code`,
`failing_checks`, `warnings`, `tests_run`, `binding: false`, `binding_gates`,
`valid_while`), `cleanup`, and `receipt`. The receipt's SHA-256 is over the JSON
and binds the base, the plan hash, every earlier SHA, the head SHA, the closure
snapshot hash and the git version. A verdict is valid only while
`origin/master` equals its base and the plan's earlier SHAs land unchanged.

## How it composes with production

| Production gate | What the preflight adds | What it does not replace |
| --- | --- | --- |
| `roll_verdict.ps1 -Branch <b>` | An expected roll class and landing path, so the calendar books the right window | The verdict: only `roll_verdict.ps1` on the production tree is binding |
| The bounded suite (`bounded_worktree_test_suite.ps1`) | The head's affected tests and the ratchets on the cumulative tree, with `head`/`interaction` classing, before the night | The host's full bounded suite at the exact tip |
| `quiet_window_merge.ps1` and integration attempts | The cumulative merge of the night's plan, with conflicts attributed to the step and pair that caused them | The guarded merge, recovery proof and push |
| The documentation transaction (docs light path) | `diff_check` over the night span and the four required docs' blob ids as of the final planned tip | The transaction's own `git diff --check` and bindings |

Run it after the head is final and before the handback; re-run whenever
`origin/master` or an earlier head moves. A changed head needs a new verdict.

## Update this file when

The CLI, exit codes, checks, night-plan or verdict schema, the host refusal, the
routing of test runs, or the production gates it composes with change.
