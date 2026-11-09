"""Immutable release/environment identity, separate from editable campaign policy."""
from datetime import datetime, timezone
from pathlib import Path
import importlib.metadata
import json
import subprocess
import sys
import hashlib

from weather.execution_host import (current_execution_host_id, current_execution_principal_id,
                                      require_current_portable_execution_assignment)
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.operations.live_path_security import (assert_no_ambient_proxy_configuration,
    resolve_production_python_runtime_binding, validate_nonreparse_directory,
    validate_regular_nonreparse_file, validate_production_python_runtime_binding)
from weather.paths import REPO_ROOT


RELEASE_SCHEMA = 'lfc_campaign_release_v0.1'
TASK_NAME = 'WeatherLFCCampaign'
BOUND_PACKAGES = ('polymarket-client', 'websocket-client', 'httpx', 'httpcore', 'eth-account',
                  'eth-keys', 'eth-abi', 'eth-utils', 'pydantic', 'pydantic-core')


def package_binding(name):
    distribution = importlib.metadata.distribution(name)
    paths = sorted(p for p in distribution.files or () if str(p).endswith(('.py', '.pyd', '.dll', '/METADATA', '/RECORD')))
    if not paths:
        raise RuntimeError('campaign_package_files_missing')
    sha = hashlib.sha256()
    for relative in paths:
        path = validate_regular_nonreparse_file(Path(distribution.locate_file(relative)).absolute())
        sha.update(str(relative).replace('\\', '/').encode() + b'\0' + file_sha(path).encode() + b'\n')
    return {'version': distribution.version, 'source_sha256': sha.hexdigest(), 'files': len(paths)}


def git_identity(root):
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True,
                              timeout=15).stdout.strip()
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise RuntimeError('campaign_requires_clean_pin')
    return git('rev-parse', 'HEAD')


def validate_policy_path(path):
    path = Path(path)
    if not path.is_absolute() or path.suffix.lower() != '.json':
        raise RuntimeError('campaign_path')
    return validate_regular_nonreparse_file(path)


def seal_release(*, campaign_path, pregate_path, qualified_head, python_path, output):
    """Called by the OWNER registrar, after it qualifies the full pregate receipt.

    This is not an agent setup command. No credentials or venue are read. The
    account is bound to the existing ledger's public genesis, never a new ledger.
    """
    from weather.market.lfc_campaign_guard import account_lease
    from weather.market.lfc_campaign_policy import load_policy, EARLIEST, parameter_support
    from weather.market.lfc_campaign_state import AccountState, DEFAULT_STATE_ROOT
    from weather.market.lfc_ledger import Ledger, ledger_path
    from weather.market.lfc_pilot import pilot_root
    root = validate_nonreparse_directory(REPO_ROOT)
    policy_path = validate_policy_path(campaign_path)
    policy = load_policy(policy_path)
    from weather.market.lfc_f2_policy import require_live_loss_basis
    basis = require_live_loss_basis(policy)
    assignment = require_current_portable_execution_assignment()
    head = git_identity(root)
    if head != qualified_head:
        raise RuntimeError('qualified_head_mismatch')
    now = datetime.now(timezone.utc)
    if now < EARLIEST:
        raise RuntimeError('enrollment_waits_until_after_frozen_F0')
    ledger = Ledger.open(ledger_path(pilot_root()), clock=lambda: datetime.now(timezone.utc))
    state = AccountState(DEFAULT_STATE_ROOT, ledger)
    windowless_python = validate_regular_nonreparse_file(Path(python_path).resolve().with_name('pythonw.exe'))
    windowless = {'python': str(windowless_python), 'sha256': file_sha(windowless_python),
                  'launcher_sha256': file_sha(root / 'scripts/ops/lfc_campaign_windowless.py')}
    state.policy_binding = policy.labels()
    with account_lease(state.maker):
        if ledger.enrollment is None:
            state.enroll(now)
        else:
            state.verify()
        row = {'schema_version': RELEASE_SCHEMA, 'root': str(root.resolve()), 'head': head,
               'sleeve_loss_basis': basis,
               **policy.labels(),
               'parameter_support': parameter_support(),
               'python': str(Path(python_path).resolve()), 'campaign_path': str(policy_path.resolve()),
               'windowless': windowless,
               'python_root': str(Path(python_path).resolve().parent.parent.parent),
               'host_id': current_execution_host_id(), 'principal_id': current_execution_principal_id(),
               'assignment_sha256': file_sha(root / 'config/international_live_execution_host.json'),
               'pregate_sha256': file_sha(validate_regular_nonreparse_file(pregate_path)),
               'pregate_path': str(Path(pregate_path).resolve()), 'maker_address': state.maker,
               'ledger_genesis_sha256': ledger.row_sha256(0), 'state_id': state.verify()['state_id'],
               'runtime_binding': resolve_production_python_runtime_binding(
                   Path(python_path).resolve().parent.parent.parent, interpreter_redirector=python_path),
               'packages': {name: package_binding(name) for name in BOUND_PACKAGES},
               'task_name': TASK_NAME, 'created_at_utc': now.isoformat()}
        write_new(output, row)
    return row


def load_release(path, expected_sha):
    path = validate_regular_nonreparse_file(path)
    if file_sha(path) != expected_sha:
        raise RuntimeError('campaign_release_hash')
    row = strict_json(read_bytes(path, 65536))
    if not isinstance(row, dict) or row.get('schema_version') != RELEASE_SCHEMA or row.get('task_name') != TASK_NAME:
        raise RuntimeError('campaign_release_schema')
    return row


def validate_parameter_support(row):
    from weather.market.lfc_campaign_policy import parameter_support
    if row.get('parameter_support') != parameter_support():
        raise RuntimeError('campaign_parameter_support_changed')


def validate_release(row):
    validate_parameter_support(row)
    assert_no_ambient_proxy_configuration()
    require_current_portable_execution_assignment()
    if (current_execution_host_id() != row['host_id'] or current_execution_principal_id() != row['principal_id'] or
            REPO_ROOT.resolve() != Path(row['root']).resolve() or git_identity(REPO_ROOT) != row['head'] or
            file_sha(REPO_ROOT / 'config/international_live_execution_host.json') != row['assignment_sha256']):
        raise RuntimeError('campaign_release_identity')
    validate_nonreparse_directory(REPO_ROOT)
    windowless = row.get('windowless', {})
    expected = Path(row['python']).with_name('pythonw.exe')
    if (Path(windowless.get('python', '')).resolve() != expected.resolve() or
            file_sha(validate_regular_nonreparse_file(expected)) != windowless.get('sha256') or
            file_sha(REPO_ROOT / 'scripts/ops/lfc_campaign_windowless.py') != windowless.get('launcher_sha256')):
        raise RuntimeError('campaign_windowless_binding')
    # Pending money postchecks use their immutable claim snapshot, even if the
    # editable policy is absent/broken. Validate that file only when it is read.
    if not Path(row['campaign_path']).is_absolute() or Path(row['campaign_path']).suffix.lower() != '.json':
        raise RuntimeError('campaign_path')
    validate_production_python_runtime_binding(row['runtime_binding'], production_root=row['python_root'])
    if Path(sys.executable).resolve() != Path(row['python']).resolve():
        raise RuntimeError('campaign_interpreter_changed')
    if set(row['packages']) != set(BOUND_PACKAGES):
        raise RuntimeError('campaign_dependency_scope')
    for name, binding in row['packages'].items():
        if package_binding(name) != binding:
            raise RuntimeError('campaign_dependency_changed')


def task_enabled(release, release_path, release_sha):
    """Fresh actual Scheduler read-back, not a digest pretending the task is enabled."""
    script = REPO_ROOT / 'scripts/ops/lfc_campaign_task_contract.ps1'
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
                             '-Action', 'Read', '-ReleasePath', str(release_path), '-ReleaseSha256', release_sha],
                            capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise RuntimeError('campaign_task_readback_failed')
    row = strict_json(result.stdout)
    if (not isinstance(row, dict) or row.get('schema_version') != 'lfc_campaign_task_read_v0.1' or
            row.get('definition_valid') is not True or type(row.get('enabled')) is not bool or
            row.get('release_sha256') != release_sha):
        raise RuntimeError('campaign_task_readback_invalid')
    return row['enabled']
