# 255. Taker Current-High Deny Regression Proof [COMPLETE 2026-06-23 - CONFIG-DRIFT CURRENT-HIGH DENY RATIFIED]

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

- [x] Remove config-reopenable pre-late allowance for aggressive untrusted
  current-high taker fills.
- [x] Add tests with `current_high_trust_gate_start_hour_local=15` proving
  aggressive rows block from the start of day.
- [x] Add daily-roll/config diagnostics for delayed current-high trust starts.
- [x] Update item 236 closeout notes or link this follow-up as the remaining
  hardening step.

Acceptance: an aggressive untrusted-current-high taker candidate is blocked
from local hour `0` even if config sets a later start hour, unless it belongs to
a non-promotable diagnostic-only arm.

## 2026-06-23 Completion Note

Implemented in `weather.market.taker_bot_strategy_evaluation` and
`weather.operations.taker_bot_daily_roll`.

- `current_high_trust_gate_state` now denies aggressive untrusted-current-high
  taker rows before the pre-late observe branch, so
  `current_high_trust_gate_start_hour_local=15` cannot reopen early fills.
- Non-promotable diagnostic-only arms can still use the observe/cap path when
  they are explicitly configured away from `deny_aggressive`.
- `current_high_trust_config_warnings` emits
  `CURRENT_HIGH_TRUST_GATE_DELAYED_START` and the taker daily-roll status JSON
  records `config_warning_count` plus `config_warnings` when an override tries
  to delay the gate.
- Regression coverage now proves an aggressive untrusted row at local hour `9`
  still returns `NO_TRADE_CURRENT_HIGH_TRUST_GATE` under a delayed start-hour
  config.

Verification:

- `python -m pytest tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py -q`
  - `52 passed, 5 subtests passed`

Related: items 215, 236, 237.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - CONFIG-DRIFT CURRENT-HIGH DENY RATIFIED`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

