"""Research only: L15 rung R-S, NBM TXNSD spread information on P3d_N_fix (2026-10-25).

The arm is lane L2's P3d_N_fix (``pooled_residual_model``, rung 07-12 R-A form). R-S changes one thing: the
per-row scale ``s`` of its kernel-smoothed residual distribution is multiplied by ``exp(m)``, where
``m = clip(beta_h * (x - xbar), -ln 2, ln 2)`` and ``x`` is the day's NBP 07Z TXNSD as a log anomaly against the
same market's previous 14 bulletins. The mean, the floor censoring, the z set and the climatology mix are
unchanged, and ``xbar`` centres the modulation to mean zero over each fit's own training rows (no global
sharpening). The rule is pre-registered outside the repository (``C:\\t\\l15\\rule_rs.md``, sha256
:data:`RS_RULE_SHA256`) and copied under ``docs/research/l15-spread-info-2026-10-25/``.

Stages (CLI subcommands; heavy ones run only through ``scripts/ops/workstation_heavy.ps1``):

``rs-loyo``
    Gate 1 (and the 13-16 secondary LOYO): strictly nested leave-one-year-out on the 2021-25 Aug-Sep rows, R-A's
    LOYO Brier reproduced at beta = 0 as the positive control, plus the frozen dev coefficient per hour.
``rs-emit``
    Dev vectors for P3d_N_fix (byte-identical control against R-A / R-H) and P3d_N_fix_S, only after the block's
    LOYO gate passed.
``rs-score``
    Gate 2 (dev against the unmodulated arm) and gate 3 (against L6, read as in R-F) on the dev scorecard.

Boundaries: offline, no network, never imported by serving, capture or release code (importing it on the
capture host raises ``ProductionImportRefused`` through ``pooled_residual_model``). Outputs must lie outside the
repository. Nothing dated after 2026-09-29 is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from weather.calibration import pooled_residual_model as prm  # refuses to load on the capture host

RS_RULE_SHA256 = "70908316df5066fe5d000fa8d84d0ec2b1f384285a1d3f68b311b9d24cf93ff9"
RS_PLAN_SHA256 = "523d334e65e6a7af335ec2f98734a26e6368d33654816a4f198f9014fac00483"
RS_BETA_GRID = tuple(round(0.05 * i, 2) for i in range(31))  # 0.00 .. 1.50, contains 0
RS_WINDOW_DAYS = 14
RS_MIN_PRIOR = 5
RS_CLIP = math.log(2.0)
RS_TRAIN_CORPUS_SHA256 = "1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd"
RS_DEV_CORPUS_SHA256 = "85746b7a560116f632436b24f268938a0a4ec47bf6d748aacba6e0abef257727"
BLOCKS = {
    "0712": {"hours": (7, 8, 9, 10, 11, 12), "fix_sha256": prm.RI_FIX_SHA256, "gate": "primary"},
    "1316": {"hours": (13, 14, 15, 16), "fix_sha256": prm.DIAG_RH_FIX_SHA256, "gate": "secondary"},
}
FAST_STEP = 0.001
FAST_MARGIN = 6.0
EXACT_TOP = 3
TABLE_TOLERANCE = 1e-6
LAST_ALLOWED = date(2026, 9, 29)


class SpreadRungError(ValueError):
    """An input breaks the R-S row, control or gate contract."""


# ----------------------------------------------------------------------------- predictor


def load_sd_table(path):
    """L9-format NBP corpus -> ({(market, day): [(cycle, lm, (mean, sd))]}, {market: {day: log sd}} for 07Z)."""
    from datetime import datetime

    table, logsd = defaultdict(list), defaultdict(dict)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if date.fromisoformat(r["target_date"][:10]) > LAST_ALLOWED:
            raise SpreadRungError(f"NBM corpus row after {LAST_ALLOWED}: {r['target_date']}")
        if not r["available"] or r["mean"] is None:
            continue
        lm = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
        sd = None if r.get("sd") is None else float(r["sd"])
        table[(r["market_id"], r["target_date"])].append((r["cycle"], lm, (float(r["mean"]), sd)))
        if r["cycle"] == "07" and sd is not None and sd >= 1.0:
            logsd[r["market_id"]][r["target_date"]] = math.log(sd)
    return table, logsd


def trailing_baseline(logsd_by_day, day, window=RS_WINDOW_DAYS, minimum=RS_MIN_PRIOR):
    """Mean log sd of the market's 07Z bulletins for target dates day-window .. day-1, or None."""
    d = date.fromisoformat(str(day)[:10])
    values = [logsd_by_day[k] for k in ((d - timedelta(days=i)).isoformat() for i in range(1, window + 1))
              if k in logsd_by_day]
    return sum(values) / len(values) if len(values) >= minimum else None


def spread_anomaly(sd, baseline):
    """x = log(sd) - baseline; 0 when sd is missing or below 1, or the baseline is missing."""
    if sd is None or baseline is None:
        return 0.0
    try:
        sd = float(sd)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(sd) or sd < 1.0:
        return 0.0
    return math.log(sd) - baseline


def modulation(x, xbar, beta):
    """m = clip(beta * (x - xbar), -ln 2, ln 2) (numpy arrays or floats)."""
    import numpy as np

    return np.clip(beta * (np.asarray(x, dtype=float) - xbar), -RS_CLIP, RS_CLIP)


def modulated_scale(s, x, xbar, beta):
    import numpy as np

    return np.maximum(prm.MIN_SCALE, np.asarray(s, dtype=float) * np.exp(modulation(x, xbar, beta)))


def training_x(frame, table, logsd, timezones, nbm_at_cutoff):
    """Per training row: the anomaly x of the bulletin the anchor uses (0 when the anchor is imputed)."""
    import numpy as np

    xs, stats = [], defaultdict(int)
    for market, day, hour, fh in zip(frame["market"], frame["target_date"], frame["hour"], frame["fh"]):
        day = str(day)[:10]
        value, _ = nbm_at_cutoff(table, market, day, int(hour), timezones[market])
        if value is None:
            stats["anchor_imputed_x0"] += 1
            xs.append(0.0)
            continue
        mean, sd = value
        if not (math.isfinite(float(fh)) and float(fh) == mean):
            raise SpreadRungError(f"anchor mismatch {market} {day} h{hour}: {fh} vs corpus {mean}")
        base = trailing_baseline(logsd.get(market, {}), day)
        x = spread_anomaly(sd, base)
        if base is None:
            stats["baseline_missing_x0"] += 1
        elif sd is None or sd < 1.0:
            stats["sd_missing_x0"] += 1
        else:
            stats["x_defined"] += 1
        xs.append(x)
    return np.asarray(xs, dtype=float), dict(stats)


# ----------------------------------------------------------------------------- distributions


class KernelTable:
    """Tabulated kernel CDF G(t) = mean_j Phi((t - z_j) / bandwidth), for the beta search only."""

    def __init__(self, z):
        import numpy as np
        from scipy.special import ndtr

        z = np.asarray(z, dtype=float)
        self.zmin, self.zmax = float(np.min(z)), float(np.max(z))
        self.t = np.arange(self.zmin - FAST_MARGIN, self.zmax + FAST_MARGIN + FAST_STEP, FAST_STEP)
        g = np.zeros(len(self.t))
        for start in range(0, len(self.t), 2000):
            part = self.t[start:start + 2000]
            g[start:start + 2000] = ndtr((part[:, None] - z[None, :]) / prm.KERNEL_BANDWIDTH).mean(axis=1)
        self.g = g

    def cdf(self, t):
        import numpy as np

        return np.interp(t, self.t, self.g)


def fast_brier(yhat, s, floor, table, p_clim, actual):
    """Multi-category Brier (``fm.brier_score`` form) of ``predictive_distribution`` on the tabulated kernel CDF."""
    import numpy as np
    from weather.units import round_half_up

    lo = math.floor(yhat + s * (table.zmin - 1.5))
    hi = math.ceil(yhat + s * (table.zmax + 1.5))
    ks = np.arange(lo, hi + 1)
    edges = np.append(ks - 0.5, hi + 0.5)
    mass = np.diff(table.cdf((edges - yhat) / s))
    mass = mass / mass.sum()
    dist = dict(zip(ks.tolist(), mass.tolist()))
    if floor is not None and math.isfinite(floor):
        fb = int(round_half_up(floor))
        below = sum(v for k, v in dist.items() if k < fb)
        dist = {k: v for k, v in dist.items() if k >= fb}
        dist[fb] = dist.get(fb, 0.0) + below
    out = {k: (1.0 - prm.FLOOR_MIX_CLIM) * v for k, v in dist.items()}
    for k, v in p_clim.items():
        out[int(k)] = out.get(int(k), 0.0) + prm.FLOOR_MIX_CLIM * float(v)
    total = sum(out.values())
    return sum((v / total - (1.0 if k == actual else 0.0)) ** 2 for k, v in out.items())


def exact_dist(row, s):
    return prm.predictive_distribution(row["yhat"], float(s), row["F"], row["z"], row["buckets"], row["p_clim"])


def exact_brier(row, s):
    from weather.calibration import feature_model as fm

    return fm.brier_score(exact_dist(row, s), row["actual"])


def predict_rows(entry, val, buckets, x_val, xbar):
    """P3d_N_fix inputs of every validation row: yhat, s, F, z, p_clim (``_dist_from_fit`` arithmetic)."""
    import numpy as np
    from weather.calibration import feature_model as fm

    fitted = entry["fit"]
    rows = []
    for market in sorted(val["market"].unique()):
        sel = (val["market"] == market).to_numpy()
        part = val[sel].reset_index(drop=True)
        xs = x_val[sel]
        yhat, X = fitted["mean"].predict(part)
        gap = np.nan_to_num(yhat - part["F"].to_numpy(float), nan=0.0)
        s = np.maximum(prm.MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap])) * math.sqrt(math.pi / 2))
        p_clim = fm.smoothed_dist(entry["train_y"][market], buckets[market], alpha=0.10)
        for i in range(len(part)):
            rows.append({"market": market, "date": str(part.at[i, "target_date"])[:10],
                         "actual": int(part.at[i, "y"]) if math.isfinite(float(part.at[i, "y"])) else None,
                         "yhat": float(yhat[i]), "s": float(s[i]), "F": float(part["F"].iat[i]), "x": float(xs[i]),
                         "xbar": float(xbar), "z": fitted["z"], "buckets": buckets[market], "p_clim": p_clim,
                         "table": entry["table"]})
    return rows


def select_beta(rows, grid=RS_BETA_GRID, top=EXACT_TOP):
    """Grid minimiser of summed Brier: tabulated search, then the best ``top`` (and beta 0) re-scored exactly.

    Ties (within 1e-12) go to the smallest beta. Returns (beta, {beta: exact summed Brier}, max table error).
    """
    import numpy as np

    approx = np.zeros(len(grid))
    for row in rows:
        for j, beta in enumerate(grid):
            s = float(modulated_scale(row["s"], row["x"], row["xbar"], beta))
            approx[j] += fast_brier(row["yhat"], s, row["F"], row["table"], row["p_clim"], row["actual"])
    order = sorted(range(len(grid)), key=lambda j: (approx[j], grid[j]))[:top]
    candidates = sorted(set(order) | {grid.index(0.0)})
    exact = {}
    for j in candidates:
        beta = grid[j]
        exact[beta] = sum(exact_brier(r, float(modulated_scale(r["s"], r["x"], r["xbar"], beta))) for r in rows)
    error = max(abs(exact[grid[j]] - approx[j]) / max(1, len(rows)) for j in candidates)
    best = min(exact.values())
    beta = min(b for b, v in exact.items() if v <= best + 1e-12)
    return beta, exact, float(error)


# ----------------------------------------------------------------------------- gate 1: nested LOYO


def _fit(at_hour, x_hour, excluded):
    """P3d_N_fix fit on the years outside ``excluded``, with its kernel table and training-mean anomaly."""
    sel = (~at_hour["year"].isin(sorted(excluded))).to_numpy()
    train = at_hour[sel].reset_index(drop=True)
    entry = prm._rung_entry(train, *prm._arm_spec(prm.RUNG_ARMS["P3d_N_fix"]))
    entry["table"] = KernelTable(entry["fit"]["z"])
    entry["xbar"] = float(x_hour[sel].mean())
    return entry


def rs_loyo(frame, x, buckets, hours):
    """Nested LOYO per hour; returns (rows, per (hour, held) betas, dev betas, diagnostics)."""
    import numpy as np

    rows, betas, dev, diag = [], {}, {}, {}
    for hour in hours:
        mask = (frame["hour"] == hour).to_numpy()
        at_hour = frame[mask].reset_index(drop=True)
        x_hour = x[mask]
        years = sorted(int(y) for y in at_hour["year"].unique())
        fits = {}

        def fit(excluded):
            key = frozenset(excluded)
            if key not in fits:
                fits[key] = _fit(at_hour, x_hour, key)
            return fits[key]

        def preds(excluded, target):
            entry = fit(excluded)
            sel = (at_hour["year"] == target).to_numpy()
            return predict_rows(entry, at_hour[sel].reset_index(drop=True), buckets, x_hour[sel], entry["xbar"])

        plain = {}
        for held in years:
            inner = [r for other in years if other != held for r in preds({other, held}, other)]
            beta, exact, err = select_beta(inner)
            if err > TABLE_TOLERANCE:
                raise SpreadRungError(f"kernel table error {err} above {TABLE_TOLERANCE} (h{hour} held {held})")
            if exact[beta] > exact[0.0] + 1e-12:
                raise SpreadRungError(f"beta {beta} worsened its own training score (h{hour} held {held})")
            betas[(hour, held)] = {"beta": beta, "inner_brier_beta0": exact[0.0], "inner_brier_beta": exact[beta],
                                   "inner_rows": len(inner), "table_error_per_row": err}
            plain[held] = preds({held}, held)
            for r in plain[held]:
                s_mod = float(modulated_scale(r["s"], r["x"], r["xbar"], beta))
                b0, b1 = exact_brier(r, r["s"]), exact_brier(r, s_mod)
                d0, d1 = exact_dist(r, r["s"]), exact_dist(r, s_mod)
                rows.append({"hour": int(hour), "year": int(held), "market": r["market"], "date": r["date"],
                             "beta": beta, "x": r["x"], "m": float(modulation(r["x"], r["xbar"], beta)),
                             "P3d_N_fix_brier": b0, "P3d_N_fix_S_brier": b1,
                             "P3d_N_fix_log": _log(d0, r["actual"]), "P3d_N_fix_S_log": _log(d1, r["actual"])})
            print(f"rs loyo h{hour:02d} held {held}: beta {beta}", flush=True)
        all_rows = [r for held in years for r in plain[held]]
        beta, exact, err = select_beta(all_rows)
        if err > TABLE_TOLERANCE:
            raise SpreadRungError(f"kernel table error {err} above {TABLE_TOLERANCE} (dev beta h{hour})")
        full_xbar = float(x_hour.mean())
        dev[hour] = {"beta": beta, "xbar_all_years": full_xbar, "oof_brier_beta0": exact[0.0],
                     "oof_brier_beta": exact[beta], "rows": len(all_rows), "table_error_per_row": err}
        diag[hour] = {"share_x_zero": float(np.mean(x_hour == 0.0)), "x_mean": float(x_hour.mean()),
                      "x_sd": float(x_hour.std()), "rows": int(len(x_hour))}
        print(f"rs dev beta h{hour:02d}: {beta}", flush=True)
    return rows, betas, dev, diag


def _log(dist, actual):
    from weather.calibration import feature_model as fm

    return fm.log_loss(dist, actual)


def loyo_summary(rows, draws=prm.BOOTSTRAP_DRAWS, seed=prm.BOOTSTRAP_SEED):
    """S - unmodulated per hour and pooled (mean per row), date-clustered bootstrap."""
    import numpy as np

    out = {}
    groups = {f"h{h:02d}": [r for r in rows if r["hour"] == h] for h in sorted({r["hour"] for r in rows})}
    groups["pooled"] = rows
    rng = np.random.default_rng(seed)
    for name, rs in groups.items():
        for metric in ("brier", "log"):
            by_date = defaultdict(list)
            for r in rs:
                by_date[r["date"]].append(r[f"P3d_N_fix_S_{metric}"] - r[f"P3d_N_fix_{metric}"])
            dates = sorted(by_date)
            sums = np.array([sum(by_date[d]) for d in dates])
            counts = np.array([len(by_date[d]) for d in dates])
            idx = rng.integers(0, len(dates), size=(draws, len(dates)))
            boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
            out[f"{name}|{metric}"] = {
                "S_minus_unmod": float(sums.sum() / counts.sum()),
                "ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
                "unmod_mean": float(np.mean([r[f"P3d_N_fix_{metric}"] for r in rs])),
                "mean_abs_m": float(np.mean([abs(r["m"]) for r in rs])),
                "mean_m": float(np.mean([r["m"] for r in rs])), "n": len(rs), "n_dates": len(dates)}
    return out


def _training_inputs(records_root, nbm_train_corpus, markets, hours):
    from weather.calibration import ols_floor_ladder as l9
    from weather.market.market_registry import spec_for_id

    sha = hashlib.sha256(Path(nbm_train_corpus).read_bytes()).hexdigest()
    if sha != RS_TRAIN_CORPUS_SHA256:
        raise SpreadRungError(f"training NBM corpus sha {sha} != {RS_TRAIN_CORPUS_SHA256}")
    timezones = {m: spec_for_id(m).timezone for m in markets}
    frame, buckets = prm.dev_training_frame(records_root, markets)
    if frame["year"].max() >= 2026:
        raise SpreadRungError("a training row is from 2026")
    frame, train_stats = prm.attach_training_nbm(frame, l9.load_nbm(nbm_train_corpus), l9.nbm_at_cutoff, timezones)
    frame = frame[frame["hour"].isin(hours)].reset_index(drop=True)
    table, logsd = load_sd_table(nbm_train_corpus)
    x, x_stats = training_x(frame, table, logsd, timezones, l9.nbm_at_cutoff)
    return frame, buckets, x, {"train_nbm": train_stats, "x": x_stats, "nbm_train_corpus": sha}


def rung_s_loyo(*, records_root, nbm_train_corpus, ra_loyo_rows, out_dir, block, markets=prm.R0_MARKETS):
    """Gate 1 (block 0712) or the secondary LOYO (block 1316), and the frozen dev betas."""
    out = prm.require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = (f"rs_loyo_{block}.json", f"rs_loyo_rows_{block}.jsonl")
    for name in names:
        if (out / name).exists():
            raise SpreadRungError(f"refusing to overwrite {out / name}")
    hours = BLOCKS[block]["hours"]
    frame, buckets, x, inputs = _training_inputs(records_root, nbm_train_corpus, markets, hours)
    rows, betas, dev, diag = rs_loyo(frame, x, buckets, hours)
    controls = {}
    if block == "0712":
        ra = {}
        with open(ra_loyo_rows, encoding="utf-8") as handle:
            for line in handle:
                r = json.loads(line)
                ra[(r["hour"], r["market"], r["date"])] = r["P3d_N_fix_brier"]
        worst = max(abs(r["P3d_N_fix_brier"] - ra[(r["hour"], r["market"], r["date"])]) for r in rows)
        if len(ra) != len(rows) or worst > 1e-9:
            raise SpreadRungError(f"R-A LOYO control failed: rows {len(rows)} vs {len(ra)}, max diff {worst}")
        controls = {"ra_loyo_rows": len(ra), "ra_max_abs_diff": worst,
                    "ra_loyo_rows_sha256": hashlib.sha256(Path(ra_loyo_rows).read_bytes()).hexdigest()}
    prm._write_jsonl(out / names[1], rows)
    summary = loyo_summary(rows)
    result = {"rule_sha256": RS_RULE_SHA256, "block": block, "gate": BLOCKS[block]["gate"], "hours": list(hours),
              "inputs": {**inputs, "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         "prm_module_sha256": hashlib.sha256(Path(prm.__file__).read_bytes()).hexdigest()},
              "controls": controls, "betas": {f"h{h:02d}|{y}": v for (h, y), v in sorted(betas.items())},
              "dev_betas": {f"h{h:02d}": v for h, v in sorted(dev.items())}, "x_diagnostics":
                  {f"h{h:02d}": v for h, v in sorted(diag.items())}, "summary": summary,
              "loyo_pass": summary["pooled|brier"]["ci95"][1] < 0}
    (out / names[0]).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ----------------------------------------------------------------------------- dev emission


def rung_s_emit(*, records_root, layout, replay_root, nbm_train_corpus, nbm_dev_corpus, loyo_result, out_dir, block,
                markets=prm.R0_MARKETS):
    """Dev vectors: P3d_N_fix (control, byte-identical to R-A / R-H) and P3d_N_fix_S with the frozen betas."""
    import numpy as np
    import pandas as pd
    from zoneinfo import ZoneInfo

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.r0_ols_floor_devfit import usable_v2_mean
    from weather.market.market_registry import spec_for_id
    from weather.calibration import feature_model as fm
    from weather.model import observed_running_max
    from weather.units import round_half_up

    loyo = json.loads(Path(loyo_result).read_bytes())
    if loyo.get("rule_sha256") != RS_RULE_SHA256 or loyo.get("block") != block or not loyo.get("loyo_pass"):
        raise SpreadRungError("the block's LOYO gate has not passed under this rule; dev may not run (KILL applies)")
    dev_sha = hashlib.sha256(Path(nbm_dev_corpus).read_bytes()).hexdigest()
    if dev_sha != RS_DEV_CORPUS_SHA256:
        raise SpreadRungError(f"dev NBM corpus sha {dev_sha} != {RS_DEV_CORPUS_SHA256}")
    hours = BLOCKS[block]["hours"]
    running_max = prm._require_metar_only(observed_running_max.running_max_since_midnight)
    out = prm.require_output_outside_repo(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {arm: out / f"dev_{arm}.jsonl" for arm in ("P3d_N_fix", "P3d_N_fix_S")}
    for path in paths.values():
        if path.exists():
            raise SpreadRungError(f"refusing to overwrite {path}")
    frame, buckets, x, inputs = _training_inputs(records_root, nbm_train_corpus, markets, hours)
    fits = prm.rung_fits(frame, hours, arms={"P3d_N_fix": prm.RUNG_ARMS["P3d_N_fix"]})
    frozen = {}
    for hour in hours:
        xbar = float(x[(frame["hour"] == hour).to_numpy()].mean())
        want = loyo["dev_betas"][f"h{hour:02d}"]
        if abs(xbar - want["xbar_all_years"]) > 1e-12:
            raise SpreadRungError(f"h{hour}: xbar {xbar} != LOYO {want['xbar_all_years']}")
        frozen[hour] = (float(want["beta"]), xbar)
    _, dev_logsd = load_sd_table(nbm_dev_corpus)
    coords = prm.station_coordinates(markets)
    snaps = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=[
        "snapshot_id", "market", "target_date", "local_hour", "cutoff_hour",
        "v2_mean", "v2_stddev", "v2_available_at", "captured_at_utc"])
    if (pd.to_datetime(snaps.target_date).dt.date > prm.N_DEV_LAST).any():
        raise SpreadRungError("layout holds a snapshot after 2026-09-29")
    snaps = snaps.assign(nbm_usable=usable_v2_mean(snaps))
    audit = {"rule_sha256": RS_RULE_SHA256, "block": block, "hours": list(hours), "frozen": {
        f"h{h:02d}": {"beta": b, "xbar": xb} for h, (b, xb) in frozen.items()}, "markets": {},
        "inputs": {**inputs, "nbm_dev_corpus": dev_sha, "loyo_result_sha256": hashlib.sha256(
            Path(loyo_result).read_bytes()).hexdigest(),
            "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "prm_module_sha256": hashlib.sha256(Path(prm.__file__).read_bytes()).hexdigest()}}
    m_values, x_zero, below_floor_diff = [], 0, 0.0
    writers = {arm: open(path, "w", encoding="utf-8") for arm, path in paths.items()}
    try:
        for market in markets:
            spec = spec_for_id(market)
            tz = ZoneInfo(spec.timezone)
            folders = {target: folder for slug, target, folder in l3._event_folders(replay_root)
                       if slug == market and prm.N_DEV_FIRST <= target <= prm.N_DEV_LAST}
            stats = defaultdict(int)
            lat, lon, elev = coords[market]
            rows = snaps[snaps.market == market].copy()
            rows["target"] = pd.to_datetime(rows.target_date).dt.date
            for target, group in rows.groupby("target"):
                folder = folders.get(target)
                eligible = []
                for row in group.itertuples(index=False):
                    try:
                        hour = int(str(row.cutoff_hour))
                    except ValueError:
                        hour = None
                    if hour not in hours:
                        stats["outside_cutoff_hours"] += 1
                    elif int(row.local_hour) < hour:
                        stats["local_hour_before_cutoff"] += 1
                    elif not math.isfinite(float(row.nbm_usable)):
                        stats["no_usable_nbm"] += 1
                    elif folder is None:
                        stats["no_replay_folder"] += 1
                    else:
                        eligible.append((row, hour))
                if not eligible:
                    continue
                base = trailing_baseline(dev_logsd.get(market, {}), target.isoformat())
                with open(Path(folder) / "replay_inputs.jsonl", "rb") as handle:
                    index = prm.replay_index(handle, target, tz)
                    cache, parsed = {}, {}
                    for row, hour in eligible:
                        captured = pd.Timestamp(row.captured_at_utc)
                        captured = (captured.tz_localize("UTC") if captured.tzinfo is None else captured)
                        entry = prm.latest_at_or_before(index, captured.to_pydatetime())
                        if entry is None:
                            stats["no_replay_snapshot_at_or_before_capture"] += 1
                            continue
                        key = (entry[1], hour)
                        if key not in cache:
                            if entry[1] not in parsed:
                                handle.seek(entry[1])
                                try:
                                    parsed = {entry[1]: json.loads(handle.read(entry[2]))}
                                except json.JSONDecodeError:
                                    parsed = {entry[1]: None}
                            snap = parsed[entry[1]]
                            cache[key] = None if snap is None else prm.rung_inputs(
                                snap, target, tz, hour, spec.display_unit, entry[0], running_max,
                                l3.observations_at_cutoff)
                        rec = cache[key]
                        if rec is None:
                            stats["corrupt_replay_line"] += 1
                            continue
                        if rec["high_so_far"] is None or rec["current_temp"] is None:
                            stats["missing_metar_feature"] += 1
                            continue
                        doy = target.timetuple().tm_yday
                        one = pd.DataFrame([{
                            "market": market, "centre": prm.nearest_centre(target.isoformat()), "season": "aug_sep",
                            "hour": hour, "target_date": target.isoformat(), "year": target.year, "y": float("nan"),
                            "F": float(rec["high_so_far"]), "fh": float(row.nbm_usable), "lat": lat, "lon": lon,
                            "elev": elev, "doy_sin": math.sin(2 * math.pi * doy / 365.25),
                            "doy_cos": math.cos(2 * math.pi * doy / 365.25),
                            "x_high_so_far": float(rec["high_so_far"]), "x_current_temp": float(rec["current_temp"]),
                            "market_code": float(prm.R0_MARKETS.index(market))}])
                        fit_entry = fits[("P3d_N_fix", hour)]
                        fitted = fit_entry["fit"]
                        yhat, X = fitted["mean"].predict(one)
                        gap = np.nan_to_num(yhat - one["F"].to_numpy(float), nan=0.0)
                        s = np.maximum(prm.MIN_SCALE, fitted["scale"].predict(np.column_stack([X, gap]))
                                       * math.sqrt(math.pi / 2))
                        p_clim = fm.smoothed_dist(fit_entry["train_y"][market], buckets[market], alpha=0.10)
                        beta, xbar = frozen[hour]
                        xv = spread_anomaly(row.v2_stddev, base)
                        x_zero += xv == 0.0
                        m = float(modulation(xv, xbar, beta))
                        m_values.append(m)
                        s_mod = float(modulated_scale(float(s[0]), xv, xbar, beta))
                        d0 = prm.predictive_distribution(float(yhat[0]), float(s[0]), float(one["F"].iat[0]),
                                                         fitted["z"], buckets[market], p_clim)
                        d1 = prm.predictive_distribution(float(yhat[0]), s_mod, float(one["F"].iat[0]),
                                                         fitted["z"], buckets[market], p_clim)
                        fb = int(round_half_up(float(one["F"].iat[0])))
                        below_floor_diff = max(below_floor_diff, abs(sum(v for k, v in d1.items() if k < fb)
                                                                     - sum(v for k, v in d0.items() if k < fb)))
                        if abs(sum(d1.values()) - 1.0) > 1e-9:
                            raise SpreadRungError("probability mass not preserved")
                        for arm, dist in (("P3d_N_fix", d0), ("P3d_N_fix_S", d1)):
                            writers[arm].write(json.dumps({
                                "market": market, "snapshot_id": row.snapshot_id, "target_date": target.isoformat(),
                                "distribution": {str(b): p for b, p in dist.items() if p > 0}}, sort_keys=True) + "\n")
                        stats["emitted"] += 1
            audit["markets"][market] = dict(stats)
            print(f"rs emit {market}: {dict(stats)}", flush=True)
    finally:
        for w in writers.values():
            w.close()
    if below_floor_diff > 1e-12:
        raise SpreadRungError(f"modulation moved mass below the floor ({below_floor_diff})")
    audit["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()}
    audit["control_pass"] = audit["files"]["dev_P3d_N_fix.jsonl"] == BLOCKS[block]["fix_sha256"]
    audit["dev_modulation"] = {"n": len(m_values), "mean_m": float(np.mean(m_values)) if m_values else None,
                               "mean_abs_m": float(np.mean(np.abs(m_values))) if m_values else None,
                               "share_x_zero": x_zero / max(1, len(m_values)),
                               "flag_mean_m_above_0_05": bool(m_values and abs(np.mean(m_values)) > 0.05),
                               "max_below_floor_mass_change": below_floor_diff}
    (out / "rs_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    if not audit["control_pass"]:
        raise SpreadRungError(f"unmodulated control {audit['files']['dev_P3d_N_fix.jsonl']} != "
                              f"{BLOCKS[block]['fix_sha256']} (R-S refused)")
    return audit


# ----------------------------------------------------------------------------- gates 2-3: dev scorecard


def rung_s_score(*, layout, emit_dir, coefficients, nowcasts, out_path, block, start="2026-08-01", end="2026-09-29"):
    """Gate 2 (S against unmodulated) and gate 3 (S against L6, 07-12 only) on the dev scorecard."""
    import os

    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    out_path = prm.require_output_outside_repo(out_path)
    if out_path.exists():
        raise SpreadRungError(f"refusing to overwrite {out_path}")
    emit = Path(emit_dir)
    audit = json.loads((emit / "rs_emit_audit.json").read_bytes())
    if audit.get("rule_sha256") != RS_RULE_SHA256 or audit.get("block") != block or not audit.get("control_pass"):
        raise SpreadRungError("emit is not an R-S emit of this block with a passing control")
    for name, sha in audit["files"].items():
        if hashlib.sha256((emit / name).read_bytes()).hexdigest() != sha:
            raise SpreadRungError(f"{name} changed since emission")
    hours = BLOCKS[block]["hours"]
    lo_b, hi_b = hours[0], hours[-1]
    with_l6 = block == "0712"
    if with_l6:
        now_sha = hashlib.sha256(Path(nowcasts).read_bytes()).hexdigest()
        if now_sha != prm.L6_NOWCAST_SHA256:
            raise SpreadRungError(f"L6 nowcast sha {now_sha} != {prm.L6_NOWCAST_SHA256}")
        os.environ["L6_NOWCASTS"] = str(nowcasts)
        from weather.reporting.scorecards.free_source_candidates import l6_stack

        l6_stack._CACHE.clear()
        state, part_sha = prm.l6_frozen_state(coefficients)
    start_d, end_d = data.check_range(start, end)
    lay = data.load_layout(layout, data.DEV_FIRST, end_d)
    folds = data.make_folds(lay.dates, start_d, end_d, 7, 1, 7)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(lay, scored)
    date_w = l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED)
    market_b = table.brier(table.p_market)

    def vec(path):
        return l3._vector(table, l3._candidate_frame(str(path), table, lay, folds, data)[0])

    p_fix, cov_fix, r_fix = vec(emit / "dev_P3d_N_fix.jsonl")
    p_s, cov_s, r_s = vec(emit / "dev_P3d_N_fix_S.jsonl")
    p_mg1, _, _ = l3._vector(table, loss_atlas.mg1_frame(table))
    w0712 = (table.local_hour >= 7) & (table.local_hour <= 12)
    _, e = table.cells(table.brier(p_mg1) - market_b, w0712)
    mg1_excess = float(e.mean())
    if round(mg1_excess, 3) != l3.MG1_CONTROL_0712_EXCESS:
        raise SpreadRungError(f"MG-1 positive control failed: {mg1_excess:.5f}")
    probs = {"P3d_N_fix": p_fix, "P3d_N_fix_S": p_s}
    common = cov_fix & cov_s
    controls = {"mg1_excess_07_12": mg1_excess}
    if with_l6:
        p_l6, cov_l6, r_l6 = prm.l6_vector(table, state, l3)
        probs["L6"] = p_l6
        common = common & cov_l6
        controls.update({"l6_part_sha256": part_sha, "l6_nowcast_sha256": now_sha})
    for name, p in probs.items():
        mass = np.add.reduceat(p, table.offsets)
        if np.any(np.abs(mass[common] - 1.0) > 1e-9):
            raise SpreadRungError(f"{name}: probability mass not preserved")
    briers = {k: table.brier(v) for k, v in probs.items()}
    groups = [(block, lo_b, hi_b)] + [(f"h{h:02d}", h, h) for h in hours]
    pools = [(sc.ALL_MARKETS, None)] + [(m, {m}) for m in sorted(set(table.markets))]

    def compare(arm, ref):
        rows = []
        for market, members in pools:
            in_pool = np.ones(len(table.snaps), bool) if members is None else np.isin(table.markets, sorted(members))
            for group, lo, hi in groups if members is None else groups[:1]:
                mask = common & in_pool & (table.local_hour >= lo) & (table.local_hour <= hi)
                if not mask.any():
                    continue
                idx, c = table.cells(briers[arm], mask)
                _, r_ = table.cells(briers[ref], mask)
                _, m = table.cells(market_b, mask)
                rows.append({"arm": arm, "reference": ref, "market": market, "group": group,
                             "n_market_days": int(len(idx)), "n_snapshots": int(mask.sum()),
                             "R_arm": sc.ratio_interval(table.w[:, idx], c, m),
                             "R_reference": sc.ratio_interval(table.w[:, idx], r_, m),
                             "dR_crossed": sc.ratio_interval(table.w[:, idx], c - r_, m),
                             "dR_date_clustered": sc.ratio_interval(date_w[:, idx], c - r_, m)})
        return rows

    def primary(rows):
        return next(r for r in rows if r["market"] == sc.ALL_MARKETS and r["group"] == block)

    def hours_lower(rows):
        return [r["dR_date_clustered"]["ci95"][0] for r in rows if r["market"] == sc.ALL_MARKETS
                and r["group"] != block]

    def reading(rows):
        p = primary(rows)["dR_date_clustered"]["ci95"]
        if p[0] > 0:
            return "HARM"
        return "WIN" if p[1] < 0 and not any(lo > 0 for lo in hours_lower(rows)) else "NULL"

    in_block = (table.local_hour >= lo_b) & (table.local_hour <= hi_b)
    result = {"rule": "C:/t/l15/rule_rs.md", "rule_sha256": RS_RULE_SHA256, "block": block,
              "gate": BLOCKS[block]["gate"],
              "population": {"n_dates": len(scored), "first_date": scored[0], "last_date": scored[-1],
                             "n_market_days": len(table.keys),
                             "common_covered_snapshots": int((common & in_block).sum())},
              "controls": controls, "coverage": {"P3d_N_fix": r_fix, "P3d_N_fix_S": r_s},
              "frozen": audit["frozen"], "dev_modulation": audit["dev_modulation"],
              "inputs": {"emit_files": audit["files"], "emit_audit_sha256": hashlib.sha256(
                  (emit / "rs_emit_audit.json").read_bytes()).hexdigest(),
                  "layout_manifest_sha256": lay.manifest_sha256, "scorecard_code_sha256": sc.code_sha256(),
                  "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
              "gates": {}, "rows": [], "reported": {}}
    rows = compare("P3d_N_fix_S", "P3d_N_fix")
    result["rows"] += rows
    g2 = primary(rows)["dR_date_clustered"]
    result["gates"]["2_dev_vs_unmodulated"] = {
        "dR_date_clustered": g2, "hours_lower": hours_lower(rows),
        "pass": g2["ci95"][1] < 0 and not any(lo > 0 for lo in hours_lower(rows))}
    if with_l6:
        result["rows"] += compare("P3d_N_fix", "L6")  # R-F incumbent control (reported)
        if result["gates"]["2_dev_vs_unmodulated"]["pass"]:
            rows = compare("P3d_N_fix_S", "L6")
            result["rows"] += rows
            result["gates"]["3_vs_L6"] = {"reading": reading(rows),
                                          "dR_date_clustered": primary(rows)["dR_date_clustered"]}
        else:
            result["stopped_at"] = "gate 2 (KILL: NBM-published-spread family closed)"
    elif not result["gates"]["2_dev_vs_unmodulated"]["pass"]:
        result["stopped_at"] = "secondary dev gate failed (13-16; reported, never reopens the primary)"
    # SELECTION EVIDENCE (consumes the market benchmark; never booked as improvement)
    mask = common & in_block
    idx, mden = table.cells(np.ones(len(table.snaps)), mask)
    _, mk = table.cells(market_b, mask)
    result["reported"]["excess_vs_market_SELECTION_EVIDENCE"] = {
        name: sc.ratio_interval(date_w[:, idx], table.cells(b, mask)[1] - mk, mden) for name, b in briers.items()}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ----------------------------------------------------------------------------- CLI


def build_parser():
    parser = argparse.ArgumentParser(prog="weather.calibration.spread_information_rung", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lo = sub.add_parser("rs-loyo", help="R-S gate 1 / secondary LOYO (heavy)")
    lo.add_argument("--records", required=True)
    lo.add_argument("--nbm-train-corpus", required=True)
    lo.add_argument("--ra-loyo-rows", required=True)
    lo.add_argument("--block", choices=sorted(BLOCKS), required=True)
    lo.add_argument("--out", required=True)
    em = sub.add_parser("rs-emit", help="R-S dev vectors after the block's LOYO gate passed (heavy)")
    for name in ("--records", "--layout", "--replay-root", "--nbm-train-corpus", "--nbm-dev-corpus", "--loyo-result",
                 "--out"):
        em.add_argument(name, required=True)
    em.add_argument("--block", choices=sorted(BLOCKS), required=True)
    sc = sub.add_parser("rs-score", help="R-S gates 2-3 on the dev scorecard (heavy)")
    for name in ("--layout", "--emit", "--out"):
        sc.add_argument(name, required=True)
    sc.add_argument("--coefficients")
    sc.add_argument("--nowcasts")
    sc.add_argument("--block", choices=sorted(BLOCKS), required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "rs-loyo":
        result = rung_s_loyo(records_root=args.records, nbm_train_corpus=args.nbm_train_corpus,
                             ra_loyo_rows=args.ra_loyo_rows, out_dir=args.out, block=args.block)
        print(json.dumps({"loyo_pass": result["loyo_pass"], "pooled": result["summary"]["pooled|brier"],
                          "dev_betas": result["dev_betas"]}, indent=1))
    elif args.command == "rs-emit":
        audit = rung_s_emit(records_root=args.records, layout=args.layout, replay_root=args.replay_root,
                            nbm_train_corpus=args.nbm_train_corpus, nbm_dev_corpus=args.nbm_dev_corpus,
                            loyo_result=args.loyo_result, out_dir=args.out, block=args.block)
        print(json.dumps({"files": audit["files"], "control_pass": audit["control_pass"],
                          "dev_modulation": audit["dev_modulation"]}, indent=1))
    elif args.command == "rs-score":
        result = rung_s_score(layout=args.layout, emit_dir=args.emit, coefficients=args.coefficients,
                              nowcasts=args.nowcasts, out_path=args.out, block=args.block)
        print(json.dumps({"gates": result["gates"], "stopped_at": result.get("stopped_at")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
