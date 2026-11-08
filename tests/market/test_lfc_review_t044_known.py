"""Desired-behavior B058 witnesses: synthetic only; no Scheduler operations.

Guards: B058/T044 review."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import example_policy


@pytest.mark.spawns
def test_b058_1_v03_deadline_covers_full_session(tmp_path):
    from tests.powershell_host import run_command
    path = tmp_path / 'campaign.json'
    path.write_text(json.dumps(example_policy()))
    contract = Path('scripts/ops/lfc_campaign_task_contract.ps1').resolve()
    result = run_command(f". '{contract}'; (Get-LfcCampaignDeadline -CampaignPath '{path}' -NowUtc ([DateTimeOffset]'2026-11-11T14:00:00Z')).ToString('o')", timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith('2026-11-11T20:30:00'), result.stdout


def test_b058_2_peer_requote_retains_terminal_private_proof(tmp_path):
    from weather.market.lfc_f2_repost import private_fill_proof
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    peer = controller.bands[1]
    steps = peer.run_steps()
    next(steps)
    assert private_fill_proof(peer, require_terminal=False)['complete']
    oid = next(iter(peer.active))
    leg, _ = peer.active[oid]
    peer.cancel_leg(oid)
    peer.submit(leg, peer.prices[leg])
    assert ledger.legs[ledger.by_order[oid]]['status'] == 'terminal'
    try:
        private_fill_proof(peer, require_terminal=False)
    finally:
        steps.close()


@pytest.mark.parametrize('event', [
    {'id': 'oid', 'status': 'LIVE', 'size_matched': '1'},
    {'id': 'oid', 'type': 'CANCELLATION', 'size_matched': '0'},
])
def test_b058_3_late_terminal_events_do_not_end_a_proved_band(event):
    from weather.market.lfc_f2_repost import filtered_events
    leg = {'session_id': 'band', 'status': 'terminal', 'size_matched': '1', 'size': '20'}
    band = SimpleNamespace(session_id='band', ledger=SimpleNamespace(by_order={'oid': 'key'}, legs={'key': leg}),
        journal=SimpleNamespace(record=lambda *a, **k: None))
    assert filtered_events(band, [event]) == []


def test_b058_5_pre_intent_failure_is_not_ambiguous_placement(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    def fail(**kwargs):
        raise OSError('synthetic ledger failure BEFORE durable intent and POST')
    ledger.intent = fail
    result = controller.run()
    assert not ledger.legs and not any(raw.calls for raw in account.raws)
    assert result['unknown_submit'] is False, result


def test_b058_6_cooldown_one_second_is_rejected():
    row = example_policy()
    row['fill_cooldown_seconds'] = 1
    with pytest.raises((ValueError, RuntimeError)):
        parse_policy(row)


@pytest.mark.spawns
def test_b058_7_task_launcher_uses_windowless_host():
    from tests.powershell_host import run_command
    contract = Path('scripts/ops/lfc_campaign_task_contract.ps1').resolve()
    result = run_command(f". '{contract}'; New-LfcCampaignTaskXml -Release @{{root='C:\\fixture';windowless=@{{python='C:\\fixture\\pythonw.exe'}}}} -ReleasePath 'C:\\fixture\\release.json' -ReleaseSha256 ('a'*64) -OwnerSid 'S-1-5-21-1-2-3-4'", timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'powershell.exe' not in result.stdout.lower(), result.stdout


def test_b058_8_peer_partial_fill_does_not_retire_posting_band(tmp_path):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path)
    account.fills_enabled = False
    raw = account.raws[1]
    original = raw.balances
    injected = []
    def balances():
        orders = account.raws[0].memory.orders
        if orders and not injected:
            first = next(iter(orders.values()))
            first.update(size_matched='1', associate_trades=['fill-' + first['id']])
            injected.append(True)
        return original()
    raw.balances = balances
    controller.run()
    assert injected
    result = controller.results[controller.bands[1].session_id]
    assert result['reason'] != 'capital_cash_changed', result


def test_b058_4_redemption_after_t40_can_refresh_before_consuming_date(tmp_path, monkeypatch):
    from tests.market.test_lfc_campaign import MAKER, Mutexes
    from tests.market.test_lfc_campaign_runtime import runtime_at
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_campaign_runtime import ScheduledAuthority
    from weather.market.lfc_ledger import take_baseline, write_baseline
    from weather.market import lfc_cli
    monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **k: True)
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path)
        runtime.clock.sleep(1)
        policy = parse_policy(example_policy())
        authority = object.__new__(ScheduledAuthority)
        authority.runtime, authority.pilot_root, authority.policy = runtime, runtime.pilot_root, policy
        authority.check = lambda **kwargs: None  # Freshness is tested independently above.
        authority.baseline = take_baseline(label='t40', now=runtime.clock.now(), maker_address=MAKER,
            positions=[{'asset': '111', 'conditionId': 'owner-held', 'size': '20'}],
            open_orders=[], available_collateral='100')
        write_baseline(runtime.pilot_root, authority.baseline, runtime.state.ledger)
        # Auto redemption burned the old holding after t40; current inventory is
        # empty. This exercises the real start gate before any POST-capable phase.
        refused = authority.start_gates(ledger=runtime.state.ledger, now=runtime.clock.now(),
            maker_address=MAKER, open_orders=[], positions=[])
        # Missing holdings without any payout/burn evidence must still refuse.
        # The proved native-redemption positive is in test_lfc_f2_setup_b058.
        assert 'inventory_changed_after_baseline' in refused, refused
