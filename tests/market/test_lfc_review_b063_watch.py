"""Guards: B063 timestamp-sorted no-file watch remains compatible with refusals."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import re
from types import SimpleNamespace

import pytest

from weather.paths import REPO_ROOT
from weather.market.lfc_campaign_control import control_record


def launcher(tmp_path, monkeypatch):
    spec=importlib.util.spec_from_file_location('b063_windowless',REPO_ROOT/'scripts/ops/lfc_campaign_windowless.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    now=datetime(2026,11,11,14,tzinfo=timezone.utc)
    class Fixed(datetime):
        @classmethod
        def now(cls,tz=None): return now
    monkeypatch.setattr(module,'datetime',Fixed)
    monkeypatch.setattr(module,'STATUS_ROOT',tmp_path)
    return module,now


def test_old_refusal_cannot_sort_after_a_later_control_record(tmp_path,monkeypatch):
    module,now=launcher(tmp_path,monkeypatch)
    module.refusal_row('campaign_import_environment')
    control_record(tmp_path,'a'*32,phase='IDLE',now=now+timedelta(seconds=1),reason='idle')
    latest=sorted(tmp_path.iterdir(),key=lambda p:p.name)[-1]
    assert json.loads(latest.read_text())['phase']=='IDLE'
    refusal=next(p for p in tmp_path.iterdir() if 'launcher-refusals' in p.name)
    assert re.match(r'^\d{8}T\d{12}Z-launcher-refusals-',refusal.name)


def test_repeated_refusals_are_individually_parseable_even_in_one_clock_tick(tmp_path,monkeypatch):
    module,now=launcher(tmp_path,monkeypatch)
    monkeypatch.setenv('PYTHONPATH','never-record-this-fixture-value')
    module.refusal_row('campaign_import_environment')
    module.refusal_row('campaign_import_environment')
    paths=list(tmp_path.iterdir())
    assert len(paths)==2
    for path in paths:
        text=path.read_text()
        row=json.loads(text)
        assert len(text.splitlines())==1 and row['state']=='REFUSED'
        assert 'never-record-this-fixture-value' not in text and str(tmp_path) not in text
        assert 'PYTHONPATH' in row['variable_names']


def test_latest_refusal_exposes_watch_phase_and_utc_without_private_data(tmp_path,monkeypatch):
    module,now=launcher(tmp_path,monkeypatch)
    control_record(tmp_path,'a'*32,phase='IDLE',now=now-timedelta(seconds=1),reason='idle')
    module.refusal_row('campaign_import_environment')
    row=json.loads(sorted(tmp_path.iterdir(),key=lambda p:p.name)[-1].read_text())
    assert row['phase']=='REFUSED' and row['at_utc']==now.isoformat()


def test_refusal_publication_is_atomic_and_preserves_an_existing_name(tmp_path,monkeypatch):
    module,now=launcher(tmp_path,monkeypatch)
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex='a'*32))
    link=module.os.link
    observed=[]
    def publish(source,target):
        assert source.parent==tmp_path.parent and source.parent!=tmp_path
        observed.append(json.loads(source.read_text()))
        return link(source,target)
    monkeypatch.setattr(module.os,'link',publish)
    module.refusal_row('campaign_import_environment')
    final=next(tmp_path.iterdir()); original=final.read_bytes()
    module.refusal_row('campaign_windowless_refused')
    assert final.read_bytes()==original and len(list(tmp_path.iterdir()))==1
    assert len(observed)==2
    fallback=tmp_path.parent/'launcher-refusals-fallback.jsonl'
    assert json.loads(fallback.read_text().splitlines()[-1])['reason']=='campaign_windowless_refused'
    assert not (tmp_path.parent/('.'+final.name+'.tmp')).exists()


def test_preexisting_temporary_file_is_never_removed(tmp_path,monkeypatch):
    module,now=launcher(tmp_path,monkeypatch)
    monkeypatch.setattr(module.uuid,'uuid4',lambda:SimpleNamespace(hex='b'*32))
    name=now.strftime('%Y%m%dT%H%M%S%fZ')+'-launcher-refusals-'+now.date().isoformat()+'-'+'b'*32+'.jsonl'
    temporary=tmp_path.parent/('.'+name+'.tmp')
    temporary.write_bytes(b'pre-existing synthetic evidence')
    module.refusal_row('campaign_import_environment')
    assert temporary.read_bytes()==b'pre-existing synthetic evidence'
    assert len(list(tmp_path.iterdir()))==1
    assert json.loads(next(tmp_path.iterdir()).read_text())['phase']=='REFUSED'
