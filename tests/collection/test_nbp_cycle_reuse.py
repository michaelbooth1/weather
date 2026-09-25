"""Complete national-cycle reuse: fixture-only, no external requests or outcomes."""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from weather.collection.forecast_payload_fetch_fanout import (
    CrossProcessMarketInvariantFetchFanout, _complete_nbp, _nbp_reuse_stations,
)
from weather.collection.forecast_payload_cas import forecast_payload_byte_summary
from weather.collection.snapshot_store import SnapshotStore
from weather.model.toronto_model import TorontoHighTempModel
from weather.sources.nbm_probabilistic_tmax import nbp_text_url, nbp_request_key, nbp_cycle_key

TEXT = (Path(__file__).parents[1] / 'fixtures/nbp_reuse_complete_20260917T07Z.txt').read_text()
CYCLE = datetime(2026, 9, 17, 7, tzinfo=timezone.utc)
URL = nbp_text_url(CYCLE)
KEY = dict(source='nbm_probabilistic_tmax', request_key=nbp_request_key(URL), cycle_key=nbp_cycle_key(CYCLE))
VALUE = dict(text=TEXT, fetched_at='2026-09-17T07:30:00+00:00',
             request_started_at='2026-09-17T07:29:59+00:00', response_received_at='2026-09-17T07:30:00+00:00')


def fetch(root, callback, scope, *, reuse=True):
    coordinator = CrossProcessMarketInvariantFetchFanout(root, wait_timeout_seconds=0.)
    method = coordinator.fetch_reusable_nbp if reuse else coordinator.fetch
    return method(**KEY, scope_key=scope, fetch_fn=callback)


def test_fixture_probe_independent_passes_and_markets(tmp_path):
    measurements = []
    for reuse, expected in [(False, 33), (True, 1)]:
        calls = []
        for pass_number in range(3):
            for station in _nbp_reuse_stations():
                # Each market is due in a different process/supervisor iteration.
                result = fetch(tmp_path / str(reuse), lambda: calls.append(1) or dict(VALUE),
                               f'pass-{pass_number}-{station}', reuse=reuse)
                assert result.value == VALUE
                if reuse and len(calls) == 1 and (pass_number or station != _nbp_reuse_stations()[0]):
                    assert result.reused and not result.fetched
                    assert result.coordinator_network_fetch_count == 0
        assert len(calls) == expected
        measurements.append({'reuse': reuse, 'passes': 3, 'markets': len(_nbp_reuse_stations()),
                             'downloads': len(calls), 'bulletin_bytes': len(TEXT.encode())})
    print('NBP_FETCH_PROBE=' + json.dumps(measurements))


@pytest.mark.parametrize('defect', ['station', 'txn', 'terminal', 'truncated', 'cycle', 'duplicate'])
def test_incomplete_first_fetch_is_not_indexed_and_next_pass_downloads(tmp_path, defect):
    text = TEXT
    if defect == 'station':
        text = text.replace('KLGA', 'XXXX')
    elif defect == 'cycle':
        text = text.replace('0700 UTC', '0100 UTC', 1)
    elif defect == 'duplicate':
        text += '\n' + TEXT
    elif defect == 'truncated':
        line = next(line for line in text.splitlines() if line[:6].strip() == 'SLPP9')
        text = text.replace(line, line[:-2], 1)
    else:
        code = 'TXNP5' if defect == 'txn' else 'SLPP9'
        line = next(line for line in text.splitlines() if line[:6].strip() == code)
        text = text.replace(line, '', 1)
    if defect == 'cycle':
        assert not _complete_nbp(text, KEY['cycle_key'], _nbp_reuse_stations())
        return
    assert not _complete_nbp(text, KEY['cycle_key'], _nbp_reuse_stations())
    calls = []
    fetch(tmp_path, lambda: calls.append(1) or {**VALUE, 'text': text}, 'first')
    assert not list(tmp_path.glob('nbp_cycle_index/*/*.json'))
    result = fetch(tmp_path, lambda: calls.append(1) or dict(VALUE), 'second')
    assert result.fetched and len(calls) == 2
    assert list(tmp_path.glob('nbp_cycle_index/*/*.json'))


@pytest.mark.parametrize('defect', ['json', 'missing_blob', 'hash', 'identity', 'missing_receipt',
                                   'naive_clock', 'future_clock', 'pre_issue_clock'])
def test_bad_index_or_blob_falls_back_to_download(tmp_path, defect):
    first = fetch(tmp_path, lambda: dict(VALUE), 'first')
    index = next(tmp_path.glob('nbp_cycle_index/*/*.json'))
    receipt = json.loads(index.read_text())
    blob = tmp_path / first.prepublished_payload_ref
    if defect == 'json':
        index.write_text('{')
    elif defect == 'missing_blob':
        blob.unlink()
    elif defect == 'hash':
        blob.write_bytes(b'corrupt')
    elif defect == 'missing_receipt':
        (tmp_path / first.coordinator_receipt_ref).unlink()
    elif defect == 'identity':
        receipt['request_key'] = 'invalid'
        index.write_text(json.dumps(receipt))
    else:
        bad_time = {'naive_clock': '2026-09-17T07:30:00',
                    'future_clock': '9999-09-17T07:30:00+00:00',
                    'pre_issue_clock': '2026-09-17T06:30:00+00:00'}[defect]
        original_path = tmp_path / first.coordinator_receipt_ref
        original = json.loads(original_path.read_text())
        original['fetched_at'] = receipt['fetched_at'] = bad_time
        original_path.write_text(json.dumps(original))
        index.write_text(json.dumps(receipt))
    calls = []
    result = fetch(tmp_path, lambda: calls.append(1) or dict(VALUE), 'second')
    assert result.fetched and not result.reused and calls == [1]
    assert result.value == VALUE


def test_index_write_error_does_not_repeat_successful_download(tmp_path):
    from weather.collection import forecast_payload_fetch_fanout as module
    original = module._write_immutable_json
    def write(root, path, payload):
        if 'nbp_cycle_index' in path.parts:
            raise OSError('index unavailable')
        return original(root, path, payload)
    calls = []
    with patch.object(module, '_write_immutable_json', side_effect=write):
        result = fetch(tmp_path, lambda: calls.append(1) or dict(VALUE), 'first')
    assert result.fetched and calls == [1]


def test_bad_first_clock_does_not_poison_index_for_later_valid_capture(tmp_path):
    fetch(tmp_path, lambda: {**VALUE, 'fetched_at': '2026-09-17T07:30:00'}, 'bad-clock')
    assert not list(tmp_path.glob('nbp_cycle_index/*/*.json'))
    calls = []
    fetch(tmp_path, lambda: calls.append(1) or dict(VALUE), 'good-clock')
    assert calls == [1] and list(tmp_path.glob('nbp_cycle_index/*/*.json'))


@pytest.mark.parametrize('status', [403, 404])
def test_unpublished_cycle_retried_next_pass(tmp_path, status):
    calls = []
    def missing():
        calls.append(1)
        response = requests.Response()
        response.status_code = status
        raise requests.HTTPError('not published', response=response)
    for scope in ['first', 'first', 'second']:
        with pytest.raises(requests.HTTPError):
            fetch(tmp_path, missing, scope)
    assert len(calls) == 2
    assert not list(tmp_path.glob('nbp_cycle_index/*/*.json'))


def test_claim_timeout_keeps_existing_bound_and_downloads(tmp_path):
    coordinator = CrossProcessMarketInvariantFetchFanout(tmp_path, wait_timeout_seconds=0.)
    _, claim = coordinator._paths(**KEY, scope_key='busy')
    token = coordinator._try_claim(tmp_path, claim, KEY)
    try:
        result = coordinator.fetch_reusable_nbp(**KEY, scope_key='busy', fetch_fn=lambda: dict(VALUE))
        assert result.fetched and result.wait_timed_out
        assert not list(tmp_path.glob('nbp_cycle_index/*/*.json'))
    finally:
        coordinator._release_claim(tmp_path, claim, token)


def test_new_cycle_is_a_new_download(tmp_path):
    fetch(tmp_path, lambda: dict(VALUE), 'first')
    cycle = CYCLE.replace(hour=19)
    calls = []
    result = CrossProcessMarketInvariantFetchFanout(tmp_path).fetch_reusable_nbp(
        source=KEY['source'], request_key=nbp_request_key(nbp_text_url(cycle)), cycle_key=nbp_cycle_key(cycle),
        scope_key='second', fetch_fn=lambda: calls.append(1) or {**VALUE,
            'text': TEXT.replace('0700 UTC', '1900 UTC'), 'fetched_at': '2026-09-17T20:00:00+00:00'})
    assert result.fetched and calls == [1]


def test_reuse_is_registered_only_for_nbp(tmp_path):
    with pytest.raises(ValueError, match='only for NBM'):
        CrossProcessMarketInvariantFetchFanout(tmp_path).fetch_reusable_nbp(
            **{**KEY, 'source': 'other'}, scope_key='pass',
            fetch_fn=lambda: pytest.fail('unregistered source must not fetch'))


def test_real_live_writer_truthful_attribution_and_age_at_use(tmp_path):
    # Warm from an earlier process with a known original timestamp.
    fetch(tmp_path / 'cas', lambda: dict(VALUE), 'original')
    model = TorontoHighTempModel(target_date='2026-09-17', market_id='nyc')
    model.market_invariant_fetch_fanout = CrossProcessMarketInvariantFetchFanout(tmp_path / 'cas')
    model.market_invariant_fetch_scope = 'later-pass'
    model.get_text = lambda url: pytest.fail('indexed complete cycle must not download')
    with patch('weather.model.model_sources.nbp_cycle_candidates', return_value=[CYCLE]):
        payload = model.fetch_nbm_probabilistic_tmax()
    assert payload['fetched_at'] == VALUE['fetched_at']
    assert payload['cycle_age_at_use_hours'] > .5
    captured = datetime.now(timezone.utc)
    store = SnapshotStore(root=tmp_path / 'event', event_slug='fixture',
                          shared_forecast_payload_cas_root=tmp_path / 'cas')
    store.root.mkdir()
    rows = store.write_forecast_payloads({KEY['source']: {'ok': True, 'data': payload,
        'fetched_at': captured.isoformat()}}, 'fixture', captured, 'fixture',
        config_identity={'market_id': 'nyc', 'target_date': '2026-09-17'})
    row = rows[0]
    assert row['single_fetch_reused'] and not row['single_fetch_fetched']
    assert row['single_fetch_scope'] == 'later-pass'
    assert row['fetched_at'] == VALUE['fetched_at']
    assert row['response_received_at'] == VALUE['response_received_at']
    assert row['captured_at_utc'] != row['fetched_at']
    assert 'cycle_age_at_use_hours' not in payload['raw_payload']
    summary = forecast_payload_byte_summary(rows)
    assert summary['network_fetch_count'] == 0


def test_fixture_memory_probe_retains_no_extra_national_copy(tmp_path):
    import gc
    import sys
    import tracemalloc
    # One MiB synthetic national body; no weather values or outcomes are made up.
    body = TEXT.encode() + b'\n' + b'# padding\n' * ((1024 * 1024 - len(TEXT)) // 10)
    measurements = []
    for reuse in (False, True):
        root = tmp_path / str(reuse)
        fetch(root, lambda: {**VALUE, 'text': body.decode()}, 'warm', reuse=reuse)
        gc.collect()
        tracemalloc.start()
        coordinator = CrossProcessMarketInvariantFetchFanout(root)
        method = coordinator.fetch_reusable_nbp if reuse else coordinator.fetch
        result = method(**KEY, scope_key='later', fetch_fn=lambda: {**VALUE, 'text': body.decode()})
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert coordinator.completed_entry_count() == 1
        assert coordinator._local.max_entries == 2
        measurements.append({'reuse': reuse, 'body_bytes': len(body),
            'held_text_bytes': sys.getsizeof(result.value['text']),
            'traced_current_bytes': current, 'traced_peak_bytes': peak})
    assert measurements[1]['held_text_bytes'] == measurements[0]['held_text_bytes']
    print('NBP_MEMORY_PROBE=' + json.dumps(measurements))
