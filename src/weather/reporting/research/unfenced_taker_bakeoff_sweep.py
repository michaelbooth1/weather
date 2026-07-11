"""Unfenced taker strategy bakeoff sweep (item 238 / fade_overpriced activation).

The daily strategy bakeoff replays each live run's recorded ticks through the
registered strategy basket, but it inherits the live policy config — including
``taker_edge_permission_enabled`` — so counterfactual arms are fenced by the
same settlement-scored permission map as the live worker. Since permission
requires settled orders and settled orders require permission, both the live
worker AND the daily bakeoff have produced zero fills for weeks: the fence
built to gate trading also gated learning.

This sweep re-runs the bakeoff over historical run folders with the edge
permission fence DISABLED for the counterfactual arms, writing to a separate
research directory so the daily fenced artifacts and the champion ledger are
never contaminated. Counterfactual orders risk nothing; their purpose is to
generate exactly the settlement-scored evidence the permission map demands.

Usage:
    python -m weather.reporting.research.unfenced_taker_bakeoff_sweep \
        [--runs-root data/taker_runs] [--out-root data/backtest/research/unfenced_bakeoff] \
        [--max-days N] [--strategies id,id,...]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic
from weather.market.taker_bot_bakeoff import (
    build_champion_challenger_ledger,
    render_champion_challenger_ledger,
    run_taker_strategy_bakeoff,
)
from weather.market.taker_bot_strategy_registry import DEFAULT_BAKEOFF_STRATEGIES
from weather.market.taker_bot_tape_io import DEFAULT_LABELS_CSV, DEFAULT_RUNS_ROOT

EXPERIMENT_PREFIX = "unfenced-permission-probe"
UNFENCED_CONFIG = {"taker_edge_permission_enabled": False}


def sweep_run_folders(runs_root):
    """One run folder per date: the folder with the largest recorded tick tape."""
    root = Path(runs_root)
    for date_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        candidates = [
            (orders.stat().st_size, orders.parent)
            for orders in date_dir.glob("*/orders_long.csv")
            if orders.stat().st_size > 0
        ]
        if candidates:
            yield max(candidates)[1]


def run_sweep(
    runs_root=DEFAULT_RUNS_ROOT,
    out_root=None,
    labels_csv=DEFAULT_LABELS_CSV,
    strategies=DEFAULT_BAKEOFF_STRATEGIES,
    max_days=0,
):
    out_root = Path(out_root or Path("data") / "backtest" / "research" / "unfenced_bakeoff")
    out_root.mkdir(parents=True, exist_ok=True)
    folders = list(sweep_run_folders(runs_root))
    if max_days and max_days > 0:
        folders = folders[-max_days:]
    results = []
    bakeoff_paths = []
    for folder in folders:
        target = folder.parent.name
        out_json = out_root / f"{target}_strategy_bakeoff.json"
        row = {"target_date": target, "run_folder": str(folder), "out_json": str(out_json)}
        try:
            payload = run_taker_strategy_bakeoff(
                folder,
                labels_csv=labels_csv,
                strategies=strategies,
                out_json=out_json,
                out_report=out_root / f"{target}_strategy_bakeoff.md",
                config=dict(UNFENCED_CONFIG),
                experiment_id=f"{EXPERIMENT_PREFIX}-{target}",
            )
            summary = payload.get("summary") or {}
            row.update({
                "status": "ok",
                "generated_order_rows": summary.get("generated_order_rows"),
                "replay_tick_count": summary.get("replay_tick_count"),
                "promotion_pass_count": summary.get("promotion_pass_count"),
            })
            bakeoff_paths.append(out_json)
        except Exception as exc:  # noqa: BLE001 - one bad day must not kill the sweep
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        results.append(row)
        print(f"{target}: {row['status']} rows={row.get('generated_order_rows')}")

    ledger = build_champion_challenger_ledger(bakeoff_paths=bakeoff_paths)
    ledger["experiment"] = EXPERIMENT_PREFIX
    ledger["permission_fence_disabled"] = True
    ledger_json = out_root / "unfenced_champion_challenger_ledger.json"
    write_json_atomic(ledger_json, ledger, trailing_newline=True)
    ledger_md = out_root / "unfenced_champion_challenger_ledger.md"
    ledger_md.write_text(render_champion_challenger_ledger(ledger), encoding="utf-8")

    manifest = {
        "schema_version": "unfenced_taker_bakeoff_sweep_v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": EXPERIMENT_PREFIX,
        "permission_fence_disabled": True,
        "strategies": strategies,
        "day_count": len(results),
        "ok_count": sum(1 for row in results if row["status"] == "ok"),
        "error_count": sum(1 for row in results if row["status"] == "error"),
        "ledger_json": str(ledger_json),
        "ledger_report": str(ledger_md),
        "days": results,
    }
    manifest_path = out_root / "sweep_manifest.json"
    write_json_atomic(manifest_path, manifest, trailing_newline=True)
    print(f"sweep complete: {manifest['ok_count']}/{manifest['day_count']} days; ledger: {ledger_json}")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--out-root", default="")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--strategies", default=DEFAULT_BAKEOFF_STRATEGIES)
    parser.add_argument("--max-days", type=int, default=0)
    args = parser.parse_args(argv)
    manifest = run_sweep(
        runs_root=args.runs_root,
        out_root=args.out_root or None,
        labels_csv=args.labels_csv,
        strategies=args.strategies,
        max_days=args.max_days,
    )
    return 0 if manifest["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
