"""Pure scoring and aggregation helpers shared across backtests and reports."""

from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd


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


def brier(p, y):
    return (p - y) ** 2


def binary_log_loss(p, y):
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


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


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def winner_band_catchup(rows):
    """Model-vs-market recognition of the realized winning band."""
    winners = [row for row in rows if row.get("outcome") == 1]
    n = len(winners)
    if not n:
        return {
            "winner_rows": 0,
            "winner_model_probability": None,
            "winner_market_probability": None,
            "winner_catchup_gap": None,
            "winner_catchup_rate": None,
            "winner_model_over_50_rate": None,
            "winner_market_over_50_rate": None,
        }

    model_probability = _mean(row["model_probability"] for row in winners)
    market_probability = _mean(row["market_yes"] for row in winners)
    return {
        "winner_rows": n,
        "winner_model_probability": model_probability,
        "winner_market_probability": market_probability,
        "winner_catchup_gap": (
            model_probability - market_probability
            if model_probability is not None and market_probability is not None
            else None
        ),
        "winner_catchup_rate": (
            sum(
                1
                for row in winners
                if row["model_probability"] >= row["market_yes"]
            )
            / n
        ),
        "winner_model_over_50_rate": (
            sum(1 for row in winners if row["model_probability"] > 0.5) / n
        ),
        "winner_market_over_50_rate": (
            sum(1 for row in winners if row["market_yes"] > 0.5) / n
        ),
    }


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


def group_sort_key(value):
    if value is None:
        return (3, "")
    if isinstance(value, (int, float)):
        return (0, float(value))
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def unique_sorted(values):
    cleaned = sorted({str(v) for v in values if not missing(v) and str(v) != ""})
    return cleaned


def grouped_reliability(rows, prob_key, group_key, n_bins=5):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        for rel in reliability(group_rows, prob_key, n_bins=n_bins):
            output.append({"group": group, **rel})
    return output


def daily_first_score(day_results):
    """Equal-weight market days before averaging metrics."""
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
