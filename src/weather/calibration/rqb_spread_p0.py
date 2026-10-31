r"""R-Q B captured GEFS spread market-residual P0 (lane L3, 2026-10-30; rule ``RULE_SHA256``, ledger row 88).

Rule ``docs/research/rqb-spread-p0-2026-10-30/rule_rqb_spread_p0.md`` (sha256 ``844c2eb5…``, on the ledger
branch ``claude/successor-batch-20261030``). Its own arm (K = 1), not pooled with the MR sweep (row 78) or the
marine P0 (row 87). The candidate ``GEFS-SPREAD80`` is the captured ``global_ensemble.day_member_high_spread_80``
(type S, sign +) at local hours 00..06. A snapshot is covered when the source is ``ok``, ``fetched_at`` <=
``captured_at_utc`` and the value is finite. Everything downstream is ``mr_sweep``'s machinery unchanged
(type S tilt, the calibration-matched disagreement placebo, 20 derangements, the paired date-cluster
bootstrap with 10,000 draws and seed 20261024). BH at q = 0.10 with K = 1 is p <= 0.10, and a survivor also
needs the Delta lower bound > 0. Only a survivor gets the w = 0 identity and the w gate in block 00-06. One
run; nothing after 2026-09-29 is read.

Writes ``rqb_spread_p0.json`` (never overwrites), ``rqb_spread_p0_rows.jsonl`` (per date, plus per market and
date) and ``features.parquet``.

    python -m weather.calibration.loyo_screen rqb-spread-p0 --layout C:/swarm/v3layout \
        --replay-root <replay-inputs-le0929> --out C:/t/l3rqb/p0
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from weather.calibration import loyo_screen as ls
from weather.calibration import mr_gate as mg
from weather.calibration import mr_sweep as sw

SCHEMA = "rqb_spread_p0/1"
GATE = "RQB-SPREAD-P0"
RULE_SHA256 = "844c2eb516da7dcff92ba25a150e8b12a1c7ead47289aaa8ed066e82357415d3"
LEDGER_ROW = 88
HOURS = (0, 6)
W_BLOCK = "00-06"
CANDIDATE = ("GEFS-SPREAD80", "S", 1)
FIELD = "day_member_high_spread_80"


class RqbError(mg.GateError):
    """A refused R-Q B spread P0 run."""


def record_spread(rec):
    """One replay record -> (spread, receipt); NaN / None unless ``global_ensemble`` is ``ok``."""
    s = (rec.get("sources") or {}).get("global_ensemble") or {}
    if s.get("ok") is not True:
        return np.nan, None
    return sw._num((s.get("data") or {}).get(FIELD)), s.get("fetched_at")


def extract_spread(replay_root, row_keys):
    """Stream the layout's replay records (read only) -> (row_key, spread, rc_ge), records read, malformed lines.

    The same scan as ``mr_sweep.extract_features``: a truncated line is skipped and listed; the last complete
    record of a snapshot wins."""
    root = Path(replay_root) / "snapshots"
    keys, rows, seen, malformed = set(row_keys), [], 0, []
    markets = {k.split("|", 1)[0] for k in keys}
    for folder in sorted(root.iterdir()):
        hit = sw.SLUG.match(folder.name)
        f = folder / "replay_inputs.jsonl"
        if not hit or hit["market"] not in markets or not f.exists():
            continue
        market = hit["market"]
        with f.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not any(f"{market}|{sid}" in keys for sid in sw.SNAP_ID.findall(line)):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    malformed.append({"file": folder.name, "line": lineno, "chars": len(line),
                                      "error": str(exc)[:120]})
                    continue
                rk = f"{market}|{rec.get('snapshot_id')}"
                if rk not in keys:
                    continue
                seen += 1
                v, rc = record_spread(rec)
                rows.append({"row_key": rk, "spread80": v, "rc_ge": rc})
    frame = pd.DataFrame(rows, columns=["row_key", "spread80", "rc_ge"])
    if frame.empty:
        raise RqbError(f"no replay record matched the layout under {root}")
    return frame.drop_duplicates("row_key", keep="last").reset_index(drop=True), seen, malformed


def spread_values(snaps, local_hour, feats):
    """GEFS-SPREAD80 on ``snaps``: NaN outside 00..06, without a value, without a receipt or with a receipt
    after capture."""
    f = feats.set_index("row_key").reindex(snaps.row_key.to_numpy())
    cap = sw._utc(snaps.captured_at_utc)
    rc = sw._utc(f["rc_ge"])
    v = f["spread80"].to_numpy(float)
    ok = (np.isfinite(v) & ~np.isnat(rc) & ~np.isnat(cap) & (rc <= cap)
          & (local_hour >= HOURS[0]) & (local_hour <= HOURS[1]))
    return np.where(ok, v, np.nan)


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


def run(*, layout, out_dir, replay_root=sw.DEFAULT_REPLAY, allow_dirty=False):
    """Controls, the captured spread, P0 for K = 1, the decision, and the w gate only for a survivor."""
    code = ls.require_clean(ls.code_state(), allow_dirty)
    from weather.calibration import market_blend as mb
    from weather.reporting.scorecards import dev_scorecard as sc

    out = Path(out_dir)
    if (out / "rqb_spread_p0.json").exists():
        raise RqbError(f"refusing to overwrite {out / 'rqb_spread_p0.json'}")
    sums_path = Path(replay_root) / "SHA256SUMS"
    if not sums_path.exists():
        raise RqbError(f"replay SHA256SUMS missing under {replay_root}")
    if W_BLOCK not in mg.BLOCKS or mg.BLOCKS[W_BLOCK] != HOURS:
        raise RqbError("mr_gate.BLOCKS must carry the 00-06 block")
    lay, folds, burn, scored, fit_t, score_t = mg.build_tables(layout)
    if "toronto" in set(fit_t.markets):
        raise RqbError("the population is the sweep's US markets; toronto is not in the rule")
    controls = mg.market_controls(fit_t, score_t)

    feats, n_records, malformed = extract_spread(replay_root, set(fit_t.snaps.row_key))
    out.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(out / "features.parquet", index=False)
    values = spread_values(fit_t.snaps, fit_t.local_hour, feats)
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted({str(d) for d in score_t.snaps.date.astype(str)}))
    counts = sw.boot_counts(len(score_dates))
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}

    cid, kind, sign = CANDIDATE
    res, vecs = sw.p0_candidate(cid, kind, sign, values, fit_t, score_t, geo, counts, score_dates, donors)
    rows = res.pop("_rows", [])
    if vecs is not None:
        rows += market_rows(cid, vecs, fit_t, score_t, score_dates, donors)
    adj, reject = sw.bh_adjust([res["p0"]["p_one_sided"]])
    lo = res["p0"]["ci95"][0]
    res["bh_q"], res["bh_reject"] = float(adj[0]), bool(reject[0])
    res["survive"] = bool(res["testable"] and reject[0] and lo is not None and lo > 0)
    res["verdict"] = "SURVIVE" if res["survive"] else ("UNTESTABLE" if not res["testable"] else "KILL")
    if res["survive"]:
        key = f"w0_identity_{cid}"
        controls[key] = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, vecs["c_fit"]))
        if controls[key]["verdict"] != "PASS":
            raise mb.ControlFailed(f"refused: w = 0 identity failed for {cid}")
        g = mg.gate_candidate(cid, W_BLOCK, fit_t, score_t, vecs["c_fit"], vecs["covered"],
                              p_placebo_fit=vecs["pl0_fit"])
        res["w_gate"] = {"verdict": "PASS (w)" if g["w"]["pass"] else "KILL (w)", "w": g["w"], "rows": g["rows"],
                         "per_hour": g["per_hour"], "coverage": g["coverage"]}

    line = sw.line_for(res)
    receipt = {"schema": SCHEMA, "gate": GATE, "rule_sha256": RULE_SHA256, "ledger_row": LEDGER_ROW, "code": code,
               "evidence_class": "development (dev window, provisional; kill-only)",
               "module_sha256": {"rqb_spread_p0": ls.sha256_file(__file__), "mr_sweep": ls.sha256_file(sw.__file__),
                                 "mr_gate": ls.sha256_file(mg.__file__), "market_blend": ls.sha256_file(mb.__file__)},
               "scorecard_code_sha256": sc.code_sha256(), "layout_manifest_sha256": lay.manifest_sha256,
               "replay_sha256sums_sha256": ls.sha256_file(sums_path),
               "features_parquet_sha256": ls.sha256_file(out / "features.parquet"),
               "replay_records_read": n_records, "replay_malformed_lines": malformed,
               "population": {"burn_in_dates": burn, "scored_first": scored[0], "scored_last": scored[-1],
                              "n_scored_dates": len(scored), "markets": sorted(set(score_t.markets)),
                              "local_hours": list(HOURS)},
               "constants": {"field": FIELD, "k": 1, "draws": sw.DRAWS, "seed": sw.SEED,
                             "placebo_seeds": list(sw.PLACEBO_SEEDS), "bh_q": sw.BH_Q,
                             "sigma2_floor": sw.SIGMA2_FLOOR, "min_dates": sw.MIN_DATES,
                             "min_snapshots": sw.MIN_SNAPS, "w_block": W_BLOCK},
               "controls": controls, "result": res, "line": line}
    (out / "rqb_spread_p0_rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True, default=mg._default) + "\n"
                                                          for r in rows), encoding="utf-8")
    receipt["rows_sha256"] = ls.sha256_file(out / "rqb_spread_p0_rows.jsonl")
    (out / "rqb_spread_p0.json").write_text(json.dumps(receipt, indent=1, sort_keys=True, default=mg._default),
                                            encoding="utf-8")
    return receipt
