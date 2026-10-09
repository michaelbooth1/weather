"""Mechanical panel exclusion of the campaign (signed pre-registration section 4), synthetic lines only.

Guards: exactly the signed line fields, every condition of the event, one line per market-local quote date the
session can rest on (to GTD expiry), per-line SHA-256 over the exact bytes, append-only with fail-closed reads, the
10-15 T+2 band-days dropped by condition and date, and the selector helper that splits panel rows.
"""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from weather.market.lfc_panel_exclusion import (EXCLUSION_FILE, FIELDS, append_exclusions, drop_excluded,
                                                excluded_band_days, excluded_conditions, exclusion_lines,
                                                load_panel_exclusions, local_quote_dates, main)

A, B = '0x' + 'a' * 64, '0x' + 'b' * 64
START = datetime(2026, 10, 15, 17, tzinfo=timezone.utc)
END = datetime(2026, 10, 15, 23, tzinfo=timezone.utc)
APPENDED = datetime(2026, 10, 15, 16, 59, tzinfo=timezone.utc)


def lines(tz='America/New_York', **kwargs):
    values = dict(event_slug='highest-temperature-in-nyc-on-october-17-2026', condition_ids=[B, A], session_id='S1',
                  start=START, end=END, timezone_name=tz, appended=APPENDED)
    values.update(kwargs)
    return exclusion_lines(**values)


def test_one_line_with_exactly_the_signed_fields_and_every_event_condition():
    [line] = lines()
    assert tuple(sorted(line)) == FIELDS == ('appended_utc', 'condition_ids', 'event_slug', 'local_quote_date',
                                             'session_id')
    assert line['condition_ids'] == [A, B] and line['local_quote_date'] == '2026-10-15'
    assert line['appended_utc'] == '2026-10-15T16:59:00+00:00'


def test_a_window_crossing_local_midnight_writes_one_line_per_date():
    # Seoul: 17:00Z on 10-15 is 02:00 on 10-16 local, so the session rests on local 10-16 only.
    assert [l['local_quote_date'] for l in lines('Asia/Seoul')] == ['2026-10-16']
    # A session ending 23:50Z + 60 s GTD reaches local 10-16 in Seoul from a 10-15 start at 14:00Z (23:00 local).
    assert local_quote_dates(datetime(2026, 10, 15, 14, tzinfo=timezone.utc),
                             datetime(2026, 10, 15, 20, tzinfo=timezone.utc), 'Asia/Seoul') == ['2026-10-15',
                                                                                                 '2026-10-16']


@pytest.mark.parametrize('field', ['event_slug', 'condition_ids', 'session_id'])
def test_incomplete_lines_refuse(field):
    with pytest.raises(ValueError, match='exclusion_incomplete'):
        lines(**{field: [] if field == 'condition_ids' else ''})


def test_append_returns_the_sha_of_each_exact_line_and_reads_back(tmp_path):
    first = append_exclusions(tmp_path, lines())
    second = append_exclusions(tmp_path, lines(session_id='S2'))
    raw = (tmp_path / EXCLUSION_FILE).read_bytes().splitlines(keepends=True)
    assert first + second == [hashlib.sha256(r).hexdigest() for r in raw]
    loaded = load_panel_exclusions(tmp_path / EXCLUSION_FILE)
    assert [l['session_id'] for l in loaded] == ['S1', 'S2']
    assert excluded_conditions(loaded) == {A, B}


@pytest.mark.parametrize('damage', [b'{"truncated":', b'\n', b'{"event_slug":"x"}\n', b'[]\n'])
def test_malformed_file_refuses_reads_and_appends(tmp_path, damage):
    path = tmp_path / EXCLUSION_FILE
    path.write_bytes(damage)
    with pytest.raises(ValueError):
        load_panel_exclusions(path)
    if not damage.endswith(b'\n'):
        with pytest.raises(ValueError, match='exclusion_file_truncated'):
            append_exclusions(tmp_path, lines())


def test_extra_field_refuses_the_append(tmp_path):
    bad = lines()
    bad[0]['note'] = 'x'
    with pytest.raises(ValueError, match='exclusion_fields'):
        append_exclusions(tmp_path, bad)
    assert not (tmp_path / EXCLUSION_FILE).exists()


def test_t_plus_2_band_days_of_10_15_are_dropped_by_condition_and_date():
    excluded = lines()
    assert excluded_band_days(excluded) == {(A, '2026-10-15'), (B, '2026-10-15')}
    rows = [{'condition_id': A.upper(), 'local_quote_date': '2026-10-15T00:00:00'},
            {'condition_id': A, 'local_quote_date': '2026-10-16'},
            {'condition_id': '0x' + 'c' * 64, 'local_quote_date': '2026-10-15'}]
    kept, dropped = drop_excluded(rows, excluded)
    assert dropped == rows[:1] and kept == rows[1:]


def test_cli_summarises_band_days(tmp_path, capsys):
    append_exclusions(tmp_path, lines())
    assert main(['--exclusions', str(tmp_path / EXCLUSION_FILE), '--output', str(tmp_path / 'out.json')]) == 0
    payload = json.loads((tmp_path / 'out.json').read_bytes())
    assert payload['lines'] == 1 and payload['band_days'] == [[A, '2026-10-15'], [B, '2026-10-15']]
    assert json.loads(capsys.readouterr().out)['band_days'] == 2
