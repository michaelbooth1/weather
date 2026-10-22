$OldHomeNorm = (Get-Content "$R\oldhome.txt").Trim().TrimEnd('\'); $NewHomeNorm = $NewHome.TrimEnd('\')
function Get-VenvHolders([string]$Dir) {
  # Anchored with a trailing backslash, so a sibling worktree such as <checkout>-<name>\venv never matches.
  # The base-interpreter clause catches child processes of either home that name the production checkout.
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    $_.ExecutablePath -like "$Dir\*" -or $_.CommandLine -like "*$Dir\*" -or
    (($_.ExecutablePath -like "$OldHomeNorm\*" -or $_.ExecutablePath -like "$NewHomeNorm\*") -and $_.CommandLine -like "*$P\*") } |
    Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine }
function Rename-WithSweep([string]$From, [string]$To, [string]$Tag) {
  for ($i = 1; $i -le 3; $i++) {
    $hold = Get-VenvHolders $From; $hold | Format-List | Out-File "$N\holders-$Tag-try$i.txt"
    if ($hold) { Log "$Tag try $i holders $(($hold.ProcessId) -join ',')"; Start-Sleep 20; continue }
    try { Rename-Item -LiteralPath $From -NewName $To -ErrorAction Stop; return $true } catch { Log "$Tag rename try $i failed: $($_.Exception.Message)"; Start-Sleep 20 } }
  return $false }
# C3 + C4 guarded block. NoGo must not release the lease before the undo has run, so the catch releases it itself.
$global:ReleaseOnNoGo = $false
try {
  if (-not (Stop-Capture $Py)) { NoGo 'C3 stop not confirmed' }
  $GapStart = Get-Date; Log 'C3 capture stopped'
  if ((Get-Date) -gt (Get-Date).Date.AddHours(1).AddMinutes(30)) { NoGo 'swap deadline 01:30 passed' }
  if (-not (Rename-WithSweep (Join-Path $P 'venv') 'venv-cp3110' 'c4')) { NoGo 'C4 rename failed' }
} catch {
  $msg = $_.Exception.Message; Log "C3/C4 failed before the rename: $msg - undo, no swap"
  try { Undo-Stop } finally { Release-Lease }
  throw }
Log 'C4 renamed'                  # from here on a failure means §R, which keeps the lease
