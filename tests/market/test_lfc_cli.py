"""Live-fill calibration owner commands: pure start gates, flags, reconcile, close-out and cancel-ours, fakes only.

Guards: the signed start refusals (earliest start, 23:50Z hard stop, last start date, one counted session per
owner-local date, session 0 passed first, 8 sessions, stop-at-100, open orders), the T-40-only baseline of session 0,
session-0 flags refused without --session0, reconcile closing a crashed session (S0 run 0c) with its session_end.json
and notification, trades mismatches surfaced, and cancel-ours never touching a foreign order.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from weather.market import lfc_constants as LFC
from weather.market.lfc_cli import (cancel_ours, check_flags, classify_open_orders, close_crashed, close_out,
                                    finish_session, load_conditions, parser, reconcile_ledger, session0_passed,
                                    session_directory, session_identity, start_gates)
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.lfc_pilot import PilotProfile

MAKER = '0x' + 'a' * 40
NOW = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
S0_NOW = datetime(2026, 10, 12, 17, tzinfo=timezone.utc)


def ledger_with_baselines(tmp_path, *, now=NOW, t24=True):
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: now, maker_address=MAKER)
    labels = (('t24', timedelta(hours=24)), ('t40', timedelta(minutes=40))) if t24 else (('t40', timedelta(minutes=40)),)
    for label, age in labels:
        write_baseline(tmp_path, take_baseline(label=label, now=now - age, maker_address=MAKER, positions=[],
                                               open_orders=[], available_collateral='500'), ledger)
    return ledger


def pass_session0(ledger, *, reason='fixed_end', cleanup_ok=True, run='0a'):
    sid = f'S0{run[1]}-x{len(ledger.sessions)}'
    ledger.record('session_start', session_id=sid, counted=False, session_number=0, session0_run=run)
    ledger.record('session_end', session_id=sid, reason=reason, cleanup_ok=cleanup_ok)


def gates(ledger, tmp_path, *, now=NOW, profile=None, open_orders=(), positions=()):
    return start_gates(ledger=ledger, now=now, profile=profile or PilotProfile(), root=tmp_path, maker_address=MAKER,
                       open_orders=list(open_orders), positions=list(positions))


def counted(ledger, sid, *, local_date, matched='0'):
    ledger.record('session_start', session_id=sid, counted=True, owner_local_date=local_date)
    ledger.intent(session_id=sid, intent_key=sid + ':1', token_id='1', condition_id='c', price='.5', size='1',
                  fee_rate_bps='0')
    ledger.ack(sid + ':1', 'o' + sid)
    ledger.terminal('o' + sid, {'status': 'CANCELED', 'size_matched': matched}, source='test')
    ledger.record('session_end', session_id=sid, reason='fixed_end', cleanup_ok=True)


def test_clean_state_passes_once_session0_has_passed(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    assert gates(ledger, tmp_path) == ['session0_not_passed']
    pass_session0(ledger)
    assert gates(ledger, tmp_path) == []


@pytest.mark.parametrize('reason,cleanup_ok,run', [('foreign_open_order', True, '0b'), ('fixed_end', False, '0a'),
                                                   ('heartbeat_stale', True, '0a')])
def test_session0_pass_needs_a_clean_fixed_end_0a(tmp_path, reason, cleanup_ok, run):
    ledger = ledger_with_baselines(tmp_path)
    pass_session0(ledger, reason=reason, cleanup_ok=cleanup_ok, run=run)
    assert not session0_passed(ledger) and 'session0_not_passed' in gates(ledger, tmp_path)


def test_dates_refuse_counted_sessions_but_not_session0(tmp_path):
    early = datetime(2026, 10, 14, 17, tzinfo=timezone.utc)
    ledger = ledger_with_baselines(tmp_path, now=early)
    pass_session0(ledger)
    assert gates(ledger, tmp_path, now=early) == ['before_earliest_start']
    assert gates(ledger, tmp_path, now=early, profile=PilotProfile(session0=True, run='0a')) == []
    late = NOW.replace(hour=18)
    assert 'past_hard_stop_2350z' in gates(ledger, tmp_path, now=late)


def test_session0_needs_only_the_t40_baseline(tmp_path):
    ledger = ledger_with_baselines(tmp_path, now=S0_NOW, t24=False)
    assert gates(ledger, tmp_path, now=S0_NOW, profile=PilotProfile(session0=True, run='0e')) == []
    assert 'baseline_missing_t24' in gates(ledger, tmp_path, now=S0_NOW + timedelta(days=3))


def test_missing_baseline_and_foreign_orders_refuse(tmp_path):
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: NOW, maker_address=MAKER)
    assert 'baseline_missing_t24' in gates(ledger, tmp_path)
    ledger = ledger_with_baselines(tmp_path / 'b')
    assert 'foreign_open_orders_at_start' in gates(ledger, tmp_path / 'b', open_orders=[{'id': 'x'}])
    assert 'wallet_activity_outside_pilot' in gates(ledger, tmp_path / 'b', positions=[{'asset': 'z', 'size': '3'}])


def test_one_counted_session_per_owner_local_date(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    pass_session0(ledger)
    counted(ledger, 'S1', local_date='2026-10-20')
    assert gates(ledger, tmp_path) == ['local_date_already_used']
    assert gates(ledger, tmp_path, now=NOW + timedelta(days=1, minutes=-30)) != ['local_date_already_used']
    # A session started 2026-10-21T02:00Z is still 10-20 in Toronto.
    assert 'local_date_already_used' in gates(ledger, tmp_path, now=datetime(2026, 10, 21, 2, tzinfo=timezone.utc))


def test_open_session_unresolved_leg_cap_and_stop_refuse(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    pass_session0(ledger)
    ledger.record('session_start', session_id='S1', counted=True, owner_local_date='2026-10-01')
    assert 'ledger_open_session_needs_reconcile' in gates(ledger, tmp_path)
    ledger.intent(session_id='S1', intent_key='S1:1', token_id='1', condition_id='c', price='.5', size='40',
                  fee_rate_bps='0')
    ledger.ack('S1:1', 'o1')
    ledger.record('session_end', session_id='S1', reason='exception')
    assert gates(ledger, tmp_path) == ['ledger_unresolved_legs_need_reconcile']
    ledger.terminal('o1', {'status': 'CANCELED', 'size_matched': '0'}, source='test')
    for number in range(2, LFC.MAX_SESSIONS + 1):
        counted(ledger, f'S{number}', local_date=f'2026-10-0{number}')
    assert ledger.counted_sessions() == LFC.MAX_SESSIONS
    assert gates(ledger, tmp_path) == ['session_cap']
    ledger.record('halt', reason='test')
    assert 'ledger_halted' in gates(ledger, tmp_path, profile=PilotProfile(session0=True, run='0a'))


def test_session_identity_and_directories(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    sid, numbering = session_identity(ledger, NOW, profile=PilotProfile())
    assert sid.startswith('S1-') and numbering == {'session_number': 1, 'counted': True}
    ledger.record('session_start', session_id=sid, counted=True)
    ledger.record('session_end', session_id=sid, reason='no_post')
    assert session_identity(ledger, NOW + timedelta(seconds=1), profile=PilotProfile())[0].startswith('S1-')
    s0 = PilotProfile(session0=True, run='0c')
    sid0, numbering0 = session_identity(ledger, NOW, profile=s0)
    assert sid0.startswith('S0c-') and numbering0 == {'session_number': 0, 'counted': False}
    first = session_directory(tmp_path, sid0, profile=s0)
    assert first == tmp_path / 'session0' / '0c'
    first.mkdir(parents=True)
    assert session_directory(tmp_path, sid0, profile=s0) == tmp_path / 'session0' / ('0c-' + sid0)
    assert session_directory(tmp_path, sid, profile=PilotProfile()) == tmp_path / f'session-{sid}'


def test_flags_session0_requires_run_and_scope_files():
    assert check_flags(parser().parse_args(['live'])).session0 is False
    for argv, code in ((['live', '--run', '0a'], 'without_session0'),
                       (['live', '--event-slug', 'x'], 'without_session0'),
                       (['preflight', '--session0', '--event-slug', 'x'], 'requires_run'),
                       (['live', '--session0', '--run', '0a', '--event-slug', 'x'], 'extra_conditions')):
        with pytest.raises(ValueError, match=code):
            check_flags(parser().parse_args(argv))
    args = parser().parse_args(['live', '--session0', '--run', '0d', '--event-slug', 'a', '--event-slug', 'b',
                                '--extra-conditions', 'x.json', '--shadow-scope', 'y.json'])
    assert check_flags(args).run == '0d' and args.event_slug == ['a', 'b']
    with pytest.raises(SystemExit):
        parser().parse_args(['live', '--session0', '--run', '0z'])
    with pytest.raises(SystemExit):
        parser().parse_args(['live', '--force-limit', 'dead_man'])


def test_condition_file_shapes(tmp_path):
    (tmp_path / 'a.json').write_text('["0xAB", "0x2"]')
    (tmp_path / 'b.json').write_text('{"conditions": []}')
    (tmp_path / 'c.json').write_text('{"x": 1}')
    assert load_conditions(tmp_path / 'a.json')[0] == ['0xab', '0x2']
    assert load_conditions(tmp_path / 'b.json')[0] == []
    with pytest.raises(ValueError):
        load_conditions(tmp_path / 'c.json')


class FakeVenue:
    def __init__(self, rows, orders, trades=()):
        self.rows, self.orders, self.cancelled, self._trades = rows, orders, [], list(trades)

    def open_orders(self):
        return [r for r in self.rows if r['id'] not in self.cancelled]

    def order(self, oid):
        return self.orders[oid]

    def trades(self):
        return self._trades

    def cancel(self, oid):
        self.cancelled.append(oid)
        return {'canceled': [oid]}


def crashed(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    ledger.record('session_start', session_id='S0c-1', counted=False, session_number=0, session0_run='0c',
                  directory='session0/0c')
    for key, oid in (('S0c-1:1', 'o1'), ('S0c-1:2', 'o2')):
        ledger.intent(session_id='S0c-1', intent_key=key, token_id='1', condition_id='c', price='.5', size='40',
                      fee_rate_bps='0')
        ledger.ack(key, oid)
    return ledger


def test_reconcile_waits_while_our_order_rests(tmp_path):
    ledger = crashed(tmp_path)
    venue = FakeVenue([{'id': 'o2'}], {'o1': {'status': 'CANCELED', 'size_matched': '0'}})
    report, _ = reconcile_ledger(ledger, venue)
    assert report['resolved_order_ids'] == ['o1'] and report['our_open_orders'] == ['o2']
    assert report['closed_sessions'] == [] and ledger.open_sessions() == ['S0c-1'] and ledger.L() == Decimal(20)


def test_reconcile_closes_a_crashed_run_and_writes_its_session_end(tmp_path):
    ledger = crashed(tmp_path)
    trades = [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o2', 'matched_amount': '40'}]}]
    venue = FakeVenue([], {'o1': {'status': 'CANCELED', 'size_matched': '0'},
                           'o2': {'status': 'MATCHED', 'size_matched': '40'}}, trades)
    report, rows = reconcile_ledger(ledger, venue)
    assert report['closed_sessions'] == ['S0c-1'] and report['mismatches'] == [] and ledger.L() == Decimal(20)
    notes = []
    [summary] = close_crashed(tmp_path, ledger, report['closed_sessions'], rows,
                              notifier=lambda root, s: notes.append(s) or {'toast_delivered': True})
    body = json.loads((tmp_path / 'session0' / '0c' / 'session_end.json').read_bytes())
    assert body['reason'] == 'reconciled_after_crash' and body['session0_run'] == '0c'
    assert body['L_filled'] == '20.0' and body['fills'][1]['size_matched'] == '40'
    assert body['notification'] == {'toast_delivered': True} and notes[0]['session_id'] == 'S0c-1'
    assert body['open_orders'] == {'ours': [], 'foreign': []}


def test_reconcile_surfaces_a_trades_mismatch(tmp_path):
    ledger = crashed(tmp_path)
    venue = FakeVenue([], {'o1': {'status': 'CANCELED', 'size_matched': '0'},
                           'o2': {'status': 'CANCELED', 'size_matched': '0'}},
                      [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o1', 'matched_amount': '3'}]}])
    report, _ = reconcile_ledger(ledger, venue)
    assert report['mismatches'] and report['stop_reason'] == 'l_reconciliation_mismatch'


def test_finish_session_halts_at_stop_at_100(tmp_path):
    ledger = crashed(tmp_path)
    ledger.terminal('o1', {'status': 'MATCHED', 'size_matched': '40'}, source='t')
    ledger.terminal('o2', {'status': 'MATCHED', 'size_matched': '40'}, source='t')  # 40 + 38.4 <= 100
    finish_session(ledger, 'S0c-1', {'reason': 'fill', 'cleanup_ok': True})
    assert not ledger.halted
    ledger.record('session_start', session_id='S2', counted=True)
    ledger.intent(session_id='S2', intent_key='S2:1', token_id='1', condition_id='c', price='.8', size='40',
                  fee_rate_bps='0')
    ledger.ack('S2:1', 'o3')
    ledger.terminal('o3', {'status': 'MATCHED', 'size_matched': '40'}, source='t')  # 72 + 38.4 > 100
    finish_session(ledger, 'S2', {'reason': 'fill', 'cleanup_ok': True})
    assert ledger.halted and ledger.rows[-1]['reason'] == 'l_stop_at_cap'


def test_close_out_records_a_failed_notification(tmp_path):
    def failed(root, summary):
        return {'toast_delivered': False, 'toast_error': 'OSError'}
    summary = close_out(tmp_path, tmp_path / 'run', {'session_id': 'S1', 'reason': 'fixed_end'}, notifier=failed)
    body = json.loads((tmp_path / 'run' / 'session_end.json').read_bytes())
    assert body['notification']['toast_error'] == 'OSError' and summary['session_end_sha256']


def test_cancel_ours_never_touches_foreign_orders(tmp_path):
    ledger = crashed(tmp_path)
    venue = FakeVenue([{'id': 'o1'}, {'id': 'foreign'}], {})
    receipt = cancel_ours(ledger, venue)
    assert venue.cancelled == ['o1'] and receipt['foreign_left'] == ['foreign'] and receipt['remaining_ours'] == []
    assert classify_open_orders([{'id': 'o2'}, {'id': 'x'}], ledger) == (['o2'], ['x'])
