"""Reproducible F2 selection: F0 public filters, configured quote, one per city.

Predicted rewards rank candidates only. They are never a ledger cash credit.
The retained public table is rechecked; current-clock horizon and money checks
also run at every actual placement/requote through F2Band.
"""
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
import json
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from weather.market import lfc_constants as C
from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import native
from weather.market.lfc_fees import maker_fee_refusal
from weather.market.lfc_horizon import horizon_allowed
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import SCHEMA_VERSION, digest, utc
from weather.market.mm_stage2_selection import reward_rate
from weather.market.reward_quote import QuoteRefused, _levels, price_sized_reward_quote, reward_rate_eligible


DERIVED = {'eligible', 'refusal', 'quote', 'predicted_360_minutes', 'trade_legs'}


def trade_legs(policy, mid):
    tokens = policy.raw['tokens']
    if tokens == ['YES', 'NO']:
        return (0, 1)
    if tokens == ['YES']:
        return (0,)
    if tokens == ['NO']:
        return (1,)
    if tokens == ['CHEAP']:
        return (0,) if quantity(mid) <= Decimal('.5') else (1,)
    raise QuoteRefused('unsupported_tokens')


def check_book(inputs, *, mid, size, share, policy):
    """The same campaign eligibility on selection and each fresh hold/POST read."""
    if not reward_rate_eligible(inputs['reward_rate_per_day'], policy.raw['min_reward_rate']):
        raise QuoteRefused('reward_rate_or_terms')
    if quantity(inputs['reward_max_spread_cents']) < 3:
        raise QuoteRefused('reward_rate_or_terms')
    mid, size = quantity(mid), quantity(size)
    if not quantity('.20') <= mid <= quantity('.80'):
        raise QuoteRefused('midpoint_outside_treatment')
    low, high = map(quantity, policy.raw['share_many_range'])
    if not low <= quantity(share) <= high:
        raise QuoteRefused('share_many_outside_range')
    bids, asks = _levels(inputs['yes_bids']), _levels(inputs['yes_asks'])
    for bid_key, ask_key in [('yes_bids', 'yes_asks'), ('no_bids', 'no_asks')]:
        spread = min(p for p, _ in _levels(inputs[ask_key])) - max(p for p, _ in _levels(inputs[bid_key]))
        if not 0 < spread <= quantity('.06'):
            raise QuoteRefused('spread_too_wide')
    reach = quantity(inputs['reward_max_spread_cents']) / 100
    depth = min(sum((s for p, s in bids if mid - reach <= p <= mid), Decimal(0)),
                sum((s for p, s in asks if mid <= p <= mid + reach), Decimal(0)))
    if depth < max(quantity(policy.raw['min_book_depth']), size):
        raise QuoteRefused('thin_book_depth')
    return {'min_reward_rate': policy.raw['min_reward_rate'], 'min_book_depth': policy.raw['min_book_depth'],
            'share_many_range': policy.raw['share_many_range'], 'depth': str(depth)}


def candidate(band, *, now, policy, held):
    row = {**band, 'eligible': False, 'refusal': None, 'quote': None, 'predicted_360_minutes': None}
    try:
        if band['market_id'] not in policy.raw['market_ids']:
            raise QuoteRefused('market_outside_campaign')
        if band['market_timezone'] != REGISTRY[band['market_id']].timezone:
            raise QuoteRefused('market_timezone')
        if not horizon_allowed(band, now, policy.raw['local_event_dte']):
            raise QuoteRefused('market_local_horizon')
        snapshot = band['snapshot']
        if (not 0 <= (utc(now) - utc(snapshot['observed_at_utc'])).total_seconds() <= 1800 or
                snapshot['condition_id'] != band['condition_id'] or
                snapshot['token_ids'] != band['token_ids'] or len(set(band['token_ids'])) != 2):
            raise QuoteRefused('public_scope_or_freshness')
        siblings = {str(c).lower() for c in band['event_condition_ids']}
        if band['condition_id'].lower() not in siblings:
            raise QuoteRefused('event_conditions_incomplete')
        if siblings & held:
            raise QuoteRefused('event_position_in_baseline')
        fee, _ = maker_fee_refusal(snapshot, band['token_ids'])
        if fee:
            raise QuoteRefused(fee)
        inputs = snapshot['quote_inputs']
        # Midpoint is independent of our orders; never choose a side using an
        # inferred complementary ask or by repricing a stale book.
        minimum = quantity(inputs['reward_min_size'])
        bids, asks = _levels(inputs['yes_bids']), _levels(inputs['yes_asks'])
        qualified_bids = [p for p, size in bids if size >= minimum]
        qualified_asks = [p for p, size in asks if size >= minimum]
        if not qualified_bids or not qualified_asks:
            raise QuoteRefused('no_size_adjusted_midpoint')
        mid = (max(qualified_bids) + min(qualified_asks)) / 2
        legs = trade_legs(policy, mid)
        quote = price_sized_reward_quote(**inputs, size=policy.raw['shares_per_leg'],
                    per_order_ceiling=policy.raw['per_order_cap_pusd'], per_band_ceiling=policy.raw['per_band_cap_pusd'],
                    quote_offset=policy.raw['quote_offset_pusd'],
                    distance_window=policy.raw['requote_distance_cents'], trade_legs=legs,
                    min_reward_rate=policy.raw['min_reward_rate'])
        low, high = map(quantity, policy.raw['leg_price_range'])
        if any(not low <= (quote.yes_buy, quote.no_buy)[leg] <= high for leg in legs):
            raise QuoteRefused('leg_price_outside_range')
        check_book(inputs, mid=quote.adjusted_mid, size=quote.size, share=quote.share_many, policy=policy)
        row.update(eligible=True, trade_legs=list(legs),
                   quote={k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(quote).items()},
                   predicted_360_minutes=quote.predicted_per_minute_many * 360)
    except (QuoteRefused, ValueError, KeyError, TypeError) as exc:
        row['refusal'] = str(exc) if isinstance(exc, QuoteRefused) else 'candidate_unreadable'
    return row


def build_table(universe, *, now, policy, cash, capital, held_conditions=(), source_records=(), complete=True):
    held = {str(c).lower() for c in held_conditions}
    if len(universe) > 1500 or len({r['condition_id'] for r in universe}) != len(universe):
        raise ValueError('f2_universe_identity_or_budget')
    rows = [candidate(band, now=now, policy=policy, held=held) for band in universe]
    rank = lambda row: (-row['predicted_360_minutes'], row['condition_id'])
    city_picks = []
    for city in policy.raw['market_ids']:
        eligible = sorted((r for r in rows if r['eligible'] and r['market_id'] == city), key=rank)
        if eligible:
            city_picks.append(eligible[0])
    picks, total = [], 0
    cash_native = native(cash)
    segregated = sum(capital[k] for k in ('segregated_profit_native', 'segregated_incentives_native',
                                          'segregated_external_cash_native'))
    for row in sorted(city_picks, key=rank):
        reserve = native(row['quote']['reserve_pusd'], ceil=True)
        if (len(picks) < policy.raw['band_limit_session'] and
                capital['charged_native'] + total + reserve <= capital['funding_native'] and
                capital['resting_reserve_native'] + total + reserve <= cash_native - segregated):
            picks.append(row['condition_id'])
            total += reserve
    return {'schema_version': SCHEMA_VERSION, 'kind': 'selection', 'size_treatment': C.TREATMENT,
            'f2_policy_sha256': policy.sha256, 'created_at_utc': utc(now).isoformat(),
            'universe_complete': complete is True, 'source_records': list(source_records),
            'available_collateral': str(quantity(cash)), 'capital': capital,
            'baseline_position_conditions': sorted(held), 'rows': sorted(rows, key=lambda r: r['condition_id']),
            'ranked_conditions': [r['condition_id'] for r in sorted(city_picks, key=rank)],
            'selected_condition_ids': picks if complete else [],
            'selected_condition_id': picks[0] if picks and complete else None,
            'planning_label': 'PLANNING', 'prediction_booked_as_income': False}


def validate_table(table, *, now, policy):
    if (table.get('f2_policy_sha256') != policy.sha256 or table.get('universe_complete') is not True or
            not 0 <= (utc(now) - utc(table['created_at_utc'])).total_seconds() <= 1800):
        raise ValueError('f2_selection_binding')
    original = [{k: v for k, v in row.items() if k not in DERIVED} for row in table['rows']]
    rebuilt = build_table(original, now=table['created_at_utc'], policy=policy, cash=table['available_collateral'],
                          capital=table['capital'], held_conditions=table['baseline_position_conditions'],
                          source_records=table['source_records'])
    if rebuilt != table:
        raise ValueError('f2_selection_not_reproducible')
    selected = [next(row for row in table['rows'] if row['condition_id'] == cid) for cid in table['selected_condition_ids']]
    if any(not horizon_allowed(row, now, policy.raw['local_event_dte']) for row in selected):
        raise ValueError('market_local_horizon')
    return selected


def band_table(table, condition):
    if condition not in table['selected_condition_ids']:
        raise ValueError('f2_unselected_band')
    return {**table, 'selected_condition_id': condition, 'f2_parent_table_sha256': digest(table)}


def discover(public, policy, *, now, cash, capital, held_conditions):
    universe, seen = [], set()
    for city in policy.raw['market_ids']:
        for dte in policy.raw['local_event_dte']:
            target = utc(now).astimezone(ZoneInfo(REGISTRY[city].timezone)).date() + timedelta(days=dte)
            slug = event_slug_for_date(target, city)
            try:
                event = public.get('https://gamma-api.polymarket.com/events/slug/' + slug)
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                public.records.append({'event_slug': slug, 'http_status': 404, 'observed_at_utc': utc(now).isoformat()})
                continue
            if event.get('slug') != slug or not isinstance(event.get('markets'), list):
                raise ValueError('configured_event_response_changed')
            siblings = sorted(str(m['conditionId']) for m in event['markets'])
            for band in event['markets']:
                cid = band['conditionId']
                if cid in seen or len(seen) >= 1500:
                    raise ValueError('f2_universe_identity_or_budget')
                seen.add(cid)
                if band.get('closed') or not band.get('enableOrderBook', True):
                    continue
                reward = public.reward(cid)
                if reward is None:
                    continue
                if (quantity(reward['rewards_min_size']) > 20 or not reward_rate_eligible(reward_rate(reward, now), policy.raw['min_reward_rate']) or
                        quantity(reward['rewards_max_spread']) < 3):
                    continue
                tokens = json.loads(band['clobTokenIds']) if isinstance(band['clobTokenIds'], str) else band['clobTokenIds']
                outcomes = json.loads(band['outcomes']) if isinstance(band['outcomes'], str) else band['outcomes']
                if outcomes != ['Yes', 'No'] or len(tokens) != 2 or len(set(tokens)) != 2:
                    raise ValueError('event_token_pair')
                universe.append({'market_id': city, 'market_timezone': REGISTRY[city].timezone,
                    'target_date': target.isoformat(), 'condition_id': cid, 'token_ids': tokens,
                    'event_condition_ids': siblings, 'event_slug': slug,
                    'snapshot': public.snapshot(cid, tokens, reward=reward)})
    return build_table(universe, now=now, policy=policy, cash=cash, capital=capital,
                       held_conditions=held_conditions, source_records=public.records)
