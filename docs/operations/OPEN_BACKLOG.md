# Open backlog — operational work with no owner

> **HISTORICAL — dormant, not current authority.** Last edited 2026-08-14 (`git log`); it holds one
> item from 2026-08-08 and, by its own one-month rule, stopped being a live list in September.
> **Do not add to it and do not read it for what is broken today.** Live equivalents:
> `data/alerts/MORNING_BRIEFING.md` and `scripts\ops\status.ps1` (what is open right now),
> [`STATE_OF_PLAY.md`](STATE_OF_PLAY.md) (what matters now), and numbered roadmap items surfaced in
> the generated [`../roadmap/active-backlog.md`](../roadmap/active-backlog.md) (owned work). A new
> unowned operational defect becomes a numbered item.
>
> Disposition of the one item below: the supervisor fatal-gap repair was suite-proved on
> 2026-08-14 but **not live-timing-proved**, and
> [`ESTABLISHED_FINDINGS.md` §8l](ESTABLISHED_FINDINGS.md) keeps it open until a live
> stop-to-recovery interval is measured. §8l owns it now.

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
The relationship between these two numbers was written nowhere and neither number looks wrong
alone; the derived rule is now printed by the generated
[`OPERATING_REFERENCE.md`](OPERATING_REFERENCE.md).

---

## Update this file when

Do not — this file is dormant. If the hand-kept list is ever revived, remove the HISTORICAL banner
in the same change and fix the operations index entry. The original rule is kept for the record: an
item lands (remove it), a new unowned defect is found (add it, ranked); if an item has been here for
a month, either it is not real or it is not actually unowned — say which.
