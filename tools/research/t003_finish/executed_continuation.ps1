# Attended orchestration only. Every heavy child is the reviewed canonical runner.
[CmdletBinding()]
param([switch]$PlanOnly)
$ErrorActionPreference='Stop'
$taskRoot='C:\t\codex\T085'
$outRoot=Join-Path $taskRoot 'out'
$approvedCommit='8590d590fb5252cf14058b7e6fb2625eccb5ef97'
$approvedScript='3174d1cac7f6da3229804b6d8e414fe4a437d3f380a07d5f05e2b673c3f7f70d'
$approvedPrereg='73e8b665437b837108f28325ad3b26dd8983c0498a4c6d7e5ae04533011df902'
$scriptPath=Join-Path $outRoot 'scan.py'
$runnerPath=Join-Path $outRoot 'run_chunk.ps1'
$allItems=Get-Content C:\t\codex\T003\out\inventory.json -Raw | ConvertFrom-Json
$plan=@($allItems | Where-Object {$_.date -ge '2026-08-01' -and $_.date -le '2026-09-29'})
if($plan.Count -ne 720){throw 'Fixed permitted universe mismatch'}
$exitCode=1
$commitPaused=$false
function Write-ProgressRecord([string]$Phase,$Detail) {
    $record=@{recorded_utc=[DateTimeOffset]::UtcNow.ToString('o');phase=$Phase;detail=$Detail}
    $line=$record | ConvertTo-Json -Compress -Depth 6
    Add-Content -LiteralPath (Join-Path $outRoot 'continuation_events.jsonl') -Encoding utf8 -Value $line
    Write-Host $line
}
function Wait-Lightly([int]$Seconds,[string]$Reason) {
    $until=[DateTimeOffset]::UtcNow.AddSeconds($Seconds)
    while([DateTimeOffset]::UtcNow -lt $until){
        Write-ProgressRecord 'waiting' @{reason=$Reason;until_utc=$until.ToString('o')}
        $remaining=[int][Math]::Ceiling(($until-[DateTimeOffset]::UtcNow).TotalSeconds)
        if($remaining -gt 0){Start-Sleep -Seconds ([Math]::Min(60,$remaining))}
    }
}
function Assert-Pins {
    if((Get-FileHash -LiteralPath $scriptPath).Hash.ToLowerInvariant() -cne $approvedScript){throw 'Approved script bytes changed'}
    if((Get-FileHash -LiteralPath (Join-Path $taskRoot 'PREREG.md')).Hash.ToLowerInvariant() -cne $approvedPrereg){throw 'Frozen prereg changed'}
}
function Wait-AdmissionWindow {
    while($true){
        Assert-Pins
        $now=[DateTimeOffset]::UtcNow
        if($now -ge [DateTimeOffset]::Parse('2026-11-11T04:58:00Z')){throw 'Authorized November 10 execution window expired'}
        if($now -ge [DateTimeOffset]::Parse('2026-11-10T13:23:00Z') -and $now -lt [DateTimeOffset]::Parse('2026-11-11T00:00:00Z')){
            Wait-Lightly 60 '08:30 cutoff reserve; resume after 19:00 Toronto'
            continue
        }
        if(Test-Path -LiteralPath 'C:\t\codex\HOLD_HEAVY'){
            Wait-Lightly 300 'HOLD_HEAVY'
            continue
        }
        $mem=Get-CimInstance Win32_PerfRawData_PerfOS_Memory
        if($mem.CommitLimit -le 0){throw 'Cannot prove commit headroom'}
        $percent=100.0*[double]$mem.CommittedBytes/[double]$mem.CommitLimit
        if($percent -ge 90){$script:commitPaused=$true}
        if($script:commitPaused -and $percent -ge 88){
            Write-ProgressRecord 'commit_pause' @{commit_percent=$percent;resume_below=88}
            Wait-Lightly 600 'commit hysteresis'
            continue
        }
        $script:commitPaused=$false
        return
    }
}
function Invoke-ReviewedChunk([string]$Mode,[int]$Start,[int]$count) {
    Wait-AdmissionWindow
    Assert-Pins
    if(Test-Path -LiteralPath 'C:\t\codex\HOLD_HEAVY'){return 76}
    $stamp=[DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
    $log=Join-Path $outRoot ('wrapped-'+$Mode+'-'+$Start.ToString('D4')+'-'+$stamp+'.log')
    Write-ProgressRecord 'invoking' @{mode=$Mode;start=$Start;count=$count;log=$log;script_sha256=$approvedScript;reviewed_commit=$approvedCommit}
    $savedPreference=$ErrorActionPreference
    try{
        # Capture native stderr and inspect the actual exit code. A queued
        # resource refusal must reach the retry policy rather than throw here.
        $ErrorActionPreference='Continue'
        & powershell.exe -NoProfile -File $runnerPath -ReviewedCommit $approvedCommit -Mode $Mode -Start $Start -Count $count *> $log
        $code=$LASTEXITCODE
    }
    finally{$ErrorActionPreference=$savedPreference}
    Write-ProgressRecord 'child_exit' @{mode=$Mode;start=$Start;count=$count;exit_code=$code;log=$log}
    Get-Content -LiteralPath $log -Tail 4 | ForEach-Object {Write-Host $_}
    return [int]$code
}
function Find-Next([int]$Limit) {
    for($index=0;$index -lt $Limit;$index++){
        $eventPath=Join-Path (Join-Path $outRoot 'stream_events_v4_r2') ($plan[$index].event+'.json')
        if(-not(Test-Path -LiteralPath $eventPath)){return $index}
    }
    return $Limit
}
function Complete-Phase([int]$Limit) {
    while($true){
        $next=Find-Next $Limit
        if($next -eq $Limit){return}
        $count=[Math]::Min(30,$Limit-$next)
        $code=Invoke-ReviewedChunk 'scan' $next $count
        if($code -eq 0 -or $code -eq 78){
            $after=Find-Next $Limit
            Write-ProgressRecord 'progress' @{completed_prefix=$after;phase_limit=$Limit}
            if($after -le $next){throw 'No complete-event progress; stop instead of retrying an unbounded event'}
            Wait-Lightly 60 'successful or bounded-progress chunk yield'
        }
        elseif($code -eq 75){Wait-Lightly 600 'wrapper resource/queue refusal'}
        elseif($code -eq 76){Wait-Lightly 300 'HOLD'}
        else{throw "Fatal reviewed scanner/wrapper exit $code; no event skipped"}
    }
}
try{
    Assert-Pins
    if($PlanOnly){
        Write-ProgressRecord 'plan_only' @{permitted_events=$plan.Count;next_first393=(Find-Next 393);next_all720=(Find-Next 720);script_sha256=$approvedScript;prereg_sha256=$approvedPrereg;no_heavy_invoked=$true}
        $exitCode=0
        return
    }
    Write-ProgressRecord 'controller_started' @{pid=$PID;reviewed_commit=$approvedCommit}
    Wait-Lightly 60 'initial completed chunk yield'
    Complete-Phase 393
    $code=Invoke-ReviewedChunk 'compare' 0 1
    if($code -ne 0){throw "First-393 reproduction did not pass: $code"}
    Write-ProgressRecord 'reproduction_passed' (Get-Content (Join-Path $outRoot 'reproduction.json') -Raw | ConvertFrom-Json | Select-Object status,events,totals)
    Wait-Lightly 60 'comparison chunk yield'
    Complete-Phase 720
    $code=Invoke-ReviewedChunk 'aggregate' 0 1
    if($code -ne 0){throw "Aggregate did not complete: $code"}
    Write-ProgressRecord 'complete' (Get-Content (Join-Path $outRoot 'completion_statistics.json') -Raw | ConvertFrom-Json | Select-Object verdict,event_days,effective_dates,q10_any_positive_captures,consecutive_episodes,mean_daily_positive_event_fraction,descriptive_date_clustered_95_interval)
    $exitCode=0
}
catch{Write-ProgressRecord 'controller_stopped' @{error=$_.ToString();exit_code=$exitCode};$Host.UI.WriteErrorLine(($_ | Out-String).TrimEnd())}
finally{$Host.SetShouldExit($exitCode);exit $exitCode}
