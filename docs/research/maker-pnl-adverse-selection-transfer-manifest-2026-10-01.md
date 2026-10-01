# Maker P&L adverse-selection study — transfer manifest, part 1 pilot (2026-10-01)

Status: frozen with the [pre-registration](maker-pnl-adverse-selection-preregistration-2026-10-01.md). It is the exact
input selection for the **part 1 pilot**; part 2 gets its own manifest after its read conditions hold. The production
agent runs the export below on the capture host and copies the result to the workstation by scp. Nothing goes through git.

## What is selected

All paths are relative to the production checkout's `data\` folder.

| # | Source | Selection | Why |
| --- | --- | --- | --- |
| 1 | `maker_evidence\<UTC-day>\<HH>-<12 hex>\` (88a) | UTC days **2026-09-25..2026-09-29**. Only **sealed** segments (`manifest.json` or `manifest.json.gz` present). Whole segment, **except** `updates-*.jsonl[.gz]` (raw L2 stream, not needed) and `*.tmp`. | Books (`books.jsonl` + `book-<asset>.jsonl`), public trades (`trades.jsonl`), reward terms (`reward-*.jsonl`), universe (`universe-<city>.jsonl`), and status events. Whole segments are needed because book parts and `payload_ref` resolve inside a segment. |
| 2 | `settlements\<market>\ledger.jsonl` | Only rows whose `target_date` is **2026-09-26..2026-09-29**, written to `settlements\<market>\ledger.2026-09-26_2026-09-29.jsonl` | Settlement marks (`polymarket_winning_band`). Rows for 2026-09-30 and later are never exported. |
| 3 | `manual_order_journal\<UTC-date>.jsonl` (110x) | Whole files for UTC dates **≤ 2026-09-29** | Owner-discretionary stratum, descriptive only. The chain must stay intact for `verify`. |

**Refusals (the script stops and exports nothing):**

- a selected path names a UTC day or `target_date` of 2026-09-30 or later;
- the 88a day folder for any selected date is missing;
- the export root already exists.

Unsealed segments are listed as skipped, never copied.

## Export (production, inside 00:30-09:00 while holding the shared lease)

The export copies several GiB, so treat it as heavy work under the
[host load policy](../operations/HOST_LOAD_POLICY.md). Run it serially and alone. First run it with `-DryRun`, which
prints counts and bytes and copies nothing. Check the total against free space before running it for real.

```powershell
param(
  [string]$Data = "C:\Users\Michael\Documents\github\weather\data",
  [string]$Out  = "C:\pt\maker-pnl-pilot-20261001",
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$days = "2026-09-25","2026-09-26","2026-09-27","2026-09-28","2026-09-29"
$events = "2026-09-26","2026-09-27","2026-09-28","2026-09-29"
$cut = "2026-09-30"
if (Test-Path $Out) { throw "export root exists: $Out" }
$plan = New-Object System.Collections.Generic.List[object]; $skipped = @()
foreach ($d in $days) {
  if ($d -ge $cut) { throw "refused: $d" }
  $dayDir = Join-Path $Data "maker_evidence\$d"
  if (-not (Test-Path $dayDir)) { throw "missing 88a day: $dayDir" }
  foreach ($seg in Get-ChildItem $dayDir -Directory) {
    $sealed = (Test-Path (Join-Path $seg.FullName "manifest.json")) -or (Test-Path (Join-Path $seg.FullName "manifest.json.gz"))
    if (-not $sealed) { $skipped += $seg.FullName; continue }
    foreach ($f in Get-ChildItem $seg.FullName -File) {
      if ($f.Name -like "updates-*" -or $f.Name -like "*.tmp") { continue }
      $plan.Add([pscustomobject]@{ Src = $f.FullName; Rel = "maker_evidence\$d\$($seg.Name)\$($f.Name)"; Bytes = $f.Length })
    }
  }
}
foreach ($f in Get-ChildItem (Join-Path $Data "manual_order_journal") -Filter "2026-09-*.jsonl" -File) {
  if ($f.BaseName -lt $cut) { $plan.Add([pscustomobject]@{ Src = $f.FullName; Rel = "manual_order_journal\$($f.Name)"; Bytes = $f.Length }) }
}
"88a+journal files: $($plan.Count)  bytes: $(($plan | Measure-Object Bytes -Sum).Sum)  unsealed skipped: $($skipped.Count)"
$skipped | ForEach-Object { "skipped unsealed: $_" }
if ($DryRun) { return }
foreach ($p in $plan) {
  $dst = Join-Path $Out $p.Rel; New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
  Copy-Item -LiteralPath $p.Src -Destination $dst
}
foreach ($ledger in Get-ChildItem (Join-Path $Data "settlements") -Filter "ledger.jsonl" -File -Recurse) {
  $market = $ledger.Directory.Name
  $rows = Get-Content -LiteralPath $ledger.FullName -Encoding UTF8 | Where-Object {
    $_.Trim() -and ($events -contains [string](($_ | ConvertFrom-Json).target_date)) }
  if ($rows) {
    $dst = Join-Path $Out "settlements\$market\ledger.2026-09-26_2026-09-29.jsonl"
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    [System.IO.File]::WriteAllLines($dst, [string[]]$rows, (New-Object System.Text.UTF8Encoding $false))
  }
}
Get-ChildItem $Out -Recurse -File | ForEach-Object {
  if ($_.FullName -match "20\d\d-(\d\d)-(\d\d)" -and "2026-$($Matches[1])-$($Matches[2])" -ge $cut -and $_.FullName -notmatch "2026-09-26_2026-09-29") {
    throw "refused after copy: $($_.FullName)" }
  "{0}  {1}  {2}" -f (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLower(), $_.Length, $_.FullName.Substring($Out.Length + 1)
} | Set-Content -Encoding ascii (Join-Path $Out "SHA256SUMS")
"SHA256SUMS: " + (Get-FileHash -Algorithm SHA256 (Join-Path $Out "SHA256SUMS")).Hash.ToLower()
```

## Copy to the workstation

```powershell
scp -r C:\pt\maker-pnl-pilot-20261001 <user>@<workstation>:C:/Users/Michael/Documents/github/weather/data/research/
```

Report back the `SHA256SUMS` hash line, the file count and the bytes. The workstation re-hashes every file against
`SHA256SUMS` before any read and refuses on a mismatch. Delete `C:\pt\maker-pnl-pilot-20261001` on production once the
workstation confirms. The originals are untouched: the export only copies.
