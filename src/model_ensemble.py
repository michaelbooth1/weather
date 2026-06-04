"""Model ensemble and component-ablation research harness.

This module scores candidate forecasters on settlement-scored snapshot tapes.
It is deliberately separate from live inference: it can compare the deployed
weather model, market price, simple context priors, and any component
probability tapes persisted by snapshot_tracker.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (  # noqa: E402
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    backtest_tape,
    binary_log_loss,
    brier,
    load_daily_summary,
    load_market_day_label,
    missing,
    settlement_for_tape,
)
from market_config import date_from_event_slug  # noqa: E402
from settled_days import discover_settled_folders  # noqa: E402


DEFAULT_REPORT_PATH = Path("data") / "backtest" / "model_ensemble_report.md"
CANDIDATE_PREFIX = "candidate:"
DEPLOYED_MODEL = f"{CANDIDATE_PREFIX}deployed_model"
MARKET_PRICE = f"{CANDIDATE_PREFIX}market_price"
CONTEXT_PRIOR = f"{CANDIDATE_PREFIX}context_prior"


def clip_probability(value):
    return max(1e-6, min(1.0 - 1e-6, float(value)))


def candidate_label(name):
    return name.replace(CANDIDATE_PREFIX, "")


def score_predictions(predictions):
    clean = [(clip_probability(p), int(y)) for p, y in predictions if p is not None and not missing(p)]
    if not clean:
        return None
    return {
        "n": len(clean),
        "brier": sum(brier(p, y) for p, y in clean) / len(clean),
        "logloss": sum(binary_log_loss(p, y) for p, y in clean) / len(clean),
        "base_rate": sum(y for _, y in clean) / len(clean),
    }


def normalized_bin_value(value):
    if value is None or value == "":
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def component_key(row):
    return (
        str(row.get("snapshot_id")),
        str(row.get("bin_kind")),
        normalized_bin_value(row.get("bin_value_c")),
    )


def load_component_probabilities(folder):
    path = Path(folder) / "components_long.csv"
    if not path.exists():
        return {}
    out = defaultdict(dict)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            probability = row.get("component_probability")
            if probability in (None, ""):
                continue
            name = f"{CANDIDATE_PREFIX}component_{row.get('component_name')}"
            out[component_key(row)][name] = float(probability)
    return out


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    return discover_settled_folders(root, required_file="snapshots_long.csv")


def load_scored_rows(
    folders,
    daily_summary_path=DEFAULT_DAILY_SUMMARY,
    quality_grades=None,
    max_rows=None,
):
    daily_index = load_daily_summary(daily_summary_path)
    allowed_quality = set(quality_grades or [])
    rows = []
    metadata = []
    for folder in folders:
        folder = Path(folder)
        tape = folder / "snapshots_long.csv"
        if not tape.exists():
            continue
        label = load_market_day_label(folder)
        grade = label.get("quality_grade") if label else "-"
        if allowed_quality and grade not in allowed_quality:
            metadata.append({
                "event_slug": folder.name,
                "quality_grade": grade,
                "included": False,
                "reason": "quality filtered",
            })
            continue
        frame = pd.read_csv(tape)
        target_date = date_from_event_slug(folder.name)
        settlement, source, note = settlement_for_tape(frame, target_date, daily_index, {})
        scored, _, _, _ = backtest_tape(frame, settlement, [0.05], target_date=target_date)
        component_index = load_component_probabilities(folder)
        for row in scored:
            row[DEPLOYED_MODEL] = row.get("model_probability")
            row[MARKET_PRICE] = row.get("market_yes")
            row.update(component_index.get((
                str(row.get("snapshot_id")),
                str(row.get("bin_kind")),
                normalized_bin_value(row.get("bin_value_c")),
            ), {}))
            rows.append(row)
        metadata.append({
            "event_slug": folder.name,
            "quality_grade": grade,
            "included": True,
            "rows": len(scored),
            "settlement": settlement,
            "settlement_source": source,
            "note": note,
            "component_rows": sum(1 for _ in component_index),
        })
    rows = sorted(rows, key=lambda item: (
        str(item.get("target_date")),
        str(item.get("captured_at_local")),
        str(item.get("band")),
    ))
    if max_rows and len(rows) > max_rows:
        rows = rows[:max_rows]
    return rows, metadata


def available_candidates(rows, include_market=True):
    names = set()
    for row in rows:
        names.update(key for key in row if key.startswith(CANDIDATE_PREFIX))
    if not include_market:
        names.discard(MARKET_PRICE)
    # final_model duplicates deployed_model in future component tapes.
    names.discard(f"{CANDIDATE_PREFIX}component_final_model")
    return sorted(names)


class ContextPrior:
    def __init__(self, train_rows):
        self.groups = defaultdict(list)
        for row in train_rows:
            outcome = int(row["outcome"])
            self.groups[("bin_value", row.get("bin_type"), row.get("bin_value"))].append(outcome)
            self.groups[("bin_type", row.get("bin_type"))].append(outcome)
            self.groups[("global",)].append(outcome)

    def probability(self, row):
        for key in (
            ("bin_value", row.get("bin_type"), row.get("bin_value")),
            ("bin_type", row.get("bin_type")),
            ("global",),
        ):
            values = self.groups.get(key)
            if values:
                return sum(values) / len(values)
        return 0.5


def probability_for(row, candidate, prior=None):
    if candidate == CONTEXT_PRIOR:
        return prior.probability(row) if prior else None
    value = row.get(candidate)
    return None if value is None or missing(value) else float(value)


def evaluate_pair(train_rows, candidate_a, candidate_b, weight, prior):
    predictions = []
    for row in train_rows:
        pa = probability_for(row, candidate_a, prior)
        pb = probability_for(row, candidate_b, prior)
        if pa is None or pb is None:
            continue
        predictions.append((weight * pa + (1.0 - weight) * pb, row["outcome"]))
    return score_predictions(predictions)


def learn_pair_config(train_rows, candidates, weight_grid=None):
    weight_grid = weight_grid or [i / 10 for i in range(11)]
    candidates = sorted(set(candidates) | {CONTEXT_PRIOR})
    prior = ContextPrior(train_rows)
    best = None
    for candidate_a in candidates:
        for candidate_b in candidates:
            for weight in weight_grid:
                score = evaluate_pair(train_rows, candidate_a, candidate_b, weight, prior)
                if not score:
                    continue
                candidate = {
                    "candidate_a": candidate_a,
                    "candidate_b": candidate_b,
                    "weight_a": weight,
                    "train_brier": score["brier"],
                    "train_logloss": score["logloss"],
                    "train_n": score["n"],
                }
                if best is None or candidate["train_brier"] < best["train_brier"]:
                    best = candidate
    return best


def leave_one_day_ensemble(rows, candidates):
    days = sorted({row.get("target_date") for row in rows})
    if len(days) < 2:
        return None
    predictions = []
    configs = []
    for holdout in days:
        train_rows = [row for row in rows if row.get("target_date") != holdout]
        held_rows = [row for row in rows if row.get("target_date") == holdout]
        config = learn_pair_config(train_rows, candidates)
        if not config:
            continue
        prior = ContextPrior(train_rows)
        for row in held_rows:
            pa = probability_for(row, config["candidate_a"], prior)
            pb = probability_for(row, config["candidate_b"], prior)
            if pa is None or pb is None:
                continue
            pred = config["weight_a"] * pa + (1.0 - config["weight_a"]) * pb
            predictions.append((pred, row["outcome"]))
        configs.append({"holdout": holdout, **config})
    score = score_predictions(predictions)
    if not score:
        return None
    return {"score": score, "configs": configs}


def standalone_scores(rows):
    out = []
    for candidate in available_candidates(rows, include_market=True):
        score = score_predictions((row.get(candidate), row["outcome"]) for row in rows)
        if score:
            out.append({"candidate": candidate, **score})
    return sorted(out, key=lambda item: item["brier"])


def grouped_scores(rows, candidate, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    out = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        score = score_predictions((row.get(candidate), row["outcome"]) for row in group_rows)
        if score:
            out.append({"group": group, **score})
    return out


def group_sort_key(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def fmt_num(value, digits=4):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def score_row(label, score):
    if not score:
        return f"| {label} | - | - | - | - |"
    return (
        f"| {label} | {score['n']} | {fmt_num(score['brier'])} | "
        f"{fmt_num(score['logloss'])} | {fmt_num(score['base_rate'])} |"
    )


def write_report(path, rows, metadata, no_market, market_informed, max_rows=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    days = sorted({row.get("target_date") for row in rows})
    lines = [
        "# Model Ensemble And Ablation Report",
        "",
        f"Rows scored: {len(rows)}",
        f"Target days: {len(days)}",
        f"Sample cap: {max_rows or 'none'}",
        "",
        "## Inputs",
        "",
        "| Event | Included | Quality | Rows | Settlement | Source | Component keys |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for item in metadata:
        lines.append(
            f"| {item.get('event_slug')} | {item.get('included')} | "
            f"{item.get('quality_grade')} | {item.get('rows', 0)} | "
            f"{item.get('settlement', '-')} | {item.get('settlement_source', '-')} | "
            f"{item.get('component_rows', 0)} |"
        )
    lines.extend([
        "",
        "## Standalone Forecasters",
        "",
        "| Forecaster | Rows | Brier | LogLoss | Base rate |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])
    for item in standalone_scores(rows):
        lines.append(score_row(candidate_label(item["candidate"]), item))
    lines.extend([
        "",
        "## Leave-One-Day Ensemble",
        "",
        "No-market candidates exclude Polymarket prices. Market-informed candidates include them and are scored separately so edge claims remain interpretable.",
        "",
        "| Ensemble | Rows | Brier | LogLoss | Base rate |",
        "| :--- | :--- | :--- | :--- | :--- |",
        score_row("No-market tuned pair", no_market["score"] if no_market else None),
        score_row("Market-informed tuned pair", market_informed["score"] if market_informed else None),
        "",
    ])
    if len(days) < 2:
        lines.append("> Insufficient clean target days for leave-one-day ensemble validation.")
    if no_market:
        lines.extend(["", "### No-market fold configs", "", "| Holdout | A | Weight A | B | Train Brier |", "| :--- | :--- | :--- | :--- | :--- |"])
        for config in no_market["configs"]:
            lines.append(
                f"| {config['holdout']} | {candidate_label(config['candidate_a'])} | "
                f"{fmt_num(config['weight_a'], 2)} | {candidate_label(config['candidate_b'])} | "
                f"{fmt_num(config['train_brier'])} |"
            )
    if market_informed:
        lines.extend(["", "### Market-informed fold configs", "", "| Holdout | A | Weight A | B | Train Brier |", "| :--- | :--- | :--- | :--- | :--- |"])
        for config in market_informed["configs"]:
            lines.append(
                f"| {config['holdout']} | {candidate_label(config['candidate_a'])} | "
                f"{fmt_num(config['weight_a'], 2)} | {candidate_label(config['candidate_b'])} | "
                f"{fmt_num(config['train_brier'])} |"
            )
    lines.extend([
        "",
        "## Standalone By Cutoff",
        "",
        "| Forecaster | Cutoff | Rows | Brier | LogLoss | Base rate |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for candidate in available_candidates(rows, include_market=True):
        for item in grouped_scores(rows, candidate, "cutoff_hour"):
            lines.append(
                f"| {candidate_label(candidate)} | {item['group']} | {item['n']} | "
                f"{fmt_num(item['brier'])} | {fmt_num(item['logloss'])} | "
                f"{fmt_num(item['base_rate'])} |"
            )
    lines.extend([
        "",
        "## Standalone By Market-Bin Type",
        "",
        "| Forecaster | Bin type | Rows | Brier | LogLoss | Base rate |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for candidate in available_candidates(rows, include_market=True):
        for item in grouped_scores(rows, candidate, "bin_type"):
            lines.append(
                f"| {candidate_label(candidate)} | {item['group']} | {item['n']} | "
                f"{fmt_num(item['brier'])} | {fmt_num(item['logloss'])} | "
                f"{fmt_num(item['base_rate'])} |"
            )
    lines.extend([
        "",
        "Promotion guardrail: do not promote an ensemble unless it improves the no-market score on clean leave-one-day validation and the market-informed score is reported separately.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_ensemble(
    folders,
    daily_summary_path=DEFAULT_DAILY_SUMMARY,
    quality_grades=None,
    report_path=DEFAULT_REPORT_PATH,
    max_rows=None,
):
    rows, metadata = load_scored_rows(
        folders,
        daily_summary_path=daily_summary_path,
        quality_grades=quality_grades,
        max_rows=max_rows,
    )
    no_market_candidates = available_candidates(rows, include_market=False)
    market_candidates = available_candidates(rows, include_market=True)
    no_market = leave_one_day_ensemble(rows, no_market_candidates)
    market_informed = leave_one_day_ensemble(rows, market_candidates)
    write_report(report_path, rows, metadata, no_market, market_informed, max_rows=max_rows)
    return {
        "rows": rows,
        "metadata": metadata,
        "no_market": no_market,
        "market_informed": market_informed,
        "report_path": str(report_path),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score model components and simple ensembles.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders. Defaults to settled Toronto tapes.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    parser.add_argument("--quality-grades", default="complete,manual_override")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--max-rows", type=int, default=None, help="Deterministic row cap for fast research runs.")
    args = parser.parse_args(argv)

    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    quality_grades = [
        item.strip() for item in str(args.quality_grades).split(",")
        if item.strip()
    ]
    result = run_ensemble(
        folders,
        daily_summary_path=args.daily_summary,
        quality_grades=quality_grades,
        report_path=args.report,
        max_rows=args.max_rows,
    )
    print(f"Wrote ensemble report to {result['report_path']}")
    print(f"Rows scored: {len(result['rows'])}")
    if not result["no_market"]:
        print("No-market ensemble: insufficient clean days or candidates.")
    if not result["market_informed"]:
        print("Market-informed ensemble: insufficient clean days or candidates.")


if __name__ == "__main__":
    main()
