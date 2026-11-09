"""Guards: B065 unread account evidence is UNKNOWN and never a clean watch row."""
import json

import pytest


@pytest.mark.parametrize('packet', [[], ['--wrapper-deadline-utc', 'bad', '--wrapper-policy-sha256', 'a' * 64]])
def test_unread_refusal_is_unknown_and_needs_attention_in_the_watch(tmp_path, monkeypatch, packet):
    from weather.market import lfc_campaign_cli as cli, lfc_pilot
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path / 'control')
    monkeypatch.setattr(cli, 'load_release', lambda *a: {})
    monkeypatch.setattr(cli, 'validate_release', lambda *a: None)
    monkeypatch.setattr(cli, 'account_lease', lambda *a: pytest.fail('unread refusal accessed the account'))
    original = lfc_pilot.notify_owner; notices = []
    def inert_notice(root, summary, **kwargs):
        row = original(root, summary, windows=False, printer=lambda *a, **k: None, **kwargs)
        notices.append(row); return row
    monkeypatch.setattr(lfc_pilot, 'notify_owner', inert_notice)
    assert cli.main(['tick', '--release', 'synthetic', '--release-sha256', 'a' * 64] + packet) == 0
    # This is the filename-sorted, status-only watch view, never the pilot root.
    row = json.loads(sorted((tmp_path / 'control').iterdir())[-1].read_text())
    assert row['orders_open_unproven'] is None and row['incident'] is None
    assert row['account_read'] is False and row['attention_required'] is True
    from weather.market.lfc_campaign_control import row_is_clean, needs_attention
    assert not row_is_clean(row) and needs_attention(row)
    assert len(notices) == 1 and 'account not read' in notices[0]['result_line']
    assert 'attention required' in notices[0]['result_line']
    assert 'orders_open_unproven' not in notices[0]['result_line']
