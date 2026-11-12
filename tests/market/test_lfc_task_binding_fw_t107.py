"""Guards: real contract binding refusals must not become cached enabled reads."""
import hashlib
import json
import subprocess

import pytest

from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_campaign_runtime import runtime_at
from weather.market import lfc_campaign_release as release
from weather.market.lfc_campaign_guard import account_lease
from weather.paths import REPO_ROOT


@pytest.mark.spawns
@pytest.mark.parametrize('fault', ['release_hash', 'task_definition'])
def test_real_binding_fault_does_not_enter_transient_fallback(tmp_path, monkeypatch, fault):
    contract = REPO_ROOT / 'scripts/ops/lfc_campaign_task_contract.ps1'
    path = tmp_path / 'synthetic-release.json'
    row = {'schema_version': 'lfc_campaign_release_v0.1', 'task_name': 'WeatherLFCCampaign',
           'root': str(tmp_path), 'windowless': {'python': str(tmp_path / 'pythonw.exe')}}
    path.write_text(json.dumps(row), encoding='utf-8')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    native_run = subprocess.run
    observations = []
    q = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = f'. {q(contract)}; ' + r'''
function Export-ScheduledTask {
    param($TaskName,$TaskPath,$ErrorAction)
    $r=Read-LfcCampaignRelease -Path $global:A088FixturePath -Sha256 $global:A088FixtureSha
    $xml=New-LfcCampaignTaskXml -Release $r -ReleasePath $global:A088FixturePath -ReleaseSha256 $global:A088FixtureSha -OwnerSid ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    return $xml.Replace('<ExecutionTimeLimit>PT11H</ExecutionTimeLimit>','<ExecutionTimeLimit>PT12H</ExecutionTimeLimit>')
}
''' + f'$global:A088FixturePath={q(path)};$global:A088FixtureSha={q(sha)}; & {q(contract)} -Action Read -ReleasePath {q(path)} -ReleaseSha256 {q(sha)}'
    def native_contract(command, **kwargs):
        assert command[-1] == sha and kwargs['timeout'] == 5
        result = native_run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], **kwargs)
        expected = 'release hash' if fault == 'release_hash' else 'task property mismatch ExecutionTimeLimit'
        assert result.returncode != 0 and expected in result.stderr
        observations.append({'native_exit': result.returncode, 'binding_fault': fault})
        return result
    with account_lease(MAKER, backend=Mutexes()):
        runtime = runtime_at(tmp_path / 'runtime')
        runtime._read_task_enabled = lambda: True
        assert runtime.task_enabled()
        runtime.state.ledger.record('session_start', session_id='active-fixture')
        runtime.clock.sleep(60)
        if fault == 'release_hash':
            path.write_text(json.dumps({**row, 'changed': True}), encoding='utf-8')
        monkeypatch.setattr(release.subprocess, 'run', native_contract)
        runtime._read_task_enabled = lambda: release.task_enabled(row, path, sha)
        try:
            returned = runtime.task_enabled()
        except BaseException as exc:
            (tmp_path / 'observation.json').write_text(json.dumps({
                'native': observations, 'raised': type(exc).__name__, 'reason': str(exc)}))
            assert type(exc) is RuntimeError
        else:
            (tmp_path / 'observation.json').write_text(json.dumps({
                'native': observations, 'returned': returned, 'failures': runtime._task_failures}))
            pytest.fail('Real native binding fault was tolerated as enabled instead of fatal')
