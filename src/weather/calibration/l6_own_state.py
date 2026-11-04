"""Fit, once, the frozen L6 own-model state that ``weather.model.mg_serve_core`` serves (research only).

Guards: master ruling D2 (i) of 2026-10-26 (frozen L6 own-model state, sha-bound, fitted once, no per-run refit
in any serve path; not part of MG-2's binding). The ledger row is drafted before the fit.

``fit`` uses L6's own history fit, unchanged: ``upstream_obs_screen.build_history``, the primary training months
(``TRAIN_MONTHS_PRIMARY``) and ``make_model(OWN)``, as ``r0_ols_floor_challenger.l6_captured_nowcasts`` and
``mg2_composite.captured_nowcast`` refit it per run. It writes ``l6_own_state.pkl`` (schema
``mg_serve_core.L6_STATE_SCHEMA``) and a sidecar with the file sha256 and provenance.

``control`` loads the state by its bound sha through the serve core and reproduces two references to 1e-9:

* L6's own ``n_own`` on L6's IEM serve features (``<research>/upstream_obs/screen``), the control L3 ran;
* L3's captured nowcasts (``l6cap/nowcasts.parquet``) from their captured serve features.

The history ends 2025-12-31; no 2026 outcome is read. Refuses the capture host, through the research guards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from pathlib import Path

from weather.calibration import r0_ols_floor_challenger as _l3  # noqa: F401  (capture-host guard)
from weather.calibration import upstream_obs_screen as l6
from weather.model import mg_serve_core as core

STATE_FILE = "l6_own_state.pkl"
SIDECAR = "l6_own_state.json"
CONTROL_TOLERANCE = 1e-9


class L6StateError(RuntimeError):
    """The fit or the control cannot proceed honestly."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit(research_root, out_dir, commit):
    import sklearn

    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise L6StateError(f"output directory {out} must be new or empty")
    if tuple(l6.OWN) != core.L6_OWN_COLUMNS:
        raise L6StateError("upstream_obs_screen.OWN differs from mg_serve_core.L6_OWN_COLUMNS")
    hist, prov = l6.build_history(research_root)
    train = hist[hist.month.isin(l6.TRAIN_MONTHS_PRIMARY)].reset_index(drop=True)
    if train.local_date.max() > "2025-12-31":
        raise L6StateError("training history extends past 2025-12-31")
    model = l6.make_model(l6.OWN).fit(train[list(l6.OWN)].to_numpy(float), train.y.to_numpy(float))
    provenance = {"commit": commit, "upstream_obs_screen_sha256": _sha(l6.__file__),
                  "l6_own_state_module_sha256": _sha(__file__), **prov,
                  "train_months": list(l6.TRAIN_MONTHS_PRIMARY), "train_rows": int(len(train)),
                  "train_first": str(train.local_date.min()), "train_last": str(train.local_date.max()),
                  "hgb_params": dict(l6.HGB_PARAMS), "sklearn": sklearn.__version__,
                  "python": sys.version.split()[0]}
    state = {"schema": core.L6_STATE_SCHEMA, "columns": list(l6.OWN), "model": model, "provenance": provenance}
    out.mkdir(parents=True, exist_ok=True)
    path = out / STATE_FILE
    path.write_bytes(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL))
    sidecar = dict(provenance, state_sha256=_sha(path), schema=core.L6_STATE_SCHEMA)
    (out / SIDECAR).write_text(json.dumps(sidecar, indent=1, sort_keys=True), encoding="utf-8")
    return sidecar


def _gap(state, features_path, nowcasts_path):
    import numpy as np
    import pandas as pd

    feat = pd.read_parquet(features_path)
    ref = pd.read_parquet(nowcasts_path).set_index("row_key")
    got = core.l6_own_nowcast(state, feat)
    want = ref.n_own.reindex(feat.row_key).to_numpy(float)
    both = np.isfinite(got) | np.isfinite(want)
    gap = float(np.nanmax(np.abs(got[both] - want[both]))) if both.any() else float("nan")
    return {"features": str(features_path), "features_sha256": _sha(features_path),
            "nowcasts": str(nowcasts_path), "nowcasts_sha256": _sha(nowcasts_path), "rows": int(len(feat)),
            "max_abs_gap": gap, "pass": bool(gap <= CONTROL_TOLERANCE)}


def control(state_path, state_sha, research_root, captured_dir, out):
    state = core.load_l6_own_state(state_path, state_sha)
    screen = Path(research_root) / "upstream_obs" / "screen"
    result = {"state": str(state_path), "state_sha256": state_sha, "tolerance": CONTROL_TOLERANCE,
              "l6_iem": _gap(state, screen / "serve_features.parquet", screen / "nowcasts.parquet"),
              "l3_captured": _gap(state, Path(captured_dir) / "serve_features.parquet",
                                  Path(captured_dir) / "nowcasts.parquet")}
    result["pass"] = result["l6_iem"]["pass"] and result["l3_captured"]["pass"]
    out = Path(out)
    if out.exists():
        raise L6StateError(f"{out} exists")
    out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.l6_own_state", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fit", help="fit the frozen L6 own-model state once")
    f.add_argument("--research-root", required=True)
    f.add_argument("--out-dir", required=True)
    f.add_argument("--commit", required=True, help="the source commit, recorded in the provenance")
    c = sub.add_parser("control", help="reproduce L6's and L3's n_own from the frozen state")
    c.add_argument("--state", required=True)
    c.add_argument("--state-sha256", required=True)
    c.add_argument("--research-root", required=True)
    c.add_argument("--captured-dir", required=True)
    c.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "fit":
        result = fit(args.research_root, args.out_dir, args.commit)
    else:
        result = control(args.state, args.state_sha256, args.research_root, args.captured_dir, args.out)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if args.command == "fit" or result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
