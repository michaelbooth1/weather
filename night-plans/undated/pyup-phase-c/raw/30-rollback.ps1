Log 'ROLLBACK start'
$global:ReleaseOnNoGo = $false
function Test-Interp([string]$Exe, [string]$Tag) { if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
  (Invoke-Native $Exe @('-c','import weather.operations.execution_tape_supervisor, weather.operations.capture_resource_gate') "$N\probe-$Tag") -eq 0 }
$StatusFile = @{ snapshot='loop_status.json'; clob='clob_loop_status.json'; obs='observation_trigger_status.json'; tape='execution_tape_status.json' }
function Resolve-StopPy([string]$Key) {
  $rec = $null
  try { $s = Get-Content -LiteralPath (Join-Path $P "data\snapshots\$($StatusFile[$Key])") -Raw | ConvertFrom-Json
        $cmd = @($s.managed_process.expected_command); if ($cmd.Count -gt 0 -and $cmd[0]) { $rec = ([string]$cmd[0]).Trim().Trim('"') } } catch {}
  if ($rec) {
    $cand = Join-Path (Split-Path -Parent $rec) 'python.exe'     # same-directory sibling of the recorded argv[0]
    if (Test-Interp $cand "rec-$Key") { Log "$Key stop interpreter $cand (recorded $rec)"; return $cand }
    Log "ESCALATE: $Key recorded $rec but $cand does not import weather; using the probe fallback" }
  foreach ($c in @(@("$Old\Scripts\python.exe",'old'), @("$P\venv\Scripts\python.exe",'new'))) {
    if (Test-Interp $c[0] "$Key-$($c[1])") { Log "$Key stop interpreter $($c[0]) (probe fallback)"; return $c[0] } }
  Log "ESCALATE: no interpreter for $Key"; return $null }
$X = @{}; foreach ($sk in 'snapshot','clob','obs','tape') { $X[$sk] = Resolve-StopPy $sk }
$X.gate = @($X.snapshot, $X.clob, $X.obs, $X.tape | Where-Object { $_ })[0]     # the gate has no provenance check; any importable interpreter will do
$X | ConvertTo-Json | Set-Content "$N\rollback-interpreters.json" -Encoding utf8
Quiesce-Aux $X.tape -Soft         # idempotent: shadow STOP file, disable aux tasks, tape stop (already-stopped is fine), 88a stop (Q12)
if (-not $X.gate) { Log 'ESCALATE: no importable interpreter; capture stop verbs skipped, the holder sweep decides' }
elseif (-not (Stop-Capture $X -Soft)) { Log 'ESCALATE: capture stop not confirmed in 600 s; continuing to the swap-back' }
if (Test-Path -LiteralPath "$P\venv") { if (-not (Rename-WithSweep "$P\venv" 'venv-cp3119-failed' 'r1')) { NoGo 'ROLLBACK: new venv still held - ESCALATE (holders file in $N); lease kept, see below' } }
if (-not (Rename-WithSweep $Old 'venv' 'r2')) { NoGo 'ROLLBACK: venv-cp3110 cannot be renamed back - ESCALATE (holders file in $N); lease kept, see below' }
if ((& "$P\venv\Scripts\python.exe" -VV) -notlike 'Python 3.11.0*') { Log 'ESCALATE: venv not 3.11.0' }
if (Compare-Object (Mask-Editable (Get-Content "$A\freeze-3110.txt")) (Mask-Editable (& "$P\venv\Scripts\python.exe" -m pip freeze --all))) { Log 'ESCALATE: freeze differs' }
foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
$rb = Wait-Restore (Get-Date)
if ($rb) { Undo-Aux; Start-AuxHolders }
else { Log 'ESCALATE: capture not 3/3 - aux tasks (including any U6 export) left DISABLED' }
$rar = Get-ReleaseActive "$P\venv\Scripts\python.exe" "$N\rollback-active"; Assert-CaseA $rar 'rollback'
Release-Lease; Log 'ROLLBACK DONE'
