# Audit dimension: Agent governance - process weight versus throughput

Key: `agent-governance`. Auditor run: 2026-09-19 (host local ~02:20-03:30, quiet window).
Read-only. No project file was modified; this report is the only write.

Health grade: **D**

---

## 1. Scope and method

Question set (from the brief): how many steps/receipts/gates stand between a finished change and
production adoption; success rate of guarded integrations and qualification attempts over the last
30 days; branch-to-adoption latency; the cost of immutable per-attempt namespaces; whether the two
agent systems (Codex, Claude) duplicate or contradict each other; whether governance has become
the main product; which controls are load-bearing and which are ceremony; what to KEEP.

Files read in full: `docs/operations/DELEGATION_CONTRACT.md`, `OPERATIONS_AGENT_ROLE.md`,
`INTEGRATION_ATTEMPT_RUNBOOK.md`, `STATE_OF_PLAY.md`, `docs/git-workflow.md`,
`docs/documentation-maintenance.md`, `CONTRIBUTING.md`, root `AGENTS.md`, `scripts/ops/AGENTS.md`,
`docs/roadmap/AGENTS.md`, `.github/pull_request_template.md`, `scripts/ops/merge_queue_driver.ps1`.
Read in part (traced lines cited below): `src/weather/operations/documentation_transaction.py`,
`scripts/ops/status.ps1`, `scripts/ops/bounded_worktree_test_suite.ps1`,
`scripts/ops/quiet_window_merge.ps1`, `scripts/ops/memory_commit_guard.ps1`,
`docs/operations/HOST_LOAD_POLICY.md`, `docs/ops/streak-soak.md`, `ESTABLISHED_FINDINGS.md`,
items 329 and 330, `docs/roadmap/branch-retirement-2026-08-11.md`.
Live files (explicitly allowed): `data/alerts/quiet_window_merge_last.json`,
`data/alerts/quiet_window_merge_history.jsonl` (all 75 records - the file is only 76 lines),
`data/alerts/documentation_transaction_pending.json`, and `data/alerts/MORNING_BRIEFING.md`
(generated 2026-09-19 02:20; the brief names its task list as a source).
Git (whitelisted, serial, piped through head): `git log`, `git branch`, `git worktree list`,
`git ls-files`, `git diff --stat/--shortstat`, `git show <rev>:<path>`.

Basis labels used: verified_in_code, live_state, doc_claimed, inferred.

One deviation to disclose: I ran a single-file Grep against `.codex/hooks/pre_tool_use_host_load.py`
(the brief allowed reading `.codex` text; `.codex` is not in the general Grep allow-list). It was a
one-file search, not a directory walk.

---

## 2. Headline

The project has a real safety culture and several controls that demonstrably protected capture.
But over the last ~4 weeks the governance layer has out-grown the work it governs:

- The **unattended, receipt-governed adoption path has not produced one PASS since 2026-08-23**
  (0 of 4 immutable integration attempts; 0 of 19 real qualification-family tasks on 09-12..09-14),
  and at today's disk level it **cannot** pass: its suite gate hard-requires 50 GiB free and the
  host has 11.3 GB.
- Everything that did reach production in the last 30 days got there by an **attended** agent
  running `quiet_window_merge.ps1` directly (or by plain `git merge`), typically within minutes to
  hours of the branch being created.
- The declared product direction (item 330 maker economics, PR 55) is explicitly **queued behind**
  a reliability candidate (PR 61) that is itself governance machinery, which is blocked on
  qualification machinery, whose proposed remedy (on an unmerged branch) is four new receipt schemas.
- On master in the last 30 days, merge/admission/status governance scripts and their tests took
  **34,757 inserted lines in 30 files**; every product package plus its tests took **14,573 in 53**.

---

## 3. Steps, receipts and gates between "change finished" and "production adopted"

### 3a. Roll-free documentation change (as actually executed 2026-09-13, merge-history record 75)

Agent/human steps:
1. Intake record (outcome, acceptance, owner, risk, base) - `docs/git-workflow.md:94-99`.
2. Inspect status/worktrees/branches, classify every dirty path - `:101-113`.
3. Create isolated worktree + `codex/<topic>` from fetched `origin/master` - `:118-141`.
4. Edit; run `agent_docs_audit`, roadmap lint, focused docs tests - `docs/documentation-maintenance.md:45-52`, PR template `:10-13`.
5. Whole-branch diff review against target (4 commands) - `git-workflow.md:188-199`.
6. Stage exact paths, cached-diff review - `:205-216`.
7. Commit; push topic branch (on this host, interactive push has no credentials, so a one-shot
   push task is used - `OPERATIONS_AGENT_ROLE.md:164-167`; briefing shows `WeatherCodexTopicPush_*` tasks).
8. Draft PR, 9-checkbox template, CI - `git-workflow.md:228-251`.
9. Owner approval - `:28-29`.
10. Guarded adoption with `quiet_window_merge.ps1 -ExpectedTip <40-hex> -ExpectedBaseline <40-hex>`.
11. Documentation transaction closeout by 09:00 - `documentation-maintenance.md:67-126`
    (review STATE_OF_PLAY, items, backlog; run checks; publish; hand-write a completion manifest with
    pending SHA-256, ordered tips, doc tip, reviewed docs, evidence path, per-document blob OIDs;
    run `complete`; obtain immutable PASS receipt).
12. Worktree/branch cleanup - `git-workflow.md:271-305` (in practice never done; see F6).

Automated gates inside step 10 for a change with **0 importable files** (log of record 75,
`data/alerts/quiet_window_merge_last.json:86-108`): time-window check, roll verdict,
push-task definition binding, exact-tip binding, master==origin/master, commit of the two generated
config files, capture-before proof (3 workers), staged merge, **300 s settle "for supervisors to
readopt the new code"**, capture-after proof, merge commit, documentation-transaction record,
second push-task binding, push, origin acknowledgement. **15 gates, >= 5 min 15 s wall clock**,
for a docs-only diff that by the project's own rule cannot roll anything
(`DELEGATION_CONTRACT.md:184-185`).

Durable records: PR record, merge report + history line, doc-transaction pending snapshot,
completion manifest, completion receipt = **5**.

### 3b. Roll-sensitive code change via the mandated immutable-attempt path

Steps 1-9 as above with the full verification matrix, then:
10. `roll_verdict.ps1` (exit 3).
11. Clean isolated registered worktree at the reviewed full SHA.
12. `new_integration_attempt.ps1` (8+ parameters) -> manifest freezing baseline, tip, SHA-256 of every
    orchestration PowerShell dependency, tracked test-file count, chunk size/count, local wall-clock
    schedule (suite in 00:30-09:00; merge in 01:00-03:40 and >= 30 min after suite; DST-ambiguous
    hours refused) - `INTEGRATION_ATTEMPT_RUNBOOK.md:62-123`.
13. Record manifest SHA-256; obtain explicit operator authorization for Scheduler registration - `:146-147`.
14. `register_integration_attempt.ps1` -> registration-intent, two S4U one-shots, read-back
    attestation, registration receipt - `:155-170`.
15. Night: preflight (7 ratchets, `:39-43`) then full suite in 20-file chunks (~21 chunks for 413
    test files). Before work and **before every chunk**: 3 healthy capture workers, commit <= 64 %
    start / 66 % abort, **>= 50 GiB free on every involved volume**
    (`bounded_worktree_test_suite.ps1:20-25, 288-312, 348-363, 365, 608`); 90-minute ceiling; 09:00 hard stop.
16. Merge task: waits for suite, re-verifies 7 groups (`RUNBOOK:180-195`), then runs the 15 gates of
    3a plus execution-tape recovery proof -> `merge-receipt.json` PASS.
17. Hash receipt; `assert_integration_attempt_success.ps1` before anything downstream - `:445-456`.
18. `adopt_execution_tape_after_merge.ps1` where applicable.
19. Documentation transaction (as 3a.11).

On any failure: `close_integration_attempt` (closure receipt) -> hash -> `dispatch_integration_attempt_recovery`
(one of 5 failure classes) -> descendant repair commit -> new attempt id with `-RepairClass`,
`-RepairOfReceiptPath` and an atomic `successor-claim.json` -> re-register -> **next night**
("The current merge window is then spent", `RUNBOOK:104-106`).

Durable records on the happy path: **>= 10** (manifest, registration intent, registration receipt,
preflight log, suite log, suite receipt, quiet-merge report, merge receipt, doc snapshot, completion
manifest + receipt). Failure adds 3 more. Minimum calendar time: one night; one merge window per night.

Size of the machinery that implements 3a/3b (line counts, `scripts/ops/*.ps1`): `quiet_window_merge` 4,092;
`integration_attempt_contract` 1,799; `reconcile_integration_attempt` 1,363;
`production_baseline_scheduler_rpc` 1,045; `bounded_worktree_test_suite` 790; `integration_attempt_merge` 732;
`close_` 381; `new_` 367; `suite_gated_quiet_merge` 343; `register_` 309; `integration_attempt_suite` 308;
`roll_verdict` 264; `adopt_execution_tape_after_merge` 243; `assert_` 143; `dispatch_` 132;
`merge_queue_driver` 70. **Total ~12,400 of 28,747 PowerShell lines (43 %)**, before
`workload_admission` (2,049) and `status` (4,591).

---

## 4. Measured success rates

### 4a. Guarded merges (`data/alerts/quiet_window_merge_history.jsonl`, all 75 records, 2026-08-06..09-13)

| Period | Records | Pushed | Dry-run | Abort | Rolled back | rollback_recovery_failed |
| --- | --- | --- | --- | --- | --- | --- |
| 08-06..08-11 | 48 | 35 | 1 | 11 | 1 | 0 |
| 08-14..08-26 | 14 | 11 | 0 | 1 | 2 | 0 |
| 09-03..09-13 | 13 | 9 | 1 | 2 | 0 | 1 |
| **All** | **75** | **55** | 2 | 14 | 3 | 1 |

Last 30 days (records 55-75, 08-19..09-13): 21 invocations, **15 pushed, 1 dry-run, 5 failed**
(75 % of real attempts). Classification of the 5 failures:
- 1 true defect catch - record 60, 08-23 19:40: execution-tape closure rolled but did not re-adopt; clean rollback.
- 1 window guard - record 59, 08-23 19:15; the owner then granted a one-time protected-window exception 8 minutes later (records 60/61).
- 3 self-inflicted by the tooling's own strictness or bugs: record 63 (09-03) the one-time reconciliation
  refused because "WeatherOneShotPush task XML changed from the reviewed definition" - a night lost;
  record 69 (09-10) a `-DryRun` committed the generated config then failed its own rollback check
  (`rollback_recovery_failed`, "original=dry-run merge_exit=0 conflicts=0"); record 72 (09-10) a
  mistyped 41-character `ExpectedBaseline`.

No production adoption has been recorded since 2026-09-13 04:09 (6 days). 3 of the last 4 adoptions
(records 73, 74, 75) were status-only documentation branches with 0 importable files.

Throughput context: the tool was ~240-380 lines when it landed 35 branches in 5 days (08-07..08-11,
mostly one-file workstation reports, driven by an allowlist queue). It is 4,092 lines now
(`git log --follow --shortstat`: +953 on 08-21, +1,920 on 09-01, +1,167 on 09-02). The early period is
not like-for-like (smaller branches), but supply is not the limit today: **76 remote branch tips
dated on/after 2026-08-19 are unmerged** (108 remote unmerged in total).

### 4b. Immutable integration attempts (item 329), from the briefing task list

| Attempt | Suite | Merge | Outcome |
| --- | --- | --- | --- |
| workflow-minimal-0822-a1 | ran 0x0 (l.117) | tip in production (l.105) | PASS |
| stage1-readiness-0823-a1 | never ran 0x41303 (l.115) | superseded (l.103) | - |
| stage1-readiness-0823-a2 | ran 0x0 (l.116) | tip in production (l.104) | PASS |
| credential-reconcile-0824-a1 | FAIL 0x1 (l.113) | never ran (l.100) | FAIL |
| credential-reconcile-0825-a2 | FAIL 0x1 (l.114) | FAIL 0x1 (l.102) | FAIL; "recovery is ready for an active agent" since 08-25 (l.101), unconsumed 25 days |
| 48h-maker-20260912-a1 | never ran (l.111) | never ran (l.97) | - |
| 48h-maker-20260912-a2 | FAIL 0x1 (l.112) | FAIL 0x1 (l.99) | FAIL; "closed and needs reviewed recovery dispatch" (l.98) |

**2 PASS of 7, both on 08-22/23; 0 of 4 since.** Both branches that failed are still unmerged.

### 4c. Qualification family a1..a11, 2026-09-12 21:24 -> 09-14 06:45 (briefing l.16, 32-33, 58-88, 140-142, 154-155)

- 39 scheduled tasks were registered for this one effort.
- **Real tasks (Qualification / FollowThrough / MorningAudit): 19. PASS: 0.** 11 never ran at all
  (`0x41303`, last-run 1999 - superseded by the next namespace before their trigger); 8 ran and failed
  (`CompleteQualification` a8 0x1, a9 0x41306, a10 0x1, a11 0x1; `CompleteFollowThrough` a6, a7 0x1;
  `MorningAudit` a8, a9 0x1).
- **Smokes: 18 of 19 exited 0x0** (one "unexpectedly DISABLED"). A smoke pass predicted nothing.
- Nine namespaces (a2..a10) were minted in about 9.5 hours.

Root causes as the project records them (doc_claimed): a PowerShell 5.1 strict-mode failure on an
empty Git-query array inside the qualification apparatus; "disposable test fixtures that assumed the
portable PC's identity, plus a launcher fixture using obsolete seal tokens"; the follow-through
"ended FAIL at 03:25:01 because its exact suite receipt deadline passed" while the suite was still
running (`item-329...md:10-16, 23-29`); and resource refusal - "stopped at 67.19% commit against its
66% abort limit after ten completed chunks ... A smaller-chunk successor on September 14 stopped
during its first chunk at 68.5%" (`git show b0cab6f8e:docs/roadmap/agent-report-2026-09-14-qualification-design.md`, section 1).
**None of these is a defect in product behaviour; every one is a defect or limit of the
governing apparatus or its own fixtures.** The same item records that hosted CI then passed 210 native
Windows checks (`item-329:18-21`) - i.e. the fixture class was discoverable off-host.

### 4d. All retained one-shot tasks dated 08-19..09-17 in the briefing (manual count, approximate)

~64 FAILED or never ran; ~35 succeeded, of which 19 are smokes and 5 are topic pushes. Substantive
successes (suite / merge / closeout / preflight): ~9.

---

## 5. Branch creation -> adoption latency

For the 16 branches adopted 2026-08-22..09-13 (first branch-only commit -> merge commit, `git log`):
2 min, 7 min, 13 min, 22 min, 27 min, 31 min, 42 min, 58 min, 2.7 h, 6.7 h, 13.5 h, 18.5 h, 1.65 d,
1.77 d, 2.69 d, 5.49 d. **Median ~1.8 hours; mean ~0.9 days; max 5.5 days.**

That number is survivorship-biased. The distribution is bimodal: what an attended agent lands,
lands in minutes (e.g. `e31720cc9`, a 5-line fix, 2 minutes, outside the guarded tool); what is handed
to the unattended governed path waits indefinitely - `credential-reconcile-20260823` 27 days,
`production-bind-model-identity-to-the-process-2026-08-11` 39 days, `48h-maker-integration-20260912`
7 days, the `reliability-*` stack 6-7 days, plus `capacity-150gb-20260915` and
`recovery-end-to-end-20260917` while the disk is at 11.3 GB. The practised fast path is not the
documented path (draft PR -> CI -> owner approval -> GitHub merge commit).

---

## 6. Findings

### F1 (HIGH) - The mandated unattended adoption path has ~0 % recent success and is currently unpassable
- `bounded_worktree_test_suite.ps1:288-312` throws unless every involved volume has >= 53,687,091,200
  bytes free; called at `:365` and before each chunk at `:608`; `integration_attempt_suite.ps1:168`
  delegates to it. Briefing l.14: "LOW DISK: 11.3 GB free"; l.12: "about 2 days of headroom".
  `STATE_OF_PLAY.md:24`: "Ordinary qualification retains its 50 GiB disk floor."
- Before disk was the limit, commit admission was: 64/66 % (`:23-25`), refused at 67.19 % and 68.5 %
  on 09-13/14 (design report on `origin/codex/qualification-design-20260914`).
- Results: section 4b/4c. `STATE_OF_PLAY.md:35,38` and `item-330:5-8` put the maker candidate (PR 55)
  behind the reliability candidate (PR 61) behind host qualification.
- The attended bypass exists and is what actually works: `quiet_window_merge.ps1` has no disk floor
  (no `FreeSpace`/`50 GiB` match in it, `workload_admission.ps1` or `integration_attempt_merge.ps1`), and
  the 105-file roll-sensitive `bulk-cold-archive` branch landed that way on 09-10 (record 70) with no
  attempt tasks in the briefing.
- Known status: the "qualification bottleneck" is recorded by the project (unmerged design branch,
  `STATE_OF_PLAY:35`); the disk-floor lock-out is not recorded anywhere I could find.

### F2 (HIGH) - Immutable per-attempt namespaces multiplied the cost of apparatus bugs; smokes do not predict real runs
Evidence in 4c. 39 tasks, 0/19 real PASS, 18/19 smoke PASS, 11 tasks superseded before they ever
ran. `STATE_OF_PLAY.md:44-46` orders "Preserve the failed qualification/follow-through receipts ...
Do not reuse spent attempt namespaces" as critical-path item 1. Spent tasks are never deleted
(`scripts/ops/AGENTS.md:40-41`; `OPERATIONS_AGENT_ROLE.md:199` "a spent one-shot flags forever until
unregistered"), so each namespace is a permanent Scheduler and briefing entry. Item 329 was itself
built because "Several nights were then spent rediscovering or documenting blockers"
(`item-329:49-53`); three weeks later the same pattern recurred one level up.

### F3 (HIGH) - A GitHub-side merge strands production, and the canonical Git SOP still instructs one
- `docs/git-workflow.md:258-261`: "After repository-owner approval, use a GitHub merge commit".
- The production path refuses unless local `master == origin/master` (`docs/ops/streak-soak.md:327`;
  `ESTABLISHED_FINDINGS.md:2534-2537`; history records 2-6).
- It happened: PR #4/#5 merged on GitHub 08-30/08-31 put origin 26 commits ahead of production
  (`git log 3361520fa..c932b54f8`). No production adoption 08-26 -> 09-04; one failed night (record 63).
- The remedy was a one-time mode hard-coded to that SHA pair: `quiet_window_merge.ps1:1353-1357`;
  +3,087 lines to that script on 09-01/02; `production_baseline_scheduler_rpc.ps1` 1,045 lines;
  `streak-soak.md:325-565` (240 lines); `scripts/ops/AGENTS.md:67-117` (50 lines of a scoped agent guide).
  `ESTABLISHED_FINDINGS.md:2564-2565`: it authorizes no "other baseline pair".
- PRs 55 and 61 are open. One click on "Merge" re-creates the split with no tool to resolve it.
- Every ordinary merge report now carries ~40 null reconciliation fields
  (`quiet_window_merge_last.json:10-32, 48-51, 60-81`).

### F4 (HIGH) - Effort has shifted to governing the work rather than doing it
- `git diff --shortstat a76ec7b55 master` (08-19 -> now): 325 files, +120,472 / -14,820.
  By file share (`--dirstat=files`): tests/operations 22.4 %, src/weather/operations 18.1 %,
  scripts/ops 16.3 %, docs/operations 8.3 %, docs/roadmap 5.8 % (71 %); src/weather/market 9.2 % +
  tests/market 5.8 %; model, calibration, sources, collection each under the 5 % reporting threshold.
- Merge/admission/status governance scripts + their tests + doc-transaction + Codex hook:
  **30 files, +34,757**. All product packages (market, model, calibration, sources, collection,
  backtesting, app) + their tests: **53 files, +14,573**. Docs: 66 files, +10,247.
- `.codex/hooks/pre_tool_use_host_load.py` went from 144 lines (08-23 incident fix) to ~3,200
  (+2,790 on 08-29); it is 110 KB and runs on every Codex tool call.
- The remedy proposed for the qualification bottleneck is `qualification_policy_v2`,
  `code_qualification_v2`, `host_acceptance_v2`, `integration_attempt_merge_receipt_v2` - four new
  strict-schema record types - and sits on an unmerged branch, as does its own audit.
- "No new model-alpha work" and "focus on reliability/storage" are owner decisions (accepted). What is
  new here is the measurement that "reliability" has mostly meant merge-governance, and that the one
  declared product track is queued behind it.

### F5 (MEDIUM) - The documentation transaction has been open since 2026-08-23 and overdue since 08-24 09:00
- `data/alerts/documentation_transaction_pending.json:2-3,72-74`: created 08-23 20:04, due 08-24 09:00,
  11 integrations, `PENDING`.
- Trace: `documentation_transaction.py:163-174` starts a fresh list only if the state is COMPLETE at
  the next `begin`; `:175-198` otherwise appends. The list was appended on 08-26, 09-04, 09-05 (x4),
  09-10 (x3), 09-13 - so it was not COMPLETE at any of those moments.
- `status.ps1:4285-4293` adds the flag "DOCUMENTATION TRANSACTION DUE" whenever overdue - a red flag on
  the daily read for ~26 days. The project's own rule: "a monitor that flags a deliberate decision
  daily trains you to ignore it" (`OPERATIONS_AGENT_ROLE.md:289-291`).
- Structural cause (inferred): closing it normally needs a docs commit; docs commits reach master
  through the guarded merge, which records itself as a new pending integration
  (`STATE_OF_PLAY.md:40`: "plus any subsequent guarded documentation adoption ... This rewrite alone
  does not clear it"). The 09-13 status-only merge is exactly that: integration #11.
- I did not read `data/alerts/documentation_transactions/` (not allowed), so completion after 09-13
  04:09 is unverified; `codex/documentation-transaction-20260904` remains unmerged.
- Known status: known_open (`STATE_OF_PLAY:40, 50-51`).

### F6 (MEDIUM) - "Never delete" rules accumulate branches, worktrees and spent tasks; the daily read is mostly noise
- 382 branches (local 115 merged / 102 unmerged; remote 57 / 108) and **200 worktrees** (`git branch`,
  `git worktree list`). 172 branches are full ancestors of master.
- `DELEGATION_CONTRACT.md:119-120` and `OPERATIONS_AGENT_ROLE.md:64-65` (rewritten 08-27): "Never delete
  a branch - agent reports exist only on unmerged branches". But `branch-retirement-2026-08-11.md:3-11`
  documents a safe manifest-based retirement and "Orphaned-report count at the time of writing: 0";
  `git-workflow.md:271-305` prescribes `git worktree remove` + `git branch -d`.
- 200 full checkouts on C: (both `C:/tmp/wt-*` and sibling `weather-*`, two conventions) at ~50 MB of
  tracked content each is on the order of 10 GB - unmeasured, inferred - on a volume with 11.3 GB free.
- `MORNING_BRIEFING.md`: 3 HIGH items at l.10-15; then 156 lines of standing notes of which ~149
  are spent one-shots back to 08-01.

### F7 (MEDIUM) - Two agent systems, two knowledge stores, contradicting contracts
- `OPERATIONS_AGENT_ROLE.md:20-22` makes Claude's auto-memory `MEMORY.md` (outside the repo, unversioned,
  same disk, invisible to Codex and to the workstation) mandatory read #2 - against its own
  `:31-33` "Findings live in the repo" and root `AGENTS.md:34-35`. Root `AGENTS.md:8-32` never mentions it.
  All work in the last 30 days is on `codex/*` branches and `WeatherCodex*` wake tasks.
- Launch-time prevention is Codex-only (`HOST_LOAD_POLICY.md:365-377`; no "claude" string in the hook);
  the OS backstop does cover `claude.exe` (`memory_commit_guard.ps1:96`). I could not inspect `.claude/`.
- Merge authority: `ROLE:118-119` "full authority over commits, pushes, merge timing, scheduled tasks ...
  Commit and push proactively" vs `git-workflow.md:19-21, 28-29` "a coding agent does not self-authorize it".
- Scheduler authority: `ROLE:118` vs `scripts/ops/AGENTS.md:130-132` and `RUNBOOK:146-147`.
- Top objective: root `AGENTS.md:92-93` and `streak-soak.md:1` "the #1 operational objective" (streak) vs
  `ROLE:39` (capture continuity), `STATE_OF_PLAY.md:9-12` (no streak), and Claude memory "STREAK GATES NOTHING".
- `ROLE:7` calls `docs/roadmap/AGENTS.md` "the coding contract"; it is the roadmap guide.
- Chunk size: `AGENTS.md:116` and `ROLE:141` "25-file" vs `RUNBOOK:116` "20-file" (`bounded_worktree_test_suite.ps1:20-21`: default 20, max 25).
  `AGENTS.md:141` lists bare `pytest -q` as canonical; `:114-116` forbids it on this host.
- `ROLE` was "Rewritten 2026-08-27" with the warning that its predecessor went 10 days stale (`:10-12, 354-356`);
  it is now 23 days old and ~70 of its 356 lines are an explicitly unmaintained 08-13 snapshot (`:203-275`).
- Mandatory pre-read for an ops change that ends in a merge: ~3,600 lines excluding
  `ESTABLISHED_FINDINGS.md` (2,753 lines, described as the "distilled state", and now also holding
  incident design text at `:2531-2591`).

### F8 (LOW) - Blanket rules are stricter than the mechanism, and the guard lives only inside the tool
- Docs-only merges wait 300 s and prove capture twice (record 75; also 34-37, 40-48).
- A roll-free docs branch was refused at 12:33 on 08-10 (record 38) and landed 17 h later.
- On 08-23, 11 merges reached production master between 12:41 and 16:00 (10 inside 12:00-18:00) with no
  `quiet_window_merge` record; their only `src` change was `capture_recovery_check.py`, which earlier
  verdicts class as roll-free. No harm is recorded - which shows both that the blanket ban is broader
  than needed and that nothing enforces it outside the tool.

### F9 (INFO) - Control ledger: what is load-bearing, what is ceremony
Load-bearing (evidence of an incident prevented or a concrete failure caught):
- Post-merge capture-recovery proof + automatic rollback before push: record 49 (08-14,
  `observation_trigger=runtime_identity_stale`), record 60 (08-23, execution tape stale), record 23
  (08-09, capture already down). Nothing was pushed in any of them.
- `roll_verdict.ps1` from the loaded-module closure: removed the 25-branch backlog (`AGENTS.md:102-103`).
- Exact-tip binding (`-ExpectedTip`), `master == origin/master` precondition (records 2-6).
- Protected-window refusal for roll-sensitive merges (records 12-14).
- Host load policy, OS memory guard, shared heavy-work lease: three documented incidents
  (`HOST_LOAD_POLICY.md:383-404`; `ROLE:134-138`).
- "Never relax a gate to make it pass", the falsification section in handoffs, RETRACTED ledger.
Ceremony (no incident shown to be prevented; measurable cost):
- Closure receipt / recovery dispatch / successor claim / registration intent (0 PASS since 08-23).
- Documentation-transaction completion manifest with blob OIDs (26 days overdue, blocks nothing).
- Push-task XML equality check (cost the 09-03 night).
- 300 s settle and capture proofs on 0-importable merges.
- Retaining every spent Scheduler task and every merged branch forever.
- The hard-coded one-time reconciliation mode left inside the permanent merge tool.

---

## 7. Strengths (genuine)

1. The capture-recovery-gated merge with pre-push rollback is a well-designed control that caught two
   real re-adoption defects and never pushed a bad merge (`quiet_window_merge_history.jsonl` records 49, 60).
2. `roll_verdict.ps1` decides roll sensitivity from the live import closure rather than a glob, and the
   project wrote down why (`DELEGATION_CONTRACT.md:137-197`).
3. The epistemic discipline is unusual and valuable: mandatory falsification sections, "verify before
   you accept", a retractions ledger, plain self-correction (`DELEGATION_CONTRACT.md:201-249`, `ROLE:279-308`).
4. `STATE_OF_PLAY.md` is a good idea executed within its cap (73 lines, rewritten not appended).
5. The project can be light when it chooses: a 70-line exact-tip queue driver
   (`scripts/ops/merge_queue_driver.ps1`) and a 2-minute attended fix (`e31720cc9`); and it has already
   once diagnosed and removed an over-broad gate (the quiet-window-for-everything rule, 08-06).

---

## 8. Recommendations - KEEP first

KEEP unchanged: capture-recovery proof + rollback; `roll_verdict.ps1`; exact-tip binding; the
quiet window for roll-sensitive merges; host-load policy, memory guard, heavy-work lease; falsification
sections; RETRACTED ledger; STATE_OF_PLAY as a capped rewrite.

Change (owner decisions; nothing here was done):
1. Run the full suite off-host (workstation/CI) and reduce the production step to a short acceptance
   probe plus the existing guarded merge. The project's own 09-14 design says this; adopt the idea
   without the four new record types.
2. Make the suite's disk and commit limits parameters of the host policy, or exempt storage-recovery
   and reliability fixes, so the remedy for low disk is not gated on having disk.
3. Fast-path roll-free changes: skip the 300 s settle and the second capture proof when the verdict
   shows 0 importable files; allow them outside 12:00-18:00 only if you want the rule, but say so once.
4. Replace the one-time reconciliation mode with a general "local master is an ancestor of
   origin/master" path, or remove the GitHub-merge instruction from `git-workflow.md`. Pick one.
5. Collapse the documentation transaction to a one-line acknowledgement in the merge report, or let
   `complete` accept "no doc change needed" without a guarded merge. Clear the 26-day flag either way.
6. Reinstate manifest-based retirement (the 08-11 procedure) for merged branches, worktrees and spent
   one-shot tasks; measure the worktree footprint in an admitted window first.
7. One contract, one memory: move what Claude's memory holds that is still true into the repo, drop it
   from the role file's read order, and reconcile the five contradictions in F7.
8. Reuse an attempt namespace when the failure class is "apparatus/fixture" rather than "candidate".

---

## 9. Not covered / open questions

- `.claude/` settings and any Claude-side hooks (forbidden path) - the hook asymmetry in F7 is therefore partial.
- `data/integration_attempts/**`, `data/alerts/documentation_transactions/**`, `scratch/handoffs/**` receipts
  (not allowed) - attempt outcomes come from the briefing's task list, not the receipts.
- Whether a full suite was run anywhere before the attended 09-10 roll-sensitive merge (record 70).
- Actual disk footprint of the 200 worktrees.
- GitHub PR/CI history (no network): PR counts, CI pass rates and review latency are unmeasured.
- `docs/development.md`, `OPERATIONS_DESIGN.md`, `PROJECT_OPERATING_SOP.md` were only skimmed by heading.
- Whether the 08-23 daytime merges were made on the production checkout or fast-forwarded from another clone.
- The ~600 dated correspondence files were not sampled for this dimension.
