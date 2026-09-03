# Delegation Contract

Status: canonical. Written for LLM agents on every project host.

Work in this project uses distinct host roles. This file is the standing contract between them.
**Every mission inherits §2 whether or not the handoff restates it.** A handoff may add constraints
and may not remove them.

**Operator decision 2026-08-28:** the former host-based prohibition on opening
pull requests or performing an authorized Git merge from the workstation or
portable PC was written in error and is removed. Source-control authority is
now governed by the explicit operator instruction plus `docs/git-workflow.md`,
not by the machine that holds the checkout. This does not turn a remote Git
merge into runtime adoption or bypass a production-host guarded integration,
capture-recovery, Scheduler, release, or live-exchange gate.

**Operator decision 2026-08-28:** the dedicated capture-host load timetable
does not follow the portable assignment onto the separate 32 GB workstation.
That PC may perform ordinary implementation, testing, training, replay, and
measurement at any local time. Recognized heavy commands use the repository
workstation wrapper; its admission-only profile shares the portable launcher's
host-global mutex and admits only the assignment's exact non-capture Windows
installation and attending principal. Both launch paths own their complete
child tree in a kill-on-close Windows Job, so wrapped work and a launched stage
cannot overlap through cleanup. Heavy work still ends before sealing as an operational attempt-
preservation rule. Its separate live-executor role
remains fixed-scope and grants no additional production or live authority.

**Operator decision 2026-08-30:** the exact reviewed remote branch
`codex/portable-execution-host-clean-20260827` may be live code authority before
master adoption for `portable_execution_v1` only. This is not a general
topic-branch rule. The worktree must be clean; local HEAD, local branch, cached
origin branch, and freshly queried canonical branch must be identical;
local/cached/live canonical master must be synchronized and ancestral to the
topic tip; exact-head CI and review must pass; the repository owner must
explicitly authorize the tip; and the tracked host/principal assignment must
match. `capture_colocated_v1` remains exact-master-only. This exception removes
only master promotion: it does not make the topic branch production-adopted,
alter capture or Scheduler state, or relax any credential, geography, account,
money, order, cancellation, deadline, cleanup, or attendance gate.

Conventions for naming, ordering and reading the correspondence are in
[`docs/roadmap/AGENTS.md`](../roadmap/AGENTS.md). This file owns the *content* contract.

---

## 1. Host roles

| Host | Role | Constraint |
| --- | --- | --- |
| **Production (16 GB)** | Live capture, settlement, release, guarded runtime integration, merge timing | Capture is the priority. Heavy work only 00:30–09:00 |
| **Workstation (32 GB)** | Research, implementation, tests, training, replay, measurement | Exact tracked non-capture host/principal; outside the capture-host timetable/resource admission; heavy commands use the admission-only shared-mutex wrapper and cannot overlap a launched live stage; cannot see production `data/`; its mirror is **FROZEN at 2026-08-12 05:03** and is not authoritative |
| **Portable live executor** | One attended fixed-scope International Stage 0/1 lifecycle session; may be the same physical PC as the workstation | Exact adopted master or the single operator-authorized topic ref under its full equality/ancestry contract; no capture, release, Scheduler, production-state, unattended, or general-live authority; Git/PR actions follow explicit operator authority and `docs/git-workflow.md`; provision and relocate only through `PORTABLE_LIVE_EXECUTION_HOST.md` |

The portable executor is a role, not a permanent machine name. The same
physical PC may do ordinary workstation work outside a launched live stage;
that work uses the workstation role and must not claim the portable live
profile or its evidence. Its offline wrapper shares only the host-global mutex.
The live role uses a clean checkout at an exact reviewed Git authority, creates
host-local credentials and attempt evidence, and is rebound whenever it moves
to another Windows installation. Normally that authority is the
production-adopted master tip; the exact portable-only topic branch permitted
by the 2026-08-30 operator decision is the sole pre-adoption exception. A
portable live session is not a delegated research mission:
its narrowly authorized exchange writes are governed by
[`INTERNATIONAL_MM_LIVE_PILOT.md`](INTERNATIONAL_MM_LIVE_PILOT.md), while all
implementation or research work on that PC remains inside the workstation
boundaries below.

The production host writes handoffs and verifies handbacks. The workstation implements and measures.
The workstation may perform explicitly authorized source-control actions,
including PR creation or merge, under the Git workflow and owning integration
runbook. It never registers Scheduler tasks or writes production runtime state.

**The mirror is not evidence.** It lags and has repeatedly produced confident wrong conclusions
about live state. A workstation mission that needs live evidence must be handed that evidence as
facts in the handoff, and must say which of its conclusions depend on them.

**Since 2026-08-12 the mirror is PAUSED, so it does not lag — it is FROZEN**
([record](mirror-paused-2026-08-12.md)). The rule above is unchanged and now binds harder: a date
after 2026-08-12 simply does not exist on the workstation, and a mission that reads `data/` there
is reading a fixed snapshot of that morning, not a stale-by-a-day copy.

---

## 2. Standing boundaries — inherited by every delegated workstation mission

These are not per-mission preferences. A delegated workstation mission that breaches one has
failed regardless of its result. They do **not** revoke the production master agent's separate
authority in `OPERATIONS_AGENT_ROLE.md` to operate this host, schedule tasks, integrate reviewed
work, or write required receipts. A production agent executing delegated implementation scope is
still bound by this section for that mission; a production operations action is governed by the
role file and host runbooks.

**Production safety**

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled task,
  write nothing under `data/` on the production host.
- **Never write to the workstation mirror or `D:\weather-mirror`.**
- **Never read or expose `C:\Users\micha\.weathersync.cred`.**
- PR creation and merge require explicit repository-owner authority and the Git
  workflow's review, CI, and merge-method gates. When an owning runbook requires
  guarded production-host integration, use that path; a remote ref change is
  not production adoption. The narrow portable topic-ref exception above is
  live authority only for its exact portable role and branch; it does not claim
  a production merge, capture adoption/recovery, Scheduler state, or broader
  exchange authority.

**Evidence integrity**

- [`reserved-confirmation-window.md`](reserved-confirmation-window.md) **wins over every handoff.**
  Check it at run time — do not assume its contents are unchanged since the handoff was written.
  **Reading a reserved target date destroys it permanently.**
- **Never weaken the trusted observed-high floor.**
- **Do not relax the promotion gate for `harvest_only` rows.** That requires an operator decision plus
  a code change and is explicitly not delegated.
- **Do not relax a gate to make it pass.** Gates in this project are frequently correct when they
  refuse. If a gate is right, the deliverable is the sentence explaining why, not a patch.
- Never rewrite published git history. **Never delete a branch** — agent reports exist only on
  unmerged branches.

**Providers**

- **Free-tier Open-Meteo only. No paid API, ever**, without a new dated operator decision in
  [`forecast-source-and-training-population.md`](forecast-source-and-training-population.md).
- That file also closes the licensing question permanently. **Do not stop a mission on provider
  licensing or on the training population** — both are decided. This exact block halted two missions.

**Scope**

- Do not fit a model, produce a candidate, or promote anything unless the handoff says so explicitly.
- Stay inside the files the handoff assigns. Concurrent missions own other files; if you need one,
  **report the requirement instead of taking the file.**

---

## 3. Roll sensitivity — how to decide it

Landing code on the production host can restart live capture and cost a streak day. Getting this
verdict right is the difference between a safe merge and a lost day.

### The roll happens at MERGE on production, never at commit on the workstation

**A workstation mission must always commit and push its branch, at any hour, including inside the
graded window.** Doing so carries no capture risk and §2 requires it; §5 cannot be satisfied
without the resulting commit hash.

The capture supervisors fingerprint the **source files in the production host's working tree**
(`runtime_identity.identity_source: git_filesystem`). A branch on `origin` is a remote ref: it
changes no file in that tree, so it cannot change the fingerprint and cannot trigger a
`STALE_CODE` readoption.

Measured 2026-08-06, inside the graded window: branch
`codex/fix-wu-404-classification-2026-08-06`, which modifies `wu_history.py` — in the snapshot and
observation-trigger closures — was pushed at ~14:00. Snapshot `source_fingerprint` was
`cbb7175fb9031ba6` before and `cbb7175fb9031ba6` after, with capture at iteration 840, zero errors.
Over the same afternoon `git_commit` advanced through six commits on master with the fingerprint
unchanged: **runtime identity tracks source file content, not commit ids or refs.**

So the roll verdict below governs **when the production agent merges**, not when the workstation
commits. A mission that withholds a push to protect the streak has misread this section and has
blocked its own handback for nothing.

- **The test is the loaded-module import closure**, recorded in the capture status files as
  `runtime_identity.source_scope_files`. **Do not derive it by hand — run
  `scripts\ops\roll_verdict.ps1 -Branch <branch>`.** Exit 0 roll-free, 2 roll-free only while a
  dormant loop stays down, 3 roll-sensitive, 1 undecidable. `quiet_window_merge.ps1` consults it
  and only requires 01:00–04:00 for a branch that is genuinely roll-sensitive.
- **The four closures, and the file that carries each** — the naming is not uniform and a
  hand-derived verdict on 2026-08-06 got it wrong in both directions at once:

  | Closure | File |
  | --- | --- |
  | snapshot | `data\snapshots\loop_supervisor_status.json` |
  | CLOB | `data\snapshots\clob_loop_supervisor_status.json` |
  | observation-trigger | `data\snapshots\observation_trigger_supervisor_status.json` |
  | CLOB-enrichment | `data\snapshots\clob_enrichment_status.json` — **note: not `*_supervisor_status.json`** |

  The former `loop_status_supervisor_status.json` tombstone was retired from the live namespace on
  2026-08-14 and preserved under `data/snapshots/_retired_supervisor_status/`. It was not a fifth
  closure. `roll_verdict.ps1` uses the explicit table above and rejects any configured closure
  whose current state is `DEAD` or `BLOCKED`.
- **The `SOURCE_PATTERNS` glob is not the test.** It over-reports and wastes quiet windows.
- Markdown, `docs/`, and `config/` are roll-free. `.ps1` scripts are roll-free (status closures
  contain Python only).
- **The whole `schema_registry*` family is in all four closures** — `schema_registry.py`,
  `schema_registry_data.py`, `schema_registry_recent_data.py`, `schema_registry_types.py`
  (verified 2026-08-06 against the live snapshot and observation-trigger status files). Any change
  to any of them rolls every capture loop at merge. Central registration is *mandatory* —
  `schema_version()` raises `KeyError` on unregistered names — so the roll cannot be avoided, only
  made **purely additive** and therefore behaviourally inert. **A mission touching this family must
  state in its report whether its change is additive-only**; that is what lets the production agent
  treat the merge as a low-risk roll rather than a behavioural one.

Every mission must deliver a **per-file roll verdict**, stating which closures each changed file
enters. Roll-sensitive branches merge only in the **01:00–04:00 quiet window** and never inside
**12:00–18:00**, the graded capture window. An exact exit-0 roll-free tip may use the canonical
09:00–18:00 control-plane lane. That lane still takes the shared lease, so Stage A or any heavy
owner blocks it; it is not permission for tests, training, replay, bulk scans, Scheduler changes,
or a hand-derived verdict. Pushes, PRs, reviews, and workstation verification remain daytime work
and never require the production quiet window.

---

## 4. What a handoff must contain

1. **Goal in one sentence**, stated as the outcome, not the activity.
2. **"Start from this, do not re-derive it"** — established facts with values, so the mission does not
   re-measure what is known. Cite [`ESTABLISHED_FINDINGS.md`](ESTABLISHED_FINDINGS.md).
3. **Prioritised work (P0/P1/P2…)**, with the cheapest falsifying test first. If a repair might be
   unnecessary, testing that must be P0.
4. **Boundaries** — §2 plus anything mission-specific, including the concurrent file owners.
5. **"What would falsify this mission"** — the outcomes that would mean the premise is wrong. This
   section is mandatory. A mission that cannot fail is a mission that will confirm whatever it was
   sent to find.
6. **Exact branch name** and **exact report path**.

Write the falsification section honestly. Several missions in this project produced their most
valuable output by falsifying their own premise.

---

## 5. What a report must contain

1. **Verdict first**, in bold, including refusals and NO-GOs.
2. **Measured values with support** — date clusters, market clusters, market-days — and the interval
   treatment used. Crossed date x market clustering is mandatory (`ESTABLISHED_FINDINGS.md` §5).
3. **Per-file roll verdict** derived from the retained closures.
4. **What was NOT done**, explicitly: no registration, no production write, no restart, no merge.
5. **Exact reproduction commands**, with paths that exist on the host that will run them — not
   workstation-local scratch paths.
6. **Commit hash and branch.**

---

## 6. Verification on handback

The production agent verifies before accepting. Standard checks:

- **Positive controls reproduce.** A measurement stack that cannot reproduce a retained finding is
  wrong; the retained finding is not.
- **Load-bearing code claims are checked against the source**, not accepted from the report.
- **Reproduction commands are checked for path existence on this host.** Workstation scratch paths are
  the most common defect in an otherwise correct report.
- **Roll verdict is re-derived** before scheduling a merge window.
- **Push is verified**, always: production adoption uses
  `git ls-tree -r --name-only origin/master | Select-String '<slug>'`. The
  portable-only pre-adoption exception instead requires an exact bounded
  `git ls-remote --exit-code --refs` query of canonical
  `refs/heads/codex/portable-execution-host-clean-20260827`, equality to the
  reviewed local/cached tip, exact-head CI/review, and explicit owner
  authorization. Claiming a push without verifying the governing remote ref
  has happened here and was caught by the operator.

---

## 7. Concurrency

Missions run in parallel when they are **file-disjoint**. Before dispatching, check actual diffs:

```powershell
git diff --name-only "origin/master...origin/<branch>" | Where-Object { $_ -like 'src/*' }
```

- Overlap on a file is a merge conflict and, worse, an invalidated assumption.
- Purely additive overlap (new entries in a registry) is tolerable if every party knows.
- The binding constraint on parallelism is usually **the merge queue and review bandwidth**, not the
  workstation's capacity.
- A soak or timing measurement in flight constrains what else may run: bytes and RSS are insensitive
  to unrelated load, but **CPU share and reconnect counts are not.**

---

## Related

- [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md) — what is known
- [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) — what is not true despite appearing so
- [AGENT_CONTEXT.md](AGENT_CONTEXT.md) — durable domain invariants
- [HOST_LOAD_POLICY.md](HOST_LOAD_POLICY.md) — heavy-work windows
- [OPERATIONS_AGENT_ROLE.md](OPERATIONS_AGENT_ROLE.md) — the production agent's standing role
- [`docs/roadmap/AGENTS.md`](../roadmap/AGENTS.md) — correspondence naming and reading order

## Update this file when

Delegation boundaries, host roles, roll-verdict method, or the required handoff/report structure
change. Do not put mission-specific content here.
