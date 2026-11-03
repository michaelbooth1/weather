# Evening-fix Stage 1 step (iii): master one-off 2026-11-03 direct run of stage1_score_v1.py (ce70e3e8).
# Usage: powershell -File run_score_oneoff.ps1 [-CheckOnly]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$root = 'C:\t\evening-fix-stage1'
$outer = Join-Path $root 'score-20261103'
$runDir = Join-Path $outer 'run'
$python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
$script = 'C:\wt\l16-efx-s1\scratch-transport\stage1_score_v1.py'
$src = Join-Path $root 'src_c32629156\src'
$commit = 'c32629156f0408a735923b1886b3fc31c59e6f44'
$replay = Join-Path $root 'evening-fix-20261102-replay\replay_c32629156_all.jsonl'
$ledger = Join-Path $root 'evening-fix-20261102\ledger_rows.jsonl'
$prereg = Join-Path $root 'gate\evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md'
$declog = Join-Path $root 'gate\DECISION_LOG.md'
$clar2 = 'C:\wt\l16-efx-s1\docs\research\evening-lockin-fix-scoring-clarification-2-2026-11-03.md'
$expect = @{
    script = 'ce70e3e8979b323e06c218da1eeef3b76561f3c4ea05ed096c57a6f79c52146d'
    replay = 'ff4478c3bf5493c82047bd6d0b539b9fbdd4ebb07eb004dba42d2a94c90db3ab'
    ledger = '69546a69190169d0b815b59034a2650ac5d9612f528a4b1d71028bd8fd529505'
    clar2  = '634823a7261c00abbf9a90c1863641a278ce59423fc38c600a785ee8bb5bbe79'
    prereg = '16ed20df6035fbc512b085757dae1d98d6ca5b3b1326fcdf44b0b33708e577ac'
}
function Sha($p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() }

$now = Get-Date
# Serial check: no workstation_heavy wrapper, no other python of ours, no row-28 process.
$procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match '^(python|pythonw|powershell|pwsh)\.exe$') -and $_.ProcessId -ne $PID -and (
        $_.CommandLine -match 'workstation_heavy|row.?28|row28|guarded_launcher|launcher_v|pytest|lockin_anchor_replay' -or
        $_.Name -match '^python')
}
$procList = @($procs | ForEach-Object { [ordered]@{ pid = $_.ProcessId; name = $_.Name; cmd = ($_.CommandLine -replace '\s+', ' ') } })
$os = Get-CimInstance Win32_OperatingSystem
$availGB = [math]::Round($os.FreePhysicalMemory * 1KB / 1GB, 2)
$perf = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
$commitPct = [math]::Round(100.0 * $perf.CommittedBytes / $perf.CommitLimit, 1)
$pre = [ordered]@{ checked_at = $now.ToString('o'); available_memory_gb = $availGB; commit_percent = $commitPct;
                   memory_ok = ($availGB -ge 6 -and $commitPct -le 90); other_processes = $procList }
$pre | ConvertTo-Json -Depth 5
if ($CheckOnly) { return }
if (-not $pre.memory_ok) { throw 'pre-check failed: memory' }
$heavy = @($procs | Where-Object { $_.CommandLine -match 'workstation_heavy|row.?28|guarded_launcher|launcher_v|pytest|lockin_anchor_replay' })
if ($heavy.Count -gt 0) { throw 'pre-check failed: workstation_heavy / row-28 / heavy process active (see list)' }
if (Test-Path $outer) { throw "exists: $outer" }

$shas = [ordered]@{ script = Sha $script; replay = Sha $replay; ledger = Sha $ledger; clar2 = Sha $clar2; prereg = Sha $prereg;
                    decision_log = Sha $declog }
foreach ($k in $expect.Keys) { if ($shas[$k] -ne $expect[$k]) { throw "sha mismatch: $k" } }
$argList = @('-I', '-B', $script, '--src', $src, '--commit', $commit, '--replay', $replay, '--ledger-rows', $ledger,
             '--prereg', $prereg, '--decision-log', $declog, '--out-dir', $runDir)
$cmdLine = '"' + $python + '" ' + (($argList | ForEach-Object { '"' + $_ + '"' }) -join ' ')
New-Item -ItemType Directory $outer | Out-Null
$receipt = [ordered]@{
    schema = 'evening_fix_stage1_score_prerun_receipt_v1'; written_at = (Get-Date).ToString('o')
    authority = 'Ran outside workstation_heavy under master one-off 2026-11-03 (scorer not on the offline list; 4 s, ~1.36 GB)'
    script_sha256 = $shas.script; code_commit = $commit
    c32629156_src_archive = [ordered]@{ git_archive_tar_sha256 = 'cc9e14de49b399521c9c5353d1b6476919cfcf53d11ca515eacadd83d30fce2e';
                                        src_tree = 'bac859f02a7d90f6be8d1bb1b7a773288155e5bb'; extracted_dir = $src; diff_vs_archive = 'IDENTICAL' }
    command_line = $cmdLine
    inputs = $shas
    pre_check = $pre
}
$receipt | ConvertTo-Json -Depth 6 | Out-File -FilePath (Join-Path $outer 'prerun_receipt.json') -Encoding utf8
$t0 = Get-Date
& $python @argList | Tee-Object -FilePath (Join-Path $outer 'run_stdout.json')
$rc = $LASTEXITCODE
"rc=$rc secs=$([math]::Round(((Get-Date) - $t0).TotalSeconds, 1)) ended=$((Get-Date).ToString('o'))"
