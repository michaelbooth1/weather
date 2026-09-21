"""SDK 0.6 response fixtures through its actual parsers; no key or authentication."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from tests.market.test_mm_stage2_hold import run
from tests.market.test_mm_paid_incentive_reconciliation import evidence_fixture, add_payment, MAKER, CONDITION
from weather.market.mm_stage2_hold import verify_prediction_journal
from weather.market.mm_stage2_rewards import RewardsReaders, load_frozen_predictions, verdict, verify_campaign_day


def frozen(tmp_path):
    result, _, _ = run(tmp_path)
    records = [{'prediction': str(tmp_path / 'prediction.json'), 'journal': str(tmp_path / 'journal.jsonl'),
                'prediction_sha256': hashlib.sha256((tmp_path / 'prediction.json').read_bytes()).hexdigest()}]
    return result, records


def test_prediction_replays_and_tampered_sum_is_refused(tmp_path):
    result, records = frozen(tmp_path)
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    assert load_frozen_predictions(records, now=now) == [result]
    result['P_many'] += 1
    with pytest.raises(ValueError, match='reward sums'):
        verify_prediction_journal(result, tmp_path / 'journal.jsonl')
    with pytest.raises(ValueError, match='next-day'):
        load_frozen_predictions(records, now=datetime(2026, 9, 21, 15, tzinfo=timezone.utc))


def sdk_fixture():
    from polymarket.clients.secure import SecureClient, _CREATE_TOKEN
    calls = []
    row = {'date': '2026-09-21T00:00:00Z', 'maker_address': MAKER, 'asset_address': '0x' + 'c' * 40,
           'condition_id': CONDITION, 'earnings': '0.123456789012345678', 'asset_rate': '1'}
    def handle(request):
        calls.append((request.method, request.url.path))
        assert not any(k.lower().startswith('poly_') for k in request.headers)
        if request.url.path == '/orders-scoring': payload = dict.fromkeys(json.loads(request.content), True)
        elif request.url.path == '/order-scoring': payload = {'scoring': True}
        elif request.url.path == '/rewards/user': payload = {'data': [row], 'count': 1, 'limit': 100, 'next_cursor': 'LTE='}
        elif request.url.path == '/rewards/user/total': payload = [{k: v for k, v in row.items() if k != 'condition_id'}]
        elif request.url.path == '/rewards/user/markets': payload = {'data': [], 'next_cursor': 'LTE=', 'total_count': 0}
        elif request.url.path == '/rewards/user/percentages': payload = {CONDITION: 3.5}
        else: raise AssertionError(request.url)
        return httpx.Response(200, json=payload)
    http = httpx.Client(base_url='https://clob.polymarket.com', transport=httpx.MockTransport(handle))
    class Transport:
        _client = http
        def get_json(self, path, *, params): return http.get(path, params=params).json()
        def post_json(self, path, *, json): return http.post(path, json=json).json()
    # Construct only the SDK facade around the closed mock transport. No SDK
    # create(), account context, auth headers, wallet derivation or signer runs.
    client = SecureClient(ctx=SimpleNamespace(secure_clob=Transport(), wallet_type='EOA'), _create_token=_CREATE_TOKEN)
    return client, http, calls


def test_official_scoring_and_earnings_parsers_retain_exact_body(tmp_path):
    _, records = frozen(tmp_path)
    client, transport, calls = sdk_fixture()
    try:
        reader = RewardsReaders(client, purpose='explicit_post_session_collect')
        assert calls == []
        assert reader.scoring(('one', 'two')) == {'one': True, 'two': True}
        assert reader.order_scoring('one') is True
        result = reader.daily(reward_day='2026-09-21', maker_address=MAKER, signature_type=0,
                              clock=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc), prediction_records=records)
        assert result['payment_verified'] is False
        assert result['accrual_evidence']['row_count'] == 1
        assert result['accrual_evidence']['earnings_by_asset']['0x' + 'c' * 40] == '0.123456789012345678'
        assert result['sdk_totals'][0]['earnings'] == '0.123456789012345678'
        assert transport.event_hooks['response'] == []
        assert set(calls) == {('POST', '/orders-scoring'), ('GET', '/order-scoring'), ('GET', '/rewards/user'),
                              ('GET', '/rewards/user/total'), ('GET', '/rewards/user/markets'), ('GET', '/rewards/user/percentages')}
    finally:
        transport.close()


@pytest.mark.parametrize(('paid', 'decision'), [('1', 'PAID_AS_MODELLED'), ('0.2', 'PAID_DILUTED'), ('0', 'NOT_PAID'), ('0.1', 'INCONCLUSIVE')])
def test_frozen_verdict_thresholds(paid, decision):
    evidence = evidence_fixture()
    if paid != '0': add_payment(evidence, programme='liquidity_reward', amount=paid)
    prediction = {'reward_day': '2026-09-01', 'condition_id': CONDITION, 'mode': 'rehearsal',
        'scope': {'maker_address': MAKER}, 'P_many': 2, 'P_single': 3, 'visible_two_sided_minutes': 180,
        'cleanup_ok': True, 'cancel_acknowledged': True, 'fill_seen': False,
        'reward_terms_changed': False, 'all_observed_legs_scoring': True}
    result = verdict([prediction], payment_evidence=evidence)
    assert result['verdict'] == decision, result
    assert result['live_evidence'] is False
    prediction['visible_two_sided_minutes'] = 179
    assert verdict([prediction], payment_evidence=evidence)['verdict'] == 'INCONCLUSIVE'
    prediction['visible_two_sided_minutes'] = 180
    prediction['scope']['maker_address'] = '0x' + 'f' * 40
    assert verdict([prediction], payment_evidence=evidence)['verdict'] == 'INCONCLUSIVE'


def test_campaign_collection_refuses_omitted_same_day_attempt(tmp_path):
    from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as profile
    from weather.market.mm_stage2_hold import SCHEMA_VERSION, digest, write_new
    predictions = []
    for number in (1, 2):
        path = tmp_path / f'2026-09-21-{number}.attempt.json'
        attempt = {'schema_version': SCHEMA_VERSION, 'kind': 'session', 'reward_day': '2026-09-21',
            'condition_id': CONDITION, 'profile_sha256': profile.sha256, 'fixture_attempt_number': number}
        write_new(path, attempt)
        prediction = {'scope': {'campaign_attempt_path': str(path), 'campaign_attempt_sha256': digest(attempt)},
            'condition_id': CONDITION, 'reward_day': '2026-09-21', 'mode': 'live'}
        write_new(path.with_name(path.name.replace('.attempt.json', '.result.json')),
            {'attempt_sha256': digest(attempt), 'prediction_sha256': digest(prediction)})
        predictions.append(prediction)
    assert verify_campaign_day(predictions) == ['2026-09-21']
    with pytest.raises(ValueError, match='omits'):
        verify_campaign_day(predictions[:1])
