"""A9 driver for the maker replay v2 transfer manifest (``maker_core.replay.v2.transfer_cli``).

Bundles come from the REAL exporters over the market tests' fictional sealed day (fixtures shared with
``test_maker_replay_v2_transfer``); everything lives under pytest's tmp_path, nothing under ``data/``.

Guards: calibration kinds only; embargo by folder name before any byte (days at or after the carry fence refuse);
build never overwrites and prints the manifest sha256; verify compares the relayed sha256 before any parse,
requires the roots to cover the manifest exactly, always runs the bounds scan, and refuses fail-closed with one
``refused: <code>`` line.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import shutil

import pytest

from maker_core.replay.v2 import panel, transfer, transfer_cli
from tests.market.test_maker_replay_v2_transfer import DAY, build as transfer_build, exports, fictional_panel  # noqa: F401

CAL = ("calibration_night", "calibration_hazard", "calibration_v01_reference")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = transfer_cli.main([str(a) for a in argv], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def roots_args(exports, kinds=CAL):
    args = []
    for kind in kinds:
        args += ["--root", f"{kind}={exports[kind]}"]
    return args


def built(exports, tmp_path, kinds=CAL):
    manifest = tmp_path / "transfer_manifest.json"
    code, out, err = run("build", *roots_args(exports, kinds), "--host-id", "fictional-capture-host",
                         "--out", manifest)
    assert (code, err) == (0, ""), err
    return manifest, json.loads(out)


def test_build_then_verify_passes_with_the_printed_sha(exports, tmp_path):
    manifest, receipt = built(exports, tmp_path)
    raw = manifest.read_bytes()
    assert receipt["manifest_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["bundles"] == [[DAY.isoformat(), k] for k in CAL]
    doc = json.loads(raw)
    assert transfer.check_doc(doc) and doc["host_id"] == "fictional-capture-host"
    code, out, err = run("verify", "--manifest", manifest, "--expected-manifest-sha256", receipt["manifest_sha256"],
                         *roots_args(exports))
    assert (code, err) == (0, ""), err
    result = json.loads(out)
    assert result["verdict"] == "PASS" and result["manifest_sha256"] == receipt["manifest_sha256"]
    assert [b["export_kind"] for b in result["bundles"]] == sorted(CAL)
    for bundle in result["bundles"]:  # counts and bounds only
        for value in bundle["streams"].values():
            assert set(value) == {"records", "min_captured_at", "max_captured_at"}


def test_build_never_overwrites_and_never_writes_inside_a_root(exports, tmp_path):
    manifest, _ = built(exports, tmp_path)
    before = manifest.read_bytes()
    code, _, err = run("build", *roots_args(exports), "--host-id", "h", "--out", manifest)
    assert (code, err) == (2, "refused: transfer_cli_out_exists\n") and manifest.read_bytes() == before
    inside = exports["calibration_night"] / "manifest.json"
    code, _, err = run("build", *roots_args(exports), "--host-id", "h", "--out", inside)
    assert (code, err) == (2, "refused: transfer_cli_out_inside_root\n") and not inside.exists()


@pytest.mark.parametrize("command", ["build", "verify"])
def test_panel_kinds_are_refused_before_any_read(exports, tmp_path, monkeypatch, command):
    monkeypatch.setattr(transfer, "_raw", lambda *a, **k: pytest.fail("a file was read"))
    monkeypatch.setattr(transfer, "_entry", lambda *a, **k: pytest.fail("a root was read"))
    tail = (["--host-id", "h", "--out", tmp_path / "m.json"] if command == "build"
            else ["--manifest", tmp_path / "m.json", "--expected-manifest-sha256", "0" * 64])
    code, out, err = run(command, "--root", f"panel_night={exports['panel_night']}", *tail)
    assert (code, out, err) == (2, "", "refused: transfer_cli_kind_not_admitted\n")


@pytest.mark.parametrize("offset,code_", [(1, "transfer_cli_day_embargoed"), (400, "transfer_cli_day_embargoed"),
                                          (-1, "transfer_cli_day_not_in_kind")])
def test_a_folder_named_for_another_day_is_refused_by_name_before_any_read(exports, tmp_path, monkeypatch,
                                                                          offset, code_):
    other = tmp_path / "other" / (DAY + timedelta(days=offset)).isoformat()
    shutil.copytree(exports["calibration_night"], other)
    monkeypatch.setattr(transfer, "build", lambda *a, **k: pytest.fail("transfer.build reached"))
    code, _, err = run("build", "--root", f"calibration_night={other}", "--host-id", "h", "--out", tmp_path / "m.json")
    assert (code, err) == (2, f"refused: {code_}\n")


@pytest.mark.parametrize("name", ["bundle", "2026-9-27", "2026-02-30", "x2026-09-27"])
def test_a_folder_not_named_as_a_day_is_refused(exports, tmp_path, name):
    code, _, err = run("build", "--root", f"calibration_night={tmp_path / name}", "--host-id", "h",
                       "--out", tmp_path / "m.json")
    assert (code, err) == (2, "refused: transfer_cli_root_not_a_day\n")


def test_the_real_scope_is_the_three_calibration_days_before_the_panel():
    assert transfer_cli.transfer.CALIBRATION_KINDS == CAL
    assert transfer.CALIBRATION_CARRY_FENCE == datetime(2026, 9, 30, tzinfo=timezone.utc)
    assert panel.CALIBRATION_DATES == (date(2026, 9, 27), date(2026, 9, 28), date(2026, 9, 29))
    assert transfer_cli.admitted_day("calibration_hazard", "2026-09-29") == date(2026, 9, 29)
    for name in ("2026-09-30", "2026-10-13", "2026-10-15"):
        with pytest.raises(transfer_cli.Refused, match="^transfer_cli_day_embargoed$"):
            transfer_cli.admitted_day("calibration_night", name)
    with pytest.raises(transfer_cli.Refused, match="^transfer_cli_day_not_in_kind$"):
        transfer_cli.admitted_day("calibration_night", "2026-09-26")


def test_an_invalid_fence_fails_closed(monkeypatch):
    monkeypatch.setattr(transfer, "CALIBRATION_CARRY_FENCE", datetime(2026, 9, 30))
    with pytest.raises(transfer_cli.Refused, match="^transfer_cli_fence_invalid$"):
        transfer_cli.admitted_day("calibration_night", "2026-09-27")


@pytest.mark.parametrize("sha,code_", [("0" * 64, "transfer_cli_manifest_sha_mismatch"),
                                       ("A" * 64, "transfer_cli_expected_sha_not_64_lower_hex"),
                                       ("abc", "transfer_cli_expected_sha_not_64_lower_hex")])
def test_verify_compares_the_relayed_sha_before_any_parse(exports, tmp_path, monkeypatch, sha, code_):
    manifest, _ = built(exports, tmp_path)
    monkeypatch.setattr(transfer_cli.json, "loads", lambda *a, **k: pytest.fail("manifest parsed"))
    code, out, err = run("verify", "--manifest", manifest, "--expected-manifest-sha256", sha, *roots_args(exports))
    assert (code, out, err) == (2, "", f"refused: {code_}\n")


def test_verify_refuses_a_manifest_listing_a_panel_kind(exports, tmp_path):
    doc = transfer_build([("panel_night", exports["panel_night"])])
    manifest = tmp_path / "panel.json"
    manifest.write_bytes(transfer_cli._canonical(doc))
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    code, _, err = run("verify", "--manifest", manifest, "--expected-manifest-sha256", sha, *roots_args(exports, CAL[:1]))
    assert (code, err) == (2, "refused: transfer_cli_kind_not_admitted\n")


@pytest.mark.parametrize("kinds", [CAL[:2], CAL[1:]])
def test_verify_requires_the_roots_to_cover_the_manifest_exactly(exports, tmp_path, kinds):
    manifest, receipt = built(exports, tmp_path)
    code, _, err = run("verify", "--manifest", manifest, "--expected-manifest-sha256", receipt["manifest_sha256"],
                       *roots_args(exports, kinds))
    assert (code, err) == (2, "refused: transfer_cli_roots_do_not_cover_manifest\n")


def test_a_changed_stream_refuses_with_one_line_and_no_traceback(exports, tmp_path):
    manifest, receipt = built(exports, tmp_path)
    folder = exports["calibration_hazard"] / "bundle"
    stream = sorted(p for p in folder.iterdir() if p.name not in ("bundle.json", "export.json"))[0]
    raw = bytearray(stream.read_bytes())
    raw[len(raw) // 2] ^= 1
    stream.write_bytes(bytes(raw))
    code, out, err = run("verify", "--manifest", manifest, "--expected-manifest-sha256", receipt["manifest_sha256"],
                         *roots_args(exports))
    assert code == 2 and out == "" and err.startswith("refused: ") and err.count("\n") == 1
    assert "Traceback" not in err


def test_an_unexpected_error_exits_3_without_text(exports, tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("internal detail")
    monkeypatch.setattr(transfer, "build", boom)
    code, out, err = run("build", *roots_args(exports), "--host-id", "h", "--out", tmp_path / "m.json")
    assert (code, out, err) == (3, "", "error: transfer_cli_error:RuntimeError\n")
