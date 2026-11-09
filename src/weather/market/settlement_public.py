"""Bounded public GETs for settlement diagnostics: AWC, Gamma event bins and HKO."""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from weather.market.metar_reports import aware_utc, parse_metar_text

AWC_URL = "https://aviationweather.gov/api/data/metar"
GAMMA_URL = "https://gamma-api.polymarket.com/events"
HKO_URL = "https://www.weather.gov.hk/cis/dailyExtract/dailyExtract_{year:04d}{month:02d}.xml"


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OSError("public reader refused redirect")


def public_json_or_text(url: str) -> str:
    parsed = urlparse(url)
    allowed = ((parsed.hostname, parsed.path) in {
        ("aviationweather.gov", "/api/data/metar"), ("gamma-api.polymarket.com", "/events")
    } or (parsed.hostname == "www.weather.gov.hk" and re.fullmatch(
        r"/cis/dailyExtract/dailyExtract_\d{6}\.xml", parsed.path)))
    if parsed.scheme != "https" or parsed.username or parsed.password or not allowed:
        raise ValueError("URL is outside public settlement GET allowlist")
    request = Request(url, headers={"User-Agent": "weather-settlement-diagnostic/1.0"}, method="GET")
    with build_opener(NoRedirects).open(request, timeout=20) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise OSError("public response exceeds 2 MiB")
    return payload.decode("utf-8-sig")


class PublicSettlementClient:
    """One serial client; spaces AWC calls by at least one second, including retries.

    Five 2/hour stations x 30 h ~300 reports. Near-cap responses are discarded
    and split, first by stations then by time; saturation can never silently
    masquerade as a complete fetch. HTTP errors stop the AWC run, including 429.
    """

    def __init__(self, get=public_json_or_text, *, clock=time.monotonic, sleep=time.sleep):
        self.get, self.clock, self.sleep = get, clock, sleep
        self.last_by_host = {}
        self.consecutive_429 = Counter()

    def request(self, url):
        """Pace every GET per host; a third consecutive 429 disables that host."""
        host = urlparse(url).hostname
        if self.consecutive_429[host] >= 3:
            raise OSError(f"stopped {host} after 3 consecutive HTTP 429s")
        previous = self.last_by_host.get(host)
        if previous is not None:
            delay = 1.0 - (self.clock() - previous)
            if delay > 0:
                self.sleep(delay)
        self.last_by_host[host] = self.clock()
        try:
            result = self.get(url)
        except HTTPError as exc:
            self.consecutive_429[host] = self.consecutive_429[host] + 1 if exc.code == 429 else 0
            raise
        self.consecutive_429[host] = 0
        return result

    def metars(self, station_ids, end: datetime):
        end = aware_utc(end).replace(microsecond=0)
        stations = sorted(set(station_ids))
        if any(len(s) != 4 or not s.isalpha() or s != s.upper() for s in stations):
            raise ValueError("invalid AWC station id")
        reports, flags, errors = [], Counter(), []
        requests = 0

        def fetch(batch, start, stop):
            nonlocal requests
            requests += 1
            hours = max(1, math.ceil((stop - start).total_seconds() / 3600))
            query = urlencode(dict(ids=",".join(batch), format="raw", hours=hours,
                                   date=stop.strftime("%Y-%m-%dT%H:%M:%SZ")))
            raw = self.request(AWC_URL + "?" + query)
            lines = [line for line in raw.splitlines() if line.strip()]
            if len(lines) >= 390:
                if len(batch) > 1:
                    mid = len(batch) // 2
                    fetch(batch[:mid], start, stop)
                    fetch(batch[mid:], start, stop)
                elif stop - start > timedelta(minutes=30):
                    mid = start + (stop - start) / 2
                    fetch(batch, start, mid)
                    fetch(batch, mid, stop)
                else:
                    raise OSError(f"AWC response saturated for {batch[0]} after bounded splitting")
                return
            parsed, counts = parse_metar_text(raw, stop - timedelta(hours=hours), stop)
            flags.update(counts)
            reports.extend(r for r in parsed if r.station in batch and (
                r.observation_time is None or start <= r.observation_time <= stop))

        try:
            for offset in range(0, len(stations), 5):
                fetch(stations[offset:offset + 5], end - timedelta(hours=30), end)
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
        # A snapshot is not an ordered revision tape: distinct rows sharing an
        # observation key are ambiguous, rather than last-row-wins (AWC is newest-first).
        unique = list(dict.fromkeys(reports))
        variants = {}
        for report in unique:
            variants.setdefault((report.station, report.observation_time), set()).add(report.raw)
        ambiguous = {key for key, raws in variants.items() if key[1] is not None and len(raws) > 1}
        if ambiguous:
            unique = [replace(r, flags=r.flags + ("ambiguous_source_revision",))
                      if (r.station, r.observation_time) in ambiguous else r for r in unique]
            flags["ambiguous_source_revision"] += len(ambiguous)
            errors.append("AWC snapshot contains conflicting observation revisions")
        return unique, dict(request_count=requests, parse_flags=dict(flags), errors=errors)

    def event_bins(self, event_slug: str) -> list[str]:
        payload = json.loads(self.request(GAMMA_URL + "?" + urlencode({"slug": event_slug})))
        if not isinstance(payload, list):
            raise ValueError("invalid public event payload")
        events = [event for event in payload if event.get("slug") == event_slug]
        if not events:
            return []
        if len(events) != 1:
            raise ValueError("ambiguous public event")
        # Only bin labels are consumed. Never inspect prices, tokens or orders.
        labels = [market.get("groupItemTitle") for market in events[0].get("markets", [])]
        if not labels or any(not isinstance(label, str) or not label for label in labels):
            raise ValueError("missing public bin labels")
        if len(labels) != len(set(labels)):
            raise ValueError("duplicate public bin labels")
        return labels

    def hko_payloads(self, day):
        from weather.market.hko_settlement import DailyExtractSnapshot, parse_daily_extract
        # The official .xml-named endpoint serves a JSON stn/data/dayData document.
        try:
            raw = self.request(HKO_URL.format(year=day.year, month=day.month))
        except HTTPError as exc:
            if exc.code != 404:
                raise
            return DailyExtractSnapshot(day.year, day.month, {})
        return parse_daily_extract(raw, day.year, day.month)
