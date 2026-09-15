# Guarded first-landing installation

Status: source contract for one separately approved control-plane installation.
[Split qualification](SPLIT_QUALIFICATION_CONTRACT.md) owns ordinary acceptance;
[item 329](../roadmap/items/item-329-immutable-overnight-integration-attempt-recovery.md)
owns implementation and adoption status.

## Authority and sequence

The fixed installer consumes an independently approved
`qualification_bootstrap_install_envelope_v1`. Its sole operation is
`install_control_plane_K_once`: install exactly reviewed control-plane K onto
adopted B with the approved generated configuration Q. Source publication or
approval to implement this code is not approval to execute that operation.

The sequence is independently reviewed off-host evidence, actual
[first-landing probes](BOOTSTRAP_QUALIFICATION_PROBES.md), independent acceptance
of their completed native result, explicit owner approval of the exact install
envelope, one guarded installation, then exact task closeout. The owner must
explicitly accept replacing the full capture-host suite for K only. The
installer consumes no candidate-issued qualification certificate and cannot
manufacture a v1 full-suite PASS or ordinary v2 acceptance.

The approved package must already contain:

- Exact B, isolated clean K commit/tree and remote branch ref, complete source
  inventory, reviewed control-plane policy/review graph and effective K+Q tree.
  K itself may not change either generated configuration file.
- Separate frozen temporary adapter A and retained adopted B execution roots.
  A has its own complete independently reviewed byte inventory. The B closure
  must match actual B Git blobs, including its admission and outer-Job helpers.
  The roll classifier differs from B only by explicit production-root routing.
- Complete reviewed interpreter/dependency/native environment, fixed Git
  interpretation policy, actual host/principal/SID, and exact Q snapshots.
- Retained exact Windows/Linux workflow revision, run IDs, attempts, coverage,
  logs and artifacts, plus cumulative diff and rollback reviews. These are
  direct-review inputs, not a self-issued certificate.
- The original probe envelope, completed parent result, accepted probe review
  and exact task XML hash. The probes must precede the separate owner approval,
  bind the same B/K/Q/environment/host, and have no remaining task instance.
- One unique bootstrap ID/evidence namespace, exact one-shot task name,
  start/deadline, resource budgets, owner identity/approval time, and rollback
  policy preserving ambiguous committed state.

The closed fields and references are defined by
`weather.operations.qualification.bootstrap_install.context`. Use its exact
schema; adding an arbitrary command, ordinary v2 manifest, candidate certificate
or generic prerequisite-skip flag is refused.

## Invocation and bounds

The parent entrypoint is the independently frozen
`scripts/ops/bootstrap_qualification_install.ps1`. The exact registered action
must call native PowerShell with `-NoProfile -NonInteractive -ExecutionPolicy
Bypass -File`, followed by that absolute script path and these literal pins:

```powershell
-EnvelopePath <absolute-approved-envelope.json> `
-ExpectedEnvelopeSha256 <reviewed-envelope-sha256> `
-ExpectedAdapterSha256 <independently-reviewed-entrypoint-sha256>
```

These are action arguments, not a registration command. Preparation must provide
the concrete approved paths, complete records and actual hashes before any
separate Scheduler registration. This source path does not register a task.

The one-shot is `WeatherQualificationBootstrapInstall_<bootstrap_id>`, bound to
the exact S4U/Limited principal, one time trigger at the envelope start,
production working directory, `IgnoreNew`, no late catch-up, and `PT46M`.
The parent verifies the actual unelevated batch token, process generations,
command line, Scheduler instance and unchanged task definition. Its child and
the guarded primitive also verify their fixed delegation chain.

Execution is restricted to 01:00–04:00 local with an absolute envelope span of
at most 45 minutes, including teardown and receipt reserves. B holds the shared
workload lease and outer kill-on-close Job. A fixed inner monitor continuously
enforces aggregate commit, working set, disk, lifetime reads, output and child
cleanup. Capture-generation continuity is suspended only for that guarded roll
monitor; the existing primitive must prove capture recovery before commit and
publication, and individual metadata calls still enforce current capture.

Maximum envelope budgets are 2 GiB aggregate commit, 1.5 GiB working set,
128 MiB scratch, 512 scratch entries and 64 GiB lifetime worker reads. Each
metadata call is capped at 120 seconds and 4 GiB reads. The owner policy may
tighten these limits. The ordinary 50 GiB disk floor plus scratch reservation
and existing memory gates remain mandatory. Teardown reserves are explicit;
an unproved outer teardown poisons the lease.

Native startup separately bounds A to 8 MiB/512 files, runtime/native hashing
to 256 MiB, and retained B to 128 MiB/8,192 files. Reviewed file handles stay
locked until the entire installer child tree has exited. Production working
files are not held open across the merge.

## Guarded mutation and terminal evidence

The fixed child invokes the existing quiet-window primitive in separate
`bootstrap_installation_v1` mode. It refuses mixing bootstrap input with v2
manifest arguments or override modes. The existing merge, capture recovery,
documentation transaction and single publication route remain in force.

Read-only contained boundaries revalidate source/environment/configuration,
B+Q preparation, staged K+Q, the exact two-parent merge and acknowledged
publication before and after the actual mutations. Boundary/native records
have separate bootstrap schemas and `integration_eligible=false`.

`install-use.json` spends the namespace before execution. Claims, partials and
work directories are never overwritten for a retry. The parent publishes
`install-result.json` with `PUBLISHED_CLOSEOUT_REQUIRED` only after exact
publication, documentation and capture proofs plus native zero-child completion.
It retains `full_host_suite_pass=false` and `retry_authorized=false`.

After commit may have started, failure conservatively preserves possible
commit/publication and requires separate reconciliation review. Before the
merge commit is proved, the boot marker uses K as the reset-refusal sentinel
while retaining the actual preparation parent in bootstrap evidence. K is
required to contain a non-configuration change, so B cannot mistake that
sentinel for its config-only preparation child. Existing guarded precommit
abort/config restoration and capture recovery remain available.

## Closeout

After both exact probe and install tasks are non-running and successful, the
independently pinned `scripts/ops/close_bootstrap_qualification_install.ps1`
takes `EnvelopePath`, `ExpectedEnvelopeSha256`, `ExpectedResultSha256` and
`ExpectedCloserSha256`. It verifies the completed installation and all retained
boundary/native proofs, host/principal and exact task definitions.

Closeout claims `close-use.json` before mutation, disables only those two exact
tasks, and verifies their resulting definitions changed only in enabled state.
It does not delete tasks, repeat publication or register recurring work.
`installed-root.json` records published K/policy, the integration commit,
revoked bootstrap ID and proved task closure. A partial/lost closeout remains
spent for review; the command has no automatic retry mode.

Future attempts must use ordinary split qualification. Reliability adoption
still requires its own exact candidate and complete current-input audit.
The installed-root record is historical installation evidence, not continuing
execution authority or a claim about current production health.

## Verification and update

Hosted unit and native fixtures cover closed-envelope refusal, actual Git tree
drift, immutable boundaries, byte-pin refusal, native process containment during
capture readoption, ambiguous-commit marker identity and incomplete publication
proofs. They use disposable roots and do not establish production S4U acceptance.

Update this runbook when the first-landing envelope, fixed entrypoints, resource
limits, mutation boundary, failure classification or closeout contract changes.
