"""Price-free coverage receipts, strict identities and book reconciliation."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import math
import threading
import time

from weather.market.pilot_evidence_contract import strict_json
from weather.market.pilot_evidence_public import CONDITION
from weather.market.pilot_evidence_store import stamp


def event_slug(spec, day):
    months = ("january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december")
    return f"{spec.slug_prefix}-{months[day.month - 1]}-{day.day}-{day.year}"


def event_bands(event, spec, day):
    slug = event_slug(spec, day)
    if not isinstance(event, dict) or event.get("slug") != slug or not event.get("markets"):
        raise ValueError("event identity or bands missing")
    if not isinstance(event["markets"], list) or len(event["markets"]) > 100:
        raise ValueError("event band limit")
    result, seen = [], set()
    for market in event["markets"]:
        if not isinstance(market, dict):
            raise ValueError("event band shape")
        cid = market.get("conditionId", "")
        tokens, outcomes = market.get("clobTokenIds"), market.get("outcomes")
        tokens = strict_json(tokens) if isinstance(tokens, str) else tokens
        outcomes = strict_json(outcomes) if isinstance(outcomes, str) else outcomes
        if (not isinstance(cid, str) or not re.fullmatch(CONDITION, cid) or cid in seen or not isinstance(tokens, list) or len(tokens) != 2 or
                not all(isinstance(t, str) and 0 < len(t) <= 100 and t.isdecimal() for t in tokens) or
                len(set(tokens)) != 2 or not isinstance(outcomes, list) or
                sorted(str(o).lower() for o in outcomes) != ["no", "yes"]):
            raise ValueError("condition/token/outcome binding missing")
        seen.add(cid)
        result.append({"condition_id": cid, "token_ids": tokens, "outcomes": outcomes,
                       "market": spec.id, "event_date": day.isoformat(), "event_slug": slug,
                       "unit": spec.display_unit, "question": market.get("question"),
                       "gamma_market_id": market.get("id")})
    return result


def levels(rows):
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError("full book levels missing")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("book level shape")
        try:
            if len(str(row["price"])) > 64 or len(str(row["size"])) > 64:
                raise ValueError("book numeric length")
            price, size = Decimal(str(row["price"])), Decimal(str(row["size"]))
        except (KeyError, InvalidOperation):
            raise ValueError("book level number") from None
        if not price.is_finite() or not size.is_finite() or not 0 <= price <= 1 or size < 0 or price in result:
            raise ValueError("book level scope")
        if size:
            result[price] = size
    return result


def validated_book(row, token, cid, received):
    if not isinstance(row, dict) or row.get("asset_id") != token or str(row.get("market", "")).lower() != cid.lower():
        raise ValueError("book asset/condition binding")
    books = {side: levels(row.get(side)) for side in ("bids", "asks")}
    try:
        source = Decimal(str(row["timestamp"])) / 1000
    except (KeyError, InvalidOperation):
        raise ValueError("book source clock missing") from None
    if not source.is_finite() or source <= 0:
        raise ValueError("book source clock invalid")
    age = datetime.fromisoformat(received["receipt_utc"]).timestamp() - float(source)
    if not math.isfinite(age):
        raise ValueError("book source clock unrepresentable")
    return books, age


class Coverage:
    def __init__(self, store, expected, *, max_age=30, max_delay=30):
        self.store, self.max_age, self.max_delay = store, max_age, max_delay
        self.lock = threading.RLock()
        self.events = {slug: {"discovered": False, "metadata_receipt_utc": None,
                              "tokens": [], "f0_discovery_agrees": False} for slug in expected}
        self.bands, self.tokens, self.stream_books = {}, {}, {}
        self.intervals = {}
        self.last_market = self.last_transport = None
        self.begin = stamp()
        self.metadata_seconds = 180

    def interval(self, code, scope, *, bad=True, boundary=None, **details):
        key, row = code + ":" + scope, None
        now = stamp()
        with self.lock:
            if bad and key not in self.intervals:
                row = {"code": code, "scope": scope, "from": boundary or now,
                       "detected": now, **details}
                self.intervals[key] = row
            elif not bad and key in self.intervals:
                previous = self.intervals.pop(key)
                row = {"code": code, "scope": scope, "from": previous["from"], "to": now,
                       "duration_seconds": max(0, (now["receipt_monotonic_ns"] -
                                                   previous["from"]["receipt_monotonic_ns"]) / 1e9)}
        if row:
            if bad:
                self.store.gap(code, **{k: v for k, v in row.items() if k != "code"})
            else:
                self.store.write("coverage_gap_end", row)

    def discover(self, bands, received):
        if not bands:
            raise ValueError("event has no bands")
        slug = bands[0]["event_slug"]
        revisions, added = [], []
        with self.lock:
            for band in bands:
                cid = band["condition_id"]
                prior = self.bands.get(cid)
                fields = ("condition_id", "token_ids", "outcomes", "market", "event_date", "event_slug", "unit")
                if prior and any(prior[k] != band[k] for k in fields):
                    raise ValueError("immutable identity changed")
                if prior and prior != band:
                    revisions.append({"condition_id": cid, "previous": prior, "current": band})
                for token in band["token_ids"]:
                    if token in self.tokens and self.tokens[token]["condition_id"] != cid:
                        raise ValueError("token reused across conditions")
                    if token not in self.tokens:
                        self.tokens[token] = {"condition_id": cid, "event": slug,
                            "baseline_taken_at": None, "baseline_valid_at": None,
                            "last_rest": None, "last_stream": None, "source_age_seconds": None,
                            "baseline_usable": False, "rest_observation_fresh": False}
                self.bands[cid] = band
                if prior is None:
                    added.append(band)
            event = self.events[slug]
            current = {t for band in bands for t in band["token_ids"]}
            event.update(discovered=True, metadata_receipt_utc=received["receipt_utc"], metadata_received=received,
                         tokens=sorted(set(event["tokens"]) | current), f0_discovery_agrees=True)
            disappeared = set(event["tokens"]) - current
        for revision in revisions:
            self.store.write("descriptive_metadata_revision", revision)
        self.interval("event_membership_missing", slug, bad=bool(disappeared), missing=sorted(disappeared))
        self.interval("event_discovery_pending", slug, bad=False)
        return added

    def eligible_stream_tokens(self):
        with self.lock:
            return sorted(t for t, state in self.tokens.items() if state["baseline_taken_at"] is not None)

    def book(self, row, token, received, *, source, request_start=None):
        with self.lock:
            state = self.tokens[token]
            cid, boundary = state["condition_id"], state["last_rest"] or self.begin
        try:
            book, age = validated_book(row, token, cid, received)
        except ValueError:
            self.interval("book_invalid", token, boundary=boundary)
            return False
        usable = -self.max_delay <= age <= self.max_age
        mismatch = ambiguous = False
        with self.lock:
            state["baseline_taken_at"] = state["baseline_taken_at"] or received
            state["source_age_seconds"] = age
            state["source_age_at_observation"] = age
            state["source_observed_at"] = received
            state["baseline_usable"] = usable
            if usable:
                state["baseline_valid_at"] = received
            source_boundary = state["baseline_valid_at"] or self.begin
            if source == "rest":
                state["last_rest"] = received
                state["rest_observation_fresh"] = True
                current = self.stream_books.get(token)
                if current and request_start:
                    ambiguous = current["received"]["receipt_monotonic_ns"] >= request_start["receipt_monotonic_ns"]
                    mismatch = current["book"] != book and not ambiguous
            else:
                state["last_stream"] = received
                self.last_market = received
                self.stream_books[token] = {"book": book, "received": received}
        self.interval("book_invalid", token, bad=False)
        self.interval("book_source_age", token, bad=not usable, boundary=source_boundary, seconds=age,
                      interpretation="source age, not an outage or missing-price count")
        if source == "rest":
            self.interval("rest_observation_stale", token, bad=False)
            if not ambiguous:
                self.interval("stream_rest_mismatch", token, bad=mismatch, boundary=boundary)
            if ambiguous:
                self.store.counts["reconciliation_overlaps_stream_update"] += 1
        return usable

    def changes(self, row, received):
        changes = row.get("price_changes")
        if not isinstance(changes, list):
            return
        with self.lock:
            for change in changes:
                token = change.get("asset_id") if isinstance(change, dict) else None
                if token not in self.tokens or token not in self.stream_books:
                    continue
                if row.get("market") != self.tokens[token]["condition_id"]:
                    raise ValueError("stream change condition")
                side = {"BUY": "bids", "SELL": "asks"}.get(change.get("side"))
                if not side:
                    raise ValueError("stream change side")
                item = levels([change])
                price = Decimal(str(change["price"]))
                target = self.stream_books[token]["book"][side]
                if item:
                    if price not in target and len(target) >= 5000:
                        raise ValueError("stream state level cap")
                    target.update(item)
                else:
                    target.pop(price, None)
                self.stream_books[token]["received"] = received
                self.tokens[token]["last_stream"] = received
                self.last_market = received

    def freshness(self):
        now = time.monotonic_ns()
        with self.lock:
            rows = [(t, s["last_rest"]) for t, s in self.tokens.items()]
            market, transport = self.last_market, self.last_transport
        for token, last in rows:
            stale = last is None or (now - last["receipt_monotonic_ns"]) / 1e9 > self.max_age
            with self.lock:
                self.tokens[token]["rest_observation_fresh"] = not stale
                sample = self.tokens[token].get("source_observed_at")
                if sample:
                    age = self.tokens[token]["source_age_at_observation"] + (now - sample["receipt_monotonic_ns"]) / 1e9
                    self.tokens[token]["source_age_seconds"] = age
                    if age > self.max_age:
                        self.tokens[token]["baseline_usable"] = False
            self.interval("rest_observation_stale", token, bad=stale, boundary=last or self.begin)
        for event, state in tuple(self.events.items()):
            last = state.get("metadata_received")
            stale = last is None or (now - last["receipt_monotonic_ns"]) / 1e9 > self.metadata_seconds * 1.1
            self.interval("event_metadata_stale", event, bad=stale, boundary=last or self.begin)
        if transport:
            quiet = market is None or (now - market["receipt_monotonic_ns"]) / 1e9 > self.max_age
            self.interval("market_update_silence_uncertain", "stream", bad=quiet, boundary=market or self.begin,
                          interpretation="quiet market or stalled feed; heartbeat is transport-only")

    def snapshot(self):
        with self.lock:
            now = time.monotonic_ns()
            def recent(received, limit):
                return bool(received and 0 <= (now - received["receipt_monotonic_ns"]) / 1e9 <= limit)
            tokens = {t: dict(state) for t, state in self.tokens.items()}
            events = {e: dict(state) for e, state in self.events.items()}
            # Health also runs while the main reconciliation loop is in a shared
            # cooldown. Derive current ages without mutating/journaling here.
            for state in tokens.values():
                state["rest_observation_fresh"] = recent(state["last_rest"], self.max_age)
                sample = state.get("source_observed_at")
                if sample:
                    elapsed = (now - sample["receipt_monotonic_ns"]) / 1e9
                    age = state["source_age_at_observation"] + elapsed
                    state["source_age_seconds"] = age
                    state["baseline_usable"] = bool(state["baseline_usable"] and elapsed >= 0 and
                                                   -self.max_delay <= age <= self.max_age)
            for event in events.values():
                event["metadata_observation_fresh"] = recent(event.get("metadata_received"), self.metadata_seconds * 1.1)
            ready = bool(tokens) and all(e["discovered"] and e["f0_discovery_agrees"] and
                                         e["metadata_observation_fresh"] for e in events.values())
            observed_ready = ready and all(s["baseline_taken_at"] is not None and s["rest_observation_fresh"] for s in tokens.values())
            blocking = {"book_invalid", "book_response_scope", "book_baseline_missing", "event_discovery_pending",
                        "event_membership_missing", "event_metadata_stale", "f0_discovery_mismatch", "capacity_infeasible"}
            observed_ready = observed_ready and not any(r["code"] in blocking for r in self.intervals.values())
            ready = ready and all(s["baseline_usable"] and s["rest_observation_fresh"] for s in tokens.values())
            ready = ready and not self.intervals
            return {"coverage_ready": ready, "accuracy_qualified": False,
                    "ready_for_capture": observed_ready,
                    "source_freshness_ready": bool(tokens) and all(s["baseline_usable"] for s in tokens.values()),
                    "expected_events": len(events), "discovered_events": sum(e["discovered"] for e in events.values()),
                    "expected_tokens": len(tokens), "baselines_taken": sum(s["baseline_taken_at"] is not None for s in tokens.values()),
                    "usable_baselines": sum(s["baseline_usable"] for s in tokens.values()),
                    "events": events, "tokens": tokens, "open_intervals": dict(self.intervals),
                    "last_transport": self.last_transport, "last_market_event": self.last_market}
