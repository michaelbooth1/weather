"""Measure rehearsed heap pops vs pull-opportunity candidates on fictional fixtures.

Run with the pinned exam tree's ``src`` first on PYTHONPATH; it imports only that tree's code.
``--validate DIR`` (a new, empty scratch directory) proves the pop counter equals ReplayEngine.run()
and pack_cli.rehearse(); ``--grid`` prints one JSON line per scenario. Replay work: on the capture
host it is heavy work under the host load policy. Report:
docs/roadmap/agent-report-2026-10-03-pull-cap-precheck.md.
"""
import argparse
import heapq
import json
import sys
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixture import day_records, in_memory, seal  # noqa: E402

from maker_core.replay import ceilings, pack_cli  # noqa: E402
from maker_core.replay.calibration import CALIBRATION_DATES  # noqa: E402
from maker_core.replay.engine import MAX_ENGINE_EVENTS, ReplayConfig, ReplayEngine  # noqa: E402
from maker_core.replay.execution_manifest import FROZEN_CONFIG, QUOTE_DATES, SETTLEMENT_DATE  # noqa: E402
from maker_core.replay.pull_efficiency import opportunity_candidates  # noqa: E402

CONFIG = ReplayConfig(**FROZEN_CONFIG, hazard_per_minute=0.01, max_events=MAX_ENGINE_EVENTS,
                      max_outputs=MAX_ENGINE_EVENTS)


class PopCounter(ReplayEngine):
    """run() without trades, ticks or spans: those never call schedule() under informed-v0."""

    def count(self):
        while self.heap:
            at = heapq.heappop(self.heap)
            self.pending.remove(at)
            self.processed += 1
            for row in sorted(self.records.pop(at, ()), key=lambda r: r.sequence):
                if row.kind != "trade":
                    self.ingest(row, at)
        return self.processed


def pops(bundle):
    return PopCounter((pack_cli._maintenance((bundle,))[0],), CONFIG).count()


def panel_candidates(d_union_by_day):
    """Panel-format windows (maintenance split; settlement day and targets after it carry none)."""
    from maker_core.replay.bundle import Bundle, Condition
    from datetime import datetime, timezone
    bundles = []
    for day, n in d_union_by_day.items():
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        conds = tuple(Condition(f"c{day:%m%d}-{k:04d}", f"city{k % 12:02d}", "fictional", start,
                                start + timedelta(days=1)) for k in range(n))
        intervals = []
        if day != SETTLEMENT_DATE:
            for k, c in enumerate(conds):
                if day == QUOTE_DATES[-1] and k % 3 == 2:
                    continue  # Horizon-2 bands on 10-13 target 10-15 > settlement: excluded.
                for lo, hi in ((c.active_from, start + timedelta(hours=5)), (start + timedelta(hours=8), c.active_until)):
                    intervals.append((c.condition_id, lo, hi))
        bundles.append(Bundle(day, start + timedelta(days=1), "synthetic", conds, (), {}, 0, tuple(intervals)))
    return opportunity_candidates(ReplayEngine(tuple(bundles), replace(CONFIG)).windows)


def validate(tmp):
    """Pop counter == real run() == rehearse(); reduced density == full density."""
    out = {}
    day = CALIBRATION_DATES[0]
    for minutes, d, churn, trades in ((180, 12, 1.0, 300), (120, 12, 2.0, 200), (90, 40, 1.5, 100),
                                      (40, 60, 1.5, 100)):
        conds, full = day_records(day, d, churn, trades, minutes=minutes)
        _, red = day_records(day, d, churn, trades, minutes=minutes, reduced=True)
        bf, br = in_memory(day, conds, full), in_memory(day, conds, red)
        engine = ReplayEngine(pack_cli._maintenance((bf,)), CONFIG)
        started = time.monotonic()
        engine.run()
        out[f"{minutes}m_D{d}_u{churn}_T{trades}"] = dict(
            records_full=len(full), records_reduced=len(red), counter_full=pops(bf), counter_reduced=pops(br),
            run_processed=engine.processed, run_seconds=round(time.monotonic() - started, 1))
    # The rehearsal CLI path itself, on sealed files: max over all eight passes.
    conds, full = day_records(day, 12, 1.0, 300, minutes=180)
    path = seal(tmp / day.isoformat() / "bundle", day, conds, full)
    cal = tmp / "calibration.json"
    cal.write_text(json.dumps({"format": "maker_core.replay.calibration.v1", "hazard_per_minute": 0.01}))
    from datetime import datetime, timezone
    measured, detail = pack_cli.rehearse([path], cal, now=datetime(2026, 10, 3, tzinfo=timezone.utc))
    out["rehearse_180m_D12"] = dict(engine_events=measured["engine_events"], passes=detail["engine_passes"],
                                    counter=pops(in_memory(day, conds, full)), records=measured["records"])
    return out


def scenario(d_inst, churn, trades, rewards="per_minute", panel_churn=None):
    per_date = {}
    for day in CALIBRATION_DATES:
        conds, red = day_records(day, d_inst, churn, trades, reduced=True, rewards=rewards)
        per_date[day.isoformat()] = dict(pops=pops(in_memory(day, conds, red)), d_union=len(conds))
    largest = max(v["pops"] for v in per_date.values())
    max_events = ceilings.next_power_of_two(largest * ceilings.MULTIPLIER)
    d_union = max(d_inst, round(d_inst * (panel_churn or churn)))
    candidates = panel_candidates({d: d_union for d in (*QUOTE_DATES, SETTLEMENT_DATE)})
    return dict(d_inst=d_inst, churn=churn, panel_churn=panel_churn or churn, trades_per_day=trades, rewards=rewards,
                per_date_pops=per_date, largest_pops=largest, unrounded=largest * 15, max_events=max_events,
                candidates=candidates, ratio=candidates / max_events,
                ratio_unrounded=candidates / (largest * 15), refuses=candidates > max_events)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--validate", type=Path)
    p.add_argument("--grid", action="store_true")
    a = p.parse_args()
    if a.validate:
        print(json.dumps(validate(a.validate), indent=1, default=str))
    if a.grid:
        rows = []
        for d, u, t, rw in ((12, 1.0, 0, "per_minute"), (12, 1.0, 2000, "per_minute"), (12, 2.0, 0, "per_minute"),
                            (12, 3.0, 0, "per_minute"), (12, 4.0, 0, "per_minute"), (12, 6.0, 0, "per_minute"),
                            (12, 1.0, 0, "hourly"), (12, 1.0, 2000, "hourly"), (12, 1.0, 0, "none"),
                            (120, 1.0, 0, "per_minute"), (120, 1.5, 2000, "per_minute"), (120, 2.0, 2000, "per_minute"),
                            (120, 3.0, 2000, "per_minute")):
            started = time.monotonic()
            r = scenario(d, u, t, rw)
            r["seconds"] = round(time.monotonic() - started, 1)
            rows.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "per_date_pops"}), flush=True)
        # The panel universe outgrowing the calibration universe.
        for d, u, t, pu in ((12, 1.0, 0, 2.0), (120, 1.5, 2000, 3.0), (120, 1.5, 2000, 4.5)):
            started = time.monotonic()
            r = scenario(d, u, t, panel_churn=pu)
            r["seconds"] = round(time.monotonic() - started, 1)
            rows.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "per_date_pops"}), flush=True)


if __name__ == "__main__":
    main()
