r"""MRMS echo against the market: market-residual P0 (lane L3, 2026-10-30; rule ``RULE_SHA256``, ledger row 91).

Rule ``docs/research/mrms-market-p0-2026-10-30/rule_mrms_p0.md`` (sha256 ``b0f170a5…``, on the ledger branch
``claude/successor-batch-20261030``). Its own arm (K = 2), not pooled with rows 78, 81 or 85-90. The candidates are
the MRMS composite reflectivity maximum within 25 km of the market's station, g = max(``max_dbz_25km``, 0)
(``MRMS-MAXDBZ25``), and the F2 echo flag 1[``max_dbz_25km`` >= 35] (``MRMS-ECHO35``), both type D with sign -1
(a high echo moves mass to the lower bands), at local hours 13..16. The selected slot is F2's join: the newest slot
at the station with ``valid_utc + 5 min <= captured_at_utc`` and ``valid_utc >= captured_at_utc - 40 min``. A market
whose g has sd < 1e-9 over its covered fit snapshots gets g_z = 0 (zero tilt). The 50 km values are a descriptive
arm (not in K); ``cover_25km`` is radar data coverage (``free_screens/mrms.py:119``) and is reported as QC only.
Everything downstream is ``mr_sweep``'s machinery unchanged (type D tilt, the calibration-matched disagreement
placebo, 20 derangements, the paired date-cluster bootstrap with 10,000 draws and seed 20261024, BH q = 0.10).
Only a survivor gets the w = 0 identity and the w gate in block 13-16. One run; nothing after 2026-09-29 is read.

Reads the layout and the sha-pinned MRMS station table; no network. Writes ``mrms_p0.json`` (never overwrites),
``mrms_p0_rows.jsonl`` (per date, plus per market and date) and ``features.parquet``.

    python -m weather.calibration.loyo_screen mrms-p0 --layout C:/swarm/v3layout \
        --refl C:/Users/Michael/Documents/github/weather/data/research/free_sources/mrms_refl/station_refl.parquet \
        --out C:/t/l3mrms/p0
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mos_p0 as mp
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "mrms_p0/1"
GATE = "MRMS-P0"
RULE_SHA256 = "b0f170a5a69b93c040d3b7092e5c3f2ce2eb9a626978ad77f2b2f69e02fa091e"
LEDGER_ROW = 91
HOURS = (13, 16)
W_BLOCK = "13-16"
REFL_SHA256 = "3446d1a6d134b6059b4ca7d1e3694bc7cc3a033bae6a65ba73850c49acee97be"
LAG = pd.Timedelta(minutes=5)
MAX_AGE = pd.Timedelta(minutes=40)
ECHO_DBZ = 35.0
SD_FLOOR = 1e-9
VALID_END = pd.Timestamp("2026-09-30T00:00:00Z")
CANDIDATES = (("MRMS-MAXDBZ25", "D", -1, "maxdbz", 25), ("MRMS-ECHO35", "D", -1, "echo35", 25))
DESCRIPTIVE = (("MRMS-MAXDBZ50", "D", -1, "maxdbz", 50), ("MRMS-ECHO35-50", "D", -1, "echo35", 50))
NS_UTC = mp.NS_UTC
STATIONS = mp.STATIONS


class MrmsError(mg.GateError):
    """A refused MRMS P0 run."""


def verify_refl(path, expected=REFL_SHA256):
    """sha256 of the pinned station table; refuses on a missing file or a mismatch."""
    f = Path(path)
    if not f.exists():
        raise MrmsError(f"missing MRMS station table {f}")
    got = ls.sha256_file(f)
    if got != expected:
        raise MrmsError(f"{f.name} sha256 {got} != pinned {expected}")
    return got


def load_refl(path):
    """Station-slot rows (station, valid_utc, max_dbz_25km/50km, cover_25km/50km) with valid_utc < 2026-09-30."""
    r = pd.read_parquet(Path(path), columns=["station", "valid_utc", "max_dbz_25km", "max_dbz_50km",
                                             "cover_25km", "cover_50km"])
    r["valid_utc"] = pd.to_datetime(r.valid_utc, utc=True).astype(NS_UTC)
    r = r[r.valid_utc.notna() & (r.valid_utc < VALID_END)]
    return r.reset_index(drop=True)


def select_slots(snaps, local_hour, refl):
    """Per snapshot: the newest slot at the market's station with valid + 5 min <= captured_at_utc and
    valid >= captured_at_utc - 40 min -> a frame of the slot's columns (NaN / NaT outside 13..16 or without one)."""
    k = len(snaps)
    left = pd.DataFrame({"i": np.arange(k), "station": snaps.market.map(STATIONS).to_numpy(),
                         "cap": pd.to_datetime(snaps.captured_at_utc.to_numpy(), utc=True).astype(NS_UTC)})
    hour = np.asarray(local_hour)
    left = left[(hour >= HOURS[0]) & (hour <= HOURS[1]) & left.station.notna().to_numpy() & left.cap.notna()]
    right = refl.assign(t=refl.valid_utc + LAG).sort_values(["t", "station"])
    m = pd.merge_asof(left.sort_values("cap"), right, left_on="cap", right_on="t", by="station",
                      direction="backward")
    m = m[m.valid_utc.notna() & (m.valid_utc >= m.cap - MAX_AGE)]
    out = pd.DataFrame({"valid_utc": pd.Series(pd.NaT, index=range(k), dtype=NS_UTC)})
    for c in ("max_dbz_25km", "max_dbz_50km", "cover_25km", "cover_50km"):
        out[c] = np.nan
        out.loc[m.i.to_numpy(), c] = m[c].to_numpy(float)
    out.loc[m.i.to_numpy(), "valid_utc"] = m.valid_utc.to_numpy()
    return out


def candidate_value(slots, construct, radius):
    """g per snapshot: max(dbz, 0) or 1[dbz >= 35] at the radius; NaN where the slot or its dbz is missing."""
    dbz = slots[f"max_dbz_{radius}km"].to_numpy(float)
    if construct == "maxdbz":
        return np.where(np.isfinite(dbz), np.maximum(dbz, 0.0), np.nan)
    if construct == "echo35":
        return np.where(np.isfinite(dbz), (dbz >= ECHO_DBZ).astype(float), np.nan)
    raise MrmsError(f"unknown construct {construct}")


def zscore(values, markets):
    """g_z within market over covered snapshots; a market with sd < 1e-9 gets 0 (zero tilt). Returns
    (g_z, degenerate markets). ``mr_sweep.standardise`` of the result is the result (idempotent)."""
    out = np.full(len(values), np.nan)
    degenerate = []
    for mk in np.unique(markets):
        sel = (markets == mk) & np.isfinite(values)
        if not sel.any():
            continue
        sd = values[sel].std() if sel.sum() >= 2 else 0.0
        if sd < SD_FLOOR:
            out[sel] = 0.0
            degenerate.append(str(mk))
        else:
            out[sel] = (values[sel] - values[sel].mean()) / sd
    return out, degenerate


def _qc(slots, covered_hours):
    c = slots.loc[covered_hours]
    return {"slots_joined": int(c.valid_utc.notna().sum()),
            "cover_25km_below_1": int((c.cover_25km < 1).sum()), "cover_25km_mean": float(c.cover_25km.mean()),
            "cover_50km_below_1": int((c.cover_50km < 1).sum()),
            "max_dbz_25km_nan_on_joined": int((c.valid_utc.notna() & c.max_dbz_25km.isna()).sum())}


def run(*, layout, out_dir, refl_path, allow_dirty=False):
    """Controls, the MRMS values, P0 for K = 2 plus the descriptive 50 km arm, the decision, and the w gate only
    for a survivor."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = Path(out_dir)
    if (out / "mrms_p0.json").exists():
        raise MrmsError(f"refusing to overwrite {out / 'mrms_p0.json'}")
    if W_BLOCK not in mg.BLOCKS or mg.BLOCKS[W_BLOCK] != HOURS:
        raise MrmsError("mr_gate.BLOCKS must carry the 13-16 block")
    refl_sha = verify_refl(refl_path)
    stations = mp.check_stations(layout)
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    if "toronto" in set(fit_t.markets):
        raise MrmsError("the population is the sweep's US markets; toronto is not in the rule")
    controls = mg.market_controls(fit_t, score_t)

    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}

    slots = select_slots(fit_t.snaps, fit_t.local_hour, load_refl(refl_path))
    hours = (np.asarray(fit_t.local_hour) >= HOURS[0]) & (np.asarray(fit_t.local_hour) <= HOURS[1])
    feats = pd.DataFrame({"row_key": fit_t.snaps.row_key.to_numpy(), "slot_valid_utc": slots.valid_utc.values})
    for c in ("max_dbz_25km", "max_dbz_50km", "cover_25km", "cover_50km"):
        feats[c] = slots[c].to_numpy()
    results, descriptive, kept, rows, degenerate = {}, {}, {}, [], {}
    for arm, cands in (("main", CANDIDATES), ("descriptive", DESCRIPTIVE)):
        for cid, kind, sign, construct, radius in cands:
            g = candidate_value(slots, construct, radius)
            gz, degenerate[cid] = zscore(g, np.asarray(fit_t.markets))
            feats[f"{cid}_g"], feats[f"{cid}_gz"] = g, gz
            res, vecs = sw.p0_candidate(cid, kind, sign, gz, fit_t, score_t, geo, counts, score_dates, donors)
            res["zero_tilt_markets"] = degenerate[cid]
            if arm == "main":
                rows += res.pop("_rows", [])
                if vecs is not None:
                    kept[cid] = vecs
                    rows += mp.market_rows(cid, vecs, fit_t, score_t, score_dates, donors)
                results[cid] = res
            else:
                res.pop("_rows", None)
                res["arm"] = "descriptive (not in K, no decision)"
                descriptive[cid] = res
    out.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(out / "features.parquet", index=False)

    ids = [c[0] for c in CANDIDATES]
    adj, reject = sw.bh_adjust([results[c]["p0"]["p_one_sided"] for c in ids])
    for cid, q, rj in zip(ids, adj, reject):
        r = results[cid]
        lo = r["p0"]["ci95"][0]
        r["bh_q"], r["bh_reject"] = float(q), bool(rj)
        r["survive"] = bool(r["testable"] and rj and lo is not None and lo > 0)
        r["verdict"] = "SURVIVE" if r["survive"] else ("UNTESTABLE" if not r["testable"] else "KILL")

    for cid in [c for c in ids if results[c]["survive"]]:
        vec = kept[cid]
        key = f"w0_identity_{cid}"
        controls[key] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vec["c_fit"]))
        if controls[key]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, W_BLOCK, fit_t, score_t, vec["c_fit"], vec["covered"], p_placebo_fit=vec["pl0_fit"])
        results[cid]["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"],
                                  "rows": g["rows"], "per_hour": g["per_hour"], "coverage": g["coverage"]}

    lines = [sw.line_for(results[c]) for c in ids]
    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
               "evidence_class": "development (dev window, provisional; kill-only)",
               "serve_parity": "NONE (no production capture; capture change held, DECISION_LOG 2026-10-24)",
               "module_sha256": {"mrms_p0": ls.sha256_file(__file__), "mos_p0": ls.sha256_file(mp.__file__),
                                 "mr_sweep": ls.sha256_file(sw.__file__), "mr_gate": ls.sha256_file(mg.__file__),
                                 "market_blend": ls.sha256_file(mb.__file__)},
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "refl_sha256": refl_sha, "stations": stations,
               "features_parquet_sha256": ls.sha256_file(out / "features.parquet"),
               "qc": _qc(slots, hours),
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "markets": sorted(set(score_t.markets)),
                              "local_hours": list(HOURS)},
               "constants": {"k": len(ids), "draws": sw.DRAWS, "seed": sw.SEED,
                             "placebo_seeds": list(sw.PLACEBO_SEEDS), "bh_q": sw.BH_Q,
                             "sigma2_floor": sw.SIGMA2_FLOOR, "min_dates": sw.MIN_DATES,
                             "min_snapshots": sw.MIN_SNAPS, "w_block": W_BLOCK, "lag_minutes": 5,
                             "max_age_minutes": 40, "echo_dbz": ECHO_DBZ, "sd_floor": SD_FLOOR,
                             "valid_end": str(VALID_END)},
               "controls": controls, "results": results, "descriptive": descriptive, "lines": lines}
    (out / "mrms_p0_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                    for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "mrms_p0_rows.jsonl")
    (out / "mrms_p0.json").write_text(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default),
                                      encoding="utf-8")
    return receipt
