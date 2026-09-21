"""Attended sealed Stage 2 wiring. Importing this module performs no I/O."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import signal
from types import SimpleNamespace

from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as PROFILE
from weather.market.mm_stage2_hold import CONFIRMATION, SCHEMA_VERSION, digest, run_hold_session, write_new
from weather.market.mm_stage2_rewards import RewardsReaders
from weather.market.mm_stage2_selection import PublicBooks, validate_selection
from weather.market.mm_stage2_hold import public_quote
from weather.market.mm_stage2_user_stream import Stage2UserStreamReader, verify_stage2_user_stream_journal


def keyless_doctors(validated, activation):
    from weather.market import mm_live_pilot_cli as cli
    scope = validated['scope']
    for token, role in zip(scope['stage2']['token_ids'], ('doctor_receipt', 'doctor_no_receipt')):
        result = cli.run_doctor(SimpleNamespace(
            command='doctor', identity=validated['inputs']['identity']['path'],
            target_date=scope['target_date'], condition_id=scope['condition_id'], token_id=token,
            budget=10, receipt_out=str(validated['outputs'][role]), sdk_overlay_activation=activation,
            confirmation=cli.DOCTOR_CONFIRMATION,
        ))
        if result.get('status') != 'PASS' or result.get('missing'):
            raise RuntimeError('Stage 2 keyless doctor did not pass for both tokens')


def _reserve_campaign(production_root, *, maker, scope):
    """Spend the attempt before signing; an unfinished attempt blocks successors.

    The caller holds the launcher host-global lease throughout. Its canonical
    per-wallet directory persists across private attempt roots and Git tips.
    No loss or unresolved fill may be silently discarded by starting a session.
    """
    from weather.operations.international_live_session_launcher_sealer import _default_attempt_directory_creator
    from weather.operations.live_path_security import validate_private_attempt_root, validate_regular_nonreparse_file
    from weather.paths import REPO_ROOT, data_path
    if Path(production_root).resolve() != REPO_ROOT.resolve():
        raise RuntimeError('campaign root differs from the loaded production package')
    root = data_path('operations', 'stage2_hold', hashlib.sha256(maker.encode('ascii')).hexdigest())
    if not root.exists():
        _default_attempt_directory_creator(root)
    if validate_private_attempt_root(root).get('status') != 'PASS':
        raise RuntimeError('Stage 2 campaign directory is not private')
    markers = sorted(root.glob('*.attempt.json'))
    days, today_count = set(), 0
    today = datetime.now(timezone.utc).date().isoformat()
    if len(markers) >= PROFILE.max_reward_days * PROFILE.max_sessions_per_utc_day:
        raise RuntimeError('Stage 2 campaign attempt ceiling exhausted')
    for marker in markers:
        validate_regular_nonreparse_file(marker)
        row = json.loads(marker.read_bytes())
        result_path = marker.with_name(marker.name.replace('.attempt.json', '.result.json'))
        validate_regular_nonreparse_file(result_path)
        prior = json.loads(result_path.read_bytes())
        if (row.get('profile_sha256') != PROFILE.sha256 or prior.get('attempt_sha256') != digest(row)
                or prior.get('cleanup_ok') is not True or prior.get('fill_seen') is not False):
            raise RuntimeError('prior Stage 2 attempt requires owner reconciliation')
        days.add(row['reward_day'])
        if row['reward_day'] == today:
            if row['condition_id'] != scope['condition_id']:
                raise RuntimeError('one band per UTC reward day is already fixed')
            today_count += 1
    if today_count >= PROFILE.max_sessions_per_utc_day or today not in days and len(days) >= PROFILE.max_reward_days:
        raise RuntimeError('Stage 2 daily/session ceiling exhausted')
    path = root / f'{today}-{today_count + 1}.attempt.json'
    row = {'schema_version': SCHEMA_VERSION, 'kind': 'session', 'reward_day': today,
           'condition_id': scope['condition_id'], 'profile_sha256': PROFILE.sha256,
           'scope_sha256': digest(scope), 'created_at_utc': datetime.now(timezone.utc).isoformat()}
    write_new(path, row)
    return path, row


def run_sealed_hold(scope, *, confirmation_receipt, pre_submit_attestor, geography_reader):
    from weather.market import mm_live_pilot_cli as cli
    from weather.market.mm_official_adapter import OfficialPolymarketGlobalAdapter
    from weather.market.mm_live_attendance import session_confirmation_literal
    from weather.operations.live_path_security import resolve_production_python_runtime_binding
    from weather.operations.international_live_wrapper_sealer import revalidate_stage2_runtime, validate_stage2_predecessors
    validated = revalidate_stage2_runtime(scope, doctor_complete=True)
    root = Path(validated['production']['root'])
    inputs = validated['inputs']
    display = {key: scope[key] for key in ('stage2', 'profile_values', 'condition_id', 'requested_budget_pusd',
                                           'run_not_before_local', 'run_not_after_local', 'cleanup_reserve_seconds')}
    display_sha = hashlib.sha256(json.dumps(display, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    literal_sha = hashlib.sha256(session_confirmation_literal(CONFIRMATION, display_sha).encode('ascii')).hexdigest()
    if (confirmation_receipt.get('authorization_method') != 'typed_session_confirmation'
            or confirmation_receipt.get('scope_sha256') != display_sha
            or confirmation_receipt.get('literal_sha256') != literal_sha
            or confirmation_receipt.get('physical_location_eligible') is not True
            or confirmation_receipt.get('no_circumvention') is not True):
        raise RuntimeError('Stage 2 typed attendance is absent')
    public = PublicBooks()
    table = json.loads(Path(inputs['selection']['path']).read_bytes())
    selected = validate_selection(table, expected_sha256=scope['stage2']['selection_sha256'],
                                  condition_id=scope['condition_id'], token_ids=scope['stage2']['token_ids'],
                                  now=datetime.now(timezone.utc))
    tokens = tuple(selected['token_ids'])
    initial = public.snapshot(scope['condition_id'], tokens)
    # Reprice only before either submit; the hold controller never requotes.
    for token in tokens:
        if initial['rules'][token] != selected['snapshot']['rules'][token]:
            raise RuntimeError('selected venue fee/tick/minimum/neg-risk changed')
    predecessor = validate_stage2_predecessors(inputs, scope=validated['scope'], production=validated['production'],
                                               interpreter_binding=resolve_production_python_runtime_binding(
                                                   root, interpreter_redirector=validated['production']['python']),
                                               now=datetime.now(timezone.utc))
    identity = json.loads(Path(inputs['identity']['path']).read_bytes())
    reference = json.loads(Path(inputs['credential_reference_manifest']['path']).read_bytes())
    campaign_path, campaign = _reserve_campaign(root, maker=reference['funder_address'], scope=scope)
    client = None
    stream = None
    context = None
    controller_started = False
    handlers = {}
    result = None
    cleanup = None
    try:
        credentials = cli.load_global_credential_bundle()
        client = cli.build_unified_clob_client(credentials, identity, expected_signer_address=reference['wallet_address'])
        maker = str(credentials.funder)
        stream = Stage2UserStreamReader(token_ids=tokens, authority_root=root,
            api_key=credentials.api_key, secret=credentials.api_secret, passphrase=credentials.api_passphrase,
            maker_address=maker, condition_id=scope['condition_id'], journal_path=scope['user_stream_journal_out'])
        heartbeat = cli.OfficialHeartbeatSender(signer_address=client.signer, api_key=credentials.api_key,
            api_secret=credentials.api_secret, api_passphrase=credentials.api_passphrase, timeout_seconds=2)
        adapters = [OfficialPolymarketGlobalAdapter(client, token_id=token, maker_address=maker,
            condition_id=scope['condition_id'], user_event_reader=lambda token=token: stream.events_for_token(token),
            user_event_health_reader=stream.health,
            position_reader=lambda: cli.fetch_current_positions(maker, scope['condition_id']),
            heartbeat_sender=heartbeat, market_rule_reader=lambda token=token: cli.fetch_market_rule_endpoints(token, timeout_seconds=2),
            authoritative_readers_verified=True, max_order_notional=PROFILE.per_order_pusd,
            envelope_profile_id=PROFILE.profile_id, envelope_authority_root=root) for token in tokens]
        context = cli.LivePilotContext(credentials=credentials, client=client, user_stream=stream,
                                       adapter=adapters[0], credential_topology={})
        cli.wait_for_user_stream(stream)
        pre_submit_attestor()
        initial = public.snapshot(scope['condition_id'], tokens)
        for token in tokens:
            if initial['rules'][token] != selected['snapshot']['rules'][token]:
                raise RuntimeError('selected venue rules changed before submit')
        fresh_quote = public_quote(initial, now=datetime.now(timezone.utc), condition_id=scope['condition_id'], token_ids=tokens)
        if fresh_quote.predicted_per_minute_many * 360 < 2:
            raise RuntimeError('selected band no longer meets the frozen prediction floor')
        def interrupted(_signum, _frame):
            raise KeyboardInterrupt
        for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
            if hasattr(signal, name):
                value = getattr(signal, name)
                handlers[value] = signal.signal(value, interrupted)
        readers = RewardsReaders(client, purpose='sealed_stage2_scoring')
        treatment_scope = {**scope['stage2'], 'condition_id': scope['condition_id'],
                           'maker_address': maker, 'end_at_utc': scope['run_not_after_local'],
                           'campaign_attempt_path': str(campaign_path), 'campaign_attempt_sha256': digest(campaign)}
        controller_started = True
        result = run_hold_session(adapters, predecessor['gates'], scope=treatment_scope, initial_public=initial,
            public_reader=lambda **kwargs: public.snapshot(scope['condition_id'], tokens, **kwargs), geography_reader=geography_reader,
            journal_path=scope['lifecycle_journal_out'], prediction_path=scope['result_out'],
            confirmation=CONFIRMATION, operator_stop=lambda: False, scoring_reader=readers.scoring)
    finally:
        for value, handler in handlers.items():
            signal.signal(value, handler)
        if context is not None:
            # The hold controller owns unconditional cancel/reconcile. A setup
            # failure before that boundary retains the existing cleanup path.
            cleanup = cli._cleanup_context(context, cancel_all_required=not controller_started)
        elif client is not None:
            client.close()
    complete = result['cleanup_ok'] and cleanup is not None and cleanup['ok'] and not result['fill_seen']
    try:
        journal = [json.loads(line) for line in Path(scope['lifecycle_journal_out']).read_bytes().splitlines()]
        orders = {r['order_id']: tokens[r['leg'] - 1] for r in journal if r['event'] == 'order_acknowledged'}
        stream_evidence = verify_stage2_user_stream_journal(scope['user_stream_journal_out'], maker=maker,
            condition=scope['condition_id'], tokens=tokens, orders=orders)
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        stream_evidence = {'status': 'FAIL', 'exception_type': type(exc).__name__}
        complete = False
    write_new(scope['command_receipt_out'], {'schema_version': SCHEMA_VERSION, 'kind': 'session',
        'status': 'PASS' if complete else 'FAIL', 'stage': 'stage2_hold',
        'prediction_sha256': digest(result), 'profile_sha256': PROFILE.sha256, 'context_cleanup': cleanup,
        'cleanup_ok': complete, 'fill_seen': result['fill_seen'], 'session_confirmation': confirmation_receipt,
        'final_stream_evidence': stream_evidence})
    write_new(campaign_path.with_name(campaign_path.name.replace('.attempt.json', '.result.json')),
              {'schema_version': SCHEMA_VERSION, 'kind': 'session', 'attempt_sha256': digest(campaign),
               'prediction_sha256': digest(result), 'cleanup_ok': complete, 'fill_seen': result['fill_seen']})
    return {**result, 'cleanup_ok': complete, 'context_cleanup': cleanup}
