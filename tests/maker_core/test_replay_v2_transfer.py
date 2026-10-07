"""Maker replay v2 transfer manifest (U1, W7; owner decision 19, A-defender M9). Fictional exports only."""
from __future__ import annotations

import json
from datetime import date

import pytest

from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import transfer
from .fixtures.panel_v02 import Panel

CAL = date(2026, 9, 28)
QUOTE = date(2026, 10, 7)
SETTLE = date(2026, 10, 15)
FIXTURE = Panel(markets=("toronto",), bands=1, step=60)


@pytest.fixture
def exports(tmp_path):
    return [("calibration_night", FIXTURE.write_export(tmp_path / "night", CAL)),
            ("calibration_hazard", FIXTURE.write_export(tmp_path / "hazard", CAL, kind="calibration")),
            ("panel_night", FIXTURE.write_export(tmp_path / "night", QUOTE)),
            ("settlement_night", FIXTURE.write_export(tmp_path / "night", SETTLE))]


def build(roots):
    return transfer.build(roots, host_id="fictional-capture-host", created_at="2026-10-07T00:00:00+00:00")


def test_manifest_is_keyed_per_bundle_with_two_bundles_per_calibration_date(exports):
    doc = build(exports)
    assert doc["format"] == "maker_core.replay.v2.transfer.v0.1"
    keys = [(e["day"], e["export_kind"]) for e in doc["bundles"]]
    assert keys == [("2026-09-28", "calibration_night"), ("2026-09-28", "calibration_hazard"),
                    ("2026-10-07", "panel_night"), ("2026-10-15", "settlement_night")]
    night, hazard = doc["bundles"][:2]
    assert night["receipt_sha256"] != hazard["receipt_sha256"]
    assert night["v01_equivalent_sha256"] != hazard["v01_equivalent_sha256"]
    assert set(night["streams"]) == {"descriptor.jsonl"}
    assert transfer.TRANSFER_MANIFEST_PATH == "config/maker_replay_v2/transfer_manifest.json"
    opened = transfer.verify(doc, exports)
    assert [(k, b.day) for k, b in opened] == [(k, date.fromisoformat(r.name)) for k, r in exports]


def test_build_reads_only_bundle_json_and_receipt(exports, monkeypatch):
    def refuse(*_):
        raise AssertionError("a stream was read")
    monkeypatch.setattr(bundle_v02, "_hash_stream", refuse)
    monkeypatch.setattr(transfer, "open_stream_bundle", refuse)
    assert len(build(exports)["bundles"]) == 4


def test_verify_compares_before_any_record_is_parsed(exports, monkeypatch):
    doc = build(exports)
    monkeypatch.setattr(bundle_v02.StreamBundle, "records", lambda self: (_ for _ in ()).throw(AssertionError))
    assert len(transfer.verify(doc, exports)) == 4


def test_one_changed_stream_byte_refuses_before_records(exports, monkeypatch):
    doc = build(exports)
    monkeypatch.setattr(bundle_v02.StreamBundle, "records", lambda self: (_ for _ in ()).throw(AssertionError))
    stream = exports[2][1] / "bundle" / "descriptor.jsonl"
    raw = bytearray(stream.read_bytes())
    raw[raw.index(b'"horizon_days":') + 15] ^= 1  # one digit, same size; bundle.json and receipt untouched
    stream.write_bytes(bytes(raw))
    with pytest.raises(BundleError, match="stream_hash_or_size_mismatch"):
        transfer.verify(doc, exports)


def test_a_consistent_re_export_is_a_mismatch(exports, tmp_path):
    doc = build(exports)
    redo = Panel(markets=("toronto",), bands=1, step=60, offset=7).write_export(tmp_path / "redo", QUOTE)
    roots = [exports[0], exports[1], ("panel_night", redo), exports[3]]
    with pytest.raises(BundleError, match="transfer_manifest_mismatch:2026-10-07:bundle_json_sha256"):
        transfer.verify(doc, roots)


def test_receipt_change_alone_is_a_mismatch(exports):
    doc = build(exports)
    receipt = exports[3][1] / "receipt.json"
    value = json.loads(receipt.read_text())
    value["extra"] = 1
    receipt.write_text(json.dumps(value))
    with pytest.raises(BundleError, match="transfer_manifest_mismatch:2026-10-15:receipt_sha256"):
        transfer.verify(doc, exports)


def test_unlisted_duplicate_and_swapped_roots_are_refused(exports):
    doc = build(exports[:3])
    with pytest.raises(BundleError, match="transfer_manifest_unlisted:2026-10-15:settlement_night"):
        transfer.verify(doc, exports)
    with pytest.raises(BundleError, match="transfer_duplicate_bundle"):
        transfer.verify(doc, [exports[0], exports[0]])
    with pytest.raises(BundleError, match="transfer_manifest_mismatch:2026-09-28:receipt_sha256"):
        # the night bundle presented as the hazard bundle of the same date (fictional: same bundle bytes)
        transfer.verify(doc, [("calibration_hazard", exports[0][1])])


def test_build_refuses_kind_day_and_receipt_disagreements(exports, tmp_path):
    with pytest.raises(BundleError, match="transfer_day_not_in_export_kind"):
        build([("panel_night", exports[0][1])])
    with pytest.raises(BundleError, match="transfer_day_not_in_export_kind"):
        build([("panel_night", exports[3][1])])  # settlement-only date is not a quote date
    with pytest.raises(BundleError, match="transfer_receipt_kind_mismatch"):
        build([("calibration_hazard", exports[0][1])])
    with pytest.raises(BundleError, match="transfer_export_kind_unknown"):
        build([("calibration", exports[1][1])])
    with pytest.raises(BundleError, match="transfer_duplicate_bundle"):
        build([exports[2], exports[2]])
    receipt = exports[2][1] / "receipt.json"
    original = json.loads(receipt.read_text())
    for edit, code in ((dict(status="REFUSED"), "transfer_receipt_not_sealed"),
                       (dict(day="2026-10-08"), "transfer_receipt_day_mismatch"),
                       (dict(bundle=dict(original["bundle"], files={})), "transfer_receipt_bundle_mismatch")):
        receipt.write_text(json.dumps(dict(original, **edit)))
        with pytest.raises(BundleError, match=code):
            build([exports[2]])


@pytest.mark.parametrize("edit", [
    lambda d: d.update(extra=1),
    lambda d: d.update(format="maker_core.replay.v2.transfer.v0.0"),
    lambda d: d["bundles"].reverse(),
    lambda d: d["bundles"].append(dict(d["bundles"][0])),
    lambda d: d["bundles"][0].update(export_kind="panel_night"),
    lambda d: d["bundles"][0].update(module_sha256="x"),
    lambda d: d["bundles"][0].pop("v01_equivalent_sha256"),
])
def test_malformed_committed_manifest_is_refused(exports, edit):
    doc = json.loads(json.dumps(build(exports)))
    edit(doc)
    with pytest.raises(BundleError, match="transfer_manifest_invalid"):
        transfer.verify(doc, exports)
