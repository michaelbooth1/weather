"""Lane L2: the single look of the L6_G forward screen (L6_G vs L6 at local 07-12; no price is ever read).

Pre-registration: ``docs/research/gefs-members-l11-2026-10-26/l6g_forward_prereg_DRAFT.md`` (§5-§7, §9). The look
reads the accrued per-snapshot band vectors of both arms (inputs, written outcome-blind during accrual), the GEFS
forward recorder's per-date manifests (only the ``g_lastmodified_rule`` table decides; ``g_fetched_rule`` is counted
and reported, never used) and, last and only after every guard has passed, the venue-rule band labels.

Guards, all before any label is read: today >= 2026-12-13 and after the 45th countable date; MG-1's and B's look
receipts exist; this look's receipt does not exist (single look, written with exclusive create); the frozen state
file has its pinned sha256; no input carries a price, market or quote column; the countable dates are exactly 45,
from D0, with D0 <= 2026-11-02.

Estimand (B-1 §5 with the comparator changed to L6): Δ = mean over equal (date, market) cells of
[Brier(L6_G) - Brier(L6)], per-snapshot band Brier (mean over bands), equal snapshot weights within a cell, on
snapshots both arms cover with G present; fixed-market date-clustered percentile 95% interval, 2,000 draws, seed
20260921. PASS: U < 0 and no hour h07..h12 has its lower bound > 0. FAIL: L > 0. Else INCONCLUSIVE. VOID when fewer
than 40 dates survive the 90% coverage drop or a control fails.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

NAME = "l6g_forward_look"
SCHEMA = "l6g_forward_look/1"
STATE_SHA256 = "ae95686b5468bceed0fd33ead0f397dc061d9a5822f56bfb2364814553e8983e"
RECORDER_SCHEMA = "l6g_gefs_forward_points/1"
DECIDING_TABLE = "g_lastmodified_rule"
REPORTED_TABLE = "g_fetched_rule"
LOOK_EARLIEST = dt.date(2026, 12, 13)
D0_LATEST = dt.date(2026, 11, 2)
MARKETS = ("atlanta", "austin", "chicago", "dallas", "houston", "los-angeles", "miami", "nyc", "san-francisco",
           "seattle")
HOURS = (7, 8, 9, 10, 11, 12)
N_DATES = 45
MIN_SURVIVING = 40
COVERAGE_MIN = 0.90
DRAWS = 2000
SEED = 20260921
CONTROL_TOL = 1e-12
MASS_TOL = 1e-9
VECTOR_COLUMNS = ("date", "market", "snapshot_id", "local_hour", "band_index", "p_l6", "p_l6g", "covered_l6",
                  "g_present", "state_sha256")
LABEL_COLUMNS = ("date", "market", "band_index", "y")
_PRICE_MARKERS = ("price", "p_market", "market_yes", "bid", "ask", "mid", "quote", "book", "last_trade")


class LookError(RuntimeError):
    """A guard refused the look; nothing was scored and no label was read."""


def module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refuse_price_columns(columns, what):
    bad = sorted(c for c in columns if any(k in str(c).lower() for k in _PRICE_MARKERS))
    if bad:
        raise LookError(f"{what} carries price/market columns {bad}; the L6_G look never reads a price")


def load_state(path):
    """{hour: (a, b)} from the frozen state file, refused unless its sha256 is the pinned one."""
    if _sha(path) != STATE_SHA256:
        raise LookError("frozen state sha256 differs from the pin")
    doc = json.loads(Path(path).read_bytes())
    return {int(k[1:]): (float(v["a"]), float(v["b"])) for k, v in doc["state"].items()}


def look_guard(*, today, countable_dates, mg1_look_receipt, b_look_receipt, out):
    """Every refusal that must hold before any label is read."""
    dates = sorted(dt.date.fromisoformat(str(d)[:10]) for d in countable_dates)
    if len(dates) != N_DATES or len(set(dates)) != N_DATES:
        raise LookError(f"exactly {N_DATES} distinct countable dates are required, got {len(set(dates))}")
    if dates[0] > D0_LATEST:
        raise LookError(f"D0 {dates[0]} is after the cap {D0_LATEST}")
    if today < LOOK_EARLIEST or today <= dates[-1]:
        raise LookError(f"no look before {LOOK_EARLIEST} or before the 45th date ({dates[-1]}) has passed")
    for name, path in (("MG-1", mg1_look_receipt), ("B", b_look_receipt)):
        if not Path(path).is_file():
            raise LookError(f"{name}'s look receipt is absent: the L6_G look is strictly after it")
    if Path(out).exists():
        raise LookError("this look's receipt already exists: single look")
    return [d.isoformat() for d in dates]


def forward_g_presence(manifest_root, dates, markets=MARKETS, hours=HOURS):
    """{(market, date, hour): bool} from the deciding (LastModified-rule) table only, plus the reported-only
    fetched-rule non-null count. Values are never returned; G itself was applied during accrual."""
    present, fetched_count, problems = {}, 0, []
    for d in dates:
        path = Path(manifest_root) / d / "manifest.json"
        if not path.is_file():
            problems.append(f"{d}: recorder manifest missing")
            continue
        m = json.loads(path.read_bytes())
        if m.get("schema") != RECORDER_SCHEMA or m.get("date") != d:
            problems.append(f"{d}: recorder manifest schema/date mismatch")
            continue
        deciding, reported = m[DECIDING_TABLE], m.get(REPORTED_TABLE, {})
        for mk in markets:
            for h in hours:
                present[(mk, d, h)] = deciding.get(mk, {}).get(f"h{h:02d}") is not None
                fetched_count += reported.get(mk, {}).get(f"h{h:02d}") is not None
    return present, fetched_count, problems


def decide(primary, hour_rows):
    lo, hi = primary["ci95"]
    if lo is not None and lo > 0:
        return "FAIL"
    if hi is not None and hi < 0 and not any(r["ci95"][0] is not None and r["ci95"][0] > 0 for r in hour_rows):
        return "PASS"
    return "INCONCLUSIVE"


def score(vectors, labels, g_present, dates):
    """The §5 estimand on prepared frames; returns (result, void_conditions). Pure: no I/O, no clock."""
    import numpy as np

    from weather.calibration.r0_ols_floor_challenger import _date_weights
    from weather.reporting.scorecards.dev_scorecard import ratio_interval

    voids = []
    v = vectors[vectors["date"].isin(dates) & vectors["market"].isin(MARKETS)
                & vectors["local_hour"].isin(HOURS)].copy()
    if set(v["state_sha256"].unique()) - {STATE_SHA256}:
        voids.append("vectors were emitted under another state")
    v["g_lm"] = [g_present.get((mk, d, int(h)), False) for mk, d, h in zip(v["market"], v["date"], v["local_hour"])]
    if bool((v["g_present"].astype(bool) != v["g_lm"]).any()):
        voids.append("vector G presence disagrees with the recorder's LastModified-rule table")
    off = ~v["g_lm"]
    if len(v) and float(np.max(np.abs((v.loc[off, "p_l6g"] - v.loc[off, "p_l6"]).to_numpy()), initial=0.0)) > CONTROL_TOL:
        voids.append("positive control: L6_G differs from L6 where G is absent (s must be 0)")
    snap_keys = ["date", "market", "snapshot_id"]
    mass = v.groupby(snap_keys)[["p_l6", "p_l6g"]].sum()
    if len(mass) and float(np.max(np.abs(mass.to_numpy() - 1.0))) > MASS_TOL:
        voids.append("probability mass not preserved")
    v = v.merge(labels[list(LABEL_COLUMNS)], on=["date", "market", "band_index"], how="left", validate="many_to_one")
    if v["y"].isna().any():
        voids.append("a scored band has no label")
    v["b6"] = (v["p_l6"] - v["y"]) ** 2
    v["bg"] = (v["p_l6g"] - v["y"]) ** 2
    snaps = v.groupby(snap_keys, sort=True).agg(local_hour=("local_hour", "first"), b6=("b6", "mean"),
                                                 bg=("bg", "mean"), cov=("covered_l6", "all"), g=("g_lm", "all"))
    snaps = snaps.reset_index()
    snaps["both"] = snaps["cov"].astype(bool) & snaps["g"].astype(bool)
    frac = snaps.groupby("date")["both"].mean()
    dropped = sorted(d for d in dates if frac.get(d, 0.0) < COVERAGE_MIN)
    surviving = [d for d in dates if d not in dropped]
    if len(surviving) < MIN_SURVIVING:
        voids.append(f"only {len(surviving)} of {N_DATES} dates survive the coverage drop")
    s = snaps[snaps["both"] & snaps["date"].isin(surviving)]

    def interval(rows):
        cells = rows.groupby(["date", "market"], sort=True)[["bg", "b6"]].mean().reset_index()
        if cells.empty:
            return {"estimate": None, "ci95": [None, None], "n_cells": 0}
        w = _date_weights(cells["date"].to_numpy(), DRAWS, SEED)
        out = ratio_interval(w, (cells["bg"] - cells["b6"]).to_numpy(float), np.ones(len(cells)))
        out["n_cells"] = int(len(cells))
        return out

    primary = interval(s)
    hour_rows = [{"group": f"h{h:02d}", **interval(s[s["local_hour"] == h])} for h in HOURS]
    result = {"primary_07_12": primary, "hours": hour_rows, "dropped_dates": dropped,
              "surviving_dates": len(surviving), "scored_snapshots": int(len(s)),
              "verdict": "VOID" if voids else decide(primary, hour_rows)}
    return result, voids


def run_look(*, vectors, labels, countable_dates, recorder_root, state, mg1_look_receipt, b_look_receipt, out,
             today=None):
    import pandas as pd

    today = today or dt.date.today()
    dates = look_guard(today=today, countable_dates=countable_dates, mg1_look_receipt=mg1_look_receipt,
                       b_look_receipt=b_look_receipt, out=out)
    load_state(state)
    vec = pd.read_parquet(vectors)
    refuse_price_columns(vec.columns, "vectors")
    missing = set(VECTOR_COLUMNS) - set(vec.columns)
    if missing:
        raise LookError(f"vectors lack {sorted(missing)}")
    vec["date"] = vec["date"].astype(str).str[:10]
    present, fetched_count, problems = forward_g_presence(recorder_root, dates)
    lab = pd.read_parquet(labels)  # the only label read, after every guard
    refuse_price_columns(lab.columns, "labels")
    lab["date"] = lab["date"].astype(str).str[:10]
    result, voids = score(vec, lab, present, dates)
    voids += problems
    if voids:
        result["verdict"] = "VOID"
    receipt = {"schema": SCHEMA, "look_date": today.isoformat(), "countable_dates": dates, "result": result,
               "void_conditions": voids, "deciding_g_table": DECIDING_TABLE,
               "reported_only": {"fetched_rule_nonnull_cells": fetched_count},
               "inputs": {"state_sha256": STATE_SHA256, "vectors_sha256": _sha(vectors), "labels_sha256": _sha(labels),
                          "mg1_look_receipt_sha256": _sha(mg1_look_receipt),
                          "b_look_receipt_sha256": _sha(b_look_receipt), "module_sha256": module_sha256()}}
    with open(out, "x", encoding="utf-8") as handle:  # exclusive create: a second look fails here
        handle.write(json.dumps(receipt, indent=1, sort_keys=True) + "\n")
    return receipt


def main(argv=None):
    p = argparse.ArgumentParser(prog=f"python -m weather.calibration.{NAME}", description=__doc__.split("\n\n")[0])
    for flag in ("--vectors", "--labels", "--countable-dates", "--recorder-root", "--state", "--mg1-look-receipt",
                 "--b-look-receipt", "--out"):
        p.add_argument(flag, required=True)
    a = p.parse_args(argv)
    dates = [line.strip() for line in Path(a.countable_dates).read_text(encoding="utf-8").splitlines() if line.strip()]
    receipt = run_look(vectors=a.vectors, labels=a.labels, countable_dates=dates, recorder_root=a.recorder_root,
                       state=a.state, mg1_look_receipt=a.mg1_look_receipt, b_look_receipt=a.b_look_receipt,
                       out=a.out)
    print(json.dumps({"verdict": receipt["result"]["verdict"], "primary": receipt["result"]["primary_07_12"]}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
