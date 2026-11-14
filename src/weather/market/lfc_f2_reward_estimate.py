"""Non-money condition/day reward estimates alongside unchanged strict cash.

Venue earnings, possible payment rows and D+1/D+2 observations are separate.
Absence of an observed owner order never proves complete earning-order history.
Nothing in this module writes the ledger or supplies capital/refill/headroom.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from weather.market.lfc_accounting import quantity
from weather.market.lfc_capital import ASSET
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, STATE_JSON_LIMIT
from weather.market.mm_stage2_hold import digest, utc
from weather.operations.live_path_security import validate_contained_regular_file


TOUCH_LIMIT = 25000
EVENT = re.compile(rb'"event"\s*:\s*"([^"\r\n]+)"')


def quoted_scope(ledger, sessions):
    scope = {}
    for sid in sessions:
        session = ledger.sessions[sid]
        for key in session['legs']:
            leg = ledger.legs[key]
            if leg['order_id'] is not None:
                day = session['start']['recorded_at_utc'][:10]
                scope.setdefault((day, leg['condition_id']), set()).add(sid)
    return scope


def instant(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('reward_context_time')
    if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit():
        return datetime.fromtimestamp(float(value), timezone.utc)
    return utc(value)


def venue_observations(response, *, condition, maker, observed_at_utc, receipt_sha256, record_pass=0, conditions=None):
    """Reuse the existing native-asset/day normalizer; asset USD rates are not cash."""
    from weather.market.re1_payout_evidence import normalize_earnings, micro_units
    from weather.market.lfc_rewards_record import clob_earnings
    day = response['day']
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    scope = {'maker_address': maker.lower(), 'condition_id': condition,
             'accrual_start_utc': start.isoformat(), 'accrual_end_utc': (start + timedelta(days=1)).isoformat()}
    earnings = clob_earnings(response['rows'])
    totals = clob_earnings(response['total_earnings'], total=True)
    rows, assets_complete = normalize_earnings(
        [(row, receipt_sha256) for row in earnings],
        [(row, receipt_sha256) for row in totals], scope, utc(observed_at_utc))
    selected = {condition} if conditions is None else set(conditions)
    present = {(row['condition_id'], row['cash_asset']['asset_address']) for row in rows}
    for total in totals:
        if quantity(total['earnings']) == 0:
            for cid in sorted(selected):
                if (cid, total['asset_address'].lower()) not in present:
                    zero, _ = normalize_earnings([(dict(total, condition_id=cid), receipt_sha256)], [],
                        dict(scope, condition_id=cid), utc(observed_at_utc))
                    rows.extend(zero)
    return [{**{key: row[key] for key in ('accrual_id', 'condition_id', 'cash_asset', 'venue_amount',
                  'status', 'period_start_utc', 'period_end_utc', 'observed_at_utc')},
             'earned_date': day, 'amount_native': micro_units(row['venue_amount']),
             'source_record_sha256': receipt_sha256, 'record_pass': record_pass,
             'source_assets_complete': assets_complete, 'payment_verified': False}
            for row in rows if row['condition_id'] in selected]


def capture_accrual(band, response):
    try:
        conditions = {condition for day, condition in quoted_scope(band.ledger, band.ledger.sessions)
                      if day == response['day']}
        rows = venue_observations(response, condition=band.condition, maker=band.venue.maker,
            observed_at_utc=band.clock.now().isoformat(), receipt_sha256=digest(response), conditions=conditions)
        for row in rows:
            band.reward_estimates[(row['earned_date'], row['condition_id'], row['cash_asset']['asset_address'])] = row
        for first in range(0, max(1, len(rows)), 64):
            band.journal.record('campaign_reward_estimate', entries=rows[first:first + 64],
                                source_response_sha256=digest(response), capital_credit_native=0)
        band.reward_estimate_gaps.discard('session_earnings_unavailable')
    except Exception as exc:
        band.reward_estimate_gaps.add('session_earnings_unavailable')
        band.journal.record('campaign_reward_estimate_unavailable', exception_type=type(exc).__name__)


def capture_stream_context(band, rows):
    """The pair reader already bound these normalized own events to this maker."""
    try:
        ours = band.ledger.our_order_ids()
        for event in rows:
            oid = event.get('order_id', event.get('id'))
            kind = event.get('official_event_type')
            if (kind not in {'trade', 'order'} or not oid or oid in ours or
                    event.get('condition_id') != band.condition):
                continue
            try:
                when = instant(event.get('exchange_match_time', event.get('exchange_timestamp'))).isoformat()
            except (ValueError, TypeError, OverflowError):
                when = None
            touch = {'condition_id': band.condition, 'own_order_id': oid,
                'first_touch_at_utc': when, 'last_touch_at_utc': when,
                'trade_ids': [event['trade_id']] if kind == 'trade' and event.get('trade_id') else [],
                'time_basis': 'validated_own_stream', 'source_event_sha256': event.get('raw_event_sha256') or digest(event)}
            key = digest(touch)
            if len(band.reward_context) >= 4096 and key not in band.reward_context:
                raise ValueError('reward_context_budget')
            if key not in band.reward_context:
                band.reward_context[key] = touch
                band.journal.record('campaign_reward_context', touch=touch)
    except Exception as exc:
        band.reward_estimate_gaps.add('stream_reward_context_unavailable')
        band.journal.record('campaign_reward_context_unavailable', exception_type=type(exc).__name__)


def account_context(ledger, read):
    """Retain observed noncampaign own touches, without claiming closed-order coverage."""
    maker, ours = ledger.rows[0]['maker_address'].lower(), ledger.our_order_ids()
    if str(read.get('maker_address', '')).lower() != maker:
        raise ValueError('reward_context_account')
    observed = utc(read['ended_at_utc'])
    touches, gaps = {}, set()
    def add(condition, oid, first, last, trade_id=None, basis='trade_match_time'):
        if oid in ours:
            return
        if not isinstance(oid, str) or not oid or not isinstance(condition, str) or not condition:
            gaps.add('owner_touch_identity_unknown')
            return
        # Trades are exact-day observations; do not bridge unrelated trade days.
        key = condition, oid, first[:10] if first else 'unknown', basis
        if key not in touches and len(touches) >= TOUCH_LIMIT:
            raise ValueError('reward_context_budget')
        row = touches.setdefault(key, {'condition_id': condition, 'own_order_id': oid,
            'first_touch_at_utc': first, 'last_touch_at_utc': last, 'time_basis': basis, 'trade_ids': []})
        if trade_id is not None and trade_id not in row['trade_ids']:
            if len(row['trade_ids']) >= 512:
                raise ValueError('reward_context_budget')
            row['trade_ids'].append(trade_id)
    for row in read.get('open_orders', []):
        first, basis = observed, 'observed_open_order'
        try:
            first = instant(row.get('created_at'))
            basis = 'created_to_observed_open_order'
        except (ValueError, TypeError, OverflowError):
            pass
        add(row.get('condition_id', row.get('market')), row.get('id', row.get('order_id')),
            first.isoformat(), observed.isoformat(), basis=basis)
    for trade in read.get('trades', []):
        condition = trade.get('condition_id', trade.get('market'))
        try:
            when = instant(next((trade.get(key) for key in ('matched_at', 'match_time', 'exchange_match_time', 'timestamp')
                                 if trade.get(key) is not None), None)).isoformat()
        except (ValueError, TypeError, OverflowError):
            when = None
        if str(trade.get('trader_side', '')).upper() == 'TAKER':
            add(condition, trade.get('taker_order_id'), when, when, trade.get('id'))
        for part in trade.get('maker_orders') or ():
            if str(part.get('maker_address', '')).lower() == maker:
                add(condition, part.get('order_id'), when, when, trade.get('id'))
    return {'observed_at_utc': observed.isoformat(), 'source_read_sha256': digest(read),
            'order_history_complete': False, 'coverage': 'observed_open_orders_and_account_trades',
            'touches': list(touches.values()), 'gaps': sorted(gaps)}


def remember_account_context(runtime, read):
    """Ancillary local projection of an already retained read; no extra GETs."""
    try:
        row = account_context(runtime.state.ledger, read)
        sha = digest(row)
        relative = 'reward-context/' + sha[:32] + '.json'
        if not (runtime.state.root / relative).exists():
            runtime.state.save(relative, {**row, 'content_sha256': sha})
        elif runtime.state.read(runtime.state.root / relative).get('content_sha256') != sha:
            raise ValueError('reward_context_collision')
        session = getattr(getattr(runtime, '_task_status', None), 'session', None)
        if session is not None and hasattr(session, 'reward_context'):
            for touch in row['touches']:
                key = digest(touch)
                if len(session.reward_context) < TOUCH_LIMIT or key in session.reward_context:
                    session.reward_context[key] = touch
                else:
                    session.reward_context_gaps.add('reward_context_budget')
            session.reward_context_gaps.update(row['gaps'])
    except Exception:
        gaps = getattr(runtime, 'reward_estimate_gaps', set())
        gaps.add('account_reward_context_unavailable')
        runtime.reward_estimate_gaps = gaps
        session = getattr(getattr(runtime, '_task_status', None), 'session', None)
        if session is not None and hasattr(session, 'reward_context_gaps'):
            session.reward_context_gaps.add('account_reward_context_unavailable')


def contamination(scope, contexts, ours):
    result = {}
    for day, condition in scope:
        start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        end, orders, trades, unknown = start + timedelta(days=1), set(), set(), False
        for context in contexts:
            for row in context.get('touches', []):
                if row['condition_id'] != condition or row['own_order_id'] in ours:
                    continue
                if row['first_touch_at_utc'] is None:
                    unknown = True
                    continue
                first, last = utc(row['first_touch_at_utc']), utc(row['last_touch_at_utc'])
                if first < end and last >= start:
                    orders.add(row['own_order_id']); trades.update(row['trade_ids'])
        result[day, condition] = {'other_own_activity_detected': bool(orders) if orders or not unknown else None,
            'other_own_order_ids': sorted(orders), 'other_own_trade_ids': sorted(trades),
            'other_own_touch_date_unknown': unknown, 'order_history_complete': False,
            'clean_scope_proven': False, 'flag': 'other_own_activity' if orders else
                'owner_touch_date_unknown' if unknown else 'none_observed_history_incomplete'}
    return result


def summary(ledger, sessions, *, observations=(), contexts=(), receipts=(), payments=(), gaps=()):
    scope = quoted_scope(ledger, sessions)
    whole_campaign = quoted_scope(ledger, ledger.sessions)
    flags = contamination(scope, contexts, ledger.our_order_ids())
    latest, observed = {}, {}
    for row in observations:
        day_condition = row['earned_date'], row['condition_id']
        if day_condition not in scope:
            continue
        key = (*day_condition, row['cash_asset']['asset_address'])
        # D+1 and D+2 remain independent receipts; latest actual collection wins.
        identity = (*key, row['record_pass'])
        if identity not in observed or utc(row['observed_at_utc']) > utc(observed[identity]['observed_at_utc']):
            observed[identity] = row
        if key not in latest or utc(row['observed_at_utc']) > utc(latest[key]['observed_at_utc']):
            latest[key] = row
    entries = [{**row, **flags[key[:2]], 'campaign_session_ids': sorted(whole_campaign[key[:2]]),
                'label': 'CAMPAIGN_ESTIMATE', 'capital_credit_native': 0}
               for key, row in sorted(latest.items())]
    by_asset = []
    for asset in sorted({key[2] for key in latest}):
        covered = {key[:2] for key in latest if key[2] == asset}
        amount = sum(row['amount_native'] for row in entries if row['cash_asset']['asset_address'] == asset)
        missing = [{'earned_date': day, 'condition_id': condition} for day, condition in sorted(scope.keys() - covered)]
        marker = next(row['cash_asset'] for row in entries if row['cash_asset']['asset_address'] == asset)
        by_asset.append({'cash_asset': marker, 'estimated_native': amount if not missing else None,
                         'observed_estimate_native': amount, 'missing_condition_days': missing})
    primary = by_asset[0] if len(by_asset) == 1 else None
    missing_pairs = ({(row['earned_date'], row['condition_id']) for asset in by_asset
                      for row in asset['missing_condition_days']} if by_asset else set(scope))
    missing = [{'earned_date': day, 'condition_id': condition} for day, condition in sorted(missing_pairs)]
    pusd = next((row['estimated_native'] for row in by_asset if row['cash_asset']['asset_address'] == ASSET), None)
    return {'strict_attributable': {'recognized_native': 0, 'cash_asset': ASSET,
                'state': 'unproven_contributes_zero', 'capital_credit_native': 0,
                'basis': 'existing_complete_earned_order_and_native_payment_proof_required'},
            'campaign_estimate': {'label': 'CAMPAIGN_ESTIMATE', 'basis': 'venue_condition_day_earnings',
                'earned_date_timezone': 'UTC', 'cash_asset': primary['cash_asset']['asset_address'] if primary else None,
                'native_decimals': 6, 'asset_estimates': by_asset, 'estimated_pusd_native': pusd,
                'estimated_native': primary['estimated_native'] if primary else 0 if not scope else None,
                'observed_estimate_native': primary['observed_estimate_native'] if primary else None if by_asset else 0,
                'aggregation_key': ['earned_date', 'condition_id', 'asset_address'],
                'allocation_scope': 'whole_condition_day_across_campaign_attempts',
                'complete_condition_day_coverage': not missing, 'missing_condition_days': missing,
                'entries': entries, 'observations_by_pass': [row for _, row in sorted(observed.items())],
                'd1_d2_receipts': list(receipts), 'payment_candidates': list(payments),
                'actually_paid_native': None, 'capital_credit_native': 0, 'booked_as_income': False,
                'evidence_gaps': sorted(set(gaps) | {g for context in contexts for g in context.get('gaps', [])})}}


def session_observations(root, ledger, sessions, *, state=None):
    """Small terminal projections for new code; streamed one-time replay for old journals."""
    result, hashes, gaps, contexts = [], {}, [], []
    for sid in sorted(sessions):
        relative = ledger.sessions[sid]['start'].get('directory')
        if relative is None:
            gaps.append('session_earnings_projection_pending')
            continue
        try:
            directory = Path(root) / relative
            path = validate_contained_regular_file(root, directory / 'prediction.json')
            prediction = strict_json(read_bytes(path, STATE_JSON_LIMIT))
            hashes[str(path.relative_to(root))] = file_sha(path)
            contexts.append(prediction.get('reward_context', {'touches': [], 'gaps': []}))
            if 'reward_estimates' in prediction:
                result.extend(prediction['reward_estimates'])
                gaps.extend(prediction.get('reward_estimate_gaps', []))
                continue
            journal = validate_contained_regular_file(root, directory / 'journal.jsonl')
            sha = file_sha(journal)
            cached = state.root / 'reward-projections' / (sha[:32] + '.json') if state is not None else None
            if cached is not None and cached.exists():
                saved = state.read(cached)
                body = {key: saved[key] for key in ('journal_sha256', 'observations')}
                if body['journal_sha256'] != sha or digest(body) != saved['content_sha256']:
                    raise ValueError('reward_projection_hash')
                result.extend(body['observations'])
                continue
            latest = {}
            with journal.open('rb') as handle:
                for raw in handle:
                    event = EVENT.search(raw[:500])
                    if event is None or event[1] not in {b'accrual_response', b'final_accrual_response'}:
                        continue
                    row = strict_json(raw)
                    conditions = {condition for day, condition in quoted_scope(ledger, ledger.sessions)
                                  if day == row['response']['day']}
                    condition = ledger.sessions[sid]['start'].get('condition_id') or ledger.legs[ledger.sessions[sid]['legs'][0]]['condition_id']
                    for item in venue_observations(row['response'], condition=condition, conditions=conditions,
                            maker=ledger.rows[0]['maker_address'], observed_at_utc=row['recorded_at_utc'], receipt_sha256=digest(row)):
                        latest[item['earned_date'], item['condition_id'], item['cash_asset']['asset_address']] = item
            result.extend(latest.values())
            hashes[str(journal.relative_to(root))] = sha
            if cached is not None:
                body = {'journal_sha256': sha, 'observations': list(latest.values())}
                state.save('reward-projections/' + cached.name, {**body, 'content_sha256': digest(body)})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            gaps.append('session_earnings_projection_unavailable')
    return result, hashes, gaps, contexts


def retained_summary(root, ledger, sessions, *, state=None):
    """Replay existing receipts only. Never perform a venue or account read."""
    from weather.market.lfc_rewards_record import latest_record
    from weather.market.re1_payout_evidence import micro_units
    scope = quoted_scope(ledger, sessions)
    days = {day for day, _ in scope}
    observation_sessions = [sid for sid, session in ledger.sessions.items()
                            if session['legs'] and session['start']['recorded_at_utc'][:10] in days]
    observations, hashes, gaps, contexts = session_observations(root, ledger, observation_sessions, state=state)
    receipts, payments = [], {}
    for day in sorted({day for day, _ in scope}):
        conditions = sorted(filter(None, {s['start'].get('condition_id') or ledger.legs[key].get('condition_id')
            for s in ledger.sessions.values() for key in s['legs'] if s['start']['recorded_at_utc'][:10] == day}))
        for lag in (1, 2):
            try:
                row, path, _ = latest_record(Path(root) / 'rewards' / f'{day}-d{lag}.json',
                    kind='lfc_rewards_record', day=day, maker=ledger.rows[0]['maker_address'].lower(),
                    conditions=conditions, lag=lag)
                if row is None:
                    gaps.append(f'{day}:d{lag}:pending')
                    continue
                sha = file_sha(path)
                hashes[str(path.relative_to(root))] = sha
                receipts.append({'earned_date': day, 'record_pass': lag, 'file_sha256': sha,
                    'observed_at_utc': row['observed_at_utc'], 'query_end_utc': row['query_end_utc']})
                for entry in row['accruals']:
                    if not entry['source']['complete']:
                        gaps.append(f'{day}:d{lag}:incomplete')
                        from weather.market.lfc_accrual_replay import validate_accrual
                        from weather.market.lfc_rewards_record import clob_earnings
                        try:
                            validate_accrual(entry, row['wire_journal'], maker=ledger.rows[0]['maker_address'].lower(),
                                day=day, start=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
                                decode_rows=clob_earnings, allow_partial_assets=True)
                        except (ValueError, KeyError, TypeError, RuntimeError):
                            continue
                    for item in entry['accruals']:
                        observations.append({**item, 'earned_date': day, 'record_pass': lag,
                            'amount_native': micro_units(item['venue_amount']), 'source_record_sha256': sha,
                            'source_assets_complete': entry['source']['complete'], 'payment_verified': False})
                for item in row['distributions'].get('rows', row['distributions'].get('partial_rows', [])):
                    payment_id = item.get('id') or digest(item)
                    payment = payments.setdefault(payment_id, {'payment_id': payment_id,
                        'payment_id_basis': 'venue_id' if item.get('id') else 'activity_row_sha256',
                        'transaction_hash': item.get('transaction_hash'), 'paid_at_epoch': item.get('timestamp'),
                        'cash_amount_native': micro_units(str(item['usdc_size'])), 'earned_date': None,
                        'reported_amount_field': 'usdc_size', 'cash_asset': None, 'native_asset_verified': False,
                        'candidate_earned_dates': [], 'record_passes': [], 'observations': [], 'earned_date_link_verified': False})
                    payment['candidate_earned_dates'] = sorted(set(payment['candidate_earned_dates']) | {day})
                    payment['record_passes'] = sorted(set(payment['record_passes']) | {lag})
                    payment['observations'].append({'candidate_earned_date': day, 'record_pass': lag,
                        'observed_at_utc': row['observed_at_utc'], 'source_record_sha256': sha,
                        'reported_amount': str(item['usdc_size'])})
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                gaps.append(f'{day}:d{lag}:refused')
    if state is not None:
        relevant = {condition for _, condition in scope}
        touches, context_gaps = {}, set()
        for path in sorted((state.root / 'reward-context').glob('*.json')):
            try:
                row = state.read(path)
                body = {key: row[key] for key in ('observed_at_utc', 'source_read_sha256', 'order_history_complete',
                                                  'coverage', 'touches', 'gaps')}
                if digest(body) != row['content_sha256']:
                    raise ValueError('reward_context_hash')
                selected = [touch for touch in body['touches'] if touch['condition_id'] in relevant]
                for touch in selected:
                    key = digest(touch)
                    if len(touches) >= TOUCH_LIMIT and key not in touches:
                        raise ValueError('reward_context_budget')
                    touches[key] = touch
                context_gaps.update(body['gaps'])
                if selected or body['gaps']:
                    hashes['reward-context/' + path.name] = file_sha(path)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                gaps.append('account_reward_context_unavailable')
        contexts.append({'touches': [row for _, row in sorted(touches.items())], 'gaps': sorted(context_gaps)})
    return summary(ledger, sessions, observations=observations, contexts=contexts,
                   receipts=receipts, payments=list(payments.values()), gaps=gaps), hashes
