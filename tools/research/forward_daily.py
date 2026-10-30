"""Lane L13: local-day maximum and completeness for ONE forecast series (one model run, product and member).

``forward_local_day.daily_max`` sums window hours over every row it is given and calls a day complete only when the
inside windows cover it. Neither works for a 6-hour maximum: when local midnight is not on a 6-hour UTC boundary
(Toronto in EDT: 04Z), a run's windows wholly inside a day cover only 18 of its 24 (or 25) hours, and rows from
several runs or members would inflate the sum. This module replaces it for daily summaries; ``forward_local_day``
keeps the bucketing rules and stays byte-identical, because the live ECCC recorder pins its git blob.

Rules (``local_day_summary``):

* The rows must come from one series: a single ``run_utc`` and a single ``member`` (``None`` for a deterministic
  model). Mixed rows raise ``ValueError``; group first (``group_series``).
* A window ``(start, end]`` wholly inside local day ``D`` is an inside window; one that crosses a local midnight is an
  edge window for both days. ``max`` uses inside windows only, so it is a lower bound of the day's maximum.
* ``covered_hours`` is the union of the inside windows (never a sum); ``spanned_hours`` is the union of inside and
  edge windows clipped to the day.
* ``status`` for window rows:
  - ``exact``: the inside windows cover the whole day, so ``max`` is the day's maximum;
  - ``bounded``: inside and edge windows together cover the whole day, so the day's maximum lies in
    ``[max, max_upper]`` with ``max_upper = max(max, edge_max)``. This is what a complete 6-hour Tmax day is;
  - ``partial``: some hour of the day is covered by no window of this series.
* ``status`` for instantaneous rows (2 m temperature at a valid time): ``hourly`` when every local hour of the day
  starts with a value (a sampled maximum, never a true maximum), otherwise ``partial``.
* A day mixing window and instantaneous rows raises ``ValueError``.

Research / shadow only; nothing outside lane L13 tools and tests imports it.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo

try:
    from .forward_local_day import _utc, local_day_bounds, window_local_day
except ImportError:  # run as a script next to forward_local_day.py
    from forward_local_day import _utc, local_day_bounds, window_local_day

HOUR = dt.timedelta(hours=1)


def _union_hours(intervals, lo, hi):
    """Length in hours of the union of ``intervals`` clipped to ``[lo, hi]``."""
    total, cur_s, cur_e = dt.timedelta(0), None, None
    for s, e in sorted((max(s, lo), min(e, hi)) for s, e in intervals):
        if e <= s:
            continue
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total.total_seconds() / 3600.0


def group_series(rows, keys=("model", "product", "run_utc", "market", "member")):
    """Split rows into series by ``keys`` (missing keys count as ``None``)."""
    out = defaultdict(list)
    for r in rows:
        out[tuple(r.get(k) for k in keys)].append(r)
    return dict(out)


def local_day_summary(rows, tz):
    """Per local day of one series: inside maximum, coverage, edge windows and ``status`` (see module rules)."""
    z = ZoneInfo(tz) if isinstance(tz, str) else tz
    rows = list(rows)
    runs = {r.get("run_utc") for r in rows}
    members = {r.get("member") for r in rows}
    if len(runs) > 1 or len(members) > 1:
        raise ValueError(f"mixed series: runs {sorted(map(str, runs))}, members {sorted(map(str, members))}")
    days = defaultdict(lambda: {"max": None, "inside": [], "edges": [], "edge_max": None, "instants": set(),
                                "kinds": set()})
    for r in rows:
        s, e = _utc(r["start_utc"]), _utc(r["end_utc"])
        v = float(r["value"])
        day, sl, el = window_local_day(s, e, z)
        if day is None:
            for d in {sl.date(), el.date()}:
                b = days[d]
                b["kinds"].add("window")
                b["edges"].append((s, e))
                b["edge_max"] = v if b["edge_max"] is None else max(b["edge_max"], v)
            continue
        b = days[day]
        b["max"] = v if b["max"] is None else max(b["max"], v)
        if s == e:
            b["kinds"].add("instant")
            b["instants"].add(s)
        else:
            b["kinds"].add("window")
            b["inside"].append((s, e))
    out = {}
    for d, b in sorted(days.items()):
        if len(b["kinds"]) > 1:
            raise ValueError(f"{d}: window and instantaneous rows mixed")
        start, end = local_day_bounds(d, z)
        day_hours = (end - start).total_seconds() / 3600.0
        covered = _union_hours(b["inside"], start, end)
        spanned = _union_hours(b["inside"] + b["edges"], start, end)
        if "instant" in b["kinds"]:
            hours_missing = sum(1 for k in range(round(day_hours)) if start + k * HOUR not in b["instants"])
            status = "hourly" if hours_missing == 0 else "partial"
            upper = None
        else:
            status = "exact" if covered == day_hours else "bounded" if spanned == day_hours else "partial"
            upper = None if status == "partial" else max(x for x in (b["max"], b["edge_max"]) if x is not None)
        out[d.isoformat()] = {"max": b["max"], "max_upper": upper, "status": status, "day_hours": day_hours,
                              "covered_hours": covered, "spanned_hours": spanned, "instants": len(b["instants"]),
                              "edge_windows": len(b["edges"]), "edge_max": b["edge_max"],
                              "day_start_utc": start.isoformat(), "day_end_utc": end.isoformat()}
    return out
