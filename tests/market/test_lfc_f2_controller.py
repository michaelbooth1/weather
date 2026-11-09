"""Closed in-memory two-band sessions: no SDK, account, signer or network.

Guards: B036 per-band limits/retirement, one claim, hard end, STOP and retained proof.
The actual ScheduledAuthority type is used with fixture-only admission callbacks.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_pilot import Clock
from tests.market.test_lfc_f2_selection import universe
from tests.market.test_lfc_f2_capital import install
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import ScheduledAuthority, ScheduledProfile
from weather.market.lfc_capital import CapitalBook, bridge, native
from weather.market.lfc_f2_controller import F2Band, F2Coordinator, ScopedVenue
from weather.market.lfc_f2_evidence import F2Status
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_f2_selection import band_table, build_table
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import write_new
from weather.market.mm_stage2_hold import HoldEnd, digest
from weather.market.re1_rehearsal import RehearsalVenue


NOW = datetime(2026, 11, 11, 14, tzinfo=timezone.utc)
MAKER = '0x' + 'a' * 40


class Account:
    def __init__(self, clock):
        self.clock, self.raws, self.cancel_all_calls = clock, [], []
        self.filled_band = self.fill_at = self.stop_at = None
        self.unknown_ack_band = None
        self.scoring_missed = False
        self.exposure = []

    def advance(self):
        if self.filled_band is not None and self.clock.seconds >= self.fill_at:
            raw = self.raws[self.filled_band]
            if raw.memory.orders:
                first = next(iter(raw.memory.orders.values()))
                first.update(status='MATCHED', size_matched='1', associate_trades=['synthetic-fill'])
        self.exposure.append((self.clock.seconds, [r['id'] for raw in self.raws for r in raw.memory.orders.values()
                                                  if r['status'] == 'LIVE']))

    def open_orders(self):
        self.advance()
        return deepcopy([r for raw in self.raws for r in raw.memory.orders.values() if r['status'] == 'LIVE'])

    def checkpoint(self):
        if self.stop_at is not None and self.clock.seconds >= self.stop_at:
            raise HoldEnd('owner_stop')


class Raw(RehearsalVenue):
    def __init__(self, snapshot, directory, *, clock, account, index):
        super().__init__(snapshot, directory, clock=clock)
        self.account, self.index = account, index
        account.raws.append(self)
        self.cancellations = []

    def open_orders(self):
        return self.account.open_orders()

    def order(self, oid):
        self.account.advance()
        return super().order(oid)

    def balances(self):
        return {'available_collateral': '300'}

    def submit(self, request, *, checkpoint=lambda: None):
        response = super().submit(request, checkpoint=checkpoint)
        old = response['order_id']
        oid = getattr(self.account, 'prefix', '') + str(self.index) + '-' + old
        row = self.memory.orders.pop(old)
        row['id'] = oid
        self.memory.orders[oid] = row
        response['order_id'] = oid
        if self.account.unknown_ack_band == self.index:
            raise ConnectionError('synthetic ACK loss after durable POST')
        return response

    def cancel(self, oid):
        self.cancellations.append((self.account.clock.seconds, oid))
        if self.memory.orders[oid]['status'] != 'MATCHED':
            self.memory.orders[oid]['status'] = 'CANCELED'
        return {'canceled': [oid], 'not_canceled': {}}

    def cancel_all(self):
        self.account.cancel_all_calls.append(self.account.clock.seconds)
        ids = []
        for raw in self.account.raws:
            for oid, row in raw.memory.orders.items():
                if row['status'] == 'LIVE':
                    raw.cancel(oid)
                    ids.append(oid)
        return {'canceled': ids, 'not_canceled': {}}

    def trades(self):
        return [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': r['id'], 'matched_amount': r['size_matched']} ]}
                for r in self.memory.orders.values() if Decimal(r['size_matched'])]

    def scoring(self, ids):
        if self.account.scoring_missed:
            raise TimeoutError('synthetic scoring gap')
        return super().scoring(ids)


def setup(tmp_path, *, tokens=None, k=2, offset='.015', window=None, late_seconds=0, enrolled=False,
          base=NOW, schedule=None, shared_ledger=None, shared_state=None, session_id='F2-fixture',
          policy_row=None, universe_rows=None, account_type=Account, raw_type=Raw):
    row = deepcopy(policy_row) if policy_row is not None else example_policy()
    row.update(max_session_seconds=300, band_limit_session=k, band_limit_concurrent=k)
    if schedule:
        row.update(schedule)
    if tokens is not None:
        row['tokens'] = tokens
    row['quote_offset_pusd'] = offset
    if window is not None:
        row['requote_distance_cents'] = window
    policy = parse_policy(row)
    from zoneinfo import ZoneInfo
    local_date = base.astimezone(ZoneInfo('America/Toronto')).date().isoformat()
    entry = next(e for e in policy.entries if e.local_date == local_date)
    clock = Clock(base)
    clock.seconds = late_seconds
    ledger = shared_ledger or Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    ledger.clock = clock.now
    if shared_ledger is None:
        install(ledger, cash='300')
    state, claim = None, None
    if enrolled:
        from weather.market.lfc_campaign_state import AccountState
        state = shared_state or AccountState(tmp_path / 'state', ledger)
        if ledger.enrollment is None:
            state.enroll(clock.now())
        claim = state.claim(entry, policy, clock.now())
    attempt_id = claim['attempt_id'] if claim is not None else 'a' * 32
    rows = deepcopy(universe_rows) if universe_rows is not None else universe()
    if base != NOW:
        from zoneinfo import ZoneInfo
        for source in rows:
            source['snapshot']['observed_at_utc'] = clock.now().isoformat()
            source['target_date'] = (clock.now().astimezone(ZoneInfo(source['market_timezone'])).date()
                                     + timedelta(days=1)).isoformat()
    if tokens is not None and tokens != ['YES', 'NO']:
        # A sufficiently shallow but qualifying cheap side gives nonzero
        # one-sided reward weight while preserving the F0 displayed-depth guard.
        for source in rows:
            inputs = source['snapshot']['quote_inputs']
            inputs['reward_max_spread_cents'] = '6'
            inputs['yes_bids'] = [{'price': '.34', 'size': '20'}, {'price': '.29', 'size': '55'}]
            inputs['yes_asks'] = [{'price': '.35', 'size': '20'}, {'price': '.40', 'size': '55'}]
    table = build_table(rows, now=clock.now(), policy=policy, cash='300', capital=CapitalBook(ledger).figures())
    assert len(table['selected_condition_ids']) == k, table['rows']
    account = account_type(clock)
    account.prefix = '' if session_id == 'F2-fixture' else session_id + '-'
    account.state, account.claim, account.policy = state, claim, policy
    directory = tmp_path / ('session-' + session_id)
    directory.mkdir()
    write_new(directory / 'selection.json', table)
    write_new(directory / 'attempt.json', {'attempt_id': attempt_id, 'policy_sha256': policy.sha256})
    status = F2Status(kind='autostart', clock=clock.now, monotonic=clock.monotonic,
                      checkpoint_hook=account.checkpoint, policy_metadata=policy.labels(entry.local_date))
    status.directory = tmp_path / 'status'
    status.stop_file = tmp_path / 'OWNER-STOP-FIXTURE'
    def verify():
        return {'money_accounting_complete': not ledger.unresolved_legs(),
                'cleanup_proven': account.open_orders() == [] and not ledger.unresolved_legs()}
    coordinator = F2Coordinator(ledger=ledger, clock=clock, directory=directory, session_id=session_id,
                    attempt_id=attempt_id, policy=policy, entry=entry, table=table, status=status, verify=verify)
    status.bind(coordinator.session_id, directory=directory, selection={}, ledger=ledger)
    status.session = coordinator
    authority = object.__new__(ScheduledAuthority)
    from weather.market.lfc_f2_breadth import enabled, PROTOCOL as BREADTH_PROTOCOL
    breadth = enabled(policy)
    protocol = BREADTH_PROTOCOL if breadth else 'lfc_autostart_v2'
    authority.policy, authority.entry, authority.protocol = policy, entry, protocol
    authority.session_end = lambda start, seconds: entry.session_end(start)
    authority.confirmation_valid = lambda table, receipt: receipt == {'fixture_only': True}
    for index, cid in enumerate(table['selected_condition_ids'], 1):
        chosen = next(r for r in table['rows'] if r['condition_id'] == cid)
        sid = session_id + '-b' + str(index)
        child = directory / ('band-' + str(index))
        child.mkdir()
        attempt = {'counted': index == 1, 'session_number': 1, 'protocol': protocol,
                   **status.policy_metadata}
        write_new(child / 'attempt.json', attempt)
        from weather.market.lfc_f2_breadth import arm_field_keys
        arm_fields = ({key: chosen[key] for key in arm_field_keys(policy)}
                      if breadth else {})
        day_fields = ({'quote_day_utc': clock.now().date().isoformat(), 'market_id': chosen['market_id'],
                       'per_band_daily_filled_cap_pusd': policy.raw['per_band_daily_filled_cap_pusd']} if breadth else {})
        if policy.raw['schema_version'] == 'lfc_campaign_policy_v0.4':
            day_fields.update(autostart_policy_schema=policy.raw['schema_version'],
                max_submits_per_band=policy.raw['max_submits_per_band'],
                max_requotes_per_band=policy.raw['max_requotes_per_band'])
        ledger.record('session_start', session_id=sid, counted=index == 1,
                    owner_local_date=entry.local_date, condition_id=cid, autostart_attempt_id=attempt_id,
                    autostart_policy_sha256=policy.sha256, protocol=protocol, **arm_fields, **day_fields,
                    directory=child.relative_to(tmp_path).as_posix())
        raw = raw_type(chosen['snapshot'], child, clock=clock, account=account, index=index - 1)
        band = F2Band(policy=policy, entry=entry, ledger=ledger, session_id=sid,
                    profile=ScheduledProfile(policy, entry), root=tmp_path,
                    exclusion={'event_slug': chosen['event_slug'], 'condition_ids': chosen['event_condition_ids'],
                               'timezone_name': chosen['market_timezone']},
                    venue=ScopedVenue(raw, coordinator, sid), public=raw, table=band_table(table, cid), clock=clock,
                    directory=child, mode='live', confirmation={'fixture_only': True}, attempt=attempt,
                    scheduled_authority=authority)
        coordinator.bands.append(band)
    return coordinator, account, status, ledger, clock


def test_two_bands_share_one_session_claim_and_keep_limits_per_band(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    result = controller.run()
    assert result['cleanup_ok'] and result['post_count'] == 4, result
    assert [b.submits for b in controller.bands] == [2, 2]
    assert ledger.counted_sessions() == 1 and len(ledger.sessions) == 2
    assert account.cancel_all_calls == [300]
    assert max(len(ids) for _, ids in account.exposure) == 4
    outcome = status.finish(success=True)
    assert outcome['state'] == 'COMPLETE' and outcome['f2_session']
    assert outcome['economics']['planning']['label'] == 'PLANNING'
    assert outcome['economics']['measured']['label'] == 'MEASURED'
    from weather.market.lfc_campaign_proof import local_money_proof
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id='a' * 32, outcome=outcome)
    assert proof['complete'] and not proof['unknown_submit'], proof


def test_first_fill_retires_only_own_band_without_replacement(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    account.filled_band, account.fill_at = 0, 12
    result = controller.run()
    assert controller.results[controller.bands[0].session_id]['reason'] == 'fill'
    assert controller.results[controller.bands[1].session_id]['reason'] == 'fixed_end'
    assert [b.submits for b in controller.bands] == [2, 2]
    assert any(second == 200 and len(ids) == 2 for second, ids in account.exposure)
    assert all(when >= 300 for when, _ in account.raws[1].cancellations)
    assert account.cancel_all_calls == [300]
    assert result['cleanup_ok'], result


def test_stop_cleans_all_bands_and_requests_one_account_cancel_all(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    account.stop_at = 12
    result = controller.run()
    assert result['reason'] == 'owner_stop'
    assert not ledger.unresolved_legs() and not account.open_orders()
    assert account.cancel_all_calls == [12]
    assert all(b.closed for b in controller.bands)


def test_ack_loss_stops_other_band_and_never_releases_unknown_reserve(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    account.unknown_ack_band = 0
    result = controller.run()
    assert result['unknown_submit'] and not result['cleanup_ok']
    assert controller.bands[1].submits == 0
    assert ledger.unacknowledged_intents() and CapitalBook(ledger).figures()['resting_reserve_native'] > 0
    assert account.cancel_all_calls


def test_scoring_gap_does_not_end_either_band(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    account.scoring_missed = True
    result = controller.run()
    assert clock.seconds == 300
    assert all(r['reason'] == 'fixed_end' for r in controller.results.values())
    assert not result['evidence_complete']
    outcome = status.finish(success=False)
    from weather.market.lfc_campaign_proof import local_money_proof
    proof = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                             attempt_id='a' * 32, outcome=outcome)
    assert proof['complete'] and not proof['unknown_submit'], proof


def test_submit_and_requote_limits_are_per_band_and_price_caps_dominate(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path)
    for band in controller.bands:
        band.control = lambda **kwargs: None
    first, second = controller.bands
    first.submits = 10
    with pytest.raises(HoldEnd) as stop:
        first.submit(0, first.prices[0])
    assert stop.value.reason == 'submit_budget' and second.submits == 0
    first.submits, first.requotes = 0, 5
    with pytest.raises(HoldEnd) as stop:
        first.submit(0, first.prices[0])
    assert stop.value.reason == 'submit_budget' and second.requotes == 0
    first.requotes, first.prices[0] = 0, Decimal('.80')
    with pytest.raises(HoldEnd) as stop:
        first.submit(0, Decimal('.80'))
    assert stop.value.reason == 'capital_cap'
    for band in controller.bands:
        band.journal.close()
    controller.journal.close()


@pytest.mark.parametrize('tokens,expected_legs', [(['YES'], [0]), (['NO'], [1]), (['CHEAP'], [0])])
def test_one_sided_field_places_only_selected_token_and_reserves_only_that_leg(tmp_path, tokens, expected_legs):
    controller, account, status, ledger, clock = setup(tmp_path, tokens=tokens)
    result = controller.run()
    assert result['cleanup_ok'] and result['post_count'] == 2, result
    assert all(list(b.TRADE_LEGS) == expected_legs for b in controller.bands)
    assert all(len(raw.calls) == 1 for raw in account.raws)
    for band, raw in zip(controller.bands, account.raws):
        assert raw.calls[0]['token_id'] == band.tokens[expected_legs[0]]


def test_denver_local_midnight_retires_only_denver_while_toronto_continues(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path,
        base=datetime(2026, 11, 11, 6, 55, tzinfo=timezone.utc),
        schedule={'start_window_toronto': ['01:55:00', '02:00:00'],
                  'trading_end_toronto': '02:10:00', 'max_session_seconds': 900})
    result = controller.run()
    by_city = {band.horizon_row['market_id']: band for band in controller.bands}
    denver, toronto = by_city['denver'], by_city['toronto']
    assert controller.results[denver.session_id]['reason'] == 'market_local_horizon'
    assert controller.results[toronto.session_id]['reason'] == 'fixed_end'
    assert denver.horizon_retirement['current_local_event_dte'] == 0
    assert not hasattr(toronto, 'horizon_retirement')
    assert result['cleanup_ok'] and account.cancel_all_calls == [900]
    assert any(second == 600 and len(ids) == 2 for second, ids in account.exposure)


def test_legacy_session_count_is_not_a_new_hidden_F2_stop(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path, k=1)
    controller.bands[0].attempt['session_number'] = 500
    assert controller.bands[0].session_number_ok()
    result = controller.run()
    assert result['cleanup_ok'] and result['post_count'] == 2


def test_opening_read_latency_cannot_start_first_order_after_window(tmp_path):
    controller, account, status, ledger, clock = setup(tmp_path, late_seconds=899,
                                                     schedule={'max_session_seconds': 3600})
    for raw in account.raws:
        original = raw.submit
        def delayed(request, *, checkpoint, original=original):
            clock.sleep(2)
            return original(request, checkpoint=checkpoint)
        raw.submit = delayed
    result = controller.run()
    assert result['reason'] == 'start_window_expired'
    assert result['post_count'] == 0 and result['unknown_submit'] is False
    assert not ledger.legs and not any(raw.calls for raw in account.raws)
    assert not list(controller.directory.glob('band-*/*.intent.json'))
