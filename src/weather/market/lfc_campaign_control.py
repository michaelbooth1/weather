"""Embargo-safe agent projection; detailed monetary evidence stays owner-only."""
from pathlib import Path
import hashlib
import uuid
import re

from weather.market.lfc_recording_io import write_new


CONTROL_SCHEMA = 'lfc_campaign_control_v0.1'
CONTROL_ROOT = Path(r'C:\t\pilot\status\control')
SAFE_STATES = {'IDLE', 'DEFERRED', 'MISSED', 'DISABLED', 'RUNNING', 'POSTCHECK_PENDING', 'COMPLETE', 'INCIDENT', 'REFUSED', 'EVIDENCE_GAP'}
SAFE_REASONS = {'idle', 'transport_deferred', 'window_missed', 'campaign_disabled', 'running', 'postcheck_pending',
                'completed', 'account_incident', 'policy_refused', 'release_refused', 'policy_changed',
                'owner_stop', 'market_local_horizon', 'admission_busy', 'hold_retained',
                'disk_free_below_floor', 'session_stalled', 'claim_no_intents', 'freeze_missing', 'no_qualifying_band'}


def active_incidents(state):
    """A damaged receipt cannot suppress the public incident projection."""
    if state is None:
        return []
    try:
        return state.incidents()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        anchors = getattr(state.ledger, 'autostart_incidents', ())
        attempt = anchors[-1]['attempt_id'] if anchors else stable_id('continuity', 'INCIDENT', None, 'unbound')
        return [{'attempt_id': attempt}]


def stable_id(state_id, phase, reason, local_date, attempt=None, *, incident=False):
    if isinstance(attempt, str) and re.fullmatch('[0-9a-f]{32}', attempt):
        return attempt
    identity = (state_id, attempt) if incident else (state_id, phase, reason, local_date, attempt)
    source = '|'.join(map(str, identity))
    return hashlib.sha256(source.encode()).hexdigest()[:32]


def orders_unproven(state, runtime=None):
    if state is None:
        return True  # A failed account-state binding cannot prove absence.
    ledger = state.ledger
    if ledger.unresolved_legs():
        return True
    recent = getattr(runtime, '_orders_open_unproven', None)
    if recent is not None:
        return recent
    for claim in ledger.autostart_claims:
        if (any(s['legs'] and s['start'].get('autostart_attempt_id') == claim['attempt_id']
                for s in ledger.sessions.values()) and
                not (state.root / 'closed' / (claim['attempt_id'] + '.json')).exists()):
            return True
    return False


def control_record(root, attempt_id, *, phase, now, incident=False, postchecks_pending=False,
                   evidence_sha256=None, research_gaps=False, reason=None, policy_metadata=None,
                   orders_open_unproven=False):
    if phase not in SAFE_STATES:
        raise ValueError('control_phase')
    if not isinstance(attempt_id, str) or not re.fullmatch(r'[0-9a-f]{32}', attempt_id):
        raise ValueError('control_opaque_id')
    if reason is not None and reason not in SAFE_REASONS:
        raise ValueError('control_reason')
    # Deliberate allowlist: no selection, token, event, price, fill, wallet,
    # credential path or raw exception message is allowed in the agent view.
    row = {'schema_version': CONTROL_SCHEMA, 'attempt_id': attempt_id, 'phase': phase,
           'at_utc': now.isoformat(), 'incident': incident is True,
           'orders_open_unproven': orders_open_unproven is not False,
           'postchecks_pending': postchecks_pending is True, 'research_gaps': research_gaps is True,
           'evidence_sha256': evidence_sha256}
    row['reason'] = reason
    metadata = {} if policy_metadata is None else policy_metadata
    row.update({key: metadata.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')})
    name = now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + attempt_id + '-' + phase + '-' + uuid.uuid4().hex + '.json'
    write_new(Path(root) / name, row)
    return row
