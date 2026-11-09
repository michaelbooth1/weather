"""One explicit owner close for an operational fault with proved money.

Missing private evidence is acknowledged, never reconstructed as a PASS. An
unacknowledged intent cannot use this route. Every receipt names one occurrence;
a later loss or changed artifact needs another owner decision (N1).
"""
from pathlib import Path
import os
import re
import sys

from weather.market.lfc_campaign_recovery import attempt_intents, attempt_sessions
from weather.market.lfc_recording_io import file_sha, write_new
from weather.market.mm_stage2_hold import digest
from weather.market.lfc_ledger_queries import event_rows
from weather.operations.live_path_security import validate_contained_regular_file


def legs_binding(ledger, attempt):
    return {row['intent_key']: ledger.legs[row['intent_key']] for row in attempt_intents(ledger, attempt)}


def artifact_path(state, name):
    from weather.market.lfc_campaign_state import StateRefused
    parts = Path(name).parts
    if len(parts) < 2 or parts[0] not in ('state', 'pilot') or '..' in parts:
        raise StateRefused('owner_close_artifact_path')
    root = state.root if parts[0] == 'state' else state.ledger.path.parent
    path = root.joinpath(*parts[1:])
    if not path.exists():
        return None
    return validate_contained_regular_file(root, path)


def manifest(state, attempt):
    names = {'state/results/' + attempt + '.json'}
    names.add('state/emergency/' + attempt + '.json')
    if attempt == 'campaign-freeze':
        names.add('state/policies/freeze.json')
    directories = set()
    go_directories = set()
    for session in attempt_sessions(state.ledger, attempt).values():
        relative = Path(str(session['start'].get('directory', '')))
        if relative.parts and not relative.is_absolute() and '..' not in relative.parts:
            directories.add(relative)
            if relative.name in {'band-' + str(i) for i in range(1, 13)}:
                directories.add(relative.parent)
                if session['start'].get('go_account_sha256') is not None:
                    go_directories.add(relative.parent)
    for directory in directories:
        for name in ('journal.jsonl', 'prediction.json', 'session_end.json', 'attempt.json', 'selection.json', 'f2_manifest.json'):
            names.add('pilot/' + (directory / name).as_posix())
        if directory in go_directories:
            names.add('pilot/' + (directory / 'go_account.json').as_posix())
        for number in range(1, 11):
            for suffix in ('intent', 'ack'):
                names.add('pilot/' + (directory / f'submit-{number}.{suffix}.json').as_posix())
    return {name: file_sha(path) if (path := artifact_path(state, name)) is not None else None for name in sorted(names)}


def binding(state, attempt, *, incident=None):
    from weather.market.lfc_campaign_state import StateRefused
    anchors = [row for row in event_rows(state.ledger, 'autostart_owner_close', field='source_attempt_id', value=attempt) if
               (incident is None or row.get('incident_id') == incident)]
    if not anchors:
        return None
    anchor = anchors[-1]
    relative = Path(anchor['file'])
    if len(relative.parts) != 2 or relative.parts[0] != 'owner-closures' or relative.name != anchor['incident_id'] + '.json':
        raise StateRefused('owner_operational_close_path')
    path = state.root / relative
    row = state.read(path)
    proof = row.get('proof', {})
    legs = legs_binding(state.ledger, attempt)
    if (file_sha(path) != anchor['file_sha256'] or row.get('authority') != 'owner_operational_close' or
            row.get('source_attempt_id') != attempt or row.get('incident_id') != anchor['incident_id'] or
            row.get('ledger_head_sha256') != anchor.get('receipt_ledger_sha256', anchor['previous_sha256']) or
            row.get('ledger_head_sha256') not in {state.ledger.row_sha256(i) for i in range(anchor['sequence'])} or
            proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
            proof.get('unknown_submit') is not False or proof.get('read_sha256') != digest(row.get('account_read')) or
            row.get('terminal_legs_sha256') != digest(legs) or
            any(leg['status'] != 'terminal' or leg['order_id'] is None for leg in legs.values()) or
            row.get('research_evidence_complete') is not False):
        raise StateRefused('owner_operational_close_binding')
    for name, previous in row.get('artifact_manifest', {}).items():
        current = artifact_path(state, name)
        current_sha = file_sha(current) if current is not None else None
        restored = [r for r in state.ledger.rows if r['event'] == 'autostart_owner_artifact_restored' and
                    r.get('closure_sha256') == anchor['file_sha256'] and r.get('artifact') == name]
        if previous is None and not restored:
            if current_sha is not None:
                state.ledger.record('autostart_owner_artifact_restored', closure_sha256=anchor['file_sha256'],
                                    artifact=name, file_sha256=current_sha)
            continue
        expected = previous if previous is not None else restored[0]['file_sha256']
        if current_sha != expected:
            state.evidence_fault(attempt, artifact='owner-accepted/' + name)
            raise StateRefused('owner_accepted_artifact_recurred')
    return row


def complete_committed(state, attempt, now, *, incident=None):
    """Finish only a retained, ledger-committed decision; never decide again.

    Current artifacts and terminal legs still pass binding(), including N1.
    The missing receipt points to the original anchor, not a fresh money read.
    Existing receipts and the consumed claim/date are never replaced.
    """
    from weather.market.lfc_campaign_guard import require_account
    from weather.market.lfc_campaign_state import StateRefused
    require_account(state.maker)
    closure = binding(state, attempt, incident=incident)
    if closure is None:
        return None
    anchors = [row for row in state.ledger.rows if row['event'] == 'autostart_owner_close' and
               row.get('source_attempt_id') == attempt and row.get('incident_id') == closure['incident_id']]
    if len(anchors) != 1:
        raise StateRefused('owner_committed_anchor_binding')
    anchor = anchors[0]
    if not any(row['attempt_id'] == attempt for row in state.ledger.autostart_claims):
        return False  # An account/freeze incident has no session claim to close.
    target = state.root / 'closed' / (attempt + '.json')
    if target.exists():
        saved = state.closed_binding(target)
        proof = saved.get('proof', {})
        if (saved.get('attempt_id') != attempt or proof.get('unknown_submit') is not False or
                proof.get('cleanup_proven') is not True or proof.get('money_accounting_complete') is not True or
                proof.get('ledger_head_sha256') not in {state.ledger.row_sha256(i) for i in range(len(state.ledger.rows))}):
            raise StateRefused('owner_committed_close_binding')
        return False
    proof = anchor['proof']
    if (anchor.get('proof_sha256') != digest(proof) or proof.get('unknown_submit') is not False or
            proof.get('cleanup_proven') is not True or proof.get('money_accounting_complete') is not True):
        raise StateRefused('owner_committed_anchor_binding')
    closed_proof = {**proof, 'authority': 'owner_operational_close', 'research_evidence_complete': False,
                    'ledger_head_sha256': state.ledger.row_sha256(anchor['sequence']),
                    'owner_closure_sha256': anchor['file_sha256']}
    state.save('closed/' + attempt + '.json', {'attempt_id': attempt, 'proof': closed_proof,
        'proof_sha256': digest(closed_proof), 'closed_at_utc': closure['closed_at_utc']})
    return True


def owner_close(runtime, incident):
    from weather.market.lfc_campaign_state import StateRefused
    if not sys.stdin.isatty():
        raise StateRefused('owner_terminal_required')
    if not re.fullmatch('[0-9a-f]{32}', incident):
        raise StateRefused('incident_missing')
    state = runtime.state
    path = state.root / 'incidents' / (incident + '.json')
    occurrence, sha = state.read(path), file_sha(path)
    if any(row['event'] == 'autostart_owner_close' and row.get('incident_id') == incident for row in state.ledger.rows):
        source = occurrence.get('source_attempt_id', occurrence['attempt_id'])
        complete_committed(state, source, runtime.clock.now(), incident=incident)
        return 0
    print('Close this occurrence with gaps retained; release only its proved-dead workload. Type: close ' + sha[:12])
    if input().strip() != 'close ' + sha[:12]:
        raise StateRefused('owner_confirmation_refused')
    runtime.owner_fault_review = True
    try:
        if state.ledger.unacknowledged_intents():
            raise StateRefused('owner_close_ambiguous_placement')
        from weather.market.lfc_campaign_workload import owner_release_hold_only, owner_release_workload_after_reboot
        marker = getattr(runtime, 'workload_path', Path(os.environ.get('ProgramData', r'C:\ProgramData')) /
                         'WeatherProject' / 'heavy_workload_v1.poison')
        if marker.exists():
            marker_sha = file_sha(marker)
            owner_release_workload_after_reboot(path=marker, expected_sha=marker_sha,
                state_id=state.verify(owner_fault_review=True)['state_id'], maker=state.maker,
                owner_terminal=True, confirmation='clear workload ' + marker_sha[:12], hold_path=runtime.hold_path)
        elif runtime.hold_path.exists():
            hold_sha = file_sha(runtime.hold_path)
            owner_release_hold_only(path=runtime.hold_path, expected_sha=hold_sha, owner_terminal=True,
                                    confirmation='clear hold ' + hold_sha[:12])
        with runtime.admission():
            ledger = runtime.reload_ledger()
            if file_sha(path) != sha or ledger.unacknowledged_intents():
                raise StateRefused('owner_close_ambiguous_placement')
            source = occurrence.get('source_attempt_id', occurrence['attempt_id'])
            read = runtime.read_account()
            # Validate the full read before using any acknowledged order row.
            runtime.validate_account_read(ledger, read)
            from datetime import datetime, timedelta
            for leg in list(ledger.unresolved_legs()):
                observed = read.get('terminal_orders', {}).get(leg['order_id'])
                if observed is None:
                    raise StateRefused('owner_close_terminal_pending')
                begin, end = (datetime.fromisoformat(observed[key]) for key in ('started_at_utc', 'ended_at_utc'))
                if (begin.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0) or
                        not datetime.fromisoformat(read['started_at_utc']) <= begin <= end <= datetime.fromisoformat(read['ended_at_utc']) or
                        not 0 <= (runtime.clock.now() - begin).total_seconds() <= 120):
                    raise StateRefused('owner_close_terminal_binding')
                ledger.terminal(leg['order_id'], observed['row'], source='owner_operational_close')
            if ledger.unresolved_legs() or read.get('open_orders') != []:
                raise StateRefused('owner_close_terminal_pending')
            for sid, session in list(ledger.sessions.items()):
                if session['end'] is None and session['start'].get('autostart_attempt_id'):
                    ledger.record('session_end', session_id=sid, reason='owner_operational_close', cleanup_ok=False,
                        evidence_complete=False, inventory_proven=False, unknown_submit=False)
            proof = runtime.core_proof(ledger, read)
            if (proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
                    proof.get('unknown_submit') is not False or proof.get('money_contradiction') is True):
                raise StateRefused('owner_money_repair_required')
            relative = 'owner-closures/' + incident + '.json'
            fields = {'authority': 'owner_operational_close', 'incident_id': incident, 'incident_sha256': sha,
                **{key: occurrence.get(key) for key in ('source_attempt_id', 'artifact', 'detection_sequence')},
                'ledger_head_sha256': ledger.previous, 'proof': proof, 'account_read': read,
                'terminal_legs_sha256': digest(legs_binding(ledger, source)), 'artifact_manifest': manifest(state, source),
                'research_evidence_complete': False, 'closed_at_utc': runtime.clock.now().isoformat()}
            fields['source_attempt_id'] = source
            target = state.root / relative
            recovery = {}
            if target.exists():
                # A retry is still owner-confirmed and freshly proves money.
                # Complete precisely the retained decision; never replace it
                # or let it accept a later artifact loss/incident occurrence.
                partial = state.read(target)
                previous = partial.get('ledger_head_sha256')
                retained = partial.get('proof', {})
                keys = ('authority', 'incident_id', 'incident_sha256', 'source_attempt_id',
                        'artifact', 'detection_sequence', 'terminal_legs_sha256', 'artifact_manifest',
                        'research_evidence_complete')
                if (any(partial.get(key) != fields.get(key) for key in keys) or
                        previous not in {ledger.row_sha256(i) for i in range(len(ledger.rows))} or
                        retained.get('money_accounting_complete') is not True or
                        retained.get('cleanup_proven') is not True or retained.get('unknown_submit') is not False or
                        retained.get('read_sha256') != digest(partial.get('account_read'))):
                    raise StateRefused('owner_close_partial_binding')
                closure_sha = file_sha(target)
                recovery = {'receipt_ledger_sha256': previous, 'recovered_partial': True}
            else:
                closure_sha = state.save(relative, fields)
            ledger.record('autostart_owner_close', attempt_id=incident, incident_id=incident,
                source_attempt_id=source, file=relative, file_sha256=closure_sha, proof=proof, proof_sha256=digest(proof),
                **recovery)
            complete_committed(state, source, runtime.clock.now(), incident=incident)
        return 0
    finally:
        runtime.owner_fault_review = False
