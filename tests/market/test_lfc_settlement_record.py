"""Synthetic v2 resolution and token reference envelopes only.

Guards: F2 R1 create-only venue settlement, pending re-reads and price/label independence.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from weather.market.lfc_settlement_record import load_settlements, record_settlement as raw_record_settlement, resolution_result
from weather.market import lfc_settlement_record as recorder

CONDITION = '0x' + 'c' * 64
NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


def record_settlement(*args, **kwargs):
    kwargs.setdefault('traded_tokens', ('111', '222'))
    return raw_record_settlement(*args, **kwargs)


def resolution(status='resolved', payouts=None):
    return json.dumps({'data': [{'condition_id': CONDITION, 'status': status,
        'payouts': [0, 1_000_000] if payouts is None else payouts,
        'extended_review': False, 'was_disputed': False, 'new_version_q': False,
        'transaction_hash': '0x' + 'f' * 64, 'log_index': '1', 'last_update_timestamp': NOW.isoformat()}]}).encode()


def tokens():
    return json.dumps({'data': [{'condition_id': CONDITION, 'token_id': token, 'outcome_index': index,
        'module': 'v1_ctf', 'resolved': True, 'final_price': .5} for index, token in enumerate(('111', '222'))]}).encode()


def test_pending_then_terminal_create_only_without_ledger_or_prices(tmp_path):
    calls = []
    def get(path, params):
        calls.append((path, params))
        return resolution('proposed') if path.endswith('resolutions') else tokens()
    first = record_settlement(tmp_path, CONDITION, clock=lambda: NOW, get=get)
    assert first['terminal'] is False and first['winning_token_id'] is None
    assert not (tmp_path / 'settlement' / (CONDITION + '.json')).exists()
    assert len(list((tmp_path / 'settlement' / 'pending' / CONDITION).glob('*.json'))) == 1
    row = record_settlement(tmp_path, CONDITION, clock=lambda: NOW,
        get=lambda path, params: resolution() if path.endswith('resolutions') else tokens())
    target = tmp_path / 'settlement' / (CONDITION + '.json')
    before = target.read_bytes()
    assert row['winning_token_id'] == '222'  # deliberately contradictory final_price ignored
    assert row['resolution']['sha256'] == hashlib.sha256(resolution()).hexdigest()
    assert load_settlements(tmp_path / 'settlement', [CONDITION]) == {CONDITION: '222'}
    with pytest.raises(FileExistsError):
        record_settlement(tmp_path, CONDITION, get=lambda *a: pytest.fail('must refuse before GET'))
    assert target.read_bytes() == before and not (tmp_path / 'ledger.jsonl').exists()
    assert calls == [('/v2/resolutions', {'condition': CONDITION})]


def test_resolution_miss_is_unknown(tmp_path):
    row = record_settlement(tmp_path, CONDITION, clock=lambda: NOW, get=lambda *a: b'{"data":[]}')
    assert row['terminal'] is False and load_settlements(tmp_path / 'settlement', [CONDITION]) == {}


@pytest.mark.parametrize('raw', [b'[]', b'{}', b'{"data":null}'])
def test_bad_envelope_refused(tmp_path, raw):
    row = record_settlement(tmp_path, CONDITION, get=lambda *a: raw)
    assert row['terminal'] is False and row['reason'] == 'recording_envelope'
    assert len(list((tmp_path / 'settlement' / 'reads' / CONDITION).glob('*.json'))) == 1


def test_split_payout_is_terminal_without_invented_winner():
    assert resolution_result(CONDITION, resolution(payouts=[500_000, 500_000]), tokens(), traded_tokens=['111']) == (True, None, ['111', '222'])


def test_resolved_lifecycle_without_payouts_stays_pending(tmp_path):
    raw = json.loads(resolution())
    raw['data'][0]['payouts'] = None
    row = record_settlement(tmp_path, CONDITION,
        get=lambda path, params: json.dumps(raw).encode() if path.endswith('resolutions') else tokens())
    assert row['terminal'] is False and row['winning_token_id'] is None
    assert not (tmp_path / 'settlement' / (CONDITION + '.json')).exists()


def test_settlement_observed_after_response_and_hash_checked(tmp_path):
    current = [NOW]
    def get(path, params):
        current[0] += timedelta(seconds=1)
        return resolution() if path.endswith('resolutions') else tokens()
    row = record_settlement(tmp_path, CONDITION, clock=lambda: current[0], get=get)
    assert row['observed_at_utc'] == (NOW + timedelta(seconds=2)).isoformat()
    target = tmp_path / 'settlement' / (CONDITION + '.json')
    row['resolution']['raw_response'] += ' '
    target.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='recording_response_hash'):
        load_settlements(tmp_path / 'settlement', [CONDITION])


def test_ambiguous_token_mapping_and_wrong_condition_refused():
    rows = json.loads(tokens())
    rows['data'].append(rows['data'][0])
    with pytest.raises(ValueError, match='no_matching_token_pair'):
        resolution_result(CONDITION, resolution(), json.dumps(rows).encode(), traded_tokens=['111'])
    with pytest.raises(ValueError, match='resolution_condition_scope'):
        resolution_result('0x' + 'd' * 64, resolution(), tokens(), traded_tokens=['111'])


def test_tampered_or_legacy_settlement_refused(tmp_path):
    record_settlement(tmp_path, CONDITION, get=lambda path, params: resolution() if path.endswith('resolutions') else tokens())
    target = tmp_path / 'settlement' / (CONDITION + '.json')
    row = json.loads(target.read_bytes())
    row['winning_token_id'] = '111'
    target.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='settlement_record_mismatch'):
        load_settlements(tmp_path / 'settlement', [CONDITION])
    target.write_text(json.dumps({CONDITION: '111'}))
    with pytest.raises(ValueError, match='settlement_record_scope'):
        load_settlements(tmp_path / 'settlement', [CONDITION])
    with pytest.raises(ValueError, match='settlement_directory_required'):
        load_settlements(target, [CONDITION])


def test_migrated_pair_selected_from_verified_campaign_intents(tmp_path):
    from weather.market.lfc_ledger import Ledger
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: NOW, maker_address='0x' + 'a' * 40)
    ledger.record('session_start', session_id='S1', counted=True, condition_id=CONDITION)
    for token in ('333', '444'):
        ledger.intent(session_id='S1', intent_key='S1:' + token, token_id=token, condition_id=CONDITION,
                      price='.4', size='20', fee_rate_bps='0')
    refs = json.loads(tokens())
    refs['data'] += [dict(row, module='binary', token_id=token, structural_condition_id='0x' + 'd' * 64)
                     for row, token in zip(refs['data'], ('333', '444'))]
    row = raw_record_settlement(tmp_path, CONDITION,
        get=lambda path, params: resolution() if path.endswith('resolutions') else json.dumps(refs).encode())
    assert row['terminal'] is True and row['winning_token_id'] == '444'
    assert row['token_ids'] == row['traded_token_ids'] == ['333', '444']
    with pytest.raises(ValueError, match='settlement_leg_token_outside_pair'):
        load_settlements(tmp_path / 'settlement', [CONDITION], tokens_by_condition={CONDITION: {'111'}})


def test_unmatched_pair_preserves_refused_reads_as_pending(tmp_path):
    for _ in range(2):
        row = raw_record_settlement(tmp_path, CONDITION, clock=lambda: NOW, traded_tokens=['999'],
            get=lambda path, params: resolution() if path.endswith('resolutions') else tokens())
        assert row['terminal'] is False and row['reason'] == 'no_matching_token_pair'
        assert row['tokens']['raw_response'].encode() == tokens()
    assert not (tmp_path / 'settlement' / (CONDITION + '.json')).exists()
    assert len(list((tmp_path / 'settlement' / 'pending' / CONDITION).glob('*.json'))) == 2


def test_missing_settlement_directory_refused(tmp_path):
    with pytest.raises(ValueError, match='settlement_directory_required'):
        load_settlements(tmp_path / 'absent', [CONDITION])


def test_public_get_allowlist_before_network(monkeypatch):
    monkeypatch.setattr(recorder, 'direct_opener', lambda: pytest.fail('network must not be constructed'))
    with pytest.raises(ValueError, match='recording_endpoint_refused'):
        recorder.public_get('/v2/positions', {})


@pytest.mark.parametrize('status,redirect,body,refused', [
    (200, False, b'12345678', None), (200, True, b'{}', 'recording_response_refused'),
    (503, False, b'{}', 'recording_response_refused'), (200, False, b'123456789', 'recording_response_budget')])
def test_public_get_response_guards(monkeypatch, status, redirect, body, refused):
    from io import BytesIO
    requests = []
    class Reply(BytesIO):
        def geturl(self):
            return 'https://example.invalid/redirect' if redirect else requests[0].full_url
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            assert request.get_method() == 'GET' and request.data is None
            assert request.get_header('User-agent') == recorder.USER_AGENT
            assert not request.has_header('Authorization')
            reply = Reply(body)
            reply.status = status
            return reply
    monkeypatch.setattr(recorder, 'direct_opener', Opener)
    monkeypatch.setattr(recorder, 'MAX_BYTES', 8)
    if refused:
        with pytest.raises(ValueError, match=refused):
            recorder.public_get('/v2/resolutions', {'condition': CONDITION})
    else:
        assert recorder.public_get('/v2/resolutions', {'condition': CONDITION}) == body
    assert len(requests) == 1


def test_public_get_redirect_is_not_followed(monkeypatch):
    from urllib.error import HTTPError
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 302, 'redirect', {}, None)
    monkeypatch.setattr(recorder, 'direct_opener', Opener)
    with pytest.raises(recorder.PublicReadFailure) as error:
        recorder.public_get('/v2/tokens', {'condition': CONDITION})
    assert error.value.status == 302


def test_recorded_public_shapes_have_intact_receipts_and_no_invented_payout():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'fixtures' / 'lfc_recording' / 'public_v2_20261106'
    provenance = json.loads((root / 'provenance.json').read_bytes())
    for receipt in provenance:
        raw = (root / (receipt['endpoint'].rsplit('/', 1)[1] + '.json')).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == receipt['sha256']
        assert receipt['status'] == 200 and receipt['user_agent'] == recorder.USER_AGENT
    refs = json.loads((root / 'tokens.json').read_bytes())['data']
    condition = refs[0]['condition_id']
    traded = [r['token_id'] for r in refs]
    assert set(recorder.select_token_pair(condition, refs, traded)) == set(traded)
    assert resolution_result(condition, (root / 'resolutions.json').read_bytes(),
        (root / 'tokens.json').read_bytes(), traded_tokens=traded) == (False, None, [])
