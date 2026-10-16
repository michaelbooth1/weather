# Live Fill-Calibration Session-1 Runbook (DRAFT, 2026-10-16)

**Status: DRAFT, not yet reviewed or adopted.** Adds no rule: the signed pre-registration (PR), clarifications C and
D and the DECISION_LOG rows govern. This file revises the session-0 runbook
(`docs/research/live-fill-calibration-session0-runbook-2026-10-09.md` on origin/master, "RB" below) for the first
counted session, around the owner driver `python -m weather.market.lfc_cli session-run`
(`src/weather/market/lfc_session_driver.py`). It folds in the session-1 prep checklist of 2026-10-16 and the
should-fixes SF-1/SF-2 of the pin review
[lfc-pin-review-e27909a76-6bc6f2bec-2026-10-16.md](lfc-pin-review-e27909a76-6bc6f2bec-2026-10-16.md).
**Read when:** preparing or running a counted LFC session, or reviewing the driver.

**Session 1 schedule (owner 2026-10-16 14:28, DECISION_LOG):** Sun 2026-10-18, `go` 12:00 EDT (16:00Z); t24
(`--phase t24`) Sat 10-17 ~14:00 EDT (18:00Z); latest legal `go` 13:50 EDT. Fallback Mon 10-19, same times (t24 10-18
~14:00 EDT). Manual trading is paused from the start of session 1 until the last campaign lot settles (PR §5, owner
2026-10-16).

## 1. What changes from RB

- **Pin.** `6bc6f2bec` plus the driver commit(s) on `claude/lfc-session-driver-20261016`; the driver tip becomes the
  session-1 pin (`clean_preflight` refuses a dirty tree and `code_identity` binds the commit, so the driver cannot be
  dropped loose into a worktree). It needs a review of `6bc6f2bec..<driver tip>` (PASS) and a DECISION_LOG pin row
  naming the full sha. Worktree `C:\wt\lfc-pinned-<sha9>`, locked and detached (RB §3.0 commands).
- **No session-0 flags.** A counted `preflight`/`live` refuses `--session0 --run --event-slug --extra-conditions
  --shadow-scope` (`session0_flags_without_session0`); the driver refuses them before starting anything. No 88a extras
  copy, no `shadow-scope-union`, no event slugs.
- **One 360-min run**, size 40, unattended after `go`. New start gates in the pin: `session0_not_passed`,
  `session_cap`, `local_date_already_used`, `before_earliest_start`, `after_last_start_date`, `baseline_t24_age`
  (the t24 must be 20-30 h old at `live`), and t40 at most 90 min old.
- **Latest `go`.** Start + 360 min must end by 23:50Z (`past_hard_stop_2350z`, re-checked at the recorded start), so
  the latest `go` is **17:50Z = 13:50 EDT**. The driver prints the latest legal live start (the earlier of that and
  t24 + 30 h) before the prompt and stops before preflight if it has passed.
- **neg_risk (clarification D, D8) inverts.** Session 0 was screened to `neg_risk` false. "Session 1 is the first
  neg-risk signing", so a counted session may sign either exchange path under the unchanged PR §6 limits. The driver
  screens the printed condition's row in the latest PASS preflight `selection.json`: both tokens must carry a boolean
  `neg_risk`, equal on both; missing, `None`, non-boolean or mixed refuses (session 0: `false` only).
- **Per-spender allowance (pin review SF-1).** The pin's `collateral_allowance` check takes the maximum over all
  spenders, so a wallet approved only for the standard exchange passes and the first neg-risk post is rejected,
  spending a session and its date. Before `go` the driver reads the allowances the PASS preflight already journaled
  (`preflight_read` step `balances`; no new venue read, no approval call) and refuses unless every spender of the
  band's path covers the band cap 0.98 x size (39.2 pUSD at 40): neg-risk band = neg-risk exchange **and** neg-risk
  adapter; plain band = standard exchange.
- **Signing contract (SF-2).** SDK 0.6.0 picks the exchange for a neg-risk order from its own market lookup, and the
  signed order carries no exchange field, so our binding check cannot confirm it. The driver prints `neg_risk` for
  both tokens and the fee class before `go` and again from the session's own `selection.json` after the run. **A
  first post rejected on a neg-risk band (`submit_acknowledgment` or `exception`) is a signing-contract suspect:
  report it to master, do not retry, do not start another session for it.** The pack flags it
  (`neg_risk_signing_suspect`).
- **Reader spacing (session-0 finding).** `Wait-ReaderQuiet` before every reader-touching read; one
  `TimeoutError`/`timeout`/`refused` (or an `ERR` field in `wallet-verify`) is answered by one wait and one retry,
  then the step FAILs. `preflight` and `live` are never retried.
- **Wallet rule.** PR §5 "pause all manual trading from the start of session 1 until the last campaign lot settles" is
  the signed rule; the narrower session-0 window covered session 0 only. Recommended from the t24 on.
- **Halt table (RB §10)** gains the new start codes plus `panel_exclusion_required`, `panel_exclusion_write_failed`,
  `no_qualifying_band`, `treatment_size`, `capital_cap`, and the driver's own stop codes (§4).
- Session 0 nit N-4: any rerun keeps the plain `shadow_scope_YYYYMMDD.json` name.

## 2. Dates (proposed; owner decides, DL logistics row)

| Constraint | Value |
| --- | --- |
| Earliest | 10-18, after the session-0 PASS is on master |
| Last start | local date 2026-10-31 (`LAST_START_LOCAL_DATE`); 8 sessions on distinct local dates |
| Hard stop | start + 360 min <= 23:50Z, latest `go` 17:50Z = 13:50 EDT (EDT = UTC-4 through 10-31) |
| t24 | 20-30 h before `go`, the day before |
| Capture host | no cutover the night before or the night of a session (G7); the 8765 reader serves the capture host too: no reader restart or workstation reboot from t24 to the end of the post-run checks |

**Primary: Sun 2026-10-18, `go` 12:00 EDT = 16:00Z** (t24 Sat 10-17 14:00 EDT = 18:00Z, 22 h old at `go`; any `go`
between 10:00 and 13:50 EDT passes). **Fallback: Mon 10-19, same times.**

## 3. Gates before the session

| # | Gate | Who | Verify |
| --- | --- | --- | --- |
| G1 | Session-0 PASS record and DL row "LFC session 0 ATTESTED" on master | master | row on origin/master |
| G2 | Driver on this branch: fakes/tests PASS on the workstation (`workstation_heavy`), review of `6bc6f2bec..<driver tip>` PASS (it must check SF-1/SF-2), dry run (§5.2) PASS | workstation, reviewer | review doc; dry-run pack `stopped_reason=dry_run_complete` |
| G3 | Review `e27909a76..6bc6f2bec`: PASS (`lfc-pin-review-e27909a76-6bc6f2bec-2026-10-16.md`) | done | file on this branch |
| G4 | DL row for the session-1 pin = driver tip, full sha | master; owner logistics yes | DL row |
| G5 | Locked detached pin worktree; RB §3.2 prints `3.11.9`, pin paths, `0.6.0`, `econ_loaded=False` (the driver re-checks all of this) | workstation | driver `setup` PASS |
| G13 | Reader client config in the new pin's `config\local\wallet_reader_client.json` | **owner only** | driver `open_order_count` PASS |
| G14 | Workstation heavy freeze from T-60 until the post-run checks; no second slot during live | master, all WS agents | driver `Test-HostFree` lines |
| G15 | Windows Update paused (until 10-30); sleep off; toasts on | owner | Settings |
| G16 | Manual-trading pause (PR §5), no foreign open order, no position change after t40 | **owner** | DL row |
| G17 | Funding: available pUSD >= L_resting + reserve (<= 39.2) | owner | preflight PASS |
| G22 | Owner date as a DL row | owner | DL row |

## 4. The driver

One interactive PowerShell window in the pinned worktree, the runbook §2 environment
(`$env:PYTHONPATH = "$PIN;$PIN\src"`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`),
then one command per phase. `--expect-commit` is the full 40-hex pin sha.

```powershell
# T-22 h (day before): t24 snapshot + baseline
& $PY -m weather.market.lfc_cli session-run --expect-commit <pin sha> --phase t24
# Any time the t24 is valid (20-30 h old) and before the session: dry run to the go prompt; nothing is posted
& $PY -m weather.market.lfc_cli session-run --expect-commit <pin sha> --to-go-prompt
# T-40: the session
& $PY -m weather.market.lfc_cli session-run --expect-commit <pin sha>
```

What it runs, in order (each a child of the pinned CLI, cwd = the pin, nothing written into the pin):

1. **setup** (RB §3.1-3.3): pin HEAD equals `--expect-commit`; `git status --porcelain` empty; the worktree is
   `locked`; the pinned interpreter reports 3.11.9, the pin's `weather` and `lfc_cli` paths, `REPO_ROOT`, SDK 0.6.0,
   `econ_loaded=False`; the host-assignment line is `status=ASSIGNED host_match=True principal_match=True
   not_capture=True`.
2. **timing**: t24 age window and the latest legal live start, printed (§1).
3. **Test-HostFree**, **Get-OpenOrderCount = 0**, **Save-OwnerSnapshot t40**, **baseline --label t40** (= `t40_start`),
   **Compare-T40ToStart** PASS.
4. **Test-HostFree**, **preflight** (owner console; `owner_terminal_required` stays real) PASS.
5. **Test-HostFree**, **live** (owner console). The driver holds back live's output from the selection line until
   the screens pass: `SCREEN PASS condition=... event_slug=... fee_class=... neg_risk={...} allowed=[...]
   allowances_atomic={...}`. Only then does the owner see `Type: go <6 hex>`. On a refused screen the driver kills
   the live tree first and only then prints the `SCREEN REFUSED <code> ...` line; every later line of live's output
   (a `Type: go` line still in the pipe included) is dropped, so no go code or selection sha is ever shown (= RB
   Ctrl+C at the prompt: nothing posted). If live's output has not ended 10 s after the kill, the driver prints
   `LIVE STILL RUNNING — Ctrl+C now, type nothing`, records `live_still_running` in the pack and stops with
   `live_still_running_after_kill`: press Ctrl+C, type nothing, then RB §9. The driver never types or relays a
   phrase.
6. **after-run**: `session_end.json` (reason, `cleanup_ok`, `panic`, toast), the journal's submit expirations (one
   value), the session's own `selection.json` `neg_risk` and fee class (printed as `AFTER-RUN ...`),
   Get-OpenOrderCount = 0, `verify` PASS.
7. **verify**, **wallet-verify** PASS, final **baseline t40**, **Compare-T40ToStart** PASS,
   **Save-OwnerSnapshot after-session**.

Every reader-touching step (open-order count, baseline, verify, wallet-verify, snapshot reads) first waits for
`READER_QUIET` and retries once on a timeout/refused. The driver stops at the first FAIL or refusal and **never runs
`cancel-ours`**; on a stop after `live` started, or on Ctrl+C, it prints the RB §9 action.

**Ctrl+C.** Children run in a Windows job object with kill-on-close (fallback `taskkill /F /T`). Ctrl+C kills a
non-live child at once. During `live` the console also delivers Ctrl+C to live, which runs its own cleanup; the driver
waits up to 90 s for it, and a second Ctrl+C kills the tree. A first Ctrl+C never kills live, wherever it lands in
the driver's loop, and the job is not closed while that grace is pending. If the driver itself fails during the grace, it
keeps reading until live's output ends (at most the remaining grace) before it closes the job. Either way the pack is written with
`stopped_reason=owner_interrupt`; then follow RB §9.

**Evidence pack.** `<campaign root>\driver-<UTC stamp>\` holds only `pack.json` and `summary.txt`. The raw child
transcripts (reader JSON, live's table with `available_collateral`) are owner-private and go to
`<owner snapshot folder>\driver-transcripts\driver-<UTC stamp>\NN-<step>.txt`; the pack carries only each one's
sha256. Snapshot contents stay in the owner snapshot folder; only hash lines go to the pack. No balances, addresses
or positions in the pack folder, only counts and codes.

Driver stop codes (in addition to every pinned-CLI code it passes through): `owner_terminal_required`,
`pin_head_not_expected_commit`, `pin_worktree_not_clean`, `pin_worktree_not_locked`,
`pin_interpreter_or_imports_unexpected`, `pin_sdk_spenders_differ` (the pinned SDK's three exchange/adapter
addresses, printed at setup, differ from the driver's SF-1 spenders), `wrong_workstation_or_principal`, `baseline_missing_t24`,
`driver_t24_younger_than_20h_until_<time>`, `driver_past_latest_legal_live_start`, `host_not_free`,
`reader_<reason>`, `open_orders_<n>_expected_0`, `snapshot_<reason>`, `wallet_verify_reader_err`,
`STOP <reasons>` (compare), `neg_risk_*`, `allowance_*`, `allowance_evidence_unreadable`,
`session_directory_unknown`, `session_end_unreadable`, `cleanup_not_ok_or_panic`, `submit_expirations_differ`,
`owner_interrupt`, `live_still_running_after_kill`, `dry_run_complete` (the dry run's normal end).

## 5. Owner steps (T = `go`, primary 10-18 12:00 EDT)

1. **By 10-17 noon:** answer the open questions (§7). Master records the DL rows (G4, G22).
2. **10-17 ~13:30 EDT:** write the reader client config into the new pin (G13; type the token; never paste it to an
   agent). Confirm no open orders.
3. **10-17 14:00 EDT:** `session-run --phase t24`. From here: no manual trades, cancels, redeems or transfers (G16).
4. **10-18 before T-40 (e.g. 10:30 EDT), optional but recommended:** the dry run `session-run --to-go-prompt`. Read
   the SCREEN line and the `DRY RUN stopped at the go prompt: condition=... event_slug=... size=...` line (no go
   code or sha is shown); expect `stopped_reason=dry_run_complete`. It runs a real preflight, a t40 baseline and reader
   reads, so leave a gap before step 6 and never run it after T-40.
5. **10-18 by 11:00 EDT:** fund if needed (G17); sleep off, toasts on, Windows Update paused. Master confirms the
   heavy freeze and 88a health.
6. **10-18 11:20 EDT (T-40):** `session-run`. Watch the PASS lines.
7. **At the prompt (no later than 13:50 EDT):** read the SCREEN line (band, `event_slug`, fee class, `neg_risk` of
   both tokens, allowances) and live's printed table; type `go <6 hex>`. You may then leave; keep the workstation on.
8. **~T+6 h, on the toast:** the driver finishes the after-run block by itself. Paste `summary.txt` to master. On
   `PANIC`, a stop after live, or any open order: RB §9 (`cancel-ours`, then `reconcile`, `verify`, `wallet-verify`).
9. **If anything filled:** hold the lot to settlement, take the after-settlement snapshot, keep the pause.

There is no attest phrase in a counted session.

## 6. What to paste to master

The whole `summary.txt` block (it starts `LFC session driver pack ... sha256=`). It carries the RB §8 list adapted to a
counted session: `stopped_reason`, `stop_step`, `stop_code`, `pin_commit`, `session_kind`, `runs_planned`, `t24`
(file, sha256, window), `latest_legal_live_start_utc`, `host_free_lines`, `reader_quiet_lines`,
`snapshot_hash_lines`, `t40_start_line`, `compare_lines`, `preflight` (receipt folder, status), `selection_screen`
(condition, event_slug, fee class, `neg_risk` per token, allowances), `runs` (folder, session id, end reason,
`cleanup_ok`, `panic`, the `LFC-RESULT` line, toast, helper count after, submit expirations, the session's `neg_risk`
and fee class, `neg_risk_signing_suspect`), `verify_lines`, `wallet_verify_line`, `refusal_codes`, `action`. Add the
toast yes/no if the driver could not read it, and say whether you typed `go`.

## 7. Open questions (master / owner)

1. Owner availability Sun 10-18 12:00 EDT or Mon 10-19; which day is the DL row?
2. PR §5 pause until the last lot settles: kept as signed? Any change needs a signed clarification.
3. G7 reading for the C cutover at 00:30 10-17 relative to a 10-18 session.
4. The driver changes the session-1 pin, so it needs its own review and DL row. If G2 misses 10-17 noon: run by hand
   under RB on `6bc6f2bec` with the SF-1/SF-2 checks done manually, or slip?
5. Held T+1/T+2 weather positions excluding events (`no_qualifying_band` risk).
6. Whether `baseline` (venue + data-api reads) also timed out in session 0; the driver retries it once either way.
