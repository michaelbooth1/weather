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

## 2. Revert the Windows auto-reboot block after the build window

AU policy was changed on 2026-08-03 to stop an unattended reboot breaking the streak during the
release build window. **It is still in place.** Leaving it indefinitely means security updates stop
landing. Revert once the build window closes.

---

## Update this file when

An item lands (**remove it**), a new unowned defect is found (**add it, ranked**), or an item's rank
changes because the risk moved. If an item has been here for a month, either it is not real or it is
not actually unowned — say which.
