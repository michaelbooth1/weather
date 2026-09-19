# Findings index - every finding, all severities (30 auditors: 24 dimensions + 6 gap)

Columns: severity, id, known_status, basis, [verifier verdicts: e=evidence lens, i=impact lens -> corrected severity], title.
Medium/low/info findings were NOT independently verified. Full text: dimensions/<key>.md

```
CRITICAL strategy-1               new            verified_in_code [e:partially_confirmed->high,i:partially_confirmed->high] Ordered critical path is not executable in the current live state and omits storage
CRITICAL recent-work-1            new            live_state       [e:confirmed->high,i:confirmed->high] About 70 GiB of duplicated LFS model pickles sit in 199 worktrees on a disk about 4 days from full
CRITICAL ops-archive-1            known_open     verified_in_code [e:partially_confirmed->high,i:partially_confirmed->high] Capacity deadlock: every delete-capable and merge-capable lane is inadmissible at current free space, and the dated recovery approvals have expired
CRITICAL storage-capacity-1       new            live_state       [e:partially_confirmed->high,i:partially_confirmed->critical] Real disk headroom is about 1.5-2.5 days, not ~4: the monitor ignores a 13-16 GiB daily sawtooth
CRITICAL storage-capacity-2       new            verified_in_code [e:partially_confirmed->high,i:partially_confirmed->high] The only automatic reclaim deadlocks at low disk, has no retry, and a blocked 05:00 run blocks the 06:00 run
CRITICAL live-ops-state-1         known_open     live_state       [e:confirmed->critical,i:partially_confirmed->high] Disk headroom is about 1-2 days at the daily trough, not the reported 3 days, and tiering stops working before zero
CRITICAL gap-live-lane-truth-and-eligibility-1 new            live_state       [e:confirmed->high,i:confirmed->high] Venue geoblock returned blocked CA/ON on the execution PC twice on test day, flipped to MX/QUE within minutes, real orders followed; no tracked doc records it
CRITICAL gap-disk-reclaim-tiebreak-1 new            live_state       [i:partially_confirmed->high,e:partially_confirmed->high] 62.0 GiB of duplicate smudged LFS model pickles sit in 175 of 200 linked worktrees (full census)
HIGH     model-core-1             known_open     verified_in_code [e:confirmed->high] Replay identity on master hashes the disk at capture time, omits output-changing modules/artifacts, and the version label is frozen; fix unmerged since 08-15
HIGH     model-core-2             new            verified_in_code [e:partially_confirmed->medium] A stale, in-sample-fitted per-market COOL shift is live in serving 15:00-18:00, in the direction of the established cool bias
HIGH     model-core-3             known_open     verified_in_code [e:partially_confirmed->high] Served base HGBs are absolute-bucket classifiers fitted to prior-year days within +/-7 days of mid-June, three months out of season with the retrain blocked
HIGH     eval-validity-1          known_open     verified_in_code [e:confirmed->medium] Mandated crossed date x market inference is absent from every decision-bearing evaluator; the production verifier hard-codes date-only clustering
HIGH     eval-validity-2          new            verified_in_code [e:partially_confirmed->medium] Evaluators and calibration trainers silently fall back to a tape-derived proxy label when the settlement ledger has no row
HIGH     eval-validity-3          known_open     verified_in_code [e:partially_confirmed->medium] Unsettled dates vanish from the evidence base and the evaluation layer's liveness gate is structurally unable to see it
HIGH     reporting-gates-1        known_open     verified_in_code [e:partially_confirmed->medium] The gate stack has never gated a real change, and its one end-to-end PASS was a label leak
HIGH     reporting-gates-2        new            verified_in_code [e:partially_confirmed->medium] promotion_readiness is report-only because the permission-granting allowlist is built before it and ignores it
HIGH     calibration-1            new            verified_in_code [e:partially_confirmed->medium] The leakage audit is a hard-coded constant, consumed by gates and reports as a verdict
HIGH     calibration-2            new            verified_in_code [e:partially_confirmed->medium] Replay fidelity gate passes when it cannot measure and gates only the same-identity subset
HIGH     strategy-2               new            verified_in_code [e:partially_confirmed->medium] No executable route to a viability decision, and no kill criteria or hurdle
HIGH     strategy-3               new            verified_in_code [e:partially_confirmed->medium] Refocus re-walks a maker track already closed NOT_VIABLE, under an unchanged risk envelope
HIGH     strategy-4               new            verified_in_code [e:confirmed->medium] Canon is forked: master omits the first live exchange orders and the own-information challenger result
HIGH     strategy-5               new            verified_in_code [e:partially_confirmed->medium] Cheapest decisive maker experiment not run: public execution tape has no analytical consumer
HIGH     recent-work-2            known_open     verified_in_code [e:confirmed->high] The merge queue has stalled: 58% of the last 30 days' commits never reached master, none since 09-13
HIGH     recent-work-3            new            verified_in_code [e:confirmed->high] Master no longer describes production: a real-order live test, the archive reclaim code and the deployed watchdog exist only on unmerged branches
HIGH     recent-work-4            known_open     verified_in_code [e:partially_confirmed->medium] Small product-critical fixes stranded 17-38 days while roughly 700 commits of machinery landed
HIGH     recent-work-5            new            verified_in_code [e:partially_confirmed->medium] Effort allocation does not match the stated objectives; machinery is compounding
HIGH     collection-sources-1     new            verified_in_code [e:partially_confirmed->medium] Live Polymarket metadata names NWS timeseries, not Weather Underground, as resolution source for all 12 core markets; project still assumes WU
HIGH     collection-sources-2     new            verified_in_code [e:partially_confirmed->medium] Settling one day rebuilds all WU history for every market, outside per-market failure isolation
HIGH     collection-sources-3     new            verified_in_code [e:partially_confirmed->medium] Snapshot JSONL appends are not torn-write safe, damage is uncounted, and capture never checks free disk
HIGH     ops-chain-1              known_open     verified_in_code [e:confirmed->high] Settlement chain is single-shot: one failed admission check loses the day and nothing retries or backfills
HIGH     ops-chain-2              new            verified_in_code [e:confirmed->high] Settlement runs behind a hard-stop historical audit, and one market's capture error defers all 12 markets
HIGH     ops-chain-3              known_open     verified_in_code [e:confirmed->high] Finalize re-revises every historical market-day on every run; super-linear cost inside a 145-minute kill window, newest day last
HIGH     reporting-rest-1         new            verified_in_code [e:partially_confirmed->medium] Progress ledger re-runs, unbudgeted in the orchestrator parent, the whole-corpus replays that were deliberately removed from the budgeted fleet child
HIGH     reporting-rest-2         new            verified_in_code [e:partially_confirmed->medium] The fleet-observability CLI advertised as the verification/remediation command has no bounded mode
HIGH     market-maker-1           new            verified_in_code [e:confirmed->high] Paper fill simulator is not connected to the continuous public execution tape
HIGH     market-maker-2           known_open     verified_in_code [e:partially_confirmed->medium] Scheduled maker roll runs a lane that cannot quote; the lane that can quote is unscheduled and cannot be reward-eligible
HIGH     market-maker-3           known_open     verified_in_code [e:partially_confirmed->medium] Item 330 economics code and two production-relevant fixes are stranded on an unadopted branch
HIGH     ops-archive-2            new            live_state       [e:confirmed->high] The code that deleted ~80.8 GB of canonical originals is not on master; master's state docs are contradicted by receipts on this disk
HIGH     ops-archive-3            new            live_state       [e:partially_confirmed->high] Fail-closed with no retry lets one small defect burn a whole recovery night; two consecutive nights reclaimed zero bytes
HIGH     ops-archive-4            known_open     verified_in_code [e:partially_confirmed->high] No recurring retention service exists; structural inflow is unaddressed and the disk emergency recurs every one to three weeks
HIGH     ps-ops-1                 new            verified_in_code [e:confirmed->high] Memory guard tree termination is inert: assignment to constant $PID
HIGH     ps-ops-2                 known_open     verified_in_code [e:partially_confirmed->medium] Hard-coded 50 GiB disk floor closes the integration-attempt merge path at current free space
HIGH     security-1               new            live_state       [e:partially_confirmed->medium] Wallet-credential source file sits on the production host Desktop
HIGH     storage-capacity-3       new            verified_in_code [e:partially_confirmed->high] Capture has no disk-full handling: ENOSPC truncates canonical tape, the canonical reader then fails closed, and both loops exit
HIGH     storage-capacity-4       known_open     verified_in_code [e:partially_confirmed->high] Every manual recovery lane is inadmissible at today's free space, nothing else is armed, and the plan cannot outrun 6-8 GiB/day
HIGH     storage-capacity-5       new            inferred         [e:partially_confirmed->medium] The pagefile is dynamic and on the same volume: commit spikes eat disk, and at zero free the commit limit freezes
HIGH     live-ops-state-2         known_open     verified_in_code [e:partially_confirmed->high] Settlement hole: one admission attempt per day, a learning-lane step gates finalize, and no September backfill has been attempted
HIGH     live-ops-state-3         known_open     verified_in_code [e:partially_confirmed->high] Qualification is a structural deadlock; most 'FAILED' a1..a11 tasks never ran
HIGH     live-ops-state-4         known_open     live_state       [e:confirmed->critical] Storage-recovery nights 09-14..09-17 failed on harness defects, not host resources, and recovered 0.6 GB against a 150 GB target
HIGH     live-ops-state-5         new            verified_in_code [e:partially_confirmed->medium] Alert channel cannot signal a new or worsening problem; its only escalation path is dead code
HIGH     docs-system-1            new            verified_in_code [e:partially_confirmed->medium] STATE_OF_PLAY is frozen at 09-13 and no tracked document records 09-14..09-18
HIGH     tests-ci-1               known_open     verified_in_code [e:confirmed->high] The production-host bounded suite, the only gate that counts, cannot currently start and master cannot pass it
HIGH     tests-ci-2               known_open     verified_in_code [e:partially_confirmed->medium] Master CI is Ubuntu-only: no PowerShell is parsed or run, about 321 tests skip, and Windows workflows exist only on an unmerged branch
HIGH     tests-ci-3               known_open     verified_in_code [e:partially_confirmed->medium] PowerShell ops scripts are tested mainly by substring assertions; critical-path scripts have zero executing tests
HIGH     architecture-1           known_open     verified_in_code [e:partially_confirmed->medium] Central schema registry is inside every capture loop's code identity, so most feature merges restart production capture
HIGH     architecture-2           new            verified_in_code [e:partially_confirmed->medium] Codebase is out of proportion to the product; the excess is meta-machinery and unauthorized live-trading code
HIGH     error-handling-sweep-1   new            verified_in_code [e:partially_confirmed->medium] Daily chain failure channel is saturated: critical, deferred, interrupted and a deadline kill all read as 'expected'
HIGH     error-handling-sweep-2   new            verified_in_code [e:partially_confirmed->medium] Six divergent definitions of 'settled'; freshness gate and its repair command pass on a row that holds nothing
HIGH     error-handling-sweep-3   known_open     verified_in_code [e:partially_confirmed->medium] Settlement is all-or-nothing across 12 markets with no self-heal; poisoned-date skip is unexplained
HIGH     config-artifacts-1       new            verified_in_code [e:partially_confirmed->high] Markets' declared resolution source moved from Weather Underground to weather.gov timeseries on the 2026-08-23 event; project still assumes WU and cannot detect the change
HIGH     config-artifacts-2       known_open     verified_in_code [e:partially_confirmed->medium] Served models are ~97 days old, fitted on a May10-Jun30 archive; Toronto probability calibration was fit on four target dates
HIGH     config-artifacts-3       known_open     verified_in_code [e:partially_confirmed->medium] Runtime identity cannot attest served bytes: git_dirty hard-coded None, config and artifacts outside the fingerprint, unknown reported as clean
HIGH     data-integrity-1         known_open     verified_in_code [e:partially_confirmed->medium] Labels CSV is rewritten whole, in place, from whatever folders were discovered, by three unlocked copies, with no shrink detection
HIGH     data-integrity-2         known_open     verified_in_code [e:confirmed->medium] Ledger idempotency is defeated by a timestamp inside the hashed payload: every chain run appends a revision per historical market-day and re-reads the whole ledger per upsert
HIGH     agent-governance-1       known_open     verified_in_code [e:partially_confirmed->high] The mandated unattended adoption path has ~0% recent success and cannot pass at today's disk level
HIGH     agent-governance-2       known_open     live_state       [e:partially_confirmed->medium] Immutable attempt namespaces multiplied the cost of apparatus bugs: 0 of 19 real qualification tasks passed while 18 of 19 smokes passed
HIGH     agent-governance-3       new            verified_in_code [e:partially_confirmed->medium] A GitHub-side merge strands production, and the canonical Git SOP still instructs one
HIGH     agent-governance-4       new            verified_in_code [e:partially_confirmed->medium] Effort has shifted to governing the work: governance scripts and tests took 2.4x the lines of all product packages in 30 days
HIGH     time-units-1             new            verified_in_code [e:partially_confirmed->medium] Band-label parsers drop the minus sign; Toronto's winter ladder will be mis-parsed on the tape, in the ledger and in CLOB metadata
HIGH     gap-settlement-truth-source-1 new            verified_in_code [e:partially_confirmed->medium] Venue changed its declared resolution source on 2026-08-23; master still hard-codes WU and no gate can detect such a change
HIGH     gap-live-lane-truth-and-eligibility-2 new            verified_in_code [e:partially_confirmed->medium] master is false by omission about real-money trading; the complete record lives only on unmerged branches and unbacked scratch
HIGH     gap-live-lane-truth-and-eligibility-3 new            live_state       [e:partially_confirmed->medium] Credential residue: whole-personal-wallet signing key probably in two Windows vaults plus an unexplained Desktop file; no rotation or decommission procedure
HIGH     gap-chain-deferral-evidence-and-memory-root-cause-1 new            live_state       [e:partially_confirmed->high] The 70% commit gate runs against a commit limit that has fallen to 22.0 GB from the documented 63.7 GB; nothing records or monitors the limit
HIGH     gap-chain-deferral-evidence-and-memory-root-cause-2 known_open     verified_in_code [e:partially_confirmed->high] Settlement deferral is sampled once, never retried, holes never self-heal, and no recovery has been attempted for any of the 10 dates
HIGH     gap-chain-deferral-evidence-and-memory-root-cause-3 new            verified_in_code [e:partially_confirmed->medium] The settlement-hole alarm expires unsettled dates after 14 days; 2026-09-04 has already vanished without being settled
HIGH     gap-chain-deferral-evidence-and-memory-root-cause-4 new            verified_in_code [e:confirmed->high] Memory guard tree termination cannot succeed: it assigns to PowerShell's constant $PID, and its tests only assert strings
HIGH     gap-what-production-serves-1 new            verified_in_code [e:confirmed->medium] Thirteen serving stages keyed on WU history have been silent no-ops since 2026-06-30
HIGH     gap-what-production-serves-2 new            verified_in_code [e:partially_confirmed->medium] No served-input liveness alarm; the only source summary calls empty payloads fresh
HIGH     gap-what-production-serves-3 new            verified_in_code [e:partially_confirmed->medium] A June-fitted 15:00-18:00 serving-side temperature offset is live, against the project's own rule
HIGH     gap-off-master-inventory-1 known_open     live_state       [e:partially_confirmed->high] The landing path is stalled; every written fix queues behind a gate that cannot currently pass
HIGH     gap-off-master-inventory-2 new            live_state       [e:partially_confirmed->medium] Production is not master: deployed watchdog, the 79 GB reclaim and one-shot capacity tasks all ran from unmerged commits
HIGH     gap-off-master-inventory-3 new            verified_in_code [e:partially_confirmed->medium] Follow-through scorecard: 32 numbered items across two prior audits, 3 substantially on master; the 08-11 headline was contradicted
HIGH     gap-off-master-inventory-4 known_open     verified_in_code [e:confirmed->high] Sign-blind band parsing is still on master at four sites; the tested fix from 09-05 is third in a stalled queue
HIGH     gap-off-master-inventory-5 known_open     verified_in_code [e:confirmed->high] The snapshot hang-detection fix has been local-only and unmerged for 36 days while master documents the defect it fixes
HIGH     gap-disk-reclaim-tiebreak-2 new            verified_in_code [e:partially_confirmed->medium] New worktrees still smudge 363 MiB by default; the capacity-recovery effort itself consumed about 9.9 GiB this way
MEDIUM   model-core-4             new            verified_in_code 30 F plausibility bound will quarantine legitimate winter observations in F markets; training never applies the same gate
MEDIUM   model-core-5             new            verified_in_code Celsius-tuned constants are applied per bucket in Fahrenheit markets without scale_delta, while neighbouring thresholds are scaled
MEDIUM   model-core-6             new            verified_in_code HGB -> LR -> empirical fallback is silent, the live pickle load is unverified, and no ops check watches the model kind
MEDIUM   model-core-7             known_open     verified_in_code Train and serve build features through two implementations guarded by one happy-path parity case
MEDIUM   model-core-8             known_accepted verified_in_code Production serves RESEARCH_UNBOUND; roughly 300 KB of release verification code has never bound a live process
MEDIUM   eval-validity-4          known_open     verified_in_code Promotion, hourly and replay-regression gates still decide on bare point estimates
MEDIUM   eval-validity-5          new            verified_in_code Mismatched denominators survive in three model-versus-market comparisons
MEDIUM   eval-validity-6          new            verified_in_code Pre-registration is partly enforced in code; alpha spending is documentation only
MEDIUM   reporting-gates-3        new            verified_in_code The runtime-identity gate cannot pass except through an unverified hand-written three-field JSON
MEDIUM   reporting-gates-4        new            verified_in_code The production-readiness SHADOW stage requires evidence the owner has switched off
MEDIUM   reporting-gates-5        known_open     verified_in_code The row-export candidate path reports gate fields that are constants or declarations, not computed
MEDIUM   reporting-gates-6        new            verified_in_code Several gates cannot realistically pass: WARN collapses to BLOCK and thresholds sit far below measured noise
MEDIUM   reporting-gates-7        new            verified_in_code Scoring liveness uses the settlement ledger as its clock, so a settlement stall reads PASS
MEDIUM   reporting-gates-8        new            verified_in_code The gauntlet's replay-fidelity canary passes on an empty input, and no caller enables the strict mode
MEDIUM   calibration-3            new            verified_in_code Served probability-calibration artifacts: in-sample fit on 6 dates, mismatched objective, and a self-score worse than identity that nothing gates on
MEDIUM   calibration-4            new            verified_in_code Candidate replay normalises over surviving bands only; live normalises over the full partition; default gamma 1.25 is a global sharpening
MEDIUM   calibration-5            new            verified_in_code Per-market blend weights are hard-coded from replay outcomes, re-scored on the same corpus, and a zero weight passes the per-market gate trivially
MEDIUM   calibration-6            known_open     verified_in_code Gate statistics ignore the project's clustering rules: 'held-out days' counts market-days, thresholds have no intervals, no crossed clustering exists in the package
MEDIUM   calibration-7            new            verified_in_code Serving-critical calibration functions exist in two copies with no parity test; training and serving use different copies
MEDIUM   calibration-8            new            verified_in_code Metric definitions are fragmented, so headline numbers from different modules are not comparable
MEDIUM   strategy-6               new            verified_in_code Goal hierarchy is incoherent across canonical docs; 'model-alpha' is ambiguous
MEDIUM   strategy-7               known_open     verified_in_code Headline meter is still the streak; the confirmation-panel clock has no counter and is being starved
MEDIUM   strategy-8               known_open     verified_in_code Effort allocation contradicts the refocus: process and storage work dominates, simplification not started
MEDIUM   strategy-9               known_accepted doc_claimed      Strategy-level single points of failure: host, disk, operator, key custody, venue eligibility
MEDIUM   recent-work-6            new            inferred         The development process is a measured consumer of the resources whose shortage trips the production gates
MEDIUM   recent-work-7            new            verified_in_code Research results orphaned on unmerged branches again, including a spent terminal evaluation
MEDIUM   collection-sources-4     known_accepted verified_in_code WU settlement data comes from a single-point scrape of WU's own web API key; page drift is mislabelled transient
MEDIUM   collection-sources-5     new            verified_in_code forecast_history backfill overwrites good archives with partial results and exits 0
MEDIUM   collection-sources-6     new            verified_in_code The first WU fetch of a date is frozen forever and there is no completeness test
MEDIUM   ops-chain-4              new            verified_in_code Monitoring words a Stage-A settlement deferral as benign and whitelists its exit codes
MEDIUM   ops-chain-5              new            verified_in_code Low-disk hypothesis refuted; the chain has no disk floor and its settlement writes are non-atomic
MEDIUM   ops-chain-6              known_open     verified_in_code Bounded recovery reports PASS and exit 0 when WU restore blocked and nothing settled
MEDIUM   ops-chain-7              known_open     verified_in_code Labels-CSV truncation remains on the success path for any subset finalize
MEDIUM   ops-chain-8              known_open     verified_in_code One market's WU failure still blocks label finalization for all 12 markets
MEDIUM   reporting-rest-3         new            verified_in_code june23_location_bias_repair 'repair replay' cannot fail, runs daily on a frozen date, and was accepted as roadmap completion evidence
MEDIUM   reporting-rest-4         new            verified_in_code rollup_freshness is stage-unaware, forcing a structural BLOCK and 'critical' on clean Stage A runs; the project's triage misattributes it to the model gap
MEDIUM   reporting-rest-5         new            verified_in_code With Stage B held disabled the daily rollup stack does not run, and the progress ledger re-stamps stale Stage-B values as today's
MEDIUM   reporting-rest-6         known_open     verified_in_code Market-beating scoreboard requires two inputs no automated step produces and never checks input age
MEDIUM   reporting-rest-7         new            verified_in_code Stage A re-scores the whole settled corpus from raw tapes in separate hourly and ten-minute passes with no cache or increment
MEDIUM   reporting-rest-8         new            verified_in_code disagreement_casebook walks every snapshot folder with full materialisation, un-isolated (latent while Stage B is held)
MEDIUM   market-live-1            new            verified_in_code Execution tape: one market's metadata defect stops capture for all 12 markets
MEDIUM   market-live-2            new            verified_in_code CLOB gap audit raises its own threshold from the loop's lifetime-worst iteration
MEDIUM   market-live-3            new            doc_claimed      Live-lane residue is untracked after the 2026-09-04 no-live decision
MEDIUM   market-live-4            new            verified_in_code The host registry has no state that means live is off
MEDIUM   market-live-5            known_open     inferred         The live lane's own gate machinery is now its dominant failure mode
MEDIUM   market-maker-4           new            verified_in_code Paper engine has no inventory state, so no risk cap can bind; scorer TTL disagrees with the run
MEDIUM   market-maker-5           known_open     verified_in_code No component on any branch measures fill probability or post-fill loss; economics is an eligibility screen
MEDIUM   market-maker-6           new            verified_in_code Paper-engine statistics claim corrections the code does not apply
MEDIUM   market-maker-7           new            verified_in_code Both 14-day gates read a window of at most 14 run folders
MEDIUM   market-maker-8           new            inferred         At current free disk the recurring maker roll refuses to launch
MEDIUM   market-maker-9           known_open     doc_claimed      Paper settlement P&L uses the WU proxy label while venue rules for the tested market are recorded as NOAA-first
MEDIUM   ops-archive-5            new            verified_in_code Master's storage lanes refuse most of the time: a 180 s heartbeat bound is applied to a snapshot loop that does not heartbeat during its sleep
MEDIUM   ops-archive-6            new            verified_in_code Proportionality: roughly 50,000 lines and 110 commits bought about two weeks of disk runway
MEDIUM   ops-archive-7            known_open     verified_in_code The approval chain proves consistency between agent-written files, not owner authority
MEDIUM   ps-ops-3                 new            verified_in_code Watchdog settlement-hole escalation is dead code after status flag text changed
MEDIUM   ps-ops-4                 known_open     verified_in_code One-shot scheduled tasks are never unregistered; monitor noise and cost grow without bound
MEDIUM   ps-ops-5                 new            verified_in_code Training window: a status-file write failure skips the capture restore; thrown reasons are never logged
MEDIUM   ps-ops-6                 new            verified_in_code One-shot runners have throw sites that leave no receipt and no log
MEDIUM   ps-ops-7                 known_open     verified_in_code Generated config is git-tracked and rewritten in the production tree four times daily
MEDIUM   security-2               new            verified_in_code No privilege boundary between autonomous agents and the user's secrets
MEDIUM   security-3               new            verified_in_code 79 GB of deleted originals depend on one Google account and self-asserted key custody
MEDIUM   security-4               known_open     doc_claimed      Production host: SSH password auth, RDP, IIS, no disk encryption (per 08-14 handover)
MEDIUM   storage-capacity-6       new            verified_in_code A built, merged, fail-safe config flag worth ~13 GiB of trough headroom was dismissed on the wrong metric
MEDIUM   storage-capacity-7       known_open     doc_claimed      The only slope-reducing software fix (warm tier) has been blocked since 08-02 and nothing scheduled generates its prerequisite
MEDIUM   storage-capacity-8       known_open     doc_claimed      A second disk is the cheapest durable option; 'the host cannot be grown' is asserted without a reason
MEDIUM   live-ops-state-6         known_open     verified_in_code 70-85% host commit is a silent dead zone between the memory guard and the settlement chain
MEDIUM   live-ops-state-7         known_open     live_state       STATE_OF_PLAY (09-13) is contradicted by live state in five places
MEDIUM   live-ops-state-8         known_open     live_state       No instrument has measured the primary objective for 36 days
MEDIUM   live-ops-state-9         known_open     inferred         Unclean shutdowns are attributed to power loss without evidence; reboot pending on a nearly full disk
MEDIUM   docs-system-2            new            verified_in_code Distilled research canon omits the last 15 missions; their conclusions live in an unindexed doc, a 'never use' section and local Claude memory
MEDIUM   docs-system-3            new            verified_in_code Operations index labels a fixed incident LIVE, states a paused mirror as running, and leaves 17 files unlinked against its own rule
MEDIUM   docs-system-4            new            verified_in_code Four canonical files state different objective hierarchies; two still call the streak the '#1 operational objective'
MEDIUM   docs-system-5            new            verified_in_code Git authority and branch-deletion rules contradict across git-workflow, the role file and the delegation contract
MEDIUM   docs-system-6            new            verified_in_code Mandatory onboarding is about 4,400 lines before acting, inflated by duplication, dead sections and an undistilled findings file
MEDIUM   docs-system-7            known_open     verified_in_code Documentation transaction is costly, attests form not truth, omits the mandatory files from the audit, and has been pending 8+ days
MEDIUM   docs-system-8            new            verified_in_code Live-pilot runbook delegates operator authorization and failed-attempt history to STATE_OF_PLAY, which no longer contains them
MEDIUM   tests-ci-4               new            verified_in_code Change-detector ratchets make refactoring expensive without protecting behaviour
MEDIUM   tests-ci-5               new            inferred         No environment routinely runs the host-global lease tests, and by code trace they collide with the production runner
MEDIUM   tests-ci-6               new            verified_in_code Test hermeticity is policy, not mechanism: no conftest, no network guard, no timeout, and the offline marker has no reader on master
MEDIUM   tests-ci-7               new            verified_in_code CI has no coverage, lint, type or PowerShell static analysis, and docs lint runs before and can mask the test step
MEDIUM   architecture-3           known_open     verified_in_code Seven files exceed 3,000 lines and module-size governance has no ceiling
MEDIUM   architecture-4           new            verified_in_code Shared helper modules are bypassed; basic utilities are re-implemented 50 to 150 times
MEDIUM   architecture-5           known_open     verified_in_code Replay readers are not cold-archive aware: an archived market-day reads as an empty corpus
MEDIUM   architecture-6           new            verified_in_code Import ratchet permits 66% of package edges and cannot see top-level conduit modules
MEDIUM   architecture-7           new            verified_in_code No lint, no type check, no transitive dependency lock
MEDIUM   error-handling-sweep-4   new            verified_in_code Tape-derived fallback settlement is graded 'complete', clears the hole flag and needs no WU fetch
MEDIUM   error-handling-sweep-5   new            verified_in_code Health checks gate on a negative token, so unreadable or absent evidence passes
MEDIUM   error-handling-sweep-6   new            verified_in_code Serving degrades HGB -> LR -> empirical on any exception with only a log warning; no monitor alarms on the fallback
MEDIUM   config-artifacts-4       known_open     verified_in_code Generated runtime state is tracked in config/, so the production tree is dirty by construction and every clean-tree gate fails from it
MEDIUM   config-artifacts-5       new            verified_in_code The only serving path that has ever run loads the base model unverified and fails open to a different model kind
MEDIUM   config-artifacts-6       new            verified_in_code Artifact registry binds bytes but not lineage, and its labels invert reality
MEDIUM   data-integrity-3         new            verified_in_code Canonical JSONL evidence is appended without fsync or torn-tail guard, streamed in many small writes, under a supervisor that hard-kills loops; the fsync went to the projection CSVs
MEDIUM   data-integrity-4         new            verified_in_code CLOB tiering deletes the only uncompressed canonical tape after verifying a gzip that was never fsynced
MEDIUM   data-integrity-5         new            verified_in_code Execution-tape capture fails closed with no repair path and a fleet-wide blast radius, and its seed config is rewritten in place underneath it
MEDIUM   data-integrity-6         known_open     verified_in_code A reader holding the raw-tape guard makes the book writer discard already-fetched order books after about 50 ms
MEDIUM   data-integrity-7         new            verified_in_code Shared 'atomic' helpers give three different guarantees, none durable, and in-place JSON writes outnumber them two to one
MEDIUM   agent-governance-5       known_open     verified_in_code The documentation transaction has been open since 2026-08-23 and overdue since 08-24 09:00
MEDIUM   agent-governance-6       new            verified_in_code 'Never delete' rules accumulate 382 branches, 200 worktrees and ~149 spent-task notes that bury the three HIGH alerts
MEDIUM   agent-governance-7       new            verified_in_code Two agent systems keep separate knowledge stores, and the canonical contracts contradict each other
MEDIUM   time-units-2             new            verified_in_code captured_at_local is Toronto time for all 12 markets and the settlement ledger grades its '12:00-18:00 local' window in that offset
MEDIUM   time-units-3             new            verified_in_code Legacy hour-of-day analytics read the Toronto wall clock as each market's local hour
MEDIUM   time-units-4             known_open     verified_in_code *_c field names hold Fahrenheit for 11 of 12 markets, and the same suffix means true Celsius in the WU store
MEDIUM   gap-settlement-truth-source-2 new            live_state       WU-vs-venue agreement is measured per row but was never aggregated: 921/921 pre-switch, 131/132 post-switch, band level only
MEDIUM   gap-settlement-truth-source-3 new            verified_in_code Serving-floor safety is checked WU-against-WU; nothing compares the floor with the venue's feed
MEDIUM   gap-settlement-truth-source-4 known_open     live_state       All 168 'unsettled' market-days already hold the venue's winning band on disk; policy forbids using it, and no doc separates economics truth from training truth
MEDIUM   gap-settlement-truth-source-5 new            verified_in_code The venue's Rules text is not retained anywhere in the repository
MEDIUM   gap-live-lane-truth-and-eligibility-4 new            verified_in_code Five live-money controls were relaxed between failed attempts on test day; all authority is agent paraphrase
MEDIUM   gap-live-lane-truth-and-eligibility-5 new            doc_claimed      Funds: no closing balance, withdrawal, fee or post-test account record; wallet cash moved 214 pUSD during the day unexplained; account-wide cancel-all ran on a personal wallet
MEDIUM   gap-live-lane-truth-and-eligibility-6 known_open     doc_claimed      Venue Rules for the traded market name NOAA first and WU only as fallback; recorded only off master
MEDIUM   gap-live-lane-truth-and-eligibility-7 new            verified_in_code No ToS / licence / regulatory register exists; of the exposures checked only Open-Meteo is recorded
MEDIUM   gap-chain-deferral-evidence-and-memory-root-cause-5 new            verified_in_code Per-date blocker history is destroyed daily; 8 of the 10 unsettled dates cannot be attributed to a blocker
MEDIUM   gap-chain-deferral-evidence-and-memory-root-cause-6 new            live_state       An audit step's admission stands in front of settlement truth, and a post-step recheck can stop the run before the light in-process finalize (the 09-16 case)
MEDIUM   gap-chain-deferral-evidence-and-memory-root-cause-7 new            verified_in_code No consumer attribution is retained below 85% commit, so the 09-12 program-control authority has nothing to aim at
MEDIUM   gap-what-production-serves-4 new            verified_in_code Open-Meteo family stale-cache fallback is unreachable; a failed refresh blanks the source immediately
MEDIUM   gap-what-production-serves-5 known_open     verified_in_code Calibration layer is fail-open, fitted on 2-6 days per hour, and no gate reads its own metrics
MEDIUM   gap-what-production-serves-6 new            verified_in_code forecast_high is a different estimator at serve than at training, and the parity gate does not check it
MEDIUM   gap-what-production-serves-7 new            inferred         In-season versus out-of-season contrast is confounded with the WU cutoff date
MEDIUM   gap-off-master-inventory-6 new            live_state       Accepted research results and prior audits exist only on branches; canon on master is silent; 31 commits are on no remote
MEDIUM   gap-off-master-inventory-7 known_open     verified_in_code One schema-registry file sits inside the capture import closure, making nearly every branch roll-sensitive and mutually conflicting
MEDIUM   gap-off-master-inventory-8 new            verified_in_code The production host cannot be rebuilt from origin: hand-made tasks, a hash/SID-pinned push task, LFS-only pickles, no lock file, no runbook
MEDIUM   gap-disk-reclaim-tiebreak-3 new            verified_in_code The cheap lever needs an explicit owner exception to three written rules, and no guarded script exists
MEDIUM   gap-disk-reclaim-tiebreak-4 known_open     live_state       About a third of unmerged worktree branches are local-only; detached HEADs and master are all pushed
MEDIUM   gap-disk-reclaim-tiebreak-5 known_open     doc_claimed      Shadow storage can absorb delete-type reclaim; the '10+ GiB from VSS' lever is unsupported by the only measurement on record
MEDIUM   gap-disk-reclaim-tiebreak-6 known_open     verified_in_code The long-CSV capture flag is real, fail-safe and roll-free; it is the second admissible lever
LOW      model-core-9             known_open     verified_in_code Exact zero below the floor, with the WU-empty floor sourced from non-resolution observations
LOW      model-core-10            new            verified_in_code Small latent defects: falsy-zero support bounds, or-chains on numeric zero, import-time target date, fail-open blend alpha
LOW      eval-validity-7          known_accepted verified_in_code Benchmark is Gamma outcomePrices, not a verified CLOB mid; P&L diagnostics fill at it without spread
LOW      eval-validity-8          new            verified_in_code 'Power' quoted in canon is observed-effect plug-in power
LOW      eval-validity-9          new            verified_in_code Daily-learning promotion confidence check has no input producer and would be an i.i.d. bootstrap if wired
LOW      eval-validity-10         known_open     verified_in_code 230 KB PIT module mixes five concerns; statistical core is 60 lines with no coverage test
LOW      reporting-gates-9        new            verified_in_code Vacuous passes on empty or uncomputed inputs, including a dead alert whose test uses a fabricated fixture shape
LOW      calibration-9            new            verified_in_code Monolith risk: a 4,046-line replay module and a 7-file star-import chain that is one module in disguise
LOW      calibration-10           new            verified_in_code Silent skips and stray hard-coded values in trainers and replay
LOW      strategy-10              new            live_state       Staged research corpus sits in an unmanaged temp directory on the production host
LOW      recent-work-8            known_accepted verified_in_code A generated 1.7 MB JSON is tracked in git and auto-committed before every merge
LOW      recent-work-9            known_open     verified_in_code Report filenames and mission IDs carry synthetic future dates
LOW      recent-work-10           new            verified_in_code 30 commits exist only on this host, including two product fixes
LOW      collection-sources-7     new            verified_in_code Atomic-write discipline is inconsistent across source stores and file existence is used as coverage
LOW      collection-sources-8     new            verified_in_code One implausible auxiliary field discards the whole WU observation, including its temperature
LOW      collection-sources-9     new            verified_in_code eccc_history write mode is hard-wired to May and June
LOW      ops-chain-9              new            verified_in_code Receipts and budgets that do not describe what actually runs
LOW      reporting-rest-9         new            verified_in_code Reporting layer is disproportionate to the decisions it informs; 16% of it has no production caller
LOW      reporting-rest-10        new            verified_in_code Progress ledger 'append' is a non-atomic truncate-and-rewrite that silently drops unparseable history
LOW      market-live-6            new            verified_in_code A partial /books response is recorded as a clean capture
LOW      market-live-7            new            verified_in_code Dead trading-capable adapters and a live_posted label with nothing behind it
LOW      market-live-8            new            verified_in_code SDK trust rests on first use; an unhashed live extra and a version-only import path remain
LOW      market-live-9            new            verified_in_code Paper taker fee model cites the US exchange's fee page
LOW      market-maker-10          new            verified_in_code Markouts have no staleness bound
LOW      ops-archive-8            known_open     verified_in_code Documentation transaction is permanently overdue, and the docs audit cannot detect a stale state file
LOW      ops-archive-9            new            doc_claimed      Recovery keys share a Drive remote with the ciphertext, and their location identifiers are published in a tracked doc
LOW      ps-ops-8                 new            verified_in_code Heavy-work window check is copied into at least 12 scripts; policy doc gives two boundaries; no DST guard
LOW      ps-ops-9                 new            verified_in_code Scheduler state is not reproducible from the repo; hard-coded checkout paths; SMB password on a command line
LOW      ps-ops-10                new            verified_in_code Format operator precedence: the tiering-skip message never names the skipped job
LOW      security-5               new            verified_in_code Current serving path unpickles model artifacts with no integrity check
LOW      security-6               new            verified_in_code shell=True behind a prefix-only allowlist in MM preflight recovery
LOW      security-7               new            verified_in_code No dependency lock file, hashes or advisory scanning; Actions pinned by tag
LOW      security-8               new            verified_in_code weather.com API key literal in Git history; settlement source uses a scraped front-end key
LOW      security-9               new            inferred         Dashboard launcher does not pin Streamlit to localhost
LOW      storage-capacity-9       new            live_state       200 worktrees are a small, one-off and risky reclaim
LOW      storage-capacity-10      new            verified_in_code Capacity documentation is stale and the last five days of storage work exist only on unmerged branches
LOW      live-ops-state-10        new            verified_in_code Settlement-hole checker cannot distinguish 'unsettled' from 'fell out of the 400-line tail'
LOW      docs-system-9            new            verified_in_code Protected near-close window ends at 00:30 in three canonical places and 00:05 in two, including the generated 'cannot drift' reference
LOW      docs-system-10           known_accepted verified_in_code 'Dated' correspondence filenames are sequence numbers colliding with real dates; the handoff channel has been dormant 38 days while docs say it grows daily
LOW      tests-ci-8               known_open     inferred         The operations suite proves refusal far more than completion
LOW      tests-ci-9               known_accepted verified_in_code retrain.yml is dormant and unverified; no retrain lane is running anywhere
LOW      architecture-8           new            verified_in_code Research one-offs and tombstone stubs live in the production package and tools
LOW      architecture-9           known_open     verified_in_code Generated 1.7 MB runtime file is tracked under config/, keeping the production tree permanently dirty
LOW      architecture-10          known_open     verified_in_code Four overlapping import-resolution mechanisms; sitecustomize patches the interpreter for any process started in the repo
LOW      error-handling-sweep-7   new            verified_in_code Streak 'contiguous complete days' is contiguous over ledger rows, not calendar days
LOW      error-handling-sweep-8   new            verified_in_code Risk sizing coerces unparseable USAGE to 0.0 and drops correlated caps on a bad value (latent)
LOW      error-handling-sweep-9   new            verified_in_code status.ps1 self-blinding spots under global SilentlyContinue
LOW      config-artifacts-7       new            verified_in_code Config generator writes capture-critical files non-atomically and with CRLF against an eol=lf pin
LOW      config-artifacts-8       new            verified_in_code Promotion preflight never checks that registry-referenced artifacts exist; one required artifact lives only in a gitignored directory
LOW      config-artifacts-9       known_open     doc_claimed      LFS bandwidth quota is exhausted by design constraints and pre-LFS pickles remain in history; gc precondition is never met
LOW      data-integrity-8         new            verified_in_code 'Could not read' is treated as 'empty' and then written back over the existing file
LOW      data-integrity-9         new            verified_in_code After-the-fact detection is per-slug or seal-time only: tail truncation, whole-slug loss and labels-CSV shrinkage would pass
LOW      data-integrity-10        new            verified_in_code Live capture re-reads the whole day's forecasts_long.csv into memory on every snapshot
LOW      agent-governance-8       new            live_state       Blanket merge rules are stricter than the roll mechanism, and the guard exists only inside the tool
LOW      time-units-5             new            verified_in_code What fires on 2026-11-01: grading windows shift one hour for all 12 markets and status.ps1 computes a negative heartbeat age
LOW      time-units-6             new            inferred         early_hour_coverage_summary uses wall-clock arithmetic: spring-forward will falsely BLOCK all 12 markets, fall-back can mask a real outage
LOW      time-units-7             new            verified_in_code Toronto-hour operating windows are applied to markets up to three hours west
LOW      time-units-8             known_open     inferred         Every hour-indexed model rule is wall-clock and was fitted on daylight-time data only
LOW      gap-settlement-truth-source-6 new            verified_in_code Scoring keeps the WU bucket even when the venue is known to have paid a different band
LOW      gap-settlement-truth-source-7 new            verified_in_code reconciliation_alerts.jsonl is write-only and re-appends the same alert on every re-finalize
LOW      gap-settlement-truth-source-8 new            verified_in_code The 09-06 observation of the rules change was lost when STATE_OF_PLAY was rewritten on 09-13
LOW      gap-settlement-truth-source-9 new            live_state       All twelve 2026-06-18 labels are permanently not_closed
LOW      gap-live-lane-truth-and-eligibility-8 known_open     verified_in_code Parked-lane residue is still armed and the registry has no 'off' state
LOW      gap-chain-deferral-evidence-and-memory-root-cause-8 new            verified_in_code Finalize re-processes every historical folder in-process on every run but is documented as a one-day step
LOW      gap-what-production-serves-8 known_open     verified_in_code cloud_group is dead at serve in the 11 F markets, alongside the known-dead wind_group
LOW      gap-what-production-serves-9 new            inferred         Avoidable polling and dead payload on a disk-constrained host
LOW      gap-off-master-inventory-9 new            live_state       A fix branch for this audit's findings is being written now: local-only, partly uncommitted, and aimed at a file whose deployed copy is pinned elsewhere
INFO     reporting-gates-10       known_accepted verified_in_code The observed-floor safety monitor is documented as fail-closed but runs alert-only
INFO     ops-chain-10             new            verified_in_code The backfill tool was non-functional until 2026-09-04, and its recipe does N full finalizes
INFO     market-live-10           new            verified_in_code An accidental live order is not a realistic failure mode
INFO     ops-archive-10           known_accepted inferred         About 80.8 GB of originals classed irreplaceable now exist only off-host, under a paused-backup posture the owner has accepted
INFO     security-10              new            verified_in_code Self-asserted safety flags and stale template line in the credential path
INFO     tests-ci-10              known_open     doc_claimed      The suite itself is cheap to run on the host; the constraint is the machinery around it
INFO     error-handling-sweep-10  new            verified_in_code Pattern census: counts overstate the problem; defects are gate semantics, not raw swallowing
INFO     config-artifacts-10      known_accepted verified_in_code No release has ever been cut; the release machinery has never run on real evidence
INFO     agent-governance-9       new            live_state       Control ledger: which controls are load-bearing and should be kept
INFO     time-units-9             new            verified_in_code Naive-datetime census: 36 naive now(), 2 utcnow(), 4 date.today() out of 451 clock reads; none decides a gate without documentation
INFO     gap-settlement-truth-source-10 new            doc_claimed      The -100c/-100e/-100f/-100g 'WU outcome' missions say nothing about venue agreement
INFO     gap-live-lane-truth-and-eligibility-9 known_accepted doc_claimed      Open-Meteo non-commercial term: recorded, owner-decided, revisit trigger stated
INFO     gap-chain-deferral-evidence-and-memory-root-cause-9 known_open     live_state       All 10 dates are recoverable now; no hard deadline found; about 22 minutes per date; 09-16 needs finalize only
INFO     gap-chain-deferral-evidence-and-memory-root-cause-10 new            verified_in_code No long-lived loop iterates the 51-location config; the accumulators found in the sampled loops are bounded
INFO     gap-what-production-serves-10 new            verified_in_code Snapshot loops iterate exactly 12 markets; the dashboard is safe on the production host
INFO     gap-off-master-inventory-10 known_accepted live_state       Corrections to the audit's working premises about which branches are unmerged
INFO     gap-disk-reclaim-tiebreak-7 new            live_state       Tie-break: recent-work was right (-12%); storage-capacity-9 and agent-governance F6 were low by about 6x
INFO     gap-disk-reclaim-tiebreak-8 known_open     inferred         The free-space figures 21, 18.5, 11.3 and 14.2 are one GiB instrument at different sawtooth phases and are mutually consistent
INFO     gap-disk-reclaim-tiebreak-9 new            live_state       C:/tmp and worktree-local data/ are not levers; the PIT corpus in C:/tmp is hard-linked and frozen
INFO     gap-disk-reclaim-tiebreak-10 new            live_state       A fix branch advanced in a new worktree while the no-changes audit was running

30 audits, 296 findings, 85 findings with verdicts
```
