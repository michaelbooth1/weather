"""Leakage-safe characterization of ex-ante severe model/market disagreement.

The severe label is evaluated after settlement.  Every candidate signal is
assembled from the captured replay row at its own timestamp; settlement is
used only for the label and loss.  The module deliberately fits no model.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "severe_tail_ex_ante_casebook_v0.1"
PROVENANCE_ANCHOR = date(2026, 7, 31)
STRATA = ("before_2026_07_31", "on_or_after_2026_07_31")
SEVERE_GAP_POINTS = 30.0
BOOTSTRAP_SEED = 932

REQUIRED_COLUMNS = {
    "band",
    "captured_at_local",
    "cutoff_hour",
    "feature_forecast_disagreement",
    "feature_forecast_high",
    "feature_forecast_source_count",
    "feature_high_so_far",
    "market_id",
    "market_yes",
    "outcome",
    "reconstructed",
    "replayed_p",
    "snapshot_id",
    "target_date",
}

INFORMATION_CUTOFFS = [
    {
        "signal": "market and cutoff hour",
        "cutoff": "effective WU-print cutoff retained on a row captured at captured_at_local",
        "enforcement": (
            "timestamp must be timezone-aware and map to the target date in the canonical market "
            "timezone; cutoff hour must be valid but may lag wall clock under the "
            "effective-WU-print contract"
        ),
    },
    {
        "signal": "forecast disagreement and forecast-source count",
        "cutoff": "features retained in the captured serving input at captured_at_local",
        "enforcement": "only exact, non-reconstructed replay rows are admitted",
    },
    {
        "signal": "distance between high_so_far and forecast_high",
        "cutoff": "both values retained in the same captured serving input",
        "enforcement": "computed only when both captured values are present",
    },
    {
        "signal": "model width and entropy",
        "cutoff": "replayed distribution emitted from the captured serving input",
        "enforcement": "computed across the row's complete band partition before settlement is joined",
    },
    {
        "signal": "market quote structure and model/market disagreement",
        "cutoff": "market_yes values on the same captured snapshot",
        "enforcement": "computed across the same timestamped band partition",
    },
]


def _as_float(value):
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_int(value):
    parsed = _as_float(value)
    return None if parsed is None else int(parsed)


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _safe_ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _percentile(values, probability):
    ordered = sorted(value for value in values if value is not None and math.isfinite(value))
    if not ordered:
        return None
    position = probability * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stratum_accepts(target_date, stratum):
    if stratum not in STRATA:
        raise ValueError(f"unknown provenance stratum: {stratum}")
    before = target_date < PROVENANCE_ANCHOR
    return before if stratum == STRATA[0] else not before


def load_current_settlement_index(settlements_root):
    """Read append-only ledgers while retaining only each event's current label."""

    root = Path(settlements_root)
    selected = {}
    raw_count = 0
    raw_reported_band_rows = 0
    raw_reported_snapshots = 0
    invalid_count = 0
    for path in sorted(root.glob("*/ledger.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle):
                if not line.strip():
                    continue
                raw_count += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    invalid_count += 1
                    continue
                slug = str(row.get("event_slug") or "")
                if not slug:
                    invalid_count += 1
                    continue
                try:
                    revision = int(row.get("revision_number") or 0)
                except (TypeError, ValueError):
                    revision = 0
                rank = (revision, line_number)
                previous = selected.get(slug)
                if previous is None or rank >= previous[0]:
                    selected[slug] = (
                        rank,
                        {
                            "event_slug": slug,
                            "market_id": str(row.get("market_id") or path.parent.name),
                            "target_date": str(row.get("target_date") or ""),
                            "promotion_countable": row.get("promotion_countable") is True,
                            "promotion_countable_reason": row.get("promotion_countable_reason"),
                            "quality_grade": row.get("quality_grade"),
                            "revision_number": revision,
                            "reported_band_row_count": _as_int(row.get("row_count")) or 0,
                            "reported_snapshot_count": _as_int(row.get("snapshot_count")) or 0,
                        },
                    )
                raw_reported_band_rows += _as_int(row.get("row_count")) or 0
                raw_reported_snapshots += _as_int(row.get("snapshot_count")) or 0

    by_market_date = {}
    for _, row in selected.values():
        key = (row["market_id"], row["target_date"])
        if key in by_market_date and by_market_date[key]["event_slug"] != row["event_slug"]:
            raise ValueError(f"ambiguous current settlement labels for {key}")
        by_market_date[key] = row
    return by_market_date, {
        "raw_ledger_record_count": raw_count,
        "raw_ledger_reported_band_row_sum": raw_reported_band_rows,
        "raw_ledger_reported_snapshot_sum": raw_reported_snapshots,
        "invalid_ledger_record_count": invalid_count,
        "current_event_label_count": len(selected),
        "current_event_reported_band_row_sum": sum(
            row["reported_band_row_count"] for _, row in selected.values()
        ),
        "current_event_reported_snapshot_sum": sum(
            row["reported_snapshot_count"] for _, row in selected.values()
        ),
        "current_promotion_countable_label_count": sum(
            row["promotion_countable"] for _, row in selected.values()
        ),
    }


def _normalized(values):
    total = sum(values)
    if total <= 0:
        return None
    return [value / total for value in values]


def _entropy(values):
    return -sum(value * math.log(value) for value in values if value > 0)


def _width(values):
    center = sum(index * value for index, value in enumerate(values))
    return math.sqrt(
        sum(value * (index - center) ** 2 for index, value in enumerate(values))
    )


def _constant(group, field):
    values = {str(row.get(field) or "") for row in group}
    if len(values) != 1:
        raise ValueError(f"snapshot has inconsistent {field}: {sorted(values)!r}")
    return next(iter(values))


def _snapshot_rows(group, *, settlement_index, stratum):
    # Lazy import lets --data-root bind weather.paths before market specs are
    # constructed in captured-input replay mode.
    from weather.market.market_registry import REGISTRY

    first = group[0]
    market_id = _constant(group, "market_id")
    target_text = _constant(group, "target_date")
    snapshot_id = _constant(group, "snapshot_id")
    captured_text = _constant(group, "captured_at_local")
    cutoff_hour = _as_int(_constant(group, "cutoff_hour"))
    try:
        target_date = date.fromisoformat(target_text)
        captured_at = datetime.fromisoformat(captured_text)
    except (TypeError, ValueError):
        return [], "undated_snapshot"
    if captured_at.utcoffset() is None:
        return [], "timezone_naive_snapshot"
    spec = REGISTRY.get(market_id)
    if spec is None:
        return [], "unknown_market_timezone"
    market_capture_date = captured_at.astimezone(ZoneInfo(spec.timezone)).date()
    if market_capture_date != target_date:
        return [], "cutoff_timestamp_mismatch"
    if cutoff_hour is None or not 0 <= cutoff_hour <= 23:
        return [], "invalid_cutoff_hour"
    if not _stratum_accepts(target_date, stratum):
        return [], "outside_provenance_stratum"
    if any(_truthy(row.get("reconstructed")) for row in group):
        return [], "reconstructed_snapshot"

    label = settlement_index.get((market_id, target_text))
    if label is None:
        return [], "missing_current_settlement_label"
    if not label["promotion_countable"]:
        return [], "settlement_not_promotion_countable"

    bands = [str(row.get("band") or "") for row in group]
    if len(set(bands)) != len(bands):
        return [], "duplicate_band"
    model = [_as_float(row.get("replayed_p")) for row in group]
    market = [_as_float(row.get("market_yes")) for row in group]
    outcomes = [_as_float(row.get("outcome")) for row in group]
    if any(value is None or value < 0 or value > 1 for value in model + market + outcomes):
        return [], "invalid_probability"
    model_norm = _normalized(model)
    market_norm = _normalized(market)
    if model_norm is None or market_norm is None or abs(sum(outcomes) - 1.0) > 1e-6:
        return [], "incomplete_band_partition"

    model_mode = max(range(len(group)), key=lambda index: model_norm[index])
    market_mode = max(range(len(group)), key=lambda index: market_norm[index])
    winner = max(range(len(group)), key=lambda index: outcomes[index])
    sorted_market = sorted(market_norm, reverse=True)
    forecast_high = _as_float(first.get("feature_forecast_high"))
    high_so_far = _as_float(first.get("feature_high_so_far"))
    snapshot = {
        "market_id": market_id,
        "target_date": target_text,
        "snapshot_id": snapshot_id,
        "captured_at_local": captured_text,
        "cutoff_hour": cutoff_hour,
        "forecast_disagreement": _as_float(first.get("feature_forecast_disagreement")),
        "forecast_source_count": _as_int(first.get("feature_forecast_source_count")),
        "forecast_high_distance": (
            abs(forecast_high - high_so_far)
            if forecast_high is not None and high_so_far is not None
            else None
        ),
        "model_entropy": _entropy(model_norm),
        "model_width": _width(model_norm),
        "market_entropy": _entropy(market_norm),
        "market_width": _width(market_norm),
        "market_modal_probability": market_norm[market_mode],
        "market_top_two_gap": sorted_market[0] - sorted_market[1],
        "model_market_tv": 0.5 * sum(
            abs(model_value - market_value)
            for model_value, market_value in zip(model_norm, market_norm)
        ),
        "snapshot_max_gap_points": max(
            abs(model_value - market_value) * 100.0
            for model_value, market_value in zip(model, market)
        ),
        "model_market_mode_agree": model_mode == market_mode,
        "model_mode_is_winner": model_mode == winner,
        "market_mode_is_winner": market_mode == winner,
    }
    compact = []
    for index, row in enumerate(group):
        excess = (model[index] - outcomes[index]) ** 2 - (
            market[index] - outcomes[index]
        ) ** 2
        signed_gap = (model[index] - market[index]) * 100.0
        compact.append(
            {
                **snapshot,
                "band": bands[index],
                "model_probability": model[index],
                "market_probability": market[index],
                "outcome": outcomes[index],
                "selected_gap_points": signed_gap,
                "selected_abs_gap_points": abs(signed_gap),
                "selected_is_market_mode": index == market_mode,
                "selected_is_model_mode": index == model_mode,
                "positive_excess_brier": max(excess, 0.0),
                "severe": excess > 0 and abs(signed_gap) + 1e-12 >= SEVERE_GAP_POINTS,
            }
        )
    return compact, None


def compact_replay_rows(raw_rows, *, settlement_index, stratum):
    """Group a replay export into compact, timestamp-validated band rows."""

    compact = []
    excluded = Counter()
    current_key = None
    group = []
    seen = set()

    def finish(rows):
        if not rows:
            return
        selected, reason = _snapshot_rows(
            rows, settlement_index=settlement_index, stratum=stratum
        )
        if reason:
            excluded[reason] += 1
        else:
            compact.extend(selected)

    for raw in raw_rows:
        key = (
            str(raw.get("market_id") or ""),
            str(raw.get("target_date") or ""),
            str(raw.get("snapshot_id") or ""),
        )
        if current_key is not None and key != current_key:
            finish(group)
            seen.add(current_key)
            group = []
        if key in seen:
            raise ValueError(f"replay rows are not contiguous for snapshot {key}")
        current_key = key
        group.append(raw)
    finish(group)
    return compact, dict(sorted(excluded.items()))


def load_replay_csv(path, *, settlement_index, stratum):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"replay CSV missing required columns: {sorted(missing)}")
        return compact_replay_rows(
            reader, settlement_index=settlement_index, stratum=stratum
        )


def _summarize(rows, *, baseline_rate=None, total_severe_loss=None):
    count = len(rows)
    severe_count = sum(row["severe"] for row in rows)
    severe_loss = sum(row.get("daily_weighted_severe_loss", 0.0) for row in rows)
    rate = _safe_ratio(severe_count, count)
    return {
        "row_count": count,
        "row_share": None,
        "severe_row_count": severe_count,
        "severe_rate": rate,
        "severe_rate_lift": (
            _safe_ratio(rate, baseline_rate)
            if rate is not None and baseline_rate is not None
            else None
        ),
        "severe_loss": severe_loss,
        "severe_loss_share": _safe_ratio(severe_loss, total_severe_loss),
    }


def _quantile_groups(rows, field, bins=5):
    values = sorted(row[field] for row in rows if row.get(field) is not None)
    if not values:
        return {"missing": list(rows)}
    cuts = []
    for index in range(1, bins):
        cuts.append(values[min(len(values) - 1, int(index * len(values) / bins))])
    cuts = sorted(set(cuts))
    groups = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if value is None:
            label = "missing"
        else:
            bucket = sum(value >= cut for cut in cuts)
            label = f"q{bucket + 1}"
        groups[label].append(row)
    return dict(groups)


def build_cross_tabs(rows, baseline):
    categorical = {
        "market": "market_id",
        "cutoff_hour": "cutoff_hour",
        "forecast_source_count": "forecast_source_count",
        "model_market_mode_agree": "model_market_mode_agree",
    }
    numeric = [
        "forecast_disagreement",
        "forecast_high_distance",
        "model_entropy",
        "model_width",
        "market_entropy",
        "market_width",
        "market_modal_probability",
        "market_top_two_gap",
        "model_market_tv",
        "selected_abs_gap_points",
    ]
    result = {}
    for dimension, field in categorical.items():
        groups = defaultdict(list)
        for row in rows:
            groups[str(row.get(field) if row.get(field) is not None else "missing")].append(row)
        result[dimension] = groups
    for field in numeric:
        result[field] = _quantile_groups(rows, field)

    rendered = {}
    total_rows = len(rows)
    for dimension, groups in result.items():
        items = []
        for value, group in sorted(groups.items(), key=lambda item: str(item[0])):
            summary = _summarize(
                group,
                baseline_rate=baseline["severe_rate"],
                total_severe_loss=baseline["severe_loss"],
            )
            summary["value"] = value
            summary["row_share"] = _safe_ratio(summary["row_count"], total_rows)
            summary["loss_capture_lift"] = _safe_ratio(
                summary["severe_loss_share"], summary["row_share"]
            )
            items.append(summary)
        rendered[dimension] = items
    return rendered


def _p0_structure(cross_tabs):
    screens = []
    for dimension, groups in cross_tabs.items():
        if dimension == "selected_abs_gap_points":
            continue
        eligible = [
            group for group in groups
            if group["row_share"] is not None and group["row_share"] >= 0.01
        ]
        if not eligible:
            continue
        best = max(
            eligible,
            key=lambda group: max(
                group.get("severe_rate_lift") or 0.0,
                group.get("loss_capture_lift") or 0.0,
            ),
        )
        material = max(
            best.get("severe_rate_lift") or 0.0,
            best.get("loss_capture_lift") or 0.0,
        ) >= 1.5
        screens.append(
            {
                "dimension": dimension,
                "strongest_value": best["value"],
                "severe_rate_lift": best["severe_rate_lift"],
                "loss_capture_lift": best["loss_capture_lift"],
                "material_descriptive_structure": material,
            }
        )
    return {
        "screen": screens,
        "structure_found": any(row["material_descriptive_structure"] for row in screens),
        "screen_definition": (
            "descriptive triage only: a >=1% support group reaches >=1.5x baseline "
            "severe-rate lift or loss-capture lift; definition-adjacent selected gap excluded"
        ),
    }


def _rule_specs(rows):
    rules = []
    for threshold in range(5, 55, 5):
        rules.append(("selected_band_gap", float(threshold), lambda row, t=threshold: row["selected_abs_gap_points"] >= t))
        rules.append(("snapshot_max_gap", float(threshold), lambda row, t=threshold: row["snapshot_max_gap_points"] >= t))
    for threshold in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
        rules.append(("snapshot_total_variation", threshold, lambda row, t=threshold: row["model_market_tv"] >= t))
    for threshold in (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        rules.append(("gap_30_and_market_modal_probability", threshold, lambda row, t=threshold: row["selected_abs_gap_points"] >= 30.0 and row["market_modal_probability"] >= t))
    for threshold in (0.00, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60):
        rules.append(("gap_30_and_market_top_two_gap", threshold, lambda row, t=threshold: row["selected_abs_gap_points"] >= 30.0 and row["market_top_two_gap"] >= t))
    quantile_fields = (
        "forecast_disagreement",
        "forecast_high_distance",
        "model_entropy",
        "model_width",
    )
    for field in quantile_fields:
        values = sorted(row[field] for row in rows if row.get(field) is not None)
        for probability in (0.20, 0.40, 0.60, 0.80):
            threshold = _percentile(values, probability)
            if threshold is not None:
                rules.append((field, threshold, lambda row, t=threshold, f=field: row.get(f) is not None and row[f] >= t))
    return rules


def _metric_values(totals):
    rows = totals["rows"]
    severe = totals["severe"]
    nonsevere = rows - severe
    flagged = totals["flagged"]
    flagged_severe = totals["flagged_severe"]
    flagged_nonsevere = flagged - flagged_severe
    unflagged = rows - flagged
    unflagged_severe = severe - flagged_severe
    precision = _safe_ratio(flagged_severe, flagged)
    unflagged_rate = _safe_ratio(unflagged_severe, unflagged)
    return {
        "row_flag_rate": _safe_ratio(flagged, rows),
        "severe_row_recall": _safe_ratio(flagged_severe, severe),
        "severe_loss_recall": _safe_ratio(totals["flagged_severe_loss"], totals["severe_loss"]),
        "nonsevere_flag_rate": _safe_ratio(flagged_nonsevere, nonsevere),
        "precision": precision,
        "risk_difference": (
            precision - unflagged_rate
            if precision is not None and unflagged_rate is not None
            else None
        ),
    }


def _crossed_intervals(cell_totals, *, replicates, seed):
    dates = sorted({key[0] for key in cell_totals})
    markets = sorted({key[1] for key in cell_totals})
    rng = random.Random(seed)
    draws = defaultdict(list)
    for _ in range(replicates):
        date_weights = Counter(rng.choices(dates, k=len(dates)))
        market_weights = Counter(rng.choices(markets, k=len(markets)))
        totals = defaultdict(float)
        for (target_date, market_id), cell in cell_totals.items():
            weight = date_weights[target_date] * market_weights[market_id]
            if not weight:
                continue
            for field, value in cell.items():
                totals[field] += weight * value
        for field, value in _metric_values(totals).items():
            if value is not None:
                draws[field].append(value)
    intervals = {
        field: [_percentile(values, 0.025), _percentile(values, 0.975)]
        for field, values in draws.items()
    }
    risk_draws = draws.get("risk_difference") or []
    power = None
    if len(risk_draws) >= 2:
        point = statistics.fmean(risk_draws)
        standard_error = statistics.stdev(risk_draws)
        if standard_error > 0:
            noncentrality = abs(point) / standard_error
            normal = statistics.NormalDist()
            power = (
                1.0 - normal.cdf(1.959963984540054 - noncentrality)
                + normal.cdf(-1.959963984540054 - noncentrality)
            )
    return intervals, power


def build_tradeoff_curve(rows, *, replicates=2000, seed=BOOTSTRAP_SEED):
    snapshot_total = len({(row["market_id"], row["target_date"], row["snapshot_id"]) for row in rows})
    day_total = len({(row["market_id"], row["target_date"]) for row in rows})
    result = []
    for rule_index, (family, threshold, predicate) in enumerate(_rule_specs(rows)):
        cells = defaultdict(lambda: defaultdict(float))
        flagged_snapshots = set()
        flagged_days = set()
        for row in rows:
            cell = cells[(row["target_date"], row["market_id"])]
            cell["rows"] += 1
            cell["severe"] += int(row["severe"])
            cell["severe_loss"] += row["daily_weighted_severe_loss"]
            flagged = bool(predicate(row))
            if flagged:
                cell["flagged"] += 1
                cell["flagged_severe"] += int(row["severe"])
                cell["flagged_severe_loss"] += row["daily_weighted_severe_loss"]
                flagged_snapshots.add((row["market_id"], row["target_date"], row["snapshot_id"]))
                flagged_days.add((row["market_id"], row["target_date"]))
        totals = defaultdict(float)
        for cell in cells.values():
            for field, value in cell.items():
                totals[field] += value
        metrics = _metric_values(totals)
        intervals, power = _crossed_intervals(
            cells, replicates=replicates, seed=seed + rule_index
        )
        risk_interval = intervals.get("risk_difference") or [None, None]
        result.append(
            {
                "rule_family": family,
                "threshold": threshold,
                **metrics,
                "snapshot_flag_rate": _safe_ratio(len(flagged_snapshots), snapshot_total),
                "market_day_flag_rate": _safe_ratio(len(flagged_days), day_total),
                "crossed_95_intervals": intervals,
                "risk_difference_distinguishable_from_zero": (
                    risk_interval[0] is not None
                    and (risk_interval[0] > 0 or risk_interval[1] < 0)
                ),
                "risk_difference_plugin_power": power,
            }
        )
    return result


def analyze_compact_rows(
    rows,
    *,
    settlement_inventory,
    source,
    excluded_snapshots=None,
    stratum,
    bootstrap_replicates=2000,
    bootstrap_seed=BOOTSTRAP_SEED,
):
    if not rows:
        raise ValueError("no leakage-safe, promotion-countable replay rows were admitted")
    day_counts = Counter((row["market_id"], row["target_date"]) for row in rows)
    for row in rows:
        weight = 1.0 / day_counts[(row["market_id"], row["target_date"])]
        row["daily_weighted_positive_excess"] = row["positive_excess_brier"] * weight
        row["daily_weighted_severe_loss"] = (
            row["daily_weighted_positive_excess"] if row["severe"] else 0.0
        )

    baseline = _summarize(rows)
    baseline["row_share"] = 1.0
    baseline["positive_excess_loss"] = sum(
        row["daily_weighted_positive_excess"] for row in rows
    )
    baseline["severe_loss_share_of_positive_excess"] = _safe_ratio(
        baseline["severe_loss"], baseline["positive_excess_loss"]
    )
    severe_rows = [row for row in rows if row["severe"]]
    baseline["snapshot_count"] = len(
        {(row["market_id"], row["target_date"], row["snapshot_id"]) for row in rows}
    )
    baseline["severe_snapshot_count"] = len(
        {(row["market_id"], row["target_date"], row["snapshot_id"]) for row in severe_rows}
    )
    baseline["market_day_count"] = len(day_counts)
    baseline["date_cluster_count"] = len({row["target_date"] for row in rows})
    baseline["market_cluster_count"] = len({row["market_id"] for row in rows})
    baseline["market_mode_winner_rate_on_severe_rows"] = _safe_ratio(
        sum(row["market_mode_is_winner"] for row in severe_rows), len(severe_rows)
    )
    baseline["model_mode_winner_rate_on_severe_rows"] = _safe_ratio(
        sum(row["model_mode_is_winner"] for row in severe_rows), len(severe_rows)
    )
    cross_tabs = build_cross_tabs(rows, baseline)
    p0 = _p0_structure(cross_tabs)
    curve = (
        build_tradeoff_curve(
            rows, replicates=bootstrap_replicates, seed=bootstrap_seed
        )
        if p0["structure_found"]
        else []
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "STRUCTURE_FOUND_CHARACTERIZE_RULES"
            if p0["structure_found"]
            else "NO_EX_ANTE_STRUCTURE_STOP_AFTER_P0"
        ),
        "source": source,
        "provenance_stratum": stratum,
        "severity_definition": {
            "positive_model_minus_market_brier": True,
            "absolute_selected_band_gap_at_least_points": SEVERE_GAP_POINTS,
            "outcome_used_only_for_label_and_loss": True,
        },
        "admission": {
            **settlement_inventory,
            "admitted_market_day_count": baseline["market_day_count"],
            "required": "current settlement ledger label has promotion_countable=true",
            "excluded_snapshot_counts": excluded_snapshots or {},
        },
        "support": baseline,
        "information_cutoffs": INFORMATION_CUTOFFS,
        "excluded_as_leakage_or_undated": [
            "settlement bucket/high and realized winner as candidate signals",
            "settlement_distance and winner-midpoint distances",
            "same-day aggregates not retained in the row's captured serving input",
            "reconstructed replay rows",
            "features without a captured row timestamp",
        ],
        "p0_structure": p0,
        "cross_tabs": cross_tabs,
        "tradeoff_curve": curve,
        "inference": {
            "method": "independent resampling of date clusters and market clusters, crossed by product weights",
            "bootstrap_replicates": bootstrap_replicates,
            "bootstrap_seed": bootstrap_seed,
            "interval": "two-sided percentile 95%",
            "power": (
                "two-sided alpha=0.05 normal approximation using observed risk difference "
                "and crossed-bootstrap standard error; descriptive plug-in power, not prospective power"
            ),
        },
        "actions_not_taken": [
            "no learned model or fitted candidate",
            "no global sharpening",
            "no maker configuration or quoting change",
            "no observed-high floor change",
            "no production data write, registration, restart, promotion, or merge",
        ],
    }


def _fmt(value, digits=3):
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _pct(value, digits=2):
    if value is None:
        return "-"
    return f"{100.0 * value:.{digits}f}%"


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def render_report(payload):
    support = payload["support"]
    if payload["verdict"].startswith("STRUCTURE_FOUND"):
        verdict = (
            "**YES, severe rows have ex-ante structure, but the strongest universal signal is "
            "definition-adjacent model/market disagreement; this is a defensive stand-down "
            "trade-off, not evidence that the weather model became more accurate.**"
        )
    else:
        verdict = "**NO: severe rows are indistinguishable from a random draw on the admitted ex-ante dimensions.**"
    lines = [
        "# Severe-tail ex-ante identifiability casebook",
        "",
        verdict,
        "",
        "## Admitted evidence",
        "",
        _table(
            ["Measure", "Value"],
            [
                ["Band rows", f"{support['row_count']:,}"],
                ["Snapshots", f"{support['snapshot_count']:,}"],
                ["Market-days", f"{support['market_day_count']:,}"],
                ["Date × market clusters", f"{support['date_cluster_count']} × {support['market_cluster_count']}"],
                ["Severe rows", f"{support['severe_row_count']:,} ({_pct(support['severe_rate'], 3)})"],
                ["Positive excess loss in severe rows", _pct(support['severe_loss_share_of_positive_excess'], 3)],
                ["Market mode wins on severe rows", _pct(support['market_mode_winner_rate_on_severe_rows'])],
                ["Model mode wins on severe rows", _pct(support['model_mode_winner_rate_on_severe_rows'])],
            ],
        ),
        "",
        "The append-only ledgers contain "
        f"{payload['admission']['raw_ledger_record_count']:,} physical records but only "
        f"{payload['admission']['current_event_label_count']:,} current event labels. Revisions "
        "are not independent market-days and their repeated row/snapshot totals are never counted "
        "as support.",
        "",
        "## P0 — structure screen",
        "",
        payload["p0_structure"]["screen_definition"] + ".",
        "",
        _table(
            ["Dimension", "Strongest group", "Severe-rate lift", "Loss-capture lift", "Material"],
            [
                [
                    row["dimension"],
                    row["strongest_value"],
                    _fmt(row["severe_rate_lift"], 2),
                    _fmt(row["loss_capture_lift"], 2),
                    "YES" if row["material_descriptive_structure"] else "no",
                ]
                for row in payload["p0_structure"]["screen"]
            ],
        ),
    ]
    if payload["tradeoff_curve"]:
        lines.extend(["", "## P1 — decision-rule trade-off curves", ""])
        for family in sorted({row["rule_family"] for row in payload["tradeoff_curve"]}):
            rows = [row for row in payload["tradeoff_curve"] if row["rule_family"] == family]
            lines.extend(
                [
                    f"### {family}",
                    "",
                    _table(
                        ["Threshold", "Tail loss reached", "Non-severe flagged", "All rows flagged", "Snapshot flag rate"],
                        [
                            [
                                _fmt(row["threshold"], 3),
                                _pct(row["severe_loss_recall"]),
                                _pct(row["nonsevere_flag_rate"]),
                                _pct(row["row_flag_rate"]),
                                _pct(row["snapshot_flag_rate"]),
                            ]
                            for row in rows
                        ],
                    ),
                    "",
                ]
            )
        lines.extend(
            [
                "No operating point is selected here. Choosing the cost of standing down is an operator decision.",
                "",
                "## P2 — crossed inference and power",
                "",
            ]
        )
        infer_rows = []
        for row in payload["tradeoff_curve"]:
            if row["rule_family"] not in {
                "selected_band_gap",
                "snapshot_max_gap",
                "gap_30_and_market_modal_probability",
            }:
                continue
            risk_interval = row["crossed_95_intervals"].get("risk_difference") or [None, None]
            infer_rows.append(
                [
                    row["rule_family"],
                    _fmt(row["threshold"], 2),
                    f"{_fmt(row['risk_difference'], 4)} [{_fmt(risk_interval[0], 4)}, {_fmt(risk_interval[1], 4)}]",
                    _pct(row["risk_difference_plugin_power"], 1),
                    (
                        "distinguishable"
                        if row["risk_difference_distinguishable_from_zero"]
                        else "not distinguishable from zero"
                    ),
                ]
            )
        lines.append(
            _table(
                ["Rule", "Threshold", "Severe-risk difference [95%]", "Plug-in power", "Verdict"],
                infer_rows,
            )
        )
    lines.extend(
        [
            "",
            "## Leakage controls",
            "",
            _table(
                ["Signal", "Information cutoff", "Enforcement"],
                [
                    [row["signal"], row["cutoff"], row["enforcement"]]
                    for row in payload["information_cutoffs"]
                ],
            ),
            "",
            "Settlement and the realized outcome define the retrospective label only. They never enter a rule. "
            "This is retrospective characterization of already-used dates, not unseen-day or promotion evidence.",
            "",
            "## Explicit non-actions",
            "",
            *[f"- {item}." for item in payload["actions_not_taken"]],
            "",
        ]
    )
    return "\n".join(lines)


def _discover_replay_rows(args, settlement_index):
    snapshots_root = Path(args.snapshots_root)
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    folders = []
    for label in settlement_index.values():
        target = date.fromisoformat(label["target_date"])
        if (
            label["promotion_countable"]
            and start <= target <= end
            and _stratum_accepts(target, args.provenance_stratum)
        ):
            folder = snapshots_root / label["event_slug"]
            if folder.joinpath("snapshots_long.csv").exists():
                folders.append(str(folder))
    if not folders:
        raise ValueError("no promotion-countable snapshot folders found in requested range")

    import weather.paths as weather_paths

    weather_paths.DATA_ROOT = Path(args.data_root)
    from weather.backtesting.replay_backtest import run_replay_backtest

    results = run_replay_backtest(
        sorted(folders),
        daily_summary_path=None,
        overrides={},
        out_path=Path(args.out_report),
        include_reconstructed=False,
        write=False,
        corpus_manifest=None,
    )
    return results.get("all_rows") or [], {
        "kind": "captured_input_replay",
        "data_root": str(args.data_root),
        "snapshots_root": str(snapshots_root),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "folder_count": len(folders),
        "replayed_snapshot_count": results.get("snaps_scored"),
        "replayed_versions": results.get("replayed_versions"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Characterize whether severe-loss rows are identifiable ex ante."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rows-csv", help="Existing exact replay band-row CSV.")
    source.add_argument("--snapshots-root", help="Replay promotion-countable snapshot folders.")
    parser.add_argument("--data-root", default=None, help="Required with --snapshots-root.")
    parser.add_argument("--settlements-root", required=True)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--provenance-stratum", required=True, choices=STRATA)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    args = parser.parse_args(argv)
    if args.snapshots_root and not all((args.data_root, args.start_date, args.end_date)):
        parser.error("--snapshots-root requires --data-root, --start-date, and --end-date")

    settlement_index, settlement_inventory = load_current_settlement_index(
        args.settlements_root
    )
    if args.rows_csv:
        compact, excluded = load_replay_csv(
            args.rows_csv,
            settlement_index=settlement_index,
            stratum=args.provenance_stratum,
        )
        source_info = {
            "kind": "exact_replay_row_csv",
            "path": str(Path(args.rows_csv).resolve()),
            "sha256": _sha256(args.rows_csv),
        }
    else:
        raw_rows, source_info = _discover_replay_rows(args, settlement_index)
        compact, excluded = compact_replay_rows(
            raw_rows,
            settlement_index=settlement_index,
            stratum=args.provenance_stratum,
        )
    payload = analyze_compact_rows(
        compact,
        settlement_inventory=settlement_inventory,
        source=source_info,
        excluded_snapshots=excluded,
        stratum=args.provenance_stratum,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
    )
    out_json = Path(args.out_json)
    out_report = Path(args.out_report)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    out_report.write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "rows": payload["support"]["row_count"],
                "snapshots": payload["support"]["snapshot_count"],
                "market_days": payload["support"]["market_day_count"],
                "severe_rows": payload["support"]["severe_row_count"],
                "out_json": str(out_json),
                "out_report": str(out_report),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
