# Landing preflight (non-binding workstation check)

Status: canonical runbook. Owns `weather.operations.landing_preflight` and its
`landing_preflight_*` helper modules, the `landing_preflight_v0.1` verdict, the
`landing_night_plan_v0.1` plan schema, and the owner-approved pilots (non-binding
shadows) and their `landing_preflight_m5_concordance_v0.1` ledger.

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
  serial or PowerShell-spawning file) run directly with a `--basetemp` inside the
  scratch; anything larger goes through the landing tree's
  `scripts\ops\workstation_heavy.ps1 -RepoRoot <scratch worktree> -Queue`, which
  takes the **workstation** heavy lease ([host load policy](HOST_LOAD_POLICY.md)).
  It never starts a direct full pytest. A queue timeout (wrapper exit 75) is
  NOT_RUN.
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

# Check a handed-back verdict (production, before relying on it): exit 0 current and intact, 2 refuse:
.\venv\Scripts\python.exe -m weather.operations.landing_preflight --verify-receipt <verdict.json> `
    --expect-head <sha40> [--origin-master <sha40>]
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
Paste it, with the verdict JSON, into the handback
([delegation contract](DELEGATION_CONTRACT.md) §5). `--verify-receipt` refuses a
receipt whose `sha256` no longer matches the verdict body or whose base is not the
current `origin/master` (default: the repository's `origin/master` ref, without a
fetch): a stale receipt is refused, never warned.

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
| Objects | `diff_check` (`git diff --check` over the span and per step, attributed), `whitespace_only` (INFO evidence: no non-whitespace change, no added/renamed/binary file, expected ROLL-FREE), `schema_additive`, `roll_class`, `landing_path`, `docs_transaction` (the documentation-transaction pre-check, below), `eof_newline_only` (M13 pilot, INFO only; see [pilots](#pilots-non-binding)) |
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

**Documentation transaction (M3a, adopted).** `docs_transaction` is a real check.
It FAILs when the morning transaction would fail on this plan: a required document
(read from the landing tree's `documentation_transaction.py`) is absent from the
landing tree, or `diff_check` FAILs (the transaction's `git_diff_check` over
`first_integration..HEAD`). It WARNs for what a later slot causes: a `--check` hit
added after this head, a required document absent from the final planned tip, an
unknown final tip, or an unchanged review that a later head makes stale. It reports
the required documents' blob ids as of the final planned tip and carries the M3b
shadow row. The transaction's `agent_docs_audit` and roadmap parity are the
worktree-phase checks of the same names.

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

## Pilots (non-binding)

The owner approved these as pilots (Swarm L, 2026-10-05). Each is a shadow that
records what an adopted rule would conclude. None changes a verdict, another check's
status or an exit code, and none grants anything; production's gates are unchanged.

**M13 `eof_newline_only` (object phase, always INFO).** The predicate is byte-exact.
Every file the head step changes (from the tree before the head step to the landing
tree) must satisfy `new == old.rstrip(b"\n") + b"\n"`. That is, the blobs are equal
once their trailing `\n`/`\r\n` run is stripped, the new blob ends in exactly one LF,
and no CR byte changes. No literal parsing is needed, because no Python or
PowerShell string can be open at end of file. Never `-w` or `--ignore-space-at-eol`:
those admit indentation changes and whitespace removed inside triple-quoted strings
and here-strings.

- Also disqualified: any add, delete, rename, mode or type change; an LFS path; a
  YAML file (a `|+` block keeps trailing newlines as content); a hash-frozen file;
  `diff_check` other than PASS; a roll class other than EXPECTED-ROLL-FREE.
- Hash-frozen files are derived from the tree
  (`landing_preflight_pilots.hash_frozen_paths`): `quiet_window_merge.ps1`,
  `boot_recovery.ps1`, `health_watchdog.ps1` and `status.ps1` always; any `.ps1`
  declaring `[string]$ExpectedSelfSha256`; any `.ps1` named by a `register_*.ps1`
  that declares an `Expected*Sha256` parameter; and a changed path that a tracked
  JSON under `config/` or `artifacts/` names next to a `*sha256*` key.
- The row reports `suite_skip_eligible: true|false`. The host `roll_verdict.ps1`
  exit 0 would still be required. Calibration: the 10-05 05:51 landing (`6c6ab479`
  on `202245b4`, 37 files) is eligible.

**M3b binding shadow (INFO row in `docs_transaction`).** `evidence.m3b_binding_shadow`
computes what binding the unchanged reviews to the night's **final** integration
commit would conclude. Each required disposition document needs a review whose blob
id equals its blob at the final planned tip; by default the reviews are assumed bound
at this head. `effective_if_adopted` is `strictest(current status, would_conclude)`,
so the shadow can add a FAIL but never turn a FAIL into a PASS (tested). A night
whose later integration moves STATE_OF_PLAY concludes FAIL without a review bound to
the final tip.

**M5 shadow dual run (`python -m weather.operations.landing_preflight_m5`).** It
applies to a ROLL-FREE tip that production landed **with** the bounded suite. The
workstation records three things for that exact tip: the preflight verdict (receipt
re-verified), the CI conclusion at that SHA (the Windows `native-launch` lane and the
rest), and the host bounded-suite outcome the production agent hands back. It appends
one `landing_preflight_m5_concordance_v0.1` JSON line to
`data/workstation/landing_preflight/m5_concordance.jsonl` (override with `--ledger`).

```powershell
.\venv\Scripts\python.exe -m weather.operations.landing_preflight_m5 record --preflight <verdict.json> `
    --host-outcome <handback.json> --ci-checks <check-runs.json> [--host-only-nodeids <json>]
.\venv\Scripts\python.exe -m weather.operations.landing_preflight_m5 progress
.\venv\Scripts\python.exe -m weather.operations.landing_preflight_m5 host-only --ref <sha> `
    [--host-junit <host.xml> ... --ci-junit <shard.xml> ...]
```

- `--fetch-ci` reads the check runs with `gh api` instead of `--ci-checks`.
- The handback file carries `tip_sha` (40 hex), `roll_verdict` (the production
  `roll_verdict.ps1` result), `bounded_suite.outcome` (`PASS` or `FAIL`) and
  `landed_at` (ISO 8601); `landing_sha` and `source` are optional.
- A row is concordant when "preflight PASS or PASS_NO_TESTS, and every CI lane green"
  equals "the host bounded suite passed". A row is recorded but not counted when the
  host verdict is not ROLL-FREE, CI is still pending, or a disqualifier applies.
- Disqualifiers: a changed host-only test; a changed `src` module that a host-only
  test imports directly; a changed hash-frozen script (the M13 derivation).
- **Host-only tests are enumerated mechanically** (`host-only` lists them):
  - a test file with a Windows-only skip condition that is in no shard of
    `windows-qualification.yml`;
  - a skip condition on `GITHUB_ACTIONS` or `CI`;
  - a file naming a host-identity, ACL or Scheduler surface (`icacls`, `whoami`,
    `USERDOMAIN`, `MachineGuid`, `Register-ScheduledTask`, `schtasks`,
    `ProgramData`, `S4U`): the 10-04 icacls 1332 class;
  - when JUnit is supplied, every node id the host bounded suite ran that every CI
    JUnit skipped or never listed.
- `progress` reports the owner's threshold: the later of 5 concordant landings or 14
  days since the current run began. Any discordance resets both. The output is always
  `binding: false`. The recorder refuses to run on the capture host.

## Update this file when

The CLI, exit codes, checks, night-plan or verdict schema, the host refusal, the
routing of test runs, the production gates it composes with, or a pilot's rule,
ledger or adoption status change.
