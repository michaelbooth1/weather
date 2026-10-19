# Phase C delta review for a post-N12 cutover (2026-10-19)

Status: **dated review, evidence only.** It records what the host Python upgrade kit assumed when it was
last checked (Phase B, 2026-10-16) and what changes once N12 and #190 land. The procedure itself lives in
[the host Python upgrade runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md). The cutover night, and the owner's GO,
live in [the state of play](STATE_OF_PLAY.md) and [the decision log](DECISION_LOG.md).

Read when: you prepare or run the Phase C night that follows N12 (`claude/integration-20261019-chain-r3`) and #190.
Read it together with the runbook's 2026-10-19 revision note. This review ran nothing on or against the capture host.

## 0. Inputs (git, read on the workstation)

| Ref | Full sha | Role |
| --- | --- | --- |
| `origin/master` | `6aac6de81a25bd939b954c5e7f29db02b2fd2fee` | today's production source |
| N12 `claude/integration-20261019-chain-r3` | `739c03eff1e2f26c49759899e4e39b669d2c6628` | post-N12 master tree; 218 files change against master |
| #190 `claude/nbm-parser-v2-r2-20261019` | `44a8c50e9a829cfca167bfdc387929b7adbaf421` | re-merged on post-N12 master on Tue 10-20 |
| `git merge-tree --write-tree 739c03eff 44a8c50e9` | tree `481a6590b3eb4f788f6fd61edad914b27ed4beb2` | simulated post-#190 tree; it conflicts in two test files only |

## 1. Why Phase C has not run, and what is still open

- **10-17:** C did not run because the owner had not given GO by 01:15. Nothing was touched (DECISION_LOG
  2026-10-17). The kit itself was not the cause.
- **10-19/20:** the owner's 10-19 ruling, "10-21/22 for python", relayed by master-agent, replaces this night. N12 also
  runs as a quiet-window merge that night, and G5 forbids a merge on a C night. The DL row and the re-dating belong
  to master.
- Still unresolved from Phase B:
  - (a) There is no procedure for a HEAD that moves after qualification. G3 says only that the move must be
    roll-free. Section 2 row 1 and the new runbook step B-R address this.
  - (b) The three standing `status.ps1` flags (an overdue doc transaction and two STALENESS_SWEEP CRITICAL rows) are
    handled by the C0 baseline. The owner must still accept them at C0.
  - (c) The open commitments queued "after C" have to be re-dated against the new night: the U6 registration (row 4
    below), the watchdog redeploy by 10-28, RF policy A with the #274 lane repin, the Q-11 production read, and the
    §9 follow-ups.

## 2. Stale assumptions and their replacements

| # | Assumption in the kit | Now | Replacement |
| --- | --- | --- | --- |
| 1 | G3: HEAD is the Phase B qualified tip (in `$R\qualification.json`, 10-16), or the move is roll-free. | N12 is roll-sensitive. It changes capture-loop modules, including `collection/snapshot_tracker.py`, `model/model_features.py`, `operations/supervisor.py`, the execution tape and 88a. G3 therefore fails as written. | The exact check is now in the runbook: `scripts\ops\roll_verdict.ps1 -Branch <HEAD> -Base <qualified tip>`; exit 3 or 1 fails. A failure needs **B-R** (new runbook step: archive the record, §D, B0, prove the wheelhouse and freeze unchanged, then B1c-B3) on an earlier admitted night, or an owner G3 ruling (section 5). |
| 2 | The venv holders are capture, the tape, the shadow and 88a (C2 `$Holders`; Q12). | N12 adds `WeatherMakerEvidenceLowestTemperature` (`config/scheduled_tasks.json` state `active`; registrar `register_maker_evidence_family_capture.ps1`). It is S4U `pythonw -m weather.market.maker_evidence_capture --family lowest_temperature`, with a 1-minute `IgnoreNew` trigger and no stop verb. If registered and not stopped, the C4 holder sweep refuses the rename, and the night is NO-GO with no swap. | Runbook edits: the Disabled-at-C2 list; C0 asserts it is in `aux-tasks.txt` and that `$R\q12b.txt` = `STOP_AUTHORIZED` (new owner choice Q12b); C2 stops it next to 88a; C9b restarts it through `$Holders`; C9c checks `data\maker_evidence_families\<id>\status.json`. |
| 3 | `aux-tasks.txt` and `tasks-venv.csv` come from the 10-13..16 H3 dumps. | The task set changed (row 2). | Before C0, re-take §4 H3 and rebuild `aux-tasks.txt` (A1 review). List only registered tasks: C2 throws on a wrong name. |
| 4 | U6 first night "2026-10-20 ... after cutover C" (DECISION_LOG 2026-10-15). | 10-20 now comes before C. | Re-date U6 to after a C PASS (earliest 04:10 on Fri 10-23), or record that it runs on 3.11.0 until C. Either way C2 disables it from C2 to C9b, and `Assert-NoU6At0035` only covers a 00:35 slot. |
| 5 | The calendar text: the header "cutover night is 00:30 on 10-17", G7's dated exception "C stays at 00:30 on 10-17", the §7a C row, and the state of play's "next C night 10-19/20". | Superseded by the owner's 10-19 ruling. | Master re-dates it (a DL row plus a state-of-play rewrite). **Not edited on this branch.** |
| 6 | Line citations | After N12: `snapshot_tracker.py` `LOOP_STATUS_PATH` :240 → :245, stop authorization :796 → :801, `--stop` :2413-2415 → :2418-2420; `maker_evidence_capture.py` parser :365-372 → :397-405 (still no stop verb), `store.seal()` :355 → :387; `maker_evidence_store.py` torn journal :143 → :179; `windows-qualification.yml` `python-version: '3.11.0'` :244 → :247 on master and :254 after N12. `supervisor.py` citations (≤ :1361) do not move, because N12 adds code only from :1578. | Behaviour is unchanged. §9 now cites the lane pin by its content. The other citations are evidence pointers and are left as they are. |
| 7 | `status.ps1` output | After N12 it also runs `venv python -m weather.reporting.market.capture_family_status`, which adds `CAPTURE_FAMILY` flags (a disabled family is informational) and a `CAPTURE_REGISTRY` warn. | No change: the baseline is taken per night at C0. At C8 a disabled family raises no flag. The new C9c bullet waits for the family's first fresh status, because `STARTING` would otherwise be a new flag. |
| 8 | `roll_verdict.ps1` closures | After N12 it reads `config/capture_families.json` `platform.roll_closures` fail-closed (a bad registry gives exit 1, UNDECIDABLE). Its parameters and exit codes are unchanged. | G3 treats exit 1 as a failure (runbook edit). |
| 9 | G5 lists the lease users. | Host replays are now planned (lever-5 after N12; item 337). | G5 now names host replays and research batches explicitly (runbook edit). |

## 3. Confirmed unchanged (both diffs)

- **No pin file changes.** `pyproject.toml`, `requirements*.txt`, lock, `setup.*`, `.python-version` and `pyvenv.cfg`
  are absent from both `origin/master..739c03eff` and `origin/master..44a8c50e9`. So these all stand: `$A\freeze-3110.txt`
  (masked), `pth-3110.txt`, `rtv-3110.json` (its direct dependencies come from `pyproject.toml`), the wheelhouse and
  its locks, `constants.json`, the verifier r2 sha `FE9F7A57…668D`, and the `Mask-Editable` regex (the editable line
  still names `weather_market`).
- **Kit dependencies untouched by N12 and #190:**
  - release and runtime: `release_artifacts.py`, `runtime_identity.py`, `capture_resource_gate.py`, `capture_recovery_check.py`;
  - ops scripts: `training_window.ps1`, `register_training_window.ps1`, `bounded_worktree_test_suite.ps1`,
    `quiet_window_merge.ps1`, every `integration_attempt_*.ps1`, `memory_guard_status_reader.ps1`,
    `register_maker_shadow_runner.ps1`, `register_daily_refresh.ps1`;
  - workers and serving: `execution_tape_supervisor.py`, `market_microstructure.py`, `observation_trigger.py`,
    `release_lifecycle_cli.py`, `release_serving.py`, `maker_shadow.py`;
  - live seals: `live_sdk_portability.py`, `international_live_wrapper_sealer.py`.

  `workload_admission.ps1` changes only the workstation offline allowlist (two modules added), so the lease
  functions in §6 are unchanged.
- **Wallet reader and journal pin:** no `wallet_reader_*` or `order_journal*` file is in either diff. The
  workstation reader and the `WeatherManualOrderJournal` five-file pin are unaffected.
- **Bounded suite:** the kit pins neither its sha nor `Assert-HostAdmission`. The G1 parameters are unchanged
  (`-InterpreterPath` :48, `-ExpectedInterpreterVersion` :52, `MaxRuntimeSeconds` :27). The 10-18 probe fix
  (`Get-ConfirmedHealthyCaptureWorkerCount` :543, used by `Assert-HostAdmission` :577) matters only to a B-R B2,
  where capture is running. Phase C runs no suite.
- **git.exe binding:** it is only used by B2. Re-read the host values (path, SHA-256, file version) if B-R runs.
- **STALE_CODE:** N12 rolls capture at its own merge (10-19/20). The C swap does not, because `venv` is outside the
  fingerprint. N12 also starts workers with BLAS threads capped at 1 (`supervisor.capped_worker_env`), and C7
  inherits that.

## 4. #190 is already inside N12

Chain-r3 merges `claude/nbm-parser-v2-refresh-20261013` (`770ec91d8`). The simulated post-#190 tree differs from
`739c03eff` only in `tests/operations/test_missing_information_admission.py` and
`tests/operations/test_workload_admission_script.py`, where the allowlist lists conflict. The non-test blobs
are identical, for example `nbm_input_regime.py` `6b15e9fd…` and `model_features.py` `456b9664…`. Once
re-merged on post-N12 master, #190 should therefore be **tests-only and roll-free**, and MG-1's dependency on
#190 is met by N12. Verify this on the Tuesday tip:
`git diff --stat <post-N12 master> <#190 tip> -- . ':!tests'` should print nothing, and `roll_verdict.ps1` should exit 0.

## 5. Re-takes and their order

1. **Night 10-19/20:** N12 lands (quiet-window merge).
2. **10-20, workstation:** check the #190 delta (section 4).
3. **Night 10-20/21: choose one.**
   - **(A, recommended)** Run B-R on the post-N12 HEAD. #190 does not land that night: its tests-only remainder
     lands after C. G3 then holds on 10-21/22 because HEAD equals the new qualified tip.
   - **(B)** Keep the #190 merge on 10-20/21, and the owner rules G3 for this night. The case for it is that the
     workstation is on 3.11.9 with identical pins (§5), the chain-r3 pregate passed there (22/22, 9496 passed,
     receipt `pg-739c03eff1e2-20261018T045220-105120`), and C6 runs an import smoke test. The residual risk is
     host-only 3.11.9 behaviour of the N12 code, and §R's automatic rollback is the backstop.
4. **Before C0 (master):**
   - re-take H3 and rebuild `aux-tasks.txt`;
   - write `q12b.txt` if a family task is registered;
   - leave `q12.txt` and `gap-overrun.txt` as recorded.
5. **At C0:** the G3 call names the tip actually qualified, and the status baseline is fresh.
6. **Not re-taken:** `freeze-3110`, `rtv-3110`, `pth-3110`, `oldhome-sha256`, the wheelhouse and its locks,
   `constants.json`, and the verifier sha. C1 and B-R prove the first and the wheelhouse mechanically.

## 6. The 10-21/22 night (and any B-R night) is exclusive

G5 requires that no other lease user and no task change touches that night. Check each of these against the night plan:
- the lever-5 final-vector host replay (master, after N12, from `4743a7048`) and the item 337 no-METAR replay;
- data layer v2 S2+S9+P1, "10-21 night": an 88a code change through an integration attempt, with an 88a restart
  at 00:30-01:00;
- S4 evidence host, "10-22 night": a new venv holder, `WeatherEvidenceHost`;
- the maker replay v2 transfer host block, "10-21" (exports until 03:15);
- a U6 registration, the training window and Stage B, held heads, and storage one-shots;
- any new task registration that starts the production venv between the last A1 review and C0.

## 7. Open questions

1. Option A or B in section 5, and where #190's remainder lands (master, owner).
2. Will `WeatherMakerEvidenceLowestTemperature` (and S4's `WeatherEvidenceHost`) be registered before C? If so,
   the owner records Q12b. Registering them after a C PASS is simpler.
3. Which calendar nights do "10-21 night" (S2+S9+P1, A9 transfer) and "10-22 night" (S4) mean? Neither may be the
   C night or a B-R night.
4. The U6 first night (row 4).
5. MG-1 window (D0 10-15, bound 10-16): does a 20-47 minute capture gap at about 01:15-02:00 local on 10-22 make
   10-22 non-countable? The owner accepted the gap inside 10-15..10-30 on 10-12, before the bound. This review read
   no evidence.
6. G4 and escalation: DL 10-13 says "advance GO + sleep, auto rollback"; DL 10-17 requires the owner's own GO in chat
   that night. Confirm who is reachable if §R escalates before 09:00.
7. G7: the LFC campaign was backlogged on 10-19 (relayed, no DL row yet). Confirm that no session is set for 10-22.
