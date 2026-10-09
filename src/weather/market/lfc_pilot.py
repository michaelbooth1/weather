"""Live-fill calibration campaign: the RE-1 controller at 40 shares, the L gate, session 0 and the end notice.

Governed by the owner-signed documents (2026-10-09T18:09Z; record on claude/live-fill-calibration-prereg-20261009
@ c57a6d07): the pre-registration (PR), the session-0 spec (S0) and the panel clarifications. The quote, requote
rule, stop-on-fill, cleanup and every RE-1 hard limit are inherited unchanged from
weather.market.re1_attended.Session (codex/re1-wallet-200-20260923 @ 2b9a0ca9); this module only overrides its
profile hooks.

Added hard limits (PR section 6; each ends the session through the RE-1 cleanup):
  * L gate before the first post and before every requote: L_after_cancel_of_replaced_leg + reserve <= 100 with
    reserve = size x (p_yes + p_no); available pUSD >= L_resting + reserve (fresh balance read); a stopped campaign
    (stop-at-100 or a reconciliation mismatch) refuses. Missing or unreadable ledger state refuses.
  * Open orders must be exactly ours: an account-wide read every FOREIGN_CHECK_SECONDS ends the session on any
    foreign open order (`foreign_open_order`). The preflight and the live start refuse any open order at all.
  * Dates: no counted session before 2026-10-15T00:00Z, none ending after 23:50Z of its UTC day, the last one
    starting by local 2026-10-31, at most one per owner-local date. Session 0 is exempt from the earliest start only.

Dead-man and unattended cleanup (PR section 7, RE-1 pattern unchanged): the heartbeat thread sends every 2 s and the
session ends when none succeeds within 8 s; a main loop stale for 20 s stops the sends so the venue cancels all of
the account's orders about 10 s later; every order is GTD with expiration = session end + 60 s; every end path runs
the RE-1 cleanup: cancel each order, then the account-wide cancel_all, poll open orders until empty for up to 10 s,
read our terminal orders, positions and trades; PANIC on an unclean cleanup. Changes from RE-1: fills are attributed
by our order ids (a condition position alone is not our fill on the owner's existing wallet), and the end notice.
cancel_all is account-wide, so it also cancels a foreign order found at runtime (S0 run 0b: expected).

Session 0 (S0, explicit flag only): uncounted, counts in L, no panel exclusion, a market outside every panel,
size = the market's min_order_size (<= 20), offset 5c, only the reward-terms check skipped. Sub-runs 0a-0f, plus 0g
(fix round 1, review F-1; DRAFT clarification C): the venue-only dead-man, with the script's stale cleanup off.

Fix round 1 (review 2026-10-09 @ f88074d5; semantics in the DRAFT, UNSIGNED clarification C): fee_rate_bps == 0 at
selection, every submit and every minute (else the session ends); every market rule compared each minute (F-9); a
cancelled requote leg is re-read until terminal before L_resting is released (F-3); a foreign order seen on the user
stream ends as foreign_open_order and any other stream failure has its own code (F-2).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

from weather.market import lfc_constants as LFC
from weather.market.lfc_ledger import LedgerCap, LedgerUnavailable, band_reserve, position_conditions, traded_shares
from weather.market.lfc_panel_exclusion import append_exclusions, exclusion_lines
from weather.market.market_config import event_slug_for_date, market_id_from_slug
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import HoldEnd, _order_id, digest, utc, write_new, SCHEMA_VERSION
from weather.market.re1_attended import Session, filled, number
from weather.market.re1_rehearsal import Re1PublicBooks
from weather.market.reward_quote import QuoteRefused, _levels

LFC_JOURNAL_SCHEMA = 'lfc_journal_v0.1'  # additive events inside the unchanged RE-1 hold-journal chain
SESSION_END_SCHEMA = 'lfc_session_end_v0.1'


def pilot_root():
    """Fixed across worktrees and tips (the budget spans every session); no override for live."""
    if os.name != 'nt':
        raise RuntimeError('campaign_requires_windows_token')
    from weather.market.live_sdk_overlay import _windows_token_profile_root
    return _windows_token_profile_root() / '.weather-lfc-20261009'


# ----- dates (PR section 4) ---------------------------------------------------------------------------------------
def hard_stop(start):
    start = utc(start)
    return datetime.combine(start.date(), LFC.HARD_STOP_UTC, tzinfo=timezone.utc)


def owner_local_date(when):
    return utc(when).astimezone(ZoneInfo(LFC.OWNER_TIMEZONE)).date()


def start_refusals(now, *, session0=False, seconds=LFC.SESSION_SECONDS):
    """Date refusals for a session starting at `now` and lasting `seconds` (empty = may start)."""
    now, refusals = utc(now), []
    if not session0 and now < LFC.EARLIEST_START_UTC:
        refusals.append('before_earliest_start')
    if not session0 and owner_local_date(now) > LFC.LAST_START_LOCAL_DATE:
        refusals.append('after_last_start_date')
    if now + timedelta(seconds=seconds) > hard_stop(now):
        refusals.append('past_hard_stop_2350z')
    return refusals


# ----- profiles -------------------------------------------------------------------------------------------------
class PilotProfile:
    def __init__(self, *, session0=False, run=None):
        if session0 != (run is not None) or (run is not None and run not in LFC.SESSION0_RUNS):
            raise ValueError('session0_run_required_with_session0_only')
        self.session0, self.run = session0, run
        self.size = None if session0 else LFC.PILOT_SIZE
        self.treatment = LFC.SESSION0_TREATMENT if session0 else LFC.TREATMENT
        self.seconds = LFC.SESSION0_RUNS[run] if session0 else LFC.SESSION_SECONDS

    @property
    def SIZES(self):
        return (self.size,) if self.size is not None else ()

    def bind_size(self, size):
        """Session 0: the size is the selected market's min_order_size (never above 20)."""
        size = number(size)
        if not self.session0 or not 0 < size <= LFC.SESSION0_MAX_SIZE or (self.size is not None and self.size != size):
            raise RuntimeError('capital_cap')
        self.size = size
        return self

    def venue_ceiling(self, size):
        """(order cap, band cap) of PR section 6: 0.79 x size and 0.98 x size (31.6 / 39.2 at 40)."""
        size = number(size)
        if self.session0 and self.size is None:
            self.bind_size(size)
        if size not in self.SIZES:
            raise RuntimeError('capital_cap')
        return Decimal('.79') * size, Decimal('.98') * size


# ----- fee rule (review Q4 replacement; DRAFT clarification C) --------------------------------------------------
def fee_refusal(rules, tokens):
    """None when every token reads fee_rate_bps == 0; else 'fee_rate_unreadable' or 'fee_rate_nonzero'."""
    try:
        fees = [number(rules[token]['fee_rate_bps']) for token in tokens]
    except Exception:
        return 'fee_rate_unreadable'
    if not fees:
        return 'fee_rate_unreadable'
    return None if all(fee == LFC.REQUIRED_FEE_RATE_BPS for fee in fees) else 'fee_rate_nonzero'


def require_zero_fee(table):
    """Preflight and live selection (both profiles): the selected market's tokens must read fee_rate_bps == 0."""
    if table.get('selected_condition_id'):
        selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        try:
            rules, tokens = selected['snapshot']['rules'], selected['token_ids']
        except (KeyError, TypeError):
            raise RuntimeError('fee_rate_unreadable') from None
        code = fee_refusal(rules, tokens)
        if code:
            raise RuntimeError(code)
    return table


def _rule_key(rule):
    """Comparable market rules of one token; an unreadable rule never equals a readable one."""
    try:
        return (number(rule['tick_size']), number(rule['min_order_size']), number(rule['fee_rate_bps']),
                rule['neg_risk'])
    except Exception:
        return ('unreadable', id(rule))


def _terminal(row):
    row = row if isinstance(row, dict) else {}
    status = str(row.get('status') or row.get('official_order_status') or '').upper()
    return bool(status) and status != 'LIVE'


# ----- session 0 market choice (S0 section 2) -------------------------------------------------------------------
def session0_slug_refusals(event_slug, *, now):
    """Rule 1: no slug prefix of the 12 built-in markets (any date) and no YouTube market slug."""
    refusals = []
    slug = str(event_slug or '').lower()
    if not slug:
        return ['session0_event_slug_missing']
    if market_id_from_slug(slug) is not None or any(slug.startswith(spec.slug_prefix) for spec in REGISTRY.values()):
        refusals.append('session0_built_in_market')
    today = utc(now).date()
    if any(slug == event_slug_for_date(today + timedelta(days=d), m) for m in REGISTRY for d in range(-60, 61)):
        refusals.append('session0_built_in_band')
    if 'youtube' in slug:
        refusals.append('session0_youtube_market')
    return sorted(set(refusals))


def _plain_mid(quote_inputs):
    bids, asks = _levels(quote_inputs['yes_bids']), _levels(quote_inputs['yes_asks'])
    return (max(p for p, _ in bids) + min(p for p, _ in asks)) / 2, bids, asks


def session0_quote(snapshot, *, size):
    """Offset d = 5c from the plain mid, snapped outward to the 0.01 tick (S0 section 3)."""
    values = snapshot['quote_inputs']
    mid, yb, ya = _plain_mid(values)
    nb, na = _levels(values['no_bids']), _levels(values['no_asks'])
    tick = Decimal('.01')

    def outward(value):
        return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    yes, no = outward(mid - LFC.SESSION0_OFFSET), outward(1 - mid - LFC.SESSION0_OFFSET)
    for price, asks in ((yes, ya), (no, na)):
        if not LFC.PER_LEG_PRICE_FLOOR <= price <= LFC.PER_LEG_PRICE_CEILING:
            raise QuoteRefused('leg_price_outside_range')
        if min(p for p, _ in asks) - price < tick:
            raise QuoteRefused('would_cross_or_violate_touch_buffer')
    size = number(size)
    return {'adjusted_mid': str(mid), 'yes_buy': str(yes), 'no_buy': str(no), 'size': str(size),
            'reserve_pusd': str(band_reserve(size, (yes, no))), 'offset': str(LFC.SESSION0_OFFSET)}


def session0_candidate(candidate, *, now, excluded_conditions, held_conditions, ledger):
    """Evaluate one candidate (event + market + public snapshot) against rules 1-5; returns the table row."""
    row = dict(candidate)
    row.update(eligible=False, refusal=None, quote=None, depth_within_3c=None)
    try:
        refusals = session0_slug_refusals(candidate['event_slug'], now=now)
        if refusals:
            raise QuoteRefused(refusals[0])
        event_conditions = {str(c).lower() for c in candidate['event_condition_ids']}
        if candidate['condition_id'].lower() not in event_conditions:
            raise QuoteRefused('event_conditions_incomplete')
        if event_conditions & excluded_conditions:
            raise QuoteRefused('session0_in_retained_scope')
        if event_conditions & held_conditions:
            raise QuoteRefused('session0_event_held_in_baseline')
        end = utc(candidate['market_end_utc'])
        if end.date() < utc(now).date() + timedelta(days=LFC.SESSION0_END_DAYS):
            raise QuoteRefused('session0_market_ends_too_soon')
        snapshot = candidate['snapshot']
        rules = snapshot['rules']
        if any(number(r['tick_size']) != Decimal('.01') for r in rules.values()):
            raise QuoteRefused('unsupported_tick')
        fee = fee_refusal(rules, candidate['token_ids'])
        if fee:
            raise QuoteRefused(fee)
        sizes = {number(r['min_order_size']) for r in rules.values()}
        if len(sizes) != 1 or not 0 < max(sizes) <= LFC.SESSION0_MAX_SIZE:
            raise QuoteRefused('session0_min_order_size')
        values = snapshot['quote_inputs']
        for bid_key, ask_key in (('yes_bids', 'yes_asks'), ('no_bids', 'no_asks')):
            bids, asks = _levels(values[bid_key]), _levels(values[ask_key])
            if not bids or not asks:
                raise QuoteRefused('one_sided_book')
            if max(p for p, _ in bids) >= min(p for p, _ in asks):
                raise QuoteRefused('crossed_book')
        mid, yb, ya = _plain_mid(values)
        if not LFC.SESSION0_MID_RANGE[0] <= mid <= LFC.SESSION0_MID_RANGE[1]:
            raise QuoteRefused('midpoint_outside_range')
        reach = LFC.SESSION0_DEPTH_REACH
        depth = min(sum((s for p, s in yb if mid - reach <= p <= mid), Decimal(0)),
                    sum((s for p, s in ya if mid <= p <= mid + reach), Decimal(0)))
        row['depth_within_3c'] = str(depth)
        quote = session0_quote(snapshot, size=max(sizes))
        row['quote'] = quote
        if number(ledger['L']) + number(quote['reserve_pusd']) > LFC.BUDGET_PUSD:
            raise QuoteRefused('l_budget_refused')
        row['eligible'] = True
    except (QuoteRefused, ValueError, KeyError, TypeError) as exc:
        row['refusal'] = str(exc) if isinstance(exc, QuoteRefused) else type(exc).__name__
    return row


def session0_table(candidates, *, now, run, available_collateral, ledger, excluded_conditions, held_conditions,
                   scope_sources):
    """Full candidate table and the pick: the largest two-sided displayed depth within 3c of the mid, ties by
    ascending condition id (S0 section 2). Written to selection.json by the CLI."""
    excluded = {str(c).lower() for c in excluded_conditions}
    held = {str(c).lower() for c in held_conditions}
    rows, seen = [], set()
    for candidate in candidates:
        if candidate['condition_id'] in seen:
            raise ValueError('session0 universe repeats a condition')
        seen.add(candidate['condition_id'])
        observed = utc(candidate['snapshot']['observed_at_utc'])
        if not 0 <= (utc(now) - observed).total_seconds() <= 1800:
            raise ValueError('session0 snapshot outside the 30-minute window')
        rows.append(session0_candidate(candidate, now=now, excluded_conditions=excluded, held_conditions=held,
                                       ledger=ledger))
    survivors = sorted((r for r in rows if r['eligible']),
                       key=lambda r: (-number(r['depth_within_3c']), r['condition_id']))
    for row in rows:
        row['predicted_360_minutes'] = 0.0
    return {'size_treatment': LFC.SESSION0_TREATMENT, 'session0_run': run, 'schema_version': SCHEMA_VERSION,
            'kind': 'selection', 'created_at_utc': utc(now).isoformat(), 'target_date': None,
            'available_collateral': str(number(available_collateral)),
            'campaign_L_pusd': str(number(ledger['L'])), 'campaign_L_resting_pusd': str(number(ledger['L_resting'])),
            'excluded_conditions': sorted(excluded), 'baseline_position_conditions': sorted(held),
            'scope_sources': scope_sources, 'universe_complete': True, 'source_records': [],
            'rows': sorted(rows, key=lambda r: r['condition_id']),
            'ranked_conditions': [r['condition_id'] for r in survivors],
            'selected_condition_id': survivors[0]['condition_id'] if survivors else None}


_DERIVED = {'eligible', 'refusal', 'quote', 'depth_within_3c', 'predicted_360_minutes'}


def validate_session0_table(table, *, now):
    if (table.get('size_treatment') != LFC.SESSION0_TREATMENT or table.get('kind') != 'selection' or
            table.get('schema_version') != SCHEMA_VERSION or not table.get('selected_condition_id') or
            not 0 <= (utc(now) - utc(table['created_at_utc'])).total_seconds() <= 1800):
        raise ValueError('session0 table is stale or malformed')
    candidates = [{k: v for k, v in row.items() if k not in _DERIVED} for row in table['rows']]
    rebuilt = session0_table(candidates, now=table['created_at_utc'], run=table['session0_run'],
                             available_collateral=table['available_collateral'],
                             ledger={'L': table['campaign_L_pusd'], 'L_resting': table['campaign_L_resting_pusd']},
                             excluded_conditions=table['excluded_conditions'],
                             held_conditions=table['baseline_position_conditions'],
                             scope_sources=table['scope_sources'])
    if rebuilt != table:
        raise ValueError('session0 table does not reproduce')
    return next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])


class Session0Books(Re1PublicBooks):
    """Public books for an unrewarded session-0 market: no reward read; the reward fields of the snapshot are
    zero placeholders that only the reward-terms check (skipped in session 0) would read."""

    def reward(self, condition, *, checkpoint=lambda: None):
        import re
        if re.fullmatch(r'0x[0-9a-f]{64}', str(condition)) is None:
            raise ValueError('reward condition is invalid')
        return {'condition_id': condition, 'rewards_min_size': '0', 'rewards_max_spread': '0',
                'total_daily_rate': '0', 'session0_placeholder': True}

    def candidates(self, event_slugs, *, checkpoint=lambda: None):
        rows = []
        for slug in event_slugs:
            event = self.get('https://gamma-api.polymarket.com/events/slug/' + slug, checkpoint=checkpoint)
            if event.get('slug') != slug or not isinstance(event.get('markets'), list) or not event['markets']:
                raise ValueError('session0_event_unreadable')
            conditions = sorted(str(m.get('conditionId')) for m in event['markets'])
            for market in event['markets']:
                if market.get('closed') or not market.get('enableOrderBook', True):
                    continue
                tokens = (json.loads(market['clobTokenIds']) if isinstance(market['clobTokenIds'], str)
                          else market['clobTokenIds'])
                outcomes = json.loads(market['outcomes']) if isinstance(market['outcomes'], str) else market['outcomes']
                if outcomes != ['Yes', 'No'] or len(tokens) != 2 or len(set(tokens)) != 2:
                    continue
                condition = str(market['conditionId'])
                rows.append({'event_slug': slug, 'event_condition_ids': conditions, 'condition_id': condition,
                             'token_ids': tokens, 'market_end_utc': market.get('endDate'),
                             'snapshot': self.snapshot(condition, tokens, checkpoint=checkpoint)})
        return rows


# ----- queue-ahead (cheap: derived from snapshots RE-1 already reads; no new network call) -------------------------
def visible_at_price(snapshot, token_index, price):
    key = 'yes_bids' if token_index == 0 else 'no_bids'
    try:
        levels = _levels(snapshot['quote_inputs'][key])
    except (QuoteRefused, KeyError):
        return None
    return str(sum((s for p, s in levels if p == number(price)), Decimal(0)))


# ----- notification (PR section 5, P8) ----------------------------------------------------------------------------
_TOAST = (
    "$ErrorActionPreference = 'Stop'; "
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] "
    "| Out-Null; "
    "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
    "$x = $t.GetElementsByTagName('text'); "
    "$x.Item(0).AppendChild($t.CreateTextNode('Weather live-fill calibration')) | Out-Null; "
    "$x.Item(1).AppendChild($t.CreateTextNode($env:LFC_NOTIFY_TEXT)) | Out-Null; "
    "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'; "
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
    "[Windows.UI.Notifications.ToastNotification]::new($t))")


def result_line(summary):
    keys = ('session_id', 'reason', 'cleanup_ok', 'panic', 'L', 'L_filled', 'L_resting', 'open_orders', 'fills')
    return 'LFC-RESULT ' + ' '.join(f'{k}={summary.get(k)}' for k in keys)


def notify_owner(root, summary, *, runner=subprocess.run, printer=print, windows=None):
    """Default channel (owner ruling, P8): a Windows desktop toast on the workstation plus a one-line session result
    for the master agent to relay. No third-party service and no credential. Never raises; returns the
    notification record (delivered or the recorded failure), which goes into session_end.json."""
    line = result_line(summary)
    record = {'channel': 'windows_toast+result_line', 'result_line': line, 'toast_delivered': False,
              'toast_error': None, 'at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        printer(line, flush=True)
        record['result_line_printed'] = True
    except Exception as exc:
        record['result_line_printed'] = False
        record['result_line_error'] = type(exc).__name__
    try:
        if not (os.name == 'nt' if windows is None else windows):
            raise RuntimeError('toast_requires_windows')
        done = runner(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command',
                       _TOAST], env={**os.environ, 'LFC_NOTIFY_TEXT': line[:240]}, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, timeout=30, check=False)
        if getattr(done, 'returncode', 1) != 0:
            raise RuntimeError('toast_exit_' + str(getattr(done, 'returncode', None)))
        record['toast_delivered'] = True
    except Exception as exc:
        record['toast_error'] = (str(exc) if isinstance(exc, RuntimeError) and str(exc).replace('_', '').isalnum()
                                 else type(exc).__name__)
    try:
        path = Path(root) / 'notifications.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, sort_keys=True) + '\n')
    except Exception:
        record['notification_log_failed'] = True
    return record


def write_session_end(directory, payload):
    """session_end.json (PR sections 5 and 7): reason, L, open orders, fills, notification. Never overwritten."""
    body = {'schema_version': SESSION_END_SCHEMA, 'kind': 'lfc_session_end', **payload}
    return write_new(Path(directory) / 'session_end.json', body)


# ----- the session ----------------------------------------------------------------------------------------------
class PilotSession(Session):
    PROTOCOL = LFC.PROTOCOL
    MAX_SESSIONS = LFC.MAX_SESSIONS

    def __init__(self, *, ledger, session_id, profile, root=None, exclusion=None, cap=LFC.BUDGET_PUSD,
                 baselines=None, **kwargs):
        # Hooks run inside Session.__init__, so campaign state is set first.
        self.ledger, self.session_id, self.profile = ledger, session_id, profile
        self.root, self.exclusion, self.baselines = root, exclusion, baselines or {}
        self.TREATMENT, self.SECONDS = profile.treatment, profile.seconds
        self.REWARD_TERMS = not profile.session0
        self.OFFSET = LFC.SESSION0_OFFSET if profile.session0 else LFC.RE1_OFFSET
        self.REQUOTE_WINDOW = LFC.SESSION0_REQUOTE_WINDOW if profile.session0 else LFC.RE1_REQUOTE_WINDOW
        self.cap = number(cap)
        self.posted_at = None
        self.dropped = self.stalled = False
        self.dropped_at = None  # 0d/0g: monotonic time the heartbeat sends stopped
        self.venue_deadman_observed = None  # 0g: the first terminal reads that proved the venue cancel
        self.cancels_since_drop = 0  # delta review N-2: cancel requests this process journalled after the drop
        if kwargs.get('mode') == 'live' and (ledger is None or not session_id or root is None):
            raise LedgerUnavailable('ledger_required')
        if not profile.session0 and kwargs.get('mode') == 'live' and not exclusion:
            raise RuntimeError('panel_exclusion_required')
        table = kwargs['table']
        if profile.session0:
            selected = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
            profile.bind_size(selected['quote']['size'])
        self.SIZES = profile.SIZES
        self.BAND_CEILING = Decimal('.98') * profile.size  # band cap of PR section 6 (39.2 at 40)
        super().__init__(**kwargs)
        chosen = next(r for r in table['rows'] if r['condition_id'] == table['selected_condition_id'])
        opening = chosen['snapshot'].get('rules')
        self.opening_rules = ({t: dict(opening[t]) for t in self.tokens}
                              if isinstance(opening, dict) and all(t in opening for t in self.tokens) else None)
        if ledger is not None:
            # Bounded trade reads (review F-6): only trades after the campaign genesis, before any of our orders.
            self.venue.trades_after = str(int(utc(ledger.rows[0]['recorded_at_utc']).timestamp()))
            self.venue.trades_seconds = LFC.TRADE_READ_SECONDS
        self.scope.update(session_id=session_id, session0=profile.session0, session0_run=profile.run,
                          pilot_size=str(profile.size), budget_pusd=str(LFC.BUDGET_PUSD))

    # profile hooks ------------------------------------------------------------------------------------------
    def session_seconds(self, realtime_rehearsal):
        return 900 if realtime_rehearsal else self.profile.seconds

    def caps(self, size, available_collateral):
        size = number(size)
        if size not in self.SIZES:
            raise HoldEnd('treatment_size')
        return Decimal('.79') * size, Decimal('.98') * size

    def start_allowed(self, now):
        return not start_refusals(self.start, session0=self.profile.session0,
                                  seconds=(self.end - self.start).total_seconds()) and utc(now) <= hard_stop(self.start)

    def session_number_ok(self):
        if not self.attempt:
            return False
        if self.profile.session0:
            return self.attempt.get('counted') is False and self.attempt.get('session_number') == 0
        return self.attempt.get('counted') is True and 1 <= self.attempt.get('session_number', 0) <= self.MAX_SESSIONS

    def validate_table(self, table):
        if self.profile.session0:
            validate_session0_table(table, now=self.start)
        else:
            if table.get('size_treatment') != LFC.TREATMENT:
                raise ValueError('pilot table treatment differs')
            super().validate_table(table)

    def _ledger(self, fn):
        try:
            return fn()
        except LedgerUnavailable:
            raise HoldEnd('ledger_unavailable') from None

    def _gate(self, *, own_resting=Decimal(0)):
        reserve = band_reserve(self.size, self.prices)
        try:
            base = self._ledger(lambda: self.ledger.post_gate(reserve=reserve, own_resting=own_resting, cap=self.cap))
        except LedgerCap as exc:
            raise HoldEnd(str(exc)) from None
        return reserve, base

    def _cash(self, balances, reserve):
        resting = self._ledger(self.ledger.L_resting)
        cash = number(balances['available_collateral'])
        if cash < resting + reserve:
            raise HoldEnd('cash_below_l_resting_plus_reserve')
        return cash, resting

    def initial_capital_ok(self, balances):
        if self.profile.run == '0e':
            # S0 run 0e: the L budget is set below the reserve of the selected quote; the gate must refuse.
            self.cap = self._ledger(self.ledger.L) + band_reserve(self.size, self.prices) - Decimal('.01')
            self.journal.record('lfc_session0_test_flag', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run='0e',
                                cap=str(self.cap))
        reserve, base = self._gate()
        cash, resting = self._cash(balances, reserve)
        self.journal.record('lfc_l_gate', lfc_journal_schema=LFC_JOURNAL_SCHEMA, phase='band', L=str(base),
                            reserve=str(reserve), cap=str(self.cap), L_resting=str(resting),
                            available_collateral=str(cash))
        return True

    def before_first_post(self):
        """Selection, baseline and panel-exclusion records before the first post (PR sections 3-5)."""
        selection = self.directory / 'selection.json'
        try:
            selection_sha = hashlib.sha256(selection.read_bytes()).hexdigest()
        except OSError:
            raise HoldEnd('selection_file_missing') from None
        if selection_sha != digest(self.table) and self.mode == 'live':
            raise HoldEnd('selection_file_differs')
        self.journal.record('lfc_selection', lfc_journal_schema=LFC_JOURNAL_SCHEMA, file='selection.json',
                            sha256=selection_sha, baselines=self.baselines)
        if self.profile.session0:
            return
        lines = exclusion_lines(**self.exclusion, session_id=self.session_id, start=self.start, end=self.end,
                                appended=self.clock.now())
        try:
            shas = append_exclusions(self.root, lines)
        except (OSError, ValueError):
            raise HoldEnd('panel_exclusion_write_failed') from None
        for line, sha in zip(lines, shas):
            self.journal.record('lfc_panel_exclusion', lfc_journal_schema=LFC_JOURNAL_SCHEMA, line_sha256=sha, **line)

    def authorize_post(self, leg, price, size, rule):
        own = sum((self.size * p for _, p in self.active.values()), Decimal(0))
        reserve, base = self._gate(own_resting=own)
        record = {'phase': 'post', 'leg': leg, 'L_after_cancel_of_replaced_leg': str(base), 'reserve': str(reserve),
                  'cap': str(self.cap)}
        if self.submits >= 2:
            # A requote: the cash rule is re-read against a fresh balance (PR section 6).
            balances = self.required('requote_balances', self.venue.balances)
            cash, resting = self._cash(balances, reserve)
            record.update(available_collateral=str(cash), L_resting=str(resting))
        self.journal.record('lfc_l_gate', lfc_journal_schema=LFC_JOURNAL_SCHEMA, **record)
        fee = fee_refusal({self.tokens[leg]: rule}, [self.tokens[leg]])
        if fee:
            self.journal.record('lfc_fee_rule', lfc_journal_schema=LFC_JOURNAL_SCHEMA, phase='submit', leg=leg,
                                refusal=fee)
            raise HoldEnd(fee)
        self._pending = {'token_id': self.tokens[leg], 'price': price, 'size': size,
                         'fee_rate_bps': rule['fee_rate_bps']}

    def post_intent(self, request):
        # Persisted before the raw POST; a failed write raises inside the venue before anything is posted.
        pending = getattr(self, '_pending', None)
        if (pending is None or pending['token_id'] != request['token_id'] or
                number(pending['price']) != number(request['price']) or number(pending['size']) != number(request['size'])):
            raise LedgerUnavailable('ledger_intent_binding')
        self.ledger.intent(session_id=self.session_id, intent_key=f'{self.session_id}:{self.posts}',
                           token_id=request['token_id'], condition_id=self.condition, price=request['price'],
                           size=request['size'], fee_rate_bps=pending['fee_rate_bps'])
        self._pending = None

    def posted(self, oid, leg, price):
        self.ledger.ack(f'{self.session_id}:{self.posts}', oid)
        snapshot = getattr(self, 'submit_snapshot', None)
        self.journal.record('lfc_queue_ahead', lfc_journal_schema=LFC_JOURNAL_SCHEMA, phase='placement',
                            order_id=oid, leg=leg, token_id=self.tokens[leg], price=str(price),
                            own_size=str(self.size), visible_at_price=visible_at_price(snapshot, leg, price)
                            if snapshot else None, snapshot_observed_at_utc=snapshot and snapshot['observed_at_utc'])

    def minute_extra(self, snapshot):
        # Review F-9: every market rule of our tokens is compared each minute; any change (or fee != 0) ends.
        rules = snapshot.get('rules')
        if not isinstance(rules, dict) or self.opening_rules is None:
            raise HoldEnd('market_rules')
        changed = sorted(t for t in self.tokens if _rule_key(rules.get(t)) != _rule_key(self.opening_rules[t]))
        fee = fee_refusal(rules, self.tokens)
        if changed or fee:
            self.journal.record('lfc_market_rules_changed', lfc_journal_schema=LFC_JOURNAL_SCHEMA, tokens=changed,
                                fee_refusal=fee)
            raise HoldEnd(fee if fee and not changed else 'market_rules')
        for oid, (leg, price) in self.active.items():
            self.journal.record('lfc_queue_ahead', lfc_journal_schema=LFC_JOURNAL_SCHEMA, phase='book_update',
                                order_id=oid, leg=leg, token_id=self.tokens[leg], price=str(price),
                                own_size=str(self.size), visible_at_price=visible_at_price(snapshot, leg, price),
                                snapshot_observed_at_utc=snapshot['observed_at_utc'])

    def leg_terminal(self, oid, row):
        self.ledger.terminal(oid, row, source='session')

    def cancel_terminal_row(self, oid, row):
        """Review F-3: the pre-poll read can still say LIVE. Re-read (bounded) until terminal before L_resting is
        released; if it never is, the leg stays reserved in L and the session ends with cancel_not_terminal."""
        for _ in range(10):
            if filled(row):
                self.fill_seen = True
                raise HoldEnd('fill')
            if _terminal(row):
                return row
            self._alive()
            self.clock.sleep(1)
            row = self.required('cancel_terminal_read', lambda: self.venue.order(oid), checkpoint=False, order_id=oid)
        if filled(row):
            self.fill_seen = True
            raise HoldEnd('fill')
        if _terminal(row):
            return row
        self.journal.record('lfc_cancel_not_terminal', lfc_journal_schema=LFC_JOURNAL_SCHEMA, order_id=oid,
                            status=str((row or {}).get('status')))
        raise HoldEnd('cancel_not_terminal')

    def call(self, name, fn, **request):
        # Delta review N-2: every cancel request this process sends after the 0d/0g drop is counted before it is
        # sent; the 0g proof needs the count to be 0 (the cleanup's safety cancel follows the proof and is separate).
        if self.dropped and name in ('cancel', 'cancel_all'):
            self.cancels_since_drop += 1
        return super().call(name, fn, **request)

    def cancel_leg(self, oid):
        if self.profile.run == '0g' and self.dropped:
            # Our own cancel would contaminate the venue dead-man proof: end through the cleanup instead (no pass).
            raise HoldEnd('venue_deadman_requote_needed')
        return super().cancel_leg(oid)

    def check_fills(self, *, canceling=None, force=False):
        try:
            return super().check_fills(canceling=canceling, force=force)
        except HoldEnd as exc:
            if exc.reason == 'order_no_longer_resting' and self.profile.run == '0g' and self.dropped:
                self._venue_deadman_observe()
            if exc.reason == 'unknown_user_event':
                self._stream_foreign_check('unknown_user_event')
            raise
        except RuntimeError as exc:
            if str(exc) != 'user_stream_invalid_event':
                raise
            self._stream_foreign_check('user_stream_invalid_event')

    def _stream_foreign_check(self, code):
        """Review F-2: an account order event on a token outside the session (the owner's 0b order) fails the user
        stream; it ends as foreign_open_order (with a forced account read for the record). Any other stream failure
        ends with its own code instead of the generic 'exception'."""
        stream = getattr(self.venue, 'stream', None)
        failed = getattr(stream, 'failed_event', None)
        maker = str(getattr(self.venue, 'maker', '')).lower()
        stream_foreign = (isinstance(failed, dict) and str(failed.get('event_type', '')).lower() == 'order' and
                          str(failed.get('asset_id')) not in self.tokens and
                          str(failed.get('maker_address') or maker).lower() == maker)
        try:
            rows = self.required('account_open_orders', self.venue.open_orders, checkpoint=False)
        except Exception as exc:
            rows = None
            self.journal.record('read_unavailable', fact='account_open_orders', exception_type=type(exc).__name__)
        foreign = [_order_id(r) for r in rows if not self._ours(r)] if isinstance(rows, list) else None
        if stream_foreign or foreign:
            self.journal.record('lfc_foreign_open_order', lfc_journal_schema=LFC_JOURNAL_SCHEMA, order_ids=foreign,
                                source='user_stream', stream_code=code,
                                stream_order_id=failed.get('id') if stream_foreign else None)
            raise HoldEnd('foreign_open_order') from None
        self.journal.record('lfc_user_stream_failed', lfc_journal_schema=LFC_JOURNAL_SCHEMA, code=code)
        raise HoldEnd(code) from None

    def positions_mean_fill(self, positions):
        # Existing wallet (PR section 7 change): fills are attributed by our order ids only.
        return False

    def _ours(self, row):
        oid = _order_id(row)
        if oid in self.known:
            return True
        # A posted-but-unacknowledged intent is ours too: match it on token, price, size and side.
        for leg in self.ledger.unresolved_legs():
            if (leg['session_id'] == self.session_id and leg['order_id'] is None and
                    str(row.get('asset_id') or row.get('token_id')) == leg['token_id'] and
                    number(row.get('price', -1)) == number(leg['price']) and
                    number(row.get('original_size', -1)) == number(leg['size']) and row.get('side') == 'BUY'):
                return True
        return False

    def after_open(self):
        self.posted_at = self.clock.monotonic()

    def extra_checks(self, *, force=False):
        stopped = self._ledger(self.ledger.stop_reason)
        if stopped:
            raise HoldEnd(stopped)
        if not self.submits:
            return
        # Review F-7: the account read's budget runs from the first post (while the band is being posted, from now).
        self._session0_flags()
        self._venue_deadman_deadline()
        rows = self.freshness.read('account_open_orders', lambda: self.call('account_open_orders', self.venue.open_orders),
                                   cadence=LFC.FOREIGN_CHECK_SECONDS, budget=3 * LFC.FOREIGN_CHECK_SECONDS,
                                   initial=self.clock.monotonic() if self.posted_at is None else self.posted_at)
        if rows is None:
            return
        if not isinstance(rows, list):
            raise HoldEnd('account_open_orders_unreadable')
        foreign = [_order_id(r) for r in rows if not self._ours(r)]
        if foreign:
            self.journal.record('lfc_foreign_open_order', lfc_journal_schema=LFC_JOURNAL_SCHEMA, order_ids=foreign)
            raise HoldEnd('foreign_open_order')

    def _session0_flags(self):
        """S0 runs 0d/0g (heartbeat sends stop, main loop alive) and 0f (main-loop stall), 120 s after posting.
        0g also disables the script's 8 s stale end, so only the venue dead-man can cancel (review F-1)."""
        if self.posted_at is None or self.clock.monotonic() - self.posted_at < LFC.SESSION0_DROP_AFTER_SECONDS:
            return
        if self.profile.run in ('0d', '0g') and not self.dropped:
            self.dropped, self.dropped_at = True, self.clock.monotonic()
            self.heartbeat_loop.drop_sends()
            if self.profile.run == '0g':
                self.heartbeat_loop.disable_stale_cleanup()
            self.journal.record('lfc_session0_test_flag', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run=self.profile.run,
                                action='heartbeat_sends_stopped', script_stale_cleanup=self.profile.run != '0g',
                                last_heartbeat_ack=self.heartbeat_loop.last_ack, at_monotonic=self.dropped_at)
        if self.profile.run == '0f' and not self.stalled:
            self.stalled = True
            self.journal.record('lfc_session0_test_flag', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run='0f',
                                action='main_loop_stall', seconds=LFC.SESSION0_STALL_SECONDS)
            self.clock.sleep(LFC.SESSION0_STALL_SECONDS)  # no tick: the watchdog must stop the heartbeat sends
            self.heartbeat_loop.check()

    def _venue_deadman_reads(self):
        rows = {}
        for oid in list(self.active):
            row = None
            for _ in range(10):
                row = self.required('venue_deadman_order', lambda: self.venue.order(oid), checkpoint=False, order_id=oid)
                if _terminal(row):
                    break
                self._alive()
                self.clock.sleep(1)
            rows[oid] = row
        return rows

    def _venue_deadman_observe(self):
        """0g: an order of ours stopped resting with no cancel from us. Record the first terminal read of each leg
        (the proof) and end; the cleanup cancel that follows is a recorded safety step, not part of the proof."""
        rows = self._venue_deadman_reads()
        seconds = self.clock.monotonic() - self.dropped_at
        self.venue_deadman_observed = {'seconds_after_drop': seconds, 'order_ids': sorted(rows)}
        self.journal.record('lfc_venue_deadman_first_terminal', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run='0g',
                            seconds_after_drop=seconds, rows=rows,
                            own_cancel_requests_since_drop=self.cancels_since_drop,
                            all_terminal=all(_terminal(r) for r in rows.values()))
        if any(filled(r) for r in rows.values()):
            self.fill_seen = True
            raise HoldEnd('fill')
        if rows and all(_terminal(r) for r in rows.values()) and self.cancels_since_drop == 0:
            raise HoldEnd('venue_deadman_cancelled')
        raise HoldEnd('order_no_longer_resting')

    def _venue_deadman_deadline(self):
        """0g hard wall-clock cap: at window + margin after the drop, read our orders; if any still rests, the venue
        dead-man was not observed: the campaign ledger records a halt and the run ends through the cleanup."""
        if self.profile.run != '0g' or self.dropped_at is None:
            return
        if (self.clock.monotonic() - self.dropped_at <
                LFC.SESSION0_VENUE_WINDOW_SECONDS + LFC.SESSION0_VENUE_MARGIN_SECONDS):
            return
        rows = {}
        for oid in list(self.active):
            rows[oid] = self.required('venue_deadman_order', lambda: self.venue.order(oid), checkpoint=False,
                                      order_id=oid)
        if rows and all(_terminal(r) for r in rows.values()):
            self._venue_deadman_observe()
        self.journal.record('lfc_venue_deadman_not_observed', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run='0g',
                            seconds_after_drop=self.clock.monotonic() - self.dropped_at, rows=rows)
        try:
            self.ledger.record('halt', reason='venue_deadman_not_observed', session_id=self.session_id)
        except LedgerUnavailable:
            self.evidence_failed = True
        raise HoldEnd('venue_deadman_not_observed')

    def initial_positions_ok(self, rows):
        # Existing wallet (PR section 7): positions outside the selected event are the owner's and are pinned by the
        # baselines; a position in any condition of the selected event refuses (event-level exclusion, PR section 3).
        if not isinstance(rows, list):
            return False
        selected = next(r for r in self.table['rows'] if r['condition_id'] == self.condition)
        event = {str(c).lower() for c in selected['event_condition_ids']}
        try:
            held = set(position_conditions(rows))
        except (QuoteRefused, ValueError):
            return False
        self.journal.record('lfc_initial_positions', lfc_journal_schema=LFC_JOURNAL_SCHEMA, rows=len(rows),
                            event_conditions_held=sorted(held & event))
        return not held & event

    def cleanup(self):
        if self.closed:
            return self.cleanup_ok
        if self.profile.run in ('0d', '0g') and self.submits:
            # Review F-1b: the first terminal read of each leg BEFORE our cleanup cancel; the per-leg
            # cleanup_cancel_response follows in the RE-1 cleanup. That cancel is a safety step, never the proof.
            # Delta review N-3: one attempt per leg, no retry, so the safety cancel is not delayed; the RE-1
            # cleanup's own terminal reads follow the cancel.
            rows = {}
            for oid in list(self.known):
                try:
                    rows[oid] = self.venue.order(oid)
                except BaseException as exc:
                    rows[oid] = None
                    self._retain('lfc_first_terminal_order_read_unavailable', order_id=oid,
                                 exception_type=type(exc).__name__)
            self._retain('lfc_first_terminal_order_read', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run=self.profile.run,
                         rows=rows, before_cleanup_cancel=True, venue_deadman_observed=self.venue_deadman_observed)
            self._retain('lfc_session0_safety_cancel', lfc_journal_schema=LFC_JOURNAL_SCHEMA, run=self.profile.run,
                         part_of_proof=False, order_ids=list(self.active))
        ok = super().cleanup()
        if self.submits:
            self.reconcile_trades()
        return ok

    def reconcile_trades(self, *, attempts=5, pause=2):
        """L from venue trades at cleanup (PR section 6). Trade reads can lag a terminal order read, so a
        disagreement is re-read before it is recorded as a mismatch (which stops the campaign for good)."""
        try:
            for attempt in range(attempts):
                trades = self._recover('lfc_trades', self.venue.trades)
                traded = traded_shares(trades, self.ledger.our_order_ids())
                found = self.ledger.trade_mismatches(traded)
                self._retain('lfc_trade_reconcile', lfc_journal_schema=LFC_JOURNAL_SCHEMA, attempt=attempt,
                             traded=traded, mismatches=found)
                if not found:
                    return []
                if attempt + 1 < attempts:
                    self.clock.sleep(pause)
            for row in found:
                self.ledger.record('mismatch', source='cleanup', **row)
            return found
        except BaseException:
            self.evidence_failed = True
            return None
