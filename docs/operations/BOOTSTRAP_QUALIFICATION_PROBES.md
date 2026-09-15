# First-landing qualification probes

Status: source contract for a temporary, directly reviewed adapter.
[Split qualification](SPLIT_QUALIFICATION_CONTRACT.md) owns acceptance;
[item 329](../roadmap/items/item-329-immutable-overnight-integration-attempt-recovery.md)
owns implementation and adoption status.

## Scope

The adapter executes the existing nine fixed control-plane probes against
disposable inputs. It records observations for independent review. It cannot
issue a code or host qualification PASS, replace the complete v1 suite,
install a runner, register a task, merge source, publish source, or clear an
integration marker. Its terminal status is `PROBES_RECORDED`; all records
keep `integration_eligible=false`.

The adapter is one component of first landing. The complete first-landing
envelope, [guarded installation](BOOTSTRAP_QUALIFICATION_INSTALLATION.md),
measured current-input feasibility and actual host acceptance remain separately required. Hosted fixtures do not establish
an actual production S4U observation.

## Independent inputs

The operator reviews the exact adapter SHA-256 and complete source-only
closure independently of candidate-generated evidence. The fixed entrypoint
`scripts/ops/bootstrap_qualification_probe.ps1` takes only `EnvelopePath`,
`ExpectedEnvelopeSha256`, and `ExpectedAdapterSha256`. An approved future
registration must pin those literal arguments; the entrypoint itself does
not register anything.

The closed `qualification_bootstrap_probe_envelope_v1` record binds:

- Actual adopted baseline, isolated candidate commit/tree, directly reviewed
  policy and review graph, and the two adopted admission/outer-Job helper pins.
- Separate frozen adapter and evidence roots, complete interpreter inventory,
  selected native prerequisites, retained dependency environment, Git policy
  and generated-configuration snapshot.
- Exact capture installation, attending principal and user SID, unique task
  name, start/deadline, limits, and retained independent review evidence.

The native parent pins itself and the request before loading dependencies.
Adopted B owns the lease and outer kill-on-close Job. Native preflight rejects
redirection, undeclared adapter files and adapter bytecode; it locks reviewed
file contents against replacement until teardown. Before Python starts, it
also verifies the complete reviewed interpreter topology and selected native
prerequisite bytes. Interpreter exclusions are restricted to documentation,
Tcl, tools and site-packages; isolated Python starts with `-I -S -B`.
The child rechecks the complete environment, packages, source and configuration
before and after the fixed probes. The adopted helper pins must also match
the actual Git blobs at B.

This uses an explicitly reviewed temporary adapter as bootstrap authority;
it consumes no certificate minted by that adapter. OS/.NET trust and the
initial native PowerShell installation remain prerequisites of independent
review, as with the existing adopted native launcher.

## Native limits and invocation

Execution requires the shared heavy-work lease during 00:30–09:00 local, a
unique actual S4U batch-token task instance, exact action and process ancestry,
unelevated primary token, and matching host/principal. The start/deadline span
is at most eight minutes. The one-shot task has no catch-up, ignores new
instances, and has a nine-minute Scheduler limit. The parent reserves time
for child-tree termination and final receipt publication.

Preflight requires the ordinary 50 GiB free-disk floor plus scratch reservation,
healthy identities for all three capture workers, current system commit at
most 64%, projected commit at most 66%, and projected available physical
memory of at least 4 GiB. The child continuously applies the existing native
capture/resource gate. Its aggregate Job commit and sampled working set are
capped at 512 MiB, with at most 64 MiB scratch and 512 scratch entries.

Native startup inventory hashing has a separate fixed 256 MiB ceiling and
deadline reserve. The contained worker has a lifetime 2 GiB read ceiling,
including exited descendants. Windows Job I/O accounting retains exited
process totals and aggregates nested jobs; the adapter verifies those
semantics in native fixtures. See Microsoft's
[Job accounting structure](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_and_io_accounting_information)
and [nested Job accounting](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
These are probe-component limits, not measured limits for the complete first
landing or current-data audit.

## Evidence and failure

The adapter creates `probe-use.json` once, then its owned `probe-work/`
directory. Existing claims, partial files and work directories spend the
namespace. Failure preserves evidence and never overwrites a previous result.
The parent independently checks the nine exact probe records, native exit,
typed completion/teardown fields, read ceiling, scratch ceiling, unchanged
actual task instance and absolute deadline before publishing
`probe-result.json`. Unproved outer teardown poisons the shared lease.

The Python observation alone remains incomplete. A native completed result
still requires independent review and grants no adoption authority.

## Verification

`tests/operations/test_qualification_bootstrap.py` covers closed envelopes,
source/window/limit drift, reused evidence, native byte-pin refusal, frozen
file locks, complete-tree refusal, scratch bounds and typed result readback.
`tests/operations/test_qualification_bootstrap_native.py` exercises actual
nested/exited reader accounting, read-limit refusal with cleanup, and the
nine fixed probes inside the existing native containment primitive.

The pipeline fixture isolates input validation with a disposable driver.
It exercises real probes but deliberately does not claim production identity,
registration, independently approved inputs, or host acceptance. Both files
run in the existing hosted qualification workflow; ordinary production-host
test admission rules still apply.

## Update when

Update when the adapter entrypoint, envelope schema, direct-review boundary,
probe set, resource limits or retained-result semantics change.
