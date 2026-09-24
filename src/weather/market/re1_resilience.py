"""RE-1M read freshness and an independent, dead-main-loop heartbeat watchdog."""
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from importlib.util import find_spec

from weather.market.mm_stage2_hold import HoldEnd


def transient(exc):
    """Retry transport failures only; malformed safety facts still fail closed."""
    import httpx
    if find_spec('polymarket') is not None:
        from polymarket.errors import TransportError, RateLimitError, TimeoutError as SdkTimeout
        sdk_errors = (TransportError, RateLimitError, SdkTimeout)
    else:
        sdk_errors = ()
    if isinstance(exc, HTTPError):
        return exc.code in (408, 429) or exc.code >= 500
    if isinstance(exc, (TimeoutError, ConnectionError, URLError, httpx.TransportError) + sdk_errors):
        return True
    status = getattr(exc, 'status_code', getattr(exc, 'status', None))
    if isinstance(status, int):
        return status in (408, 429) or status >= 500
    return exc.__cause__ is not None and transient(exc.__cause__)


class Freshness:
    def __init__(self, clock, journal):
        self.clock, self.journal = clock, journal
        self.started = clock.monotonic()
        self.success, self.next_read = {}, {}

    def check(self, name, budget, *, initial=None):
        since = self.success.get(name, self.started if initial is None else initial)
        if self.clock.monotonic() - since >= budget:
            raise HoldEnd(name + '_stale')

    def read(self, name, fn, *, cadence, budget, force=False, initial=None):
        self.check(name, budget, initial=initial)
        now = self.clock.monotonic()
        if not force and now < self.next_read.get(name, float('-inf')):
            return None
        try:
            value = fn()
        except Exception as exc:
            if not transient(exc):
                raise
            self.journal.record('read_unavailable', fact=name, exception_type=type(exc).__name__)
            self.next_read[name] = self.clock.monotonic() + 1
            self.check(name, budget, initial=initial)
            return None
        self.check(name, budget, initial=initial)
        self.success[name] = self.clock.monotonic()
        self.next_read[name] = self.clock.monotonic() + cadence
        return value


def retry_read(name, fn, *, clock, journal, budget=30, checkpoint=lambda: None):
    until = clock.monotonic() + budget
    while True:
        try:
            result = fn()
            if clock.monotonic() >= until:
                raise HoldEnd(name + '_stale')
            return result
        except Exception as exc:
            if not transient(exc):
                raise
            journal.record('read_unavailable', fact=name, exception_type=type(exc).__name__)
            if clock.monotonic() >= until:
                raise HoldEnd(name + '_stale') from None
            checkpoint()
            clock.sleep(min(1, until - clock.monotonic()))


class HeartbeatLoop:
    """Only this worker sends heartbeats. Replay pumps the same step explicitly."""
    def __init__(self, clock, send, journal, *, threaded):
        self.clock, self.send, self.journal = clock, send, journal
        self.threaded = threaded
        self.main_tick = self.started = clock.monotonic()
        self.last_ack, self.next_send = None, self.started
        self.failure = None
        self.stopped = Event()
        self.thread = None

    def tick(self):
        self.main_tick = self.clock.monotonic()

    def step(self):
        now = self.clock.monotonic()
        if self.stopped.is_set() or self.failure:
            return
        if now - self.main_tick >= 20:
            self.failure = 'main_loop_stalled'
            self.stopped.set()
            return
        if now - (self.last_ack if self.last_ack is not None else self.started) >= 8:
            self.failure = 'heartbeat_stale'
            self.stopped.set()
            return
        if now < self.next_send:
            return
        self.next_send = now + 1
        try:
            self.journal.record('heartbeat_request')
            result = self.send()
            self.journal.record('heartbeat_response', response=result)
            if result != {'status': 'ok'}:
                self.failure = 'heartbeat_acknowledgment'
                return
            # A late response cannot revive a stale lease or hung main loop.
            at = self.clock.monotonic()
            if at - self.main_tick >= 20:
                self.failure = 'main_loop_stalled'
            elif at - (self.last_ack if self.last_ack is not None else self.started) >= 8:
                self.failure = 'heartbeat_stale'
            else:
                # Every 2 s (was 5): one hung request can be retried inside the 8 s stale limit (session 5, 09-24).
                self.last_ack, self.next_send = at, now + 2
        except Exception as exc:
            if not transient(exc):
                self.failure = 'heartbeat_failed'
            try:
                self.journal.record('heartbeat_unavailable', exception_type=type(exc).__name__)
            except BaseException:
                self.failure = 'heartbeat_journal_failed'

    def start(self):
        if self.threaded:
            def worker():
                while not self.stopped.is_set():
                    self.step()
                    self.stopped.wait(.1)
            self.thread = Thread(target=worker, name='re1-heartbeat', daemon=True)
            self.thread.start()
        else:
            self.step()

    def check(self):
        if not self.threaded:
            self.step()
        if self.failure:
            raise HoldEnd(self.failure)
        if self.clock.monotonic() - (self.last_ack if self.last_ack is not None else self.started) >= 8:
            raise HoldEnd('heartbeat_stale')

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise RuntimeError('heartbeat_thread_not_stopped')
