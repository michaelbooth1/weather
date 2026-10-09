"""Retained child facts produced by the real controller over fake transports."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import pytest

from tests.market.stage2_fakes import Clock, Venue, adapters_and_gates, CONDITION, TOKENS, MAKER
from tests.operations.test_international_live_session_runner import session_fixture, fake_sealer, write, sha
from tests.operations.test_international_live_wrapper_sealer import launcher_lineage_proof
from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as PROFILE
from weather.market.mm_live_attendance import session_confirmation_literal
from weather.market.mm_official_adapter import normalize_official_user_event
from weather.market.mm_stage2_hold import CONFIRMATION, SCHEMA_VERSION, digest, run_hold_session
from weather.market.mm_user_stream import SCHEMA_VERSION as STREAM_SCHEMA
from weather.market.mm_stage2_user_stream import verify_stage2_user_stream_journal
from weather.operations import international_live_session_runner as runner
from weather.operations import international_live_wrapper_sealer as sealer


def child_fixture(tmp_path):
    clock, venue = Clock(), None
    venue = Venue(clock)
    (tmp_path / 'base').mkdir()
    attempt, manifest, _ = session_fixture(tmp_path / 'base', 'stage0', now=clock.now(),
        execution_host_profile='portable_execution_v1')
    base = json.loads(manifest.read_bytes())
    scope = {**base['scope'], 'condition_id': CONDITION, 'token_id': TOKENS[0],
        'token_ids': list(TOKENS), 'requested_budget_pusd': 20, 'max_session_seconds': 7200,
        'run_not_before_local': clock.now().isoformat(), 'run_not_after_local': (clock.now() + timedelta(seconds=125)).isoformat(),
        'stage2': {'profile_id': PROFILE.profile_id, 'profile_sha256': PROFILE.sha256,
                   'selection_sha256': 'c' * 64, 'token_ids': list(TOKENS)}}
    del scope['token_ids']
    spec = {'stage': 'stage2_hold', 'scope': {k: v for k, v in scope.items() if k != 'max_session_seconds'},
        'production': base['production'], 'inputs': base['inputs'], 'reviewed_status_flags': [],
        'source_sha256': {sealer.SDK_OVERLAY_MANIFEST_PATH: 'd' * 64}}
    spec_path = write(attempt / 'inputs/stage2_hold-seal-spec.json', spec)
    binding = runner.resolve_production_python_runtime_binding(base['production']['root'],
        interpreter_redirector=base['production']['python'])
    seal_result = fake_sealer(attempt, 'stage2_hold')(spec_path)
    outputs = {k: attempt / v for k, v in sealer.OUTPUT_LAYOUTS['stage2_hold'].items()}
    runtime = sealer._runtime_scope({**spec, 'spec_path': spec_path, 'spec_raw': spec_path.read_bytes(), 'outputs': outputs})
    # Render the actual no-argument template; the executable itself is never
    # launched and the placeholder interpreter cannot launch a real session.
    rendered = sealer._render_python_wrapper((sealer.REPO_ROOT / sealer.PYTHON_TEMPLATE_PATHS['stage2_hold']).read_text(),
        production_root=Path(base['production']['root']), production_python=Path(base['production']['python']),
        production_python_sha256=sha(Path(base['production']['python'])),
        production_pyvenv_config=Path(binding['pyvenv_config']), production_pyvenv_config_sha256=binding['pyvenv_config_sha256'],
        production_runtime_python=Path(binding['runtime_process_image']), production_runtime_python_sha256=binding['runtime_process_image_sha256'],
        scope=runtime, source_sha256=spec['source_sha256'], stage='stage2_hold')
    Path(seal_result['wrapper']['path']).write_text(rendered, encoding='utf-8')
    seal_result['wrapper']['sha256'] = sha(Path(seal_result['wrapper']['path']))
    seal_path = Path(seal_result['seal_receipt']['path'])
    seal_payload = json.loads(seal_path.read_bytes())
    seal_payload['scope']['cancellation_mode'] = 'cancel_all'
    # The real receipt owns redirector/runtime bindings, not the manifest's
    # root/python aliases. Keep the fixture at that actual serialization shape.
    seal_payload['production'].pop('root')
    seal_payload['production'].pop('python')
    seal_payload['wrapper'] = seal_result['wrapper']
    write(seal_path, seal_payload)
    seal_result['seal_receipt']['sha256'] = sha(seal_path)
    adapters, gates = adapters_and_gates(tmp_path / 'inert-numeric-authority', clock, venue)
    prediction = run_hold_session(adapters, gates, scope={**scope['stage2'], 'condition_id': CONDITION,
        'maker_address': MAKER, 'end_at_utc': scope['run_not_after_local']},
        initial_public=venue.snapshot(), public_reader=venue.snapshot, geography_reader=venue.geography,
        journal_path=outputs['lifecycle_journal'], prediction_path=outputs['result'], confirmation=CONFIRMATION,
        operator_stop=lambda: False, scoring_reader=lambda ids: dict.fromkeys(ids, True),
        utc_clock=clock.now, monotonic_clock=clock.monotonic, sleeper=clock.sleep, mode='live')
    assert prediction['cleanup_ok'] and not prediction['fill_seen']
    stream_rows = [{'event_type': 'stream_starting', 'maker_address': MAKER, 'condition_id': CONDITION,
        'token_ids': list(TOKENS), 'account_wide_subscription': True}, {'event_type': 'subscription_sent'}]
    orders = {}
    for row in venue.orders.values():
        orders[row['id']] = row['asset_id']
        event = normalize_official_user_event({**row, 'event_type': 'order', 'type': 'CANCELLATION'},
            maker_address=MAKER, condition_id=CONDITION, token_id=row['asset_id'])[0]
        stream_rows.append({'event_type': 'user_event', 'payload': event})
    stream_rows.append({'event_type': 'stream_stopped'})
    outputs['user_stream_journal'].write_text(''.join(json.dumps({'schema_version': STREAM_SCHEMA, **r}) + '\n' for r in stream_rows), encoding='utf-8')
    stream_evidence = verify_stage2_user_stream_journal(outputs['user_stream_journal'], maker=MAKER,
        condition=CONDITION, tokens=TOKENS, orders=orders)
    for role in ('doctor_receipt', 'doctor_no_receipt'):
        write(outputs[role], {'status': 'PASS'})
    write(outputs['geography_precredential_receipt'], venue.geography())
    display = {k: runtime[k] for k in ('stage2', 'profile_values', 'condition_id', 'requested_budget_pusd',
        'run_not_before_local', 'run_not_after_local', 'cleanup_reserve_seconds')}
    display_sha = hashlib.sha256(json.dumps(display, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    confirmation = {'authorization_method': 'typed_session_confirmation', 'scope_sha256': display_sha,
        'literal_sha256': hashlib.sha256(session_confirmation_literal(CONFIRMATION, display_sha).encode()).hexdigest(),
        'physical_location_eligible': True, 'no_circumvention': True}
    write(outputs['command_receipt'], {'status': 'PASS', 'cleanup_ok': True, 'prediction_sha256': digest(prediction),
        'session_confirmation': confirmation, 'context_cleanup': {'ok': True, 'user_stream_journal_sha256': sha(outputs['user_stream_journal'])},
        'final_stream_evidence': stream_evidence})
    artifacts = {k: {'path': str(outputs[k]), 'sha256': sha(outputs[k])} for k in ('doctor_receipt',
        'doctor_no_receipt', 'geography_precredential_receipt', 'result', 'command_receipt', 'user_stream_journal', 'lifecycle_journal')}
    execution = {'schema_version': SCHEMA_VERSION, 'kind': 'session', 'stage': 'stage2_hold', 'status': 'PASS',
        'phase': 'complete', 'exception_type': None, 'scope': runtime, 'artifacts': artifacts,
        'wrapper': seal_result['wrapper'], 'session_confirmation': confirmation,
        'host_attestations': [{'checked_at_local': clock.now().isoformat(), 'status_json_sha256': '9' * 64,
            'status_flag_sha256': [], 'execution_host_profile': scope['execution_host_profile'],
            'execution_host_id': scope['execution_host_id'], 'lease_process_lineage': launcher_lineage_proof()} for _ in range(3)]}
    write(outputs['wrapper_execution_receipt'], execution)
    args = {'expected_scope': scope, 'expected_production': base['production'], 'expected_interpreter_binding': binding,
        'expected_lineage': {'seal_spec': {'path': str(spec_path), 'sha256': sha(spec_path)}},
        'expected_candidate_sha256': 'c' * 64, 'expected_candidate': {}, 'exit_code': 0}
    return attempt, seal_result, args, outputs, execution


def test_stage2_parent_consumes_rendered_template_and_real_fake_transport_controller(tmp_path):
    attempt, seal_result, args, _outputs, _execution = child_fixture(tmp_path)
    result = runner._stage2_child_execution_facts('stage2_hold', attempt, seal_result, **args)
    assert result['validation'] == 'PASS', result


@pytest.mark.parametrize('fault', ['production', 'confirmation', 'profile', 'window', 'stream', 'prediction', 'interpreter'])
def test_stage2_parent_rejects_rehashed_or_unbound_child_evidence(tmp_path, fault):
    attempt, seal_result, args, outputs, execution = child_fixture(tmp_path)
    if fault == 'production': execution['scope']['expected_production_tip'] = 'f' * 40
    if fault == 'confirmation': execution['session_confirmation']['physical_location_eligible'] = False
    if fault == 'profile': execution['scope']['profile_values']['per_band_pusd'] = 21
    if fault == 'window': execution['scope']['run_not_after_local'] = '2026-09-22T00:00:00Z'
    if fault == 'stream':
        rows = outputs['user_stream_journal'].read_text().splitlines()
        outputs['user_stream_journal'].write_text('\n'.join(rows[:-2] + rows[-1:]) + '\n')
        execution['artifacts']['user_stream_journal']['sha256'] = sha(outputs['user_stream_journal'])
    if fault == 'prediction':
        payload = json.loads(outputs['result'].read_bytes())
        payload['P_many'] += 1
        write(outputs['result'], payload)
        execution['artifacts']['result']['sha256'] = sha(outputs['result'])
    if fault == 'interpreter': args['expected_interpreter_binding']['runtime_process_image_sha256'] = 'f' * 64
    write(outputs['wrapper_execution_receipt'], execution)
    result = runner._stage2_child_execution_facts('stage2_hold', attempt, seal_result, **args)
    assert result['validation'] == 'FAIL'
