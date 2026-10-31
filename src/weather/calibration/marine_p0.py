r"""Marine market-residual P0 screen (lane L3, 2026-10-30; rule ``RULE_SHA256``, dev-window ledger row 87).

Rule ``docs/research/marine-ndbc-2026-10-30/rule_marine_p0.md`` (sha256 ``a374f771…``, on the ledger branch
``claude/successor-batch-20261030``; amendment 1 at ``36877c7df`` pins the offshore secondaries). Free NOAA
CO-OPS and NDBC observations, downloaded under the NBM conditions, are turned into two capture-time signals:

* ``MAR-SST`` (+): the latest water temperature, degC;
* ``MAR-ONSHORE`` (-): the latest wind speed (m/s) when the direction lies inside the registry onshore sector,
  else 0.

A snapshot's value is the latest observation with ``obs_utc + L <= captured_at_utc`` and
``obs_utc >= captured_at_utc - 6 h`` from the highest-priority station that has one, for L = 90 (primary) and
L = 180 (sensitivity) minutes. Values exist only for the six coastal markets at local hours 07..12. Everything
downstream is the MR sweep's machinery (``mr_sweep``, rule 85f8192c) unchanged: type D band signal and tilt, the
calibration-matched disagreement placebo (20 derangements), the paired date-cluster bootstrap (10,000 draws,
seed 20261024), BH at q = 0.10 over K = 2 at each lag. A candidate survives only if it survives at both lags;
the w gate (block 07-12, L = 90) runs only for a survivor. One run; nothing after 2026-09-29 is read.

Writes ``marine_p0.json`` (never overwrites), ``marine_p0_rows.jsonl`` (per candidate, lag and date, plus per
market and date) and ``features.parquet`` (value, station and obs time per snapshot, candidate and lag).

    python -m weather.calibration.loyo_screen marine-p0 --layout C:/swarm/v3layout \
        --raw C:/t/l3marine/raw --raw C:/t/l3marine/raw2 --out C:/t/l3marine/p0
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "marine_p0/1"
GATE = "MAR-P0"
RULE_SHA256 = "a374f771612e6b0e2b9f392db6a1688a23a2296a4cc2b5cdc98aaa42bb37c230"
AMENDMENT_COMMIT = "36877c7df609d467a41e04e01c635f14b7148e82"
LEDGER_ROW = 87
LAGS = (90, 180)  # minutes; 90 primary, 180 sensitivity; both are gates
PRIMARY_LAG = 90
MAX_AGE = np.timedelta64(6, "h")
HOURS = (7, 12)
END_UTC = np.datetime64("2026-09-30T00:00", "ns")  # nothing at or after this instant is used
MARKETS = ("san-francisco", "seattle", "los-angeles", "nyc", "miami", "houston")
# (id, type, sign, variable) - rule section 3
CANDIDATES = (("MAR-SST", "D", 1, "sst"), ("MAR-ONSHORE", "D", -1, "onshore"))
# Registry onshore sectors (MARINE_CONTEXT_REGISTRY, unchanged; checked at run time).
SECTORS = {"nyc": (45.0, 165.0), "miami": (45.0, 160.0), "houston": (90.0, 190.0),
           "los-angeles": (220.0, 320.0), "san-francisco": (220.0, 320.0), "seattle": (180.0, 310.0)}
# Station priority per market and variable: the registry stations in registry order, then the amendment-1
# secondaries (rule section 4).
STATIONS = {
    "nyc": {"sst": [("coops", "8518750"), ("ndbc", "44065")], "wind": [("coops", "8518750"), ("ndbc", "44065")]},
    "miami": {"sst": [("coops", "8723214")], "wind": [("coops", "8723214")]},
    "houston": {"sst": [("coops", "8770613")], "wind": [("coops", "8770613")]},
    "los-angeles": {"sst": [("coops", "9410660"), ("ndbc", "46025")], "wind": [("coops", "9410660"), ("ndbc", "46025")]},
    "san-francisco": {"sst": [("coops", "9414290"), ("ndbc", "46026")], "wind": [("coops", "9414290")]},
    "seattle": {"sst": [("coops", "9447130"), ("ndbc", "46088")], "wind": [("coops", "9447130"), ("ndbc", "WPOW1")]},
}
NDBC_MISSING = (99.0, 999.0, 9999.0)


class MarineError(mg.GateError):
    """A refused marine P0 run."""


# ----------------------------------------------------------------------------- raw observations

def verify_raw(roots):
    """Every downloaded file must match its manifest sha256; returns {root: manifest sha256}."""
    out = {}
    for root in map(Path, roots):
        man = root.parent / f"{root.name}_manifest.jsonl"
        if not man.exists():
            raise MarineError(f"download manifest missing: {man}")
        for line in man.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("status") != 200 or not rec.get("bytes"):
                continue
            p = root / rec["path"]
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != rec["sha256"]:
                raise MarineError(f"raw file does not match its manifest: {p}")
        out[str(root)] = ls.sha256_file(man)
    return out


def parse_coops(text):
    """A CO-OPS datagetter CSV (GMT, metric) -> DataFrame(t, wtmp | wspd, wdir); empty on a no-data reply."""
    d = pd.read_csv(io.StringIO(text))
    d.columns = [c.strip() for c in d.columns]
    if "Date Time" not in d.columns:
        return pd.DataFrame(columns=["t"])
    t = pd.to_datetime(d["Date Time"], errors="coerce", format="%Y-%m-%d %H:%M")
    out = pd.DataFrame({"t": t.to_numpy("datetime64[ns]")})
    if "Water Temperature" in d.columns:
        out["wtmp"] = pd.to_numeric(d["Water Temperature"], errors="coerce").to_numpy(float)
    if "Speed" in d.columns:
        out["wspd"] = pd.to_numeric(d["Speed"], errors="coerce").to_numpy(float)
        out["wdir"] = pd.to_numeric(d["Direction"], errors="coerce").to_numpy(float)
    return out[out.t.notna()]


def parse_ndbc(raw):
    """NDBC stdmet text (optionally gzip) -> DataFrame(t, wtmp, wspd, wdir) with the missing codes as NaN."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    lines = raw.decode("ascii", "replace").splitlines()
    hdr = lines[0].lstrip("#").split()
    rows = [ln.split() for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
    if not rows:
        return pd.DataFrame(columns=["t", "wtmp", "wspd", "wdir"])
    d = pd.DataFrame(rows, columns=hdr[:len(rows[0])])
    yy = d["YY"].astype(int) if "YY" in d.columns else d["YYYY"].astype(int)
    t = pd.to_datetime(dict(year=yy, month=d["MM"].astype(int), day=d["DD"].astype(int), hour=d["hh"].astype(int),
                            minute=d["mm"].astype(int)))
    out = pd.DataFrame({"t": t.to_numpy("datetime64[ns]")})
    for src, dst in (("WTMP", "wtmp"), ("WSPD", "wspd"), ("WDIR", "wdir")):
        s = pd.to_numeric(d[src], errors="coerce")
        out[dst] = s.where(~s.isin(NDBC_MISSING)).to_numpy(float)
    return out


def load_station(roots, provider, station):
    """All files of one station across the raw roots -> DataFrame(t, wtmp, wspd, wdir), sorted, < END_UTC."""
    frames = []
    for root in map(Path, roots):
        d = root / provider / station
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if provider == "coops":
                frames.append(parse_coops(f.read_text(encoding="utf-8", errors="replace")))
            else:
                frames.append(parse_ndbc(f.read_bytes()))
    cols = ["t", "wtmp", "wspd", "wdir"]
    if not frames:
        return pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == "t" else float) for c in cols})
    d = pd.concat([f.reindex(columns=cols) for f in frames], ignore_index=True)
    d = d[d.t < END_UTC].groupby("t", as_index=False).first().sort_values("t")
    return d.reset_index(drop=True)


def in_sector(direction, lo, hi):
    d = np.mod(np.asarray(direction, float), 360.0)
    return (d >= lo) & (d <= hi) if lo <= hi else (d >= lo) | (d <= hi)


def onshore(spd, direction, sector):
    """Speed when the direction lies inside the (inclusive) sector, else 0; NaN when either is missing."""
    spd, direction = np.asarray(spd, float), np.asarray(direction, float)
    ok = np.isfinite(spd) & np.isfinite(direction)
    with np.errstate(invalid="ignore"):
        val = np.where(in_sector(direction, *sector), spd, 0.0)
    return np.where(ok, val, np.nan)


def asof(cap, t, v, lag_minutes):
    """Per capture time: (value, obs time) of the latest finite observation with t + lag <= cap and
    t >= cap - 6 h; NaN / NaT when none qualifies."""
    t, v = np.asarray(t, "datetime64[ns]"), np.asarray(v, float)
    keep = np.isfinite(v) & ~np.isnat(t)
    t, v = t[keep], v[keep]
    order = np.argsort(t, kind="mergesort")
    t, v = t[order], v[order]
    cap = np.asarray(cap, "datetime64[ns]")
    edge = cap - np.timedelta64(int(lag_minutes), "m")
    idx = np.searchsorted(t, edge, side="right") - 1
    ok = (idx >= 0) & ~np.isnat(cap)
    j = np.where(ok, idx, 0)
    if len(t):
        ok &= t[j] >= cap - MAX_AGE
    else:
        ok &= False
    val = np.where(ok, v[j] if len(v) else np.nan, np.nan)
    obs = np.where(ok, t[j] if len(t) else np.datetime64("NaT", "ns"), np.datetime64("NaT", "ns"))
    return val, obs.astype("datetime64[ns]")


def station_series(roots, market, variable):
    """[(station label, t, value)] for one market and variable, in priority order."""
    out = []
    for provider, station in STATIONS[market]["sst" if variable == "sst" else "wind"]:
        d = load_station(roots, provider, station)
        if variable == "sst":
            v = d.wtmp.to_numpy(float)
        else:
            v = onshore(d.wspd.to_numpy(float), d.wdir.to_numpy(float), SECTORS[market])
        out.append((f"{provider}:{station}", d.t.to_numpy("datetime64[ns]"), v))
    return out


def marine_values(snaps, local_hour, markets, series, lag):
    """Per variable: (value, station, obs_utc) on ``snaps``; NaN outside the six markets and hours 07..12."""
    cap = sw._utc(snaps.captured_at_utc)
    n = len(snaps)
    in_pop = np.isin(markets, MARKETS) & (local_hour >= HOURS[0]) & (local_hour <= HOURS[1])
    out = {}
    for variable in ("sst", "onshore"):
        val = np.full(n, np.nan)
        src = np.full(n, "", dtype=object)
        obs = np.full(n, np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
        for mk in MARKETS:
            sel = np.flatnonzero(in_pop & (markets == mk))
            if not len(sel):
                continue
            for label, t, v in series[(mk, variable)]:
                todo = sel[~np.isfinite(val[sel])]
                if not len(todo):
                    break
                x, o = asof(cap[todo], t, v, lag)
                hit = np.isfinite(x)
                val[todo[hit]], src[todo[hit]], obs[todo[hit]] = x[hit], label, o[hit]
        out[variable] = (val, src, obs)
    return out


# ----------------------------------------------------------------------------- per-market rows

def market_rows(cid, lag, vals, vecs, fit_t, score_t, score_dates, donors):
    """Per market and date: the six sufficient sums for c and the 20 placebos on the candidate's population."""
    from weather.calibration import market_blend as mb

    covered = vecs["covered"]
    cov_float = np.repeat(covered.astype(float), fit_t.n)
    donor_ok = np.ones(len(fit_t.snaps), bool)
    pls = []
    for seed in sw.PLACEBO_SEEDS:
        pl, _ = sw.disagreement_placebo(fit_t, vecs["c_fit"], seed, donors[seed])
        dcov = cov_float[donors[seed][0]]
        donor_ok &= np.bincount(fit_t.band_snap, weights=dcov, minlength=len(fit_t.snaps)) == fit_t.n
        pls.append(mb.restrict(fit_t, score_t, pl))
    pop = mb.restrict_snap(fit_t, score_t, covered & donor_ok)
    c = mb.restrict(fit_t, score_t, vecs["c_fit"])
    m, e = score_t.p_market, score_t.y - score_t.p_market
    didx = np.searchsorted(score_dates, score_t.snaps.date.astype(str).to_numpy())[score_t.band_snap]
    nd = len(score_dates)
    rows = []
    for mk in MARKETS:
        band = (pop & (score_t.markets == mk))[score_t.band_snap]
        if not band.any():
            continue
        sc_ = sw.date_sums((c - m)[band], e[band], didx[band], nd)
        sp = [sw.date_sums((p - m)[band], e[band], didx[band], nd) for p in pls]
        rows += [{"candidate": cid, "lag_minutes": lag, "market": mk, "date": score_dates[i],
                  "n_entries": int(sc_[0, i]), "sums_c": sc_[:, i].tolist(), "sums_pl": [s[:, i].tolist() for s in sp]}
                 for i in range(nd) if sc_[0, i] > 0]
    return rows


# ----------------------------------------------------------------------------- the run

def _check_registry():
    from weather.sources.marine_context import MARINE_CONTEXT_REGISTRY as reg

    for mk, sector in SECTORS.items():
        rows = reg.get(mk) or []
        got = {(float(r["onshore_direction_min"]), float(r["onshore_direction_max"])) for r in rows}
        if got != {sector}:
            raise MarineError(f"registry onshore sector for {mk} is {got}, the rule pins {sector}")
        reg_stations = [(r["provider"], str(r["station_id"])) for r in rows]
        for var in ("sst", "wind"):
            if STATIONS[mk][var][:len(reg_stations)] != reg_stations:
                raise MarineError(f"{mk} {var}: the priority list must start with the registry stations")


def run(*, layout, raw_roots, out_dir, allow_dirty=False):
    """Controls, marine values at both lags, P0 for K = 2 per lag, BH per lag, both-lag survival, w gate."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = Path(out_dir)
    if (out / "marine_p0.json").exists():
        raise MarineError(f"refusing to overwrite {out / 'marine_p0.json'}")
    if not raw_roots:
        raise MarineError("no raw download directory given")
    raw_manifests = verify_raw(raw_roots)
    _check_registry()
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    missing = set(MARKETS) - set(fit_t.markets)
    if missing:
        raise MarineError(f"markets absent from the layout: {sorted(missing)}")
    controls = mg.market_controls(fit_t, score_t)

    series = {(mk, v): station_series(raw_roots, mk, v) for mk in MARKETS for v in ("sst", "onshore")}
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}

    results, kept, rows, feat_frames = {}, {}, [], []
    for lag in LAGS:
        mv = marine_values(fit_t.snaps, fit_t.local_hour, fit_t.markets, series, lag)
        per_lag = {}
        for cid, kind, sign, var in CANDIDATES:
            val, src, obs = mv[var]
            feat_frames.append(pd.DataFrame({"row_key": fit_t.snaps.row_key.to_numpy(), "market": fit_t.markets,
                                             "local_hour": fit_t.local_hour, "lag_minutes": lag, "candidate": cid,
                                             "value": val, "station": src.astype(str), "obs_utc": obs}))
            res, vecs = sw.p0_candidate(cid, kind, sign, val, fit_t, score_t, geo, counts, score_dates, donors)
            for r in res.pop("_rows", []):
                rows.append(dict(r, lag_minutes=lag))
            if vecs is not None:
                kept[(cid, lag)] = vecs
                rows += market_rows(cid, lag, val, vecs, fit_t, score_t, score_dates, donors)
            covered = np.isfinite(val)
            res["station_share"] = {mk: pd.Series(src[covered & (fit_t.markets == mk)]).value_counts().to_dict()
                                    for mk in MARKETS}
            per_lag[cid] = res
        ids = [c[0] for c in CANDIDATES]
        adj, reject = sw.bh_adjust([per_lag[c]["p0"]["p_one_sided"] for c in ids])
        for cid, q, rj in zip(ids, adj, reject):
            r = per_lag[cid]
            lo = r["p0"]["ci95"][0]
            r["bh_q"] = float(q)
            r["bh_reject"] = bool(rj)
            r["survive"] = bool(r["testable"] and rj and lo is not None and lo > 0)
            r["verdict"] = "SURVIVE" if r["survive"] else ("UNTESTABLE" if not r["testable"] else "KILL")
        results[str(lag)] = per_lag

    final = {}
    for cid, _, _, _ in CANDIDATES:
        at = {lag: results[str(lag)][cid] for lag in LAGS}
        if all(a["survive"] for a in at.values()):
            verdict = "SURVIVE"
        elif any(not a["testable"] for a in at.values()):
            verdict = "UNTESTABLE"
        else:
            verdict = "KILL"
        final[cid] = {"verdict": verdict, "by_lag": {str(k): v["verdict"] for k, v in at.items()}}
        if verdict == "SURVIVE":
            vec = kept[(cid, PRIMARY_LAG)]
            key = f"w0_identity_{cid}"
            controls[key] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec["c_fit"]))
            if controls[key]["verdict"] != "PASS":
                raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
            g = mg.gate_candidate(cid, "07-12", fit_t, score_t, vec["c_fit"], vec["covered"],
                                  p_placebo_fit=vec["pl0_fit"])
            final[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                    "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}

    out.mkdir(parents=True, exist_ok=True)
    feats = pd.concat(feat_frames, ignore_index=True)
    feats = feats[np.isfinite(feats.value.to_numpy(float))]
    feats.to_parquet(out / "features.parquet", index=False)
    lines = [line_for(cid, final[cid], {lag: results[str(lag)][cid] for lag in LAGS}) for cid, *_ in CANDIDATES]
    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "amendment_commit": AMENDMENT_COMMIT,
               "ledger_row": LEDGER_ROW, "code": code,
               "evidence_class": "screen (dev window, provisional; kill-only)",
               "module_sha256": {"marine_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(sw.__file__),
                                 "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__)},
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "raw_manifest_sha256": raw_manifests,
               "features_parquet_sha256": ls.sha256_file(out / "features.parquet"),
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "markets": list(MARKETS), "local_hours": list(HOURS)},
               "constants": {"lags_minutes": list(LAGS), "primary_lag": PRIMARY_LAG, "max_age_hours": 6,
                             "draws": sw.DRAWS, "seed": sw.SEED, "placebo_seeds": list(sw.PLACEBO_SEEDS),
                             "bh_q": sw.BH_Q, "k": len(CANDIDATES), "sigma2_floor": sw.SIGMA2_FLOOR,
                             "min_dates": sw.MIN_DATES, "min_snapshots": sw.MIN_SNAPS, "sectors": SECTORS,
                             "stations": STATIONS},
               "controls": controls, "results": results, "final": final, "lines": lines}
    (out / "marine_p0_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                      for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "marine_p0_rows.jsonl")
    (out / "marine_p0.json").write_text(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default),
                                        encoding="utf-8")
    return receipt


def line_for(cid, fin, at):
    parts = []
    for lag, r in at.items():
        p0 = r["p0"]
        if not r["testable"]:
            parts.append(f"L{lag} UNTESTABLE ({r['coverage']['population_snapshots']} snapshots / "
                         f"{r['coverage']['population_dates']} dates)")
        else:
            ci = p0["ci95"]
            parts.append(f"L{lag} {r['verdict']} delta {p0['delta']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}] "
                         f"p {p0['p_one_sided']:.4f} q {r['bh_q']:.3f}")
    tail = f"; w gate {fin['w_gate']['verdict']}" if "w_gate" in fin else ""
    return f"{fin['verdict']}: {cid}; " + "; ".join(parts) + tail
