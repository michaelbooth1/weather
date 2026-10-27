"""Rung R-ODC gate 1 (rule ``docs/research/octdec-0712-rodc-2026-10-27/rule_rodc.md`` with Clarification 1).

Research only, history only (Oct-Dec 2021-25), never served. Nothing in serving, capture or Scheduler imports
this module. Reached through ``python -m weather.calibration.cool_season_audit rodc-gate1``.

* COMP: the frozen blend_l6_H (P3d_H state e9276477, weights c7b8ebc0, L6 part 07a67425), CS-1 1c serve math.
* G1: P3d_H refit on the Oct-Dec rows only (``RK_ARMS["P3d_H"]``, ``_rung_entry``, one fit per hour), blocked
  leave-one-year-out 2021-25, inside the same frozen blend (same L6 partner, same weights w_h).
* Statistic: dR = mean_cell(Brier_G1 - Brier_COMP) / mean_cell(Brier_COMP), cells (local_date, market), h07-12,
  11 markets, date-clustered 2,000 draws, seed 20261027. PASS iff the upper 95% bound < 0.
* Headline rows: every Oct-Dec 2021-25 record row where both arms are scorable; no-cycle rows stay with NaN HRRR
  extras (never imputed). The no-cycle-dropped recomputation is reported only.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

from weather.calibration import cool_season_audit as cs

RODC_SEED = 20261027
RODC_HOURS = (7, 8, 9, 10, 11, 12)
RODC_YEARS = (2021, 2022, 2023, 2024, 2025)
OCT_DEC = (10, 11, 12)
BACKFILL_2425_SUMS = "fe2dad2c9b2567ff28a9916f42c51a9196d33fc79f40690332745c2ed2acbc4d"
P3DH_EXTRA = ("k_max", "k_gap", "k_tcdc")


class RodcError(RuntimeError):
    pass


def g1_training_frame(records_root, nbm_corpus, hrrr, markets):
    """P3d_H's own training frame (``dev_training_frame`` construction) on the Oct-Dec centres, NBM anchor
    attached as MG-3 does, hours 07-12, R-K columns from the R-ODC HRRR map. -> (frame, stats)."""
    from weather.calibration import ols_floor_ladder as l9
    from weather.calibration import pooled_residual_model as prm
    from weather.market.market_registry import spec_for_id

    payloads = [prm.load_records(records_root, m, c) for c in cs.OCT_DEC_CENTRES for m in markets]
    if any(p is None for p in payloads):
        raise RodcError("an Oct-Dec record payload is missing")
    frame, _ = prm.pooled_frame(payloads, prm.station_coordinates(markets))
    drop = [c for c in frame.columns if c.startswith("x_") and c not in prm.DEV_KEEP_X]
    frame = frame.drop(columns=drop)
    if frame["year"].max() >= 2026 or frame["target_date"].max() > "2025-12-31":
        raise RodcError("an R-ODC training row is from 2026")
    if not frame["target_date"].str[5:7].astype(int).isin(OCT_DEC).all():
        raise RodcError("an R-ODC training row is outside Oct-Dec")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, nbm_stats = prm.attach_training_nbm(frame, l9.load_nbm(nbm_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(RODC_HOURS)].reset_index(drop=True)
    frame, hook = prm.rk_training_columns(frame, hrrr)
    return frame, {"train_nbm": nbm_stats, "train_hrrr": hook, "rows": int(len(frame))}


def fold_support(frame, year, markets):
    """The fold's shared bucket support (rule Clarification 2): per market, every integer from the minimum to the
    maximum settled label ``y`` over the Oct-Dec training rows of the four years other than ``year``. No
    outcome-free per-date support exists for 2021-25 Oct-Dec (the records' ``bucket_space`` is the observed
    label set over all years, held-out year included), so the support is built from training years only. COMP
    and G1 both score on it in that fold."""
    train = frame[frame["year"] != year]
    if year in set(train["year"]):
        raise RodcError(f"fold {year}: the support saw the held-out year")
    out = {}
    for m in markets:
        ys = train.loc[train["market"] == m, "y"].astype(int)
        if ys.empty:
            raise RodcError(f"fold {year}: no training labels for {m}")
        out[m] = list(range(int(ys.min()), int(ys.max()) + 1))
    return out


def comp_state(frozen, buckets):
    """The frozen P3d_H state with only ``buckets`` replaced by the fold's shared support (everything else,
    train_y included, stays frozen)."""
    state = dict(frozen)
    state["buckets"] = {m: list(buckets[m]) for m in frozen["markets"]}
    return state


def fold_state(frozen, frame, buckets, year):
    """A P3d_H state with the frozen state's structure and constants, fitted per hour on Oct-Dec rows of every
    year except ``year`` (the arm spec and construction are MG-3's, unchanged)."""
    from weather.calibration import pooled_residual_model as prm

    simple, extra_ols, extra_hgb, extra_scale = prm._arm_spec(prm.RK_ARMS["P3d_H"])
    if simple or extra_ols or extra_scale or tuple(extra_hgb) != P3DH_EXTRA:
        raise RodcError(f"the P3d_H arm spec changed: {prm.RK_ARMS['P3d_H']}")
    train_all = frame[frame["year"] != year]
    if year in set(train_all["year"]) or len(set(train_all["year"])) != 4:
        raise RodcError(f"fold {year}: training years are not the other four")
    hours, rows, fits = {}, {}, {}
    for hour in RODC_HOURS:
        train = train_all[train_all["hour"] == hour].reset_index(drop=True)
        fits[hour] = prm._rung_entry(train, simple, extra_ols, extra_hgb, extra_scale)
        hours[hour] = prm.mg3_hour_entry(fits[hour])
        rows[hour] = int(len(train))
    state = {k: frozen[k] for k in ("season_of", "coords", "constants", "conversion")}
    state.update(markets=list(frozen["markets"]), centres=list(cs.OCT_DEC_CENTRES), extra_hgb=list(extra_hgb),
                 buckets={m: list(buckets[m]) for m in frozen["markets"]}, hours=hours)
    rows["export_parity_max_abs"] = export_parity(state, fits, train_all)
    return state, rows


def export_parity(state, fits, train_all, n=200, tol=1e-9):
    """The fold state's serve-math mean (``p3dh_distribution``'s yhat) equals the in-process fitted mean model on
    sampled training rows, or the run refuses (MG-3's control 1, applied to each fold)."""
    import numpy as np

    from weather.model import mg_serve_core as core

    worst = 0.0
    for hour, entry in fits.items():
        train = train_all[train_all["hour"] == hour].reset_index(drop=True)
        ok = np.isfinite(train["F"].to_numpy(float)) & np.isfinite(train["x_current_temp"].to_numpy(float))
        sample = train[ok].sample(n=min(n, int(ok.sum())), random_state=hour)
        pred, _ = entry["fit"]["mean"].predict(sample)
        mean = state["hours"][hour]["mean"]
        for j, (_, r) in enumerate(sample.iterrows()):
            X, mu0, g, _f = core.state_features(state, hour, market=r["market"],
                                                target_date=date.fromisoformat(r["target_date"]),
                                                high_so_far=float(r["F"]), current_temp=float(r["x_current_temp"]),
                                                nbm_mean=float(r["fh"]))
            X = np.column_stack([X, np.asarray([[float(r[c]) for c in P3DH_EXTRA]])])
            yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ mean["ols"] + mean["hgb"].predict(X))[0])
            worst = max(worst, abs(yhat - float(pred[j])))
    if not worst <= tol:
        raise RodcError(f"fold export parity failed: max |dyhat| {worst}")
    return worst


def score_rows(frame, comps, folds, hrrr, nmap, coef, weights):
    """Per Oct-Dec row: COMP = frozen blend_l6_H, G1 = the fold's P3d_H in the same blend, plus MG-1 (reported).
    ``comps[year]`` and ``folds[year]`` carry the same fold support (``fold_support``).
    The CS-1 1c per-row math (``score_0712``) without its 2024-25 scope guard."""
    import numpy as np

    n = len(frame)
    cols = {c: np.full(n, np.nan) for c in ("comp", "g1", "mg1", "p3d_comp", "p3d_g1")}
    stats = Counter()
    for i, r in enumerate(frame.itertuples(index=False)):
        F, ct, nm = (float(x) if x is not None and x == x else float("nan") for x in (r.F, r.current_temp, r.nbm_mean))
        if not (math.isfinite(F) and math.isfinite(ct)):
            stats["no_obs"] += 1
            continue
        v = float("nan") if r.v is None else float(r.v)
        s = float("nan") if r.s is None else float(r.s)
        if not (math.isfinite(v) and math.isfinite(s)):
            stats["no_mg1"] += 1
            continue
        h = int(r.hour)
        entry = hrrr.get((r.market, r.local_date, h))
        stats["hrrr_covered" if entry is not None and not entry["k_miss"] else "hrrr_miss"] += 1
        extra = cs.k_extra(entry, r.nbm_mean)
        kw = dict(market=r.market, target_date=date.fromisoformat(r.local_date), high_so_far=F, current_temp=ct,
                  nbm_mean=nm)
        pa = cs.p3dh_distribution(comps[int(r.year)], h, extra, **kw)
        pg = cs.p3dh_distribution(folds[int(r.year)], h, extra, **kw)
        sig = max(s, 1.0)
        pm = cs.dist_vector(v, sig, F)
        N = nmap.get((r.market, r.local_date, h))
        if N is None:
            stats["l6_no_nowcast_mg1"] += 1
            pl = pm
        else:
            a, b = coef[h]
            pl = cs.dist_vector(v + a + b * (N - v), sig, F)
        w = weights[h]
        cols["comp"][i] = cs.brier_from_dist(cs.blend(pa, pl, w), r.y)
        cols["g1"][i] = cs.brier_from_dist(cs.blend(pg, pl, w), r.y)
        cols["p3d_comp"][i], cols["p3d_g1"][i] = cs.brier_from_dist(pa, r.y), cs.brier_from_dist(pg, r.y)
        cols["mg1"][i] = cs.brier_from_dist(pm, r.y)
        stats["scored"] += 1
    out = frame[["market", "local_date", "hour", "year", "month"]].copy()
    for k, v in cols.items():
        out[k] = v
    return out, dict(stats)


def compare(scored, arm, ref, primary5):
    """dR(arm vs ref) pooled plus reported slices; rows where either is NaN are dropped (paired)."""
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz

    ok = np.isfinite(scored[arm].to_numpy(float)) & np.isfinite(scored[ref].to_numpy(float))
    f = scored[ok].reset_index(drop=True)
    num = (f[arm] - f[ref]).to_numpy(float)
    den = f[ref].to_numpy(float)
    dates, markets = f.local_date.astype(str).to_numpy(), f.market.astype(str).to_numpy()
    hour, year, month = f.hour.to_numpy(int), f.year.to_numpy(int), f.month.to_numpy(int)
    allm = np.ones(len(f), bool)
    masks = {"pooled": allm, "primary5": np.isin(markets, primary5)}
    masks.update({f"h{h:02d}": hour == h for h in RODC_HOURS})
    masks.update({f"year_{y}": year == y for y in RODC_YEARS})
    masks.update({f"month_{m}": month == m for m in OCT_DEC})
    res = rz._cell_ratio(dates, markets, num, den, masks, RODC_SEED)
    for k, v in res.items():
        sel = masks[k]
        v["abs_brier_diff_row_mean"] = float(num[sel].mean())
    res["pooled"]["key_set"] = dict(zip(("sha256", "rows"), cs.key_set_sha(f)))
    return res


def gate1(*, nbm_corpus, records_root, research_root, state_0712, hrrr_2123, sums_2123, hrrr_2425, land, l6_state,
          mg2_coefficients, blend_weights, rule, rule_sha256, out_path, commit):
    import numpy as np

    from weather.model.mg_serve_core import R0_MARKETS

    cs._pin(rule, rule_sha256, "R-ODC rule (with Clarification 1)")
    cs._pin(nbm_corpus, "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd", "NBM corpus")
    sums_a = cs.bind_sha256sums(hrrr_2123, sums_2123)
    sums_b = cs.bind_sha256sums(hrrr_2425, BACKFILL_2425_SUMS)
    if sums_a.get("stations.json") != sums_b.get("stations.json"):
        raise RodcError("the 2021-23 and 2024-25 backfills have different stations.json")
    frozen, state_sha, control_sha = cs.bind_l2_state(state_0712)
    if state_sha != cs.P3DH_0712_STATE_SHA256:
        raise RodcError(f"P3d_H state {state_sha} != {cs.P3DH_0712_STATE_SHA256}")
    weights = cs.bind_blend_weights(blend_weights)
    coef = cs.l6_part(mg2_coefficients)
    markets = set(R0_MARKETS)
    fitted = frozen["point_rule"]["report"]["stations"]
    hrrr, hstats, point_reports = {}, {}, {}
    for tag, root, years in (("2021_23", hrrr_2123, ("2021", "2022", "2023")),
                             ("2024_25", hrrr_2425, ("2024", "2025"))):
        point, rep = cs.rn1_point_map(land, root, markets)
        for icao, x in rep["stations"].items():
            if fitted.get(icao, {}).get("chosen_index") != x["chosen_index"]:
                raise RodcError(f"{icao}: RN-1 index differs from the state's fitted point rule")
        h, st = cs.hrrr_k_columns(root, markets, hours=RODC_HOURS, point=point, months=OCT_DEC)
        if any(k[1][:4] not in years for k in h):
            raise RodcError(f"backfill {tag} holds a date outside {years}")
        hrrr.update(h)
        hstats[tag], point_reports[tag] = st, rep
    recf, rec_shas, missing = cs.record_rows(records_root, nbm_corpus, hours=RODC_HOURS)
    recf = recf[recf.month.isin(OCT_DEC)].reset_index(drop=True)
    if missing:
        raise RodcError(f"records missing: {missing}")
    if recf.year.max() >= 2026 or recf.local_date.max() > "2025-12-31":
        raise RodcError("a scoring row is from 2026")
    nmap, l6prov = cs.l6_nowcast_map(research_root, nbm_corpus, l6_state)
    frame, train_stats = g1_training_frame(records_root, nbm_corpus, hrrr, sorted(markets))
    folds, comps, supports, fold_rows = {}, {}, {}, {}
    for y in RODC_YEARS:
        supports[y] = fold_support(frame, y, frozen["markets"])
        folds[y], fold_rows[y] = fold_state(frozen, frame, supports[y], y)
        comps[y] = comp_state(frozen, supports[y])
        if folds[y]["buckets"] != comps[y]["buckets"]:
            raise RodcError(f"fold {y}: COMP and G1 supports differ")
        print(f"r-odc gate 1 fold {y}: {fold_rows[y]}", flush=True)
    scored, stats = score_rows(recf, comps, folds, hrrr, nmap, coef, weights)
    keys = list(zip(scored.market, scored.local_date, scored.hour.astype(int)))
    no_cycle = np.array([hrrr.get(k) is None or not hrrr[k].get("cycle_present") for k in keys])
    from weather.calibration import r0_ols_floor_challenger as l3

    primary5 = list(l3.PRIMARY_MARKETS)
    head = compare(scored, "g1", "comp", primary5)
    sens = compare(scored[~no_cycle].reset_index(drop=True), "g1", "comp", primary5)
    ub = head["pooled"]["ci95"][1]
    verdict = "PASS" if ub is not None and ub < 0 else "FAIL"
    payload = {
        "label": "R-ODC gate 1: season-matched P3d_H (Oct-Dec refit, LOYO 2021-25) in the frozen blend_l6_H vs the "
                 "frozen blend_l6_H, Oct-Dec 07-12, history only",
        "rule_sha256": rule_sha256, "module_sha256": cs._sha(__file__), "cs_module_sha256": cs._sha(cs.__file__),
        "commit": commit, "verdict": verdict,
        "headline": {k: head["pooled"].get(k) for k in ("estimate", "ci95", "n_rows", "n_cells", "n_dates",
                                                         "abs_brier_diff_row_mean", "key_set")},
        "gate1": head, "sensitivity_no_cycle_dropped": sens,
        "reported_mg1": {"g1_vs_mg1": compare(scored, "g1", "mg1", primary5)["pooled"],
                         "comp_vs_mg1": compare(scored, "comp", "mg1", primary5)["pooled"],
                         "p3d_g1_vs_p3d_comp": compare(scored, "p3d_g1", "p3d_comp", primary5)["pooled"]},
        "counts": {"scoring_rows_read": int(len(recf)), "no_cycle_rows": int(no_cycle.sum()),
                   "fold_training_rows": {str(y): v for y, v in fold_rows.items()}, "row_stats": stats,
                   "training": train_stats},
        "fold_support": {str(y): {m: [v[0], v[-1], len(v)] for m, v in sup.items()} for y, sup in supports.items()},
        "inputs": {"p3d_h_state_sha256": state_sha, "l2_control_sha256": control_sha,
                   "blend_weights_sha256": cs.BLEND_WEIGHTS_SHA256, "l6_part_sha256": cs.L6_PART_SHA256,
                   "l6_state_sha256": cs.L6_STATE_SHA256, "mg2_coefficients_sha256": cs.MG2_COEF_SHA256,
                   "hrrr_2021_23_sha256sums": sums_2123, "hrrr_2021_23_files": sums_a,
                   "hrrr_2024_25_sha256sums": BACKFILL_2425_SUMS, "hrrr_2024_25_files": sums_b,
                   "records_sha256": rec_shas, "l6_obs": l6prov},
        "hrrr_stats": hstats, "point_rule": point_reports,
    }
    cs._write_once(out_path, payload)
    rows_path = Path(str(out_path).replace(".json", "_rows.csv.gz"))
    if rows_path.exists():
        raise RodcError(f"refusing to overwrite {rows_path}")
    scored.to_csv(rows_path, index=False, compression="gzip")
    payload["rows_sha256"] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    return payload
