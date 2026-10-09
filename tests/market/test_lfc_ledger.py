"""Campaign loss ledger L (signed pre-registration section 6), wallet baselines, fail-closed state. Synthetic only.

Guards: the signed L formula (filled x price + resting x limit, no fee term, zero recovery), the post gate
L_after_cancel + reserve <= 100 with its boundary, stop-at-100 (L_filled + 38.4 > 100), mismatch halts, the
l_ledger.json snapshot, the trades reconcile by our order ids, persistence across restarts and sessions, fail-closed
on missing/empty/truncated/edited/changed-underneath state, and the T-24h/T-40min baselines.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from weather.market import lfc_constants as LFC
from weather.market import lfc_ledger as ledger_module
from weather.market.lfc_ledger import (Ledger, LedgerCap, LedgerUnavailable, band_reserve, compare_baselines,
                                       latest_baseline, leg_cost, normalize_positions, position_conditions,
                                       take_baseline, traded_shares, write_baseline)

MAKER = '0x' + 'a' * 40
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


def new(tmp_path):
    clock = Clock()
    return Ledger.create(tmp_path / 'ledger.jsonl', clock=clock, maker_address=MAKER), clock


def leg(ledger, session_id, key, *, price='.4', size='40', fee='0', order_id=None):
    ledger.intent(session_id=session_id, intent_key=key, token_id='111', condition_id='0xc', price=price, size=size,
                  fee_rate_bps=fee)
    if order_id:
        ledger.ack(key, order_id)


def test_signed_formula_filled_plus_resting_without_fee(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', price='.33', fee='0', order_id='o1')
    leg(ledger, 'S1', 'S1:2', price='.64', fee='100', order_id='o2')
    assert ledger.figures() == {'L': Decimal('38.80'), 'L_filled': 0, 'L_resting': Decimal('38.80')}
    ledger.terminal('o1', {'status': 'CANCELED', 'size_matched': '0'}, source='test')
    ledger.terminal('o2', {'status': 'MATCHED', 'size_matched': '12'}, source='test')
    assert ledger.figures() == {'L': Decimal('7.68'), 'L_filled': Decimal('7.68'), 'L_resting': 0}
    assert leg_cost({'price': '.5', 'size': '40', 'status': 'open', 'size_matched': '0'}) == (0, Decimal('20'))
    assert leg_cost({'price': '.5', 'size': '40', 'status': 'terminal', 'size_matched': '40'}) == (Decimal('20'), 0)
    assert band_reserve(40, ('.33', '.64')) == Decimal('38.80')


def test_unacknowledged_intent_stays_at_full_worst_case(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', price='.5')
    assert ledger.L() == Decimal('20') and ledger.unresolved_legs()[0]['order_id'] is None
    # A live or unreadable read never releases worst case.
    assert ledger.terminal('unknown', {'status': 'CANCELED'}, source='test') is None
    ledger.ack('S1:1', 'o1')
    assert ledger.terminal('o1', {'status': 'LIVE', 'size_matched': '0'}, source='test') is None
    assert ledger.terminal('o1', {}, source='test') is None
    assert ledger.L() == Decimal('20')


def test_persists_across_restarts_and_sessions(tmp_path):
    ledger, clock = new(tmp_path)
    for number in (1, 2):
        sid = f'S{number}'
        ledger.record('session_start', session_id=sid, counted=True)
        leg(ledger, sid, sid + ':1', order_id='o' + sid)
        ledger.terminal('o' + sid, {'status': 'MATCHED', 'size_matched': '40'}, source='test')
        ledger.record('session_end', session_id=sid, reason='fill')
        ledger = Ledger.open(tmp_path / 'ledger.jsonl', clock=clock, maker_address=MAKER)
    ledger.record('session_start', session_id='S0-x', counted=False)
    ledger.record('session_end', session_id='S0-x', reason='fixed_end')
    reopened = Ledger.open(tmp_path / 'ledger.jsonl', clock=clock, maker_address=MAKER)
    assert reopened.L() == Decimal('32') and reopened.counted_sessions() == 2 and not reopened.open_sessions()
    assert reopened.our_order_ids() == {'oS1', 'oS2'}


def test_post_gate_boundary_and_own_resting(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', price='.8', size='40', order_id='o1')  # 32 resting
    leg(ledger, 'S1', 'S1:2', price='.75', size='40', order_id='o2')  # 62 resting
    assert ledger.post_gate(reserve=Decimal('38'), cap=100) == Decimal('62')  # exactly 100 is allowed
    with pytest.raises(LedgerCap, match='l_budget_refused'):
        ledger.post_gate(reserve=Decimal('38.01'), cap=100)
    # The band's own resting legs are inside its reserve: a requote is gated on L without them.
    assert ledger.post_gate(reserve=Decimal('62'), own_resting=Decimal('62'), cap=100) == 0
    with pytest.raises(LedgerCap, match='l_budget_refused'):
        ledger.post_gate(reserve=Decimal('38'), cap=Decimal('99.99'))


def test_stop_at_100_uses_filled_plus_minimum_feasible_reserve(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', price='.5', size='123.2', order_id='o1')
    ledger.terminal('o1', {'status': 'MATCHED', 'size_matched': '123.2'}, source='test')  # 61.6 + 38.4 = 100
    assert ledger.L_filled() == Decimal('61.6') and ledger.stop_reason() is None
    leg(ledger, 'S1', 'S1:2', price='.5', size='1', order_id='o2')
    ledger.terminal('o2', {'status': 'MATCHED', 'size_matched': '.2'}, source='test')  # 61.7 + 38.4 > 100
    assert ledger.stop_reason() == 'l_stop_at_cap'
    with pytest.raises(LedgerCap, match='l_stop_at_cap'):
        ledger.post_gate(reserve=0, cap=100)


def test_halt_and_mismatch_stop_for_good_across_restarts(tmp_path):
    ledger, clock = new(tmp_path)
    ledger.record('halt', reason='test')
    assert ledger.stop_reason() == 'ledger_halted'
    ledger.record('mismatch', order_id='o', recorded='0', observed='1', source='test', kind='test')
    reopened = Ledger.open(ledger.path, clock=clock, maker_address=MAKER)
    assert reopened.stop_reason() == 'l_reconciliation_mismatch'
    with pytest.raises(LedgerCap, match='l_reconciliation_mismatch'):
        reopened.post_gate(reserve=1, cap=100)


def test_second_terminal_read_that_disagrees_is_a_mismatch(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', order_id='o1')
    ledger.terminal('o1', {'status': 'CANCELED', 'size_matched': '0'}, source='session')
    ledger.terminal('o1', {'status': 'CANCELED', 'size_matched': '0'}, source='reconcile')
    assert ledger.stop_reason() is None
    ledger.terminal('o1', {'status': 'MATCHED', 'size_matched': '5'}, source='reconcile')
    assert ledger.stop_reason() == 'l_reconciliation_mismatch'


def test_trades_reconcile_counts_only_our_order_ids(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', order_id='o1')
    ledger.terminal('o1', {'status': 'MATCHED', 'size_matched': '40'}, source='session')
    trades = [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o1', 'matched_amount': '25'},
                                                       {'order_id': 'owner', 'matched_amount': '99'}]},
              {'status': 'MINED', 'taker_order_id': 'o1', 'size': '15'},
              {'status': 'FAILED', 'maker_orders': [{'order_id': 'o1', 'matched_amount': '40'}]}]
    assert traded_shares(trades, {'o1'}) == {'o1': '40'}
    assert ledger.reconcile_trades(trades, source='test') == ({'o1': '40'}, [])
    traded, found = ledger.reconcile_trades(trades[:1], source='test')
    assert found[0]['kind'] == 'trades_vs_size_matched' and ledger.stop_reason() == 'l_reconciliation_mismatch'


def test_snapshot_file_tracks_the_history(tmp_path):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', price='.5', order_id='o1')
    snap = json.loads((tmp_path / 'l_ledger.json').read_bytes())
    assert snap['schema_version'] == 'lfc_l_ledger_v0.1' and Decimal(snap['L']) == Decimal(snap['L_resting']) == 20
    assert snap['history_rows'] == len(ledger.rows) and snap['our_order_ids'] == ['o1']
    assert snap['history_last_sha256'] == ledger.previous


def test_create_once_and_account_binding(tmp_path):
    ledger, clock = new(tmp_path)
    with pytest.raises(LedgerUnavailable, match='exists'):
        Ledger.create(ledger.path, clock=clock, maker_address=MAKER)
    with pytest.raises(LedgerUnavailable, match='account'):
        Ledger.open(ledger.path, clock=clock, maker_address='0x' + 'b' * 40)


@pytest.mark.parametrize('damage', ['missing', 'empty', 'truncated', 'edited', 'reordered', 'not_json'])
def test_unreadable_ledger_fails_closed(tmp_path, damage):
    ledger, clock = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', order_id='o1')
    raw = ledger.path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if damage == 'missing':
        ledger.path.unlink()
    else:
        ledger.path.write_bytes({'empty': b'', 'truncated': raw[:-1],
                                 'edited': raw.replace(b'"price":"0.4"', b'"price":"0.1"').replace(b'"price":".4"', b'"price":".1"'),
                                 'reordered': lines[0] + lines[2] + lines[1] + lines[3],
                                 'not_json': raw + b'garbage\n'}[damage])
    with pytest.raises(LedgerUnavailable):
        Ledger.open(ledger.path, clock=clock, maker_address=MAKER)


def test_edit_of_a_value_breaks_the_chain(tmp_path):
    ledger, clock = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    leg(ledger, 'S1', 'S1:1', price='.4', order_id='o1')
    rows = [json.loads(line) for line in ledger.path.read_bytes().splitlines()]
    rows[2]['price'] = '0.1'
    ledger.path.write_bytes(b''.join(json.dumps(r, sort_keys=True, separators=(',', ':')).encode() + b'\n' for r in rows))
    with pytest.raises(LedgerUnavailable, match='chain'):
        Ledger.open(ledger.path, clock=clock)


def test_changed_underneath_or_missing_refuses_writes(tmp_path):
    ledger, clock = new(tmp_path)
    other = Ledger.open(ledger.path, clock=clock)
    other.record('session_start', session_id='S1', counted=True)
    with pytest.raises(LedgerUnavailable, match='changed_underneath'):
        ledger.record('session_start', session_id='S2', counted=True)
    ledger.path.unlink()
    with pytest.raises(LedgerUnavailable, match='missing'):
        other.record('session_start', session_id='S3', counted=True)


def test_failed_write_leaves_state_unchanged(tmp_path, monkeypatch):
    ledger, _ = new(tmp_path)
    ledger.record('session_start', session_id='S1', counted=True)
    before = ledger.path.read_bytes()

    def broken(self, *args, **kwargs):
        raise OSError('disk')
    monkeypatch.setattr(type(ledger.path), 'open', broken)
    with pytest.raises(LedgerUnavailable, match='write_failed'):
        leg(ledger, 'S1', 'S1:1')
    monkeypatch.undo()
    assert ledger.L() == 0 and not ledger.legs and ledger.path.read_bytes() == before


@pytest.mark.parametrize('event,fields', [
    ('leg_intent', dict(session_id='nope', intent_key='k', token_id='1', condition_id='c', price='.1', size='1',
                        fee_rate_bps='0')),
    ('leg_ack', dict(intent_key='missing', order_id='o')),
    ('leg_terminal', dict(order_id='missing', size_matched='0')),
    ('session_end', dict(session_id='missing')),
    ('genesis', {}),
])
def test_out_of_scope_transitions_refused(tmp_path, event, fields):
    ledger, _ = new(tmp_path)
    with pytest.raises(LedgerUnavailable):
        ledger.record(event, **fields)
    assert len(ledger.rows) == 1


def baseline(label, at, positions=(), orders=()):
    return take_baseline(label=label, now=at, maker_address=MAKER, positions=list(positions), open_orders=list(orders),
                         available_collateral='500')


def test_baselines_exclude_preexisting_positions(tmp_path):
    ledger, clock = new(tmp_path)
    held = [{'asset': 'old-token', 'conditionId': '0xOLD', 'size': '10'}]
    t24 = baseline('t24', NOW - timedelta(hours=24), held)
    t40 = baseline('t40', NOW - timedelta(minutes=40), held)
    for value in (t24, t40):
        write_baseline(tmp_path, value, ledger)
    assert latest_baseline(tmp_path, ledger, 't24') == t24
    ok = compare_baselines(t24, t40, now=NOW, current_positions=held + [{'asset': 'pilot-token', 'size': '40'}],
                           current_open_orders=[], ledger_tokens={'pilot-token'}, maker_address=MAKER)
    assert ok == []
    assert t40['position_conditions'] == ['0xold']
    bad = compare_baselines(t24, t40, now=NOW, current_positions=[{'asset': 'old-token', 'size': '5'}],
                            current_open_orders=[{'id': 'x'}], ledger_tokens=set(), maker_address=MAKER)
    assert bad == ['foreign_open_orders_at_start', 'wallet_activity_outside_pilot']


@pytest.mark.parametrize('age24,age40,code', [(timedelta(hours=19), timedelta(minutes=40), 'baseline_t24_age'),
                                              (timedelta(hours=31), timedelta(minutes=40), 'baseline_t24_age'),
                                              (timedelta(hours=24), timedelta(minutes=91), 'baseline_t40_age'),
                                              (timedelta(hours=24), timedelta(minutes=-1), 'baseline_t40_age')])
def test_baseline_ages(age24, age40, code):
    refusals = compare_baselines(baseline('t24', NOW - age24), baseline('t40', NOW - age40), now=NOW,
                                 current_positions=[], current_open_orders=[], ledger_tokens=set(), maker_address=MAKER)
    assert refusals == [code]


def test_baseline_with_open_orders_or_other_account_refuses():
    t24 = baseline('t24', NOW - timedelta(hours=24), orders=[{'id': 'owner-order'}])
    t40 = baseline('t40', NOW - timedelta(minutes=40))
    refusals = compare_baselines(t24, t40, now=NOW, current_positions=[], current_open_orders=[], ledger_tokens=set(),
                                 maker_address='0x' + 'c' * 40)
    assert 'baseline_foreign_open_orders' in refusals and 'baseline_account_differs_t24' in refusals


def test_baseline_file_tamper_and_missing_fail_closed(tmp_path):
    ledger, _ = new(tmp_path)
    with pytest.raises(LedgerUnavailable, match='baseline_missing_t24'):
        latest_baseline(tmp_path, ledger, 't24')
    name, _ = write_baseline(tmp_path, baseline('t24', NOW - timedelta(hours=24)), ledger)
    (tmp_path / name).write_bytes((tmp_path / name).read_bytes().replace(b'500', b'501'))
    with pytest.raises(LedgerUnavailable, match='baseline_hash'):
        latest_baseline(tmp_path, ledger, 't24')


def test_positions_reader_paginates_without_credentials():
    pages = [[{'asset': str(i), 'size': '1'} for i in range(2)], [{'asset': '9', 'size': '0'}]]
    seen = []

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self, _limit):
            return json.dumps(self.body).encode()

        def close(self):
            pass

    def opener(request, timeout):
        seen.append(request.full_url)
        assert 'Authorization' not in request.headers
        return Response(pages[len(seen) - 1])
    rows = ledger_module.fetch_account_positions(MAKER, opener=opener, page_size=2)
    assert len(rows) == 3 and len(seen) == 2 and 'offset=2' in seen[1]
    assert normalize_positions(rows) == {'0': '1', '1': '1'}


def test_budget_constant_is_one_hundred():
    assert LFC.BUDGET_PUSD == Decimal('100')


def test_session0_compares_against_t40_only():
    t40 = baseline('t40', NOW - timedelta(minutes=40))
    assert compare_baselines(None, t40, now=NOW, current_positions=[], current_open_orders=[], ledger_tokens=set(),
                             maker_address=MAKER) == []


def test_position_conditions_fail_closed_without_a_condition():
    assert position_conditions([{'conditionId': '0xA', 'size': '1'}, {'conditionId': '0xB', 'size': '0'}]) == ['0xa']
    with pytest.raises(ValueError, match='position_without_condition'):
        position_conditions([{'asset': '1', 'size': '1'}])
