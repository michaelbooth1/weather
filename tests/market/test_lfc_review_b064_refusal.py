"""Guards: B064 launcher publication failures retain a complete safe refusal."""
import json

import pytest

from tests.market.test_lfc_review_b063_watch import launcher


@pytest.mark.parametrize('direct_write_fails', [False, True])
def test_link_failure_retains_one_complete_refusal_with_a_fixed_fallback(tmp_path, monkeypatch, direct_write_fails):
    control = tmp_path / 'control'
    module, _ = launcher(control, monkeypatch)
    monkeypatch.setenv('PYTHONPATH', 'NEVER_LOG_THIS_VALUE')
    def no_link(*args): raise OSError('synthetic_link_unavailable')
    monkeypatch.setattr(module.os, 'link', no_link)
    original_move = module.os.rename
    if direct_write_fails:
        def limited_move(source, target):
            if target.parent == control: raise PermissionError('synthetic_control_unwritable')
            return original_move(source, target)
        monkeypatch.setattr(module.os, 'rename', limited_move)
    module.refusal_row('campaign_windowless_environment')
    files = list(tmp_path.rglob('*.jsonl'))
    assert len(files) == 1
    row = json.loads(files[0].read_text())
    assert row['phase'] == 'REFUSED' and row['variable_names'] == ['PYTHONPATH']
    assert len(files[0].read_text().splitlines()) == 1
    assert 'NEVER_LOG_THIS_VALUE' not in files[0].read_text()
    fallback = direct_write_fails or module.os.name != 'nt'
    assert files[0].parent == (tmp_path if fallback else control)
    if fallback: assert files[0].name == 'launcher-refusals-fallback.jsonl'
    assert not list(tmp_path.glob('.*.tmp'))


def test_fixed_fallback_preserves_prior_refusals(tmp_path, monkeypatch):
    control = tmp_path / 'control'; module, _ = launcher(control, monkeypatch)
    def no_link(*args): raise OSError('synthetic_link_unavailable')
    monkeypatch.setattr(module.os, 'link', no_link)
    def limited_move(*args): raise PermissionError('synthetic_control_unwritable')
    monkeypatch.setattr(module.os, 'rename', limited_move)
    module.refusal_row('campaign_release_hash')
    module.refusal_row('campaign_windowless_binding')
    path = tmp_path / 'launcher-refusals-fallback.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row['reason'] for row in rows] == ['campaign_release_hash', 'campaign_windowless_binding']
