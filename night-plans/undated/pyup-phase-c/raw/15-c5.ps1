& $NewPy -I -m venv (Join-Path $P 'venv'); if ($LASTEXITCODE) { NoGo 'venv create -> ROLLBACK' }
Build-Venv $Py $P
