# Capture memory pressure — September 7, 2026

Status: dated incident and repair record. All times are America/Toronto.

The owner requested a full production-PC systems check, then authorized all
necessary repairs. No live trading was requested. Capture, retention and
host-admission contracts remained in force.

## Incident and recovery

The snapshot loop's last clean iteration was 09:19:10. Windows Scheduler
started `\Microsoft\Windows\Defrag\ScheduledDefrag` at 09:20:55. During the
09:22–09:28 audit, free physical RAM was approximately 2.3–2.5 GiB. Snapshot
admission required 3.25 GiB for one worker and began refusing market captures.
At 09:27:49, the worker reported ten consecutive errors. At repair intake,
10:07:56, that had grown to 547 errors and all twelve markets were named.
CLOB, observation-trigger and public execution capture remained active.

The `defragsvc` service host held about 1.3 GiB of working set and Explorer
about 2.1 GiB. These are observed consumers, not independently proved leaks.
The combined repair was:

1. Export the exact ScheduledDefrag definition, disable the automatic
   maintenance task, stop its running instance, and stop `defragsvc` through
   Service Control Manager. The service stopped and the task read back Disabled.
2. Restart Explorer after a zero-read/zero-write I/O sample. Its replacement
   desktop-shell process initially held about 230 MiB. The direct child launch
   did not persist, so an on-demand Interactive/Limited Scheduler action restored
   the shell in the attended desktop session; it has no recurrence.
3. Verify a new clean snapshot iteration at **10:10:15**, zero consecutive
   errors, and more than 5 GiB free physical RAM. The capture worker did not
   require a restart.

The first audit's healthy process check was superseded by the later actual
capture errors. Likewise, `ensure_status=OK` alongside supervisor `ERRORING`
was not evidence of successful collection. The failure interval must remain
visible in retained capture evidence; this repair does not reconstruct it.

## Capacity and other repairs

- Disabled Windows hibernation and Fast Startup with `powercfg /hibernate off`.
  This reclaimed approximately 6.3 GiB from OS-reserved space; C: free space
  rose from about 23.5 to 29.8 GiB. No project evidence was deleted. AC sleep
  was already disabled. Hibernation can be restored with `powercfg /hibernate on`
  only after reviewing its disk cost and the unattended-host power policy.
- Retired the disabled `WeatherMaintenancePostBoot0823` registration after
  exporting it and verifying its August 23 PASS receipt, receipt SHA-256
  sidecar, wrapper SHA-256, action and zero task result. That wrapper deliberately
  self-disabled on completion. The current `WeatherBootRecovery` task remains
  enabled; its September 3 run succeeded. Historical receipts remain untouched.
- The accompanying monitoring change exposes the fresh memory guard's commit
  percentage and thresholds in the main digest, fails visibly on invalid/stale
  guard evidence, and classifies erroring capture loops as capture incidents.
  The watchdog's Stage-A window and capacity/durability advice now follow the
  existing host-load and retention contracts.

The drive-optimization hold is reversible from its retained XML, but must not
be re-enabled as opportunistic daytime maintenance. A reviewed bounded schedule
is still needed. Do not trade capture headroom for a blanket maintenance restart.

## Remaining boundaries

The bounded recent-ledger checker (400 tail lines per market) reported all
twelve markets missing August 28–31, September 1, September 4 and September 5.
This is 84 flagged market-dates, not a full historical ledger audit. September
6 and September 7 Stage A both deferred at `ingest_quality_gate`; the retained
September 6 admission receipt explicitly names host commit above its 70% limit.
The resource fix does not itself settle those dates or complete today's chain.

Free disk space remains below the ordinary heavy-work preflight minimum.
Both scheduled CLOB tiering jobs already succeeded this morning. Additional
tiering, historical settlement recovery, and production archive scans retain
their admitted-window requirements. The paused mirror is not verified archival
storage; encrypted off-site transfer and restore must be proved before any
exact-manifest source reclaim. No new archive upload or restore was claimed.

Windows also reported shadow-copy storage failures, a recent DNS-policy error,
UDP-port exhaustion warnings, and firmware-limited CPU speed. Current DNS
lookups and time synchronization passed. Those historical errors do not
justify resetting the active network or claiming an SSD failure; the SSD
reported Healthy and 43 C at the check. Hardware/firmware root causes and
off-site resilience remain open.

## Retained evidence

Production-local ignored/host-local evidence, not assumed in a clean checkout:

- `C:/Users/micha/ops/system-health-20260907-0927/REPORT.md` and sibling status
  snapshots and bounded Windows System event export.
- `C:/Users/micha/ops/system-health-20260907-0925-status.json` (initial digest).
- `C:/Users/micha/ops/capture-repair-20260907-1008/`: pre-repair snapshot,
  memory and daily-chain receipts; exported drive-optimization and retired
  post-boot task definitions; repair closeout evidence.

Source publication, tests and adoption are recorded in Git/CI and the repair
closeout receipt. A source patch or this narrative alone does not establish
that the new monitor has been adopted.
