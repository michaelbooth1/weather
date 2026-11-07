"""Closed recorder fault injection only.

Guards: B018/T024 independent observation passes, strict JSON, atomic publication,
explicit corrupt-attempt recovery and complete paired accrual-walk replay.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path

import pytest

from weather.market import lfc_recording_io as evidence
from weather.market import lfc_rewards_record as rewards
from tests.market.test_lfc_rewards_record import START, MAKER, CONDITION, accrual_fixture, owner_command, page
from tests.market.test_lfc_settlement_record import record_settlement, resolution, tokens


@pytest.mark.parametrize('raw', [b'{"data":[1],"data":[]}', b'{"pagination":{},"pagination":{}}',
    b'{"payouts":[1000000,0],"payouts":[0,1000000]}', b'{"row":{"amount":1,"amount":0}}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}'])
def test_ambiguous_json_is_never_admitted(raw):
    with pytest.raises(ValueError):
        evidence.strict_json(raw)


def test_atomic_writer_fsync_failure_leaves_attempt_not_final(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('synthetic fsync failure')))
    target = tmp_path / 'final.json'
    with pytest.raises(OSError):
        evidence.write_new(target, {'answer': 1})
    assert not target.exists()
    attempts = list(tmp_path.glob('.final.json.attempt-*'))
    assert len(attempts) == 1 and attempts[0].read_bytes()


def test_atomic_writer_publish_failure_retains_complete_attempt(tmp_path, monkeypatch):
    def fail(*args): raise OSError('synthetic publication failure')
    monkeypatch.setattr(evidence.os, 'link', fail)
    with pytest.raises(OSError): evidence.write_new(tmp_path / 'final.json', {'answer': 42})
    assert not (tmp_path / 'final.json').exists()
    attempts = list(tmp_path.glob('.final.json.attempt-*'))
    assert len(attempts) == 1 and evidence.strict_json(attempts[0].read_bytes()) == {'answer': 42}


def test_atomic_writer_serializes_before_creating_any_file(tmp_path):
    with pytest.raises(ValueError): evidence.write_new(tmp_path / 'final.json', {'answer': float('nan')})
    assert list(tmp_path.iterdir()) == []


def test_atomic_writer_partial_write_leaves_attempt_not_final(tmp_path, monkeypatch):
    original = Path.open
    class Partial:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def write(self, raw):
            self.stream.write(raw[:5])
            raise OSError('synthetic partial write')
    monkeypatch.setattr(Path, 'open', lambda self, mode='r', *a, **kw:
        Partial(original(self, mode, *a, **kw)) if mode == 'xb' else original(self, mode, *a, **kw))
    with pytest.raises(OSError):
        evidence.write_new(tmp_path / 'final.json', {'answer': 1})
    assert not (tmp_path / 'final.json').exists()
    assert list(tmp_path.glob('.final.json.attempt-*'))[0].read_bytes() == b'{"ans'


def test_atomic_writer_collision_is_exclusive_and_keeps_losing_attempt(tmp_path):
    target = tmp_path / 'final.json'
    def writer(number):
        try:
            evidence.write_new(target, {'answer': number})
            return number
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, (1, 2)))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1 and evidence.strict_json(target.read_bytes()) == {'answer': winners[0]}
    assert len(list(tmp_path.glob('.final.json.attempt-*'))) == 1


def test_corrupt_settlement_recovery_keeps_original_and_hash_bound_manifest(tmp_path):
    target = tmp_path / 'settlement' / (CONDITION + '.json')
    target.parent.mkdir()
    target.write_bytes(b'{"partial":')
    old = target.read_bytes()
    row = record_settlement(tmp_path, CONDITION, recover_corrupt=True, clock=lambda: START,
                           get=lambda endpoint, params: resolution() if endpoint.endswith('resolutions') else tokens())
    from weather.market.lfc_settlement_record import load_settlements
    assert row['terminal'] and target.read_bytes() == old
    assert load_settlements(target.parent, [CONDITION]) == {CONDITION: '222'}
    assert len(list((target.parent / 'recovery').glob('*-published.json'))) == 1


def test_corrupt_rebate_recovery_keeps_original(tmp_path):
    target = tmp_path / 'rewards' / '2026-09-20-rebate.json'
    target.parent.mkdir()
    target.write_bytes(b'{"partial":')
    row = rewards.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=lambda *a: page(), recover_corrupt=True)
    assert rewards.record_complete(row) and target.read_bytes() == b'{"partial":'
    loaded, actual, _ = rewards.latest_record(target, kind='lfc_rebate_record', day='2026-09-20',
                                            maker=MAKER, conditions=[CONDITION], lag=1)
    assert loaded == row and actual != target


def test_duplicate_resolution_and_rebate_data_are_retained_incomplete(tmp_path):
    raw = resolution().replace(b'"payouts":', b'"payouts":[1000000,0],"payouts":')
    row = record_settlement(tmp_path, CONDITION, get=lambda *a: raw)
    assert not row['terminal'] and row['reason'] == 'recording_duplicate_json_key'
    assert row['resolution']['raw_response'].encode() == raw
    raw = b'{"data":[{"usdc_size":1}],"data":[],"pagination":{"has_more":false,"next_cursor":null}}'
    row = rewards.record_rebates(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        clock=lambda: START + timedelta(days=1, hours=2), get=lambda *a: raw)
    assert not rewards.record_complete(row) and row['flags'] == [{'flag': 'rebate_read_incomplete'}]
    assert row['activity']['pages'][0]['raw_response'].encode() == raw


def test_failed_tokens_read_keeps_successful_resolution_and_attempts(tmp_path):
    def get(endpoint, params):
        if endpoint.endswith('resolutions'): return resolution()
        raise evidence.PublicReadFailure('recording_response_refused', status=503, raw=b'upstream unavailable')
    row = record_settlement(tmp_path, CONDITION, get=get, clock=lambda: START)
    assert not row['terminal'] and row['resolution']['raw_response'].encode() == resolution()
    attempts = [evidence.strict_json(path.read_bytes()) for path in
                (tmp_path / 'settlement' / 'reads' / CONDITION).glob('*.json')]
    assert len(attempts) == 2
    failed = next(read for read in attempts if read['status'] == 503)
    assert failed['endpoint'] == '/v2/tokens' and failed['query'] == {'condition': CONDITION}
    assert evidence.response_bytes(failed['response']) == b'upstream unavailable'


@pytest.mark.parametrize('mutation', ['cursor', 'omitted', 'params', 'provenance', 'walk_scope'])
def test_missing_terminal_or_omitted_accrual_page_refuses_resume(tmp_path, monkeypatch, mutation):
    venue, journal, clock = accrual_fixture(monkeypatch)
    row = rewards.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=clock, get=lambda *a: page())
    target = tmp_path / 'rewards' / '2026-09-20-d1.json'
    receipt = next(item for item in row['wire_journal'] if item.get('event') == 'sdk_response' and item.get('path') == '/rewards/user')
    linked = next(item for item in row['wire_journal'] if item.get('event') == 'accrual_response')
    if mutation == 'cursor':
        payload = json.loads(receipt['raw_response'])
        payload['next_cursor'] = 'more-pages'
        receipt.update(evidence.retained(json.dumps(payload).encode()))
        linked['response_sha256'] = receipt['sha256']
    elif mutation == 'omitted':
        row['wire_journal'].remove(linked)
    elif mutation == 'params':
        next(item for item in row['wire_journal'] if item.get('event') == 'accrual_request')['params']['date'] = '2026-09-19'
    elif mutation == 'provenance':
        total = next(item for item in row['wire_journal'] if item.get('path') == '/rewards/user/total' and 'sha256' in item)
        row['accruals'][0]['accruals'][0]['source_record_sha256'] = total['sha256']
    else:
        next(item for item in row['wire_journal'] if item.get('event') == 'accrual_walk_start')['maker'] = '0x' + 'b' * 40
    target.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        rewards.load_record(target, kind='lfc_rewards_record', day='2026-09-20', maker=MAKER,
                            conditions=[CONDITION], lag=1)


def test_d2_is_independent_of_persistently_failed_d1(tmp_path, monkeypatch):
    venue, journal, clock = accrual_fixture(monkeypatch)
    def fail(*args): raise TimeoutError()
    d1 = rewards.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=clock, get=fail)
    base = tmp_path / 'rewards' / '2026-09-20-d1.json'
    before = base.read_bytes()
    args = owner_command(tmp_path, monkeypatch, now=START + timedelta(days=2, hours=1))
    monkeypatch.setattr(rewards, 'load_reward_credentials', lambda: ({'FUNDER_ADDRESS': MAKER}, rewards.SecretGuard()))
    monkeypatch.setattr(rewards, 'AccrualTransport', lambda *a: None)
    monkeypatch.setattr(rewards, 'AccrualClient', lambda *a: None)
    original_rewards, original_rebates = rewards.record_rewards, rewards.record_rebates
    def record(*args, **kwargs):
        kwargs.update(venue=venue, journal=journal, get=lambda *a: page())
        return original_rewards(*args, **kwargs)
    monkeypatch.setattr(rewards, 'record_rewards', record)
    monkeypatch.setattr(rewards, 'record_rebates', lambda *a, **kw: original_rebates(*a, **dict(kw, get=lambda *a: page())))
    assert rewards.run_rewards_record(args) == 0
    assert not rewards.record_complete(d1) and base.read_bytes() == before
    assert (base.parent / '2026-09-20-d2.json').exists()
    assert (base.parent / '2026-09-20-d2-rebate.json').exists()


def test_zero_width_reward_window_is_explicitly_incomplete(tmp_path, monkeypatch):
    venue, journal, _ = accrual_fixture(monkeypatch)
    row = rewards.record_rewards(tmp_path, '2026-09-20', maker=MAKER, conditions=[CONDITION],
        venue=venue, journal=journal, clock=lambda: START + timedelta(days=1), get=lambda *a: pytest.fail('no open window'))
    assert not rewards.record_complete(row)
    assert row['distributions']['failure_type'] == 'activity_zero_width_reward_window'
