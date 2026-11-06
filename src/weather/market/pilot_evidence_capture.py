"""Latched all-band universe, raw market stream and fair REST reconciliation."""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from weather.market.market_registry import BUILTIN_SPECS
from weather.market.pilot_evidence_public import CLOB, GAMMA, CONDITION, open_socket
from weather.market.pilot_evidence_store import CaptureStopped, MIB, stamp


def event_slug(spec, day):
    months = ("january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december")
    return f"{spec.slug_prefix}-{months[day.month - 1]}-{day.day}-{day.year}"


def event_bands(event, spec, day):
    slug = event_slug(spec, day)
    if not isinstance(event, dict) or event.get("slug") != slug or not event.get("markets"):
        raise ValueError("event identity or bands missing")
    result = []
    for market in event["markets"]:
        cid = market.get("conditionId", "")
        tokens, outcomes = market.get("clobTokenIds"), market.get("outcomes")
        tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        if (not re.fullmatch(CONDITION, cid) or not isinstance(tokens, list) or len(tokens) != 2 or
                len(set(tokens)) != 2 or not all(isinstance(t, str) and t.isdecimal() for t in tokens) or
                not isinstance(outcomes, list) or sorted(str(o).lower() for o in outcomes) != ["no", "yes"]):
            raise ValueError("condition/token/outcome binding missing")
        result.append({"condition_id": cid, "token_ids": tokens, "outcomes": outcomes,
                       "market": spec.id, "event_date": day.isoformat(), "event_slug": slug,
                       "unit": spec.display_unit, "question": market.get("question"),
                       "gamma_market_id": market.get("id")})
    return result


class MarketStream(threading.Thread):
    """Independent receiving thread; no queue drops or semantic deduplication."""

    def __init__(self, store, gate, tokens, *, connect=open_socket, max_age=30, max_delay=30):
        super().__init__(name="pilot-public-market", daemon=False)
        self.store, self.gate, self.tokens, self.connect = store, gate, tokens, connect
        self.max_age, self.max_delay = max_age, max_delay
        self.ending = threading.Event()
        self.pending = set()
        self.gap_open = False

    def disconnected(self, reason):
        if not self.gap_open:
            self.store.gap("stream_gap_start", reason=reason)
            self.gap_open = True

    def frame(self, opcode, raw, received):
        if len(raw) > MIB:
            self.store.fail("socket_frame_cap", bytes=len(raw))
            raise CaptureStopped("socket_frame_cap")
        value = self.store.raw("ws_frame", raw, received=received, opcode=opcode)
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = row.get("timestamp")
            if source is not None:
                try:
                    age = datetime.fromisoformat(received["receipt_utc"]).timestamp() - float(source) / 1000
                    if age > self.max_delay or age < -self.max_delay:
                        self.store.gap("stream_source_delay", seconds=age)
                except (ValueError, TypeError, OverflowError):
                    self.store.gap("stream_source_clock_unreadable")
            if row.get("event_type") == "book":
                self.pending.discard(str(row.get("asset_id")))
        if self.gap_open and not self.pending and value is not None:
            self.store.write("stream_gap_end", {"basis": "all_subscribed_book_frames_received",
                                                "backfilled": False})
            self.gap_open = False

    def run(self):
        failures = 0
        while not self.ending.is_set() and not self.store.stop.is_set():
            ws = None
            try:
                tokens = self.tokens()
                if not tokens:
                    self.ending.wait(0.2)
                    continue
                self.disconnected("initial_or_reconnect")
                self.gate.wait()  # Even handshakes share the no-burst budget.
                ws = self.connect()
                self.store.write("stream_connected", {"token_count": len(tokens)})
                self.pending = set(tokens)
                ws.send(json.dumps({"assets_ids": tokens, "type": "market",
                                    "custom_feature_enabled": True}))
                self.store.write("subscription", {"tokens": tokens})
                subscribed, last_receive, last_ping = set(tokens), time.monotonic(), 0.0
                baseline_due = last_receive + self.max_age
                while not self.ending.is_set():
                    self.store.check()
                    now = time.monotonic()
                    additions = set(self.tokens()) - subscribed
                    if additions:
                        ws.send(json.dumps({"assets_ids": sorted(additions), "operation": "subscribe"}))
                        subscribed.update(additions)
                        self.pending.update(additions)
                        baseline_due = now + self.max_age
                        self.disconnected("new_tokens_awaiting_baseline")
                        self.store.write("subscription", {"tokens": sorted(additions), "additive": True})
                    if now - last_ping >= 10:
                        ws.send("PING")
                        last_ping = now
                    if now - last_receive > self.max_age:
                        raise TimeoutError("stream silence")
                    if self.pending and now > baseline_due:
                        raise TimeoutError("stream baseline missing")
                    try:
                        frame = ws.recv_frame()
                    except TimeoutError:
                        continue
                    except Exception as exc:
                        if type(exc).__name__ == "WebSocketTimeoutException":
                            continue
                        raise
                    received = stamp()
                    raw = frame.data.encode() if isinstance(frame.data, str) else frame.data
                    self.frame(frame.opcode, raw, received)
                    last_receive = time.monotonic()
                    failures = 0
                    if frame.opcode == 9:
                        ws.pong(raw)
                    if frame.opcode == 8:
                        raise ConnectionError("peer close")
            except CaptureStopped:
                break
            except Exception as exc:
                if self.ending.is_set():
                    break
                self.disconnected(type(exc).__name__)
                failures += 1
                delay = min(60, 2 ** min(failures, 6))
                self.store.write("stream_reconnect", {"error": type(exc).__name__, "backoff_seconds": delay})
                self.ending.wait(delay)
            finally:
                if ws is not None:
                    ws.close(timeout=1)


@dataclass
class Job:
    key: str
    interval: float
    action: object
    due: float = 0.0


class PublicCapture:
    def __init__(self, args, store, http):
        self.args, self.store, self.http = args, store, http
        self.bands, self.baselined, self.jobs = {}, set(), {}
        self.lock = threading.Lock()
        self.stream = MarketStream(store, http.gate, self.tokens, max_age=args.max_age_seconds,
                                   max_delay=args.max_mark_delay_seconds)

    def tokens(self):
        with self.lock:
            return sorted({t for band in self.bands.values() for t in band["token_ids"]})

    def add_job(self, key, interval, action):
        if key not in self.jobs:
            self.jobs[key] = Job(key, interval, action)

    def discover(self, spec, day):
        event = self.http.read(GAMMA + "/events/slug/" + event_slug(spec, day))
        bands = event_bands(event, spec, day)
        for band in bands:
            cid = band["condition_id"]
            with self.lock:
                prior = self.bands.get(cid)
                if prior and prior != band:
                    self.store.fail("identity_changed", condition_id=cid)
                    raise CaptureStopped("identity_changed")
                self.bands[cid] = band
            if prior is None:
                self.store.write("band_identity", band)
                self.add_job("reward:" + cid, self.args.terms_seconds, lambda cid=cid: self.reward(cid))
                self.add_job("fee:" + cid, self.args.metadata_seconds,
                             lambda cid=cid: self.http.read(CLOB + "/clob-markets/" + cid))
                for token in band["token_ids"]:
                    self.add_job("fee-rate:" + token, self.args.metadata_seconds,
                                 lambda t=token: self.http.read(CLOB + "/fee-rate", params={"token_id": t}))
        missing = set(self.bands) - {b["condition_id"] for b in bands}
        missing = {cid for cid in missing if self.bands[cid]["event_slug"] == event_slug(spec, day)}
        if missing:
            self.store.gap("metadata_membership_missing", condition_ids=sorted(missing), retained=True)
        self.books(only_new=True)

    def books(self, only_new=False):
        tokens = self.tokens()
        if only_new:
            tokens = [t for t in tokens if t not in self.baselined]
        for offset in range(0, len(tokens), 100):
            batch = tokens[offset:offset + 100]
            rows = self.http.read(CLOB + "/books", body=[{"token_id": t} for t in batch])
            if not isinstance(rows, list):
                raise ValueError("book array missing")
            present = {str(row.get("asset_id")) for row in rows if isinstance(row, dict) and
                       isinstance(row.get("bids"), list) and isinstance(row.get("asks"), list)}
            if set(batch) - present:
                self.store.gap("book_baseline_missing", tokens=sorted(set(batch) - present))
            for row in rows:
                if not isinstance(row, dict) or str(row.get("asset_id")) not in present:
                    continue
                try:
                    age = datetime.now(timezone.utc).timestamp() - float(row["timestamp"]) / 1000
                    if abs(age) > self.args.max_age_seconds:
                        self.store.gap("book_source_age", token=row["asset_id"], seconds=age)
                except (ValueError, TypeError, KeyError):
                    self.store.gap("book_source_clock_unreadable")
            new = present - self.baselined
            if new:
                self.store.write("rest_baseline", {"tokens": sorted(new), "source_age_not_guaranteed": True})
            self.baselined.update(present)

    def reward(self, cid):
        cursor, seen = None, set()
        for _ in range(10):
            page = self.http.read(CLOB + "/rewards/markets/" + cid,
                                  params={"next_cursor": cursor} if cursor else None)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ValueError("reward page shape")
            cursor = page.get("next_cursor")
            if cursor in (None, "", "LTE=", "-1"):
                return
            if not isinstance(cursor, str) or cursor in seen:
                raise ValueError("reward repeated cursor")
            seen.add(cursor)
        raise ValueError("reward pagination bound")

    def run(self):
        specs = {spec.id: spec for spec in BUILTIN_SPECS}
        for market in self.args.market:
            for day in self.args.event_date:
                self.add_job(f"event:{market}:{day}", self.args.metadata_seconds,
                             lambda s=specs[market], d=day: self.discover(s, d))
        self.add_job("books", self.args.rest_book_seconds, self.books)
        self.add_job("time", self.args.time_sample_seconds, lambda: self.http.read(CLOB + "/time"))
        self.stream.start()
        try:
            while True:
                self.store.check()
                if not self.stream.is_alive():
                    self.store.fail("stream_thread_ended")
                    raise CaptureStopped("stream_thread_ended")
                now = time.monotonic()
                job = min(self.jobs.values(), key=lambda j: j.due)
                if job.due > now:
                    self.store.stop.wait(min(0.2, job.due - now))
                    continue
                if job.due and now - job.due > 0.5:
                    self.store.gap("rest_cadence_lag", job=job.key, seconds=now - job.due)
                try:
                    job.action()
                except (ValueError, OSError) as exc:
                    self.store.gap("reconciliation_failed", job=job.key, error=type(exc).__name__)
                job.due = time.monotonic() + job.interval
                self.store.health()
        finally:
            self.stream.ending.set()
            self.stream.join(timeout=10)
            if self.stream.is_alive():
                self.store.fail("stream_shutdown_timeout")
