"""Deterministic, role-specific verification of retained receipt projections.

Unsupported raw shapes cannot qualify. The raw wallet contract is snapshots plus
individual confirmed cash/token movements, never a second copy of aggregate P&L.
No submitted exporter is executed. Byte identity and venue authenticity differ.
"""
from collections import defaultdict
from copy import deepcopy
import json

from weather.backtesting.t1_accounting import actual_accounts
from weather.backtesting.t1_raw_snapshot import collateral, positions as native_positions, open_orders
from weather.backtesting.t1_types import ONE, ZERO, canonical, decimal_context, digest, number, utc

PROJECTOR = 't1_raw_projection_v1'


def load_role(verified, role):
    entry = verified[role]
    if entry['path'].stat().st_size > 16 * 1024 * 1024:
        raise ValueError('bounded raw role limit; stage a bounded session')
    return json.loads(entry['path'].read_bytes())


def same(value, expected, label):
    """Check projected facts, preserving identity strings and native quantities."""
    if isinstance(expected, dict):
        if not isinstance(value, dict) or set(value) != set(expected):
            raise ValueError(label + ': raw projection keys disagree')
        for key in expected:
            same(value[key], expected[key], label + '/' + str(key))
    elif isinstance(expected, list):
        if not isinstance(value, list) or len(value) != len(expected):
            raise ValueError(label + ': raw projection rows disagree')
        for i, item in enumerate(expected):
            same(value[i], item, label + '/' + str(i))
    elif isinstance(expected, type(ZERO)):
        if number(value, minimum=None) != expected:
            raise ValueError(label + ': raw numeric projection disagrees')
    elif value != expected:
        raise ValueError(label + ': raw projection disagrees')


def without_lineage(value):
    if isinstance(value, dict):
        return {k: without_lineage(v) for k, v in value.items() if not k.endswith('source_sha256')}
    if isinstance(value, list):
        return [without_lineage(v) for v in value]
    return value


def raw_clob(raw):
    """Retained request cursor plus native response pages, not a complete flag."""
    if raw['endpoint'] != 'https://clob.polymarket.com/data/trades' or not raw['pages']:
        raise ValueError('raw CLOB endpoint/pages missing')
    expected, rows = None, []
    for page in raw['pages']:
        if page['request_cursor'] != expected or expected == 'LTE=':
            raise ValueError('raw CLOB pagination chain fails')
        body = page['response']
        rows.extend(body['data'])
        expected = body['next_cursor']
    if expected != 'LTE=':
        raise ValueError('raw CLOB final cursor missing')
    return {'endpoint': raw['endpoint'], 'complete': True, 'next_cursor': 'LTE=', 'rows': rows}


def raw_settlement(raw, scope, tokens):
    matches = [r for r in raw['resolutions'] if r['condition_id'] == scope['condition_id']]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('duplicate raw resolution')
    row = matches[0]
    if row['token_ids'] != tokens or row['status'] != 'FINAL':
        raise ValueError('raw resolution mapping/finality fails')
    denominator = number(row['payout_denominator'], minimum=ONE)
    numerators = [number(v) for v in row['payout_numerators']]
    if len(numerators) != 2 or sum(numerators, ZERO) != denominator:
        raise ValueError('raw payout fractions do not conserve mass')
    return numerators[0] / denominator


def raw_reward(raw, scope):
    for key in ('account_id', 'condition_id', 'reward_day'):
        if raw[key] != scope[key]:
            raise ValueError('raw reward scope mismatch')
    paid = ZERO
    ids = set()
    for credit in raw['credits']:
        if credit['id'] in ids or utc(credit['at']) > utc(raw['as_of_utc']):
            raise ValueError('raw reward credit identity/finality/clock fails')
        ids.add(credit['id'])
        if credit['status'] == 'PENDING':
            continue
        if (credit['status'] != 'CONFIRMED' or not credit.get('finalized_at')
                or not utc(credit['at']) <= utc(credit['finalized_at']) <= utc(raw['as_of_utc'])):
            raise ValueError('raw paid reward requires completed finality by collection')
        allocated = {sid: number(amount) for sid, amount in credit['sessions'].items()}
        if sum(allocated.values(), ZERO) != number(credit['amount']):
            raise ValueError('raw reward allocation does not equal paid credit')
        paid += allocated.get(scope['session_id'], ZERO)
    return paid


def raw_wallet(raw, scope, tokens, yes_payout, source):
    """Derive purchases, fees, paid credits, burned tokens and all balances."""
    if raw.get('format') != PROJECTOR or raw['account_id'] != scope['account_id'] or raw['session_id'] != scope['session_id']:
        raise ValueError('raw wallet snapshot/activity format or scope unsupported')
    opening, terminal, closing = (raw[k] for k in ('opening', 'terminal', 'closing'))
    if not utc(opening['at']) <= utc(terminal['at']) <= utc(closing['at']):
        raise ValueError('raw wallet snapshot clock fails')
    opening_positions, other = native_positions(opening, tokens, scope['account_id'], scope['condition_id'])
    native_terminal, terminal_other = native_positions(terminal, tokens, scope['account_id'], scope['condition_id'])
    native_closing, closing_other = native_positions(closing, tokens, scope['account_id'], scope['condition_id'])
    if terminal_other or closing_other:
        raise ValueError('flat account projection cannot omit other terminal/closing positions')
    opening_cash, closing_cash = collateral(opening), collateral(closing)
    holdings = dict(opening_positions)
    cash = opening_cash
    terminal_positions, terminal_cash = None, None
    fills, redemptions, outside, cash_events, ids = [], [], [], [], set()
    rewards, rebates, fees, costs, redeem_cash = ZERO, ZERO, ZERO, ZERO, ZERO
    payment_ids = {'reward': [], 'rebate': [], 'redemption': []}
    last, last_phase = utc(opening['at']), -100
    for row in raw['activity']:
        at = utc(row['at'])
        phase = 2 if row['kind'] == 'BUY' else 7
        if at < last or at > utc(closing['at']) or row['id'] in ids or row['status'] != 'CONFIRMED':
            raise ValueError('raw wallet activity identity/finality/clock fails')
        if at == last and phase < last_phase:
            raise ValueError('same-clock raw activity contradicts the declared economic phases')
        if terminal_positions is None and (at > utc(terminal['at']) or at == utc(terminal['at']) and phase > 3):
            terminal_positions = dict(holdings)
            terminal_cash = cash
        ids.add(row['id'])
        last, last_phase = at, phase
        amount = number(row['cash_delta'], minimum=None)
        kind = row['kind']
        if kind == 'BUY':
            token, size, price = row['token_id'], number(row['size']), number(row['price'], maximum=ONE)
            if token not in holdings or amount != -size * price:
                raise ValueError('raw BUY native quantities/cash fail')
            holdings[token] += size
            fills.append({'order_id': row['order_id'], 'price': price, 'size': size})
        elif kind == 'REDEEM':
            burned = {t: number(row['tokens'][t]) for t in tokens}
            if set(row['tokens']) != set(tokens) or yes_payout is None:
                raise ValueError('raw redemption missing native resolution')
            value = sum((burned[t] * (yes_payout if i == 0 else ONE - yes_payout) for i, t in enumerate(tokens)), ZERO)
            if amount != value:
                raise ValueError('raw redemption proceeds disagree with payout')
            for token in tokens:
                holdings[token] -= burned[token]
                if holdings[token] < ZERO:
                    raise ValueError('raw token balance below zero')
            redemptions.append({'id': row['id'], 'session_id': scope['session_id'], 'at': row['at'],
                                'tokens': burned, 'credit': amount, 'source_sha256': source,
                                'status': row['status'], 'finalized_at': row.get('finalized_at')})
            redeem_cash += amount
            payment_ids['redemption'].append(row['id'])
        elif kind in ('REWARD', 'REBATE'):
            if amount < ZERO:
                raise ValueError('raw incentive credit is negative')
            if kind == 'REWARD':
                rewards += amount
            else:
                rebates += amount
            payment_ids[kind.lower()].append(row['id'])
        elif kind in ('MAKER_FEE', 'OPERATING_COST'):
            if amount > ZERO:
                raise ValueError('raw cost has positive cash sign')
            if kind == 'MAKER_FEE':
                fees -= amount
            else:
                costs -= amount
        elif kind == 'EXTERNAL':
            outside.append({'id': row['id'], 'session_id': row['session_id'], 'amount': amount, 'source_sha256': source})
        else:
            raise ValueError('unsupported raw activity; manual exits cannot qualify BUY/hold')
        if kind not in ('BUY', 'REDEEM'):
            cash_events.append({'id': row['id'], 'kind': kind, 'at': row['at'], 'amount': amount,
                                 'status': row['status'], 'finalized_at': row.get('finalized_at'), 'source_sha256': source})
        cash += amount
    if terminal_positions is None:
        terminal_positions = dict(holdings)
        terminal_cash = cash
    if abs(collateral(terminal) - terminal_cash) > number('.00001'):
        raise ValueError('wallet/terminal_cash: raw cash conservation fails')
    same(native_terminal, terminal_positions, 'wallet/terminal_positions')
    same(native_closing, holdings, 'wallet/end_positions')
    if abs(closing_cash - cash) > number('.00001'):
        raise ValueError('wallet/end_cash: raw cash conservation fails')
    bought = defaultdict(lambda: ZERO)
    for row in raw['activity']:
        if row['kind'] == 'BUY':
            bought[row['token_id']] += number(row['size'])
    venue_value = ZERO if yes_payout is None else sum((bought[t] * (yes_payout if i == 0 else ONE - yes_payout)
                                                       for i, t in enumerate(tokens)), ZERO)
    return {'account_id': scope['account_id'], 'session_id': scope['session_id'], 'complete': True,
        'opening_positions': opening_positions,
        'opening_open_orders': open_orders(opening), 'opening_other_positions': list(other),
        'opening_other_open_orders': [], 'terminal_positions': terminal_positions,
        'end_positions': holdings, 'start_as_of_utc': opening['at'], 'as_of_utc': closing['at'],
        'start_cash': opening_cash, 'end_cash': closing_cash, 'fills': fills,
        'redemptions': redemptions, 'reward_credit': rewards, 'rebate_credit': rebates,
        'redemption_credit': redeem_cash, 'maker_fees': fees, 'operating_cost': costs,
        'payment_ids': payment_ids, 'other_attributed_cashflows': outside, 'unattributed_cashflows': [],
        'settlement_complete': yes_payout is not None or not fills, 'yes_payout': yes_payout if yes_payout is not None else ZERO,
        'settlement_value': venue_value, 'cash_events': cash_events,
        'closing_open_orders': open_orders(closing),
        'cash_followup_complete': closing.get('activity_final') is True,
        'payment_scope_complete': raw.get('activity_cursor') == 'LTE='}


@decimal_context
def verify_projection(verified, receipts, payload, result):
    """Recompute actual accounts from raw role bytes and check every projected fact.

    Returns a bound verification receipt, or a concrete mismatch. No role can be
    satisfied by a hash of unrelated bytes from another role.
    """
    from weather.backtesting.t1_accuracy import clob_fills, pin_commands, read_pin_evidence

    followup_roles = tuple('reward_followup_' + str(i + 1) for i in range(len(receipts.get('reward_followups', []))))
    required = ('journal', 'clob', 'wallet', 'settlement', 'redemptions', 'reward_d1', 'reward_d2', *followup_roles)
    if any(role not in verified for role in required):
        raise ValueError('raw financial roles missing')
    scope = receipts['scope']
    tokens = payload['conditions'][scope['condition_id']]['token_ids']
    raw = {role: load_role(verified, role) for role in required if role != 'journal'}
    # Explicitly diagnose the original counterexample even if its legacy raw
    # shape is otherwise unsupported; unknown schemas never become PASS.
    if 'end_cash' in raw['wallet']:
        same(raw['wallet']['end_cash'], number(receipts['wallet']['end_cash']), 'wallet/end_cash')
    yes_payout = raw_settlement(raw['settlement'], scope, tokens)
    settlement_hashes = {verified['settlement']['sha256'], *(digest(r) for r in raw['settlement']['resolutions'])}
    if yes_payout is not None:
        if receipts['wallet']['settlement_source_sha256'] not in settlement_hashes:
            raise ValueError('wallet payout source is not its raw settlement role')
        for event in payload['events']:
            if event['kind'] == 'settlement':
                resolution = next(r for r in raw['settlement']['resolutions'] if r['condition_id'] == event['condition_id'])
                if (event['source_sha256'] not in settlement_hashes
                        or utc(event['at']) != utc(resolution['available_at'])
                        or number(event['yes_payout']) != yes_payout):
                    raise ValueError('settlement event source, clock or payout differs from its raw record')
    wallet = raw_wallet(raw['wallet'], scope, tokens, yes_payout, verified['wallet']['sha256'])
    for key, value in wallet.items():
        actual = receipts['wallet'].get(key)
        # Source hashes are checked at their precise role rather than compared
        # as arithmetic facts; record bytes still determine every monetary field.
        same(without_lineage(actual), without_lineage(value), 'wallet/' + key)
    for flow in receipts['wallet'].get('cash_events', []):
        if flow['source_sha256'] != verified['wallet']['sha256']:
            raise ValueError('cash event source is not its raw wallet role')
    if 'wallet_observations' not in verified and receipts['wallet']['end_cash_source_sha256'] != verified['wallet']['sha256']:
        raise ValueError('wallet closing cash source is not its raw wallet role')
    clob = raw_clob(raw['clob'])
    same(receipts['clob'], clob, 'clob')
    journal = read_pin_evidence(verified['journal']['path'])
    _, known = pin_commands(journal.rows, scope['condition_id'])
    fills = clob_fills(clob, known, tokens, account_id=scope['account_id'])
    accounts = actual_accounts(fills, wallet, tokens, yes_payout=yes_payout, session_id=scope['session_id'])
    for key, value in accounts.items():
        same(result['actual_accounts'][key], value, 'accounts/' + key)
    from weather.backtesting.t1_wallet_observations import verify_observations

    observations = verify_observations(verified, raw['wallet'], receipts, payload, accounts)
    if observations['status'] == 'PASS':
        same(result['wallet_observations'], observations['references'], 'report/wallet_observations')
        same(result['wallet_activity_source_sha256'], verified['wallet']['sha256'], 'report/wallet_activity_source_sha256')
        same(result['wallet_end_cash_source_sha256'], observations['source_sha256'], 'report/wallet_end_cash_source_sha256')
    same(without_lineage(receipts['wallet']['redemptions']), without_lineage(raw['redemptions']['transactions']), 'redemptions')
    reward_reads = [*receipts['rewards'], *receipts.get('reward_followups', [])]
    for role, read in zip(('reward_d1', 'reward_d2', *followup_roles), reward_reads):
        if read['source_sha256'] != verified[role]['sha256'] or read['as_of_utc'] != raw[role]['as_of_utc']:
            raise ValueError(role + ': wrong raw source or collection clock')
        same(read['paid_reward'], raw_reward(raw[role], scope), role + '/paid_reward')
        if read is reward_reads[-1] and any(
                c['status'] == 'PENDING' for c in raw[role]['credits']):
            raise ValueError('latest retained reward observation still has pending credits')
        if read.get('allocation'):
            allocation = read['allocation']
            matches = [c for c in raw[role]['credits'] if c['id'] == allocation['payment_id'] and c['status'] == 'CONFIRMED']
            if len(matches) != 1:
                raise ValueError('raw shared reward payment identity missing or repeated')
            credit = matches[0]
            same(allocation['sessions'], {sid: number(v) for sid, v in credit['sessions'].items()}, role + '/allocation')
            same(allocation['day_total'], number(credit['amount']), role + '/day_total')
            if allocation['source_sha256'] not in (verified[role]['sha256'], digest(credit)):
                raise ValueError('shared reward allocation source is not its raw credit record')
    try:
        transition_check = verify_raw_states(raw['wallet'], receipts, payload, journal.rows, known, fills,
                                              verified['wallet']['sha256'])
    except (ValueError, KeyError, TypeError) as exc:
        transition_check = {'status': 'NOT QUALIFIED', 'reason': str(exc)}
    from weather.backtesting.t1_raw_market import verify_market_roles

    return {'projector': PROJECTOR, 'status': 'PASS',
            'scope': 'RAW_FINANCIAL_PROJECTION', 'transitions': transition_check,
            'market_projection': verify_market_roles(verified, payload, receipts),
            'wallet_observations': observations,
            'input_role_sha256': {k: verified[k]['sha256'] for k in (*required,
                *(('wallet_observations',) if 'wallet_observations' in verified else ()))},
            'projected_accounts_sha256': digest(accounts),
            'normalized_receipts_sha256': digest(receipts), 'actual_accounts': accounts}


def verify_raw_states(raw, receipts, payload, journal_rows, known, fills, source):
    """Check raw snapshots using private orders/fills and actual cash movements.

    The public-book simulator is deliberately absent from this reconstruction.
    """
    from weather.backtesting.t1_accuracy import pin_commands
    from weather.backtesting.t1_transitions import required_transitions

    cid, tokens = receipts['scope']['condition_id'], payload['conditions'][receipts['scope']['condition_id']]['token_ids']
    commands, _ = pin_commands(journal_rows, cid)
    required = required_transitions(commands, fills, payload['events'], receipts['wallet'],
        start=payload['start'], terminal=journal_rows[-1]['recorded_at_utc'])
    observations = {r.get('transition_id', r['id']): r for r in raw['checkpoints']}
    normalized = {r.get('transition_id', r['id']): r for r in receipts['state_checkpoints']}
    if len(observations) != len(raw['checkpoints']) or not set(required) <= set(observations):
        raise ValueError('raw checkpoints omit or repeat required economic transitions')
    if set(observations) != set(normalized):
        raise ValueError('normalized checkpoint population differs from raw observations')
    for key, checkpoint in observations.items():
        projected = {k: checkpoint[k] for k in ('id', 'at', 'reserved', 'cost_at_risk')}
        if 'transition_id' in checkpoint:
            projected['transition_id'] = checkpoint['transition_id']
        if 'activity_prefix_ids' in checkpoint:
            projected['activity_prefix_ids'] = checkpoint['activity_prefix_ids']
        projected['cash'] = collateral(checkpoint)
        projected['positions'], other = native_positions(checkpoint, tokens, receipts['scope']['account_id'], cid)
        same(without_lineage(normalized[key]), projected, 'checkpoint/' + key)
        if normalized[key]['source_sha256'] not in (source, digest(checkpoint)):
            raise ValueError('checkpoint source is not its raw wallet record')
        at = utc(checkpoint['at'])
        phase = {'opening': -100, 'expiry': -1, 'fill': 2, 'terminal': 3, 'cancel': 3,
                 'post': 4, 'settlement': 6, 'redemption': 7, 'cash': 7}.get(key.split(':')[0])
        if phase is None and any(utc(row['at']) == at for row in raw['activity']):
            raise ValueError('same-clock observation needs an identified economic transition')
        phase = 8 if phase is None else phase
        if key in required and at != required[key]:
            raise ValueError('raw economic transition observation clock differs')
        cash = collateral(raw['opening'])
        positions, _ = native_positions(raw['opening'], tokens, receipts['scope']['account_id'], cid)
        prefix = checkpoint.get('activity_prefix_ids')
        if prefix is None:
            if any(utc(row['at']) == at for row in raw['activity']):
                raise ValueError('same-clock raw checkpoint requires an explicit activity prefix')
            included = [row for row in raw['activity'] if utc(row['at']) < at]
        else:
            included = raw['activity'][:len(prefix)]
            if (prefix != [row['id'] for row in included]
                    or any(utc(row['at']) > at for row in included)
                    or any(utc(row['at']) < at for row in raw['activity'][len(prefix):])):
                raise ValueError('raw checkpoint activity prefix is not an observed chronological prefix')
            if phase <= 6 and any(utc(row['at']) == at and row['kind'] != 'BUY' for row in included):
                raise ValueError('settlement/order phase precedes same-clock redemption and payments')
            if phase < 2 and any(utc(row['at']) == at for row in included):
                raise ValueError('opening/expiry phase precedes same-clock executions')
            if key.startswith(('redemption:', 'cash:')) and (not prefix or prefix[-1] != key.split(':', 1)[1]):
                raise ValueError('payment checkpoint prefix must end at its identified movement')
        matched, foreign = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
        for row in included:
            cash += number(row['cash_delta'], minimum=None)
            if row['kind'] == 'BUY':
                positions[row['token_id']] += number(row['size'])
                matched[row['order_id']] += number(row['size'])
            elif row['kind'] == 'REDEEM':
                for token in tokens:
                    positions[token] -= number(row['tokens'][token])
            elif row['kind'] == 'EXTERNAL':
                for token, delta in row.get('token_deltas', {}).items():
                    if token in tokens or not token.isdigit() or utc(row['at']) < utc(payload['end']):
                        raise ValueError('foreign token movements require a disjoint later funded period')
                    foreign[token] += number(delta, minimum=None)
                    if foreign[token] < ZERO:
                        raise ValueError('foreign token movement exceeds independently retained holdings')
        same(other, {t: v for t, v in foreign.items() if v}, 'checkpoint/' + key + '/other_positions')
        for fill in fills:
            if fill['at'] < at < fill['at_end']:
                raise ValueError('raw transition clock falls within unresolved fill interval')
        for oid in known:
            before = sum((f['size'] for f in fills if f['order_id'] == oid and f['at_end'] < at), ZERO)
            through = sum((f['size'] for f in fills if f['order_id'] == oid and f['at_end'] <= at), ZERO)
            if not before <= matched[oid] <= through:
                raise ValueError('checkpoint activity prefix contradicts private fill quantities/clocks')
        resolved = any(e['kind'] == 'settlement' and (utc(e['at']) < at or utc(e['at']) == at and phase >= 6)
                       for e in payload['events'])
        reserve = ZERO
        terminal_at = utc(journal_rows[-1]['recorded_at_utc'])
        closed = at > terminal_at or at == terminal_at and phase >= 3
        if not closed and not resolved:
            for oid, command in known.items():
                canceled = any(c['kind'] == 'cancel' and c['id'] == oid and (utc(c['arrival_at']) < at
                               or utc(c['arrival_at']) == at and phase >= 3) for c in commands)
                arrived = utc(command['arrival_at']) < at or utc(command['arrival_at']) == at and phase >= 4
                simultaneous_posts = [c['id'] for c in commands if c['kind'] == 'post' and utc(c['arrival_at']) == at]
                if phase == 4 and len(simultaneous_posts) > 1 and oid in simultaneous_posts:
                    arrived = arrived and simultaneous_posts.index(oid) <= simultaneous_posts.index(key.split(':', 1)[1])
                if arrived and at < utc(command['expires_at']) and not canceled:
                    reserve += number(command['price']) * (number(command['size']) - matched[oid])
        risk = ZERO if resolved else reserve + sum((number(known[oid]['price']) * size for oid, size in matched.items()), ZERO)
        observed_cash = collateral(checkpoint)
        observed_positions, _ = native_positions(checkpoint, tokens, receipts['scope']['account_id'], cid)
        if abs(observed_cash - cash) > number('.00001'):
            raise ValueError('raw checkpoint cash conservation fails')
        same(observed_positions, positions, 'checkpoint/' + key + '/positions')
        same(checkpoint['reserved'], reserve, 'checkpoint/' + key + '/reserved')
        same(checkpoint['cost_at_risk'], risk, 'checkpoint/' + key + '/cost_at_risk')
    return {'status': 'PASS', 'required_ids': sorted(required)}
