"""Guards: missing money-postcheck flags cannot become a clean watch result."""
import json
from datetime import datetime, timezone
import pytest
from weather.market import lfc_campaign_control as control

NOW = datetime(2026, 11, 9, 14, tzinfo=timezone.utc)


@pytest.mark.parametrize('phase', ['IDLE', 'COMPLETE', 'RUNNING'])
@pytest.mark.parametrize('field', ['postchecks_pending', 'incident', 'orders_open_unproven', 'attention_required'])
@pytest.mark.parametrize('missing', [False, True])
def test_every_unknown_completion_flag_stays_attention(tmp_path, monkeypatch, capsys, phase, field, missing):
    live = phase == 'RUNNING'
    row = control.control_record(tmp_path, 'a'*32, phase=phase, now=NOW,
        orders_open_unproven=live, orders_live=live)
    if missing: row.pop(field)
    else: row[field] = None
    next(tmp_path.glob('*.json')).write_text(json.dumps(row))
    monkeypatch.setattr(control, 'utc_now', lambda: NOW)
    code = control.main(['--root', str(tmp_path)])
    actual = json.loads(capsys.readouterr().out)
    assert code == 1 and actual['attention_required'] is True and not actual['clean'], actual
