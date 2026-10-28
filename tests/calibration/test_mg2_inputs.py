"""MG-2 daily input transfer (workstation side): the allow-list, pull, receiver and label-free builder.

Guards: MG-2 binding plan §9 input transfer (docs/research/mg2-composite-binding-2026-10-25/binding-plan.md):
receipts, label-free layouts, one-window concat.
"""
import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from weather.calibration import mg2_input_allowlist as allow

from tests.host_guard import import_or_skip_on_capture_host

mi = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")

ROOT = Path(__file__).resolve().parents[2]
D = date(2026, 11, 2)
BLOB = b"NBM NBP national bulletin fixture bytes\n"
BLOB_SHA = hashlib.sha256(BLOB).hexdigest()
BANDS = [("lte", 79, 79)] + [("eq", lo, lo + 1) for lo in range(80, 90, 2)] + [("gte", 90, 90)]
TZ = {"atlanta": "America/New_York", "austin": "America/Chicago", "chicago": "America/Chicago",
      "dallas": "America/Chicago", "denver": "America/Denver", "houston": "America/Chicago",
      "los-angeles": "America/Los_Angeles", "miami": "America/New_York", "nyc": "America/New_York",
      "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}
LOCAL_HOURS = (3, 14)
# Model-input-only fields that must never travel (the host carries them; the exporter drops them).
HOST_ONLY = {"wu_history": {"ok": True, "data": {"rows": [{"temp_native": 99.0}]}},
             "wu_current": {"ok": True, "data": {}}, "local_history": {"ok": True, "data": {}},
             "station_observations": {"ok": True, "data": {"rows": [], "station_observation_source": "wu_history"}}}


def _local(market, day, hour):
    return datetime(day.year, day.month, day.day, hour, 7, tzinfo=ZoneInfo(TZ[market]))


def _sid(local):
    return local.strftime("%Y%m%dT%H%M%S000000%z")


def _metar_rows(local):
    utc = local.astimezone(timezone.utc)
    return [{"raw": f"METAR KXXX {utc:%d%H}52Z 00000KT 10SM", "report_time": utc.strftime("%Y-%m-%dT%H:00:00.000Z"),
             "temp_native": 70.0 + local.hour / 2, "temp_c": 21.0, "time": local.strftime("%H:%M")}]


def _host_records(market, day):
    slug = allow.slug_for(market, day)
    replay, long_rows, features, nbm = [], [], [], []
    for hour in LOCAL_HOURS:
        local = _local(market, day, hour)
        sid, utc = _sid(local), local.astimezone(timezone.utc).isoformat()
        replay.append({"schema_version": 1, "snapshot_id": sid, "captured_at_utc": utc,
                       "captured_at_local": local.isoformat(), "event_slug": slug, "target_date": day.isoformat(),
                       "model_version": "v-test", "captured_input_hash": "c" * 64,
                       "recorded_distribution": {"80-81": 1.0},
                       "sources": {"metar": {"ok": True, "status": "fresh", "stale": False, "fetched_at": utc,
                                             "data": {"rows": _metar_rows(local), "station_id": "KXXX",
                                                      "target_date_match": True, "report_time": utc,
                                                      "raw": "x", "temp_native": 71.0}},
                                   "open_meteo_multimodel": {"ok": True, "fetched_at": utc, "data": {
                                       "day_model_highs": {"gfs_seamless": 84.0, "ncep_hrrr_conus": 85.0},
                                       "fetched_at": utc, "target_date_match": True}},
                                   **HOST_ONLY}})
        probs = [0.0, 0.1, 0.2, 0.4, 0.2, 0.1, 0.0]
        for (kind, lo, hi), p in zip(BANDS, probs):
            long_rows.append({"snapshot_id": sid, "captured_at_utc": utc, "captured_at_local": local.isoformat(),
                              "event_slug": slug, "model_version": "v-test", "range_label": f"{kind}{lo}",
                              "bin_kind": kind, "bin_value_c": lo, "bin_value_hi_c": hi if kind == "eq" else "",
                              "model_probability": p, "market_yes": 0.5, "best_bid": 0.4, "best_ask": 0.6})
        features.append({"snapshot_id": sid, "captured_at_utc": utc, "captured_at_local": local.isoformat(),
                         "event_slug": slug, "target_date": day.isoformat(), "model_version": "v-test",
                         "cutoff_hour": str(hour), "guidance_physical_floor": 81.6 if hour == 14 else "",
                         "high_so_far": 80.2 if hour == 14 else 70.0, "trusted_current_max": "",
                         "wu_history_high_c": 88.0})
        # BLOB is content-addressed, so it is one bulletin with one cycle identity (D 01Z) in every folder;
        # giving it each folder's own date made the earliest (D-1, past the lookback) win the digest entry.
        nbm.append({"snapshot_id": sid, "captured_at_utc": utc, "event_slug": slug, "source": allow.NBM_SOURCE,
                    "status": "fresh", "parser_version": "", "provider_issue_time": f"{D}T01:00:00+00:00",
                    "provider_update_time": "", "response_received_at": f"{D}T02:00:00+00:00",
                    "fetched_at": f"{D}T02:00:00+00:00", "first_seen_at": "", "cycle_key": f"nbm-nbp:{D:%Y%m%d}T01Z",
                    "payload_hash": BLOB_SHA, "payload_ref": allow.blob_ref(BLOB_SHA),
                    "payload_storage_scope": allow.NBM_SCOPE, "payload_bytes": len(BLOB)})
        nbm.append({"snapshot_id": sid, "captured_at_utc": utc, "event_slug": slug, "source": "open_meteo_multimodel"})
    return replay, long_rows, features, nbm


def _csv_text(rows, fields):
    import csv
    import io

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fields})
    return out.getvalue()


def _jsonl_text(rows):
    return "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def write_manifest(root, day=D, cut=None, **extra):
    """The exporter's manifest over every file under ``root`` (reference implementation for tests)."""
    root = Path(root)
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name not in (allow.MANIFEST, allow.MANIFEST_SHA)):
        rel = path.relative_to(root).as_posix()
        kind = allow.classify_path(rel, day)
        rows = None
        if kind and kind[0] in ("snapshots_long", "features_long"):
            rows = max(len(path.read_text(encoding="utf-8").splitlines()) - 1, 0)
        elif kind and kind[0] != "nbm_blob":
            rows = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        files.append({"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "bytes": path.stat().st_size, "rows": rows})
    manifest = {"schema": allow.BUNDLE_SCHEMA, "target_date": day.isoformat(),
                "export_cut_utc": (cut or allow.export_cut_utc(day)).isoformat(),
                "allowlist_sha256": allow.allowlist_sha256(), "files": files, **extra}
    (root / allow.MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (root / allow.MANIFEST_SHA).write_text(hashlib.sha256((root / allow.MANIFEST).read_bytes()).hexdigest() + "\n",
                                           encoding="utf-8")
    return manifest


def export_bundle(root, day=D, markets=allow.MARKETS):
    """A reference exporter: host-shaped records projected onto the allow-list."""
    root = Path(root)
    for market in markets:
        for offset in (-1, 0, 1):
            folder_day = day + timedelta(days=offset)
            slug = allow.slug_for(market, folder_day)
            replay, long_rows, features, nbm = _host_records(market, folder_day)
            folder = root / "snapshots" / slug
            folder.mkdir(parents=True, exist_ok=True)
            cut = allow.export_cut_utc(day)
            nbm_rows = [allow.project_row(r, allow.NBM_FIELDS) for r in nbm
                        if r.get("source") == allow.NBM_SOURCE and mi.parse_time(r["captured_at_utc"]) <= cut]
            (folder / "forecast_payloads.jsonl").write_text(_jsonl_text(nbm_rows), encoding="utf-8")
            if offset == 0:
                (folder / "replay_inputs.jsonl").write_text(
                    _jsonl_text([allow.project_replay_record(r) for r in replay]), encoding="utf-8")
                (folder / "snapshots_long.csv").write_text(
                    _csv_text(long_rows, allow.CSV_FIELDS["snapshots_long.csv"]), encoding="utf-8")
                (folder / "features_long.csv").write_text(
                    _csv_text(features, allow.CSV_FIELDS["features_long.csv"]), encoding="utf-8")
            if offset == -1:
                prev = root / "prev_day" / slug
                prev.mkdir(parents=True, exist_ok=True)
                (prev / "metar_rows.jsonl").write_text(_jsonl_text([allow.project_prev_day_record(replay[-1])]),
                                                       encoding="utf-8")
    blob = root / "forecast_payload_cas" / allow.blob_ref(BLOB_SHA)
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(BLOB)
    return write_manifest(root, day)


class FakeParser:
    parser_version = 2
    identity = {"head": "2e17ce0eb-fake", "module_sha256": "a" * 64}

    def __init__(self):
        self.calls = []

    def parse(self, blob, sha256, targets):
        assert hashlib.sha256(Path(blob).read_bytes()).hexdigest() == sha256
        self.calls.append((sha256, list(targets)))
        return None, [{"available": True, "reason": None, "parser_version": "v2", "issued_at": f"{D}T01:00:00+00:00",
                       "valid_time_utc": f"{D + timedelta(days=1)}T00:00:00+00:00", "forecast_hour": 23,
                       "period_kind": "maximum", "percentiles": {"10": 80.0, "25": 82.0, "50": 84.0, "75": 86.0,
                                                                 "90": 88.0},
                       "mean_native": 84.0, "stddev_native": 3.0} for _ in targets]

    def close(self):
        pass


@pytest.fixture()
def inbox(tmp_path):
    root = tmp_path / "inbox"
    export_bundle(root / D.isoformat() / "incoming")
    return root


def _receive(inbox, tmp_path, now=None):
    return mi.receive(inbox=inbox, day=D, ledger=tmp_path / "ledger.jsonl",
                      now=now or datetime(2026, 11, 3, 6, 30).astimezone())


def _incoming(inbox):
    return inbox / D.isoformat() / "incoming"


def _rewrite_jsonl(path, fn):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.write_text(_jsonl_text([fn(r) for r in rows]), encoding="utf-8")


# ----------------------------------------------------------------------------- allow-list

def test_allowlist_sha_is_canonical_and_stable():
    assert allow.allowlist_sha256() == allow.allowlist_sha256()
    blob = json.dumps(allow.contract(), sort_keys=True, separators=(",", ":")).encode()
    assert allow.allowlist_sha256() == hashlib.sha256(blob).hexdigest()


def test_allowlist_covers_the_scorecard_label_set_and_every_station_and_wu_surface():
    from weather.reporting.scorecards.dev_scorecard_data import LABELISH

    assert LABELISH <= allow.FORBIDDEN_KEYS
    for key in ("wu_history", "wu_current", "local_history", "station_observations", "station",
                "station_observation_source", "recorded_distribution", "market_yes", "reanalysis_prev_high",
                "wu_anything"):
        assert allow.forbidden(key)
    assert not set(allow.REPLAY_SOURCES) & allow.FORBIDDEN_KEYS


def test_markets_and_slugs_match_the_registry():
    from weather.market.market_config import event_slug_for_date
    from weather.market.market_registry import spec_for_id

    for market in allow.MARKETS:
        assert spec_for_id(market).display_unit == "F"
        for day in (D, date(2026, 12, 31), date(2027, 1, 9)):
            assert allow.slug_for(market, day) == event_slug_for_date(day, market)
            assert allow.parse_slug(allow.slug_for(market, day)) == (market, day)
    assert allow.parse_slug("highest-temperature-in-toronto-on-november-2-2026") is None
    assert allow.parse_slug("highest-temperature-in-nyc-on-november-02-2026") is None


def test_export_cut_is_midnight_ending_d_in_the_westernmost_market():
    cut = allow.export_cut_utc(D)
    assert cut == datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)  # PST after 2026-11-01
    for market in allow.MARKETS:
        assert cut.astimezone(ZoneInfo(TZ[market])).date() > D


def test_projection_drops_every_unlisted_and_forbidden_surface():
    replay, _, _, _ = _host_records("nyc", D)
    projected = allow.project_replay_record(replay[0])
    assert allow.replay_record_problems(projected) == []
    assert set(projected["sources"]) == {"metar", "open_meteo_multimodel"}
    assert projected["sources"]["open_meteo_multimodel"]["data"]["day_model_highs"] == {"gfs_seamless": 84.0}
    assert "recorded_distribution" not in projected
    problems = allow.replay_record_problems(replay[0])
    assert any(p.startswith("forbidden:sources.wu_history") for p in problems)
    assert any(p.startswith("forbidden:sources.station_observations") for p in problems)


def test_allowlist_module_is_pure_stdlib():
    tree = ast.parse((ROOT / "src/weather/calibration/mg2_input_allowlist.py").read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
             and n.module != "__future__"}
    assert mods <= {"hashlib", "json", "re", "datetime", "zoneinfo"}


# ----------------------------------------------------------------------------- receiver

def test_clean_bundle_verifies_and_is_recorded(inbox, tmp_path):
    receipt = _receive(inbox, tmp_path)
    assert receipt["status"] == "verified", receipt
    assert all(c["pass"] for c in receipt["checks"].values())
    assert (inbox / D.isoformat() / "verified" / allow.MANIFEST).is_file()
    assert not _incoming(inbox).exists()
    ledger = mi.read_ledger(tmp_path / "ledger.jsonl")
    assert [r["status"] for r in ledger] == ["verified"]
    assert ledger[0]["manifest_sha256"] == hashlib.sha256(
        (inbox / D.isoformat() / "verified" / allow.MANIFEST).read_bytes()).hexdigest()
    assert _receive(inbox, tmp_path)["status"] == "already_recorded"
    assert len(mi.read_ledger(tmp_path / "ledger.jsonl")) == 1


@pytest.mark.parametrize("mutate,check", [
    (lambda r: (r / allow.MANIFEST_SHA).write_text("0" * 64, encoding="utf-8"), "manifest_sha"),
    (lambda r: (r / "snapshots" / allow.slug_for("nyc", D) / "snapshots_long.csv").write_text(
        (r / "snapshots" / allow.slug_for("nyc", D) / "snapshots_long.csv").read_text(encoding="utf-8") + "\n",
        encoding="utf-8"), "files_match"),
    (lambda r: _set_manifest(r, allowlist_sha256="1" * 64), "allowlist_sha"),
])
def test_integrity_failures_refuse(inbox, tmp_path, mutate, check):
    mutate(_incoming(inbox))
    receipt = _receive(inbox, tmp_path)
    assert receipt["status"] == f"refused:{check}", receipt
    assert not receipt["checks"][check]["pass"]
    assert (inbox / "_refused" / D.isoformat() / "attempt-1").is_dir()
    assert not (inbox / D.isoformat() / "verified").exists()


def _set_manifest(root, **fields):
    manifest = json.loads((root / allow.MANIFEST).read_text(encoding="utf-8"))
    manifest.update(fields)
    (root / allow.MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (root / allow.MANIFEST_SHA).write_text(hashlib.sha256((root / allow.MANIFEST).read_bytes()).hexdigest(),
                                           encoding="utf-8")
    return True


def _nyc(root, name):
    return root / "snapshots" / allow.slug_for("nyc", D) / name


@pytest.mark.parametrize("mutate", [
    # an unlisted file (a settlement sidecar)
    lambda r: _nyc(r, "settlement.json").write_text("{}", encoding="utf-8"),
    # a WU source key in a replay record
    lambda r: _rewrite_jsonl(_nyc(r, "replay_inputs.jsonl"),
                             lambda x: {**x, "sources": {**x["sources"], "wu_history": {"ok": True, "data": {}}}}),
    # a station surface (master 2026-10-25: METAR only)
    lambda r: _rewrite_jsonl(_nyc(r, "replay_inputs.jsonl"), lambda x: {**x, "sources": {
        **x["sources"], "station_observations": {"ok": True, "data": {"rows": [],
                                                                       "station_observation_source": "metar"}}}}),
    # a forbidden key nested inside a METAR row
    lambda r: _rewrite_jsonl(_nyc(r, "replay_inputs.jsonl"), lambda x: {**x, "sources": {**x["sources"], "metar": {
        **x["sources"]["metar"], "data": {**x["sources"]["metar"]["data"], "rows": [
            {**row, "wu_history_high_c": 30.0} for row in x["sources"]["metar"]["data"]["rows"]]}}}}),
    # an unlisted data key
    lambda r: _rewrite_jsonl(_nyc(r, "replay_inputs.jsonl"), lambda x: {**x, "sources": {**x["sources"], "metar": {
        **x["sources"]["metar"], "data": {**x["sources"]["metar"]["data"], "temp_native": 70.0}}}}),
    # a forbidden key in the D-1 METAR rows
    lambda r: _rewrite_jsonl(r / "prev_day" / allow.slug_for("nyc", D - timedelta(days=1)) / "metar_rows.jsonl",
                             lambda x: {**x, "settlement_high": 80}),
    # a price column in the band tape
    lambda r: _nyc(r, "snapshots_long.csv").write_text(_csv_text(
        [], list(allow.CSV_FIELDS["snapshots_long.csv"]) + ["market_yes"]), encoding="utf-8"),
    # a non-NBM forecast manifest row
    lambda r: _rewrite_jsonl(_nyc(r, "forecast_payloads.jsonl"), lambda x: {**x, "source": "open_meteo_multimodel"}),
])
def test_forbidden_or_unlisted_names_quarantine(inbox, tmp_path, mutate):
    mutate(_incoming(inbox))
    write_manifest(_incoming(inbox))
    receipt = _receive(inbox, tmp_path)
    assert receipt["status"] == "quarantined", receipt
    assert receipt["reason"] == "forbidden_field"
    assert (inbox / "_quarantine" / D.isoformat() / "attempt-1" / allow.MANIFEST).is_file()
    assert not (inbox / D.isoformat() / "verified").exists()
    text = json.dumps(receipt)
    assert "30.0" not in text and "\"80\"" not in text  # names only, never values


def test_rows_after_the_export_cut_refuse(inbox, tmp_path):
    late = (allow.export_cut_utc(D) + timedelta(minutes=1)).isoformat()
    _rewrite_jsonl(_nyc(_incoming(inbox), "replay_inputs.jsonl"), lambda x: {**x, "captured_at_utc": late})
    write_manifest(_incoming(inbox))
    assert _receive(inbox, tmp_path)["status"] == "refused:dates_and_cut"


def test_wrong_target_date_refuses(inbox, tmp_path):
    _rewrite_jsonl(_nyc(_incoming(inbox), "replay_inputs.jsonl"), lambda x: {**x, "target_date": "2026-11-01"})
    write_manifest(_incoming(inbox))
    assert _receive(inbox, tmp_path)["status"] == "refused:dates_and_cut"


def test_a_missing_market_refuses_the_date(tmp_path):
    inbox = tmp_path / "inbox"
    export_bundle(_incoming(inbox), markets=[m for m in allow.MARKETS if m != "denver"])
    receipt = _receive(inbox, tmp_path)
    assert receipt["status"] == "refused:markets"
    assert receipt["checks"]["markets"]["problems"] == ["market_missing:denver"]


def test_a_blob_that_does_not_rehash_refuses(inbox, tmp_path):
    (_incoming(inbox) / "forecast_payload_cas" / allow.blob_ref(BLOB_SHA)).write_bytes(b"tampered")
    write_manifest(_incoming(inbox))
    assert _receive(inbox, tmp_path)["status"] == "refused:blob_hashes"


def test_late_missing_and_not_ready(inbox, tmp_path):
    after = mi.deadline(D) + timedelta(minutes=1)
    assert mi.deadline(D) == datetime(2026, 11, 4, 0, 0).astimezone()
    assert _receive(inbox, tmp_path, now=after)["status"] == "late"
    assert _receive(inbox, tmp_path, now=after)["status"] == "already_recorded"
    other = tmp_path / "other"
    other_ledger = tmp_path / "other.jsonl"
    assert mi.receive(inbox=other, day=D, ledger=other_ledger, now=datetime(2026, 11, 3, 7).astimezone())[
        "status"] == "not_ready"
    assert mi.read_ledger(other_ledger) == []
    assert mi.receive(inbox=other, day=D, ledger=other_ledger, now=after)["status"] == "missing"


def test_one_reexport_then_the_date_is_closed(inbox, tmp_path):
    _nyc(_incoming(inbox), "settlement.json").write_text("{}", encoding="utf-8")
    assert _receive(inbox, tmp_path)["status"] == "quarantined"
    export_bundle(_incoming(inbox))
    (_incoming(inbox) / allow.MANIFEST_SHA).write_text("0" * 64, encoding="utf-8")
    second = _receive(inbox, tmp_path)
    assert second["status"] == "refused:manifest_sha" and second["attempt"] == 2
    export_bundle(_incoming(inbox))
    assert _receive(inbox, tmp_path)["status"] == "already_recorded"
    assert [r["attempt"] for r in mi.read_ledger(tmp_path / "ledger.jsonl")] == [1, 2]


def test_ledger_is_append_only(inbox, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _receive(inbox, tmp_path)
    before = ledger.read_bytes()
    other = tmp_path / "inbox2"
    mi.receive(inbox=other, day=D + timedelta(days=1), ledger=ledger, now=mi.deadline(D + timedelta(days=1)))
    after = ledger.read_bytes()
    assert after.startswith(before) and len(after) > len(before)
    source = (ROOT / "src/weather/calibration/mg2_inputs.py").read_text(encoding="utf-8")
    assert source.count('open(path, "a"') == 1  # the only ledger write is the append


# ----------------------------------------------------------------------------- pull

def _tree(root):
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in Path(root).rglob("*") if p.is_file()}


def test_pull_is_read_only_and_copies_exactly(tmp_path):
    share = tmp_path / "share"
    export_bundle(share / D.isoformat())
    before = _tree(share / D.isoformat())
    result = mi.pull(share_root=share, day=D, inbox=tmp_path / "inbox", ledger=tmp_path / "ledger.jsonl")
    assert result["status"] == "pulled"
    assert _tree(share / D.isoformat()) == before
    copied = _tree(tmp_path / "inbox" / D.isoformat() / "incoming")
    assert {k: v[0] for k, v in copied.items()} == {k: v[0] for k, v in before.items()}
    assert mi.pull(share_root=share, day=D, inbox=tmp_path / "inbox",
                   ledger=tmp_path / "ledger.jsonl")["status"] == "already_pulled"


def test_pull_waits_for_the_ready_marker_and_skips_a_refused_bundle(tmp_path):
    share, inbox, ledger = tmp_path / "share", tmp_path / "inbox", tmp_path / "ledger.jsonl"
    export_bundle(share / D.isoformat())
    marker = (share / D.isoformat() / allow.MANIFEST_SHA).read_text(encoding="utf-8")
    (share / D.isoformat() / allow.MANIFEST_SHA).unlink()
    assert mi.pull(share_root=share, day=D, inbox=inbox, ledger=ledger)["status"] == "not_ready"
    (share / D.isoformat() / allow.MANIFEST_SHA).write_text(marker, encoding="utf-8")
    (share / D.isoformat() / "extra.txt").write_text("x", encoding="utf-8")
    assert mi.pull(share_root=share, day=D, inbox=inbox, ledger=ledger)["status"] == "pulled"
    assert mi.receive(inbox=inbox, day=D, ledger=ledger, now=datetime(2026, 11, 3, 7).astimezone())[
        "status"] == "quarantined"
    assert mi.pull(share_root=share, day=D, inbox=inbox, ledger=ledger)["status"] == "unchanged_since_refusal"


# ----------------------------------------------------------------------------- builder

@pytest.fixture()
def verified(inbox, tmp_path):
    assert _receive(inbox, tmp_path)["status"] == "verified"
    return inbox / D.isoformat() / "verified"


def _build(verified, out, parser=None):
    return mi.build(bundle=verified, out=out, day=D, parser=parser or FakeParser())


def test_build_writes_the_label_free_layout_with_parser_v2(verified, tmp_path):
    from weather.calibration import mg2_composite as mg2
    from weather.reporting.scorecards.dev_scorecard_data import LABELISH

    parser = FakeParser()
    layout = _build(verified, tmp_path / "layout", parser)
    snaps, bands = mg2.read_inputs(tmp_path / "layout")
    assert len(snaps) == 11 * len(LOCAL_HOURS) and layout["snapshots"] == len(snaps)
    assert not LABELISH & (set(snaps.columns) | set(bands.columns))
    # "station" here is the registry ICAO identity column of the dev layout, not a station surface
    assert not {c for c in set(snaps.columns) | set(bands.columns) if allow.forbidden(c)} - {"station"}
    assert (snaps.v2_parser_version == 2).all() and snaps.v2_parser_version.dtype == "int64"
    assert (snaps.v2_parser_module_sha256 == "a" * 64).all()
    assert (snaps.v2_status == "available").all() and (snaps.v2_mean == 84.0).all()
    assert (snaps.v2_period_kind == "maximum").all()
    row = snaps[(snaps.market == "nyc") & (snaps.local_hour == 14)].iloc[0]
    assert row.row_key == f"nyc|{row.snapshot_id}" and row.station == "KLGA" and row.block == "13-16"
    assert row.floor == pytest.approx(81.6) and row.floor_bucket == 82.0 and row.cutoff_hour == "14"
    assert row.stratum == "from_20260823" and row.date == D.isoformat() and row.n_bands == len(BANDS)
    b = bands[bands.row_key == row.row_key].sort_values("band_index")
    assert b.kind.tolist() == [k for k, _, _ in BANDS]
    assert b.floor_impossible.tolist() == [True, True, False, False, False, False, False]
    assert b.p_served.sum() == pytest.approx(1.0)
    checks = mg2.outcome_blind_checks(snaps, {rk: "mg1" for rk in snaps.row_key}, bands)
    assert checks["parser_pass"] and checks["pit_pass"]
    assert parser.calls and all(t[1] == D.isoformat() for _sha, ts in parser.calls for t in ts)
    assert layout["parser"]["parser_version"] == 2 and layout["parser"]["module_sha256"] == "a" * 64


def test_build_never_reads_prev_day(verified, tmp_path):
    _build(verified, tmp_path / "a")
    prev = next((verified / "prev_day").rglob("metar_rows.jsonl"))
    prev.write_bytes(b"\x00garbage, not json")
    _build(verified, tmp_path / "b")
    import shutil

    shutil.rmtree(verified / "prev_day")
    _build(verified, tmp_path / "c")
    for name in ("inputs_snapshots.parquet", "inputs_bands.parquet"):
        digests = {hashlib.sha256((tmp_path / x / name).read_bytes()).hexdigest() for x in "abc"}
        assert len(digests) == 1, name


def test_build_refuses_unverified_changed_or_non_v2_inputs(verified, inbox, tmp_path):
    with pytest.raises(mi.InputRefused, match="verified"):
        mi.build(bundle=inbox / "_refused", out=tmp_path / "x", day=D, parser=FakeParser())
    bad = FakeParser()
    bad.parser_version = 1
    with pytest.raises(mi.InputRefused, match="parser_version 2"):
        _build(verified, tmp_path / "y", bad)
    path = _nyc(verified, "features_long.csv")
    path.write_text(path.read_text(encoding="utf-8").replace("81.6", "99.9"), encoding="utf-8")
    with pytest.raises(mi.InputRefused, match="changed since verification"):
        _build(verified, tmp_path / "z")


def test_build_excludes_off_date_captures_and_bulletins_after_capture(tmp_path):
    inbox = tmp_path / "inbox"
    root = _incoming(inbox)
    export_bundle(root)
    off = _local("nyc", D, 3) - timedelta(hours=4)  # previous local date
    path = _nyc(root, "snapshots_long.csv")
    text = path.read_text(encoding="utf-8")
    first_utc = _local("nyc", D, 3).astimezone(timezone.utc).isoformat()
    path.write_text(text.replace(first_utc, off.astimezone(timezone.utc).isoformat()), encoding="utf-8")
    write_manifest(root)
    assert _receive(inbox, tmp_path)["status"] == "verified"
    layout = _build(inbox / D.isoformat() / "verified", tmp_path / "layout")
    assert layout["excluded_snapshots"] == {"nyc:capture_not_on_target_date": 1}


def test_builder_selection_equals_guidance_extract():
    from weather.reporting.research import guidance_extract as ge

    issue = datetime(2026, 11, 2, 1, tzinfo=timezone.utc)
    bulletins = {
        "h1": {"cycle_key": "nbm-nbp:20261102T01Z", "issue": issue, "available_at": issue + timedelta(hours=1),
               "available_basis": "response_received_at", "status": "parsed"},
        "h2": {"cycle_key": "nbm-nbp:20261102T07Z", "issue": issue + timedelta(hours=6),
               "available_at": issue + timedelta(hours=9), "available_basis": "fetched_at", "status": "parsed"},
        "h3": {"cycle_key": "nbm-nbp:20261102T13Z", "issue": issue + timedelta(hours=12),
               "available_at": issue + timedelta(hours=13), "available_basis": "fetched_at", "status": "bytes_missing"},
    }
    result = {"available": True, "percentiles": {"10": 80, "50": 84, "90": 88}, "mean_native": 84.0,
              "stddev_native": 3.0, "period_kind": "maximum", "forecast_hour": 23,
              "valid_time_utc": "2026-11-03T00:00:00+00:00"}
    parsed = {("h1", "KLGA", "2026-11-02"): result,
              ("h2", "KLGA", "2026-11-02"): {"available": False, "reason": "period_not_maximum"}}
    for hours in (0.5, 3, 8, 11, 14, 30):
        captured = issue + timedelta(hours=hours)
        assert mi.select_v2(bulletins, parsed, "KLGA", "2026-11-02", captured) == ge.select_v2(
            bulletins, parsed, "KLGA", "2026-11-02", captured, timedelta(hours=24))
    rows = [{"bin_kind": k, "bin_value_c": lo, "bin_value_hi_c": hi if k == "eq" else None} for k, lo, hi in BANDS]
    assert [x[:4] for x in mi.band_vector(rows)] == [x[:4] for x in ge.band_vector(rows)]
    assert mi.FLOOR_FIELDS == __import__("weather.reporting.scorecards.dev_scorecard_data",
                                         fromlist=["FLOOR_FIELDS"]).FLOOR_FIELDS
    from weather.reporting.scorecards import dev_scorecard

    assert mi.BLOCKS == dev_scorecard.BLOCKS


# ----------------------------------------------------------------------------- dataflow and import scan

LABEL_MODULES = ("weather.backtesting", "weather.reporting.scorecards", "weather.reporting.research.guidance_extract",
                 "weather.settlement", "weather.market.maker")
LABEL_LITERALS = ("labels.parquet", "market.parquet", "settlement.json", "settlements", "ledger.jsonl")


def _imports(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return tree, out


@pytest.mark.parametrize("name", ["mg2_inputs.py", "mg2_input_allowlist.py"])
def test_receiver_and_builder_never_import_label_or_scoring_code(name):
    tree, imports = _imports(ROOT / "src/weather/calibration" / name)
    bad = sorted(m for m in imports for p in LABEL_MODULES
                 if (m == p or m.startswith(p + ".")) and m != "weather.reporting.research.guidance_extract_parser")
    assert bad == []
    literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [s for s in literals if any(x in s for x in LABEL_LITERALS)]


def test_builder_functions_never_name_prev_day():
    tree = ast.parse((ROOT / "src/weather/calibration/mg2_inputs.py").read_text(encoding="utf-8"))
    builder = {"build", "bulletin_index", "parse_bulletins", "select_v2", "band_vector", "snapshot_rows",
               "_check_bundle_files", "_floor", "block_of", "cycle_time", "availability"}
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in builder:
            seen.add(node.name)
            text = ast.unparse(node)
            assert "prev_day" not in text and "metar" not in text.lower(), node.name
    assert seen == builder


@pytest.mark.spawns
def test_importing_the_receiver_loads_no_label_module():
    code = ("import sys, json; import weather.calibration.mg2_inputs as m; "
            "print(json.dumps(sorted(k for k in sys.modules if k.startswith('weather.'))))")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(ROOT),
                         timeout=120, check=True).stdout
    loaded = json.loads(out.strip().splitlines()[-1])
    assert not [m for m in loaded for p in LABEL_MODULES if m == p or m.startswith(p + ".")], loaded


def test_import_refuses_from_a_production_package():
    saved = sys.modules.pop("weather.calibration.mg2_inputs")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.mg2_inputs", {"__name__": "weather.serving.anything"})
    finally:
        sys.modules["weather.calibration.mg2_inputs"] = saved


def test_no_production_module_imports_the_receiver():
    hits = []
    for top in ("src", "app"):
        for path in (ROOT / top).rglob("*.py"):
            # the receiver itself, the binding (its release file list) and the allow-list (its docstring)
            if path.name in ("mg2_inputs.py", "mg2_composite.py", "mg2_input_allowlist.py"):
                continue
            if "mg2_inputs" in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(path.relative_to(ROOT).as_posix())
    assert hits == []


def test_receiver_and_builder_have_no_network_access():
    tree, imports = _imports(ROOT / "src/weather/calibration/mg2_inputs.py")
    net = ("socket", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib")
    assert not [m for m in imports if m.split(".")[0] in net]
    assert "://" not in (ROOT / "src/weather/calibration/mg2_inputs.py").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- concat (window layout)

D2 = D + timedelta(days=1)


def _layout_for(tmp_path, day, name):
    inbox, ledger = tmp_path / f"inbox-{name}", tmp_path / "ledger.jsonl"
    export_bundle(inbox / day.isoformat() / "incoming", day=day)
    assert mi.receive(inbox=inbox, day=day, ledger=ledger,
                      now=datetime.combine(day + timedelta(days=1), datetime.min.time()).astimezone()
                      + timedelta(hours=7))["status"] == "verified"
    out = tmp_path / f"layout-{name}"
    mi.build(bundle=inbox / day.isoformat() / "verified", out=out, day=day, parser=FakeParser())
    return out


def _rewrite_layout(root, fn, manifest_fn=None):
    snaps = pd.read_parquet(root / "inputs_snapshots.parquet")
    bands = pd.read_parquet(root / "inputs_bands.parquet")
    snaps, bands = fn(snaps, bands)
    snaps.to_parquet(root / "inputs_snapshots.parquet", index=False)
    bands.to_parquet(root / "inputs_bands.parquet", index=False)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name in mi.LAYOUT_FILES:
        manifest["files"][name]["sha256"] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    (manifest_fn or (lambda m: m))(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture()
def two_layouts(tmp_path):
    return _layout_for(tmp_path, D, "a"), _layout_for(tmp_path, D2, "b")


def test_concat_builds_one_window_readable_by_the_binding(two_layouts, tmp_path):
    from weather.calibration import mg2_composite as mg2

    a, b = two_layouts
    result = mi.concat(layouts=[b, a], out=tmp_path / "window", ledger=tmp_path / "ledger.jsonl")
    assert result["dates"] == [D.isoformat(), D2.isoformat()]
    snaps, bands = mg2.read_inputs(tmp_path / "window")
    assert len(snaps) == 2 * 11 * len(LOCAL_HOURS) and not snaps.row_key.duplicated().any()
    assert set(bands.row_key) == set(snaps.row_key)
    assert snaps.date.tolist() == sorted(snaps.date.tolist())
    manifest = json.loads((tmp_path / "window" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == mi.WINDOW_SCHEMA and manifest["ledger_checked"] is True
    assert [m["target_date"] for m in manifest["members"]] == result["dates"]
    assert manifest["parser"] == {"module_sha256": "a" * 64, "parser_version": 2}


def test_concat_refuses_a_duplicate_date(two_layouts, tmp_path):
    a, _b = two_layouts
    with pytest.raises(mi.InputRefused, match="duplicate target date"):
        mi.concat(layouts=[a, a], out=tmp_path / "w")


def test_concat_refuses_a_row_key_in_two_layouts(two_layouts, tmp_path):
    a, b = two_layouts
    key = pd.read_parquet(a / "inputs_snapshots.parquet").row_key.iloc[0]

    def clash(snaps, bands):
        old = snaps.row_key.iloc[0]
        snaps.loc[0, "row_key"] = key
        bands.loc[bands.row_key == old, "row_key"] = key
        return snaps, bands

    _rewrite_layout(b, clash)
    with pytest.raises(mi.InputRefused, match="more than one layout"):
        mi.concat(layouts=[a, b], out=tmp_path / "w")
    assert not (tmp_path / "w").exists()


def test_concat_refuses_a_duplicate_row_key_within_a_layout(two_layouts, tmp_path):
    a, b = two_layouts

    def dup(snaps, bands):
        snaps.loc[1, "row_key"] = snaps.row_key.iloc[0]
        return snaps, bands

    _rewrite_layout(b, dup)
    with pytest.raises(mi.InputRefused, match="duplicate row_key inside"):
        mi.concat(layouts=[a, b], out=tmp_path / "w")


def test_concat_refuses_tampered_mixed_or_unreceipted_layouts(two_layouts, tmp_path):
    a, b = two_layouts
    with pytest.raises(mi.InputRefused, match="no verified receipt"):
        mi.concat(layouts=[a, b], out=tmp_path / "w1", ledger=tmp_path / "empty.jsonl")
    _rewrite_layout(b, lambda s, x: (s, x), lambda m: m["parser"].update(module_sha256="b" * 64))
    with pytest.raises(mi.InputRefused, match="different allow-list, builder or parser"):
        mi.concat(layouts=[a, b], out=tmp_path / "w2")
    (a / "inputs_bands.parquet").write_bytes(b"tampered")
    with pytest.raises(mi.InputRefused, match="does not match its manifest"):
        mi.concat(layouts=[a, b], out=tmp_path / "w3")


def test_concat_cli_refuses_with_exit_2(two_layouts, tmp_path, capsys):
    a, _b = two_layouts
    assert mi.main(["concat", "--layout", str(a), "--layout", str(a), "--out", str(tmp_path / "w")]) == 2
    assert "duplicate target date" in capsys.readouterr().out
