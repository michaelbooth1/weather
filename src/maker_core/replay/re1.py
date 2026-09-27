"""Offline RE-1 lifecycle. Emits intents only; no transport or account imports.

Source: re1_attended, re1_transport, re1_resilience and re1_sizing at
2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8. Callers supply observed acknowledgments;
a public-book counterfactual must label any assumed successful transport.
"""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal as D

from maker_core.quoting.policy import QuoteLeg, blind_re1, decide
from maker_core.quoting.prices import QuoteRefused
from maker_core.quoting.re1 import observe, replacement_price, session_caps


@dataclass(frozen=True)
class Intent:
    action: str
    leg: int
    price: D
    size: D


class Re1Session:
    """Frozen treatment, ordered cancel/read-confirm/post, and no post retry.

    This models the decision boundaries, not HTTP scheduling or cleanup IO.
    Cancellation transport retries remain read-budget inputs to the caller.
    """
    def __init__(self, legs, *, end, available=D(100), sized=True):
        if (len(legs) != 2 or tuple(v.outcome for v in legs) != ('YES', 'NO')
                or legs[0].size != legs[1].size):
            raise ValueError('RE-1 requires a frozen pair')
        self.size = legs[0].size
        self.sized = sized
        self.prices = [v.price for v in legs]
        self.order_cap, self.band_cap = session_caps(self.size, available) if sized else (D('15.8'), D('19.6'))
        self.end, self.active = end, {}
        self.submits = self.requotes = self.posts = self.acknowledged_posts = 0
        self.reason = None
        self.pending = [Intent('POST', i, self.prices[i], self.size) for i in (0, 1)]
        self.cancel_ack_at = None
        self.cancel_polls = 0
        self.next_cancel_read = None
        self.cancel_exhausted_at = None
        self.next_minute = None
        self.inflight = False
        self.awaiting_ack = False
        self.open_read_retries = 0
        self.next_open_read = None

    @property
    def legs(self):
        return tuple(self.active[i] for i in sorted(self.active))

    @property
    def unknown_submit(self):
        return self.posts != self.acknowledged_posts

    def finish(self, reason):
        if self.reason != 'fill':
            self.reason = reason
        self.pending.clear()
        self.active.clear()
        self.inflight = False
        self.awaiting_ack = False

    def fill(self):
        self.finish('fill')

    def due(self, now):
        """run(): next sample = max(previous + 60 s, current + 1 s)."""
        if self.reason or self.pending:
            return False
        if self.next_minute is not None and now < self.next_minute:
            return False
        self.next_minute = max((self.next_minute or now) + timedelta(seconds=60), now + timedelta(seconds=1))
        return True

    def minute(self, inputs):
        if self.reason or self.pending or len(self.active) != 2:
            raise ValueError('minute outside resting phase')
        decision = decide(replace(inputs, profile=blind_re1, existing=self.legs))
        affected = ()
        if decision.reasons == ('OUTSIDE_REQUOTE_WINDOW',):
            observation = observe(inputs.book, inputs.terms, tuple(self.prices), self.size)
            affected = observation.requote_legs
            if self.requotes >= 4:
                self.finish('fifth_requote')
            else:
                self.requotes += 1
                cancels = [Intent('CANCEL', i, self.prices[i], self.size) for i in affected]
                # New prices are planned together, but posted only after ALL
                # affected orders have left the open-order view.
                for i in affected:
                    self.prices[i] = replacement_price(observation.adjusted_mid, i)
                self.pending = cancels + [Intent('POST', i, self.prices[i], self.size) for i in affected]
        elif decision.action in ('END', 'CANCEL', 'NO_QUOTE'):
            self.finish('fill' if inputs.fill_seen else decision.reasons[0].lower())
        return decision, affected

    def opening_check(self, book):
        for leg, asks in enumerate((book.yes_asks, book.no_asks)):
            if not asks:
                self.finish('one_sided_book_before_post')
                return
            if self.prices[leg] >= min(p for p, _ in asks):
                self.finish('fresh_ask_before_post')
                return

    def pre_submit_open_read(self, now, listed, *, unknown_count=0):
        """Initial read plus up to ten one-second retries for missing own posts."""
        if self.reason or not self.pending or self.pending[0].action != 'POST':
            raise ValueError('open-order preflight outside post')
        if self.next_open_read is not None and now < self.next_open_read:
            raise ValueError('open-order retry outside one-second schedule')
        expected = set(self.active)
        if unknown_count or len(set(listed)) != len(listed) or not set(listed) <= expected:
            self.finish('unexpected_open_orders')
        elif set(listed) < expected and self.open_read_retries < 10:
            self.open_read_retries += 1
            self.next_open_read = now + timedelta(seconds=1)
            return False
        elif set(listed) != expected:
            self.finish('unexpected_open_orders')
        elif len(listed) >= 2 or self.pending[0].leg in expected:
            self.finish('open_order_cap')
        else:
            self.open_read_retries = 0
            self.next_open_read = None
            return True
        return False

    def begin_post(self, inputs, *, minimum_order=D(1), fee_bps=D(0)):
        """Adjacent fresh snapshot, then post-signing actual ask; one raw POST.

        Scope, exact account identities and signing bindings are outside this
        identity-free projection and must be reported as coverage limits.
        """
        if (self.reason or not self.pending or self.pending[0].action != 'POST' or self.inflight
                or self.next_open_read is not None):
            raise ValueError('post out of order or duplicate retry')
        intent = self.pending[0]
        reason = None
        if inputs.now >= self.end:
            reason = 'fixed_end'
        elif (self.end - inputs.now).total_seconds() < 180:
            reason = 'expiration_horizon'
        elif self.submits >= 10 or self.requotes > 4:
            reason = 'submit_budget'
        elif not D('.17') <= intent.price <= D('.80') or intent.price % D('.01'):
            reason = 'submit_price'
        elif (intent.price * self.size > self.order_cap or sum(self.prices) * self.size > self.band_cap
              or sum(self.prices) * self.size > 75):
            reason = 'capital_cap'
        elif not 0 <= (inputs.now - inputs.book.as_of_utc).total_seconds() <= 10:
            reason = 'fresh_book_scope'
        elif inputs.terms is None or (inputs.terms.min_size > self.size if self.sized else inputs.terms.min_size != 20) or inputs.terms.rate_per_day < 40:
            reason = 'reward_terms'
        else:
            try:
                observe(inputs.book, inputs.terms, tuple(self.prices), self.size)
            except QuoteRefused as exc:
                reason = str(exc)
        if reason is None:
            asks = inputs.book.yes_asks if intent.leg == 0 else inputs.book.no_asks
            if inputs.market.tick != D('.01') or minimum_order > self.size or fee_bps < 0:
                reason = 'market_rules'
            elif intent.price >= min(p for p, _ in asks):
                reason = 'fresh_ask'
        if reason:
            self.finish(reason)
            return None
        self.submits += 1  # Consumed before signing, even if no raw POST follows.
        self.inflight = True
        return intent

    def signed_book(self, ask):
        if not self.inflight or self.reason or self.awaiting_ack:
            raise ValueError('signed book outside submit')
        if ask is None or self.pending[0].price >= ask:
            self.finish('exception')  # OwnerVenue raises RuntimeError here.
            return
        self.posts += 1
        self.awaiting_ack = True

    def post_result(self, *, identity_present=True, ok=True, status='live', trade=False, ambiguous=False):
        if not self.inflight or not self.awaiting_ack:
            raise ValueError('no pending POST acknowledgment')
        self.inflight = False
        self.awaiting_ack = False
        if ambiguous:
            self.finish('submit_transport_ambiguous')
            return
        intent = self.pending.pop(0)
        if identity_present:
            self.acknowledged_posts += 1
            self.active[intent.leg] = QuoteLeg(('YES', 'NO')[intent.leg], intent.price, intent.size)
        if trade or status == 'matched':
            self.fill()
        elif not identity_present or ok is not True or status != 'live':
            self.finish('submit_acknowledgment')

    def cancel_result(self, now, *, acknowledged, filled=False):
        if self.reason or not self.pending or self.pending[0].action != 'CANCEL':
            raise ValueError('cancel out of order')
        if not acknowledged:
            self.finish('cancel_acknowledgment')
        elif filled:
            self.fill()
        else:
            self.cancel_ack_at, self.cancel_polls = now, 0
            self.next_cancel_read, self.cancel_exhausted_at = now, None

    def advance(self, now):
        if not self.reason and self.cancel_exhausted_at is not None and now >= self.cancel_exhausted_at:
            self.finish('cancel_not_terminal')

    def cancel_open_read(self, now, *, present, filled=False):
        if self.cancel_ack_at is None or self.reason:
            raise ValueError('cancel requires acknowledgment and order read')
        if now < self.next_cancel_read or self.cancel_exhausted_at is not None:
            raise ValueError('cancel poll outside one-second schedule')
        if filled:
            self.fill()
            return
        if present:
            self.cancel_polls += 1
            # The real loop reads ten times with one-second sleeps. The
            # scheduler supplies those reads; wall time alone is insufficient.
            self.next_cancel_read = now + timedelta(seconds=1)
            if self.cancel_polls >= 10:
                # cancel_leg sleeps after its tenth failed read before the
                # loop's else raises; do not shorten that final second.
                self.cancel_exhausted_at = self.next_cancel_read
            return
        intent = self.pending.pop(0)
        self.active.pop(intent.leg, None)
        self.cancel_ack_at = None


@dataclass
class Heartbeat:
    """Explicit-clock re1_resilience watchdog; a resync is NOT an ack."""
    started: float
    main_tick: float
    last_ack: float | None = None
    next_send: float = 0
    failure: str | None = None

    def check(self, now):
        if not self.failure:
            if now - self.main_tick >= 20:
                self.failure = 'main_loop_stalled'
            elif now - (self.started if self.last_ack is None else self.last_ack) >= 8:
                self.failure = 'heartbeat_stale'
        return self.failure

    def response(self, started, now, *, ok=False, transient=False, resynchronized=False):
        if self.check(now):
            return
        self.next_send = started + 1
        if ok:
            self.last_ack, self.next_send = now, started + 2
        elif not transient and not resynchronized:
            self.failure = 'heartbeat_acknowledgment'
