# Cross-process lease for heavyweight production-host work.
#
# Resource thresholds answer "can this job fit?"; this lease answers the independent
# question "is another heavyweight job already running?". The open file handle and
# named mutex are live ownership. Portable/workstation leases additionally keep a
# protected host-global ACTIVE/TEARDOWN_PENDING state file so abrupt exit and incomplete
# teardown remain observable after the last named-mutex handle closes.

# A teardown failure intentionally retains the owned lease until process exit.
# These script-scope references also prevent recursive acquisition by the same
# PowerShell process while fail-closed cleanup is still unwinding.
if (-not (Get-Variable -Name WeatherHeavyWorkloadMutexPoisoned `
        -Scope Script -ErrorAction SilentlyContinue)) {
    $script:WeatherHeavyWorkloadMutexPoisoned = $false
    $script:WeatherHeavyWorkloadPoisonedLease = $null
}

function Get-WeatherExecutionHostId {
    [CmdletBinding()]
    param()

    $machineGuid = [string](Get-ItemPropertyValue `
        -LiteralPath "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography" `
        -Name "MachineGuid" `
        -ErrorAction Stop)
    $machineGuid = $machineGuid.Trim().ToLowerInvariant()
    if (-not $machineGuid) {
        throw "execution host identity is unavailable"
    }
    $material = "international_live_execution_host_v2`0$machineGuid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($material)
        return -join ($hasher.ComputeHash($bytes) | ForEach-Object {
            $_.ToString("x2")
        })
    }
    finally { $hasher.Dispose() }
}


function Get-WeatherExecutionPrincipalId {
    [CmdletBinding()]
    param()

    $sid = [string]([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    $sid = $sid.Trim().ToLowerInvariant()
    if (-not $sid) {
        throw "execution principal identity is unavailable"
    }
    $material = "international_live_execution_principal_v1`0$sid"
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($material)
        return -join ($hasher.ComputeHash($bytes) | ForEach-Object {
            $_.ToString("x2")
        })
    }
    finally { $hasher.Dispose() }
}


function Initialize-WeatherExecutionHostAssignmentReader {
    [CmdletBinding()]
    param()

    if (-not ("Weather.Operations.ExecutionHostAssignmentReaderV1" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace Weather.Operations
{
    public static class ExecutionHostAssignmentReaderV1
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct FILETIME
        {
            public UInt32 Low;
            public UInt32 High;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct BY_HANDLE_FILE_INFORMATION
        {
            public UInt32 FileAttributes;
            public FILETIME CreationTime;
            public FILETIME LastAccessTime;
            public FILETIME LastWriteTime;
            public UInt32 VolumeSerialNumber;
            public UInt32 FileSizeHigh;
            public UInt32 FileSizeLow;
            public UInt32 NumberOfLinks;
            public UInt32 FileIndexHigh;
            public UInt32 FileIndexLow;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetFileInformationByHandle(
            SafeFileHandle file,
            out BY_HANDLE_FILE_INFORMATION information
        );

        private static BY_HANDLE_FILE_INFORMATION GetIdentity(FileStream stream)
        {
            BY_HANDLE_FILE_INFORMATION information;
            if (!GetFileInformationByHandle(stream.SafeFileHandle, out information))
            {
                throw new Win32Exception(
                    Marshal.GetLastWin32Error(),
                    "execution-host assignment identity query failed"
                );
            }
            return information;
        }

        private static bool SameIdentity(
            BY_HANDLE_FILE_INFORMATION left,
            BY_HANDLE_FILE_INFORMATION right
        )
        {
            return left.VolumeSerialNumber == right.VolumeSerialNumber
                && left.FileIndexHigh == right.FileIndexHigh
                && left.FileIndexLow == right.FileIndexLow;
        }

        private static bool SameSizeAndWriteTime(
            BY_HANDLE_FILE_INFORMATION left,
            BY_HANDLE_FILE_INFORMATION right
        )
        {
            return left.FileSizeHigh == right.FileSizeHigh
                && left.FileSizeLow == right.FileSizeLow
                && left.LastWriteTime.High == right.LastWriteTime.High
                && left.LastWriteTime.Low == right.LastWriteTime.Low;
        }

        private static void RejectRedirectedPath(string path)
        {
            string full = Path.GetFullPath(path);
            string root = Path.GetPathRoot(full);
            if (String.IsNullOrEmpty(root))
            {
                throw new InvalidDataException(
                    "execution-host assignment path must be absolute"
                );
            }
            string cursor = root;
            string remainder = full.Substring(root.Length);
            string[] parts = remainder.Split(
                new char[] {
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar
                },
                StringSplitOptions.RemoveEmptyEntries
            );
            foreach (string part in parts)
            {
                cursor = Path.Combine(cursor, part);
                FileAttributes attributes = File.GetAttributes(cursor);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                {
                    throw new InvalidDataException(
                        "execution-host assignment path is redirected"
                    );
                }
            }
        }

        public static string ReadStableUtf8Json(
            string path,
            Int32 maximumBytes,
            Action afterReadTestHook
        )
        {
            if (String.IsNullOrWhiteSpace(path) || maximumBytes <= 0)
            {
                throw new ArgumentException(
                    "execution-host assignment read contract is invalid"
                );
            }
            string full = Path.GetFullPath(path);
            RejectRedirectedPath(full);
            FileShare sharing = FileShare.ReadWrite | FileShare.Delete;
            using (FileStream stream = new FileStream(
                full,
                FileMode.Open,
                FileAccess.Read,
                sharing,
                4096,
                FileOptions.SequentialScan
            ))
            {
                BY_HANDLE_FILE_INFORMATION before = GetIdentity(stream);
                Int64 length = stream.Length;
                if (length <= 0 || length > maximumBytes)
                {
                    throw new InvalidDataException(
                        "execution-host assignment is not a bounded regular file"
                    );
                }
                byte[] raw = new byte[(Int32)length];
                Int32 offset = 0;
                while (offset < raw.Length)
                {
                    Int32 count = stream.Read(raw, offset, raw.Length - offset);
                    if (count == 0)
                    {
                        break;
                    }
                    offset += count;
                }
                if (offset != raw.Length || stream.ReadByte() != -1)
                {
                    throw new IOException(
                        "execution-host assignment changed while it was read"
                    );
                }
                if (afterReadTestHook != null)
                {
                    afterReadTestHook();
                }
                BY_HANDLE_FILE_INFORMATION after = GetIdentity(stream);
                RejectRedirectedPath(full);
                using (FileStream pathProbe = new FileStream(
                    full,
                    FileMode.Open,
                    FileAccess.Read,
                    sharing,
                    1,
                    FileOptions.None
                ))
                {
                    BY_HANDLE_FILE_INFORMATION atPath = GetIdentity(pathProbe);
                    if (!SameIdentity(before, after)
                        || !SameIdentity(before, atPath)
                        || !SameSizeAndWriteTime(before, after)
                        || !SameSizeAndWriteTime(before, atPath)
                        || stream.Length != length)
                    {
                        throw new IOException(
                            "execution-host assignment changed while it was read"
                        );
                    }
                }
                if (raw.Length >= 3
                    && raw[0] == 0xEF
                    && raw[1] == 0xBB
                    && raw[2] == 0xBF)
                {
                    throw new InvalidDataException(
                        "execution-host assignment must not contain a UTF-8 BOM"
                    );
                }
                string json = new UTF8Encoding(false, true).GetString(raw);
                new DuplicateKeyJsonParser(json).ParseDocument();
                return json;
            }
        }

        private sealed class DuplicateKeyJsonParser
        {
            private readonly string source;
            private Int32 offset;

            public DuplicateKeyJsonParser(string value)
            {
                source = value;
                offset = 0;
            }

            public void ParseDocument()
            {
                SkipWhitespace();
                ParseValue();
                SkipWhitespace();
                if (offset != source.Length)
                {
                    Fail("trailing content");
                }
            }

            private void ParseValue()
            {
                SkipWhitespace();
                if (offset >= source.Length)
                {
                    Fail("missing value");
                }
                char token = source[offset];
                if (token == '{') { ParseObject(); return; }
                if (token == '[') { ParseArray(); return; }
                if (token == '"') { ParseString(); return; }
                if (token == 't') { ParseLiteral("true"); return; }
                if (token == 'f') { ParseLiteral("false"); return; }
                if (token == 'n') { ParseLiteral("null"); return; }
                ParseNumber();
            }

            private void ParseObject()
            {
                offset++;
                SkipWhitespace();
                HashSet<string> names = new HashSet<string>(StringComparer.Ordinal);
                if (Consume('}')) { return; }
                while (true)
                {
                    SkipWhitespace();
                    if (offset >= source.Length || source[offset] != '"')
                    {
                        Fail("object key is not a string");
                    }
                    string name = ParseString();
                    if (!names.Add(name))
                    {
                        throw new InvalidDataException(
                            "execution-host assignment contains a duplicate JSON key"
                        );
                    }
                    SkipWhitespace();
                    Require(':');
                    ParseValue();
                    SkipWhitespace();
                    if (Consume('}')) { return; }
                    Require(',');
                }
            }

            private void ParseArray()
            {
                offset++;
                SkipWhitespace();
                if (Consume(']')) { return; }
                while (true)
                {
                    ParseValue();
                    SkipWhitespace();
                    if (Consume(']')) { return; }
                    Require(',');
                }
            }

            private string ParseString()
            {
                Require('"');
                StringBuilder value = new StringBuilder();
                while (offset < source.Length)
                {
                    char current = source[offset++];
                    if (current == '"') { return value.ToString(); }
                    if (current < 0x20) { Fail("unescaped control character"); }
                    if (current != '\\')
                    {
                        value.Append(current);
                        continue;
                    }
                    if (offset >= source.Length) { Fail("truncated escape"); }
                    char escaped = source[offset++];
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
                            if (offset + 4 > source.Length)
                            {
                                Fail("truncated unicode escape");
                            }
                            UInt16 code;
                            if (!UInt16.TryParse(
                                source.Substring(offset, 4),
                                System.Globalization.NumberStyles.AllowHexSpecifier,
                                System.Globalization.CultureInfo.InvariantCulture,
                                out code
                            ))
                            {
                                Fail("invalid unicode escape");
                            }
                            value.Append((char)code);
                            offset += 4;
                            break;
                        default: Fail("invalid string escape"); break;
                    }
                }
                Fail("unterminated string");
                return null;
            }

            private void ParseLiteral(string literal)
            {
                if (offset + literal.Length > source.Length
                    || String.CompareOrdinal(
                        source,
                        offset,
                        literal,
                        0,
                        literal.Length
                    ) != 0)
                {
                    Fail("invalid literal");
                }
                offset += literal.Length;
            }

            private void ParseNumber()
            {
                Int32 start = offset;
                while (offset < source.Length
                    && "+-0123456789.eE".IndexOf(source[offset]) >= 0)
                {
                    offset++;
                }
                if (offset == start) { Fail("invalid value"); }
            }

            private bool Consume(char expected)
            {
                if (offset < source.Length && source[offset] == expected)
                {
                    offset++;
                    return true;
                }
                return false;
            }

            private void Require(char expected)
            {
                if (!Consume(expected))
                {
                    Fail("missing JSON delimiter");
                }
            }

            private void SkipWhitespace()
            {
                while (offset < source.Length
                    && (source[offset] == ' '
                        || source[offset] == '\t'
                        || source[offset] == '\r'
                        || source[offset] == '\n'))
                {
                    offset++;
                }
            }

            private static void Fail(string reason)
            {
                throw new InvalidDataException(
                    "execution-host assignment JSON is invalid: " + reason
                );
            }
        }
    }
}
'@
    }
}


function Read-WeatherStableExecutionHostAssignmentText {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Action]$AfterReadTestHook = $null
    )

    Initialize-WeatherExecutionHostAssignmentReader
    return [Weather.Operations.ExecutionHostAssignmentReaderV1]::ReadStableUtf8Json(
        $Path,
        16384,
        $AfterReadTestHook
    )
}


function ConvertFrom-WeatherExactJson {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Text)

    $parameters = @{ ErrorAction = "Stop" }
    $command = Get-Command ConvertFrom-Json -ErrorAction Stop
    if ($command.Parameters.ContainsKey("DateKind")) {
        $parameters["DateKind"] = "String"
    }
    elseif ([string]$PSVersionTable.PSEdition -ceq "Core") {
        throw "this PowerShell Core version cannot preserve exact JSON timestamps"
    }
    return $Text | ConvertFrom-Json @parameters
}


function Get-WeatherExecutionHostAssignment {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $path = Join-Path $RepoRoot "config\international_live_execution_host.json"
    try {
        $assignmentText = Read-WeatherStableExecutionHostAssignmentText -Path $path
        if ($assignmentText.TrimStart().StartsWith("{") -ne $true) {
            throw "execution-host assignment root is not an object"
        }
        $assignment = ConvertFrom-WeatherExactJson -Text $assignmentText
    }
    catch {
        throw "execution-host assignment is not readable exact JSON"
    }
    $expectedNames = @(
        "active_portable_execution_host_id",
        "active_portable_execution_principal_id",
        "assignment_status",
        "dedicated_capture_execution_host_id",
        "reassignment_requires_new_production_tip",
        "schema_version"
    ) | Sort-Object
    $observedNames = @($assignment.PSObject.Properties.Name | Sort-Object)
    $schemaVersion = $assignment.schema_version
    $assignmentStatus = $assignment.assignment_status
    $dedicatedHostId = $assignment.dedicated_capture_execution_host_id
    $activeHostId = $assignment.active_portable_execution_host_id
    $activePrincipalId = $assignment.active_portable_execution_principal_id
    $requiresNewTip = $assignment.reassignment_requires_new_production_tip
    if (
        $observedNames.Count -ne $expectedNames.Count -or
        @(Compare-Object $expectedNames $observedNames -CaseSensitive).Count -ne 0 -or
        $schemaVersion -isnot [string] -or
        $schemaVersion -cne
            "international_live_execution_host_assignment_v0.1" -or
        $dedicatedHostId -isnot [string] -or
        $dedicatedHostId -cnotmatch '\A[0-9a-f]{64}\z' -or
        $requiresNewTip -isnot [bool] -or
        $requiresNewTip -ne $true -or
        $assignmentStatus -isnot [string] -or
        $assignmentStatus -cnotin @("UNASSIGNED", "ASSIGNED")
    ) {
        throw "execution-host assignment contract is invalid"
    }
    if ($assignmentStatus -ceq "UNASSIGNED") {
        if ($null -ne $activeHostId -or $null -ne $activePrincipalId) {
            throw "unassigned execution-host registry contains an active identity"
        }
    }
    elseif (
        $activeHostId -isnot [string] -or
        $activeHostId -cnotmatch '\A[0-9a-f]{64}\z' -or
        $activePrincipalId -isnot [string] -or
        $activePrincipalId -cnotmatch '\A[0-9a-f]{64}\z' -or
        $activeHostId -ceq $dedicatedHostId
    ) {
        throw "assigned portable execution-host identity is invalid"
    }
    return $assignment
}


function Get-WeatherHeavyWorkloadPolicyWindow {
    [CmdletBinding()]
    param(
        [datetime]$Now = (Get-Date),
        [switch]$AllowStageAWindow,
        [string]$OwnerApprovedException = ""
    )

    if ($OwnerApprovedException) {
        if (
            $OwnerApprovedException -cne
                "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
            $Now.ToString("yyyy-MM-dd") -cne "2026-08-23"
        ) {
            throw "owner-approved workload exception is invalid or expired"
        }
        return "owner_approved_merge_20260823"
    }

    $localMinute = ($Now.Hour * 60) + $Now.Minute
    if ($localMinute -ge 30 -and $localMinute -lt (9 * 60)) {
        return "agent_heavy"
    }
    if (
        $AllowStageAWindow -and
        $localMinute -ge (9 * 60 + 30) -and
        $localMinute -lt (11 * 60 + 55)
    ) {
        return "stage_a"
    }
    return $null
}


function Get-WeatherWorkstationOfflineModule {
    [CmdletBinding()]
    param()

    @(
        "weather.backtesting.backtest",
        "weather.backtesting.replay",
        "weather.backtesting.replay_ablation",
        "weather.backtesting.replay_backtest",
        "weather.backtesting.snapshot_analytics",
        "weather.backtesting.tape_scoring",
        "weather.calibration.calendar_residual_replication",
        "weather.calibration.pooled_candidate_replay",
        "weather.calibration.pooled_candidate_replay_diagnostics",
        "weather.calibration.pooled_candidate_replay_report",
        "weather.calibration.seasonal_challenger",
        "weather.operations.agent_docs_audit",
        "weather.operations.base_retrain",
        "weather.operations.density_live_replay_parity",
        "weather.operations.nightly_retrain",
        "weather.operations.replay_status_backfill",
        "weather.reporting.roadmap.roadmap_backlog",
        "weather.reporting.scorecards.train_serve_feature_parity"
    )
}


function Get-WeatherCommandLineWord {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$CommandLine)

    if (-not $CommandLine) { return @() }
    $wordPattern = '(?:"[^"]*"|''[^'']*''|[^\s"'']+)+'
    return @(
        [regex]::Matches($CommandLine, $wordPattern) |
            ForEach-Object { $_.Value }
    )
}


function ConvertFrom-WeatherCommandLineWord {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$Word)

    return (($Word -replace '"', '') -replace '''', '')
}


function Get-WeatherPythonModuleFromCommandLine {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$CommandLine)

    $words = @(Get-WeatherCommandLineWord -CommandLine $CommandLine)
    if ($words.Count -lt 2) { return $null }
    $executableWord = ConvertFrom-WeatherCommandLineWord -Word $words[0]
    $executableName = [IO.Path]::GetFileName($executableWord)
    $isLauncher = $executableName -cmatch
        '(?i)\A(?:pyw?|pyw?manager|pyw?-manager)(?:\.exe)?\z'
    $isManager = $executableName -cmatch
        '(?i)\A(?:pyw?manager|pyw?-manager)(?:\.exe)?\z'
    $firstArgument = 1
    $explicitExec = $false
    if ($isManager) {
        if (
            $words.Count -lt 3 -or
            (ConvertFrom-WeatherCommandLineWord -Word $words[1]) -cne 'exec'
        ) { return $null }
        $firstArgument = 2
        $explicitExec = $true
    }
    elseif (
        $isLauncher -and
        (ConvertFrom-WeatherCommandLineWord -Word $words[1]) -ceq 'exec'
    ) {
        $firstArgument = 2
        $explicitExec = $true
    }
    if ($explicitExec) {
        while ($firstArgument -lt $words.Count) {
            $managerOption = ConvertFrom-WeatherCommandLineWord `
                -Word $words[$firstArgument]
            if (
                $managerOption -cmatch '\A-(?:q+|v+)\z' -or
                $managerOption -cin @('--quiet', '--verbose')
            ) {
                $firstArgument += 1
                continue
            }
            if ($managerOption -cmatch '\A--config=') {
                $firstArgument += 1
                continue
            }
            if ($managerOption -ceq '--config') {
                $firstArgument += 2
                if ($firstArgument -gt $words.Count) { return $null }
                continue
            }
            if ($managerOption -cin @('-?', '--help')) { return $null }
            break
        }
    }
    $clusterFlags = '[bBdEiIOPqRsSuvVx]*'
    for ($index = $firstArgument; $index -lt $words.Count; $index += 1) {
        $word = ConvertFrom-WeatherCommandLineWord -Word $words[$index]
        if (
            $isLauncher -and
            $word -cmatch '\A[/-]\d+(?:\.\d+)?t?(?:-(?:32|64|arm64))?\z'
        ) {
            continue
        }
        if (
            $isLauncher -and
            $word -cmatch '\A[/-]V:(?:[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]*)?)?\z'
        ) {
            continue
        }
        $moduleMatch = [regex]::Match(
            $word,
            ('\A-(?<flags>' + $clusterFlags + ')m(?<module>.*)\z')
        )
        if ($moduleMatch.Success) {
            if ($moduleMatch.Groups["flags"].Value.Contains("V")) {
                return $null
            }
            $module = $moduleMatch.Groups["module"].Value
            if (-not $module) {
                $index += 1
                if ($index -ge $words.Count) { return $null }
                $module = ConvertFrom-WeatherCommandLineWord -Word $words[$index]
            }
            if ($module -cnotmatch '\A[A-Za-z0-9_.-]+\z') { return $null }
            return $module.ToLowerInvariant()
        }
        $consumingMatch = [regex]::Match(
            $word,
            ('\A-' + $clusterFlags + '[WX](?<value>.*)\z')
        )
        if ($consumingMatch.Success) {
            if (-not $consumingMatch.Groups["value"].Value) {
                $index += 1
            }
            continue
        }
        if ($word -ceq '--check-hash-based-pycs') {
            $index += 1
            continue
        }
        if ($word -cmatch '\A--check-hash-based-pycs=') {
            continue
        }
        if (
            $word -ceq '--' -or
            $word -ceq '-' -or
            $word -ceq '-c' -or
            ($word.Length -gt 2 -and $word.StartsWith('-c'))
        ) {
            return $null
        }
        if (
            $word.Contains("V") -and
            $word -cmatch ('\A-' + $clusterFlags + '\z')
        ) {
            return $null
        }
        if ($word -cmatch ('\A-' + $clusterFlags + '\z')) {
            continue
        }
        return $null
    }
    return $null
}


function Test-WeatherWorkstationOfflineModuleCommandLine {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$CommandLine)

    $module = Get-WeatherPythonModuleFromCommandLine -CommandLine $CommandLine
    $offlineModules = @(Get-WeatherWorkstationOfflineModule)
    return $offlineModules -ccontains $module
}


function Get-WeatherWorkstationResearchCollectionModule {
    [CmdletBinding()]
    param()

    "weather.sources.previous_runs_research_collection"
}


function Test-WeatherWorkstationResearchCollectionModuleCommandLine {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$CommandLine)

    $module = Get-WeatherPythonModuleFromCommandLine -CommandLine $CommandLine
    return $module -ceq (Get-WeatherWorkstationResearchCollectionModule)
}


function Test-WeatherHeuristicHeavyModuleCommandLine {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$CommandLine)

    $module = Get-WeatherPythonModuleFromCommandLine -CommandLine $CommandLine
    return $module -cmatch (
        '(?i)\Aweather\.[A-Za-z0-9_.-]*' +
        '(?:retrain|training|replay|backtest|daily_refresh|score_all)' +
        '[A-Za-z0-9_.-]*\z'
    )
}


function Get-WeatherActiveWorkstationHeavyProcess {
    [CmdletBinding()]
    param([object[]]$ProcessSnapshot)

    if ($PSBoundParameters.ContainsKey("ProcessSnapshot")) {
        $processes = @($ProcessSnapshot)
    }
    else {
        $processes = @(Get-CimInstance Win32_Process `
            -Property ProcessId, ParentProcessId, Name, CommandLine `
            -ErrorAction Stop)
    }

    foreach ($process in $processes) {
        $processId = [int]$process.ProcessId
        if ($processId -eq [int]$PID) { continue }
        $name = [string]$process.Name
        $commandLine = [string]$process.CommandLine
        $isPython = $name -cmatch
            '(?i)\A(?:(?:python|pythonw)(?:3(?:\.\d+)?t?)?' +
            '(?:-(?:32|64|arm64))?(?:_d)?|' +
            '(?:pyw?|pyw?manager|pyw?-manager))\.exe\z'
        $isHeavyEntrypoint = $name -cmatch
            '(?i)\A(?:pytest|py\.test|coverage(?:3|-\d+(?:\.\d+)?)?|' +
            'tox|nox)(?:\.exe)?\z'
        $isFixedScopeLiveChild = $isPython -and $commandLine -cmatch (
            '(?i)(?:\A|\s)-I\s+-S\s+-B\s+-c\s+.+?' +
            'sys\.dont_write_bytecode=True.+?runpy\.run_path'
        )
        $pythonModule = if ($isPython) {
            Get-WeatherPythonModuleFromCommandLine -CommandLine $commandLine
        }
        else { $null }
        $isOfflineWeatherModule = $isPython -and
            (Test-WeatherWorkstationOfflineModuleCommandLine `
                -CommandLine $commandLine)
        $isHeuristicHeavyWeatherModule = $isPython -and
            (Test-WeatherHeuristicHeavyModuleCommandLine `
                -CommandLine $commandLine)
        $isResearchCollectionModule = $isPython -and
            (Test-WeatherWorkstationResearchCollectionModuleCommandLine `
                -CommandLine $commandLine)
        $heavy = $isHeavyEntrypoint -or (
            $isPython -and (
                -not $commandLine -or
                @(
                    "pytest", "pytest.__main__", "compileall",
                    "coverage", "coverage.__main__",
                    "tox", "tox.__main__", "nox", "nox.__main__",
                    "cprofile", "profile", "pdb", "trace"
                ) -ccontains $pythonModule -or
                $isOfflineWeatherModule -or
                $isResearchCollectionModule -or
                $isHeuristicHeavyWeatherModule
            )
        ) -or $isFixedScopeLiveChild
        if ($heavy) {
            [PSCustomObject]@{
                ProcessId = $processId
                Name = $name
            }
        }
    }
}


function New-WeatherProtectedStateDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]
        [Security.AccessControl.DirectorySecurity]$Security
    )

    $aclExtensions = "System.IO.FileSystemAclExtensions" -as [type]
    if ($null -ne $aclExtensions) {
        $method = $aclExtensions.GetMethod(
            "CreateDirectory",
            [type[]]@(
                [Security.AccessControl.DirectorySecurity],
                [string]
            )
        )
        if ($null -eq $method) {
            throw "Core filesystem ACL directory creation is unavailable"
        }
        return [IO.DirectoryInfo]$method.Invoke(
            $null,
            [object[]]@($Security, $Path)
        )
    }
    return [IO.Directory]::CreateDirectory($Path, $Security)
}


function Get-WeatherStateDirectorySecurity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][IO.DirectoryInfo]$Directory)

    $aclExtensions = "System.IO.FileSystemAclExtensions" -as [type]
    if ($null -ne $aclExtensions) {
        $method = $aclExtensions.GetMethod(
            "GetAccessControl",
            [type[]]@([IO.DirectoryInfo])
        )
        if ($null -eq $method) {
            throw "Core filesystem ACL inspection is unavailable"
        }
        return [Security.AccessControl.DirectorySecurity]$method.Invoke(
            $null,
            [object[]]@($Directory)
        )
    }
    return [IO.Directory]::GetAccessControl($Directory.FullName)
}


function Resolve-WeatherHeavyWorkloadPoisonPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$CommonDataRoot,
        [switch]$CreateIfMissing
    )

    $commonData = $CommonDataRoot
    if ([string]::IsNullOrWhiteSpace($commonData) -or
        -not [IO.Path]::IsPathRooted($commonData)) {
        throw "host-global workload state root is unavailable"
    }
    $commonDataItem = Get-Item -LiteralPath $commonData -Force -ErrorAction Stop
    if (-not $commonDataItem.PSIsContainer -or
        ($commonDataItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "host-global workload state root is absent or redirected"
    }
    $stateRoot = Join-Path $commonDataItem.FullName "WeatherProject"
    if (-not (Test-Path -LiteralPath $stateRoot)) {
        if (-not $CreateIfMissing) {
            throw "host-global workload state directory is absent"
        }
        $directorySecurity = [Security.AccessControl.DirectorySecurity]::new()
        $directorySecurity.SetAccessRuleProtection($true, $false)
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit `
            -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
        $allow = [Security.AccessControl.AccessControlType]::Allow
        $fullControl = [Security.AccessControl.FileSystemRights]::FullControl
        $identities = @(
            [Security.Principal.WindowsIdentity]::GetCurrent().User,
            [Security.Principal.SecurityIdentifier]::new("S-1-5-18"),
            [Security.Principal.SecurityIdentifier]::new("S-1-5-32-544")
        )
        foreach ($identity in $identities) {
            $rule = [Security.AccessControl.FileSystemAccessRule]::new(
                $identity,
                $fullControl,
                $inheritance,
                [Security.AccessControl.PropagationFlags]::None,
                $allow
            )
            [void]$directorySecurity.AddAccessRule($rule)
        }
        [void](New-WeatherProtectedStateDirectory `
            -Path $stateRoot `
            -Security $directorySecurity)
    }
    $stateRootItem = Get-Item -LiteralPath $stateRoot -Force -ErrorAction Stop
    if (-not $stateRootItem.PSIsContainer -or
        ($stateRootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "host-global workload state directory is absent or redirected"
    }
    $observedSecurity = Get-WeatherStateDirectorySecurity `
        -Directory $stateRootItem
    if (-not $observedSecurity.AreAccessRulesProtected) {
        throw "host-global workload state directory ACL is not protected"
    }
    $allowedSids = @(
        [Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
        "S-1-5-18",
        "S-1-5-32-544"
    )
    $ownerSid = $observedSecurity.GetOwner(
        [Security.Principal.SecurityIdentifier]
    ).Value
    if ($ownerSid -notin $allowedSids) {
        throw "host-global workload state directory owner is not trusted"
    }
    $writeRights = [Security.AccessControl.FileSystemRights]::WriteData `
        -bor [Security.AccessControl.FileSystemRights]::AppendData `
        -bor [Security.AccessControl.FileSystemRights]::WriteExtendedAttributes `
        -bor [Security.AccessControl.FileSystemRights]::WriteAttributes `
        -bor [Security.AccessControl.FileSystemRights]::Delete `
        -bor [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles `
        -bor [Security.AccessControl.FileSystemRights]::ChangePermissions `
        -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
    foreach ($rule in $observedSecurity.GetAccessRules(
        $true,
        $true,
        [Security.Principal.SecurityIdentifier]
    )) {
        if ($rule.AccessControlType -eq
                [Security.AccessControl.AccessControlType]::Allow -and
            ($rule.FileSystemRights -band $writeRights) -ne 0 -and
            $rule.IdentityReference.Value -notin $allowedSids) {
            throw "host-global workload state directory ACL grants broad write access"
        }
    }
    return Join-Path $stateRootItem.FullName "heavy_workload_v1.poison"
}


function Get-WeatherHeavyWorkloadPoisonPath {
    [CmdletBinding()]
    param([switch]$CreateIfMissing)

    $commonData = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::CommonApplicationData
    )
    return Resolve-WeatherHeavyWorkloadPoisonPath `
        -CommonDataRoot $commonData `
        -CreateIfMissing:$CreateIfMissing
}


function Get-WeatherHeavyWorkloadPoisonState {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $exists = Test-Path -LiteralPath $Path -ErrorAction Stop
    }
    catch {
        throw "host-global workload poison state could not be validated"
    }
    if (-not $exists) { return $null }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "host-global workload state marker is malformed"
    }
    try {
        $text = Read-WeatherStableExecutionHostAssignmentText -Path $Path
        if ($text.TrimStart().StartsWith("{") -ne $true) {
            throw "marker root is not an object"
        }
        $marker = ConvertFrom-WeatherExactJson -Text $text
    }
    catch {
        throw "host-global workload state marker is not exact JSON"
    }
    $expectedNames = @(
        "boot_session_id",
        "execution_host_profile",
        "owner_process_start_utc",
        "pid",
        "schema_version",
        "state",
        "state_changed_at_utc",
        "workload"
    ) | Sort-Object
    $observedNames = @($marker.PSObject.Properties.Name | Sort-Object)
    $changedAt = [DateTimeOffset]::MinValue
    $changedAtValid = $marker.state_changed_at_utc -is [string] -and
        [DateTimeOffset]::TryParse(
            $marker.state_changed_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$changedAt
        )
    $ownerStartedAt = [DateTimeOffset]::MinValue
    $ownerStartedAtValid = $marker.owner_process_start_utc -is [string] -and
        [DateTimeOffset]::TryParse(
            $marker.owner_process_start_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind,
            [ref]$ownerStartedAt
        )
    $pidIsExactInteger =
        $marker.pid -is [int] -or $marker.pid -is [long]
    $bootSessionIdIsExactInteger =
        $marker.boot_session_id -is [int] -or
        $marker.boot_session_id -is [long]
    if (
        $observedNames.Count -ne $expectedNames.Count -or
        @(Compare-Object $expectedNames $observedNames `
            -CaseSensitive).Count -ne 0 -or
        $marker.schema_version -isnot [string] -or
        $marker.schema_version -cne "weather_heavy_workload_state_v1" -or
        $marker.state -isnot [string] -or
        $marker.state -cnotin @("ACTIVE", "TEARDOWN_PENDING") -or
        $marker.workload -isnot [string] -or
        [string]::IsNullOrWhiteSpace($marker.workload) -or
        $marker.execution_host_profile -isnot [string] -or
        $marker.execution_host_profile -cnotin @(
            "portable_execution_v1",
            "workstation_offline_v1",
            "workstation_research_collection_v1"
        ) -or
        -not $pidIsExactInteger -or
        [long]$marker.pid -le 0 -or
        [long]$marker.pid -gt [int]::MaxValue -or
        -not $ownerStartedAtValid -or
        -not $bootSessionIdIsExactInteger -or
        [long]$marker.boot_session_id -lt 0 -or
        [long]$marker.boot_session_id -gt [int]::MaxValue -or
        -not $changedAtValid
    ) {
        throw "host-global workload state marker contract is malformed"
    }
    return $marker
}


function Get-WeatherBootSessionId {
    [CmdletBinding()]
    param()

    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Registry64
    )
    $key = $null
    try {
        $key = $base.OpenSubKey(
            "SYSTEM\CurrentControlSet\Control\Session Manager\" +
            "Memory Management\PrefetchParameters",
            $false
        )
        if ($null -eq $key -or
            $key.GetValueKind("BootId") -ne
                [Microsoft.Win32.RegistryValueKind]::DWord) {
            throw "Windows boot-session identifier is unavailable"
        }
        $value = $key.GetValue(
            "BootId",
            $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        if ($value -isnot [int] -or $value -lt 0) {
            throw "Windows boot-session identifier is invalid"
        }
        return [int]$value
    }
    finally {
        if ($null -ne $key) { $key.Dispose() }
        $base.Dispose()
    }
}


function Get-WeatherProcessCreationIdentity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $process = $null
    try {
        try {
            $process = [Diagnostics.Process]::GetProcessById($ProcessId)
        }
        catch [ArgumentException] {
            return $null
        }
        try {
            return $process.StartTime.ToUniversalTime().ToString("o")
        }
        catch {
            try {
                if ($process.HasExited) { return $null }
            }
            catch { }
            throw "process creation identity could not be proved"
        }
    }
    finally {
        if ($null -ne $process) { $process.Dispose() }
    }
}


function Test-WeatherHeavyWorkloadMarkerOwnerAbsent {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Marker)

    $observedCreationIdentity = Get-WeatherProcessCreationIdentity `
        -ProcessId ([int]$Marker.pid)
    if ($null -eq $observedCreationIdentity) { return $true }
    return [string]$observedCreationIdentity -cne `
        [string]$Marker.owner_process_start_utc
}


function New-WeatherHeavyWorkloadPoisonMarker {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Workload,
        [Parameter(Mandatory = $true)][string]$ExecutionHostProfile,
        [ValidateSet("ACTIVE", "TEARDOWN_PENDING")][string]$State = "ACTIVE"
    )

    $ownerProcessStartUtc = Get-WeatherProcessCreationIdentity -ProcessId $PID
    if ([string]::IsNullOrWhiteSpace($ownerProcessStartUtc)) {
        throw "current process creation identity is unavailable"
    }
    $bootSessionId = Get-WeatherBootSessionId
    $stateChangedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    $stream = $null
    try {
        $stream = [IO.File]::Open(
            $Path,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::Read
        )
        $record = [ordered]@{
            schema_version = "weather_heavy_workload_state_v1"
            state = $State
            workload = $Workload
            execution_host_profile = $ExecutionHostProfile
            pid = $PID
            owner_process_start_utc = $ownerProcessStartUtc
            boot_session_id = $bootSessionId
            state_changed_at_utc = $stateChangedAtUtc
        }
        $raw = [Text.UTF8Encoding]::new($false).GetBytes(
            ($record | ConvertTo-Json -Compress)
        )
        $stream.Write($raw, 0, $raw.Length)
        $stream.Flush($true)
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
    }
    $created = Get-WeatherHeavyWorkloadPoisonState -Path $Path
    if ($null -eq $created -or
        [string]$created.state -cne $State -or
        [string]$created.workload -cne $Workload -or
        [string]$created.execution_host_profile -cne $ExecutionHostProfile -or
        [int]$created.pid -ne $PID -or
        [string]$created.owner_process_start_utc -cne $ownerProcessStartUtc -or
        [int]$created.boot_session_id -ne $bootSessionId -or
        [string]$created.state_changed_at_utc -cne $stateChangedAtUtc) {
        throw "host-global workload state marker did not persist exactly"
    }
}


function Set-WeatherHeavyWorkloadMarkerTeardownPending {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedWorkload,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutionHostProfile,
        [Parameter(Mandatory = $true)][int]$ExpectedPid,
        [Parameter(Mandatory = $true)][string]$ExpectedOwnerProcessStartUtc
    )

    $marker = Get-WeatherHeavyWorkloadPoisonState -Path $Path
    if ($null -eq $marker) {
        throw "host-global ACTIVE workload marker is absent"
    }
    if (
        [string]$marker.workload -cne $ExpectedWorkload -or
        [string]$marker.execution_host_profile -cne
            $ExpectedExecutionHostProfile -or
        [int]$marker.pid -ne $ExpectedPid -or
        [string]$marker.owner_process_start_utc -cne
            $ExpectedOwnerProcessStartUtc
    ) {
        throw "host-global ACTIVE workload marker does not match its owned lease"
    }
    if ([string]$marker.state -ceq "TEARDOWN_PENDING") { return $marker }
    $record = [ordered]@{
        schema_version = "weather_heavy_workload_state_v1"
        state = "TEARDOWN_PENDING"
        workload = [string]$marker.workload
        execution_host_profile = [string]$marker.execution_host_profile
        pid = [int]$marker.pid
        owner_process_start_utc = [string]$marker.owner_process_start_utc
        boot_session_id = [int]$marker.boot_session_id
        state_changed_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    }
    $temporary = "{0}.{1}.{2}.tmp" -f $Path, $PID, ([guid]::NewGuid().ToString("N"))
    $backup = "{0}.{1}.{2}.bak" -f $Path, $PID, ([guid]::NewGuid().ToString("N"))
    $stream = $null
    try {
        $stream = [IO.File]::Open(
            $temporary,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::Write,
            [IO.FileShare]::Read
        )
        $raw = [Text.UTF8Encoding]::new($false).GetBytes(
            ($record | ConvertTo-Json -Compress)
        )
        $stream.Write($raw, 0, $raw.Length)
        $stream.Flush($true)
        $stream.Dispose()
        $stream = $null
        [IO.File]::Replace($temporary, $Path, $backup)
        $updated = Get-WeatherHeavyWorkloadPoisonState -Path $Path
        if ($null -eq $updated -or
            [string]$updated.state -cne "TEARDOWN_PENDING" -or
            [string]$updated.workload -cne $ExpectedWorkload -or
            [string]$updated.execution_host_profile -cne
                $ExpectedExecutionHostProfile -or
            [int]$updated.pid -ne $ExpectedPid -or
            [string]$updated.owner_process_start_utc -cne
                $ExpectedOwnerProcessStartUtc) {
            throw "host-global teardown-pending transition did not persist"
        }
        return $updated
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        if (Test-Path -LiteralPath $temporary) {
            [IO.File]::Delete($temporary)
        }
        if (Test-Path -LiteralPath $backup) {
            [IO.File]::Delete($backup)
        }
    }
}


function Enter-WeatherHeavyWorkloadLease {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Workload,
        [switch]$AllowStageAWindow,
        [string]$OwnerApprovedException = "",
        [string]$ExecutionHostProfile = "capture_colocated_v1",
        [string]$ExpectedExecutionHostId = ""
    )

    $poisonSensitiveProfile = $ExecutionHostProfile -cin @(
        "portable_execution_v1",
        "workstation_offline_v1",
        "workstation_research_collection_v1"
    )
    if ($null -ne $script:WeatherHeavyWorkloadPoisonedLease) {
        throw (
            "this PowerShell process retains a fail-closed workload lease after " +
            "an incomplete teardown"
        )
    }

    $durablePoisonPath = $null
    $initialWorkloadState = $null

    $executionHostId = Get-WeatherExecutionHostId
    $executionPrincipalId = $null
    if ($ExecutionHostProfile -ceq "portable_execution_v1") {
        $executionPrincipalId = Get-WeatherExecutionPrincipalId
        $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
        if ($executionHostId -ceq
            [string]$assignment.dedicated_capture_execution_host_id) {
            throw (
                "portable execution-host admission is forbidden on the " +
                "dedicated capture host"
            )
        }
        if (
            [string]$assignment.assignment_status -cne "ASSIGNED" -or
            $executionHostId -cne
                [string]$assignment.active_portable_execution_host_id -or
            $executionPrincipalId -cne
                [string]$assignment.active_portable_execution_principal_id
        ) {
            throw "this host and Windows principal are not the active portable executor"
        }
        if ($AllowStageAWindow -or $OwnerApprovedException) {
            throw (
                "portable execution-host admission cannot combine with Stage-A " +
                "or owner-approved exceptions"
            )
        }
        if (
            $Workload.Length -gt 96 -or
            $Workload -cnotmatch (
                '\AInternationalLive-(?:stage0|stage1_cancel_all|stage1_dead_man)-' +
                '[A-Za-z0-9._-]+-[0-9a-f]{12}\z'
            )
        ) {
            throw "portable execution-host admission requires a canonical International live workload"
        }
        if (
            $ExpectedExecutionHostId -cnotmatch '\A[0-9a-f]{64}\z' -or
            $ExpectedExecutionHostId -cne $executionHostId
        ) {
            throw "portable execution-host identity does not match the sealed host binding"
        }
        $policyWindow = "portable_execution"
    }
    elseif ($ExecutionHostProfile -ceq "workstation_offline_v1") {
        $executionPrincipalId = Get-WeatherExecutionPrincipalId
        $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
        if ($executionHostId -ceq
            [string]$assignment.dedicated_capture_execution_host_id) {
            throw (
                "workstation-offline admission is forbidden on the dedicated " +
                "capture host"
            )
        }
        if (
            [string]$assignment.assignment_status -cne "ASSIGNED" -or
            $executionHostId -cne
                [string]$assignment.active_portable_execution_host_id -or
            $executionPrincipalId -cne
                [string]$assignment.active_portable_execution_principal_id
        ) {
            throw (
                "this host and Windows principal are not the assigned " +
                "non-capture workstation"
            )
        }
        if ($AllowStageAWindow -or $OwnerApprovedException) {
            throw (
                "workstation-offline admission cannot combine with Stage-A " +
                "or owner-approved exceptions"
            )
        }
        if (
            $Workload.Length -gt 96 -or
            $Workload -cnotmatch
                '\AWorkstationOffline-(?:pytest|compileall|weather_heavy)-[A-Za-z0-9._-]+\z'
        ) {
            throw "workstation-offline admission requires a canonical offline workload"
        }
        if ($ExpectedExecutionHostId) {
            throw "workstation-offline admission does not accept a live host binding"
        }
        $policyWindow = "workstation_offline"
    }
    elseif ($ExecutionHostProfile -ceq "workstation_research_collection_v1") {
        $executionPrincipalId = Get-WeatherExecutionPrincipalId
        $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
        if ($executionHostId -ceq
            [string]$assignment.dedicated_capture_execution_host_id) {
            throw (
                "workstation research collection is forbidden on the " +
                "dedicated capture host"
            )
        }
        if (
            [string]$assignment.assignment_status -cne "ASSIGNED" -or
            $executionHostId -cne
                [string]$assignment.active_portable_execution_host_id -or
            $executionPrincipalId -cne
                [string]$assignment.active_portable_execution_principal_id
        ) {
            throw (
                "this host and Windows principal are not the assigned " +
                "non-capture workstation"
            )
        }
        if ($AllowStageAWindow -or $OwnerApprovedException) {
            throw (
                "workstation research collection cannot combine with Stage-A " +
                "or owner-approved exceptions"
            )
        }
        if (
            $Workload.Length -gt 96 -or
            $Workload -cnotmatch
                '\AWorkstationResearchCollection-[0-9a-f]{12}\z'
        ) {
            throw (
                "workstation research collection requires the exact bounded " +
                "collector workload"
            )
        }
        if ($ExpectedExecutionHostId) {
            throw (
                "workstation research collection does not accept a live host binding"
            )
        }
        $policyWindow = "workstation_research_collection"
    }
    elseif ($ExecutionHostProfile -ceq "capture_colocated_v1") {
        if ($Workload -cmatch '\AInternationalLive-') {
            $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
            if ($executionHostId -cne
                [string]$assignment.dedicated_capture_execution_host_id) {
                throw (
                    "capture-colocated International live admission is restricted " +
                    "to the dedicated capture host"
                )
            }
            if ([string]$assignment.assignment_status -ceq "ASSIGNED") {
                throw (
                    "capture-colocated International live admission is disabled " +
                    "while a portable executor is assigned"
                )
            }
        }
        if (
            $ExpectedExecutionHostId -and
            ($ExpectedExecutionHostId -cnotmatch '\A[0-9a-f]{64}\z' -or
             $ExpectedExecutionHostId -cne $executionHostId)
        ) {
            throw "capture-colocated execution-host identity does not match the sealed host binding"
        }
        if ($OwnerApprovedException -and $Workload -cne "quiet_window_merge") {
            throw "owner-approved workload exception is restricted to quiet_window_merge"
        }
        $policyWindow = Get-WeatherHeavyWorkloadPolicyWindow `
            -AllowStageAWindow:$AllowStageAWindow `
            -OwnerApprovedException $OwnerApprovedException
        if ($null -eq $policyWindow) {
            throw (
                "heavy workload '{0}' is outside the 00:30-09:00 window; " +
                "only the explicit Stage-A lane may acquire the lease at 09:30-11:55"
            ) -f $Workload
        }
    }
    else {
        throw "execution-host profile is unsupported"
    }

    if ($poisonSensitiveProfile) {
        try {
            $durablePoisonPath = Get-WeatherHeavyWorkloadPoisonPath `
                -CreateIfMissing
            $initialWorkloadState = Get-WeatherHeavyWorkloadPoisonState `
                -Path $durablePoisonPath
        }
        catch {
            throw "host-global workload poison state blocks admission: $($_.Exception.Message)"
        }
        if ($null -ne $initialWorkloadState -and
            [string]$initialWorkloadState.state -ceq "TEARDOWN_PENDING") {
            throw (
                "host-global workload teardown is pending; a proved reboot " +
                "and explicit poison recovery are required"
            )
        }
    }

    $mutex = $null
    $mutexOwned = $false
    try {
        $mutex = [Threading.Mutex]::new(
            $false,
            "Global\WeatherProjectHeavyWorkloadV1"
        )
        try { $mutexOwned = $mutex.WaitOne(0, $false) }
        catch [Threading.AbandonedMutexException] {
            $mutexOwned = $true
        }
        if (-not $mutexOwned) {
            $mutex.Dispose()
            return $null
        }
    }
    catch {
        if ($mutexOwned -and $mutex) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        if ($mutex) { $mutex.Dispose() }
        throw "host-global workload mutex could not be acquired"
    }

    $observedWorkloadState = $null
    if ($poisonSensitiveProfile) {
        try {
            $observedWorkloadState = Get-WeatherHeavyWorkloadPoisonState `
                -Path $durablePoisonPath
        }
        catch {
            try { $mutex.ReleaseMutex() } catch { }
            $mutex.Dispose()
            throw "host-global workload state changed during admission"
        }
        if ($null -ne $observedWorkloadState -and
            [string]$observedWorkloadState.state -ceq "TEARDOWN_PENDING") {
            try { $mutex.ReleaseMutex() } catch { }
            $mutex.Dispose()
            throw (
                "host-global workload teardown is pending; a proved reboot " +
                "and explicit poison recovery are required"
            )
        }
    }

    if ($null -ne $observedWorkloadState -and
        [string]$observedWorkloadState.state -ceq "ACTIVE") {
        try {
            $ownerAbsent = Test-WeatherHeavyWorkloadMarkerOwnerAbsent `
                -Marker $observedWorkloadState
        }
        catch {
            try { $mutex.ReleaseMutex() } catch { }
            $mutex.Dispose()
            throw "ACTIVE workload owner identity could not be proved absent"
        }
        if (-not $ownerAbsent) {
            try { $mutex.ReleaseMutex() } catch { }
            $mutex.Dispose()
            throw "ACTIVE workload owner process still exists"
        }
        try {
            $activeHeavyProcesses = $null
            for ($attempt = 0; $attempt -lt 50; $attempt++) {
                $activeHeavyProcesses = @(
                    Get-WeatherActiveWorkstationHeavyProcess
                )
                if ($activeHeavyProcesses.Count -eq 0) { break }
                if ($attempt -lt 49) { Start-Sleep -Milliseconds 100 }
            }
        }
        catch {
            if ($mutexOwned) {
                try { $mutex.ReleaseMutex() } catch { }
            }
            $mutex.Dispose()
            throw (
                "ACTIVE workload recovery could not prove heavy-process " +
                "quiescence"
            )
        }
        if ($activeHeavyProcesses.Count -gt 0) {
            if ($mutexOwned) {
                try { $mutex.ReleaseMutex() } catch { }
            }
            $mutex.Dispose()
            throw (
                "ACTIVE workload recovery found {0} residual heavy " +
                "process(es)"
            ) -f $activeHeavyProcesses.Count
        }
    }

    if ($null -ne $observedWorkloadState -and
        [string]$observedWorkloadState.state -ceq "ACTIVE") {
        try {
            $confirmedState = Get-WeatherHeavyWorkloadPoisonState `
                -Path $durablePoisonPath
            if ($null -eq $confirmedState -or
                [string]$confirmedState.state -cne "ACTIVE" -or
                [int]$confirmedState.pid -ne [int]$observedWorkloadState.pid -or
                [string]$confirmedState.owner_process_start_utc -cne
                    [string]$observedWorkloadState.owner_process_start_utc -or
                [int]$confirmedState.boot_session_id -ne
                    [int]$observedWorkloadState.boot_session_id -or
                [string]$confirmedState.execution_host_profile -cne
                    [string]$observedWorkloadState.execution_host_profile -or
                [string]$confirmedState.state_changed_at_utc -cne
                    [string]$observedWorkloadState.state_changed_at_utc -or
                [string]$confirmedState.workload -cne
                    [string]$observedWorkloadState.workload) {
                throw "ACTIVE workload marker changed during recovery"
            }
            if (-not (Test-WeatherHeavyWorkloadMarkerOwnerAbsent `
                    -Marker $confirmedState)) {
                throw "ACTIVE workload owner process reappeared during recovery"
            }
            [IO.File]::Delete($durablePoisonPath)
            if (Test-Path -LiteralPath $durablePoisonPath -ErrorAction Stop) {
                throw "ACTIVE workload marker could not be cleared"
            }
        }
        catch {
            try { $mutex.ReleaseMutex() } catch { }
            $mutex.Dispose()
            throw "ACTIVE workload recovery failed closed: $($_.Exception.Message)"
        }
        $mutex.ReleaseMutex()
        $mutexOwned = $false
        $mutex.Dispose()
        throw (
            "a stale ACTIVE workload marker was recovered after proving zero " +
            "residual heavy processes; retry the exact attended operation"
        )
    }

    try {
        $logRoot = Join-Path $RepoRoot "data\logs"
        if (-not (Test-Path -LiteralPath $logRoot)) {
            New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
        }
        $path = Join-Path $logRoot "heavy_workload.lock"
    }
    catch {
        if ($mutexOwned) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        $mutex.Dispose()
        throw
    }
    $stream = $null
    try {
        # Readers may inspect the owner record, but a second ReadWrite owner cannot open it.
        $stream = [System.IO.File]::Open(
            $path,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::Read
        )
    }
    catch [System.IO.IOException] {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
        return $null
    }
    catch {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
        throw
    }

    try {
        $stream.SetLength(0)
        $ownerProcessStartUtc = Get-WeatherProcessCreationIdentity -ProcessId $PID
        if ([string]::IsNullOrWhiteSpace($ownerProcessStartUtc)) {
            throw "current workload-owner process creation identity is unavailable"
        }
        $ownerProcessCreationTimeToken = "win32-filetime:{0}" -f (
            [DateTime]::Parse(
                $ownerProcessStartUtc,
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind
            ).ToFileTimeUtc()
        )
        $record = [ordered]@{
            schema_version = "weather_heavy_workload_lease_v3"
            workload = $Workload
            pid = $PID
            owner_process_creation_time_token = $ownerProcessCreationTimeToken
            acquired_at = (Get-Date).ToUniversalTime().ToString("o")
            policy_window = $policyWindow
            host = [Environment]::MachineName
            execution_host_profile = $ExecutionHostProfile
            execution_host_id = $executionHostId
            execution_principal_id = $executionPrincipalId
            host_global_mutex = "Global\WeatherProjectHeavyWorkloadV1"
        }
        $encoding = New-Object System.Text.UTF8Encoding($false)
        $writer = New-Object System.IO.StreamWriter($stream, $encoding, 1024, $true)
        try {
            $writer.Write(($record | ConvertTo-Json -Compress))
            $writer.Flush()
            $stream.Flush()
        }
        finally { $writer.Dispose() }
        if ($poisonSensitiveProfile) {
            New-WeatherHeavyWorkloadPoisonMarker `
                -Path $durablePoisonPath `
                -Workload $Workload `
                -ExecutionHostProfile $ExecutionHostProfile `
                -State "ACTIVE"
        }
        return [PSCustomObject]@{
            Path = $path
            Workload = $Workload
            Stream = $stream
            Mutex = $mutex
            MutexOwned = $mutexOwned
            ExecutionHostProfile = $ExecutionHostProfile
            ExecutionHostId = $executionHostId
            ExecutionPrincipalId = $executionPrincipalId
            DurablePoisonPath = $durablePoisonPath
            WorkloadState = $(
                if ($poisonSensitiveProfile) { "ACTIVE" } else { $null }
            )
        }
    }
    catch {
        $stream.Dispose()
        if ($mutexOwned) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        $mutex.Dispose()
        throw
    }
}


function Set-WeatherHeavyWorkloadLeaseTeardownPending {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Lease)

    if (
        $null -eq $Lease -or
        $Lease.PSObject.Properties.Name -notcontains "MutexOwned" -or
        $Lease.PSObject.Properties.Name -notcontains "Mutex" -or
        -not $Lease.MutexOwned -or
        $null -eq $Lease.Mutex
    ) {
        throw "cannot transition an unowned host-global workload lease"
    }
    if ([string]$Lease.ExecutionHostProfile -ceq "capture_colocated_v1") {
        return
    }
    if ([string]$Lease.ExecutionHostProfile -cnotin @(
            "portable_execution_v1",
            "workstation_offline_v1",
            "workstation_research_collection_v1"
        ) -or
        $Lease.PSObject.Properties.Name -notcontains "DurablePoisonPath" -or
        $Lease.PSObject.Properties.Name -notcontains "WorkloadState" -or
        [string]::IsNullOrWhiteSpace([string]$Lease.DurablePoisonPath) -or
        [string]$Lease.WorkloadState -cne "ACTIVE") {
        throw "workstation lease is not in the ACTIVE teardown state"
    }
    try {
        $current = Get-WeatherHeavyWorkloadPoisonState `
            -Path ([string]$Lease.DurablePoisonPath)
        $currentProcessStartUtc = Get-WeatherProcessCreationIdentity `
            -ProcessId $PID
        if ($null -eq $current -or
            [string]$current.state -cne "ACTIVE" -or
            [string]$current.owner_process_start_utc -cne
                $currentProcessStartUtc) {
            throw "owned ACTIVE workload marker is absent or not ACTIVE"
        }
        $pending = Set-WeatherHeavyWorkloadMarkerTeardownPending `
            -Path ([string]$Lease.DurablePoisonPath) `
            -ExpectedWorkload ([string]$Lease.Workload) `
            -ExpectedExecutionHostProfile ([string]$Lease.ExecutionHostProfile) `
            -ExpectedPid $PID `
            -ExpectedOwnerProcessStartUtc `
                ([string]$current.owner_process_start_utc)
        $Lease.WorkloadState = "TEARDOWN_PENDING"
        return $pending
    }
    catch {
        $Lease | Add-Member -NotePropertyName TeardownPoisoned `
            -NotePropertyValue $true -Force
        $script:WeatherHeavyWorkloadMutexPoisoned = $true
        $script:WeatherHeavyWorkloadPoisonedLease = $Lease
        throw "failed to durably enter teardown-pending state: $($_.Exception.Message)"
    }
}


function Set-WeatherHeavyWorkloadLeasePoisoned {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)]$Lease)

    if (
        $null -eq $Lease -or
        $Lease.PSObject.Properties.Name -notcontains "MutexOwned" -or
        $Lease.PSObject.Properties.Name -notcontains "Mutex" -or
        -not $Lease.MutexOwned -or
        $null -eq $Lease.Mutex
    ) {
        throw "cannot poison an unowned host-global workload lease"
    }
    if ([string]$Lease.ExecutionHostProfile -ceq "capture_colocated_v1") {
        $Lease | Add-Member -NotePropertyName TeardownPoisoned `
            -NotePropertyValue $true -Force
        $script:WeatherHeavyWorkloadPoisonedLease = $Lease
        return
    }
    if ($Lease.PSObject.Properties.Name -notcontains "DurablePoisonPath" -or
        $Lease.PSObject.Properties.Name -notcontains "WorkloadState" -or
        [string]::IsNullOrWhiteSpace([string]$Lease.DurablePoisonPath) -or
        [string]$Lease.WorkloadState -cne "TEARDOWN_PENDING") {
        throw "failed workstation teardown was not durably marked pending"
    }
    try {
        $marker = Get-WeatherHeavyWorkloadPoisonState `
            -Path ([string]$Lease.DurablePoisonPath)
        if ($null -eq $marker -or
            [string]$marker.state -cne "TEARDOWN_PENDING" -or
            [string]$marker.workload -cne [string]$Lease.Workload -or
            [string]$marker.execution_host_profile -cne
                [string]$Lease.ExecutionHostProfile -or
            [int]$marker.pid -ne $PID -or
            [string]$marker.owner_process_start_utc -cne
                (Get-WeatherProcessCreationIdentity -ProcessId $PID) -or
            [int]$marker.boot_session_id -ne (Get-WeatherBootSessionId)) {
            throw "durable teardown-pending marker no longer matches the lease"
        }
    }
    catch {
        $Lease | Add-Member -NotePropertyName TeardownPoisoned `
            -NotePropertyValue $true -Force
        $script:WeatherHeavyWorkloadMutexPoisoned = $true
        $script:WeatherHeavyWorkloadPoisonedLease = $Lease
        throw "failed to verify durable teardown poison: $($_.Exception.Message)"
    }
    $Lease | Add-Member -NotePropertyName TeardownPoisoned `
        -NotePropertyValue $true -Force
    $script:WeatherHeavyWorkloadMutexPoisoned = $true
    $script:WeatherHeavyWorkloadPoisonedLease = $Lease
}


function Clear-WeatherHeavyWorkloadPoison {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Confirmation)

    if ($Confirmation -cne
        "I_HAVE_VERIFIED_NO_RESIDUAL_WEATHER_WORKLOAD_PROCESSES") {
        throw "host-global workload poison recovery confirmation is not exact"
    }
    if ($script:WeatherHeavyWorkloadMutexPoisoned -or
        $null -ne $script:WeatherHeavyWorkloadPoisonedLease) {
        throw "host-global workload poison recovery requires a fresh PowerShell process"
    }
    $path = Get-WeatherHeavyWorkloadPoisonPath
    try {
        $marker = Get-WeatherHeavyWorkloadPoisonState -Path $path
        if ($null -eq $marker) {
            throw "host-global workload poison marker is absent"
        }
        if ([string]$marker.state -cne "TEARDOWN_PENDING") {
            throw "only a TEARDOWN_PENDING workload marker may be explicitly recovered"
        }
        if ((Get-WeatherBootSessionId) -eq [int]$marker.boot_session_id) {
            throw "a different Windows boot session is required for poison recovery"
        }
    }
    catch {
        throw "host-global workload poison marker cannot be recovered: $($_.Exception.Message)"
    }

    $mutex = $null
    $owned = $false
    try {
        $mutex = [Threading.Mutex]::new(
            $false,
            "Global\WeatherProjectHeavyWorkloadV1"
        )
        try { $owned = $mutex.WaitOne(0, $false) }
        catch [Threading.AbandonedMutexException] { $owned = $true }
        if (-not $owned) {
            throw "host-global workload mutex is still owned during poison recovery"
        }
        $confirmed = Get-WeatherHeavyWorkloadPoisonState -Path $path
        if ($null -eq $confirmed -or
            [string]$confirmed.state -cne "TEARDOWN_PENDING" -or
            [int]$confirmed.boot_session_id -ne [int]$marker.boot_session_id -or
            [int]$confirmed.pid -ne [int]$marker.pid -or
            [string]$confirmed.owner_process_start_utc -cne
                [string]$marker.owner_process_start_utc -or
            [string]$confirmed.execution_host_profile -cne
                [string]$marker.execution_host_profile -or
            [string]$confirmed.state_changed_at_utc -cne
                [string]$marker.state_changed_at_utc -or
            [string]$confirmed.workload -cne [string]$marker.workload) {
            throw "host-global workload poison marker changed during recovery"
        }
        try {
            $residuals = $null
            for ($attempt = 0; $attempt -lt 50; $attempt++) {
                $residuals = @(Get-WeatherActiveWorkstationHeavyProcess)
                if ($residuals.Count -eq 0) { break }
                if ($attempt -lt 49) { Start-Sleep -Milliseconds 100 }
            }
        }
        catch {
            throw "residual-process quiescence could not be proved during poison recovery"
        }
        if ($residuals.Count -ne 0) {
            throw "residual heavy processes remain during poison recovery"
        }
        $finalState = Get-WeatherHeavyWorkloadPoisonState -Path $path
        if ($null -eq $finalState -or
            [string]$finalState.state -cne "TEARDOWN_PENDING" -or
            [int]$finalState.boot_session_id -ne
                [int]$confirmed.boot_session_id -or
            [int]$finalState.pid -ne [int]$confirmed.pid -or
            [string]$finalState.owner_process_start_utc -cne
                [string]$confirmed.owner_process_start_utc -or
            [string]$finalState.execution_host_profile -cne
                [string]$confirmed.execution_host_profile -or
            [string]$finalState.state_changed_at_utc -cne
                [string]$confirmed.state_changed_at_utc -or
            [string]$finalState.workload -cne [string]$confirmed.workload) {
            throw "host-global workload poison marker changed during residual scan"
        }
        [IO.File]::Delete($path)
        if (Test-Path -LiteralPath $path -ErrorAction Stop) {
            throw "host-global workload poison marker could not be cleared"
        }
    }
    finally {
        if ($owned -and $null -ne $mutex) {
            try { $mutex.ReleaseMutex() } catch { }
        }
        if ($null -ne $mutex) { $mutex.Dispose() }
    }
}


function Exit-WeatherHeavyWorkloadLease {
    [CmdletBinding()]
    param($Lease)
    if (
        $null -ne $Lease -and
        $Lease.PSObject.Properties.Name -contains "TeardownPoisoned" -and
        $Lease.TeardownPoisoned
    ) {
        throw "refusing to release a teardown-poisoned host-global workload lease"
    }
    $poisonSensitiveProfile = $null -ne $Lease -and
        [string]$Lease.ExecutionHostProfile -cin @(
            "portable_execution_v1",
            "workstation_offline_v1",
            "workstation_research_collection_v1"
        )
    if ($poisonSensitiveProfile) {
        try {
            if ($Lease.PSObject.Properties.Name -notcontains "WorkloadState" -or
                [string]$Lease.WorkloadState -cne "TEARDOWN_PENDING" -or
                $Lease.PSObject.Properties.Name -notcontains "DurablePoisonPath" -or
                [string]::IsNullOrWhiteSpace([string]$Lease.DurablePoisonPath)) {
                throw "workstation lease did not enter TEARDOWN_PENDING"
            }
            $marker = Get-WeatherHeavyWorkloadPoisonState `
                -Path ([string]$Lease.DurablePoisonPath)
            if ($null -eq $marker -or
                [string]$marker.state -cne "TEARDOWN_PENDING" -or
                [string]$marker.workload -cne [string]$Lease.Workload -or
                [string]$marker.execution_host_profile -cne
                    [string]$Lease.ExecutionHostProfile -or
                [int]$marker.pid -ne $PID -or
                [string]$marker.owner_process_start_utc -cne
                    (Get-WeatherProcessCreationIdentity -ProcessId $PID) -or
                [int]$marker.boot_session_id -ne (Get-WeatherBootSessionId)) {
                throw "TEARDOWN_PENDING marker does not match the owned lease"
            }
            [IO.File]::Delete([string]$Lease.DurablePoisonPath)
            if (Test-Path -LiteralPath ([string]$Lease.DurablePoisonPath) `
                    -ErrorAction Stop) {
                throw "TEARDOWN_PENDING marker could not be cleared"
            }
            $Lease.WorkloadState = "CLEARED"
        }
        catch {
            $Lease | Add-Member -NotePropertyName TeardownPoisoned `
                -NotePropertyValue $true -Force
            $script:WeatherHeavyWorkloadMutexPoisoned = $true
            $script:WeatherHeavyWorkloadPoisonedLease = $Lease
            throw "workstation lease cleanup failed closed: $($_.Exception.Message)"
        }
    }
    try {
        if ($null -ne $Lease -and
            $Lease.PSObject.Properties.Name -contains "Stream" -and
            $null -ne $Lease.Stream) {
            $Lease.Stream.Dispose()
        }
    }
    finally {
        if ($null -ne $Lease -and
            $Lease.PSObject.Properties.Name -contains "MutexOwned" -and
            $Lease.PSObject.Properties.Name -contains "Mutex" -and
            $Lease.MutexOwned -and $null -ne $Lease.Mutex) {
            try { $Lease.Mutex.ReleaseMutex() }
            finally {
                $Lease.Mutex.Dispose()
                $Lease.MutexOwned = $false
            }
        }
    }
}


function Get-WeatherHeavyWorkloadLeaseState {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $path = Join-Path $RepoRoot "data\logs\heavy_workload.lock"
    if (-not (Test-Path -LiteralPath $path)) {
        return [PSCustomObject]@{ Active = $false; Path = $path; Owner = $null }
    }

    $probe = $null
    try {
        # The owner permits readers but not writers. A no-op write-capable open therefore
        # distinguishes an active OS-held lease from stale diagnostic JSON.
        $probe = [System.IO.File]::Open(
            $path,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::ReadWrite
        )
        return [PSCustomObject]@{ Active = $false; Path = $path; Owner = $null }
    }
    catch [System.IO.IOException] {
        $owner = $null
        try { $owner = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch {}
        return [PSCustomObject]@{ Active = $true; Path = $path; Owner = $owner }
    }
    finally { if ($probe) { $probe.Dispose() } }
}
