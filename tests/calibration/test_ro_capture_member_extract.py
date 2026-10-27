"""R-O Clarification 1: capture-side node-max extractor and P's C1 comparison (research-only branch).

Guards: the extractor refuses, before opening any file, event directories that do not parse or whose target date is
outside 2026-07-30..2026-09-29; it reads only forecast_payloads blobs that carry temperature_2m_member keys (a decoy
blob is skipped, gzip blobs are read); a member's node max is the max over exactly history's 06Z fh6-24 nodes whose
local date (via utc_offset_seconds) is the target date, and is empty if any node is missing; the full-day max covers
every label on the local date; the manifest's output sha equals the CSV's. P under C1 links a snapshot to the blob
that reproduces its captured day p10/p90/control and compares history's node statistics with the blob's.
"""
import csv
import gzip
import hashlib
import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from tools.research import ro_capture_member_extract as ex

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        prm = None
    else:
        raise

UTC = timezone.utc


def _payload(day, offset, peak_local_hour, members=30, missing=None, control_shift=0.0):
    """48 hourly naive local labels from local midnight of ``day``; value = 90 - |h - peak| + k/10 for member k."""
    start = datetime.fromisoformat(day)
    labels, hourly = [], {"temperature_2m": []}
    for k in range(1, members + 1):
        hourly[f"temperature_2m_member{k:02d}"] = []
    for i in range(48):
        t = start + timedelta(hours=i)
        labels.append(t.strftime("%Y-%m-%dT%H:%M"))
        base = 90.0 - abs(i - peak_local_hour)
        hourly["temperature_2m"].append(base + control_shift)
        for k in range(1, members + 1):
            v = base + k / 10.0
            hourly[f"temperature_2m_member{k:02d}"].append(None if missing == (k, i) else v)
    hourly["time"] = labels
    return {"generationtime_ms": 12.5, "utc_offset_seconds": offset, "hourly_units": {"temperature_2m": "°F"},
            "hourly": hourly}


def _event(root, slug, blobs):
    pdir = root / slug / "forecast_payloads"
    pdir.mkdir(parents=True)
    for name, data in blobs.items():
        (pdir / name).write_bytes(data)
    return root / slug


def _rows(out):
    with open(out / "ro_capture_members.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_refuses_out_of_window_before_opening(tmp_path):
    bad = tmp_path / "highest-temperature-in-nyc-on-september-30-2026"
    (bad / "forecast_payloads").mkdir(parents=True)
    (bad / "forecast_payloads" / "x").write_bytes(b"\xff not json, never opened")
    good = _event(tmp_path, "highest-temperature-in-nyc-on-august-10-2026", {})
    with pytest.raises(SystemExit, match="refusing"):
        ex.run([good, bad], tmp_path / "out")
    assert not (tmp_path / "out").exists()
    with pytest.raises(SystemExit, match="refusing"):
        ex.run([tmp_path / "not-an-event"], tmp_path / "out2")


def test_node_max_day_max_decoy_gzip_and_offset(tmp_path):
    ny = json.dumps(_payload("2026-08-10", -14400, 13, missing=(30, 14))).encode()
    la = gzip.compress(json.dumps(_payload("2026-08-10", -25200, 22)).encode())
    decoy = json.dumps({"hourly": {"time": ["2026-08-10T00:00"], "temperature_2m": [99.0]}}).encode()
    d1 = _event(tmp_path, "highest-temperature-in-nyc-on-august-10-2026",
                {hashlib.sha256(ny).hexdigest(): ny, "decoy": decoy})
    d2 = _event(tmp_path, "highest-temperature-in-los-angeles-on-august-10-2026", {"la.json.gz": la})
    man = ex.run([d1, d2], tmp_path / "out")
    assert man["counts"]["blobs_ensemble"] == 2 and man["counts"]["blobs_skipped_not_ensemble"] == 1
    assert man["output"]["sha256"] == hashlib.sha256((tmp_path / "out" / "ro_capture_members.csv").read_bytes()).hexdigest()
    rows = {(r["event"][23:26], r["member"]): r for r in _rows(tmp_path / "out")}
    # New York EDT (-4 h): nodes 12Z..03Z = 08,11,14,17,20,23 local (06Z = 02:00 next day is not the local date).
    # Peak at 13:00 local is not a node: node max is 89 + k/10 (at 14:00), the day max is 90 + k/10.
    r = rows[("nyc", "05")]
    assert r["nodes_wanted"] == "6" and float(r["node_max"]) == pytest.approx(89.5)
    assert float(r["day_max"]) == pytest.approx(90.5) and r["n_day_hours"] == "24"
    assert rows[("nyc", "30")]["node_max"] == "" and float(rows[("nyc", "30")]["day_max"]) == pytest.approx(93.0)
    assert float(rows[("nyc", "control")]["node_max"]) == pytest.approx(89.0)
    # Los Angeles PDT (-7 h): all seven nodes fall on the local date; 06Z D+1 = 23:00 local is a node.
    r = rows[("los", "05")]
    assert r["nodes_wanted"] == "7" and float(r["node_max"]) == pytest.approx(89.5)
    assert float(r["day_max"]) == pytest.approx(90.5)


@pytest.mark.skipif(prm is None, reason="research module refuses this host")
def test_parity_c1_links_by_day_fingerprint(tmp_path):
    from weather.model.model_sources import percentile

    pay = _payload("2026-08-10", -14400, 13)
    blob = json.dumps(pay).encode()
    other = json.dumps(_payload("2026-08-10", -14400, 13, control_shift=5.0)).encode()  # different fingerprint
    ev = _event(tmp_path / "host", "highest-temperature-in-nyc-on-august-10-2026", {"a": blob, "b": other})
    ex.run([ev], tmp_path / "cap")
    # history corpus: every member's node value 300 K + k/10 (control k = 0)
    cycle = datetime(2026, 8, 10, 6, tzinfo=UTC)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    with open(corpus / "gefs_member_rows.jsonl", "w", encoding="utf-8") as fh:
        for k in range(0, 31):
            for step in (6, 9, 12, 15, 18, 21, 24):
                fh.write(json.dumps({"kind": "message", "status": "ok", "date": "2026-08-10",
                                     "member": "gec00" if k == 0 else f"gep{k:02d}",
                                     "valid_utc": (cycle + timedelta(hours=step)).isoformat(),
                                     "available_utc": "2026-08-10T10:00:00+00:00",
                                     "points": {"nyc": {"bilinear_k": 300.0 + k / 10.0}}}) + "\n")
    day_highs = [90.0 + k / 10.0 for k in range(1, 31)]
    captured = {"day_member_high_p10": percentile(day_highs, 0.10), "day_member_high_p90": percentile(day_highs, 0.90),
                "day_max_native": 90.0}
    inputs = tmp_path / "inputs" / "highest-temperature-in-nyc-on-august-10-2026"
    inputs.mkdir(parents=True)
    lines = [json.dumps({"captured_at_local": f"2026-08-10T{h:02d}:05:00-04:00",
                         "captured_at_utc": f"2026-08-10T{h + 4:02d}:05:00+00:00",
                         "target_date": "2026-08-10", "model_identity": {"market_id": "nyc"},
                         "sources": {"global_ensemble": {"data": captured}}}) for h in (8, 10, 11)]
    lines += [json.dumps({"captured_at_local": "2026-08-10T09:05:00-04:00", "captured_at_utc": "2026-08-10T13:05:00+00:00",
                         "target_date": "2026-08-10", "model_identity": {"market_id": "nyc"},
                         "sources": {"global_ensemble": {"data": dict(captured, day_max_native=1.0)}}})]
    (inputs / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = prm.rung_o_parity_c1(inputs_root=tmp_path / "inputs", gefs_corpus=corpus,
                               capture_csv=tmp_path / "cap" / "ro_capture_members.csv",
                               capture_manifest=tmp_path / "cap" / "ro_capture_manifest.json",
                               out_dir=tmp_path / "out")
    assert res["counts"]["snapshots_compared"] == 3 and res["counts"]["snapshots_unlinked"] == 1
    node = [89.0 + k / 10.0 for k in range(1, 31)]
    assert res["parity"]["control"]["n"] == 3
    hist_p90 = percentile([prm.ro_kelvin_to_f(300.0 + k / 10.0) for k in range(1, 31)], 0.90)
    assert res["parity"]["p90"]["mean_diff"] == pytest.approx(hist_p90 - percentile(node, 0.90))
    assert res["rule_sha256"] == prm.RO_RULE_C1_SHA256
