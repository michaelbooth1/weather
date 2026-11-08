"""Independent T044 desired-behavior witnesses. Guards: retained campaign evidence.

All inputs are synthetic. No account, venue, credential, reader or Scheduler call.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_f2_capital import ledger_at, install, filled
from tests.market.test_lfc_f2_revision import setup
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook, record_activity
from weather.market.lfc_f2_economics import measured
from weather.market.lfc_f2_final import snapshot
from weather.market.lfc_f2_freeze import capture, verify
from weather.market.lfc_recording_io import file_sha


@pytest.fixture(autouse=True)
def account_guard():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def test_freeze_partial_receipt_recovers_on_next_healthy_tick_in_window(tmp_path, monkeypatch):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    state, clock, policy = setup(tmp_path, now)
    ordinary = state.ledger.record
    def crash(event, **fields):
        if event == 'autostart_freeze':
            raise OSError('synthetic crash after receipt fsync before ledger anchor')
        return ordinary(event, **fields)
    with monkeypatch.context() as m:
        m.setattr(state.ledger, 'record', crash)
        with pytest.raises(OSError):
            capture(state, policy, now)
    path = state.root / 'policies' / 'freeze.json'
    original = file_sha(path)
    assert verify(state) is None and path.exists()
    clock.seconds = 300
    capture(state, policy, clock.now())
    assert file_sha(path) == original  # The original remains evidence.
    frozen = verify(state)
    assert frozen is not None and frozen['on_time'], 'confirmation becomes successor_learning despite another healthy tick inside the window'


@pytest.mark.parametrize('case', ['intervening_row', 'late', 'changed_economics', 'foreign_head'])
def test_partial_freeze_recovery_preserves_binding_and_window(tmp_path, monkeypatch, case):
    now = datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
    state, clock, policy = setup(tmp_path, now)
    ordinary = state.ledger.record
    with monkeypatch.context() as patch:
        patch.setattr(state.ledger, 'record', lambda *a, **k: (_ for _ in ()).throw(OSError('interrupted')))
        with pytest.raises(OSError): capture(state, policy, now)
    path = state.root / 'policies' / 'freeze.json'
    if case == 'intervening_row':
        ordinary('session_start', session_id='unposted', counted=False)
    elif case == 'late':
        clock.seconds = 86400
    elif case == 'changed_economics':
        policy = parse_policy({**policy.raw, 'policy_revision': policy.raw['policy_revision'] + 1, 'tokens': ['YES']})
    else:
        row = state.read(path)
        row['ledger_sha256'] = 'f' * 64
        path.write_text(json.dumps(row))
    original = file_sha(path)
    capture(state, policy, clock.now())
    assert file_sha(path) == original
    assert (verify(state) is not None) == (case == 'intervening_row')


