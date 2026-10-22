foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
if (-not (Wait-Restore $GapStart)) { NoGo 'C7 not recovered -> ROLLBACK' }
$GapEnd = Get-Date; Log ("C7 3/3; gap {0:n1} min" -f ($GapEnd-$GapStart).TotalMinutes)
