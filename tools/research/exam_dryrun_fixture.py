"""Synthetic 88a day tree for the maker-replay exam dry run; fixture data only.

Writes the exam's 18 UTC days (three calibration dates, fourteen quote dates and the
settlement-only date) through the production writers. Capture goes through
``EvidenceStore`` (hourly sealed segments, gzip by ``compress_closed_segments``).
Plugin support tables use the CSV/JSONL layout of
``tests/market/test_maker_plugin_dry_run.layout``. The immutable release root lets the
night kind project calibration methods.

Each day records two capture runs. The first loses power after a third of the day's
segments and leaves its segment unsealed. The second run's ``_recover`` seals it and
writes the day's ``run_summary``, so the export receipt carries one restart event and
the bundle shows the gap. One trailing segment is left unsealed in the open UTC day
after the panel, as on a live host at export time. No production path, network,
credential or clock is read. The writer's per-record ``fsync`` is skipped in this
process only: durability is irrelevant to a throwaway fixture, and fsync would
dominate the 150k-row run.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.execution_manifest import QUOTE_DATES, SETTLEMENT_DATE
from maker_core.replay.payloads import MAX_TRADE_CLOCK_SKEW
from weather.market.maker_evidence_archive import compress_closed_segments
from weather.market.maker_evidence_store import EvidenceStore, encoded
from weather.market.market_registry import BUILTIN_SPECS
from weather.release_artifacts import manifest_content_sha256
from weather.schema_registry import schema_version

DAYS = (*CALIBRATION_DATES, *QUOTE_DATES, SETTLEMENT_DATE)
RELEASE_ID = "dryrun-release"
CAPTURE_MINUTE = 20  # Outside the station's scheduled-print pull window, as in the dry-run layout.


@dataclass(frozen=True)
class Shape:
    cities: int = 12
    segments: int = 12  # Sealed hourly segments per day, spread evenly across the UTC day.
    minutes: int = 2  # Capture minutes per segment.
    reward_rows: int | None = None  # Per day; None is one row per condition per capture minute.
    trades_per_minute: int = 1  # Per city.
    # Calibration dates only (None: as above). Each print is a distinct engine event; the
    # look's pull_opportunity_cap needs rehearsed events x15 to cover the panel's candidates.
    calibration_trades_per_minute: int | None = None
    trade_lead_ms: int = 1200  # Venue clock ahead of capture; must stay inside the W1 bound.
    power_loss: bool = True
    trailing_unsealed: bool = True

    def __post_init__(self):
        if not 1 <= self.cities <= len(BUILTIN_SPECS):
            raise ValueError("cities_out_of_range")
        if not 2 <= self.segments <= 24 or not 1 <= self.minutes <= 30:
            raise ValueError("segments_or_minutes_out_of_range")
        if not 0 <= self.trades_per_minute <= 5000 or not 0 <= (self.calibration_trades_per_minute or 0) <= 5000:
            raise ValueError("trades_per_minute_out_of_range")
        if not 0 <= self.trade_lead_ms * 1000 <= MAX_TRADE_CLOCK_SKEW // timedelta(microseconds=1):
            raise ValueError("trade_lead_outside_w1_bound")

    def trades(self, day):
        dense = day in CALIBRATION_DATES and self.calibration_trades_per_minute is not None
        return self.calibration_trades_per_minute if dense else self.trades_per_minute

    def rewards_per_day(self):
        conditions = self.cities * 3
        return conditions * self.segments * self.minutes if self.reward_rows is None else self.reward_rows


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(encoded(r) + b"\n" for r in rows))


def csv_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@contextlib.contextmanager
def _no_fsync():
    original = os.fsync
    os.fsync = lambda fd: None
    try:
        yield
    finally:
        os.fsync = original


def _at(day, hour=0, minute=0, second=0):
    return datetime.combine(day, time(hour, minute, second), tzinfo=timezone.utc)


def _bulletin(spec, target, issue, fetched):
    """NBP station text in the layout of tests/market/test_maker_plugin.bulletin."""
    valid = datetime.combine(target + timedelta(days=1), time.min, timezone.utc)
    lead = (valid - issue).total_seconds() / 3600
    lines = [f" {spec.icao} NBM V4.3 NBP GUIDANCE {issue:%m/%d/%Y %H%M} UTC", f"FHR   {lead - 12:g} {lead:g}"]
    centre = 75 if spec.unit == "F" else 22
    spread = (-10, -5, 0, 5, 10, 0, 8) if spec.unit == "F" else (-5, -3, 0, 3, 5, 0, 4)
    for code, delta in zip(("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9", "TXNMN", "TXNSD"), spread):
        lines.append(f"{code:<6} 40 {abs(delta) if code == 'TXNSD' else centre + delta}")
    text = "\n".join(lines) + "\n"
    return {"schema_version": "nbm_probabilistic_tmax_v0.1", "source": "nbm_probabilistic_tmax",
            "source_kind": "nbp_station_text", "station_id": spec.icao, "target_date": target.isoformat(),
            "source_url": None, "fetched_at": fetched.isoformat(),
            "payload_hash": hashlib.sha256(text.encode()).hexdigest(), "text": text}


class Event:
    """One city's event for one capture day: three bands, target the next local date."""

    def __init__(self, spec, city_index, day, day_index):
        self.spec, self.day = spec, day
        self.target = day + timedelta(days=1)
        self.slug = f"{spec.slug_prefix}-{self.target.strftime('%B').lower()}-{self.target.day}-{self.target.year}"
        bands = [("lte", 69, 69), ("eq", 70, 79), ("gte", 80, 80)] if spec.unit == "F" else [
            ("lte", 19, 19), ("eq", 20, 25), ("gte", 26, 26)]
        captured = _at(day) - timedelta(hours=1)
        self.rows, self.markets, self.tokens = [], [], []
        for band, (kind, lo, hi) in enumerate(bands):
            serial = (city_index + 1) * 100_000 + day_index * 10 + band
            cid = "0x" + f"{serial:064x}"
            yes, no = str(2 * serial), str(2 * serial + 1)
            self.tokens += [(cid, yes), (cid, no)]
            self.markets.append({"id": str(serial), "conditionId": cid, "active": True, "closed": False,
                                 "enableOrderBook": True, "outcomes": '["No", "Yes"]',
                                 "clobTokenIds": json.dumps([no, yes]), "rewardsMinSize": 20})
            self.rows.append({"snapshot_id": f"dryrun-{spec.id}-{day}", "captured_at_utc": captured.isoformat(),
                              "captured_at_local": captured.astimezone(spec.tz).isoformat(), "event_slug": self.slug,
                              "model_version": "synthetic-model", "feature_schema_version": "synthetic",
                              "condition_id": cid, "clob_yes_token_id": yes, "clob_no_token_id": no,
                              "bin_kind": kind, "bin_value_c": lo, "bin_value_hi_c": hi,
                              "range_label": f"synthetic-{band}", "model_probability": (.2, .6, .2)[band],
                              "market_yes": .4, "market_no": .6})

    @property
    def conditions(self):
        return [m["conditionId"] for m in self.markets]

    def discovery(self):
        return {"id": "event-" + self.slug, "slug": self.slug, "markets": self.markets}

    def books(self):
        return [{"market": cid, "asset_id": token, "timestamp": "1894287300000", "tick_size": "0.01",
                 "min_order_size": "5", "neg_risk": True, "bids": [{"price": ".49", "size": "75"}],
                 "asks": [{"price": ".51", "size": "75"}]} for cid, token in self.tokens]

    def reward(self, cid):
        return {"data": [{"condition_id": cid, "rewards_min_size": 20, "rewards_max_spread": 5,
                          "rewards_config": [{"rate_per_day": 100, "start_date": (self.day - timedelta(days=2)).isoformat(),
                                              "end_date": self.target.isoformat()}]}]}

    def write_support(self, data_root, release_hash):
        folder = data_root / "snapshots" / self.slug
        csv_rows(folder / "snapshots_long.csv", self.rows)
        base = {key: self.rows[0][key] for key in ("snapshot_id", "event_slug", "captured_at_utc")}
        manifests = []
        for issue in (_at(self.day) - timedelta(hours=11), _at(self.day, 13)):
            payload = encoded(_bulletin(self.spec, self.target, issue, issue + timedelta(minutes=90)))
            key = hashlib.sha256(payload).hexdigest()
            path = folder / "forecast_payloads" / "sha256" / key[:2] / (key + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload + b"\n")
            # The night kind projects the calibration method from the release; none is captured.
            manifests.append(dict(base, captured_at_utc=(issue + timedelta(minutes=90)).isoformat(),
                                  release_id=RELEASE_ID, release_manifest_sha256=release_hash,
                                  release_identity_status="verified_variant_serving_bundle",
                                  source="nbm_probabilistic_tmax", payload_hash=key))
        jsonl(folder / "forecast_payloads.jsonl", manifests)
        jsonl(folder / "snapshot_explanations.jsonl", [{**base, "explanations": {"probability_calibration_context": {
            "afternoon_residual_centering": {"active": True, "reason": "afternoon_residual_centering_applied",
                                              "context_key": f"market={self.spec.id}|afternoon", "shift": -.3}}}}])


def write_release(release_root, specs):
    folder = release_root / RELEASE_ID
    folder.mkdir(parents=True)
    inventory = []
    for spec in specs:
        raw = encoded({"market_bin": {"method": "identity"}})
        artifact = folder / f"calibration-{spec.id}.json"
        artifact.write_bytes(raw)
        inventory.append(dict(role=f"base_model.{spec.id}.probability_calibration", path=artifact.name,
                              kind="calibration", declared=True, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    manifest = dict(schema_version=schema_version("release_manifest"), release_id=RELEASE_ID,
                    artifacts=dict(inventory=inventory))
    manifest["manifest_sha256"] = manifest_content_sha256(manifest)
    (folder / "release_manifest.json").write_bytes(encoded(manifest))
    return manifest["manifest_sha256"]


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


def _capture_minute(store, clock, at, events, trades, lead_ms, reward_slots, trade_index):
    """One capture cycle: discovery, books, rewards, then public trades, in clock order."""
    actions = [(0, "discovery", None), (500_000, "books", None)]
    for slot, (event, cid) in enumerate(reward_slots):
        actions.append((1_000_000 + slot * 1_000_000 // len(reward_slots), "rewards", (event, cid)))
    prints = [(event, trade_index + n) for n in range(trades) for event in events]
    for k, item in enumerate(prints):  # Distinct microsecond clocks in [2 s, 58 s).
        actions.append((2_000_000 + k * 56_000_000 // len(prints), "trade", item))
    for micros, kind, item in sorted(actions, key=lambda a: a[0]):
        clock.at = at + timedelta(microseconds=micros)
        if kind == "discovery":
            body = encoded([e.discovery() for e in events])
            store.record("discovery", body, metadata={"http_status": 200}, stored_body=body,
                         change_key="discovery:fixture")
        elif kind == "books":
            store.record("books", encoded([b for e in events for b in e.books()]), metadata={"http_status": 200})
        elif kind == "rewards":
            event, cid = item
            store.record("rewards", encoded(event.reward(cid)), metadata={"http_status": 200},
                         change_key="reward:" + cid)
        else:
            event, n = item
            cid, token = event.tokens[2 * (n % 3)]
            # Alternate a venue clock ahead of capture (inside the bound) and one behind it.
            lead = timedelta(milliseconds=lead_ms if n % 2 == 0 else -800)
            traded = clock.at + lead
            store.record("trades", encoded(dict(event_type="last_trade_price", asset_id=token, market=cid,
                         timestamp=str(int(traded.timestamp() * 1000)), price=(".47", ".53", ".50")[n % 3],
                         size="10", side=("SELL", "BUY")[n % 2], id=f"{cid[-8:]}-{at:%Y%m%dT%H%M}-{n}")))


def _write_day(root, day, events, shape, reward_cursor, pid):
    """Two runs: power loss after a third of the segments, then a recovering restart."""
    hours = [i * 24 // shape.segments for i in range(shape.segments)]
    cids = [(e, cid) for e in events for cid in e.conditions]
    slots = shape.segments * shape.minutes
    per_slot, extra = divmod(shape.rewards_per_day(), slots)
    loss = shape.segments // 3 if shape.power_loss else None
    tokens = [token for e in events for _, token in e.tokens]
    clock = Clock(_at(day, hours[0], CAPTURE_MINUTE - 1))
    store = EvidenceStore(root, clock=clock, max_raw_bytes=8 * 1024**3, rotate_bytes=2 * 1024**3)
    started = clock.at
    slot, trades = 0, 0
    for index, hour in enumerate(hours):
        if loss is not None and index == loss + 1:
            # Restart 90 minutes after the loss: _recover seals the orphaned segment.
            clock.at = _at(day, hour, CAPTURE_MINUTE - 1)
            store = EvidenceStore(root, clock=clock, max_raw_bytes=8 * 1024**3, rotate_bytes=2 * 1024**3)
            started = clock.at
        clock.at = _at(day, hour, CAPTURE_MINUTE - 1, 30)
        store.event("stream_lifecycle", dict(state="connected", channel="trades",
                                             subscription=store.subscription(tokens, "trades")))
        for minute in range(shape.minutes):
            count = per_slot + (1 if slot < extra else 0)
            chosen = [cids[(reward_cursor + k) % len(cids)] for k in range(count)]
            reward_cursor += count
            _capture_minute(store, clock, _at(day, hour, CAPTURE_MINUTE + minute), events, shape.trades(day),
                            shape.trade_lead_ms, chosen, trades)
            trades += shape.trades(day)
            slot += 1
        if loss is not None and index == loss:
            store = None  # Power lost: no seal, no run summary.
    clock.at = _at(day, hours[-1], CAPTURE_MINUTE + shape.minutes, 30)
    store.event("run_summary", dict(started_at_utc=started.isoformat(), pid=pid, state="COMPLETED"))
    store.seal()
    compress_closed_segments(store)
    return reward_cursor


def build(root, shape=Shape()):
    """Write ``root``/data (88a + snapshots) and ``root``/releases; return a summary."""
    root = Path(root)
    data_root, release_root = root / "data", root / "releases"
    if data_root.exists() or release_root.exists():
        raise ValueError("fixture_root_must_be_new")
    specs = BUILTIN_SPECS[:shape.cities]
    release_hash = write_release(release_root, specs)
    evidence = data_root / "maker_evidence"
    counts = {}
    with _no_fsync():
        cursor = 0
        for day_index, day in enumerate(DAYS):
            events = [Event(spec, i, day, day_index) for i, spec in enumerate(specs)]
            for event in events:
                event.write_support(data_root, release_hash)
            cursor = _write_day(evidence, day, events, shape, cursor, pid=1000 + day_index)
            counts[day.isoformat()] = dict(conditions=3 * len(events), reward_rows=shape.rewards_per_day(),
                                           trades=len(events) * shape.trades(day) * shape.segments * shape.minutes)
        if shape.trailing_unsealed:
            open_day = SETTLEMENT_DATE + timedelta(days=1)
            clock = Clock(_at(open_day, 0, 5))
            store = EvidenceStore(evidence, clock=clock, max_raw_bytes=8 * 1024**3)
            store.record("discovery", encoded([]), metadata={"http_status": 200})
            # Left open: the live segment at export time.
    return dict(data_root=str(data_root), release_root=str(release_root), shape=asdict(shape),
                days=[d.isoformat() for d in DAYS], calibration_days=[d.isoformat() for d in CALIBRATION_DATES],
                panel_days=[d.isoformat() for d in (*QUOTE_DATES, SETTLEMENT_DATE)],
                cities=[s.id for s in specs], counts=counts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="new fixture root (never a production data root)")
    for field, value in asdict(Shape()).items():
        flag = "--" + field.replace("_", "-")
        if isinstance(value, bool):
            parser.add_argument(flag, action=argparse.BooleanOptionalAction, default=value)
        else:
            parser.add_argument(flag, type=int, default=value)
    args = vars(parser.parse_args(argv))
    root = args.pop("root")
    print(json.dumps(build(root, Shape(**args)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
