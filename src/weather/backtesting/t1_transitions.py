"""Required economic transition inventory and independent state comparisons."""
from collections import defaultdict

from weather.backtesting.t1_types import ZERO, number, utc


def required_transitions(commands, fills, events, wallet, *, start, terminal):
    required = {'opening': utc(start), 'terminal': utc(terminal)}
    for command in commands:
        required[command['kind'] + ':' + command['id']] = utc(command['arrival_at'])
    counts = defaultdict(int)
    for fill in sorted(fills, key=lambda r: (r['at'], r['trade_id'], r['order_id'])):
        counts[fill['order_id']] += 1
        required[f"fill:{fill['order_id']}:{counts[fill['order_id']]}"] = fill['at']
    for event in events:
        if event['kind'] == 'settlement':
            required['settlement:' + event['condition_id']] = utc(event['at'])
        elif event['kind'] == 'redemption':
            if event.get('id'):
                required['redemption:' + event['id']] = utc(event['at'])
    for redemption in wallet['redemptions']:
        required['redemption:' + redemption['id']] = utc(redemption['at'])
    for flow in wallet.get('cash_events', []):
        required['cash:' + flow['id']] = utc(flow['at'])
    cash_events = wallet.get('cash_events', [])
    expected_totals = {'REWARD': number(wallet['reward_credit']), 'REBATE': number(wallet['rebate_credit']),
                       'MAKER_FEE': -number(wallet['maker_fees']), 'OPERATING_COST': -number(wallet['operating_cost']),
                       'EXTERNAL': sum((number(f['amount'], minimum=None) for f in wallet['other_attributed_cashflows']), ZERO)}
    for kind, expected in expected_totals.items():
        if sum((number(f['amount'], minimum=None) for f in cash_events if f['kind'] == kind), ZERO) != expected:
            required['unverified_cash_events:' + kind] = utc(wallet['as_of_utc'])
    if {f['id'] for f in cash_events if f['kind'] == 'EXTERNAL'} != {f['id'] for f in wallet['other_attributed_cashflows']}:
        required['unverified_cash_events:external_identities'] = utc(wallet['as_of_utc'])
    # Expiry matters only while the private lifetime still has unfilled reserve.
    for command in commands:
        if command['kind'] != 'post':
            continue
        expiry = utc(command['expires_at'])
        canceled = any(c['kind'] == 'cancel' and c['id'] == command['id'] and utc(c['arrival_at']) <= expiry for c in commands)
        filled = sum((f['size'] for f in fills if f['order_id'] == command['id'] and f['at_end'] <= expiry), ZERO)
        if expiry <= utc(terminal) and not canceled and filled < number(command['size']):
            required['expiry:' + command['id']] = expiry
    return required


def verify_transitions(required, predictions, observed, cid, *, money_tolerance, position_tolerance):
    """No caller-chosen terminal-only subset can satisfy transition coverage."""
    from weather.backtesting.t1_accuracy import compare

    indexed = {}
    for checkpoint in observed:
        key = checkpoint.get('transition_id', checkpoint['id'])
        if key in indexed:
            raise ValueError('duplicate economic transition observation')
        indexed[key] = checkpoint
    missing, metrics = [], {}
    for key, at in required.items():
        actual, predicted = indexed.get(key), predictions.get(key)
        if actual is None or predicted is None:
            missing.append(key)
            continue
        if utc(actual['at']) != at or utc(predicted['at']) != at:
            missing.append(key + ':unidentified_clock')
            continue
        row = {k: compare(predicted[k], number(actual[k]), money_tolerance)
               for k in ('cash', 'reserved', 'cost_at_risk')}
        for token, size in predicted['positions'][cid].items():
            row['position:' + token] = compare(size, number(actual['positions'][token]), position_tolerance)
        metrics[key] = row
    passed = not missing and all(m['pass'] for row in metrics.values() for m in row.values())
    return {'status': 'PASS' if passed else 'NOT QUALIFIED' if missing else 'FAIL', 'required_ids': sorted(required),
            'missing': sorted(missing), 'metrics': metrics}
