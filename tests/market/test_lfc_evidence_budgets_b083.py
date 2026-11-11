"""Guards: B083 full account proofs survive every retained-evidence reopen."""
from datetime import datetime
import json
import io
import os
from pathlib import Path

import pytest

from tests.market.test_lfc_account_pages_b079 import trade_row
from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, NOW, state_at
from tests.market.test_lfc_campaign_adversarial import reconciled_legacy
from tests.market.test_lfc_campaign_runtime import account_read, runtime_at
from tests.market.test_lfc_f2_inventory_b080 import fixture, observation
from tests.market.test_lfc_review_b067_integrity import prepared
from tests.market.test_lfc_unattended_account_reads import sdk_client
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_history import history_refusals, record_owner_recovery, validate_recovery
from weather.market.lfc_campaign_runtime import Runtime
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_ledger import Ledger, latest_baseline, take_baseline, write_baseline
from weather.market.lfc_recording_io import (ACCOUNT_EVIDENCE_JSON_LIMIT, STATE_JSON_LIMIT,
    file_sha, read_bytes, strict_json, write_new)
from weather.market.mm_stage2_hold import canonical_bytes, digest
from weather.market.re1_transport import OwnerVenue


@pytest.fixture(scope='module')
def large_trades():
    """Real SDK model normalization over an inert 5000-row HTTP page."""
    body = dict(data=[trade_row(n) for n in range(5000)], next_cursor='LTE=', limit=5000, count=5000)
    client, _, http, calls = sdk_client(lambda _: body)
    venue = object.__new__(OwnerVenue)
    venue.client, venue.condition = client, None
    venue.trades_after, venue.trades_seconds = '1791583200', 60
    try:
        rows = venue.trades()
        assert len(rows) == 5000 and len(calls) == 1
        assert len(canonical_bytes(rows)) > 2_000_000
        return rows
    finally:
        http.close()


def recovery(tmp_path, trades):
    ledger = reconciled_legacy(tmp_path)
    runtime = Runtime(state=AccountState(tmp_path/'state', ledger), pilot_root=tmp_path,
        policy_path=tmp_path/'unused.json', release={}, clock=Clock(),
        control_root=tmp_path/'control', task_enabled=lambda: False)
    read = account_read(runtime, trades=trades)
    read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
    proof = runtime.core_proof(ledger, read)
    event = record_owner_recovery(ledger, tmp_path, 'S0c-1', account_read=read, proof=proof,
                                 now=NOW, containment_proven=True)
    return ledger, read, event


def test_owner_recovery_reopens_5000_trade_proof(tmp_path, large_trades):
    with account_lease(MAKER, backend=Mutexes()):
        ledger, read, event = recovery(tmp_path, large_trades)
        path = tmp_path/event['file']
        assert path.stat().st_size > 2_000_000
        saved = validate_recovery(ledger, tmp_path, event)
        assert saved['account_read'] == read and saved['account_read_sha256'] == digest(read)
        reopened = Ledger.open(ledger.path, clock=ledger.clock)
        assert history_refusals(reopened, tmp_path) == {}
        assert validate_recovery(reopened, tmp_path, event) == saved


@pytest.mark.parametrize('directory', ['account-reads', 'go-refreshes', 'prepared',
                                     'postchecks', 'owner-closures', 'funding'])
def test_state_envelopes_reopen_complete_sdk_account_read(tmp_path, large_trades, directory):
    with account_lease(MAKER, backend=Mutexes()):
        state = state_at(tmp_path, Clock())
        body = {'account_read': {'trades': large_trades}, 'read_sha256': digest(large_trades)}
        relative = directory+'/large.json'
        sha = state.save(relative, body)
        path = state.root/relative
        assert path.stat().st_size > 2_000_000 and file_sha(path) == sha
        assert state.read(path)['account_read']['trades'] == large_trades
        cold = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=state.ledger.clock))
        assert cold.read_uncached(path, expected_sha256=sha)['account_read']['trades'] == large_trades


def test_go_packet_writer_and_reader_retain_full_proof(tmp_path, large_trades):
    read = {'trades': large_trades}
    row = {'read': read, 'proof': {'read_sha256': digest(read)}}
    path = tmp_path/'go_account.json'
    write_new(path, row, max_bytes=STATE_JSON_LIMIT)
    assert path.stat().st_size > 2_000_000
    saved = strict_json(read_bytes(path, STATE_JSON_LIMIT))
    assert saved == row and saved['proof']['read_sha256'] == digest(saved['read'])


def test_closure_anchors_and_reopens_full_account_read(tmp_path, monkeypatch, large_trades):
    with account_lease(MAKER, backend=Mutexes()):
        runtime, _, claim, proof = prepared(tmp_path, monkeypatch)
        read = {**proof['account_read'], 'trades': proof['account_read']['trades']+large_trades}
        proof.update(account_read=read, read_sha256=digest(read))
        state = runtime.state
        state.close(claim, proof, NOW)
        path = state.root/'closed'/(claim['attempt_id']+'.json')
        assert path.stat().st_size > 2_000_000
        sha = file_sha(path)
        assert state.read(path)['proof']['account_read'] == read
        cold = AccountState(state.root.parent, Ledger.open(state.ledger.path, clock=state.ledger.clock))
        cold.verify()
        compact = cold.closed_binding(path)
        assert compact['proof']['read_sha256'] == digest(read)
        assert 'account_read' not in compact['proof']  # Existing bounded cache projection.
        assert cold.read_uncached(path)['proof']['account_read'] == read
        assert file_sha(path) == sha
        assert len(cold.ledger.event_rows('autostart_close_intent')) == 1
        assert len(cold.ledger.event_rows('autostart_close')) == 1


def test_inventory_anchor_and_bridge_bind_large_read_without_embedding_it(tmp_path, large_trades):
    ledger, baseline, clock, _ = fixture(tmp_path, bridge=False)
    read = observation(ledger, clock, positions={'denver': '20'}, cash='302')
    read['trades'] += large_trades
    result = synchronize(ledger, baseline, read, anchor_mode='enrollment')
    book = CapitalBook(ledger)
    anchor = book.inventory_anchor
    assert result['cash_bridge_complete'] and result['funding_native'] == 300_000_000
    assert anchor['read_sha256'] == digest(read) == book.bridge['proof']['read_sha256']
    assert 'account_read' not in anchor and 'account_read' not in book.bridge['proof']
    reopened = CapitalBook(Ledger.open(ledger.path, clock=clock.now))
    assert reopened.inventory_anchor == anchor and reopened.figures() == book.figures()


def test_compact_baseline_budget_matches_both_readers(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        ledger = Ledger.create(tmp_path/'ledger.jsonl', clock=Clock().now, maker_address=MAKER)
        runtime = Runtime(state=AccountState(tmp_path/'state', ledger), pilot_root=tmp_path,
            policy_path=tmp_path/'unused.json', release={}, clock=Clock(),
            control_root=tmp_path/'control', task_enabled=lambda: False)
        # Baselines retain compact positions, not SDK trade pages.
        row = take_baseline(label='t40', now=NOW, maker_address=MAKER, positions=[],
                            open_orders=[], available_collateral='100')
        row['synthetic_retained_padding'] = 'x'*2_000_000
        write_baseline(runtime.pilot_root, row, ledger)
        assert runtime.original_baseline(runtime.state.ledger) == row
        assert latest_baseline(runtime.pilot_root, runtime.state.ledger, 't40') == row


def test_budget_covers_measured_maximum_trade_count_with_safety_factor(large_trades):
    measured = len(canonical_bytes(large_trades))
    assert 4*(measured*25000//5000) < ACCOUNT_EVIDENCE_JSON_LIMIT
    assert STATE_JSON_LIMIT == ACCOUNT_EVIDENCE_JSON_LIMIT
    # The raw page and RPC bounds remain independent; no page cap was raised.
    from weather.market.mm_account_reads import ACCOUNT_RESPONSE_MAX_BYTES
    from weather.market.lfc_capital_native import MAX_BYTES, MAX_NEW_RECEIPTS
    assert ACCOUNT_EVIDENCE_JSON_LIMIT == 256_000_000
    assert (ACCOUNT_RESPONSE_MAX_BYTES, MAX_BYTES, MAX_NEW_RECEIPTS) == (16_000_000, 2_000_000, 200)


def test_real_limit_plus_one_refuses_without_read_allocation(tmp_path, monkeypatch):
    path = tmp_path/'oversized.json'
    path.write_bytes(b'{}')
    original = Path.stat
    def reported_size(value, *args, **kwargs):
        result = original(value, *args, **kwargs)
        if value == path:
            fields = list(result)
            fields[6] = ACCOUNT_EVIDENCE_JSON_LIMIT+1
            return os.stat_result(fields)
        return result
    monkeypatch.setattr(Path, 'stat', reported_size)
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: pytest.fail('oversize must refuse before allocating/reading'))
    with pytest.raises(ValueError, match='recording_file_budget'):
        read_bytes(path, ACCOUNT_EVIDENCE_JSON_LIMIT)


def test_actual_file_and_writer_boundary_stays_fail_closed(tmp_path):
    row = {'read': {'trades': []}, 'sha256': 'a'*64}
    raw = (json.dumps(row, sort_keys=True, separators=(',', ':'))+'\n').encode()
    path = tmp_path/'exact.json'
    write_new(path, row, max_bytes=len(raw))
    assert read_bytes(path, len(raw)) == raw
    with pytest.raises(ValueError, match='recording_file_budget'):
        read_bytes(path, len(raw)-1)
    refused = tmp_path/'refused.json'
    with pytest.raises(ValueError, match='recording_file_budget'):
        write_new(refused, row, max_bytes=len(raw)-1)
    assert not refused.exists()


def test_history_writer_refuses_before_publishing_or_anchoring(tmp_path, monkeypatch, large_trades):
    from weather.market import lfc_campaign_history as history
    monkeypatch.setattr(history, 'ACCOUNT_EVIDENCE_JSON_LIMIT', 128)
    with account_lease(MAKER, backend=Mutexes()):
        with pytest.raises(ValueError, match='recording_file_budget'):
            recovery(tmp_path, large_trades)
        assert not list((tmp_path/'history-recoveries').glob('*.json'))
        assert Ledger.open(tmp_path/'ledger.jsonl', clock=Clock().now).history_recoveries == []


def test_file_growth_after_stat_still_obeys_streaming_budget(tmp_path, monkeypatch):
    path = tmp_path/'growing.json'
    path.write_bytes(b'{}')
    monkeypatch.setattr(Path, 'open', lambda *_a, **_k: io.BytesIO(b'x'*17))
    with pytest.raises(ValueError, match='recording_file_budget'):
        read_bytes(path, 16)
