"""Close unposted claims from durable absence of intents; never infer a POST."""
from weather.market.lfc_campaign_guard import require_account
from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import digest
from weather.market.lfc_ledger_queries import event_rows


def attempt_sessions(ledger, attempt):
    return {sid: session for sid, session in ledger.sessions.items()
            if session['start'].get('autostart_attempt_id') == attempt}


def attempt_intents(ledger, attempt):
    indexed = getattr(ledger, 'attempt_intent_rows', None)
    if callable(indexed):
        return list(indexed(attempt))
    sessions = attempt_sessions(ledger, attempt)
    return [row for row in ledger.rows if row['event'] == 'leg_intent' and row['session_id'] in sessions]


def empty_binding(state, attempt):
    from weather.market.lfc_campaign_state import StateRefused
    anchors = event_rows(state.ledger, 'autostart_no_intent_close', field='attempt_id', value=attempt)
    if not anchors:
        return None
    path = state.root / 'closed' / (attempt + '.json')
    row = state.read(path)
    proof = row.get('proof', {})
    if (len(anchors) != 1 or file_sha(path) != anchors[0]['file_sha256'] or
            row.get('attempt_id') != attempt or proof.get('authority') != 'automatic_no_intent' or
            row.get('proof_sha256') != digest(proof) or proof.get('ledger_head_sha256') != anchors[0]['previous_sha256'] or
            attempt_intents(state.ledger, attempt) or proof.get('scope') != 'attempt_only_no_placement'):
        raise StateRefused('no_intent_close_binding')
    return row


def close_empty(state, claim, now, *, reason='claim_no_intents'):
    from weather.market.lfc_campaign_state import StateRefused
    require_account(state.maker)
    attempt = claim['attempt_id']
    if attempt_intents(state.ledger, attempt):
        raise StateRefused('claim_has_order_intents')
    if empty_binding(state, attempt) is not None:
        return False
    for sid, session in attempt_sessions(state.ledger, attempt).items():
        if session['end'] is None:
            state.ledger.record('session_end', session_id=sid, reason=reason, cleanup_ok=False,
                                evidence_complete=False, inventory_proven=False, unknown_submit=False)
    path = state.root / 'closed' / (attempt + '.json')
    if path.exists():
        saved = state.read(path)
        if saved.get('proof', {}).get('authority') != 'automatic_no_intent':
            return False
        # Repair only the create-before-ledger-anchor crash gap. No POST was
        # possible, and the immutable claim/date and original files are kept.
        if saved['proof']['ledger_head_sha256'] != state.ledger.previous:
            raise StateRefused('partial_no_intent_close_stale')
    else:
        proof = {'authority': 'automatic_no_intent', 'scope': 'attempt_only_no_placement',
                 'ledger_head_sha256': state.ledger.previous, 'claim_sha256': digest(claim),
                 'money_accounting_complete': True, 'cleanup_proven': True, 'unknown_submit': False,
                 'research_evidence_complete': False, 'reason': reason}
        state.save('closed/' + attempt + '.json', {'attempt_id': attempt, 'state': 'MISSED',
            'proof': proof, 'proof_sha256': digest(proof), 'closed_at_utc': now.isoformat()})
    state.ledger.record('autostart_no_intent_close', attempt_id=attempt, local_date=claim['local_date'],
                        file_sha256=file_sha(path))
    from weather.market.lfc_campaign_closures import anchor as anchor_closure
    anchor_closure(state, attempt)
    for anchor in state.ledger.autostart_incidents:
        incident_path = state.root / 'incidents' / (anchor['attempt_id'] + '.json')
        incident = state.read(incident_path)
        if incident.get('source_attempt_id', incident['attempt_id']) != attempt:
            continue
        closure = 'owner-closures/' + incident['attempt_id'] + '.json'
        if not (state.root / closure).exists():
            state.save(closure, {'authority': 'automatic_no_intent', 'incident_sha256': file_sha(incident_path),
                'incident_id': incident['attempt_id'], **{key: incident.get(key) for key in
                    ('source_attempt_id', 'artifact', 'detection_sequence')}, 'no_intent_close_sha256': file_sha(path),
                'closed_at_utc': now.isoformat()})
    return True


def recover_empty(state, now):
    from weather.market.lfc_campaign_persistence import ClosureRetryPending, retry_failure
    from weather.market.lfc_ledger import LedgerUnavailable
    require_account(state.maker)
    state.verify(ignore_empty_result_errors=True)
    closed = []
    for anchor in list(state.ledger.autostart_claims):
        if anchor['attempt_id'] in state._closure_completed:
            continue
        claim = state.read(state.root / 'claims' / (anchor['local_date'] + '.json'))
        from weather.market.lfc_campaign_owner_close import complete_committed
        try:
            if complete_committed(state, claim['attempt_id'], now) is not None:
                continue
            if not attempt_intents(state.ledger, claim['attempt_id']) and close_empty(state, claim, now):
                closed.append(claim)
        except ClosureRetryPending:
            raise
        except (OSError, LedgerUnavailable) as exc:
            retry_failure(state, claim['attempt_id'], exc)
    return closed


def failure_result(ledger, claim, reason):
    intents = attempt_intents(ledger, claim['attempt_id'])
    ambiguous = any(ledger.legs[row['intent_key']]['order_id'] is None for row in intents)
    return {'exit_code': 1, 'session_id': None, 'private_evidence_directory': None,
            'evidence_complete': False, 'inventory_proven': False, 'unknown_submit': ambiguous,
            'local_money_proof': {'complete': False, 'unknown_submit': ambiguous},
            'outcome': {'halt_reason': reason, 'evidence_sha256': {}, 'evidence_complete': False,
                        'inventory_proven': False, 'unknown_submit': ambiguous, 'cleanup_ok': False},
            'public_coverage': {'configured': False, 'gap': 'postclaim_failure'}}
