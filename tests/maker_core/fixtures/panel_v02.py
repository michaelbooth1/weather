"""Fictional v0.2 panel and calibration bundles for the maker replay v2 universe rule (U1, W7).

Every value is invented; no captured market, panel or settlement row is read. Dates are the real panel
and calibration dates (the rule is keyed by them), the data are not.

Markets are built-in registry IDs (A-defender M5), with their registry timezones and slug prefixes
pinned by ``tests/market/test_maker_replay_universe_v02.py``:

- ``austin`` (America/Chicago, local midnight 05:00Z in CDT): its target 2026-10-03 event is the
  owner-excluded market-date. It is discovered at local midnight 10-01 (horizon 2), rolls to 1 and then
  0 at local midnight, which coincides with the 05:00Z maintenance start.
- ``toronto`` (America/Toronto, local midnight 04:00Z in EDT, outside maintenance): the horizon roll
  and stale-descriptor minutes are tested on it.
- ``dallas`` (America/Chicago) is optional: same close time as Austin, so a close-time-only key would
  wrongly exclude it.

A capture every ``step`` minutes, ``offset`` minutes and 20 seconds past the grid, projects every event whose local
horizon is 0..2, like the exporter: a descriptor on first sight in the UTC day and on every horizon
change. ``full=True`` adds what the engine needs to quote (books every capture, terms, outcome views,
info events, one coverage group per condition, prints and settlements the next UTC day at 11:00Z).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from maker_core.contracts import MarketDescriptor, OutcomeView, SettlementFact
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.quoting.policy import Book, RewardTerms
from maker_core.replay.bundle import sha256
from maker_core.replay.bundle_v02 import FORMAT_V02
from maker_core.replay.v2.panel import CALIBRATION_DATES, QUOTE_DATES, SETTLEMENT_ONLY_DATES

ZONES = {"austin": "America/Chicago", "toronto": "America/Toronto", "dallas": "America/Chicago"}
SLUGS = {m: f"highest-temperature-in-{m}-on" for m in ZONES}
PANEL_DAYS = QUOTE_DATES + SETTLEMENT_ONLY_DATES
ALL_DAYS = CALIBRATION_DATES + PANEL_DAYS
AUSTIN_TARGET = date(2026, 10, 3)
DOMAIN = "fictional-weather"
SOURCE = {"fixture": "0" * 64}


def cid_of(market, target, band, event_suffix=""):
    return "0x" + hashlib.sha256(f"{market}|{target}|{band}|{event_suffix}".encode()).hexdigest()[:40]


def slug_of(market, target):
    return f"{SLUGS[market]}-{target.strftime('%B').lower()}-{target.day}-{target.year}"


def close_of(market, target):
    return datetime.combine(target + timedelta(days=1), time(), tzinfo=ZoneInfo(ZONES[market])).astimezone(timezone.utc)


class Panel:
    def __init__(self, markets=("austin", "toronto"), *, bands=2, step=10, offset=3, full=False,
                 capture_minutes=None, second_austin_event=False, omit=frozenset(), close_override=None):
        self.markets, self.bands, self.step, self.offset, self.full = markets, bands, step, offset, full
        self.capture_minutes = capture_minutes  # None: the whole day
        self.second_austin_event = second_austin_event
        self.omit = frozenset(omit)  # condition IDs left out of every bundle (the "records deleted" twin)
        self.close_override = dict(close_override or {})  # condition ID -> descriptor close_at_utc

    # -- universe -------------------------------------------------------------------------------------
    def events(self, market, target):
        out = [(slug_of(market, target), "")]
        if self.second_austin_event and market == "austin" and target == AUSTIN_TARGET:
            out.append((slug_of(market, target) + "-b", "b"))  # a second event, same market-date key
        return out

    def conditions_at(self, at):
        """(market, target, event_id, condition_id, horizon) projected at ``at``."""
        out = []
        for market in self.markets:
            local = at.astimezone(ZoneInfo(ZONES[market])).date()
            for horizon in range(3):
                target = local + timedelta(days=horizon)
                for event_id, suffix in self.events(market, target):
                    for band in range(self.bands):
                        cid = cid_of(market, target, band, suffix)
                        if cid not in self.omit:
                            out.append((market, target, event_id, cid, horizon))
        return sorted(out, key=lambda c: c[3])

    def captures(self, day):
        start = datetime.combine(day, time(), tzinfo=timezone.utc)
        minutes = range(1440) if self.capture_minutes is None else self.capture_minutes
        return [start + timedelta(minutes=m + self.offset, seconds=20)
                for m in minutes if m % self.step == 0 and m + self.offset < 1440]

    def inventory(self, days):
        rows = {}
        for day in days:
            for at in self.captures(day):
                for market, target, _, cid, _ in self.conditions_at(at):
                    rows[cid] = dict(condition_id=cid, market_id=market, domain_id=DOMAIN,
                                     target_date=target.isoformat(), local_timezone=ZONES[market])
        return [rows[c] for c in sorted(rows)]

    def austin_excluded(self, days):
        return sorted(r["condition_id"] for r in self.inventory(days)
                      if r["market_id"] == "austin" and r["target_date"] == AUSTIN_TARGET.isoformat())

    # -- rows -----------------------------------------------------------------------------------------
    def rows(self, day):
        rows, last, conditions, targets = [], {}, {}, {}

        def add(at, kind, payload, *, cid=None, group=None):
            value = dict(sequence=len(rows), captured_at=at.isoformat(), kind=kind, payload=plain(payload),
                         payload_sha256=sha256(canonical_bytes(payload)), source_hashes=SOURCE)
            value["group_id" if group else "condition_id"] = group or cid
            rows.append(value)

        captures = self.captures(day)
        for i, at in enumerate(captures):
            for market, target, event_id, cid, horizon in self.conditions_at(at):
                conditions[cid] = market
                targets[cid] = target
                if last.get(cid) != horizon:
                    last[cid] = horizon
                    add(at, "descriptor", self.descriptor(market, target, event_id, cid, horizon), cid=cid)
                if not self.full:
                    continue
                if i % 30 == 0 or (cid, "terms") not in last:
                    last[(cid, "terms")] = True
                    add(at, "terms", RewardTerms(at, D(20), D("3.5"), D(100)), cid=cid)
                    add(at, "outcome_view", dict(available=True, value=OutcomeView(
                        cid, .5, .015, None, at, at + timedelta(hours=1), sha256(f"{cid}{at}".encode()),
                        "synthetic", "none")), cid=cid)
                if (cid, "info") not in last:
                    last[(cid, "info")] = True
                    add(at, "info_event", {"events": []}, cid=cid)
                mid = D(".5") + (D(".01") if (i // 7) % 2 else 0)
                add(at, "book", Book(at, ((mid - D(".01"), D(75)),), ((mid + D(".01"), D(75)),),
                                     ((1 - mid - D(".01"), D(75)),), ((1 - mid + D(".01"), D(75)),)), cid=cid)
                add(at, "coverage", dict(trade_stream_ok=True, valid_until_utc=at + timedelta(seconds=60)),
                    group="g-" + cid)
                if i % 37 == 5:
                    print_at = at + timedelta(seconds=2)
                    add(print_at, "trade", dict(trade_id=f"t-{cid[:10]}-{i}", outcome="YES", price=".40",
                                                size="10", traded_at_utc=print_at.isoformat(),
                                                aggressor_side="SELL"), cid=cid)
        if self.full:
            settle_at = datetime.combine(day, time(11), tzinfo=timezone.utc)
            for cid, market in sorted(conditions.items()):
                if targets[cid] + timedelta(days=1) == day:
                    add(settle_at, "settlement", SettlementFact(cid, 1.0 if cid.endswith(("0", "2", "4", "6", "8"))
                                                                else 0.0, settle_at, SOURCE, "reconciled"), cid=cid)
        rows.sort(key=lambda r: (r["captured_at"], r["sequence"]))
        return rows, conditions

    def descriptor(self, market, target, event_id, cid, horizon):
        close = self.close_override.get(cid, close_of(market, target))
        desc = MarketDescriptor(DOMAIN, event_id, cid, {"YES": cid + "-y", "NO": cid + "-n"}, D(".01"), D(20),
                                None, close, close + timedelta(minutes=1), "F", "fixture", SOURCE)
        return dict(market=plain(desc), horizon_days=horizon, exposure_factors={f"market:{market}": "1"})

    # -- files ----------------------------------------------------------------------------------------
    def write(self, folder: Path, day: date, *, provenance="synthetic") -> Path:
        """One v0.2 bundle folder for ``day``; returns it."""
        folder.mkdir(parents=True)
        rows, conditions = self.rows(day)
        start = datetime.combine(day, time(), tzinfo=timezone.utc)
        streams = []
        for kind in sorted({r["kind"] for r in rows}):
            raw = b"".join(canonical_bytes(r) for r in rows if r["kind"] == kind)
            (folder / f"{kind}.jsonl").write_bytes(raw)
            streams.append(dict(path=f"{kind}.jsonl", sha256=sha256(raw), bytes=len(raw),
                                records=sum(1 for r in rows if r["kind"] == kind)))
        groups = [dict(group_id="g-" + cid, condition_ids=[cid]) for cid in sorted(conditions)
                  if any(r.get("group_id") == "g-" + cid for r in rows)]
        manifest = dict(format=FORMAT_V02, day=day.isoformat(), sealed_at=(start + timedelta(days=1)).isoformat(),
                        provenance=provenance, streams=streams, coverage_groups=groups,
                        conditions=[dict(condition_id=cid, market_id=conditions[cid], domain_id=DOMAIN,
                                         active_from=start.isoformat(),
                                         active_until=(start + timedelta(days=1)).isoformat())
                                    for cid in sorted(conditions)])
        (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
        return folder

    def write_export(self, parent: Path, day: date, *, kind="panel", provenance="captured") -> Path:
        """``maker_replay_night_v02``'s day-folder layout: ``<day>/bundle/`` and ``<day>/receipt.json``."""
        root = parent / day.isoformat()
        bundle = self.write(root / "bundle", day, provenance=provenance)
        files = {}
        for path in sorted(bundle.iterdir()):
            raw = path.read_bytes()
            files[path.name] = dict(bytes=len(raw), sha256=sha256(raw))
        receipt = dict(day=day.isoformat(), kind=kind, format="v0.2", status="SEALED",
                       module_sha256=sha256(b"fictional-exporter-closure"),
                       bundle=dict(format="v0.2", files=files,
                                   v01_equivalent=dict(sha256=sha256(f"v01-{day}-{kind}".encode()),
                                                       bytes=1, records=1)))
        (root / "receipt.json").write_bytes(json.dumps(receipt, sort_keys=True).encode())
        return root
