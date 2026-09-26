"""Local T+0..T+2 universe from 88a discovery/books plus snapshot band metadata.

88a selection_projection omits band boundaries, tick and minimum order size.
Those must be supplied from captured long rows and both-token books, never
inferred from rewardsMinSize (a different contract) or fetched here.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json

from maker_core.contracts import MarketDescriptor, UniverseSnapshot, utc_time
from weather.market.maker_plugin import PLUGIN_VERSION
from weather.market.maker_plugin.inputs import band, body, digest, event_identity, latest, records, timestamp


class WeatherUniverse:
    def __init__(self, *, discovery=(), books=(), band_rows=()):
        self.discovery = records(discovery)
        self.books = records(books)
        self.band_rows = records(band_rows)

    def bands(self, event_slug, as_of):
        candidates = [r for r in self.band_rows if r["event_slug"] == event_slug
                      and timestamp(r["captured_at_utc"]) <= as_of]
        if not candidates:
            raise ValueError("missing_captured_band_metadata")
        when = max(timestamp(r["captured_at_utc"]) for r in candidates)
        selected = [r for r in candidates if timestamp(r["captured_at_utc"]) == when]
        result = {}
        for row in selected:
            identity = row["condition_id"].lower()
            if identity in result:
                raise ValueError("duplicate_band_identity")
            result[identity] = band(row)
        return result

    def _events(self, as_of):
        events = {}
        for captured in self.discovery:
            if timestamp(captured["captured_at_utc"]) > as_of or not captured.get("body_stored"):
                continue
            for event in body(captured):
                events.setdefault(event["slug"], []).append({
                    "captured_at_utc": captured["captured_at_utc"], "event": event})
        return [latest(rows, as_of) for _, rows in sorted(events.items())]

    def _book(self, token, as_of):
        found = []
        for capture in self.books:
            if timestamp(capture["captured_at_utc"]) > as_of or not capture.get("body_stored"):
                continue
            for book in body(capture):
                if str(book["asset_id"]) == token:
                    found.append({"captured_at_utc": capture["captured_at_utc"], "book": book})
        return latest(found, as_of)["book"]

    def discover(self, as_of_utc, horizon_days):
        utc_time(as_of_utc)
        if isinstance(horizon_days, bool) or horizon_days not in (0, 1, 2):
            raise ValueError("supported_horizon_is_zero_to_two")
        markets = []
        for captured in self._events(as_of_utc):
            event = captured["event"]
            spec, target = event_identity(event["slug"])
            lead = (target - as_of_utc.astimezone(spec.tz).date()).days
            if not 0 <= lead <= horizon_days:
                continue
            bands = self.bands(event["slug"], as_of_utc)
            for row in event["markets"]:
                if row.get("closed") or not row.get("active") or row.get("enableOrderBook") is False:
                    continue
                cid = row["conditionId"].lower()
                outcomes, tokens = row["outcomes"], row["clobTokenIds"]
                outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
                if len(tokens) != 2 or len(outcomes) != 2 or set(outcomes) != {"Yes", "No"}:
                    raise ValueError("invalid_outcome_mapping")
                pair = {name.upper(): str(tokens[outcomes.index(name)]) for name in outcomes}
                books = [self._book(token, as_of_utc) for token in pair.values()]
                if any(b["market"].lower() != cid for b in books) or cid not in bands:
                    raise ValueError("captured_condition_mismatch")
                terms = {(Decimal(str(b["tick_size"])), Decimal(str(b["min_order_size"]))) for b in books}
                if len(terms) != 1:
                    raise ValueError("ambiguous_book_rules")
                tick, size = terms.pop()
                close = datetime.combine(target + timedelta(days=1), time(), spec.tz).astimezone(timezone.utc)
                markets.append(MarketDescriptor(
                    "weather", event["slug"], cid, pair, tick, size, event["slug"], close, None,
                    spec.unit, PLUGIN_VERSION, {"discovery": digest(captured),
                    "band": digest([str(v) for v in bands[cid]]),
                    "book_rules": digest([str(tick), str(size)])}))
        ordered = tuple(sorted(markets, key=lambda m: m.condition_id))
        return UniverseSnapshot(ordered, as_of_utc, {"descriptors": digest([
            [m.condition_id, dict(m.source_hashes)] for m in ordered])})

    def describe(self, condition_id, as_of_utc):
        for market in self.discover(as_of_utc, 2).markets:
            if market.condition_id == condition_id:
                return market
        raise KeyError(condition_id)
