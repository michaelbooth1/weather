"""Offline accuracy gate on pinned LFC journal bytes and saved, attributed receipts.

The gate certifies agreement for a config/input/code binding, never profitability
or live authority. Raw receipt files remain hashed CLI inputs. No source fetches.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
from io import BytesIO
import json
from pathlib import Path

from weather.backtesting.t1_simulator import replay
from weather.backtesting.t1_types import (ONE, ZERO, canonical, decimal_context, digest, levels,
                                         number, source_hash, utc)

LFC_PIN = '124603578f393827fa1b67bd978f6e3b02048ae9'
# Wire identifier from schema_registry_data.py at LFC_PIN; do not import live code.
PIN_JOURNAL_VERSION = 'mm_stage2_hold_v0.1'
PIN_LEDGER_VERSION = 'lfc_l_ledger_v0.1'
MAX_JOURNAL_LINE_BYTES = 1024 * 1024
MAX_JOURNAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_LIFECYCLE_BYTES = 16 * 1024 * 1024
LIFECYCLE_EVENTS = frozenset((
    'opened', 'terminal', 'submit_market_snapshot', 'submit_request', 'submit_response', 'lfc_queue_ahead',
    'cancel_request', 'cancel_response', 'cleanup_cancel_response', 'cleanup_cancel_all_response',
    'cleanup_cancel_ours_response', 'cleanup_cancel_request', 'cleanup_cancel_all_request',
    'cleanup_cancel_ours_request',
))


def clob_time(value):
    """CLOB wire match_time is Unix seconds; normalized exports may use ISO UTC."""
    text = str(value)
    return datetime.fromtimestamp(int(text), timezone.utc) if text.isdigit() else utc(value)


@dataclass(frozen=True)
class Tolerance:
    reward_absolute: str
    reward_relative: str
    fill_absolute_shares: str
    fill_relative: str
    markout_absolute_per_share: str
    receipt_reconciliation_absolute: str
    min_filled_orders: int
    min_paid_reward: str

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key == 'min_filled_orders':
                if type(value) is not int or value < 1:
                    raise ValueError('positive fill evidence floor required')
            else:
                number(value)
        if number(self.min_paid_reward) <= ZERO:
            raise ValueError('positive paid reward floor required')


@dataclass(frozen=True)
class JournalEvidence:
    rows: list
    sha256: str
    byte_count: int
    record_count: int


def read_pin_evidence(source):
    """Stream all canonical chain bytes; retain only quote lifecycle records.

    source is bytes for a small fixture, or an explicit path for a pilot journal.
    Skipped observations still participate in sequence, clock and hash checks.
    """
    previous, rows, last_time = None, [], None
    whole_hash, byte_count, count, retained_bytes = hashlib.sha256(), 0, 0, 0
    first_event, last_event = None, None
    handle = BytesIO(source) if isinstance(source, bytes) else Path(source).open('rb')
    with handle:
        while True:
            line = handle.readline(MAX_JOURNAL_LINE_BYTES + 1)
            if not line:
                break
            byte_count += len(line)
            if len(line) > MAX_JOURNAL_LINE_BYTES or byte_count > MAX_JOURNAL_BYTES:
                raise ValueError('journal exceeds bounded receipt limits')
            row = json.loads(line)
            at = utc(row['recorded_at_utc'])
            if (canonical(row) != line or row['schema_version'] != PIN_JOURNAL_VERSION
                    or row['kind'] != 'journal' or row['sequence'] != count
                    or row['previous_sha256'] != previous or last_time is not None and at < last_time):
                raise ValueError('invalid pinned journal chain or clock')
            previous, last_time = hashlib.sha256(line).hexdigest(), at
            whole_hash.update(line)
            first_event = row['event'] if count == 0 else first_event
            last_event = row['event']
            count += 1
            keep = (row['event'] in LIFECYCLE_EVENTS
                    and not (row['event'] == 'lfc_queue_ahead' and row.get('phase') != 'placement'))
            if keep:
                retained_bytes += len(line)
                if retained_bytes > MAX_LIFECYCLE_BYTES:
                    raise ValueError('retained journal lifecycle exceeds bounded receipt limit')
                rows.append(row)
    if not rows or first_event != 'opened' or last_event != 'terminal':
        raise ValueError('journal missing opened or terminal record')
    terminal = rows[-1]
    if (rows[0]['mode'] not in ('live', 'replay') or terminal['cleanup_ok'] is not True
            or terminal['evidence_complete'] is not True or terminal['unknown_submit'] is not False
            or terminal['inventory_proven'] is not True):
        raise ValueError('incomplete session journal')
    return JournalEvidence(rows, whole_hash.hexdigest(), byte_count, count)


def read_pin_journal(source):
    """Verified lifecycle rows from the exact pin writer's full hash chain."""
    return read_pin_evidence(source).rows


def pin_latency_evidence(raw):
    """Retain observation -> decision -> ACK samples from the pinned writer format.

    The file hash of this returned projection becomes latency_source_sha256.
    This is measurement/export only: it does not choose the frozen latency.
    """
    evidence = read_pin_evidence(raw)
    rows = evidence.rows
    snapshot, observed_start, request, samples = None, None, None, []
    for row in rows:
        if row['event'] == 'submit_market_snapshot':
            # Pin observed_at_utc is HTTP batch START. Data is available only
            # once this completed snapshot has been journalled.
            observed_start = row['snapshot']['observed_at_utc']
            snapshot = row['recorded_at_utc']
            if utc(observed_start) > utc(snapshot):
                raise ValueError('snapshot collection starts after availability')
        elif row['event'] == 'submit_request':
            if request is not None or snapshot is None:
                raise ValueError('unpaired latency request')
            request = row['recorded_at_utc']
        elif row['event'] == 'submit_response':
            if request is None or not utc(snapshot) <= utc(request) <= utc(row['recorded_at_utc']):
                raise ValueError('unpaired or regressed latency sample')
            samples.append({'observed_at': snapshot, 'decided_at': request,
                            'acknowledged_at': row['recorded_at_utc'], 'collection_started_at': observed_start})
            request = None
    if request is not None or not samples:
        raise ValueError('complete latency samples required')
    return {'kind': 'observation_to_order_ack', 'sample_count': len(samples), 'samples': samples,
            'synthetic': rows[0]['mode'] != 'live', 'journal_sha256': evidence.sha256,
            'journal_pin': LFC_PIN}


def pin_commands(rows, condition_id):
    """Adapt pin's real submit_request/response and acknowledged cancel lifecycle.

    Modelled arrival is observation plus declared latency, not the ACK timestamp.
    ACKs supply order identity only. Unknown/ambiguous posts refuse the session.
    Queue-placement rows cross-check the acknowledged order mapping.
    """
    scope = rows[0]['scope']
    if scope['condition_id'] != condition_id or len(scope['token_ids']) != 2:
        raise ValueError('journal condition mapping mismatch')
    tokens = scope['token_ids']
    snapshot, available_at, pending, commands, known = None, None, None, [], {}
    pending_cancels, pending_global_cancel = {}, None
    for row in rows:
        event = row['event']
        if event == 'submit_market_snapshot':
            snapshot = row['snapshot']
            available_at = row['recorded_at_utc']
            if snapshot['condition_id'] != condition_id or snapshot['token_ids'] != tokens:
                raise ValueError('submit snapshot token mapping mismatch')
        elif event == 'submit_request':
            if pending is not None or snapshot is None:
                raise ValueError('ambiguous submit sequence')
            request = row['request']
            if request['side'] != 'BUY' or request['post_only'] is not True or request['token_id'] not in tokens:
                raise ValueError('unsupported pilot order shape')
            if (utc(snapshot['observed_at_utc']) > utc(available_at)
                    or utc(available_at) > utc(row['recorded_at_utc'])):
                raise ValueError('future submit snapshot')
            pending = {'request': request, 'observed_at': available_at, 'decided_at': row['recorded_at_utc']}
        elif event == 'submit_response':
            response = row['response']
            oid = response.get('orderID') or response.get('order_id') or response.get('id')
            if pending is None or not oid or response.get('status') not in ('live', 'matched'):
                raise ValueError('unbound submit response')
            oid = str(oid)
            if oid in known:
                raise ValueError('duplicate order acknowledgment')
            request = pending['request']
            command = {'kind': 'post', 'id': oid, 'condition_id': condition_id,
                       'outcome': 'YES' if request['token_id'] == tokens[0] else 'NO',
                       'observed_at': pending['observed_at'], 'decided_at': pending['decided_at'],
                       'expires_at': clob_time(request['expiration']).isoformat(),
                       'price': request['price'], 'size': request['size']}
            commands.append(command)
            known[oid] = command
            pending = None
        elif event == 'lfc_queue_ahead' and row['phase'] == 'placement':
            command = known.get(row['order_id'])
            if (command is None or number(command['price']) != number(row['price'])
                    or number(command['size']) != number(row['own_size'])
                    or tokens[0 if command['outcome'] == 'YES' else 1] != row['token_id']):
                raise ValueError('LFC placement binding mismatch')
        elif event in ('cancel_request', 'cleanup_cancel_request'):
            oid = row.get('order_id') or row.get('request', {}).get('order_id')
            if oid:
                pending_cancels[oid] = row['recorded_at_utc']
        elif event in ('cleanup_cancel_all_request', 'cleanup_cancel_ours_request'):
            pending_global_cancel = row['recorded_at_utc']
        elif event in ('cancel_response', 'cleanup_cancel_response', 'cleanup_cancel_all_response',
                       'cleanup_cancel_ours_response'):
            response = row['response']
            canceled = response.get('canceled', [])
            if not isinstance(canceled, list):
                raise ValueError('invalid cancellation response')
            # Cleanup per-order and cancel-all acknowledgments may repeat IDs.
            for oid in canceled:
                if oid not in known:
                    raise ValueError('cancel of unknown session order')
                if any(c['kind'] == 'cancel' and c['id'] == oid for c in commands):
                    continue
                request_time = pending_cancels.pop(oid, None) or pending_global_cancel
                if request_time is None:
                    raise ValueError('cancel acknowledgment lacks its request')
                commands.append({'kind': 'cancel', 'id': oid, 'observed_at': request_time,
                                 'decided_at': request_time})
    if pending is not None or len(known) != rows[-1]['post_count']:
        raise ValueError('missing submit acknowledgment')
    canceled_ids = {c['id'] for c in commands if c['kind'] == 'cancel'}
    if not set(known) <= canceled_ids:
        # A fully filled order may be absent from cancellation ACKs; caller must
        # provide its terminal matched size in the saved CLOB receipts.
        terminal_ids = set(rows[-1].get('order_ids', []))
        if not set(known) <= terminal_ids:
            raise ValueError('unbound terminal order identities')
    return commands, known


def clob_fills(receipt, known, tokens, *, account_id):
    """Saved CLOB /data/trades rows; count our maker_orders, never taker volume.

    Duplicate trade IDs on pagination boundaries are allowed only if identical.
    A transaction hash is not a fill ID: multiple fills in a transaction survive.
    """
    if (receipt['endpoint'] != 'https://clob.polymarket.com/data/trades'
            or receipt['complete'] is not True or receipt['next_cursor'] != 'LTE='):
        raise ValueError('incomplete CLOB trades pagination')
    seen, out = {}, []
    for row in receipt['rows']:
        key = str(row['id'])
        if key in seen:
            if seen[key] != row:
                raise ValueError('conflicting CLOB trade ID')
            continue
        seen[key] = row
        for maker in row['maker_orders']:
            oid = maker['order_id']
            if oid not in known:
                continue
            if str(maker['maker_address']).lower() != str(account_id).lower():
                raise ValueError('own fill maker account mismatch')
            if row['status'] != 'CONFIRMED':
                raise ValueError('failed or unknown own trade status')
            command = known[oid]
            asset = maker.get('asset_id', row.get('asset_id'))
            if asset != tokens[0 if command['outcome'] == 'YES' else 1]:
                raise ValueError('own fill token mismatch')
            if row['market'] != command['condition_id'] or maker['side'] != 'BUY':
                raise ValueError('own fill market or maker side mismatch')
            p, size = number(maker['price']), number(maker['matched_amount'])
            if p != number(command['price']) or size <= ZERO:
                raise ValueError('own fill price or size mismatch')
            matched_at = clob_time(row['match_time'])
            if str(row['match_time']).isdigit():
                precision = D(1)  # raw CLOB match_time is integer Unix seconds
                if 'match_time_precision_seconds' in row and number(row['match_time_precision_seconds']) != precision:
                    raise ValueError('CLOB integer seconds require a one-second time interval')
            else:
                precision = number(row['match_time_precision_seconds'], maximum=D(1))
            latest_at = matched_at + timedelta(seconds=float(precision))
            decision, expiry = utc(command['decided_at']), utc(command['expires_at'])
            if (matched_at >= expiry or latest_at < decision
                    or precision > ZERO and latest_at == decision):
                raise ValueError('CLOB fill outside submitted order lifetime')
            out.append({'order_id': oid, 'condition_id': command['condition_id'], 'outcome': command['outcome'],
                        'price': p, 'size': size, 'at': max(matched_at, decision),
                        'at_end': min(latest_at, expiry), 'trade_id': key})
    for oid, command in known.items():
        if sum((r['size'] for r in out if r['order_id'] == oid), ZERO) > number(command['size']):
            raise ValueError('own fills exceed posted size')
    return out


def observed_markouts(fills, events, config):
    """Bound markouts over each CLOB timestamp interval, rather than inventing milliseconds."""
    values = defaultdict(lambda: [ZERO, ZERO, ZERO])
    for fill in fills:
        due = fill['at'] + timedelta(seconds=config.markout_seconds)
        due_end = fill['at_end'] + timedelta(seconds=config.markout_seconds)
        books = sorted((r for r in events if r['kind'] == 'book' and r['condition_id'] == fill['condition_id']
                        and utc(r['observed_at']) >= due), key=lambda r: utc(r['at']))
        marks, frontier, covered = [], None, False
        for candidate in books:
            observed = utc(candidate['observed_at'])
            if frontier is not None and observed <= frontier:
                continue  # an earlier available book dominates this observation
            earliest_horizon = due if frontier is None else max(due, frontier)
            if D(str((utc(candidate['at']) - earliest_horizon).total_seconds())) > number(config.mark_max_delay_seconds):
                raise ValueError('actual fill lacks bounded horizon book')
            side = candidate[fill['outcome']]
            mid = (max(r['price'] for r in levels(side['bids']))
                   + min(r['price'] for r in levels(side['asks']))) / 2
            marks.append(mid - fill['price'])
            frontier = observed
            if observed >= due_end:
                covered = True
                break
        if not covered:
            raise ValueError('actual fill lacks bounded horizon book')
        values[fill['order_id']][0] += min(marks) * fill['size']
        values[fill['order_id']][1] += max(marks) * fill['size']
        values[fill['order_id']][2] += fill['size']
    return {oid: (low / size, high / size) for oid, (low, high, size) in values.items()}


def ledger_snapshot_fills(snapshot, known, tokens, *, session_id, minimum_at, epsilon):
    """Read pin Ledger.snapshot() directly; its L is cost-at-risk, not wallet cash."""
    if (snapshot['schema_version'] != PIN_LEDGER_VERSION or snapshot['kind'] != 'lfc_l_ledger'
            or snapshot['mismatches'] != 0 or snapshot['history_rows'] < 1
            or utc(snapshot['recorded_at_utc']) < utc(minimum_at)):
        raise ValueError('incomplete pinned ledger snapshot')
    source_hash(snapshot['history_last_sha256'])
    filled_cost, resting_cost, quantities, seen = ZERO, ZERO, {}, set()
    for leg in snapshot['legs']:
        p, size = number(leg['price'], maximum=ONE), number(leg['size'])
        matched = number(leg['size_matched'], maximum=size)
        if leg['status'] == 'terminal':
            filled_cost += p * matched
        elif leg['status'] in ('intent', 'open'):
            resting_cost += p * size
        else:
            raise ValueError('unknown pinned ledger leg status')
        oid = leg['order_id']
        if oid is not None:
            if oid in seen:
                raise ValueError('duplicate pinned ledger order')
            seen.add(oid)
        if leg['session_id'] != session_id:
            if oid in known:
                raise ValueError('foreign ledger session for own order')
            continue
        command = known.get(oid)
        if (command is None or leg['status'] != 'terminal' or leg['condition_id'] != command['condition_id']
                or leg['token_id'] != tokens[0 if command['outcome'] == 'YES' else 1]
                or p != number(command['price']) or size != number(command['size'])):
            raise ValueError('pinned ledger leg does not match journal')
        quantities[oid] = matched
    if set(quantities) != set(known) or set(snapshot['our_order_ids']) != seen:
        raise ValueError('pinned ledger order identities incomplete')
    for key, expected in (('L_filled', filled_cost), ('L_resting', resting_cost), ('L', filled_cost + resting_cost)):
        if abs(number(snapshot[key]) - expected) > epsilon:
            raise ValueError('pinned ledger cost identity fails')
    return quantities


def compare(predicted, actual, absolute, relative=ZERO):
    error = abs(predicted - actual)
    limit = max(number(absolute), number(relative) * abs(actual))
    return {'predicted': predicted, 'actual': actual, 'absolute_error': error, 'limit': limit, 'pass': error <= limit}


@decimal_context
def accuracy_gate(payload, config, raw_journal, receipts, tolerance: Tolerance):
    """Evaluate one fully attributed session; missing evidence raises, disagreement FAILs.

    receipts is the documented sanitized export manifest. Wallet snapshots and
    D+1/D+2 venue reads must refer to the same account/session/reward day. Their
    source hashes bind separate files at the CLI layer, not caller assertions.
    """
    journal = read_pin_evidence(raw_journal)
    rows = journal.rows
    scope = receipts['scope']
    cid, day = scope['condition_id'], scope['reward_day']
    if (receipts['journal_pin'] != LFC_PIN or receipts['journal_sha256'] != journal.sha256
            or rows[0]['scope']['condition_id'] != cid or set(payload['conditions']) != {cid}
            or rows[0]['scope']['maker_address'].lower() != scope['account_id'].lower()
            or rows[0]['scope']['session_id'] != scope['session_id']
            or payload['conditions'][cid]['token_ids'] != rows[0]['scope']['token_ids']
            or day != utc(rows[0]['recorded_at_utc']).date().isoformat()):
        raise ValueError('receipt/journal scope mismatch')
    commands, known = pin_commands(rows, cid)
    predicted = replay({**payload, 'commands': commands, 'close_all_at': rows[-1]['recorded_at_utc'],
                        'close_all_source_sha256': journal.sha256}, config)
    fills = clob_fills(receipts['clob'], known, rows[0]['scope']['token_ids'], account_id=scope['account_id'])
    wallet = receipts['wallet']
    if (wallet['account_id'] != scope['account_id'] or wallet['session_id'] != scope['session_id']
            or wallet['complete'] is not True or wallet['unattributed_cashflows'] != []
            or utc(wallet['as_of_utc']) < utc(rows[-1]['recorded_at_utc'])
            or utc(wallet['start_as_of_utc']) > utc(rows[0]['recorded_at_utc'])):
        raise ValueError('incomplete or foreign wallet evidence')
    # Both independent sources must agree on quantities and cost per own order.
    actual_sizes, wallet_sizes = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for fill in fills:
        actual_sizes[fill['order_id']] += fill['size']
    for fill in wallet['fills']:
        oid = fill['order_id']
        if oid not in known or number(fill['price']) != number(known[oid]['price']):
            raise ValueError('wallet fill does not bind to session order')
        wallet_sizes[oid] += number(fill['size'])
    eps = number(tolerance.receipt_reconciliation_absolute)
    if any(actual_sizes[oid] != wallet_sizes[oid] for oid in set(actual_sizes) | set(wallet_sizes)):
        raise ValueError('wallet and CLOB fills disagree')
    ledger_sizes = ledger_snapshot_fills(receipts['lfc_ledger'], known, rows[0]['scope']['token_ids'],
                                         session_id=scope['session_id'],
                                         minimum_at=max((f['at'] for f in fills),
                                                        default=utc(rows[0]['recorded_at_utc'])),
                                         epsilon=eps)
    if any(ledger_sizes[oid] != actual_sizes[oid] for oid in known):
        raise ValueError('pinned ledger and CLOB fills disagree')
    closed_by = min(utc(rows[-1]['recorded_at_utc']), utc(receipts['lfc_ledger']['recorded_at_utc']))
    for fill in fills:
        fill['at_end'] = min(fill['at_end'], closed_by)
        if fill['at_end'] < fill['at']:
            raise ValueError('CLOB fill clock conflicts with terminal ledger proof')
    reward_reads = receipts['rewards']
    if len(reward_reads) != 2:
        raise ValueError('both D+1 and D+2 rewards required')
    base_day = utc(day + 'T00:00:00Z')
    for read, delay in zip(reward_reads, (1, 2)):
        if (read['account_id'] != scope['account_id'] or read['condition_id'] != cid or read['reward_day'] != day
                or read['session_id'] != scope['session_id'] or read['session_exclusive'] is not True
                or read['complete'] is not True or utc(read['as_of_utc']) < base_day + timedelta(days=delay)
                or not read['source_sha256']):
            raise ValueError('unattributed, immature or incomplete rewards')
        source_hash(read['source_sha256'])
    actual_reward = number(reward_reads[1]['paid_reward'])
    if utc(wallet['as_of_utc']) < utc(reward_reads[1]['as_of_utc']):
        raise ValueError('wallet snapshot predates payout evidence')
    if (abs(number(reward_reads[0]['paid_reward']) - actual_reward) > eps
            or abs(number(wallet['reward_credit']) - actual_reward) > eps):
        raise ValueError('reward reads or wallet credit disagree')
    cost = sum((f['size'] * f['price'] for f in fills), ZERO)
    if wallet['settlement_complete'] is not True:
        raise ValueError('incomplete wallet venue settlement evidence')
    source_hash(wallet['settlement_source_sha256'])
    settlements = [e for e in payload['events'] if e['kind'] == 'settlement' and e['condition_id'] == cid]
    if len(settlements) != 1 or settlements[0]['source'] != 'venue':
        raise ValueError('unique venue settlement required for receipt reconciliation')
    yes_payout = number(settlements[0]['yes_payout'], maximum=ONE)
    actual_venue_value = sum((f['size'] * (yes_payout if f['outcome'] == 'YES' else ONE - yes_payout)
                              for f in fills), ZERO)
    if (abs(actual_venue_value - number(wallet['settlement_value'])) > eps
            or number(wallet['redemption_credit']) > actual_venue_value + eps):
        raise ValueError('wallet and captured venue settlement disagree')
    outside_cash, cash_ids = ZERO, set()
    for flow in wallet['other_attributed_cashflows']:
        if not flow['id'] or flow['id'] in cash_ids or flow['session_id'] == scope['session_id']:
            raise ValueError('invalid external wallet cashflow identity')
        source_hash(flow['source_sha256'])
        cash_ids.add(flow['id'])
        outside_cash += number(flow['amount'], minimum=None)
    expected_end_cash = (number(wallet['start_cash']) - cost + actual_reward + number(wallet['rebate_credit'])
                         + number(wallet['redemption_credit']) + outside_cash)
    if abs(number(wallet['end_cash']) - expected_end_cash) > eps:
        raise ValueError('wallet cash identity fails')
    predicted_sizes = defaultdict(lambda: ZERO)
    predicted_marks = defaultdict(lambda: [ZERO, ZERO])
    for fill in predicted['fills']:
        oid = fill['order_id']
        predicted_sizes[oid] += fill['size']
        if fill['markout_per_share'] is not None:
            predicted_marks[oid][0] += fill['size'] * fill['markout_per_share']
            predicted_marks[oid][1] += fill['size']
    actual_marks = observed_markouts(fills, payload['events'], config)
    fill_metrics, mark_metrics = {}, {}
    for oid in sorted(known):
        fill_metrics[oid] = compare(predicted_sizes[oid], actual_sizes[oid],
                                    tolerance.fill_absolute_shares, tolerance.fill_relative)
        if oid in actual_marks:
            total, size = predicted_marks[oid]
            low, high = actual_marks[oid]
            if size:
                prediction = total / size
                metric = compare(prediction, (low + high) / 2, tolerance.markout_absolute_per_share)
                metric['actual_interval'] = [low, high]
                metric['absolute_error'] = max(abs(prediction - low), abs(prediction - high))
                metric['pass'] = metric['absolute_error'] <= metric['limit']
                mark_metrics[oid] = metric
            else:
                mark_metrics[oid] = {'predicted': None, 'actual_interval': [low, high], 'pass': False}
    reward_metric = compare(predicted['reward_payable'], actual_reward,
                            tolerance.reward_absolute, tolerance.reward_relative)
    rebate_metric = compare(predicted['rebate_payable'], number(wallet['rebate_credit']),
                            tolerance.receipt_reconciliation_absolute)
    evidence_sufficient = (len(actual_marks) >= tolerance.min_filled_orders
                           and actual_reward >= number(tolerance.min_paid_reward))
    complete = not predicted['reasons'] and not predicted['rejected']
    passed = (evidence_sufficient and complete and reward_metric['pass'] and rebate_metric['pass']
              and all(m['pass'] for m in fill_metrics.values()) and all(m['pass'] for m in mark_metrics.values()))
    metrics_pass = (complete and reward_metric['pass'] and rebate_metric['pass']
                    and all(m['pass'] for m in fill_metrics.values())
                    and all(m['pass'] for m in mark_metrics.values()))
    return {'status': 'PASS' if passed else ('INSUFFICIENT_EVIDENCE' if not evidence_sufficient else 'FAIL'),
            'synthetic': rows[0]['mode'] != 'live',
            'rewards': reward_metric, 'rebates': rebate_metric,
            'venue_settlement': {'actual_fills_value': actual_venue_value,
                                 'wallet_value': number(wallet['settlement_value']),
                                 'predicted_fills_value': predicted['venue_payout']},
            'fills': fill_metrics, 'markouts_per_share': mark_metrics,
            'evidence_sufficient': evidence_sufficient, 'simulator_complete': complete,
            'metrics_pass': metrics_pass, 'actual_filled_orders': len(actual_marks),
            'simulator_reasons': predicted['reasons'], 'scope': scope,
            'lifecycle_rejections': predicted['rejected'],
            'config_sha256': digest(config.projection()), 'payload_sha256': digest(payload),
            'receipts_sha256': digest(receipts), 'journal_sha256': receipts['journal_sha256'],
            'journal_records': journal.record_count, 'journal_bytes': journal.byte_count,
            'retained_lifecycle_records': len(rows),
            'tolerance': asdict(tolerance), 'tolerance_sha256': digest(asdict(tolerance)),
            'qualification': 'SESSION_ACCURACY_ONLY', 'trial_can_pass': False, 'simulation': predicted}


@decimal_context
def combine_session_gates(reports, *, min_sessions, min_filled_orders, min_paid_reward):
    """Campaign certificate from distinct complete sessions at one code/config/tolerance.

    No-fill sessions still contribute their reward and zero-fill checks; they do
    not identify informed flow or markout accuracy. A session-level evidence
    floor must not make the first-fill-stops pilot impossible to certify.
    """
    if not reports or min_sessions < 1 or min_filled_orders < 1:
        raise ValueError('campaign evidence floors required')
    identities = [(r['scope']['account_id'].lower(), r['scope']['session_id']) for r in reports]
    if (len(set(identities)) != len(identities)
            or len({r['journal_sha256'] for r in reports}) != len(reports)):
        raise ValueError('duplicate campaign session')
    for key in ('config_sha256', 'tolerance_sha256'):
        if len({r[key] for r in reports}) != 1:
            raise ValueError('mixed campaign configuration')
    filled = sum(r['actual_filled_orders'] for r in reports)
    paid = sum((r['rewards']['actual'] for r in reports), ZERO)
    enough = len(reports) >= min_sessions and filled >= min_filled_orders and paid >= number(min_paid_reward)
    return {'status': 'PASS' if enough and all(r['metrics_pass'] for r in reports)
            else ('INSUFFICIENT_EVIDENCE' if not enough else 'FAIL'),
            'sessions': len(reports), 'actual_filled_orders': filled, 'paid_rewards': paid,
            'synthetic': any(r['synthetic'] for r in reports),
            'config_sha256': reports[0]['config_sha256'], 'tolerance_sha256': reports[0]['tolerance_sha256'],
            'session_report_sha256': [digest(r) for r in reports],
            'qualification': 'ACCURACY_ONLY_REQUIRES_CODE_AND_PREREG_BINDING', 'trial_can_pass': False}
