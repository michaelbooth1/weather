"""Embargo-safe agent projection; detailed monetary evidence stays owner-only."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import uuid
import re

from weather.market.lfc_recording_io import write_new


CONTROL_SCHEMA = 'lfc_campaign_control_v0.1'
CONTROL_ROOT = Path(r'C:\t\pilot\status\control')
SAFE_STATES = {'IDLE', 'DEFERRED', 'MISSED', 'DISABLED', 'RUNNING', 'POSTCHECK_PENDING', 'COMPLETE', 'INCIDENT', 'REFUSED', 'EVIDENCE_GAP'}
SAFE_REASONS = {
    'stale_control_row', 'control_row_unknown',
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
    return evaluate_row(row)[1] == 1


def known_live_orders(state):
    """Acknowledged resting orders are normal; an unacked intent is not."""
    legs = state.ledger.unresolved_legs()
    return bool(legs) and all(leg['status'] == 'open' and leg['order_id'] for leg in legs)


def normal_live(row):
    return (isinstance(row, dict) and row.get('phase') == 'RUNNING' and
            row.get('orders_live') is True and row.get('orders_open_unproven') is True and
            row.get('incident') is False and row.get('attention_required') is False and
            row.get('postchecks_pending') is False and row.get('account_read') is not False)


def row_is_clean(row, *, now=None, max_age_seconds=900):
    """A clean observation requires fresh time, a known phase and exact flags."""
    return evaluate_row(row, now=now, max_age_seconds=max_age_seconds)[1] == 0


def flags_are_clean(row):
    """Missing/null is UNKNOWN, including inconsistent or legacy projections."""
    return (isinstance(row, dict) and all(row.get(key) is False for key in
            ('attention_required', 'incident', 'orders_open_unproven')) and row.get('account_read') is not False)


def flags_need_attention(row):
    """Producer calculation, before the attention_required field is written."""
    return (row.get('phase') in {'INCIDENT', 'POSTCHECK_PENDING', 'REFUSED', 'DEFERRED', 'MISSED', 'EVIDENCE_GAP'} or
            row.get('postchecks_pending') is True or row.get('account_read') is False or row.get('incident') is not False or
            row.get('orders_open_unproven') is not False and not (
                row.get('phase') == 'RUNNING' and row.get('orders_live') is True and
                row.get('orders_open_unproven') is True and row.get('postchecks_pending') is False))


def public_status(row, *, now=None):
    """Safe watch/toast projection: no monetary figures or private paths."""
    row = row if isinstance(row, dict) else {}
    identity = row.get('attempt_id')
    phase = row.get('phase') if isinstance(row.get('phase'), str) else None
    result = {'attempt_id': identity if isinstance(identity, str) and re.fullmatch('[0-9a-f]{32}', identity) else None,
              'phase': phase if phase in SAFE_STATES else None,
              **{key: row.get(key) if type(row.get(key)) is bool else None
                 for key in ('incident', 'orders_open_unproven')}}
    age, code, reason, stamp = evaluate_row(row, now=now)
    result['attention_required'] = code == 1
    result['at_utc'] = stamp
    if row.get('orders_live') is True:
        result['orders_live'] = True
        result['postchecks_pending'] = row.get('postchecks_pending') if type(row.get('postchecks_pending')) is bool else None
    if row.get('account_not_read') is True:
        result['account_not_read'] = True
    if isinstance(reason, str) and reason in SAFE_REASONS:
        result['reason'] = reason
    if isinstance(row.get('sleeve_loss_basis'), str) and row.get('sleeve_loss_basis') in {'gross', 'net_of_retained_gains'}:
        result['sleeve_loss_basis'] = row['sleeve_loss_basis']
    return result


def utc_now():
    return datetime.now(timezone.utc)


def evaluate_row(row, *, now=None, max_age_seconds=900):
    """Shared classification for every watch, status, projection and notice."""
    row = row if isinstance(row, dict) else {}
    if type(max_age_seconds) not in (int, float) or not 0 < max_age_seconds < float('inf'):
        raise ValueError('control_max_age')
    now = utc_now() if now is None else now
    age, stamp = None, None
    try:
        stamp = datetime.fromisoformat(row['at_utc'])
        if stamp.utcoffset() is None:
            raise ValueError('control_time_unknown')
        age, stamp = (now - stamp).total_seconds(), stamp.isoformat()
    except (KeyError, TypeError, ValueError):
        age, stamp = None, None
    reason = row.get('reason')
    phase = row.get('phase') if isinstance(row.get('phase'), str) else None
    code = 0 if flags_are_clean(row) else 2 if normal_live(row) else 1
    if phase not in SAFE_STATES or row.get('postchecks_pending') is True:
        code, reason = 1, 'control_row_unknown'
    if phase in {'INCIDENT', 'POSTCHECK_PENDING', 'REFUSED', 'DEFERRED', 'MISSED', 'EVIDENCE_GAP'}:
        code = 1
    if age is None or age < 0:
        code, reason = 1, 'control_row_unknown'
    elif age >= max_age_seconds:
        code, reason = 1, 'stale_control_row'
    return age, code, reason, stamp


def watch_status(row, *, now=None, max_age_seconds=900):
    """One watch contract: 0 clean idle, 2 proved normal live, 1 attention."""
    age, code, reason, stamp = evaluate_row(row, now=now, max_age_seconds=max_age_seconds)
    result = public_status(row, now=now)
    result['age_seconds'] = age
    result.pop('reason', None)
    if isinstance(reason, str) and reason in SAFE_REASONS:
        result['reason'] = reason
    result.update(clean=code == 0, attention_required=code == 1,
                  watch_state='clean_idle' if code == 0 else 'live_orders' if code == 2 else 'attention')
    return result, code


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
    parser.add_argument('--max-row-age-seconds', type=float, default=900)
    args = parser.parse_args(argv)
    result, code = watch_status(latest_control(args.root), max_age_seconds=args.max_row_age_seconds)
    print(json.dumps(result))
    return code


def control_record(root, attempt_id, *, phase, now, incident=False, postchecks_pending=False,
                   evidence_sha256=None, research_gaps=False, reason=None, policy_metadata=None,
                   orders_open_unproven=False, account_not_read=False, orders_live=False):
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
    if orders_live is True:
        if phase != 'RUNNING' or orders_open_unproven is not True:
            raise ValueError('control_live_context')
        row['orders_live'] = True
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
