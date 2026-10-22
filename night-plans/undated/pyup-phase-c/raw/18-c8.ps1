# a) the workers run 3.11.9
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') {
  $v = (Get-Content -LiteralPath (Join-Path $P "data\snapshots\$f") -Raw | ConvertFrom-Json).runtime_identity.python_version
  Log "$f python_version=$v"; if ($v -ne '3.11.9') { NoGo "$f $v -> ROLLBACK" } }
# c) release readiness: still case A
$ra1 = Get-ReleaseActive $Py "$N\release-active-3119"; Assert-CaseA $ra1 'C8'
if ($ra1.status -ne $ra0.status -or $ra1.error -ne $ra0.error) { NoGo 'release active fields changed across the swap -> ROLLBACK' }
# d) host status
$st1 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-core"
$new1 = Get-NewStatusFlags "$N\status-core" "$R\c0-status-flags.txt" 'C8'   # judged below; aux flags are expected until C9b
# e) native-library receipt, old and new
$null = Invoke-Native $Py @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$N\native-3119"
