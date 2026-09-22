"""Public-only RE-1 capacity research. No account, credential, or order imports.

Run ``python -m weather.market.reward_capacity --help``. Raw responses and
derived samples stay in this worktree's ignored data/reward_capacity directory.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from weather.market.exchange_economics_sources import MAX_RESPONSE_BYTES, json_response_payload, response_evidence, current_reward_page
from weather.market.market_registry import REGISTRY
from weather.market.mm_stage2_public import canonical_bytes, utc
from weather.market.mm_stage2_selection import capacity_quote, select_table, selection_rank
from weather.market.re1_rehearsal import Re1PublicBooks
from weather.market.reward_share_estimate import share_of
from weather.operations.live_path_security import assert_no_ambient_proxy_configuration
from weather.paths import data_path, config_path

SIZES = (20, 50, 100, 200)
ET = ZoneInfo('America/Toronto')
ROOT = data_path('reward_capacity')
USER_AGENT = 'weather-reward-capacity-research/1.0 (public-only; 1 request/sec)'


class SamplerStopped(RuntimeError):
    pass


def append(path, value):
    with Path(path).open('ab') as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def network_lease():
    """The same OS mutex RE-1 live holds; no campaign files or live imports."""
    if os.name != 'nt':
        raise SamplerStopped('sampling_requires_windows_workstation')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, 'Global\\WeatherProjectHeavyWorkloadV1')
    if not handle:
        raise SamplerStopped('host_mutex_unavailable')
    owned = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        owned = result in (0, 0x80)
        if result != 0:
            raise SamplerStopped('live_or_heavy_mutex_busy_or_abandoned')
        if (Path(os.environ.get('ProgramData', 'C:/ProgramData')) / 'WeatherProject/heavy_workload_v1.poison').exists():
            raise SamplerStopped('host_workload_recovery_required')
        yield
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CapturedResponse(io.BytesIO):
    def __init__(self, body, status, headers, url):
        super().__init__(body)
        self.status, self.headers, self.url = status, headers, url

    def geturl(self):
        return self.url


class PublicTransport:
    """One serial, allowlisted GET path for discovery and canonical book reads."""
    def __init__(self, directory, deadline, *, lease=network_lease, clock=None,
                 monotonic=time.monotonic, sleep=time.sleep, opener=None):
        self.directory, self.deadline, self.lease = Path(directory), utc(deadline), lease
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic, self.sleep = monotonic, sleep
        self.next_request = 0.0
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect()).open
        self.responses = 0

    def checkpoint(self):
        if utc(self.clock()) >= self.deadline - timedelta(seconds=10):
            raise SamplerStopped('deadline')
        if (self.directory.parent / 'STOP').exists():
            raise SamplerStopped('owner_stop')

    def wait(self, seconds):
        until = self.monotonic() + seconds
        while self.monotonic() < until:
            self.checkpoint()
            with self.lease():
                pass
            self.sleep(min(1, until - self.monotonic()))

    def __call__(self, request, *, timeout=2):
        url = request.full_url
        parts = urlsplit(url)
        allowed = (parts.netloc == 'gamma-api.polymarket.com' and
                   (parts.path in {'/events', '/tags/slug/weather'} or parts.path.startswith('/events/slug/')))
        allowed |= (parts.netloc == 'clob.polymarket.com' and
                    (parts.path in {'/book', '/fee-rate', '/rewards/markets/current'} or
                     re.fullmatch(r'/rewards/markets/0x[0-9a-f]{64}', parts.path) is not None))
        if (not allowed or parts.scheme != 'https' or parts.fragment or parts.username or parts.password
                or request.get_method() != 'GET' or request.data is not None):
            raise ValueError('nonpublic_request_refused')
        assert_no_ambient_proxy_configuration()
        self.wait(max(0, self.next_request - self.monotonic()))
        self.checkpoint()
        with self.lease():
            self.checkpoint()
            self.next_request = self.monotonic() + 1
            started = utc(self.clock()).isoformat()
            response = None
            try:
                try:
                    response = self.opener(Request(url, headers={'Accept': 'application/json', 'User-Agent': USER_AGENT}), timeout=2)
                except HTTPError as exc:
                    response = exc
                body = response.read(MAX_RESPONSE_BYTES + 1)
                status, headers, final_url = response.status, dict(response.headers), response.geturl()
                if len(body) > MAX_RESPONSE_BYTES:
                    record = {'url': url, 'http_status': status, 'truncated': True,
                              'response_body_base64': base64.b64encode(body).decode('ascii'),
                              'response_sha256': hashlib.sha256(body).hexdigest()}
                else:
                    record = response_evidence(body, url=url, http_status=status,
                        content_type=response.headers.get('Content-Type', ''), origin='http_response_bytes')
                record.update(retrieved_at_utc=utc(self.clock()).isoformat(), requested_at_utc=started,
                              sequence=self.responses, final_url=final_url)
                append(self.directory / 'responses.jsonl', record)
                self.responses += 1
                if status != 200 or final_url != url or len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(f'public_http_status_{status}_or_size_redirect')
                return CapturedResponse(body, status, headers, final_url)
            except Exception as exc:
                append(self.directory / 'errors.jsonl', {'at_utc': utc(self.clock()).isoformat(),
                       'url': url, 'failure_type': type(exc).__name__, 'detail': str(exc)[:300]})
                raise
            finally:
                if response is not None:
                    response.close()

    def discovery(self, url):
        with self(Request(url)) as response:
            if not response.headers.get('Content-Type', '').lower().startswith('application/json'):
                raise ValueError('discovery_not_json')
            return json_response_payload(response.read())


def event_identity(event, now):
    """Venue's dated weather slug; unconfigured cities use ET date explicitly."""
    slug = event.get('slug', '')
    match = re.search(r'-([a-z]+)-(\d{1,2})-(\d{4})$', slug)
    if not match:
        return None
    try:
        target = datetime.strptime('-'.join(match.groups()), '%B-%d-%Y').date()
    except ValueError:
        return None
    market = next((key for key, spec in REGISTRY.items() if slug.startswith(spec.slug_prefix + '-')), None)
    zone = REGISTRY[market].timezone if market else 'America/Toronto'
    today = utc(now).astimezone(ZoneInfo(zone)).date()
    if target not in (today, today + timedelta(days=1)):
        return None
    return {'market_id': market or slug[:match.start()], 'configured_market': market is not None,
            'market_timezone': zone, 'target_date': target.isoformat(),
            'horizon': (target - today).days, 'event_slug': slug,
            'date_basis': 'market_local' if market else 'ET_unconfigured_city'}


def discover(transport):
    tag = transport.discovery('https://gamma-api.polymarket.com/tags/slug/weather')
    if tag.get('slug') != 'weather' or not str(tag.get('id', '')).isdigit():
        raise ValueError('weather_tag_identity')
    seen, events = set(), []
    for offset in range(0, 5000, 5):
        page = transport.discovery('https://gamma-api.polymarket.com/events?' + urlencode({
            'tag_id': tag['id'], 'closed': 'false', 'limit': 5, 'offset': offset,
            'order': 'id', 'ascending': 'true'}))
        if not isinstance(page, list) or len(page) > 5:
            raise ValueError('weather_event_page_shape')
        for event in page:
            if event['id'] in seen:
                raise ValueError('weather_event_pagination_duplicate')
            seen.add(event['id'])
            identity = event_identity(event, transport.clock())
            if identity:
                if not isinstance(event.get('markets'), list):
                    raise ValueError('weather_event_missing_bands')
                events.append((identity, event))
        if len(page) < 5:
            return events
    raise ValueError('weather_event_pagination_bound')


def rewarded_conditions(transport):
    seen, cursors, cursor = set(), set(), None
    for _ in range(100):
        query = {'limit': 500}
        if cursor:
            query['next_cursor'] = cursor
        page = transport.discovery('https://clob.polymarket.com/rewards/markets/current?' + urlencode(query))
        _, cursor = current_reward_page(page, page_limit=500, seen_conditions=seen)
        if cursor == 'LTE=':
            return seen
        if cursor in cursors:
            raise ValueError('rewards_cursor_repeated')
        cursors.add(cursor)
    raise ValueError('rewards_pagination_bound')


def model_band(band):
    """Same quote gates; same-day/unconfigured rows are research, never RE-1 selection."""
    rows = []
    for size in SIZES:
        row = {key: value for key, value in band.items() if key != 'snapshot'}
        row.update(size=size, eligible=False, modelled=True, predicted_360_minutes=None)
        try:
            quote = capacity_quote(band['snapshot'], size=size, now=band['snapshot']['observed_at_utc'])
            predicted = quote.predicted_per_minute_many * 360
            row.update(quote=asdict(quote), predicted_360_minutes=predicted,
                       capital_pusd=float(quote.reserve_pusd),
                       worst_case_one_fill_loss_pusd=float(size * max(quote.yes_buy, quote.no_buy)),
                       gross_cash_at_risk_pusd=float(quote.reserve_pusd),
                       eligible=predicted >= 2, refusal=None if predicted >= 2 else 'predicted_below_two',
                       share_with_one_equal_competitor=share_of(quote.own_q_min, quote.competing_q_many + quote.own_q_min),
                       share_with_three_equal_competitors=share_of(quote.own_q_min, quote.competing_q_many + 3 * quote.own_q_min))
        except (ValueError, RuntimeError, KeyError, TypeError) as exc:
            row['refusal'] = str(exc)
        rows.append(row)
    return rows


def sample(transport, *, interval_minutes=15, configured_only=False):
    started = utc(transport.clock())
    response_start = transport.responses
    reader = Re1PublicBooks(clock=transport.clock, opener=transport)
    result = {'started_at_utc': started.isoformat(), 'modelled': True,
              'complete': True, 'rows': [], 'band_errors': [], 'unrewarded_conditions': [],
              'interval_seconds': interval_minutes * 60,
              'scope': 'configured_only' if configured_only else 'all_venue_dated_weather'}
    events = discover(transport)
    rewards = rewarded_conditions(transport)
    if configured_only:
        events = [(identity, event) for identity, event in events if identity['configured_market']]
    expected_bands = sum(market.get('conditionId') in rewards for _, event in events for market in event['markets'])
    minimum_seconds = 5 * expected_bands + transport.responses - response_start
    if minimum_seconds > interval_minutes * 60:
        append(transport.directory / 'cadence_refusals.jsonl', {
            'at_utc': utc(transport.clock()).isoformat(), 'reward_bands': expected_bands,
            'minimum_seconds': minimum_seconds, 'requested_interval_minutes': interval_minutes})
        raise SamplerStopped('complete_universe_cannot_fit_requested_cadence')
    result['events'] = [identity for identity, _ in events]
    seen, re1 = set(), []
    for identity, event in events:
        for market in event['markets']:
            transport.checkpoint()
            condition = market.get('conditionId')
            if condition in seen:
                raise ValueError('duplicate_weather_condition')
            seen.add(condition)
            if condition not in rewards:
                result['unrewarded_conditions'].append(condition)
                continue
            try:
                reward = reader.reward(condition, checkpoint=transport.checkpoint)
                if reward is None:
                    result['unrewarded_conditions'].append(condition)
                    continue
                tokens, outcomes = market['clobTokenIds'], market['outcomes']
                tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
                outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                if outcomes != ['Yes', 'No'] or len(tokens) != 2 or len(set(tokens)) != 2:
                    raise ValueError('weather_yes_no_pair')
                snapshot = reader.snapshot(condition, tokens, reward=reward, checkpoint=transport.checkpoint)
                band = dict(identity, condition_id=condition, token_ids=tokens, snapshot=snapshot,
                            sample_started_at_utc=started.isoformat())
                append(transport.directory / 'snapshots.jsonl', band)
                result['rows'].extend(model_band(band))
                # Run the canonical UTC-tomorrow table on exactly its admitted domain.
                if identity['configured_market'] and identity['target_date'] == (started.date() + timedelta(days=1)).isoformat():
                    re1.append(band)
            except SamplerStopped:
                raise
            except (ValueError, RuntimeError, KeyError, TypeError, OSError) as exc:
                result['complete'] = False
                result['band_errors'].append({'condition_id': condition, 'failure': str(exc)[:300]})
            finally:
                reader.records.clear()  # Bodies are already durably journalled; bound memory.
    finished = utc(transport.clock())
    result['finished_at_utc'] = finished.isoformat()
    result['duration_seconds'] = (finished - started).total_seconds()
    result['re1_selection'] = select_table(re1, now=finished, complete=result['complete'])
    result['condition_count'] = len(seen)
    result['response_count'] = transport.responses - response_start
    append(transport.directory / 'samples.jsonl', result)
    return result


def run(deadline, *, once=False, interval_minutes=15, configured_only=False):
    deadline = utc(deadline)
    now = datetime.now(timezone.utc)
    if now >= deadline or deadline > now + timedelta(hours=18):
        raise ValueError('deadline_must_be_future_and_within_18_hours')
    local = now.astimezone(ET)
    hard_stop = datetime(2026, 9, 22, 19, 45, tzinfo=ET)
    if local.date() == hard_stop.date() and deadline > hard_stop:
        raise ValueError('September_22_deadline_cannot_exceed_1945_ET')
    from weather.execution_host import current_execution_host_id, current_execution_principal_id
    assignment = json.loads(config_path('international_live_execution_host.json').read_bytes())
    host = current_execution_host_id()
    if (assignment['assignment_status'] != 'ASSIGNED'
            or host != assignment['active_portable_execution_host_id']
            or host == assignment['dedicated_capture_execution_host_id']
            or current_execution_principal_id() != assignment['active_portable_execution_principal_id']):
        raise SamplerStopped('wrong_workstation_or_principal')
    ROOT.mkdir(parents=True, exist_ok=True)
    # A stale marker requires inspection, never automatic restart after a crash.
    lock = ROOT / 'sampler.lock'
    with lock.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps({'pid': os.getpid(), 'started_at_utc': now.isoformat(),
                                 'deadline_utc': deadline.isoformat()}))
    directory = ROOT / now.strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir()
    transport = PublicTransport(directory, deadline)
    # An OS process exit is a last-resort bound on a stuck socket read. Normal
    # shutdown occurs ten seconds earlier and releases the request mutex cleanly.
    watchdog = threading.Timer(max(0, (deadline - now).total_seconds() - 1), lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    append(directory / 'lifecycle.jsonl', {'event': 'started', 'at_utc': now.isoformat(),
           'deadline_utc': deadline.isoformat(), 'pid': os.getpid(), 'modelled_only': True})
    terminal_reason, exit_code = 'one_cycle_complete', 0
    try:
        while True:
            tick = time.monotonic()
            try:
                result = sample(transport, interval_minutes=interval_minutes, configured_only=configured_only)
                print(json.dumps({'directory': str(directory), 'complete': result['complete'],
                      'conditions': result['condition_count'], 'rows': len(result['rows']),
                      'duration_seconds': result['duration_seconds']}), flush=True)
            except SamplerStopped:
                raise
            except Exception as exc:
                terminal_reason, exit_code = 'cycle_failed', 2
                append(directory / 'cycle_errors.jsonl', {'at_utc': datetime.now(timezone.utc).isoformat(),
                       'failure_type': type(exc).__name__, 'detail': str(exc)[:300]})
                print(json.dumps({'cycle_failed': type(exc).__name__, 'detail': str(exc)[:300]}), flush=True)
            if once:
                break
            transport.wait(max(0, interval_minutes * 60 - (time.monotonic() - tick)))
    except SamplerStopped as exc:
        terminal_reason = str(exc)
        exit_code = 0 if terminal_reason in {'deadline', 'owner_stop'} else 2
        print(json.dumps({'stopped': str(exc)}), flush=True)
    finally:
        append(directory / 'lifecycle.jsonl', {'event': 'stopped', 'at_utc': datetime.now(timezone.utc).isoformat(),
               'pid': os.getpid(), 'responses': transport.responses,
               'reason': terminal_reason, 'exit_code': exit_code})
        watchdog.cancel()
        lock.unlink()
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--until', required=True, help='Mandatory timezone-aware stop time; max 18 hours.')
    parser.add_argument('--once', action='store_true', help='One discovery/books cycle, then exit.')
    parser.add_argument('--interval-minutes', type=int, choices=(15, 30), default=15,
                        help='Default 15. A 30-minute override needs an explicit mission amendment.')
    parser.add_argument('--configured-only', action='store_true',
                        help='Scope override; requires an explicit mission amendment.')
    args = parser.parse_args(argv)
    return run(args.until, once=args.once, interval_minutes=args.interval_minutes, configured_only=args.configured_only)


if __name__ == '__main__':
    raise SystemExit(main())
