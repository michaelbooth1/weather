"""Synthetic sealed capture only; no production paths, clocks or network."""
import builtins
from datetime import timedelta
import io
import json
from pathlib import Path
import socket

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import Limits, load_bundle, sha256
from maker_core.replay.execution_manifest import quote_market_rule
from maker_core.replay.pack_io import load_days
from weather.market.maker_evidence_store import EvidenceStore, WriterLock, encoded
from weather.market.maker_replay_bundle import ExportReader
from weather.market.maker_replay_night import calibration, main, module_closure, module_sha256, night
from weather.market import maker_replay_night as module
from tests.market.test_maker_plugin import fixture
from tests.market.test_maker_plugin_dry_run import NOW, layout, csv_rows, jsonl

LATER = NOW + timedelta(days=1)


def setup(tmp_path, *, multi=False, compressed=False, minutes=2):
    args, _, segment = layout(tmp_path, minutes=minutes, compressed=compressed)
    args.day, args.out = args.date, tmp_path / "panel"
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


def live(args, name="snapshot_explanations.jsonl"):
    return next((args.data_root / "snapshots").glob("*/" + name))


def test_one_all_city_bundle_per_date_hashes_append_only_and_no_input_writes(tmp_path, monkeypatch):
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
    report = night(args, now=LATER)
    assert report["status"] == "SEALED" and report["kind"] == "panel"
    assert report["cities"] == ["chicago", "nyc"] == report["bundle"]["captured_band_cities"]
    assert report["restart_events"][0]["reason"] == "RECORDED_88A_RUN"
    assert report["gaps"][0]["reason"] == "STREAM_GAP"
    assert report["active_intervals"] == "MANIFEST_ONLY"
    assert handles and all(h.closed for h in handles)
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    folder = args.out / args.day / "bundle"
    # The exact neutral reader and the scored loader admit the one all-city directory.
    manifest = json.loads((folder / "bundle.json").read_bytes())
    assert all(set(c) == {"condition_id", "market_id", "domain_id", "active_from", "active_until"}
               for c in manifest["conditions"])
    bundle, = load_days([folder], Limits(), lambda: None, now=LATER)
    assert {c.market_id for c in bundle.conditions} == {"chicago", "nyc"}
    for name, binding in report["bundle"]["files"].items():
        raw = (folder / name).read_bytes()
        assert binding == dict(bytes=len(raw), sha256=sha256(raw))
    source = next(r for r in bundle.records if r.kind == "plugin_input" and r.payload["source"] == "source_rows")
    assert source.payload["release_calibration_method"] == "identity"
    ledger = (args.out / "panel-ledger.jsonl").read_bytes()
    row, = map(json.loads, ledger.splitlines())
    assert row["receipt_sha256"] == sha256((args.out / args.day / "receipt.json").read_bytes())
    with pytest.raises(ValueError, match="day_already"):
        night(args, now=LATER)
    assert (args.out / "panel-ledger.jsonl").read_bytes() == ledger
    assert report["runtime_seconds"] > 0 and report["peak_memory_bytes"] > 0
    print("FIXTURE_DAY_BYTES", report["bundle"]["bytes"], report["bundle"]["records"])


@pytest.mark.parametrize("fmt", ["v0.1", "v0.2"])
@pytest.mark.parametrize("bad", [False, True])
def test_receipt_summary_carries_the_clock_trigger_refusals(tmp_path, fmt, bad):
    """Owner decision SWOB-b (2026-10-07): the clock's trigger-row refusal counter is in the receipt
    summary (``bundle``), not only in reader_coverage, with an explicit 0 when nothing was refused."""
    from tests.market.test_maker_plugin_clock_triggers import trigger
    from tests.market.test_maker_plugin_dry_run import NOW as RUN_NOW
    from weather.market import maker_replay_night_v02 as night_v02

    args, _ = setup(tmp_path)
    if bad:
        _, rows, spec, target, _, _ = fixture(now=RUN_NOW)
        row = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
        row.update(observed_at="15:14", current_captured_at_utc=(RUN_NOW - timedelta(minutes=5)).isoformat(),
                   previous_captured_at_utc=(RUN_NOW - timedelta(minutes=6)).isoformat())
        jsonl(args.data_root / "snapshots" / "observation_triggers.jsonl", [row])
    report = night(args, now=LATER) if fmt == "v0.1" else night_v02.export_day(args, "panel", now=LATER)
    assert report["status"] == "SEALED"
    skipped = report["bundle"]["clock_trigger_rows_skipped"]
    coverage = report["reader_coverage"].get("clock.trigger_rows_skipped.observed_at_unparseable", 0)
    assert skipped == {"observed_at_unparseable": coverage}
    assert (coverage > 0) is bad
    assert receipt(args)["bundle"]["clock_trigger_rows_skipped"] == skipped


def test_clock_trigger_rows_skipped_reads_only_the_clock_prefix_and_shows_an_explicit_zero():
    from weather.market.maker_plugin_runner import clock_trigger_rows_skipped

    coverage = {"clock.trigger_rows_skipped.observed_at_unparseable": 7, "clock.trigger_rows_skipped.other": 2,
                "triggers.rows": 9, "clock.other": 4}
    assert clock_trigger_rows_skipped(coverage) == {"observed_at_unparseable": 7, "other": 2}
    assert clock_trigger_rows_skipped({}) == {"observed_at_unparseable": 0}
    assert clock_trigger_rows_skipped(None) == {"observed_at_unparseable": 0}


def test_exclusions_are_manifest_only(tmp_path):
    args, _ = setup(tmp_path)
    with pytest.raises(SystemExit):
        main(["night", "--day", args.day, "--data-root", str(args.data_root), "--out", str(args.out),
              "--exclude-utc", "05:00-08:00"])
    assert not args.out.exists()


def test_calibration_export_is_hazard_kinds_only_and_calibration_dates_only(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, multi=True)
    with pytest.raises(ValueError, match="calibration_dates"):
        calibration(args, now=LATER)
    assert not args.out.exists()
    monkeypatch.setattr(module, "CALIBRATION_DATES", (NOW.date(),))
    report = calibration(args, now=LATER)
    assert report["status"] == "SEALED" and report["kind"] == "calibration"
    assert (args.out / "calibration-ledger.jsonl").is_file() and not (args.out / "panel-ledger.jsonl").exists()
    bundle = load_bundle(args.out / args.day / "bundle")
    assert {r.kind for r in bundle.records} <= {"descriptor", "coverage", "trade"}
    assert {"descriptor", "coverage"} <= {r.kind for r in bundle.records}
    # Quote markets are the captured-band cities of the sealed calibration inventory.
    assert quote_market_rule([bundle]) == ["chicago", "nyc"] == report["bundle"]["captured_band_cities"]
    (tmp_path / "p").mkdir()
    panel, _ = setup(tmp_path / "p", multi=True)
    night(panel, now=LATER)
    assert {c.condition_id for c in bundle.conditions} == {
        c.condition_id for c in load_bundle(panel.out / panel.day / "bundle").conditions}


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
        night(args, now=LATER)
    assert receipt(args)["status"] == "REFUSED"
    assert not (args.out / args.day / "bundle").exists()
    assert before == {p: p.read_bytes() for p in args.data_root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="day_already"):
        night(args, now=LATER)


def grow_after_read(monkeypatch, args, mutate):
    """Mutate a live input only after the export has pinned and read it."""
    path = live(args)
    original = ExportReader.recheck
    def recheck(self):
        key = self._key(path)
        if key in self.prefix and not getattr(self, "_mutated", False):
            self._mutated = True
            mutate(path)
        return original(self)
    monkeypatch.setattr(ExportReader, "recheck", recheck)
    return path


def test_append_only_growth_with_unchanged_prefix_is_accepted(tmp_path, monkeypatch):
    args, _ = setup(tmp_path)
    original = live(args).read_bytes()
    def append(path):
        with path.open("ab") as handle:
            handle.write(b'{"appended_after_pin": true}\n')
    grow_after_read(monkeypatch, args, append)
    report = night(args, now=LATER)
    assert report["status"] == "SEALED"
    assert report["reader_coverage"]["append_only_growth_accepted"] >= 1
    key = next(k for k in report["input_hashes"] if k.endswith("snapshot_explanations.jsonl"))
    assert report["input_hashes"][key] == sha256(original)


@pytest.mark.parametrize("edit", ["prefix", "truncate", "replace"])
def test_edited_truncated_or_replaced_live_input_refuses(tmp_path, monkeypatch, edit):
    args, _ = setup(tmp_path)
    def mutate(path):
        raw = path.read_bytes()
        if edit == "prefix":
            path.write_bytes(b" " + raw[1:] + b'{"more": 1}\n')
        elif edit == "truncate":
            path.write_bytes(raw[:-2])
        else:
            # A replacement may reuse the inode on Linux; its different prefix still refuses.
            path.unlink()
            path.write_bytes(b'{"replaced": true}\n' + raw)
    grow_after_read(monkeypatch, args, mutate)
    with pytest.raises(ValueError, match="source_"):
        night(args, now=LATER)
    assert receipt(args)["status"] == "REFUSED"


@pytest.mark.parametrize("name, partial", [("snapshot_explanations.jsonl", b'{"partial": '),
                                           ("snapshots_long.csv", b"2030-01-10T00:")])
def test_unterminated_trailing_line_is_skipped_and_flagged(tmp_path, name, partial):
    args, _ = setup(tmp_path)
    with live(args, name).open("ab") as handle:
        handle.write(partial)
    report = night(args, now=LATER)
    assert report["status"] == "SEALED"
    assert sum(v for k, v in report["reader_coverage"].items() if k.startswith("unterminated_tail_skipped.")) >= 1


def test_prefix_pinned_reads_are_stable_within_one_export(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    path = root / "live.jsonl"
    path.write_bytes(b'{"a": 1}\n')
    reader = ExportReader(root, 30, 1024**2)
    first = reader.read(path)
    path.write_bytes(path.read_bytes() + b'{"b": 2}\n')
    assert reader.read(path) == first  # Same pinned prefix, never the appended rows.
    assert reader.table(path) == [{"a": 1}]
    reader.recheck()
    assert reader.coverage["append_only_growth_accepted"] == 1


def test_release_projection_and_providers_are_built_once_per_event(tmp_path, monkeypatch):
    from weather.market import maker_plugin_runner, maker_replay_release
    args, _ = setup(tmp_path, minutes=4)
    projections, providers = [], []
    identity = maker_replay_release.event_identity
    monkeypatch.setattr(maker_replay_release, "event_identity", lambda slug: projections.append(slug) or identity(slug))
    fair_value = maker_plugin_runner.WeatherFairValue
    monkeypatch.setattr(maker_plugin_runner, "WeatherFairValue",
                        lambda *a, **k: providers.append(True) or fair_value(*a, **k))
    assert night(args, now=LATER)["status"] == "SEALED"
    assert len(projections) == len(set(projections)) == 1
    assert len(providers) == 1


def test_module_hash_pin_refuses_before_output_and_matches_cli(tmp_path, capsys):
    args, _ = setup(tmp_path)
    args.expected_module_sha256 = "0" * 64
    with pytest.raises(ValueError, match="module_hash_mismatch"):
        night(args, now=LATER)
    assert not args.out.exists()
    assert main(["module-hash"]) == 0
    printed = json.loads(capsys.readouterr().out)
    closure = module_closure()
    assert printed == dict(module_sha256=module_sha256(closure), files=len(closure))
    assert "weather/market/maker_replay_night.py" in closure and "maker_core/replay/bundle.py" in closure
    args.expected_module_sha256 = printed["module_sha256"]
    report = night(args, now=LATER)
    assert report["status"] == "SEALED" and report["module_sha256"] == printed["module_sha256"]


def test_open_day_overlap_and_busy_lock_refuse(tmp_path):
    args, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="closed"):
        night(args, now=NOW)
    assert not args.out.exists()
    out = args.out
    args.out = args.data_root / "output"
    with pytest.raises(ValueError, match="overlap"):
        night(args, now=LATER)
    args.out = out
    args.out.mkdir()
    with WriterLock(args.out), pytest.raises(RuntimeError, match="writer"):
        night(args, now=LATER)


def test_torn_ledger_is_never_repaired_or_appended(tmp_path):
    args, _ = setup(tmp_path)
    args.out.mkdir()
    path = args.out / "panel-ledger.jsonl"
    path.write_bytes(b'{"day":')
    with pytest.raises(ValueError, match="incomplete"):
        night(args, now=LATER)
    assert path.read_bytes() == b'{"day":'
    assert not (args.out / args.day).exists()


def test_cli_uses_requested_surface(tmp_path, monkeypatch, capsys):
    args, _ = setup(tmp_path)
    original = module.night
    monkeypatch.setattr(module, "night", lambda a: original(a, now=LATER))
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
    result = night(args, now=LATER)
    bundle = load_bundle(args.out / args.day / "bundle")
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
        night(args, now=LATER)
    assert receipt(args)["status"] == "REFUSED"


def test_universe_inventory_is_domain_bound_and_verifies_against_descriptors(tmp_path, capsys):
    from maker_core.replay.execution_manifest import _inventory
    from weather.market.maker_replay_universe import universe
    args, _ = setup(tmp_path, multi=True)
    night(args, now=LATER)
    folder = args.out / args.day / "bundle"
    rows = universe([folder])
    bundle = load_bundle(folder)
    assert [r["condition_id"] for r in rows] == sorted(c.condition_id for c in bundle.conditions)
    assert {r["market_id"] for r in rows} == {"chicago", "nyc"}
    assert {r["local_timezone"] for r in rows} == {"America/Chicago", "America/New_York"}
    # The manifest's own binding check accepts the produced inventory.
    assert set(_inventory([bundle], rows, check=lambda: None)) == {r["condition_id"] for r in rows}
    out = tmp_path / "universe.json"
    assert main(["universe", "--bundle", str(folder), "--out", str(out)]) == 0
    assert json.loads(out.read_bytes()) == rows
    assert json.loads(capsys.readouterr().out)["universe_sha256"] == sha256(out.read_bytes())
    with pytest.raises(SystemExit):
        main(["universe", "--bundle", str(folder), "--out", str(out)])  # Create-only.


def test_calibration_receipt_records_trade_clock_skew(tmp_path, monkeypatch):
    from tests.market.test_maker_replay_bundle import record_trades
    args, _ = setup(tmp_path, minutes=1)
    record_trades(args, [(30, 1200), (40, -50)])
    monkeypatch.setattr(module, "CALIBRATION_DATES", (NOW.date(),))
    report = calibration(args, now=LATER)
    assert report["status"] == "SEALED"
    skew = receipt(args)["bundle"]["trade_clock_skew"]
    assert skew["trades"] == 2 and skew["leading_capture"] == 1 and skew["max_us"] == 1_200_000
    assert {r.kind for r in load_bundle(args.out / args.day / "bundle").records} >= {"trade"}


def test_memory_error_records_a_refused_receipt_and_never_leaves_the_day_stuck(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, minutes=1)
    monkeypatch.setattr(module, "export", lambda *a, **k: (_ for _ in ()).throw(MemoryError()))
    with pytest.raises(ValueError, match="MemoryError"):
        night(args, now=LATER)
    refused = receipt(args)
    assert refused["status"] == "REFUSED" and refused["reason"].startswith("MemoryError")
    ledger = [json.loads(line) for line in (args.out / "panel-ledger.jsonl").read_bytes().splitlines()]
    assert [(r["day"], r["status"]) for r in ledger] == [(args.day, "REFUSED")]
    assert not (args.out / args.day / "bundle").exists()
    with pytest.raises(ValueError, match="day_already"):
        night(args, now=LATER)


def test_long_event_lists_are_trimmed_with_count_and_hash_instead_of_refusing(tmp_path, monkeypatch):
    args, _ = setup(tmp_path, minutes=1)
    original = module._inventory
    extra = [dict(segment="00-000000000000", sequence=i, captured_at_utc=NOW.isoformat(),
                  sealed_segment_sha256="0"*64, reason="STREAM_GAP", details={"channel": "trades"}) for i in range(4000)]
    def inventory(reader, day):
        cities, restarts, gaps, seals = original(reader, day)
        return cities, restarts, [*gaps, *extra], seals
    monkeypatch.setattr(module, "_inventory", inventory)
    monkeypatch.setattr(module, "MAX_RECEIPT_BYTES", 65536 + 200_000)
    report = night(args, now=LATER)
    assert report["status"] == "SEALED" and (args.out / args.day / "bundle").is_dir()
    sealed = receipt(args)
    trimmed = sealed["events_trimmed"]["gaps"]
    full = [*original(ExportReader(args.data_root, 60, 10**9), args.day)[2], *extra]
    assert trimmed["total"] == len(full) and trimmed["sha256"] == sha256(canonical_bytes(full))
    assert trimmed["kept"] == len(sealed["gaps"]) < len(full) and sealed["gaps"] == full[:trimmed["kept"]]
    assert "details_omitted" not in sealed
