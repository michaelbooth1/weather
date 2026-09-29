# Night plan snapshot 2026-09-26 (work-tracker seed)

- **Owns:** a frozen copy of the production agent's untracked night plan of 2026-09-26/27, published only as backfill input for the work tracker (handoff 110p).
- **Read when:** backfilling work records.
- **Do not use for:** current state (STATE_OF_PLAY) or instructions; it is a dated snapshot.

# Night plan 2026-09-26/27 (production agent)

Owner approvals 2026-09-26: storage 1-9 (10 keep, 11 no); economics baseline re-accept (DONE 11:40, receipt
data/alerts/economics-baseline-20260926/); one-wallet portfolio ledger (handoff 110i); 110f and 110g handbacks received.

Serial, one lease at a time; lease released by 04:55; none 05:00-06:30; no heavy work before 00:30.

1. 00:30 — bounded suite on `origin/codex/integration-91a-110f-20260926` tip `8180404a0e588f73dab3c83a171538f8a89c9705` (SUPERSEDES 3c1e58337 in the loop prompt; adds 110i portfolio ledger d586e2d1e, 110j A registry a65195268 and 110j B twin delete e42dc36b5)
   (master 965374a0e + 91a + 110f wallet reader + 110g centering off + docs owner-decisions-0926-day).
   Worktree C:\tmp\wt-intsuite, LogPath C:\tmp\suite-logs\int-20260927.log, git identity args, ~50 min.
   If master moved: resync first (index-only conflicts).
2. 01:00-04:00 — `roll_verdict.ps1 -Branch origin/codex/integration-91a-110f-20260926`, then
   `quiet_window_merge.ps1` with -ExpectedTip = suite tip (never -DryRun). It proves 3 capture workers recovered and
   OneShotPushes. Verify origin/master.
3. 110g adoption: confirm the snapshot loop + observation trigger workers restarted after the merge (new pids/source hash);
   check a fresh snapshot's probability_calibration_context.afternoon_residual_centering: reason=artifact_disabled,
   active=false, zero shift. Confirm no bound release pointer exists (artifacts/releases/current_release.json absent).
   Receipt data/alerts/110g-activation-20260927.json.
4. Economics resume for 09-25 (snapshot valid until 09:58 local 09-27): under the lease,
   `python -m weather.operations.daily_refresh run --resume-from-step exchange_economics_rule_drift --backtest-root <data\backtest> --snapshots-root <data\snapshots> --settled-analysis-target-date 2026-09-25 --paper-maker-paused`
   from the production root. Check help first; stop if it would re-run long learning steps past 04:45.
5. Storage (each: free bytes before/after, exact manifest with sha256, receipt under data/alerts/storage-decisions-20260927/,
   file-by-file deletes only, never Remove-Item -Recurse):
   a. #1 backtest/replay_cache (owner waiver of the reachability manifest, DECISION_LOG 2026-09-26). Try
      cleanup_preflight --manifest; if it refuses on the class rule, record the refusal and delete per the signed manifest.
   b. #3 the 8 FAIL_CLOSED staging tarballs (e10d1/e10d2/e10d5/e10r6, p11b-e); keep every receipt JSON and the 4 PASS stages.
   c. #2 rotated console logs stamped before 09-12 (+ observation_trigger_console.log.malformed.bak); exclude the 4 incident
      files, the 07-13 clob console and live consoles.
   d. #2 taker counterfactual detail: the 6 named files.
   e. #8 gzip-and-retain EF §8e incident logs except the 07-13 file (verify gzip round-trip hash before removing plain).
   f. #2 backtest shadow exports via backtest_artifact_retention + cleanup_preflight, hand-excluding the pinned files.
   g. #2 mm_runs scoring projections: only if rebuild-source checks are simple; else defer with reason.
   Deferred to 110j part A: WU .tmp orphans (needs registry exclusion).
6. 91a: after landing, dry run of the nightly entry point per docs/operations/cold-snapshot-compression.md; register
   WeatherColdSnapshotNightly only after a clean dry run (probably 09-27/28 night).
6b. 110j C (compress-on-close 377b40186, capture writers, conflicts with 91a in cold_snapshot_compression_run.ps1) and D (lane extensions caf62294c): NOT tonight. After the landing, review both reports, rebase C/D on the new master, and plan their own suite for the 09-27/28 night.
   110j A is the registry basis for step 5: re-check cleanup_preflight for replay_cache and WU .tmp orphans after the merge.
7. Morning: summary to owner; record outcomes in STATE_OF_PLAY via docs light path. Also add DECISION_LOG rows (owner
   2026-09-26): (a) 110i default confirmed — unmatched lots go to owner-discretionary, outside bot bleed limits; (b) all trades
   so far are the owner's manual trades and must not pollute automated campaign data; the wallet reader's campaign start /
   capital are set only when the next automated campaign starts (current INCOMPLETE status is expected, not a defect).
   Update the STATE_OF_PLAY wallet bullet accordingly.

## Fable audit corrections (2026-09-26 14:10) — these override the steps above where they differ
- Suite must pass ALL chunks on 8180404a0 (first combined run; hand-merged schema_registry_recent_data.py). Never merge on a
  partial pass. If a failure is in 91a code, pull 91a out, rebuild the integration branch without it, re-run.
- After the merge verify the 88a WeatherMakerEvidenceCapture worker re-adopted too (was pid 17840), not only the 3 capture workers.
- python-dotenv pin moves to 1.2.3 (venv has 1.2.2); only wallet_reader_security imports it; do NOT pip-install tonight; record it.
- Step 5a replay_cache: cleanup_preflight classifies it OPERATOR_CACHE -> expect PASS; gates are operator_review
  approved/note/approved_by + per-file bytes/sha256. Require PASS. Measure file count first (bounded, timed); it is the biggest job.
- WU .tmp orphans: NOT executable (no proof-carrying caller) -> handoff 110k Part 2.
- Order before 04:55: 5a, 5b, 5c, then stop. 5d-5g and step 4 (economics resume, snapshot valid to 09:58) go in 06:30-09:00.
- Portfolio ledger production command will not run on data/wallet_ledger (layout mismatch) -> handoff 110k Part 1. Do not run it.
- Docs step 7: fix STATE_OF_PLAY lines on production source, afternoon centering, wallet reader landing, critical path 4,
  wallet bullet (manual-trades rule), disk item; add the 2 DECISION_LOG rows; note dotenv pin gap and 110i layout gap;
  land handoff 110k branch codex/handoff-110k-20260926 (7f883abd1) with the docs.
- Workstation queue: 110h (owner pasted 14:15), 110k. Then C/D rebase, plugin landing after the 110h dry run, Phase 2 replay harness.

## 110h weather plugin dry run (added 2026-09-26 14:40)
- Branch origin/codex/weather-maker-plugin-20260925 tip 3b8c7b92d (PR #96), ROLL-SENSITIVE (schema_registry_recent_data).
  Do NOT land before the dry run. Worktree C:\tmp\wt-plugin (GIT_LFS_SKIP_SMUDGE=1) at 3b8c7b92d.
- Slot: FIRST in 06:30-09:00 (needs 45 min + cleanup), then step 4 economics resume (before 09:58), then 5d-5g if time.
- Command: the report's exact block (agent-report-2026-09-110h-weather-plugin-dry-run-cli.md "Exact production command"),
  run from the PRODUCTION root for data paths but with $env:PYTHONPATH = 'C:\tmp\wt-plugin\src'; FIRST print
  `python -B -c "import weather.market.maker_plugin.dry_run as m; print(m.__file__)"` and require it under C:\tmp\wt-plugin.
  --date 2026-09-25, --data-root <prod>\data, --output <prod>\data\alerts\weather-plugin-110h-20260925 (must not exist),
  --max-seconds 2700 --max-output-bytes 200000000 --max-input-bytes 1073741824, under the lease 'WeatherPluginDryRun-110h'.
- Read both reports: coverage denominators per source, Unavailable reasons, mass sums, leg counts. MISSING_CONSERVATIVE_FILL_BOUND
  zero-leg decisions are EXPECTED (no measured hazard). Landing decision for the plugin goes into the morning summary; if clean,
  plugin lands 09-27/28 quiet window with 110j C/D (resync index conflicts first).

## Next nights (proposal, 2026-09-26 16:00)
- 110k-1 portfolio ledger adapter origin/codex/portfolio-ledger-adapter-20260926 6bf55b4c7 (PR #98) and 110k-2 WU orphan proof
  caller origin/codex/wu-orphan-proof-caller-20260926 67c46a704 (PR #99): both based on the integration branch, ROLL-SENSITIVE.
  The workstation rebases both after tonight's landing (hourly follow-up there).
- 09-27/28 night: one integration of weather plugin (only if the 06:30 dry run is clean) + 110k-1 + 110k-2 + 110j D.
- 09-28/29 night: 110j C (compress-on-close, capture writers) on its own.
- After 110k-1 lands: author config/local/portfolio_campaigns.json from its example (owner-discretionary only) and run its
  production command once on data/wallet_ledger; after 110k-2 lands: WU .tmp orphan cleanup.

- 110l (Phase 2 replay harness) handoff on origin/codex/handoff-110k-20260926 b5a1cf81e; land that handoff branch with the docs step (step 7).

- (D7 audit) Before the 00:30 suite: set $env:TEMP and $env:TMP to a fresh dir under C:\pt (e.g. C:\pt\tmp-int-20260927) in the launching shell, record %TEMP% free bytes before/after, and delete that dir (cmd rd /s /q, not Remove-Item -Recurse) after the suite. ~1,233 TemporaryDirectory uses write to %TEMP% outside --basetemp.

- Step 7 docs: land origin/codex/handoff-110k-20260926 (2c8b90618+: handoffs 110k/110l/110m/110n + repo-health audit 2026-09-26) via the docs light path after the integration merge (resync index first). STATE_OF_PLAY: add the repo-health audit to the critical path (4 live defects -> 110m part 1, 110n) and the 10 owner decisions pointer.

- 110l replay harness DONE: origin/codex/maker-replay-harness-20260926 ed6d43260 (PR #100, on top of the plugin branch). 09-27/28 integration (if dry run clean): plugin + harness + 110k-1 + 110k-2 + 110j D. RE-1 journal parity pending owner OK for workstation read-only access to RE-1 journals.

- Owner approved all 10 repo-health decisions (2026-09-26 ~19:30). Step 7 docs: add a DECISION_LOG row for them; handoff branch now d52969fa2 (adds 110o). Production-side: branch retirement per decision 7 once 110o documents the rule (archive-tag first, one-shot push task).

- Owner 2026-09-26: approved read-only workstation access to the recorded RE-1 journals for the 110l blind_re1 parity test (no keys, secret guard first, no copies into git beyond hashed minimal fixtures). DECISION_LOG row in step 7.

## Landing queue after tonight (2026-09-26 ~20:00; each night = one integration branch, one bounded suite, one quiet-window merge; rebase all on master after tonight's landing; roll_verdict each)
- 09-27/28: weather plugin 3b8c7b92d (only if 06:30 dry run clean) + replay harness ed6d43260 (+RE-1 parity if back) + 110k-1 6bf55b4c7 + 110k-2 67c46a704 + 110m-1 signed-band capture a0f11a8a6 (#101, live defect) + 110n ops alarm path ac47f5035 (#102; then run its re-registration commands after owner-ops review).
- 09-28/29: 110j C compress-on-close 377b40186 alone (capture writers).
- 09-29/30: 110m PIT split 3306dd95d (#103) + neutral helpers c1391d970 (#104) + quick wins 7c2392786 (#105) + 110j D caaf62294c; ratchets fbf1d3f67 (#106) LAST (may flag the others).
- 110o parts follow as they arrive.

- Replay harness tip now 8ee7b8ad (313/313 minute parity; 5 terminal differences strict-xfail with evidenced causes). Use it in the 09-27/28 integration.

## Fable audit corrections #2 (2026-09-26 ~21:40) — override earlier text where they differ
- Step 7 writes FOUR DECISION_LOG rows (not 2): (a) 110i default owner-discretionary; (b) manual trades never pollute automated data, campaign start only at next automated campaign; (c) all 10 repo-health decisions approved; (d) RE-1 journal read-only workstation access for harness parity. Plus STATE_OF_PLAY rewrite within 95 lines (merge wallet-reader into wallet bullet, trim 88a/disk history): production source = integration landing; 110g landed (receipt); wallet reader landed; critical path 1 = 110h done (3b8c7b92d), harness DONE 8ee7b8ad 313/313, dry run verdict; path 4 ledger needs 110k-1 + config/local/portfolio_campaigns.json; path 5 add repo-health audit (4 live defects -> #101/#102; 110o). Say "replay_cache deleted" only if 5a receipt exists. Note dotenv 1.2.3 pin vs venv 1.2.2 in the host bullet.
- Check `git status` at 01:00: only the two allow-listed config files may be dirty.
- Economics resume must finish inside the 09:00 lease and runs BEFORE 5d-5g; 5d-5g default to 09-27/28. If the suite fails and 91a is pulled, 5a-5c move to 06:30-09:00 after the dry run and economics.
- 110o sequencing (tell owner/workstation): part 3 must wait for 110n + 110m-3 landing; part 6 (index split) lands at one clean boundary right after the 09-27/28 integration; part 1 must update quiet_window_merge.ps1 hash pins and dirty allow-list.
