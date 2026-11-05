"""Item 343b: the offline year-round refit of row 28's candidate B (synthetic data only).

Guards: item 343b design (docs/research/item343b-yearround-module-design-2026-11-03.md, accepted 2026-11-03) and
master's BUILD GO rulings: Rule L and the kept 2024-02-29 training row (row28_run_v12.py:1595-1600, 2004-2008),
fit_kind "forward" with both sha guards (Q-S), hard date bounds and no label or price reader (Q-G), weekly
as-of-capture emission (Q-W), train/serve parity to 1e-12, MG-2 emit_rows equality on the C5 window, the
equivalence harness and loop isolation (section 7).
"""
from __future__ import annotations

import ast
import builtins
import gzip
import hashlib
import json
import math
import os
import pickle
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

yr = import_or_skip_on_capture_host("weather.calibration.yearround_refit")
p3 = import_or_skip_on_capture_host("weather.calibration.mg2_p3d_n")
prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")

ROOT = Path(__file__).resolve().parents[2]
MODULE_FILE = ROOT / "src" / "weather" / "calibration" / "yearround_refit.py"
MARKETS = ("atlanta", "denver", "seattle")
CENTRES = ("2026-12-09", "2026-12-24", "2026-01-08", "2026-02-22", "2026-05-23", "2026-06-07")
YEARS = (2022, 2023, 2024)
FORBIDDEN_IMPORT = re.compile(r"venue_label|venue_rule_labels|settlement_ledger|market_day_labels|clob|price|"
                              r"orderbook|polymarket|execution_tape|b_scorer|ledger")


# ----------------------------------------------------------------------------- synthetic world

def _unit(*parts):
    h = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(h[:4], "big") / 2 ** 32


def _y(market, day):
    doy = day.timetuple().tm_yday
    return int(round(65 + 18 * math.sin(2 * math.pi * (doy - 100) / 365.25) + 3 * MARKETS.index(market)
                     + 6 * (_unit("y", market, day) - 0.5)))


def _payload(market, centre, years):
    records = {}
    for hour in (13, 14, 15, 16):
        rows = []
        for year in years:
            for day in prm.window_days(centre, year):
                y = _y(market, day)
                f = y - (16 - hour) * _unit("f", market, day, hour) * 1.5 - 0.3
                rows.append({"target_date": day.isoformat(), "final_bucket": y, "high_so_far": round(f, 1),
                             "current_temp": round(f - 1.0, 1),
                             "forecast_high": round(y + 4 * (_unit("fh", market, day) - 0.5), 1)})
        records[hour] = rows
    ys = [r["final_bucket"] for rs in records.values() for r in rs]
    return {"market": market, "centre": centre, "unit": "F", "bucket_space": list(range(min(ys) - 4, max(ys) + 5)),
            "plan": {"numeric_feature_names": ["high_so_far", "current_temp"], "all_wind_groups": [],
                     "all_cloud_groups": []},
            "records": records}


def _write_records(root, market, centre, payload):
    path = prm.records_path(root, market, centre)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _minimal_bound_state():
    return {"schema": p3.STATE_SCHEMA, "arm": p3.ARM, "fit_kind": "forward", "markets": [], "centres": [],
            "season_of": {}, "coords": {}, "buckets": {}, "constants": {"levels": []},
            "conversion": {"enabled": False, "rule_id": None, "rule": None},
            "late_report": {"rule": "last_in_hour", "grace_minutes": None}, "hours": {}, "provenance": {}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Synthetic records, NBM and fetch inputs, the module's constants pointed at them, hour 13 only."""
    monkeypatch.setattr(yr, "SCORED_HOURS", (13,))
    monkeypatch.setattr(yr, "FOLDS", (2023,))
    monkeypatch.setattr(yr, "REQUIRED_FIT_MARKETS", MARKETS)
    monkeypatch.setattr(yr, "state_root", lambda: tmp_path / "data" / "yearround_refit")
    monkeypatch.setattr(yr, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(yr, "_wu_market_root", lambda market: tmp_path / "wu_store" / market)  # never the real store
    from weather.sources.forecast_training_corpus import CorpusVerificationError

    def covered_years(centre, manifests):
        return list(YEARS) if centre in CENTRES else []

    def extract_market(market, centre, manifests, out_root, training_years=None):
        if market not in MARKETS:
            raise CorpusVerificationError("synthetic: market not in the test set")
        target = prm.records_path(out_root, market, centre)
        if target.exists():
            raise prm.PooledModelError("refusing to overwrite")
        return _write_records(out_root, market, centre, _payload(market, centre, training_years)), {}

    monkeypatch.setattr(prm, "covered_years", covered_years)
    monkeypatch.setattr(prm, "extract_market", extract_market)
    real_sets = yr.centre_sets  # the synthetic world builds only its own record windows (ruling 1 refuses gaps)
    monkeypatch.setattr(yr, "record_centres", lambda prm_: tuple(c for c in real_sets(prm_)["A"] if c in CENTRES))
    monkeypatch.setattr(yr, "record_markets", lambda prm_: MARKETS)
    # NBM: an L9-format corpus with a 07Z mean for every (market, date) but one; the new-rows build is empty.
    rows = []
    for market in MARKETS:
        for centre in CENTRES:
            for year in YEARS:
                for day in prm.window_days(centre, year):
                    if (market, day) == ("atlanta", date(2023, 2, 20)):
                        continue
                    rows.append({"market_id": market, "target_date": day.isoformat(), "cycle": "07",
                                 "available": True,
                                 "mean": _y(market, day) + 1.0 + 5 * (_unit("nbm", market, day) - 0.5),
                                 "last_modified": f"{day.isoformat()}T08:30:00Z"})
    l9_corpus = tmp_path / "l9" / "nbm_pit_corpus_rows.jsonl"
    l9_corpus.parent.mkdir()
    l9_corpus.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(yr, "L9_CORPUS_SHA256", _sha(l9_corpus))
    fetch = tmp_path / "fetch"
    (fetch / "nbp").mkdir(parents=True)
    blocks = {}
    for key, (rel, manifest) in yr.BLOCK_FILES.items():
        path = fetch / rel
        path.write_text(json.dumps({"utc_date": "2023-06-05", "k": key}) + "\n"
                        + json.dumps({"utc_date": "2023-03-05", "k": key}) + "\n", encoding="utf-8")
        blocks.setdefault(manifest, {})[rel] = {"sha256": _sha(path)}
    shas = {}
    for manifest, files in blocks.items():
        (fetch / manifest).write_text(json.dumps({"files": files}), encoding="utf-8")
        shas[manifest] = _sha(fetch / manifest)
    monkeypatch.setattr(yr, "FETCH_MANIFEST_SHA256", shas)

    def build_new_nbm_rows(l9, blocks_in, out_dir):
        Path(out_dir).mkdir(parents=True)
        path = Path(out_dir) / "nbm_pit_corpus_rows.jsonl"
        path.write_text("", encoding="utf-8")
        return path

    monkeypatch.setattr(yr, "build_new_nbm_rows", build_new_nbm_rows)
    bound = tmp_path / "bound" / "p3d_n_state.pkl"
    bound.parent.mkdir()
    bound.write_bytes(pickle.dumps(_minimal_bound_state(), protocol=4))
    monkeypatch.setattr(yr, "BOUND_P3D_N_STATE_SHA256", _sha(bound))

    def cfg():
        return {"pit_corpora": str(tmp_path / "pit"), "fetch_dir": str(fetch), "l9_corpus": str(l9_corpus),
                "bound_state": str(bound)}

    cfg.root = lambda records="records": str(tmp_path / records)  # the required --records-root, never config
    return cfg


def _frame(world, tmp_path):
    mods = yr._modules()
    n = len(list((tmp_path / "data").glob("yearround_refit/t/nbm*")))
    files, _ = yr.build_records(world(), mods.prm, world.root(f"records{n}"))  # a fresh root: a reuse needs lists
    frame, payload_buckets, report = yr.training_frame(world(), mods, files, yr.state_root() / "t" / f"nbm{n}")
    return mods, frame, payload_buckets, report


# ----------------------------------------------------------------------------- centres, rows, buckets

def test_centre_sets_rule_l_and_wrap_check_over_a_leap_year():
    sets = yr.centre_sets(prm)
    assert len(sets["A"]) == 24 and len(sets["B"]) == 11 and set(sets["B"]) <= set(sets["A"])
    assert sets["B"] == tuple(prm.JAN_JUL_CENTRES[:10]) + ("2026-12-24",)
    for arm in yr.ARMS:
        assert yr.centre_for(prm, sets[arm], "2024-02-29") == "2026-02-22"
        assert yr.centre_for(prm, sets[arm], "2024-02-28") == "2026-02-22"
        days = [date(2024, 1, 1) + timedelta(days=k) for k in range(366)]
        assert yr.wrap_check(prm, days, sets[arm]) == 366
    with pytest.raises(ValueError):
        prm.nearest_centre("2024-02-29", sets["B"])  # the bound lookup that Rule L protects
    assert yr.centre_for(prm, sets["B"], "2025-05-31") == "2026-05-23"
    assert yr.centre_for(prm, sets["B"], "2024-12-17") == "2026-12-24"
    assert yr.centre_for(prm, sets["B"], "2025-01-03") == "2026-01-08"
    assert yr.season_map(prm, sets["B"]) == {"01": "jan_jul", "02": "jan_jul", "03": "jan_jul", "04": "jan_jul",
                                            "05": "jan_jul", "12": "oct_dec"}


def test_feb29_training_row_is_kept_with_its_real_date_and_held_out_only_in_fold_2024(world, tmp_path):
    mods, frame, payload_buckets, _ = _frame(world, tmp_path)
    framed = yr.with_arm_centres(prm, yr.centre_sets(prm), frame, "B")
    leap = framed[framed["target_date"] == "2024-02-29"]
    assert len(leap) == len(MARKETS) * 4 and set(leap["centre"]) == {"2026-02-22"}
    doy = date(2024, 2, 29).timetuple().tm_yday
    assert (leap["doy_sin"] == math.sin(2 * math.pi * doy / 365.25)).all()
    for fold in (2021, 2022, 2023, 2025, 2026):
        assert "2024-02-29" in set(yr.arm_rows(framed, "B", 13, fold)["target_date"])
    assert "2024-02-29" not in set(yr.arm_rows(framed, "B", 13, 2024)["target_date"])


def test_b_filters_on_target_date_and_folds_hold_out_a_season_year(world, tmp_path):
    mods, frame, payload_buckets, _ = _frame(world, tmp_path)
    sets = yr.centre_sets(prm)
    framed = yr.with_arm_centres(prm, sets, frame, "B")
    train = yr.arm_rows(framed, "B", 13, 2026)
    assert train["target_date"].map(yr.in_dec_may).all() and (train["hour"] == 13).all()
    assert "2023-05-31" in set(train["target_date"])  # May 31 sits in the 06-07 payload window
    assert set(train.loc[train["target_date"] == "2023-05-31", "centre"]) == {"2026-05-23"}
    assert set(train.loc[train["payload_centre"] == "2026-12-09", "target_date"]) == set()
    assert set(train.loc[train["target_date"].str[5:7] == "12", "centre"]) == {"2026-12-24"}
    assert (train["target_date"] <= "2025-12-16").all()
    held = yr.arm_rows(framed, "B", 13, 2023)
    assert not (held["sy"] == 2023).any() and (train["sy"] == 2023).any()
    assert yr.season_year("2022-12-17") == 2023 and yr.season_year("2022-12-16") == 2022
    framed_a = yr.with_arm_centres(prm, sets, frame, "A")
    assert len(yr.arm_rows(framed_a, "A", 13, 2026)) > len(train)


def test_bucket_space_is_payload_union_plus_training_label_range():
    frame = pd.DataFrame({"market": ["atlanta"] * 3, "payload_centre": ["2026-01-08", "2026-01-08", "2026-02-22"],
                          "y": [50.0, 75.0, 61.0]})
    buckets = yr.arm_buckets({("atlanta", "2026-01-08"): [60, 61], ("atlanta", "2026-02-22"): [80]}, frame)
    assert buckets == {"atlanta": list(range(50, 76)) + [80]}


def test_training_window_bound_refuses_a_row_outside_it():
    ok = pd.DataFrame({"target_date": ["2020-12-17", "2025-12-16"]})
    yr.check_training_window(ok)
    for bad in ("2020-12-16", "2025-12-17", "2026-01-05"):
        with pytest.raises(yr.YearroundRefused, match="training_window"):
            yr.check_training_window(pd.DataFrame({"target_date": ["2023-01-05", bad]}))


# ----------------------------------------------------------------------------- state and parity

def test_forward_state_contract_and_train_serve_parity_to_1e12(world, tmp_path):
    mods, frame, payload_buckets, report = _frame(world, tmp_path)
    assert report["train_nbm"]["train_nbm_imputed_forecast"] == 4  # the one missing (market, date), hours 13-16
    state, info = yr.arm_state(mods, frame, payload_buckets, "B", 2026, hours=(13, 15),
                               provenance={"candidate": yr.CANDIDATE_ID, "shadow_only": True})
    assert p3.state_problems(state) == [] and state["fit_kind"] == "forward"
    assert state["markets"] == list(MARKETS) and state["centres"] == list(yr.centre_sets(prm)["B"])
    assert set(info["training_rows_sha256"]) == {13, 15}
    framed = yr.with_arm_centres(prm, yr.centre_sets(prm), frame, "B")
    months = set()
    for hour in (13, 15):
        train = yr.arm_rows(framed, "B", hour, 2026)
        rows = train[train["target_date"] != "2024-02-29"].drop(columns=["y"])
        entry = state["hours"][hour]
        fitted = {"mean": None, "scale": entry["scale"], "z": entry["z"]}
        refit = yr.fit_hour(prm, train)
        fitted["mean"] = refit["fit"]["mean"]
        trainer = yr.trainer_predict(mods, refit["fit"], refit["train_y"], state["buckets"], rows)
        for (market, day, h), _, _, dist in trainer:
            row = rows[(rows["market"] == market) & (rows["target_date"] == day)].iloc[0]
            served = p3.serve_distribution(state, market=market, target_date=day, hour=h, nbm_mean=float(row["fh"]),
                                           high_so_far=float(row["F"]), current_temp=float(row["x_current_temp"]))
            assert set(served) == set(dist)
            assert max(abs(served[k] - dist[k]) for k in dist) <= 1e-12
            assert abs(sum(served.values()) - 1.0) <= 1e-12 and min(served.values()) >= 0.0
            months.add(day[5:7])
    assert {"12", "01", "02", "05"} <= months


def test_freeze_refuses_the_bound_sha_before_writing_and_writes_once(world, tmp_path, monkeypatch):
    state = _minimal_bound_state() | {"provenance": {"candidate": yr.CANDIDATE_ID}}
    sha = hashlib.sha256(pickle.dumps(state, protocol=4)).hexdigest()
    out = tmp_path / "data" / "yearround_refit" / "f"
    monkeypatch.setattr(yr, "BOUND_P3D_N_STATE_SHA256", sha)
    with pytest.raises(yr.YearroundRefused, match="bound P3d_N"):
        yr.freeze_state(p3, state, out)
    assert not (out / p3.STATE_FILE).exists()
    monkeypatch.setattr(yr, "BOUND_P3D_N_STATE_SHA256", "0" * 64)
    assert yr.freeze_state(p3, state, out) == sha
    with pytest.raises(p3.P3dNRefused, match="overwrite"):
        yr.freeze_state(p3, state, out)


def test_release_binding_shas_are_refused_and_include_the_bound_state():
    listed = yr.release_binding_shas()
    assert yr.BOUND_P3D_N_STATE_SHA256 in listed
    for sha in sorted(listed)[:3]:
        with pytest.raises(yr.YearroundRefused):
            yr.refuse_bound_sha(sha, where="emit")
    yr.refuse_bound_sha("f" * 64, where="emit")


def test_state_schema_and_family_pins():
    from weather.schema_families import yearround_refit as fam

    assert yr.STATE_SCHEMA == p3.STATE_SCHEMA
    got = {s.name: s.version for s in fam.SCHEMAS}
    assert got == {"yearround_refit_fit_manifest": yr.FIT_MANIFEST_SCHEMA,
                   "yearround_refit_shadow_receipt": yr.SHADOW_RECEIPT_SCHEMA,
                   "yearround_refit_equivalence": yr.EQUIVALENCE_SCHEMA,
                   "yearround_refit_forward_receipt": yr.FORWARD_RECEIPT_SCHEMA,
                   "yearround_refit_records_manifest": yr.RECORDS_MANIFEST_SCHEMA}
    from weather.model import toronto_model
    from weather.model.model_constants import INTRADAY_CUTOFF_HOURS

    assert tuple(toronto_model.INTRADAY_CUTOFF_HOURS) == tuple(INTRADAY_CUTOFF_HOURS)  # emit_rows' source


# ----------------------------------------------------------------------------- fit end to end

def _fit_cfg(tmp_path, world):
    walk = _frozen_list(tmp_path, world)
    return world() | {"frozen_records_lists": [[str(walk[0]), walk[1]]]}


def test_fit_freezes_writes_once_and_archives_sha_equal(world, tmp_path):
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    cfg = _fit_cfg(tmp_path, world)
    result = yr.fit(cfg, arm="B", now=now, records_root=world.root())
    fit_dir = Path(result["fit_dir"])
    manifest = json.loads((fit_dir / yr.FIT_MANIFEST).read_text(encoding="utf-8"))
    assert _sha(fit_dir / yr.FIT_MANIFEST) == result["fit_manifest_sha256"]
    assert manifest["state_sha256"] == result["state_sha256"] == _sha(fit_dir / p3.STATE_FILE)
    assert manifest["fit_kind"] == "forward" and manifest["candidate_id"] == "row28_B"
    assert manifest["markets"] == list(yr.EMIT_MARKETS) and "denver" not in manifest["markets"]
    assert manifest["scored_window"] == ["2026-12-17", "2027-01-30"]
    assert manifest["emission_window"] == ["2026-12-17", "2027-05-31"]
    assert manifest["frozen_before_utc"] == yr.FROZEN_BEFORE_UTC and manifest["input_modes"] == ["as_of_capture"]
    assert set(manifest["upstream_sha256"]) >= set(yr.PINNED_MODULE_SHA256)
    assert manifest["source_presence"]["calendar_grid"]["holes"] == 0  # F8
    assert manifest["source_presence"]["wu_hourly_market_dates"] > 0
    assert manifest["imputation_by_market_month"]["by_market_month"]  # F3(c), reported only
    archive = Path(result["archive_dir"])
    assert archive == tmp_path / "archive" / fit_dir.name
    for name in (p3.STATE_FILE, p3.STATE_SIDECAR, yr.FIT_MANIFEST):
        assert _sha(archive / name) == _sha(fit_dir / name) == result["archive_sha256"][name]
    assert all(yr.verify_archive(fit_dir, archive, result["archive_sha256"]).values())
    text = (fit_dir / yr.FIT_MANIFEST).read_text(encoding="utf-8")
    assert '"y"' not in text and "final_bucket" not in text and "brier" not in text.lower()
    state = p3.load_state(fit_dir / p3.STATE_FILE, result["state_sha256"], forward=True)
    assert state["provenance"]["shadow_only"] is True and state["provenance"]["candidate"] == "row28_B"
    with pytest.raises(yr.YearroundRefused, match="write-once"):
        yr.fit(cfg, arm="B", now=now, records_root=world.root())
    with pytest.raises(yr.YearroundRefused, match="frozen before"):
        yr.fit(cfg, arm="B", now=datetime(2026, 12, 17, tzinfo=timezone.utc), records_root=world.root())
    with pytest.raises(yr.YearroundRefused, match="forward fit"):
        yr.fit(cfg, arm="A", now=now, records_root=world.root())


# ----------------------------------------------------------------------------- emit

def _metar_row(obs_local, temp, tz):
    t = obs_local.astimezone(timezone.utc)
    return {"raw": f"METAR KATL {t:%d%H%M}Z 00000KT 10SM CLR {round((temp - 32) * 5 / 9):02d}/10 A3000",
            "datetime": t.isoformat(), "report_time": t.isoformat(), "temp_native": temp, "station_id": "KATL"}


def _replay(folder, day, tz, captures):
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (cap, obs) in enumerate(captures):
        lines.append(json.dumps({"snapshot_id": f"s{i}", "captured_at_local": cap.isoformat(),
                                 "captured_at_utc": cap.astimezone(timezone.utc).isoformat(),
                                 "target_date": day.isoformat(),
                                 "sources": {"metar": {"data": {"rows": [_metar_row(o, t, tz) for o, t in obs],
                                                                "station_id": "KATL"}}}}))
    (folder / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _event_folder(root, market, day):
    months = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
              "november", "december")
    return root / "snapshots" / f"highest-temperature-in-{market}-on-{months[day.month - 1]}-{day.day}-{day.year}"


def _f(t):
    return 32 + 9 * t / 50


def _snaps(rows, tz):
    return pd.DataFrame({
        "row_key": [r[0] for r in rows], "snapshot_id": [r[0].split("|")[1] for r in rows],
        "market": ["atlanta"] * len(rows), "target_date": [r[1].isoformat() for r in rows],
        "local_hour": [r[2].hour for r in rows], "cutoff_hour": [str(r[3]) for r in rows],
        "v2_mean": [80.0] * len(rows), "v2_stddev": [2.0] * len(rows),
        "v2_available_at": [datetime.combine(r[1], datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
                            .isoformat() for r in rows],
        "captured_at_utc": [r[2].astimezone(timezone.utc).isoformat() for r in rows]})


def _replay_world(root, days, tz):
    rows = []
    for day in days:
        def at(h, m, d=day):
            return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)

        early = [(at(11, 52), _f(256)), (at(12, 52), _f(261))]
        late = early + [(at(12, 59), _f(283))]
        _replay(_event_folder(root, "atlanta", day), day, tz, [(at(13, 5), early), (at(13, 40), late)])
        rows += [(f"atlanta|a{day.day}", day, at(13, 20), 13), (f"atlanta|b{day.day}", day, at(13, 45), 13),
                 (f"atlanta|c{day.day}", day, at(12, 30), 13), (f"atlanta|d{day.day}", day, at(13, 50), 21)]
    return _snaps(rows, tz)


@pytest.fixture
def b_state(world, tmp_path):
    mods, frame, payload_buckets, _ = _frame(world, tmp_path)
    state, _ = yr.arm_state(mods, frame, payload_buckets, "B", 2026, hours=(13,),
                            provenance={"candidate": yr.CANDIDATE_ID, "shadow_only": True,
                                        "helper_source_sha256": yr.helper_source_shas()})
    return state


def test_shadow_rows_equal_mg2_emit_rows_on_the_c5_window(b_state, tmp_path):
    tz = ZoneInfo("America/New_York")
    days = [date(2026, 11, 2), date(2026, 12, 16), date(2026, 12, 17)]
    snaps = _replay_world(tmp_path / "replay", days, tz)
    ours, stats, used = yr.shadow_rows(b_state, snaps, tmp_path / "replay", days[0], days[-1], ["atlanta"],
                                       in_coverage=p3.in_training_coverage)
    theirs, their_stats = p3.emit_rows(b_state, snaps, tmp_path / "replay", days[0], days[-1], markets=["atlanta"],
                                       inputs="as_of_capture")
    assert ours == theirs and stats == their_stats
    body = "".join(p3.jsonl_line(m, s, t, d) for m, s, t, _, d in ours)
    assert body == "".join(p3.jsonl_line(m, s, t, d) for m, s, t, _, d in theirs)
    assert stats["atlanta"]["outside_training_coverage"] == 2 and len(used) == 2  # 12-17: rows a and b


def test_b_coverage_emits_dec_to_may_and_never_admits_a_late_report(b_state, tmp_path):
    tz = ZoneInfo("America/New_York")
    day = date(2026, 12, 21)
    snaps = _replay_world(tmp_path / "replay", [day], tz)
    rows, stats, _ = yr.shadow_rows(b_state, snaps, tmp_path / "replay", day, day, ["atlanta"])
    kw = dict(market="atlanta", target_date=day.isoformat(), hour=13, nbm_mean=80.0)
    no_late = p3.serve_distribution(b_state, **kw, high_so_far=_f(261), current_temp=_f(261))
    with_late = p3.serve_distribution(b_state, **kw, high_so_far=_f(283), current_temp=_f(283))
    assert {r[3]: r[4] for r in rows} == {"atlanta|a21": no_late, "atlanta|b21": with_late}
    assert stats["atlanta"]["local_hour_before_cutoff"] == 1 and stats["atlanta"]["outside_cutoff_hours"] == 1
    again, _, _ = yr.shadow_rows(b_state, snaps, tmp_path / "replay", day, day, ["atlanta"])
    assert again == rows


def test_window_bounds_batch_receipt_and_after_the_fact(monkeypatch):
    receipt = ["2026-12-17", "2027-05-31"]
    today = date(2027, 1, 10)
    yr.check_window(date(2026, 12, 17), date(2026, 12, 20), receipt, today)
    yr.check_window(date(2026, 12, 21), date(2026, 12, 27), receipt, today)
    cases = [((date(2026, 12, 16), date(2026, 12, 18)), "emission window"),
             ((date(2027, 5, 30), date(2027, 6, 1)), "emission window"),
             ((date(2026, 12, 21), date(2026, 12, 28)), "at most 7"),
             ((date(2027, 1, 8), date(2027, 1, 10)), "after the fact"),
             ((date(2026, 12, 20), date(2026, 12, 19)), "after last")]
    for (first, last), needle in cases:
        with pytest.raises(yr.YearroundRefused, match=needle):
            yr.check_window(first, last, receipt, today)
    with pytest.raises(yr.YearroundRefused, match="receipt"):
        yr.check_window(date(2026, 12, 21), date(2026, 12, 22), ["2027-01-01", "2027-05-31"], today)
    monkeypatch.setattr(yr, "EMISSION_WINDOW", ("2027-12-17", "2028-05-31"))
    with pytest.raises(yr.YearroundRefused, match="Feb 29"):
        yr.check_window(date(2028, 2, 27), date(2028, 3, 1), ["2027-12-17", "2028-05-31"], date(2028, 4, 1))


def test_snapshot_screen_refuses_label_settlement_and_price_columns(tmp_path):
    base = {c: ["x"] for c in p3.SNAPSHOT_COLUMNS}
    pd.DataFrame(base).to_parquet(tmp_path / "ok.parquet")
    assert list(yr.read_snapshots(tmp_path / "ok.parquet").columns) == list(p3.SNAPSHOT_COLUMNS)
    for bad in ("settlement_high", "yes_price", "label_native", "y", "outcome", "best_bid"):
        pd.DataFrame(base | {bad: ["v"]}).to_parquet(tmp_path / f"{bad}.parquet")
        with pytest.raises(yr.YearroundRefused, match="label, settlement or price"):
            yr.read_snapshots(tmp_path / f"{bad}.parquet")
    pd.DataFrame({c: ["x"] for c in p3.SNAPSHOT_COLUMNS[:-1]}).to_parquet(tmp_path / "short.parquet")
    with pytest.raises(yr.YearroundRefused, match="lacks"):
        yr.read_snapshots(tmp_path / "short.parquet")


def _emit_inputs(tmp_path, state, manifest_extra=None):
    manifest_extra = manifest_extra or {}
    out = tmp_path / "data" / "yearround_refit" / "row28_B" / "20261103T120000Z"
    sha = yr.freeze_state(p3, state, out)
    manifest = {"schema": yr.FIT_MANIFEST_SCHEMA, "candidate_id": "row28_B", "state_sha256": sha,
                "fit_id": "20261103T120000Z", "fitted_at_utc": "2026-11-03T12:00:00+00:00",
                "sklearn_version": yr._versions()["sklearn"], "module_source_sha256": yr.module_source_sha256(),
                "upstream_sha256": yr.upstream_shas()} | manifest_extra
    (out / yr.FIT_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    msha = _sha(out / yr.FIT_MANIFEST)
    receipt = {"schema": yr.FORWARD_RECEIPT_SCHEMA, "candidate_id": "row28_B", "state_sha256": sha,
               "fit_manifest_sha256": msha, "forward_prereg_sha256": "a" * 64,
               "owner_approval": "synthetic test record", "window": ["2026-12-17", "2027-05-31"]}
    (tmp_path / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return out, sha, msha, _sha(tmp_path / "receipt.json")


def test_emit_end_to_end_prints_both_shas_and_refuses_a_rerun(b_state, tmp_path, monkeypatch):
    monkeypatch.setattr(yr, "EMIT_MARKETS", ("atlanta",))  # the synthetic replay world captures atlanta only
    tz = ZoneInfo("America/New_York")
    days = [date(2026, 12, 21), date(2026, 12, 22)]
    snaps = _replay_world(tmp_path / "replay", days, tz)
    snaps.to_parquet(tmp_path / "snaps.parquet")
    out, sha, msha, rsha = _emit_inputs(tmp_path, b_state)
    kw = dict(state_path=out / p3.STATE_FILE, state_sha=sha, fit_manifest=out / yr.FIT_MANIFEST,
              fit_manifest_sha=msha, forward_receipt=tmp_path / "receipt.json", forward_receipt_sha=rsha,
              snapshots=tmp_path / "snaps.parquet", replay_root=tmp_path / "replay", first="2026-12-21",
              last="2026-12-22", today=date(2026, 12, 28))
    result = yr.emit(**kw)
    batch = Path(result["out_dir"])
    assert result["shadow_rows_sha256"] == _sha(batch / yr.SHADOW_ROWS)
    assert result["emit_receipt_sha256"] == _sha(batch / yr.EMIT_RECEIPT) and result["rows"] == 4
    receipt = json.loads((batch / yr.EMIT_RECEIPT).read_text(encoding="utf-8"))
    assert receipt["shadow_rows_sha256"] == result["shadow_rows_sha256"] and receipt["inputs"] == "as_of_capture"
    assert len(receipt["replay_sha256"]) == 2 and receipt["state_sha256"] == sha
    assert receipt["holes"] == 0 == result["holes"] and receipt["hole_records"] == []  # F3(d)
    assert receipt["source_presence"]["market_dates"] == 2 and _sha(batch / yr.HOLES) == receipt["holes_sha256"]
    rows, _, _ = yr.shadow_rows(b_state, yr.read_snapshots(tmp_path / "snaps.parquet", days[0], days[1]),
                                tmp_path / "replay",
                                days[0], days[1], yr.EMIT_MARKETS)
    body = "".join(p3.jsonl_line(m, s, t, d) for m, s, t, _, d in rows).encode()
    assert hashlib.sha256(body).hexdigest() == result["shadow_rows_sha256"]  # re-emission is byte-identical
    with pytest.raises(yr.YearroundRefused, match="write-once"):
        yr.emit(**kw)
    with pytest.raises(yr.YearroundRefused, match="as_of_capture"):
        yr.emit(**kw | {"inputs": "last_in_hour"})
    with pytest.raises(yr.YearroundRefused, match="outside the batch"):
        yr.emit(**kw | {"first": "2026-12-22"})
    with pytest.raises(yr.YearroundRefused, match="sha256 differs"):
        yr.emit(**kw | {"forward_receipt_sha": "0" * 64})


def test_forward_receipt_must_name_the_state_the_manifest_and_an_approval(tmp_path):
    good = {"schema": yr.FORWARD_RECEIPT_SCHEMA, "candidate_id": "row28_B", "state_sha256": "1" * 64,
            "fit_manifest_sha256": "2" * 64, "forward_prereg_sha256": "3" * 64, "owner_approval": "ok",
            "window": ["2026-12-17", "2027-01-30"]}
    for change, needle in ((None, None), ({"state_sha256": "9" * 64}, "does not name"),
                           ({"owner_approval": " "}, "owner approval"), ({"forward_prereg_sha256": "x"}, "prereg"),
                           ({"window": ["2026-12-01", "2027-01-30"]}, "outside the emission"),
                           ({"schema": "other/1"}, "not a row28_B")):
        path = tmp_path / "r.json"
        path.write_text(json.dumps(good | (change or {})), encoding="utf-8")
        call = dict(state_sha="1" * 64, manifest_sha="2" * 64)
        if needle is None:
            assert yr.load_forward_receipt(path, _sha(path), **call)["window"] == good["window"]
        else:
            with pytest.raises(yr.YearroundRefused, match=needle):
                yr.load_forward_receipt(path, _sha(path), **call)


# ----------------------------------------------------------------------------- equivalence harness

FAKE_RUNNER = '''
"""A stand-in with the frozen runner's API, built from the module's own port (harness test only)."""
from weather.calibration import yearround_refit as yr

LAST_TRAIN = yr.LAST_TRAIN
season_year = yr.season_year
DROP_FIRST_TRAINING_ROW = {drop}


def market_frame(ctx, files, with_labels):
    return yr.market_frame(ctx.prm, files, with_labels)


def merged_table(ctx, paths):
    return yr.merged_table(ctx.l9, paths)


def with_arm_centres(ctx, frame, arm):
    return yr.with_arm_centres(ctx.prm, ctx.centres, frame, arm)


def arm_training(frame, arm, hour, fold):
    out = yr.arm_rows(frame, arm, hour, fold)
    return out.iloc[1:].reset_index(drop=True) if DROP_FIRST_TRAINING_ROW else out


def arm_buckets(payload_buckets, train):
    return yr.arm_buckets(payload_buckets, train)

'''


def _runner(tmp_path, drop=False):
    path = tmp_path / f"runner_{int(drop)}.py"
    path.write_text(FAKE_RUNNER.format(drop=drop), encoding="utf-8")
    return path, _sha(path)


def _frozen_list(tmp_path, world, alter=False):
    """The frozen side's path/sha list (built once from a separate records root of the same synthetic world)."""
    mods = yr._modules()
    if not (tmp_path / "records_frozen" / yr.RECORDS_MANIFEST).is_file():  # a reuse would need the frozen lists
        yr.build_records(world(), mods.prm, world.root("records_frozen"))
    manifest = json.loads((tmp_path / "records_frozen" / yr.RECORDS_MANIFEST).read_text(encoding="utf-8"))
    lines = ["path,sha256,payload_sha256"]
    for i, (name, entry) in enumerate(sorted(manifest["files"].items())):
        payload = ("0" * 64) if (alter and i == 0) else entry["payload_sha256"]
        lines.append(f"C:\\run\\records\\{name},{entry['sha256']},{payload}")
    lines.append("C:\\run\\controls_report.json," + "e" * 64 + ",")
    path = tmp_path / f"walk_{int(alter)}.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, _sha(path)


def _run_equivalence(tmp_path, world, *, records, runner, walk, minute, **kw):
    cfg = world() | {"frozen_records_lists": [[str(walk[0]), walk[1]]],
                     "frozen_new_nbm_rows_sha256": hashlib.sha256(b"").hexdigest()}  # the world's empty new rows
    cfg = cfg | kw.pop("cfg_extra", {})
    for key in kw.pop("cfg_drop", ()):
        cfg.pop(key)
    result = yr.equivalence(cfg, records_root=world.root(records), frozen_runner=runner[0], frozen_runner_sha=runner[1],
                            now=datetime(2026, 11, 3, 12, minute, tzinfo=timezone.utc), **kw)
    report = json.loads((Path(result["out_dir"]) / yr.EQUIVALENCE_REPORT).read_text(encoding="utf-8"))
    assert result["equivalence_report_sha256"] == _sha(Path(result["out_dir"]) / yr.EQUIVALENCE_REPORT)
    return result, report


def test_equivalence_passes_on_identical_inputs_and_holds_no_value(world, tmp_path):
    walk = _frozen_list(tmp_path, world)
    result, report = _run_equivalence(tmp_path, world, records="rec_ok", runner=_runner(tmp_path), walk=walk,
                                      minute=1)
    assert result["status"] == "PASS", report["failed_checks"]
    assert report["records"]["compared"] == len(MARKETS) * len(CENTRES) and report["records"]["differ"] == 0
    assert report["forward"]["state_sha_equal"] and report["forward"]["round_trip_sha_equal"]
    assert {(e["arm"], e["fold"]) for e in report["row_sets"]} == {("A", 2023), ("B", 2023), ("B", 2026)}
    assert all(c["rows"] > 0 and c["max_abs_serve"] <= 1e-12 for c in report["fits"])
    assert report["mode"] == "state_sha" and report["new_nbm_rows"]["equal_to_frozen"]
    assert report["records"]["built_not_listed"] == 0 and report["records"]["frozen_not_built"] == 0
    assert all(c["coverage_complete"] and c["trainer_compared"] == c["expected_rows"] > 0
               and c["serve_compared"] == c["expected_serve"] > 0 for c in report["fits"])
    assert report["forward"]["coverage_complete"] and report["forward"]["serve_compared"] > 0
    grid = report["training_source_checks"]["calendar_grid"]
    holes_file = Path(grid["holes_file"])
    assert holes_file.name == yr.TRAINING_GRID_HOLES_FILE and _sha(holes_file) == grid["holes_file_sha256"]
    assert json.loads(holes_file.read_text(encoding="utf-8"))["holes"] == grid["holes"]

    def walk_values(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not re.search(r"brier|log_loss|label|price|^y$|final_bucket", str(k), re.I), path + "/" + k
                walk_values(v, path + "/" + str(k))
        elif isinstance(obj, list):
            for v in obj:
                walk_values(v, path)

    walk_values(report)
    with pytest.raises(yr.YearroundRefused, match="NEW records root"):
        _run_equivalence(tmp_path, world, records="rec_ok", runner=_runner(tmp_path), walk=walk, minute=2)


def test_equivalence_fails_on_a_record_a_row_key_or_a_fit_change(world, tmp_path):
    _, report = _run_equivalence(tmp_path, world, records="rec_rb", runner=_runner(tmp_path),
                                 walk=_frozen_list(tmp_path, world, alter=True), minute=3)
    assert report["status"] == "FAIL" and report["records"]["differ"] == 1
    walk = _frozen_list(tmp_path, world)
    _, report = _run_equivalence(tmp_path, world, records="rec_rk", runner=_runner(tmp_path, drop=True), walk=walk,
                                 minute=4)
    assert report["status"] == "FAIL" and not any(e["ordered_keys_equal"] for e in report["row_sets"])

    def other_fit(prm_, train):  # a changed fit: the standardised errors scaled by 1 + 1e-6
        out = yr.fit_hour(prm_, train)
        out["fit"]["z"] = out["fit"]["z"] * (1 + 1e-6)
        return out

    _, report = _run_equivalence(tmp_path, world, records="rec_seed", runner=_runner(tmp_path), walk=walk,
                                 minute=5, fit=other_fit)
    assert report["status"] == "FAIL" and report["records"]["pass"]
    assert all(e["pass"] for e in report["row_sets"]) and not report["forward"]["state_sha_equal"]
    assert any(c["max_abs_dist"] > 1e-12 for c in report["fits"])


def test_frame_compare_treats_missing_strings_as_equal_and_finds_a_change():
    a = pd.DataFrame({"k": [2, 1], "c": pd.array(["07", None], dtype="string"), "v": [1.0, float("nan")]})
    b = pd.DataFrame({"k": [1, 2], "c": pd.array([None, "07"], dtype="string"), "v": [float("nan"), 1.0]})
    assert yr.frame_compare(a, b, ["k"], 0.0)["pass"]
    assert not yr.frame_compare(a, b.assign(c=pd.array([None, "01"], dtype="string")), ["k"], 0.0)["pass"]
    assert not yr.frame_compare(a, b.assign(v=[1.0, 1.0]), ["k"], 0.0)["pass"]
    assert not yr.frame_compare(a, b.assign(k=[1, 3]), ["k"], 0.0)["identical_keys"]


def test_frame_compare_missing_on_one_side_only_is_a_diff():
    """Master review 2026-11-03 (deviation 5): missing equals missing only at the same position."""
    a = pd.DataFrame({"k": [1, 2], "c": pd.array([None, "07"], dtype="string"), "v": [float("nan"), 1.0]})
    for col, other in (("c", pd.array(["07", "07"], dtype="string")), ("c", pd.array(["07", None], dtype="string")),
                       ("v", [1.0, 1.0]), ("v", [1.0, float("nan")])):
        result = yr.frame_compare(a, a.assign(**{col: other}), ["k"], 1e9)
        assert not result["pass"] and result["max_abs_diff"][col] == float("inf"), (col, other)
    assert yr.frame_compare(a, a.copy(), ["k"], 0.0)["pass"]


def test_records_root_is_a_required_cli_argument_never_a_config_key(world):
    with pytest.raises(yr.YearroundRefused, match="--records-root"):
        yr.fit(world() | {"records_root": world.root(), "frozen_records_lists": [["x", "0" * 64]]}, arm="B",
               now=datetime(2026, 11, 3, tzinfo=timezone.utc), records_root=world.root())
    with pytest.raises(yr.YearroundRefused, match="--records-root is required"):
        yr.records_root_arg("", world())
    subparsers = next(a for a in yr._parser()._actions if a.dest == "command")
    for command in ("fit", "equivalence"):
        action = next(a for a in subparsers.choices[command]._actions if "--records-root" in a.option_strings)
        assert action.required and action.default is None, command


def test_the_private_replay_index_source_is_pinned(monkeypatch):
    """Master review 2026-11-03 (deviation 2): any change to mg2_p3d_n._replay_index fails loudly."""
    from weather.calibration import mg2_p3d_n as p3

    assert yr.replay_index_source_sha256(p3) == yr.REPLAY_INDEX_SOURCE_SHA256
    monkeypatch.setattr(yr, "REPLAY_INDEX_SOURCE_SHA256", "0" * 64)
    with pytest.raises(yr.YearroundRefused, match="_replay_index"):
        yr._modules()


def test_per_row_mode_reads_only_a_label_free_extract(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("fold,hour,market,date,A_yhat\n2023,13,atlanta,2023-01-05,61.5\n", encoding="utf-8")
    assert yr.read_frozen_rows(path, _sha(path))[0]["A_yhat"] == "61.5"
    path.write_text("fold,hour,market,date,A_yhat,A,y\n2023,13,atlanta,2023-01-05,61.5,0.1,60\n", encoding="utf-8")
    with pytest.raises(yr.YearroundRefused, match="label-free"):
        yr.read_frozen_rows(path, _sha(path))


# ----------------------------------------------------------------------------- isolation and no label reader

def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{a.name}" for a in node.names)


def test_no_capture_loop_or_product_module_imports_the_module():
    importer = re.compile(r"calibration\.yearround_refit\b|\bimport\s+yearround_refit\b|yearround_refit\s+import\b")
    hits = [str(p.relative_to(ROOT)) for base in ("src", "app") for p in (ROOT / base).rglob("*.py")
            if p != MODULE_FILE and "schema_families" not in p.parts
            and importer.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_module_imports_no_production_label_or_price_module():
    allowed = {"weather.market.market_registry", "weather.market.market_registry.spec_for_id",
               "weather.model.model_constants", "weather.model.model_constants.INTRADAY_CUTOFF_HOURS",
               "weather.sources.forecast_training_corpus",
               "weather.sources.forecast_training_corpus.CorpusVerificationError"}
    names = set(_imports(MODULE_FILE))
    production = {n for n in names if n.startswith(yr._PRODUCTION_PREFIXES)}
    assert production <= allowed, sorted(production - allowed)
    assert not [n for n in names if FORBIDDEN_IMPORT.search(n)]
    assert not {"requests", "urllib", "urllib3", "httpx", "http", "aiohttp", "socket"} & {n.split(".")[0]
                                                                                          for n in names}


def test_runtime_refusal_of_a_production_importer():
    saved = sys.modules.pop("weather.calibration.yearround_refit")
    try:
        for name in ("weather.operations.x", "weather.serving.x", "app.views.x"):
            with pytest.raises(ImportError, match="research-only"):
                exec("import weather.calibration.yearround_refit", {"__name__": name})
    finally:
        sys.modules["weather.calibration.yearround_refit"] = saved


def test_sentinel_no_label_or_price_reader_is_imported_on_fit_or_emit(b_state, world, tmp_path, monkeypatch):
    seen = []
    real = builtins.__import__

    def spy(name, globals=None, locals=None, fromlist=(), level=0):
        seen.append(name)
        seen.extend(f"{name}.{f}" for f in (fromlist or ()))
        return real(name, globals, locals, fromlist, level)

    tz = ZoneInfo("America/New_York")
    day = date(2026, 12, 21)
    snaps = _replay_world(tmp_path / "replay", [day], tz)
    monkeypatch.setattr(builtins, "__import__", spy)
    mods, frame, payload_buckets, _ = _frame(world, tmp_path)
    yr.arm_state(mods, frame, payload_buckets, "B", 2026, hours=(13,), provenance={"candidate": yr.CANDIDATE_ID})
    rows, _, _ = yr.shadow_rows(b_state, snaps, tmp_path / "replay", day, day, ["atlanta"])
    monkeypatch.setattr(builtins, "__import__", real)
    assert rows and seen
    assert [n for n in seen if FORBIDDEN_IMPORT.search(n)] == []


def test_cli_has_no_live_path():
    for flag in ("--live", "--execute", "--place", "--cancel", "--promote=1"):
        with pytest.raises(SystemExit, match="no live"):
            yr.main(["emit", flag])


# ----------------------------------------------------------------------------- review fixes (master 2026-11-03)

def test_equivalence_fails_without_the_frozen_new_nbm_sha_or_when_coverage_is_incomplete(world, tmp_path,
                                                                                          monkeypatch):
    walk = _frozen_list(tmp_path, world)
    _, report = _run_equivalence(tmp_path, world, records="rec_nn", runner=_runner(tmp_path), walk=walk, minute=6,
                                 cfg_drop=("frozen_new_nbm_rows_sha256",))
    assert report["status"] == "FAIL" and report["failed_checks"] == ["new_nbm_rows"]
    monkeypatch.setattr(yr, "synthetic_serve_rows", lambda **kw: [])  # nothing compared may never pass
    _, report = _run_equivalence(tmp_path, world, records="rec_zero", runner=_runner(tmp_path), walk=walk, minute=7)
    assert report["status"] == "FAIL" and report["failed_checks"] == ["forward"]
    assert not report["forward"]["coverage_complete"] and report["forward"]["expected_rows"] == 0


def test_per_row_mode_fails_unless_every_row_is_compared(world, tmp_path):
    rows = tmp_path / "rows.csv"
    rows.write_text("fold,hour,market,date,A_yhat\n", encoding="utf-8")
    _, report = _run_equivalence(tmp_path, world, records="rec_pr", runner=_runner(tmp_path),
                                 walk=_frozen_list(tmp_path, world), minute=8, mode="per_row", frozen_rows=rows,
                                 frozen_rows_sha=_sha(rows))
    assert report["status"] == "FAIL" and report["mode"] == "per_row"
    assert all(c["per_row_compared"] == 0 < c["rows"] and not c["pass"] for c in report["fits"])


def test_frozen_lists_union_refuses_overlap_duplicates_and_a_wrong_count(tmp_path):
    def write(name, records):
        path = tmp_path / name
        path.write_text("path,sha256,payload_sha256\n" + "".join(
            f"C:\\r\\records_{m}_{c}.pkl.gz,{'1' * 64},{'2' * 64}\n" for m, c in records)
            + f"C:\\r\\walk.json,{'3' * 64},\n", encoding="utf-8")
        return [str(path), _sha(path)]

    a = write("a.csv", [("atlanta", "2026-01-08"), ("denver", "2026-01-08")])
    b = write("b.csv", [("atlanta", "2026-02-22")])
    assert len(yr.frozen_records_lists([a, b], expected=3)) == 3
    with pytest.raises(yr.YearroundRefused, match="expected 4"):
        yr.frozen_records_lists([a, b], expected=4)
    with pytest.raises(yr.YearroundRefused, match="overlap"):
        yr.frozen_records_lists([a, write("c.csv", [("denver", "2026-01-08")])])
    with pytest.raises(yr.YearroundRefused, match="twice"):
        yr.frozen_records_lists([write("d.csv", [("atlanta", "2026-01-08")] * 2)])
    with pytest.raises(yr.YearroundRefused, match="pinned sha256"):
        yr.frozen_records_lists([[a[0], "abc"]])
    with pytest.raises(yr.YearroundRefused, match="no frozen"):
        yr.frozen_records_lists([])


def test_build_records_refuses_fail_closed_extracts_and_skipped_centres(world, tmp_path, monkeypatch):
    from weather.sources.forecast_training_corpus import CorpusVerificationError

    real = prm.extract_market

    def flaky(market, centre, manifests, out_root, training_years=None):
        if (market, centre) == ("denver", "2026-02-22"):
            raise CorpusVerificationError("synthetic fail-closed extract")
        return real(market, centre, manifests, out_root, training_years=training_years)

    monkeypatch.setattr(prm, "extract_market", flaky)
    with pytest.raises(yr.YearroundRefused, match="failed closed or were skipped: denver 2026-02-22"):
        yr.build_records(world(), yr._modules().prm, world.root("rec_fc"))
    with pytest.raises(yr.YearroundRefused, match="failed closed"):  # the evidence manifest refuses on reuse too
        yr.build_records(world(), yr._modules().prm, world.root("rec_fc"))
    monkeypatch.setattr(prm, "extract_market", real)
    monkeypatch.setattr(prm, "covered_years", lambda centre, manifests: [] if centre == "2026-05-23" else list(YEARS))
    with pytest.raises(yr.YearroundRefused, match="no covered year"):
        yr.build_records(world(), yr._modules().prm, world.root("rec_nc"))


def test_a_reused_records_root_needs_this_module_sha_the_full_set_and_the_frozen_lists(world, tmp_path):
    mods = yr._modules()
    walk = _frozen_list(tmp_path, world)  # builds records_frozen
    with pytest.raises(yr.YearroundRefused, match="frozen records lists"):
        yr.build_records(world(), mods.prm, world.root("records_frozen"))
    cfg = world() | {"frozen_records_lists": [[str(walk[0]), walk[1]]]}
    files, _ = yr.build_records(cfg, mods.prm, world.root("records_frozen"))
    assert len(files) == len(MARKETS) * len(CENTRES)
    altered = _frozen_list(tmp_path, world, alter=True)
    with pytest.raises(yr.YearroundRefused, match="differ from the frozen"):
        yr.build_records(world() | {"frozen_records_lists": [[str(altered[0]), altered[1]]]}, mods.prm,
                         world.root("records_frozen"))
    manifest_path = tmp_path / "records_frozen" / yr.RECORDS_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(manifest | {"module_source_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(yr.YearroundRefused, match="different module source"):
        yr.build_records(cfg, mods.prm, world.root("records_frozen"))


def test_records_root_refuses_a_checkout_data_folder_and_any_reparse_point(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(yr.YearroundRefused, match="checkout's data"):
        yr.check_records_root(checkout / "data" / "training" / "records")
    assert yr.check_records_root(tmp_path / "plain" / "records") == (tmp_path / "plain" / "records").resolve()
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(yr.YearroundRefused, match="reparse point"):
            yr.check_records_root(link / "records")
        with pytest.raises(yr.YearroundRefused, match="reparse point"):
            yr.records_root_arg(str(link / "records"), {})
    finally:
        os.rmdir(link) if os.name == "nt" else link.unlink()  # the link itself, never its target
    assert target.is_dir()


def test_read_snapshots_refuses_by_row_group_statistics_and_filters_the_batch(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    tz = ZoneInfo("America/New_York")
    snaps = _replay_world(tmp_path / "replay", [date(2026, 12, 21), date(2026, 12, 22)], tz)
    path = tmp_path / "snaps.parquet"
    pq.write_table(pa.Table.from_pandas(snaps, preserve_index=False), path, row_group_size=4)
    assert pq.ParquetFile(path).metadata.num_row_groups == 2
    assert len(yr.read_snapshots(path, "2026-12-21", "2026-12-22")) == len(snaps)
    with pytest.raises(yr.YearroundRefused, match="row group 1 lies outside the batch"):
        yr.read_snapshots(path, "2026-12-21", "2026-12-21")
    pq.write_table(pa.Table.from_pandas(snaps, preserve_index=False), path, write_statistics=False)
    with pytest.raises(yr.YearroundRefused, match="no target_date statistics"):
        yr.read_snapshots(path, "2026-12-21", "2026-12-22")


def test_emit_refuses_when_a_serve_helper_source_changed_since_the_fit(b_state, tmp_path, monkeypatch):
    monkeypatch.setattr(yr, "EMIT_MARKETS", ("atlanta",))
    tz = ZoneInfo("America/New_York")
    snaps = _replay_world(tmp_path / "replay", [date(2026, 12, 21)], tz)
    snaps.to_parquet(tmp_path / "snaps.parquet")
    recorded = dict(b_state["provenance"]["helper_source_sha256"])
    assert set(recorded) == {f"{m}.{n}" for m, n in yr.SERVE_HELPERS} and len(recorded) == 7
    stale = dict(b_state, provenance=dict(b_state["provenance"], helper_source_sha256=recorded
                                          | {"weather.calibration.mg2_p3d_n.serve_distribution": "0" * 64}))
    out, sha, msha, rsha = _emit_inputs(tmp_path, stale)
    kw = dict(state_path=out / p3.STATE_FILE, state_sha=sha, fit_manifest=out / yr.FIT_MANIFEST,
              fit_manifest_sha=msha, forward_receipt=tmp_path / "receipt.json", forward_receipt_sha=rsha,
              snapshots=tmp_path / "snaps.parquet", replay_root=tmp_path / "replay", first="2026-12-21",
              last="2026-12-21", today=date(2026, 12, 28))
    with pytest.raises(yr.YearroundRefused, match="serve_distribution"):
        yr.emit(**kw)
    with pytest.raises(yr.YearroundRefused, match="no complete helper_source_sha256"):
        yr.refuse_changed_helpers(None)
    yr.refuse_changed_helpers(yr.helper_source_shas())


def test_fit_refuses_by_name_a_training_source_absent_for_a_market_date():
    nan = float("nan")
    rows = [{"market": m, "target_date": d, "hour": 13, "F": 60.0, "x_high_so_far": 60.0, "x_current_temp": 58.0,
             "fh": 62.0, "nbm_cycle": "07"} for m in ("atlanta", "denver") for d in ("2023-01-05", "2023-01-06")]
    frame = pd.DataFrame(rows)
    assert yr.refuse_absent_training_sources(frame, "B")["wu_hourly_market_dates"] == 4
    gap = frame.copy()
    wu_cols = ["F", "x_high_so_far", "x_current_temp"]
    gap.loc[(gap.market == "denver") & (gap.target_date == "2023-01-06"), wu_cols] = nan
    with pytest.raises(yr.SourceAbsent, match="'wu_hourly' is absent or empty for 1 .*denver 2023-01-06 13"):
        yr.refuse_absent_training_sources(gap, "B")
    no_nbm = frame.copy()
    no_nbm.loc[no_nbm.target_date == "2023-01-05", "nbm_cycle"] = None
    with pytest.raises(yr.SourceAbsent, match="'nbm' is absent or empty .*all markets 2023-01-05"):
        yr.refuse_absent_training_sources(no_nbm, "B")
    one_market = frame.copy()
    one_market.loc[(one_market.market == "atlanta") & (one_market.target_date == "2023-01-05"), "nbm_cycle"] = None
    yr.refuse_absent_training_sources(one_market, "B")  # a per-market NBM gap stays the capped 3.3b imputation
    with pytest.raises(yr.SourceAbsent, match="'nbm' column 'nbm_cycle' is absent"):
        yr.refuse_absent_training_sources(frame.drop(columns=["nbm_cycle"]), "B")


def test_emit_refuses_by_name_a_captured_source_absent_for_a_market_date(tmp_path):
    snaps = pd.DataFrame({"market": ["atlanta", "atlanta"], "target_date": ["2026-12-21", "2026-12-22"]})
    full = {("atlanta", "2026-12-21"): {"gated": 2, "nbm": 2, "replay_folder": True, "observation": 2},
            ("atlanta", "2026-12-22"): {"gated": 1, "nbm": 1, "replay_folder": True, "observation": 1}}
    first, last = date(2026, 12, 21), date(2026, 12, 22)
    assert yr.refuse_absent_emit_sources(snaps, full, first, last, ["atlanta"])["market_dates"] == 2
    with pytest.raises(yr.SourceAbsent, match="'captured_snapshots' .*denver 2026-12-21"):
        yr.refuse_absent_emit_sources(snaps, full, first, last, ["atlanta", "denver"])
    cases = (("replay_folder", False, "captured_metar_replay"), ("nbm", 0, "captured_nbm"),
             ("observation", 0, "captured_metar_replay"))
    for field, value, source in cases:
        broken = dict(full)
        broken[("atlanta", "2026-12-22")] = dict(full[("atlanta", "2026-12-22")], **{field: value})
        with pytest.raises(yr.SourceAbsent, match=f"'{source}' .*atlanta 2026-12-22"):
            yr.refuse_absent_emit_sources(snaps, broken, first, last, ["atlanta"])


# ----------------------------------------------------------------------------- second fix (L16 re-review, 11-03)

def _emit_kw(tmp_path, out, sha, msha, rsha, day="2026-12-21"):
    return dict(state_path=out / p3.STATE_FILE, state_sha=sha, fit_manifest=out / yr.FIT_MANIFEST,
                fit_manifest_sha=msha, forward_receipt=tmp_path / "receipt.json", forward_receipt_sha=rsha,
                snapshots=tmp_path / "snaps.parquet", replay_root=tmp_path / "replay", first=day, last=day,
                today=date(2026, 12, 28))


@pytest.mark.parametrize("what", ["module", "src/weather/calibration/mg2_p3d_n.py",
                                  "src/weather/calibration/r0_ols_floor_devfit.py"])
def test_emit_refuses_a_module_or_pinned_file_changed_since_the_fit(b_state, tmp_path, monkeypatch, what):
    monkeypatch.setattr(yr, "EMIT_MARKETS", ("atlanta",))
    _replay_world(tmp_path / "replay", [date(2026, 12, 21)], ZoneInfo("America/New_York")).to_parquet(
        tmp_path / "snaps.parquet")
    up = yr.upstream_shas()
    extra = ({"module_source_sha256": "0" * 64} if what == "module"
             else {"upstream_sha256": up | {what: "0" * 64}})
    out, sha, msha, rsha = _emit_inputs(tmp_path, b_state, extra)

    def never(*a, **k):
        raise AssertionError("load_state ran before the whole-file pin refusal")

    monkeypatch.setattr(p3, "load_state", never)  # the pin refuses before any state is unpickled
    name = yr.MODULE if what == "module" else what
    with pytest.raises(yr.YearroundRefused, match=re.escape(name)):
        yr.emit(**_emit_kw(tmp_path, out, sha, msha, rsha))
    assert not (out / "shadow").exists()  # refused before any write


def test_fit_requires_the_frozen_lists_and_refuses_the_legacy_keys_by_name(world, tmp_path):
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(yr.YearroundRefused, match="fit requires frozen_records_lists"):
        yr.fit(world(), arm="B", now=now, records_root=world.root())
    for key in yr.LEGACY_CONFIG_KEYS:
        with pytest.raises(yr.YearroundRefused, match=key):
            yr.fit(world() | {key: "x"}, arm="B", now=now, records_root=world.root("rec_legacy"))
        with pytest.raises(yr.YearroundRefused, match=key):
            yr.equivalence(world() | {key: "x"}, records_root=world.root("rec_legacy"),
                           frozen_runner=tmp_path / "none.py", frozen_runner_sha="0" * 64)


def test_wu_hourly_presence_needs_each_named_column():
    nan = float("nan")
    frame = pd.DataFrame([{"market": "atlanta", "target_date": "2023-01-05", "hour": h, "F": 60.0,
                           "x_high_so_far": 60.0, "x_current_temp": nan, "fh": 62.0, "nbm_cycle": "07"}
                          for h in (13, 14)])
    with pytest.raises(yr.SourceAbsent, match="class nan_feature .* on 2 undeclared \\(market, date, hour\\) of 2: "
                                              "atlanta 2023-01-05 13 \\[x_current_temp\\]"):
        yr.refuse_absent_training_sources(frame, "B")
    frame.loc[frame.hour == 14, "x_current_temp"] = 58.0  # hour grain: hour 13 still lacks the column
    with pytest.raises(yr.SourceAbsent, match="on 1 undeclared \\(market, date, hour\\) of 2: atlanta 2023-01-05 13 "
                                              "\\[x_current_temp\\]$"):
        yr.refuse_absent_training_sources(frame, "B")
    frame = pd.concat([frame, frame.assign(x_current_temp=58.0)], ignore_index=True)  # a finite row at each hour
    out = yr.refuse_absent_training_sources(frame, "B")
    assert out["rows_missing_any_wu_hourly_value"] == 1 and out["wu_hourly_market_date_hours"] == 2
    assert out["wu_hourly_absent"] == 0 and out["wu_hourly_nan_feature"] == 0
    checks = yr.training_source_checks(frame.iloc[[0, 1]], "B", {}, prm)  # mirrored
    assert "class nan_feature" in checks["source_presence"]["refused"]
    assert checks["source_presence"]["wu_hourly_classes"] == {
        "keys": 2, "absent": 0, "absent_names": [], "nan_feature": 1,
        "nan_feature_names": ["atlanta 2023-01-05 13 [x_current_temp]"]}


# ----------------------------------------------------------------------------- amended F3(a) (master 2026-11-04)

def _wu_frame(cells):
    """One row per (market, date, hour) with the three wu_hourly columns finite unless named in ``cells``."""
    nan = float("nan")
    rows = []
    for (m, d, h), bad in cells.items():
        row = {"market": m, "target_date": d, "hour": h, "F": 60.0, "x_high_so_far": 60.0, "x_current_temp": 58.0,
               "fh": 62.0, "nbm_cycle": "07"}
        row.update({c: nan for c in bad})
        rows.append(row)
    return pd.DataFrame(rows)


def _nan_key(market, day, hour, columns):
    return {"market": market, "target_date": day, "hour": hour, "columns": list(columns), "reason": "nan_feature",
            "cause": "src/weather/model/feature_store.py:1233,1258", "ruling": "master 2026-11-04"}


def _declared_v2(tmp_path, nan_keys, name="declared_v2.json", records=None, extra=None):
    body = {"schema": yr.DECLARED_ABSENT_SCHEMA_V2, "records": records or [_rec("denver", "2023-01-15")],
            "nan_feature_keys": nan_keys} | (extra or {})
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return yr.load_declared_absent(path, _sha(path))


def test_amended_f3a_all_nan_still_refuses_as_absent(tmp_path):
    every = ("F", "x_current_temp", "x_high_so_far")
    frame = _wu_frame({("nyc", "2024-03-13", 13): every, ("nyc", "2024-03-13", 14): ()})
    declared = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])])
    for decl in (None, declared):  # a declaration never turns an absent key into a pass
        with pytest.raises(yr.SourceAbsent, match="'wu_hourly' is absent or empty for 1 \\(market, date, hour\\) of 2: "
                                                  "nyc 2024-03-13 13$"):
            yr.refuse_absent_training_sources(frame, "B", declared=decl)
    assert yr.wu_hourly_class_report(frame, "B")["absent_names"] == ["nyc 2024-03-13 13"]


def test_amended_f3a_undeclared_partial_refuses_and_names_the_columns():
    frame = _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",),
                       ("san-francisco", "2022-03-17", 13): ("F", "x_high_so_far")})
    with pytest.raises(yr.SourceAbsent, match="class nan_feature .* on 2 undeclared .* of 2: nyc 2024-03-13 13 "
                                              "\\[x_current_temp\\], san-francisco 2022-03-17 13 \\[F,x_high_so_far\\]"):
        yr.refuse_absent_training_sources(frame, "B")


def test_amended_f3a_declared_exact_match_passes_and_the_rows_are_untouched(tmp_path):
    cells = {("nyc", "2024-03-13", 13): ("x_current_temp",), ("san-francisco", "2022-03-17", 13): ("x_current_temp",),
             ("nyc", "2024-03-13", 14): ()}
    frame = _wu_frame(cells)
    before = frame.copy()
    declared = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"]),
                                       _nan_key("san-francisco", "2022-03-17", 13, ["x_current_temp"])])
    out = yr.refuse_absent_training_sources(frame, "B", declared=declared)
    pd.testing.assert_frame_equal(frame, before)  # refuse-only: nothing filtered, filled or altered
    assert out["wu_hourly_absent"] == 0 and out["wu_hourly_nan_feature"] == 2
    assert out["nan_feature_declared"] == {"keys": 2, "sha256": declared["sha256"], "names": [
        "nyc 2024-03-13 13 [x_current_temp]", "san-francisco 2022-03-17 13 [x_current_temp]"]}


def test_amended_f3a_an_extra_declared_key_refuses(tmp_path):
    frame = _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",), ("nyc", "2024-03-13", 14): ()})
    declared = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"]),
                                       _nan_key("nyc", "2024-03-13", 14, ["x_current_temp"])])
    with pytest.raises(yr.YearroundRefused, match="1 declared nan_feature key\\(s\\) are not nan_feature keys on the "
                                                  "frame: nyc 2024-03-13 14 \\[x_current_temp\\]"):
        yr.refuse_absent_training_sources(frame, "B", declared=declared)


def test_amended_f3a_a_missing_or_mismatched_declared_key_refuses(tmp_path):
    frame = _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",),
                       ("san-francisco", "2022-03-17", 13): ("x_current_temp",)})
    one = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])], "one.json")
    with pytest.raises(yr.SourceAbsent, match="on 1 undeclared .*: san-francisco 2022-03-17 13 \\[x_current_temp\\]$"):
        yr.refuse_absent_training_sources(frame, "B", declared=one)
    wrong = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"]),
                                    _nan_key("san-francisco", "2022-03-17", 13, ["F"])], "wrong.json")
    with pytest.raises(yr.SourceAbsent, match="on 1 undeclared .*: san-francisco 2022-03-17 13 \\[x_current_temp\\]$"):
        yr.refuse_absent_training_sources(frame, "B", declared=wrong)  # the column set is part of the key


def test_declared_absent_v1_loads_with_an_empty_nan_section_and_v2_is_strict(tmp_path):
    v1 = yr.load_declared_absent(*_declared(tmp_path, [_rec("denver", "2023-01-15")]))
    assert v1["nan_feature_keys"] == set() and v1["records"] == {("denver", "2023-01-15")}
    frame = _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",)})
    with pytest.raises(yr.SourceAbsent, match="class nan_feature"):
        yr.refuse_absent_training_sources(frame, "B", declared=v1)  # a v1 file declares no nan_feature key
    path = tmp_path / "v1_extra.json"
    path.write_text(json.dumps({"schema": yr.DECLARED_ABSENT_SCHEMA, "records": [_rec("denver", "2023-01-15")],
                                "nan_feature_keys": [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])]}),
                    encoding="utf-8")
    with pytest.raises(yr.YearroundRefused, match="holds only schema and records"):
        yr.load_declared_absent(path, _sha(path))
    good = _nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])
    for i, (bad, match) in enumerate([
            ([], "non-empty nan_feature_keys"),
            ([good, dict(good, columns=["F"])], "twice"),
            ([dict(good, reason="source_absent_final")], "nan_feature"),
            ([dict(good, market="toronto")], "training market"),
            ([dict(good, cause="")], "cause cite"),
            ([dict(good, hour=12)], "hour must be"),
            ([dict(good, hour="13")], "hour must be"),
            ([dict(good, columns=[])], "proper subset"),
            ([dict(good, columns=["x_current_temp", "F"])], "sorted"),
            ([dict(good, columns=["F", "x_current_temp", "x_high_so_far"])], "proper subset"),
            ([dict(good, columns=["fh"])], "proper subset"),
            ([dict(good, value=1)], "keys")]):
        with pytest.raises(yr.YearroundRefused, match=match):
            _declared_v2(tmp_path, bad, f"bad_v2_{i}.json")
    with pytest.raises(yr.YearroundRefused, match="needs exactly schema, records"):
        _declared_v2(tmp_path, [good], "extra_top.json", extra={"note": "x"})
    v2 = _declared_v2(tmp_path, [good], "ok.json")
    assert v2["nan_feature_keys"] == {(("nyc", "2024-03-13", 13), ("x_current_temp",))}
    assert v2["records"] == {("denver", "2023-01-15")}  # the grid-hole section is unchanged
    assert v1["nbm_absent_dates"] == set() and v2["nbm_absent_dates"] == set()  # /1 and /2 declare no NBM date


# ----------------------------------------------------------------------- NBM date presence (master 2026-11-05)

def _nbm_frame(missing):
    """Two markets x two dates x hours 13-14; ``missing`` names (market, date) with no NBM cycle (pre-imputation).
    ``fh`` stays finite everywhere, as ``attach_training_nbm`` leaves it after the forecast_high fill."""
    rows = []
    for m in ("atlanta", "denver"):
        for d in ("2022-01-05", "2022-01-06"):
            for h in (13, 14):
                rows.append({"market": m, "target_date": d, "hour": h, "F": 60.0, "x_high_so_far": 60.0,
                             "x_current_temp": 58.0, "fh": 62.0,
                             "nbm_cycle": None if (m, d) in missing else "07"})
    return pd.DataFrame(rows)


def _nbm_date(day):
    return {"target_date": day, "reason": "nbm_all_market_absent", "cause": "no NBM cycle at the cutoff, any market",
            "ruling": "master 2026-11-05"}


def _declared_v3(tmp_path, dates, name="declared_v3.json", nan_keys=None, extra=None):
    body = {"schema": yr.DECLARED_ABSENT_SCHEMA_V3, "records": [_rec("denver", "2023-01-15")],
            "nan_feature_keys": nan_keys or [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])],
            "nbm_absent_dates": dates} | (extra or {})
    path = tmp_path / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return yr.load_declared_absent(path, _sha(path))


def test_nbm_undeclared_all_market_gap_refuses_on_the_pre_imputation_column(tmp_path):
    gap = _nbm_frame({("atlanta", "2022-01-06"), ("denver", "2022-01-06")})
    v2 = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])])
    frame = pd.concat([gap, _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",)})], ignore_index=True)
    # fh is finite on every row: only the pre-imputation nbm_cycle shows the gap
    with pytest.raises(yr.SourceAbsent, match="'nbm' is absent or empty for 1 dates .* of 2: all markets 2022-01-06$"):
        yr.refuse_absent_training_sources(gap, "B")
    with pytest.raises(yr.SourceAbsent, match="'nbm' is absent or empty for 1 dates .* of 3: all markets 2022-01-06$"):
        yr.refuse_absent_training_sources(frame, "B", declared=v2)  # a /2 file declares no NBM date
    assert yr.nbm_class_report(frame, "B") == {"dates": 3, "absent_dates": 1, "absent_date_names": ["2022-01-06"]}


def test_nbm_declared_exact_match_passes_and_the_rows_are_untouched(tmp_path):
    frame = pd.concat([_nbm_frame({("atlanta", "2022-01-06"), ("denver", "2022-01-06")}),
                       _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",)})], ignore_index=True)
    before = frame.copy()
    declared = _declared_v3(tmp_path, [_nbm_date("2022-01-06")])
    assert declared["nbm_absent_dates"] == {"2022-01-06"}
    out = yr.refuse_absent_training_sources(frame, "B", declared=declared)
    pd.testing.assert_frame_equal(frame, before)  # refuse-only: the forecast_high fill is the treatment, unchanged
    assert out["nbm_dates"] == 3 and out["nbm_absent_dates"] == 1
    assert out["nbm_absent_declared"] == {"dates": 1, "sha256": declared["sha256"], "names": ["2022-01-06"]}


def test_nbm_an_extra_or_missing_declared_date_refuses(tmp_path):
    base = _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",)})
    gap = pd.concat([_nbm_frame({("atlanta", "2022-01-06"), ("denver", "2022-01-06")}), base], ignore_index=True)
    extra = _declared_v3(tmp_path, [_nbm_date("2022-01-06"), _nbm_date("2022-01-05")], "extra.json")
    with pytest.raises(yr.YearroundRefused, match="1 declared nbm_absent date\\(s\\) are not all-market NBM gaps on "
                                                  "the frame: 2022-01-05$"):
        yr.refuse_absent_training_sources(gap, "B", declared=extra)
    clean = pd.concat([_nbm_frame(set()), base], ignore_index=True)
    one = _declared_v3(tmp_path, [_nbm_date("2022-01-06")], "one.json")
    with pytest.raises(yr.YearroundRefused, match="declared nbm_absent date\\(s\\) .*: 2022-01-06$"):
        yr.refuse_absent_training_sources(clean, "B", declared=one)  # declared but present: extra
    two = pd.concat([_nbm_frame({("atlanta", "2022-01-05"), ("denver", "2022-01-05"), ("atlanta", "2022-01-06"),
                                 ("denver", "2022-01-06")}), base], ignore_index=True)
    with pytest.raises(yr.SourceAbsent, match="'nbm' is absent or empty for 1 dates .*: all markets 2022-01-05$"):
        yr.refuse_absent_training_sources(two, "B", declared=one)  # a gap date the file does not name: missing


def test_nbm_a_per_market_date_gap_still_imputes_and_does_not_refuse(tmp_path):
    frame = pd.concat([_nbm_frame({("atlanta", "2022-01-06")}),
                       _wu_frame({("nyc", "2024-03-13", 13): ("x_current_temp",)})], ignore_index=True)
    v2 = _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])])
    out = yr.refuse_absent_training_sources(frame, "B", declared=v2)
    assert out["nbm_absent_dates"] == 0 and "nbm_absent_declared" not in out
    imputed = yr.imputation_by_market_month(frame, "B")["by_market_month"]["atlanta|01"]
    assert imputed == {"rows": 4, "imputed": 2, "share": 0.5}  # the capped 3.3b imputation counts it


def test_declared_absent_v3_is_strict(tmp_path):
    good = _nbm_date("2022-01-06")
    for i, (bad, match) in enumerate([
            ([], "non-empty nbm_absent_dates"),
            ([good, good], "twice"),
            ([dict(good, reason="source_absent_final")], "nbm_all_market_absent"),
            ([dict(good, cause=" ")], "cause cite"),
            ([dict(good, ruling="")], "ruling"),
            ([dict(good, market="nyc")], "keys"),
            (["2022-01-06"], "keys")]):
        with pytest.raises(yr.YearroundRefused, match=match):
            _declared_v3(tmp_path, bad, f"bad_v3_{i}.json")
    path = tmp_path / "v3_no_section.json"
    path.write_text(json.dumps({"schema": yr.DECLARED_ABSENT_SCHEMA_V3, "records": [_rec("denver", "2023-01-15")],
                                "nan_feature_keys": [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])]}),
                    encoding="utf-8")
    with pytest.raises(yr.YearroundRefused, match="and nbm_absent_dates"):
        yr.load_declared_absent(path, _sha(path))
    with pytest.raises(yr.YearroundRefused, match="needs exactly schema, records"):
        _declared_v2(tmp_path, [_nan_key("nyc", "2024-03-13", 13, ["x_current_temp"])], "v2_with_nbm.json",
                     extra={"nbm_absent_dates": [good]})  # /2 never carries the NBM section


def test_training_calendar_grid_refuses_a_hole_by_name():
    expected = yr.expected_training_grid(prm, {"2026-01-08": [2023]}, "B", markets=("atlanta", "denver"))
    assert len(expected) == 2 * 15 and ("denver", "2023-01-15") in expected
    rows = [{"market": m, "target_date": d, "hour": 13} for m, d in sorted(expected)]
    frame = pd.DataFrame(rows)
    assert yr.refuse_training_grid_holes(frame, expected)["holes"] == 0
    with pytest.raises(yr.SourceAbsent, match="'training_calendar_grid' .*1 .*denver 2023-01-15"):
        yr.refuse_training_grid_holes(frame[(frame.market != "denver") | (frame.target_date != "2023-01-15")],
                                      expected)
    other_hour = frame.assign(hour=frame.hour.where(frame.target_date != "2023-01-01", 7))
    with pytest.raises(yr.SourceAbsent, match="training_calendar_grid"):
        yr.refuse_training_grid_holes(other_hour, expected)  # only scored-hour rows count
    july = yr.expected_training_grid(prm, {"2026-07-10": [2023]}, "B", markets=("atlanta",))
    assert july == set()  # B's grid is Dec 17 - May 31 only


def test_imputation_counts_per_market_month_are_reported_not_refused():
    frame = pd.DataFrame([{"market": m, "target_date": f"2023-01-0{d}", "hour": 13,
                           "nbm_cycle": None if (m, d) == ("atlanta", 1) else "07"}
                          for m in ("atlanta", "denver") for d in range(1, 5)])
    out = yr.imputation_by_market_month(frame, "B")
    assert out["by_market_month"]["atlanta|01"] == {"rows": 4, "imputed": 1, "share": 0.25}
    assert out["max_share"] == 0.25 and out["over_cap"] == ["atlanta|01"]
    assert yr.imputation_shares(frame, "B")["01"]["share"] == 0.125  # the pooled cap is the refusing rule


def test_emit_holes_are_named_records_per_state_hour_with_a_reason():
    hp = {("atlanta", "2026-12-21", 13): {"gated": 1, "emitted": 1},
          ("atlanta", "2026-12-21", 14): {"gated": 2, "emitted": 0}}
    holes = yr.emit_holes(hp, date(2026, 12, 21), date(2026, 12, 22), ["atlanta"], {13: {}, 14: {}})
    assert holes == [
        {"market": "atlanta", "target_date": "2026-12-21", "hour": 14, "rows": 0, "reason": "gated_but_not_served"},
        {"market": "atlanta", "target_date": "2026-12-22", "hour": 13, "rows": 0,
         "reason": "no_gated_snapshot_at_hour"},
        {"market": "atlanta", "target_date": "2026-12-22", "hour": 14, "rows": 0,
         "reason": "no_gated_snapshot_at_hour"}]
    assert yr.emit_holes(hp, date(2026, 12, 21), date(2026, 12, 21), ["atlanta"], {13: {}}) == []


def test_compare_records_fails_on_either_side_missing():
    built = {"records_a_2026-01-08.pkl.gz": "1", "records_b_2026-01-08.pkl.gz": "2"}
    extra = yr.compare_records(built, {"records_a_2026-01-08.pkl.gz": "1"})
    assert not extra["pass"] and extra["built_not_listed"] == 1 and extra["frozen_not_built"] == 0
    short = yr.compare_records({"records_a_2026-01-08.pkl.gz": "1"}, built)
    assert not short["pass"] and short["frozen_not_built"] == 1 and short["built_not_listed"] == 0
    assert yr.compare_records(built, dict(built))["pass"] and not yr.compare_records({}, {})["pass"]


def test_state_sha_mode_fails_without_a_forward_compare(world, tmp_path, monkeypatch):
    monkeypatch.setattr(yr, "ARMS", ("A",))  # no B arm, so no forward fold is compared
    _, report = _run_equivalence(tmp_path, world, records="rec_nofw", runner=_runner(tmp_path),
                                 walk=_frozen_list(tmp_path, world), minute=9)
    assert report["status"] == "FAIL" and report["failed_checks"] == ["forward"] and "forward" not in report
    assert report["training_source_checks"]["calendar_grid"]["holes"] == 0


def test_a_none_served_distribution_is_a_mismatch_not_a_crash():
    assert yr._serve_vs(None, {1: 1.0}) == (0.0, True) and yr._serve_vs({1: 1.0}, {1: 1.0}) == (0.0, False)

    class P3:
        @staticmethod
        def serve_distribution(state, **kw):
            return None

    worst, compared, mismatch = yr._forward_trainer_compare(SimpleNamespace(p3=P3, prm=prm), {}, {}, {},
                                                            [{"market": "atlanta"}])
    assert (worst, compared, mismatch) == (0.0, 0, 1)
    assert yr._serve_compare(P3, {}, {}, [{"market": "atlanta"}]) == (0.0, 1, 0)


def test_read_snapshots_refuses_a_timestamp_target_date_by_name(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    snaps = _replay_world(tmp_path / "replay", [date(2026, 12, 21)], ZoneInfo("America/New_York"))
    snaps = snaps.assign(target_date=pd.to_datetime(snaps["target_date"]))
    pq.write_table(pa.Table.from_pandas(snaps, preserve_index=False), tmp_path / "ts.parquet")
    with pytest.raises(yr.YearroundRefused, match="target_date has type timestamp"):
        yr.read_snapshots(tmp_path / "ts.parquet", "2026-12-21", "2026-12-21")


def test_records_root_inside_any_checkout_is_refused(tmp_path):
    checkout = tmp_path / "repo"
    (checkout / ".git").mkdir(parents=True)
    for target in (checkout / "records", checkout / "scratch" / "records", checkout):
        with pytest.raises(yr.YearroundRefused, match="inside a checkout"):
            yr.check_records_root(target)


def test_reuse_refuses_a_stray_file_and_a_short_expected_set(world, tmp_path, monkeypatch):
    mods = yr._modules()
    walk = _frozen_list(tmp_path, world)
    cfg = world() | {"frozen_records_lists": [[str(walk[0]), walk[1]]]}
    stray = tmp_path / "records_frozen" / "records_atlanta_2026-07-25.pkl.gz"
    stray.write_bytes(b"x")
    with pytest.raises(yr.YearroundRefused, match="outside its records manifest"):
        yr.build_records(cfg, mods.prm, world.root("records_frozen"))
    stray.unlink()
    real = yr.record_centres
    monkeypatch.setattr(yr, "record_centres", lambda prm_: real(prm_)[:-1])
    with pytest.raises(yr.YearroundRefused, match="file set differs from the expected"):
        yr.build_records(cfg, mods.prm, world.root("records_frozen"))


# ----------------------------------------------------------------------------- third fix (L16 re-check, 11-03)

def test_a_refused_fit_leaves_a_refused_marker_in_its_dir(world, tmp_path):
    altered = _frozen_list(tmp_path, world, alter=True)
    now = datetime(2026, 11, 3, 12, 30, tzinfo=timezone.utc)
    cfg = world() | {"frozen_records_lists": [[str(altered[0]), altered[1]]]}
    with pytest.raises(yr.YearroundRefused, match="differ from the frozen"):
        yr.fit(cfg, arm="B", now=now, records_root=world.root("rec_refused"))
    fit_dir = tmp_path / "data" / "yearround_refit" / "row28_B" / "20261103T123000Z"
    marker = json.loads((fit_dir / yr.REFUSED_MARKER).read_text(encoding="utf-8"))
    assert marker["refused"] is True and marker["reason"] == "YearroundRefused"
    assert "differ from the frozen" in marker["message"] and marker["refused_utc"].endswith("+00:00")
    assert not (fit_dir / p3.STATE_FILE).exists() and not (fit_dir / yr.FIT_MANIFEST).exists()


def test_equivalence_refuses_missing_frozen_lists_before_writing_anything(world, tmp_path):
    with pytest.raises(yr.YearroundRefused, match="equivalence requires frozen_records_lists"):
        yr.equivalence(world(), records_root=world.root("rec_nolists"), frozen_runner=tmp_path / "none.py",
                       frozen_runner_sha="0" * 64)
    assert not (tmp_path / "data" / "yearround_refit" / "row28_B" / "equivalence").exists()
    assert not (tmp_path / "rec_nolists").exists()


def test_an_empty_training_grid_refuses_by_name():
    frame = pd.DataFrame([{"market": "atlanta", "target_date": "2023-01-05", "hour": 13}])
    for covered in ({}, None, {"2026-01-08": []}):
        grid = yr.expected_training_grid(prm, covered, "B")
        assert grid == set()
        with pytest.raises(yr.SourceAbsent, match="'training_calendar_grid' is empty"):
            yr.refuse_training_grid_holes(frame, grid)


# ----------------------------------------------------------------------------- post-run commit (master 11-04)

def test_shadow_rows_hour_presence_counts_only_the_state_hours(b_state, tmp_path):
    tz = ZoneInfo("America/New_York")
    day = date(2026, 12, 21)
    snaps = _replay_world(tmp_path / "replay", [day], tz)
    presence, hour_presence = {}, {}
    rows, _, _ = yr.shadow_rows(b_state, snaps, tmp_path / "replay", day, day, ["atlanta"], presence=presence,
                                hour_presence=hour_presence)
    assert set(hour_presence) == {("atlanta", "2026-12-21", 13)}  # the state holds hour 13 only
    assert hour_presence[("atlanta", "2026-12-21", 13)] == {"gated": 2, "emitted": len(rows)} and len(rows) == 2
    assert presence[("atlanta", "2026-12-21")]["gated"] == 2
    assert yr.emit_holes(hour_presence, day, day, ["atlanta"], b_state["hours"]) == []


def test_emit_refusals_gate_on_the_state_hours_not_the_intraday_set(b_state, tmp_path):
    # Q1(a): a date whose only gated snapshot is at a non-state hour (14; the state holds 13) and has no replay
    # folder would refuse 'captured_metar_replay' under the 7..20 gate; at the state hours it is a named hole
    tz = ZoneInfo("America/New_York")
    d1, d2 = date(2026, 12, 21), date(2026, 12, 22)
    snaps = pd.concat([_replay_world(tmp_path / "replay", [d1], tz),
                       _snaps([("atlanta|e22", d2, datetime(2026, 12, 22, 14, 10, tzinfo=tz), 14)], tz)],
                      ignore_index=True)
    presence, hour_presence = {}, {}
    yr.shadow_rows(b_state, snaps, tmp_path / "replay", d1, d2, ["atlanta"], presence=presence,
                   hour_presence=hour_presence)
    assert ("atlanta", "2026-12-22") not in presence
    assert yr.refuse_absent_emit_sources(snaps, presence, d1, d2, ["atlanta"])["gated_market_dates"] == 1
    assert yr.emit_holes(hour_presence, d1, d2, ["atlanta"], b_state["hours"]) == [
        {"market": "atlanta", "target_date": "2026-12-22", "hour": 13, "rows": 0,
         "reason": "no_gated_snapshot_at_hour"}]
    presence[("atlanta", "2026-12-21")]["replay_folder"] = False  # still fail-closed AT a state hour
    with pytest.raises(yr.SourceAbsent, match="captured_metar_replay"):
        yr.refuse_absent_emit_sources(snaps, presence, d1, d2, ["atlanta"])


def test_emit_refuses_a_refused_marker_beside_the_manifest_or_state(tmp_path):
    for where in ("fit", "state"):
        fit_dir, state_dir = tmp_path / where / "fit", tmp_path / where / "state"
        fit_dir.mkdir(parents=True)
        state_dir.mkdir()
        ((fit_dir if where == "fit" else state_dir) / yr.REFUSED_MARKER).write_text("{}", encoding="utf-8")
        with pytest.raises(yr.YearroundRefused, match="REFUSED marker"):
            yr.emit(state_path=state_dir / "s.pkl", state_sha="0" * 64, fit_manifest=fit_dir / yr.FIT_MANIFEST,
                    fit_manifest_sha="0" * 64, forward_receipt=tmp_path / "r.json", forward_receipt_sha="0" * 64,
                    snapshots=tmp_path / "s.parquet", replay_root=tmp_path, first="2026-12-21",
                    last="2026-12-21")


def test_a_refused_archive_leaves_no_manifest(world, tmp_path, monkeypatch):
    def refuse(*_a, **_k):
        raise yr.YearroundRefused("archive refused for the test")

    monkeypatch.setattr(yr, "archive_copy", refuse)
    now = datetime(2026, 11, 3, 13, 0, tzinfo=timezone.utc)
    with pytest.raises(yr.YearroundRefused, match="archive refused for the test"):
        yr.fit(_fit_cfg(tmp_path, world), arm="B", now=now, records_root=world.root("rec_archive"))
    fit_dir = tmp_path / "data" / "yearround_refit" / "row28_B" / "20261103T130000Z"
    assert (fit_dir / yr.REFUSED_MARKER).exists() and not (fit_dir / yr.FIT_MANIFEST).exists()


def test_archive_add_is_write_once_and_sha_verified(tmp_path):
    (tmp_path / "fit").mkdir()
    (tmp_path / "arc").mkdir()
    (tmp_path / "fit" / "m.json").write_text("{}", encoding="utf-8")
    assert yr.archive_add(tmp_path / "fit", tmp_path / "arc", "m.json") == _sha(tmp_path / "fit" / "m.json")
    with pytest.raises(yr.YearroundRefused, match="write-once"):
        yr.archive_add(tmp_path / "fit", tmp_path / "arc", "m.json")


def test_a_failed_marker_write_keeps_the_original_refusal(world, tmp_path, monkeypatch):
    altered = _frozen_list(tmp_path, world, alter=True)
    real = yr._write_json

    def failing(path, obj):
        if Path(path).name == yr.REFUSED_MARKER:
            raise OSError("disk full for the test")
        return real(path, obj)

    monkeypatch.setattr(yr, "_write_json", failing)
    now = datetime(2026, 11, 3, 13, 30, tzinfo=timezone.utc)
    cfg = world() | {"frozen_records_lists": [[str(altered[0]), altered[1]]]}
    with pytest.raises(yr.YearroundRefused, match="differ from the frozen") as info:
        yr.fit(cfg, arm="B", now=now, records_root=world.root("rec_marker"))
    assert any("could not be written" in n and "disk full" in n for n in info.value.__notes__)


def test_equivalence_refuses_a_malformed_frozen_list_before_any_directory(world, tmp_path):
    bad = tmp_path / "bad_walk.csv"
    bad.write_text("not,a,walk\n", encoding="utf-8")
    cfg = world() | {"frozen_records_lists": [[str(bad), "0" * 64]]}
    with pytest.raises(yr.YearroundRefused):
        yr.equivalence(cfg, records_root=world.root("rec_badlist"), frozen_runner=tmp_path / "none.py",
                       frozen_runner_sha="0" * 64)
    assert not (tmp_path / "data" / "yearround_refit" / "row28_B" / "equivalence").exists()


def test_grid_hole_names_classifies_by_name_and_flags_the_forward_window():
    holes = [("atlanta", "2022-03-01"), ("atlanta", "2022-03-13"), ("denver", "2024-02-29"),
             ("denver", "2024-03-01"), ("seattle", "2023-04-02")]
    out = yr.grid_hole_names(holes, 100)
    assert out["holes"] == 5 and out["expected_market_dates"] == 100
    assert out["per_market"] == {"atlanta": 2, "denver": 2, "seattle": 1}
    assert out["by_class"]["march_1"]["names"] == ["atlanta 2022-03-01", "denver 2024-03-01"]
    assert out["by_class"]["us_spring_forward_sunday"]["names"] == ["atlanta 2022-03-13"]
    assert out["by_class"]["other"]["names"] == ["denver 2024-02-29", "seattle 2023-04-02"]
    assert out["feb_29_holes"] == ["denver 2024-02-29"] and out["has_2024_02_29"] and out["has_2024_03_01"]
    assert out["in_forward_window"] is False and out["in_forward_window_names"] == []
    edge = yr.grid_hole_names([("nyc", "2023-12-17"), ("nyc", "2024-01-30"), ("nyc", "2024-01-31"),
                               ("nyc", "2023-12-16")], 4)
    assert edge["in_forward_window"] is True
    assert edge["in_forward_window_names"] == ["nyc 2023-12-17", "nyc 2024-01-30"]
    assert all(yr._us_spring_forward(date.fromisoformat(d)) for d in ("2022-03-13", "2023-03-12", "2024-03-10",
                                                                        "2025-03-09", "2021-03-14"))
    assert not yr._us_spring_forward(date(2024, 3, 17)) and not yr._us_spring_forward(date(2024, 3, 3))


def _grid_counts(tmp_path, world):
    mods = yr._modules()
    root = tmp_path / "records_frozen"
    manifest = json.loads((root / yr.RECORDS_MANIFEST).read_text(encoding="utf-8"))
    files = sorted(root / n for n in manifest["files"])
    frame, _ = yr.market_frame(mods.prm, files, with_labels=False)
    frame = frame[frame["target_date"].astype(str).str[:10] <= yr.LAST_TRAIN.isoformat()]
    grid = yr.expected_training_grid(mods.prm, manifest["covered_years"], "B")
    return {"expected_market_dates": len(grid), "holes": len(yr.training_grid_holes(frame, grid))}


def test_grid_holes_writes_one_names_only_file_and_is_write_once(world, tmp_path):
    walk = _frozen_list(tmp_path, world)
    cfg = world() | {"frozen_records_lists": [[str(walk[0]), walk[1]]]}
    want = _grid_counts(tmp_path, world)
    assert want["expected_market_dates"] > 0
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = yr.grid_holes(cfg, records_root=tmp_path / "records_frozen", out=tmp_path / "gh", expected=want)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert set(after) - set(before) == {Path("gh"), Path("gh") / yr.GRID_HOLES_FILE}  # writes only under --out
    path = Path(result["out_file"])
    assert _sha(path) == result["sha256"] and result["holes"] == want["holes"]
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["schema"] == yr.GRID_HOLES_SCHEMA and body["module_source_sha256"] == yr.module_source_sha256()
    assert body["expected_market_dates"] == want["expected_market_dates"]
    assert sum(body["per_market"].values()) == body["holes"] == len(body["names"])
    assert sum(c["count"] for c in body["by_class"].values()) == body["holes"]
    assert set(body["names"][0]) == {"market", "target_date"} if body["names"] else True
    text = path.read_text(encoding="utf-8")
    assert "final_bucket" not in text and '"y"' not in text
    with pytest.raises(yr.YearroundRefused, match="write-once"):
        yr.grid_holes(cfg, records_root=tmp_path / "records_frozen", out=tmp_path / "gh", expected=want)


def test_grid_holes_refuses_a_wrong_count_a_missing_manifest_and_a_checkout_out(world, tmp_path):
    walk = _frozen_list(tmp_path, world)
    cfg = world() | {"frozen_records_lists": [[str(walk[0]), walk[1]]]}
    want = _grid_counts(tmp_path, world)
    wrong = dict(want, holes=want["holes"] + 1)
    with pytest.raises(yr.YearroundRefused, match="self-check"):
        yr.grid_holes(cfg, records_root=tmp_path / "records_frozen", out=tmp_path / "gh_wrong", expected=wrong)
    assert not (tmp_path / "gh_wrong").exists()
    with pytest.raises(yr.YearroundRefused, match="self-check"):  # the default is the accepted 7315 / 81
        yr.grid_holes(cfg, records_root=tmp_path / "records_frozen", out=tmp_path / "gh_default")
    (tmp_path / "empty_root").mkdir()
    with pytest.raises(yr.YearroundRefused, match="existing records root only"):
        yr.grid_holes(cfg, records_root=tmp_path / "empty_root", out=tmp_path / "gh_empty", expected=want)
    assert not any((tmp_path / "empty_root").iterdir())  # nothing is ever built
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(yr.YearroundRefused, match="inside a checkout"):
        yr.grid_holes(cfg, records_root=tmp_path / "records_frozen", out=tmp_path / "repo" / "gh", expected=want)
    with pytest.raises(yr.YearroundRefused, match="frozen_records_lists"):
        yr.grid_holes(world(), records_root=tmp_path / "records_frozen", out=tmp_path / "gh_nolist", expected=want)


def test_grid_holes_cli_exits_4_on_a_forward_window_hole(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    calls = []

    def fake(cfg_obj, *, records_root, out):
        calls.append((records_root, out))
        return {"in_forward_window": len(calls) == 2, "out_file": "x", "sha256": "0" * 64}

    monkeypatch.setattr(yr, "grid_holes", fake)
    argv = ["grid-holes", "--config", str(cfg), "--config-sha", _sha(cfg), "--records-root", "r", "--out", "o"]
    assert yr.main(argv) == 0
    assert yr.main(argv) == 4
    assert calls == [("r", "o"), ("r", "o")]


def test_grid_holes_touches_no_fit_state_or_emit_path():
    import inspect

    src = inspect.getsource(yr.grid_holes) + inspect.getsource(yr.verify_existing_records_root)
    for name in ("fit(", "_fit_in(", "freeze_state(", "write_state", "arm_state(", "emit(", "shadow_rows(",
                 "training_frame(", "build_records(", "_new_dir(", "state_root("):
        assert name not in src, name


def _declared(tmp_path, records, name="declared.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"schema": yr.DECLARED_ABSENT_SCHEMA, "records": records}), encoding="utf-8")
    return path, _sha(path)


def _rec(market, day, cls="other"):
    return {"market": market, "target_date": day, "reason": "source_absent_final", "class": cls,
            "cause": "src/weather/model/model_climatology.py:112", "ruling": "master 2026-11-04"}


def test_declared_absent_grid_holes_are_by_name_and_fail_closed(tmp_path):
    expected = yr.expected_training_grid(prm, {"2026-01-08": [2023]}, "B", markets=("atlanta", "denver"))
    frame = pd.DataFrame([{"market": m, "target_date": d, "hour": 13} for m, d in sorted(expected)
                          if (m, d) not in {("denver", "2023-01-15"), ("atlanta", "2023-01-02")}])
    both = yr.load_declared_absent(*_declared(tmp_path, [_rec("denver", "2023-01-15"), _rec("atlanta", "2023-01-02")]))
    out = yr.refuse_training_grid_holes(frame, expected, declared=both)
    assert out["holes"] == 0 and out["declared_absent"]["records"] == 2
    assert out["declared_absent"]["names"] == ["atlanta 2023-01-02", "denver 2023-01-15"]
    assert out["declared_absent"]["by_class"] == {"other": 2}
    one = yr.load_declared_absent(*_declared(tmp_path, [_rec("denver", "2023-01-15")], "one.json"))
    with pytest.raises(yr.SourceAbsent, match="training_calendar_grid.*atlanta 2023-01-02"):
        yr.refuse_training_grid_holes(frame, expected, declared=one)  # an undeclared hole still refuses
    extra = yr.load_declared_absent(*_declared(tmp_path, [_rec("denver", "2023-01-15"), _rec("atlanta", "2023-01-02"),
                                                          _rec("atlanta", "2023-01-03")], "extra.json"))
    with pytest.raises(yr.YearroundRefused, match="1 declared-absent record.*not grid holes: atlanta 2023-01-03"):
        yr.refuse_training_grid_holes(frame, expected, declared=extra)
    with pytest.raises(yr.SourceAbsent, match="training_calendar_grid"):
        yr.refuse_training_grid_holes(frame, expected)  # no declaration: the hard check as before


def test_declared_absent_records_refuse_a_bad_record_by_name(tmp_path):
    good = _rec("denver", "2023-01-15")
    for i, (bad, match) in enumerate([
            ([good, good], "twice"),
            ([dict(good, reason="missing")], "source_absent_final"),
            ([dict(good, **{"class": "dst"})], "class"),
            ([dict(good, cause=" ")], "no cause"),
            ([dict(good, ruling="")], "no cause cite or ruling"),
            ([dict(good, market="toronto")], "unknown market"),
            ([dict(good, value=1)], "keys"),
            ([], "non-empty")]):
        with pytest.raises(yr.YearroundRefused, match=match):
            yr.load_declared_absent(*_declared(tmp_path, bad, f"bad{i}.json"))
    path, sha = _declared(tmp_path, [good], "pinned.json")
    with pytest.raises(yr.YearroundRefused):
        yr.load_declared_absent(path, "0" * 64)  # the sha pins the file


def test_fit_with_declared_absent_needs_both_flags_and_refuses_before_any_directory(world, tmp_path):
    cfg = _fit_cfg(tmp_path, world)
    now = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)
    path, sha = _declared(tmp_path, [_rec("denver", "2023-01-15")])
    with pytest.raises(yr.YearroundRefused, match="--declare-absent-sha"):
        yr.fit(cfg, arm="B", now=now, records_root=world.root("rec_decl"), declared_absent=path)
    with pytest.raises(yr.YearroundRefused, match="not grid holes"):  # the world has no hole to declare
        yr.fit(cfg, arm="B", now=now, records_root=world.root("rec_decl"), declared_absent=path,
               declared_absent_sha=sha)
    bad, bad_sha = _declared(tmp_path, [dict(_rec("denver", "2023-01-15"), reason="x")], "bad.json")
    later = datetime(2026, 11, 3, 14, 30, tzinfo=timezone.utc)
    with pytest.raises(yr.YearroundRefused, match="source_absent_final"):
        yr.fit(cfg, arm="B", now=later, records_root=world.root("rec_decl2"), declared_absent=bad,
               declared_absent_sha=bad_sha)
    assert not (tmp_path / "data" / "yearround_refit" / "row28_B" / "20261103T143000Z").exists()


def test_declared_absent_never_reaches_the_state():
    import inspect

    src = inspect.getsource(yr._fit_in)
    head, tail = src.split("provenance = {", 1)
    assert "declared" in head and "declared" not in tail.split("}", 1)[0]  # not in the state's provenance


HEADER = "schema_version,local_date,temperature_unit,row_count,first_time,max_temp,max_temp_bucket\n"


def _daily(tmp_path, lines, header=HEADER):
    path = tmp_path / "daily_summary.csv"
    path.write_text(header + "".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def test_wu_daily_presence_refuses_a_header_without_local_date_second(tmp_path):
    path = _daily(tmp_path, ["2022-03-13,2,F,24,00:53,61,61"], header="local_date,schema_version,unit\n")
    with pytest.raises(yr.YearroundRefused, match="header"):
        yr.wu_daily_presence(path, ["2022-03-13"])


def test_wu_daily_presence_stops_at_the_cutoff_and_never_parses_past_it(tmp_path):
    path = _daily(tmp_path, ["2,2022-03-12,F,24,00:53,61,61", "2,2022-03-13,F,19,00:53,62,62",
                             "2,2026-09-30,F,24,00:53,70,70", "not a csv line at all", "2,2020-01-01,F,1,x,1,1"])
    out = yr.wu_daily_presence(path, ["2022-03-13", "2022-03-14"])
    assert out == {"2022-03-13": {"daily_row_present": True, "row_count": 19, "row_count_ge_20": False},
                   "2022-03-14": {"daily_row_present": False, "row_count": None, "row_count_ge_20": False}}
    with pytest.raises(yr.YearroundRefused, match="on or after 2026-09-30"):
        yr.wu_daily_presence(path, ["2026-09-30"])


def test_wu_daily_presence_refuses_descending_date_tokens(tmp_path):
    path = _daily(tmp_path, ["2,2022-03-13,F,24,00:53,61,61", "2,2022-03-12,F,24,00:53,61,61"])
    with pytest.raises(yr.YearroundRefused, match="descend"):
        yr.wu_daily_presence(path, ["2022-03-13"])
    quoted = _daily(tmp_path, ['"2",2022-03-13,F,24,00:53,61,61'])
    with pytest.raises(yr.YearroundRefused, match="schema_version field"):
        yr.wu_daily_presence(quoted, ["2022-03-13"])


def test_wu_daily_presence_never_converts_the_high_or_its_bucket(tmp_path, monkeypatch):
    import inspect

    from weather.sources import daily_summary

    def boom(*_a, **_k):
        raise AssertionError("a high or bucket was converted")

    monkeypatch.setattr(daily_summary, "native_bucket", boom)
    monkeypatch.setattr(daily_summary, "native_high", boom)
    path = _daily(tmp_path, ["2,2023-03-12,F,22,00:53,not-a-number,also-not"])
    out = yr.wu_daily_presence(path, ["2023-03-12"])
    assert out == {"2023-03-12": {"daily_row_present": True, "row_count": 22, "row_count_ge_20": True}}
    src = inspect.getsource(yr.wu_daily_presence) + inspect.getsource(yr._daily_date_token)
    assert "native_bucket(" not in src and "float(" not in src and "max_temp" not in src


def test_wu_hourly_presence_is_a_raw_substring_with_no_parse(tmp_path, monkeypatch):
    month = tmp_path / "hourly" / "year=2023" / "month=03"
    month.mkdir(parents=True)
    (month / "observations.jsonl").write_text(json.dumps({"local_date": "2023-03-11", "temp": 50}, sort_keys=True)
                                              + "\n", encoding="utf-8")

    def no_parse(*_a, **_k):
        raise AssertionError("an hourly line was parsed")

    monkeypatch.setattr(yr.json, "loads", no_parse)
    assert yr.wu_hourly_presence(tmp_path, ["2023-03-11", "2023-03-12", "2024-03-10"]) == {
        "2023-03-11": True, "2023-03-12": False, "2024-03-10": False}
    with pytest.raises(yr.YearroundRefused, match="never opened"):
        yr.wu_hourly_presence(tmp_path, ["2026-01-04"])


def test_wu_store_checks_report_fall_back_sundays_and_never_refuse_on_them(tmp_path, monkeypatch):
    assert [yr.us_fall_back_sunday(y).isoformat() for y in yr.FALL_BACK_YEARS] == [
        "2020-11-01", "2021-11-07", "2022-11-06", "2023-11-05", "2024-11-03", "2025-11-02"]
    roots = {"atlanta": tmp_path / "a", "denver": tmp_path / "d"}
    monkeypatch.setattr(yr, "_wu_market_root", lambda m: roots[m])
    (roots["atlanta"] / "daily").mkdir(parents=True)
    _daily(roots["atlanta"] / "daily", ["2,2022-03-13,F,23,00:53,61,61", "2,2022-11-06,F,25,00:53,61,61"])
    (roots["denver"] / "daily").mkdir(parents=True)
    _daily(roots["denver"] / "daily", ["2,2022-03-13,F,23,x,1,1"], header="bad header\n")
    out = yr.wu_store_checks([("atlanta", "2022-03-13")], ["atlanta", "denver"])
    assert "read time" in out["caveat"]
    assert out["spring_forward_holes"] == [{"market": "atlanta", "target_date": "2022-03-13",
                                            "daily_row_present": True, "row_count": 23, "row_count_ge_20": True,
                                            "hourly_row_present": False}]
    fall = {(e["market"], e["target_date"]): e for e in out["fall_back_sundays_report_only"]}
    assert fall[("atlanta", "2022-11-06")]["row_count"] == 25 and len(fall) == 12
    assert "header" in fall[("denver", "2022-11-06")]["refused"]  # report-only: a refused read never refuses
    with pytest.raises(yr.YearroundRefused, match="header"):
        yr.wu_store_checks([("denver", "2022-03-13")], ["atlanta", "denver"])  # a hole's read refusal refuses


def test_wu_store_checks_report_every_other_hole_class_and_never_refuse_on_them(tmp_path, monkeypatch):
    roots = {"atlanta": tmp_path / "a", "denver": tmp_path / "d"}
    monkeypatch.setattr(yr, "_wu_market_root", lambda m: roots[m])
    (roots["atlanta"] / "daily").mkdir(parents=True)
    _daily(roots["atlanta"] / "daily", ["2,2022-03-01,F,24,00:53,61,61", "2,2022-03-13,F,23,00:53,61,61"])
    (roots["denver"] / "daily").mkdir(parents=True)
    _daily(roots["denver"] / "daily", ["2,2022-01-01,F,1,x,1,1"], header="bad header\n")
    out = yr.wu_store_checks([("atlanta", "2022-03-13")], ["atlanta", "denver"],
                             other_holes=[("atlanta", "2022-03-01", "march_1"), ("atlanta", "2022-03-02", "other"),
                                          ("denver", "2022-01-01", "other")])
    other = {(e["market"], e["target_date"]): e for e in out["other_holes_report_only"]}
    assert other[("atlanta", "2022-03-01")] == {"market": "atlanta", "target_date": "2022-03-01", "class": "march_1",
                                                "daily_row_present": True, "row_count": 24, "row_count_ge_20": True,
                                                "hourly_row_present": False}
    assert other[("atlanta", "2022-03-02")]["daily_row_present"] is False
    assert "header" in other[("denver", "2022-01-01")]["refused"]  # report-only: a refused read never refuses
    assert [e["target_date"] for e in out["spring_forward_holes"]] == ["2022-03-13"]


FIT_PROV = {"candidate": "row28_B", "shadow_only": True, "module": "m", "module_source_sha256": "a" * 64,
            "fit_id": "20261105T000000Z", "arm": "B", "fold": 2026, "upstream_sha256": {"x": "b" * 64},
            "bound_hooks_state_sha256": "c" * 64, "sklearn_version": "1.8.0", "helper_source_sha256": {"h": "d" * 64}}
REF_PROV = {"candidate": "row28_B", "shadow_only": True, "equivalence": True}


def _state_file(tmp_path, name, provenance, payload=None):
    obj = {"schema": "mg2_p3d_n_state/1", "fits": {"13": [1.5, 2.5]}, "markets": ["atlanta"],
           "hours": [13], "provenance": provenance}
    if payload:
        obj.update(payload)
    path = tmp_path / name
    path.write_bytes(pickle.dumps(obj, protocol=4))
    return path, _sha(path)


def _k2(tmp_path, state, ref, out="k2"):
    return yr.k2_compare(state=state[0], state_sha=state[1], reference=ref[0], reference_sha=ref[1],
                         out=tmp_path / out)


def test_k2_compare_passes_on_equal_payloads_with_the_allowed_provenance_diff(tmp_path):
    fit = _state_file(tmp_path, "fit.pkl", dict(FIT_PROV, sklearn_version="VALUE-NEVER-WRITTEN"))
    ref = _state_file(tmp_path, "ref.pkl", REF_PROV)
    result = _k2(tmp_path, fit, ref)
    assert result["pass"] and result["failed_checks"] == []
    assert result["payload_sha256_state"] == result["payload_sha256_reference"]
    path = Path(result["out_file"])
    assert _sha(path) == result["sha256"] and path.parent == tmp_path / "k2"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["provenance_only_in_state"] == sorted(yr.K2_FIT_ONLY_PROVENANCE)
    assert body["provenance_only_in_reference"] == ["equivalence"]
    assert body["provenance_shared"] == ["candidate", "shadow_only"] and body["provenance_shared_differing"] == []
    assert body["module_source_sha256"] == yr.module_source_sha256()
    assert "VALUE-NEVER-WRITTEN" not in path.read_text(encoding="utf-8")  # names and shas only
    with pytest.raises(yr.YearroundRefused, match="write-once"):
        _k2(tmp_path, fit, ref)


@pytest.mark.parametrize("case, failed", [
    ("payload", "payload_sha256"),
    ("extra_fit_key", "provenance_only_in_state"),
    ("missing_fit_key", "provenance_only_in_state"),
    ("no_equivalence", "provenance_only_in_reference"),
    ("candidate_differs", "provenance_shared_differing"),
    ("shadow_differs", "provenance_shared_differing"),
    ("extra_shared", "provenance_shared"),
])
def test_k2_compare_fails_on_any_other_difference(tmp_path, case, failed):
    fit_prov, ref_prov, payload = dict(FIT_PROV), dict(REF_PROV), None
    if case == "payload":
        payload = {"fits": {"13": [1.5, 2.5000000001]}}
    elif case == "extra_fit_key":
        fit_prov["note"] = "x"
    elif case == "missing_fit_key":
        del fit_prov["fit_id"]
    elif case == "no_equivalence":
        del ref_prov["equivalence"]
    elif case == "candidate_differs":
        fit_prov["candidate"] = "row28_A"
    elif case == "shadow_differs":
        ref_prov["shadow_only"] = False
    elif case == "extra_shared":
        fit_prov["extra"] = ref_prov["extra"] = 1
    fit = _state_file(tmp_path, "fit.pkl", fit_prov, payload)
    ref = _state_file(tmp_path, "ref.pkl", ref_prov)
    result = _k2(tmp_path, fit, ref)
    assert result["pass"] is False and failed in result["failed_checks"]


def test_k2_compare_verifies_both_shas_before_unpickling_and_refuses_a_checkout_out(tmp_path, monkeypatch):
    fit = _state_file(tmp_path, "fit.pkl", FIT_PROV)
    ref = _state_file(tmp_path, "ref.pkl", REF_PROV)

    def never(*_a, **_k):
        raise AssertionError("unpickled before both shas were verified")

    monkeypatch.setattr(yr.pickle, "loads", never)
    with pytest.raises(yr.YearroundRefused, match="reference state sha256 differs"):
        _k2(tmp_path, fit, (ref[0], "0" * 64))
    with pytest.raises(yr.YearroundRefused, match="fit state sha256 differs"):
        _k2(tmp_path, (fit[0], "0" * 64), ref)
    monkeypatch.undo()
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(yr.YearroundRefused, match="inside a checkout"):
        _k2(tmp_path, fit, ref, out="repo/k2")
    assert not (tmp_path / "k2").exists()


def test_k2_compare_cli_exits_5_on_a_mismatch(tmp_path, capsys):
    fit = _state_file(tmp_path, "fit.pkl", FIT_PROV)
    ref = _state_file(tmp_path, "ref.pkl", REF_PROV)
    bad = _state_file(tmp_path, "bad.pkl", FIT_PROV, {"hours": [14]})

    def argv(state, out):
        return ["k2-compare", "--state", str(state[0]), "--state-sha", state[1], "--reference", str(ref[0]),
                "--reference-sha", ref[1], "--out", str(tmp_path / out)]

    assert yr.main(argv(fit, "ok")) == 0
    assert yr.main(argv(bad, "bad")) == 5


def test_k2_compare_touches_no_fit_state_writing_or_emit_path():
    import inspect

    src = inspect.getsource(yr.k2_compare)
    for name in ("fit(", "_fit_in(", "freeze_state(", "write_state", "arm_state(", "emit(", "shadow_rows(",
                 "training_frame(", "build_records(", "_new_dir(", "state_root(", "archive_copy("):
        assert name not in src, name
