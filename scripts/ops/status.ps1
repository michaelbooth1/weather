# Overall host health check for the weather production PC -- one command that both
# GATHERS and INTERPRETS state, so a status update is a single tool call.
#
#   .\scripts\ops\status.ps1          # compact human digest (default)
#   .\scripts\ops\status.ps1 -Json     # machine-readable; exit 2 if any FLAG
#
# It delegates the streak to the authoritative checker (streak_status.py, which reads
# the ledger) and adds capture-loop priority, resources, the daily chain, git/push
# state, scheduled-task health, and recent alerts. Crucially it encodes what is
# EXPECTED vs anomalous (e.g. the daily chain exiting 0x2 = model-skill gates BLOCK
# pre-release, the tape backup being broken since Jun 30) so only genuine problems
# land in FLAGS. Pure host tooling, imports nothing from a capture loop -> roll-free.
# See docs/ops/streak-soak.md.
[CmdletBinding()]
param([switch]$Json)

$ErrorActionPreference = "SilentlyContinue"
$repo = "C:\Users\micha\Desktop\github\weather"
$py = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$flags = New-Object System.Collections.Generic.List[string]
$warns = New-Object System.Collections.Generic.List[string]

# ---- streak (delegate to the authoritative ledger-based checker) ----
$streak = $null
try { $streak = & $py (Join-Path $repo "scripts\ops\streak_status.py") --json | ConvertFrom-Json } catch {}
if ($null -eq $streak) { $flags.Add("streak checker failed to run") }
$today = $streak.today_health
if ($today -and $today.verdict -eq "AT_RISK") { $flags.Add("TODAY capture AT_RISK: $($today.reason)") }

# ---- capture workers + priority (persistent loop must be alive & AboveNormal) ----
# Match the FULL module path (as capture_priority_guard.ps1 does), NOT the short name,
# and SKIP the short-lived per-cycle "hot capture" subprocesses the loop spawns to do
# the actual fetch. Those children run at Normal for a few seconds by design (I/O-bound,
# transient) and the 5-min guard rarely coincides with them; counting them would falsely
# report "not all AboveNormal" every capture cycle. The persistent loop is what matters.
$caps = [ordered]@{
    "snapshot_tracker"      = "weather.collection.snapshot_tracker"
    "market_microstructure" = "weather.market.market_microstructure"
    "observation_trigger"   = "weather.operations.observation_trigger"
}
$transientMarks = @("--expected-runtime-fingerprint", "hot_capture", "result.json")
$capState = @{}
foreach ($c in $caps.Keys) { $capState[$c] = @() }
Get-CimInstance Win32_Process | Where-Object { $_.Name -in @("python.exe", "pythonw.exe") } | ForEach-Object {
    $cl = [string]$_.CommandLine
    $skip = $false
    foreach ($tm in $transientMarks) { if ($cl -like "*$tm*") { $skip = $true; break } }
    if ($skip) { return }   # per-cycle capture child, not the persistent loop
    foreach ($label in $caps.Keys) {
        if ($cl -like "*$($caps[$label])*") {
            $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
            if ($p) { $capState[$label] += [string]$p.PriorityClass }
            break
        }
    }
}
# S4U-owned process command lines are hidden from an ordinary interactive WMI
# query on this host.  An empty command-line match is therefore UNKNOWN, not
# DOWN.  Fall back to the capture workers' portable single-writer contract:
# fresh heartbeat + live PID + a writer lock owned by that same PID.  This is
# the same evidence the resource gate uses and still fails closed if any part
# is absent, stale, unreadable, or mismatched.
$portableCaps = [ordered]@{
    # Snapshot intentionally sleeps for nearly ten minutes between cycles. Keep this
    # aligned with capture_recovery_check and the bounded-suite admission contract: 12
    # minutes tolerates a complete normal cycle while remaining below the 15-minute streak
    # gap limit. CLOB and observation retain their three-minute contracts.
    "snapshot_tracker"      = @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720.0 }
    "market_microstructure" = @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180.0 }
    "observation_trigger"   = @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180.0 }
}
$captureRoot = Join-Path $repo "data\snapshots"
foreach ($label in $portableCaps.Keys) {
    if ($capState[$label].Count -gt 0) { continue }
    $spec = $portableCaps[$label]
    try {
        $status = Get-Content -LiteralPath (Join-Path $captureRoot $spec.Status) -Raw | ConvertFrom-Json
        $lock = Get-Content -LiteralPath (Join-Path $captureRoot $spec.Lock) -Raw | ConvertFrom-Json
        $pidValue = [int]$status.pid
        $ageSeconds = ((Get-Date) - [datetime]$status.last_heartbeat).TotalSeconds
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($pidValue -gt 0 -and [int]$lock.pid -eq $pidValue -and $process -and
            $ageSeconds -ge 0 -and $ageSeconds -le [double]$spec.MaxAge) {
            $priority = [string]$process.PriorityClass
            # PriorityClass can be hidden with the command line under S4U.
            # The separately scheduled priority guard owns re-assertion; this
            # fallback proves liveness rather than inventing a priority value.
            if (-not $priority) { $priority = "PortableHealthy" }
            $capState[$label] += $priority
        }
    }
    catch { }
}
foreach ($c in $caps.Keys) {
    if ($capState[$c].Count -eq 0) {
        $flags.Add("capture loop DOWN: $c")   # a dead capture loop is streak-critical
    }
    else {
        $low = @($capState[$c] | Where-Object { $_ -notin @("AboveNormal", "High", "RealTime", "PortableHealthy") })
        if ($low.Count -gt 0) {
            $warns.Add("$c not all AboveNormal ($($capState[$c] -join ',')) - guard re-asserts within 5 min")
        }
    }
}

# ---- auxiliary public execution tape (economics evidence, not streak grading) ----
# This producer is optional until its task is explicitly registered. Once
# armed, status/lock/PID/supervisor identity must agree just like the core
# loops. Its failure loses irreplaceable forward market-path evidence, but it
# does not relabel the three-worker weather-capture streak.
$executionTapeState = [ordered]@{
    armed = $false; task_state = $null; process_healthy = $null
    capture_state = $null; evidence_integrity = $null; price_path_usable = $null
    heartbeat_age_seconds = $null; pid = $null
}
$executionTapeTask = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction SilentlyContinue
if ($executionTapeTask) {
    $executionTapeState.armed = [string]$executionTapeTask.State -ne "Disabled"
    $executionTapeState.task_state = [string]$executionTapeTask.State
}
if ($executionTapeState.armed) {
    try {
        $executionStatus = Get-Content -LiteralPath (Join-Path $captureRoot "execution_tape_status.json") -Raw | ConvertFrom-Json
        $executionLock = Get-Content -LiteralPath (Join-Path $captureRoot ".execution_tape_status.json.writer.lock") -Raw | ConvertFrom-Json
        $executionSupervisor = Get-Content -LiteralPath (Join-Path $captureRoot "execution_tape_supervisor_status.json") -Raw | ConvertFrom-Json
        $executionPid = [int]$executionStatus.pid
        $executionProcess = Get-Process -Id $executionPid -ErrorAction SilentlyContinue
        $executionAge = ((Get-Date) - [datetime]$executionStatus.last_heartbeat).TotalSeconds
        $executionTapeState.pid = $executionPid
        $executionTapeState.heartbeat_age_seconds = [math]::Round($executionAge, 1)
        $executionTapeState.capture_state = [string]$executionStatus.state
        $executionTapeState.evidence_integrity = [string]$executionStatus.evidence_integrity
        $executionTapeState.price_path_usable = [bool]$executionStatus.price_path_evidence_usable
        $executionTapeState.process_healthy = [bool](
            $executionPid -gt 0 -and [int]$executionLock.pid -eq $executionPid -and
            $executionProcess -and $executionAge -ge 0 -and $executionAge -le 180 -and
            [string]$executionSupervisor.ensure_status -eq "OK" -and
            [bool]$executionSupervisor.runtime_identity_matches_current
        )
        if (-not $executionTapeState.process_healthy) {
            $flags.Add("public execution-tape producer is armed but its process/lock/identity contract is unhealthy")
        }
        elseif ($executionTapeState.evidence_integrity -eq "BLOCKED_EVIDENCE_LOSS") {
            $flags.Add("public execution-tape evidence integrity is BLOCKED_EVIDENCE_LOSS")
        }
        elseif (-not $executionTapeState.price_path_usable) {
            $warns.Add("public execution-tape producer is alive but complete price-path evidence is not currently usable ($($executionTapeState.capture_state))")
        }
    }
    catch {
        $executionTapeState.process_healthy = $false
        $flags.Add("public execution-tape producer is armed but its status contract is unreadable")
    }
}

# ---- resources ----
$os = Get-CimInstance Win32_OperatingSystem
$freeRamGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$totRamGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$freeDiskGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($freeRamGB -lt 1.5) { $flags.Add("LOW RAM: $freeRamGB GB free (streak-critical)") }
elseif ($freeRamGB -lt 2.5) { $warns.Add("RAM tightening: $freeRamGB GB free") }
if ($freeDiskGB -lt 25) { $flags.Add("LOW DISK: $freeDiskGB GB free") }
elseif ($freeDiskGB -lt 60) { $warns.Add("disk headroom low: $freeDiskGB GB free") }

# Resource headroom alone does not reveal an overlapping heavyweight job. The shared
# file-handle lease is authoritative; stale owner JSON without a live handle is not active.
$heavyWorkload = $null
try {
    . (Join-Path $repo "scripts\ops\workload_admission.ps1")
    $heavyWorkload = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $repo
    if ($heavyWorkload.Active) {
        $ownerName = [string]$heavyWorkload.Owner.workload
        $ownerPid = [int]$heavyWorkload.Owner.pid
        $warns.Add("heavy workload lease active: $ownerName (pid $ownerPid)")
    }
}
catch { $flags.Add("heavy-workload lease state could not be read") }

# Free space is a point-in-time number and tells me nothing about how long I have. The
# tape/CLOB history means "195 GB free" can be comfortable or two weeks from an outage
# depending on the slope, so keep a cheap sample trail and report the 24h burn. Sampling
# Get-PSDrive costs nothing -- deliberately NOT a recursive size walk of data\, which has
# starved capture before (see the codex-scan hazard) and must never run from a monitor.
$diskDelta = $null
$diskDaysLeft = $null
try {
    $trail = Join-Path $repo "data\alerts\disk_free_trail.jsonl"
    $old = @()
    if (Test-Path $trail) { $old = @(Get-Content $trail -Tail 400 | Where-Object { $_ }) }
    $cut = (Get-Date).AddHours(-24)
    $ref = $null
    foreach ($line in $old) {
        try {
            $s = $line | ConvertFrom-Json
            if ([datetime]$s.ts -le $cut) { $ref = $s }   # newest sample at least 24h old
        }
        catch {}
    }
    if ($ref) {
        $hrs = ((Get-Date) - [datetime]$ref.ts).TotalHours
        if ($hrs -gt 0) {
            $diskDelta = [math]::Round((($freeDiskGB - $ref.free_gb) / $hrs) * 24, 1)   # GB/day, negative = filling
            if ($diskDelta -lt 0) { $diskDaysLeft = [math]::Round($freeDiskGB / [math]::Abs($diskDelta), 0) }
        }
    }
    $new = @($old) + @(([ordered]@{ ts = (Get-Date).ToString("o"); free_gb = $freeDiskGB } | ConvertTo-Json -Compress))
    Set-Content -Path $trail -Value ($new | Select-Object -Last 400) -Encoding utf8
}
catch {}
if ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 21) {
    $flags.Add("disk filling at $([math]::Abs($diskDelta)) GB/day - about $diskDaysLeft days of headroom left")
}
elseif ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 60) {
    $warns.Add("disk filling at $([math]::Abs($diskDelta)) GB/day - about $diskDaysLeft days left")
}

# ---- system clock ----
# CLOB heartbeats, order TTLs, evidence ordering, and scheduled one-shots all trust the
# Windows clock. W32Time is trigger-start on this workgroup host, so a stopped service is
# not itself a failure. Use the bounded Time-Service event stream as a fallback, but
# prefer the live w32tm last-success timestamp when the service is already running.
# The event stream can lag a successful resync by more than a day on this host.
$clockService = $null
$clockLastSync = $null
$clockSyncAgeH = $null
$clockSource = $null
$clockSynchronized = $null
try {
    $clockService = Get-Service -Name W32Time -ErrorAction Stop
    $syncEvent = Get-WinEvent -FilterHashtable @{
        LogName = "System"
        ProviderName = "Microsoft-Windows-Time-Service"
        Id = 35, 37
        StartTime = (Get-Date).AddDays(-7)
    } -MaxEvents 1 -ErrorAction Stop
    if ($syncEvent) {
        $clockLastSync = [datetime]$syncEvent.TimeCreated
        $clockSyncAgeH = [math]::Round(((Get-Date) - $clockLastSync).TotalHours, 1)
    }
    if ($clockService.Status -eq "Running") {
        $clockStatusText = ((& w32tm.exe /query /status 2>&1) -join "`n")
        $clockQueryExit = $LASTEXITCODE
        $sourceMatch = [regex]::Match($clockStatusText, "(?m)^Source:\s*(.+?)\s*$")
        $liveSyncMatch = [regex]::Match(
            $clockStatusText,
            "(?m)^Last Successful Sync Time:\s*(.+?)\s*$"
        )
        if ($sourceMatch.Success) { $clockSource = $sourceMatch.Groups[1].Value.Trim() }
        if ($clockQueryExit -ne 0 -or -not $sourceMatch.Success) {
            $clockSynchronized = $false
            $clockSource = "unavailable"
        }
        else {
            $clockSynchronized = -not (
                $clockStatusText -match "Leap Indicator:\s*3" -or
                $clockStatusText -match "Source:\s*Local CMOS Clock"
            )
            $liveSync = [datetime]::MinValue
            if ($liveSyncMatch.Success -and
                [datetime]::TryParse($liveSyncMatch.Groups[1].Value.Trim(), [ref]$liveSync)) {
                $clockLastSync = $liveSync
                $clockSyncAgeH = [math]::Round(((Get-Date) - $clockLastSync).TotalHours, 1)
            }
        }
    }
}
catch { }
if ($clockSynchronized -eq $false) {
    $flags.Add("system clock is not synchronized (source $clockSource)")
}
elseif ($null -eq $clockLastSync) {
    $flags.Add("system clock has no successful Windows Time event in 7 days")
}
elseif ($clockSyncAgeH -gt 24) {
    $flags.Add("system clock last received valid time $clockSyncAgeH hours ago")
}
elseif ($clockSyncAgeH -gt 12) {
    $warns.Add("system clock last received valid time $clockSyncAgeH hours ago")
}

# ---- daily chain ----
$chain = $null
$cf = Join-Path $repo "data\backtest\daily_refresh_status.json"
if (Test-Path $cf) { try { $chain = Get-Content $cf -Raw | ConvertFrom-Json } catch {} }
$chainStatus = if ($chain) { [string]$chain.status } else { "?" }
$chainTerm = if ($chain -and $chain.terminal) { "terminal" } else { "running/unknown" }
$chainTaskResult = $null
try {
    $chainTaskInfo = Get-ScheduledTaskInfo -TaskName "WeatherDailySettlementPromotionRefresh"
    $chainTaskResult = "0x{0:X}" -f $chainTaskInfo.LastTaskResult
} catch {}
# A `critical` run with every step OK is NOT a broken chain: it is the production-readiness
# gate correctly reporting that no release pointer exists yet, which is the standing
# pre-release state (2026-07-26: 24/24 steps ok, SLA pass, 69 blockers led by
# active_release_verification_failed). Reporting that as breakage is the same false-positive
# trap as the old 0x2 exit code, so name what it actually means.
$chainGate = $null
if ($chain -and $chain.production_readiness) {
    $pr = $chain.production_readiness
    if ([string]$pr.status -eq "SKIPPED") {
        # A SKIPPED readiness gate carries `reason` + `pipeline_status`, NOT stage/
        # blocker_count/first_blocker. The generic format below therefore rendered it as
        # "readiness SKIPPED/, 0 blockers -> " -- three empty fields and a zero, which reads
        # as benign. It is the opposite: SKIPPED means the gate never ran at all because the
        # pipeline upstream of it did not succeed. Name that reason. (2026-08-03.)
        $chainGate = "readiness SKIPPED - {0} (pipeline {1})" -f [string]$pr.reason, [string]$pr.pipeline_status
    }
    else {
        $chainGate = "readiness {0}/{1}, {2} blockers -> {3}" -f [string]$pr.status, [string]$pr.stage,
        [int]$pr.blocker_count, [string]$pr.first_blocker.code
    }
}
# Every step can be `ok` while the run still did not succeed. A step's STEP status only says
# it EXECUTED; its PAYLOAD carries the verdict, and the two disagree routinely. On 2026-08-03
# all 23 steps were `ok` and the chain still terminated `deferred /
# upstream_pipeline_not_successful`, because live_variant_settlement_scorecard,
# hourly_model_performance, ten_minute_model_performance, rollup_freshness and
# trading_evidence were each BLOCK inside $chain.summary. Reading step status alone says
# "the chain is healthy" and is wrong -- surface the payload verdicts too.
$chainBlocked = $null
if ($chain -and $chain.summary) {
    $blocked = @($chain.summary.PSObject.Properties |
        Where-Object { $_.Value -and [string]$_.Value.status -eq "BLOCK" } |
        ForEach-Object { $_.Name })
    if ($blocked.Count -gt 0) { $chainBlocked = "{0} step(s) BLOCK in payload: {1}" -f $blocked.Count, ($blocked -join ", ") }
}
# Name the failing STEP and its reason. A bare "error" costs a manual dig through
# daily_refresh_status.json every single time, which is exactly what this script exists
# to avoid (2026-07-24: "error" was maker_paper_input_budget_exceeded, 20 min to find).
$chainFail = $null
if ($chain -and $chain.steps) {
    $bad = @($chain.steps | Where-Object { $_.status -and $_.status -notin @("ok", "skipped") })
    if ($bad.Count -gt 0) {
        $f = $bad[0]
        $why = [string]$f.result.reason
        if (-not $why) { $why = [string]$f.error }
        if (-not $why) { $why = [string]$f.result.status }
        if (-not $why) { $why = [string]$f.status }
        # A deferral is the resource gates working as designed (heavy steps refusing to run
        # beside live capture), not a fault. Say so, or every quiet-window-bound run looks broken.
        # WHEN it failed matters as much as what failed: a step that broke this morning and
        # was fixed this afternoon still sits in this file until the next run, so an ageless
        # "FAILING" reads as live breakage (2026-07-25: the MemoryError shown here predated
        # its own budget fix by 4.5h). Always say how old the failure is.
        $failAge = ""
        $stepFin = $null
        try {
            if ($f.finished_at_utc) {
                $stepFin = ([datetime]$f.finished_at_utc).ToLocalTime()
                $failAge = " [{0:HH:mm}, {1:N1}h ago]" -f $stepFin, ((Get-Date) - $stepFin).TotalHours
            }
        }
        catch {}
        if ([string]$f.status -eq "deferred") {
            $chainFail = "deferred at {0} ({1}) - heavy steps wait for a quieter host" -f $f.name, $why
        }
        else {
            $chainFail = "FAILING {0}{1} -> {2}" -f $f.name, $failAge, $why
            $warns.Add("chain step $chainFail")
        }
    }
}
# `terminal` describes the LAST completed run and goes stale the moment a resume starts,
# so trust the live step state instead: a running step means a run is in flight now.
if ($chain -and $chain.current_step -and [string]$chain.current_step.status -like "running*") {
    $chainTerm = "RUNNING NOW: $($chain.current_step.name)"
    $chainFail = $null
}
elseif ($chain -and -not $chain.terminal) {
    $chainTerm = "running/unknown"
}

# ---- settlement holes (the CONSEQUENCE, not the event) ----
# Everything above watches the chain as an event: which step failed, what the task
# returned. None of it watches the thing that actually costs us anything -- whether a
# target date ended up settled. Those are different questions, and on 2026-08-06 they
# gave different answers: the failing step was a MEDIUM standing note while 2026-08-05
# went unsettled in all 12 markets and nothing said so.
#
# The event is also transient and the hole is not. Each chain run settles only
# yesterday, so a missed day is never retried by the next run -- it needs an explicit
# backfill (scripts\ops\chain_recovery_run.ps1). A hole therefore compounds silently
# while the daily "chain ok" signal returns to normal the very next morning.
#
# Read the tail rather than the whole ledger: toronto's is large and this script runs
# every 15 minutes beside live capture. Revisions append, so scan a window and take the
# max rather than trusting the final line.
$settleHole = $null
$settleRoot = Join-Path $repo "data\settlements"
if (Test-Path $settleRoot) {
    # 2026-08-10: this was a MAX-DATE check that read only `target_date`, and it went blind.
    # The 08-05 backfill appended records for 08-06/08-08/08-09 that settled NOTHING
    # (settlement_source "none", missing_settlement, null high). Those satisfied a
    # target_date-only test, so every market's max became 08-09 and the flag could not fire
    # while three dates sat empty. Two defects, both fixed here:
    #   1. A record only counts as SETTLED if it actually settled - source and high present.
    #   2. Max-date can never see an INTERIOR hole (08-06 empty while 08-07 settled), so
    #      scan the whole recent window per date instead of tracking a maximum.
    # PowerShell 5.1 Get-Content -Tail rescans each ledger from byte zero and ConvertFrom-
    # Json is disproportionately slow on these large records. One Python process seeks
    # backward and parses only the requested suffix for every market.
    $windowDays = 14
    $settlementCheck = $null
    try {
        $settlementRaw = @(& $py -m weather.operations.settlement_hole_check `
            --repo-root $repo --window-days $windowDays --tail-lines 400 --json)
        if ($LASTEXITCODE -eq 0) {
            $settlementCheck = (($settlementRaw -join "`n") | ConvertFrom-Json)
        }
    }
    catch {}
    if ($null -eq $settlementCheck) {
        $flags.Add("settlement-hole checker failed to run")
    }
    elseif (-not $settlementCheck.ok) {
        $flags.Add("settlement-hole checker could not read every ledger: $(@($settlementCheck.errors) -join ', ')")
    }
    elseif (@($settlementCheck.holes).Count -gt 0) {
        $holes = @($settlementCheck.holes)
        $worst = $holes[0].date
        $dates = ($holes | ForEach-Object { $_.date }) -join ", "
        $settleHole = "SETTLEMENT HOLE: {0} date(s) unsettled in the last {1} days [{2}] - worst {3}, up to {4} of {5} market(s) - each needs an EXPLICIT per-date backfill; the next chain run will not retry it" -f `
            $holes.Count, $windowDays, $dates, $worst, ($holes | Measure-Object -Property markets -Maximum).Maximum, $settlementCheck.market_count
        $flags.Add($settleHole)
    }
}

# ---- git / push ----
$unpushed = & git -C $repo rev-list --count origin/master..master 2>$null
if (-not $unpushed) { $unpushed = "?" }
$dirty = @(& git -C $repo status --porcelain 2>$null)
$dirtyCount = ($dirty | Where-Object { $_ }).Count
$lastCommit = & git -C $repo log -1 --format="%h %s" 2>$null
if (($unpushed -ne "?") -and ([int]$unpushed -gt 0)) { $warns.Add("$unpushed commit(s) unpushed (run WeatherOneShotPush)") }

# ---- scheduled tasks (classify against what is EXPECTED) ----
# Tasks that exit non-zero BY DESIGN pre-release, and tasks intentionally disabled.
$expNonZero = @{
    # 0x4B = the repository-owned wrapper reached/refused the 11:55 protected-window
    # deadline and its kill-on-close Job tore down the delegated child tree. The OS-held
    # workload lease is the ownership signal; stale JSON/lock text is diagnostic residue.
    "WeatherDailySettlementPromotionRefresh" = @("0x2", "0x4B")
    "WeatherEveningEvidenceRefresh"          = @("0x2")   # evidence gates BLOCK
    "WeatherTrainingWindow"                  = @("0x2")   # no promotion pre-release
    # 0x41306 = we terminated a wedged push. Pushes need an interactive logon session,
    # so this task legitimately fails when nobody is logged on; the honest health signal
    # is the unpushed-commit count below, not this exit code.
    "WeatherOneShotPush"                     = @("0x1", "0x0", "0x41306")
    # These two are MONITORS: their exit code is their verdict, not their health.
    # staleness_sweep.ps1:385  exit 1 = one or more WARN, exit 2 = one or more CRITICAL
    # health_watchdog.ps1:199  exit 2 = top severity CRITICAL
    # Flagging those as "unexpected" reported the smoke detector as the fire: on 2026-08-07
    # two of six FLAGS were these, on a day that also had a real capture failure to find. The
    # findings themselves are surfaced by their own reports, which are the daily reads.
    "WeatherStalenessSweep"                  = @("0x1", "0x2")
    "WeatherHostHealthWatchdog"              = @("0x2")
}
# The taker was PAUSED by operator decision 2026-08-07 to focus 100% on the maker
# (docs/operations/taker-paused-and-pruned-2026-08-07.md). Both tasks are deliberately
# Disabled; flagging them daily is noise. Re-enable BOTH to restart the taker.
# The off-host mirror was PAUSED by operator decision 2026-08-12 to keep this host's
# resources on capture stability (docs/operations/mirror-paused-2026-08-12.md). These three
# stay silent HERE because the mirror block below raises exactly one warn that carries the
# age of the frozen copy -- one voice for the pause, not four.
$expDisabled = @(
    "WeatherNightlyRetrainValidatePromote", "WeatherAgentQuietWindow",
    "WeatherTakerBotDailyRoll", "WeatherTakerBotDailyRollSupervisor",
    "WeatherDataMirror", "WeatherMirrorRestoreVerify", "WeatherOneShotMirror",
    # Legacy host-local queue drivers lack immutable expected-tip bindings. They stay off
    # until the repository-owned exact-tip queue replaces them. The -09-69a suite is also
    # review-blocked and must not be re-armed from its obsolete wrapper.
    "WeatherMergeQueueDriver", "WeatherMergeSensitiveDriver", "WeatherSuite0969a",
    # This operator hold remains visible through a dedicated warning below. Keeping it in
    # the generic anomaly path as well called the same deliberate state "unexpected".
    "WeatherEveningEvidenceRefresh"
)
# A temporary training hold is expected only while one exact, enabled, self-disabling
# re-enable action is visibly armed for the next integration night. The old 12-hour
# horizon contradicted a task legitimately armed the prior morning for 04:20 the next day.
# Thirty hours covers that operating cadence without letting an abandoned far-future task
# silence the recurring-window alarm. Action, trigger, identity, and time are all checked:
# a similarly named task or an action with extra commands cannot suppress the FLAG.
$trainingReenableNow = Get-Date
$trainingReenableDeadline = $trainingReenableNow.AddHours(30)
$trainingReenable = @(Get-ScheduledTask -TaskName "WeatherTrainingWindowReenable*" -ErrorAction SilentlyContinue |
    Where-Object {
        $candidate = $_
        if ([string]$candidate.State -eq "Disabled" -or [string]$candidate.TaskPath -ne "\") {
            return $false
        }
        $candidateActions = @($candidate.Actions)
        $candidateTriggers = @($candidate.Triggers | Where-Object {
                $_.CimClass.CimClassName -eq "MSFT_TaskTimeTrigger" -and -not $_.Repetition.Interval
            })
        if ($candidateActions.Count -ne 1 -or $candidateTriggers.Count -ne 1) {
            return $false
        }
        $candidateAction = $candidateActions[0]
        $expectedExecutable = Join-Path $PSHOME "powershell.exe"
        $expectedArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"Enable-ScheduledTask -TaskName 'WeatherTrainingWindow'; Disable-ScheduledTask -TaskName '$([string]$candidate.TaskName)'`""
        if ([string]$candidateAction.Execute -ine $expectedExecutable -or
            [string]$candidateAction.Arguments -cne $expectedArguments) {
            return $false
        }
        $info = $candidate | Get-ScheduledTaskInfo
        $info -and $info.NextRunTime -gt $trainingReenableNow -and
            $info.NextRunTime -le $trainingReenableDeadline
    })
if ($trainingReenable.Count -gt 0) {
    $expDisabled += "WeatherTrainingWindow"
    $warns.Add("WeatherTrainingWindow is intentionally held for tonight; an automatic re-enable is armed")
}
$taskCount = 0
$interactiveTasks = 0
$evidenceRefreshHeld = $false
$sensitiveDriverNextRun = $null
$armedQuietMerges = New-Object System.Collections.Generic.List[psobject]
# Work that is ARMED but has not happened yet is invisible to every other check here: a
# one-shot scheduled for tonight can be deleted, disabled or silently mis-scheduled and
# nothing would say so until the morning it fails to have run. Surface the queue instead.
# List[psobject], not List[object]: `@($list)` throws "Argument types do not match" for a
# generic List[object] on this host. The -Json path only survives it because a pipeline
# enumerates the list first, which is luck rather than design.
$upcoming = New-Object System.Collections.Generic.List[psobject]
Get-ScheduledTask | Where-Object { $_.TaskName -like "Weather*" } | ForEach-Object {
    $taskCount++
    $ti = $_ | Get-ScheduledTaskInfo
    $res = "0x{0:X}" -f ($ti.LastTaskResult)
    $st = [string]$_.State
    $name = $_.TaskName
    if ($name -eq "WeatherMergeSensitiveDriver" -and $st -ne "Disabled" -and $ti.NextRunTime) {
        $sensitiveDriverNextRun = [datetime]$ti.NextRunTime
    }
    # A task due soon on a one-shot trigger is armed work -- the quiet-window merge, a
    # chain recovery run. That is exactly what I want to see queued.
    #
    # Keying this on "never run" (0x41303) alone was wrong and hid real armed work: RE-ARMING
    # an existing one-shot leaves its last result 0x0, so it vanished from this list. Caught
    # 2026-07-27, when the merge task was re-pointed at a new branch for 01:15 and did not
    # appear. MSFT_TaskTimeTrigger is a `-Once` trigger; recurring work uses Daily/Weekly/
    # Logon/Boot classes, so this stays quiet about the routine fleet.
    # Repetition.Interval must be excluded too: the loop supervisors and guards are all
    # registered as a time trigger that then repeats every couple of minutes, so matching
    # the trigger class alone flagged nine recurring tasks as armed one-shot work.
    $oneShot = @($_.Triggers | Where-Object {
            $_.CimClass.CimClassName -eq "MSFT_TaskTimeTrigger" -and -not $_.Repetition.Interval
        }).Count -gt 0
    $noTriggers = ($null -eq $_.Triggers)
    $actionArguments = (@($_.Actions | ForEach-Object { [string]$_.Arguments }) -join " ")
    $completeAuditReceipt = $null
    $auditReportPath = $null
    if (
        $actionArguments -like "*audit_overnight_integration_chain.ps1*" -and
        $actionArguments -match '(?i)-ReportPath\s+(?:"([^"]+)"|(\S+))'
    ) {
        $auditReportPath = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
        try {
            $candidateAuditReceipt = Get-Content -LiteralPath $auditReportPath -Raw |
                ConvertFrom-Json
            if (
                $candidateAuditReceipt.schema_version -eq
                    "overnight_integration_chain_audit_v1" -and
                $candidateAuditReceipt.complete -eq $true
            ) {
                $completeAuditReceipt = $candidateAuditReceipt
            }
        }
        catch { }
    }
    $isQuietMergeAction = (
        $actionArguments -like "*quiet_window_merge.ps1*" -or
        $actionArguments -like "*suite_gated_quiet_merge.ps1*"
    )
    # A replaced exact-tip quiet merge is spent evidence once that reviewed
    # object is already in production history, whether Task Scheduler retains
    # it as Disabled or as Ready with no next run. Do not hard-code dated task
    # names: bind the classification to the action's full SHA and Git ancestry.
    # An unmerged or unreadable tip remains anomalous.
    $integratedExactTipMerge = $false
    $integratedExactTip = $null
    if (
        $isQuietMergeAction -and
        $actionArguments -match '(?i)(?:^|\s)-ExpectedTip\s+([0-9a-f]{40})(?:\s|$)'
    ) {
        $integratedExactTip = $Matches[1].ToLowerInvariant()
        & git -C $repo merge-base --is-ancestor $integratedExactTip HEAD 2>$null
        $integratedExactTipMerge = ($LASTEXITCODE -eq 0)
    }
    if ($oneShot -and $ti.NextRunTime -and $isQuietMergeAction) {
        $settleSeconds = 300
        if ($actionArguments -match '(?i)-SettleSeconds\s+(\d+)') {
            $settleSeconds = [int]$Matches[1]
        }
        $rollbackRecoverySeconds = 1200
        if ($actionArguments -match '(?i)-RollbackRecoverySeconds\s+(\d+)') {
            $rollbackRecoverySeconds = [int]$Matches[1]
        }
        $successProtectionSeconds = $settleSeconds + 240
        $rollbackProtectionSeconds = $settleSeconds + $rollbackRecoverySeconds + 60
        $protectedSeconds = [math]::Max($successProtectionSeconds, $rollbackProtectionSeconds)
        $armedQuietMerges.Add([PSCustomObject]@{
                name = $name
                at = [datetime]$ti.NextRunTime
                # Cover both success (settle + push acknowledgement) and failure (settle +
                # bounded rollback readoption proof). The dangerous case is another driver
                # publishing local master before the guarded script has completed either path.
                protected_until = ([datetime]$ti.NextRunTime).AddSeconds($protectedSeconds)
            })
    }
    # Both push tasks are deliberately Interactive: the Windows credential vault is not
    # available to S4U. Other Interactive tasks are reboot exposure only while they are
    # enabled and still have scheduled work. A disabled task or spent one-shot cannot miss
    # a run after reboot, and an on-demand task has no unattended schedule to miss.
    $deliberatelyInteractive = @("WeatherOneShotPush", "WeatherOneShotMirror")
    $scheduledWorkRemains = (-not $noTriggers -and (-not $oneShot -or $ti.NextRunTime))
    if ([string]$_.Principal.LogonType -eq "Interactive" -and
        $deliberatelyInteractive -notcontains $name -and $st -ne "Disabled" -and
        $scheduledWorkRemains) {
        $interactiveTasks++
    }
    if ($name -eq "WeatherEveningEvidenceRefresh" -and $st -eq "Disabled") {
        $evidenceRefreshHeld = $true
    }
    if ($ti.NextRunTime -and ($res -eq "0x41303" -or $oneShot)) {
        $hrs = ([datetime]$ti.NextRunTime - (Get-Date)).TotalHours
        if ($hrs -gt 0 -and $hrs -lt 16) {
            $upcoming.Add([PSCustomObject]@{
                    name = $name; at = ([datetime]$ti.NextRunTime); in_hours = [math]::Round($hrs, 1)
                    state = $st
                })
            # Armed work that is disabled will never fire, and silence is the failure mode.
            if ($st -eq "Disabled") { $flags.Add("$name is armed for $($ti.NextRunTime) but DISABLED - it will not fire") }
            # Armed work landing inside 12:00-18:00 would roll the fleet in the graded window.
            # quiet_window_merge and chain_recovery_run both refuse there, but a mis-scheduled
            # trigger should be visible here rather than relying on the callee to save us.
            $atHour = ([datetime]$ti.NextRunTime).Hour
            if ($atHour -ge 12 -and $atHour -lt 18) {
                $flags.Add("$name is armed for $($ti.NextRunTime), inside the 12:00-18:00 graded window")
            }
        }
    }
    if ($st -eq "Disabled") {
        # A one-shot that FIRED, SUCCEEDED and then disabled itself is completed work, not an
        # anomaly. Every guarded agent runner (lock day, quiet window, post-merge watchdog,
        # morning briefing) ends with Disable-ScheduledTask by design so it cannot re-fire on a
        # later boot. On 2026-08-05 that raised three simultaneous "unexpectedly DISABLED" flags
        # for three tasks that had each done exactly what they were built to do. Same lesson as
        # the spent-FAILED case below: a monitor that flags success trains us to ignore it.
        $selfDisarmed = ($oneShot -and -not $ti.NextRunTime -and $res -eq "0x0" -and $ti.LastRunTime)
        # Expected-disabled is checked FIRST. A spent one-shot that is ALSO deliberately
        # disabled (WeatherOneShotMirror, 2026-08-12) matched $selfDisarmed and reported
        # "self-disarmed cleanly", which is a different claim from "an operator turned this
        # off" and points at the wrong artifact. Deliberate beats incidental.
        $onDemandCompleted = ($noTriggers -and $res -eq "0x0" -and $ti.LastRunTime)
        if ($expDisabled -contains $name) { }
        elseif ($integratedExactTipMerge) {
            $warns.Add("$name is disabled and retained as spent exact-tip merge evidence; $integratedExactTip is already in production history")
        }
        elseif ($onDemandCompleted) {
            $warns.Add("$name completed an on-demand run at $($ti.LastRunTime) and is now disabled (exit 0x0) - verify its artifact before relying on the result")
        }
        elseif ($selfDisarmed) {
            # 2026-08-10: this used to end "completed work, no action". It cannot know that.
            # WeatherAgentOvernight1030 exited 0x0 having done NOTHING - claude.exe printed
            # "You've hit your session limit" and returned 0 - and this line called it completed
            # work. Exit 0x0 proves the task RAN and disarmed; it proves nothing about output.
            # Say only what the exit code supports, and point at the artifact that would show it.
            $warns.Add("$name ran $($ti.LastRunTime) and self-disarmed cleanly (spent one-shot, exit 0x0) - task ran; exit code does NOT prove it produced output, check its artifact")
        }
        elseif ($oneShot -and -not $ti.NextRunTime -and $ti.LastRunTime) {
            # A failed one-shot can deliberately self-disable too. Describe the
            # completed run and its durable receipt, not the expected terminal
            # scheduler state.
            $spentFailure = "$name spent one-shot FAILED $res on $($ti.LastRunTime); verify its artifact"
            $auditFailures = @($completeAuditReceipt.failures)
            $knownRetainedGapOnly = (
                $null -ne $completeAuditReceipt -and
                $completeAuditReceipt.ok -eq $false -and
                $auditFailures.Count -eq 1 -and
                [string]$auditFailures[0] -like
                    "execution_tape_runtime:*health=DEGRADED; capture=CONNECTED; integrity=PASS; identity=True; lock=True*"
            )
            if ($completeAuditReceipt -and $completeAuditReceipt.ok -eq $true) {
                $warns.Add(
                    "$name retained failed scheduler result $res; later complete audit receipt is PASS"
                )
            }
            elseif ($knownRetainedGapOnly) {
                $warns.Add(
                    "$name complete audit remains BLOCK only for retained execution-tape gaps; " +
                    "producer is CONNECTED with integrity, identity, and lock PASS"
                )
            }
            elseif ($completeAuditReceipt) {
                $flags.Add(
                    "$name complete audit verdict is BLOCK with $($auditFailures.Count) failure(s); " +
                    "review $auditReportPath"
                )
            }
            elseif ([datetime]$ti.LastRunTime -lt (Get-Date).AddHours(-24)) {
                $warns.Add($spentFailure)
            }
            else {
                $flags.Add($spentFailure)
            }
        }
        else { $flags.Add("$name unexpectedly DISABLED") }
    }
    else {
        $ok = ($res -eq "0x0")
        # LastTaskResult is a completed-run field, not a live-run verdict. Task
        # Scheduler can retain the prior result (observed as 0x800710E0 for an
        # on-demand suite) while State already says Running. Health and hang
        # checks belong to each workload's own monitor; do not turn that stale
        # result into a generic failure before the current run has completed.
        if (-not $ok -and $st -eq "Running") { $ok = $true }
        # 0x41301 = SCHED_S_TASK_RUNNING: we sampled the task mid-execution (the
        # every-minute supervisors make this a routine race). The task is healthy
        # by definition while running; its next completed result is what matters.
        if (-not $ok -and $res -eq "0x41301") { $ok = $true }
        # 0x41303 = SCHED_S_TASK_HAS_NOT_RUN: a scheduled one-shot that has not fired yet.
        # Normal for freshly registered work, and flagging it would train us to ignore flags.
        if (-not $ok -and $res -eq "0x41303") { $ok = $true }
        if (-not $ok -and $expNonZero.ContainsKey($name)) { $ok = ($expNonZero[$name] -contains $res) }
        # A completed exact-tip merge can leave the one-shot Ready with no next
        # run and retain the failed result of an earlier attempt. Once Git proves
        # that exact reviewed object is in production, the task is spent evidence,
        # not a current failure. This does not forgive an unintegrated tip.
        if (-not $ok -and $integratedExactTipMerge -and $oneShot -and -not $ti.NextRunTime) {
            $warns.Add("$name prior attempt ended $res on $($ti.LastRunTime), but exact tip $integratedExactTip is already in production history (spent one-shot)")
            $ok = $true
        }
        # Re-arming a one-shot preserves its previous exit code. Once a future
        # run is present, that code is historical evidence about the prior
        # attempt, not proof that the armed attempt already failed.
        if (-not $ok -and $oneShot -and $ti.NextRunTime -and
            ([datetime]$ti.NextRunTime) -gt (Get-Date)) {
            $warns.Add("$name is re-armed for $($ti.NextRunTime); previous attempt ended $res on $($ti.LastRunTime)")
            $ok = $true
        }
        # A SPENT one-shot -- it fired, has no NextRunTime, and last ran over a day ago -- is
        # finished work, not current breakage. Its exit code is history and would otherwise burn
        # a FLAG forever: the three WeatherQuietWindowMerge tasks were still flagging 0x1 from
        # 2026-08-01 two days later, long after a manual re-run had completed the merge. Keep the
        # failure visible, but report it as what it is -- an old run nobody re-armed -- so it
        # cannot masquerade as a live fault and train us to ignore the flag list.
        if (-not $ok -and $oneShot -and -not $ti.NextRunTime -and $ti.LastRunTime -and
            ([datetime]$ti.LastRunTime) -lt (Get-Date).AddHours(-24)) {
            $warns.Add("$name last FAILED $res on $($ti.LastRunTime) and is NOT re-armed (spent one-shot) - re-register it if that work still needs to run")
            $ok = $true
        }
        if (-not $ok) { $flags.Add("$name $res unexpected (last run $($ti.LastRunTime))") }
    }
}

if ($sensitiveDriverNextRun) {
    foreach ($mergeTask in $armedQuietMerges) {
        if ($sensitiveDriverNextRun -ge $mergeTask.at -and
            $sensitiveDriverNextRun -le $mergeTask.protected_until) {
            $flags.Add(
                "$($mergeTask.name) recovery/publish interval overlaps WeatherMergeSensitiveDriver at $sensitiveDriverNextRun - the driver can publish unverified local master"
            )
        }
    }
}

if ($evidenceRefreshHeld) {
    $warns.Add("WeatherEveningEvidenceRefresh is operator-held DISABLED; evidence refresh remains unavailable until it is explicitly re-enabled")
}

# ---- unattended resilience ----
# HISTORY, because the comment here outlived the fact and produced a false alarm for ten
# days. Before 2026-07-24 almost every Weather* task was LogonType=Interactive, so the fleet
# only ran while a user session existed and a reboot left this host DARK until somebody
# logged in. That was fixed: measured 2026-08-03, every capture-critical task
# (WeatherSnapshotLoopSupervisor, WeatherClobBookLoopSupervisor,
# WeatherObservationTriggerSupervisor, WeatherCapturePriorityGuard) is S4U with a time
# trigger, and WeatherBootRecovery is S4U on a boot trigger. Credential-vault push tasks are
# excluded above; any other enabled Interactive task with scheduled work remains visible.
# The exposure is still surfaced continuously, because the monitoring cannot warn about the
# one failure that would disable the monitoring.
#
# NOT YET PROVEN: the S4U fix has never survived a real reboot (uptime was 322 h on
# 2026-08-03; the fix landed 07-24, last boot 07-21). Configuration says capture self-recovers.
# That is not the same as measured. Worth a deliberate 01:00-04:00 reboot test after the lock.
$windowsUpdatePolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
$windowsUpdateAuOptions = $null
try {
    $updatePolicy = Get-ItemProperty -Path $windowsUpdatePolicyPath -ErrorAction SilentlyContinue
    if ($updatePolicy -and $updatePolicy.PSObject.Properties.Name -contains "AUOptions") {
        $windowsUpdateAuOptions = [int]$updatePolicy.AUOptions
    }
}
catch {}
if ($windowsUpdateAuOptions -eq 2) {
    $flags.Add("Windows Update is policy-forced to notify-only (AUOptions=2); unattended security updates cannot download/install")
}
$rebootPending = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
$autoLogon = ""
try {
    $autoLogon = [string](Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -ErrorAction SilentlyContinue).AutoAdminLogon
}
catch {}
if ($interactiveTasks -gt 0 -and $autoLogon -ne "1") {
    if ($rebootPending) {
        $flags.Add("REBOOT PENDING + $interactiveTasks logon-dependent tasks + no auto-logon: a restart leaves the whole fleet DOWN until someone logs in")
    }
    else {
        $warns.Add("$interactiveTasks Weather tasks are LogonType=Interactive with no auto-logon - none of them run after an unattended reboot")
    }
}
elseif ($rebootPending) {
    # The fleet is S4U now, so a restart self-recovers; still worth knowing one is queued
    # because it costs a short capture gap whenever it happens.
    $warns.Add("reboot pending - fleet is S4U so it self-recovers, but expect a brief capture gap; avoid restarting inside 12:00-18:00")
}

# ---- off-host mirror (the only copy of data\ that is not on this disk) ----
# PAUSED by operator decision 2026-08-12 to keep this 16 GB host's resources on capture
# stability (docs/operations/mirror-paused-2026-08-12.md). The pause switch is the TASK STATE,
# not a marker file: re-enabling WeatherDataMirror restores full alerting automatically, so the
# suppression cannot outlive the pause or be forgotten in a file nobody reads. A paused mirror
# still WARNS on every run, carrying the AGE of the frozen copy -- the point is to stop crying
# wolf about a nightly job that is off on purpose, NOT to stop saying data\ is unprotected.
$mirrorPaused = $false
try { $mirrorPaused = ([string](Get-ScheduledTask -TaskName "WeatherDataMirror" -EA Stop).State -eq "Disabled") } catch {}
$mirror = $null
$mirrorAgeH = $null
$mf = "C:\Users\micha\ops\mirror_status.json"
if (Test-Path $mf) {
    try {
        $mirror = Get-Content $mf -Raw | ConvertFrom-Json
        $mirrorAgeH = [math]::Round(((Get-Date) - [datetime]$mirror.last_run).TotalHours, 1)
    }
    catch {}
}
if ($null -eq $mirror) { $warns.Add("mirror status unreadable - off-host copy unverified") }
elseif ($mirrorPaused) {
    $frozenAt = "an unknown date"
    try { $frozenAt = ([datetime]$mirror.last_run).ToString("yyyy-MM-dd HH:mm") } catch {}
    $warns.Add("mirror PAUSED by operator 2026-08-12 - the off-host copy of data\ is FROZEN at $frozenAt (${mirrorAgeH}h old and ageing). Everything written since exists ONLY on this disk. Re-enable WeatherDataMirror to resume")
}
elseif (-not $mirror.ok) { $flags.Add("mirror last run FAILED (robocopy exit $($mirror.robocopy_exit))") }
elseif ($mirrorAgeH -gt 30) { $flags.Add("mirror stale: last good run ${mirrorAgeH}h ago (nightly 04:30)") }

# robocopy's exit code says a copy RAN, not that what landed can be restored. With the tape
# backup's restore drill disabled since 2026-06-30, nothing proved the mirror readable until
# verify_mirror_restore.ps1 pulled files back and hashed them. Surface that separately from
# mirror freshness -- "copied recently" and "restorable" are different claims.
$restore = $null
$restoreAgeH = $null
$rf = Join-Path $repo "data\alerts\mirror_restore_verify.json"
if (Test-Path $rf) {
    try {
        $restore = Get-Content $rf -Raw | ConvertFrom-Json
        $restoreAgeH = [math]::Round(((Get-Date) - [datetime]$restore.ts).TotalHours, 1)
    }
    catch {}
}
# No versioned backup exists (the tape subsystem was deleted 2026-07-07, commit 3ebca26e) and
# the nightly /MIR mirror is a replica rather than a backup. That is an ACCEPTED operator
# decision as of 2026-07-26 -- durability work waits until the model is profitable -- so it is
# deliberately NOT reported here. The cheap checks below stay because they already run.
if ($null -eq $restore) { $warns.Add("mirror has never been restore-verified - run scripts\ops\verify_mirror_restore.ps1") }
elseif ($mirrorPaused) {
    # Restorability cannot improve while the mirror is off, so this is a standing fact about the
    # frozen copy rather than a new event each morning. Said once, as a warn, and only when the
    # last verify actually failed.
    if (-not $restore.ok) {
        $warns.Add("the FROZEN off-host copy is not proven restorable - the last restore-verify (before the pause) found $($restore.problems) problem file(s)")
    }
}
elseif (-not $restore.ok) { $flags.Add("MIRROR RESTORE VERIFY FAILED: $($restore.problems) problem file(s) - the off-host copy may not be restorable") }
elseif ($restoreAgeH -gt 48) { $warns.Add("mirror restore-verify stale (${restoreAgeH}h) - restorability unproven since then") }

# ---- host stability (this machine loses power) ----
# Event-log forensics on 2026-07-25 found five unexpected shutdowns in 90 days, four of them
# bugcheck=0 / powerButton=0 -- abrupt power loss, not a crash. That is roughly one every
# three weeks against a 14-day contiguous streak, and none of them were ever visible here:
# the digest reported a healthy host either side of a 29-minute outage on 2026-07-21, which
# was day 1 of the current streak. An outage inside 12:00-18:00 ends the streak, so a recent
# one is a FLAG -- it means today's grade needs checking, not just today's process list.
$uptimeH = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
$lastCrash = $null
$crashes90 = 0
try {
    $ev = @(Get-WinEvent -FilterHashtable @{LogName = 'System'; Id = 41; StartTime = (Get-Date).AddDays(-90) } -MaxEvents 20 -EA SilentlyContinue)
    $crashes90 = $ev.Count
    if ($ev.Count -gt 0) { $lastCrash = $ev[0].TimeCreated }
}
catch {}
if ($lastCrash -and ((Get-Date) - $lastCrash).TotalHours -lt 24) {
    $flags.Add("UNEXPECTED SHUTDOWN $lastCrash - verify today's capture grade; an outage inside 12:00-18:00 ends the streak")
}
elseif ($crashes90 -ge 3) {
    $warns.Add("$crashes90 unexpected shutdowns in 90d (most recent $lastCrash) - power loss is the top uncontrolled streak risk; a UPS would remove it")
}

# ---- the watchdog itself (who watches the watcher) ----
# health_watchdog.ps1 is what alerts overnight while nobody is awake. If IT dies, every
# window-aware alert silently stops and the first symptom is a morning with no briefing.
# Nothing else here would notice, so check its heartbeat explicitly. It runs every 15 min.
$wd = $null
$wdAgeMin = $null
$wdf = Join-Path $repo "data\alerts\host_health_latest.json"
if (Test-Path $wdf) {
    try {
        $wd = Get-Content $wdf -Raw | ConvertFrom-Json
        $wdAgeMin = [math]::Round(((Get-Date) - [datetime]$wd.ts).TotalMinutes, 0)
    }
    catch {}
}
if ($null -eq $wd) { $flags.Add("health watchdog has never reported - overnight alerting is NOT running") }
elseif ($wdAgeMin -gt 45) { $flags.Add("health watchdog stale by ${wdAgeMin} min (runs every 15) - overnight alerting may be dead") }

# ---- last guarded quiet-window merge ----
# Merges happen at 01:30 while I am not watching; the outcome must be waiting in the morning.
$qw = $null
$qwf = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
if (Test-Path $qwf) {
    try {
        $qw = Get-Content $qwf -Raw | ConvertFrom-Json
        $qwAgeH = ((Get-Date) - [datetime]$qw.ts).TotalHours
        # A rollback means capture did not survive the code roll -- streak-critical, and the
        # branch still needs a human decision. Never let that scroll past in a log file.
        if ($qw.stage -eq "rollback_recovery_failed" -and $qwAgeH -lt 36) {
            $flags.Add("quiet-window merge rollback recovery is UNPROVEN ($($qw.detail)) - protect capture and reconcile before another merge")
        }
        elseif ($qw.stage -eq "rolled_back" -and $qwAgeH -lt 36) {
            $flags.Add("quiet-window merge ROLLED BACK ($($qw.detail)) - capture did not recover; branch unmerged")
        }
        elseif ($qw.stage -eq "merged_unpushed" -and $qwAgeH -lt 36) {
            $warns.Add("quiet-window merge committed locally but NOT pushed - run WeatherOneShotPush")
        }
    }
    catch {}
}

# ---- alerts ----
$alertLast = $null
$af = Join-Path $repo "data\alerts\streak_capture_alerts.jsonl"
if (Test-Path $af) {
    $l = Get-Content $af -Tail 1
    if ($l) {
        try {
            $j = $l | ConvertFrom-Json
            # Show the AGE. Without it a two-day-old AT_RISK reads as current alarm, which is
            # both frightening and wrong -- the entry is historical the moment the day recovers.
            $alertTime = [datetime]$j.ts
            $ageH = ((Get-Date) - $alertTime).TotalHours
            $historicalCaptureDay = $alertTime.Date -lt (Get-Date).Date
            $alertLast = "{0}  {1}  ({2:N0}h ago{3})" -f $j.ts, $j.level, $ageH,
                $(if ($historicalCaptureDay -or $ageH -ge 24) { ", historical" } else { "" })
            # The capture grade closes by local calendar day. Yesterday's final
            # AT_RISK is evidence in the ledger, not a live alarm today.
            if (-not $historicalCaptureDay -and $ageH -lt 24) {
                $flags.Add("capture alert raised today: $alertLast")
            }
        }
        catch {}
    }
}

# ---- verdict ----
$verdict = if ($flags.Count -gt 0) { "ATTENTION" } else { "OK" }
$exitCode = if ($flags.Count -gt 0) { 2 } else { 0 }

# ---- render ----
$ts = Get-Date -Format "yyyy-MM-dd HH:mm"
# "no today_health" is NOT "already settled" -- that reads as a benign claim about a day
# nobody measured. Say which of the two it is; an unreadable state is not a passing state.
$todayStr = if ($null -eq $streak) { "UNKNOWN - streak checker did not run" }
elseif ($null -eq $today) { "no today_health from the streak checker" }
else { "{0}  ({1} caps, {2}min max gap)" -f ([string]$today.verdict).ToUpper(), $today.captures, $today.max_window_gap_min }
$capSummary = ($caps.Keys | ForEach-Object {
        $pri = if ($capState[$_].Count) { (($capState[$_] | Select-Object -Unique) -join ",") } else { "DOWN" }
        "{0}={1}" -f $_, $pri
    }) -join "   "
$alertStr = if ($alertLast) { $alertLast } else { "none" }

if ($Json) {
    [PSCustomObject]@{
        ts       = $ts; verdict = $verdict
        flags    = @($flags); warns = @($warns)
        streak   = @{ days = $streak.streak_days; target = $streak.target; start = $streak.streak_start;
            today = $todayStr; lock = $streak.projected_lock_date_if_all_clean;
            settled = $streak.most_recent_settled
        }
        capture  = $capState; execution_tape = $executionTapeState
        ram_free_gb = $freeRamGB; ram_total_gb = $totRamGB; disk_free_gb = $freeDiskGB
        disk     = @{ free_gb = $freeDiskGB; delta_gb_per_day = $diskDelta; days_left = $diskDaysLeft }
        clock    = @{ service = $(if ($clockService) { [string]$clockService.Status } else { $null })
            synchronized = $clockSynchronized; source = $clockSource; sync_age_hours = $clockSyncAgeH
            last_sync = $(if ($clockLastSync) { $clockLastSync.ToString("o") } else { $null })
        }
        chain    = @{ status = $chainStatus; terminal = $chainTerm; failing_step = $chainFail; payload_blocked = $chainBlocked }
        git      = @{ unpushed = $unpushed; dirty = $dirtyCount; last = $lastCommit }
        mirror   = @{ ok = $(if ($mirror) { [bool]$mirror.ok } else { $null }); age_hours = $mirrorAgeH
            paused = $mirrorPaused
            restore_verified = $(if ($restore) { [bool]$restore.ok } else { $null })
            restore_verify_age_hours = $restoreAgeH
            restore_identical = $(if ($restore) { $restore.verified_identical } else { $null })
        }
        watchdog = @{ age_min = $wdAgeMin; verdict = $(if ($wd) { [string]$wd.verdict } else { $null }) }
        merge    = @{ stage = $(if ($qw) { [string]$qw.stage } else { $null }); ts = $(if ($qw) { [string]$qw.ts } else { $null }) }
        upcoming = @($upcoming | Sort-Object at | ForEach-Object {
                @{ name = $_.name; at = $_.at.ToString("yyyy-MM-dd HH:mm"); in_hours = $_.in_hours }
            })
        resilience = @{ reboot_pending = $rebootPending; auto_logon = ($autoLogon -eq "1");
            interactive_tasks = $interactiveTasks; uptime_hours = $uptimeH
            windows_update_au_options = $windowsUpdateAuOptions
            unattended_updates_blocked = ($windowsUpdateAuOptions -eq 2)
            unexpected_shutdowns_90d = $crashes90
            last_unexpected_shutdown = $(if ($lastCrash) { $lastCrash.ToString("o") } else { $null })
        }
        tasks_scanned = $taskCount; alert_last = $alertStr
    } | ConvertTo-Json -Depth 6
    exit $exitCode
}

$bar = "=" * 76
Write-Output $bar
Write-Output ("  WEATHER HOST STATUS   $ts          VERDICT: $verdict")
Write-Output $bar
Write-Output ("  STREAK    : {0}/{1}  day1 {2}    TODAY: {3}" -f $streak.streak_days, $streak.target, $streak.streak_start, $todayStr)
Write-Output ("              lock ~{0} if all clean   |  settled -> {1}" -f $streak.projected_lock_date_if_all_clean, $streak.most_recent_settled)
Write-Output ("  CAPTURE   : {0}" -f $capSummary)
$executionTapeSummary = if (-not $executionTapeState.armed) { "not armed" }
elseif (-not $executionTapeState.process_healthy) { "ARMED / UNHEALTHY" }
else { "{0}, price-path usable={1}" -f $executionTapeState.capture_state, $executionTapeState.price_path_usable }
Write-Output ("  EXEC TAPE : {0}" -f $executionTapeSummary)
$diskTrend = if ($null -eq $diskDelta) { "" }
elseif ($diskDelta -lt 0) { "  ({0} GB/day, ~{1}d left)" -f $diskDelta, $diskDaysLeft }
else { "  (+{0} GB/day)" -f $diskDelta }
Write-Output ("  RESOURCES : RAM {0}/{1} GB free    Disk C: {2} GB free{3}" -f $freeRamGB, $totRamGB, $freeDiskGB, $diskTrend)
$clockState = if ($clockSynchronized -eq $false) { "UNSYNCHRONIZED" }
elseif ($null -eq $clockLastSync) { "UNKNOWN" }
elseif ($clockService.Status -eq "Running" -and $clockSource) { "synced via $clockSource, $clockSyncAgeH h ago" }
else { "last valid sample $clockSyncAgeH h ago (trigger-start service $($clockService.Status))" }
Write-Output ("  CLOCK     : {0}" -f $clockState)
$chainNote = if ($chainTaskResult -eq "0x4B" -and $chain -and $chain.terminal) {
    "0x4B = protected-window deadline; durable terminal status verified"
}
elseif ($chainStatus -eq "critical" -and -not $chainFail) {
    "all steps OK - 'critical' is the readiness gate, expected pre-release"
}
elseif ($chainTaskResult -eq "0x2") {
    "0x2 = gates BLOCK, expected pre-release"
}
elseif ($chainTaskResult) {
    "$chainTaskResult = last scheduled result"
}
else { "scheduled result unavailable" }
Write-Output ("  CHAIN     : {0} / {1}   ({2})" -f $chainStatus, $chainTerm, $chainNote)
if ($chainFail) { Write-Output ("              step: {0}" -f $chainFail) }
if ($chainGate) { Write-Output ("              gate: {0}" -f $chainGate) }
if ($chainBlocked) { Write-Output ("              {0}" -f $chainBlocked) }
$mirrorStr = if ($null -eq $mirror) { "unreadable" }
elseif ($mirrorPaused) { "PAUSED by operator, frozen {0}h ago" -f $mirrorAgeH }
elseif ($mirror.ok) { "ok, {0}h ago" -f $mirrorAgeH }
else { "FAILED (exit $($mirror.robocopy_exit))" }
# While paused, the restore suffix would report a verify that can no longer change against a
# copy that can no longer change. The PAUSED string plus its warn already say it.
if ($mirrorPaused) { }
elseif ($restore) {
    $mirrorStr += if ($restore.ok) { " [restore-verified {0}/{1} {2}h ago]" -f $restore.verified_identical, $restore.checked, $restoreAgeH }
    else { " [RESTORE VERIFY FAILED]" }
}
else { $mirrorStr += " [never restore-verified]" }
Write-Output ("  OFF-HOST  : mirror {0}    |  reboot pending: {1}   logon-dependent tasks: {2}" -f $mirrorStr, $rebootPending, $interactiveTasks)
$crashStr = if ($lastCrash) { "{0} unexpected shutdown(s)/90d, last {1:MM-dd HH:mm}" -f $crashes90, $lastCrash } else { "no unexpected shutdowns in 90d" }
Write-Output ("  STABILITY : up {0}h   |  {1}" -f $uptimeH, $crashStr)
Write-Output ("  GIT       : {0} unpushed | {1} dirty | {2}" -f $unpushed, $dirtyCount, $lastCommit)
Write-Output ("  TASKS     : {0} Weather tasks scanned (anomalies -> FLAGS)" -f $taskCount)
$wdStr = if ($null -eq $wd) { "NEVER REPORTED" } else { "{0}, {1} min ago" -f ([string]$wd.verdict), $wdAgeMin }
$qwStr = if ($null -eq $qw) { "none" } else { "{0} ({1:yyyy-MM-dd HH:mm})" -f $qw.stage, ([datetime]$qw.ts) }
Write-Output ("  WATCHDOG  : {0}    |  last merge attempt: {1}" -f $wdStr, $qwStr)
Write-Output ("  ALERTS    : last {0}" -f $alertStr)
if ($upcoming.Count -gt 0) {
    Write-Output "  ARMED     : (scheduled, not yet run)"
    foreach ($u in ($upcoming | Sort-Object at)) {
        Write-Output ("              {0:HH:mm} (+{1}h)  {2}" -f $u.at, $u.in_hours, $u.name)
    }
}
if ($flags.Count -gt 0) {
    Write-Output ("  " + ("-" * 74))
    Write-Output "  FLAGS (need attention):"
    foreach ($f in $flags) { Write-Output "    ! $f" }
}
if ($warns.Count -gt 0) {
    Write-Output ("  " + ("-" * 74))
    Write-Output "  notes (standing / low-priority):"
    foreach ($w in $warns) { Write-Output "    - $w" }
}
Write-Output $bar
exit $exitCode
