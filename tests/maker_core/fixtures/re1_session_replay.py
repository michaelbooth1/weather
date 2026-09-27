"""Offline RE-1 decision projection; no account, SDK, or filesystem access.

The journal has no native QuoteDecision objects. Compare canonical bytes of the
shared observable action/legs projection, preserving every minute and terminal.
Transport-only terminal causes remain unsupported, never manufactured inputs.
"""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib

from maker_core.contracts import MarketDescriptor, Unavailable
from maker_core.evidence.journal import canonical_bytes
from maker_core.quoting.policy import (
    Book, DecisionInputs, Portfolio, QuoteLeg, RewardTerms, blind_re1, decide,
)


def legs(prices, size):
    return tuple(QuoteLeg(side, D(price), D(size)) for side, price in zip(('YES', 'NO'), prices))


def projection(action, current):
    return dict(action=action, legs=[dict(outcome=v.outcome, price=str(v.price), size=str(v.size)) for v in current])


def inputs_for(session, frame, existing):
    at = datetime.fromisoformat(frame['at'])
    observed = datetime.fromisoformat(frame['observed_at'])
    raw = frame['quote_inputs']
    size = D(session['size'])
    # RE-1 journals do not retain market close or an event-wide portfolio.
    # Explicit neutral scaffolding isolates the recorded quote/hold decisions;
    # it is not historical evidence for these newer gates.
    close = datetime.fromisoformat(session['fixed_end_at']) + timedelta(days=1)
    market = MarketDescriptor('re1-parity', 'event', 'band', {'YES': 'yes', 'NO': 'no'},
                              D(raw['tick']), D(1), None, close, close, None,
                              'journal-projection', {'journal': session['source_journal_sha256']})
    book = Book(observed, *(tuple((D(p), D(s)) for p, s in raw[k])
                           for k in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks')),
                post_only_available=raw['post_only_available'])
    terms = RewardTerms(observed, D(raw['reward_min_size']), D(raw['reward_max_spread_cents']),
                        D(raw['reward_rate_per_day']))
    return DecisionInputs(market, at, book, terms, Unavailable('recorded blind policy', at),
                          Portfolio(size, D(0), size, size * D('.8'), D(0), size, D(0), size),
                          2, profile=blind_re1, existing=existing)


def replay_session(session, selection):
    """Carry the kernel's own legs; separately diagnose recorded-state decisions.

    Recorded terminal fill_seen is an observed account input, not a simulated
    fill prediction. Other terminal causes cannot be inferred from quote books.
    No raw expected decision is ever used to advance the carried kernel state.
    """
    assert selection['source_journal_sha256'] == session['source_journal_sha256']
    raw = dict(selection['quote_inputs'])
    for key in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'):
        raw[key] = [(str(v['price']), str(v['size'])) for v in raw[key]]
    # The older public selection fixture has no capture time. Use a neutral
    # clock ONLY for this already-qualified selection-price control.
    initial_frame = dict(at=session['opening']['at'], observed_at=session['opening']['at'], quote_inputs=raw)
    initial = decide(inputs_for(session, initial_frame, ()))
    current = initial.legs
    initial_equal = canonical_bytes(projection(initial.action, current)) == canonical_bytes(
        projection('QUOTE', legs(selection['expected_prices'], session['size'])))
    expected, actual, mismatches = [], [], []
    local_reasons = Counter()
    for index, frame in enumerate(session['minutes']):
        recorded = legs(frame['prices'], session['size'])
        # RE-1 cancels affected legs before attempting replacements. Compare
        # that immediate cancellation intent with the core's CANCEL, not an
        # invented REQUOTE action that would fail merely on vocabulary.
        wanted = projection('CANCEL' if frame['requote_legs'] else 'HOLD',
                            () if frame['requote_legs'] else recorded)
        wanted.update(at=frame['at'], cancel_legs=frame['requote_legs'])
        decision = decide(inputs_for(session, frame, current))
        got = projection(decision.action, decision.legs)
        got.update(at=frame['at'], cancel_legs=[0 if v.outcome == 'YES' else 1 for v in current]
                   if decision.action in ('CANCEL', 'END') else [])
        expected.append(wanted)
        actual.append(got)
        local = decide(inputs_for(session, frame, recorded))
        local_got = projection(local.action, local.legs)
        local_got.update(at=frame['at'], cancel_legs=[0, 1] if local.action in ('CANCEL', 'END') else [])
        if canonical_bytes(local_got) != canonical_bytes(wanted):
            local_reasons.update(local.reasons)
        if canonical_bytes(got) != canonical_bytes(wanted):
            mismatches.append(dict(minute=index + 1, sequence=frame['sequence'],
                                   expected=wanted, actual=got, reasons=list(decision.reasons)))
        if decision.action in ('QUOTE', 'HOLD'):
            current = decision.legs
        elif decision.action in ('CANCEL', 'END', 'NO_QUOTE'):
            current = ()

    terminal = session['terminal']
    terminal_expected = dict(at=terminal['at'], action='END', reason=terminal['reason'])
    # A fill flag exercises the actual first-fill gate. Do not translate other
    # terminal reasons into inputs chosen to force the recorded outcome.
    if terminal['fill_seen']:
        last = session['minutes'][-1] if session['minutes'] else session['opening']
        decision = decide(replace(inputs_for(session, last, current),
                                  now=datetime.fromisoformat(terminal['at']), fill_seen=True))
        terminal_actual = dict(at=terminal['at'], action=decision.action,
                               reason='fill' if decision.reasons == ('FIRST_FILL_ENDS',) else list(decision.reasons))
    else:
        terminal_actual = dict(at=terminal['at'], action='UNSUPPORTED', reason='TRANSPORT_STATE_NOT_REPLAYED')
    expected.append(terminal_expected)
    actual.append(terminal_actual)
    terminal_equal = canonical_bytes(terminal_expected) == canonical_bytes(terminal_actual)
    return dict(attempt=session['attempt'], session=session['session'], initial_quote_equal=initial_equal,
                minute_count=len(session['minutes']), matched_minutes=len(session['minutes']) - len(mismatches),
                mismatched_minutes=len(mismatches), first_mismatch=mismatches[0] if mismatches else None,
                mismatched_minute_indices=[m['minute'] for m in mismatches],
                recorded_state_reasons=dict(sorted(local_reasons.items())), terminal_equal=terminal_equal,
                terminal_reason=terminal['reason'],
                decision_bytes_equal=canonical_bytes(actual) == canonical_bytes(expected),
                expected_sha256=hashlib.sha256(canonical_bytes(expected)).hexdigest(),
                actual_sha256=hashlib.sha256(canonical_bytes(actual)).hexdigest(),
                # Even matching minutes/fill termination do not replay sequential
                # post acks, fresh-ask checks, failed cancels, or cleanup.
                full_session_parity='FAIL' if mismatches or not initial_equal else 'INCOMPLETE',
                uncovered=['opening_and_sequential_submit_checks', 'transport_and_cleanup',
                           'market_close_and_account_caps_not_retained'])
