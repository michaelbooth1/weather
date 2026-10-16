"""COUNTERFACTUAL adverse-selection (toxicity) table fit for the informed-maker net screen.

Item 330 build 2. Fits a versioned table of fill hazard x signed markout (1, 5,
30 minutes and to settlement) by context (information clock, decidedness, time
to close, horizon, book imbalance and depth, print size, burst and cross-band
sweep). Every input is a **counterfactual** record: a hypothetical resting quote
minute, or a public print matched to such a quote. Nothing here is our own fill,
and the table is not the informed-fill fraction (EF §1b, §8c).

Embargo is enforced in code (``maker_core.contracts.evidence_embargo``): every
dated read refuses 2026-09-30..2026-10-15, the fit refuses any date after
2026-09-29, and a scored read refuses 2026-09-30..2026-11-13.

No domain imports, no network, explicit paths only, create-only output. Nothing
on the capture or shadow-runner import path imports this module.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from maker_core.contracts import utc_time
from maker_core.contracts.evidence_embargo import (
    EXAM_EMBARGO, FIT_LAST_DATE, SCORED_PANEL, as_date, refuse,
)
from maker_core.evidence.journal import digest
from maker_core.quoting.fill_cost import (
    DEFAULT_SPEC, DIMENSIONS, HORIZON_SECONDS, HORIZONS, LABEL, TABLE_VERSION,
    FillContext, PointInTimeError, TableFillCostProvider, TableSpec, levels,
)
from maker_core.replay.inference import cluster_intervals

BASIS = "counterfactual"
EVIDENCE_BASIS = ("COUNTERFACTUAL: hypothetical resting quotes matched to public prints; price-path "
                  "markouts of other makers' flow, not our fills and not the informed-fill fraction "
                  "(EF 1b, 8c)")
MARK_TOLERANCE = timedelta(seconds=120)
ROUND = 10


class ToxicityError(ValueError):
    """Refuse an unidentifiable input; never silently drop or impute."""


def _time(value) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    utc_time(result)
    return result


def _day(value) -> date:
    return value if isinstance(value, date) and not isinstance(value, datetime) else as_date(value)


@dataclass(frozen=True)
class QuoteMinute:
    """One counterfactual band-minute of a hypothetical resting quote (hazard denominator)."""
    condition_id: str
    market_id: str
    event_date: date
    minute_utc: datetime
    context: FillContext
    basis: str = BASIS

    def __post_init__(self):
        utc_time(self.minute_utc)
        if self.basis != BASIS:
            raise ToxicityError("non_counterfactual_record")
        if not self.condition_id or not self.market_id:
            raise ToxicityError("missing_identity")
        if self.context.at_utc > self.minute_utc:
            raise PointInTimeError("minute context after the minute start")

    def dates(self):
        return (self.event_date, self.minute_utc, *self.context.feature_times.values())


@dataclass(frozen=True)
class Mark:
    observed_at_utc: datetime
    mid_yes: float

    def __post_init__(self):
        utc_time(self.observed_at_utc)
        if isinstance(self.mid_yes, bool) or not math.isfinite(self.mid_yes) or not 0 <= self.mid_yes <= 1:
            raise ToxicityError("invalid_mark")


@dataclass(frozen=True)
class CounterfactualFill:
    """A public print that would have filled a hypothetical resting maker leg.

    ``price`` is on the maker leg's own token axis. ``context`` is the trailing
    context at the fill instant; ``minute_utc`` keys the exposure minute that
    supplies the hazard cell. Marks are price-path labels at fill + horizon.
    """
    fill_id: str
    condition_id: str
    market_id: str
    event_date: date
    minute_utc: datetime
    fill_at_utc: datetime
    maker_side: str
    price: float
    size: float
    context: FillContext
    marks: Mapping[str, Mark]
    settlement_p_yes: float | None
    settlement_observed_at_utc: datetime | None = None
    basis: str = BASIS

    def __post_init__(self):
        utc_time(self.minute_utc)
        utc_time(self.fill_at_utc)
        if self.basis != BASIS:
            raise ToxicityError("non_counterfactual_record")
        if self.maker_side not in ("YES", "NO") or self.maker_side != self.context.maker_side:
            raise ToxicityError("maker_side_mismatch")
        if not (0 < self.price < 1) or not (math.isfinite(self.size) and self.size > 0):
            raise ToxicityError("invalid_fill_price_or_size")
        if not self.minute_utc <= self.fill_at_utc < self.minute_utc + timedelta(minutes=1):
            raise ToxicityError("fill_outside_exposure_minute")
        if self.context.at_utc > self.fill_at_utc:
            raise PointInTimeError("feature timestamped after the fill")
        marks = dict(self.marks)
        for horizon, mark in marks.items():
            if horizon not in HORIZON_SECONDS:
                raise ToxicityError(f"unknown_mark_horizon:{horizon}")
            due = self.fill_at_utc + timedelta(seconds=HORIZON_SECONDS[horizon])
            if not due <= mark.observed_at_utc <= due + MARK_TOLERANCE:
                raise PointInTimeError(f"mark {horizon} not observed at fill + horizon")
        if self.settlement_p_yes is not None and (not math.isfinite(self.settlement_p_yes)
                                                  or not 0 <= self.settlement_p_yes <= 1):
            raise ToxicityError("invalid_settlement")
        if (self.settlement_p_yes is None) != (self.settlement_observed_at_utc is None):
            raise ToxicityError("settlement_needs_observation_time")
        if self.settlement_observed_at_utc is not None:
            utc_time(self.settlement_observed_at_utc)
            if self.settlement_observed_at_utc < self.fill_at_utc:
                raise PointInTimeError("settlement observed before the fill")
        object.__setattr__(self, "marks", MappingProxyType(marks))

    def dates(self):
        # The settlement observation is dated too: an event whose settlement was read on an
        # embargoed date cannot be fitted or scored.
        return (self.event_date, self.minute_utc, self.fill_at_utc, self.settlement_observed_at_utc,
                *(m.observed_at_utc for m in self.marks.values()), *self.context.feature_times.values())

    def markout(self, horizon: str) -> float | None:
        """Signed maker markout per share, probability units; positive is good for the maker."""
        if horizon == "settlement":
            value = self.settlement_p_yes
        else:
            mark = self.marks.get(horizon)
            value = None if mark is None else mark.mid_yes
        if value is None:
            return None
        token_value = value if self.maker_side == "YES" else 1 - value
        return token_value - self.price


def _refuse_records(records, purpose):
    for record in records:
        refuse(*record.dates(), purpose=purpose)


def _row_keys(context, spec):
    labels = levels(context, spec)
    return [("pooled", "all")] + [(d, labels[d]) for d in DIMENSIONS]


def _interval(cells, replicates, seed):
    if not cells:
        return {"status": "EMPTY", "date_clusters": 0, "market_clusters": 0, "cells": 0,
                "estimate": None, "interval": None, "valid_replicates": 0}
    crossed = cluster_intervals(cells, replicates=replicates, seed=seed)["date_x_market"]
    return {k: crossed[k] for k in ("status", "date_clusters", "market_clusters", "cells",
                                    "estimate", "interval", "valid_replicates")}


def _rounded(value):
    if isinstance(value, float):
        return round(value, ROUND)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def fit(minutes: Iterable[QuoteMinute], fills: Iterable[CounterfactualFill], *,
        spec: TableSpec = DEFAULT_SPEC, replicates: int = 200, seed: int = 20261016) -> dict:
    """Fit the COUNTERFACTUAL toxicity table. Refuses any record dated after 2026-09-29."""
    minutes, fills = tuple(minutes), tuple(fills)
    _refuse_records(minutes, "fit")
    _refuse_records(fills, "fit")
    if not minutes:
        raise ToxicityError("no_counterfactual_minutes")
    exposure = {}
    for m in minutes:
        key = (m.condition_id, m.minute_utc)
        if key in exposure:
            raise ToxicityError("duplicate_quote_minute")
        exposure[key] = m
    seen = set()
    for f in fills:
        if f.fill_id in seen:
            raise ToxicityError("duplicate_fill")
        seen.add(f.fill_id)
        source = exposure.get((f.condition_id, f.minute_utc))
        if source is None:
            raise ToxicityError("fill_without_exposure_minute")
        if (source.market_id, source.event_date) != (f.market_id, f.event_date):
            raise ToxicityError("fill_exposure_identity_mismatch")
        if source.context.maker_side != f.maker_side:
            raise ToxicityError("fill_exposure_side_mismatch")

    # Hazard: fills keyed by their exposure minute's context (consistent denominator).
    minute_count = defaultdict(lambda: defaultdict(int))
    fill_count = defaultdict(lambda: defaultdict(int))
    for m in minutes:
        cluster = (m.event_date.isoformat(), m.market_id)
        for key in _row_keys(m.context, spec):
            minute_count[key][cluster] += 1
    for f in fills:
        source = exposure[(f.condition_id, f.minute_utc)]
        cluster = (f.event_date.isoformat(), f.market_id)
        for key in _row_keys(source.context, spec):
            fill_count[key][cluster] += 1
    # Markouts: keyed by the trailing context at the fill instant, share-weighted.
    marks = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0])))
    for f in fills:
        cluster = (f.event_date.isoformat(), f.market_id)
        for key in _row_keys(f.context, spec):
            for h in HORIZONS:
                value = f.markout(h)
                if value is not None:
                    acc = marks[key][h][cluster]
                    acc[0] += value * f.size
                    acc[1] += f.size
                    acc[2] += 1

    rows = []
    keys = [("pooled", "all")] + sorted(k for k in minute_count.keys() | marks.keys() if k != ("pooled", "all"))
    for key in keys:
        mc, fc = minute_count.get(key, {}), fill_count.get(key, {})
        n_min, n_fill = sum(mc.values()), sum(fc.values())
        hazard_cells = {c: fc.get(c, 0) / n for c, n in mc.items() if n}
        row = {"dimension": key[0], "level": key[1], "minutes": n_min, "fills": n_fill,
               "hazard": {"per_minute": n_fill / n_min if n_min else None,
                          **_interval(hazard_cells, replicates, seed)},
               "markout": {}}
        for h in HORIZONS:
            cells = marks.get(key, {}).get(h, {})
            shares = sum(v[1] for v in cells.values())
            row["markout"][h] = {
                "fills": sum(v[2] for v in cells.values()), "shares": shares,
                "mean_prob": sum(v[0] for v in cells.values()) / shares if shares else None,
                **_interval({c: v[0] / v[1] for c, v in cells.items() if v[1]}, replicates, seed)}
        rows.append(row)

    all_dates = sorted({m.event_date for m in minutes} | {f.event_date for f in fills})
    pooled = rows[0]
    table = {
        "table_version": TABLE_VERSION,
        "label": LABEL,
        "evidence_basis": EVIDENCE_BASIS,
        "units": "hazard: counterfactual fills per quoted band-minute; markout: probability per share, "
                 "maker-signed (negative is adverse)",
        "spec": spec.as_dict(),
        "spec_digest": digest(spec.as_dict()),
        "horizons": list(HORIZONS),
        "fit_window": {"first_date": all_dates[0].isoformat(), "last_date": all_dates[-1].isoformat(),
                       "fit_last_allowed": FIT_LAST_DATE.isoformat()},
        "embargo": {"exam": [d.isoformat() for d in EXAM_EMBARGO],
                    "scored_panel": [d.isoformat() for d in SCORED_PANEL]},
        "counts": {"minutes": len(minutes), "fills": len(fills),
                   "date_clusters": pooled["hazard"]["date_clusters"],
                   "market_clusters": pooled["hazard"]["market_clusters"]},
        "inference": {"method": "crossed date x market cluster bootstrap (maker_core.replay.inference)",
                      "interval_level": 0.90, "replicates": replicates, "seed": seed,
                      "underpowered_below_clusters": 10},
        "source_digest": digest({"minutes": [_minute_payload(m) for m in minutes],
                                 "fills": [_fill_payload(f) for f in fills]}),
        "rows": rows,
    }
    rounded = _rounded(table)
    rounded["spec"] = spec.as_dict()  # Declared constants stay exact so the spec digest round-trips.
    return rounded


def table_digest(table: Mapping) -> str:
    return digest(table)


def score_table(table: Mapping, fills: Iterable[CounterfactualFill], *, horizon: str = "settlement") -> dict:
    """Scored read: envelope coverage of realized counterfactual losses.

    Refuses every record dated 2026-09-30..2026-11-13 (and the exam window).
    """
    fills = tuple(fills)
    _refuse_records(fills, "scored")
    if horizon not in HORIZONS:
        raise ToxicityError("unknown_horizon")
    provider = TableFillCostProvider(table)
    covered = total = 0
    for f in fills:
        value = f.markout(horizon)
        if value is None:
            continue
        estimate = provider.estimate(f.context)
        if not hasattr(estimate, "adverse_markout_upper"):
            continue
        total += 1
        covered += (-value) <= estimate.adverse_markout_upper
    return {"label": LABEL, "horizon": horizon, "scored_fills": total,
            "envelope_coverage": covered / total if total else None, "table_digest": table_digest(table)}


# ---- neutral JSONL records -------------------------------------------------------------

def _minute_payload(m: QuoteMinute):
    return {"kind": "minute", "condition_id": m.condition_id, "market_id": m.market_id,
            "event_date": m.event_date.isoformat(), "minute_utc": m.minute_utc.isoformat(),
            "context": m.context.as_dict(), "basis": m.basis}


def _fill_payload(f: CounterfactualFill):
    return {"kind": "fill", "fill_id": f.fill_id, "condition_id": f.condition_id, "market_id": f.market_id,
            "event_date": f.event_date.isoformat(), "minute_utc": f.minute_utc.isoformat(),
            "fill_at_utc": f.fill_at_utc.isoformat(), "maker_side": f.maker_side, "price": f.price,
            "size": f.size, "context": f.context.as_dict(),
            "marks": {h: {"observed_at_utc": m.observed_at_utc.isoformat(), "mid_yes": m.mid_yes}
                      for h, m in sorted(f.marks.items())},
            "settlement_p_yes": f.settlement_p_yes,
            "settlement_observed_at_utc": (None if f.settlement_observed_at_utc is None
                                           else f.settlement_observed_at_utc.isoformat()),
            "basis": f.basis}


def record_payload(record) -> dict:
    return _minute_payload(record) if isinstance(record, QuoteMinute) else _fill_payload(record)


def _payload_dates(payload: Mapping):
    out = [payload.get("event_date"), payload.get("minute_utc"), payload.get("fill_at_utc"),
           payload.get("settlement_observed_at_utc")]
    out += [m.get("observed_at_utc") for m in (payload.get("marks") or {}).values()]
    context = payload.get("context") or {}
    out += [context.get("at_utc"), *(context.get("feature_times") or {}).values()]
    return [v for v in out if v is not None]


def parse_record(payload: Mapping, *, purpose: str = "read"):
    """Decode one neutral record; the embargo check runs before construction."""
    refuse(*_payload_dates(payload), purpose=purpose)
    if payload.get("basis") != BASIS:
        raise ToxicityError("non_counterfactual_record")
    context = FillContext.from_mapping(payload["context"])
    if payload.get("kind") == "minute":
        return QuoteMinute(payload["condition_id"], payload["market_id"], _day(payload["event_date"]),
                           _time(payload["minute_utc"]), context, payload["basis"])
    if payload.get("kind") == "fill":
        marks = {h: Mark(_time(m["observed_at_utc"]), m["mid_yes"]) for h, m in payload["marks"].items()}
        return CounterfactualFill(payload["fill_id"], payload["condition_id"], payload["market_id"],
                                  _day(payload["event_date"]), _time(payload["minute_utc"]),
                                  _time(payload["fill_at_utc"]), payload["maker_side"], payload["price"],
                                  payload["size"], context, marks, payload["settlement_p_yes"],
                                  None if payload.get("settlement_observed_at_utc") is None
                                  else _time(payload["settlement_observed_at_utc"]), payload["basis"])
    raise ToxicityError("unknown_record_kind")


def read_records(path: Path, *, purpose: str = "read"):
    """Dated read of a neutral counterfactual JSONL file (explicit path)."""
    minutes, fills = [], []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = parse_record(json.loads(line), purpose=purpose)
            (minutes if isinstance(record, QuoteMinute) else fills).append(record)
    return tuple(minutes), tuple(fills)


def write_table(table: Mapping, path: Path) -> str:
    """Create-only canonical JSON; returns the table digest."""
    data = json.dumps(table, sort_keys=True, indent=1, allow_nan=False) + "\n"
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(data)
    return table_digest(table)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m maker_core.replay.toxicity",
                                     description="Fit the COUNTERFACTUAL toxicity table (dates <= 2026-09-29).")
    sub = parser.add_subparsers(dest="command", required=True)
    fit_cmd = sub.add_parser("fit")
    fit_cmd.add_argument("--input", type=Path, required=True)
    fit_cmd.add_argument("--output", type=Path, required=True)
    fit_cmd.add_argument("--replicates", type=int, default=200)
    fit_cmd.add_argument("--seed", type=int, default=20261016)
    args = parser.parse_args(argv)
    minutes, fills = read_records(args.input, purpose="fit")
    table = fit(minutes, fills, replicates=args.replicates, seed=args.seed)
    print(json.dumps({"label": LABEL, "table_digest": write_table(table, args.output),
                      "fit_window": table["fit_window"], "counts": table["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
