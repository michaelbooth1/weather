"""Read-only, create-only T1 simulator/accuracy reports from explicit JSON inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from weather.backtesting.t1_accuracy import Tolerance, accuracy_gate
from weather.backtesting.t1_simulator import replay
from weather.backtesting.t1_types import ReplayConfig, canonical, number, utc


def source_binding():
    """Hash all T1 source bytes, and record Git identity with dirty state separately."""
    from weather.paths import REPO_ROOT

    result = {}
    source_dir = REPO_ROOT / 'src' / 'weather' / 'backtesting'
    if Path(__file__).resolve().parent != source_dir.resolve():
        raise ValueError('T1 CLI imported outside the bound worktree')
    for path in sorted(source_dir.glob('t1_*.py')):
        result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    from maker_core.quoting import book, policy

    for dependency in (book, policy):
        path = Path(dependency.__file__).resolve()
        if not path.is_relative_to(REPO_ROOT):
            raise ValueError('maker dependency imported outside the bound worktree')
        result[dependency.__name__] = hashlib.sha256(path.read_bytes()).hexdigest()
    commit = subprocess.run(['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'], check=True,
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', str(REPO_ROOT), 'status', '--porcelain'], check=True,
                           capture_output=True, text=True).stdout.strip()
    return {'git_commit': commit, 'worktree_clean': not bool(dirty), 'source_sha256': result}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('simulate', 'accuracy'))
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--receipts', type=Path)
    parser.add_argument('--tolerance', type=Path)
    parser.add_argument('--latency-evidence', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == 'accuracy' and not all((args.journal, args.receipts, args.tolerance)):
        parser.error('accuracy requires --journal, --receipts and --tolerance')
    files = {name: path for name, path in vars(args).items() if isinstance(path, Path) and name != 'output'}
    # This command accepts bounded session exports, never whole capture tapes.
    if sum(path.stat().st_size for path in files.values()) > 16 * 1024 * 1024:
        parser.error('input files exceed 16 MiB; export a bounded session')
    raw = {name: path.read_bytes() for name, path in files.items()}
    config = ReplayConfig(**json.loads(raw['config']))
    latency = json.loads(raw['latency_evidence'])
    durations = []
    for sample in latency['samples']:
        observed, decided, acknowledged = (utc(sample[k]) for k in ('observed_at', 'decided_at', 'acknowledged_at'))
        if not observed <= decided <= acknowledged:
            parser.error('latency sample clock regressed')
        durations.append(number((acknowledged - observed).total_seconds()))
    durations.sort()
    # Nearest-rank empirical p95, including the full observation-to-ACK path.
    p95 = durations[(95 * len(durations) + 99) // 100 - 1] if durations else None
    if (hashlib.sha256(raw['latency_evidence']).hexdigest() != config.latency_source_sha256
            or latency['kind'] != 'observation_to_order_ack'
            or p95 != number(config.measured_p95_seconds)
            or latency['sample_count'] != len(durations) or not durations):
        parser.error('latency measurement does not bind to config')
    payload = json.loads(raw['inputs'])
    if args.mode == 'simulate':
        result = replay(payload, config)
    else:
        result = accuracy_gate(payload, config, raw['journal'], json.loads(raw['receipts']),
                               Tolerance(**json.loads(raw['tolerance'])))
    from weather.schema_families import schema_version

    report = {'schema_version': schema_version('t1_simulator_report'),
              'result': result, 'code': source_binding(),
              'synthetic': latency['synthetic'] or result.get('synthetic', False),
              'inputs': {name: {'path': str(files[name].resolve()), 'sha256': hashlib.sha256(data).hexdigest()}
                         for name, data in raw.items()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as handle:
        handle.write(canonical(report))
    return 0 if args.mode == 'simulate' or result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
