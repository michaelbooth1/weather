"""Evening-fix Stage 1, label-free stages only (L16, 2026-11-03). Stdlib plus the replay commit's own code.

Reads ONLY the --no-market replay JSONL. It never opens the ledger-rows file, any label, outcome,
settlement or price. Uses the scorer/transfer code of the replay commit itself (source tree passed
with --src, a `git archive c32629156 src`), so the numbers are the scorer's own definitions:

  (a) countability, replay half only: evening_fix_scorer.metadata_cells needs both replay arms on
      >= 90% of a cell's 17-23 snapshots AND the ledger's promotion_countable (Clarification 1 s.2,
      line 25-26). The ledger half is not read here (master: ledger_rows.jsonl stays closed until the
      label-free commit and master's go). A date with zero replay-countable US11 cells has zero
      countable US11 market-days whatever the ledger says; the converse is not claimed.
  (b) per-date L1 new vs recorded: evening_fix_transfer.reproduction_table (the B2 table) plus
      descriptive miss diagnostics (L1 magnitude, hour, market, model_version) for non-reproduced rows.
  (c) B2 verdict: evening_fix_transfer.select_reproducing_commit (overall single-commit share).

Output: one JSON file (counts and L1 values only, no band probabilities, no labels).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="src/ of the replay commit (git archive)")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--replay", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(f"refused: {out} exists", file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(args.src).resolve()))
    import weather
    from weather.backtesting import evening_fix_scorer as scorer
    from weather.backtesting import evening_fix_transfer as transfer
    weather_file = str(Path(weather.__file__).resolve())
    if not weather_file.startswith(str(Path(args.src).resolve())):
        print(f"refused: weather imported from {weather_file}", file=sys.stderr)
        return 2

    rows = transfer.load_replay(args.replay)          # window check + forecast-field projection
    scorer.check_no_market(rows)                     # a band price refuses
    table = transfer.reproduction_table({args.commit: rows})
    try:
        receipt = transfer.select_reproducing_commit({args.commit: rows})
        b2 = {"pass": True, "commit": receipt.commit}
    except transfer.ReproductionStop:
        b2 = {"pass": False, "commit": None}

    # (a) replay half of metadata_cells: every slug passed as promotion_countable=True (ledger not read).
    # (dict.get never calls a defaultdict factory, so the stand-in must name every slug.)
    stand_in = {row.get("event_slug"): {"promotion_countable": True} for row in rows}
    cells = scorer.metadata_cells(rows, stand_in)
    us_replay_countable = Counter(day for (market, day), cell in cells.items()
                                  if market in scorer.US_MARKETS and cell["countable"])
    dates = [d.isoformat() for d in transfer.window_dates()]
    zero_dates = [d for d in dates if us_replay_countable.get(d, 0) == 0]

    # (b) diagnostics for rows with a vector that miss 1e-9.
    misses = defaultdict(list)
    for row in rows:
        value = row.get("l1_new_vs_recorded")
        if value is not None and value > transfer.REPRODUCTION_L1:
            misses[row["target_date"]].append(row)
    diag = {}
    for day, items in sorted(misses.items()):
        values = sorted(r["l1_new_vs_recorded"] for r in items)
        diag[day] = {
            "misses": len(values),
            "l1_min": values[0], "l1_median": values[len(values) // 2], "l1_max": values[-1],
            "l1_gt_1e-6": sum(v > 1e-6 for v in values), "l1_gt_1e-3": sum(v > 1e-3 for v in values),
            "by_market": dict(sorted(Counter(r.get("market_id") for r in items).items())),
            "by_hour": dict(sorted(Counter(str(r.get("hour")) for r in items).items())),
            "by_model_version": dict(sorted(Counter(str(r.get("model_version")) for r in items).items())),
            "by_reconstructed": dict(sorted(Counter(str(r.get("reconstructed")) for r in items).items())),
        }

    result = {
        "schema": "evening_fix_stage1_label_free_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha256_file(__file__),
        "replay": {"path": str(Path(args.replay).resolve()), "sha256": sha256_file(args.replay), "rows": len(rows)},
        "code_commit": args.commit,
        "weather_file": weather_file,
        "inputs_not_opened": ["ledger_rows.jsonl", "any label/outcome/settlement/price"],
        "a_countability_replay_half": {
            "rule": "both arms on >=90% of 17-23 snapshots (metadata_cells); ledger promotion_countable NOT read",
            "dates_with_zero_replay_countable_us11_market_days": zero_dates,
        },
        "b_reproduction_table": table,
        "b_miss_diagnostics": diag,
        "c_b2_overall": b2,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(out)
    summary = {d: (v["rows"], v["within"], v["share"]) for d, v in table["commits"][args.commit]["per_date"].items()}
    print(json.dumps({"b2": b2, "overall": {k: table["commits"][args.commit][k] for k in ("rows", "within", "share")},
                      "zero_dates": zero_dates, "per_date": summary, "out_sha256": sha256_file(out)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
