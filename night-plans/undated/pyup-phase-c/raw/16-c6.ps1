Test-Venv $Py $P 'prod'      # includes the import-location check: weather and maker_core must import from $P\src
foreach ($ln in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $P "venv\Scripts\$ln")) -ne $K.binaries."Lib\venv\scripts\nt\$ln") { NoGo "launcher $ln -> ROLLBACK" } }
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$N\pth-3119.txt" -Encoding utf8     # receipt only; the import-location check is the pass rule
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'tree dirty -> ROLLBACK' }
