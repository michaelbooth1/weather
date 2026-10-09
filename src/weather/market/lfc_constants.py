"""Frozen constants of the live-fill calibration campaign.

Governing documents (owner-signed 2026-10-09T18:09Z; signature record on
claude/live-fill-calibration-prereg-20261009 @ c57a6d07, signed bytes at 82936d68):
docs/research/live-fill-calibration-preregistration-2026-10-09.md (sections cited below as PR),
docs/research/live-fill-calibration-session0-spec-2026-10-09.md (S0) and
docs/research/live-fill-calibration-panel-clarifications-2026-10-09.md.
Pure values only; nothing here creates an exchange capability. Changing any value needs a dated
clarification of the signed documents first, then a reviewed commit.
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal

# DECLARED DEVIATION (PR section 2, ruling R5): the desk study, replay v2 and shadow proxies simulate a 75-share
# RE-1 quote. The campaign rests 40 shares per leg, so each leg costs at most 32 pUSD (40 x 0.80) and a double fill
# on one band (64) plus the next band's reserve never exceeds the 100 pUSD L budget. The RE-1 depth filter of 75 is
# kept. c_at/c_thr are ratios per offered share and are compared to replay at the same size.
PILOT_SIZE = Decimal('40')
PROXY_SIZE = Decimal('75')  # the proxies' size the campaign deviates from; reporting only

TREATMENT = 'LFC-40'
SESSION0_TREATMENT = 'LFC-S0'
PROTOCOL = 'LFC-live-fill-calibration-v1'

# PR section 6: L ledger cap; at most 8 counted sessions of at most 360 minutes; GTD = end + 60 s (RE-1).
BUDGET_PUSD = Decimal('100')
MAX_SESSIONS = 8
SESSION_SECONDS = 21600
PER_LEG_PRICE_FLOOR = Decimal('.17')
PER_LEG_PRICE_CEILING = Decimal('.80')

# PR section 6 "Stop at 100": the campaign ends once L_filled + the minimum feasible reserve exceeds the cap. A fresh
# RE-1 quote is m - 1.5c and (1 - m) - 1.5c snapped outward to the 0.01 tick, so p_yes + p_no >= 0.96 and the
# smallest reserve any counted band can need is 40 x 0.96.
MIN_FEASIBLE_LEG_SUM = Decimal('.96')
MIN_FEASIBLE_RESERVE = PILOT_SIZE * MIN_FEASIBLE_LEG_SUM

# PR section 3: selection filters the RE-1 quote function does not already enforce.
SHARE_MANY_RANGE = (Decimal('.15'), Decimal('.70'))

# PR section 4 dates. No campaign order may rest before EARLIEST_START_UTC (replaces RE-1 LAST_DAY); a hard stop at
# 23:50Z keeps every session inside its UTC day; counted sessions are on distinct owner-local dates and the last
# one starts by LAST_START_LOCAL_DATE. Session 0 is exempt from the earliest start only (S0 section 1).
EARLIEST_START_UTC = datetime(2026, 10, 15, tzinfo=timezone.utc)
HARD_STOP_UTC = time(23, 50)
LAST_START_LOCAL_DATE = date(2026, 10, 31)
OWNER_TIMEZONE = 'America/Toronto'

# Reserved panel dates: the descriptive analysis refuses inputs dated inside this window without an explicit
# override (the agent read clearance in PR section 9 forbids 88a/panel/settlement reads for these dates).
RESERVED_FIRST_DAY = '2026-09-30'
RESERVED_LAST_DAY = '2026-10-15'

# Account-wide foreign-order read during a session (PR section 6 "Open orders"); the RE-1 submit-time read stays.
FOREIGN_CHECK_SECONDS = 30

# ----- session 0 (S0 sections 2-4) -------------------------------------------------------------------------------
SESSION0_MAX_SIZE = Decimal('20')  # size = the market's min_order_size, never above 20
SESSION0_OFFSET = Decimal('.05')  # d = 5c from the mid, snapped outward
SESSION0_END_DAYS = 7  # the market's end date is at least 7 days after the session date
SESSION0_DEPTH_REACH = Decimal('.03')  # pick: largest two-sided displayed depth within 3c of the mid
SESSION0_MID_RANGE = (Decimal('.20'), Decimal('.80'))
# Sub-runs, each one owner-started run. Seconds = fixed end; 0a has a 20-minute end, 0b-0d at most 10 minutes,
# 0e refuses before any submit, 0f is the optional main-loop stall.
SESSION0_RUNS = {'0a': 1200, '0b': 600, '0c': 600, '0d': 600, '0e': 600, '0f': 600}
SESSION0_DROP_AFTER_SECONDS = 120  # 0d: heartbeat sends stop 120 s after posting; the main loop stays alive
SESSION0_STALL_SECONDS = 25  # 0f: the main loop stalls for longer than the 20 s watchdog, 120 s after posting
# The session-0 requote window keeps RE-1's shape around its own offset: RE-1 posts at 1.5c and requotes outside
# [1, 3]c, i.e. [d - 0.5, d + 1.5]. Not specified by S0; recorded as an open question for the reviewer.
SESSION0_REQUOTE_WINDOW = (Decimal('4.5'), Decimal('6.5'))
RE1_REQUOTE_WINDOW = (Decimal('1'), Decimal('3'))
RE1_OFFSET = Decimal('.015')
