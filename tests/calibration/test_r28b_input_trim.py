"""Row-28b (a) as-of-capture trim (host) and its workstation verifier, ledger and invariance comparison.

Guards: docs/research/row28b-asof-trim-design-2026-11-04.md and master's rulings of 2026-11-04 (Q1-Q6, the 7..20
gate ruling): the trim reads the published MG-2 bundle only, keeps exactly the records captured at or before
T*(m, D) byte for byte, refuses W1 captures and W2 markets by name, drops prev_day (no prev_dmax), keeps the bundle
format (the bound receiver verifies it unchanged), carries only listed manifest keys plus the r28b_trim block,
refuses every date outside 2026-12-17..2027-01-30 and any run before 2026-12-21 (no override), records a named hole
for a date not exported by its D+1 deadline; the workstation verifier never writes MG-2's ledger and checks the
host-logged manifest sha; the comparison reports booleans, counts and shas only, lists the allowed-to-differ stats
counters by name and STOPs on any other difference; the trim is stdlib plus the allowlist and imported by nothing
but the verifier; the wrapper's plan mode touches nothing. All fixtures are synthetic.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_inputs
from weather.calibration import r28b_input_trim as rt
from weather.calibration import r28b_inputs as ri

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/weather/calibration/r28b_input_trim.py"
D = date(2026, 12, 18)
NOW = datetime(2026, 12, 21, 13, 0, tzinfo=timezone.utc)  # 08:00 Toronto on the first emission-batch day
FINISHED = datetime(2026, 12, 19, 9, 20, tzinfo=timezone.utc)  # 04:20 Toronto on D+1
BLOB_A, BLOB_B = b"NBM bulletin A fixture\n", b"NBM bulletin B fixture\n"
EASTERN = ("atlanta", "miami", "nyc")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _at(market, day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(rt.TZ[market])).astimezone(timezone.utc)


def _snapshots(market):
    """(captured_utc, cutoff_hour text) of one market's D folder."""
    snaps = [(_at(market, D - timedelta(days=1), 22), "22"), (_at(market, D, 9, 5), "9"), (_at(market, D, 13, 10), "13"),
             (_at(market, D, 16, 40), "16"), (_at(market, D, 17, 5), "17"), (_at(market, D, 19, 30), "19"),
             (_at(market, D, 23, 50), "23")]
    if market in EASTERN:
        snaps.append((_at(market, D + timedelta(days=1), 1, 0), "16"))  # W1: a stale cutoff after local midnight
    if market == "seattle":
        snaps.append((_at(market, D, 19, 10), "16"))  # a WU print stall: T* moves to 19:10, disclosed as late
    if market == "chicago":
        snaps.append((_at(market, D, 18, 0), "16.5"))  # unparseable: never sets T*
    if market == "austin":
        snaps.append((_at(market, D, 17, 30), "16.0"))  # integral float text: accepted (a superset of the emitter)
    if market == "denver":
        snaps = [(c, "") for c, _ in snaps]  # no parseable cutoff at all: W2
    return sorted(snaps)


def _csv_bytes(fields, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow([row.get(k, "") for k in fields])
    return buffer.getvalue().encode("utf-8")


def _jsonl_bytes(rows):
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")


def _nbm_row(market, slug, captured, blob):
    digest = _sha(blob)
    row = {k: "" for k in allow.NBM_FIELDS}
    row.update(snapshot_id=f"{market}-nbm-{captured:%H%M}", captured_at_utc=captured.isoformat(), event_slug=slug,
               source=allow.NBM_SOURCE, status="ok", payload_hash=digest, payload_ref=allow.blob_ref(digest),
               payload_storage_scope=allow.NBM_SCOPE, payload_bytes=len(blob))
    return row


def make_source(tmp_path, day=D, finished=FINISHED, extra_manifest=None, drop=()):
    """A published MG-2 bundle (format of mg2_input_export) under <tmp>/data/exports/mg2-inputs/<D>/."""
    root = tmp_path / "data" / "exports" / "mg2-inputs"
    bundle = root / day.isoformat()
    files = {}
    for market in allow.MARKETS:
        slug = allow.slug_for(market, day)
        replay, longs, feats = [], [], []
        for n, (captured, cutoff) in enumerate(_snapshots(market)):
            sid = f"{market}-{n}"
            local = captured.astimezone(ZoneInfo(rt.TZ[market])).isoformat()
            replay.append({"schema_version": 1, "snapshot_id": sid, "captured_at_utc": captured.isoformat(),
                           "captured_at_local": local, "event_slug": slug, "target_date": day.isoformat(),
                           "model_version": "v", "captured_input_hash": "h",
                           "sources": {"metar": {"ok": True, "status": "ok",
                                                 "data": {"rows": [{"raw": f"METAR {sid}"}], "station_id": "K"}}}})
            for band in ('80-81 F, "eq"', "82 or above"):
                longs.append({"snapshot_id": sid, "captured_at_utc": captured.isoformat(), "captured_at_local": local,
                              "event_slug": slug, "model_version": "v", "range_label": band, "bin_kind": "eq",
                              "bin_value_c": "26.7", "bin_value_hi_c": "27.2", "model_probability": "0.5"})
            feats.append({"snapshot_id": sid, "captured_at_utc": captured.isoformat(), "captured_at_local": local,
                          "event_slug": slug, "target_date": day.isoformat(), "model_version": "v",
                          "cutoff_hour": cutoff, "guidance_physical_floor": "", "high_so_far": "70",
                          "trusted_current_max": "70"})
        files[f"snapshots/{slug}/replay_inputs.jsonl"] = _jsonl_bytes(replay)
        files[f"snapshots/{slug}/snapshots_long.csv"] = _csv_bytes(allow.CSV_FIELDS["snapshots_long.csv"], longs)
        if not (market == "houston" and "houston_features" in drop):
            files[f"snapshots/{slug}/features_long.csv"] = _csv_bytes(allow.CSV_FIELDS["features_long.csv"], feats)
        for offset, captured, blob in ((-1, _at(market, day - timedelta(days=1), 12), BLOB_A),
                                       (0, _at(market, day, 8), BLOB_A), (0, _at(market, day, 20), BLOB_B),
                                       (1, _at(market, day, 21), BLOB_B)):
            fslug = allow.slug_for(market, day + timedelta(days=offset))
            rel = f"snapshots/{fslug}/forecast_payloads.jsonl"
            files[rel] = files.get(rel, b"") + _jsonl_bytes([_nbm_row(market, fslug, captured, blob)])
        prev = allow.slug_for(market, day - timedelta(days=1))
        files[f"prev_day/{prev}/metar_rows.jsonl"] = _jsonl_bytes([{
            "snapshot_id": f"{market}-prev", "captured_at_utc": _at(market, day - timedelta(days=1), 23).isoformat(),
            "captured_at_local": "x", "event_slug": prev, "target_date": (day - timedelta(days=1)).isoformat(),
            "rows": [{"raw": "METAR prev"}]}])
    for blob in (BLOB_A, BLOB_B):
        files[f"forecast_payload_cas/{allow.blob_ref(_sha(blob))}"] = blob
    entries = []
    for rel, data in sorted(files.items()):
        target = bundle.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        kind = allow.classify_path(rel, day)[0]
        rows = (None if kind == "nbm_blob" else
                data.count(b"\n") - 1 if kind in ("snapshots_long", "features_long") else data.count(b"\n"))
        entries.append({"path": rel, "sha256": _sha(data), "bytes": len(data), "rows": rows, "source_path": rel,
                        "source_bytes": len(data), "read_mode": "bounded_range_at_open"})
    manifest = {"schema": allow.BUNDLE_SCHEMA, "exporter_schema": "mg2_input_export/1",
                "target_date": day.isoformat(), "export_cut_utc": allow.export_cut_utc(day).isoformat(),
                "export_started_utc": (finished - timedelta(minutes=5)).isoformat(),
                "export_finished_utc": finished.isoformat(), "allowlist_sha256": allow.allowlist_sha256(),
                "exporter_sha256": "e" * 64, "host_repo_head": "a" * 40, "files": entries,
                "markets": {m: {"expected": True, "present": True, "reason": None} for m in allow.MARKETS},
                "nbm_blobs": {"referenced": 2, "copied": 2, "missing": 0, "hash_mismatch": 0},
                "dropped_after_cut": 0, "nbm_rows_bad_ref": 0, "min_quiet_seconds": 1800,
                "read_mode": "bounded_range_at_open", "coverage_counts": False, **(extra_manifest or {})}
    body = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
    (bundle / allow.MANIFEST).write_bytes(body)
    (bundle / allow.MANIFEST_SHA).write_bytes((_sha(body) + "\n").encode("ascii"))
    iso = day.isoformat()
    lines = [f"{_sha(body)}  {iso}/{allow.MANIFEST}",
             f"{_sha((bundle / allow.MANIFEST_SHA).read_bytes())}  {iso}/{allow.MANIFEST_SHA}"]
    lines += [f"{e['sha256']}  {iso}/{e['path']}" for e in entries]
    (root / f"{iso}{rt.SUMS_SUFFIX}").write_bytes(("\n".join(sorted(lines, key=lambda s: s.split("  ", 1)[1]))
                                                   + "\n").encode("utf-8"))
    return root


def _out(tmp_path):
    return tmp_path / "data" / "exports" / "r28b-inputs"


def _trim(tmp_path, source, day=D, now=NOW):
    return rt.trim(day=day, source_root=source, out=_out(tmp_path), now=now)


def _lines(path):
    with open(path, "rb") as handle:
        return list(handle)


def _all_checks_clean(checks, allowed_markets=()):
    extra = {k: [p for p in v if not (k == "markets" and p in {f"market_missing:{m}" for m in allowed_markets})]
             for k, v in checks.items()}
    return all(not v for v in extra.values()), extra


@pytest.fixture
def source(tmp_path):
    return make_source(tmp_path)


# ----------------------------------------------------------------------------- the host trim

def test_the_synthetic_source_is_a_valid_mg2_bundle(source):
    checks, _manifest, _sha256 = mg2_inputs.verify_bundle(source / D.isoformat(), D)
    assert _all_checks_clean(checks)[0], checks


def test_trimmed_bundle_keeps_the_format_and_passes_the_bound_receiver(source, tmp_path):
    result = _trim(tmp_path, source)
    assert result["status"] == "trimmed" and result["refused_markets"] == {"denver": rt.W2}
    bundle = _out(tmp_path) / D.isoformat()
    checks, manifest, manifest_sha = mg2_inputs.verify_bundle(bundle, D)
    ok, extra = _all_checks_clean(checks, allowed_markets=("denver",))
    assert ok, extra
    assert manifest_sha == result["manifest_sha256"]
    assert manifest["schema"] == allow.BUNDLE_SCHEMA and manifest["allowlist_sha256"] == allow.allowlist_sha256()
    assert not any(p.startswith("prev_day/") for p in (e["path"] for e in manifest["files"]))
    assert not (bundle / "prev_day").exists()
    block = manifest["r28b_trim"]
    assert block["schema"] == rt.SCHEMA and block["prev_day"] == "dropped" and block["h_last"] == 16
    assert block["trim_module_sha256"] == _sha(MODULE.read_bytes())
    assert block["source_manifest_sha256"] == _sha((source / D.isoformat() / allow.MANIFEST).read_bytes())
    assert block["walls"] == {"W1": rt.W1, "W2": rt.W2}
    sums = (_out(tmp_path) / f"{D.isoformat()}{rt.SUMS_SUFFIX}").read_text(encoding="utf-8")
    assert f"{manifest_sha}  {D.isoformat()}/manifest.json" in sums


def test_only_listed_manifest_keys_travel_never_a_coverage_block(tmp_path):
    source = make_source(tmp_path, extra_manifest={"market_price_coverage": {"counts_only": True},
                                                   "book_coverage": {"counts_only": True}})
    _trim(tmp_path, source)
    manifest = json.loads((_out(tmp_path) / D.isoformat() / allow.MANIFEST).read_bytes())
    assert "market_price_coverage" not in manifest and "book_coverage" not in manifest
    assert manifest["coverage_counts"] is False
    assert set(manifest) == set(rt.COPY_KEYS) | {"files", "markets", "nbm_blobs", "coverage_counts", "r28b_trim"}


def test_kept_lines_are_byte_identical_and_exactly_those_captured_by_t_star(source, tmp_path):
    _trim(tmp_path, source)
    manifest = json.loads((_out(tmp_path) / D.isoformat() / allow.MANIFEST).read_bytes())
    for market in allow.MARKETS:
        if market == "denver":
            continue
        star = datetime.fromisoformat(manifest["r28b_trim"]["markets"][market]["t_star_utc"])
        slug = allow.slug_for(market, D)
        src = _lines(source / D.isoformat() / "snapshots" / slug / "replay_inputs.jsonl")
        want = [line for line in src if datetime.fromisoformat(json.loads(line)["captured_at_utc"]) <= star]
        assert _lines(_out(tmp_path) / D.isoformat() / "snapshots" / slug / "replay_inputs.jsonl") == want
        for name in ("snapshots_long.csv", "features_long.csv"):
            src = _lines(source / D.isoformat() / "snapshots" / slug / name)
            got = _lines(_out(tmp_path) / D.isoformat() / "snapshots" / slug / name)
            assert got[0] == src[0] and set(got[1:]) <= set(src[1:])
            assert [line for line in src[1:] if line in got[1:]] == got[1:]  # the source order, byte for byte
            for line in src[1:]:
                captured = datetime.fromisoformat(next(csv.reader([line.decode()]))[1])
                assert (line in got) == (captured <= star)


def test_t_star_is_the_last_snapshot_with_a_cutoff_of_at_most_16(source, tmp_path):
    _trim(tmp_path, source)
    stars = json.loads((_out(tmp_path) / D.isoformat() / allow.MANIFEST).read_bytes())["r28b_trim"]["markets"]
    assert stars["dallas"]["t_star_utc"] == _at("dallas", D, 16, 40).isoformat()
    assert stars["dallas"]["t_star_local_hour"] == 16 and stars["dallas"]["late_t_star"] is False
    assert stars["seattle"]["t_star_utc"] == _at("seattle", D, 19, 10).isoformat()  # the stall is kept, disclosed
    assert stars["seattle"]["late_t_star"] is True
    assert stars["austin"]["t_star_utc"] == _at("austin", D, 17, 30).isoformat()  # "16.0" accepted
    assert stars["chicago"]["t_star_utc"] == _at("chicago", D, 16, 40).isoformat()  # "16.5" ignored
    assert stars["chicago"]["cutoff_unparseable"] == 1


def test_w1_refuses_a_capture_after_local_midnight_by_name(source, tmp_path):
    _trim(tmp_path, source)
    bundle = _out(tmp_path) / D.isoformat()
    stars = json.loads((bundle / allow.MANIFEST).read_bytes())["r28b_trim"]["markets"]
    for market in EASTERN:
        assert stars[market]["w1_excluded"] == 1
        assert stars[market]["t_star_utc"] == _at(market, D, 16, 40).isoformat()
        slug = allow.slug_for(market, D)
        times = [json.loads(line)["captured_at_utc"] for line in _lines(bundle / "snapshots" / slug /
                                                                         "replay_inputs.jsonl")]
        assert _at(market, D + timedelta(days=1), 1).isoformat() not in times
    assert all(stars[m]["w1_excluded"] == 0 for m in ("dallas", "seattle"))


def test_w2_refuses_the_market_by_name_and_none_of_its_files_travel(tmp_path):
    source = make_source(tmp_path, drop=("houston_features",))
    result = _trim(tmp_path, source)
    assert result["refused_markets"] == {"denver": rt.W2, "houston": rt.W2}
    manifest = json.loads((_out(tmp_path) / D.isoformat() / allow.MANIFEST).read_bytes())
    for market in ("denver", "houston"):
        assert manifest["markets"][market] == {"expected": True, "present": False, "reason": rt.W2}
        assert not any(allow.classify_path(e["path"], D)[1] == market for e in manifest["files"])
    assert result["absent_markets"] == ["denver", "houston"]


def test_nbm_rows_after_t_star_are_dropped_and_their_blob_pruned(source, tmp_path):
    result = _trim(tmp_path, source)
    bundle = _out(tmp_path) / D.isoformat()
    assert (bundle / "forecast_payload_cas" / allow.blob_ref(_sha(BLOB_A))).read_bytes() == BLOB_A
    assert not (bundle / "forecast_payload_cas" / allow.blob_ref(_sha(BLOB_B))).exists()
    assert result["nbm_blobs"] == {"referenced": 1, "copied": 1, "missing": 0, "hash_mismatch": 0}
    nyc = allow.slug_for("nyc", D + timedelta(days=1))
    assert _lines(bundle / "snapshots" / nyc / "forecast_payloads.jsonl") == []


@pytest.mark.parametrize("day", [date(2026, 12, 16), date(2027, 1, 31), date(2026, 9, 28), date(2026, 10, 29)])
def test_dates_outside_the_row28b_window_are_refused_with_no_override(source, tmp_path, day):
    with pytest.raises(rt.TrimRefused, match="outside the row-28b input window"):
        _trim(tmp_path, source, day=day)
    assert not _out(tmp_path).exists()


def test_no_run_before_the_first_emission_batch(source, tmp_path):
    with pytest.raises(rt.TrimRefused, match="first emission batch"):
        _trim(tmp_path, source, now=datetime(2026, 12, 20, 13, tzinfo=timezone.utc))


def test_an_absent_bundle_is_not_ready_before_its_deadline_and_a_named_hole_after(tmp_path):
    root = tmp_path / "data" / "exports" / "mg2-inputs"
    root.mkdir(parents=True)
    day = date(2026, 12, 20)
    with pytest.raises(rt.NotReady):
        _trim(tmp_path, root, day=day, now=datetime(2026, 12, 21, 13, 30, tzinfo=timezone.utc))
    assert not _out(tmp_path).exists()
    result = _trim(tmp_path, root, day=day, now=datetime(2026, 12, 21, 14, 30, tzinfo=timezone.utc))
    assert result["status"] == "hole" and result["reason"] == rt.HOLE_NOT_EXPORTED
    hole = json.loads(rt.hole_path(_out(tmp_path), day).read_bytes())
    assert hole["schema"] == rt.HOLE_SCHEMA and hole["deadline_utc"] == rt.deadline_utc(day).isoformat()
    assert result["hole_sha256"] == _sha(rt.hole_path(_out(tmp_path), day).read_bytes())
    make_source(tmp_path, day=day, finished=datetime(2026, 12, 21, 9, 20, tzinfo=timezone.utc))
    again = _trim(tmp_path, root, day=day)  # a bundle that turns up later never replaces the hole
    assert again["status"] == "hole" and again["already_recorded"] is True
    assert not (_out(tmp_path) / day.isoformat()).exists()


def test_a_bundle_finished_after_its_deadline_is_a_named_hole(tmp_path):
    source = make_source(tmp_path, finished=datetime(2026, 12, 19, 14, 30, tzinfo=timezone.utc))
    result = _trim(tmp_path, source)
    assert result["status"] == "hole" and result["reason"] == rt.HOLE_EXPORTED_LATE
    assert not (_out(tmp_path) / D.isoformat()).exists()


def test_source_integrity_is_verified_before_any_trim(source, tmp_path):
    bundle = source / D.isoformat()
    target = bundle / "snapshots" / allow.slug_for("nyc", D) / "replay_inputs.jsonl"
    original = target.read_bytes()
    target.write_bytes(original + b"\n")
    with pytest.raises(rt.TrimRefused, match="changed since export"):
        _trim(tmp_path, source)
    target.write_bytes(original)
    extra = bundle / "snapshots" / allow.slug_for("nyc", D) / "notes.txt"
    extra.write_text("x", encoding="utf-8")
    with pytest.raises(rt.TrimRefused, match="unlisted file"):
        _trim(tmp_path, source)
    extra.unlink()
    sums = source / f"{D.isoformat()}{rt.SUMS_SUFFIX}"
    sums.write_text(sums.read_text(encoding="utf-8").replace("a", "b", 1), encoding="utf-8")
    with pytest.raises(rt.TrimRefused, match="SHA256SUMS"):
        _trim(tmp_path, source)
    assert not (_out(tmp_path) / D.isoformat()).exists()


def test_roots_are_guarded_and_the_trim_is_write_once(source, tmp_path):
    other = tmp_path / "elsewhere"
    shutil.copytree(source, other)
    with pytest.raises(rt.TrimRefused, match="published MG-2 export root"):
        rt.trim(day=D, source_root=other, out=_out(tmp_path), now=NOW)
    with pytest.raises(rt.TrimRefused, match="inside"):
        rt.trim(day=D, source_root=source, out=source / "r28b", now=NOW)
    with pytest.raises(rt.TrimRefused, match="inside"):
        rt.trim(day=D, source_root=source, out=tmp_path / "data" / "snapshots" / "x", now=NOW)
    _trim(tmp_path, source)
    with pytest.raises(rt.TrimRefused, match="one trim per date"):
        _trim(tmp_path, source)


def test_a_forbidden_key_in_a_kept_record_refuses_the_date(tmp_path):
    source = make_source(tmp_path)
    bundle = source / D.isoformat()
    rel = f"snapshots/{allow.slug_for('nyc', D)}/replay_inputs.jsonl"
    lines = _lines(bundle / rel)
    record = json.loads(lines[1])
    record["sources"]["metar"]["data"]["rows"][0]["settlement_high"] = 1
    lines[1] = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    data = b"".join(lines)
    (bundle / rel).write_bytes(data)
    manifest = json.loads((bundle / allow.MANIFEST).read_bytes())
    for entry in manifest["files"]:
        if entry["path"] == rel:
            entry.update(sha256=_sha(data), bytes=len(data))
    body = json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8")
    (bundle / allow.MANIFEST).write_bytes(body)
    (bundle / allow.MANIFEST_SHA).write_bytes((_sha(body) + "\n").encode("ascii"))
    sums = source / f"{D.isoformat()}{rt.SUMS_SUFFIX}"
    text = sums.read_text(encoding="utf-8").splitlines()
    fixed = {f"{D.isoformat()}/{allow.MANIFEST}": _sha(body), f"{D.isoformat()}/{rel}": _sha(data),
             f"{D.isoformat()}/{allow.MANIFEST_SHA}": _sha((bundle / allow.MANIFEST_SHA).read_bytes())}
    sums.write_text("\n".join(f"{fixed.get(l.split('  ', 1)[1], l.split('  ', 1)[0])}  {l.split('  ', 1)[1]}"
                              for l in text) + "\n", encoding="utf-8")
    with pytest.raises(rt.TrimRefused, match="forbidden or unlisted"):
        _trim(tmp_path, source)
    assert not (_out(tmp_path) / D.isoformat()).exists()
    assert not (_out(tmp_path) / f".{D.isoformat()}.partial").exists()


def test_cli_exit_codes(source, tmp_path, capsys):
    args = ["--source-root", str(source), "--out", str(_out(tmp_path))]
    assert rt.main(["--date", D.isoformat(), *args], now=NOW) == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["status"] == "trimmed" and "settlement" not in json.dumps(line)
    assert rt.main(["--date", "2027-01-31", *args], now=NOW) == 2
    assert rt.main(["--date", "2026-12-20", *args], now=datetime(2026, 12, 21, 13, 30, tzinfo=timezone.utc)) == 3
    assert rt.main(["--date", "2026-12-20", *args], now=datetime(2026, 12, 21, 14, 30, tzinfo=timezone.utc)) == 4


def test_cutoff_parse_is_a_superset_of_the_emitters():
    for text in ("7", "16", " 16", "20"):
        assert rt.cutoff_value(text) == int(str(text))
    assert rt.cutoff_value("16.0") == 16
    for text in (None, "", "x", "16.5", "nan", "inf"):
        assert rt.cutoff_value(text) is None


def test_trim_is_stdlib_plus_allowlist_and_imported_only_by_the_verifier():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names] if node.module == "weather.calibration" else [""]
            imported.update(f"{node.module}.{n}".rstrip(".") for n in names)
    assert {m for m in imported if m.split(".")[0] not in sys.stdlib_module_names} == {
        "weather.calibration.mg2_input_allowlist"}
    importers = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
                       if p != MODULE and "r28b_input_trim" in p.read_text(encoding="utf-8", errors="replace"))
    assert importers == ["src/weather/calibration/r28b_inputs.py"]


def test_constants_match_the_bound_modules():
    from weather.calibration import mg2_composite
    from weather.calibration import mg2_input_export
    assert rt.TZ == mg2_input_export.TZ
    assert rt.PRODUCTION_PREFIXES == mg2_composite._PRODUCTION_PREFIXES
    assert (rt.WINDOW_FIRST, rt.WINDOW_LAST, rt.FIRST_RUN, rt.H_LAST) == (
        date(2026, 12, 17), date(2027, 1, 30), date(2026, 12, 21), 16)


def test_a_production_importer_is_refused(monkeypatch):
    monkeypatch.delitem(sys.modules, "weather.calibration.r28b_input_trim")
    with pytest.raises(ImportError, match="one-shot"):
        exec("import importlib\nimportlib.import_module('weather.calibration.r28b_input_trim')",
             {"__name__": "weather.operations.fixture"})


# ----------------------------------------------------------------------------- the workstation verifier

def _ledger(tmp_path):
    return tmp_path / "ws" / "r28b" / "input_receipts.jsonl"


def test_verify_accepts_the_trimmed_bundle_against_the_host_logged_sha(source, tmp_path):
    result = _trim(tmp_path, source)
    bundle = _out(tmp_path) / D.isoformat()
    receipt = ri.verify(bundle=bundle, day=D, expected_manifest_sha=result["manifest_sha256"],
                        trim_module_sha=_sha(MODULE.read_bytes()), ledger=_ledger(tmp_path))
    assert receipt["status"] == "verified", receipt["problems"]
    assert receipt["absent_markets"] == ["denver"]
    again = ri.verify(bundle=bundle, day=D, expected_manifest_sha=result["manifest_sha256"],
                      trim_module_sha=_sha(MODULE.read_bytes()), ledger=_ledger(tmp_path))
    assert again["status"] == "already_recorded"
    assert len(ri.read_ledger(_ledger(tmp_path))) == 1


def test_verify_refuses_an_unlogged_sha_an_unpinned_module_and_a_tampered_file(source, tmp_path):
    result = _trim(tmp_path, source)
    bundle = _out(tmp_path) / D.isoformat()
    module_sha = _sha(MODULE.read_bytes())
    bad = ri.verify(bundle=bundle, day=D, expected_manifest_sha="0" * 64, trim_module_sha=module_sha,
                    ledger=_ledger(tmp_path))
    assert bad["status"] == "refused" and "manifest_sha_not_the_host_logged_sha" in bad["problems"]
    bad = ri.verify(bundle=bundle, day=D, expected_manifest_sha=result["manifest_sha256"], trim_module_sha="1" * 64,
                    ledger=_ledger(tmp_path))
    assert "trim_module_sha_not_pinned" in bad["problems"]
    target = bundle / "snapshots" / allow.slug_for("nyc", D) / "features_long.csv"
    target.write_bytes(target.read_bytes() + b"x\n")
    bad = ri.verify(bundle=bundle, day=D, expected_manifest_sha=result["manifest_sha256"],
                    trim_module_sha=module_sha, ledger=_ledger(tmp_path))
    assert bad["status"] == "refused" and any(p.startswith("files_match:") for p in bad["problems"])
    assert all(r["status"] == "refused" for r in ri.read_ledger(_ledger(tmp_path)))


def test_the_verifier_never_writes_mg2s_ledger_and_refuses_other_dates(source, tmp_path):
    with pytest.raises(ri.R28bRefused, match="MG-2's input ledger"):
        ri.record_hole(day=D, reason=rt.HOLE_NOT_EXPORTED, host_hole_sha="2" * 64, ledger=mg2_inputs.LEDGER)
    with pytest.raises(ri.R28bRefused, match="outside the row-28b input window"):
        ri.verify(bundle=tmp_path, day=date(2027, 1, 31), expected_manifest_sha="0" * 64,
                  trim_module_sha="0" * 64, ledger=_ledger(tmp_path))


def test_a_host_named_hole_is_recorded_once(tmp_path):
    row = ri.record_hole(day=D, reason=rt.HOLE_NOT_EXPORTED, host_hole_sha="2" * 64, ledger=_ledger(tmp_path))
    assert row["status"] == "hole" and row["kind"] == "hole"
    with pytest.raises(ri.R28bRefused, match="already has"):
        ri.record_hole(day=D, reason=rt.HOLE_NOT_EXPORTED, host_hole_sha="2" * 64, ledger=_ledger(tmp_path))
    with pytest.raises(ri.R28bRefused, match="unknown hole reason"):
        ri.record_hole(day=date(2026, 12, 19), reason="other", host_hole_sha="2" * 64, ledger=_ledger(tmp_path))


# ----------------------------------------------------------------------------- the invariance comparison (Q6)

class _FakeRefused(RuntimeError):
    pass


def _fake_emitter():
    def read_snapshots(path, first, last):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def shadow_rows(state, snaps, replay_root, first, last, markets, presence=None):
        presence["__holes__"] = snaps["holes"]
        return [tuple(r) for r in snaps["rows"]], snaps["stats"], {}

    def refuse_absent_emit_sources(snaps, presence, first, last, markets):
        if snaps.get("refuse"):
            raise _FakeRefused(snaps["refuse"])

    def emit_holes(rows, presence, first, last, markets):
        return presence["__holes__"]

    yr = SimpleNamespace(EMIT_MARKETS=("nyc",), YearroundRefused=_FakeRefused, guard_path=Path,
                         read_snapshots=read_snapshots, shadow_rows=shadow_rows,
                         refuse_absent_emit_sources=refuse_absent_emit_sources, emit_holes=emit_holes)
    p3 = SimpleNamespace(load_state=lambda path, sha, forward: {"sha": sha, "forward": forward},
                         jsonl_line=lambda m, sid, t, d: json.dumps([m, sid, t, d], sort_keys=True) + "\n")
    return yr, p3


BASE = {"rows": [["nyc", "nyc-3", "2026-12-17", "k", {"60": 0.25, "61": 0.75}]],
        "holes": [{"market": "nyc", "target_date": "2026-12-18", "rows": 0, "reason": "no_row_served"}],
        "stats": {"nyc": {"emitted": 1, "outside_cutoff_hours": 4, "no_fit_for_hour": 2, "replay_hours": 2,
                          "no_usable_nbm": 0, "missing_metar_feature": 0, "coverage_fallback": []}}}


def _compare(tmp_path, monkeypatch, trimmed, name="report.json"):
    monkeypatch.setattr(ri, "_emitter", _fake_emitter)
    full_path, trim_path = tmp_path / "full.json", tmp_path / f"trim-{name}"
    full_path.write_text(json.dumps(BASE), encoding="utf-8")
    trim_path.write_text(json.dumps(trimmed), encoding="utf-8")
    return ri.compare(state=tmp_path / "state.pkl", state_sha="5" * 64, first=date(2026, 12, 17),
                      last=date(2026, 12, 20), full_snapshots=full_path, full_replay_root=tmp_path,
                      trimmed_snapshots=trim_path, trimmed_replay_root=tmp_path, out=tmp_path / name,
                      ledger=_ledger(tmp_path))


def _variant(**changes):
    out = json.loads(json.dumps(BASE))
    for key, value in changes.items():
        if key == "stats":
            out["stats"]["nyc"].update(value)
        else:
            out[key] = value
    return out


def test_equal_sides_pass_and_open_the_gate_with_allowed_counters_named(tmp_path, monkeypatch):
    report = _compare(tmp_path, monkeypatch, _variant(stats={"outside_cutoff_hours": 1, "no_fit_for_hour": 0}))
    assert report["verdict"] == "PASS" and report["shadow_rows_equal"] and report["hole_keys_equal"]
    assert report["stats_allowed_to_differ"] == ["outside_cutoff_hours", "no_fit_for_hour", "replay_hours"]
    assert report["stats_differing_allowed"] == ["no_fit_for_hour", "outside_cutoff_hours"]
    assert report["stats_differing_disallowed"] == []
    assert ri.emit_allowed(_ledger(tmp_path)) is True
    text = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "0.75" not in text and "nyc-3" not in text and "2026-12-18" not in text  # no values, keys or rows


@pytest.mark.parametrize("trimmed,flag", [
    (_variant(rows=[["nyc", "nyc-3", "2026-12-17", "k", {"60": 0.5, "61": 0.5}]]), "shadow_rows_equal"),
    (_variant(holes=[]), "hole_keys_equal"),
    (_variant(refuse="captured_metar_replay"), "refusal_equal"),
    (_variant(stats={"no_usable_nbm": 1}), "stats_differing_disallowed"),
])
def test_any_other_difference_is_a_stop_and_closes_the_gate(tmp_path, monkeypatch, trimmed, flag):
    report = _compare(tmp_path, monkeypatch, trimmed)
    assert report["verdict"] == "STOP"
    assert (report[flag] is False) if flag != "stats_differing_disallowed" else report[flag] == ["no_usable_nbm"]
    assert (_ledger(tmp_path).parent / ri.STOP_MARKER).exists()
    assert ri.emit_allowed(_ledger(tmp_path)) is False
    # a later PASS does not reopen the gate while master's STOP marker stands
    _compare(tmp_path, monkeypatch, _variant(), name="again.json")
    assert ri.emit_allowed(_ledger(tmp_path)) is False


def test_a_hole_reason_may_move_but_the_hole_keys_must_not(tmp_path, monkeypatch):
    moved = _variant(holes=[{"market": "nyc", "target_date": "2026-12-18", "rows": 0,
                             "reason": "no_snapshot_at_a_scored_cutoff"}])
    assert _compare(tmp_path, monkeypatch, moved)["verdict"] == "PASS"


def test_the_gate_is_closed_without_a_comparison(tmp_path):
    assert ri.emit_allowed(_ledger(tmp_path)) is False


def test_compare_refuses_a_batch_outside_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "_emitter", _fake_emitter)
    with pytest.raises(ri.R28bRefused):
        ri.compare(state=tmp_path, state_sha="5" * 64, first=date(2027, 1, 30), last=date(2027, 2, 2),
                   full_snapshots=tmp_path, full_replay_root=tmp_path, trimmed_snapshots=tmp_path,
                   trimmed_replay_root=tmp_path, out=tmp_path / "r.json", ledger=_ledger(tmp_path))


# ----------------------------------------------------------------------------- the host wrapper

OPS = ROOT / "scripts" / "ops"
POWERSHELL = shutil.which("powershell.exe") if os.name == "nt" else None


def test_the_wrapper_registers_nothing_and_never_names_the_bound_exporter():
    code = "\n".join(line for line in (OPS / "r28b_input_trim.ps1").read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    for word in ("Register-ScheduledTask", "schtasks", "New-ScheduledTask", "mg2_input_export",
                 "--coverage-counts"):
        assert word not in code
    assert "Enter-WeatherHeavyWorkloadLease" in code and "-Workload 'r28b_input_trim'" in code
    assert "if ($null -eq $lease)" in code


@pytest.mark.spawns
@pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell")
def test_wrapper_plan_touches_nothing(tmp_path):
    root = tmp_path / "prod repo"
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(OPS / "r28b_input_trim.ps1"), "-ProductionRepoRoot", str(root),
                             "-Date", "2026-12-17,2026-12-18", "-PlanOnly"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(result.stdout.strip().splitlines()[-1])
    assert plan["dates"] == ["2026-12-17", "2026-12-18"]
    assert plan["child_arguments"] == ["-P", "-B", "-m", "weather.calibration.r28b_input_trim",
                                       "--date", "2026-12-17", "--date", "2026-12-18",
                                       "--source-root", str(root / "data" / "exports" / "mg2-inputs"),
                                       "--out", str(root / "data" / "exports" / "r28b-inputs")]
    assert not root.exists()
    bad = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                          str(OPS / "r28b_input_trim.ps1"), "-ProductionRepoRoot", str(root),
                          "-Date", "2026-12-17;x", "-PlanOnly"],
                         cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False)
    assert bad.returncode != 0 and not root.exists()
