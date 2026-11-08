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


def test_interrupted_owner_close_can_finish_for_proved_terminal_orders(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_ledger import Ledger
    runtime, claim, incident, _ = owner_runtime(tmp_path, monkeypatch)
    ordinary = Ledger.record
    def crash(self, event, **fields):
        if event == 'autostart_owner_close':
            raise OSError('synthetic crash after owner closure receipt before ledger anchor')
        return ordinary(self, event, **fields)
    with monkeypatch.context() as m:
        m.setattr(Ledger, 'record', crash)
        with pytest.raises(OSError):
            owner_close(runtime, incident)
    assert not runtime.state.ledger.unacknowledged_intents()
    assert not runtime.state.ledger.unresolved_legs()
    assert (runtime.state.root / 'owner-closures' / (incident + '.json')).exists()
    assert not any(row['event'] == 'autostart_owner_close' for row in runtime.state.ledger.rows)
    from weather.market.lfc_campaign_state import StateRefused
    with pytest.raises(StateRefused, match='incident_closure_invalid'):
        runtime.state.incidents()
    assert owner_close(runtime, incident) == 0
    assert not runtime.state.pending() and not runtime.state.incidents()


@pytest.mark.parametrize('change', ['reboot', 'new_artifact', 'foreign_head', 'other_incident', 'changed_read'])
def test_partial_owner_close_is_one_bound_decision_not_a_future_waiver(tmp_path, monkeypatch, change):
    from tests.market.test_lfc_campaign_recovery import owner_runtime
    from weather.market.lfc_campaign_owner_close import owner_close
    from weather.market.lfc_campaign_state import StateRefused
    from weather.market.lfc_ledger import Ledger
    runtime, claim, incident, directory = owner_runtime(tmp_path, monkeypatch)
    ordinary = Ledger.record
    def crash(self, event, **fields):
        if event == 'autostart_owner_close': raise OSError('interrupted')
        return ordinary(self, event, **fields)
    with monkeypatch.context() as patch:
        patch.setattr(Ledger, 'record', crash)
        with pytest.raises(OSError): owner_close(runtime, incident)
    path = runtime.state.root / 'owner-closures' / (incident + '.json')
    row = runtime.state.read(path)
    if change == 'new_artifact':
        (directory / 'journal.jsonl').write_text('new fragment')
    elif change == 'foreign_head': row['ledger_head_sha256'] = 'f' * 64
    elif change == 'other_incident': row['incident_id'] = 'f' * 32
    elif change == 'changed_read': row['account_read']['open_orders'] = [{'id': 'foreign'}]
    else:
        runtime.reload_ledger()
    if change not in ('reboot', 'new_artifact'): path.write_text(json.dumps(row))
    original = file_sha(path)
    if change == 'reboot':
        assert owner_close(runtime, incident) == 0
        assert not runtime.state.incidents() and not runtime.state.pending()
        assert claim['local_date'] in runtime.state.consumed_dates()
    else:
        with pytest.raises(StateRefused, match='owner_close_partial_binding'): owner_close(runtime, incident)
        assert not any(r['event'] == 'autostart_owner_close' for r in runtime.state.ledger.rows)
    assert file_sha(path) == original

