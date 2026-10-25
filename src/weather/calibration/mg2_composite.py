r"""MG-2 composite binding: MG-1 + lane L6's own-observation stack before 13:00, L3 arm A after.

Research and shadow only. Nothing in serving, capture, release or Scheduler imports this module; the
import refuses from a production package and on the dedicated capture host (see
``_refuse_production_import``). Forward scoring is by captured-input replay at a frozen code and
coefficient hash; no capture-host serving change is made or needed.

The composite, per snapshot (``SWITCH_HOUR`` = 13, fixed by the rule):

* ``local_hour < 13``: lane L6's own-obs stack over MG-1
  (``weather.reporting.scorecards.free_source_candidates.l6_stack``: mu = v2_mean + a_h + b_h (N - v2_mean)
  at hours 07-12 where the own-obs nowcast N exists; MG-1 exactly otherwise);
* ``local_hour >= 13``: arm A, L3's OLS + hard floor on (forecast_high, high_so_far, current_temp) with
  high_so_far from lane L8's ``running_max_since_midnight``, discretised on integer native buckets;
  MG-1 where arm A has no distribution or no mass on a band the rule-4 floor allows.

Floor and calibration are MG-1's: every vector, both halves and the MG-1 comparator, goes through the
dev scorecard's rule-4 floor mask (``Table.candidate_vector``); there is no calibration stage in MG-1,
so there is none here. MG-1 itself falls back to the served vector.

Subcommands (heavy ones run through ``scripts\ops\workstation_heavy.ps1``):

* ``dev``: the composite through the dev scorecard on the dev window (selection evidence only), with the
  component controls and the per-cell deltas used to size the forward look;
* ``freeze``: the frozen coefficients file (arm A OLS per market x cutoff hour on the 2021-25 PIT corpus;
  L6 stack a_h, b_h on every dev snapshot through 2026-09-29; the L6 own-obs nowcast provenance);
* ``emit``: captured-input replay of the composite for a date range, at the frozen coefficients;
* ``check``: the outcome-blind checks MG-1 section 7 permits (coverage, PIT, replay reproduction, parser
  version); reads no label, settlement, price or market file;
* ``score``: the one forward look. Refuses any target date inside the MG-1 reserved window
  (``weather.mg1_reserved_window``) unless the rule carries a dated owner decision id.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

NAME = "mg2_composite"
SWITCH_HOUR = 13
SCHEMA = "mg2_composite/1"
RULE_BLOCK = "mg2_rule_v1"
DEV_LAST = date(2026, 9, 29)
REPLAY_TOLERANCE = 1e-12
COVERAGE_MIN = 0.90
ARM_A_FEATURES = ("forecast_high", "high_so_far", "current_temp")
ARM_A_TRAIN_CENTRE = date(2026, 9, 7)
OWNER_DECISION_ID = re.compile(r"^OD-(\d{4}-\d{2}-\d{2})-[A-Za-z0-9][A-Za-z0-9_.-]*$")
LABEL_FILES = ("labels.parquet", "market.parquet")

_PRODUCTION_PREFIXES = ("weather.operations", "weather.market", "weather.model", "weather.serving",
                        "weather.trading", "weather.capture", "weather.sources", "weather.execution",
                        "maker_core", "app")


class Mg2Refused(RuntimeError):
    """The MG-2 run cannot proceed under the rule, the reservation or the hashes."""


def _refuse_production_import():
    """Fail closed when imported from a production package, or on the capture host."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "") or ""
        if any(name == p or name.startswith(p + ".") for p in _PRODUCTION_PREFIXES):
            raise ImportError(f"weather.calibration.mg2_composite is research-only; imported from {name}")
        frame = frame.f_back
    from weather.calibration import r0_ols_floor_challenger  # noqa: F401  (its import refuses on the capture host)


_refuse_production_import()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


# ----------------------------------------------------------------------------- the rule

def read_rule(path):
    """The rule's raw sha256 and its fenced ``mg2_rule_v1`` key: value block."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    match = re.search(r"```" + RULE_BLOCK + r"\n(.*?)```", text, re.S)
    if not match:
        raise Mg2Refused(f"rule has no fenced {RULE_BLOCK} block")
    fields = {}
    for line in match.group(1).splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    for key in ("switch_hour", "d0", "n_forward_dates", "owner_decision_id", "coefficients_sha256"):
        if key not in fields:
            raise Mg2Refused(f"rule block lacks {key}")
    if int(fields["switch_hour"]) != SWITCH_HOUR:
        raise Mg2Refused(f"rule switch_hour {fields['switch_hour']} != code {SWITCH_HOUR}")
    return hashlib.sha256(raw).hexdigest(), fields


def owner_decision(fields):
    """The dated owner decision id, or None. Malformed ids refuse rather than pass."""
    value = fields.get("owner_decision_id", "NONE")
    if value in ("", "NONE"):
        return None
    match = OWNER_DECISION_ID.match(value)
    if not match:
        raise Mg2Refused(f"owner_decision_id {value!r} is not a dated id OD-YYYY-MM-DD-<slug>")
    date.fromisoformat(match.group(1))
    return value


def rule_d0(fields):
    value = fields.get("d0", "UNSET")
    return None if value == "UNSET" else date.fromisoformat(value)


def reserved_end():
    """Last MG-1 reserved date, or None when the window is open-ended (everything from the floor)."""
    from weather import mg1_reserved_window as w

    start, end = w.window()
    return start, end


def score_guard(fields, target_dates, today=None, mg1_look_receipt=None):
    """Refuse a forward look that the reservation, the rule or the one-look clause forbids.

    - every target date must be on or after the rule's D0 (D0 must be set);
    - a target date inside the MG-1 window (``weather.mg1_reserved_window``) needs a dated owner decision
      id in the rule AND a receipt of MG-1's completed look (the look is strictly after MG-1's);
    - the look needs all ``n_forward_dates`` dates.
    """
    d0 = rule_d0(fields)
    if d0 is None:
        raise Mg2Refused("rule d0 is UNSET: no forward look exists")
    days = sorted({date.fromisoformat(str(d)[:10]) for d in target_dates})
    if not days:
        raise Mg2Refused("no target dates")
    if days[0] < d0:
        raise Mg2Refused(f"target date {days[0]} is before D0 {d0}")
    start, end = reserved_end()
    inside = [d for d in days if d >= start and (end is None or d <= end)]
    decision = owner_decision(fields)
    if inside:
        if decision is None:
            raise Mg2Refused(f"{len(inside)} target dates inside the MG-1 reserved window "
                             f"({start}..{end or 'open'}); the rule carries no dated owner decision id")
        if not mg1_look_receipt or not Path(mg1_look_receipt).is_file():
            raise Mg2Refused("owner decision present, but the MG-2 look is strictly after MG-1's look and no "
                             "MG-1 look receipt was given")
        today = today or datetime.now(timezone.utc).date()
        if end is None or today <= end:
            raise Mg2Refused("the MG-1 window has not closed")
    need = int(fields["n_forward_dates"])
    if len(days) != need:
        raise Mg2Refused(f"the look needs exactly {need} forward dates, got {len(days)}")
    return {"d0": d0.isoformat(), "dates": len(days), "inside_mg1_window": len(inside),
            "owner_decision_id": decision}


# ----------------------------------------------------------------------------- composition

def floor_B(snaps):
    """B = floor(F + 0.5) with F the rule-4 floor (the scorecard's ``FLOOR_FIELDS`` max)."""
    import numpy as np
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    F = snaps[list(data.FLOOR_FIELDS)].apply(pd.to_numeric, errors="coerce").max(axis=1, skipna=True)
    F = F.to_numpy(float)
    return np.where(np.isfinite(F), np.floor(F + 0.5), -np.inf)


def distribution_band_frame(dists, bands):
    """{row_key: {bucket: p}} onto bands (``dev_scorecard_data.distribution_predictions`` mapping)."""
    import numpy as np
    import pandas as pd

    b = bands[bands.row_key.isin(set(dists))]
    probs = []
    for rk, kind, low, high in zip(b.row_key, b.kind, b.low, b.high):
        d = dists[rk]
        if kind == "lte":
            probs.append(sum(p for k, p in d.items() if k <= high))
        elif kind == "gte":
            probs.append(sum(p for k, p in d.items() if k >= low))
        else:
            probs.append(sum(p for k, p in d.items() if low <= k <= high))
    return pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                         "p": np.asarray(probs, float)})


def compose(snaps, bands, pre, post, mg1):
    """Per snapshot: ``pre`` before SWITCH_HOUR, ``post`` from it; MG-1 where the half has nothing usable.

    A ``post`` row is usable only when it puts mass on a band the rule-4 floor allows (so the scorecard
    would not drop it to served). Returns (frame, source per row_key).
    """
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    hour = dict(zip(s.row_key, s.local_hour.astype(int)))
    B = dict(zip(s.row_key, floor_B(s)))
    kind = dict(zip(zip(bands.row_key, bands.band_index.astype(int)), bands.kind))
    high = dict(zip(zip(bands.row_key, bands.band_index.astype(int)), bands.high.astype(float)))

    def usable(frame):
        if frame.empty:
            return set()
        ok = [(kind[(r, i)] == "gte") or (high[(r, i)] >= B[r]) for r, i in zip(frame.row_key, frame.band_index)]
        mass = frame.p.to_numpy(float) * np.asarray(ok, bool)
        tot = pd.Series(mass).groupby(frame.row_key.to_numpy()).sum()
        return set(tot.index[tot.to_numpy() > 0])

    pre_keys = {k for k in set(pre.row_key) if hour.get(k, 99) < SWITCH_HOUR}
    post_keys = {k for k in usable(post) if hour.get(k, -1) >= SWITCH_HOUR}
    mg1_keys = set(mg1.row_key) - pre_keys - post_keys
    parts = [pre[pre.row_key.isin(pre_keys)], post[post.row_key.isin(post_keys)], mg1[mg1.row_key.isin(mg1_keys)]]
    frame = pd.concat(parts, ignore_index=True)
    source = {}
    for k in s.row_key:
        source[k] = ("pre" if k in pre_keys else "arm_a" if k in post_keys else "mg1" if k in mg1_keys
                     else "none")
    return frame.sort_values(["row_key", "band_index"]).reset_index(drop=True), source


# ----------------------------------------------------------------------------- dev module contract

def _arm_a_dists(path):
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if date.fromisoformat(row["target_date"]) > DEV_LAST:
                    raise Mg2Refused("arm A distributions hold a row after 2026-09-29")
                out[f"{row['market']}|{row['snapshot_id']}"] = {int(float(k)): float(v)
                                                                 for k, v in row["distribution"].items()}
    return out


def fit(train):
    """Dev-scorecard module contract: the L6 stack refits per fold; arm A is a fixed historical fit."""
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    path = os.environ["MG2_ARM_A_DISTRIBUTIONS"]
    state = {"l6": l6_stack.fit(train, "n_own", NAME), "arm_a_path": path}
    state["provenance"] = {"rule": NAME, "switch_hour": SWITCH_HOUR, "l6": state["l6"]["provenance"],
                           "arm_a_sha256": sha256_file(path)}
    return state


def predict(state, snaps, bands):
    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    pre = l6_stack.predict(state["l6"], snaps, bands)
    base = mg1.predict(snaps, bands, None)
    dists = _arm_a_dists(state["arm_a_path"])
    keys = set(snaps.row_key)
    post = distribution_band_frame({k: v for k, v in dists.items() if k in keys}, bands)
    frame, _ = compose(snaps, bands, pre, post, base)
    return frame


# ----------------------------------------------------------------------------- dev sizing

DEV_GROUPS = (("00-05", 0, 5), ("06-09", 6, 9), ("07-12", 7, 12), ("10-12", 10, 12), ("00-12", 0, 12),
              ("13-16", 13, 16), ("00-16", 0, 16), ("17-23", 17, 23), ("all", 0, 23)) + tuple(
    (f"h{h:02d}", h, h) for h in range(7, 17))
Z_ALPHA, Z_POWER = 1.959963984540054, 0.8416212335729143


def forward_sizing(cell_dates, cell_delta, n_values, draws=2000, seed=20261025, margin=None):
    """Date-cluster bootstrap SE of the equal-cell mean delta at N forward dates, from dev cells.

    Draws N dates with replacement from the dev dates (each date carries its market cells), and returns,
    per N: se, mde80 (one-sided alpha 0.025), the power at the dev point estimate for superiority
    (upper bound < 0) and, with ``margin``, for non-inferiority (upper bound < margin).
    """
    import numpy as np
    from scipy.stats import norm

    cell_dates = np.asarray(cell_dates)
    delta = np.asarray(cell_delta, float)
    dates, inv = np.unique(cell_dates, return_inverse=True)
    sums = np.bincount(inv, weights=delta)
    counts = np.bincount(inv).astype(float)
    point = float(delta.mean())
    rng = np.random.default_rng(seed)
    out = {"dev_point": point, "dev_dates": int(len(dates)), "dev_cells": int(len(delta)), "per_n": {}}
    for n in n_values:
        pick = rng.integers(0, len(dates), size=(draws, int(n)))
        est = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
        se = float(est.std(ddof=1))
        row = {"se": se, "mde80": (Z_ALPHA + Z_POWER) * se,
               "power_superiority_at_dev_point": float(norm.cdf(-point / se - Z_ALPHA)) if se > 0 else None}
        if margin is not None:
            row["power_noninferiority_at_dev_point"] = float(norm.cdf((margin - point) / se - Z_ALPHA))
            row["power_noninferiority_at_zero"] = float(norm.cdf(margin / se - Z_ALPHA))
        out["per_n"][str(n)] = row
    return out


def dev_run(layout_root, arm_a, nowcasts, out, start="2026-08-01", end="2026-09-29", n_values=(30, 45, 60),
            margin=None):
    """Composite vs MG-1 on the dev window with the scorecard's own machinery (selection evidence only)."""
    import numpy as np
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    os.environ["MG2_ARM_A_DISTRIBUTIONS"] = str(arm_a)
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    l6_stack._CACHE.clear()
    s, e = data.check_range(start, end)
    layout = data.load_layout(layout_root, data.DEV_FIRST, e)
    folds = data.make_folds(layout.dates, s, e)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    table = sc.Table(layout, scored)
    here = Path(__file__).resolve()
    comp_frame, comp_meta = data.module_predictions(data.CandidateSpec("module", str(here)), layout, folds)
    p_comp, r_comp = table.candidate_vector(comp_frame)
    p_mg1, r_mg1 = table.candidate_vector(loss_atlas.mg1_frame(table))
    l6_path = Path(l6_stack.__file__).with_name("l6_own_candidate.py")
    l6_frame, _ = data.module_predictions(data.CandidateSpec("module", str(l6_path)), layout, folds)
    p_l6, _ = table.candidate_vector(l6_frame)
    a_frame, _ = data.distribution_predictions(data.CandidateSpec("distributions", str(arm_a), "2025-12-31", False),
                                               layout, folds)
    p_a, _ = table.candidate_vector(a_frame)
    from weather.calibration import r0_ols_floor_challenger as l3

    band_hour = table.local_hour[table.band_snap]
    a_used = l3.covered_mask(table, a_frame)[table.band_snap] & (band_hour >= SWITCH_HOUR)
    controls = {
        "pre_equals_l6_max_abs": float(np.abs(p_comp - p_l6)[band_hour < SWITCH_HOUR].max()),
        "post_equals_arm_a_where_arm_a_used_max_abs": float(np.abs(p_comp - p_a)[a_used].max()) if a_used.any()
        else 0.0,
        "post_equals_mg1_where_arm_a_unused_max_abs": float(np.abs(p_comp - p_mg1)[~a_used & (band_hour >= SWITCH_HOUR)].max()),
    }
    bc, bk, bm = table.brier(p_comp), table.brier(p_mg1), table.brier(table.p_market)
    groups = {}
    cells = {}
    for name, lo, hi in DEV_GROUPS:
        mask = (table.local_hour >= lo) & (table.local_hour <= hi)
        idx, c = table.cells(bc, mask)
        _, k = table.cells(bk, mask)
        _, m = table.cells(bm, mask)
        wd = table.w_date[:, idx]
        ones = np.ones(len(idx))
        groups[name] = {"n_cells": int(len(idx)),
                        "brier_minus_mg1_date_clustered": sc.ratio_interval(wd, c - k, ones),
                        "dR_vs_mg1_date_clustered": sc.ratio_interval(wd, c - k, m),
                        "brier_minus_mg1_crossed": sc.ratio_interval(table.w[:, idx], c - k, ones)}
        cells[name] = ([table.keys[i][0] for i in idx], (c - k).tolist())
    sizing = {g: forward_sizing(cells[g][0], cells[g][1], n_values, margin=margin if g == "00-16" else None)
              for g in ("00-16", "13-16", "00-12", "07-12")}
    payload = {"schema": SCHEMA, "evidence_class": "development (selection evidence only)",
               "population": {"n_dates": len(scored), "first": scored[0], "last": scored[-1],
                              "n_snapshots": int(len(table.snaps))},
               "coverage": {"composite": r_comp, "mg1": r_mg1}, "candidate_meta": comp_meta,
               "controls": controls, "groups": groups, "sizing": sizing,
               "code_sha256": sha256_file(here), "arm_a_sha256": sha256_file(arm_a),
               "nowcasts_sha256": sha256_file(nowcasts), "layout_manifest_sha256": layout.manifest_sha256}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "dev_composite.json").write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    pd.DataFrame({"date": cells["00-16"][0], "delta": cells["00-16"][1]}).to_csv(out / "cells_00_16.csv", index=False)
    pd.DataFrame({"date": cells["13-16"][0], "delta": cells["13-16"][1]}).to_csv(out / "cells_13_16.csv", index=False)
    return payload


# ----------------------------------------------------------------------------- freeze

def arm_a_fit(records):
    """L3's ``fit_fold`` OLS part, exactly: usable rows, feature vector, ``ols_fit``."""
    from weather.calibration import r0_ols_floor_challenger as l3

    usable = [r for r in records if l3._has_forecast(r)]
    xs = [l3.feature_vector(r, ARM_A_FEATURES) for r in usable]
    ys = [float(r["final_bucket"]) for r in usable]
    beta, sd = l3.ols_fit(xs, ys)
    return {"beta": [float(x) for x in beta], "ols_sd": float(sd), "n_train": len(usable)}


def arm_a_distribution(entry, record, support):
    """Arm A ``ols_floor`` distribution, exactly L3's ``challenger_distributions`` for that arm."""
    import numpy as np

    from weather.calibration import r0_ols_floor_challenger as l3

    floor = l3.floor_of(record)
    lo, hi = l3.bucket_grid(support, floor)
    x = l3.feature_vector(record, ARM_A_FEATURES)
    mu = l3.ols_predict(np.asarray(entry["beta"], float), x)
    return l3.discretised_normal(mu, entry["ols_sd"], lo, hi, floor)


def freeze(layout_root, train_manifest, markets, out):
    """The frozen coefficients: arm A per (market, cutoff hour), L6 stack per hour, nowcast provenance."""
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards.free_source_candidates import l6_stack

    arm_a = {}
    for market in markets:
        built = l3.build_r0_records(market, ARM_A_TRAIN_CENTRE, [train_manifest])
        arm_a[market] = {"support": sorted(int(b) for b in built["bucket_space"]),
                         "corpus_ids": built["corpus_ids"],
                         "hours": {str(h): arm_a_fit(r) for h, r in sorted(built["records"].items())}}
    layout = data.load_layout(layout_root, data.DEV_FIRST, DEV_LAST)
    train = {"snapshots": layout.snaps, "bands": layout.bands,
             "labels": layout.labels[["row_key", "date", "market", "winner"]]}
    data.screen_inputs(train["snapshots"], train["bands"])
    l6 = l6_stack.fit(train, "n_own", NAME)
    payload = {"schema": SCHEMA, "switch_hour": SWITCH_HOUR,
               "arm_a": {"features": list(ARM_A_FEATURES), "train_centre": ARM_A_TRAIN_CENTRE.isoformat(),
                         "train_manifest_sha256": sha256_file(train_manifest), "markets": arm_a},
               "l6_stack": {"column": "n_own", "trained_through": DEV_LAST.isoformat(),
                            "coef": {str(h): [float(a), float(b), int(n)] for h, (a, b, n) in l6["coef"].items()},
                            "nowcasts_sha256": l6["provenance"]["nowcasts_sha256"],
                            "layout_manifest_sha256": layout.manifest_sha256}}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    blob = canonical(payload)
    (out / "mg2_coefficients.json").write_bytes(blob)
    return {"coefficients_sha256": hashlib.sha256(blob).hexdigest(), "path": str(out / "mg2_coefficients.json")}


def load_coefficients(path, expected_sha):
    blob = Path(path).read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    if sha != expected_sha:
        raise Mg2Refused(f"coefficients sha {sha} != rule's {expected_sha}")
    return json.loads(blob)


# ----------------------------------------------------------------------------- emit (captured-input replay)

def read_inputs(layout_root):
    """Snapshots and bands only. Label, settlement and price files are never opened."""
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard_data as data

    root = Path(layout_root)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE)
    bands = pd.read_parquet(root / data.BANDS_FILE)
    data.screen_inputs(snaps, bands)
    return snaps, bands


def _window(snaps, first, last):
    d = snaps.date.astype(str)
    return snaps[(d >= first.isoformat()) & (d <= last.isoformat())].reset_index(drop=True)


def arm_a_records(snaps, replay_root, forecast_manifest, first, last):
    """{row_key: record} for arm A, as L3's ``dev_emit`` builds the l8 variant (cutoff <= local hour)."""
    from zoneinfo import ZoneInfo

    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.calibration.feature_model_training_inputs import PITForecastCorpusUnion
    from weather.market.market_registry import spec_for_id
    from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS

    hours = set(int(h) for h in INTRADAY_CUTOFF_HOURS)
    out, stats = {}, {}
    for market in sorted(set(snaps.market)):
        spec = spec_for_id(market)
        tz = ZoneInfo(spec.timezone)
        union = PITForecastCorpusUnion([forecast_manifest], spec.id, target_year=2027,
                                       required_cutoff_hours=INTRADAY_CUTOFF_HOURS)
        obs = {}
        for slug, target, folder in l3._event_folders(replay_root):
            if slug == market and first <= target <= last:
                for hour, rec in l3.scan_replay_observations(folder, market, target, tz, hours,
                                                             unit=spec.display_unit).items():
                    obs[(target.isoformat(), hour)] = rec
        m = stats.setdefault(market, {"emitted": 0, "local_hour_before_cutoff": 0, "no_observation": 0,
                                      "no_l8_value": 0, "outside_cutoff_hours": 0})
        for row in snaps[snaps.market == market].itertuples(index=False):
            try:
                hour = int(str(row.cutoff_hour))
            except ValueError:
                hour = None
            if hour not in hours:
                m["outside_cutoff_hours"] += 1
                continue
            if int(row.local_hour) < hour:
                m["local_hour_before_cutoff"] += 1
                continue
            key = (str(row.target_date)[:10], hour)
            rec = obs.get(key)
            if rec is None or (rec["high_so_far"] is None and rec.get("high_so_far_l8") is None):
                m["no_observation"] += 1
                continue
            if rec.get("high_so_far_l8") is None:
                m["no_l8_value"] += 1
                continue
            record = {"forecast_high": union.resolve(key[0], hour)["forecast_high"],
                      "high_so_far": rec["high_so_far_l8"], "current_temp": rec["current_temp"],
                      "cutoff_hour": hour, "local_hour": int(row.local_hour),
                      "replay_captured_at_local": rec["replay_captured_at_local"]}
            if any(record[f] is None for f in ARM_A_FEATURES):
                continue
            out[row.row_key] = record
            m["emitted"] += 1
    return out, stats


def emit(*, layout_root, replay_root, forecast_manifest, nowcasts, coefficients, rule, out, first, last,
         control=False):
    """Captured-input replay of the composite for [first, last] at the frozen coefficients.

    Forward (``control`` False): the rule's D0 must be set and ``first`` >= D0. Control mode replays dev
    dates only (<= 2026-09-29) and is how the code is checked against the dev emission.
    """
    import pandas as pd

    from weather.reporting.scorecards.free_source_candidates import l6_stack, mg1

    rule_sha, fields = read_rule(rule)
    first, last = date.fromisoformat(str(first)), date.fromisoformat(str(last))
    if control:
        if last > DEV_LAST:
            raise Mg2Refused("control replay is for dev dates <= 2026-09-29 only")
    else:
        d0 = rule_d0(fields)
        if d0 is None or first < d0:
            raise Mg2Refused("forward emission needs the rule's D0 set and first >= D0")
    coef = load_coefficients(coefficients, fields["coefficients_sha256"])
    snaps, bands = read_inputs(layout_root)
    snaps = _window(snaps, first, last)
    bands = bands[bands.row_key.isin(set(snaps.row_key))].reset_index(drop=True)
    if sha256_file(nowcasts) != coef["l6_stack"]["nowcasts_sha256"] and control:
        raise Mg2Refused("control replay must use the frozen dev nowcasts")
    os.environ["L6_NOWCASTS"] = str(nowcasts)
    l6_stack._CACHE.clear()
    state = {"column": coef["l6_stack"]["column"],
             "coef": {int(h): (a, b, n) for h, (a, b, n) in coef["l6_stack"]["coef"].items()}}
    pre = l6_stack.predict(state, snaps, bands)
    base = mg1.predict(snaps, bands, None)
    records, stats = arm_a_records(snaps, replay_root, forecast_manifest, first, last)
    market_of = dict(zip(snaps.row_key, snaps.market))
    dists = {}
    for rk, record in records.items():
        entry = coef["arm_a"]["markets"][market_of[rk]]
        dists[rk] = arm_a_distribution(entry["hours"][str(record["cutoff_hour"])], record, entry["support"])
    post = distribution_band_frame(dists, bands)
    frame, source = compose(snaps, bands, pre, post, base)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out / "mg2_vectors.parquet", index=False)
    pd.DataFrame({"row_key": list(source), "source": list(source.values())}).to_parquet(
        out / "mg2_sources.parquet", index=False)
    with open(out / "mg2_arm_a_records.jsonl", "w", encoding="utf-8") as handle:
        for rk in sorted(records):
            handle.write(json.dumps({"row_key": rk, **records[rk],
                                     "distribution": {str(k): v for k, v in dists[rk].items() if v > 0}},
                                    sort_keys=True) + "\n")
    audit = {"schema": SCHEMA, "mode": "control" if control else "forward", "first": first.isoformat(),
             "last": last.isoformat(), "rule_sha256": rule_sha, "coefficients_sha256": fields["coefficients_sha256"],
             "code_sha256": sha256_file(__file__), "nowcasts_sha256": sha256_file(nowcasts),
             "forecast_manifest_sha256": sha256_file(forecast_manifest), "arm_a_stats": stats,
             "vectors_sha256": sha256_file(out / "mg2_vectors.parquet"), "snapshots": int(len(snaps))}
    (out / "mg2_emit_audit.json").write_text(json.dumps(audit, indent=1, sort_keys=True), encoding="utf-8")
    return audit


# ----------------------------------------------------------------------------- outcome-blind checks

def outcome_blind_checks(snaps, sources, frame, replayed=None, parser_column="v2_parser_version"):
    """Coverage, PIT, replay reproduction and parser version; no label, settlement or price is read.

    ``replayed``: a second emission of the same inputs; every probability must agree to 1e-12.
    """
    import numpy as np
    import pandas as pd

    s = snaps.reset_index(drop=True)
    src = s.row_key.map(sources).fillna("none")
    h = s.local_hour.astype(int)
    in_00_16 = (h >= 0) & (h <= 16)
    coverage = float((src[in_00_16] != "none").mean()) if in_00_16.any() else 0.0
    avail = pd.to_datetime(s.v2_available_at, utc=True, errors="coerce")
    cap = pd.to_datetime(s.captured_at_utc, utc=True, errors="coerce")
    uses_v2 = src.isin(["pre", "mg1"])
    pit_v2 = int((uses_v2 & ~(avail <= cap).fillna(False)).sum())
    period = int((uses_v2 & (s.v2_period_kind.astype(str) != "maximum")).sum())
    checks = {"coverage_00_16": coverage, "coverage_pass": coverage >= COVERAGE_MIN,
              "pit_v2_after_capture": pit_v2, "pit_v2_period_not_maximum": period,
              "pit_pass": pit_v2 == 0 and period == 0, "sources": src.value_counts().to_dict(),
              "nbm_reading_snapshots": int((src != "none").sum())}
    if parser_column in s.columns:
        bad = int((uses_v2 & (pd.to_numeric(s[parser_column], errors="coerce") != 2)).sum())
        checks.update(parser_not_v2=bad, parser_pass=bad == 0, parser_status="checked")
    else:
        checks.update(parser_not_v2=None, parser_pass=False, parser_status=f"UNVERIFIED: no {parser_column} column")
    if replayed is not None:
        a = frame.sort_values(["row_key", "band_index"]).reset_index(drop=True)
        b = replayed.sort_values(["row_key", "band_index"]).reset_index(drop=True)
        same_keys = len(a) == len(b) and (a.row_key.to_numpy() == b.row_key.to_numpy()).all() and \
            (a.band_index.to_numpy() == b.band_index.to_numpy()).all()
        diff = float(np.abs(a.p.to_numpy(float) - b.p.to_numpy(float)).max()) if same_keys and len(a) else (
            0.0 if same_keys else math.inf)
        checks.update(replay_max_abs=diff, replay_pass=bool(same_keys and diff <= REPLAY_TOLERANCE))
    return checks


# ----------------------------------------------------------------------------- the look

def score(*, layout_root, vectors, rule, out, mg1_look_receipt=None, today=None):
    """The single forward look (composite minus MG-1 Brier, fixed-market date-clustered). Guarded."""
    import pandas as pd

    from weather.reporting.scorecards import dev_scorecard as sc
    from weather.reporting.scorecards import dev_scorecard_data as data
    from weather.reporting.scorecards import loss_atlas

    rule_sha, fields = read_rule(rule)
    root = Path(layout_root)
    snaps = pd.read_parquet(root / data.SNAPSHOTS_FILE, columns=["row_key", "date"])
    guard = score_guard(fields, snaps.date.astype(str).unique(), today=today, mg1_look_receipt=mg1_look_receipt)
    layout = data.Layout(snaps=pd.read_parquet(root / data.SNAPSHOTS_FILE),
                         bands=pd.read_parquet(root / data.BANDS_FILE),
                         labels=pd.read_parquet(root / data.LABELS_FILE),
                         market=pd.read_parquet(root / data.MARKET_FILE),
                         manifest_sha256=sha256_file(root / data.MANIFEST), file_sha256={},
                         label_source="layout labels")
    days = sorted(layout.snaps.date.astype(str).unique())
    table = sc.Table(layout, days)
    p_c, r_c = table.candidate_vector(pd.read_parquet(vectors))
    p_k, r_k = table.candidate_vector(loss_atlas.mg1_frame(table))
    rows = sc.score_rows(table, p_c, False, p_k, sc.GROUPS + sc.HOURLY_GROUPS)
    payload = {"schema": SCHEMA, "rule_sha256": rule_sha, "guard": guard, "coverage": {"mg2": r_c, "mg1": r_k},
               "vectors_sha256": sha256_file(vectors), "rows": rows,
               "mg1_look_receipt_sha256": sha256_file(mg1_look_receipt) if mg1_look_receipt else None}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "mg2_look.json").write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return payload


# ----------------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m weather.calibration.mg2_composite")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("dev")
    p.add_argument("--layout", required=True)
    p.add_argument("--arm-a", required=True)
    p.add_argument("--nowcasts", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n", default="30,45,60")
    p.add_argument("--margin", type=float, default=None)
    p = sub.add_parser("freeze")
    p.add_argument("--layout", required=True)
    p.add_argument("--train-manifest", required=True)
    p.add_argument("--markets", required=True)
    p.add_argument("--out", required=True)
    for name in ("emit", "check"):
        p = sub.add_parser(name)
        p.add_argument("--layout", required=True)
        p.add_argument("--replay-root", required=True)
        p.add_argument("--forecast-manifest", required=True)
        p.add_argument("--nowcasts", required=True)
        p.add_argument("--coefficients", required=True)
        p.add_argument("--rule", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--first", required=True)
        p.add_argument("--last", required=True)
        p.add_argument("--control", action="store_true")
    p = sub.add_parser("score")
    p.add_argument("--layout", required=True)
    p.add_argument("--vectors", required=True)
    p.add_argument("--rule", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--mg1-look-receipt", default=None)
    return parser


def main(argv=None):
    import pandas as pd

    args = build_parser().parse_args(argv)
    try:
        if args.command == "dev":
            result = dev_run(args.layout, args.arm_a, args.nowcasts, args.out,
                             n_values=tuple(int(x) for x in args.n.split(",")), margin=args.margin)
            result = {k: result[k] for k in ("population", "coverage", "controls", "groups", "sizing")}
        elif args.command == "freeze":
            result = freeze(args.layout, args.train_manifest, args.markets.split(","), args.out)
        elif args.command in ("emit", "check"):
            kw = dict(layout_root=args.layout, replay_root=args.replay_root, forecast_manifest=args.forecast_manifest,
                      nowcasts=args.nowcasts, coefficients=args.coefficients, rule=args.rule,
                      first=args.first, last=args.last, control=args.control)
            result = emit(out=args.out, **kw)
            if args.command == "check":
                again = emit(out=Path(args.out) / "_replay", **kw)
                snaps, _ = read_inputs(args.layout)
                snaps = _window(snaps, date.fromisoformat(args.first), date.fromisoformat(args.last))
                src = pd.read_parquet(Path(args.out) / "mg2_sources.parquet")
                result = outcome_blind_checks(
                    snaps, dict(zip(src.row_key, src.source)), pd.read_parquet(Path(args.out) / "mg2_vectors.parquet"),
                    replayed=pd.read_parquet(Path(args.out) / "_replay" / "mg2_vectors.parquet"))
                result["emit_audit_vectors_sha256"] = [r["vectors_sha256"] for r in (
                    json.loads((Path(args.out) / "mg2_emit_audit.json").read_text()), again)]
                (Path(args.out) / "mg2_checks.json").write_text(json.dumps(result, indent=1, sort_keys=True,
                                                                           default=str), encoding="utf-8")
        else:
            result = score(layout_root=args.layout, vectors=args.vectors, rule=args.rule, out=args.out,
                           mg1_look_receipt=args.mg1_look_receipt)
            result = {"guard": result["guard"], "coverage": result["coverage"]}
    except Mg2Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
