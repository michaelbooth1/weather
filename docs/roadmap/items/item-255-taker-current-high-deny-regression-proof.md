# 255. Taker Current-High Deny Regression Proof [OPEN 2026-06-23 - PRE-LATE BYPASS STILL CONFIG-REOPENABLE]

Goal: make aggressive untrusted-current-high taker denial impossible to reopen
through `current_high_trust_gate_start_hour_local` config drift.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-23.md`.
Current defaults set `current_high_trust_gate_start_hour_local` to `0`, but
`current_high_trust_gate_state` still contains an `allow_pre_late_window`
branch. The June 22 run config used start hour `15` and recorded `2`
pre-late untrusted-current-high fills.

Why this matters: item 236 is marked complete because defaults now close the
gap, but the code path can still be reopened by config. A safety gate that
depends on not changing a start-hour value is too fragile for live readiness.

## Design

1. Remove or invert the `allow_pre_late_window` branch for aggressive
   untrusted-current-high taker orders.
2. Keep a non-aggressive observe/cap mode only for explicit diagnostic arms
   that cannot fill live or promote.
3. Add a regression fixture where start hour is set to `15`; aggressive
   untrusted-current-high rows must still be `NO_TRADE_CURRENT_HIGH_TRUST_GATE`.
4. Surface a config warning when a taker config tries to delay the current-high
   trust gate beyond local hour `0`.

- [ ] Remove config-reopenable pre-late allowance for aggressive untrusted
  current-high taker fills.
- [ ] Add tests with `current_high_trust_gate_start_hour_local=15` proving
  aggressive rows block from the start of day.
- [ ] Add daily-roll/config diagnostics for delayed current-high trust starts.
- [ ] Update item 236 closeout notes or link this follow-up as the remaining
  hardening step.

Acceptance: an aggressive untrusted-current-high taker candidate is blocked
from local hour `0` even if config sets a later start hour, unless it belongs to
a non-promotable diagnostic-only arm.

Related: items 215, 236, 237.
