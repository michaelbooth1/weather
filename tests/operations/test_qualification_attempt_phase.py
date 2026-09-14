"""Native shared task contracts keep host and historical suite evidence distinct.

These tests never register a task. They exercise the actual immutable readers,
task token construction and per-attempt schema decisions in PowerShell 5.1.
"""

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "scripts/ops/integration_attempt_contract.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows PowerShell task contract")


def run(tmp_path, body):
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / "phase-fixture.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n. " + literal(CONTRACT) + "\n"
                      + "$root = " + literal(ROOT) + "\n$fixture = " + literal(tmp_path.resolve()) + "\n" + SETUP + body,
                      encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


SETUP = r'''
function New-FixtureContract([string]$version) {
    $role = if ($version -eq 'v2') { 'host' } else { 'suite' }
    $title = if ($version -eq 'v2') { 'Host' } else { 'Suite' }
    $directory = Join-Path $fixture $version
    [void][IO.Directory]::CreateDirectory($directory)
    $schedule = [ordered]@{ merge_task_name = "WeatherIntegrationMerge_$version"; merge_at_local = '2026-09-15T01:10:00' }
    $schedule[$role + '_task_name'] = "WeatherIntegration${title}_$version"
    $schedule[$role + '_at_local'] = '2026-09-15T00:35:00'
    $orchestration = [ordered]@{
        attempt_merge = [pscustomobject]@{ path = (Join-Path $root 'scripts/ops/integration_attempt_merge.ps1'); sha256 = ('a' * 64) }
    }
    $orchestration['attempt_' + $role] = [pscustomobject]@{
        path = (Join-Path $root "scripts/ops/integration_attempt_$role.ps1"); sha256 = ('b' * 64)
    }
    $manifest = [ordered]@{
        schema = "weather_integration_attempt_manifest_$version"; attempt_id = $version
        repo_root = $root; attempt_root = $directory
        schedule = [pscustomobject]$schedule; orchestration = [pscustomobject]$orchestration
        evidence = [pscustomobject]@{ registration_intent = (Join-Path $directory 'registration-intent.json') }
    }
    if ($version -eq 'v2') { $manifest['qualification_mode'] = 'split_v2'; $manifest['control'] = [pscustomobject]@{ root = $root } }
    return [pscustomobject]@{
        Manifest = [pscustomobject]$manifest; ManifestPath = (Join-Path $directory 'manifest.json')
        ManifestSha256 = ('c' * 64); AttemptRoot = $directory
    }
}
function New-FixtureIntent($contract) {
    $role = (Get-WeatherIntegrationPrerequisite -AttemptContract $contract).Role
    $intent = [ordered]@{
        schema = (Get-WeatherIntegrationRecordSchema -AttemptContract $contract -Kind registration_intent)
        status = 'PREPARED'; binding_contract = $script:WeatherIntegrationAttemptTaskBindingContract
        attempt_id = $contract.Manifest.attempt_id; intent_path = $contract.Manifest.evidence.registration_intent
        manifest_path = $contract.ManifestPath; manifest_sha256 = $contract.ManifestSha256
        prepared_at_local = (Get-Date).ToString('o')
        principal = [pscustomobject]@{ user_id = 'fixture-user'; logon_type = 'S4U'; run_level = 'Limited'
            id = 'Author'; display_name = ''; group_id = ''; process_token_sid_type = 'Default'; required_privileges = @() }
        merge = (Get-WeatherIntegrationExpectedTaskBinding -AttemptContract $contract -Role merge -UserId 'fixture-user')
        safety = [pscustomobject]@{ authority = 'NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY'
            credential_value_access_authorized = $false; live_exchange_mutation_authorized = $false }
    }
    $intent[$role] = Get-WeatherIntegrationExpectedTaskBinding -AttemptContract $contract -Role $role -UserId 'fixture-user'
    return $intent
}
'''


def test_both_phases_round_trip_without_mutable_global_schema(tmp_path):
    run(tmp_path, r'''
foreach ($version in @('v2', 'v1')) {
    $contract = New-FixtureContract $version
    $intent = New-FixtureIntent $contract
    Write-WeatherIntegrationImmutableJson -Path $contract.Manifest.evidence.registration_intent -Payload $intent
    $result = Assert-WeatherIntegrationRegistrationIntent -AttemptContract $contract
    if ($result.Intent.schema -cne "weather_integration_attempt_registration_intent_$version") { throw 'schema contaminated by another attempt' }
    $role = (Get-WeatherIntegrationPrerequisite -AttemptContract $contract).Role
    $binding = $result.Intent.PSObject.Properties[$role].Value
    $limit = if ($version -eq 'v2') { 'PT34M' } else { 'PT8H' }
    if ($binding.settings.execution_time_limit -cne $limit -or $binding.settings.start_when_available) { throw 'wrong time contract' }
    if ($binding.arguments -notlike "*integration_attempt_$role.ps1*") { throw 'wrong canonical script' }
    if ($result.Intent.PSObject.Properties[ $(if ($role -eq 'host') { 'suite' } else { 'host' }) ]) { throw 'phase evidence mislabeled' }
}
''')


@pytest.mark.parametrize("mutation", ["wrong_role", "downgrade", "missing_host", "wrong_action", "long_limit", "catchup"])
def test_host_intent_rejects_wrong_role_schema_and_task_contract(tmp_path, mutation):
    changes = {
        "wrong_role": "$intent['suite'] = $intent['host']; $intent.Remove('host')",
        "downgrade": "$intent.schema = 'weather_integration_attempt_registration_intent_v1'",
        "missing_host": "$intent.Remove('host')",
        "wrong_action": "$intent.host.arguments += ' -Force'",
        "long_limit": "$intent.host.settings.execution_time_limit = 'PT8H'",
        "catchup": "$intent.host.settings.start_when_available = $true",
    }
    run(tmp_path, "$contract = New-FixtureContract 'v2'\n$intent = New-FixtureIntent $contract\n" + changes[mutation] + r'''
Write-WeatherIntegrationImmutableJson -Path $contract.Manifest.evidence.registration_intent -Payload $intent
$refused = $false
try { Assert-WeatherIntegrationRegistrationIntent -AttemptContract $contract | Out-Null } catch { $refused = $true }
if (-not $refused) { throw 'invalid host phase was accepted' }
''')


def test_host_role_cannot_be_interpreted_as_suite_and_unfinished_v2_cannot_arm(tmp_path):
    run(tmp_path, r'''
$contract = New-FixtureContract 'v2'
$refused = $false
try { Get-WeatherIntegrationExpectedTaskBinding -AttemptContract $contract -Role suite -UserId 'fixture-user' | Out-Null } catch { $refused = $true }
if (-not $refused) { throw 'host reinterpreted as full suite' }
# Until the full v2 manifest/authentication reader is connected, the public
# registrar's first gate must continue to reject this partial implementation.
Write-WeatherIntegrationImmutableJson -Path $contract.ManifestPath -Payload $contract.Manifest
$sha = Get-WeatherIntegrationFileSha256 -Path $contract.ManifestPath
$refused = $false
try { Assert-WeatherIntegrationAttemptManifest -ManifestPath $contract.ManifestPath -ExpectedSha256 $sha | Out-Null } catch { $refused = $true }
if (-not $refused) { throw 'incomplete v2 manifest reader authorized registration' }
''')
