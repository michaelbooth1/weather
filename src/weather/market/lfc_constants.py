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
SESSION0_MIN_CANDIDATE_EVENTS = 3  # DRAFT clarification C: owner-listed candidate events, distinct, off-panel
# Sub-runs, each one owner-started run. Seconds = fixed end; 0a has a 20-minute end, 0b-0d at most 10 minutes,
# 0e refuses before any submit, 0f is the optional main-loop stall, 0g the venue-only dead-man.
# 0g (fix round 1, review F-1; DRAFT clarification C): the venue-only dead-man run. Heartbeat sends stop as in 0d,
# but the script's own 8 s stale cleanup is disabled so only the venue's /v1/heartbeats dead-man can cancel.
SESSION0_RUNS = {'0a': 1200, '0b': 600, '0c': 600, '0d': 600, '0e': 600, '0f': 600, '0g': 600}
SESSION0_DROP_AFTER_SECONDS = 120  # 0d/0g: heartbeat sends stop 120 s after posting; the main loop stays alive
# 0g exposure bound: the venue cancels about 10 s after the last heartbeat (+5 s buffer) = the window. The cap is
# at least window + margin after the drop, read at the next control checkpoint (>= 30 s + one control cycle); if
# our orders still rest then, the run ends through the normal cleanup (a safety cancel that follows within one
# control cycle plus read latency and is not part of the proof) and the campaign ledger records a halt. Requotes are
# allowed before the drop and never sent after it. The proof is "every leg terminal with no cancel request from this
# process since the drop"; it cannot tell the venue dead-man from an owner cancel, hence the manual-trading pause.
SESSION0_VENUE_WINDOW_SECONDS = 15
SESSION0_VENUE_MARGIN_SECONDS = 15
# Owner rule (DRAFT clarification C5): printed by preflight and by the confirmation prompt of run 0g.
SESSION0_0G_MANUAL_TRADING_PAUSED = (
    'Run 0g: manual trading, including any owner cancel in the Polymarket UI, must stay PAUSED from before this run '
    'until its result is read. An owner cancel would counterfeit the venue dead-man proof.')
# session0_passed (review F-1a): every required sub-run ended with one of these reasons and a clean cleanup; 0f is
# optional. Plus the owner attestation session0/pass.json bound to the ledger, with S0-2 measured on 0c.
SESSION0_PASS_REASONS = {'0a': ('fixed_end',), '0b': ('foreign_open_order',), '0c': ('reconciled_after_crash',),
                         '0d': ('heartbeat_stale', 'order_no_longer_resting'), '0e': ('l_budget_refused',),
                         '0g': ('venue_deadman_cancelled',)}
SESSION0_S0_2_MAX_SECONDS = 20  # S0-2 measured on 0c gates session 1 (review F-1c)
# Maker-fee class rule (C8 as replaced 2026-10-09 by clarification D; EF section 10o; weather.market.lfc_fees): the
# selected market must classify as WEATHER_TAKER_ONLY (Gamma feesEnabled true, feeType == WEATHER_FEE_TYPE,
# feeSchedule.takerOnly true, CLOB fd.to true) or FEE_FREE (every fee field off/absent, /fee-rate base_fee 0) at
# selection, at every submit and every minute; session 0 must be FEE_FREE. base_fee / makerBaseFee read 1000 on
# weather markets and are recorded only (not the maker charge); the schedule coefficients are recorded, never
# required to equal 0.05 / 1 / 0.25. Anything else fails closed.
WEATHER_FEE_TYPE = 'weather_fees'
# Trade reads at reconcile (review F-6): the same 5 x 2 s re-read as the session cleanup, bounded in time.
TRADE_READ_ATTEMPTS = 5
TRADE_READ_PAUSE_SECONDS = 2
TRADE_READ_SECONDS = 60
SESSION0_STALL_SECONDS = 25  # 0f: the main loop stalls for longer than the 20 s watchdog, 120 s after posting
# The session-0 requote window keeps RE-1's shape around its own offset: RE-1 posts at 1.5c and requotes outside
# [1, 3]c, i.e. [d - 0.5, d + 1.5]. Not specified by S0; proposed in DRAFT clarification C (owner signature pending).
SESSION0_REQUOTE_WINDOW = (Decimal('4.5'), Decimal('6.5'))
RE1_REQUOTE_WINDOW = (Decimal('1'), Decimal('3'))
RE1_OFFSET = Decimal('.015')
