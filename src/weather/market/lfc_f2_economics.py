"""Measured native cash and immutable follow-ups, distinct from planning.

Public summaries export normalized facts and hashes only. Incentive activity
has no authoritative earned-day reference: an observed payment is deliberately
not invented as a particular session's income.
"""
from decimal import Decimal
from pathlib import Path

from weather.market.lfc_capital import ASSET, CapitalBook, native
from weather.market.lfc_recording_io import file_sha, write_new
from weather.market.mm_stage2_hold import digest


def measured(ledger, sessions):
    sessions = set(sessions)
    book = CapitalBook(ledger)
    fills = [{'session_id': leg['session_id'], 'order_id': leg['order_id'], 'token_id': leg['token_id'],
              'size': leg['size_matched'], 'price': leg['price'],
              'purchase_cost_native': native(Decimal(leg['size_matched']) * Decimal(leg['price']), ceil=True)}
             for leg in ledger.legs.values() if leg['session_id'] in sessions and leg['status'] == 'terminal'
             and Decimal(leg['size_matched'])]
    releases = [r for r in book.allocations if book.lots[r['intent_key']]['session_id'] in sessions]
    ids = {r['activity_id'] for r in releases}
    redemptions = []
    for key in sorted(ids):
        all_allocations = [r for r in book.allocations if r['activity_id'] == key]
        exclusive = all(book.lots[r['intent_key']]['session_id'] in sessions for r in all_allocations)
        redemptions.append({**book.redemptions[key], 'exclusive_session_scope': exclusive,
            'session_cash_native': book.redemptions[key]['cash_native'] if exclusive else None})
    credits = [{'activity_id': key, 'type': row['type'], 'cash_native': row['cash_native'],
                'timestamp': row['timestamp'], 'attributed_session': None}
               for key, row in book.activities.items() if row['type'] in
               ('REWARD', 'YIELD', 'MAKER_REBATE', 'TAKER_REBATE', 'REFERRAL_REWARD')]
    return {'label': 'MEASURED', 'cash_asset': ASSET, 'native_decimals': 6, 'fills': fills,
        'fees': {'maker_fee_paid_native': None, 'state': 'independent_session_fee_receipt_not_available',
                 'campaign_paid_or_reserved_costs_native': book.costs},
        'carried_inventory': [{'intent_key': key, 'token_id': lot['token_id'],
            'quantity': str(lot['remaining_quantity']), 'cost_basis_native': lot['remaining_basis']}
            for key, lot in book.lots.items() if lot['session_id'] in sessions and lot['remaining_quantity'] and
            not lot.get('zero_payout_evidence_sha256')],
        'unswept_zero_payout_positions': [{'intent_key': key, 'token_id': lot['token_id'],
            'quantity': str(lot['remaining_quantity']), 'settlement_sha256': lot['zero_payout_evidence_sha256']}
            for key, lot in book.lots.items() if lot['session_id'] in sessions and lot['remaining_quantity'] and
            lot.get('zero_payout_evidence_sha256')],
        'settlement': {'cost_basis_releases': releases, 'redemptions': redemptions,
                       'zero_payout_losses': [r for r in book.zero_resolutions if book.lots[r['intent_key']]['session_id'] in sessions],
                       'unknown_payouts': [key for key in book.unknown if key in ids]},
        'rewards': {'accruals': [], 'actually_paid_native': None, 'rebates_actually_paid_native': None,
                    'account_cash_credits': credits, 'earned_session_link_verified': False,
                    'state': 'earned_scope_evidence_pending', 'planning_is_income': False},
        'campaign_capital': book.figures()}


def economics(coordinator):
    prediction = sum(row['predicted_360_minutes'] for row in coordinator.table['rows']
                     if row['condition_id'] in coordinator.table['selected_condition_ids'])
    duration = max((band.planned_seconds for band in coordinator.bands), default=0)
    return {'planning': {'label': 'PLANNING', 'booked_as_income': False,
                'predicted_360_minute_reward': prediction, 'maximum_session_seconds': duration,
                'expected_maker_fee_native': 0,
                'basis': 'displayed_competition_scenario_not_expected_profit'},
            'measured': measured(coordinator.ledger, [band.session_id for band in coordinator.bands])}


def accrual_evidence(root, ledger, sessions):
    """Replay retained R3 evidence. Native token units never use an asset USD rate."""
    from weather.market.lfc_rewards_record import latest_record
    result, hashes, gaps = [], {}, []
    maker = ledger.rows[0]['maker_address'].lower()
    days = sorted({ledger.sessions[sid]['start']['recorded_at_utc'][:10] for sid in sessions})
    selected = {ledger.sessions[sid]['start']['condition_id'] for sid in sessions}
    for day in days:
        conditions = sorted({s['start']['condition_id'] for s in ledger.sessions.values()
            if s['legs'] and s['start']['recorded_at_utc'][:10] == day})
        for lag in (1, 2):
            base = Path(root) / 'rewards' / f'{day}-d{lag}.json'
            try:
                row, path, _ = latest_record(base, kind='lfc_rewards_record', day=day, maker=maker,
                                              conditions=conditions, lag=lag)
                if row is None:
                    gaps.append(f'{day}:d{lag}:pending')
                    continue
                hashes[path.name] = file_sha(path)
                for entry in row['accruals']:
                    if entry['condition_id'] not in selected:
                        continue
                    if not entry['source']['complete']:
                        gaps.append(f'{day}:d{lag}:incomplete')
                        continue
                    for item in entry['accruals']:
                        result.append({key: item[key] for key in ('accrual_id', 'condition_id', 'cash_asset',
                            'venue_amount', 'status', 'period_start_utc', 'period_end_utc')} | {'record_pass': lag})
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                gaps.append(f'{day}:d{lag}:refused')
    return result, hashes, gaps


def publish_supplements(runtime):
    """A new hash names each new observation; the original outcome is immutable."""
    state, ledger = runtime.state, runtime.state.ledger
    for claim in state.claims():
        sessions = [sid for sid, row in ledger.sessions.items()
                    if row['start'].get('autostart_attempt_id') == claim['attempt_id']]
        if not sessions or not all(ledger.sessions[sid]['end'] is not None for sid in sessions):
            continue
        result, result_sha, _ = state.retained_result(claim)
        if not result['outcome'].get('f2_session'):
            continue
        facts = measured(ledger, sessions)
        accruals, hashes, gaps = accrual_evidence(runtime.pilot_root, ledger, sessions)
        facts['rewards'].update(accruals=accruals, evidence_gaps=gaps)
        content = {'session_id': result['session_id'], 'attempt_id': claim['attempt_id'],
            **{key: claim.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')},
            'original_result_sha256': result_sha, 'ledger_head_sha256': ledger.previous,
            'evidence_sha256': hashes, 'measured': facts}
        sha = digest(content)
        relative = 'economics/' + sha[:32] + '.json'
        if not (state.root / relative).exists():
            state.save(relative, dict(content, content_sha256=sha, observed_at_utc=runtime.clock.now().isoformat()))
        elif state.read(state.root / relative).get('content_sha256') != sha:
            raise ValueError('economics_supplement_collision')
        target = runtime.control_root.parent / (result['session_id'] + '.e-' + sha[:16] + '.json')
        if not target.exists():
            write_new(target, dict(schema_version='lfc_economics_supplement_v0.1', content_sha256=sha, **content))
        else:
            from weather.market.lfc_recording_io import read_bytes, strict_json
            if strict_json(read_bytes(target, 2_000_000)).get('content_sha256') != sha:
                raise ValueError('economics_supplement_collision')


def final_cash_assessment(policy, *, profit_native, complete, family_closed, now):
    """One final cash look; positive cash alone never means qualified edge."""
    from datetime import datetime
    if now < datetime.fromisoformat(policy.raw['success_looks'][0]):
        raise ValueError('success_look_not_open')
    if not complete or profit_native is None:
        return {'state': 'INCONCLUSIVE', 'label': 'MEASURED', 'net_cash_native': None}
    if type(profit_native) is not int or profit_native < -300_000_000:
        raise ValueError('campaign_loss_bound_violated')
    alpha = Decimal(policy.raw['family_alpha']) if family_closed else Decimal('.0125')
    bound = alpha * (profit_native + 300_000_000) - 300_000_000
    return {'state': 'PASS' if family_closed and profit_native > 0 and bound > 0 else 'INCONCLUSIVE',
            'label': 'MEASURED', 'net_cash_native': profit_native, 'cash_positive': profit_native > 0,
            'lower_confidence_bound_native': str(bound), 'alpha': str(alpha),
            'nominal_dates': policy.raw['nominal_confirmation_dates'], 'independent_campaigns': 1}
