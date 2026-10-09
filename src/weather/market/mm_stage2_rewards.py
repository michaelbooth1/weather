"""SDK reward observations and offline RE-1 verdicts; no client at import.

Daily SDK earnings are accruals. A paid amount requires the existing independent
distribution-to-wallet reconciliation, including complete cash coverage.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import json
from pathlib import Path

from weather.market.exchange_economics_sources import MAX_RESPONSE_BYTES, response_evidence
from weather.market.mm_exchange_reports import reconcile_incentive_payments
from weather.market.mm_liquidity_earnings_evidence import normalize_liquidity_earnings_pages
from weather.market.mm_stage2_hold import SCHEMA_VERSION, digest, utc, write_new, verify_prediction_journal
from weather.market.reward_quote import _decimal


def load_frozen_predictions(records, *, now):
    """Validate the exact frozen files before constructing an earnings reader."""
    predictions, seen = [], set()
    for record in records:
        path, journal = Path(record['prediction']), Path(record['journal'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['prediction_sha256']:
            raise ValueError('frozen prediction changed')
        payload = json.loads(raw)
        if (payload.get('schema_version') != SCHEMA_VERSION or payload.get('kind') != 'prediction'
                or payload.get('earnings_read') is not False
                or payload.get('journal_sha256') != hashlib.sha256(journal.read_bytes()).hexdigest()
                or payload['journal_sha256'] in seen
                or utc(payload['frozen_at_utc']) > utc(now)
                or utc(now).date().isoformat() <= payload['reward_day']):
            raise ValueError('prediction/journal is not unique, frozen and next-day collectable')
        for name in ('P_many', 'P_single', 'visible_two_sided_minutes'):
            if _decimal(payload[name]) < 0:
                raise ValueError('negative frozen prediction')
        verify_prediction_journal(payload, journal)
        seen.add(payload['journal_sha256'])
        predictions.append(payload)
    if (not 1 <= len(predictions) <= 4
            or len({(p['reward_day'], p['condition_id'], p['mode'], p['scope'].get('maker_address')) for p in predictions}) != 1):
        raise ValueError('collect exactly one band and UTC reward day, at most four sessions')
    if predictions[0]['mode'] == 'live':
        verify_campaign_day(predictions)
    return predictions


def verify_campaign_day(predictions):
    """For live evidence, refuse an omitted or unresolved same-day attempt."""
    from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as profile
    from weather.operations.live_path_security import validate_regular_nonreparse_file, validate_nonreparse_directory
    roots, submitted = set(), {}
    for prediction in predictions:
        scope = prediction['scope']
        path = validate_regular_nonreparse_file(scope['campaign_attempt_path'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != scope['campaign_attempt_sha256']:
            raise ValueError('campaign attempt changed after prediction freeze')
        roots.add(path.parent)
        submitted[path] = digest(prediction)
    if len(roots) != 1 or len(submitted) != len(predictions):
        raise ValueError('campaign roots or attempts differ')
    root = validate_nonreparse_directory(next(iter(roots)))
    paths = sorted(root.glob('*.attempt.json'))
    if len(paths) > profile.max_reward_days * profile.max_sessions_per_utc_day:
        raise ValueError('campaign exceeds its attempt ceiling')
    day, condition = predictions[0]['reward_day'], predictions[0]['condition_id']
    expected, days = {}, set()
    for path in paths:
        validate_regular_nonreparse_file(path)
        attempt = json.loads(path.read_bytes())
        if (attempt.get('schema_version') != SCHEMA_VERSION or attempt.get('kind') != 'session'
                or attempt.get('profile_sha256') != profile.sha256):
            raise ValueError('campaign attempt schema or profile differs')
        days.add(attempt['reward_day'])
        if attempt['reward_day'] != day:
            continue
        result_path = validate_regular_nonreparse_file(path.with_name(path.name.replace('.attempt.json', '.result.json')))
        result = json.loads(result_path.read_bytes())
        if attempt['condition_id'] != condition or result['attempt_sha256'] != digest(attempt):
            raise ValueError('campaign day changes band or result binding')
        expected[path] = result['prediction_sha256']
    if len(days) > profile.max_reward_days or len(expected) > profile.max_sessions_per_utc_day or submitted != expected:
        raise ValueError('collection omits or changes a campaign day attempt')
    return sorted(days)


class RewardsReaders:
    """A narrow facade over an already supplied pinned SDK client.

    The sealed session constructs it for scoring. Explicit collect constructs
    it only after load_frozen_predictions succeeds. The raw-response hook keeps
    body bytes and public scope only; request/authentication headers are never
    inspected or retained. No client or credential is resolved by this class.
    """

    def __init__(self, client, *, purpose):
        if purpose not in {'sealed_stage2_scoring', 'explicit_post_session_collect'}:
            raise ValueError('reward reader needs an explicit session/collect purpose')
        self.client, self.purpose = client, purpose

    def scoring(self, order_ids):
        ids = tuple(order_ids)
        if not 1 <= len(ids) <= 2 or len(set(ids)) != len(ids) or any(not x for x in ids):
            raise ValueError('scoring requires one or two exact known order IDs')
        result = self.client.get_orders_scoring(order_ids=ids)
        if not isinstance(result, dict) or set(result) != set(ids) or any(type(v) is not bool for v in result.values()):
            raise ValueError('SDK scoring response does not bind both orders')
        return result

    def order_scoring(self, order_id):
        result = self.client.get_order_scoring(order_id=order_id)
        if type(result) is not bool:
            raise ValueError('SDK scoring response is not boolean')
        return result

    def daily(self, *, reward_day, maker_address, signature_type, clock, prediction_records):
        if self.purpose != 'explicit_post_session_collect' or utc(clock()).date().isoformat() <= reward_day:
            raise ValueError('earnings are only read by explicit next-day collect')
        frozen = load_frozen_predictions(prediction_records, now=clock())
        if frozen[0]['reward_day'] != reward_day or frozen[0]['scope'].get('maker_address') != maker_address:
            raise ValueError('earnings query differs from the frozen session')
        pages = []

        def retain(response):
            if response.request.method != 'GET' or response.url.path != '/rewards/user':
                return
            body = response.read()
            if len(body) > MAX_RESPONSE_BYTES or len(pages) >= 50:
                raise ValueError('earnings response budget exceeded')
            record = response_evidence(body, url=str(response.url), http_status=response.status_code,
                                       content_type=response.headers.get('content-type', ''), origin='http_response_bytes')
            record['retrieved_at_utc'] = utc(clock()).isoformat()
            pages.append(record)

        # This pinned SDK transport is also exercised with httpx.MockTransport
        # in fixture tests. The hook observes real bytes, not re-encoded models.
        hooks = self.client._ctx.secure_clob._client.event_hooks['response']
        hooks.append(retain)
        try:
            rows = list(self.client.list_user_earnings_for_day(date=reward_day).iter_items())
        finally:
            hooks.remove(retain)
        normalized = normalize_liquidity_earnings_pages(
            pages, query_date=reward_day, maker_address=maker_address, signature_type=signature_type,
            as_of_utc=utc(clock()).isoformat(),
        )
        if normalized['row_count'] != len(rows):
            raise ValueError('SDK and retained page row counts differ')
        # These observations are deliberately separate from payment evidence.
        totals = self.client.get_total_earnings_for_user_for_day(date=reward_day)
        configurations = []
        cursors = set()
        for index, page in enumerate(self.client.list_user_earnings_and_markets_config(date=reward_day)):
            if index >= 50 or page.next_cursor is not None and page.next_cursor in cursors or len(configurations) + len(page.items) > 25000:
                raise ValueError('reward configuration row budget exceeded')
            cursors.add(page.next_cursor)
            configurations.extend(page.items)
        percentages = self.client.get_reward_percentages()
        def plain(value):
            if hasattr(value, 'model_dump'):
                return value.model_dump(mode='json')
            if isinstance(value, (list, tuple)):
                return [plain(v) for v in value]
            if isinstance(value, dict):
                return {k: plain(v) for k, v in value.items()}
            return value
        return {'accrual_evidence': normalized, 'sdk_totals': plain(totals),
                'sdk_market_configurations': plain(configurations), 'sdk_percentages': plain(percentages),
                'payment_verified': False}


def verdict(predictions, *, payment_evidence, earnings_observation=None):
    """Apply the frozen table to cumulative same-band/day observations."""
    if (not predictions or len(predictions) > 4
            or len({(p['reward_day'], p['condition_id'], p['mode']) for p in predictions}) != 1):
        raise ValueError('verdict requires one band in one reward day')
    first = predictions[0]
    p_many = sum(_decimal(p['P_many']) for p in predictions)
    p_single = sum(_decimal(p['P_single']) for p in predictions)
    minutes = sum(_decimal(p['visible_two_sided_minutes']) for p in predictions)
    payment = reconcile_incentive_payments(payment_evidence)
    scope = payment.get('scope') or {}
    start = utc(first['reward_day'] + 'T00:00:00Z')
    complete = (payment['valid'] and payment['complete']
                and scope.get('maker_address') == first['scope'].get('maker_address')
                and scope.get('condition_id') == first['condition_id']
                and utc(scope.get('accrual_start_utc')) == start
                and utc(scope.get('accrual_end_utc')) == start + timedelta(days=1))
    paid = _decimal(payment['actual_liquidity_reward_usdc']) if complete else None
    k = paid / p_many if paid is not None and p_many > 0 else None
    adequate = (complete and minutes >= 180 and p_many >= 2
                and all(p['cleanup_ok'] and p['cancel_acknowledged'] and not p['fill_seen']
                        and not p['reward_terms_changed'] for p in predictions))
    decision = 'INCONCLUSIVE'
    if adequate and k >= _decimal('.5'):
        decision = 'PAID_AS_MODELLED'
    elif adequate and _decimal('.1') <= k < _decimal('.5'):
        decision = 'PAID_DILUTED'
    elif adequate and paid == 0 and all(p['all_observed_legs_scoring'] for p in predictions):
        decision = 'NOT_PAID'
    return {'schema_version': SCHEMA_VERSION, 'kind': 'verdict', 'mode': first['mode'],
            'condition_id': first['condition_id'], 'reward_day': first['reward_day'],
            'prediction_sha256': [digest(p) for p in predictions], 'P_many': str(p_many), 'P_single': str(p_single),
            'visible_two_sided_minutes': str(minutes), 'paid': None if paid is None else str(paid),
            'k': None if k is None else str(k), 'verdict': decision,
            'payment_reconciliation': payment, 'earnings_observation': earnings_observation,
            'live_evidence': first['mode'] == 'live'}
