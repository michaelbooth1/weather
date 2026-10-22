$GapMin = ($GapEnd-$GapStart).TotalMinutes
if ($GapMin -gt 35) {
  Log ("gap {0:n1} min over 35; recorded choice {1}" -f $GapMin, $GapChoice)
  if ($GapChoice -eq 'ROLLBACK_ON_OVERRUN') { NoGo 'capture gap overran and the owner chose rollback -> ROLLBACK' } }
Log 'C9 core PASS'
