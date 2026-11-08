"""Immutable fault occurrences; an owner closure never clears a recurrence."""
from weather.market.lfc_campaign_guard import require_account
from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import digest


class EvidenceArtifactError(ValueError):
    def __init__(self, artifact):
        super().__init__('private_original_evidence_fault')
        self.artifact = artifact


def occurrence_closed(state, path, row, sha):
    from weather.market.lfc_campaign_state import StateRefused
    if not any(event['attempt_id'] == row['attempt_id'] and event['file_sha256'] == sha
               for event in state.ledger.autostart_incidents):
        raise StateRefused('incident_continuity')
    closure = state.root / 'owner-closures' / path.name
    if not closure.exists():
        return False
    closed = state.read(closure)
    if closed.get('authority') == 'owner_operational_close':
        source = row.get('source_attempt_id', row['attempt_id'])
        fields = ('artifact', 'detection_sequence')
        if (closed.get('incident_sha256') != sha or closed.get('incident_id') != row['attempt_id'] or
                closed.get('source_attempt_id') != source or any(closed.get(key) != row.get(key) for key in fields) or
                not any(r['event'] == 'autostart_owner_close' and r.get('incident_id') == row['attempt_id'] and
                        r.get('file_sha256') == file_sha(closure) for r in state.ledger.rows)):
            raise StateRefused('incident_closure_invalid')
        return True
    if closed.get('authority') == 'automatic_no_intent':
        from weather.market.lfc_campaign_recovery import empty_binding
        source = row.get('source_attempt_id', row['attempt_id'])
        binding = empty_binding(state, source)
        if (binding is None or closed.get('incident_sha256') != sha or
                closed.get('no_intent_close_sha256') != file_sha(state.root / 'closed' / (source + '.json'))):
            raise StateRefused('incident_closure_invalid')
        return True
    fields = ('incident_id', 'source_attempt_id', 'artifact', 'detection_sequence')
    identity = {**row, 'incident_id': row['attempt_id']}
    if (closed.get('incident_sha256') != sha or closed.get('authority') != 'owner_recovery' or
            ('detection_sequence' in row and any(closed.get(k) != identity.get(k) for k in fields))):
        raise StateRefused('incident_closure_invalid')
    return True


def latch_occurrence(state, attempt, reason, artifact, now, *, initial_id=None):
    """Deduplicate only an open occurrence, under the account-wide writer lease.

    The ledger count survives process restarts. Hashes bind the attempt, artifact
    and sequence; original incidents/closures are never replaced or reopened.
    A partial create refuses rather than adopting an unanchored incident.
    """
    from weather.market.lfc_campaign_policy import ZONE
    from weather.market.lfc_campaign_state import StateRefused
    require_account(state.maker)
    for event in state.ledger.autostart_incidents:
        path = state.root / 'incidents' / (event['attempt_id'] + '.json')
        sha = file_sha(path)
        if sha != event['file_sha256']:
            raise StateRefused('incident_continuity')
        row = state.read(path)
        old_artifact = row.get('artifact', 'private-evidence' if row['reason'] == 'private_evidence_fault' else 'attempt')
        if (row.get('source_attempt_id', row['attempt_id']) == attempt and row['reason'] == reason and
                old_artifact == artifact and not occurrence_closed(state, path, row, sha)):
            return row['attempt_id']
    identity = {'source_attempt_id': attempt, 'artifact': artifact, 'reason': reason,
                'detection_sequence': len(state.ledger.autostart_incidents) + 1,
                'detected_at_ledger_sha256': state.ledger.previous}
    used = {event['attempt_id'] for event in state.ledger.autostart_incidents}
    incident = initial_id if initial_id is not None and initial_id not in used else digest(identity)[:32]
    relative = 'incidents/' + incident + '.json'
    if (state.root / relative).exists():
        raise StateRefused('incident_occurrence_conflict')
    local_date = now.astimezone(ZONE).date().isoformat()
    sha = state.save(relative, {**identity, 'attempt_id': incident, 'at_utc': now.isoformat(), 'local_date': local_date})
    state.ledger.record('autostart_incident', attempt_id=incident, file_sha256=sha, local_date=local_date)
    return incident
