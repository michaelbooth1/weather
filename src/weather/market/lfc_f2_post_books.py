"""Optional public GET-only marks, isolated from the account/quote controller.

One daemon owns bounded scopes and writes each sample immediately. No queue,
account client, order capability, quote checkpoint or completion join is used.
An in-flight GET has a short timeout; stopping prevents subsequent reads/writes.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from threading import Event, Lock, Thread
from urllib.request import Request, urlopen

from weather.market.mm_stage2_hold import utc
from weather.market.re1_attended import GuardedJournal, SecretGuard


POST_RETIREMENT_RECORDING = True
CADENCE_SECONDS = 60
RETENTION_SECONDS = 3600
BOOK_BYTES = 2_000_000


def public_book(condition, token):
    """The recorder's only network boundary: an unauthenticated public GET."""
    if re.fullmatch(r'[0-9]{1,256}', str(token)) is None:
        raise ValueError('post_book_token')
    request = Request('https://clob.polymarket.com/book?token_id=' + token,
                      method='GET', headers={'Accept': 'application/json'})
    with urlopen(request, timeout=2) as response:
        raw = response.read(BOOK_BYTES + 1)
        if response.status != 200 or response.geturl() != request.full_url or len(raw) > BOOK_BYTES:
            raise ValueError('post_book_response')
    row = json.loads(raw)
    if (not isinstance(row, dict) or row.get('market') != condition or
            str(row.get('asset_id', row.get('token_id'))) != token):
        raise ValueError('post_book_scope')
    return row


@dataclass
class Watch:
    directory: Path
    condition: str
    tokens: tuple
    end_utc: str
    deadline: float
    until: float
    next_read: float
    trigger_at_utc: str
    trigger: str


class PostBookRecorder:
    def __init__(self, *, clock, max_bands, get=public_book, threaded=True, directory=None):
        if not 1 <= max_bands <= 12:
            raise ValueError('post_book_band_limit')
        self.clock, self.max_bands, self.get = clock, max_bands, get
        self.threaded = threaded
        self.directory = Path(directory) if directory is not None else None
        self.diagnostics, self.failure = None, None
        self.watches, self.journals = {}, {}
        self.stopped, self.wake, self.lock = Event(), Event(), Lock()
        self.thread = None

    def watch(self, band, trigger):
        if not POST_RETIREMENT_RECORDING or self.stopped.is_set():
            return
        now = self.clock.monotonic()
        if now >= band.deadline or utc(self.clock.now()) >= band.end:
            return
        key = str(band.directory)
        with self.lock:
            old = self.watches.get(key)
            if old is None and len(self.watches) >= self.max_bands:
                raise ValueError('post_book_band_limit')
            self.watches[key] = Watch(Path(band.directory), band.condition, tuple(band.tokens),
                utc(band.end).isoformat(), band.deadline, min(band.deadline, now + RETENTION_SECONDS),
                old.next_read if old is not None and now < old.until else now,
                utc(self.clock.now()).isoformat(), trigger)
        self.wake.set()

    def start(self):
        if self.threaded and self.thread is None:
            self.thread = Thread(target=self.run, name='lfc-public-post-books', daemon=True)
            self.thread.start()

    def stop(self):
        # Never wait for network/disk from the account's teardown path.
        self.stopped.set()
        self.wake.set()

    def live(self, key):
        with self.lock:
            watch = self.watches[key]
            return (not self.stopped.is_set() and self.clock.monotonic() < min(watch.until, watch.deadline)
                    and utc(self.clock.now()) < utc(watch.end_utc))

    def record_failure(self, exc):
        # The optional worker never acquires an account/heartbeat journal lock.
        # Its independent diagnostic also leaves a bounded terminal status if
        # the filesystem cannot retain either optional file.
        self.failure = {'exception_type': type(exc).__name__,
                        'collected_at_utc': utc(self.clock.now()).isoformat()}
        if self.directory is None or self.stopped.is_set():
            return
        try:
            if self.diagnostics is None:
                self.diagnostics = GuardedJournal(self.directory / 'post_books_errors.jsonl',
                    clock=self.clock.now, scope={'public_get_only': True}, mode='live', guard=SecretGuard())
            self.diagnostics.record('post_book_recording_unavailable', **self.failure)
        except Exception:
            self.failure = {**self.failure, 'diagnostic_write_failed': True}

    def step(self):
        if self.stopped.is_set():
            return
        now = self.clock.monotonic()
        with self.lock:
            due = [(key, watch) for key, watch in self.watches.items()
                   if watch.next_read <= now < min(watch.until, watch.deadline)]
            for _, watch in due:
                watch.next_read = now + CADENCE_SECONDS
        for key, watch in due:
            for leg, token in enumerate(watch.tokens):
                if not self.live(key):
                    return
                began = utc(self.clock.now()).isoformat()
                fields = {'leg': leg, 'token_id': token, 'collection_started_at_utc': began}
                try:
                    fields['book'] = self.get(watch.condition, token)
                    fields['ok'] = True
                except Exception as exc:
                    fields.update(ok=False, exception_type=type(exc).__name__)
                fields['collected_at_utc'] = utc(self.clock.now()).isoformat()
                if not self.live(key):
                    return
                try:
                    if key not in self.journals:
                        self.journals[key] = GuardedJournal(watch.directory / 'post_books.jsonl',
                            clock=self.clock.now, scope={'condition_id': watch.condition,
                            'token_ids': list(watch.tokens), 'public_get_only': True},
                            mode='live', guard=SecretGuard())
                    self.journals[key].record('post_book', trigger=watch.trigger,
                        trigger_at_utc=watch.trigger_at_utc, **fields)
                except Exception as exc:
                    if not self.stopped.is_set():
                        self.record_failure(exc)

    def run(self):
        try:
            while not self.stopped.is_set():
                self.wake.clear()
                self.step()
                self.wake.wait(1)
        except Exception as exc:
            if not self.stopped.is_set():
                self.record_failure(exc)
        finally:
            for journal in list(self.journals.values()) + ([self.diagnostics] if self.diagnostics is not None else []):
                try:
                    journal.close()
                except Exception:
                    pass
