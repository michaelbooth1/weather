# PHASE-C retry wrapper (agent, 2026-10-22) for the night 2026-10-23/24 (files dated by the morning, 20261024).
# Owner GO, relayed by master-agent, verbatim "yes approve that for now": start at 00:30; up to 2 same-night retries until 03:30, ONLY for
# failures before the swap (before step C3, zero capture gap); any failure after the swap undoes itself and waits for the owner.
#
# What it does: runs phase-c-run-20261024.ps1 (same directory) as attempt 1, and re-runs it as attempt 2 or 3 only when the decision
# below says RETRY. It never touches the Scheduler, the lease, capture, git or any host state itself: all of that is the run file's.
# The decision is mechanical and fail-closed (Get-PyupcRetryDecision): it reads only the attempt's own transcript markers and exit code.
#
# Launch form: as a FILE, elevated, no redirects, from the local copy under C:\pyup\cp3119, after C0 has written c0-done-20261024.flag and
# master has written owner-go-20261024.txt (first token GO). Never press Ctrl+C in this window: the run file shares the console and
# touches the Scheduler.
#   Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File C:\pyup\cp3119\phase-c-retry-wrapper-20261024.ps1'
# Needs, next to it: phase-c-run-20261024.ps1 and SHA256SUMS.txt (the run file's line must match, or nothing starts).
#
# Transcripts: this wrapper C:\pyup\cp3119\phase-c-retry-transcript-20261024.txt; attempt n C:\pyup\cp3119\phase-c-transcript-20261024-a<n>.txt
#   (written by the run file). If any attempt transcript of the night already exists, the wrapper refuses: the attempt cap holds across launches.
#
# Decision table (first matching row wins; RETRY only in the last row):
#   exit 0 + DONE marker + EXIT code=0 marker                      -> SUCCESS          (wrapper exit 0)
#   exit 0 otherwise, a marker at or after C3, or SWAP              -> WAIT-FOR-OWNER   (wrapper exit 2)
#   exit 0 otherwise, no PYUPC-EXIT marker                          -> WAIT-FOR-OWNER   (RUN_FILE_DIED: no undo or verify ran)
#   exit 0 otherwise, all markers before C3                         -> STOPPED          (wrapper exit 1)
#   any marker at or after C3 (C3, SWAP, C5..C10, DONE)             -> WAIT-FOR-OWNER   (the run file's own C3 undo or §R ran; no retry)
#   exit 3 and no attempt transcript file at all                    -> STOPPED          (REFUSED_PRE_TRANSCRIPT: elevation, redirect, -Attempt/-RunId)
#   markers missing, unparseable, duplicated or out of order        -> WAIT-FOR-OWNER   (cannot prove the stop was before C3)
#   GO-REVIEW-WAIT marker (retry GO review blocked)                 -> WAIT-FOR-OWNER   (new non-allowlisted flag, new CRITICAL, no baseline; attempts 2..3 also HEAD or next-runs changed)
#   GATE-REFUSAL marker (PREFLIGHT, G3, C0, GO_REVIEW, C1, C1_THROW) -> STOPPED          (deterministic gate: a retry would refuse again)
#   no PYUPC-EXIT marker (killed or crashed run file)               -> WAIT-FOR-OWNER   (RUN_FILE_DIED: no undo or verify ran)
#   process exit code not 1 (3 refused, 4 owner hold, other crash)  -> STOPPED
#   EXIT marker missing or not code=1                               -> STOPPED
#   RESTORE-VERIFY marker missing                                   -> STOPPED
#   RESTORE-VERIFY result=FAIL                                      -> STOPPED
#   attempt cap: this was attempt 3                                 -> STOPPED
#   next start at or after 03:30 (owner cutoff)                     -> STOPPED
#   next start after 01:04 (the run file's C1 lease deadline)       -> STOPPED
#   otherwise (pre-C3 stop, exit 1, restore verified)               -> RETRY after a 60 s settle
# Final line, fixed format (one line, always printed, also on an interrupt):
#   PYUPC-RETRY-VERDICT night=20261024 run=<id> final=<SUCCESS|STOPPED|WAIT-FOR-OWNER> reason=<TOKEN> attempts=<n> last_exit=<c> last_stage=<S> wrapper_exit=<0|1|2|3>
# Wrapper exit: 0 SUCCESS; 1 STOPPED; 2 WAIT-FOR-OWNER; 3 refused before attempt 1. Anything but a successful attempt is nonzero.
# Dot-sourcing this file (". .\phase-c-retry-wrapper-20261024.ps1") defines the decision functions only and runs nothing (self-test use).

$script:PyupcStageRank = [ordered]@{ PREFLIGHT = 0; C0 = 1; C1 = 2; C2 = 3; C3 = 4; SWAP = 5; C5 = 6; C6 = 7; C7 = 8; C8 = 9; C9 = 10; C9B = 11; C9C = 12; C10 = 13; DONE = 14 }

function Get-PyupcAttemptEvidence([string[]]$Lines, [string]$RunId, [int]$Attempt) {
  # Parse one attempt transcript. Only lines that are exactly a marker (after Trim) and carry this run id and attempt count.
  $ev = [pscustomobject]@{ Parsed = $true; Problems = New-Object System.Collections.Generic.List[string]; Stages = New-Object System.Collections.Generic.List[string]
    MaxRank = -1; MaxStage = 'NONE'; Swap = $false; Done = $false; RestoreResult = $null; ExitMarkerCode = $null; Gate = $null; GoWait = $null }
  $nRestore = 0; $nExit = 0; $last = -1
  foreach ($raw in @($Lines)) {
    $l = "$raw".Trim()
    if (-not $l.StartsWith('PYUPC-')) { continue }
    if ($l -cmatch '^PYUPC-MARK run=(\S+) attempt=(\d+) stage=(\S+) at=(\S+)$') {
      if ($Matches[1] -cne $RunId -or [int]$Matches[2] -ne $Attempt) { continue }
      $st = $Matches[3]
      if (-not $script:PyupcStageRank.Contains($st)) { $ev.Problems.Add("unknown_stage_$st"); continue }
      $rk = [int]$script:PyupcStageRank[$st]
      if ($rk -le $last) { $ev.Problems.Add("stage_out_of_order_$st") }
      $last = [math]::Max($last, $rk); $ev.Stages.Add($st)
      if ($rk -gt $ev.MaxRank) { $ev.MaxRank = $rk; $ev.MaxStage = $st }
      if ($st -ceq 'SWAP') { $ev.Swap = $true }
      if ($st -ceq 'DONE') { $ev.Done = $true }
      continue }
    if ($l -cmatch '^PYUPC-RESTORE-VERIFY run=(\S+) attempt=(\d+) result=(PASS|FAIL) stage=(\S+) reasons=(\S+)$') {
      if ($Matches[1] -cne $RunId -or [int]$Matches[2] -ne $Attempt) { continue }
      $nRestore++; $ev.RestoreResult = $Matches[3]; continue }
    if ($l -cmatch '^PYUPC-EXIT run=(\S+) attempt=(\d+) code=(-?\d+) stage=(\S+)$') {
      if ($Matches[1] -cne $RunId -or [int]$Matches[2] -ne $Attempt) { continue }
      $nExit++; $ev.ExitMarkerCode = [int]$Matches[3]; continue }
    if ($l -cmatch '^PYUPC-GO-REVIEW-WAIT run=(\S+) attempt=(\d+) reason=([a-z0-9_]+)$') {
      if ($Matches[1] -cne $RunId -or [int]$Matches[2] -ne $Attempt) { continue }
      $ev.GoWait = $Matches[3]; continue }
    if ($l -cmatch '^PYUPC-GATE-REFUSAL run=(\S+) attempt=(\d+) gate=([A-Z0-9_]+)$') {
      if ($Matches[1] -cne $RunId -or [int]$Matches[2] -ne $Attempt) { continue }
      $ev.Gate = $Matches[3]; continue }
    if ($l -cmatch "^PYUPC-(MARK|RESTORE-VERIFY|EXIT|GATE-REFUSAL|GO-REVIEW-WAIT) run=$([regex]::Escape($RunId)) attempt=$Attempt ") { $ev.Problems.Add('malformed_marker') } }
  if ($ev.Stages.Count -eq 0 -or $ev.Stages[0] -cne 'PREFLIGHT') { $ev.Problems.Add('no_preflight_marker') }
  if ($nRestore -gt 1) { $ev.Problems.Add('restore_verify_repeated'); $ev.RestoreResult = 'FAIL' }
  if ($nExit -gt 1) { $ev.Problems.Add('exit_marker_repeated'); $ev.ExitMarkerCode = $null }
  if ($ev.Problems.Count) { $ev.Parsed = $false }
  $ev }

function Test-PyupcAttemptStart([datetime]$Now, [int]$NextAttempt, [int]$MaxAttempts) {
  # $null = attempt $NextAttempt may start now; otherwise the reason token. Clocks: README.md CLOCKS (floor 00:30, cutoff 03:30, lease deadline 01:04).
  if ($NextAttempt -gt $MaxAttempts) { return 'ATTEMPT_CAP' }
  if ($Now -lt $Now.Date.AddMinutes(30)) { return 'BEFORE_FLOOR_0030' }
  if ($Now -ge $Now.Date.AddHours(3).AddMinutes(30)) { return 'CUTOFF_0330' }
  if ($Now -gt $Now.Date.AddHours(1).AddMinutes(4)) { return 'LEASE_WINDOW_CLOSED_0104' }
  return $null }

function Get-PyupcRetryDecision($Evidence, [int]$ExitCode, [int]$Attempt, [int]$MaxAttempts, [datetime]$Now, [bool]$TranscriptExists = $true) {
  # Action: SUCCESS | RETRY | STOPPED | WAIT-FOR-OWNER. Purely mechanical; see the table in the header.
  $c3 = [int]$script:PyupcStageRank['C3']
  $post = ($Evidence.Swap -or $Evidence.MaxRank -ge $c3)
  $mk = { param($a, $r) [pscustomobject]@{ Action = $a; Reason = $r } }
  if ($ExitCode -eq 0) {
    if ($Evidence.Parsed -and $Evidence.Done -and $Evidence.ExitMarkerCode -eq 0) { return (& $mk 'SUCCESS' 'CUTOVER_PASS') }
    if ($post -or -not $Evidence.Parsed) { return (& $mk 'WAIT-FOR-OWNER' 'EXIT0_WITHOUT_DONE') }
    if ($null -eq $Evidence.ExitMarkerCode) { return (& $mk 'WAIT-FOR-OWNER' 'RUN_FILE_DIED') }   # (Fable Low 2) no PYUPC-EXIT: the run file died, no undo or restore verify ran
    return (& $mk 'STOPPED' 'EXIT0_WITHOUT_DONE') }
  if ($post) { return (& $mk 'WAIT-FOR-OWNER' "POST_C3_STOP_EXIT_$ExitCode") }
  if ($ExitCode -eq 3 -and -not $TranscriptExists) { return (& $mk 'STOPPED' 'REFUSED_PRE_TRANSCRIPT') }
  if (-not $Evidence.Parsed) { return (& $mk 'WAIT-FOR-OWNER' 'MARKERS_UNPARSEABLE') }
  if ($Evidence.GoWait) { return (& $mk 'WAIT-FOR-OWNER' "GO_REVIEW_DELTA_$($Evidence.GoWait)") }
  if ($Evidence.Gate) { return (& $mk 'STOPPED' "GATE_REFUSAL_$($Evidence.Gate)") }
  if ($null -eq $Evidence.ExitMarkerCode) { return (& $mk 'WAIT-FOR-OWNER' 'RUN_FILE_DIED') }   # (Fable Low 2) every exit after the transcript starts prints PYUPC-EXIT; none = killed or crashed, no undo or verify ran
  if ($ExitCode -ne 1) { return (& $mk 'STOPPED' "EXIT_${ExitCode}_NOT_RETRIABLE") }
  if ($Evidence.ExitMarkerCode -ne 1) { return (& $mk 'STOPPED' 'EXIT_MARKER_MISSING_OR_MISMATCH') }
  if (-not $Evidence.RestoreResult) { return (& $mk 'STOPPED' 'RESTORE_VERIFY_MISSING') }
  if ($Evidence.RestoreResult -cne 'PASS') { return (& $mk 'STOPPED' 'RESTORE_VERIFY_FAIL') }
  $gate = Test-PyupcAttemptStart $Now ($Attempt + 1) $MaxAttempts
  if ($gate) { return (& $mk 'STOPPED' $gate) }
  return (& $mk 'RETRY' 'PRE_C3_RESTORED') }

function Format-PyupcVerdict([string]$RunId, [string]$Final, [string]$Reason, [int]$Attempts, [string]$LastExit, [string]$LastStage, [int]$WrapperExit) {
  "PYUPC-RETRY-VERDICT night=20261024 run=$RunId final=$Final reason=$Reason attempts=$Attempts last_exit=$LastExit last_stage=$LastStage wrapper_exit=$WrapperExit" }

if ($MyInvocation.InvocationName -eq '.') { return }   # dot-sourced: functions only

# ---- main (only when run as a file)
$code = 1
$WTxStarted = $false; $WVerdictDone = $false; $WRunId = 'none'; $WAttempts = 0; $WLastExit = 'none'; $WLastStage = 'NONE'
try {
  $ErrorActionPreference = 'Stop'
  $WMax = 3; $WR = 'C:\pyup\cp3119'
  $WDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $WRun = Join-Path $WDir 'phase-c-run-20261024.ps1'
  $WWhy = $null
  if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $WWhy = 'NOT_ELEVATED' }
  elseif ([Console]::IsErrorRedirected -or [Console]::IsOutputRedirected) { $WWhy = 'STDIO_REDIRECTED' }
  elseif ((Get-Date).ToString('yyyyMMdd') -ne '20261024') { $WWhy = 'WRONG_NIGHT' }
  elseif ($WDir.TrimEnd('\') -ne $WR) { $WWhy = 'NOT_IN_CP3119' }   # (Fable 5) the kit runs only from its local copy in C:\pyup\cp3119
  elseif (-not (Test-Path -LiteralPath $WRun)) { $WWhy = 'RUN_FILE_MISSING' }
  elseif (@(Get-ChildItem -LiteralPath $WR -Filter 'phase-c-transcript-20261024-a*.txt' -ErrorAction SilentlyContinue).Count) { $WWhy = 'ATTEMPT_TRANSCRIPT_EXISTS' }
  else {
    # ---- PYUPC-SUMS-PREFLIGHT-BEGIN (the self-test extracts the lines between these two markers verbatim and runs them against a temp kit copy)
    $wSums = Join-Path $WDir 'SHA256SUMS.txt'
    $wLine = @(if (Test-Path -LiteralPath $wSums) { Get-Content -LiteralPath $wSums | Where-Object { ("$_".Trim() -split '\s+')[0] -ceq 'phase-c-run-20261024.ps1' } })
    if ($wLine.Count -ne 1) { $WWhy = 'RUN_FILE_NOT_IN_SHA256SUMS' }
    else { $wf = @("$($wLine[0])".Trim() -split '\s+'); $wSz = [long]-1   # (Fable nit) TryParse: a non-numeric size field refuses (exit 3), it never throws
      if ($wf.Count -ne 3 -or -not [long]::TryParse($wf[1], [Globalization.NumberStyles]::None, [Globalization.CultureInfo]::InvariantCulture, [ref]$wSz) -or $wSz -ne (Get-Item -LiteralPath $WRun).Length -or $wf[2].ToUpperInvariant() -cne (Get-FileHash -LiteralPath $WRun -Algorithm SHA256).Hash.ToUpperInvariant()) { $WWhy = 'RUN_FILE_HASH_MISMATCH' } }
    # ---- PYUPC-SUMS-PREFLIGHT-END
  }
  if ($WWhy) { $code = 3; Write-Host (Format-PyupcVerdict $WRunId 'STOPPED' "REFUSED_$WWhy" 0 'none' 'NONE' 3); $WVerdictDone = $true; return }
  Start-Transcript -LiteralPath (Join-Path $WR 'phase-c-retry-transcript-20261024.txt') -Append | Out-Null; $WTxStarted = $true
  $WRunId = '{0}-{1}' -f (Get-Date -Format 'HHmmss'), ([guid]::NewGuid().ToString('N').Substring(0, 6))
  Write-Host "PYUPC-RETRY start run=$WRunId run_file=$WRun at=$((Get-Date).ToString('o'))"
  $final = 'STOPPED'; $reason = 'NO_ATTEMPT'
  for ($n = 1; $n -le $WMax; $n++) {
    $gate = Test-PyupcAttemptStart (Get-Date) $n $WMax
    if ($gate) { $final = 'STOPPED'; $reason = $gate; break }
    $WAttempts = $n
    Write-Host "PYUPC-RETRY attempt=$n launch at=$((Get-Date).ToString('o'))"
    $wArgs = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Attempt {1} -RunId {2}' -f $WRun, $n, $WRunId
    $wp = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $wArgs -NoNewWindow -Wait -PassThru
    $wp.WaitForExit()
    $wExit = if ($null -eq $wp.ExitCode) { -9999 } else { [int]$wp.ExitCode }
    $wTx = Join-Path $WR "phase-c-transcript-20261024-a$n.txt"
    $wTxExists = Test-Path -LiteralPath $wTx
    $wLines = @(); try { if ($wTxExists) { $wLines = @(Get-Content -LiteralPath $wTx) } } catch { $wLines = @() }
    $ev = Get-PyupcAttemptEvidence $wLines $WRunId $n
    $dec = Get-PyupcRetryDecision $ev $wExit $n $WMax (Get-Date) $wTxExists
    $WLastExit = "$wExit"; $WLastStage = $ev.MaxStage
    Write-Host ("PYUPC-RETRY attempt={0} exit={1} last_stage={2} swap={3} restore={4} exit_marker={5} parsed={6} problems={7} action={8} reason={9}" -f $n, $wExit, $ev.MaxStage, $ev.Swap, $(if ($ev.RestoreResult) { $ev.RestoreResult } else { 'none' }), $(if ($null -ne $ev.ExitMarkerCode) { $ev.ExitMarkerCode } else { 'none' }), $ev.Parsed, $(if ($ev.Problems.Count) { $ev.Problems -join ';' } else { 'none' }), $dec.Action, $dec.Reason)
    $final = $dec.Action; $reason = $dec.Reason
    if ($dec.Action -ne 'RETRY') { break }
    Write-Host 'PYUPC-RETRY settle 60 s before the next attempt (the previous attempt restored its pre-state and released the lease)'
    Start-Sleep -Seconds 60
    $final = 'STOPPED'; $reason = 'NO_ATTEMPT' }
  if ($final -eq 'RETRY') { $final = 'STOPPED'; $reason = 'ATTEMPT_CAP' }
  $code = switch ($final) { 'SUCCESS' { 0 } 'WAIT-FOR-OWNER' { 2 } default { 1 } }
  if ($final -eq 'WAIT-FOR-OWNER') {
    Write-Host 'WAIT-FOR-OWNER: no retry. The run file has already run its own undo (C3 stop: Undo-Stop and restore; after the swap: §R, or a HOLD that keeps the lease until a RELEASE token). Do not relaunch. Read night.log for ESCALATE and OPERATOR CHECK lines and the last attempt transcript; if that transcript has no PYUPC-EXIT line, the run file died: follow "Wrapper process crashed or was killed" (kit raw md, Block 4). Message the owner.' }
  elseif ($final -eq 'STOPPED') {
    Write-Host 'STOPPED: no further attempt tonight. Read the last attempt transcript and night.log; exit 3 or 4 from the run file needs master or the owner, not a relaunch.' }
  Write-Host (Format-PyupcVerdict $WRunId $final $reason $WAttempts $WLastExit $WLastStage $code); $WVerdictDone = $true
}
catch { $code = 1; Write-Host "PYUPC-RETRY wrapper error: $($_.Exception.Message)" }
finally {
  if (-not $WVerdictDone) { if ($code -eq 0) { $code = 1 }; Write-Host (Format-PyupcVerdict $WRunId 'WAIT-FOR-OWNER' 'WRAPPER_INTERRUPTED_OR_ERROR' $WAttempts $WLastExit $WLastStage 2); $code = 2 }
  if ($WTxStarted) { try { Stop-Transcript | Out-Null } catch {} }
  $Host.SetShouldExit($code)
  exit $code }
