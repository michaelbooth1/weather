# Workstation-side reachability watchdog for the production capture host (DESIGN; not registered).
#
#   .\scripts\ops\ws_ping_watchdog.ps1                 # one probe pass (meant for every 5 minutes)
#
# Runs on the 32 GB workstation, never on the capture host. One invocation = one pass: probe the
# capture host (ICMP, optionally TCP 22), update a small state file, append one jsonl line, and on a
# state change raise a local toast. After -MissThreshold consecutive misses it alerts ONCE, repeats a
# reminder at most every -ReminderMinutes while the host stays down, and reports RECOVERED with the
# outage length when a probe succeeds again. If the workstation's own default gateway does not answer,
# the pass is recorded as "ws_offline" and does not count as a capture-host miss.
#
# Outbound probes only: no listener, no firewall rule, no port 8765, nothing named WeatherWalletReader,
# no import from the repository's Python code. Design: docs/operations/WS_PING_WATCHDOG.md.
[CmdletBinding()]
param(
    [string]$TargetHost = "192.168.1.247",
    [ValidateRange(0, 65535)][int]$TcpPort = 22,          # 0 disables the TCP check
    [ValidateRange(1, 100)][int]$MissThreshold = 2,
    [ValidateRange(5, 1440)][int]$ReminderMinutes = 60,
    [ValidateRange(6, 1440)][int]$GapMinutes = 15,         # a longer silence is logged as a watchdog gap
    [string]$StateDir = "",
    [switch]$NoToast,
    # Fixture evaluation only; the registered task never passes these.
    [string]$SimulateProbe = "",                           # "", up, down or ws_offline
    [string]$NowUtc = ""
)

$ErrorActionPreference = "Stop"
if ($SimulateProbe -notin @("", "up", "down", "ws_offline")) { throw "SimulateProbe must be up, down or ws_offline" }
if ([string]::IsNullOrWhiteSpace($StateDir)) {
    $StateDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "data\alerts"
}
if (-not (Test-Path -LiteralPath $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
$logPath = Join-Path $StateDir "ws_ping_watchdog.jsonl"
$statePath = Join-Path $StateDir "ws_ping_watchdog_state.json"
$now = if ($NowUtc) { [datetimeoffset]::Parse($NowUtc, [Globalization.CultureInfo]::InvariantCulture) } else { [datetimeoffset]::UtcNow }

function Test-Icmp([string]$Address, [int]$Tries = 3, [int]$TimeoutMs = 1000) {
    $ping = New-Object System.Net.NetworkInformation.Ping
    try {
        for ($i = 0; $i -lt $Tries; $i++) {
            try {
                $reply = $ping.Send($Address, $TimeoutMs)
                if ($reply.Status -eq [System.Net.NetworkInformation.IPStatus]::Success) { return $true }
            } catch { }
        }
        return $false
    } finally { $ping.Dispose() }
}

function Test-Tcp([string]$Address, [int]$Port, [int]$TimeoutMs = 2000) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($Address, $Port)
        return ($task.Wait($TimeoutMs) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}

function Get-Gateway {
    try {
        $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
            Sort-Object -Property RouteMetric | Select-Object -First 1
        if ($route -and $route.NextHop -and $route.NextHop -ne "0.0.0.0") { return [string]$route.NextHop }
    } catch { }
    return $null
}

function Show-Toast([string]$Title, [string]$Body) {
    if ($NoToast) { return "suppressed" }
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $esc = { param($s) [Security.SecurityElement]::Escape($s) }
        $xml.LoadXml("<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>$(& $esc $Title)</text>" +
                     "<text>$(& $esc $Body)</text></binding></visual></toast>")
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show(
            [Windows.UI.Notifications.ToastNotification]::new($xml))
        return "shown"
    } catch { return "error: $($_.Exception.Message)" }
}

# ---- state
$state = [ordered]@{ consecutive_misses = 0; alerting = $false; down_since_utc = $null; last_alert_utc = $null;
                     last_ok_utc = $null; last_run_utc = $null }
if (Test-Path -LiteralPath $statePath) {
    try {
        $loaded = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        foreach ($k in @($state.Keys)) { if ($null -ne $loaded.$k) { $state[$k] = $loaded.$k } }
    } catch { }   # a corrupt state file restarts the count; the log keeps the history
}
$sinceLast = $null
if ($state.last_run_utc) {
    $sinceLast = [math]::Round(($now - [datetimeoffset]::Parse($state.last_run_utc)).TotalMinutes, 1)
}

# ---- probe
$icmp = $null; $tcp = $null; $gateway = $null; $toast = $null
if ($SimulateProbe) {
    $probe = $SimulateProbe
} else {
    $icmp = Test-Icmp $TargetHost
    if (-not $icmp -and $TcpPort -gt 0) { $tcp = Test-Tcp $TargetHost $TcpPort }
    if ($icmp -or $tcp) {
        $probe = "up"
    } else {
        $gateway = Get-Gateway
        $probe = if ($gateway -and (Test-Icmp $gateway)) { "down" } else { "ws_offline" }
    }
}

# ---- rules
$evt = $null
switch ($probe) {
    "up" {
        if ($state.alerting) {
            $mins = [math]::Round(($now - [datetimeoffset]::Parse($state.down_since_utc)).TotalMinutes, 1)
            $evt = "RECOVERED"
            $toast = Show-Toast "Capture host reachable again" "$TargetHost answered after about $mins min down."
        }
        $state.consecutive_misses = 0; $state.alerting = $false; $state.down_since_utc = $null
        $state.last_alert_utc = $null; $state.last_ok_utc = $now.ToString("o")
    }
    "down" {
        $state.consecutive_misses = [int]$state.consecutive_misses + 1
        if (-not $state.down_since_utc) { $state.down_since_utc = $now.ToString("o") }
        if (-not $state.alerting -and $state.consecutive_misses -ge $MissThreshold) {
            $evt = "ALERT"; $state.alerting = $true; $state.last_alert_utc = $now.ToString("o")
            $toast = Show-Toast "Capture host UNREACHABLE" "$TargetHost missed $($state.consecutive_misses) probes in a row. Check its Wi-Fi."
        } elseif ($state.alerting -and
                  ($now - [datetimeoffset]::Parse($state.last_alert_utc)).TotalMinutes -ge $ReminderMinutes) {
            $evt = "REMINDER"; $state.last_alert_utc = $now.ToString("o")
            $toast = Show-Toast "Capture host still unreachable" "$TargetHost down since $($state.down_since_utc)."
        }
    }
    "ws_offline" { }   # this PC has no network: neither a miss nor a recovery
}
$state.last_run_utc = $now.ToString("o")

# ---- record
$record = [ordered]@{ ts_utc = $now.ToString("o"); target = $TargetHost; probe = $probe; icmp = $icmp; tcp = $tcp;
                      gateway = $gateway; consecutive_misses = $state.consecutive_misses; alerting = $state.alerting;
                      event = $evt; toast = $toast; minutes_since_last_run = $sinceLast;
                      watchdog_gap = [bool]($sinceLast -and $sinceLast -gt $GapMinutes); simulated = [bool]$SimulateProbe }
$line = ($record | ConvertTo-Json -Compress)
if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -gt 16MB) {
    Move-Item -LiteralPath $logPath -Destination (Join-Path $StateDir ("ws_ping_watchdog.{0}.jsonl" -f $now.UtcDateTime.ToString("yyyyMMddTHHmmssZ")))
}
[IO.File]::AppendAllText($logPath, $line + "`n", [Text.UTF8Encoding]::new($false))
$tmp = $statePath + ".tmp"
[IO.File]::WriteAllText($tmp, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $tmp -Destination $statePath -Force
Write-Output $line
if ($evt -eq "ALERT" -or $evt -eq "REMINDER") { exit 2 }
exit 0
