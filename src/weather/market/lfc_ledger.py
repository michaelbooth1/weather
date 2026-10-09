"""Campaign loss ledger L and wallet baselines (signed pre-registration section 6, 2026-10-09).

L is the campaign-wide worst-case loss across ALL sessions, session 0 included. Only legs this campaign's script
posted count, keyed by our own intents and order ids; pre-existing wallet positions are excluded and pinned by the
T-24 h / T-40 min baselines instead. Exactly as signed (no fee term, recovery counted as zero):

    L         = L_filled + L_resting
    L_filled  = sum over our terminal legs of size_matched x limit price
    L_resting = sum over our non-terminal legs of size x limit price

A non-terminal leg is a posted-or-maybe-posted intent or a resting order; it stays at full size until a venue
terminal read proves otherwise, so filled cost is never released and resting cost is released only by a terminal
read confirmed by the venue. A post-only maker fill executes at the limit price, so size_matched x limit price is
the fill cost; any later disagreement between a venue read and the ledger is a reconciliation mismatch that halts
the campaign permanently.

Gates (Ledger.post_gate / Ledger.stop_reason):
    post or requote: L_after_cancel_of_replaced_leg + reserve <= 100, reserve = size x (p_yes + p_no) of the band
    cash:            available pUSD >= L_resting + reserve        (checked by the session with a fresh balance read)
    stop at 100:     L_filled + MIN_FEASIBLE_RESERVE > 100, or any reconciliation mismatch -> halt for good

Storage: ledger.jsonl is the append-only, hash-chained history; l_ledger.json is a snapshot of the current figures
rewritten after every append. Every read verifies the full chain; a missing, empty, truncated, reordered or edited
history raises LedgerUnavailable and every caller fails closed. Nothing here creates an exchange capability.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from weather.market import lfc_constants as LFC
from weather.market.mm_stage2_hold import canonical_bytes, digest, utc, write_new
from weather.market.reward_quote import QuoteRefused, _decimal

LEDGER_SCHEMA = 'lfc_ledger_v0.1'
BASELINE_SCHEMA = 'lfc_baseline_v0.1'
SNAPSHOT_SCHEMA = 'lfc_l_ledger_v0.1'
LEDGER_FILE = 'ledger.jsonl'
SNAPSHOT_FILE = 'l_ledger.json'
POSITIONS_URL = 'https://data-api.polymarket.com/positions'
_EVENTS = {'genesis', 'baseline', 'session_start', 'leg_intent', 'leg_ack', 'leg_terminal', 'session_end', 'halt',
           'mismatch'}


class LedgerUnavailable(RuntimeError):
    """Missing, unreadable or inconsistent ledger state: callers must refuse."""


class LedgerCap(RuntimeError):
    """A placement would break the signed L gate, or the campaign has stopped."""


def _num(value, name):
    try:
        result = _decimal(value)
    except QuoteRefused:
        raise LedgerUnavailable('ledger_number_' + name) from None
    if result < 0:
        raise LedgerUnavailable('ledger_negative_' + name)
    return result


def leg_cost(leg):
    """(filled, resting) cost of one of our legs, in pUSD."""
    price = _num(leg['price'], 'price')
    if leg['status'] == 'terminal':
        return _num(leg['size_matched'], 'size_matched') * price, Decimal(0)
    return Decimal(0), _num(leg['size'], 'size') * price


def band_reserve(size, prices):
    """reserve = size x (p_yes + p_no) of the band being posted."""
    return _decimal(size) * sum((_decimal(p) for p in prices), Decimal(0))


_HEADER = frozenset(('schema_version', 'kind', 'sequence', 'previous_sha256', 'recorded_at_utc', 'event'))


class Ledger:
    """Chained ledger. Construct with Ledger.open (existing) or Ledger.create (explicit, once)."""

    def __init__(self, path, *, clock, rows, raw):
        self.path, self.clock = Path(path), clock
        self.rows, self._raw_len = rows, len(raw)
        self.previous = hashlib.sha256(raw.splitlines(keepends=True)[-1]).hexdigest() if rows else None
        self._replay()

    # ----- construction -------------------------------------------------------------------------------------
    @classmethod
    def create(cls, path, *, clock, maker_address, budget=LFC.BUDGET_PUSD):
        path = Path(path)
        if path.exists():
            raise LedgerUnavailable('ledger_exists')
        if _decimal(budget) != LFC.BUDGET_PUSD:
            raise LedgerUnavailable('ledger_budget_differs')
        path.parent.mkdir(parents=True, exist_ok=True)
        row = cls._row(0, None, clock, 'genesis', {'budget_pusd': str(LFC.BUDGET_PUSD), 'maker_address': maker_address,
                                                   'pilot_size': str(LFC.PILOT_SIZE), 'protocol': LFC.PROTOCOL})
        raw = canonical_bytes(row)
        with path.open('xb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        ledger = cls.open(path, clock=clock, maker_address=maker_address)
        ledger.write_snapshot()
        return ledger

    @classmethod
    def open(cls, path, *, clock, maker_address=None):
        path = Path(path)
        try:
            raw = path.read_bytes()
        except OSError:
            raise LedgerUnavailable('ledger_missing') from None
        rows = cls._verify(raw)
        genesis = rows[0]
        if _decimal(genesis['budget_pusd']) != LFC.BUDGET_PUSD:
            raise LedgerUnavailable('ledger_budget_differs')
        if maker_address is not None and str(genesis['maker_address']).lower() != str(maker_address).lower():
            raise LedgerUnavailable('ledger_account_differs')
        return cls(path, clock=clock, rows=rows, raw=raw)

    @staticmethod
    def _row(sequence, previous, clock, event, fields):
        if set(fields) & _HEADER:
            raise LedgerUnavailable('ledger_reserved_field')
        return {'schema_version': LEDGER_SCHEMA, 'kind': 'lfc_ledger', 'sequence': sequence,
                'previous_sha256': previous, 'recorded_at_utc': utc(clock()).isoformat(), 'event': event, **fields}

    @staticmethod
    def _verify(raw):
        if not raw:
            raise LedgerUnavailable('ledger_empty')
        if not raw.endswith(b'\n'):
            raise LedgerUnavailable('ledger_truncated')
        rows, previous, last = [], None, None
        for index, line in enumerate(raw.splitlines(keepends=True)):
            try:
                row = json.loads(line)
                when = utc(row['recorded_at_utc'])
                ok = (canonical_bytes(row) == line and row['schema_version'] == LEDGER_SCHEMA and
                      row['kind'] == 'lfc_ledger' and row['sequence'] == index and
                      row['previous_sha256'] == previous and row['event'] in _EVENTS and
                      (last is None or when >= last) and (index == 0) == (row['event'] == 'genesis'))
            except (ValueError, KeyError, TypeError):
                ok = False
            if not ok:
                raise LedgerUnavailable('ledger_chain_broken')
            previous, last = hashlib.sha256(line).hexdigest(), when
            rows.append(row)
        return rows

    # ----- state --------------------------------------------------------------------------------------------
    def _replay(self):
        self.legs, self.by_order, self.sessions, self.baselines = {}, {}, {}, []
        self.halted, self.mismatches = False, []
        for row in self.rows:
            self._apply(row)

    def _apply(self, row):
        event = row['event']
        if event == 'baseline':
            self.baselines.append(row)
        elif event == 'session_start':
            if row['session_id'] in self.sessions:
                raise LedgerUnavailable('ledger_session_repeated')
            self.sessions[row['session_id']] = {'start': row, 'end': None, 'legs': []}
        elif event == 'leg_intent':
            session = self.sessions.get(row['session_id'])
            if session is None or session['end'] is not None or row['intent_key'] in self.legs:
                raise LedgerUnavailable('ledger_intent_scope')
            for key in ('price', 'size'):
                _num(row[key], key)
            self.legs[row['intent_key']] = {**{k: row[k] for k in ('session_id', 'intent_key', 'token_id',
                                            'condition_id', 'price', 'size', 'fee_rate_bps')},
                                            'order_id': None, 'status': 'intent', 'size_matched': '0'}
            session['legs'].append(row['intent_key'])
        elif event == 'leg_ack':
            leg = self.legs.get(row['intent_key'])
            if leg is None or leg['order_id'] is not None or not row['order_id'] or row['order_id'] in self.by_order:
                raise LedgerUnavailable('ledger_ack_scope')
            leg['order_id'], leg['status'] = row['order_id'], 'open'
            self.by_order[row['order_id']] = row['intent_key']
        elif event == 'leg_terminal':
            leg = self.legs.get(self.by_order.get(row['order_id'], ''))
            if leg is None or leg['status'] == 'terminal':
                raise LedgerUnavailable('ledger_terminal_scope')
            _num(row['size_matched'], 'size_matched')
            leg['status'], leg['size_matched'] = 'terminal', row['size_matched']
        elif event == 'mismatch':
            self.mismatches.append(row)
            self.halted = True
        elif event == 'session_end':
            session = self.sessions.get(row['session_id'])
            if session is None or session['end'] is not None:
                raise LedgerUnavailable('ledger_session_end_scope')
            session['end'] = row
        elif event == 'halt':
            self.halted = True

    def figures(self):
        filled = resting = Decimal(0)
        for leg in self.legs.values():
            f, r = leg_cost(leg)
            filled, resting = filled + f, resting + r
        return {'L': filled + resting, 'L_filled': filled, 'L_resting': resting}

    def L(self):
        return self.figures()['L']

    def L_filled(self):
        return self.figures()['L_filled']

    def L_resting(self):
        return self.figures()['L_resting']

    def headroom(self, cap=LFC.BUDGET_PUSD):
        return max(Decimal(0), _decimal(cap) - self.L())

    def stop_reason(self, cap=LFC.BUDGET_PUSD):
        """Why the campaign has stopped for good (None = not stopped): a mismatch, a halt, or stop-at-100."""
        if self.mismatches:
            return 'l_reconciliation_mismatch'
        if self.halted:
            return 'ledger_halted'
        if self.L_filled() + LFC.MIN_FEASIBLE_RESERVE > _decimal(cap):
            return 'l_stop_at_cap'
        return None

    def post_gate(self, *, reserve, own_resting=Decimal(0), cap=LFC.BUDGET_PUSD):
        """Signed gate: L_after_cancel_of_replaced_leg + reserve <= cap (raises LedgerCap).

        reserve is size x (p_yes + p_no) of the band being posted or requoted; own_resting is the resting cost of
        that band's own legs still counted in L, which the reserve already covers (a replaced leg is cancelled and
        terminal before its replacement is gated, so it is no longer in L).
        """
        stopped = self.stop_reason(LFC.BUDGET_PUSD)
        if stopped:
            raise LedgerCap(stopped)
        base = self.L() - _decimal(own_resting)
        if base + _decimal(reserve) > _decimal(cap):
            raise LedgerCap('l_budget_refused')
        return base

    def counted_sessions(self):
        return sum(1 for s in self.sessions.values() if s['start']['counted'] and s['legs'])

    def open_sessions(self):
        return [sid for sid, s in self.sessions.items() if s['end'] is None]

    def unresolved_legs(self):
        return [leg for leg in self.legs.values() if leg['status'] != 'terminal']

    def our_order_ids(self):
        return set(self.by_order)

    def tokens(self):
        return {leg['token_id'] for leg in self.legs.values()}

    # ----- writes -------------------------------------------------------------------------------------------
    def record(self, event, **fields):
        if event not in _EVENTS or event == 'genesis':
            raise LedgerUnavailable('ledger_event_unknown')
        # Refuse to append on top of bytes this process did not verify (another writer or an edit).
        try:
            size = self.path.stat().st_size
        except OSError:
            raise LedgerUnavailable('ledger_missing') from None
        if size != self._raw_len:
            raise LedgerUnavailable('ledger_changed_underneath')
        row = self._row(len(self.rows), self.previous, self.clock, event, fields)
        raw = canonical_bytes(row)
        try:
            self._apply(row)  # validates the transition before anything is written
            with self.path.open('ab') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except LedgerUnavailable:
            self._replay()
            raise
        except OSError:
            self._replay()
            raise LedgerUnavailable('ledger_write_failed') from None
        self.rows.append(row)
        self._raw_len += len(raw)
        self.previous = hashlib.sha256(raw).hexdigest()
        self.write_snapshot()
        return row

    def snapshot(self):
        figures = self.figures()
        return {'schema_version': SNAPSHOT_SCHEMA, 'kind': 'lfc_l_ledger', 'history_file': self.path.name,
                'history_rows': len(self.rows), 'history_last_sha256': self.previous,
                'recorded_at_utc': self.rows[-1]['recorded_at_utc'], 'budget_pusd': str(LFC.BUDGET_PUSD),
                **{k: str(v) for k, v in figures.items()}, 'halted': self.halted,
                'mismatches': len(self.mismatches), 'stop_reason': self.stop_reason(),
                'our_order_ids': sorted(self.by_order),
                'legs': [{k: leg[k] for k in ('session_id', 'intent_key', 'order_id', 'token_id', 'condition_id',
                                              'price', 'size', 'status', 'size_matched')}
                         for leg in self.legs.values()]}

    def write_snapshot(self):
        """Rewrite l_ledger.json from the verified history (atomic replace). A failure fails closed."""
        target = self.path.parent / SNAPSHOT_FILE
        temporary = target.with_name(SNAPSHOT_FILE + '.tmp')
        try:
            temporary.write_bytes(canonical_bytes(self.snapshot()))
            os.replace(temporary, target)
        except OSError:
            raise LedgerUnavailable('ledger_snapshot_write_failed') from None

    def intent(self, *, session_id, intent_key, token_id, condition_id, price, size, fee_rate_bps):
        # fee_rate_bps is recorded for the analysis only; the signed L has no fee term.
        return self.record('leg_intent', session_id=session_id, intent_key=intent_key, token_id=token_id,
                           condition_id=condition_id, price=str(price), size=str(size), fee_rate_bps=str(fee_rate_bps))

    def ack(self, intent_key, order_id):
        return self.record('leg_ack', intent_key=intent_key, order_id=str(order_id))

    def terminal(self, order_id, row, *, source):
        """Record a proven terminal read; a still-live or unreadable order stays at full resting cost.

        A later terminal read that disagrees with the recorded size_matched is a reconciliation mismatch: it is
        recorded and stops the campaign for good.
        """
        status = str(row.get('status') or row.get('official_order_status') or '').upper()
        if not status or status == 'LIVE':
            return None
        key = self.by_order.get(str(order_id))
        if key is None:
            return None
        matched = _decimal(row.get('size_matched', 0))
        leg = self.legs[key]
        if leg['status'] == 'terminal':
            if matched != _decimal(leg['size_matched']):
                self.record('mismatch', order_id=str(order_id), recorded=leg['size_matched'], observed=str(matched),
                            source=source, mismatch_kind='terminal_size_matched')
            return None
        return self.record('leg_terminal', order_id=str(order_id), size_matched=str(matched), status=status,
                           source=source)

    def trade_mismatches(self, traded):
        """Pure comparison of traded shares per our order id (traded_shares) with the ledger.

        A terminal leg must match exactly; a non-terminal leg may not have traded more than its size.
        """
        found = []
        for oid, key in self.by_order.items():
            leg, seen = self.legs[key], _decimal(traded.get(oid, 0))
            if leg['status'] == 'terminal' and seen != _decimal(leg['size_matched']):
                found.append({'order_id': oid, 'recorded': leg['size_matched'], 'observed': str(seen),
                              'mismatch_kind': 'trades_vs_size_matched'})
            elif leg['status'] != 'terminal' and seen > _decimal(leg['size']):
                found.append({'order_id': oid, 'recorded': leg['size'], 'observed': str(seen),
                              'mismatch_kind': 'trades_exceed_size'})
        return found

    def reconcile_trades(self, trades, *, source):
        """Record every mismatch between venue trades and the ledger (each stops the campaign for good)."""
        traded = traded_shares(trades, self.by_order)
        found = self.trade_mismatches(traded)
        for row in found:
            self.record('mismatch', source=source, **row)
        return traded, found


def traded_shares(trades, our_order_ids):
    """Shares traded per OUR order id: the trade's taker_order_id or a maker_orders[].order_id. FAILED trades are
    ignored (they never settle)."""
    traded, ours = {}, {str(o) for o in our_order_ids}
    for trade in trades:
        if str(trade.get('status', '')).upper() == 'FAILED':
            continue
        if str(trade.get('taker_order_id')) in ours:
            oid = str(trade['taker_order_id'])
            traded[oid] = traded.get(oid, Decimal(0)) + _decimal(trade.get('size', 0))
        for maker in trade.get('maker_orders') or ():
            oid = str(maker.get('order_id'))
            if oid in ours:
                traded[oid] = traded.get(oid, Decimal(0)) + _decimal(maker.get('matched_amount', 0))
    return {oid: str(v) for oid, v in sorted(traded.items())}


def ledger_path(root):
    return Path(root) / LEDGER_FILE


# ----- wallet baselines -----------------------------------------------------------------------------------------
def fetch_account_positions(maker_address, *, opener=None, timeout=5, page_size=500, max_pages=20):
    """Account-wide public current positions (no credential). Raises on any incomplete read."""
    rows = []
    for page in range(max_pages):
        query = urlencode({'user': maker_address, 'sizeThreshold': 0, 'limit': page_size, 'offset': page * page_size})
        response = (opener or urlopen)(Request(POSITIONS_URL + '?' + query, headers={
            'Accept': 'application/json', 'User-Agent': 'weather-lfc-baseline/1'}), timeout=timeout)
        try:
            status = getattr(response, 'status', 200)
            raw = response.read(5_000_001)
        finally:
            response.close()
        if status != 200 or len(raw) > 5_000_000:
            raise RuntimeError('positions_unreadable')
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise RuntimeError('positions_unreadable')
        rows.extend(payload)
        if len(payload) < page_size:
            return rows
    raise RuntimeError('positions_page_budget')


def normalize_positions(rows):
    result = {}
    for row in rows:
        asset = str(row.get('asset') or row.get('asset_id') or row.get('token_id') or '')
        if not asset:
            raise ValueError('position_without_asset')
        result[asset] = result.get(asset, Decimal(0)) + _decimal(row.get('size', 0))
    return {asset: str(size) for asset, size in sorted(result.items()) if size}


def position_conditions(rows):
    """Condition ids of every non-zero position (PR section 3 event-level exclusion; S0 rule 3). A non-zero row
    without a condition id fails closed."""
    held = set()
    for row in rows:
        if _decimal(row.get('size', 0)) == 0:
            continue
        condition = str(row.get('conditionId') or row.get('condition_id') or '').lower()
        if not condition:
            raise ValueError('position_without_condition')
        held.add(condition)
    return sorted(held)


def take_baseline(*, label, now, maker_address, positions, open_orders, available_collateral):
    if label not in {'t24', 't40'}:
        raise ValueError('baseline_label')
    return {'schema_version': BASELINE_SCHEMA, 'kind': 'lfc_baseline', 'label': label, 'at_utc': utc(now).isoformat(),
            'maker_address': maker_address, 'positions': normalize_positions(positions),
            'position_conditions': position_conditions(positions),
            'open_order_ids': sorted(str(r.get('id') or r.get('order_id') or '') for r in open_orders),
            'open_order_conditions': sorted({str(r.get('market') or r.get('condition_id') or '').lower()
                                             for r in open_orders}),
            'available_collateral': str(_decimal(available_collateral))}


def write_baseline(root, baseline, ledger=None):
    name = f"baseline-{baseline['label']}-{utc(baseline['at_utc']).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    sha = write_new(Path(root) / name, baseline)
    if ledger is not None:
        ledger.record('baseline', label=baseline['label'], file=name, sha256=sha, at_utc=baseline['at_utc'])
    return name, sha


def latest_baseline(root, ledger, label):
    rows = [r for r in ledger.baselines if r['label'] == label]
    if not rows:
        raise LedgerUnavailable('baseline_missing_' + label)
    row = rows[-1]
    try:
        raw = (Path(root) / row['file']).read_bytes()
    except OSError:
        raise LedgerUnavailable('baseline_unreadable_' + label) from None
    if hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise LedgerUnavailable('baseline_hash_' + label)
    value = json.loads(raw)
    if value.get('schema_version') != BASELINE_SCHEMA or value.get('label') != label:
        raise LedgerUnavailable('baseline_schema_' + label)
    return value


def compare_baselines(t24, t40, *, now, current_positions, current_open_orders, ledger_tokens, maker_address):
    """Pre-existing positions are excluded from L; a change since T-40 outside our own tokens is manual activity.

    Returns the list of refusals (empty = pass). t24 must be 20-30 h old, t40 at most 90 min old; neither, nor the
    live account, may carry an open order (PR section 6: the preflight requires zero foreign open orders).
    t24=None is session 0 only (S0 rule 3 names the T-40 min baseline alone).
    """
    now, refusals = utc(now), []
    for snap in (t24, t40) if t24 is not None else (t40,):
        if str(snap['maker_address']).lower() != str(maker_address).lower():
            refusals.append('baseline_account_differs_' + snap['label'])
    age40 = now - utc(t40['at_utc'])
    if t24 is not None and not timedelta(hours=20) <= now - utc(t24['at_utc']) <= timedelta(hours=30):
        refusals.append('baseline_t24_age')
    if not timedelta(0) <= age40 <= timedelta(minutes=90):
        refusals.append('baseline_t40_age')
    if (t24 is not None and t24['open_order_ids']) or t40['open_order_ids']:
        refusals.append('baseline_foreign_open_orders')
    if current_open_orders:
        refusals.append('foreign_open_orders_at_start')

    def outside(positions):
        return {a: _decimal(s) for a, s in positions.items() if a not in ledger_tokens}
    # S0-6 reads "pre-existing positions unchanged against the T-40 min baseline"; T-24 h is a record only (a lot
    # settling or the owner trading before the manual-trading pause may legitimately change it).
    current = normalize_positions(current_positions)
    if outside(t40['positions']) != outside(current):
        refusals.append('wallet_activity_outside_pilot')
    return refusals


def baseline_digest(baseline):
    return digest(baseline)
