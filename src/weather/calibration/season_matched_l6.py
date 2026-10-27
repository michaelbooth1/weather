r"""Lane L3, SM-L6: season-matched L6 HGB for MG-2's 07-12 arm. History only.

Rule ``C:/t/l3/sml6/rule_sml6.md`` (sha pinned below; ledger row 41). Only the training months of the L6 own-model
HGB change (Oct-Dec instead of Aug-Sep); features, station encoding, HGB_PARAMS and the state schema are those of
the frozen ``0e89b32d`` state, and MG-2's l6_stack coefficients stay frozen as bound. ``loyo`` scores the
leave-one-year-out season-matched stack against the MG-1 analogue on Oct-Dec 2021-25 07-12 rows (the frozen
Aug-Sep state on the same rows as a reference) and applies master's pre-declared decision rule. ``final`` fits
the bind-ready state once, and refuses unless ``loyo`` selected the season-matched arm. Nothing dated 2026 is
read. Research only; outputs outside the repository, write-once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

from weather.calibration import cool_season_audit as cs

RULE_SHA256 = "81649748d82319d248f9ce9b2c57e4450ecf9a796b5ff2407e2138d4c7798fc3"
TRAIN_MONTHS = (10, 11, 12)
NBM_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
PERIODS = (("oct_dec", (10, 11, 12)), ("oct", (10,)), ("nov", (11,)), ("dec_partial", (12,)),
           ("nov_dec", (11, 12)))
STATE_FILE = "l6_own_state_octdec.pkl"
SIDECAR = "l6_own_state_octdec.json"
ARM_SEASON = "season_matched_l6_stack"
ARM_MG1 = "mg1_from_11_01_frozen_augsep_l6_10_28_to_10_31"


class SeasonL6Error(RuntimeError):
    pass


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_rule(rule):
    got = _sha(rule)
    if got != RULE_SHA256:
        raise SeasonL6Error(f"rule {rule}: sha256 {got} != pinned {RULE_SHA256}")


def training_rows(research_root):
    """``build_history`` rows of months 10-12, history <= 2025-12-31 (the frozen state's fit, months changed)."""
    from weather.calibration import upstream_obs_screen as l6
    from weather.model import mg_serve_core as core

    if tuple(l6.OWN) != core.L6_OWN_COLUMNS:
        raise SeasonL6Error("upstream_obs_screen.OWN differs from mg_serve_core.L6_OWN_COLUMNS")
    hist, prov = l6.build_history(research_root)
    train = hist[hist.month.isin(TRAIN_MONTHS)].reset_index(drop=True)
    if len(train) == 0 or train.local_date.max() > "2025-12-31" or train.local_date.min() < "2021-01-01":
        raise SeasonL6Error("Oct-Dec training history is empty or outside 2021-01-01..2025-12-31")
    return train, prov


def fit_state(train, provenance):
    """An ``l6_own_state/1`` dict: ``make_model(OWN)`` fitted on ``train`` (unchanged HGB_PARAMS)."""
    from weather.calibration import upstream_obs_screen as l6
    from weather.model import mg_serve_core as core

    model = l6.make_model(l6.OWN).fit(train[list(l6.OWN)].to_numpy(float), train.y.to_numpy(float))
    return {"schema": core.L6_STATE_SCHEMA, "columns": list(l6.OWN), "model": model, "provenance": provenance}


def stack_brier(frame, n, coef):
    """MG-2 l6_stack (frozen coefficients) and the MG-1 analogue, integer-bucket Brier per row."""
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz

    v, s = frame.v.to_numpy(float), frame.s.to_numpy(float)
    hours = frame.hour.to_numpy(int)
    mu = v.copy()
    for h, (a, b, _) in coef.items():
        sel = (hours == int(h)) & np.isfinite(n) & np.isfinite(v)
        mu[sel] = v[sel] + a + b * (n[sel] - v[sel])
    ok = np.isfinite(v) & np.isfinite(s) & np.isfinite(n)
    R, dmax = frame.r.to_numpy(float), frame.dmax.to_numpy(float)
    sig = np.maximum(s, 1.0)
    part, base = np.full(len(frame), np.nan), np.full(len(frame), np.nan)
    part[ok] = rz.bucket_brier(mu[ok], sig[ok], R[ok], dmax[ok])
    base[ok] = rz.bucket_brier(v[ok], sig[ok], R[ok], dmax[ok])
    return part, base, mu


def tables(frame, arm, base):
    """dB vs MG-1 by period (pooled, hours), and by year / market / month for the pooled Oct-Dec rows."""
    import numpy as np

    from weather.calibration import rz_hrrr_spread as rz

    ok = np.isfinite(arm) & np.isfinite(base)
    f = frame[ok].reset_index(drop=True)
    a, b = arm[ok], base[ok]
    num, dates, markets = a - b, f.local_date.astype(str).to_numpy(), f.market.astype(str).to_numpy()
    month, hour, year = f.month.to_numpy(int), f.hour.to_numpy(int), f.year.to_numpy(int)
    out = {}
    for name, months in PERIODS:
        pm = np.isin(month, months)
        masks = {"pooled": pm}
        masks.update({f"h{h:02d}": pm & (hour == h) for h in cs.HOURS_0712})
        res = rz._cell_ratio(dates, markets, num, b, masks, cs.SEED)
        for k, v in res.items():
            v["brier_part"], v["brier_mg1"] = float(a[masks[k]].mean()), float(b[masks[k]].mean())
        out[name] = res
    pm = np.isin(month, TRAIN_MONTHS)
    out["oct_dec_per_year"] = rz._cell_ratio(dates, markets, num, b, {str(y): pm & (year == y) for y in cs.YEARS},
                                             cs.SEED)
    out["oct_dec_per_market"] = rz._cell_ratio(dates, markets, num, b,
                                               {m: pm & (markets == m) for m in sorted(set(markets))}, cs.SEED)
    out["rows_compared"], out["rows_without_comparator"] = int(ok.sum()), int((~ok).sum())
    return out


def decide(pooled):
    """Master's pre-declared rule: pooled Oct-Dec upper bound < 0 -> season-matched arm; otherwise MG-1 from 11-01."""
    hi = (pooled or {}).get("ci95", [None, None])[1]
    return ARM_SEASON if hi is not None and hi < 0 else ARM_MG1


VECTORS_FILE = "loyo_vectors.parquet"
VECTOR_COLUMNS = ("local_date", "market", "hour", "band_f", "band_open_top", "p_season_l6_stack", "p_mg1_analogue",
                  "fold_year")


def bucket_probs(mu, sigma, floor_r):
    """The integer-bucket probability matrix ``rz_hrrr_spread.bucket_brier`` scores, and its bands.

    Band k (deg F) runs from half-up(floor) for ``SUPPORT`` bands; the last band is open above (k and higher).
    """
    import numpy as np
    from scipy.special import ndtr

    from weather.calibration import rz_hrrr_spread as rz

    mu, sigma = np.asarray(mu, float), np.asarray(sigma, float)
    B = np.floor(np.asarray(floor_r, float) + 0.5)
    k = B[:, None] + np.arange(rz.SUPPORT)[None, :]
    lower = ndtr((k - 0.5 - mu[:, None]) / sigma[:, None])
    upper = ndtr((k + 0.5 - mu[:, None]) / sigma[:, None])
    upper[:, -1] = 1.0
    mass = np.clip(upper - lower, 0.0, None)
    total = mass.sum(1)
    dead = ~(total > 0)
    mass[dead] = 0.0
    mass[dead, 0] = 1.0
    return mass / np.where(dead, 1.0, total)[:, None], k


def write_vectors(rows, mu_season, base_ok, out_dir):
    """Per (date, market, hour, band) LOYO season-L6 stack and MG-1 analogue probabilities; nonzero bands only.

    Self-check: the Brier recomputed from the vectors equals ``bucket_brier`` per row to 1e-12. -> (path, sha).
    """
    import numpy as np
    import pandas as pd

    from weather.calibration import rz_hrrr_spread as rz

    f = rows[base_ok].reset_index(drop=True)
    v, s = f.v.to_numpy(float), np.maximum(f.s.to_numpy(float), 1.0)
    R, dmax = f.r.to_numpy(float), f.dmax.to_numpy(float)
    mu = mu_season[base_ok]
    ps, k = bucket_probs(mu, s, R)
    pm, _ = bucket_probs(v, s, R)
    for p, ref in ((ps, rz.bucket_brier(mu, s, R, dmax)), (pm, rz.bucket_brier(v, s, R, dmax))):
        onehot = (k == dmax[:, None]).astype(float)
        got = ((p - onehot) ** 2).sum(1) + (~onehot.any(1)).astype(float)
        if not np.allclose(got, ref, atol=1e-12, rtol=0):
            raise SeasonL6Error("vector Brier does not reproduce bucket_brier")
    keep = (ps > 0) | (pm > 0)
    i, j = np.nonzero(keep)
    out = pd.DataFrame({"local_date": f.local_date.to_numpy()[i], "market": f.market.to_numpy()[i],
                        "hour": f.hour.to_numpy(int)[i], "band_f": k[i, j].astype(int),
                        "band_open_top": j == ps.shape[1] - 1, "p_season_l6_stack": ps[i, j],
                        "p_mg1_analogue": pm[i, j], "fold_year": f.year.to_numpy(int)[i]})
    out = out.sort_values(["local_date", "market", "hour", "band_f"]).reset_index(drop=True)
    path = cs._outside_repo(Path(out_dir) / VECTORS_FILE)
    if path.exists():
        raise SeasonL6Error(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return str(path), _sha(path), int(len(f)), int(len(out))


def loyo(*, research_root, nbm_corpus, l6_state, mg2_coefficients, rule, out_path):
    import numpy as np

    from weather.model import mg_serve_core as core

    check_rule(rule)
    cs._pin(nbm_corpus, NBM_CORPUS_SHA256, "NBM corpus")
    cs._pin(mg2_coefficients, cs.MG2_COEF_SHA256, "MG-2 coefficients")
    coef = json.loads(Path(mg2_coefficients).read_text(encoding="utf-8"))["l6_stack"]["coef"]
    train, prov = training_rows(research_root)
    rows, rows_prov = cs.l6_rows(research_root, nbm_corpus)
    rows = rows[rows.month.isin(TRAIN_MONTHS)].reset_index(drop=True)
    n_season = np.full(len(rows), np.nan)
    folds = {}
    for y in cs.YEARS:
        te = (rows.year == y).to_numpy()
        tr = train[train.year != y]
        state = fit_state(tr, {"fold": y})
        n_season[te] = core.l6_own_nowcast(state, rows[te])
        folds[str(y)] = {"train_rows": int(len(tr)), "scored_rows": int(te.sum())}
    frozen = core.load_l6_own_state(l6_state, cs.L6_STATE_SHA256)
    n_frozen = core.l6_own_nowcast(frozen, rows)
    p_season, base, mu_s = stack_brier(rows, n_season, coef)
    p_frozen, base_f, mu_f = stack_brier(rows, n_frozen, coef)
    dmax = rows.dmax.to_numpy(float)
    rmse = {}
    for name, months in PERIODS:
        pm = rows.month.isin(months).to_numpy() & np.isfinite(base)
        rmse[name] = {"n": int(pm.sum()),
                      "nowcast_season": float(np.sqrt(np.mean((n_season[pm] - dmax[pm]) ** 2))),
                      "nowcast_frozen_augsep": float(np.sqrt(np.mean((n_frozen[pm] - dmax[pm]) ** 2))),
                      "mu_season": float(np.sqrt(np.mean((mu_s[pm] - dmax[pm]) ** 2))),
                      "mu_frozen_augsep": float(np.sqrt(np.mean((mu_f[pm] - dmax[pm]) ** 2))),
                      "nbm": float(np.sqrt(np.mean((rows.v.to_numpy(float)[pm] - dmax[pm]) ** 2)))}
    season = tables(rows, p_season, base)
    reference = tables(rows, p_frozen, base_f)
    decision = decide(season["oct_dec"].get("pooled"))
    vec_ok = np.isfinite(p_season) & np.isfinite(base)
    vpath, vsha, vrows, vlines = write_vectors(rows, mu_s, vec_ok, Path(out_path).parent)
    payload = {
        "label": "SM-L6 season-matched L6 stack, LOYO 2021-25 Oct-Dec 07-12 vs the MG-1 analogue, history only; "
                 "MG-2 l6_stack coefficients frozen as bound, only the HGB swapped",
        "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__),
        "decision": decision, "decision_basis": "pooled Oct-Dec dB upper bound (97.5%) < 0",
        "season_matched_loyo": season, "frozen_augsep_reference": reference, "rmse_f": rmse, "folds": folds,
        "training": {"rows": int(len(train)), "first": str(train.local_date.min()),
                     "last": str(train.local_date.max()), "months": list(TRAIN_MONTHS)},
        "coef": coef, "coef_sha256": cs.MG2_COEF_SHA256, "frozen_l6_sha256": cs.L6_STATE_SHA256,
        "inputs": dict(prov, nbm_corpus_sha256=NBM_CORPUS_SHA256), "scored_rows": int(len(rows)),
        "vectors": {"path": vpath, "sha256": vsha, "columns": list(VECTOR_COLUMNS), "snapshot_rows": vrows,
                    "lines": vlines, "note": "nonzero bands only; band_open_top marks the open top band; MG-1 analogue on the same rows"}}
    cs._write_once(out_path, payload)
    return payload


def final(*, research_root, loyo_result, rule, out_dir, commit):
    """The bind-ready state, fitted once on all Oct-Dec 2021-25, only when ``loyo`` selected the arm."""
    import sklearn

    from weather.calibration import upstream_obs_screen as l6
    from weather.model import mg_serve_core as core

    check_rule(rule)
    result = json.loads(Path(loyo_result).read_text(encoding="utf-8"))
    if result.get("rule_sha256") != RULE_SHA256 or result.get("decision") != ARM_SEASON:
        raise SeasonL6Error("the LOYO result did not select the season-matched arm; no final fit")
    if decide(result["season_matched_loyo"]["oct_dec"].get("pooled")) != ARM_SEASON:
        raise SeasonL6Error("the LOYO pooled upper bound is not below 0")
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise SeasonL6Error(f"output directory {out} must be new or empty")
    train, prov = training_rows(research_root)
    provenance = {"commit": commit, "upstream_obs_screen_sha256": _sha(l6.__file__),
                  "season_matched_l6_module_sha256": _sha(__file__), "rule_sha256": RULE_SHA256,
                  "loyo_result_sha256": _sha(loyo_result), **prov,
                  "train_months": list(TRAIN_MONTHS), "train_rows": int(len(train)),
                  "train_first": str(train.local_date.min()), "train_last": str(train.local_date.max()),
                  "hgb_params": dict(l6.HGB_PARAMS), "sklearn": sklearn.__version__,
                  "python": sys.version.split()[0]}
    state = fit_state(train, provenance)
    out.mkdir(parents=True, exist_ok=True)
    path = out / STATE_FILE
    path.write_bytes(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))
    digest = _sha(path)
    core.load_l6_own_state(path, digest)  # loads through the serve core unchanged
    sidecar = dict(provenance, state_sha256=digest, schema=core.L6_STATE_SCHEMA)
    (out / SIDECAR).write_text(json.dumps(sidecar, indent=1, sort_keys=True), encoding="utf-8")
    return sidecar


# ---------------------------------------------------------------- dev vectors for L2's MG-3 weight refit

CAPTURED_FEATURES_SHA256 = "0d5c30b39e92e4df8d6201769bbf1eb773f2e7e89c6d2a060a04d5bd70990557"
FROZEN_DEV_NOWCASTS_SHA256 = "3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3"
L6_PART_SHA256 = "07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9"
LAYOUT_MANIFEST_SHA256 = "4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22"
DEV_FROM, DEV_TO = "2026-08-01", "2026-09-29"


def dev_emit(*, state_dir, state_sha, captured_dir, frozen_l6_state, mg2_coefficients, layout, out_dir):
    """Season-matched L6 stack on the dev window 2026-08-01..09-29 (master/coordinator 2026-10-26, for L2's
    MG-3 weight refit under rule 4fb02a2c with its inputs swapped).

    1. ``nowcasts_season_dev.parquet``: the frozen final state on L3's captured dev serve features (the same
       rows and columns as ``3806687c``: row_key, n_own, n_up, n_ring; n_up/n_ring NaN as before). Control:
       the frozen Aug-Sep state on the same features reproduces ``3806687c`` n_own to 1e-9.
    2. ``l6_stack_season_dev_vectors.parquet``: ``free_source_candidates.l6_stack.predict`` with the bound
       MG-2 coefficients part (``07a67425``) on the v3 layout's dev snapshots, reading (1); the candidate
       format (row_key, band_index, p) plus snapshot keys. No label or price column is written.
    """
    import os

    import numpy as np
    import pandas as pd

    from weather.model import mg_serve_core as core
    from weather.reporting.scorecards import dev_scorecard_data as data

    out = cs._outside_repo(Path(out_dir))
    if out.exists() and any(out.iterdir()):
        raise SeasonL6Error(f"output directory {out} must be new or empty")
    sidecar = json.loads((Path(state_dir) / SIDECAR).read_text(encoding="utf-8"))
    if sidecar.get("state_sha256") != state_sha:
        raise SeasonL6Error("final state sidecar sha differs from the bound sha")
    season = core.load_l6_own_state(Path(state_dir) / STATE_FILE, state_sha)
    frozen = core.load_l6_own_state(frozen_l6_state, cs.L6_STATE_SHA256)
    feat_path = Path(captured_dir) / "serve_features.parquet"
    ref_path = Path(captured_dir) / "nowcasts.parquet"
    cs._pin(feat_path, CAPTURED_FEATURES_SHA256, "captured dev serve features")
    cs._pin(ref_path, FROZEN_DEV_NOWCASTS_SHA256, "captured dev nowcasts")
    if _sha(Path(layout) / "manifest.json") != LAYOUT_MANIFEST_SHA256:
        raise SeasonL6Error("layout manifest sha differs from the one the MG-2 coefficients were fitted on")
    feat = pd.read_parquet(feat_path)
    ref = pd.read_parquet(ref_path)
    if list(ref.row_key) != list(feat.row_key):
        raise SeasonL6Error("captured nowcasts and features are not row-aligned")
    again = core.l6_own_nowcast(frozen, feat)
    want = ref.n_own.to_numpy(float)
    both = np.isfinite(again) | np.isfinite(want)
    gap = float(np.nanmax(np.abs(again[both] - want[both])))
    if not gap <= 1e-9:
        raise SeasonL6Error(f"control: frozen state does not reproduce 3806687c (gap {gap})")
    now = ref.copy()
    now["n_own"] = core.l6_own_nowcast(season, feat)
    out.mkdir(parents=True, exist_ok=True)
    now_path = out / "nowcasts_season_dev.parquet"
    now.to_parquet(now_path, index=False)
    now_sha = _sha(now_path)

    cs._pin(mg2_coefficients, cs.MG2_COEF_SHA256, "MG-2 coefficients")
    part = json.loads(Path(mg2_coefficients).read_text(encoding="utf-8"))["l6_stack"]
    psha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":"), allow_nan=False)
                          .encode("utf-8")).hexdigest()
    if psha != L6_PART_SHA256:
        raise SeasonL6Error(f"l6_stack part sha {psha} != {L6_PART_SHA256}")
    state = {"coef": {int(h): tuple(v) for h, v in part["coef"].items()}, "column": part["column"]}
    os.environ["L6_NOWCASTS"] = str(now_path)
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    l6_stack._CACHE.clear()
    start, end = data.check_range(DEV_FROM, DEV_TO)
    lay = data.load_layout(layout, start, end)
    snaps = lay.snaps.reset_index(drop=True)
    if (snaps.date.astype(str) > DEV_TO).any():
        raise SeasonL6Error("a layout snapshot is after 2026-09-29")
    snaps = snaps.assign(floor=snaps[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1))
    vec = l6_stack.predict(state, snaps, lay.bands)
    if l6_stack.nowcasts()[1] != now_sha:
        raise SeasonL6Error("l6_stack read a nowcast file other than the season-matched one")
    keys = snaps[["row_key", "snapshot_id", "market", "date", "local_hour", "captured_at_utc"]].copy()
    keys["date"] = keys.date.astype(str).str[:10]
    vec = vec.merge(keys, on="row_key", how="left", validate="many_to_one")
    vec_path = out / "l6_stack_season_dev_vectors.parquet"
    vec.to_parquet(vec_path, index=False)
    n_rows = snaps.local_hour.isin(cs.HOURS_0712).to_numpy()
    has_n = np.isfinite(now.set_index("row_key").n_own.reindex(snaps.row_key).to_numpy(float))
    manifest = {"state_sha256": state_sha, "frozen_control_gap": gap, "l6_part_sha256": psha,
                "coefficients_file_sha256": cs.MG2_COEF_SHA256, "layout_manifest_sha256": LAYOUT_MANIFEST_SHA256,
                "captured_features_sha256": CAPTURED_FEATURES_SHA256,
                "nowcasts": {"path": str(now_path), "sha256": now_sha, "rows": int(len(now)),
                             "columns": list(now.columns), "key": "row_key = '<market>|<captured_at local ISO>'",
                             "replaces": FROZEN_DEV_NOWCASTS_SHA256},
                "vectors": {"path": str(vec_path), "sha256": _sha(vec_path), "rows": int(len(vec)),
                            "snapshots": int(vec.row_key.nunique()), "columns": list(vec.columns),
                            "key": "row_key (layout); snapshot_id, market, date, local_hour, captured_at_utc "
                                   "carried for joins",
                            "stack_rows_0712_with_nowcast": int((n_rows & has_n).sum())},
                "dates": [DEV_FROM, DEV_TO], "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__)}
    (out / "dev_emit_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.season_matched_l6",
                                     description="Lane L3 SM-L6 season-matched L6 (history only)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("loyo")
    for flag in ("--research-root", "--nbm-corpus", "--l6-state", "--mg2-coefficients", "--rule", "--out"):
        a.add_argument(flag, required=True)
    f = sub.add_parser("final")
    for flag in ("--research-root", "--loyo-result", "--rule", "--out-dir", "--commit"):
        f.add_argument(flag, required=True)
    e = sub.add_parser("dev-emit")
    for flag in ("--state-dir", "--state-sha256", "--captured-dir", "--frozen-l6-state", "--mg2-coefficients",
                 "--layout", "--out-dir"):
        e.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "loyo":
        out = loyo(research_root=args.research_root, nbm_corpus=args.nbm_corpus, l6_state=args.l6_state,
                   mg2_coefficients=args.mg2_coefficients, rule=args.rule, out_path=args.out)
        print(json.dumps({"decision": out["decision"],
                          "season": {k: out["season_matched_loyo"][k].get("pooled") for k, _ in PERIODS},
                          "frozen_ref": out["frozen_augsep_reference"]["oct_dec"].get("pooled")}, indent=1))
    elif args.cmd == "dev-emit":
        print(json.dumps(dev_emit(state_dir=args.state_dir, state_sha=args.state_sha256,
                                  captured_dir=args.captured_dir, frozen_l6_state=args.frozen_l6_state,
                                  mg2_coefficients=args.mg2_coefficients, layout=args.layout,
                                  out_dir=args.out_dir), indent=1, sort_keys=True))
    else:
        print(json.dumps(final(research_root=args.research_root, loyo_result=args.loyo_result, rule=args.rule,
                               out_dir=args.out_dir, commit=args.commit), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
