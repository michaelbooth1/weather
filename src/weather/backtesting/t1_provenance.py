"""Offline source/raw-evidence certificate and independent LFC ledger verifier.

Hashes prove byte identity, not venue authenticity. A reviewed prospective
evidence contract supplies that provenance boundary; a caller's complete flag
alone cannot mint a certificate. No implicit discovery or credential access.
"""
import hashlib
import json
from pathlib import Path

from weather.backtesting.t1_types import ZERO, canonical, digest, number, source_hash, utc


def verify_ledger(path, snapshot, account_id):
    previous, count, last, version = None, 0, None, 0
    legs, by_order, sessions = {}, {}, {}
    with Path(path).open('rb') as handle:
        while line := handle.readline(1024 * 1024 + 1):
            if len(line) > 1024 * 1024 or count >= 100000:
                raise ValueError('bounded ledger history limit')
            row = json.loads(line)
            at = utc(row['recorded_at_utc'])
            current = {'lfc_ledger_v0.1': 1, 'lfc_ledger_v0.2': 2}.get(row['schema_version'], 0)
            event = row['event']
            if (canonical(row) != line or row['kind'] != 'lfc_ledger' or row['sequence'] != count
                    or row['previous_sha256'] != previous or current < max(1, version)
                    or last is not None and at < last or (count == 0) != (event == 'genesis')):
                raise ValueError('invalid ledger history chain')
            if event == 'genesis':
                if row['maker_address'].lower() != account_id.lower() or number(row['budget_pusd']) != number(snapshot['budget_pusd']):
                    raise ValueError('ledger account or budget mismatch')
            elif event == 'session_start':
                if row['session_id'] in sessions:
                    raise ValueError('duplicate ledger session')
                sessions[row['session_id']] = False
            elif event == 'session_end':
                if row['session_id'] not in sessions or sessions[row['session_id']]:
                    raise ValueError('invalid ledger session end')
                sessions[row['session_id']] = True
            elif event == 'leg_intent':
                if row['session_id'] not in sessions or sessions[row['session_id']] or row['intent_key'] in legs:
                    raise ValueError('invalid ledger intent')
                number(row['price'], maximum=number('1'))
                number(row['size'])
                legs[row['intent_key']] = {k: row[k] for k in ('session_id', 'intent_key', 'token_id', 'condition_id', 'price', 'size')}
                legs[row['intent_key']].update(order_id=None, status='intent', size_matched='0')
            elif event in ('leg_ack', 'leg_adopt'):
                leg = legs.get(row['intent_key'])
                if leg is None or leg['order_id'] is not None or not row['order_id'] or row['order_id'] in by_order or event == 'leg_adopt' and current != 2:
                    raise ValueError('invalid ledger acknowledgment')
                leg.update(order_id=row['order_id'], status='open')
                by_order[row['order_id']] = leg
            elif event == 'leg_terminal':
                leg = by_order.get(row['order_id'])
                if leg is None or leg['status'] == 'terminal':
                    raise ValueError('invalid ledger terminal')
                number(row['size_matched'], maximum=number(leg['size']))
                leg.update(status='terminal', size_matched=row['size_matched'])
            elif event in ('halt', 'mismatch'):
                raise ValueError('halted or mismatched ledger cannot qualify')
            elif event != 'baseline':
                raise ValueError('unknown ledger event')
            previous, last, version = hashlib.sha256(line).hexdigest(), at, current
            count += 1
    if (not count or count != snapshot['history_rows'] or previous != snapshot['history_last_sha256']
            or last != utc(snapshot['recorded_at_utc'])
            or sorted(legs.values(), key=lambda r: r['intent_key']) != sorted(snapshot['legs'], key=lambda r: r['intent_key'])
            or set(by_order) != set(snapshot['our_order_ids'])):
        raise ValueError('ledger snapshot disagrees with full history')
    return {'rows': count, 'tail_sha256': previous, 'legs': len(legs)}


def verify_bundle(bundle, root):
    """Hash explicit safe relative files, streaming; never traverse a directory."""
    root = Path(root).resolve()
    verified = {}
    total = 0
    for entry in bundle['files']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
            raise ValueError('raw evidence path must stay within the staged receipt bundle')
        path = root / relative
        if (any(part.lower().startswith('.env') or part.lower() in ('local', 'auth.json') for part in relative.parts)
                or path.suffix.lower() not in ('.json', '.jsonl', '.txt', '.csv', '.py')
                or any((root.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1))
                or not path.resolve().is_relative_to(root)):
            raise ValueError('unsafe raw evidence path')
        total += path.stat().st_size
        if total > 2 * 1024 ** 3:
            raise ValueError('raw evidence bundle exceeds bounded 2 GiB session limit')
        expected, hasher = source_hash(entry['sha256']), hashlib.sha256()
        with path.open('rb') as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        if hasher.hexdigest() != expected or entry['role'] in verified:
            raise ValueError('raw evidence hash mismatch or duplicate role')
        verified[entry['role']] = {'path': path, 'sha256': expected}
    return verified


def session_certificate(result, code, receipts, payload, root, *, cli_inputs=None):
    """The only production PASS: real, clean, reviewed and financially reconciled.

    A partial recorder or synthetic metric match never qualifies a session.
    Conservative bound calibration is reported separately from point accuracy.
    """
    from weather.backtesting.t1_accuracy import COMPATIBLE_RECORDER_PINS

    gaps = []
    population_hash = None
    projection = {'status': 'NOT QUALIFIED', 'reason': 'raw financial roles missing'}
    idle = (result.get('metrics_pass') is True and result.get('order_ids') == []
            and result.get('actual_filled_orders') == 0
            and number(result.get('rewards', {}).get('actual', '0')) == ZERO
            and number(result.get('rewards', {}).get('predicted', '0')) == ZERO
            and number(result.get('rebates', {}).get('actual', '0')) == ZERO
            and number(result.get('rebates', {}).get('predicted', '0')) == ZERO
            and number(result.get('simulation', {}).get('reward_accrued', '0')) == ZERO
            and number(result.get('simulation', {}).get('rebate_accrued', '0')) == ZERO)
    if result.get('synthetic'):
        gaps.append('synthetic_receipts')
    if not code['worktree_clean']:
        gaps.append('dirty_source')
    if not result.get('metrics_pass') or not result.get('simulator_complete'):
        gaps.append('session_metrics_not_passed')
    if not result.get('accounting_complete'):
        gaps.append('economic_transition_coverage_or_state_not_verified')
    if result.get('completed_cash', {}).get('status') != 'COMPLETE':
        gaps.append('completed_cash_not_final')
    if result.get('simulation', {}).get('competition_estimate') == 'aggregate_upper_bound':
        gaps.append('one_sided_bound_is_not_point_pnl_accuracy')
    if result.get('receipts_sha256') != digest(receipts) or result.get('payload_sha256') != digest(payload):
        gaps.append('arithmetic_inputs_changed_before_certification')
    tolerance = result.get('tolerance', {})
    for name, ceiling in (('cash_conservation_absolute', '.00001'), ('campaign_net_absolute', '.00001'), ('joint_monetary_absolute', '.01'), ('monetary_absolute', '.01')):
        if name not in tolerance or number(tolerance[name]) > number(ceiling):
            gaps.append(name + '_exceeds_certificate_ceiling')
    if number(tolerance.get('position_absolute_shares', '0')) != ZERO:
        gaps.append('exact_native_positions_require_zero_tolerance')
    if receipts.get('journal_pin') not in COMPATIBLE_RECORDER_PINS:
        gaps.append('unreviewed_actual_recorder_pin')
    required = ('journal', 'profile', 'ledger', 'clob', 'wallet', 'wallet_observations', 'reward_d1', 'reward_d2',
                'books', 'marks', 'terms', 'settlement', 'redemptions', 'rebates', 'preregistration', 'exporter',
                'reward_samples', 'market_state', 'clock', 'rebate_rounding', 'recorder_manifest')
    if idle:
        required = tuple(role for role in required if role not in (
            'books', 'marks', 'terms', 'rebates', 'reward_samples', 'market_state', 'rebate_rounding'))
    bundle = receipts.get('evidence_bundle')
    if bundle is None:
        gaps.append('missing_raw_evidence_bundle')
        verified = {}
    else:
        verified = verify_bundle(bundle, root)
        gaps.extend('missing_raw_' + name for name in required if name not in verified)
        from weather.backtesting.t1_raw_projection import verify_projection

        try:
            projection = verify_projection(verified, receipts, payload, result)
            if projection['transitions']['status'] != 'PASS':
                gaps.append('raw_economic_transition_projection_not_verified')
            if projection['wallet_observations']['status'] != 'PASS':
                gaps.append('shared_wallet_observations_not_verified')
            if not idle and projection['market_projection']['status'] != 'PASS':
                gaps.append('raw_market_projection_not_verified')
        except (ValueError, KeyError, TypeError) as exc:
            projection = {'status': 'NOT QUALIFIED', 'reason': str(exc)}
            gaps.append('raw_projection_not_verified: ' + str(exc))
        hashes = {v['sha256'] for v in verified.values()}
        def lineage(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.endswith('source_sha256'):
                        yield source_hash(child)
                    else:
                        yield from lineage(child)
            elif isinstance(value, list):
                for child in value:
                    yield from lineage(child)
        declared = set(lineage(payload)) | set(lineage({k: v for k, v in receipts.items() if k != 'evidence_bundle'}))
        if not declared <= hashes:
            gaps.append('unverified_raw_source_hashes')
        if 'ledger' in verified and 'lfc_ledger' in receipts:
            verify_ledger(verified['ledger']['path'], receipts['lfc_ledger'], result['scope']['account_id'])
        if 'journal' in verified and verified['journal']['sha256'] != result['journal_sha256']:
            raise ValueError('journal raw bundle mismatch')
        if 'profile' in verified and verified['profile']['sha256'] != receipts.get('profile_sha256'):
            raise ValueError('profile raw bundle mismatch')
        if 'recorder_manifest' in verified:
            recorder = json.loads(verified['recorder_manifest']['path'].read_bytes())
            if (recorder.get('git_commit') != receipts.get('journal_pin') or recorder.get('worktree_clean') is not True
                    or recorder.get('journal_sha256') != result['journal_sha256']
                    or recorder.get('profile_sha256') != result.get('profile_sha256')
                    or recorder.get('session_id') != result['scope']['session_id']):
                gaps.append('actual_recorder_source_manifest_mismatch')
        if 'preregistration' in verified:
            contract = json.loads(verified['preregistration']['path'].read_bytes())
            for key, actual in (('code', code), ('config_sha256', result['config_sha256']),
                                ('tolerance_sha256', result['tolerance_sha256']), ('exporter_sha256', verified.get('exporter', {}).get('sha256'))):
                if contract.get(key) != actual:
                    gaps.append('preregistration_' + key + '_mismatch')
            if contract.get('missing_session_rule') != 'FAIL_WHOLE_CAMPAIGN_RETAIN_FULL_LOSS_ROWS':
                gaps.append('missing_frozen_population_rule')
            population = contract.get('expected_session_ids', [])
            if (not population or len(set(population)) != len(population)
                    or result['scope']['session_id'] not in population):
                gaps.append('missing_frozen_session_population')
            else:
                population_hash = digest(sorted(population))
            if not contract.get('frozen_at_utc') or utc(contract['frozen_at_utc']) > utc(result['period_start']):
                gaps.append('contract_not_declared_before_session')
    # No authoritative midpoint-rule verifier is implemented. A hash-linked
    # declaration or a basis label cannot substitute for one (T035 F09).
    midpoint_ok = False
    # Population consistency is checked by the raw projector. Authority for an
    # actual venue sample feed is still unavailable, not established by labels.
    sample_ok = False
    # Projection of supplied condition/day totals or precision declarations is
    # not independent verification of the unpublished global inputs/rule.
    rounding_ok = False
    components = {}
    for component, qualified in (
            ('realized_reward_sampling', idle or sample_ok),
            ('midpoint_semantics', idle or midpoint_ok),
            ('public_execution_identity', idle),
            ('condition_day_rebates', idle),
            ('fee_rounding', idle or rounding_ok)):
        components[component] = {'status': 'NOT APPLICABLE' if idle else 'PASS' if qualified and not gaps else 'NOT QUALIFIED',
                                 'evidence_required': 'Retained raw evidence and the common reviewed prospective contract.'}
        if not qualified:
            gaps.append(component + '_not_qualified')
    components['passive_posting_response'] = {'status': 'NOT QUALIFIED',
        'bound': 'Zero incentive income; all commanded lots may fill and lose.',
        'evidence_required': 'Independent validated intervention/response envelope; public passive data does not identify this.'}
    components['persistent_capital'] = {'status': 'NOT QUALIFIED',
        'evidence_required': 'Reviewed persistent principal/inventory ledger, independently reconciled lot carry and funding; current scope is flat nonoverlapping periods only.'}
    if not idle:
        components['midpoint_semantics']['evidence_required'] = 'STILL OPEN F09: authoritative rule/comparison verification is not implemented; hash-linked declarations are insufficient.'
        components['realized_reward_sampling']['evidence_required'] = 'STILL OPEN F08 authority: valid raw sample populations alone do not prove venue sampling; no authoritative feed adapter is implemented.'
        components['public_execution_identity']['evidence_required'] = 'Independent native consumption/finality/route join; annotations on last_trade_price are insufficient.'
        components['condition_day_rebates']['evidence_required'] = 'Independently verified full condition/day paid-fee pool, eligible maker-weight denominator and payment attribution.'
        components['fee_rounding']['evidence_required'] = 'Dated authoritative precision rule or independently checked per-match receipt experiment; a hash-linked rule label is insufficient.'
    return {'status': 'PASS' if not gaps else 'NOT QUALIFIED', 'gaps': sorted(set(gaps)),
            'code_sha256': digest(code), 'raw_bundle_sha256': digest(bundle) if bundle else None,
            'result_sha256': digest(result), 'cli_inputs_sha256': digest(cli_inputs),
            'preregistration_sha256': verified.get('preregistration', {}).get('sha256'),
            'components': components,
            'population_sha256': population_hash,
            'raw_projection': projection,
            'claim': 'CONDITIONAL_REAL_SESSION_COMPLETED_CASH_REPRODUCTION',
            'capital_scope': 'VERIFIED_FLAT_NONOVERLAPPING_PERIODS',
            'passive_posting_response': 'NOT QUALIFIED', 'trial_can_pass': False}


def certify_campaign(envelopes, *, expected_session_ids, min_sessions, min_filled_orders, min_paid_reward,
                     synthetic_diagnostic=False):
    """Consume complete CLI envelopes, never unbound result dictionaries."""
    from weather.backtesting.t1_accuracy import combine_session_gates

    if any('result' not in e or 'scope' not in e['result'] for e in envelopes):
        raise ValueError('real clean-code campaign envelopes required')
    supplied = [e['result']['scope']['session_id'] for e in envelopes]
    if sorted(supplied) != sorted(expected_session_ids) or len(set(supplied)) != len(supplied):
        raise ValueError('campaign requires every frozen population member, including zero/interrupted sessions')
    if synthetic_diagnostic:
        if not envelopes or not all(e.get('synthetic') is True for e in envelopes):
            raise ValueError('synthetic diagnostic cannot consume real or mixed envelopes')
        if len({digest(e['code']) for e in envelopes}) != 1:
            raise ValueError('mixed campaign source closure')
        report = combine_session_gates([e['result'] for e in envelopes], min_sessions=min_sessions,
            min_filled_orders=min_filled_orders, min_paid_reward=min_paid_reward, expected_session_ids=expected_session_ids)
        report['status'] = 'SYNTHETIC_PASS' if report['status'] == 'PASS' else report['status']
        report['qualification'] = 'SYNTHETIC_DIAGNOSTIC_ONLY'
        report['synthetic'] = True
        return report
    if not envelopes or any(e.get('synthetic') or e['code']['worktree_clean'] is not True for e in envelopes):
        raise ValueError('real clean-code campaign envelopes required')
    if len({digest(e['code']) for e in envelopes}) != 1:
        raise ValueError('mixed campaign source closure')
    if any(e.get('accuracy_certificate', {}).get('status') != 'PASS' for e in envelopes):
        return {'status': 'NOT QUALIFIED', 'sessions': len(envelopes), 'session_ids': supplied,
                'reason': 'Every population member needs a valid receipt certificate; retain failures.', 'trial_can_pass': False}
    for envelope in envelopes:
        certificate = envelope['accuracy_certificate']
        if (certificate.get('result_sha256') != digest(envelope['result'])
                or certificate.get('code_sha256') != digest(envelope['code'])
                or certificate.get('cli_inputs_sha256') != digest(envelope['inputs'])):
            raise ValueError('campaign envelope changed after receipt certification')
    preregs = {e['accuracy_certificate'].get('preregistration_sha256') for e in envelopes}
    if len(preregs) != 1 or None in preregs:
        raise ValueError('campaign requires one common frozen preregistration')
    if any(e['accuracy_certificate'].get('population_sha256') != digest(sorted(expected_session_ids)) for e in envelopes):
        raise ValueError('campaign population differs from its common frozen contract')
    report = combine_session_gates([e['result'] for e in envelopes], min_sessions=min_sessions,
                                   min_filled_orders=min_filled_orders, min_paid_reward=min_paid_reward,
                                   expected_session_ids=expected_session_ids)
    report['source_closure_sha256'] = digest(envelopes[0]['code'])
    return report
