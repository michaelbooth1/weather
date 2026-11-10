"""Synthetic controls only; no captured books opened by these tests."""
import ast
import csv
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('t085_scan', Path(__file__).with_name('scan.py'))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


def parse(value):
    return list(scan.strict_rows(io.StringIO(value, newline='')))


def test_long_field_and_limit_restoration():
    prior = csv.field_size_limit()
    long_value = 'x' * 200000 + '\n"' + 'y' * 200000
    stream = io.StringIO(newline='')
    csv.writer(stream).writerows([['a', 'b'], ['123', long_value]])
    csv.field_size_limit(131072)
    try:
        with pytest.raises(csv.Error):
            list(csv.reader(io.StringIO(stream.getvalue()), strict=True))
        assert parse(stream.getvalue()) == [['a', 'b'], {'a': '123', 'b': long_value}]
        assert csv.field_size_limit() == 131072
    finally:
        csv.field_size_limit(prior)


@pytest.mark.parametrize('value,error', [
    ('a,b\nx,"unfinished\n', csv.Error),
    ('a,b\nx,"bad"tail\n', csv.Error),
    ('a,b\nx,y,z\n', ValueError),
    ('a,b\nx\n', ValueError),
    ('a,b\nx,"' + 'z' * scan.MAX_CSV_CHARS, ValueError),
    ('a,b\nx,"' + 'z' * 600000 + '\n' + 'z' * 600000 + '"\n', ValueError),
], ids=['unclosed-quote', 'quote-tail', 'extra-column', 'missing-column', 'record-cap', 'multiline-record-cap'])
def test_malformed_and_unbounded_records_refuse(value, error):
    before = csv.field_size_limit()
    with pytest.raises(error):
        parse(value)
    assert csv.field_size_limit() == before


def test_embargo_boundaries_and_row_guard(tmp_path):
    assert scan.date_slug('highest-temperature-in-toronto-on-september-29-2026')[0] == '2026-09-29'
    for day in ('september-30', 'october-14', 'october-15'):
        with pytest.raises(ValueError, match='EMBARGO'):
            scan.date_slug(f'highest-temperature-in-toronto-on-{day}-2026')
    # Reuse the valid synthetic header created by the original pipeline, and
    # prove a guarded event identity is refused by captures, before valuation.
    src = Path(r'C:\t\codex\T003\out\scan_stream_v4.py')
    tree = ast.parse(src.read_text(encoding='utf-8'))
    cap = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'captures')
    required = next(n.value for n in ast.walk(cap) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'required' for t in n.targets))
    fields = sorted(ast.literal_eval(required))
    path = tmp_path / 'bad-date.csv'
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fields)
        writer.writeheader()
        writer.writerow(dict.fromkeys(fields, '') | {
            'captured_at_utc': '2026-09-29T12:00:00+00:00',
            'event_slug': 'highest-temperature-in-toronto-on-september-30-2026',
        })
    with pytest.raises(ValueError, match='EMBARGO'):
        list(scan.captures(path))


def test_original_pipeline_controls(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, 'OUT', tmp_path)
    scan.selftest()


def test_economic_and_output_method_unchanged():
    original = Path(r'C:\t\codex\T003\out\scan_stream_v4.py')
    assert scan.sha(original) == scan.LEGACY_SHA
    before = ast.parse(original.read_text(encoding='utf-8'))
    after = ast.parse(Path(scan.__file__).read_text(encoding='utf-8'))
    # The modified entry points, bounds and IO are explicit; every original
    # valuation, route, output, aggregation and selftest definition is identical.
    modified = {'date_slug', 'load_plan', 'inventory', 'captures', 'main'}
    definitions = lambda tree: {n.name: ast.dump(n, include_attributes=False)
        for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    old, new = definitions(before), definitions(after)
    assert all(new[name] == node for name, node in old.items() if name not in modified)


def test_remaining_days_require_real_reproduction(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, 'OUT', tmp_path)
    with pytest.raises(FileNotFoundError):
        scan.require_reproduction()


def test_actual_inventory_schema_metadata_only():
    # This reads fixed metadata and stats permitted sources, never opens books.
    raw=json.loads((scan.LEGACY_OUT/'inventory.json').read_text(encoding='utf-8-sig'))
    assert len(raw)==900 and all('city' not in item for item in raw)
    plan=scan.load_plan()
    assert len(plan)==720
    assert all(set(item)=={'event','date','city','path','bytes'} for item in plan)
    assert all({k:v for k,v in item.items() if k!='city'}=={k:v for k,v in original.items() if k!='index'}
               for item,original in zip(plan,raw[:720]))
    assert len({scan.date_slug(item['event'])[1] for item in plan})==12
    assert plan[-1]['date']=='2026-09-29'
    # Assert the exact input-record shape T003 serialized, beyond just accepting
    # the raw inventory schema. Historical receipts only, no source book opens.
    for item in plan[:393]:
        old=json.loads((scan.LEGACY_OUT/'stream_events_v4'/(item['event']+'.json')).read_text(encoding='utf-8'))
        assert 'index' not in old
        assert item=={k:old[k] for k in item}


@pytest.mark.parametrize('utc,allowed',[
    ('2026-11-10T08:00:00+00:00',True),
    ('2026-11-10T13:30:00+00:00',False),
    ('2026-11-10T23:59:59+00:00',False),
    ('2026-11-11T00:00:00+00:00',True),
    ('2026-11-11T05:00:00+00:00',False),
])
def test_authorized_execution_windows(utc,allowed):
    now=datetime.fromisoformat(utc)
    if allowed:
        assert scan.execution_seconds(now)>0
    else:
        with pytest.raises(ValueError):scan.execution_seconds(now)
