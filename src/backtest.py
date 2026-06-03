"""Settlement-scored backtest: score the model AND the market against the
realized WU settlement for each captured market day.

This answers the question model calibration alone cannot: does the model have
edge *over the market price*? It scores recorded snapshot tapes, which hold both
model probabilities and market yes-prices, against the realized settlement
bucket.

Settlement is the crux. The market resolves on the WU CYYZ printed daily high,
so the realized bucket is taken from the day's maximum captured
``wu_history_high_c`` (half-up rounded), cross-checked against the local daily
summary and overridable on the command line. Disagreements are reported, not
hidden.

CLI:
  python -m src.backtest [folder ...]
      [--snapshots-root data/snapshots]
      [--settle YYYY-MM-DD=BUCKET ...]   # force settlement for a date
      [--thresholds 0.05,0.10,0.15]
      [--fixed-cutoffs 9,10,12,13,15,16,17,18,20]
      [--out data/backtest/backtest_report.md]
"""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from feature_store import FEATURE_COLUMNS
from market_config import date_from_event_slug

DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_DAILY_SUMMARY = Path("data") / "wunderground" / "cyyz" / "daily" / "daily_summary.csv"
DEFAULT_OUT = Path("data") / "backtest" / "backtest_report.md"
DEFAULT_FIXED_CUTOFF_HOURS = (9, 10, 12, 13, 15, 16, 17, 18, 20)
COMPLETE_DAY_MIN_ROWS = 18  # daily summary is trusted as settlement only when this full


def round_half_up(value):
    if value is None:
        return None
    try:
        return int(math.floor(float(value) + 0.5))
    except (TypeError, ValueError):
        return None


def resolve_outcome(kind, value, settlement_bucket):
    """Did this market band resolve YES (1) or NO (0) given settlement?"""
    if settlement_bucket is None or kind is None or value is None:
        return None
    value = int(value)
    settlement_bucket = int(settlement_bucket)
    if kind == "lte":      # "X C or below"
        return 1 if settlement_bucket <= value else 0
    if kind == "gte":      # "X C or higher"
        return 1 if settlement_bucket >= value else 0
    return 1 if settlement_bucket == value else 0  # exact "X C"


def brier(p, y):
    return (p - y) ** 2


def binary_log_loss(p, y):
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def load_daily_summary(path):
    """date -> (bucket, row_count) from the WU daily summary, if present."""
    index = {}
    if not Path(path).exists():
        return index
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            d = row.get("local_date")
            bucket = row.get("max_temp_bucket_c")
            if not d or not bucket:
                continue
            try:
                index[d] = (int(float(bucket)), int(row.get("row_count") or 0))
            except (TypeError, ValueError):
                continue
    return index


def settlement_for_tape(df, target_date, daily_index, overrides):
    """Return (bucket, source, note).

    Precedence: explicit override > complete daily summary > day's max captured
    wu_history_high_c. Snapshot highs are used when the current-day daily
    summary is missing or incomplete.
    """
    iso = target_date.isoformat() if target_date else None
    snapshot_high = None
    if "wu_history_high_c" in df:
        snapshot_high = round_half_up(pd.to_numeric(df["wu_history_high_c"], errors="coerce").max())
    summary = daily_index.get(iso)

    note_bits = []
    if summary is not None and snapshot_high is not None and summary[0] != snapshot_high:
        note_bits.append(
            f"daily_summary={summary[0]} (rows={summary[1]}) disagrees with snapshot high={snapshot_high}"
        )

    if iso in overrides:
        return overrides[iso], "override", "; ".join(note_bits) or "manual override"
    if summary is not None and summary[1] >= COMPLETE_DAY_MIN_ROWS:
        return summary[0], "daily_summary", "; ".join(note_bits)
    if snapshot_high is not None:
        reason = "snapshot wu_history_high (daily summary missing/incomplete)"
        return snapshot_high, "snapshot_high", "; ".join(note_bits) or reason
    if summary is not None:
        return summary[0], "daily_summary(sparse)", "; ".join(note_bits)
    return None, "none", "no settlement available"


def missing(value):
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def safe_float(value):
    if missing(value) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_snapshot_time(value):
    if missing(value) or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def capture_minute(value):
    parsed = parse_snapshot_time(value)
    if not parsed:
        return None
    return parsed.hour * 60 + parsed.minute


def capture_hour(value):
    minute = capture_minute(value)
    if minute is None:
        return None
    return minute // 60


def timestamp_key(row):
    parsed = parse_snapshot_time(row.get("captured_at_local"))
    if parsed is not None:
        return parsed.timestamp()
    return float(row.get("row_order") or 0)


def bin_type(kind):
    if kind == "lte":
        return "lte"
    if kind == "gte":
        return "gte"
    return "eq"


def unique_sorted(values):
    cleaned = sorted({str(v) for v in values if not missing(v) and str(v) != ""})
    return cleaned


def score_rows(rows):
    """Brier + log loss for model and market over scored row dicts."""
    n = len(rows)
    if not n:
        return None
    out = {
        "n": n,
        "model_brier": sum(brier(r["model_probability"], r["outcome"]) for r in rows) / n,
        "market_brier": sum(brier(r["market_yes"], r["outcome"]) for r in rows) / n,
        "model_logloss": sum(binary_log_loss(r["model_probability"], r["outcome"]) for r in rows) / n,
        "market_logloss": sum(binary_log_loss(r["market_yes"], r["outcome"]) for r in rows) / n,
        "base_rate": sum(r["outcome"] for r in rows) / n,
    }
    out["brier_delta"] = out["market_brier"] - out["model_brier"]
    out["logloss_delta"] = out["market_logloss"] - out["model_logloss"]
    out["brier_skill_score"] = (
        1.0 - out["model_brier"] / out["market_brier"] if out["market_brier"] > 0 else 0.0
    )
    return out


def reliability(rows, prob_key, n_bins=5):
    """Reliability table: per confidence bin, mean predicted vs realized."""
    bins = [[] for _ in range(n_bins)]
    for r in rows:
        p = r[prob_key]
        idx = min(n_bins - 1, int(max(0.0, min(0.999999, p)) * n_bins))
        bins[idx].append((p, r["outcome"]))
    table = []
    for i, b in enumerate(bins):
        if not b:
            continue
        table.append({
            "bin": f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}",
            "n": len(b),
            "pred": sum(p for p, _ in b) / len(b),
            "actual": sum(y for _, y in b) / len(b),
        })
    return table


def expected_calibration_error(rows, prob_key, n_bins=5):
    table = reliability(rows, prob_key, n_bins=n_bins)
    n = sum(row["n"] for row in table)
    if n <= 0:
        return None
    return sum((row["n"] / n) * abs(row["pred"] - row["actual"]) for row in table)


def grouped_reliability(rows, prob_key, group_key, n_bins=5):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        for rel in reliability(group_rows, prob_key, n_bins=n_bins):
            output.append({"group": group, **rel})
    return output


def pnl_trades(trades):
    """Aggregate per-trade P&L (in [-1, 1] units of one share)."""
    n = len(trades)
    if not n:
        return {"n": 0, "pnl": 0.0, "avg": 0.0, "hit_rate": 0.0}
    total = sum(t for t in trades)
    wins = sum(1 for t in trades if t > 0)
    return {"n": n, "pnl": total, "avg": total / n, "hit_rate": wins / n}


def trade_pnl(model_p, market_yes, market_no, outcome, threshold):
    """P&L of taking model edge on one band, held to resolution.

    Returns None if the edge is below threshold.
    """
    edge = model_p - market_yes
    if edge > threshold:                      # model thinks YES underpriced -> buy YES
        return outcome - market_yes
    if edge < -threshold:                     # model thinks YES overpriced -> buy NO
        cost_no = market_no if market_no is not None and not pd.isna(market_no) else (1.0 - market_yes)
        return (1 - outcome) - cost_no
    return None


def pnl_for_rows(rows, thresholds):
    out = {}
    for threshold in thresholds:
        trades = [
            trade_pnl(
                row["model_probability"],
                row["market_yes"],
                row.get("market_no"),
                row["outcome"],
                threshold,
            )
            for row in rows
        ]
        out[threshold] = pnl_trades([trade for trade in trades if trade is not None])
    return out


def merge_pnl(parts):
    n = sum(p["n"] for p in parts)
    pnl = sum(p["pnl"] for p in parts)
    return {
        "n": n,
        "pnl": pnl,
        "hit_rate": (sum(p["hit_rate"] * p["n"] for p in parts) / n) if n else 0.0,
        "avg": (pnl / n) if n else 0.0,
    }


def last_pre_close_rows(rows):
    """One row per target day and market band: the last available snapshot."""
    latest = {}
    for row in rows:
        key = (row.get("target_date"), row.get("band"))
        if key not in latest or timestamp_key(row) >= timestamp_key(latest[key]):
            latest[key] = row
    return [latest[key] for key in sorted(latest, key=lambda item: (str(item[0]), str(item[1])))]


def fixed_cutoff_rows(rows, fixed_cutoffs=DEFAULT_FIXED_CUTOFF_HOURS):
    """For each cutoff hour, pick the first row at/after that cutoff per day-band."""
    by_day_band = defaultdict(list)
    for row in rows:
        by_day_band[(row.get("target_date"), row.get("band"))].append(row)
    for group_rows in by_day_band.values():
        group_rows.sort(key=timestamp_key)

    selected = {int(cutoff): [] for cutoff in fixed_cutoffs}
    for group_rows in by_day_band.values():
        for cutoff in selected:
            cutoff_minute = int(cutoff) * 60
            candidates = [
                row for row in group_rows
                if row.get("capture_minute") is not None
                and row["capture_minute"] >= cutoff_minute
            ]
            if candidates:
                selected[cutoff].append(candidates[0])
    return selected


def grouped_scores(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        score = score_rows(group_rows)
        if score:
            output.append({"group": group, **score})
    return output


def group_sort_key(value):
    if value is None:
        return (1, "")
    if isinstance(value, (int, float)):
        return (0, value)
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, str(value))


def daily_first_score(day_results):
    """Equal-weight market days before averaging metrics.

    This keeps days with many snapshots from dominating the headline score. It
    still uses all rows inside each day, so last-pre-close and fixed-cutoff
    sections provide stricter one-row-per-day-band views.
    """
    scores = [day.get("score") for day in day_results if day.get("score")]
    if not scores:
        return None

    def avg(key):
        return sum(score[key] for score in scores) / len(scores)

    out = {
        "n_days": len(scores),
        "n": sum(score["n"] for score in scores),
        "model_brier": avg("model_brier"),
        "market_brier": avg("market_brier"),
        "model_logloss": avg("model_logloss"),
        "market_logloss": avg("market_logloss"),
        "base_rate": avg("base_rate"),
    }
    out["brier_delta"] = out["market_brier"] - out["model_brier"]
    out["logloss_delta"] = out["market_logloss"] - out["model_logloss"]
    out["brier_skill_score"] = (
        1.0 - out["model_brier"] / out["market_brier"] if out["market_brier"] > 0 else 0.0
    )
    return out


def feature_gap_bucket(value):
    value = safe_float(value)
    if value is None:
        return "missing"
    if value <= 0:
        return "<=0C"
    if value <= 2:
        return "0-2C"
    return ">2C"


def load_feature_vectors(folder):
    path = Path(folder) / "features_long.csv"
    if not path.exists():
        return {}
    try:
        features = pd.read_csv(path)
    except Exception:
        return {}
    if "snapshot_id" not in features:
        return {}
    out = {}
    for _, row in features.iterrows():
        snapshot_id = row.get("snapshot_id")
        if missing(snapshot_id):
            continue
        out[str(snapshot_id)] = row.to_dict()
    return out


def attach_feature_vector(scoring_row, feature_row):
    if not feature_row:
        scoring_row["feature_schema_version"] = None
        scoring_row["feature_forecast_gap_bucket"] = "missing"
        return scoring_row
    scoring_row["feature_schema_version"] = feature_row.get("feature_schema_version")
    for column in FEATURE_COLUMNS:
        scoring_row[f"feature_{column}"] = feature_row.get(column)
    scoring_row["feature_forecast_gap_bucket"] = feature_gap_bucket(feature_row.get("forecast_gap"))
    return scoring_row


def backtest_tape(df, settlement_bucket, thresholds, target_date=None, feature_index=None):
    """Score one market day's tape.

    Returns per-row scoring rows, per-threshold P&L (per-snapshot and
    first-entry), and persistence per band.
    """
    rows = []
    target_date_value = target_date.isoformat() if target_date else None
    for row_order, (_, r) in enumerate(df.iterrows()):
        mp = safe_float(r.get("model_probability"))
        my = safe_float(r.get("market_yes"))
        if mp is None or my is None:
            continue
        outcome = resolve_outcome(r.get("bin_kind"), r.get("bin_value_c"), settlement_bucket)
        if outcome is None:
            continue
        captured_at = r.get("captured_at_local")
        minute = capture_minute(captured_at)
        event_slug = r.get("event_slug")
        if target_date_value is None:
            inferred = date_from_event_slug(event_slug) if not missing(event_slug) else None
            target_date_value = inferred.isoformat() if inferred else None
        scoring_row = {
            "row_order": row_order,
            "snapshot_id": r.get("snapshot_id"),
            "target_date": target_date_value,
            "event_slug": event_slug,
            "captured_at_local": captured_at,
            "capture_minute": minute,
            "cutoff_hour": minute // 60 if minute is not None else None,
            "model_version": r.get("model_version"),
            "band": r.get("range_label"),
            "bin_kind": r.get("bin_kind"),
            "bin_type": bin_type(r.get("bin_kind")),
            "bin_value_c": safe_float(r.get("bin_value_c")),
            "model_probability": mp,
            "market_yes": my,
            "market_no": safe_float(r.get("market_no")),
            "outcome": int(outcome),
        }
        attach_feature_vector(
            scoring_row,
            (feature_index or {}).get(str(r.get("snapshot_id"))),
        )
        rows.append(scoring_row)

    per_snapshot = pnl_for_rows(rows, thresholds)

    first_entry = {}
    for threshold in thresholds:
        seen, entries = set(), []
        for row in rows:
            key = (row.get("target_date"), row.get("band"))
            if key in seen:
                continue
            trade = trade_pnl(
                row["model_probability"],
                row["market_yes"],
                row.get("market_no"),
                row["outcome"],
                threshold,
            )
            if trade is not None:
                entries.append(trade)
                seen.add(key)
        first_entry[threshold] = pnl_trades(entries)

    # Persistence per band (using the smallest threshold).
    thr0 = min(thresholds)
    persistence = []
    for band in sorted({r["band"] for r in rows}):
        band_rows = [r for r in rows if r["band"] == band]
        edges = [r["model_probability"] - r["market_yes"] for r in band_rows]
        outcome = band_rows[0]["outcome"]
        frac_pos = sum(1 for edge in edges if edge > thr0) / len(edges)
        frac_neg = sum(1 for edge in edges if edge < -thr0) / len(edges)
        mean_edge = sum(edges) / len(edges)
        persistence.append({
            "band": band,
            "snapshots": len(band_rows),
            "mean_edge": mean_edge,
            "frac_edge_up": frac_pos,
            "frac_edge_down": frac_neg,
            "settled_yes": outcome,
        })
    return rows, per_snapshot, first_entry, persistence


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def fmt_num(value, decimals=4):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}"


def fmt_signed(value, decimals=4):
    if value is None:
        return "-"
    return f"{float(value):+.{decimals}f}"


def fmt_group(value):
    if value is None or value == "":
        return "-"
    return str(value)


def fmt_pnl(value):
    return f"{float(value):+.2f}"


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def score_table_rows(items):
    rows = []
    for label, score in items:
        if not score:
            continue
        rows.append([
            label,
            score.get("n_days", "-"),
            score.get("n", "-"),
            fmt_num(score.get("model_brier")),
            fmt_num(score.get("market_brier")),
            fmt_signed(score.get("brier_delta")),
            fmt_signed(score.get("brier_skill_score"), 3),
            fmt_num(score.get("model_logloss")),
            fmt_num(score.get("market_logloss")),
            fmt_signed(score.get("logloss_delta")),
            fmt_pct(score.get("base_rate")),
        ])
    return rows


def grouped_score_table_rows(items):
    return [
        [
            fmt_group(item.get("group")),
            item.get("n", "-"),
            fmt_num(item.get("model_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("brier_skill_score"), 3),
            fmt_num(item.get("model_logloss")),
            fmt_num(item.get("market_logloss")),
            fmt_signed(item.get("logloss_delta")),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def feature_vector_coverage(rows):
    total = len(rows)
    with_features = [
        row for row in rows
        if not missing(row.get("feature_schema_version"))
    ]
    schema_versions = unique_sorted(row.get("feature_schema_version") for row in with_features)
    return {
        "rows": total,
        "rows_with_features": len(with_features),
        "coverage": len(with_features) / total if total else None,
        "schema_versions": schema_versions,
    }


def reliability_table_rows(items):
    return [
        [
            fmt_group(item.get("group")),
            item.get("bin", "-"),
            item.get("n", "-"),
            fmt_pct(item.get("pred")),
            fmt_pct(item.get("actual")),
        ]
        for item in items
    ]


def collect_model_card(results):
    aggregate = results.get("aggregate_score") or {}
    daily = results.get("daily_first_score") or {}
    model_ece = expected_calibration_error(results.get("all_rows", []), "model_probability")
    market_ece = expected_calibration_error(results.get("all_rows", []), "market_yes")
    return {
        "market_days": len(results.get("days", [])),
        "band_rows": results.get("total_rows", 0),
        "model_versions": ", ".join(results.get("model_versions") or []) or "-",
        "all_snapshot_skill": aggregate.get("brier_skill_score"),
        "daily_first_skill": daily.get("brier_skill_score"),
        "logloss_delta": aggregate.get("logloss_delta"),
        "model_ece": model_ece,
        "market_ece": market_ece,
    }


def write_report(results, out_path, thresholds):
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    model_card = collect_model_card(results)
    lines = [
        "# Settlement-Scored Backtest",
        "",
        f"Generated: {generated}",
        "",
        (
            f"Market days: {len(results['days'])}  |  "
            f"Total band-rows scored: {results['total_rows']}"
        ),
        f"Quality filter: {', '.join(results.get('quality_filter') or ['all'])}",
        "",
        "> Model resolution = WU CYYZ printed daily high. Results over a handful of",
        "> market days are illustrative, not conclusive. Intraday snapshots from the",
        "> same day are correlated, so use the daily-first, last-pre-close, and",
        "> fixed-cutoff sections as the safer accuracy gates.",
        "",
        "## Model Card",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Market days", model_card["market_days"]],
            ["All-snapshot band rows", model_card["band_rows"]],
            ["Model versions", model_card["model_versions"]],
            ["All-snapshot Brier skill vs market", fmt_signed(model_card["all_snapshot_skill"], 3)],
            ["Daily-first Brier skill vs market", fmt_signed(model_card["daily_first_skill"], 3)],
            ["All-snapshot log-loss delta (market - model)", fmt_signed(model_card["logloss_delta"])],
            ["Model ECE", fmt_num(model_card["model_ece"])],
            ["Market ECE", fmt_num(model_card["market_ece"])],
        ],
    )

    lines += [
        "",
        "## Run Inputs And Settlement",
        "",
    ]
    lines += markdown_table(
        [
            "Date",
            "Snapshot tape",
            "Snapshots",
            "Bands",
            "Model versions",
            "Settlement",
            "Source",
            "Quality",
            "Note",
        ],
        [
            [
                day["date"],
                day["tape_path"],
                day["snapshot_count"],
                day["band_count"],
                ", ".join(day.get("model_versions") or []) or "-",
                f"{day['settlement']} C" if day["settlement"] is not None else "-",
                day["source"],
                day.get("quality_grade") or "-",
                day["note"] or "-",
            ]
            for day in results["days"]
        ],
    )

    feature_coverage = results.get("feature_vector_coverage") or {}
    lines += [
        "",
        "## Feature Vector Coverage",
        "",
    ]
    lines += markdown_table(
        ["Rows", "Rows with features", "Coverage", "Feature schemas"],
        [[
            feature_coverage.get("rows", 0),
            feature_coverage.get("rows_with_features", 0),
            fmt_pct(feature_coverage.get("coverage")),
            ", ".join(feature_coverage.get("schema_versions") or []) or "-",
        ]],
    )
    if feature_coverage.get("rows_with_features"):
        lines += [
            "",
            "### Score By Forecast Gap Feature",
            "",
        ]
        lines += markdown_table(
            [
                "Forecast Gap",
                "Rows",
                "Model Brier",
                "Market Brier",
                "Brier Skill",
                "Model LogLoss",
                "Market LogLoss",
                "LogLoss Delta",
                "Base Rate",
            ],
            grouped_score_table_rows(results.get("score_by_feature_forecast_gap") or []),
        )

    lines += [
        "",
        "## Score Summary",
        "",
    ]
    lines += markdown_table(
        [
            "Scope",
            "Days",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        score_table_rows([
            ("All snapshots", results.get("aggregate_score")),
            ("Daily-first equal-day average", results.get("daily_first_score")),
            ("Last pre-close", results.get("last_pre_close_score")),
        ]),
    )

    lines += [
        "",
        "## Model Vs Market By Target Day",
        "",
    ]
    lines += markdown_table(
        [
            "Date",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        grouped_score_table_rows(results.get("score_by_day", [])),
    )

    lines += [
        "",
        "## Model Vs Market By Capture Hour",
        "",
    ]
    lines += markdown_table(
        [
            "Hour",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        grouped_score_table_rows(results.get("score_by_cutoff", [])),
    )

    lines += [
        "",
        "## Model Vs Market By Market-Bin Type",
        "",
    ]
    lines += markdown_table(
        [
            "Bin Type",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        grouped_score_table_rows(results.get("score_by_bin_type", [])),
    )

    lines += [
        "",
        "## Fixed-Cutoff Performance",
        "",
        "Each row uses the first available snapshot at or after the cutoff hour for each day-band.",
        "",
    ]
    lines += markdown_table(
        [
            "Cutoff",
            "Rows",
            "Model Brier",
            "Market Brier",
            "Brier Skill",
            "Model LogLoss",
            "Market LogLoss",
            "LogLoss Delta",
            "Base Rate",
        ],
        [
            [
                f"{cutoff:02d}:00",
                score.get("n", "-"),
                fmt_num(score.get("model_brier")),
                fmt_num(score.get("market_brier")),
                fmt_signed(score.get("brier_skill_score"), 3),
                fmt_num(score.get("model_logloss")),
                fmt_num(score.get("market_logloss")),
                fmt_signed(score.get("logloss_delta")),
                fmt_pct(score.get("base_rate")),
            ]
            for cutoff, score in results.get("fixed_cutoff_scores", {}).items()
            if score
        ],
    )

    lines += [
        "",
        "## Realized Edge / P&L",
        "",
        "P&L is in shares (max +1 / -1 each). Per-snapshot overcounts correlated",
        "intraday signals; first-entry takes one trade per day-band at the first",
        "threshold crossing; last-pre-close takes one trade per day-band at the",
        "last available snapshot.",
        "",
    ]
    lines += markdown_table(
        [
            "Threshold",
            "Per-snapshot trades",
            "Per-snapshot P&L",
            "First-entry trades",
            "First-entry P&L",
            "Last-pre-close trades",
            "Last-pre-close P&L",
        ],
        [
            [
                f"{threshold:.2f}",
                results["pnl_per_snapshot"][threshold]["n"],
                fmt_pnl(results["pnl_per_snapshot"][threshold]["pnl"]),
                results["pnl_first_entry"][threshold]["n"],
                fmt_pnl(results["pnl_first_entry"][threshold]["pnl"]),
                results["pnl_last_pre_close"][threshold]["n"],
                fmt_pnl(results["pnl_last_pre_close"][threshold]["pnl"]),
            ]
            for threshold in thresholds
        ],
    )

    lines += [
        "",
        "## Overall Reliability",
        "",
    ]
    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        lines += [
            f"### {label} Reliability",
            "",
        ]
        lines += markdown_table(
            ["Confidence bin", "N", "Mean predicted", "Realized"],
            [
                [row["bin"], row["n"], fmt_pct(row["pred"]), fmt_pct(row["actual"])]
                for row in reliability(results["all_rows"], key)
            ],
        )
        lines.append("")

    lines += [
        "## Reliability By Capture Hour",
        "",
    ]
    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        lines += [
            f"### {label} By Hour",
            "",
        ]
        lines += markdown_table(
            ["Hour", "Confidence bin", "N", "Mean predicted", "Realized"],
            reliability_table_rows(grouped_reliability(results["all_rows"], key, "cutoff_hour")),
        )
        lines.append("")

    lines += [
        "## Reliability By Market Band",
        "",
    ]
    for label, key in [("Model", "model_probability"), ("Market", "market_yes")]:
        lines += [
            f"### {label} By Band",
            "",
        ]
        lines += markdown_table(
            ["Band", "Confidence bin", "N", "Mean predicted", "Realized"],
            reliability_table_rows(grouped_reliability(results["all_rows"], key, "band")),
        )
        lines.append("")

    lines += [
        "## Edge Persistence Per Band",
        "",
    ]
    lines += markdown_table(
        ["Date", "Band", "Snapshots", "Mean edge", "% edge up", "% edge down", "Settled YES?"],
        [
            [
                day["date"],
                item["band"],
                item["snapshots"],
                f"{item['mean_edge']:+.2f}",
                fmt_pct(item["frac_edge_up"]),
                fmt_pct(item["frac_edge_down"]),
                item["settled_yes"],
            ]
            for day in results["days"]
            for item in day["persistence"]
        ],
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_backtest(
    folders,
    daily_summary_path,
    overrides,
    thresholds,
    out_path,
    fixed_cutoffs=DEFAULT_FIXED_CUTOFF_HOURS,
    quality_grades=None,
):
    daily_index = load_daily_summary(daily_summary_path)
    allowed_quality = set(quality_grades or [])
    days, all_rows = [], []
    pnl_ps = {threshold: [] for threshold in thresholds}
    pnl_fe = {threshold: [] for threshold in thresholds}

    for folder in folders:
        tape = Path(folder) / "snapshots_long.csv"
        if not tape.exists():
            print(f"  skip {folder}: no snapshots_long.csv")
            continue
        df = pd.read_csv(tape)
        slug = Path(folder).name
        target_date = date_from_event_slug(slug)
        label = load_market_day_label(Path(folder))
        grade = label.get("quality_grade") if label else "-"
        if allowed_quality and grade not in allowed_quality:
            print(f"  skip {slug}: quality {grade} not in {sorted(allowed_quality)}")
            continue
        feature_index = load_feature_vectors(folder)
        bucket, source, note = settlement_for_tape(df, target_date, daily_index, overrides)
        rows, per_snap, first_entry, persistence = backtest_tape(
            df,
            bucket,
            thresholds,
            target_date=target_date,
            feature_index=feature_index,
        )
        all_rows.extend(rows)
        for threshold in thresholds:
            pnl_ps[threshold].append(per_snap[threshold])
            pnl_fe[threshold].append(first_entry[threshold])

        day_score = score_rows(rows)
        model_versions = unique_sorted(df["model_version"]) if "model_version" in df else []
        snapshot_count = int(df["snapshot_id"].nunique()) if "snapshot_id" in df else 0
        band_count = int(df["range_label"].nunique()) if "range_label" in df else 0
        days.append({
            "date": target_date.isoformat() if target_date else slug,
            "event_slug": slug,
            "folder": str(Path(folder)),
            "tape_path": str(tape),
            "snapshot_count": snapshot_count,
            "band_count": band_count,
            "model_versions": model_versions,
            "settlement": bucket,
            "source": source,
            "note": note,
            "quality_grade": grade,
            "rows": len(rows),
            "score": day_score,
            "persistence": persistence,
        })
        print(f"  {slug}: settlement {bucket} C ({source}); {len(rows)} band-rows scored")

    last_rows = last_pre_close_rows(all_rows)
    fixed_rows = fixed_cutoff_rows(all_rows, fixed_cutoffs=fixed_cutoffs)

    results = {
        "days": days,
        "total_rows": len(all_rows),
        "all_rows": all_rows,
        "model_versions": unique_sorted(row.get("model_version") for row in all_rows),
        "aggregate_score": score_rows(all_rows),
        "daily_first_score": daily_first_score(days),
        "last_pre_close_score": score_rows(last_rows),
        "fixed_cutoff_scores": {
            cutoff: score_rows(rows)
            for cutoff, rows in fixed_rows.items()
        },
        "score_by_day": grouped_scores(all_rows, "target_date"),
        "score_by_cutoff": grouped_scores(all_rows, "cutoff_hour"),
        "score_by_bin_type": grouped_scores(all_rows, "bin_type"),
        "score_by_feature_forecast_gap": grouped_scores(all_rows, "feature_forecast_gap_bucket"),
        "feature_vector_coverage": feature_vector_coverage(all_rows),
        "pnl_per_snapshot": {threshold: merge_pnl(pnl_ps[threshold]) for threshold in thresholds},
        "pnl_first_entry": {threshold: merge_pnl(pnl_fe[threshold]) for threshold in thresholds},
        "pnl_last_pre_close": pnl_for_rows(last_rows, thresholds),
        "fixed_cutoffs": tuple(fixed_cutoffs),
        "quality_filter": sorted(allowed_quality),
    }
    write_report(results, out_path, thresholds)
    return results


def load_market_day_label(folder):
    path = Path(folder) / "settlement.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def parse_csv_numbers(value, type_fn=float):
    return [type_fn(item.strip()) for item in str(value).split(",") if item.strip()]


def main():
    parser = argparse.ArgumentParser(description="Settlement-scored model-vs-market backtest.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all under snapshots root).")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    parser.add_argument("--settle", action="append", default=[],
                        help="Force settlement: YYYY-MM-DD=BUCKET (repeatable).")
    parser.add_argument("--thresholds", default="0.05,0.10,0.15")
    parser.add_argument("--fixed-cutoffs", default=",".join(str(v) for v in DEFAULT_FIXED_CUTOFF_HOURS))
    parser.add_argument("--quality-grades", default="",
                        help="Comma-separated settlement label quality grades to include; empty includes all.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    overrides = {}
    for item in args.settle:
        d, _, b = item.partition("=")
        overrides[d.strip()] = int(b)
    thresholds = parse_csv_numbers(args.thresholds, float)
    fixed_cutoffs = parse_csv_numbers(args.fixed_cutoffs, int)
    quality_grades = [
        item.strip() for item in str(args.quality_grades).split(",")
        if item.strip()
    ]

    folders = args.folders
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Backtesting {len(folders)} market day(s)...")
    results = run_backtest(
        folders,
        args.daily_summary,
        overrides,
        thresholds,
        args.out,
        fixed_cutoffs=fixed_cutoffs,
        quality_grades=quality_grades,
    )
    agg = results["aggregate_score"]
    daily = results["daily_first_score"]
    if agg:
        print(
            f"\nAll-snapshot model Brier {agg['model_brier']:.4f} vs "
            f"market {agg['market_brier']:.4f} (skill {agg['brier_skill_score']:+.3f})"
        )
    if daily:
        print(
            f"Daily-first model Brier {daily['model_brier']:.4f} vs "
            f"market {daily['market_brier']:.4f} (skill {daily['brier_skill_score']:+.3f})"
        )
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
