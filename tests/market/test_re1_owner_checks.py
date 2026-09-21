"""Owner-only command flow with injected credentials/client; never real auth."""
from contextlib import nullcontext
from types import SimpleNamespace
import json

import pytest

from tests.market.test_re1_attended import setup
from weather.market.re1_attended import SecretGuard
from weather.market.re1_owner_checks import run_preflight, clean_preflight


def preflight_fixture(tmp_path, monkeypatch, *, failed=None, nonempty=False):
    from weather.market import re1_owner_checks as checks, re1_transport as transport
    session, fake, clock = setup(tmp_path / 'selection-fixture')
    table = session.table
    session.journal.close()
    root = tmp_path / 'campaign'
    monkeypatch.setattr(checks, 'campaign_root', lambda: root)
    monkeypatch.setattr(checks, 'live_mutex', nullcontext)
    monkeypatch.setattr(checks, 'code_identity', lambda: 'f' * 40)
    monkeypatch.setattr(checks, 'WallClock', lambda: clock)
    monkeypatch.setattr(checks, 'Re1PublicBooks', lambda: SimpleNamespace(selection=lambda: table))
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    fields = {'FUNDER_ADDRESS': fake.maker}
    def credentials(mode):
        assert mode == 'preflight'
        return fields, SecretGuard(['synthetic-private'])
    monkeypatch.setattr(transport, 'load_owner_credentials', credentials)
    monkeypatch.setattr(transport, 'build_client', lambda f, readonly: SimpleNamespace(close=lambda: None) if readonly else pytest.fail('write client'))
    counts, beats = {}, []
    class Venue:
        journal_failed = False
        def __init__(self, client, f, guard, **kwargs):
            assert kwargs['readonly'] and kwargs['preflight']
        def set_journal(self, journal): self.journal = journal
        def start(self):
            if failed == 'bootstrap': raise TimeoutError()
        def close(self): pass
        def read(self, name, value):
            counts[name] = counts.get(name, 0) + 1
            if failed == name and counts[name] == 3: raise TimeoutError('synthetic-private')
            clock.sleep(.1)
            return value
        def open_orders(self): return self.read('open_orders', [{}] if nonempty else [])
        def events(self): return self.read('user_stream', [])
        def positions(self): return self.read('positions', [])
        def balances(self): return self.read('balances', {'available_collateral': '50'})
        def geography(self): return self.read('geoblock', {'blocked': False})
        def accrual(self, day): return self.read('accrual', {'day': day, 'rows': []})
        def heartbeat(self):
            beats.append(clock.seconds)
            self.journal.record('heartbeat_v1_acknowledgment', response={'heartbeat_id': str(len(beats))})
            return self.read('heartbeat', {'status': 'ok'})
    monkeypatch.setattr(transport, 'OwnerVenue', Venue)
    return root, clock, counts, beats


def test_preflight_twenty_reads_six_heartbeats_no_attempt(tmp_path, monkeypatch):
    root, clock, counts, beats = preflight_fixture(tmp_path, monkeypatch)
    assert run_preflight() == 0
    assert counts == dict.fromkeys(('open_orders', 'positions', 'balances', 'geoblock', 'accrual'), 20) | {'heartbeat': 6, 'user_stream': 21}
    assert all(b-a == pytest.approx(5) for a, b in zip(beats, beats[1:]))
    assert not list(root.glob('session-*'))
    row = clean_preflight(root, now=clock.now(), commit='f' * 40)
    assert row['timeouts_seconds'] == dict.fromkeys(counts, 2)
    assert row['latency_seconds']['open_orders']['count'] == 20
    with pytest.raises(RuntimeError, match='preflight'):
        clean_preflight(root, now=clock.now(), commit='e' * 40)


@pytest.mark.parametrize('failure', ['positions', 'bootstrap'])
def test_preflight_failure_names_step_and_exception_without_secret(tmp_path, monkeypatch, capsys, failure):
    root, clock, _, _ = preflight_fixture(tmp_path, monkeypatch, failed=failure)
    assert run_preflight() == 1
    output = capsys.readouterr().out
    assert 'FAIL' in output and 'TimeoutError' in output and 'synthetic-private' not in output
    path = next(root.glob('preflight-*/preflight.json'))
    row = json.loads(path.read_bytes())
    expected = 'user_stream_readiness' if failure == 'bootstrap' else failure
    assert any(r['step'] == expected and r['exception_type'] == 'TimeoutError' for r in row['failures'])
    with pytest.raises(RuntimeError, match='preflight'):
        clean_preflight(root, now=clock.now(), commit='f' * 40)


def test_preflight_nonempty_account_never_heartbeats(tmp_path, monkeypatch):
    _, _, _, beats = preflight_fixture(tmp_path, monkeypatch, nonempty=True)
    assert run_preflight() == 1 and beats == []


def test_preflight_redirected_input_never_loads_credentials(monkeypatch):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    monkeypatch.setattr('weather.market.re1_transport.load_owner_credentials', lambda _: pytest.fail('credentials'))
    with pytest.raises(RuntimeError, match='owner_terminal_required'):
        run_preflight()


def test_preflight_receipt_is_bound_to_terminal_and_newer_incomplete_attempt(tmp_path, monkeypatch):
    root, clock, _, _ = preflight_fixture(tmp_path, monkeypatch)
    assert run_preflight() == 0
    path = next(root.glob('preflight-*/preflight.json'))
    original = path.read_bytes()
    row = json.loads(original)
    row['timeouts_seconds']['balances'] = 999
    path.write_text(json.dumps(row))
    with pytest.raises(RuntimeError, match='preflight'):
        clean_preflight(root, now=clock.now(), commit='f' * 40)
    path.write_bytes(original)
    (root / 'preflight-99999999').mkdir()
    with pytest.raises((RuntimeError, ValueError, OSError)):
        clean_preflight(root, now=clock.now(), commit='f' * 40)


def test_owner_stream_configuration_and_readonly_heartbeat_guard(tmp_path, monkeypatch):
    from weather.market.re1_transport import OwnerVenue, PairStream
    from tests.market.stage2_fakes import CONDITION, TOKENS, MAKER
    fields = dict(FUNDER_ADDRESS=MAKER, API_KEY='fixture', API_SECRET='fixture', API_PASSPHRASE='fixture')
    client = SimpleNamespace(signer='0x' + 'c' * 40)
    venue = OwnerVenue(client, fields, SecretGuard(), condition=CONDITION, tokens=TOKENS,
                       directory=tmp_path, readonly=True, preflight=True)
    assert isinstance(venue.stream, PairStream) and venue.stream.inbound_silence_seconds > venue.stream.heartbeat_seconds
    calls = []
    venue.sender = SimpleNamespace(send=lambda: calls.append('beat') or {'status': 'ok'}, last_response={'heartbeat_id': 'one'})
    venue.open_orders = lambda: [{}]
    with pytest.raises(RuntimeError, match='empty_account'):
        venue.heartbeat()
    assert calls == []
    venue.open_orders = lambda: []
    assert venue.heartbeat() == {'status': 'ok'}
    for action in (lambda: venue.submit({}, checkpoint=lambda: None), lambda: venue.cancel('one'), venue.cancel_all):
        with pytest.raises(RuntimeError, match='read_only'): action()
