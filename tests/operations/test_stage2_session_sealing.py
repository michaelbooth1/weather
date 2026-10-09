"""Stage 2 manifest and grants use actual validators over inert public fixtures."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil

import pytest

from tests.operations.test_international_live_session_launcher_sealer import manifest_builder_fixture, build_manifest, sha
from tests.market.test_mm_stage2_selection import universe
from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as PROFILE, GRANT_PREFIX, GRANT_KEY, EnvelopeNotAuthorized
from weather.market.mm_stage2_hold import canonical_bytes, digest
from weather.market.mm_stage2_selection import select_table
from weather.operations import international_live_session_launcher_sealer as builder
from weather.operations import international_live_wrapper_sealer as sealer

NOW = datetime.fromisoformat('2026-08-23T12:00:00-04:00')


def stage2_builder_fixture(tmp_path):
    prepared = manifest_builder_fixture(tmp_path)
    root = prepared['production']
    for relative in set(sealer.LIVE_SOURCE_PATHS['stage2_hold']) | {sealer.PYTHON_TEMPLATE_PATHS['stage2_hold']}:
        destination = root / relative
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text('inert source fixture\n', encoding='utf-8')
    shutil.copyfile(sealer.REPO_ROOT / sealer.PYTHON_TEMPLATE_PATHS['stage2_hold'], root / sealer.PYTHON_TEMPLATE_PATHS['stage2_hold'])
    # An expired historical test date and a deliberately incomplete assignment
    # cannot authorize the actual installation. No real grant is written.
    grant = {'profile_id': PROFILE.profile_id, 'profile_sha256': PROFILE.sha256,
             'authorized_on': NOW.date().isoformat(), 'expires_at_utc': '2026-08-23T23:59:00Z'}
    (root / 'docs/operations/STATE_OF_PLAY.md').write_text('## Current authority\n' + GRANT_PREFIX + json.dumps(grant) + '\n', encoding='utf-8')
    (root / sealer.EXECUTION_HOST_ASSIGNMENT_PATH).write_text(json.dumps({GRANT_KEY: grant}), encoding='utf-8')
    bands = universe()
    for row in bands:
        row['target_date'] = (NOW.date() + timedelta(days=1)).isoformat()
        row['snapshot']['observed_at_utc'] = NOW.astimezone(timezone.utc).isoformat()
    table = select_table(bands, now=NOW)
    prepared['discovery'].write_bytes(canonical_bytes(table))
    predecessor = prepared['discovery'].with_name('predecessors.json')
    predecessor.write_text('{}', encoding='utf-8')
    args = dict(stage='stage2_hold', now=NOW, execution_host_profile='portable_execution_v1', event_metadata_source_path=None,
        predecessors_source_path=predecessor, lease_workload=builder._canonical_lease_workload(prepared['attempt'], 'stage2_hold'))
    return prepared, args, table


def test_stage2_builder_binds_both_tokens_profile_selection_and_7200_seconds(tmp_path):
    prepared, args, table = stage2_builder_fixture(tmp_path)
    receipt = build_manifest(prepared, **args)
    manifest_path = Path(receipt['session_manifest']['path'])
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest['scope']['requested_budget_pusd'] == 20
    assert manifest['scope']['max_session_seconds'] == 7200
    assert manifest['scope']['stage2'] == {'profile_id': PROFILE.profile_id, 'profile_sha256': PROFILE.sha256,
        'selection_sha256': digest(table), 'token_ids': ['111', '222']}
    assert set(manifest['inputs']) == {'identity', 'credential_import_receipt', 'credential_reference_manifest', 'selection', 'predecessors'}
    assert receipt['discovery']['unconstrained_discovery_only'] is False
    launcher = builder.prepare_fixed_session_launcher(manifest_path, sha(manifest_path), sha(Path(receipt['build_receipt_path'])),
        repo_root=prepared['production'], template_path=prepared['outer_template'], powershell_parser=lambda _s: None,
        attempt_root_validator=lambda _p: {'status': 'PASS'}, portable_assignment_validator=lambda *_a, **_k: {}, now=NOW)
    assert launcher['status'] == 'PASS' and launcher['no_argument_surface']
    assert launcher['live_mutation_attempted'] is False


@pytest.mark.parametrize('fault', ['absent', 'mismatch', 'expired', 'profile_hash', 'selection_hash', 'extra_token', 'midnight', 'duration'])
def test_stage2_scope_fails_closed_for_grant_and_treatment_changes(tmp_path, fault):
    prepared, args, table = stage2_builder_fixture(tmp_path)
    root = prepared['production']
    receipt = build_manifest(prepared, **args)
    scope = {**receipt['scope'], 'run_not_before_local': NOW.isoformat(),
             'run_not_after_local': (NOW + timedelta(seconds=7200)).isoformat()}
    assignment = root / sealer.EXECUTION_HOST_ASSIGNMENT_PATH
    payload = json.loads(assignment.read_bytes())
    if fault == 'absent': payload.pop(GRANT_KEY)
    if fault == 'mismatch': payload[GRANT_KEY]['authorized_on'] = '2026-08-22'
    if fault == 'expired': payload[GRANT_KEY]['expires_at_utc'] = '2026-08-23T00:00:00Z'
    if fault == 'profile_hash': scope['stage2']['profile_sha256'] = 'f' * 64
    if fault == 'selection_hash': scope['stage2']['selection_sha256'] = 'unknown'
    if fault == 'extra_token': scope['stage2']['token_ids'].append('333')
    if fault == 'midnight': scope['run_not_after_local'] = '2026-08-24T00:00:00Z'
    if fault == 'duration': scope['run_not_after_local'] = (NOW + timedelta(seconds=7201)).isoformat()
    assignment.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises((sealer.SealError, EnvelopeNotAuthorized)):
        sealer.require_stage2_scope(scope, root=root, now=NOW)


def test_unsealed_stage2_entrypoint_cannot_reach_credential_resolver(monkeypatch):
    from weather.market import mm_stage2_entrypoint as entry
    from weather.market import mm_live_pilot_cli as cli
    calls = []
    def forbidden():
        calls.append('credential resolver')
        raise AssertionError('credential I/O is forbidden in this fixture')
    monkeypatch.setattr(cli, 'load_global_credential_bundle', forbidden)
    with pytest.raises(KeyError):
        entry.run_sealed_hold({}, confirmation_receipt={}, pre_submit_attestor=lambda: None,
            geography_reader=lambda: None)
    assert calls == []


@pytest.mark.skipif(os.name != 'nt', reason='executes the Windows-only template imports; AST rendering is tested separately')
def test_unsealed_stage2_template_refuses_before_runtime_import(monkeypatch):
    source = (sealer.REPO_ROOT / sealer.PYTHON_TEMPLATE_PATHS['stage2_hold']).read_text()
    namespace = {'__name__': 'unsealed_fixture', '__file__': str(sealer.REPO_ROOT / 'unsealed-stage2.py')}
    exec(compile(source, namespace['__file__'], 'exec'), namespace)
    monkeypatch.setattr('sys.argv', ['unsealed-stage2.py'])
    with pytest.raises(RuntimeError, match='not sealed'):
        namespace['main']()
