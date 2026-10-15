<#
.SYNOPSIS
Parse-checks every ```powershell fence in the given Markdown files with the Windows PowerShell 5.1 parser.

.DESCRIPTION
Runbooks and night-plan blocks are pasted or saved as .ps1 on the production host, which runs Windows PowerShell 5.1.
A fence that does not parse there (for example `foreach (...) { ... } | Out-File`, since a statement cannot be piped)
fails only at run time, mid-procedure. This check is read-only: it never executes a fence, it only parses it.

It also flags non-ASCII characters in fences: a fence saved as a .ps1 without a UTF-8 BOM is decoded as ANSI by
PowerShell 5.1, and an em dash then becomes a smart quote that breaks parsing. Those are warnings, because pasting is
fine; save such blocks with a BOM (`Set-Content -Encoding utf8` writes one in 5.1).

Exit code: 0 when every fence parses, 1 when any fence has a parse error, 2 on bad input.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\check_markdown_powershell_fences.ps1 `
  -Path 'docs\operations\HOST_PYTHON_UPGRADE_RUNBOOK.md;night-plans'
#>
param(
    [Parameter(Mandatory = $true)][string[]]$Path
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) {
    Write-Warning "running on PowerShell $($PSVersionTable.PSVersion); the host parser is 5.1"
}

$files = @()
# `-File` invocations pass one string, so semicolons also separate paths.
foreach ($p in @($Path | ForEach-Object { $_ -split ';' } | Where-Object { $_ })) {
    if (Test-Path -LiteralPath $p -PathType Container) {
        $files += @(Get-ChildItem -LiteralPath $p -Recurse -File -Filter '*.md' | ForEach-Object FullName)
    } elseif (Test-Path -LiteralPath $p -PathType Leaf) {
        $files += (Resolve-Path -LiteralPath $p).Path
    } else {
        Write-Error "not found: $p" -ErrorAction Continue; exit 2
    }
}

$bad = 0; $fences = 0; $warn = 0
foreach ($f in $files) {
    $lines = [IO.File]::ReadAllLines($f, [Text.UTF8Encoding]::new($false))
    $in = $false; $start = 0; $buf = $null; $indent = ''
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $l = $lines[$i]
        if (-not $in) {
            if ($l -match '^(\s*)```\s*(powershell|ps1|pwsh)\s*$') {
                $in = $true; $start = $i + 1; $indent = $Matches[1]
                $buf = New-Object System.Collections.Generic.List[string]
            }
            continue
        }
        if ($l -match '^\s*```\s*$') {
            $in = $false; $fences++
            $text = $buf -join "`n"
            $tokens = $null; $errors = $null
            [void][System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
            foreach ($e in $errors) {
                $bad++
                "{0}:{1}: parse error (fence at line {2}): {3}" -f $f, ($start + $e.Extent.StartLineNumber), $start, $e.Message
            }
            $na = [regex]::Matches($text, '[^\x00-\x7F]')
            if ($na.Count) {
                $warn++
                # Re-read the fence the way 5.1 reads a BOM-less .ps1: UTF-8 bytes decoded as the ANSI code page.
                $ansi = [Text.Encoding]::Default.GetString([Text.Encoding]::UTF8.GetBytes($text))
                $aerr = $null
                [void][System.Management.Automation.Language.Parser]::ParseInput($ansi, [ref]$null, [ref]$aerr)
                $how = if ($aerr.Count) { "BREAKS when saved without a BOM ($($aerr[0].Message))" } else { 'parses either way' }
                "{0}:{1}: warning: fence holds {2} non-ASCII character(s) ({3}), {4}; save as .ps1 only with a UTF-8 BOM" -f `
                    $f, $start, $na.Count, ((@($na | ForEach-Object Value) | Select-Object -Unique) -join ' '), $how
            }
            continue
        }
        if ($indent -and $l.StartsWith($indent)) { $l = $l.Substring($indent.Length) }
        $buf.Add($l)
    }
    if ($in) { $bad++; "{0}:{1}: unterminated powershell fence" -f $f, $start }
}
"checked $fences powershell fence(s) in $($files.Count) file(s): $bad parse error(s), $warn non-ASCII warning(s)"
if ($bad) { exit 1 }
exit 0
