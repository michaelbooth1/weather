# L6_G forward daily emission task: design note (lane L2, 2026-10-30)

Dated research note, not canonical guidance. It belongs to the L6_G forward screen,
`l6g_forward_prereg_FROZEN_2026-10-30.md` (D0 2026-10-31; branch `claude/l6g-prereg-freeze-20261030`).

- **Status:** built and tested, **NOT registered**. The owner said yes to a workstation scheduled task on 2026-10-30
  (relayed by the coordinator); the coordinator registers it. No agent registers it.
- **Code:** `tools/research/l6g_forward_daily.ps1` (the action) and `tools/research/register_l6g_forward_daily_task.ps1`
  (the registrar, with `-WhatIf`). Tests: `tests/operations/test_l6g_forward_daily_task.py`.

## Chain for one finished local date D

1. `mg2_inputs pull` + `receive` copy `\\192.168.1.247\mg2-inputs\<D>\` read-only into L6_G's own inbox
   `C:\t\l6g\forward\inbox\` with L6_G's own ledger `C:\t\l6g\forward\bundle_receipts.jsonl`. B's ledger
   (`C:\t\mg2\forward\`) is never read or written (prereg §3).
2. `mg2_inputs build` (pinned parser worktree) and `mg2_composite captured-nowcast --prev-root`, each through
   `workstation_heavy.ps1 -Queue`, into a fresh `C:\t\l6g\forward\work\<D>\<run>\`.
3. `l6g_forward_frame run` writes `frames\<D>\` and hands it to the emitter: `vectors\<D>.parquet` plus one row in
   `input_receipts.jsonl`, both exclusive-create.

Inputs are pinned:
- L6 state: `C:\t\l6g\forward\pins\l6_own_state_octdec.pkl` (sha256 800072c7…, checked by `captured-nowcast`).
- Coefficients: `pins\mg2_coefficients.json` (L6 part 07a67425…, checked by the builder).
- Frozen L6_G state: `state\l6g_state.json` (ae95686b…, checked by the emitter).
- Recorder manifest: `gefs\<D>\manifest.json` (pins checked by the emitter).

The pins copies are read-only.

## Schedule, and why

Local wall-clock daily triggers at 07:30, 10:30, 13:30, 16:30, 19:30 and 22:30. They are unzoned, so they follow the
clock across the 2026-11-01 fall-back.
- The capture host publishes D's bundle at about 04:15 local on D+1, with one retry at 07:00 (export receipts on the
  share: 2026-10-28 and 2026-10-29 both finished at 04:15).
- The GEFS recorder writes D's manifest at about 06:03 on D.
- 07:30 is the first slot after both. The later slots retry a late bundle. The last slot still lands before the
  receiver's deadline (23:59 local on D+1).

## Idempotence, refusals and backfill

- A date whose `vectors\<D>.parquet` exists is a no-op. The mutex and `MultipleInstances IgnoreNew` prevent overlap.
- Logged refusals for one date (`logs\daily_<yyyymmdd>.log`, `logs\runs.jsonl`, per-step child output in `logs\`),
  with nothing emitted:
  - bundle missing or not verified;
  - recorder manifest missing;
  - a pinned input missing;
  - any failed step;
  - a frame present without vectors (left for the operator; the builder never rewrites).
- Whole-run refusals:
  - the `STOP` file;
  - a module in the pinned worktree that is not at its pinned blob (emitter 3ecf3819, look 17539ca4, frame 75a587b0,
    `mg2_inputs` 045956fe, `mg2_composite` 8cff85ae).
- Point-in-time:
  - A bundle counts only if L6_G's receiver verified it by 23:59 on D+1, using the receiver's own deadline. After
    that the receiver records `late` or `missing`, and the date is never emitted.
  - Every later step reads only hash-pinned, as-of-capture inputs. A verified date that the task missed is therefore
    emitted on the next run, with the same content. The receipt's `emitted_utc` discloses the delay.
  - No date before 2026-10-31 is ever run (the emitter's own floor is 10-29).
- Principal: current user, Interactive / Limited, as for the GEFS and MOSMIX recorder tasks. An S4U session cannot
  use the stored share credential. The task therefore runs only while the user is logged on, and
  `StartWhenAvailable` covers a slot missed while the machine was asleep.

## Worktrees (not moved by agents)

- `C:\wt\l6g-daily-pinned`: detached at the reviewed tip of `claude/l6g-daily-emit-task-20261030` and
  `git worktree lock`ed. The wrapper re-checks the module blobs on every run.
- `C:\wt\l6g-parser-pinned`: detached at the parser pin 2e17ce0eb, locked. The builder refuses any other HEAD or a
  dirty tree.
