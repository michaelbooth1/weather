"""One cooperative owner process with independent F0-shaped bands.

No thread posts orders. Each band retains its own finite profile budget,
private journal and durable intents. Band cleanup cancels that band's orders;
the explicit breadth protocol may continue only after inventory proof and cooldown.
Any monetary ambiguity, STOP or account fault triggers campaign cleanup.
The final wallet-wide read verifies the result of scoped order cancellation.
"""
from decimal import Decimal
from pathlib import Path

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CapitalBook, CapitalRefused, SCALE
from weather.market.lfc_f2_breadth import arm_field_keys
from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_pilot import PilotSession, write_session_end
from weather.market.lfc_recording_io import file_sha, write_new
from weather.market.mm_stage2_hold import HoldEnd, _order_id, cancel_ack_ids, digest
from weather.market.re1_attended import GuardedJournal, SecretGuard, observe
from weather.market.re1_resilience import HeartbeatLoop
from weather.market import lfc_pair_runtime as pairs


class PeerCashPending(RuntimeError):
    """No POST: give peer controllers time to reconcile a possible fill."""
    retry_pre_post = True


class SharedHeartbeat:
    """A retired band cannot stop the other band's account heartbeat."""
    def __init__(self, loop):
        self.loop = loop

    def __getattr__(self, name):
        return getattr(self.loop, name)

    def stop(self):
        pass  # Only the account coordinator stops the real worker, after cleanup.


class ScopedVenue:
    """Retain account-wide foreign-order detection before taking a band view."""
    def __init__(self, raw, coordinator, session_id):
        object.__setattr__(self, 'raw', raw)
        object.__setattr__(self, 'coordinator', coordinator)
        object.__setattr__(self, 'session_id', session_id)

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def __setattr__(self, name, value):
        setattr(self.raw, name, value)

    def open_orders(self):
        rows = self.coordinator.account_orders(self.raw.open_orders())
        return [row for row in rows if self.coordinator.order_session(row) == self.session_id]

    def account_events(self):
        from weather.market.lfc_f2_owner_notice import NOTICE, OVERLAP
        rows = self.raw.events()
        if not isinstance(rows, list):
            return rows
        fills = []
        for row in rows:
            event = row.get('event_type')
            if event in {NOTICE, OVERLAP}:
                self.coordinator.note_owner_activity(row)
                continue
            fills.append(row)
        return fills

    def events(self):
        rows = self.account_events()
        band = next(b for b in self.coordinator.bands if b.session_id == self.session_id)
        from weather.market.lfc_f2_breadth import enabled
        if enabled(self.coordinator.policy):
            from weather.market.lfc_f2_repost import filtered_events, observe_trade_ids
            observe_trade_ids(band, rows or [])
            from weather.market.lfc_f2_reward_estimate import capture_stream_context
            capture_stream_context(band, rows or [])
            band.project_trades(rows, source='stream')
            result = filtered_events(band, band.pending_repost_events + rows)
            band.pending_repost_events, band.pending_repost_bytes = [], 0
            return result
        band.project_trades(rows, source='stream')
        return rows

    def cancel(self, oid):
        if self.coordinator.acknowledged_session(oid) != self.session_id:
            raise HoldEnd('campaign_cancel_order_unbound')
        return self.raw.cancel(oid)

    def cancel_all(self):
        raise RuntimeError('band_has_no_account_cancel_all')


class F2Band(PilotSession):
    def __init__(self, *, policy, entry, **kwargs):
        self.campaign_policy, self.campaign_entry = policy, entry
        from weather.market.lfc_f2_pinb import enabled as pinb
        if pinb(policy):
            self.MAX_SUBMITS = policy.raw['max_submits_per_band']
            self.MAX_REQUOTES = policy.raw['max_requotes_per_band']
        self.MIN_REWARD_RATE = quantity(policy.raw['min_reward_rate'])
        chosen = next(row for row in kwargs['table']['rows']
                      if row['condition_id'] == kwargs['table']['selected_condition_id'])
        self.TRADE_LEGS = tuple(chosen['trade_legs'])
        self.LEG_PRICE_RANGE = tuple(map(quantity, policy.raw['leg_price_range']))
        super().__init__(**kwargs)
        from weather.market.lfc_f2_breadth import enabled
        self.breadth = enabled(policy)
        self.OFFSET = quantity(chosen['quote_offset_pusd'] if self.breadth else policy.raw['quote_offset_pusd'])
        self.repost_waiting = False
        self.proven_trade_ids, self.observed_trade_ids = set(), set()
        self.pending_repost_events, self.pending_repost_bytes = [], 0
        from weather.market.lfc_own_trades import OwnTradeProjection
        self.own_trades = OwnTradeProjection(limit=8192)  # Existing 4096 trade identities, up to both own legs.
        self.reward_estimates, self.reward_estimate_gaps = {}, set()
        self.reward_context = {}
        self.REQUOTE_WINDOW = tuple(map(quantity, policy.raw['requote_distance_cents']))
        self.SECONDS = self.planned_seconds  # Late entry keeps the absolute end.
        self.cap = quantity(policy.raw['owner_funding_ceiling_pusd'])
        self.scope.update(budget_pusd=str(self.cap), capital_mode=policy.raw['capital_mode'],
                          trade_legs=list(self.TRADE_LEGS), quote_offset_pusd=str(self.OFFSET),
                          requote_distance_cents=list(map(str, self.REQUOTE_WINDOW)))
        if pinb(policy):
            self.scope.update(autostart_policy_schema=policy.raw['schema_version'],
                max_submits_per_band=self.MAX_SUBMITS, max_requotes_per_band=self.MAX_REQUOTES)
        if self.breadth:
            self.scope.update({key: chosen[key] for key in arm_field_keys(policy)})
            self.scope['market_id'] = chosen['market_id']
            self.journal.record('quote_arm', **{key: self.scope[key] for key in
                (*arm_field_keys(policy), 'market_id')})
        pairs.initialize(self)

    def quote_steps(self, *, rehearsal_seconds=None):
        from weather.market.lfc_f2_repost import continue_quotes
        base = super().quote_steps
        if pairs.enabled(self):
            def base(*, rehearsal_seconds=None):
                yield from pairs.cycle(self, super(F2Band, self).quote_steps, rehearsal_seconds=rehearsal_seconds)
        yield from continue_quotes(self, base, rehearsal_seconds=rehearsal_seconds)

    def read_geoblock(self, *, force=False):
        from weather.market.lfc_f2_geoblock import read_for_band
        return read_for_band(self)

    def submit_steps(self, leg, price):
        price = pairs.submit_price(self, leg, price)
        began, deferrals = None, 0
        while True:
            previous_submits = self.submits
            try:
                if began is not None:
                    self.control()
                    if deferrals >= 24:
                        reason = ('owner_activity_cash_pending' if self.venue.coordinator.owner_notice_digests
                                  else 'peer_cash_wait_expired')
                        raise HoldEnd(reason)
                    own = sum((self.size * p for _, p in self.active.values()), Decimal(0))
                    reserve, _ = self._gate(own_resting=own)
                    self._cash(self.required('f2_wait_balances', self.venue.balances), reserve)
                self.submit(leg, price)
                return
            except PeerCashPending:
                deferrals += 1
                if began is None:
                    began = self.clock.monotonic()
                    self.journal.record('f2_peer_cash_wait', reason='capital_cash_changed')
                # authorize_post failed before counting, or call() proved that
                # its counted attempt acquired no durable POST authority.
                # Polling/retrying this exact request spends no submit budget.
                self.submits = previous_submits
                # No posting thread or recursive peer driver. The account's
                # ordinary cooperative loop advances every band on this yield.
                # Count cooperative turns, not wall time spent inside peer GETs.
                # At most24 five-second deferrals; ordinary hard-end, STOP and
                # freshness checks remain in force on every resumed turn.
                yield 5

    def call(self, name, fn, **request):
        previous_posts = self.posts
        try:
            response = super().call(name, fn, **request)
            if name in {'accrual', 'final_accrual'}:
                from weather.market.lfc_f2_reward_estimate import capture_accrual
                capture_accrual(self, response)
            return response
        except PeerCashPending:
            if name == 'submit':
                number = self.posts + 1
                if (self.posts != previous_posts or previous_posts != len(self.known) or
                        not self.ledger.intent_proven_absent(f'{self.session_id}:{number}') or
                        (self.directory / f'submit-{number}.intent.json').exists()):
                    raise HoldEnd('peer_cash_defer_not_proven') from None
                self.journal.record('submit_deferred', attempted_number=number,
                    request_sha256=digest(request), durable_intent_present=False)
            raise

    def final_reason(self, reason):
        return reason if self.breadth else super().final_reason(reason)

    def check_fills(self, **kwargs):
        if not self.repost_waiting:
            try:
                return super().check_fills(**kwargs)
            except HoldEnd as exc:
                if exc.reason == 'fill':
                    self.record_post_books('fill')
                raise
        # All this band's orders are terminal. Fresh account proof is required
        # before returning to the ordinary stream/REST checks and submit path.
        from weather.market.lfc_f2_repost import poll_waiting_stream
        return poll_waiting_stream(self)

    def record_post_books(self, trigger):
        coordinator = self.venue.coordinator
        if coordinator.post_books is not None:
            try:
                coordinator.post_books.watch(self, trigger)
            except Exception as exc:
                coordinator.retain('post_book_recording_unavailable', exception_type=type(exc).__name__)

    def project_trades(self, rows, *, source):
        pairs.remember_trades(self, rows, source=source)
        ours = {oid: self.ledger.legs[self.ledger.by_order[oid]] for oid in self.known}
        changed = self.own_trades.ingest(rows or [], ours, source=source,
                                        observed_at_utc=self.clock.now().isoformat())
        if changed:
            self.journal.record('fill', rows=changed, projection_update=True, source=source)
            if any(row['money_counted'] and (row['trade_id'], row['own_order_id']) in self.own_trades.new_keys
                   for row in changed):
                self.record_post_books('fill')
        return changed

    def record_fill(self, **fields):
        event = fields.get('user_event')
        if event is not None:
            self.project_trades([event], source='stream')
        rows = self.own_trades.rows()
        signal = event or fields.get('order')
        if signal is not None:
            oid = _order_id(signal)
            tid = signal.get('trade_id')
            rows = [row for row in rows if (not oid or row['own_order_id'] == oid) and
                    (not tid or row['trade_id'] == tid)]
        # Keep the old source/order payload, but never call an empty order-read
        # list a canonical execution. Cleanup's REST read finalizes this signal.
        order_rows = fields.pop('rows', [])
        self.journal.record('fill' if rows else 'fill_pending', rows=rows,
            order_rows=order_rows, awaiting_trade_evidence=not rows, **fields)

    def terminal_extra(self):
        return {**super().terminal_extra(), 'own_trade_projection': self.own_trades.rows(),
                'reward_estimates': list(self.reward_estimates.values()),
                'reward_estimate_gaps': sorted(self.reward_estimate_gaps),
                'reward_context': {'touches': list(self.reward_context.values()), 'gaps': []},
                **pairs.terminal_extra(self)}

    def posted(self, oid, leg, price):
        super().posted(oid, leg, price)
        pairs.posted(self, oid)

    def leg_terminal(self, oid, row):
        before = self.ledger.legs[self.ledger.by_order[oid]]['size_matched']
        super().leg_terminal(oid, row)
        if quantity(row['size_matched']) > quantity(before):
            self.record_post_books('fill')

    def refresh_repost_prices(self):
        from weather.market.re1_attended import replacement_price
        snapshot = self.public.snapshot(self.condition, self.tokens, checkpoint=self.control)
        observation = self.observe_snapshot(snapshot)
        self.minute_extra(snapshot)
        self.prices = [replacement_price(observation['adjusted_mid'], leg, self.OFFSET) for leg in (0, 1)]
        pairs.cap_prices(self)
        self.market_time = self.clock.monotonic()
        self.journal.record('repost_market_snapshot', snapshot=snapshot, prices=list(map(str, self.prices)))

    def validate_table(self, table):
        from weather.market.lfc_f2_selection import validate_table
        parent = {key: value for key, value in table.items() if key != 'f2_parent_table_sha256'}
        parent['selected_condition_id'] = parent['selected_condition_ids'][0]
        if digest(parent) != table.get('f2_parent_table_sha256'):
            raise ValueError('f2_band_parent_binding')
        selected = validate_table(parent, now=self.start, policy=self.campaign_policy)
        if table['selected_condition_id'] not in {row['condition_id'] for row in selected}:
            raise ValueError('f2_unselected_band')

    def start_allowed(self, now):
        return (self.campaign_entry.start <= self.start < self.campaign_entry.end and
                self.start <= now <= self.end and self.start.date() == self.end.date())

    def session_number_ok(self):
        return (bool(self.attempt) and self.attempt.get('protocol') == ('lfc_autostart_v3' if self.breadth else 'lfc_autostart_v2') and
                type(self.attempt.get('session_number')) is int and self.attempt['session_number'] >= 1)

    def observe_snapshot(self, snapshot):
        from weather.market.lfc_f2_selection import check_book
        from weather.market.reward_quote import QuoteRefused
        matched = self.own_trades.traded_shares() if self.active else {}
        resting = {leg: (price, self.size - quantity(matched.get(oid, 0)))
                   for oid, (leg, price) in self.active.items()}
        observation = observe(snapshot, self.prices, self.size, self.SIZES, reward_terms=True,
            window=self.REQUOTE_WINDOW, trade_legs=self.TRADE_LEGS, min_reward_rate=self.MIN_REWARD_RATE,
            resting_by_leg=resting)
        try:
            check_book(snapshot['quote_inputs'], mid=observation['adjusted_mid'], size=self.size,
                       share=observation['share_many'], policy=self.campaign_policy)
        except QuoteRefused as exc:
            raise HoldEnd(str(exc)) from None
        return pairs.observe(self, snapshot, observation)

    def _gate(self, *, own_resting=Decimal(0)):
        reserve = self.size * sum(self.reserve_prices(), Decimal(0))
        try:
            from weather.market.lfc_f2_breadth import daily_gate
            daily_gate(self.ledger, self.ledger.sessions[self.session_id]['start'], reserve=reserve,
                       own_resting=own_resting, journal=self.journal)
            figures = CapitalBook(self.ledger).gate(reserve=reserve, own_resting=own_resting)
        except CapitalRefused as exc:
            raise HoldEnd(str(exc)) from None
        return reserve, Decimal(figures['charged_native']) / SCALE - own_resting

    def check_pending_quote(self, snapshot, leg, price):
        from weather.market.lfc_f2_pinb import enabled as pinb
        from weather.market.reward_quote import reward_distance_allowed
        observation = self.observe_snapshot(snapshot)
        if not pinb(self.campaign_policy) or (pairs.enabled(self) and pairs.require_state(self).completing):
            return
        mid = quantity(observation['adjusted_mid'])
        distance = ((mid if leg == 0 else 1 - mid) - price) * 100
        maximum = quantity(snapshot['quote_inputs']['reward_max_spread_cents'])
        if not reward_distance_allowed(distance, *self.REQUOTE_WINDOW, maximum):
            raise HoldEnd('outside_leave_alone_window')

    def _cash(self, balances, reserve):
        own = sum((self.size * price for _, price in self.active.values()), Decimal(0))
        try:
            coordinator = self.venue.coordinator
            external = (coordinator.foreign_orders_reserve(self.venue.raw.open_orders())
                        if coordinator.shared_wallet else 0)
            figures = CapitalBook(self.ledger).gate(reserve=reserve, own_resting=own,
                       available_cash=balances['available_collateral'], external_resting=external)
        except CapitalRefused as exc:
            peers = {band.session_id for band in self.venue.coordinator.bands if band is not self}
            if (self.breadth and str(exc) == 'capital_cash_changed' and
                    (coordinator.owner_notice_digests or any(
                        leg['session_id'] in peers and leg['status'] != 'terminal' for leg in self.ledger.legs.values()))):
                raise PeerCashPending() from None
            raise HoldEnd(str(exc)) from None
        return quantity(balances['available_collateral']), Decimal(figures['resting_reserve_native']) / SCALE

    def authorize_post(self, leg, price, size, rule):
        # Every placement/requote, not just selection or the first band.
        reserve, _ = self._gate(own_resting=sum((self.size * p for _, p in self.active.values()), Decimal(0)))
        self._cash(self.required('f2_post_balances', self.venue.balances), reserve)
        super().authorize_post(leg, price, size, rule)
        pairs.authorize(self, leg, price, size)  # Includes the adjacent fresh submit snapshot.

    def before_post(self, request):
        self.control()
        own = sum((self.size * p for _, p in self.active.values()), Decimal(0))
        reserve, _ = self._gate(own_resting=own)
        self._cash(self.required('f2_raw_post_balances', self.venue.balances), reserve)
        super().before_post(request)

    def final_post_gate(self):
        self.check_horizon()
        if (not any(band.posts for band in self.venue.coordinator.bands) and
                not self.campaign_entry.permits(self.clock.now())):
            raise HoldEnd('start_window_expired')

    def check_requote_cancel_response(self, oid, response):
        # A requote can lose to a fill. This permits only the existing read,
        # never a claim of cancellation or release of the durable reserve.
        if (isinstance(response, dict) and isinstance(response.get('not_canceled'), dict)
                and oid in response['not_canceled']):
            return
        return super().check_requote_cancel_response(oid, response)

    def cancel_remaining(self):
        # This is BAND cleanup, not a claim of account-wide cancellation.
        # Filled and already-terminal orders are proved, never labelled cancelled.
        rows = self._recover('cleanup_open_orders', self.venue.raw.open_orders)
        coordinator = self.venue.coordinator
        for row in rows:
            if coordinator.order_session(row) != self.session_id:
                continue  # A matching token, price and size cannot grant cancel authority.
            oid = _order_id(row)
            self._retain('cleanup_cancel_request', order_id=oid)
            response = self._recover('cleanup_cancel', lambda: self.venue.cancel(oid))
            self._retain('cleanup_cancel_response', order_id=oid, response=response)
            if (isinstance(response, dict) and isinstance(response.get('not_canceled'), dict)
                    and oid in response['not_canceled']):
                # The list can lag the first cancel or a match. The subsequent
                # empty read and terminal proofs still have to establish cleanup.
                continue
            if oid not in cancel_ack_ids(response):
                return False
        self._retain('f2_band_cleanup_scope', session_id=self.session_id, account_wide=False)
        return True

    def cancel_terminal_row(self, oid, row):
        row = super().cancel_terminal_row(oid, row)
        if self.breadth:
            # Requotes and final cleanup retain the same terminal-order proof.
            # Legacy protocol journals keep their original shape.
            self.journal.record('terminal_order', order=row, source='requote_cancel_read')
        return row

    def progress(self):
        status = getattr(self, 'outcome_status', None)
        try:
            if status is not None:
                status.progress()
            loop = getattr(self, 'heartbeat_loop', None)
            if loop is not None:
                loop.tick()
                if not loop.threaded:
                    loop.step()
        except Exception:
            self.evidence_failed = True  # Observer failure cannot stop cancellation.

    def _retain(self, event, **fields):
        self.progress()
        return super()._retain(event, **fields)

    def _recover(self, name, fn):
        def observed():
            self.progress()
            try:
                return fn()
            finally:
                self.progress()
        result = super()._recover(name, observed)
        if name == 'terminal_trades' or name == 'lfc_trades' and pairs.enabled(self):
            self.project_trades(result, source='rest')
        return result

    def terminal_order_read(self, oid, recover):
        """Prove unresolved legs first, with one shared in-band retry budget."""
        from weather.market.mm_account_reads import order_terminal
        from weather.market.re1_resilience import transient

        def probe(order_id):
            self.progress()
            try:
                row = self.venue.order(order_id)
            except Exception as exc:
                return None, type(exc).__name__, transient(exc)
            finally:
                self.progress()
            if order_terminal(row, order_id=order_id, size=self.size):
                return row, None, False
            if isinstance(row, dict) and _order_id(row) == order_id and str(
                    row.get('status', '')).upper() in {'LIVE', 'DELAYED', 'UNMATCHED'}:
                return None, 'OrderNotTerminal', True  # Terminal propagation may lag.
            return None, 'OrderBindingError', False

        def wait(delay):
            remaining = self._terminal_order_deadline - self.clock.monotonic()
            if remaining <= 0:
                return False
            self.clock.sleep(min(delay, remaining))
            return self.clock.monotonic() < self._terminal_order_deadline

        if self._terminal_order_deadline is None:
            self._terminal_order_deadline = self.clock.monotonic() + getattr(self, '_terminal_read_seconds', 10)
            unresolved = [order_id for order_id in self.known if self.ledger.legs.get(
                self.ledger.by_order.get(order_id), {}).get('status') != 'terminal']
            # Every unresolved identity gets an initial read, even if a peer
            # consumes the retry budget. Historical reads cannot spend it first.
            self._terminal_first_reads = {order_id: probe(order_id) for order_id in unresolved}
            pending = unresolved
            delay, rounds = 1, 0
            while pending:
                pending = [order_id for order_id in pending if self._terminal_first_reads[order_id][2]]
                if not pending or not wait(delay):
                    break
                for order_id in pending:
                    if self.clock.monotonic() >= self._terminal_order_deadline:
                        break
                    self._terminal_first_reads[order_id] = probe(order_id)
                rounds += 1
                delay = 2 if rounds >= 2 else 1
        historical = oid not in self._terminal_first_reads
        if historical:
            row, error, retryable = (probe(oid) if self.clock.monotonic() < self._terminal_order_deadline
                                      else (None, 'TerminalReadBudget', True))
            for delay in (1, 2):
                if not retryable or not wait(delay):
                    break
                row, error, retryable = probe(oid)
            if error == 'OrderNotTerminal':
                retryable = False  # A historically proved terminal order cannot reopen.
        else:
            row, error, retryable = self._terminal_first_reads.pop(oid)
        if error is None:
            return row
        self._retain('terminal_order_unavailable', order_id=oid, exception_type=error, retryable=retryable)
        raise TimeoutError('terminal_order_unavailable')

    def cleanup(self):
        self._terminal_order_deadline = None  # One shared budget for all known orders in this cleanup.
        # Global ends issue every band's cancels before any terminal retry
        # waits. A local retirement leaves quoting peers alone.
        final = (getattr(self.venue.coordinator, 'final_teardown', False) or
                 self.clock.monotonic() >= self.deadline)
        if not self.closed and final:
            self.venue.coordinator.cancel_bands_before_probes()
        self._terminal_read_seconds = 10 if getattr(self, '_repost_terminal_reads', False) and not final else 3
        status = getattr(self, 'outcome_status', None)
        previous = getattr(status, 'phase', None)
        if status is not None:
            status.phase = 'CLEANUP'
        try:
            return super().cleanup()
        finally:
            if status is not None:
                status.phase = previous


class F2Coordinator:
    def __init__(self, *, ledger, clock, directory, session_id, attempt_id, policy, entry, table,
                 status, verify, guard=None, repost_proof=None, heartbeat_key=None, heartbeat_signer=None, selected=()):
        self.ledger, self.clock, self.directory = ledger, clock, Path(directory)
        self.session_id, self.attempt_id, self.policy, self.entry = session_id, attempt_id, policy, entry
        self.table, self.status, self.verify = table, status, verify
        self.repost_proof = repost_proof
        self.heartbeat_key, self.heartbeat_signer, self.selected = heartbeat_key, heartbeat_signer, selected
        self.shared_wallet = heartbeat_key is not None
        self.guard = guard or SecretGuard()
        self.bands, self.results, self.closed_bands = [], {}, set()
        self.cleanup_ok = self.cancellation_ok = self.inventory_proven = False
        self.evidence_failed, self.posts, self.known, self.fill_seen = False, 0, {}, False
        self.reason, self.open_rows = 'fixed_end', None
        self.account_fault_reason = None
        self.owner_notice_digests = set()
        self.account_evidence_faults = set()
        self.task_readback_gaps = []
        self.post_books = None
        self.reward_context, self.reward_context_gaps = {}, set()
        from weather.market.lfc_f2_breadth import enabled, PROTOCOL as BREADTH_PROTOCOL
        self.scope = {'session_id': session_id, 'attempt_id': attempt_id,
                      'protocol': BREADTH_PROTOCOL if enabled(policy) else 'lfc_autostart_v2',
                      'policy_sha256': policy.sha256, **status.policy_metadata}
        self.journal = GuardedJournal(self.directory / 'journal.jsonl', clock=clock.now,
                                     scope=self.scope, mode='live', guard=self.guard)
        from weather.market.lfc_f2_geoblock import SharedGeoblock
        self.geoblock = SharedGeoblock(clock, self.journal)

    def retain(self, event, **fields):
        try:
            self.journal.record(event, **fields)
        except BaseException:
            self.evidence_failed = True

    def note_owner_activity(self, row):
        from weather.market.lfc_f2_owner_notice import OVERLAP
        event, raw = row['event_type'], row['raw_event_sha256']
        if raw not in self.owner_notice_digests:
            self.journal.record(event, activity_type=row['activity_type'], raw_event_sha256=raw,
                                activity_identity_sha256=row['activity_identity_sha256'])
            self.owner_notice_digests.add(raw)
        if event == OVERLAP:
            self.account_fault_reason = event
            raise HoldEnd(event)

    def note_task_readback_gap(self, row):
        # Persist before tolerating the read. This cannot mask missing money
        # evidence or a failed journal write with an ancillary gap label.
        self.journal.record('campaign_task_readback_unavailable', **row)
        self.task_readback_gaps.append(dict(row))
        self.account_evidence_faults.add('campaign_task_readback_unavailable')
        self.evidence_failed = True

    def acknowledged_session(self, oid):
        key = self.ledger.by_order.get(oid)
        if key is not None and self.ledger.event_rows('leg_ack', field='intent_key', value=key):
            return self.ledger.legs[key]['session_id']
        return None

    def order_session(self, row):
        session = self.acknowledged_session(_order_id(row))
        if session is not None and any(band.session_id == session for band in self.bands):
            return session
        return None

    def split_orders(self, rows):
        from weather.market.lfc_f2_order_scope import mark_open_orders, split
        if not isinstance(rows, list):
            raise CapitalRefused('foreign_open_order_identity')
        return split(self.ledger, mark_open_orders(rows, self.heartbeat_key, self.heartbeat_signer),
                     selected=self.selected)

    def foreign_orders_reserve(self, rows):
        from weather.market.lfc_f2_order_scope import foreign_reserve
        campaign, foreign = self.split_orders(rows)
        self.validate_account_orders(campaign)
        return foreign_reserve(self.ledger, foreign)

    def account_orders(self, rows):
        if self.shared_wallet:
            from weather.market.lfc_f2_order_scope import foreign_reserve
            try:
                rows, foreign = self.split_orders(rows)
                locked = foreign_reserve(self.ledger, foreign)
                if locked:
                    book = CapitalBook(self.ledger)
                    book.gate(reserve=0, available_cash=Decimal(book.expected_cash()) / SCALE, external_resting=locked)
            except CapitalRefused as exc:
                self.account_fault_reason = str(exc)
                raise HoldEnd(self.account_fault_reason) from exc
        self.validate_account_orders(rows)
        return rows

    def validate_account_orders(self, rows):
        if not isinstance(rows, list) or any(self.order_session(row) is None for row in rows):
            self.account_fault_reason = 'foreign_open_order'
            raise HoldEnd('foreign_open_order')
        for row in rows:
            key = self.ledger.by_order.get(_order_id(row))
            if key is not None and self.ledger.legs[key]['status'] == 'terminal':
                self.account_fault_reason = 'terminal_order_reappeared'
                raise HoldEnd(self.account_fault_reason)

    def cancel_bands_before_probes(self):
        """Request all known active cancellations before bounded final reads.

        These responses do not prove cancellation or release any reserve. Each
        band's ordinary cleanup and the final account verification still run.
        """
        if getattr(self, '_terminal_cancels_started', False):
            return
        self._terminal_cancels_started = True
        for band in self.bands:
            if band.closed:
                continue
            for oid in band.active:
                try:
                    band._retain('cleanup_cancel_request', order_id=oid)
                    response = band._recover('cleanup_cancel', lambda: band.venue.cancel(oid))
                    band._retain('cleanup_cancel_response', order_id=oid, response=response)
                except BaseException:
                    band._retain('cleanup_cancel_unavailable', order_id=oid)

    def finish_band(self, band, result):
        if band.session_id in self.closed_bands:
            raise RuntimeError('f2_band_already_closed')
        flags = evidence_flags(result)
        self.ledger.record('session_end', session_id=band.session_id, reason=result['reason'],
                           cleanup_ok=band.cleanup_ok, fill_seen=band.fill_seen, **flags)
        write_session_end(band.directory, {'session_id': band.session_id, 'reason': result['reason'],
                           'cleanup_ok': band.cleanup_ok, 'cancellation_ok': band.cancellation_ok,
                           'cancellation_scope': 'band', **flags, **self.status.policy_metadata})
        self.results[band.session_id] = result
        self.closed_bands.add(band.session_id)
        band.record_post_books('retirement')
        if self.status.resync_hook is not None:
            self.status.resync_hook()
        self.status.progress()

    def run(self):
        if not 1 <= len(self.bands) <= self.policy.raw['band_limit_concurrent']:
            raise RuntimeError('f2_band_count')
        primary = self.bands[0].venue.raw
        # The account heartbeat outlives any individual band. Its adapter's
        # raw acknowledgement must never target a retired/closed band journal.
        primary.heartbeat_journal = self.journal
        loop = HeartbeatLoop(self.clock, primary.heartbeat, self.journal,
                             threaded=getattr(self.clock, 'realtime', False))
        steps, due = {}, {}
        failed = None
        try:
            from weather.market.lfc_f2_post_books import POST_RETIREMENT_RECORDING, PostBookRecorder
            try:
                if POST_RETIREMENT_RECORDING and getattr(self.clock, 'realtime', False) and self.post_books is None:
                    self.post_books = PostBookRecorder(clock=self.clock, max_bands=len(self.bands), directory=self.directory)
                if self.post_books is not None:
                    self.post_books.start()
            except Exception as exc:
                if self.post_books is not None:
                    self.post_books.stop()
                self.post_books = None
                self.retain('post_book_recording_unavailable', exception_type=type(exc).__name__)
            self.status.phase = 'QUOTING'
            loop.start()
            for band in self.bands:
                band.heartbeat_loop = SharedHeartbeat(loop)
                band.outcome_status = self.status
                steps[band.session_id] = band.run_steps()
                due[band.session_id] = self.clock.monotonic()
            while steps:
                self.status.checkpoint()
                loop.tick()
                loop.check()
                for band in self.bands:
                    key = band.session_id
                    if key not in steps or self.clock.monotonic() < due[key]:
                        continue
                    try:
                        delay = next(steps[key])
                        due[key] = self.clock.monotonic() + delay
                    except StopIteration as done:
                        self.finish_band(band, done.value)
                        del steps[key]
                        if done.value.get('reason') == 'campaign_task_readback_unavailable':
                            raise HoldEnd('campaign_task_readback_unavailable')
                        if self.account_fault_reason:
                            raise HoldEnd(self.account_fault_reason)
                        if (done.value.get('unknown_submit') is not False or not band.cancellation_ok or
                                done.value.get('failure_type') is not None):
                            raise HoldEnd('f2_band_money_or_core_fault')
                if steps:
                    self.clock.sleep(min(1, max(0, min(due[key] for key in steps) - self.clock.monotonic())))
            if self.clock.monotonic() < max(band.deadline for band in self.bands):
                reasons = {row['reason'] for row in self.results.values()}
                self.reason = 'start_window_expired' if reasons == {'start_window_expired'} else 'all_bands_retired'
        except BaseException as exc:
            failed = exc
            self.reason = (exc.reason if isinstance(exc, HoldEnd) else
                           'owner_interrupt' if isinstance(exc, KeyboardInterrupt) else 'f2_exception')
            if self.reason == 'f2_exception':
                from weather.market.lfc_campaign_visibility import safe_traceback
                self.retain('f2_exception', exception_type=type(exc).__name__,
                            traceback=safe_traceback(exc.__traceback__))
        finally:
            if self.post_books is not None:
                self.post_books.stop()
            self.final_teardown = True
            self.status.phase = 'CLEANUP'
            # Inject the stop into each live band so it follows the ordinary
            # cancel, terminal read and private evidence path exactly once.
            for band in self.bands:
                key = band.session_id
                if key not in steps:
                    continue
                try:
                    steps[key].throw(HoldEnd(self.reason))
                except StopIteration as done:
                    self.finish_band(band, done.value)
                except BaseException:
                    self.evidence_failed = True
                    band.cleanup()
                finally:
                    steps[key].close()
            stage = 'cancel'
            try:
                # Band cleanup sent per-ID requests. An unproved submit
                # stays reserved and cannot authorize a wider cancellation.
                if hasattr(primary, 'set_journal'):
                    primary.set_journal(self.journal)
                self.retain('campaign_cleanup_scoped')
                for _ in range(10):
                    self.status.progress()
                    loop.tick()
                    rows = primary.open_orders()
                    self.open_rows = self.split_orders(rows)[0] if self.shared_wallet else rows
                    self.retain('account_cleanup_open_orders', rows=self.open_rows)
                    if self.open_rows == []:
                        break
                    self.clock.sleep(1)
                if self.open_rows == []:
                    loop.stop()
                self.cancellation_ok = self.open_rows == []
                stage = 'verify'
                self.status.phase = 'VERIFY'
                proof = self.verify()
                self.final_money_proof = proof
                self.cancellation_ok = self.open_rows == [] and proof.get('cleanup_proven') is True
                self.inventory_proven = proof.get('money_accounting_complete') is True
            except BaseException as exc:
                from weather.market.lfc_campaign_runtime import transient_read_error
                event = ('f2_account_read_unavailable' if stage == 'verify' else 'f2_account_cancel_unavailable')
                if not transient_read_error(exc):
                    event = 'f2_account_cleanup_fault'
                self.account_evidence_faults.add(event)
                self.retain(event, exception_type=type(exc).__name__)
                self.evidence_failed = True
            finally:
                loop.stop()
        if not self.cancellation_ok or not self.inventory_proven:
            self.account_evidence_faults.add('f2_account_cleanup_pending')
            self.retain('f2_account_cleanup_pending')
            self.evidence_failed = True
        self.posts = sum(band.posts for band in self.bands)
        self.known = {oid: band.session_id for band in self.bands for oid in band.known}
        self.fill_seen = any(band.fill_seen for band in self.bands)
        from weather.market.lfc_campaign_proof import ANCILLARY_SAMPLES, ANCILLARY_EVENT_GAPS, MONEY_READ_GAPS
        supported_gaps = ({'sample_' + name for name in ANCILLARY_SAMPLES} | ANCILLARY_EVENT_GAPS |
                          MONEY_READ_GAPS | {'scoring_missed', 'minute_missed'})
        private_money_intact = (not self.evidence_failed and len(self.results) == len(self.bands) and
            all(self.results[b.session_id].get('failure_type') is None and
                b._evidence_faults <= supported_gaps for b in self.bands))
        self.evidence_failed |= (len(self.results) != len(self.bands) or any(b.evidence_failed for b in self.bands))
        flags = {'evidence_complete': not self.evidence_failed, 'inventory_proven': self.inventory_proven,
                 'unknown_submit': self.posts != len(self.known)}
        # Root cancellation plus the final whole-account money/inventory proof
        # owns cleanup. Ancillary sampling gaps remain evidence_complete=false.
        self.cleanup_ok = (self.cancellation_ok and self.inventory_proven and
                           not flags['unknown_submit'] and private_money_intact)
        manifest = {'session_id': self.session_id, 'attempt_id': self.attempt_id,
                    'schema_version': ('lfc_f2_manifest_v0.2' if self.scope['protocol'] == 'lfc_autostart_v3' else 'lfc_f2_manifest_v0.1'), 'policy_sha256': self.policy.sha256, 'bands': []}
        for band in self.bands:
            hashes = {name: file_sha(band.directory / name) for name in
                      ('journal.jsonl', 'prediction.json', 'session_end.json', 'selection.json', 'attempt.json')
                      if (band.directory / name).exists()}
            hashes.update({path.name: file_sha(path) for pattern in ('submit-*.intent.json', 'submit-*.ack.json')
                           for path in band.directory.glob(pattern)})
            manifest['bands'].append({'session_id': band.session_id,
                'directory': band.directory.relative_to(self.directory).as_posix(),
                'condition_id': band.condition, 'token_ids': list(band.tokens), 'trade_legs': list(band.TRADE_LEGS),
                'evidence_sha256': hashes, 'reason': self.results.get(band.session_id, {}).get('reason', 'unproved'),
                'cancellation_scope': 'band', **({key: band.scope[key] for key in
                    ('market_id', *arm_field_keys(self.policy))}
                    if band.breadth else {})})
        write_new(self.directory / 'f2_manifest.json', manifest)
        terminal = {'reason': self.reason, 'failure_type': (type(failed).__name__ if failed is not None and
                    not isinstance(failed, HoldEnd) else None), 'cleanup_ok': self.cleanup_ok,
                    'cancellation_ok': self.cancellation_ok, 'cancellation_scope': 'campaign',
                    'submits': sum(b.submits for b in self.bands), 'requotes': sum(b.requotes for b in self.bands),
                    'post_count': self.posts, 'order_ids': list(self.known), 'fill_seen': self.fill_seen,
                    'post_book_recording_failure': getattr(self.post_books, 'failure', None),
                    'evidence_faults': sorted(self.account_evidence_faults | {f for b in self.bands for f in b._evidence_faults}), **flags}
        self.journal.record('terminal', **terminal)
        self.journal.close()
        result = {'mode': 'live', 'scope': self.scope, 'f2_session': True, **terminal,
                  'journal_sha256': file_sha(self.journal.path), 'manifest_sha256': file_sha(self.directory / 'f2_manifest.json')}
        write_new(self.directory / 'prediction.json', result)
        write_session_end(self.directory, {'session_id': self.session_id, **terminal,
                                           **self.status.policy_metadata})
        return result
