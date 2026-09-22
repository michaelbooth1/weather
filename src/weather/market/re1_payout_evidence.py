"""Owner-run RE-1 reads with an explicitly labelled, bounded payout linkage rule.

This RE-1 producer rule is not an authoritative venue earned-period reference
and does not change the pure activity bridge. See INTERNATIONAL_MM_LIVE_PILOT.md.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
import re
from urllib.request import Request, urlopen

from weather.market.mm_exchange_reports import INCENTIVE_CASH_ASSET, PAID_INCENTIVE_EVIDENCE_SCHEMA
from weather.market.mm_official_adapter import _plain_sdk_value
from weather.market.mm_stage2_hold import canonical_bytes, digest, utc, write_new
from weather.market.re1_evidence import campaign_root, load_prediction, payout_verdict
from weather.market.re1_transport import ASSETS, HOST, RPC
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration, validate_nonreparse_directory

TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
ASSET_MARKERS = {a.lower(): dict(chain_id=137, asset_address=a.lower(),
    symbol='pUSD' if a.lower() == INCENTIVE_CASH_ASSET['asset_address'] else 'USDC.e', decimals=6) for a in ASSETS}
MAX_ROWS = 2048
MAX_CALLS = 2048
MAX_BYTES = 2_000_000
LINKAGE_BASIS = 'exact_amount_single_condition_unique_credit_v0.1'


def now_utc():
    return datetime.now(timezone.utc)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def micro_units(value):
    amount = Decimal(value)
    require(amount.is_finite() and abs(amount.as_tuple().exponent) <= 2048
            and len(amount.as_tuple().digits) <= 2048, 'amount_precision_budget')
    with localcontext() as context:
        context.prec = max(40, len(amount.as_tuple().digits) + 8)
        return int(amount.quantize(Decimal('0.000001'), rounding=ROUND_HALF_EVEN) * 1_000_000)


def amount_text(units):
    whole, fraction = divmod(units, 1_000_000)
    return f'{whole}.{fraction:06d}' if units else '0'


def native_sum(values):
    amounts = [Decimal(value) for value in values]
    require(all(v.is_finite() for v in amounts), 'amount_not_finite')
    integers = max((max(0, v.adjusted() + 1) for v in amounts), default=0)
    fractions = max((max(0, -v.as_tuple().exponent) for v in amounts), default=0)
    precision = max(40, integers + fractions + len(str(len(amounts))) + 1)
    require(precision <= 4096, 'amount_precision_budget')
    with localcontext() as context:
        context.prec = precision
        return sum(amounts, Decimal(0))


class ReadJournal:
    """In-memory OwnerVenue journal plus hashes of actual header-free requests.

    GET hashes cover method, raw URL target and body, separated by LF. RPC
    request hashes cover the transmitted JSON bytes. Source-level hashes are
    canonical-JSON hashes of ordered per-message hash lists, not invented wire
    payloads. Auth headers never enter this journal.
    """
    def __init__(self, guard, clock):
        self.guard, self.clock = guard, clock
        self.records, self.kind, self.bytes = [], 'accruals', 0

    def record(self, event, **fields):
        row = self.guard.clean(dict(source=self.kind, event=event,
            observed_at_utc=utc(self.clock()).isoformat(), **fields))
        self.bytes += len(canonical_bytes(row))
        require(self.bytes <= MAX_BYTES and len(self.records) < MAX_CALLS * 3, 'journal_budget')
        self.records.append(row)

    def request(self, request):
        require(request.method == 'GET' and request.url.scheme == 'https' and request.url.port in {None, 443}
            and (request.url.host, request.url.path) in {
            ('clob.polymarket.com', '/rewards/user'), ('clob.polymarket.com', '/rewards/user/markets'),
            ('clob.polymarket.com', '/rewards/user/total'), ('data-api.polymarket.com', '/activity')},
            'evidence_read_only_endpoint')
        raw = request.method.encode() + b'\n' + request.url.raw_path + b'\n' + request.content
        self.record('wire_request', method=request.method, url=str(request.url),
            sha256=sha(raw), hash_basis='method_LF_raw_path_LF_body', body_sha256=sha(request.content))

    def summary(self, kind):
        requests = [r['sha256'] for r in self.records if r['source'] == kind and r['event'] in {'wire_request', 'rpc_request'}]
        responses = [r['sha256'] for r in self.records if r['source'] == kind and r['event'] in {'sdk_response', 'rpc_response'}]
        return dict(request_sha256=digest(requests), response_sha256=digest(responses),
            hash_basis='canonical_json_ordered_message_sha256_list', request_count=len(requests), response_count=len(responses))

    def last_response_hash(self, path):
        rows = [r for r in self.records if r['event'] == 'sdk_response' and r['path'] == path]
        require(bool(rows), 'missing_wire_response')
        return rows[-1]['sha256']


def read_pages(paginator, journal, path):
    rows, cursors = [], set()
    terminal = False
    for page in paginator:
        require(not terminal and len(cursors) < 50, 'pagination_budget')
        require(type(page.has_more) is bool and page.has_more == (page.next_cursor is not None), 'pagination_shape')
        require(page.next_cursor not in cursors, 'pagination_cycle')
        cursors.add(page.next_cursor)
        rows.extend((row, journal.last_response_hash(path)) for row in _plain_sdk_value(page.items))
        require(len(rows) <= MAX_ROWS, 'row_budget')
        terminal = not page.has_more
    require(terminal, 'pagination_terminal_missing')
    return rows


def source(scope, kind, journal, clock, *, status='OBSERVED', complete=False, pagination=False, through=None):
    start = scope['cash_start_utc'] if kind == 'wallet_credits' else scope['accrual_start_utc']
    end = scope['accrual_end_utc'] if kind == 'accruals' else scope['cash_end_utc']
    observed = utc(clock())
    return dict(status=status, query_scope='exact_account_asset_period', request_scope=dict(
        maker_address=scope['maker_address'], cash_asset=dict(INCENTIVE_CASH_ASSET), condition_scope='account',
        period_start_utc=start, period_end_utc=end), observed_at_utc=observed.isoformat(),
        coverage_through_utc=utc(through or start).isoformat(), complete=bool(complete),
        pagination_complete=bool(pagination), payout_cycle_complete=observed >= utc(scope['cash_end_utc']),
        **journal.summary(kind))


def normalize_earnings(rows, totals, scope, observed):
    """Keep native precision and both assets. Missing is not completed zero."""
    by_key, total_by_asset, result = {}, {}, []
    start, end = utc(scope['accrual_start_utc']), utc(scope['accrual_end_utc'])
    for row, provenance in rows:
        asset, condition = row['asset_address'].lower(), row['condition_id'].lower()
        amount, rate = Decimal(row['earnings']), Decimal(row['asset_rate'])
        require(row['maker_address'].lower() == scope['maker_address'] and utc(row['date']) == start,
                'earnings_account_or_day')
        require(asset in ASSET_MARKERS and re.fullmatch(r'0x[0-9a-f]{64}', condition), 'earnings_asset_or_condition')
        require(amount.is_finite() and amount >= 0 and rate.is_finite() and rate > 0, 'earnings_amount')
        require((condition, asset) not in by_key, 'earnings_duplicate')
        by_key[condition, asset] = amount
        result.append(dict(maker_address=scope['maker_address'], cash_asset=ASSET_MARKERS[asset],
            observed_at_utc=observed.isoformat(), source_record_sha256=provenance,
            amount=amount_text(micro_units(amount)), venue_amount=format(amount, 'f'),
            asset_rate=format(rate, 'f'), accrual_id='earning-' + digest([scope['maker_address'], condition, asset, start.isoformat()])[:48],
            programme='liquidity_reward', condition_id=condition, period_start_utc=start.isoformat(),
            period_end_utc=end.isoformat(), status='ESTIMATED' if observed < end else 'ACCRUED' if amount else 'COMPLETED_ZERO'))
    for row, provenance in totals:
        asset, amount = row['asset_address'].lower(), Decimal(row['earnings'])
        require(asset in ASSET_MARKERS and asset not in total_by_asset and amount.is_finite() and amount >= 0,
                'earnings_total_asset_or_amount')
        require(row['maker_address'].lower() == scope['maker_address'] and utc(row['date']) == start,
                'earnings_total_scope')
        require(amount == native_sum(v for (c, a), v in by_key.items() if a == asset), 'earnings_total_mismatch')
        total_by_asset[asset] = amount
        # An explicit account-wide zero total proves zero for the selected
        # condition. An omitted asset, or merely an empty page, does not.
        if amount == 0 and (scope['condition_id'], asset) not in by_key:
            result.extend(normalize_earnings([(dict(row, condition_id=scope['condition_id']), provenance)], [], scope, observed)[0])
    return result, set(total_by_asset) == set(ASSET_MARKERS)


def collect_accruals(venue, scope, journal, clock):
    journal.kind = 'accruals'
    retained = {}
    try:
        day = utc(scope['accrual_start_utc']).date().isoformat()
        rows = read_pages(venue.client.list_user_earnings_for_day(date=day), journal, '/rewards/user')
        retained['rows'] = [r for r, _ in rows]
        configurations = read_pages(venue.client.list_user_earnings_and_markets_config(date=day), journal, '/rewards/user/markets')
        retained['market_configurations'] = [r for r, _ in configurations]
        totals = _plain_sdk_value(venue.client.get_total_earnings_for_user_for_day(date=day))
        retained['total_earnings'] = totals
        require(len(totals) <= MAX_ROWS, 'earnings_total_budget')
        provenance = journal.last_response_hash('/rewards/user/total')
        observed = utc(clock())
        normalized, all_assets = normalize_earnings(rows, [(r, provenance) for r in totals], scope, observed)
        expected = {(r['condition_id'].lower(), r['asset_address'].lower()): Decimal(r['earnings']) for r, _ in rows}
        configured = {}
        for row, _ in configurations:
            require(row['maker_address'].lower() == scope['maker_address'], 'configuration_account')
            for earning in row['earnings']:
                key = row['condition_id'].lower(), earning['asset_address'].lower()
                require(key not in configured and key[1] in ASSET_MARKERS, 'configuration_duplicate_or_asset')
                configured[key] = Decimal(earning['earnings'])
        require({k: v for k, v in expected.items() if v} == {k: v for k, v in configured.items() if v}, 'configuration_earnings_mismatch')
        closed = observed >= utc(scope['accrual_end_utc'])
        src = source(scope, 'accruals', journal, clock, complete=closed and all_assets,
            pagination=True, through=min(observed, utc(scope['accrual_end_utc'])))
        if not all_assets:
            src['reason'] = 'asset_total_missing'
        return src, normalized, retained
    except Exception as exc:
        src = source(scope, 'accruals', journal, clock, status='FAILED')
        src['failure_type'] = type(exc).__name__
        return src, [], retained


def collect_distribution_candidates(venue, scope, journal, clock):
    """Retain REWARD candidates; the separate producer rule decides their day."""
    journal.kind = 'distributions'
    rows, pagination, failure = [], False, None
    try:
        end = min(utc(scope['cash_end_utc']), utc(clock()))
        start = utc(scope['accrual_end_utc'])
        require(start < end, 'activity_window_not_open')
        rows = read_pages(venue.client.list_activity(user=scope['maker_address'],
            activity_types=['REWARD'], start=int(start.timestamp()),
            end=int(end.timestamp()) - 1, sort_by='TIMESTAMP', sort_direction='ASC', page_size=500), journal, '/activity')
        for row, _ in rows:
            require(row['wallet'].lower() == scope['maker_address'] and row['type'] == 'REWARD', 'activity_scope')
            require(start <= utc(row['timestamp']) < end, 'activity_time')
            hex32(row['transaction_hash'])
        pagination = True
    except Exception as exc:
        failure = type(exc).__name__
    src = source(scope, 'distributions', journal, clock, status='OBSERVED' if pagination else 'FAILED', pagination=pagination)
    src.update(reason='linkage_not_evaluated', linkage_basis=LINKAGE_BASIS,
        venue_earned_period_reference=False, activity_observed_at_utc=src['observed_at_utc'],
        activity_request_scope=dict(maker_address=scope['maker_address'],
            period_start_utc=scope['accrual_end_utc'], period_end_utc=end.isoformat()),
        candidate_endpoint='https://data-api.polymarket.com/activity', candidate_pagination_complete=pagination,
        failure_type=failure)
    return src, [dict(row, source_record_sha256=provenance) for row, provenance in rows]


def link_reward_payment(scope, accrual_source, accruals, raw_earnings, activity_source, activities, wallet_source, credits, clock):
    """Apply the reviewed RE-1 rule; never allocate unexplained wallet credits."""
    pusd = [r for r in accruals if r['cash_asset'] == INCENTIVE_CASH_ASSET]
    cash = [r for r in credits if r['cash_asset'] == INCENTIVE_CASH_ASSET]
    other_cash = [r for r in credits if r['cash_asset'] != INCENTIVE_CASH_ASSET]
    other = [r for r in accruals if r['condition_id'] != scope['condition_id'] and Decimal(r['venue_amount']) > 0]
    raw = raw_earnings.get('rows')
    try:
        venue_total = None if raw is None else format(native_sum(r['earnings'] for r in raw
            if r['asset_address'].lower() == INCENTIVE_CASH_ASSET['asset_address']), 'f')
        observed_other = [r for r in raw or [] if r['condition_id'].lower() != scope['condition_id'] and Decimal(r['earnings']) > 0]
        other_observations = dict(count=None if raw is None else len(observed_other), total={
            marker['symbol']: None if raw is None else format(native_sum(r['earnings'] for r in observed_other
                if r['asset_address'].lower() == asset), 'f') for asset, marker in ASSET_MARKERS.items()})
    except (KeyError, TypeError, ValueError, ArithmeticError):
        venue_total = None
        other_observations = dict(count=None, total=None)
    units = sum(micro_units(r['amount']) for r in pusd) if accrual_source['complete'] else None
    closed = utc(clock()) >= utc(scope['cash_end_utc'])
    credit_fields = ('credited_at_utc', 'transaction_hash', 'log_index', 'amount')
    diagnostics = dict(reward_day=utc(scope['accrual_start_utc']).date().isoformat(),
        accrual_total_venue=venue_total, accrual_total_units=units,
        other_condition_accruals=other_observations,
        reward_activity_rows=[dict(timestamp_utc=utc(r['timestamp']).isoformat(),
            transaction_hash=r['transaction_hash'], amount=r['amount']) for r in activities if r['type'] == 'REWARD'],
        pusd_credits_in_window=[{k: r[k] for k in credit_fields} for r in cash],
        usdc_e_credits_in_window=[{k: r[k] for k in credit_fields} for r in other_cash],
        cash_window_closed=closed, linkage_rule_outcome='accruals_not_final')
    src = activity_source
    src.update(complete=False, observed_at_utc=utc(clock()).isoformat())
    def finish(reason, distributions=(), *, complete=False):
        diagnostics['linkage_rule_outcome'] = src['reason'] = reason
        src['complete'] = complete
        if complete:
            src.update(status='OBSERVED', pagination_complete=True, payout_cycle_complete=True,
                coverage_through_utc=min(utc(scope['cash_end_utc']), utc(src['activity_observed_at_utc'])).isoformat())
        return list(distributions), diagnostics
    if accrual_source['status'] != 'OBSERVED' or not accrual_source['complete'] or any(
            r['status'] not in {'ACCRUED', 'COMPLETED_ZERO'} for r in pusd):
        return finish('accruals_not_final')
    if other:
        return finish('other_condition_accruals')
    if not units or units < 0:
        return finish('nonpositive_accrual')
    if (not src['candidate_pagination_complete'] or src['failure_type'] is not None or
            utc(src['activity_request_scope']['period_end_utc']) < utc(scope['cash_end_utc'])):
        return finish('activity_coverage_incomplete')
    joined, unjoined = [], []
    for activity in activities:
        matches = [c for c in cash if c['status'] == 'CONFIRMED' and c['transaction_hash'] == activity['transaction_hash'].lower()]
        activity['join_status'] = 'joined' if len(matches) == 1 else 'unjoined'
        activity['matching_credit_ids'] = [c['credit_id'] for c in matches]
        (joined if len(matches) == 1 else unjoined).append((activity, matches))
    if unjoined:
        return finish('activity_credit_join_failed')
    if not activities:
        if other_cash: return finish('non_pusd_credit_present')
        if cash: return finish('wallet_credit_unattributed')
        if not closed: return finish('cash_window_open')
        if not wallet_source['complete'] or not wallet_source['pagination_complete']:
            return finish('wallet_coverage_incomplete')
        return finish('not_paid', complete=True)
    matches = [(a, cs[0]) for a, cs in joined if abs(micro_units(cs[0]['amount']) - units) <= 1]
    if not matches: return finish('no_amount_match')
    if len(matches) != 1: return finish('ambiguous_amount_match')
    if not wallet_source['complete'] or not wallet_source['pagination_complete']:
        return finish('wallet_coverage_incomplete')
    activity, credit = matches[0]
    if any(c['credit_id'] != credit['credit_id'] for c in cash):
        return finish('wallet_credit_unattributed')
    # Zero rows for other conditions do not receive a fabricated distribution.
    targets = [r for r in pusd if r['condition_id'] == scope['condition_id'] and micro_units(r['amount']) > 0]
    if len(targets) != 1: return finish('accrual_identity_ambiguous')
    accrual = targets[0]
    distribution = dict(maker_address=scope['maker_address'], cash_asset=dict(INCENTIVE_CASH_ASSET),
        observed_at_utc=src['observed_at_utc'], source_record_sha256=activity['source_record_sha256'],
        amount=credit['amount'], distribution_id='reward-' + digest([
            diagnostics['reward_day'], credit['transaction_hash'], credit['log_index']])[:48],
        accrual_id=accrual['accrual_id'], programme='liquidity_reward', condition_id=scope['condition_id'],
        status='PAID', credit_id=credit['credit_id'], linkage_basis=LINKAGE_BASIS,
        activity_sha256=activity['source_record_sha256'], activity_timestamp_utc=utc(activity['timestamp']).isoformat(),
        matched_amount_delta_units=micro_units(credit['amount']) - units)
    return finish('matched', [distribution], complete=True)


class RpcRangeLimit(RuntimeError):
    pass


class PolygonReads:
    def __init__(self, journal, *, opener=urlopen):
        self.journal, self.opener, self.count = journal, opener, 0

    def call(self, method, params):
        require(method in {'eth_chainId', 'eth_getBlockByNumber', 'eth_getLogs'}, 'rpc_read_only_method')
        self.count += 1
        require(self.count <= MAX_CALLS, 'rpc_call_budget')
        assert_no_ambient_proxy_configuration()
        payload = dict(jsonrpc='2.0', id=self.count, method=method, params=params)
        raw = json.dumps(payload, separators=(',', ':')).encode()
        self.journal.record('rpc_request', request=payload, url=RPC, sha256=sha(raw), hash_basis='transmitted_json_bytes')
        request = Request(RPC, data=raw, method='POST', headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        with self.opener(request, timeout=10) as response:
            body = response.read(MAX_BYTES + 1)
            self.journal.record('rpc_response', id=self.count, status=response.status, length=len(body), sha256=sha(body))
            require(response.status == 200 and response.geturl() == RPC and len(body) <= MAX_BYTES, 'rpc_response_refused')
        value = json.loads(body)
        require(value.get('jsonrpc') == '2.0' and type(value.get('id')) is int and value['id'] == self.count, 'rpc_envelope')
        if 'error' in value:
            error = value['error']
            if isinstance(error, dict) and error.get('code') in {-32005, -32602, -32000} and re.search(
                    r'range|limit|too many|too large', str(error.get('message', '')), re.I):
                raise RpcRangeLimit('rpc_range_limit')
            raise RuntimeError('rpc_error')
        require('result' in value, 'rpc_result_missing')
        return value['result'], sha(body)


def quantity(value):
    require(isinstance(value, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', value), 'rpc_quantity')
    return int(value, 16)


def hex32(value):
    require(isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{64}', value), 'rpc_bytes32')
    return value.lower()


def collect_wallet(scope, journal, clock, *, opener=urlopen):
    journal.kind = 'wallet_credits'
    rpc, blocks, chunks, credits = PolygonReads(journal, opener=opener), {}, [], {}
    proof, through = {}, utc(scope['cash_start_utc'])
    failures = []
    def block(tag):
        if tag not in blocks:
            row, provenance = rpc.call('eth_getBlockByNumber', [tag, False])
            number, timestamp = quantity(row['number']), quantity(row['timestamp'])
            require(tag == 'finalized' or number == quantity(tag), 'block_number_mismatch')
            require(timestamp <= utc(clock()).timestamp(), 'block_in_future')
            blocks[tag] = dict(number=number, timestamp=timestamp, hash=hex32(row['hash']), source_record_sha256=provenance)
        return blocks[tag]
    def lower_bound(timestamp, tip):
        lo, hi = 0, tip['number'] + 1
        while lo < hi:
            mid = (lo + hi) // 2
            if block(hex(mid))['timestamp'] < timestamp: lo = mid + 1
            else: hi = mid
        return lo
    def walk(first, last, topic):
        try:
            logs, provenance = rpc.call('eth_getLogs', [dict(address=list(ASSET_MARKERS),
                fromBlock=hex(first), toBlock=hex(last), topics=[TRANSFER, None, topic])])
        except RpcRangeLimit:
            if first == last:
                chunks.append(dict(first_block=first, last_block=last, complete=False, failure_type='RpcRangeLimit'))
            else:
                mid = (first + last) // 2
                walk(first, mid, topic)
                walk(mid + 1, last, topic)
            return
        except Exception as exc:
            chunks.append(dict(first_block=first, last_block=last, complete=False, failure_type=type(exc).__name__))
            return
        accepted = {}
        try:
            require(isinstance(logs, list) and len(logs) <= MAX_ROWS, 'logs_shape_or_budget')
            for log in logs:
                asset, height = log['address'].lower(), quantity(log['blockNumber'])
                require(asset in ASSET_MARKERS and first <= height <= last and log['removed'] is False, 'log_scope')
                topics = log['topics']
                require(isinstance(topics, list) and len(topics) == 3 and hex32(topics[0]) == TRANSFER and
                        hex32(topics[2]) == topic and hex32(topics[1])[2:26] == '0' * 24, 'transfer_topics')
                header = block(hex(height))
                require(hex32(log['blockHash']) == header['hash'], 'log_block_hash')
                credited = datetime.fromtimestamp(header['timestamp'], timezone.utc)
                require(utc(scope['cash_start_utc']) <= credited < utc(scope['cash_end_utc']), 'log_time')
                tx, index = hex32(log['transactionHash']), quantity(log['logIndex'])
                amount = int(hex32(log['data']), 16)
                if amount == 0: continue
                key = f'137:{tx}:{index}'
                whole, fraction = divmod(amount, 1_000_000)
                row = dict(maker_address=scope['maker_address'], cash_asset=ASSET_MARKERS[asset],
                    chain_id=137, transaction_hash=tx, log_index=index, credit_id=key, block_number=height,
                    block_hash=header['hash'], credited_at_utc=credited.isoformat(), status='CONFIRMED',
                    amount=f'{whole}.{fraction:06d}', source_record_sha256=provenance,
                    observed_at_utc=utc(clock()).isoformat())
                require(key not in credits and key not in accepted, 'duplicate_credit')
                accepted[key] = row
            require(len(credits) + len(accepted) <= MAX_ROWS, 'credit_budget')
        except Exception as exc:
            chunks.append(dict(first_block=first, last_block=last, complete=False, failure_type=type(exc).__name__, response_sha256=provenance))
            return
        credits.update(accepted)
        chunks.append(dict(first_block=first, last_block=last, complete=True, log_count=len(logs), response_sha256=provenance))
    try:
        chain, _ = rpc.call('eth_chainId', [])
        require(quantity(chain) == 137, 'rpc_chain')
        tip = block('finalized')
        start, end = utc(scope['cash_start_utc']), utc(scope['cash_end_utc'])
        first, after = lower_bound(start.timestamp(), tip), lower_bound(end.timestamp(), tip)
        proof = dict(first_block=first, last_block=after - 1, finalized=tip,
            start_predecessor=block(hex(first - 1)) if first else None,
            start_block=block(hex(first)) if first <= tip['number'] else None,
            end_block=block(hex(after)) if after <= tip['number'] else None)
        topic = '0x' + scope['maker_address'][2:].rjust(64, '0')
        for begin in range(first, after, 1000):
            walk(begin, min(begin + 999, after - 1), topic)
            if rpc.count >= MAX_CALLS: break
        # Re-read the finalized anchor at its numeric height to detect a
        # changed chain view; do not substitute a latest/unfinalized head.
        anchor, _ = rpc.call('eth_getBlockByNumber', [hex(tip['number']), False])
        require(hex32(anchor['hash']) == tip['hash'] and quantity(anchor['number']) == tip['number'] and
                quantity(anchor['timestamp']) == tip['timestamp'], 'finalized_anchor_changed')
        cursor = first
        for chunk in chunks:
            if not chunk['complete'] or chunk['first_block'] != cursor: break
            cursor = chunk['last_block'] + 1
        covered = cursor == after
        if covered:
            through = min(end, datetime.fromtimestamp(tip['timestamp'], timezone.utc))
        elif cursor > first:
            through = datetime.fromtimestamp(block(hex(cursor))['timestamp'], timezone.utc)
        complete = covered and tip['timestamp'] >= end.timestamp()
    except Exception as exc:
        failures.append(type(exc).__name__)
        covered = complete = False
    src = source(scope, 'wallet_credits', journal, clock, complete=complete, pagination=covered, through=through)
    src.update(block_bounds=proof, chunks=chunks, failures=failures, chain_id=137,
               assets=list(ASSET_MARKERS), endpoint=RPC, block_headers=list(blocks.values()))
    return src, list(credits.values())


def collect_evidence(venue, prediction, *, clock=now_utc, opener=urlopen):
    require(venue.readonly and not venue.preflight, 'readonly_venue_required')
    maker = prediction['scope']['maker_address'].lower()
    require(maker == venue.maker.lower() and re.fullmatch(r'0x[0-9a-f]{40}', maker), 'collection_account_changed')
    start = utc(prediction['reward_day'] + 'T00:00:00Z')
    scope = dict(maker_address=maker, condition_id=prediction['condition_id'].lower(), cash_asset=dict(INCENTIVE_CASH_ASSET),
        accrual_start_utc=start.isoformat(), accrual_end_utc=(start + timedelta(days=1)).isoformat(),
        cash_start_utc=start.isoformat(), cash_end_utc=(start + timedelta(days=3)).isoformat())
    journal = ReadJournal(venue.guard, clock)
    hooks = []
    for name in ('secure_clob', 'clob', 'data', 'gamma'):
        transport = getattr(venue.client._ctx, name, None)
        if transport is not None:
            hooks.append((transport._client, {k: list(v) for k, v in transport._client.event_hooks.items()}))
    try:
        venue.set_journal(journal)
        for http, _ in hooks:
            http.event_hooks['request'].append(journal.request)
        accrual_source, accruals, raw_earnings = collect_accruals(venue, scope, journal, clock)
        distribution_source, candidates = collect_distribution_candidates(venue, scope, journal, clock)
        wallet_source, credits = collect_wallet(scope, journal, clock, opener=opener)
    finally:
        for http, previous in hooks:
            http.event_hooks = previous
    if venue.journal_failed:
        accrual_source.update(complete=False, status='FAILED', reason='sdk_journal_failed')
        distribution_source.update(complete=False, reason='sdk_journal_failed')
    distributions, diagnostics = link_reward_payment(scope, accrual_source, accruals, raw_earnings,
        distribution_source, candidates, wallet_source, credits, clock)
    # v0.1 only represents native pUSD. Preserve USDC.e separately, never
    # relabel or convert it into pUSD to satisfy the existing matcher.
    evidence = dict(schema_version=PAID_INCENTIVE_EVIDENCE_SCHEMA, scope=scope, as_of_utc=utc(clock()).isoformat(),
        sources=dict(accruals=accrual_source, distributions=distribution_source, wallet_credits=wallet_source),
        accruals=[r for r in accruals if r['cash_asset'] == INCENTIVE_CASH_ASSET], distributions=distributions,
        wallet_credits=[r for r in credits if r['cash_asset'] == INCENTIVE_CASH_ASSET], excluded_external_credit_ids=[],
        asset_observations={a: dict(accruals=[r for r in accruals if r['cash_asset']['asset_address'] == a],
            wallet_credits=[r for r in credits if r['cash_asset']['asset_address'] == a]) for a in ASSET_MARKERS},
        distribution_candidates=candidates, sdk_earnings=raw_earnings, wire_journal=journal.records,
        prediction_sha256=digest(prediction), payout_diagnostics=diagnostics,
        limitations=['reviewed_re1_linkage_rule_not_venue_earned_period_reference',
            'reconciler_accepts_native_pusd_only', 'reconciler_requires_closed_cash_window'])
    return venue.guard.clean(evidence)


def run_collect_evidence(args):
    path = args.prediction.absolute()
    root = validate_nonreparse_directory(campaign_root())
    require(path.name == 'prediction.json' and path.parent.parent == root and
            re.fullmatch(r'session-[1-6]', path.parent.name), 'prediction_outside_campaign')
    validate_nonreparse_directory(path.parent)
    prediction = load_prediction(path, now=now_utc())
    require(prediction['mode'] == 'live', 'rehearsal_is_not_payout_evidence')
    from weather.market.re1_transport import load_owner_credentials, build_client, OwnerVenue
    # Reuse the existing read-only collection credential permission. No change
    # to the live transport, heartbeat, credential loader or preflight mode.
    fields, guard = load_owner_credentials('collect-payout')
    require(fields['FUNDER_ADDRESS'].lower() == prediction['scope']['maker_address'].lower(), 'collection_account_changed')
    client = build_client(fields, readonly=True)
    try:
        venue = OwnerVenue(client, fields, guard, condition=prediction['condition_id'], readonly=True)
        evidence = collect_evidence(venue, prediction)
        # The file must survive malformed/partial earnings as refused evidence.
        # Accrued diagnostics are computed by collect-payout's separate read;
        # this command reports only the paid-evidence decision.
        result = payout_verdict(prediction, {'rows': []}, evidence)
        destination = path.parent / ('payout-evidence-' + now_utc().strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        file_hash = write_new(destination, guard.clean(evidence))
        guard.print(dict(payment_evidence_path=str(destination), payment_evidence_sha256=file_hash,
            verdict=result['verdict'], paid=result['paid'], k=result['k'],
            reconciliation_status=result['payment_reconciliation']['status'],
            blockers=result['payment_reconciliation']['blockers'], limitations=evidence['limitations']))
        return 0 if result['payment_reconciliation']['complete'] else 2
    finally:
        client.close()
