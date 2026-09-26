# Wide audit — 2026-09-25

- **Owns:** the multi-agent read-only audit of 2026-09-25 (10 areas, every HIGH/CRITICAL finding independently verified), ranked actions, owner decisions and their dispositions.
- **Read when:** planning ops, disk, maker, security or docs work in the following days.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)).

**Dispositions (2026-09-26 night):** owner decided a-e and the disk reclaim (DECISION_LOG 2026-09-25); 88a floor 40 GiB landed and restarted; paper-maker flag landed; .gitignore covers `config/local/` and `.claude/settings.local.json`; contracts tag after the MAK-4/MAK-1 fixes (110e); retired `mm_runs`/`taker_runs` NTFS-compressed (+25 GiB); DOC-1/2/3 applied; afternoon stage off via 110g (next quiet window); wallet INCOMPLETE P&L via 110f; settlement negative-Celsius parser (CI-4) is 95b.


## 1. Overall verdict

- **Disk is the binding risk this week.** Free space was 53.1 GiB at 23:31 and falls about 11–13 GiB a day. The 50 GiB floor is likely crossed on 09-26, 40 GiB around 09-27, and zero in about 4–5 days if nothing is reclaimed. Nothing currently armed can reclaim at that rate, and capture has no low-disk brake.
- **88a maker-evidence capture sits about 3 GiB above its own 50 GiB stop.** Today's 05:00 projection tiering was skipped because the lease was busy, and that step has no retry.
- **Core capture is healthy:** snapshot, CLOB, observation and execution tape are all fresh. The execution tape has a blind spot, though: when it goes fully dark, it raises the same warning it always shows.
- **Two latent correctness defects:**
  - The settlement ledger mis-parses negative Celsius band labels. This matters before the first sub-zero Toronto day.
  - A plaintext wallet-credential file is still on the production Desktop.
- **The maker code is close to taggable.** One hole in the InfoEvent contract should be closed before v0.1. On real weather views, `informed_v0` always quotes one side.
- **Some canon files still contradict the 09-25 pause:** the runbook header, digest point 12, and the Stage 2 item in STATE_OF_PLAY.
- **No finding was refuted.** Many were downgraded because live trading is paused and the code involved is unmerged.

## 2. Act now (verified, holds; ranked by risk)

| # | ID | Sev (verified) | Area | Evidence | Fix | Who | Before 00:30? |
|---|---|---|---|---|---|---|---|
| 1 | DISK-1 | HIGH (claimed CRIT) | Storage | 53.07 GiB at 23:34. Net loss about 11 GiB/day. Stage-A leaves −5 to −6 GiB each day. 91a is not registered (STATE:75). | Tonight, under the lease, run the landed attended cold-snapshot compress-and-retain lane, oldest closed days first. Measure the NTFS ratio, then size 91a from it. If the ratio is under about 3x, the Drive archive is also needed. | owner-decision | **Yes.** Put it first in the window. |
| 2 | DISK-3 / CAP-2 | HIGH | 88a | `maker_evidence_store.py:50` brakes at 50 GiB. Floor fix `d0e06394c` is not on master and is roll-sensitive. The task relaunches every minute, so a stop lasts exactly as long as free space stays under 50 GiB. | Run `roll_verdict.ps1`, then land in the 01:00–04:00 window. After landing, restart deliberately and check that `source_sha256` in status.json matches the file. Pair with reclaim: the new floor buys about one day. | owner-decision | **Yes** (already in tonight's plan) |
| 3 | OPS-1 | HIGH | Ops / disk | `clob_tiering_task_status.json` shows SKIPPED_WORKLOAD_LEASE_BUSY at 05:00 with no retry. The 06:00 raw tiering also skips when the lease is busy. | Make sure tonight's work releases the heavy lease before 05:00 and stays off it until 06:00. Add a bounded retry. Consider moving the 4.6 GB of cold-eligible rotated logs. | owner-action | **Yes.** Tonight's long overnight work (91a-style runs, 95b) must not hold the lease across 05:00–06:00. |
| 4 | DISK-2 | HIGH (claimed CRIT) | Storage | No capture-side brake (storage-plan step 5). Correction: Stage-A does have a 30 GiB admission gate (`daily_refresh.py:265-322`), but 30 is below the plan's 45–70 GiB bands. | Short term: raise or add a Stage-A projection skip at about 45 GiB (roll-free .ps1) and name who pages the owner when the 24 h low drops below 45. Longer term: build the D5-01(c) brake. | agent-alone | Name the pager tonight. The code can follow. |
| 5 | DISK-5 | MED | Storage | The suite floor is exactly 50 GiB and is re-checked per chunk. At 00:30 there will be about 52.4–52.6 GiB. | Reclaim first. Run 95b or the suite only if free space measures at least about 58 GiB. | agent-alone | **Yes** (it changes tonight's gate) |
| 6 | CAP-1 | HIGH | Capture | `price_path_evidence_usable` needs cumulative `seconds_dark == 0`, so it is false for the rest of the day after any reconnect. `status.ps1:1398-1406` FLAGs only on process failure or BLOCKED_EVIDENCE_LOSS. | FLAG when `capture_state` is not CONNECTED or DEGRADED_PARTIALLY_CONNECTED, or when a seed-error dark is set. Base the usable condition on current darkness. Roll-free. | agent-alone | Optional; it is roll-free |
| 7 | SEC-1 | HIGH | Security | `Desktop\.env.txt`: 1,376 B, mtime 08-13, unchanged since the 09-18 audit. The verifier could not stat it (sandbox), so this relies on the auditor's metadata check. | Owner inspects it. If it is populated, move it off-host and delete it securely. If exposure is in doubt, rotate the L2 credentials. Record the disposition in STATE_OF_PLAY. | owner-action | No, but overdue |
| 8 | CI-4 | HIGH | Settlement | `settlement_ledger.py:573` uses `\d+`, so '-2°C' is read as the band [-2, 2]. `polymarket_winning_markets` uses the same parser, so reconciliation would report false mismatches. There are no tests for negative labels. | Parse `-?\d+` with separate handling of the range hyphen, and possibly U+2212. Single-number labels keep `value_hi = value`. Add table tests for both parsers. Versioned change in the quiet window. | agent-alone | No. It must land before the first sub-zero Toronto day. |
| 9 | MAK-4 (+MAK-1) | MED | Maker contracts | An InfoEvent with no reference time, or observed-only with no expiry, validates and is then never active, so a pull fails open. | Require one of scheduled, observed or detected. Treat observed-only events as active until expiry or removal. | agent-alone | **Yes.** Fix before tonight's contracts v0.1 tag. |
| 10 | MAK-1 | MED (claimed HIGH) | Maker policy | The weather stdev (at least about 0.10) pins width at the cap. With grade 'none', the disfavoured leg is dropped (`policy.py:351-353`), so quoting is one-sided whenever p ≠ mid. No test runs a real WeatherFairValue view through `decide()`. | Decide whether an unscored fair value may skew quotes. Either quote symmetrically for grade 'none' or clamp the widened leg. Add an end-to-end test that asserts the number of legs. | owner-decision | Before any Phase 2 replay is read. It also biases tonight's plugin dry run, so read that run's leg counts with this in mind. |
| 11 | OPS-3 | MED | Ops / learning | The barrier blocks on the retired `maker_paper_score` and on `exchange_economics_rule_drift`. Fix `f2ac4ed8f` (`--paper-maker-paused`) exists but is not wired into the scheduled invocation. Correction: daily_learning has been stale since 08-13, which predates the retirement, so the cause of the 43-day staleness is not established. | Wire the flag in with tonight's paper-maker flag landing. Diagnose the rule-drift BLOCK (possibly the EF §10o fee change). | owner-decision | **Yes** (paper-maker flag is tonight) |
| 12 | DOC-1/2/3 | MED | Docs | Runbook:5 and digest:30 still grant the RE-1 exception. STATE:30, :63-64 and :79-80 schedule the Stage 2 build and a live session around 10-01, against DECISION_LOG:39 and :42. | Apply the replacement text in each finding. | agent-alone | **Yes.** Fold into tonight's doc closeout. |
| 13 | CI-1 | MED | CI | The light path skips `agent_docs_audit`, which the suite and CI assert. STATE_OF_PLAY is at 95 of its 95-line budget. | Add the audit (it takes seconds) to the light-path receipt. Leave slack in the STATE budget. | agent-alone | **Yes.** Run the audit before pushing tonight's closeout. |
| 14 | OPS-2 | MED | Ops | The deployed watchdog (aa99048, not an ancestor of master) raises false paused-maker alarms and has no MAKER_EVIDENCE check. STATE:49 is half-true. | Build a reconciled watchdog commit, deploy it to a new locked worktree with new pins, and correct STATE:49. | agent-alone | No |
| 15 | WAL-1 | MED | Accounting | A campaign lot that has resolved but is unredeemed drops out of equity. Chicago 75 YES would show −32.25 whether it won or lost; a win is really about +42.75. | Add terminal resolved value for post-baseline lots, or mark the P&L INCOMPLETE. Meanwhile, redeem before reading campaign P&L. | owner-decision | No |
| 16 | FV-1 | MED | Model | The afternoon centering shift runs before calibration truncates below the floor, so a cool shift turns warmer at 15–16h. Lockin suppresses this at 17–18h. | Include it in the owner-approved test-and-disable of the stage. The maker T+0 path should flag rows where the stage is active. | owner-decision | No |
| 17 | FV-2 | MED | Model | Serving uses the median of live sources with censoring at the floor. Training uses a single stitched Open-Meteo value. The skew is unmeasured. | Run a bounded read-only parity measurement and record it in EF. Keep the maker centre at mid. | agent-alone | No |
| 18 | RE1-1 | MED | Live safety | The pause and the bleed limit exist only in prose. No code gate would refuse a session today. | Before any resumption, add a fail-closed pause marker and a bleed-limit preflight. Carry both into maker_core as portfolio limits. | owner-decision | No (the owner starts every live run) |
| 19 | DISK-4 | MED | Storage | The 91a nightly run holds the lease from 00:30 to 04:45 (MaxRuntime 15300). It is roll-sensitive (schema_registry) and based on an old master. | Cut the deadline or budget. Rebase. Sequence: reclaim, suite, land, dry run, register. | agent-alone | Do not register it tonight |

## 3. Next few days (MED)

**Maker core / plugin**
- MAK-2: cancel resting legs that the current view drops or moves adversely (or carry `placed_fair_value`).
- MAK-3: refuse when Unavailable.kind is `decided`, `corrupt` or `out_of_scope`.
- MAK-5: the SecretGuard substring scrub strips `outcome_tokens` and asset identity. Allowlist identity keys.

**Wallet / accounting**
- WAL-2: move `wallet_snapshot.py` out of the scratchpad and the detached `C:/tmp/wt-wrc` worktree into the repo.
- WAL-3: record resolved rows, rewards, server commit and capital derivation. Note in the ledger that the baseline predates the P&L split.
- WAL-4: store the reason code for each attempt.
- WAL-6 (owner-action): check one known taker fill against the maker_address query.

**Ops**
- OPS-4: Stage-A finished 33 min before teardown. Dropping `maker_paper_score` saves about 9 min.
- OPS-5: the documentation transaction has been overdue since 09-20, with 23 pending. Tonight's closeout addresses it.
- OPS-6: lock and tag the boot-recovery worktree (`weather-integration-attempt-recovery`) and exclude it from cleanup.
- OPS-7 (owner-action): unregister about 40 spent one-shot tasks, starting with the credential-import and merge/push tasks.

**Capture / evidence**
- CAP-3: FLAG on 88a `compression_error` or raw bytes above about 40% of the limit.
- CAP-4: write a quarantine runbook for a torn 88a journal.
- CAP-5: check for a trailing newline before each ledger append. BLOCK when any line fails to decode.
- CAP-6: surface and de-duplicate reconciliation alerts, and track the venue resolutionSource.
- CAP-7: register `data/wallet_ledger` as protected canonical_evidence.

**Model serving**
- FV-3: the centering stage was fitted on a pipeline that has not been served since 06-30. Do not refit it on its own output.
- FV-4: mark hour boundaries in the plugin clock as model-stage boundaries, not information.
- FV-5: remove the `market_yes` path from serving, or hard-fail on `market_shrink`. Add a ratchet test. Roll-sensitive.
- FV-6: the plugin should accept only `no_market` variants.

**Docs**
- DOC-4: forward plan.
- DOC-5: live-testing plan.
- DOC-6: attempts 5–11 vs 5–12.
- DOC-7: 88a floor wording plus the night queue.
- DOC-8: 09-25 model approvals missing from STATE.
- DOC-9: fill count and the Miami loss.
- DOC-10: OPEN_QUESTIONS owners.
- DOC-11: item 330 September 25 status.

**Security**
- SEC-2 (owner-decision): the RE-1 and wallet-reader loaders read a plaintext `.env` that holds the private key. Record the exception, or return to wincred for maker_core.
- SEC-3: add `config/local/` and `.claude/settings.local.json` to the tracked `.gitignore`. Tonight's `.gitignore` fix should include both.

**CI / tests**
- CI-2: set `fetch-depth: 0` in `host-load-hook.yml` and `retrain.yml`.
- CI-3: don't use cancel-in-progress on master, so every master commit gets a completed run.
- TEST-1: add a conftest that enforces OFFLINE and the write-root guard.
- TEST-2: run the PowerShell merge and recovery tools in the windows-qualification workflow.
- TEST-3: edge tests for the 88a disk bands.

**Live safety (before any resumption)**
- RE1-2: a second Ctrl-C skips cancel-all.
- RE1-3: tip `2b9a0ca9e` is untested. Test it or reset the tip to `d90d0a6e6`.
- RE1-5: replace the account-wide assumptions in maker_core with an exact expected-order ledger.
- RE1-6 (owner-action): run `reconcile 12`. The code hard-expires 09-30, so any later run is a new campaign.

**Storage**
- DISK-6 (owner-decision): allow hash-verified compress-and-retain on retired `mm_runs` (42 GiB) and `taker_runs` (9 GiB).
- DISK-7: attribute what Stage-A persists each day.

## 4. Owner decisions needed

1. **Disk reclaim now (DISK-1).** Recommend: spend the start of tonight's window on attended compress-and-retain, and approve the Drive archive if the measured ratio is under 3x.
2. **mm_runs/taker_runs compression scope (DISK-6).** Recommend: approve it as a one-time, lossless, hash-verified pass. It is the fastest large reclaim.
3. **88a floor landing path (DISK-3).** Recommend: quiet window after `roll_verdict`. If the suite cannot fit, allow the 2-line constant change on the light path, with a deliberate restart after.
4. **Unscored fair value and one-sided quoting (MAK-1).** Recommend: quote symmetrically, with no skew, for grade 'none' until the fair value is scored.
5. **Settled-day barrier (OPS-3).** Recommend: wire `--paper-maker-paused` tonight and have the exchange_economics drift BLOCK diagnosed.
6. **Afternoon centering stage (FV-1, FV-3).** Recommend: disable it pending measurement. Do not refit it on its own output.
7. **Campaign P&L with resolved-but-unredeemed lots (WAL-1).** Recommend: report INCOMPLETE rather than silently understate. Redeem before reading P&L.
8. **Put the pause and bleed limit in code before any RE-1 resumption (RE1-1), and settle the size rule (RE1-4).** Recommend: yes to both. Treat any run after 09-30 as a new campaign.
9. **Desktop `.env.txt` (SEC-1).** Recommend: inspect, move off-host, and rotate if in doubt.
10. **Plaintext `.env` credential pattern (SEC-2).** Recommend: maker_core uses wincred. Record the exception for the RE-1 and wallet-reader loaders.
11. **METAR pulls for T+1/T+2 (MAK-10).** Recommend: limit them to lead 0 until Phase 2 measures their value.
12. **`quiet_window_merge -Force` during 18:00–00:30 (OPS-10).** Recommend: refuse roll-sensitive merges in that window without an owner token.
13. **Minor:**
    - DOC-16: add a DECISION_LOG row clarifying that the pause suspends the 09-19 exception. Also confirm whether the bleed limit was adopted or is only a recommendation.
    - SEC-4: set user.email to the GitHub noreply address.
    - SEC-5: retire the mirror SMB credential.
    - SEC-6: accept plain HTTP for the wallet reader as scoped.

## 5. Refuted or downgraded claims

None were refuted (every verified item has holds = true). Downgrades and corrections:
- DISK-1 is HIGH, not CRITICAL. Its first consequence is a process block at 50 GiB. Evidence loss is 4–5 days out, and attended reclaims happen almost daily.
- DISK-2 is HIGH, not CRITICAL. Stage-A does have a 30 GiB admission gate and per-step floors, and alerting exists. The real gap is that there is no automatic brake on capture.
- DISK-3 is overstated on duration. The task relaunches every minute, so a stop lasts only while free space is under 50 GiB, not for the rest of the day.
- DISK-4 and DISK-5 are MED. The branch is unregistered and already gated in STATE, and the suite fails closed.
- OPS-2 is MED: the effect is alarm noise and one missing check. OPS-3 is MED: the retired maker does not explain the 43-day staleness, and the fix `f2ac4ed8f` already exists.
- MAK-1 is MED. Dropping a leg is designed behaviour, and the code is offline. The ~Q/3 earnings figure was not verified.
- WAL-1 is MED. The error only understates P&L, the single lot does not trip −40, and trading is paused.
- FV-1 is MED. Lockin suppresses the effect at 17–18h, so the "typical 15:00–18:59" claim is overstated. FV-2 is MED.
- DOC-1, DOC-2 and DOC-3 are MED, because the same files point readers to STATE_OF_PLAY and only the owner starts RE-1.
- CI-1 is MED. No breakage exists today, and a fix-forward repairs it.
- RE1-1 is MED, because the owner is the only one who can launch a run.

## 6. Sound — leave alone

- **Maker 110c fixes:** half-tick step, own-order subtraction, requote semantics, units and rounding, core free of weather literals, import ratchet, fair value free of market input, NBP parsing, settlement resolver, journal durability.
- **Wallet reader security boundary:** no PRIVATE_KEY, an exact GET allowlist, no redirects or proxies, RFC1918 IP plus a constant-time token check, and a journal with no headers.
- **Scheduled tasks:**
  - No task points at any of the worktrees slated for removal.
  - Every script path of every live task resolves.
  - The watchdog and boot-recovery hash pins match.
  - The deployed boot-recovery script matches master.
- **Core supervisors:** fresh and CLEAN, memory commit at 38%. The quiet-window merge refuses 12:00–18:00, and the Stage-A teardown works.
- **88a:** store design, compression with hash checks, source hashes matching master. 88a is not a material disk writer (about 60–90 MiB/day).
- **Settlement ledger:** hash-chained, with a lock that is safe on Windows.
- **Secrets:** no live secret in any tracked tree or in the history searched, and master's credential path is wincred-only.
- **RE-1 controller:** single-post discipline, pre-post binding, lost-ack blocking, open-order refusal, independent heartbeat, hard caps, owner typed confirmation.
- **Bounded suite:** exact tip, per-chunk basetemp, kill-on-close. Every test file named in the workflows exists.
- **Canon:** no dangling links, and the audit index is complete.

## 7. Unverified — worth checking

- Who held the heavy lease at 05:00 on 09-25 (OPS-1).
- Whether `agent_docs_audit` passes on master now. Run it before tonight's closeout (CI-1).
- The roll verdicts for the 88a floor, maker-core, weather-plugin and 91a branches. None was run.
- Whether the settled-day barrier has blocked every day since 08-13, and why `exchange_economics_rule_drift` BLOCKs.
- The real Polymarket spelling of negative Celsius labels, including the U+2212 minus sign (CI-4).
- The NTFS compression ratio on closed snapshots and mm_runs. It sets 91a's real GiB per night.
- What Stage-A persists (5–6 GiB/day), and what causes the +3 GiB step at 06:05 and the +3.7 GiB step at 19:50 on 09-24.
- The real contents and existence of `Desktop\.env.txt` (SEC-1).
- Whether CLOB `maker_address` fills include taker fills (WAL-6), and whether any of the 103 resolved holdings are unredeemed winners.
- Whether the served T+0 `afternoon_residual_centering` path consumes market prices, and whether morning snapshots carry that key.
- The 12 "day_ahead 0, available 0" reward shortages in 88a status.
- Whether the polymarket SDK retries `post_order` internally, and the scope of the venue's dead-man cancel.
- The pass state of `d90d0a6e6` and `2b9a0ca9e`, and the attempt-12 state in the campaign root.
- Whether tonight's worktree removal ran and what it reclaimed (expect about 2 GiB, not 5).