"""Offline, synthetic-tested fill-toxicity desk study; never places orders.

Frozen authority: mission 89a and Clarifications 1-12 at 0df126491. A dry run
stats exact named inputs and reads no tape content. Normal runs stream one
event-date through a disk-backed sort, writing only beneath --output-dir.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sqlite3
import sys
import tempfile
import tracemalloc
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from weather.backtesting.settlement_ledger import clean_temperature_label, current_ledger_label
from weather.market import execution_tape_markout as base
from weather.market import fill_toxicity_inputs as inputs
from weather.market import fill_toxicity_reward_inputs as reward_inputs
from weather.market import fill_toxicity_statistics as stats
from weather.market.fill_toxicity_panels import MinutePanels
from weather.market.fill_toxicity_model import (
    DISTANCES, FILL_RULES, WINDOW_SETS, StudyError, membership, simulate,
)
from weather.market.market_registry import REGISTRY
from weather.paths import data_path


PANELS = {"A": (date(2026, 8, 15), date(2026, 9, 23)),
          "B": (date(2026, 9, 25), date(2026, 10, 8))}
FROZEN_REF = "0df1264910a36b75d01474f63f86b71920e22541"
REPORT_NAME = "fill_toxicity_desk_study"
EXTRA_GROUPS = ("PLACEBO", "E2_DETECTED", "E123_DETECTED")
GROUPS = ("TOTAL", *WINDOW_SETS, *EXTRA_GROUPS, "OUTSIDE")


def _existing(folder, names):
    return [folder / name for name in names if (folder / name).is_file()]


def panel_metadata(panel):
    if panel not in PANELS:
        raise StudyError("panel must be A or B")
    start, end = PANELS[panel]
    return {"panel": panel, "panel_start": start.isoformat(), "panel_end": end.isoformat()}


def require_closed_panel(panel, now=None):
    """B's complete frozen window must close, even for a bounded subset run."""
    panel_metadata(panel)
    if panel == "B":
        now = now or datetime.now(timezone.utc)
        next_day = PANELS[panel][1] + timedelta(days=1)
        if any(datetime.combine(next_day, time(), spec.tz).timestamp() > now.timestamp()
               for spec in REGISTRY.values()):
            raise StudyError("panel B cannot be scored before every frozen panel-B date is closed")


def input_plan(snapshots_root, settlement_root, *, max_dates=None, supplements=None, now=None,
               maker_evidence_root=None, panel="A"):
    """Generate frozen events; list event inputs and sealed reward-hour metadata."""
    metadata = panel_metadata(panel)
    first, last = PANELS[panel]
    days = (last - first).days + 1
    max_dates = days if max_dates is None else max_dates
    if not 1 <= max_dates <= days:
        raise StudyError("max-dates must be within the frozen date range")
    now = now or datetime.now(timezone.utc)
    supplements = supplements or {}
    maker_evidence_root = (Path(maker_evidence_root) if maker_evidence_root is not None
                           else Path(snapshots_root).parent / "maker_evidence")
    plan = []
    for offset in range(max_dates):
        day = first + timedelta(days=offset)
        for market, spec in sorted(REGISTRY.items()):
            slug = f"{spec.slug_prefix}-{day.strftime('%B').lower()}-{day.day}-{day.year}"
            folder = Path(snapshots_root) / slug
            start = datetime.combine(day, time(), spec.tz).timestamp()
            end = datetime.combine(day + timedelta(days=1), time(), spec.tz).timestamp()
            # B may be planned before it closes; scoring has a separate full-window gate.
            if panel == "A" and end > now.timestamp():
                continue
            extra = supplements.get(slug, {})
            book_candidates = _existing(folder, ("order_books.jsonl", "order_books.jsonl.gz"))
            summary_candidates = _existing(folder, ("order_books_summary.csv", "order_books_summary.csv.gz"))
            tape = folder / "execution_tape"
            children = sorted(tape.iterdir()) if tape.is_dir() else []
            trades = [p for p in children if base.TRADE_PART_RE.fullmatch(p.name)]
            gaps = [p for p in children if p.name.startswith("gaps-") and p.suffix == ".jsonl"]
            weather = _existing(folder, ("replay_inputs.jsonl", "replay_inputs.jsonl.gz"))
            # Never read both a projection and its compressed canonical equivalent.
            weather = weather[:1]
            rewards = _existing(folder, ("reward_records.jsonl", "rewards.jsonl", "snapshots.jsonl"))
            entry = {**metadata, "date": day.isoformat(), "market": market, "slug": slug,
                     "start": start, "end": end, "folder": str(folder),
                     "book": str(book_candidates[0]) if book_candidates else None,
                     "summary": str(summary_candidates[0]) if summary_candidates else None,
                     "trades": list(map(str, trades)), "gaps": list(map(str, gaps)),
                     "status": str(tape / "status.json"), "weather": list(map(str, weather)),
                     "rewards": list(map(str, rewards)),
                     "maker_rewards": reward_inputs.plan_rewards(maker_evidence_root, start, end),
                     "triggers": [str(Path(snapshots_root) / "observation_triggers.jsonl")]
                         if (Path(snapshots_root) / "observation_triggers.jsonl").is_file() else [],
                     "ledger": str(Path(settlement_root) / market / "ledger.jsonl"), "iem": [],
                     "reconstruct_e2": bool(extra.get("reconstruct_e2", False))}
            for name in ("weather", "rewards", "triggers", "gaps", "iem"):
                entry[name].extend(map(str, extra.get(name, [])))
            if extra.get("ledger"):
                entry["ledger"] = str(extra["ledger"])
            plan.append(entry)
    return plan


def inventory(plan):
    found = {}
    for event in plan:
        for name in ("book", "summary", "status", "ledger", "trades", "gaps", "weather", "rewards", "maker_rewards", "triggers", "iem"):
            values = event.get(name) if isinstance(event.get(name), list) else [event.get(name)]
            for value in values:
                if value:
                    path = Path(value).resolve()
                    found[str(path)] = path.stat().st_size if path.is_file() else None
                    if name == "maker_rewards":
                        seal = reward_inputs.manifest_path(path.parent)
                        if seal:
                            found[str(seal.resolve())] = seal.stat().st_size
    return [{"path": path, "bytes": size} for path, size in sorted(found.items())]


def read_settlement(path, slug):
    selected = None
    if Path(path).is_file():
        for row in inputs.json_lines(path, settlement=True):
            if row.get("event_slug") == slug:
                selected = current_ledger_label([selected, row] if selected else [row], slug)
    return selected


def settlement_mark(label, band):
    if label is None:
        return None, "missing_settlement_row"
    winning = label.get("polymarket_winning_band")
    if winning not in (None, ""):
        return float(clean_temperature_label(winning) == clean_temperature_label(band["label"])), "polymarket_winning_band"
    value = base.token_settlement_payoff(
        {"bin_kind": band["kind"], "bin_value": band["lo"], "bin_value_hi": band["hi"], "outcome": "Yes"},
        label.get("settlement_bucket"))
    return value, "WU_FALLBACK" if value is not None else "missing_settlement_value"


def panel_terms(db, event, windows, *, defect_minutes=()):
    bands, missing_counts = [], defaultdict(int)
    excluded_counts, defect_counts = defaultdict(int), defaultdict(int)
    raw_bands = list(db.execute("""SELECT t.condition_id,b.token,b.no_token,b.label,b.kind,b.lo,b.hi
        FROM (SELECT DISTINCT condition_id FROM terms WHERE at>=? AND at<?) t
        LEFT JOIN bands b ON b.condition_id=t.condition_id ORDER BY t.condition_id""", (event["start"], event["end"])))
    if len(raw_bands) > 256:
        raise StudyError("event exceeds the 256-band memory budget; no partial result")
    for row in raw_bands:
        condition = row[0]
        present = db.execute("SELECT 1 FROM terms WHERE condition_id=? AND at>=? AND at<? LIMIT 1",
                             (condition, event["start"], event["end"])).fetchone()
        if not present:
            continue
        if not row[1]:
            raise StudyError("panel condition lacks a captured YES book identity")
        band = dict(zip(("condition", "token", "no_token", "label", "kind", "lo", "hi"), row))
        band["terms"] = {}
        for minute in range(int(event["start"]), int(event["end"]), 60):
            terms = inputs.terms_at(db, condition, minute)
            damaged = minute in defect_minutes
            band["terms"][minute] = None if damaged else terms
            for target, excluded in ((excluded_counts, damaged or terms is None), (defect_counts, damaged)):
                if excluded:
                    target["TOTAL"] += 1
                    for group in membership(windows, minute, condition):
                        target[group] += 1
            if terms is None:
                missing_counts["TOTAL"] += 1
                for group in membership(windows, minute, condition):
                    missing_counts[group] += 1
        bands.append(band)
    expected = len(bands) * int((event["end"] - event["start"]) / 60)
    return bands, {"expected_band_minutes": expected, "missing_term_band_minutes": dict(missing_counts),
                   "capture_defect_band_minutes": dict(defect_counts),
                   "excluded_band_minutes": dict(excluded_counts),
                   "excluded_band_minute_fraction": excluded_counts["TOTAL"] / expected if expected else None,
                   "missing_term_fraction": missing_counts["TOTAL"] / expected if expected else None}


def _write_audit(handle, row, *, panel="A"):
    handle.write(json.dumps({**row, **panel_metadata(panel)}, sort_keys=True,
                           allow_nan=False, default=str) + "\n")


def process_band(db, event, band, windows, label, audit):
    cells = defaultdict(stats.zero)
    diagnostics = {}
    payoff, settlement_source = settlement_mark(label, band)
    condition, token = band["condition"], band["token"]
    horizons = dict(base.HORIZON_SECONDS)
    if payoff is not None:
        horizons["settlement"] = None
    for distance in DISTANCES:
        for rule in FILL_RULES:
            scenario = f"d{distance:g}_{rule}"

            def cell(population, adjusted, horizon, group):
                return cells[(scenario, population, "adjusted" if adjusted else "book_mid", horizon, group)]

            def record(row):
                _write_audit(audit, {"event": event["slug"], "date": event["date"], "market": event["market"],
                    "band": condition, "scenario": scenario, **row}, panel=event.get("panel", "A"))
                if row["type"].startswith("removed_"):
                    for field in ("leg_minutes_by_group", "fills_by_group", "quote_minutes_by_group"):
                        for group, count in row.get(field, {}).items():
                            key = "/".join((scenario, row["midpoint"], row["horizon"], field, group))
                            diagnostics[key] = diagnostics.get(key, 0) + count

            def emit(population, adjusted, horizon, group, values):
                stats.add(cell(population, adjusted, horizon, group), values)

            panel = MinutePanels(midpoint=lambda at, adjusted: inputs.midpoint(db, token, at, adjusted=adjusted),
                                 payoff=payoff, end=event["end"], emit=emit, audit=record)

            def exposure(a, b, share_minutes, many, single, groups, population, remaining):
                _write_audit(audit, {"event": event["slug"], "band": condition, "scenario": scenario,
                    "type": "exposure", "start": a, "end": b, "share_minutes": share_minutes,
                    "reward_many": many, "reward_single": single, "groups": sorted(groups), "population": population,
                    "remaining_sizes": remaining}, panel=event.get("panel", "A"))
                for group in {"TOTAL", *groups}:
                    target = cell(population, False, "R", group)
                    target["exposure"] += share_minutes
                    target["reward_many"] += many
                    target["reward_single"] += single
                panel.exposure(a, b, share_minutes, many, single, groups, population, remaining)

            def fill(at, shares, price, side, groups, population):
                marks = panel.fill(at, shares, price, side, groups, population)
                for group in {"TOTAL", *groups}:
                    target = cell(population, False, "R", group)
                    target["filled_shares"] += shares
                    target["fills"] += 1
                _write_audit(audit, {"event": event["slug"], "band": condition, "scenario": scenario,
                    "type": "fill", "at": at, "shares": shares, "price": price, "side": side,
                    "groups": sorted(groups), "population": population, "markouts": marks,
                    "settlement_source": settlement_source}, panel=event.get("panel", "A"))

            def quote_record(at, values):
                _write_audit(audit, {"event": event["slug"], "band": condition, "scenario": scenario,
                                    "type": "quote", "at": at, **values}, panel=event.get("panel", "A"))

            simulate(inputs.iter_books(db, condition), inputs.iter_prints(db, token, band["no_token"]),
                     start=event["start"], end=event["end"], terms_at=band["terms"].get,
                     windows=windows, band=condition, distance=distance, rule=rule,
                     exposure=exposure, fill=fill, diagnostics=diagnostics, quote_record=quote_record)
            panel.flush()
            for population in ("midrange", "outside_midrange"):
                for group in GROUPS:
                    cell(population, False, "R", group)["band_days"] = 1
                for adjusted in (False, True):
                    for horizon in horizons:
                        for group in GROUPS:
                            # Every eligible panel band-day contributes to the dollars/band-day denominator,
                            # including band-days with zero fills or zero event-window exposure.
                            cell(population, adjusted, horizon, group)["band_days"] = 1
    return cells, {**diagnostics, "settlement_source": settlement_source}


def public_markouts(db, event, band, windows, label, public, *, defect_minutes=()):
    payoff, _ = settlement_mark(label, band)
    for token, complement in ((band["token"], False), (band["no_token"], True)):
        if not token:
            continue
        for at, price, shares, side in db.execute("SELECT at,price,size,side FROM trades WHERE token=? ORDER BY at,seq", (token,)):
            if math.floor(at / 60) * 60 in defect_minutes:
                continue
            reference = inputs.midpoint(db, token, at, before=True)
            side = side or base.maker_side_from_quote_rule(price, reference)
            if side is None:
                continue
            for horizon in base.HORIZONS:
                mark = payoff if horizon == "settlement" else inputs.midpoint(db, token, at + base.HORIZON_SECONDS[horizon])
                if mark is None:
                    continue
                if complement and horizon == "settlement":
                    mark = 1 - mark
                value = base.maker_markout(side, price, mark)
                for group in {"TOTAL", *membership(windows, at, band["condition"])}:
                    key = (horizon, group)
                    public.setdefault(key, base.CellAccumulator()).add(event["date"], shares, value, 0.0)


def _latency(db, event, band, windows, latency, counters):
    for window in windows:
        if window.kind not in ("E2", "E3") or window.band not in (None, band["condition"]):
            continue
        if window.detected is None:
            counters["latency_missing_detection"] += 1
            continue
        marks = [inputs.midpoint(db, band["token"], at, before=before) for at, before in
                 ((window.observed, True), (window.detected, True), (window.observed + 1800, False))]
        if any(value is None for value in marks):
            counters["latency_missing_midpoint"] += 1
            continue
        observed, detected, later = marks
        if abs(later - observed) < .01:
            counters["latency_move_under_1_cent"] += 1
            continue
        latency[window.kind][event["date"]].append((detected - observed) / (later - observed))


def station_modes(plan, output, *, defect_collectors=None):
    """Measure E1 from unique captured reports, over the named frozen panel dates."""
    counts = defaultdict(Counter)
    for event in plan:
        if not event["weather"] or event["market"] == "toronto":
            continue
        with tempfile.TemporaryDirectory(prefix="station-", dir=output) as scratch:
            db = inputs.open_store(Path(scratch) / "observations.sqlite")
            try:
                spec = REGISTRY[event["market"]]
                defects = inputs.CaptureDefects(event)
                if defect_collectors is not None:
                    defect_collectors[event["slug"]] = defects
                inputs.stage_weather(db, event["weather"], [], spec, event["start"], event["end"], reader=defects.read)
                for at, in db.execute("SELECT DISTINCT at FROM observations WHERE routine=1"):
                    counts[spec.icao][datetime.fromtimestamp(at, timezone.utc).minute] += 1
            finally:
                db.close()
    modes = {}
    for station, values in counts.items():
        maximum = max(values.values())
        candidates = [minute for minute, count in values.items() if count == maximum]
        if len(candidates) != 1:
            raise StudyError(f"station {station} has tied report-minute modes; E1 window needs clarification")
        modes[station] = candidates[0]
    return modes, {station: dict(values) for station, values in counts.items()}


class DiskTotals:
    """Keep corpus-size aggregation off the capture host's Python heap."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA cache_size=-4096")
        self.db.execute("CREATE TABLE cells (key TEXT,day TEXT,market TEXT," +
                        ",".join(name + " REAL" for name in stats.FIELDS) + ",PRIMARY KEY(key,day,market))")

    def add(self, key, identity, values):
        fields = stats.FIELDS
        self.db.execute("INSERT INTO cells VALUES (" + ",".join("?" for _ in range(3 + len(fields))) +
                        ") ON CONFLICT(key,day,market) DO UPDATE SET " +
                        ",".join(name + "=" + name + "+excluded." + name for name in fields),
                        ("/".join(key), *identity, *(values[name] for name in fields)))

    def get(self, key):
        return {(row[0], row[1]): dict(zip(stats.FIELDS, row[2:])) for row in self.db.execute(
            "SELECT day,market," + ",".join(stats.FIELDS) + " FROM cells WHERE key=? ORDER BY day,market", ("/".join(key),))}

    def configurations(self):
        return sorted({tuple(row[0].split("/")[:4])
                       for row in self.db.execute("SELECT DISTINCT key FROM cells")})


def process_peak_bytes():
    """OS process-lifetime RSS high-water mark, including interpreter imports."""
    if os.name != "nt":
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("peak", "current", "peak_paged", "paged",
                                               "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.argtypes, current.restype = [], wintypes.HANDLE
    query = ctypes.windll.psapi.GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not query(current(), ctypes.byref(counters), counters.cb):
        raise OSError("could not measure process memory peak")
    return int(counters.peak)


def run_study(plan, output_dir, *, replicates=base.DEFAULT_BOOTSTRAP_REPLICATES, panel="A", now=None):
    output = base.ensure_output_dir_allowed(output_dir).resolve()
    metadata = panel_metadata(panel)
    require_closed_panel(panel, now)
    first, last = PANELS[panel]
    # Validate even caller-built plans before any tape read or output creation.
    for event in plan:
        day = date.fromisoformat(event["date"])
        if not first <= day <= last or event.get("panel", panel) != panel:
            raise StudyError("event does not belong to the selected frozen panel; panels cannot be pooled")
        spec = REGISTRY[event["market"]]
        if (event["start"] != datetime.combine(day, time(), spec.tz).timestamp()
                or event["end"] != datetime.combine(day + timedelta(days=1), time(), spec.tz).timestamp()):
            raise StudyError("event time bounds do not match its frozen panel date")
    plan = [{**event, **metadata} for event in plan]
    if output.exists() and any(output.iterdir()):
        raise StudyError("output directory must be new or empty; prior evidence is immutable")
    output.mkdir(parents=True, exist_ok=True)
    inventories = inventory(plan)
    totals, public = DiskTotals(output / "date_market_sums.sqlite"), {}
    events, counters = [], defaultdict(int)
    latency = {key: defaultdict(list) for key in ("E2", "E3")}
    tracemalloc.start()
    try:
        defect_collectors = {}
        modes, mode_counts = station_modes(plan, output, defect_collectors=defect_collectors)
        with gzip.open(output / "intermediates.jsonl.gz", "wt", encoding="utf-8") as audit:
            _write_audit(audit, {"type": "study_panel", "frozen_ref": FROZEN_REF}, panel=panel)
            for event in sorted(plan, key=lambda e: (e["date"], e["market"])):
                note = {"event": event["slug"], "date": event["date"], "market": event["market"], "exclusions": []}
                defects = defect_collectors.pop(event["slug"], None) or inputs.CaptureDefects(event)
                note["record_exclusions"] = defects.rows
                events.append(note)
                if not event["trades"] and not event["gaps"] and not Path(event["status"]).is_file():
                    note["exclusions"].append("not_on_execution_tape")
                    continue
                if not event["summary"]:
                    note["exclusions"].append("book_coverage_below_90_percent_no_summary")
                    continue
                quality = inputs.coverage(event["summary"], event["gaps"], event["status"], event["start"], event["end"], target_date=event["date"], defects=defects)
                note.update(quality)
                if note["exclusions"]:
                    continue
                if not event["book"]:
                    raise StudyError("admitted date-market has no full-depth tape; cannot compute frozen quotes")
                with tempfile.TemporaryDirectory(prefix="event-", dir=output) as scratch:
                    db = inputs.open_store(Path(scratch) / "sort.sqlite")
                    try:
                        spec = REGISTRY[event["market"]]
                        inputs.stage_terms(db, event["rewards"], event["start"], event["end"], reader=defects.read)
                        reward_inputs.stage_rewards(db, event.get("maker_rewards", []), event["slug"],
                                                    event["start"], event["end"])
                        inputs.stage_weather(db, event["weather"], event["triggers"], spec, event["start"], event["end"], reader=defects.read)
                        if not db.execute("SELECT 1 FROM terms WHERE at>=? AND at<? LIMIT 1",
                                          (event["start"], event["end"])).fetchone():
                            note["exclusions"].append("no_panel_bands_with_captured_reward_terms")
                            continue
                        inputs.stage_iem(db, event.get("iem", []), spec, event["start"], event["end"])
                        inputs.stage_books(db, event["book"], counters, reader=defects.read)
                        inputs.stage_trades(db, event["trades"], event["start"], event["end"], counters, reader=defects.read)
                        note.update(inputs.coverage(event["summary"], event["gaps"], event["status"],
                            event["start"], event["end"], target_date=event["date"], defects=defects))
                        note["undecodable_records"] = len(defects.rows)
                        for row in defects.rows:
                            _write_audit(audit, {"type": "record_exclusion", **row}, panel=panel)
                        if note["exclusions"]:
                            continue
                        windows, window_notes = inputs.windows_for_event(db, spec, event["start"], event["end"],
                            station_minute=modes.get(spec.icao),
                            reconstruct_triggers=event.get("reconstruct_e2", False) or not event["triggers"])
                        note.update(window_notes)
                        bands, term_notes = panel_terms(db, event, windows, defect_minutes=defects.minutes)
                        note.update(term_notes)
                        if not bands:
                            note["exclusions"].append("no_panel_bands_with_captured_reward_terms")
                            continue
                        if term_notes["excluded_band_minute_fraction"] > .20:
                            note["exclusions"].append("missing_terms_or_capture_defects_above_20_percent_of_band_minutes"
                                if defects.minutes else "missing_terms_above_20_percent_of_band_minutes")
                            continue
                        label = read_settlement(event["ledger"], event["slug"])
                        note["bands"] = []
                        for window in windows:
                            _write_audit(audit, {"type": "window", "event": event["slug"], **vars(window)}, panel=panel)
                        for band in bands:
                            cells, band_notes = process_band(db, event, band, windows, label, audit)
                            note["bands"].append({"condition": band["condition"], **band_notes})
                            identity = (event["date"], event["market"])
                            for key, values in cells.items():
                                totals.add(key, identity, values)
                            public_markouts(db, event, band, windows, label, public, defect_minutes=defects.minutes)
                            _latency(db, event, band, windows, latency, counters)
                    finally:
                        db.close()
                if tracemalloc.get_traced_memory()[1] > 256 * 1024 * 1024:
                    raise StudyError("256 MiB Python allocation budget exceeded; no partial verdict")
        results, reward_results = {}, {}
        totals.db.commit()
        configurations = totals.configurations()
        for config in configurations:
            total = totals.get((*config, "TOTAL"))
            outside = totals.get((*config, "OUTSIDE"))
            if config[3] == "R":
                rows = [(identity, values, stats.zero(), stats.zero()) for identity, values in sorted(total.items())]
                key = "/".join(config[:2])
                reward_results[key] = stats.summarize(rows, "R:" + key, replicates=replicates, reward_only=True)
                continue
            for group in (*WINDOW_SETS, *EXTRA_GROUPS):
                inside = totals.get((*config, group))
                rows = [(identity, values, inside.get(identity, stats.zero()), outside.get(identity, stats.zero()))
                        for identity, values in sorted(total.items())]
                key = "/".join((*config, group))
                results[key] = stats.summarize(rows, key, replicates=replicates)
                # The standing measurement contract defines market x date as crossed clustering.
                results[key]["crossed_date_market_sensitivity"] = stats.summarize(rows, key + ":crossed",
                    replicates=replicates, crossed=True)
                if config[3] != "30m":
                    for result in (results[key], results[key]["crossed_date_market_sensitivity"]):
                        for section in ("point", "interval_90", "valid_bootstrap_replicates"):
                            result[section] = {name: value for name, value in result[section].items() if not name.startswith("net_")}
        primary_prefix = "d1.5_conservative/midrange/book_mid/30m/"
        primary = results.get(primary_prefix + "E123")
        decision = stats.decision(primary) if primary else {"verdict": "INCONCLUSIVE", "reason": "UNDERPOWERED"}
        kill_sets = {name: results[primary_prefix + name] for name in WINDOW_SETS if primary_prefix + name in results}
        peak = tracemalloc.get_traced_memory()[1]
        report = {"report_kind": REPORT_NAME, "revision": 1, "frozen_ref": FROZEN_REF, **metadata,
                  "primary": primary_prefix + "E123", "decision": decision,
                  "kill": stats.kill_decision(kill_sets), "results": results, "R": reward_results, "events": events,
                  "inputs": inventories, "counters": dict(counters), "station_report_minute_counts": mode_counts,
                  "latency": {key: stats.latency_summary(value, "latency:" + key, replicates=replicates) for key, value in latency.items()},
                  "public_maker_markouts": {"/".join(key): base.summarize_cell(cell, seed=base.DEFAULT_SEED,
                      cell_key="public:" + "/".join(key), replicates=replicates) for key, cell in sorted(public.items())},
                  "resources": {"peak_python_allocated_bytes": peak, "sqlite_cache_bytes": 4194304,
                                "process_lifetime_peak_working_set_bytes": process_peak_bytes(),
                                "max_jsonl_record_bytes": inputs.MAX_LINE_BYTES, "events_in_memory": 1},
                  "inference": {"seed": base.DEFAULT_SEED, "bootstrap_replicates": replicates,
                      "interval_level": .90, "min_date_clusters": base.MIN_DATE_CLUSTERS},
                  "accounting": {"CR": "horizon-specific leg-minute panel",
                      "net_pull": "30m two-leg quote-minutes, unchanged joint reward",
                      "R": "full eligible panel; no horizon restriction",
                      "minute_clock": "UTC calendar minutes; exposure integrated between events",
                      "market_date_sensitivity": "independently resample dates and markets; multiply their weights"},
                  "caveats": ["Synthetic counterfactual fills; queue ahead ignored; no realized maker-profit claim.",
                      "One-minute markouts are descriptive only (60-second samples, 120-second tolerance).",
                      "WU settlement fallback is flagged per band; no rebate is credited.",
                      "Outside-[0.10,0.90] midpoints are reported separately."]}
        peak = tracemalloc.get_traced_memory()[1]
        if peak > 256 * 1024 * 1024:
            raise StudyError("256 MiB Python allocation budget exceeded during inference; no verdict written")
        report["resources"]["peak_python_allocated_bytes"] = peak
        with (output / (REPORT_NAME + ".json")).open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        (output / (REPORT_NAME + ".md")).write_text(
            f"# Fill-toxicity desk study\n\n**{decision['verdict']} — {decision['reason']}**\n\n"
            f"Frozen authority: `{FROZEN_REF}`. Kill rule: `{report['kill']['verdict']}`.\n\n"
            f"panel: `{panel}`; panel_start: `{metadata['panel_start']}`; panel_end: `{metadata['panel_end']}`.\n\n"
            f"Peak traced Python allocation: {peak:,} bytes. Inputs, exclusions, every estimate and its interval "
            f"are in `{REPORT_NAME}.json`; streaming intermediates are in `intermediates.jsonl.gz`.\n\n"
            + "\n".join("- " + note for note in report["caveats"]) + "\n", encoding="utf-8")
        return report
    finally:
        totals.db.close()
        tracemalloc.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", choices=tuple(PANELS), default="A",
                        help="separately frozen study panel (default: A); B scores only after all its dates close")
    parser.add_argument("--snapshots-root", type=Path, default=data_path("snapshots"))
    parser.add_argument("--settlement-root", type=Path, default=data_path("settlements"))
    parser.add_argument("--maker-evidence-root", type=Path,
                        help="sealed 88a segments (default: maker_evidence beside snapshots root)")
    parser.add_argument("--support-manifest", type=Path, help="JSON map of event slugs to exact additional captured input paths; no data precomputation")
    parser.add_argument("--max-dates", type=int, help="limit dates within the selected panel (default: its full range)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="list exact inputs and sizes without reading tape content")
    args = parser.parse_args(argv)
    try:
        base.ensure_output_dir_allowed(args.output_dir)
        if not args.dry_run:
            require_closed_panel(args.panel)
        supplements = json.loads(args.support_manifest.read_text(encoding="utf-8-sig")) if args.support_manifest else None
        plan = input_plan(args.snapshots_root, args.settlement_root, max_dates=args.max_dates,
                          supplements=supplements, maker_evidence_root=args.maker_evidence_root, panel=args.panel)
        if args.dry_run:
            print(json.dumps({"dry_run": True, "frozen_ref": FROZEN_REF, **panel_metadata(args.panel),
                              "events": plan, "inputs": inventory(plan)}, indent=2))
            return 0
        result = run_study(plan, args.output_dir, panel=args.panel)
        print(json.dumps({**panel_metadata(args.panel), "decision": result["decision"],
                          "kill": result["kill"], "resources": result["resources"]}))
        return 0
    except (StudyError, base.MarkoutError, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
