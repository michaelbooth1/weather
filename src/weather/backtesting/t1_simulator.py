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
from weather.backtesting.t1_accounting import predicted_positions
from weather.backtesting.t1_types import (ONE, ZERO, ReplayConfig, book_valid, decimal_context, digest,
                                         fee, levels, lineage_hashes, number, source_hash, utc)


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
    if payload.get('policy') is not None:
        from weather.backtesting.t1_policy import asof_commands

        commands = asof_commands([e for e in payload['events'] if e['kind'] == 'book'], payload['policy'],
                                 start=payload['start'], end=payload['end'], max_age=config.max_book_age_seconds)
        if payload.get('commands') and payload['commands'] != commands:
            raise ValueError('command stream differs from the deterministic as-of policy')
        payload = {**payload, 'commands': commands}
    start, end = utc(payload['start']), utc(payload['end'])
    if start >= end:
        raise ValueError('invalid replay interval')
    if payload.get('opening_state') != 'flat':
        raise ValueError('explicit flat opening state required; inventory state carry is unsupported')
    conditions = payload['conditions']
    opening_cash = number(payload.get('opening_cash', config.total_cap))
    operating_cost = number(payload.get('operating_cost', '0'))
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
    settlement_values, settled_fractions, redeemed = {}, {}, defaultdict(lambda: ZERO)
    redemption_quantities = defaultdict(lambda: defaultdict(lambda: ZERO))
    redemption_ids, checkpoints, sampled_minutes = set(), {}, set()
    transitions, fill_ordinals = {}, defaultdict(int)
    observed_cashflows = ZERO
    accounting_end = utc(payload.get('accounting_end', payload['end']))
    if accounting_end < end:
        raise ValueError('accounting follow-up precedes session end')

    def state(at):
        holdings = {}
        for condition, meta in conditions.items():
            _, holdings[condition] = predicted_positions(
                [f for f in fills if f['condition_id'] == condition], meta['token_ids'], redemption_quantities[condition])
        return {'at': at, 'cash': opening_cash - spent + cash_paid + observed_cashflows,
                'reserved': sum((r['price'] * r['remaining'] for r in active.values()), ZERO),
                'cost_at_risk': sum(used.values(), ZERO), 'positions': holdings}

    def emit(key, at):
        if key in transitions:
            raise ValueError('duplicate economic transition identity')
        transitions[key] = state(at)

    emit('opening', start)
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
    for i, checkpoint in enumerate(payload.get('checkpoints', [])):
        checkpoint_at = utc(checkpoint['at'])
        if not start <= checkpoint_at <= accounting_end:
            raise ValueError('checkpoint outside capital period')
        schedule.append((checkpoint_at, 8, i, {'kind': 'checkpoint', **checkpoint}))
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
    sample_denominators, sample_counts = {}, defaultdict(int)
    for i, event in enumerate(payload['events']):
        event = deepcopy(event)
        source_hash(event['source_sha256'])
        cid = event['condition_id']
        if cid not in conditions:
            raise ValueError('unknown condition')
        available = utc(event['at'])
        at = utc(event['traded_at']) if event['kind'] == 'trade' else available
        if event['kind'] == 'reward_sample':
            count = number(event['epoch_active_sample_count'], minimum=ONE, maximum=D(1440))
            if count != count.to_integral_value():
                raise ValueError('reward sample denominator must be an integer')
            sample_key = (cid, at.date())
            if sample_key in sample_denominators and sample_denominators[sample_key] != count:
                raise ValueError('inconsistent condition-day sample denominator')
            sample_denominators[sample_key] = count
            sample_counts[sample_key] += 1
            if sample_counts[sample_key] > count:
                raise ValueError('observed samples exceed condition-day denominator')
        if event['kind'] == 'trade':
            if at > available:
                raise ValueError('trade precedes availability incorrectly')
            finality = event.get('status', 'UNKNOWN')
            route = event.get('execution_route', 'UNKNOWN')
            if finality == 'FAILED':
                continue
            if finality != 'CONFIRMED' or route == 'UNKNOWN' or not event.get('consumption_id'):
                reasons.add('unqualified_public_execution_route_identity_or_finality')
            if finality != 'CONFIRMED':
                continue  # a later confirmed update must still be eligible to supply settled flow
            if route == 'complementary_mint':
                if event['aggressor'] != 'BUY':
                    raise ValueError('complementary mint must retain the original BUY representation')
                source_hash(event['route_source_sha256'])
                event.update(outcome='NO' if event['outcome'] == 'YES' else 'YES',
                             aggressor='SELL', price=ONE - number(event['price'], maximum=ONE))
            elif route not in ('native_sell', 'not_buy_liquidity', 'UNKNOWN'):
                raise ValueError('unsupported execution route')
            if route == 'native_sell' and event['aggressor'] != 'SELL':
                raise ValueError('native SELL route disagrees with aggressor')
            key = (cid, event.get('consumption_id', event['id']))
            if key in trade_ids:
                prior = trade_ids[key]
                economic_keys = ('traded_at', 'outcome', 'aggressor')
                if (any(prior[k] != event[k] for k in economic_keys)
                        or number(prior['price']) != number(event['price'])
                        or number(prior['size']) != number(event['size'])):
                    raise ValueError('conflicting duplicate trade')
                continue
            trade_ids[key] = event
        priority = {'book': 0, 'terms': 1, 'trade': 2, 'reward_sample': 5, 'settlement': 6, 'redemption': 7, 'cashflow': 7}.get(event['kind'])
        if priority is None:
            raise ValueError('unknown event kind')
        bound = accounting_end if event['kind'] in ('cashflow', 'settlement', 'redemption') else end
        if at < start or at > bound:
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
        transport = timedelta(seconds=float(number(config.cancel_latency_seconds))) if command['kind'] == 'cancel' else order_latency
        earliest = max(observed + latency, decided + transport) if command['kind'] == 'post' else decided + transport
        if payload.get('replay_mode') == 'receipt':
            earliest = decided
            if not command.get('arrival_at'):
                raise ValueError('receipt replay requires an observed acknowledgment')
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
    schedule.append((accounting_end, 9, 0, {'kind': 'end'}))

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
                share = reward_share(book, resting, term, config.competition_rule, config.midpoint_rule)
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
            if payload.get('reward_realization') != 'observed_samples':
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
        if kind == 'checkpoint':
            if event['id'] in checkpoints:
                raise ValueError('duplicate accounting checkpoint')
            checkpoints[event['id']] = state(at)
            continue
        if kind == 'session_close':
            for order in active.values():
                used[order['condition_id']] -= order['price'] * order['remaining']
            active.clear()
            session_closed = True
            emit('terminal', at)
            continue
        if kind in ('cancel', 'expiry'):
            order = active.pop(event['id'], None)
            if order:
                used[order['condition_id']] -= order['price'] * order['remaining']
            emit(kind + ':' + event['id'], at)
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
            if book.get('accepting_orders') is not True:
                rejected.append({'id': event['id'], 'reason': 'market_not_accepting_orders'})
                if 'accepting_orders' not in book or book.get('acceptance_state_known') is False:
                    reasons.add('missing_market_acceptance_state')
                continue
            other = 'NO' if outcome == 'YES' else 'YES'
            opposite = [r['price'] for r in active.values() if r['condition_id'] == cid and r['outcome'] == other]
            if opposite and p + max(opposite) >= ONE:
                rejected.append({'id': event['id'], 'reason': 'own_post_only_cross'})
                continue
            asks = [r['price'] for r in levels(book[outcome]['asks'])] + [ONE - v for v in opposite]
            if not asks:
                reasons.add('missing_executable_ask')
                rejected.append({'id': event['id'], 'reason': 'missing_executable_ask'})
                continue
            if p >= min(asks):
                rejected.append({'id': event['id'], 'reason': 'post_only_cross'})
                continue
            reserve = p * size
            resting_cash = sum((r['price'] * r['remaining'] for r in active.values()), ZERO)
            funding_cash = opening_cash - spent + cash_paid - operating_cost
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
            ahead = defaultdict(lambda: ZERO)
            for row in levels(book[outcome]['bids']):
                if row['price'] >= p:
                    ahead[row['price']] += row['size']
            order = {**event, 'price': p, 'size': size, 'remaining': size,
                     'queue_ahead_levels': ahead, 'at': at,
                     'queue_ahead_ids': {r['order_id'] for r in book.get('reward_orders', [])
                                         if r['outcome'] == outcome and r['side'] == 'BUY' and number(r['price']) >= p}}
            orders[event['id']] = order
            active[event['id']] = order
            used[cid] += reserve
            emit('post:' + event['id'], at)
        elif kind == 'trade':
            if event['outcome'] not in ('YES', 'NO') or event['aggressor'] not in ('BUY', 'SELL'):
                raise ValueError('unknown trade side or outcome')
            p, volume = number(event['price'], maximum=ONE), number(event['size'])
            if p <= ZERO or p >= ONE or volume <= ZERO:
                raise ValueError('invalid trade')
            if event['aggressor'] != 'SELL':
                continue
            candidates = sorted((r for r in active.values() if r['condition_id'] == cid
                                 and r['outcome'] == event['outcome']),
                                key=lambda r: (-r['price'], r['at'], r['id']))
            # T1 permits one live order per native outcome. A physical print
            # therefore never supplies residual volume to multiple own orders.
            own_consumed = ZERO
            for order in candidates:
                executable = volume
                # Better-price prints retire their actual price levels too.
                # A lower-price sweep retires all represented preceding depth.
                for price in sorted(order['queue_ahead_levels'], reverse=True):
                    if price < p:
                        continue
                    consumed = min(executable, order['queue_ahead_levels'][price])
                    order['queue_ahead_levels'][price] -= consumed
                    executable -= consumed
                if p > order['price']:
                    continue
                if config.queue_rule == 'back_strict_through' and p == order['price']:
                    continue
                quantity = min(order['remaining'], executable)
                if quantity <= ZERO:
                    continue
                own_consumed += quantity
                pre_fill_remaining = order['remaining']
                order['remaining'] -= quantity
                cost = quantity * order['price']
                spent += cost
                weight = fee(quantity, order['price'], config.fee_coefficient, config.fee_rounding_rule)
                rebate_weight[(cid, at.date().isoformat())] += weight
                reference_mid = None
                current = books.get(cid)
                try:
                    if current is None:
                        raise ValueError('missing fill book')
                    book_valid(current, now=at, max_age=max_age)
                    side = current[order['outcome']]
                    bids = [r['price'] for r in levels(side['bids'])]
                    if pre_fill_remaining:
                        bids.append(order['price'])
                    other = 'NO' if order['outcome'] == 'YES' else 'YES'
                    asks = [r['price'] for r in levels(side['asks'])] + [ONE - r['price'] for r in active.values()
                             if r['condition_id'] == cid and r['outcome'] == other and r['remaining'] > ZERO]
                    reference_mid = (max(bids) + min(asks)) / 2
                except ValueError:
                    reasons.add('missing_fill_reference_mid')
                fills.append({'order_id': order['id'], 'condition_id': cid, 'outcome': order['outcome'],
                              'at': at, 'trade_id': event['id'], 'price': order['price'], 'size': quantity,
                              'fee_weight': weight, 'maker_fee': ZERO, 'entry_mid': reference_mid})
                if order['remaining'] == ZERO:
                    active.pop(order['id'])
                fill_ordinals[order['id']] += 1
                emit(f"fill:{order['id']}:{fill_ordinals[order['id']]}", at)
            # Keep the captured external book coherent until its next snapshot;
            # a cancel/repost must not rebuild queue from already consumed depth.
            current = books.get(cid)
            if current is not None:
                current = deepcopy(current)
                external_volume = volume - own_consumed
                ahead_ids = set().union(*(r['queue_ahead_ids'] for r in candidates)) if candidates else set()
                other = 'NO' if event['outcome'] == 'YES' else 'YES'
                for outcome, side, threshold in ((event['outcome'], 'bids', p), (other, 'asks', ONE - p)):
                    remaining = external_volume
                    rows = sorted(current[outcome][side], key=lambda r: number(r['price']), reverse=side == 'bids')
                    for row in rows:
                        price = number(row['price'])
                        if (side == 'bids' and price >= threshold) or (side == 'asks' and price <= threshold):
                            consumed = min(remaining, number(row['size']))
                            row['size'] = number(row['size']) - consumed
                            remaining -= consumed
                    current[outcome][side] = [r for r in rows if number(r['size']) > ZERO]
                    if remaining:
                        reasons.add('external_consumption_exceeds_displayed_depth')
                if current.get('reward_orders_complete'):
                    remaining = external_volume
                    eligible = sorted((r for r in current['reward_orders']
                                       if r['outcome'] == event['outcome'] and r['side'] == 'BUY'
                                       and number(r['price']) >= p),
                                      key=lambda r: (-number(r['price']), r['order_id'] not in ahead_ids,
                                                     r.get('arrived_at', ''), r['order_id']))
                    cohorts = defaultdict(list)
                    for row in eligible:
                        cohorts[(number(row['price']), row['order_id'] in ahead_ids)].append(row)
                    frontier = remaining
                    for cohort in cohorts.values():
                        total = sum((number(r['size']) for r in cohort), ZERO)
                        if ZERO < frontier < total and len(cohort) > 1 and not all(r.get('arrived_at') for r in cohort):
                            reasons.add('unidentified_competitor_queue_assignment')
                        frontier = max(ZERO, frontier - total)
                    for row in eligible:
                        consumed = min(remaining, number(row['size']))
                        row['size'] = number(row['size']) - consumed
                        remaining -= consumed
                    current['reward_orders'] = [r for r in current['reward_orders'] if number(r['size']) > ZERO]
                current['competitor_only'] = True
                books[cid] = current
        elif kind == 'reward_sample':
            if payload.get('reward_realization') != 'observed_samples':
                raise ValueError('sample evidence supplied without realized reward mode')
            book, term = books.get(cid), terms.get(cid)
            resting = [r for r in active.values() if r['condition_id'] == cid]
            if book is None or term is None:
                reasons.add('missing_reward_sample_inputs')
                continue
            book_valid(book, now=at, max_age=max_age)
            if at >= utc(term['valid_until']):
                reasons.add('stale_reward_sample_terms')
                continue
            count = number(event['epoch_active_sample_count'], minimum=ONE, maximum=D(1440))
            if count != count.to_integral_value():
                raise ValueError('reward sample denominator must be an integer')
            sample_key = (cid, at.replace(second=0, microsecond=0))
            if sample_key in sampled_minutes:
                raise ValueError('duplicate reward sample minute')
            sampled_minutes.add(sample_key)
            rewards[(cid, at.date().isoformat())] += reward_share(
                book, resting, term, config.competition_rule, config.midpoint_rule) * number(term['rate_per_day']) / count
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
            settled_fractions[cid] = payout
            used[cid] = ZERO
            active = {oid: r for oid, r in active.items() if r['condition_id'] != cid}
            settled.add(cid)
            emit('settlement:' + cid, at)
        elif kind == 'redemption':
            if cid not in settled or event['source'] != 'venue' or event.get('id') and event['id'] in redemption_ids:
                raise ValueError('unsettled or duplicate cash redemption')
            tokens = conditions[cid]['token_ids']
            bought, _ = predicted_positions([f for f in fills if f['condition_id'] == cid], tokens, ZERO)
            if 'tokens' in event:
                if set(event['tokens']) != set(tokens):
                    raise ValueError('redemption requires both token quantities')
                quantities = {t: number(event['tokens'][t]) for t in tokens}
            else:
                fraction = number(event['fraction'], maximum=ONE)
                if redeemed[cid] + fraction > ONE:
                    raise ValueError('unsettled or duplicate cash redemption')
                redeemed[cid] += fraction
                quantities = {t: bought[t] * fraction for t in tokens}
            for t in tokens:
                redemption_quantities[cid][t] += quantities[t]
                if redemption_quantities[cid][t] > bought[t]:
                    raise ValueError('duplicate cash redemption exceeds held tokens')
            cash_paid += sum((quantities[t] * (settled_fractions[cid] if i == 0 else ONE - settled_fractions[cid])
                              for i, t in enumerate(tokens)), ZERO)
            if event.get('id'):
                redemption_ids.add(event['id'])
                emit('redemption:' + event['id'], at)
        elif kind == 'cashflow':
            if event['flow_kind'] not in ('REWARD', 'REBATE', 'EXTERNAL', 'MAKER_FEE', 'OPERATING_COST'):
                raise ValueError('unsupported cashflow kind')
            observed_cashflows += number(event['amount'], minimum=None)
            emit('cash:' + event['id'], at)
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
    daily_rebates = defaultdict(lambda: ZERO)
    rebate_scope_qualified = True
    for day, pool in payload.get('rebate_pools', {}).items():
        category = pool.get('category_totals')
        if category is not None:
            if category['complete'] is not True or not pool.get('conditions'):
                raise ValueError('incomplete rebate category reconciliation')
            source_hash(category['source_sha256'])
            for key in ('total_taker_fees', 'total_maker_fee_weight'):
                if sum((number(p[key]) for p in pool['conditions'].values()), ZERO) != number(category[key]):
                    raise ValueError('condition rebate pools do not reconcile to category aggregates')
    for (cid, day), weight in rebate_weight.items():
        day_pool = payload.get('rebate_pools', {}).get(day)
        pool = day_pool.get('conditions', {}).get(cid) if day_pool and 'conditions' in day_pool else day_pool
        if pool is None:
            reasons.add('missing_rebate_pool')
            continue
        if pool.get('category', 'weather') != 'weather' or not pool['source_sha256'] or pool['complete'] is not True:
            raise ValueError('incomplete rebate pool')
        source_hash(pool['source_sha256'])
        denominator = number(pool['total_maker_fee_weight'])
        fees = number(pool['total_taker_fees'])
        if denominator <= ZERO or weight > denominator:
            raise ValueError('invalid rebate denominator')
        if pool.get('condition_id') != cid or pool.get('eligible') is not True:
            rebate_scope_qualified = False
        if pool.get('eligible') is False:
            raise ValueError('captured condition is not eligible for weather maker rebates')
        if 'fee_coefficient' in pool and number(pool['fee_coefficient']) != number(config.fee_coefficient):
            raise ValueError('captured condition fee schedule differs from config')
        if 'rebate_fraction' in pool and number(pool['rebate_fraction']) != number(config.rebate_fraction):
            raise ValueError('captured rebate allocation differs from config')
        day_start = utc(day + 'T00:00:00Z')
        if (pool.get('fee_coefficient') is None or pool.get('rebate_fraction') is None
                or pool.get('valid_from') is None or pool.get('valid_until') is None):
            rebate_scope_qualified = False
        elif not utc(pool['valid_from']) <= day_start < day_start + timedelta(days=1) <= utc(pool['valid_until']):
            raise ValueError('captured rebate economics do not cover the earned day')
        daily_rebate = number(config.rebate_fraction) * fees * weight / denominator
        rebates += daily_rebate
        daily_rebates[day] += daily_rebate
    for day, daily_rebate in daily_rebates.items():
        outside_rebate = number(external.get(day, {}).get('rebate_accrued', '0'))
        rebate_paid += daily_rebate if daily_rebate + outside_rebate >= ONE else ZERO
    reward_total = sum(rewards.values(), ZERO)
    daily_rewards = defaultdict(lambda: ZERO)
    for (_, day), amount in rewards.items():
        daily_rewards[day] += amount
    reward_paid = sum((r for day, r in daily_rewards.items()
                       if payload.get('reward_payment_rule') == 'campaign_day'
                       or r + number(external.get(day, {}).get('reward_accrued', '0')) >= ONE), ZERO)
    raw_pnl = payouts - spent + reward_paid + rebate_paid - operating_cost
    # This reserve is a proposed incremental adverse-selection stress, not a
    # different venue outcome or a claim to have identified informed traders.
    stress = number(config.informed_fraction) * spent
    references_complete = all(r['entry_mid'] is not None for r in fills)
    reference_value = sum((r['entry_mid'] * r['size'] for r in fills), ZERO) if references_complete else None
    terminal_positions, end_positions = {}, {}
    for cid, meta in conditions.items():
        terminal_positions[cid], end_positions[cid] = predicted_positions(
            [f for f in fills if f['condition_id'] == cid], meta['token_ids'], redemption_quantities[cid])
    return {'config': config.projection(), 'config_sha256': digest(config.projection()),
            'conditions': deepcopy(conditions),
            'input_sha256': digest(payload), 'fills': fills, 'rejected': rejected,
            'decision_trace': deepcopy(payload['commands']),
            'policy_qualification': ('ASOF_POLICY_REQUIRES_FREEZE' if payload.get('policy') else
                                     'EXTERNAL_JOURNAL_TRACE_ONLY' if payload.get('replay_mode') == 'receipt' else 'NOT QUALIFIED'),
            'source_hashes': sorted(lineage_hashes(payload)),
            'rewards': [{'condition_id': cid, 'day': day, 'accrued': amount}
                        for (cid, day), amount in sorted(rewards.items())],
            'reward_accrued': reward_total, 'rebate_accrued': rebates,
            'reward_payable': reward_paid, 'rebate_payable': rebate_paid,
            'cost': spent, 'venue_payout': payouts, 'raw_net_pnl': raw_pnl,
            'economic_net_pnl': raw_pnl,
            'cash_net_pnl': cash_paid - spent + reward_paid + rebate_paid - operating_cost,
            'cash_redemptions_pusd': cash_paid, 'unredeemed_venue_value': payouts - cash_paid,
            'cash_available': opening_cash - spent + cash_paid - operating_cost,
            'wallet_end_cash': opening_cash - spent + cash_paid + reward_paid + rebate_paid - operating_cost,
            'terminal_positions': terminal_positions, 'end_positions': end_positions,
            'checkpoints': checkpoints,
            'transitions': transitions,
            'operating_cost': operating_cost,
            'spread_capture_pusd': reference_value - spent if references_complete else None,
            'inventory_move_pusd': payouts - reference_value if references_complete else None,
            'maker_fees_pusd': ZERO,
            'cost_reserve': stress, 'cost_reserve_fraction': number(config.informed_fraction),
            'informed_stress_cost': stress, 'stressed_net_pnl': raw_pnl - stress,
            'stress_rule': 'incremental_fill_cost_reserve', 'f_identification': 'NOT_ESTIMATED',
            'competition_estimate': config.competition_rule,
            'reward_epoch_rule': config.reward_epoch_rule,
            'reward_realization': payload.get('reward_realization', 'CONTINUOUS_EXPECTATION_DIAGNOSTIC'),
            'reward_payment_rule': payload.get('reward_payment_rule', 'zero_credit_below_account_day_threshold_no_assumed_carry'),
            'reward_sampling_qualification': 'RETAINED_SAMPLES_REQUIRE_RAW_PROOF' if payload.get('reward_realization') == 'observed_samples' else 'NOT QUALIFIED',
            'midpoint_qualification': 'NOT QUALIFIED',
            'midpoint_evidence_required': 'Dated authoritative rule or controlled fragmented-depth comparison, bound in the receipt certificate',
            'rebate_scope_qualification': 'CONDITION_DAY_REQUIRES_RAW_PROOF' if rebate_scope_qualified else 'NOT QUALIFIED',
            'rebate_rounding_rule': config.fee_rounding_rule,
            'rebate_precision_qualification': 'NOT QUALIFIED',
            'rebate_precision_evidence_required': 'Dated per-match rounding and actual payment/carry receipts',
            'incentive_cash_policy': 'NO_UNVERIFIED_CARRY_CREDIT_OR_INCENTIVE_REINVESTMENT',
            'rebate_paid_lower_bound': ZERO,
            'competition_response': 'CONDITIONAL_ON_CAPTURED_BOOK_ONLY',
            'passive_competition_qualification': 'NOT QUALIFIED',
            'passive_incentive_lower_bound': ZERO,
            'competition_evidence_required': 'Validated posting-response intervention/envelope; public passive data does not identify causality',
            'fill_path_claim': 'NO_PNL_ORDERING_FROM_FEWER_FILLS',
            'all_posted_lots_loss_floor': -sum((number(r['price']) * number(r['size']) for r in payload['commands'] if r['kind'] == 'post'), ZERO) - operating_cost,
            'loss_floor_rule': 'Every commanded posted lot fills fully and loses; zero incentives; fixed command trace only',
            'qualification': 'ACCURACY_GATE_REQUIRED' if not reasons else 'INCOMPLETE',
            'reasons': sorted(reasons), 'trial_can_pass': False}
