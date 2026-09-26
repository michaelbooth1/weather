"""Deterministic checks of the diagnostic, not a test requiring a parser bug."""
import csv
import hashlib
import json
from pathlib import Path

import pytest

from tools.research.nbm_target_trace.run import fetch, recover_quantiles, token_grid

EVIDENCE = Path(__file__).resolve().parents[2] / "tools/research/nbm_target_trace/evidence"


def test_real_noaa_leading_minimum_and_next_maximum():
    block = (EVIDENCE / "blocks/20260917T13Z-KLGA.txt").read_text()
    issued, _, cells = token_grid(block)
    assert issued.isoformat() == "2026-09-17T13:00:00+00:00"
    first, second = cells[:2]
    assert (first["group"], first["token"], first["period_kind"], first["TXNP5"]) == (0, 0, "minimum", 72)
    assert first["period_date"] == "2026-09-18"
    assert second["valid_time_utc"] == "2026-09-19T00:00:00+00:00"
    assert (second["period_kind"], second["period_date"], second["TXNP5"]) == ("maximum", "2026-09-18", 81)


def test_convention_uses_time_not_magnitude():
    block = (EVIDENCE / "blocks/20260917T13Z-KLGA.txt").read_text()
    changed = block.replace("TXNP5  72| 81  66", "TXNP5  95| 20  66")
    _, _, cells = token_grid(changed)
    assert cells[0]["period_kind"] == "minimum"
    assert cells[1]["period_kind"] == "maximum"
    with pytest.raises(ValueError, match="unsupported"):
        token_grid(block.replace("UTC    12", "UTC    11"))


def test_spreads_recover_tails_but_not_deleted_median():
    q, recovered, lower, upper = recover_quantiles({
        "nbm_prob_tmax_p75": 73, "nbm_prob_tmax_p90": 75,
        "nbm_prob_tmax_iqr": 4, "nbm_prob_tmax_p10_p90_spread": 8})
    assert q == {10: 67, 25: 69, 50: None, 75: 73, 90: 75}
    assert recovered == [10, 25]
    assert (lower, upper) == (69, 73)


def test_absent_tails_remain_unknown():
    q, recovered, lower, upper = recover_quantiles({
        "nbm_prob_tmax_iqr": 4, "nbm_prob_tmax_p10_p90_spread": 8})
    assert not recovered
    assert all(value is None for value in q.values())
    assert lower is upper is None


def test_saved_t1_census_and_wrong_period_date_are_internally_consistent():
    with (EVIDENCE / "picks.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 396
    assert len({r["station"] for r in rows}) == 11
    wrong = [r for r in rows if r["classification"] == "wrong"]
    assert len(wrong) == 66
    assert {r["hour"] for r in wrong} == {"13", "19"}
    assert all(r["period_kind"] == "minimum" and r["target_date"] != r["period_date"] for r in wrong)


def test_cache_reuse_never_calls_network_and_rejects_drift(tmp_path, monkeypatch):
    path = tmp_path / "noaa.txt"
    path.write_bytes(b"retained public bulletin")
    (tmp_path / "noaa.txt.json").write_text(json.dumps({
        "url": "https://example.test/noaa", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))
    def forbidden(*args, **kwargs):
        raise AssertionError("cached national file must not refetch")
    monkeypatch.setattr("requests.get", forbidden)
    assert fetch(tmp_path, "noaa.txt", "https://example.test/noaa")[0] == path
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="cache identity/hash"):
        fetch(tmp_path, "noaa.txt", "https://example.test/noaa")


def test_retained_evidence_matches_manifest():
    manifest = json.loads((EVIDENCE / "file-manifest.json").read_text())
    for name, digest in manifest.items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest, name


def test_t1_v1_binding_reproduces_all_396_retained_parser_rows(monkeypatch):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from tools.research.nbm_target_trace import run as trace

    def forbidden(*args, **kwargs):
        pytest.fail("parser-only reproduction must not observe, fetch or run a study stage")

    monkeypatch.setattr(trace, "observations", forbidden)
    monkeypatch.setattr(trace, "fetch", forbidden)
    monkeypatch.setattr(trace, "t1", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    columns = ("chosen_group", "chosen_token", "valid_time_utc", "period_kind",
               "period_date", "p50", "reason", "classification")
    with (EVIDENCE / "picks.csv").open(newline="") as handle:
        # Compare only parser-derived columns, never the observed-temperature fields.
        expected = {(row["cycle"], row["station"], row["target_offset"]):
                    {name: row[name] for name in columns} for row in csv.DictReader(handle)}
    specs = {spec["station"]: spec for spec in trace.stations().values()}
    blocks = sorted((EVIDENCE / "blocks").glob("*.txt"))
    assert len(blocks) == 132 and len(expected) == 396
    reproduced = {}
    for path in blocks:
        block = path.read_text()
        cycle, station = path.stem.split("-")
        issued, _, _ = trace.token_grid(block)
        local_day = issued.astimezone(ZoneInfo(specs[station]["timezone"])).date()
        for offset in (-1, 0, 1):
            key = (cycle, station, str(offset))
            row = trace.t1_parser_pick(block, station, local_day + timedelta(days=offset))
            reproduced[key] = {name: "" if row[name] is None else str(row[name]) for name in columns}
    assert reproduced.keys() == expected.keys()
    differences = [{"row": key, "column": name, "expected": expected[key][name],
                    "actual": row[name]} for key, row in reproduced.items()
                   for name in columns if row[name] != expected[key][name]]
    assert differences == [], differences


def test_t1_13z_klga_keeps_the_recorded_v1_wrong_period(monkeypatch):
    from datetime import date
    from tools.research.nbm_target_trace import run as trace
    from weather.sources import nbm_probabilistic_tmax as source

    def forbidden(*args, **kwargs):
        pytest.fail("the historical T1 binding must not reach the version-2 default")

    monkeypatch.setattr(source, "parse_nbp_station_tmax", forbidden)
    monkeypatch.setattr(trace, "parse_nbp_station_tmax", forbidden, raising=False)
    monkeypatch.setattr(trace, "observations", forbidden)
    monkeypatch.setattr(trace, "fetch", forbidden)
    monkeypatch.setattr("requests.sessions.Session.request", forbidden)
    block = (EVIDENCE / "blocks/20260917T13Z-KLGA.txt").read_text()
    row = trace.t1_parser_pick(block, "KLGA", date(2026, 9, 17))
    assert row == {
        "chosen_group": 0, "chosen_token": 0,
        "valid_time_utc": "2026-09-18T12:00:00+00:00",
        "period_kind": "minimum", "period_date": "2026-09-18", "p50": 72.,
        "reason": None, "classification": "wrong",
    }
