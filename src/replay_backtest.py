"""Replay-backtest: re-run the *current* model over the captured corpus and
score it against settlement, three ways.

Unlike ``backtest.py`` (which scores the *frozen* probabilities recorded on the
tape, and so cannot evaluate a code change on days already captured), this
re-runs ``estimate_distribution`` over each snapshot's stored inputs with
today's code. For every captured band it compares:

  * **replayed** model -- what the current code produces, and
  * **recorded** model -- what was deployed when the snapshot was taken, and
  * **market**  -- the contemporaneous yes-price,

all against the realized WU settlement bucket. ``replayed_brier - recorded_brier``
is the measured effect of every code change since capture: negative is an
improvement. With ``--save-baseline`` / ``--gate`` it becomes a regression guard
so no model change ships without being measured on real days.

A fidelity canary guards the corpus itself: replaying a snapshot with the same
code version that produced it must reproduce its recorded distribution (L1 ~ 0).

CLI:
  python -m src.replay_backtest [folder ...]
      [--snapshots-root data/snapshots]
      [--settle YYYY-MM-DD=BUCKET ...]
      [--include-reconstructed]          # also score approximate reconstructed days
      [--out data/backtest/replay_report.md]
      [--save-baseline PATH] | [--gate PATH [--tol 0.003]]
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    bin_type,
    capture_minute,
    fmt_num,
    fmt_pct,
    fmt_signed,
    group_sort_key,
    last_pre_close_rows,
    load_daily_summary,
    band_value_hi,
    markdown_table,
    reliability,
    resolve_outcome,
    safe_float,
    score_rows,
    settlement_for_tape,
)
from market_config import date_from_event_slug
from replay import (
    band_model_probability,
    distribution_l1,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    replay_distribution,
    replay_model_version,
)
from toronto_model import TorontoHighTempModel

DEFAULT_OUT = Path("data") / "backtest" / "replay_report.md"
DEFAULT_BASELINE = Path("data") / "backtest" / "replay_baseline.json"
FIDELITY_FAITHFUL_L1 = 0.01  # same-version replay within this L1 is "faithful"


def model_view(rows, prob_field):
    """Rows shaped for ``score_rows``: ``model_probability`` drawn from one of
    the parallel probability fields. All grouping keys are preserved."""
    out = []
    for row in rows:
        copy = dict(row)
        copy["model_probability"] = row[prob_field]
        out.append(copy)
    return out


def comparison(rows):
    """Replayed vs recorded vs market over a row set (None if empty)."""
    replayed = score_rows(model_view(rows, "replayed_p"))
    recorded = score_rows(model_view(rows, "recorded_p"))
    if not replayed or not recorded:
        return None
    return {
        "n": replayed["n"],
        "replayed_brier": replayed["model_brier"],
        "recorded_brier": recorded["model_brier"],
        "market_brier": replayed["market_brier"],
        "replayed_logloss": replayed["model_logloss"],
        "recorded_logloss": recorded["model_logloss"],
        "market_logloss": replayed["market_logloss"],
        "replayed_skill": replayed["brier_skill_score"],
        "recorded_skill": recorded["brier_skill_score"],
        "code_effect": replayed["model_brier"] - recorded["model_brier"],
        "base_rate": replayed["base_rate"],
    }


def daily_first_comparison(day_results):
    """Equal-weight days (so snapshot-heavy days don't dominate the headline)."""
    comps = [day["comparison"] for day in day_results if day.get("comparison")]
    if not comps:
        return None

    def avg(key):
        return sum(c[key] for c in comps) / len(comps)

    return {
        "n_days": len(comps),
        "n": sum(c["n"] for c in comps),
        "replayed_brier": avg("replayed_brier"),
        "recorded_brier": avg("recorded_brier"),
        "market_brier": avg("market_brier"),
        "replayed_skill": avg("replayed_skill"),
        "recorded_skill": avg("recorded_skill"),
        "code_effect": avg("replayed_brier") - avg("recorded_brier"),
        "base_rate": avg("base_rate"),
    }


def grouped_comparison(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def fidelity_summary(fidelity_rows):
    """Split the fidelity canary into same-version (must be ~0) and changed-
    version (the magnitude of the code change) cohorts."""
    same = [f for f in fidelity_rows if f["recorded_version"] == f["replayed_version"]
            and not f["reconstructed"]]
    changed = [f for f in fidelity_rows if f["recorded_version"] != f["replayed_version"]
               and not f["reconstructed"]]
    reconstructed = [f for f in fidelity_rows if f["reconstructed"]]

    def mean_l1(rows):
        return sum(r["l1"] for r in rows) / len(rows) if rows else None

    same_mean = mean_l1(same)
    return {
        "same_version_n": len(same),
        "same_version_mean_l1": same_mean,
        "same_version_max_l1": max((r["l1"] for r in same), default=None),
        "same_version_faithful": (same_mean is not None and same_mean <= FIDELITY_FAITHFUL_L1),
        "changed_version_n": len(changed),
        "changed_version_mean_l1": mean_l1(changed),
        "reconstructed_n": len(reconstructed),
        "reconstructed_mean_l1": mean_l1(reconstructed),
    }


def run_replay_backtest(folders, daily_summary_path, overrides, out_path,
                        include_reconstructed=False, write=True):
    daily_index = load_daily_summary(daily_summary_path)
    model = TorontoHighTempModel()

    all_rows = []
    days = []
    fidelity_rows = []
    snaps_in_corpus = 0
    snaps_scored = 0

    for folder in folders:
        tape_path = Path(folder) / "snapshots_long.csv"
        if not tape_path.exists():
            print(f"  skip {folder}: no snapshots_long.csv")
            continue
        records = index_records_by_snapshot(load_replay_records(folder))
        if not records:
            print(f"  skip {Path(folder).name}: no replay_inputs.jsonl (capture not yet seeded)")
            continue
        df = pd.read_csv(tape_path)
        if "snapshot_id" not in df:
            continue
        slug = Path(folder).name
        target_date = date_from_event_slug(slug)
        date_label = target_date.isoformat() if target_date else slug
        bucket, source, note = settlement_for_tape(df, target_date, daily_index, overrides)

        day_rows = []
        for snapshot_id, group in df.groupby("snapshot_id"):
            record = records.get(str(snapshot_id))
            if not record:
                continue
            reconstructed = is_reconstructed(record)
            if reconstructed and not include_reconstructed:
                continue
            snaps_in_corpus += 1
            distribution = replay_distribution(model, record)
            if not distribution:
                continue
            snaps_scored += 1

            recorded_distribution = record.get("recorded_distribution")
            if recorded_distribution:
                fidelity_rows.append({
                    "snapshot_id": str(snapshot_id),
                    "date": date_label,
                    "recorded_version": record.get("model_version"),
                    "replayed_version": replay_model_version(model),
                    "l1": distribution_l1(distribution, recorded_distribution),
                    "reconstructed": reconstructed,
                })

            for _, band_series in group.iterrows():
                band = band_series.to_dict()
                outcome = resolve_outcome(
                    band.get("bin_kind"), band.get("bin_value_c"), bucket,
                    value_hi=band_value_hi(band.get("range_label"), band.get("bin_value_c")))
                if outcome is None:
                    continue
                market_yes = safe_float(band.get("market_yes"))
                recorded_p = safe_float(band.get("model_probability"))
                if market_yes is None or recorded_p is None:
                    continue
                replayed_p = band_model_probability(model, distribution, band)
                if replayed_p is None:
                    continue
                minute = capture_minute(band.get("captured_at_local"))
                day_rows.append({
                    "snapshot_id": str(snapshot_id),
                    "target_date": date_label,
                    "captured_at_local": band.get("captured_at_local"),
                    "capture_minute": minute,
                    "cutoff_hour": minute // 60 if minute is not None else None,
                    "band": band.get("range_label"),
                    "bin_type": bin_type(band.get("bin_kind")),
                    "bin_value_c": safe_float(band.get("bin_value_c")),
                    "market_yes": market_yes,
                    "market_no": safe_float(band.get("market_no")),
                    "outcome": int(outcome),
                    "recorded_p": recorded_p,
                    "replayed_p": replayed_p,
                    "reconstructed": reconstructed,
                })

        all_rows.extend(day_rows)
        days.append({
            "date": date_label,
            "event_slug": slug,
            "settlement": bucket,
            "source": source,
            "note": note,
            "snapshots_scored": len({r["snapshot_id"] for r in day_rows}),
            "rows": len(day_rows),
            "reconstructed": any(r["reconstructed"] for r in day_rows),
            "comparison": comparison(day_rows),
        })
        print(f"  {slug}: settlement {bucket} C ({source}); "
              f"{len({r['snapshot_id'] for r in day_rows})} snapshots replayed, {len(day_rows)} band-rows")

    last_rows = last_pre_close_rows(all_rows)
    results = {
        "folders": [str(f) for f in folders],
        "days": days,
        "total_rows": len(all_rows),
        "all_rows": all_rows,
        "snaps_in_corpus": snaps_in_corpus,
        "snaps_scored": snaps_scored,
        "replayed_versions": sorted({f["replayed_version"] for f in fidelity_rows if f["replayed_version"]}),
        "aggregate": comparison(all_rows),
        "daily_first": daily_first_comparison(days),
        "last_pre_close": comparison(last_rows),
        "by_day": grouped_comparison(all_rows, "target_date"),
        "by_hour": grouped_comparison(all_rows, "cutoff_hour"),
        "by_bin_type": grouped_comparison(all_rows, "bin_type"),
        "fidelity": fidelity_summary(fidelity_rows),
        "include_reconstructed": include_reconstructed,
    }
    if write:
        write_report(results, out_path)
    return results


# --- Report -----------------------------------------------------------------

def comparison_table_rows(items):
    rows = []
    for label, comp in items:
        if not comp:
            continue
        rows.append([
            label,
            comp.get("n_days", "-"),
            comp.get("n", "-"),
            fmt_num(comp.get("replayed_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            fmt_signed(comp.get("code_effect")),
            fmt_signed(comp.get("replayed_skill"), 3),
            fmt_pct(comp.get("base_rate")),
        ])
    return rows


def grouped_comparison_table_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", "-"),
            fmt_num(item.get("replayed_brier")),
            fmt_num(item.get("recorded_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("code_effect")),
            fmt_signed(item.get("replayed_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


COMPARISON_HEADERS = [
    "Scope", "Days", "Rows", "Replayed Brier", "Recorded Brier",
    "Market Brier", "Code Effect", "Replayed Skill", "Base Rate",
]
GROUPED_HEADERS = [
    "Group", "Rows", "Replayed Brier", "Recorded Brier",
    "Market Brier", "Code Effect", "Replayed Skill", "Base Rate",
]


def write_report(results, out_path):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    fid = results.get("fidelity") or {}
    lines = [
        "# Replay Backtest (model re-run over captured inputs)",
        "",
        f"Generated: {generated}",
        "",
        (
            f"Days scored: {len(results['days'])}  |  "
            f"Snapshots replayed: {results['snaps_scored']}  |  "
            f"Band-rows: {results['total_rows']}"
        ),
        f"Replayed model version(s): {', '.join(results.get('replayed_versions') or []) or '-'}",
        f"Reconstructed days included: {results.get('include_reconstructed')}",
        "",
        "> **Code Effect = Replayed Brier - Recorded Brier** (negative = the current",
        "> code is better than what was deployed when the snapshot was captured).",
        "> Recorded/market are the frozen tape values; replayed is today's code re-run",
        "> over the identical stored inputs. Lower Brier is better.",
        "",
        "## Replay Fidelity Canary",
        "",
        "Replaying a snapshot with the *same* code version that produced it must",
        "reproduce its recorded distribution (L1 ~ 0). A large same-version L1 means",
        "the corpus is not faithfully replayable -- investigate before trusting scores.",
        "",
    ]
    lines += markdown_table(
        ["Cohort", "Snapshots", "Mean L1", "Max L1", "Verdict"],
        [
            [
                "Same code version (canary)",
                fid.get("same_version_n", 0),
                fmt_num(fid.get("same_version_mean_l1")),
                fmt_num(fid.get("same_version_max_l1")),
                "FAITHFUL" if fid.get("same_version_faithful") else
                ("-" if fid.get("same_version_n", 0) == 0 else "CHECK"),
            ],
            [
                "Changed code version (effect size)",
                fid.get("changed_version_n", 0),
                fmt_num(fid.get("changed_version_mean_l1")),
                "-",
                "code change moved the distribution",
            ],
            [
                "Reconstructed (approximate)",
                fid.get("reconstructed_n", 0),
                fmt_num(fid.get("reconstructed_mean_l1")),
                "-",
                "approximate inputs -- exploratory only",
            ],
        ],
    )

    lines += ["", "## Headline: Replayed vs Recorded vs Market", ""]
    lines += markdown_table(
        COMPARISON_HEADERS,
        comparison_table_rows([
            ("All snapshots", results.get("aggregate")),
            ("Daily-first equal-day average", results.get("daily_first")),
            ("Last pre-close", results.get("last_pre_close")),
        ]),
    )

    lines += ["", "## Per Target Day", ""]
    lines += markdown_table(
        ["Date", "Settlement", "Source", "Snaps", "Replayed Brier",
         "Recorded Brier", "Market Brier", "Code Effect", "Note"],
        [
            [
                day["date"],
                f"{day['settlement']} C" if day["settlement"] is not None else "-",
                day["source"],
                day["snapshots_scored"],
                fmt_num((day.get("comparison") or {}).get("replayed_brier")),
                fmt_num((day.get("comparison") or {}).get("recorded_brier")),
                fmt_num((day.get("comparison") or {}).get("market_brier")),
                fmt_signed((day.get("comparison") or {}).get("code_effect")),
                day["note"] or "-",
            ]
            for day in results["days"]
        ],
    )

    lines += ["", "## By Capture Hour", ""]
    lines += markdown_table(GROUPED_HEADERS, grouped_comparison_table_rows(results.get("by_hour", [])))

    lines += ["", "## By Market-Bin Type", ""]
    lines += markdown_table(GROUPED_HEADERS, grouped_comparison_table_rows(results.get("by_bin_type", [])))

    lines += ["", "## Replayed Reliability", ""]
    lines += markdown_table(
        ["Confidence bin", "N", "Mean predicted", "Realized"],
        [
            [row["bin"], row["n"], fmt_pct(row["pred"]), fmt_pct(row["actual"])]
            for row in reliability(model_view(results["all_rows"], "replayed_p"), "model_probability")
        ],
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Baseline / regression gate ---------------------------------------------

def baseline_payload(results):
    aggregate = results.get("aggregate") or {}
    daily = results.get("daily_first") or {}
    return {
        "generated": datetime.now().isoformat(),
        "replayed_versions": results.get("replayed_versions"),
        "snaps_scored": results.get("snaps_scored"),
        "aggregate_replayed_brier": aggregate.get("replayed_brier"),
        "aggregate_market_brier": aggregate.get("market_brier"),
        "daily_first_replayed_brier": daily.get("replayed_brier"),
    }


def save_baseline(path, results):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(baseline_payload(results), indent=2, sort_keys=True), encoding="utf-8")


def gate(baseline_path, results, tol):
    """Compare the current replayed aggregate Brier to a saved baseline.

    Returns (passed, message). A change that *worsens* the replayed Brier on the
    corpus by more than ``tol`` fails the gate.
    """
    try:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"could not read baseline {baseline_path}: {exc}"
    aggregate = results.get("aggregate") or {}
    current = aggregate.get("replayed_brier")
    base = baseline.get("aggregate_replayed_brier")
    if current is None or base is None:
        return False, "missing aggregate Brier in baseline or current run"
    delta = current - base
    passed = delta <= tol
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"{verdict}: replayed Brier {current:.4f} vs baseline {base:.4f} "
        f"(delta {delta:+.4f}, tol {tol:.4f})"
    )


def main():
    parser = argparse.ArgumentParser(description="Replay the model over captured inputs and score it.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under snapshots root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    parser.add_argument("--settle", action="append", default=[],
                        help="Force settlement: YYYY-MM-DD=BUCKET (repeatable).")
    parser.add_argument("--include-reconstructed", action="store_true",
                        help="Also score approximate reconstructed days (excluded by default).")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--save-baseline", nargs="?", const=str(DEFAULT_BASELINE), default=None,
                        help="Save this run's replayed scores as the regression baseline.")
    parser.add_argument("--gate", nargs="?", const=str(DEFAULT_BASELINE), default=None,
                        help="Fail (exit 1) if replayed Brier regressed vs the saved baseline.")
    parser.add_argument("--tol", type=float, default=0.003, help="Gate tolerance on aggregate Brier.")
    args = parser.parse_args()

    overrides = {}
    for item in args.settle:
        date_str, _, value = item.partition("=")
        overrides[date_str.strip()] = int(value)

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Replaying {len(folders)} market day(s) over the corpus...")
    results = run_replay_backtest(
        folders, args.daily_summary, overrides, args.out,
        include_reconstructed=args.include_reconstructed,
    )

    if results["snaps_scored"] == 0:
        print("\nNo snapshots had replay inputs yet. Seed the corpus by running the")
        print("collector (snapshot_tracker) on this version, then re-run this backtest.")
        return

    aggregate = results.get("aggregate") or {}
    fid = results.get("fidelity") or {}
    if aggregate:
        print(
            f"\nAll-snapshot replayed Brier {aggregate['replayed_brier']:.4f} vs "
            f"recorded {aggregate['recorded_brier']:.4f} vs market {aggregate['market_brier']:.4f} "
            f"(code effect {aggregate['code_effect']:+.4f})"
        )
    if fid.get("same_version_n"):
        verdict = "faithful" if fid.get("same_version_faithful") else "CHECK CORPUS"
        print(f"Fidelity canary: {fid['same_version_n']} same-version snapshots, "
              f"mean L1 {fid['same_version_mean_l1']:.5f} ({verdict})")
    print(f"Report written to {args.out}")

    if args.save_baseline:
        save_baseline(args.save_baseline, results)
        print(f"Baseline saved to {args.save_baseline}")
    if args.gate:
        passed, message = gate(args.gate, results, args.tol)
        print(f"Regression gate: {message}")
        if not passed:
            sys.exit(1)


if __name__ == "__main__":
    main()
