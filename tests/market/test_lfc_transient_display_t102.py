"""Guards: T102 all transient prechecks display DEFERRED, not a false incident."""
import json
import pytest

from weather.market.lfc_campaign import TransientPrecheck


@pytest.mark.parametrize('command', ['check', 'owner-close', 'owner-recover'])
@pytest.mark.parametrize('code', ['capital_cash_snapshot_pending', 'f2_anchor_snapshot_pending'])
def test_non_check_transient_never_manufactures_display_incident(tmp_path, monkeypatch, capsys, command, code):
    from weather.market import lfc_campaign_cli as cli
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path/'control')
    def unavailable(*args):
        raise TransientPrecheck(code)
    monkeypatch.setattr(cli, 'load_release', unavailable)
    args = [command, '--release', 'synthetic', '--release-sha256', 'a'*64]
    if command.startswith('owner-'):
        args += ['--incident', 'b'*32]
    assert cli.dispatch(args) == 1
    rows = [json.loads(p.read_text()) for p in (tmp_path/'control').glob('*.json')]
    assert len(rows) == 1 and rows[0]['phase'] == 'DEFERRED'
    assert rows[0]['incident'] is not True and rows[0]['attention_required'] is True
    assert rows[0]['reason'] == code
    assert json.loads(capsys.readouterr().out)['code'] == code


def test_transient_cannot_hide_an_already_latched_incident(tmp_path, monkeypatch):
    from weather.market import lfc_campaign_cli as cli
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path/'control')
    monkeypatch.setattr(cli, 'active_incidents', lambda *args, **kwargs: [{'attempt_id': 'b'*32}])
    def unavailable(*args):
        raise TransientPrecheck('capital_cash_snapshot_pending')
    monkeypatch.setattr(cli, 'load_release', unavailable)
    assert cli.dispatch(['owner-close', '--release', 'synthetic', '--release-sha256', 'a'*64,
                         '--incident', 'b'*32]) == 1
    row, = [json.loads(p.read_text()) for p in (tmp_path/'control').glob('*.json')]
    assert row['phase'] == 'INCIDENT' and row['incident'] is True


def test_unclassified_transient_text_is_not_published(tmp_path, monkeypatch, capsys):
    from weather.market import lfc_campaign_cli as cli
    monkeypatch.setattr(cli, 'CONTROL_ROOT', tmp_path/'control')
    def unavailable(*args):
        raise TransientPrecheck('private path or credential: NEVER-PUBLISH')
    monkeypatch.setattr(cli, 'load_release', unavailable)
    assert cli.dispatch(['owner-close', '--release', 'synthetic', '--release-sha256', 'a'*64,
                         '--incident', 'b'*32]) == 1
    row, = [json.loads(p.read_text()) for p in (tmp_path/'control').glob('*.json')]
    assert row['phase'] == 'DEFERRED' and row['reason'] == 'transport_deferred'
    assert 'NEVER-PUBLISH' not in json.dumps(row) + capsys.readouterr().out
