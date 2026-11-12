"""Guards: T102 terminal claims can close same-second cash without hiding a fill."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import json

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_campaign_runtime import runtime_at
from tests.market.test_lfc_f2_cash_mirror_b082 import cash_activity, observed
from tests.market.test_lfc_f2_inventory_b080 import observation
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_ledger import Ledger


@pytest.fixture(autouse=True)
def guarded():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def pending_snapshot(tmp_path):
    runtime = runtime_at(tmp_path)
    policy = parse_policy(example_policy())
    runtime.policy_path.write_text(json.dumps(policy.raw))
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    runtime.clock.value = entry.start + timedelta(seconds=1)
    ledger, clock = runtime.state.ledger, runtime.clock
    synchronize(ledger, runtime.original_baseline(ledger), observation(ledger, clock, positions={}, cash='302'),
                anchor_mode='enrollment')
    stamp = clock.now()
    clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor, observation(ledger, clock, positions={}, cash='302'),
                anchor_mode='session')
    claim = runtime.state.claim(entry, policy, clock.now())
    source, proof = cash_activity(clock, 'DEPOSIT', '20', timestamp=int(stamp.timestamp()))
    clock.value += timedelta(seconds=2)
    read = observed(ledger, clock, source, proof, '321', positions={})
    read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
    return runtime, claim, read


@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('finished', [False, True])
def test_next_terminal_read_resolves_same_second_after_claim(tmp_path, reopen, finished):
    runtime, claim, read = pending_snapshot(tmp_path)
    ledger = runtime.state.ledger
    if finished:
        ledger.record('session_start', session_id='closed', autostart_attempt_id=claim['attempt_id'])
        ledger.record('session_end', session_id='closed')
    if reopen:
        runtime.state.ledger = ledger = Ledger.open(ledger.path, clock=runtime.clock.now)
    proof = runtime.core_proof(ledger, read)
    assert proof['money_accounting_complete'] and proof['cleanup_proven']
    assert proof['capital']['cash_bridge_complete'] and proof['unknown_submit'] is False
    assert not runtime.state.incidents()
    book = CapitalBook(ledger)
    assert book.expected_cash() == 321_000_000
    assert book.figures()['retained_gains_available_native'] == 0
    assert book.figures()['headroom_native'] <= 300_000_000
    before = ledger.path.read_bytes()
    assert runtime.core_proof(ledger, read)['money_accounting_complete']
    assert ledger.path.read_bytes() == before
    cold = Ledger.open(ledger.path, clock=runtime.clock.now)
    assert CapitalBook(cold).figures() == book.figures()
    ledger._replay()
    assert CapitalBook(ledger).figures() == book.figures()


@pytest.mark.parametrize('fault', ['personal_position', 'foreign_order', 'open_session', 'campaign_fill',
                                  'same_second_personal'])
def test_closing_read_never_absorbs_an_open_or_changed_account(tmp_path, fault):
    runtime, claim, read = pending_snapshot(tmp_path)
    ledger = runtime.state.ledger
    if fault == 'personal_position':
        read['positions'].append({'asset': 'personal', 'size': '20'})
    elif fault == 'foreign_order':
        read['open_orders'].append({'id': 'foreign'})
    elif fault == 'open_session':
        ledger.record('session_start', session_id='active', autostart_attempt_id=claim['attempt_id'])
    elif fault == 'campaign_fill':
        from tests.market.test_lfc_f2_capital import filled
        filled(ledger, 'late', token='campaign')
        # The ledger fill is missing from SDK trades and holdings.
    else:
        from tests.market.test_lfc_f2_personal_cash_b081 import owner_trade
        previous = CapitalBook(ledger).inventory_anchor['snapshot_at_utc']
        for side in ('BUY', 'SELL'):
            row = owner_trade(runtime.clock, side)
            row['matched_at'] = datetime.fromtimestamp(int(datetime.fromisoformat(previous).timestamp()),
                                                      tz=runtime.clock.now().tzinfo).isoformat()
            read['trades'].append(row)
    before = len(CapitalBook(ledger).inventory_anchors)
    try:
        proof = runtime.core_proof(ledger, read)
    except (CapitalRefused, TransientPrecheck):
        pass
    else:
        assert proof['money_accounting_complete'] is False
    assert len(CapitalBook(ledger).inventory_anchors) == before


@pytest.mark.parametrize('reopen', [False, True])
def test_pending_postcheck_closes_then_next_day_can_anchor(tmp_path, monkeypatch, reopen):
    from tests.market.lfc_campaign_fixtures import private_result
    runtime, claim, read = pending_snapshot(tmp_path)
    _, result = private_result(runtime, claim, faults=())
    runtime.save_result(claim, result)
    if reopen:
        runtime.state.ledger = Ledger.open(runtime.state.ledger.path, clock=runtime.clock.now)
    runtime.lease = SimpleNamespace(check=lambda: None)
    monkeypatch.setattr(runtime, 'read_account', lambda: read)
    monkeypatch.setattr(runtime, 'notify_control', lambda *args: None)
    coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=runtime.clock,
                                      control_root=runtime.control_root)
    assert coordinator.pending() is True
    assert not runtime.state.incidents() and not runtime.state.pending()
    runtime.clock.value += timedelta(days=1)
    fresh = observation(runtime.state.ledger, runtime.clock, positions={}, cash='321')
    assert synchronize(runtime.state.ledger, CapitalBook(runtime.state.ledger).inventory_anchor,
                       fresh, anchor_mode='session')['cash_bridge_complete']


@pytest.mark.parametrize('reopen', [False, True])
def test_partial_closing_capture_finishes_from_a_later_safe_read(tmp_path, monkeypatch, reopen):
    runtime, claim, read = pending_snapshot(tmp_path)
    ledger = runtime.state.ledger
    record = ledger.record
    def interrupted(event, **fields):
        result = record(event, **fields)
        if event == 'capital_activity':
            raise OSError('after durable cash fallback')
        return result
    monkeypatch.setattr(ledger, 'record', interrupted)
    with pytest.raises(OSError, match='durable cash fallback'):
        runtime.core_proof(ledger, read)
    monkeypatch.setattr(ledger, 'record', record)
    if reopen:
        runtime.state.ledger = ledger = Ledger.open(ledger.path, clock=runtime.clock.now)
    runtime.clock.value += timedelta(seconds=10)
    from tests.market.test_lfc_f2_cash_mirror_b082 import observed
    book = CapitalBook(ledger)
    source = next(value for value in read['capital_activity']['rows'])
    native = next(iter(book.native_groups.values()))
    fresh = observed(ledger, runtime.clock, source, native, '321', positions={})
    fresh['since'] = read['since']
    assert runtime.core_proof(ledger, fresh)['capital']['cash_bridge_complete']
    assert CapitalBook(Ledger.open(ledger.path, clock=runtime.clock.now)).expected_cash() == 321_000_000


def test_closing_snapshot_race_stays_pending_then_finishes_without_incident(tmp_path, monkeypatch):
    from tests.market.lfc_campaign_fixtures import private_result
    runtime, claim, read = pending_snapshot(tmp_path)
    _, result = private_result(runtime, claim, faults=())
    runtime.save_result(claim, result)
    earlier = CapitalBook(runtime.state.ledger).inventory_anchor['snapshot_at_utc']
    read['started_at_utc'] = earlier
    for component in read['component_times'].values():
        component['started_at_utc'] = earlier
    runtime.lease = SimpleNamespace(check=lambda: None)
    monkeypatch.setattr(runtime, 'read_account', lambda: read)
    monkeypatch.setattr(runtime, 'notify_control', lambda *args: None)
    coordinator = CampaignCoordinator(state=runtime.state, runtime=runtime, clock=runtime.clock,
                                      control_root=runtime.control_root)
    assert coordinator.pending() is True
    assert runtime.state.pending() and not runtime.state.incidents()
    runtime.clock.value += timedelta(seconds=10)
    ledger = runtime.state.ledger
    source = read['capital_activity']['rows'][0]
    native = read['capital_activity']['native_receipts'][source['transaction_hash']]
    fresh = observed(ledger, runtime.clock, source, native, '321', positions={})
    fresh['since'] = read['since']
    monkeypatch.setattr(runtime, 'read_account', lambda: fresh)
    assert coordinator.pending() is True
    assert not runtime.state.pending() and not runtime.state.incidents()
    assert CapitalBook(runtime.state.ledger).expected_cash() == 321_000_000


@pytest.mark.parametrize('warm', [False, True])
def test_go_refresh_reference_replays_after_the_same_claim_posts_and_fills(tmp_path, warm):
    from tests.market.lfc_campaign_fixtures import private_result
    runtime, claim, read = pending_snapshot(tmp_path)
    ledger = runtime.state.ledger
    assert runtime.core_proof(ledger, read)['capital']['cash_bridge_complete']
    _, result = private_result(runtime, claim, faults=(), matched='20')
    runtime.save_result(claim, result)
    if warm:
        ledger._replay()
    else:
        runtime.state.ledger = ledger = Ledger.open(ledger.path, clock=runtime.clock.now)
    fresh = observation(ledger, runtime.clock, positions={'t': '20'}, cash='311')
    fresh['since'] = read['since']
    proof = runtime.core_proof(ledger, fresh)
    assert proof['money_accounting_complete'] and proof['cleanup_proven']
    assert proof['capital']['cash_bridge_complete'] and proof['unknown_submit'] is False
    assert CapitalBook(ledger).expected_cash() == 311_000_000
    assert not runtime.state.incidents()
