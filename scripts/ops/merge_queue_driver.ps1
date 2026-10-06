# Drive an owner-signed merge queue whose entries are bound to immutable commits.
# Missing queues are a no-op; an unsigned, malformed or moved queue fails the entire run before
# a merge. -Dry evaluates the queue against the night's real gates (owner signature, exact tips,
# preflight receipts, the heavy-work lease, Scheduler LastRunTime/LastTaskResult) and writes a
# "would have run X at T" receipt. Dry mode takes no lease, registers/starts/stops no task,
# merges nothing, fetches nothing and pushes nothing: it only reads.
# The queue format, signing procedure and the dry pilot are owned by
# docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md ("Merge-train dry pilot").
[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$QueueFile,
    [Parameter(Mandatory = $true)][string]$LogFile,
    # Detached SSH signature made by the owner over the exact queue bytes.
    [string]$SignatureFile = "",
    # Trust anchor: the allowed_signers file on the production checkout's master.
    [string]$AllowedSignersFile = "",
    [string]$SignerIdentity = "owner",
    [string]$SshKeygenPath = "",
    [switch]$Dry,
    # Dry only: tasks whose LastRunTime/LastTaskResult must show a finished, successful run
    # tonight before the next unit may start (for example the night's integration attempt tasks).
    [string[]]$GateTaskName = @(),
    # Dry only: evaluate as of this local wall clock (yyyy-MM-ddTHH:mm:ss) instead of now.
    [string]$EvaluatedAt = "",
    # Dry only: receipt path; default data\merge_train_dry\<night>\receipt-<time>.json.
    [string]$ReceiptOut = "",
    # Dry only: "test the train once". When every pending entry is ROLL-FREE, plan ONE bounded
    # suite on the final tip of the stacked chain, then merge each head in order. The receipt
    # records, from the chained per-entry preflight receipts, which intermediate tips would have
    # failed where the final tip passed (the cost of skipping per-head suites).
    [switch]$TrainOnce
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$mergeScript = Join-Path $RepoRoot "scripts\ops\quiet_window_merge.ps1"
$SignatureNamespace = "weather-merge-queue"
$QueueSchema = "weather_exact_tip_merge_queue_v1"
$ReceiptSchema = "weather_merge_train_dry_receipt_v1"
$RollClasses = @("ROLL-FREE", "ROLL-SENSITIVE")
if (-not $SignatureFile) { $SignatureFile = "$QueueFile.sig" }
if (-not $AllowedSignersFile) {
    $AllowedSignersFile = Join-Path $RepoRoot "scripts\ops\merge_queue_allowed_signers"
}
$GateTaskName = @($GateTaskName | ForEach-Object { $_ -split "," } | Where-Object { $_ })
if (-not $Dry -and ($EvaluatedAt -or $ReceiptOut -or $GateTaskName.Count -gt 0 -or $TrainOnce)) {
    throw "-EvaluatedAt, -ReceiptOut, -GateTaskName and -TrainOnce are dry-run parameters"
}

$logParent = Split-Path -Parent ([IO.Path]::GetFullPath($LogFile))
if (-not (Test-Path -LiteralPath $logParent)) {
    New-Item -ItemType Directory -Path $logParent -Force | Out-Null
}
function Note([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Output $line
}

function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-Commit([string]$Ref) {
    $ErrorActionPreference = "Continue"
    $raw = @(& git -C $RepoRoot rev-parse --verify --quiet ("{0}^{{commit}}" -f $Ref) 2>$null)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -eq 0) { return "" }
    return ([string]$raw[-1]).Trim().ToLowerInvariant()
}

function Test-Ancestor([string]$Ancestor, [string]$Descendant) {
    $ErrorActionPreference = "Continue"
    & git -C $RepoRoot merge-base --is-ancestor $Ancestor $Descendant 2>$null
    return ($LASTEXITCODE -eq 0)
}

# The owner signs the exact queue bytes with `ssh-keygen -Y sign -n weather-merge-queue`.
# Verification needs the signature, a key for $SignerIdentity in the committed allowed_signers
# file restricted to this namespace, and byte-identical queue content. Anything else refuses.
function Test-QueueSignature {
    $result = [ordered]@{
        verified = $false; principal = $SignerIdentity; namespace = $SignatureNamespace
        signature_file = $SignatureFile; allowed_signers_file = $AllowedSignersFile
        allowed_signers_sha256 = $null; key_fingerprint = $null; reason = $null
    }
    if (-not (Test-Path -LiteralPath $SignatureFile -PathType Leaf)) {
        $result.reason = "unsigned: no signature file"; return $result
    }
    if (-not (Test-Path -LiteralPath $AllowedSignersFile -PathType Leaf)) {
        $result.reason = "no allowed_signers trust anchor"; return $result
    }
    $result.allowed_signers_sha256 = Get-Sha256 $AllowedSignersFile
    $keygen = $SshKeygenPath
    if (-not $keygen) {
        $found = @(Get-Command ssh-keygen -CommandType Application -ErrorAction SilentlyContinue)
        if ($found.Count -gt 0) { $keygen = $found[0].Source }
    }
    if (-not $keygen -or -not (Test-Path -LiteralPath $keygen -PathType Leaf)) {
        $result.reason = "ssh-keygen unavailable; signature cannot be verified"; return $result
    }
    $scratch = Join-Path ([IO.Path]::GetTempPath()) ("mqsig-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $scratch | Out-Null
    try {
        $out = Join-Path $scratch "out.txt"; $err = Join-Path $scratch "err.txt"
        # The message is passed as a file handle: piping bytes through PowerShell re-encodes them.
        $arguments = @("-Y", "verify", "-f", ('"{0}"' -f $AllowedSignersFile), "-I", $SignerIdentity,
            "-n", $SignatureNamespace, "-s", ('"{0}"' -f $SignatureFile))
        $process = Start-Process -FilePath $keygen -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
            -RedirectStandardInput $QueueFile -RedirectStandardOutput $out -RedirectStandardError $err
        $text = ((@(Get-Content -LiteralPath $out -ErrorAction SilentlyContinue) +
            @(Get-Content -LiteralPath $err -ErrorAction SilentlyContinue)) -join " ").Trim()
        if ($process.ExitCode -eq 0 -and $text -match 'Good "weather-merge-queue" signature') {
            $result.verified = $true
            if ($text -match '(SHA256:[A-Za-z0-9+/=]+)') { $result.key_fingerprint = $Matches[1] }
        }
        else {
            $result.reason = "signature did not verify: $text"
        }
    }
    finally { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }
    return $result
}

# One validator for both modes. A later malformed row must not leave the queue half-applied,
# and a movable ref is never substituted for its reviewed object.
function Get-QueueRefusals($Payload, [string]$QueueDirectory) {
    $refusals = New-Object System.Collections.Generic.List[string]
    if ([string](Get-Field $Payload "schema_version") -ne $QueueSchema) {
        $refusals.Add("unsupported merge queue schema"); return $refusals
    }
    $night = [string](Get-Field $Payload "night")
    $parsedNight = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($night, "yyyy-MM-dd", [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None, [ref]$parsedNight)) {
        $refusals.Add("night must be yyyy-MM-dd")
    }
    if ([string](Get-Field $Payload "base_sha") -notmatch '^[0-9a-f]{40}$') {
        $refusals.Add("base_sha must be a full lowercase SHA")
    }
    if ([string](Get-Field $Payload "plan_sha256") -notmatch '^[0-9a-f]{64}$') {
        $refusals.Add("plan_sha256 must be 64 lowercase hex")
    }
    if ([string](Get-Field $Payload "on_failure") -ne "stop_night") {
        $refusals.Add("on_failure must be stop_night")
    }
    $entries = @(Get-Field $Payload "entries")
    if ($entries.Count -eq 0) { $refusals.Add("queue has no entries") }
    $orders = @()
    foreach ($entry in $entries) {
        $branch = [string](Get-Field $entry "branch")
        $expectedTip = [string](Get-Field $entry "expected_tip")
        $orders += [string](Get-Field $entry "order")
        if (-not [bool](Get-Field $entry "approved")) { $refusals.Add("queue entry is not explicitly approved: $branch"); continue }
        if ($branch -notmatch '^(origin/)?(codex|claude)/[A-Za-z0-9._/-]+$') { $refusals.Add("invalid branch ref in queue: $branch"); continue }
        if ($expectedTip -notmatch '^[0-9a-f]{40}$') { $refusals.Add("expected_tip must be a full lowercase SHA for $branch"); continue }
        if ($RollClasses -notcontains [string](Get-Field $entry "roll_class")) { $refusals.Add("roll_class must be ROLL-FREE or ROLL-SENSITIVE for $branch") }
        if (-not [string](Get-Field $entry "approval_ref")) { $refusals.Add("approval_ref missing for $branch") }
        $resolved = Resolve-Commit $branch
        if ($resolved -ne $expectedTip) { $refusals.Add("exact-tip preflight failed for ${branch}: resolved=$resolved expected=$expectedTip") }
        $receiptSha = [string](Get-Field $entry "preflight_receipt_sha256")
        $receiptRel = [string](Get-Field $entry "preflight_receipt")
        if ($receiptSha -notmatch '^[0-9a-f]{64}$' -or -not $receiptRel -or [IO.Path]::IsPathRooted($receiptRel) -or $receiptRel -match '\.\.') {
            $refusals.Add("preflight receipt binding malformed for $branch"); continue
        }
        $receiptPath = Join-Path $QueueDirectory $receiptRel
        if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { $refusals.Add("preflight receipt missing for $branch"); continue }
        if ((Get-Sha256 $receiptPath) -ne $receiptSha) { $refusals.Add("preflight receipt hash mismatch for $branch"); continue }
        if (-not (Get-Content -LiteralPath $receiptPath -Raw).Contains($expectedTip)) {
            $refusals.Add("preflight receipt does not name the expected tip for $branch")
        }
    }
    $expectedOrders = @(1..([Math]::Max($entries.Count, 1)) | ForEach-Object { [string]$_ })
    if ($entries.Count -gt 0 -and (@($orders) -join ",") -ne ($expectedOrders -join ",")) {
        $refusals.Add("entry order must be 1..n as listed")
    }
    return $refusals
}

function ConvertTo-LocalStamp([datetime]$Value) { return $Value.ToString("yyyy-MM-ddTHH:mm:ss") }

function Get-GateTaskObservation([string]$Name, [datetime]$NightStart) {
    $row = [ordered]@{ name = $Name; state = $null; last_run_time = $null; last_task_result = $null; decision = $null }
    try {
        $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction Stop
    }
    catch { $row.decision = "missing"; return $row }
    $row.state = [string]$task.State
    $lastRun = [datetime](Get-Field $info "LastRunTime")
    $code = [int64](Get-Field $info "LastTaskResult")
    $row.last_run_time = ConvertTo-LocalStamp $lastRun
    $row.last_task_result = ("0x{0:x}" -f $code)
    # A result code is not an outcome by itself (a busy-lease skip also exits 0); the receipt keeps
    # the raw values so the morning comparison can read the task's own status artefact.
    if ($row.state -eq "Running" -or $code -eq 0x41301) { $row.decision = "running" }
    elseif ($lastRun -lt $NightStart -or $code -eq 0x41303) { $row.decision = "not_run_tonight" }
    elseif ($code -ne 0) { $row.decision = "failed" }
    else { $row.decision = "succeeded_tonight" }
    return $row
}

function Get-ReceiptVerdict($Entry) {
    # The preflight receipt was hash-checked by Get-QueueRefusals. Its verdict is either a
    # string or an object with a status (weather.operations.landing_preflight).
    try {
        $path = Join-Path (Split-Path -Parent $QueueFile) ([string]$Entry.preflight_receipt)
        $verdict = Get-Field (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json) "verdict"
        $status = if ($verdict -is [string]) { $verdict } else { [string](Get-Field $verdict "status") }
        if ($status) { return $status.ToUpperInvariant() }
    }
    catch { }
    return "UNKNOWN"
}

function Get-TrainPlan($Payload, $EntriesOut) {
    $pendingOrders = @($EntriesOut | Where-Object { $_.status -ne "merged" } | ForEach-Object { [int]$_.order })
    $pending = @(@($Payload.entries) | Where-Object { $pendingOrders -contains [int]$_.order })
    $plan = [ordered]@{ mode = "TRAIN_ONCE"; eligible = $false; ineligible_reason = $null
        pending_orders = $pendingOrders; final_tip = $null; suites_planned = 0; suites_saved = 0
        receipt_verdicts = @(); intermediate_failures = @(); intermediate_failed_where_final_passed = $false }
    if ($pending.Count -eq 0) { $plan.ineligible_reason = "no pending entries"; return $plan }
    $sensitive = @($pending | Where-Object { [string]$_.roll_class -ne "ROLL-FREE" } | ForEach-Object { [int]$_.order })
    $verdicts = @($pending | ForEach-Object {
        [ordered]@{ order = [int]$_.order; expected_tip = [string]$_.expected_tip; verdict = (Get-ReceiptVerdict $_) } })
    $plan.receipt_verdicts = $verdicts
    $final = $verdicts[$verdicts.Count - 1]
    $plan.final_tip = $final.expected_tip
    $intermediate = @()
    if ($verdicts.Count -gt 1) { $intermediate = @($verdicts[0..($verdicts.Count - 2)]) }
    $plan.intermediate_failures = @($intermediate | Where-Object { $_.verdict -ne "PASS" } | ForEach-Object { [int]$_.order })
    $plan.intermediate_failed_where_final_passed = ($final.verdict -eq "PASS" -and $plan.intermediate_failures.Count -gt 0)
    if ($sensitive.Count -gt 0) {
        $plan.ineligible_reason = "ROLL-SENSITIVE entries: " + ($sensitive -join ",")
    }
    elseif ($final.verdict -ne "PASS") {
        $plan.ineligible_reason = "the final tip's chained preflight is $($final.verdict)"
    }
    else {
        $plan.eligible = $true
        $plan.suites_planned = 1
        $plan.suites_saved = $pending.Count - 1
    }
    return $plan
}

function Invoke-DryEvaluation($Payload, [string]$QueueSha, $Signature, [string[]]$Refusals) {
    $wallClock = Get-Date
    if ($EvaluatedAt) {
        $asOf = [datetime]::ParseExact($EvaluatedAt, "yyyy-MM-ddTHH:mm:ss", [Globalization.CultureInfo]::InvariantCulture)
    }
    else { $asOf = $wallClock }
    # The night is the 00:30-09:00 window of a calendar date; evaluations after noon are for tomorrow.
    $nightDate = if ($asOf.Hour -lt 12) { $asOf.Date } else { $asOf.Date.AddDays(1) }
    $nightStart = $nightDate.AddMinutes(30)
    $refusalList = New-Object System.Collections.Generic.List[string]
    foreach ($item in $Refusals) { $refusalList.Add($item) }
    $master = Resolve-Commit "master"
    $originMaster = Resolve-Commit "origin/master"
    $entriesOut = @()
    $next = $null
    if ($Signature.verified -and $refusalList.Count -eq 0) {
        if ([string]$Payload.night -ne $nightDate.ToString("yyyy-MM-dd")) {
            $refusalList.Add("queue is for night $($Payload.night), evaluation night is $($nightDate.ToString('yyyy-MM-dd'))")
        }
        $merged = 0
        foreach ($entry in @($Payload.entries)) {
            $isMerged = $master -and (Test-Ancestor ([string]$entry.expected_tip) $master)
            if ($isMerged) { $merged += 1 }
            $status = if ($isMerged) { "merged" } elseif ($null -eq $next) { "next" } else { "pending" }
            if ($status -eq "next") { $next = $entry }
            $entriesOut += [ordered]@{ order = [int]$entry.order; branch = [string]$entry.branch
                expected_tip = [string]$entry.expected_tip; roll_class = [string]$entry.roll_class
                approval_ref = [string]$entry.approval_ref; status = $status }
        }
        $base = [string]$Payload.base_sha
        if (-not $master -or -not (Test-Ancestor $base $master)) {
            $refusalList.Add("master does not contain the signed base_sha")
        }
        elseif ($master -ne $base -and $merged -eq 0) {
            $refusalList.Add("master moved since signing and no queue entry explains it")
        }
    }
    $train = $null
    if ($TrainOnce -and $Signature.verified -and $refusalList.Count -eq 0) { $train = Get-TrainPlan $Payload $entriesOut }
    $lease = [ordered]@{ active = $null; workload = $null; pid = $null }
    $gates = @()
    $blockedBy = New-Object System.Collections.Generic.List[string]
    $verdict = $null
    $wouldRun = $null
    if (-not $Signature.verified) { $verdict = "REFUSED_UNSIGNED" }
    elseif ($refusalList.Count -gt 0) { $verdict = "REFUSED" }
    elseif ($null -eq $next) { $verdict = "DONE" }
    else {
        . (Join-Path $RepoRoot "scripts\ops\workload_admission.ps1")
        $leaseState = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $RepoRoot
        $lease.active = [bool]$leaseState.Active
        $owner = Get-Field $leaseState "Owner"
        $lease.workload = [string](Get-Field $owner "workload")
        $lease.pid = Get-Field $owner "pid"
        if ($lease.active) { $blockedBy.Add("lease_held:$($lease.workload)") }
        foreach ($name in $GateTaskName) {
            $row = Get-GateTaskObservation $name $nightStart
            $gates += $row
            if ($row.decision -ne "succeeded_tonight") { $blockedBy.Add("gate_task_$($row.decision):$name") }
        }
        $suiteAt = if ($asOf -lt $nightStart) { $nightStart } else { $asOf }
        $mergeAt = $suiteAt.AddMinutes(30)
        if ($mergeAt -lt $nightDate.AddHours(1)) { $mergeAt = $nightDate.AddHours(1) }
        if (@($gates | Where-Object { $_.decision -eq "failed" -or $_.decision -eq "missing" }).Count -gt 0) {
            $verdict = "STOP_FOR_NIGHT"
        }
        elseif ($mergeAt -gt $nightDate.AddHours(3).AddMinutes(40)) {
            $verdict = "STOP_FOR_NIGHT"; $blockedBy.Add("merge_window_exhausted")
        }
        elseif ($blockedBy.Count -gt 0) { $verdict = "WAIT" }
        else {
            $verdict = "WOULD_RUN"
            $wouldRun = [ordered]@{
                order = [int]$next.order; branch = [string]$next.branch; expected_tip = [string]$next.expected_tip
                roll_class = [string]$next.roll_class
                attempt_id = ("train-{0}-{1}-{2}" -f $nightDate.ToString("yyyyMMdd"), $next.order, ([string]$next.expected_tip).Substring(0, 8))
                suite_at_local = ConvertTo-LocalStamp $suiteAt; merge_at_local = ConvertTo-LocalStamp $mergeAt
                summary = ("would have run {0} at {1} (merge {2})" -f $next.branch, (ConvertTo-LocalStamp $suiteAt), (ConvertTo-LocalStamp $mergeAt))
            }
            if ($train -and $train.eligible) {
                $wouldRun.train_once = $true
                $wouldRun.suite_tip = [ordered]@{ kind = "synthetic_chain"; base = $master; orders = $train.pending_orders
                    final_tip = $train.final_tip }
                $wouldRun.merge_orders = $train.pending_orders
                $wouldRun.summary = ("would have run ONE bounded suite on the final tip of {0} heads at {1}, then merged orders {2} in sequence from {3}" -f
                    $train.pending_orders.Count, (ConvertTo-LocalStamp $suiteAt), ($train.pending_orders -join ","), (ConvertTo-LocalStamp $mergeAt))
            }
        }
    }
    $receipt = [ordered]@{
        schema_version = $ReceiptSchema; mode = "DRY"; verdict = $verdict
        evaluated_at = ConvertTo-LocalStamp $asOf; generated_at = ConvertTo-LocalStamp $wallClock
        night = $nightDate.ToString("yyyy-MM-dd"); queue_file = [IO.Path]::GetFullPath($QueueFile)
        queue_sha256 = $QueueSha; plan_sha256 = [string](Get-Field $Payload "plan_sha256")
        base_sha = [string](Get-Field $Payload "base_sha"); master_sha = $master; origin_master_sha = $originMaster
        signature = $Signature; refusals = @($refusalList); entries = @($entriesOut)
        lease = $lease; gate_tasks = @($gates); blocked_by = @($blockedBy); would_run = $wouldRun; train = $train
        driver_sha256 = Get-Sha256 $PSCommandPath
        mutations = "NONE: dry mode takes no lease, registers no task, merges, fetches and pushes nothing"
    }
    if (-not $ReceiptOut) {
        $ReceiptOut = Join-Path $RepoRoot ("data\merge_train_dry\{0}\receipt-{1}.json" -f $receipt.night, $wallClock.ToString("yyyyMMddTHHmmss"))
    }
    $receiptParent = Split-Path -Parent ([IO.Path]::GetFullPath($ReceiptOut))
    if (-not (Test-Path -LiteralPath $receiptParent)) { New-Item -ItemType Directory -Path $receiptParent -Force | Out-Null }
    [IO.File]::WriteAllText([IO.Path]::GetFullPath($ReceiptOut), ($receipt | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    Note ("DRY verdict {0}; receipt {1}" -f $verdict, $ReceiptOut)
    if ($wouldRun) { Note $wouldRun.summary }
    if ($train) {
        $masked = if ($train.intermediate_failed_where_final_passed) { $train.intermediate_failures.Count } else { 0 }
        $reason = if ($train.ineligible_reason) { " ($($train.ineligible_reason))" } else { "" }
        Note ("train: eligible={0}{1}; intermediate tips failing where the final passed: {2} of {3}" -f
            $train.eligible, $reason, $masked, [Math]::Max($train.pending_orders.Count - 1, 0))
    }
    foreach ($item in $refusalList) { Note "refused: $item" }
    if ($Signature.reason) { Note "signature: $($Signature.reason)" }
    if ($verdict -like "REFUSED*") { exit 4 }
    exit 0
}

Note ("=== exact-tip merge queue starting{0} ===" -f $(if ($Dry) { " (DRY)" } else { "" }))
if (-not (Test-Path -LiteralPath $QueueFile -PathType Leaf)) {
    Note "queue absent; no work"
    exit 0
}
$QueueFile = (Resolve-Path -LiteralPath $QueueFile).Path
$queueSha = Get-Sha256 $QueueFile
$signature = Test-QueueSignature
$payload = $null
$refusals = @()
try { $payload = Get-Content -LiteralPath $QueueFile -Raw | ConvertFrom-Json }
catch { $refusals = @("queue is not valid JSON") }
if ($null -ne $payload -and $signature.verified) {
    $refusals = @(Get-QueueRefusals $payload (Split-Path -Parent $QueueFile))
}
if ($Dry) { Invoke-DryEvaluation $payload $queueSha $signature $refusals }

if (-not $signature.verified) { throw "merge queue refused: $($signature.reason)" }
if ($refusals.Count -gt 0) { throw ("merge queue refused: " + ($refusals -join "; ")) }
$entries = @($payload.entries)
foreach ($entry in $entries) {
    # Retained invariant of the reviewed v1 driver, now enforced by Get-QueueRefusals as well.
    if (-not [bool]$entry.approved) { throw "queue entry is not explicitly approved: $($entry.branch)" }
}

# Validate every entry before allowing the first merge (Get-QueueRefusals above), then merge in order.
foreach ($entry in $entries) {
    $branch = [string]$entry.branch
    $expectedTip = ([string]$entry.expected_tip).ToLowerInvariant()
    & git -C $RepoRoot merge-base --is-ancestor $expectedTip master
    if ($LASTEXITCODE -eq 0) {
        Note "already merged: $branch at $expectedTip"
        continue
    }
    Note "merging reviewed entry: $branch at $expectedTip"
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $mergeScript -Branch $branch -ExpectedTip $expectedTip
    if ($LASTEXITCODE -ne 0) {
        throw "guarded merge failed for $branch with exit $LASTEXITCODE; later entries were not attempted"
    }
}
Note "=== exact-tip merge queue finished ==="
