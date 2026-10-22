# CHECK-THE-CHECKS rehearsal for the Python-upgrade C night (night of 2026-10-23 to 2026-10-24).
# READ-ONLY. It evaluates, against the live host, every predicate the C kit gates on and changes nothing. Kit:
# claude/night-plans-pyup-c-next-20261022 @ 0b90d641c (phase-c0-run-20261024.ps1, phase-c-run-20261024.ps1,
# phase-c-retry-wrapper-20261024.ps1, README.md CLOCKS) and the runbook (HOST_PYTHON_UPGRADE_RUNBOOK.md at 15440ed4e).
#
# Launch (elevated, like the kit: a non-elevated Get-ScheduledTask hides S4U tasks):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File <this file> [-OutFile C:\pyup\check-the-checks-20261024.txt]
# -OutFile is refused (exit 2, nothing read) when it lies under -KitRoot or C:\pyup\cp3119, or its file name is one the kit reads.
# Parameters default to the kit's host values and to master's G3 values for this night (the kit itself takes them only
# from the operator). -KitTag (default 20261024) is the date tag in the kit's file names.
#
# Output: one line per predicate
#   CHECK <id> | read=<value> | expected=<value> | PASS|WOULD-FAIL|NOT-EVALUABLE   (G3 lines may also say DEFER)
# then one SUMMARY line. The id carries the kit lines it mirrors (run:N = phase-c-run-20261024.ps1, c0:N =
# phase-c0-run-20261024.ps1, retry:N = phase-c-retry-wrapper-20261024.ps1). Clock predicates are judged at the planned
# times on -NightDate (standalone C0 -PlannedC0 00:30, retry-wrapper launch -PlannedLaunch 00:32, README timeline); the
# read field also carries the current clock. Exit 0 for a completed rehearsal (the verdict is in the output); exit 2
# only when the self-check below refuses to run.
#
# G3 mirrors the kit's Test-G3Gate (run :343-372, c0 :168-197) and its call sites (run :385-388, :438; c0 :203-206, :234),
# read-only (git diff --name-only, and rev-parse --verify in place of the kit's cat-file -t), with the kit's exact text:
#   "G3 PASS mode=<m> branch=<b> <detail>", "G3 DEFER mode=strict branch=HEAD!=tip requires=ROLL-FREE-at-GO-review",
#   "G3 FAIL reason=<r> mode=<m> head=<h> tip=<operator tip>".
# strict: the qualification.json tip; HEAD == tip is PASS, otherwise DEFER (not a refusal: the ROLL-FREE roll verdict is
#   reviewed at GO). dependency: the operator tip, which must equal the qualification.json tip; PASS on HEAD == tip, or on
#   (i) no dependency file differs tip..HEAD and (ii) the non-docs diff tested..HEAD holds nothing but
#   config/locations.json and config/location_market_events.json (exact paths; fleet_drift_exempt=<paths or none>), with
#   the pre-gate receipt id, tested sha and Python 3.11.9 attestation well formed and the receipt file
#   $R\pregate-receipt-<id without pg->.json matching its one $R\SHA256SUMS.txt line (size + sha256) and reading schema
#   weather.workstation_pregate_receipt.v1, verdict PASS, head = the tested sha, and a log_path with the id as a path
#   segment (PASS text adds py=attested); otherwise FAIL. (iii): the kit prints the PASS/DEFER line only after every other
#   C0 check passed and, inside an attempt, after the post-C0 GO-review checks (HEAD vs flag, flags vs the GO review,
#   root next-runs), so a C0-* or POSTC0-* WOULD-FAIL makes the G3 line WOULD-FAIL here.
# Verdicts for a G3 line: PASS, DEFER (strict, HEAD != tip; master needs the ROLL-FREE verdict at the GO review),
# WOULD-FAIL, NOT-EVALUABLE. Without -G3Mode both modes print, as CHECK G3-strict and CHECK G3-dependency.
# -HeadOverride <sha> replaces HEAD for the G3 evaluation only (every other predicate keeps the live HEAD); each G3 line
# then starts with HEAD-OVERRIDE IN USE.
#
# Read-only contract (enforced by the self-check before anything touches the host):
# - commands: Get-ScheduledTask, Get-ScheduledTaskInfo, Get-Process, Get-CimInstance, Test-Path, Get-Content,
#   Get-Item, git (rev-parse / status / show / diff only; status with --no-optional-locks so it never rewrites the
#   index; diff with --no-ext-diff --name-only), plus the pure pipeline helpers Get-Date, Join-Path, Split-Path,
#   Where-Object, ForEach-Object, Sort-Object, Select-Object, Measure-Object, ConvertFrom-Json, Write-Output; no
#   dot-sourcing, no dynamic invocation except "& $Body" on this file's own literal script blocks (every $Body binding
#   must be a literal script block or a [scriptblock] parameter; no foreach or -*Variable binding of it; no "&"/"." of a
#   string); no file redirection; no property assignment; one final "exit $exitCode" and no other exit;
# - .NET: files open only with FileMode Open and FileAccess Read (share ReadWrite|Delete, so a writer's atomic
#   replace is never blocked); the lease mutex is opened only with OpenExisting(name, MutexRights Synchronize)
#   and never waited on (TryOpenExisting is denied); InvokeScript, NewScriptBlock, SetAttributes, SetEnvironmentVariable
#   and CreateInstance are denied; the only write is one WriteAllLines to -OutFile when the operator passes it.
# - No repo script is dot-sourced: the lease, memory-guard and G3 predicates are re-implemented here.
[CmdletBinding()]
param(
    [string]$RepoRoot = 'C:\Users\micha\Desktop\github\weather',
    [string]$KitRoot = 'C:\pyup\cp3119',
    [string]$NewHome = 'C:\Program Files\Python311-cp3119',
    [string]$NightDate = '2026-10-24',
    [string]$KitTag = '20261024',
    [string]$PlannedC0 = '00:30',
    [string]$PlannedLaunch = '00:32',
    [string]$G3QualifiedTip = '90b2e1844ad0de71916c67996026dea7b04ce5ff',
    [string]$G3PregateReceipt = 'pg-739c03eff1e2-20261018T045220-105120',
    [string]$G3TestedSha = '739c03eff1e2f26c49759899e4e39b669d2c6628',
    [string]$G3PregatePython = '3.11.9',
    [ValidateSet('', 'strict', 'dependency')][string]$G3Mode = '',
    [string]$HeadOverride = '',
    [string]$ExpectedRunSha256 = '79f72c2546ebc40c710a87541931044c7aa4d570da2ccedebcb28d1b202ea914',
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
    'InvokeReturnAsIs', 'SetValue', 'DeleteValue', 'SetShouldExit',
    'InvokeScript', 'NewScriptBlock', 'SetAttributes', 'SetEnvironmentVariable', 'CreateInstance', 'TryOpenExisting')
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
    # (Fable 10-23) exit: only the one final "exit $exitCode"; a property assignment can write host state ((Get-Item x).Attributes = ...)
    $exits = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.ExitStatementAst] }, $true))
    foreach ($e in $exits) { if ($exits.Count -ne 1 -or -not $e.Pipeline -or $e.Pipeline.Extent.Text -cne '$exitCode') { $problems.Add("exit at line $($e.Extent.StartLineNumber) is not the single final 'exit `$exitCode'") } }
    foreach ($a in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] }, $true)) {
        $line = $a.Extent.StartLineNumber; $lhs = $a.Left
        while ($lhs -is [Management.Automation.Language.ConvertExpressionAst] -or $lhs -is [Management.Automation.Language.AttributedExpressionAst]) { $lhs = $lhs.Child }
        if ($lhs -is [Management.Automation.Language.MemberExpressionAst]) { $problems.Add("property assignment at line $line"); continue }
        # $Body is the one variable "&" may invoke: every binding of it must be a literal script block
        if ($lhs -is [Management.Automation.Language.VariableExpressionAst] -and ($lhs.VariablePath.UserPath -replace '^[A-Za-z]+:', '') -eq 'Body') {
            $rhs = $a.Right
            if ($a.Operator -ne [Management.Automation.Language.TokenKind]::Equals -or $rhs -isnot [Management.Automation.Language.CommandExpressionAst] -or
                $rhs.Expression -isnot [Management.Automation.Language.ScriptBlockExpressionAst]) { $problems.Add("`$Body at line $line is assigned something other than a literal script block") } }
    }
    foreach ($pa in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.ParameterAst] -and ($n.Name.VariablePath.UserPath -replace '^[A-Za-z]+:', '') -eq 'Body' }, $true)) {
        if ($pa.StaticType -ne [scriptblock]) { $problems.Add("parameter `$Body at line $($pa.Extent.StartLineNumber) is not [scriptblock]") } }
    foreach ($fe in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.ForEachStatementAst] -and ($n.Variable.VariablePath.UserPath -replace '^[A-Za-z]+:', '') -eq 'Body' }, $true)) {
        $problems.Add("foreach binds `$Body at line $($fe.Extent.StartLineNumber)") }
    foreach ($cp in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandParameterAst] -and $n.ParameterName -match '^(OutVariable|ov|PipelineVariable|pv|ErrorVariable|ev|WarningVariable|wv|InformationVariable|iv)$' }, $true)) {
        $problems.Add("-$($cp.ParameterName) at line $($cp.Extent.StartLineNumber) can bind a variable that '&' invokes") }
    foreach ($uc in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -eq 'Use-Check' }, $true)) {
        if ($uc.CommandElements[-1] -isnot [Management.Automation.Language.ScriptBlockExpressionAst]) { $problems.Add("Use-Check at line $($uc.Extent.StartLineNumber) does not end in a literal script block") } }
    foreach ($ic in $ast.FindAll({ param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.InvocationOperator -ne [Management.Automation.Language.TokenKind]::Unknown }, $true)) {
        $first = $ic.CommandElements[0]
        if ($first -is [Management.Automation.Language.StringConstantExpressionAst] -or $first -is [Management.Automation.Language.ExpandableStringExpressionAst]) { $problems.Add("$($ic.InvocationOperator) invocation of a string at line $($ic.Extent.StartLineNumber)") } }
    return , $problems
}

# ---------------------------------------------------------------------------------------------------------
# Result accumulation
# ---------------------------------------------------------------------------------------------------------
$script:Lines = [Collections.Generic.List[string]]::new()
$script:Count = @{ 'PASS' = 0; 'DEFER' = 0; 'WOULD-FAIL' = 0; 'NOT-EVALUABLE' = 0 }
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
    if ($Verdict -cnotin @('PASS', 'DEFER', 'WOULD-FAIL', 'NOT-EVALUABLE')) { $Verdict = 'NOT-EVALUABLE' }
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
# Unary comma: a function's output unrolls, and in PS 5.1 a lone CimInstance has no .Count (host 10-22).
function Get-TaskExact([string]$Name) { return ,@(Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) }
function Get-SpanSeconds([string]$Iso) { if (-not $Iso) { return $null }; [Xml.XmlConvert]::ToTimeSpan($Iso).TotalSeconds }
function Get-KitFirstToken([string]$Path) { ((Get-Content -LiteralPath $Path -TotalCount 1) -split '\s+')[0] }   # the kit's q12 / q12b / gap form (no Trim)

# The kit's receipt predicate (run :356-362, c0 :181-187), in the same order and with the same reason tokens. $null = pass.
function Test-G3ReceiptRO([string]$Receipt, [string]$Tested) {
    if ("$Receipt" -cnotmatch '^pg-[0-9a-f]{12}-[0-9]{8}T[0-9]{6}-[0-9]+$') { return 'pregate_receipt_not_supplied_or_malformed' }
    $wRf = Join-Path $R ('pregate-receipt-' + $Receipt.Substring(3) + '.json')
    if (-not (Test-Path -LiteralPath $wRf)) { return 'pregate_receipt_file_missing' }
    # run :357 / c0 :182: exactly one $R\SHA256SUMS.txt line for the receipt, 3 fields, numeric size and sha256 both matching
    $wSf = Join-Path $R 'SHA256SUMS.txt'
    $wSl = @(if (Test-Path -LiteralPath $wSf) { Get-Content -LiteralPath $wSf | Where-Object { ("$_".Trim() -split '\s+')[0] -ceq (Split-Path -Leaf $wRf) } })
    if ($wSl.Count -ne 1) { return 'pregate_receipt_not_in_sha256sums' }
    $wSq = @("$($wSl[0])".Trim() -split '\s+'); $wSz = [long]-1
    if ($wSq.Count -ne 3 -or -not [long]::TryParse($wSq[1], [Globalization.NumberStyles]::None, [Globalization.CultureInfo]::InvariantCulture, [ref]$wSz) -or
        $wSz -ne (Get-Item -LiteralPath $wRf).Length -or $wSq[2].ToUpperInvariant() -cne (Get-FileSha256 $wRf)) { return 'pregate_receipt_sha256sums_mismatch' }
    $wRj = $null; try { $wRj = Get-Content -LiteralPath $wRf -Raw | ConvertFrom-Json } catch { $wRj = $null }; if ($null -eq $wRj) { return 'pregate_receipt_unreadable' }
    if ([string]$wRj.schema -cne 'weather.workstation_pregate_receipt.v1') { return 'pregate_receipt_schema_mismatch' }
    if ([string]$wRj.verdict -cne 'PASS') { return 'pregate_receipt_verdict_not_pass' }
    if ([string]$wRj.head -cne $Tested) { return 'pregate_receipt_head_ne_tested_sha' }
    if (@("$($wRj.log_path)" -split '[\\/]') -cnotcontains $Receipt) { return 'pregate_receipt_log_path_ne_receipt_id' }   # run :362 / c0 :187
    return $null
}
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
    # -OutFile must never overwrite a kit input: refuse any path under the kit root (or C:\pyup\cp3119) and any kit file name
    if ($OutFile) {
        $ofFull = [IO.Path]::GetFullPath($OutFile); $ofLeaf = Split-Path -Leaf $ofFull
        $ofRoots = @(([IO.Path]::GetFullPath($KitRoot).TrimEnd('\') + '\'), 'C:\pyup\cp3119\')
        $ofUnder = @($ofRoots | Where-Object { $ofFull.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) -or $ofFull.TrimEnd('\') -ieq $_.TrimEnd('\') })
        $ofNames = @("phase-c0-run-$KitTag.ps1", "phase-c-run-$KitTag.ps1", "phase-c-retry-wrapper-$KitTag.ps1", 'SHA256SUMS.txt', 'README.md',
            'phase-c-raw-20261022.md', "c0-done-$KitTag.flag", "owner-go-$KitTag.txt", 'qualification.json', 'q12.txt', 'q12b.txt', 'gap-overrun.txt',
            'aux-tasks.txt', 'oldhome.txt', 'constants.json', 'lock-hashed.txt', 'lock-tools-hashed.txt', 'night.log', 'c0-status.out.txt',
            'c0-status.err.txt', 'c0-status-flags.txt', 'c0-next-runs.txt', 'freeze-3110.txt', 'rtv-3110.json', 'check-the-checks-20261023.ps1',
            'scheduler-semantics-probe-20261022.ps1')
        $ofLike = @('pregate-receipt-*.json', 'decision-*', 'hold-*', 'phase-c*-transcript-*', 'goreview-baseline-flags*', 'aux-restart-at*', 'aux-prestate*')
        $ofHit = @($ofNames | Where-Object { $_ -ieq $ofLeaf }) + @($ofLike | Where-Object { $ofLeaf -like $_ })
        if ($ofUnder.Count -or $ofHit.Count) {
            Write-Output "REFUSED: -OutFile $ofFull $(if ($ofUnder.Count) { "lies under $($ofUnder -join ', ')" } else { "is named like a kit input ($($ofHit -join ', '))" }); choose a path outside the kit root"
            $exitCode = 2; return } }

    $P = $RepoRoot.TrimEnd('\'); $R = $KitRoot.TrimEnd('\')
    $Now = Get-Date
    $Night = [datetime]::ParseExact($NightDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
    $Tag = $KitTag
    $PlanC0 = $Night + [timespan]::Parse($PlannedC0); $PlanC = $Night + [timespan]::Parse($PlannedLaunch)
    $NowText = $Now.ToString('yyyy-MM-dd HH:mm')
    $IsElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $Missing = if ($IsElevated) { 'WOULD-FAIL' } else { 'NOT-EVALUABLE' }   # non-elevated, Get-ScheduledTask hides S4U tasks
    $Py = Join-Path $P 'venv\Scripts\python.exe'; $A = Join-Path $R 'receipts-3110'; $WH = Join-Path $R 'wheelhouse'
    $NewPy = Join-Path $NewHome 'python.exe'; $Old = Join-Path $P 'venv-cp3110'
    $Sup = @('WeatherSnapshotLoopSupervisor', 'WeatherClobBookLoopSupervisor', 'WeatherObservationTriggerSupervisor')
    $NightN = Join-Path $R ('night-' + $Night.ToString('yyyyMMdd'))
    # Mirror of the kit's retry GO-review allowlist (run:144-147) and window N (run:148 $WGoAllowSeconds, master ruling 660 s)
    $GoAllowSeconds = 660
    $GoAllowKeys = @('public execution-tape producer is armed but its process/lock/identity contract is unhealthy', 'MAKER_EVIDENCE: STARTING, status age #s', 'MAKER_EVIDENCE: CAPTURING, status age #s')
    Write-Output ("CONTEXT host={0} elevated={1} now={2} night={3} tag={4} P={5} R={6} NewHome={7}" -f $env:COMPUTERNAME, $IsElevated, $NowText, $NightDate, $Tag, $P, $R, $NewHome)

    # --- wrapper preflight (run:46-71; c0:26-29; retry:128-140)
    Use-Check 'SELF-GET-TASKEXACT' 'Get-TaskExact on a live single-match task name returns an array with Count 1 (if not, every task check below misreports)' {
        $all = @(Get-ScheduledTask -ErrorAction SilentlyContinue); $pick = $null
        foreach ($c in $all) { if ($null -eq $pick -and @($all | Where-Object { $_.TaskName -ceq $c.TaskName }).Count -eq 1) { $pick = $c.TaskName } }
        if ($null -eq $pick) { "no single-match task visible (tasks=$($all.Count) elevated=$IsElevated)"; 'NOT-EVALUABLE'; return }
        $t = Get-TaskExact $pick
        "pick=$pick count=$($t.Count) type=$($t.GetType().Name)"; (Get-Verdict ($t -is [array] -and $t.Count -eq 1)) }
    Use-Check 'PF-ELEVATED(run:46,c0:26,retry:128)' 'True (launch the kit elevated)' { $IsElevated; (Get-Verdict $IsElevated) }
    Use-Check 'PF-STDIO-NOT-REDIRECTED(run:47,c0:27,retry:129)' 'err=False out=False (this session; the kit refuses a redirected launch)' {
        $e = [Console]::IsErrorRedirected; $o = [Console]::IsOutputRedirected; "err=$e out=$o"; (Get-Verdict (-not $e -and -not $o)) }
    Use-Check 'PF-C0-FLAG(run:58-61)' "c0-done-$Tag.flag written on $NightDate with head=<40-hex>" {
        $f = Join-Path $R "c0-done-$Tag.flag"
        if (-not (Test-Path -LiteralPath $f)) { "absent now: C0 writes it at ~00:30 on $NightDate"; 'NOT-EVALUABLE'; return }
        $it = Get-Item -LiteralPath $f; $l1 = "$(Get-Content -LiteralPath $f -TotalCount 1)"
        if ($it.LastWriteTime -lt $Night) { "present but written $($it.LastWriteTime.ToString('yyyy-MM-dd HH:mm')) (C0 removes it and rewrites it tonight)"; 'NOT-EVALUABLE'; return }
        "$l1"; (Get-Verdict ($l1 -match 'head=([0-9a-f]{40})')) }
    Use-Check 'PF-OWNER-GO(run:66-68)' "owner-go-$Tag.txt first token GO (case-sensitive)" {
        $f = Join-Path $R "owner-go-$Tag.txt"
        if (-not (Test-Path -LiteralPath $f)) { 'absent now: written after the owner GO at the C0 review'; 'NOT-EVALUABLE'; return }
        $tok = ("$(Get-Content -LiteralPath $f -TotalCount 1)".Trim() -split '\s+')[0]
        "first token '$tok' (written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm')))"; (Get-Verdict ($tok -ceq 'GO')) }
    Use-Check 'C0-FLOOR-0030(c0:29)' "standalone C0 at or after 00:30 on $NightDate" {
        "now=$NowText; planned C0=$($PlanC0.ToString('yyyy-MM-dd HH:mm'))"; (Get-Verdict ($PlanC0 -ge $PlanC0.Date.AddMinutes(30))) }
    Use-Check 'PF-CLOCK-0030-0104(run:69-70,retry:85-87)' "launch in [00:30, 01:04] on $NightDate" {
        $ok = $PlanC -ge $PlanC.Date.AddMinutes(30) -and $PlanC -le $PlanC.Date.AddHours(1).AddMinutes(4)
        "now=$NowText (would refuse now: $(-not ($Now -ge $Now.Date.AddMinutes(30) -and $Now -le $Now.Date.AddHours(1).AddMinutes(4)))); planned=$($PlanC.ToString('yyyy-MM-dd HH:mm'))"; (Get-Verdict $ok) }
    Use-Check 'PF-G3-FLAG-LINE(run:62-65,c0:241)' "c0-done-$Tag.flag holds exactly one 'G3 mode=<strict|dependency> branch=.. tip=.. pregate=.. tested=.. py=..' line" {
        $f = Join-Path $R "c0-done-$Tag.flag"
        if (-not (Test-Path -LiteralPath $f) -or (Get-Item -LiteralPath $f).LastWriteTime -lt $Night) { 'flag for the night not written yet (C0 writes line 2 at ~00:30)'; 'NOT-EVALUABLE'; return }
        $g = @(Get-Content -LiteralPath $f | Where-Object { "$_" -cmatch '^G3 ' })
        $ok = $g.Count -eq 1 -and "$($g[0])".Trim() -cmatch '^G3 mode=(strict|dependency) branch=\S+ tip=(\S+) pregate=(\S+) tested=(\S+) py=(\S+)$'
        "g3_lines=$($g.Count) $($g | Select-Object -First 1)"; (Get-Verdict $ok) }
    Use-Check 'RW-NIGHT-DATE(retry:130)' "retry wrapper launched on $Tag (WRONG_NIGHT otherwise)" {
        "planned=$($PlanC.ToString('yyyyMMdd')) now=$($Now.ToString('yyyyMMdd'))"; (Get-Verdict ($PlanC.ToString('yyyyMMdd') -eq $Tag)) }
    Use-Check 'RW-NO-ATTEMPT-TRANSCRIPTS(retry:133)' "no $R\phase-c-transcript-$Tag-a*.txt (ATTEMPT_TRANSCRIPT_EXISTS otherwise)" {
        $t = @(Get-Item -Path (Join-Path $R "phase-c-transcript-$Tag-a*.txt") -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
        "existing=$($t.Count) [$($t -join ',')]"; (Get-Verdict (-not $t.Count)) }
    Use-Check 'RW-IN-CP3119(retry:125,131)' "retry wrapper launched from its copy in $R (NOT_IN_CP3119 otherwise); the run file beside it" {
        $w = Join-Path $R "phase-c-retry-wrapper-$Tag.ps1"; $ok = (Test-Path -LiteralPath $w) -and (Test-Path -LiteralPath (Join-Path $R "phase-c-run-$Tag.ps1"))
        "wrapper_in_R=$(Test-Path -LiteralPath $w) run_in_R=$(Test-Path -LiteralPath (Join-Path $R "phase-c-run-$Tag.ps1"))"; (Get-Verdict $ok) }
    Use-Check 'RW-GO-REVIEW-FILES-ABSENT(run:89,420-435)' "no stale $NightN\goreview-baseline-flags.txt or aux-restart-at.txt (attempt 1 writes the baseline once; an undo writes the restart time)" {
        $gb = Join-Path $NightN 'goreview-baseline-flags.txt'; $ar = Join-Path $NightN 'aux-restart-at.txt'
        $e1 = Test-Path -LiteralPath $gb; $e2 = Test-Path -LiteralPath $ar
        "N=$NightN goreview-baseline-flags.txt=$e1 aux-restart-at.txt=$e2"; (Get-Verdict (-not $e1 -and -not $e2)) }
    Use-Check "GO-REVIEW-ALLOWLIST-WINDOW(run:144-148,152,427)" "the kit copy's `$WGoAllowSeconds = $GoAllowSeconds (master ruling: N = 660 s, restart -> status sample `$WStatusAt) and its 3 allowlist keys equal this mirror" {
        $rf = Join-Path $R "phase-c-run-$Tag.ps1"
        if (-not (Test-Path -LiteralPath $rf)) { "kit copy absent; mirror N=$GoAllowSeconds s"; 'NOT-EVALUABLE'; return }
        $rt = Read-SharedText $rf
        $kn = if ($rt -cmatch '(?m)^\$WGoAllowSeconds = (\d+)\s') { [int]$Matches[1] } else { $null }
        $kk = @([regex]::Matches($rt, "(?m)^  '([^']+)'[,)]\s+# WRAPPER status\.ps1:") | ForEach-Object { $_.Groups[1].Value })
        $same = ($kn -eq $GoAllowSeconds) -and ($kk.Count -eq $GoAllowKeys.Count) -and -not @($kk | Where-Object { $GoAllowKeys -cnotcontains $_ }).Count
        "kit N=$kn s mirror N=$GoAllowSeconds s; kit keys=$($kk.Count) mirror keys=$($GoAllowKeys.Count)"; (Get-Verdict $same) }
    Use-Check "GO-REVIEW-ALLOWLIST-NOW(run:144-148, informational, N=$GoAllowSeconds s)" "which of the 3 masked allowlist keys the latest status.ps1 -Json output on disk (`$R\c0-status.out.txt) contains (allowed at attempts 2-3 only within $GoAllowSeconds s of the undo's restart); status.ps1 itself is not run" {
        $f = Join-Path $R 'c0-status.out.txt'
        if (-not (Test-Path -LiteralPath $f)) { 'no status.ps1 output on disk to read (c0-status.out.txt absent); running status.ps1 is outside the allowlist'; 'NOT-EVALUABLE'; return }
        $j = Read-SharedJson $f
        if ($null -eq $j -or -not $j.PSObject.Properties['flags']) { 'c0-status.out.txt has no flags field'; 'NOT-EVALUABLE'; return }
        $keys = @(@($j.flags) | ForEach-Object { ([string]$_ -replace '[0-9a-fA-F]{64}', '<sha>') -replace '\d+(\.\d+)?', '#' } | Sort-Object -Unique)
        $hit = @($GoAllowKeys | Where-Object { $keys -ccontains $_ })
        "status output written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm')); keys=$($keys.Count); allowlisted_present=[$($hit -join ' ; ')]; window N=$GoAllowSeconds s"; 'PASS' }
    Use-Check 'G3-RECEIPT-FILE(run:356-362,c0:181-187)' "pregate-receipt-$($G3PregateReceipt.Substring(3)).json in ${R}: one SHA256SUMS.txt line matching size and sha256, schema weather.workstation_pregate_receipt.v1, verdict PASS, head = $G3TestedSha, log_path has $G3PregateReceipt as a path segment" {
        $r = Test-G3ReceiptRO $G3PregateReceipt $G3TestedSha
        if ($r) { "receipt check fails: $r"; 'WOULD-FAIL' } else { 'receipt present and passes the kit predicate'; 'PASS' } }
    Use-Check 'RW-RUN-FILE-HASH(retry:132,134-140)' "local phase-c-run-$Tag.ps1 present; exactly one 3-field SHA256SUMS.txt line matching its size and sha256; that line is the reviewed $($ExpectedRunSha256.Substring(0,12))" {
        $rf = Join-Path $R "phase-c-run-$Tag.ps1"; $sf = Join-Path $R 'SHA256SUMS.txt'
        if (-not (Test-Path -LiteralPath $rf)) { 'run file missing (RUN_FILE_MISSING)'; 'WOULD-FAIL'; return }
        $ln = @(if (Test-Path -LiteralPath $sf) { Get-Content -LiteralPath $sf | Where-Object { ("$_".Trim() -split '\s+')[0] -ceq "phase-c-run-$Tag.ps1" } })
        if ($ln.Count -ne 1) { "SHA256SUMS lines for the run file=$($ln.Count) (RUN_FILE_NOT_IN_SHA256SUMS)"; 'WOULD-FAIL'; return }
        $fld = "$($ln[0])".Trim() -split '\s+'; $len = (Get-Item -LiteralPath $rf).Length; $h = Get-FileSha256 $rf
        $fsz = [long]-1; $match = $fld.Count -eq 3 -and [long]::TryParse($fld[1], [Globalization.NumberStyles]::None, [Globalization.CultureInfo]::InvariantCulture, [ref]$fsz) -and $fsz -eq $len -and $fld[2].ToUpperInvariant() -ceq $h
        $pin = $fld.Count -eq 3 -and $fld[2].ToLowerInvariant() -eq $ExpectedRunSha256.ToLowerInvariant()
        # Kit-literal replay of retry:137-140 (between the PYUPC-SUMS-PREFLIGHT markers) as at 0b90d641c: `$wLine = @(if (..) {..})`
        # keeps one match an array, so $wLine[0] is the whole line (the 26fbc19c0 pre-fix form split its first character and
        # refused), and the size field goes through TryParse, so a non-numeric size refuses instead of throwing.
        $kl = @(if (Test-Path -LiteralPath $sf) { Get-Content -LiteralPath $sf | Where-Object { ("$_".Trim() -split '\s+')[0] -ceq "phase-c-run-$Tag.ps1" } })
        $kf = @("$($kl[0])".Trim() -split '\s+'); $ksz = [long]-1
        $kit = $kl.Count -eq 1 -and -not ($kf.Count -ne 3 -or -not [long]::TryParse($kf[1], [Globalization.NumberStyles]::None, [Globalization.CultureInfo]::InvariantCulture, [ref]$ksz) -or $ksz -ne $len -or $kf[2].ToUpperInvariant() -cne $h)
        $kitTxt = if ($kit) { 'OK' } else { "REFUSED_RUN_FILE_HASH_MISMATCH (fields=$($kf.Count))" }
        "size=$len sha=$($h.Substring(0,12)) sums_line_match=$match reviewed_pin=$pin kit_literal=$kitTxt"; (Get-Verdict ($match -and $pin -and $kit)) }
    Use-Check 'KIT-LOCAL-COPIES(README launch form)' "C0, run and retry-wrapper copies and the pre-gate receipt in $R match SHA256SUMS.txt" {
        $sf = Join-Path $R 'SHA256SUMS.txt'; if (-not (Test-Path -LiteralPath $sf)) { 'SHA256SUMS.txt absent'; 'WOULD-FAIL'; return }
        $sums = @(Get-Content -LiteralPath $sf); $parts = @(); $ok = $true
        foreach ($kf in "phase-c0-run-$Tag.ps1", "phase-c-run-$Tag.ps1", "phase-c-retry-wrapper-$Tag.ps1", "pregate-receipt-$($G3PregateReceipt.Substring(3)).json") {
            $fp = Join-Path $R $kf; $ln = @($sums | Where-Object { ("$_".Trim() -split '\s+')[0] -ceq $kf })
            if (-not (Test-Path -LiteralPath $fp) -or $ln.Count -ne 1) { $parts += "$kf=missing"; $ok = $false; continue }
            $m = (("$($ln[0])".Trim() -split '\s+')[2]).ToUpperInvariant() -ceq (Get-FileSha256 $fp); if (-not $m) { $ok = $false }; $parts += "$kf=$m" }
        ($parts -join ' '); (Get-Verdict $ok) }

    # --- section 6 header, paths, and files the later blocks read (run:209-285)
    Use-Check 'HDR-REPO-ROOT(run:210)' "$P exists with .git" { $ok = (Test-Path -LiteralPath $P) -and (Test-Path -LiteralPath (Join-Path $P '.git')); "exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'HDR-KIT-ROOT(run:212-214,220)' 'R, R\tools and R\receipts-3110 exist (the kit New-Items them; existing evidence expected)' {
        $s = @($R, (Join-Path $R 'tools'), $A | ForEach-Object { "$(Split-Path -Leaf $_)=$(Test-Path -LiteralPath $_)" }); ($s -join ' '); (Get-Verdict (-not ($s -match '=False'))) }
    $K = $null
    Use-Check 'HDR-CONSTANTS(run:221-222,298,603)' 'constants.json present; nupkg_url nupkg_size nupkg_sha512_b64 tools_manifest_sha256 binary_signer_thumbprint vv_prefix binaries non-empty' {
        $f = Join-Path $R 'constants.json'
        if (-not (Test-Path -LiteralPath $f)) { 'absent ($K null: C6 launcher check would NO-GO -> section R)'; 'WOULD-FAIL'; return }
        $script:K = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
        $miss = @('nupkg_url', 'nupkg_size', 'nupkg_sha512_b64', 'tools_manifest_sha256', 'binary_signer_thumbprint', 'vv_prefix', 'binaries') | Where-Object { -not $script:K.$_ }
        "missing=[$($miss -join ',')] vv_prefix='$($script:K.vv_prefix)'"; (Get-Verdict (-not $miss.Count)) }
    $K = $script:K
    Use-Check 'HDR-ADMISSION-HELPER(run:284)' 'scripts\ops\workload_admission.ps1 defines Enter-/Exit-WeatherHeavyWorkloadLease and Get-WeatherHeavyWorkloadLeaseState' {
        $f = Join-Path $P 'scripts\ops\workload_admission.ps1'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-Content -LiteralPath $f -Raw
        $have = @('Enter-WeatherHeavyWorkloadLease', 'Exit-WeatherHeavyWorkloadLease', 'Get-WeatherHeavyWorkloadLeaseState') | Where-Object { $t -match ('(?m)^function ' + [regex]::Escape($_) + '\b') }
        "defines=[$($have -join ',')]"; (Get-Verdict ($have.Count -eq 3)) }
    Use-Check 'HDR-MEMGUARD-HELPER(run:285)' 'scripts\ops\memory_guard_status_reader.ps1 defines Read-WeatherMemoryGuardStatus' {
        $f = Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $ok = (Get-Content -LiteralPath $f -Raw) -match '(?m)^function Read-WeatherMemoryGuardStatus\b'; "defines=$ok"; (Get-Verdict $ok) }
    Use-Check 'HDR-STATUS-PS1(run:408,624,664)' 'scripts\ops\status.ps1 present' { $ok = Test-Path -LiteralPath (Join-Path $P 'scripts\ops\status.ps1'); "exists=$ok"; (Get-Verdict $ok) }

    $OldHomeLines = @(); $OldHome = $null
    if (Test-Path -LiteralPath (Join-Path $R 'oldhome.txt')) { $OldHomeLines = @(Get-Content -LiteralPath (Join-Path $R 'oldhome.txt')); $OldHome = "$(Get-Content -LiteralPath (Join-Path $R 'oldhome.txt') -TotalCount 1)".Trim() }
    Use-Check 'C0-OLDHOME-SINGLE-LINE(run:401,c0:219)' 'oldhome.txt exists; first line non-empty; exactly one non-empty line' {
        if (-not (Test-Path -LiteralPath (Join-Path $R 'oldhome.txt'))) { 'absent'; 'WOULD-FAIL'; return }
        $ne = @($OldHomeLines | Where-Object { "$_".Trim() }).Count
        "first='$OldHome' non_empty_lines=$ne"; (Get-Verdict ([bool]$OldHome -and $ne -eq 1)) }
    Use-Check 'PATH-OLDHOME-PYTHON(run:224,563,569)' '<oldhome>\python.exe exists (the 3.11.0 base the C4 sweep and Test-Venv use)' {
        if (-not $OldHome) { 'oldhome unknown'; 'WOULD-FAIL'; return }; $f = Join-Path $OldHome 'python.exe'; $ok = Test-Path -LiteralPath $f; "$f exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'PATH-PROD-PYTHON(run:211)' "$Py exists" { $ok = Test-Path -LiteralPath $Py; "exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'PATH-PROD-PYVENV(run:184,298-300)' 'venv\pyvenv.cfg home = oldhome and version 3.11.0 (pre-swap)' {
        $f = Join-Path $P 'venv\pyvenv.cfg'; if (-not (Test-Path -LiteralPath $f)) { 'pyvenv.cfg absent'; 'WOULD-FAIL'; return }
        $cfg = @(Get-Content -LiteralPath $f)
        $home1 = @($cfg | Where-Object { $_ -match '^home\s*=' } | ForEach-Object { ($_ -replace '^home\s*=\s*', '').Trim() })[0]
        $ver = @($cfg | Where-Object { $_ -match '^(version|version_info)\s*=' } | ForEach-Object { ($_ -replace '^[a-z_]+\s*=\s*', '').Trim() })[0]
        $ok = $OldHome -and $home1 -and ($home1.TrimEnd('\') -eq $OldHome.TrimEnd('\')) -and "$ver".StartsWith('3.11.0')
        "home='$home1' version='$ver'"; (Get-Verdict $ok) }
    Use-Check 'C0-OLD-VENV-ABSENT(run:400,c0:218)' "$Old absent" { $ex = Test-Path -LiteralPath $Old; "exists=$ex"; (Get-Verdict (-not $ex)) }
    Use-Check 'C4-PROD-VENV-PRESENT(run:587)' "$P\venv exists (the C4 rename source)" { $ok = Test-Path -LiteralPath (Join-Path $P 'venv'); "exists=$ok"; (Get-Verdict $ok) }
    Use-Check 'PATH-NEWHOME(run:215-216,597)' 'new home python.exe and pythonw.exe exist' {
        $s = @('python.exe', 'pythonw.exe' | ForEach-Object { "$_=$(Test-Path -LiteralPath (Join-Path $NewHome $_))" }); ($s -join ' '); (Get-Verdict (-not ($s -match '=False'))) }
    Use-Check 'C6-LAUNCHER-SOURCE(run:603)' 'sha256 of <newhome>\Lib\venv\scripts\nt\python(w).exe equals constants.json binaries (venv copies these launchers)' {
        if (-not $K -or -not $K.binaries) { 'constants.json binaries unavailable'; 'WOULD-FAIL'; return }
        $parts = @(); $ok = $true
        foreach ($ln in 'python.exe', 'pythonw.exe') { $key = "Lib\venv\scripts\nt\$ln"; $src = Join-Path $NewHome $key
            if (-not (Test-Path -LiteralPath $src)) { $parts += "$ln=absent"; $ok = $false; continue }
            $h = Get-FileSha256 $src; $want = ([string]$K.binaries.$key).ToUpper(); $m = $h -eq $want; if (-not $m) { $ok = $false }
            $parts += "$ln match=$m" }
        ($parts -join ' ; '); (Get-Verdict $ok) }
    # 10-22 host run: C5's Build-Venv (run:290-292) is the runbook's B1c verbatim, which already passed in Phase B on this lock and wheelhouse.
    # So the hazards are an EMPTY tools selection (pip refuses an empty -r file), an unhashed tool line, or a lock/wheelhouse changed since Phase B,
    # not "fewer than three" tool pins: the lock is the 3.11.0 freeze, which need not list all of pip/setuptools/wheel.
    Use-Check 'C5-LOCK-WHEELHOUSE(run:290-293)' 'lock-hashed.txt: >=1 tool pin (pip/setuptools/wheel) selected by run:290, each tool line hashed; every lock line hashed; wheelhouse holds .whl files' {
        $lf = Join-Path $R 'lock-hashed.txt'; if (-not (Test-Path -LiteralPath $lf)) { 'lock-hashed.txt absent'; 'WOULD-FAIL'; return }
        $lt = @(Get-Content -LiteralPath $lf | Where-Object { "$_".Trim() })
        $tl = @($lt | Where-Object { $_ -match '^(pip|setuptools|wheel)==' }); $tn = @($tl | ForEach-Object { ($_ -split '==')[0] })
        $tunh = @($tl | Where-Object { $_ -notmatch '--hash=sha256:' }).Count; $unh = @($lt | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==' -and $_ -notmatch '--hash=sha256:' }).Count
        $hashes = @($lt | Where-Object { $_ -match '--hash=sha256:' }).Count
        $whl = @(Get-Item -Path (Join-Path $WH '*.whl') -ErrorAction SilentlyContinue).Count
        "tool_pins=$($tl.Count) [$($tn -join ',')] missing=[$(@('pip','setuptools','wheel' | Where-Object { $tn -notcontains $_ }) -join ',')] unhashed_tool_lines=$tunh unhashed_pin_lines=$unh hash_lines=$hashes wheels=$whl"
        (Get-Verdict ($tl.Count -ge 1 -and $tunh -eq 0 -and $unh -eq 0 -and $hashes -gt 0 -and $whl -gt 0)) }
    Use-Check 'C5-WHEELHOUSE-MANIFEST(run:290-292; runbook B1b wheelhouse-sha256.txt)' 'every wheelhouse file matches wheelhouse-sha256.txt and the two sets are equal (the wheelhouse Phase B qualified is the one C5 installs from)' {
        $mf = Join-Path $R 'wheelhouse-sha256.txt'; if (-not (Test-Path -LiteralPath $mf)) { 'wheelhouse-sha256.txt absent'; 'WOULD-FAIL'; return }
        $want = @{}; foreach ($ln in @(Get-Content -LiteralPath $mf | Where-Object { "$_".Trim() })) { $p = "$ln".Trim() -split '\s+', 2; if ($p.Count -eq 2) { $want[$p[1]] = $p[0].ToUpperInvariant() } }
        $have = @(Get-Item -Path (Join-Path $WH '*') -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer })
        $bad = @(); foreach ($fi in $have) { if (-not $want.ContainsKey($fi.Name)) { $bad += "extra:$($fi.Name)" } elseif ((Get-FileSha256 $fi.FullName) -ne $want[$fi.Name]) { $bad += "hash:$($fi.Name)" } }
        foreach ($k in $want.Keys) { if (@($have | Where-Object { $_.Name -ceq $k }).Count -ne 1) { $bad += "missing:$k" } }
        "manifest=$($want.Count) files=$($have.Count) mismatches=$($bad.Count) [$(@($bad | Select-Object -First 5) -join ', ')]"; (Get-Verdict ($want.Count -gt 0 -and $bad.Count -eq 0)) }
    Use-Check 'C6-RECEIPTS-3110(run:303,326,450)' 'receipts-3110\freeze-3110.txt and rtv-3110.json present; rtv parses with python 3.11.0' {
        $fz = Join-Path $A 'freeze-3110.txt'; $rt = Join-Path $A 'rtv-3110.json'
        if (-not (Test-Path -LiteralPath $fz) -or -not (Test-Path -LiteralPath $rt)) { "freeze=$(Test-Path -LiteralPath $fz) rtv=$(Test-Path -LiteralPath $rt)"; 'WOULD-FAIL'; return }
        $o = Get-Content -LiteralPath $rt -Raw | ConvertFrom-Json
        "freeze_lines=$(@(Get-Content -LiteralPath $fz).Count) rtv.python=$($o.python) implementation=$($o.implementation)"; (Get-Verdict ([string]$o.python -eq '3.11.0')) }
    Use-Check 'C1-FREEZE-UNCHANGED-APPROX(run:448-450)' 'installed dist-info set equals receipts-3110\freeze-3110.txt (approximation: dist-info scan, not pip freeze)' {
        $fz = Join-Path $A 'freeze-3110.txt'; $sp = Join-Path $P 'venv\Lib\site-packages'
        if (-not (Test-Path -LiteralPath $fz) -or -not (Test-Path -LiteralPath $sp)) { 'freeze or site-packages absent'; 'NOT-EVALUABLE'; return }
        $fl = @(Get-Content -LiteralPath $fz)
        $editable = @($fl | Where-Object { $_ -match '#egg=([A-Za-z0-9_.\-]+)' } | ForEach-Object { if ($_ -match '#egg=([A-Za-z0-9_.\-]+)') { ($Matches[1].ToLower() -replace '[-_.]+', '_') } })
        $want = @($fl | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+==' } | ForEach-Object { $n, $v = $_ -split '==', 2; (($n.ToLower() -replace '[-_.]+', '_') + '==' + $v.Trim()) } | Sort-Object -Unique)
        $have = @(Get-Item -Path (Join-Path $sp '*.dist-info') -ErrorAction SilentlyContinue | ForEach-Object { if ($_.Name -match '^(.+?)-([^-]+)\.dist-info$') { $n = $Matches[1].ToLower() -replace '[-_.]+', '_'; if ($editable -notcontains $n) { "$n==$($Matches[2])" } } } | Sort-Object -Unique)
        $miss = @($want | Where-Object { $have -notcontains $_ }); $extra = @($have | Where-Object { $want -notcontains $_ })
        "freeze_pins=$($want.Count) dist_info=$($have.Count) missing=[$($miss -join ',')] extra=[$($extra -join ',')]"; (Get-Verdict (-not $miss.Count -and -not $extra.Count)) }

    # --- C0 GO checks (run:372-434 = c0:198-234)
    $q = $null
    Use-Check 'C0-QUALIFIED-CASE-A(run:380,c0:198,G2)' 'qualification.json result=PASS release_case=A' {
        $f = Join-Path $R 'qualification.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $script:q = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
        "result=$($script:q.result) release_case=$($script:q.release_case) tip=$($script:q.tip)"; (Get-Verdict ($script:q.result -eq 'PASS' -and $script:q.release_case -eq 'A')) }
    $q = $script:q
    Use-Check 'C0-Q12-STOP-AUTHORIZED(run:381,512,c0:199,G8)' 'q12.txt first token STOP_AUTHORIZED' {
        $f = Join-Path $R 'q12.txt'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-KitFirstToken $f; "first token '$t'"; (Get-Verdict ($t -eq 'STOP_AUTHORIZED')) }
    Use-Check 'C0-GAP-CHOICE(run:382,262-263,639-641,c0:200)' 'gap-overrun.txt first token ACCEPT_OVERRUN or ROLLBACK_ON_OVERRUN' {
        $f = Join-Path $R 'gap-overrun.txt'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $t = Get-KitFirstToken $f; "first token '$t'"; (Get-Verdict ($t -in 'ACCEPT_OVERRUN', 'ROLLBACK_ON_OVERRUN')) }
    Use-Check 'C0-U6-NOT-0035(run:383,257-260,c0:201,G5)' 'WeatherReplayBundleExportNightly absent, State Disabled, or no T00:35 trigger' {
        $t = Get-TaskExact 'WeatherReplayBundleExportNightly'
        if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        $u = $t[0]; $at = @($u.Triggers | Where-Object { [string]$_.StartBoundary -match 'T00:35' }).Count
        "State=$($u.State) Enabled=$($u.Settings.Enabled) T00:35_triggers=$at"; (Get-Verdict (-not ([string]$u.State -ne 'Disabled' -and $at -gt 0))) }
    $Head = $null
    if (Test-Path -LiteralPath (Join-Path $P '.git')) { $Head = "$(git --no-optional-locks -C $P rev-parse HEAD)".Trim(); if ($LASTEXITCODE) { $Head = $null } }
    Use-Check 'C0-HEAD-VS-QUALIFIED-TIP(run:384-385,c0:202-203)' "qualification.json tip = -G3QualifiedTip $G3QualifiedTip (dependency mode: else G3 FAIL reason=operator_tip_ne_qualification_json; strict mode uses the qualification.json tip)" {
        if (-not $Head) { 'HEAD unreadable'; 'NOT-EVALUABLE'; return }; if (-not $q) { "HEAD=$Head tip=<no qualification.json>"; 'NOT-EVALUABLE'; return }
        $same = $G3QualifiedTip -ceq ([string]$q.tip).Trim().ToLowerInvariant()
        "HEAD=$Head qualification.tip=$($q.tip) head_is_tip=$($Head -eq [string]$q.tip)"; (Get-Verdict $same) }
    $FamilyTasks = @(Get-ScheduledTask -TaskName 'WeatherMakerEvidence*' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ne 'WeatherMakerEvidenceCapture' } | ForEach-Object { $_.TaskName })
    $AuxFile = Join-Path $R 'aux-tasks.txt'
    $AuxNames = @(); if (Test-Path -LiteralPath $AuxFile) { $AuxNames = @(Get-Content -LiteralPath $AuxFile | Where-Object { $_.Trim() }) }
    Use-Check 'C0-FAMILY-Q12B(run:390-395,c0:208-213)' 'no WeatherMakerEvidence<Family> task, or q12b.txt STOP_AUTHORIZED and every family task in aux-tasks.txt' {
        if (-not $FamilyTasks.Count) { "family tasks=none (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        $f = Join-Path $R 'q12b.txt'; $t = if (Test-Path -LiteralPath $f) { Get-KitFirstToken $f } else { '<absent>' }
        $trimmed = @(Get-Content -LiteralPath $AuxFile -ErrorAction SilentlyContinue | ForEach-Object { $_.Trim() }); $notAux = @($FamilyTasks | Where-Object { $trimmed -notcontains $_ })
        "family=[$($FamilyTasks -join ',')] q12b='$t' not_in_aux=[$($notAux -join ',')]"; (Get-Verdict ($t -eq 'STOP_AUTHORIZED' -and -not $notAux.Count)) }
    Use-Check 'C0-AUX-NAMES-RESOLVE(run:396-397,491,c0:214-215)' 'aux-tasks.txt present; every name matches exactly one task' {
        if (-not (Test-Path -LiteralPath $AuxFile)) { 'aux-tasks.txt absent'; 'WOULD-FAIL'; return }
        $bad = @(); foreach ($n in $AuxNames) { $c = (Get-TaskExact $n).Count; if ($c -ne 1) { $bad += "$n=$c" } }
        "names=$($AuxNames.Count) unresolved_or_duplicate=[$($bad -join ',')]"
        if (-not $bad.Count) { 'PASS' } elseif (@($bad | Where-Object { $_ -notmatch '=0$' }).Count) { 'WOULD-FAIL' } else { $Missing } }
    Use-Check 'C0-CLOB-ENRICHMENT-STATE(run:398,c0:216)' 'WeatherClobEnrichmentLoop absent or State Disabled (not Settings.Enabled: a running instance fails)' {
        $t = Get-TaskExact 'WeatherClobEnrichmentLoop'
        if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled)"; (Get-Verdict ([string]$t[0].State -eq 'Disabled')) }
    Use-Check 'C0-PROD-TREE-CLEAN(run:399,606,c0:217)' 'git status --porcelain --untracked-files=no empty' {
        if (-not (Test-Path -LiteralPath (Join-Path $P '.git'))) { 'no repo'; 'WOULD-FAIL'; return }
        $s = @(git --no-optional-locks -C $P status --porcelain --untracked-files=no); if ($LASTEXITCODE) { "git exit $LASTEXITCODE"; 'NOT-EVALUABLE'; return }
        "dirty_entries=$($s.Count) $($s | Select-Object -First 5)"; (Get-Verdict (-not $s.Count)) }
    Use-Check 'C0-DISK-10GB(run:402,c0:220)' 'C: free >= 10 GB (Win32_LogicalDisk FreeSpace, same volume as Get-Volume)' {
        $d = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='C:'"; $gb = [math]::Round($d.FreeSpace / 1GB, 1); "free=${gb}GB"; (Get-Verdict ($d.FreeSpace -ge 10GB)) }
    foreach ($tn in 'WeatherTrainingWindow', 'WeatherEveningEvidenceRefresh') {
        Use-Check "C0-G5-$tn(run:403-404,c0:221-222,G5)" 'absent or State Disabled (State: a disabled task still running holds the lease)' {
            $t = Get-TaskExact $tn
            if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
            "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled)"; (Get-Verdict ([string]$t[0].State -eq 'Disabled')) } }
    Use-Check 'C0-MEMGUARD-STATUS-READABLE(run:405,c0:223)' 'data\logs\memory_commit_guard_status.json reads as JSON (Read-WeatherMemoryGuardStatus throws otherwise)' {
        $f = Join-Path $P 'data\logs\memory_commit_guard_status.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $j = Read-SharedJson $f; "parsed; last_write=$((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"; (Get-Verdict ($null -ne $j)) }
    Use-Check 'C0-STATUS-BASELINE(run:408-409,271-277,c0:225-226)' 'status.ps1 -Json prints JSON with a flags field; capture 3/3; no unaccepted FLAG' {
        $f = Join-Path $R 'c0-status.out.txt'; $r0 = if (Test-Path -LiteralPath $f) { "last c0-status.out.txt written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))" } else { 'no earlier c0-status.out.txt' }
        "$r0; status.ps1 itself not run (outside the read-only allowlist; it is run by C0 at 00:30)"; 'NOT-EVALUABLE' }
    Use-Check 'C0-RELEASE-POINTER-ABSENT(run:266,G6)' 'artifacts\releases\current_release.json absent (case A)' {
        $ex = Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json'); "exists=$ex"; (Get-Verdict (-not $ex)) }
    Use-Check 'C0-RELEASE-CLI-CASE-A(run:410,245-255,264-265,c0:227)' 'release_lifecycle_cli active -> BLOCK "active release pointer is missing"' { 'needs python (release_lifecycle_cli); outside the read-only allowlist'; 'NOT-EVALUABLE' }
    Use-Check 'C0-RESTORE-ARMED(c0:233)' 'WeatherTrainingWindowRestore not Disabled, with an enabled T04:15 trigger' {
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
    Use-Check 'C0-NEXT-RUNS-ALL(run:411-415,c0:228-232,C0 go/no-go)' "c0-next-runs.txt empty: no non-exempt task due $($DueFrom.ToString('MM-dd HH:mm'))-$($DueTo.ToString('HH:mm')) (predicted from triggers)" {
        if ($DueErr) { "error: $DueErr"; 'NOT-EVALUABLE'; return }
        "due=$($Due.Count) [$($Due -join ', ')] (elevated=$IsElevated)"; $(if (-not $IsElevated) { 'NOT-EVALUABLE' } elseif ($Due.Count) { 'WOULD-FAIL' } else { 'PASS' }) }
    # The wrapper exits 4 only on a root task due before 04:00 at the attempt's C0 re-run that is ABSENT from the standalone 00:30 C0 list,
    # which attempt 1 freezes into c0-go-reviewed-<tag> before its own re-run (run:377, 431-434). A root task listed by the 00:30 C0 is "seen".
    # Today there is no 00:30 list, so this only lists the root tasks the 00:30 C0 must show and the GO review must accept (informational).
    Use-Check 'POSTC0-NEXT-RUNS-ROOT(run:377,431-434,G5)' 'root-folder tasks due before 04:00 are listed by the 00:30 standalone C0 (then "seen": no exit 4); one newly due only at an attempt gives exit 4' {
        if ($DueErr) { "error: $DueErr"; 'NOT-EVALUABLE'; return }
        "root_due=$($DueRoot.Count) [$($DueRoot -join ', ')] (each must appear in the 00:30 C0 c0-next-runs.txt and be accepted at the GO review)"; $(if (-not $IsElevated) { 'NOT-EVALUABLE' } else { 'PASS' }) }
    Use-Check 'POSTC0-GO-REVIEWED-BASELINE(run:374-379,419-430)' "c0-status-flags.txt present at launch; c0-go-reviewed-$Tag absent before attempt 1; no flag new since the GO review" {
        $f = Join-Path $R 'c0-status-flags.txt'; $r0 = if (Test-Path -LiteralPath $f) { "present, written $((Get-Item -LiteralPath $f).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))" } else { 'absent' }
        $rev = Join-Path $R "c0-go-reviewed-$Tag"; $rv = if (Test-Path -LiteralPath (Join-Path $rev 'c0-status-flags.txt')) { 'present (attempt 1 seeds it; a stale copy would be kept)' } else { 'absent' }
        "$r0; c0-go-reviewed-$Tag=$rv; C0 rewrites the baseline at 00:30 on $NightDate and attempt 1 copies it"; 'NOT-EVALUABLE' }
    Use-Check 'POSTC0-HEAD-EQUALS-FLAG(run:418)' 'HEAD at launch = head= in the C0 flag' {
        $f = Join-Path $R "c0-done-$Tag.flag"
        if (-not (Test-Path -LiteralPath $f) -or (Get-Item -LiteralPath $f).LastWriteTime -lt $Night) { "HEAD now=$Head; flag for $NightDate not written yet"; 'NOT-EVALUABLE'; return }
        $fh = if ("$(Get-Content -LiteralPath $f -TotalCount 1)" -match 'head=([0-9a-f]{40})') { $Matches[1] } else { '<none>' }
        "HEAD=$Head flag=$fh"; (Get-Verdict ($Head -and $Head -eq $fh)) }

    # --- C1 lease and receipts (run:440-456); lease read-only probe
    Use-Check 'C1-POLICY-WINDOW(workload_admission.ps1:596-598,run:719 C1_THROW)' 'agent_heavy window (00:30-09:00) at the planned launch' {
        $m = $PlanC.Hour * 60 + $PlanC.Minute; $mn = $Now.Hour * 60 + $Now.Minute
        "planned=agent_heavy:$($m -ge 30 -and $m -lt 540) now=agent_heavy:$($mn -ge 30 -and $mn -lt 540)"; (Get-Verdict ($m -ge 30 -and $m -lt 540)) }
    Use-Check 'C1-LEASE-FREE(run:442-444,workload_admission.ps1:1804-1815,1975-1986)' 'Global\WeatherProjectHeavyWorkloadV1 not held and heavy_workload.lock not owned by a live process' {
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
    Use-Check 'C1-LEASE-DEADLINE-0104(run:442-446)' 'lease by 01:04 (launch in the 00:30-01:04 C1 window, free lease: first probe succeeds)' {
        "planned_launch=$($PlanC.ToString('HH:mm')) deadline=01:04 now=$NowText"; (Get-Verdict ($PlanC -le $PlanC.Date.AddHours(1).AddMinutes(4))) }
    Use-Check 'C1-CAPTURE-STATUS-FILES(run:451)' 'data\snapshots loop_status.json, clob_loop_status.json, observation_trigger_status.json exist (Copy-Item would throw)' {
        $s = @('loop_status.json', 'clob_loop_status.json', 'observation_trigger_status.json' | ForEach-Object { "$_=$(Test-Path -LiteralPath (Join-Path $P "data\snapshots\$_"))" }); ($s -join ' '); (Get-Verdict (-not ($s -match '=False'))) }
    $ShadowStop = $null; $ShadowTask = Get-TaskExact 'WeatherMakerShadowRunner'
    Use-Check 'C1-SHADOW-STOP-FILE(run:452-456)' 'shadow task absent, or Actions[0].Arguments has --stop-file "<path>"' {
        if (-not $ShadowTask.Count) { "not visible (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        if ([string]$ShadowTask[0].Actions[0].Arguments -match '--stop-file\s+"([^"]+)"') { $script:ShadowStop = $Matches[1]; "stop_file=$($Matches[1]) present_now=$(Test-Path -LiteralPath $Matches[1])"; 'PASS' }
        else { 'stop-file argument unreadable'; 'WOULD-FAIL' } }
    $ShadowStop = $script:ShadowStop

    # --- C2 quiesce (run:458-522)
    Use-Check 'C2-PRESTATE-CSV-ABSENT(run:493)' "$NightN\aux-prestate.csv absent (else C2 reuses an old pre-state)" {
        $f = Join-Path $NightN 'aux-prestate.csv'; $ex = Test-Path -LiteralPath $f; "exists=$ex"; (Get-Verdict (-not $ex)) }
    foreach ($an in $AuxNames) {
        $at = Get-TaskExact $an
        Use-Check "C2-ENABLED-$an(run:494,503-504)" 'exactly one task; live Settings.Enabled readable as True/False (C2 verifies the disable with Settings.Enabled -eq $false)' {
            if ($at.Count -ne 1) { "matches=$($at.Count) (elevated=$IsElevated)"; $(if ($at.Count -eq 0) { $Missing } else { 'WOULD-FAIL' }); return }
            $en = $at[0].Settings.Enabled; "State=$($at[0].State) Settings.Enabled=$en"; (Get-Verdict ($en -is [bool])) }
        Use-Check "C2-PRESTATE-$an(run:464-465,467-468)" 'pre-state row Enabled column is exactly True or False (Test-PrestateEnabled takes the exact path)' {
            if ($at.Count -ne 1) { "matches=$($at.Count)"; $(if ($at.Count -eq 0) { $Missing } else { 'WOULD-FAIL' }); return }
            $row = [pscustomobject]@{ Task = $an; State = [string]$at[0].State; Enabled = [string]$at[0].Settings.Enabled }
            $exact = $row.Enabled -in 'True', 'False'
            $wouldRestore = if ($row.Enabled) { $row.Enabled -eq 'True' } else { $row.State -ne 'Disabled' }
            $note = if (-not $wouldRestore -and $row.State -eq 'Running') { ' (disabled but running: C9b leaves it disabled, ESCALATE)' } else { '' }
            "row State=$($row.State) Enabled='$($row.Enabled)' -> undo re-enables=$wouldRestore$note"; (Get-Verdict $exact) } }
    Use-Check 'C2-SHADOW-SEALABLE(run:496-501)' 'shadow not in aux-tasks.txt, or its stop-file path is known' {
        if ($AuxNames -notcontains 'WeatherMakerShadowRunner') { 'shadow not in aux list'; 'PASS'; return }
        $st = if ($ShadowTask.Count) { [string]$ShadowTask[0].State } else { '<not visible>' }
        "stop_file=$ShadowStop State=$st"; $(if ($ShadowStop) { 'PASS' } elseif (-not $ShadowTask.Count -and -not $IsElevated) { 'NOT-EVALUABLE' } else { 'WOULD-FAIL' }) }
    Use-Check 'C2-TAPE-ENSURE-BOUND(run:507-509)' 'WeatherExecutionTapeSupervisor ExecutionTimeLimit <= 150 s (the C2 wait bound; 01:12 arithmetic)' {
        if ($AuxNames -notcontains 'WeatherExecutionTapeSupervisor') { 'tape supervisor not in aux list'; 'PASS'; return }
        $t = Get-TaskExact 'WeatherExecutionTapeSupervisor'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        $lim = [string]$t[0].Settings.ExecutionTimeLimit; $s = Get-SpanSeconds $lim
        "ExecutionTimeLimit=$lim MultipleInstances=$($t[0].Settings.MultipleInstances) State=$($t[0].State)"; (Get-Verdict ($s -and $s -gt 0 -and $s -le 150)) }
    Use-Check 'C2-88A-TASK-REGISTERED(run:511-513)' 'WeatherMakerEvidenceCapture resolves (a non-SilentlyContinue Get-ScheduledTask under Stop)' {
        $t = Get-TaskExact 'WeatherMakerEvidenceCapture'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled)"; 'PASS' }
    Use-Check 'C2-TAPE-STOP-VERB(run:475-487,510)' 'execution_tape_supervisor stop exits 0, or process_gone, or status_pid_unknown + unhealthy' { 'needs python (execution_tape_supervisor stop); outside the read-only allowlist'; 'NOT-EVALUABLE' }

    # --- C3 / C4 (run:523-594)
    foreach ($sn in $Sup) {
        Use-Check "C3-SUPERVISOR-$sn(run:528-534,610)" 'exactly one task; Settings.Enabled True now; ExecutionTimeLimit <= 330 s (the C3 ensure wait)' {
            $t = Get-TaskExact $sn; if ($t.Count -ne 1) { "matches=$($t.Count) (elevated=$IsElevated)"; $(if ($t.Count -eq 0) { $Missing } else { 'WOULD-FAIL' }); return }
            $lim = [string]$t[0].Settings.ExecutionTimeLimit; $s = Get-SpanSeconds $lim
            "State=$($t[0].State) Enabled=$($t[0].Settings.Enabled) ExecutionTimeLimit=$lim"; (Get-Verdict ($t[0].Settings.Enabled -eq $true -and $s -and $s -gt 0 -and $s -le 330)) } }
    Use-Check 'C3-PRE-DEADLINE-0112(run:577-579)' 'latest lease 01:04 + worst-case C1+C2 8.0 min (README CLOCKS) <= 01:12' {
        $t = $PlanC.Date.AddHours(1).AddMinutes(12); $w = $PlanC.Date.AddHours(1).AddMinutes(4).AddMinutes(8)
        "planned launch $($PlanC.ToString('HH:mm')) -> C3 by about $($PlanC.AddMinutes(8.2).ToString('HH:mm:ss')); worst case (lease 01:04) $($w.ToString('HH:mm:ss'))"; (Get-Verdict ($w -le $t -and $PlanC.AddMinutes(8.2) -le $t)) }
    Use-Check 'C3-STOP-VERBS-AND-GATE(run:536-545)' 'three stop verbs exit 0; capture_resource_gate no_live_capture exits 0 within 600 s' { 'needs python and a real stop; outside the read-only allowlist'; 'NOT-EVALUABLE' }
    Use-Check 'C4-RENAME-DEADLINE-0130(run:586)' '01:12 + C3 pass-case worst case 17.5 min (runbook) <= 01:30' {
        $t = $PlanC.Date.AddHours(1).AddMinutes(12).AddSeconds(17.5 * 60); "worst-case rename at $($t.ToString('HH:mm:ss'))"; (Get-Verdict ($t -le $PlanC.Date.AddHours(1).AddMinutes(30))) }
    Use-Check 'C4-HOLDERS-KNOWN(run:563-576)' 'every current holder of venv is a worker C2/C3 stops (capture, tape, shadow, 88a, family)' {
        $dir = Join-Path $P 'venv'; $ohn = if ($OldHome) { $OldHome.TrimEnd('\') } else { '<none>' }; $nhn = $NewHome.TrimEnd('\')
        $hold = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
                $_.ExecutablePath -like "$dir\*" -or $_.CommandLine -like "*$dir\*" -or
                (($_.ExecutablePath -like "$ohn\*" -or $_.ExecutablePath -like "$nhn\*") -and $_.CommandLine -like "*$P\*") })
        $known = 'snapshot_tracker|market_microstructure|observation_trigger|execution_tape_supervisor|maker_shadow|maker_evidence'
        $unknown = @($hold | Where-Object { "$($_.CommandLine)" -notmatch $known } | ForEach-Object { "pid $($_.ProcessId): $("$($_.CommandLine)".Substring(0, [math]::Min(120, "$($_.CommandLine)".Length)))" })
        $nocl = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { -not $_.CommandLine }).Count
        "holders=$($hold.Count) unknown=[$($unknown -join ' ; ')] python_without_visible_cmdline=$nocl"
        if ($unknown.Count) { 'WOULD-FAIL' } elseif ($nocl -and -not $IsElevated) { 'NOT-EVALUABLE' } else { 'PASS' } }

    # --- C7 restore, C8, C9c reads (run:547-555, 610-624, 652-691)
    Use-Check 'C7-RESTORE-TASK(run:547-555,610-611)' 'WeatherTrainingWindowRestore resolves; ExecutionTimeLimit <= 15 min (Wait-Restore budget 32 min = run + rerun)' {
        $t = Get-TaskExact 'WeatherTrainingWindowRestore'; if (-not $t.Count) { "not visible (elevated=$IsElevated)"; $Missing; return }
        $lim = [string]$t[0].Settings.ExecutionTimeLimit; $s = Get-SpanSeconds $lim
        "State=$($t[0].State) ExecutionTimeLimit=$lim"; (Get-Verdict ($s -and $s -gt 0 -and $s -le 900)) }
    Use-Check 'C7-TRAINING-WINDOW-STATUS(run:550-552)' 'data\logs\training_window_status.json parses with updated_at, phase, outcome (Wait-Restore reads it under Stop)' {
        $f = Join-Path $P 'data\logs\training_window_status.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $j = Read-SharedJson $f; $ok = $j.updated_at -and $j.PSObject.Properties['phase'] -and $j.PSObject.Properties['outcome']
        "updated_at=$($j.updated_at) phase=$($j.phase) outcome=$($j.outcome)"; (Get-Verdict ([bool]$ok)) }
    foreach ($sf in 'loop_status.json', 'clob_loop_status.json', 'observation_trigger_status.json') {
        Use-Check "C8-PYVER-FIELD-$sf(run:617-619,201-202)" 'runtime_identity.python_version present (3.11.0 before the swap; C8 requires 3.11.9 after)' {
            $f = Join-Path $P "data\snapshots\$sf"; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
            $v = (Read-SharedJson $f).runtime_identity.python_version; "python_version=$v"; (Get-Verdict ([string]$v -eq '3.11.0')) } }
    Use-Check 'C9C-88A-STATUS(run:658-659,686-691)' 'data\maker_evidence\status.json parses (a hard read in C9c)' {
        $f = Join-Path $P 'data\maker_evidence\status.json'; if (-not (Test-Path -LiteralPath $f)) { 'absent'; 'WOULD-FAIL'; return }
        $m = Read-SharedJson $f; "state=$($m.state) updated=$($m.updated_at_utc) last_error=$($m.last_error)"; 'PASS' }
    Use-Check 'C9C-FAMILY-STATUS(run:660-663)' 'for each family task, data\maker_evidence_families\<fid>\status.json parses' {
        if (-not $FamilyTasks.Count) { "family tasks=none (elevated=$IsElevated)"; $(if ($IsElevated) { 'PASS' } else { 'NOT-EVALUABLE' }); return }
        $bad = @(); foreach ($ft in $FamilyTasks) { $fid = (($ft -replace '^WeatherMakerEvidence', '') -creplace '([a-z0-9])([A-Z])', '$1_$2').ToLowerInvariant()
            $f = Join-Path $P "data\maker_evidence_families\$fid\status.json"; try { $null = Read-SharedJson $f } catch { $bad += $fid } }
        "family=[$($FamilyTasks -join ',')] unreadable=[$($bad -join ',')]"; (Get-Verdict (-not $bad.Count)) }
    Use-Check 'C9C-TAPE-HEALTH(run:652-657,670-674)' 'execution_tape_supervisor status RUNNING, identity current, integrity PASS, CONNECTED' { 'needs python (execution_tape_supervisor status); outside the read-only allowlist'; 'NOT-EVALUABLE' }

    # --- section R interpreter resolution (run:162-177)
    foreach ($kv in @(@('snapshot', 'loop_status.json'), @('clob', 'clob_loop_status.json'), @('obs', 'observation_trigger_status.json'), @('tape', 'execution_tape_status.json'))) {
        $key = $kv[0]; $file = $kv[1]
        Use-Check "R-STOP-INTERPRETER-$key(run:165-175)" 'managed_process.expected_command[0] recorded and its same-directory python.exe exists (else the probe fallback runs)' {
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
    # --- G3: kit Test-G3Gate (run :343-372, c0 :168-197) and its call sites (run :385-388, :438; c0 :203-206, :234), read-only.
    #     Printed after every C0 predicate so (iii) can AND them. -HeadOverride replaces HEAD here only.
    function Test-G3GateRO([string]$Mode, [string]$GHead, [string]$QualTip, [string]$Receipt, [string]$Tested, [string]$PyAttest) {
        $Body = { param($r) [pscustomobject]@{ Pass = $false; Status = 'FAIL'; Mode = $Mode; Branch = 'none'; Detail = $r } }
        if (@('strict', 'dependency') -cnotcontains "$Mode") { return (& $Body 'g3mode_missing_or_invalid') }
        if ("$QualTip" -cnotmatch '^[0-9a-f]{40}$') { return (& $Body 'qualified_tip_not_supplied_as_40hex') }
        if ($GHead -ceq $QualTip) { return [pscustomobject]@{ Pass = $true; Status = 'PASS'; Mode = $Mode; Branch = 'HEAD==tip'; Detail = "tip=$QualTip" } }
        if ($Mode -ceq 'strict') { return [pscustomobject]@{ Pass = $true; Status = 'DEFER'; Mode = $Mode; Branch = 'HEAD!=tip'; Detail = 'requires=ROLL-FREE-at-GO-review' } }
        $wNames = @(git --no-optional-locks -C $P diff --no-ext-diff --name-only $QualTip $GHead); if ($LASTEXITCODE) { return (& $Body 'diff_tip_head_failed') }
        $wDeps = @($wNames | Where-Object { $wLeaf = ("$_" -split '/')[-1]; $wLeaf -like 'requirements*' -or $wLeaf -like 'constraints*' -or $wLeaf -like '*.lock' -or $wLeaf -in 'pyproject.toml', 'setup.cfg', 'setup.py' })
        if ($wDeps.Count) { return (& $Body "deps_changed=$(@($wDeps | Select-Object -First 5) -join ',')") }
        if ("$Receipt" -cnotmatch '^pg-([0-9a-f]{12})-[0-9]{8}T[0-9]{6}-[0-9]+$') { return (& $Body 'pregate_receipt_not_supplied_or_malformed') }
        $wRp = $Matches[1]
        if ("$Tested" -cnotmatch '^[0-9a-f]{40}$' -or -not $Tested.StartsWith($wRp)) { return (& $Body 'tested_sha_not_40hex_or_not_the_receipt_head') }
        if ("$PyAttest" -cne '3.11.9') { return (& $Body 'pregate_python_3.11.9_not_attested') }
        $wRr = Test-G3ReceiptRO $Receipt $Tested; if ($wRr) { return (& $Body $wRr) }
        $null = @(git --no-optional-locks -C $P rev-parse --verify --quiet "$Tested^{commit}"); if ($LASTEXITCODE) { return (& $Body 'tested_sha_not_in_production_repo') }
        $wTd = @(git --no-optional-locks -C $P diff --no-ext-diff --name-only $Tested $GHead); if ($LASTEXITCODE) { return (& $Body 'diff_tested_head_failed') }
        $wNd = @($wTd | Where-Object { "$_" -cnotmatch '^docs/.+\.md$' })
        $wFleet = @('config/locations.json', 'config/location_market_events.json')   # the only exempt paths: exact, case-sensitive, no globbing
        $wEx = @($wNd | Where-Object { $wFleet -ccontains "$_" })
        $wRest = @($wNd | Where-Object { $wFleet -cnotcontains "$_" })
        if ($wRest.Count) { return (& $Body "nondocs_diff=$($wRest.Count):$(@($wRest | Select-Object -First 5) -join ',')") }
        $wExS = if ($wEx.Count) { $wEx -join ',' } else { 'none' }
        [pscustomobject]@{ Pass = $true; Status = 'PASS'; Mode = $Mode; Branch = '(i)+(ii)+(iii)'; Detail = "deps_changed=none pregate=$Receipt tested=$Tested py=attested nondocs_diff=empty fleet_drift_exempt=$wExS" } }
    $g3Modes = if ($G3Mode) { @($G3Mode) } else { @('strict', 'dependency') }
    $g3Head = $Head; $g3Note = ''
    if ($HeadOverride) {
        $ho = $null; if (Test-Path -LiteralPath (Join-Path $P '.git')) { $ho = "$(git --no-optional-locks -C $P rev-parse --verify --quiet "$HeadOverride^{commit}")".Trim() }
        $g3Head = $ho; $g3Note = "HEAD-OVERRIDE IN USE head=$ho (live HEAD=$Head; the override feeds only G3) ; "
        Write-Output "CONTEXT HEAD-OVERRIDE IN USE for G3 only: -HeadOverride $HeadOverride -> $ho; every other predicate uses the live HEAD $Head" }
    # (iii) mirrors both call sites: the standalone C0 (c0:234, after every C0 check) and the attempt (run:438, also after the
    # post-C0 GO-review checks run:418-434: HEAD vs flag, flags vs the GO review or the retry delta, root next-runs).
    $c0Ids = @($script:Verdicts.Keys | Where-Object { ($_ -like 'C0-*' -or $_ -like 'POSTC0-*') -and $_ -notlike 'C0-HEAD-VS-QUALIFIED-TIP*' -and $_ -notlike 'C0-FLOOR*' })
    $c0Fail = @($c0Ids | Where-Object { $script:Verdicts[$_] -eq 'WOULD-FAIL' }); $c0Ne = @($c0Ids | Where-Object { $script:Verdicts[$_] -eq 'NOT-EVALUABLE' })
    foreach ($gm in $g3Modes) {
        $gid = "G3-$gm(run:343-372,385-388,438;c0:168-197,203-206,234)"
        $gexp = if ($gm -eq 'strict') { 'G3 PASS mode=strict branch=HEAD==tip (qualification.json tip), or G3 DEFER mode=strict branch=HEAD!=tip requires=ROLL-FREE-at-GO-review; C0 other checks clean' } else { "G3 PASS mode=dependency (HEAD==tip, or (i)+(ii)+(iii) with fleet_drift_exempt only config/locations.json, config/location_market_events.json); operator tip $G3QualifiedTip = qualification.json tip; C0 other checks clean" }
        try {
            if (-not $g3Head) { throw 'HEAD unreadable (no repo at -RepoRoot, or -HeadOverride does not resolve)' }
            $qTip = if ($q) { ([string]$q.tip).Trim().ToLowerInvariant() } else { $null }
            $tipNote = if ($q) { "qualification.json tip=$qTip" } else { "qualification.json unread here (strict falls back to -G3QualifiedTip $G3QualifiedTip; dependency skips the operator-tip match)" }
            $gate = $null
            if ($gm -ceq 'dependency' -and $qTip -and $G3QualifiedTip -cne $qTip) { $kitLine = "G3 FAIL reason=operator_tip_ne_qualification_json supplied=$G3QualifiedTip qualification=$($q.tip)" }
            else {
                $useTip = if ($gm -ceq 'strict') { if ($qTip) { $qTip } else { $G3QualifiedTip } } else { $G3QualifiedTip }
                $gate = Test-G3GateRO $gm $g3Head $useTip $G3PregateReceipt $G3TestedSha $G3PregatePython
                $kitLine = if ($gate.Pass) { "G3 $($gate.Status) mode=$($gate.Mode) branch=$($gate.Branch) $($gate.Detail)" } else { "G3 FAIL reason=$($gate.Detail) mode=$gm head=$g3Head tip=$G3QualifiedTip" } }
            $iii = if ($c0Fail.Count) { "would-fail:[$($c0Fail -join ',')]" } elseif ($c0Ne.Count) { "clean-where-evaluable(unevaluated here: $($c0Ne.Count))" } else { 'clean' }
            $v = if (-not $gate -or -not $gate.Pass) { 'WOULD-FAIL' } elseif ($c0Fail.Count) { 'WOULD-FAIL' } elseif ($gate.Status -ceq 'DEFER') { 'DEFER' } else { 'PASS' }
            Push-Check $gid "$g3Note$kitLine ; $tipNote ; iii=$iii" $gexp $v }
        catch { Push-Check $gid ("$g3Note" + 'error: ' + $_.Exception.Message) $gexp 'NOT-EVALUABLE' } }
    Use-Check 'G12-DOWNLOADS-APPROVED' 'owner approved the wheel and NuGet downloads' { 'owner record (the wheelhouse is checked in C5-LOCK-WHEELHOUSE)'; 'NOT-EVALUABLE' }
}
catch { Write-Output ("CHECK REHEARSAL-ABORTED | read=error: {0} | expected=completed rehearsal | NOT-EVALUABLE" -f ($_.Exception.Message -replace '\|', '/')); $script:Count['NOT-EVALUABLE']++ }
finally {
    if ($exitCode -eq 0) {
        $verdict = if ($script:Count['WOULD-FAIL']) { 'WOULD-FAIL' } elseif ($script:Count['DEFER']) { 'DEFER-TO-GO-REVIEW' } elseif ($script:Count['NOT-EVALUABLE']) { 'PASS-WITH-UNEVALUATED' } else { 'PASS' }
        $summary = 'SUMMARY | pass={0} | defer={5} | would-fail={1} | not-evaluable={2} | verdict={3} | non-pass=[{4}]' -f $script:Count['PASS'], $script:Count['WOULD-FAIL'], $script:Count['NOT-EVALUABLE'], $verdict, ($script:FailIds -join ', '), $script:Count['DEFER']
        $script:Lines.Add($summary)
        [Console]::Out.WriteLine($summary)
        if ($OutFile) { try { [IO.File]::WriteAllLines($OutFile, $script:Lines.ToArray()) } catch { [Console]::Out.WriteLine("OUTFILE not written: $($_.Exception.Message)") } }
    }
    exit $exitCode
}
