"""Offline accuracy gate on pinned LFC journal bytes and saved, attributed receipts.

The gate certifies agreement for a config/input/code binding, never profitability
or live authority. Raw receipt files remain hashed CLI inputs. No source fetches.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
from io import BytesIO
import json
from pathlib import Path

from weather.backtesting.t1_simulator import replay
from weather.backtesting.t1_accounting import actual_accounts
from weather.backtesting.t1_types import (ONE, ZERO, canonical, decimal_context, digest, levels,
                                         number, source_hash, utc)

LFC_PIN = '124603578f393827fa1b67bd978f6e3b02048ae9'
F0_PIN = 'f531395522d0b0a37495185b2750164008fe586a'
COMPATIBLE_RECORDER_PINS = frozenset((LFC_PIN, F0_PIN))
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
    monetary_absolute: str = '.01'
    campaign_net_absolute: str = '.01'
    position_absolute_shares: str = '0'

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
    gaps: tuple = ()


def read_pin_evidence(source, *, require_complete=True, observations=False):
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
            keep = ((row['event'] in LIFECYCLE_EVENTS or observations and row['event'] in (
                        'market_snapshot', 'terminal_trades', 'terminal_positions',
                        'initial_balances_response', 'initial_positions_response', 'final_balances_response'))
                    and not (row['event'] == 'lfc_queue_ahead' and row.get('phase') != 'placement'))
            if keep:
                retained_bytes += len(line)
                if retained_bytes > MAX_LIFECYCLE_BYTES:
                    raise ValueError('retained journal lifecycle exceeds bounded receipt limit')
                rows.append(row)
    gaps = []
    if not rows or first_event != 'opened':
        raise ValueError('journal missing opened record')
    if last_event != 'terminal':
        gaps.append('missing_terminal_record')
    else:
        terminal = rows[-1]
        if any(terminal.get(k) is not v for k, v in (
                ('cleanup_ok', True), ('evidence_complete', True), ('unknown_submit', False), ('inventory_proven', True))):
            gaps.append('incomplete_session_journal')
    if rows[0]['mode'] not in ('live', 'replay', 'rehearse'):
        raise ValueError('unsupported journal mode')
    if require_complete and gaps:
        raise ValueError('incomplete session journal: missing opened or terminal record or cleanup proof')
    source_hash(rows[0]['profile_sha256'])
    return JournalEvidence(rows, whole_hash.hexdigest(), byte_count, count, tuple(gaps))


def read_pin_journal(source):
    """Verified lifecycle rows from the exact pin writer's full hash chain."""
    return read_pin_evidence(source).rows


def pin_latency_evidence(raw, *, recorder_pin=None):
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
    commands, _ = pin_commands(rows, rows[0]['scope']['condition_id'])
    cancel_samples = [{'requested_at': c['decided_at'], 'acknowledged_at': c['arrival_at']}
                      for c in commands if c['kind'] == 'cancel']
    if recorder_pin is not None and recorder_pin not in COMPATIBLE_RECORDER_PINS:
        raise ValueError('unreviewed recorder latency pin')
    return {'kind': 'observation_to_order_ack', 'sample_count': len(samples), 'samples': samples,
            'cancel_samples': cancel_samples, 'tail_claim': 'EMPIRICAL_P95_IS_NOT_A_WORST_CASE_BOUND',
            'synthetic': rows[0]['mode'] != 'live', 'journal_sha256': evidence.sha256,
            'journal_pin': recorder_pin or 'UNBOUND_RECORDER_PIN'}


def pin_commands(rows, condition_id):
    """Adapt pin's real submit_request/response and acknowledged cancel lifecycle.

    Receipt replay uses actual request/ACK bounds, independently of p95 stress.
    Unknown/ambiguous posts refuse the complete gate and remain partial evidence.
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
                       'arrival_at': row['recorded_at_utc'], 'arrival_earliest': pending['decided_at'],
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
                                 'decided_at': request_time, 'arrival_earliest': request_time,
                                 'arrival_at': row['recorded_at_utc']})
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
    if payload.get('input_kind') == 'f0_lfc_recording':
        from weather.backtesting.t1_recorder import recorder_report

        return recorder_report(payload, config, raw_journal, receipts, tolerance)
    journal = read_pin_evidence(raw_journal)
    rows = journal.rows
    scope = receipts['scope']
    cid, day = scope['condition_id'], scope['reward_day']
    if (receipts['journal_pin'] not in COMPATIBLE_RECORDER_PINS or receipts['journal_sha256'] != journal.sha256
            or rows[0]['scope']['condition_id'] != cid or set(payload['conditions']) != {cid}
            or rows[0]['scope']['maker_address'].lower() != scope['account_id'].lower()
            or rows[0]['scope']['session_id'] != scope['session_id']
            or payload['conditions'][cid]['token_ids'] != rows[0]['scope']['token_ids']
            or day != utc(rows[0]['recorded_at_utc']).date().isoformat()):
        raise ValueError('receipt/journal scope mismatch')
    commands, known = pin_commands(rows, cid)
    if receipts.get('profile_sha256', rows[0]['profile_sha256']) != rows[0]['profile_sha256']:
        raise ValueError('actual journal profile hash mismatch')
    replay_payload = {**payload, 'opening_cash': receipts['wallet']['start_cash'],
                        'commands': commands, 'replay_mode': 'receipt',
                        'checkpoints': [{'id': r['id'], 'at': r['at']} for r in receipts.get('state_checkpoints', [])],
                        'close_all_at': rows[-1]['recorded_at_utc'],
                        'close_all_source_sha256': journal.sha256}
    if any(r.get('allocation') for r in receipts['rewards']):
        replay_payload['reward_payment_rule'] = 'campaign_day'
    predicted = replay(replay_payload, config)
    fills = clob_fills(receipts['clob'], known, rows[0]['scope']['token_ids'], account_id=scope['account_id'])
    from weather.backtesting.t1_capture import verify_own_exclusions

    evidence_gaps = verify_own_exclusions(payload['events'], commands, fills)
    if not receipts.get('state_checkpoints'):
        evidence_gaps.append('missing_intermediate_cash_inventory_reservation_evidence')
    for fill in fills:
        for command in commands:
            if command['id'] == fill['order_id'] and utc(command['decided_at']) <= fill['at_end'] and fill['at'] < utc(command['arrival_at']):
                evidence_gaps.append('lifecycle_time_unidentified')
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
                or read['session_id'] != scope['session_id']
                or (read['session_exclusive'] is not True and not read.get('allocation'))
                or read['complete'] is not True
                or not base_day + timedelta(days=delay) <= utc(read['as_of_utc']) < base_day + timedelta(days=delay + 1)
                or not read['source_sha256']):
            raise ValueError('unattributed, immature or incomplete rewards')
        source_hash(read['source_sha256'])
        allocation = read.get('allocation')
        if allocation is not None:
            source_hash(allocation['source_sha256'])
            if (allocation['method'] != 'independent_venue_accrual_deltas'
                    or not allocation['payment_id'] or allocation['account_day_complete'] is not True
                    or number(allocation['sessions'][scope['session_id']]) != number(read['paid_reward'])
                    or sum((number(v) for v in allocation['sessions'].values()), ZERO) != number(allocation['day_total'])):
                raise ValueError('unattributed shared reward-day allocation')
    if (reward_reads[0]['source_sha256'] == reward_reads[1]['source_sha256']
            or utc(reward_reads[0]['as_of_utc']) >= utc(reward_reads[1]['as_of_utc'])
            or reward_reads[0].get('allocation') != reward_reads[1].get('allocation')):
        raise ValueError('distinct chronological D+1/D+2 reward reads required')
    actual_reward = number(reward_reads[1]['paid_reward'])
    if utc(wallet['as_of_utc']) < utc(reward_reads[1]['as_of_utc']):
        raise ValueError('wallet snapshot predates payout evidence')
    if (abs(number(reward_reads[0]['paid_reward']) - actual_reward) > eps
            or abs(number(wallet['reward_credit']) - actual_reward) > eps):
        raise ValueError('reward reads or wallet credit disagree')
    cost = sum((f['size'] * f['price'] for f in fills), ZERO)
    if wallet['settlement_complete'] is True:
        source_hash(wallet['settlement_source_sha256'])
    elif fills:
        evidence_gaps.append('unresolved_inventory_full_loss_retained')
    settlements = [e for e in payload['events'] if e['kind'] == 'settlement' and e['condition_id'] == cid]
    if len(settlements) > 1 or settlements and settlements[0]['source'] != 'venue':
        raise ValueError('unique venue settlement required for receipt reconciliation')
    if fills and (not settlements or wallet['settlement_complete'] is not True):
        # Keep the full-loss row; the entire campaign fails completeness.
        yes_payout = None
    else:
        yes_payout = number(settlements[0]['yes_payout'], maximum=ONE) if settlements else None
    if fills and yes_payout is not None and number(wallet['yes_payout'], maximum=ONE) != yes_payout:
        raise ValueError('wallet and captured venue settlement fractions disagree')
    accounts = actual_accounts(fills, wallet, rows[0]['scope']['token_ids'],
                               yes_payout=yes_payout, session_id=scope['session_id'], epsilon=eps)
    actual_venue_value = sum((f['size'] * (yes_payout if f['outcome'] == 'YES' else ONE - yes_payout)
                              for f in fills), ZERO) if yes_payout is not None else ZERO
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
                         + number(wallet['redemption_credit']) + outside_cash
                         - number(wallet['maker_fees']) - number(wallet['operating_cost']))
    if abs(number(wallet['end_cash']) - expected_end_cash) > eps:
        raise ValueError('wallet cash identity fails')
    money_keys = ('cost', 'venue_payout', 'cash_redemptions_pusd', 'unredeemed_venue_value',
                  'cash_available', 'wallet_end_cash', 'raw_net_pnl', 'maker_fees_pusd', 'operating_cost')
    economics = {k: compare(predicted[k] + (outside_cash if k == 'wallet_end_cash' else ZERO),
                            accounts[k], tolerance.monetary_absolute) for k in money_keys}
    economics['wallet_balance_identity'] = compare(accounts['wallet_end_cash'], number(wallet['end_cash']), eps)
    economics['net_balance_identity'] = compare(accounts['raw_net_pnl'], accounts['balance_net_pnl'], eps)
    position_metrics = {stage: {token: compare(predicted[stage][cid][token], accounts[stage][token],
                                                tolerance.position_absolute_shares)
                                 for token in rows[0]['scope']['token_ids']}
                        for stage in ('terminal_positions', 'end_positions')}
    economics['cost_reserve_identity'] = compare(predicted['cost_reserve'],
                                                number(config.informed_fraction) * predicted['cost'], '0')
    economics['stressed_net_identity'] = compare(predicted['stressed_net_pnl'],
                                                predicted['raw_net_pnl'] - predicted['cost_reserve'], '0')
    economics_pass = (accounts['settlement_complete'] and all(m['pass'] for m in economics.values())
                      and all(m['pass'] for stage in position_metrics.values() for m in stage.values()))
    checkpoint_metrics = {}
    for checkpoint in receipts.get('state_checkpoints', []):
        source_hash(checkpoint['source_sha256'])
        prediction = predicted['checkpoints'][checkpoint['id']]
        checkpoint_metrics[checkpoint['id']] = {
            k: compare(prediction[k], number(checkpoint[k]), tolerance.monetary_absolute)
            for k in ('cash', 'reserved', 'cost_at_risk')}
        for token in rows[0]['scope']['token_ids']:
            checkpoint_metrics[checkpoint['id']][token] = compare(prediction['positions'][cid][token],
                number(checkpoint['positions'][token]), tolerance.position_absolute_shares)
    economics_pass = economics_pass and all(m['pass'] for point in checkpoint_metrics.values() for m in point.values())
    predicted_sizes = defaultdict(lambda: ZERO)
    predicted_marks = defaultdict(lambda: [ZERO, ZERO])
    for fill in predicted['fills']:
        oid = fill['order_id']
        predicted_sizes[oid] += fill['size']
        if fill['markout_per_share'] is not None:
            predicted_marks[oid][0] += fill['size'] * fill['markout_per_share']
            predicted_marks[oid][1] += fill['size']
    if 'mark_books' not in receipts:
        evidence_gaps.append('missing_independent_raw_mark_books')
    mark_events = receipts.get('mark_books', payload['events'])
    try:
        actual_marks = observed_markouts(fills, mark_events, config)
    except ValueError:
        actual_marks = {}
        evidence_gaps.append('missing_bounded_independent_five_minute_marks')
    horizon_diagnostics = {}
    for horizon in (60, 300, 1800):
        try:
            values = observed_markouts(fills, mark_events, replace(config, markout_seconds=horizon))
            horizon_diagnostics[str(horizon)] = {'status': 'OBSERVED_INTERVAL', 'per_share': values}
        except ValueError:
            horizon_diagnostics[str(horizon)] = {'status': 'NOT QUALIFIED', 'evidence_required': 'Independent post-fill books through horizon and timestamp uncertainty.'}
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
                metric['absolute_error'] = max(low - prediction, prediction - high, ZERO)
                metric['pass'] = metric['absolute_error'] <= metric['limit']
                metric['identified'] = high - low <= 2 * metric['limit']
                if not metric['identified']:
                    evidence_gaps.append('markout_time_resolution_insufficient')
                mark_metrics[oid] = metric
            else:
                mark_metrics[oid] = {'predicted': None, 'actual_interval': [low, high], 'pass': False}
        elif actual_sizes[oid] > ZERO:
            mark_metrics[oid] = {'predicted': None, 'actual_interval': None, 'pass': False,
                                 'status': 'NOT QUALIFIED: MISSING_HORIZON_EVIDENCE'}
    reward_metric = compare(predicted['reward_payable'], actual_reward,
                            tolerance.reward_absolute, tolerance.reward_relative)
    if config.competition_rule == 'aggregate_upper_bound':
        reward_metric.update({'comparison': 'ONE_SIDED_LOWER_BOUND_COVERAGE',
                              'pass': predicted['reward_payable'] <= actual_reward + number(tolerance.reward_absolute)})
    rebate_metric = compare(predicted['rebate_payable'], number(wallet['rebate_credit']),
                            tolerance.receipt_reconciliation_absolute)
    actual_filled_count = sum(size > ZERO for size in actual_sizes.values())
    evidence_sufficient = (actual_filled_count >= tolerance.min_filled_orders
                           and actual_reward >= number(tolerance.min_paid_reward))
    complete = not predicted['reasons'] and not predicted['rejected'] and not evidence_gaps
    passed = (economics_pass and evidence_sufficient and complete and reward_metric['pass'] and rebate_metric['pass']
              and all(m['pass'] for m in fill_metrics.values()) and all(m['pass'] for m in mark_metrics.values()))
    metrics_pass = (economics_pass and complete and reward_metric['pass'] and rebate_metric['pass']
                    and all(m['pass'] for m in fill_metrics.values())
                    and all(m['pass'] for m in mark_metrics.values()))
    status = ('NOT_QUALIFIED' if evidence_gaps else 'PASS' if passed else
              'INSUFFICIENT_EVIDENCE' if not evidence_sufficient else 'FAIL')
    if config.competition_rule == 'aggregate_upper_bound' and not evidence_gaps:
        status = 'BOUND_COVERAGE_PASS' if complete and reward_metric['pass'] else 'BOUND_NOT_QUALIFIED'
    return {'status': status,
            'synthetic': rows[0]['mode'] != 'live',
            'rewards': reward_metric, 'rebates': rebate_metric,
            'economics': economics, 'positions': position_metrics, 'actual_accounts': accounts,
            'checkpoints': checkpoint_metrics,
            'order_ids': sorted(known), 'period_start': payload['start'], 'period_end': payload['end'],
            'reward_allocation': reward_reads[1].get('allocation'),
            'session_exclusive': reward_reads[1]['session_exclusive'],
            'external_reward_accrued': number(payload.get('external_incentives', {}).get(day, {}).get('reward_accrued', '0')),
            'payment_ids': wallet['payment_ids'],
            'wallet_as_of_utc': wallet['as_of_utc'], 'wallet_end_cash': number(wallet['end_cash']),
            'wallet_end_cash_source_sha256': source_hash(wallet['end_cash_source_sha256']),
            'other_attributed_cashflows': wallet['other_attributed_cashflows'],
            'capital_period': {'opening_cash': number(wallet['start_cash']),
                               'closing_cash': accounts['cash_available'],
                               'opening_positions': accounts['opening_positions'],
                               'end_positions': accounts['end_positions'],
                               'last_redemption_at': max((r['at'] for r in wallet['redemptions']), default=payload['start']),
                               'interperiod_cashflows': wallet.get('interperiod_cashflows', [])},
            'venue_settlement': {'actual_fills_value': actual_venue_value,
                                 'wallet_value': number(wallet['settlement_value']),
                                 'predicted_fills_value': predicted['venue_payout']},
            'fills': fill_metrics, 'markouts_per_share': mark_metrics,
            'markout_diagnostics_seconds': horizon_diagnostics,
            'settlement_markout_per_share': {f['order_id']: (yes_payout if f['outcome'] == 'YES' else ONE - yes_payout) - f['price']
                                            for f in fills} if yes_payout is not None else None,
            'evidence_sufficient': evidence_sufficient, 'simulator_complete': complete,
            'metrics_pass': metrics_pass, 'actual_filled_orders': actual_filled_count,
            'simulator_reasons': predicted['reasons'], 'scope': scope,
            'evidence_gaps': sorted(set(evidence_gaps)), 'timing_rule': 'OBSERVED_REQUEST_ACK_INTERVALS',
            'lifecycle_rejections': predicted['rejected'],
            'config_sha256': digest(config.projection()), 'payload_sha256': digest(payload),
            'receipts_sha256': digest(receipts), 'journal_sha256': receipts['journal_sha256'],
            'journal_records': journal.record_count, 'journal_bytes': journal.byte_count,
            'retained_lifecycle_records': len(rows),
            'profile_sha256': rows[0]['profile_sha256'], 'recorder_pin': receipts['journal_pin'],
            'tolerance': asdict(tolerance), 'tolerance_sha256': digest(asdict(tolerance)),
            'qualification': 'NOT QUALIFIED: BOUND_ONLY' if config.competition_rule == 'aggregate_upper_bound' else 'SESSION_METRICS_REQUIRE_RAW_CERTIFICATE',
            'trial_can_pass': False, 'simulation': predicted}


@decimal_context
def combine_session_gates(reports, *, min_sessions, min_filled_orders, min_paid_reward, expected_session_ids=None):
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
    if len({r['scope']['account_id'].lower() for r in reports}) != 1:
        raise ValueError('campaign must represent one funded account')
    if expected_session_ids is not None and sorted(expected_session_ids) != sorted(r['scope']['session_id'] for r in reports):
        raise ValueError('campaign population includes every scheduled, failed and incomplete session')
    order_ids, cash_ids, allocations, periods, day_claims = set(), set(), {}, [], {}
    for report in sorted(reports, key=lambda r: utc(r['period_start'])):
        if order_ids.intersection(report['order_ids']):
            raise ValueError('duplicate campaign order identity')
        order_ids.update(report['order_ids'])
        allocation = report['reward_allocation']
        day_key = (report['scope']['condition_id'], report['scope']['reward_day'])
        if day_key in day_claims and (day_claims[day_key] or report['session_exclusive']):
            raise ValueError('two sessions claim exclusive income from the same condition-day')
        day_claims[day_key] = report['session_exclusive']
        for kind, ids in report['payment_ids'].items():
            for key in ids:
                # A shared reward payment is legal only with the SAME whole
                # independently observed day allocation, checked below.
                if (kind, key) in cash_ids and not (kind == 'reward' and allocation and key == allocation['payment_id']):
                    raise ValueError('duplicate campaign payment identity')
                cash_ids.add((kind, key))
        if allocation:
            key = (report['scope']['account_id'].lower(), report['scope']['reward_day'], allocation['payment_id'])
            if key in allocations and allocations[key][0] != allocation:
                raise ValueError('conflicting shared reward-day allocation')
            allocations.setdefault(key, (allocation, []))[1].append(report['scope']['session_id'])
        capital = report['capital_period']
        if any(capital['opening_positions'].values()):
            raise ValueError('NOT QUALIFIED: unsettled capital carry requires persistent inventory support')
        if utc(capital['last_redemption_at']) > utc(report['period_end']):
            raise ValueError('capital period ends before its redemption')
        if periods:
            previous = periods[-1]
            if any(previous['capital_period']['end_positions'].values()):
                raise ValueError('NOT QUALIFIED: prior inventory was not flat before the next funded period')
            if utc(previous['period_end']) > utc(report['period_start']):
                raise ValueError('overlapping funded capital periods')
            changes = ZERO
            for flow in capital['interperiod_cashflows']:
                source_hash(flow['source_sha256'])
                amount = number(flow['amount'], minimum=None)
                if (flow.get('kind') not in ('deposit', 'withdrawal')
                        or flow['kind'] == 'deposit' and amount < ZERO
                        or flow['kind'] == 'withdrawal' and amount > ZERO):
                    raise ValueError('capital policy excludes incentive reinvestment; only explicit deposits/withdrawals adjust funding')
                key = ('interperiod', flow['id'])
                if key in cash_ids or not utc(previous['period_end']) <= utc(flow['at']) <= utc(report['period_start']):
                    raise ValueError('duplicate or out-of-period capital cashflow')
                cash_ids.add(key)
                changes += amount
            if capital['opening_cash'] != previous['capital_period']['closing_cash'] + changes:
                raise ValueError('campaign cash reset or unrecorded capital flow')
        periods.append(report)
    for allocation, sessions in allocations.values():
        if sorted(sessions) != sorted(allocation['sessions']):
            raise ValueError('incomplete shared reward-day campaign population')
    filled = sum(r['actual_filled_orders'] for r in reports)
    paid = sum((r['rewards']['actual'] for r in reports), ZERO)
    enough = len(reports) >= min_sessions and filled >= min_filled_orders and paid >= number(min_paid_reward)
    net_predicted = sum((r['economics']['raw_net_pnl']['predicted'] for r in reports), ZERO)
    net_actual = sum((r['economics']['raw_net_pnl']['actual'] for r in reports), ZERO)
    population = {r['scope']['session_id'] for r in reports}
    closings = {(r['wallet_as_of_utc'], r['wallet_end_cash'], r['wallet_end_cash_source_sha256']) for r in reports}
    if len(closings) != 1:
        raise ValueError('campaign requires one independent common closing cash snapshot')
    external_flows = {}
    for flow in periods[0]['other_attributed_cashflows']:
        if flow['session_id'] not in population:
            external_flows[flow['id']] = number(flow['amount'], minimum=None)
    residual = sum((r['actual_accounts']['unredeemed_venue_value'] for r in reports), ZERO)
    balance_net = (periods[-1]['wallet_end_cash'] - periods[0]['capital_period']['opening_cash']
                   - sum(external_flows.values(), ZERO) + residual)
    actual_identity = compare(net_actual, balance_net, reports[0]['tolerance']['receipt_reconciliation_absolute'])
    reward_days = defaultdict(list)
    for r in reports:
        reward_days[r['scope']['reward_day']].append(r)
    campaign_reward_metrics = {}
    for day, sessions in reward_days.items():
        if not any(r['reward_allocation'] for r in sessions):
            continue
        if len({r['external_reward_accrued'] for r in sessions}) != 1:
            raise ValueError('conflicting external account-day incentive scope')
        accrued = sum((r['simulation']['reward_accrued'] for r in sessions), ZERO)
        payable = accrued if accrued + sessions[0]['external_reward_accrued'] >= ONE else ZERO
        assigned = sum((r['rewards']['predicted'] for r in sessions), ZERO)
        net_predicted += payable - assigned
        campaign_reward_metrics[day] = compare(payable, sum((r['rewards']['actual'] for r in sessions), ZERO),
                                               reports[0]['tolerance']['monetary_absolute'])
    net_metric = compare(net_predicted, net_actual, reports[0]['tolerance']['campaign_net_absolute'])
    return {'status': 'PASS' if enough and net_metric['pass'] and actual_identity['pass'] and all(r['metrics_pass'] for r in reports)
                          and all(r['pass'] for r in campaign_reward_metrics.values())
            else ('INSUFFICIENT_EVIDENCE' if not enough else 'FAIL'),
            'sessions': len(reports), 'actual_filled_orders': filled, 'paid_rewards': paid,
            'net_pnl': net_metric, 'population_rule': 'ALL_SCHEDULED_SESSIONS_NO_FILTERING',
            'reward_days': campaign_reward_metrics,
            'actual_campaign_cash_identity': actual_identity,
            'capital_rule': 'VERIFIED_FLAT_NONOVERLAPPING_PERIODS_WITH_CASH_CONTINUITY',
            'synthetic': any(r['synthetic'] for r in reports),
            'config_sha256': reports[0]['config_sha256'], 'tolerance_sha256': reports[0]['tolerance_sha256'],
            'session_report_sha256': [digest(r) for r in reports],
            'qualification': 'ACCURACY_ONLY_REQUIRES_CODE_AND_PREREG_BINDING', 'trial_can_pass': False}
