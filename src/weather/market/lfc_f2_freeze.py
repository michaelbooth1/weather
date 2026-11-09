"""Automatic research binding, never another trading arm or owner ceremony."""
from datetime import datetime, timedelta, time, date

from weather.market.lfc_recording_io import file_sha
from weather.market.mm_stage2_hold import digest
from weather.market.lfc_ledger_queries import event_rows


def economic_digest(policy):
    from weather.market.lfc_f2_breadth import economic_fields
    # A revision of identical parameters does not invent a second economic policy.
    keys = economic_fields(policy) - {'policy_revision'}
    # Explicit gross and retained pre-field gross have the same economics.
    # Preserve those historical hashes; net adds its distinct identity field.
    if policy.raw.get('sleeve_loss_basis', 'gross') == 'gross':
        keys -= {'sleeve_loss_basis'}
    return digest({key: policy.raw[key] for key in sorted(keys)})


def capture_window(policy):
    from weather.market.lfc_campaign_policy import ZONE
    begin = datetime.fromisoformat(policy.raw['freeze_deadline_toronto']) - timedelta(minutes=5)
    end = datetime.combine(date.fromisoformat(policy.raw['confirmation_dates'][0]), time(8, 55), ZONE)
    return begin, end


def verify(state):
    events = event_rows(state.ledger, 'autostart_freeze')
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
                row['policy_sha256'] != policy.sha256 or
                row['ledger_sha256'] != event.get('receipt_ledger_sha256', event['previous_sha256']) or
                row['ledger_sha256'] not in {state.ledger.row_sha256(i) for i in range(event['sequence'])} or
                row['on_time'] != (capture_window(policy)[0] <= captured <= capture_window(policy)[1])):
            raise ValueError('freeze_binding')
        return row
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        from weather.market.lfc_campaign_state import StateRefused
        from weather.market.lfc_campaign_owner_close import binding
        if binding(state, 'campaign-freeze') is not None:
            return None  # Owner accepted evidence loss; never a confirmation PASS.
        state.evidence_fault('campaign-freeze', artifact='policies/freeze.json')
        raise StateRefused('freeze_evidence_fault') from None


def capture(state, policy, now):
    """First healthy tick in the approved overnight window seals the version.

    Keep the actual capture time. A later observation is explicitly late;
    economic edits remain supported as successor learning.
    """
    if not policy.f2 or verify(state) is not None:
        return
    path = state.root / 'policies' / 'freeze.json'
    if path.exists():
        # Complete only a valid original transaction, during the same capture
        # window. Never rewrite its bytes or backdate the recovery anchor.
        from weather.market.lfc_campaign_policy import parse_policy
        try:
            row = state.read(path)
            original = parse_policy(row['policy'])
            captured = datetime.fromisoformat(row['captured_at_utc'])
            begin, end = capture_window(original)
            valid = (begin <= captured <= now <= end and row['on_time'] is True and
                row['policy_sha256'] == original.sha256 and
                row['economic_sha256'] == economic_digest(original) == economic_digest(policy) and
                row['ledger_sha256'] in {state.ledger.row_sha256(i) for i in range(len(state.ledger.rows))})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            valid = False
        if valid:
            state.ledger.record('autostart_freeze', attempt_id='campaign-freeze', file_sha256=file_sha(path),
                receipt_ledger_sha256=row['ledger_sha256'], recovered_partial=True)
        return
    deadline = datetime.fromisoformat(policy.raw['freeze_deadline_toronto'])
    if now < deadline - timedelta(minutes=5):
        return
    sha = state.save('policies/freeze.json', {'policy': policy.raw, 'policy_sha256': policy.sha256,
        'economic_sha256': economic_digest(policy), 'captured_at_utc': now.isoformat(),
        'on_time': now <= capture_window(policy)[1], 'ledger_sha256': state.ledger.previous})
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
