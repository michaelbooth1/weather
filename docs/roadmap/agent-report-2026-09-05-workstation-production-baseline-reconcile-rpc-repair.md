# Workstation production-baseline reconciliation RPC repair

Mission: `workstation-production-baseline-reconcile-rpc-repair-2026-09-96a`

Terminal verdict: **`BLOCKED_GITHUB_AUTHENTICATION`**. The requested repair is
implemented and locally verified, but this workstation could not publish the
append-only commits or obtain exact-head Linux CI. HTTPS push failed before any
remote update because the configured Git credential was unusable; the GitHub
CLI token is invalid, and no existing SSH key is authorized. No credential
value was inspected, created, changed, or exposed. The remote branch remained at the required
starting tip.

## Frozen identities

| Identity | Commit | Tree |
| --- | --- | --- |
| Required source | `1cd51d516875e279c674a76bf921e22ddaf30943` | `ba23363a956e66c4914ad7bdc4f3766d9e1678b8` |
| Implementation | `296f8d2dfb7c90beb74767b4e56f695cbc502e0b` | `d1f31219d5d2f8b48b7e1174161b67cc7ba14f3b` |
| Final report carrier | Externally bound to the commit containing this report and its paired receipt | Externally bound to that commit's tree |

- Branch: `codex/workstation-production-baseline-self-adopting-reconcile-2026-09-85a`
- PR: <https://github.com/michaelbooth1/weather/pull/10> (open draft;
  base `master`; head branch and starting SHA independently verified)
- Entry SHA-256: `40a912564452fbedf175e7015c4b800d765fc40407f9ce7e053f7b4f81956419`
- Scheduler helper SHA-256:
  `249fc4e9e5bfb2d4c2cacca073c28c65c8f2b060473a50820a7889ff3fcbc885`
- The implementation is a strict descendant of both source tip `1cd51d...`
  and published target `c932b54f8747df5cdefc4cc42f8454b6797f09ae`.

The report/receipt commit cannot contain its own Git commit or tree identifier.
The paired receipt therefore uses an explicit external-binding rule: resolve
the branch ref, require that its tip contains the byte-exact receipt, require
that the implementation-to-tip diff contains only the two named handback
files, and then use that resolved commit/tree as the final identity. The final
chat handback prints the locally resolved values. Publication is not claimed.

## P0 falsification evidence

Before changing production code, two exact tests failed against the old child:

1. The mocked name/path export returned the frozen reviewed XML while the same
   task's mocked `-InputObject` export returned different valid XML. The old
   child exited `2` and wrote `WeatherOneShotPush task XML changed from the
   reviewed definition`; the test invocation ended `2 failed in 0.92s`, exit
   `1`. Mutation authority remained unclaimed and undispatched.
2. A triggerless mocked task exposed `Triggers = $null`. The old
   `@($Task.Triggers)` path counted one and exited `2` with static binding
   failure; mutation authority remained unclaimed and undispatched. A direct
   Windows PowerShell 5.1 ratchet proves old/new counts `1|0`.

The mechanisms were reproduced, so `NO_CHANGE_MECHANISM_FALSIFIED` does not
apply.

## Repair

The child now uses the identical canonical path frozen by the parent:
`Export-ScheduledTask -TaskName WeatherOneShotPush -TaskPath \`, UTF-8 bytes,
and one strict reviewed SHA-256. It does not accept an alternate hash. Each
structured task read is bracketed by canonical exports and fails closed if the
XML bytes/hash change, preserving exact name/path identity and avoiding a new
snapshot gap. Trigger checks count only non-null objects; one real trigger is
still rejected. The directly equivalent ordinary quiet-merge count received
the same narrow correction.

Action, principal, state, execution timing, working directory, task path, and
singleton mismatches still fail closed. Changed canonical XML bytes fail even
when structured fields look valid. RPC deadlines, kill-on-close containment,
create-only request/result files, request hashes, bounded response validation,
durable Start/Stop claims, ambiguous-response semantics, rollback, capture
recovery, immutable journaling, and the single authorized push budget were not
relaxed.

Changed implementation paths:

- `docs/operations/OPERATIONS_DESIGN.md`
- `docs/operations/STATE_OF_PLAY.md`
- `docs/ops/streak-soak.md`
- `scripts/ops/AGENTS.md`
- `scripts/ops/production_baseline_scheduler_rpc.ps1`
- `scripts/ops/quiet_window_merge.ps1`
- `tests/operations/test_production_baseline_reconciler_execution.py`
- `tests/operations/test_production_baseline_scheduler_rpc.py`
- `tests/operations/test_quiet_window_merge_script.py`

## Verification ledger

All pytest/compileall invocations used `scripts/ops/workstation_heavy.ps1` with
the assigned `workstation_offline_v1` admission profile and project
interpreter. Counts overlap and are not summed.

| Gate | Exit | Result |
| --- | ---: | --- |
| Required branch/worktree/cached/live/PR identity before edit | 0 | exact source tip/tree; clean; PR #10 open draft |
| Initial local `venv` invocation | 1 | diagnostic only: worktree-local interpreter absent; no pytest collected |
| Pre-repair P0 two-case red run | 1 | `2 failed in 0.92s`; both required mechanisms reproduced |
| Post-repair exact P0 selection | 0 | `12 passed in 4.68s` |
| Early complete Scheduler-RPC file | 0 | `40 passed in 21.24s` |
| Early combined integration selection | 1 | `3 failed, 85 passed in 38.49s`; one stale static assertion and two default-temp literal file-remote identity artifacts, all corrected/superseded |
| Short-temp execution control | 0 | `1 passed in 34.69s` |
| Intermediate static ratchet run | 1 | `1 failed, 44 passed in 0.28s`; stale line-continuation assertion corrected |
| Final Scheduler-RPC plus quiet-merge/static files | 0 | `87 passed in 21.17s` |
| Complete reconciliation execution/adversarial file | 0 | `70 passed in 1272.19s (0:21:12)` |
| Complete reconciliation/status/watchdog files | 0 | `93 passed in 632.94s (0:10:32)` |
| Uninterrupted full repository suite, shortest ordinary temp root | 1 | `4405 passed, 18 skipped, 13 warnings, 862 subtests passed, 12 failed in 2624.83s (0:43:44)`; every failure was the documented Windows legacy-MAX_PATH signature in `test_experiment_executor.py` |
| Complete path-sensitive executor file, extended-prefix temp | 0 | `24 passed in 3.53s` |
| `compileall -q app src tests` | 0 | PASS through workstation wrapper |
| PowerShell AST parse of every changed `.ps1` | 0 | two files, zero parser errors |
| Agent-document audit | 0 | PASS, 18 agent files / 831 Markdown files |
| Roadmap lint/check | 0 | PASS, generated report matches sources |
| Cumulative and staged `git diff --check` | 0 | PASS |
| HTTPS append-only push | 1 | no remote update; configured authentication unavailable |
| Existing-key SSH read-only authority probe | 128 | no authorized public key; no remote update |
| Exact-head Linux CI | n/a | `NOT_RUN_GITHUB_AUTHENTICATION_BLOCKED` |

The ordinary-temp suite result is diagnostic only for the known Windows path
limit: every non-path-sensitive collected test passed in that uninterrupted
run, and the complete affected file passed under the established extended-path
mode. Exact-head Linux CI remains mandatory and was not waived.

## Production handback boundary

No production access, Scheduler read/write, real task operation, merge,
production-master mutation, retry, push-task invocation, capture action,
credential-value inspection or mutation, provider/exchange call, live execution, model/corpus/outcome
work, deletion, branch deletion, rebase, or force-push occurred.

Attempt `20260903_a1` is spent and frozen. It must never be retried, rewritten,
or reused. After an authorized maintainer publishes the two local commits and
exact-head Linux CI succeeds, the production owner must independently fetch and
review the final exact tip, run the canonical production-host roll verdict,
and create a wholly new immutable attempt. No workstation roll verdict is
production evidence, and this report grants no production execution authority.
