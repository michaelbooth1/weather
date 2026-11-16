"""Pre-placement stream failures stay inside the original claim.

Guards: T119 Monday 17:07Z closed WebSocket surfaces as user_stream_readiness.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.market.test_lfc_pilot import Clock
from weather.market.lfc_f2_runtime import start_stream
from weather.market.lfc_campaign_state import StateRefused
from weather.market.mm_stage2_hold import HoldEnd


@pytest.mark.parametrize('error', [RuntimeError('user_stream_readiness'), ConnectionError('user_stream_readiness')])
def test_startup_transport_defers_then_recovers_same_claim_before_any_session(error):
    clock, calls, rows = Clock(), [], []
    ledger = SimpleNamespace(open_sessions=lambda: [], unresolved_legs=lambda: [])
    runtime = SimpleNamespace(clock=clock, state=SimpleNamespace(ledger=ledger))
    authority = SimpleNamespace(entry=SimpleNamespace(permits=lambda now: True),
                                resync=lambda: True, check=lambda: calls.append('check'))
    def start():
        calls.append('start')
        if calls.count('start') < 3: raise error
    start_stream(SimpleNamespace(start=start), runtime=runtime, authority=authority,
        status=SimpleNamespace(progress=lambda: None),
        journal=SimpleNamespace(record=lambda event, **kw: rows.append((event, kw))))
    assert calls == ['start', 'check', 'start', 'check', 'start']
    assert len(rows) == 2 and all(row[0] == 'startup_stream_unavailable' for row in rows)
    assert clock.seconds == 2 and not ledger.open_sessions()


@pytest.mark.parametrize('mode', ['malformed', 'after_placement', 'window'])
def test_startup_retry_never_hides_invalid_events_placement_or_window_end(mode):
    clock, calls = Clock(), []
    ledger = SimpleNamespace(open_sessions=lambda: ['existing'] if mode == 'after_placement' else [],
                             unresolved_legs=lambda: [])
    runtime = SimpleNamespace(clock=clock, state=SimpleNamespace(ledger=ledger))
    authority = SimpleNamespace(entry=SimpleNamespace(permits=lambda now: clock.seconds < 1),
                                resync=lambda: True, check=lambda: None)
    def start():
        calls.append(True)
        raise RuntimeError('user_stream_invalid_event' if mode == 'malformed' else 'user_stream_readiness')
    expected = StateRefused if mode == 'after_placement' else HoldEnd if mode == 'window' else RuntimeError
    with pytest.raises(expected):
        start_stream(SimpleNamespace(start=start), runtime=runtime, authority=authority,
            status=SimpleNamespace(progress=lambda: None), journal=SimpleNamespace(record=lambda *a, **kw: None))
    assert len(calls) == (0 if mode == 'after_placement' else 1)
