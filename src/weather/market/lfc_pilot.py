"""Live-fill calibration pilot: the RE-1 controller with the 40-share size, the L-ledger gate and session 0.

Owner approval 2026-10-09 (relayed by master-agent 14:40, scope changes 14:50 and 14:55). Design:
docs/research/live-fill-calibration-design-2026-10-09.md. The quote, requote rule, stop-on-fill and every RE-1 hard
limit are inherited unchanged from weather.market.re1_attended.Session; this module only overrides its profile hooks.

Hard limits added here (each ends the session through RE-1's cleanup: cancel our orders, then reconcile):
  * L-ledger gate: a placement is refused when L + its worst case would exceed the cap; the session halts when
    L >= cap. Missing or unreadable ledger state refuses (weather.market.lfc_ledger).
  * Account-wide foreign-order check every FOREIGN_CHECK_SECONDS: any open order that is not one of ours ends
    the session. Cleanup cancels OUR orders only; the owner's foreign order is left untouched and reported.
  * Earliest start: no counted session before lfc_constants.EARLIEST_START_UTC.
  * Session 0 (explicit flag only): uncounted, SESSION0_SIZE, refused on any built-in weather market or anything
    in 88a's retained scope; forced limits for the shakeout are accepted only in session 0.

Dead-man (inherited from RE-1, unchanged): the exchange heartbeat (/v1/heartbeats) is sent every 2 s by a
separate thread (re1_resilience.HeartbeatLoop). The thread stops sending when the main loop has not ticked for
20 s or the last acknowledgment is 8 s old. The venue cancels ALL of the account's open orders when it stops
receiving heartbeats (about 10 s plus its buffer), so a hung or killed process leaves zero resting orders. Every
order is also GTD with expiration = fixed session end + 60 s, so even a lost heartbeat contract cannot leave an
order resting past the session. A normal crash additionally runs Session.cleanup via finally/atexit.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

from weather.market import lfc_constants as LFC
from weather.market.lfc_ledger import LedgerCap, LedgerUnavailable, order_worst
from weather.market.market_config import event_slug_for_date, market_id_from_slug
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import HoldEnd, _order_id, _cancel_ack_ids, digest, utc, SCHEMA_VERSION
from weather.market.re1_attended import Session, number
from weather.market.re1_sizing import pilot_quote
from weather.market.reward_quote import QuoteRefused, _levels

LFC_JOURNAL_SCHEMA = 'lfc_journal_v0.1'  # additive events inside the unchanged RE-1 hold-journal chain


def pilot_root():
    """Fixed across worktrees and tips (the budget spans every session); no override for live."""
    if os.name != 'nt':
        raise RuntimeError('campaign_requires_windows_token')
    from weather.market.live_sdk_overlay import _windows_token_profile_root
    return _windows_token_profile_root() / '.weather-lfc-20261009'


# ----- dates ----------------------------------------------------------------------------------------------------
def start_refusal(now, *, session0=False):
    """None when a session may start at `now`, else the refusal reason."""
    now = utc(now)
    if session0:
        return None
    if now < LFC.EARLIEST_START_UTC:
        return 'before_earliest_start'
    return None


# ----- profiles -------------------------------------------------------------------------------------------------
class PilotProfile:
    def __init__(self, *, session0=False, force=None):
        if force is not None and (not session0 or force not in LFC.FORCE_LIMITS):
            raise ValueError('forced_limits_are_session0_only')
        self.session0, self.force = session0, force
        self.SIZES = (LFC.SESSION0_SIZE,) if session0 else (LFC.PILOT_SIZE,)
        self.size = self.SIZES[0]
        self.treatment = LFC.SESSION0_TREATMENT if session0 else LFC.TREATMENT
        self.seconds = LFC.SESSION0_FORCED_SECONDS if force == 'fixed_end' else LFC.SESSION_SECONDS

    def venue_ceiling(self, size):
        size = number(size)
        if size not in self.SIZES:
            raise RuntimeError('capital_cap')
        return Decimal('.79') * size, Decimal('.98') * size


# ----- session 0 scope ------------------------------------------------------------------------------------------
def session0_refusals(*, event_slug, condition_id, now, extras_88a):
    """Session 0 must sit outside every panel: no built-in weather event (any date), no temperature event at all,
    and no condition in 88a's retained extras list (which must be supplied explicitly, possibly empty)."""
    refusals = []
    slug = str(event_slug or '').lower()
    if not slug:
        refusals.append('session0_event_slug_missing')
    if market_id_from_slug(slug) is not None:
        refusals.append('session0_built_in_market')
    if any(slug.startswith(spec.slug_prefix) for spec in REGISTRY.values()):
        refusals.append('session0_built_in_market')
    today = utc(now).date()
    if any(slug == event_slug_for_date(today + timedelta(days=d), m) for m in REGISTRY for d in range(-60, 61)):
        refusals.append('session0_built_in_band')
    if 'temperature' in slug or 'weather' in slug:
        refusals.append('session0_weather_market')
    if extras_88a is None:
        refusals.append('session0_88a_scope_unknown')
    elif str(condition_id).lower() in {str(c).lower() for c in extras_88a}:
        refusals.append('session0_in_88a_scope')
    return sorted(set(refusals))


def session0_table(*, band, now, available_collateral, headroom, extras_88a, extras_sha256):
    """Build the one-row session-0 selection from a public snapshot of the owner-named condition."""
    refusals = session0_refusals(event_slug=band['event_slug'], condition_id=band['condition_id'], now=now,
                                 extras_88a=extras_88a)
    if refusals:
        raise ValueError('session0_scope: ' + ','.join(refusals))
    quote = pilot_quote(band['snapshot'], size=LFC.SESSION0_SIZE, headroom=headroom,
                        available_collateral=available_collateral, budget=LFC.BUDGET_PUSD)
    row = {**band, 'eligible': True, 'refusal': None,
           'quote': {k: str(getattr(quote, k)) if isinstance(getattr(quote, k), Decimal) else getattr(quote, k)
                     for k in quote.__dataclass_fields__},
           'predicted_360_minutes': quote.predicted_per_minute_many * 360}
    return {'size_treatment': LFC.SESSION0_TREATMENT, 'available_collateral': str(number(available_collateral)),
            'pilot_headroom_pusd': str(number(headroom)), 'pilot_size': str(LFC.SESSION0_SIZE),
            'schema_version': SCHEMA_VERSION, 'kind': 'selection', 'created_at_utc': utc(now).isoformat(),
            'target_date': None, 'universe_complete': True, 'source_records': [],
            'session0_scope': {'extras_88a_sha256': extras_sha256, 'extras_88a_count': len(extras_88a),
                               'refusals': []},
            'rows': [row], 'ranked_conditions': [band['condition_id']], 'selected_condition_id': band['condition_id']}


def validate_session0_table(table, *, now, extras_88a):
    if (table.get('size_treatment') != LFC.SESSION0_TREATMENT or table.get('kind') != 'selection' or
            table.get('schema_version') != SCHEMA_VERSION or len(table.get('rows', ())) != 1 or
            not 0 <= (utc(now) - utc(table['created_at_utc'])).total_seconds() <= 1800):
        raise ValueError('session0 table is stale or malformed')
    row = table['rows'][0]
    original = {k: v for k, v in row.items() if k not in {'eligible', 'refusal', 'quote', 'predicted_360_minutes'}}
    rebuilt = session0_table(band=original, now=table['created_at_utc'], available_collateral=table['available_collateral'],
                             headroom=table['pilot_headroom_pusd'], extras_88a=extras_88a,
                             extras_sha256=table['session0_scope']['extras_88a_sha256'])
    if rebuilt != table:
        raise ValueError('session0 table does not reproduce')
    return row


# ----- queue-ahead (cheap: derived from snapshots RE-1 already reads; no new network call) -------------------------
def visible_at_price(snapshot, token_index, price):
    key = 'yes_bids' if token_index == 0 else 'no_bids'
    try:
        levels = _levels(snapshot['quote_inputs'][key])
    except (QuoteRefused, KeyError):
        return None
    return str(sum((s for p, s in levels if p == number(price)), Decimal(0)))


# ----- notification ---------------------------------------------------------------------------------------------
_BALLOON = (
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
    "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
    "$n.Visible = $true; $n.ShowBalloonTip(60000, 'Weather LFC session ended', $env:LFC_NOTIFY_TEXT, 'Info'); "
    "Start-Sleep -Seconds 65; $n.Dispose()")


def notify_owner(root, summary, *, runner=subprocess.Popen, printer=print):
    """Local, credential-free end-of-session notice: an append-only notice file, a console bell and a Windows
    balloon. RE-1 and the repo have no notifier, so this is the minimal local one. It never raises."""
    text = (f"session {summary.get('session_id')} ended: reason={summary.get('reason')} "
            f"cleanup_ok={summary.get('cleanup_ok')} fill_seen={summary.get('fill_seen')} L={summary.get('L')}")
    delivered = []
    try:
        path = Path(root) / 'notifications.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at_utc': datetime.now(timezone.utc).isoformat(), 'text': text,
                                     **{k: str(v) for k, v in summary.items()}}, sort_keys=True) + '\n')
        delivered.append('file')
    except Exception:
        pass
    try:
        printer('\a' + text, flush=True)
        delivered.append('console')
    except Exception:
        pass
    try:
        if os.name == 'nt':
            runner(['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', _BALLOON],
                   env={**os.environ, 'LFC_NOTIFY_TEXT': text}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            delivered.append('balloon')
    except Exception:
        pass
    return delivered


# ----- the session ----------------------------------------------------------------------------------------------
class PilotSession(Session):
    PROTOCOL = LFC.PROTOCOL
    MAX_SESSIONS = LFC.MAX_SESSIONS

    def __init__(self, *, ledger, session_id, profile, cap=LFC.BUDGET_PUSD, extras_88a=None, **kwargs):
        # Hooks run inside Session.__init__, so pilot state is set first.
        self.ledger, self.session_id, self.profile = ledger, session_id, profile
        self.SIZES, self.TREATMENT, self.SECONDS = profile.SIZES, profile.treatment, profile.seconds
        self.BAND_CEILING = profile.size
        self.cap = number(cap)
        self.extras_88a = extras_88a
        self.forced_foreign = False
        self.dead_man = None
        if kwargs.get('mode') == 'live' and (ledger is None or not session_id):
            raise LedgerUnavailable('ledger_required')
        super().__init__(**kwargs)
        self.scope.update(session_id=session_id, session0=profile.session0, force=profile.force,
                          pilot_size=str(profile.size), budget_pusd=str(LFC.BUDGET_PUSD))

    # profile hooks ------------------------------------------------------------------------------------------
    def session_seconds(self, realtime_rehearsal):
        return 900 if realtime_rehearsal else self.profile.seconds

    def caps(self, size, available_collateral):
        size = number(size)
        if size not in self.SIZES:
            raise HoldEnd('treatment_size')
        headroom = number(self.table.get('pilot_headroom_pusd', 0)) if hasattr(self, 'table') else Decimal(0)
        return Decimal('.79') * size, min(Decimal('.98') * size, headroom)

    def start_allowed(self, now):
        return start_refusal(now, session0=self.profile.session0) is None

    def session_number_ok(self):
        if not self.attempt:
            return False
        if self.profile.session0:
            return self.attempt.get('counted') is False and self.attempt.get('session_number') == 0
        return self.attempt.get('counted') is True and 1 <= self.attempt.get('session_number', 0) <= self.MAX_SESSIONS

    def validate_table(self, table):
        if self.profile.session0:
            validate_session0_table(table, now=self.start, extras_88a=self.extras_88a)
        else:
            if table.get('size_treatment') != LFC.TREATMENT:
                raise ValueError('pilot table treatment differs')
            super().validate_table(table)

    def initial_capital_ok(self, balances):
        try:
            current = self.ledger.L()
        except LedgerUnavailable:
            raise HoldEnd('ledger_unavailable') from None
        rules = self.table['rows'][0]['snapshot'].get('rules', {}) if self.profile.session0 else next(
            r for r in self.table['rows'] if r['condition_id'] == self.condition)['snapshot'].get('rules', {})
        worst = sum((order_worst(p, self.size, rules.get(t, {}).get('fee_rate_bps', '0'))
                     for p, t in zip(self.prices, self.tokens)), Decimal(0))
        cash = number(balances['available_collateral'])
        self.band_cap = min(self.band_cap, self.cap - current)
        self.journal.record('lfc_ledger_gate', lfc_journal_schema=LFC_JOURNAL_SCHEMA, L=str(current), cap=str(self.cap),
                            band_worst=str(worst), available_collateral=str(cash))
        return current + worst <= self.cap and cash >= current + worst

    def authorize_post(self, leg, price, size, rule):
        try:
            self.ledger.check_new(price=price, size=size, fee_rate_bps=rule['fee_rate_bps'], cap=self.cap)
        except LedgerCap as exc:
            raise HoldEnd(str(exc)) from None
        except LedgerUnavailable:
            raise HoldEnd('ledger_unavailable') from None
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
        for oid, (leg, price) in self.active.items():
            self.journal.record('lfc_queue_ahead', lfc_journal_schema=LFC_JOURNAL_SCHEMA, phase='book_update',
                                order_id=oid, leg=leg, token_id=self.tokens[leg], price=str(price),
                                own_size=str(self.size), visible_at_price=visible_at_price(snapshot, leg, price),
                                snapshot_observed_at_utc=snapshot['observed_at_utc'])

    def leg_terminal(self, oid, row):
        self.ledger.terminal(oid, row, source='session')

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

    def extra_checks(self, *, force=False):
        try:
            current = self.ledger.L()
        except LedgerUnavailable:
            raise HoldEnd('ledger_unavailable') from None
        if self.submits and current >= self.cap:
            raise HoldEnd('ledger_cap_reached')
        if not self.submits:
            return
        rows = self.freshness.read('account_open_orders', lambda: self.call('account_open_orders', self.venue.open_orders),
                                   cadence=LFC.FOREIGN_CHECK_SECONDS, budget=3 * LFC.FOREIGN_CHECK_SECONDS)
        if rows is None:
            return
        if not isinstance(rows, list):
            raise HoldEnd('account_open_orders_unreadable')
        hidden = set()
        if self.profile.force == 'foreign_order' and len(self.active) == 2:
            # Forced test trigger (session 0 only): treat our own leg 0 as a foreign order.
            hidden = {oid for oid, (leg, _) in self.active.items() if leg == 0}
            self.forced_foreign = True
        foreign = [_order_id(r) for r in rows if _order_id(r) in hidden or not self._ours(r)]
        if foreign:
            self.journal.record('lfc_foreign_open_order', lfc_journal_schema=LFC_JOURNAL_SCHEMA, order_ids=foreign,
                                forced=self.forced_foreign)
            raise HoldEnd('foreign_open_order')

    def after_open(self):
        if self.profile.force == 'ledger_cap':
            # Forced test trigger (session 0 only): the cap becomes exactly L with both legs resting -> halt.
            self.cap = self.ledger.L()
            self.journal.record('lfc_forced_limit', lfc_journal_schema=LFC_JOURNAL_SCHEMA, limit='ledger_cap',
                                cap=str(self.cap))
        if self.profile.force == 'dead_man':
            self.force_dead_man()

    def force_dead_man(self, *, observe_seconds=LFC.DEAD_MAN_OBSERVE_SECONDS):
        """Stop the exchange heartbeat and do NOT cancel: the venue's dead-man must empty our orders by itself."""
        self.journal.record('lfc_forced_limit', lfc_journal_schema=LFC_JOURNAL_SCHEMA, limit='dead_man',
                            observe_seconds=observe_seconds)
        self.heartbeat_loop.stop()
        started = self.clock.monotonic()
        emptied_after = None
        while self.clock.monotonic() - started <= observe_seconds:
            try:
                rows = self.venue.open_orders()
                ours = [_order_id(r) for r in rows if self._ours(r)]
                self.journal.record('lfc_dead_man_poll', lfc_journal_schema=LFC_JOURNAL_SCHEMA,
                                    seconds=self.clock.monotonic() - started, our_open_orders=ours)
                if not ours:
                    emptied_after = self.clock.monotonic() - started
                    break
            except Exception as exc:
                self.journal.record('lfc_dead_man_poll', lfc_journal_schema=LFC_JOURNAL_SCHEMA,
                                    exception_type=type(exc).__name__)
            self.clock.sleep(1)
        self.dead_man = {'emptied': emptied_after is not None, 'seconds': emptied_after}
        self.journal.record('lfc_dead_man_result', lfc_journal_schema=LFC_JOURNAL_SCHEMA, **self.dead_man)
        if emptied_after is not None:
            # The venue cancelled them: mark the legs inactive so cleanup only verifies.
            self.active.clear()
        raise HoldEnd('forced_dead_man')

    def cancel_remaining(self):
        """Cancel OUR remaining orders only (known ids plus unacknowledged intents); never a foreign order."""
        rows = self._recover('cleanup_open_orders_before_cancel', self.venue.open_orders)
        targets = [_order_id(r) for r in rows if self._ours(r)]
        self._retain('lfc_cleanup_cancel_ours', lfc_journal_schema=LFC_JOURNAL_SCHEMA, order_ids=targets,
                     foreign_left=[_order_id(r) for r in rows if not self._ours(r)])
        ok = True
        for oid in targets:
            try:
                response = self._recover('cleanup_cancel_ours', lambda: self.venue.cancel(oid))
                self._retain('cleanup_cancel_ours_response', order_id=oid, response=response)
                ok = ok and oid in _cancel_ack_ids(response)
            except BaseException:
                ok = False
        return ok

    def account_clear(self, rows):
        return isinstance(rows, list) and not any(self._ours(r) for r in rows)
