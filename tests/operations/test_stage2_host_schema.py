"""Identical optional-grant shape in Python and PowerShell; never an actual grant."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from weather.execution_host import load_execution_host_assignment, ExecutionHostAssignmentError


@pytest.mark.parametrize('fault', [None, 'unassigned', 'extra', 'profile', 'hash', 'day', 'expiry', 'naive', 'null'])
def test_assignment_readers_agree_on_optional_stage2_shape(tmp_path, fault):
    # Synthetic installation and principal; no State of Play grant exists.
    grant = {'profile_id': 'stage2_hold_v1', 'profile_sha256': 'd' * 64,
             'authorized_on': '2026-09-21', 'expires_at_utc': '2026-09-21T22:00:00Z'}
    payload = {'schema_version': 'international_live_execution_host_assignment_v0.1',
        'assignment_status': 'ASSIGNED', 'dedicated_capture_execution_host_id': 'a' * 64,
        'active_portable_execution_host_id': 'b' * 64, 'active_portable_execution_principal_id': 'c' * 64,
        'reassignment_requires_new_production_tip': True, 'stage2_hold_owner_authorization': grant}
    if fault == 'unassigned':
        payload.update(assignment_status='UNASSIGNED', active_portable_execution_host_id=None,
                       active_portable_execution_principal_id=None)
    elif fault == 'extra': grant['extra'] = True
    elif fault == 'profile': grant['profile_id'] = 'stage1_v1'
    elif fault == 'hash': grant['profile_sha256'] = 17
    elif fault == 'day': grant['authorized_on'] = '2026-02-30'
    elif fault == 'expiry': grant['expires_at_utc'] = False
    elif fault == 'naive': grant['expires_at_utc'] = '2026-09-21T22:00:00'
    elif fault == 'null': payload['stage2_hold_owner_authorization'] = None
    path = tmp_path / 'config/international_live_execution_host.json'
    path.parent.mkdir()
    path.write_text(json.dumps(payload), encoding='utf-8')
    if fault is None:
        assert load_execution_host_assignment(path) == payload
    else:
        with pytest.raises(ExecutionHostAssignmentError):
            load_execution_host_assignment(path)
    if os.name != 'nt':
        pytest.skip('Python schema assertions ran; the native PowerShell comparison requires Windows')
    script = Path(__file__).resolve().parents[2] / 'scripts/ops/workload_admission.ps1'
    command = ". '" + str(script).replace("'", "''") + "'; try { Get-WeatherExecutionHostAssignment -RepoRoot '" + str(tmp_path).replace("'", "''") + "' | Out-Null; exit 0 } catch { exit 2 }"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == (0 if fault is None else 2), result.stderr
