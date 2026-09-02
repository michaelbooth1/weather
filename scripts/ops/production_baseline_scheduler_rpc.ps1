# Fixed-scope ScheduledTasks RPC helper for the one-time production baseline
# reconciliation. The owning parent must run this script in a kill-on-close
# Windows Job and enforce a shorter wall-clock deadline than the request.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "ReadExecutionTapeTask",
        "ReadPushSnapshot",
        "StartPush",
        "StopPush"
    )]
    [string]$Operation,

    [Parameter(Mandatory = $true)]
    [string]$RequestBase64,

    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$script:RequestSchema = "production_baseline_scheduler_rpc_request_v0.1"
$script:ResultSchema = "production_baseline_scheduler_rpc_result_v0.1"
$script:MutationClaimSchema =
    "production_baseline_scheduler_rpc_mutation_claim_v0.1"
$script:MarkerSchema = "quiet_window_merge_in_progress_v0.1"
$script:ReconciliationMode = "production_baseline_reconciliation_v0.1"
$script:PushTaskName = "WeatherOneShotPush"
$script:ExecutionTapeTaskName = "WeatherExecutionTapeSupervisor"
$script:FixedTaskPath = "\"
$script:ReviewedPushTaskXmlSha256 =
    "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
$script:ExpectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
$script:ExpectedPushUserId = "micha"
$script:ExpectedPushLogPath = "C:\Users\micha\ops\logs\push-oneshot.log"
$script:MaximumRequestBytes = 16384
$script:MaximumRequestBase64Characters = 24576
$script:MaximumResultBytes = 131072
$script:MaximumTaskXmlBytes = 65536
$script:MaximumMarkerBytes = 262144
$script:MaximumFutureDeadlineMinutes = 20
$script:MutationAuthorityClaimed = $false

# ConvertFrom-Json on Windows PowerShell accepts duplicate keys. Validate the
# complete JSON grammar first and reject duplicate keys case-insensitively so
# subsequent PowerShell property lookup cannot reinterpret the request.
if (-not ("Weather.Operations.StrictJsonObjectKeyValidator" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Weather.Operations
{
    public sealed class StrictJsonObjectKeyValidator
    {
        private readonly string text;
        private int index;
        private int depth;

        private StrictJsonObjectKeyValidator(string value)
        {
            if (value == null)
            {
                throw new ArgumentNullException("value");
            }
            text = value;
        }

        public static void Validate(string value)
        {
            StrictJsonObjectKeyValidator parser =
                new StrictJsonObjectKeyValidator(value);
            parser.SkipWhitespace();
            parser.ParseValue();
            parser.SkipWhitespace();
            if (parser.index != parser.text.Length)
            {
                throw new FormatException("trailing content after JSON value");
            }
        }

        private void ParseValue()
        {
            if (index >= text.Length)
            {
                throw new FormatException("unexpected end of JSON");
            }
            if (depth >= 32)
            {
                throw new FormatException("JSON nesting exceeds the fixed bound");
            }
            depth++;
            try
            {
                char c = text[index];
                if (c == '{') { ParseObject(); return; }
                if (c == '[') { ParseArray(); return; }
                if (c == '"') { ParseString(); return; }
                if (c == 't') { ParseLiteral("true"); return; }
                if (c == 'f') { ParseLiteral("false"); return; }
                if (c == 'n') { ParseLiteral("null"); return; }
                if (c == '-' || (c >= '0' && c <= '9'))
                {
                    ParseNumber();
                    return;
                }
                throw new FormatException("invalid JSON value");
            }
            finally { depth--; }
        }

        private void ParseObject()
        {
            Expect('{');
            SkipWhitespace();
            if (TryConsume('}')) { return; }
            HashSet<string> keys = new HashSet<string>(
                StringComparer.OrdinalIgnoreCase
            );
            while (true)
            {
                SkipWhitespace();
                string key = ParseString();
                if (!keys.Add(key))
                {
                    throw new FormatException("duplicate JSON property");
                }
                SkipWhitespace();
                Expect(':');
                SkipWhitespace();
                ParseValue();
                SkipWhitespace();
                if (TryConsume('}')) { return; }
                Expect(',');
            }
        }

        private void ParseArray()
        {
            Expect('[');
            SkipWhitespace();
            if (TryConsume(']')) { return; }
            while (true)
            {
                ParseValue();
                SkipWhitespace();
                if (TryConsume(']')) { return; }
                Expect(',');
                SkipWhitespace();
            }
        }

        private string ParseString()
        {
            Expect('"');
            StringBuilder value = new StringBuilder();
            while (index < text.Length)
            {
                char c = text[index++];
                if (c == '"') { return value.ToString(); }
                if (c < 0x20)
                {
                    throw new FormatException("control character in JSON string");
                }
                if (c != '\\')
                {
                    value.Append(c);
                    continue;
                }
                if (index >= text.Length)
                {
                    throw new FormatException("unterminated JSON escape");
                }
                char escaped = text[index++];
                switch (escaped)
                {
                    case '"': value.Append('"'); break;
                    case '\\': value.Append('\\'); break;
                    case '/': value.Append('/'); break;
                    case 'b': value.Append('\b'); break;
                    case 'f': value.Append('\f'); break;
                    case 'n': value.Append('\n'); break;
                    case 'r': value.Append('\r'); break;
                    case 't': value.Append('\t'); break;
                    case 'u':
                        if (index + 4 > text.Length)
                        {
                            throw new FormatException("short JSON unicode escape");
                        }
                        string hex = text.Substring(index, 4);
                        int code;
                        if (!Int32.TryParse(
                            hex,
                            NumberStyles.AllowHexSpecifier,
                            CultureInfo.InvariantCulture,
                            out code
                        ))
                        {
                            throw new FormatException("invalid JSON unicode escape");
                        }
                        value.Append((char)code);
                        index += 4;
                        break;
                    default:
                        throw new FormatException("invalid JSON escape");
                }
            }
            throw new FormatException("unterminated JSON string");
        }

        private void ParseNumber()
        {
            if (TryConsume('-') && index >= text.Length)
            {
                throw new FormatException("incomplete JSON number");
            }
            if (TryConsume('0'))
            {
                if (index < text.Length && Char.IsDigit(text[index]))
                {
                    throw new FormatException("leading zero in JSON number");
                }
            }
            else
            {
                int start = index;
                while (index < text.Length && Char.IsDigit(text[index]))
                {
                    index++;
                }
                if (index == start)
                {
                    throw new FormatException("invalid JSON number");
                }
            }
            if (TryConsume('.'))
            {
                int start = index;
                while (index < text.Length && Char.IsDigit(text[index]))
                {
                    index++;
                }
                if (index == start)
                {
                    throw new FormatException("invalid JSON fraction");
                }
            }
            if (index < text.Length &&
                (text[index] == 'e' || text[index] == 'E'))
            {
                index++;
                if (index < text.Length &&
                    (text[index] == '+' || text[index] == '-'))
                {
                    index++;
                }
                int start = index;
                while (index < text.Length && Char.IsDigit(text[index]))
                {
                    index++;
                }
                if (index == start)
                {
                    throw new FormatException("invalid JSON exponent");
                }
            }
        }

        private void ParseLiteral(string literal)
        {
            if (index + literal.Length > text.Length ||
                String.CompareOrdinal(text, index, literal, 0, literal.Length) != 0)
            {
                throw new FormatException("invalid JSON literal");
            }
            index += literal.Length;
        }

        private void SkipWhitespace()
        {
            while (index < text.Length)
            {
                char c = text[index];
                if (c != ' ' && c != '\t' && c != '\r' && c != '\n')
                {
                    return;
                }
                index++;
            }
        }

        private void Expect(char expected)
        {
            if (index >= text.Length || text[index] != expected)
            {
                throw new FormatException("invalid JSON syntax");
            }
            index++;
        }

        private bool TryConsume(char expected)
        {
            if (index < text.Length && text[index] == expected)
            {
                index++;
                return true;
            }
            return false;
        }
    }
}
'@
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($Bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-RequiredProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($Object.PSObject.Properties.Name -cnotcontains $Name) {
        throw "missing required property: $Name"
    }
    return $Object.$Name
}

function Assert-ExactProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Required
    )

    $actual = @($Object.PSObject.Properties.Name)
    $unknown = @($actual | Where-Object { $Required -cnotcontains [string]$_ })
    $missing = @($Required | Where-Object { $actual -cnotcontains [string]$_ })
    if ($unknown.Count -gt 0) {
        throw "unknown request property: $([string]$unknown[0])"
    }
    if ($missing.Count -gt 0) {
        throw "missing required property: $([string]$missing[0])"
    }
}

function ConvertFrom-StrictJsonObject {
    param(
        [Parameter(Mandatory = $true)][string]$Json,
        [Parameter(Mandatory = $true)][int]$MaximumBytes
    )

    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $bytes = $utf8.GetBytes($Json)
    if ($bytes.Length -eq 0 -or $bytes.Length -gt $MaximumBytes) {
        throw "JSON byte length is outside the fixed bound"
    }
    [Weather.Operations.StrictJsonObjectKeyValidator]::Validate($Json)
    $value = $Json | ConvertFrom-Json -ErrorAction Stop
    if ($null -eq $value -or $value -is [array] -or
        $value -is [string] -or $value -is [ValueType]) {
        throw "JSON root must be an object"
    }
    return $value
}

function Resolve-AbsoluteCanonicalPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet("File", "Directory", "Result")]
        [string]$Kind
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or -not [IO.Path]::IsPathRooted($Path)) {
        throw "$Kind path must be absolute"
    }
    $full = [IO.Path]::GetFullPath($Path)
    if ($Kind -eq "Directory") {
        if (-not (Test-Path -LiteralPath $full -PathType Container)) {
            throw "directory path does not exist"
        }
        return (Resolve-Path -LiteralPath $full -ErrorAction Stop).Path.TrimEnd('\')
    }
    if ($Kind -eq "File") {
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
            throw "file path does not exist"
        }
        return (Resolve-Path -LiteralPath $full -ErrorAction Stop).Path
    }
    $parent = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "result parent directory does not exist"
    }
    if (Test-Path -LiteralPath $full) {
        throw "ResultPath must be unused"
    }
    return $full
}

function Write-ExclusiveJsonResult {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Payload
    )

    $json = ($Payload | ConvertTo-Json -Depth 8 -Compress)
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    $bytes = $encoding.GetBytes($json)
    if ($bytes.Length -eq 0 -or $bytes.Length -gt $script:MaximumResultBytes) {
        throw "result exceeds the fixed byte bound"
    }
    $stream = New-Object IO.FileStream(
        $Path,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
}

function Assert-DeadlineOpen {
    param([Parameter(Mandatory = $true)][datetimeoffset]$Deadline)

    if ([datetimeoffset]::UtcNow -ge $Deadline) {
        throw "request deadline is closed"
    }
}

function ConvertFrom-RequestBase64 {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value.Length -eq 0 -or
        $Value.Length -gt $script:MaximumRequestBase64Characters -or
        ($Value.Length % 4) -ne 0 -or
        $Value -notmatch '^[A-Za-z0-9+/]*={0,2}$') {
        throw "RequestBase64 is not canonical bounded base64"
    }
    try { $bytes = [Convert]::FromBase64String($Value) }
    catch { throw "RequestBase64 is not valid base64" }
    if ($bytes.Length -eq 0 -or $bytes.Length -gt $script:MaximumRequestBytes -or
        [Convert]::ToBase64String($bytes) -cne $Value) {
        throw "RequestBase64 is not canonical bounded base64"
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try { return $utf8.GetString($bytes) }
    catch { throw "request is not strict UTF-8" }
}

function Get-ValidatedRequest {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedOperation,
        [Parameter(Mandatory = $true)][string]$Encoded
    )

    $json = ConvertFrom-RequestBase64 -Value $Encoded
    $requestEncoding = New-Object System.Text.UTF8Encoding($false, $true)
    $requestSha256 = Get-Sha256Hex -Bytes ($requestEncoding.GetBytes($json))
    $request = ConvertFrom-StrictJsonObject `
        -Json $json -MaximumBytes $script:MaximumRequestBytes
    $common = @("schema", "request_id", "operation", "deadline_utc", "repo_root")
    $properties = switch ($ExpectedOperation) {
        "ReadExecutionTapeTask" { $common }
        "ReadPushSnapshot" { $common + @("task_xml_sha256") }
        "StartPush" {
            $common + @("task_xml_sha256", "marker_path", "marker_sha256")
        }
        "StopPush" {
            $common + @(
                "task_xml_sha256", "marker_path", "marker_sha256", "stop_ordinal"
            )
        }
        default { throw "unsupported fixed operation" }
    }
    Assert-ExactProperties -Object $request -Required $properties
    $requiredStringProperties = @(
        "schema", "request_id", "operation", "deadline_utc", "repo_root"
    )
    if ($ExpectedOperation -ne "ReadExecutionTapeTask") {
        $requiredStringProperties += "task_xml_sha256"
    }
    if ($ExpectedOperation -in @("StartPush", "StopPush")) {
        $requiredStringProperties += @("marker_path", "marker_sha256")
    }
    foreach ($name in $requiredStringProperties) {
        if ((Get-RequiredProperty -Object $request -Name $name) -isnot [string]) {
            throw "$name must be a JSON string"
        }
    }
    if ([string](Get-RequiredProperty -Object $request -Name "schema") -cne
        $script:RequestSchema) {
        throw "request schema mismatch"
    }
    if ([string](Get-RequiredProperty -Object $request -Name "operation") -cne
        $ExpectedOperation) {
        throw "request operation mismatch"
    }
    $requestId = [string](Get-RequiredProperty -Object $request -Name "request_id")
    if ($requestId -notmatch '^[0-9a-f]{32}$') {
        throw "request_id must be 32 lowercase hexadecimal characters"
    }
    $deadlineRaw = [string](Get-RequiredProperty -Object $request -Name "deadline_utc")
    try {
        $deadline = [datetimeoffset]::ParseExact(
            $deadlineRaw,
            "yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::AssumeUniversal -bor
                [Globalization.DateTimeStyles]::AdjustToUniversal
        )
    }
    catch { throw "deadline_utc must be canonical UTC with seven fractional digits" }
    $now = [datetimeoffset]::UtcNow
    if ($deadline -le $now -or
        $deadline -gt $now.AddMinutes($script:MaximumFutureDeadlineMinutes)) {
        throw "deadline_utc is closed or beyond the fixed maximum horizon"
    }
    $repoRoot = Resolve-AbsoluteCanonicalPath `
        -Path ([string](Get-RequiredProperty -Object $request -Name "repo_root")) `
        -Kind Directory
    if ($ExpectedOperation -ne "ReadExecutionTapeTask") {
        $taskXmlSha = [string](Get-RequiredProperty -Object $request -Name "task_xml_sha256")
        if ($taskXmlSha -cne $script:ReviewedPushTaskXmlSha256) {
            throw "task_xml_sha256 does not match the reviewed task definition"
        }
    }
    if ($ExpectedOperation -eq "StopPush") {
        $rawStopOrdinal = Get-RequiredProperty -Object $request -Name "stop_ordinal"
        if ($rawStopOrdinal -isnot [int] -and $rawStopOrdinal -isnot [long]) {
            throw "stop_ordinal must be a JSON integer"
        }
        try { $stopOrdinal = [int]$rawStopOrdinal }
        catch { throw "stop_ordinal is invalid" }
        if ($stopOrdinal -notin @(1, 2)) {
            throw "stop_ordinal must be one or two"
        }
    }
    return [PSCustomObject]@{
        value = $request
        request_id = $requestId
        deadline = $deadline
        deadline_raw = $deadlineRaw
        repo_root = $repoRoot
        request_sha256 = $requestSha256
    }
}

function Assert-MutationMarker {
    param(
        [Parameter(Mandatory = $true)][object]$ValidatedRequest,
        [Parameter(Mandatory = $true)][ValidateSet("StartPush", "StopPush")]
        [string]$Mutation
    )

    $request = $ValidatedRequest.value
    $markerPath = Resolve-AbsoluteCanonicalPath `
        -Path ([string](Get-RequiredProperty -Object $request -Name "marker_path")) `
        -Kind File
    $expectedMarkerPath = Resolve-AbsoluteCanonicalPath `
        -Path (Join-Path `
            $ValidatedRequest.repo_root `
            "data\alerts\quiet_window_merge_in_progress.json") `
        -Kind File
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals(
        $markerPath,
        $expectedMarkerPath
    )) {
        throw "marker_path is not the canonical active reconciliation marker"
    }
    $markerItem = Get-Item -LiteralPath $markerPath -ErrorAction Stop
    if ($markerItem.Length -le 0 -or $markerItem.Length -gt $script:MaximumMarkerBytes) {
        throw "marker byte length is outside the fixed bound"
    }
    $expectedMarkerSha = [string](Get-RequiredProperty -Object $request -Name "marker_sha256")
    if ($expectedMarkerSha -notmatch '^[0-9a-f]{64}$') {
        throw "marker_sha256 must be lowercase hexadecimal SHA256"
    }
    $markerBytes = [IO.File]::ReadAllBytes($markerPath)
    if ((Get-Sha256Hex -Bytes $markerBytes) -cne $expectedMarkerSha) {
        throw "marker SHA256 mismatch"
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $markerJson = $utf8.GetString($markerBytes)
    $marker = ConvertFrom-StrictJsonObject `
        -Json $markerJson -MaximumBytes $script:MaximumMarkerBytes
    foreach ($name in @("schema", "operation_mode", "phase", "repo_root", "merge_commit")) {
        if ((Get-RequiredProperty -Object $marker -Name $name) -isnot [string]) {
            throw "marker $name must be a JSON string"
        }
    }
    $attempted = Get-RequiredProperty -Object $marker -Name "push_invocation_attempted"
    $acknowledged = Get-RequiredProperty -Object $marker -Name "publication_acknowledged"
    if ($attempted -isnot [bool] -or $acknowledged -isnot [bool]) {
        throw "marker publication flags must be JSON booleans"
    }
    if ([string](Get-RequiredProperty -Object $marker -Name "schema") -cne
        $script:MarkerSchema -or
        [string](Get-RequiredProperty -Object $marker -Name "operation_mode") -cne
            $script:ReconciliationMode -or
        [string](Get-RequiredProperty -Object $marker -Name "phase") -cne
            "documented_unpublished" -or
        $attempted -ne $true -or $acknowledged -eq $true -or
        [string](Get-RequiredProperty -Object $marker -Name "merge_commit") -notmatch
            '^[0-9a-f]{40}$') {
        throw "marker is not an unacknowledged attempted reconciliation publication"
    }
    $markerRepo = Resolve-AbsoluteCanonicalPath `
        -Path ([string](Get-RequiredProperty -Object $marker -Name "repo_root")) `
        -Kind Directory
    if ($markerRepo -ine $ValidatedRequest.repo_root) {
        throw "marker repo_root does not match the request"
    }
    if ($Mutation -eq "StartPush") {
        if ([string](Get-RequiredProperty -Object $marker -Name "push_start_rpc_request_id") -cne
                $ValidatedRequest.request_id -or
            [string](Get-RequiredProperty -Object $marker -Name "push_start_rpc_deadline_utc") -cne
                $ValidatedRequest.deadline_raw) {
            throw "marker does not bind the exact Start helper request"
        }
    }
    else {
        $ordinal = [int](Get-RequiredProperty -Object $request -Name "stop_ordinal")
        $stopAttempted = Get-RequiredProperty -Object $marker -Name "push_stop_attempted"
        $stopCount = Get-RequiredProperty -Object $marker -Name "push_stop_count"
        if ($stopAttempted -isnot [bool] -or
            ($stopCount -isnot [int] -and $stopCount -isnot [long])) {
            throw "marker Stop fields have invalid JSON types"
        }
        if ($stopAttempted -ne $true -or [int]$stopCount -ne $ordinal -or
            [string](Get-RequiredProperty -Object $marker -Name "push_stop_rpc_request_id") -cne
                $ValidatedRequest.request_id -or
            [string](Get-RequiredProperty -Object $marker -Name "push_stop_rpc_deadline_utc") -cne
                $ValidatedRequest.deadline_raw) {
            throw "marker does not bind the exact Stop helper request and ordinal"
        }
    }
    Assert-DeadlineOpen -Deadline $ValidatedRequest.deadline
}

function Write-MutationAuthorityClaim {
    param(
        [Parameter(Mandatory = $true)][object]$ValidatedRequest,
        [Parameter(Mandatory = $true)][ValidateSet("StartPush", "StopPush")]
        [string]$Mutation
    )

    $request = $ValidatedRequest.value
    $claimLeaf = if ($Mutation -eq "StartPush") {
        "production_baseline_scheduler_rpc_start_authority.claim.json"
    }
    else {
        $ordinal = [int](Get-RequiredProperty -Object $request -Name "stop_ordinal")
        "production_baseline_scheduler_rpc_stop_${ordinal}_authority.claim.json"
    }
    $claimPath = [IO.Path]::GetFullPath((Join-Path `
        $ValidatedRequest.repo_root `
        ("data\alerts\{0}" -f $claimLeaf)
    ))
    $claim = [ordered]@{
        schema = $script:MutationClaimSchema
        request_schema = [string](Get-RequiredProperty -Object $request -Name "schema")
        request_id = $ValidatedRequest.request_id
        request_sha256 = $ValidatedRequest.request_sha256
        operation = $Mutation
        marker_sha256 = [string](Get-RequiredProperty `
            -Object $request -Name "marker_sha256")
    }
    if ($Mutation -eq "StopPush") {
        $claim["stop_ordinal"] = [int](Get-RequiredProperty `
            -Object $request -Name "stop_ordinal")
    }
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    $bytes = $encoding.GetBytes(($claim | ConvertTo-Json -Depth 3 -Compress))

    # CreateNew is the durable, fixed per-authority replay barrier. Never
    # remove a partial or complete claim: once creation succeeds, a lost child,
    # failed flush, thrown Scheduler call, or lost response spends that exact
    # Start authority (or that exact Stop ordinal) deliberately.
    $stream = $null
    try {
        $stream = New-Object IO.FileStream(
            $claimPath,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::None
        )
        # FileMode.CreateNew crossing successfully spends this fixed authority,
        # even if a later write, flush, Scheduler call, or response fails.
        $script:MutationAuthorityClaimed = $true
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    catch {
        # A collision means a prior process already spent the authority. Do
        # not serialize the unknowable claim/mutation state as a safe negative.
        if (Test-Path -LiteralPath $claimPath -PathType Leaf) {
            $script:MutationAuthorityClaimed = $true
        }
        throw
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
    # Claim creation and its durable flush may themselves consume the final
    # request budget.  Once the claim exists its authority is spent, but a
    # deadline crossed during that write must never be followed by Scheduler
    # dispatch.  This is the sole post-claim check before the direct cmdlet.
    Assert-DeadlineOpen -Deadline $ValidatedRequest.deadline
}

function Get-ExactTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][datetimeoffset]$Deadline
    )

    Assert-DeadlineOpen -Deadline $Deadline
    $rows = @(Get-ScheduledTask `
        -TaskName $TaskName -TaskPath $script:FixedTaskPath -ErrorAction Stop)
    Assert-DeadlineOpen -Deadline $Deadline
    if ($rows.Count -ne 1) {
        throw "$TaskName must resolve to exactly one scheduled task"
    }
    $task = $rows[0]
    if ([string]$task.TaskName -cne $TaskName -or
        [string]$task.TaskPath -cne $script:FixedTaskPath) {
        throw "ScheduledTasks returned a mismatched task identity"
    }
    return $task
}

function Get-PushTaskStaticEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][datetimeoffset]$Deadline,
        [Parameter(Mandatory = $true)][string[]]$AllowedStates
    )

    Assert-DeadlineOpen -Deadline $Deadline
    $taskXml = [string](Export-ScheduledTask -InputObject $Task -ErrorAction Stop)
    Assert-DeadlineOpen -Deadline $Deadline
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    $taskXmlBytes = $encoding.GetBytes($taskXml)
    if ($taskXmlBytes.Length -eq 0 -or
        $taskXmlBytes.Length -gt $script:MaximumTaskXmlBytes) {
        throw "task XML byte length is outside the fixed bound"
    }
    $taskXmlSha = Get-Sha256Hex -Bytes $taskXmlBytes
    if ($taskXmlSha -cne $script:ReviewedPushTaskXmlSha256) {
        throw "WeatherOneShotPush task XML changed from the reviewed definition"
    }

    $actions = @($Task.Actions)
    $triggers = @($Task.Triggers)
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    try { $currentSid = [string]$currentIdentity.User.Value }
    finally { $currentIdentity.Dispose() }
    $expectedArguments = "/c git -C $RepoRoot push origin master > $($script:ExpectedPushLogPath) 2>&1"
    $actualWorkingDirectory = try {
        [IO.Path]::GetFullPath([string]$actions[0].WorkingDirectory).TrimEnd('\')
    }
    catch { "" }
    if ([string]$Task.TaskName -cne $script:PushTaskName -or
        [string]$Task.TaskPath -cne $script:FixedTaskPath -or
        $AllowedStates -cnotcontains [string]$Task.State -or
        $Task.Settings.Enabled -ne $true -or
        [string]$Task.Principal.UserId -ine $script:ExpectedPushUserId -or
        $currentSid -cne $script:ExpectedPushSid -or
        [string]$Task.Principal.LogonType -cne "Interactive" -or
        [string]$Task.Principal.RunLevel -cne "Limited" -or
        $triggers.Count -ne 0 -or
        [string]$Task.Settings.MultipleInstances -cne "IgnoreNew" -or
        [string]$Task.Settings.ExecutionTimeLimit -cne "PT15M" -or
        $Task.Settings.StartWhenAvailable -ne $false -or
        $actions.Count -ne 1 -or
        [string]$actions[0].Execute -ine "cmd.exe" -or
        [string]$actions[0].Arguments -ine $expectedArguments -or
        $actualWorkingDirectory -ine $RepoRoot) {
        throw "WeatherOneShotPush static task or current-principal binding failed"
    }
    return [PSCustomObject]@{
        task_xml = $taskXml
        task_xml_bytes = $taskXmlBytes
        task_xml_sha256 = $taskXmlSha
        action = $actions[0]
        trigger_count = $triggers.Count
    }
}

function Get-PushRuntimeInfo {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][datetimeoffset]$Deadline
    )

    Assert-DeadlineOpen -Deadline $Deadline
    $rows = @(Get-ScheduledTaskInfo -InputObject $Task -ErrorAction Stop)
    Assert-DeadlineOpen -Deadline $Deadline
    if ($rows.Count -ne 1) {
        throw "WeatherOneShotPush runtime info must resolve exactly once"
    }
    try {
        $lastRunTime = [datetime]$rows[0].LastRunTime
        $lastTaskResult = [long]$rows[0].LastTaskResult
    }
    catch { throw "WeatherOneShotPush runtime info is malformed" }
    return [PSCustomObject]@{
        last_run_time = $lastRunTime
        last_task_result = $lastTaskResult
    }
}

function Get-FullyValidatedPushTask {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][datetimeoffset]$Deadline,
        [Parameter(Mandatory = $true)][string[]]$AllowedStates
    )

    $task = Get-ExactTask `
        -TaskName $script:PushTaskName -Deadline $Deadline
    $static = Get-PushTaskStaticEvidence `
        -Task $task -RepoRoot $RepoRoot -Deadline $Deadline `
        -AllowedStates $AllowedStates
    $runtime = Get-PushRuntimeInfo -Task $task -Deadline $Deadline
    return [PSCustomObject]@{
        task = $task
        static = $static
        runtime = $runtime
    }
}

function New-PushSnapshotResult {
    param(
        [Parameter(Mandatory = $true)][object]$ValidatedRequest,
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][object]$StaticEvidence,
        [Parameter(Mandatory = $true)][object]$RuntimeInfo
    )

    return [ordered]@{
        schema = $script:ResultSchema
        request_id = $ValidatedRequest.request_id
        operation = $Operation
        ok = $true
        completed_at_utc = ([datetimeoffset]::UtcNow).ToString("o")
        task_name = [string]$Task.TaskName
        task_path = [string]$Task.TaskPath
        match_count = 1
        state = [string]$Task.State
        task_xml_base64 = [Convert]::ToBase64String($StaticEvidence.task_xml_bytes)
        task_xml_sha256 = [string]$StaticEvidence.task_xml_sha256
        enabled = [bool]$Task.Settings.Enabled
        principal_user_id = [string]$Task.Principal.UserId
        principal_logon_type = [string]$Task.Principal.LogonType
        principal_run_level = [string]$Task.Principal.RunLevel
        action_execute = [string]$StaticEvidence.action.Execute
        action_arguments = [string]$StaticEvidence.action.Arguments
        action_working_directory = [string]$StaticEvidence.action.WorkingDirectory
        trigger_count = [int]$StaticEvidence.trigger_count
        multiple_instances = [string]$Task.Settings.MultipleInstances
        execution_time_limit = [string]$Task.Settings.ExecutionTimeLimit
        start_when_available = [bool]$Task.Settings.StartWhenAvailable
        last_run_time = $RuntimeInfo.last_run_time.ToString("o")
        last_task_result = [long]$RuntimeInfo.last_task_result
    }
}

$resolvedResultPath = $null
$requestIdForError = $null
try {
    $resolvedResultPath = Resolve-AbsoluteCanonicalPath -Path $ResultPath -Kind Result
    $validated = Get-ValidatedRequest `
        -ExpectedOperation $Operation -Encoded $RequestBase64
    $requestIdForError = $validated.request_id
    Assert-DeadlineOpen -Deadline $validated.deadline

    $result = switch ($Operation) {
        "ReadExecutionTapeTask" {
            $task = Get-ExactTask `
                -TaskName $script:ExecutionTapeTaskName `
                -Deadline $validated.deadline
            [ordered]@{
                schema = $script:ResultSchema
                request_id = $validated.request_id
                operation = $Operation
                ok = $true
                completed_at_utc = ([datetimeoffset]::UtcNow).ToString("o")
                task_name = [string]$task.TaskName
                task_path = [string]$task.TaskPath
                match_count = 1
                state = [string]$task.State
            }
        }
        "ReadPushSnapshot" {
            $task = Get-ExactTask `
                -TaskName $script:PushTaskName -Deadline $validated.deadline
            $static = Get-PushTaskStaticEvidence `
                -Task $task -RepoRoot $validated.repo_root `
                -Deadline $validated.deadline `
                -AllowedStates @("Ready", "Running", "Queued")
            $runtime = Get-PushRuntimeInfo `
                -Task $task -Deadline $validated.deadline
            New-PushSnapshotResult `
                -ValidatedRequest $validated -Task $task `
                -StaticEvidence $static -RuntimeInfo $runtime
        }
        "StartPush" {
            Assert-MutationMarker `
                -ValidatedRequest $validated -Mutation "StartPush"
            $null = Get-FullyValidatedPushTask `
                -RepoRoot $validated.repo_root -Deadline $validated.deadline `
                -AllowedStates @("Ready")
            Assert-MutationMarker `
                -ValidatedRequest $validated -Mutation "StartPush"
            $final = Get-FullyValidatedPushTask `
                -RepoRoot $validated.repo_root -Deadline $validated.deadline `
                -AllowedStates @("Ready")
            $task = $final.task
            $static = $final.static
            $runtime = $final.runtime
            Assert-MutationMarker `
                -ValidatedRequest $validated -Mutation "StartPush"
            Assert-DeadlineOpen -Deadline $validated.deadline
            Write-MutationAuthorityClaim `
                -ValidatedRequest $validated -Mutation "StartPush"
            Start-ScheduledTask -InputObject $task -ErrorAction Stop
            [ordered]@{
                schema = $script:ResultSchema
                request_id = $validated.request_id
                operation = $Operation
                ok = $true
                completed_at_utc = ([datetimeoffset]::UtcNow).ToString("o")
                task_name = [string]$task.TaskName
                task_path = [string]$task.TaskPath
                pre_state = [string]$task.State
                task_xml_sha256 = [string]$static.task_xml_sha256
                pre_last_run_time = $runtime.last_run_time.ToString("o")
                pre_last_task_result = [long]$runtime.last_task_result
                mutation_authority_claimed = $true
                mutation_dispatched = $true
            }
        }
        "StopPush" {
            Assert-MutationMarker `
                -ValidatedRequest $validated -Mutation "StopPush"
            $null = Get-FullyValidatedPushTask `
                -RepoRoot $validated.repo_root -Deadline $validated.deadline `
                -AllowedStates @("Ready", "Running", "Queued")
            Assert-MutationMarker `
                -ValidatedRequest $validated -Mutation "StopPush"
            $final = Get-FullyValidatedPushTask `
                -RepoRoot $validated.repo_root -Deadline $validated.deadline `
                -AllowedStates @("Ready", "Running", "Queued")
            $task = $final.task
            $static = $final.static
            $runtime = $final.runtime
            Assert-MutationMarker `
                -ValidatedRequest $validated -Mutation "StopPush"
            Assert-DeadlineOpen -Deadline $validated.deadline
            Write-MutationAuthorityClaim `
                -ValidatedRequest $validated -Mutation "StopPush"
            Stop-ScheduledTask -InputObject $task -ErrorAction Stop
            [ordered]@{
                schema = $script:ResultSchema
                request_id = $validated.request_id
                operation = $Operation
                ok = $true
                completed_at_utc = ([datetimeoffset]::UtcNow).ToString("o")
                task_name = [string]$task.TaskName
                task_path = [string]$task.TaskPath
                pre_state = [string]$task.State
                task_xml_sha256 = [string]$static.task_xml_sha256
                pre_last_run_time = $runtime.last_run_time.ToString("o")
                pre_last_task_result = [long]$runtime.last_task_result
                stop_ordinal = [int]$validated.value.stop_ordinal
                mutation_authority_claimed = $true
                mutation_dispatched = $true
            }
        }
    }
    Assert-DeadlineOpen -Deadline $validated.deadline
    Write-ExclusiveJsonResult -Path $resolvedResultPath -Payload $result
    exit 0
}
catch {
    $message = [string]$_.Exception.Message
    if ($message.Length -gt 1024) { $message = $message.Substring(0, 1024) }
    $errorPayload = [ordered]@{
        schema = $script:ResultSchema
        request_id = $requestIdForError
        operation = $Operation
        ok = $false
        completed_at_utc = ([datetimeoffset]::UtcNow).ToString("o")
        error_code = $_.Exception.GetType().Name
        error_message = $message
        mutation_authority_claimed = [bool]$script:MutationAuthorityClaimed
        mutation_dispatched = if ($script:MutationAuthorityClaimed) {
            $null
        }
        else { $false }
    }
    if ($resolvedResultPath -and -not (Test-Path -LiteralPath $resolvedResultPath)) {
        try { Write-ExclusiveJsonResult -Path $resolvedResultPath -Payload $errorPayload }
        catch { Write-Error "failed to persist the exclusive Scheduler RPC error result" }
    }
    exit 2
}
