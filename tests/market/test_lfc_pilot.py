"""Live-fill calibration session controller with in-memory fakes only (no network, no credentials, no orders).

Guards: the declared 40-share deviation, the signed dates (earliest start 2026-10-15T00:00Z, 23:50Z hard stop, last
start local 10-31), the signed L gate and cash rule before any post, stop-at-100, the event-level position exclusion
on the existing wallet, the foreign-order end, account-wide cancel-all cleanup, the trades reconcile, panel exclusions
before the first post, session 0 (market rules, 5c quote at min size, sub-runs 0a/0b/0d/0e/0f) and the notification.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from tests.market.stage2_fakes import Venue, CONDITION, TOKENS
from weather.market import lfc_constants as LFC
from weather.market import reward_quote
from weather.market.lfc_ledger import Ledger, LedgerUnavailable
from weather.market.lfc_panel_exclusion import EXCLUSION_FILE, FIELDS, load_panel_exclusions
from weather.market.lfc_pilot import (PilotProfile, PilotSession, hard_stop, notify_owner, result_line,
                                      session0_quote, session0_slug_refusals, session0_table, start_refusals,
                                      validate_session0_table, write_session_end)
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import HoldEnd, digest
from weather.market.mm_stage2_selection import select_table
from weather.market.re1_rehearsal import RehearsalVenue

MAKER = '0x' + 'a' * 40
OTHER = '0x' + 'c' * 64
BASE = datetime(2026, 10, 20, 17, tzinfo=timezone.utc)
S0_BASE = datetime(2026, 10, 12, 17, tzinfo=timezone.utc)
S0_SLUG = 'synthetic-election-winner-2026'
LA_SLUG = 'highest-temperature-in-los-angeles-on-october-21-2026'


class Clock:
    def __init__(self, base=BASE):
        self.base, self.seconds = base, 0.0

    def now(self):
        return self.base + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


def snapshot(clock, *, session0=False):
    value = Venue(clock).snapshot()
    value['quote_inputs'].update(reward_rate_per_day='100')
    if session0:  # Session0Books placeholders: an unrewarded market
        value['quote_inputs'].update(reward_min_size='0', reward_max_spread_cents='0', reward_rate_per_day='0')
    return value


def counted_table(clock, *, held=(), figures=None, cash='500'):
    band = dict(market_id='los-angeles', market_timezone=REGISTRY['los-angeles'].timezone,
                target_date=(clock.now() + timedelta(days=1)).date().isoformat(),
                condition_id=CONDITION, token_ids=list(TOKENS), snapshot=snapshot(clock), event_slug=LA_SLUG,
                event_condition_ids=[CONDITION, OTHER])
    return select_table([band], now=clock.now(), available_collateral=cash, treatment=LFC.TREATMENT,
                        ledger=figures or {'L': '0', 'L_resting': '0'}, held_conditions=list(held))


def s0_candidate(clock, *, slug=S0_SLUG, condition=CONDITION, end_days=30, snap=None):
    return {'event_slug': slug, 'event_condition_ids': [condition, OTHER], 'condition_id': condition,
            'token_ids': list(TOKENS), 'market_end_utc': (clock.now() + timedelta(days=end_days)).isoformat(),
            'snapshot': snap or snapshot(clock, session0=True)}


def s0_table(clock, candidates=None, *, run='0a', excluded=(), held=(), figures=None, cash='500'):
    return session0_table(candidates or [s0_candidate(clock)], now=clock.now(), run=run, available_collateral=cash,
                          ledger=figures or {'L': '0', 'L_resting': '0'}, excluded_conditions=excluded,
                          held_conditions=held, scope_sources={'extra_conditions_sha256': '0' * 64})


def prior(ledger, *, filled=None, resting=None):
    ledger.record('session_start', session_id='prior', counted=True)
    if filled is not None:
        ledger.intent(session_id='prior', intent_key='prior:1', token_id='999', condition_id='0xold', price='.5',
                      size=str(Decimal(filled) * 2), fee_rate_bps='0')
        ledger.ack('prior:1', 'prior-filled')
        ledger.terminal('prior-filled', {'status': 'MATCHED', 'size_matched': str(Decimal(filled) * 2)}, source='test')
    if resting is not None:
        ledger.intent(session_id='prior', intent_key='prior:2', token_id='998', condition_id='0xold', price='.5',
                      size=str(Decimal(resting) * 2), fee_rate_bps='0')
        ledger.ack('prior:2', 'prior-resting')
    ledger.record('session_end', session_id='prior', reason='fill')


def setup(tmp_path, *, session0=False, run=None, base=None, filled=None, resting=None, cash='500', table=None):
    clock = Clock(base or (S0_BASE if session0 else BASE))
    root = tmp_path / 'root'
    ledger = Ledger.create(root / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    if filled is not None or resting is not None:
        prior(ledger, filled=filled, resting=resting)
    if table is None:
        table = s0_table(clock, run=run or '0a') if session0 else counted_table(clock, figures={
            k: str(v) for k, v in ledger.figures().items()}, cash=cash)
    assert table['selected_condition_id'] == CONDITION, [r['refusal'] for r in table['rows']]
    directory = tmp_path / 'session'
    selected = table['rows'][0]
    venue = RehearsalVenue(selected['snapshot'], directory, clock=clock)
    venue.balances = lambda: {'available_collateral': cash}
    venue.cancelled = []
    original_cancel = venue.cancel

    def cancel(oid):
        venue.cancelled.append(oid)
        return original_cancel(oid)
    venue.cancel = cancel
    venue.trades = lambda: [{'status': 'CONFIRMED', 'maker_orders': [
        {'order_id': r['id'], 'matched_amount': r['size_matched']}]}
        for r in venue.memory.orders.values() if Decimal(r['size_matched'])]
    profile = PilotProfile(session0=session0, run=(run or '0a') if session0 else None)
    sid = 'S0a-test' if session0 else 'S1-test'
    ledger.record('session_start', session_id=sid, counted=not session0)
    exclusion = None if session0 else {'event_slug': LA_SLUG, 'condition_ids': [CONDITION, OTHER],
                                       'timezone_name': REGISTRY['los-angeles'].timezone}
    session = PilotSession(ledger=ledger, session_id=sid, profile=profile, root=root, exclusion=exclusion,
                           venue=venue, public=venue, table=table, clock=clock, directory=directory)
    return session, venue, clock, ledger


def journal(session):
    return [json.loads(line) for line in Path(session.journal.path).read_bytes().splitlines()]


def events(session, name):
    return [r for r in journal(session) if r['event'] == name]


# ----- constants, profile, dates --------------------------------------------------------------------------------
def test_forty_share_constant_is_a_declared_deviation_from_75():
    assert LFC.PILOT_SIZE == Decimal('40') and LFC.PROXY_SIZE == Decimal('75')
    source = Path(LFC.__file__).read_text(encoding='utf-8')
    assert 'DECLARED DEVIATION' in source and 'live-fill-calibration-preregistration-2026-10-09.md' in source
    assert PilotProfile().SIZES == (Decimal('40'),) and PilotProfile().venue_ceiling(40) == (Decimal('31.60'),
                                                                                            Decimal('39.20'))
    assert LFC.MAX_SESSIONS == 8 and LFC.SESSION_SECONDS == 360 * 60 and LFC.BUDGET_PUSD == 100
    assert LFC.MIN_FEASIBLE_RESERVE == Decimal('38.4')
    with pytest.raises(RuntimeError):
        PilotProfile().venue_ceiling(75)


def test_profile_session0_needs_a_run_and_binds_min_size_at_most_20():
    for kwargs in ({'session0': True}, {'run': '0a'}, {'session0': True, 'run': '0z'}):
        with pytest.raises(ValueError):
            PilotProfile(**kwargs)
    profile = PilotProfile(session0=True, run='0a')
    assert profile.seconds == 1200 and profile.treatment == LFC.SESSION0_TREATMENT
    with pytest.raises(RuntimeError):
        PilotProfile(session0=True, run='0b').bind_size(21)
    assert profile.bind_size(5).SIZES == (Decimal(5),)
    with pytest.raises(RuntimeError):
        profile.bind_size(6)


def test_earliest_start_is_utc_2026_10_15_with_a_hard_refusal():
    edge = LFC.EARLIEST_START_UTC
    assert edge == datetime(2026, 10, 15, tzinfo=timezone.utc)
    assert 'before_earliest_start' in start_refusals(edge - timedelta(microseconds=1), seconds=60)
    assert start_refusals(edge, seconds=60) == []
    assert start_refusals(datetime(2026, 10, 15, 17, tzinfo=timezone.utc)) == []  # the first signed session
    assert start_refusals(edge - timedelta(days=3), session0=True, seconds=1200) == []


def test_hard_stop_2350z_and_last_start_owner_local_10_31():
    assert hard_stop(BASE) == datetime(2026, 10, 20, 23, 50, tzinfo=timezone.utc)
    assert start_refusals(datetime(2026, 10, 20, 17, 50, tzinfo=timezone.utc)) == []
    assert start_refusals(datetime(2026, 10, 20, 17, 50, 1, tzinfo=timezone.utc)) == ['past_hard_stop_2350z']
    assert 'past_hard_stop_2350z' in start_refusals(datetime(2026, 10, 12, 23, 40, tzinfo=timezone.utc),
                                                    session0=True, seconds=1200)
    # 2026-11-01T00:00Z is 20:00 on 10-31 in Toronto: still the last start date.
    assert start_refusals(datetime(2026, 11, 1, 0, tzinfo=timezone.utc)) == []
    assert start_refusals(datetime(2026, 11, 1, 4, 1, tzinfo=timezone.utc)) == ['after_last_start_date']
    assert LFC.LAST_START_LOCAL_DATE == date(2026, 10, 31)


def test_counted_session_before_earliest_start_posts_nothing(tmp_path):
    session, venue, _, ledger = setup(tmp_path, base=datetime(2026, 10, 14, 17, tzinfo=timezone.utc))
    result = session.run()
    assert result['reason'] == 'session_duration_or_utc_day' and not venue.calls and ledger.L() == 0


# ----- a normal counted session -----------------------------------------------------------------------------------
def test_full_session_rests_forty_counts_L_and_releases_it_after_cleanup(tmp_path):
    session, venue, _, ledger = setup(tmp_path)
    seen = []
    original = session.minute_extra

    def minute_extra(snap):
        seen.append(ledger.figures())
        original(snap)
    session.minute_extra = minute_extra
    result = session.run(rehearsal_seconds=180)
    assert result['submits'] == 2 and result['cleanup_ok'] and not venue.open_orders()
    assert {Decimal(r['size']) for r in venue.calls} == {Decimal('40')}
    assert all(r['expiration'] == int(session.end.timestamp()) + 60 for r in venue.calls)
    band = sum(session.prices) * 40
    assert seen and all(f['L'] == band and f['L_resting'] == band and f['L_filled'] == 0 for f in seen)
    assert ledger.L() == 0 and not ledger.unresolved_legs()
    gates = events(session, 'lfc_l_gate')
    assert gates[0]['phase'] == 'band' and Decimal(gates[0]['reserve']) == band
    placement = [r for r in events(session, 'lfc_queue_ahead') if r['phase'] == 'placement']
    assert len(placement) == 2 and all(r['visible_at_price'] is not None for r in placement)
    snapshot_file = json.loads((tmp_path / 'root' / 'l_ledger.json').read_bytes())
    assert snapshot_file['schema_version'] == 'lfc_l_ledger_v0.1' and Decimal(snapshot_file['L']) == 0


def test_selection_and_panel_exclusions_are_recorded_before_the_first_post(tmp_path):
    session, venue, _, ledger = setup(tmp_path)
    session.run(rehearsal_seconds=60)
    rows = journal(session)
    names = [r['event'] for r in rows]
    first_submit = names.index('submit_request')
    assert names.index('lfc_selection') < first_submit and names.index('lfc_panel_exclusion') < first_submit
    selection = events(session, 'lfc_selection')[0]
    assert selection['sha256'] == hashlib.sha256((session.directory / 'selection.json').read_bytes()).hexdigest()
    path = tmp_path / 'root' / EXCLUSION_FILE
    lines = load_panel_exclusions(path)
    assert lines and all(tuple(sorted(line)) == FIELDS for line in lines)
    assert lines[0]['condition_ids'] == sorted([CONDITION, OTHER]) and lines[0]['local_quote_date'] == '2026-10-20'
    recorded = [r['line_sha256'] for r in events(session, 'lfc_panel_exclusion')]
    assert recorded == [hashlib.sha256(raw + b'\n').hexdigest() for raw in path.read_bytes().splitlines()]


def test_panel_exclusion_write_failure_posts_nothing(tmp_path):
    session, venue, _, _ = setup(tmp_path)
    (tmp_path / 'root' / EXCLUSION_FILE).write_bytes(b'{"truncated":')
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'panel_exclusion_write_failed' and not venue.calls


def test_existing_wallet_positions_outside_the_event_do_not_refuse(tmp_path):
    session, venue, _, ledger = setup(tmp_path)
    venue.positions = lambda: [{'conditionId': '0x' + 'd' * 64, 'asset': '777', 'size': '12'}]
    result = session.run(rehearsal_seconds=60)
    assert result['submits'] == 2 and not result['fill_seen'] and result['reason'] != 'fill'


@pytest.mark.parametrize('condition', [CONDITION, OTHER])
def test_position_in_any_condition_of_the_event_refuses(tmp_path, condition):
    session, venue, _, _ = setup(tmp_path)
    venue.positions = lambda: [{'conditionId': condition, 'asset': '777', 'size': '1'}]
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'initial_positions' and not venue.calls


def test_live_mode_requires_a_ledger_and_the_panel_exclusion(tmp_path):
    clock = Clock()
    table = counted_table(clock)
    venue = RehearsalVenue(table['rows'][0]['snapshot'], tmp_path, clock=clock)
    common = dict(venue=venue, public=venue, table=table, clock=clock, directory=tmp_path, mode='live',
                  confirmation={'text': 'go ' + digest(table)[:6]})
    with pytest.raises(LedgerUnavailable):
        PilotSession(ledger=None, session_id='S1', profile=PilotProfile(), root=tmp_path, **common)
    ledger = Ledger.create(tmp_path / 'l' / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    with pytest.raises(RuntimeError, match='panel_exclusion_required'):
        PilotSession(ledger=ledger, session_id='S1', profile=PilotProfile(), root=tmp_path, **common)


# ----- the signed L gate ------------------------------------------------------------------------------------------
def test_L_plus_reserve_exactly_100_is_allowed(tmp_path):
    # reserve = 40 x (.33 + .64) = 38.8; 61.2 + 38.8 = 100 (<= 100 passes); 61.2 + 38.4 < 100 (not stopped)
    session, venue, _, ledger = setup(tmp_path, filled='61.2')
    assert band_sum(session) == Decimal('.97')
    result = session.run(rehearsal_seconds=60)
    assert result['submits'] == 2 and result['reason'] != 'l_budget_refused'


def band_sum(session):
    return sum(session.prices)


def test_L_plus_reserve_above_100_refuses_before_any_post(tmp_path):
    table_clock = Clock()
    table = counted_table(table_clock, figures={'L': '0', 'L_resting': '0'})
    session, venue, _, ledger = setup(tmp_path, filled='61.3', table=table)
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'l_budget_refused' and not venue.calls and ledger.L() == Decimal('61.3')


def test_stop_at_100_when_filled_plus_minimum_reserve_exceeds_cap(tmp_path):
    table = counted_table(Clock())
    session, venue, _, ledger = setup(tmp_path, filled='61.7', table=table)  # 61.7 + 38.4 = 100.1
    assert ledger.stop_reason() == 'l_stop_at_cap'
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'l_stop_at_cap' and not venue.calls


def test_cash_must_cover_L_resting_plus_reserve(tmp_path):
    table = counted_table(Clock())
    session, venue, _, ledger = setup(tmp_path, resting='30', cash='68.7', table=table)  # 30 + 38.8 > 68.7
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'cash_below_l_resting_plus_reserve' and not venue.calls


def test_a_requote_rereads_the_balance(tmp_path):
    session, venue, clock, ledger = setup(tmp_path)
    reads = []
    session.run(rehearsal_seconds=30)
    venue.balances = lambda: reads.append(1) or {'available_collateral': '1'}
    session.closed = False
    session.submits, session.active = 2, {}
    session.journal.record = lambda *args, **kwargs: None  # the run closed the journal; this probes the gate only
    with pytest.raises(HoldEnd, match='cash_below_l_resting_plus_reserve'):
        session.authorize_post(0, session.prices[0], session.size, {'fee_rate_bps': '0'})
    assert reads


def test_ledger_mismatch_or_halt_stops_the_session(tmp_path):
    session, venue, _, ledger = setup(tmp_path)
    ledger.record('mismatch', order_id='x', recorded='0', observed='1', source='test', mismatch_kind='test')
    result = session.run(rehearsal_seconds=60)
    assert result['reason'] == 'l_reconciliation_mismatch' and not venue.calls


def test_ledger_file_lost_mid_session_fails_closed_before_any_post(tmp_path):
    session, venue, _, ledger = setup(tmp_path)
    ledger.path.unlink()
    result = session.run(rehearsal_seconds=60)
    assert not venue.calls and result['cleanup_ok'] and result['reason'] in {'exception', 'ledger_unavailable'}


def test_unacknowledged_intent_stays_in_L_and_cancel_all_clears_it(tmp_path):
    session, venue, _, ledger = setup(tmp_path)
    original = venue.submit

    def lost_ack(request, *, checkpoint=lambda: None):
        original(request, checkpoint=checkpoint)
        raise TimeoutError('ack lost')
    venue.submit = lost_ack
    result = session.run(rehearsal_seconds=60)
    assert result['unknown_submit'] and not venue.open_orders() and venue.cancelled
    assert ledger.L() == Decimal(40) * session.prices[0]  # full resting cost until an owner reconcile


# ----- foreign orders, cleanup, fills ---------------------------------------------------------------------------
def add_foreign_at(venue, clock, seconds=120):
    real = venue.open_orders

    def open_orders():
        if clock.seconds >= seconds and 'owner-manual' not in venue.memory.orders:
            venue.memory.orders['owner-manual'] = {
                'id': 'owner-manual', 'asset_id': '555', 'market': OTHER, 'maker_address': venue.maker, 'side': 'BUY',
                'price': '.05', 'original_size': '5', 'size_matched': '0', 'status': 'LIVE', 'associate_trades': []}
        return real()
    venue.open_orders = open_orders


def test_foreign_order_ends_the_session_and_cancel_all_clears_the_account(tmp_path):
    session, venue, clock, ledger = setup(tmp_path)
    add_foreign_at(venue, clock)
    result = session.run(rehearsal_seconds=600)
    assert result['reason'] == 'foreign_open_order' and result['cleanup_ok']
    assert clock.seconds < 120 + 2 * LFC.FOREIGN_CHECK_SECONDS
    assert 'owner-manual' in venue.cancelled and not venue.open_orders() and ledger.L() == 0
    assert events(session, 'lfc_foreign_open_order')[0]['order_ids'] == ['owner-manual']


def test_cleanup_is_account_wide_cancel_all(tmp_path):
    session, venue, _, _ = setup(tmp_path)
    calls = []
    original = venue.cancel_all
    venue.cancel_all = lambda: calls.append(1) or original()
    result = session.run(rehearsal_seconds=120)
    assert calls and result['cleanup_ok'] and not venue.open_orders()


def fill_first_at(venue, clock, seconds=120):
    real = venue.open_orders

    def open_orders():
        rows = [r for r in venue.memory.orders.values() if r['status'] == 'LIVE']
        if clock.seconds >= seconds and rows:
            rows[0].update(status='MATCHED', size_matched=rows[0]['original_size'])
        return real()
    venue.open_orders = open_orders


@pytest.mark.parametrize('cause', ['exception', 'interrupt', 'fill'])
def test_crash_or_limit_leaves_zero_resting_orders(tmp_path, cause):
    session, venue, clock, ledger = setup(tmp_path)
    original = venue.snapshot

    def snap(*args, **kwargs):
        if clock.seconds >= 120 and cause != 'fill':
            raise ZeroDivisionError() if cause == 'exception' else KeyboardInterrupt()
        return original(*args, **kwargs)
    venue.snapshot = snap
    if cause == 'fill':
        fill_first_at(venue, clock)
    result = session.run(rehearsal_seconds=600)
    assert not venue.open_orders()
    if cause == 'fill':
        assert result['reason'] == 'fill' and ledger.L() == ledger.L_filled() == Decimal(40) * session.prices[0]
        assert ledger.stop_reason() is None  # trades agree with the terminal read
    else:
        assert result['reason'] in {'exception', 'interrupted'} and ledger.L() == 0


def test_trades_disagreeing_with_the_ledger_record_a_mismatch_after_retries(tmp_path):
    session, venue, clock, ledger = setup(tmp_path)
    fill_first_at(venue, clock)
    reads = []
    venue.trades = lambda: reads.append(1) or []
    session.run(rehearsal_seconds=600)
    assert len(reads) >= 5 and ledger.stop_reason() == 'l_reconciliation_mismatch'
    assert ledger.mismatches[0]['mismatch_kind'] == 'trades_vs_size_matched'


def test_lagging_trades_are_re_read_before_a_mismatch(tmp_path):
    session, venue, clock, ledger = setup(tmp_path)
    fill_first_at(venue, clock)
    good, reads = venue.trades, []
    venue.trades = lambda: [] if reads.append(1) or len(reads) < 3 else good()
    session.run(rehearsal_seconds=600)
    assert ledger.stop_reason() is None and ledger.L_filled() == Decimal(40) * session.prices[0]


# ----- session 0 ------------------------------------------------------------------------------------------------
def test_session0_slug_rule_refuses_built_in_markets_and_youtube():
    market = sorted(REGISTRY)[0]
    band = event_slug_for_date(date(2026, 10, 13), market)
    assert 'session0_built_in_band' in session0_slug_refusals(band, now=S0_BASE)
    assert 'session0_built_in_market' in session0_slug_refusals(REGISTRY[market].slug_prefix + 'x', now=S0_BASE)
    assert 'session0_youtube_market' in session0_slug_refusals('will-mrbeast-youtube-video-hit-1b', now=S0_BASE)
    assert session0_slug_refusals('', now=S0_BASE) == ['session0_event_slug_missing']
    assert session0_slug_refusals(S0_SLUG, now=S0_BASE) == []


def refusal(table):
    return table['rows'][0]['refusal']


@pytest.mark.parametrize('kwargs,code', [
    ({'excluded': [OTHER.upper()]}, 'session0_in_retained_scope'),
    ({'held': [OTHER]}, 'session0_event_held_in_baseline'),
    ({'figures': {'L': '99', 'L_resting': '0'}}, 'l_budget_refused'),
])
def test_session0_scope_baseline_and_L_rules(kwargs, code):
    assert refusal(s0_table(Clock(S0_BASE), **kwargs)) == code


def test_session0_market_rules():
    clock = Clock(S0_BASE)
    assert refusal(s0_table(clock, [s0_candidate(clock, end_days=6)])) == 'session0_market_ends_too_soon'
    for change, code in ((lambda s: [r.update(min_order_size='21') for r in s['rules'].values()],
                          'session0_min_order_size'),
                         (lambda s: [r.update(tick_size='.001') for r in s['rules'].values()], 'unsupported_tick'),
                         (lambda s: s['quote_inputs'].update(yes_asks=[]), 'one_sided_book'),
                         (lambda s: s['quote_inputs'].update(yes_bids=[{'price': '.36', 'size': '9'}]),
                          'crossed_book'),
                         (lambda s: s['quote_inputs'].update(yes_bids=[{'price': '.84', 'size': '9'}],
                                                             yes_asks=[{'price': '.85', 'size': '9'}]),
                          'midpoint_outside_range')):
        snap = snapshot(clock, session0=True)
        change(snap)
        assert refusal(s0_table(clock, [s0_candidate(clock, snap=snap)])) == code


def test_session0_pick_is_largest_depth_within_3c_then_condition_id():
    clock = Clock(S0_BASE)
    deep = snapshot(clock, session0=True)
    deep['quote_inputs']['yes_asks'] = [{'price': '.35', 'size': '500'}]
    deep['quote_inputs']['yes_bids'] = [{'price': '.34', 'size': '300'}, {'price': '.10', 'size': '9999'}]
    a, b, c = ('0x' + ch * 64 for ch in '123')
    table = s0_table(clock, [s0_candidate(clock, condition=b, snap=deep), s0_candidate(clock, condition=a),
                             s0_candidate(clock, condition=c)])
    assert table['selected_condition_id'] == b and table['ranked_conditions'] == [b, a, c]
    assert {r['condition_id']: r['depth_within_3c'] for r in table['rows']}[b] == '300'
    assert validate_session0_table(table, now=clock.now())['condition_id'] == b
    table['rows'][0]['depth_within_3c'] = '1'
    table['ranked_conditions'] = []
    with pytest.raises(ValueError):
        validate_session0_table(table, now=clock.now())


def test_session0_quote_is_5c_outward_at_min_order_size():
    quote = session0_quote(snapshot(Clock(S0_BASE), session0=True), size=5)
    assert (quote['yes_buy'], quote['no_buy'], quote['size']) == ('0.29', '0.60', '5')
    assert Decimal(quote['reserve_pusd']) == Decimal('4.45')


def test_session0_0a_runs_before_10_15_uncounted_at_min_size_and_ends_fixed(tmp_path):
    session, venue, _, ledger = setup(tmp_path, session0=True, run='0a')
    seen = []
    original = session.minute_extra
    session.minute_extra = lambda snap: seen.append(ledger.L()) or original(snap)
    result = session.run()
    assert result['reason'] == 'fixed_end' and result['cleanup_ok'] and session.planned_seconds == 1200
    assert {Decimal(r['size']) for r in venue.calls} == {Decimal(5)} and len(venue.calls) == 2
    assert {r['price'] for r in venue.calls} == {'0.29', '0.60'}
    assert seen and all(value == Decimal('4.45') for value in seen)  # session 0 counts in L while resting
    assert ledger.counted_sessions() == 0 and ledger.L() == 0
    assert not (tmp_path / 'root' / EXCLUSION_FILE).exists()  # session 0 adds no panel exclusion


def test_session0_0b_foreign_order_ends_the_run(tmp_path):
    session, venue, clock, _ = setup(tmp_path, session0=True, run='0b')
    add_foreign_at(venue, clock)
    result = session.run()
    assert result['reason'] == 'foreign_open_order' and 'owner-manual' in venue.cancelled and not venue.open_orders()


def test_session0_0d_heartbeat_drop_ends_and_cleans_up(tmp_path):
    session, venue, clock, _ = setup(tmp_path, session0=True, run='0d')
    result = session.run()
    flags = events(session, 'lfc_session0_test_flag')
    assert flags and flags[0]['action'] == 'heartbeat_sends_stopped'
    assert result['reason'] == 'heartbeat_stale' and result['cleanup_ok'] and not venue.open_orders()
    assert LFC.SESSION0_DROP_AFTER_SECONDS <= clock.seconds < LFC.SESSION0_DROP_AFTER_SECONDS + 20


def test_session0_0e_L_budget_below_reserve_refuses_before_any_submit(tmp_path):
    session, venue, _, _ = setup(tmp_path, session0=True, run='0e')
    result = session.run()
    assert result['reason'] == 'l_budget_refused' and not venue.calls and result['submits'] == 0
    assert events(session, 'lfc_session0_test_flag')[0]['run'] == '0e'


def test_session0_0f_main_loop_stall_stops_heartbeats(tmp_path):
    session, venue, _, _ = setup(tmp_path, session0=True, run='0f')
    result = session.run()
    assert result['reason'] == 'main_loop_stalled' and result['cleanup_ok'] and not venue.open_orders()


def test_test_flags_never_fire_in_a_counted_session(tmp_path):
    session, venue, clock, _ = setup(tmp_path)
    result = session.run(rehearsal_seconds=400)
    assert not events(session, 'lfc_session0_test_flag') and result['reason'] != 'heartbeat_stale'


# ----- notification and session_end ------------------------------------------------------------------------------
SUMMARY = {'session_id': 'S1', 'reason': 'fixed_end', 'cleanup_ok': True, 'panic': False, 'L': '0'}


def test_notification_is_a_windows_toast_plus_a_result_line(tmp_path):
    calls, printed = [], []

    class Done:
        returncode = 0

    def runner(command, **kwargs):
        calls.append((command, kwargs['env']['LFC_NOTIFY_TEXT']))
        return Done()
    record = notify_owner(tmp_path, SUMMARY, runner=runner, printer=lambda *a, **k: printed.append(a[0]),
                          windows=True)
    assert record['toast_delivered'] and record['toast_error'] is None and record['result_line_printed']
    assert calls[0][0][0] == 'powershell.exe' and 'ToastNotificationManager' in calls[0][0][-1]
    assert printed == [result_line(SUMMARY)] and printed[0].startswith('LFC-RESULT session_id=S1 reason=fixed_end')
    assert json.loads((tmp_path / 'notifications.jsonl').read_text().splitlines()[0])['toast_delivered']


def test_notification_failure_is_recorded_and_never_raises(tmp_path):
    def boom(*args, **kwargs):
        raise OSError('no shell')
    record = notify_owner(tmp_path, SUMMARY, runner=boom, printer=boom, windows=True)
    assert not record['toast_delivered'] and record['toast_error'] == 'OSError' and not record['result_line_printed']
    assert notify_owner(tmp_path, SUMMARY, printer=lambda *a, **k: None, windows=False)['toast_error'] == \
        'toast_requires_windows'


def test_session_end_is_written_once(tmp_path):
    write_session_end(tmp_path, {**SUMMARY, 'notification': {'toast_delivered': False}})
    body = json.loads((tmp_path / 'session_end.json').read_bytes())
    assert body['schema_version'] == 'lfc_session_end_v0.1' and body['notification'] == {'toast_delivered': False}
    with pytest.raises(FileExistsError):
        write_session_end(tmp_path, SUMMARY)
