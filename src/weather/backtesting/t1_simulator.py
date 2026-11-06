"""Deterministic, offline T1 post-only maker replay against explicit captured inputs.

No source discovery, network, credentials, wall clock, model, or trial verdict.
BUY YES/NO only. Settlement releases locked capital; rewards do not fund new
orders before payment. All unknowns remain non-countable in report reasons.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal as D

from weather.backtesting.t1_rewards import reward_share
from weather.backtesting.t1_types import (ONE, ZERO, ReplayConfig, book_valid, decimal_context, digest,
                                         fee, levels, number, source_hash, utc)


@decimal_context
def market_centred_quote(book, *, condition_id, observed_at, size, distance_cents, tick,
                         expires_at, max_book_age_seconds):
    """Pure policy proposal from the captured YES mid; both legs are native buys."""
    from decimal import ROUND_CEILING, ROUND_FLOOR

    size, tick = number(size), number(tick)
    if size <= ZERO or tick <= ZERO:
        raise ValueError('invalid quote size or tick')
    book_valid(book, now=utc(observed_at), max_age=number(max_book_age_seconds))
    if (utc(expires_at) <= utc(observed_at)
            or any(number(book[o]['tick']) != tick or size < number(book[o]['min_order_size']) for o in ('YES', 'NO'))):
        raise ValueError('proposal differs from captured rules or expiry')
    mid = (max(r['price'] for r in levels(book['YES']['bids']))
           + min(r['price'] for r in levels(book['YES']['asks']))) / 2
    distance = number(distance_cents) / 100
    bid = ((mid - distance) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    ask = ((mid + distance) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    if not ZERO < bid < ask < ONE:
        raise ValueError('quote outside probability range')
    return [{'kind': 'post', 'id': f'{condition_id}:{observed_at}:{outcome}', 'condition_id': condition_id,
             'outcome': outcome, 'observed_at': observed_at, 'decided_at': observed_at,
             'expires_at': expires_at, 'price': str(price), 'size': str(size)}
            for outcome, price in (('YES', bid), ('NO', ONE - ask))]


@decimal_context
def replay(payload, config: ReplayConfig):
    """Replay normalized full snapshots and execution-time trades, never Gamma prices.

    events: book, terms, trade, settlement. Each has at (availability UTC).
    Trades additionally require traded_at and aggressor. Public print latency
    does not move execution time forward: matching uses traded_at, while quote
    decisions always use observed_at plus declared end-to-end latency.
    coverage is a declared complete book/trade interval per condition.
    """
    start, end = utc(payload['start']), utc(payload['end'])
    if start >= end:
        raise ValueError('invalid replay interval')
    if payload.get('opening_state') != 'flat':
        raise ValueError('explicit flat opening state required; inventory state carry is unsupported')
    conditions = payload['conditions']
    if not conditions:
        raise ValueError('empty universe')
    if len(payload['events']) + len(payload['commands']) > 50000:
        raise ValueError('bounded replay limit exceeded; export a smaller session')
    all_tokens = set()
    for cid, meta in conditions.items():
        if (meta['venue'] != 'international_polymarket' or len(meta['token_ids']) != 2
                or len(set(meta['token_ids'])) != 2 or meta['native_unit'] not in ('C', 'F')):
            raise ValueError('condition mapping or venue missing')
        date.fromisoformat(meta['event_date'])
        if any(not isinstance(token, str) or not token or token in all_tokens for token in meta['token_ids']):
            raise ValueError('duplicate or missing token across conditions')
        all_tokens.update(meta['token_ids'])
        if utc(meta['coverage_start']) > start or utc(meta['coverage_end']) < end:
            raise ValueError('incomplete capture coverage')
        number(meta['tick'], minimum=D('.000001'))
        number(meta['min_order_size'], minimum=D('.000001'))
    max_age = number(config.max_book_age_seconds)
    latency = timedelta(seconds=float(number(config.latency_seconds)))
    order_latency = timedelta(seconds=float(number(config.order_latency_seconds)))
    books, terms, active, orders, fills = {}, {}, {}, {}, []
    used, rewards = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    rewarded_seconds = defaultdict(lambda: ZERO)
    spent, payouts, cash_paid, rebate_weight = ZERO, ZERO, ZERO, defaultdict(lambda: ZERO)
    settlement_values, redeemed = {}, defaultdict(lambda: ZERO)
    reasons, rejected, settled = set(), [], set()
    if payload.get('account_scope_complete') is not True:
        reasons.add('incomplete_account_incentive_scope')
    external = payload.get('external_incentives', {})
    for row in external.values():
        if row['complete'] is not True:
            raise ValueError('incomplete external account incentives')
        source_hash(row['source_sha256'])
        number(row['reward_accrued'])
        number(row['rebate_accrued'])
    schedule = []
    if payload.get('close_all_at') is not None:
        source_hash(payload['close_all_source_sha256'])
        close_at = utc(payload['close_all_at'])
        if not start <= close_at <= end:
            raise ValueError('session close outside replay interval')
        schedule.append((close_at, 3, -1, {'kind': 'session_close'}))
    midnight = (start + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while midnight < end:
        schedule.append((midnight, 8, 0, {'kind': 'boundary'}))
        midnight += timedelta(days=1)
    trade_ids = {}
    for i, event in enumerate(payload['events']):
        source_hash(event['source_sha256'])
        cid = event['condition_id']
        if cid not in conditions:
            raise ValueError('unknown condition')
        available = utc(event['at'])
        at = utc(event['traded_at']) if event['kind'] == 'trade' else available
        if event['kind'] == 'trade':
            if at > available:
                raise ValueError('trade precedes availability incorrectly')
            key = (cid, event['id'])
            if key in trade_ids:
                prior = trade_ids[key]
                economic_keys = ('traded_at', 'outcome', 'aggressor')
                if (any(prior[k] != event[k] for k in economic_keys)
                        or number(prior['price']) != number(event['price'])
                        or number(prior['size']) != number(event['size'])):
                    raise ValueError('conflicting duplicate trade')
                continue
            trade_ids[key] = event
        priority = {'book': 0, 'terms': 1, 'trade': 2, 'settlement': 6, 'redemption': 7}.get(event['kind'])
        if priority is None:
            raise ValueError('unknown event kind')
        if at < start or at > end:
            raise ValueError('event outside declared interval')
        schedule.append((at, priority, i, event))
    post_arrivals, cancels = {}, []
    for i, command in enumerate(payload['commands']):
        if command['kind'] not in ('post', 'cancel'):
            raise ValueError('only post/cancel simulation commands supported')
        if not isinstance(command['id'], str) or not command['id']:
            raise ValueError('submitted order identity required')
        observed = utc(command['observed_at'])
        decided = utc(command['decided_at'])
        earliest = max(observed + latency, decided + order_latency)
        at = utc(command['arrival_at']) if command.get('arrival_at') else earliest
        if decided < observed or at < earliest or observed < start or at > end:
            raise ValueError('command violates declared latency or interval')
        if command['kind'] == 'post':
            if command['id'] in post_arrivals:
                raise ValueError('duplicate submitted order identity')
            post_arrivals[command['id']] = at
            expiry = utc(command['expires_at'])
            if expiry <= at:
                raise ValueError('order expires before arrival')
            if expiry <= end:
                schedule.append((expiry, -1, i, {'kind': 'expiry', 'id': command['id']}))
        else:
            cancels.append((command['id'], at))
        schedule.append((at, 3 if command['kind'] == 'cancel' else 4, i, command))
    if any(oid not in post_arrivals or at < post_arrivals[oid] for oid, at in cancels):
        raise ValueError('cancel precedes or lacks its submitted order')
    schedule.append((end, 9, 0, {'kind': 'end'}))

    def accrue(left, right):
        for cid in conditions:
            resting = [r for r in active.values() if r['condition_id'] == cid and r['remaining'] > ZERO]
            if not resting:
                continue
            book, term = books.get(cid), terms.get(cid)
            if book is None or term is None:
                reasons.add('missing_book_or_terms')
                continue
            safe_end = min(right, utc(book['observed_at']) + timedelta(seconds=float(max_age)), utc(term['valid_until']))
            if safe_end < right:
                reasons.add('capture_or_terms_gap')
            if safe_end <= left:
                continue
            try:
                share = reward_share(book, resting, term, config.competition_rule)
            except ValueError as exc:
                reasons.add(str(exc))
                continue
            duration = D(str((safe_end - left).total_seconds()))
            day = left.date().isoformat()
            if safe_end.date() != left.date() and safe_end.time().isoformat() != '00:00:00':
                raise ValueError('split reward interval at UTC day boundary')
            if config.reward_epoch_rule == 'full_day_upper_bound':
                active_seconds = D(86400)
            else:
                epoch = payload.get('reward_epochs', {}).get(day, {}).get(cid)
                if epoch is None:
                    reasons.add('missing_reward_epoch')
                    continue
                if epoch['complete'] is not True:
                    raise ValueError('incomplete reward epoch denominator')
                source_hash(epoch['source_sha256'])
                active_seconds = number(epoch['active_seconds'], minimum=D('.000001'), maximum=D(86400))
            if share > ZERO:
                rewarded_seconds[(cid, day)] += duration
                if rewarded_seconds[(cid, day)] > active_seconds:
                    raise ValueError('reward epoch shorter than own eligible duration')
            rewards[(cid, day)] += share * number(term['rate_per_day']) * duration / active_seconds

    previous, session_closed = start, False
    for at, _, _, event in sorted(schedule, key=lambda x: x[:3]):
        if at < previous:
            raise ValueError('replay clock regressed')
        accrue(previous, at)
        previous = at
        kind = event['kind']
        if kind == 'end':
            break
        if kind == 'boundary':
            continue
        if kind == 'session_close':
            for order in active.values():
                used[order['condition_id']] -= order['price'] * order['remaining']
            active.clear()
            session_closed = True
            continue
        if kind in ('cancel', 'expiry'):
            order = active.pop(event['id'], None)
            if order:
                used[order['condition_id']] -= order['price'] * order['remaining']
            continue
        cid = event['condition_id']
        if kind == 'book':
            # A late snapshot is a valid capture but may be unusable for a
            # quote. Freshness is applied at use, not hidden by its receipt time.
            observed_age = D(str((at - utc(event['observed_at'])).total_seconds()))
            book_valid(event, now=at, max_age=max(max_age, observed_age))
            books[cid] = event
        elif kind == 'terms':
            if (utc(event['valid_until']) <= at or not event['source_sha256']
                    or event.get('substitute_rule') not in (None, 'none')):
                raise ValueError('terms missing provenance or undeclared substitute')
            number(event['rate_per_day'])
            number(event['min_size'], minimum=D('.000001'))
            number(event['max_spread_cents'], minimum=D('.000001'))
            terms[cid] = event
        elif kind == 'post':
            if session_closed:
                rejected.append({'id': event['id'], 'reason': 'session_closed'})
                continue
            if event['id'] in orders or cid in settled:
                raise ValueError('duplicate order or already settled market')
            outcome = event['outcome']
            if outcome not in ('YES', 'NO'):
                raise ValueError('invalid outcome')
            p, size = number(event['price'], maximum=ONE), number(event['size'])
            book = books.get(cid)
            if book is None:
                reasons.add('missing_arrival_book')
                rejected.append({'id': event['id'], 'reason': 'missing_arrival_book'})
                continue
            try:
                book_valid(book, now=at, max_age=max_age)
            except ValueError:
                reasons.add('stale_arrival_book')
                rejected.append({'id': event['id'], 'reason': 'stale_arrival_book'})
                continue
            if (not ZERO < p < ONE or p % number(book[outcome]['tick'])
                    or size < number(book[outcome]['min_order_size'])):
                rejected.append({'id': event['id'], 'reason': 'arrival_market_rules'})
                continue
            if p >= min(r['price'] for r in levels(book[outcome]['asks'])):
                rejected.append({'id': event['id'], 'reason': 'post_only_cross'})
                continue
            reserve = p * size
            resting_cash = sum((r['price'] * r['remaining'] for r in active.values()), ZERO)
            funding_cash = number(config.total_cap) - spent + cash_paid
            if (used[cid] + reserve > number(config.per_market_cap)
                    or sum(used.values(), ZERO) + reserve > number(config.total_cap)
                    or resting_cash + reserve > funding_cash):
                rejected.append({'id': event['id'], 'reason': 'capital_cap'})
                continue
            if any(r['condition_id'] == cid and r['outcome'] == outcome for r in active.values()):
                rejected.append({'id': event['id'], 'reason': 'one_order_per_outcome'})
                continue
            # Better prices execute first, then every displayed share at our price.
            # No cancellation credit, and no reset when later snapshots shrink.
            ahead = sum((r['size'] for r in levels(book[outcome]['bids']) if r['price'] >= p), ZERO)
            order = {**event, 'price': p, 'size': size, 'remaining': size, 'queue_ahead': ahead, 'at': at}
            orders[event['id']] = order
            active[event['id']] = order
            used[cid] += reserve
        elif kind == 'trade':
            if event['outcome'] not in ('YES', 'NO') or event['aggressor'] not in ('BUY', 'SELL'):
                raise ValueError('unknown trade side or outcome')
            p, volume = number(event['price'], maximum=ONE), number(event['size'])
            if p <= ZERO or p >= ONE or volume <= ZERO:
                raise ValueError('invalid trade')
            if event['aggressor'] != 'SELL':
                continue
            candidates = sorted((r for r in active.values() if r['condition_id'] == cid
                                 and r['outcome'] == event['outcome'] and p <= r['price']),
                                key=lambda r: (-r['price'], r['at'], r['id']))
            # T1 permits one live order per native outcome. A physical print
            # therefore never supplies residual volume to multiple own orders.
            for order in candidates:
                consumed = min(volume, order['queue_ahead'])
                order['queue_ahead'] -= consumed
                executable = volume - consumed
                if config.queue_rule == 'back_strict_through' and p == order['price']:
                    continue
                quantity = min(order['remaining'], executable)
                if quantity <= ZERO:
                    continue
                order['remaining'] -= quantity
                cost = quantity * order['price']
                spent += cost
                weight = fee(quantity, order['price'], config.fee_coefficient)
                rebate_weight[at.date().isoformat()] += weight
                reference_mid = None
                current = books.get(cid)
                try:
                    if current is None:
                        raise ValueError('missing fill book')
                    book_valid(current, now=at, max_age=max_age)
                    side = current[order['outcome']]
                    reference_mid = (max(r['price'] for r in levels(side['bids']))
                                     + min(r['price'] for r in levels(side['asks']))) / 2
                except ValueError:
                    reasons.add('missing_fill_reference_mid')
                fills.append({'order_id': order['id'], 'condition_id': cid, 'outcome': order['outcome'],
                              'at': at, 'trade_id': event['id'], 'price': order['price'], 'size': quantity,
                              'fee_weight': weight, 'maker_fee': ZERO, 'entry_mid': reference_mid})
                if order['remaining'] == ZERO:
                    active.pop(order['id'])
        elif kind == 'settlement':
            if cid in settled or event['source'] != 'venue' or not event['source_sha256']:
                raise ValueError('unverified or duplicate venue settlement')
            payout = number(event['yes_payout'], maximum=ONE)
            if any(r['condition_id'] == cid for r in active.values()):
                reasons.add('orders_open_at_settlement')
            value = sum((r['size'] * (payout if r['outcome'] == 'YES' else ONE - payout)
                         for r in fills if r['condition_id'] == cid), ZERO)
            payouts += value
            settlement_values[cid] = value
            used[cid] = ZERO
            active = {oid: r for oid, r in active.items() if r['condition_id'] != cid}
            settled.add(cid)
        elif kind == 'redemption':
            fraction = number(event['fraction'], maximum=ONE)
            if cid not in settled or event['source'] != 'venue' or redeemed[cid] + fraction > ONE:
                raise ValueError('unsettled or duplicate cash redemption')
            redeemed[cid] += fraction
            cash_paid += settlement_values[cid] * fraction
    if any(r['condition_id'] not in settled for r in fills):
        reasons.add('unsettled_inventory')
    if active:
        reasons.add('open_orders_at_end')
    # Markouts use the first captured two-sided book at/after the fixed horizon.
    # They are diagnostics, never available to quoting or fill decisions.
    for fill in fills:
        due = fill['at'] + timedelta(seconds=config.markout_seconds)
        marks = sorted((e for e in payload['events'] if e['kind'] == 'book'
                        and e['condition_id'] == fill['condition_id'] and utc(e['observed_at']) >= due),
                       key=lambda e: utc(e['at']))
        if not marks or D(str((utc(marks[0]['at']) - due).total_seconds())) > number(config.mark_max_delay_seconds):
            fill['markout_per_share'] = None
            reasons.add('missing_markout')
        else:
            side = marks[0][fill['outcome']]
            mid = (max(r['price'] for r in levels(side['bids']))
                   + min(r['price'] for r in levels(side['asks']))) / 2
            fill['markout_per_share'] = mid - fill['price']
    rebates = ZERO
    rebate_paid = ZERO
    for day, weight in rebate_weight.items():
        pool = payload.get('rebate_pools', {}).get(day)
        if pool is None:
            reasons.add('missing_rebate_pool')
            continue
        if pool['category'] != 'weather' or not pool['source_sha256'] or pool['complete'] is not True:
            raise ValueError('incomplete rebate pool')
        source_hash(pool['source_sha256'])
        denominator = number(pool['total_maker_fee_weight'])
        fees = number(pool['total_taker_fees'])
        if denominator <= ZERO or weight > denominator:
            raise ValueError('invalid rebate denominator')
        daily_rebate = number(config.rebate_fraction) * fees * weight / denominator
        rebates += daily_rebate
        outside_rebate = number(external.get(day, {}).get('rebate_accrued', '0'))
        rebate_paid += daily_rebate if daily_rebate + outside_rebate >= ONE else ZERO
    reward_total = sum(rewards.values(), ZERO)
    daily_rewards = defaultdict(lambda: ZERO)
    for (_, day), amount in rewards.items():
        daily_rewards[day] += amount
    reward_paid = sum((r for day, r in daily_rewards.items()
                       if r + number(external.get(day, {}).get('reward_accrued', '0')) >= ONE), ZERO)
    raw_pnl = payouts - spent + reward_paid + rebate_paid
    # This reserve is a proposed incremental adverse-selection stress, not a
    # different venue outcome or a claim to have identified informed traders.
    stress = number(config.informed_fraction) * spent
    references_complete = all(r['entry_mid'] is not None for r in fills)
    reference_value = sum((r['entry_mid'] * r['size'] for r in fills), ZERO) if references_complete else None
    return {'config': config.projection(), 'config_sha256': digest(config.projection()),
            'conditions': deepcopy(conditions),
            'input_sha256': digest(payload), 'fills': fills, 'rejected': rejected,
            'source_hashes': sorted({e['source_sha256'] for e in payload['events']}
                                    | {p['source_sha256'] for p in payload.get('rebate_pools', {}).values()}
                                    | {p['source_sha256'] for day in payload.get('reward_epochs', {}).values()
                                       for p in day.values()} | {p['source_sha256'] for p in external.values()}),
            'rewards': [{'condition_id': cid, 'day': day, 'accrued': amount}
                        for (cid, day), amount in sorted(rewards.items())],
            'reward_accrued': reward_total, 'rebate_accrued': rebates,
            'reward_payable': reward_paid, 'rebate_payable': rebate_paid,
            'cost': spent, 'venue_payout': payouts, 'raw_net_pnl': raw_pnl,
            'cash_redemptions_pusd': cash_paid, 'unredeemed_venue_value': payouts - cash_paid,
            'cash_available': number(config.total_cap) - spent + cash_paid,
            'spread_capture_pusd': reference_value - spent if references_complete else None,
            'inventory_move_pusd': payouts - reference_value if references_complete else None,
            'maker_fees_pusd': ZERO,
            'informed_stress_cost': stress, 'stressed_net_pnl': raw_pnl - stress,
            'stress_rule': 'incremental_fill_cost_reserve', 'f_identification': 'NOT_ESTIMATED',
            'competition_estimate': config.competition_rule,
            'reward_epoch_rule': config.reward_epoch_rule,
            'competition_response': 'CONDITIONAL_ON_CAPTURED_BOOK_ONLY',
            'qualification': 'ACCURACY_GATE_REQUIRED' if not reasons else 'INCOMPLETE',
            'reasons': sorted(reasons), 'trial_can_pass': False}
