"""Guards: T1 code/input/latency pinning, create-only output and bounded fixture IO."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.backtesting.t1_fixtures import at, config, journal_bytes, payload, receipts, tolerance
from weather.backtesting import t1_cli
from weather.backtesting.t1_types import canonical


def inputs(tmp_path):
    latency = {'kind': 'observation_to_order_ack', 'sample_count': 1, 'synthetic': True,
               'samples': [{'observed_at': at(0), 'decided_at': at(1), 'acknowledged_at': at(2)}]}
    raw_latency = canonical(latency)
    raw_journal = journal_bytes()
    files = {'inputs': payload(), 'config': config(latency_source_sha256=hashlib.sha256(raw_latency).hexdigest()).projection(),
             'receipts': receipts(raw_journal), 'tolerance': asdict(tolerance()), 'latency-evidence': latency}
    args = []
    for name, value in files.items():
        path = tmp_path / (name + '.json')
        path.write_bytes(canonical(value))
        args.extend(['--' + name, str(path)])
    journal = tmp_path / 'journal.jsonl'
    journal.write_bytes(raw_journal)
    output = tmp_path / 'result.json'
    return [*args, '--journal', str(journal), '--output', str(output)], output


@pytest.mark.spawns
def test_full_fixture_accuracy_cli_and_source_origin(tmp_path):
    args, output = inputs(tmp_path)
    assert t1_cli.main(['accuracy', *args]) == 2
    report = json.loads(output.read_bytes())
    assert report['result']['status'] == 'CASH_PENDING'
    assert report['synthetic'] is True
    assert report['accuracy_certificate']['status'] == 'NOT QUALIFIED'
    assert len(report['code']['git_commit']) == 40
    assert report['code']['source_sha256']['t1_cli.py'] == hashlib.sha256(Path(t1_cli.__file__).read_bytes()).hexdigest()
    assert Path(t1_cli.__file__).resolve().is_relative_to(Path.cwd().resolve())
    assert set(report['inputs']) == {'inputs', 'config', 'receipts', 'tolerance', 'journal', 'latency_evidence'}
    with pytest.raises(FileExistsError):
        t1_cli.main(['accuracy', *args])


def test_latency_file_hash_and_empirical_p95_refuse_mismatch(tmp_path):
    args, _ = inputs(tmp_path)
    path = tmp_path / 'latency-evidence.json'
    evidence = json.loads(path.read_bytes())
    evidence['samples'][0]['acknowledged_at'] = at(3)
    path.write_bytes(canonical(evidence))
    with pytest.raises(SystemExit) as error:
        t1_cli.main(['simulate', *args])
    assert error.value.code == 2


def test_cli_bounds_input_size_before_reading(tmp_path):
    args, _ = inputs(tmp_path)
    with (tmp_path / 'inputs.json').open('ab') as handle:
        handle.truncate(17 * 1024 * 1024)
    with pytest.raises(SystemExit) as error:
        t1_cli.main(['simulate', *args])
    assert error.value.code == 2


@pytest.mark.spawns
def test_native_f0_intake_cli_accepts_empty_measurement_and_receipts_with_gap_flags(tmp_path):
    from weather.backtesting.t1_accuracy import F0_PIN

    args, output = inputs(tmp_path)
    (tmp_path / 'inputs.json').write_bytes(canonical({'input_kind': 'f0_lfc_recording', 'recorder_pin': F0_PIN}))
    (tmp_path / 'receipts.json').write_bytes(canonical({}))
    latency = {'kind': 'observation_to_order_ack', 'samples': [], 'sample_count': 0, 'synthetic': True}
    raw = canonical(latency)
    (tmp_path / 'latency-evidence.json').write_bytes(raw)
    (tmp_path / 'config.json').write_bytes(canonical(config(latency_source_sha256=hashlib.sha256(raw).hexdigest()).projection()))
    assert t1_cli.main(['accuracy', *args]) == 2
    report = json.loads(output.read_bytes())
    assert report['result']['status'] == 'NOT_QUALIFIED'
    assert report['result']['cash'] is None
    assert report['result']['gap_flags']['reward_payment']['status'] == 'NOT QUALIFIED'
    assert report['accuracy_certificate']['status'] == 'NOT QUALIFIED'


@pytest.mark.spawns
def test_canonical_module_process_binds_shared_interpreter_to_worktree(tmp_path):
    from weather.paths import REPO_ROOT

    args, output = inputs(tmp_path)
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(REPO_ROOT), str(REPO_ROOT / 'src')))}
    child = subprocess.run([sys.executable, '-m', 'weather.backtesting.t1_cli', 'accuracy', *args],
                           cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert child.returncode == 2, child.stderr
    report = json.loads(output.read_bytes())
    assert report['result']['status'] == 'CASH_PENDING'
    assert report['code']['source_sha256']['maker_core.quoting.book'] == hashlib.sha256(
        (REPO_ROOT / 'src/maker_core/quoting/book.py').read_bytes()).hexdigest()
