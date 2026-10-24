"""Mission 111h extractor on fixtures written by the production writers.

The national bulletins are the real NOAA NBP station blocks retained by 82a.
Parser v2 runs from a real detached worktree of 2e17ce0eb, exactly as on
production; CI checks out full history, so the commit object is present.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.backtesting.settlement_ledger import write_folder_label
from weather.collection.snapshot_store import LONG_COLUMNS, SnapshotStore
from weather.market.market_config import event_slug_for_date
from weather.model.feature_store import FEATURE_AUDIT_COLUMNS
from weather.paths import repo_path
from weather.reporting.research import guidance_extract
from weather.reporting.research.guidance_extract_parser import PINNED_PARSER_COMMIT, verify_pinned_worktree
from weather.sources import nbm_probabilistic_tmax as nbm_v1

BLOCKS = repo_path("tools", "research", "nbm_target_trace", "evidence", "blocks")
BANDS = [("lte", 83, 83)] + [("eq", lo, lo + 1) for lo in range(84, 96, 2)] + [("gte", 96, 96)]


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd or repo_path(), check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def parser_worktree(tmp_path_factory):
    try:
        _git("cat-file", "-e", f"{PINNED_PARSER_COMMIT}^{{commit}}")
    except subprocess.CalledProcessError:
        pytest.skip(f"parser commit {PINNED_PARSER_COMMIT} is not in this clone (fetch full history)")
    root = tmp_path_factory.mktemp("parser") / "wt"
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}
    subprocess.run(["git", "worktree", "add", "--detach", str(root), PINNED_PARSER_COMMIT],
                   cwd=repo_path(), check=True, capture_output=True, env=env)
    yield root
    subprocess.run(["git", "worktree", "remove", "--force", str(root)], cwd=repo_path(), capture_output=True)


def bulletin(cycle):
    """A national bulletin: the 11 retained US station blocks of one cycle."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(BLOCKS.glob(f"{cycle}-*.txt")))


class Fixture:
    """Writes one data root the way production does."""

    def __init__(self, root):
        self.root = root
        self.cas = root / "forecast_payload_cas"

    def store(self, market, target):
        slug = event_slug_for_date(target, market)
        folder = self.root / "snapshots" / slug
        folder.mkdir(parents=True, exist_ok=True)
        return SnapshotStore(root=folder, event_slug=slug, retain_raw_forecast_payloads=True,
                             shared_forecast_payload_cas_root=self.cas)

    def snapshot(self, market, target, captured, nbm_cycle, fetched, station="KATL", *,
                 served=None, features=None, sources=None):
        """Write one snapshot: bands, features, replay inputs and the v1 NBM manifest row."""
        store = self.store(market, target)
        sid = captured.strftime("%Y%m%dT%H%M%S%f%z")
        captured_utc = captured.astimezone(timezone.utc).isoformat()
        served = served or [.02, .03, .05, .1, .2, .3, .2, .1]
        rows = [{"snapshot_id": sid, "captured_at_utc": captured_utc, "captured_at_local": captured.isoformat(),
                 "event_slug": store.event_slug, "model_version": "fixture", "range_label": f"{kind}{lo}",
                 "bin_kind": kind, "bin_value_c": lo, "bin_value_hi_c": hi, "model_probability": p,
                 "market_yes": .125, "best_bid": .1, "best_ask": .15}
                for (kind, lo, hi), p in zip(BANDS, served)]
        store.append_csv(store.root / "snapshots_long.csv", LONG_COLUMNS, rows)
        feature = {"snapshot_id": sid, "captured_at_utc": captured_utc, "event_slug": store.event_slug,
                   "target_date": target.isoformat(), **(features or {})}
        store.append_csv(store.root / "features_long.csv", FEATURE_AUDIT_COLUMNS, [feature])
        store.append_jsonl(store.root / "replay_inputs.jsonl", {"snapshot_id": sid, "sources": sources or {}})
        if nbm_cycle:
            issue = datetime.strptime(nbm_cycle, "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
            # These rows model captures made by production parser v1 (2026-09); the
            # in-tree default is v2 once the repair lands, so bind v1 explicitly.
            data = nbm_v1.parse_nbp_station_tmax_v1(bulletin(nbm_cycle), station, target,
                                                    nbm_v1.nbp_text_url(issue), fetched.isoformat())
            store.write_forecast_payloads({"nbm_probabilistic_tmax": {"ok": True, "fetched_at": fetched.isoformat(),
                                                                      "data": data}},
                                          sid, captured, "fixture",
                                          config_identity={"market_id": market, "target_date": target.isoformat()})
        return sid

    def settle(self, market, target, bucket, countable=True):
        folder = self.store(market, target).root
        write_folder_label(folder, {"event_slug": folder.name, "market_id": market,
                                    "target_date": target.isoformat(), "settlement_high": bucket,
                                    "settlement_bucket": bucket, "settlement_unit": "F",
                                    "promotion_countable": countable, "quality_grade": "fixture"})


def utc(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def extract(tmp_path_factory, parser_worktree):
    root = tmp_path_factory.mktemp("data")
    fx = Fixture(root)
    d17, d18 = datetime(2026, 9, 17).date(), datetime(2026, 9, 18).date()
    fetched = {"20260917T01Z": utc(17, 1, 40), "20260917T07Z": utc(17, 7, 40),
               "20260917T13Z": utc(17, 14, 10), "20260917T19Z": utc(17, 20, 10),
               "20260918T01Z": utc(18, 1, 40), "20260918T07Z": utc(18, 7, 40),
               "20260918T13Z": utc(18, 14, 10)}
    features = {"guidance_physical_floor": 80, "high_so_far": 81, "nbm_prob_tmax_p50": 72,
                "guidance_impossible_features": "nbm_prob_tmax_p50"}
    sources = {"nws_grid": {"ok": True, "data": {"day_max_native": 92, "provider_issue_time": utc(17, 9).isoformat(),
                                                 "provider_update_time": utc(17, 9).isoformat(),
                                                 "fetched_at": utc(17, 9, 5).isoformat()}},
               "open_meteo_multimodel": {"ok": True, "data": {"day_model_highs": {"ncep_hrrr_conus": 93},
                                                              "fetched_at": utc(17, 9, 5).isoformat()}}}
    late_nws = {"nws_grid": {"ok": True, "data": {"day_max_native": 99, "provider_issue_time": utc(17, 22).isoformat(),
                                                  "fetched_at": utc(17, 22).isoformat()}}}
    ids = {
        "morning": fx.snapshot("atlanta", d17, utc(17, 10), "20260917T07Z", fetched["20260917T07Z"], sources=sources),
        "after_13z": fx.snapshot("atlanta", d17, utc(17, 15), "20260917T13Z", fetched["20260917T13Z"],
                                 features=features, sources=late_nws),
        # 19Z exists in the store only from 20:10Z; this 19:00Z snapshot must not see it.
        "before_19z_fetch": fx.snapshot("atlanta", d17, utc(17, 19), "20260917T13Z", fetched["20260917T13Z"]),
        "after_19z_fetch": fx.snapshot("atlanta", d17, utc(17, 21), "20260917T19Z", fetched["20260917T19Z"]),
        "d18_early": fx.snapshot("atlanta", d18, utc(18, 6), "20260918T01Z", fetched["20260918T01Z"]),
        "d18_07z_missing": fx.snapshot("atlanta", d18, utc(18, 9), "20260918T07Z", fetched["20260918T07Z"]),
        "d18_after_13z": fx.snapshot("atlanta", d18, utc(18, 15), "20260918T13Z", fetched["20260918T13Z"]),
    }
    fx.snapshot("miami", d17, utc(17, 15), "20260917T13Z", fetched["20260917T13Z"], station="KMIA")
    fx.snapshot("toronto", d17, utc(17, 15), None, None)
    fx.settle("atlanta", d17, 94)
    fx.settle("atlanta", d18, 92)
    fx.settle("miami", d17, 90, countable=False)
    # The 18th's 07Z bulletin was referenced by a manifest but its bytes are gone.
    blob_07z = [p for p in fx.cas.rglob("*.blob") if "9/18/2026  0700 UTC" in p.read_text(encoding="utf-8")]
    assert len(blob_07z) == 1
    blob_07z[0].unlink()
    out = root.parent / "out"
    code = guidance_extract.main(["--data-root", str(root), "--out", str(out), "--from", "2026-09-17",
                                  "--to", "2026-09-18", "--parser-worktree", str(parser_worktree)])
    with gzip.open(out / "guidance_rows.jsonl.gz", "rt", encoding="utf-8") as stream:
        rows = {r["snapshot_id"]: r for r in map(json.loads, stream)}
    with gzip.open(out / "market_days.jsonl.gz", "rt", encoding="utf-8") as stream:
        days = list(map(json.loads, stream))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return {"code": code, "rows": rows, "days": days, "manifest": manifest, "ids": ids, "out": out}


def row(extract, name):
    return extract["rows"][extract["ids"][name]]


def test_run_completes_and_admits_only_countable_us_market_days(extract):
    assert extract["code"] == 0
    assert extract["manifest"]["status"] == "COMPLETE"
    assert {r["market"] for r in extract["rows"].values()} == {"atlanta"}
    assert len(extract["rows"]) == 7
    reasons = {(d["market"], d["target_date"]): d.get("reason") for d in extract["days"]}
    assert reasons[("miami", "2026-09-17")] == "not_promotion_countable"
    assert ("toronto", "2026-09-17") not in reasons


def test_morning_row_uses_07z_maximum(extract):
    r = row(extract, "morning")
    assert r["v2_status"] == "available" and r["v2_cycle_key"] == "nbm-nbp:20260917T07Z"
    assert r["v2_p50"] == 91 and r["v2_valid_time_utc"] == "2026-09-18T00:00:00+00:00"
    assert r["v1_period"] == "maximum"
    assert r["local_hour"] == 6 and r["captured_at_local"].endswith("-04:00")


def test_13z_bulletin_is_rejected_and_older_07z_maximum_is_used(extract):
    r = row(extract, "after_13z")
    assert r["v1_cycle_key"] == "nbm-nbp:20260917T13Z" and r["v1_period"] == "minimum"
    assert r["v2_newest_cycle_key"] == "nbm-nbp:20260917T13Z"
    assert r["v2_newest_reason"] == "target_max_not_in_cycle"
    assert r["v2_cycle_key"] == "nbm-nbp:20260917T07Z" and r["v2_p50"] == 91
    assert r["v2_age_hours"] == 8.0
    assert r["features"]["nbm_prob_tmax_p50"] == 72  # the captured wrong-period value is retained, not used


def test_bulletin_fetched_after_capture_is_excluded(extract):
    before = row(extract, "before_19z_fetch")
    assert before["v2_skipped"] == {"after_capture": 1}
    assert before["v2_newest_cycle_key"] == "nbm-nbp:20260917T13Z"
    after = row(extract, "after_19z_fetch")
    assert "after_capture" not in after["v2_skipped"]
    assert after["v2_newest_cycle_key"] == "nbm-nbp:20260917T19Z"
    assert after["v2_cycle_key"] == "nbm-nbp:20260917T07Z"


def test_missing_07z_bytes_fall_back_to_01z(extract):
    r = row(extract, "d18_after_13z")
    assert r["v2_skipped"] == {"bytes_missing": 1}
    assert r["v2_cycle_key"] == "nbm-nbp:20260918T01Z"
    assert row(extract, "d18_07z_missing")["v2_cycle_key"] == "nbm-nbp:20260918T01Z"
    assert extract["manifest"]["bulletins"]["status"]["bytes_missing"] == 1


def test_point_guidance_respects_capture_time(extract):
    r = row(extract, "morning")
    assert r["hrrr_high"] == 93 and r["hrrr_issued_at"] is None
    assert r["nws_grid_high_raw"] == 92 and r["nws_grid_issued_at"] == "2026-09-17T09:00:00+00:00"
    late = row(extract, "after_13z")
    assert late["nws_grid_high_raw"] is None and late["nws_grid_status"] == "after_capture"


def test_outcome_market_and_served_vectors(extract):
    r = row(extract, "morning")
    assert r["bands"][r["winner"]] == {"kind": "eq", "low": 94, "high": 95, "label": "eq94"}
    assert r["p_served"][r["winner"]] == .2 and r["market_mid"][0] == pytest.approx(.125)
    assert r["stratum"] == "from_20260823"


def test_manifest_binds_parser_and_output_hashes(extract):
    manifest = extract["manifest"]
    assert manifest["parser"]["head"].startswith(PINNED_PARSER_COMMIT)
    assert manifest["bytes_read_by_source"]["nbp_bulletin_cas"] > 0
    for name, entry in manifest["outputs"].items():
        assert hashlib.sha256((extract["out"] / name).read_bytes()).hexdigest() == entry["sha256"]
    sums = (extract["out"] / "SHA256SUMS").read_text(encoding="utf-8").split()
    assert "manifest.json" in sums


def test_budget_exhaustion_is_reported_not_silent(tmp_path, parser_worktree):
    fx = Fixture(tmp_path / "data")
    fx.snapshot("atlanta", datetime(2026, 9, 17).date(), utc(17, 10), "20260917T07Z", utc(17, 7, 40))
    fx.settle("atlanta", datetime(2026, 9, 17).date(), 94)
    out = tmp_path / "out"
    code = guidance_extract.main(["--data-root", str(tmp_path / "data"), "--out", str(out), "--from", "2026-09-17",
                                  "--to", "2026-09-17", "--parser-worktree", str(parser_worktree),
                                  "--max-input-bytes", "1000"])
    assert code == 3
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["status"] == "INCOMPLETE_BUDGET_EXCEEDED"


def test_parser_refuses_an_unpinned_tree(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        verify_pinned_worktree(tmp_path)


def test_selection_ignores_bulletins_older_than_lookback():
    captured = utc(18, 15)
    bulletins = {"h": {"cycle_key": "nbm-nbp:20260917T07Z", "available_at": utc(17, 7, 40),
                       "available_basis": "fetched_at", "status": "parsed"}}
    parsed = {("h", "KATL", "2026-09-18"): {"available": True, "issued_at": utc(17, 7).isoformat()}}
    result = guidance_extract.select_v2(bulletins, parsed, "KATL", "2026-09-18", captured, timedelta(hours=24))
    assert result["v2_status"] == "unavailable" and result["v2_candidates"] == 0
