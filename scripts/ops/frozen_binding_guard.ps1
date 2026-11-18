# Frozen-binding guard (ruling R14, master 2026-11-01). Dot-source it; it defines one function:
#
#   . (Join-Path $PSScriptRoot "frozen_binding_guard.ps1")
#   $r = Test-FrozenBindingHead -Repo <repo root> -Base <merge target sha> -Tip <head tip sha>
#   if (-not $r.Ok) { <refuse the head: $r.Refusals> }
#
# It judges the three-dot diff Base...Tip against config/frozen_bindings.json AS IT IS AT $Base
# (a head cannot loosen the registry it is judged by). No registry at $Base means no holds; a
# malformed one refuses. A hold is active while its release_record is absent at $Base.
#
# Refused: any change to a record, or a modify/delete of a file matching a record glob (adding a
# new b1-clarification-*.md passes outside the S1 head); any change under a frozen prefix; a
# modify/delete of a present release record; an added release record whose fields fail (below);
# while active, any change to a code pin or a release-binding file except the S1 edit; a registry
# change that is not a pure addition.
#
# The S1 edit (B-1 Clarification 3 section 5; master's R14 rulings 2026-11-01, strict): one head
# changes every s1_edit file of the hold, each in exactly its constant line, from the S0 line to a
# quoted 64-hex value, all values equal. Besides those files it may add at most ONE new file, and
# only one matching the hold's s1_companion_glob (B-1: docs/research/**/b1-clarification-7-*.md);
# any other path, any other clarification number, a second new file or a modify is refused. Its
# paths are returned in SuiteChecked: line endings and the b_scorer_entry_edit verdict are
# re-checked by tests/operations/test_frozen_bindings.py, so a head with SuiteChecked paths must
# be suite-gated.
#
# The release record (master's R14 ruling 2026-11-01) is checked when a head adds it while the hold
# is active. Fields are key: value lines. A look record has rule_sha256 equal to the hold's
# record_rule_sha256, receipt_path (a repo-relative path committed at the tip and made non-text by a
# .gitattributes line at the tip: exact path with -text or binary, not set to text by any later line),
# receipt_sha256 equal to the sha256 of that blob's exact bytes, and decision_log_row (a YYYY-MM-DD with a DECISION_LOG
# row at the tip). An abandonment record has b_abandonment and decision_log_row, and a DECISION_LOG
# row of that date must name an owner abandonment: it contains the word "owner" and "abandon", and
# not "not an owner decision" (case-insensitive).
#
# Warnings (never a refusal): changes to a hold's warn paths. The function never writes anything.

$script:FrozenBindingRegistryPath = "config/frozen_bindings.json"
$script:FrozenBindingDecisionLog = "docs/operations/DECISION_LOG.md"
$script:FrozenBindingRecordKeys = @("rule_sha256", "receipt_path", "receipt_sha256", "decision_log_row", "b_abandonment")

function Get-FrozenBindingProperty($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    # -NoEnumerate: a one-element JSON array must stay an array.
    Write-Output -NoEnumerate $property.Value
}

function Invoke-FrozenBindingGit([string]$Repo, [string[]]$Arguments) {
    # Lines are kept exactly (no trim, empty lines kept); native stderr cannot terminate under Stop.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& git -C $Repo -c core.quotepath=off @Arguments 2>$null | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    return [pscustomobject]@{ code = $code; lines = $out }
}

function Test-FrozenBindingBlob([string]$Repo, [string]$Commit, [string]$Path) {
    return ((Invoke-FrozenBindingGit $Repo @("cat-file", "-e", "${Commit}:$Path")).code -eq 0)
}

function Get-FrozenBindingBlobLines([string]$Repo, [string]$Commit, [string]$Path) {
    $r = Invoke-FrozenBindingGit $Repo @("show", "${Commit}:$Path")
    if ($r.code -ne 0) { throw "git show ${Commit}:$Path failed (exit $($r.code))" }
    return , @($r.lines)
}

function Get-FrozenBindingBlobSha256([string]$Repo, [string]$Commit, [string]$Path) {
    # sha256 of the blob's exact bytes (cat-file applies no text conversion); $null if absent.
    if (-not (Test-FrozenBindingBlob $Repo $Commit $Path)) { return $null }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "git"
    $psi.Arguments = '-C "{0}" cat-file blob "{1}:{2}"' -f $Repo.TrimEnd('\'), $Commit, $Path
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::Start($psi)
    $stderr = $process.StandardError.ReadToEndAsync()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash($process.StandardOutput.BaseStream) }
    finally { $sha.Dispose() }
    $process.WaitForExit()
    [void]$stderr.Result
    if ($process.ExitCode -ne 0) { return $null }
    return (-join ($hash | ForEach-Object { $_.ToString("x2") }))
}

function Test-FrozenBindingReceiptByteExact([string]$Repo, [string]$Tip, [string]$Path) {
    # Exact path only: a .gitattributes line (at the tip) whose pattern is $Path or /$Path with -text or binary,
    # and no later line, any pattern, that sets text again (text, text=..., !text). Fail-closed: put it last.
    if (-not (Test-FrozenBindingBlob $Repo $Tip ".gitattributes")) { return $false }
    $exact = $false
    foreach ($line in (Get-FrozenBindingBlobLines $Repo $Tip ".gitattributes")) {
        $tokens = @($line.Trim() -split '\s+' | Where-Object { $_ })
        if ($tokens.Count -eq 0 -or $tokens[0].StartsWith("#") -or $tokens[0].StartsWith("[attr]")) { continue }
        $attributes = @($tokens | Select-Object -Skip 1)
        $setsText = @($attributes | Where-Object { $_ -ceq "text" -or $_.StartsWith("text=") -or $_ -ceq "!text" }).Count -gt 0
        if (($tokens[0] -ceq $Path -or $tokens[0] -ceq "/$Path") -and
            ($attributes -ccontains "-text" -or $attributes -ccontains "binary") -and -not $setsText) { $exact = $true }
        elseif ($setsText) { $exact = $false }
    }
    return $exact
}

function Get-FrozenBindingRecordProblems([string]$Repo, [string]$Tip, $Hold, [string]$RecordPath) {
    $problems = New-Object System.Collections.Generic.List[string]
    $fields = @{}
    foreach ($line in (Get-FrozenBindingBlobLines $Repo $Tip $RecordPath)) {
        $m = [regex]::Match($line.TrimEnd("`r"), '^(?<key>[a-z0-9_]+):[ \t]*(?<value>\S.*?)[ \t]*$')
        if (-not $m.Success -or $script:FrozenBindingRecordKeys -cnotcontains $m.Groups["key"].Value) { continue }
        $key = $m.Groups["key"].Value
        if ($fields.ContainsKey($key)) { $problems.Add("release record field $key appears more than once") }
        $fields[$key] = $m.Groups["value"].Value
    }
    $row = [string]$fields["decision_log_row"]
    $rows = @()
    if ($row -cmatch '^\d{4}-\d{2}-\d{2}$' -and (Test-FrozenBindingBlob $Repo $Tip $script:FrozenBindingDecisionLog)) {
        $rows = @((Get-FrozenBindingBlobLines $Repo $Tip $script:FrozenBindingDecisionLog) |
                Where-Object { $_.StartsWith("| $row |", [StringComparison]::Ordinal) })
    }
    if ($rows.Count -eq 0) { $problems.Add("release record decision_log_row '$row' names no DECISION_LOG row") }
    if ($fields.ContainsKey("b_abandonment")) {
        $owner = @($rows | Where-Object {
                $_ -match '(?i)\bowner\b' -and $_ -match '(?i)abandon' -and $_ -notmatch '(?i)not an owner decision' })
        if ($rows.Count -gt 0 -and $owner.Count -eq 0) {
            $problems.Add("release record b_abandonment: no DECISION_LOG row of $row names an owner abandonment")
        }
        return , $problems
    }
    $rule = [string](Get-FrozenBindingProperty $Hold "record_rule_sha256")
    if (-not $rule -or [string]$fields["rule_sha256"] -cne $rule) {
        $problems.Add("release record rule_sha256 '$($fields["rule_sha256"])' is not B's rule sha '$rule'")
    }
    $receiptPath = [string]$fields["receipt_path"]
    $receiptSha = [string]$fields["receipt_sha256"]
    if ($receiptSha -cnotmatch '^[0-9a-f]{64}$') {
        $problems.Add("release record receipt_sha256 '$receiptSha' is not 64 lowercase hex")
    }
    $segments = @($receiptPath -split '/')
    if ($receiptPath -cnotmatch '^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$' -or $segments -contains '.' -or $segments -contains '..') {
        $problems.Add("release record receipt_path '$receiptPath' is not a repo-relative path")
    }
    else {
        $actual = Get-FrozenBindingBlobSha256 $Repo $Tip $receiptPath
        if ($null -eq $actual) { $problems.Add("release record receipt_path $receiptPath is not committed at the tip") }
        elseif (-not (Test-FrozenBindingReceiptByteExact $Repo $Tip $receiptPath)) {
            # Checked before the sha: a normalised blob must not read as a bare sha mismatch.
            $problems.Add("receipt must be committed byte-exact: add '$receiptPath -text' to .gitattributes in the same head")
        }
        elseif ($actual -cne $receiptSha) {
            $problems.Add("release record receipt_sha256 is not the sha256 of the bytes of $receiptPath ($actual)")
        }
    }
    return , $problems
}

function ConvertTo-FrozenBindingGlobRegex([string]$Glob) {
    # '**/' spans zero or more directories; '*' stays inside one path segment.
    $pattern = [regex]::Escape($Glob) -replace '\\\*\\\*/', '(?:.+/)?' -replace '\\\*', '[^/]*'
    return "^$pattern$"
}

function Test-FrozenBindingJsonContained($Old, $New) {
    # True when $New keeps every value of $Old: objects keep every key, arrays keep $Old as a prefix.
    if ($null -eq $Old) { return ($null -eq $New) }
    if ($Old -is [System.Management.Automation.PSCustomObject]) {
        if ($New -isnot [System.Management.Automation.PSCustomObject]) { return $false }
        foreach ($p in $Old.PSObject.Properties) {
            $match = $New.PSObject.Properties[$p.Name]
            if ($null -eq $match -or -not (Test-FrozenBindingJsonContained $p.Value $match.Value)) { return $false }
        }
        return $true
    }
    if ($Old -is [System.Array]) {
        if ($New -isnot [System.Array] -or $New.Count -lt $Old.Count) { return $false }
        for ($i = 0; $i -lt $Old.Count; $i++) {
            if (-not (Test-FrozenBindingJsonContained $Old[$i] $New[$i])) { return $false }
        }
        return $true
    }
    if ($New -is [System.Management.Automation.PSCustomObject] -or $New -is [System.Array]) { return $false }
    return ([string]$Old -ceq [string]$New -and $Old.GetType() -eq $New.GetType())
}

function Read-FrozenBindingRegistry([string]$Repo, [string]$Commit) {
    # $null: no registry at $Commit. Throws on a malformed registry.
    if (-not (Test-FrozenBindingBlob $Repo $Commit $script:FrozenBindingRegistryPath)) { return $null }
    $text = (Get-FrozenBindingBlobLines $Repo $Commit $script:FrozenBindingRegistryPath) -join "`n"
    try { $registry = $text | ConvertFrom-Json }
    catch { throw "registry $($script:FrozenBindingRegistryPath) at $Commit is not JSON" }
    if ((Get-FrozenBindingProperty $registry "schema") -cne "frozen_bindings/1") {
        throw "registry $($script:FrozenBindingRegistryPath) at $Commit has no schema frozen_bindings/1"
    }
    $holds = Get-FrozenBindingProperty $registry "holds"
    if ($null -eq $holds -or $holds -isnot [System.Array] -or $holds.Count -eq 0) {
        throw "registry $($script:FrozenBindingRegistryPath) at $Commit has no holds list"
    }
    foreach ($hold in $holds) {
        if (-not (Get-FrozenBindingProperty $hold "id") -or -not (Get-FrozenBindingProperty $hold "release_record")) {
            throw "registry $($script:FrozenBindingRegistryPath) at $Commit has a hold without id or release_record"
        }
    }
    return $registry
}

function Test-FrozenBindingHead {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Repo,
        [Parameter(Mandatory = $true)][string]$Base,
        [Parameter(Mandatory = $true)][string]$Tip
    )
    $result = [pscustomobject]@{
        Ok = $false
        Refusals = New-Object System.Collections.Generic.List[string]
        Warnings = New-Object System.Collections.Generic.List[string]
        SuiteChecked = New-Object System.Collections.Generic.List[string]
        ActiveHolds = New-Object System.Collections.Generic.List[string]
        RegistryPresent = $false
    }
    foreach ($ref in @($Base, $Tip)) {
        if ((Invoke-FrozenBindingGit $Repo @("rev-parse", "-q", "--verify", "$ref^{commit}")).code -ne 0) {
            $result.Refusals.Add("frozen-binding guard: $ref is not a commit")
            return $result
        }
    }
    try { $registry = Read-FrozenBindingRegistry $Repo $Base }
    catch {
        $result.Refusals.Add("frozen-binding guard: $($_.Exception.Message)")
        return $result
    }
    $diff = Invoke-FrozenBindingGit $Repo @("diff", "--no-renames", "--name-status", "$Base...$Tip")
    if ($diff.code -ne 0) {
        $result.Refusals.Add("frozen-binding guard: git diff $Base...$Tip failed (exit $($diff.code))")
        return $result
    }
    $changes = @($diff.lines | Where-Object { $_ } | ForEach-Object {
            $parts = $_ -split "`t", 2
            [pscustomobject]@{ status = $parts[0].Substring(0, 1); path = $parts[1] }
        })

    # The registry itself: a pure addition only (judged against its $Base copy).
    $registryChange = @($changes | Where-Object { $_.path -ceq $script:FrozenBindingRegistryPath })
    if ($registryChange.Count -gt 0) {
        if ($registryChange[0].status -eq "D") {
            $result.Refusals.Add("$($script:FrozenBindingRegistryPath) is deleted")
        }
        else {
            try {
                $tipRegistry = Read-FrozenBindingRegistry $Repo $Tip
                if ($null -ne $registry -and -not (Test-FrozenBindingJsonContained $registry $tipRegistry)) {
                    $result.Refusals.Add("$($script:FrozenBindingRegistryPath) changes other than by pure additions")
                }
            }
            catch { $result.Refusals.Add("the tip's $($script:FrozenBindingRegistryPath) is malformed: $($_.Exception.Message)") }
        }
    }
    if ($null -eq $registry) {
        $result.Ok = ($result.Refusals.Count -eq 0)
        return $result
    }
    $result.RegistryPresent = $true

    foreach ($hold in @($registry.holds)) {
        $id = [string]$hold.id
        $releaseRecord = [string]$hold.release_record
        $active = -not (Test-FrozenBindingBlob $Repo $Base $releaseRecord)
        if ($active) { $result.ActiveHolds.Add($id) }
        $records = Get-FrozenBindingProperty $hold "records"
        $recordPaths = @(if ($records) { $records.PSObject.Properties | ForEach-Object { $_.Name } })
        $globs = @((Get-FrozenBindingProperty $hold "record_globs") | Where-Object { $_ } |
                ForEach-Object { ConvertTo-FrozenBindingGlobRegex ([string]$_) })
        $prefixes = @((Get-FrozenBindingProperty $hold "frozen_prefixes") | Where-Object { $_ })
        $warn = @((Get-FrozenBindingProperty $hold "warn") | Where-Object { $_ })
        $code = Get-FrozenBindingProperty $hold "code"
        $codePaths = @(if ($code) { $code.PSObject.Properties | ForEach-Object { $_.Name } })
        $s1Edit = Get-FrozenBindingProperty $hold "s1_edit"
        $s1Paths = @(if ($s1Edit) { $s1Edit.PSObject.Properties | ForEach-Object { $_.Name } })
        $releasePaths = @()
        $releaseBinding = [string](Get-FrozenBindingProperty $hold "release_binding")
        if ($active -and $releaseBinding) {
            try {
                $binding = (Get-FrozenBindingBlobLines $Repo $Base $releaseBinding) -join "`n" | ConvertFrom-Json
                $releasePaths = @($binding.files.PSObject.Properties | ForEach-Object { $_.Name })
            }
            catch { $result.Refusals.Add("${id}: release binding $releaseBinding at $Base is unreadable") }
        }

        $s1Changed = New-Object System.Collections.Generic.List[string]
        foreach ($change in $changes) {
            $path = $change.path
            $status = $change.status
            $isGlobRecord = @($globs | Where-Object { $path -cmatch $_ }).Count -gt 0
            if ($recordPaths -ccontains $path) {
                $result.Refusals.Add("${id}: record $path is changed ($status)")
            }
            elseif ($isGlobRecord -and $status -ne "A") {
                $result.Refusals.Add("${id}: record $path is changed ($status); only new clarifications may be added")
            }
            foreach ($prefix in $prefixes) {
                if ($path.StartsWith([string]$prefix, [StringComparison]::Ordinal)) {
                    $result.Refusals.Add("${id}: $path is under the frozen prefix $prefix ($status)")
                }
            }
            if (-not $active -and $path -ceq $releaseRecord -and $status -ne "A") {
                $result.Refusals.Add("${id}: the release record $path is changed ($status)")
            }
            if ($active -and $path -ceq $releaseRecord -and $status -eq "A") {
                foreach ($problem in (Get-FrozenBindingRecordProblems $Repo $Tip $hold $releaseRecord)) {
                    $result.Refusals.Add("${id}: $problem")
                }
            }
            if ($warn -ccontains $path) { $result.Warnings.Add("${id}: warn path $path is changed ($status)") }
            if (-not $active) { continue }
            if ($s1Paths -ccontains $path) {
                if ($status -eq "M") { $s1Changed.Add($path) }
                else { $result.Refusals.Add("${id}: S1-edit file $path is changed ($status), not modified") }
            }
            elseif ($codePaths -ccontains $path) {
                $result.Refusals.Add("${id}: code pin $path is changed ($status) while $releaseRecord is absent")
            }
            elseif ($releasePaths -ccontains $path) {
                $result.Refusals.Add("${id}: release file $path is changed ($status) while $releaseRecord is absent")
            }
        }

        if ($s1Changed.Count -eq 0) { continue }
        # ---- the S1 edit (B-1 Clarification 3 section 5) ----
        foreach ($path in $s1Paths) {
            if (-not ($s1Changed -ccontains $path)) { $result.Refusals.Add("${id}: the S1 edit must also change $path") }
        }
        $companionGlob = [string](Get-FrozenBindingProperty $hold "s1_companion_glob")
        $companion = if ($companionGlob) { ConvertTo-FrozenBindingGlobRegex $companionGlob } else { $null }
        $companions = New-Object System.Collections.Generic.List[string]
        foreach ($change in $changes) {
            if ($s1Paths -ccontains $change.path) { continue }
            if ($companion -and $change.status -eq "A" -and $change.path -cmatch $companion) { $companions.Add($change.path) }
            else {
                $result.Refusals.Add(("${id}: the S1 head touches another path: $($change.path) ($($change.status)); " +
                        "it may only add one new file matching '$companionGlob'"))
            }
        }
        if ($companions.Count -gt 1) {
            $result.Refusals.Add("${id}: the S1 head adds $($companions.Count) files matching '$companionGlob'; at most one")
        }
        $values = New-Object System.Collections.Generic.List[string]
        foreach ($path in $s1Changed) {
            $spec = $s1Edit.PSObject.Properties[$path].Value
            $constant = [string]$spec.constant
            $s0Line = [string]$spec.s0_line
            $old = Get-FrozenBindingBlobLines $Repo $Base $path
            $new = Get-FrozenBindingBlobLines $Repo $Tip $path
            if ($old.Count -ne $new.Count) {
                $result.Refusals.Add("${id}: S1 edit of $path changes the line count ($($old.Count) to $($new.Count))")
                continue
            }
            $changed = @(for ($i = 0; $i -lt $old.Count; $i++) { if ($old[$i] -cne $new[$i]) { $i } })
            if ($changed.Count -ne 1) {
                $result.Refusals.Add("${id}: S1 edit of $path changes $($changed.Count) lines, not the one $constant line")
                continue
            }
            $line = $changed[0]
            $valuePattern = '^' + [regex]::Escape($constant) + ' = "(?<sha>[0-9a-f]{64})"$'
            $m = [regex]::Match($new[$line], $valuePattern)
            if ($old[$line] -cne $s0Line) {
                $result.Refusals.Add("${id}: S1 edit of $path changes line $($line + 1), which is not the S0 line '$s0Line'")
            }
            elseif (-not $m.Success) {
                $result.Refusals.Add("${id}: S1 edit of $path does not set $constant to a quoted 64-hex value")
            }
            else {
                $values.Add($m.Groups["sha"].Value)
                $result.SuiteChecked.Add($path)
            }
        }
        if (@($values | Sort-Object -Unique).Count -gt 1) {
            $result.Refusals.Add("${id}: the S1 edit sets unequal values: $($values -join ', ')")
        }
    }
    $result.Ok = ($result.Refusals.Count -eq 0)
    return $result
}
