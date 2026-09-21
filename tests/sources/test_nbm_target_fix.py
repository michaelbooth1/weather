"""83a regression controls from the pinned 82a station bytes; no outcomes."""
import json
from datetime import date, datetime, timedelta, timezone
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


def test_feature_diagnostic_uses_current_age_without_rewriting_parser_provenance():
    model = TorontoHighTempModel(target_date='2026-09-17', market_id='nyc')
    text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text()
    payload = parse_nbp_station_tmax(text, 'KLGA', '2026-09-17', fetched_at='2026-09-17T08:00:00Z')
    payload['cycle_age_at_use_hours'] = 13.
    before = json.dumps(payload, sort_keys=True)
    features = model.us_guidance_features(nbm_probabilistic_tmax=payload, forecast_high=85.)
    assert features['nbm_prob_tmax_cycle_age_hours'] == 13.
    assert payload['raw_payload']['cycle_age_hours'] == 1.
    assert json.dumps(payload, sort_keys=True) == before


@pytest.mark.parametrize('fetched_at,reason', [
    ('2026-09-17T14:00:00', 'nbp_capture_time_naive'),
    ('2026-09-17T06:59:59Z', 'nbp_capture_time_before_issue'),
    ('bad-clock', 'nbp_capture_time_invalid'),
])
def test_bad_clock_is_retained_live_but_replay_raises(fetched_at, reason):
    text = (FIXTURES / '20260917T07Z-KLGA.txt').read_text()
    identity = {'station_id': 'KLGA', 'target_date': '2026-09-17'}
    with pytest.raises(ValueError, match=reason):
        replay_nbp_shared_payload(text.encode(), identity,
                                 fetched_at=fetched_at, parser_version=2)
    model = TorontoHighTempModel(target_date=identity['target_date'], market_id='nyc')
    model.market_invariant_fetch_fanout = MarketInvariantFetchFanout()
    # Supply the retained clock directly, as a fan-out receipt would.
    from weather.sources.forecast_payload_fanout import FanoutFetchResult
    from weather.sources.nbm_probabilistic_tmax import nbp_text_url, nbp_request_key, nbp_cycle_key
    cycle = datetime(2026, 9, 17, 7, tzinfo=timezone.utc)
    result = FanoutFetchResult({'text': text, 'fetched_at': fetched_at},
                              'nbm_probabilistic_tmax', nbp_request_key(nbp_text_url(cycle)),
                              nbp_cycle_key(cycle), True, False)
    with patch.object(model.market_invariant_fetch_fanout, 'fetch', return_value=result), \
         patch('weather.model.model_sources.nbp_cycle_candidates', return_value=[cycle]):
        payload = model.fetch_nbm_probabilistic_tmax()
    assert payload['available'] is False and payload['reason'] == reason
    assert payload['percentiles'] == {}
    assert payload['raw_values']['TXNP5'] == 83.
    assert payload['raw_payload']['text'] == text
    assert payload['parser_version'] == NBM_NBP_PARSER_V2
    assert payload['fetched_at'] == fetched_at
    assert payload['cycle_age_hours'] is None
    assert len(payload['tried_urls']) == 1


@pytest.mark.parametrize('hour,version,available', [(7, 2, True), (13, 2, False), (13, 1, True)])
def test_real_manifest_and_retained_bytes_derive_parser_decision(tmp_path, hour, version, available):
    from weather.collection.snapshot_store import SnapshotStore
    from weather.collection.forecast_payload_cas import SharedForecastPayloadCAS
    from weather.sources.nbm_probabilistic_tmax import nbp_text_url
    text = (FIXTURES / f'20260917T{hour:02d}Z-KLGA.txt').read_text()
    captured = datetime(2026, 9, 17, 20, tzinfo=timezone.utc)
    payload = parse_nbp_station_tmax(text, 'KLGA', '2026-09-17',
        source_url=nbp_text_url(captured.replace(hour=hour)),
        fetched_at=captured.isoformat(), parser_version=version)
    store = SnapshotStore(root=tmp_path / 'event', event_slug='fixture',
                          shared_forecast_payload_cas_root=tmp_path / 'cas')
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {'nbm_probabilistic_tmax': {'ok': True, 'data': payload, 'fetched_at': payload['fetched_at']}},
        'fixture', captured, 'fixture', config_identity={'market_id': 'nyc', 'target_date': '2026-09-17'})[0]
    retained = SharedForecastPayloadCAS(tmp_path / 'cas').read(row['payload_hash'], expected_bytes=row['payload_bytes'])
    replayed = replay_nbp_shared_payload(retained, json.loads(row['extraction_identity']),
        source_url=row['source_url'], fetched_at=row['fetched_at'], parser_version=row['parser_version'])
    assert replayed['available'] is available
    for key in ('period_kind', 'group_index', 'token_index', 'raw_values', 'percentiles', 'reason'):
        assert replayed.get(key) == payload.get(key)
    if version == 2 and available:
        assert len(replayed['raw_values']) == 7
        assert replayed['cycle_age_hours'] == 13.
    if version == 1:
        assert replayed['percentiles']['50'] == 72.
        assert replayed['valid_time_utc'] == '2026-09-18T12:00:00+00:00'


@pytest.mark.parametrize('zone', sorted(set(NBM_NBP_STATION_TIMEZONES.values())))
@pytest.mark.parametrize('day', [date(2026, 1, 17), date(2026, 9, 17)])
@pytest.mark.parametrize('hour', range(24))
def test_all_local_hours_have_reachable_cycle_and_404_fallback(zone, day, hour):
    from zoneinfo import ZoneInfo
    now = datetime.combine(day, datetime.min.time(), ZoneInfo(zone)).replace(hour=hour)
    cycles = nbp_target_cycle_candidates(now.astimezone(timezone.utc), day)
    assert cycles and 0 <= (now - cycles[0]).total_seconds() / 3600 <= 24
    assert cycles[0].date() == day
    if hour == 23 and zone == 'America/Los_Angeles' and day.month == 1:
        assert len(cycles) == 1  # 07Z is 24h old; a 404 leaves no older candidate.
    for cycle in cycles[:2]:
        # Candidate date/horizon is independently exercised with the real station rows above.
        first_max_day = cycle.date() + timedelta(days=int(cycle.hour >= 12))
        assert first_max_day <= day


def test_provenance_is_stored_but_excluded_from_training_and_source_reports():
    from weather.model.feature_store import (
        FEATURE_COLUMNS, FEATURE_DIAGNOSTIC_COLUMNS, FEATURE_AUDIT_COLUMNS,
        NATIVE_NAN_FEATURE_COLUMNS, build_live_feature_record, audit_row,
        empty_us_guidance_features,
    )
    from weather.sources.nbm_probabilistic_tmax import (
        NBM_PROB_TMAX_PROVENANCE_COLUMNS, NBM_PROB_TMAX_FEATURE_COLUMNS,
    )
    from weather.calibration.feature_model import feature_model_columns, late_day_feature_columns
    from weather.calibration.pooled_feature_assembly import feature_names_for_subset, FEATURE_SUBSET_CHOICES
    from weather.model.variant_prediction_runtime import feature_frame, band_feature_frame
    from weather.reporting.source_gates.nbm_probabilistic_tmax_gate import NBM_FEATURES
    from weather.reporting.source_gates.nbm_probabilistic_tmax_settlement_scoring import _artifact_payload
    provenance = dict(zip(NBM_PROB_TMAX_PROVENANCE_COLUMNS, [2., 0., 13., 1.]))
    keys = set(provenance)
    assert len(NBM_PROB_TMAX_FEATURE_COLUMNS) == 15
    assert keys <= set(FEATURE_DIAGNOSTIC_COLUMNS) <= set(FEATURE_AUDIT_COLUMNS)
    assert keys <= set(empty_us_guidance_features())
    record = build_live_feature_record('2026-09-17', 12, None, 'fixture', provenance)
    assert {key: audit_row({}, record)[key] for key in keys} == provenance
    selectors = [FEATURE_COLUMNS, NATIVE_NAN_FEATURE_COLUMNS, NBM_FEATURES,
                 _artifact_payload(0, {})['feature_names']]
    for spec in all_specs():
        selectors.extend(feature_model_columns([], [], market_spec=spec))
        selectors.append(late_day_feature_columns([], [], market_spec=spec))
    for builder in (feature_frame, band_feature_frame):
        columns = list(builder([{**record, 'market_id': 'nyc'}]).columns)
        selectors.append(columns)
        for subset in FEATURE_SUBSET_CHOICES:
            selectors.append(feature_names_for_subset(columns, subset))
    assert all(not keys.intersection(columns) for columns in selectors)
