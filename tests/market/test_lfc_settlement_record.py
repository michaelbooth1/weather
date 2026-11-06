"""Synthetic v2 resolution and token reference envelopes only.

Guards: F2 R1 create-only venue settlement, pending re-reads and price/label independence.
"""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from weather.market.lfc_settlement_record import load_settlements, record_settlement, resolution_result

CONDITION = '0x' + 'c' * 64
NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


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
    with pytest.raises(ValueError, match='recording_envelope'):
        record_settlement(tmp_path, CONDITION, get=lambda *a: raw)
    assert not (tmp_path / 'settlement').exists()


def test_split_payout_is_terminal_without_invented_winner():
    assert resolution_result(CONDITION, resolution(payouts=[500_000, 500_000]), tokens()) == (True, None)


def test_resolved_lifecycle_without_payouts_stays_pending(tmp_path):
    raw = json.loads(resolution())
    raw['data'][0]['payouts'] = None
    row = record_settlement(tmp_path, CONDITION,
        get=lambda path, params: json.dumps(raw).encode() if path.endswith('resolutions') else tokens())
    assert row['terminal'] is False and row['winning_token_id'] is None
    assert not (tmp_path / 'settlement' / (CONDITION + '.json')).exists()


def test_ambiguous_token_mapping_and_wrong_condition_refused():
    rows = json.loads(tokens())
    rows['data'].append(rows['data'][0])
    with pytest.raises(ValueError, match='resolution_token_mapping'):
        resolution_result(CONDITION, resolution(), json.dumps(rows).encode())
    with pytest.raises(ValueError, match='resolution_condition_scope'):
        resolution_result('0x' + 'd' * 64, resolution(), tokens())


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
