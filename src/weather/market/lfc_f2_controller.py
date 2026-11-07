"""One cooperative owner process, at most two independent F0-shaped bands.

No thread posts orders. Each band retains its own 10-submit/4-requote budget,
private journal and durable intents. A fill/horizon retirement cancels that
band only; any monetary ambiguity, STOP or account fault cleans up the account.
The final account-wide cancel/verify remains distinct from band cancellation.
"""
from decimal import Decimal
from pathlib import Path

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import CapitalBook, CapitalRefused, SCALE
from weather.market.lfc_completion import complete_evidence, evidence_flags
from weather.market.lfc_pilot import PilotSession, write_session_end
from weather.market.lfc_recording_io import file_sha, write_new
from weather.market.mm_stage2_hold import HoldEnd, _order_id, cancel_ack_ids, digest
from weather.market.re1_attended import GuardedJournal, SecretGuard, observe
from weather.market.re1_resilience import HeartbeatLoop


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
        rows = self.raw.open_orders()
        self.coordinator.validate_account_orders(rows)
        return [row for row in rows if self.coordinator.order_session(row) == self.session_id]

    def cancel_all(self):
        raise RuntimeError('band_has_no_account_cancel_all')


class F2Band(PilotSession):
    def __init__(self, *, policy, entry, **kwargs):
        self.campaign_policy, self.campaign_entry = policy, entry
        chosen = next(row for row in kwargs['table']['rows']
                      if row['condition_id'] == kwargs['table']['selected_condition_id'])
        self.TRADE_LEGS = tuple(chosen['trade_legs'])
        self.LEG_PRICE_RANGE = tuple(map(quantity, policy.raw['leg_price_range']))
        super().__init__(**kwargs)
        self.OFFSET = quantity(policy.raw['quote_offset_pusd'])
        self.REQUOTE_WINDOW = tuple(map(quantity, policy.raw['requote_distance_cents']))
        self.SECONDS = self.planned_seconds  # Late entry keeps the absolute end.
        self.cap = quantity(policy.raw['owner_funding_ceiling_pusd'])
        self.scope.update(budget_pusd=str(self.cap), capital_mode=policy.raw['capital_mode'],
                          trade_legs=list(self.TRADE_LEGS), quote_offset_pusd=str(self.OFFSET),
                          requote_distance_cents=list(map(str, self.REQUOTE_WINDOW)))

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
        return (bool(self.attempt) and self.attempt.get('protocol') == 'lfc_autostart_v2' and
                type(self.attempt.get('session_number')) is int and self.attempt['session_number'] >= 1)

    def observe_snapshot(self, snapshot):
        return observe(snapshot, self.prices, self.size, self.SIZES, reward_terms=True,
                       window=self.REQUOTE_WINDOW, trade_legs=self.TRADE_LEGS)

    def _gate(self, *, own_resting=Decimal(0)):
        reserve = self.size * sum(self.reserve_prices(), Decimal(0))
        try:
            figures = CapitalBook(self.ledger).gate(reserve=reserve, own_resting=own_resting)
        except CapitalRefused as exc:
            raise HoldEnd(str(exc)) from None
        return reserve, Decimal(figures['charged_native']) / SCALE - own_resting

    def _cash(self, balances, reserve):
        own = sum((self.size * price for _, price in self.active.values()), Decimal(0))
        try:
            figures = CapitalBook(self.ledger).gate(reserve=reserve, own_resting=own,
                                                   available_cash=balances['available_collateral'])
        except CapitalRefused as exc:
            raise HoldEnd(str(exc)) from None
        return quantity(balances['available_collateral']), Decimal(figures['resting_reserve_native']) / SCALE

    def authorize_post(self, leg, price, size, rule):
        # Every placement/requote, not just selection or the first band.
        reserve, _ = self._gate(own_resting=sum((self.size * p for _, p in self.active.values()), Decimal(0)))
        self._cash(self.required('f2_post_balances', self.venue.balances), reserve)
        super().authorize_post(leg, price, size, rule)

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

    def cancel_remaining(self):
        # This is BAND cleanup, not a claim of account-wide cancellation.
        # Filled and already-terminal orders are proved, never labelled cancelled.
        rows = self._recover('cleanup_open_orders', self.venue.open_orders)
        for row in rows:
            oid = _order_id(row)
            self._retain('cleanup_cancel_request', order_id=oid)
            response = self._recover('cleanup_cancel', lambda: self.venue.cancel(oid))
            self._retain('cleanup_cancel_response', order_id=oid, response=response)
            if oid not in cancel_ack_ids(response):
                return False
        self._retain('f2_band_cleanup_scope', session_id=self.session_id, account_wide=False)
        return True


class F2Coordinator:
    def __init__(self, *, ledger, clock, directory, session_id, attempt_id, policy, entry, table,
                 status, verify, guard=None):
        self.ledger, self.clock, self.directory = ledger, clock, Path(directory)
        self.session_id, self.attempt_id, self.policy, self.entry = session_id, attempt_id, policy, entry
        self.table, self.status, self.verify = table, status, verify
        self.guard = guard or SecretGuard()
        self.bands, self.results, self.closed_bands = [], {}, set()
        self.cleanup_ok = self.cancellation_ok = self.inventory_proven = False
        self.evidence_failed, self.posts, self.known, self.fill_seen = False, 0, {}, False
        self.reason, self.open_rows = 'fixed_end', None
        self.account_fault_reason = None
        self.account_evidence_faults = set()
        self.scope = {'session_id': session_id, 'attempt_id': attempt_id, 'protocol': 'lfc_autostart_v2',
                      'policy_sha256': policy.sha256, **status.policy_metadata}
        self.journal = GuardedJournal(self.directory / 'journal.jsonl', clock=clock.now,
                                     scope=self.scope, mode='live', guard=self.guard)

    def retain(self, event, **fields):
        try:
            self.journal.record(event, **fields)
        except BaseException:
            self.evidence_failed = True

    def order_session(self, row):
        oid = _order_id(row)
        for band in self.bands:
            if oid in band.known:
                return band.session_id
        # An ACK-lost request stays reserved and fails the final flags. This
        # exact field match only permits cleanup; it never adopts or retries it.
        for band in self.bands:
            if band._ours(row):
                return band.session_id
        return None

    def validate_account_orders(self, rows):
        if not isinstance(rows, list) or any(self.order_session(row) is None for row in rows):
            self.account_fault_reason = 'foreign_open_order'
            raise HoldEnd('foreign_open_order')
        for row in rows:
            key = self.ledger.by_order.get(_order_id(row))
            if key is not None and self.ledger.legs[key]['status'] == 'terminal':
                self.account_fault_reason = 'terminal_order_reappeared'
                raise HoldEnd(self.account_fault_reason)

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
        finally:
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
                # Band journals are closed. Rebind the primary SDK's existing
                # observational hooks before account-wide cleanup; no hook may
                # prevent cancellation by writing to an already closed band.
                if hasattr(primary, 'set_journal'):
                    primary.set_journal(self.journal)
                self.retain('account_cleanup_cancel_all_request')
                response = primary.cancel_all()
                cancel_ack_ids(response)
                self.retain('account_cleanup_cancel_all_response', response=response)
                for _ in range(10):
                    self.open_rows = primary.open_orders()
                    self.retain('account_cleanup_open_orders', rows=self.open_rows)
                    if self.open_rows == []:
                        break
                    self.clock.sleep(1)
                if self.open_rows == []:
                    loop.stop()
                self.cancellation_ok = self.open_rows == []
                stage = 'verify'
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
        self.evidence_failed |= (len(self.results) != len(self.bands) or any(b.evidence_failed for b in self.bands))
        flags = {'evidence_complete': not self.evidence_failed, 'inventory_proven': self.inventory_proven,
                 'unknown_submit': self.posts != len(self.known)}
        self.cleanup_ok = self.cancellation_ok and complete_evidence(flags)
        manifest = {'session_id': self.session_id, 'attempt_id': self.attempt_id,
                    'schema_version': 'lfc_f2_manifest_v0.1', 'policy_sha256': self.policy.sha256, 'bands': []}
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
                'cancellation_scope': 'band'})
        write_new(self.directory / 'f2_manifest.json', manifest)
        terminal = {'reason': self.reason, 'failure_type': (type(failed).__name__ if failed is not None and
                    not isinstance(failed, HoldEnd) else None), 'cleanup_ok': self.cleanup_ok,
                    'cancellation_ok': self.cancellation_ok, 'cancellation_scope': 'account',
                    'submits': sum(b.submits for b in self.bands), 'requotes': sum(b.requotes for b in self.bands),
                    'post_count': self.posts, 'order_ids': list(self.known), 'fill_seen': self.fill_seen,
                    'evidence_faults': sorted(self.account_evidence_faults | {f for b in self.bands for f in b._evidence_faults}), **flags}
        self.journal.record('terminal', **terminal)
        self.journal.close()
        result = {'mode': 'live', 'scope': self.scope, 'f2_session': True, **terminal,
                  'journal_sha256': file_sha(self.journal.path), 'manifest_sha256': file_sha(self.directory / 'f2_manifest.json')}
        write_new(self.directory / 'prediction.json', result)
        write_session_end(self.directory, {'session_id': self.session_id, **terminal,
                                           **self.status.policy_metadata})
        return result
