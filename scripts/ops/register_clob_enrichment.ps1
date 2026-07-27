# Register WeatherClobEnrichmentLoop: run the CLOB enrichment loop that was built but never
# deployed.
#
#   .\scripts\ops\register_clob_enrichment.ps1 [-StartAt "01:00"] [-Unregister]
#
# Why this exists: market_microstructure has TWO loops by design. The latency-critical book
# loop captures raw books only -- there is an explicit contract (_assert_raw_loop_contract)
# forbidding price history and WebSocket sampling there, so a duplicate-heavy research
# refresh can never delay unbackfillable book tape. Everything else belongs to a separate
# enrichment loop. That second loop was written, given its own status/diagnostics/pause-flag
# contract and a health function... and never registered. As of 2026-07-27 it had never run:
# no clob_enrichment_status.json existed and no task referenced it.
#
# The cost of that gap: market_ws_events.csv, price_history.csv and clob_features_long.csv
# were never produced, so `mm_paper_scoring.load_trade_rows` -- which reads exactly
# trades_long.csv / market_trades.csv / market_ws_events.csv -- had nothing to read. The
# market-making paper scorer has been reporting $0.00 over vacuous evidence because the
# apparatus feeding it was never connected.
#
# Deliberately NOT a source change, so it triggers no STALE_CODE fleet roll: this is a new
# task running a separate process. Duplicate protection is twofold -- the loop takes its own
# writer lock on the status file, and the task uses MultipleInstances=IgnoreNew. The 15-minute
# repetition therefore acts as a supervisor: it is ignored while the process is alive and
# restarts it if it has died.
[CmdletBinding()]
param(
    [string]$StartAt = "01:00",
    [int]$IntervalSeconds = 900,
    # Defaults sample the WebSocket for 1s capped at 5 messages, which in a thin book is
    # almost never long enough to see anything but a book update. Measured 2026-07-27 on
    # toronto: 1s/5msg produced 24 rows/iteration, while 20s/400msg produced 806 price_change
    # rows in 12.8s. Widened, but kept bounded -- 12 markets at ~13s is ~17% duty cycle.
    [double]$WebsocketSeconds = 20.0,
    [int]$WebsocketMessageLimit = 400,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "WeatherClobEnrichmentLoop"
$repo = "C:\Users\micha\Desktop\github\weather"
$python = Join-Path $repo "venv\Scripts\pythonw.exe"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "unregistered $taskName"
    exit 0
}
if (-not (Test-Path $python)) { throw "missing $python" }

$arguments = "-m weather.market.market_microstructure enrichment-loop " +
"--market all --interval-seconds $IntervalSeconds " +
"--websocket-seconds $WebsocketSeconds --websocket-message-limit $WebsocketMessageLimit"

$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $repo
# Repetition doubles as the supervisor; the process is long-lived so there is no time limit.
$trigger = New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "micha" -LogonType S4U -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
$info = $t | Get-ScheduledTaskInfo
Write-Output ("registered {0}: state={1} logon={2} next={3}" -f $taskName, $t.State, $t.Principal.LogonType, $info.NextRunTime)
Write-Output "verify: venv\Scripts\python.exe -m weather.market.market_microstructure enrichment-status"
