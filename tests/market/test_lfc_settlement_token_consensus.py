"""Invented positional references; all file activity uses pytest's private directory."""
import json
from copy import copy
from datetime import datetime, timezone

import pytest

from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_recording_io import retained
from weather.market.lfc_settlement_record import (
    SETTLEMENT_SCHEMA, SettlementScopeUnproven, load_settlements, record_settlement,
    resolution_result, validate_settlement_row,
)
from weather.market.mm_stage2_hold import canonical_bytes, digest


CID = '0x' + '1' * 64
NOW = datetime(2020, 1, 1, tzinfo=timezone.utc)


def payload(data, **metadata):
    return json.dumps(dict(data=data, **metadata)).encode()


def group(name, left, right):
    return [dict(condition_id=CID, structural_condition_id=name, module='invented',
                 outcome_index=i, token_id=token) for i, token in enumerate((left, right))]


RESOLUTION = payload([dict(condition_id=CID, status='resolved', payouts=[1_000_000, 0])])
ORIGINAL = group('a', '101', '202')
SWAPPED = group('b', '202', '101')


def historical_row():
    return dict(schema_version=SETTLEMENT_SCHEMA, kind='lfc_venue_settlement',
                condition_id=CID, terminal=True, winning_token_id='101',
                token_ids=['101', '202'], traded_token_ids=['101', '202'],
                reason=None, observed_at_utc=NOW.isoformat(), resolution=retained(RESOLUTION),
                tokens=retained(payload(ORIGINAL + SWAPPED)))


@pytest.mark.parametrize('groups', [(ORIGINAL, SWAPPED), (SWAPPED, ORIGINAL)])
@pytest.mark.parametrize('traded', [('101',), ('101', '202')])
def test_eligible_groups_must_agree_in_order(groups, traded):
    with pytest.raises(SettlementScopeUnproven, match='ambiguous_matching_token_pair'):
        resolution_result(CID, RESOLUTION, payload(groups[0] + groups[1]), traded_tokens=traded)


@pytest.mark.parametrize('second', [
    group('b', '101', '202'), group('b', '303', '404'), list(reversed(group('b', '101', '202'))),
])
def test_confirming_or_disjoint_second_group(second):
    assert resolution_result(CID, RESOLUTION, payload(second + ORIGINAL),
                             traded_tokens=['101', '202']) == (True, '101', ['101', '202'])


def test_single_intent_does_not_identify_the_other_slot():
    with pytest.raises(SettlementScopeUnproven):
        resolution_result(CID, RESOLUTION, payload(ORIGINAL + group('b', '101', '303')),
                          traded_tokens=['101'])


@pytest.mark.parametrize('which', ['tokens', 'resolution'])
def test_explicit_pagination_cannot_certify_a_terminal(which):
    page = {'has_more': True, 'next_cursor': 'next'}
    resolution = payload(json.loads(RESOLUTION)['data'], pagination=page) if which == 'resolution' else RESOLUTION
    tokens = payload(ORIGINAL, pagination=page if which == 'tokens' else {'has_more': False})
    with pytest.raises(SettlementScopeUnproven, match='settlement_page_incomplete'):
        resolution_result(CID, resolution, tokens, traded_tokens=['101'])


@pytest.mark.parametrize('pagination', [None, {'next_cursor': None}, {'has_more': False, 'next_cursor': ''}])
def test_existing_single_envelope_encodings(pagination):
    result = resolution_result(CID, RESOLUTION, payload(ORIGINAL, pagination=pagination), traded_tokens=['101'])
    assert result == (True, '101', ['101', '202'])


def test_recorder_keeps_conflicting_originals_pending(tmp_path):
    tokens = payload(ORIGINAL + SWAPPED)
    result = record_settlement(tmp_path, CID, clock=lambda: NOW, traded_tokens=['101'],
                               get=lambda path, params: RESOLUTION if path.endswith('resolutions') else tokens)
    assert (result['terminal'], result['reason'], result['winning_token_id']) == (
        False, 'ambiguous_matching_token_pair', None)
    assert result['tokens'] == retained(tokens)
    assert not (tmp_path / 'settlement' / (CID + '.json')).exists()


def test_old_ambiguous_file_is_preserved_but_cannot_authorize_new_use(tmp_path):
    directory = tmp_path / 'settlement'
    directory.mkdir()
    row = historical_row()
    target = directory / (CID + '.json')
    original = json.dumps(row).encode()
    target.write_bytes(original)
    with pytest.raises(SettlementScopeUnproven):
        load_settlements(directory, [CID])
    with pytest.raises(SettlementScopeUnproven):
        record_settlement(tmp_path, CID, clock=lambda: NOW, recover_corrupt=True,
                          get=lambda *args: pytest.fail('unexpected fetch'))
    assert target.read_bytes() == original
    assert not (directory / 'recovery').exists()


def seeded_ledger(tmp_path):
    ledger = Ledger.create(tmp_path / 'fixture.jsonl', clock=lambda: NOW, maker_address='0x' + '2' * 40)
    ledger.record('session_start', session_id='s', counted=True, condition_id=CID)
    for token in ('101', '202'):
        key, order_id = 'lot-' + token, 'fixture-' + token
        ledger.intent(session_id='s', intent_key=key, condition_id=CID, token_id=token,
                      size='3', price='.4', fee_rate_bps='0')
        ledger.ack(key, order_id)
        assert ledger.terminal(order_id, dict(id=order_id, status='MATCHED', size_matched='3'), source='fixture')
    ledger.record('session_end', session_id='s')
    return ledger


def zero_fields(evidence):
    return dict(condition_id=CID, settlement=evidence, intent_keys=['lot-202'], settlement_sha256=digest(evidence))


def book_state(ledger):
    book = CapitalBook(ledger)
    return book.losses, [(book.lots['lot-' + t]['remaining_basis'], book.lots['lot-' + t]['remaining_quantity'])
                         for t in ('101', '202')]


def test_conflict_refuses_before_append_then_unique_map_posts_from_identical_state(tmp_path):
    ledger = seeded_ledger(tmp_path)
    ambiguous = historical_row()
    unique = dict(ambiguous, tokens=retained(payload(ORIGINAL)))
    with pytest.raises(SettlementScopeUnproven, match='^ambiguous_matching_token_pair$'):
        validate_settlement_row(ambiguous, CID)
    original = ledger.path.read_bytes()
    before = book_state(ledger)
    assert before == (0, [(1_200_000, 3), (1_200_000, 3)])
    with pytest.raises(LedgerUnavailable, match='^ambiguous_matching_token_pair$'):
        ledger.record('capital_zero_resolution', **zero_fields(ambiguous))
    assert ledger.path.read_bytes() == original
    assert not ledger.capital_rows and book_state(ledger) == before
    ledger.record('capital_zero_resolution', **zero_fields(unique))
    assert book_state(ledger) == (1_200_000, [(1_200_000, 3), (0, 3)])
    assert book_state(Ledger.open(ledger.path, clock=lambda: NOW)) == book_state(ledger)


def test_historical_first_match_reopens_in_warm_and_detached_books(tmp_path):
    ledger = seeded_ledger(tmp_path)
    original = ledger.path.read_bytes()
    # Construct the old writer's canonical v0.4 row only in a fresh private clone.
    old = Ledger._row(len(ledger.rows), ledger.previous, lambda: NOW,
                      'capital_zero_resolution', zero_fields(historical_row()))
    old['schema_version'] = 'lfc_ledger_v0.4'
    posted = original + canonical_bytes(old)
    clone = tmp_path / 'legacy-copy.jsonl'
    clone.write_bytes(posted)
    reopened = Ledger.open(clone, clock=lambda: NOW)
    detached = copy(reopened)
    detached._capital_checkpoint = None
    assert book_state(reopened) == book_state(detached) == (1_200_000, [(1_200_000, 3), (0, 3)])
    assert ledger.path.read_bytes() == original and clone.read_bytes() == posted


@pytest.mark.parametrize('mode', ('conflict', 'reversed_conflict', 'incomplete', 'partial_page',
                                  'duplicate', 'migration', 'unique', 'split'))
def test_recorder_post_reopen_and_native_redemption(tmp_path, mode):
    from types import SimpleNamespace

    from tests.market.test_lfc_campaign import Mutexes
    from tests.market.test_lfc_f2_capital import MAKER, filled, install, ledger_at
    from tests.market.test_lfc_pilot import Clock
    from tests.market.test_lfc_redemption_native import paired
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_capital import record_activity
    from weather.market.lfc_capital_settlement import record_zero_payouts
    from weather.market.lfc_f2_followup import collect

    source, native, (win, lose) = paired(losing_shares=5)
    condition = source['condition_id']
    first = [dict(row, condition_id=condition) for row in group('a', win, lose)]
    reversed_pair = [dict(row, condition_id=condition) for row in group('b', lose, win)]
    disjoint = [dict(row, condition_id=condition) for row in group('other', '303', '404')]
    rows = {'conflict': first + reversed_pair, 'reversed_conflict': reversed_pair + first,
            'incomplete': first + reversed_pair[:1], 'duplicate': first + first,
            'migration': disjoint + first}.get(mode, first)
    reasons = {'conflict': 'ambiguous_matching_token_pair', 'reversed_conflict': 'ambiguous_matching_token_pair',
               'incomplete': 'incomplete_matching_token_pair', 'partial_page': 'settlement_page_incomplete'}
    tokens = payload(rows, pagination={'has_more': mode == 'partial_page'})
    payouts = [500_000, 500_000] if mode == 'split' else [1_000_000, 0]
    resolution = payload([dict(condition_id=condition, status='resolved', payouts=payouts)])
    ledger = ledger_at(tmp_path)
    filled(ledger, 'winner', token=win, condition=condition, price='.4')
    filled(ledger, 'loser', token=lose, condition=condition, size='5', price='.6')
    get = lambda path, params: resolution if path.endswith('resolutions') else tokens
    clock = Clock(ledger.clock())
    runtime = SimpleNamespace(clock=clock, pilot_root=tmp_path, state=SimpleNamespace(ledger=ledger, maker=MAKER))
    with account_lease(MAKER, backend=Mutexes()):
        install(ledger, cash='289')
        original = ledger.path.read_bytes()
        report = collect(runtime, get=get, reward_client=SimpleNamespace())
        assert report['settlement_scope_unresolved'] == int(mode in reasons)
        assert report['gaps'] == (['settlement_' + reasons[mode]] if mode in reasons else [])
        written = record_zero_payouts(ledger, tmp_path)
        if mode in reasons:
            assert written == 0 and ledger.path.read_bytes() == original
            pending, = (tmp_path / 'settlement' / 'pending' / condition).glob('*.json')
            assert json.loads(pending.read_bytes())['tokens'] == retained(tokens)
            assert CapitalBook(ledger).losses == 0
            return
        if mode == 'split':
            assert written == 0 and ledger.path.read_bytes() == original
            row = json.loads((tmp_path / 'settlement' / (condition + '.json')).read_bytes())
            assert row['terminal'] and row['winning_token_id'] is None
            return
        assert written == 1 and record_zero_payouts(ledger, tmp_path) == 0
        posted = CapitalBook(ledger)
        assert posted.losses == 3_000_000 and posted.cash_in == 0
        assert posted.lots['winner']['remaining_basis'] == 8_000_000
        assert posted.lots['loser']['remaining_quantity'] == 5
        reopened = Ledger.open(ledger.path, clock=ledger.clock)
        assert CapitalBook(reopened).figures() == posted.figures()
        record_activity(reopened, source, native_evidence=native)
        redeemed = CapitalBook(reopened)
        assert redeemed.cash_in == 20_000_000 and redeemed.returned_principal == 8_000_000
        assert redeemed.losses == 3_000_000 and redeemed.profit == 12_000_000
        assert all(lot['remaining_quantity'] == 0 for lot in redeemed.lots.values())
        assert CapitalBook(Ledger.open(ledger.path, clock=ledger.clock)).figures() == redeemed.figures()
