"""Live-fill calibration owner commands: pure start gates, flags, reconcile, close-out and cancel-ours, fakes only.

Guards: the signed start refusals (earliest start, 23:50Z hard stop, last start date, one counted session per
owner-local date, session 0 passed first, 8 sessions, stop-at-100, open orders), the T-40-only baseline of session 0,
session-0 flags refused without --session0, reconcile closing a crashed session (S0 run 0c) with its session_end.json
and notification, trades mismatches surfaced, cancel-ours never touching a foreign order, and the S0-1/S0-6
wallet-reader verify (session-0 spec section 5) through fake wallet_reader_client reads.
Fix round 1: session0_passed needs every required sub-run plus the owner attestation bound to the ledger with S0-2 on
0c <= 20 s (F-1), the PARTIAL positions read rule (F-4), adoption of a lost-ack intent onto its one matching venue
order and the start refusal while an intent is unresolved (F-5), the bounded 5 x 2 s trade re-read with an order
re-read at reconcile and the bounded trade reads (F-6), and the preflight ledger state (F-10).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import json

import pytest

from weather.market import lfc_constants as LFC
from weather.market.lfc_cli import (cancel_ours, check_flags, classify_open_orders, close_crashed, close_out,
                                    finish_session, ledger_state, load_conditions, parser,
                                    positions_inventory_readable, reconcile_ledger, session0_attest,
                                    session0_attestation, session0_mechanical, session0_passed,
                                    session_directory, session_identity, start_gates, run_wallet_verify,
                                    wallet_reader_report)
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


def pass_all_session0(ledger, root, *, s0_2='12.5', skip=None, attest=True):
    """Every required sub-run with its first accepted end reason, then the owner attestation (review F-1)."""
    for run, reasons in LFC.SESSION0_PASS_REASONS.items():
        if run != skip:
            pass_session0(ledger, reason=reasons[0], run=run)
    if attest and skip is None:
        session0_attest(root, ledger, s0_2_seconds=s0_2, phrase='attest session0 test', now=NOW)


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
    pass_all_session0(ledger, tmp_path)
    assert session0_passed(ledger, root=tmp_path) and gates(ledger, tmp_path) == []


def test_session0_pass_needs_every_required_sub_run_not_only_0a(tmp_path):
    # Review F-1: a clean 0a alone no longer passes; every required sub-run must pass (0f stays optional).
    assert set(LFC.SESSION0_PASS_REASONS) == {'0a', '0b', '0c', '0d', '0e', '0g'}
    assert LFC.SESSION0_PASS_REASONS['0d'] == ('heartbeat_stale', 'order_no_longer_resting')
    assert LFC.SESSION0_PASS_REASONS['0g'] == ('venue_deadman_cancelled',)
    for run in LFC.SESSION0_PASS_REASONS:
        root = tmp_path / run
        ledger = ledger_with_baselines(root)
        pass_all_session0(ledger, root, skip=run)
        assert session0_mechanical(ledger) == [run]
        with pytest.raises(RuntimeError, match='session0_runs_missing_' + run):
            session0_attest(root, ledger, s0_2_seconds='5', phrase='x', now=NOW)
        assert not session0_passed(ledger, root=root) and 'session0_not_passed' in gates(ledger, root)


@pytest.mark.parametrize('reason,cleanup_ok,run', [('foreign_open_order', True, '0a'), ('fixed_end', False, '0a'),
                                                   ('exception', True, '0b'), ('heartbeat_stale', True, '0g'),
                                                   ('venue_deadman_not_observed', True, '0g'),
                                                   ('user_stream_invalid_event', True, '0b')])
def test_session0_a_wrong_reason_or_unclean_cleanup_does_not_pass_its_run(tmp_path, reason, cleanup_ok, run):
    ledger = ledger_with_baselines(tmp_path)
    pass_session0(ledger, reason=reason, cleanup_ok=cleanup_ok, run=run)
    assert run in session0_mechanical(ledger)
    assert not session0_passed(ledger, root=tmp_path) and 'session0_not_passed' in gates(ledger, tmp_path)


def test_session0_attestation_binds_the_ledger_and_s0_2_on_0c_at_most_20_seconds(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    pass_all_session0(ledger, tmp_path, attest=False)
    assert session0_mechanical(ledger) == []
    assert session0_attestation(tmp_path, ledger) == ['session0_attestation_missing']
    assert not session0_passed(ledger, root=tmp_path)
    with pytest.raises(RuntimeError, match='session0_s0_2_above_20_seconds'):
        session0_attest(tmp_path, ledger, s0_2_seconds='20.5', phrase='x', now=NOW)
    session0_attest(tmp_path, ledger, s0_2_seconds='20', phrase='x', now=NOW)
    assert session0_passed(ledger, root=tmp_path)
    with pytest.raises(FileExistsError):
        session0_attest(tmp_path, ledger, s0_2_seconds='3', phrase='x', now=NOW)
    path = tmp_path / 'session0' / 'pass.json'
    body = json.loads(path.read_bytes())
    assert body['schema_version'] == 'lfc_session0_pass_v0.1' and body['ledger_previous_sha256'] == ledger.previous
    for change, code in (({'s0_2_seconds_0c': '21'}, 'session0_s0_2_above_20_seconds'),
                         ({'ledger_previous_sha256': '0' * 64}, 'session0_attestation_not_bound_to_ledger'),
                         ({'sessions': {**body['sessions'], '0c': 'S0c-other'}}, 'session0_attestation_run_0c'),
                         ({'ledger_sequence': 2, 'ledger_previous_sha256': ledger.row_sha256(2)},
                          'session0_attestation_run_0a')):
        path.write_text(json.dumps({**body, **change}))
        assert code in session0_attestation(tmp_path, ledger) and not session0_passed(ledger, root=tmp_path)
    path.write_text(json.dumps(body))
    ledger.record('halt', reason='later rows keep an earlier binding valid')
    assert session0_attestation(tmp_path, ledger) == []


def test_dates_refuse_counted_sessions_but_not_session0(tmp_path):
    early = datetime(2026, 10, 14, 17, tzinfo=timezone.utc)
    ledger = ledger_with_baselines(tmp_path, now=early)
    pass_all_session0(ledger, tmp_path)
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
    pass_all_session0(ledger, tmp_path)
    counted(ledger, 'S1', local_date='2026-10-20')
    assert gates(ledger, tmp_path) == ['local_date_already_used']
    assert gates(ledger, tmp_path, now=NOW + timedelta(days=1, minutes=-30)) != ['local_date_already_used']
    # A session started 2026-10-21T02:00Z is still 10-20 in Toronto.
    assert 'local_date_already_used' in gates(ledger, tmp_path, now=datetime(2026, 10, 21, 2, tzinfo=timezone.utc))


def test_open_session_unresolved_leg_cap_and_stop_refuse(tmp_path):
    ledger = ledger_with_baselines(tmp_path)
    pass_all_session0(ledger, tmp_path)
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
    scope = ['--extra-conditions', 'x.json', '--shadow-scope', 'y.json']
    for slugs in (['a', 'b'], ['a', 'b', 'B ']):  # at least three distinct owner-listed events (clarification C)
        with pytest.raises(ValueError, match='session0_requires_three_candidate_events'):
            check_flags(parser().parse_args(['live', '--session0', '--run', '0d', *scope,
                                             *[x for slug in slugs for x in ('--event-slug', slug)]]))
    args = parser().parse_args(['live', '--session0', '--run', '0d', '--event-slug', 'a', '--event-slug', 'b',
                                '--event-slug', 'c', *scope])
    assert check_flags(args).run == '0d' and args.event_slug == ['a', 'b', 'c']
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
    pauses = []
    report, _ = reconcile_ledger(ledger, venue, sleep=pauses.append)
    assert report['mismatches'] and report['stop_reason'] == 'l_reconciliation_mismatch'
    # Review F-6: the 5 x 2 s re-read before the mismatch is recorded (never a single read).
    assert pauses == [LFC.TRADE_READ_PAUSE_SECONDS] * (LFC.TRADE_READ_ATTEMPTS - 1)


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


# ----- S0-1 / S0-6 through the production-side wallet reader (fakes only) ---------------------------------------
OLD = '9' * 20  # a pre-existing position, outside every pilot token


def wallet_ledger(tmp_path, *, matched='2'):
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: S0_NOW, maker_address=MAKER)
    write_baseline(tmp_path, take_baseline(label='t40', now=S0_NOW - timedelta(minutes=40), maker_address=MAKER,
                                           positions=[{'asset': OLD, 'size': '7', 'conditionId': 'c-old'}],
                                           open_orders=[], available_collateral='500'), ledger)
    ledger.record('session_start', session_id='S0a-1', counted=False, session_number=0, session0_run='0a')
    ledger.intent(session_id='S0a-1', intent_key='S0a-1:1', token_id='11', condition_id='c', price='.5', size='20',
                  fee_rate_bps='0')
    ledger.ack('S0a-1:1', 'o1')
    ledger.terminal('o1', {'status': 'CANCELED', 'size_matched': matched}, source='test')
    ledger.record('session_end', session_id='S0a-1', reason='fixed_end', cleanup_ok=True)
    return ledger


def snapshot(tmp_path):
    return json.loads((tmp_path / 'l_ledger.json').read_bytes())


def fills(*pairs):
    return {'fills': [{'status': 'CONFIRMED', 'taker_order_id': 'someone',
                       'maker_orders': [{'order_id': oid, 'matched_amount': amount}]} for oid, amount in pairs]}


def positions(*pairs):
    return {'status': 'OBSERVED', 'positions': [{'token_id': t, 'size': s} for t, s in pairs], 'resolved_count': 0}


def report(tmp_path, ledger, *, open_orders=(), trades=None, held=None, snap=None):
    t40 = json.loads(next(tmp_path.glob('baseline-t40-*.json')).read_bytes())
    return wallet_reader_report(ledger, snapshot(tmp_path) if snap is None else snap, t40,
                                open_orders=list(open_orders) if open_orders is not None else None,
                                trades=fills(('o1', '2')) if trades is None else trades,
                                positions=positions((OLD, '7'), ('11', '2')) if held is None else held)


def test_wallet_verify_passes_when_venue_fills_reproduce_l_and_old_positions_are_unchanged(tmp_path):
    ledger = wallet_ledger(tmp_path)
    result = report(tmp_path, ledger)
    assert result['status'] == 'PASS' and result['s0_1'] == 'PASS' and result['s0_6'] == 'PASS'
    assert Decimal(result['venue_L']) == Decimal(result['l_ledger_json_L']) == Decimal('1.0')
    assert result['positions_changed_outside_pilot'] == []


def test_wallet_verify_counts_only_our_order_ids_and_ignores_failed_trades(tmp_path):
    ledger = wallet_ledger(tmp_path)
    trades = fills(('o1', '2'), ('foreign', '50'))
    trades['fills'].append({'status': 'FAILED', 'maker_orders': [{'order_id': 'o1', 'matched_amount': '9'}]})
    assert report(tmp_path, ledger, trades=trades)['status'] == 'PASS'


@pytest.mark.parametrize('venue_shares,verdict', [('2.02', 'PASS'), ('2.04', 'FAIL'), ('0', 'FAIL')])
def test_wallet_verify_l_tolerance_is_one_cent(tmp_path, venue_shares, verdict):
    ledger = wallet_ledger(tmp_path)
    assert report(tmp_path, ledger, trades=fills(('o1', venue_shares)))['s0_6'] == verdict


def test_wallet_verify_fails_on_any_open_order_or_unreadable_route(tmp_path):
    ledger = wallet_ledger(tmp_path)
    assert report(tmp_path, ledger, open_orders=[{'id': 'foreign'}])['s0_1'] == 'FAIL'
    unreadable = report(tmp_path, ledger, open_orders=None)
    assert unreadable['open_orders'] == 'ERR' and unreadable['status'] == 'FAIL'
    assert report(tmp_path, ledger, trades={'error': 'x'})['venue_L'] == 'ERR'
    assert report(tmp_path, ledger, held={'status': 'PARTIAL', 'positions': []})['s0_6'] == 'FAIL'


def test_wallet_verify_flags_a_changed_position_outside_the_pilot(tmp_path):
    ledger = wallet_ledger(tmp_path)
    result = report(tmp_path, ledger, held=positions((OLD, '6'), ('11', '2'), ('77', '1')))
    assert result['s0_6'] == 'FAIL' and result['positions_changed_outside_pilot'] == ['77', OLD]


def test_wallet_verify_refuses_a_stale_l_ledger_json(tmp_path):
    ledger = wallet_ledger(tmp_path)
    stale = dict(snapshot(tmp_path), history_last_sha256='0' * 64)
    result = report(tmp_path, ledger, snap=stale)
    assert result['s0_6'] == 'FAIL' and result['l_ledger_json'] == 'stale_or_unreadable'


def test_wallet_verify_command_reads_only_the_three_reader_routes(tmp_path, capsys):
    from weather.market.wallet_reader_client import ClientError
    wallet_ledger(tmp_path)
    calls = []

    def reader(command, **options):
        calls.append((command, options))
        return {'open-orders': [], 'trades': fills(('o1', '2')),
                'positions': positions((OLD, '7'), ('11', '2'))}[command]
    args = parser().parse_args(['wallet-verify'])
    assert run_wallet_verify(args, reader=reader, root=tmp_path) == 0
    genesis = str(int(S0_NOW.timestamp()))
    assert calls == [('open-orders', {}), ('trades', {'since': genesis}), ('positions', {'include_resolved': True})]
    assert "'status': 'PASS'" in capsys.readouterr().out

    def broken(command, **options):
        raise ClientError('timeout')
    assert run_wallet_verify(parser().parse_args(['wallet-verify', '--since', '5']), reader=broken, root=tmp_path) == 1


def test_session0_attest_command_shape():
    args = parser().parse_args(['session0-attest', '--s0-2-seconds', '12.5'])
    assert args.s0_2_seconds == '12.5' or str(args.s0_2_seconds) == '12.5'


# ----- fix round 1: PARTIAL positions read (review F-4) -------------------------------------------------------------
def partial(**changes):
    body = {'status': 'PARTIAL', 'positions': [{'token_id': OLD, 'size': '7', 'curPrice': None},
                                               {'token_id': '11', 'size': '2'}],
            'inventory_complete': True, 'unclassified_positions': [], 'errors': []}
    return {**body, **changes}


def test_a_complete_partial_positions_read_passes_on_sizes_only(tmp_path):
    ledger = wallet_ledger(tmp_path)
    result = report(tmp_path, ledger, held=partial())
    assert result['s0_6'] == 'PASS' and result['positions_reader_status'] == 'PARTIAL'
    assert positions_inventory_readable(positions((OLD, '7')))


@pytest.mark.parametrize('changes', [{'inventory_complete': False}, {'inventory_complete': None},
                                     {'unclassified_positions': [{'token_id': '5'}]},
                                     {'unclassified_positions': None}, {'errors': ['marks_unavailable']},
                                     {'positions': [{'token_id': OLD}]}, {'positions': [{'token_id': OLD, 'size': 'x'}]},
                                     {'positions': [{'size': '7'}]}, {'status': 'ERROR'}])
def test_an_incomplete_partial_positions_read_refuses(tmp_path, changes):
    ledger = wallet_ledger(tmp_path)
    assert not positions_inventory_readable(partial(**changes))
    result = report(tmp_path, ledger, held=partial(**changes))
    assert result['s0_6'] == 'FAIL' and result['positions_changed_outside_pilot'] == 'ERR'


# ----- fix round 1: a lost submit ack is adopted at reconcile (review F-5) -----------------------------------------
EXPIRATION = 1792000000


def lost_ack(tmp_path, *, journal_ids=('o2',)):
    ledger = ledger_with_baselines(tmp_path)
    ledger.record('session_start', session_id='S0c-1', counted=False, session_number=0, session0_run='0c',
                  directory='session0/0c')
    for key in ('S0c-1:1', 'S0c-1:2'):
        ledger.intent(session_id='S0c-1', intent_key=key, token_id='1', condition_id='c', price='.5', size='40',
                      fee_rate_bps='0')
    ledger.ack('S0c-1:1', 'o1')
    directory = tmp_path / 'session0' / '0c'
    directory.mkdir(parents=True)
    (directory / 'submit-2.intent.json').write_text(json.dumps({'number': 2, 'request': {
        'token_id': '1', 'side': 'BUY', 'size': '40', 'price': '0.5', 'post_only': True, 'expiration': EXPIRATION}}))
    lines = [{'event': 'sdk_request', 'method': 'POST', 'path': '/order'}]
    lines += [{'event': 'sdk_response', 'method': 'POST', 'path': '/order', 'response': {'orderID': oid}}
              for oid in journal_ids]
    (directory / 'journal.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in lines))
    return ledger


def venue_order(oid, *, status='CANCELED', expiration=EXPIRATION, price='0.5'):
    return {'id': oid, 'asset_id': '1', 'side': 'BUY', 'price': price, 'original_size': '40',
            'expiration': str(expiration), 'status': status, 'size_matched': '0'}


def test_reconcile_adopts_the_one_matching_order_from_the_post_response(tmp_path):
    ledger = lost_ack(tmp_path)
    assert 'ledger_unacknowledged_intent_needs_reconcile' in gates(ledger, tmp_path)
    venue = FakeVenue([], {'o1': {'status': 'CANCELED', 'size_matched': '0'}, 'o2': venue_order('o2')})
    report_, _ = reconcile_ledger(ledger, venue, root=tmp_path, sleep=lambda s: None)
    assert report_['adopted_order_ids'] == ['o2'] and report_['adoption_refusals'] == {}
    assert report_['unacknowledged_intents'] == [] and report_['closed_sessions'] == ['S0c-1'] and ledger.L() == 0
    [adopt] = [r for r in ledger.rows if r['event'] == 'leg_adopt']
    assert adopt['schema_version'] == 'lfc_ledger_v0.2' and adopt['source'] == 'journal_post_response'
    assert adopt['intent_key'] == 'S0c-1:2' and adopt['evidence']['expiration'] == str(EXPIRATION)
    assert 'ledger_unacknowledged_intent_needs_reconcile' not in gates(ledger, tmp_path)


def test_reconcile_adopts_a_resting_open_order_when_the_post_response_was_lost(tmp_path):
    ledger = lost_ack(tmp_path, journal_ids=())
    rows = [venue_order('o2', status='LIVE')]
    venue = FakeVenue(rows, {'o1': {'status': 'CANCELED', 'size_matched': '0'}, 'o2': rows[0]})
    report_, _ = reconcile_ledger(ledger, venue, root=tmp_path, sleep=lambda s: None)
    assert report_['adopted_order_ids'] == ['o2'] and report_['our_open_orders'] == ['o2']
    assert report_['foreign_open_orders'] == [] and report_['closed_sessions'] == []
    assert ledger.L() == Decimal(20)  # adopted, still resting at full cost


@pytest.mark.parametrize('journal_ids,orders,open_ids,code', [
    (('o2', 'o3'), {'o2': venue_order('o2'), 'o3': venue_order('o3')}, (), 'adoption_ambiguous'),
    ((), {}, (), 'adoption_no_matching_order'),
    (('o2',), {'o2': venue_order('o2', expiration=EXPIRATION + 1)}, (), 'adoption_no_matching_order'),
    (('o2',), {'o2': venue_order('o2', price='0.51')}, (), 'adoption_no_matching_order'),
    (('o2',), {}, (), 'adoption_candidate_unreadable'),
    (('o2',), {'o2': venue_order('o2'), 'o3': venue_order('o3', status='LIVE')}, ('o3',), 'adoption_ambiguous'),
])
def test_ambiguous_or_missing_adoption_adopts_nothing_and_start_stays_refused(tmp_path, journal_ids, orders,
                                                                              open_ids, code):
    ledger = lost_ack(tmp_path, journal_ids=journal_ids)

    class Venue(FakeVenue):
        def order(self, oid):
            if oid not in self.orders:
                raise RuntimeError('order_unreadable')
            return self.orders[oid]
    venue = Venue([orders[oid] for oid in open_ids], {'o1': {'status': 'CANCELED', 'size_matched': '0'}, **orders})
    report_, _ = reconcile_ledger(ledger, venue, root=tmp_path, sleep=lambda s: None)
    assert report_['adoption_refusals'] == {'S0c-1:2': code} and report_['adopted_order_ids'] == []
    assert report_['closed_sessions'] == [] and report_['unacknowledged_intents'] == ['S0c-1:2']
    assert ledger.L() == Decimal(20) and 'ledger_unacknowledged_intent_needs_reconcile' in gates(ledger, tmp_path)


def test_adoption_refuses_without_a_usable_intent_file(tmp_path):
    ledger = lost_ack(tmp_path)
    (tmp_path / 'session0' / '0c' / 'submit-2.intent.json').write_text(json.dumps({'request': {
        'token_id': '1', 'side': 'BUY', 'size': '41', 'price': '0.5', 'expiration': EXPIRATION}}))
    venue = FakeVenue([], {'o1': {'status': 'CANCELED', 'size_matched': '0'}, 'o2': venue_order('o2')})
    report_, _ = reconcile_ledger(ledger, venue, root=tmp_path, sleep=lambda s: None)
    assert report_['adoption_refusals'] == {'S0c-1:2': 'adoption_intent_request_unusable'}


# ----- fix round 1: bounded trade re-reads at reconcile (review F-6) ------------------------------------------------
def test_reconcile_re_reads_lagging_trades_before_a_mismatch(tmp_path):
    ledger = crashed(tmp_path)
    good = [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o2', 'matched_amount': '40'}]}]
    venue = FakeVenue([], {'o1': {'status': 'CANCELED', 'size_matched': '0'},
                           'o2': {'status': 'MATCHED', 'size_matched': '40'}})
    reads, pauses = [], []
    venue.trades = lambda: [] if reads.append(1) or len(reads) < 3 else good
    report_, _ = reconcile_ledger(ledger, venue, sleep=pauses.append)
    assert report_['mismatches'] == [] and ledger.stop_reason() is None and pauses == [2, 2]
    assert venue.trades_after == str(int(NOW.timestamp())) and venue.trades_seconds == LFC.TRADE_READ_SECONDS


def test_reconcile_re_reads_size_matched_from_the_order_before_recording(tmp_path):
    ledger = crashed(tmp_path)
    ledger.terminal('o1', {'status': 'CANCELED', 'size_matched': '0'}, source='session')
    venue = FakeVenue([], {'o1': {'status': 'CANCELED', 'size_matched': '3'},
                           'o2': {'status': 'CANCELED', 'size_matched': '0'}},
                      [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o1', 'matched_amount': '3'}]}])
    pauses = []
    report_, _ = reconcile_ledger(ledger, venue, sleep=pauses.append)
    assert pauses == [] and ledger.stop_reason() == 'l_reconciliation_mismatch'
    # The order re-read records the terminal disagreement first, ending the retries at once.
    assert report_['mismatches'][0]['mismatch_kind'] == 'terminal_size_matched'
    assert report_['mismatches'][0]['source'] == 'reconcile_trade_check'


def test_trade_reads_are_bounded_by_genesis_pages_and_time(monkeypatch):
    from weather.market import re1_transport
    from weather.market.re1_transport import OwnerVenue, bounded_rows
    calls = []
    venue = OwnerVenue.__new__(OwnerVenue)
    venue.condition = '0xc'
    venue.client = SimpleNamespace(list_account_trades=lambda **kw: calls.append(kw) or iter(
        [SimpleNamespace(items=[{'id': 't1'}], next_cursor=None)]))
    assert venue.trades() == [{'id': 't1'}] and calls == [{'market': '0xc'}]  # RE-1 unchanged
    venue.trades_after, venue.trades_seconds = '1760000000', 60
    venue.trades()
    assert calls[-1] == {'market': '0xc', 'after': '1760000000'}
    ticks = iter(range(0, 1000, 40))
    monkeypatch.setattr(re1_transport, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    pages = (SimpleNamespace(items=[{'id': str(n)}], next_cursor=str(n)) for n in range(10))
    with pytest.raises(RuntimeError, match='read_time_budget'):
        bounded_rows(pages, seconds=60)
    endless = (SimpleNamespace(items=[], next_cursor=str(n)) for n in range(100))
    with pytest.raises(RuntimeError, match='pagination_budget'):
        bounded_rows(endless)


# ----- fix round 1: preflight ledger state (review F-10) ------------------------------------------------------------
def test_preflight_ledger_state_names_open_sessions_and_unresolved_legs(tmp_path):
    state = ledger_state(crashed(tmp_path))
    assert state['open_sessions'] == ['S0c-1'] and state['L'] == '40.0'
    assert [leg['order_id'] for leg in state['unresolved_legs']] == ['o1', 'o2']
