# Capture-loop priority guard (protects the code-soak streak).
#
# The three capture loops MUST run at AboveNormal so their snapshot cadence wins
# CPU races under contention (an in-window snapshot gap resets the streak). But
# multiple restart paths keep resetting them to a lower default:
#   * supervisor `ensure` respawn        -> Normal
#   * 01:00 training-window restart       -> BelowNormal (spawned as python.exe)
#   * mirror-time / stale-code rolls      -> default
# Neither a one-shot bump nor raising the supervisor task priority survives all of
# these, so this guard re-asserts AboveNormal every few minutes, 24/7. Idempotent
# and cheap (a process enumeration + priority set only when wrong).
# Scheduled as WeatherCapturePriorityGuard. See docs/ops/streak-soak.md.
$ErrorActionPreference = "SilentlyContinue"

$caps = @(
    "weather.collection.snapshot_tracker",
    "weather.market.market_microstructure",
    "weather.operations.observation_trigger"
)
$want = [System.Diagnostics.ProcessPriorityClass]::AboveNormal

Get-CimInstance Win32_Process |
    Where-Object { $_.Name -in @("python.exe", "pythonw.exe") } |
    ForEach-Object {
        $cl = [string]$_.CommandLine
        foreach ($m in $caps) {
            if ($cl -like "*$m*") {
                $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
                if ($p -and $p.PriorityClass -ne $want) {
                    try { $p.PriorityClass = $want } catch {}
                }
                break
            }
        }
    }
exit 0
