"""R-ODC-lin / X13 released-cell P0 driver (ledger row 103): guards, fit math, features, D3 and labels.

Synthetic inputs only, except two read-only pins of the run tree (the imported blobs and the rule files) and,
when the archive is present, control C-d on row 80's archived rows. No r80 layout, export, label or price is read.
"""
from __future__ import annotations

import argparse
import ast
import inspect
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from tests.host_guard import import_or_skip_on_capture_host

p0 = import_or_skip_on_capture_host("tools.research.released_window.rodc_released_p0")

NY = ZoneInfo("America/New_York")
NETWORK = {"socket", "urllib", "http", "requests", "ssl", "ftplib", "httpx", "aiohttp", "smtplib"}


# ----------------------------------------------------------------------------- static and guards

def test_the_module_imports_no_network_library():
    tree = ast.parse(Path(p0.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & NETWORK
    assert set(p0.NETWORK_MODULES) <= NETWORK


def test_pinned_blobs_and_rule_files_match_the_run_tree():
    assert len(p0.check_blobs()) == len(p0.BLOBS)
    assert set(p0.check_rule_files()) == {p0.RULE_PATH, p0.CLARIFICATION_PATH, p0.CLARIFICATION2_PATH,
                                          p0.CLARIFICATION3_PATH}


def test_a_changed_blob_is_refused(tmp_path):
    f = tmp_path / "m.py"
    f.write_bytes(b"x = 1\n")
    want = hashlib.sha1(b"blob 6\0x = 1\n").hexdigest()
    assert p0.check_blobs(tmp_path, {"m.py": want})
    f.write_bytes(b"x = 2\n")
    with pytest.raises(p0.Refused, match="blob mismatch"):
        p0.check_blobs(tmp_path, {"m.py": want})


def test_origin_assertion(tmp_path):
    tree = tmp_path / "tree"
    (tree / "src" / "weather" / "calibration").mkdir(parents=True)
    (tree / "weather").mkdir()
    wf = tree / "src" / "weather" / "__init__.py"
    shim = tree / "weather" / "__init__.py"
    sub = tree / "src" / "weather" / "calibration" / "__init__.py"
    for f in (wf, shim, sub):
        f.write_text("", encoding="utf-8")
    subs = {"weather.calibration": str(sub)}
    env = {"PYTHONPATH": str(tree / "src")}
    assert p0.check_origin(tree, env, str(tree), str(wf), subs)["tree"] == str(tree)
    assert p0.check_origin(tree, env, str(tree), str(shim), subs)["weather_submodules_checked"] == 1
    with pytest.raises(p0.Refused, match="PYTHONPATH"):
        p0.check_origin(tree, {}, str(tree), str(wf), subs)
    with pytest.raises(p0.Refused, match="PYTHONPATH"):
        p0.check_origin(tree, {"PYTHONPATH": str(tmp_path / "other" / "src")}, str(tree), str(wf), subs)
    with pytest.raises(p0.Refused, match="cwd"):
        p0.check_origin(tree, env, str(tmp_path), str(wf), subs)
    other = tmp_path / "site" / "weather" / "calibration" / "__init__.py"
    other.parent.mkdir(parents=True)
    other.write_text("", encoding="utf-8")
    with pytest.raises(p0.Refused, match="weather imported"):
        p0.check_origin(tree, env, str(tree), str(other.parent.parent / "__init__.py"), subs)
    with pytest.raises(p0.Refused, match="outside"):        # the editable-.pth trap: shim here, code elsewhere
        p0.check_origin(tree, env, str(tree), str(shim), {"weather.calibration": str(other)})
    with pytest.raises(p0.Refused, match="no weather submodule"):
        p0.check_origin(tree, env, str(tree), str(shim), {})


def test_origin_in_this_process_resolves_every_weather_module_to_the_run_tree():
    files = p0.loaded_weather_files()
    assert files and all(p0._under(Path(f).resolve(), (p0.TREE / "src").resolve()) for f in files.values())


def test_out_dir_must_be_new_and_below_the_root(tmp_path):
    root = tmp_path / "rodc"
    assert p0.check_out_dir(root / "fit1", root) == root / "fit1"
    for bad in (root, tmp_path / "elsewhere", tmp_path / "rodcx" / "a"):
        with pytest.raises(p0.Refused, match="not below"):
            p0.check_out_dir(bad, root)
    (root / "fit1").mkdir(parents=True)
    with pytest.raises(p0.Refused, match="already exists"):
        p0.check_out_dir(root / "fit1", root)
    with pytest.raises(p0.Refused, match="required"):
        p0.check_out_dir(None, root)


def test_a_second_look_is_refused(tmp_path):
    assert p0.check_no_prior_look(tmp_path / "missing")
    (tmp_path / "look1").mkdir()
    assert p0.check_no_prior_look(tmp_path)
    (tmp_path / "look1" / p0.LOOK_RECEIPT).write_text("{}", encoding="utf-8")
    with pytest.raises(p0.Refused, match="second look"):
        p0.check_no_prior_look(tmp_path)


def test_coef_sha_is_required_and_checked(tmp_path):
    f = tmp_path / "coef.json"
    f.write_text(json.dumps({"arms": {}}), encoding="utf-8")
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    assert p0.check_coef(f, sha) == {"arms": {}}
    for bad in (None, "", "abc", "0" * 64):
        with pytest.raises(p0.Refused, match="coef"):
            p0.check_coef(f, bad)


def test_a_dirty_tree_is_refused():
    with pytest.raises(p0.Refused, match="dirty"):
        p0.require_clean({"dirty": True})
    assert p0.require_clean({"dirty": False}) == {"dirty": False}


def test_the_cli_has_no_dirty_override_and_the_look_needs_coef_sha_and_approval():
    parser = p0.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["look", "--out", "x", "--coef", "c"])
    with pytest.raises(SystemExit):
        parser.parse_args(["fit", "--out", "x", "--allow-dirty"])


def test_look_refuses_a_wrong_coef_sha_before_reading_any_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(p0, "check_origin", lambda: {})
    monkeypatch.setattr(p0, "code_state", lambda: {"dirty": False})
    monkeypatch.setattr(p0, "OUT_ROOT", tmp_path / "rodc")
    monkeypatch.setattr(p0, "check_out_dir", lambda out, root=None: p0.Path(out))
    monkeypatch.setattr(p0, "check_look2_guard", lambda: {})
    touched = []
    monkeypatch.setattr(p0, "control_cd", lambda: touched.append("cd"))
    coef = tmp_path / "coef.json"
    coef.write_text("{}", encoding="utf-8")
    par = tmp_path / "parity_receipt.json"
    par.write_text(json.dumps({"schema": p0.SCHEMA + "/parity", "ledger_row": p0.LEDGER_ROW,
                               "parity_limited": {a: False for a in p0.ARMS}}), encoding="utf-8")
    par_sha = hashlib.sha256(par.read_bytes()).hexdigest()
    coef_sha = hashlib.sha256(coef.read_bytes()).hexdigest()
    base = ["look", "--out", str(tmp_path / "rodc" / "look1"), "--coef", str(coef)]
    for extra in (["--coef-sha", "0" * 64, "--parity", str(par), "--parity-sha", par_sha],
                  ["--coef-sha", coef_sha, "--parity", str(tmp_path / "missing.json"), "--parity-sha", par_sha],
                  ["--coef-sha", coef_sha, "--parity", str(par), "--parity-sha", "0" * 64],
                  ["--coef-sha", coef_sha, "--parity", str(par), "--parity-sha", par_sha]):   # parity1, not parity2
        rc = p0.main(base + extra + ["--approval", p0.LOOK2_APPROVAL])
        assert rc == 2 and not touched and not (tmp_path / "rodc").exists()
    rc = p0.main(base + ["--coef-sha", coef_sha, "--parity", str(par), "--parity-sha", par_sha,
                         "--approval", "short"])
    assert rc == 2 and not touched
    with pytest.raises(SystemExit):        # the parity receipt is required
        p0.build_parser().parse_args(base + ["--coef-sha", coef_sha, "--approval", "x" * 10])


# ----------------------------------------------------------------------------- fit (history only)

def _cache(market, centre, n=80, seed=0, beta_low=0.5, beta_dew=-0.3, year0=2021):
    rng = np.random.default_rng(seed)
    hours = {}
    for h in p0.HOURS:
        rows = []
        for i in range(n):
            fc = 60 + rng.normal(0, 6)
            hsf = fc - 8 + rng.normal(0, 2)
            cur = hsf - rng.uniform(0, 2)
            low = 45 + rng.normal(0, 4)
            dew = 40 + rng.normal(0, 5)
            prev = low - rng.uniform(0, 3)
            actual = round(5 + 0.9 * fc + beta_low * (low - 45) + beta_dew * (dew - 40) + rng.normal(0, 0.5))
            rows.append({"date": f"{year0 + i % 5}-10-{1 + i % 28:02d}", "year": year0 + i % 5, "actual": actual,
                         "scored": True, "low_so_far": low, "low_prev_evening": prev, "forecast_high": fc,
                         "high_so_far": hsf, "current_temp": cur, "dewpoint_c": dew})
        hours[str(h)] = rows
    return {"market_id": market, "centre": centre, "timezone": "America/New_York", "bucket_space": list(range(30, 110)),
            "hours": hours}


def test_fit_recovers_planted_slopes_and_skips_denver_for_rodc():
    caches = [_cache(m, c, seed=k) for k, (m, c) in enumerate((m, c) for m in ("nyc", "denver")
                                                               for c in p0.OCTDEC_CENTRES)]
    coef, n = p0.fit_coefficients(caches)
    rodc = coef[p0.ARM_RODC]
    assert set(k.split("|")[0] for k in rodc) == {"nyc"}
    assert set(k.split("|")[0] for k in coef[p0.ARM_X13]) == {"nyc", "denver"}
    cell = rodc["nyc|9"]
    assert cell["columns"] == ["low_so_far", "dewpoint_c"] and cell["n"] == 5 * 80
    assert abs(cell["beta"][0] - 0.5) < 0.05 and abs(cell["beta"][1] + 0.3) < 0.05
    assert n["nyc|9"] == 400


def test_base_is_the_ladder_recipe_in_sample():
    from weather.calibration import ols_floor_ladder as lad
    from weather.calibration import r0_ols_floor_challenger as l3

    rows = _cache("nyc", "10-10")["hours"]["7"]
    rows[3]["high_so_far"] = None          # impute "fc", as the ladder
    rows[5]["forecast_high"] = None        # not usable
    got = p0.base_insample(rows)
    usable = [r for r in rows if r["forecast_high"] is not None]
    means = lad.fold_means(usable, lad.BASE_FEATURES)
    x = lad.design(usable, lad.BASE_FEATURES, means)
    beta, _ = l3.ols_fit(x, [float(r["actual"]) for r in usable])
    assert len(got) == len(usable)
    assert all(abs(mu - l3.ols_predict(beta, xi)) < 1e-12 for (_, mu), xi in zip(got, x))


def test_fit_refuses_a_non_history_date():
    c = _cache("nyc", "10-10")
    c["hours"]["8"][0]["date"] = "2026-10-05"
    with pytest.raises(p0.Refused, match="after 2025-12-31"):
        p0.fit_coefficients([c])


def test_increment_is_centred_and_none_when_a_column_is_missing():
    cell = {"columns": ["low_so_far", "dewpoint_c"], "beta": [0.5, -0.25], "means": [40.0, 30.0]}
    assert p0.increment(cell, {"low_so_far": 42, "dewpoint_c": 34}) == pytest.approx(1.0 - 1.0)
    assert p0.increment(cell, {"low_so_far": 44, "dewpoint_c": 30}) == pytest.approx(2.0)
    assert p0.increment(cell, {"low_so_far": None, "dewpoint_c": 30}) is None
    assert p0.increment(None, {"low_so_far": 1, "dewpoint_c": 1}) is None


# ----------------------------------------------------------------------------- serve-side features

def _metar_row(local, temp, dew=40.0):
    return {"obs_time": local.isoformat(), "temp_native": temp, "dewpoint_native": dew}


def _record(rows, fetched, report, match=True, ok=True):
    return {"sources": {"metar": {"ok": ok, "fetched_at": fetched.isoformat(),
                                  "data": {"target_date_match": match, "report_time": report.isoformat(),
                                           "rows": rows}}}}


def test_metar_validity_reasons():
    cap = datetime(2026, 10, 5, 14, 10, tzinfo=timezone.utc)
    good = _record([], cap - timedelta(minutes=5), cap - timedelta(minutes=20))
    assert p0.metar_valid(good, cap)[1] is None
    assert p0.metar_valid(_record([], cap, cap, ok=False), cap)[1] == "metar_not_ok"
    assert p0.metar_valid(_record([], cap, cap, match=False), cap)[1] == "target_date_mismatch"
    assert p0.metar_valid(_record([], cap + timedelta(seconds=1), cap), cap)[1] == "fetched_after_capture"
    assert p0.metar_valid(_record([], cap, cap + timedelta(seconds=1)), cap)[1] == "report_after_capture"


def test_snapshot_features_odc_and_x13_lows():
    d = date(2026, 10, 5)
    rows = [_metar_row(datetime(2026, 10, 4, 17, 51, tzinfo=NY), 66.0),     # before 18:00 on D-1: not evening
            _metar_row(datetime(2026, 10, 4, 21, 51, tzinfo=NY), 55.0),     # D-1 evening
            _metar_row(datetime(2026, 10, 5, 2, 51, tzinfo=NY), 57.4),
            _metar_row(datetime(2026, 10, 5, 5, 51, tzinfo=NY), 56.6, 50.0),
            _metar_row(datetime(2026, 10, 5, 8, 51, tzinfo=NY), 60.0, 52.0),
            _metar_row(datetime(2026, 10, 5, 9, 51, tzinfo=NY), 63.0, 53.0)]  # after the 09:00 cutoff
    cap = datetime(2026, 10, 5, 9, 55, tzinfo=NY).astimezone(timezone.utc)
    rec = _record(rows, cap - timedelta(minutes=2), cap - timedelta(minutes=4))
    f = p0.snapshot_features(rec, market="nyc", target_date=d, local_hour=9, captured=cap, tz=NY, unit="F")
    assert f["reason"] is None
    assert f["odc_low_so_far"] == 57 and f["dewpoint_c"] == 52 and f["current_temp"] == 60
    assert f["x13_low_so_far"] == 57.0 and f["low_prev_evening"] == 55.0
    rodc = p0.arm_columns(p0.ARM_RODC, f)
    x13 = p0.arm_columns(p0.ARM_X13, f)
    assert rodc == {"low_so_far": 57, "dewpoint_c": 52}
    assert x13 == {"low_so_far": 57.0, "low_prev_evening": 55.0, "dewpoint_c": 52}
    # without a D-1 evening row X13 has no low_prev_evening (uncovered)
    rec2 = _record(rows[2:], cap - timedelta(minutes=2), cap - timedelta(minutes=4))
    f2 = p0.snapshot_features(rec2, market="nyc", target_date=d, local_hour=9, captured=cap, tz=NY, unit="F")
    assert f2["low_prev_evening"] is None
    # a capture before 08:51 does not see that row
    early = datetime(2026, 10, 5, 8, 40, tzinfo=NY).astimezone(timezone.utc)
    rec3 = _record(rows, early - timedelta(minutes=2), early - timedelta(minutes=4))
    f3 = p0.snapshot_features(rec3, market="nyc", target_date=d, local_hour=9, captured=early, tz=NY, unit="F")
    assert f3["dewpoint_c"] == 50 and f3["current_temp"] == 57


def _sf(hour, low, cur, hsf, market="nyc", day="2026-10-05"):
    cap = datetime(2026, 10, 5, hour, 10, tzinfo=timezone.utc)
    return {"market": market, "date": day, "local_hour": hour, "captured": cap,
            "feats": {"odc_low_so_far": low, "current_temp": cur}, "high_so_far": hsf}


def test_control_cg_passes_and_refuses():
    ok = [_sf(7, 50, 52, 55.0), _sf(8, 50, 54, 56.0), _sf(9, 49, 56, float("nan"))]
    assert p0.control_cg(ok)["verdict"] == "PASS"
    with pytest.raises(p0.Refused, match="C-g"):
        p0.control_cg(ok[:2] + [_sf(9, 51, 56, 58.0)])         # running min rises
    with pytest.raises(p0.Refused, match="C-g"):
        p0.control_cg([_sf(7, 57, 58, 55.0)])                   # low above the layout high_so_far


def test_read_export_hashes_and_selects(tmp_path):
    slug = "highest-temperature-in-nyc-on-october-5-2026"
    f = tmp_path / "data" / "snapshots" / slug / "replay_inputs.jsonl"
    f.parent.mkdir(parents=True)
    lines = [json.dumps({"snapshot_id": f"s{i}", "captured_at_utc": "x", "v": i}) for i in range(3)]
    f.write_bytes(("\n".join(lines) + "\n").encode())
    digest = hashlib.sha256(f.read_bytes()).hexdigest()
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(f"{digest}  data/snapshots/{slug}/replay_inputs.jsonl\n", encoding="utf-8")
    sums_sha = hashlib.sha256(sums.read_bytes()).hexdigest()
    recs, malformed, hashed = p0.read_export(tmp_path, sums_sha, {"nyc|s1": slug})
    assert list(recs) == ["nyc|s1"] and recs["nyc|s1"]["v"] == 1 and not malformed and len(hashed) == 1
    with pytest.raises(p0.Refused, match="SHA256SUMS"):
        p0.read_export(tmp_path, "0" * 64, {"nyc|s1": slug})
    f.write_bytes(f.read_bytes() + b"{}\n")
    with pytest.raises(p0.Refused, match="differs"):
        p0.read_export(tmp_path, sums_sha, {"nyc|s1": slug})


# ----------------------------------------------------------------------------- statistic, D3, labels

def test_planted_toy_and_null():
    planted, null = p0.planted_toy(1.0), p0.planted_toy(0.0)
    assert planted["ci95_wider"][0] > 0
    assert null["ci95_wider"][0] <= 0 <= null["ci95_wider"][1]
    for iv in (planted, null):
        assert iv["ci95_wider"][0] <= min(iv["ci95_date_clustered"][0], iv["ci95_block3"][0]) + 1e-15
        assert iv["ci95_wider"][1] >= max(iv["ci95_date_clustered"][1], iv["ci95_block3"][1]) - 1e-15
        assert iv["se_wider"] == max(iv["se_date_clustered"], iv["se_block3"])
        assert iv["power_at_edge"] == pytest.approx(
            0.5 * (1 + math.erf((p0.DELTA_EDGE / iv["se_wider"] - 1.959963984540054) / math.sqrt(2))))


@pytest.mark.parametrize("args, label", [
    ((False, 0.99, 0.1, -0.1, False), p0.LABEL_UNTESTABLE),
    ((True, 0.4, 0.3, -0.1, True), p0.LABEL_UNTESTABLE_EDGE),
    ((True, 0.4, 0.2, -0.1, True), p0.LABEL_UNTESTABLE_SUB),
    ((True, None, 0.2, -0.1, True), p0.LABEL_UNTESTABLE_SUB),
    ((True, 0.9, 0.2, 0.01, True), p0.LABEL_KILL),
    ((True, 0.9, 0.3, 0.01, True), p0.LABEL_SCREEN),
    ((True, 0.9, 0.3, 0.01, False), p0.LABEL_NOT_KILLED),
    ((True, 0.9, 0.3, -0.01, True), p0.LABEL_NOT_KILLED),
])
def test_labels_in_rule_order(args, label):
    assert p0.label_for(*args) == label


def test_bh_table_two_implementations_agree():
    adj, rej = p0.bh_table([0.04, 0.2])
    assert rej == [True, False] and adj[0] == pytest.approx(0.08)
    adj, rej = p0.bh_table([0.06, 0.09])
    assert rej == [True, True]
    assert p0.bh_table([1.0, 1.0])[1] == [False, False]


@pytest.mark.skipif(not (p0.ROW80_ARCHIVE / "outputs" / "look" / "rows.jsonl").is_file(),
                    reason="row 80 archive not on this machine")
def test_control_cd_reproduces_row80_label():
    out = p0.control_cd()
    assert out["verdict"] == "PASS" and out["max_abs_diff"] <= 1e-12


def test_zero_tilt_identity_and_restrict_identity_on_a_synthetic_layout(tmp_path):
    from tests.reporting.test_released_window_served_market_blocks import write_layout

    from weather.calibration import mr_sweep as sw
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    root = write_layout(tmp_path / "lay", date(2026, 8, 1), 6)
    lay = data.load_layout(root, data.DEV_FIRST, date(2026, 8, 6))
    t = sc.Table(lay, sorted(lay.dates))
    geo = sw.band_geometry(t)
    out = p0.control_cc(t, geo)
    assert out["verdict"] == "PASS" and out["max_abs_c_minus_m"] <= 1e-15
    assert "snapshots_with_m_below_eps" in out           # ruling 2: the separate count is kept
    assert p0.control_restrict_identity(t)["verdict"] == "PASS"


# ----------------------------------------------------------------------------- master's rulings (2026-10-31)

def _pin_blob(sha):
    import subprocess

    got = subprocess.run(["git", "-C", str(p0.TREE), "cat-file", "blob", sha], capture_output=True)
    if got.returncode != 0:
        pytest.skip(f"pin blob {sha} not in this clone")
    return got.stdout.decode("utf-8")


def test_ruling_1a_orm_functions_are_source_identical_to_the_pin_blob():
    src = _pin_blob(p0.ORM_PIN_BLOB)
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    for fn, want in p0.ORM_PIN_SOURCE_SHA256.items():
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn)
        seg = "".join(lines[node.lineno - 1:node.end_lineno])
        assert hashlib.sha256(seg.encode("utf-8")).hexdigest() == want
    assert f'METAR_OBSERVATION_GROUP_RE = re.compile(r"{p0.ORM_PIN_GROUP_RE}")' in src
    assert p0.check_pin_identity()["orm_source_sha256"] == p0.ORM_PIN_SOURCE_SHA256


def test_ruling_1b_prm_constants_equal_the_pin_blob_values():
    tree = ast.parse(_pin_blob(p0.PRM_PIN_BLOB))
    pinned = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                getattr(node.targets[0], "id", None) in p0.PRM_PIN_CONSTANTS:
            pinned[node.targets[0].id] = ast.literal_eval(node.value)
    assert pinned == p0.PRM_PIN_CONSTANTS
    from weather.calibration import loyo_screen as ls

    assert (ls.DEFAULT_DRAWS, ls.DEFAULT_SEED) == (2000, 20261024)


def test_ruling_1_mismatches_are_refused():
    import types

    from weather.calibration import pooled_residual_model as prm
    from weather.model import observed_running_max as orm

    def metar_observation_local_time(row, tz, raw_obs_times=None):
        return None

    fake_orm = types.SimpleNamespace(metar_observation_local_time=metar_observation_local_time,
                                     row_obs_time_local=orm.row_obs_time_local,
                                     METAR_OBSERVATION_GROUP_RE=orm.METAR_OBSERVATION_GROUP_RE)
    with pytest.raises(p0.Refused, match="observed_running_max"):
        p0.check_pin_identity(orm=fake_orm, prm=prm)
    fake_prm = types.SimpleNamespace(BOOTSTRAP_DRAWS=1000, BOOTSTRAP_SEED=prm.BOOTSTRAP_SEED,
                                     R0_MARKETS=prm.R0_MARKETS)
    with pytest.raises(p0.Refused, match="pooled_residual_model"):
        p0.check_pin_identity(orm=orm, prm=fake_prm)


def test_ruling_2_cc_call_paths_are_recorded_and_differ_so_the_look_needs_the_pinned_ruling():
    audit = p0.cc_path_audit()
    assert audit["candidate"]["function"] == "mr_sweep.tilt"
    assert audit["placebo"]["function"] == "mr_sweep.disagreement_placebo"
    assert audit["candidate"]["renormalised_to_sum_m"] and audit["placebo"]["renormalised_to_sum_m"]
    assert audit["candidate"]["clip_to_eps"] is False and audit["placebo"]["clip_to_eps"] is True
    assert audit["identical_clip_and_renormalisation"] is False
    with pytest.raises(p0.Refused, match="awaiting master"):
        p0.check_cc_paths(ruling="")
    assert p0.check_cc_paths()["ruling"] == p0.CC_PATH_RULING
    assert p0.CC_PATH_RULING == ("master 10-31 C-c: frozen statistic; exact identities as above; m<EPS count; "
                                 "all-m>=EPS sensitivity guards KILL")


def test_ruling_2_candidate_is_not_clipped_and_the_placebo_is():
    """Behavioural check of the audit: a band below EPS stays below EPS in c; the placebo lifts it to ~EPS."""
    from weather.calibration import market_blend as mb
    from weather.calibration import mr_sweep as sw

    class T:
        n = np.array([3])
        band_snap = np.array([0, 0, 0])
        snaps = [0]
        p_market = np.array([1e-6, 0.5, 0.499999])

    geo = {"mt": T.p_market / T.p_market.sum(), "tot": np.array([T.p_market.sum()])}
    c, _ = sw.tilt(T, geo, np.zeros(3), np.array([True]))
    assert c[0] < mb.EPS
    pl, _ = sw.disagreement_placebo(T, c, 0, donor=(np.arange(3), {}))
    assert pl[0] > 0.99 * mb.EPS and pl.sum() == pytest.approx(T.p_market.sum())


def _prec(mk, low_c, low_s, prev_c, prev_s):
    return {"market": mk, "date": "2024-10-01", "hour": 9, "kept_rows": 4, "implausible": 0,
            "cache": {"low_so_far": low_c, "low_prev_evening": prev_c},
            "serve": {"odc_low_so_far": low_s, "x13_low_so_far": low_c, "low_prev_evening": prev_s}}


def test_ruling_4_parity_table_flags_and_receipt_check(tmp_path):
    recs = []
    for mk in p0.US11:
        recs += [_prec(mk, 50.0, 50, 48.0, 48.0), _prec(mk, 52.0, 52, 47.0, 47.0)]
    table, limited, _ = p0.parity_table(recs)
    assert limited == {p0.ARM_RODC: False, p0.ARM_X13: False}
    assert table["nyc"]["odc_low_so_far-vs-low_so_far"] == {"n": 2, "mae": 0.0, "max_abs": 0.0, "bias": 0.0}
    # +1 F in the R-ODC low in Miami and Denver: R-ODC is limited by Miami only (Denver is uncovered); X13 is not
    recs2 = [dict(r, serve=dict(r["serve"], odc_low_so_far=r["serve"]["odc_low_so_far"] + 1))
             if r["market"] in ("miami", "denver") else r for r in recs]
    _, limited, reasons = p0.parity_table(recs2)
    assert limited == {p0.ARM_RODC: True, p0.ARM_X13: False}
    assert {w[0] for w in reasons[p0.ARM_RODC]} == {"miami"}
    # no overlap in a covered market -> parity-limited (conservative)
    assert p0.parity_table([r for r in recs if r["market"] != "seattle"])[1] == {p0.ARM_RODC: True,
                                                                                 p0.ARM_X13: True}
    assert p0.label_with_parity(p0.LABEL_KILL, True) == p0.LABEL_KILL + p0.PARITY_SUFFIX
    assert p0.label_with_parity(p0.LABEL_KILL, False) == p0.LABEL_KILL

    f = tmp_path / "parity2_receipt.json"
    f.write_text(json.dumps(_parity2_receipt(limited)), encoding="utf-8")
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    assert p0.check_parity(f, sha)["parity_limited"] == limited
    for path, s, msg in ((tmp_path / "none.json", sha, "missing"), (f, None, "required"), (f, "0" * 64, "is not")):
        with pytest.raises(p0.Refused, match=msg):
            p0.check_parity(path, s)
    bad = [{"schema": p0.SCHEMA + "/parity"}, {"look_serve_rule": p0.SERVE_RULE_OFF},
           {"odc_metar_features_blob": "0" * 40}, {"arm_excluded_markets": {a: [] for a in p0.ARMS}},
           {"parity_limited": {a: True for a in p0.ARMS}}]
    for change, msg in zip(bad, ("parity2", "decided under", "changed odc", "exclusions", "deciding")):
        f.write_text(json.dumps(dict(_parity2_receipt(limited), **change)), encoding="utf-8")
        with pytest.raises(p0.Refused, match=msg):
            p0.check_parity(f, hashlib.sha256(f.read_bytes()).hexdigest())


def _parity2_receipt(limited):
    return {"schema": p0.SCHEMA + "/parity2", "ledger_row": p0.LEDGER_ROW, "look_serve_rule": p0.LOOK_SERVE_RULE,
            "odc_metar_features_blob": p0.ODC_FROZEN_BLOB,
            "arm_excluded_markets": {a: sorted(v) for a, v in p0.ARM_EXCLUDED_MARKETS.items()},
            "runs": {p0.LOOK_SERVE_RULE: {"deciding": True, "parity_limited": limited},
                     p0.SERVE_RULE_OFF: {"deciding": False, "parity_limited": limited}},
            "parity_limited": limited}


def test_ruling_4_parity_records_use_the_serve_code_on_history(tmp_path):
    root = tmp_path / "metar" / "klga"
    part = root / "hourly" / "year=2024" / "month=10" / "observations.jsonl"
    part.parent.mkdir(parents=True)
    obs = [("2024-10-01", "22:51", 55.0), ("2024-10-02", "02:51", 57.4), ("2024-10-02", "05:51", 56.6),
           ("2024-10-02", "06:51", 25.0), ("2024-10-02", "08:51", 60.0), ("2024-10-02", "09:51", 50.0)]
    lines = [json.dumps({"local_date": d, "valid_time_local": f"{d}T{t}:00-04:00", "temp_native": v,
                         "dewpoint_native": 40.0}) for d, t, v in obs]
    part.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    manifest = {"partitions": [{"path": "hourly/year=2024/month=10/observations.jsonl",
                                "sha256": hashlib.sha256(part.read_bytes()).hexdigest()}]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    by_date, hashed = p0.read_metar_history(tmp_path / "metar", "klga", {(2024, 10), (2024, 9)})
    assert len(hashed) == 1 and len(by_date["2024-10-02"]) == 5
    cache = {"market_id": "nyc", "hours": {"9": [{"date": "2024-10-02", "low_so_far": 57.0,
                                                   "low_prev_evening": 55.0}]}}
    recs, conflicts = p0.parity_records([cache, cache], {"nyc": by_date}, {"nyc": NY}, {"nyc": "F"}, hours=(9,))
    assert conflicts == 0 and len(recs) == 1
    r = recs[0]
    assert r["serve"] == {"odc_low_so_far": 57, "x13_low_so_far": 57.0, "low_prev_evening": 55.0}
    assert r["implausible"] == 1 and r["kept_rows"] == 4          # the 25 F row is dropped by the filter
    assert r["dropped_by_rule"] == 1 and r["below_m40"] == 0
    for rule in (p0.SERVE_RULE_OFF, p0.SERVE_RULE_TRAINER):     # Clarification 2: the 25 F row is kept
        r2 = p0.parity_records([cache], {"nyc": by_date}, {"nyc": NY}, {"nyc": "F"}, hours=(9,), rule=rule)[0][0]
        assert r2["serve"] == {"odc_low_so_far": 25, "x13_low_so_far": 25.0, "low_prev_evening": 25.0}
        assert r2["implausible"] == 1 and r2["dropped_by_rule"] == 0
    assert p0._ACTIVE_RULE[0] == p0.SERVE_RULE_FROZEN
    part.write_bytes(part.read_bytes() + b"{}\n")
    with pytest.raises(p0.Refused, match="manifest"):
        p0.read_metar_history(tmp_path / "metar", "klga", {(2024, 10)})
    late = {"market_id": "nyc", "hours": {"9": [{"date": "2026-01-02", "low_so_far": 1.0}]}}
    with pytest.raises(p0.Refused, match="after 2025-12-31"):
        p0.parity_records([late], {"nyc": by_date}, {"nyc": NY}, {"nyc": "F"}, hours=(9,))


def test_parity_cli_defaults():
    args = p0.build_parser().parse_args(["parity", "--out", r"C:\t\l16\rodc\parity1"])
    assert args.cache_dir == str(p0.L9_CACHE) and args.metar_dir == str(p0.METAR_HISTORY)


def test_parity2_cli():
    args = p0.build_parser().parse_args(["parity2", "--out", r"C:\t\l16\rodc\parity2"])
    assert args.stage == "parity2" and args.cache_dir == str(p0.L9_CACHE) and args.metar_dir == str(p0.METAR_HISTORY)


# ----------------------------------------------------------------------------- Clarification 2 (2026-10-31)

def test_clarification_2_is_pinned():
    assert p0.check_rule_files()[p0.CLARIFICATION2_PATH] == p0.CLARIFICATION2_SHA256
    text = " ".join((p0.TREE / p0.CLARIFICATION2_PATH).read_text(encoding="utf-8").split())
    assert p0.CC_PATH_RULING in text
    for blob in (p0.ODC_FROZEN_BLOB,) + tuple(e["blob"] for e in p0.TRAINER_PLAUSIBILITY["trainer_path"]):
        assert blob in text


def test_odc_metar_features_is_blob_unchanged():
    import subprocess

    path = p0.TREE / "src/weather/calibration/odc_metar_features.py"
    assert p0.git_blob_sha(path) == p0.ODC_FROZEN_BLOB == p0.BLOBS["src/weather/calibration/odc_metar_features.py"]
    got = subprocess.run(["git", "-C", str(p0.TREE), "rev-parse",
                          "0e11b018f:src/weather/calibration/odc_metar_features.py"], capture_output=True, text=True)
    if got.returncode != 0:
        pytest.skip("0e11b018f not in this clone")
    assert got.stdout.strip() == p0.ODC_FROZEN_BLOB


def test_trainer_path_has_no_plausibility_filter():
    import inspect

    from weather.calibration import ols_floor_ladder as lad
    from weather.model import model_climatology as mc

    for fn in (mc.ClimatologyMixin.historical_target_cache, lad.overnight_lows):
        assert "plausib" not in inspect.getsource(fn)
    low, prev = lad.overnight_lows([{"minute_of_day": 60, "temp_native": 12.0}], date(2024, 12, 1), 9,
                                   [{"minute_of_day": 1200, "temp_native": -5.0}], None)
    assert low == 12.0 and prev == -5.0


def test_serve_rules():
    assert p0.serve_plausible(25.0, "F", p0.SERVE_RULE_FROZEN) is False
    assert p0.serve_plausible(25.0, "F", p0.SERVE_RULE_OFF) is True
    assert p0.serve_plausible(25.0, "F", p0.SERVE_RULE_TRAINER) is True
    assert p0.serve_plausible(-40.0, "F", p0.SERVE_RULE_TRAINER) is True
    assert p0.serve_plausible(-40.5, "F", p0.SERVE_RULE_TRAINER) is False
    assert p0.serve_plausible(130.0, "F", p0.SERVE_RULE_TRAINER) is True     # the trainer has no upper bound
    for v in (None, "x", float("nan"), float("inf")):
        assert p0.serve_plausible(v, "F", p0.SERVE_RULE_OFF) is False
    with pytest.raises(p0.Refused):
        p0.serve_plausible(1.0, "F", "other")
    assert p0.LOOK_SERVE_RULE == p0.SERVE_RULE_TRAINER and p0.PHYSICAL_LOWER_NATIVE == -40.0


def test_serve_rule_override_is_scoped_and_frozen_rule_is_identity():
    from weather.calibration import odc_metar_features as odc

    original = odc.plausible_native_temperature
    d = date(2026, 10, 5)
    rows = [_metar_row(datetime(2026, 10, 4, 21, 51, tzinfo=NY), 31.0),
            _metar_row(datetime(2026, 10, 5, 5, 51, tzinfo=NY), 24.4, 20.0),
            _metar_row(datetime(2026, 10, 5, 8, 51, tzinfo=NY), 33.0, 22.0)]
    cap = datetime(2026, 10, 5, 9, 55, tzinfo=NY).astimezone(timezone.utc)
    rec = _record(rows, cap - timedelta(minutes=2), cap - timedelta(minutes=4))
    kw = dict(market="nyc", target_date=d, local_hour=9, captured=cap, tz=NY, unit="F")
    plain = p0.snapshot_features(rec, **kw)
    with p0.serve_rule(p0.SERVE_RULE_FROZEN) as o:
        assert o["rule"] == p0.SERVE_RULE_FROZEN
        frozen = p0.snapshot_features(rec, **kw)
    assert frozen == plain and plain["odc_low_so_far"] == 33 and plain["n_implausible"] == 1
    assert plain["x13_low_so_far"] == 33.0 and plain["low_prev_evening"] == 31.0
    with p0.serve_rule(p0.SERVE_RULE_TRAINER):
        fixed = p0.snapshot_features(rec, **kw)
    assert fixed["odc_low_so_far"] == 24 and fixed["x13_low_so_far"] == 24.0 and fixed["low_prev_evening"] == 24.0
    assert fixed["dewpoint_c"] == plain["dewpoint_c"] == 22 and fixed["n_implausible"] == 1
    assert odc.plausible_native_temperature is original and p0._ACTIVE_RULE[0] == p0.SERVE_RULE_FROZEN
    with pytest.raises(RuntimeError):
        with p0.serve_rule(p0.SERVE_RULE_OFF):
            raise RuntimeError("boom")
    assert odc.plausible_native_temperature is original and p0._ACTIVE_RULE[0] == p0.SERVE_RULE_FROZEN


def test_denver_is_excluded_from_both_arms():
    assert all("denver" in p0.ARM_EXCLUDED_MARKETS[a] for a in p0.ARMS)
    recs = []
    for mk in p0.US11:
        recs += [_prec(mk, 50.0, 50, 48.0, 48.0), _prec(mk, 52.0, 52, 47.0, 47.0)]
    recs = [dict(r, serve=dict(r["serve"], odc_low_so_far=60, x13_low_so_far=60.0, low_prev_evening=60.0))
            if r["market"] == "denver" else r for r in recs]
    table, limited, _ = p0.parity_table(recs)
    assert limited == {p0.ARM_RODC: False, p0.ARM_X13: False}
    assert table["denver"]["odc_low_so_far-vs-low_so_far"]["n"] == 2          # reported, decides nothing


def test_eps_guard():
    assert p0.eps_guard(p0.LABEL_KILL, p0.LABEL_KILL) == p0.LABEL_KILL
    for other in (p0.LABEL_NOT_KILLED, p0.LABEL_UNTESTABLE, p0.LABEL_UNTESTABLE_EDGE, p0.LABEL_SCREEN):
        assert p0.eps_guard(p0.LABEL_KILL, other) == p0.LABEL_UNRESOLVED_EPS == "UNRESOLVED (EPS-path sensitive)"
        assert p0.eps_guard(other, p0.LABEL_KILL) == other
    assert p0.label_with_parity(p0.eps_guard(p0.LABEL_KILL, p0.LABEL_NOT_KILLED), True) == \
        "UNRESOLVED (EPS-path sensitive)" + p0.PARITY_SUFFIX


def _synthetic_table(tmp_path):
    from tests.reporting.test_released_window_served_market_blocks import write_layout

    from weather.calibration import mr_sweep as sw
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data

    root = write_layout(tmp_path / "lay", date(2026, 8, 1), 6)
    lay = data.load_layout(root, data.DEV_FIRST, date(2026, 8, 6))
    t = sc.Table(lay, sorted(lay.dates))
    return t, sw.band_geometry(t), np.array(sorted(str(d) for d in lay.dates))


def test_cc_records_bitwise_counts(tmp_path):
    t, geo, _ = _synthetic_table(tmp_path)
    out = p0.control_cc(t, geo)
    assert out["verdict"] == "PASS" and out["ruling"] == p0.CC_PATH_RULING
    assert set(out["bands_bitwise_unequal"]) == {"candidate_vs_m", "placebo_seed0_vs_clip_renorm_m", "bands"}
    assert out["max_abs_placebo_minus_clip_renorm_m"] <= p0.C_C_TOL


def test_eps_sensitivity_reproduces_and_restricts(tmp_path, monkeypatch):
    from weather.calibration import market_blend as mb
    from weather.calibration import mr_sweep as sw

    t, geo, dates = _synthetic_table(tmp_path)
    for mod in (sw, p0):
        monkeypatch.setattr(mod, "MIN_DATES", 1)
        monkeypatch.setattr(mod, "MIN_SNAPS", 1)
    rng = np.random.default_rng(3)
    values = geo["mu"] + rng.normal(0, 1, len(t.snaps))
    donors = {seed: sw.donor_positions(t, seed) for seed in sw.PLACEBO_SEEDS}
    counts = sw.boot_counts(len(dates))
    res, _ = sw.p0_candidate("x", "C", 1, values, t, t, geo, counts, dates, donors)
    sens = p0.eps_sensitivity("x", values, t, geo, dates, donors, res)
    ok = p0.all_m_ok(t)
    assert ok.dtype == bool and len(ok) == len(t.snaps)
    assert int((~ok).sum()) == int((np.bincount(t.band_snap, weights=(t.p_market < mb.EPS).astype(float),
                                                minlength=len(t.snaps)) > 0).sum())
    assert sens["population_snapshots"] + sens["dropped_snapshots_m_below_eps"] == \
        res["coverage"]["population_snapshots"]
    if sens["dropped_snapshots_m_below_eps"] == 0 and sens["testable"]:
        assert sens["d3"]["delta"] == pytest.approx(res["p0"]["delta"], abs=1e-12)
    if res["testable"]:
        bad = dict(res, p0=dict(res["p0"], delta=res["p0"]["delta"] + 1.0))
        with pytest.raises(p0.Refused, match="reproduce"):
            p0.eps_sensitivity("x", values, t, geo, dates, donors, bad)


def test_projected_power_at_us10_n():
    have = (p0.ROW80_ARCHIVE / "outputs" / "look" / "rows.jsonl").is_file()
    n80 = p0.row80_population() if have else 10000
    same = p0.projected_power(n80, n80)
    assert same["se_projected"] == pytest.approx(p0.ROW80_SE) and same["power"] > 0.9999
    quarter = p0.projected_power(n80 / 4, n80)
    assert quarter["se_projected"] == pytest.approx(2 * p0.ROW80_SE)
    want = 0.5 * (1 + math.erf((0.2236 / quarter["se_projected"] - 1.959963984540054) / math.sqrt(2)))
    assert quarter["power"] == pytest.approx(want, abs=1e-6)
    assert p0.projected_power(0, n80)["power"] is None


def _look_src():
    import inspect

    return inspect.getsource(p0.look_front) + inspect.getsource(p0.look_tail)


def test_coverage_floor_override_is_live_before_band_scoring():
    import inspect

    from weather.calibration import mr_sweep as sw

    src = _look_src()
    i_set = src.index("sw.MIN_DATES, sw.MIN_SNAPS = MIN_DATES, MIN_SNAPS")
    assert i_set < src.index("check_coverage_floor_live(sw)") < src.index("sw.p0_candidate(")
    assert "n_dates < MIN_DATES or n_snaps < MIN_SNAPS" in inspect.getsource(sw.p0_candidate)
    assert "MIN_DATES" not in str(inspect.signature(sw.p0_candidate))
    saved = (sw.MIN_DATES, sw.MIN_SNAPS)
    try:
        sw.MIN_DATES, sw.MIN_SNAPS = 20, 1000
        with pytest.raises(p0.Refused, match="coverage floor"):
            p0.check_coverage_floor_live(sw)
        sw.MIN_DATES, sw.MIN_SNAPS = p0.MIN_DATES, p0.MIN_SNAPS
        assert p0.check_coverage_floor_live(sw) == {"mr_sweep.MIN_DATES": 10, "mr_sweep.MIN_SNAPS": 1000}
    finally:
        sw.MIN_DATES, sw.MIN_SNAPS = saved


def test_look_order_controls_before_prices_and_power_before_delta():
    src = _look_src()
    t_at = src.index("t = sc.Table(lay, dates)")
    for before in ('controls["C-d"] = control_cd()', 'controls["C-e"] = control_ce()',
                   'controls["C-g"] = control_cg(snaps_feats)', "power_projection_us10",
                   "with serve_rule(LOOK_SERVE_RULE)", "smb.released_dev_last(RELEASE_LAST)"):
        assert src.index(before) < t_at
    assert t_at < src.index("control_cc(t, geo)") < src.index("sw.p0_candidate(")
    assert "check_parity(args.parity, args.parity_sha)" in src and "eps_guard(" in src


def test_fix3_look_started_marker_blocks_a_second_look(tmp_path):
    (tmp_path / "look1").mkdir()
    (tmp_path / "look1" / p0.LOOK_STARTED).write_text("{}", encoding="utf-8")
    with pytest.raises(p0.Refused, match="second look"):
        p0.check_no_prior_look(tmp_path)


def test_fix3_look_started_is_written_before_the_release_layout_load():
    look = inspect.getsource(p0.stage_look)
    front = inspect.getsource(p0.look_front)
    assert look.index("check_look2_guard()") < look.index("check_out_dir(args.out, LOOK2_ROOT)") < \
        look.index("begin_look(o, args.approval)") < look.index("look_tail(args, ctx, out)")
    assert front.index("mark(out) if mark is not None") < front.index("data.load_layout(R80_LAYOUT")
    assert "mkdir" not in look and "mkdir" not in front and "mkdir" not in inspect.getsource(p0.look_tail)
    tail = inspect.getsource(p0.look_tail)
    assert tail.index("write_look_rows(out, rows_out)") < tail.index("write_look_receipt(out, receipt)")


def _roots(tmp_path, monkeypatch):
    rodc, look2 = tmp_path / "rodc", tmp_path / "rodc-look2"
    monkeypatch.setattr(p0, "OUT_ROOT", rodc)
    monkeypatch.setattr(p0, "LOOK2_ROOT", look2)
    return rodc, look2


def test_fix3_begin_look_creates_the_dir_and_marker_and_a_second_begin_refuses(tmp_path, monkeypatch):
    _, look2 = _roots(tmp_path, monkeypatch)
    out = p0.check_out_dir(look2 / "l2", look2)
    sha = p0.begin_look(out, p0.LOOK2_APPROVAL)
    marker = out / p0.LOOK_STARTED
    assert out.is_dir() and marker.is_file() and sha == hashlib.sha256(marker.read_bytes()).hexdigest()
    rec = json.loads(marker.read_text(encoding="utf-8"))
    assert rec["schema"] == p0.SCHEMA + "/look_started" and rec["approval"] == p0.LOOK2_APPROVAL
    with pytest.raises(p0.Refused, match="no look3"):            # same out
        p0.begin_look(out, p0.LOOK2_APPROVAL)
    with pytest.raises(p0.Refused, match="no look3"):            # a fresh out under the same root
        p0.begin_look(look2 / "l3", p0.LOOK2_APPROVAL)
    assert not (look2 / "l3").exists()


def test_fix3_begin_look_refuses_an_existing_out_dir(tmp_path, monkeypatch):
    _, look2 = _roots(tmp_path, monkeypatch)
    (look2 / "l2").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        p0.begin_look(look2 / "l2", p0.LOOK2_APPROVAL)
    assert not (look2 / "l2" / p0.LOOK_STARTED).exists()


def test_fix3_the_look_tail_writes_into_the_begun_out(tmp_path, monkeypatch):
    _, look2 = _roots(tmp_path, monkeypatch)
    out = p0.check_out_dir(look2 / "l2", look2)
    started = p0.begin_look(out, p0.LOOK2_APPROVAL)
    rows = [{"arm": "X13", "n": np.int64(3), "ok": np.bool_(True)}, {"arm": "R", "x": np.float64(0.5)}]
    rows_sha = p0.write_look_rows(out, rows)
    receipt = {"schema": p0.SCHEMA + "/look", "look_started_sha256": started, "flag": np.bool_(False)}
    receipt_sha = p0.write_look_receipt(out, receipt)
    assert rows_sha == hashlib.sha256((out / "rows.jsonl").read_bytes()).hexdigest()
    assert [json.loads(x) for x in (out / "rows.jsonl").read_text(encoding="utf-8").splitlines()] == \
        [{"arm": "X13", "n": 3, "ok": True}, {"arm": "R", "x": 0.5}]
    assert receipt_sha == hashlib.sha256((out / p0.LOOK_RECEIPT).read_bytes()).hexdigest()
    assert json.loads((out / p0.LOOK_RECEIPT).read_text(encoding="utf-8"))["look_started_sha256"] == started
    with pytest.raises(FileExistsError):
        p0.write_look_rows(out, rows)
    with pytest.raises(FileExistsError):
        p0.write_look_receipt(out, receipt)
    with pytest.raises(p0.Refused, match="no look3"):
        p0.check_look2_guard()


def test_fix3_each_stage_mkdirs_once_after_check_out_dir_and_before_its_first_write():
    for fn in (p0.stage_fit, p0.stage_parity, p0.stage_parity2, p0.begin_look):
        src = inspect.getsource(fn)
        assert src.count("mkdir(") == 1, fn.__name__
        first_write = min(i for i in (src.find('.open("x"'), src.find("write_exclusive(")) if i >= 0)
        assert src.index("mkdir(") < first_write, fn.__name__
    for fn in (p0.stage_fit, p0.stage_parity, p0.stage_parity2):
        src = inspect.getsource(fn)
        assert src.index("check_out_dir(") < src.index("mkdir("), fn.__name__


def test_fix3_default_serialises_numpy_scalars(tmp_path):
    sha = p0.write_exclusive(tmp_path / "r.json", {"b": np.bool_(True), "i": np.int64(3), "f": np.float32(0.5)})
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8")) == {"b": True, "i": 3, "f": 0.5}
    assert len(sha) == 64
    with pytest.raises(FileExistsError):
        p0.write_exclusive(tmp_path / "r.json", {})


def test_fix4_snapshot_id_is_found_past_16_kib():
    line = b'{"pad": "' + b"x" * 40000 + b'", "snapshot_id": "abc|1"}\n'
    assert p0.SNAP_ID.search(line).group(1) == b"abc|1"
    assert "16384" not in inspect.getsource(p0)


def test_fix2_x13_lows_are_wu_whole_degrees():
    rows = [_metar_row(datetime(2026, 10, 5, 2, 51, tzinfo=NY), 57.4),
            _metar_row(datetime(2026, 10, 5, 5, 51, tzinfo=NY), 56.6),
            _metar_row(datetime(2026, 10, 4, 21, 51, tzinfo=NY), 55.4)]
    lo, prev = p0.x13_lows({"rows": rows}, target_date=date(2026, 10, 5), tz=NY, unit="F", cutoff_hour=9,
                           now=datetime(2026, 10, 5, 9, 0, tzinfo=NY))
    assert (lo, prev) == (57.0, 55.0)


# ----------------------------------------------------------------------------- Clarification 3

def test_clarification_3_is_pinned():
    assert p0.check_rule_files()[p0.CLARIFICATION3_PATH] == p0.CLARIFICATION3_SHA256
    assert p0.LOOK2_APPROVAL == ("master 10-31 R-ODC row 103 look2: one bounded C-g WU-scale repair (Clarification 3) "
                                 "after look1 refused at C-g before any statistic; rehearsal PASS required; no look3")
    assert p0.LOOK1_MARKER_SHA256 == "1f3ee224f8a1775f4360a00543e7a7fbf91a75c7af11ea6344529cbf204d8b93"
    assert p0.LOOK1_REFUSAL_LOG_SHA256 == "68755c85f13da8edbf88758368147c563f9c222bf7cc6f0deb40ebc78b7c871d"


def test_look1_marker_and_refusal_log_on_this_host_match_the_pins():
    marker = p0.OUT_ROOT / "look1" / p0.LOOK_STARTED
    log = p0.OUT_ROOT.parent / "rodc-look1-console.log"
    if not marker.is_file():
        pytest.skip("look1 marker is not on this host")
    assert hashlib.sha256(marker.read_bytes()).hexdigest() == p0.LOOK1_MARKER_SHA256
    if log.is_file():
        assert hashlib.sha256(log.read_bytes()).hexdigest() == p0.LOOK1_REFUSAL_LOG_SHA256


def test_cg_compares_on_the_wu_whole_scale_and_counts_what_the_frozen_check_would_refuse():
    out = p0.control_cg([_sf(7, 65, 65, 64.94, market="atlanta", day="2026-10-01"),
                         _sf(8, 65, 66, 66.02, market="atlanta", day="2026-10-01"),
                         _sf(7, 79, 79, 78.98, market="miami", day="2026-10-01")])
    assert out["verdict"] == "PASS" and out["scale"] == "wu_whole_f half_up on both sides"
    assert out["frozen_raw_high_would_refuse"] == {"snapshots_low_above_raw_high": 2, "cells_check_bounds_refuses": 2,
                                                   "snapshots_dropped_or_flagged": 0}
    with pytest.raises(p0.Refused, match="C-g"):                  # a real violation still refuses
        p0.control_cg([_sf(7, 66, 66, 64.94)])
    with pytest.raises(p0.Refused, match="C-g"):                  # and so does a rising running minimum
        p0.control_cg([_sf(7, 60, 61, 64.94), _sf(8, 62, 62, 64.94)])


def test_wu_whole_rounding_is_monotone_on_tgroup_values():
    from weather.model.mg_serve_core import wu_whole_f

    raw = sorted(round(c / 10 * 9 / 5 + 32, 2) for c in range(-450, 500))
    whole = [wu_whole_f(v, "half_up") for v in raw]
    assert all(a <= b for a, b in zip(whole, whole[1:]))


def test_check_bounds_never_drops_or_flags_and_is_not_in_the_feature_path():
    from weather.calibration import odc_metar_features as odc

    for fn in (odc.odc_features, odc.kept_rows):
        assert "check_bounds" not in inspect.getsource(fn)
    for fn in (p0.snapshot_features, p0.x13_lows, p0.look_front, p0.look_tail):
        assert "check_bounds" not in inspect.getsource(fn)
    callers = [n for n, fn in vars(p0).items() if inspect.isfunction(fn) and fn.__module__ == p0.__name__
               and "odc.check_bounds(" in inspect.getsource(fn)]
    assert callers == ["control_cg"]
    by_hour = {7: {"low_so_far": 50, "high_so_far": 55, "current_temp": 52}}
    assert odc.check_bounds(by_hour) == 1 and by_hour == {7: {"low_so_far": 50, "high_so_far": 55,
                                                              "current_temp": 52}}
    with pytest.raises(odc.OdcMetarRefused):
        odc.check_bounds({7: {"low_so_far": 65, "high_so_far": 64.94, "current_temp": 65}})


def _fake_marker(rodc, monkeypatch, name="look1", content=b'{"m": 1}\n'):
    (rodc / name).mkdir(parents=True, exist_ok=True)
    (rodc / name / p0.LOOK_STARTED).write_bytes(content)
    monkeypatch.setattr(p0, "LOOK1_MARKER_SHA256", hashlib.sha256(content).hexdigest())


def test_look2_guard_functional(tmp_path, monkeypatch):
    rodc, look2 = _roots(tmp_path, monkeypatch)
    assert p0.check_look2_guard()["look1_marker"] is None
    _fake_marker(rodc, monkeypatch)
    g = p0.check_look2_guard()
    assert g["look1_marker"].endswith("look_started.json") and g["look1_marker_sha256"] == p0.LOOK1_MARKER_SHA256
    (look2 / "l2" / "deeper").mkdir(parents=True)
    assert p0.check_look2_guard()                                   # a dir alone is not a look
    (look2 / "l2" / "deeper" / "look_anything.json").write_text("{}", encoding="utf-8")
    with pytest.raises(p0.Refused, match="no look3"):
        p0.check_look2_guard()


@pytest.mark.parametrize("case", ["receipt_in_look1", "second_marker", "changed_marker"])
def test_look2_guard_refuses_anything_but_look1s_marker_under_rodc(tmp_path, monkeypatch, case):
    rodc, _ = _roots(tmp_path, monkeypatch)
    _fake_marker(rodc, monkeypatch)
    if case == "receipt_in_look1":
        (rodc / "look1" / p0.LOOK_RECEIPT).write_text("{}", encoding="utf-8")
    elif case == "second_marker":
        (rodc / "lookx").mkdir()
        (rodc / "lookx" / p0.LOOK_STARTED).write_bytes(b'{"m": 1}\n')
    else:
        (rodc / "look1" / p0.LOOK_STARTED).write_bytes(b'{"m": 2}\n')
    with pytest.raises(p0.Refused, match="not look1's marker alone"):
        p0.check_look2_guard()
    with pytest.raises(p0.Refused):
        p0.begin_look(p0.LOOK2_ROOT / "l2", p0.LOOK2_APPROVAL)
    assert not p0.LOOK2_ROOT.exists()


def test_look_refuses_any_other_approval_before_any_guard_or_read(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("touched")
    for name in ("check_look2_guard", "check_out_dir", "look_front", "stage_guards"):
        monkeypatch.setattr(p0, name, boom)
    for approval in ("coordinator admission 2026-10-31", p0.LOOK2_APPROVAL + " ", p0.LOOK2_APPROVAL[:-1]):
        args = p0.build_parser().parse_args(["look", "--out", "x", "--coef", "c", "--coef-sha", "s", "--parity", "p",
                                             "--parity-sha", "q", "--approval", approval])
        with pytest.raises(p0.Refused, match="pinned look2 approval"):
            p0.stage_look(args)


def _names(fn):
    tree = ast.parse(inspect.getsource(fn).lstrip())
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}


def test_rehearsal_never_reaches_the_table_c_c_or_the_statistic(tmp_path, monkeypatch):
    from weather.calibration import mr_sweep as sw
    from weather.reporting.scorecards import dev_scorecard as sc

    forbidden = {"Table", "control_cc", "p0_candidate", "look_tail", "begin_look", "band_geometry", "write_look_rows",
                 "write_look_receipt", "eps_sensitivity", "wider_interval"}
    assert not (_names(p0.look_front) | _names(p0.stage_rehearse)) & forbidden
    rodc, look2 = _roots(tmp_path, monkeypatch)
    monkeypatch.setattr(p0, "REHEARSE_ROOT", tmp_path / "rodc-rehearse")

    def boom(*a, **k):
        raise AssertionError("the rehearsal reached the table / C-c / the statistic")
    monkeypatch.setattr(sc, "Table", boom)
    monkeypatch.setattr(sw, "p0_candidate", boom)
    for name in ("control_cc", "look_tail", "begin_look", "write_look_rows", "write_look_receipt"):
        monkeypatch.setattr(p0, name, boom)
    seen = {}

    def front(args, out, mark=None):
        seen.update(out=out, mark=mark)
        return {"gd": {"origin": {}, "code": {}, "blobs": {}, "rules": {}, "pin_identity": {}}, "after": {},
                "controls": {"C-g": {"verdict": "PASS", "frozen_raw_high_would_refuse": {}}},
                "feats": {"k": {"n_implausible": 2, "n_rows": 10}}, "reasons": {"ok": 1},
                "parity": {"parity_limited": {a: False for a in p0.ARMS}},
                "power_projection": {a: {"n_arm": 5, "power": 0.5} for a in p0.ARMS}, "dates": ["2026-10-01"],
                "dropped": 0, "hashed": {}, "malformed": [], "override": {}, "serve_override": {}}
    monkeypatch.setattr(p0, "look_front", front)
    out = tmp_path / "rodc-rehearse" / "r1"
    rc = p0.main(["rehearse-to-table", "--out", str(out), "--coef", "c", "--coef-sha", "s", "--parity", "p",
                  "--parity-sha", "q"])
    assert rc == 0 and seen == {"out": out, "mark": None}
    rec = json.loads((out / p0.REHEARSE_RECEIPT).read_text(encoding="utf-8"))
    assert rec["schema"] == p0.SCHEMA + "/rehearse" and rec["controls"]["C-g"]["verdict"] == "PASS"
    assert rec["power_projection_us10"][p0.ARM_X13] == {"n_arm": 5, "power": 0.5}
    assert rec["serve_rows_outside_frozen_30F_125F"] == {"count": 2, "kept_window_rows": 10}
    assert not list(tmp_path.rglob("look_*"))
    assert sorted(q.name for q in out.iterdir()) == [p0.REHEARSE_RECEIPT]
    assert p0.main(["rehearse-to-table", "--out", str(out), "--coef", "c", "--coef-sha", "s", "--parity", "p",
                    "--parity-sha", "q"]) == 2                       # an existing --out refuses
    assert p0.main(["rehearse-to-table", "--out", str(look2 / "r1"), "--coef", "c", "--coef-sha", "s", "--parity",
                    "p", "--parity-sha", "q"]) == 2                  # only below REHEARSE_ROOT


def test_look_tail_functional_on_a_synthetic_layout(tmp_path, monkeypatch):
    """Drives the real tail from sc.Table through rows.jsonl and look_receipt.json (synthetic layout, floors 1/1)."""
    from tests.reporting.test_released_window_served_market_blocks import write_layout

    from weather.calibration import mr_sweep as sw
    from weather.reporting.scorecards import dev_scorecard_data as data

    root = write_layout(tmp_path / "lay", date(2026, 8, 1), 12)
    lay = data.load_layout(root, data.DEV_FIRST, date(2026, 8, 12))
    man_sha = hashlib.sha256((root / data.MANIFEST).read_bytes()).hexdigest()
    for name, value in (("R80_LAYOUT", root), ("DEV_LAYOUT", root), ("R80_LAYOUT_MANIFEST_SHA256", man_sha),
                        ("DEV_LAYOUT_MANIFEST_SHA256", man_sha), ("MIN_DATES", 1), ("MIN_SNAPS", 1)):
        monkeypatch.setattr(p0, name, value)
    monkeypatch.setattr(sw, "MIN_DATES", sw.MIN_DATES)
    monkeypatch.setattr(sw, "MIN_SNAPS", sw.MIN_SNAPS)
    _, look2 = _roots(tmp_path, monkeypatch)
    out = p0.check_out_dir(look2 / "l2", look2)
    started = p0.begin_look(out, p0.LOOK2_APPROVAL)
    rng = np.random.default_rng(11)
    feats, coef = {}, {"arms": {a: {} for a in p0.ARMS}}
    for r in lay.snaps.itertuples(index=False):
        if int(r.local_hour) in p0.HOURS:
            feats[str(r.row_key)] = {"odc_low_so_far": float(rng.integers(55, 65)), "dewpoint_c": float(rng.integers(5, 15)),
                                     "x13_low_so_far": float(rng.integers(55, 65)),
                                     "low_prev_evening": float(rng.integers(55, 65))}
            for arm in p0.ARMS:
                cols = list(p0.arm_columns(arm, feats[str(r.row_key)]))
                coef["arms"][arm][f"{r.market}|{int(r.local_hour)}"] = {
                    "columns": cols, "beta": [0.3] * len(cols), "means": [60.0, 10.0, 60.0][:len(cols)]}
    dates = sorted(str(d) for d in lay.dates)
    ctx = {"gd": {"origin": {}, "code": {}, "blobs": {}, "rules": {}, "pin_identity": {}}, "after": {},
           "controls": {"C-e": {}, "C-g": {"verdict": "PASS", "scale": "wu_whole_f half_up on both sides"}},
           "lay": lay, "dates": dates, "feats": feats, "reasons": {"ok": len(feats)}, "coef": coef,
           "parity": {"parity_limited": {a: False for a in p0.ARMS}}, "cc_paths": {}, "serve_override": {},
           "power_projection": {}, "override": {}, "hashed": {}, "malformed": [], "dropped": 0,
           "look_started_sha": started, "look2_guard": {"look1_marker": None}}
    args = argparse.Namespace(approval=p0.LOOK2_APPROVAL, parity_sha="q" * 64, coef_sha="c" * 64)
    receipt = p0.look_tail(args, ctx, out)
    names = sorted(q.name for q in out.iterdir())
    assert names == sorted([p0.LOOK_STARTED, "rows.jsonl", p0.LOOK_RECEIPT])
    on_disk = json.loads((out / p0.LOOK_RECEIPT).read_text(encoding="utf-8"))
    assert on_disk["rows_sha256"] == hashlib.sha256((out / "rows.jsonl").read_bytes()).hexdigest()
    assert on_disk["look_started_sha256"] == started and on_disk["controls"]["C-c"]["verdict"] == "PASS"
    assert on_disk["clarification_3"]["look1_refusal_log_sha256"] == p0.LOOK1_REFUSAL_LOG_SHA256
    assert on_disk["clarification_3"]["approval_pinned"] == p0.LOOK2_APPROVAL
    for arm in p0.ARMS:
        e = receipt["arms"][arm]
        assert e["label"] and "eps_sensitivity" in e and "bh" in e and e["covered_snapshots"] > 0
    with pytest.raises(p0.Refused, match="no look3"):
        p0.check_look2_guard()
