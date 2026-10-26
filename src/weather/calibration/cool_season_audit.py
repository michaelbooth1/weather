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


def _write_once(path, payload):
    from weather.calibration import pooled_residual_model as l2

    path = l2.require_output_outside_repo(Path(path))
    if path.exists():
        raise CoolSeasonError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return path


def brier_from_dist(dist, y):
    """sum_k p_k^2 - 2 p_y + 1 over integer buckets (the label need not be in the support)."""
    return sum(p * p for p in dist.values()) - 2.0 * dist.get(int(y), 0.0) + 1.0


# ---------------------------------------------------------------- comparisons

def compare(frame, arm_col, base_col, hours):
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
    for name, months in PERIODS:
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
    a, o = out["aug_sep_in_sample"]["by"].get("pooled"), out["oct_dec"]["by"].get("pooled")
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
    a = parser.parse_args(argv)
    if a.cmd == "coverage":
        roots = dict(x.split("=", 1) for x in a.hrrr)
        out = coverage(research_root=a.research_root, nbm_corpus=a.nbm_corpus, records_root=a.records_root,
                       hrrr_roots=roots, rule=a.rule, out_path=a.out)
        print(json.dumps({k: v["octdec_backfill_estimate_gb"] for k, v in out["hrrr"].items()}, indent=1))
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
