# Record that the OWNER reset the host, so the next UNEXPECTED SHUTDOWN flag is annotated.
#
#   .\scripts\ops\owner_reset_note.ps1 -At "2026-10-07 13:05" -Note "manual reset, screen frozen"
#
# Windows cannot tell an owner's manual reset from a crash or power loss: both leave the same
# unclean-boot record (Kernel-Power 41). Owner fact 2026-10-07: every host reset in the prior
# 30 days was the owner's own. This appends one owner marker to the dated, append-only ledger
# data\alerts\owner_resets\owner_resets_<yyyy-MM>.jsonl (runtime state, never tracked).
#
# It ACKNOWLEDGES, it never suppresses: status.ps1 still raises UNEXPECTED SHUTDOWN at its
# normal class and severity and only appends "- owner reset acknowledged <T> (<note>)" when
# -At falls inside the outage or at most 15 minutes before it. The capture grade for that day
# still needs checking. Writes nothing else; touches no scheduler, alert or capture state.
# See docs/ops/streak-soak.md#owner-reset-acknowledgement. Roll-free host tooling.
[CmdletBinding()]
param(
    # Local wall-clock time of the reset: "yyyy-MM-dd HH:mm" (or with seconds, or a 'T').
    [Parameter(Mandatory = $true)][string]$At,
    # One line, at most 200 characters, why/what (e.g. "manual reset, screen frozen").
    [Parameter(Mandatory = $true)][string]$Note,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$repo = [IO.Path]::GetFullPath($RepoRoot)
$invariant = [cultureinfo]::InvariantCulture

$formats = [string[]]@('yyyy-MM-dd HH:mm', 'yyyy-MM-dd HH:mm:ss', 'yyyy-MM-ddTHH:mm', 'yyyy-MM-ddTHH:mm:ss')
$when = [datetime]::MinValue
if (-not [datetime]::TryParseExact($At.Trim(), $formats, $invariant, [Globalization.DateTimeStyles]::None, [ref]$when)) {
    throw "-At must be local time as 'yyyy-MM-dd HH:mm' (got '$At')"
}
if ($when -gt (Get-Date).AddMinutes(1)) {
    throw "-At $($when.ToString('yyyy-MM-dd HH:mm', $invariant)) is in the future; record a reset after it happened"
}
$text = $Note.Trim()
if ($text.Length -eq 0) { throw "-Note must not be empty" }
if ($text.Length -gt 200) { throw "-Note must be at most 200 characters (got $($text.Length))" }
if ($text -match '[\x00-\x1F\x7F]') { throw "-Note must be a single line without control characters" }

$dir = Join-Path $repo "data\alerts\owner_resets"
if (-not (Test-Path -LiteralPath $dir -PathType Container)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
$ledger = Join-Path $dir ("owner_resets_{0}.jsonl" -f $when.ToString('yyyy-MM', $invariant))
$record = [ordered]@{
    schema      = "owner_reset_note_v1"
    at          = $when.ToString('yyyy-MM-ddTHH:mm:ss', $invariant)
    note        = $text
    recorded_at = (Get-Date).ToString('o')
    recorded_by = [string]$env:USERNAME
}
$line = ($record | ConvertTo-Json -Compress) + "`n"
$bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($line)
# Append-only: open for Append, never truncate or rewrite earlier markers.
$stream = New-Object System.IO.FileStream($ledger, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::Read)
try { $stream.Write($bytes, 0, $bytes.Length) }
finally { $stream.Dispose() }
Write-Output ("owner reset recorded: {0} ({1}) -> {2}" -f $record.at, $text, $ledger)
Write-Output "The UNEXPECTED SHUTDOWN flag still fires at its normal severity; verify that day's capture grade."
