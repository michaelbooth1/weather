"""Offline shared-workstation admission outage regressions.

Guards: T119 bounded readiness retries, unchanged account facts and one WS reconnect.
"""
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from tests.market.test_lfc_f2_controller import setup
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import StateRefused
from weather.market.re1_transport import OwnerVenue


@pytest.fixture
def readiness(tmp_path, monkeypatch):
    from weather.market import lfc_f2_selection, lfc_pilot, re1_transport, lfc_campaign_runtime
    controller, account, status, ledger, clock = setup(tmp_path)
    monkeypatch.setattr(lfc_pilot, 'LfcPublicBooks', lambda: object())
    monkeypatch.setattr(lfc_f2_selection, 'discover', lambda *a, **kw: controller.table)
    monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': ledger.rows[0]['maker_address']}, None))
    monkeypatch.setattr(re1_transport, 'build_client', lambda *a, **kw: object())
    monkeypatch.setattr(lfc_campaign_runtime, 'selection_account_screen', lambda *a: None)
    venue = SimpleNamespace(start=lambda: None, close=lambda: None, events=lambda: [], open_orders=lambda: [],
        positions=lambda: [], balances=lambda: {'available_collateral': '300'}, geography=lambda: {'blocked': False},
        heartbeat=lambda: {'status': 'ok'})
    monkeypatch.setattr(re1_transport, 'OwnerVenue', lambda *a, **kw: venue)
    runtime = SimpleNamespace(state=SimpleNamespace(root=tmp_path / 'state', ledger=ledger,
        maker=ledger.rows[0]['maker_address']), clock=clock, task_enabled=lambda: True)
    def run():
        return Runtime.readiness(runtime, controller.entry, controller.policy,
                                 {'balances': {'available_collateral': '300'}, 'positions': []})
    return run, venue, clock, tmp_path


@pytest.mark.parametrize('name', ['events', 'open_orders', 'positions', 'balances', 'geography', 'heartbeat'])
def test_readiness_retries_one_transient_per_sample_and_keeps_timeout_budgets(readiness, name):
    run, venue, clock, root = readiness
    original, calls = getattr(venue, name), []
    def flaky():
        calls.append(True)
        if len(calls) % 2:
            clock.sleep(.1)
            raise URLError('synthetic transport gap')
        clock.sleep(.44)
        return original()
    setattr(venue, name, flaky)
    result = run()
    assert result['timeouts_seconds']['heartbeat'] == 2
    assert all(value >= 5 for key, value in result['timeouts_seconds'].items() if key != 'heartbeat')
    assert len(calls) == (12 if name == 'heartbeat' else 6)
    assert len(list((root / 'state' / 'readiness').glob('*/*-unavailable.json'))) == len(calls) // 2


def test_readiness_persistent_error_is_bounded_and_deferred(readiness):
    run, venue, _, _ = readiness
    calls = []
    def fail():
        calls.append(True)
        raise ConnectionError('fixture')
    venue.open_orders = fail
    with pytest.raises(TransientPrecheck, match='readiness_transport_unavailable'): run()
    assert len(calls) == 3


@pytest.mark.parametrize('name,value,reason', [('open_orders', [{}], 'account_not_empty'),
    ('geography', {'blocked': True}, 'geoblock'), ('geography', {}, 'geoblock')])
def test_readiness_never_retries_a_failed_account_fact(readiness, name, value, reason):
    run, venue, _, _ = readiness
    calls = []
    setattr(venue, name, lambda: calls.append(True) or value)
    with pytest.raises(StateRefused, match=reason): run()
    assert len(calls) == 1


def test_readiness_still_refuses_slow_heartbeat_latency(readiness):
    run, venue, clock, _ = readiness
    venue.heartbeat = lambda: clock.sleep(3) or {'status': 'ok'}
    with pytest.raises(TransientPrecheck, match='heartbeat_latency_budget'): run()


@pytest.mark.parametrize('failure', ['WebSocketConnectionClosedException', 'SSLEOFError', 'RuntimeError'])
def test_private_bootstrap_retains_first_failure_and_requires_fresh_pong(tmp_path, failure):
    seen, created = [], []
    class Stream:
        def __init__(self, number): self.number, self.state = number, 'NEW'
        def start(self):
            seen.append(('start', self.number))
            self.state = 'FAILED' if self.number == 0 else 'TRANSPORT_CONNECTED_UNPROVEN'
        def health(self): return {'state': self.state, 'failure_type': failure}
        def bootstrap_evidence(self):
            return dict(transport_active=self.number == 1, server_pong_observed=self.number == 1,
                        account_wide_subscription_sent=True)
        def stop(self, **kwargs): seen.append(('stop', self.number))
    venue = object.__new__(OwnerVenue)
    venue.stream, venue.stream_number, venue.stream_args, venue.directory = Stream(0), 0, {}, tmp_path
    def factory(**kwargs):
        created.append(kwargs['journal_path'].name)
        return Stream(1)
    venue.stream_factory = factory
    if failure == 'RuntimeError':
        with pytest.raises(RuntimeError, match='user_stream_invalid_event'): venue.start()
        assert not created
    else:
        venue.start()
        assert seen == [('start', 0), ('stop', 0), ('start', 1)]
        assert created == ['user-stream-1.jsonl']
