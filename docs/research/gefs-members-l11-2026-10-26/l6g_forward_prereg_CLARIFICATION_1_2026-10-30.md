# L6_G forward pre-registration: clarification 1 (late emission), 2026-10-30

- **MASTER RULING 2026-10-30, relayed by coordinator.** This is not an owner decision. Lane L2 wrote it down on
  the coordinator's instruction.
- **It clarifies** `l6g_forward_prereg_FROZEN_2026-10-30.md`, which lives beside it on branch
  `claude/l6g-prereg-freeze-20261030`. This file does not change that file or its sha256.
- **It does not change** any of the following in the frozen prereg: D0 (2026-10-31), N, countability, the coverage
  drop, the estimand, the keep/kill rule, the void conditions, the pins, or the look. It also changes nothing in B-1
  or MG-2.

## What it clarifies

The frozen prereg's §3 says the emitter runs "once per finished local date D >= 2026-10-29, never backfilled and
never rewritten (exclusive create)". Master's reading of that text:

1. **"Never backfilled" means no dates before D0.** No date before 2026-10-31 is ever emitted or counted.
2. **A date the receiver verified by its deadline may be emitted late.** The deadline is 23:59 local on D+1, the
   deadline used by `mg2_inputs receive` writing into L6_G's own bundle ledger. A late emission must meet all three
   conditions:
   - it uses the same hash-pinned inputs as an on-time emission: the verified bundle, the recorder manifest for D,
     the frozen state, the pinned L6 state and the pinned coefficients;
   - it runs the same pinned code (the §4 blobs and the frame builder blob);
   - its receipt row records the delay. The emitter writes `emitted_utc`, which shows the lateness against D.

   Emission stays exclusive-create: a date is never rewritten.
3. **A date not verified by its deadline is never emitted.** The receiver records it as late or missing.
4. **Every emission must exist before L6_G's look.** This includes late emissions. No outcome, label or price for
   that date may be read before its emission. Breaking this is §7 void condition 2.

## Where it is implemented

- The daily task wrapper `tools/research/l6g_forward_daily.ps1`, on branch `claude/l6g-daily-emit-task-20261030`,
  implements this reading. It is described in `l6g_forward_daily_task_2026-10-30.md` on that branch.
- The wrapper:
  - refuses dates before 2026-10-31;
  - emits a date only after L6_G's receiver has verified its bundle;
  - never re-runs a date whose vectors already exist.
