from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import subprocess
import sys
from urllib.request import Request

import pytest

from weather.market.mm_stage2_selection import capacity_quote, select_table
from weather.market.reward_capacity import (
    CapturedResponse, PublicTransport, SamplerStopped, event_identity, model_band, sample,
)
from weather.market.reward_capacity_report import summarize, write_summary
from weather.market.reward_quote import price_reward_quote

NOW = datetime(2026, 9, 22, 16, tzinfo=timezone.utc)


def band():
    values = {'yes_bids': [{'price': '.34', 'size': '100'}],
              'yes_asks': [{'price': '.35', 'size': '100'}],
              'no_bids': [{'price': '.65', 'size': '100'}],
              'no_asks': [{'price': '.66', 'size': '100'}],
              'reward_min_size': '20', 'reward_max_spread_cents': '4.5',
              'reward_rate_per_day': '100', 'tick': '.01', 'post_only_available': True}
    condition, tokens = '0x' + 'b' * 64, ['111', '222']
    return {'market_id': 'los-angeles', 'market_timezone': 'America/Los_Angeles',
            'target_date': '2026-09-23', 'condition_id': condition, 'token_ids': tokens,
            'snapshot': {'condition_id': condition, 'token_ids': tokens,
                         'observed_at_utc': NOW.isoformat(), 'quote_inputs': values}}


@pytest.mark.parametrize('bid,ask,minimum,spread,depth', [
    ('.34', '.35', '20', '4.5', '100'), ('.48', '.52', '5', '3', '200'),
    ('.20', '.22', '10', '6', '50'), ('.77', '.79', '20', '4', '1000'),
])
def test_twenty_share_parity_with_canonical_quote_and_ranking(bid, ask, minimum, spread, depth):
    from decimal import Decimal
    row = band()
    inputs = row['snapshot']['quote_inputs']
    inputs.update(yes_bids=[{'price': bid, 'size': depth}], yes_asks=[{'price': ask, 'size': depth}],
        no_bids=[{'price': str(1 - Decimal(ask)), 'size': depth}],
        no_asks=[{'price': str(1 - Decimal(bid)), 'size': depth}], reward_min_size=minimum,
        reward_max_spread_cents=spread)
    quote = capacity_quote(row['snapshot'], size=20, now=NOW)
    assert quote == price_reward_quote(**inputs)
    table = select_table([row], now=NOW)
    model = model_band(row)[0]
    assert model['predicted_360_minutes'] == table['rows'][0]['predicted_360_minutes']
    assert model['eligible'] == table['rows'][0]['eligible']
    for size in (50, 100, 200):
        larger = capacity_quote(row['snapshot'], size=size, now=NOW)
        assert larger.own_q_min == pytest.approx(quote.own_q_min * size / 20)
        assert larger.reserve_pusd == quote.reserve_pusd * size / 20
        assert larger.share_many == pytest.approx(larger.own_q_min / (larger.own_q_min + quote.competing_q_many))


def test_frozen_refusals_are_not_relaxed_for_size():
    row = band()
    row['snapshot']['quote_inputs']['reward_min_size'] = '50'
    assert all(not r['eligible'] and r['refusal'] == 'reward_minimum_outside_treatment' for r in model_band(row))
    with pytest.raises(ValueError):
        capacity_quote(band()['snapshot'], size=21, now=NOW)


def test_capital_and_dilution_are_not_profit_or_double_counted_cash():
    for row in model_band(band()):
        quote = row['quote']
        assert row['share_with_one_equal_competitor'] == pytest.approx(quote['share_many'] / (1 + quote['share_many']))
        assert row['share_with_three_equal_competitors'] == pytest.approx(quote['share_many'] / (1 + 3 * quote['share_many']))
        assert row['worst_case_one_fill_loss_pusd'] < row['capital_pusd']


def test_public_import_closure_has_no_order_or_dotenv_path():
    script = """
import sys
from weather.market import reward_capacity, reward_capacity_report
for name in sys.modules:
    assert not any(x in name for x in ('dotenv', 'official_adapter', 're1_attended', 'mm_live', 'live_sdk_overlay', 're1_transport')), name
"""
    subprocess.run([sys.executable, '-c', script], check=True, timeout=10)


class Clock:
    seconds = 0.0
    def now(self): return NOW + timedelta(seconds=self.seconds)
    def sleep(self, seconds): self.seconds += seconds
    def monotonic(self): return self.seconds


def test_transport_hashes_every_response_throttles_and_overrides_headers(tmp_path):
    clock, calls = Clock(), []
    body = b'{"public":true}'
    def opener(request, *, timeout):
        calls.append((clock.seconds, dict(request.header_items())))
        assert request.get_method() == 'GET' and timeout == 2
        return CapturedResponse(body, 200, {'Content-Type': 'application/json'}, request.full_url)
    transport = PublicTransport(tmp_path, NOW + timedelta(minutes=5), lease=nullcontext,
        clock=clock.now, monotonic=clock.monotonic, sleep=clock.sleep, opener=opener)
    for _ in range(2):
        transport(Request('https://clob.polymarket.com/book?token_id=1', headers={'Authorization': 'must-be-stripped'}))
    assert calls[1][0] - calls[0][0] >= 1
    assert all(set(headers) == {'Accept', 'User-agent'} for _, headers in calls)
    for line in (tmp_path / 'responses.jsonl').read_text().splitlines():
        record = json.loads(line)
        assert base64.b64decode(record['response_body_base64']) == body
        assert record['response_sha256'] == hashlib.sha256(body).hexdigest()
    with pytest.raises(ValueError, match='nonpublic'):
        transport(Request('https://clob.polymarket.com/data/orders'))


@pytest.mark.parametrize('fault', ['stop', 'deadline', 'live'])
def test_stop_and_live_mutex_prevent_even_one_request(tmp_path, fault):
    clock = Clock()
    @contextmanager
    def lease():
        if fault == 'live': raise SamplerStopped('busy')
        yield
    transport = PublicTransport(tmp_path, NOW + timedelta(seconds=5 if fault == 'deadline' else 300),
        lease=lease, clock=clock.now, monotonic=clock.monotonic, sleep=clock.sleep,
        opener=lambda *_args, **_kw: pytest.fail('network request after stop'))
    if fault == 'stop': (tmp_path.parent / 'STOP').touch()
    try:
        with pytest.raises(SamplerStopped):
            transport(Request('https://clob.polymarket.com/book?token_id=1'))
    finally:
        if fault == 'stop': (tmp_path.parent / 'STOP').unlink()


def test_failed_http_is_journalled_before_refusal(tmp_path):
    clock = Clock()
    transport = PublicTransport(tmp_path, NOW + timedelta(minutes=5), lease=nullcontext,
        clock=clock.now, monotonic=clock.monotonic, sleep=clock.sleep,
        opener=lambda r, **kw: CapturedResponse(b'busy', 503, {}, r.full_url))
    with pytest.raises(ValueError):
        transport(Request('https://clob.polymarket.com/book?token_id=1'))
    assert json.loads((tmp_path / 'responses.jsonl').read_text())['http_status'] == 503


def test_discovery_uses_market_local_date_without_excluding_unconfigured_weather():
    now = datetime(2026, 9, 23, 2, tzinfo=timezone.utc)
    assert event_identity({'slug': 'highest-temperature-in-los-angeles-on-september-22-2026'}, now)['horizon'] == 0
    assert event_identity({'slug': 'lowest-temperature-in-london-on-september-23-2026'}, now)['configured_market'] is False
    assert event_identity({'slug': 'highest-temperature-in-los-angeles-on-september-24-2026'}, now) is None


def test_summary_never_fills_live_pause_or_calls_short_window_complete():
    def sample(offset, complete=True):
        return {'started_at_utc': (NOW + timedelta(hours=offset)).isoformat(),
            'finished_at_utc': (NOW + timedelta(hours=offset, minutes=5)).isoformat(),
            'complete': complete, 'rows': model_band(band())}
    result = summarize([sample(0), sample(.25, False), sample(8)])
    assert result['verdict'] == 'INCOMPLETE_24H_COLLECTION'
    assert result['complete_samples'] == 2
    assert result['covered_hours'] == pytest.approx(.25 + 5/60)
    assert all(r['samples'] == 0 for r in result['hour_of_day_ET'] if r['hour_ET'] == 15)
    assert result['best_bands'][0]['actual_bands'] <= 1


def test_twenty_four_hour_readiness_requires_coverage_not_just_span():
    rows = [{'started_at_utc': (NOW + timedelta(minutes=15*i)).isoformat(),
             'finished_at_utc': (NOW + timedelta(minutes=15*i+5)).isoformat(),
             'complete': True, 'rows': model_band(band())} for i in range(97)]
    assert summarize(rows)['verdict'] == 'MODELLED_DESCRIPTIVE_CURVE'
    assert summarize([rows[0], rows[-1]])['verdict'] == 'INCOMPLETE_24H_COLLECTION'


def test_impossible_cadence_stops_before_book_requests(tmp_path, monkeypatch):
    import weather.market.reward_capacity as capacity
    markets = [{'conditionId': '0x' + format(i, '064x')} for i in range(200)]
    monkeypatch.setattr(capacity, 'discover', lambda _: [({'configured_market': True}, {'markets': markets})])
    monkeypatch.setattr(capacity, 'rewarded_conditions', lambda _: {m['conditionId'] for m in markets})
    transport = PublicTransport(tmp_path, NOW + timedelta(hours=2), clock=lambda: NOW, lease=nullcontext,
        opener=lambda *_args, **_kw: pytest.fail('impossible cadence started requests'))
    with pytest.raises(SamplerStopped, match='cannot_fit'):
        sample(transport)


def test_summary_replays_response_bytes_and_rejects_tampering(tmp_path):
    from weather.market.exchange_economics_sources import response_evidence
    from weather.market.mm_stage2_public import canonical_bytes
    from weather.market.re1_rehearsal import Re1PublicBooks
    directory = tmp_path / 'run'
    directory.mkdir()
    row = band()
    condition, tokens = row['condition_id'], row['token_ids']
    reward = {'condition_id': condition, 'rewards_min_size': 20, 'rewards_max_spread': 4.5, 'total_daily_rate': 100}
    records = []
    def opener(request, **_kwargs):
        if '/rewards/' in request.full_url:
            payload = {'data': [reward], 'count': 1, 'limit': 100, 'next_cursor': 'LTE='}
        elif '/fee-rate' in request.full_url:
            payload = {'base_fee': 0}
        else:
            token = request.full_url.split('token_id=')[1]
            side = 'yes' if token == tokens[0] else 'no'
            payload = {'asset_id': token, 'market': condition, 'tick_size': '.01', 'min_order_size': '5',
                       'neg_risk': False, 'bids': row['snapshot']['quote_inputs'][side + '_bids'],
                       'asks': row['snapshot']['quote_inputs'][side + '_asks']}
        body = canonical_bytes(payload)
        records.append(response_evidence(body, url=request.full_url, http_status=200,
                       content_type='application/json', origin='http_response_bytes'))
        return CapturedResponse(body, 200, {'Content-Type': 'application/json'}, request.full_url)
    reader = Re1PublicBooks(clock=lambda: NOW, opener=opener)
    current_reward = reader.reward(condition)
    row['snapshot'] = reader.snapshot(condition, tokens, reward=current_reward)
    row['sample_started_at_utc'] = NOW.isoformat()
    sample_row = {'started_at_utc': NOW.isoformat(), 'finished_at_utc': (NOW+timedelta(minutes=5)).isoformat(),
                  'complete': True, 'rows': model_band(row)}
    (directory/'responses.jsonl').write_bytes(b''.join(canonical_bytes(r) for r in records))
    (directory/'snapshots.jsonl').write_bytes(canonical_bytes(row))
    (directory/'samples.jsonl').write_bytes(canonical_bytes(sample_row))
    assert write_summary(tmp_path)['complete_samples'] == 1
    altered = deepcopy(row)
    altered['snapshot']['quote_inputs']['reward_rate_per_day'] = '1000'
    (directory/'snapshots.jsonl').write_bytes(canonical_bytes(altered))
    with pytest.raises(ValueError, match='snapshot_does_not_reproduce'):
        write_summary(tmp_path)
    (directory/'snapshots.jsonl').write_bytes(canonical_bytes(row))
    records[0]['response_sha256'] = '0' * 64
    (directory/'responses.jsonl').write_bytes(b''.join(canonical_bytes(r) for r in records))
    with pytest.raises(ValueError, match='raw_response_hash_mismatch'):
        write_summary(tmp_path)


def test_failed_cycle_has_nonzero_exit_and_removes_own_lock(tmp_path, monkeypatch):
    import weather.market.reward_capacity as capacity
    import weather.execution_host as host
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(capacity, 'datetime', FixedDatetime)
    monkeypatch.setattr(capacity, 'ROOT', tmp_path / 'evidence')
    assignment = tmp_path / 'assignment.json'
    assignment.write_text(json.dumps({'assignment_status': 'ASSIGNED',
        'active_portable_execution_host_id': 'workstation',
        'dedicated_capture_execution_host_id': 'capture',
        'active_portable_execution_principal_id': 'owner'}))
    monkeypatch.setattr(capacity, 'config_path', lambda *_: assignment)
    monkeypatch.setattr(host, 'current_execution_host_id', lambda: 'workstation')
    monkeypatch.setattr(host, 'current_execution_principal_id', lambda: 'owner')
    def refused(*_args, **_kwargs): raise ValueError('pagination_duplicate')
    monkeypatch.setattr(capacity, 'sample', refused)
    assert capacity.run(NOW + timedelta(minutes=1), once=True) == 2
    assert not (capacity.ROOT / 'sampler.lock').exists()
    terminal = json.loads(next(capacity.ROOT.glob('*/lifecycle.jsonl')).read_text().splitlines()[-1])
    assert terminal['event'] == 'stopped' and terminal['exit_code'] == 2
