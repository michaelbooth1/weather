"""Development scorecard: a model variant vs captured market prices vs WU settlement, walk-forward.

Development evidence only (target dates 2026-07-31..2026-09-29; every later date is refused before
any file is opened). Nothing here is confirmation, edge or promotion evidence. Inputs, date guard,
fold scheme and candidate protocols: ``weather.reporting.scorecards.dev_scorecard_data``.

Scoring follows HARNESS v2/v3 (``tools/research/model_parity``) so a v3 number is reproducible here:

- per-snapshot Brier = mean over the snapshot's bands of (p - y)^2, y = 1 on the settled band;
- snapshots are averaged within a (date, market) cell and every cell weighs the same;
- intervals come from one crossed date x market multinomial weight matrix (2,000 draws, seed
  20260921, the 81a ``crossed_weights``) over the scored cells; a per-market row is therefore
  date-clustered only;
- a candidate gets the rule-4 floor mask (a non-``gte`` band whose high is below
  ``floor(max(guidance_physical_floor, high_so_far, trusted_current_max) + 0.5)`` gets 0, then
  renormalise) and falls back to served on any snapshot it does not cover; ``served`` and
  ``market`` are scored as captured;
- gap ratio R = Brier_model / Brier_market (ratio of cell means), not interpretable when the
  market Brier is below 0.005;
- secondary: log score of the settled band on the band vector normalised to 1, clipped at 1e-4.

Powered flag: a row is ``powered`` only when every clustering dimension it is resampled over has at
least ``CLUSTER_FLOOR`` (12) clusters: dates for a per-market row, dates and markets for a pooled row
(EF section 1d: the market clusters set a hard floor; 11 US markets cap crossed power, EF section 10j).

Base caveat (EF section 10v): ``served`` is the served vector of record captured at the time. A
replay of current code does not reproduce it on dev dates (4-22% of snapshots within 1e-9), so a
replay-derived candidate's delta to ``served`` is "current code +/- variant" mixed with code drift;
compare such a candidate with a current-code base replay scored the same way.

CLI::

    python -m weather.reporting.scorecards.dev_scorecard score --layout <v3 layout dir> \\
        --from 2026-08-01 --to 2026-09-29 --candidate served --out <dir>
    python -m weather.reporting.scorecards.dev_scorecard control-floor --fixture <csv[.gz]> --out <dir>

Outputs are content-addressed: ``<out>/<sha256>.json`` (sha256 of the canonical JSON bytes) and
``<out>/<sha256>.md``.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from weather.reporting.scorecards import dev_scorecard_data as data

# Not a schema-registry artifact on purpose: schema_registry_data is in the capture-loop import closure.
SCHEMA_VERSION = "dev_scorecard/1"
DRAWS = 2000
SEED = 20260921
MDE_EFFECT = -0.0075
CLUSTER_FLOOR = 12
MARKET_BRIER_FLOOR = 0.005
LOG_EPS = 1e-4
BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))
AGGREGATES = (("00-12", 0, 12), ("00-16", 0, 16), ("all", 0, 23))
GROUPS = BLOCKS + AGGREGATES
# --hourly: one row per local hour plus the 07-12 morning aggregate (lever L4 headline).
HOURLY_GROUPS = tuple((f"h{h:02d}", h, h) for h in range(24)) + (("07-12", 7, 12),)
ALL_MARKETS = "ALL"
BASE_CAVEAT = ("EF 10v: 'served' is the served vector of record; a current-code replay does not reproduce "
               "it on dev dates, so a replay-derived candidate minus served mixes code drift with the variant.")
# EF section 3 positive control (2026-08-06 skill tracker; fixture vendored from ba748b76).
FLOOR_FIXTURE_SHA256 = "8ac77c0840b0ad6dd581cb0ecfc2449ffc5db53d788d715861c7411b07291405"
FLOOR_TRACKER_SEED, FLOOR_TRACKER_REPS = 3_215_258_335, 2000
FLOOR_REFERENCE = {"baseline": 1.6639158425, "hard": 1.4979600580, "delta": -0.1659557845,
                   "ci95": [-0.3552671491, -0.0697874559]}


# ----------------------------------------------------------------------------- statistics

def crossed_weights(dates, markets, draws=DRAWS, seed=SEED):
    """Independent multinomial date and market counts (81a ``crossed_weights``, verbatim)."""
    _, di = np.unique(np.asarray(dates), return_inverse=True)
    _, mi = np.unique(np.asarray(markets), return_inverse=True)
    d, m = di.max() + 1, mi.max() + 1
    rng = np.random.default_rng(seed)
    wd = rng.multinomial(d, np.full(d, 1 / d), size=draws)
    wm = rng.multinomial(m, np.full(m, 1 / m), size=draws)
    return wd[:, di] * wm[:, mi]


def mde80(point, boot, effect=MDE_EFFECT):
    """Power at ``effect`` and the 80% MDE from the centred bootstrap (81a ``inference``)."""
    boot = np.asarray(boot, float)
    boot = boot[np.isfinite(boot)]
    error = boot - point
    critical = float(np.quantile(np.abs(error), .95)) if len(boot) else 0.0
    if critical <= 1e-15:
        return {"power": None, "mde80": None, "status": "DEGENERATE_EMPIRICAL_BOOTSTRAP"}
    low, high, direction = 0., critical * 10, -1 if effect < 0 else 1
    for _ in range(45):
        mid = (low + high) / 2
        if np.mean(np.abs(error + direction * mid) > critical) >= .8:
            high = mid
        else:
            low = mid
    return {"power": float(np.mean(np.abs(error + effect) > critical)), "mde80": float(high),
            "status": "DESCRIPTIVE"}


def ratio_interval(w, a, b, with_power=False):
    a, b = np.asarray(a, float), np.asarray(b, float)
    point = float(a.sum() / b.sum()) if b.sum() > 0 else math.nan
    num, den = w @ a, w @ b
    boot = np.divide(num, den, out=np.full(len(num), np.nan), where=den > 0)
    fin = boot[np.isfinite(boot)]
    out = {"estimate": point, "ci95": np.quantile(fin, [.025, .975]).tolist() if len(fin) else [None, None],
           "valid_draws": int(len(fin))}
    if with_power:
        out.update(mde80(point, boot))
    return out


# ----------------------------------------------------------------------------- table

class Table:
    """Aligned snapshot / band arrays over the scored population."""

    def __init__(self, layout, scored_dates):
        keep = layout.snaps.date.astype(str).isin(scored_dates)
        self.snaps = layout.snaps[keep].reset_index(drop=True)
        keys = set(self.snaps.row_key)
        self.bands = layout.bands[layout.bands.row_key.isin(keys)].reset_index(drop=True)
        self.n = self.snaps.n_bands.to_numpy(int)
        self.offsets = np.concatenate([[0], np.cumsum(self.n)[:-1]]).astype(int)
        self.band_snap = np.repeat(np.arange(len(self.snaps)), self.n)
        self.snap_pos = pd.Series(np.arange(len(self.snaps)), index=self.snaps.row_key.to_numpy())
        labels = layout.labels.set_index("row_key").reindex(self.snaps.row_key)
        if labels.winner.isna().any():
            raise data.LayoutError(f"{int(labels.winner.isna().sum())} scored snapshots have no label")
        winner = labels.winner.to_numpy(int)
        self.y = (self.bands.band_index.to_numpy(int) == np.repeat(winner, self.n)).astype(float)
        market = layout.market.set_index(["row_key", "band_index"]).p_market_yes
        self.p_market = market.reindex(pd.MultiIndex.from_arrays(
            [self.bands.row_key, self.bands.band_index])).to_numpy(float)
        if np.isnan(self.p_market).any():
            raise data.LayoutError(f"{int(np.isnan(self.p_market).sum())} scored bands have no market price")
        self.p_served = self.bands.p_served.to_numpy(float)
        floor = self.snaps[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(
            axis=1, skipna=True).to_numpy(float)
        fb = np.repeat(floor, self.n)
        imp = (self.bands.kind.to_numpy() != "gte") & (self.bands.high.to_numpy(float) < np.floor(fb + .5))
        self.impossible = np.where(np.isnan(fb), False, imp)
        self.has_floor = ~np.isnan(floor)
        self.local_hour = self.snaps.local_hour.to_numpy(int)
        self.markets = self.snaps.market.astype(str).to_numpy()
        cell_keys = sorted(set(zip(self.snaps.date.astype(str), self.markets)))
        self.keys = cell_keys
        index = {k: i for i, k in enumerate(cell_keys)}
        self.cell = np.array([index[k] for k in zip(self.snaps.date.astype(str), self.markets)], int)
        self.w = crossed_weights([k[0] for k in cell_keys], [k[1] for k in cell_keys]) if cell_keys else None
        self.w_date = crossed_weights([k[0] for k in cell_keys], ["all"] * len(cell_keys)) if cell_keys else None

    def candidate_vector(self, frame):
        """Rule-4 floor mask, renormalise, served fallback (HARNESS v2/v3 semantics)."""
        frame = frame[frame.row_key.isin(self.snap_pos.index)]
        if frame.duplicated(["row_key", "band_index"]).any():
            raise data.Refused("refused: duplicate (row_key, band_index) in candidate")
        pos = self.snap_pos.reindex(frame.row_key.to_numpy()).to_numpy().astype(int)
        bi = frame.band_index.to_numpy(int)
        if len(bi) and ((bi < 0) | (bi >= self.n[pos])).any():
            raise data.Refused("refused: candidate band_index out of range")
        pc = np.full(len(self.bands), np.nan)
        pc[self.offsets[pos] + bi] = frame.p.to_numpy(float)
        given = ~np.isnan(pc)
        if (pc[given] < 0).any() or not np.isfinite(pc[given]).all():
            raise data.Refused("refused: candidate probabilities must be finite and >= 0")
        n_given = np.bincount(self.band_snap, weights=given, minlength=len(self.snaps))
        if ((n_given > 0) & (n_given < self.n)).any():
            raise data.Refused("refused: some snapshots have probabilities for only some bands")
        provided = n_given == self.n
        reason = np.where(provided, "candidate", "absent").astype(object)
        no_floor = provided & ~self.has_floor
        reason[no_floor] = "missing_floor"
        pc[self.impossible & given] = 0.0
        total = np.bincount(self.band_snap, weights=np.where(given, pc, 0.0), minlength=len(self.snaps))
        zero = provided & ~no_floor & ~(total > 0)
        reason[zero] = "zero_mass_after_floor"
        use = provided & ~no_floor & ~zero
        scale = np.where(total > 0, total, 1.0)
        out = np.where(use[self.band_snap], pc / scale[self.band_snap], self.p_served)
        return out, {str(k): int(v) for k, v in zip(*np.unique(reason, return_counts=True))}

    def brier(self, p):
        return np.add.reduceat((p - self.y) ** 2, self.offsets) / self.n

    def log_score(self, p):
        total = np.add.reduceat(p, self.offsets)
        win = np.add.reduceat(p * self.y, self.offsets)
        q = np.divide(win, total, out=np.zeros(len(total)), where=total > 0)
        return -np.log(np.clip(q, LOG_EPS, 1.0))

    def cells(self, values, mask):
        idx = self.cell[mask]
        sums = np.bincount(idx, weights=values[mask], minlength=len(self.keys))
        counts = np.bincount(idx, minlength=len(self.keys))
        present = np.flatnonzero(counts)
        return present, sums[present] / counts[present]


def group_mask(local_hour, group, groups=GROUPS):
    low, high = next((lo, hi) for name, lo, hi in groups if name == group)
    return (local_hour >= low) & (local_hour <= high)


def score_rows(table, p_candidate, candidate_is_served, p_control=None, groups=GROUPS):
    scores = {"candidate": table.brier(p_candidate), "served": table.brier(table.p_served),
              "market": table.brier(table.p_market)}
    if p_control is not None:
        scores["control"] = table.brier(p_control)
    logs = {"candidate": table.log_score(p_candidate), "served": table.log_score(table.p_served),
            "market": table.log_score(table.p_market)}
    rows = []
    markets = [ALL_MARKETS] + sorted(set(table.markets))
    for market in markets:
        for group, _, _ in groups:
            mask = group_mask(table.local_hour, group, groups)
            if market != ALL_MARKETS:
                mask = mask & (table.markets == market)
            if not mask.any():
                continue
            idx, c = table.cells(scores["candidate"], mask)
            _, s = table.cells(scores["served"], mask)
            _, m = table.cells(scores["market"], mask)
            _, lc = table.cells(logs["candidate"], mask)
            _, lm = table.cells(logs["market"], mask)
            _, ls = table.cells(logs["served"], mask)
            w = table.w[:, idx]
            n_dates = len({table.keys[i][0] for i in idx})
            n_markets = len({table.keys[i][1] for i in idx})
            dims = [n_dates] if market != ALL_MARKETS else [n_dates, n_markets]
            ones = np.ones(len(idx))
            row = {
                "market": market, "block": group, "n_snapshots": int(mask.sum()), "n_market_days": int(len(idx)),
                "n_dates": n_dates, "n_markets": n_markets, "min_clusters": int(min(dims)),
                "powered": bool(min(dims) >= CLUSTER_FLOOR),
                "interval": "crossed date x market" if market == ALL_MARKETS else "date-clustered (one market)",
                "brier_model": float(c.mean()), "brier_market": float(m.mean()), "brier_served": float(s.mean()),
                "log_model": float(lc.mean()), "log_market": float(lm.mean()), "log_served": float(ls.mean()),
                "gap_ratio": ratio_interval(w, c, m),
                "ratio_interpretable": bool(m.mean() >= MARKET_BRIER_FLOOR),
                "model_minus_market": ratio_interval(w, c - m, ones, with_power=True),
                "served_ratio": ratio_interval(w, s, m),
            }
            if not candidate_is_served:
                row["model_minus_served"] = ratio_interval(w, c - s, ones, with_power=True)
            if p_control is not None:
                _, k = table.cells(scores["control"], mask)
                row["brier_control"] = float(k.mean())
                row["model_minus_control"] = ratio_interval(w, c - k, ones, with_power=True)
                row["control_minus_served"] = ratio_interval(w, k - s, ones, with_power=True)
                if market == ALL_MARKETS:
                    # Date-clustered only (secondary; EF 5 makes the crossed interval the binding one).
                    wd = table.w_date[:, idx]
                    row["model_minus_control_date_clustered"] = ratio_interval(wd, c - k, ones)
                    row["model_minus_served_date_clustered"] = ratio_interval(wd, c - s, ones)
            rows.append(row)
    return rows


# ----------------------------------------------------------------------------- outputs

def _clean(value):
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, np.generic):
        return _clean(value.item())
    return value


def canonical_bytes(payload):
    return json.dumps(_clean(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def code_sha256():
    h = hashlib.sha256()
    for module in (sys.modules[__name__], data):
        h.update(Path(module.__file__).read_bytes())
    return h.hexdigest()


def write_outputs(payload, out_dir, markdown):
    body = canonical_bytes(payload)
    sha = hashlib.sha256(body).hexdigest()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / f"{sha}.json", out / f"{sha}.md"
    json_path.write_bytes(body)
    md_path.write_text(markdown(payload, sha), encoding="utf-8", newline="\n")
    return sha, json_path, md_path


def _fmt(x, digits=4):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{digits}f}"


def _ci(entry, digits=4):
    lo, hi = (entry.get("ci95") or [None, None])
    return f"{_fmt(entry.get('estimate'), digits)} [{_fmt(lo, digits)}, {_fmt(hi, digits)}]"


def score_markdown(payload, sha):
    cand = payload["candidate"]
    lines = [f"# Development scorecard `{sha[:12]}`", "",
             "Development evidence only (dates <= 2026-09-29); not confirmation, edge or promotion evidence.", "",
             f"- Candidate: `{cand['kind']}` {cand.get('name', '')}; walk-forward: {cand.get('walk_forward')}",
             f"- Range {payload['range']['from']}..{payload['range']['to']}; scored dates "
             f"{payload['population']['n_dates']}, markets {payload['population']['n_markets']}, "
             f"snapshots {payload['population']['n_snapshots']}",
             f"- Folds: {payload['fold_scheme']['description']}",
             f"- Labels: {payload['provenance']['labels']}",
             f"- Base caveat: {BASE_CAVEAT}",
             f"- Powered = every resampled dimension has >= {CLUSTER_FLOOR} clusters.", "",
             "| market | block | dates | mkts | Brier model | Brier market | R = model/market [95%] | "
             "model - market [95%] | MDE80 | powered |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    if "control" in payload:
        ctl = payload["control"]
        lines[5:5] = [f"- Control: `{ctl['kind']}` {ctl.get('name', '')}; walk-forward: {ctl.get('walk_forward')}"]
    for r in payload["rows"]:
        ratio = _ci(r["gap_ratio"], 3) + ("" if r["ratio_interpretable"] else " (not interpretable)")
        lines.append(f"| {r['market']} | {r['block']} | {r['n_dates']} | {r['n_markets']} | "
                     f"{_fmt(r['brier_model'])} | {_fmt(r['brier_market'])} | {ratio} | "
                     f"{_ci(r['model_minus_market'])} | {_fmt(r['model_minus_market'].get('mde80'))} | "
                     f"{'yes' if r['powered'] else 'no'} |")
    deltas = [r for r in payload["rows"] if "model_minus_served" in r]
    if deltas:
        head = "| market | block | model - served [95%] | MDE80 |"
        if "control" in payload:
            head += " model - control [95%] | MDE80 | control - served [95%] |"
        lines += ["", head, "|" + " --- |" * (head.count("|") - 1)]
        for r in deltas:
            line = (f"| {r['market']} | {r['block']} | {_ci(r['model_minus_served'])} | "
                    f"{_fmt(r['model_minus_served'].get('mde80'))} |")
            if "model_minus_control" in r:
                line += (f" {_ci(r['model_minus_control'])} | {_fmt(r['model_minus_control'].get('mde80'))} | "
                         f"{_ci(r['control_minus_served'])} |")
            lines.append(line)
    return "\n".join(lines) + "\n"


def _candidate_vector(spec, layout, folds, table):
    builder = {"module": data.module_predictions, "vectors": data.vector_predictions,
               "distributions": data.distribution_predictions}[spec.kind]
    frame, meta = builder(spec, layout, folds)
    if spec.kind == "module":
        meta["walk_forward"] = "enforced_fit_per_fold"
    p, reasons = table.candidate_vector(frame)
    return p, meta, reasons


def run_score(layout_root, start, end, spec, fold_days=7, gap_days=1, min_train_dates=7, control=None,
              hourly=False):
    """``control`` (optional CandidateSpec, module/vectors/distributions): scored on the same rows with
    the same crossed weights, so ``model_minus_control`` is the paired increment of the candidate over
    it (e.g. a source added to a no-source rule)."""
    start, end = data.check_range(start, end)
    layout = data.load_layout(layout_root, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, fold_days, gap_days, min_train_dates)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    if not scored:
        raise data.Refused("refused: the fold scheme scores no date in this range")
    table = Table(layout, scored)
    cand = spec.identity()
    reasons = {}
    if spec.kind == "served":
        p, cand["walk_forward"] = table.p_served, "not_applicable_served_vector_of_record"
    elif spec.kind == "market":
        p, cand["walk_forward"] = table.p_market, "not_applicable_market_identity_control"
    else:
        p, meta, reasons = _candidate_vector(spec, layout, folds, table)
        cand.update(meta)
    p_control, control_id, control_reasons = None, None, None
    if control is not None:
        if control.kind not in ("module", "vectors", "distributions"):
            raise data.Refused("refused: a control must be a module, vectors or distributions candidate")
        control_id = control.identity()
        p_control, meta, control_reasons = _candidate_vector(control, layout, folds, table)
        control_id.update(meta)
    payload = {
        "schema": SCHEMA_VERSION, "code_sha256": code_sha256(), "evidence_class": "development",
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "fold_scheme": {"fold_days": fold_days, "gap_days": gap_days, "min_train_dates": min_train_dates,
                        "description": (f"consecutive {fold_days}-day calendar folds from {start}; fold trains on "
                                        f"layout dates <= fold_start - {gap_days + 1} d; scored when its pool has "
                                        f">= {min_train_dates} dates"),
                        "folds": [f.as_dict() for f in folds]},
        "population": {"n_dates": len(scored), "n_markets": len(set(table.markets)),
                       "n_snapshots": int(len(table.snaps)), "n_market_days": len(table.keys),
                       "first_date": scored[0], "last_date": scored[-1]},
        "candidate": cand, "candidate_coverage": reasons,
        **({"control": control_id, "control_coverage": control_reasons} if control is not None else {}),
        "provenance": {"labels": layout.label_source, "label_rule": "WU settlement labels (dates < 2026-10-23)",
                       "market": "captured p_market_yes per band (layout market file)",
                       "layout_manifest_sha256": layout.manifest_sha256, "layout_files": layout.file_sha256},
        "constants": {"draws": DRAWS, "seed": SEED, "cluster_floor": CLUSTER_FLOOR, "mde_effect": MDE_EFFECT,
                      "market_brier_floor": MARKET_BRIER_FLOOR, "log_eps": LOG_EPS},
        "base_caveat": BASE_CAVEAT,
        "rows": score_rows(table, p, spec.kind == "served", p_control,
                           GROUPS + HOURLY_GROUPS if hourly else GROUPS),
    }
    prov = {"labels": layout.label_source, "layout_manifest_sha256": layout.manifest_sha256,
            "candidate": cand.get("sha256", cand["kind"])}
    for row in payload["rows"]:
        row["provenance"] = prov
    return payload


# ----------------------------------------------------------------------------- positive control

def read_floor_fixture(path):
    raw = Path(path).read_bytes()
    body = gzip.decompress(raw) if str(path).endswith(".gz") else raw
    sha = hashlib.sha256(body).hexdigest()
    if sha != FLOOR_FIXTURE_SHA256:
        raise data.LayoutError(f"floor fixture sha256 {sha} != {FLOOR_FIXTURE_SHA256}")
    frame = pd.read_csv(io.BytesIO(body), usecols=["target_date", "market_id", "baseline_current_brier",
                                                    "hard_current_brier", "market_brier"])
    if (pd.to_datetime(frame.target_date).dt.date > data.DEV_LAST).any():
        raise data.Refused("refused: floor fixture holds a date after 2026-09-29")
    return frame, sha


def run_floor_control(path):
    """EF section 3: the 2026-07-31 serving floor moved served/market 1.6639 -> 1.4980."""
    frame, sha = read_floor_fixture(path)
    base, hard, mk = (frame[c].to_numpy(float) for c in ("baseline_current_brier", "hard_current_brier",
                                                         "market_brier"))
    dates, markets = frame.target_date.astype(str).to_numpy(), frame.market_id.astype(str).to_numpy()
    ud, um = sorted(set(dates)), sorted(set(markets))
    di = np.searchsorted(ud, dates)
    mi = np.searchsorted(um, markets)
    rng = np.random.default_rng(FLOOR_TRACKER_SEED)
    draws = []
    for _ in range(FLOOR_TRACKER_REPS):
        dc = np.bincount(rng.integers(0, len(ud), len(ud)), minlength=len(ud))
        mc = np.bincount(rng.integers(0, len(um), len(um)), minlength=len(um))
        w = dc[di] * mc[mi]
        den = float(np.dot(w, mk))
        if den > 0:
            draws.append(float(np.dot(w, hard) / den - np.dot(w, base) / den))
    tracker = {"baseline_ratio": float(base.sum() / mk.sum()), "hard_ratio": float(hard.sum() / mk.sum()),
               "ci95": [float(x) for x in np.quantile(draws, [.025, .975])]}
    tracker["delta"] = tracker["hard_ratio"] - tracker["baseline_ratio"]
    tracker["digits_match_ef3"] = (round(tracker["baseline_ratio"], 10) == FLOOR_REFERENCE["baseline"]
                                   and round(tracker["hard_ratio"], 10) == FLOOR_REFERENCE["hard"]
                                   and [round(x, 10) for x in tracker["ci95"]] == FLOOR_REFERENCE["ci95"])
    # Scorecard method: equal-weight (date, market) cells, crossed weights, seed 20260921.
    cells = frame.groupby(["target_date", "market_id"], sort=True)[
        ["baseline_current_brier", "hard_current_brier", "market_brier"]].mean()
    keys = cells.index.to_list()
    w = crossed_weights([k[0] for k in keys], [k[1] for k in keys])
    cb, ch, cm = (cells[c].to_numpy(float) for c in ("baseline_current_brier", "hard_current_brier",
                                                     "market_brier"))
    den = w @ cm
    boot = (w @ ch - w @ cb) / den
    point = float(ch.sum() / cm.sum() - cb.sum() / cm.sum())
    native = {"baseline_ratio": ratio_interval(w, cb, cm), "hard_ratio": ratio_interval(w, ch, cm),
              "delta": {"estimate": point, "ci95": np.quantile(boot, [.025, .975]).tolist()},
              "n_dates": len(ud), "n_markets": len(um), "n_market_days": len(keys),
              "powered": bool(min(len(ud), len(um)) >= CLUSTER_FLOOR)}
    sign_ok = point < 0 and native["delta"]["ci95"][1] < 0
    return {"schema": SCHEMA_VERSION, "code_sha256": code_sha256(), "control": "ef3_serving_floor_2026-07-31",
            "fixture": {"sha256": sha, "origin": "tests/fixtures/reporting/model_market_skill_tracker/"
                        "hard_floor_snapshot_deltas.csv @ ba748b76", "dates": [ud[0], ud[-1]],
                        "snapshots": int(len(frame))},
            "reference_ef3": FLOOR_REFERENCE, "tracker_method": tracker, "scorecard_method": native,
            "sign_reproduced": bool(sign_ok),
            "verdict": "PASS" if sign_ok and tracker["digits_match_ef3"] else "FAIL"}


def control_markdown(payload, sha):
    t, n = payload["tracker_method"], payload["scorecard_method"]
    return "\n".join([
        f"# Development scorecard positive control `{sha[:12]}`", "",
        "EF section 3, the 2026-07-31 serving floor (fixture dates "
        f"{payload['fixture']['dates'][0]}..{payload['fixture']['dates'][1]}, development).", "",
        f"- Tracker method (EF 3 digits): {t['baseline_ratio']:.10f} -> {t['hard_ratio']:.10f}, delta "
        f"{t['delta']:.10f} [{t['ci95'][0]:.10f}, {t['ci95'][1]:.10f}]; digits match: {t['digits_match_ef3']}",
        f"- Scorecard method (equal market-day cells, crossed W): {_ci(n['baseline_ratio'])} -> "
        f"{_ci(n['hard_ratio'])}; delta {_ci(n['delta'])}; D={n['n_dates']}, M={n['n_markets']}, "
        f"powered: {n['powered']}",
        f"- Sign reproduced: {payload['sign_reproduced']}; verdict **{payload['verdict']}**", ""])


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.reporting.scorecards.dev_scorecard",
                                     description="Development walk-forward scorecard (dates <= 2026-09-29).")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("score", help="score one candidate against market and settlement")
    s.add_argument("--layout", required=True, help="HARNESS v3 layout directory (manifest.json)")
    s.add_argument("--from", dest="start", required=True)
    s.add_argument("--to", dest="end", required=True)
    group = s.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidate", choices=("served", "market"))
    group.add_argument("--candidate-module", help="Python file with NAME, fit(train), predict(state, snaps, bands)")
    group.add_argument("--candidate-vectors", help="parquet/csv with row_key, band_index, p")
    group.add_argument("--candidate-distributions",
                       help="jsonl[.gz] rows {market, snapshot_id, distribution} (e.g. a served-vector replay)")
    s.add_argument("--trained-through", help="last date any fitted parameter of a vectors/distributions candidate saw")
    s.add_argument("--no-training", action="store_true", help="the vectors/distributions candidate has no fitted parameters")
    ctl = s.add_mutually_exclusive_group()
    ctl.add_argument("--control-module", help="paired control: Python file like --candidate-module")
    ctl.add_argument("--control-vectors", help="paired control: parquet/csv like --candidate-vectors")
    s.add_argument("--hourly", action="store_true", help="add one row per local hour and a 07-12 aggregate")
    s.add_argument("--fold-days", type=int, default=7)
    s.add_argument("--gap-days", type=int, default=1)
    s.add_argument("--min-train-dates", type=int, default=7)
    s.add_argument("--out", required=True)
    c = sub.add_parser("control-floor", help="EF section 3 positive control")
    c.add_argument("--fixture", required=True)
    c.add_argument("--out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "control-floor":
            payload = run_floor_control(args.fixture)
            sha, json_path, md_path = write_outputs(payload, args.out, control_markdown)
            print(json.dumps({"sha256": sha, "json": str(json_path), "md": str(md_path),
                              "verdict": payload["verdict"]}))
            return 0 if payload["verdict"] == "PASS" else 1
        if args.candidate:
            spec = data.CandidateSpec(args.candidate)
        elif args.candidate_module:
            spec = data.CandidateSpec("module", args.candidate_module)
        elif args.candidate_vectors:
            spec = data.CandidateSpec("vectors", args.candidate_vectors, args.trained_through, args.no_training)
        else:
            spec = data.CandidateSpec("distributions", args.candidate_distributions, args.trained_through,
                                      args.no_training)
        control = None
        if args.control_module:
            control = data.CandidateSpec("module", args.control_module)
        elif args.control_vectors:
            control = data.CandidateSpec("vectors", args.control_vectors, args.trained_through, args.no_training)
        payload = run_score(args.layout, args.start, args.end, spec, args.fold_days, args.gap_days,
                            args.min_train_dates, control, args.hourly)
        sha, json_path, md_path = write_outputs(payload, args.out, score_markdown)
        print(json.dumps({"sha256": sha, "json": str(json_path), "md": str(md_path)}))
        return 0
    except (data.Refused, data.LayoutError, data.LeakageError, data.WalkForwardError) as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
