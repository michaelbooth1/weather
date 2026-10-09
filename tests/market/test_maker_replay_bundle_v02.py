"""Maker replay v2 W2: bundle v0.2 export of synthetic sealed 88a days; no production paths, clocks or network.

Guards: registration C3 (bundle format v0.2, v0.1 expansion equivalence) and §4/C15 (v0.2 envelope = lead window).
"""
from datetime import timedelta
import hashlib
import json
import socket

import pytest

from maker_core.replay.bundle import BundleError, load_bundle
from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2.compaction import expand
from weather.market.maker_evidence_store import EvidenceStore, encoded
from weather.market import maker_replay_bundle_v02 as v02
from weather.market import maker_replay_night_v02 as night_v02
from weather.market.maker_replay_bundle import ExportReader, export as export_v01
from weather.market.maker_replay_night import night as night_v01
from tests.market.test_maker_replay_bundle import args_for
from tests.market.test_maker_replay_night import LATER, receipt, setup
from tests.market.test_maker_plugin_dry_run import NOW

CID = "0x" + f"{1:064x}"


def subscribe(args, tokens, at, state="connected"):
    when = at
    store = EvidenceStore(args.data_root / "maker_evidence", clock=lambda: when)
    store.event("stream_lifecycle", dict(state=state, channel="trades",
                                         subscription=store.subscription(tokens, "trades")))
    return store


def trade(store, token, cid):
    store.record("trades", encoded(dict(event_type="last_trade_price", asset_id=token, market=cid,
                 timestamp=str(int(store.clock().timestamp() * 1000)), price=".47", size="10", side="SELL")))


def both(tmp_path, args):
    """The frozen v0.1 export and the v0.2 export of the same sealed day."""
    out = args.out
    export_v01(args, now=LATER)
    args.out = tmp_path / "v02"
    summary = v02.export(args, now=LATER)
    return (out / "events.jsonl").read_bytes(), summary


def test_v02_is_the_v01_projection_row_for_row(tmp_path, monkeypatch):
    args, _, _ = args_for(tmp_path, minutes=3, compressed=True)
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network accessed"))
    events, summary = both(tmp_path, args)
    # The sequence-order digest is exactly the v0.1 exporter's events.jsonl.
    assert summary["v01_equivalent"]["sha256"] == hashlib.sha256(events).hexdigest()
    assert summary["v01_equivalent"]["records"] == len(events.splitlines())
    v1 = load_bundle(tmp_path / "bundle")
    bundle = open_stream_bundle(args.out)
    expanded = list(expand(bundle.records(), bundle.coverage_groups))
    assert expanded == sorted(v1.records, key=lambda r: (r.captured_at, r.sequence))
    assert summary["streams"]["coverage"]["records"] < summary["v01_kinds"]["coverage"]["records"]
    assert summary["coverage_groups"] == 1  # never subscribed: one always-unhealthy group
    assert sorted(p.name for p in args.out.iterdir()) == sorted(
        ["bundle.json", "export.json", *(k + ".jsonl" for k in summary["streams"])])
    assert not args.out.with_name(args.out.name + ".partial").exists()
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    args.out = tmp_path / "again"
    v02.export(args, now=LATER + timedelta(days=3))
    assert {p.name: p.read_bytes() for p in args.out.iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "v02").iterdir()}


def test_v02_condition_envelope_is_the_horizon_lead_window(tmp_path):
    """Registration §4 / C15 (owner Q2(a)): v0.2 envelopes are local leads 1..2 of the target; v0.1 keeps the day."""
    from datetime import datetime, timezone
    from maker_core.replay.bundle import time_zone
    from maker_core.replay.payloads import decode
    from maker_core.replay.v2.horizon import lead_window
    from weather.market.maker_replay_universe import registered_time_zones
    args, _, _ = args_for(tmp_path, minutes=3, compressed=True)
    both(tmp_path, args)
    v1 = load_bundle(tmp_path / "bundle")
    zones = {c.condition_id: time_zone(registered_time_zones()[c.market_id]) for c in v1.conditions}
    targets = {r.condition_id: decode(r).market.close_at_utc.astimezone(zones[r.condition_id]).date() - timedelta(days=1)
               for r in v1.records if r.kind == "descriptor"}
    start = datetime.combine(v1.day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    v2 = {c["condition_id"]: c for c in json.loads((args.out / "bundle.json").read_bytes())["conditions"]}
    assert set(v2) == set(targets) and v1.conditions
    for c in v1.conditions:
        assert (c.active_from, c.active_until) == (start, end)  # the frozen v0.1 exporter is unchanged
        low, high = lead_window(zones[c.condition_id], targets[c.condition_id], start, end)
        assert (v2[c.condition_id]["active_from"], v2[c.condition_id]["active_until"]) == (
            low.isoformat(), high.isoformat())


def test_coverage_groups_are_subscriptions_not_sockets(tmp_path):
    # Two subscriptions on one connection: band 1 alone, then bands 2 and 3 subscribed later.
    args, _, _ = args_for(tmp_path)
    store = subscribe(args, ["100", "101"], NOW + timedelta(seconds=5))
    late = NOW + timedelta(minutes=1, seconds=10)
    store.clock = lambda: late
    store.event("stream_lifecycle", dict(state="connected", channel="trades",
                                         subscription=store.subscription(["102", "103", "104", "105"], "trades")))
    store.clock = lambda: NOW + timedelta(minutes=1, seconds=20)
    trade(store, "101", CID)
    store.seal()
    events, summary = both(tmp_path, args)
    assert summary["v01_equivalent"]["sha256"] == hashlib.sha256(events).hexdigest()
    assert summary["coverage_groups"] == 2
    groups = {g.condition_ids for g in open_stream_bundle(args.out).coverage_groups}
    assert groups == {(CID,), ("0x" + f"{2:064x}", "0x" + f"{3:064x}")}


def test_one_group_per_socket_would_be_refused(tmp_path, monkeypatch):
    args, _, _ = args_for(tmp_path)
    store = subscribe(args, ["100", "101"], NOW + timedelta(seconds=5))
    store.seal()
    monkeypatch.setattr(v02.StreamingProjection, "groups",
                        lambda self: {cid: "socket-0" for cid in self.descriptors})
    with pytest.raises(BundleError, match="coverage_group_mismatch"):
        v02.export(args, now=LATER)
    assert not args.out.exists() and not args.out.with_name(args.out.name + ".partial").exists()


@pytest.mark.parametrize("fault", ["open_day", "unsealed", "changed", "byte_cap", "overlap", "validation"])
def test_refusal_leaves_source_untouched_and_no_bundle_or_partial(tmp_path, monkeypatch, fault):
    args, _, segment = args_for(tmp_path)
    now = LATER
    if fault == "open_day":
        now = NOW
    elif fault == "unsealed":
        (segment / "manifest.json").unlink()
    elif fault == "changed":
        monkeypatch.setattr(ExportReader, "recheck", lambda self: (_ for _ in ()).throw(ValueError("changed")))
    elif fault == "byte_cap":
        args.max_output_bytes = 10
    elif fault == "overlap":
        args.out = args.data_root / "bad"
    else:
        monkeypatch.setattr(v02, "validate", lambda *a, **k: (_ for _ in ()).throw(BundleError("bad")))
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    with pytest.raises(Exception):
        v02.export(args, now=now)
    assert not args.out.exists() and not args.out.with_name(args.out.name + ".partial").exists()
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}


def test_night_v02_seals_a_streamed_bundle_with_the_v01_gaps_and_per_kind_bytes(tmp_path):
    args, _ = setup(tmp_path, multi=True)
    v1 = night_v01(args, now=LATER)
    (tmp_path / "w").mkdir()
    other, _ = setup(tmp_path / "w", multi=True)
    report = night_v02.export_day(other, "panel", now=LATER)
    assert report["status"] == "SEALED" and report["format"] == "v0.2"
    assert (other.out / "panel-v02-ledger.jsonl").is_file() and not (other.out / "panel-ledger.jsonl").exists()
    bundle = report["bundle"]
    assert bundle["gaps"] == v1["bundle"]["gaps"] and bundle["conditions"] == v1["bundle"]["conditions"]
    assert bundle["v01_records"] == v1["bundle"]["records"]
    assert bundle["captured_band_cities"] == v1["bundle"]["captured_band_cities"] == ["chicago", "nyc"]
    assert set(bundle["kinds"]) == {k for k in bundle["v01_kinds"]}
    assert bundle["bytes"] == sum(p.stat().st_size for p in (other.out / other.day / "bundle").iterdir())
    assert report["peak_memory_bytes"] > 0 and report["runtime_seconds"] >= 0
    assert receipt(other)["status"] == "SEALED"
    with pytest.raises(ValueError, match="day_already"):
        night_v02.export_day(other, "panel", now=LATER)


def test_night_v02_calibration_keeps_hazard_kinds_and_refusal_keeps_a_receipt(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, multi=True)
    with pytest.raises(ValueError, match="calibration_dates"):
        night_v02.export_day(args, "calibration", now=LATER)
    monkeypatch.setattr(night_v02, "CALIBRATION_DATES", (NOW.date(),))
    report = night_v02.export_day(args, "calibration", now=LATER)
    assert set(report["bundle"]["kinds"]) <= {"descriptor", "coverage", "trade"}
    (tmp_path / "r").mkdir()
    refused, _ = setup(tmp_path / "r")
    refused.max_output_bytes = 100
    with pytest.raises(ValueError):
        night_v02.export_day(refused, "panel", now=LATER)
    assert receipt(refused)["status"] == "REFUSED"
    assert not (refused.out / refused.day / "bundle").exists()
    assert not (refused.out / refused.day / "pending").exists()


def test_twelve_city_capture_window_matches_v01_with_one_group_per_subscription(tmp_path):
    from datetime import date, datetime, timezone
    from types import SimpleNamespace
    from tools.research.maker_replay_v2.capture170 import write
    from weather.market.market_registry import BUILTIN_SPECS
    info = write(tmp_path / "in", date(2026, 9, 27), minutes=3, trades=20000, outages=0)
    assert info["fixture"]["union"] == 170 and info["fixture"]["markets"] == 12
    args = SimpleNamespace(date="2026-09-27", markets=[s.id for s in BUILTIN_SPECS], data_root=tmp_path / "in",
                           out=tmp_path / "v01", max_seconds=600, max_input_bytes=1024**3,
                           max_output_bytes=1024**3, max_records=10**6, carry_bundle=[], release_root=None, kinds=None)
    later = datetime(2026, 10, 4, tzinfo=timezone.utc)
    export_v01(args, now=later)
    events = (tmp_path / "v01" / "events.jsonl").read_bytes()
    args.out = tmp_path / "v02"
    summary = v02.export(args, now=later)
    assert summary["v01_equivalent"]["sha256"] == hashlib.sha256(events).hexdigest()
    # The four opening subscriptions; prints renew them, so coverage rows are not all identical.
    assert summary["coverage_groups"] == 4 and summary["counts"]["trade"] > 0
    assert summary["streams"]["plugin_input"]["records"] == summary["counts"]["plugin_input"]


def test_cli_module_hash_and_bundle(tmp_path, capsys):
    assert night_v02.main(["module-hash"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert set(value) == {"module_sha256", "files"}
