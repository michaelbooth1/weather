"""MG-2 host input exporter: read-only, known paths only, outcome-free bundles the receiver verifies.

Guards: MG-2 binding plan section 9 (docs/research/mg2-composite-binding-2026-10-25/binding-plan.md) and the master
2026-10-26 exporter brief: known paths only, counts-only coverage, shared-read opens, date window (<= 2026-09-29 or
>= MG-2 D0 under option 2), roll-free stdlib-only module.
"""
import ast
import csv
import gzip
import hashlib
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/weather/calibration/mg2_input_export.py"
D = date(2026, 9, 20)
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
BLOB = b"NBM NBP national bulletin fixture bytes\n"
BLOB_SHA = hashlib.sha256(BLOB).hexdigest()
BANDS = [("lte", 79, 79)] + [("eq", lo, lo + 1) for lo in range(80, 90, 2)] + [("gte", 90, 90)]
LONG_HOST = ("snapshot_id", "captured_at_utc", "captured_at_local", "event_slug", "model_version", "range_label",
             "bin_kind", "bin_value_c", "bin_value_hi_c", "model_probability", "market_yes", "best_bid", "best_ask")
FEAT_HOST = ("snapshot_id", "captured_at_utc", "captured_at_local", "event_slug", "target_date", "model_version",
             "cutoff_hour", "guidance_physical_floor", "high_so_far", "trusted_current_max", "wu_history_high_c")
NBM_HOST = allow.NBM_FIELDS + ("payload_secret_extra",)
SECRET = "99.125"  # a host-only value that must never reach the bundle


def _captures(market, folder_day, target):
    """Local capture times of one folder: the evening before, 03, 09, 14 local, and one after the export cut."""
    tz = ZoneInfo(mx.TZ[market])
    prev = folder_day - timedelta(days=1)
    out = [datetime(prev.year, prev.month, prev.day, 20, 7, tzinfo=tz)]
    out += [datetime(folder_day.year, folder_day.month, folder_day.day, h, 7, tzinfo=tz) for h in (3, 9, 14)]
    late = (allow.export_cut_utc(target) + timedelta(hours=1)).astimezone(tz)
    if folder_day == target:
        out.append(late)
    return out


def _write_csv(path, rows, fields, gz=False):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    data = out.getvalue().encode("utf-8")
    path.write_bytes(gzip.compress(data) if gz else data)


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _folder(data, market, folder_day, target):
    slug = allow.slug_for(market, folder_day)
    folder = data / "snapshots" / slug
    folder.mkdir(parents=True)
    replay, long_rows, features, nbm = [], [], [], []
    for local in _captures(market, folder_day, target):
        sid, utc = local.strftime("%Y%m%dT%H%M%S%z"), local.astimezone(timezone.utc).isoformat()
        metar = [{"raw": "METAR KXXX", "report_time": utc, "temp_native": 70.0, "time": local.strftime("%H:%M")}]
        replay.append({"schema_version": 1, "snapshot_id": sid, "captured_at_utc": utc,
                       "captured_at_local": local.isoformat(), "event_slug": slug,
                       "target_date": folder_day.isoformat(), "model_version": "v-test",
                       "captured_input_hash": "c" * 64, "recorded_distribution": {"80-81": 1.0},
                       "sources": {"metar": {"ok": True, "status": "fresh", "stale": False, "fetched_at": utc,
                                             "data": {"rows": metar, "station_id": "KXXX",
                                                      "target_date_match": True, "report_time": utc,
                                                      "raw": "x", "temp_native": 71.0}},
                                   "open_meteo_multimodel": {"ok": True, "fetched_at": utc, "data": {
                                       "day_model_highs": {"gfs_seamless": 84.0}, "fetched_at": utc,
                                       "target_date_match": True}},
                                   "wu_history": {"ok": True, "data": {"rows": [{"temp_native": float(SECRET)}]}},
                                   "station_observations": {"ok": True, "data": {"rows": []}}}})
        for i, (kind, lo, hi) in enumerate(BANDS):
            unpriced = local.hour == 9 and i == 3
            long_rows.append({"snapshot_id": sid, "captured_at_utc": utc, "captured_at_local": local.isoformat(),
                              "event_slug": slug, "model_version": "v-test", "range_label": f"{kind}{lo}",
                              "bin_kind": kind, "bin_value_c": lo, "bin_value_hi_c": hi if kind == "eq" else "",
                              "model_probability": 0.1, "market_yes": "" if unpriced else SECRET,
                              "best_bid": SECRET, "best_ask": SECRET})
        features.append({"snapshot_id": sid, "captured_at_utc": utc, "captured_at_local": local.isoformat(),
                         "event_slug": slug, "target_date": folder_day.isoformat(), "model_version": "v-test",
                         "cutoff_hour": str(local.hour), "high_so_far": 70.0, "wu_history_high_c": SECRET})
        nbm.append({"snapshot_id": sid, "captured_at_utc": utc, "event_slug": slug, "source": allow.NBM_SOURCE,
                    "status": "fresh", "cycle_key": "nbm-nbp:20260920T01Z", "payload_hash": BLOB_SHA,
                    "payload_ref": allow.blob_ref(BLOB_SHA), "payload_storage_scope": allow.NBM_SCOPE,
                    "payload_bytes": len(BLOB), "payload_secret_extra": SECRET})
        nbm.append({"snapshot_id": sid, "captured_at_utc": utc, "event_slug": slug, "source": "open_meteo_multimodel"})
    _write_jsonl(folder / "replay_inputs.jsonl", replay)
    _write_csv(folder / "snapshots_long.csv", long_rows, LONG_HOST)
    _write_csv(folder / "features_long.csv", features, FEAT_HOST)
    if market == "seattle":  # the long-CSV fallback for the NBM manifest
        _write_csv(folder / "forecast_payloads_long.csv", nbm, NBM_HOST)
    else:
        _write_jsonl(folder / "forecast_payloads.jsonl", nbm)
    # Files the exporter must never open (an unknown name in a known folder).
    (folder / "labels.csv").write_text("winner\n" + SECRET + "\n", encoding="utf-8")
    if folder_day == target:
        tz = ZoneInfo(mx.TZ[market])
        times = [datetime(target.year, target.month, target.day, h, 30, tzinfo=tz) for h in (8, 8, 15)]
        times.append(datetime(target.year, target.month, target.day, 23, 30, tzinfo=tz) + timedelta(hours=2))
        book = [{"capture_id": "c", "captured_at_utc": t.astimezone(timezone.utc).isoformat(), "event_slug": slug,
                 "best_bid": SECRET} for t in times]
        _write_csv(folder / ("order_books_summary.csv.gz" if market == "miami" else "order_books_summary.csv"),
                   book, ("capture_id", "captured_at_utc", "event_slug", "best_bid"), gz=market == "miami")
        ws = [{"received_at_utc": t.astimezone(timezone.utc).isoformat(), "event_slug": slug, "price": SECRET}
              for t in times[:2]]
        _write_csv(folder / "market_ws_events.csv", ws, ("received_at_utc", "event_slug", "price"))
        tape = folder / "execution_tape"
        tape.mkdir()
        _write_jsonl(tape / "trades-00001.jsonl", [{"price": float(SECRET)}] * 3)
        _write_jsonl(tape / "trades-00002.jsonl", [{"price": float(SECRET)}])
        (tape / "orders-00001.jsonl").write_text("{}\n", encoding="utf-8")


def make_host(tmp_path, target=D):
    data = tmp_path / "data"
    for market in allow.MARKETS:
        for offset in (-1, 0, 1):
            _folder(data, market, target + timedelta(days=offset), target)
    cas = data / "forecast_payload_cas" / "sha256" / BLOB_SHA[:2]
    cas.mkdir(parents=True)
    (cas / f"{BLOB_SHA}.blob").write_bytes(BLOB)
    (data / "labels").mkdir()
    return data


def _tree(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


@pytest.fixture
def host(tmp_path):
    return make_host(tmp_path)


def _export(data, tmp_path, day=D, now=NOW):
    out = tmp_path / "out"
    return mx.export(day=day, data_root=data, out=out, now=now), out / day.isoformat()


def test_bundle_holds_only_allowlisted_outcome_free_content(host, tmp_path):
    before = _tree(host)
    manifest, bundle = _export(host, tmp_path)
    assert _tree(host) == before  # read-only
    assert all(v["present"] for v in manifest["markets"].values())
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle).as_posix()
        assert allow.classify_path(rel, D) is not None, rel
        if rel.startswith("forecast_payload_cas/"):
            assert path.read_bytes() == BLOB
            continue
        text = path.read_text(encoding="utf-8")
        assert SECRET not in text and "market_yes" not in text and "wu_history" not in text, rel
        if rel.endswith(".csv"):
            header, *rows = list(csv.reader(io.StringIO(text)))
            assert header == list(allow.CSV_FIELDS[path.name])
            assert all(datetime.fromisoformat(r[1]) <= allow.export_cut_utc(D) for r in rows)
        elif rel.endswith(".jsonl"):
            kind = allow.classify_path(rel, D)[0]
            check = {"replay_inputs": allow.replay_record_problems, "prev_day_metar": allow.prev_day_record_problems,
                     "nbm_manifest": allow.nbm_row_problems}[kind]
            for line in text.splitlines():
                record = json.loads(line)
                assert check(record) == [], (rel, check(record))
                assert record["event_slug"] == rel.split("/")[1]
                assert datetime.fromisoformat(record["captured_at_utc"]) <= allow.export_cut_utc(D)
    assert allow.forbidden_paths(manifest) == []
    assert manifest["schema"] == allow.BUNDLE_SCHEMA and manifest["exporter_schema"] == mx.SCHEMA
    assert manifest["allowlist_sha256"] == allow.allowlist_sha256()
    assert manifest["nbm_blobs"] == {"referenced": 1, "copied": 1, "missing": 0, "hash_mismatch": 0}
    # D folder: 1 late capture per market in replay, long (7 bands) and features.
    assert manifest["dropped_after_cut"] == 11 * (1 + len(BANDS) + 1)
    sources = {e["path"]: e["source_path"] for e in manifest["files"]}
    seattle = allow.slug_for("seattle", D)
    assert sources[f"snapshots/{seattle}/forecast_payloads.jsonl"].endswith("forecast_payloads_long.csv")
    assert sources[f"prev_day/{allow.slug_for('nyc', D - timedelta(days=1))}/metar_rows.jsonl"].endswith(
        "replay_inputs.jsonl")


def test_receiver_verifies_the_exported_bundle(host, tmp_path):
    try:
        from weather.calibration import mg2_inputs as receiver
    except Exception as exc:  # absent before the C7 merge; refuses on the capture host
        pytest.skip(f"receiver not importable here: {exc}")
    _manifest, bundle = _export(host, tmp_path)
    checks, manifest, _sha = receiver.verify_bundle(bundle, D)
    assert {k: v for k, v in checks.items() if v} == {}
    assert manifest["target_date"] == D.isoformat()


def test_coverage_fields_are_counts_only(host, tmp_path):
    manifest, _bundle = _export(host, tmp_path)
    price = manifest["market_price_coverage"]
    assert price["hours_local"] == [7, 16] and price["counts_only"]
    assert set(price["markets"]) == set(allow.MARKETS)
    for entry in price["markets"].values():
        assert entry == {"snapshots_07_16": 2, "priced_07_16": 1, "source_present": True}
    books = manifest["book_coverage"]["markets"]
    for market, entry in books.items():
        name = "order_books_summary.csv.gz" if market == "miami" else "order_books_summary.csv"
        assert entry["order_books_summary"] == {"present": True, "file": name, "rows": 4,
                                                "rows_by_local_hour": {"08": 2, "15": 1}}
        assert entry["market_ws_events"] == {"present": True, "file": "market_ws_events.csv", "rows": 2,
                                             "rows_by_local_hour": {"08": 2}}
        assert entry["execution_tape_trades"] == {"files": 2, "rows": 4}

    def scalars(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from scalars(item)
        elif isinstance(value, list):
            for item in value:
                yield from scalars(item)
        else:
            yield value

    for value in scalars(manifest["book_coverage"]):
        assert value is None or isinstance(value, (bool, int, str)) and not isinstance(value, float)
    assert SECRET not in json.dumps(manifest)


def test_sha256sums_sits_beside_the_bundle_and_matches(host, tmp_path):
    _manifest, bundle = _export(host, tmp_path)
    sums = bundle.parent / f"{D.isoformat()}{mx.SUMS_SUFFIX}"
    lines = sums.read_text(encoding="utf-8").splitlines()
    listed = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in lines}
    files = {f"{D.isoformat()}/{p.relative_to(bundle).as_posix()}": hashlib.sha256(p.read_bytes()).hexdigest()
             for p in bundle.rglob("*") if p.is_file()}
    assert listed == files
    marker = (bundle / allow.MANIFEST_SHA).read_text(encoding="utf-8").strip()
    assert marker == hashlib.sha256((bundle / allow.MANIFEST).read_bytes()).hexdigest()
    assert not list(bundle.parent.glob(".*.partial"))


@pytest.mark.parametrize("day", [date(2026, 9, 30), date(2026, 10, 15), date(2026, 10, 27)])
def test_reserved_dates_are_refused(host, tmp_path, day):
    with pytest.raises(mx.ExportRefused, match="refused"):
        mx.export(day=day, data_root=host, out=tmp_path / "out", now=NOW + timedelta(days=60))
    assert not (tmp_path / "out").exists()


def test_forward_date_needs_its_cut_to_have_passed(tmp_path):
    day = date(2026, 11, 2)
    data = make_host(tmp_path, day)
    with pytest.raises(mx.ExportRefused, match="has not passed"):
        mx.export(day=day, data_root=data, out=tmp_path / "out", now=allow.export_cut_utc(day))
    manifest = mx.export(day=day, data_root=data, out=tmp_path / "out",
                         now=allow.export_cut_utc(day) + timedelta(minutes=1))
    assert manifest["target_date"] == "2026-11-02" and all(v["present"] for v in manifest["markets"].values())


def test_unknown_paths_and_markets_fail_closed(host):
    src = mx.Source(host)
    slug = allow.slug_for("nyc", D)
    for rel in (f"snapshots/{slug}/labels.csv", f"snapshots/{slug}/execution_tape/orders-00001.jsonl",
                f"snapshots/highest-temperature-in-boston-on-september-20-2026/replay_inputs.jsonl",
                f"snapshots/{slug}/../{slug}/replay_inputs.jsonl", "labels/x.csv",
                "forecast_payload_cas/sha256/zz/abc.blob"):
        with pytest.raises(mx.ExportRefused, match="unknown source path"):
            src.read(rel)
    assert src.read(f"snapshots/{allow.slug_for('nyc', D - timedelta(days=9))}/replay_inputs.jsonl") is None
    with pytest.raises(mx.ExportRefused):
        mx.Source(host / "nope")


def test_links_and_reparse_points_are_refused(host, tmp_path):
    slug = allow.slug_for("nyc", D)
    real = host / "snapshots" / slug
    moved = tmp_path / "elsewhere"
    real.rename(moved)
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(moved), str(real))
        else:
            os.symlink(moved, real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"cannot create a link here: {exc}")
    with pytest.raises(mx.ExportRefused, match="link or reparse point"):
        mx.Source(host).read(f"snapshots/{slug}/replay_inputs.jsonl")
    with pytest.raises(mx.ExportRefused, match="link or reparse point"):
        _export(host, tmp_path)
    assert not (tmp_path / "out" / D.isoformat()).exists()


def test_output_guards(host, tmp_path):
    _export(host, tmp_path)
    with pytest.raises(mx.ExportRefused, match="already exists"):
        _export(host, tmp_path)
    (tmp_path / "out" / f".{(D - timedelta(days=1)).isoformat()}.partial").mkdir()
    with pytest.raises(mx.ExportRefused, match="earlier failed run"):
        _export(host, tmp_path, day=D - timedelta(days=1))
    with pytest.raises(mx.ExportRefused, match="inside the capture tree"):
        mx.export(day=D, data_root=host, out=host / "snapshots" / "x", now=NOW)


def test_missing_and_archived_markets_are_reported_and_fail_the_exit(host, tmp_path, capsys):
    (host / "snapshots" / allow.slug_for("denver", D) / "replay_inputs.jsonl").unlink()
    cold = host / "snapshots" / allow.slug_for("austin", D)
    (cold / "replay_inputs.jsonl").unlink()
    (cold / ".cold_archive").mkdir()
    cas = host / "forecast_payload_cas" / "sha256" / BLOB_SHA[:2] / f"{BLOB_SHA}.blob"
    cas.write_bytes(b"tampered")
    out = tmp_path / "out"
    status = mx.main(["--date", D.isoformat(), "--data-root", str(host), "--out", str(out)])
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert status == 3 and report["status"] == "incomplete"
    assert report["absent_markets"] == ["austin", "denver"]
    manifest = json.loads((out / D.isoformat() / allow.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["markets"]["denver"] == {"expected": True, "present": False, "reason": "replay_inputs_missing"}
    assert manifest["markets"]["austin"]["reason"] == "cold_archived_restore_first"
    assert manifest["nbm_blobs"]["hash_mismatch"] == 1 and manifest["nbm_blobs"]["copied"] == 0
    assert not list((out / D.isoformat()).rglob("*.blob"))


def test_cli_success_and_refusal(host, tmp_path, capsys):
    out = tmp_path / "out"
    assert mx.main(["--date", D.isoformat(), "--data-root", str(host), "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out.strip())
    assert report["status"] == "exported" and report["absent_markets"] == []
    assert report["manifest_sha256"] == hashlib.sha256((out / D.isoformat() / allow.MANIFEST).read_bytes()).hexdigest()
    assert mx.main(["--date", "2026-10-10", "--data-root", str(host), "--out", str(out)]) == 2
    assert json.loads(capsys.readouterr().out.strip())["status"] == "refused"


@pytest.mark.skipif(os.name != "nt", reason="share modes are a Windows property")
def test_shared_read_handle_lets_a_writer_append_rename_and_delete(tmp_path):
    target = tmp_path / "live.csv"
    target.write_bytes(b"a\n")
    with mx._share_all_open(target) as handle:
        with open(target, "ab") as writer:  # a capture writer appending while the exporter reads
            writer.write(b"b\n")
        assert handle.read() == b"a\nb\n"
        os.rename(target, tmp_path / "rotated.csv")  # needs FILE_SHARE_DELETE on the reader's handle
        os.unlink(tmp_path / "rotated.csv")
    plain = tmp_path / "plain.csv"
    plain.write_bytes(b"a\n")
    with open(plain, "rb"):  # Python's default open lacks FILE_SHARE_DELETE: the same rename is blocked
        with pytest.raises(PermissionError):
            os.rename(plain, tmp_path / "moved.csv")


def test_module_is_stdlib_plus_allowlist_and_imported_by_nothing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names] if node.module == "weather.calibration" else [""]
            imported.update(f"{node.module}.{n}".rstrip(".") for n in names)
    third = {m for m in imported if m.split(".")[0] not in sys.stdlib_module_names}
    assert third == {"weather.calibration.mg2_input_allowlist"}
    importers = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
                 if p != MODULE and "mg2_input_export" in p.read_text(encoding="utf-8", errors="replace")]
    assert importers == []
    assert mx.SCHEMA == "mg2_input_export/1"
