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
    payload = {
        "label": "SM-L6 season-matched L6 stack, LOYO 2021-25 Oct-Dec 07-12 vs the MG-1 analogue, history only; "
                 "MG-2 l6_stack coefficients frozen as bound, only the HGB swapped",
        "rule_sha256": RULE_SHA256, "module_sha256": _sha(__file__),
        "decision": decision, "decision_basis": "pooled Oct-Dec dB upper bound (97.5%) < 0",
        "season_matched_loyo": season, "frozen_augsep_reference": reference, "rmse_f": rmse, "folds": folds,
        "training": {"rows": int(len(train)), "first": str(train.local_date.min()),
                     "last": str(train.local_date.max()), "months": list(TRAIN_MONTHS)},
        "coef": coef, "coef_sha256": cs.MG2_COEF_SHA256, "frozen_l6_sha256": cs.L6_STATE_SHA256,
        "inputs": dict(prov, nbm_corpus_sha256=NBM_CORPUS_SHA256), "scored_rows": int(len(rows))}
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
    args = parser.parse_args(argv)
    if args.cmd == "loyo":
        out = loyo(research_root=args.research_root, nbm_corpus=args.nbm_corpus, l6_state=args.l6_state,
                   mg2_coefficients=args.mg2_coefficients, rule=args.rule, out_path=args.out)
        print(json.dumps({"decision": out["decision"],
                          "season": {k: out["season_matched_loyo"][k].get("pooled") for k, _ in PERIODS},
                          "frozen_ref": out["frozen_augsep_reference"]["oct_dec"].get("pooled")}, indent=1))
    else:
        print(json.dumps(final(research_root=args.research_root, loyo_result=args.loyo_result, rule=args.rule,
                               out_dir=args.out_dir, commit=args.commit), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
