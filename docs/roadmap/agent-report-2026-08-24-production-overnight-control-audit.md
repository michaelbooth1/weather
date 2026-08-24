# Production overnight control audit -- 2026-08-24

This is dated audit evidence, not the canonical current-state page. Current
operations remain owned by `docs/operations/STATE_OF_PLAY.md`.

## Verdict

The production safety controls worked: neither the failed integration attempt
nor the stale settlement-recovery task changed production, started a live
exchange action, or exposed a credential value. The overnight plan nevertheless
failed its operational objective because readiness was asserted before every
remaining operator dependency and time-sensitive binding had been proved.

The central classification error was treating each of these as progress:

- a reviewed local repair that had not been published;
- a recovery dispatch that explicitly required an active agent;
- a host-local resume helper that nobody had acknowledged running; and
- an enabled future task whose boot and source bindings had already become
  stale.

None of those states is unattended readiness.

## Evidence-backed timeline

| Local time | Event | Actual outcome |
| --- | --- | --- |
| 2026-08-23 20:38 | Credential-reconciliation candidate `75b0b8954fd14fb275ed983ae984bf1cf6b13749` committed | No Python verification was permitted in the protected host window. |
| 20:56 | Attempt `credential-reconcile-0824-a1` frozen | Exact manifest scheduled the suite for 00:30 and merge for 03:10. |
| 21:14 | Both attempt tasks registered | Registration was valid, but it proved task identity rather than branch correctness. |
| 2026-08-24 00:30--00:31 | Integration preflight ran | 139 tests ran; three assertions exposed two deterministic governance defects. The full suite did not start. |
| 00:50 | August 17 settlement recovery fired | It refused before child launch because the frozen post-boot proof described the prior boot. Its frozen workload-admission hash was also stale. |
| 01:21 | Failed integration attempt closed and dispatched | Both exact tasks were disabled. The dispatch required reviewed active-agent recovery. |
| 01:25 | Repair `cb1745d2524145ba77786d37332d6ebc9e9c20f0` committed | Its focused 139-test preflight passed locally. |
| 01:32 | Host-local resume helper created | It still required an interactive publication and registration action. No acknowledgement followed. |
| 09:00 | Documentation transaction deadline | The transaction from the prior production merge became overdue. |
| 09:30--11:47 | Repository-owned Stage A ran | It completed 17/25 steps, terminalized `RESUMABLE` at `ten_minute_model_performance`, and its absolute deadline returned Scheduler `0x4B`; the isolated child is gone. Host protection worked, but the chain did not complete. |

Morning proof showed that `origin/codex/credential-reconcile-20260823` remained
at `75b0b8954fd14fb275ed983ae984bf1cf6b13749`, no `a2` attempt or task existed,
and production remained at `4feef39a44f920affcb05387a8882fb5f735cfa0`.

## Pre-overnight precursor failures

The overnight miss was the end of a longer preparation chain, not an isolated
00:30 defect:

- Hook installation was initially discussed as if it proved enforcement. A new
  Codex hook is skipped until the restarted session reviews and trusts it; the
  independent one-minute S4U guard remained the backstop. The later restart
  proved the hook active. Future handoffs must distinguish installed bytes,
  trusted configuration, and an observed policy decision.
- Early credential-import wrappers collapsed typed validation failures into a
  generic `RuntimeError`, then passed two SDK-overlay flags to the older
  production CLI that did not accept them. Those were interface/version and
  diagnostic-contract failures, not bad credentials.
- After the live-readiness code landed, the create-only importer correctly
  found pre-existing canonical Credential Manager targets and refused to
  overwrite them. The assistant initially treated that safe refusal as another
  import defect instead of recognizing that compare-only reconciliation was
  now the required operation.
- The first owner-approved guarded merge at 19:23 recovered all three capture
  workers but found the execution-tape worker still on stale source. The guard
  rolled the merge back and proved complete baseline recovery. Root cause was
  a supervisor restart budget that counted six refused, no-child starts as
  recoveries and imposed a 3,600-second backoff. A reviewed fix preserved real
  failed-launch protection while excluding those no-mutation refusals; the
  19:59 retry restarted the worker onto new source and published the 20:04
  merge. The guard worked, but the defect should have been exercised before an
  exceptional production-window merge.
- Repository timezone was incorrectly used conversationally as evidence that
  the host was in Ontario. It is only scheduling configuration. Physical
  location and jurisdiction eligibility require separate action-time evidence.
- User approval of a live test, credential handling, or a one-time timing
  exception was discussed as prose rather than compiled into one exact
  executable authorization/readiness transaction. Conversely, credentials in
  `.env` did not authorize secret disclosure, overwriting existing fixed
  targets, exchange contact, or an unattended order. The workflow needed to
  distinguish those authorities explicitly instead of repeatedly asking the
  operator to bridge hidden technical states.

## What failed and why it was missed

### 1. Candidate qualification was weaker than the scheduled preflight

The candidate added an intentional process-local `except ImportError` boundary
without its architecture exception and expanded a large module without updating
the ownership count/map. Static review missed both. The scheduled preflight
correctly found them and stopped the full suite.

This was not a failure of fail-closed execution. It was a planning error to
describe an unverified protected-window candidate as if the 00:30 preflight
were only confirmation. A night whose first permitted verification can still
discover a deterministic defect is a conditional attempt, not an unattended
completion plan.

### 2. Recovery state was confused with an armed successor

`READY_FOR_SUCCESSOR_REVIEW` means a human or coding agent may review and create
one successor. Canonical status rendered that as `RECOVERY_READY` and said it
was "ready for an active agent." The wording obscured that no successor manifest,
publication, registration receipt, or tasks existed. Freshness-based alert
demotion could later reduce the visibility of this unresolved state.

The audit then made the same mistake conversationally: it supplied a one-line
operator command after the operator had said they needed sleep, but did not
remain in `WAITING_FOR_OPERATOR`, obtain its output, or independently prove the
remote and task state before ending the handoff.

### 3. The resume helper was ordered incorrectly

The host-local helper checked and potentially published the repaired topic
before calculating whether enough of the same-night suite/merge window remained.
After expiry it could therefore mutate the remote and only then refuse to create
or register the successor.

The immediate local repair moves the complete time-window check ahead of all
network and Scheduler work, requires at least ten minutes of registration lead,
and exposes a no-mutation preflight mode. The durable replacement is repository
owned and permits PASS only after an independent composite readiness assertion.

### 4. Future one-shot bindings were not revalidated

The August 17 wrapper correctly bound a boot-specific authorization and frozen
dependency hashes. Those guards protected the host at runtime, but status only
observed that the task was enabled and scheduled. A later reboot invalidated the
boot identity, and a later production integration changed a frozen helper. Both
conditions were knowable hours before the trigger.

Future non-recurring missions need a standard readiness manifest and a shared
pre-run assertion that can report `STALE_BOOT_IDENTITY` or
`STALE_DEPENDENCY_HASH` before the task fires.

### 5. A known documentation deadline had no early hard escalation

Canonical status saw the pending transaction after the 20:04 production merge,
but treated every pre-deadline pending state as a warning. The watchdog promotes
flags, not warnings, so it did not create an actionable alert until after the
09:00 deadline. The audit also called it a separate non-blocker and never
assigned a closeout plan.

The durable correction adds an action-required lead interval and promotes a
still-pending transaction before the deadline, while useful time remains.

### 6. A checker's `PASS` described itself, not the attempt

The host-local overnight checker emitted `check_status=PASS` even when its
separate `attempt_status` was `REVIEW_REQUIRED`. That is syntactically
explainable but operationally misleading. The local repair now reports
`checker_executed=true`, marks `action_required`, and exits nonzero for an
actionable attempt state.

### 7. Registration proof was mistaken for activation safety

The initial hardening still allowed a newly emitted `preparation: null` to use
the historical enabled-registration path. It also let an activator consume an
old readiness receipt without repeating the live topic/master, production
baseline, clean-worktree, and quiet-merge preflight checks. A crash or remote
advance between readiness and activation could therefore arm decayed premises.

The durable correction makes composite preparation mandatory for every newly
created attempt, creates both Scheduler definitions Disabled in their first
mutation, freshness-bounds the readiness receipt, and repeats every mutable
premise immediately before enable. Suite, merge, guarded merge, and closure
now require a successful live remote refresh where their classification or
mutation depends on it; stale tracking refs are never fallback authority.

### 8. The generic one-shot design trusted each payload wrapper

The first design validated metadata but still scheduled the mission wrapper
directly and relied on that wrapper to remember runtime assertion, workload
admission, child-tree containment, and teardown. Its active manifest was the
only deletion anchor, so crash debris and eventual cleanup had no independent
history. Source-string tests checked that guard names appeared but did not
exercise kill points between intent, publication, resolution, and deletion.

The replacement schedules one canonical guarded launcher. It holds a shared
registry lock, revalidates execution state, acquires the heavy lease when
needed, rehashes every dependency from a retained write/delete-denying handle,
and owns the payload in a kill-on-close Windows Job until the absolute
deadline. Writers and lifecycle tools take the exclusive lock. Independent
create-only manifest/resolution index events, receipt-first compaction, strict
activation recovery, and reviewed invalid-debris reconciliation make each
crash point either resumable or loudly contradictory. Status checks the active
and compacted supersession graph and rejects missing edges and cycles without
an arbitrary generation limit.

The retained handles close a race found during the final audit: the earlier
validator hashed stable snapshots but disposed them before helper dot-source
and payload launch. A concurrent replacement could therefore have executed
bytes that were not hashed. Rehashing from handles held through teardown makes
the validation-to-use boundary continuous, including for light one-shots that
do not acquire the heavy-work lease.

### 9. Verification emphasized lexical ratchets over state transitions

The earlier review proved that files parsed and contained expected guard
strings. It did not simulate wrong-case flags, duplicate aliases, stale remote
advances, process death after each durable write, resolution-before-index,
successor-before-resolution, receipt-before-delete, or a semantically invalid
predecessor with structurally valid pending bytes. That is why plausible code
survived review until Scheduler or an independent reviewer exercised the real
control flow.

The focused suite now includes behavioral subprocess fixtures for these
interleavings and the repository-owned integration preflight explicitly lists
the new preparation, readiness, registry, and status ratchets. The tests are
written but the full focused pytest execution remains deferred to the next
admitted host window.

### 10. Disabled staging required authority that readiness had not created

The composite-preparation registrar required the execution-authorization token
before it would create the two Disabled tasks. Readiness was the only component
allowed to create that token, and readiness correctly required the Disabled
tasks to exist first. Each individual guard sounded conservative, but together
they formed an impossible registrar -> readiness -> registrar dependency.

Registration now requires the immutable manifest to bind the authorization
*plan* while requiring the token to be absent. It stages both tasks Disabled;
readiness then creates the token and activation consumes it. A pre-existing
token is rejected as stale authority rather than reused.

### 11. A PASS receipt could grant hours of task-exit grace

The merge waiter described a two-minute grace after a PASS suite receipt, but
calculated it from the fixed 03:40 merge deadline. A suite that emitted PASS
early and remained stuck in `Running` could therefore be tolerated for hours.
The waiter now validates the suite receipt timestamps and starts grace at the
receipt's actual completion time, capped at two minutes beyond the immutable
deadline. A missing, future, or contradictory completion time fails closed.

The same audit found two resurrection paths. New task settings allowed demand
start, and the runtime checked only a broad time-of-day window. A missed
one-shot could therefore be manually started on a later date. New tasks set
`DisallowDemandStart`; suite and merge also require the current local date to
equal the immutable manifest date. These are independent controls, not
substitutes.

### 12. Closure and collision checks trusted states and action shapes they had not proved

Closure previously refused only `Running` and `Queued`. An unknown or future
Scheduler state could be disabled and then misreported as terminal successor
authority. Closure now accepts only exact `Ready` or already `Disabled` states
before mutation. Every other state is an unresolved blocker.

The live-host preparation collision scan also read `.Arguments` from every
Scheduler action under StrictMode. A valid non-Exec action has no such property,
so the scan crashed before it could prove the overnight slot. Property lookup
is now explicit: missing arguments normalize to empty while any sensitive
driver name remains a collision. An executable non-Exec regression fixture and
a read-only live Scheduler scan cover this host-specific case.

### 13. Four live-money gates existed in prose but not at the mutation boundary

The fixed Stage 0/1 design documented jurisdiction, no-fill, economics, and
credential requirements, but the executable path could still pass without all
four:

- Geographic eligibility had no fresh official geoblock receipt mechanically
  paired with the operator's physical-location and no-circumvention
  attestation. The repository timezone had already been misused as a location
  inference once.
- A cancellation event was credited without requiring a present exact-zero
  matched size. The terminal stream was not parsed after cleanup, and there was
  no terminal order or authenticated account-trade REST reconciliation. A late
  match could therefore be mislabeled no-fill.
- Candidate fee and neg-risk values were not re-bound to fresh Stage 0 and
  submit-adjacent Stage 1 rules.
- The first-session manifest/sealer accepted historical create-new or legacy
  credential receipts even though current readiness requires a fresh
  compare-only all-four exact verification.

The fixed path now creates source-address-free, self-hashed, 60-second
geographic receipts before credential resolution and again submit-adjacent;
requires the exact attended no-circumvention literal; treats every scoped trade
state as failure; requires exact-zero cancellation size, post-cancel stream
quiescence, a terminal zero-match REST order, no associated trade, no scoped
authenticated account trade, and final stream-journal verification; binds fee
and neg-risk at candidate, Stage 0, Stage 1 intent, and submit boundaries; and
accepts only a v0.2 `verify_existing_exact` receipt with four verified, zero
written, and no credential-store mutation for the first session.

### 14. Candidate-time evidence was mistaken for action-time capital and acceptance

Stage 0's cached collateral view did not prove that the action-time balance and
allowance still backed the order. Stage 1 now performs an uncached authenticated
read immediately before submit and after cancellation. The balance must cover
the exact 10 pUSD request while remaining at or below the 100 pUSD isolated
wallet cap; the relevant conservative allowance must cover 10 pUSD. A no-fill
result requires exact equality of the normalized before/after
balance-and-allowance hash.

Likewise, file presence was not informed economics acceptance. Candidate
selection now binds the exact accepted snapshot, a recomputed PASS/no-rescore
drift report, the selected condition/token/date, and a distinct operator
acknowledgment literal containing both evidence-file hashes. The literal can be
obtained only from a review-only selection and must match a new final selection;
it is not a reusable date-level approval. All staged copies and session/seal
receipts preserve that lineage.

Finally, several live boundaries trusted cached `origin/master`. Inventory,
composition, sealing, and the generated wrappers now obtain a bounded
`git ls-remote` proof of the exact live `refs/heads/master` and require it to
equal `HEAD`, local master, cached origin/master, and the reviewed production
commit. Network failure is a stop, never authority to fall back to the cache.

### 15. Self-consistent tests did not prove current official wire spellings

The first terminal-order tests and validator both used the shortened
`CANCELED` spelling. The current official order endpoint documents
`ORDER_STATUS_CANCELED`; a clean live cancellation could therefore have failed
every run despite all local tests passing. The validator now accepts the
documented value as well as the SDK/backward-compatible shortened spellings,
and the normal success fixture uses the documented wire value. This was found
by comparing the final path with the current official geoblock, heartbeat,
order, account-trade, and user-channel contracts rather than reviewing only
repository-local mocks.

### 16. Evidence timestamps were parsed as local wall-clock strings

Registration and suite receipts correctly emitted offset-bearing ISO-8601
timestamps, but several readiness/merge consumers passed them to the
offset-forbidding local-schedule parser or cast them directly to `[datetime]`.
The first path rejected valid evidence; the second silently discarded the
instant semantics. This survived review because tests used schedule timestamps
and receipt timestamps interchangeably.

Evidence instants now use the strict `DateTimeOffset` parser and are converted
to local wall time only where Task Scheduler correlation requires it. Schedule
fields retain the offset-free local parser. Direct regressions use unequal UTC
offsets so a parser that merely compares clock faces cannot pass.

### 17. Human and network latency sat inside supposedly fresh live gates

The first submit-adjacent design checked market rules and collateral, then ran
the host check, attended prompt, and official geoblock request before signing.
That slow callback could age the seven-and-a-half-second heartbeat and ten-
second rule budgets. The adapter also performed authenticated closed-only and
position reads after its first freshness checks. Stage 0 performed its only
geography check before credential resolution and a stream wait of up to 45
seconds.

Stage 1 now runs the human/host/geography callback first, then refreshes and
rebinds authoritative rules, rechecks geography immediately before the final
heartbeat, refreshes the heartbeat, repeats time/geography checks, and enters
an adapter boundary that revalidates stream, heartbeat, rules, geography, and
submit deadlines before and after local signing. Stage 0 retains a
precredential receipt for secret-release policy and adds a distinct
mutation-adjacent receipt after the slow authenticated reads; it revalidates
that receipt before each intended heartbeat/cancel write. Risk-reducing failure
cleanup remains possible, while the redundant outer cleanup cancellation was
removed. Slow-prompt, slow-rule, slow-signing, and stale-receipt tests fail
before order submit.

### 18. Producers proved no-fill facts that downstream gates did not consume

The lifecycle bundle gained terminal order REST, authenticated account-trade,
quiescence, final user-stream, and collateral reconciliation evidence, but the
market-making preflight, session runner, and wrapper sealer still checked the
older subset. A locally valid producer artifact could therefore be weakened or
tampered after production and still reach a later readiness decision.

Every consumer now independently binds terminal order identity/hash and exact
zero match, empty associated/scoped account trades, the two-second quiescence
interval, final journal paths/hashes/counts, fee and neg-risk parity, action-time
collateral, before/after collateral equality, and ending zero orders/positions.
Each mandatory contract change has a new schema version, legacy registrations
remain explicit read-only history, tracked research templates use the new
shape, and missing/tampered-field regressions exercise the downstream gates.

### 19. Git proofs were unbounded and authenticated only refs, not the remote

New preparation/readiness checks invoked `git ls-remote`, `fetch`, and `push`
synchronously. A credential prompt or stalled connection could consume an
entire Scheduler/setup budget. Even a successful ref proof did not bind
`remote.origin.url`, so a substituted fork containing the same commits could
pass SHA-only checks and receive publication.

All remote Git operations now run in a bounded child process with interactive
prompts disabled and child-tree termination on timeout. The canonical
credential-free GitHub HTTPS origin is frozen in the preparation intent and
manifest, and rechecked before publication and at readiness, activation,
suite, merge, guarded merge, and closure boundaries. Reports/markers retain
that identity. Timeout, failure, protected-branch, and fork-substitution
regressions fail closed.

### 20. Successful historical one-shots remained manually resurrectable

The new collision gate correctly noticed that two successful v1 task pairs
were still `Ready`, enabled, and `AllowDemandStart`. A later review found two
pre-manifest bootstrap tasks with the same property whose noncanonical names
escaped the first scan. Treating a past trigger or missing `NextRunTime` as
terminal ignored manual demand-start authority.

Preparation now reports all six exact blockers. Successful attempt retirement
requires the immutable PASS merge/suite receipts, full v1 intent and live task
binding, terminal result zero, receipt-correlated run times, a review reference,
and a literal before disabling the exact pair and writing a separate immutable
receipt. The two pre-manifest tasks use a narrowly allowlisted migration that
also binds their complete exported XML hash and exact historical result. No
task is deleted or reclassified. New v2 tasks combine an exact-date runtime
gate with `DisallowDemandStart`; their expired definitions cannot be manually
resurrected. Scheduler mutation remains an explicit operator action.

### 21. A geography digest retained more response information than needed

The first redacted receipt omitted an IP field but retained the SHA-256 of the
raw response containing that IP. While not plaintext disclosure, the digest
was unnecessary and contradicted the data-minimization claim. It also made
tests focus on a self-consistent digest instead of the exact public decision.

The receipt now hashes only the canonical `blocked/country/region` decision,
records no source-address value or raw-body digest, and validates its
self-hash/freshness independently. A tampered response, stale receipt,
operator/endpoint disagreement, or attempted IP retention fails.

### 22. Equivalent UTC instants were compared as strings in the final bundle gate

The final direct lifecycle-bundle check found one last deterministic failure:
the geography receipt emitted `Z`, while adapter diagnostics normalized the
same expiry to `+00:00`. The journal verifier required literal string equality,
so two equivalent instants failed after both individual lifecycle probes had
passed. Earlier focused checks exercised producer success but did not build the
two-mode bundle after the final boundary fields were added.

The verifier now parses both values as timezone-aware instants and compares the
UTC values; malformed or offset-free evidence still fails. The success bundle
and journal-tamper checks both run directly in the protected-window-safe test
set, so this mismatch is caught before the admitted overnight suite.

### 23. Incomplete legacy evidence crashed instead of failing closed

The final readiness-consumer check exposed a separate fail-closed defect. The
new Stage 1 hardening validator converted absent numeric evidence to `None`, but
then evaluated comparisons such as `None > 0` while constructing the tuple
passed to `all()`. A legacy or deliberately incomplete platform file therefore
raised `TypeError` instead of returning a deterministic BLOCK. Producer tests
had complete fields, and earlier consumer checks exercised current PASS
fixtures, so neither covered this missing-field boundary.

Every optional numeric comparison now short-circuits behind its explicit type
or presence check. The existing current-no-go readiness fixture and the fully
passing readiness fixture are both called directly in the protected-window-safe
set: incomplete evidence blocks without an exception, while complete current
evidence still passes.

### 24. A canonical fetch URL did not prove the publication destination

The first transport hardening froze `remote.origin.url`, but Git can send a
push to `remote.origin.pushurl`, and `url.*.insteadOf` or `pushInsteadOf` can
rewrite an apparently canonical URL in any effective configuration scope. A
post-push check against the same redirected remote name could then agree with
the wrong repository. Earlier tests substituted only the fetch URL and did not
model Git's separate publication and rewrite configuration.

The shared remote helper now rejects push URLs and effective URL rewrites,
sanitizes Git configuration for a second canonical-URL query, and requires that
config-independent acknowledgement after publication. Quiet merge rechecks the
identity immediately before `WeatherOneShotPush` and does not acknowledge
publication until the canonical live `master` agrees. Local/global rewrite,
push-URL, timeout, and fork-substitution regressions fail closed.

### 25. Local signing could outlive heartbeat, stream, or rule freshness

Stage 1 revalidated these short leases before local signing, but a hardware
wallet or slow signer could consume them before the sole POST. The post-sign
boundary checked only UTC submit and geography deadlines. Earlier slow-sign
tests expired those two deadlines, so they never independently exercised stale
heartbeat, stale market rules, or a failed authenticated stream.

The adapter now revalidates authoritative stream health, heartbeat age, market
rule age, minimum size, tick alignment, and non-crossing price after signed
identity proof and immediately before POST. That proof is carried through the
lifecycle journal, result, bundle, runner, wrapper, and preflight. Independent
slow-sign regressions prove that each expired lease blocks before POST.

### 26. A journal hash did not make an authenticated stream final

The lifecycle result bound user-stream bytes and counts, but the verifier did
not require a terminal `stream_stopped` record or the cleanup routine's final
hash. A truncated snapshot could omit an event arriving after the captured
hash while still being labelled final. Producer fixtures contained only the
cancel event, so downstream checks reinforced the incomplete contract.

Current evidence requires exactly one `stream_stopped` as the final row and
requires the ordinary journal hash and cleanup-final journal hash to equal the
same bytes. Missing stop, any event after stop, content tampering, and cleanup
hash tampering all fail. The terminal-stop proof is required by every live
consumer and the sealed runtime template.

### 27. Mandatory platform semantics changed under an unchanged schema name

The platform verifier began requiring lifecycle v0.3 and new private-stream,
REST, collateral, and journal fields while still calling the outer document
`mm_platform_verification_v0.5`. That silently made previously valid v0.5
documents invalid instead of representing a new contract. Earlier schema work
bumped the embedded artifacts but did not audit the containing authorization
document.

The active outer schema is now v0.6. Version v0.5 remains an explicit legacy
registry entry and cannot authorize the current live path. The tracked template,
reader, registry, documentation, and direct legacy-rejection test agree.

### 28. Retirement and compatibility tests stopped short of their consumers

Two related integration gaps survived the first pass. Retirement disabled a
task before writing its receipt, while collision detection skipped Disabled
tasks; a receipt-write failure could therefore clear the next-attempt gate.
Also, the historical v1 regression reduced real evidence to a few booleans and
called only the expected-binding constructor, not the actual intent and receipt
readers used by retirement. The bounded-process timeout test launched no
descendant and ignored `taskkill` and parent-exit outcomes.

Disabled legacy demand-start tasks now remain blockers unless strict readers
prove either an exact PASS retirement receipt or an exact FAIL closure receipt.
This distinction preserves the real `credential-reconcile-0824-a1` recovery
path while a partial/corrupt successful retirement remains blocked. Writers
read their new receipts back before success. A full captured v1 intent, receipt,
and FAIL closure fixture now flows through the actual readers with tamper and
partial-evidence rejection. Timeout handling validates `taskkill` completion
and exit plus parent exit, and its regression proves a real descendant cannot
escape.

## Controls that worked

- Exact-tip manifest, registration intent, receipt, and live task binding.
- The integration preflight stopped the full suite on deterministic failure.
- Absence of a PASS suite receipt prevented the merge consumer from mutating Git.
- Closure disabled the exact task pair and preserved immutable failure evidence.
- Recovery dispatch granted no automatic source, Scheduler, credential, or
  exchange authority.
- Boot and dependency guards stopped the stale settlement wrapper before child
  launch, workload-lease acquisition, or mutation.
- Production `HEAD`, `master`, and `origin/master` stayed synchronized.
- No credential value was read and no exchange endpoint or order path was used.

## Implemented long-term controls

- `prepare_integration_attempt.ps1` is the new preferred interactive entry
  point. It checks the complete schedule with at least ten minutes of lead
  before publication, freezes an intent, pushes one exact non-force refspec,
  verifies the live remote, creates and registers the immutable attempt, and
  returns PASS only after readiness, activation, re-attestation, and the final
  preparation receipt all succeed.
- Every exit-bearing creator, registrar, readiness, activator, and closer script runs in
  a contained child PowerShell process. An independent pre-commit review found
  and corrected the initial direct-call implementation, which otherwise could
  have let a child's `exit` terminate the preparer before its final receipt or
  cleanup path.
- A post-manifest preparation failure invokes the canonical closer and records
  the exact terminal closure receipt. Failure to prove both exact tasks
  terminal and disabled remains a loud blocker rather than a preparation
  result.
- Canonical status now separates `AWAITING_SUCCESSOR`,
  `SUCCESSOR_UNPUBLISHED`, `SUCCESSOR_UNREGISTERED`,
  `SUCCESSOR_WINDOW_MISSED`, `SUCCESSOR_ARMED`, and `SUCCESSOR_ACTIVE`.
  Unresolved states remain flags regardless of evidence age, and the JSON
  exposes `publication_required`, `unattended_ready`, and `next_action`.
- A generic read-only one-shot validator has separate pre-trigger and
  execution-entry modes. The only schedulable action is the canonical guarded
  launcher; v0.4 separately binds payload path/arguments plus launcher,
  validator, Job helper, and workload-admission hashes. The launcher holds
  registry/readiness authority, the heavy lease, kill-on-close containment,
  and the absolute deadline. Stable blockers such as `STALE_BOOT_IDENTITY` and
  `STALE_DEPENDENCY_HASH` remain visible before trigger.
- The generic registry now has a permanent create-only index, transactional
  activation, exact terminal/supersession resolutions, receipt-first reviewed
  compaction, and reviewed reconciliation for invalid successor-pending debris.
  Status uses bounded enumeration and verifies active/compacted identity,
  hashes, replacement bindings, missing edges, and cycles.
- New integration manifests cannot opt into the legacy path. Tasks are born
  Disabled; readiness writes deterministic execution authority; activation
  freshness-bounds and repeats live remote, baseline, worktree, and merge
  preflight proof before enable. Runtime and closure treat live fetch failure
  as fatal rather than trusting stale remote-tracking state.
- Disabled staging now requires a manifest-bound authorization plan and an
  absent token, removing the impossible registrar/readiness dependency. New
  one-shots disallow demand start, execute only on their frozen local date, and
  can be closed only from an exact terminal Scheduler state. PASS task-exit
  grace is measured from the validated suite-receipt completion time.
- The first live path now compiles physical eligibility/no circumvention,
  current official geoblock evidence, exact economics acceptance/no-drift,
  compare-only all-four credential proof, fresh fee/neg-risk rules, uncached
  collateral, and complete no-fill reconciliation into the sealed mutation
  boundary. None can be supplied by repository timezone, a stale cached ref,
  a historical receipt, or a self-authored PASS boolean.
- Public inventory, manifest composition, sealing, and runtime wrappers require
  bounded live-remote `master` equality. Terminal Stage 1 evidence includes the
  final authenticated stream journals, documented terminal order status,
  exact-zero matched size, empty associated trades, account-trade scope, and
  before/after collateral equality.
- Integration transport now bounds every remote Git child, disables terminal
  and credential-manager prompts, kills the child tree on timeout, and freezes
  canonical origin identity alongside refs. Ref equality from a substituted
  fork is not publication or baseline proof.
- Collision detection treats demand-startable expired integration and bootstrap
  tasks as live blockers. Reviewed retirement paths disable only six exact
  receipt/XML-bound definitions and preserve separate immutable evidence; new
  v2 attempts use both no-demand-start settings and an exact-date runtime gate.
- Bootstrap, lifecycle result, lifecycle journal, and bundle writers now emit
  new schema versions for their expanded mandatory fields. Legacy versions are
  explicit registry entries, while current consumers and tracked templates
  refuse a partial old shape.
- Documentation transactions now enter an action-required state two hours
  before their 09:00 deadline, and the watchdog treats that state as high
  severity instead of waiting for an overdue flag.
- The host-local resume helper was date-locked and reordered so complete
  schedule viability is checked before any push or Scheduler action. The
  host-local checker now distinguishes successful checker execution from an
  actionable attempt and exits nonzero for the latter.

## 29. The narrow recovery audit did not finish with the whole-host status

The final whole-host sweep exposed an overdue but valid documentation
transaction for integration `4feef39a4` and reported
`WeatherMaintenancePostBoot0823` as unexpectedly Disabled. Earlier passes had
checked capture, the guard, Git, the failed attempt, and the exact collision
set independently, but had not rerun the canonical aggregate status after
those checks. That sequencing hid cross-subsystem debt even though neither item
was inside the credential-reconciliation failure.

The documentation transaction does not block the bounded suite or guarded
merge: the merge appends its exact integration identity to the immutable
pending transaction. It does remain a required post-merge closeout before an
attended live-readiness claim. The post-boot alert was a false positive. The
exact S4U/Highest boot task ran successfully, wrote a content-addressed v0.2
PASS receipt proving boot recovery, clock, Git, capture, execution tape, and no
credential/exchange action, and then intentionally disabled itself in
`finally`. Generic status recognized only time-triggered and on-demand
self-retirement, not receipt-proved boot-trigger retirement.

Status now recognizes a disabled `WeatherMaintenancePostBootNNNN` only after
revalidating its root task identity, exact hash-bound wrapper beneath the
current user's dated `ops` directory, boot trigger, terminal Scheduler result,
plain-file receipt and sidecar hashes, receipt/task timestamps, every required
host proof, and the no-credential/no-exchange boundary. A malformed or missing
receipt remains a flag. The actual host task now reports as exact PASS evidence
instead of an unexpected disable. The same sweep found 117 GB free on C: and
healthy three-loop capture; the recent disk-consumption trend is a follow-up
risk, not a blocker for this one bounded overnight run.

The repaired credential descendant and hardening must pass the deferred
admitted-window tests and land through one final v1 successor before the new
preparer can own later attempts. Topic publication alone is not production
activation. The new flow cannot truthfully bootstrap itself from production
code that does not yet contain it.

## Durable acceptance criteria

An overnight integration may be described as armed only when one composite
assertion proves all of the following at the same observation boundary:

1. the complete suite/merge schedule remains future with conservative setup
   lead;
2. the clean isolated worktree and exact local topic commit match;
3. the live remote topic and refreshed remote-tracking ref match that commit;
4. repair attempts bind and atomically claim the exact predecessor evidence;
5. manifest, registration intent, and PASS receipt validate;
6. both exact tasks are enabled, `Ready`, future, and have not already run;
7. no terminal or partial runtime evidence contradicts a fresh attempt; and
8. no operator action remains pending.

Dispatch-only recovery must remain a persistent blocking state. Future
boot/hash-bound one-shots must expose a machine-readable pre-run readiness
result. Documentation closeout must escalate before, rather than after, its
deadline.

## Verification boundary

Implementation continued in the 12:00--18:00 graded window, so verification is
limited to PowerShell parsing, Python AST parsing, diff checks, source ratchets,
and isolated tempfile behavior. Focused pytest, the repository-owned bounded
suite, documentation audit, and any exact integration attempt must wait for a
repository-admitted 00:30--09:00 host window. No production write, Scheduler
mutation, credential action, exchange contact, or live order is part of this
audit implementation; publishing the isolated topic ref does not alter the
production working tree.
