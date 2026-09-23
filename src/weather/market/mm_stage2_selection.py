"""Frozen RE-1 ranking and bounded unauthenticated weather-book reads."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from weather.market.exchange_economics_sources import (
    MAX_RESPONSE_BYTES, json_response_payload, response_evidence,
)
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_hold import SCHEMA_VERSION, digest, public_quote, utc
from weather.market.reward_quote import QuoteRefused, _decimal
from weather.market.re1_sizing import reserve_budget, sized_quote
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration, assert_no_ambient_market_registry_override


LOCATION_ORDER = ('los-angeles', 'seattle', 'san-francisco', 'denver')


def select_table(universe, *, now, complete=True, source_records=(), available_collateral=None):
    """Rank frozen tomorrow bands, or the explicit 84h local T+0/1/2 treatment."""
    current = utc(now)
    if available_collateral is not None:
        reserve_budget(available_collateral)
    target = (current.date() + timedelta(days=1)).isoformat()
    rows, identities = [], set()
    for band in universe:
        condition = band['condition_id']
        if condition in identities:
            raise ValueError('selection universe repeats a condition')
        identities.add(condition)
        row = dict(band)
        row.update(eligible=False, refusal=None, predicted_360_minutes=None)
        observed = utc(band['snapshot']['observed_at_utc'])
        if not 0 <= (current - observed).total_seconds() <= 1800:
            raise ValueError('selection snapshot outside the 30-minute window')
        try:
            if (band['market_id'] not in REGISTRY
                    or band['market_timezone'] != REGISTRY[band['market_id']].timezone):
                raise QuoteRefused('not_configured_tomorrow_event')
            dates = [target] if available_collateral is None else [
                (current.astimezone(ZoneInfo(band['market_timezone'])).date() + timedelta(days=d)).isoformat()
                for d in range(3)]
            if band['target_date'] not in dates:
                raise QuoteRefused('not_configured_tomorrow_event' if available_collateral is None
                                   else 'not_configured_local_day_0_1_2')
            if available_collateral is None:
                quote = public_quote(band['snapshot'], now=observed, condition_id=condition, token_ids=band['token_ids'])
            else:
                if (band['snapshot'].get('condition_id') != condition or
                        list(band['snapshot'].get('token_ids', ())) != list(band['token_ids'])):
                    raise QuoteRefused('public_scope_or_freshness')
                quote = sized_quote(band['snapshot'], available_collateral)
            predicted = quote.predicted_per_minute_many * 360
            row.update(quote={k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(quote).items()},
                       predicted_360_minutes=predicted)
            if predicted < 2:
                raise QuoteRefused('predicted_below_two')
            row['eligible'] = True
        except (QuoteRefused, ValueError, RuntimeError, KeyError, TypeError) as exc:
            row['refusal'] = str(exc) if isinstance(exc, QuoteRefused) else type(exc).__name__
        rows.append(row)
    def rank(row):
        priority = LOCATION_ORDER.index(row['market_id']) if row['market_id'] in LOCATION_ORDER else len(LOCATION_ORDER)
        return (-row['predicted_360_minutes'], priority, row['condition_id'])
    survivors = sorted((r for r in rows if r['eligible']), key=rank)
    treatment = {} if available_collateral is None else {
        'size_treatment': 'RE-1-84h', 'available_collateral': str(_decimal(available_collateral)),
        'reserve_budget_pusd': str(reserve_budget(available_collateral))}
    return {**treatment, 'schema_version': SCHEMA_VERSION, 'kind': 'selection', 'created_at_utc': current.isoformat(),
            'target_date': target, 'universe_complete': complete is True,
            'source_records': list(source_records), 'location_tie_order': list(LOCATION_ORDER),
            'rows': sorted(rows, key=lambda r: (r['market_id'], r['condition_id'])),
            'ranked_conditions': [r['condition_id'] for r in survivors],
            'selected_condition_id': survivors[0]['condition_id'] if survivors and complete else None}


def validate_selection(table, *, expected_sha256, condition_id, token_ids, now, allow_sized=False):
    current = utc(now)
    if not allow_sized and 'available_collateral' in table:
        raise ValueError('sized selection is attended RE-1 only')
    if (table.get('schema_version') != SCHEMA_VERSION or table.get('kind') != 'selection'
            or digest(table) != expected_sha256 or table.get('universe_complete') is not True
            or not 0 <= (current - utc(table['created_at_utc'])).total_seconds() <= 1800
            or table.get('selected_condition_id') != condition_id):
        raise ValueError('selection table is stale, changed, incomplete or names another condition')
    original = [{k: v for k, v in row.items() if k not in {'eligible', 'refusal', 'predicted_360_minutes', 'quote'}}
                for row in table['rows']]
    rebuilt = select_table(original, now=table['created_at_utc'], complete=True, source_records=table['source_records'],
                           available_collateral=table.get('available_collateral'))
    if rebuilt != table:
        raise ValueError('selection ranking does not reproduce the frozen rule')
    selected = next(row for row in table['rows'] if row['condition_id'] == condition_id)
    if list(selected['token_ids']) != list(token_ids):
        raise ValueError('selection token pair changed')
    return selected


def reward_rate(reward, observed_at):
    started = utc(observed_at)
    if 'total_daily_rate' in reward:
        rate = _decimal(reward['total_daily_rate'])
    else:
        configs = reward.get('rewards_config')
        if not isinstance(configs, list) or not configs:
            raise ValueError('reward configuration is incomplete')
        rate = Decimal(0)
        for config in configs:
            start = utc(str(config['start_date']) + 'T00:00:00Z') if len(str(config['start_date'])) == 10 else utc(config['start_date'])
            finish = utc(str(config['end_date']) + 'T23:59:59.999999Z') if len(str(config['end_date'])) == 10 else utc(config['end_date'])
            amount = _decimal(config['rate_per_day'])
            if amount < 0 or finish < start:
                raise ValueError('reward allocation is invalid')
            if start <= started <= finish:
                rate += amount
    return rate


class PublicBooks:
    """Exact public hosts only; no SDK, account endpoint, header or credential."""

    def __init__(self, *, clock=None, opener=None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.opener = opener or urlopen
        self.records = []

    def get(self, url, *, checkpoint=lambda: None):
        parts = urlsplit(url)
        allowed = (parts.netloc == 'gamma-api.polymarket.com' and parts.path.startswith('/events/slug/')) or (
            parts.netloc == 'clob.polymarket.com' and (parts.path in {'/book', '/tick-size', '/neg-risk', '/fee-rate', '/rewards/markets/current'}
                                                      or parts.path.startswith('/rewards/markets/0x')))
        if parts.scheme != 'https' or not allowed or parts.fragment or parts.username or parts.password:
            raise ValueError('not an allowed public weather/reward endpoint')
        assert_no_ambient_proxy_configuration()
        checkpoint()
        response = self.opener(Request(url, headers={'Accept': 'application/json',
            'User-Agent': 'weather-stage2-public-rehearsal/1.0'}), timeout=2)
        try:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
            if response.geturl() != url or status != 200 or len(body) > MAX_RESPONSE_BYTES:
                raise ValueError('public response redirected, oversized or unsuccessful')
            record = response_evidence(body, url=url, http_status=status,
                                       content_type=response.headers.get('Content-Type', ''), origin='http_response_bytes')
            record['retrieved_at_utc'] = utc(self.clock()).isoformat()
            if not record['content_type'].lower().startswith('application/json'):
                raise ValueError('public response is not JSON')
            self.records.append(record)
            checkpoint()
            return json_response_payload(body)
        finally:
            response.close()

    def reward(self, condition, *, checkpoint=lambda: None):
        import re
        if re.fullmatch(r'0x[0-9a-f]{64}', str(condition)) is None:
            raise ValueError('reward condition is invalid')
        payload = self.get('https://clob.polymarket.com/rewards/markets/' + condition, checkpoint=checkpoint)
        rows = payload.get('data') if isinstance(payload, dict) else None
        if (not isinstance(rows, list) or len(rows) > 1 or payload.get('count') != len(rows)
                or payload.get('next_cursor') != 'LTE=' or type(payload.get('limit')) is not int
                or not 1 <= payload['limit'] <= 500):
            raise ValueError('per-condition reward response is incomplete')
        if not rows:
            return None
        row = rows[0]
        if row.get('condition_id') != condition:
            raise ValueError('per-condition reward identity differs')
        for key in ('rewards_min_size', 'rewards_max_spread'):
            if _decimal(row[key]) < 0:
                raise ValueError('per-condition reward economics are invalid')
        reward_rate(row, self.clock())
        return row

    def snapshot(self, condition, tokens, *, reward=None, checkpoint=lambda: None):
        started = utc(self.clock())
        if reward is None:
            reward = self.reward(condition, checkpoint=checkpoint)
            if reward is None:
                raise ValueError('condition is no longer rewarded')
        if reward.get('condition_id') != condition:
            raise ValueError('reward condition changed')
        books, rules = [], {}
        for token in tokens:
            query = urlencode({'token_id': token})
            book = self.get('https://clob.polymarket.com/book?' + query, checkpoint=checkpoint)
            if str(book.get('asset_id')) != token or book.get('market') != condition:
                raise ValueError('public book token/condition changed')
            rules[token] = {'tick_size': str(book['tick_size']), 'min_order_size': str(book['min_order_size']),
                            'fee_rate_bps': str(self.get('https://clob.polymarket.com/fee-rate?' + query, checkpoint=checkpoint)['base_fee']),
                            'neg_risk': book['neg_risk']}
            if _decimal(rules[token]['fee_rate_bps']) < 0 or type(rules[token]['neg_risk']) is not bool:
                raise ValueError('public fee/neg-risk is invalid')
            books.append(book)
        if len(books) != 2 or books[0]['tick_size'] != books[1]['tick_size']:
            raise ValueError('two books must share the treatment tick')
        rate = reward_rate(reward, started)
        return {'condition_id': condition, 'token_ids': list(tokens), 'observed_at_utc': started.isoformat(),
                'rules': rules, 'quote_inputs': {
                    'yes_bids': books[0]['bids'], 'yes_asks': books[0]['asks'],
                    'no_bids': books[1]['bids'], 'no_asks': books[1]['asks'],
                    'reward_min_size': str(reward['rewards_min_size']),
                    'reward_max_spread_cents': str(reward['rewards_max_spread']),
                    'reward_rate_per_day': str(rate),
                    'tick': str(books[0]['tick_size']), 'post_only_available': True}}

    def selection(self, *, available_collateral=None):
        assert_no_ambient_market_registry_override()
        if available_collateral is not None:
            reserve_budget(available_collateral)
        target = utc(self.clock()).date() + timedelta(days=1)
        universe, seen = [], set()
        for market_id in sorted(REGISTRY):
            targets = [target] if available_collateral is None else [
                utc(self.clock()).astimezone(ZoneInfo(REGISTRY[market_id].timezone)).date() + timedelta(days=d)
                for d in range(3)]
            for target in targets:
                slug = event_slug_for_date(target, market_id)
                event = self.get('https://gamma-api.polymarket.com/events/slug/' + slug)
                if event.get('slug') != slug or not isinstance(event.get('markets'), list):
                    raise ValueError('configured event response changed')
                for band in event['markets']:
                    condition = band.get('conditionId')
                    if condition in seen or len(seen) >= (500 if available_collateral is None else 1500):
                        raise ValueError('configured event universe repeats a condition or exceeds its bound')
                    seen.add(condition)
                    reward = self.reward(condition)
                    if reward is None:
                        continue
                    tokens = json.loads(band['clobTokenIds']) if isinstance(band['clobTokenIds'], str) else band['clobTokenIds']
                    outcomes = json.loads(band['outcomes']) if isinstance(band['outcomes'], str) else band['outcomes']
                    if outcomes != ['Yes', 'No'] or len(tokens) != 2 or len(set(tokens)) != 2:
                        raise ValueError('event does not bind the exact YES/NO token pair')
                    # The reward thresholds define the preregistered book universe.
                    if (_decimal(reward['rewards_min_size']) > (20 if available_collateral is None else 75) or reward_rate(reward, self.clock()) < 40
                            or _decimal(reward['rewards_max_spread']) < 3):
                        continue
                    snapshot = self.snapshot(condition, tokens, reward=reward)
                    universe.append({'market_id': market_id, 'market_timezone': REGISTRY[market_id].timezone,
                                     'target_date': target.isoformat(), 'condition_id': condition,
                                     'token_ids': tokens, 'snapshot': snapshot, 'event_slug': slug})
        return select_table(universe, now=self.clock(), source_records=self.records,
                            available_collateral=available_collateral)
