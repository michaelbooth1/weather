"""Canonical minute/terminal projection, driven by anonymous recorded inputs.

Expected minute prices/requote legs and terminal reasons are comparison outputs,
never runtime state inputs. Actual legs advance only through generated intents
and recorded acknowledgment facts. Neither account identity nor HTTP is replayed.
"""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib

from maker_core.contracts import MarketDescriptor, Unavailable
from maker_core.evidence.journal import canonical_bytes
from maker_core.quoting.policy import Book, DecisionInputs, Portfolio, QuoteLeg, RewardTerms, blind_re1, decide
from maker_core.replay.re1 import Re1Session


def legs(prices, size):
    return tuple(QuoteLeg(side, D(price), D(size)) for side, price in zip(('YES', 'NO'), prices))


def projection(action, current):
    return dict(action=action, legs=[dict(outcome=v.outcome, price=str(v.price), size=str(v.size)) for v in current])


def inputs_for(session, frame, existing):
    at, observed = map(datetime.fromisoformat, (frame['at'], frame['observed_at']))
    raw, size = frame['quote_inputs'], D(session['size'])
    # These identity/cap/close fields are neutral scaffolding, not historical
    # evidence. The RE-1 observer does not use inferred market-close gates.
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
                          Portfolio(D(100), D(0), size, size * D('.8'), D(0), size, D(0), size),
                          2, profile=blind_re1, existing=existing)


def replay_session(session, selection):
    assert selection['source_journal_sha256'] == session['source_journal_sha256']
    raw = dict(selection['quote_inputs'])
    for key in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'):
        raw[key] = [(str(v['price']), str(v['size'])) for v in raw[key]]
    frame = dict(at=session['opening']['at'], observed_at=session['opening']['at'], quote_inputs=raw)
    initial = decide(inputs_for(session, frame, ()))
    initial_equal = canonical_bytes(projection(initial.action, initial.legs)) == canonical_bytes(
        projection('QUOTE', legs(selection['expected_prices'], session['size'])))
    runtime = Re1Session(initial.legs, end=datetime.fromisoformat(session['fixed_end_at']))
    expected, actual, mismatches, lifecycle_mismatches = [], [], [], []
    timeline = iter(session['lifecycle'])
    pending = next(timeline, None)
    last_cancel_ack = None

    def consume(item):
        nonlocal last_cancel_ack
        event = item['event']
        now = datetime.fromisoformat(item['at'])
        if event == 'opening_market_snapshot':
            runtime.opening_check(inputs_for(session, item, ()).book)
        elif event == 'submit_market_snapshot':
            runtime.begin_post(inputs_for(session, item, runtime.legs))
        elif event == 'submit_request':
            intent = runtime.pending[0] if runtime.pending else None
            observed = dict(leg=item['leg'], price=item['price'], size=item['size'])
            generated = dict(leg=intent.leg, price=str(intent.price), size=str(intent.size)) if intent else None
            if observed != generated:
                lifecycle_mismatches.append(dict(sequence=item['sequence'], cause='SUBMIT_INTENT_DIFFERENCE',
                                                 expected=observed, actual=generated))
        elif event == 'signed_order_book':
            runtime.signed_book(D(item['ask_min']))
        elif event == 'submit_response':
            runtime.post_result(identity_present=item['identity_present'], ok=item['ok'],
                                status='matched' if item['matched'] else 'live' if item['live'] else 'other',
                                trade=item['trade'])
        elif event == 'cancel_request':
            generated = runtime.pending[0].leg if runtime.pending else None
            if generated != item['leg']:
                lifecycle_mismatches.append(dict(sequence=item['sequence'], cause='CANCEL_INTENT_DIFFERENCE',
                                                 expected=item['leg'], actual=generated))
        elif event == 'cancel_response':
            last_cancel_ack = item['acknowledged']
        elif event == 'cancel_order_read_response':
            runtime.cancel_result(now, acknowledged=last_cancel_ack, filled=item['filled'])
        elif event == 'open_orders_response' and runtime.cancel_ack_at is not None and not runtime.reason:
            runtime.cancel_open_read(now, present=runtime.pending[0].leg in item['legs'])
        elif event == 'open_orders_response' and runtime.pending and not runtime.reason:
            runtime.pre_submit_open_read(now, item['legs'], unknown_count=item['unknown_count'])

    for index, frame in enumerate(session['minutes']):
        while pending is not None and pending['sequence'] < frame['sequence']:
            consume(pending)
            pending = next(timeline, None)
        recorded = legs(frame['prices'], session['size'])
        wanted = projection('CANCEL' if frame['requote_legs'] else 'HOLD', () if frame['requote_legs'] else recorded)
        wanted.update(at=frame['at'], cancel_legs=frame['requote_legs'])
        decision, affected = runtime.minute(inputs_for(session, frame, runtime.legs))
        got = projection(decision.action, decision.legs)
        got.update(at=frame['at'], cancel_legs=list(affected))
        expected.append(wanted)
        actual.append(got)
        if canonical_bytes(got) != canonical_bytes(wanted):
            mismatches.append(dict(minute=index + 1, sequence=frame['sequence'], cause='UNCLASSIFIED_POLICY_DIFFERENCE',
                                   expected=wanted, actual=got, reasons=list(decision.reasons)))
    while pending is not None:
        consume(pending)
        pending = next(timeline, None)
    terminal = session['terminal']
    if terminal['fill_seen']:
        runtime.fill()  # Observed inventory input; never a predicted fill.
    wanted = dict(at=terminal['at'], action='END', reason=terminal['reason'])
    got = dict(at=terminal['at'], action='END' if runtime.reason else 'UNSUPPORTED',
               reason=runtime.reason or 'TRANSPORT_STATE_NOT_REPLAYED')
    expected.append(wanted)
    actual.append(got)
    terminal_equal = canonical_bytes(wanted) == canonical_bytes(got)
    return dict(attempt=session['attempt'], session=session['session'], initial_quote_equal=initial_equal,
                minute_count=len(session['minutes']), matched_minutes=len(session['minutes']) - len(mismatches),
                mismatched_minutes=len(mismatches), minute_divergences=mismatches,
                lifecycle_divergences=lifecycle_mismatches, terminal_equal=terminal_equal,
                terminal_reason=terminal['reason'], actual_terminal_reason=got['reason'],
                decision_bytes_equal=canonical_bytes(actual) == canonical_bytes(expected),
                expected_sha256=hashlib.sha256(canonical_bytes(expected)).hexdigest(),
                actual_sha256=hashlib.sha256(canonical_bytes(actual)).hexdigest(),
                full_session_parity='INCOMPLETE',
                uncovered=['account_and_signing_bindings', 'monotonic_transport_schedule_and_cleanup',
                           'market_close_and_account_caps_not_retained'])
