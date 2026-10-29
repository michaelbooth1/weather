# Workstation ping watchdog for the capture host (design; not registered)

Status: design and script only. Nothing is registered, started or reconfigured. Registration needs the owner's
explicit yes (section 5).

## 1. Why

On 2026-10-28 the capture host lost Wi-Fi when its AX201 driver dropped. Capture was off for about 67 minutes inside
the 12:00-18:00 graded window before anyone noticed. The host's own `health_watchdog.ps1` cannot report this: with no
network it can only write to its own disk. A second machine has to notice.

This watchdog runs on the 32 GB workstation. Every 5 minutes it probes the capture host, and it raises an alert
after 2 consecutive misses. So an outage is noticed in 5-10 minutes rather than at the next human look.

## 2. Probe

The script is `scripts/ops/ws_ping_watchdog.ps1`. One invocation is one pass.

1. **ICMP** to the capture host (default `192.168.1.247`): up to 3 echo requests, 1 s timeout each. Any reply means
   "up".
2. **TCP 22** (optional, `-TcpPort 22`; `0` disables it): only when ICMP fails, a 2 s connect to the SSH port. A
   connect also means "up". This covers a host whose firewall drops ICMP but which is otherwise alive.
3. **Own-network check:** if both fail, the workstation pings its own default gateway (lowest-metric `0.0.0.0/0`
   route).
   - If the gateway answers, the pass is a **miss** ("down").
   - If not, or there is no default route, the pass is `ws_offline`. The workstation itself is off the network, so
     this is neither a miss nor a recovery.

## 3. Miss, alert, reminder and recovery rules

| Pass | Effect |
| --- | --- |
| up | Clears the miss count. If an alert was open, emits **RECOVERED** with the outage length (since the first miss). |
| down | Adds 1 to the miss count. At `-MissThreshold` (2) consecutive misses, emits **ALERT** once. |
| down while alerting | No repeat, except a **REMINDER** once `-ReminderMinutes` (60) have passed since the last alert or reminder. |
| ws_offline | Changes nothing. It is logged. |

- **Repeat suppression** is the `alerting` flag in the state file. One outage gives one ALERT, at most one REMINDER
  an hour, and one RECOVERED.
- **A single miss never alerts.** A one-off dropped ping is noise at 5-minute spacing.
- **Exit code** is 2 on ALERT or REMINDER, else 0. The scheduler's last-run result then also shows an open alert.
- **Silence:** a pass that finds the previous pass more than `-GapMinutes` (15) old sets `watchdog_gap: true`, so
  holes in coverage (sleep, reboot) are visible in the log.

## 4. Alert channel and log

**What already exists.** The repository has no push or remote alert channel: no mail, ntfy, webhook or toast in
`scripts/ops`, `src` or `tools`.

- `health_watchdog.ps1` (capture host, every 15 minutes, S4U) writes `data\alerts\host_health_alerts.jsonl`, a
  latest-state file and `MORNING_BRIEFING.md` on the host's own disk.
- That convention (append-only jsonl under `data\alerts`, deduplicated, with a heartbeat) is reused here. The
  channel is not: nothing on the capture host is reachable when its network is down.

**This watchdog's channel:**

- **A local Windows toast** on the workstation, through the built-in WinRT `ToastNotificationManager` with
  PowerShell's own app id. There is no module and no download.
  - A toast is visible only in an interactive session. Hence the logon type in section 5.
  - Toast failures are recorded in the log line (`toast: "error: ..."`) and never fail the pass.
- **Files on the workstation**, under the checkout's `data\alerts\` (git-ignored local runtime state):
  - `ws_ping_watchdog.jsonl`: one line per pass. It rotates by rename at 16 MB, which is about 30 KB a day, so
    years.
  - `ws_ping_watchdog_state.json`: miss count, alert flag, down-since, last alert, last ok, last run. It is written
    atomically. A corrupt file restarts the count; the log keeps the history.
- A phone or remote channel would be a separate decision: a paid or third-party service, plus credentials. It is not
  proposed here.

## 5. Task Scheduler registration (for the owner; NOT run)

This is put to the owner as-is. It is run only after an explicit yes, from an ordinary (non-elevated) PowerShell on
the workstation, after this branch lands in the workstation's master checkout.

```powershell
$repo   = 'C:\Users\Michael\Documents\github\weather'
$script = Join-Path $repo 'scripts\ops\ws_ping_watchdog.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $repo `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -TargetHost 192.168.1.247 -TcpPort 22"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'WeatherWsPingWatchdog' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings
```

- **Removal:** `Unregister-ScheduledTask -TaskName 'WeatherWsPingWatchdog' -Confirm:$false`.
- **Interactive vs S4U.** Interactive runs only while the owner is logged on, but it can show the toast. S4U, as the
  host watchdog uses, would also run with nobody logged on, but it writes only to the log.
  - The recommendation is Interactive, because the toast is the only real alert channel.
  - If the owner prefers S4U, change `-LogonType` to `S4U` and accept log-only alerts.
- **Window flash.** `-WindowStyle Hidden` can still flash a console for a moment every 5 minutes in an Interactive
  task. If that is unwanted, wrap the action as `conhost.exe --headless powershell.exe ...` on Windows 11.
- **No `-WakeToRun`.** The watchdog must not wake a sleeping PC (section 7).
- No `-Force`, so it cannot silently overwrite a task of the same name.

## 6. Isolation: WeatherWalletReader and port 8765

- **Network:** outbound only. ICMP echo and one TCP connect to port 22 on the capture host, plus ICMP to the
  gateway. No listener, no inbound port, no firewall rule.
- **Not touched:** port 8765, the `WeatherWalletReader-*` firewall rules and the WeatherWalletReader process or task.
- **Code:** it imports no repository Python and no exchange or credential code. It reads no credential file and
  needs no environment variable.
- **Names:** the task name `WeatherWsPingWatchdog` and the `ws_ping_watchdog*` files under `data\alerts` collide
  with nothing existing.
- **Not run by agents:** the capture host's S4U guard targets agent-rooted process trees on that host. This task
  runs on the workstation, under Task Scheduler, not under an agent tree.
- **Roll-free:** a `.ps1` and docs, so landing it rolls nothing on the capture host.

## 7. Resource cost

- **CPU and memory:** one Windows PowerShell start every 5 minutes, about 1-3 s of CPU and about 60-80 MB, released
  at exit. The pass ends in at most about 9 s worst case (3 × 1 s ICMP, 2 s TCP, 3 × 1 s gateway ICMP) and is
  capped at 2 minutes by the task.
- **Network:** at most 7 small packets per pass.
- **Disk:** about 30 KB a day of log.
- **No interference with heavy work:** `workstation_heavy.ps1` slots are not used, and this is not heavy work.

## 8. Failure modes

- **Workstation asleep or hibernating.**
  - Nothing runs, so nothing is watched. `StartWhenAvailable` runs one pass on wake, and the gap is logged
    (`watchdog_gap`).
  - Mitigation, an owner decision: set the workstation's power plan to never sleep on AC, at least for 12:00-18:00.
    The task does not wake the PC.
- **Workstation reboot or logoff.**
  - Under Interactive, there are no passes until the owner logs on. The state file survives, so a miss count or
    open alert carries over.
  - Under S4U, passes continue after boot with no logon, but log only.
- **Workstation off the network** (its own Wi-Fi drops): passes become `ws_offline` and raise no false alarm. It is
  not a capture-host check either, so it is logged for review.
- **The capture host's IP changes** (DHCP lease or router change):
  - The watchdog sees a down host and ALERTs. That is a false alarm about capture, but a true alarm about the
    address.
  - Prevention: a DHCP reservation for the capture host's MAC on the router. That is an owner action, not done here.
  - After a change, re-register with the new `-TargetHost`. A hostname works too, if the router's DNS resolves it
    reliably.
- **The host answers ping but capture is dead.** This is out of scope: the probe is reachability only. Capture
  health stays with `health_watchdog.ps1` and `status.ps1` on the host.
- **ICMP blocked on the host:** the TCP 22 fallback covers it, as long as SSH listens there. If neither is open,
  every pass is a miss. Confirm one pass by hand before registering.
- **Toast suppressed** (Focus Assist or Do Not Disturb): the toast uses the `reminder` scenario, which stays on
  screen until dismissed, but Do Not Disturb can still hide it. The log and the task's exit code remain.

## 9. Verification

- `tests/operations/test_ws_ping_watchdog_script.py` runs the script on simulated probes only (`-SimulateProbe`,
  `-NowUtc`, `-NoToast`, a temporary `-StateDir`). It covers ALERT on the 2nd miss, no repeat, the 60-minute
  REMINDER, RECOVERED, `ws_offline` neither counting nor resetting, a single miss never alerting, and gap logging.
- No real probe, toast or task registration happens in tests.
- **Before registering,** the owner or an agent can run one real pass by hand:
  `.\scripts\ops\ws_ping_watchdog.ps1 -StateDir C:\t\wsping_trial -NoToast` prints one JSON line.
