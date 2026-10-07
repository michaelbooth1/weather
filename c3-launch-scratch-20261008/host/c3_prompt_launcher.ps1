$ErrorActionPreference = "Stop"; Set-StrictMode -Version Latest
# M5: the #229 proof belongs HERE. The runner starts this launcher with stdin=subprocess.DEVNULL.
$stdinRedirected = [Console]::IsInputRedirected
Write-Host ("C3 STUB stdin_redirected=" + $stdinRedirected)
if (-not $stdinRedirected) { Write-Host "C3 STUB REFUSED: stdin is a console, not NUL; the tree lacks #229"; exit 7 }
$tree = 'C:\Users\micha\Desktop\github\weather'; $py = 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe'
$promptSha = 'c03caf8cbe6114c2c42ff216c49e8c2b6453f57f29ed2ea12146b40cffd44597'
. (Join-Path $tree 'scripts\ops\windows_kill_on_close_job.ps1')
$job = New-WeatherKillOnCloseJob
$code = 70
try {
    $childArgs = ConvertTo-WeatherWindowsArgumentString -Tokens @("-I", "-S", "-B", "C:\c3\20261008\c3_prompt_child.py", $tree, $promptSha)
    $child = Start-WeatherInteractiveProcessInJob -Job $job -FilePath $py -ArgumentString $childArgs -WorkingDirectory $tree
    $child.WaitForExit(); $code = [int]$child.ExitCode
} finally {
    if ($null -ne $job) { $job.Dispose() }   # close this stub's own kill-on-close Job; nothing else
}
exit $code
