# Peak-window (12:00-18:00 ET) capture early-warning for the code-soak streak.
# Runs the streak checker in monitor mode; if TODAY is trending toward a `partial`
# grade (an in-window snapshot gap has already opened), it appends a timestamped
# alert so the forming gap is visible same-day instead of discovered at settlement.
# Lightweight: reads one small CSV + the ledger. Scheduled as WeatherStreakCaptureMonitor.
$ErrorActionPreference = "Stop"
$repo = "C:\Users\micha\Desktop\github\weather"
$py = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$script = Join-Path $repo "scripts\ops\streak_status.py"

$out = & $py $script --monitor --json 2>&1
$code = $LASTEXITCODE

if ($code -eq 3) {
    $alertDir = Join-Path $repo "data\alerts"
    if (-not (Test-Path $alertDir)) { New-Item -ItemType Directory -Path $alertDir -Force | Out-Null }
    $alertFile = Join-Path $alertDir "streak_capture_alerts.jsonl"
    $rec = [ordered]@{
        ts       = (Get-Date).ToString("o")
        level    = "AT_RISK"
        note     = "in-window snapshot gap forming during 12:00-18:00 ET peak window"
        report   = ($out -join "")
    } | ConvertTo-Json -Compress
    Add-Content -Path $alertFile -Value $rec -Encoding utf8
}
exit 0
