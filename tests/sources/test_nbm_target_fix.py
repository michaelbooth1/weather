"""83a regression controls from the pinned 82a station bytes; no outcomes."""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from weather.market.market_registry import all_specs
from weather.model.toronto_model import TorontoHighTempModel
from weather.sources.forecast_payload_fanout import MarketInvariantFetchFanout
from weather.sources.nbm_probabilistic_tmax import (
    NBM_NBP_PARSER_V1, NBM_NBP_PARSER_V2, NBM_NBP_STATION_TIMEZONES,
    NBPStationArchiveStore, nbp_target_cycle_candidates, parse_nbp_station_tmax,
    parse_nbp_station_tmax_v1, replay_nbp_shared_payload, replay_nbp_station_archive_row,
)

FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'nbm_target_fix'


@pytest.mark.parametrize('path', sorted(FIXTURES.glob('20260917T*.txt')), ids=lambda p: p.stem)
def test_real_blocks_reject_minima_and_preserve_maxima(path):
    text = path.read_text()
    station = path.stem.split('-')[1]
    hour = int(path.stem[9:11])
    old = parse_nbp_station_tmax_v1(text, station, '2026-09-17')
    new = parse_nbp_station_tmax(text, station, '2026-09-17')
    if hour < 12:
        assert new['available']
        assert new['percentiles'] == old['percentiles']
        assert new['period_kind'] == 'maximum'
        assert new['valid_time_utc'] == '2026-09-18T00:00:00+00:00'
    else:
        assert old['available']
        assert old['valid_time_utc'] == '2026-09-18T12:00:00+00:00'
        assert not new['available']
        assert new['reason'] == 'target_max_not_in_cycle'
    tomorrow = parse_nbp_station_tmax(text, station, '2026-09-18')
    assert tomorrow['available'] and tomorrow['period_kind'] == 'maximum'
    assert tomorrow['valid_time_utc'] == '2026-09-19T00:00:00+00:00'


@pytest.mark.parametrize('station', list(NBM_NBP_STATION_TIMEZONES))
@pytest.mark.parametrize('day', ['1/17/2026', '3/08/2026', '9/17/2026', '11/01/2026'])
def test_standard_daylight_and_transition_date_assignment(station, day):
    text = (FIXTURES / f'20260917T07Z-{station}.txt').read_text().replace('9/17/2026', day)
    target = datetime.strptime(day, '%m/%d/%Y').date()
    parsed = parse_nbp_station_tmax(text, station, target)
    assert parsed['available'] and parsed['target_date'] == target.isoformat()
    assert parsed['period_kind'] == 'maximum'


def test_supported_station_zone_mapping_matches_registry():
    assert NBM_NBP_STATION_TIMEZONES == {
        spec.icao: spec.timezone for spec in all_specs() if ':US' in spec.wu_history_id
    }


@pytest.mark.parametrize('code', ['TXNP1','TXNP2','TXNP5','TXNP7','TXNP9','TXNMN','TXNSD'])
def test_incomplete_rows_and_missing_sentinels_fail_closed(code):
    text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text()
    missing = '\n'.join(line for line in text.splitlines() if line[:6].strip() != code)
    assert parse_nbp_station_tmax_v1(missing, 'KLGA', '2026-09-17')['available']
    parsed = parse_nbp_station_tmax(missing, 'KLGA', '2026-09-17')
    assert not parsed['available'] and parsed['reason'] == 'target_max_incomplete_rows'
    assert parsed['value_rejection_reasons'][code] == 'missing_row_or_token'
    sentinel = '\n'.join(line[:6] + ' -99' + line[10:] if line[:6].strip() == code else line for line in text.splitlines())
    assert not parse_nbp_station_tmax(sentinel, 'KLGA', '2026-09-17')['available']


def test_unknown_station_and_parser_fail_closed():
    text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text().replace('KLGA', 'PGUM')
    assert parse_nbp_station_tmax(text, 'PGUM', '2026-09-17')['reason'] == 'station_max_date_ambiguous'
    with pytest.raises(ValueError, match='unsupported'):
        replay_nbp_shared_payload(text.encode(), {'station_id':'PGUM','target_date':'2026-09-17'}, parser_version='v99')


def test_archive_versions_and_repeat_captures_never_overwrite_old_bytes(tmp_path):
    text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text()
    store = NBPStationArchiveStore(tmp_path)
    old = store.write_payload(parse_nbp_station_tmax_v1(text, 'KLGA', '2026-09-17'))
    old_bytes = Path(old['raw_payload_path']).read_bytes()
    new_payload = parse_nbp_station_tmax(text, 'KLGA', '2026-09-17', fetched_at='2026-09-17T14:00:00Z')
    new = store.write_payload(new_payload)
    new_bytes = Path(new['raw_payload_path']).read_bytes()
    repeated = store.write_payload(parse_nbp_station_tmax(text, 'KLGA', '2026-09-17', fetched_at='2026-09-17T15:00:00Z'))
    assert repeated['written_row_count'] == 0
    assert Path(old['raw_payload_path']).read_bytes() == old_bytes
    assert Path(new['raw_payload_path']).read_bytes() == new_bytes
    assert new['raw_payload_path'] != old['raw_payload_path']
    assert replay_nbp_station_archive_row(old['row'])['status'] == 'PASS'
    assert replay_nbp_station_archive_row(new['row'])['status'] == 'PASS'


def test_versioned_shared_and_station_replay(tmp_path):
    text = (FIXTURES / '20260917T13Z-KLGA.txt').read_text()
    identity = {'station_id': 'KLGA', 'target_date': '2026-09-17'}
    old = parse_nbp_station_tmax_v1(text, **identity)
    assert old['percentiles']['50'] == 72.0
    assert replay_nbp_shared_payload(text.encode(), identity) == old
    assert replay_nbp_shared_payload(text.encode(), identity, parser_version=NBM_NBP_PARSER_V1) == old
    assert not replay_nbp_shared_payload(text.encode(), identity, parser_version=NBM_NBP_PARSER_V2)['available']
    old_row = NBPStationArchiveStore(tmp_path / 'v1').write_payload(old)
    assert replay_nbp_station_archive_row(old_row['row'])['status'] == 'PASS'
    altered = {**old_row['row'], 'parser_version': NBM_NBP_PARSER_V2}
    assert replay_nbp_station_archive_row(altered)['status'] == 'FAIL'
    maximum_text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text()
    new = parse_nbp_station_tmax(maximum_text, **identity, fetched_at='2026-09-17T14:00:00Z')
    assert replay_nbp_shared_payload(maximum_text.encode(), identity, fetched_at='2026-09-17T14:00:00Z', parser_version=2) == new
    new_row = NBPStationArchiveStore(tmp_path / 'v2').write_payload(new)
    assert replay_nbp_station_archive_row(new_row['row'])['status'] == 'PASS'
    altered = {**new_row['row'], 'parser_version': NBM_NBP_PARSER_V1}
    assert replay_nbp_station_archive_row(altered)['status'] == 'FAIL'
    raw_path = Path(new_row['raw_payload_path'])
    raw = json.loads(raw_path.read_text())
    raw['parser_version'] = 'unknown-version'
    raw_path.write_text(json.dumps(raw))
    assert 'parser_version_mismatch' in replay_nbp_station_archive_row(new_row['row'])['issues']


@pytest.mark.parametrize('hour', range(24))
def test_target_cycle_order_and_newest_tomorrow(hour):
    now = datetime(2026,9,17,hour,tzinfo=timezone.utc)
    today = nbp_target_cycle_candidates(now, date(2026,9,17))
    tomorrow = nbp_target_cycle_candidates(now, date(2026,9,18))
    assert today == sorted(today, reverse=True)
    assert today[0].hour == (7 if hour >= 7 else 1 if hour >= 1 else 0)
    assert tomorrow[0].hour == max(h for h in (0,1,7,12,13,19) if h <= hour)
    assert len(tomorrow) <= 7


def test_two_targets_and_two_stations_download_only_two_bulletins_in_pass(tmp_path):
    now = datetime(2026,9,17,20,tzinfo=timezone.utc)
    fanout = MarketInvariantFetchFanout(max_entries=2)
    urls = []
    def fetch(url):
        urls.append(url)
        hour = int(url[-3:-1])
        return '\n'.join((FIXTURES / f'20260917T{hour:02d}Z-{s}.txt').read_text() for s in ('KLGA','KLAX'))
    for market in ('nyc','los-angeles'):
        for target in ('2026-09-17','2026-09-18'):
            model = TorontoHighTempModel(target_date=target, market_id=market)
            model.market_invariant_fetch_fanout = fanout
            model.market_invariant_fetch_scope = '83a-pass'
            model.get_text = fetch
            cycles = [now.replace(hour=h) for h in (19,13,12,7,1,0)]
            with patch('weather.model.model_sources.nbp_cycle_candidates', return_value=cycles):
                result = model.fetch_nbm_probabilistic_tmax()
            assert result['available'] and result['period_kind'] == 'maximum'
    assert len(urls) == 2


def test_provenance_and_raw_values_survive_unchanged_floor():
    model = TorontoHighTempModel(target_date='2026-09-17', market_id='nyc')
    text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text()
    payload = parse_nbp_station_tmax(text, 'KLGA', '2026-09-17', fetched_at='2026-09-17T14:00:00Z')
    before = json.dumps(payload, sort_keys=True)
    features = model.us_guidance_features(nbm_probabilistic_tmax=payload, forecast_high=85., observed_floor_native=90.)
    assert features['nbm_prob_tmax_p50'] is None
    assert features['nbm_prob_tmax_parser_version'] == 2.
    assert features['nbm_prob_tmax_valid_hour_utc'] == 0.
    assert features['nbm_prob_tmax_cycle_age_hours'] == 7.
    assert features['nbm_prob_tmax_maximum_period_flag'] == 1.
    assert payload['raw_values']['TXNP5'] == 83.
    states = model.guidance_physical_states({'nbm_probabilistic_tmax': {'ok': True, 'data': payload}},
                                           observed_floor_native=90.)
    assert 'nbm_prob_tmax_p50' in states['nbm_probabilistic_tmax']['impossible_features']
    assert json.dumps(payload, sort_keys=True) == before
