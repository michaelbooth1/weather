"""Owner-runtime plumbing uses inert clients and synthetic public snapshots.

Guards: B057 runtime protocol/arm wiring, all-city single-ledger placement and retained proof.
No SDK client, signer, credential source, task, reader or network is exercised.
"""
from copy import deepcopy
from decimal import Decimal
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_breadth import cities, NOW
from tests.market.test_lfc_f2_capital import MAKER
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from tests.market.test_lfc_f2_repost import FillingAccount, FundedRaw
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority, ScheduledProfile
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook, ASSET
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_f2_breadth import example_policy, PROTOCOL
from weather.market.lfc_f2_evidence import F2Status
from weather.market.lfc_f2_runtime import run_live
from weather.market.lfc_f2_selection import build_table
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import write_new
from weather.market.lfc_session_driver import SPENDERS
from weather.market.re1_attended import SecretGuard


@pytest.mark.parametrize('fills', [False, True])
def test_actual_owner_runtime_builds_twelve_bands_with_arms_and_no_external_capability(tmp_path, monkeypatch, fills):
    owner_runtime_fixture(tmp_path, monkeypatch, fills=fills)


def owner_runtime_fixture(tmp_path, monkeypatch, *, fills=False, setup_latency=0, audit=None, startup_failures=0):
    clock = Clock(NOW)
    row = example_policy(); row['max_session_seconds'] = 900 if fills or setup_latency else 300
    if setup_latency:
        row['enabled'] = True
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    from tests.market.test_lfc_f2_inventory_b080 import observation
    from weather.market.lfc_capital_reads import synchronize
    from weather.market.lfc_ledger import take_baseline, write_baseline
    baseline = take_baseline(label='t40', now=clock.now(), maker_address=MAKER, positions=[],
                             open_orders=[], available_collateral='300')
    write_baseline(tmp_path, baseline, ledger)
    synchronize(ledger, baseline, observation(ledger, clock, positions={}, cash='300'), anchor_mode='enrollment')
    account = FillingAccount(clock); account.fills_enabled = fills
    rows = cities()
    table = build_table(rows, now=NOW, policy=policy, cash='300', capital=CapitalBook(ledger).figures())
    snapshots = {r['condition_id']: r['snapshot'] for r in rows}
    clients, raws, signed_guards, sources, start_gaps = [], [], [], [], []
    class Client:
        def __init__(self, readonly):
            self.readonly, self.closed = readonly, False
        def close(self):
            self.closed = True
        @property
        def order_signer(self):
            raise AssertionError('Fixture never exposes a signing path')
    def build(fields, *, readonly=False, **kwargs):
        clock.sleep(setup_latency)
        client = Client(readonly); clients.append(client)
        return client
    class Reader:
        def __init__(self, client):
            self.client = client
        def balances(self):
            return {'available_collateral': '300', 'collateral_evidence': {
                'allowances': {address.lower(): '300000000' for address in SPENDERS.values()}}}
        def open_orders(self):
            return []
        def close(self):
            self.client.close()
    class CampaignRaw(FundedRaw):
        def submit(self, request, *, checkpoint=lambda: None):
            response = super().submit(request, checkpoint=checkpoint)
            previous = response['order_id']
            oid = '0x' + sha256(previous.encode()).hexdigest()
            row = self.memory.orders.pop(previous)
            self.memory.orders[oid] = {**row, 'id': oid}
            return {**response, 'order_id': oid}

    def venue(client, fields, guard, **kwargs):
        if kwargs.get('readonly'):
            return Reader(client)
        raw = CampaignRaw(snapshots[kwargs['condition']], kwargs['directory'], clock=clock,
                          account=account, index=len(raws))
        raw.fixture_stream_factory = kwargs['stream_factory']
        def start():
            clock.sleep(setup_latency / 4)
            if raw.index == 0 and len(start_gaps) < startup_failures:
                start_gaps.append(True)
                raise RuntimeError('user_stream_readiness')
        raw.start = start
        raw.close = client.close
        raws.append(raw)
        return raw
    class Public:
        def __init__(self, **kwargs):
            pass
        def snapshot(self, condition, tokens, *, checkpoint=lambda: None):
            checkpoint()
            return deepcopy(snapshots[condition]) | {'observed_at_utc': clock.now().isoformat()}
    from weather.market import re1_transport, re1_owner_checks, lfc_pilot, lfc_ledger, lfc_fees, lfc_cli
    monkeypatch.setattr(re1_transport, 'load_owner_credentials', lambda mode: (
        sources.append(mode) or {'FUNDER_ADDRESS': MAKER,
                                  'API_KEY': '00000000-0000-4000-8000-000000000001'}, SecretGuard()))
    monkeypatch.setattr(re1_transport, 'build_client', build)
    monkeypatch.setattr(re1_transport, 'OwnerVenue', venue)
    monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: '0' * 40)
    monkeypatch.setattr(lfc_pilot, 'LfcPublicBooks', Public)
    monkeypatch.setattr(lfc_ledger, 'fetch_account_positions', lambda maker: [])
    monkeypatch.setattr(lfc_fees, 'guard_signed_orders', lambda raw: signed_guards.append(raw))
    monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **k: True)
    with account_lease(MAKER, backend=Mutexes()):
        state = AccountState(tmp_path / 'state', ledger); state.enroll(clock.now())
        claim = state.claim(entry, policy, clock.now())
        runtime = object.__new__(Runtime)
        runtime.state, runtime.clock, runtime.pilot_root = state, clock, tmp_path
        runtime.lease = SimpleNamespace(check=lambda: None)
        def read(*, activity=True):
            when = clock.now().isoformat()
            positions = {}
            for raw in account.raws:
                for order in raw.memory.orders.values():
                    if Decimal(order['size_matched']):
                        token = order['asset_id']
                        positions[token] = positions.get(token, Decimal(0)) + Decimal(order['size_matched'])
            balances = account.raws[0].balances() if account.raws else {
                'available_collateral': '300', 'assets': {ASSET: '300'},
                'collateral_evidence': {'balance': '300000000'}}
            balances['collateral_evidence']['allowances'] = {address.lower(): '300000000' for address in SPENDERS.values()}
            return {'schema_version': 'lfc_campaign_account_read_v0.1', 'complete': True, 'errors': [],
                'maker_address': MAKER, 'since': str(int(NOW.timestamp())),
                'scope': 'account_wide_sdk_trades_and_f0_v2_positions', 'started_at_utc': when, 'ended_at_utc': when,
                'component_times': {key: {'started_at_utc': when, 'ended_at_utc': when}
                    for key in ('open_orders', 'trades', 'positions', 'balances', 'geography')},
                'open_orders': account.open_orders(),
                'positions': [{'asset': token, 'size': str(size)} for token, size in positions.items()],
                'trades': [row for raw in account.raws for row in raw.trades()], 'geography': {'blocked': False},
                'balances': balances, 'terminal_orders': {leg['order_id']: {
                    'row': next(raw for raw in account.raws if leg['order_id'] in raw.memory.orders).order(leg['order_id']),
                    'started_at_utc': when, 'ended_at_utc': when} for leg in ledger.unresolved_legs() if leg['order_id']},
                'capital_activity': native_packet(read_activity(MAKER, int(NOW.timestamp()), int(clock.now().timestamp()),
                                                   get=lambda *a: packet(), sleep=lambda _: None))}
        runtime.read_account = read
        authority = object.__new__(ScheduledAuthority)
        authority.runtime, authority.pilot_root = runtime, tmp_path
        authority.claim, authority.entry, authority.policy = claim, entry, policy
        authority.profile, authority.protocol = ScheduledProfile(policy, entry), PROTOCOL
        authority.baseline = CapitalBook(ledger).anchor
        authority.prepared = {'preflight': {'timeouts_seconds': {'read': 2}}}
        authority.preflight = lambda **kwargs: None
        if setup_latency:
            runtime.policy_path = tmp_path / 'inert-campaign.json'
            write_new(runtime.policy_path, row)
            runtime.lease = SimpleNamespace(check=lambda: None)
            runtime.sidecar, runtime.control_root = None, tmp_path / 'inert-control'
            runtime.task_enabled = lambda: True
            authority.last_wall, authority.last_mono = clock.now(), clock.monotonic()
            authority.last_control = None
            authority.prepared.update(account_read=read(), expires_utc=(clock.now() + timedelta(seconds=120)).isoformat())
        else:
            authority.check = lambda **kwargs: account.checkpoint()
        authority.selection = lambda: table
        authority.confirmation = lambda *a: {'fixture_only': True}
        authority.confirmation_valid = lambda table, receipt: receipt == {'fixture_only': True}
        status = F2Status(kind='autostart', clock=clock.now, monotonic=clock.monotonic,
                          policy_metadata=policy.labels(entry.local_date))
        status.directory, status.stop_file = tmp_path / 'status', tmp_path / 'OWNER-STOP-FIXTURE'
        assert run_live(runtime, authority, status) == 0
        outcome = status.finish(success=True)
        assert outcome['state'] == 'COMPLETE' and len(outcome['bands']) == 12
        assert len(raws) == len(signed_guards) == 12 and len(clients) == 13
        assert len(start_gaps) == startup_failures
        assert sources == ['live'] and all(c.closed for c in clients)
        assert len(ledger.legs) >= 24 and ledger.counted_sessions() == 1
        if fills:
            assert len(ledger.legs) > 24
            assert status.session.results[status.session.bands[0].session_id]['reason'] == 'per_band_daily_filled_cap'
        intents = [r for r in ledger.rows if r['event'] == 'leg_intent']
        assert {r['quote_arm'] for r in intents} == {'learning-0.015', 'learning-0.025'}
        assert all(r['quote_day_utc'] == '2026-11-11' for r in intents)
        from weather.market.lfc_campaign_proof import local_money_proof
        proof = local_money_proof(status.evidence_directory, ledger=ledger, session_id=status.session_id,
                                 attempt_id=claim['attempt_id'], outcome=outcome)
        assert proof['complete'] and proof['unknown_submit'] is False, proof
        if audit is not None:
            audit(runtime, status, outcome, claim, proof)

        first_post = min(when for band in status.session.bands for when in band.order_created.values())
        go_read = getattr(authority, 'go_read', authority.prepared.get('account_read'))
        return {'first_post_seconds': first_post, 'go_read_age_seconds': (
            (NOW + timedelta(seconds=first_post)) - __import__('datetime').datetime.fromisoformat(go_read['started_at_utc'])
            ).total_seconds() if go_read else None, 'claims': len(ledger.autostart_claims),
            'incidents': state.incidents(), 'posts': len(ledger.legs)}


def test_closed_private_stream_during_setup_defers_same_claim_then_completes(tmp_path, monkeypatch):
    result = owner_runtime_fixture(tmp_path, monkeypatch, startup_failures=2)
    assert result['claims'] == 1 and not result['incidents'] and result['posts'] >= 24
