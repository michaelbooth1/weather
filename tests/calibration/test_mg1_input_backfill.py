"""MG-1 input backfill (tools/research/mg1_input_backfill.py): the unchanged MG-2 exporter on 2026-10-15..10-27.

Guards: R11 Head 1 (master rulings 2026-11-01, R11 item 7, and the option (d) ruling): the gate admits exactly
2026-10-15..2026-10-27 after each date's export cut; the exporter's own gate is swapped only inside try/finally and is
restored after success and after an exception; coverage counts are always off (no flag, every call passes False); the
manifest equals a direct export of the same fixture; the sidecar receipt names the exporter, wrapper, allow-list,
manifest and sums sha256; a finished date is skipped and partial outputs are refused; precheck opens no file; nothing
under src/ imports or names the backfill; the binding exporter's bytes are unchanged.

Synthetic fixtures only (tests/calibration/test_mg2_input_export.py ``make_host``); no real data.
"""
from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.research import mg1_input_backfill as bf
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx

from tests.calibration.test_mg2_input_export import make_host

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "src/weather/calibration/mg2_input_export.py"
# mg2_input_export.py at the R11 Head 1 base, origin/master 3f3fe50a1f61ac37f225839b2bdc8f9fd0a1dcbf.
EXPORTER_SHA256 = "fc06ab56813979b64be0afd0665093e0370eefc2fba0e83563d10288b6011d90"
D = date(2026, 10, 20)
NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
TIMESTAMPS = ("export_started_utc", "export_finished_utc")


@pytest.fixture
def host(tmp_path):
    return make_host(tmp_path / "h", D)


def _export(host, out, day=D, now=NOW):
    return bf.export_one(day=day, data_root=host, out=out, now=now)


# ----------------------------------------------------------------------------- gate

def test_gate_admits_exactly_the_backfill_dates_after_their_cut():
    for day in (date(2026, 10, 14), date(2026, 10, 28), date(2026, 9, 20), date(2026, 11, 2)):
        with pytest.raises(bf.BackfillRefused):
            bf.check_date(day, NOW)
    for day in (date(2026, 10, 15), date(2026, 10, 27)):
        bf.check_date(day, NOW)
    assert bf.all_dates()[0] == date(2026, 10, 15) and bf.all_dates()[-1] == date(2026, 10, 27)
    assert len(bf.all_dates()) == 13
    cut = allow.export_cut_utc(date(2026, 10, 27))
    with pytest.raises(bf.BackfillRefused):
        bf.check_date(date(2026, 10, 27), cut)
    bf.check_date(date(2026, 10, 27), cut + timedelta(seconds=1))
    with pytest.raises(bf.BackfillRefused):
        bf.check_date(datetime(2026, 10, 20, 12), NOW)  # a datetime is not a date
    # The swap is needed: the exporter's own gate refuses these dates.
    with pytest.raises(mx.ExportRefused):
        mx.check_date(D, NOW)


def test_gate_is_swapped_only_during_the_export_and_restored_after_success(host, tmp_path, monkeypatch):
    original = mx.check_date
    seen = {}
    real_export = mx.export

    def spy(**kwargs):
        seen["gate"] = mx.check_date
        seen["kwargs"] = kwargs
        return real_export(**kwargs)

    monkeypatch.setattr(mx, "export", spy)
    status, manifest, _receipt = _export(host, tmp_path / "out")
    assert status == "exported"
    assert seen["gate"] is bf.check_date
    assert mx.check_date is original
    assert seen["kwargs"]["coverage_counts"] is False
    assert manifest["coverage_counts"] is False


def test_gate_is_restored_after_an_exception(host, tmp_path, monkeypatch):
    original = mx.check_date

    def boom(**kwargs):
        assert mx.check_date is bf.check_date
        raise RuntimeError("exporter failed")

    monkeypatch.setattr(mx, "export", boom)
    with pytest.raises(RuntimeError, match="exporter failed"):
        _export(host, tmp_path / "out")
    assert mx.check_date is original
    assert not bf.receipt_path(tmp_path / "out", D).exists()


def test_refused_date_never_reaches_the_exporter(host, tmp_path, monkeypatch):
    monkeypatch.setattr(mx, "export", lambda **k: pytest.fail("exporter called"))
    with pytest.raises(bf.BackfillRefused):
        _export(host, tmp_path / "out", day=date(2026, 10, 28))


def test_there_is_no_coverage_flag():
    for command in ("precheck", "export"):
        with pytest.raises(SystemExit):
            bf.build_parser().parse_args([command, "--coverage-counts"])
    assert "coverage" not in bf.build_parser().format_help().replace("coverage counts off", "")


# ----------------------------------------------------------------------------- output equals a direct export

def test_manifest_and_bundle_equal_a_direct_export_of_the_same_fixture(host, tmp_path, monkeypatch):
    _status, manifest, receipt = _export(host, tmp_path / "bf")
    monkeypatch.setattr(mx, "check_date", lambda day, now=None: None)
    direct = mx.export(day=D, data_root=host, out=tmp_path / "direct", now=NOW, coverage_counts=False)
    strip = lambda m: {k: v for k, v in m.items() if k not in TIMESTAMPS}  # noqa: E731
    assert strip(manifest) == strip(direct)
    bf_files = {p.relative_to(tmp_path / "bf" / D.isoformat()).as_posix(): p.read_bytes()
                for p in (tmp_path / "bf" / D.isoformat()).rglob("*") if p.is_file() and p.name not in
                (allow.MANIFEST, allow.MANIFEST_SHA)}
    direct_files = {p.relative_to(tmp_path / "direct" / D.isoformat()).as_posix(): p.read_bytes()
                    for p in (tmp_path / "direct" / D.isoformat()).rglob("*") if p.is_file() and p.name not in
                    (allow.MANIFEST, allow.MANIFEST_SHA)}
    assert bf_files == direct_files and bf_files
    assert manifest["exporter_sha256"] == EXPORTER_SHA256
    assert receipt["exporter"]["sha256"] == EXPORTER_SHA256


def test_receipt_names_every_sha_and_the_receiver_verifies_the_bundle(host, tmp_path):
    out = tmp_path / "out"
    _status, manifest, receipt = _export(host, out)
    stored = json.loads(bf.receipt_path(out, D).read_text(encoding="utf-8"))
    assert {k: v for k, v in stored.items()} == receipt
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
    assert receipt["schema"] == "mg1_backfill_receipt/1" and receipt["target_date"] == D.isoformat()
    assert receipt["gate"]["first"] == "2026-10-15" and receipt["gate"]["last"] == "2026-10-27"
    assert receipt["wrapper"] == {"module": "tools.research.mg1_input_backfill",
                                  "sha256": sha(ROOT / "tools/research/mg1_input_backfill.py")}
    assert receipt["exporter"]["module"] == "weather.calibration.mg2_input_export"
    assert receipt["exporter"]["sha256"] == sha(EXPORTER) == manifest["exporter_sha256"]
    assert receipt["allowlist_sha256"] == allow.allowlist_sha256() == manifest["allowlist_sha256"]
    assert receipt["manifest_sha256"] == sha(out / D.isoformat() / allow.MANIFEST)
    assert receipt["sha256sums_sha256"] == sha(out / f"{D.isoformat()}{mx.SUMS_SUFFIX}")
    assert receipt["coverage_counts"] is False
    assert receipt["absent_markets"] == [] and receipt["files"] == len(manifest["files"])
    # The receipt sits beside, never inside, the bundle (the receiver refuses unlisted files).
    assert not any(p.name.endswith("receipt.json") for p in (out / D.isoformat()).rglob("*"))
    try:
        from weather.calibration import mg2_inputs as receiver
    except Exception as exc:  # refuses on the capture host
        pytest.skip(f"receiver not importable here: {exc}")
    checks, _manifest, manifest_sha = receiver.verify_bundle(out / D.isoformat(), D)
    assert {k: v for k, v in checks.items() if v} == {}
    assert manifest_sha == receipt["manifest_sha256"]


def test_default_output_is_the_mg1_inputs_folder():
    assert bf.DEFAULT_OUT == ROOT / "data" / "exports" / "mg1-inputs"
    assert bf.DEFAULT_DATA_ROOT == ROOT / "data"


# ----------------------------------------------------------------------------- resumable, partial refusal

def test_finished_date_is_skipped_and_partial_outputs_are_refused(host, tmp_path, monkeypatch):
    out = tmp_path / "out"
    _s, _m, receipt = _export(host, out)
    monkeypatch.setattr(mx, "export", lambda **k: pytest.fail("re-exported a finished date"))
    status, manifest, again = _export(host, out)
    assert (status, manifest, again) == ("already_exported", None, receipt)
    bf.receipt_path(out, D).unlink()  # bundle and sums without a receipt
    with pytest.raises(bf.BackfillRefused, match="partial_outputs"):
        _export(host, out)
    (out / f".{D.isoformat()}.partial").mkdir()
    with pytest.raises(bf.BackfillRefused, match="staging_left_over"):
        _export(host, out)


def test_cli_export_reports_each_date_and_exit_codes(host, tmp_path, capsys):
    out = tmp_path / "out"
    code = bf.main(["export", "--date", D.isoformat(), "--date", "2026-10-28", "--data-root", str(host),
                    "--out", str(out)])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 2
    assert rows[0]["status"] == "exported" and rows[0]["target_date"] == D.isoformat()
    assert rows[1]["status"] == "refused"


# ----------------------------------------------------------------------------- precheck opens nothing

def test_precheck_reads_metadata_only(host, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError(f"precheck opened a file: {a[:1]}")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(io, "open", refuse)
    monkeypatch.setattr(os, "open", refuse)
    plan = bf.precheck(days=[D, date(2026, 10, 14)], data_root=host, out=tmp_path / "out", now=NOW)
    monkeypatch.undo()
    assert plan["files_opened"] == 0
    first, refused = plan["dates"]
    assert first["status"] == "new" and first["input_files_present"] > 0 and first["input_bytes"] > 0
    assert refused["status"] == "refused"
    assert plan["out_volume_free_bytes"] > 0
    assert plan["input_bytes_total"] == first["input_bytes"]


# ----------------------------------------------------------------------------- isolation pins

def test_nothing_under_src_imports_or_names_the_backfill():
    hits = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
            if "mg1_input_backfill" in p.read_text(encoding="utf-8", errors="replace")]
    assert hits == []


def test_binding_exporter_bytes_are_unchanged():
    assert hashlib.sha256(EXPORTER.read_bytes()).hexdigest() == EXPORTER_SHA256
