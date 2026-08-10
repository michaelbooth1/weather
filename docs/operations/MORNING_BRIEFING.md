# Morning briefing

**The after-away read.** Unattended overnight wake agents append a dated section here. Newest
night at the top. If nothing needed you, the sections will be short — that is the intended outcome.

**How to read it:** every section leads with `OK`, `ATTENTION` or `ACTION NEEDED`. If any section
says **ACTION NEEDED**, its first sentence is the thing to do, in imperative form with the command.

---

## Night of 2026-08-09 → 2026-08-10

Three wakes are armed: **02:00**, **06:00**, **10:30** (`WeatherAgentOvernight0200/0600/1030`,
runner `C:\tmp\weather-overnight-0810\runner.ps1`, one-shot and self-disarming). The mechanism was
smoke-tested at 21:42 on 2026-08-09 — headless launch returned `SMOKE_OK`, exit 0.

**State at hand-off, 21:39 on 2026-08-09** — `status.ps1` verdict **ATTENTION**:

| | |
| --- | --- |
| Streak | 15/14, today **CLEAN** — 142 captures, 0.0 min max gap |
| Capture | all three loops at AboveNormal |
| Disk | 160.5 GB free, **−15.1 GB/day, ~11 days headroom** |
| Settled through | **2026-08-04** — 12 of 12 markets, 4 days behind |
| Git | clean, 0 unpushed |

**Open flags the wakes are watching:**

1. **The 05:15 roll-free merge ROLLED BACK on 2026-08-09 05:20** — snapshot heartbeat did not
   advance because capture was mid-outage. Nothing landed. **11 branches are pending**, including
   `-09-56a` and `-09-57a`, whose findings are already in canon.
2. **Settlement hole, 4 days.** `WeatherSettlementBackfill20260805` fires **05:30 on 08-10**; the
   other three are armed for 08-11, 08-12, 08-13. Each missed day needs its own backfill — the
   chain will not retry it.
3. **Disk at ~11 days.** Not tonight's problem; do not let it become a surprise.
4. Mirror restore-verify reported a problem file (standing, deprioritized).

**If a wake section is missing**, the task either did not fire or its guard aborted it. Check
`C:\tmp\weather-overnight-0810\logs\runner-<wake>-*.log` — guards abort on low memory (<2500 MB),
a concurrent agent, or a missing binary, and a skipped wake is by design safer than a wake that
starves capture.

---
