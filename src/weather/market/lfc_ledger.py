"""Worst-case ledger L and wallet baselines for the live-fill calibration pilot.

L is the running worst-case loss of the pilot across ALL sessions (the 100 pUSD budget spans the eight counted
sessions and any session 0). It counts only legs this pilot's script posted, keyed by our own intents and order
ids; pre-existing wallet positions are excluded and pinned by T-24 h / T-40 min baselines instead.

    L = sum over our legs of worst(leg)
    worst(leg) = size_at_risk * price * (1 + fee_rate_bps / 10000)
    size_at_risk = size            while the leg is an intent (posted or maybe posted) or rests (not terminal)
                 = size_matched    once a terminal order read proves the leg is no longer live

Filled shares are valued at zero recovery (cost basis lost) and rewards are never netted. The fee term is an
upper bound for both the legacy (rate x min(p, 1-p)) and current (rate x p x (1-p)) fee shapes, so a filled
leg's cost plus its fee is never under-counted. A posted-but-unacknowledged intent stays at full worst case until
an owner reconcile proves otherwise.

The ledger is an append-only, hash-chained JSONL file. Every read verifies the full chain; a missing, empty,
truncated, reordered or edited file raises LedgerUnavailable and every caller fails closed. Nothing here
creates an exchange capability.
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
LEDGER_FILE = 'ledger.jsonl'
POSITIONS_URL = 'https://data-api.polymarket.com/positions'
_EVENTS = {'genesis', 'baseline', 'session_start', 'leg_intent', 'leg_ack', 'leg_terminal', 'session_end', 'halt'}


class LedgerUnavailable(RuntimeError):
    """Missing, unreadable or inconsistent ledger state: callers must refuse."""


class LedgerCap(RuntimeError):
    """A placement would take L past the cap, or L already reached it."""


def _num(value, name):
    try:
        result = _decimal(value)
    except QuoteRefused:
        raise LedgerUnavailable('ledger_number_' + name) from None
    if result < 0:
        raise LedgerUnavailable('ledger_negative_' + name)
    return result


def leg_worst(leg):
    fee = _num(leg['fee_rate_bps'], 'fee') / Decimal(10000)
    at_risk = _num(leg['size_matched'], 'size_matched') if leg['status'] == 'terminal' else _num(leg['size'], 'size')
    return at_risk * _num(leg['price'], 'price') * (1 + fee)


def order_worst(price, size, fee_rate_bps):
    return leg_worst({'price': price, 'size': size, 'fee_rate_bps': fee_rate_bps, 'status': 'intent',
                      'size_matched': '0'})


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
        return cls.open(path, clock=clock, maker_address=maker_address)

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
        self.halted = False
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
            for key in ('price', 'size', 'fee_rate_bps'):
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
        elif event == 'session_end':
            session = self.sessions.get(row['session_id'])
            if session is None or session['end'] is not None:
                raise LedgerUnavailable('ledger_session_end_scope')
            session['end'] = row
        elif event == 'halt':
            self.halted = True

    def L(self):
        return sum((leg_worst(leg) for leg in self.legs.values()), Decimal(0))

    def headroom(self, cap=LFC.BUDGET_PUSD):
        return max(Decimal(0), _decimal(cap) - self.L())

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
        return row

    def check_new(self, *, price, size, fee_rate_bps, cap=LFC.BUDGET_PUSD):
        """Refuse a placement when L + its worst case would exceed the cap, or L already reached it."""
        current, cap = self.L(), _decimal(cap)
        if self.halted or current >= cap:
            raise LedgerCap('ledger_cap_reached')
        if current + order_worst(price, size, fee_rate_bps) > cap:
            raise LedgerCap('ledger_cap_would_exceed')
        return current

    def intent(self, *, session_id, intent_key, token_id, condition_id, price, size, fee_rate_bps):
        return self.record('leg_intent', session_id=session_id, intent_key=intent_key, token_id=token_id,
                           condition_id=condition_id, price=str(price), size=str(size), fee_rate_bps=str(fee_rate_bps))

    def ack(self, intent_key, order_id):
        return self.record('leg_ack', intent_key=intent_key, order_id=str(order_id))

    def terminal(self, order_id, row, *, source):
        """Record a proven terminal read; a still-live or unreadable order stays at worst case."""
        status = str(row.get('status') or row.get('official_order_status') or '').upper()
        if not status or status == 'LIVE':
            return None
        key = self.by_order.get(str(order_id))
        if key is None or self.legs[key]['status'] == 'terminal':
            return None
        return self.record('leg_terminal', order_id=str(order_id), size_matched=str(_decimal(row.get('size_matched', 0))),
                           status=status, source=source)


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


def take_baseline(*, label, now, maker_address, positions, open_orders, available_collateral):
    if label not in {'t24', 't40'}:
        raise ValueError('baseline_label')
    return {'schema_version': BASELINE_SCHEMA, 'kind': 'lfc_baseline', 'label': label, 'at_utc': utc(now).isoformat(),
            'maker_address': maker_address, 'positions': normalize_positions(positions),
            'open_order_ids': sorted(str(r.get('id') or r.get('order_id') or '') for r in open_orders),
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
    """Pre-existing positions are excluded from L; any change outside our own tokens is manual activity -> refuse.

    Returns the list of refusals (empty = pass). t24 must be 20-30 h old, t40 at most 90 min old; neither, nor the
    live account, may carry an open order (a non-pilot open order at start is foreign).
    """
    now, refusals = utc(now), []
    for snap in (t24, t40):
        if str(snap['maker_address']).lower() != str(maker_address).lower():
            refusals.append('baseline_account_differs_' + snap['label'])
    age24, age40 = now - utc(t24['at_utc']), now - utc(t40['at_utc'])
    if not timedelta(hours=20) <= age24 <= timedelta(hours=30):
        refusals.append('baseline_t24_age')
    if not timedelta(0) <= age40 <= timedelta(minutes=90):
        refusals.append('baseline_t40_age')
    if t24['open_order_ids'] or t40['open_order_ids']:
        refusals.append('baseline_foreign_open_orders')
    if current_open_orders:
        refusals.append('foreign_open_orders_at_start')

    def outside(positions):
        return {a: _decimal(s) for a, s in positions.items() if a not in ledger_tokens}
    current = normalize_positions(current_positions)
    if not (outside(t24['positions']) == outside(t40['positions']) == outside(current)):
        refusals.append('wallet_activity_outside_pilot')
    return refusals


def baseline_digest(baseline):
    return digest(baseline)
