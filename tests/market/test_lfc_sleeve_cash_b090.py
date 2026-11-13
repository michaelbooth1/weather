"""Synthetic sleeve-cash witnesses; no account, wallet amount or public service.

Guards: B090. An uncharged owner withdrawal beyond the owner pools takes the
sleeve's own cash. A later owner contribution repays that overdraw before any
of it is segregated, headroom never changes, and pre-go deferrals keep their true reason.
"""
from datetime import timedelta

import pytest

from tests.market.test_lfc_campaign import (Clock, MAKER as CAMPAIGN_MAKER, Mutexes, StubRuntime, bind_launch,
                                            policy_row, state_at)
from tests.market.test_lfc_f2_capital import activity
from tests.market.test_lfc_f2_inventory_b080 import fixture
from weather.market.lfc_campaign import CampaignCoordinator, TransientPrecheck
from weather.market.lfc_campaign_control import PRECHECK_REASONS, SAFE_REASONS
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_capital import CapitalBook, CapitalRefused, record_activity
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import strict_json

UNIT = 1_000_000


def move(ledger, clock, *, kind, cash, tx, direction=None, session=None):
    """Record one owner cash movement at the fixture clock, optionally inside a session."""
    source = activity(cash=cash, size='0', token='', tx=tx, kind=kind)
    source['timestamp'] = int(clock.now().timestamp())
    if direction is not None:
        source['side'] = direction
    if session is None:
        record_activity(ledger, source)
        return
    ledger.record('session_start', session_id=session, counted=True, autostart_attempt_id='b' * 32)
    record_activity(ledger, source)
    ledger.record('session_end', session_id=session)


def spendable(book, cash):
    """Wallet cash the sleeve may spend, by the gate's own segregation formula."""
    f = book.figures()
    return cash * UNIT - (f['segregated_profit_native'] + f['segregated_incentives_native'] +
                          f['segregated_external_cash_native'] - f['retained_gains_offset_native']) - f['resting_reserve_native']


def test_todays_shape_deposit_repays_uncharged_overdraw_and_restores_spendable(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    before = CapitalBook(ledger).figures()
    assert before['headroom_native'] == 290 * UNIT and before['segregated_external_cash_native'] == 0
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='100', tx='owner-withdraw')
    book = CapitalBook(ledger)
    figures = book.figures()
    assert figures['owner_overdraw_outstanding_native'] == 100 * UNIT
    assert figures['owner_overdraw_repaid_native'] == 0
    assert figures['headroom_native'] == before['headroom_native']
    assert figures['paid_or_reserved_campaign_costs_native'] == before['paid_or_reserved_campaign_costs_native']
    assert spendable(book, 190) == 190 * UNIT  # Below headroom: the owner took sleeve cash.
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='DEPOSIT', cash='150', tx='owner-deposit')
    book = CapitalBook(ledger)
    figures = book.figures()
    # Only the overdraw is repaid; the rest of the deposit stays owner cash.
    assert figures['owner_overdraw_repaid_native'] == 100 * UNIT
    assert figures['owner_overdraw_outstanding_native'] == 0
    assert figures['segregated_external_cash_native'] == 50 * UNIT
    assert figures['headroom_native'] == before['headroom_native']
    assert figures['funding_native'] == before['funding_native']
    assert figures['realized_principal_losses_native'] == before['realized_principal_losses_native']
    assert figures['segregated_profit_native'] == figures['segregated_incentives_native'] == 0
    assert spendable(book, 340) == 290 * UNIT == figures['headroom_native']
    book.gate(reserve='290', available_cash='340')
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        book.gate(reserve='290.000001', available_cash='340')
    assert CapitalBook(Ledger.open(ledger.path, clock=clock.now)).figures() == figures


def test_incoming_tip_repays_and_a_second_overdraw_is_tracked_again(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='30', tx='first')
    clock.value += timedelta(hours=1)
    move(ledger, clock, kind='TIP', cash='10', tx='tip-in', direction='IN')
    clock.value += timedelta(hours=1)
    move(ledger, clock, kind='WITHDRAWAL', cash='5', tx='second')
    figures = CapitalBook(ledger).figures()
    assert figures['owner_overdraw_repaid_native'] == 10 * UNIT
    assert figures['owner_overdraw_outstanding_native'] == 25 * UNIT
    assert figures['segregated_external_cash_native'] == 0


def test_label_quarantine_deposit_does_not_repay_until_its_cash_is_known(tmp_path):
    from weather.market.mm_stage2_hold import digest
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='40', tx='owner-withdraw')
    clock.value += timedelta(hours=1)
    unknown = activity(cash=None, size='0', token='', tx='late-deposit', kind='DEPOSIT')
    unknown['timestamp'] = int(clock.now().timestamp())
    unknown['usdc_size'] = None
    record_activity(ledger, unknown)
    book = CapitalBook(ledger)
    assert book.figures()['owner_overdraw_repaid_native'] == 0
    assert book.figures()['owner_overdraw_outstanding_native'] == 40 * UNIT
    known = {**unknown, 'usdc_size': '60'}
    ledger.record('capital_resolution', source=known, source_sha256=digest(known),
                  previous_source_sha256=book.sources[next(iter(book.unknown))])
    figures = CapitalBook(ledger).figures()
    assert figures['owner_overdraw_repaid_native'] == 40 * UNIT
    assert figures['segregated_external_cash_native'] == 20 * UNIT


def test_deposit_before_the_overdraw_has_no_repayment(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='DEPOSIT', cash='150', tx='owner-deposit')
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='100', tx='owner-withdraw')
    figures = CapitalBook(ledger).figures()
    assert figures['owner_overdraw_outstanding_native'] == figures['owner_overdraw_repaid_native'] == 0
    assert figures['segregated_external_cash_native'] == 50 * UNIT
    assert figures['headroom_native'] == 290 * UNIT


def test_in_session_charged_excess_is_unchanged_and_never_repaid(tmp_path):
    ledger, _, clock, _ = fixture(tmp_path, personal=False)
    before = CapitalBook(ledger).figures()
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='WITHDRAWAL', cash='20', tx='in-session', session='charged')
    charged = CapitalBook(ledger).figures()
    assert charged['paid_or_reserved_campaign_costs_native'] == before['paid_or_reserved_campaign_costs_native'] + 20 * UNIT
    assert charged['headroom_native'] == before['headroom_native'] - 20 * UNIT
    assert charged['owner_overdraw_outstanding_native'] == 0
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='DEPOSIT', cash='50', tx='owner-deposit')
    after = CapitalBook(ledger).figures()
    assert after['owner_overdraw_repaid_native'] == 0
    assert after['segregated_external_cash_native'] == 50 * UNIT
    assert after['headroom_native'] == charged['headroom_native']
    assert after['paid_or_reserved_campaign_costs_native'] == charged['paid_or_reserved_campaign_costs_native']


def test_prebridge_withdrawal_never_becomes_an_overdraw(tmp_path):
    ledger, baseline, clock, read = fixture(tmp_path, personal=False, bridge=False)
    old = activity(cash='500', size='0', token='', tx='legacy-withdraw', kind='WITHDRAWAL')
    old['timestamp'] = int(clock.now().timestamp()) - 3600
    record_activity(ledger, old)
    from weather.market.lfc_capital_reads import synchronize
    synchronize(ledger, baseline, read, anchor_mode='enrollment')
    clock.value += timedelta(hours=12)
    move(ledger, clock, kind='DEPOSIT', cash='70', tx='owner-deposit')
    figures = CapitalBook(ledger).figures()
    assert figures['owner_overdraw_outstanding_native'] == figures['owner_overdraw_repaid_native'] == 0
    assert figures['segregated_external_cash_native'] == 70 * UNIT


class Deferring(StubRuntime):
    def __init__(self, state, clock, error):
        super().__init__(state, clock)
        self.error = error

    def pre_go(self, entry, policy):
        self.prechecks += 1
        raise self.error


@pytest.mark.parametrize('error,reason', [
    (TransientPrecheck('wallet_cash_below_sleeve'), 'wallet_cash_below_sleeve'),
    (TransientPrecheck('heartbeat_latency_budget'), 'heartbeat_latency_budget'),
    (TransientPrecheck('account_read_stale'), 'account_read_stale'),
    (TransientPrecheck('no_qualifying_band_for_policy'), 'no_qualifying_band'),
    (TransientPrecheck('unlisted_code'), 'transport_deferred')])
def test_coordinator_control_rows_show_the_true_deferral_reason(tmp_path, error, reason):
    clock = Clock()
    with account_lease(CAMPAIGN_MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        runtime = Deferring(state, clock, error)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        policy = bind_launch(coordinator, parse_policy(policy_row()))
        coordinator.tick(lambda: policy)
    rows = [strict_json(path.read_bytes()) for path in (tmp_path / 'control').glob('*.json')]
    assert runtime.go_count == 0 and runtime.prechecks >= 1
    assert {r['reason'] for r in rows if r['phase'] in {'DEFERRED', 'MISSED'}} == {reason}


@pytest.fixture
def guarded_account():
    with account_lease(CAMPAIGN_MAKER, backend=Mutexes()):
        yield


def test_pre_go_keeps_a_precheck_reason_and_still_wraps_read_errors(tmp_path, monkeypatch, guarded_account):
    from tests.market.test_lfc_campaign_runtime import runtime_at
    runtime = runtime_at(tmp_path)
    for code in ('wallet_cash_below_sleeve', 'heartbeat_latency_budget', 'private_stream_not_ready'):
        def raising(entry, policy, code=code):
            raise TransientPrecheck(code)
        monkeypatch.setattr(runtime, 'pre_go_once', raising)
        with pytest.raises(TransientPrecheck, match='^' + code + '$'):
            runtime.pre_go(None, parse_policy(policy_row()))
    def timeout(entry, policy):
        raise TimeoutError('socket')
    monkeypatch.setattr(runtime, 'pre_go_once', timeout)
    with pytest.raises(TransientPrecheck, match='^pre_go_read_unavailable$'):
        runtime.pre_go(None, parse_policy(policy_row()))
    def spend(entry, policy):
        raise CapitalRefused('capital_spendable_cash')
    monkeypatch.setattr(runtime, 'pre_go_once', spend)
    with pytest.raises(TransientPrecheck, match='^wallet_cash_below_sleeve$'):
        runtime.pre_go(None, parse_policy(policy_row()))
    assert not getattr(runtime, 'preparing_f2', False)


def test_every_precheck_reason_is_an_allowlisted_code():
    assert PRECHECK_REASONS <= SAFE_REASONS
    assert all(code.replace('_', '').isalnum() and code.islower() for code in PRECHECK_REASONS)


def missed_skip(state, entry, reason='window_missed'):
    state.save('skips/' + entry.local_date + '.json', {'local_date': entry.local_date, 'entry_id': 'earlier-window',
               'reason': reason, 'at_utc': entry.start.isoformat()})


def test_missed_only_date_reopens_inside_a_later_window_and_claims(tmp_path):
    clock = Clock()
    with account_lease(CAMPAIGN_MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        policy = parse_policy(policy_row())
        entry = policy.entries[0]
        missed_skip(state, entry)
        assert entry.local_date in state.consumed_dates()  # consumed_dates itself is unchanged.
        assert state.reopenable_missed_dates() == {entry.local_date}
        runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        bound = bind_launch(coordinator, policy)
        assert coordinator.tick(lambda: bound) == 'STARTED' and runtime.go_count == 1
        assert state.reopenable_missed_dates() == set()  # The claim now consumes the date.
        assert len(state.skips()) == 1


@pytest.mark.parametrize('offset', [timedelta(minutes=1), timedelta(hours=6)])
def test_reopenable_date_stays_closed_outside_the_window_with_no_new_missed_row(tmp_path, offset):
    clock = Clock()
    with account_lease(CAMPAIGN_MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        policy = parse_policy(policy_row())
        entry = policy.entries[0]
        missed_skip(state, entry)
        before = sorted(p.name for p in (state.root / 'skips').iterdir())
        clock.value = entry.end + offset
        runtime = StubRuntime(state, clock)
        coordinator = CampaignCoordinator(state=state, runtime=runtime, clock=clock, control_root=tmp_path / 'control')
        coordinator.tick(lambda: bind_launch(coordinator, parse_policy(policy_row())))
        rows = [strict_json(p.read_bytes()) for p in (tmp_path / 'control').glob('*.json')]
        assert runtime.go_count == runtime.prechecks == 0
        assert 'MISSED' not in {r['phase'] for r in rows}
        assert sorted(p.name for p in (state.root / 'skips').iterdir()) == before
        with pytest.raises(StateRefused, match='claim_outside_window'):
            state.claim(entry, policy, clock.now())


@pytest.mark.parametrize('closer', ['claim', 'other_skip', 'incident', 'owner_closure'])
def test_claims_other_skips_incidents_and_closures_still_consume(tmp_path, closer):
    clock = Clock()
    with account_lease(CAMPAIGN_MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        policy = parse_policy(policy_row())
        entry = policy.entries[0]
        if closer == 'claim':
            state.claim(entry, policy, clock.now())
            missed_skip(state, entry)
        elif closer == 'other_skip':
            missed_skip(state, entry, reason='policy_refused')
        else:
            missed_skip(state, entry)
            folder = 'incidents' if closer == 'incident' else 'owner-closures'
            state.save(folder + '/fixture.json', {'local_date': entry.local_date, 'attempt_id': 'c' * 32})
        assert entry.local_date not in state.reopenable_missed_dates()
        if closer in {'other_skip', 'claim'}:
            with pytest.raises(StateRefused, match='account_date_consumed'):
                state.claim(entry, policy, clock.now())


@pytest.mark.parametrize('reason,ended,idle', [('policy_refused', False, True), ('window_missed', False, False),
                                               ('window_missed', True, True)])
def test_idle_fast_path_never_hides_a_reopened_window(tmp_path, reason, ended, idle):
    from weather.market import lfc_campaign_idle
    clock = Clock()
    with account_lease(CAMPAIGN_MAKER, backend=Mutexes()):
        state = state_at(tmp_path, clock)
        coordinator = CampaignCoordinator(state=state, runtime=StubRuntime(state, clock), clock=clock,
                                          control_root=tmp_path / 'control')
        coordinator.record_followups = None
        policy = bind_launch(coordinator, parse_policy(policy_row()))
        entry = policy.entries[0]
        missed_skip(state, entry, reason=reason)
        if ended:
            clock.value = entry.end + timedelta(minutes=1)
        # A consumed date may idle; a reopened window never does before its end.
        assert lfc_campaign_idle.eligible(coordinator, policy) is idle
