"""Guards: B064 a malformed parent packet never invents open-order uncertainty."""
import json

import pytest


@pytest.mark.parametrize('packet', [[], ['--wrapper-deadline-utc', 'bad', '--wrapper-policy-sha256', 'a' * 64]])
def test_malformed_envelope_says_account_not_read_in_both_row_and_toast(tmp_path, monkeypatch, packet):
    from weather.market import lfc_campaign_cli as cli, lfc_pilot
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    monkeypatch.setattr(cli, 'load_release', lambda *args: {})
    monkeypatch.setattr(cli, 'validate_release', lambda *args: None)
    monkeypatch.setattr(cli, 'account_lease', lambda *args: pytest.fail('malformed packet read the account'))
    original = lfc_pilot.notify_owner
    notices = []
    def inert_notice(root, summary, **kwargs):
        record = original(root, summary, windows=False, printer=lambda *a, **k: None, **kwargs)
        notices.append(record)
        return record
    monkeypatch.setattr(lfc_pilot, 'notify_owner', inert_notice)
    assert cli.main(['tick', '--release', 'inert-release', '--release-sha256', 'a' * 64] + packet) == 0
    rows = [json.loads(path.read_text()) for path in (tmp_path / 'control').glob('*.json')]
    assert len(rows) == len(notices) == 1
    assert rows[0]['phase'] == 'DEFERRED' and rows[0]['account_not_read'] is True
    assert rows[0]['orders_open_unproven'] is None and rows[0]['incident'] is None
    assert rows[0]['attention_required'] is True
    assert 'account not read' in notices[0]['result_line']
    assert 'orders_open_unproven=true' not in notices[0]['result_line']


@pytest.mark.parametrize('phase,unproven', [('INCIDENT', False), ('DEFERRED', True)])
def test_not_read_notice_cannot_hide_an_incident_or_unproved_orders(tmp_path, phase, unproven):
    from weather.market.lfc_campaign_control import control_record
    from weather.market.lfc_pilot import notify_owner
    from tests.market.test_lfc_campaign import Clock
    with pytest.raises(ValueError, match='control_account_read_context'):
        control_record(tmp_path, 'a' * 32, phase=phase, now=Clock().now(),
            account_not_read=True, orders_open_unproven=unproven)
    with pytest.raises(ValueError, match='notification_account_read_context'):
        notify_owner(tmp_path, {}, windows=False, public_status={'attempt_id': 'a' * 32,
            'phase': phase, 'account_not_read': True, 'orders_open_unproven': unproven})
    assert not list(tmp_path.iterdir())
