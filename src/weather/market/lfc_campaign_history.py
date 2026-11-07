"""Legacy money ambiguity survives reconciliation and needs explicit owner recovery."""
from pathlib import Path

from weather.market.lfc_campaign_guard import require_account
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.market.mm_stage2_hold import digest
from weather.operations.live_path_security import validate_contained_regular_file


def private_history_files(ledger, root, session_id):
    relative = Path(ledger.sessions[session_id]['start']['directory'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('historical_private_path')
    directory = Path(root) / relative
    journal = validate_contained_regular_file(root, directory / 'journal.jsonl')
    paths = [journal]
    paths += [path for name in ('prediction.json', 'session_end.json', 'attempt.json', 'selection.json')
              if (path := directory / name).exists()]
    paths += list(directory.glob('submit-*.intent.json')) + list(directory.glob('submit-*.ack.json'))
    if len(paths) > 30:
        raise ValueError('historical_private_file_limit')
    return {str(path.relative_to(Path(root))): file_sha(validate_contained_regular_file(root, path)) for path in paths}


def normal_private_proof(ledger, root, session_id):
    from weather.market.lfc_campaign_proof import local_money_proof
    relative = Path(ledger.sessions[session_id]['start']['directory'])
    if relative.is_absolute() or '..' in relative.parts:
        return False
    directory = Path(root) / relative
    hashes = {name: file_sha(validate_contained_regular_file(root, directory / name))
              for name in ('journal.jsonl', 'prediction.json', 'session_end.json')}
    return local_money_proof(directory, ledger=ledger, session_id=session_id, attempt_id=None,
                             outcome={'evidence_sha256': hashes}, legacy=True)['complete']


def history_manifest(ledger, root):
    qualified = qualified_exercises(ledger, root)
    files = {}
    for session_id, session in ledger.sessions.items():
        if session['start'].get('autostart_attempt_id'):
            continue
        if session_id in qualified:
            # Qualification permits intentional S0 failure semantics, not loss
            # of the private files that are present at owner enrollment.
            if session['start'].get('directory'):
                files.update(private_history_files(ledger, root, session_id))
            continue
        files.update(private_history_files(ledger, root, session_id))
    if qualified:
        from weather.market.lfc_cli import SESSION0_PASS_FILE
        path = validate_contained_regular_file(root, Path(root) / SESSION0_PASS_FILE)
        files[str(path.relative_to(Path(root)))] = file_sha(path)
    return files


def qualified_exercises(ledger, root):
    from weather.market.lfc_cli import SESSION0_PASS_FILE, session0_attestation
    if session0_attestation(root, ledger):
        return set()
    body = strict_json(read_bytes(Path(root) / SESSION0_PASS_FILE, 65536))
    return set(body['sessions'].values())


def historical_ambiguities(ledger, root):
    """A later empty account or adopted ACK never clears original uncertainty.

    Only the exact S0 exercises named by the existing validated owner attestation
    are exempt. Ordinary manual/F0 sessions never get that exemption.
    """
    qualified = qualified_exercises(ledger, root)
    adopted = {ledger.legs[r['intent_key']]['session_id'] for r in ledger.rows if r['event'] == 'leg_adopt'}
    issues = {}
    for session_id, session in ledger.sessions.items():
        start, end = session['start'], session['end']
        if start.get('autostart_attempt_id'):
            continue  # Claim/result continuity is checked separately, including after close.
        if start.get('counted') is False and session_id in qualified:
            continue
        try:
            private_complete = normal_private_proof(ledger, root, session_id)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            private_complete = False
        if (end is None or end.get('unknown_submit') is not False or session_id in adopted or
                end.get('reason') == 'reconciled_after_crash' or not private_complete):
            issues[session_id] = digest({'start': start, 'end': end,
                                         'legs': [ledger.legs[k] for k in session['legs']]})
    return issues


def validate_recovery(ledger, root, event):
    path = validate_contained_regular_file(root, Path(root) / event['file'])
    if file_sha(path) != event['file_sha256']:
        raise ValueError('historical_recovery_evidence_missing')
    row = strict_json(read_bytes(path, 2_000_000))
    proof = row.get('proof', {})
    if (row.get('authority') != 'owner_history_recovery' or row.get('session_id') != event['session_id'] or
            row.get('original_evidence_sha256') != event['original_evidence_sha256'] or
            row.get('ledger_head_sha256') != event['previous_sha256'] or
            row.get('account_read_sha256') != digest(row.get('account_read')) or
            proof.get('read_sha256') != row.get('account_read_sha256') or
            proof.get('ledger_head_sha256') != row.get('ledger_head_sha256') or
            proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
            proof.get('unknown_submit') is not False or row.get('containment_proven') is not True):
        raise ValueError('historical_recovery_invalid')
    originals = row.get('original_private_evidence')
    if not isinstance(originals, dict) or not originals:
        raise ValueError('historical_recovery_originals_missing')
    for name, sha in originals.items():
        if file_sha(validate_contained_regular_file(root, Path(root) / name)) != sha:
            raise ValueError('historical_recovery_originals_changed')
    return row


def history_refusals(ledger, root):
    issues = historical_ambiguities(ledger, root)
    for event in ledger.history_recoveries:
        validate_recovery(ledger, root, event)
        if issues.get(event['session_id']) == event['original_evidence_sha256']:
            del issues[event['session_id']]
    return issues


def record_owner_recovery(ledger, root, session_id, *, account_read, proof, now, containment_proven):
    """Owner CLI only; called under account/all-slot exclusion after confirmation.

    Append-only evidence preserves failed flags and the original consumed date.
    No adoption, cancellation, date reset or monetary credit is performed here.
    """
    require_account(ledger.rows[0]['maker_address'])
    issues = history_refusals(ledger, root)
    if (session_id not in issues or ledger.open_sessions() or ledger.unresolved_legs() or ledger.halted or
            proof.get('ledger_head_sha256') != ledger.previous or proof.get('read_sha256') != digest(account_read) or
            proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
            proof.get('unknown_submit') is not False or containment_proven is not True):
        raise ValueError('owner_history_repair_required')
    name = 'history-recoveries/' + digest({'session_id': session_id, 'head': ledger.previous}) + '.json'
    row = {'authority': 'owner_history_recovery', 'session_id': session_id,
           'original_evidence_sha256': issues[session_id], 'ledger_head_sha256': ledger.previous,
           'account_read': account_read, 'account_read_sha256': digest(account_read), 'proof': proof,
           'containment_proven': True, 'at_utc': now.isoformat()}
    row['original_private_evidence'] = private_history_files(ledger, root, session_id)
    write_new(Path(root) / name, row)
    return ledger.record('owner_history_recovery', session_id=session_id,
                         original_evidence_sha256=issues[session_id], file=name,
                         file_sha256=file_sha(Path(root) / name))
