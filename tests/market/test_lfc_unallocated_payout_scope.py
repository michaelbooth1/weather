"""Invented lots and decoded native-burn operands. No venue or retained records."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from weather.market import lfc_f2_economics as economics, lfc_f2_reward_estimate
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_income import unknown_cash


NOW = datetime(2020, 1, 2, 1, 0, 0, 500000, tzinfo=timezone.utc)
SECOND = int(NOW.timestamp())


def book_with_burn(token='71', when=SECOND + 1):
    history = [dict(event='leg_intent', intent_key='lot', recorded_at_utc=NOW.isoformat()),
               dict(event='leg_terminal', order_id='O', sequence=1)]
    lot = dict(session_id='S', token_id='71', condition_id='selected', order_id='O',
               status='terminal', size_matched='3', price='.4')
    ledger = SimpleNamespace(rows=history, legs={'lot': lot}, baselines=[])
    book = CapitalBook(ledger)
    # One decoded native bundle can cover several contracts under a single activity.
    activity = dict(id='R', type='REDEEM', timestamp=when, condition_id='nominal-other',
                    token_id='nominal-other', cash_native=5_000_000, native_redemption=dict(
                        transaction_hash='invented-tx',
                        positions=[dict(token_id=token, quantity='5', cash_native=5_000_000)]))
    book.activities['R'] = activity
    book.activity_sequences['R'] = 2
    book.activity_transactions['R'] = 'invented-tx'
    book.redeem(activity, 2)
    return ledger, book


def test_normal_report_keeps_possible_burn_and_credit_separate(monkeypatch):
    ledger, book = book_with_burn()
    assert book.allocations == []
    assert book.redemptions['R']['unallocated'][0]['token_id'] == '71'
    assert unknown_cash(book)['blockers'] == ['R']
    assert book.lots['lot']['remaining_basis'] == 1_200_000
    monkeypatch.setattr(economics, 'CapitalBook', lambda _: book)
    monkeypatch.setattr(book, 'figures', lambda: {'blockers': unknown_cash(book)['blockers']})
    monkeypatch.setattr(lfc_f2_reward_estimate, 'summary', lambda *_: {})
    result = economics.measured(ledger, ['S'])
    assert result['settlement']['unknown_payouts'] == ['R']
    warning, = result['settlement']['possible_unallocated_redemptions']
    assert warning['activity_id'] == 'R' and warning['token_ids'] == ['71']
    assert warning['allocated_cash_native'] == warning['returned_principal_native'] == 0
    assert warning['cost_basis_released_native'] == 0
    assert result['settlement']['redemptions'] == result['settlement']['cost_basis_releases'] == []
    assert result['campaign_capital']['blockers'] == ['R']
    unrelated = economics.measured(ledger, ['unrelated'])['settlement']
    assert unrelated['unknown_payouts'] == []
    assert 'possible_unallocated_redemptions' not in unrelated


@pytest.mark.parametrize(('token', 'when', 'sessions', 'expected'), [
    ('71', SECOND, {'S'}, {'R': ['71']}), ('71', SECOND - 1, {'S'}, {}),
    ('99', SECOND + 1, {'S'}, {}), ('71', SECOND + 1, {'another'}, {}),
])
def test_token_membership_and_coarse_clock(token, when, sessions, expected):
    _, book = book_with_burn(token, when)
    assert economics.possible_unallocated_payouts(book, sessions) == expected


def test_unproved_api_rows_gain_no_new_authority():
    _, book = book_with_burn()
    del book.activities['R']['native_redemption']
    assert economics.possible_unallocated_payouts(book, {'S'}) == {}


@pytest.mark.parametrize('mode', ['oversized', 'before_intent', 'same_second', 'another_token', 'two_sessions',
                                  'partly_allocated', 'fully_allocated'])
def test_native_burn_session_warning_and_immutable_supplements(tmp_path, monkeypatch, mode):
    from datetime import timedelta
    from pathlib import Path

    from tests.market.test_lfc_campaign import Mutexes
    from tests.market.test_lfc_f2_capital import MAKER, NOW as LEDGER_TIME, activity, install, ledger_at
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    from tests.market.test_lfc_f2_native import BLOCK, TX, log, proof
    from tests.market.test_lfc_redemption_native import event
    from weather.market import lfc_campaign_owner_close
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_capital import normalize_activity, record_activity
    from weather.market.lfc_recording_io import file_sha, strict_json, write_new
    from weather.market.lfc_redemption_native import MODULES, PM, POSITION, SINGLE, ZERO

    ledger = ledger_at(tmp_path)
    latest = LEDGER_TIME + timedelta(seconds=2)
    stamp = int(latest.timestamp())
    if mode == 'before_intent':
        stamp = int(LEDGER_TIME.timestamp()) - 1
    if mode == 'same_second':
        ledger.clock = lambda: LEDGER_TIME + timedelta(microseconds=500_000)
        stamp = int(LEDGER_TIME.timestamp())
    condition = '0x' + '1' * 64
    five_quantity = mode == 'fully_allocated'
    session_ids = ['A', 'B'] if mode == 'two_sessions' else ['A']
    for sid in session_ids:
        ledger.record('session_start', session_id=sid, counted=True,
                      condition_id=condition, autostart_attempt_id='attempt-' + sid)
        legs = [(sid+'-main', '101', '5' if five_quantity else ('1' if sid == 'B' else '3'))]
        if mode == 'partly_allocated':
            legs.append((sid+'-second', '102', '5'))
        for key, token, qty in legs:
            oid = 'order-' + key
            ledger.intent(session_id=sid, intent_key=key, condition_id=condition, token_id=token,
                          size=qty, price='.4', fee_rate_bps='0')
            ledger.ack(key, oid)
            ledger.terminal(oid, dict(id=oid, status='MATCHED', size_matched=qty), source='fixture')
        ledger.record('session_end', session_id=sid)

    token = 103 if mode == 'another_token' else 101
    source = {**activity(cash='5', size='5', token=str(token), tx=TX),
              'timestamp': stamp, 'condition_id': condition, 'outcome_index': 999}
    native = proof([source], incoming=5_000_000)
    module = sorted(MODULES)[0]
    logs = []
    for position, payout in [(token, 5_000_000)] + ([(102, 0)] if mode == 'partly_allocated' else []):
        for contract, signature, indexed, amounts in [
            (PM, SINGLE, [MAKER, MAKER, module], [position, 5_000_000]),
            (PM, SINGLE, [module, module, ZERO], [position, 5_000_000]),
            (module, POSITION, [MAKER, position, MAKER], [5_000_000, payout]),
        ]:
            logs.append(event(contract, signature, indexed, ['uint256', 'uint256'], amounts, len(logs)))
    logs.append(log(5_000_000, index=len(logs)))
    native.update(receipt=rpc_packet(dict(transactionHash=TX, blockHash=BLOCK, blockNumber='0x123',
                                          status='0x1', logs=logs)), ctf_views={})

    with account_lease(MAKER, backend=Mutexes()):
        install(ledger, cash='295')
        ledger.clock = lambda: latest
        record_activity(ledger, source, native_evidence=native)
    key = normalize_activity(source)['id']
    written = ledger.path.read_bytes()
    book = CapitalBook(ledger)
    assert book.activities[key]['native_redemption']
    assert book.lots['A-main']['remaining_basis'] == (0 if five_quantity else 1_200_000)

    originals = {}
    for sid in session_ids:
        original = tmp_path / (sid + '.json')
        write_new(original, {'session_id': sid, 'outcome': {'f2_session': True}})
        originals[sid] = original
    state_root = tmp_path / 'state'
    state = SimpleNamespace(root=state_root, ledger=ledger,
        claims=lambda: [{'attempt_id': 'attempt-' + sid} for sid in session_ids],
        save=lambda rel, row: write_new(state_root / rel, row),
        read=lambda path: strict_json(Path(path).read_bytes()))
    def retained_result(claim):
        original = originals[claim['attempt_id'].split('-')[-1]]
        return strict_json(original.read_bytes()), file_sha(original), {}
    state.retained_result = retained_result
    monkeypatch.setattr(lfc_campaign_owner_close, 'binding', lambda *a: None)
    monkeypatch.setattr(lfc_f2_reward_estimate, 'summary', lambda *a: {})
    rails = {'campaign_estimate': {'evidence_gaps': []}}
    monkeypatch.setattr(lfc_f2_reward_estimate, 'retained_summary', lambda *a, **kw: (rails, {}))
    runtime = SimpleNamespace(state=state, pilot_root=tmp_path, control_root=tmp_path/'control',
                              clock=SimpleNamespace(now=lambda: latest))

    expected_warning = mode in {'oversized', 'same_second', 'two_sessions', 'partly_allocated'}
    before = {sid: original.read_bytes() for sid, original in originals.items()}
    economics.publish_supplements(runtime)
    economics.publish_supplements(runtime)
    for sid in session_ids:
        output, = tmp_path.glob(sid+'.e-*.json')
        body = strict_json(output.read_bytes())
        report = economics.measured(ledger, [sid])['settlement']
        assert body['measured']['settlement'] == report and originals[sid].read_bytes() == before[sid]
        warnings = report.get('possible_unallocated_redemptions', [])
        if expected_warning:
            warning, = warnings
            assert (warning['activity_id'], warning['token_ids'], warning['attribution']) == (key, ['101'], 'possible')
            assert warning['allocated_cash_native'] == warning['returned_principal_native'] == 0
            assert warning['cost_basis_released_native'] == 0 and report['unknown_payouts'] == [key]
        else:
            assert warnings == [] and report['unknown_payouts'] == []
        allocations = report['cost_basis_releases']
        assert sum(row['payout_native'] for row in allocations) == (5_000_000 if five_quantity else 0)
        assert sum(row['cost_basis_released_native'] for row in allocations) == (
            2_000_000 if (five_quantity or mode == 'partly_allocated') else 0)
    assert ledger.path.read_bytes() == written
    assert CapitalBook(ledger).figures() == book.figures()
