# Full project audit — weather-market platform

**Audit window:** 2026-09-18 21:30 → 2026-09-19 ~03:30 America/Toronto · **Auditor:** Claude (lead) + 24 dimension
auditors + ~70 adversarial verifiers + completeness critic · **Requested by:** owner ("nothing is off limits; no changes").

Files in this directory:

| File | What it is |
| --- | --- |
| `AUDIT_FINDINGS.md` | this file — consolidated, verified main findings |
| `FINDINGS_INDEX.md` | every finding (all severities) on one line each, with verifier verdicts |
| `dimensions/<key>.md` | the full per-dimension report: scope, method, evidence with `path:line`, strengths, gaps |
| `00_lead_scouting_notes.md` | facts the lead auditor observed directly before the fan-out |
| `IMPLEMENTATION_LOG.md` | what was changed after the audit, under the owner's 09-19 authorization |

---

## 0. Method, and what this audit is NOT

- It ran **on the 16 GB production capture host**, starting inside the protected 18:00–00:30 window. It is therefore a
  **static, read-only audit**: Read/Grep/Glob with explicit sub-paths and a whitelist of bounded `git` reads.
  **Nothing was executed** — no pytest, compileall, python, `.ps1`, or `weather.*` CLI; `data\` was touched only through
  named status files. Every code finding is *read and traced*, none is *reproduced*.
- Concurrency was capped at 6 agents. Host memory was monitored throughout: commit stayed 51–60%, free RAM 7.5–8.3 GB,
  no guard warning. Capture was not disturbed.
- Every critical/high finding was handed to an adversarial verifier told to **refute it by opening the cited files and
  tracing one instance end-to-end**. Critical findings got two verifiers (evidence lens + impact/mitigation lens).
  **Medium and lower findings were NOT independently verified** — treat them as leads.
- Verification mattered: of 62 critical/high claims, **0 were refuted outright, 19 were confirmed as stated, and 43 were
  narrowed** — most of those downgraded to medium. The corrected claims are what appear below.
- `docs/operations/reserved-confirmation-window.md`: no dates are reserved, so no dated evidence was off limits.

### One of my own hypotheses was refuted
I briefed the chain auditor to test whether **low disk causes the settlement hole**. It does not: the Stage-A chain has
no disk floor (`ops-chain-5`). The hole is caused by memory/commit admission and a hair-trigger capture-health
threshold (§2). Recorded here because a wrong causal story would have sent the fix to the wrong place.

---

## 1. What the project is, where it stands, what it has been doing

**Goal (owner's terms).** A better daily-high temperature forecast *from our own information* for 12 city markets that
settle on a weather record; edge over International Polymarket prices follows; the end state is market-making (maker) on
International Polymarket. No live trading is authorized. Standing decisions: no paid weather APIs, International only,
no new model-alpha work for now; current focus is reliability, storage, and the non-live *maker economics refocus*
(item 330).

**What the project's own evidence says.** The model does **not** beat the market; the gap is information/sharpness, not
calibration; one shipped forecast win (serving floor, 07-31) against ~31 retracted claims; no quotable edge in 114–117
pre-registered cells; the primary 09:00–14:00 objective is statistically unmeasurable at achievable N. The research
discipline that produced those negatives is genuinely strong (§8).

**Scale.** ~360k lines of Python (reporting 120k, operations 86k, market 65k, calibration 30k), 413 test files, 73
PowerShell ops scripts (one is 4,092 lines), 881 docs, 382 branches (210 unmerged), 200 git worktrees, 341 enabled
scheduled tasks.

**Recent work (last 30 days, `recent-work`).** 266 commits reached master; ~360 did not. Themes on master are dominated by
cold-archive / storage recovery / qualification-integration machinery / documentation. **Nothing has merged to master
since 2026-09-13 04:09.** Governance scripts and their tests took ~2.4× the lines of all product packages in the period
(`agent-governance-4`, narrowed to medium).

**Live state at audit time** (measured by the lead auditor, 2026-09-19 02:23–02:57):

| | |
| --- | --- |
| Disk C: | **11.21 GiB free at 02:23 → 9.82 GiB at 02:57**, falling ~1.8 GiB/h until the 05:00 tiering job |
| Settlement | 10 of the last 14 dates unsettled (09-04..09-10, 09-13, 09-16, 09-17) |
| Capture | healthy — today CLEAN, 0.0 min max gap, three workers verified |
| Adoption | no code has been adoptable since 09-13; qualification attempts a1..a11 all failed or never ran |
| Streak | 2/14 |

---

## 2. MAIN FINDINGS

Severity shown is **after verification**. `known_open` = the project already records it but it is unresolved; `new` =
not recorded in any canonical doc the auditors could find.

### A. The disk fills in ~2 days, and the recovery machinery is deadlocked by its own floors — CRITICAL

Four auditors reached this independently; both verifier lenses upheld it; the lead auditor re-measured it live.

1. **Real headroom is ~1.5–2.5 days, not "~4 days"** (`storage-capacity-1`, `live-ops-state-1`). `status.ps1:1343-1348`
   divides *current* free space by a same-clock 24 h delta. Free space is a **daily sawtooth**: it bottoms at ~04:50,
   10–13 GiB below the evening reading, then the 05:00 tiering job returns ~13 GiB. Troughs: 29.9 → 25.9 → 14.2 GiB
   (09-15, 09-17, 09-18). The auditors predicted a 09-19 trough of 5.5–8.5 GiB; **the live readings above are on that
   line.** The 09-20 trough projects to ~0–2 GiB.
2. **The only automatic reclaim deadlocks exactly when it is needed** (`storage-capacity-2`). Projection tiering skips a
   file unless `free >= source_bytes + 1 GiB` (`clob_order_book_tiering.py:26,308-328`) although the gzip it writes is
   ~1/23 of the source; raw-tape tiering needs `source + 8 GiB`. No retry; busy lease → exit 0; `StartWhenAvailable`
   forbidden. Below ~2.5 GiB free the host cannot heal itself.
3. **Every other lane refuses at this free space** (`ops-archive-1`, `storage-capacity-4`). Archive stage/transfer/reclaim
   need a 50 GiB reserve (dated 20/25/8 GiB exceptions have all expired); the bounded test suite throws below 50 GiB
   (`bounded_worktree_test_suite.ps1:288-312`), so **no code fix can be qualified or merged either**. Only gzip tiering
   and NTFS compress-and-retain (8 GiB floor, ~2 GB/cold day) remain admissible.
4. **The recovery harness has not completed one clean night** (`live-ops-state-4`, raised to critical by its verifier).
   Nights 09-14..09-17 reclaimed **601 MB against a 150 GB target**; each ended BLOCKED on a harness defect (an unretried
   `Errno 13` on a status read; a 180.7 s heartbeat vs a 180 s bound) while resource admission was PASS. Fail-closed with
   no retry means one transient fault burns a whole night (`ops-archive-3`).
5. **Capture has no disk-full handling** (`storage-capacity-3`). Neither capture writer checks free space; JSONL appends
   are unfsynced `open('a')` writes; status writes are unguarded, so both loops exit on ENOSPC; one torn line makes the
   canonical reader raise for that market-day until repaired by hand, and no repair tool exists.
6. **~62 GiB of the disk is duplicated model pickles in worktrees** (`recent-work-1`, confirmed ×2; **re-measured by the
   lead auditor: 176 of 200 worktrees carry smudged `artifacts/models/hgb/*.pkl`, 62.4 GiB logical**). Every byte is
   already in `.git/lfs/objects`. The development process occupies nearly as much disk as the five-week archive campaign
   freed (79 GB) by moving *irreplaceable originals* to cloud.
7. **A built, merged, fail-safe flag worth ~13 GiB of trough was dismissed on the wrong metric** (`storage-capacity-6`,
   medium, **traced by the lead auditor**). `config/storage_pressure.json: write_order_books_long_csv`. The long CSV is a
   rebuildable projection (`order_book_tape.py:1-7` — raw JSONL is canonical and ranked first by every reader); audits
   use any-of semantics; the policy is re-read on every capture call (`market_microstructure_capture.py:1079`) and fails
   safe. Item 325 rejected it as "~0.7 GB/day retained" — true for the *slope*, but the CSV **is** the ~13 GiB the 05:00
   job hands back each morning, i.e. exactly the trough that is now binding.
8. No recurring retention service exists (`ops-archive-4`); ~50k lines / ~110 commits of archive machinery bought about
   two weeks of runway (`ops-archive-6`, medium). A second disk is the cheapest durable fix and "the host cannot be
   grown" is asserted without a reason (`storage-capacity-8`, medium).

**Consequence.** A full disk stops capture of near-close order-book tape — the one dataset that cannot be backfilled — on
the only host, with the off-host mirror paused since 08-12 (owner-accepted).

### B. The settlement hole is a design property of the chain, not bad luck — HIGH (all confirmed)

- **Single-shot** (`ops-chain-1`): one 09:30 trigger; each isolated step checks admission once; a DEFER raises and breaks
  the loop (`daily_refresh.py:630-683,1460-1462`); the persisted `resume_command` has no consumer; WU restore fetches only
  *yesterday*. Nothing retries, nothing backfills.
- **Settlement sits behind a learning-lane historical audit, and one market's blip defers all 12** (`ops-chain-2`).
  `ingest_quality_gate` precedes WU restore and finalize (`daily_refresh_registry.py:17-21`). Admission uses
  `error_threshold=1`; the snapshot loop increments `consecutive_errors` when *any one* of 12 markets errors in the last
  iteration. The supervisor's own threshold is 3.
- **Proven instance** (`live-ops-state-2`): target 09-06 deferred after 1 of 25 steps — commit 91.4% vs 70%, 1.81 GB
  available vs 3 GB, snapshot loop degraded. Host commit sat at 85–94% from 09-05 to 09-07. The 70–85% commit band is a
  **silent dead zone**: above the chain's ceiling, below the guard's warning (`live-ops-state-6`).
- **Finalize re-revises every historical market-day on every run** (`ops-chain-3`, `data-integrity-2`). The label hash
  includes wall-clock `finalized_at_utc`, so the idempotent early-return can never fire; the idempotency test uses a
  fixed timestamp. Cost is super-linear, folders run oldest-first, and the labels CSV is written only at the end —
  so an 11:55 teardown loses the *new* day after re-stamping the old ones. Recorded 07-28 and 08-11; unfixed.
- No September backfill has been attempted. The hole checker reads only the last 400 ledger lines, so the oldest dates
  may be over-reported (`live-ops-state-10`, low). Six divergent definitions of "settled" exist
  (`error-handling-sweep-2`, medium), and a tape-derived fallback is graded `complete` (`error-handling-sweep-4`).

**Consequence for evaluation** (`eval-validity-3`): unsettled dates silently vanish from every scorecard, and the
evaluation layer's liveness gate uses the settlement ledger as its clock, so a settlement stall reads PASS.

### C. Nothing can be adopted, and master no longer describes production — HIGH (confirmed)

- **The only gate that counts cannot start** (`tests-ci-1`, `agent-governance-1`): the 50 GiB floor is hard-coded, not a
  parameter. Separately, **five** native wrapper test modules build the execution-host id from the *portable* id and so
  fail on the capture host; the repair (PR 61) fixes four and **leaves `test_storage_recovery_night_wrapper.py`
  unrepaired**, so PR 61 may still fail.
- 11 of 19 qualification tasks on 09-13/14 **never ran** (0x41303) yet are labelled "spent one-shot FAILED"
  (`live-ops-state-3`). 0 of 19 real qualifications passed while 18 of 19 *smokes* passed (`agent-governance-2`).
- **The merge queue has stalled** (`recent-work-2`): ~58% of 30-day commits never reached master; none since 09-13.
- **Master ≠ production** (`recent-work-3`, `ops-archive-2`): (i) the code that **deleted ~80.8 GB of canonical
  originals** ran from unmerged branches — master still says 79,105,806,336 bytes / 1,679 files / 85 batches while a
  receipt on disk says 80,816,955,392 / 1,749 / sequence 87, and master still says raw capture is *never* uploaded
  unencrypted while a branch records an owner-approved plain-upload lane; (ii) an owner-authorized **live Stage 0/1
  exchange test on 2026-09-06** (two BUY probes, zero fills) is recorded only on an unmerged branch — master says no
  such protocol has passed; (iii) `WeatherHostHealthWatchdog` and `WeatherBootRecovery` execute from detached linked
  worktrees. The lead auditor counted **41 enabled scheduled tasks whose action points into a linked worktree.**
- The canonical Git SOP still instructs a GitHub-side merge that strands production (`agent-governance-3`, medium).

### D. There is no executable route to a viability decision — HIGH → narrowed to MEDIUM, still the strategic headline

- Item 330 defines continue/redesign/stop, but **only a negative desk outcome is executable**: G2–G4 need live sessions the
  owner has blocked; hurdle H is deferred; G1 has no date; there is no project-level stop date, spend cap, or
  capture-only fallback (`strategy-2`).
- The maker track was closed **NOT_VIABLE** on 07-27; caps are unchanged, and the unmerged 09-11 W3 work again found a
  20-share pair breaches the 10 pUSD ceiling. Canon does record what changed; item 330 does not cite it (`strategy-3`).
- **The cheapest informative maker experiment is unrun** (`strategy-5`, `market-maker-1` confirmed high): the public
  execution tape — the only data that cannot be backfilled, captured since 08-10 — **has no analytical consumer**. The
  paper-fill simulator reads four legacy trade files that nothing writes any more, so paper fills are structurally near
  zero regardless of strategy, and `events_without_trade_rows` is reported but never blocks.
- No component on any branch measures fill probability or post-fill loss; the economics layer is an eligibility screen
  (`market-maker-5`). The paper engine has no inventory state, so no risk cap can bind (`market-maker-4`).
- The ordered critical path in STATE_OF_PLAY is not executable today and contains no storage step (`strategy-1`).

### E. The measuring instrument has moved — HIGH (two independent auditors)

- **Polymarket's declared resolution source changed from Weather Underground to `weather.gov/wrh/timeseries` around
  2026-08-23..26 for all 12 captured markets** (`config-artifacts-1` high; `collection-sources-1`). 103 of 119 active
  events carry the NWS URL, copied verbatim from Gamma `resolutionSource`. `locations.json`, `MarketSpec` and the
  settlement ledger still hard-code WU; the string `wrh/timeseries` has **zero hits** in src/tests/scripts/docs; the
  validator compares Gamma only with Gamma. Same ICAO station, so disagreements are probably rare — but **the label
  impact is unmeasured**, a 1° difference flips a band, and for a maker this is the contract term. *Unverified: whether
  the binding rules text changed too.*
- Evaluators and two trainers silently fall back to a **tape-derived proxy label** when the ledger has no row
  (`eval-validity-2`); with 10 of 14 recent dates unsettled this path is live. The promotion path is unaffected.
- **Served models are ~97 days old**, absolute-bucket classifiers fit on days within ±7 of mid-June (`model-core-3`,
  `config-artifacts-2`). The blend with a serve-date climatology prior means unseen buckets do get mass, so the
  "cannot cover autumn highs" claim is *unverified inference* — but no `classes_`-coverage monitor exists.
- Replay identity on master omits output-changing modules and the enabled `afternoon_residual_centering.json`; the
  version label has been frozen across four serving commits; the fix is unmerged since 08-15 (`model-core-1`).
- A June in-sample per-market **cool shift (up to −1.3 °F) is live 15:00–18:00**, the same direction as the established
  cool bias (`model-core-2`, medium). Production serves `RESEARCH_UNBOUND`: ~300 KB of release-verification code has
  never bound a live process (`model-core-8`). HGB→LR→empirical fallback is silent and unmonitored (`model-core-6`).
- Mandated crossed date×market inference is absent from every decision-bearing evaluator (`eval-validity-1`); the
  leakage audit consumed by gates is a hard-coded constant (`calibration-1`); the replay-fidelity gate passes when it
  cannot measure (`calibration-2`). The gate stack has never gated a real change and its one end-to-end PASS was a label
  leak (`reporting-gates-1`). ~42k lines of gating, zero promotions.

### F. Concrete defects

| ID | Sev | Defect | Status |
| --- | --- | --- | --- |
| `ps-ops-1` | **HIGH, confirmed; runtime proof found by lead auditor** | `memory_commit_guard.ps1:200,205` assigns to `$pid` — PowerShell's constant `$PID`. The kill loop inspects the guard's *own* process, sees a creation-date mismatch, and never reaches `Stop-Process`. Every tree kill (out-of-window agent work, >8 GB trees, the 92% commit offender) is **inert since 2026-08-23**. `memory_commit_guard.log` 2026-09-10 21:29: a 3-member tree "terminated" with the same pid 29288 logged three times. Tests are substring assertions; nothing executes the script. | new |
| `time-units-1` | HIGH→medium (latent) | Eleven band-label parsers use `\d+` and **drop the minus sign**: a "−3 °C" Toronto band is priced as +3. Fires when Toronto lists negative bands (~mid/late November). | new |
| `model-core-4` | medium | A 30 °F plausibility bound will quarantine legitimate winter observations in F markets. | new |
| `ps-ops-3` | medium | The watchdog's settlement-hole escalation is dead code after the status flag text changed. | new |
| `ps-ops-5` | medium | `training_window.ps1`: a status-file write failure skips the capture restore. | new |
| `time-units-2/3` | medium | `captured_at_local` is Toronto time for all 12 markets; the ledger grades each market's "12:00–18:00 local" window in that offset. | new |
| `collection-sources-5` | medium | `forecast_history` backfill overwrites good archives with partial results and exits 0. | new |
| `data-integrity-4` | medium | Raw-tape tiering deletes the only uncompressed canonical tape after verifying a gzip that was never fsynced. | new |
| `data-integrity-1` | medium | Labels CSV is rewritten whole, in place, by three unlocked copies, with no shrink detection. | known_open |
| `tests-ci-5` | medium | The test environment runs the host-global lease tests and by code trace they collide with the production runner. | new |
| `market-live-1` | medium | Execution tape: one market's metadata defect stops capture for all 12. | new |

### G. Security — grade B

No live secret in the tracked tree or its history; wallet secrets are by Credential-Manager reference only; the order
path is single-use, capability-gated and hard-clamped; rclone invocation is injection-safe. Open items:
`C:\Users\micha\Desktop\.env.txt` exists on the production host (1,376 bytes, 08-13; **not opened** — the 08-14
handover calls it "the external credential source"; `security-1`, narrowed to medium pending the owner checking its
contents); no privilege boundary between autonomous agents and the user's secrets (`security-2`); 81 GB of deleted
originals depend on one Google account and self-asserted key custody (`security-3`); SSH password auth / RDP / IIS / no
disk encryption on the production host (`security-4`, known).

### H. Process weight

- The documentation transaction has been open since 08-23 (`agent-governance-5`); mandatory onboarding is ~4,400 lines
  before acting (`docs-system-6`); four canonical files state different objective hierarchies (`docs-system-4`);
  STATE_OF_PLAY is frozen at 09-13 and no tracked doc records 09-14..09-18 (`docs-system-1`).
- "Never delete" rules have accumulated 382 branches, 200 worktrees and ~149 spent-task notes that **bury the three HIGH
  alerts** in the briefing; the alert channel cannot signal a *new* problem (`live-ops-state-5`, `agent-governance-6`).
- Immutable per-attempt namespaces multiplied the cost of apparatus bugs: a1..a11 for what was a test fixture.
- Controls the audit judged **load-bearing — keep**: capture-recovery-gated merge with rollback-before-push (caught two
  real re-adoption defects), `roll_verdict.ps1` closure test, kill-on-close Job containment, the workload lease,
  verify-before-delete, the retractions ledger and alpha ledger.

---

## 3. Dimension grades

| Grade | Dimensions |
| --- | --- |
| **B** | eval-validity · market-live · security · error-handling-sweep |
| **C** | model-core · calibration · reporting-gates · reporting-rest · collection-sources · market-maker · ps-ops · docs-system · tests-ci · architecture · config-artifacts · data-integrity · time-units |
| **D** | strategy · recent-work · ops-chain · ops-archive · storage-capacity · live-ops-state · agent-governance |

The pattern: **the science and the safety engineering grade well; operations, capacity and strategy grade poorly.**

## 4. Strengths (genuine, with paths in the dimension reports)

- Research honesty: hash-bound pre-registration, a binding alpha ledger that has refused spends, a quantified
  retractions ledger, a 117-cell Holm-adjusted negative result defended with power screens.
- Leakage controls in code: rolling-origin folds with embargo, `feature_available_at <= prediction_made_at` per row.
- Evidence engineering: content-addressed payload stores (stage → fsync → hard-link → re-verify); append-only,
  fsynced, hash-chained settlement ledger; execution-tape store with gap accounting.
- Delete-after-verify is careful: exclusive handle, hash through that handle, delete by handle, intent journaled first.
- Live-money safety design: non-raisable caps, post-only, attended sessions, credentials by reference, SDK tree-hash pin.
- Process containment is real: suspended-start kill-on-close Job Objects with memory/timeout ceilings and receipts.
- Capture itself is healthy and self-healing; tiering has reclaimed 9–15 GB on twelve consecutive mornings.
- `settlement_backfill_one.ps1` verifies **outcome, not exit code** — the model the rest of ops should follow.

## 5. Recommended order of action

1. **Disk, today.** (a) Replace the 62 GiB of duplicate pickles in linked worktrees with LFS pointers (reversible,
   git-clean, offline-restorable; script prepared — *needs owner go-ahead, see IMPLEMENTATION_LOG*). (b) Flip
   `write_order_books_long_csv=false`. (c) Make status report the trough, not the instantaneous reading. Together these
   restore >50 GiB and reopen every gated lane without touching one byte of evidence.
2. **Fix the memory guard** (`$pid`) — the documented #1 cause of capture gaps has had no working backstop for 27 days.
3. **Settlement:** backfill the 10 dates once disk allows; then move WU restore + finalize ahead of the learning-lane
   gate, add bounded in-window re-admission, align the health threshold with the supervisor's, and make finalize
   idempotent (drop `finalized_at` from the label hash; newest-first; only folders lacking a settled current revision).
4. **Measure the WU-vs-NWS label disagreement since 08-23** and add a validator rule comparing the live declared
   resolution source with the durable settlement source.
5. **Reconcile master with production** in a docs-only change: the 09-06 live test, the true archive counter, the plain
   upload lane, and a register of every scheduled task that executes from a non-master checkout.
6. **Owner decisions:** kill criteria / hurdle / date for G1; whether the 50 GiB floor should be a host-policy parameter;
   whether destructive lanes may run from unmerged code; a second disk; the contents of `Desktop\.env.txt`.
7. **Run the execution-tape markout study** on the workstation with a pre-registered kill threshold — the cheapest
   experiment that can move the viability question.
8. Before November: one signed, range-aware band parser; winter plausibility bound.

---

## 6. GAP ROUND — what the completeness critic found missing (6 further auditors, all critical/high verified)

The critic's assessment: code coverage was broad and the auditors agreed on the big picture, but most live-state claims
were inferred, three contradictions needed tie-breaks, and the largest substantive hole was the settlement truth source.

### 6.1 The 2026-09-06 live test: a geoblock record that no tracked document mentions — HIGH (confirmed by BOTH verifiers)
`gap-live-lane-truth-and-eligibility-1`. Real-money trading **did** happen: on 09-06 an owner-attended International
Stage 0/1 test ran from the 32 GB portable PC on unmerged branch code — nine attempt namespaces, three real 0.005 pUSD
post-only BUYs, cancelled, zero fills. It was a one-day exception between the 09-04 "no live trading" instruction and its
09-10/11/13 restatements; nothing is authorized today.

Untracked receipts under `scratch/handoffs/live-test-preparation-20260906/` show `polymarket.com/api/geoblock` returned
**blocked=true CA/ON** at 13:18:31Z and again at 18:21:49Z (sealed Stage 0 FAIL `OFFICIAL_LOCATION_BLOCKED`, with the
operator attestation "physically eligible" set true), then **blocked=false MX/QUE 4m45s and 2m36s later** on the same
host and principal ids. The retry note reads "owner reports that the Ontario location attribution was mistaken and the
infrastructure was moved". Orders followed.

Verifier caveats, kept: *VPN use is not proven*; the 13:xx diagnostics carry no host ids; the venue's current Ontario
text was unverifiable offline. But `mm_geographic_eligibility.py:396-410` trusts only the endpoint's `blocked` flag plus
caller-supplied booleans and never evaluates country or region; `live_path_security.py:679-720` cannot see a VPN
adapter; and `INTERNATIONAL_MM_LIVE_PILOT.md:59-60` says an unblocked egress that disagrees with physical location "is
not authority". The item-67 narrative on PR 37 skips the geo-failed attempt.

**Why it matters strategically:** if the operator is in Ontario, the maker end goal on International Polymarket may be
unreachable regardless of economics. That is a first-order viability input and belongs in item 330 before any more
W3–W7 work. The only evidence sits in an ignored, un-backed-up directory.

Related (medium): five live-money controls were relaxed between failed attempts that day; no closing balance or
post-test account record exists and wallet cash moved 214 pUSD unexplained; no ToS/licence register exists; the Desktop
`.env.txt` is **not** the file deleted on 09-06, so `security-1` stands.

### 6.2 The settlement hole's deeper root: the commit limit shrank to 22 GB — HIGH (partially confirmed)
`gap-chain-deferral-evidence-and-memory-root-cause`. Only **2 of the 10** unsettled dates have a provable cause, because
the chain's status file is overwritten daily. 09-17 is proved: deferred at `ingest_quality_gate`, sole blocker **host
commit 72.5% vs 70%, with 6.4 GiB RAM free and every loop healthy**. 09-16 restored WU 12/12 and then stopped before
finalize.

The "raised memory baseline" is mostly a **shrunken denominator**: the live commit limit is **22.0 GB**, against the
63.7 GB the policy documents (37.05 → 34.51 GB was already recorded on 08-13). Used commit actually *fell* (16.9 GB at
49% on 08-13; 11.8 GB at 53.7% now). The 70% gate therefore trips at 15.4 GB, leaving ~3.6 GB of idle headroom — less
than two permitted capture children. A dynamic pagefile on a nearly-full system volume is the likely mechanism (*not
proven; the pagefile setting was not read*). **So low disk plausibly does cause the settlement hole after all —
indirectly, through the pagefile** — a better explanation than the one I originally briefed and the auditors refuted.

No admission receipt stores `commit_used`/`commit_limit` bytes, the guard retains no consumer attribution below 85%, and
the settlement-hole alarm **expires dates after 14 days: 2026-09-04 has already vanished unsettled**. Good news: **all
10 dates are recoverable now** (~22 min each); 09-16 needs finalize only. Smallest fix: a bounded admission wait plus a
WU look-back range.

### 6.3 Settlement truth source, measured — downgraded to MEDIUM
`gap-settlement-truth-source`. The venue's declared source moved from wunderground to `weather.gov/wrh/timeseries` with
the 2026-08-23 event (verified in git for Atlanta and Toronto); same ICAO stations. **Agreement at band level: 921/921
before the switch, 131/132 after** (Miami 09-02: WU 89 °F vs venue 90–91 °F — the floor-safe direction). Exact-degree
agreement for the 11 °F markets is unmeasured. Production callers do enable venue reconciliation and promotion
countability requires `match`. Still open: master hard-codes WU and no gate can detect a source change; the venue's
Rules text is retained nowhere; serving-floor safety is checked WU-against-WU; and **all 168 "unsettled" market-days
already hold the venue's winning band on disk** while policy forbids using it and no doc separates economic truth from
training truth.

### 6.4 What production actually serves — grade D (code-only; no served output was read)
Live WU inputs have been hard-disabled since 2026-06-30. The project repaired the *feature* consequence but never the
*post-processing* one: **13 of ~26 serving stages — including all five late-day lock-ins and the calibration taper —
are silent no-ops** (confirmed, medium). A June-fitted 15:00–18:00 offset is live against the project's own rule, with a
known-failing test. No alert-path monitor sees source, NaN-feature or model-kind degradation, and the one source summary
treats empty payloads as fresh. `forecast_high` is a different estimator at serve than at train and the parity gate does
not check it.

### 6.5 Off-master inventory — the real bottleneck is LANDING, not authoring
**406 non-merge commits sit off master** in four large stacks, nearly all roll-sensitive because every new schema edits
`schema_registry*`, which is inside the snapshot loop's import closure. **Two prior audits produced 32 numbered items;
3 are substantially on master**, and the 09-05 audit itself is not on master. The 08-11 audit headline ("no more
qualification machinery") was contradicted: 1 of 402 subsequent master commits touched model/calibration, 186 touched
ops, plus a +20k-line qualification stack. Fixes that already exist and are stranded: the **sign-blind band parser fix
(tested, 09-05, third in the queue)** and the **snapshot hang-detection fix (local-only, 36 days)**. The production
host cannot be rebuilt from origin: ~7 tasks have no registrar, the push task is hash/SID-pinned, pickles are LFS-only,
no lock file, no runbook. **This audit will meet the same fate unless the landing path is reopened first.**

### 6.6 Disk tie-break
Full census: **175 of 200 worktrees hold smudged pickles, 371,560 KiB each (link count 1), 62.0 GiB.** `recent-work-1`
was right (overstated ~12%); two other auditors were low by ~6× because they priced tracked content only. Un-smudging
beats removal: ~61 GiB, ~4,700 file operations, reversible from local `.git/lfs`, no branch or untracked file touched.
The differing free-space figures in this audit (21, 18.5, 14.2, 11.3) are one instrument at different sawtooth phases.

---

## 7. A finding the audit produced by accident — and a disclosure

**`tests/operations/test_status_script.py` wrote 550.8 MiB of real disk per test.** Its reconciliation fixture did
`git init --bare` and then **pushed the project's whole history (a 1,010 MB pack) into a fresh bare origin for every
test**; pytest retains the newest three run directories. One run of that module is tens of GiB.

I found this the hard way. While verifying my `status.ps1` change I ran that module twice (one run hit my timeout, one I
stopped). **Those two interrupted runs took C: from 20.6 GiB to 7.1 GiB free in about fifteen minutes**, in the
pre-trough window. My monitor caught it; I stopped the run, confirmed no orphan processes, and deleted my own temp
directories (**18.66 GiB freed; C: back to 25.7 GiB**). Capture was not affected (commit ≤ 60%, no admission failure),
but it was a real near-miss and entirely my doing.

It also explains two mysteries: the unexplained +11 GiB at 03:04 (pytest pruned someone's older debris when my first
small run started) and, very likely, **why the qualification suite needs a 50 GiB floor at all**.

Fixed on `claude/audit-rollfree-fixes-20260919`: the bare origin now borrows objects through git alternates and its ref
is seeded directly. **Measured: 56.7 MiB per test (was 550.8), 5.2 s (was 19 s).** Nobody should run that module on the
capture host from master until that lands.

**Disclosure on sequencing:** the owner authorized implementation at ~02:20 while verification was still running. Two
gap auditors correctly noticed a fix branch advancing during a "no changes" audit. No file on master or in the
production working tree was modified; all work is on two new branches in two new pointer-only worktrees.
