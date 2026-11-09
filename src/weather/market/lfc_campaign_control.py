"""Embargo-safe agent projection; detailed monetary evidence stays owner-only."""
from pathlib import Path
import hashlib
import uuid
import re

from weather.market.lfc_recording_io import write_new


CONTROL_SCHEMA = 'lfc_campaign_control_v0.1'
CONTROL_ROOT = Path(r'C:\t\pilot\status\control')
SAFE_STATES = {'IDLE', 'DEFERRED', 'MISSED', 'DISABLED', 'RUNNING', 'POSTCHECK_PENDING', 'COMPLETE', 'INCIDENT', 'REFUSED', 'EVIDENCE_GAP'}
SAFE_REASONS = {
    'wrapper_launch_missing_or_invalid', 'wrapper_policy_changed', 'wrapper_cleanup_budget_insufficient','idle', 'transport_deferred', 'window_missed', 'campaign_disabled', 'running', 'postcheck_pending',
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


def needs_attention(row):
    """Compatibility consumer; use the single exported clean-row contract."""
    return not row_is_clean(row)


def row_is_clean(row):
    """Missing/null is UNKNOWN, including inconsistent or legacy projections."""
    return (isinstance(row, dict) and all(row.get(key) is False for key in
            ('attention_required', 'incident', 'orders_open_unproven')) and row.get('account_read') is not False)


def flags_need_attention(row):
    """Producer calculation, before the attention_required field is written."""
    return (row.get('phase') in {'INCIDENT', 'POSTCHECK_PENDING', 'REFUSED', 'DEFERRED', 'MISSED', 'EVIDENCE_GAP'} or
            row.get('account_read') is False or row.get('incident') is not False or
            row.get('orders_open_unproven') is not False)


def public_status(row):
    """Safe watch/toast projection: no monetary figures or private paths."""
    result = {key: row.get(key) for key in ('attempt_id', 'phase', 'incident', 'orders_open_unproven')}
    result['attention_required'] = not row_is_clean(row)
    if row.get('account_not_read') is True:
        result['account_not_read'] = True
    if row.get('reason') in SAFE_REASONS:
        result['reason'] = row['reason']
    if row.get('sleeve_loss_basis') in {'gross', 'net_of_retained_gains'}:
        result['sleeve_loss_basis'] = row['sleeve_loss_basis']
    return result


def latest_control(root):
    from weather.market.lfc_recording_io import read_bytes, strict_json
    from weather.operations.live_path_security import validate_regular_nonreparse_file
    try:
        files = sorted(p for p in Path(root).iterdir() if p.suffix in {'.json', '.jsonl'})
        if not files:
            return {}
        row = strict_json(read_bytes(validate_regular_nonreparse_file(files[-1].absolute()), 4*1024**2))
        return row if isinstance(row, dict) else {}
    except (OSError, ValueError, RuntimeError):
        return {}


def main(argv=None):
    """Read only the agent-readable control folder, with no release/account access."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--root', type=Path, default=CONTROL_ROOT)
    row = latest_control(parser.parse_args(argv).root)
    print(json.dumps({**public_status(row), 'clean': row_is_clean(row)}))
    return 0 if row_is_clean(row) else 1


def control_record(root, attempt_id, *, phase, now, incident=False, postchecks_pending=False,
                   evidence_sha256=None, research_gaps=False, reason=None, policy_metadata=None,
                   orders_open_unproven=False, account_not_read=False):
    if phase not in SAFE_STATES:
        raise ValueError('control_phase')
    if not isinstance(attempt_id, str) or not re.fullmatch(r'[0-9a-f]{32}', attempt_id):
        raise ValueError('control_opaque_id')
    if reason is not None and reason not in SAFE_REASONS:
        raise ValueError('control_reason')
    if account_not_read is True and (phase != 'DEFERRED' or orders_open_unproven is not None or incident is not None):
        raise ValueError('control_account_read_context')
    if any(value is not None and type(value) is not bool for value in (incident, orders_open_unproven)):
        raise ValueError('control_boolean_flags')
    # Deliberate allowlist: no selection, token, event, price, fill, wallet,
    # credential path or raw exception message is allowed in the agent view.
    row = {'schema_version': CONTROL_SCHEMA, 'attempt_id': attempt_id, 'phase': phase,
           'at_utc': now.isoformat(), 'incident': incident,
           'orders_open_unproven': orders_open_unproven,
           'postchecks_pending': postchecks_pending is True, 'research_gaps': research_gaps is True,
           'evidence_sha256': evidence_sha256}
    if account_not_read is True:
        row['account_not_read'] = True
        row.update(account_read=False, orders_open_unproven=None, incident=None)
    row['attention_required'] = flags_need_attention(row)
    row['reason'] = reason
    metadata = {} if policy_metadata is None else policy_metadata
    row.update({key: metadata.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')})
    row['sleeve_loss_basis'] = metadata.get('sleeve_loss_basis')
    name = now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + attempt_id + '-' + phase + '-' + uuid.uuid4().hex + '.json'
    write_new(Path(root) / name, row)
    return row


if __name__ == '__main__':
    raise SystemExit(main())
