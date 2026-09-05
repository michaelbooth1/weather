# Cold-archive staging adapter handback

**PASS for the reviewed implementation and focused verification. Real-data staging remains FAIL-CLOSED at the production controller's module-admission boundary. No source deletion is authorized.**

Recorded 2026-09-04 America/Toronto. This finalizes the previously unpublished
stop report; the earlier controller stop receipt remains preserved.

## Exact source and review

- Branch: `codex/workstation-cold-archive-staging-adapter-2026-09-101b`.
- Declared parent: `2e6c9b49fc5bf28d3842eff17787123b330c6b91`.
- Implementation commit: `68b9b130e9ee77e8737a861f92bd6ef5445f340e`.
- Implementation tree: `f2aed43825d6dda371debaab2f8854ba80d852e0`.
- Worktree: `C:/Users/Michael/Documents/github/weather/scratch/w/cold-archive-staging-adapter-09-101b`.
- This report is committed separately after the implementation. Publication and
  exact final-tip equality are recorded by the production controller after that
  commit; this report does not claim its own future commit hash.

The inherited 13-path implementation was reviewed in full and its mixed index
was preserved until intentional staging. Review covered create-only namespaces,
stable source identity, the 1 GiB bound, local crypt-root binding, encrypted
configuration and DPAPI custody, child timeout/termination, partial preservation,
and the absence of an archive/source deletion executor.

Two concrete gaps were repaired: all ambient `RCLONE_*` configuration/logging
overrides are excluded from rclone children, and written manifests/receipts
require stable exact-byte readback plus self-hash validation before PASS.
A corrupt already-written receipt remains spent and cannot be rewritten.
Three regression cases cover these repairs.

## Current verification

The exact seven-file focused suite ran through the reviewed workstation
wrapper from the adapter worktree:

```text
C:/Windows/System32/OpenSSH/ssh.exe -F none -T -n -o BatchMode=yes -o StrictHostKeyChecking=yes -o PermitLocalCommand=no -o ProxyCommand=none -o ProxyJump=none -o ClearAllForwardings=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 -o HostName=192.168.1.106 -i C:/Users/micha/.ssh/id_ed25519_workstation_codex -o UserKnownHostsFile=C:/Users/micha/.ssh/known_hosts -l Michael weather-workstation C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:/Users/Michael/Documents/github/weather/scratch/w/cold-archive-staging-adapter-09-101b/scripts/ops/workstation_heavy.ps1 -Kind pytest -PythonPath C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe -ArgumentsBase64 WyItbSIsInB5dGVzdCIsInRlc3RzL29wZXJhdGlvbnMvdGVzdF93b3Jrc3RhdGlvbl9jb2xkX2FyY2hpdmVfc3RhZ2UucHkiLCJ0ZXN0cy9vcGVyYXRpb25zL3Rlc3Rfd29ya2xvYWRfYWRtaXNzaW9uX3NjcmlwdC5weSIsInRlc3RzL29wZXJhdGlvbnMvdGVzdF9zY2hlbWFfcmVnaXN0cnkucHkiLCJ0ZXN0cy9vcGVyYXRpb25zL3Rlc3RfaW1wb3J0X2FyY2hpdGVjdHVyZS5weSIsInRlc3RzL29wZXJhdGlvbnMvdGVzdF92ZXJpZmllZF9jb2xkX2FyY2hpdmUucHkiLCJ0ZXN0cy9vcGVyYXRpb25zL3Rlc3RfYWdlbnRfZG9jc19hdWRpdC5weSIsInRlc3RzL3JlcG9ydGluZy90ZXN0X3JvYWRtYXBfYmFja2xvZy5weSIsIi1xIl0= -RepoRoot C:/Users/Michael/Documents/github/weather/scratch/w/cold-archive-staging-adapter-09-101b
```

Result: **141 passed, 15 skipped in 15.36s; terminal wrapper/SSH exit 0**.
The assertions completed before pytest's remaining process work; the controller
retained and polled the session through normal exit, rather than treating the
summary as termination proof. No new full suite was run.

The first admission recovered an old ACTIVE marker only after proving its owner
absent and zero residual heavy processes, then deliberately rejected the launch.
The repository-requested exact retry was used. The successful run completed
normal wrapper teardown; the host-global poison marker was absent afterwards.
No manual marker deletion or weakened identity/mutex/Job check was used.

Compileall, also through the same wrapper, exited 0:

```text
C:/Windows/System32/OpenSSH/ssh.exe -F none -T -n -o BatchMode=yes -o StrictHostKeyChecking=yes -o PermitLocalCommand=no -o ProxyCommand=none -o ProxyJump=none -o ClearAllForwardings=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 -o HostName=192.168.1.106 -i C:/Users/micha/.ssh/id_ed25519_workstation_codex -o UserKnownHostsFile=C:/Users/micha/.ssh/known_hosts -l Michael weather-workstation C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:/Users/Michael/Documents/github/weather/scratch/w/cold-archive-staging-adapter-09-101b/scripts/ops/workstation_heavy.ps1 -Kind compileall -PythonPath C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe -ArgumentsBase64 WyItbSIsImNvbXBpbGVhbGwiLCItcSIsImFwcCIsInNyYyIsInRlc3RzIl0= -RepoRoot C:/Users/Michael/Documents/github/weather/scratch/w/cold-archive-staging-adapter-09-101b
```

Additional final checks, all PASS:

- PowerShell 5.1 AST parsing of changed `scripts/ops/workload_admission.ps1`:
  zero parse errors.
- From the exact adapter working directory, using
  `C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe`:
  `-m weather.operations.agent_docs_audit`:
  PASS, 18 agent files and 833 Markdown files.
- From that same directory:
  `-m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check`:
  generated report matches sources.
- Worktree, staged and cumulative `git diff --check`: PASS.
  The pre-existing generated-backlog CRLF warning did not report a diff error.

An initial roadmap check was launched outside the adapter working directory
with explicit input paths. It reported link-prefix differences because the
imported module used the other checkout's default path context. Nothing was
regenerated or overwritten. Re-running the canonical command from the exact
adapter working directory passed.

### Retained full-suite evidence, corrected

The handoff's 4,382-pass figure belongs to earlier foundation verification.
The final adapter full-suite terminal line in the retained transcript is:

```text
61 failed, 4420 passed, 18 skipped, 13 warnings, 862 subtests passed in 2212.38s
```

Its exact-parent control is:

```text
61 failed, 109 passed in 707.96s
```

Parent/tree binding was verified as
`2e6c9b49fc5bf28d3842eff17787123b330c6b91` /
`f76bb7050311db0c91e7e39f007b04e37a42ddaa`.
All 61 terminal FAILED descriptions match exactly. This supports unchanged
failures relative to that parent; it is not a claim that the complete suite is
green. Those retained runs predate the two review repairs, which are covered by
the current focused verification above.

Transcript:
`C:/Users/Michael/Documents/Codex/handoffs/workstation-verify-cold-archive-staging-adapter-2026-09-101b.err.log`.
Terminal summary line 135338; parent/tree lines 136011-136012; parent control
summary line 157064.

## Production qualification and per-file roll verdict

The owner approved only the separate SSH hook repair, merged and published as
production `423b4d5888ecd3f4e34b84e6fd3fb03c93ded933`.
Both production CI workflows passed. Local/cached/live master equality and
unchanged hashes of the two pre-existing generated location-config files were
proved. No capture restart was requested or performed.

The production controller imported the exact implementation through a verified
incremental Git bundle. Its canonical command was:

```powershell
& scripts/ops/roll_verdict.ps1 -Branch codex/workstation-cold-archive-staging-adapter-2026-09-101b -JsonOut scratch/handoffs/cold-archive-adapter-roll-20260904.json
```

At 2026-09-04T22:39:32-04:00, against master `423b4d588`, the canonical
verdict was **ROLL-SENSITIVE**. The schema registration is additive-only:
two new manifest/receipt schemas, with no existing entry changed. It still
enters `clob_loop`, `execution_tape`, `loop`, and `observation_trigger`.

| Adapter path | Roll verdict |
| --- | --- |
| `.codex/hooks/pre_tool_use_host_load.py` | Roll-free |
| `docs/operations/README.md` | Roll-free |
| `docs/operations/data-retention-policy.md` | Roll-free |
| `docs/operations/verified-cold-archive.md` | Roll-free |
| `docs/roadmap/ROADMAP.md` | Roll-free |
| `docs/roadmap/active-backlog.md` | Roll-free |
| `docs/roadmap/items/item-325-tiered-data-retention-and-verified-archive-offload.md` | Roll-free |
| `scripts/ops/workload_admission.ps1` | Roll-free |
| `src/weather/operations/workstation_cold_archive_stage.py` | Roll-free; no retained capture closure |
| `src/weather/schema_registry_data.py` | Roll-sensitive; all four closures above |
| `tests/operations/test_schema_registry.py` | Roll-free |
| `tests/operations/test_workload_admission_script.py` | Roll-free |
| `tests/operations/test_workstation_cold_archive_stage.py` | Roll-free |
| This handback report | Roll-free |

The cumulative branch also includes its declared foundation dependency.
The canonical verdict independently found the inherited
`src/weather/operations/verified_cold_archive.py` outside the capture closures.
The dormant enrichment closure was subsumed by live closures; no dormant
worker was restarted. Future adapter integration requires separate authority
and the guarded quiet-window path.

## Remaining fail-closed boundary

The now-adopted production hook admits the constrained SSH transport, but its
offline module allowlist does **not** yet admit
`weather.operations.workstation_cold_archive_stage`. The adapter branch adds
that exact member to its hook and workstation admission code, but those branch
changes have not been adopted by the production controller. The successful
pytest/compileall transport is not permission to disguise real staging as a
test or another allowlisted module. No unsupported staging launch was attempted.

Before real staging, obtain reviewed controller admission for this exact
module without merging capture-sensitive code outside its integration gate.
Then re-prove fresh namespace absence, regular non-reparse executable/source
identity, exact source metadata, config/DPAPI ACLs and encryption, local crypt
binding, and the committed adapter tip.

The WinGet Links rclone path is a reparse point. The observed regular target,
which must be re-qualified at action time, is:
`C:/Users/Michael/AppData/Local/Microsoft/WinGet/Packages/Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe/rclone-v1.75.1-windows-amd64/rclone.exe`.

The 513,522,801-byte mirror is still provisional. Production content identity
has not been proved. The last production disk sample was below the policy's
50 GB heavy-work floor; that independent gate must pass in the admitted
window before source hashing. Do not weaken it.

No real source read/hash/compression, archive-secret recovery, real staging,
cloud write, independent download/restore, archive/source/output deletion,
adapter merge, Scheduler mutation, capture restart, exchange call, or trade
occurred. Every future provisional result must retain
`production_identity_not_proved=true`, `cleanup_eligible=false`, and
`deletion_authorized=false`.
