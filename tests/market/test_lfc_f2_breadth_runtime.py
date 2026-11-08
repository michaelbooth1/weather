"""Owner-runtime plumbing uses inert clients and synthetic public snapshots.

Guards: B057 runtime protocol/arm wiring, all-city single-ledger placement and retained proof.
No SDK client, signer, credential source, task, reader or network is exercised.
"""
from copy import deepcopy
from decimal import Decimal

import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_breadth import cities, NOW
from tests.market.test_lfc_f2_capital import install, MAKER
from tests.market.test_lfc_f2_capital_reads import native_packet, packet
from tests.market.test_lfc_f2_repost import FillingAccount, FundedRaw
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority, ScheduledProfile
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_capital_reads import read_activity
from weather.market.lfc_f2_breadth import example_policy, PROTOCOL
from weather.market.lfc_f2_evidence import F2Status
from weather.market.lfc_f2_runtime import run_live
from weather.market.lfc_f2_selection import build_table
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_session_driver import SPENDERS
from weather.market.re1_attended import SecretGuard


@pytest.mark.parametrize('fills', [False, True])
def test_actual_owner_runtime_builds_twelve_bands_with_arms_and_no_external_capability(tmp_path, monkeypatch, fills):
    clock = Clock(NOW)
    row = example_policy(); row['max_session_seconds'] = 900 if fills else 300
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    install(ledger, cash='300')
    account = FillingAccount(clock); account.fills_enabled = fills
    rows = cities()
    table = build_table(rows, now=NOW, policy=policy, cash='300', capital=CapitalBook(ledger).figures())
    snapshots = {r['condition_id']: r['snapshot'] for r in rows}
    clients, raws, signed_guards, sources = [], [], [], []
    class Client:
        def __init__(self, readonly):
            self.readonly, self.closed = readonly, False
        def close(self):
            self.closed = True
        @property
        def order_signer(self):
            raise AssertionError('Fixture never exposes a signing path')
    def build(fields, *, readonly=False, **kwargs):
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
    def venue(client, fields, guard, **kwargs):
        if kwargs.get('readonly'):
            return Reader(client)
        raw = FundedRaw(snapshots[kwargs['condition']], kwargs['directory'], clock=clock,
                        account=account, index=len(raws))
        raw.start = lambda: None
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
        sources.append(mode) or {'FUNDER_ADDRESS': MAKER}, SecretGuard()))
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
        def read():
            when = clock.now().isoformat()
            positions = {}
            for raw in account.raws:
                for order in raw.memory.orders.values():
                    if Decimal(order['size_matched']):
                        token = order['asset_id']
                        positions[token] = positions.get(token, Decimal(0)) + Decimal(order['size_matched'])
            return {'schema_version': 'lfc_campaign_account_read_v0.1', 'complete': True, 'errors': [],
                'maker_address': MAKER, 'since': str(int(NOW.timestamp())),
                'scope': 'account_wide_sdk_trades_and_f0_v2_positions', 'started_at_utc': when, 'ended_at_utc': when,
                'component_times': {key: {'started_at_utc': when, 'ended_at_utc': when}
                    for key in ('open_orders', 'trades', 'positions', 'balances', 'geography')},
                'open_orders': account.open_orders(),
                'positions': [{'asset': token, 'size': str(size)} for token, size in positions.items()],
                'trades': [row for raw in account.raws for row in raw.trades()], 'geography': {'blocked': False},
                'balances': account.raws[0].balances(), 'terminal_orders': {leg['order_id']: {
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
