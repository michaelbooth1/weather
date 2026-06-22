# 215. Current-High Trust Gate For Aggressive Trading [OPEN 2026-06-22 - UNTRUSTED CURRENT MAX MUST CAP TAKER AND MM RISK]

Goal: add stronger current-high trust gating so markets with untrusted current
max state cannot receive aggressive taker buys or tight MM quotes until
settlement/current-high evidence is reliable.

Source: the 2026-06-21 log review and taker/MM reports marked current-high
trust false for Toronto, Atlanta, Denver, Houston, and San Francisco. Those
markets showed settlement-adjusted highs that diverged from raw/current highs,
for example Atlanta raw high near `84.02F` vs settlement high `86F`, Denver
`83.84F` vs `87F`, Houston `86F` vs `89F`, and San Francisco `64.94F` vs
`70F`.

Why this matters: late-day weather markets are highly sensitive to whether the
current maximum is real, stale, rounded, lagged, or revised. If current-high
trust is false, buying or quoting around the apparent winner can turn a
settlement-source artifact into trading risk.

## Design

1. Promote current-max trust state into taker and MM risk policy, not just the
   report table.
2. Define aggressive-risk behaviors for untrusted current max: deny, cap size,
   require larger edge, or widen quotes depending on market/time regime.
3. Add per-market trust reasons to order and quote tapes so decisions are
   auditable.
4. Build specific regression cases for Toronto, Atlanta, Denver, Houston, and
   San Francisco from the June 21 logs.

- [ ] Add current-high trust state and reason to taker sizing/permission.
- [ ] Add current-high trust state and reason to MM quote permission/risk.
- [ ] Configure stronger behavior for untrusted current max near settlement or
  late-day lock-in windows.
- [ ] Add tests for the five June 21 untrusted-current-high markets.
- [ ] Surface current-high trust failures in daily progress and fleet
  observability.

Acceptance: when current-high trust is false, taker and MM outputs show an
explicit current-high trust gate and reduce or deny aggressive exposure; the
June 21 untrusted-market cases are covered by tests.

Related: items 59, 153, 193, 196, 209, 214.
