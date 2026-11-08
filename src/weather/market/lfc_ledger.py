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
from http.client import HTTPException
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from weather.market import lfc_constants as LFC
from weather.market.mm_stage2_hold import canonical_bytes, digest, utc, write_new
from weather.market.reward_quote import QuoteRefused, _decimal

# v0.2 (fix round 1, review F-5) adds leg_adopt: an unacknowledged intent adopted at reconcile onto the one venue
# order that matches it. New rows are written as v0.2; v0.1 history stays valid and leg_adopt needs a v0.2 row.
LEDGER_SCHEMA = 'lfc_ledger_v0.2'
LEDGER_SCHEMAS = ('lfc_ledger_v0.1', 'lfc_ledger_v0.2', 'lfc_ledger_v0.3', 'lfc_ledger_v0.4')
BASELINE_SCHEMA = 'lfc_baseline_v0.1'
SNAPSHOT_SCHEMA = 'lfc_l_ledger_v0.1'
LEDGER_FILE = 'ledger.jsonl'
SNAPSHOT_FILE = 'l_ledger.json'
# Data API v1 was retired by the venue on 2026-11-02 (HTTP 410 from 22:30Z). v2 (F0, master ruling 2026-11-06):
# OPEN is the superset of held positions (it includes settled-but-unredeemed winners); REDEEMABLE_LOST is listed
# separately. The 0 token floor replaces v1 sizeThreshold=0 (the v2 default drops holdings under 0.1 share).
POSITIONS_URL = 'https://data-api.polymarket.com/v2/positions'
POSITIONS_STATUSES = ('OPEN', 'REDEEMABLE_LOST')
# sort_by=TOKENS: the keyset cursor must not page on a key that moves with prices (the default CURRENT_VALUE does),
# or a row could cross the cursor between pages and be skipped (F0 review finding 1).
POSITIONS_FILTERS = {'include_archived': 'true', 'filter_type': 'TOKENS', 'filter_amount': '0', 'sort_by': 'TOKENS',
                     'sort_direction': 'DESC'}
_EVENTS = {'genesis', 'baseline', 'session_start', 'leg_intent', 'leg_ack', 'leg_adopt', 'leg_terminal', 'session_end',
           'halt', 'mismatch', 'autostart_enroll', 'autostart_claim', 'autostart_incident', 'autostart_result', 'autostart_freeze',
           'owner_history_recovery', 'autostart_no_intent_close', 'autostart_owner_close',
           'autostart_owner_artifact_restored', 'capital_anchor', 'capital_bridge', 'capital_native_group',
           'capital_activity', 'capital_resolution', 'capital_cost', 'capital_zero_resolution'}


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
        self._history_hash = hashlib.sha256(raw)
        self._row_hashes = [hashlib.sha256(line).hexdigest() for line in raw.splitlines(keepends=True)]
        self.previous = self._row_hashes[-1] if rows else None
        self._replay()

    # ----- construction -------------------------------------------------------------------------------------
    @classmethod
    def create(cls, path, *, clock, maker_address, budget=LFC.GENESIS_BUDGET_PUSD):
        path = Path(path)
        if path.exists():
            raise LedgerUnavailable('ledger_exists')
        if _decimal(budget) != LFC.GENESIS_BUDGET_PUSD:
            raise LedgerUnavailable('ledger_budget_differs')
        path.parent.mkdir(parents=True, exist_ok=True)
        row = cls._row(0, None, clock, 'genesis', {'budget_pusd': str(LFC.GENESIS_BUDGET_PUSD), 'maker_address': maker_address,
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
        if _decimal(genesis['budget_pusd']) != LFC.GENESIS_BUDGET_PUSD:
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
        rows, previous, last, version = [], None, None, 0
        for index, line in enumerate(raw.splitlines(keepends=True)):
            try:
                row = json.loads(line)
                when = utc(row['recorded_at_utc'])
                row_version = LEDGER_SCHEMAS.index(row['schema_version'])
                ok = (canonical_bytes(row) == line and row_version >= version and
                      (row['event'] != 'leg_adopt' or row_version >= 1) and
                      (row['event'] != 'autostart_enroll' or row_version >= 2) and
                      (row['event'] != 'owner_history_recovery' or row_version >= 2) and
                      (not row['event'].startswith('capital_') or row_version == 3) and
                      row['kind'] == 'lfc_ledger' and row['sequence'] == index and
                      row['previous_sha256'] == previous and row['event'] in _EVENTS and
                      (last is None or when >= last) and (index == 0) == (row['event'] == 'genesis'))
            except (ValueError, KeyError, TypeError):
                ok = False
            if not ok:
                raise LedgerUnavailable('ledger_chain_broken')
            previous, last, version = hashlib.sha256(line).hexdigest(), when, row_version
            rows.append(row)
        return rows

    # ----- state --------------------------------------------------------------------------------------------
    def _replay(self):
        self.legs, self.by_order, self.sessions, self.baselines = {}, {}, {}, []
        self.enrollment = None
        self.autostart_claims, self.autostart_incidents, self.history_recoveries = [], [], []
        self.autostart_results = []
        self.capital_rows = []
        self._capital_checkpoint = None
        self.halted, self.mismatches = False, []
        self._replaying = True
        try:
            for row in self.rows:
                self._apply(row)
        finally:
            self._replaying = False

    def _apply(self, row):
        event = row['event']
        if event.startswith('capital_'):
            from weather.market.lfc_capital import CapitalBook, CapitalRefused
            try:
                book = self._capital_checkpoint if getattr(self, '_replaying', False) else None
                if book is None:
                    book = CapitalBook(self)
                else:
                    book.sync_lots()
                book.apply(row)
            except (ValueError, KeyError, TypeError) as exc:
                raise LedgerUnavailable(str(exc) if isinstance(exc, CapitalRefused) else 'capital_event_invalid') from None
            self.capital_rows.append(row)
            self._capital_checkpoint = book
        elif event == 'owner_history_recovery':
            if (row.get('session_id') not in self.sessions or self.sessions[row['session_id']]['end'] is None or
                    not all(isinstance(row.get(k), str) and row[k] for k in
                            ('original_evidence_sha256', 'file', 'file_sha256'))):
                raise LedgerUnavailable('ledger_history_recovery_scope')
            self.history_recoveries.append(row)
        elif event == 'autostart_enroll':
            if self.enrollment is not None or self.open_sessions() or self.unresolved_legs():
                raise LedgerUnavailable('ledger_enrollment_scope')
            if not all(isinstance(row.get(k), str) and row[k] for k in ('state_id', 'identity_sha256', 'state_root')):
                raise LedgerUnavailable('ledger_enrollment_identity')
            self.enrollment = row
        elif event == 'autostart_freeze':
            if (self.enrollment is None or row.get('attempt_id') != 'campaign-freeze' or
                    not isinstance(row.get('file_sha256'), str) or
                    any(r['event'] == event and r['sequence'] < row['sequence'] for r in self.rows)):
                raise LedgerUnavailable('ledger_freeze_scope')
        elif event == 'autostart_owner_close':
            proof = row.get('proof', {})
            if (self.enrollment is None or self.unresolved_legs() or self.unacknowledged_intents() or
                    row.get('proof_sha256') != digest(proof) or proof.get('unknown_submit') is not False or
                    proof.get('money_accounting_complete') is not True or proof.get('cleanup_proven') is not True or
                    any(r['event'] == event and r.get('incident_id') == row.get('incident_id') and
                        r['sequence'] < row['sequence'] for r in self.rows)):
                raise LedgerUnavailable('ledger_owner_close_unproved')
            self.halted, self.mismatches = False, []
        elif event == 'autostart_owner_artifact_restored':
            if (not isinstance(row.get('artifact'), str) or not isinstance(row.get('file_sha256'), str) or
                    not any(r['event'] == 'autostart_owner_close' and r.get('file_sha256') == row.get('closure_sha256') and
                            r['sequence'] < row['sequence'] for r in self.rows)):
                raise LedgerUnavailable('ledger_owner_restore_scope')
        elif event == 'autostart_no_intent_close':
            from weather.market.lfc_campaign_recovery import attempt_intents
            if (self.enrollment is None or not any(r['attempt_id'] == row['attempt_id'] for r in self.autostart_claims) or
                    attempt_intents(self, row['attempt_id']) or not isinstance(row.get('file_sha256'), str) or
                    any(r['event'] == event and r['attempt_id'] == row['attempt_id'] and r['sequence'] < row['sequence'] for r in self.rows)):
                raise LedgerUnavailable('ledger_no_intent_close_scope')
        elif event in ('autostart_claim', 'autostart_incident', 'autostart_result'):
            if self.enrollment is None:
                raise LedgerUnavailable('ledger_not_enrolled')
            if not all(isinstance(row.get(k), str) and row[k] for k in ('attempt_id', 'file_sha256')):
                raise LedgerUnavailable('ledger_autostart_record')
            target = {'autostart_claim': self.autostart_claims, 'autostart_incident': self.autostart_incidents,
                      'autostart_result': self.autostart_results}[event]
            if event == 'autostart_result' and not any(r['attempt_id'] == row['attempt_id'] for r in self.autostart_claims):
                raise LedgerUnavailable('ledger_result_without_claim')
            if any(r['attempt_id'] == row['attempt_id'] for r in target):
                raise LedgerUnavailable('ledger_autostart_repeated')
            target.append(row)
        elif event == 'baseline':
            self.baselines.append(row)
        elif event == 'session_start':
            if any(r['event'] == 'autostart_no_intent_close' and r['attempt_id'] == row.get('autostart_attempt_id') and
                   r['sequence'] < row['sequence'] for r in self.rows):
                raise LedgerUnavailable('ledger_attempt_already_closed')
            if row['session_id'] in self.sessions:
                raise LedgerUnavailable('ledger_session_repeated')
            self.sessions[row['session_id']] = {'start': row, 'end': None, 'legs': []}
        elif event == 'leg_intent':
            session = self.sessions.get(row['session_id'])
            if session is None or session['end'] is not None or row['intent_key'] in self.legs:
                raise LedgerUnavailable('ledger_intent_scope')
            for key in ('price', 'size'):
                _num(row[key], key)
            from weather.market.lfc_f2_breadth import daily_gate, PROTOCOL as BREADTH_PROTOCOL
            if session['start'].get('protocol') == BREADTH_PROTOCOL:
                start = session['start']
                fields = ('market_id', 'quote_day_utc', 'quote_offset_pusd', 'quote_arm',
                          'arm_date_toronto', 'arm_market_id', 'per_band_daily_filled_cap_pusd')
                if (row['recorded_at_utc'][:10] != start['quote_day_utc'] or
                        any(row.get(key) != start.get(key) for key in fields)):
                    raise LedgerUnavailable('ledger_breadth_intent_binding')
                try:
                    daily_gate(self, start, reserve=_decimal(row['price']) * _decimal(row['size']))
                except ValueError as exc:
                    raise LedgerUnavailable(str(exc)) from None
            self.legs[row['intent_key']] = {**{k: row[k] for k in ('session_id', 'intent_key', 'token_id',
                                            'condition_id', 'price', 'size', 'fee_rate_bps')},
                                            'order_id': None, 'status': 'intent', 'size_matched': '0'}
            session['legs'].append(row['intent_key'])
        elif event in ('leg_ack', 'leg_adopt'):
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
            from weather.market.mm_account_reads import order_terminal
            if not order_terminal(row, order_id=leg['order_id'], size=leg['size']):
                raise LedgerUnavailable('ledger_terminal_unproven')
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

    def headroom(self, cap=None):
        if any(r['event'] == 'capital_bridge' for r in self.capital_rows):
            from weather.market.lfc_capital import CapitalBook, SCALE
            figures = CapitalBook(self).figures()
            ceiling = figures['funding_native'] if cap is None else min(figures['funding_native'], int(_decimal(cap) * SCALE))
            return Decimal(max(0, ceiling - figures['charged_native'])) / SCALE
        return max(Decimal(0), self.effective_cap(cap) - self.L())

    @staticmethod
    def effective_cap(cap=None):
        """A per-session limit can lower the campaign cap, never raise it."""
        return min(LFC.CAP_PUSD, _decimal(LFC.CAP_PUSD if cap is None else cap))

    def stop_reason(self, cap=None):
        """Why the campaign has stopped for good (None = not stopped): a mismatch, a halt, or stop-at-100."""
        if self.mismatches:
            return 'l_reconciliation_mismatch'
        if self.halted:
            return 'ledger_halted'
        if any(r['event'] == 'capital_bridge' for r in self.capital_rows):
            from weather.market.lfc_capital import CapitalBook
            figures = CapitalBook(self).figures()
            return 'capital_total_ceiling' if figures['charged_native'] > figures['funding_native'] else None
        if self.L_filled() + LFC.MIN_FEASIBLE_RESERVE > self.effective_cap(cap):
            return 'l_stop_at_cap'
        return None

    def post_gate(self, *, reserve, own_resting=Decimal(0), cap=None):
        """Signed gate: L_after_cancel_of_replaced_leg + reserve <= cap (raises LedgerCap).

        reserve is size x (p_yes + p_no) of the band being posted or requoted; own_resting is the resting cost of
        that band's own legs still counted in L, which the reserve already covers (a replaced leg is cancelled and
        terminal before its replacement is gated, so it is no longer in L).
        """
        if any(row['event'] == 'capital_bridge' for row in self.capital_rows):
            raise LedgerCap('capital_requires_native_gate')
        stopped = self.stop_reason(LFC.CAP_PUSD)
        if stopped:
            raise LedgerCap(stopped)
        base = self.L() - _decimal(own_resting)
        if base + _decimal(reserve) > self.effective_cap(cap):
            raise LedgerCap('l_budget_refused')
        return base

    def counted_sessions(self):
        legacy = sum(1 for s in self.sessions.values() if s['start']['counted'] and s['legs'] and
                     s['start'].get('protocol') not in {'lfc_autostart_v2', 'lfc_autostart_v3'})
        f2 = {s['start']['autostart_attempt_id'] for s in self.sessions.values() if s['legs'] and
              s['start'].get('protocol') in {'lfc_autostart_v2', 'lfc_autostart_v3'}}
        return legacy + len(f2)

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
        fields = {**getattr(self, 'policy_metadata', {}), **fields}
        if event not in _EVENTS or event == 'genesis':
            raise LedgerUnavailable('ledger_event_unknown')
        if self.enrollment is not None or self.history_recoveries or event in {'autostart_enroll', 'owner_history_recovery'}:
            from weather.market.lfc_campaign_guard import require_account
            require_account(self.rows[0]['maker_address'])
        # Refuse to append on top of bytes this process did not verify (another writer or an edit).
        try:
            size = self.path.stat().st_size
        except OSError:
            raise LedgerUnavailable('ledger_missing') from None
        if size != self._raw_len:
            raise LedgerUnavailable('ledger_changed_underneath')
        from weather.market.lfc_recording_io import file_sha
        try:
            unchanged = file_sha(self.path) == self._history_hash.hexdigest()
        except OSError:
            raise LedgerUnavailable('ledger_write_failed') from None
        if not unchanged:
            raise LedgerUnavailable('ledger_changed_underneath')
        row = self._row(len(self.rows), self.previous, self.clock, event, fields)
        if self.enrollment is not None or self.history_recoveries or event in {'autostart_enroll', 'owner_history_recovery'}:
            row['schema_version'] = 'lfc_ledger_v0.3'
        if self.capital_rows or event.startswith('capital_'):
            row['schema_version'] = 'lfc_ledger_v0.4'
        if utc(row['recorded_at_utc']) < utc(self.rows[-1]['recorded_at_utc']):
            raise LedgerUnavailable('ledger_clock_regressed')
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
        self._history_hash.update(raw)
        self._raw_len += len(raw)
        self.previous = hashlib.sha256(raw).hexdigest()
        self._row_hashes.append(self.previous)
        self.write_snapshot()
        return row

    def snapshot(self):
        figures = self.figures()
        capital = None
        if any(r['event'] == 'capital_bridge' for r in self.capital_rows):
            from weather.market.lfc_capital import CapitalBook
            capital = CapitalBook(self).figures()
        return {'schema_version': SNAPSHOT_SCHEMA, 'kind': 'lfc_l_ledger', 'history_file': self.path.name,
                'history_rows': len(self.rows), 'history_last_sha256': self.previous,
                'recorded_at_utc': self.rows[-1]['recorded_at_utc'], 'budget_pusd': str(LFC.CAP_PUSD),
                **({} if capital is None else {'capital_mode': 'fixed_sleeve_redeemed_principal_only', 'capital': capital}),
                **{k: str(v) for k, v in figures.items()}, 'halted': self.halted,
                'mismatches': len(self.mismatches), 'stop_reason': self.stop_reason(),
                'our_order_ids': sorted(self.by_order),
                'legs': [{k: leg[k] for k in ('session_id', 'intent_key', 'order_id', 'token_id', 'condition_id',
                                              'price', 'size', 'status', 'size_matched')}
                         for leg in self.legs.values()]}

    def write_snapshot(self):
        """Rewrite l_ledger.json from the verified history (atomic replace). A failure fails closed."""
        if self.enrollment is not None:
            from weather.market.lfc_campaign_guard import require_account
            require_account(self.rows[0]['maker_address'])
        target = self.path.parent / SNAPSHOT_FILE
        temporary = target.with_name(SNAPSHOT_FILE + '.tmp')
        try:
            temporary.write_bytes(canonical_bytes(self.snapshot()))
            os.replace(temporary, target)
        except OSError:
            raise LedgerUnavailable('ledger_snapshot_write_failed') from None

    def intent(self, *, session_id, intent_key, token_id, condition_id, price, size, fee_rate_bps):
        # fee_rate_bps is recorded for the analysis only; the signed L has no fee term.
        if any(row['event'] == 'capital_bridge' for row in self.capital_rows):
            from weather.market.lfc_capital import CapitalBook
            # Lowest durable boundary: concurrent bands cannot both spend the
            # same headroom even if an earlier planning gate was stale.
            CapitalBook(self).gate(reserve=_decimal(price) * _decimal(size))
        from weather.market.lfc_f2_breadth import daily_gate, PROTOCOL as BREADTH_PROTOCOL
        start = self.sessions[session_id]['start']
        daily_gate(self, start, reserve=_decimal(price) * _decimal(size))
        metadata = ({key: start[key] for key in ('market_id', 'quote_day_utc', 'quote_offset_pusd', 'quote_arm',
                    'arm_date_toronto', 'arm_market_id', 'per_band_daily_filled_cap_pusd')}
                    if start.get('protocol') == BREADTH_PROTOCOL else {})
        return self.record('leg_intent', session_id=session_id, intent_key=intent_key, token_id=token_id,
                           condition_id=condition_id, price=str(price), size=str(size), fee_rate_bps=str(fee_rate_bps), **metadata)

    def ack(self, intent_key, order_id):
        return self.record('leg_ack', intent_key=intent_key, order_id=str(order_id))

    def adopt(self, intent_key, order_id, *, source, evidence):
        """Review F-5: bind an unacknowledged intent to the one venue order matching all of its fields; the leg then
        resolves like any acknowledged leg (it stays at full resting cost until a terminal read)."""
        return self.record('leg_adopt', intent_key=intent_key, order_id=str(order_id), source=source,
                           evidence=evidence)

    def unacknowledged_intents(self):
        return [leg for leg in self.legs.values() if leg['status'] != 'terminal' and leg['order_id'] is None]

    def row_sha256(self, sequence):
        return self._row_hashes[sequence]

    def terminal(self, order_id, row, *, source):
        """Record a proven terminal read; a still-live or unreadable order stays at full resting cost.

        A later terminal read that disagrees with the recorded size_matched is a reconciliation mismatch: it is
        recorded and stops the campaign for good.
        """
        from weather.market.mm_account_reads import order_terminal
        key = self.by_order.get(str(order_id))
        if key is None:
            return None
        leg = self.legs[key]
        if not order_terminal(row, order_id=order_id, size=leg['size']):
            return None
        status = str(row.get('status') or row.get('official_order_status') or '').upper()
        matched = _decimal(row.get('size_matched', 0))
        if leg['status'] == 'terminal':
            if matched != _decimal(leg['size_matched']):
                self.record('mismatch', order_id=str(order_id), recorded=leg['size_matched'], observed=str(matched),
                            source=source, mismatch_kind='terminal_size_matched')
            return None
        return self.record('leg_terminal', order_id=str(order_id), size_matched=str(matched), status=status,
                           source=source)

    def trade_mismatches(self, traded, *, order_ids=None):
        """Pure comparison of traded shares per our order id (traded_shares) with the ledger.

        A terminal leg must match exactly; a non-terminal leg may not have traded more than its size.
        """
        found = []
        for oid, key in self.by_order.items():
            if order_ids is not None and oid not in order_ids:
                continue
            leg, seen = self.legs[key], _decimal(traded.get(oid, 0))
            if leg['status'] == 'terminal' and seen != _decimal(leg['size_matched']):
                found.append({'order_id': oid, 'recorded': leg['size_matched'], 'observed': str(seen),
                              'mismatch_kind': 'trades_vs_size_matched'})
            elif leg['status'] != 'terminal' and seen > _decimal(leg['size']):
                found.append({'order_id': oid, 'recorded': leg['size'], 'observed': str(seen),
                              'mismatch_kind': 'trades_exceed_size'})
        return found

    def trade_scope_ids(self, condition=None):
        return {oid for oid, key in self.by_order.items()
                if condition is None or str(self.legs[key]['condition_id']).lower() == str(condition).lower()}

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
def _positions_page(query, *, opener, timeout):
    try:
        response = (opener or urlopen)(Request(POSITIONS_URL + '?' + urlencode(query), headers={
            'Accept': 'application/json', 'User-Agent': 'weather-lfc-baseline/2'}), timeout=timeout)
    except (OSError, HTTPException):  # URLError/HTTPError (e.g. the v1 410), timeouts, resets
        raise RuntimeError('positions_unreadable') from None
    try:
        status = getattr(response, 'status', 200)
        raw = response.read(5_000_001)
    except (OSError, HTTPException):  # a timeout, reset or IncompleteRead mid-body
        raise RuntimeError('positions_unreadable') from None
    finally:
        response.close()
    if status != 200 or len(raw) > 5_000_000:
        raise RuntimeError('positions_unreadable')
    try:
        payload = json.loads(raw, parse_float=Decimal)
    except ValueError:
        raise RuntimeError('positions_unreadable') from None
    if (not isinstance(payload, dict) or not isinstance(payload.get('data'), list)
            or not isinstance(payload.get('pagination'), dict)):
        raise RuntimeError('positions_unreadable')
    cursor, more = payload['pagination'].get('next_cursor'), payload['pagination'].get('has_more')
    # has_more is exact in v2; it must agree with the cursor, or a page could be lost silently (review finding 2).
    if (cursor is not None and not isinstance(cursor, str)) or not isinstance(more, bool) or more != bool(cursor):
        raise RuntimeError('positions_unreadable')
    return payload['data'], cursor or None


def _position_row(row, maker_address, status):
    """One v2 row in the v1 shape every caller reads (asset, size, conditionId). Never defaults a missing size."""
    if not isinstance(row, dict):
        raise RuntimeError('positions_unreadable')
    token, condition, size = row.get('token_id'), row.get('condition_id'), row.get('current_size')
    if (str(row.get('proxy_wallet', '')).lower() != str(maker_address).lower()
            or not isinstance(token, str) or not token.isdigit() or not isinstance(condition, str) or not condition
            or size is None or isinstance(size, bool)):
        raise RuntimeError('positions_unreadable')
    try:
        amount = _decimal(size)
    except QuoteRefused:
        raise RuntimeError('positions_unreadable') from None
    if amount < 0:
        raise RuntimeError('positions_unreadable')
    return {'asset': token, 'size': str(amount), 'conditionId': condition, 'status': str(row.get('status', '')),
            'requested_status': status}


def fetch_account_positions(maker_address, *, opener=None, timeout=5, page_size=1000, max_pages=20,
                            status_counts=None):
    """Account-wide public current positions from Data API v2 (no credential). Raises on any incomplete read.

    Walks every status in POSITIONS_STATUSES by cursor (sorted by TOKENS) until next_cursor is null, de-duplicates
    on token_id and refuses (positions_conflict) when one token carries two different sizes. A status that needs more
    than one page is walked until two consecutive walks agree, at most three walks (positions_walks_differ). ``status_counts``, when a dict, is filled
    with the row count per requested status for the baseline evidence.
    """
    merged, counts = {}, {}
    for status in POSITIONS_STATUSES:
        previous = None
        for _walk in range(3):
            pages, rows = _walk_status(maker_address, status, opener=opener, timeout=timeout,
                                       page_size=page_size, max_pages=max_pages)
            if pages == 1:
                break
            observed = {r['asset']: Decimal(r['size']) for r in rows}
            if observed == previous:
                break  # two consecutive multi-page walks agree
            previous = observed
        else:
            # A fill between walks may differ once; three walks with no consecutive agreement refuse.
            raise RuntimeError('positions_walks_differ')
        counts[status] = len(rows)
        for row in rows:
            seen = merged.get(row['asset'])
            if seen is None:
                merged[row['asset']] = row
            elif Decimal(seen['size']) != Decimal(row['size']):
                raise RuntimeError('positions_conflict')
    if status_counts is not None:
        status_counts.update(counts)
    return [merged[token] for token in sorted(merged)]


def _walk_status(maker_address, status, *, opener, timeout, page_size, max_pages):
    rows, cursor = [], None
    for page_number in range(1, max_pages + 1):
        query = {'user': maker_address, **POSITIONS_FILTERS}
        query.update({'cursor': cursor} if cursor else {'status': status, 'limit': page_size})
        page, cursor = _positions_page(query, opener=opener, timeout=timeout)
        rows.extend(_position_row(raw, maker_address, status) for raw in page)
        if cursor is None:
            if len({r['asset'] for r in rows}) != len(rows):
                raise RuntimeError('positions_conflict')  # one status listing a token twice
            return page_number, rows
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


def take_baseline(*, label, now, maker_address, positions, open_orders, available_collateral,
                  position_status_counts=None):
    if label not in {'t24', 't40'}:
        raise ValueError('baseline_label')
    extra = {} if position_status_counts is None else {
        'positions_source': POSITIONS_URL, 'position_status_counts': dict(sorted(position_status_counts.items()))}
    return {**extra, 'schema_version': BASELINE_SCHEMA, 'kind': 'lfc_baseline', 'label': label,
            'at_utc': utc(now).isoformat(),
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
