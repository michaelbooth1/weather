"""MG-1 input layout (workstation): staged backfill bundles plus B's MG-2 bundles to one D0..MG1_LAST layout.

Guards: R11 Head 1 (master rulings 2026-11-01, option d): every section 9.3 check runs and only the deadline is
skipped; a backfill bundle travels with its sidecar receipt and is refused when the receipt names another manifest,
coverage counts on, another exporter or another date; B's MG-2 bundle is re-verified in place and never moved or
written; MG-1 keeps its own ledger (never the MG-2 one); build needs a verified MG-1 line for the same manifest;
concat takes exactly the window dates and refuses an open window or a missing date; the evening-fix transfer files are
never read; the share root is a parameter and no host address is named; the restated backfill constants equal the
tools-side backfill's and the transfer names equal b_scorer's.

Synthetic fixtures only (tests/calibration/test_mg2_input_export.py and test_mg2_inputs.py helpers).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from weather.calibration import mg2_input_allowlist as allow

from tests.host_guard import import_or_skip_on_capture_host

lay = import_or_skip_on_capture_host("weather.calibration.mg1_layout")
mi = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")

from tests.calibration.test_mg2_input_export import make_host  # noqa: E402
from tests.calibration.test_mg2_inputs import FakeParser, export_bundle, write_manifest  # noqa: E402
from tools.research import mg1_input_backfill as bf  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BF_DAY = date(2026, 10, 27)
MG2_DAY = date(2026, 10, 28)
NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


@pytest.fixture
def short_window(monkeypatch):
    """A two-date MG-1 window: one backfill date, one MG-2 date."""
    monkeypatch.setattr(lay.window, "window", lambda: (BF_DAY, MG2_DAY))


def _share_bundle(share, day, **receipt_overrides):
    """A reference bundle on the share plus a matching sidecar receipt (the backfill's contract)."""
    export_bundle(Path(share) / day.isoformat(), day)
    manifest = write_manifest(Path(share) / day.isoformat(), day, exporter_sha256="e" * 64, coverage_counts=False)
    receipt = {"schema": bf.RECEIPT_SCHEMA, "target_date": day.isoformat(), "coverage_counts": False,
               "exporter": {"sha256": "e" * 64},
               "manifest_sha256": _sha(Path(share) / day.isoformat() / allow.MANIFEST), **receipt_overrides}
    (Path(share) / f"{day.isoformat()}{bf.RECEIPT_SUFFIX}").write_text(json.dumps(receipt), encoding="utf-8")
    return manifest


def _stage_admit(share, inbox, ledger, day=BF_DAY):
    staged = lay.stage(share_root=share, inbox=inbox, day=day, ledger=ledger)
    assert staged["status"] == "pulled"
    return lay.admit(inbox=inbox, day=day, ledger=ledger, now=NOW)


# ----------------------------------------------------------------------------- pins

def test_restated_constants_equal_the_backfill_and_b_scorer():
    assert (lay.BACKFILL_FIRST, lay.BACKFILL_LAST) == (bf.FIRST, bf.LAST)
    assert lay.BACKFILL_RECEIPT_SCHEMA == bf.RECEIPT_SCHEMA
    assert lay.BACKFILL_RECEIPT_SUFFIX == bf.RECEIPT_SUFFIX
    assert lay.LEDGER != mi.LEDGER
    from weather.calibration import b_scorer

    assert lay.TRANSFER_NAMES == (b_scorer.TRANSFER_MANIFEST, *b_scorer.TRANSFER_FILES)


def test_source_kind_splits_at_mg2_d0_and_refuses_before_mg1_d0():
    assert lay.source_kind(date(2026, 10, 15)) == "backfill"
    assert lay.source_kind(BF_DAY) == "backfill"
    assert lay.source_kind(MG2_DAY) == "mg2"
    with pytest.raises(lay.LayoutRefused):
        lay.source_kind(date(2026, 10, 14))


def test_share_root_is_a_parameter_and_no_host_address_is_named():
    text = (ROOT / "src/weather/calibration/mg1_layout.py").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\d.])\d{1,3}(\.\d{1,3}){3}(?![\d.])", text)
    with pytest.raises(SystemExit):
        lay.build_parser().parse_args(["stage", "--inbox", "i", "--date", "2026-10-20"])


# ----------------------------------------------------------------------------- end to end from the real backfill

def test_real_backfill_bundle_stages_and_admits_without_the_deadline(tmp_path):
    day = date(2026, 10, 20)
    host = make_host(tmp_path / "h", day)
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "mg1" / "ledger.jsonl"
    bf.export_one(day=day, data_root=host, out=share, now=NOW)
    share_before = _tree(share)
    result = _stage_admit(share, inbox, ledger, day)
    assert _tree(share) == share_before  # the share is only read
    assert result["status"] == "verified" and result["source"] == "backfill"
    assert result["deadline_checked"] is False and result["schema"] == lay.RECEIPT_SCHEMA
    assert (inbox / day.isoformat() / "verified" / allow.MANIFEST).is_file()
    assert not (inbox / day.isoformat() / "incoming").exists()
    assert (inbox / day.isoformat() / lay.SIDECAR).is_file()
    rows = lay.read_ledger(ledger)
    assert [r["status"] for r in rows] == ["verified"]
    assert rows[0]["manifest_sha256"] == _sha(inbox / day.isoformat() / "verified" / allow.MANIFEST)
    # A second admit and a second stage record nothing new.
    assert lay.admit(inbox=inbox, day=day, ledger=ledger, now=NOW)["status"] == "already_recorded"
    assert lay.stage(share_root=share, inbox=inbox, day=day, ledger=ledger)["status"] == "already_recorded"
    assert len(lay.read_ledger(ledger)) == 1


# ----------------------------------------------------------------------------- refusals

def test_stage_refuses_a_missing_sidecar_and_an_mg2_date(tmp_path):
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "ledger.jsonl"
    _share_bundle(share, BF_DAY)
    (share / f"{BF_DAY.isoformat()}{bf.RECEIPT_SUFFIX}").unlink()
    with pytest.raises(lay.LayoutRefused, match="missing"):
        lay.stage(share_root=share, inbox=inbox, day=BF_DAY, ledger=ledger)
    with pytest.raises(lay.LayoutRefused, match="MG-2 date"):
        lay.stage(share_root=share, inbox=inbox, day=MG2_DAY, ledger=ledger)


@pytest.mark.parametrize("override, check", [
    ({"manifest_sha256": "0" * 64}, "backfill_receipt"),
    ({"coverage_counts": True}, "backfill_receipt"),
    ({"exporter": {"sha256": "f" * 64}}, "backfill_receipt"),
    ({"target_date": "2026-10-26"}, "backfill_receipt"),
    ({"schema": "other/1"}, "backfill_receipt"),
])
def test_admit_refuses_a_sidecar_that_does_not_match_the_bundle(tmp_path, override, check):
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "ledger.jsonl"
    _share_bundle(share, BF_DAY, **override)
    result = _stage_admit(share, inbox, ledger)
    assert result["status"] == f"refused:{check}"
    assert result["checks"][check]["pass"] is False
    assert all(v["pass"] for k, v in result["checks"].items() if k != check)
    assert (inbox / "_refused" / BF_DAY.isoformat() / "attempt-1" / allow.MANIFEST).is_file()
    assert not (inbox / BF_DAY.isoformat() / "verified").exists()


def test_admit_runs_the_section_9_3_checks(tmp_path):
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "ledger.jsonl"
    _share_bundle(share, BF_DAY)
    lay.stage(share_root=share, inbox=inbox, day=BF_DAY, ledger=ledger)
    (inbox / BF_DAY.isoformat() / "incoming" / "extra.txt").write_text("x", encoding="utf-8")
    result = lay.admit(inbox=inbox, day=BF_DAY, ledger=ledger, now=NOW)
    assert result["status"].startswith("refused:") and result["checks"]["no_unlisted_files"]["pass"] is False


def test_evening_fix_transfer_files_are_never_read(tmp_path):
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "ledger.jsonl"
    _share_bundle(share, BF_DAY)
    lay.stage(share_root=share, inbox=inbox, day=BF_DAY, ledger=ledger)
    for name in lay.TRANSFER_NAMES:
        marker = inbox / BF_DAY.isoformat() / name
        marker.write_bytes(b"")
        with pytest.raises(lay.LayoutRefused, match=name):
            lay.admit(inbox=inbox, day=BF_DAY, ledger=ledger, now=NOW)
        marker.unlink()
    assert lay.read_ledger(ledger) == []


def test_mg2_bundle_is_verified_in_place_and_never_moved_or_written(tmp_path, short_window):
    mg2_inbox, ledger = tmp_path / "mg2", tmp_path / "mg1-ledger.jsonl"
    export_bundle(mg2_inbox / MG2_DAY.isoformat() / "verified", MG2_DAY)
    before = _tree(mg2_inbox)
    with pytest.raises(lay.LayoutRefused, match="mg2-inbox"):
        lay.admit(inbox=tmp_path / "inbox", day=MG2_DAY, ledger=ledger, now=NOW)
    result = lay.admit(inbox=tmp_path / "inbox", day=MG2_DAY, ledger=ledger, mg2_inbox=mg2_inbox, now=NOW)
    assert result["status"] == "verified" and result["source"] == "mg2" and result["deadline_checked"] is False
    assert result["path"] == str(mg2_inbox / MG2_DAY.isoformat() / "verified")
    assert _tree(mg2_inbox) == before
    assert not (tmp_path / "inbox").exists()


# ----------------------------------------------------------------------------- build and concat

def test_build_and_concat_cover_exactly_the_window(tmp_path, short_window):
    share, inbox, mg2_inbox = tmp_path / "share", tmp_path / "inbox", tmp_path / "mg2"
    ledger, layouts, out = tmp_path / "ledger.jsonl", tmp_path / "layouts", tmp_path / "window"
    _share_bundle(share, BF_DAY)
    export_bundle(mg2_inbox / MG2_DAY.isoformat() / "verified", MG2_DAY)
    with pytest.raises(lay.LayoutRefused, match="no verified line"):
        lay.build(inbox=inbox, day=BF_DAY, layouts=layouts, ledger=ledger, parser=FakeParser())
    assert _stage_admit(share, inbox, ledger)["status"] == "verified"
    assert lay.admit(inbox=inbox, day=MG2_DAY, ledger=ledger, mg2_inbox=mg2_inbox, now=NOW)["status"] == "verified"
    built = lay.build(inbox=inbox, day=BF_DAY, layouts=layouts, ledger=ledger, parser=FakeParser())
    assert built["target_date"] == BF_DAY.isoformat() and built["snapshots"] > 0
    with pytest.raises(lay.LayoutRefused, match="no layout"):
        lay.concat(layouts=layouts, out=out, ledger=ledger)
    mg2_before = _tree(mg2_inbox)
    lay.build(inbox=inbox, day=MG2_DAY, layouts=layouts, ledger=ledger, mg2_inbox=mg2_inbox, parser=FakeParser())
    assert _tree(mg2_inbox) == mg2_before
    result = lay.concat(layouts=layouts, out=out, ledger=ledger)
    assert result["dates"] == [BF_DAY.isoformat(), MG2_DAY.isoformat()]
    record = json.loads((out / lay.WINDOW_RECEIPT).read_text(encoding="utf-8"))
    assert record["sources"] == {BF_DAY.isoformat(): "backfill", MG2_DAY.isoformat(): "mg2"}
    assert record["d0"] == BF_DAY.isoformat() and record["last"] == MG2_DAY.isoformat() and record["dates"] == 2
    assert record["ledger_sha256"] == _sha(ledger)
    assert record["window_manifest_sha256"] == _sha(out / "manifest.json")


def test_build_refuses_a_manifest_changed_after_admission(tmp_path):
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "ledger.jsonl"
    _share_bundle(share, BF_DAY)
    assert _stage_admit(share, inbox, ledger)["status"] == "verified"
    manifest = inbox / BF_DAY.isoformat() / "verified" / allow.MANIFEST
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(lay.LayoutRefused, match="changed"):
        lay.build(inbox=inbox, day=BF_DAY, layouts=tmp_path / "layouts", ledger=ledger, parser=FakeParser())


def test_concat_refuses_an_open_ended_window(tmp_path, monkeypatch):
    monkeypatch.setattr(lay.window, "window", lambda: (date(2026, 10, 15), None))
    with pytest.raises(lay.LayoutRefused, match="open-ended"):
        lay.concat(layouts=tmp_path / "layouts", out=tmp_path / "out", ledger=tmp_path / "ledger.jsonl")
