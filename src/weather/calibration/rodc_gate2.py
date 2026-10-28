"""Rung R-ODC gate 2 (rule ``docs/research/octdec-0712-rodc-2026-10-27/rule_rodc.md`` with Clarification 3).

Research only, history only (Oct-Dec 2021-25), never served. Nothing in serving, capture or Scheduler imports
this module. Reached through ``python -m weather.calibration.cool_season_audit rodc-gate2``. Gate 1's module
``rodc_octdec`` is used unchanged (its functions are called, never edited).

* G2 = G1 (``RK_ARMS["P3d_H"]``, ``_rung_entry``) with ``extra_hgb`` + (low_so_far, dewpoint_c), inside the same
  frozen blend (same L6 partner, same weights w_h).
* NESTED LOYO: per outer year y, inner blocked LOYO of G1 and G2 on the four other years (each inner fit on its
  own three training years' support); NEST(y) = G2 iff the inner pooled mean Brier(G2) - Brier(G1) < 0, else G1;
  NEST(y) is fitted on the four years and scored on y.
* PASS iff the upper 95% bound of dR(NEST vs G1) < 0 (Clarification 3, C3.1). COMP (item 341 label),
  COMP-800072c7 (IN-SAMPLE) and MG-1 are reported only.
* Control (C3.5): gate 1's own code path must reproduce ``gate1_rows.csv.gz`` to 1e-12 before anything is
  scored; the first outer G2 fit is repeated and must predict identically.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path

from weather.calibration import cool_season_audit as cs
from weather.calibration import rodc_octdec as r1

G2_COLUMNS = ("low_so_far", "dewpoint_c")
G2_EXTRA = r1.P3DH_EXTRA + G2_COLUMNS
LADDER_SHA256 = "6e6d100fb5bb2c9c2d811a681a3a88d9458305ef701ba4b8651be34011c12e8e"
GATE1_JSON_SHA256 = "6f26c5a2af6253748dce0b2eb44aff5632b7dd94d444693b8d84831581b3d5c0"
GATE1_ROWS_SHA256 = "5239e6a10f4e6a2eaecededd5eda3ee6157365eb3c4539a4d16b4d27ad33bda9"
CONTROL_COLUMNS = ("comp", "g1", "mg1", "p3d_comp", "p3d_g1")
CONTROL_TOL = 1e-12
HIGH_TOL = 1e-9
G2_CENTRES = tuple(cs.OCT_DEC_CENTRES)  # every Oct-Dec scoring row comes from an Oct-Dec centre (gate 1 key set)
COMP_LABEL = "vs the Aug-Sep-centred frozen blend (item 341); reported only, never gating"
COMP_SM_LABEL = ("vs COMP with the season-matched L6 HGB 800072c7 nowcasts (IN-SAMPLE on every Oct-Dec history "
                 "row; weights c7b8ebc0 were fitted with the 0e89b32d partner); reported only")


class RodcGate2Error(RuntimeError):
    pass


def _md(day):
    return str(day)[5:10]


def _keep(day):
    day = str(day)[:10]
    return "2021-01-01" <= day <= "2025-12-31" and int(day[5:7]) in r1.OCT_DEC


# ---------------------------------------------------------------- the two columns (C3.4)

def ladder_cache_manifest(cache_dir, markets, centres=G2_CENTRES):
    """sha256 over the (file name, file sha256) lines, market-sorted then centre order, of the ladder caches the run
    reads (``cache_<market>_<MM-DD>.json``)."""
    lines = []
    for m in sorted(markets):
        for c in centres:
            p = Path(cache_dir) / f"cache_{m}_{_md(c)}.json"
            if not p.exists():
                raise RodcGate2Error(f"ladder cache missing: {p.name}")
            lines.append(f"{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()}")
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest(), len(lines)


def load_low_map(cache_dir, markets, centres=G2_CENTRES):
    """{(market, centre, date, hour): (low_so_far, cache high_so_far)} from L9's ladder caches (built by
    ``ols_floor_ladder build`` -> ``overnight_lows``), Oct-Dec 2021-25 rows only. No label is kept."""
    out = {}
    for m in markets:
        for c in centres:
            payload = json.loads((Path(cache_dir) / f"cache_{m}_{_md(c)}.json").read_text(encoding="utf-8"))
            if payload.get("market_id") != m or payload.get("centre") != _md(c):
                raise RodcGate2Error(f"ladder cache {m} {c} names {payload.get('market_id')} {payload.get('centre')}")
            for hour, rows in payload["hours"].items():
                if int(hour) not in r1.RODC_HOURS:
                    continue
                for row in rows:
                    if not _keep(row["date"]):
                        continue
                    low, high = row.get("low_so_far"), row.get("high_so_far")
                    out[(m, c, str(row["date"])[:10], int(hour))] = (
                        float("nan") if low is None else float(low), float("nan") if high is None else float(high))
    return out


def load_dew_map(records_root, markets, centres=G2_CENTRES):
    """{(market, centre, date, hour): (record high_so_far, record dewpoint_c)} from L2's records, Oct-Dec 2021-25
    rows only; NaN stays NaN. No label is kept."""
    from weather.calibration import pooled_residual_model as prm

    out = {}
    for m in markets:
        for c in centres:
            payload, _sha = cs.load_records(records_root, m, c)
            if payload is None:
                raise RodcGate2Error(f"records missing: {m} {c}")
            for hour, recs in payload["records"].items():
                if int(hour) not in r1.RODC_HOURS:
                    continue
                for rec in recs:
                    day = str(rec["target_date"])[:10]
                    if not _keep(day):
                        continue
                    out[(m, c, day, int(hour))] = (prm._num(rec.get("high_so_far")), prm._num(rec.get("dewpoint_c")))
    return out


def attach_g2_columns(frame, low_map, dew_map, *, date_col):
    """Append low_so_far and dewpoint_c to ``frame`` on (market, centre, date, hour). Refuses (C3.4) if any row
    has no ladder-cache or record entry, or if the cache's high_so_far differs from the record's (the
    ``overnight_lows`` assertion against the records the arms use) or from the frame's own F. -> (frame, stats)."""
    import numpy as np

    low, dew = np.full(len(frame), np.nan), np.full(len(frame), np.nan)
    stats = Counter()
    missing, mismatch = [], []
    for i, (m, c, d, h, F) in enumerate(zip(frame["market"], frame["centre"], frame[date_col], frame["hour"],
                                           frame["F"])):
        key = (m, c, str(d)[:10], int(h))
        lo, de = low_map.get(key), dew_map.get(key)
        if lo is None or de is None:
            missing.append(key)
            continue
        cache_high, rec_high = lo[1], de[0]
        F = float("nan") if F is None else float(F)
        if not (abs(cache_high - rec_high) <= HIGH_TOL and (not math.isfinite(F) or abs(F - rec_high) <= HIGH_TOL)):
            mismatch.append((key, cache_high, rec_high, F))
            continue
        low[i], dew[i] = lo[0], de[1]
        stats["dewpoint_nan"] += int(not math.isfinite(de[1]))
        stats["low_nan"] += int(not math.isfinite(lo[0]))
    if missing:
        raise RodcGate2Error(f"{len(missing)} rows have no ladder-cache or record entry, e.g. {missing[:3]}")
    if mismatch:
        raise RodcGate2Error(f"{len(mismatch)} rows fail the high_so_far assertion, e.g. {mismatch[:3]}")
    if (np.isfinite(low) & np.isfinite(frame["F"].to_numpy(float))
            & (low > frame["F"].to_numpy(float) + HIGH_TOL)).any():
        raise RodcGate2Error("a low_so_far is above its high_so_far")
    out = frame.copy()
    out["low_so_far"], out["dewpoint_c"] = low, dew
    stats["rows"] = int(len(out))
    return out, dict(stats)


# ---------------------------------------------------------------- fits

def support_for(frame, train_years, markets):
    """``rodc_octdec.fold_support`` generalised to any training-year set: per market, every integer from the
    minimum to the maximum label over the rows of ``train_years`` only."""
    train = frame[frame["year"].isin(list(train_years))]
    if set(train["year"]) != set(train_years):
        raise RodcGate2Error(f"support: training years {sorted(set(train['year']))} != {sorted(train_years)}")
    out = {}
    for m in markets:
        ys = train.loc[train["market"] == m, "y"].astype(int)
        if ys.empty:
            raise RodcGate2Error(f"support {sorted(train_years)}: no training labels for {m}")
        out[m] = list(range(int(ys.min()), int(ys.max()) + 1))
    return out


def fit_state(frozen, frame, buckets, train_years, extra_hgb):
    """``rodc_octdec.fold_state`` with the training years and ``extra_hgb`` as arguments: the P3d_H arm spec and
    ``_rung_entry`` construction unchanged, one fit per hour on ``train_years`` only, export parity checked."""
    from weather.calibration import pooled_residual_model as prm

    simple, extra_ols, spec_hgb, extra_scale = prm._arm_spec(prm.RK_ARMS["P3d_H"])
    if simple or extra_ols or extra_scale or tuple(spec_hgb) != r1.P3DH_EXTRA:
        raise RodcGate2Error(f"the P3d_H arm spec changed: {prm.RK_ARMS['P3d_H']}")
    if tuple(extra_hgb) not in (r1.P3DH_EXTRA, G2_EXTRA):
        raise RodcGate2Error(f"extra_hgb {extra_hgb} is neither G1's nor G2's")
    train_all = frame[frame["year"].isin(list(train_years))]
    if set(train_all["year"]) != set(train_years):
        raise RodcGate2Error(f"fit: training years {sorted(set(train_all['year']))} != {sorted(train_years)}")
    hours, rows, fits = {}, {}, {}
    for hour in r1.RODC_HOURS:
        train = train_all[train_all["hour"] == hour].reset_index(drop=True)
        fits[hour] = prm._rung_entry(train, simple, extra_ols, tuple(extra_hgb), extra_scale)
        hours[hour] = prm.mg3_hour_entry(fits[hour])
        rows[str(hour)] = int(len(train))
    state = {k: frozen[k] for k in ("season_of", "coords", "constants", "conversion")}
    state.update(markets=list(frozen["markets"]), centres=list(cs.OCT_DEC_CENTRES), extra_hgb=list(extra_hgb),
                 buckets={m: list(buckets[m]) for m in frozen["markets"]}, hours=hours)
    rows["export_parity_max_abs"] = export_parity(state, fits, train_all, tuple(extra_hgb))
    return r1.open_edges(state, buckets), rows, fits


def export_parity(state, fits, train_all, extra_hgb, n=200, tol=1e-9):
    """``rodc_octdec.export_parity`` with the arm's own extra columns."""
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
            X = np.column_stack([X, np.asarray([[float(r[c]) for c in extra_hgb]])])
            yhat = float((mu0 + np.array([[1.0, g, max(g, 0.0)]]) @ mean["ols"] + mean["hgb"].predict(X))[0])
            worst = max(worst, abs(yhat - float(pred[j])))
    if not worst <= tol:
        raise RodcGate2Error(f"fold export parity failed: max |dyhat| {worst}")
    return worst


def mean_predictions(fits, frame):
    """{hour: in-process mean-model predictions on that hour's rows} (the determinism check)."""
    import numpy as np

    out = {}
    for hour, entry in fits.items():
        rows = frame[frame["hour"] == hour].reset_index(drop=True)
        pred, _ = entry["fit"]["mean"].predict(rows)
        out[hour] = np.asarray(pred, float)
    return out


def determinism(fits_a, fits_b, frame):
    """Max |difference| between two fits' mean-model predictions on the same rows (0.0 when deterministic)."""
    import numpy as np

    a, b = mean_predictions(fits_a, frame), mean_predictions(fits_b, frame)
    worst = 0.0
    for hour in a:
        if a[hour].shape != b[hour].shape or not np.array_equal(np.isnan(a[hour]), np.isnan(b[hour])):
            return float("inf")
        ok = np.isfinite(a[hour])
        if ok.any():
            worst = max(worst, float(np.max(np.abs(a[hour][ok] - b[hour][ok]))))
    return worst


# ---------------------------------------------------------------- scoring

def _extra(state, base, row):
    """The arm's extra HGB vector: R-K's [k_max, k_gap, k_tcdc], then G2's two columns when the state has them."""
    names = tuple(state.get("extra_hgb") or r1.P3DH_EXTRA)
    if names == r1.P3DH_EXTRA:
        return list(base)
    if names == G2_EXTRA:
        return list(base) + [float(getattr(row, c)) for c in G2_COLUMNS]
    raise RodcGate2Error(f"unknown extra_hgb {names}")


def score_arms(frame, arms, hrrr, nmaps, coef, weights):
    """Per row, every arm's blend Brier on its year's support (``edge_brier``): ``arms`` maps a name to
    (states by year, nmap name); the L6 partner and weights are the frozen ones, and without a nowcast the L6 part is
    the MG-1 analogue (as gate 1). All arms of a row must share one support. Also the MG-1 analogue (``mg1``).
    The per-row math is ``rodc_octdec.score_rows``'s."""
    import numpy as np

    n = len(frame)
    cols = {k: np.full(n, np.nan) for k in list(arms) + ["mg1"]}
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
        h, y = int(r.hour), int(r.year)
        entry = hrrr.get((r.market, r.local_date, h))
        stats["hrrr_covered" if entry is not None and not entry["k_miss"] else "hrrr_miss"] += 1
        base = cs.k_extra(entry, r.nbm_mean)
        kw = dict(market=r.market, target_date=date.fromisoformat(r.local_date), high_so_far=F, current_temp=ct,
                  nbm_mean=nm)
        sig = max(s, 1.0)
        pm = cs.dist_vector(v, sig, F)
        sup = None
        for name, (states, nmap_name) in arms.items():
            st = states[y]
            if sup is None:
                sup = st["buckets"][r.market]
            elif st["buckets"][r.market] != sup:
                raise RodcGate2Error(f"year {y} {r.market}: arm {name} has a different support")
            N = nmaps[nmap_name].get((r.market, r.local_date, h))
            if N is None:
                stats[f"l6_no_nowcast_mg1_{nmap_name}"] += 1
                pl = pm
            else:
                a, b = coef[h]
                pl = cs.dist_vector(v + a + b * (N - v), sig, F)
            pa = cs.p3dh_distribution(st, h, _extra(st, base, r), **kw)
            cols[name][i] = r1.edge_brier(cs.blend(pa, pl, weights[h]), r.y, sup)
        stats["y_below_support" if int(r.y) < sup[0] else "y_above_support" if int(r.y) > sup[-1]
              else "y_in_support"] += 1
        cols["mg1"][i] = r1.edge_brier(pm, r.y, sup)
        stats["scored"] += 1
    out = frame[["market", "local_date", "hour", "year", "month"]].copy()
    for k, v in cols.items():
        out[k] = v
    return out, dict(stats)


def paired_mean(scored, arm, ref):
    """Plain row mean of Brier(arm) - Brier(ref) over rows where both are finite -> (mean, n)."""
    import numpy as np

    a, b = scored[arm].to_numpy(float), scored[ref].to_numpy(float)
    ok = np.isfinite(a) & np.isfinite(b)
    if not ok.any():
        raise RodcGate2Error(f"no paired rows for {arm} vs {ref}")
    return float(np.mean(a[ok] - b[ok])), int(ok.sum())


def select_arm(inner_mean):
    """NEST's arm: G2 iff the inner pooled mean Brier(G2) - Brier(G1) is strictly below 0 (equality picks G1)."""
    if inner_mean is None or not math.isfinite(inner_mean):
        raise RodcGate2Error(f"inner mean is not finite: {inner_mean}")
    return "g2" if inner_mean < 0 else "g1"


def nested_fold(frozen, train_frame, score_frame, outer_year, hrrr, nmap, coef, weights, markets):
    """Inner blocked LOYO of G1 and G2 on the four years other than ``outer_year``; each inner fit uses its own
    three training years' support. -> (selected arm, record). The outer year is never in any inner fit or score."""
    train4 = [y for y in r1.RODC_YEARS if y != outer_year]
    rec = {"train_years": train4, "inner": {}}
    parts = []
    for z in train4:
        inner3 = [y for y in train4 if y != z]
        if outer_year in inner3 or z in inner3:
            raise RodcGate2Error(f"outer {outer_year} inner {z}: leakage")
        sup = support_for(train_frame, inner3, markets)
        g1, rows_g1, _ = fit_state(frozen, train_frame, sup, inner3, r1.P3DH_EXTRA)
        g2, rows_g2, _ = fit_state(frozen, train_frame, sup, inner3, G2_EXTRA)
        held = score_frame[score_frame["year"] == z].reset_index(drop=True)
        if held.empty:
            raise RodcGate2Error(f"outer {outer_year} inner {z}: no held-out rows")
        scored, st = score_arms(held, {"g1": ({z: g1}, "l6"), "g2": ({z: g2}, "l6")}, hrrr, {"l6": nmap},
                                coef, weights)
        mean, n = paired_mean(scored, "g2", "g1")
        parts.append(scored)
        rec["inner"][str(z)] = {"train_years": inner3, "mean_g2_minus_g1": mean, "n_rows": n, "row_stats": st,
                                "support": {m: [v[0], v[-1], len(v)] for m, v in sup.items()},
                                "training_rows": {"g1": rows_g1, "g2": rows_g2}}
        print(f"r-odc gate 2 outer {outer_year} inner {z}: mean {mean:+.6f} n {n}", flush=True)
    import pandas as pd

    pooled, n = paired_mean(pd.concat(parts, ignore_index=True), "g2", "g1")
    rec.update(inner_pooled_mean=pooled, inner_pooled_rows=n, selected=select_arm(pooled))
    return rec["selected"], rec


# ---------------------------------------------------------------- control (C3.5)

def gate1_control(scored, rows_path, tol=CONTROL_TOL):
    """Gate 1's code path, re-executed, reproduces ``gate1_rows.csv.gz`` on the same keys to ``tol`` with identical
    NaN patterns, or the run is VOID (raises)."""
    import numpy as np
    import pandas as pd

    ref = pd.read_csv(rows_path)
    keys = ["market", "local_date", "hour"]
    a = scored.assign(hour=scored.hour.astype(int)).sort_values(keys).reset_index(drop=True)
    b = ref.assign(hour=ref.hour.astype(int)).sort_values(keys).reset_index(drop=True)
    if len(a) != len(b) or not (a[keys].astype(str).to_numpy() == b[keys].astype(str).to_numpy()).all():
        raise RodcGate2Error(f"VOID: gate 1 control keys differ ({len(a)} vs {len(b)} rows)")
    worst = 0.0
    for c in CONTROL_COLUMNS:
        x, y = a[c].to_numpy(float), b[c].to_numpy(float)
        if not np.array_equal(np.isnan(x), np.isnan(y)):
            raise RodcGate2Error(f"VOID: gate 1 control NaN pattern differs in {c}")
        ok = np.isfinite(x)
        if ok.any():
            worst = max(worst, float(np.max(np.abs(x[ok] - y[ok]))))
    if not worst <= tol:
        raise RodcGate2Error(f"VOID: gate 1 control max |diff| {worst} > {tol}")
    return {"pass": True, "max_abs_diff": worst, "rows": int(len(a)), "columns": list(CONTROL_COLUMNS)}


def sm_nowcast_map(research_root, nbm_corpus, sm_state_path):
    """{(market, local_date, hour): N} from L6's history builder and the season-matched 800072c7 HGB (IN-SAMPLE on
    every Oct-Dec history row); the ``cool_season_audit.l6_nowcast_map`` construction with the other state."""
    import numpy as np

    from weather.model import mg_serve_core as core

    frame, prov = cs.l6_rows(research_root, nbm_corpus)
    state = core.load_l6_own_state(sm_state_path, cs.SM_STATE_SHA256)
    n = core.l6_own_nowcast(state, frame)
    out = {(m, d, int(h)): float(x) for m, d, h, x in zip(frame.market, frame.local_date, frame.hour, n)
           if np.isfinite(x)}
    return out, prov


# ---------------------------------------------------------------- the run

def gate2(*, nbm_corpus, records_root, research_root, state_0712, hrrr_2123, sums_2123, hrrr_2425, land, l6_state,
          sm_state, mg2_coefficients, blend_weights, ladder_cache, ladder_cache_sha256, gate1_json, gate1_rows,
          rule, rule_sha256, out_path, commit):
    import numpy as np

    from weather.calibration import ols_floor_ladder as lad
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.model.mg_serve_core import R0_MARKETS

    out_path = Path(out_path)
    rows_out = Path(str(out_path).replace(".json", "_rows.csv.gz"))
    for p in (out_path, rows_out):
        if p.exists():
            raise RodcGate2Error(f"refusing to overwrite {p}")
    cs._pin(rule, rule_sha256, "R-ODC rule (with Clarification 3)")
    cs._pin(lad.__file__, LADDER_SHA256, "ols_floor_ladder.py")
    cs._pin(gate1_json, GATE1_JSON_SHA256, "gate1.json")
    cs._pin(gate1_rows, GATE1_ROWS_SHA256, "gate1_rows.csv.gz")
    cs._pin(nbm_corpus, "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd", "NBM corpus")
    markets = sorted(set(R0_MARKETS))
    cache_sha, cache_files = ladder_cache_manifest(ladder_cache, markets)
    if cache_sha != ladder_cache_sha256:
        raise RodcGate2Error(f"ladder cache manifest {cache_sha} != pinned {ladder_cache_sha256}")
    sums_a = cs.bind_sha256sums(hrrr_2123, sums_2123)
    sums_b = cs.bind_sha256sums(hrrr_2425, r1.BACKFILL_2425_SUMS)
    if sums_a.get("stations.json") != sums_b.get("stations.json"):
        raise RodcGate2Error("the 2021-23 and 2024-25 backfills have different stations.json")
    frozen, state_sha, control_sha = cs.bind_l2_state(state_0712)
    if state_sha != cs.P3DH_0712_STATE_SHA256:
        raise RodcGate2Error(f"P3d_H state {state_sha} != {cs.P3DH_0712_STATE_SHA256}")
    weights = cs.bind_blend_weights(blend_weights)
    coef = cs.l6_part(mg2_coefficients)
    fitted = frozen["point_rule"]["report"]["stations"]
    hrrr, hstats = {}, {}
    for tag, root, years in (("2021_23", hrrr_2123, ("2021", "2022", "2023")),
                             ("2024_25", hrrr_2425, ("2024", "2025"))):
        point, rep = cs.rn1_point_map(land, root, set(markets))
        for icao, x in rep["stations"].items():
            if fitted.get(icao, {}).get("chosen_index") != x["chosen_index"]:
                raise RodcGate2Error(f"{icao}: RN-1 index differs from the state's fitted point rule")
        h, st = cs.hrrr_k_columns(root, set(markets), hours=r1.RODC_HOURS, point=point, months=r1.OCT_DEC)
        if any(k[1][:4] not in years for k in h):
            raise RodcGate2Error(f"backfill {tag} holds a date outside {years}")
        hrrr.update(h)
        hstats[tag] = st
    recf, rec_shas, missing = cs.record_rows(records_root, nbm_corpus, hours=r1.RODC_HOURS)
    recf = recf[recf.month.isin(r1.OCT_DEC)].reset_index(drop=True)
    if missing:
        raise RodcGate2Error(f"records missing: {missing}")
    if recf.year.max() >= 2026 or recf.local_date.max() > "2025-12-31":
        raise RodcGate2Error("a scoring row is from 2026")
    frame, train_stats = r1.g1_training_frame(records_root, nbm_corpus, hrrr, markets)

    # the two columns, joined and asserted before any fit (C3.4)
    low_map = load_low_map(ladder_cache, markets)
    dew_map = load_dew_map(records_root, markets)
    frame, col_train = attach_g2_columns(frame, low_map, dew_map, date_col="target_date")
    recf, col_score = attach_g2_columns(recf, low_map, dew_map, date_col="local_date")
    del low_map, dew_map

    # gate 1 reproduction control (C3.5): gate 1's own code path, unchanged
    nmap, l6prov = cs.l6_nowcast_map(research_root, nbm_corpus, l6_state)
    sm_map, smprov = sm_nowcast_map(research_root, nbm_corpus, sm_state)
    g1, comps, supports, fold_rows = {}, {}, {}, {}
    for y in r1.RODC_YEARS:
        supports[y] = r1.fold_support(frame, y, frozen["markets"])
        g1[y], fold_rows[y] = r1.fold_state(frozen, frame, supports[y], y)
        comps[y] = r1.comp_state(frozen, supports[y])
    control_scored, _ = r1.score_rows(recf, comps, g1, hrrr, nmap, coef, weights)
    control = gate1_control(control_scored, gate1_rows)
    print(f"r-odc gate 2 control: {control}", flush=True)

    # nested LOYO
    nested, g2, nest, g2_rows = {}, {}, {}, {}
    det = None
    for y in r1.RODC_YEARS:
        sel, nested[str(y)] = nested_fold(frozen, frame, recf, y, hrrr, nmap, coef, weights, frozen["markets"])
        train4 = [x for x in r1.RODC_YEARS if x != y]
        g2[y], g2_rows[y], fits = fit_state(frozen, frame, supports[y], train4, G2_EXTRA)
        if det is None:
            _, _, again = fit_state(frozen, frame, supports[y], train4, G2_EXTRA)
            det = determinism(fits, again, frame[frame["year"].isin(train4)])
            if det != 0.0:
                raise RodcGate2Error(f"VOID: the repeated G2 fit differs (max |dyhat| {det})")
            del again
        nest[y] = g2[y] if sel == "g2" else g1[y]
        print(f"r-odc gate 2 outer {y}: selected {sel}", flush=True)
    arms = {"comp": (comps, "l6"), "comp_sm": (comps, "sm"), "g1": (g1, "l6"), "g2": (g2, "l6"),
            "nest": (nest, "l6")}
    scored, stats = score_arms(recf, arms, hrrr, {"l6": nmap, "sm": sm_map}, coef, weights)
    if not np.allclose(scored["g1"].to_numpy(float), control_scored["g1"].to_numpy(float), rtol=0, atol=CONTROL_TOL,
                       equal_nan=True):
        raise RodcGate2Error("VOID: score_arms' G1 differs from gate 1's score_rows")
    scored["nest_arm"] = scored["year"].map({y: nested[str(y)]["selected"] for y in r1.RODC_YEARS})
    primary5 = list(l3.PRIMARY_MARKETS)
    head = r1.compare(scored, "nest", "g1", primary5)
    ub = head["pooled"]["ci95"][1]
    verdict = "PASS" if ub is not None and ub < 0 else "FAIL"
    pooled = lambda a, b: r1.compare(scored, a, b, primary5)["pooled"]  # noqa: E731
    payload = {
        "label": "R-ODC gate 2: G2 = G1 + (low_so_far, dewpoint_c) under nested LOYO, in the frozen blend_l6_H, vs "
                 "G1 (Oct-Dec refit, LOYO 2021-25), Oct-Dec 07-12, history only",
        "rule_sha256": rule_sha256, "module_sha256": cs._sha(__file__), "gate1_module_sha256": cs._sha(r1.__file__),
        "cs_module_sha256": cs._sha(cs.__file__), "commit": commit, "verdict": verdict,
        "pass_rule": "upper 95% bound of dR(NEST vs G1) < 0 (Clarification 3, C3.1)",
        "headline": {k: head["pooled"].get(k) for k in ("estimate", "ci95", "n_rows", "n_cells", "n_dates",
                                                         "abs_brier_diff_row_mean", "key_set")},
        "gate2": head,
        "selection": {"g2_selected_folds": sum(v["selected"] == "g2" for v in nested.values()), "nested": nested},
        "reported": {"nest_vs_comp": dict(pooled("nest", "comp"), label=COMP_LABEL),
                     "nest_vs_comp_800072c7": dict(pooled("nest", "comp_sm"), label=COMP_SM_LABEL),
                     "nest_vs_mg1": pooled("nest", "mg1"),
                     "g2_vs_g1_plain": dict(r1.compare(scored, "g2", "g1", primary5), label="non-nested, reference"),
                     "g1_vs_comp": pooled("g1", "comp")},
        "control": dict(control, determinism_max_abs=det),
        "counts": {"scoring_rows_read": int(len(recf)), "row_stats": stats, "training": train_stats,
                   "columns_train": col_train, "columns_score": col_score,
                   "fold_training_rows": {"g1": {str(y): v for y, v in fold_rows.items()},
                                          "g2": {str(y): v for y, v in g2_rows.items()}}},
        "fold_support": {str(y): {m: [v[0], v[-1], len(v)] for m, v in sup.items()} for y, sup in supports.items()},
        "inputs": {"p3d_h_state_sha256": state_sha, "l2_control_sha256": control_sha,
                   "blend_weights_sha256": cs.BLEND_WEIGHTS_SHA256, "l6_part_sha256": cs.L6_PART_SHA256,
                   "l6_state_sha256": cs.L6_STATE_SHA256, "sm_state_sha256": cs.SM_STATE_SHA256,
                   "mg2_coefficients_sha256": cs.MG2_COEF_SHA256, "ladder_sha256": LADDER_SHA256,
                   "ladder_cache_manifest_sha256": cache_sha, "ladder_cache_files": cache_files,
                   "gate1_json_sha256": GATE1_JSON_SHA256, "gate1_rows_sha256": GATE1_ROWS_SHA256,
                   "hrrr_2021_23_sha256sums": sums_2123, "hrrr_2021_23_files": sums_a,
                   "hrrr_2024_25_sha256sums": r1.BACKFILL_2425_SUMS, "hrrr_2024_25_files": sums_b,
                   "records_sha256": rec_shas, "l6_obs": l6prov, "sm_l6_obs": smprov},
        "hrrr_stats": hstats,
    }
    cs._write_once(out_path, payload)
    scored.to_csv(rows_out, index=False, compression="gzip")
    payload["rows_sha256"] = hashlib.sha256(rows_out.read_bytes()).hexdigest()
    return payload
