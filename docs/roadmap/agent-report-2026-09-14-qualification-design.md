# Qualification bottleneck: proposed acceptance design

Date: September 14, 2026. Status: design for review, not an adopted runbook.
Request: fix the qualification bottleneck first; finish the design, then audit
it afresh from beginning to end. This document specifies the replacement;
the [separate audit](agent-report-2026-09-14-qualification-design-audit.md)
records the subsequent review. Neither document grants execution authority.

## 1. Decision and scope

Move complete regression qualification to non-capture Windows and Linux
environments. Retain a small, explicitly budgeted production acceptance phase
under the real S4U identity, followed by the existing guarded merge and capture
recovery. Replace the full-production-suite prerequisite only through a
reviewed, versioned acceptance contract. Do not reinterpret a smoke result as
a full suite, weaken resource limits, or repeat the same resource-bound suite
until it happens to survive.

The minimal delivery extends item 329's existing attempt machinery and the
[R2 qualification package in the reviewed reliability candidate](https://github.com/michaelbooth1/weather/blob/aaa7f2de19542f2ddc0c2953e0301433dcd69a93/docs/roadmap/items/item-331-overnight-reliability-program.md).
It does not require R4's unattended workstation role, a new coordinator,
cloud deployment, hardware purchase, immutable capture deployment, or maker
features. Those remain separate work. This design branch starts at fetched
`origin/master` = `3bdba3d15470d831710eeeb8c5885d1c9d4ae12a`; it contains
documentation only. Implementation must reconcile the exact then-current
reliability branch before producing new evidence; the referenced tip is not
already qualified under this proposed contract.

Why this addresses the failure: the September 13 host attempt stopped at
67.19% commit against its 66% abort limit after ten completed chunks, with a
native fixture failure also retained. A smaller-chunk successor on September
14 stopped during its first chunk at 68.5%. A successful preflight therefore
does not establish capacity for the entire suite. These are observed resource
refusals, not evidence of which unrelated process caused memory pressure.

Source inspection also finds that current Windows workflows select affected
files, not the complete Windows suite. The native-launch workflow checks out
the PR head explicitly; the general CI and settlement workflows use the default
PR checkout. GitHub documents that the default PR SHA is the synthetic merge
commit. Their green statuses cannot be combined into an exact-head, complete
Windows/Linux certificate without inspecting their tested identities and
coverage. See [GitHub event semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).

## 2. Authority and invariants

The active [integration runbook](../operations/INTEGRATION_ATTEMPT_RUNBOOK.md),
[host-load policy](../operations/HOST_LOAD_POLICY.md),
[delegation contract](../operations/DELEGATION_CONTRACT.md), and
[guarded merge runbook](../ops/streak-soak.md) remain controlling until the
replacement is explicitly accepted and adopted. Existing v1 attempts retain
their original contracts, immutable history, closure and recovery rules.

Preserve these properties throughout implementation and cutover:

- Complete applicable tests run somewhere qualified; a missing native test
  does not become an approved skip because its preferred runner is unavailable.
- Full source identity, actual import paths, dependency bytes, test plan,
  platform and external artifact identity are bound, not inferred from PR name.
- Production retains its shared lease, capture-health checks, ordinary 50 GiB
  disk floor on every involved volume, protected windows and continuous memory
  guard. Qualification initially keeps the stricter 64% start / 66% abort
  limits of the existing suite, rather than adopting the general 70% ceiling.
- Candidate processes are contained from suspended creation through proved
  zero-child teardown. The adopted parent establishes offline restrictions.
  A candidate cannot grant itself the production qualification marker.
- No candidate receives production credentials, live-order authority, capture
  control, or authority to publish production data. Source publication is
  distinct from production adoption; adoption is distinct from live readiness.
- Ledger precedence, nonempty label overlays, native units, WU cutoffs, release
  binding and existing truth-label BLOCK results remain unchanged.
- Failed attempts remain failed; uncertain publication is reconciled rather
  than retried. A reconciled historical gap does not manufacture a PASS.

## 3. Four distinct records

Use one acceptance policy and a small evidence graph, not another scheduler.
Names below are proposed schemas, not implemented commands or configuration.

| Record | Authoritative producer | Required binding | What it permits |
| --- | --- | --- | --- |
| `qualification_policy_v2` | Reviewed, already-adopted control plane | Policy revision/hash, trusted verifier and producer hashes, platform coverage, environment rules, host profile, validity and revocation rules | Defines admissibility only |
| `code_qualification_v2` | Trusted off-host publisher after all required jobs | Candidate S/tree, baseline B, coverage plan, dependency/artifact manifests, actual job/run-attempt identities, individual results and authenticated artifact digests | Eligibility to request host acceptance |
| `host_acceptance_v2` | Adopted capture-host parent | Policy and certificate hashes, attempt ID, S/B, installed environment, production config Q, current-input manifest D, exact S4U task, all probe/audit outputs and teardown | Eligibility for this attempt's guarded merge |
| `integration_attempt_merge_receipt_v2` | Adopted guarded integration parent | Both predecessor records, original/prepared baseline, exact two-parent merge, recovery, documentation transaction and remote acknowledgment | Existing downstream adoption gate, subject to its other requirements |

Use explicit enums for phase results: PASS, FAIL, BLOCKED, CANCELLED and
INDETERMINATE. Only PASS can satisfy a dependency. Report admission refusal
separately from executed test failure without weakening either gate. A process
exit, Scheduler state, log phrase, attestation, or manifest hash alone is
insufficient. The production verifier independently validates the graph.

All records use bounded strict schemas: duplicate keys, unknown critical fields,
wrong types, floating-point IDs, malformed hashes and unsupported versions
fail closed. Git IDs and remote run/artifact IDs are strings. Hash original
UTF-8 file bytes; do not reserialize JSON across Python and PowerShell and call
that the original hash. Lists are ordered where order has semantics. Store
canonical relative paths with explicit root IDs, reject traversal, case-fold
collisions, reparse escapes and unexpected links, and never execute a path or
command supplied by a downloaded result.

Each attempt has create-once inputs and terminal evidence, durable flushes,
atomic publication, an OS-held terminal mutex and a unique namespace. A partial
write has no PASS meaning. Receipt references form an acyclic graph with hashes
of all children; metadata limits and artifact extraction limits apply before
parsing. Raw transcripts/JUnit are retained outside the compact receipt, with
their hashes and exact locations recorded. Retain code evidence and verifier
trust material locally before arming adoption; seven-day CI retention is not
the operational archive. Never garbage-collect evidence reachable from an
attempt or rollback point through this feature.

## 4. Prepare exactly one candidate

1. Fetch the canonical remote; record synchronized production baseline B and
   reconcile the candidate so B is an ancestor of its full commit S. Review
   the cumulative B..S diff, not only its last repair. Freeze a clean isolated
   checkout, Git tree, tracked-file/content inventory and allowed artifacts.
2. Freeze the test plan from the complete tracked `tests/` inventory and the
   reviewed pytest configuration. Include relevant non-pytest checks from the
   development guide. Record deletions, collection-rule changes and added tests
   against B. Test-plan changes require review, not automatic acceptance of
   whatever the candidate happens to collect.
3. Inventory the production interpreter, installed distribution versions and
   package hashes, native PowerShell, approved Git, optional SDK overlay and
   external artifacts without reading credential values. Define platform
   manifests for matching Windows and equivalent Linux installations.
4. Pin exact resolved dependency distributions and their downloaded hashes,
   interpreter patch version/architecture and native prerequisites. Install in
   a clean isolated environment. A `pip freeze` list alone is not reproducible
   installation. Production venv mutation is outside the initial v2 scope:
   if its environment cannot be reproduced and verified, block and prepare a
   separately reviewed environment change. Never overwrite it during a merge.
5. Review the qualification-policy digest and approved producer/verifier set
   independently of S. If S edits the policy or verifier, its own qualification
   is still judged by the old approved policy. Qualification authority upgrades
   require the separate cutover described in section 10.

Changing S, required dependencies/artifacts, policy, required coverage or B
invalidates the corresponding candidate qualification. The first version is
deliberately strict: even a docs-only baseline advance requires a newly bound
certificate; no automatic ancestor or equal-tree shortcut. Serialize candidate
integration preparation to avoid needless rebasing and wasted runs. Never
amend or rewrite published source history to obtain identity equality.

## 5. Off-host code qualification

### Execution and complete coverage

Run the full collected suite on native Windows with Windows PowerShell 5.1 and
on Linux. Every workflow explicitly checks out S, proves `HEAD == S`, records
the tree and actual imported `weather` paths, and repeats identity/cleanliness
checks after execution. Record the workflow's own revision separately from
the tested source. Compile checks, agent documentation audit and roadmap lint
are required where the development contract requires them.

Use existing hosted runners for the repeatable CI path. The existing 32 GB
workstation is the fallback for required Windows capabilities the hosted image
cannot provide, through its exact assigned host/principal
`workstation_heavy.ps1` wrapper, shared portable/heavy mutex and Windows Job.
The attended role remains attended. Do not install an unattended worker or
relabel a privileged interactive result as S4U evidence. No production data or
frozen workstation mirror is needed for ordinary regression tests.

The reviewed coverage plan contains test files and per-platform collected node
IDs, including parametrization, collection errors, deselections and skips.
The trusted runner reports started/completed tests and native exit codes;
JUnit is corroborating evidence, not sole proof. Every planned chunk must be
present exactly once and end successfully; worker loss, cancellation, timeout,
missing tail, zero collection or contradictory totals cannot pass.

| Test disposition | Acceptance rule |
| --- | --- |
| Portable test | Run on both required platforms; platform-specific differences are explicit |
| Windows-native behavior | Executes on Windows; Linux skip names the Windows execution record |
| Real production identity/configuration behavior | A narrowly named case executes in section 7; off-host mocks alone are insufficient |
| Missing dependency, capability or unexplained skip | BLOCKED until provided or covered on another approved native runner |
| Existing expected failure | Reviewed exact node/reason/owner; retained as a limitation, not counted as passing coverage; new or changed xfail needs review |
| Deleted/deselected/newly skipped test | Explicit diff review and coverage disposition; no blanket directory exceptions |

Do not shard merely to maximize concurrency. Begin with serial chunks in each
OS job and measured limits; additional off-host sharding is optional after
deterministic partition/aggregation and resource tests. A run attempt is
atomic: a rerun starts a new full evidence set; do not splice successful shards
from different run attempts. CI cancellation before certification produces no
certificate. After a certificate is sealed, transport/job cleanup cannot
change its bytes or the referenced terminal results.

### Provenance and trust

The producer workflow and publisher are pinned by the independently reviewed
policy, including action commit IDs and collection/aggregation code. Candidate
workflow edits cannot approve themselves. Use a separate trusted publisher job
that validates bounded data and never runs downloaded candidate code. It checks
repository identity, event, workflow revision, actual S, exact run ID/attempt,
all expected jobs, conclusions and artifact digests. No name-only or
latest-success lookup is authoritative. Candidate jobs have no production
secrets, deployment token, persistent checkout credentials or signing role.

Bind the sealed bundle to authenticated GitHub provenance, including signer
workflow identity and approved revision. Retain its attestation bundle and
trusted-root material for verification on the network-restricted S4U host.
GitHub documents both [artifact provenance](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
and [offline verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline).
Pin and test the verifier and root-update procedure; missing or expired trust
material blocks import. If repository/service capabilities cannot provide this
path, specify and separately review a replacement authenticated transport;
do not silently fall back to an unsigned uploaded JSON file.

An attestation proves origin, not that tests are sufficient or honest. Source,
test-plan and workflow review remain necessary. This mechanism defends against
mistakes, substitution, stale results and an untrusted artifact crossing into a
privileged consumer; it is not a claim that arbitrary malicious test code is
proved safe by a signature. The trusted publisher never loads candidate Python
or uses `pull_request_target` to execute candidate code with elevated access.

Before arming, the source-control principal retrieves the exact bundle and
current remote run state through the existing authorized route. An import
receipt binds the authenticated query, exact IDs, bundle and policy. The S4U
task consumes only sealed local files. Code evidence expires seven days after
completion; remote disposition/revocation validation must be within 60 minutes
of arming. Policy/source/environment mismatch invalidates it immediately.
These are proposed conservative validity defaults, not existing guarantees.

## 6. Attempt planning and resource admission

Extend the immutable attempt manifest with `qualification_mode = split_v2`,
policy/certificate hashes, bounded host plan, input/config manifests, exact
task/principal bindings, deadlines and the existing merge/recovery bindings.
Never put v2 data into v1 `suite-receipt.json` or invent an `ALL CHUNKS PASSED`
log to satisfy a legacy caller. Existing v1 manifests execute under v1.

The planner runs before the overnight window. It validates all off-host proof,
retained bytes and available disk and emits READY_TO_ARM or one specific
blocker. It cannot reserve future memory; actual admission rechecks under the
shared lease. It also checks active markers, predecessor closure/successor
claims, source/baseline synchronization and current task definitions before
registering any successor. No duplicate Scheduler or automation owner is added.

Proposed initial host budgets, all stricter than outer policy:

| Phase | Wall-clock maximum | Process-tree cap / boundary |
| --- | --- | --- |
| Identity/import/config and native probes | 8 minutes total | 512 MiB private commit and working set; one contained child at a time |
| Fresh settlement audit, including bounded input staging | 20 minutes total | 2 GiB private commit, 1.5 GiB working set; no increase to a stricter existing limit |
| Pre-merge validation and receipt publication | 2 minutes | Bounded metadata only; hashes stream |
| Qualification teardown reserve | 2 minutes inside the absolute deadline | Hold lease until proved zero children |

These are design ceilings, not measured completion promises. Measure peak
working set/private commit for the parent plus full child tree, disk scratch,
CPU and elapsed time on representative synthetic and admitted current inputs.
Freeze a lower per-phase envelope if the actual implementation needs less.
For admission, project start consumption plus that full envelope and leave at
least 4 GiB physical availability and the 66% commit ceiling; also apply all
existing stricter admission checks. Refuse on unknown measurements. Monitor
capture freshness and resources throughout, not just between chunks. A job
that cannot fit must be optimized or moved to a separately qualified data
handoff path, not given a larger capture-host cap.

For a roll-sensitive candidate, target 00:30 host acceptance, complete by 01:02,
and merge only at/after 01:00 when evidence is ready. The planner computes the
actual remaining time using measured phase bounds plus teardown and guarded
merge/rollback reserve, rather than relying on these target times. Retain the
existing latest merge-start cutoff and the quiet wrapper's safety checks; do
not start late merely because the outer 09:00 heavy deadline is farther away.
Do not overlap the reserved 04:45-06:45 tiering block. Register consumer first,
preserve the exact one-shot S4U/Limited/no-StartWhenAvailable contract, and
reject ambiguous or nonexistent DST wall times. A missed slot is a recorded
deferral, not permission to run in the protected windows.

The entire host plan is under one absolute deadline; the merge phase receives
its own existing containment/recovery budget. A consumer waiting on evidence
holds no workload lease. Do not release a lease while children survive. If
teardown is uncertain, block successors and retain the relevant poison/active
marker and process creation identities; resource recovery follows the owning
host contract. Killing an exact task is not by itself zero-child proof.

## 7. Real-host acceptance and current evidence

The trusted adopted parent verifies every frozen byte before starting candidate
Python, clears ambient import/Git/credential controls as the existing runner
does, installs the existing offline policy itself and verifies the actual
candidate module paths. Use disposable fixture roots for native probes. The
probe manifest contains an explicit inventory, no implicit "smoke everything".

Required probes cover: actual Windows installation/principal/logon mode;
selected Git and Python identity; sanitized launch/import from the isolated
candidate; duplicate PATH handling; bounded native stdout/stderr; timeout and
zero-child teardown; intended inherited handles only; create-once receipt and
rename/flush semantics; read-only configuration and SDK-overlay compatibility;
and three-worker health before and after. Hosted fault injection covers the
destructive cases. Production probes must never kill a capture worker, change
its priority, rotate tapes or alter real protected ACLs to demonstrate safety.
The small fixtures exercise the actual launch path without such side effects.

Bind current config Q separately from tested program source S. Q includes the
two allowlisted generated location/event files, relevant non-secret active
settings, registry and release-pointer/artifact identities. Freeze exact bytes
and validate the production overlay against S in the host phase. V2 initially
permits only the existing two generated-file differences at merge preparation;
their exact Q hashes must already have been checked. A changed registry,
artifact, serving pointer, code file or environment is not a harmless config
exception. The resulting merge tree must equal S outside the explicitly
declared generated pair, and that pair must equal Q. No unreviewed rebuild or
last-minute install is permitted. Record both source-tree and effective
configuration identities without claiming the merged commit was tested as S.

Run the reliability candidate's current settlement-source audit against all
required current authoritative ledgers and the labels projection, with a fresh
index and no cached audit result. Derive required markets from the frozen
registry; the present 12-ledger expectation must not become a permanent count.
Read complete declared inputs, including tails; preserve encounter order,
last-encountered ledger semantics, nonempty overlays and late revisions.
Missing, malformed or truncated inputs block this acceptance, even when a
historical report previously passed. A frozen August workstation mirror cannot
substitute for these inputs.

Input manifest D records ordered file identities, root/relative path, byte
length, raw SHA256, coverage/cutoff and label/ledger generation. For a live
append-only ledger, copy/hash a fixed complete-record prefix through a shared
read handle, record its ending offset and prove the prefix unchanged. For a
replaced projection, capture a stable file identity/generation. Detect removal,
replacement, late append or same-length rewrite through end-of-audit and
pre-merge validation. Initial v2 accepts only an unchanged complete generation:
any later relevant change requires a new bounded audit in a new attempt. No
row is silently excluded by choosing a convenient earlier cutoff.

Stage exact read-only input snapshots inside the admitted budget, retaining
lineage to canonical sources; never lock live writers for the audit duration.
Account for copies, indexes, outputs and receipts against disk reservations
before allocating. Never recursively scan unrelated `data/`. A size or deadline
limit produces a non-authorizing partial result with observed coverage, not a
PASS. If complete-current-input processing cannot meet the host budget, stop
v2 adoption until R3 is improved or the separate sealed-data off-host lane is
qualified. Design completion does not assert that this performance gate is met.

Distinguish algorithm acceptance from economic acceptance. A well-formed audit
that faithfully reports existing truth-label BLOCKs can prove its computation
and resource behavior; its downstream outputs must retain those BLOCKs.
Freeze expected semantic acceptance before running: fixture parity, full input
coverage, internally consistent counts, canonical gate decisions and unchanged
consumer behavior. Do not change the expected answer after seeing current data.
Retain bounded consumer checks for the audit output format and its full tail.

The host receipt requires every probe, audit and teardown result, fresh capture
identities and resource maxima. It expires 30 minutes after completion and on
any relevant drift; it applies only to its exact attempt and local adoption
day. Revalidate Q/D/environment/policy and fresh three-worker health immediately
before merge under the merge lease. A receipt from an earlier night cannot
authorize a new night's adoption.

## 8. Guarded adoption and rollback

Use the existing `roll_verdict.ps1`; classification is never hand-derived.
Only a trusted adopted integration consumer may invoke the unchanged guarded
merge primitive after validating the complete v2 graph. Candidate-owned
wrappers cannot be the authority for their own invocation. The consumer freezes
its dependency closure, selected native tools and exact push-task definition.

Immediately before mutation, prove branch `master`, synchronized HEAD/local/
remote baseline B, candidate S/ancestry/cleanliness, Q/D and certificate
validity, task identity, no competing marker or attempt, roll verdict and
remaining safety window. The existing generated-config preparation may produce
Bq; record its exact parent and allowlisted Q content. Require the final commit
to have parents Bq (or B) and S and verify its effective source/config tree.
Any other merge resolution invalidates qualification and is not improvised on
production. The source branch never rewrites published history.

The guarded wrapper continues to perform local integration, three-worker
recovery plus required execution-tape recovery, documentation transaction,
then `WeatherOneShotPush` and exact remote acknowledgment. A source merge does
not deploy Scheduler definitions automatically. Emit v2 PASS only after the
same historical recovery/publication facts that v1 requires are established.
The downstream validator learns v2 explicitly; unmodified consumers reject it.

Before publication, failed recovery rolls back to the exact recorded baseline
using the established generated-config preservation and recovery contract.
Require proof of recovered baseline workers; preserve all failure evidence.
After a recovery-proved commit or possible publication, do not initiate a new
merge or treat absent final receipt as non-integration: use the existing marker,
immutable report and reviewed reconciliation/resume rules. A published change
is reversed through a reviewed new commit/guarded roll, not remote history
rewriting. Data and environment migrations are outside initial v2 so rollback
does not require undoing a schema or package installation.

## 9. Failure and retry table

| Boundary/failure | Required disposition |
| --- | --- |
| Incomplete Windows/Linux coverage, deterministic test failure, mismatched source | No certificate; repair and qualify a new reviewed S |
| Runner outage, transient transport failure | New off-host run attempt, bounded retry; retain prior failure; no mixed-run results |
| Certificate missing, revoked, stale, unsigned or wrong workflow | BLOCKED before host registration/launch; no implicit weaker fallback |
| Host cannot admit budget or missed trigger | Non-authorizing terminal result; close exact tasks before a successor; no capture restart to make room |
| Current inputs/config/environment changed | New bound host attempt and audit; code certificate reusable only if its S/B/policy/environment remain valid |
| Resource breach or candidate timeout | Terminate contained tree, prove cleanup, keep failure, diagnose; do not repeat indefinitely unchanged |
| Partial registration, task action changed, task absent | Existing intent-bound closure/recovery; exact identities, no broad name-based disabling |
| Merge committed or push possibly happened | Reconcile/resume publication from durable evidence; never ordinary retry |
| PASS bytes exist but contradictory/unfinished task or teardown | Not authority; apply existing bounded terminal-grace checks and require cleanup |
| Receipt published then controller crashes | Idempotently read/validate immutable evidence; no rerun or replacement receipt |

Retain item 329's single successor claim and one reviewed unchanged retry for
classified transient production failure. A second resource refusal triggers
diagnosis or plan repair. Old receipts are not overwritten; manual review and
exceptions must name exact source, scope, expiry and evidence.

## 10. Bootstrap without self-approval

The old acceptance gate requires a full host suite; it cannot truthfully emit
that PASS for the new split method. The new verifier cannot be trusted merely
because its own certificate says it passed. Resolve this openly with one narrow
first-landing decision, not a hidden waiver or an endless legacy-suite loop.

1. Build a minimal control-plane-only increment K from the current baseline.
   It adds v2 verification and host acceptance without including unrelated
   reliability/maker runtime changes. Qualify K off-host and audit its cumulative
   diff, input parser, launch dependencies, negative cases and rollback.
2. Prepare a concrete first-landing envelope for separate explicit owner
   acceptance. Bind B, K/tree, approved test/coverage records, policy/verifier
   and adapter SHA256s, every dependency, precise host probes, resources,
   current-config rules, time window, quiet-merge primitive and exact invocation,
   receipt destinations, single-use ID, expiry and rollback. Approval must state
   that this evidence replaces the full-host-suite prerequisite for K only.
   The present request to design the replacement is not that approval.
3. The envelope authorizes one small externally reviewed bootstrap adapter as
   a temporary trust root. Its bytes and closure are inspected independently of
   K and its self-tests; the owner-reviewed envelope is the authority. The
   adapter cannot select a new tip, policy, verifier, command, deadline or scope.
   Use the already-adopted workload admission, offline-marker installation and
   containment primitives. If a needed primitive cannot safely run the bounded
   probe, repair the adapter/envelope and re-review; do not run candidate code
   uncontained or change the installed hook.
4. Run the actual S4U bounded probes for K in the normal admitted window. A
   control-plane-only K requires configuration/fixture acceptance, not the
   unrelated large settlement rewrite's current-input audit; the reviewed scope
   establishes this distinction in advance. The bootstrap result has its own
   schema and is never a legacy full-suite result.
5. After independent verification, that adapter calls the already-adopted
   guarded quiet-merge primitive for K, with exact baseline/tip/self hashes.
   Preserve roll-verdict, lease, recovery, documentation and push checks. The
   primitive does not itself supply the missing qualification policy; the
   explicit envelope supplies this single bounded exception. No `-Force`,
   expired historical exception token, marker edit or fabricated v1 receipt.
6. After recovery and acknowledged publication, record K's installed verifier/
   policy as the v2 trust root, revoke the bootstrap ID and close its exact
   tasks. Registration of recurring/new v2 tasks still requires the applicable
   Scheduler authorization. Qualify the reconciled reliability candidate under
   K's v2 contract, including the complete current-data audit, before its own
   guarded adoption. Its prior green workflows are not sufficient certificates.

Future policy/verifier upgrades are qualified by the currently adopted version
and receive explicit policy-change review. If incompatible, use another
explicit narrowly reviewed transition, never a generic skip switch. Keep the
old v1 reader/closure/reconciler until all historical attempts can still be
classified and safely closed. Production gating rolls back to the old policy
if v2 acceptance is defective; that may block new integrations, which is safer
than granting an unproved one. Capture continues on its recovered source.

## 11. Implementation sequence and acceptance

| Increment | Owning surfaces | Reviewable acceptance |
| --- | --- | --- |
| A. Source and coverage evidence | `.github/workflows/`, trusted runner/publisher, package operations verifier and tests | Full Windows/Linux inventory with explained skips; exact S and environments; independently authenticated bundle; tamper failures |
| B. Read-only v2 verifier | `src/weather/operations/`, strict schemas, `tests/operations/` | Table-driven valid/invalid evidence graph; no remote execution or adoption; compare with retained v1 proof without upgrading it |
| C. Bounded host acceptance | `scripts/ops/`, package audit/probe helpers and native tests | Measured budgets, exact S4U evidence, offline launch, current-input parity and stable lineage; interruption/zero-child proof |
| D. Attempt/consumer integration | Existing create/register/suite-or-host/merge/assert/close/dispatch/reconcile scripts | Explicit v1/v2 routing; immutable claims, deadlines, recovery and downstream checks all covered |
| E. Accepted first landing and one candidate adoption | Exact bootstrap envelope, then ordinary v2 attempt | K adopted safely, then one complete reliability-candidate evidence chain; no fictional full-host PASS |

Keep A-D in one coherent minimal qualification candidate if splitting them
would leave an unusable trust transition. Implementation tests must exercise the
actual parent/consumer decision functions and native boundaries, not merely
search source strings. Update owning runbooks, development matrix, agent routing,
schema registry and the existing numbered item's evidence in the same change.
Reconcile the competing prepared item-331/332 number assignments before changing
the master roadmap; this design does not create a duplicate numbered item.

Required fault cases span wrong source/tree, changed policy, unsafe path,
duplicate JSON key, altered artifacts, forged JUnit-only success, missing native
coverage, hidden deselection, mixed run attempts, stale trust/receipts, environment
drift, wrong S4U principal, failed process assignment, child/grandchild leak,
partial output, full disk, rewritten/extended ledger, final config drift,
duplicate registration, simultaneous successors, every commit/push crash
boundary and incompatible old/new receipt readers. Retain original and repaired
outcomes. Prove import/collection identity using clean checkouts without `data/`.

The release-readiness checklist is finite: no open critical/high design or
implementation findings; complete cross-platform coverage; authenticated
evidence; measured host budgets; bounded native fault tests; correct v1/v2
compatibility; reviewed first-landing envelope; guarded recovery and rollback.
No calendar-only seven-day waiting gate is added before the first safe landing.

After cutover, observe the next seven available adoption opportunities and
record qualification time, queue delay, host peak memory/scratch, completed
versus blocked evidence, manual intervention and capture disruption. Target:
complete off-host qualification before arming; host acceptance within its
32-minute ceiling; zero guard bypasses, false PASS results or qualification-
caused capture interruptions. Capacity refusal remains a failure to meet the
operational target, even when safely blocked. If the current-input audit remains
the bottleneck, improve that bounded path next rather than rebuilding the
qualification framework. No claim of long-term reliability or trading edge
follows from these initial observations.
