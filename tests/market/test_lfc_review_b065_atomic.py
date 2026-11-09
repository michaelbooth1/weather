"""Guards: B065 fallback publication never exposes a partial control file."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_review_b063_watch import launcher


def test_mid_write_failure_leaves_no_partial_control_and_one_complete_refusal(tmp_path, monkeypatch):
    control = tmp_path / 'control'; module, _ = launcher(control, monkeypatch)
    original = Path.open
    @contextmanager
    def partial(path, mode='r', *args, **kwargs):
        with original(path, mode, *args, **kwargs) as stream:
            if mode == 'xb':
                def write(raw):
                    stream.write(raw[:19]); stream.flush()
                    raise OSError('synthetic_mid_write_failure')
                yield SimpleNamespace(write=write, flush=stream.flush, fileno=stream.fileno)
            else: yield stream
    monkeypatch.setattr(Path, 'open', partial)
    module.refusal_row('campaign_windowless_binding')
    assert not list(control.iterdir())
    records = list(tmp_path.rglob('*.jsonl'))
    assert len(records) == 1 and json.loads(records[0].read_text())['phase'] == 'REFUSED'
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows atomic no-replace rename contract')
def test_link_failure_publishes_the_complete_stage_with_one_atomic_rename(tmp_path, monkeypatch):
    control = tmp_path / 'control'; module, _ = launcher(control, monkeypatch)
    original = module.os.rename; calls = []
    def no_link(*args): raise OSError('synthetic_link_unavailable')
    def move(source, target):
        assert not target.exists() and json.loads(source.read_text())['phase'] == 'REFUSED'
        calls.append((source, target)); return original(source, target)
    monkeypatch.setattr(module.os, 'link', no_link)
    monkeypatch.setattr(module.os, 'rename', move)
    module.refusal_row('campaign_release_hash')
    assert len(calls) == 1
    assert len(list(control.iterdir())) == 1
    assert json.loads(next(control.iterdir()).read_text())['reason'] == 'campaign_release_hash'
