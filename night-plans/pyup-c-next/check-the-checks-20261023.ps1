# CHECK-THE-CHECKS rehearsal for the Python-upgrade C night (night of 2026-10-23 to 2026-10-24, C0 at 00:30).
# READ-ONLY. It evaluates, against the live host, every predicate the C kit (phase-c0-run / phase-c-run at
# 353167c0e) and the runbook (HOST_PYTHON_UPGRADE_RUNBOOK.md at 15440ed4e) gate on, and changes nothing.
#
# Launch (elevated, like the kit: a non-elevated Get-ScheduledTask hides S4U tasks):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File <this file> [-OutFile C:\pyup\cp3119\check-the-checks.txt]
# Parameters default to the kit's host values. -KitTag is the date tag in the kit's operator file names
# (c0-done-<tag>.flag, owner-go-<tag>.txt); it defaults to -NightDate as yyyyMMdd. Pass it explicitly if the
# re-dated kit uses another tag.
#
# Output: one line per predicate
#   CHECK <id> | read=<value> | expected=<value> | PASS|WOULD-FAIL|NOT-EVALUABLE
# then one SUMMARY line. The id carries the kit line it mirrors (run:N = phase-c-run, c0:N = phase-c0-run).
# Clock predicates are judged at the planned times on -NightDate (C0 00:30, C launch 01:00); the read field
# also carries the current clock. Exit 0 for a completed rehearsal (the verdict is in the output); exit 2 only
# when the self-check below refuses to run.
#
# Read-only contract (enforced by the self-check before anything touches the host):
# - commands: Get-ScheduledTask, Get-ScheduledTaskInfo, Get-Process, Get-CimInstance, Test-Path, Get-Content,
#   Get-Item, git (rev-parse / status / show only, with --no-optional-locks so status never rewrites the index),
#   plus the pure pipeline helpers Get-Date, Join-Path, Split-Path, Where-Object, ForEach-Object, Sort-Object,
#   Select-Object, Measure-Object, ConvertFrom-Json, Write-Output; no dot-sourcing, no dynamic invocation
#   except "& $Body" on this file's own literal script blocks; no file redirection;
# - .NET: files open only with FileMode Open and FileAccess Read (share ReadWrite|Delete, so a writer's atomic
#   replace is never blocked); the lease mutex is opened only with OpenExisting(name, MutexRights Synchronize)
#   and never waited on; the only write is one WriteAllLines to -OutFile when the operator passes it.
# - G3 (master's rule for this night): HEAD = the qualified tip, OR all of (i) no dependency file (requirements*,
#   pyproject.toml, *.lock, constraints*, setup.cfg, setup.py, any depth) differs between the qualified tip and HEAD;
#   (ii) git diff --name-only <pregate tested sha> HEAD has no path outside ^docs/.+\.md$ (the tested tree carries the
#   full workstation pre-gate PASS on 3.11.9, -PregateReceiptId); (iii) every other C0 predicate is clean. It is
#   printed last as CHECK G3. The pre-gate receipt is workstation evidence; pass -PregateReceiptPath to have its
#   verdict and head read too.
# - No repo script is dot-sourced: the lease and memory-guard predicates are re-implemented here.
[CmdletBinding()]
param(
    [string]$RepoRoot = 'C:\Users\micha\Desktop\github\weather',
    [string]$KitRoot = 'C:\pyup\cp3119',
    [string]$NewHome = 'C:\Program Files\Python311-cp3119',
    [string]$NightDate = '2026-10-24',
    [string]$KitTag = '',
    [string]$QualifiedTip = '90b2e1844ad0de71916c67996026dea7b04ce5ff',
    [string]$PregateReceiptId = 'pg-739c03eff1e2-20261018T045220-105120',
    [string]$PregateTestedSha = '739c03eff1e2f26c49759899e4e39b669d2c6628',
    [string]$PregateReceiptPath = '',
    [string]$OutFile = ''
)

# ---------------------------------------------------------------------------------------------------------
# Static read-only self-check of this file's own AST
# ---------------------------------------------------------------------------------------------------------
$SelfAllowedCommands = @(
    'Get-ScheduledTask', 'Get-ScheduledTaskInfo', 'Get-Process', 'Get-CimInstance', 'Test-Path', 'Get-Content',
    'Get-Item', 'git', 'Get-Date', 'Join-Path', 'Split-Path', 'Where-Object', 'ForEach-Object', 'Sort-Object',
    'Select-Object', 'Measure-Object', 'ConvertFrom-Json', 'Write-Output')
$SelfDeniedMembers = @(
    'WaitOne', 'WaitAny', 'WaitAll', 'SignalAndWait', 'ReleaseMutex', 'Delete', 'Kill', 'Create', 'CreateDirectory',
    'CreateSubdirectory', 'CreateText', 'AppendText', 'OpenWrite', 'OpenSubKey', 'CreateSubKey', 'Move', 'MoveTo',
    'Copy', 'CopyTo', 'Replace', 'SetLength', 'Flush', 'WriteAllText', 'WriteAllBytes',
    'AppendAllText', 'AppendAllLines', 'SetAccessControl', 'Start', 'Terminate', 'InvokeMethod', 'Invoke',
    'InvokeReturnAsIs', 'SetValue', 'DeleteValue', 'SetShouldExit')
$SelfDeniedFunctionName = '^(Disable|Enable|Stop|Start|Register|Unregister|Set|New|Remove|Rename|Clear|Restart|Invoke|Out|Export|Add-Content|Copy|Move)-'

function Test-SelfReadOnly([string]$Path) {
    $problems = [Collections.Generic.List[string]]::new()
    $tokens = $null; $parseErrors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$parseErrors)
    if (@($parseErrors).Count) { $problems.Add("parse errors: $(@($parseErrors).Count)") }
    $defined = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true) | ForEach-Object { $_.Name })
    foreach ($fn in $defined) { if ($fn -match $SelfDeniedFunctionName -or $SelfAllowedCommands -contains $fn) { $problems.Add("function name $fn shadows a mutating or allowed command") } }
    foreach ($c in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] }, $true)) {
        $line = $c.Extent.StartLineNumber
        if ($c.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Dot) { $problems.Add("dot-source at line $line"); continue }
        $name = $c.GetCommandName()
        if (-not $name) {
            $first = $c.CommandElements[0]
            if ($c.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Ampersand -and
                $first -is [Management.Automation.Language.VariableExpressionAst] -and $first.VariablePath.UserPath -ceq 'Body') { continue }
            $problems.Add("dynamic invocation at line $line"); continue }
        if ($defined -contains $name) { continue }
        if ($SelfAllowedCommands -notcontains $name) { $problems.Add("command '$name' at line $line is not on the read-only allowlist"); continue }
        if ($name -eq 'git') {
            $els = @($c.CommandElements | Select-Object -Skip 1); $i = 0; $sub = $null
            while ($i -lt $els.Count) {
                $t = $els[$i].Extent.Text
                if ($t -ceq '--no-optional-locks') { $i++; continue }
                if ($t -ceq '-C') { $i += 2; continue }
                $sub = $t; break }
            if ($sub -cnotin @('rev-parse', 'status', 'show', 'diff')) { $problems.Add("git '$sub' at line $line is not read-only") }
            if ($sub -ceq 'diff' -and (-not @($els | Where-Object { $_.Extent.Text -ceq '--name-only' }).Count -or -not @($els | Where-Object { $_.Extent.Text -ceq '--no-ext-diff' }).Count)) { $problems.Add("git diff at line $line is not --no-ext-diff --name-only") }
            if ($sub -ceq 'status' -and -not @($els | Where-Object { $_.Extent.Text -ceq '--no-optional-locks' }).Count) { $problems.Add("git status at line $line lacks --no-optional-locks") } }
    }
    $writeAllLines = 0
    foreach ($m in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] }, $true)) {
        $line = $m.Extent.StartLineNumber
        if ($m.Member -isnot [Management.Automation.Language.StringConstantExpressionAst]) { $problems.Add("dynamic member call at line $line"); continue }
        $mn = $m.Member.Value; $margs = @($m.Arguments)
        if ($SelfDeniedMembers -contains $mn) { $problems.Add(".$mn() at line $line is denied"); continue }
        if ($mn -in 'Write', 'WriteLine' -and $m.Expression.Extent.Text -cne '[Console]::Out') { $problems.Add(".$mn() at line $line is not [Console]::Out") }
        if ($mn -eq 'new' -and $m.Expression.Extent.Text -match 'Writer|FileStream|FileInfo|DirectoryInfo|Mutex|Semaphore|WaitHandle|Process') { $problems.Add("::new() of $($m.Expression.Extent.Text) at line $line is denied") }
        if ($mn -eq 'Open') {
            if ($margs.Count -ne 4 -or $margs[1].Extent.Text -cne '[IO.FileMode]::Open' -or $margs[2].Extent.Text -cne '[IO.FileAccess]::Read') { $problems.Add("Open at line $line is not FileMode Open + FileAccess Read") } }
        if ($mn -eq 'OpenExisting') {
            if ($margs.Count -ne 2 -or $margs[1].Extent.Text -cne '[Security.AccessControl.MutexRights]::Synchronize') { $problems.Add("OpenExisting at line $line is not Synchronize-only") } }
        if ($mn -eq 'WriteAllLines') {
            $writeAllLines++
            if ($margs.Count -lt 1 -or $margs[0].Extent.Text -cne '$OutFile') { $problems.Add("WriteAllLines at line $line does not target `$OutFile") } }
    }
    if ($writeAllLines -gt 1) { $problems.Add("more than one WriteAllLines ($writeAllLines)") }
    foreach ($r in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FileRedirectionAst] }, $true)) { $problems.Add("file redirection at line $($r.Extent.StartLineNumber)") }
    return , $problems
}

# ---------------------------------------------------------------------------------------------------------
# Result accumulation
# ---------------------------------------------------------------------------------------------------------
$script:Lines = [Collections.Generic.List[string]]::new()
$script:Count = @{ 'PASS' = 0; 'WOULD-FAIL' = 0; 'NOT-EVALUABLE' = 0 }
$script:FailIds = [Collections.Generic.List[string]]::new()
$script:Verdicts = [ordered]@{}

function Format-CheckValue($Value) {
    $s = if ($null -eq $Value) { '<null>' } elseif ($Value -is [array]) { ($Value | ForEach-Object { [string]$_ }) -join ', ' } else { [string]$Value }
    $s = ($s -replace '[\r\n]+', ' ') -replace '\|', '/'
    if ($s.Length -gt 400) { $s = $s.Substring(0, 397) + '...' }
    if ($s -eq '') { $s = '<empty>' }
    return $s
}
function Push-Check([string]$Id, $Read, $Expected, [string]$Verdict) {
    if ($Verdict -cnotin @('PASS', 'WOULD-FAIL', 'NOT-EVALUABLE')) { $Verdict = 'NOT-EVALUABLE' }
    $line = 'CHECK {0} | read={1} | expected={2} | {3}' -f $Id, (Format-CheckValue $Read), (Format-CheckValue $Expected), $Verdict
    $script:Lines.Add($line); $script:Count[$Verdict]++; $script:Verdicts[$Id] = $Verdict
    if ($Verdict -ne 'PASS') { $script:FailIds.Add("$Id=$Verdict") }
    Write-Output $line
}
# Every check body runs here, so one throwing predicate cannot stop the rehearsal.
function Use-Check([string]$Id, $Expected, [scriptblock]$Body) {
    try { $r = @(& $Body); Push-Check $Id $r[0] $Expected ([string]$r[1]) }
    catch { Push-Check $Id ("error: " + $_.Exception.Message) $Expected 'NOT-EVALUABLE' }
}
function Get-Verdict([bool]$Ok) { if ($Ok) { 'PASS' } else { 'WOULD-FAIL' } }

# ---------------------------------------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------------------------------------
function Read-SharedText([string]$Path) {
    $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
    try {
        $sr = [IO.StreamReader]::new($fs, [Text.UTF8Encoding]::new($false), $true)
        try { $text = $sr.ReadToEnd() } finally { $sr.Dispose() }
    } finally { $fs.Dispose() }
    return $text.TrimStart([char]0xFEFF)
}
function Read-SharedJson([string]$Path) { (Read-SharedText $Path) | ConvertFrom-Json }
function Get-FileSha256([string]$Path) {
    $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
    $fs = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
    try {
        $h = [Security.Cryptography.SHA256Managed]::new()
        try { return (-join ($h.ComputeHash($fs) | ForEach-Object { $_.ToString('X2') })) } finally { $h.Dispose() }
    } finally { $fs.Dispose() }
}
function Get-TaskExact([string]$Name) { @(Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) }
function Get-SpanSeconds([string]$Iso) { if (-not $Iso) { return $null }; [Xml.XmlConvert]::ToTimeSpan($Iso).TotalSeconds }
function Get-KitFirstToken([string]$Path) { ((Get-Content -LiteralPath $Path -TotalCount 1) -split '\s+')[0] }   # the kit's q12 / q12b / gap form (no Trim)

# Would this trigger fire in [From, To)? $null = trigger kind not modelled (caller falls back to NextRunTime).
function Test-TriggerFiresIn($Trigger, [datetime]$From, [datetime]$To) {
    if ($Trigger.Enabled -eq $false) { return $false }
    $sbText = [string]$Trigger.StartBoundary; if (-not $sbText) { return $false }
    $inv = [Globalization.CultureInfo]::InvariantCulture
    $sb = [datetime]::Parse($sbText, $inv)
    if ([string]$Trigger.EndBoundary) { if ([datetime]::Parse([string]$Trigger.EndBoundary, $inv) -lt $From) { return $false } }
    $cls = [string]$Trigger.CimClass.CimClassName
    $bases = @()
    if ($cls -eq 'MSFT_TaskTimeTrigger') { $bases = @($sb) }
    elseif ($cls -eq 'MSFT_TaskDailyTrigger') { foreach ($d in @($From.Date.AddDays(-1), $From.Date)) { $b = $d + $sb.TimeOfDay; if ($b -ge $sb) { $bases += $b } } }
    elseif ($cls -eq 'MSFT_TaskWeeklyTrigger') {
        foreach ($d in @($From.Date.AddDays(-1), $From.Date)) { $bit = [int][math]::Pow(2, [int]$d.DayOfWeek); $b = $d + $sb.TimeOfDay
            if ((([int]$Trigger.DaysOfWeek) -band $bit) -and $b -ge $sb) { $bases += $b } } }
    elseif ($cls -in @('MSFT_TaskLogonTrigger', 'MSFT_TaskBootTrigger', 'MSFT_TaskEventTrigger', 'MSFT_TaskIdleTrigger', 'MSFT_TaskSessionStateChangeTrigger', 'MSFT_TaskRegistrationTrigger')) { return $false }
    else { return $null }
    $iv = [string]$Trigger.Repetition.Interval; $du = [string]$Trigger.Repetition.Duration
    foreach ($b in $bases) {
        if ($b -ge $From -and $b -lt $To) { return $true }
        if ($iv -and $b -lt $From) {
            $ivs = Get-SpanSeconds $iv; if (-not $ivs -or $ivs -le 0) { continue }
            $end = if ($du) { $b.AddSeconds((Get-SpanSeconds $du)) } else { [datetime]::MaxValue }
            $k = [math]::Ceiling(($From - $b).TotalSeconds / $ivs); $next = $b.AddSeconds($k * $ivs)
            if ($next -lt $To -and $next -le $end) { return $true } } }
    return $false
}
function Test-TaskDueIn($Task, [datetime]$From, [datetime]$To) {
    $unmodelled = $false
    foreach ($tr in @($Task.Triggers)) { $f = Test-TriggerFiresIn $tr $From $To; if ($f -eq $true) { return $true }; if ($null -eq $f) { $unmodelled = $true } }
    $info = Get-ScheduledTaskInfo -InputObject $Task -ErrorAction SilentlyContinue
    if ($info -and $info.NextRunTime -and $info.NextRunTime -ge $From -and $info.NextRunTime -lt $To) { return $true }
    if ($unmodelled -and $info -and $info.NextRunTime -and $info.NextRunTime -lt $To) { return $true }   # fail towards listing it
    return $false
}

# ---------------------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------------------
$exitCode = 0
$ErrorActionPreference = 'Stop'   # a throwing read lands in its Use-Check catch as NOT-EVALUABLE
try {
    if (-not $PSCommandPath) { Write-Output 'REFUSED: run this as a file (-File) so the self-check can read its own AST'; $exitCode = 2; return }
    $selfProblems = Test-SelfReadOnly $PSCommandPath
    if ($selfProblems.Count) { foreach ($sp in $selfProblems) { Write-Output "REFUSED: self-check: $sp" }; $exitCode = 2; return }
    Write-Output "SELF-CHECK read-only AST assert PASS ($PSCommandPath)"

    $P = $RepoRoot.TrimEnd('\'); $R = $KitRoot.TrimEnd('\')
    $Now = Get-Date
    $Night = [datetime]::ParseExact($NightDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    $Tag = if ($KitTag) { $KitTag } else { $Night.ToString('yyyyMMdd') }
    $PlanC0 = $Night.AddMinutes(30); $PlanC = $Night.AddHours(1)
    $NowText = $Now.ToString('yyyy-MM-dd HH:mm')
    $IsElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $Missing = if ($IsElevated) { 'WOULD-FAIL' } else { 'NOT-EVALUABLE' }   # non-elevated, Get-ScheduledTask hides S4U tasks
    $Py = Join-Path $P 'venv\Scripts\python.exe'; $A = Join-Path $R 'receipts-3110'; $WH = Join-Path $R 'wheelhouse'
    $NewPy = Join-Path $NewHome 'python.exe'; $Old = Join-Path $P 'venv-cp3110'
    $Sup = @('WeatherSnapshotLoopSupervisor', 'WeatherClobBookLoopSupervisor', 'WeatherObservationTriggerSupervisor')
    $NightN = Join-Path $R ('night-' + $Night.ToString('yyyyMMdd'))
    Write-Output ("CONTEXT host={0} elevated={1} now={2} night={3} tag={4} P={5} R={6} NewHome={7}" -f $env:COMPUTERNAME, $IsElevated, $NowText, $NightDate, $Tag, $P, $R, $NewHome)

    # --- wrapper preflight (phase-c-run lines 23-39; phase-c0-run 15-16)
    Use-Check 'PF-ELEVATED(run:23,c0:15)' 'True (launch the kit elevated)' { $IsElevated; (Get-Verdict $IsElevated) }
    Use-Check 'PF-STDIO-NOT-REDIRECTED(run:24,c0:16)' 'err=False out=False (this session; the kit refuses a redirected launch)' {
        $e = [Console]::IsErrorRedirected; $o = [Console]::IsOutputRedirected; "err=$e out=$o"; (Get-Verdict (-not $e -and -not $o)) }
    Use-Check 'PF-C0-FLAG(run:30-33)' "c0-done-$Tag.flag written on $NightDate with head=<40-hex>" {
        $f = Join-Path $R "c0-done-$Tag.flag"
        if (-not (Test-Path -LiteralPath $f)) { "absent now: C0 writes it at ~00:30 on $NightDate"; 'NOT-EVALUABLE'; return }
        $it = Get-Item -LiteralPath $f; $l1 = "$(Get-Content -LiteralPath $f -TotalCount 1)"
        if ($it.LastWriteTime -lt $Night) { "present but written $($it.LastWriteTime.ToString('yyyy-MM-dd HH:mm')) (C0 removes it and rewrites it tonight)"; 'NOT-EVALUABLE'; return }
        "$l1"; (Get-Verdict ($l1 -match 'head=([0-9a-f]{40})')) }
    Use-Check 'PF-OWNER-GO(run:35-36)' "owner-go-$Tag.txt first token GO (case-sensitive)" {
        $f = Join-Path $R "owner-go-$Tag.txt"
        if (-not (Test-Path -LiteralPath $f)) { 'absent now: written after the owner GO at the C0 review'; 'NOT-EVALUABLE'; return }
        $tok = ("$(Get-Content -LiteralPath $f -TotalCount 1)".Trim() -split '\s+')[0]
        "first token '$tok' (written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm')))"; (Get-Verdict ($tok -ceq 'GO')) }
    Use-Check 'PF-CLOCK-0100-0104(run:37-38)' "launch in [01:00, 01:04] on $NightDate" {
        $ok = $PlanC -ge $PlanC.Date.AddHours(1) -and $PlanC -le $PlanC.Date.AddHours(1).AddMinutes(4)
        "now=$NowText (would refuse now: $(-not ($Now -ge $Now.Date.AddHours(1) -and $Now -le $Now.Date.AddHours(1).AddMinutes(4)))); planned=$($PlanC.ToString('yyyy-MM-dd HH:mm'))"; (Get-Verdict $ok) }

    # --- section 6 header, paths, and files the later blocks read (run:118-194)
    Use-Check 'HDR-REPO-ROOT(run:119)' "$P exists with .git" { $ok = (Test-Path -LiteralPath $P) -and (Test-Path -LiteralPath (Join-Path $P '.git')); "exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'HDR-KIT-ROOT(run:121-123,129)' 'R, R\tools and R\receipts-3110 exist (the kit New-Items them; existing evidence expected)' {
        $s = @($R, (Join-Path $R 'tools'), $A | ForEach-Object { "$(Split-Path -Leaf $_)=$(Test-Path -LiteralPath $_)" }); ($s -join ' '); (Get-Verdict (-not ($s -match '=False'))) }
    $K = $null
    Use-Check 'HDR-CONSTANTS(run:130-131,207,448)' 'constants.json present; nupkg_url nupkg_size nupkg_sha512_b64 tools_manifest_sha256 binary_signer_thumbprint vv_prefix binaries non-empty' {
        $f = Join-Path $R 'constants.json'
        if (-not (Test-Path -LiteralPath $f)) { 'absent ($K null: C6 launcher check would NO-GO -> section R)'; 'WOULD-FAIL'; return }
        $script:K = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
        $miss = @('nupkg_url', 'nupkg_size', 'nupkg_sha512_b64', 'tools_manifest_sha256', 'binary_signer_thumbprint', 'vv_prefix', 'binaries') | Where-Object { -not $script:K.$_ }
        "missing=[$($miss -join ',')] vv_prefix='$($script:K.vv_prefix)'"; (Get-Verdict (-not $miss.Count)) }
    $K = $script:K
    Use-Check 'HDR-ADMISSION-HELPER(run:193)' 'scripts\ops\workload_admission.ps1 defines Enter-/Exit-WeatherHeavyWorkloadLease and Get-WeatherHeavyWorkloadLeaseState' {
        $f = Join-Path $P 'scripts\ops\workload_admission.ps1'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-Content -LiteralPath $f -Raw
        $have = @('Enter-WeatherHeavyWorkloadLease', 'Exit-WeatherHeavyWorkloadLease', 'Get-WeatherHeavyWorkloadLeaseState') | Where-Object { $t -match ('(?m)^function ' + [regex]::Escape($_) + '\b') }
        "defines=[$($have -join ',')]"; (Get-Verdict ($have.Count -eq 3)) }
    Use-Check 'HDR-MEMGUARD-HELPER(run:194)' 'scripts\ops\memory_guard_status_reader.ps1 defines Read-WeatherMemoryGuardStatus' {
        $f = Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $ok = (Get-Content -LiteralPath $f -Raw) -match '(?m)^function Read-WeatherMemoryGuardStatus\b'; "defines=$ok"; (Get-Verdict $ok) }
    Use-Check 'HDR-STATUS-PS1(run:270,469,509)' 'scripts\ops\status.ps1 present' { $ok = Test-Path -LiteralPath (Join-Path $P 'scripts\ops\status.ps1'); "exists=$ok"; (Get-Verdict $ok) }

    $OldHomeLines = @(); $OldHome = $null
    if (Test-Path -LiteralPath (Join-Path $R 'oldhome.txt')) { $OldHomeLines = @(Get-Content -LiteralPath (Join-Path $R 'oldhome.txt')); $OldHome = "$(Get-Content -LiteralPath (Join-Path $R 'oldhome.txt') -TotalCount 1)".Trim() }
    Use-Check 'C0-OLDHOME-SINGLE-LINE(run:264,c0:163)' 'oldhome.txt exists; first line non-empty; exactly one non-empty line' {
        if (-not (Test-Path -LiteralPath (Join-Path $R 'oldhome.txt'))) { 'absent'; 'WOULD-FAIL'; return }
        $ne = @($OldHomeLines | Where-Object { "$_".Trim() }).Count
        "first='$OldHome' non_empty_lines=$ne"; (Get-Verdict ([bool]$OldHome -and $ne -eq 1)) }
    Use-Check 'PATH-OLDHOME-PYTHON(run:133,410,416)' '<oldhome>\python.exe exists (the 3.11.0 base the C4 sweep and Test-Venv use)' {
        if (-not $OldHome) { 'oldhome unknown'; 'WOULD-FAIL'; return }; $f = Join-Path $OldHome 'python.exe'; $ok = Test-Path -LiteralPath $f; "$f exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'PATH-PROD-PYTHON(run:120)' "$Py exists" { $ok = Test-Path -LiteralPath $Py; "exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'PATH-PROD-PYVENV(run:93,207-209)' 'venv\pyvenv.cfg home = oldhome and version 3.11.0 (pre-swap)' {
        $f = Join-Path $P 'venv\pyvenv.cfg'; if (-not (Test-Path -LiteralPath $f)) { 'pyvenv.cfg absent'; 'WOULD-FAIL'; return }
        $cfg = @(Get-Content -LiteralPath $f)
        $home1 = @($cfg | Where-Object { $_ -match '^home\s*=' } | ForEach-Object { ($_ -replace '^home\s*=\s*', '').Trim() })[0]
        $ver = @($cfg | Where-Object { $_ -match '^(version|version_info)\s*=' } | ForEach-Object { ($_ -replace '^[a-z_]+\s*=\s*', '').Trim() })[0]
        $ok = $OldHome -and $home1 -and ($home1.TrimEnd('\') -eq $OldHome.TrimEnd('\')) -and "$ver".StartsWith('3.11.0')
        "home='$home1' version='$ver'"; (Get-Verdict $ok) }
    Use-Check 'C0-OLD-VENV-ABSENT(run:263,c0:162)' "$Old absent" { $ex = Test-Path -LiteralPath $Old; "exists=$ex"; (Get-Verdict (-not $ex)) }
    Use-Check 'C4-PROD-VENV-PRESENT(run:433)' "$P\venv exists (the C4 rename source)" { $ok = Test-Path -LiteralPath (Join-Path $P 'venv'); "exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'PATH-NEWHOME(run:124-125,442)' 'new home python.exe and pythonw.exe exist' {
        $s = @('python.exe', 'pythonw.exe' | ForEach-Object { "$_=$(Test-Path -LiteralPath (Join-Path $NewHome $_))" }); ($s -join ' '); (Get-Verdict (-not ($s -match '=False'))) }
    Use-Check 'C6-LAUNCHER-SOURCE(run:448)' 'sha256 of <newhome>\Lib\venv\scripts\nt\python(w).exe equals constants.json binaries (venv copies these launchers)' {
        if (-not $K -or -not $K.binaries) { 'constants.json binaries unavailable'; 'WOULD-FAIL'; return }
        $parts = @(); $ok = $true
        foreach ($ln in 'python.exe', 'pythonw.exe') { $key = "Lib\venv\scripts\nt\$ln"; $src = Join-Path $NewHome $key
            if (-not (Test-Path -LiteralPath $src)) { $parts += "$ln=absent"; $ok = $false; continue }
            $h = Get-FileSha256 $src; $want = ([string]$K.binaries.$key).ToUpper(); $m = $h -eq $want; if (-not $m) { $ok = $false }
            $parts += "$ln match=$m" }
        ($parts -join ' ; '); (Get-Verdict $ok) }
    Use-Check 'C5-LOCK-WHEELHOUSE(run:199-202)' 'lock-hashed.txt has pip/setuptools/wheel pins with hashes; wheelhouse holds .whl files' {
        $lf = Join-Path $R 'lock-hashed.txt'; if (-not (Test-Path -LiteralPath $lf)) { 'lock-hashed.txt absent'; 'WOULD-FAIL'; return }
        $lt = @(Get-Content -LiteralPath $lf); $tools = @($lt | Where-Object { $_ -match '^(pip|setuptools|wheel)==' }).Count; $hashes = @($lt | Where-Object { $_ -match '--hash=sha256:' }).Count
        $whl = @(Get-Item -Path (Join-Path $WH '*.whl') -ErrorAction SilentlyContinue).Count
        "tool_pins=$tools hash_lines=$hashes wheels=$whl"; (Get-Verdict ($tools -eq 3 -and $hashes -gt 0 -and $whl -gt 0)) }
    Use-Check 'C6-RECEIPTS-3110(run:212,235,298)' 'receipts-3110\freeze-3110.txt and rtv-3110.json present; rtv parses with python 3.11.0' {
        $fz = Join-Path $A 'freeze-3110.txt'; $rt = Join-Path $A 'rtv-3110.json'
        if (-not (Test-Path -LiteralPath $fz) -or -not (Test-Path -LiteralPath $rt)) { "freeze=$(Test-Path -LiteralPath $fz) rtv=$(Test-Path -LiteralPath $rt)"; 'WOULD-FAIL'; return }
        $o = Get-Content -LiteralPath $rt -Raw | ConvertFrom-Json
        "freeze_lines=$(@(Get-Content -LiteralPath $fz).Count) rtv.python=$($o.python) implementation=$($o.implementation)"; (Get-Verdict ([string]$o.python -eq '3.11.0')) }
    Use-Check 'C1-FREEZE-UNCHANGED-APPROX(run:297-298)' 'installed dist-info set equals receipts-3110\freeze-3110.txt (approximation: dist-info scan, not pip freeze)' {
        $fz = Join-Path $A 'freeze-3110.txt'; $sp = Join-Path $P 'venv\Lib\site-packages'
        if (-not (Test-Path -LiteralPath $fz) -or -not (Test-Path -LiteralPath $sp)) { 'freeze or site-packages absent'; 'NOT-EVALUABLE'; return }
        $fl = @(Get-Content -LiteralPath $fz)
        $editable = @($fl | Where-Object { $_ -match '#egg=([A-Za-z0-9_.\-]+)' } | ForEach-Object { if ($_ -match '#egg=([A-Za-z0-9_.\-]+)') { ($Matches[1].ToLower() -replace '[-_.]+', '_') } })
        $want = @($fl | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==' } | ForEach-Object { $n, $v = $_ -split '==', 2; (($n.ToLower() -replace '[-_.]+', '_') + '==' + $v.Trim()) } | Sort-Object -Unique)
        $have = @(Get-Item -Path (Join-Path $sp '*.dist-info') -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Name -match '^(.+?)-([^-]+)\.dist-info$') { $n = $Matches[1].ToLower() -replace '[-_.]+', '_'; if ($editable -notcontains $n) { "$n==$($Matches[2])" } } } | Sort-Object -Unique)
        $miss = @($want | Where-Object { $have -notcontains $_ }); $extra = @($have | Where-Object { $want -notcontains $_ })
        "freeze_pins=$($want.Count) dist_info=$($have.Count) missing=[$($miss -join ',')] extra=[$($extra -join ',')]"; (Get-Verdict (-not $miss.Count -and -not $extra.Count)) }

    # --- C0 GO checks (phase-c-run 241-277 = phase-c0-run 145-176)
    $q = $null
    Use-Check 'C0-QUALIFIED-CASE-A(run:246,G2)' 'qualification.json result=PASS release_case=A' {
        $f = Join-Path $R 'qualification.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $script:q = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
        "result=$($script:q.result) release_case=$($script:q.release_case) tip=$($script:q.tip)"; (Get-Verdict ($script:q.result -eq 'PASS' -and $script:q.release_case -eq 'A')) }
    $q = $script:q
    Use-Check 'C0-Q12-STOP-AUTHORIZED(run:247,360,G8)' 'q12.txt first token STOP_AUTHORIZED' {
        $f = Join-Path $R 'q12.txt'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-KitFirstToken $f; "first token '$t'"; (Get-Verdict ($t -eq 'STOP_AUTHORIZED')) }
    Use-Check 'C0-GAP-CHOICE(run:248,171-172,484-486)' 'gap-overrun.txt first token ACCEPT_OVERRUN or ROLLBACK_ON_OVERRUN' {
        $f = Join-Path $R 'gap-overrun.txt'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-KitFirstToken $f; "first token '$t'"; (Get-Verdict ($t -in 'ACCEPT_OVERRUN', 'ROLLBACK_ON_OVERRUN')) }
    Use-Check 'C0-U6-NOT-0035(run:249,166-169,G5)' 'WeatherReplayBundleExportNightly absent, State Disabled, or no T00:35 trigger' {
        $t = Get-TaskExact 'WeatherReplayBundleExportNightly'
        if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        $u = $t[0]; $at = @($u.Triggers | Where-Object { [string]$_.StartBoundary -match 'T00:35' }).Count
        "State=$($u.State) Enabled=$($u.Settings.Enabled) T00:35_triggers=$at"; (Get-Verdict (-not ([string]$u.State -ne 'Disabled' -and $at -gt 0))) }
    $Head = $null
    if (Test-Path -LiteralPath (Join-Path $P '.git')) { $Head = "$(git --no-optional-locks -C $P rev-parse HEAD)".Trim(); if ($LASTEXITCODE) { $Head = $null } }
    Use-Check 'C0-HEAD-VS-QUALIFIED-TIP(run:250-251)' "qualification.json tip = -QualifiedTip $QualifiedTip; HEAD vs tip (logged by the kit; judged by CHECK G3 below)" {
        if (-not $Head) { 'HEAD unreadable'; 'NOT-EVALUABLE'; return }; if (-not $q) { "HEAD=$Head tip=<no qualification.json>"; 'NOT-EVALUABLE'; return }
        $same = [string]$q.tip -eq $QualifiedTip
        "HEAD=$Head qualification.tip=$($q.tip) head_is_tip=$($Head -eq [string]$q.tip)"; (Get-Verdict $same) }
    $FamilyTasks = @(Get-ScheduledTask -TaskName 'WeatherMakerEvidence*' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ne 'WeatherMakerEvidenceCapture' } | ForEach-Object { $_.TaskName })
    $AuxFile = Join-Path $R 'aux-tasks.txt'
    $AuxNames = @(); if (Test-Path -LiteralPath $AuxFile) { $AuxNames = @(Get-Content -LiteralPath $AuxFile | Where-Object { $_.Trim() }) }
    Use-Check 'C0-FAMILY-Q12B(run:253-258)' 'no WeatherMakerEvidence<Family> task, or q12b.txt STOP_AUTHORIZED and every family task in aux-tasks.txt' {
        if (-not $FamilyTasks.Count) { "family tasks=none (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        $f = Join-Path $R 'q12b.txt'; $t = if (Test-Path -LiteralPath $f) { Get-KitFirstToken $f } else { '<absent>' }
        $trimmed = @(Get-Content -LiteralPath $AuxFile -ErrorAction SilentlyContinue | ForEach-Object { $_.Trim() }); $notAux = @($FamilyTasks | Where-Object { $trimmed -notcontains $_ })
        "family=[$($FamilyTasks -join ',')] q12b='$t' not_in_aux=[$($notAux -join ',')]"; (Get-Verdict ($t -eq 'STOP_AUTHORIZED' -and -not $notAux.Count)) }
    Use-Check 'C0-AUX-NAMES-RESOLVE(run:259-260,339)' 'aux-tasks.txt present; every name matches exactly one task' {
        if (-not (Test-Path -LiteralPath $AuxFile)) { 'aux-tasks.txt absent'; 'WOULD-FAIL'; return }
        $bad = @(); foreach ($n in $AuxNames) { $c = (Get-TaskExact $n).Count; if ($c -ne 1) { $bad += "$n=$c" } }
        "names=$($AuxNames.Count) unresolved_or_duplicate=[$($bad -join ',')]"
        if (-not $bad.Count) { 'PASS' } elseif (@($bad | Where-Object { $_ -notmatch '=0$' }).Count) { 'WOULD-FAIL' } else { $Missing } }
    Use-Check 'C0-CLOB-ENRICHMENT-STATE(run:261,c0:160)' 'WeatherClobEnrichmentLoop absent or State Disabled (not Settings.Enabled: a running instance fails)' {
        $t = Get-TaskExact 'WeatherClobEnrichmentLoop'
        if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled)"; (Get-Verdict ([string]$t[0].State -eq 'Disabled')) }
    Use-Check 'C0-PROD-TREE-CLEAN(run:262,451)' 'git status --porcelain --untracked-files=no empty' {
        if (-not (Test-Path -LiteralPath (Join-Path $P '.git'))) { 'no repo'; 'WOULD-FAIL'; return }
        $s = @(git --no-optional-locks -C $P status --porcelain --untracked-files=no); if ($LASTEXITCODE) { "git exit $LASTEXITCODE"; 'NOT-EVALUABLE'; return }
        "dirty_entries=$($s.Count) $($s | Select-Object -First 5)"; (Get-Verdict (-not $s.Count)) }
    Use-Check 'C0-DISK-10GB(run:265)' 'C: free >= 10 GB (Win32_LogicalDisk FreeSpace, same volume as Get-Volume)' {
        $d = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='C:'"; $gb = [math]::Round($d.FreeSpace / 1GB, 1); "free=${gb}GB"; (Get-Verdict ($d.FreeSpace -ge 10GB)) }
    foreach ($tn in 'WeatherTrainingWindow', 'WeatherEveningEvidenceRefresh') {
        Use-Check "C0-G5-$tn(run:266-267,G5)" 'absent or State Disabled (State: a disabled task still running holds the lease)' {
            $t = Get-TaskExact $tn
            if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
            "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled)"; (Get-Verdict ([string]$t[0].State -eq 'Disabled')) } }
    Use-Check 'C0-MEMGUARD-STATUS-READABLE(run:268)' 'data\logs\memory_commit_guard_status.json reads as JSON (Read-WeatherMemoryGuardStatus throws otherwise)' {
        $f = Join-Path $P 'data\logs\memory_commit_guard_status.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $j = Read-SharedJson $f; "parsed; last_write=$((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"; (Get-Verdict ($null -ne $j)) }
    Use-Check 'C0-STATUS-BASELINE(run:270-271,180-186)' 'status.ps1 -Json prints JSON with a flags field; capture 3/3; no unaccepted FLAG' {
        $f = Join-Path $R 'c0-status.out.txt'; $r0 = if (Test-Path -LiteralPath $f) { "last c0-status.out.txt written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))" } else { 'no earlier c0-status.out.txt' }
        "$r0; status.ps1 itself not run (outside the read-only allowlist; it is run by C0 at 00:30)"; 'NOT-EVALUABLE' }
    Use-Check 'C0-RELEASE-POINTER-ABSENT(run:175,G6)' 'artifacts\releases\current_release.json absent (case A)' {
        $ex = Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json'); "exists=$ex"; (Get-Verdict (-not $ex)) }
    Use-Check 'C0-RELEASE-CLI-CASE-A(run:272,154-164,173-174)' 'release_lifecycle_cli active -> BLOCK "active release pointer is missing"' { 'needs python (release_lifecycle_cli); outside the read-only allowlist'; 'NOT-EVALUABLE' }
    Use-Check 'C0-RESTORE-ARMED(c0:176)' 'WeatherTrainingWindowRestore not Disabled, with an enabled T04:15 trigger' {
        $t = Get-TaskExact 'WeatherTrainingWindowRestore'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        $tr = @($t[0].Triggers | Where-Object { [string]$_.StartBoundary -match 'T04:15' -and $_.Enabled }).Count
        "State=$($t[0].State) T04:15_enabled_triggers=$tr"; (Get-Verdict ([string]$t[0].State -ne 'Disabled' -and $tr -gt 0)) }

    # Next runs as C0 would list them at 00:30 on the night: non-Disabled, non-exempt, due before 04:00.
    $Exempt = @('WeatherMemoryCommitGuard', 'WeatherSnapshotLoopSupervisor', 'WeatherClobBookLoopSupervisor', 'WeatherObservationTriggerSupervisor', 'WeatherTrainingWindowRestore') + $AuxNames
    $DueFrom = $PlanC0; $DueTo = $Night.AddHours(4)
    $Due = @(); $DueErr = $null
    try { $Due = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { [string]$_.State -ne 'Disabled' -and $Exempt -notcontains $_.TaskName } | Where-Object { Test-TaskDueIn $_ $DueFrom $DueTo } | ForEach-Object { "$($_.TaskPath)$($_.TaskName)" }) }
    catch { $DueErr = $_.Exception.Message }
    $DueRoot = @($Due | Where-Object { $_ -match '^\\[^\\]+$' })
    Use-Check 'C0-NEXT-RUNS-ALL(run:273-276,C0 go/no-go)' "c0-next-runs.txt empty: no non-exempt task due $($DueFrom.ToString('MM-dd HH:mm'))-$($DueTo.ToString('HH:mm')) (predicted from triggers)" {
        if ($DueErr) { "error: $DueErr"; 'NOT-EVALUABLE'; return }
        "due=$($Due.Count) [$($Due -join ', ')] (elevated=$IsElevated)"; $(if (-not $IsElevated) { 'NOT-EVALUABLE' } elseif ($Due.Count) { 'WOULD-FAIL' } else { 'PASS' }) }
    Use-Check 'POSTC0-NEXT-RUNS-ROOT(run:284-287,G5)' 'no root-folder task due before 04:00 (the wrapper exits 4 on one the GO review did not see)' {
        if ($DueErr) { "error: $DueErr"; 'NOT-EVALUABLE'; return }
        "root_due=$($DueRoot.Count) [$($DueRoot -join ', ')]"; $(if (-not $IsElevated) { 'NOT-EVALUABLE' } elseif ($DueRoot.Count) { 'WOULD-FAIL' } else { 'PASS' }) }
    Use-Check 'POSTC0-GO-REVIEWED-BASELINE(run:243-245,280-283)' "c0-status-flags.txt present at launch; no flag new since the GO review" {
        $f = Join-Path $R 'c0-status-flags.txt'; $r0 = if (Test-Path -LiteralPath $f) { "present, written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))" } else { 'absent' }
        "$r0; C0 rewrites it at 00:30 on $NightDate and the wrapper compares it with the GO-reviewed copy"; 'NOT-EVALUABLE' }
    Use-Check 'POSTC0-HEAD-EQUALS-FLAG(run:279)' 'HEAD at launch = head= in the C0 flag' {
        $f = Join-Path $R "c0-done-$Tag.flag"
        if (-not (Test-Path -LiteralPath $f) -or (Get-Item -LiteralPath $f).LastWriteTime -lt $Night) { "HEAD now=$Head; flag for $NightDate not written yet"; 'NOT-EVALUABLE'; return }
        $fh = if ("$(Get-Content -LiteralPath $f -TotalCount 1)" -match 'head=([0-9a-f]{40})') { $Matches[1] } else { '<none>' }
        "HEAD=$Head flag=$fh"; (Get-Verdict ($Head -and $Head -eq $fh)) }

    # --- C1 lease and receipts (run:289-304); lease read-only probe
    Use-Check 'C1-POLICY-WINDOW(workload_admission.ps1:596-598)' 'agent_heavy window (00:30-09:00) at the planned 01:00 lease' {
        $m = $PlanC.Hour * 60 + $PlanC.Minute; $mn = $Now.Hour * 60 + $Now.Minute
        "planned=agent_heavy:$($m -ge 30 -and $m -lt 540) now=agent_heavy:$($mn -ge 30 -and $mn -lt 540)"; (Get-Verdict ($m -ge 30 -and $m -lt 540)) }
    Use-Check 'C1-LEASE-FREE(run:291-293,workload_admission.ps1:1804-1815,1975-1986)' 'Global\WeatherProjectHeavyWorkloadV1 not held and heavy_workload.lock not owned by a live process' {
        $mx = 'absent'
        try { $h = [Threading.Mutex]::OpenExisting('Global\WeatherProjectHeavyWorkloadV1', [Security.AccessControl.MutexRights]::Synchronize); $mx = 'exists'; $h.Dispose() }
        catch [Threading.WaitHandleCannotBeOpenedException] { $mx = 'absent' }
        catch [UnauthorizedAccessException] { $mx = 'exists(access-denied)' }
        $lock = Join-Path $P 'data\logs\heavy_workload.lock'; $own = 'no-lock-file'; $alive = $false
        if (Test-Path -LiteralPath $lock) {
            $o = $null; try { $o = Read-SharedJson $lock } catch { }
            if ($o -and $o.pid) {
                $pr = Get-Process -Id ([int]$o.pid) -ErrorAction SilentlyContinue
                if ($pr) { $tok = $null; try { $tok = 'win32-filetime:' + $pr.StartTime.ToUniversalTime().ToFileTimeUtc() } catch { }
                    # an unreadable start time (another user's process, non-elevated) counts as alive: fail towards 'held'
                    $alive = (-not $tok) -or (-not $o.owner_process_creation_time_token) -or ($tok -eq [string]$o.owner_process_creation_time_token) }
                $own = "pid=$($o.pid) workload=$($o.workload) acquired_at=$($o.acquired_at) owner_alive=$alive" }
            else { $own = 'lock file present, no owner record' } }
        "mutex=$mx lock=[$own]"
        if ($mx -eq 'absent' -and -not $alive) { 'PASS' } else { 'NOT-EVALUABLE' } }   # held now: whether it is free at 01:00 depends on that holder
    Use-Check 'C1-WORKLOAD-MARKER(workload_admission.ps1:1782-1799)' 'informational for capture_colocated_v1 (Enter- reads the ProgramData marker only for portable/workstation profiles)' {
        $f = Join-Path $env:ProgramData 'WeatherProject\heavy_workload_v1.poison'
        if (-not (Test-Path -LiteralPath $f)) { 'marker absent'; 'PASS'; return }
        $mk = $null; try { $mk = Read-SharedJson $f } catch { }
        "marker present state=$($mk.state) workload=$($mk.workload) profile=$($mk.execution_host_profile)"; 'PASS' }
    Use-Check 'C1-LEASE-DEADLINE-0104(run:291-295)' 'lease by 01:04 (launch at 01:00, free lease: first attempt succeeds)' {
        "planned_launch=$($PlanC.ToString('HH:mm')) deadline=01:04 now=$NowText"; (Get-Verdict ($PlanC -le $PlanC.Date.AddHours(1).AddMinutes(4))) }
    Use-Check 'C1-CAPTURE-STATUS-FILES(run:299)' 'data\snapshots loop_status.json, clob_loop_status.json, observation_trigger_status.json exist (Copy-Item would throw)' {
        $s = @('loop_status.json', 'clob_loop_status.json', 'observation_trigger_status.json' | ForEach-Object { "$_=$(Test-Path -LiteralPath (Join-Path $P "data\snapshots\$_"))" }); ($s -join ' '); (Get-Verdict (-not ($s -match '=False'))) }
    $ShadowStop = $null; $ShadowTask = Get-TaskExact 'WeatherMakerShadowRunner'
    Use-Check 'C1-SHADOW-STOP-FILE(run:300-304)' 'shadow task absent, or Actions[0].Arguments has --stop-file "<path>"' {
        if (-not $ShadowTask.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        if ([string]$ShadowTask[0].Actions[0].Arguments -match '--stop-file\s+"([^"]+)"') { $script:ShadowStop = $Matches[1]; "stop_file=$($Matches[1]) present_now=$(Test-Path -LiteralPath $Matches[1])"; 'PASS' }
        else { 'stop-file argument unreadable'; 'WOULD-FAIL' } }
    $ShadowStop = $script:ShadowStop

    # --- C2 quiesce (run:306-368)
    Use-Check 'C2-PRESTATE-CSV-ABSENT(run:341)' "$NightN\aux-prestate.csv absent (else C2 reuses an old pre-state)" {
        $f = Join-Path $NightN 'aux-prestate.csv'; $ex = Test-Path -LiteralPath $f; "exists=$ex"; (Get-Verdict (-not $ex)) }
    foreach ($an in $AuxNames) {
        $at = Get-TaskExact $an
        Use-Check "C2-ENABLED-$an(run:342,351-352)" 'exactly one task; live Settings.Enabled readable as True/False (C2 verifies the disable with Settings.Enabled -eq $false)' {
            if ($at.Count -ne 1) { "matches=$($at.Count) (elevated=$IsElevated)"; $(if ($at.Count -eq 0) { $Missing } else { 'WOULD-FAIL' }); return }
            $en = $at[0].Settings.Enabled; "State=$($at[0].State) Settings.Enabled=$en"; (Get-Verdict ($en -is [bool])) }
        Use-Check "C2-PRESTATE-$an(run:312-313,315-316)" 'pre-state row Enabled column is exactly True or False (Test-PrestateEnabled takes the exact path)' {
            if ($at.Count -ne 1) { "matches=$($at.Count)"; $(if ($at.Count -eq 0) { $Missing } else { 'WOULD-FAIL' }); return }
            $row = [pscustomobject]@{ Task = $an; State = [string]$at[0].State; Enabled = [string]$at[0].Settings.Enabled }
            $exact = $row.Enabled -in 'True', 'False'
            $wouldRestore = if ($row.Enabled) { $row.Enabled -eq 'True' } else { $row.State -ne 'Disabled' }
            $note = if (-not $wouldRestore -and $row.State -eq 'Running') { ' (disabled but running: C9b leaves it disabled, ESCALATE)' } else { '' }
            "row State=$($row.State) Enabled='$($row.Enabled)' -> undo re-enables=$wouldRestore$note"; (Get-Verdict $exact) } }
    Use-Check 'C2-SHADOW-SEALABLE(run:344-349)' 'shadow not in aux-tasks.txt, or its stop-file path is known' {
        if ($AuxNames -notcontains 'WeatherMakerShadowRunner') { 'shadow not in aux list'; 'PASS'; return }
        $st = if ($ShadowTask.Count) { [string]$ShadowTask[0].State } else { '<not visible>' }
        "stop_file=$ShadowStop State=$st"; $(if ($ShadowStop) { 'PASS' } elseif (-not $ShadowTask.Count -and -not $IsElevated) { 'NOT-EVALUABLE' } else { 'WOULD-FAIL' }) }
    Use-Check 'C2-TAPE-ENSURE-BOUND(run:355-357)' 'WeatherExecutionTapeSupervisor ExecutionTimeLimit <= 150 s (the C2 wait bound; 01:12 arithmetic)' {
        if ($AuxNames -notcontains 'WeatherExecutionTapeSupervisor') { 'tape supervisor not in aux list'; 'PASS'; return }
        $t = Get-TaskExact 'WeatherExecutionTapeSupervisor'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        $lim = [string]$t[0].Settings.ExecutionTimeLimit; $s = Get-SpanSeconds $lim
        "ExecutionTimeLimit=$lim MultipleInstances=$($t[0].Settings.MultipleInstances) State=$($t[0].State)"; (Get-Verdict ($s -and $s -gt 0 -and $s -le 150)) }
    Use-Check 'C2-88A-TASK-REGISTERED(run:359-361)' 'WeatherMakerEvidenceCapture resolves (a non-SilentlyContinue Get-ScheduledTask under Stop)' {
        $t = Get-TaskExact 'WeatherMakerEvidenceCapture'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled)"; 'PASS' }
    Use-Check 'C2-TAPE-STOP-VERB(run:323-335,358)' 'execution_tape_supervisor stop exits 0, or process_gone, or status_pid_unknown + unhealthy' { 'needs python (execution_tape_supervisor stop); outside the read-only allowlist'; 'NOT-EVALUABLE' }

    # --- C3 / C4 (run:370-438)
    foreach ($sn in $Sup) {
        Use-Check "C3-SUPERVISOR-$sn(run:375-381,455)" 'exactly one task; Settings.Enabled True now; ExecutionTimeLimit <= 330 s (the C3 ensure wait)' {
            $t = Get-TaskExact $sn; if ($t.Count -ne 1) { "matches=$($t.Count) (elevated=$IsElevated)"; $(if ($t.Count -eq 0) { $Missing } else { 'WOULD-FAIL' }); return }
            $lim = [string]$t[0].Settings.ExecutionTimeLimit; $s = Get-SpanSeconds $lim
            "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled) ExecutionTimeLimit=$lim"; (Get-Verdict ($t[0].Settings.Enabled -eq $true -and $s -and $s -gt 0 -and $s -le 330)) } }
    Use-Check 'C3-PRE-DEADLINE-0112(run:424-426)' 'C1 01:00 + worst-case C1+C2 8.0 min (runbook) <= 01:12' {
        $t = $PlanC.AddMinutes(8); "planned C3 start by $($t.ToString('HH:mm:ss'))"; (Get-Verdict ($t -le $PlanC.Date.AddHours(1).AddMinutes(12))) }
    Use-Check 'C3-STOP-VERBS-AND-GATE(run:383-392)' 'three stop verbs exit 0; capture_resource_gate no_live_capture exits 0 within 600 s' { 'needs python and a real stop; outside the read-only allowlist'; 'NOT-EVALUABLE' }
    Use-Check 'C4-RENAME-DEADLINE-0130(run:432)' '01:12 + C3 pass-case worst case 17.5 min (runbook) <= 01:30' {
        $t = $PlanC.Date.AddHours(1).AddMinutes(12).AddSeconds(17.5 * 60); "worst-case rename at $($t.ToString('HH:mm:ss'))"; (Get-Verdict ($t -le $PlanC.Date.AddHours(1).AddMinutes(30))) }
    Use-Check 'C4-HOLDERS-KNOWN(run:410-423)' 'every current holder of venv is a worker C2/C3 stops (capture, tape, shadow, 88a, family)' {
        $dir = Join-Path $P 'venv'; $ohn = if ($OldHome) { $OldHome.TrimEnd('\') } else { '<none>' }; $nhn = $NewHome.TrimEnd('\')
        $hold = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
                $_.ExecutablePath -like "$dir\*" -or $_.CommandLine -like "*$dir\*" -or
                (($_.ExecutablePath -like "$ohn\*" -or $_.ExecutablePath -like "$nhn\*") -and $_.CommandLine -like "*$P\*") })
        $known = 'snapshot_tracker|market_microstructure|observation_trigger|execution_tape_supervisor|maker_shadow|maker_evidence'
        $unknown = @($hold | Where-Object { "$($_.CommandLine)" -notmatch $known } | ForEach-Object { "pid $($_.ProcessId): $("$($_.CommandLine)".Substring(0, [math]::Min(120, "$($_.CommandLine)".Length)))" })
        $nocl = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { -not $_.CommandLine }).Count
        "holders=$($hold.Count) unknown=[$($unknown -join ' ; ')] python_without_visible_cmdline=$nocl"
        if ($unknown.Count) { 'WOULD-FAIL' } elseif ($nocl -and -not $IsElevated) { 'NOT-EVALUABLE' } else { 'PASS' } }

    # --- C7 restore, C8, C9c reads (run:394-402, 455-466, 497-510)
    Use-Check 'C7-RESTORE-TASK(run:394-402,455-456)' 'WeatherTrainingWindowRestore resolves; ExecutionTimeLimit <= 15 min (Wait-Restore budget 32 min = run + rerun)' {
        $t = Get-TaskExact 'WeatherTrainingWindowRestore'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        $lim = [string]$t[0].Settings.ExecutionTimeLimit; $s = Get-SpanSeconds $lim
        "State=$($t[0].State) ExecutionTimeLimit=$lim"; (Get-Verdict ($s -and $s -gt 0 -and $s -le 900)) }
    Use-Check 'C7-TRAINING-WINDOW-STATUS(run:397-399)' 'data\logs\training_window_status.json parses with updated_at, phase, outcome (Wait-Restore reads it under Stop)' {
        $f = Join-Path $P 'data\logs\training_window_status.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $j = Read-SharedJson $f; $ok = $j.updated_at -and $j.PSObject.Properties['phase'] -and $j.PSObject.Properties['outcome']
        "updated_at=$($j.updated_at) phase=$($j.phase) outcome=$($j.outcome)"; (Get-Verdict ([bool]$ok)) }
    foreach ($sf in 'loop_status.json', 'clob_loop_status.json', 'observation_trigger_status.json') {
        Use-Check "C8-PYVER-FIELD-$sf(run:462-464,110-111)" 'runtime_identity.python_version present (3.11.0 before the swap; C8 requires 3.11.9 after)' {
            $f = Join-Path $P "data\snapshots\$sf"; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
            $v = (Read-SharedJson $f).runtime_identity.python_version; "python_version=$v"; (Get-Verdict ([string]$v -eq '3.11.0')) } }
    Use-Check 'C9C-88A-STATUS(run:503-504,531-536)' 'data\maker_evidence\status.json parses (a hard read in C9c)' {
        $f = Join-Path $P 'data\maker_evidence\status.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $m = Read-SharedJson $f; "state=$($m.state) updated=$($m.updated_at_utc) last_error=$($m.last_error)"; 'PASS' }
    Use-Check 'C9C-FAMILY-STATUS(run:505-508)' 'for each family task, data\maker_evidence_families\<fid>\status.json parses' {
        if (-not $FamilyTasks.Count) { "family tasks=none (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        $bad = @(); foreach ($ft in $FamilyTasks) { $fid = (($ft -replace '^WeatherMakerEvidence', '') -creplace '([a-z0-9])([A-Z])', '$1_$2').ToLowerInvariant()
            $f = Join-Path $P "data\maker_evidence_families\$fid\status.json"; try { $null = Read-SharedJson $f } catch { $bad += $fid } }
        "family=[$($FamilyTasks -join ',')] unreadable=[$($bad -join ',')]"; (Get-Verdict (-not $bad.Count)) }
    Use-Check 'C9C-TAPE-HEALTH(run:497-502,515-519)' 'execution_tape_supervisor status RUNNING, identity current, integrity PASS, CONNECTED' { 'needs python (execution_tape_supervisor status); outside the read-only allowlist'; 'NOT-EVALUABLE' }

    # --- section R interpreter resolution (run:71-86)
    foreach ($kv in @(@('snapshot', 'loop_status.json'), @('clob', 'clob_loop_status.json'), @('obs', 'observation_trigger_status.json'), @('tape', 'execution_tape_status.json'))) {
        $key = $kv[0]; $file = $kv[1]
        Use-Check "R-STOP-INTERPRETER-$key(run:74-84)" 'managed_process.expected_command[0] recorded and its same-directory python.exe exists (else the probe fallback runs)' {
            $f = Join-Path $P "data\snapshots\$file"; if (-not (Test-Path -LiteralPath $f)) { 'status file absent (fallback probe would run)'; 'WOULD-FAIL'; return }
            $cmd = @((Read-SharedJson $f).managed_process.expected_command)
            if (-not $cmd.Count -or -not $cmd[0]) { 'no expected_command recorded (fallback probe would run)'; 'WOULD-FAIL'; return }
            $rec = ([string]$cmd[0]).Trim().Trim('"'); $cand = Join-Path (Split-Path -Parent $rec) 'python.exe'
            "recorded=$rec sibling_exists=$(Test-Path -LiteralPath $cand) (import probe not run)"; (Get-Verdict (Test-Path -LiteralPath $cand)) } }

    # --- runbook section 2 gates not already covered above
    Use-Check 'G0-OWNER-SIGNED-NIGHT-NAMED' 'owner signed section 11 and named the night' { 'owner record (DECISION_LOG / chat), not a host state'; 'NOT-EVALUABLE' }
    Use-Check 'G1-BOUNDED-SUITE-PARAMS' 'bounded_worktree_test_suite.ps1 has -InterpreterPath and -ExpectedInterpreterVersion' {
        $f = Join-Path $P 'scripts\ops\bounded_worktree_test_suite.ps1'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-Content -LiteralPath $f -Raw; $a = $t -match '\$InterpreterPath\b'; $b = $t -match '\$ExpectedInterpreterVersion\b'; "InterpreterPath=$a ExpectedInterpreterVersion=$b"; (Get-Verdict ($a -and $b)) }
    Use-Check 'G4-OWNER-REACHABLE' 'owner reachable 00:30-03:45 (or the recorded escalation rule)' { 'owner availability'; 'NOT-EVALUABLE' }
    Use-Check 'G5-NO-OTHER-LEASE-USER' 'no integration attempt, quiet-window merge, storage one-shot, replay or research batch due or running' {
        "root tasks due 00:30-04:00: [$($DueRoot -join ', ')]; lease: see C1-LEASE-FREE; ad-hoc agent work is not visible to the Scheduler"
        $(if (-not $IsElevated) { 'NOT-EVALUABLE' } elseif ($DueRoot.Count) { 'WOULD-FAIL' } else { 'PASS' }) }
    Use-Check 'G7-NOT-LFC-NIGHT' 'not the night before or of a scheduled LFC session' { 'calendar / state of play'; 'NOT-EVALUABLE' }
    Use-Check 'G8-AFTER-88A-FREEZE' 'night after the 88a merge freeze in the state of play (q12 checked in C0-Q12)' { 'state of play'; 'NOT-EVALUABLE' }
    Use-Check 'G9-TZDATA-DECIDED' 'Q13 tzdata sequencing decided' { 'owner record'; 'NOT-EVALUABLE' }
    Use-Check 'G10-NO-LIVE-ATTEMPT' 'no live attempt planned before the reseal' { 'owner plan'; 'NOT-EVALUABLE' }
    Use-Check 'G11-NOT-DST-NIGHT' 'night is not 10-31/11-01; no ambiguous or invalid local time 00:00-04:30' {
        $tz = [TimeZoneInfo]::Local; $amb = @(0..54 | ForEach-Object { $Night.AddMinutes(5 * $_) } | Where-Object { $tz.IsAmbiguousTime($_) -or $tz.IsInvalidTime($_) }).Count
        $md = $Night.ToString('MM-dd'); "night=$NightDate ambiguous_or_invalid_slots=$amb"; (Get-Verdict ($md -notin '10-31', '11-01' -and $amb -eq 0)) }
    # --- G3, master's rule for this night (printed after every C0 predicate so (iii) can AND them)
    try {
        $g3Exp = "HEAD = $QualifiedTip, or (i) deps_changed=0 and (ii) nondocs_diff=0 vs $PregateTestedSha ($PregateReceiptId) and (iii) c0_other clean"
        if (-not $Head) { throw 'HEAD unreadable' }
        $tipFull = "$(git --no-optional-locks -C $P rev-parse --verify "$QualifiedTip^{commit}")".Trim(); if ($LASTEXITCODE -or $tipFull -notmatch '^[0-9a-f]{40}$') { throw "qualified tip $QualifiedTip does not resolve" }
        $testedFull = "$(git --no-optional-locks -C $P rev-parse --verify "$PregateTestedSha^{commit}")".Trim(); if ($LASTEXITCODE -or $testedFull -notmatch '^[0-9a-f]{40}$') { throw "tested sha $PregateTestedSha does not resolve" }
        $depFiles = @(git --no-optional-locks -C $P diff --no-ext-diff --name-only $tipFull $Head); if ($LASTEXITCODE) { throw "git diff tip..HEAD exit $LASTEXITCODE" }
        $deps = @($depFiles | Where-Object { $_ -match '(^|/)(requirements[^/]*|pyproject\.toml|[^/]*\.lock|constraints[^/]*|setup\.cfg|setup\.py)$' })
        $testedDiff = @(git --no-optional-locks -C $P diff --no-ext-diff --name-only $testedFull $Head); if ($LASTEXITCODE) { throw "git diff tested..HEAD exit $LASTEXITCODE" }
        $nonDocs = @($testedDiff | Where-Object { $_ -notmatch '^docs/.+\.md$' })
        $c0Ids = @($script:Verdicts.Keys | Where-Object { $_ -like 'C0-*' -and $_ -notlike 'C0-HEAD-VS-QUALIFIED-TIP*' })
        $c0Fail = @($c0Ids | Where-Object { $script:Verdicts[$_] -eq 'WOULD-FAIL' }); $c0Ne = @($c0Ids | Where-Object { $script:Verdicts[$_] -eq 'NOT-EVALUABLE' })
        $rcpt = 'not read (workstation evidence)'; $rcptBad = $false
        if ($PregateReceiptPath) {
            if (Test-Path -LiteralPath $PregateReceiptPath) { $rj = Read-SharedJson $PregateReceiptPath; $rh = [string]$rj.head; if (-not $rh) { $rh = [string]$rj.tested_sha }
                $rcpt = "verdict=$($rj.verdict) head=$rh"; $rcptBad = ([string]$rj.verdict -ne 'PASS') -or ($rh -and $rh -ne $testedFull) }
            else { $rcpt = 'receipt path absent'; $rcptBad = $true } }
        if ($Head -eq $tipFull) { $branch = 'head-equals-tip'; $ok = $true }
        else { $branch = 'tested-tree'; $ok = (-not $deps.Count) -and (-not $nonDocs.Count) -and (-not $c0Fail.Count) -and (-not $rcptBad) }
        if (-not $ok) { $branch = "$branch(fails)" }
        $read = "branch=$branch head=$Head tip=$tipFull deps_changed=$($deps.Count) [$($deps -join ',')] nondocs_diff=$($nonDocs.Count) [$(@($nonDocs | Select-Object -First 8) -join ',')$(if ($nonDocs.Count -gt 8) { ',...' })] c0_other_would_fail=[$($c0Fail -join ',')] c0_other_unevaluated_here=[$($c0Ne -join ',')] receipt=$PregateReceiptId $rcpt"
        Push-Check 'G3' $read $g3Exp (Get-Verdict $ok)
    }
    catch { Push-Check 'G3' ("error: " + $_.Exception.Message) 'read-only git evaluation' 'NOT-EVALUABLE' }
    Use-Check 'G12-DOWNLOADS-APPROVED' 'owner approved the wheel and NuGet downloads' { 'owner record (the wheelhouse is checked in C5-LOCK-WHEELHOUSE)'; 'NOT-EVALUABLE' }
}
catch { Write-Output ("CHECK REHEARSAL-ABORTED | read=error: {0} | expected=completed rehearsal | NOT-EVALUABLE" -f ($_.Exception.Message -replace '\|', '/')); $script:Count['NOT-EVALUABLE']++ }
finally {
    if ($exitCode -eq 0) {
        $verdict = if ($script:Count['WOULD-FAIL']) { 'WOULD-FAIL' } elseif ($script:Count['NOT-EVALUABLE']) { 'PASS-WITH-UNEVALUATED' } else { 'PASS' }
        $summary = 'SUMMARY | pass={0} | would-fail={1} | not-evaluable={2} | verdict={3} | non-pass=[{4}]' -f $script:Count['PASS'], $script:Count['WOULD-FAIL'], $script:Count['NOT-EVALUABLE'], $verdict, ($script:FailIds -join ', ')
        $script:Lines.Add($summary)
        [Console]::Out.WriteLine($summary)
        if ($OutFile) { try { [IO.File]::WriteAllLines($OutFile, $script:Lines.ToArray()) } catch { [Console]::Out.WriteLine("OUTFILE not written: $($_.Exception.Message)") } }
    }
    exit $exitCode
}
