"""Guards: B068 freshness and normal live-order watch exit codes."""
from datetime import datetime, timedelta, timezone
import json
import pytest

from weather.market import lfc_campaign_control as control

NOW = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize('phase,age,incident,live,expected', [
    ('IDLE', 0, False, False, 0), ('IDLE', 899, False, False, 0),
    ('IDLE', 900, False, False, 1), ('IDLE', 901, False, False, 1),
    ('RUNNING', 0, False, True, 2), ('RUNNING', 0, True, True, 1),
    ('RUNNING', 900, False, True, 1),
])
def test_watch_freshness_and_live_orders(tmp_path, monkeypatch, capsys, phase, age, incident, live, expected):
    row = control.control_record(tmp_path, 'a'*32, phase=phase, now=NOW-timedelta(seconds=age),
        incident=incident, orders_open_unproven=live, **({'orders_live': True} if live else {}))
    monkeypatch.setattr(control, 'utc_now', lambda: NOW, raising=False)
    assert control.main(['--root', str(tmp_path)]) == expected
    result = json.loads(capsys.readouterr().out)
    assert result['age_seconds'] == age
    if age >= 900:
        assert result['reason'] == 'stale_control_row' and result['attention_required'] is True
    elif live and not incident:
        assert result['watch_state'] == 'live_orders' and result['attention_required'] is False
    assert result['clean'] is (expected == 0)
    assert control.row_is_clean(row, now=NOW) is (expected == 0)
    assert control.public_status(row, now=NOW)['attention_required'] is (expected == 1)


@pytest.mark.parametrize('field', ['incident', 'orders_open_unproven', 'attention_required', 'at_utc'])
@pytest.mark.parametrize('value', [None, 'missing'])
def test_watch_unknown_fields_are_never_clean(tmp_path, monkeypatch, field, value):
    row = control.control_record(tmp_path, 'a'*32, phase='IDLE', now=NOW)
    path = next(tmp_path.glob('*.json'))
    if value == 'missing': row.pop(field)
    else: row[field] = value
    path.write_text(json.dumps(row))
    monkeypatch.setattr(control, 'utc_now', lambda: NOW, raising=False)
    assert control.main(['--root', str(tmp_path)]) == 1


def test_watch_age_is_configurable(tmp_path, monkeypatch):
    control.control_record(tmp_path, 'a'*32, phase='IDLE', now=NOW-timedelta(seconds=900))
    monkeypatch.setattr(control, 'utc_now', lambda: NOW, raising=False)
    assert control.main(['--root', str(tmp_path), '--max-row-age-seconds', '901']) == 0


def test_unproven_running_is_not_proven_live(tmp_path, monkeypatch):
    control.control_record(tmp_path, 'a'*32, phase='RUNNING', now=NOW, orders_open_unproven=True)
    monkeypatch.setattr(control, 'utc_now', lambda: NOW, raising=False)
    assert control.main(['--root', str(tmp_path)]) == 1


@pytest.mark.parametrize('stamp', [None, 'invalid', '2026-11-09T10:00:00', '2026-11-09T10:00:01+00:00'])
def test_watch_bad_or_future_time_is_unknown(tmp_path, monkeypatch, stamp):
    row = control.control_record(tmp_path, 'a'*32, phase='IDLE', now=NOW)
    row['at_utc'] = stamp
    next(tmp_path.glob('*.json')).write_text(json.dumps(row))
    monkeypatch.setattr(control, 'utc_now', lambda: NOW)
    assert control.main(['--root', str(tmp_path)]) == 1


def test_normal_live_toast_is_not_an_attention_alarm(tmp_path, monkeypatch):
    from weather.market.lfc_pilot import notify_owner
    monkeypatch.setattr(control, 'utc_now', lambda: NOW)
    row = control.control_record(tmp_path/'control', 'a'*32, phase='RUNNING', now=NOW,
        orders_open_unproven=True, orders_live=True)
    notice = notify_owner(tmp_path, {}, windows=False, printer=lambda *a, **k: None,
                          public_status=control.public_status(row))
    assert 'attention required' not in notice['result_line']
    assert 'live_orders (normal)' in notice['result_line']


def test_notice_timestamp_changes_do_not_repeat_a_stable_incident(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from weather.market import lfc_pilot
    from weather.market.lfc_campaign_visibility import notify_control
    notices = []
    monkeypatch.setattr(lfc_pilot, 'notify_owner', lambda *a, **k: notices.append(k))
    clock = SimpleNamespace(now=lambda: NOW)
    runtime = SimpleNamespace(clock=clock, control_root=tmp_path)
    first = control.control_record(tmp_path, 'a'*32, phase='INCIDENT', now=NOW, incident=True)
    notify_control(runtime, first)
    clock.now = lambda: NOW+timedelta(minutes=5)
    later = control.control_record(tmp_path, 'a'*32, phase='INCIDENT', now=clock.now(), incident=True)
    notify_control(runtime, later)
    assert len(notices) == 1


def test_malformed_control_values_are_unknown_and_not_echoed(monkeypatch):
    monkeypatch.setattr(control, 'utc_now', lambda: NOW)
    row = {'at_utc': 'private-value', 'attempt_id': 'private-value', 'phase': 'private-value',
           'incident': 'private-value', 'orders_open_unproven': 'private-value', 'attention_required': False}
    result, code = control.watch_status(row)
    assert code == 1 and 'private-value' not in json.dumps(result)
