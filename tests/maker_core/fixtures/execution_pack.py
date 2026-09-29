"""Synthetic execution-pack inputs; no retained capture, ledger or wallet reads."""
from datetime import datetime, timedelta, timezone
import json

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization, ceilings
from maker_core.replay.bundle import load_bundle, sha256
from maker_core.replay.calibration import CALIBRATION_DATES, calibrate
from maker_core.replay.execution_manifest import QUOTE_DATES, SETTLEMENT_DATE, build_manifest
from maker_core.replay.pack_io import write_json
from .replay_scenario import Scenario
from .replay_bundle import seal


def calibration_days(root, minutes=480, markets=("a",), occupied=10):
    bundles = []
    for day in CALIBRATION_DATES:
        scenario = Scenario(day, markets=markets, minutes=minutes)
        scenario.records = [r for r in scenario.records if r["kind"] == "descriptor"]
        # O(n) fixture construction, independent of the calibration implementation.
        def add(market, kind, seconds, payload):
            scenario.records.append(dict(sequence=len(scenario.records), captured_at=scenario.at(seconds).isoformat(),
                condition_id=scenario.cid(market), kind=kind, payload=payload,
                payload_sha256=sha256(canonical_bytes(payload)), source_hashes={"fictional": "0"*64}))
        for market in markets:
            for seconds in range(0, minutes*60, 30):
                add(market, "coverage", seconds, dict(trade_stream_ok=True, valid_until_utc=scenario.at(seconds+30).isoformat()))
            for minute in range(min(occupied, minutes)):
                add(market, "trade", minute*60+1, dict(trade_id=f"{day}-{minute}", outcome="YES", price=".01",
                    size=".1", aggressor_side="BUY", traded_at_utc=scenario.at(minute*60+1).isoformat()))
        bundles.append(scenario.bundle(root/day.isoformat()))
    return tuple(bundles)


# Fictional resource counts sized so the rule admits the fixture panel.
MEASURED = dict(input_bytes=16*1024**2, records=20000, engine_events=50000, decisions_spans=50000,
                peak_memory_bytes=64*1024**2, runtime_seconds=1.0)


def measurement(measured=MEASURED):
    return dict(format=ceilings.FORMAT, date=ceilings.MEASUREMENT_DATE.isoformat(), measured=dict(measured),
                detail={}, measured_at="2026-09-30T08:00:00+00:00", derived=ceilings.derive(dict(measured)))


def pack(root, measured=MEASURED):
    calibration_root, panel_root = root/"calibration-bundles", root/"panel"
    calibration_root.mkdir()
    panel_root.mkdir()
    cb = calibration_days(calibration_root, minutes=2, occupied=1)
    quote_markets = root/"quote-markets.json"
    quote_hash = write_json(quote_markets, ["a"])
    calibration = calibrate(cb, ["a"])
    calibration["quote_inventory_sha256"] = quote_hash
    calibration_path = root/"calibration.json"
    calibration_hash = write_json(calibration_path, calibration)
    bundles, inventory = [], []
    for day in (*QUOTE_DATES, SETTLEMENT_DATE):
        scenario = Scenario(day, markets=("a",), minutes=600)
        for r in scenario.records:
            if r["kind"] == "descriptor":
                r["payload"]["horizon_days"] = 1
                r["payload_sha256"] = sha256(canonical_bytes(r["payload"]))
        bundles.append(scenario.bundle(panel_root/day.isoformat()))
        inventory.append(dict(condition_id=scenario.cid("a"), market_id="a", domain_id="fictional",
                              target_date=(day+timedelta(days=1)).isoformat(), local_timezone="UTC"))
    inventory.sort(key=lambda r: r["condition_id"])
    universe_path = root/"universe.json"
    inventory_hash = write_json(universe_path, inventory)
    measurement_path = root/"ceiling-measurement.json"
    measurement_hash = write_json(measurement_path, measurement(measured))
    paths = dict(decision_log=root/"DECISION_LOG.md", frozen_protocol=root/"protocol.md",
                 execution_addendum=root/"addendum.md", clarification=root/"clarification.md",
                 clarification_2=root/"clarification-2.md", calibration_path=calibration_path,
                 inventory_path=universe_path, quote_inventory_path=quote_markets, measurement_path=measurement_path)
    decision = dict(authorization_id="maker-replay-2026-10-15-v2", owner="michaelbooth1",
        signed_at="2026-09-29T12:00:00Z", scoring_date="2026-10-15", expires_at="2026-11-01T04:00:00Z")
    for field, name in (("protocol_sha256", "frozen_protocol"), ("addendum_sha256", "execution_addendum"),
                        ("clarification_sha256", "clarification"), ("clarification_2_sha256", "clarification_2")):
        raw = b"# FICTIONAL TEST DOCUMENT ONLY\n" + name.encode() + b"\n"
        paths[name].write_bytes(raw)
        decision[field] = sha256(raw)
    row = "| 2026-09-29 | APPROVE_MAKER_REPLAY | offline replay only | `"+json.dumps(decision)+"` | — |\n"
    paths["decision_log"].write_text(authorization.LOG_HEADER+"\n| --- | --- | --- | --- | --- |\n"+row, encoding="utf8")
    doc = build_manifest(bundles, cb, calibration, inventory, decision, measurement(measured),
                         calibration_sha256=calibration_hash, inventory_sha256=inventory_hash,
                         quote_inventory_sha256=quote_hash, measurement_sha256=measurement_hash)
    manifest = root/"manifest.json"
    key = write_json(manifest, doc)
    return doc, tuple(bundles), cb, paths, manifest, key
