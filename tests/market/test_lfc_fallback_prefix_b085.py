"""Guards: B085 replay validates fallback authority before later claims/fills."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_campaign_runtime import runtime_at
from tests.market.test_lfc_f2_cash_mirror_b082 import cash_activity, observed
from tests.market.test_lfc_f2_inventory_b080 import observation
from tests.market.lfc_campaign_fixtures import private_result
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_capital import CapitalBook, CapitalRefused
from weather.market.lfc_capital_reads import synchronize
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha


@pytest.fixture(autouse=True)
def guarded_account():
    with account_lease(MAKER, backend=Mutexes()):
        yield


def fallback_runtime(tmp_path):
    runtime = runtime_at(tmp_path)
    policy = parse_policy(example_policy())
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    runtime.policy_path.write_text(json.dumps(policy.raw))
    runtime.clock.value = entry.start + timedelta(seconds=1)
    ledger = runtime.state.ledger
    synchronize(ledger, runtime.original_baseline(ledger),
        observation(ledger, runtime.clock, positions={}, cash='302'), anchor_mode='enrollment')
    second = runtime.clock.now()
    runtime.clock.value += timedelta(microseconds=250000)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, runtime.clock, positions={}, cash='302'), anchor_mode='session')
    source, proof = cash_activity(runtime.clock, 'DEPOSIT', '20', timestamp=int(second.timestamp()))
    runtime.clock.value += timedelta(seconds=2)
    read = observed(ledger, runtime.clock, source, proof, '321', positions={})
    assert synchronize(ledger, CapitalBook(ledger).inventory_anchor, read, anchor_mode='session')['cash_bridge_complete']
    assert any(value.get('surplus_only') for value in CapitalBook(ledger).cash_capture_bindings.values())
    return runtime, policy, entry


@pytest.mark.parametrize('warm', [False, True])
def test_fallback_replays_after_claim_fill_postcheck_owner_close_and_status(tmp_path, monkeypatch, capsys, warm):
    runtime, policy, entry = fallback_runtime(tmp_path)
    state = runtime.state
    claim = state.claim(entry, policy, runtime.clock.now())
    _, result = private_result(runtime, claim, faults=(), matched='20')
    runtime.save_result(claim, result)
    assert state.ledger.legs['s:1']['size_matched'] == '20'
    if warm:
        state.ledger._replay()  # Same object, full later rows, cache rebuilt.
    else:
        state.ledger = Ledger.open(state.ledger.path, clock=runtime.clock.now)
    read = observation(state.ledger, runtime.clock, positions={'t': '20'}, cash='311')
    read['since'] = str(int(datetime.fromisoformat(state.ledger.rows[0]['recorded_at_utc']).timestamp()))
    read['trades'] = [{'status': 'CONFIRMED', 'maker_orders': [{'order_id': 'o', 'matched_amount': '20'}]}]
    runtime.lease = SimpleNamespace(check=lambda: None)
    runtime.workload_path = tmp_path/'fixture-workload'
    @contextmanager
    def admission():
        yield
    monkeypatch.setattr(runtime, 'admission', admission)
    monkeypatch.setattr(runtime, 'read_account', lambda: read)
    proof = runtime.postcheck(claim, runtime.saved_result(claim))
    assert proof['money_accounting_complete'] is True and proof['unknown_submit'] is False
    assert list((state.root/'postchecks').glob('*.json'))
    runtime.reload_ledger()
    incident = state.latch(claim['attempt_id'], 'claimed_attempt_interrupted', runtime.clock.now())
    sha = file_sha(state.root/'incidents'/(incident+'.json'))
    monkeypatch.setattr('sys.stdin.isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda: 'close '+sha[:12])
    from weather.market.lfc_campaign_owner_close import owner_close
    assert owner_close(runtime, incident) == 0
    assert state.incidents() == [] and state.pending() == []
    from weather.market.lfc_campaign_control import control_record
    from weather.market.lfc_campaign_status import report
    from weather.market import lfc_campaign_status as status
    from weather.market import lfc_campaign_guard as guard
    completed = runtime.clock.now() + timedelta(seconds=1)
    control_record(runtime.control_root, claim['attempt_id'], phase='COMPLETE', now=completed)
    watch = status.watch_status
    monkeypatch.setattr(status, 'watch_status', lambda row: watch(row, now=completed))
    release = {'maker_address': MAKER, 'ledger_genesis_sha256': state.ledger.row_sha256(0),
               'state_id': state.verify()['state_id'], 'campaign_path': str(runtime.policy_path)}
    monkeypatch.setattr(guard, 'account_lease_busy', lambda maker: False)
    assert report(SimpleNamespace(release='fixture', release_sha256='a'*64), load_release=lambda *args: release,
                  validate_release=lambda value: None, root=lambda: runtime.pilot_root,
                  state_root=state.root.parent, control_root=runtime.control_root) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['state'] == 'STATUS'
    runtime.clock.value += timedelta(days=1)
    fresh = observation(state.ledger, runtime.clock, positions={'t': '20'}, cash='311')
    assert synchronize(state.ledger, CapitalBook(state.ledger).inventory_anchor, fresh, anchor_mode='session')['cash_bridge_complete']
    assert CapitalBook(Ledger.open(state.ledger.path, clock=runtime.clock.now)).figures() == CapitalBook(state.ledger).figures()


@pytest.mark.parametrize('warm', [False, True])
def test_fallback_followed_by_later_anchor_then_claim_replays(tmp_path, warm):
    runtime, policy, entry = fallback_runtime(tmp_path)
    ledger = runtime.state.ledger
    runtime.clock.value += timedelta(seconds=1)
    synchronize(ledger, CapitalBook(ledger).inventory_anchor,
        observation(ledger, runtime.clock, positions={}, cash='321'), anchor_mode='session')
    runtime.state.claim(entry, policy, runtime.clock.now())
    expected = CapitalBook(ledger).figures()
    if warm:
        ledger._replay()
    else:
        ledger = Ledger.open(ledger.path, clock=runtime.clock.now)
    assert CapitalBook(ledger).figures() == expected


def test_historical_cut_does_not_waive_a_current_pending_claim(tmp_path):
    runtime, policy, entry = fallback_runtime(tmp_path)
    ledger = runtime.state.ledger
    runtime.state.claim(entry, policy, runtime.clock.now())
    before = ledger.path.read_bytes()
    with pytest.raises(CapitalRefused, match='f2_anchor_postchecks_pending'):
        synchronize(ledger, CapitalBook(ledger).inventory_anchor,
            observation(ledger, runtime.clock, positions={}, cash='321'), anchor_mode='session')
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize('bridge_exists', [False, True])
def test_first_pre_go_uses_lower_funding_after_enrollment_reference_fallback(tmp_path, monkeypatch, bridge_exists):
    from weather.market import lfc_campaign_runtime, lfc_campaign_visibility, lfc_cli, re1_owner_checks
    from weather.market import lfc_session_status
    from weather.market.lfc_f2_pinb import example_policy as pinb_policy
    from tests.market.test_lfc_f2_cash_mirror_b082 import single_redemption
    from weather.market.mm_stage2_hold import digest
    runtime = runtime_at(tmp_path)
    policy = parse_policy(pinb_policy())
    runtime.policy_path.write_text(json.dumps(policy.raw))
    entry = next(e for e in policy.entries if e.local_date == '2026-11-12')
    runtime.clock.value = entry.start + timedelta(microseconds=250000)
    runtime.lease = SimpleNamespace(check=lambda: None)
    @contextmanager
    def admission():
        yield
    monkeypatch.setattr(runtime, 'admission', admission)
    def complete(positions, cash):
        ledger = runtime.state.ledger
        read = observation(ledger, runtime.clock, positions=positions, cash=cash)
        read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
        return read
    monkeypatch.setattr(runtime, 'read_account', lambda: complete({'203': '20'}, '302'))
    if bridge_exists:
        assert runtime.core_proof(runtime.state.ledger, runtime.read_account())['capital']['funding_native'] == 300_000_000
    assert runtime.confirm_funding()['funding_native'] == 300_000_000
    ledger = runtime.state.ledger
    assert any(row['event'] == 'f2_session_anchor' for row in ledger.rows) is bridge_exists
    source, receipt = single_redemption('203', '20', '20', '0x'+'6'*64, '0x'+'e'*64)
    source['timestamp'] = int(runtime.clock.now().timestamp())
    receipt.update(rows=[source], rows_sha256=digest([source]))
    runtime.clock.value += timedelta(seconds=2)
    read = observed(ledger, runtime.clock, source, receipt, '327', positions={})
    read['since'] = str(int(datetime.fromisoformat(ledger.rows[0]['recorded_at_utc']).timestamp()))
    monkeypatch.setattr(runtime, 'read_account', lambda: read)
    monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', tmp_path/'owner-only-stop-never-created')
    monkeypatch.setattr(lfc_campaign_runtime, 'workstation_headroom', lambda: {})
    monkeypatch.setattr(lfc_campaign_visibility, 'disk_headroom', lambda path: {})
    monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *args, **kwargs: True)
    monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: 'f'*40)
    monkeypatch.setattr(runtime, 'readiness', lambda *args: {'timeouts_seconds': {},
        'selection_sha256': 'a'*64, 'readiness_directory': 'readiness/inert', 'latency_seconds': {}})
    prepared = runtime.pre_go(entry, policy)
    funding = 300_000_000 if bridge_exists else 282_000_000
    assert prepared['money_proof']['capital']['funding_native'] == funding
    assert prepared['money_proof']['money_accounting_complete'] is True
    book = CapitalBook(runtime.state.ledger)
    assert book.figures()['funding_native'] == funding and book.profit == 0
    book.gate(reserve=str(funding/1_000_000), available_cash='327', loss_basis='net_of_retained_gains')
    with pytest.raises(CapitalRefused, match='capital_total_ceiling'):
        from decimal import Decimal
        book.gate(reserve=str(Decimal(funding+1)/1_000_000), available_cash='327', loss_basis='net_of_retained_gains')
    assert not runtime.state.incidents() and not runtime.state.ledger.autostart_claims
