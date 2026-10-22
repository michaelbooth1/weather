@{ result='PASS'; head=$Head; gap_minutes=[math]::Round(($GapEnd-$GapStart).TotalMinutes,1); old_venv=$Old; new_home=$NewHome; release_case='A'; at=(Get-Date).ToString('o') } |
  ConvertTo-Json | Set-Content "$N\cutover-receipt.json" -Encoding utf8
Release-Lease; Log 'CUTOVER PASS'
