"""Fictional sealed 88a capture day at the real calibration density, as the exporter reads it (maker replay v2, W2).

S2 measures the exporter itself, so this writes its *input*: sealed hourly ``maker_evidence`` segments
through the production ``EvidenceStore``, plus per-event plugin sources, shaped like the exporter tests'
``layout()`` fixture but at a 170-condition daily union. No captured market, wallet, calibration,
panel or settlement data is read; every identity, price and forecast is invented.

- The 12 built-in markets (real slugs and time zones, so ``event_identity`` resolves) with four target
  dates each: local T+0..T+2 are live at 00:00 UTC; at each market's local midnight T+0 leaves the
  export and the new T+2 event is discovered. Band counts are spread so the union is exactly ``union``.
- Each minute: one discovery capture (stored on change), one reward capture per live band (body
  changes ``terms_changes`` times a day), and ``ceil(2*D/100)`` book captures of at most 50 bands with
  ``book_depth`` levels a side. The exporter projects every live band at every book capture.
- Trade stream: markets share ``connections`` sockets. Each socket's opening batch is one subscription
  and each later-discovered event subscribes alone; ``outages`` per socket drop every subscription on
  it until one lifecycle row per subscription reconnects it; ``trades`` prints a day.
- Plugin sources per event: band snapshot rows, one NBM bulletin with its manifest, one explanation.
  No settlement ledger is written (settlement rows are a few dozen a day, not a memory driver).

``EvidenceStore`` fsyncs every append; the generator is not the measurement, so ``fsync`` is
suspended while it writes. The exporter run that follows is untouched.
"""
from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random

from weather.market.maker_evidence_store import EvidenceStore, encoded
from weather.market.market_registry import BUILTIN_SPECS

HEALTH = timedelta(seconds=30)


@contextmanager
def _no_fsync():
    original = os.fsync
    os.fsync = lambda fd: None
    try:
        yield
    finally:
        os.fsync = original


def _slug(spec, target):
    return f"{spec.slug_prefix}-{target.strftime('%B').lower()}-{target.day}-{target.year}"


class CaptureDay:
    def __init__(self, day: date, *, union=170, trades=2000, connections=4, outages=2, book_depth=8,
                 terms_changes=6, seed=0, minutes=1440):
        specs = list(BUILTIN_SPECS)
        if union < 3 * 4 * len(specs):
            raise ValueError("union_below_three_bands_per_event")
        self.day, self.trades, self.connections, self.outages = day, trades, connections, outages
        self.book_depth, self.terms_changes, self.minutes = book_depth, terms_changes, minutes
        self.rng = random.Random(f"capture170-{day}-{union}-{trades}-{seed}")
        self.start = datetime.combine(day, time(), tzinfo=timezone.utc)
        self.events, self.token = [], 1000
        slots = [(m, k) for m in range(len(specs)) for k in range(4)]
        self.rng.shuffle(slots)
        base, extra = divmod(union, len(slots))
        sizes = {slot: base + (i < extra) for i, slot in enumerate(slots)}
        for m, spec in enumerate(specs):
            local0 = self.start.astimezone(spec.tz).date()
            roll = datetime.combine(local0 + timedelta(days=1), time(), tzinfo=spec.tz).astimezone(timezone.utc)
            for k in range(4):
                found = self.start if k < 3 else roll + timedelta(seconds=60 + self.rng.randrange(60))
                self.events.append(self._event(spec, m, local0 + timedelta(days=k), found, sizes[(m, k)]))
        self.bands = {b["cid"]: b for e in self.events for b in e["bands"]}
        self.changes = {cid: sorted(self.rng.randrange(1440) for _ in range(terms_changes)) for cid in sorted(self.bands)}

    def _event(self, spec, m, target, found, n):
        slug = _slug(spec, target)
        lo = 60 if spec.unit == "F" else 18
        width = 2 if spec.unit == "F" else 1
        centre = self.rng.uniform(0, n - 1)
        weights = [math.exp(-((i - centre) ** 2) / 2) for i in range(n)]
        bands = []
        for i in range(n):
            kind = "lte" if i == 0 else "gte" if i == n - 1 else "eq"
            low = lo if i == 0 else lo + 1 + (i - 1) * width if kind == "eq" else lo + 1 + (n - 2) * width
            high = low + width - 1 if kind == "eq" else low
            cid = "0x" + hashlib.sha256(f"{slug}|{i}".encode()).hexdigest()
            yes, no = str(self.token), str(self.token + 1)
            self.token += 2
            bands.append(dict(cid=cid, yes=yes, no=no, kind=kind, lo=low, hi=high, index=i,
                              p=round(weights[i] / sum(weights), 6)))
        return dict(spec=spec, market=m, target=target, slug=slug, found=found, bands=bands,
                    socket=m % self.connections)

    def horizon(self, event, at):
        return (event["target"] - at.astimezone(event["spec"].tz).date()).days

    def live(self, at):
        return sorted((e for e in self.events if e["found"] <= at and 0 <= self.horizon(e, at) <= 2),
                      key=lambda e: e["slug"])

    # -- plugin sources -----------------------------------------------------------------------------
    def write_sources(self, root: Path):
        for event in self.events:
            spec, target = event["spec"], event["target"]
            folder = root / "snapshots" / event["slug"]
            folder.mkdir(parents=True)
            captured = min(event["found"], self.start) - timedelta(minutes=5) if event["found"] == self.start \
                else event["found"] - timedelta(minutes=5)
            rows = [{"snapshot_id": "fixture-" + event["slug"], "captured_at_utc": captured.isoformat(),
                     "captured_at_local": captured.astimezone(spec.tz).isoformat(), "event_slug": event["slug"],
                     "model_version": "fixture-model", "feature_schema_version": "fixture",
                     "condition_id": b["cid"], "clob_yes_token_id": b["yes"], "clob_no_token_id": b["no"],
                     "bin_kind": b["kind"], "bin_value_c": b["lo"], "bin_value_hi_c": b["hi"],
                     "range_label": f"fixture-{b['index']}", "model_probability": b["p"],
                     "market_yes": .4, "market_no": .6} for b in event["bands"]]
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            issue = captured.replace(minute=0, second=0, microsecond=0)
            valid = datetime.combine(target + timedelta(days=1), time(), timezone.utc)
            lead = (valid - issue).total_seconds() / 3600
            lines = [f" {spec.icao} NBM V4.3 NBP GUIDANCE {issue:%m/%d/%Y %H%M} UTC", f"FHR   {lead - 12:g} {lead:g}"]
            lo = 60 if spec.unit == "F" else 18
            for code, value in zip(("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9", "TXNMN", "TXNSD"),
                                   (lo, lo + 2, lo + 4, lo + 6, lo + 8, lo + 4, 3)):
                lines.append(f"{code:<6} 40 {value}")
            text = "\n".join(lines) + "\n"
            bulletin = {"schema_version": "nbm_probabilistic_tmax_v0.1", "source": "nbm_probabilistic_tmax",
                        "source_kind": "nbp_station_text", "station_id": spec.icao, "target_date": target.isoformat(),
                        "source_url": None, "fetched_at": captured.isoformat(),
                        "payload_hash": hashlib.sha256(text.encode()).hexdigest(), "text": text}
            payload = encoded(bulletin)
            key = hashlib.sha256(payload).hexdigest()
            path = folder / "forecast_payloads" / "sha256" / key[:2] / (key + ".json")
            path.parent.mkdir(parents=True)
            path.write_bytes(payload + b"\n")
            base = {k: rows[0][k] for k in ("snapshot_id", "event_slug", "captured_at_utc")}
            explanation = {**base, "explanations": {"probability_calibration_context": {}}}
            lineage = {**base, "release_id": "fixture-release", "release_manifest_sha256": "a" * 64,
                       "release_identity_status": "unverified", "release_calibration_method": None}
            (folder / "forecast_payloads.jsonl").write_bytes(
                encoded(dict(lineage, source="nbm_probabilistic_tmax", payload_hash=key)) + b"\n")
            (folder / "snapshot_explanations.jsonl").write_bytes(encoded(explanation) + b"\n")

    # -- 88a timeline -------------------------------------------------------------------------------
    def _timeline(self):
        rng, out = self.rng, []
        end = self.start + timedelta(minutes=self.minutes)
        for socket in range(self.connections):
            out.append((self.start + timedelta(milliseconds=100 + 10 * socket), "connect", (socket, None)))
            for _ in range(self.outages):
                drop = self.start + timedelta(seconds=rng.randrange(600, 86000), microseconds=rng.randrange(10**6))
                out += [(drop, "gap", socket), (drop + timedelta(seconds=rng.randrange(60, 600)), "connect", (socket, None))]
        for event in self.events:
            if event["found"] > self.start:
                out.append((event["found"] - timedelta(milliseconds=500), "connect", (event["socket"], event["slug"])))
        for minute in range(self.minutes):
            base = self.start + timedelta(seconds=minute * 60, microseconds=250_000 + rng.randrange(500_000))
            live = self.live(base)
            selected = [b for e in live for b in e["bands"]]
            out.append((base, "discovery", None))
            for i, band in enumerate(selected):
                out.append((base + timedelta(seconds=1, microseconds=15_000 * i), "reward", (band["cid"], minute)))
            for k in range(max(1, math.ceil(2 * len(selected) / 100))):
                out.append((base + timedelta(seconds=3, microseconds=400_000 * k),
                            "books", [b for j, b in enumerate(selected) if j * 2 // 100 == k]))
        for _ in range(self.trades):
            out.append((self.start + timedelta(microseconds=rng.randrange(86_400 * 10**6)), "trade", None))
        out.sort(key=lambda e: e[0])
        return [e for e in out if self.start <= e[0] < end]

    def _discovery(self, at):
        events = []
        for e in sorted((e for e in self.events if e["found"] <= at), key=lambda e: e["slug"]):
            markets = [{"id": str(b["index"]), "conditionId": b["cid"], "active": True, "closed": False,
                        "enableOrderBook": True, "outcomes": '["No", "Yes"]',
                        "clobTokenIds": json.dumps([b["no"], b["yes"]]), "rewardsMinSize": 20}
                       for b in e["bands"]]
            events.append({"id": "event-" + e["slug"], "slug": e["slug"], "markets": markets})
        return events

    def _book(self, band, at):
        rng = self.rng
        tick = 1 + int(band["p"] * 96) + rng.randrange(-1, 2)
        tick = min(max(tick, 1), 97)
        bids = [{"price": f"{(tick - i) / 100:.2f}", "size": str(10 + rng.randrange(200))}
                for i in range(self.book_depth) if tick - i > 0]
        asks = [{"price": f"{(tick + 2 + i) / 100:.2f}", "size": str(10 + rng.randrange(200))}
                for i in range(self.book_depth) if tick + 2 + i < 100]
        stamp = str(int(at.timestamp() * 1000))
        common = {"market": band["cid"], "timestamp": stamp, "tick_size": "0.01", "min_order_size": "5", "neg_risk": True}
        no_bids = [{"price": f"{1 - float(a['price']):.2f}", "size": a["size"]} for a in asks]
        no_asks = [{"price": f"{1 - float(b['price']):.2f}", "size": b["size"]} for b in bids]
        return [dict(common, asset_id=band["yes"], bids=bids, asks=asks),
                dict(common, asset_id=band["no"], bids=no_bids, asks=no_asks)]

    def write_capture(self, root: Path) -> dict:
        """Write the sealed hourly segments; returns counts of what was recorded."""
        now = [self.start]
        counts = dict(discovery=0, rewards=0, books=0, book_rows=0, trades=0, lifecycle=0, gaps=0)
        subs = {}  # key -> [socket, tokens, subscribed, connected]
        for e in self.events:
            key = e["socket"] if e["found"] == self.start else e["slug"]
            entry = subs.setdefault(key, [e["socket"], [], e["found"] == self.start, False])
            entry[1] += [t for b in e["bands"] for t in (b["yes"], b["no"])]
        with _no_fsync():
            store = EvidenceStore(root / "maker_evidence", clock=lambda: now[0])
            for at, kind, value in self._timeline():
                now[0] = at
                if kind == "discovery":
                    body = encoded(self._discovery(at))
                    store.record("discovery", body, metadata={"http_status": 200}, stored_body=body,
                                 change_key="discovery:fixture")
                    counts["discovery"] += 1
                elif kind == "reward":
                    cid, minute = value
                    band, change = self.bands[cid], sum(1 for m in self.changes[cid] if m <= minute)
                    reward = {"data": [{"condition_id": cid, "rewards_min_size": 20 + 30 * (change % 2),
                              "rewards_max_spread": 3.5 + change % 3, "rewards_config": [{
                                  "rate_per_day": 50 + 25 * (change % 4), "start_date": self.day.isoformat(),
                                  "end_date": (self.day + timedelta(days=4)).isoformat()}]}]}
                    store.record("rewards", encoded(reward), metadata={"http_status": 200}, change_key="reward:" + cid)
                    counts["rewards"] += 1
                elif kind == "books":
                    rows = [r for band in value for r in self._book(band, at)]
                    store.record("books", encoded(rows), metadata={"http_status": 200})
                    counts["books"] += 1
                    counts["book_rows"] += len(rows)
                elif kind == "trade":
                    live = [b for e in self.live(at) for b in e["bands"]
                            if any(s[3] and b["yes"] in s[1] for s in subs.values())]
                    if not live:
                        continue
                    band = live[self.rng.randrange(len(live))]
                    store.record("trades", encoded(dict(
                        event_type="last_trade_price", asset_id=self.rng.choice((band["yes"], band["no"])),
                        market=band["cid"], timestamp=str(int((at - timedelta(milliseconds=self.rng.randrange(800)))
                                                              .timestamp() * 1000)),
                        price=f"{self.rng.randrange(1, 100) / 100:.2f}", size=str(self.rng.randrange(1, 500)),
                        side=self.rng.choice(("BUY", "SELL")))))
                    counts["trades"] += 1
                elif kind == "gap":
                    for entry in subs.values():
                        if entry[0] == value and entry[3]:
                            entry[3] = False
                            store.event("stream_gap", dict(channel="trades", error_type="FixtureDisconnect",
                                                           subscription=store.subscription(entry[1], "trades")))
                            counts["gaps"] += 1
                else:
                    socket, only = value
                    if only is not None:
                        subs[only][2] = True
                    keys = [only] if only is not None else sorted(
                        (k for k, s in subs.items() if s[0] == socket and s[2]), key=str)
                    for offset, key in enumerate(keys):
                        now[0] = at + timedelta(microseconds=offset)
                        subs[key][3] = True
                        store.event("stream_lifecycle", dict(state="connected", channel="trades",
                                                             subscription=store.subscription(subs[key][1], "trades")))
                        counts["lifecycle"] += 1
            now[0] = self.start + timedelta(minutes=self.minutes) - timedelta(microseconds=1)
            store.seal()
        return counts

    def stats(self):
        counts = []
        for minute in range(0, 1440, 10):
            counts.append(sum(len(e["bands"]) for e in self.live(self.start + timedelta(minutes=minute, seconds=30))))
        return dict(union=len(self.bands), events=len(self.events), markets=len({e["spec"].id for e in self.events}),
                    subscriptions=len({e["socket"] if e["found"] == self.start else e["slug"] for e in self.events}),
                    instantaneous_min=min(counts), instantaneous_max=max(counts),
                    instantaneous_mean=round(sum(counts) / len(counts), 2), book_depth=self.book_depth,
                    trades=self.trades, minutes=self.minutes)


def write(root: Path, day: date, **kwargs) -> dict:
    """Create ``root`` (new) with one fictional capture day and its plugin sources."""
    root.mkdir(parents=True)
    capture = CaptureDay(day, **kwargs)
    capture.write_sources(root)
    counts = capture.write_capture(root)
    return dict(fixture=capture.stats(), recorded=counts)
