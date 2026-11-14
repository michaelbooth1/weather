"""Owner adapter wiring through inert venues and synthetic account claims.

Guards: B036 two-client isolation, one account claim and per-band retained proof.
No SDK client, credentials, network, signing or Scheduler is constructed.
"""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_capital import MAKER, install
from tests.market.test_lfc_f2_controller import Account, Raw, NOW
from tests.market.test_lfc_f2_selection import universe
from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import ScheduledProfile, ScheduledAuthority
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_f2_evidence import F2Status
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_f2_runtime import run_live
from weather.market.lfc_f2_selection import build_table
from weather.market.lfc_ledger import Ledger
from weather.market.re1_attended import SecretGuard


@pytest.mark.parametrize('close_failure', [False, True])
def test_owner_adapter_builds_two_independent_inert_clients_with_one_claim(tmp_path, monkeypatch, close_failure):
    from weather.market import re1_transport as transport, re1_owner_checks as checks, lfc_pilot
    from weather.market import lfc_campaign_runtime as adapter
    clock = Clock(NOW)
    row = example_policy()
    row['max_session_seconds'] = 300
    policy = parse_policy(row)
    entry = next(e for e in policy.entries if e.local_date == '2026-11-11')
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address=MAKER)
    install(ledger, '300')
    account = Account(clock)
    state = AccountState(tmp_path / 'state', ledger)
    source = universe()
    table = build_table(source, now=clock.now(), policy=policy, cash='300', capital=CapitalBook(ledger).figures())
    by_id = {r['condition_id']: r for r in source}
    clients = []
    def client(*a, **kw):
        obj = SimpleNamespace(close=lambda: None)
        clients.append(obj)
        return obj
    closed = []
    reader = SimpleNamespace(balances=lambda: {'available_collateral': '300'}, open_orders=lambda: [],
                             close=lambda: closed.append('reader'))
    def venue(client, fields, guard, **kw):
        if kw.get('readonly'):
            return reader
        raw = Raw(by_id[kw['condition']]['snapshot'], kw['directory'], clock=clock,
                  account=account, index=len(account.raws))
        raw.fixture_stream_factory, raw.fixture_directory = kw['stream_factory'], kw['directory']
        def close():
            closed.append(raw.index)
            if close_failure and raw.index == 1:
                raise RuntimeError('fixture_close_failure')
        raw.client, raw.start, raw.close = client, lambda: None, close
        return raw
    public = SimpleNamespace(snapshot=lambda condition, tokens, **kw: by_id[condition]['snapshot'])
    monkeypatch.setattr(transport, 'load_owner_credentials', lambda _: ({'FUNDER_ADDRESS': MAKER}, SecretGuard()))
    monkeypatch.setattr(transport, 'build_client', client)
    monkeypatch.setattr(transport, 'OwnerVenue', venue)
    monkeypatch.setattr(checks, 'code_identity', lambda: 'f' * 40)
    monkeypatch.setattr(adapter, 'selection_account_screen', lambda *a: None)
    monkeypatch.setattr(lfc_pilot, 'LfcPublicBooks', lambda **kw: public)
    from weather.market import lfc_ledger
    monkeypatch.setattr(lfc_ledger, 'fetch_account_positions', lambda _: [])
    with account_lease(MAKER, backend=Mutexes()):
        state.enroll(clock.now())
        claim = state.claim(entry, policy, clock.now())
        status = F2Status(kind='autostart', clock=clock.now, monotonic=clock.monotonic,
                         policy_metadata={key: claim[key] for key in ('policy_name', 'policy_revision', 'evidence_lane')})
        status.directory, status.stop_file = tmp_path / 'public', tmp_path / 'fixture-owner-stop'
        runtime = SimpleNamespace(state=state, clock=clock, pilot_root=tmp_path,
            read_account=lambda: {}, core_proof=lambda *a: {'money_accounting_complete': True, 'cleanup_proven': True})
        authority = object.__new__(ScheduledAuthority)
        authority.__dict__.update(policy=policy, entry=entry, claim=claim, profile=ScheduledProfile(policy, entry),
            prepared={'preflight': {'timeouts_seconds': {'get': 1}}}, baseline={}, protocol='lfc_autostart_v2',
            preflight=lambda **kw: None, selection=lambda: table, start_gates=lambda **kw: [],
            confirmation=lambda *a: {'fixture_only': True}, confirmation_valid=lambda *a: True,
            check=lambda **kw: None, session_end=lambda started, maximum: entry.session_end(started))
        if close_failure:
            with pytest.raises(RuntimeError, match='fixture_close_failure'):
                run_live(runtime, authority, status)
        else:
            assert run_live(runtime, authority, status) == 0
        assert closed == [1, 0, 'reader']
        outcome = status.finish(success=not close_failure)
        assert outcome['state'] == ('ATTENTION' if close_failure else 'COMPLETE')
        assert outcome['orders_placed']['count'] == 4
        assert len(clients) == 3 and len(state.claims()) == 1 and ledger.counted_sessions() == 1
        assert [len(raw.calls) for raw in account.raws] == [2, 2]
        from tests.market.test_lfc_f2_repost import campaign_stream, wire_trade
        for raw in account.raws:
            order = next(iter(raw.memory.orders.values()))
            wire = wire_trade(dict(order, size_matched='5'), raw.memory.condition)
            normalized = campaign_stream(raw)._normalize_event(wire)
            assert normalized[0]['trade_id'] == wire['id']
        from weather.market.lfc_campaign_proof import local_money_proof
        proof = local_money_proof(status.evidence_directory, ledger=ledger, session_id=status.session_id,
                                 attempt_id=claim['attempt_id'], outcome=outcome)
        assert proof['complete'], proof
