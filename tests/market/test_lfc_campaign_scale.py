"""Six-week retained-proof benchmark, with closed in-memory venue adapters.

Guards: B046 C4; 36 two-band sessions, no network, credential or Scheduler reads.
The controller clocks advance 300 seconds. Streaming synthetic heartbeat rows
bring each journal to a six-hour / five-second observation workload; only fixture
padding skips per-row fsync. Production journal durability is unchanged.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import time
from types import SimpleNamespace

from tests.market.test_lfc_campaign import Mutexes
from tests.market.test_lfc_f2_controller import setup, MAKER
from tests.market.test_lfc_f2_capital import install, activity
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_capital import CapitalBook, normalize_activity
from weather.market.lfc_f2_freeze import capture
from weather.market.lfc_f2_policy import example_policy
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import canonical_bytes, digest


def pad(journal, pairs=4320):
    # Build a valid retained chain without spending a benchmark's time in
    # ~1 million fixture fsync calls. No domain decision or mutation is mocked.
    for _ in range(pairs):
        for event in ('heartbeat_request', 'heartbeat_response'):
            from weather.market.mm_stage2_hold import SCHEMA_VERSION
            row = {'schema_version': SCHEMA_VERSION, 'kind': 'journal',
                   'sequence': journal.sequence, 'previous_sha256': journal.previous,
                   'recorded_at_utc': journal.clock().isoformat(), 'event': event}
            raw = canonical_bytes(row)
            journal.handle.write(raw)
            journal.previous = hashlib.sha256(raw).hexdigest()
            journal.sequence += 1
    journal.handle.flush()


def receipt_history(ledger, now):
    """Stream 300 fixture capital rows, 100 receipts with 500 logs apiece.

    One cold Ledger.open validates the generated chain and every native receipt.
    This avoids measuring quadratic fixture construction through live fsyncs.
    """
    from tests.market.test_lfc_f2_native import log, SENDER
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    sequence, previous = len(ledger.rows), ledger.previous
    with ledger.path.open('ab') as stream:
        def append(event, **fields):
            nonlocal sequence, previous
            raw = canonical_bytes({'schema_version': 'lfc_ledger_v0.4', 'kind': 'lfc_ledger',
                'sequence': sequence, 'previous_sha256': previous,
                'recorded_at_utc': now.isoformat(), 'event': event, **fields})
            stream.write(raw); sequence += 1; previous = hashlib.sha256(raw).hexdigest()
        for n in range(100):
            tx = '0x' + format(n + 1, '064x')
            source = activity(cash='0', size='0', kind='REWARD', tx=tx)
            source['timestamp'] = int(now.timestamp())
            logs = [{**log(1, receiver=SENDER, index=i), 'transactionHash': tx} for i in range(500)]
            receipt = {'transactionHash': tx, 'blockHash': '0x' + 'b' * 64, 'blockNumber': '0x123',
                       'status': '0x1', 'logs': logs}
            proof = {'transaction_hash': tx, 'rows': [source], 'rows_sha256': digest([source]),
                     'receipt': rpc_packet(receipt), 'failure_type': None}
            sha = digest(proof)
            append('capital_native_group', proof=proof, proof_sha256=sha)
            append('capital_activity', source=source, source_sha256=digest(source),
                   activity=normalize_activity(source, proof), native_group_sha256=sha)
            extra = activity(cash='0', size='0', kind='REWARD', tx='extra-' + str(n))
            extra['timestamp'] = int(now.timestamp())
            append('capital_activity', source=extra, source_sha256=digest(extra), activity=normalize_activity(extra))
    return Ledger.open(ledger.path, clock=ledger.clock, maker_address=MAKER)


def test_36_sessions_keep_real_admission_and_authority_within_their_time_budgets(tmp_path, monkeypatch, record_property):
    from weather.market import lfc_campaign_runtime as runtime_module, lfc_cli, re1_owner_checks, lfc_session_status
    from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS, account_read_age
    # No component below constructs an authenticated or public client.
    row = example_policy(); row.update(enabled=True, max_session_seconds=300)
    policy = parse_policy(row)
    monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', tmp_path / 'owner-stop-fixture')
    started = time.perf_counter()
    with account_lease(MAKER, backend=Mutexes()):
        ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: policy.entries[0].start, maker_address=MAKER)
        # Distribution receipts are large even for a wallet receiving no credit.
        ledger = receipt_history(ledger, policy.entries[0].start)
        install(ledger, cash='300')
        state = None
        journal_rows = 0
        for n, entry in enumerate(policy.entries[:36]):
            if state is not None and entry.local_date >= '2026-11-17' and not any(r['event'] == 'autostart_freeze' for r in ledger.rows):
                ledger.clock = lambda: datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
                capture(state, policy, ledger.clock())
            controller, account, status, ledger, clock = setup(tmp_path, enrolled=True,
                shared_ledger=ledger, shared_state=state, session_id='scale-' + str(n), base=entry.start,
                offset=row['quote_offset_pusd'], schedule={'enabled': True})
            state, claim = account.state, account.claim
            for journal in [controller.journal] + [band.journal for band in controller.bands]:
                pad(journal)
            result = controller.run()
            assert result['cleanup_ok'] and result['post_count'] == 4
            outcome = status.finish(success=True)
            from weather.market.lfc_campaign_proof import local_money_proof
            local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                                      attempt_id=claim['attempt_id'], outcome=outcome)
            assert local['complete']
            runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path / 'campaign.json',
                release={}, clock=clock, control_root=tmp_path / 'control', task_enabled=lambda: True,
                hold_path=tmp_path / 'work.lock', heavy_hold_path=tmp_path / 'manual-hold')
            runtime.save_result(claim, {'session_id': controller.session_id, 'outcome': outcome,
                'evidence_complete': True, 'inventory_proven': True, 'unknown_submit': False,
                'local_money_proof': local, 'private_evidence_directory': controller.directory.name})
            _, sha, retained = state.retained_result(claim)
            state.close(claim, {'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
                'result_sha256': sha, 'private_evidence_sha256': digest(retained)}, clock.now())
            journal_rows += sum(j.sequence for j in [controller.journal] + [band.journal for band in controller.bands])
        assert len(state.claims()) == 36 and len(ledger.sessions) == 72 and not ledger.open_sessions()
        expected_capital = CapitalBook(ledger).figures()
        cold_start = time.perf_counter()
        ledger = Ledger.open(ledger.path, clock=clock.now, maker_address=MAKER)
        assert CapitalBook(ledger).figures() == expected_capital
        state = AccountState(tmp_path / 'state', ledger)
        state.verify(); state.require_retained_evidence()
        cold_seconds = time.perf_counter() - cold_start
        # Pre-go follows the actual Runtime path. Only external facts and their
        # unrelated qualification checks are injected; retention remains real.
        entry = policy.entries[36]
        class AdmissionClock:
            def __init__(self): self.started = time.perf_counter()
            def now(self): return entry.start + timedelta(seconds=time.perf_counter() - self.started)
            def monotonic(self): return time.perf_counter()
            def sleep(self, seconds): raise AssertionError('unexpected admission retry in benchmark')
        clock = AdmissionClock()
        ledger.clock = clock.now
        path = tmp_path / 'campaign.json'; path.write_text(json.dumps(policy.raw))
        runtime = Runtime(state=state, pilot_root=tmp_path, policy_path=path, release={}, clock=clock,
            control_root=tmp_path / 'control', task_enabled=lambda: True, hold_path=tmp_path / 'work.lock',
            heavy_hold_path=tmp_path / 'manual-hold')
        runtime.lease = SimpleNamespace(check=lambda: None)
        monkeypatch.setattr(runtime_module, 'workstation_headroom', lambda: {})
        monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **k: True)
        monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: 'f' * 40)
        runtime.readiness = lambda *a: {'fixture_only': True}
        runtime.core_proof = lambda *a, **kw: {'money_accounting_complete': True, 'cleanup_proven': True}
        def read_account():
            stamp = clock.now().isoformat()
            return {'started_at_utc': stamp, 'ended_at_utc': stamp, 'component_times': {
                name: {'started_at_utc': stamp, 'ended_at_utc': stamp} for name in ACCOUNT_READ_COMPONENTS},
                'positions': [], 'open_orders': [], 'balances': {'available_collateral': '300'}}
        runtime.read_account = read_account
        begin = time.perf_counter()
        prepared = runtime.pre_go(entry, policy)
        go_seconds = time.perf_counter() - begin
        claim = state.claim(entry, policy, clock.now(), prepared=prepared)
        authority = ScheduledAuthority(runtime, claim, entry, policy, prepared)
        check_times = []
        for index in range(3):
            begin = time.perf_counter()
            authority.check(starting=index == 0)
            check_times.append(time.perf_counter() - begin)
        authority_seconds = max(check_times)
        assert go_seconds < 120 and authority_seconds < 15
        assert account_read_age(prepared['account_read'], clock.now()) < 120
        assert len(state.claims()) == 37 and not ledger.unresolved_legs()
        files = list(tmp_path.glob('session-*/**/journal.jsonl'))
        metrics = {'sessions': 36, 'bands': 72, 'capital_rows_seeded': 300, 'receipt_logs_each': 500,
            'ledger_rows': len(state.ledger.rows), 'journal_rows': journal_rows,
            'journal_bytes': sum(p.stat().st_size for p in files), 'cold_retained_seconds': cold_seconds,
            'pre_go_seconds': go_seconds, 'authority_seconds': authority_seconds,
            'go_account_age_seconds': account_read_age(prepared['account_read'], clock.now()),
            'total_seconds': time.perf_counter() - started,
            'ledger_sha256': file_sha(ledger.path), 'external_clients_constructed': 0}
        from weather.market.lfc_retained_cache import RetainedCache
        metrics['native_cache_sequence_supported'] = RetainedCache().signature(ledger.path)[-1] is not None
        (tmp_path / 'benchmark.json').write_text(json.dumps(metrics, indent=2))
        for key, value in metrics.items(): record_property(key, value)
