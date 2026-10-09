"""The EXPLORATORY_NOT_COUNTED <= 2026-09-26 shadow: guards A, B and C and the aggregate refusal.

Guards: contract/exploratory-le0926 (EXPLORATORY-SHADOW-HOST-SPEC §1.1: day window and panel gate, forbidden
date path components, output placement and labels, cutoff 2026-09-27T00:00Z exclusive in verify and in the
driver, descriptor-only inventory, declared hazard grid, no post-cutoff hazard derivation, aggregate identifier
refusal, PowerShell twin date refusal first).

Every value here is fictional: invented condition ids, a built-in market slug shape, fictional books and trades.
No captured data is read.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from maker_core.contracts import MarketDescriptor, SettlementFact
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.replay.bundle_v02 import FORMAT_V02
from maker_core.replay.fill_model import Fill
from maker_core.replay.v2.compaction import compact
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import DaySource, record_from_row, run_plan
from tools.research.maker_replay_v2 import exploratory_le0926 as ex
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.sources import materialize

UTC = timezone.utc
DAY = date(2026, 9, 26)
CUTOFF = datetime(2026, 9, 27, tzinfo=UTC)
FICTIONAL = {"fixture": "0" * 64}
NY = ZoneInfo("America/New_York")
REPO = Path(ex.__file__).resolve().parents[3]


# -- fictional fixtures -----------------------------------------------------------------------------------------
def slug(target, city="nyc"):
    return f"highest-temperature-in-{city}-on-{target.strftime('%B').lower()}-{target.day}-{target.year}"


def close_of(target):
    return datetime.combine(target + timedelta(days=1), datetime.min.time(), tzinfo=NY).astimezone(UTC)


def cid_of(name):
    return "0x" + hashlib.sha256(f"exploratory-fixture|{name}".encode()).hexdigest()[:40]


def descriptor_payload(cid, target, captured, city="nyc"):
    close = close_of(target)
    market = MarketDescriptor("fictional", slug(target, city), cid, {"YES": cid + "-y", "NO": cid + "-n"}, D(".01"),
                              D(5), slug(target, city), close, close + timedelta(minutes=1), "F", "fixture",
                              FICTIONAL, "partition")
    horizon = (target - captured.astimezone(NY).date()).days
    return plain(dict(market=market, horizon_days=horizon))


class Rows:
    """A tiny exporter-shaped v0.1 row list for one UTC day."""

    def __init__(self, day=DAY):
        self.day = day
        self.start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        self.rows, self.conditions = [], {}

    def add(self, at, cid, kind, payload):
        payload = plain(payload)
        self.rows.append(dict(sequence=len(self.rows), captured_at=at.isoformat(), condition_id=cid, kind=kind,
                              payload=payload, payload_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest(),
                              source_hashes=FICTIONAL))

    def condition(self, cid, target, city="nyc", at=None):
        at = at or self.start + timedelta(hours=10)
        self.conditions[cid] = city
        self.add(at, cid, "descriptor", descriptor_payload(cid, target, at, city))

    def condition_rows(self):
        end = self.start + timedelta(days=1)
        return [dict(condition_id=c, market_id=m, domain_id="fictional", active_from=self.start.isoformat(),
                     active_until=end.isoformat()) for c, m in sorted(self.conditions.items())]


def mini(day=DAY):
    """One NYC condition for the day's own event: descriptor, book, trade and a timed snapshot row."""
    r = Rows(day)
    a = cid_of(f"a-{day}")
    t0 = r.start + timedelta(hours=10)
    r.condition(a, day)
    r.add(t0 + timedelta(seconds=5), a, "book", dict(as_of_utc=(t0 + timedelta(seconds=5)).isoformat(),
                                                     yes_bids=[["0.40", "10"]], yes_asks=[["0.42", "10"]],
                                                     no_bids=[["0.58", "10"]], no_asks=[["0.60", "10"]]))
    r.add(t0 + timedelta(minutes=1), a, "trade", dict(trade_id="t-fixture-1", outcome="YES", price="0.41", size="3",
                                                      traded_at_utc=(t0 + timedelta(seconds=59)).isoformat(),
                                                      aggressor_side="BUY"))
    r.add(t0 + timedelta(minutes=2), a, "plugin_input",
          dict(source="snapshots", original_captured_at=t0.isoformat(),
               record=dict(captured_at_utc=t0.isoformat(), event_slug=slug(day), band=0)))
    return r, a


def write_bundle(root, day, conditions, groups, rows, *, receipt=None):
    folder = Path(root) / day.isoformat()
    bundle = folder / "bundle"
    bundle.mkdir(parents=True)
    by_kind = {}
    for value in rows:
        by_kind.setdefault(value["kind"], []).append(value)
    streams = []
    for kind, items in sorted(by_kind.items()):
        items.sort(key=lambda v: (datetime.fromisoformat(v["captured_at"]), v["sequence"]))
        raw = b"".join(canonical_bytes(v) for v in items)
        (bundle / f"{kind}.jsonl").write_bytes(raw)
        streams.append(dict(path=f"{kind}.jsonl", sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                            records=len(items)))
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    manifest = dict(format=FORMAT_V02, day=day.isoformat(), sealed_at=end.isoformat(), provenance="synthetic",
                    conditions=conditions, coverage_groups=groups, streams=streams)
    (bundle / "bundle.json").write_bytes(canonical_bytes(manifest))
    receipt = receipt if receipt is not None else dict(day=day.isoformat(), status="SEALED", module_sha256="a" * 64,
                                                       reader_coverage={"rows": 1})
    (folder / "receipt.json").write_bytes(canonical_bytes(receipt))
    return folder


def write_mini(root, r, **kw):
    return write_bundle(root, r.day, r.condition_rows(), [], r.rows, **kw)


def builtin_dense(day=DAY, *, minutes=20, trades=600):
    """W2's dense fictional day relabelled as the built-in NYC market (descriptor slug, close, horizon 0)."""
    dd = DenseDay(day, union=12, trades=trades, start_minute=600, minutes=minutes)
    event = slug(day)
    described, rows = set(), []
    for value in dd.rows():
        value = dict(value)
        captured = datetime.fromisoformat(value["captured_at"])
        if value["kind"] == "descriptor":
            if value["condition_id"] in described:
                continue  # the fixture's mid-window horizon roll would change the bound target
            described.add(value["condition_id"])
            payload = dict(value["payload"])
            payload.update(descriptor_payload(value["condition_id"], day, captured))
            value["payload"] = payload
        elif value["kind"] == "plugin_input":
            value["payload"] = dict(source="snapshots", original_captured_at=captured.isoformat(),
                                    record=dict(captured_at_utc=captured.isoformat(), event_slug=event))
        else:
            rows.append(value)
            continue
        value["payload_sha256"] = hashlib.sha256(canonical_bytes(value["payload"])).hexdigest()
        rows.append(value)
    conditions = [dict(c, market_id="nyc") for c in dd.conditions()]
    return dd, conditions, list(compact(rows, dd.groups))


@pytest.fixture
def stage(tmp_path):
    root = tmp_path / "stage"
    for name in ("bundles", "receipts", "runs"):
        (root / name).mkdir(parents=True)
    return root


def run_cli(capsys, *argv):
    code = ex.main([str(a) for a in argv])
    lines = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(lines[-1])


def verify(capsys, stage, *days, out="EXPLORATORY-verify.json"):
    return run_cli(capsys, "verify", "--bundle-root", stage / "bundles", "--day", *days,
                   "--out", stage / "receipts" / out)


# -- guard A ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("day", ["2026-09-27", "2026-09-30", "2026-10-15", "2026-09-22", "20260926", "2026-9-26",
                                 "2026-09-26T00:00"])
def test_guard_a_refuses_days_outside_window_before_opening_anything(capsys, tmp_path, day):
    out = tmp_path / "EXPLORATORY-verify.json"
    code, result = run_cli(capsys, "verify", "--bundle-root", tmp_path / "missing", "--day", day, "--out", out)
    assert code == ex.EXIT_REFUSED and result["status"] == "REFUSED"
    assert not out.exists() and not (tmp_path / "missing").exists()


def test_guard_a_consults_the_panel_gate(monkeypatch):
    monkeypatch.setattr(ex.export_gate, "gated", lambda day: True)
    with pytest.raises(ex.Refusal) as caught:
        ex.check_day("2026-09-26")
    assert caught.value.code == "panel_gated_day"


def test_guard_a_refuses_duplicate_days(tmp_path):
    with pytest.raises(ex.Refusal) as caught:
        ex.guard_a(["2026-09-26", "2026-09-26"], inputs=[tmp_path], outputs=[])
    assert caught.value.code == "duplicate_day"


@pytest.mark.parametrize("component", ["2026-09-28", "export-2026-10-03", "20260929", "2026-09-30"])
def test_guard_a_refuses_forbidden_date_path_components(capsys, tmp_path, component):
    root = tmp_path / component / "bundles"
    root.mkdir(parents=True)
    code, result = run_cli(capsys, "verify", "--bundle-root", root, "--day", "2026-09-26",
                           "--out", tmp_path / "EXPLORATORY-verify.json")
    assert (code, result["reason"]) == (ex.EXIT_REFUSED, "forbidden_date_path_component")
    assert not (tmp_path / "EXPLORATORY-verify.json").exists()


def test_guard_a_allows_window_dates_in_paths(tmp_path):
    root = tmp_path / "2026-09-26" / "bundles"
    root.mkdir(parents=True)
    assert ex.guard_a(["2026-09-26"], inputs=[root], outputs=[tmp_path / "EXPLORATORY-v.json"]) == [DAY]


@pytest.mark.parametrize("where, code", [
    ("data", "output_inside_data_tree"),
    ("Data", "output_inside_data_tree"),
    ("repo", "output_inside_repository_or_forbidden_root"),
    ("forbid", "output_inside_repository_or_forbidden_root"),
    ("ledger", "output_inside_nightly_export_root"),
    ("input", "output_overlaps_input"),
    ("unlabelled", "output_not_labelled_exploratory"),
    ("exists", "output_exists"),
    ("noparent", "output_parent_missing"),
])
def test_guard_a_refuses_output_placement(capsys, tmp_path, where, code):
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    forbid = tmp_path / "prod"
    forbid.mkdir()
    out = {"data": tmp_path / "data" / "EXPLORATORY-verify.json",
           "Data": tmp_path / "x" / "Data" / "EXPLORATORY-verify.json",
           "repo": REPO / "EXPLORATORY-verify.json",
           "forbid": forbid / "EXPLORATORY-verify.json",
           "ledger": tmp_path / "nightly" / "EXPLORATORY-verify.json",
           "input": bundles / "EXPLORATORY-verify.json",
           "unlabelled": tmp_path / "verify.json",
           "exists": tmp_path / "EXPLORATORY-exists.json",
           "noparent": tmp_path / "nope" / "EXPLORATORY-verify.json"}[where]
    if where in ("data", "Data", "ledger"):
        out.parent.mkdir(parents=True)
    if where == "ledger":
        (out.parent / "panel-v02-ledger.jsonl").write_text("{}\n")
    if where == "exists":
        out.write_text("{}")
    before = out.exists()
    code_, result = run_cli(capsys, "verify", "--bundle-root", bundles, "--day", "2026-09-26", "--out", out,
                            "--forbid-root", forbid)
    assert (code_, result["reason"]) == (ex.EXIT_REFUSED, code)
    assert out.exists() == before


def test_guard_a_refuses_input_inside_a_data_tree(capsys, tmp_path):
    root = tmp_path / "data" / "maker_evidence"
    root.mkdir(parents=True)
    code, result = run_cli(capsys, "verify", "--bundle-root", root, "--day", "2026-09-26",
                           "--out", tmp_path / "EXPLORATORY-verify.json")
    assert (code, result["reason"]) == (ex.EXIT_REFUSED, "input_inside_data_tree")


def test_refusal_result_file_is_written_only_when_its_own_path_passes(capsys, stage):
    result = stage / "receipts" / "EXPLORATORY-verify.result.json"
    code, _ = run_cli(capsys, "verify", "--bundle-root", stage / "bundles", "--day", "2026-09-27",
                      "--out", stage / "receipts" / "EXPLORATORY-verify.json", "--result", result)
    assert code == ex.EXIT_REFUSED
    assert json.loads(result.read_text())["reason"] == "day_outside_exploratory_window"
    bad = stage / "receipts" / "2026-09-30-EXPLORATORY.json"
    run_cli(capsys, "verify", "--bundle-root", stage / "bundles", "--day", "2026-09-27",
            "--out", stage / "receipts" / "EXPLORATORY-v2.json", "--result", bad)
    assert not bad.exists()


# -- guard B ----------------------------------------------------------------------------------------------------
def test_verify_passes_a_clean_fictional_day(capsys, stage):
    r, _ = mini()
    write_mini(stage / "bundles", r)
    code, result = verify(capsys, stage, "2026-09-26")
    assert (code, result["status"], result["breaches"]) == (0, "PASS", 0)
    report = json.loads((stage / "receipts" / "EXPLORATORY-verify.json").read_text())
    assert report["label"] == ex.LABEL and report["counted"] is False
    assert report["days_used"] == ["2026-09-26"] and report["breaches"] == []
    assert report["per_day"]["2026-09-26"]["kinds"]["trade"]["count"] == 1


def _breach_codes(stage):
    report = json.loads((stage / "receipts" / "EXPLORATORY-verify.json").read_text())
    return {b["code"] for b in report["breaches"]}


def _late(r):
    return r.start + timedelta(hours=23, minutes=59, seconds=59)


MUTATIONS = {
    "settlement_untimestamped": lambda r, a: r.add(_late(r), a, "settlement", dict(
        condition_id=a, p_yes=1.0, source_hashes=FICTIONAL, reconciliation_status="reconciled")),
    "settlement_at_or_after_cutoff": lambda r, a: r.add(_late(r), a, "settlement", plain(SettlementFact(
        a, 1.0, CUTOFF, FICTIONAL, "reconciled"))),
    "trade_at_or_after_cutoff": lambda r, a: r.add(_late(r), a, "trade", dict(
        trade_id="t-late", outcome="YES", price="0.4", size="1", traded_at_utc=CUTOFF.isoformat(),
        aggressor_side="BUY")),
    "trade_untimestamped": lambda r, a: r.add(_late(r), a, "trade", dict(
        trade_id="t-none", outcome="YES", price="0.4", size="1", aggressor_side="BUY")),
    "plugin_input_untimestamped": lambda r, a: r.add(_late(r), a, "plugin_input", dict(
        source="snapshots", record=dict(captured_at_utc=_late(r).isoformat(), event_slug=slug(DAY)))),
    "plugin_record_untimestamped": lambda r, a: r.add(_late(r), a, "plugin_input", dict(
        source="snapshots", original_captured_at=_late(r).isoformat(), record=dict(event_slug=slug(DAY)))),
    "plugin_record_at_or_after_cutoff": lambda r, a: r.add(_late(r), a, "plugin_input", dict(
        source="bulletins", original_captured_at=_late(r).isoformat(), record=dict(fetched_at=CUTOFF.isoformat()))),
    "plugin_input_unknown_source": lambda r, a: r.add(_late(r), a, "plugin_input", dict(
        source="fixture", original_captured_at=_late(r).isoformat(), record={})),
    "ledger_row_for_event_after_last_day": lambda r, a: r.add(_late(r), a, "plugin_input", dict(
        source="ledger_rows", original_captured_at=_late(r).isoformat(),
        record=dict(recorded_at_utc=_late(r).isoformat(), event_slug=slug(date(2026, 9, 27))))),
    "book_at_or_after_cutoff": lambda r, a: r.add(_late(r), a, "book", dict(
        as_of_utc=CUTOFF.isoformat(), yes_bids=[], yes_asks=[], no_bids=[], no_asks=[])),
}


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_verify_breaches_on_cutoff_and_untimestamped_rows(capsys, stage, code):
    r, a = mini()
    MUTATIONS[code](r, a)
    write_mini(stage / "bundles", r)
    exit_code, result = verify(capsys, stage, "2026-09-26")
    assert (exit_code, result["status"]) == (ex.EXIT_BREACH, "BREACH")
    assert code in _breach_codes(stage)


def test_verify_allows_descriptors_to_09_28_but_no_settlement_after_09_26(capsys, stage):
    r, _ = mini()
    b, c = cid_of("b"), cid_of("c")
    r.condition(b, date(2026, 9, 27))
    r.condition(c, date(2026, 9, 28))
    write_mini(stage / "bundles", r)
    assert verify(capsys, stage, "2026-09-26")[0] == 0
    shutil.rmtree(stage / "bundles" / "2026-09-26")
    (stage / "receipts" / "EXPLORATORY-verify.json").unlink()
    r.add(_late(r), b, "settlement", plain(SettlementFact(b, 0.0, _late(r), FICTIONAL, "reconciled")))
    write_mini(stage / "bundles", r)
    assert verify(capsys, stage, "2026-09-26")[0] == ex.EXIT_BREACH
    assert "settlement_for_event_after_last_day" in _breach_codes(stage)


def test_verify_breaches_on_a_descriptor_after_09_28(capsys, stage):
    r, _ = mini()
    r.condition(cid_of("d"), date(2026, 9, 29))
    write_mini(stage / "bundles", r)
    assert verify(capsys, stage, "2026-09-26")[0] == ex.EXIT_BREACH
    assert "descriptor_target_after_limit" in _breach_codes(stage)


def test_verify_breaches_on_nonzero_exporter_untimestamped_coverage(capsys, stage):
    r, _ = mini()
    write_mini(stage / "bundles", r, receipt=dict(day="2026-09-26", status="SEALED", module_sha256="a" * 64,
                                                  reader_coverage={"settlement.untimestamped_rows": 2}))
    assert verify(capsys, stage, "2026-09-26")[0] == ex.EXIT_BREACH
    assert "exporter_untimestamped_coverage_nonzero" in _breach_codes(stage)


def test_verify_drops_refused_days_and_keeps_the_trailing_contiguous_block(capsys, stage):
    for day in (date(2026, 9, 23), date(2026, 9, 25), date(2026, 9, 26)):
        write_mini(stage / "bundles", mini(day)[0])
    r, _ = mini(date(2026, 9, 24))
    write_mini(stage / "bundles", r, receipt=dict(day="2026-09-24", status="REFUSED"))
    code, result = verify(capsys, stage, "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26")
    assert code == 0 and result["days_used"] == ["2026-09-25", "2026-09-26"]
    report = json.loads((stage / "receipts" / "EXPLORATORY-verify.json").read_text())
    assert {(d["day"], d["reason"]) for d in report["days_dropped"]} == {
        ("2026-09-23", "not_in_trailing_contiguous_block"), ("2026-09-24", "receipt_not_sealed")}


def test_verify_refuses_a_tampered_stream(capsys, stage):
    r, _ = mini()
    folder = write_mini(stage / "bundles", r)
    trade = folder / "bundle" / "trade.jsonl"
    trade.write_bytes(trade.read_bytes().replace(b'"3"', b'"4"'))
    assert verify(capsys, stage, "2026-09-26")[0] == ex.EXIT_BREACH
    assert any(c.startswith("bundle_unreadable") for c in _breach_codes(stage))


# -- inventory --------------------------------------------------------------------------------------------------
def test_inventory_comes_from_descriptors_of_the_window_bundles_only(stage):
    r, a = mini()
    b = cid_of("b")
    r.condition(b, date(2026, 9, 27))
    folder = write_mini(stage / "bundles", r)
    bundle = ex.open_bundle(folder / "bundle")
    inventory, zones = ex.inventory_and_zones([bundle])
    assert dict(zones) == {"nyc": "America/New_York"}
    assert [(row["condition_id"], row["target_date"]) for row in inventory] == sorted(
        [(a, "2026-09-26"), (b, "2026-09-27")])


def test_inventory_refuses_a_bundle_outside_the_window(stage):
    r, _ = mini()
    bundle = ex.open_bundle(write_mini(stage / "bundles", r) / "bundle")
    from dataclasses import replace
    with pytest.raises(ex.Refusal) as caught:
        ex.inventory_and_zones([replace(bundle, day=date(2026, 9, 27))])
    assert caught.value.code == "inventory_bundle_outside_exploratory_window"


def test_inventory_refuses_a_non_builtin_event(stage):
    r = Rows()
    x = cid_of("x")
    r.condition(x, DAY, city="atlantis")
    r.conditions[x] = "nyc"
    bundle = ex.open_bundle(write_mini(stage / "bundles", r) / "bundle")
    with pytest.raises(ex.Refusal) as caught:
        ex.inventory_and_zones([bundle])
    assert caught.value.code == "inventory_descriptor_not_builtin_or_mismatched"


# -- guard C ----------------------------------------------------------------------------------------------------
def _source(rows, day=DAY):
    plan = materialize(DenseDay(day, union=12, trades=10, minutes=2))[0].plan
    records = [record_from_row(v) for v in rows]
    return DaySource(plan, lambda: iter(records))


@pytest.mark.parametrize("kind, payload, captured", [
    ("info_event", {"events": []}, CUTOFF),
    ("trade", dict(trade_id="t", outcome="YES", price="0.4", size="1", traded_at_utc=CUTOFF.isoformat(),
                   aggressor_side="BUY"), CUTOFF - timedelta(seconds=1)),
    ("settlement", dict(condition_id="c", p_yes=1.0, source_hashes=FICTIONAL, reconciliation_status="reconciled",
                        as_of_utc=CUTOFF.isoformat()), CUTOFF - timedelta(seconds=1)),
    ("settlement", dict(condition_id="c", p_yes=1.0, source_hashes=FICTIONAL, reconciliation_status="reconciled"),
     CUTOFF - timedelta(seconds=1)),
    ("plugin_input", dict(source="snapshots", record={}), CUTOFF - timedelta(seconds=1)),
])
def test_guard_c_source_raises_on_a_verifier_bypassing_record(kind, payload, captured):
    row = dict(sequence=0, captured_at=captured.isoformat(), condition_id="c", kind=kind, payload=payload,
               payload_sha256="0" * 64, source_hashes=FICTIONAL)
    source = ex.guarded_source(_source([row]))
    with pytest.raises(ex.GuardCBreach):
        list(source.records())


def test_guard_c_refuses_a_source_day_after_the_window():
    with pytest.raises(ex.GuardCBreach):
        ex.guarded_source(_source([], day=date(2026, 9, 27)))


def _engine():
    source = materialize(DenseDay(DAY, union=12, trades=10, minutes=2))[0]
    return ex.guarded_engine_class()(V2Config(hazard_per_minute=1.0), run_plan([source]))


def _fill(at, traded_at):
    return Fill(at, traded_at, "c", "nyc", "t", "YES", D("0.4"), D(1), "strictly_through", False)


def test_guard_c_engine_refuses_an_instant_at_the_cutoff():
    with pytest.raises(ex.GuardCBreach, match="instant_at_or_after_cutoff"):
        _engine().instant(CUTOFF, [])


@pytest.mark.parametrize("at, traded", [(CUTOFF, CUTOFF - timedelta(seconds=1)),
                                        (CUTOFF - timedelta(seconds=1), CUTOFF),
                                        (CUTOFF + timedelta(hours=1), CUTOFF + timedelta(hours=1))])
def test_guard_c_engine_refuses_a_fill_at_or_after_the_cutoff(at, traded):
    engine = _engine()
    engine.fills.append(_fill(at, traded))
    with pytest.raises(ex.GuardCBreach, match="fill_at_or_after_cutoff"):
        engine.finish()


def test_guard_c_engine_refuses_a_settlement_at_the_cutoff():
    engine = _engine()
    engine.settlements["c"] = SettlementFact("c", 1.0, CUTOFF, FICTIONAL, "reconciled")
    with pytest.raises(ex.GuardCBreach, match="settlement_at_or_after_cutoff"):
        engine.finish()


def test_execute_refuses_a_hazard_outside_the_declared_grid():
    with pytest.raises(ex.Refusal) as caught:
        ex.execute([], {}, "0.5")
    assert caught.value.code == "hazard_not_in_declared_grid"
    assert ex.HAZARD_GRID == ("1.0", "0.1", "0.01")


# -- end to end on one fictional built-in day ---------------------------------------------------------------------
def _stage_dense(stage):
    dd, conditions, rows = builtin_dense()
    write_bundle(stage / "bundles", DAY, conditions, dd.coverage_groups(), rows)
    manifest = stage / "receipts" / "EXPLORATORY-input-manifest.json"
    manifest.write_text(json.dumps([{"path": "bundles", "sha256": "0" * 64}]))
    return manifest


def test_verify_run_aggregate_end_to_end(capsys, stage):
    manifest = _stage_dense(stage)
    assert verify(capsys, stage, "2026-09-26")[0] == 0
    verify_path = stage / "receipts" / "EXPLORATORY-verify.json"
    pin = "1" * 40
    code, result = run_cli(capsys, "run", "--bundle-root", stage / "bundles", "--day", "2026-09-26",
                           "--hazard-per-minute", "1.0", "--verify", verify_path, "--out", stage / "runs" / "h1.0",
                           "--pin", pin, "--result", stage / "receipts" / "EXPLORATORY-run-h1.0.result.json")
    assert (code, result["status"]) == (0, "RUN"), result
    run = json.loads((stage / "runs" / "h1.0" / "EXPLORATORY-run.json").read_text())
    assert run["label"] == ex.LABEL and run["counted"] is False and run["market_count"] == 1
    assert set(run["results"]) == {"strictly_through", "at_price"}
    for bound in run["results"].values():
        assert set(bound) == {*ex.POLICIES, "matched_clock"}
        assert bound["no_quote"]["fills"] == 0
    out = stage / "receipts" / "EXPLORATORY-aggregate.json"
    code, result = run_cli(capsys, "aggregate", "--run-root", stage / "runs", "--verify", verify_path,
                           "--input-manifest", manifest, "--out", out, "--pin", pin)
    assert (code, result["status"]) == (0, "AGGREGATED"), result
    aggregate = json.loads(out.read_text())
    assert aggregate["label"] == ex.LABEL and aggregate["counted"] is False
    assert aggregate["cutoff_utc_exclusive"] == "2026-09-27T00:00:00+00:00"
    assert aggregate["hazards_missing"] == ["0.1", "0.01"] and aggregate["days_used"] == ["2026-09-26"]
    assert out.stat().st_size <= ex.AGGREGATE_MAX_BYTES
    text = out.read_text()
    assert "0x" not in text and "highest-temperature" not in text


def test_run_refuses_inputs_changed_since_verify(capsys, stage):
    _stage_dense(stage)
    verify(capsys, stage, "2026-09-26")
    verify_path = stage / "receipts" / "EXPLORATORY-verify.json"
    report = json.loads(verify_path.read_text())
    report["per_day"]["2026-09-26"]["input_hashes"]["trade.jsonl"] = "f" * 64
    tampered = stage / "receipts" / "EXPLORATORY-verify-tampered.json"
    tampered.write_text(json.dumps(report))
    code, result = run_cli(capsys, "run", "--bundle-root", stage / "bundles", "--day", "2026-09-26",
                           "--hazard-per-minute", "0.1", "--verify", tampered, "--out", stage / "runs" / "h0.1")
    assert (code, result["reason"]) == (ex.EXIT_BREACH, "input_changed_since_verify")
    assert not (stage / "runs" / "h0.1").exists()


@pytest.mark.parametrize("status, days, hazard, reason", [
    ("BREACH", ["2026-09-26"], "1.0", "verify_not_pass_for_these_days"),
    ("PASS", ["2026-09-25", "2026-09-26"], "1.0", "verify_not_pass_for_these_days"),
    ("PASS", ["2026-09-26"], "0.05", "hazard_not_in_declared_grid"),
])
def test_run_refuses_without_a_matching_pass_or_grid_hazard(capsys, stage, status, days, hazard, reason):
    verify_path = stage / "receipts" / "EXPLORATORY-verify.json"
    verify_path.write_text(json.dumps(dict(label=ex.LABEL, status=status, days_used=days, per_day={})))
    code, result = run_cli(capsys, "run", "--bundle-root", stage / "bundles", "--day", "2026-09-26",
                           "--hazard-per-minute", hazard, "--verify", verify_path, "--out", stage / "runs" / "h")
    assert (code, result["reason"]) == (ex.EXIT_REFUSED, reason)


# -- aggregate refusal ------------------------------------------------------------------------------------------
def _aggregate_inputs(stage, results):
    verify_path = stage / "receipts" / "EXPLORATORY-verify.json"
    raw = json.dumps(dict(label=ex.LABEL, status="PASS", days_used=["2026-09-26"], days_dropped=[],
                          per_day={"2026-09-26": {"module_sha256": "a" * 64}})).encode()
    verify_path.write_bytes(raw)
    manifest = stage / "receipts" / "EXPLORATORY-input-manifest.json"
    manifest.write_text("[]")
    (stage / "runs" / "h1.0").mkdir()
    (stage / "runs" / "h1.0" / "EXPLORATORY-run.json").write_text(json.dumps(dict(
        label=ex.LABEL, counted=False, hazard_per_minute="1.0", days_used=["2026-09-26"],
        verify_sha256=hashlib.sha256(raw).hexdigest(), results=results)))
    return verify_path, manifest


@pytest.mark.parametrize("results, reason", [
    ({"at_price": {"no_quote": {"condition_id": "c"}}}, "aggregate_forbidden_key"),
    ({"at_price": {"no_quote": {"note": "0x" + "ab" * 20}}}, "aggregate_hex_identifier"),
    ({"at_price": {"0x" + "ab" * 20: 1}}, "aggregate_hex_identifier"),
    ({"at_price": {"no_quote": {"note": "cd" * 32}}}, "aggregate_hex_identifier"),
    ({"at_price": {"no_quote": {"note": "1234567890123456789"}}}, "aggregate_numeric_identifier"),
    ({"at_price": {"no_quote": {"note": slug(DAY)}}}, "aggregate_event_slug"),
    ({"at_price": {"no_quote": {"price": 0.4}}}, "aggregate_forbidden_key"),
    ({"at_price": {"no_quote": {"trades": []}}}, "aggregate_forbidden_key"),
    ({"at_price": {"no_quote": {"series": list(range(65))}}}, "aggregate_series_refused"),
    ({"at_price": {"no_quote": {f"k{i}": "x" * 200 for i in range(1500)}}}, "aggregate_too_large"),
])
def test_aggregate_refuses_identifiers_series_and_size(capsys, stage, results, reason):
    verify_path, manifest = _aggregate_inputs(stage, results)
    out = stage / "receipts" / "EXPLORATORY-aggregate.json"
    code, result = run_cli(capsys, "aggregate", "--run-root", stage / "runs", "--verify", verify_path,
                           "--input-manifest", manifest, "--out", out)
    assert (code, result["reason"]) == (ex.EXIT_AGGREGATE_REFUSED, reason)
    assert not out.exists()


def test_aggregate_refuses_a_run_bound_to_another_verify(capsys, stage):
    verify_path, manifest = _aggregate_inputs(stage, {"at_price": {}})
    verify_path.write_bytes(verify_path.read_bytes() + b" ")
    code, result = run_cli(capsys, "aggregate", "--run-root", stage / "runs", "--verify", verify_path,
                           "--input-manifest", manifest, "--out", stage / "receipts" / "EXPLORATORY-aggregate.json")
    assert (code, result["reason"]) == (ex.EXIT_REFUSED, "run_output_inconsistent")


# -- static guards ----------------------------------------------------------------------------------------------
def test_module_never_reaches_the_post_cutoff_hazard_derivation():
    tree = ast.parse(Path(ex.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.name for a in node.names)
            names.add(getattr(node, "module", None) or "")
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    banned = {"calibrate", "CALIBRATION_DATES", "quote_market_rule", "maker_core.replay.calibration", "calibration"}
    assert not names & banned
    assert ex.EXPLORATORY_CUTOFF == datetime(2026, 9, 27, tzinfo=UTC)
    assert ex.EXPLORATORY_LAST_UTC_DAY == date(2026, 9, 26)


def _powershell():
    return shutil.which("powershell.exe") or shutil.which("powershell")


PS_FIRST = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$errors)
if ($errors.Count) { Write-Output 'PARSE_ERROR'; exit 0 }
$first = $ast.EndBlock.Statements[0]
Write-Output $first.Extent.Text
"""


@pytest.mark.skipif(sys.platform != "win32" or _powershell() is None, reason="Windows PowerShell parser")
def test_powershell_twin_first_statement_is_the_date_refusal(tmp_path):
    script = tmp_path / "first.ps1"
    script.write_text("$errors = $null\n" + PS_FIRST, encoding="ascii")
    twin = REPO / "scripts" / "ops" / "exploratory_export_le0926.ps1"
    out = subprocess.run([_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(twin)],
                         capture_output=True, text=True, timeout=120).stdout
    assert "PARSE_ERROR" not in out
    assert "ParseExact" in out and "2026-09-26" in out and "exit 2" in out
    text = twin.read_text(encoding="ascii")
    assert "[ValidatePattern('\\A2026-09-2[3-6]\\z')]" in text
    assert "'-Kind', 'night'" in text


@pytest.mark.skipif(sys.platform != "win32" or _powershell() is None, reason="Windows PowerShell parser")
def test_powershell_scripts_parse_and_twin_refuses_a_late_day(tmp_path):
    check = tmp_path / "parse.ps1"
    check.write_text("$errors = $null\n$null = [System.Management.Automation.Language.Parser]::ParseFile($args[0], "
                     "[ref]$null, [ref]$errors)\nif ($errors.Count) { Write-Output $errors[0].Message; exit 1 }\n",
                     encoding="ascii")
    for name in ("exploratory_export_le0926.ps1", "exploratory_le0926_host.ps1"):
        done = subprocess.run([_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(check),
                               str(REPO / "scripts" / "ops" / name)], capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stdout
    sentinel = tmp_path / "out"
    done = subprocess.run([_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(REPO / "scripts" / "ops" / "exploratory_export_le0926.ps1"), "-Day", "2026-09-30",
                           "-DeployRoot", str(tmp_path), "-ProductionRoot", str(tmp_path), "-OutputRoot", str(sentinel),
                           "-ExpectedModuleSha256", "0" * 64, "-ExpectedSelfSha256", "0" * 64],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode != 0 and not sentinel.exists()
