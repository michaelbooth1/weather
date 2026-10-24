"""Floor + remaining-rise pmf (t3-r3, EF 10q) with an optional fresher running high (screen F1).

Control (``t3r3``): R = point-in-time running max of routine, non-COR METAR rows of the station-local
date (temp_f = half-up of T-group C x 1.8 + 32, falling back to the body integer C; available =
valid + 10 min). P(high = R + e) uses the history pmf of e = dmax - R at local H:30 by station x
target month x local hour (local dates <= 2026-07-31; complete day = >= 20 routine rows; dmax = max
of those rows), smoothed with a discrete Gaussian sd 1 F. Constants are t3-r3's, fixed a priori.

F1 (``fresh``): R* = max(R, R_hf), where R_hf is the running max of a high-frequency series built
from the IEM 1-minute archive and degraded to a serve product before use (cadence, resolution and
latency are explicit arguments). The history pmf is of e* = dmax - R* computed the same way, so the
table and the serve-time state share one definition (train/serve parity); e* may be negative. Mass
of any value below R (the METAR running max, a hard lower bound for dmax) is folded onto R. Where a
station-day has no 1-minute data, R* = R, exactly as at serve when the feed is absent.

No market or label input: e is built from observations only, and history ends before the first
development date.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

HIST_END = "2026-07-31"
OBS_LAST = "2026-09-29"
MIN_ROUTINE = 20
KERNEL_SD = 1.0
HIST_CUTOFF_MIN = 30
MIN_CELL_N = 30
METAR_AVAIL_MIN = 10

DEFAULT_METAR_DIR = r"C:\swarm\data\iem\metar"
DEFAULT_ROOT = r"C:\Users\Michael\Documents\github\weather\data\research\free_sources"
DEFAULT_INBOX = r"C:\Users\Michael\Documents\github\weather\data\inbox\replay-inputs-le0929"


def metar_dir():
    return Path(os.environ.get("FREE_SCREENS_METAR_DIR", DEFAULT_METAR_DIR))


def replay_inbox():
    return Path(os.environ.get("FREE_SCREENS_REPLAY_INBOX", DEFAULT_INBOX))


def research_root():
    return Path(os.environ.get("FREE_SCREENS_ROOT", DEFAULT_ROOT))


@dataclass(frozen=True)
class HfSpec:
    """How the 1-minute archive is degraded to a serve product."""
    name: str
    cadence_min: int      # keep minutes with minute % cadence == 0
    latency_min: int      # available = valid + latency
    whole_c: bool         # round to whole degrees C (the 5-minute HF-METAR resolution), then back to F


HF5C = HfSpec("hf5c_lat10", 5, 10, True)
M1F = HfSpec("m1f_lat2", 1, 2, False)


def half_up(x):
    return np.floor(np.asarray(x, float) + 0.5)


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- observations

def load_metar(stations, root=None):
    """Routine non-COR METAR rows: station, local_date, available_utc, temp_f (integer F)."""
    root = Path(root or metar_dir())
    frames, shas = [], {}
    for st in stations:
        path = root / f"{st}.parquet"
        shas[st] = file_sha(path)
        m = pd.read_parquet(path, columns=["station", "report_type", "is_cor", "tgroup_c", "main_temp_c",
                                            "valid_utc", "local_date"])
        m = m[(m.report_type == "routine") & (~m.is_cor)].copy()
        tf = np.where(m.tgroup_c.notna(), m.tgroup_c * 1.8 + 32, m.main_temp_c * 1.8 + 32)
        m["temp_f"] = half_up(tf)
        m = m[np.isfinite(m.temp_f)]
        m["local_date"] = m.local_date.astype(str)
        if (m.local_date > OBS_LAST).any():
            raise AssertionError(f"{st}: METAR rows after {OBS_LAST}")
        m["available_utc"] = pd.to_datetime(m.valid_utc, utc=True) + pd.Timedelta(minutes=METAR_AVAIL_MIN)
        frames.append(m[["station", "local_date", "available_utc", "temp_f"]])
    return pd.concat(frames, ignore_index=True), shas


def hf_series(onemin, tz_by_station, spec):
    """Degrade 1-minute rows (icao, valid_utc, tmpf) to ``spec``: station, local_date, available_utc, temp_f."""
    frames = []
    for st, g in onemin.groupby("icao"):
        if st not in tz_by_station:
            continue
        valid = pd.to_datetime(g.valid_utc, utc=True)
        keep = (valid.dt.minute % spec.cadence_min) == 0
        g, valid = g[keep.to_numpy()], valid[keep.to_numpy()]
        f = g.tmpf.to_numpy(float)
        if spec.whole_c:
            f = half_up(half_up((f - 32.0) / 1.8) * 1.8 + 32.0)
        local = valid.dt.tz_convert(tz_by_station[st]).dt.strftime("%Y-%m-%d")
        out = pd.DataFrame({"station": st, "local_date": local.to_numpy(),
                            "available_utc": valid + pd.Timedelta(minutes=spec.latency_min), "temp_f": f})
        frames.append(out[np.isfinite(out.temp_f)])
    frame = pd.concat(frames, ignore_index=True)
    if (frame.local_date > OBS_LAST).any():
        raise AssertionError(f"1-minute rows after {OBS_LAST}")
    return frame


def running_max_asof(obs, queries):
    """For queries (qid, station, local_date, t) return the max of obs on that station-local date
    with available_utc <= t (NaN when none)."""
    o = obs.sort_values(["station", "local_date", "available_utc"]).copy()
    o["cummax"] = o.groupby(["station", "local_date"]).temp_f.cummax()
    o["key"] = o.station + "|" + o.local_date
    q = queries.copy()
    q["key"] = q.station + "|" + q.local_date
    q["t"] = pd.to_datetime(q.t, utc=True).astype("datetime64[us, UTC]")
    o["available_utc"] = o.available_utc.astype("datetime64[us, UTC]")
    j = pd.merge_asof(q.sort_values("t"), o.sort_values("available_utc")[["key", "available_utc", "cummax"]],
                      left_on="t", right_on="available_utc", by="key", direction="backward")
    ok = j.available_utc.notna()
    if (j.available_utc[ok] > j.t[ok]).any():
        raise AssertionError("point-in-time violation in running max")
    return j.set_index("qid")["cummax"].reindex(queries.qid)


# ----------------------------------------------------------------------------- history table

def history_cutoffs(days, tz_by_station):
    """One query per (station, local_date, hour) at local H:30."""
    rows = []
    for st, g in days.groupby("station"):
        tz = tz_by_station[st]
        base = pd.to_datetime(g.local_date.to_numpy())
        for hour in range(24):
            local = (base + pd.Timedelta(hours=hour, minutes=HIST_CUTOFF_MIN)).tz_localize(
                tz, ambiguous="NaT", nonexistent="NaT")
            rows.append(pd.DataFrame({"station": st, "local_date": g.local_date.to_numpy(), "hour": hour,
                                      "month": g.month.to_numpy(), "dmax": g.dmax.to_numpy(),
                                      "t": local.tz_convert("UTC")}))
    out = pd.concat(rows, ignore_index=True).dropna(subset=["t"]).reset_index(drop=True)
    out["qid"] = np.arange(len(out))
    return out


def complete_days(metar):
    d = metar.groupby(["station", "local_date"]).agg(dmax=("temp_f", "max"), n=("temp_f", "size")).reset_index()
    d = d[(d.n >= MIN_ROUTINE) & (d.local_date <= HIST_END)].copy()
    d["month"] = d.local_date.str[5:7].astype(int)
    return d


def disc_gauss(sd=KERNEL_SD, half=6):
    k = np.arange(-half, half + 1)
    w = np.exp(-0.5 * (k / sd) ** 2)
    return k, w / w.sum()


def smooth_pmf(values):
    v = np.asarray(values, int)
    lo, hi = int(v.min()), int(v.max())
    counts = np.bincount(v - lo, minlength=hi - lo + 1).astype(float)
    k, w = disc_gauss()
    p = np.convolve(counts, w)
    return lo + int(k[0]), p / p.sum()


def fit_table(metar, tz_by_station, hf=None, months=(8, 9), cond=None):
    """{(station, month, hour): (base, pmf, n)} of e = dmax - R(*) at local H:30 (history only).

    ``cond(queries, r)`` (optional) returns an integer bin per query (-1 = no information); cells
    ``(station, month, hour, bin)`` with >= MIN_CELL_N days are added beside the unconditioned ones.
    The same ``cond`` is applied at serve (``predict_frame``), which backs off to the unconditioned cell."""
    days = complete_days(metar)
    days = days[days.month.isin(months)]
    q = history_cutoffs(days, tz_by_station)
    r = running_max_asof(metar, q[["qid", "station", "local_date", "t"]]).to_numpy(float)
    if hf is not None:
        rh = running_max_asof(hf, q[["qid", "station", "local_date", "t"]]).to_numpy(float)
        r = np.where(np.isnan(rh), r, np.fmax(r, rh))
    q["e"] = q.dmax.to_numpy(float) - r
    q["bin"] = -1 if cond is None else np.asarray(cond(q, r), int)
    q = q[np.isfinite(q.e)]
    table = {}
    for (st, mo, hour), g in q.groupby(["station", "month", "hour"]):
        if len(g) >= MIN_CELL_N:
            base, p = smooth_pmf(g.e.to_numpy())
            table[(st, int(mo), int(hour))] = (base, p, int(len(g)))
    if cond is not None:
        for (st, mo, hour, b), g in q[q["bin"] >= 0].groupby(["station", "month", "hour", "bin"]):
            if len(g) >= MIN_CELL_N:
                base, p = smooth_pmf(g.e.to_numpy())
                table[(st, int(mo), int(hour), int(b))] = (base, p, int(len(g)))
    return table


# ----------------------------------------------------------------------------- serve-time state and pmf

def band_probs(base, pmf, kinds, lows, highs):
    cum = np.concatenate([[0.0], np.cumsum(pmf)])
    n = len(pmf)

    def mass(a, b):
        i = int(np.clip(a - base, 0, n))
        j = int(np.clip(b - base + 1, 0, n))
        return max(cum[j] - cum[i], 0.0)

    out = []
    for kind, lo, hi in zip(kinds, lows, highs):
        if kind == "lte":
            out.append(mass(-10 ** 6, hi))
        elif kind == "gte":
            out.append(mass(lo, 10 ** 6))
        else:
            out.append(mass(lo, hi))
    return out


def snapshot_state(snaps, metar, hf=None):
    q = pd.DataFrame({"qid": np.arange(len(snaps)), "station": snaps.station.astype(str).to_numpy(),
                      "local_date": snaps.date.astype(str).to_numpy(), "t": snaps.captured_at_utc.to_numpy()})
    r = running_max_asof(metar, q).to_numpy(float)
    rstar = r.copy()
    if hf is not None:
        rh = running_max_asof(hf, q).to_numpy(float)
        rstar = np.where(np.isnan(rh) | np.isnan(r), r, np.fmax(r, rh))
    return r, rstar


def predict_frame(table, snaps, bands, metar, hf=None, cond=None):
    r, rstar = snapshot_state(snaps, metar, hf)
    bins = np.full(len(snaps), -1)
    if cond is not None:
        q = pd.DataFrame({"qid": np.arange(len(snaps)), "station": snaps.station.astype(str).to_numpy(),
                          "local_date": snaps.date.astype(str).to_numpy(),
                          "t": pd.to_datetime(snaps.captured_at_utc, utc=True).to_numpy()})
        q["t"] = pd.to_datetime(q.t, utc=True)
        bins = np.asarray(cond(q, r), int)
    months = snaps.date.astype(str).str[5:7].astype(int).to_numpy()
    hours = snaps.local_hour.to_numpy(int)
    stations = snaps.station.astype(str).to_numpy()
    grouped = {k: g for k, g in bands.groupby("row_key", sort=False)}
    rk, bi, pp = [], [], []
    for i, key in enumerate(snaps.row_key.to_numpy()):
        if np.isnan(r[i]):
            continue
        cell = table.get((stations[i], int(months[i]), int(hours[i])))
        if bins[i] >= 0:
            cell = table.get((stations[i], int(months[i]), int(hours[i]), int(bins[i])), cell)
        if cell is None or key not in grouped:
            continue
        base, pmf, _ = cell
        floor = int(r[i])
        start = int(rstar[i]) + base
        values = start + np.arange(len(pmf))
        below = values < floor
        if below.any():
            pmf = pmf.copy()
            folded = pmf[below].sum()
            pmf = pmf[~below]
            if len(pmf) == 0:
                pmf, start = np.array([folded]), floor
            else:
                pmf[0] += folded
                start = floor
        g = grouped[key]
        probs = band_probs(start, pmf, g.kind.to_numpy(), g.low.to_numpy(int), g.high.to_numpy(int))
        rk.extend([key] * len(g))
        bi.extend(g.band_index.to_numpy(int).tolist())
        pp.extend(probs)
    return pd.DataFrame({"row_key": rk, "band_index": np.asarray(bi, int), "p": np.asarray(pp, float)})


def table_digest(table):
    rows = sorted((list(k), v[0], [round(x, 12) for x in v[1].tolist()], v[2]) for k, v in table.items())
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()
