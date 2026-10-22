function Build-Venv($vpy, $root) {
  Select-String -LiteralPath "$R\lock-hashed.txt" -Pattern '^(pip|setuptools|wheel)==' | ForEach-Object Line | Set-Content "$R\lock-tools-hashed.txt" -Encoding ascii
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-tools-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tools install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-hashed.txt";       if ($LASTEXITCODE) { NoGo 'lock install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --no-deps -e $root;                                    if ($LASTEXITCODE) { NoGo 'editable install' }
}
