"""Reported-only NWP-availability breakdown of the frozen T+1 fair-value read.

T+1 pre-registration Amendment 3 (2026-10-02). Reads the frozen scorer's
unchanged ``report.json`` and writes ``buckets.json`` beside it. It never
re-scores, re-selects or re-labels: every number comes from ``selected_hours[]``.
No bucket is primary, none is compared against a threshold, and no difference
between buckets is a finding or a selection rule.

The Brier aggregation and the crossed date x market bootstrap are vendored
verbatim from ``weather.market.maker_fair_value_statistics`` (110b, frozen) so
this post-processor runs without the scorer; a test pins the equivalence
wherever that module is importable.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np


PREREGISTRATION = "docs/research/t1-fair-value-preregistration-2026-09-25.md"
AMENDMENT = "Amendment 3 — 2026-10-02 (before scoring, owner decision; reported-only breakdown)"
REPLICATES = 10_000
SEED = 110
LEADS = (1, 2)
# Membership is the frozen pooled descriptive table's; tied-read strata are not broken down.
MEMBER_SOURCES = ("nbp", "fallback")
# Fixed engineering availability anchors (UTC), not measured latency.
ANCHORS = {
    "gfs": (time(3, 30), time(9, 30), time(15, 30), time(21, 30)),
    "ecmwf": (time(1, 40), time(7, 40), time(13, 40), time(19, 40)),
}
CLOCKS = ("gfs", "ecmwf", "latest_of_either")
BUCKETS = (("[0,60)", 0, 60), ("[60,120)", 60, 120), ("[120,240)", 120, 240), ("[240,360]", 240, 360))
OUTPUT_NAME = "buckets.json"
INTERPRETATION_CONSTRAINT = (
    "Interpretation constraint, binding on the report: the plugin fair value updates "
    "only on NBM cycles (01/07/13/19Z, available by the frozen +1 h assumption at "
    "02:00, 08:00, 14:00 and 20:00 UTC), never on GFS or ECMWF. Disagreement between "
    "fair value and mid therefore changes at NBM times **by construction**, and the "
    "ECMWF anchors sit 20 minutes before NBM availability, so the ECMWF and \"latest of "
    "either\" breakdowns cannot separate an ECMWF effect from an NBM step. A bucket "
    "pattern here is not evidence about NWP-driven market moves; the market-only "
    "question is pre-registered separately in "
    "`docs/research/t12-nwp-timing-market-only-preregistration-2026-10-02.md` "
    "(branch `codex/t12-nwp-timing-prereg-20261002`)."
)
LIMITATIONS = [
    "Reported only: no bucket is primary, none is compared against a threshold, and no "
    "difference between buckets is a finding or a selection rule for pull windows.",
    "Anchors are fixed engineering assumptions (GFS cycle + 210 min; ECMWF open data cycle + "
    "7 h 40 min, 06Z/18Z by assumption), not measured latency; Open-Meteo ingestion lag is excluded.",
    "Computed from the frozen scorer's unchanged report.json; the frozen tables are untouched.",
    "UNDERPOWERED when either cluster dimension has fewer than ten unique clusters, per cell.",
    "An interval crossing zero is not evidence of an improvement.",
]
_ROW_FIELDS = ("captured_at", "lead", "source", "target_date", "market_id", "bands")
_BAND_FIELDS = ("probability", "mid", "observed_yes")


class NotComputed(ValueError):
    """The report lacks a field the breakdown needs."""


def minutes_since(captured_at: datetime, anchors) -> float:
    """Minutes from the latest daily UTC anchor at or before ``captured_at``."""
    at = captured_at.astimezone(timezone.utc)
    instants = (datetime.combine(at.date() + timedelta(days=offset), anchor, timezone.utc)
                for offset in (-1, 0) for anchor in anchors)
    return (at - max(t for t in instants if t <= at)).total_seconds() / 60


def bucket(minutes: float) -> str:
    for label, lower, upper in BUCKETS:
        if lower <= minutes < upper or (upper == 360 and minutes == 360):
            return label
    raise NotComputed("minutes_outside_buckets")


def assign(captured_at: datetime) -> dict:
    gfs, ecmwf = (minutes_since(captured_at, ANCHORS[k]) for k in ("gfs", "ecmwf"))
    minutes = dict(gfs=gfs, ecmwf=ecmwf, latest_of_either=min(gfs, ecmwf))
    return dict(minutes_since=minutes, buckets={k: bucket(v) for k, v in minutes.items()})


# --- Vendored frozen 110b estimands (maker_fair_value_statistics), Brier only. ---

def cluster_weights(cells):
    dates = sorted({d for d, _ in cells})
    markets = sorted({m for _, m in cells})
    rng = np.random.default_rng(SEED)
    date_draws = rng.integers(len(dates), size=(REPLICATES, len(dates)))
    market_draws = rng.integers(len(markets), size=(REPLICATES, len(markets)))
    dw = np.stack([(date_draws == dates.index(d)).sum(axis=1) for d, _ in cells], axis=1)
    mw = np.stack([(market_draws == markets.index(m)).sum(axis=1) for _, m in cells], axis=1)
    return dw * mw, dw


def _interval(values):
    valid = values[np.isfinite(values)]
    return {"interval_90": np.quantile(valid, [.05, .95]).tolist() if len(valid) else None,
            "valid_replicates": len(valid), "undefined_replicates": REPLICATES - len(valid)}


def _estimate(numerator, denominator, weights):
    total = float(np.sum(denominator))
    result = {"estimate": float(np.sum(numerator) / total) if total else None}
    for name, w in zip(("crossed", "date_only"), weights):
        n, d = w @ numerator, w @ denominator
        draws = np.divide(n, d, out=np.full(REPLICATES, np.nan), where=d > 0)
        result[name] = _interval(draws)
    return result


def summarize_brier(rows):
    """Frozen paired Brier: bands, then hours within market-day, then market-days equally."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["target_date"], row["market_id"])].append(row)
    cells = sorted(grouped)
    ndate, nmarket = len({d for d, _ in cells}), len({m for _, m in cells})
    result = dict(status="UNDERPOWERED" if min(ndate, nmarket) < 10 else "DESCRIPTIVE",
                  date_clusters=ndate, market_clusters=nmarket, market_days=len(cells),
                  hours=len(rows), band_hours=sum(len(r["bands"]) for r in rows))
    if not cells:
        result.update(brier=None, market_day_scores=[])
        return result
    weights = cluster_weights(cells)
    losses, day_scores = [], []
    for target, market in cells:
        hours = grouped[(target, market)]
        loss = np.mean([[np.mean([(b[key] - b["observed_yes"]) ** 2 for b in h["bands"]])
                         for key in ("probability", "mid")] for h in hours], axis=0)
        losses.append([*loss, loss[0] - loss[1]])
        day_scores.append(dict(target_date=target, market_id=market, hours=len(hours),
                               provider_brier=float(loss[0]), mid_brier=float(loss[1]),
                               paired_difference=float(loss[0] - loss[1])))
    losses = np.asarray(losses)
    result["market_day_scores"] = day_scores
    result["brier"] = {name: _estimate(losses[:, i], np.ones(len(cells)), weights)
                       for i, name in enumerate(("provider", "mid", "provider_minus_mid"))}
    return result


# --- Report reading and breakdown. ---

def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _captured_at(text):
    try:
        at = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        raise NotComputed("invalid_captured_at") from None
    if at.tzinfo is None:
        raise NotComputed("naive_captured_at")
    return at


def member_rows(report):
    """Validated pooled-membership rows with their bucket assignment."""
    if not isinstance(report, dict):
        raise NotComputed("report_not_a_json_object")
    if not isinstance(report.get("selected_hours"), list):
        raise NotComputed("missing_selected_hours")
    members = []
    for row in report["selected_hours"]:
        if not isinstance(row, dict) or any(k not in row for k in _ROW_FIELDS):
            raise NotComputed("missing_selected_hour_fields")
        if row["source"] not in MEMBER_SOURCES:
            continue
        if row["lead"] not in LEADS:
            raise NotComputed("lead_out_of_scope")
        bands = row["bands"]
        if (not isinstance(bands, list) or not bands
                or any(not isinstance(b, dict) or not all(_number(b.get(k)) for k in _BAND_FIELDS)
                       for b in bands)):
            raise NotComputed("missing_band_fields")
        members.append(dict(row, assignment=assign(_captured_at(row["captured_at"]))))
    return members


def breakdown(report) -> dict:
    """The Amendment 3 result for a parsed report; NOT_COMPUTED when fields are absent."""
    base = dict(preregistration=PREREGISTRATION, amendment=AMENDMENT,
                interpretation_constraint=INTERPRETATION_CONSTRAINT, limitations=LIMITATIONS)
    try:
        rows = member_rows(report)
    except NotComputed as exc:
        return dict(status="NOT_COMPUTED", reason=str(exc), **base)
    anchors = {k: [a.strftime("%H:%M") for a in v] for k, v in ANCHORS.items()}
    cells = {}
    for lead in LEADS:
        for clock in CLOCKS:
            for label, _, _ in BUCKETS:
                cell = [r for r in rows if r["lead"] == lead and r["assignment"]["buckets"][clock] == label]
                cells[f"lead_{lead}/{clock}/{label}"] = dict(lead=lead, clock=clock, bucket=label,
                                                             **summarize_brier(cell))
    assignments = [dict(event_id=r.get("event_id"), market_id=r["market_id"], target_date=r["target_date"],
                        lead=r["lead"], source=r["source"], captured_at=r["captured_at"], **r["assignment"])
                   for r in rows]
    return dict(status="REPORTED_ONLY", member_sources=list(MEMBER_SOURCES), anchors_utc=anchors,
                buckets_minutes=[label for label, _, _ in BUCKETS], bootstrap_replicates=REPLICATES,
                bootstrap_seed=SEED, cells=cells, assignments=assignments, **base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True,
                        help="the frozen scorer's report.json; buckets.json is created beside it")
    args = parser.parse_args(argv)
    output = args.report.parent / OUTPUT_NAME
    try:
        raw = args.report.read_bytes()
        if output.exists():
            raise ValueError("buckets_json_exists")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"nwp bucket breakdown refused: {type(exc).__name__}: {exc}\n")
    try:
        report = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        report = None
    result = breakdown(report)
    result["report_sha256"] = hashlib.sha256(raw).hexdigest()
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
