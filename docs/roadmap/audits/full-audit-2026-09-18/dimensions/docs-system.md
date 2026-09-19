# Audit dimension: Documentation system (`docs-system`)

Auditor: docs-system subagent. Date: 2026-09-18 (evening, inside the protected near-close window).
Mode: read-only. Tools used: Read, Grep, Glob (all with explicit paths under `docs/`, `src/`, `scripts/`,
`app/`, `tools/`), plus whitelisted `git log`, `git diff --stat`, `git show <rev>:<path>`, `git branch`,
`git ls-files`, and non-recursive `ls` of `docs/`, `docs/operations/`, `docs/ops/`, `docs/roadmap/` and the
repo root. No Python, no tests, no scripts, no `data/` reads, no network.

Procedural disclosure: one Bash call chained five `git log -n 1 -- <file>` commands with `&&` instead of
issuing them one at a time. They ran sequentially, were each bounded to one commit of one file, and were
piped through `head`. No other deviation from the safety rules.

Live-state numbers quoted below (21 GB free, ~5.9 GB/day, 10 of 14 dates unsettled, streak 2/14, failed
one-shots a1..a11) come from the lead auditor's brief of `data/alerts/MORNING_BRIEFING.md`. I was not
permitted to read `data/` and did not. Everything about the documents themselves was read directly.

---

## 1. Scope covered

- Root: `AGENTS.md` (183 lines), `README.md` (first 520 lines of ~31 KB), `CONTRIBUTING.md`, `pyproject.toml`.
- `docs/`: `README.md`, `AGENTS.md`, `documentation-maintenance.md`, `development.md` (first 135 lines),
  `git-workflow.md` (parts 1-60, 228-312).
- `docs/operations/` (70 files listed): read in full `STATE_OF_PLAY.md`, `HOST_LOAD_POLICY.md`,
  `OPERATING_REFERENCE.md`, `AGENT_CONTEXT.md`, `OPERATIONS_AGENT_ROLE.md`, `DELEGATION_CONTRACT.md`,
  `README.md` (index), `reserved-confirmation-window.md`, `OPEN_BACKLOG.md`; read in part
  `ESTABLISHED_FINDINGS.md` (lines 1-877, 1040-1075, 2205-2229, 2380-2404, 2705-2754 of 2,754, plus full heading
  map), `RETRACTED_AND_FALSE_LEADS.md` (heading map + lines 290-380), `INTERNATIONAL_MM_LIVE_PILOT.md`
  (1-75 + heading map), `OPERATIONS_DESIGN.md` (244-265), `wu-settlement-source-down-2026-08-07.md`,
  `mirror-paused-2026-08-12.md`, `CAMPAIGN_LEDGER.md` (grep), `OVERNIGHT_BRIEFINGS.md` (headings).
- `docs/ops/`: `streak-soak.md` (1-70). `docs/roadmap/`: `AGENTS.md`, `active-backlog.md` (1-60), file-name
  inventory of handoffs/reports, git add-dates for three sampled files.
- Nested agent files: 18 tracked `AGENTS.md` files exist; read root, `docs/`, `docs/roadmap/`, `scripts/ops/`,
  `src/weather/operations/`.
- Tooling behind the docs: `src/weather/operations/documentation_transaction.py` (constants, completion
  checks, dispositions), `agent_docs_audit.py` (file lists + `audit_repo`), `operating_reference.py`
  (PROTECTED_WINDOWS), `scripts/ops/workload_admission.ps1:1469-1477`, `collection_health.py` constants.

## 2. Headline

The documentation system is well designed on paper (one owner per fact, generated references, a negative-
knowledge file, a link/ownership audit) and the tooling that exists works: I found **zero dead links in 25
spot checks**, the generated operating reference matches the code line-for-line, and README setup commands
are correct. But it is **failing at the one job the project assigns it first**: telling a cold agent what is
true *now*. The "read this first, always" file is 5.7 days old, no tracked document on `master` mentions any
date after 2026-09-13, and the mechanism that refreshes it is coupled to an integration pipeline that has not
landed anything since 2026-09-13 04:09. Around that core failure sit four secondary problems: contradictions
between canonical files about objectives, windows and git authority; an index that still advertises a fixed
incident as LIVE; a distilled-knowledge file that stopped being distilled (2,754 lines, missing the last 15
research missions); and a documentation-transaction control whose cost is high and whose protection is, by
its own text, an attestation rather than a check.

Grade: **C**.

---

## 3. Findings

### docs-system-1 (HIGH) - The "what is happening right now" file is frozen at 09-13 and nothing tracked records 09-14..09-18

- `AGENTS.md:10-14` makes `STATE_OF_PLAY.md` mandatory first reading "always, first, whatever the task";
  `AGENTS.md:163-166` says every other canonical file "deliberately says nothing about today".
- `docs/operations/STATE_OF_PLAY.md:3`: "Last updated: 2026-09-13". `git log` shows its last commit is
  `2b3eb68a7` 2026-09-13 03:42. `master` HEAD is `3bdba3d15` 2026-09-13 04:09; no commit has landed on master
  since.
- Grep of all of `docs/` for `2026-09-1[4-8]` / "September 1[4-8]" returns one false positive (an August report
  quoting a mission id). `docs/roadmap/items/` returns zero. So failed qualification attempts on 09-14, failed
  archive/storage-recovery tasks 09-14..09-17, the disk level and the current settlement hole are recorded in
  no tracked document on master.
- Work did continue: branches `codex/recovery-end-to-end-20260917`, `codex/capacity-150gb-20260915`,
  `codex/qualification-bootstrap-probe-20260915`, `codex/split-qualification-20260914` exist. I checked the
  three newest: none carries a STATE_OF_PLAY newer than 09-13. The newest branch (commit date 09-17) carries a
  version headed **"Last updated: 2026-09-10"** that still says "The 100 GB target remains open", i.e. it is
  *older* than master's and contradicts master's "owner accepted 79,105,806,336 bytes ... uploads are paused"
  (`STATE_OF_PLAY.md:31`). Integrating that branch will conflict on, or regress, the file.
- Structural cause: `STATE_OF_PLAY.md:72-73` lists rewrite triggers as owner decision, source adoption, measured
  storage outcome, validated settlement/job disposition, economic result. `documentation-maintenance.md:67-88`
  ties the review to "a successful guarded integration". There is **no time-based or degradation-based
  trigger**. When integration stalls (as now), the file freezes exactly when the host is in the most trouble.
- Consequence visible in the text: `STATE_OF_PLAY.md:44-46` sets critical-path step 1 as "qualify the reviewed
  repair with the admitted complete Windows host suite", and `:24` says qualification "retains its 50 GiB disk
  floor". With ~21 GB free (lead's live state) that step cannot be admitted, so the documented critical path
  is not executable and the file does not say so. `:39` describes settlement gaps only as "historical ...
  investigation leads" with no dates or counts.
- The project already knows the principle: `HOST_LOAD_POLICY.md:60-62` - "A stale operations document is worse
  than a missing one, because it gets believed." The specific staleness is not recorded anywhere.

Basis: verified_in_code (docs + git) for the document facts; live_state via lead brief for disk/settlement.
Known status: new.

### docs-system-2 (MEDIUM, becomes HIGH when research resumes) - The distilled research canon stopped being distilled; the last 15 missions live outside it

- `AGENTS.md:20-25` and `docs/README.md:69-73` say the correspondence "cannot be read" and that
  `ESTABLISHED_FINDINGS.md` + `RETRACTED_AND_FALSE_LEADS.md` "are its distilled state".
- `ESTABLISHED_FINDINGS.md` is **2,754 lines** (the Read tool reports ~66.7k tokens, more than 2.5x its
  single-read cap). Its model sections end at §1j (`:1040`, mission `-09-63a`, 2026-08-10). Grep for
  `-09-(6[4-9]|7[0-9])a` finds only three incidental mentions (`:1059`, `:1065`, `:2217`). There is no section
  for `-09-64a`..`-09-78a`: replay-does-not-reproduce, bytes-never-committed, `high_so_far` narrowing, the
  observation-recovery rule, the unpowered recovery thread.
- Those conclusions exist in three places a cold Codex agent will not reach:
  1. `docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md` - grep of `docs/` shows it is
     linked only from `GATE_3_FIRED_..._2026-08-10.md:443` and three roadmap handoffs. It is in neither
     `docs/README.md` nor `docs/operations/README.md`, nor in FINDINGS/RETRACTED "Related".
  2. `OPERATIONS_AGENT_ROLE.md:246-255` ("Replay thread CLOSED - never dispatch another historical-
     reproduction mission") - inside §7, whose own heading (`:203`) is "Historical snapshot - never use this
     section for current state" and "intentionally not maintained".
  3. A machine-local Claude auto-memory index, which `OPERATIONS_AGENT_ROLE.md:20-22` lists as reading #2 even
     though `documentation-maintenance.md:151` says local machine/agent files "are never project truth".
     Codex sessions (which produced essentially all September branches) do not have it.
- Freshness: `RETRACTED_AND_FALSE_LEADS.md` last commit `a76ec7b55` 2026-08-19; newest dated entry 2026-08-19
  (`:275`, `:290`); zero September entries. `ESTABLISHED_FINDINGS.md` last commit 2026-09-02; newest dated entries
  are 2026-09-01 (`:2531`, `:2560`, `:2640`) and all September additions are ops/integration (§8v-8x), not
  measurements. `HOW_WE_GET_THINGS_WRONG.md` last commit 2026-08-09. `CAMPAIGN_LEDGER.md` 2026-08-11.
- Both files are in `documentation_transaction.py:30-37 REQUIRED_REVIEWED_DOCUMENTS`, so every transaction
  since 08-19 "reviewed" them. The review did not surface a 15-mission gap.
- `OPERATIONS_AGENT_ROLE.md:27-28` says RETRACTED "is the longer of the two". It is 380 lines against 2,754.
- The file is appended, not distilled: `:37-39` says parts of §0b-§0c are "superseded" but leaves them in
  place; §1 retains retired numbers with strike-through prose; +245 lines in the last 30 days.

Basis: verified_in_code. Known status: new (the project records the *principle* "a result not written into
ESTABLISHED_FINDINGS or a trace doc did not happen", `OPERATIONS_AGENT_ROLE.md:31-33`, but not this gap).

### docs-system-3 (MEDIUM) - The operations index advertises a fixed incident as LIVE, states a paused mirror as running, and breaks its own linking rule 17 times

- `docs/operations/README.md:153-155`: "**wu-settlement-source-down-2026-08-07.md - LIVE INCIDENT.** The
  settlement proxy returns 404 for *every* date ... `-Refetch` works and still fails. Read before touching
  settlement, the chain, or the streak." The linked file's title (`:1`) is "root-caused and fixed 2026-08-07".
  The index was last edited 2026-09-09, so the label survived at least one edit.
  Today the host has a real settlement hole; the index routes an agent to a six-week-old closed cause.
- `docs/operations/README.md:167-169`: "the workstation is full because production mirrors 532 GB to it
  nightly". `mirror-paused-2026-08-12.md:3-21` records the mirror Disabled since 2026-08-12. The pause record is
  not linked from the index at all.
- `docs/operations/README.md:183`: "Anything added under `docs/operations/` must be linked from this index."
  Grep of the index for 17 file stems present in the directory returns **no matches**: `CAMPAIGN_LEDGER`,
  `INTERNATIONAL_MM_LIVE_PILOT`, `OVERNIGHT_BRIEFINGS`, `cold-snapshot-compression`, `maker-incentive-feasibility`,
  `production-cold-archive-staging`, `replay-cache-compression`, `storage-recovery-inventory`,
  `storage-recovery-night`, `mirror-paused-2026-08-12`, `taker-paused-and-pruned-2026-08-07`,
  `codex-host-overload-2026-08-23`, `FINALIZE_LOST_...`, `GATE_3_FIRED_...`, `REPLAY_FLOOR_...`,
  `REPLAY_DOES_NOT_REPRODUCE_...`, `SERVED_BAND_FLOOR_...`, `PRE_OVERNIGHT_AUDIT_...`. Seven of the undated ones are
  linked from `docs/README.md` instead; `CAMPAIGN_LEDGER.md` (the live alpha-spend ledger) and
  `OVERNIGHT_BRIEFINGS.md` are linked from neither index.
- The rule itself is inconsistent: `:183` says "Anything", `:196` says "undated operations contract", and
  `ESTABLISHED_FINDINGS.md:2221-2222` says the sweep was relaxed to non-dated files on 2026-08-14.

Basis: verified_in_code. Known status: new (the index text at `:188-192` admits the sweep is weaker than the
rule, but not that the rule is currently broken or that the two entries are false).

### docs-system-4 (MEDIUM) - Four canonical files state four different objective hierarchies; two still call the streak "#1"

- `docs/ops/streak-soak.md:1`: "# Code-soak streak - the #1 operational objective"; `:10-11` "Protecting capture
  cleanliness outranks all other routine work". `docs/README.md:25` classes it "Canonical runbook". It was
  actively edited in the last 30 days (+303 lines) with the title intact.
- `AGENTS.md:91-93`: a roll in the graded window "can cost a streak day - the #1 operational objective".
- `ESTABLISHED_FINDINGS.md:24-26`: "Contiguity is not the objective (§0d)". §0d (`:194-254`), an operator
  challenge upheld 2026-08-10: both consumers of contiguity are off the critical path, the streak has a 7-day
  shelf life, "Do not treat a broken streak as an emergency, and do not treat 14 contiguous days as an
  achievement."
- `STATE_OF_PLAY.md:9-12`: objectives are capture/settlement evidence, reliable unattended execution, item 330.
- `OPERATIONS_AGENT_ROLE.md:37-44`: capture continuity, then maker profitability, then model adequacy.
- `src/weather/operations/AGENTS.md:29-33` still frames "two independent clocks gate a release".
- Effect: the daily brief leads with "streak 2/14" while the thing §0d says matters (settled, promotion-
  countable date volume) is what is actually bleeding (10 of 14 dates unsettled per lead's live state).

Basis: verified_in_code. Known status: known_open in substance (§0d records the decision) but the
contradiction in AGENTS.md/streak-soak.md is new.

### docs-system-5 (MEDIUM) - Git authority and branch-deletion rules contradict across three canonical files

- `docs/git-workflow.md:19-21`: master "protected ... routine task work and direct pushes do not happen there".
  `:28-31`: "A repository owner approves the merge; a coding agent does not self-authorize it. Publishing a
  branch or pull request still requires authority from the task."
- `OPERATIONS_AGENT_ROLE.md:118-119`: "You have full authority over commits, pushes, merge timing, scheduled
  tasks ... **Commit and push proactively**". `:322-324`: handoffs are committed and pushed straight to
  master ("Read docs/roadmap/<file> on origin/master"). Master history confirms direct doc commits
  (`72a548cdc`, `933182c35`).
- `git-workflow.md:230-238` documents interactive `git push -u origin $branch`; `OPERATIONS_AGENT_ROLE.md:164-167`
  says interactive push "has no credentials" and the only path is the `WeatherOneShotPush` task.
- `git-workflow.md:296-308` prescribes `git worktree remove` + `git branch -d` after merge.
  `DELEGATION_CONTRACT.md:119-120`, `OPERATIONS_AGENT_ROLE.md:64` and `RETRACTED_AND_FALSE_LEADS.md:330-334` say
  "Never delete a branch ... even one declared superseded". The lead reports 382 branches and 200 worktrees;
  contradictory cleanup rules are a sufficient explanation for nobody cleaning up.

Basis: verified_in_code. Known status: new.

### docs-system-6 (MEDIUM) - Onboarding cost: ~4,400 mandatory lines before acting, with heavy duplication

Mandatory pre-read for a production-host model/ops task per `AGENTS.md:6-32`:

| File | Lines |
| --- | ---: |
| `AGENTS.md` | 183 |
| `STATE_OF_PLAY.md` | 73 |
| `OPERATIONS_AGENT_ROLE.md` | 357 |
| `reserved-confirmation-window.md` | 133 |
| `AGENT_CONTEXT.md` | 160 |
| `ESTABLISHED_FINDINGS.md` | 2,754 |
| `RETRACTED_AND_FALSE_LEADS.md` | 381 |
| `DELEGATION_CONTRACT.md` | 283 |
| `docs/README.md` | 93 |
| **Subtotal** | **4,417** |

Add `HOST_LOAD_POLICY.md` (434) before any heavy command, the nearest nested `AGENTS.md` (`scripts/ops/AGENTS.md`
is 240), `docs/roadmap/AGENTS.md` (87), and the owning runbook (`INTERNATIONAL_MM_LIVE_PILOT.md` is ~1,980 lines).
A realistic ops task is 5,000-7,000 lines, on the order of 100k+ tokens, before the first tool call.

Waste inside that budget:
- `reserved-confirmation-window.md`: 133 mandatory lines whose operative content is `:10` "NONE ARE CURRENTLY
  RESERVED" (unchanged since 2026-08-04, and the retrain it arms for is off the critical path).
- `OPERATIONS_AGENT_ROLE.md:203-275`: 70 lines declared "never use this section", yet carrying live decisions.
- The workstation heavy-wrapper contract is pasted near-verbatim into seven files: `AGENTS.md:71-88`,
  `HOST_LOAD_POLICY.md:8-54`, `OPERATIONS_AGENT_ROLE.md:98-112`, `DELEGATION_CONTRACT.md:17-27`,
  `development.md:42-56`, `scripts/ops/AGENTS.md:171-186`, `PORTABLE_LIVE_EXECUTION_HOST.md:40`. This violates
  `docs/AGENTS.md:18` "Put each fact in one canonical file".
- `scripts/ops/AGENTS.md:67-117`: 50 lines of a one-time incident mode bound to commits `3361520f -> c932b54f`
  inside an always-loaded scoped agent file, against `documentation-maintenance.md:155-158` ("Keep it short").
- Canonical docs grew by +5,978 / -457 lines in 30 days (`git diff --stat a76ec7b55 HEAD`), with
  `INTERNATIONAL_MM_LIVE_PILOT.md` +1,756 while "No live trading is authorized" (`STATE_OF_PLAY.md:18-19`).
- Harness gap: there is no `CLAUDE.md` in the repo root (root `ls`). This Claude session's injected project
  context contained only the machine-local `MEMORY.md` index; `AGENTS.md` was not auto-loaded. Claude
  sessions therefore start from a private memory index and Codex sessions from `AGENTS.md`: two different
  entry points into one "canonical" system.

Basis: verified_in_code (line counts from Read), live_state for the session-context observation.
Known status: new.

### docs-system-7 (MEDIUM) - The documentation transaction is expensive and protects form, not truth; its own debt has been open since at least 09-10

- Cost per integration (`documentation-maintenance.md:67-126`): review STATE_OF_PLAY against ancestry, receipts
  and worker evidence; update items; regenerate backlog; run roadmap lint, focused tests, `git diff --check`,
  `agent_docs_audit`; publish; then hand-build a JSON manifest binding the pending SHA-256, ordered integration
  tips, documentation tip, every reviewed document, a durable evidence path, and for unchanged files an exact
  `blob_oid` + `reason`; then run `documentation_transaction complete`, which re-runs four checks including
  pytest (`documentation_transaction.py:303-332`) and requires HEAD == local master == cached origin.
  The pending marker is wired into at least six ops scripts (`integration_attempt_merge.ps1`,
  `integration_attempt_contract.ps1`, `assert_integration_attempt_success.ps1`, `close_integration_attempt.ps1`,
  `boot_recovery.ps1`, plus `quiet_window_merge.ps1` per `scripts/ops/AGENTS.md:63-66`).
- Protection: that two files (`REQUIRED_DISPOSITION_DOCUMENTS`, `:38-43`) got either a diff or a signed
  "unchanged" attestation. The policy says so itself: "These reviews attest prose truth; byte checks cannot
  establish that a factual claim is accurate" (`documentation-maintenance.md:123-125`).
- Not protected: time-based staleness (finding 1), reachability (finding 3), cross-file contradiction
  (findings 4, 5, 8), completeness of FINDINGS/RETRACTED (finding 2). `agent_docs_audit.py:23-84` does not list
  `STATE_OF_PLAY.md`, `ESTABLISHED_FINDINGS.md`, `RETRACTED_AND_FALSE_LEADS.md`, `DELEGATION_CONTRACT.md`,
  `HOST_LOAD_POLICY.md` or `OPERATIONS_AGENT_ROLE.md` in REQUIRED_FILES, CANONICAL_DOCS or UPDATE_TRIGGER_DOCS,
  so the six files AGENTS.md makes mandatory are outside the audit's required/trigger/legacy-command checks.
- Debt: `STATE_OF_PLAY.md:40` (09-13) says the pending record "binds ten actual guarded integrations ... This
  rewrite alone does not clear it." The 09-10 version on the unmerged branch says the same. A control with a
  09:00 next-morning deadline has been in breach for 8+ days; per `documentation-maintenance.md:93-94` that
  means `status.ps1` has been flagging it daily, adding a standing alarm to an already noisy brief.

Basis: verified_in_code for cost and coverage; doc_claimed for the pending state (I did not read
`data/alerts/documentation_transaction_pending.json`). Known status: known_open for the pending debt
(STATE_OF_PLAY records it); new for the cost/coverage assessment.

### docs-system-8 (MEDIUM) - A live-money runbook delegates "operator authorization" and failed-attempt history to a file that no longer contains them

- `INTERNATIONAL_MM_LIVE_PILOT.md:24-27`: "Read the current exact branch tip, exact-head CI/review status,
  operator authorization, and production master baseline from Git and STATE_OF_PLAY.md". `:29-31`: "Failed
  precredential launcher attempts and their exact disposition are recorded in STATE_OF_PLAY.md". `:38-40`
  repeats the delegation.
- Grep of `STATE_OF_PLAY.md` for `precredential|portable|Stage 0|launcher`: **no matches**.
- Mechanism: STATE_OF_PLAY is "REWRITTEN, never appended. Capped at about 90 lines" (`:6-7`). Any durable
  runbook that points at it for a fact loses that fact at the next rewrite. The failure is fail-safe here
  (absence of an authorization record should read as HOLD), but the runbook's statement is currently false
  and the failed-attempt dispositions are now findable only via item 67 or git history.

Basis: verified_in_code. Known status: new.

### docs-system-9 (LOW) - Protected-window end time disagrees across canon, and the "cannot drift" generated file hard-codes it

- 18:00-**00:30**: `AGENTS.md:69-70`, `HOST_LOAD_POLICY.md:326` (Rule 1), `OPERATIONS_AGENT_ROLE.md:76-77`.
- 18:00-**00:05**: `HOST_LOAD_POLICY.md:131` (24-hour map; 00:05-00:30 is a separate unprotected "brief spike"
  row at `:127`), `OPERATING_REFERENCE.md:27`.
- `OPERATING_REFERENCE.md:17-19` claims values are "imported at render time, never copied, so they cannot drift".
  That holds for the governing constants (I verified `collection_health.py:31-34,55` match the cited lines),
  but the protected windows are string literals typed into `operating_reference.py:121-144` (`:138`
  "18:00-00:05 local").
- Enforcement is 00:30: `workload_admission.ps1:1469-1477` refuses the lease outside 00:30-09:00. So leased
  heavy work is safe; the exposure is un-leased ad-hoc reads (the class that has broken production three
  times) started at 00:06 by an agent that trusted `HOST_LOAD_POLICY.md:56-57` ("for the current governing
  numbers, read OPERATING_REFERENCE").

Basis: verified_in_code. Known status: new (example supplied by lead; mechanism traced here).

### docs-system-10 (LOW) - "Dated" correspondence filenames are sequence numbers, now colliding with real dates; the handoff channel has been dormant 38 days

- `git log --diff-filter=A`: `workstation-handoff-2026-09-18a-...` was added **2026-08-05**;
  `workstation-handoff-2026-09-78a-...` (not a calendar date) **2026-08-11**;
  `agent-report-2026-09-02-workstation-estimand-power-and-sign.md` **2026-08-12**. Handoffs run
  `2026-08-03a ... 2026-09-78a` as a counter. `docs/roadmap/AGENTS.md:34-35` admits "a filename may use the
  mission's nominal future date" for handoffs; it says nothing about reports, whose names are also up to three
  weeks ahead of their commit date.
- `docs/AGENTS.md:10-11` classes these as "dated ... historical evidence. Preserve the facts ... true at the
  time". Any agent or script that sorts or filters by filename date gets a false chronology; today's real
  date now matches a file from 08-05.
- The last handoff file was added 2026-08-11. Five later reports (`agent-report-2026-09-07`..`09-11`) have no
  handoff partner (Glob for baseline/archive/reconcil handoffs finds none), against `roadmap/AGENTS.md:38`
  "A handoff and its answering report form a pair". `docs/README.md:69` still says the correspondence "grows
  daily"; only 18 docs files were added on master in the last 30 days. `AGENTS.md:23`, `docs/README.md:69`,
  `ESTABLISHED_FINDINGS.md:5` and `operations/README.md:36` all copy the count "~600" (actual top-level
  handoffs + reports + work orders is roughly 350), against `AGENTS.md:169-170` "not copied counts".

Basis: verified_in_code / git. Known status: known_accepted for handoff naming (documented), new for the rest.

---

## 4. Smaller observations (not in the structured list)

- **README contradiction.** `README.md:459`: "The Operations dashboard can inspect and control the supervised
  loops." `OPERATIONS_DESIGN.md:247-248`: "the dashboard has no recovery controls"; `:254-256` neither page
  "controls host processes". `app/views/` contains only `control_room.py` and `roadmap.py`; grep of `app/` for
  `st.button|restart|subprocess` finds nothing. README is stale here.
- **README / AGENTS test command.** `README.md:107-110` and `AGENTS.md:140-144` present `pytest -q` as the
  canonical check with no adjacent host caveat; `AGENTS.md:113-117` forbids a direct full pytest on the
  production host at every hour. `development.md:35-40` does carry the caveat next to the command. The Codex
  hook is the backstop. Low.
- **README setup is accurate.** `pyproject.toml` has `requires-python >=3.11` and a `test` extra; `requirements.txt`,
  `pytest.ini`, `scripts/launch/start_weather_dashboard.{cmd,ps1,vbs}`, `app/streamlit_app.py`,
  `tools/train_all_markets.ps1` and `docs/research/exchange_economics_snapshot_template.json` all exist.
- **OPEN_BACKLOG.md is dead.** One item (from 2026-08-08), last commit 2026-08-14. Its own rule (`:30-31`): "If an
  item has been here for a month, either it is not real or it is not actually unowned - say which." §8l of
  FINDINGS suggests the item was addressed. Meanwhile the host's actual unowned defects (spent one-shots,
  pending reboot, settlement hole) are not in it. It also cites a Claude memory note by name (`:22`).
- **OVERNIGHT_BRIEFINGS.md**: last entry "Night of 2026-08-10 -> 2026-08-11" (`:19`), yet
  `OPERATIONS_AGENT_ROLE.md:184-186` describes it in the present tense as a daily channel.
- **active-backlog.md** (generated 2026-09-13): 35 "active" items, 32 PARTIAL. About 25 are June/July model-alpha
  items ("SHADOW-ONLY", "BLOCKED") that the standing "no new model-alpha work" decision freezes. As the
  "fastest current-work view" (`docs/README.md:64-65`) its signal-to-noise is roughly 1 in 4. It also embeds a
  render timestamp (`:7`), the exact practice `OPERATING_REFERENCE.md:11-15` rejects for dirtying the tree.
- **OPERATIONS_AGENT_ROLE.md** (last commit 2026-08-29, 20 days) warns at `:10-12` that its predecessor "went
  ten days without a rewrite and ended up asserting three things that were no longer true". It copies volatile
  numbers the docs policy forbids: `:71` alpha ledger "7 of 20" (owned by `CAMPAIGN_LEDGER.md:49`, currently
  consistent), `:140` "3.6M files, 463 GB". `:7` calls `docs/roadmap/AGENTS.md` "the coding contract"; that file
  is the roadmap guide, the coding contract is root `AGENTS.md`.
- **CONTRIBUTING.md:31-32** forbids "local machine paths in a change"; canonical docs contain
  `C:\Users\micha\...` paths, the workstation hostname (`OPERATIONS_AGENT_ROLE.md:314`), and the *location* of a
  credential file (`OPERATIONS_AGENT_ROLE.md:61`, `DELEGATION_CONTRACT.md:100`). Location and type only
  (scraped WU token / sync credential); no value is present in anything I read.
- **HOST_LOAD_POLICY.md** mixes durable policy with expired one-date exceptions (09-08, 09-09, 09-10, 08-23:
  `:83-109`, `:287-322`, `:337-342`), roughly 90 of 434 lines that no longer grant anything. `:432` inside the
  July incident section still reads "Disk headroom is ~6-7 days at current burn".
- **Disk thresholds** appear as ">= 50 GB" (`HOST_LOAD_POLICY.md:333`), "> 60 GB" (training preflight, `:256`)
  and "50 GiB" (`STATE_OF_PLAY.md:24`). I did not find the enforcing constant in `workload_admission.ps1`;
  unverified which unit the code uses.

## 5. Strengths

1. `docs/operations/AGENT_CONTEXT.md` - 160 lines of durable invariants that explicitly exclude metrics,
   versions and priorities (`:11-14`, `:157-159`) and actually keep to it. The model for the rest.
2. `docs/operations/OPERATING_REFERENCE.md` + `src/weather/operations/operating_reference.py` - generated from
   imported constants with source line numbers; I checked five against `collection_health.py:31-34,55` and
   all match. The "derived rules" section (`:29-37`) documents a relationship no grep could find.
3. `src/weather/operations/agent_docs_audit.py` - real, cheap checks: broken local links, README market table
   vs the registry AST, `pyproject`/`requirements` parity, config inventory coverage, legacy command surfaces.
   Result: 0 dead links in my 25-link sample, including three `#anchor` targets.
4. `RETRACTED_AND_FALSE_LEADS.md` (+ `HOW_WE_GET_THINGS_WRONG.md`) - a negative-knowledge record with a fixed
   shape ("what it looked like / what is true / why it fooled us", `:371-380`). Rare and valuable, even though
   it has gone quiet.
5. `docs/operations/DELEGATION_CONTRACT.md` §4-§6 - handoffs must state a falsification section, reports must
   lead with the verdict and list what was *not* done, and handbacks are re-verified against source. Most
   nested agent files (e.g. `src/weather/operations/AGENTS.md`, 48 lines) are short, scoped and end with an
   update trigger.

## 6. What I could not cover

- `data/alerts/*` (MORNING_BRIEFING, OPERATING_SCHEDULE, documentation_transaction_pending.json): not permitted.
  All live-state statements rely on the lead's brief.
- `docs/research/`, `docs/roadmap/audits/`, `docs/roadmap/items/` beyond two existence checks, `ROADMAP.md`,
  `architecture.md`, `PROJECT_OPERATING_SOP.md`, `OPERATIONS_DESIGN.md` (22 lines read), `NIGHTLY_RETRAIN_RUNBOOK.md`,
  `PORTABLE_LIVE_EXECUTION_HOST.md`, `INTEGRATION_ATTEMPT_RUNBOOK.md`, the storage/archive runbooks.
- 13 of 18 nested `AGENTS.md` files; `.github/` PR template and CI docs job; `.claude/` and `.codex/` contents.
- ~1,880 lines of `ESTABLISHED_FINDINGS.md` and most of `RETRACTED` body text were not read line by line;
  claims about their coverage rest on heading maps and targeted greps.
- The ~350 correspondence files were inventoried by name only; none was read.
- Whether branches other than the three newest carry a fresher STATE_OF_PLAY.
- I did not run `agent_docs_audit` or the roadmap lint (forbidden), so "0 dead links" is a sample, not a run.

## 7. Open questions for the owner

1. Should STATE_OF_PLAY have a time trigger (for example: rewrite or re-attest if older than 48 h while
   `status.ps1` is ATTENTION), decoupled from integration success?
2. Is the streak still "#1" anywhere? If §0d stands, `streak-soak.md:1` and `AGENTS.md:92` need to say so.
3. Which rule wins on branches: `git-workflow.md` cleanup or "never delete a branch"? With 382 branches the
   answer has operational weight.
4. Is the Claude auto-memory an accepted second canon? If yes, Codex cannot see it; if no, 15 missions of
   conclusions need a home in `ESTABLISHED_FINDINGS.md` (or that file needs to be split into a short current
   digest plus an archive).
5. Is the documentation transaction worth keeping in its current form, given that it has been pending for
   8+ days and did not prevent any of findings 1-5? A smaller control (freshness age check + reachability +
   the six mandatory files added to `agent_docs_audit`) would cover more for less.
