# R-P2 prereg clarification 1: futility reading confirmed by master

Recorded 2026-11-02T13:17:05.9366131-05:00 (WS Get-Date). Applies to `prereg_rp2.md` sha256 2a438306214ece68e6e58d6f288765dc8addace7d21b89a02a22141e9c2d3e70 @ 5fb28de40c98114f1cb0fe28d4342c692685366a. The frozen prereg is not edited.

1. **Futility at 50% is confirmed by master:** KILL at the half-way look if the point estimate is >= 0, **or** if the 95% CI lower bound is > -0.0015.
2. **The screen is approved by master** on this prereg. It runs only via `workstation_heavy.ps1 -Queue` after the cleanup pass, and only on the coordinator's explicit "RUN SCREEN".
3. **The season scope is deferred.** Master's expected outcomes:
   - **If the screen passes:** "screen PASS; confirmation infeasible at size; PARKED as ingredient; reopen trigger: a year-round base model or a variance reduction bringing the forward length under 1 season".
   - **If the screen fails:** KILL.
   - No shadow infrastructure is built.