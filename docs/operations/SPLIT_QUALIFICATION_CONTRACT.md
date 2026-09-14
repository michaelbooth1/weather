# Split qualification implementation contract

Status: proposed control-plane implementation, not an adopted production gate.
The [integration-attempt runbook](INTEGRATION_ATTEMPT_RUNBOOK.md) remains the
authority until the exact [first-landing transition](../roadmap/agent-report-2026-09-14-qualification-design.md#10-bootstrap-without-self-approval)
is explicitly accepted. A development workflow, registered schema or structural
verifier result cannot grant that authority.

## Records and trust

`weather.operations.qualification` owns bounded original-byte records, source
and environment inventories, complete coverage, native event/JUnit agreement,
authenticated remote-state bindings, and offline provenance verification.
The [schema registry](../../src/weather/schema_registry_qualification.py) owns
record names and their implementation modules. References bind the original
UTF-8 bytes; paths are canonical and relative to an explicitly selected root.

An independently selected policy and review are trust inputs. A downloaded
certificate cannot nominate either one, a native executable or a command.
Structural verification deliberately returns `eligible_to_arm=false` until the
adopted caller verifies the pinned native attestation result, independently
sealed import and current local revocations. All required native chunks and
repository checks must be present; JUnit alone is insufficient.

Publication claims are create-once and OS-locked through durable flush and
atomic no-replace publication. A failed or interrupted publication spends its
namespace. Retain partial bytes and claims for reconciliation. Do not remove
them to turn a failed attempt into a retry.

## Native execution boundary

[`windows_kill_on_close_job.ps1`](../../scripts/ops/windows_kill_on_close_job.ps1)
retains the existing scheduled-wrapper APIs. Its bounded APIs add explicit
aggregate Job commit and process limits, BelowNormal priority, a completion
port, a capped stdout/stderr pipe, and explicit inherited handles. The child is
created suspended, assigned, and only then resumed. Assignment or output-file
creation failure terminates the suspended child and waits for native proof.

`EncloseCurrentProcess` places the controller, its monitor/output-reader threads
and every descendant in an enclosing aggregate memory Job. That Job deliberately
does not kill the controller when its handle closes. A nested kill-on-close Job
owns candidate teardown, including parent death. `TerminateAndWait` refuses the
controller envelope. Reviewed phase transitions may change the enclosing limit;
closing the envelope does not exempt the running controller from its limits.

[`qualification_process.ps1`](../../scripts/ops/qualification_process.ps1) samples
the enclosing native process inventory and memory, bounds the transcript and
absolute/monotonic deadlines, reserves teardown, and proves no descendants remain.
Capture mode adds the stricter 64% initial and projected 66% commit checks, 4 GiB
physical headroom, the ordinary 50 GiB floor on each declared volume, and repeated
three-worker identity/heartbeat checks. Admission and launch-policy installation
belong to its adopted caller; dot-sourcing this helper grants neither.

Working-set and current private-byte maxima are sampled across the controller
and descendants. A sample gap over one second refuses execution. Native Job
peak accounting is retained separately: Windows can include a refused allocation
attempt in that counter. Never clip it to the limit or report it as resident
consumption. Completion notifications are supplementary; their absence cannot
prove that a limit event never occurred. See Microsoft's
[Job notifications](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_associate_completion_port)
and [nested Job limits](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs).

Output failure and cleanup are separate facts. A capped, failed or incomplete
transcript cannot complete a phase, even when native zero-child teardown is
proved. Unproved teardown retains the caller's lease/poison boundary. This
helper's `completed` field is process evidence, never host-acceptance authority.

The host identity reader queries the actual primary token, authentication LUID,
elevation and native logon session. A production invocation requires an
unelevated batch logon plus the exact S4U task action and one Scheduler instance
whose engine belongs to the wrapper's bounded ancestry. Registered task settings
alone do not prove that an interactive process is that invocation. The reader
uses Microsoft's documented [token statistics](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-token_statistics)
and [logon session data](https://learn.microsoft.com/en-us/windows/win32/api/ntsecapi/ns-ntsecapi-security_logon_session_data).
Hosted token/argument tests do not substitute for actual capture-host S4U probes.
## Current-input generation

`inputs.open_current` is intentionally separate from immutable evidence reads:
it shares the live source with writers and replacement. It never locks or pauses
capture. The stager copies a complete observed generation, retains original bytes
and file identity, rehashes the complete source, and records read intervals.
Replacement, append, deletion or same-length byte changes invalidate the attempt.
Optional missing lineage is explicit; an appearance at later validation is drift.

All read bytes, including repeated validations and staged parsing, consume one
absolute byte/time budget. A parser that does not consume and authenticate the
entire declared file cannot satisfy input integrity. Complete ledger records
must end in a newline. Blank lines remain ignorable. Malformed JSON, duplicate
keys, invalid object types, nonfinite values, duplicate CSV headers and incorrect
CSV widths block qualification without changing ordinary audit semantics.

`settlement_inputs.prepare` reads the complete registry-selected ledger set and
labels projection. Its bounded SQLite index preserves last encounter within each
source and nonempty label overlays solely to discover the actual lineage closure.
It does not stage unused alternative payloads or classify settlement truth.
Undeclared roots, unsafe aliases and extra market ledgers are refused.

The audit's optional `input_reader` dependency supplies staged label/ledger rows
and lineage hashes. Ordinary callers retain their existing readers and gates.
`SealedAuditReader` resolves only the declared generation, preserves original
lineage names, and has a per-invocation verified-copy hash cache. Revalidate all
staged bytes after the audit and the complete current source generation before
mutation. These checks do not claim an atomic cross-file producer generation.
No candidate or downstream caller may convert an existing truth-label BLOCK to
PASS because staging, computation or resource checks completed.

## Off-host execution

`qualification.runner.Runner` accepts an independently pinned launch closure,
native executables, external dependency sites and separate trusted/candidate
checkouts. It executes fixed collection, chunk, import and repository-check
commands serially. Candidate children start with `-I -S`; the trusted bootstrap
loads its guard before adding approved source and dependency paths. Candidate
`sitecustomize` and installation `.pth` hooks do not run in this lane.

The environment is an allowlist with scratch-owned home/temp directories and no
inherited CI credentials. The Python audit guard refuses external network and
credential access and writes outside assigned scratch. It is a guard for reviewed
offline commands, not a security sandbox for hostile native code. The native
controller and exact command/dependency review remain required.

Windows uses the native Job controller. Its dispatcher rejects the dedicated
capture installation, validates integer limits and scrubs CI identity before
candidate launch. Linux uses a child-free serial parent, a native subreaper and
complete `/proc` descendant accounting. Teardown retains parent identity until
exit and uses PID file descriptors when signalling descendants; double-forked
new sessions remain owned. Linux aggregate RSS is monitored and bounded; this
does not claim a kernel aggregate allocation limit equivalent to Windows Job
memory enforcement. Both platforms retain bounded output and require EOF and
durable flush, explicit zero-descendant proof and a native exit consistent with
the complete journal. Partial output and failed commands retain spent paths.

Every collection, test chunk and repository check binds a separate process
record. The verifier rejects absent/failed cleanup or resource proof even when
the test journal and JUnit report success. Complete collection is corroborated
by its actual collection-only event stream, not a producer-supplied node list.

`producer.run_job` revalidates complete Git source and baseline inventories,
the installation's raw bytes, all installed RECORDs and unexpected site files,
then native imports before and after execution. Coverage is predetermined by
the independent review. `installation.prepare` verifies the complete retained
wheel set and emits a fixed offline, hash-required, no-dependency-resolution pip
invocation into a new prefix. A plan or completed installer alone is insufficient:
the producer must match the full resulting environment against the review.

`publisher.seal` reads the actual authenticated exact-attempt jobs and requires
both native jobs to have completed successfully while the selected publisher is
running. Its code certificate is validated before its final path is published.
Only the separate publisher job receives attestation authority. The signing
action is pinned to a full commit of GitHub's
[attestation action](https://github.com/actions/attest), and the signature binds
the producer revision separately from the tested candidate revision.

`transport.Github` reads only the selected repository's Actions API. It bounds
time, metadata, artifact bytes and extraction, rejects pagination omissions and
redirect ambiguity, and never forwards authentication to artifact storage.
`importer.import_bundle` retains original API response bytes, rechecks all four
current/exact-attempt/job/artifact pages, invokes the adopted contained signature
verifier and seals the import only after graph, signature and cleanup success.
An artifact download or saved verifier JSON is not an authenticated import.

`verifier.ContainedVerifier` is the concrete off-host implementation of that
invocation. It rechecks the pinned interpreter runtime, native executable and
launch closure before and after execution. Its no-site child runs only the fixed
offline `gh attestation verify` command; stdout and stderr have separate 2 MiB
bounds and create-once retained files. Only actual zero-exit output with proved
native cleanup reaches signature interpretation. Runtime exclusions are exact
independently reviewed paths, including any unused platform linker aliases;
included paths still reject redirection and every used executable is pinned.

Separate unprivileged Windows/Linux jobs consume the bootstrap protocol fixture
and exercise this actual contained binary invocation, including rejection of a
wrong signer revision. The fixture tests replace only the graph-to-argv step;
they do not claim that the fixture is a production code certificate.

The bootstrap workflow also signs a fixed public protocol fixture in a job with
no candidate checkout. It retains the actual verifier version/hash, signature,
trust roots and JSON output, and tests the documented
[offline verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline)
command in a fresh network namespace with an empty credential/config directory.
This fixture is never a production certificate or a policy trust root.
The manual [`qualification.yml`](../../.github/workflows/qualification.yml)
executes only at its independently approved producer revision. Dispatch inputs
pin the complete candidate commit, preparation artifact bytes and a separate
`qualification_dispatch_v2` reference. That authority binds both native profiles,
their reviewed environment/coverage evidence, retained wheel artifacts, external
executable paths and the full base interpreter/pip closure. Source inspection or
environment discovery does not approve the observed values automatically.

The installer checks that entire closure before and after its bounded invocation.
Its `-I -S` bootstrap selects only the pinned pip import roots and never processes
site hooks. The resulting isolated prefix must reproduce every installed file
against the review. Native tools and dependency roots must be outside candidate
source. OS installations may use stable hardlinks; retained evidence files still
reject hardlinks and every native byte/identity remains checked.

The native jobs have read-only source/Actions permissions. The separate publisher
downloads only data files, rejects disagreements between native evidence copies,
authenticates both completed jobs and signs only its checked code certificate.
The final artifact carries that certificate graph plus the native attestation.
Workflow dispatch does not create a production task or change either host gate.

## Host audit computation

The fixed host audit child imports the candidate audit only after the trusted
offline guard is installed. Its resolver/control modules execute from separately
pinned in-memory bytes under a private package name; candidate imports cannot
replace them. Every loaded `weather` module is checked against the source
inventory before and after the audit. Candidate-facing readers use only sealed
input bytes and cannot fall through to a mutable production path.

Input preparation, the actual audit, complete output readback, consumer checks
for every output date, and current-generation revalidation share cumulative read
accounting. Computation evidence retains existing semantic BLOCK outcomes and
explicitly requires current validation. Its availability does not prove host
admission, S4U identity, phase timing or integration eligibility.

The fixed pipeline controller now executes staging, the isolated candidate audit,
complete output readback, and final current-generation validation in one native
process tree. Its parent owns one absolute execution/teardown deadline and one
aggregate memory cap. The controller carries every read count forward; it never
resets the audit budget between phases. The audit child has only one computation
mode and one writable output directory. Staged inputs, controller scratch and
parent receipts occupy separate, non-overlapping roots. The controller explicitly
names its approved interpreter on Windows as well as Linux, and publishes final
current-validation/pipeline records only in its own receipt directory. An output
BLOCK remains BLOCK. Pipeline
completion alone leaves integration eligibility false until host identity,
admission, probes, configuration/environment and final native cleanup are proved.

## Frozen adopted execution source

`frozen.freeze` creates the attempt's control copy from actual adopted B Git
blobs, independently of dirty working files. Its code-owned selection includes
every canonical package Python file, operations Python/PowerShell file, tracked
configuration file and package bootstrap. It excludes runtime data and artifacts.
No candidate evidence can reduce this set. The owning native parent must admit
and bound the copy and every later rehash.

Before each deferred launch, `frozen.validate` compares the complete file set,
raw SHA256s and Git blob identities against B. Extra bytecode, missing imports,
or substituted bytes invalidate the copy even if an adjacent SHA256 was changed.
Read-only copies preserve the source while S enters the production working tree;
they do not themselves confer invocation or integration authority.

## Effective merge tree

`merge_tree.preview` computes Git's complete S-plus-Q tree in memory without
changing the production index or invoking a merge driver. Only the canonical
generated pair can overlay S. Initial v2 refuses tracked artifact changes;
it has no environment or artifact migration lane. When an existing working
artifact is an expanded LFS payload, its complete SHA256 and size must match the
actual S-bound LFS pointer. Git tree identity remains the pointer identity.

The stage and commit checks compare the entire Git tree and exact two parents.
The working-byte check separately detects an unstaged rewrite hidden behind a
correct index, and generated configuration must retain both its bytes and file
generation. These helpers need calls from the guarded primitive at each required
boundary; their availability alone does not enable split integration.

Native regression fixtures bind their disposable copied host assignment to the
actual test installation. They retain production identity checks, canonical
temporary paths and offline LFS pointer handling; they never change the real
assignment, Scheduler, capture roots or expected acceptance outcomes.

## Shared attempt lifecycle

The common task-binding and immutable registration readers select the prerequisite
per manifest: a historical v1 `suite` or an explicit v2 `host`. V2 never supplies
suite fields or a full-suite log. Schema selection is local to each attempt, so
reading a v2 attempt cannot change how a v1 predecessor is closed or verified.
Both phases reuse the same exact S4U/Limited tokens, no-catch-up settings,
pre-registration intent and identity-bound task closure. The host task has a
34-minute Scheduler backstop; its inner absolute execution/teardown plan remains
the tighter authority. The historical suite retains its existing settings.

The typed Python attempt reader binds the reviewed source/baseline, separate host
plan, adoption day, canonical evidence names and attempt-local adopted control
copy. It rejects suite aliases and mismatched scopes. Code consumption performs
the full certificate/import/revocation checks and actual native signature
verification. Both functions return no standalone integration authority; native
identity, measurement, lifecycle and mutation-boundary checks remain mandatory.

`integration_attempt_host.ps1` is the fixed native parent. It requires its exact
S4U instance and adopted attempt-local control copy, owns the shared workload
lease, executes the four code-owned child phases with whole-tree telemetry,
and retains a separate host receipt. Unknown native teardown poisons the attempt
and retains the lease. `host_acceptance` checks complete measurement and phase
records, the fixed probe inventory, current-input scope, and receipt expiry.
The configuration check covers all tracked config/artifacts plus the current
release pointer (including absence) and the complete pointed-to release directory.
The parent and its real-host measurement path still require native qualification;
source availability and parser acceptance do not qualify production.

The public manifest reader still rejects v2 until the complete host and guarded
adoption entrypoints are connected. Native fixture acceptance of a v2 task binding
alone cannot arm a task or replace the legacy suite prerequisite.
## Verification and first landing

[`qualification-bootstrap.yml`](../../.github/workflows/qualification-bootstrap.yml)
checks out the exact PR head on Windows and Linux, retains the native environment,
runs focused faults and repository checks, then the complete suite with native
event journals and JUnit. Its ordinary dependency installation is development
evidence; it does not claim a reproduced approved production environment or emit
an authenticated code certificate. Keep its exact run-attempt artifacts for
direct bootstrap review.

Native tests exercise actual Windows Job/pipe/process behavior, controller
accounting, memory refusal, output flooding, timeout, creation failure, parent
death and cleanup. Input tests use disposable fixtures and compare the real audit
with its sealed reader, including revisions, nonempty overlays and truth BLOCKs.
They require no ignored production data.

First landing must bind the final cumulative source, complete reviewed evidence,
policy/adapter/verifier closure and a single-use owner envelope. The host's real
S4U probes and measured resource gate remain separate from hosted CI. A green
workflow is not permission to invoke the new production lane.

## Update when

Update when a record, trust boundary, native resource/teardown mechanism, input
resolver or qualification invocation changes. The numbered integration work item
and retained attempt receipts own implementation/adoption status.

The host's frozen control record also binds `qualification_git_policy_v2`.
It rejects configuration includes, external merge/diff drivers, additional
filters and attribute changes; fixes empty hooks and global/system exclusions;
and binds any required Git LFS executable to the qualified native inventory.
Every host metadata child uses the verified interpretation. The guarded merge
integration remains disabled until these checks are wired at its mutation
boundaries and their native execution is verified.