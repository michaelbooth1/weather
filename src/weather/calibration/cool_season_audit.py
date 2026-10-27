r"""Lane L3, CS-1: cool-season transfer audit of the frozen MG-2/MG-3 parts. History only, descriptive.

Rule ``C:/t/l3/coolseason/rule_cs.md`` (sha pinned below). Every part is scored AS FROZEN (no refit) on
Oct-Dec 2021-25 and on its Aug-Sep 2021-25 self-score (in-sample for the HGB and P3d fits), against the MG-1
analogue (normal(NBM mean, max(sd, 1)), floored). Nothing dated after 2026-09-29 is read and no 2026 row is
scored. No binding changes. Research only; outputs outside the repository, write-once.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

RULE_CS_SHA256 = "ac9c74332876c53a7e721b1acf6b3abaf692e45592d68d022c4a432210b71f30"
L6_STATE_SHA256 = "0e89b32dbf91c8cdf7ecd3a8e99da84be91c51342c646f0c0cf6c2720e627988"
MG2_COEF_SHA256 = "4bc51e031ce10862d44ffdc57a6a6ca92bd46d98412bfc0e087b681a01b0c398"
P3D_N_STATE_SHA256 = "dff5d7975fa7a18278f8e500e4e0bcdd768c5d05dc4caf8b8e08332dad1a6574"
AUG_SEP_CENTRES = ("2026-08-08", "2026-08-23", "2026-09-07", "2026-09-22")
OCT_DEC_CENTRES = ("2026-10-10", "2026-10-25", "2026-11-09", "2026-11-24", "2026-12-09")
HOURS_0712 = (7, 8, 9, 10, 11, 12)
HOURS_1316 = (13, 14, 15, 16)
YEARS = (2021, 2022, 2023, 2024, 2025)
PERIODS = (("aug_sep_in_sample", (8, 9)), ("oct", (10,)), ("nov", (11,)), ("dec_partial", (12,)),
           ("oct_dec", (10, 11, 12)))
SEED = 20261026
EXCLUDED_STATIONS = ("CYYZ",)


class CoolSeasonError(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pin(path, pinned, what):
    got = _sha(path)
    if got != pinned:
        raise CoolSeasonError(f"{what} {path}: sha256 {got} != pinned {pinned}")
    return got


def check_rule(rule):
    return _pin(rule, RULE_CS_SHA256, "rule")


def _outside_repo(path):
    """Research output never lands in the repository (the same check as L2's ``require_output_outside_repo``)."""
    from weather.paths import REPO_ROOT

    resolved = Path(path).resolve()
    repo = Path(REPO_ROOT).resolve()
    if resolved == repo or repo in resolved.parents:
        raise CoolSeasonError(f"output must be outside the repository: {resolved}")
    return resolved


def _write_once(path, payload):
    path = _outside_repo(Path(path))
    if path.exists():
        raise CoolSeasonError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return path


def brier_from_dist(dist, y):
    """sum_k p_k^2 - 2 p_y + 1 over integer buckets (the label need not be in the support)."""
    return sum(p * p for p in dist.values()) - 2.0 * dist.get(int(y), 0.0) + 1.0


# ---------------------------------------------------------------- comparisons

def compare(frame, arm_col, base_col, hours, periods=PERIODS):
    """dB tables by period x {pooled, hour}, plus per market / per year for oct_dec and aug_sep."""
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz

    ok = np.isfinite(frame[arm_col].to_numpy(float)) & np.isfinite(frame[base_col].to_numpy(float))
    f = frame[ok].reset_index(drop=True)
    num = (f[arm_col] - f[base_col]).to_numpy(float)
    den = f[base_col].to_numpy(float)
    dates = f.local_date.astype(str).to_numpy()
    markets = f.market.astype(str).to_numpy()
    month = f.month.to_numpy(int)
    hour = f.hour.to_numpy(int)
    year = f.year.to_numpy(int)
    out = {}
    for name, months in periods:
        pm = np.isin(month, months)
        masks = {"pooled": pm}
        masks.update({f"h{h:02d}": pm & (hour == h) for h in hours})
        res = rz._cell_ratio(dates, markets, num, den, masks, SEED)
        for k, v in res.items():
            sel = masks[k]
            v["brier_part"] = float(f[arm_col].to_numpy(float)[sel].mean())
            v["brier_mg1"] = float(den[sel].mean())
        entry = {"by": res}
        if name in ("aug_sep_in_sample", "oct_dec"):
            entry["per_market"] = {m: rz._cell_ratio(dates, markets, num, den, {"x": pm & (markets == m)}, SEED).get("x")
                                   for m in sorted(set(markets))}
            entry["per_year"] = {str(y): rz._cell_ratio(dates, markets, num, den, {"x": pm & (year == y)}, SEED).get("x")
                                 for y in YEARS}
        out[name] = entry
    a = out.get("aug_sep_in_sample", {}).get("by", {}).get("pooled")
    o = out.get("oct_dec", {}).get("by", {}).get("pooled")
    reading = None
    if a and o:
        if a["ci95"][1] is not None and a["ci95"][1] < 0 and o["ci95"][0] is not None and o["ci95"][0] >= 0:
            reading = "does not transfer"
        elif o["estimate"] > a["estimate"] + 0.5 * abs(a["estimate"]):
            reading = "weakens"
        else:
            reading = "transfers"
    return {"rows_compared": int(ok.sum()), "rows_without_comparator": int((~ok).sum()), "periods": out,
            "transfer_reading": reading}


# ---------------------------------------------------------------- 07-12: L6 stack

def l6_rows(research_root, nbm_corpus):
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz
    from weather.calibration import upstream_obs_screen as l6

    obs, sel, prov = l6.load(research_root)
    if prov["obs_sha256"] != rz.OBS_SHA256:
        raise CoolSeasonError(f"L6 obs sha {prov['obs_sha256']} != {rz.OBS_SHA256}")
    nbm = rz.load_nbm_with_sd([nbm_corpus])
    frames = []
    import pandas as pd

    for code, icao in enumerate(l6.stations(sel)):
        m = sel[icao]
        g, dmax = l6.market_series(obs, icao, m["timezone"])
        dates = [d for d in dmax.index if "2021-01-01" <= d <= "2025-12-31" and int(d[5:7]) >= 8]
        q = rz.history_queries(dates, m["timezone"], HOURS_0712)
        f = l6.features(q, obs, m, icao, m["timezone"], code, g, dmax)
        f["station"], f["local_date"], f["hour"] = icao, q.local_date, q.hour
        f["market"] = m["market"]
        f["dmax"] = q.local_date.map(dmax).to_numpy(float)
        got = [rz.nbm_at(nbm, m["market"], d, int(h), m["timezone"]) for d, h in zip(q.local_date, q.hour)]
        f["v"] = [x[0] for x in got]
        f["s"] = [x[1] for x in got]
        frames.append(f)
    out = pd.concat(frames, ignore_index=True)
    out = out[np.isfinite(out.r) & np.isfinite(out.t) & np.isfinite(out.dmax)].reset_index(drop=True)
    out = out[~out.station.isin(EXCLUDED_STATIONS)].reset_index(drop=True)
    out["year"] = out.local_date.str[:4].astype(int)
    out["month"] = out.local_date.str[5:7].astype(int)
    if (out.local_date > "2025-12-31").any():
        raise CoolSeasonError("an L6 history row is after 2025")
    return out, prov


def score_l6(frame, l6_state_path, coef_path):
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz
    from weather.model import mg_serve_core as core

    state = core.load_l6_own_state(l6_state_path, L6_STATE_SHA256)
    _pin(coef_path, MG2_COEF_SHA256, "MG-2 coefficients")
    coef = json.loads(Path(coef_path).read_text(encoding="utf-8"))["l6_stack"]["coef"]
    n = core.l6_own_nowcast(state, frame)
    v, s = frame.v.to_numpy(float), frame.s.to_numpy(float)
    hours = frame.hour.to_numpy(int)
    mu = v.copy()
    for h, (a, b, _) in coef.items():
        sel = (hours == int(h)) & np.isfinite(n) & np.isfinite(v)
        mu[sel] = v[sel] + a + b * (n[sel] - v[sel])
    ok = np.isfinite(v) & np.isfinite(s)
    R, dmax = frame.r.to_numpy(float), frame.dmax.to_numpy(float)
    sig = np.maximum(s, 1.0)
    part = np.full(len(frame), np.nan)
    base = np.full(len(frame), np.nan)
    part[ok] = rz.bucket_brier(mu[ok], sig[ok], R[ok], dmax[ok])
    base[ok] = rz.bucket_brier(v[ok], sig[ok], R[ok], dmax[ok])
    out = frame[["market", "local_date", "hour", "year", "month"]].copy()
    out["part"], out["mg1"] = part, base
    rmse = {}
    for name, months in PERIODS:
        pm = np.isin(frame.month.to_numpy(int), months) & np.isfinite(n)
        rmse[name] = {"n": int(pm.sum()), "rmse_nowcast_vs_dmax": float(np.sqrt(np.mean((n[pm] - dmax[pm]) ** 2))),
                      "rmse_mu_vs_dmax": float(np.sqrt(np.nanmean((mu[pm & ok] - dmax[pm & ok]) ** 2))),
                      "rmse_nbm_vs_dmax": float(np.sqrt(np.nanmean((v[pm & ok] - dmax[pm & ok]) ** 2))),
                      "mean_nbm_error": float(np.nanmean(v[pm & ok] - dmax[pm & ok])),
                      "mean_mu_error": float(np.nanmean(mu[pm & ok] - dmax[pm & ok]))}
    return out, {"coef": coef, "rmse": rmse, "l6_state_sha256": L6_STATE_SHA256, "coef_sha256": MG2_COEF_SHA256}


# ---------------------------------------------------------------- 13-16: P3d_N from L2's records

def load_records(records_root, market, centre):
    path = Path(records_root) / f"records_{market}_{centre}.pkl.gz"
    if not path.exists():
        return None, None
    with gzip.open(path, "rb") as handle:
        payload = pickle.load(handle)
    return payload, _sha(path)


def record_rows(records_root, nbm_corpus, hours=HOURS_1316):
    import pandas as pd

    from weather.calibration import ols_floor_ladder as lad
    from weather.calibration import rz_hrrr_spread as rz
    from weather.market.market_registry import spec_for_id
    from weather.model.mg_serve_core import R0_MARKETS

    nbm = rz.load_nbm_with_sd([nbm_corpus])
    rows, shas, missing = [], {}, []
    for market in R0_MARKETS:
        tz = spec_for_id(market).timezone
        for centre in AUG_SEP_CENTRES + OCT_DEC_CENTRES:
            payload, sha = load_records(records_root, market, centre)
            if payload is None:
                missing.append(f"{market}_{centre}")
                continue
            shas[f"{market}_{centre}"] = sha
            for hour, recs in payload["records"].items():
                if int(hour) not in hours:
                    continue
                for rec in recs:
                    day = str(rec["target_date"])[:10]
                    if not "2021-01-01" <= day <= "2025-12-31":
                        raise CoolSeasonError(f"record outside 2021-25: {market} {centre} {day}")
                    value, cycle = lad.nbm_at_cutoff(nbm, market, day, int(hour), tz)
                    mean, sd = (value if value is not None else (None, None))
                    fh = rec.get("forecast_high")
                    rows.append({"market": market, "centre": centre, "local_date": day, "hour": int(hour),
                                 "y": float(rec["final_bucket"]), "F": rec.get("high_so_far"),
                                 "current_temp": rec.get("current_temp"),
                                 "nbm_mean": mean if mean is not None else fh,
                                 "nbm_imputed": mean is None, "v": mean, "s": sd, "nbm_cycle": cycle})
    frame = pd.DataFrame(rows)
    frame = frame.drop_duplicates(["market", "local_date", "hour"]).reset_index(drop=True)
    frame["year"] = frame.local_date.str[:4].astype(int)
    frame["month"] = frame.local_date.str[5:7].astype(int)
    return frame, shas, missing


def score_p3d(frame, state, extra=None):
    """Frozen-state serve math per row; ``extra`` (P3d_H) is a callable row -> list of extra HGB values."""
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz
    from weather.model import mg_serve_core as core

    part = np.full(len(frame), np.nan)
    stats = Counter()
    for i, r in enumerate(frame.itertuples(index=False)):
        F, ct, nm = (float(x) if x is not None and x == x else float("nan") for x in (r.F, r.current_temp, r.nbm_mean))
        if not (math.isfinite(F) and math.isfinite(ct)):
            stats["no_obs"] += 1
            continue
        kw = dict(market=r.market, target_date=date.fromisoformat(r.local_date), high_so_far=F, current_temp=ct,
                  nbm_mean=nm)
        if extra is None:
            dist = core.state_distribution(state, r.hour, **kw)
        else:
            ex = extra(r)
            if ex is None:
                stats["no_extra"] += 1
                continue
            dist = p3dh_distribution(state, r.hour, ex, **kw)
        part[i] = brier_from_dist(dist, r.y)
        stats["scored"] += 1
    v = np.array([np.nan if x is None else x for x in frame.v], float)
    s = np.array([np.nan if x is None else x for x in frame.s], float)
    F = np.array([np.nan if x is None else x for x in frame.F], float)
    ok = np.isfinite(v) & np.isfinite(s) & np.isfinite(F)
    base = np.full(len(frame), np.nan)
    base[ok] = rz.bucket_brier(v[ok], np.maximum(s[ok], 1.0), F[ok], frame.y.to_numpy(float)[ok])
    out = frame[["market", "local_date", "hour", "year", "month"]].copy()
    out["part"], out["mg1"] = part, base
    return out, dict(stats)


def p3dh_distribution(state, hour, extra_values, **inputs):
    """P3d_H serve math (rule_mg3_p3dh_state.md section 2): the P3d_N math with ``extra_hgb`` appended to X."""
    import numpy as np

    from weather.model import mg_serve_core as core

    X, mu0, g, floor = core.state_features(state, hour, **inputs)
    X = np.column_stack([X, np.asarray([extra_values], float)])
    entry = state["hours"][int(hour)]
    mean = entry["mean"]
    yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ mean["ols"] + mean["hgb"].predict(X))[0])
    c = state["constants"]
    s = max(c["min_scale"], float(entry["scale"].predict(np.column_stack([X, [yhat - floor]]))[0]) * math.sqrt(math.pi / 2))
    p_clim = core.smoothed_dist(entry["train_y"][inputs["market"]], state["buckets"][inputs["market"]],
                                alpha=c["clim_alpha"])
    return core.predictive_distribution(yhat, s, floor, entry["z"], state["buckets"][inputs["market"]], p_clim)


def load_state(path, sha):
    blob = Path(path).read_bytes()
    got = hashlib.sha256(blob).hexdigest()
    if got != sha:
        raise CoolSeasonError(f"state {path}: sha256 {got} != bound {sha}")
    return pickle.loads(blob)


# ---------------------------------------------------------------- 1b: P3d_H 13-16 (L2's MG-3 state)

HRRR_1316_SHAS = {"manifest.jsonl": "409f6f917f2bca2999ebf39c52440c673760356295aaa291f572bfe624269935",
                  "selections.jsonl": "055add5a4a2aa25483f70ee6c355562d4730e8b01daa1f8b56adb5788512ec75",
                  "stations.json": "52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3"}
P3DH_EXTRA = ("k_max", "k_gap", "k_tcdc")
RK_VARIABLES = {"TMP": "TMP:2 m above ground", "TCDC": "TCDC:entire atmosphere"}
RK_VALID_END_LOCAL = 17
RK_MARGIN_S = 10 * 60
RK_TMP_RANGE_F = (-60.0, 130.0)


def _json_lines(path, stats, name):
    with open(path, "rb") as handle:
        for line in handle:
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    stats[f"{name}_corrupt_line"] += 1


def hrrr_k_columns(corpus_dir, markets, hours=HOURS_1316, point=None, months=None, skip_after=None):
    """R-K raw path (a read-only copy of L2's ``rk_hrrr_columns``): ``point=None`` reads the nearest cell (R-K,
    13-16); a {icao: block index} map reads ``block3x3[index]`` (RN-1, 07-12), and a station absent from the map
    is a miss (``no_land_cell``). ``months``: keep only selections whose local month is listed. ``skip_after``:
    selections dated after it are not read (a corpus that also holds 2026 dev days); otherwise one after 2025
    refuses the run.
    -> {(market, local_date, hour): {k_max, k_tcdc, k_miss, reason}} plus counts. Inputs only."""
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    corpus = Path(corpus_dir)
    stats = Counter()
    stations = json.loads((corpus / "stations.json").read_bytes())
    icao_market = {icao: s["market"] for icao, s in stations.items() if s.get("market") in markets}
    tzs = {icao: ZoneInfo(stations[icao]["tz"]) for icao in icao_market}
    messages, mismatched = {}, set()
    for m in _json_lines(corpus / "manifest.jsonl", stats, "manifest"):
        record = str(m.get("idx_record") or "")
        var = next((v for v, prefix in RK_VARIABLES.items() if record.startswith(prefix + ":")), None)
        if var is None:
            continue
        cycle, fh = datetime.fromisoformat(m["cycle_utc"]), int(m["fh"])
        key = (cycle, fh, var)
        want = f"hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf{fh:02d}.grib2"
        if m.get("key") != want or record != f"{RK_VARIABLES[var]}:{fh} hour fcst:":
            stats["manifest_identity_mismatch"] += 1
            mismatched.add(key)
            continue
        values = {}
        for icao, cell in (m.get("points") or {}).items():
            if icao not in icao_market:
                continue
            cell = cell or {}
            if point is None:
                values[icao] = cell.get("nearest")
            elif icao in point:
                block = cell.get("block3x3")
                values[icao] = block[point[icao]] if isinstance(block, list) and len(block) == 9 else None
        if key in messages:
            if messages[key] != values:
                stats["manifest_duplicate_conflict"] += 1
                mismatched.add(key)
            continue
        messages[key] = values
    out = {}
    for s in _json_lines(corpus / "selections.jsonl", stats, "selections"):
        icao = s.get("station")
        if icao not in icao_market:
            continue
        market, day, hour = icao_market[icao], str(s["local_date"]), int(s["hour_local"])
        if hour not in hours or (market, day, hour) in out:
            continue
        if months is not None and int(day[5:7]) not in months:
            continue
        if skip_after is not None and day > skip_after:
            stats["skipped_after"] += 1
            continue
        if day > "2025-12-31":
            raise CoolSeasonError(f"HRRR selection after 2025: {market} {day}")
        tz, target = tzs[icao], date.fromisoformat(day)
        snapshot = datetime.combine(target, time(hour, 0), tzinfo=tz)
        window_end = datetime.combine(target, time(RK_VALID_END_LOCAL, 0), tzinfo=tz)
        fhs = list(s.get("fhs") or [])
        entry = {"k_max": float("nan"), "k_tcdc": float("nan"), "k_miss": 1.0, "reason": None,
                 "cycle_present": s.get("cycle_utc") is not None and bool(fhs)}
        out[(market, day, hour)] = entry
        if point is not None and icao not in point:
            entry["reason"] = "no_land_cell"
        elif datetime.fromisoformat(s["snapshot_utc"]) != snapshot:
            entry["reason"] = "snapshot_mismatch"
        elif s.get("cycle_utc") is None or not fhs:
            entry["reason"] = "no_cycle"
        else:
            cycle = datetime.fromisoformat(s["cycle_utc"])
            latest = s.get("latest_available_utc")
            valid = [cycle + timedelta(hours=int(fh)) for fh in fhs]
            if latest is None or datetime.fromisoformat(latest) + timedelta(seconds=RK_MARGIN_S) > snapshot:
                entry["reason"] = "pit_violation"
            elif min(valid) < snapshot or max(valid) > window_end:
                entry["reason"] = "window_violation"
            else:
                tmp, tcdc = [], []
                for fh in fhs:
                    for var, sink in (("TMP", tmp), ("TCDC", tcdc)):
                        k = (cycle, int(fh), var)
                        if k in mismatched:
                            entry["reason"] = "identity_mismatch"
                        v = messages.get(k, {}).get(icao)
                        sink.append(float("nan") if v is None else float(v))
                if entry["reason"] is None:
                    if not all(math.isfinite(v) for v in tmp + tcdc):
                        entry["reason"] = "message_absent"
                    else:
                        tmp_f = [(v - 273.15) * 9.0 / 5.0 + 32.0 for v in tmp]
                        if min(tmp_f) < RK_TMP_RANGE_F[0] or max(tmp_f) > RK_TMP_RANGE_F[1]:
                            entry["reason"] = "tmp_out_of_range"
                        else:
                            entry.update(k_max=max(tmp_f), k_tcdc=sum(tcdc) / len(tcdc), k_miss=0.0)
        stats["covered" if entry["k_miss"] == 0.0 else f"miss_{entry['reason']}"] += 1
    return out, dict(stats)


def k_extra(entry, nbm_mean):
    """[k_max, k_gap, k_tcdc] (R-K ``rk_columns``); NaN on a miss (the HGB takes NaN, as L2's serve does)."""
    if entry is None or entry["k_miss"]:
        return [float("nan")] * 3
    nm = float("nan") if nbm_mean is None else float(nbm_mean)
    return [entry["k_max"], entry["k_max"] - nm if math.isfinite(nm) else float("nan"), entry["k_tcdc"]]


def bind_l2_state(state_dir):
    """L2's 1a state: control.json must PASS; its state_sha256 must equal the sidecar's and the file's."""
    d = Path(state_dir)
    control = json.loads((d / "control.json").read_text(encoding="utf-8"))
    if control.get("pass") is not True:
        raise CoolSeasonError(f"L2 control {d / 'control.json'} does not PASS; (1b) not scorable")
    sidecar = json.loads((d / "p3d_h_state.json").read_text(encoding="utf-8"))
    sha = control.get("state_sha256")
    if not sha or sidecar.get("state_sha256") != sha:
        raise CoolSeasonError("L2 control and sidecar state sha256 differ")
    state = load_state(d / "p3d_h_state.pkl", sha)
    if tuple(state.get("extra_hgb") or ()) != P3DH_EXTRA:
        raise CoolSeasonError(f"L2 state extra_hgb {state.get('extra_hgb')} != {P3DH_EXTRA}")
    return state, sha, _sha(d / "control.json")


def part1b(*, nbm_corpus, records_root, state_1316, hrrr_1316, rule, out_path):
    check_rule(rule)
    _pin(nbm_corpus, "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd", "NBM corpus")
    for name, sha in HRRR_1316_SHAS.items():
        _pin(Path(hrrr_1316) / name, sha, f"HRRR 13-16 {name}")
    state, state_sha, control_sha = bind_l2_state(state_1316)
    recf, shas, missing = record_rows(records_root, nbm_corpus)
    hrrr, hstats = hrrr_k_columns(hrrr_1316, set(recf.market))
    keys = list(zip(recf.market, recf.local_date, recf.hour.astype(int)))
    recf["hrrr_covered"] = [hrrr.get(k) is not None and not hrrr[k]["k_miss"] for k in keys]
    p3s, p3stats = score_p3d(recf, state, extra=lambda r: k_extra(hrrr.get((r.market, r.local_date, int(r.hour))),
                                                                  r.nbm_mean))
    cmp = compare(p3s, "part", "mg1", HOURS_1316)
    payload = {
        "label": "CS-1 (1b) cool-season transfer audit, history only, descriptive: L2's frozen MG-3 P3d_H 13-16 "
                 "(control PASS, sha-bound) vs the MG-1 analogue; Aug-Sep is IN-SAMPLE; Oct-Dec rows are never "
                 "training rows but share the training years 2021-25; no binding change",
        "rule_sha256": RULE_CS_SHA256, "module_sha256": _sha(__file__),
        "p3d_h_1316": dict(cmp, rows=int(len(recf)), stats=p3stats, state_sha256=state_sha,
                           l2_control_sha256=control_sha, hrrr_stats=hstats,
                           hrrr_covered_by_period={n: [int(recf.hrrr_covered[recf.month.isin(m)].sum()),
                                                       int(recf.month.isin(m).sum())] for n, m in PERIODS},
                           records_missing=missing, records_sha256=shas),
        "p3d_h_0712": "NOT SCORABLE on Oct-Dec: no HRRR 07-12 for Oct-Dec in L13's corpus (coverage.json)",
        "blend_l6_h_0712": "NOT SCORABLE on Oct-Dec: its P3d_H 07-12 input has no Oct-Dec HRRR (coverage.json)"}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- clarification 2026-10-27 (1c and row 49 scope)

CLARIFIED_YEARS = (2024, 2025)  # L13's sealed 07-12 backfill holds Oct-Dec of 2024 and 2025 only


def oct_dec_scope(frame, backfill):
    """Clarification 2026-10-27 (CS-1 rule section 1: scored only where complete inputs exist): an Oct-Dec row is
    kept only if its year is 2024 or 2025 AND the backfill has a selection with a cycle for its key. 2021-23
    Oct-Dec rows are dropped before any scorer (never served, never scored, not even reported-only); a no-cycle
    or absent key is absent, never imputed. Aug-Sep rows are untouched. -> (kept frame, counts)."""
    import numpy as np

    keys = list(zip(frame.market, frame.local_date, frame.hour.astype(int)))
    od = frame.month.isin(OCT_DEC).to_numpy()
    yr = frame.year.isin(CLARIFIED_YEARS).to_numpy()
    entry = [backfill.get(k) for k in keys]
    has_sel = np.array([e is not None for e in entry])
    cyc = np.array([e is not None and bool(e.get("cycle_present")) for e in entry])
    keep = ~od | (yr & cyc)
    counts = {"oct_dec_rows_read": int(od.sum()), "oct_dec_2021_23_not_scored": int((od & ~yr).sum()),
              "oct_dec_2024_25_no_cycle_absent": int((od & yr & has_sel & ~cyc).sum()),
              "oct_dec_2024_25_no_selection_absent": int((od & yr & ~has_sel).sum()),
              "oct_dec_kept": int((od & keep).sum()), "aug_sep_rows": int((~od).sum())}
    return frame[keep].reset_index(drop=True), counts


def guard_scope(frame):
    """No Oct-Dec 2021-23 row may reach a scorer (clarification 2026-10-27, term c)."""
    bad = frame.month.isin(OCT_DEC) & ~frame.year.isin(CLARIFIED_YEARS)
    if bad.any():
        raise CoolSeasonError(f"{int(bad.sum())} Oct-Dec 2021-23 rows reached a scorer")


def key_set_sha(frame):
    keys = sorted(f"{m}|{d}|{int(h)}" for m, d, h in zip(frame.market, frame.local_date, frame.hour))
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest(), len(keys)


def pair_keys(scored, cols):
    """Paired keys (term a): a row counts only where EVERY arm and comparator in ``cols`` is finite; elsewhere all
    are set NaN, so every comparison runs on one key set. -> {scope: {sha256, rows}}."""
    import numpy as np

    ok = np.ones(len(scored), bool)
    for c in cols:
        ok &= np.isfinite(scored[c].to_numpy(float))
    for c in cols:
        scored.loc[~ok, c] = np.nan
    kept = scored[ok]
    out = {}
    for name, months in (("all", AUG_SEP + OCT_DEC), ("aug_sep", AUG_SEP), ("oct_dec", OCT_DEC)):
        sha, n = key_set_sha(kept[kept.month.isin(months)])
        out[name] = {"sha256": sha, "rows": n}
    out["unpaired_rows_dropped"] = int((~ok).sum())
    return out


def headline(cmp, keys):
    """Term b: the Oct-Dec pooled dB with its reduced N, its date-cluster count and its key-set sha."""
    pooled = cmp["periods"]["oct_dec"]["by"].get("pooled") or {}
    return {"oct_dec_2024_25_pooled": {k: pooled.get(k) for k in ("estimate", "ci95", "n_rows", "n_cells", "n_dates")},
            "key_set_oct_dec": keys["oct_dec"], "transfer_reading": cmp.get("transfer_reading")}


# ---------------------------------------------------------------- 1c: P3d_H 07-12 and blend_l6_H (L2's MG-3)

HRRR_0712_SHAS = {"manifest.jsonl": "fef6c307a411e6373af05830b55c4dff8cb23d08f46e18f07949821f08fe88e6",
                  "selections.jsonl": "31bd3d3a7c6456df657e8f99b763a06a80bc41772881f67dc7eeaf5dee1f4e67",
                  "days.jsonl": "34af53b0e276c541605e3e93a57018619ddf0895f92f07add5c835901fd3515e",
                  "stations.json": "52e8bb5f22513828cb5edbfc16b77afb293cfcb9df62a92abd4db30ab7a0abe3"}
P3DH_0712_STATE_SHA256 = "e92764773e1614aae548ccfd74b3a60740f25105578abd045b0808fe6dd159c0"
BLEND_WEIGHTS_SHA256 = "c7b8ebc08d31ca30e5289d453ec2260bcc6659b32b379410f58b0d2b9b03530a"
L6_PART_SHA256 = "07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9"
L6_DEV_NOWCASTS_SHA256 = "3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3"
RN1_LAND_SHA256 = "22069beebb5609755b35621bac05e91a1b35e434670c993a93a8aca9434fd7d6"
RN1_LAND_MSG_SHA256 = "10c7fb85ac10616ca3f45295d945002ab5da437054736748f6746dd01b0e7c29"
RN1_LAND_KEY = "hrrr.20250801/conus/hrrr.t00z.wrfsfcf00.grib2"
RN1_EXPECTED_INDEX = {"KSFO": 3}  # every other station is the centre cell (4)
SUMS_REQUIRED = ("manifest.jsonl", "selections.jsonl", "stations.json")
AUG_SEP, OCT_DEC = (8, 9), (10, 11, 12)


def rn1_point_map(land_path, corpus_dir, markets):
    """RN-1 land point rule (a read-only copy of L2's ``rr_point_rule``) -> ({icao: block index}, report).

    Refused unless the land file is the registered LAND:surface message, its stations_json_sha256 equals the
    corpus's stations.json, the block distances and the chosen index recompute, and the index equals the
    registered reading (KSFO 3, every other station 4).
    """
    _pin(land_path, RN1_LAND_SHA256, "RN-1 land file")
    land = json.loads(Path(land_path).read_bytes())
    stations_sha = _sha(Path(corpus_dir) / "stations.json")
    if land.get("stations_json_sha256") != stations_sha:
        raise CoolSeasonError(f"land stations_json_sha256 {land.get('stations_json_sha256')} != {stations_sha}")
    if land.get("msg_sha256") != RN1_LAND_MSG_SHA256 or land.get("key") != RN1_LAND_KEY:
        raise CoolSeasonError("land file is not the registered LAND:surface message")
    stations = json.loads((Path(corpus_dir) / "stations.json").read_bytes())
    point, report = {}, {}
    for icao, s in sorted(stations.items()):
        if s.get("market") not in markets:
            continue
        cell = land["stations"][icao]
        if (cell["i"], cell["j"], cell["fi"], cell["fj"]) != (s["i"], s["j"], s["fi"], s["fj"]):
            raise CoolSeasonError(f"{icao}: land grid position differs from stations.json")
        mask = cell["land_block3x3"]
        dist = []
        for k in range(9):
            dj, di = divmod(k, 3)
            dist.append(math.hypot(s["i"] + di - 1 - s["fi"], s["j"] + dj - 1 - s["fj"]))
        if max(abs(a - b) for a, b in zip(dist, cell["dist_grid_units"])) > 1e-9:
            raise CoolSeasonError(f"{icao}: block ordering does not reproduce the stored distances")
        land_cells = [k for k in range(9) if mask[k] == 1]
        chosen = min(land_cells, key=lambda k: (dist[k], k)) if land_cells else None
        if chosen != cell.get("rn1_chosen_index") or chosen != RN1_EXPECTED_INDEX.get(icao, 4):
            raise CoolSeasonError(f"{icao}: RN-1 index {chosen} differs from the land file or the registered reading")
        point[icao] = chosen
        report[icao] = {"market": s["market"], "chosen_index": chosen, "n_land": len(land_cells),
                        "chosen_dist_grid": dist[chosen]}
    return point, {"land_sha256": RN1_LAND_SHA256, "stations_json_sha256": stations_sha, "stations": report}


def bind_sha256sums(corpus_dir, sums_sha256):
    """The sealed backfill: SHA256SUMS must hash to the forwarded seal sha, list every required file, and every
    listed file must hash to its line. -> {name: sha256}."""
    d = Path(corpus_dir)
    _pin(d / "SHA256SUMS", sums_sha256, "backfill SHA256SUMS")
    listed = {}
    for line in (d / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip().lstrip("*").replace("\\", "/")
        if name.startswith("./"):
            name = name[2:]
        if name in listed:
            raise CoolSeasonError(f"SHA256SUMS lists {name} twice")
        listed[name] = digest.lower()
    missing = [n for n in SUMS_REQUIRED if n not in listed]
    if missing:
        raise CoolSeasonError(f"SHA256SUMS does not list {missing}")
    for name, digest in listed.items():
        _pin(d / name, digest, f"backfill {name}")
    return listed


def bind_blend_weights(path):
    """L2's frozen blend_l6_H weights: file sha pinned, the .sha256 sidecar agrees, control PASS, and the L6
    partner they were fitted with is the frozen Aug-Sep L6 (part 07a67425, nowcasts 3806687c)."""
    _pin(path, BLEND_WEIGHTS_SHA256, "blend_l6_H weights")
    side = Path(str(path) + ".sha256").read_text(encoding="utf-8").split()
    if not side or side[0] != BLEND_WEIGHTS_SHA256:
        raise CoolSeasonError("blend weights .sha256 sidecar disagrees")
    w = json.loads(Path(path).read_text(encoding="utf-8"))
    if w["control"].get("pass") is not True:
        raise CoolSeasonError("blend weights control does not PASS")
    if w["inputs"].get("l6_part") != L6_PART_SHA256 or w["inputs"].get("nowcasts") != L6_DEV_NOWCASTS_SHA256:
        raise CoolSeasonError("blend weights were not fitted with the frozen Aug-Sep L6 partner")
    weights = {int(k[1:]): float(v) for k, v in w["weights"].items()}
    if sorted(weights) != list(HOURS_0712) or not all(0.0 <= x <= 1.0 for x in weights.values()):
        raise CoolSeasonError(f"blend weights hours/values invalid: {weights}")
    return weights


def l6_part(coef_path):
    """MG-2's l6_stack part: file sha pinned and the canonical-JSON part sha equals the blend's partner."""
    _pin(coef_path, MG2_COEF_SHA256, "MG-2 coefficients")
    part = json.loads(Path(coef_path).read_bytes())["l6_stack"]
    sha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":"), allow_nan=False)
                         .encode("utf-8")).hexdigest()
    if sha != L6_PART_SHA256:
        raise CoolSeasonError(f"l6_stack part sha {sha} != {L6_PART_SHA256}")
    return {int(h): (float(v[0]), float(v[1])) for h, v in part["coef"].items()}


def l6_nowcast_map(research_root, nbm_corpus, l6_state_path):
    """{(market, local_date, hour): N} from L6's history builder and the frozen 0e89b32d HGB (as 1a)."""
    import numpy as np

    from weather.model import mg_serve_core as core

    frame, prov = l6_rows(research_root, nbm_corpus)
    state = core.load_l6_own_state(l6_state_path, L6_STATE_SHA256)
    n = core.l6_own_nowcast(state, frame)
    out = {(m, d, int(h)): float(x) for m, d, h, x in zip(frame.market, frame.local_date, frame.hour, n)
           if np.isfinite(x)}
    return out, prov


def dist_vector(mu, sigma, floor_r):
    """The MG-1-analogue integer-bucket distribution (``rz.bucket_brier``'s) as {bucket: p}."""
    from weather.calibration import season_matched_l6 as sm

    p, k = sm.bucket_probs([mu], [sigma], [floor_r])
    return {int(b): float(x) for b, x in zip(k[0], p[0]) if x > 0.0}


def blend(pa, pb, w):
    return {k: w * pa.get(k, 0.0) + (1.0 - w) * pb.get(k, 0.0) for k in set(pa) | set(pb)}


def score_0712(frame, state, hrrr, nmap, coef, weights):
    """Per row: P3d_H (L2 state, RN-1 HRRR extras), blend_l6_H = w_h P3d_H + (1 - w_h) L6, and the MG-1 analogue.

    L6 = Normal(v + a_h + b_h (N - v), max(s, 1)) floored at half-up(F); without N it is the MG-1 analogue
    exactly (as the dev L6 part serves). Rows without v, s or F have no comparator and no blend.
    """
    import numpy as np

    guard_scope(frame)
    n = len(frame)
    p3, bl, mg = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    stats = Counter()
    for i, r in enumerate(frame.itertuples(index=False)):
        F, ct, nm = (float(x) if x is not None and x == x else float("nan") for x in (r.F, r.current_temp, r.nbm_mean))
        if not (math.isfinite(F) and math.isfinite(ct)):
            stats["no_obs"] += 1
            continue
        h = int(r.hour)
        entry = hrrr.get((r.market, r.local_date, h))
        stats["hrrr_covered" if entry is not None and not entry["k_miss"] else "hrrr_miss"] += 1
        pa = p3dh_distribution(state, h, k_extra(entry, r.nbm_mean), market=r.market,
                               target_date=date.fromisoformat(r.local_date), high_so_far=F, current_temp=ct,
                               nbm_mean=nm)
        p3[i] = brier_from_dist(pa, r.y)
        stats["p3d_scored"] += 1
        v = float("nan") if r.v is None else float(r.v)
        s = float("nan") if r.s is None else float(r.s)
        if not (math.isfinite(v) and math.isfinite(s)):
            stats["no_mg1"] += 1
            continue
        sig = max(s, 1.0)
        pm = dist_vector(v, sig, F)
        mg[i] = brier_from_dist(pm, r.y)
        N = nmap.get((r.market, r.local_date, h))
        if N is None:
            stats["l6_no_nowcast_mg1"] += 1
            pl = pm
        else:
            a, b = coef[h]
            pl = dist_vector(v + a + b * (N - v), sig, F)
            stats["l6_nowcast"] += 1
        bl[i] = brier_from_dist(blend(pa, pl, weights[h]), r.y)
        stats["blend_scored"] += 1
    out = frame[["market", "local_date", "hour", "year", "month"]].copy()
    out["p3d_h"], out["blend"], out["mg1"] = p3, bl, mg
    return out, dict(stats)


def part1c(*, nbm_corpus, records_root, research_root, state_0712, hrrr_0712, hrrr_backfill, backfill_sums_sha256,
           land, l6_state, mg2_coefficients, blend_weights, rule, rule_1c, rule_1c_sha256, clarification,
           clarification_sha256, out_path):
    import numpy as np

    check_rule(rule)
    _pin(rule_1c, rule_1c_sha256, "1c rule")
    _pin(clarification, clarification_sha256, "clarification 2026-10-27")
    _pin(nbm_corpus, "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd", "NBM corpus")
    for name, sha in HRRR_0712_SHAS.items():
        _pin(Path(hrrr_0712) / name, sha, f"HRRR 07-12 training corpus {name}")
    sums = bind_sha256sums(hrrr_backfill, backfill_sums_sha256)
    state, state_sha, control_sha = bind_l2_state(state_0712)
    if state_sha != P3DH_0712_STATE_SHA256:
        raise CoolSeasonError(f"P3d_H 07-12 state {state_sha} != {P3DH_0712_STATE_SHA256}")
    weights = bind_blend_weights(blend_weights)
    coef = l6_part(mg2_coefficients)
    recf, shas, missing = record_rows(records_root, nbm_corpus, hours=HOURS_0712)
    markets = set(recf.market)
    point_train, rep_train = rn1_point_map(land, hrrr_0712, markets)
    point_back, rep_back = rn1_point_map(land, hrrr_backfill, markets)
    fitted = state["point_rule"]["report"]["stations"]
    for rep in (rep_train, rep_back):
        for icao, x in rep["stations"].items():
            if fitted.get(icao, {}).get("chosen_index") != x["chosen_index"]:
                raise CoolSeasonError(f"{icao}: RN-1 index differs from the state's fitted point rule")
    h_train, st_train = hrrr_k_columns(hrrr_0712, markets, hours=HOURS_0712, point=point_train, months=AUG_SEP,
                                       skip_after="2025-12-31")
    h_back, st_back = hrrr_k_columns(hrrr_backfill, markets, hours=HOURS_0712, point=point_back, months=OCT_DEC)
    hrrr = dict(h_train)
    hrrr.update(h_back)
    rows_read = int(len(recf))
    recf, scope = oct_dec_scope(recf, h_back)
    nmap, l6prov = l6_nowcast_map(research_root, nbm_corpus, l6_state)
    scored, stats = score_0712(recf, state, hrrr, nmap, coef, weights)
    keyset = pair_keys(scored, ("p3d_h", "blend", "mg1"))
    keys = list(zip(recf.market, recf.local_date, recf.hour.astype(int)))
    hcov = np.array([hrrr.get(k) is not None and not hrrr[k]["k_miss"] for k in keys])
    ncov = np.array([k in nmap for k in keys])
    month = recf.month.to_numpy(int)

    def counts(arm):
        out = {}
        for name, months in PERIODS:
            pm = np.isin(month, months)
            out[name] = {"rows": int(pm.sum()), "scored": int(np.isfinite(scored[arm].to_numpy(float))[pm].sum()),
                         "compared": int((np.isfinite(scored[arm].to_numpy(float))
                                          & np.isfinite(scored.mg1.to_numpy(float)))[pm].sum()),
                         "hrrr_covered": int(hcov[pm].sum()), "l6_nowcast_covered": int(ncov[pm].sum())}
        return out

    recent = scored[scored.year.isin(CLARIFIED_YEARS)].reset_index(drop=True)

    def arm(col):
        # the headline and transfer reading use Aug-Sep 2024-25 (same years as Oct-Dec); the declared all-years
        # Aug-Sep is reported beside it (its Oct-Dec periods are the same 2024-25 rows)
        main = compare(recent, col, "mg1", HOURS_0712)
        return {"headline": headline(main, keyset), "years_2024_25": main,
                "aug_sep_all_years_2021_25_reference": compare(scored, col, "mg1", HOURS_0712),
                "coverage": counts(col)}

    payload = {
        "label": "CS-1 (1c) cool-season transfer audit, history only, descriptive: L2's frozen MG-3 P3d_H 07-12 "
                 "and blend_l6_H (control PASS, sha-bound; blend L6 partner = frozen Aug-Sep L6 0e89b32d + part "
                 "07a67425, as the weights were fitted) vs the MG-1 analogue; Aug-Sep is IN-SAMPLE; Oct-Dec rows "
                 "are never training rows but share the training years 2021-25; no binding change. Clarification "
                 "2026-10-27: Oct-Dec scope = 2024-25 cycle-present backfill keys only, paired keys",
        "rule_sha256": RULE_CS_SHA256, "rule_1c_sha256": rule_1c_sha256, "module_sha256": _sha(__file__),
        "inputs": {"p3d_h_0712_state_sha256": state_sha, "l2_control_sha256": control_sha,
                   "blend_weights_sha256": BLEND_WEIGHTS_SHA256, "weights": {f"h{h:02d}": w for h, w in weights.items()},
                   "l6_state_sha256": L6_STATE_SHA256, "mg2_coefficients_sha256": MG2_COEF_SHA256,
                   "l6_part_sha256": L6_PART_SHA256, "hrrr_0712_train": HRRR_0712_SHAS,
                   "hrrr_backfill_sha256sums": backfill_sums_sha256, "hrrr_backfill_files": sums,
                   "land_sha256": RN1_LAND_SHA256, "l6_obs": l6prov, "records_sha256": shas,
                   "records_missing": missing},
        "point_rule": {"train": rep_train, "backfill": rep_back},
        "hrrr_stats": {"train_aug_sep": st_train, "backfill_oct_dec": st_back},
        "row_stats": stats, "rows_read": rows_read, "rows_in_scope": int(len(recf)),
        "clarification_sha256": clarification_sha256, "scope": scope, "key_sets": keyset,
        "p3d_h_0712": arm("p3d_h"), "blend_l6_h_0712": arm("blend")}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- row 49: blend_l6_H with the season-matched L6

SM_STATE_SHA256 = "800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db"
SM_LOYO_SHA256 = "07ef7810d81e434c93e08e552d3ca2df0ec195790a52b6431e578ab3ce515919"
SM_DEV_NOWCASTS_SHA256 = "714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a"
SM_DEV_VECTORS_SHA256 = "2366d67c5cdd6eb26b98064807210ade1c657829b7fa8e683535b94a9a2faa76"
RF1_NOTE_SHA256 = "b13f2e035cb797efc04ed936af523aa5c269dc693fd6eec766b0bb212ed8efa9"
OCT_DEC_PERIODS = tuple(x for x in PERIODS if x[0] != "aug_sep_in_sample")
LOYO_CONTROL_TOL = 1e-12


def bind_rf1_weights(path, weights_sha256):
    """L2's RF-1 refit weights: file sha = the forwarded one, the .sha256 sidecar agrees, every check PASSes
    and nothing stopped, the note is b13f2e03, and the partner is the season-matched L6 (part 07a67425,
    season dev nowcasts 714fa14e, partner vectors 2366d67c)."""
    _pin(path, weights_sha256, "RF-1 weights")
    side = Path(str(path) + ".sha256").read_text(encoding="utf-8").split()
    if not side or side[0] != weights_sha256:
        raise CoolSeasonError("RF-1 weights .sha256 sidecar disagrees")
    w = json.loads(Path(path).read_text(encoding="utf-8"))
    checks = w.get("checks") or {}
    if w.get("stopped_at") or not checks or not all(c.get("pass") is True for c in checks.values()):
        raise CoolSeasonError(f"RF-1 weights did not PASS every check: {w.get('stopped_at')}")
    if w.get("note_sha256") != RF1_NOTE_SHA256:
        raise CoolSeasonError(f"RF-1 note {w.get('note_sha256')} != {RF1_NOTE_SHA256}")
    inp = w.get("inputs") or {}
    if (inp.get("l6_part") != L6_PART_SHA256 or inp.get("season_nowcasts") != SM_DEV_NOWCASTS_SHA256
            or inp.get("partner_vectors") != SM_DEV_VECTORS_SHA256):
        raise CoolSeasonError("RF-1 weights were not fitted with the season-matched L6 partner")
    fit = list(w.get("fit_dates") or [])
    if len(fit) < 2 or not str(fit[0]) >= "2026-01-01" or str(fit[1]) > "2026-09-29":
        raise CoolSeasonError(f"RF-1 fit_dates {fit} are not inside dev 2026 (..2026-09-29)")
    weights = {int(k[1:]): float(v) for k, v in w["weights"].items()}
    if sorted(weights) != list(HOURS_0712) or not all(0.0 <= x <= 1.0 for x in weights.values()):
        raise CoolSeasonError(f"RF-1 weights hours/values invalid: {weights}")
    return weights, {"checks": {k: bool(c.get("pass")) for k, c in checks.items()}, "inputs": inp, "fit_dates": fit}


def season_nowcast_maps(research_root, nbm_corpus, sm_state_path, loyo_result, mg2_coefficients):
    """Oct-Dec season-L6 nowcasts on L6's history rows: LOYO (fold y fitted on Oct-Dec history without year y,
    exactly SM-L6's folds) and the final 800072c7 (IN-SAMPLE on every Oct-Dec history row).

    Positive control: SM-L6's registered LOYO pooled Oct-Dec dB is reproduced from these fold nowcasts, or the
    run refuses. -> ({key: N_loyo}, {key: N_final}, control)."""
    import numpy as np

    from weather.calibration import season_matched_l6 as sm
    from weather.model import mg_serve_core as core

    _pin(loyo_result, SM_LOYO_SHA256, "SM-L6 LOYO result")
    _pin(mg2_coefficients, MG2_COEF_SHA256, "MG-2 coefficients")
    coef = json.loads(Path(mg2_coefficients).read_text(encoding="utf-8"))["l6_stack"]["coef"]
    train, _ = sm.training_rows(research_root)
    rows, prov = l6_rows(research_root, nbm_corpus)
    rows = rows[rows.month.isin(OCT_DEC)].reset_index(drop=True)
    n_loyo = np.full(len(rows), np.nan)
    for y in YEARS:
        te = (rows.year == y).to_numpy()
        n_loyo[te] = core.l6_own_nowcast(sm.fit_state(train[train.year != y], {"fold": y}), rows[te])
    final = core.load_l6_own_state(sm_state_path, SM_STATE_SHA256)
    n_final = core.l6_own_nowcast(final, rows)
    part, base, _ = sm.stack_brier(rows, n_loyo, coef)
    got = sm.tables(rows, part, base)["oct_dec"]["pooled"]["estimate"]
    want = json.loads(Path(loyo_result).read_text(encoding="utf-8"))["season_matched_loyo"]["oct_dec"]["pooled"]
    control = {"reproduced": float(got), "registered": float(want["estimate"]),
               "abs_diff": abs(float(got) - float(want["estimate"]))}
    control["pass"] = control["abs_diff"] <= LOYO_CONTROL_TOL
    if not control["pass"]:
        raise CoolSeasonError(f"SM-L6 LOYO control failed: {control}")
    keys = list(zip(rows.market, rows.local_date, rows.hour.astype(int)))
    loyo_map = {k: float(x) for k, x in zip(keys, n_loyo) if np.isfinite(x)}
    final_map = {k: float(x) for k, x in zip(keys, n_final) if np.isfinite(x)}
    return loyo_map, final_map, dict(control, l6_obs=prov, training_rows=int(len(train)))


def score_sm_blend(frame, state, hrrr, maps, coef, weights):
    """Per Oct-Dec row: blend = w_h P3d_H + (1 - w_h) SM-L6, the SM-L6 stack alone (MG-2's 07-12 arm) and the
    MG-1 analogue, for each nowcast map in ``maps`` ({tag: {key: N}}). SM-L6 without N is the MG-1 analogue."""
    import numpy as np

    guard_scope(frame)
    n = len(frame)
    cols = {"mg1": np.full(n, np.nan), "p3d_h": np.full(n, np.nan)}
    for tag in maps:
        cols[f"blend_{tag}"], cols[f"sml6_{tag}"] = np.full(n, np.nan), np.full(n, np.nan)
    stats = Counter()
    for i, r in enumerate(frame.itertuples(index=False)):
        F, ct, nm = (float(x) if x is not None and x == x else float("nan") for x in (r.F, r.current_temp, r.nbm_mean))
        v = float("nan") if r.v is None else float(r.v)
        s = float("nan") if r.s is None else float(r.s)
        if not (math.isfinite(F) and math.isfinite(ct)):
            stats["no_obs"] += 1
            continue
        if not (math.isfinite(v) and math.isfinite(s)):
            stats["no_mg1"] += 1
            continue
        h = int(r.hour)
        entry = hrrr.get((r.market, r.local_date, h))
        stats["hrrr_covered" if entry is not None and not entry["k_miss"] else "hrrr_miss"] += 1
        pa = p3dh_distribution(state, h, k_extra(entry, r.nbm_mean), market=r.market,
                               target_date=date.fromisoformat(r.local_date), high_so_far=F, current_temp=ct,
                               nbm_mean=nm)
        sig = max(s, 1.0)
        pm = dist_vector(v, sig, F)
        cols["mg1"][i], cols["p3d_h"][i] = brier_from_dist(pm, r.y), brier_from_dist(pa, r.y)
        for tag, nmap in maps.items():
            N = nmap.get((r.market, r.local_date, h))
            if N is None:
                stats[f"{tag}_no_nowcast_mg1"] += 1
                pl = pm
            else:
                a, b = coef[h]
                pl = dist_vector(v + a + b * (N - v), sig, F)
            cols[f"sml6_{tag}"][i] = brier_from_dist(pl, r.y)
            cols[f"blend_{tag}"][i] = brier_from_dist(blend(pa, pl, weights[h]), r.y)
        stats["scored"] += 1
    out = frame[["market", "local_date", "hour", "year", "month"]].copy()
    for k, v in cols.items():
        out[k] = v
    return out, dict(stats)


def part_sm_blend(*, nbm_corpus, records_root, research_root, state_0712, hrrr_backfill, backfill_sums_sha256,
                  land, sm_state, sm_loyo, mg2_coefficients, rf1_weights, rf1_weights_sha256, rule, rule_49,
                  rule_49_sha256, clarification, clarification_sha256, out_path):
    import numpy as np

    check_rule(rule)
    _pin(rule_49, rule_49_sha256, "row 49 rule")
    _pin(clarification, clarification_sha256, "clarification 2026-10-27")
    _pin(nbm_corpus, "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd", "NBM corpus")
    sums = bind_sha256sums(hrrr_backfill, backfill_sums_sha256)
    state, state_sha, control_sha = bind_l2_state(state_0712)
    if state_sha != P3DH_0712_STATE_SHA256:
        raise CoolSeasonError(f"P3d_H 07-12 state {state_sha} != {P3DH_0712_STATE_SHA256}")
    weights, rf1 = bind_rf1_weights(rf1_weights, rf1_weights_sha256)
    coef = l6_part(mg2_coefficients)
    recf, shas, missing = record_rows(records_root, nbm_corpus, hours=HOURS_0712)
    recf = recf[recf.month.isin(OCT_DEC)].reset_index(drop=True)
    markets = set(recf.market)
    point, rep = rn1_point_map(land, hrrr_backfill, markets)
    fitted = state["point_rule"]["report"]["stations"]
    for icao, x in rep["stations"].items():
        if fitted.get(icao, {}).get("chosen_index") != x["chosen_index"]:
            raise CoolSeasonError(f"{icao}: RN-1 index differs from the state's fitted point rule")
    hrrr, hstats = hrrr_k_columns(hrrr_backfill, markets, hours=HOURS_0712, point=point, months=OCT_DEC)
    rows_read = int(len(recf))
    recf, scope = oct_dec_scope(recf, hrrr)
    n_loyo, n_final, control = season_nowcast_maps(research_root, nbm_corpus, sm_state, sm_loyo, mg2_coefficients)
    scored, stats = score_sm_blend(recf, state, hrrr, {"loyo": n_loyo, "final_in_sample": n_final}, coef, weights)
    keyset = pair_keys(scored, ("mg1", "p3d_h", "blend_loyo", "sml6_loyo", "blend_final_in_sample",
                                "sml6_final_in_sample"))
    keys = list(zip(recf.market, recf.local_date, recf.hour.astype(int)))
    hcov = np.array([hrrr.get(k) is not None and not hrrr[k]["k_miss"] for k in keys])
    month = recf.month.to_numpy(int)

    def counts(col):
        x = np.isfinite(scored[col].to_numpy(float))
        return {name: {"rows": int(np.isin(month, m).sum()), "scored": int(x[np.isin(month, m)].sum()),
                       "hrrr_covered": int(hcov[np.isin(month, m)].sum()),
                       "nowcast_covered_loyo": int(np.array([k in n_loyo for k in keys])[np.isin(month, m)].sum()),
                       "nowcast_covered_final": int(np.array([k in n_final for k in keys])[np.isin(month, m)].sum())}
                for name, m in OCT_DEC_PERIODS}

    def cmp(arm, base):
        c = compare(scored, arm, base, HOURS_0712, periods=OCT_DEC_PERIODS)
        return dict(c, headline=headline(c, keyset), coverage=counts(arm))

    payload = {
        "label": "Row 49 (CS-1 addendum), history only, descriptive: blend_l6_H with the season-matched L6 partner "
                 "and L2's RF-1 weights on Oct-Dec 2021-25 07-12, vs (a) the MG-1 analogue and (b) the SM-L6 "
                 "stack (MG-2's 07-12 arm). PRIMARY = LOYO season-L6 nowcasts (SM-L6's folds); the final 800072c7 "
                 "is IN-SAMPLE on every Oct-Dec history row and is reported labelled so; no binding change. "
                 "Clarification 2026-10-27: scope = 2024-25 cycle-present backfill keys only (folds 2024 and 2025 "
                 "scored), paired keys",
        "rule_sha256": RULE_CS_SHA256, "rule_49_sha256": rule_49_sha256, "module_sha256": _sha(__file__),
        "inputs": {"p3d_h_0712_state_sha256": state_sha, "l2_control_sha256": control_sha,
                   "rf1_weights_sha256": rf1_weights_sha256, "rf1": rf1,
                   "weights": {f"h{h:02d}": w for h, w in weights.items()},
                   "sm_state_sha256": SM_STATE_SHA256, "sm_loyo_sha256": SM_LOYO_SHA256,
                   "mg2_coefficients_sha256": MG2_COEF_SHA256, "l6_part_sha256": L6_PART_SHA256,
                   "hrrr_backfill_sha256sums": backfill_sums_sha256, "hrrr_backfill_files": sums,
                   "land_sha256": RN1_LAND_SHA256, "records_sha256": shas, "records_missing": missing},
        "loyo_control": control, "point_rule": rep, "hrrr_stats": hstats, "row_stats": stats,
        "rows_read": rows_read, "rows_in_scope": int(len(recf)), "clarification_sha256": clarification_sha256,
        "scope": scope, "key_sets": keyset,
        "primary_loyo": {"a_blend_vs_mg1": cmp("blend_loyo", "mg1"), "b_blend_vs_sml6": cmp("blend_loyo", "sml6_loyo"),
                         "sml6_vs_mg1": cmp("sml6_loyo", "mg1")},
        "secondary_final_in_sample": {"a_blend_vs_mg1": cmp("blend_final_in_sample", "mg1"),
                                      "b_blend_vs_sml6": cmp("blend_final_in_sample", "sml6_final_in_sample"),
                                      "sml6_vs_mg1": cmp("sml6_final_in_sample", "mg1")},
        "p3d_h_vs_mg1": cmp("p3d_h", "mg1")}
    _write_once(out_path, payload)
    return payload


# ---------------------------------------------------------------- subcommands

def coverage(*, research_root, nbm_corpus, records_root, hrrr_roots, rule, out_path):
    import pandas as pd

    check_rule(rule)
    obs = pd.read_parquet(Path(research_root) / "upstream_obs" / "obs.parquet", columns=["valid_utc", "role", "station"])
    obs = obs[(obs.role == "market") & (obs.valid_utc.dt.year <= 2025)]
    key = obs.valid_utc.dt.strftime("%Y-%m")
    obs_cov = obs.groupby([obs.station, key]).size().unstack(fill_value=0)
    nbm = Counter()
    for line in Path(nbm_corpus).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["target_date"] > "2025-12-31":
            continue
        nbm[(r["market_id"], r["target_date"][:7], bool(r["available"]))] += 1
    nbm_days = defaultdict(set)
    for line in Path(nbm_corpus).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["available"] and r["target_date"] <= "2025-12-31":
            nbm_days[r["target_date"][:7]].add(r["target_date"])
    rec = Counter()
    rec_last = {}
    from weather.model.mg_serve_core import R0_MARKETS

    for market in R0_MARKETS:
        for centre in AUG_SEP_CENTRES + OCT_DEC_CENTRES:
            payload, _ = load_records(records_root, market, centre)
            if payload is None:
                rec[(market, centre, "missing")] += 1
                continue
            days = {str(r["target_date"])[:10] for recs in payload["records"].values() for r in recs}
            for d in days:
                rec[(market, d[:7])] += 1
                rec_last[d[:7]] = max(rec_last.get(d[:7], ""), d)
    hrrr = {}
    for name, root in hrrr_roots.items():
        per_month, bytes_day = Counter(), defaultdict(float)
        days = defaultdict(set)
        for line in open(Path(root) / "selections.jsonl", encoding="utf-8"):
            s = json.loads(line)
            if s["local_date"] > "2026-09-29":
                raise CoolSeasonError("HRRR selection after 2026-09-29")
            per_month[s["local_date"][:7]] += 1
        for line in open(Path(root) / "manifest.jsonl", encoding="utf-8"):
            m = json.loads(line)
            for d in m.get("local_dates") or []:
                days[d[:4]].add(d)
            yr = m["cycle_utc"][:4]
            bytes_day[yr] += float(m.get("msg_bytes") or 0) + float(m.get("idx_bytes") or 0)
        gb_per_day = {y: bytes_day[y] / 1e9 / max(len(days[y]), 1) for y in sorted(bytes_day) if y <= "2025"}
        mean_gb_day = sum(gb_per_day.values()) / max(len(gb_per_day), 1)
        months = {"10": 31, "11": 30, "12": 31}
        hrrr[name] = {"selections_by_month": dict(sorted(per_month.items())),
                      "history_gb_per_local_day_by_year": gb_per_day,
                      "octdec_backfill_estimate_gb": {
                          "per_month_per_year": {m: mean_gb_day * n for m, n in months.items()},
                          "per_year": mean_gb_day * 92, "five_years": mean_gb_day * 92 * 5},
                      "has_oct_dec_2021_25": any(k[5:7] in months and k[:4] <= "2025" for k in per_month)}
    payload = {"label": "CS-1 coverage (history 2021-25; no backfill)", "rule_sha256": RULE_CS_SHA256,
               "obs_rows_by_station_month": {st: {k: int(v) for k, v in row.items()} for st, row in obs_cov.iterrows()},
               "nbm_rows_by_market_month": {f"{m}|{ym}|{a}": n for (m, ym, a), n in sorted(nbm.items())},
               "nbm_distinct_days_by_month": {k: len(v) for k, v in sorted(nbm_days.items())},
               "nbm_last_day_by_month": {k: max(v) for k, v in sorted(nbm_days.items())},
               "records_days_by_market_month": {f"{k[0]}|{k[1]}": n for k, n in sorted(rec.items()) if len(k) == 2},
               "records_missing": sorted(f"{k[0]}|{k[1]}" for k in rec if len(k) == 3),
               "records_last_day_by_month": dict(sorted(rec_last.items())), "hrrr": hrrr,
               "module_sha256": _sha(__file__)}
    _write_once(out_path, payload)
    return payload


def part1a(*, research_root, nbm_corpus, records_root, l6_state, mg2_coefficients, p3d_n_state, rule, out_path):
    check_rule(rule)
    _pin(nbm_corpus, "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd", "NBM corpus")
    l6f, prov = l6_rows(research_root, nbm_corpus)
    l6s, l6info = score_l6(l6f, l6_state, mg2_coefficients)
    l6cmp = compare(l6s, "part", "mg1", HOURS_0712)
    recf, shas, missing = record_rows(records_root, nbm_corpus)
    state = load_state(p3d_n_state, P3D_N_STATE_SHA256)
    p3s, p3stats = score_p3d(recf, state)
    p3cmp = compare(p3s, "part", "mg1", HOURS_1316)
    nbm_imputed = {name: int(recf.nbm_imputed[recf.month.isin(m)].sum()) for name, m in PERIODS}
    payload = {
        "label": "CS-1 (1a) cool-season transfer audit, history only, descriptive: frozen parts vs the MG-1 analogue; "
                 "Aug-Sep is IN-SAMPLE for the HGB and P3d fits; Oct-Dec rows are never training rows but share "
                 "the training years 2021-25; no binding change",
        "rule_sha256": RULE_CS_SHA256,
        "l6_stack_0712": dict(l6cmp, info=l6info, rows=int(len(l6f)),
                              rows_by_period={n: int(l6f.month.isin(m).sum()) for n, m in PERIODS},
                              inputs=prov),
        "p3d_n_1316": dict(p3cmp, rows=int(len(recf)), stats=p3stats, nbm_imputed_forecast_by_period=nbm_imputed,
                           rows_by_period={n: int(recf.month.isin(m).sum()) for n, m in PERIODS},
                           records_missing=missing, records_sha256=shas, state_sha256=P3D_N_STATE_SHA256),
        "module_sha256": _sha(__file__)}
    _write_once(out_path, payload)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.cool_season_audit",
                                     description="Lane L3 CS-1 cool-season transfer audit (history only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--research-root", required=True)
    c.add_argument("--nbm-corpus", required=True)
    c.add_argument("--records-root", required=True)
    c.add_argument("--hrrr", action="append", required=True, help="name=root")
    c.add_argument("--rule", required=True)
    c.add_argument("--out", required=True)
    a1 = sub.add_parser("part1a")
    for flag in ("--research-root", "--nbm-corpus", "--records-root", "--l6-state", "--mg2-coefficients",
                 "--p3d-n-state", "--rule", "--out"):
        a1.add_argument(flag, required=True)
    b1 = sub.add_parser("part1b")
    for flag in ("--nbm-corpus", "--records-root", "--state-1316", "--hrrr-1316", "--rule", "--out"):
        b1.add_argument(flag, required=True)
    c1 = sub.add_parser("part1c")
    for flag in ("--nbm-corpus", "--records-root", "--research-root", "--state-0712", "--hrrr-0712",
                 "--hrrr-backfill", "--backfill-sums-sha256", "--land", "--l6-state", "--mg2-coefficients",
                 "--blend-weights", "--rule", "--rule-1c", "--rule-1c-sha256", "--clarification",
                 "--clarification-sha256", "--out"):
        c1.add_argument(flag, required=True)
    r49 = sub.add_parser("sm-blend")
    for flag in ("--nbm-corpus", "--records-root", "--research-root", "--state-0712", "--hrrr-backfill",
                 "--backfill-sums-sha256", "--land", "--sm-state", "--sm-loyo", "--mg2-coefficients", "--rf1-weights",
                 "--rf1-weights-sha256", "--rule", "--rule-49", "--rule-49-sha256", "--clarification",
                 "--clarification-sha256", "--out"):
        r49.add_argument(flag, required=True)
    a = parser.parse_args(argv)
    if a.cmd == "coverage":
        roots = dict(x.split("=", 1) for x in a.hrrr)
        out = coverage(research_root=a.research_root, nbm_corpus=a.nbm_corpus, records_root=a.records_root,
                       hrrr_roots=roots, rule=a.rule, out_path=a.out)
        print(json.dumps({k: v["octdec_backfill_estimate_gb"] for k, v in out["hrrr"].items()}, indent=1))
    elif a.cmd == "sm-blend":
        out = part_sm_blend(nbm_corpus=a.nbm_corpus, records_root=a.records_root, research_root=a.research_root,
                            state_0712=a.state_0712, hrrr_backfill=a.hrrr_backfill,
                            backfill_sums_sha256=a.backfill_sums_sha256, land=a.land, sm_state=a.sm_state,
                            sm_loyo=a.sm_loyo, mg2_coefficients=a.mg2_coefficients, rf1_weights=a.rf1_weights,
                            rf1_weights_sha256=a.rf1_weights_sha256, rule=a.rule, rule_49=a.rule_49,
                            rule_49_sha256=a.rule_49_sha256, clarification=a.clarification,
                            clarification_sha256=a.clarification_sha256, out_path=a.out)
        print(json.dumps({"control": out["loyo_control"]["pass"], "scope": out["scope"], "key_sets": out["key_sets"],
                          **{k: v["headline"] for k, v in out["primary_loyo"].items()}}, indent=1))
    elif a.cmd == "part1c":
        out = part1c(nbm_corpus=a.nbm_corpus, records_root=a.records_root, research_root=a.research_root,
                     state_0712=a.state_0712, hrrr_0712=a.hrrr_0712, hrrr_backfill=a.hrrr_backfill,
                     backfill_sums_sha256=a.backfill_sums_sha256, land=a.land, l6_state=a.l6_state,
                     mg2_coefficients=a.mg2_coefficients, blend_weights=a.blend_weights, rule=a.rule,
                     rule_1c=a.rule_1c, rule_1c_sha256=a.rule_1c_sha256, clarification=a.clarification,
                     clarification_sha256=a.clarification_sha256, out_path=a.out)
        print(json.dumps({"scope": out["scope"], "key_sets": out["key_sets"],
                          **{k: out[k]["headline"] for k in ("p3d_h_0712", "blend_l6_h_0712")}}, indent=1))
    elif a.cmd == "part1b":
        out = part1b(nbm_corpus=a.nbm_corpus, records_root=a.records_root, state_1316=a.state_1316,
                     hrrr_1316=a.hrrr_1316, rule=a.rule, out_path=a.out)
        x = out["p3d_h_1316"]
        print(json.dumps({"reading": x["transfer_reading"], "stats": x["stats"],
                          "periods": {k: v["by"].get("pooled") for k, v in x["periods"].items()}}, indent=1))
    else:
        out = part1a(research_root=a.research_root, nbm_corpus=a.nbm_corpus, records_root=a.records_root,
                     l6_state=a.l6_state, mg2_coefficients=a.mg2_coefficients, p3d_n_state=a.p3d_n_state,
                     rule=a.rule, out_path=a.out)
        print(json.dumps({k: {"reading": out[k]["transfer_reading"],
                              "aug_sep": out[k]["periods"]["aug_sep_in_sample"]["by"].get("pooled"),
                              "oct_dec": out[k]["periods"]["oct_dec"]["by"].get("pooled")}
                          for k in ("l6_stack_0712", "p3d_n_1316")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
