"""Durable identity of a closure, before its exclusive publication.

Staging/fsync precede the ledger intent. Only its exact staging pathname/bytes
may finish a deferred publication; lost published originals still latch.
"""
import hashlib
import json
import re

from weather.market.lfc_ledger_queries import event_rows
from weather.market.mm_stage2_hold import canonical_bytes


INLINE_LIMIT = 65536


def saved_intent(ledger, attempt):
    rows = event_rows(ledger, 'autostart_close_intent', field='attempt_id', value=attempt)
    return rows[0] if rows else None


def bind(state, path, raw, temporary):
    from weather.market.lfc_campaign_closures import fields_from_raw
    from weather.market.lfc_campaign_state import StateRefused
    item = fields_from_raw(path, raw)
    if saved_intent(state.ledger, item['attempt_id']) is not None:
        raise StateRefused('closure_intent_already_bound')
    return state.ledger.record('autostart_close_intent', **item,
                               staged_file='closed/' + temporary.name,
                               canonical_closure_utf8=raw.decode('utf-8') if len(raw) <= INLINE_LIMIT else None)


def validate(ledger, row):
    from pathlib import Path
    from weather.market.lfc_campaign_closures import validate_anchor, fields_from_raw
    from weather.market.lfc_ledger import LedgerUnavailable
    validate_anchor(ledger, row, intent=True)
    if saved_intent(ledger, row['attempt_id']) is not None:
        raise LedgerUnavailable('ledger_closure_intent_duplicate')
    stage = row.get('staged_file')
    if stage is not None and (not isinstance(stage, str) or not re.fullmatch(
            r'closed/\.' + re.escape(row['attempt_id']) + r'\.json\.attempt-[0-9a-f]{32}', stage)):
        raise LedgerUnavailable('ledger_closure_intent_stage')
    text = row.get('canonical_closure_utf8')
    if text is None and row['file_size'] > INLINE_LIMIT:
        return
    try:
        raw = text.encode('utf-8')
        if (len(raw) > INLINE_LIMIT or len(raw) != row['file_size'] or
                hashlib.sha256(raw).hexdigest() != row['file_sha256'] or canonical_bytes(json.loads(raw)) != raw):
            raise ValueError('closure_intent_bytes')
        if any(row.get(k) != v for k, v in fields_from_raw(Path(row['file']), raw).items()):
            raise ValueError('closure_intent_binding')
    except (AttributeError, ValueError, TypeError, KeyError, RuntimeError):
        raise LedgerUnavailable('ledger_closure_intent_binding') from None


def require_match(state, item):
    from weather.market.lfc_campaign_closures import fault
    saved = saved_intent(state.ledger, item['attempt_id'])
    if saved is None or any(saved.get(key) != value for key, value in item.items()):
        fault(state, item['attempt_id'])
    return saved
