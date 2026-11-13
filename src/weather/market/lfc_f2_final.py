"""Owner-run final cash snapshot; no venue reads, orders or price valuation.

`lfc_campaign_cli final-look` uses the retained account/release and writes this
create-only report. Unknown paid-income/fee attribution prevents a qualified
cash verdict. A successful command means the report was written, not PASS.
"""
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_accounting import quantity
from weather.market.lfc_f2_economics import final_cash_assessment
from weather.market.lfc_recording_io import read_recovered, response_bytes, write_new, file_sha
from weather.market.lfc_settlement_record import envelope, validate_settlement
from weather.market.mm_stage2_hold import digest
from weather.operations.live_path_security import validate_contained_regular_file


def confirmation_sessions(ledger, frozen):
    """Classify by retained claims and frozen economics, never revision number."""
    if not frozen or frozen.get('on_time') is not True or ledger.enrollment is None:
        return set()
    from weather.market.lfc_campaign_policy import parse_policy, ZONE
    from weather.market.lfc_f2_freeze import economic_digest
    from weather.market.lfc_recording_io import read_bytes, strict_json
    root = Path(ledger.enrollment['state_root'])
    claims = {}
    for anchor in ledger.autostart_claims:
        from weather.market.lfc_campaign_state import claim_file
        path = validate_contained_regular_file(root, claim_file(root, anchor['local_date'], anchor['attempt_id']))
        claim = strict_json(read_bytes(path, 2 * 1024 * 1024))
        policy_path = validate_contained_regular_file(root, root / 'policies' / (anchor['attempt_id'] + '.json'))
        retained = strict_json(read_bytes(policy_path, 2 * 1024 * 1024))
        policy = parse_policy(retained['policy'])
        if (file_sha(path) != anchor['file_sha256'] or claim['attempt_id'] != anchor['attempt_id'] or
                claim['ledger_sha256'] != anchor['previous_sha256'] or
                file_sha(policy_path) != claim['policy_snapshot_sha256'] or
                policy.sha256 != claim['policy_sha256'] or retained['sha256'] != policy.sha256):
            raise ValueError('final_confirmation_claim_binding')
        if (claim.get('evidence_lane') == 'confirmation' and
                economic_digest(policy) == frozen['economic_sha256']):
            claims[anchor['attempt_id']] = (anchor, claim)
    result = set()
    for sid, session in ledger.sessions.items():
        start = session['start']
        attempt = start.get('autostart_attempt_id')
        # Earlier campaign fixtures/journals bind through the active claim and
        # date; current runtime also writes the explicit attempt identifier.
        if attempt is None:
            prior = [a for a in ledger.autostart_claims if a['sequence'] < start['sequence']]
            attempt = prior[-1]['attempt_id'] if prior else None
        if attempt not in claims:
            continue
        anchor, claim = claims[attempt]
        day = datetime.fromisoformat(start['recorded_at_utc']).astimezone(ZONE).date().isoformat()
        if (anchor['sequence'] < start['sequence'] and day == claim['local_date'] and
                all(start.get(key) == claim.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane'))):
            result.add(sid)
    return result


def snapshot(ledger, policy, *, root, now, frozen=None):
    cutoff = datetime.fromisoformat(policy.raw['evidence_cutoff_toronto'])
    if now < cutoff:
        raise ValueError('final_cutoff_not_open')
    book = CapitalBook(ledger)
    winners, unknown, zeros, hashes, by_lot = [], [], [], {}, {}
    for allocation in book.allocations:
        activity = book.activities[allocation['activity_id']]
        if activity['timestamp'] <= cutoff.timestamp():
            by_lot.setdefault(allocation['intent_key'], []).append(allocation)
    for key, lot in book.lots.items():
        left = lot['quantity'] - sum((quantity(a['quantity']) for a in by_lot.get(key, [])
            if book.activities[a['activity_id']]['cash_native'] is not None and
            not book.activities[a['activity_id']].get('principal_unproved')), Decimal(0))
        if not left:
            continue
        path = Path(root) / 'settlement' / (lot['condition_id'] + '.json')
        payout = None
        if path.exists():
            record, accepted = read_recovered(path, lambda p: validate_settlement(
                validate_contained_regular_file(Path(root), p), lot['condition_id']))
            hashes[str(Path(accepted).relative_to(root))] = file_sha(accepted)
            if record['terminal'] and lot['token_id'] in record['token_ids']:
                payouts = envelope(response_bytes(record['resolution']))['data'][0]['payouts']
                payout = payouts[record['token_ids'].index(lot['token_id'])]
        row = {'intent_key': key, 'session_id': lot['session_id'], 'token_id': lot['token_id'],
               'quantity_at_cutoff': str(left), 'counted_as_cash_native': 0}
        if payout is None:
            unknown.append(row)
        elif payout == 0:
            zeros.append(row)
        else:
            winners.append({**row, 'unredeemed_payout_native': int(left * payout), 'state': 'UNREDEEMED_AT_CUTOFF'})
    confirmation = confirmation_sessions(ledger, frozen)
    purchases = {lane: sum(lot['basis'] for lot in book.lots.values() if (lot['session_id'] in confirmation) ==
                          (lane == 'confirmation')) for lane in ('confirmation', 'learning_and_legacy')}
    proceeds = dict.fromkeys(purchases, 0)
    uncertain = []
    for key, allocations in by_lot.items():
        lane = 'confirmation' if book.lots[key]['session_id'] in confirmation else 'learning_and_legacy'
        for allocation in allocations:
            activity = book.activities[allocation['activity_id']]
            if activity['cash_native'] is None or activity.get('principal_unproved'):
                uncertain.append(allocation['activity_id'])
            else:
                proceeds[lane] += allocation['payout_native']
    gaps = ['paid_reward_session_links_unverified', 'paid_fee_and_cost_scope_unverified',
            'independent_cutoff_cash_bridge_unverified', 'family_closure_unverified']
    if frozen is None or frozen.get('on_time') is not True:
        gaps.append('on_time_freeze_unverified')
    if winners: gaps.append('unredeemed_positive_payouts_at_cutoff')
    if unknown: gaps.append('settlement_unknown_at_cutoff')
    if uncertain: gaps.append('redemption_cash_or_allocation_unknown')
    try:
        assessment = final_cash_assessment(policy, profit_native=proceeds['confirmation'] - purchases['confirmation'],
            complete=False, family_closed=False, now=now)
    except ValueError as exc:
        if str(exc) != 'success_look_not_open':
            raise
        assessment = {'state': 'INCONCLUSIVE', 'label': 'MEASURED', 'net_cash_native': None,
                      'reason': 'success_look_not_open'}
    return {'schema_version': 'lfc_final_cash_snapshot_v0.1', 'label': 'MEASURED',
        'observed_at_utc': now.isoformat(), 'evidence_cutoff': cutoff.isoformat(),
        **{key: policy.raw[key] for key in ('policy_name', 'policy_revision')},
        'policy_sha256': policy.sha256, 'ledger_head_sha256': ledger.previous,
        'planning_booked_as_income': False, 'assessment': assessment, 'accounting_complete': False,
        'gaps': gaps, 'purchase_cost_native': purchases, 'proved_redemption_cash_native': proceeds,
        'cash_subtotal_before_unverified_income_fees_costs_native': {k: proceeds[k] - purchases[k] for k in purchases},
        'reward_accrual_native': None, 'reward_actually_paid_confirmation_native': None,
        'unredeemed_winners_at_cutoff': winners, 'unresolved_at_cutoff': unknown,
        'unswept_zero_payout_positions': zeros, 'evidence_sha256': hashes,
        'late_cash_activity_ids': sorted(key for key, a in book.activities.items() if a['timestamp'] > cutoff.timestamp())}


def write_final(state, policy, *, root, output, now):
    from weather.market.lfc_f2_freeze import verify
    from weather.market.lfc_campaign_policy import parse_policy
    state.require_retained_evidence()
    frozen = verify(state, policy=policy)
    if frozen is not None:
        policy = parse_policy(frozen['policy'])
    if not policy.f2:
        raise ValueError('final_look_requires_f2')
    row = snapshot(state.ledger, policy, root=root, now=now, frozen=frozen)
    write_new(output, {**row, 'content_sha256': digest(row)})
    return row
