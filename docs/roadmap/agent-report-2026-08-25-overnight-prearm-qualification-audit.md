# Overnight pre-arm qualification audit -- 2026-08-25

This is dated audit evidence, not current operating instruction or work-item
status. Current truth is in `docs/operations/STATE_OF_PLAY.md`; item scope and
acceptance remain in item 329.

## Verdict

The overnight safety boundary worked, but the preparation claim did not.
Attempt `credential-reconcile-0825-a2` ran 143 deterministic integration
preflight tests: 134 passed and nine failed. The bounded full suite did not
start, the 03:10 merge refused before repository mutation, and production
remained at `4feef39a44f920affcb05387a8882fb5f735cfa0`.

The failures were knowable repository contract mismatches, not transient host
noise. The mistake was scheduling the first complete exact-tip check as part of
the overnight attempt and then describing that attempt as likely to land. A
test first run after Task Scheduler is armed is discovery, not confirmation.

Attempt a2 is now immutable `FAIL/ABANDONED`. Both exact tasks are Disabled.
The exact closure SHA-256 is
`32b1757fcfc80f4602c9f95cd859b059f3911d1b514e2db346f613d59b7d92bd`, and
the reviewed `manual_reviewed_change` dispatch SHA-256 is
`0f63494581612d5cb5401fb6cb8082fbcc8751a10ad4dcfc1938d5bbed68c057`.
The dispatch classifies one reviewed descendant opportunity; it authorizes no
network/topic publication, Scheduler mutation, credential access, exchange
contact, or production mutation.
No successor manifest, predecessor claim, registration receipt, or successor
task exists at the time of this report.

## What failed

The nine failures divide into four deterministic groups:

| Count | Contract mismatch | Why execution was right to stop |
| ---: | --- | --- |
| 1 | A test expected an obsolete diagnostic string. | Diagnostics are part of the operator contract; tests must follow the current exact refusal. |
| 4 | Fixtures supplied bare `codex/...` topic refs after the contract began requiring remote-tracking `origin/...` refs. | A local branch name does not prove canonical remote publication. |
| 1 | A synthetic Git repository omitted the canonical-origin identity required by current preparation. | Exact commit equality from an arbitrary remote is not production lineage proof. |
| 3 | Quiet-merge tests expected a retired raw Git-fetch shape instead of the bounded, noninteractive fetch helper. | Reintroducing raw fetch would remove timeout, prompt, and child-tree controls. |

These were test repairs, not reasons to weaken the production contracts. The
preflight's fail-closed outcome prevented a longer suite from consuming the
night and prevented a merge based on contradictory evidence.

## Why earlier review missed them

### Verification scope was mistaken for verification result

Most hardening was written during protected host windows. The allowed checks
were PowerShell parsing, source ratchets, diff review, and small direct-function
probes. Those checks can find syntax, missing symbols, and selected control-flow
errors; they cannot establish that all 143 integration contracts execute
together. The handoff stated that the bounded suite was deferred, but later
readiness language treated the deferred work as low-risk confirmation.

The correction is semantic: deferred executable verification is a blocker, not
a confidence discount. No attempt can be called armed while its candidate's
exact scheduled preflight or full bounded suite remains unrun.

### Tests and implementation shared stale assumptions

The changed code and nearby tests were reviewed as one coherent patch. That
made internally familiar spellings look plausible: bare topic refs, a minimal
synthetic remote, and source assertions for the prior fetch implementation.
Review emphasized the new safety branches but did not execute every older
fixture against them. A self-consistent review can therefore miss drift at the
boundary between old fixtures and new contracts.

The long-term control is independent execution at several levels: focused
behavioral regressions, a Windows operations gate, the exact integration
preflight, and the complete bounded suite. Lexical assertions remain useful as
ratchets but cannot substitute for state-transition tests.

### Registration proved identity, not candidate quality

The immutable attempt machinery strongly bound the source tip, helper hashes,
tasks, schedule, and later receipts. It did not require a prior immutable PASS
showing that the same exact tip had already completed the preflight and bounded
suite. Consequently, Scheduler could be mutated lawfully around a candidate
whose first comprehensive test would occur at 00:30.

Evidence integrity answered "what did we schedule?" but not "did this exact
candidate already pass?" Both questions need independent proof before arming.

### The plan had no explicit error-discovery budget

The schedule budget accounted for overnight preflight, suite, and quiet merge,
but not for discovering a deterministic failure, reviewing a repair, rerunning
the whole qualification, and preserving the 03:40 recovery reserve. Once the
first executable gate failed, the correct safe outcome was to lose that night's
integration. Earlier planning should have made that consequence explicit.

Future preparation must use measured qualification duration plus conservative
margin and reject a schedule that cannot finish before the reserve. Urgency and
operator approval can choose when reviewed work runs; neither can turn an
incomplete evidence chain into PASS.

### The first audit was still too incident-shaped

Repairing the nine failed assertions was necessary but not a sufficient audit.
An independent adversarial pass then found failure classes that had not fired
on a2 at all:

- a literal preflight file count was repeated across the runner, preparer, and
  scheduled suite, so adding a contract test could silently make the claimed
  inventory stale;
- Git-clean worktrees could still contain ignored bytecode, native extensions,
  source, `conftest.py`, or test configuration capable of changing imports or
  test semantics;
- creator validation, capture probes, and remote Git children were not all
  assigned-before-resume to an operating-system kill-on-close boundary, and
  redirected child output could be reopened by pathname after its last writer
  closed;
- ordinary hash-then-parse evidence reads could combine two generations of one
  file, while reparse-point ancestry and mutable remote-tracking refs created
  separate pathname and freshness risks;
- normal-day wall-clock arithmetic concealed daylight-saving gaps, ambiguous
  hours, and elapsed-time compression, and Scheduler collision review modeled
  only the states seen in the latest incident;
- the candidate CI workflow did not cover topic pushes or Windows, and all
  repository workflows still named mutable major-version action tags;
- a duplicated PID-count capture check, hydrated-local Git LFS assumptions,
  and timeout-only process cleanup each supplied a plausible but incomplete
  proxy for the property actually needed.
- the comprehensive test process inherited production-capable network,
  Credential Manager, Git-remote, and Task Scheduler surfaces, so a future
  test or plugin mistake could turn qualification into external state access;
- the user-layer host-load hook classified raw command text rather than command
  positions, so a quoted search term could be refused while an indirect wrapper
  or nested shell launch was not modeled with the same precision;
- Git helpers trusted more ambient process and repository configuration than
  their evidence model admitted, including executable resolution, replacement
  objects, filters, diff drivers, proxies, pagers, and ref freshness;
- the Python bootstrap blocked sockets and shell mode but still accepted an
  arbitrary native executable, an opaque non-shell command string, or an
  `executable=` override. A cached original `Popen` could therefore retain the
  guarded environment while escaping the intended executable grammar;
- the same bootstrap inherited ambient CI and operator secrets before test
  collection. Network denial reduced exfiltration paths but did not make
  credentials legitimate test inputs or safe diagnostic material;
- quiet merge had a pinned Git lookup at entry but more than thirty later raw
  Git invocations. A source test actually required that direct-call count,
  turning an implementation detail into a ratchet for the unsafe behavior;
- the preparation child used a wall-clock hard stop without an independent
  monotonic lifetime. A backward clock correction could lengthen an otherwise
  bounded child tree;
- post-merge execution-tape adoption still had direct Python, direct Git, an
  in-process unbounded attempt gate, pathname-reopened writer-lock JSON, and
  local-ref-only master checks on an authority-bearing path;
- qualification hash-bound `python.exe`, while the adopted Scheduler action
  executes `pythonw.exe`. The executable that would actually run production
  work was not yet part of the same retained environment identity;
- a cache-ancestry check named a leaf that the workflow never created. The
  guard was fail-closed, but it was also fail-always and had no positive
  end-to-end control proving the accepted path existed;
- capture identity compared a 16-character loaded-source fingerprint against
  a 64-character expectation, and the disk gate enforced 2 GiB where the
  operator contract required 50 GiB. Both were locally plausible constants
  that had drifted from their actual producers and policy owners.
- raising an ordinary exception from `sitecustomize` was described as
  fail-closed even though CPython reports that exception and continues startup;
  the offline bootstrap therefore needed an explicit completion sentinel and
  a hard exit before any unguarded payload could run;
- Disabled task registration and later activation shared one broad approval
  story. They now require separate case-sensitive literals, rechecked at their
  actual mutation boundaries, so registration consent cannot become enablement
  consent by implication;
- test-local Git remotes could name a production repository or execute local
  receive hooks, while status inspection could evaluate contract text selected
  by an evidence-controlled `repo_root`. Both paths now bind to disjoint
  authority roots and reject hook/config redirection before execution;
- a recursive cleanup enumeration could enter a reparse directory before
  rejecting it, and initial temp-policy validation froze `TEMP` and `TMP` but
  omitted `TMPDIR`. No-follow traversal and one exact three-variable temp root
  are now part of the static contract.

These omissions shared one review error: the implementation was inspected by
script and by the observed failure, rather than by every authority-bearing
input over its complete lifecycle. A value can be correct when frozen and
wrong when consumed; a process can time out correctly and still survive its
caller; a clean Git index does not describe ignored import state; a local
clock interval is not necessarily elapsed time; and a passing test list does
not prove that the list itself was complete.

The replacement review method is a boundary matrix. For each phase it records
the authoritative identity, its single owner, how bytes are retained, which
mutable premises are rechecked, what survives a parent crash, what an
unexpected Scheduler state means, and what immutable artifact proves the
outcome. Every newly discovered class gets both a positive control and an
adversarial refusal regression. A second reviewer follows the end-to-end PASS
path looking specifically for missing arguments, duplicated constants,
post-exit name lookups, direct-entry bypasses, and state transitions that the
author's tests did not exercise.

The deeper correction is to prefer negative inventories over occurrence-count
ratchets for authority-bearing edges. A test asks for zero uncontained Python,
zero direct Git in guarded merge and adoption, zero unguarded Scheduler
mutations, zero mutable workflow-action tags, and zero opaque or unapproved
external-process forms. Positive controls then exercise the one canonical
helper. Fingerprint width, runtime budget, Scheduler limit, and disk reserve
are asserted against the producing schema or canonical policy instead of
copied into another implementation-specific count.

## Layered long-term controls

The hardening branch implements the following control stack and has completed
protected-window-safe independent static review. It has not run Python, CI, or
production-host qualification, so this list is a reviewed design boundary, not
an executable PASS or readiness claim.

1. **Early topic CI.** Topic pushes run an explicit cross-platform inventory on
   Ubuntu and the complete inventory on Windows. This gives faster
   cross-platform feedback. Every external workflow action is pinned to an
   immutable commit and checkouts discard their write credential, but CI
   remains an early signal rather than production-host qualification.
2. **Pre-arm exact-tip qualification.** Before registration or activation, the
   isolated candidate worktree must pass both the deterministic integration
   preflight and the complete repository-owned bounded suite. Immutable
   evidence binds commit, baseline, import root, command plan, logs, verdicts,
   helper hashes, timestamps, and completeness.
3. **No alternate entry-point bypass.** Manifest creation, registration,
   readiness, and activation must all reject missing, partial, stale, malformed,
   wrong-tip, or wrong-baseline qualification evidence. A caller cannot obtain
   authority by invoking a lower-level script directly.
4. **Overnight drift rerun.** The actual attempt repeats both preflight and the
   complete suite. Pre-arm PASS proves the candidate; the repeated run detects
   host, dependency, evidence, or environment drift before merge.
5. **Final mutable-state recheck.** Immediately before attempt creation and
   again before enable, refresh the canonical live topic and master; prove
   remote identity, exact refs, production baseline, clean worktree, helper
   hashes, and schedule feasibility. Cached refs are not authority.
6. **Versioned evidence compatibility.** New writers emit the strict new
   qualification-bound schema. Historical v1 attempts remain structurally
   readable and closable without requiring a deleted worktree or retroactive
   evidence that did not exist when they ran.
7. **Contained heavy execution.** Qualification and overnight suites use the
   repository workload-admission path, bounded diagnostics, absolute deadlines,
   and child-tree containment. A killed parent must not leave pytest or wrapper
   descendants competing with capture past 09:00.
8. **Schedule feasibility from evidence.** The preparer uses observed
   qualification duration and conservative margin. It refuses publication or
   Scheduler mutation when a complete later attempt cannot retain the quiet
   merge reserve.
9. **Transactional task lifecycle.** Tasks are staged Disabled, disallow demand
   start, bind the exact local date, and are enabled only after readiness. The
   terminal mutex spans final evidence and task attestation. Closure and status
   use canonical evidence validation and detect re-enabled or drifted tasks.
10. **Crash-visible progress.** Preparation freezes its qualification plan
    before launching children. Phase logs plus terminal preparation evidence
    distinguish not-run, running/interrupted, FAIL, and PASS; missing or torn
    evidence is an explicit blocker rather than an inferred success.
11. **Behavioral regressions for every incident.** Each observed failure gets a
    positive control and a refusal test. Boundary tests cover remote names,
    canonical origin, bounded transport, direct-entry bypasses, schema
    compatibility, task drift, rollback, and process containment.
12. **Whole-system review.** Exact-tip static checks, independent adversarial
    review, topic CI, admitted Windows qualification, actual overnight rerun,
    guarded merge recovery, and canonical whole-host status are distinct
    acceptance layers. A PASS at one layer cannot be restated as another.
13. **Offline qualification boundary.** CI, pre-arm qualification, and the
    overnight suite set one exact offline marker before Python starts. A tracked
    interpreter bootstrap blocks sockets in descendants; real market and
    Credential Manager boundaries refuse directly; repository Scheduler and
    remote-Git mutations refuse under the marker while explicitly injected
    fixture transports and in-process function mocks remain testable. Ambient
    secret-bearing variables are removed before collection and at every Python
    child edge. Subprocesses use a sequence-form grammar and exact Python, Git,
    or PowerShell identities; shell mode, executable overrides, arbitrary
    native tools, bootstrap-disabling Python flags, and common PowerShell
    network or credential commands refuse before launch. This is defense in
    depth around reviewed test bytes, not a claim that CPython is an OS sandbox.
14. **Deterministic toolchain and Git authority.** Preparation freezes the
    executable, version, dependency, test inventory, PowerShell inventory,
    helper hashes, environment policy, and complete local/live/local ref tuple.
    Git children use one absolute regular non-reparse executable, bounded
    retained output, explicit configuration and environment rejection, and
    assignment-before-resume containment. A local ref cache or PATH lookup is
    never canonical-remote proof.
15. **Semantic host-load prevention.** The launch hook tokenizes executable and
    module positions across compound and nested commands. Quoted audit text is
    not treated as execution, while direct runners, encoded nested shells, and
    repository heavy wrappers stay time-gated. The independent one-minute S4U
    guard remains the enforcement backstop. Opaque commands and hook/parser
    failures deny rather than becoming an allow path, and a RAM upgrade cannot
    silently change the dedicated host's policy identity.
16. **One process and Git edge per authority path.** Quiet merge,
    reconciliation, and post-merge adoption route every Git and Python child
    through the pinned, retained-output, assignment-before-resume Job helper.
    The executable used by Scheduler (`pythonw.exe`) is included in
    qualification identity. Cleanup disables resurrection before stopping a
    worker and preserves the initiating error even when cleanup actions fail.
17. **Dual lifetime and resource clocks.** Shared suite time is capped by a
    monotonic 5,400-second budget and the 09:00 wall boundary; preparation
    children also freeze a monotonic allowance at launch. Scheduler execution
    is capped at 5,700 seconds (`PT1H35M`) to leave teardown reserve, and each
    distinct relevant volume must retain 50 GiB before and during execution.

## How this changes the next attempt

The admitted host window closed before the hardening could be executed. The
earliest lawful exact-tip qualification is Aug 26 at 00:30 America/Toronto. If
it passes completely, a separately reviewed immutable successor can use no
earlier than the Aug 27 suite/merge window. Any failed test, partial log,
timeout, stale remote, insufficient schedule margin, process-containment
failure, or review finding moves the attempt later; it does not authorize a
shortcut.

Even a successful successor merge does not authorize live money. The first live
test remains separately attended and requires fresh credential equality,
physical-location/no-circumvention and official geoblock evidence, public
economics and paper candidate, informed baseline acceptance, identity/doctor,
account collateral/zero-state, sealed wrappers, and action-bound literals.

## Limit of the promise

No finite audit can promise to predict every unknown software, Windows,
network, Git, Scheduler, dependency, or exchange failure. Claiming otherwise
would recreate the overconfidence that made the a2 attempt sound ready.

The defensible promise is narrower and stronger: known failure classes receive
behavioral regression tests; complete candidate tests run before arming; mutable
premises are rechecked at the last responsible boundary; the actual overnight
run detects drift; incomplete evidence never becomes PASS; and unknown failures
stop before production or live-money mutation while leaving enough immutable
evidence for the next reviewed repair.

## Verification boundary

This report records the design response, protected-window-safe static review,
and the already completed a2 closure/dispatch. PowerShell AST and diff checks
pass, but no Python/import/test execution is claimed. It does not claim that the
hardening branch passes CI or focused tests, passes pre-arm qualification,
creates a successor, lands in production, closes the documentation transaction,
or passes any attended live gate. Those outcomes require their own exact
evidence.
