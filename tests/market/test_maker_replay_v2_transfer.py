"""Maker replay v2 transfer manifest over bundles written by the REAL night exporters (U1 fix round 1).

The capture inputs are the market tests' fictional sealed 88a day (2030-01-10); the bundles, export.json
and receipts are produced by ``maker_replay_night_v02.export_day`` and the frozen v0.1
``maker_replay_night.export_day``, never hand-built. The panel day sets are monkeypatched to hold the
fictional day. Owner decision 19, A-defender M9, P-v2-defender NB4 and PB2(a)/(b).
"""
from __future__ import annotations

from copy import copy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import panel, transfer
from weather.market import maker_replay_night as night_v01
from weather.market import maker_replay_night_v02 as night_v02
from tests.market.test_maker_replay_night import LATER, setup

DAY = LATER.date() - timedelta(days=1)


@pytest.fixture
def fictional_panel(monkeypatch):
    for name in ("QUOTE_DATES", "CALIBRATION_DATES"):
        monkeypatch.setattr(panel, name, (DAY,))
    monkeypatch.setattr(panel, "SETTLEMENT_ONLY_DATES", (DAY + timedelta(days=400),))
    monkeypatch.setattr(night_v02, "CALIBRATION_DATES", (DAY,))
    monkeypatch.setattr(night_v01, "CALIBRATION_DATES", (DAY,))


@pytest.fixture
def exports(tmp_path, fictional_panel):
    """Every export kind of one fictional day, each from the real exporter into its own output root."""
    args, _ = setup(tmp_path, multi=True)
    assert args.day == DAY.isoformat()
    roots = {}
    for kind, run in (("panel_night", lambda a: night_v02.export_day(a, "panel", now=LATER)),
                      ("calibration_night", lambda a: night_v02.export_day(a, "panel", now=LATER)),
                      ("calibration_hazard", lambda a: night_v02.export_day(a, "calibration", now=LATER)),
                      ("calibration_v01_reference", lambda a: night_v01.export_day(a, "calibration", now=LATER))):
        each = copy(args)
        each.out = tmp_path / "out" / kind
        each.out.parent.mkdir(exist_ok=True)
        assert run(each)["status"] == "SEALED"
        roots[kind] = each.out / each.day
    return roots


def build(pairs):
    return transfer.build(pairs, host_id="fictional-capture-host", created_at="2030-01-11T01:00:00+00:00")


def test_real_exports_build_and_verify_with_export_json_bound(exports):
    pairs = list(exports.items())
    doc = build(pairs)
    assert doc["format"] == "maker_core.replay.v2.transfer.v0.2"
    assert [(e["day"], e["export_kind"]) for e in doc["bundles"]] == [
        (DAY.isoformat(), k) for k in ("panel_night", "calibration_night", "calibration_hazard",
                                       "calibration_v01_reference")]
    by_kind = {e["export_kind"]: e for e in doc["bundles"]}
    for kind, root in exports.items():
        entry = by_kind[kind]
        assert entry["export_json_sha256"] == hashlib.sha256((root / "bundle" / "export.json").read_bytes()).hexdigest()
        assert set(entry["streams"]) == {p.name for p in (root / "bundle").iterdir()} - {"bundle.json", "export.json"}
    assert by_kind["calibration_v01_reference"]["bundle_format"] == "maker_core.replay.bundle.v0.1"
    assert by_kind["calibration_v01_reference"]["v01_equivalent_sha256"] == by_kind[
        "calibration_v01_reference"]["streams"]["events.jsonl"]["sha256"]
    assert by_kind["panel_night"]["bundle_format"] in transfer.V2_FORMATS
    verified = transfer.verify(doc, pairs)
    assert [v.export_kind for v in verified] == [k for k, _ in pairs]
    for item in verified:  # PB2(b): counts and bounds only, every record inside the day
        assert set(item.bounds) == {r.name for r in item.bundle.streams}
        for value in item.bounds.values():
            assert set(value) == {"records", "min_captured_at", "max_captured_at"}
            assert value["min_captured_at"].startswith(DAY.isoformat())
            assert value["max_captured_at"].startswith(DAY.isoformat())


def test_build_reads_no_stream_byte(exports, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a stream was read")
    monkeypatch.setattr(bundle_v02, "_hash_stream", refuse)
    monkeypatch.setattr(transfer, "open_stream_bundle", refuse)
    assert len(build(list(exports.items()))["bundles"]) == 4


def test_verify_compares_before_any_record_is_parsed(exports, monkeypatch):
    doc = build(list(exports.items()))
    monkeypatch.setattr(bundle_v02.StreamBundle, "records", lambda self: pytest.fail("records() called"))
    monkeypatch.setattr(transfer, "bounds", lambda bundle: pytest.fail("bounds scanned"))
    assert len(transfer.verify(doc, list(exports.items()), bounds_check=False)) == 4


def _first_stream(root):
    return sorted(p for p in (root / "bundle").iterdir() if p.name not in ("bundle.json", "export.json"))[0]


def test_one_changed_stream_byte_refuses_in_pass_one(exports):
    pairs = [("panel_night", exports["panel_night"])]
    doc = build(pairs)
    stream = _first_stream(exports["panel_night"])
    raw = bytearray(stream.read_bytes())
    # one byte, same size; bundle.json, export.json and the receipt untouched
    raw[raw.index(b'"sequence":') + 11 if stream.suffix == ".jsonl" else len(raw) // 2] ^= 1
    stream.write_bytes(bytes(raw))
    with pytest.raises(BundleError, match="stream_hash_or_size_mismatch|stream_decompression_failed"):
        transfer.verify(doc, pairs)


@pytest.mark.parametrize("name, field", [("bundle/export.json", "export_json_sha256"),
                                         ("receipt.json", "receipt_sha256")])
def test_export_json_and_receipt_are_bound_by_hash(exports, name, field):
    pairs = [("calibration_hazard", exports["calibration_hazard"])]
    doc = build(pairs)
    path = exports["calibration_hazard"] / name
    path.write_bytes(path.read_bytes().rstrip() + b" \n")
    with pytest.raises(BundleError, match=f"transfer_manifest_mismatch:{DAY}:{field}"):
        transfer.verify(doc, pairs)


def test_unlisted_duplicate_and_swapped_roots_are_refused(exports):
    doc = build([("calibration_hazard", exports["calibration_hazard"])])
    with pytest.raises(BundleError, match=f"transfer_manifest_unlisted:{DAY}:panel_night"):
        transfer.verify(doc, [("panel_night", exports["panel_night"])])
    with pytest.raises(BundleError, match="transfer_duplicate_bundle"):
        transfer.verify(doc, [("calibration_hazard", exports["calibration_hazard"])] * 2)
    with pytest.raises(BundleError, match=f"transfer_manifest_mismatch:{DAY}:"):
        transfer.verify(doc, [("calibration_hazard", exports["calibration_night"])])


def test_kind_day_format_and_receipt_disagreements_are_refused(exports, monkeypatch):
    with pytest.raises(BundleError, match="transfer_receipt_kind_mismatch"):
        build([("calibration_hazard", exports["calibration_night"])])
    with pytest.raises(BundleError, match="transfer_bundle_format_not_allowed"):
        build([("calibration_night", exports["calibration_v01_reference"])])
    with pytest.raises(BundleError, match="transfer_bundle_format_not_allowed"):
        build([("calibration_v01_reference", exports["calibration_hazard"])])
    with pytest.raises(BundleError, match="transfer_export_kind_unknown"):
        build([("calibration", exports["calibration_hazard"])])
    with pytest.raises(BundleError, match="transfer_duplicate_bundle"):
        build([("panel_night", exports["panel_night"])] * 2)
    monkeypatch.setattr(panel, "QUOTE_DATES", (DAY + timedelta(days=1),))
    with pytest.raises(BundleError, match="transfer_day_not_in_export_kind"):
        build([("panel_night", exports["panel_night"])])


def test_settlement_night_kind(exports, monkeypatch):
    monkeypatch.setattr(panel, "SETTLEMENT_ONLY_DATES", (DAY,))
    doc = build([("settlement_night", exports["panel_night"])])
    assert doc["bundles"][0]["export_kind"] == "settlement_night"


def _reseal(root, *, export_edit=None, stream_edit=None):
    """Forge a self-consistent root: rewrite export.json or one stream, then bundle.json and the receipt."""
    folder = root / "bundle"
    receipt = json.loads((root / "receipt.json").read_bytes())
    if export_edit is not None:
        export = json.loads((folder / "export.json").read_bytes())
        export_edit(export)
        (folder / "export.json").write_bytes(canonical_bytes(export))
    if stream_edit is not None:
        manifest = json.loads((folder / "bundle.json").read_bytes())
        stream = next(s for s in manifest["streams"] if s["path"] == stream_edit[0])
        raw = stream_edit[1]((folder / stream["path"]).read_bytes())
        (folder / stream["path"]).write_bytes(raw)
        stream.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (folder / "bundle.json").write_bytes(canonical_bytes(manifest))
    for path in folder.iterdir():
        raw = path.read_bytes()
        receipt["bundle"]["files"][path.name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (root / "receipt.json").write_bytes(canonical_bytes(receipt))


def test_pb2a_capture_input_outside_the_day_folder_is_refused(exports):
    root = exports["calibration_hazard"]
    other = f"maker_evidence/{DAY + timedelta(days=1)}/15-x/books.jsonl"
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({other: "0" * 64}))
    with pytest.raises(BundleError, match=f"transfer_inputs_outside_day:{DAY}"):
        build([("calibration_hazard", root)])


def test_pb2a_cumulative_non_evidence_inputs_are_allowed(exports):
    root = exports["calibration_hazard"]
    _reseal(root, export_edit=lambda e: e["input_hashes"].update({"snapshots/x/settlements.jsonl": "0" * 64}))
    assert build([("calibration_hazard", root)])["bundles"]


@pytest.mark.parametrize("kind", ["panel_night", "calibration_v01_reference"])
def test_pb2b_record_outside_the_day_is_refused_by_the_bounds_scan(exports, kind):
    root = exports[kind]
    manifest = json.loads((root / "bundle" / "bundle.json").read_bytes())
    if manifest["format"] == "maker_core.replay.bundle.v0.3":
        pytest.skip("v0.3 streams are gzip; the forgery below rewrites plain lines")
    name = manifest["streams"][0]["path"]
    late = datetime.combine(DAY + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).isoformat()

    def shift_last(raw):
        lines = raw.splitlines(keepends=True)
        value = json.loads(lines[-1])
        value["captured_at"] = late
        lines[-1] = canonical_bytes(value)
        return b"".join(lines)
    _reseal(root, stream_edit=(name, shift_last))
    doc = build([(kind, root)])
    assert transfer.verify(doc, [(kind, root)], bounds_check=False)  # pass one alone cannot see it
    with pytest.raises(BundleError, match=f"transfer_bounds_outside_day:{DAY}:{name}"):
        transfer.verify(doc, [(kind, root)])


def test_v03_decoded_digests_are_bound_when_the_exporter_writes_gzip(exports):
    root = exports["panel_night"]
    manifest = json.loads((root / "bundle" / "bundle.json").read_bytes())
    if manifest["format"] != "maker_core.replay.bundle.v0.3":
        pytest.skip("this tree's exporter writes v0.2; runs once X1's v0.3 writer is merged")
    doc = build([("panel_night", root)])
    entry = doc["bundles"][0]
    assert all(set(v) == {"sha256", "bytes", "records", "decoded_sha256", "decoded_bytes"}
               for v in entry["streams"].values())
    receipt = json.loads((root / "receipt.json").read_bytes())
    kind = next(iter(receipt["bundle"]["kinds"]))
    receipt["bundle"]["kinds"][kind]["decoded_sha256"] = "0" * 64
    (root / "receipt.json").write_bytes(canonical_bytes(receipt))
    with pytest.raises(BundleError, match="transfer_receipt_bundle_mismatch"):
        build([("panel_night", root)])


@pytest.mark.parametrize("edit", [
    lambda d: d.update(extra=1),
    lambda d: d.update(format="maker_core.replay.v2.transfer.v0.1"),
    lambda d: d["bundles"].reverse(),
    lambda d: d["bundles"].append(dict(d["bundles"][0])),
    lambda d: d["bundles"][0].update(export_kind="calibration_v01_reference"),
    lambda d: d["bundles"][0].update(module_sha256="x"),
    lambda d: d["bundles"][0].pop("export_json_sha256"),
    lambda d: d["bundles"][0].update(format="v0.1"),
])
def test_malformed_committed_manifest_is_refused(exports, edit):
    pairs = [("calibration_night", exports["calibration_night"]), ("calibration_hazard", exports["calibration_hazard"])]
    doc = json.loads(json.dumps(build(pairs)))
    edit(doc)
    with pytest.raises(BundleError, match="transfer_manifest_invalid"):
        transfer.verify(doc, pairs)


def test_transfer_constants():
    assert transfer.TRANSFER_MANIFEST_PATH == "config/maker_replay_v2/transfer_manifest.json"
    assert transfer.EXPORT_KINDS[-1] == "calibration_v01_reference"
    assert transfer.days_of("calibration_v01_reference") == tuple(panel.CALIBRATION_DATES)
    assert date(2026, 9, 27) in transfer.days_of("calibration_hazard")
