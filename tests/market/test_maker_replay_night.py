"""Synthetic sealed capture only; no production paths, clocks or network."""
import builtins
from datetime import timedelta
import io
import json
from pathlib import Path
import socket

import pytest

from maker_core.replay.bundle import BundleError, load_bundle, sha256
from weather.market.maker_evidence_store import EvidenceStore, WriterLock, encoded
from weather.market.maker_replay_night import active_intervals, night, main
from weather.market import maker_replay_night as module
from tests.market.test_maker_plugin import fixture
from tests.market.test_maker_plugin_dry_run import NOW, layout, csv_rows, jsonl


def setup(tmp_path, *, multi=False, exclusions=(), compressed=False):
    args, _, segment = layout(tmp_path, minutes=2, compressed=compressed)
    args.day, args.out, args.exclude_utc = args.date, tmp_path / "panel", list(exclusions)
    args.max_output_bytes = 64 * 1024**2
    if multi:
        _, rows, _, _, discovery, books = fixture(city="chicago", now=NOW)
        # Distinct fictional condition/token identities in the second city.
        replacements = {"0x" + f"{i:064x}": "0x" + f"{i+10:064x}" for i in range(1, 4)}
        replacements.update({str(i): str(i+1000) for i in range(100, 106)})
        def remap(value):
            if isinstance(value, dict):
                return {k: remap(v) for k, v in value.items()}
            if isinstance(value, list):
                return [remap(v) for v in value]
            if isinstance(value, str):
                if value.startswith('["'):
                    return json.dumps(remap(json.loads(value)))
                return replacements.get(value, value)
            return value
        rows = remap(rows)
        csv_rows(args.data_root / "snapshots" / rows[0]["event_slug"] / "snapshots_long.csv", rows)
        store = EvidenceStore(args.data_root / "maker_evidence", clock=lambda: NOW + timedelta(minutes=3))
        store.record("discovery", encoded(remap(json.loads(discovery["body_utf8"]))), metadata={"http_status": 200})
        store.record("books", encoded(remap(json.loads(books["body_utf8"]))), metadata={"http_status": 200})
        store.event("run_summary", dict(started_at_utc=NOW.isoformat(), pid=123, state="COMPLETED"))
        store.event("stream_gap", dict(channel="trades", error_type="FixtureDisconnect",
                                      subscription=store.subscription(["1100", "1101"], "trades")))
        store.seal()
    return args, segment


def receipt(args):
    return json.loads((args.out / args.day / "receipt.json").read_bytes())


def test_every_discovered_city_hashes_append_only_and_no_input_writes(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, multi=True, compressed=True)
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    handles = []
    def guard(original):
        def opened(path, mode="r", *a, **kw):
            if any(flag in mode for flag in "wax+"):
                assert Path(path).absolute().is_relative_to(args.out)
            handle = original(path, mode, *a, **kw)
            if "r" in mode and Path(path).absolute().is_relative_to(args.data_root):
                handles.append(handle)
            return handle
        return opened
    monkeypatch.setattr(builtins, "open", guard(builtins.open))
    monkeypatch.setattr(io, "open", guard(io.open))
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("network"))
    report = night(args, now=NOW+timedelta(days=1))
    assert report["status"] == "SEALED"
    assert report["cities"] == ["chicago", "nyc"]
    assert report["restart_events"][0]["reason"] == "RECORDED_88A_RUN"
    assert report["gaps"][0]["reason"] == "STREAM_GAP"
    assert handles and all(h.closed for h in handles)
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    assert report["free_before_bytes"] > 0 and report["free_after_bytes"] > 0
    for city, info in report["bundles"].items():
        folder = args.out / args.day / "bundles" / city
        bundle = load_bundle(folder)
        assert {c.market_id for c in bundle.conditions} == {city}
        for name, binding in info["files"].items():
            raw = (folder / name).read_bytes()
            assert binding == dict(bytes=len(raw), sha256=sha256(raw))
        if city == "nyc":
            source = next(r for r in bundle.records if r.kind == "plugin_input" and r.payload["source"] == "source_rows")
            assert source.payload["release_calibration_method"] == "identity"
            assert source.payload["record"]["release_calibration_method"] == "identity"
    ledger = (args.out / "panel-ledger.jsonl").read_bytes()
    row, = map(json.loads, ledger.splitlines())
    assert row["receipt_sha256"] == sha256((args.out / args.day / "receipt.json").read_bytes())
    with pytest.raises(ValueError, match="day_already"):
        night(args, now=NOW+timedelta(days=1))
    assert (args.out / "panel-ledger.jsonl").read_bytes() == ledger
    print("FIXTURE_CITY_BYTES", {city: value["bytes"] for city, value in report["bundles"].items()})
    print("FIXTURE_DAY_BYTES", sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file()))


def test_exclusion_is_declared_and_legacy_reader_refuses_not_zero_fills(tmp_path):
    args, _ = setup(tmp_path, exclusions=["05:00-08:00"])
    report = night(args, now=NOW+timedelta(days=1))
    folder = args.out / args.day / "bundles" / "nyc"
    manifest = json.loads((folder / "bundle.json").read_bytes())
    assert all(c["active_intervals"] == report["active_intervals"] for c in manifest["conditions"])
    assert len(report["active_intervals"]) == 2
    assert report["active_intervals"][0]["active_until"].endswith("05:00:00+00:00")
    assert report["active_intervals"][1]["active_from"].endswith("08:00:00+00:00")
    assert report["reader_compatibility"] == "REQUIRES_110R_ACTIVE_INTERVALS"
    with pytest.raises(BundleError, match="unexpected_fields"):
        load_bundle(folder)
    gaps = report["bundles"]["nyc"]["gaps"]
    assert all(g["until"] <= args.day + "T05:00:00+00:00" or
               g["from"] >= args.day + "T08:00:00+00:00" for g in gaps)


@pytest.mark.parametrize("value", ["5:00-08:00", "23:00-01:00", "08:00-08:00", "00:00-25:00"])
def test_bad_exclusion(value):
    with pytest.raises(ValueError):
        active_intervals(NOW.date(), [value])


def test_overlapping_and_full_day_exclusion():
    with pytest.raises(ValueError, match="overlapping"):
        active_intervals(NOW.date(), ["05:00-08:00", "07:00-09:00"])
    assert active_intervals(NOW.date(), ["00:00-24:00"]) == []


@pytest.mark.parametrize("fault", ["unsealed", "output_cap", "input_cap", "hash", "empty", "changed"])
def test_refused_day_retains_receipt_and_never_seals_partial_output(tmp_path, monkeypatch, fault):
    args, segment = setup(tmp_path)
    if fault == "unsealed":
        (segment / "manifest.json").unlink()
    elif fault == "output_cap":
        args.max_output_bytes = 100
    elif fault == "input_cap":
        args.max_input_bytes = 100
    elif fault == "hash":
        with (segment / "discovery.jsonl").open("ab") as handle:
            handle.write(b"bad\n")
    elif fault == "empty":
        args.day = (NOW.date()-timedelta(days=1)).isoformat()
    else:
        monkeypatch.setattr(module.ExportReader, "recheck", lambda self: (_ for _ in ()).throw(ValueError("changed")))
    before = {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        night(args, now=NOW+timedelta(days=1))
    assert receipt(args)["status"] == "REFUSED"
    assert not (args.out / args.day / "bundles").exists()
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="day_already"):
        night(args, now=NOW+timedelta(days=1))


def test_failed_second_city_does_not_publish_first(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, multi=True)
    original = module.export
    def capped_city(options, **kwargs):
        if options.markets == ["nyc"]:
            raise module.StopRun("bundle_output_cap")
        return original(options, **kwargs)
    monkeypatch.setattr(module, "export", capped_city)
    with pytest.raises(ValueError, match="bundle_output_cap"):
        night(args, now=NOW+timedelta(days=1))
    assert (args.out / args.day / "pending" / "chicago").is_dir()
    assert not (args.out / args.day / "bundles").exists()
    assert receipt(args)["status"] == "REFUSED"


def test_open_day_overlap_and_busy_lock_refuse(tmp_path):
    args, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="closed"):
        night(args, now=NOW)
    assert not args.out.exists()
    out = args.out
    args.out = args.data_root / "output"
    with pytest.raises(ValueError, match="overlap"):
        night(args, now=NOW+timedelta(days=1))
    args.out = out
    args.out.mkdir()
    with WriterLock(args.out), pytest.raises(RuntimeError, match="writer"):
        night(args, now=NOW+timedelta(days=1))


def test_torn_ledger_is_never_repaired_or_appended(tmp_path):
    args, _ = setup(tmp_path)
    args.out.mkdir()
    path = args.out / "panel-ledger.jsonl"
    path.write_bytes(b'{"day":')
    with pytest.raises(ValueError, match="incomplete"):
        night(args, now=NOW+timedelta(days=1))
    assert path.read_bytes() == b'{"day":'
    assert not (args.out / args.day).exists()


def test_cli_uses_requested_surface(tmp_path, monkeypatch, capsys):
    args, _ = setup(tmp_path)
    original = module.night
    monkeypatch.setattr(module, "night", lambda a: original(a, now=NOW+timedelta(days=1)))
    assert main(["night", "--day", args.day, "--data-root", str(args.data_root), "--out", str(args.out)]) == 0
    assert '"status": "SEALED"' in capsys.readouterr().out


def bind_release(args, method="identity"):
    from weather.release_artifacts import manifest_content_sha256
    from weather.schema_registry import schema_version
    args.release_root = args.data_root.parent / "releases"
    folder = args.release_root / "synthetic-release"
    folder.mkdir(parents=True)
    raw = encoded({"market_bin": {"method": method}})
    artifact = folder / "calibration.json"
    artifact.write_bytes(raw)
    manifest = dict(schema_version=schema_version("release_manifest"), release_id=folder.name,
                    artifacts=dict(inventory=[dict(role="base_model.nyc.probability_calibration",
                        path=artifact.name, kind="calibration", declared=True, bytes=len(raw), sha256=sha256(raw))]))
    manifest["manifest_sha256"] = manifest_content_sha256(manifest)
    (folder / "release_manifest.json").write_bytes(encoded(manifest))
    source = next((args.data_root / "snapshots").glob("*/forecast_payloads.jsonl"))
    rows = [json.loads(line) for line in source.read_bytes().splitlines()]
    for row in rows:
        row.pop("release_calibration_method")
        row["release_manifest_sha256"] = manifest["manifest_sha256"]
    jsonl(source, rows)
    return folder, source


@pytest.mark.parametrize("method", ["identity", "market_shrink"])
def test_calibration_is_projected_from_exact_captured_release(tmp_path, method):
    args, _ = setup(tmp_path)
    folder, source = bind_release(args, method)
    before = {p: p.read_bytes() for root in (args.data_root, args.release_root) for p in root.rglob("*") if p.is_file()}
    result = night(args, now=NOW+timedelta(days=1))
    bundle = load_bundle(args.out / args.day / "bundles" / "nyc")
    rows = [r.payload for r in bundle.records if r.kind == "plugin_input" and r.payload["source"] == "source_rows"]
    assert rows and all(r["release_calibration_method"] == method for r in rows)
    assert all(r["record"]["release_calibration_method"] == method for r in rows)
    assert all(r["record"]["release_calibration_artifact_sha256"] == sha256((folder / "calibration.json").read_bytes()) for r in rows)
    assert "release:synthetic-release/calibration.json" in result["input_hashes"]
    assert before == {p: p.read_bytes() for root in (args.data_root, args.release_root) for p in root.rglob("*") if p.is_file()}
    assert "release_calibration_method" not in json.loads(source.read_bytes())


@pytest.mark.parametrize("fault", ["artifact", "manifest", "conflict", "missing"])
def test_calibration_projection_fails_closed(tmp_path, fault):
    args, _ = setup(tmp_path)
    folder, source = bind_release(args)
    if fault == "artifact":
        (folder / "calibration.json").write_bytes(encoded({"market_bin": {"method": "market_shrink"}}))
    elif fault == "manifest":
        value = json.loads((folder / "release_manifest.json").read_bytes())
        value["release_id"] = "other"
        (folder / "release_manifest.json").write_bytes(encoded(value))
    elif fault == "missing":
        (folder / "calibration.json").unlink()
    else:
        value = json.loads(source.read_bytes())
        value["release_calibration_method"] = "market_shrink"
        jsonl(source, [value])
    with pytest.raises(ValueError):
        night(args, now=NOW+timedelta(days=1))
    assert receipt(args)["status"] == "REFUSED"
