r"""Toronto (CYYZ) NBM NBP guidance lane L14: MG-1-CYYZ, B_N-CYYZ and ECCC controls in native Celsius.

Research only, development evidence only, no edge claim. Pre-registered in ``C:\t\l14\rule.md``
(sha256 ``RULE_SHA256``). Refuses to import on the dedicated capture host (``loss_atlas`` guard).

Phases::

    corpus     parse the NBP CYYZ block corpus (L12 fetcher, ``--products nbp``) with parser v2 -> rows jsonl
    loyo       blocked leave-one-year-out 2021-25 (Aug-Sep and Oct-Dec blocks): MG-1, B_N, CLIM
    dev-inputs gate 0 on the Toronto replay snapshots (no label is read): coverage, unit sanity, floor parity
    dev-score  dev 2026-08-01..09-29: arms vs served and the capture-time market, date-clustered intervals

Units: NBP is published in F and converted once on read (mean_C = (F - 32) * 5/9, sd_C = sd_F * 5/9); every
label, floor, bucket and bin is whole C. MG-1's 1 F spread floor and B_N's 0.5 F minimum scale are carried
as 5/9 C and 0.5 * 5/9 C. Nothing dated after 2026-09-29 is read.
"""
from __future__ import annotations

from weather.reporting.scorecards import loss_atlas as _la  # fails closed on the capture host

_la.refuse_production_import()

import argparse  # noqa: E402
import csv  # noqa: E402
import gzip  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

RULE_SHA256 = "a3899507c74f2f6cbb210b2c7b8bfb18cd66d8744079ea458cd129a8b6eb1af6"
STATION = "CYYZ"
TZ_NAME = "America/Toronto"
LAST_ALLOWED = date(2026, 9, 29)
DEV_FIRST = date(2026, 8, 1)
TRAIN_YEARS = (2021, 2022, 2023, 2024, 2025)
F_TO_C = 5.0 / 9.0
MG1_SD_FLOOR_C = 1.0 * F_TO_C
MIN_SCALE_C = 0.5 * F_TO_C
KERNEL_BANDWIDTH = 0.25
FLOOR_MIX_CLIM = 0.02
CLIM_ALPHA = 0.10
DRAWS = 2000
SEED_DEV = 20260921
SEED_LOYO = 20261024
MARKET_MAX_AGE_S = 600
LOG_EPS = 1e-4
LABEL_SHA = {
    "pinned": "1ced925a605b6f4e82fa20cbe238b9c91d841a9390da604bc648b630dac920e1",
    "second": "c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a",
}
TAPES_SUMS_SHA = "a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0"
AUGSEP_OBS_SHA = "9f3b2972a44bcff53c295e3cb1c3f290c314f948dfe379feabc02744b573a802"
DEV_OBS_SHA = "bb85d7a554cca7803e542e60ba6c02125d75f888a2f589198e0eec33c7c0798f"
GROUPS = {
    "00-05": range(0, 6), "06-09": range(6, 10), "10-12": range(10, 13), "07-12": range(7, 13),
    "13-16": range(13, 17), "17-23": range(17, 24), "00-16": range(0, 17), "ALL": range(0, 24),
}
_TGROUP = re.compile(r" T([01])(\d{3})([01])(\d{3})")


class Refused(RuntimeError):
    pass


def tz():
    return ZoneInfo(TZ_NAME)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def block_of(day):
    return "aug_sep" if day.month in (8, 9) else "oct_dec"


def guard_date(day):
    if day > LAST_ALLOWED:
        raise Refused(f"refused: date {day} after {LAST_ALLOWED}")
    return day


# ----------------------------------------------------------------------------- NBP corpus

def parse_nbp(text, target):
    """Parser v2 on one CYYZ NBP block, CYYZ mapped to America/Toronto in this process only."""
    from weather.sources import nbm_probabilistic_tmax as nbp

    zones = nbp.NBM_NBP_STATION_TIMEZONES
    added = STATION not in zones
    if added:
        zones[STATION] = TZ_NAME
    try:
        return nbp.parse_nbp_station_tmax(text, STATION, target)
    finally:
        if added:
            zones.pop(STATION, None)


def corpus(nbp_dir, out_path):
    nbp_dir = Path(nbp_dir)
    rows = []
    for line in (nbp_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("product") != "nbp":
            continue
        utc_day = guard_date(date.fromisoformat(rec["utc_date"]))
        st = (rec.get("stations") or {}).get(STATION) or {}
        if rec.get("status") != "ok" or st.get("status") != "ok":
            rows.append({"utc_date": rec["utc_date"], "cycle": rec["cycle"], "available": False,
                         "reason": rec.get("status") if rec.get("status") != "ok" else st.get("status")})
            continue
        raw = (nbp_dir / rec["blocks_file"]).read_bytes()
        block = raw[st["file_offset"]:st["file_offset"] + st["length"]]
        if hashlib.sha256(block).hexdigest() != st["sha256"]:
            raise Refused(f"block sha mismatch {rec['blocks_file']}")
        text = block.decode("ascii", "replace")
        for target in (utc_day, utc_day + timedelta(days=1)):
            if target > LAST_ALLOWED:
                continue
            p = parse_nbp(text, target)
            if not p.get("available"):
                continue
            rows.append({"utc_date": rec["utc_date"], "cycle": rec["cycle"], "target_date": target.isoformat(),
                         "available": True, "last_modified": rec["last_modified"], "issued_at": p["issued_at"],
                         "valid_time_utc": p["valid_time_utc"], "mean_f": p["mean_native"],
                         "sd_f": p["stddev_native"], "p50_f": p["percentiles"]["50"],
                         "mean_c": (p["mean_native"] - 32.0) * F_TO_C, "sd_c": p["stddev_native"] * F_TO_C,
                         "product_version": p.get("product_version"), "block_sha256": st["sha256"]})
    rows.sort(key=lambda r: (r.get("target_date", ""), r["utc_date"], r["cycle"]))
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode("utf-8")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    avail = [r for r in rows if r["available"]]
    summary = {"corpus_sha256": sha, "rows": len(rows), "available": len(avail),
               "unavailable": len(rows) - len(avail),
               "targets": len({r["target_date"] for r in avail}),
               "per_cycle": {c: sum(1 for r in avail if r["cycle"] == c) for c in ("01", "07", "13", "19")}}
    print(json.dumps(summary, sort_keys=True))
    return summary


def load_nbp(path):
    table = defaultdict(list)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if not r.get("available"):
            continue
        guard_date(date.fromisoformat(r["target_date"]))
        lm = datetime.fromisoformat(r["last_modified"].replace("Z", "+00:00"))
        iss = datetime.fromisoformat(r["issued_at"])
        table[r["target_date"]].append((lm, iss, r["mean_c"], r["sd_c"], r["cycle"]))
    return table


def nbp_at(table, target, instant):
    """Latest-issued available bulletin for ``target`` whose S3 LastModified <= instant."""
    best = None
    for lm, iss, m, s, cyc in table.get(target, ()):
        if lm <= instant and (best is None or iss > best[1]):
            best = (lm, iss, m, s, cyc)
    return best


# ----------------------------------------------------------------------------- labels and observations

def load_labels(pinned, second):
    """{date: whole C} from the two WU daily summaries; rows after 2026-09-29 dropped before parsing."""
    out = {}
    for path, key in ((pinned, "pinned"), (second, "second")):
        sha = sha256_file(path)
        if sha != LABEL_SHA[key]:
            raise Refused(f"refused: {path} sha256 {sha}")
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                d = row.get("local_date") or ""
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d > LAST_ALLOWED.isoformat():
                    continue
                if row.get("temperature_unit") != "C":
                    raise Refused(f"refused: non-C unit on {d}")
                if d in out:
                    raise Refused(f"refused: duplicate label date {d}")
                v = row.get("max_temp_native")
                if v in (None, ""):
                    continue
                f = float(v)
                if f != int(f):
                    raise Refused(f"refused: non-whole C label {d} {v}")
                out[d] = int(f)
    return out


def tgroup_c(metar):
    m = _TGROUP.search(f" {metar} ") if isinstance(metar, str) else None
    if not m:
        return None
    return (-1.0 if m.group(1) == "1" else 1.0) * int(m.group(2)) / 10.0


def load_iem(augsep_parquet, octdec_dir):
    """{local date: [(local datetime, temp C)]}, T-group tenths else tmpc, COR dropped."""
    import pandas as pd

    if sha256_file(augsep_parquet) != AUGSEP_OBS_SHA:
        raise Refused("refused: Aug-Sep obs sha mismatch")
    a = pd.read_parquet(augsep_parquet)
    frames = [pd.DataFrame({"valid_utc": a.valid_utc, "t": a.tgroup_c.where(a.tgroup_c.notna(), a.tmpc),
                            "cor": a.is_cor.fillna(False).astype(bool)})]
    receipts = json.loads((Path(octdec_dir) / "receipts.json").read_text(encoding="utf-8"))
    for rec in receipts:
        p = Path(rec["file"])
        if sha256_file(p) != rec["sha256"]:
            raise Refused(f"refused: {p} sha mismatch")
        t = pd.read_csv(io.BytesIO(gzip.decompress(p.read_bytes())), dtype=str)
        tm = pd.to_numeric(t.tmpc, errors="coerce")
        tg = pd.Series([tgroup_c(m) for m in t.metar.fillna("")], dtype=float)
        frames.append(pd.DataFrame({"valid_utc": pd.to_datetime(t.valid, utc=True),
                                    "t": tg.where(tg.notna(), tm),
                                    "cor": t.metar.fillna("").str.contains(" COR ", regex=False)}))
    obs = pd.concat(frames, ignore_index=True).dropna(subset=["valid_utc", "t"])
    obs = obs[~obs.cor].drop_duplicates("valid_utc").sort_values("valid_utc")
    zone = tz()
    out = defaultdict(list)
    for ts, v in zip(obs.valid_utc, obs.t):
        loc = ts.to_pydatetime().astimezone(zone)
        out[loc.date()].append((loc, float(v)))
    return out


def running_floor(day_obs, until_local):
    vals = [v for t, v in day_obs if t <= until_local]
    return max(vals) if vals else None


# ----------------------------------------------------------------------------- distributions (integer C)

def _ndtr(x):
    from scipy.special import ndtr

    return ndtr(x)


def mg1_buckets(mean, sd, floor_value):
    """MG-1 on integer buckets: Normal(mean, max(sd, 5/9 C)), mass below B moved onto B."""
    import numpy as np

    s = max(float(sd), MG1_SD_FLOOR_C)
    lo, hi = math.floor(mean - 9 * s) - 1, math.ceil(mean + 9 * s) + 1
    ks = np.arange(lo, hi + 1)
    cdf = _ndtr((np.append(ks - 0.5, hi + 0.5) - mean) / s)
    mass = np.diff(cdf)
    mass[0] += cdf[0]
    mass[-1] += 1 - cdf[-1]
    dist = {int(k): float(m) for k, m in zip(ks, mass)}
    return _floor_dist(dist, floor_value)


def _floor_dist(dist, floor_value):
    if floor_value is None or not math.isfinite(floor_value):
        return dist
    fb = int(math.floor(floor_value + 0.5))
    below = sum(v for k, v in dist.items() if k < fb)
    out = {k: v for k, v in dist.items() if k >= fb}
    out[fb] = out.get(fb, 0.0) + below
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()}


def smoothed_clim(labels):
    from weather.calibration.feature_model import smoothed_dist

    support = list(range(min(labels) - 5, max(labels) + 6))
    return smoothed_dist(list(labels), support, alpha=CLIM_ALPHA)


def predictive_distribution(yhat, s, floor_value, z, p_clim):
    """``pooled_residual_model.predictive_distribution`` (L2 R-A B_N), in C."""
    import numpy as np

    lo = math.floor(yhat + s * (float(np.min(z)) - 1.5))
    hi = math.ceil(yhat + s * (float(np.max(z)) + 1.5))
    ks = np.arange(lo, hi + 1)
    edges = np.append(ks - 0.5, hi + 0.5)
    t = (edges - yhat) / s
    cdf = _ndtr((t[:, None] - z[None, :]) / KERNEL_BANDWIDTH).mean(axis=1)
    mass = np.diff(cdf)
    mass = mass / mass.sum()
    dist = {int(k): float(m) for k, m in zip(ks, mass)}
    if floor_value is not None and math.isfinite(floor_value):
        fb = int(math.floor(floor_value + 0.5))
        below = sum(v for k, v in dist.items() if k < fb)
        dist = {k: v for k, v in dist.items() if k >= fb}
        dist[fb] = dist.get(fb, 0.0) + below
    out = {k: (1.0 - FLOOR_MIX_CLIM) * v for k, v in dist.items()}
    for k, v in p_clim.items():
        out[int(k)] = out.get(int(k), 0.0) + FLOOR_MIX_CLIM * float(v)
    total = sum(out.values())
    return {k: v / total for k, v in out.items()}


class BN:
    """B_N for one (block, hour): mu0 = m + b; mean = mu0 + OLS on [1, g, max(g, 0)], g = F - mu0."""

    def fit(self, m, F, y):
        import numpy as np

        m, F, y = (np.asarray(a, float) for a in (m, F, y))
        self.b = float(np.mean(y - m))
        mu0 = m + self.b
        X = self._x(mu0, F)
        self.beta = np.linalg.lstsq(X, y - mu0, rcond=None)[0]
        return self

    @staticmethod
    def _x(mu0, F):
        import numpy as np

        g = F - mu0
        return np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])

    def predict(self, m, F):
        import numpy as np

        mu0 = np.asarray(m, float) + self.b
        return mu0 + self._x(mu0, np.asarray(F, float)) @ self.beta


def fit_bn(rows):
    """Mean model on all rows, constant scale and z set from an inner leave-one-year-out."""
    import numpy as np

    m = np.array([r["m"] for r in rows])
    F = np.array([r["F"] for r in rows])
    y = np.array([r["y"] for r in rows], float)
    yr = np.array([r["year"] for r in rows])
    years = sorted(set(yr.tolist()))
    if len(years) < 2:
        raise Refused("B_N needs at least two training years")
    err = np.full(len(rows), np.nan)
    for Y in years:
        tr = yr != Y
        mdl = BN().fit(m[tr], F[tr], y[tr])
        err[~tr] = y[~tr] - mdl.predict(m[~tr], F[~tr])
    mean = BN().fit(m, F, y)
    s = max(MIN_SCALE_C, float(np.nanmean(np.abs(err))) * math.sqrt(math.pi / 2))
    return {"mean": mean, "s": s, "z": err / s, "clim": smoothed_clim([int(v) for v in y])}


def bn_dist(fitted, m, F):
    yhat = float(fitted["mean"].predict([m], [F])[0])
    return predictive_distribution(yhat, fitted["s"], F, fitted["z"], fitted["clim"])


def bucket_brier(dist, y):
    return float(sum(v * v for v in dist.values()) - 2 * dist.get(y, 0.0) + 1.0)


def bucket_log(dist, y):
    return float(-math.log(max(dist.get(y, 0.0), 1e-15)))


# ----------------------------------------------------------------------------- bootstrap

def date_weights(n, seed, draws=DRAWS):
    import numpy as np

    rng = np.random.default_rng(seed)
    return rng.multinomial(n, np.full(n, 1.0 / n), size=draws).astype(float)


def summarise(diff_by_date, ref_by_date, W, levels=(0.95,)):
    """Point and percentile intervals of mean_date(diff) and of dR = sum(w diff) / sum(w ref)."""
    import numpy as np

    d = np.asarray(diff_by_date, float)
    point = float(d.mean())
    boot = W @ d / W.sum(axis=1)
    out = {"n_dates": int(len(d)), "delta": point, "se": float(boot.std(ddof=1))}
    for lv in levels:
        a = (1 - lv) / 2
        out[f"ci{int(round(lv * 1000))}"] = [float(np.quantile(boot, a)), float(np.quantile(boot, 1 - a))]
    if ref_by_date is not None:
        r = np.asarray(ref_by_date, float)
        out["dR"] = point / float(r.mean())
        bR = (W @ d) / (W @ r)
        for lv in levels:
            a = (1 - lv) / 2
            out[f"dR_ci{int(round(lv * 1000))}"] = [float(np.quantile(bR, a)), float(np.quantile(bR, 1 - a))]
    out["mde80"] = 2.8 * out["se"]
    return out


# ----------------------------------------------------------------------------- LOYO

def loyo_rows(nbp_table, labels, obs):
    zone = tz()
    rows = []
    for y in TRAIN_YEARS:
        d = date(y, 8, 1)
        while d <= date(y, 12, 31):
            lab = labels.get(d.isoformat())
            day_obs = obs.get(d, [])
            if lab is not None:
                for h in range(24):
                    loc = datetime(d.year, d.month, d.day, h, 0, tzinfo=zone)
                    nb = nbp_at(nbp_table, d.isoformat(), loc.astimezone(timezone.utc))
                    F = running_floor(day_obs, loc)
                    if nb is None or F is None:
                        continue
                    rows.append({"date": d.isoformat(), "year": y, "block": block_of(d), "hour": h,
                                 "m": nb[2], "sd": nb[3], "cycle": nb[4], "F": F, "y": lab})
            d += timedelta(days=1)
    return rows


def loyo(nbp_path, label_paths, obs_paths, out_dir):
    import numpy as np

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    table = load_nbp(nbp_path)
    labels = load_labels(*label_paths)
    obs = load_iem(*obs_paths)
    rows = loyo_rows(table, labels, obs)
    by = defaultdict(list)
    for r in rows:
        by[(r["block"], r["hour"])].append(r)
    scored = []
    for (blk, h), rs in sorted(by.items()):
        for Y in TRAIN_YEARS:
            train = [r for r in rs if r["year"] != Y]
            test = [r for r in rs if r["year"] == Y]
            if not test or len({r["year"] for r in train}) < 2:
                continue
            fitted = fit_bn(train)
            for r in test:
                p_mg1 = mg1_buckets(r["m"], r["sd"], r["F"])
                p_bn = bn_dist(fitted, r["m"], r["F"])
                p_cl = _floor_dist(dict(fitted["clim"]), r["F"])
                scored.append({**r, "brier_mg1": bucket_brier(p_mg1, r["y"]), "brier_bn": bucket_brier(p_bn, r["y"]),
                               "brier_clim": bucket_brier(p_cl, r["y"]), "log_mg1": bucket_log(p_mg1, r["y"]),
                               "log_bn": bucket_log(p_bn, r["y"]), "log_clim": bucket_log(p_cl, r["y"])})
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in scored).encode()
    (out / "loyo_rows.jsonl").write_bytes(body)
    res = {"schema": "toronto_guidance_loyo/1", "rule_sha256": RULE_SHA256,
           "nbp_corpus_sha256": sha256_file(nbp_path), "rows_sha256": hashlib.sha256(body).hexdigest(),
           "rows": len(scored), "blocks": {}}
    pairs = (("mg1", "clim"), ("bn", "mg1"), ("bn", "clim"))
    for blk in ("aug_sep", "oct_dec"):
        bres = {}
        sub = [r for r in scored if r["block"] == blk]
        dates = sorted({r["date"] for r in sub})
        W = date_weights(len(dates), SEED_LOYO)
        idx = {d: i for i, d in enumerate(dates)}
        groups = dict(GROUPS)
        groups.update({f"h{h:02d}": [h] for h in range(24)})
        for g, hours in groups.items():
            hs = set(hours)
            gr = {}
            for metric in ("brier", "log"):
                cell = defaultdict(lambda: defaultdict(list))
                for r in sub:
                    if r["hour"] in hs:
                        for a in ("mg1", "bn", "clim"):
                            cell[a][r["date"]].append(r[f"{metric}_{a}"])
                ds = sorted(cell["mg1"].keys())
                if not ds:
                    continue
                Wg = W[:, [idx[d] for d in ds]]
                means = {a: np.array([np.mean(cell[a][d]) for d in ds]) for a in ("mg1", "bn", "clim")}
                gr[metric] = {"mean": {a: float(v.mean()) for a, v in means.items()}}
                for a, b in pairs:
                    gr[metric][f"{a}-{b}"] = summarise(means[a] - means[b], None, Wg)
            gr["n_rows"] = sum(1 for r in sub if r["hour"] in hs)
            bres[g] = gr
        res["blocks"][blk] = {"n_dates": len(dates), "groups": bres}
    g1 = res["blocks"]["aug_sep"]["groups"]["00-16"]["brier"]
    res["gate1a_mg1_minus_clim_pass"] = bool(g1["mg1-clim"]["ci950"][1] < 0)
    res["gate1b_bn_admitted"] = bool(g1["bn-mg1"]["ci950"][1] < 0)
    (out / "loyo_summary.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("rows", "gate1a_mg1_minus_clim_pass", "gate1b_bn_admitted",
                                          "rows_sha256")}, sort_keys=True))
    return res


# ----------------------------------------------------------------------------- dev inputs

def bin_from_label(label, kind, value, value_hi, unit):
    from weather.units import parse_temperature_band

    band = parse_temperature_band(label, expected_unit="C")
    if band is None or str(unit).strip().upper().lstrip("\u00b0") != "C" or str(kind).strip().lower() != band.kind:
        return None
    lo, hi = int(band.value), int(band.value_hi)
    try:
        v, vh = float(value), float(value_hi)
    except (TypeError, ValueError):
        return None
    if band.kind == "eq" and (v != lo or vh != hi):
        return None
    if band.kind != "eq" and v != lo:
        return None
    if band.kind == "lte":
        return ("lte", -10 ** 6, lo)
    if band.kind == "gte":
        return ("gte", lo, 10 ** 6)
    return ("eq", lo, hi)


def _price(bid, ask, last):
    def f(x):
        try:
            x = float(x)
        except (TypeError, ValueError):
            return None
        return x if math.isfinite(x) else None

    bid, ask, last = f(bid), f(ask), f(last)
    mid = (bid + ask) / 2 if bid is not None and ask is not None and 0 <= bid <= ask <= 1 else None
    if mid is not None and ask - bid <= 0.10 + 1e-12:
        disp = mid
    elif last is not None and 0 <= last <= 1:
        disp = last
    else:
        disp = mid
    return disp, mid


def market_groups(tape_csv):
    """[(captured_at_utc, bins [(kind, lo, hi)], p_display, p_mid)] in capture order; bad groups dropped."""
    import pandas as pd

    cols = ["captured_at_utc", "range_label", "bin_kind", "bin_value", "bin_value_hi", "unit", "outcome",
            "best_bid", "best_ask", "last_trade_price"]
    t = pd.read_csv(tape_csv, usecols=cols, dtype=str, keep_default_na=False)
    out, bad = [], defaultdict(int)
    for cap, g in t.groupby("captured_at_utc", sort=True):
        bins = {}
        ok = True
        for r in g.itertuples(index=False):
            b = bin_from_label(r.range_label, r.bin_kind, r.bin_value, r.bin_value_hi, r.unit)
            if b is None:
                ok = False
                bad[f"parse:{r.range_label}|{r.bin_kind}|{r.bin_value}|{r.bin_value_hi}|{r.unit}"] += 1
                break
            bins.setdefault(b, {})[str(r.outcome).strip().lower()] = _price(r.best_bid, r.best_ask,
                                                                           r.last_trade_price)
        if not ok:
            continue
        keys = sorted(bins, key=lambda b: (b[1], b[2]))
        if (len(keys) < 2 or keys[0][0] != "lte" or keys[-1][0] != "gte"
                or any(k[0] == "lte" for k in keys[1:]) or any(k[0] == "gte" for k in keys[:-1])
                or any(a[2] + 1 != b[1] for a, b in zip(keys, keys[1:]))):
            bad["not_partition"] += 1
            continue
        disp, mid = [], []
        for k in keys:
            yes, no = bins[k].get("yes"), bins[k].get("no")
            dv = yes[0] if yes and yes[0] is not None else (1 - no[0] if no and no[0] is not None else None)
            mv = yes[1] if yes and yes[1] is not None else (1 - no[1] if no and no[1] is not None else None)
            disp.append(dv)
            mid.append(mv if mv is not None else dv)
        if any(v is None for v in disp):
            bad["missing_price"] += 1
            continue
        ts = datetime.fromisoformat(cap)
        out.append((ts, keys, disp, mid))
    return out, dict(bad)


def snapshot_inputs(replay_root, tapes_root, nbp_path, dev_obs_path, out_dir, first=DEV_FIRST, last=LAST_ALLOWED):
    """Gate 0 and the dev input table (no label is read here)."""
    import bisect

    import numpy as np

    from weather.model.observed_running_max import running_max_since_midnight

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sums = Path(tapes_root) / "SHA256SUMS"
    if sha256_file(sums) != TAPES_SUMS_SHA:
        raise Refused("refused: tapes SHA256SUMS mismatch")
    expected = {}
    for line in sums.read_bytes().replace(b"\r", b"").decode().splitlines():
        if line.strip():
            h, name = line.split(None, 1)
            expected[name.strip().lstrip("*")] = h
    table = load_nbp(nbp_path)
    zone = tz()
    if sha256_file(dev_obs_path) != DEV_OBS_SHA:
        raise Refused("refused: dev obs sha mismatch")
    import pandas as pd

    dob = pd.read_parquet(dev_obs_path)
    dob = dob[~dob.is_cor.fillna(False).astype(bool)]
    dob_t = dob.tgroup_c.where(dob.tgroup_c.notna(), dob.tmpc)
    iem = defaultdict(list)
    for ts, v in zip(dob.valid_utc, dob_t):
        if v is not None and math.isfinite(v):
            loc = ts.to_pydatetime().astimezone(zone)
            iem[loc.date()].append((loc, float(v)))
    rows, audit = [], defaultdict(int)
    tape_bad = {}
    d = first
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december"]
    while d <= last:
        guard_date(d)
        slug = f"highest-temperature-in-toronto-on-{months[d.month - 1]}-{d.day}-{d.year}"
        rpath = Path(replay_root) / slug / "replay_inputs.jsonl"
        tpath = Path(tapes_root) / slug / "order_books_summary.csv"
        if not rpath.is_file():
            audit["no_replay_day"] += 1
            d += timedelta(days=1)
            continue
        groups = []
        if tpath.is_file():
            rel = f"{slug}/order_books_summary.csv"
            if expected.get(rel) != sha256_file(tpath):
                raise Refused(f"refused: tape sha mismatch {rel}")
            groups, tape_bad[d.isoformat()] = market_groups(tpath)
        else:
            audit["no_tape_day"] += 1
        gtimes = [g[0] for g in groups]
        snaps = []
        with open(rpath, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    snaps.append(json.loads(line))
        snaps.sort(key=lambda s: s["captured_at_utc"])
        last_city = None
        for s in snaps:
            cap = datetime.fromisoformat(s["captured_at_utc"])
            loc = cap.astimezone(zone)
            src = s.get("sources") or {}
            city = src.get("eccc_citypage") or {}
            cd = city.get("data") or {}
            cf = city.get("fetched_at")
            if cd.get("forecast_high_c") is not None and cf and datetime.fromisoformat(cf) <= cap:
                v = float(cd["forecast_high_c"])
                if math.isfinite(v):
                    last_city = v
            if loc.date() != d:
                audit["capture_not_on_target_date"] += 1
                continue
            dist = s.get("recorded_distribution") or {}
            try:
                served = {int(k): float(v) for k, v in dist.items()}
            except (TypeError, ValueError):
                served = {}
            if not served or abs(sum(served.values()) - 1) > 0.005:
                audit["served_mass_invalid"] += 1
                continue
            metar = (src.get("metar") or {}).get("data") or {}
            F, _ = running_max_since_midnight(None, metar, target_date=d, tz=zone, unit="C", cutoff_hour=24, now=cap)
            Fh, _ = running_max_since_midnight(None, metar, target_date=d, tz=zone, unit="C",
                                               cutoff_hour=loc.hour, now=cap)
            nb = nbp_at(table, d.isoformat(), cap)
            gem = src.get("eccc_gem") or {}
            gv = (gem.get("data") or {}).get("day_max_c")
            gf = gem.get("fetched_at")
            gem_c = float(gv) if gv is not None and gf and datetime.fromisoformat(gf) <= cap else None
            iem_F = running_floor(iem.get(d, []), cap.astimezone(zone))
            i = bisect.bisect_right(gtimes, cap) - 1
            mk = None
            if i >= 0 and (cap - gtimes[i]).total_seconds() <= MARKET_MAX_AGE_S:
                mk = groups[i]
            else:
                audit["no_market_within_10min"] += 1
            rows.append({
                "date": d.isoformat(), "snapshot_id": s.get("snapshot_id"), "captured_at_utc": s["captured_at_utc"],
                "hour": loc.hour, "model_version": s.get("model_version"), "served": served,
                "F": F, "Fh": Fh, "iem_F": iem_F,
                "nbp_mean_c": nb[2] if nb else None, "nbp_sd_c": nb[3] if nb else None,
                "nbp_cycle": (nb[1].isoformat() if nb else None),
                "eccc_city_c": last_city, "eccc_gem_c": gem_c,
                "bins": [list(b) for b in mk[1]] if mk else None,
                "p_market": mk[2] if mk else None, "p_market_mid": mk[3] if mk else None,
                "market_captured_at_utc": mk[0].isoformat() if mk else None,
            })
        d += timedelta(days=1)
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
    (out / "dev_inputs.jsonl").write_bytes(body)
    n = len(rows)
    cov = sum(1 for r in rows if r["nbp_mean_c"] is not None)
    both = [abs(r["nbp_mean_c"] - r["eccc_city_c"]) for r in rows
            if r["nbp_mean_c"] is not None and r["eccc_city_c"] is not None]
    par = [(r["F"], r["iem_F"]) for r in rows if r["F"] is not None and r["iem_F"] is not None]
    bpar = [abs(math.floor(a + .5) - math.floor(b + .5)) for a, b in par]
    gate = {
        "snapshots": n, "nbp_coverage": cov / n if n else None,
        "unit_sanity_median_abs_c": float(np.median(both)) if both else None, "unit_sanity_n": len(both),
        "floor_parity_within1": float(np.mean([x <= 1 for x in bpar])) if bpar else None,
        "floor_parity_exact": float(np.mean([x == 0 for x in bpar])) if bpar else None, "floor_parity_n": len(bpar),
        "market_covered": sum(1 for r in rows if r["p_market"] is not None),
    }
    gate["pass"] = bool(gate["nbp_coverage"] is not None and gate["nbp_coverage"] >= 0.90
                        and gate["unit_sanity_median_abs_c"] is not None and gate["unit_sanity_median_abs_c"] <= 3.0
                        and gate["floor_parity_within1"] is not None and gate["floor_parity_within1"] >= 0.95)
    res = {"schema": "toronto_guidance_dev_inputs/1", "rule_sha256": RULE_SHA256,
           "nbp_corpus_sha256": sha256_file(nbp_path), "dev_inputs_sha256": hashlib.sha256(body).hexdigest(),
           "audit": dict(audit), "tape_bad": {k: v for k, v in tape_bad.items() if v}, "gate0": gate}
    (out / "dev_inputs_summary.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(res["gate0"], sort_keys=True))
    return res


# ----------------------------------------------------------------------------- dev score

def to_bins(dist, bins):
    out = []
    for kind, lo, hi in bins:
        out.append(sum(v for k, v in dist.items() if lo <= k <= hi))
    return out


def mg1_bins(mean, sd, B, bins):
    """loss_atlas.mg1_frame on one snapshot's bins (C)."""
    s = max(float(sd), MG1_SD_FLOOR_C)
    p = []
    for kind, lo, hi in bins:
        possible = kind == "gte" or hi >= B
        up = math.inf if kind == "gte" else hi + 0.5
        low = -math.inf if (kind == "lte" or lo <= B) else lo - 0.5
        p.append(float(_ndtr((up - mean) / s) - _ndtr((low - mean) / s)) if possible else 0.0)
    return p


def floor_mask(p, bins, B):
    q = [0.0 if (k != "gte" and hi < B) else max(v, 0.0) for v, (k, lo, hi) in zip(p, bins)]
    tot = sum(q)
    return [v / tot for v in q] if tot > 0 else None


def snap_brier(p, win):
    return sum((v - (1.0 if i == win else 0.0)) ** 2 for i, v in enumerate(p)) / len(p)


def snap_log(p, win):
    tot = sum(p)
    return -math.log(max(p[win] / tot if tot > 0 else 0.0, LOG_EPS))


def dev_score(inputs_path, inputs_sha, nbp_path, label_paths, obs_paths, out_dir, bn_admitted):
    import numpy as np

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if sha256_file(inputs_path) != inputs_sha:
        raise Refused("refused: dev inputs sha mismatch")
    labels = load_labels(*label_paths)
    # B_N dev fits: aug_sep block, all five training years, per hour.
    table = load_nbp(nbp_path)
    obs = load_iem(*obs_paths)
    train = [r for r in loyo_rows(table, labels, obs) if r["block"] == "aug_sep"]
    fits = {h: fit_bn([r for r in train if r["hour"] == h]) for h in range(24)}
    arms = ("served", "market", "mg1", "bn", "e1", "e2", "market_mid", "market_norm")
    recs, audit = [], defaultdict(int)
    for line in Path(inputs_path).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        guard_date(date.fromisoformat(r["date"]))
        lab = labels.get(r["date"])
        if lab is None:
            audit["no_label"] += 1
            continue
        if r["bins"] is None:
            audit["no_market"] += 1
            continue
        bins = [tuple(b) for b in r["bins"]]
        wins = [i for i, (k, lo, hi) in enumerate(bins) if lo <= lab <= hi]
        if len(wins) != 1:
            audit["winner_not_unique"] += 1
            continue
        win = wins[0]
        served = to_bins(r["served"], bins)
        rec = {"date": r["date"], "hour": r["hour"], "snapshot_id": r["snapshot_id"]}
        vec = {"served": served, "market": r["p_market"], "market_mid": r["p_market_mid"]}
        tot = sum(r["p_market"])
        vec["market_norm"] = [v / tot for v in r["p_market"]] if tot > 0 else None
        covered = r["F"] is not None and r["nbp_mean_c"] is not None and r["Fh"] is not None
        rec["covered"] = covered
        if r["F"] is not None:
            B = math.floor(r["F"] + 0.5)
            if r["nbp_mean_c"] is not None:
                vec["mg1"] = floor_mask(mg1_bins(r["nbp_mean_c"], r["nbp_sd_c"], B, bins), bins, B)
                if r["Fh"] is not None:
                    vec["bn"] = floor_mask(to_bins(bn_dist(fits[r["hour"]], r["nbp_mean_c"], r["Fh"]), bins),
                                           bins, B)
                for arm, c in (("e1", r["eccc_city_c"]), ("e2", r["eccc_gem_c"])):
                    if c is not None:
                        vec[arm] = floor_mask(mg1_bins(c, r["nbp_sd_c"], B, bins), bins, B)
        for arm in arms:
            p = vec.get(arm)
            if p is not None:
                rec[f"b_{arm}"] = snap_brier(p, win)
                rec[f"l_{arm}"] = snap_log(p, win)
        recs.append(rec)
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in recs).encode()
    (out / "dev_rows.jsonl").write_bytes(body)
    dates = sorted({r["date"] for r in recs})
    W = date_weights(len(dates), SEED_DEV)
    idx = {d: i for i, d in enumerate(dates)}
    comps = [("mg1", "served"), ("bn", "served"), ("bn", "mg1"), ("mg1", "market"), ("bn", "market"),
             ("served", "market"), ("e1", "served"), ("mg1", "e1"), ("bn", "e1"), ("e2", "served"),
             ("mg1", "e2"), ("e1", "market")]
    groups = dict(GROUPS)
    groups.update({f"h{h:02d}": [h] for h in range(24)})

    def block_stats(scope_rows, need, metric="b"):
        res = {}
        for g, hours in groups.items():
            hs = set(hours)
            sub = [r for r in scope_rows if r["hour"] in hs and all(f"{metric}_{a}" in r for a in need)]
            if not sub:
                continue
            cell = defaultdict(lambda: defaultdict(list))
            for r in sub:
                for a in need:
                    cell[a][r["date"]].append(r[f"{metric}_{a}"])
            ds = sorted(cell[need[0]].keys())
            Wg = W[:, [idx[d] for d in ds]]
            means = {a: np.array([np.mean(cell[a][d]) for d in ds]) for a in need}
            gr = {"n_snapshots": len(sub), "n_dates": len(ds), "mean": {a: float(v.mean()) for a, v in means.items()}}
            mk = means.get("market")
            for a in need:
                if a != "market" and mk is not None:
                    gr[f"R_{a}"] = float(means[a].mean() / mk.mean())
            for a, b in comps:
                if a in means and b in means:
                    lv = (0.95, 0.975) if (a, b) in (("mg1", "served"), ("bn", "served")) else (0.95,)
                    gr[f"{a}-{b}"] = summarise(means[a] - means[b], mk if metric == "b" else None, Wg, lv)
            res[g] = gr
        return res

    covered = [r for r in recs if r["covered"]]
    res = {"schema": "toronto_guidance_dev/1", "rule_sha256": RULE_SHA256, "dev_inputs_sha256": inputs_sha,
           "rows_sha256": hashlib.sha256(body).hexdigest(), "audit": dict(audit), "n_rows": len(recs),
           "n_covered": len(covered), "n_dates": len(dates), "bn_admitted": bool(bn_admitted),
           "bn_dev_fit": {str(h): {"b": fits[h]["mean"].b, "beta": [float(x) for x in fits[h]["mean"].beta],
                                   "s": fits[h]["s"], "n": int(len(fits[h]["z"]))} for h in range(24)}}
    res["covered"] = block_stats(covered, ("served", "market", "mg1", "bn"))
    res["covered_log"] = block_stats(covered, ("served", "market", "mg1", "bn"), metric="l")
    res["covered_eccc"] = block_stats(covered, ("served", "market", "mg1", "bn", "e1"))
    res["covered_gem"] = block_stats(covered, ("served", "market", "mg1", "e2"))
    res["covered_market_mid"] = block_stats(covered, ("served", "market_mid", "mg1", "bn"))
    res["covered_market_norm"] = block_stats(covered, ("served", "market_norm", "mg1", "bn"))
    # blended: candidates fall back to served on uncovered snapshots
    blended = []
    for r in recs:
        r2 = dict(r)
        for a in ("mg1", "bn"):
            if not r["covered"] or f"b_{a}" not in r:
                r2[f"b_{a}"] = r["b_served"]
        blended.append(r2)
    res["blended"] = block_stats(blended, ("served", "market", "mg1", "bn"))
    p = res["covered"]["00-16"]
    verdict = {}
    for a in ("mg1", "bn"):
        lo, hi = p[f"{a}-served"]["ci975"]
        verdict[a] = "WIN" if hi < 0 else ("HARM" if lo > 0 else "NULL")
    if not bn_admitted:
        verdict["bn"] = f"not admitted at LOYO gate 1b (reported only; would read {verdict['bn']})"
    e = res["covered_eccc"].get("00-16", {}).get("mg1-e1")
    if e:
        verdict["eccc"] = ("NBM-specific" if e["ci950"][1] < 0 else
                           "ECCC better" if e["ci950"][0] > 0 else "guidance-centre generic; ECCC citypage does as well")
    res["verdict"] = verdict
    (out / "dev_summary.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "n_covered": len(covered), "n_dates": len(dates)}, sort_keys=True))
    return res


# ----------------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("corpus")
    c.add_argument("--nbp-dir", required=True)
    c.add_argument("--out", required=True)
    for name in ("loyo", "dev-score"):
        s = sub.add_parser(name)
        s.add_argument("--nbp-rows", required=True)
        s.add_argument("--labels", nargs=2, required=True)
        s.add_argument("--obs-augsep", required=True)
        s.add_argument("--obs-octdec-dir", required=True)
        s.add_argument("--out-dir", required=True)
        if name == "dev-score":
            s.add_argument("--inputs", required=True)
            s.add_argument("--inputs-sha256", required=True)
            s.add_argument("--bn-admitted", choices=("yes", "no"), required=True)
    d = sub.add_parser("dev-inputs")
    d.add_argument("--replay-root", required=True)
    d.add_argument("--tapes-root", required=True)
    d.add_argument("--nbp-rows", required=True)
    d.add_argument("--dev-obs", required=True)
    d.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "corpus":
        corpus(a.nbp_dir, a.out)
    elif a.cmd == "loyo":
        loyo(a.nbp_rows, a.labels, (a.obs_augsep, a.obs_octdec_dir), a.out_dir)
    elif a.cmd == "dev-inputs":
        snapshot_inputs(a.replay_root, a.tapes_root, a.nbp_rows, a.dev_obs, a.out_dir)
    else:
        dev_score(a.inputs, a.inputs_sha256, a.nbp_rows, a.labels, (a.obs_augsep, a.obs_octdec_dir), a.out_dir,
                  a.bn_admitted == "yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
