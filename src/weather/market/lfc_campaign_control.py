"""Embargo-safe agent projection; detailed monetary evidence stays owner-only."""
from pathlib import Path
import uuid
import re

from weather.market.lfc_recording_io import write_new


CONTROL_SCHEMA = 'lfc_campaign_control_v0.1'
CONTROL_ROOT = Path(r'C:\t\pilot\status\control')
SAFE_STATES = {'IDLE', 'DEFERRED', 'MISSED', 'DISABLED', 'RUNNING', 'POSTCHECK_PENDING', 'COMPLETE', 'INCIDENT', 'REFUSED'}
SAFE_REASONS = {'idle', 'transport_deferred', 'window_missed', 'campaign_disabled', 'running', 'postcheck_pending',
                'completed', 'account_incident', 'policy_refused', 'release_refused', 'policy_changed',
                'owner_stop', 'market_local_horizon', 'admission_busy', 'hold_retained',
                'disk_free_below_floor', 'session_stalled'}


def control_record(root, attempt_id, *, phase, now, incident=False, postchecks_pending=False,
                   evidence_sha256=None, research_gaps=False, reason=None, policy_metadata=None,
                   orders_open_unproven=True):
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
