"""R-Q Clarification 1 helpers (P_B capture side at history's node definition); offline, synthetic."""

import csv

import pytest

pytest.importorskip("numpy")

from weather.calibration import spread_information_rung as sir
from weather.model.model_sources import percentile


def _members(n, node0=80.0, day0=82.0):
    out = {f"{k:02d}": (node0 + k * 0.1, day0 + k * 0.1) for k in range(1, n + 1)}
    out["control"] = (79.0, 81.0)
    return out


def test_blob_stats_fingerprint_and_node():
    members = _members(30)
    fp, node = sir.rq_c1_blob_stats(members)
    day = [v[1] for k, v in members.items() if k != "control"]
    nodes = [v[0] for k, v in members.items() if k != "control"]
    assert fp == (percentile(day, 0.10), percentile(day, 0.90), 81.0)
    assert node == (percentile(nodes, 0.10), percentile(nodes, 0.90))


def test_blob_stats_below_25_members_has_no_node():
    _, node = sir.rq_c1_blob_stats(_members(24))
    assert node is None


def test_load_capture_and_close(tmp_path):
    path = tmp_path / "c.csv"
    with open(path, "w", encoding="utf-8", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(["event", "blob", "member", "node_max", "day_max", "temperature_unit"])
        w.writerow(["ev", "b1", "01", "80.5", "82.0", "°F"])
        w.writerow(["ev", "b1", "control", "", "81.0", "°F"])
    blobs, units = sir.rq_c1_load_capture(path)
    assert blobs["ev"]["b1"]["01"] == (80.5, 82.0)
    assert blobs["ev"]["b1"]["control"] == (None, 81.0)
    assert units["b1"] == "°F"
    assert sir._rq_c1_close(1.0, 1.0 + 5e-7) and not sir._rq_c1_close(1.0, 1.00001)
    assert not sir._rq_c1_close(None, 1.0)


def test_c1_cli_is_registered():
    args = sir.build_parser().parse_args(["rq-parity-b-c1", "--replay-root", "r", "--gefs-corpus", "g",
                                          "--capture-csv", "c", "--capture-manifest", "m", "--out", "o"])
    assert args.command == "rq-parity-b-c1"
