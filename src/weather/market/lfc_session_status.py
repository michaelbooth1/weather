"""Public, allowlisted unattended outcomes; never export private journal payloads.

The STOP file is OWNER ONLY: agents must never create it. Its existence requests
real cancellation through the session's existing cleanup, not through this module.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import re
import time
import uuid

from weather.market.lfc_completion import complete_evidence, evidence_flags, session_prediction
from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new

STATUS_DIRECTORY = Path(r'C:\t\pilot\status')
OWNER_STOP_FILE = Path(r'C:\t\pilot\STOP')
OUTCOME_SCHEMA = 'lfc_session_outcome_v0.1'
HEARTBEAT_SCHEMA = 'lfc_session_heartbeat_v0.1'


def public_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value) else None


def amount(value):
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def now():
    return datetime.now(timezone.utc)


class SessionStatus:
    def __init__(self, *, kind, clock=now, monotonic=time.monotonic, checkpoint_hook=None, policy_metadata=None):
        self.clock, self.monotonic = clock, monotonic
        self.started = self.timestamp()
        self.directory, self.stop_file = STATUS_DIRECTORY, OWNER_STOP_FILE
        self.kind, self.session_id = kind, kind + '-' + uuid.uuid4().hex
        self.ids = [self.session_id]
        self.related_session_ids = []
        self.last_tick, self.finished, self.stop_seen = None, False, False
        self.session, self.selection, self.evidence_directory, self.ledger = None, {}, None, None
        self.open_rows, self.reason, self.failed = None, None, False
        self.checkpoint_hook = checkpoint_hook
        self.policy_metadata = ({} if policy_metadata is None else
                                {key: policy_metadata.get(key) for key in ('policy_name', 'policy_revision', 'evidence_lane')})

    def timestamp(self):
        # A failing injected clock must never disable the driver's cleanup watchdog.
        try:
            return self.clock().isoformat()
        except Exception:
            return now().isoformat()

    def bind(self, session_id, *, directory, selection, ledger=None):
        if not public_id(session_id):
            raise ValueError('status_session_id')
        self.session_id = session_id
        self.ids.append(session_id)
        self.related_session_ids.append(session_id)
        self.evidence_directory, self.selection, self.ledger = Path(directory), selection, ledger
        self.last_tick = None
        self.tick()

    def tick(self):
        if self.finished:
            return
        stamp = self.monotonic()
        if self.last_tick is None or stamp - self.last_tick >= 60:
            self.directory.mkdir(parents=True, exist_ok=True)
            row = {'schema_version': HEARTBEAT_SCHEMA, 'state': 'RUNNING',
                   **self.policy_metadata,
                   'session_id': self.session_id, 'at_utc': self.timestamp()}
            with (self.directory / (self.session_id + '.heartbeat.jsonl')).open('ab') as handle:
                handle.write((json.dumps(row, sort_keys=True) + '\n').encode('utf-8'))
                handle.flush()
                os.fsync(handle.fileno())
            self.last_tick = stamp

    def owner_stop(self):
        # OWNER ONLY. An agent must never create this file; it causes cancellation.
        self.stop_seen |= self.stop_file.exists()
        return self.stop_seen

    def checkpoint(self):
        self.tick()
        if self.checkpoint_hook is not None:
            self.checkpoint_hook()
        if self.owner_stop():
            from weather.market.re1_attended import HoldEnd
            raise HoldEnd('owner_stop')

    def _facts(self):
        """Stream only this session's journal; copy only explicit public order fields."""
        placed, cancelled, fills, hashes = set(), set(), {}, {}
        complete = False
        flags = evidence_flags(None)
        cleanup = False
        chosen = self.selection
        if self.evidence_directory is not None:
            try:
                prediction = strict_json(read_bytes(self.evidence_directory / 'prediction.json', 2_000_000))
                flags = evidence_flags(prediction)
                cleanup = prediction.get('cleanup_ok') is True
                placed.update(oid for oid in prediction.get('order_ids', []) if public_id(oid))
                self.reason = self.reason or public_id(prediction.get('reason'))
                session_prediction(self.evidence_directory)
                complete = True
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            for name in ('attempt.json', 'selection.json', 'journal.jsonl', 'prediction.json', 'session_end.json'):
                path = self.evidence_directory / name
                try:
                    hashes[name] = file_sha(path)
                except OSError:
                    complete = False
            try:
                with (self.evidence_directory / 'journal.jsonl').open('rb') as handle:
                    for index in range(100_000):
                        line = handle.readline(2_000_001)
                        if not line:
                            break
                        if len(line) > 2_000_000:
                            raise ValueError('status_journal_limit')
                        row = strict_json(line)
                        if not isinstance(row, dict):
                            raise ValueError('status_journal_shape')
                        if row.get('event') == 'submit_response':
                            response = row.get('response') or {}
                            oid = public_id(response.get('id') or response.get('order_id') or response.get('orderID'))
                            if oid:
                                placed.add(oid)
                        if row.get('event') in ('cleanup_cancel_response', 'cleanup_cancel_all_response'):
                            response = row.get('response') or {}
                            for oid in response.get('cancelled', response.get('canceled', [])):
                                if public_id(oid):
                                    cancelled.add(oid)
                        if row.get('event') in ('terminal_order', 'fill'):
                            order = row.get('order') or {}
                            oid = public_id(order.get('id') or order.get('order_id') or order.get('orderID'))
                            size, price = amount(order.get('size_matched')), amount(order.get('price'))
                            if oid and size is not None and Decimal(size) > 0:
                                fills[oid] = {'order_id': oid, 'size': size, 'price': price}
                    else:
                        raise ValueError('status_journal_limit')
            except (OSError, ValueError, TypeError, AttributeError):
                complete = False
        if self.session is not None:
            placed.update(oid for oid in self.session.known if public_id(oid))
            live_flags = {'evidence_complete': not self.session.evidence_failed,
                          'inventory_proven': getattr(self.session, 'inventory_proven', False),
                          'unknown_submit': self.session.posts != len(self.session.known)}
            flags = evidence_flags(live_flags)
            if not complete_evidence(live_flags):
                complete = False
            cleanup &= self.session.cleanup_ok is True
        if self.ledger is not None:
            for leg in self.ledger.legs.values():
                if leg['session_id'] == self.session_id and amount(leg.get('size_matched')) is not None:
                    size = amount(leg['size_matched'])
                    if Decimal(size) > 0 and public_id(leg.get('order_id')):
                        fills[leg['order_id']] = {'order_id': leg['order_id'], 'size': size,
                                                'price': amount(leg['price'])}
        flags['evidence_complete'] &= complete
        opens = None if not isinstance(self.open_rows, list) else [public_id(
            row.get('id') or row.get('order_id') or row.get('orderID')) for row in self.open_rows]
        if opens != []:
            flags.update(evidence_complete=False, inventory_proven=False)
            cleanup = False
        retirement = getattr(self.session, 'horizon_retirement', None)
        return {**({} if retirement is None else {'horizon_retirement': dict(retirement)}),
                'event': public_id(chosen.get('event_slug')), 'band': public_id(chosen.get('condition_id')),
                'tokens': [public_id(t) for t in chosen.get('token_ids', [])],
                'orders_placed': {'count': None if flags['unknown_submit'] else len(placed),
                                  'known_count': len(placed), 'ids': sorted(placed),
                                  'attempted': getattr(self.session, 'posts', None)},
                'orders_cancelled': {'count': len(cancelled), 'ids': sorted(cancelled)},
                'orders_open_at_exit': opens, 'fills': list(fills.values()),
                'cleanup_ok': cleanup and complete_evidence(flags), **flags, 'evidence_sha256': hashes}

    def finish(self, *, success=False, reason=None):
        if self.finished:
            return
        self.finished = True
        self.owner_stop()
        self.reason = 'owner_stop' if self.stop_seen else public_id(reason) or self.reason
        try:
            facts = self._facts()
        except Exception:
            self.failed = True
            self.reason = self.reason or 'status_evidence_unreadable'
            facts = {'event': None, 'band': None, 'tokens': [], 'orders_placed': None,
                     'orders_cancelled': None, 'orders_open_at_exit': None, 'fills': [],
                     'cleanup_ok': False, **evidence_flags(None), 'evidence_sha256': {}}
        passed = success and not self.failed and not self.stop_seen and facts['cleanup_ok']
        state = 'COMPLETE' if passed else 'STOPPED' if self.stop_seen else 'ATTENTION'
        if success and not self.failed and not self.stop_seen and self.kind == 'driver' and self.evidence_directory is None:
            state = 'COMPLETE_NO_SESSION'
        row = {'schema_version': OUTCOME_SCHEMA, 'session_id': self.session_id, 'kind': self.kind,
               **self.policy_metadata,
               'state': state, 'related_session_ids': sorted(set(self.related_session_ids)),
               'started_at_utc': self.started, 'ended_at_utc': self.timestamp(),
               'halt_reason': self.reason or ('completed' if passed else 'outcome_unproven'), **facts}
        # Publish the actual session first, then its startup-attempt alias. A
        # collision can never leave a new successful alias for an old outcome.
        for record_id in reversed(list(dict.fromkeys(self.ids))):
            try:
                write_new(self.directory / (record_id + '.json'), dict(row, record_id=record_id))
            except BaseException:
                if record_id != self.ids[0]:
                    refused = dict(row, record_id=self.ids[0], state='ATTENTION', cleanup_ok=False,
                                   evidence_complete=False, halt_reason='status_publication_failed')
                    write_new(self.directory / (self.ids[0] + '.json'), refused)
                raise
        return row
