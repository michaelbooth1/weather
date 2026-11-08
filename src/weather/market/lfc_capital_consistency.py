"""Persist propagation mismatches without clearing any monetary incident."""
from datetime import datetime
import uuid

from weather.market.lfc_campaign import TransientPrecheck
from weather.market.lfc_campaign_state import MoneyContradiction

CONFIRM_SECONDS = 15 * 60
REASONS = {'capital_inventory_unreconciled', 'capital_cash_unreconciled'}


def observe(state, now, *, reason=None, read_sha256=None):
    files = sorted((state.root / 'capital-consistency').glob('*.json'))
    last = state.read(files[-1]) if files else None
    if reason is None and (last is None or last['state'] == 'CLEAR'):
        return
    first = (last['first_mismatch_utc'] if reason is not None and last is not None and
             last['state'] == 'MISMATCH' else now.isoformat())
    state.save(f'capital-consistency/{len(files) + 1:08d}.json', {
        'state': 'MISMATCH' if reason else 'CLEAR', 'reason': reason,
        'first_mismatch_utc': first, 'observed_at_utc': now.isoformat(), 'read_sha256': read_sha256})
    if reason is None:
        return
    if (now - datetime.fromisoformat(first)).total_seconds() >= CONFIRM_SECONDS:
        state.latch(uuid.uuid4().hex, 'confirmed_capital_read_mismatch', now)
        raise MoneyContradiction('confirmed_capital_read_mismatch')
    raise TransientPrecheck('capital_propagation_pending')
