# Open backlog — operational work with no owner

**Created 2026-08-08** by splitting it out of `STATE_OF_PLAY.md`, which had grown past its
current-state cap. That page answers *"what is happening right now?"*; this one answers *"what is
known-broken and unassigned?"* Neither belongs in the other.

**Not the same as [`../roadmap/active-backlog.md`](../roadmap/active-backlog.md)**, which is generated
from numbered roadmap items and tracks feature work. This file is hand-kept and tracks operational
defects and follow-ups that missions created and nobody picked up.

Ranked by risk to capture first, then correctness and waste. Remove an entry when it lands; move
measured history to `ESTABLISHED_FINDINGS.md` instead of leaving a completed item here. Log rotation
landed and is recorded in §8e there, so it is no longer an open item.

---

## 1. Supervisor hang-detection latency exceeds the fatal gap

The derived fatal capture gap is **15 minutes** (10-minute cadence × `tolerance=1.5`). A hung loop on
2026-08-08 took **~19 minutes** to be restarted, which is longer than the threshold that dooms the
day. **Detection latency must be below the fatal gap or the guard cannot save a day it notices.**
See `derived-rules-are-the-invisible-ones` — the relationship between these two numbers is written
nowhere and neither number looks wrong alone.

## 2. Start-race orphans are unreapable

The supervisor stops only the PID in its status file. `-09-45a` (merged 2026-08-08 17:57) fixes the
**maker** daily-start race; the general shape — a duplicate worker the supervisor cannot see or
reap — is not fixed. On 2026-08-07 a duplicate maker caused **430** memory-admission refusals and put
the streak day `AT_RISK`. `staleness_sweep.ps1` §12 detects it; the code fix is unowned.

## 3. A dead tombstone reads as live closure evidence

`data/snapshots/loop_status_supervisor_status.json` is `state=DEAD` with
`restart_budget_exceeded=6>=6`, but still carries a full `source_scope_files` list.
`roll_verdict.ps1` rejects it correctly; hand analysis did not. It is a trap for anyone deriving a
roll verdict manually — which is already forbidden, so this is defence in depth. Delete or mark
the tombstone through a reviewed evidence-preserving change.

## 4. The maker restarts all night outside its own evidence window

`daily_roll_status.json` carries `start_time_gate.start_after_local_time: "07:05"` and **no end
time**, while `evidence_classification` rejects any run started outside **07:00–20:00** local
(`counts_toward_live_forward_gate: false`, reason *"run started after active-day evidence window"*).

Overnight restarts are therefore **non-countable by construction**, but each still consumes restart
budget and writes a run folder that is later quarantined. This was verified not to block the 07:05
start; it is waste rather than a current outage. The gate needs an end time symmetric with the one
it already has.

## 5. Revert the Windows auto-reboot block after the build window

AU policy was changed on 2026-08-03 to stop an unattended reboot breaking the streak during the
release build window. **It is still in place.** Leaving it indefinitely means security updates stop
landing. Revert once the build window closes.

---

## Update this file when

An item lands (**remove it**), a new unowned defect is found (**add it, ranked**), or an item's rank
changes because the risk moved. If an item has been here for a month, either it is not real or it is
not actually unowned — say which.
