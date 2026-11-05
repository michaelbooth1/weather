<#
.SYNOPSIS
Quarantine torn maker-evidence journals left by a hard power loss (Stage 1: operator tool).

.DESCRIPTION
EvidenceStore._recover refuses to start when a journal in the unsealed segment ends in a
NUL-filled or partial last line, so the recorder task returns 1 at every trigger. This script
automates the manual torn-journal procedure in docs/operations/passive-maker-evidence-capture.md.
Report-only unless -Apply.

Safety contract (design approved 2026-11-02, L54):
- Classifies only while holding byte 0 of <Root>\.writer.lock (FileStream.Lock(0,1), the same
  Win32 LockFile region the recorder's msvcrt.locking takes before EvidenceStore exists). The
  lock is held for the whole pass and released on every exit. A running recorder process for
  the same root is an additional (advisory) refusal.
- Exactly one unsealed segment (<day>\<HH>-<12 hex> without manifest.json/.json.gz) or nothing.
  Root, quarantine root, day, segment, journals and destination must not be reparse points and
  root and quarantine must be on the same volume (path root, volume mount and serial).
- Candidates: non-empty, non-dot *.jsonl (case-insensitive) directly in that segment whose last
  byte is not 0x0A. At most MaxFiles (hard cap 10); above it nothing moves. A NUL byte inside any
  other journal of the segment means moving tails cannot let the store recover: UNRESOLVED.
- Same-volume rename only (never copy+delete), SHA-256 before and after, an intent file before
  the first move and an immutable receipt after the last. A rerun reconciles from the intent,
  including after the store has already sealed the segment (RECONCILED_AFTER_SEAL).
- Every NOOP exit consults -TaskName (default WeatherMakerEvidenceCapture for the core root only;
  empty skips it and the output says so). LastTaskResult 1 that is newer than this segment's
  receipt turns the NOOP into TORN_SIGNATURE_UNRESOLVED.
- Never truncates, rewrites or deletes; never touches sealed segments' journals, manifests, .gz,
  .tmp, status.json or the lock file contents. No Scheduler mutation: start the task yourself.
- A writer-alive refusal first runs a read-only mirror of EvidenceStore._recover over the store
  and reports torn_tail_found: false only when every unsealed segment and sealed manifest is
  positively recoverable, null when anything is unverifiable or over 64 unsealed segments exist.
  Only the live writer's own segment (the single newest unsealed one) may show a partial last
  line, and only while it moves during a 2 s wait. Any other torn tail is
  REFUSED_WRITER_ALIVE_TORN (exit 3): a recorder that cannot start, or a foreign lock holder.
  A lock-open failure that is not a sharing or lock violation is REFUSED_LOCK_UNAVAILABLE (2).

Exit codes: 0 NOOP / REPORT / QUARANTINED / RECONCILED / RECONCILED_AFTER_SEAL; 2 refused;
3 REFUSED_WRITER_ALIVE_TORN;
4 failed mid-apply or FAILED_HASH_READ (rerun reconciles, or reports UNRESOLVED on a hash mismatch); 5 UNRESOLVED / TORN_SIGNATURE_UNRESOLVED
(needs a human; no action taken); 6 INTERNAL_ERROR (unexpected throw; lock released). A
parameter-binding error is raised by PowerShell before the script runs and is outside this
contract.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Root = "",
    [string]$QuarantineRoot = "",
    [string]$LogPath = "",
    [string]$TaskName = "",
    [ValidateRange(1, 10)][int]$MaxFiles = 10,
    [string]$RepoRoot = ""
)
$ErrorActionPreference = "Stop"
$script:lockStream = $null
$script:receiptTime = $null
$script:result = [ordered]@{
    schema = "maker_evidence_torn_quarantine_v2"; status = ""; applied = [bool]$Apply
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("o"); script_sha256 = $null
    root = $Root; quarantine_root = $QuarantineRoot; task_name = $TaskName; task_check = $null
    segment = $null; candidates = @(); reasons = @()
}

function Release-Lock {
    if ($null -ne $script:lockStream) {
        try { $script:lockStream.Unlock(0, 1) } catch { }
        try { $script:lockStream.Dispose() } catch { }
        $script:lockStream = $null
    }
}

function Write-Log {
    if (-not $Apply -or -not $LogPath) { return }
    try {
        $dir = Split-Path -Parent $LogPath
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $bytes = [Text.Encoding]::UTF8.GetBytes(($script:result | ConvertTo-Json -Compress -Depth 6) + "`n")
        $stream = New-Object IO.FileStream($LogPath, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
        try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    }
    catch { $script:result.reasons += ("log write failed: " + $_.Exception.Message) }
}

function Emit-And-Exit([int]$Code) {
    Write-Log
    $script:result | ConvertTo-Json -Depth 6
    Release-Lock
    exit $Code
}

function Test-TaskSignature {
    if (-not $TaskName) { $script:result.task_check = "skipped: no -TaskName"; return $false }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $info) { $script:result.task_check = "task not found"; return $false }
    $last = [int64]$info.LastTaskResult
    $script:result.task_last_result = $last
    $runTime = $null
    if ($info.LastRunTime) { $runTime = ([datetime]$info.LastRunTime).ToUniversalTime(); $script:result.task_last_run_utc = $runTime.ToString("o") }
    if ($last -ne 1) { $script:result.task_check = "last result $last"; return $false }
    if ($null -ne $script:receiptTime -and ($null -eq $runTime -or $runTime -le $script:receiptTime)) {
        $script:result.task_check = "last result 1 predates this segment's receipt; start the task, then rerun"
        return $false
    }
    $script:result.task_check = "last result 1: the recorder still fails to start"
    return $true
}

function Finish([string]$Status, [int]$Code, [string]$Reason = "") {
    $script:result.status = $Status
    if ($Reason) { $script:result.reasons += $Reason }
    if ($Status.StartsWith("NOOP") -and (Test-TaskSignature)) {
        $script:result.noop_status = $Status
        $script:result.status = "TORN_SIGNATURE_UNRESOLVED"
        $script:result.reasons += "nothing this tool may move explains the failing recorder; a human must diagnose"
        $Code = 5
    }
    Emit-And-Exit $Code
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-ShaChecked([string]$Path, [bool]$HasIntent) {
    # Hash a journal during plan/apply; an unreadable or empty hash stops with FAILED_HASH_READ.
    $hash = $null
    $why = "no hash returned"
    try {
        $value = Get-FileHash -LiteralPath $Path -Algorithm SHA256
        if ($value) { $hash = [string]$value.Hash }
    }
    catch { $why = $_.Exception.Message }
    if ($hash -notmatch '^[0-9A-Fa-f]{64}$') {
        $next = "nothing moved; no intent"
        if ($HasIntent) { $next = "intent kept, rerun reconciles" }
        Finish "FAILED_HASH_READ" 4 ("cannot hash {0} ({1}); {2}" -f $Path, $why, $next)
    }
    return $hash.ToLowerInvariant()
}

function Open-Shared([string]$Path) {
    return New-Object IO.FileStream($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read,
        ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
}

function Get-TailClass([string]$Path) {
    # $null when the file ends in 0x0A (or is empty), else the torn-tail class.
    $stream = Open-Shared $Path
    try {
        $length = $stream.Length
        if ($length -eq 0) { return $null }
        $window = [int][Math]::Min($length, 1048576)
        $buffer = New-Object byte[] $window
        [void]$stream.Seek($length - $window, [IO.SeekOrigin]::Begin)
        $read = 0
        while ($read -lt $window) {
            $n = $stream.Read($buffer, $read, $window - $read)
            if ($n -le 0) { throw "short read on $Path" }
            $read += $n
        }
        if ($buffer[$window - 1] -eq 10) { return $null }
        $nul = 0
        for ($i = $window - 1; $i -ge 0 -and $buffer[$i] -eq 0; $i--) { $nul++ }
        if ($nul -gt 0) {
            return [ordered]@{ tail = "nul_tail"; nul_tail_bytes = $nul
                nul_tail_scan_capped = ($nul -eq $window -and $window -lt $length) }
        }
        return [ordered]@{ tail = "no_final_newline"; nul_tail_bytes = 0; nul_tail_scan_capped = $false }
    }
    finally { $stream.Dispose() }
}

function Test-ContainsNul([string]$Path) {
    $stream = Open-Shared $Path
    try {
        $buffer = New-Object byte[] 1048576
        while (($n = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ([Array]::IndexOf($buffer, [byte]0, 0, $n) -ge 0) { return $true }
        }
        return $false
    }
    finally { $stream.Dispose() }
}

function Test-Reparse($Item) { return [bool]($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) }

function Test-ReparseChain([string]$Path) {
    # True when the path or any existing ancestor is a reparse point (junction/symlink).
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if (Test-Reparse (Get-Item -LiteralPath $current -Force)) { return $true }
        }
        $parent = Split-Path -Parent $current
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
    return $false
}

function Get-VolumeIdentity([string]$Path) {
    # Volume mount path + serial of the nearest existing ancestor.
    $current = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $current)) {
        $parent = Split-Path -Parent $current
        if (-not $parent -or $parent -eq $current) { return $null }
        $current = $parent
    }
    if (-not ("WeatherTornQuarantine.Volume" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
namespace WeatherTornQuarantine {
    public static class Volume {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool GetVolumePathNameW(string fileName, StringBuilder volumePath, uint length);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool GetVolumeInformationW(string rootPath, StringBuilder name, uint nameSize,
            out uint serial, out uint maxComponent, out uint flags, StringBuilder fileSystem, uint fileSystemSize);
        public static string Identity(string path) {
            var volume = new StringBuilder(1024);
            if (!GetVolumePathNameW(path, volume, 1024)) { return null; }
            uint serial, maxComponent, flags;
            if (!GetVolumeInformationW(volume.ToString(), null, 0, out serial, out maxComponent, out flags, null, 0)) { return null; }
            return volume.ToString().ToLowerInvariant() + "|" + serial.ToString("x8");
        }
    }
}
"@
    }
    return [WeatherTornQuarantine.Volume]::Identity($current)
}

function Write-AtomicNew([string]$Path, $Value) {
    # Never overwrites: UTF-8 tmp + flush-to-disk + rename onto a name that must not exist.
    if (Test-Path -LiteralPath $Path) { throw "refusing to overwrite $Path" }
    $tmp = $Path + ".tmp"
    $bytes = (New-Object Text.UTF8Encoding($false)).GetBytes(($Value | ConvertTo-Json -Depth 8) + "`n")
    $stream = New-Object IO.FileStream($tmp, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    [IO.File]::Move($tmp, $Path)
}

function Read-JsonFile([string]$Path) {
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Test-JournalName([string]$Name) {
    return ($Name -and -not $Name.StartsWith(".") -and
        $Name.EndsWith(".jsonl", [StringComparison]::OrdinalIgnoreCase))
}

function Get-StoreScanType {
    # Compiled once per run; C# so a 100 MB live segment is checked in seconds.
    if (-not ("WeatherTornQuarantine.StoreScan" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
namespace WeatherTornQuarantine {
    public sealed class ScanResult {
        public List<string> Unsealed = new List<string>();
        public List<string> Torn = new List<string>();
        public List<string> Invalid = new List<string>();
        public List<string> Errors = new List<string>();
        public List<string> InFlight = new List<string>();
        public string LiveSegment;
    }

    // Read-only mirror of EvidenceStore._recover: anything it cannot positively verify is a problem.
    public static class StoreScan {
        public const string Schema = "maker_evidence_v2";
        public const long MaxRawBytes = 500000000;
        public const int MaxPaths = 20000;
        public const int MaxLineBytes = 16 * 1024 * 1024;
        // Upper bound of the manifest _seal writes for an interrupted segment (it is accounted with
        // reserve=False): per journal, the name at 6 bytes per UTF-16 unit (worst JSON escape) plus
        // the stats object with every number at 24 digits; per segment, the top-level fields.
        public const long ManifestBytesPerJournal = 400;
        public const long ManifestBytesPerNameUnit = 6;
        public const long ManifestBytesPerSegment = 1024;
        // A stream response_bytes wider than this cannot be bounded in the manifest: unknown.
        public const int MaxResponseBytesDigits = 12;
        static readonly Regex SegmentName = new Regex(@"^\d{2}-[0-9a-f]{12}$");
        static readonly Regex DayName = new Regex(@"^\d{4}-\d{2}-\d{2}$");

        static bool IsReparse(FileSystemInfo item) { return (item.Attributes & FileAttributes.ReparsePoint) != 0; }

        static FileStream OpenShared(string path) {
            return new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        }

        public static ScanResult Scan(string root, int maxSegments, int settleMs) {
            var r = new ScanResult();
            var unsealed = new List<DirectoryInfo>();
            long raw = 0, sealBound = 0; int paths = 0;
            foreach (var parent in new DirectoryInfo(root).GetDirectories()) {
                if (IsReparse(parent)) { r.Errors.Add("store folder is a reparse point: " + parent.FullName); continue; }
                DirectoryInfo[] folders;
                try {
                    foreach (var f in parent.GetFiles())
                        if (f.Name.StartsWith("manifest.jsonl", StringComparison.OrdinalIgnoreCase))
                            r.Errors.Add("legacy daily journal (recovery refuses the root): " + f.FullName);
                    folders = parent.GetDirectories();
                }
                catch (Exception e) { r.Errors.Add(parent.FullName + ": " + e.Message); continue; }
                foreach (var folder in folders) {
                    if (folder.Name.StartsWith("manifest.jsonl", StringComparison.OrdinalIgnoreCase))
                        r.Errors.Add("legacy daily journal (recovery refuses the root): " + folder.FullName);
                    if (IsReparse(folder)) { r.Errors.Add("folder is a reparse point: " + folder.FullName); continue; }
                    FileInfo[] files; DirectoryInfo[] subfolders;
                    try { files = folder.GetFiles(); subfolders = folder.GetDirectories(); }
                    catch (Exception e) { r.Errors.Add(folder.FullName + ": " + e.Message); continue; }
                    FileInfo manifest = null, zipped = null;
                    long journalBound = 0;
                    foreach (var f in files) {
                        if (f.Name.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase)) {
                            paths++; raw += f.Length;
                            journalBound += ManifestBytesPerJournal + ManifestBytesPerNameUnit * f.Name.Length;
                        }
                        else if (string.Equals(f.Name, "manifest.json", StringComparison.OrdinalIgnoreCase)) { manifest = f; paths++; raw += f.Length; }
                        else if (string.Equals(f.Name, "manifest.json.gz", StringComparison.OrdinalIgnoreCase)) { zipped = f; }
                    }
                    bool manifestFolder = false;
                    foreach (var d in subfolders) {
                        if (d.Name.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase)) paths++;
                        if (string.Equals(d.Name, "manifest.json", StringComparison.OrdinalIgnoreCase) ||
                            string.Equals(d.Name, "manifest.json.gz", StringComparison.OrdinalIgnoreCase)) manifestFolder = true;
                    }
                    if (!SegmentName.IsMatch(folder.Name)) { continue; }
                    if (manifestFolder) { r.Invalid.Add(folder.FullName + ": a folder named like a manifest"); continue; }
                    if (manifest != null || zipped != null) {
                        var used = manifest ?? zipped;
                        if (IsReparse(used)) { r.Invalid.Add(used.FullName + ": reparse point"); continue; }
                        try {
                            string why = CheckManifest(used.FullName, manifest == null);
                            if (why != null) { r.Invalid.Add(used.FullName + ": " + why); }
                        }
                        catch (Exception e) { r.Invalid.Add(used.FullName + ": " + e.Message); }
                        continue;
                    }
                    if (unsealed.Count >= maxSegments) {
                        r.Errors.Add("more than " + maxSegments + " unsealed segments; only the first " + maxSegments + " scanned");
                        return r;
                    }
                    unsealed.Add(folder);
                    r.Unsealed.Add(folder.FullName);
                    sealBound += ManifestBytesPerSegment + journalBound;
                    foreach (var d in subfolders)
                        if (d.Name.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase)) r.Invalid.Add(d.FullName + ": a folder named like a journal");
                }
            }
            // _recover refuses at startup over the bound, and _seal of each interrupted segment
            // refuses when its manifest would reach it (_account(size, reserve=False)).
            if (paths > MaxPaths || raw >= MaxRawBytes || raw + sealBound >= MaxRawBytes) {
                r.Errors.Add("uncompressed footprint at or near the recovery bound: " + paths + " paths, " + raw +
                    " bytes, up to " + sealBound + " bytes of manifests to seal");
            }

            // The live writer's own segment: the single newest unsealed one in a UTC day folder.
            DirectoryInfo live = null; bool tie = false;
            foreach (var folder in unsealed) {
                if (!DayName.IsMatch(folder.Parent.Name)) continue;
                if (live == null) { live = folder; continue; }
                int c = string.CompareOrdinal(Key(folder), Key(live));
                if (c > 0) { live = folder; tie = false; } else if (c == 0) { tie = true; }
            }
            if (tie) live = null;
            r.LiveSegment = live == null ? null : live.FullName;

            var pending = new List<KeyValuePair<FileInfo, long>>();
            foreach (var folder in unsealed) {
                FileInfo[] journals;
                try { journals = folder.GetFiles("*.jsonl"); }
                catch (Exception e) { r.Errors.Add(folder.FullName + ": " + e.Message); continue; }
                foreach (var f in journals) {
                    if (!f.Name.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase)) continue;
                    if (IsReparse(f)) { r.Errors.Add("journal is a reparse point: " + f.FullName); continue; }
                    try {
                        bool torn; long length;
                        string why = CheckJournal(f.FullName, out torn, out length);
                        if (why != null) r.Invalid.Add(f.FullName + ": " + why);
                        else if (torn && live != null && folder.FullName == live.FullName) pending.Add(new KeyValuePair<FileInfo, long>(f, length));
                        else if (torn) r.Torn.Add(f.FullName);
                    }
                    catch (Exception e) { r.Errors.Add(f.FullName + ": " + e.Message); }
                }
            }
            // A partial last line in the live segment is the writer's only while it is moving: a tail
            // still the same length after the settle wait is torn (a crash-looping recorder, or a
            // lock held by something else).
            if (pending.Count > 0) {
                Thread.Sleep(settleMs);
                foreach (var item in pending) {
                    try {
                        bool torn; long length;
                        string why = CheckJournal(item.Key.FullName, out torn, out length);
                        if (why != null) r.Invalid.Add(item.Key.FullName + ": " + why);
                        else if (torn && length == item.Value) r.Torn.Add(item.Key.FullName);
                        else r.InFlight.Add(item.Key.FullName);
                    }
                    catch (Exception e) { r.Errors.Add(item.Key.FullName + ": " + e.Message); }
                }
            }
            return r;
        }

        static string Key(DirectoryInfo folder) { return folder.Parent.Name + "/" + folder.Name.Substring(0, 2); }

        static byte[] ReadAll(string path) {
            using (var file = OpenShared(path))
            using (var buffer = new MemoryStream()) { file.CopyTo(buffer); return buffer.ToArray(); }
        }

        static uint[] crcTable;

        static uint Crc32(byte[] data) {
            if (crcTable == null) {
                var table = new uint[256];
                for (uint n = 0; n < 256; n++) {
                    uint c = n;
                    for (int k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                    table[n] = c;
                }
                crcTable = table;
            }
            uint crc = 0xFFFFFFFFu;
            foreach (byte b in data) crc = crcTable[(crc ^ b) & 0xFF] ^ (crc >> 8);
            return crc ^ 0xFFFFFFFFu;
        }

        // One gzip member, verified end to end: the decompressed bytes must match the CRC32 and
        // ISIZE in the file's last 8 bytes, so trailing data, a second member or a missing footer
        // is a problem (stricter than Python's gzip, which can only turn clean into unknown).
        static string ReadGzip(string path, out byte[] data) {
            data = null;
            byte[] packed = ReadAll(path);
            if (packed.Length < 18 || packed[0] != 0x1f || packed[1] != 0x8b || packed[2] != 8) return "not a gzip member";
            using (var input = new MemoryStream(packed))
            using (var gz = new GZipStream(input, CompressionMode.Decompress))
            using (var output = new MemoryStream()) { gz.CopyTo(output); data = output.ToArray(); }
            uint crc = BitConverter.ToUInt32(packed, packed.Length - 8);
            uint size = BitConverter.ToUInt32(packed, packed.Length - 4);
            if (Crc32(data) != crc || (uint)data.LongLength != size)
                return "gzip footer does not match the data (trailing bytes, several members or truncated)";
            return null;
        }

        static string CheckManifest(string path, bool gz) {
            byte[] bytes;
            if (gz) {
                string bad = ReadGzip(path, out bytes);
                if (bad != null) return bad;
            }
            else bytes = ReadAll(path);
            var top = new Dictionary<string, Json.Value>();
            string why = Json.Check(bytes, 0, bytes.Length, top);
            if (why != null) return why;
            Json.Value v;
            if (!top.TryGetValue("schema_version", out v) || v.Kind != 's' || v.Text != Schema) return "schema_version is not " + Schema;
            if (!top.TryGetValue("stream_response_bytes", out v) || v.Kind != 'i') return "stream_response_bytes is not an integer";
            if (!top.TryGetValue("stream_capped", out v) || (v.Kind != 't' && v.Kind != 'f')) return "stream_capped is not a boolean";
            return null;
        }

        // null when every newline-terminated line is a recoverable record; torn when bytes follow the
        // last newline; length = bytes read.
        public static string CheckJournal(string path, out bool torn, out long length) {
            torn = false; length = 0;
            using (var file = OpenShared(path)) {
                var chunk = new byte[1 << 20];
                var line = new MemoryStream();
                long offset = 0; int n; bool oversized = false;
                while ((n = file.Read(chunk, 0, chunk.Length)) > 0) {
                    length += n;
                    if (oversized) {
                        // An oversized run is torn if no newline follows it, else an oversized record.
                        if (Array.IndexOf(chunk, (byte)10, 0, n) >= 0) return "oversized record at offset " + offset;
                        continue;
                    }
                    int start = 0;
                    for (int i = 0; i < n; i++) {
                        if (chunk[i] != 10) continue;
                        line.Write(chunk, start, i + 1 - start);
                        start = i + 1;
                        if (line.Length > MaxLineBytes) return "oversized record at offset " + offset;
                        string why = CheckRecord(line.GetBuffer(), (int)line.Length, offset);
                        if (why != null) return why + " at offset " + offset;
                        offset += line.Length;
                        line = new MemoryStream();
                    }
                    line.Write(chunk, start, n - start);
                    if (line.Length > MaxLineBytes) { oversized = true; line = new MemoryStream(); }
                }
                torn = oversized || line.Length > 0;
            }
            return null;
        }

        static string CheckRecord(byte[] bytes, int count, long offset) {
            var top = new Dictionary<string, Json.Value>();
            string why = Json.Check(bytes, 0, count, top);
            if (why != null) return why;
            Json.Value v;
            if (!top.TryGetValue("offset", out v) || v.Kind != 'i') return "offset is not an integer";
            long parsed;
            if (!long.TryParse(v.Text, out parsed) || parsed != offset) return "record offset mismatch";
            if (top.TryGetValue("kind", out v) && v.Kind == 's' && v.Text == "stream") {
                if (!top.TryGetValue("response_bytes", out v) || v.Kind != 'i') return "stream record without integer response_bytes";
                if (v.Text.TrimStart('-').Length > MaxResponseBytesDigits) return "stream response_bytes too wide to bound";
            }
            return null;
        }
    }

    // Strict RFC 8259 check of one UTF-8 document whose top level must be an object. Records the
    // top-level members (a duplicate name is a problem). Rejects what Python's json accepts beyond
    // the RFC (NaN, Infinity, a BOM), which can only turn a clean result into "unknown".
    public static class Json {
        public struct Value { public char Kind; public string Text; }
        static readonly UTF8Encoding Strict = new UTF8Encoding(false, true);

        public static string Check(byte[] bytes, int index, int count, Dictionary<string, Value> top) {
            string text;
            try { text = Strict.GetString(bytes, index, count); }
            catch (ArgumentException) { return "record is not valid UTF-8"; }
            int i = 0;
            try {
                Ws(text, ref i);
                if (i >= text.Length || text[i] != '{') return "record is not a JSON object";
                ParseObject(text, ref i, top, 0);
                Ws(text, ref i);
                if (i != text.Length) return "trailing bytes after the JSON record";
            }
            catch (FormatException e) { return "invalid JSON: " + e.Message; }
            return null;
        }

        static void Ws(string t, ref int i) { while (i < t.Length && (t[i] == ' ' || t[i] == '\t' || t[i] == '\n' || t[i] == '\r')) i++; }

        static Value ParseValue(string t, ref int i, int depth) {
            if (depth > 512) throw new FormatException("nesting too deep");
            Ws(t, ref i);
            if (i >= t.Length) throw new FormatException("unexpected end");
            char c = t[i];
            var v = new Value();
            if (c == '{') { ParseObject(t, ref i, null, depth + 1); v.Kind = 'o'; }
            else if (c == '[') {
                i++; Ws(t, ref i);
                if (i < t.Length && t[i] == ']') { i++; }
                else {
                    while (true) {
                        ParseValue(t, ref i, depth + 1); Ws(t, ref i);
                        if (i < t.Length && t[i] == ',') { i++; continue; }
                        if (i < t.Length && t[i] == ']') { i++; break; }
                        throw new FormatException("bad array");
                    }
                }
                v.Kind = 'a';
            }
            else if (c == '"') { v.Text = ParseString(t, ref i); v.Kind = 's'; }
            else if (Lit(t, ref i, "true")) v.Kind = 't';
            else if (Lit(t, ref i, "false")) v.Kind = 'f';
            else if (Lit(t, ref i, "null")) v.Kind = 'n';
            else { v.Text = ParseNumber(t, ref i, out v.Kind); }
            return v;
        }

        static bool Lit(string t, ref int i, string word) {
            if (string.CompareOrdinal(t, i, word, 0, word.Length) != 0) return false;
            i += word.Length; return true;
        }

        static void ParseObject(string t, ref int i, Dictionary<string, Value> members, int depth) {
            if (depth > 512) throw new FormatException("nesting too deep");
            i++; Ws(t, ref i);
            var seen = new HashSet<string>(StringComparer.Ordinal);
            if (i < t.Length && t[i] == '}') { i++; return; }
            while (true) {
                Ws(t, ref i);
                if (i >= t.Length || t[i] != '"') throw new FormatException("bad object key");
                string name = ParseString(t, ref i);
                Ws(t, ref i);
                if (i >= t.Length || t[i] != ':') throw new FormatException("missing colon");
                i++;
                var value = ParseValue(t, ref i, depth + 1);
                if (members != null) {
                    if (!seen.Add(name)) throw new FormatException("duplicate top-level name " + name);
                    members[name] = value;
                }
                Ws(t, ref i);
                if (i < t.Length && t[i] == ',') { i++; continue; }
                if (i < t.Length && t[i] == '}') { i++; return; }
                throw new FormatException("bad object");
            }
        }

        static string ParseString(string t, ref int i) {
            i++;
            var sb = new StringBuilder();
            while (true) {
                if (i >= t.Length) throw new FormatException("unterminated string");
                char c = t[i++];
                if (c == '"') return sb.ToString();
                if (c < 0x20) throw new FormatException("control character in string");
                if (c != '\\') { sb.Append(c); continue; }
                if (i >= t.Length) throw new FormatException("bad escape");
                char e = t[i++];
                switch (e) {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 > t.Length) throw new FormatException("bad unicode escape");
                        int code = 0;
                        for (int k = 0; k < 4; k++) {
                            if (!Uri.IsHexDigit(t[i + k])) throw new FormatException("bad unicode escape");
                            code = code * 16 + Uri.FromHex(t[i + k]);
                        }
                        i += 4; sb.Append((char)code); break;
                    default: throw new FormatException("bad escape");
                }
            }
        }

        static string ParseNumber(string t, ref int i, out char kind) {
            int start = i; kind = 'i';
            if (i < t.Length && t[i] == '-') i++;
            if (i >= t.Length || t[i] < '0' || t[i] > '9') throw new FormatException("bad value");
            if (t[i] == '0') i++; else while (i < t.Length && t[i] >= '0' && t[i] <= '9') i++;
            int digits = i - start - (t[start] == '-' ? 1 : 0);
            if (i < t.Length && t[i] == '.') {
                i++; kind = 'd';
                if (i >= t.Length || t[i] < '0' || t[i] > '9') throw new FormatException("bad fraction");
                while (i < t.Length && t[i] >= '0' && t[i] <= '9') i++;
            }
            if (i < t.Length && (t[i] == 'e' || t[i] == 'E')) {
                i++; kind = 'd';
                if (i < t.Length && (t[i] == '+' || t[i] == '-')) i++;
                if (i >= t.Length || t[i] < '0' || t[i] > '9') throw new FormatException("bad exponent");
                while (i < t.Length && t[i] >= '0' && t[i] <= '9') i++;
            }
            // Python 3.11+ int() refuses more than 4300 digits, so json.loads raises.
            if (kind == 'i' && digits > 4300) throw new FormatException("integer longer than 4300 digits");
            return t.Substring(start, i - start);
        }
    }
}
'@
    }
}

function Get-Capped($List) { return @($List.GetRange(0, [Math]::Min(20, $List.Count)).ToArray()) }

function Finish-WriterAlive([string]$Reason) {
    # Writer alive (a recorder process, or a held lock): nothing may move. First a read-only
    # mirror of EvidenceStore._recover over the whole store, shared opens, no write: every unsealed
    # segment is checked record by record (UTF-8, strict JSON object, offset chain, line bound,
    # stream response_bytes), every sealed manifest's schema, and the footprint bound. The one
    # exception is the live writer's own segment (the single newest unsealed one): a partial last
    # line there passes only if the file moves during a 2 s settle wait. A torn tail anywhere else,
    # or a still one, is REFUSED_WRITER_ALIVE_TORN, exit 3, even when other files failed.
    # torn_tail_found is $false only when everything was positively verified; $null (unknown) on
    # any read error, unverifiable record, or more than 64 unsealed segments. Unattended callers may
    # treat exit 2 as benign only with torn_tail_found false.
    $script:result.torn_tail_found = $null
    $script:result.torn_tail_scan = "unknown"
    try {
        Get-StoreScanType
        $scan = [WeatherTornQuarantine.StoreScan]::Scan($Root, 64, 2000)
        $problems = New-Object 'System.Collections.Generic.List[string]'
        foreach ($item in $scan.Errors) { $problems.Add($item) }
        foreach ($item in $scan.Invalid) { $problems.Add($item) }
        $script:result.unsealed_segment_count = $scan.Unsealed.Count
        $script:result.unsealed_segments = @(Get-Capped $scan.Unsealed)
        $script:result.live_segment = $scan.LiveSegment
        if ($scan.InFlight.Count -gt 0) { $script:result.in_flight_journals = @(Get-Capped $scan.InFlight) }
        if ($problems.Count -gt 0) {
            $script:result.torn_tail_scan_problem_count = $problems.Count
            $script:result.torn_tail_scan_problems = @(Get-Capped $problems)
        }
        if ($scan.Torn.Count -gt 0) {
            $script:result.torn_tail_found = $true
            $script:result.torn_tail_scan = $(if ($problems.Count -gt 0) { "partial: " + $problems[0] } else { "complete" })
            $script:result.torn_journal_count = $scan.Torn.Count
            $script:result.torn_journals = @(Get-Capped $scan.Torn)
            Finish "REFUSED_WRITER_ALIVE_TORN" 3 ($Reason + "; an unsealed segment the writer is not writing has a torn tail")
        }
        if ($problems.Count -gt 0) { $script:result.torn_tail_scan = "unknown: " + $problems[0] }
        else {
            $script:result.torn_tail_found = $false
            $script:result.torn_tail_scan = "complete"
        }
    }
    catch { $script:result.torn_tail_scan = "unknown: " + $_.Exception.Message }
    Finish "REFUSED_WRITER_ALIVE" 2 $Reason
}

function Get-IntentProblem($Intent, [string]$Segment, [string]$Destination) {
    # "" when the intent is well-formed and belongs to exactly this root/segment/destination.
    if ([string]$Intent.root -ine $Root) { return "intent root differs from this run" }
    if ([string]$Intent.segment -ine $Segment) { return "intent names another segment" }
    if ([string]$Intent.destination -ine $Destination) { return "intent destination differs from this run" }
    $seen = @{}
    foreach ($file in @($Intent.files)) {
        $name = [string]$file.name
        if (-not (Test-JournalName $name) -or $name -ne [IO.Path]::GetFileName($name) -or
            $name.IndexOfAny([char[]]'\/:') -ge 0 -or $name.Contains("..")) { return "intent names an invalid journal: $name" }
        if ($seen.ContainsKey($name.ToLowerInvariant())) { return "intent repeats $name" }
        $seen[$name.ToLowerInvariant()] = $true
        if ([string]$file.sha256_before -cnotmatch '^[0-9a-f]{64}$') { return "intent hash is not a sha256: $name" }
        $size = $file.size
        if ($null -eq $size -or -not ($size -is [int] -or $size -is [long]) -or [int64]$size -lt 0) { return "intent size is not a non-negative integer: $name" }
        if (@("nul_tail", "no_final_newline") -cnotcontains [string]$file.tail) { return "intent tail class is unknown: $name" }
    }
    if ($seen.Count -eq 0 -or $seen.Count -gt 10) { return "intent file count is outside 1..10" }
    return ""
}

try {
    $script:result.script_sha256 = Get-Sha256 $PSCommandPath
    if (-not $RepoRoot) {
        $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
    }
    $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
    if (-not $Root) {
        $Root = Join-Path $RepoRoot "data\maker_evidence"
        if (-not $QuarantineRoot) { $QuarantineRoot = Join-Path $RepoRoot "data\maker_evidence_quarantine" }
        if (-not $PSBoundParameters.ContainsKey("TaskName")) { $TaskName = "WeatherMakerEvidenceCapture" }
    }
    if (-not $LogPath) { $LogPath = Join-Path $RepoRoot "data\alerts\maker_evidence_torn_quarantine.jsonl" }
    $script:result.task_name = $TaskName

    # ---- inputs ----
    if (-not $QuarantineRoot) { Finish "REFUSED_NO_QUARANTINE_ROOT" 2 "an explicit -Root requires an explicit -QuarantineRoot" }
    $Root = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $QuarantineRoot = [IO.Path]::GetFullPath($QuarantineRoot).TrimEnd('\')
    $script:result.root = $Root; $script:result.quarantine_root = $QuarantineRoot
    if ($QuarantineRoot.StartsWith($Root + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $Root.StartsWith($QuarantineRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $Root -ieq $QuarantineRoot) {
        Finish "REFUSED_QUARANTINE_OVERLAPS_ROOT" 2 "quarantine root must be outside the store root and vice versa"
    }
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { Finish "NOOP_NO_ROOT" 0 }
    if ([IO.Path]::GetPathRoot($Root) -ine [IO.Path]::GetPathRoot($QuarantineRoot)) {
        Finish "REFUSED_CROSS_VOLUME" 2 "quarantine root has another path root; rename-only design"
    }
    if ((Test-ReparseChain $Root) -or (Test-ReparseChain $QuarantineRoot)) {
        Finish "REFUSED_REPARSE_POINT" 2 "a reparse point in the root or quarantine path could hide a cross-volume move"
    }
    $rootVolume = Get-VolumeIdentity $Root
    $quarantineVolume = Get-VolumeIdentity $QuarantineRoot
    if (-not $rootVolume -or $rootVolume -ne $quarantineVolume) {
        Finish "REFUSED_CROSS_VOLUME" 2 ("volume identity differs or is unreadable: '{0}' vs '{1}'" -f $rootVolume, $quarantineVolume)
    }

    # ---- advisory process check (the lock below is authoritative) ----
    try { $processes = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'") }
    catch { Finish "REFUSED_PROCESS_CHECK_FAILED" 2 $_.Exception.Message }
    $writers = @($processes | Where-Object {
        $line = [string]$_.CommandLine
        if ($line -notmatch 'weather\.market\.maker_evidence_capture' -or $line -match '--dry-run') { return $false }
        if ($line -match '--root\s+"([^"]+)"' -or $line -match '--root\s+(\S+)') {
            return ([IO.Path]::GetFullPath($Matches[1]).TrimEnd('\') -ieq $Root)
        }
        return $true   # implicit root: cannot prove it is a different store
    })
    if ($writers.Count -gt 0) {
        Finish-WriterAlive ("recorder process running: pid " + (($writers | ForEach-Object { $_.ProcessId }) -join ","))
    }

    # ---- writer lock (authoritative) ----
    $lockPath = Join-Path $Root ".writer.lock"
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) { Finish "NOOP_NO_LOCK_FILE" 0 "the recorder never ran on this root" }
    try {
        $script:lockStream = New-Object IO.FileStream($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite,
            ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        $script:lockStream.Lock(0, 1)
    }
    catch {
        Release-Lock
        # Only a sharing or lock violation means a writer; ACL or I/O failures are their own refusal.
        $failure = $_.Exception
        while ($null -ne $failure.InnerException -and -not ($failure -is [IO.IOException])) { $failure = $failure.InnerException }
        $win32 = $failure.HResult -band 0xFFFF
        if ($failure -is [IO.IOException] -and ($win32 -eq 32 -or $win32 -eq 33)) {
            Finish-WriterAlive ("writer lock is held: " + $failure.Message)
        }
        Finish "REFUSED_LOCK_UNAVAILABLE" 2 ("cannot open or lock .writer.lock (not a sharing or lock violation): " + $failure.Message)
    }

    # ---- store layout: reparse guard and unsealed segments (EvidenceStore._recover's rule) ----
    $unsealed = @()
    foreach ($parent in @(Get-ChildItem -LiteralPath $Root -Directory -Force)) {
        if (Test-Reparse $parent) { Finish "REFUSED_REPARSE_POINT" 2 ("store folder is a reparse point: " + $parent.Name) }
        foreach ($folder in @(Get-ChildItem -LiteralPath $parent.FullName -Directory -Force)) {
            if ($folder.Name -cnotmatch '^\d{2}-[0-9a-f]{12}$') { continue }
            if (Test-Reparse $folder) { Finish "REFUSED_REPARSE_POINT" 2 ("segment folder is a reparse point: " + $folder.FullName) }
            if ((Test-Path -LiteralPath (Join-Path $folder.FullName "manifest.json")) -or
                (Test-Path -LiteralPath (Join-Path $folder.FullName "manifest.json.gz"))) { continue }
            $unsealed += $folder
        }
    }

    # ---- intents whose receipt failed and whose segment the store has since sealed ----
    $afterSeal = @()
    if (Test-Path -LiteralPath $QuarantineRoot) {
        foreach ($dayDir in @(Get-ChildItem -LiteralPath $QuarantineRoot -Directory -Force)) {
            if ($dayDir.Name -cnotmatch '^\d{4}-\d{2}-\d{2}$') { continue }
            foreach ($segDir in @(Get-ChildItem -LiteralPath $dayDir.FullName -Directory -Force)) {
                if ($segDir.Name -cnotmatch '^\d{2}-[0-9a-f]{12}$') { continue }
                $intentFile = Join-Path $segDir.FullName "QUARANTINE_INTENT.json"
                if (-not (Test-Path -LiteralPath $intentFile) -or
                    (Test-Path -LiteralPath (Join-Path $segDir.FullName "QUARANTINE_RECEIPT.json"))) { continue }
                $source = Join-Path (Join-Path $Root $dayDir.Name) $segDir.Name
                $sealed = (Test-Path -LiteralPath (Join-Path $source "manifest.json")) -or
                          (Test-Path -LiteralPath (Join-Path $source "manifest.json.gz"))
                if (-not (Test-Path -LiteralPath $source)) {
                    Finish "UNRESOLVED" 5 ("an intent has no receipt and its source segment is gone: " + $intentFile)
                }
                if ($sealed) { $afterSeal += [pscustomobject]@{ intent = $intentFile; source = $source; destination = $segDir.FullName } }
            }
        }
    }
    if ($afterSeal.Count -gt 0) {
        $script:result.after_seal = @()
        foreach ($item in $afterSeal) {
            if (Test-ReparseChain $item.destination) { Finish "REFUSED_REPARSE_POINT" 2 ("quarantine folder is a reparse point: " + $item.destination) }
            $intent = $null
            try { $intent = Read-JsonFile $item.intent } catch { Finish "REFUSED_INTENT_INVALID" 2 ("intent unreadable: " + $item.intent) }
            $problem = Get-IntentProblem $intent $item.source $item.destination
            if ($problem) { Finish "REFUSED_INTENT_INVALID" 2 ($problem + ": " + $item.intent) }
            $files = @()
            foreach ($entry in @($intent.files)) {
                $src = Join-Path $item.source $entry.name
                $dst = Join-Path $item.destination $entry.name
                if ((Test-Path -LiteralPath $src) -or -not (Test-Path -LiteralPath $dst)) {
                    Finish "UNRESOLVED" 5 ("sealed segment but planned journal is not only at the quarantine: " + $entry.name)
                }
                $after = Get-ShaChecked $dst $true
                if ($after -ne [string]$entry.sha256_before) { Finish "UNRESOLVED" 5 ("quarantined bytes differ from the intent: " + $entry.name) }
                $files += [pscustomobject][ordered]@{ name = [string]$entry.name; size = [int64]$entry.size; tail = [string]$entry.tail
                    sha256_before = [string]$entry.sha256_before; sha256_after = $after; source = $src; destination = $dst }
            }
            $script:result.after_seal += [pscustomobject]@{ segment = $item.source; destination = $item.destination; files = $files }
        }
        if (-not $Apply) { Finish "REPORT_AFTER_SEAL" 0 "moves completed but the receipt is missing and the store has sealed the segment; rerun with -Apply to write the receipt" }
        foreach ($record in $script:result.after_seal) {
            try {
                Write-AtomicNew (Join-Path $record.destination "QUARANTINE_RECEIPT.json") ([ordered]@{
                    schema = "maker_evidence_torn_quarantine_receipt_v1"
                    completed_at_utc = (Get-Date).ToUniversalTime().ToString("o"); script_sha256 = $script:result.script_sha256
                    host = $env:COMPUTERNAME; mode = "after_seal"; sealed_before_receipt = $true; writer_lock_held = $true
                    root = $Root; segment = $record.segment
                    reason = "torn journal tail after unclean shutdown; moved byte-exact; receipt completed after the store sealed the rest"
                    files = @($record.files) })
            }
            catch { Finish "FAILED_RECEIPT" 4 $_.Exception.Message }
        }
        Finish "RECONCILED_AFTER_SEAL" 0 "receipt written after the store sealed the segment; rerun for any other segment"
    }

    if ($unsealed.Count -eq 0) { Finish "NOOP_NO_UNSEALED_SEGMENT" 0 }
    if ($unsealed.Count -gt 1) {
        $script:result.segment = @($unsealed | ForEach-Object { $_.FullName })
        Finish "REFUSED_MULTIPLE_UNSEALED" 2 "more than one unsealed segment; the store never leaves two"
    }
    $segment = $unsealed[0]
    $day = $segment.Parent.Name
    $script:result.segment = $segment.FullName
    if ($day -cnotmatch '^\d{4}-\d{2}-\d{2}$') { Finish "REFUSED_UNEXPECTED_LAYOUT" 2 "unsealed segment parent is not a UTC day folder" }
    $destination = Join-Path (Join-Path $QuarantineRoot $day) $segment.Name
    if (Test-ReparseChain $destination) { Finish "REFUSED_REPARSE_POINT" 2 "a reparse point in the quarantine destination path" }
    $intentPath = Join-Path $destination "QUARANTINE_INTENT.json"
    $receiptPath = Join-Path $destination "QUARANTINE_RECEIPT.json"

    # ---- classify (same visibility as Python's glob('*.jsonl'): no dot files, case-insensitive) ----
    $candidates = @()
    $interior = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $segment.FullName -File -Force)) {
        if (-not (Test-JournalName $file.Name)) { continue }
        if (Test-Reparse $file) { Finish "REFUSED_REPARSE_POINT" 2 ("journal is a reparse point: " + $file.Name) }
        $tail = Get-TailClass $file.FullName
        if ($null -ne $tail) {
            $candidates += [ordered]@{ name = $file.Name; size = $file.Length; tail = $tail.tail
                nul_tail_bytes = $tail.nul_tail_bytes; nul_tail_scan_capped = $tail.nul_tail_scan_capped }
        }
        elseif ($file.Length -gt 0 -and (Test-ContainsNul $file.FullName)) { $interior += $file.Name }
    }
    $script:result.candidates = @($candidates | ForEach-Object { [pscustomobject]$_ })
    if ($interior.Count -gt 0) {
        $script:result.interior_nul_journals = $interior
        Finish "UNRESOLVED" 5 "a newline-terminated journal contains NUL bytes; moving tails cannot let the store recover"
    }

    $intent = $null
    if (Test-Path -LiteralPath $receiptPath) {
        try {
            $completed = (Read-JsonFile $receiptPath).completed_at_utc
            if ($completed -is [datetime]) { $script:receiptTime = $completed.ToUniversalTime() }
            else {
                $script:receiptTime = [DateTimeOffset]::Parse([string]$completed, [Globalization.CultureInfo]::InvariantCulture,
                    [Globalization.DateTimeStyles]::AssumeUniversal).UtcDateTime
            }
        }
        catch { Finish "REFUSED_RECEIPT_UNREADABLE" 2 $_.Exception.Message }
        if ($candidates.Count -eq 0) { Finish "NOOP_ALREADY_QUARANTINED" 0 }
        Finish "REFUSED_RECEIPT_EXISTS" 2 "a receipt exists for this segment but torn journals remain"
    }
    if (Test-Path -LiteralPath $intentPath) {
        try { $intent = Read-JsonFile $intentPath } catch { Finish "REFUSED_INTENT_INVALID" 2 ("intent unreadable: " + $_.Exception.Message) }
        $problem = Get-IntentProblem $intent $segment.FullName $destination
        if ($problem) { Finish "REFUSED_INTENT_INVALID" 2 $problem }
    }
    if ($null -eq $intent -and $candidates.Count -eq 0) { Finish "NOOP_NO_TORN_TAIL" 0 }
    if ($candidates.Count -gt $MaxFiles) { Finish "REFUSED_CAP" 2 ("{0} torn journals exceed the cap of {1}" -f $candidates.Count, $MaxFiles) }

    # ---- plan (fresh or from intent) ----
    if ($null -ne $intent) {
        $plan = @($intent.files | ForEach-Object { [ordered]@{ name = [string]$_.name; size = [int64]$_.size
            sha256_before = [string]$_.sha256_before; tail = [string]$_.tail } })
        $planned = @($plan | ForEach-Object { $_.name.ToLowerInvariant() })
        foreach ($candidate in $candidates) {
            if ($planned -notcontains $candidate.name.ToLowerInvariant()) { Finish "REFUSED_RECONCILE_MISMATCH" 2 ("torn journal not in intent: " + $candidate.name) }
        }
        $mode = "reconcile"
    }
    else {
        $plan = @()
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath (Join-Path $destination $candidate.name)) {
                Finish "REFUSED_DESTINATION_EXISTS" 2 ("quarantine already holds " + $candidate.name)
            }
            $plan += [ordered]@{ name = $candidate.name; size = $candidate.size
                sha256_before = (Get-ShaChecked (Join-Path $segment.FullName $candidate.name) $false); tail = $candidate.tail }
        }
        $mode = "fresh"
    }
    # Every plan entry must be in exactly one place with the planned hash before any mutation.
    $pending = @()
    foreach ($entry in $plan) {
        $src = Join-Path $segment.FullName $entry.name
        $dst = Join-Path $destination $entry.name
        $atSrc = Test-Path -LiteralPath $src; $atDst = Test-Path -LiteralPath $dst
        if ($atSrc -and $atDst) { Finish "REFUSED_RECONCILE_MISMATCH" 2 ("present at source and destination: " + $entry.name) }
        if (-not $atSrc -and -not $atDst) { Finish "UNRESOLVED" 5 ("missing from source and destination: " + $entry.name) }
        $path = $src; if ($atDst) { $path = $dst }
        if ((Get-ShaChecked $path ($mode -eq "reconcile")) -ne $entry.sha256_before) { Finish "UNRESOLVED" 5 ("bytes differ from the plan: " + $entry.name) }
        if ($atSrc) { $pending += $entry }
    }
    $script:result.mode = $mode
    $script:result.plan = @($plan | ForEach-Object { [pscustomobject]$_ })
    if (-not $Apply) { Finish "REPORT" 0 "report only; rerun with -Apply to quarantine" }

    # ---- apply ----
    try {
        if (-not (Test-Path -LiteralPath $destination)) { New-Item -ItemType Directory -Path $destination -Force | Out-Null }
        if ($mode -eq "fresh") {
            Write-AtomicNew $intentPath ([ordered]@{ schema = "maker_evidence_torn_quarantine_intent_v1"
                created_at_utc = (Get-Date).ToUniversalTime().ToString("o"); script_sha256 = $script:result.script_sha256
                root = $Root; segment = $segment.FullName; destination = $destination
                files = @($plan | ForEach-Object { [pscustomobject]$_ }) })
        }
    }
    catch { Finish "FAILED_INTENT" 4 $_.Exception.Message }
    foreach ($entry in $pending) {
        $src = Join-Path $segment.FullName $entry.name
        $dst = Join-Path $destination $entry.name
        try { [IO.File]::Move($src, $dst) }
        catch { Finish "FAILED_MOVE" 4 ("move failed for {0}: {1}; intent kept, rerun reconciles" -f $entry.name, $_.Exception.Message) }
    }
    $files = @()
    foreach ($entry in $plan) {
        $dst = Join-Path $destination $entry.name
        $after = Get-ShaChecked $dst $true
        if ($after -ne $entry.sha256_before) { Finish "FAILED_HASH_MISMATCH" 4 ("hash changed across move: " + $entry.name) }
        $files += [pscustomobject][ordered]@{ name = $entry.name; size = $entry.size; tail = $entry.tail
            sha256_before = $entry.sha256_before; sha256_after = $after
            source = (Join-Path $segment.FullName $entry.name); destination = $dst }
    }
    try {
        Write-AtomicNew $receiptPath ([ordered]@{ schema = "maker_evidence_torn_quarantine_receipt_v1"
            completed_at_utc = (Get-Date).ToUniversalTime().ToString("o"); script_sha256 = $script:result.script_sha256
            host = $env:COMPUTERNAME; mode = $mode; sealed_before_receipt = $false; writer_lock_held = $true
            root = $Root; segment = $segment.FullName
            reason = "torn journal tail after unclean shutdown; moved byte-exact, never truncated or rewritten"
            files = $files })
    }
    catch { Finish "FAILED_RECEIPT" 4 ($_.Exception.Message + "; moves are complete, rerun writes the receipt") }
    $script:result.receipt = $receiptPath
    $status = "QUARANTINED"; if ($mode -eq "reconcile") { $status = "RECONCILED" }
    Finish $status 0 "start the recorder task; the store seals the remaining journals"
}
catch {
    $script:result.status = "INTERNAL_ERROR"
    $script:result.reasons += ("unexpected error at line {0}: {1}" -f $_.InvocationInfo.ScriptLineNumber, $_.Exception.Message)
    try { Emit-And-Exit 6 } catch { Release-Lock; exit 6 }
}
finally { Release-Lock }
