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
import json

from weather.backtesting.t1_simulator import replay
from weather.backtesting.t1_types import ZERO, canonical, decimal_context, digest, levels, number, utc

LFC_PIN = '124603578'
# Wire identifier from schema_registry_data.py at LFC_PIN; do not import live code.
PIN_JOURNAL_VERSION = 'mm_stage2_hold_v0.1'


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


def read_pin_journal(raw):
    """Verify the exact canonical-byte chain written by pin HoldJournal.record."""
    previous, rows, last_time = None, [], None
    for index, line in enumerate(raw.splitlines(keepends=True)):
        row = json.loads(line)
        at = utc(row['recorded_at_utc'])
        if (canonical(row) != line or row['schema_version'] != PIN_JOURNAL_VERSION
                or row['kind'] != 'journal' or row['sequence'] != index
                or row['previous_sha256'] != previous or last_time is not None and at < last_time):
            raise ValueError('invalid pinned journal chain or clock')
        previous, last_time = hashlib.sha256(line).hexdigest(), at
        rows.append(row)
    if not rows or rows[0]['event'] != 'opened' or rows[-1]['event'] != 'terminal':
        raise ValueError('journal missing opened or terminal record')
    terminal = rows[-1]
    if (rows[0]['mode'] not in ('live', 'replay') or terminal['cleanup_ok'] is not True
            or terminal['evidence_complete'] is not True or terminal['unknown_submit'] is not False
            or terminal['inventory_proven'] is not True):
        raise ValueError('incomplete session journal')
    return rows


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
    snapshot, pending, commands, pending_cancel, known = None, None, [], None, {}
    for row in rows:
        event = row['event']
        if event == 'submit_market_snapshot':
            snapshot = row['snapshot']
            if snapshot['condition_id'] != condition_id or snapshot['token_ids'] != tokens:
                raise ValueError('submit snapshot token mapping mismatch')
        elif event == 'submit_request':
            if pending is not None or snapshot is None:
                raise ValueError('ambiguous submit sequence')
            request = row['request']
            if request['side'] != 'BUY' or request['post_only'] is not True or request['token_id'] not in tokens:
                raise ValueError('unsupported pilot order shape')
            if utc(snapshot['observed_at_utc']) > utc(row['recorded_at_utc']):
                raise ValueError('future submit snapshot')
            pending = request
        elif event == 'submit_response':
            response = row['response']
            oid = response.get('orderID') or response.get('order_id') or response.get('id')
            if pending is None or not oid or response.get('status') not in ('live', 'matched'):
                raise ValueError('unbound submit response')
            oid = str(oid)
            if oid in known:
                raise ValueError('duplicate order acknowledgment')
            command = {'kind': 'post', 'id': oid, 'condition_id': condition_id,
                       'outcome': 'YES' if pending['token_id'] == tokens[0] else 'NO',
                       'observed_at': snapshot['observed_at_utc'], 'price': pending['price'], 'size': pending['size']}
            commands.append(command)
            known[oid] = command
            pending = None
        elif event == 'lfc_queue_ahead' and row['phase'] == 'placement':
            command = known.get(row['order_id'])
            if (command is None or number(command['price']) != number(row['price'])
                    or number(command['size']) != number(row['own_size'])
                    or tokens[0 if command['outcome'] == 'YES' else 1] != row['token_id']):
                raise ValueError('LFC placement binding mismatch')
        elif event == 'cancel_request':
            pending_cancel = row
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
                request_time = (pending_cancel or row)['recorded_at_utc']
                commands.append({'kind': 'cancel', 'id': oid, 'observed_at': request_time})
            pending_cancel = None
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


def clob_fills(receipt, known, tokens):
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
            out.append({'order_id': oid, 'condition_id': command['condition_id'], 'outcome': command['outcome'],
                        'price': p, 'size': size, 'at': clob_time(row['match_time']), 'trade_id': key})
    for oid, command in known.items():
        if sum((r['size'] for r in out if r['order_id'] == oid), ZERO) > number(command['size']):
            raise ValueError('own fills exceed posted size')
    return out


def observed_markouts(fills, events, config):
    values = defaultdict(lambda: [ZERO, ZERO])
    for fill in fills:
        due = fill['at'] + timedelta(seconds=config.markout_seconds)
        books = sorted((r for r in events if r['kind'] == 'book' and r['condition_id'] == fill['condition_id']
                        and utc(r['at']) >= due), key=lambda r: utc(r['at']))
        if not books or D(str((utc(books[0]['at']) - due).total_seconds())) > number(config.mark_max_delay_seconds):
            raise ValueError('actual fill lacks horizon book')
        book = books[0][fill['outcome']]
        mid = (max(r['price'] for r in levels(book['bids']))
               + min(r['price'] for r in levels(book['asks']))) / 2
        values[fill['order_id']][0] += (mid - fill['price']) * fill['size']
        values[fill['order_id']][1] += fill['size']
    return {oid: total / size for oid, (total, size) in values.items()}


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
    rows = read_pin_journal(raw_journal)
    scope = receipts['scope']
    cid, day = scope['condition_id'], scope['reward_day']
    if (receipts['journal_pin'] != LFC_PIN or receipts['journal_sha256'] != hashlib.sha256(raw_journal).hexdigest()
            or rows[0]['scope']['condition_id'] != cid or set(payload['conditions']) != {cid}
            or payload['conditions'][cid]['token_ids'] != rows[0]['scope']['token_ids']
            or day != utc(rows[0]['recorded_at_utc']).date().isoformat()):
        raise ValueError('receipt/journal scope mismatch')
    commands, known = pin_commands(rows, cid)
    predicted = replay({**payload, 'commands': commands}, config)
    fills = clob_fills(receipts['clob'], known, rows[0]['scope']['token_ids'])
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
    if any(abs(actual_sizes[oid] - wallet_sizes[oid]) > eps for oid in set(actual_sizes) | set(wallet_sizes)):
        raise ValueError('wallet and CLOB fills disagree')
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
    actual_reward = number(reward_reads[1]['paid_reward'])
    if utc(wallet['as_of_utc']) < utc(reward_reads[1]['as_of_utc']):
        raise ValueError('wallet snapshot predates payout evidence')
    if (abs(number(reward_reads[0]['paid_reward']) - actual_reward) > eps
            or abs(number(wallet['reward_credit']) - actual_reward) > eps):
        raise ValueError('reward reads or wallet credit disagree')
    cost = sum((f['size'] * f['price'] for f in fills), ZERO)
    expected_end_cash = (number(wallet['start_cash']) - cost + actual_reward + number(wallet['rebate_credit'])
                         + number(wallet['redemption_credit']))
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
            mark_metrics[oid] = (compare(total / size, actual_marks[oid], tolerance.markout_absolute_per_share)
                                 if size else {'predicted': None, 'actual': actual_marks[oid], 'pass': False})
    reward_metric = compare(predicted['reward_payable'], actual_reward,
                            tolerance.reward_absolute, tolerance.reward_relative)
    evidence_sufficient = (len(actual_marks) >= tolerance.min_filled_orders
                           and actual_reward >= number(tolerance.min_paid_reward))
    complete = not predicted['reasons']
    passed = (evidence_sufficient and complete and reward_metric['pass']
              and all(m['pass'] for m in fill_metrics.values()) and all(m['pass'] for m in mark_metrics.values()))
    metrics_pass = (complete and reward_metric['pass'] and all(m['pass'] for m in fill_metrics.values())
                    and all(m['pass'] for m in mark_metrics.values()))
    return {'status': 'PASS' if passed else ('INSUFFICIENT_EVIDENCE' if not evidence_sufficient else 'FAIL'),
            'rewards': reward_metric, 'fills': fill_metrics, 'markouts_per_share': mark_metrics,
            'evidence_sufficient': evidence_sufficient, 'simulator_complete': complete,
            'metrics_pass': metrics_pass, 'actual_filled_orders': len(actual_marks),
            'simulator_reasons': predicted['reasons'], 'scope': scope,
            'config_sha256': digest(config.projection()), 'payload_sha256': digest(payload),
            'receipts_sha256': digest(receipts), 'journal_sha256': receipts['journal_sha256'],
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
    identities = [(r['scope']['account_id'], r['scope']['session_id']) for r in reports]
    if len(set(identities)) != len(identities):
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
            'config_sha256': reports[0]['config_sha256'], 'tolerance_sha256': reports[0]['tolerance_sha256'],
            'session_report_sha256': [digest(r) for r in reports],
            'qualification': 'ACCURACY_ONLY_REQUIRES_CODE_AND_PREREG_BINDING', 'trial_can_pass': False}
