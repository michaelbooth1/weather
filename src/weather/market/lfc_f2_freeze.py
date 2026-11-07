"""Automatic research binding, never another trading arm or owner ceremony."""
from datetime import datetime, timedelta

from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import digest


def economic_digest(policy):
    from weather.market.lfc_f2_policy import ECONOMIC_FIELDS
    # A revision of identical parameters does not invent a second economic policy.
    return digest({key: policy.raw[key] for key in sorted(ECONOMIC_FIELDS - {'policy_revision'})})


def verify(state):
    events = [row for row in state.ledger.rows if row['event'] == 'autostart_freeze']
    if not events:
        return None
    try:
        if len(events) != 1:
            raise ValueError('duplicate_freeze')
        event = events[0]
        path = state.root / 'policies' / 'freeze.json'
        row = state.read(path)
        from weather.market.lfc_campaign_policy import parse_policy
        policy = parse_policy(row['policy'])
        captured = datetime.fromisoformat(row['captured_at_utc'])
        deadline = datetime.fromisoformat(policy.raw['freeze_deadline_toronto'])
        if (file_sha(path) != event['file_sha256'] or row['economic_sha256'] != economic_digest(policy) or
                row['policy_sha256'] != policy.sha256 or row['ledger_sha256'] != event['previous_sha256'] or
                row['on_time'] != (deadline - timedelta(minutes=5) <= captured <= deadline)):
            raise ValueError('freeze_binding')
        return row
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        from weather.market.lfc_campaign_state import StateRefused
        state.evidence_fault('campaign-freeze', artifact='policies/freeze.json')
        raise StateRefused('freeze_evidence_fault') from None


def capture(state, policy, now):
    """First scheduled tick seals the configuration; late capture is labelled late.

    The final five-minute trigger before the deadline seals the version early.
    A missed trigger is explicitly late; no receipt is ever backdated. Economic edits remain supported as successor learning.
    """
    if not policy.f2 or verify(state) is not None:
        return
    if (state.root / 'policies' / 'freeze.json').exists():
        # A crash between create and ledger anchor cannot be adopted as a
        # timely freeze. Preserve the partial receipt and label later trading
        # as learning instead of blocking useful funded sessions.
        return
    deadline = datetime.fromisoformat(policy.raw['freeze_deadline_toronto'])
    if now < deadline - timedelta(minutes=5):
        return
    sha = state.save('policies/freeze.json', {'policy': policy.raw, 'policy_sha256': policy.sha256,
        'economic_sha256': economic_digest(policy), 'captured_at_utc': now.isoformat(),
        'on_time': now <= deadline, 'ledger_sha256': state.ledger.previous})
    state.ledger.record('autostart_freeze', attempt_id='campaign-freeze', file_sha256=sha)


def labels(state, policy, local_date):
    result = policy.labels(local_date)
    if not policy.f2 or result['evidence_lane'] != 'confirmation':
        return result
    frozen = verify(state)
    eligible = frozen is not None and frozen['on_time'] and frozen['economic_sha256'] == economic_digest(policy)
    if eligible:
        # Once an actual successor session has been claimed, returning to old
        # parameters cannot pool its later dates into the abandoned claim.
        for claim in state.claims():
            if claim['local_date'] >= policy.raw['confirmation_dates'][0] and claim.get('evidence_lane') != 'confirmation':
                eligible = False
                break
    if not eligible:
        result['evidence_lane'] = 'successor_learning'
    return result
