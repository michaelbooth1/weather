"""Implementation slice extracted from src/weather/reporting/hourly_model_performance.py."""

from weather.reporting.hourly.hourly_model_slots import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def _weighted_mean(items, value_key, weight_key="n"):
    total_weight = 0.0
    total = 0.0
    for item in items:
        value = safe_float(item.get(value_key))
        weight = safe_float(item.get(weight_key)) or 0.0
        if value is None or weight <= 0:
            continue
        total += value * weight
        total_weight += weight
    return total / total_weight if total_weight else None


def _remediation_owner(probe_name, uses_market_prices):
    if uses_market_prices:
        return {
            "owner": "market-making risk overlay",
            "claim_lane": "quote_risk_control_only",
            "counts_toward_weather_model_promotion": False,
        }
    if probe_name == "partition_power":
        return {
            "owner": "model calibration",
            "claim_lane": "weather_model_output_shape",
            "counts_toward_weather_model_promotion": True,
        }
    if probe_name == "forecast_centering":
        return {
            "owner": "early-hour forecast-centering candidate",
            "claim_lane": "weather_model_forecast_relative_centering",
            "counts_toward_weather_model_promotion": True,
        }
    return {
        "owner": "model remediation",
        "claim_lane": "weather_model_candidate",
        "counts_toward_weather_model_promotion": True,
    }


def _interpret_remediation(probe_name, delta, uses_market_prices):
    if delta is None:
        return "no comparable rows"
    if uses_market_prices:
        if delta < -0.003:
            return "risk overlay reduces error but cannot count as weather-model promotion evidence"
        if delta <= 0.003:
            return "risk overlay is inconclusive for this regime"
        return "risk overlay worsens this regime"
    if delta < -0.003:
        return "weather-only probe improves this regime and should be promoted to a candidate lane"
    if delta <= 0.003:
        return "weather-only probe is too small to explain the timing failure"
    return "weather-only probe regresses this regime"


def _serving_mitigation_status(probe_name, regime, uses_market_prices):
    if regime != "early_morning":
        return "not_applicable"
    if uses_market_prices:
        return "quote_risk_only"
    return "candidate_hourly_gate_required"


def _serving_mitigation_requirement(regime, uses_market_prices):
    if regime != "early_morning":
        return "current-serving hourly blocker applies only to the early-hour regime"
    if uses_market_prices:
        return "market-aware overlays may reduce quote risk but cannot mitigate a weather-model promotion blocker"
    return "requires a matching candidate-specific hourly gate PASS before promotion readiness can mitigate the current-serving blocker"


def build_remediation_registry(
    remediation,
    by_hour,
    checkpoint_rows=None,
    *,
    early_hour_market_delta_rows=None,
    early_brier_regression_tolerance=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    early_logloss_regression_tolerance=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
):
    hour_summary = {int(row["hour"]): row for row in by_hour if row.get("hour") is not None}
    per_market = early_hour_market_delta_rows
    if per_market is None:
        per_market = early_hour_market_deltas(
            checkpoint_rows or [],
            early_brier_regression_tolerance=early_brier_regression_tolerance,
            early_logloss_regression_tolerance=early_logloss_regression_tolerance,
        )
    rows = []
    for probe_name, probe in sorted((remediation or {}).items()):
        uses_market_prices = bool(probe.get("uses_market_prices"))
        owner = _remediation_owner(probe_name, uses_market_prices)
        by_hour_rows = {int(row["hour"]): row for row in probe.get("by_hour") or []}
        for regime, label in HOUR_REGIME_LABELS.items():
            hours = [
                hour for hour in by_hour_rows
                if hour_regime(hour) == regime and hour in hour_summary
            ]
            if not hours:
                continue
            joined = []
            best_parameters = []
            for hour in sorted(hours):
                probe_row = by_hour_rows[hour]
                summary = hour_summary[hour]
                best = probe_row.get("best") or {}
                joined.append({
                    "hour": hour,
                    "n": summary.get("n"),
                    "markets": summary.get("markets"),
                    "market_days": summary.get("market_days"),
                    "brier_delta_vs_base": best.get("brier_delta_vs_base"),
                    "logloss_delta_vs_base": best.get("logloss_delta_vs_base"),
                })
                best_parameters.append(best.get("parameter"))
            brier_delta = _weighted_mean(joined, "brier_delta_vs_base")
            logloss_delta = _weighted_mean(joined, "logloss_delta_vs_base")
            serving_status = _serving_mitigation_status(probe_name, regime, uses_market_prices)
            rows.append({
                "schema_version": REMEDIATION_REGISTRY_SCHEMA_VERSION,
                "probe_name": probe_name,
                "hour_regime": regime,
                "hour_regime_label": label,
                "metric": "model_brier",
                "metric_delta": brier_delta,
                "logloss_delta": logloss_delta,
                "market_count": max((safe_int(row.get("markets")) or 0 for row in joined), default=0),
                "market_day_count": max((safe_int(row.get("market_days")) or 0 for row in joined), default=0),
                "row_count": sum(safe_int(row.get("n")) or 0 for row in joined),
                "hour_count": len(joined),
                "hours": [row["hour"] for row in joined],
                "best_parameters": best_parameters,
                "uses_market_prices": uses_market_prices,
                "owner": owner["owner"],
                "claim_lane": owner["claim_lane"],
                "counts_toward_weather_model_promotion": owner["counts_toward_weather_model_promotion"],
                "serving_mitigation_allowed": False,
                "serving_mitigation_status": serving_status,
                "serving_mitigation_requirement": _serving_mitigation_requirement(regime, uses_market_prices),
                "interpretation": _interpret_remediation(probe_name, brier_delta, uses_market_prices),
            })
    blocked_markets = [row for row in per_market if row.get("status") == "BLOCK"]
    return {
        "schema_version": REMEDIATION_REGISTRY_SCHEMA_VERSION,
        "rows": rows,
        "early_hour_market_deltas": per_market,
        "summary": {
            "row_count": len(rows),
            "probe_names": sorted({row["probe_name"] for row in rows}),
            "hour_regimes": sorted({row["hour_regime"] for row in rows}),
            "market_price_probe_count": sum(1 for row in rows if row.get("uses_market_prices")),
            "weather_model_probe_count": sum(1 for row in rows if not row.get("uses_market_prices")),
            "early_hour_market_delta_count": len(per_market),
            "early_hour_blocked_market_count": len(blocked_markets),
            "early_hour_brier_blocked_market_count": sum(
                1 for row in blocked_markets
                if "early_hour_brier_regression" in (row.get("blocking_gates") or [])
            ),
            "early_hour_logloss_blocked_market_count": sum(
                1 for row in blocked_markets
                if "early_hour_logloss_regression" in (row.get("blocking_gates") or [])
            ),
            "early_hour_worst_markets": [row.get("market_id") for row in blocked_markets[:5]],
        },
    }


def hourly_performance_gate(
    by_hour_regime,
    corpus,
    *,
    min_regime_market_days=DEFAULT_MIN_REGIME_MARKET_DAYS,
    early_brier_regression_tolerance=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    early_logloss_regression_tolerance=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    early_ece_max=DEFAULT_EARLY_ECE_MAX,
):
    by_regime = {row.get("regime"): row for row in by_hour_regime or []}
    early = by_regime.get("early_morning") or {}
    blockers = []
    market_days = safe_int(early.get("market_days"))
    if not early:
        blockers.append({
            "gate": "early_hour_regime_missing",
            "detail": "no early 00:00-08:00 hourly-regime evidence is available",
            "remediation_command": "python -m weather.reporting.hourly.hourly_model_performance",
        })
    elif market_days < int(min_regime_market_days):
        blockers.append({
            "gate": "early_hour_min_market_days",
            "detail": (
                f"early-hour regime has {market_days} market-days; "
                f"requires at least {int(min_regime_market_days)}"
            ),
            "remediation_command": "collect more settled early-hour market-day evidence",
        })

    brier_delta = safe_float(early.get("brier_delta"))
    if brier_delta is not None and brier_delta < -float(early_brier_regression_tolerance):
        blockers.append({
            "gate": "early_hour_brier_regression",
            "detail": (
                "early-hour model Brier trails market by "
                f"{abs(brier_delta):.4f} > {float(early_brier_regression_tolerance):.4f}"
            ),
            "remediation_command": "keep promotion blocked; run early-hour remediation candidate or quote-risk guardrail",
        })
    logloss_delta = safe_float(early.get("logloss_delta"))
    if logloss_delta is not None and logloss_delta < -float(early_logloss_regression_tolerance):
        blockers.append({
            "gate": "early_hour_logloss_regression",
            "detail": (
                "early-hour model log-loss trails market by "
                f"{abs(logloss_delta):.4f} > {float(early_logloss_regression_tolerance):.4f}"
            ),
            "remediation_command": "keep promotion blocked; inspect early-hour probability tails",
        })
    ece = safe_float(early.get("model_ece"))
    if ece is not None and ece > float(early_ece_max):
        blockers.append({
            "gate": "early_hour_calibration_error",
            "detail": f"early-hour ECE {ece:.4f} exceeds {float(early_ece_max):.4f}",
            "remediation_command": "add early-hour calibration remediation before promotion",
        })
    status = "BLOCK" if blockers else "PASS"
    return {
        "schema_version": HOURLY_GATE_SCHEMA_VERSION,
        "status": status,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "thresholds": {
            "min_regime_market_days": int(min_regime_market_days),
            "early_brier_regression_tolerance": float(early_brier_regression_tolerance),
            "early_logloss_regression_tolerance": float(early_logloss_regression_tolerance),
            "early_ece_max": float(early_ece_max),
        },
        "early_morning": early,
        "corpus_market_days": (corpus or {}).get("scored_market_days", 0),
    }


def hourly_daily_summary(best_hours, worst_hours, remediation_registry, gate):
    owners = sorted({
        row.get("owner")
        for row in (remediation_registry.get("rows") or [])
        if row.get("hour_regime") == "early_morning" and row.get("owner")
    })
    return {
        "status": gate.get("status"),
        "best_hours": [row.get("hour_label") for row in best_hours or []],
        "worst_hours": [row.get("hour_label") for row in worst_hours or []],
        "active_remediation_owners": owners,
        "first_blocker": gate.get("first_blocker") or {},
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
