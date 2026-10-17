"""88a adapter for the blind lifecycle, with explicit assumed transport.

The capture bundle has no RE-1 private acks or post-signing books. This adapter
is a diagnostic counterfactual, never recorded-session transport parity.
"""
from dataclasses import replace
from datetime import timedelta

from maker_core.quoting.policy import decide, QuoteLeg, _fits
from maker_core.replay.re1 import Re1Session


def tick(engine, cid, at, inputs):
    state = engine.states[cid]
    runtime = state.re1
    if runtime is None:
        decision = decide(inputs)
        if decision.action != 'QUOTE':
            engine.record_decision(cid, at, decision)
            return
        end = at + timedelta(hours=6)
        if end.date() != at.date():
            engine.record_decision(cid, at, replace(decision, action='NO_QUOTE', legs=(),
                                                   reasons=('SESSION_DURATION_OR_UTC_DAY',)))
            return
        runtime = state.re1 = Re1Session(decision.legs, end=end,
                                        available=inputs.portfolio.cash-inputs.portfolio.reserved_elsewhere)
        engine.schedule(end)
        runtime.opening_check(inputs.book)
        affected = ()
    else:
        if at >= runtime.end:
            runtime.finish('fixed_end')
        if runtime.reason:
            decision = replace(state.decision, action='END', legs=(), reasons=(runtime.reason.upper(),))
            engine.record_decision(cid, at, decision)
            return
        if not runtime.due(at):
            return
        decision, affected = runtime.minute(inputs)
        if decision.action == 'HOLD':
            engine.record_decision(cid, at, decision)
            return
        engine.record_decision(cid, at, decision)
    if runtime.pending:
        engine.exclusions.append(dict(at=at, condition_id=cid, reason='RE1_TRANSPORT_ASSUMED',
                                      cancel_legs=list(affected),
                                      detail='instant acks and same captured book for post-signing touch'))
        planned = tuple(QuoteLeg(side, price, runtime.size) for side, price in zip(('YES', 'NO'), runtime.prices))
        if not _fits(planned, inputs.portfolio):
            runtime.finish('cash_or_cap')  # Retain the caller's counterfactual portfolio limits.
    while runtime.pending and not runtime.reason:
        intent = runtime.pending[0]
        if intent.action == 'CANCEL':
            runtime.cancel_result(at, acknowledged=True)
            runtime.cancel_open_read(at, present=False)
        else:
            # No fresh future book can be invented from minute capture. The
            # assumed snapshot is disclosed above and never used in RE-1 tests.
            if runtime.pre_submit_open_read(at, list(runtime.active)) and runtime.begin_post(inputs) is not None:
                asks = inputs.book.yes_asks if intent.leg == 0 else inputs.book.no_asks
                runtime.signed_book(min(p for p, _ in asks))
                if not runtime.reason:
                    runtime.post_result()
    if runtime.reason:
        engine.record_decision(cid, at, replace(decision, action='END', legs=(), reasons=(runtime.reason.upper(),)))
    else:
        engine.record_decision(cid, at, replace(decision, action='QUOTE', legs=runtime.legs,
                                               reasons=('BLIND_RE1_QUOTE',)))
        if runtime.next_minute is None:
            # Live run takes its first minute immediately after both posts.
            runtime.due(at)
