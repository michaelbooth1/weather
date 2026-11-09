"""Aggregate bounded retained band packets without weakening per-band/N1 proofs."""
from pathlib import Path

from weather.market.lfc_completion import evidence_flags
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, STATE_JSON_LIMIT
from weather.market.lfc_session_status import SessionStatus
from weather.market.lfc_f2_economics import economics
from weather.market.lfc_f2_breadth import arm_field_keys
from weather.market.mm_stage2_hold import digest, _order_id


ROOT_FILES = ('journal.jsonl', 'prediction.json', 'session_end.json', 'attempt.json', 'selection.json', 'f2_manifest.json')


def result_file_limit(ledger, attempt_id):
    """Seven root originals plus each ledger-bound band's finite inventory."""
    from weather.market.lfc_f2_breadth import captured_market_ids
    from weather.market.lfc_f2_pinb import session_limits
    sessions = [sid for sid, row in ledger.sessions.items()
                if row['start'].get('autostart_attempt_id') == attempt_id]
    if not 1 <= len(sessions) <= len(captured_market_ids()):
        raise ValueError('f2_private_band_coverage')
    return 7 + sum(5 + 2*session_limits(ledger, sid)[0] for sid in sessions)


def manifest_at(directory):
    row = strict_json(read_bytes(Path(directory) / 'f2_manifest.json', 1_000_000))
    bands = row.get('bands')
    from weather.market.lfc_f2_breadth import captured_market_ids
    version = row.get('schema_version')
    limit = len(captured_market_ids()) if version == 'lfc_f2_manifest_v0.2' else 2
    if (version not in {'lfc_f2_manifest_v0.1', 'lfc_f2_manifest_v0.2'} or
            not isinstance(bands, list) or not 1 <= len(bands) <= limit or
            len({b['session_id'] for b in bands}) != len(bands) or
            len({b['directory'] for b in bands}) != len(bands) or
            any(b['directory'] not in {'band-' + str(i) for i in range(1, limit + 1)} for b in bands)):
        raise ValueError('f2_private_manifest')
    return row


def money_proof(directory, *, ledger, session_id, attempt_id, outcome, owner=False):
    from weather.market.lfc_campaign_proof import journal_contract, local_money_proof, owner_originals
    directory = Path(directory).absolute()
    manifest = manifest_at(directory)
    if manifest['session_id'] != session_id or manifest['attempt_id'] != attempt_id:
        raise ValueError('f2_private_identity')
    hashes = dict(outcome['evidence_sha256'])
    for name in ROOT_FILES:
        if hashes.get(name) != file_sha(directory / name):
            raise ValueError('f2_private_root_hash')
    prediction = strict_json(read_bytes(directory / 'prediction.json', 2_000_000))
    ending = strict_json(read_bytes(directory / 'session_end.json', 2_000_000))
    attempt = strict_json(read_bytes(directory / 'attempt.json', 65536))
    go_sha = prediction.get('scope', {}).get('go_account_sha256')
    if go_sha is not None:
        if hashes.get('go_account.json') != go_sha or file_sha(directory / 'go_account.json') != go_sha:
            raise ValueError('f2_go_account_hash')
        go = strict_json(read_bytes(directory / 'go_account.json', STATE_JSON_LIMIT))
        proof = go['proof']
        if (go.get('attempt_id') != attempt_id or digest(go['read']) != proof.get('read_sha256') or
                proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
                proof.get('unknown_submit') is not False or proof.get('capital', {}).get('cash_bridge_complete') is not True or
                proof.get('ledger_head_sha256') not in {ledger.row_sha256(i) for i in range(len(ledger.rows))}):
            raise ValueError('f2_go_account_binding')
    if (prediction.get('f2_session') is not True or prediction['scope'].get('session_id') != session_id or
            prediction['scope'].get('attempt_id') != attempt_id or prediction['scope'].get('protocol') != ('lfc_autostart_v3' if manifest['schema_version'] == 'lfc_f2_manifest_v0.2' else 'lfc_autostart_v2') or
            prediction['scope'].get('policy_sha256') != manifest['policy_sha256'] or
            attempt.get('policy_sha256') != manifest['policy_sha256'] or attempt.get('attempt_id') != attempt_id or
            prediction.get('manifest_sha256') != hashes['f2_manifest.json'] or
            prediction.get('journal_sha256') != hashes['journal.jsonl'] or
            ending.get('session_id') != session_id or evidence_flags(ending) != evidence_flags(prediction)):
        raise ValueError('f2_private_terminal')
    _, _, _, root_gaps, root_money_gaps = journal_contract(directory / 'journal.jsonl', prediction, owner_review=owner)
    expected_sessions = {sid for sid, s in ledger.sessions.items()
                         if s['start'].get('autostart_attempt_id') == attempt_id}
    declared_go = {ledger.sessions[sid]['start']['go_account_sha256'] for sid in expected_sessions
                   if ledger.sessions[sid]['start'].get('go_account_sha256') is not None}
    if declared_go and declared_go != {go_sha}:
        raise ValueError('f2_go_account_scope')
    if expected_sessions != {b['session_id'] for b in manifest['bands']}:
        raise ValueError('f2_private_band_coverage')
    proofs = []
    for band in manifest['bands']:
        relative, sid = band['directory'], band['session_id']
        session = ledger.sessions[sid]
        if (session['start'].get('condition_id') != band['condition_id'] or
                session['start'].get('autostart_policy_sha256') != manifest['policy_sha256'] or
                Path(session['start']['directory']).as_posix() !=
                (directory / relative).relative_to(ledger.path.parent).as_posix()):
            raise ValueError('f2_private_band_scope')
        for name, sha in band['evidence_sha256'].items():
            if Path(name).name != name or file_sha(directory / relative / name) != sha or hashes.get(relative + '/' + name) != sha:
                raise ValueError('f2_private_band_hash')
        evidence = {'evidence_sha256': band['evidence_sha256']}
        proof = (owner_originals(directory / relative, ledger=ledger, session_id=sid, attempt_id=attempt_id, outcome=evidence)
                 if owner else local_money_proof(directory / relative, ledger=ledger, session_id=sid,
                                                attempt_id=attempt_id, outcome=evidence))
        if not owner and (proof.get('complete') is not True or proof.get('unknown_submit') is not False):
            raise ValueError('f2_private_band_incomplete')
        proofs.append(proof)
    if owner:
        return {'session_id': session_id, 'original_private_files': hashes, 'bands': proofs,
                'raw_flags': evidence_flags(prediction), 'resolved_legs_sha256': digest(proofs)}
    if (prediction['post_count'] != sum(len(ledger.sessions[b['session_id']]['legs']) for b in manifest['bands']) or
            prediction['order_ids'] != [ledger.legs[key]['order_id'] for b in manifest['bands']
                                       for key in ledger.sessions[b['session_id']]['legs']] or
            prediction.get('unknown_submit') is not False or prediction.get('failure_type') is not None):
        raise ValueError('f2_private_order_coverage')
    return {'complete': True, 'unknown_submit': False, 'raw_flags': evidence_flags(prediction),
            'evidence_sha256': hashes, 'bands': proofs,
            'explained_gaps': sorted(root_gaps | {gap for p in proofs for gap in p['explained_gaps']}),
            'money_read_gaps': sorted(root_money_gaps | {gap for p in proofs for gap in p['money_read_gaps']})}


class F2Status(SessionStatus):
    OUTCOME_SCHEMA = 'lfc_session_outcome_v0.2'

    def _facts(self):
        coordinator = self.session
        if coordinator is None:
            return super()._facts()
        bands, hashes, placed, cancelled, fills = [], {}, set(), set(), []
        for band in coordinator.bands:
            helper = SessionStatus(kind='f2-band', clock=self.clock, monotonic=self.monotonic,
                                   policy_metadata=self.policy_metadata)
            helper.session_id, helper.session, helper.ledger = band.session_id, band, self.ledger
            helper.evidence_directory = band.directory
            helper.selection = next(row for row in band.table['rows'] if row['condition_id'] == band.condition)
            helper.open_rows = (None if coordinator.open_rows is None else
                                [row for row in coordinator.open_rows if _order_id(row) in band.known])
            facts = helper._facts()
            bands.append({'session_id': band.session_id, 'reason': coordinator.results.get(band.session_id, {}).get('reason'),
                          **({key: band.scope[key] for key in ('market_id', *arm_field_keys(band.campaign_policy))}
                              if getattr(band, 'breadth', False) else {}), **facts})
            prefix = band.directory.relative_to(self.evidence_directory).as_posix() + '/'
            hashes.update({prefix + name: sha for name, sha in facts['evidence_sha256'].items()})
            hashes.update({prefix + path.name: file_sha(path) for pattern in ('submit-*.intent.json', 'submit-*.ack.json')
                           for path in band.directory.glob(pattern)})
            placed.update(facts['orders_placed']['ids'])
            cancelled.update(facts['orders_cancelled']['ids'])
            fills.extend(facts['fills'])
        for name in ROOT_FILES:
            hashes[name] = file_sha(self.evidence_directory / name)
        if coordinator.scope.get('go_account_sha256') is not None:
            hashes['go_account.json'] = file_sha(self.evidence_directory / 'go_account.json')
        flags = {'evidence_complete': not coordinator.evidence_failed and all(b['evidence_complete'] for b in bands),
                 'inventory_proven': coordinator.inventory_proven,
                 'unknown_submit': coordinator.posts != len(coordinator.known)}
        return {'f2_session': True, 'bands': bands, 'event': None, 'band': None, 'tokens': [],
                'orders_placed': {'count': None if flags['unknown_submit'] else len(placed), 'known_count': len(placed),
                                  'ids': sorted(placed), 'attempted': coordinator.posts},
                'orders_cancelled': {'count': len(cancelled), 'ids': sorted(cancelled)},
                'orders_open_at_exit': None if coordinator.open_rows is None else [_order_id(r) for r in coordinator.open_rows],
                'fills': fills, 'cancellation_requested': True, 'cancellation_proven': coordinator.cancellation_ok,
                'cleanup_ok': coordinator.cleanup_ok and flags['evidence_complete'], **flags,
                'evidence_sha256': hashes, 'economics': economics(coordinator)}
