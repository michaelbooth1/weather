"""Owner-attended RE-1M controller, separate from every sealed-lane capability.

No credential/client construction or network activity occurs at import. The
only submit boundary below is shared by the real transport and inert fakes.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
import atexit
import hashlib
import json
from pathlib import Path
from threading import RLock

from weather.market.mm_stage2_hold import (
    HoldEnd, HoldJournal, canonical_bytes, digest, utc, write_new,
    _exact_open_orders, _cancel_ack_ids, _order_id,
)
from weather.market.mm_stage2_selection import validate_selection
from weather.market.mm_official_adapter import _value
from weather.market.re1_resilience import Freshness, HeartbeatLoop, retry_read, transient
from weather.market.reward_quote import _decimal as number, _levels
from weather.market.reward_share_estimate import order_score, q_min, share_of, side_score
from weather.market.re1_sizing import SIZES, reserve_budget, session_caps
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration

HOST = 'https://clob.polymarket.com'
SIZE = Decimal('20')
ORDER_CAP = Decimal('15.8')
BAND_CAP = Decimal('19.6')
MAX_SUBMITS = 10
MAX_REQUOTES = 4
MAX_SESSIONS = 3
SECONDS = 21600
LAST_DAY = '2026-09-30'


class SecretGuard:
    """Drop auth/signature fields, then refuse any residual loaded secret."""
    def __init__(self, secrets=()):
        self.secrets = tuple(s for s in secrets if s)

    def clean(self, value):
        if hasattr(value, 'model_dump'):
            value = value.model_dump(mode='json')
        if isinstance(value, dict):
            value = {k: self.clean(v) for k, v in value.items()
                     if str(k).lower().replace('_', '') not in {
                         'headers', 'auth', 'authorization', 'signature', 'secret',
                         'apikey', 'apisecret', 'passphrase', 'privatekey'} and
                     not (str(k).lower() == 'owner' and isinstance(v, str) and v in self.secrets)}
        elif isinstance(value, (tuple, list)):
            value = [self.clean(v) for v in value]
        encoded = canonical_bytes(value).decode('utf-8')
        if any(s in encoded or json.dumps(s)[1:-1] in encoded for s in self.secrets):
            raise RuntimeError('secret_output_refused')
        return value

    def print(self, value):
        print(self.clean(value), flush=True)


class GuardedJournal(HoldJournal):
    def __init__(self, *args, guard, **kwargs):
        self.guard = guard
        self.lock = RLock()
        super().__init__(*args, **kwargs)

    def record(self, event, **fields):
        with self.lock:
            super().record(event, **self.guard.clean(fields))


def observe(snapshot, prices, size=SIZE):
    """84b scoring: hold prices may drift; drift requests a re-quote, not exit.

Reuse the estimator formulas; do not invoke 80b's hold-only re-pricing gates.
True touch remains a separate submit safety check. Plain mid is sensitivity.
"""
    size = number(size)
    if size not in SIZES:
        raise HoldEnd('treatment_size')
    values = snapshot['quote_inputs']
    minimum, maximum, rate = (number(values[k]) for k in
        ('reward_min_size', 'reward_max_spread_cents', 'reward_rate_per_day'))
    if minimum > size:
        raise HoldEnd('reward_minimum')
    if minimum <= 0 or maximum <= 0 or rate < 40:
        raise HoldEnd('reward_rate_or_terms')
    sides = ('yes_bids', 'yes_asks', 'no_bids', 'no_asks')
    if any(not values[k] for k in sides):
        raise HoldEnd('one_sided_book')
    yb, ya, nb, na = [_levels(values[k]) for k in sides]
    for bids, asks in ((yb, ya), (nb, na)):
        if max(p for p, _ in bids) >= min(p for p, _ in asks):
            raise HoldEnd('crossed_book')
    qb, qa = ([p for p, s in levels if s >= minimum] for levels in (yb, ya))
    if not qb or not qa:
        raise HoldEnd('no_size_adjusted_midpoint')
    mid = (max(qb) + min(qa)) / 2
    plain = (max(p for p, _ in yb) + min(p for p, _ in ya)) / 2
    yes, no = map(number, prices)
    visible = all(sum(s for p, s in levels if p == price) >= size
                  for levels, price in ((yb, yes), (nb, no)))

    def shares(at):
        scores = []
        for levels, own_price in ((yb, yes), (ya, 1 - no)):
            aggregate = {}
            for p, s in levels:
                aggregate[p] = aggregate.get(p, Decimal(0)) + s
            aggregate[own_price] = max(Decimal(0), aggregate.get(own_price, Decimal(0)) - size)
            scores.append(side_score([(float(p), float(s)) for p, s in aggregate.items() if s > 0],
                                     float(at), float(maximum), float(minimum))[0])
        own = q_min(*(order_score(float(size), float(d), float(maximum), float(minimum))
                      for d in ((at - yes) * 100, (1 - at - no) * 100)), float(at))
        return share_of(own, sum(scores) / 2), share_of(own, q_min(*scores, float(at)))

    many, single = shares(mid)
    plain_many, _ = shares(plain)
    distances = [(mid - yes) * 100, (1 - mid - no) * 100]
    return {'adjusted_mid': str(mid), 'plain_mid': str(plain),
            'visible_two_sided': visible, 'share_many': many, 'share_single': single,
            'share_many_plain_mid': plain_many,
            'per_minute_many': float(rate) / 1440 * many,
            'per_minute_single': float(rate) / 1440 * single,
            'per_minute_many_plain_mid': float(rate) / 1440 * plain_many,
            'requote_legs': [i for i, d in enumerate(distances) if not 1 <= d <= 3]}


def replacement_price(mid, leg):
    value = number(mid) if leg == 0 else 1 - number(mid)
    return ((value - Decimal('.015')) / Decimal('.01')).to_integral_value(rounding=ROUND_FLOOR) * Decimal('.01')


def filled(row):
    return (number(row.get('size_matched', 0)) > 0 or bool(row.get('associate_trades')) or
            str(_value(row, 'status', 'official_order_status') or '').upper() == 'MATCHED')


class Session:
    def __init__(self, *, venue, public, table, clock, directory, guard=None, mode='rehearse',
                 confirmation=None, attempt=None, realtime_rehearsal=False):
        self.venue, self.public, self.clock = venue, public, clock
        self.table, self.mode = table, mode
        self.guard = guard or SecretGuard()
        self.directory = Path(directory)
        self.start = utc(clock.now())
        if realtime_rehearsal and mode != 'rehearse':
            raise RuntimeError('live_duration_is_fixed')
        self.planned_seconds = 900 if realtime_rehearsal else SECONDS
        self.end = self.start + timedelta(seconds=self.planned_seconds)
        self.deadline = clock.monotonic() + self.planned_seconds
        self.condition = table['selected_condition_id']
        selected = next(r for r in table['rows'] if r['condition_id'] == self.condition)
        self.tokens = tuple(selected['token_ids'])
        validate_selection(table, expected_sha256=digest(table), condition_id=self.condition,
                           token_ids=self.tokens, now=self.start, allow_sized=True)
        self.prices = [number(selected['quote'][k]) for k in ('yes_buy', 'no_buy')]
        self.size = number(selected['quote']['size'])
        self.sized = table.get('size_treatment') == 'RE-1-84h'
        self.order_cap, self.band_cap = (session_caps(self.size, table['available_collateral'])
                                       if self.sized else (ORDER_CAP, BAND_CAP))
        self.selection_sha256 = digest(table)
        if mode == 'live' and (not self.sized or not confirmation or
                confirmation.get('text') != 'RE1M TUNNEL DOWN ELIGIBLE ATTENDED ' + self.selection_sha256[:12]):
            raise RuntimeError('size_confirmation_required')
        self.initial_terms = selected['snapshot']['quote_inputs']
        self.known, self.active = {}, {}
        if hasattr(venue, 'known_order_ids'):
            venue.known_order_ids = self.known
            if venue.stream is not None:
                venue.stream.known_order_ids = self.known
                venue.stream_args['known_order_ids'] = self.known
        self.submits = self.requotes = 0
        self.posts = 0
        self.venue.before_post = self.before_post
        self.fill_seen = self.terms_changed = self.evidence_failed = False
        self.scoring_seen = False
        self.started = self.closed = False
        self.empty_account_proven = False
        self.heartbeat_loop = None
        self.order_created = {}
        self.market_time = clock.monotonic()
        self.totals = dict(P_many=0.0, P_single=0.0, P_many_plain_mid=0.0, visible_two_sided_minutes=0)
        self.attempt = attempt
        self.scope = {'condition_id': self.condition, 'token_ids': list(self.tokens),
                      'maker_address': venue.maker, 'end_at_utc': self.end.isoformat(),
                      'protocol': 'RE-1M-attended-84c'}
        if self.sized:
            self.scope.update(size=str(self.size), reserve_pusd=selected['quote']['reserve_pusd'],
                              available_collateral=table['available_collateral'],
                              selection_sha256=self.selection_sha256)
        self.journal = GuardedJournal(self.directory / 'journal.jsonl', clock=clock.now,
                                     scope=self.scope, mode=mode, guard=self.guard)
        if hasattr(venue, 'set_journal'):
            venue.set_journal(self.journal)
        write_new(self.directory / 'selection.json', self.guard.clean(table))
        self.journal.record('selection', selection_sha256=digest(table), confirmation=confirmation,
                            fixed_end_at_utc=self.end.isoformat(), attempt=attempt)
        self.freshness = Freshness(clock, self.journal)

    def call(self, name, fn, **request):
        self.journal.record(name + '_request', request=request)
        result = fn()
        self.journal.record(name + '_response', response=result)
        return result

    def required(self, name, fn, *, checkpoint=True, **request):
        return retry_read(name, lambda: self.call(name, fn, **request), clock=self.clock,
                          journal=self.journal, checkpoint=self.control if checkpoint else lambda: None)

    def sample(self, name, fn):
        try:
            return self.call(name, fn)
        except Exception as exc:
            self.evidence_failed = True
            self.journal.record('missing_sample', sample=name, exception_type=type(exc).__name__)
            return None

    def before_post(self, request):
        # Persist before the raw network POST, after signing and all checks.
        write_new(self.directory / f'submit-{self.posts + 1}.intent.json',
                  {'number': self.posts + 1, 'request': request, 'scope': self.scope})
        self.posts += 1

    def control(self, *, force=False):
        # Checkpoints between reads are main-thread progress too. A blocked
        # read cannot call this, so the independent 20-second watchdog holds.
        if self.heartbeat_loop is not None:
            self.heartbeat_loop.tick()
        assert_no_ambient_proxy_configuration()
        now = self.clock.monotonic()
        if utc(self.clock.now()) >= self.end or now >= self.deadline:
            raise HoldEnd('fixed_end')
        geo = self.freshness.read('geoblock', lambda: self.call('geoblock', self.venue.geography),
                                  cadence=30, budget=45, force=force)
        if geo is not None:
            if geo.get('blocked') is not False:
                raise HoldEnd('geoblock')
        if self.heartbeat_loop is None:
            self.heartbeat_loop = HeartbeatLoop(self.clock, self.venue.heartbeat, self.journal,
                                                threaded=getattr(self.clock, 'realtime', False))
            self.heartbeat_loop.start()
        self.heartbeat_loop.check()
        self.check_fills(force=force)
        self.freshness.check('geoblock', 45)
        if self.clock.monotonic() - self.market_time >= 300:
            raise HoldEnd('market_snapshot_stale')
        if getattr(self.venue, 'journal_failed', False):
            raise HoldEnd('response_journal_failed')
        if force and ('geoblock' not in self.freshness.success or self.heartbeat_loop.last_ack is None):
            self.clock.sleep(.25)
            self.control(force=True)

    def check_fills(self, *, canceling=None, force=False):
        events = self.freshness.read('user_stream', self.venue.events, cadence=0, budget=30)
        if hasattr(self.venue, 'stream_last_alive'):
            self.freshness.success['user_stream'] = self.venue.stream_last_alive
            self.freshness.check('user_stream', 30)
        if events:
            self.journal.record('user_events', rows=events)
        for event in events or []:
            if event.get('official_event_type') == 'trade' and event.get('condition_id') == self.condition:
                self.fill_seen = True
                if event.get('event_type') == 'unmatched_trade_event':
                    self.journal.record('unmatched_trade_event', payload=event['payload'],
                                        raw_event_sha256=event['raw_event_sha256'])
                orders = []
                # Force both legs even if the first row already proves a fill.
                for oid in self.active:
                    try:
                        orders.append(self.required('fill_order', lambda: self.venue.order(oid),
                                                    checkpoint=False, order_id=oid))
                    except Exception as exc:
                        self.evidence_failed = True
                        self.journal.record('fill_order_unavailable', order_id=oid, exception_type=type(exc).__name__)
                self.journal.record('fill', rows=orders, user_event=event)
                raise HoldEnd('fill')
            if _order_id(event) not in self.known:
                raise HoldEnd('unknown_user_event')
            if (event.get('official_event_type') == 'trade' or
                    event.get('event_type') in {'trade', 'trade_pending'} or
                    filled(event)):
                self.fill_seen = True
                self.journal.record('fill', user_event=event)
                raise HoldEnd('fill')
            status = _value(event, 'status', 'official_order_status')
            if _order_id(event) in self.active and _order_id(event) != canceling and status and str(status).upper() != 'LIVE':
                raise HoldEnd('order_no_longer_resting')

        for oid in self.active:
            row = self.freshness.read('order_' + oid, lambda: self.call('order', lambda: self.venue.order(oid), order_id=oid),
                                      cadence=10, budget=30, force=force or canceling is not None,
                                      initial=self.order_created.get(oid, self.freshness.started))
            if row is None:
                continue
            if filled(row):
                self.fill_seen = True
                self.journal.record('fill', order=row)
                raise HoldEnd('fill')
            if oid != canceling and str(row.get('status', '')).upper() != 'LIVE':
                self.evidence_failed = True
                raise HoldEnd('order_no_longer_resting')

    def submit(self, leg, price, *, side='BUY', size=None, post_only=True, order_type='GTD'):
        """The sole sign/submit boundary. No CLI/config can widen these limits."""
        self.control(force=True)
        size = self.size if size is None else number(size)
        if (self.mode == 'live' and (not self.attempt or not 1 <= self.attempt.get('session_number', self.attempt['number']) <= MAX_SESSIONS)):
            raise HoldEnd('session_cap')
        now = utc(self.clock.now())
        if (self.venue.host != HOST or side != 'BUY' or size != self.size or size not in SIZES or
                post_only is not True or order_type != 'GTD' or leg not in (0, 1)):
            raise HoldEnd('submit_shape')
        if ((self.end - self.start).total_seconds() != self.planned_seconds or
                self.mode == 'live' and self.planned_seconds != SECONDS or self.end.date() != self.start.date()):
            raise HoldEnd('session_duration_or_utc_day')
        if now.date().isoformat() > LAST_DAY or (self.end - now).total_seconds() < 180:
            raise HoldEnd('expiration_horizon')
        if self.submits >= MAX_SUBMITS or self.requotes > MAX_REQUOTES:
            raise HoldEnd('submit_budget')
        price = number(price)
        if price != self.prices[leg] or not Decimal('.17') <= price <= Decimal('.80') or price % Decimal('.01'):
            raise HoldEnd('submit_price')
        if price * size > self.order_cap or sum(self.prices) * size > self.band_cap or sum(self.prices) * size > 75:
            raise HoldEnd('capital_cap')
        expected = {oid: (self.tokens[i], p, size) for oid, (i, p) in self.active.items()}
        rows = self.required('open_orders', self.venue.open_orders)
        _exact_open_orders(rows, expected, maker=self.venue.maker, condition=self.condition)
        if len(rows) >= 2 or any(i == leg for i, _ in self.active.values()):
            raise HoldEnd('open_order_cap')
        # Fresh public reads are immediately adjacent to signing, never a
        # complementary inferred ask. Every token must retain a two-sided book.
        snapshot = self.required('submit_snapshot', lambda: self.public.snapshot(self.condition, self.tokens, checkpoint=self.control))
        if (snapshot['condition_id'] != self.condition or tuple(snapshot['token_ids']) != self.tokens or
                not 0 <= (utc(self.clock.now()) - utc(snapshot['observed_at_utc'])).total_seconds() <= 10):
            raise HoldEnd('fresh_book_scope')
        self.journal.record('submit_market_snapshot', snapshot=snapshot)
        self.market_time = self.clock.monotonic()
        values = snapshot['quote_inputs']
        if ((number(values['reward_min_size']) > size if self.sized else number(values['reward_min_size']) != SIZE)
                or number(values['reward_rate_per_day']) < 40):
            raise HoldEnd('reward_terms')
        observe(snapshot, self.prices, self.size)
        rule = snapshot['rules'][self.tokens[leg]]
        if number(rule['tick_size']) != Decimal('.01') or number(rule['min_order_size']) > size or number(rule['fee_rate_bps']) < 0:
            raise HoldEnd('market_rules')
        asks = _levels(values['yes_asks' if leg == 0 else 'no_asks'])
        if price >= min(p for p, _ in asks):
            raise HoldEnd('fresh_ask')
        self.control()
        request = dict(token_id=self.tokens[leg], side=side, size=str(size), price=str(price),
                       post_only=post_only, expiration=int(self.end.timestamp()) + 60)
        self.submits += 1  # consume before signing, including ambiguous failures
        try:
            response = self.call('submit', lambda: self.venue.submit(request, checkpoint=self.control), **request)
        except Exception as exc:
            if transient(exc):
                raise HoldEnd('submit_transport_ambiguous') from None
            raise
        oid = str(_value(response, 'id', 'order_id', 'orderID') or '')
        if oid:
            self.known[oid] = leg
            self.active[oid] = (leg, price)
            self.order_created[oid] = self.clock.monotonic()
            write_new(self.directory / f'submit-{self.posts}.ack.json', {'order_id': oid})
        if _value(response, 'trade_ids', 'tradeIDs') or response.get('status') == 'matched':
            self.fill_seen = True
            raise HoldEnd('fill')
        if not oid or _value(response, 'ok', 'success') is not True or response.get('status') != 'live':
            raise HoldEnd('submit_acknowledgment')
        self.sample('scoring', lambda: self.venue.scoring(list(self.active)))
        return oid

    def cancel_leg(self, oid):
        response = self.required('cancel', lambda: self.venue.cancel(oid), checkpoint=False, order_id=oid)
        if oid not in _cancel_ack_ids(response):
            raise HoldEnd('cancel_acknowledgment')
        row = self.required('cancel_order_read', lambda: self.venue.order(oid), checkpoint=False)
        if filled(row):
            self.fill_seen = True
            raise HoldEnd('fill')
        self.check_fills(canceling=oid)  # includes fills racing cancellation
        remaining = self.required('open_orders', self.venue.open_orders)
        if any(_order_id(row) == oid for row in remaining):
            raise HoldEnd('cancel_not_terminal')
        del self.active[oid]

    def cleanup(self):
        """Cancellation does not depend on a working journal, stream or geoblock."""
        if self.closed:
            return self.cleanup_ok
        acknowledged = False
        def retain(event, **fields):
            try:
                self.journal.record(event, **fields)
            except BaseException:
                self.evidence_failed = True
        def recover(name, fn):
            for attempt in range(3):
                try:
                    return fn()
                except Exception as exc:
                    retain(name + '_unavailable', exception_type=type(exc).__name__)
                    if not transient(exc) or attempt == 2:
                        raise
                    self.clock.sleep(.5)
        if self.heartbeat_loop is not None:
            try:
                self.heartbeat_loop.stop()
            except BaseException:
                self.evidence_failed = True
        self.inventory_proven = False
        # Before the empty-account preflight succeeds, there is no authority to
        # cancel unrelated pre-existing orders. No submit can have occurred.
        if not self.empty_account_proven and self.submits == 0:
            self.cleanup_ok = True
            self.inventory_proven = True
            self.closed = True
            return True
        for oid in self.active:
            try:
                retain('cleanup_cancel_request', order_id=oid)
                response = recover('cleanup_cancel', lambda: self.venue.cancel(oid))
                retain('cleanup_cancel_response', order_id=oid, response=response)
            except BaseException:
                retain('cleanup_cancel_unavailable', order_id=oid)
        try:
            retain('cleanup_cancel_all_request')
            response = recover('cleanup_cancel_all', self.venue.cancel_all)
            _cancel_ack_ids(response)
            acknowledged = True
            retain('cleanup_cancel_all_response', response=response)
        except BaseException:
            acknowledged = False
        empty = False
        try:
            rows = recover('cleanup_open_orders', self.venue.open_orders)
            retain('cleanup_open_orders', rows=rows)
            empty = rows == []
        except BaseException:
            pass
        # Cancellation and deadline races can fill after the last loop poll.
        # A zero-open-order read alone says nothing about that inventory.
        try:
            for oid in self.known:
                row = recover('terminal_order', lambda: self.venue.order(oid))
                retain('terminal_order', order=row)
                if filled(row):
                    self.fill_seen = True
            positions = recover('terminal_positions', self.venue.positions)
            retain('terminal_positions', rows=positions)
            if positions:
                self.fill_seen = True
            self.inventory_proven = True
        except BaseException:
            self.evidence_failed = True
        try:
            retain('terminal_trades', rows=recover('terminal_trades', self.venue.trades))
        except BaseException:
            self.evidence_failed = True
        # A lost submit acknowledgement may hide an order/fill identity even
        # after cancel-all succeeds. Never qualify or silently retry it.
        if self.posts != len(self.known):
            self.evidence_failed = True
        self.cleanup_ok = empty and acknowledged
        self.closed = True
        if not self.cleanup_ok:
            self.guard.print('PANIC: run cancel-only in a second terminal and check the account in the browser.')
        return self.cleanup_ok

    def run(self, *, rehearsal_seconds=None):
        if self.started or self.mode not in {'live', 'rehearse'}:
            raise RuntimeError('one_session_per_process')
        if rehearsal_seconds is not None and self.mode != 'rehearse':
            raise RuntimeError('live_duration_is_fixed')
        self.started = True
        atexit.register(self.cleanup)
        reason, failure = 'fixed_end', None
        observed_minutes = 0
        try:
            if self.end.date() != self.start.date() or self.start.date().isoformat() > LAST_DAY:
                raise HoldEnd('session_duration_or_utc_day')
            if self.required('initial_open_orders', self.venue.open_orders, checkpoint=False) != []:
                raise HoldEnd('initial_open_orders')
            self.empty_account_proven = True
            if self.required('initial_positions', self.venue.positions, checkpoint=False) != []:
                raise HoldEnd('initial_positions')
            balances = self.required('initial_balances', self.venue.balances, checkpoint=False)
            if (sum(self.prices) * self.size > reserve_budget(balances['available_collateral']) if self.sized
                    else number(balances['available_collateral']) < 25):
                raise HoldEnd('available_collateral')
            if self.sized:
                self.band_cap = min(self.band_cap, reserve_budget(balances['available_collateral']))
            self.freshness.started = self.market_time = self.clock.monotonic()
            self.submit(0, self.prices[0])
            self.submit(1, self.prices[1])
            next_minute = self.clock.monotonic()
            next_accrual = next_minute
            stop_at = self.deadline if rehearsal_seconds is None else min(self.deadline, self.clock.monotonic() + rehearsal_seconds)
            while self.clock.monotonic() < stop_at:
                self.heartbeat_loop.tick()
                self.control()
                if self.clock.monotonic() >= next_minute:
                    next_minute = max(next_minute + 60, self.clock.monotonic() + 1)
                    try:
                        snapshot = self.public.snapshot(self.condition, self.tokens, checkpoint=self.control)
                    except Exception as exc:
                        if not transient(exc):
                            raise
                        self.evidence_failed = True
                        self.journal.record('minute_missed', exception_type=type(exc).__name__)
                        continue
                    self.journal.record('market_snapshot', snapshot=snapshot)
                    if self.clock.monotonic() - self.market_time >= 300:
                        raise HoldEnd('market_snapshot_stale')
                    self.market_time = self.clock.monotonic()
                    self.terms_changed |= any(snapshot['quote_inputs'][k] != self.initial_terms[k] for k in
                        ('reward_min_size', 'reward_rate_per_day', 'reward_max_spread_cents'))
                    observation = observe(snapshot, self.prices, self.size)
                    self.control()
                    if self.clock.monotonic() >= next_accrual:
                        scoring = self.sample('scoring', lambda: self.venue.scoring(list(self.active)))
                        self.scoring_seen |= scoring is not None and len(scoring) == 2 and all(v is True for v in scoring.values())
                        self.sample('accrual', lambda: self.venue.accrual(self.start.date().isoformat()))
                        next_accrual = self.clock.monotonic() + 1800
                        self.control()
                    # Match the reference's one-minute sampled sums exactly.
                    if observation['visible_two_sided']:
                        self.totals['visible_two_sided_minutes'] += 1
                        for suffix in ('many', 'single', 'many_plain_mid'):
                            self.totals['P_' + suffix] += observation['per_minute_' + suffix]
                    self.journal.record('minute', snapshot=snapshot, prices=list(map(str, self.prices)),
                                        observation=observation, **self.totals)
                    observed_minutes += 1
                    if observation['requote_legs']:
                        if self.requotes >= MAX_REQUOTES:
                            raise HoldEnd('fifth_requote')
                        self.requotes += 1
                    for leg in observation['requote_legs']:
                        oid = next(oid for oid, (i, _) in self.active.items() if i == leg)
                        self.cancel_leg(oid)
                    # Retire all affected legs before replacing either. A
                    # mixed old/new pair can exceed the capital cap even
                    # though the new treatment pair is within it.
                    for leg in observation['requote_legs']:
                        self.prices[leg] = replacement_price(observation['adjusted_mid'], leg)
                    for leg in observation['requote_legs']:
                        self.submit(leg, self.prices[leg])
                self.clock.sleep(min(1, max(0, stop_at - self.clock.monotonic())))
        except HoldEnd as exc:
            reason = exc.reason
        except BaseException as exc:
            reason = 'transport_unavailable' if transient(exc) else 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'exception'
            failure = type(exc).__name__
            self.evidence_failed = True
        finally:
            self.cleanup()
            atexit.unregister(self.cleanup)
        if self.fill_seen:
            reason = 'fill'
        try:
            self.sample('final_balances', self.venue.balances)
            self.sample('final_accrual', lambda: self.venue.accrual(self.start.date().isoformat()))
            self.journal.record('terminal', reason=reason, failure_type=failure, cleanup_ok=self.cleanup_ok,
                                fill_seen=self.fill_seen, submits=self.submits, requotes=self.requotes,
                                evidence_complete=not self.evidence_failed, reward_terms_changed=self.terms_changed,
                                scoring_seen=self.scoring_seen, order_ids=list(self.known),
                                unknown_submit=self.posts != len(self.known), post_count=self.posts,
                                inventory_proven=self.inventory_proven)
        except BaseException:
            self.evidence_failed = True
        self.journal.close()
        result = {**self.totals, 'scope': self.scope, 'mode': self.mode, 'condition_id': self.condition,
                  'reward_day': self.start.date().isoformat(), 'frozen_at_utc': utc(self.clock.now()).isoformat(),
                  'journal_sha256': hashlib.sha256(self.journal.path.read_bytes()).hexdigest(),
                  'cleanup_ok': self.cleanup_ok, 'fill_seen': self.fill_seen, 'reward_terms_changed': self.terms_changed,
                  'scoring_seen': self.scoring_seen, 'evidence_complete': not self.evidence_failed,
                  'reason': reason, 'failure_type': failure, 'submits': self.submits,
                  'order_ids': list(self.known), 'unknown_submit': self.posts != len(self.known), 'post_count': self.posts,
                  'inventory_proven': self.inventory_proven,
                  'requotes': self.requotes, 'minute_samples': observed_minutes, 'payout_read': False}
        write_new(self.directory / 'prediction.json', self.guard.clean(result))
        self.guard.print({'prediction': str(self.directory / 'prediction.json'), 'sha256': digest(result),
                          'reason': reason, 'cleanup_ok': self.cleanup_ok})
        return result
