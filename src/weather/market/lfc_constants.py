"""Frozen constants of the live-fill calibration pilot (owner approval 2026-10-09 ~14:40).

Design: docs/research/live-fill-calibration-design-2026-10-09.md (branch
claude/live-fill-calibration-design-20261009 @ 22112f73). Pure values only; nothing
here creates an exchange capability. Changing any value is a reviewed commit.
"""
from datetime import datetime, timezone
from decimal import Decimal

# DECLARED DEVIATION: the desk study, replay v2 and shadow proxies simulate a 75-share RE-1 quote. The pilot rests
# 40 shares per leg (design section 2 "Size"): two-sided at 40 clears the 20-share T+1/T+2 reward minimum, fill
# probability per print is price-time priority so size barely moves c_at/c_thr, and 75-share legs would let three
# total-loss fills exceed the 100 pUSD worst-case budget. The deviation is declared in the pre-registration.
PILOT_SIZE = Decimal('40')
PROXY_SIZE = Decimal('75')  # the proxies' size the pilot deviates from; reporting only

# Session 0: an uncounted, minimal-size shakeout on a market outside every panel (owner approved in principle
# 2026-10-09 14:55). Off unless the explicit --session0 flag is given.
SESSION0_SIZE = Decimal('20')

TREATMENT = 'LFC-40'
SESSION0_TREATMENT = 'LFC-S0-20'
PROTOCOL = 'LFC-live-fill-calibration-v1'

BUDGET_PUSD = Decimal('100')  # worst-case ledger L cap across all sessions (filled legs at zero recovery)
MAX_SESSIONS = 8  # counted sessions; session 0 is not counted
SESSION_SECONDS = 21600  # 360 minutes
PER_LEG_PRICE_CEILING = Decimal('.80')  # 40 x 0.80 = 32 pUSD per leg at most (design section 2)

# Earliest counted-session start. Master may move it to 2026-10-15 once that date is confirmed clean;
# change only this constant (tests pin the refusal around it).
EARLIEST_START_UTC = datetime(2026, 10, 16, tzinfo=timezone.utc)

# Reserved panel dates: the analysis refuses inputs dated inside this window without an explicit override.
RESERVED_FIRST_DAY = '2026-09-30'
RESERVED_LAST_DAY = '2026-10-15'

# Session-0 forced limits (test triggers). Off by default; accepted only together with --session0.
FORCE_LIMITS = ('fixed_end', 'ledger_cap', 'foreign_order', 'dead_man')
SESSION0_FORCED_SECONDS = 600  # forced fixed_end session length
DEAD_MAN_OBSERVE_SECONDS = 30  # how long a forced dead-man waits for the exchange to empty our orders
FOREIGN_CHECK_SECONDS = 30  # cadence of the account-wide foreign-order read during a session
