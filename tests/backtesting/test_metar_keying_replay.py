"""Read-only v3 (reportTime) vs v4 (obsTime) METAR keying replay (M0)."""

import json
from collections import Counter
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from weather.backtesting import metar_keying_replay as replay
from weather.collection.snapshot_store import SnapshotStore
from weather.market.market_config import config_for_date
from weather.model.source_adapters import fetch_source
from weather.model.toronto_model import TorontoHighTempModel


def _epoch(iso_utc):
    return int(datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).timestamp())


def awc_row(obs_utc, report_utc, temp_c):
    return {
        "icaoId": "KMIA",
        "obsTime": _epoch(obs_utc),
        "reportTime": report_utc.replace("Z", ".000Z"),
        "metarType": "METAR",
        "temp": temp_c,
        "dewp": 20.0,
        "rawOb": f"METAR KMIA {obs_utc} {temp_c}",
    }


# KMIA 2026-08-29 shape: D-1's warm 23:53 EDT report carries reportTime 04:00Z of D.
CARRIED = awc_row("2026-08-29T03:53:00Z", "2026-08-29T04:00:00Z", 30.0)
D_EARLY = awc_row("2026-08-29T04:53:00Z", "2026-08-29T05:00:00Z", 27.0)
D_AFTERNOON = awc_row("2026-08-29T18:53:00Z", "2026-08-29T19:00:00Z", 29.4)
D_LAST = awc_row("2026-08-30T03:53:00Z", "2026-08-30T04:00:00Z", 28.3)
TZ = ZoneInfo("America/New_York")


def capture(root, market, target, snapshots):
    """Write observation sidecars with the production fetch + snapshot writer."""
    slug = config_for_date(target, market).event_slug
    store = SnapshotStore(root=root / slug, event_slug=slug)
    for snapshot_id, captured_local, payload in snapshots:
        model = TorontoHighTempModel(target_date=target.isoformat(), market_id=market)
        model.get_json = lambda _url, _params, payload=payload: payload
        _, item = fetch_source(
            "metar",
            model.source_fetcher_with_contract("metar", model.fetch_metar),
            fetched_at=captured_local.isoformat(),
        )
        store.write_observation_payloads({"metar": item}, snapshot_id, captured_local, "model-v")
    return root / slug


@pytest.fixture
def snapshots_root(tmp_path):
    root = tmp_path / "snapshots"
    capture(root, "miami", date(2026, 8, 29), [
        ("s-0010", datetime(2026, 8, 29, 0, 10, tzinfo=TZ), [CARRIED]),
        ("s-0100", datetime(2026, 8, 29, 1, 0, tzinfo=TZ), [D_EARLY, CARRIED]),
        ("s-1500", datetime(2026, 8, 29, 15, 0, tzinfo=TZ), [D_AFTERNOON, D_EARLY, CARRIED]),
        ("s-1505", datetime(2026, 8, 29, 15, 5, tzinfo=TZ), [D_AFTERNOON, D_EARLY, CARRIED]),
        ("s-2358", datetime(2026, 8, 29, 23, 58, tzinfo=TZ), [D_LAST, D_AFTERNOON, D_EARLY]),
    ])
    return root


def run_cli(argv, capsys):
    code = replay.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_replay_reports_changed_rows_floor_and_served_inputs(snapshots_root, tmp_path, capsys):
    out = tmp_path / "out" / "metar.jsonl"
    before = sorted(p.relative_to(snapshots_root) for p in snapshots_root.rglob("*"))

    code, stdout, _ = run_cli([
        "--date", "2026-08-29", "--market", "miami",
        "--snapshots-root", str(snapshots_root), "--out", str(out),
    ], capsys)

    assert code == 0
    assert sorted(p.relative_to(snapshots_root) for p in snapshots_root.rglob("*")) == before
    rows = {row["snapshot_id"]: row for row in read_rows(out)}
    assert set(rows) == {"s-0010", "s-0100", "s-1500", "s-1505", "s-2358"}
    assert all(row["status"] == "ok" for row in rows.values())
    assert all(row["recorded_parser_version"] == "metar-parser-v4" for row in rows.values())

    early = rows["s-0010"]
    assert early["near_local_midnight"] is True
    assert early["old"]["current_temp"] == pytest.approx(86.0)
    assert early["new"]["current_temp"] is None
    assert early["old"]["metar_floor_bucket"] == 86
    assert early["new"]["metar_floor"] is None
    assert [r["obs_time"] for r in early["rows_only_old"]] == ["2026-08-29T03:53:00Z"]
    assert early["rows_only_new"] == []

    afternoon = rows["s-1500"]
    assert afternoon["changed"] is True
    assert afternoon["floor_bucket_changed"] is True
    assert afternoon["old"]["same_day_max"] == pytest.approx(86.0)
    assert afternoon["new"]["same_day_max"] == pytest.approx(29.4 * 9 / 5 + 32)
    assert afternoon["new"]["latest_time"] == "14:53"
    assert afternoon["old"]["latest_time"] == "15:00"

    last = rows["s-2358"]
    assert [r["obs_time"] for r in last["rows_only_new"]] == ["2026-08-30T03:53:00Z"]
    assert last["old"]["current_temp"] == pytest.approx(29.4 * 9 / 5 + 32)
    assert last["new"]["current_temp"] == pytest.approx(28.3 * 9 / 5 + 32)

    summary = json.loads(stdout)
    assert summary["snapshots"] == 5
    assert summary["changed_snapshots"] == 5
    assert summary["status"] == {"ok": 5}
    assert summary["station_days_old_floor_higher"] == ["miami:2026-08-29"]


def test_routine_report_inside_the_day_moves_only_latest_time(tmp_path, capsys):
    root = tmp_path / "snapshots"
    capture(root, "miami", date(2026, 8, 20), [
        ("s1", datetime(2026, 8, 20, 15, 0, tzinfo=TZ), [
            awc_row("2026-08-20T18:53:00Z", "2026-08-20T19:00:00Z", 30.0),
        ]),
    ])
    out = tmp_path / "o.jsonl"
    code, _, _ = run_cli(["--date", "2026-08-20", "--market", "miami",
                          "--snapshots-root", str(root), "--out", str(out)], capsys)
    row = read_rows(out)[0]
    assert code == 0
    assert row["changed_fields"] == ["latest_time"]  # 15:00 nominal hour -> 14:53 observation
    assert row["rows_only_old"] == row["rows_only_new"] == []
    assert row["floor_bucket_changed"] is False


def test_refuses_dates_from_2026_09_30(snapshots_root, tmp_path, capsys):
    out = tmp_path / "o.jsonl"
    code, _, err = run_cli(["--date", "2026-08-29", "--date", "2026-09-30", "--market", "miami",
                            "--snapshots-root", str(snapshots_root), "--out", str(out)], capsys)
    assert code == 2
    assert "2026-09-30" in err
    assert not out.exists()


def test_refuses_existing_out_and_out_under_data(snapshots_root, tmp_path, capsys, monkeypatch):
    existing = tmp_path / "exists.jsonl"
    existing.write_text("keep\n", encoding="utf-8")
    code, _, err = run_cli(["--date", "2026-08-29", "--market", "miami",
                            "--snapshots-root", str(snapshots_root), "--out", str(existing)], capsys)
    assert code == 2 and "already exists" in err
    assert existing.read_text(encoding="utf-8") == "keep\n"

    fake_data = tmp_path / "data"
    monkeypatch.setattr(replay, "data_path", lambda: fake_data)
    inside = fake_data / "backtest" / "metar.jsonl"
    code, _, err = run_cli(["--date", "2026-08-29", "--market", "miami",
                            "--snapshots-root", str(snapshots_root), "--out", str(inside)], capsys)
    assert code == 2 and "runtime data tree" in err
    assert not fake_data.exists()


def test_capture_after_cutoff_is_skipped_without_reading_its_blob(tmp_path, capsys, monkeypatch):
    root = tmp_path / "snapshots"
    folder = capture(root, "miami", date(2026, 9, 29), [
        ("late", datetime(2026, 9, 30, 0, 5, tzinfo=TZ), [CARRIED]),
    ])
    opened = []
    real = replay.load_blob
    monkeypatch.setattr(replay, "load_blob", lambda f, r: opened.append(r) or real(f, r))
    out = tmp_path / "o.jsonl"
    code, stdout, _ = run_cli(["--date", "2026-09-29", "--market", "miami",
                               "--snapshots-root", str(root), "--out", str(out)], capsys)
    assert code == 0
    assert opened == []
    assert json.loads(stdout)["status"] == {"skipped_after_cutoff": 1}
    assert out.read_text(encoding="utf-8") == ""
    assert folder.is_dir()


def test_tampered_or_missing_blob_is_reported_not_parsed(snapshots_root, tmp_path, capsys):
    blobs = sorted((snapshots_root).rglob("observation_payloads/sha256/*/*.json"))
    blobs[0].write_bytes(b"[]\n")
    out = tmp_path / "o.jsonl"
    code, _, _ = run_cli(["--date", "2026-08-29", "--market", "miami",
                          "--snapshots-root", str(snapshots_root), "--out", str(out)], capsys)
    statuses = Counter(row["status"] for row in read_rows(out))
    assert code == 0
    assert statuses["hash_mismatch"] >= 1
    assert all("old" not in row for row in read_rows(out) if row["status"] != "ok")


def test_requires_date_and_known_market():
    with pytest.raises(replay.ReplayRefused):
        replay.check_dates([])
    with pytest.raises(replay.ReplayRefused):
        replay.check_markets(["atlantis"])
    assert replay.check_dates(["2026-09-29", "2026-09-29"]) == [date(2026, 9, 29)]
