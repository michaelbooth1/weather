r"""MOS against the market: market-residual P0 (lane L3, 2026-10-30; rule ``RULE_SHA256``, ledger row 89).

Rule ``docs/research/mos-market-p0-2026-10-30/rule_mos_p0.md`` (sha256 ``952cfc52…``, on the ledger branch
``claude/successor-batch-20261030``). Its own arm (K = 2), not pooled with rows 78, 81, 87 or 88. The candidates
are GFS MOS (MAV) and NAM MOS (MET) ``n_x`` for the target day's daytime maximum (the row whose ``ftime`` is
(D + 1) 00Z at the market's station), type C, sign +, at local hours 07..12. The selected value is the latest run
whose modelled ``available_utc`` <= ``captured_at_utc`` with a finite value in [-40, 130] °F. Availability is
modelled, not a capture receipt, so a sensitivity arm (every lag + 1 h, not in K) is reported; under amendment 1
(``AMENDMENT_1_SHA256``) it is report-only and a flip is flagged, never changing the verdict.
Everything downstream is ``mr_sweep``'s machinery unchanged (type C tilt, the calibration-matched disagreement
placebo, 20 derangements, the paired date-cluster bootstrap with 10,000 draws and seed 20261024, BH q = 0.10).
Only a survivor gets the w = 0 identity and the w gate in block 07-12. One run; nothing after 2026-09-29 is read.

Reads the layout and the forecast-only A-IEM-2 IEM MOS archive (sha-pinned); no network. Writes ``mos_p0.json``
(never overwrites), ``mos_p0_rows.jsonl`` (per date, plus per market and date) and ``features.parquet``.

    python -m weather.calibration.loyo_screen mos-p0 --layout C:/swarm/v3layout --mos-root C:/swarm/data/iem/mos \
        --out C:/t/l3mos/p0
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "mos_p0/1"
GATE = "MOS-P0"
RULE_SHA256 = "952cfc52968e8d7dee8be685ecbf71f14bfccc1a6e8cd28d149bd0a58112ebc2"
AMENDMENT_1_SHA256 = "eafbfca4b3ab3b9e1ded9378bdcade6ceb20183bb54d58c3632dca7579c01f2e"
RECORDER_COMMIT = "841fb604255825258a5b2ac0d1fa4b1009a2818d"  # IEM MOS forward recorder (serve-parity source)
LEDGER_ROW = 89
HOURS = (7, 12)
W_BLOCK = "07-12"
CANDIDATES = (("MOS-GFS", "C", 1, "GFS"), ("MOS-NAM", "C", 1, "NAM"))
FIELD = "n_x"
VALID = (-40.0, 130.0)
RUNTIME_END = pd.Timestamp("2026-09-30T00:00:00Z")
SENS_LAG = pd.Timedelta(hours=1)
NS_UTC = "datetime64[ns, UTC]"
MOS_SHA256 = {
    "MANIFEST.json": "21844eae6f3398cf4cef4c95b801c1c20383ada008112a1d95cf2eee362bedb3",
    "mos_GFS.parquet": "94c8ba654e9369dfb59578acbc16bf84f97f7680c2f3a783556416f34e6a5cb4",
    "mos_NAM.parquet": "32b92d8ab0a3c0c7c33f6f165aebe0a256fe9eb648cc6f91f44a3a9c22f247ca",
}
STATIONS = {"atlanta": "KATL", "austin": "KAUS", "chicago": "KORD", "dallas": "KDAL", "denver": "KBKF",
            "houston": "KHOU", "los-angeles": "KLAX", "miami": "KMIA", "nyc": "KLGA", "san-francisco": "KSFO",
            "seattle": "KSEA"}


class MosError(mg.GateError):
    """A refused MOS P0 run."""


def verify_mos(mos_root, expected=MOS_SHA256):
    """sha256 of every pinned archive file; refuses on a missing file or a mismatch."""
    root, got = Path(mos_root), {}
    for name, sha in expected.items():
        f = root / name
        if not f.exists():
            raise MosError(f"missing MOS archive file {f}")
        got[name] = ls.sha256_file(f)
        if got[name] != sha:
            raise MosError(f"{name} sha256 {got[name]} != pinned {sha}")
    return got


def load_mos(mos_root, model):
    """Daytime-max rows (station, ftime, runtime, available_utc, value) with runtime < 2026-09-30 00Z and a valid
    value."""
    g = pd.read_parquet(Path(mos_root) / f"mos_{model}.parquet",
                        columns=["station", "runtime", "ftime", FIELD, "available_utc"])
    for c in ("runtime", "ftime", "available_utc"):
        g[c] = pd.to_datetime(g[c], utc=True).astype(NS_UTC)
    g["value"] = pd.to_numeric(g[FIELD], errors="coerce")
    keep = (g.runtime < RUNTIME_END) & g.value.between(*VALID) & g.available_utc.notna()
    return g.loc[keep, ["station", "runtime", "ftime", "available_utc", "value"]].reset_index(drop=True)


def select_values(snaps, local_hour, mos, lag=pd.Timedelta(0)):
    """Per snapshot: the latest run with available_utc + lag <= captured_at_utc for ftime (D + 1) 00Z at the
    market's station -> (value, runtime, available_utc); NaN / NaT outside 07..12 or without such a run.

    Each model's lag is a constant, so the latest available run is also the latest by runtime; ties on
    ``available_utc`` go to the later runtime."""
    k = len(snaps)
    left = pd.DataFrame({"i": np.arange(k), "station": snaps.market.map(STATIONS).to_numpy(),
                         "ftime": (pd.to_datetime(snaps.date.astype(str).to_numpy()).tz_localize("UTC")
                                   + pd.Timedelta(days=1)).astype(NS_UTC),
                         "cap": pd.to_datetime(snaps.captured_at_utc.to_numpy(), utc=True).astype(NS_UTC)})
    hour = np.asarray(local_hour)
    left = left[(hour >= HOURS[0]) & (hour <= HOURS[1]) & left.station.notna().to_numpy() & left.cap.notna()]
    right = mos.assign(t=mos.available_utc + lag).sort_values(["t", "runtime"])
    m = pd.merge_asof(left.sort_values("cap"), right[["station", "ftime", "t", "runtime", "available_utc", "value"]],
                      left_on="cap", right_on="t", by=["station", "ftime"], direction="backward")
    val = np.full(k, np.nan)
    rt = pd.Series(pd.NaT, index=range(k), dtype=NS_UTC)
    av = rt.copy()
    val[m.i.to_numpy()] = m.value.to_numpy(float)
    rt.iloc[m.i.to_numpy()] = m.runtime.to_numpy()
    av.iloc[m.i.to_numpy()] = m.available_utc.to_numpy()
    return val, rt, av


def check_stations(layout):
    """The layout's market -> station map must equal STATIONS (reads only the market and station columns)."""
    s = pd.read_parquet(Path(layout) / "inputs_snapshots.parquet", columns=["market", "station"]).drop_duplicates()
    s = s[s.market != "toronto"]
    seen = s.groupby("market").station.agg(lambda x: sorted(set(x)))
    bad = {m: v for m, v in seen.items() if v != [STATIONS.get(m)]}
    if bad:
        raise MosError(f"layout stations differ from the rule: {bad}")
    return {m: v[0] for m, v in seen.items()}


def market_rows(cid, vecs, fit_t, score_t, score_dates, donors):
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
    for mk in sorted(set(score_t.markets)):
        band = (pop & (score_t.markets == mk))[score_t.band_snap]
        if not band.any():
            continue
        sc_ = sw.date_sums((c - m)[band], e[band], didx[band], nd)
        sp = [sw.date_sums((p - m)[band], e[band], didx[band], nd) for p in pls]
        rows += [{"candidate": cid, "market": mk, "date": score_dates[i], "n_entries": int(sc_[0, i]),
                  "sums_c": sc_[:, i].tolist(), "sums_pl": [s[:, i].tolist() for s in sp]}
                 for i in range(nd) if sc_[0, i] > 0]
    return rows


def _passes(res, threshold):
    lo = res["p0"]["ci95"][0]
    return bool(res["testable"] and res["p0"]["p_one_sided"] <= threshold and lo is not None and lo > 0)


def run(*, layout, out_dir, mos_root, allow_dirty=False):
    """Controls, the two MOS values, P0 for K = 2 plus the +1 h sensitivity arm, the decision, and the w gate only
    for a survivor."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = Path(out_dir)
    if (out / "mos_p0.json").exists():
        raise MosError(f"refusing to overwrite {out / 'mos_p0.json'}")
    if W_BLOCK not in mg.BLOCKS or mg.BLOCKS[W_BLOCK] != HOURS:
        raise MosError("mr_gate.BLOCKS must carry the 07-12 block")
    mos_sha = verify_mos(mos_root)
    stations = check_stations(layout)
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    if "toronto" in set(fit_t.markets):
        raise MosError("the population is the sweep's US markets; toronto is not in the rule")
    controls = mg.market_controls(fit_t, score_t)

    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}

    feats = pd.DataFrame({"row_key": fit_t.snaps.row_key.to_numpy()})
    results, sens, kept, rows = {}, {}, {}, []
    for cid, kind, sign, model in CANDIDATES:
        mos = load_mos(mos_root, model)
        v, rt, av = select_values(fit_t.snaps, fit_t.local_hour, mos)
        v1, rt1, _ = select_values(fit_t.snaps, fit_t.local_hour, mos, lag=SENS_LAG)
        feats[f"{model}_value"], feats[f"{model}_runtime"], feats[f"{model}_available_utc"] = v, rt.values, av.values
        feats[f"{model}_value_lag1h"], feats[f"{model}_runtime_lag1h"] = v1, rt1.values
        res, vecs = sw.p0_candidate(cid, kind, sign, v, fit_t, score_t, geo, counts, score_dates, donors)
        rows += res.pop("_rows", [])
        if vecs is not None:
            kept[cid] = vecs
            rows += market_rows(cid, vecs, fit_t, score_t, score_dates, donors)
        sres, _ = sw.p0_candidate(cid, kind, sign, v1, fit_t, score_t, geo, counts, score_dates, donors)
        sres.pop("_rows", None)
        results[cid], sens[cid] = res, sres
    out.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(out / "features.parquet", index=False)

    ids = [c[0] for c in CANDIDATES]
    adj, reject = sw.bh_adjust([results[c]["p0"]["p_one_sided"] for c in ids])
    pvals = sorted(results[c]["p0"]["p_one_sided"] for c in ids)
    k = len(ids)
    passed = [p for j, p in enumerate(pvals, 1) if p <= sw.BH_Q * j / k]
    threshold = max(passed) if passed else -1.0  # the main arm's BH rejection threshold (step-up)
    for cid, q, rj in zip(ids, adj, reject):
        r, s = results[cid], sens[cid]
        lo = r["p0"]["ci95"][0]
        r["bh_q"], r["bh_reject"] = float(q), bool(rj)
        main_pass = bool(r["testable"] and rj and lo is not None and lo > 0)
        r["sensitivity_lag_plus_1h"] = {"testable": s["testable"], "coverage": s["coverage"], "p0": s["p0"],
                                        "passes_main_threshold": _passes(s, threshold),
                                        "flips_verdict": bool(main_pass != _passes(s, threshold))}
        r["survive"] = main_pass  # amendment 1 A1: the verdict is the main arm's; the sensitivity arm is reported
        r["verdict"] = "SURVIVE" if r["survive"] else ("UNTESTABLE" if not r["testable"] else "KILL")
        if r["survive"] and r["sensitivity_lag_plus_1h"]["flips_verdict"]:
            r["verdict"] = "SURVIVE (sensitivity flip)"

    for cid in [c for c in ids if results[c]["survive"]]:
        vec = kept[cid]
        key = f"w0_identity_{cid}"
        controls[key] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec["c_fit"]))
        if controls[key]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, W_BLOCK, fit_t, score_t, vec["c_fit"], vec["covered"], p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}

    flips = {c: results[c]["sensitivity_lag_plus_1h"]["flips_verdict"] for c in ids}
    lines = [sw.line_for(results[c]) + ("; sensitivity +1 h flips" if flips[c] else "") for c in ids]
    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "amendment_1_sha256": AMENDMENT_1_SHA256,
               "serve_parity_recorder_commit": RECORDER_COMMIT, "ledger_row": LEDGER_ROW, "code": code,
               "evidence_class": "development (dev window, provisional; kill-only)",
               "module_sha256": {"mos_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(sw.__file__),
                                 "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__)},
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "mos_archive_sha256": mos_sha, "stations": stations,
               "features_parquet_sha256": ls.sha256_file(out / "features.parquet"),
               "availability": "modelled (GFS runtime + 4h30 from the NCO schedule; NAM runtime + 4h00 assumed); "
                               "not a capture receipt",
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "markets": sorted(set(score_t.markets)),
                              "local_hours": list(HOURS)},
               "constants": {"field": FIELD, "k": len(ids), "draws": sw.DRAWS, "seed": sw.SEED,
                             "placebo_seeds": list(sw.PLACEBO_SEEDS), "bh_q": sw.BH_Q, "bh_threshold": threshold,
                             "sigma2_floor": sw.SIGMA2_FLOOR, "min_dates": sw.MIN_DATES,
                             "min_snapshots": sw.MIN_SNAPS, "w_block": W_BLOCK, "sensitivity_lag_hours": 1,
                             "valid_range_f": list(VALID), "runtime_end": str(RUNTIME_END)},
               "controls": controls, "results": results, "lines": lines}
    (out / "mos_p0_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                   for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "mos_p0_rows.jsonl")
    (out / "mos_p0.json").write_text(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default),
                                     encoding="utf-8")
    return receipt
