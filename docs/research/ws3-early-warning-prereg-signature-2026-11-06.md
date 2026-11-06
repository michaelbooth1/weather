# WS-3 early-warning pre-registration: master signature

Signed by master-agent (production host) on 2026-11-05 at 22:26:56 America/Toronto (host Get-Date), after reviewing the bytes at `claude/ws-docs-head-c13-20261106` @ `05a0c592d4ae81e928ac5cecae5e19fe9c3f3a33`.

- **Signed file:** `docs/research/ws3-early-warning-prereg-2026-11-06.md`, sha256 `1f992edfc0c6ce9451bea27487d9fe0466ff661169045ff48d9358ab34a0a687`.
- **Authority:** the owner's 2026-11-05 ~21:50 "Allow early warning" and ~22:03 "approved full plan" (DECISION_LOG). The file applies these master rulings:
  - T2's rule = master's spec + PT-1 §3.3;
  - hours 07-16;
  - KILL iff U < 0, at α 0.025 per arm;
  - venue settlement from the per-event settlement.json, never the settlements ledgers;
  - a declared edge size of 5 c per filled share, with a P(KILL) ≥ 0.5 power gate on the MG-2 arm (method rule 6 and STATE_OF_PLAY kill scopes, no override);
  - latency ≥ 30 s for this kill-only read.
- **Kill-only:** there is no PASS, it sits outside the edge trial charter's Holm family, and it supports no edge claim.
- **Module pin:** `src/weather/backtesting/t2_taker_rule.py` and its test file do not exist at signature. The workstation builds them to §2-§3 exactly, and master reviews them. Their sha256 values are then recorded in a dated module-pin note appended to this signature file, before step 2. After the pin neither file changes, and T2 reuses the same module sha.
- **Order:** no step runs before the module pin. The step 4 power gate decides whether steps 5-6 run.
- **Not read for this signature:** no outcome, price, book, label, settlement or model output for any local target date ≥ 2026-09-30. Master read only the prereg text, the code it cites and host file names.
- **Changes after signature** are dated, outcome-blind clarifications, never edits of the signed file.
