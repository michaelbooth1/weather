"""Guards: B065 measured verify/pre-entry/checkpoint/idle costs at campaign scale.

Forty synthetic dates, twelve bands and ten cancelled posts per band. All
adapters are closed rehearsal objects. Construction skips ledger disk rehashing,
snapshots, fixture fsyncs and repeated validation of the growing fixture prefix;
every measured phase uses the complete production verification methods.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from types import MethodType, SimpleNamespace
import pytest

from tests.market.test_lfc_campaign import Mutexes, bind_launch
from tests.market.test_lfc_f2_breadth import cities
from tests.market.test_lfc_f2_controller import setup, MAKER
from tests.market.test_lfc_f2_capital import install
from weather.market.lfc_campaign import CampaignCoordinator
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy, load_policy
from weather.market.lfc_campaign_runtime import Runtime, ScheduledAuthority
from weather.market.lfc_campaign_state import AccountState
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_freeze import capture
from weather.market.lfc_ledger import Ledger, take_baseline, write_baseline
from weather.market.mm_stage2_hold import canonical_bytes


@contextmanager
def fixture_writer(ledger):
    """Valid chained fixture rows, with one cold production replay afterwards."""
    def append(self, event, **fields):
        fields = {**getattr(self, 'policy_metadata', {}), **fields}
        row = self._row(len(self.rows), self.previous, self.clock, event, fields)
        row['schema_version'] = 'lfc_ledger_v0.4'
        raw = canonical_bytes(row)
        self._apply(row)
        with self.path.open('ab') as stream: stream.write(raw)
        self.rows.append(row); self._history_hash.update(raw); self._raw_len += len(raw)
        self.previous = hashlib.sha256(raw).hexdigest(); self._row_hashes.append(self.previous)
        return row
    ledger.record = MethodType(append, ledger)
    try: yield
    finally: del ledger.record


def native_history(ledger, number):
    """One daily zero-credit distribution receipt with 500 unrelated logs."""
    from tests.market.test_lfc_f2_native import log, SENDER
    from tests.market.test_lfc_f2_capital import activity
    from tests.market.test_lfc_f2_capital_reads import rpc_packet
    from weather.market.lfc_capital import record_activity
    from weather.market.mm_stage2_hold import digest
    tx = '0x' + f'{number:064x}'
    source = activity(cash='0', size='0', kind='REWARD', tx=tx)
    source['timestamp'] = int(ledger.clock().timestamp())
    logs = [{**log(1, receiver=SENDER, index=i), 'transactionHash': tx} for i in range(500)]
    receipt = {'transactionHash': tx, 'blockHash': '0x'+'b'*64, 'blockNumber': '0x123', 'status': '0x1', 'logs': logs}
    proof = {'transaction_hash': tx, 'rows': [source], 'rows_sha256': digest([source]),
             'receipt': rpc_packet(receipt), 'failure_type': None}
    sha = digest(proof)
    ledger.record('capital_native_group', proof=proof, proof_sha256=sha)
    record_activity(ledger, source, native_evidence=proof, native_group_sha256=sha)


def padding(journal, events):
    from weather.market.mm_stage2_hold import SCHEMA_VERSION
    for event, fields in events:
        row = {'schema_version': SCHEMA_VERSION, 'kind': 'journal', 'sequence': journal.sequence,
            'previous_sha256': journal.previous, 'recorded_at_utc': journal.clock().isoformat(),
            'event': event, **fields}
        raw = canonical_bytes(row); journal.handle.write(raw)
        journal.previous = hashlib.sha256(raw).hexdigest(); journal.sequence += 1
    journal.handle.flush()


def timed(fn):
    began = time.perf_counter(); value = fn()
    return time.perf_counter() - began, value


def measure(tmp_path, ledger, policy, clock, monkeypatch, day):
    from weather.market import lfc_campaign_runtime, lfc_cli, re1_owner_checks
    from weather.market.lfc_campaign_reads import ACCOUNT_READ_COMPONENTS
    from weather.market.lfc_retained_cache import RetainedCache
    from weather.market.lfc_recording_io import write_new
    entry = next(e for e in policy.entries if e.local_date > clock.now().date().isoformat())
    clock.base = entry.start; clock.seconds = 0
    ledger.clock = clock.now
    # Each phase gets its own cold process-local cache, as a scheduled tick does.
    def state(): return AccountState(tmp_path / 'state', ledger)
    verify_seconds, _ = timed(state().verify)
    path = tmp_path / 'campaign.json'; path.write_text(json.dumps(policy.raw))
    def runtime(s):
        value = Runtime(state=s, pilot_root=tmp_path, policy_path=path, release={}, clock=clock,
            control_root=tmp_path / 'control', task_enabled=lambda: True,
            hold_path=tmp_path / 'work.lock', heavy_hold_path=tmp_path / 'manual-hold')
        value.lease = SimpleNamespace(check=lambda: None)
        value.notify_control = lambda row: None  # Never show an owner toast.
        return value
    def account_read():
        stamp = clock.now().isoformat()
        return {'started_at_utc': stamp, 'ended_at_utc': stamp, 'component_times': {
            name: {'started_at_utc': stamp, 'ended_at_utc': stamp} for name in ACCOUNT_READ_COMPONENTS},
            'positions': [], 'open_orders': [], 'balances': {'available_collateral': '300'}}
    s = state(); r = runtime(s)
    r.read_account = account_read
    r.readiness = lambda *a: {'fixture_only': True}
    r.core_proof = lambda *a, **kw: {'money_accounting_complete': True, 'cleanup_proven': True}
    monkeypatch.setattr(lfc_campaign_runtime, 'workstation_headroom', lambda: {})
    monkeypatch.setattr(lfc_cli, 'session0_passed', lambda *a, **kw: True)
    monkeypatch.setattr(re1_owner_checks, 'code_identity', lambda: 'f' * 40)
    # Full coordinator phase before start(): exact history, freeze, follow-ups
    # (none due in this fixture), pending and retained validation. Stop at start.
    coordinator = CampaignCoordinator(state=s, runtime=r, clock=clock, control_root=tmp_path / 'control', followup=r.followup)
    p = bind_launch(coordinator, policy)
    r.wrapper_launch = coordinator.wrapper_launch
    coordinator.start = lambda *a: 'MEASURED_ENTRY'
    pre_entry_seconds, phase = timed(lambda: coordinator.tick(lambda: p))
    assert phase == 'MEASURED_ENTRY'
    prepared_seconds, prepared = timed(lambda: r.pre_go(entry, p))
    ledger = s.ledger  # pre_go reopened the writer and appended its T-40 anchor.
    # A retained claim supplies the same immutable-file validation workload;
    # starting=False avoids consuming a second date only for a timing sample.
    authority = ScheduledAuthority(r, s.claims()[-1], entry, p, prepared)
    authority.last_control = clock.monotonic()
    checkpoint_seconds, _ = timed(authority.check)
    idle_state = state(); idle_runtime = runtime(idle_state)
    clock.base = entry.start - timedelta(hours=2); clock.seconds = 0
    # A completed ancillary pass means no follow-up is due, as required by
    # B065. Use the real cadence callback and forbid all external reads.
    idle_state.save('followups/' + str(len(ledger.baselines)) + '-scale.json', {
        'observed_at_utc': clock.now().isoformat(), 'gaps': [], 'monetary_action': False,
        'money_proof_complete': True})
    idle_runtime.read_account = lambda: pytest.fail('No read is due on this idle tick')
    idle = CampaignCoordinator(state=idle_state, runtime=idle_runtime, clock=clock,
        control_root=tmp_path / 'control', followup=idle_runtime.followup)
    before = len(ledger.rows)
    idle_full_seed_seconds, result = timed(lambda: idle.tick(lambda: p))
    assert result == 'IDLE' and len(ledger.rows) == before
    assert (idle_state.root/'.idle-validation.json').exists()
    # The next scheduled process is cold; only the derived manifest persists.
    clock.seconds += 300
    idle_state = state(); idle_runtime = runtime(idle_state)
    idle_runtime.read_account = lambda: pytest.fail('No read is due on this idle tick')
    idle = CampaignCoordinator(state=idle_state, runtime=idle_runtime, clock=clock,
        control_root=tmp_path / 'control', followup=idle_runtime.followup)
    idle_seconds, result = timed(lambda: idle.tick(lambda: p))
    assert result == 'IDLE' and len(ledger.rows) == before
    return {'day': day, 'ledger_rows': len(ledger.rows), 'claims': len(s.claims()),
        'results': len(ledger.autostart_results), 'verify_seconds': verify_seconds,
        'pre_entry_seconds': pre_entry_seconds, 'pre_go_seconds': prepared_seconds,
        'checkpoint_seconds': checkpoint_seconds, 'idle_seconds': idle_seconds,
        'idle_full_seed_seconds': idle_full_seed_seconds,
        'idle_ledger_rows_written': len(ledger.rows)-before,
        'ntfs_change_stamps': RetainedCache().signature(ledger.path)[-1] is not None}, ledger


def exercise_campaign(tmp_path, monkeypatch, record_property, last_day):
    # A hard bound protects the shared workstation if a future regression loops.
    stop = threading.Event(); started = time.perf_counter(); observed_commit = [0.0]
    def watchdog():
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('ram', 'ram_free', 'commit', 'commit_free', 'virtual', 'virtual_free', 'extended')]
        while not stop.wait(1):
            mem = Memory(); mem.length = ctypes.sizeof(mem)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)) or not mem.commit:
                os._exit(125)
            used = (mem.commit-mem.commit_free)/mem.commit
            observed_commit[0] = max(observed_commit[0], used * 100)
            if time.perf_counter()-started > 570 or used >= .85:
                os._exit(124)
    thread = threading.Thread(target=watchdog, daemon=True); thread.start()
    metrics = []; bytes_written = 0
    real_verify = AccountState.verify
    real_retained = AccountState.require_retained_evidence
    real_fsync = os.fsync
    try:
        row = example_policy(); row.update(enabled=True, max_session_seconds=300)
        policy = parse_policy(row)
        with account_lease(MAKER, backend=Mutexes()):
            ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=lambda: policy.entries[0].start, maker_address=MAKER)
            install(ledger, cash='300'); state = None
            for number, entry in enumerate(policy.entries[:last_day], 1):
                if state is not None and entry.local_date >= '2026-11-17' and not any(r['event']=='autostart_freeze' for r in ledger.rows):
                    ledger.clock = lambda: datetime(2026, 11, 16, 22, 55, tzinfo=timezone.utc)
                    capture(state, policy, ledger.clock())
                with fixture_writer(ledger), monkeypatch.context() as fixture_io:
                    # Generate immutable input bytes without benchmarking SSD
                    # write-through latency thousands of times. Restore fsync
                    # before every measured production read/write phase.
                    fixture_io.setattr(os, 'fsync', lambda fd: None)
                    # Prefix validity is checked cold at each measured size.
                    # Each newly generated session still proves its own actual
                    # journal/intents/ACKs before its result can be closed.
                    fixture_io.setattr(AccountState, 'verify', lambda self, **kw: self.read(self.root/'identity.json'))
                    fixture_io.setattr(AccountState, 'require_retained_evidence', lambda self: None)
                    ledger.clock = lambda: entry.start
                    if not any(r['label'] == 't40' and r['at_utc'] == entry.start.isoformat() for r in ledger.baselines):
                        baseline = take_baseline(label='t40', now=entry.start, maker_address=MAKER,
                            positions=[], open_orders=[], available_collateral='300')
                        write_baseline(tmp_path, baseline, ledger)
                    controller, account, status, ledger, clock = setup(tmp_path, k=12, enrolled=True,
                        shared_ledger=ledger, shared_state=state, session_id='cost-' + str(number),
                        base=entry.start, policy_row=policy.raw, universe_rows=cities(entry.start))
                    state, claim = account.state, account.claim
                    # Fixture generation samples the finite five-minute driver
                    # at thirty-second clock steps. Monetary decisions and
                    # terminal proofs are real; six-hour observation counts
                    # are supplied by the streamed padding below.
                    ordinary_sleep = clock.sleep
                    clock.sleep = lambda seconds: ordinary_sleep(max(30, seconds))
                    # Shared account heartbeat: one pair per five seconds, not
                    # twelve duplicated account heartbeats. Band snapshots are
                    # sampled once per minute; the real fixture snapshot is kept.
                    padding(controller.journal, ((kind, {}) for _ in range(4320)
                        for kind in ('heartbeat_request', 'heartbeat_response')))
                    for band in controller.bands:
                        snapshot = band.venue.raw.memory.public_input
                        padding(band.journal, (('market_snapshot', {'snapshot': snapshot}) for _ in range(360)))
                        with monkeypatch.context() as muted:
                            muted.setattr(band, 'control', lambda **kw: None)
                            for _ in range(4):
                                for leg in band.TRADE_LEGS:
                                    oid = band.submit(leg, band.prices[leg]); band.cancel_leg(oid)
                    result = controller.run()
                    assert result['cleanup_ok'] and result['post_count'] == 120
                    outcome = status.finish(success=True)
                    from weather.market.lfc_campaign_proof import local_money_proof
                    from weather.market.mm_stage2_hold import digest
                    local = local_money_proof(controller.directory, ledger=ledger, session_id=controller.session_id,
                        attempt_id=claim['attempt_id'], outcome=outcome)
                    assert local['complete']
                    r = Runtime(state=state, pilot_root=tmp_path, policy_path=tmp_path/'campaign.json', release={},
                        clock=clock, control_root=tmp_path/'control', task_enabled=lambda: True,
                        hold_path=tmp_path/'work.lock', heavy_hold_path=tmp_path/'manual-hold')
                    r.save_result(claim, {'session_id': controller.session_id, 'outcome': outcome,
                        'evidence_complete': True, 'inventory_proven': True, 'unknown_submit': False,
                        'local_money_proof': local, 'private_evidence_directory': controller.directory.name})
                    _, sha, retained = state.retained_result(claim)
                    state.close(claim, {'money_accounting_complete': True, 'cleanup_proven': True,
                        'unknown_submit': False, 'result_sha256': sha, 'private_evidence_sha256': digest(retained)}, clock.now())
                bytes_written += sum(path.stat().st_size for path in controller.directory.rglob('*') if path.is_file())
                assert bytes_written < 450_000_000, 'bounded synthetic output budget'
                native_history(ledger, number)
                # Build and final-size measurement are separate bounded calls.
                # Reuse the complete retained input with the remeasure test.
                if number in (1, 20) or last_day == 1:
                    assert AccountState.verify is real_verify
                    assert AccountState.require_retained_evidence is real_retained
                    assert os.fsync is real_fsync
                    ledger = Ledger.open(ledger.path, clock=clock.now, maker_address=MAKER)
                    state = AccountState(tmp_path/'state', ledger)
                    measurement, ledger = measure(tmp_path, ledger, policy, clock, monkeypatch, number)
                    state = AccountState(tmp_path/'state', ledger)
                    metrics.append(measurement)
                    metrics[-1]['retained_private_bytes'] = bytes_written
                    metrics[-1]['peak_commit_percent'] = observed_commit[0]
                    print(json.dumps(metrics[-1]), flush=True)
                    (tmp_path/'metrics.json').write_text(json.dumps(metrics, indent=2))
            record_property('scale_metrics', json.dumps(metrics))
    finally:
        stop.set(); thread.join(timeout=2)


@pytest.mark.skipif(os.name != 'nt', reason='Windows workstation performance and commit-charge fixture')
def test_one_day_fixture_uses_real_proofs_and_bounded_construction(tmp_path, monkeypatch, record_property):
    exercise_campaign(tmp_path, monkeypatch, record_property, 1)


@pytest.mark.skipif(os.name != 'nt', reason='Windows workstation performance and commit-charge fixture')
def test_day_one_twenty_forty_final_ledger_and_idle_costs(tmp_path, monkeypatch, record_property, pytestconfig):
    if not pytestconfig.getoption('--lfc-build-scale', default=False):
        pytest.skip('Explicit bounded synthetic fixture construction required')
    exercise_campaign(tmp_path, monkeypatch, record_property, 40)


@pytest.mark.skipif(os.name != 'nt', reason='Windows workstation performance and commit-charge fixture')
def test_day_one_twenty_final_costs(tmp_path, monkeypatch, record_property, pytestconfig):
    if not pytestconfig.getoption('--lfc-build-scale', default=False):
        pytest.skip('Explicit bounded synthetic fixture construction required')
    exercise_campaign(tmp_path, monkeypatch, record_property, 20)
