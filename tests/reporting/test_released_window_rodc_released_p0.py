"""R-ODC-lin / X13 released-cell P0 driver (ledger row 103): guards, fit math, features, D3 and labels.

Synthetic inputs only, except two read-only pins of the run tree (the imported blobs and the rule files) and,
when the archive is present, control C-d on row 80's archived rows. No r80 layout, export, label or price is read.
"""
from __future__ import annotations

import ast
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
    assert set(p0.check_rule_files()) == {p0.RULE_PATH, p0.CLARIFICATION_PATH}


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
    monkeypatch.setattr(p0, "check_out_dir", lambda out: p0.Path(out))
    monkeypatch.setattr(p0, "check_no_prior_look", lambda: True)
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
                  ["--coef-sha", coef_sha, "--parity", str(par), "--parity-sha", par_sha]):   # C-c unruled
        rc = p0.main(base + extra + ["--approval", "coordinator admission 2026-10-31"])
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
    assert f["x13_low_so_far"] == 56.6 and f["low_prev_evening"] == 55.0
    rodc = p0.arm_columns(p0.ARM_RODC, f)
    x13 = p0.arm_columns(p0.ARM_X13, f)
    assert rodc == {"low_so_far": 57, "dewpoint_c": 52}
    assert x13 == {"low_so_far": 56.6, "low_prev_evening": 55.0, "dewpoint_c": 52}
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


def test_ruling_2_cc_call_paths_are_recorded_and_differ_so_the_look_refuses_until_ruled():
    audit = p0.cc_path_audit()
    assert audit["candidate"]["function"] == "mr_sweep.tilt"
    assert audit["placebo"]["function"] == "mr_sweep.disagreement_placebo"
    assert audit["candidate"]["renormalised_to_sum_m"] and audit["placebo"]["renormalised_to_sum_m"]
    assert audit["candidate"]["clip_to_eps"] is False and audit["placebo"]["clip_to_eps"] is True
    assert audit["identical_clip_and_renormalisation"] is False
    with pytest.raises(p0.Refused, match="awaiting master"):
        p0.check_cc_paths()
    assert p0.check_cc_paths(ruling="a master ruling ref")["ruling"] == "a master ruling ref"


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

    f = tmp_path / "parity_receipt.json"
    f.write_text(json.dumps({"schema": p0.SCHEMA + "/parity", "ledger_row": p0.LEDGER_ROW,
                             "parity_limited": limited}), encoding="utf-8")
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    assert p0.check_parity(f, sha)["parity_limited"] == limited
    for path, s, msg in ((tmp_path / "none.json", sha, "missing"), (f, None, "required"), (f, "0" * 64, "is not")):
        with pytest.raises(p0.Refused, match=msg):
            p0.check_parity(path, s)
    f.write_text(json.dumps({"schema": "other", "ledger_row": p0.LEDGER_ROW, "parity_limited": limited}))
    with pytest.raises(p0.Refused, match="not this row"):
        p0.check_parity(f, hashlib.sha256(f.read_bytes()).hexdigest())


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
    assert r["serve"] == {"odc_low_so_far": 57, "x13_low_so_far": 56.6, "low_prev_evening": 55.0}
    assert r["implausible"] == 1 and r["kept_rows"] == 4          # the 25 F row is dropped by the filter
    part.write_bytes(part.read_bytes() + b"{}\n")
    with pytest.raises(p0.Refused, match="manifest"):
        p0.read_metar_history(tmp_path / "metar", "klga", {(2024, 10)})
    late = {"market_id": "nyc", "hours": {"9": [{"date": "2026-01-02", "low_so_far": 1.0}]}}
    with pytest.raises(p0.Refused, match="after 2025-12-31"):
        p0.parity_records([late], {"nyc": by_date}, {"nyc": NY}, {"nyc": "F"}, hours=(9,))


def test_parity_cli_defaults():
    args = p0.build_parser().parse_args(["parity", "--out", r"C:\t\l16\rodc\parity1"])
    assert args.cache_dir == str(p0.L9_CACHE) and args.metar_dir == str(p0.METAR_HISTORY)
