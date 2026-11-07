"""Synthetic unattended lifecycle tests; no production filesystem or venue calls.

Guards: T004 B018 strict completion, atomic public outcomes, heartbeat and owner STOP.
"""
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from weather.market import lfc_cli, lfc_session_status as S
from weather.market.lfc_completion import complete_evidence, evidence_flags
from weather.market.lfc_completion import ledger_completion
from weather.market.lfc_ledger import Ledger
from tests.market.test_lfc_pilot import setup as pilot_setup
from tests.market.test_lfc_session_driver import World, FakeClock, FakeConsole, NOW, drive, D, SHA


def outcomes():
    return [json.loads(path.read_bytes()) for path in S.STATUS_DIRECTORY.glob('*.json')]


@pytest.mark.parametrize('field,value', [('evidence_complete', False), ('inventory_proven', False),
    ('unknown_submit', True), ('evidence_complete', 'true'), ('inventory_proven', None), ('unknown_submit', None)])
def test_driver_never_completes_with_missing_or_false_proofs(tmp_path, field, value):
    clock = FakeClock(NOW)
    world = World(tmp_path, clock)
    original = world.post
    def post():
        line = original()
        folder = next(world.root.glob('session-*'))
        path = folder / 'session_end.json'
        row = json.loads(path.read_bytes())
        row[field] = value
        path.write_text(json.dumps(row))
        return line
    world.post = post
    pack, _ = drive(world, clock)
    assert pack['stop_code'] == 'session_evidence_incomplete'
    assert not world.of('wallet-verify')
    assert outcomes()[0]['state'] == 'ATTENTION'


def test_prediction_proof_or_hash_is_required_even_if_summary_claims_complete(tmp_path):
    clock = FakeClock(NOW)
    world = World(tmp_path, clock)
    original = world.post
    def post():
        line = original()
        next(world.root.glob('session-*/journal.jsonl')).write_text('changed\n')
        return line
    world.post = post
    assert drive(world, clock)[0]['stop_code'] == 'session_evidence_incomplete'


def test_driver_requires_verify_proofs(tmp_path):
    clock = FakeClock(NOW)
    world = World(tmp_path, clock)
    world.overrides['verify'] = [([str({'status': 'PASS'})], 0)]
    pack, _ = drive(world, clock)
    assert pack['stop_code'] == 'verify_evidence_incomplete' and not world.of('wallet-verify')


@pytest.mark.parametrize('exception', [KeyboardInterrupt, RuntimeError, SystemExit])
def test_live_setup_exits_always_publish_without_exception_messages(tmp_path, monkeypatch, exception):
    canary = 'PRIVATE_KEY_secret_CREDENTIAL_PATH'
    def fail(*args, **kwargs): raise exception(canary)
    monkeypatch.setattr(lfc_cli, '_run_live', fail)
    with pytest.raises(exception): lfc_cli.run_live(SimpleNamespace())
    rows = outcomes()
    assert len(rows) == 1 and rows[0]['state'] == 'ATTENTION'
    assert not complete_evidence(rows[0])
    assert canary not in json.dumps(rows)


def test_heartbeat_is_immediate_then_every_sixty_seconds_and_stops(tmp_path):
    clock = FakeClock(NOW)
    elapsed = [0]
    status = S.SessionStatus(kind='test', clock=clock.now, monotonic=lambda: elapsed[0])
    status.tick()
    heartbeat = S.STATUS_DIRECTORY / (status.session_id + '.heartbeat.jsonl')
    for seconds in (1, 5, 59, 60, 119, 120):
        elapsed[0] = seconds
        clock.t = NOW + timedelta(seconds=seconds)
        status.tick()
    lines = heartbeat.read_text().splitlines()
    assert len(lines) == 3 and all(json.loads(line)['state'] == 'RUNNING' for line in lines)
    status.finish(reason='test_end')
    elapsed[0] = 180
    status.tick()
    assert heartbeat.read_text().splitlines() == lines
    assert len(outcomes()) == 1


def test_public_outcome_is_create_only(tmp_path):
    status = S.SessionStatus(kind='test')
    path = S.STATUS_DIRECTORY / (status.session_id + '.json')
    path.parent.mkdir()
    path.write_text('immutable prior record')
    with pytest.raises(FileExistsError): status.finish()
    assert path.read_text() == 'immutable prior record'


def test_owner_stop_during_session_runs_existing_cleanup_and_reports_fills(tmp_path, monkeypatch):
    session, venue, clock, ledger = pilot_setup(tmp_path)
    status = S.SessionStatus(kind='test', clock=clock.now, monotonic=clock.monotonic)
    chosen = next(r for r in session.table['rows'] if r['condition_id'] == session.condition)
    status.bind(session.session_id, directory=session.directory, selection=chosen, ledger=ledger)
    status.session, session.outcome_status = session, status
    original = clock.sleep
    requested = []
    def sleep(seconds):
        original(seconds)
        if session.posts == 2 and not requested:
            requested.append(clock.monotonic())
            S.OWNER_STOP_FILE.write_text('fixture owner stop')
    clock.sleep = sleep
    result = session.run(rehearsal_seconds=20)
    status.open_rows = venue.open_orders()
    # The public summary normally follows lfc_cli's end/attempt files.
    for name in ('attempt.json', 'session_end.json'):
        path = session.directory / name
        if not path.exists(): path.write_text('{}')
    row = status.finish(success=True, reason=result['reason'])
    assert result['reason'] == 'owner_stop' and clock.monotonic() - requested[0] < 5
    assert result['cleanup_ok'] and venue.open_orders() == []
    assert row['state'] == 'STOPPED' and row['orders_open_at_exit'] == []
    assert row['orders_placed']['count'] == 2 and row['orders_cancelled']['count'] == 2
    assert row['halt_reason'] == 'owner_stop' and row['evidence_sha256']['journal.jsonl']


def test_driver_stop_requests_graceful_cleanup_not_immediate_tree_kill(tmp_path):
    clock = FakeClock(NOW)
    world = World(tmp_path, clock)
    original = world.post
    def post():
        line = original()
        S.OWNER_STOP_FILE.write_text('fixture owner stop')
        return line
    world.post = post
    pack, _ = drive(world, clock)
    proc = world.of('live')[0]
    assert proc.stop_requested and proc.killed is None and proc.closed
    assert pack['stop_code'] == 'owner_stop' and pack['stopped_reason'] == 'owner_stop'
    assert outcomes()[0]['state'] == 'STOPPED'


def test_driver_pack_failure_still_writes_public_outcome(tmp_path, monkeypatch):
    clock = FakeClock(NOW)
    world = World(tmp_path, clock)
    cfg = D.DriverConfig(pin=world.pin, expect_commit=SHA, root=world.root, snap_dir=world.snap,
                         python='py', phase='t24')
    driver = D.SessionDriver(cfg, runner=world, clock=clock, console=FakeConsole())
    monkeypatch.setattr(driver, 'write_pack', lambda: (_ for _ in ()).throw(OSError('secret path')))
    pack, _ = driver.run()
    assert pack['stopped_reason'] == 'FAIL' and outcomes()[0]['state'] == 'ATTENTION'


@pytest.mark.parametrize('mode', ['normal', 'cleanup_failure', 'interrupt'])
def test_driver_outcome_on_every_handled_exit_is_small_and_allowlisted(tmp_path, mode):
    clock = FakeClock(NOW)
    world = World(tmp_path, clock)
    world.cleanup_ok = mode != 'cleanup_failure'
    if mode == 'interrupt': world.interrupts['live'] = [2]
    pack, _ = drive(world, clock)
    row = outcomes()[0]
    assert row['state'] == ('COMPLETE' if mode == 'normal' else 'ATTENTION')
    assert len(json.dumps(row)) < 10_000
    assert 'started_at_utc' in row and 'ended_at_utc' in row
    assert set(evidence_flags(row)) <= row.keys()
    assert set(row['evidence_sha256']) <= {'attempt.json', 'selection.json', 'journal.jsonl', 'prediction.json', 'session_end.json'}
    assert not {'pin', 'root', 'scope', 'maker_address', 'request', 'response', 'signature', 'credentials'} & row.keys()
    if mode == 'normal':
        assert complete_evidence(row) and row['orders_open_at_exit'] == []
        assert pack['stopped_reason'] == 'session_complete'


@pytest.mark.parametrize('field', ['evidence_complete', 'inventory_proven', 'unknown_submit'])
def test_missing_completion_flags_never_pass(field):
    row = {'evidence_complete': True, 'inventory_proven': True, 'unknown_submit': False}
    assert complete_evidence(row)
    del row[field]
    assert not complete_evidence(row) and not complete_evidence(evidence_flags(row))


def test_invalid_session_arguments_also_leave_a_public_outcome():
    with pytest.raises(SystemExit): lfc_cli.main(['live', '--unrecognized-fixture-flag'])
    assert outcomes()[0]['halt_reason'] == 'startup_refused'


@pytest.mark.parametrize('missing', [None, 'evidence_complete', 'inventory_proven', 'unknown_submit'])
def test_verify_reconstructs_proof_from_canonical_prediction_never_defaults(tmp_path, missing):
    clock = FakeClock(NOW)
    ledger = Ledger.create(tmp_path / 'ledger.jsonl', clock=clock.now, maker_address='0x' + 'a' * 40)
    ledger.record('session_start', session_id='S1', counted=True, directory='session')
    # Historical envelopes lacked copies; the prediction is the proof source.
    ledger.record('session_end', session_id='S1', reason='fixed_end', cleanup_ok=True)
    directory = tmp_path / 'session'
    directory.mkdir()
    (directory / 'journal.jsonl').write_bytes(b'fixture\n')
    from weather.market.lfc_recording_io import file_sha
    prediction = {'evidence_complete': True, 'inventory_proven': True, 'unknown_submit': False,
                  'journal_sha256': file_sha(directory / 'journal.jsonl')}
    if missing is not None: del prediction[missing]
    (directory / 'prediction.json').write_text(json.dumps(prediction))
    assert complete_evidence(ledger_completion(tmp_path, ledger)) is (missing is None)
