"""Implementation slice extracted from src/weather/reporting/promotion_refresh.py."""

from weather.reporting.promotion.decisions import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def _readiness_table_rows(readiness):
    blockers = (readiness or {}).get("blockers") or []
    if not blockers:
        return [["ready", "info", "no promotion readiness blockers"]]
    return [
        [row.get("category"), row.get("severity"), row.get("detail")]
        for row in blockers
    ]


def _readiness_market_detail_rows(readiness):
    rows = []
    for item in (readiness or {}).get("shadow_market_details") or []:
        rows.append([
            item.get("market_id"),
            item.get("action"),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("delta_vs_current"), 4),
            fmt_signed(item.get("delta_vs_market"), 4),
            item.get("reason") or "-",
        ])
    for item in (readiness or {}).get("blocked_market_details") or []:
        rows.append([
            item.get("market_id"),
            item.get("action"),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("delta_vs_current"), 4),
            fmt_signed(item.get("delta_vs_market"), 4),
            item.get("reason") or "-",
        ])
    return rows


def _slice_delta_vs_market(row):
    value = row.get("delta_vs_market")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slice_brier(row):
    if row.get("micro_brier") is not None:
        return row.get("micro_brier")
    return row.get("candidate_brier")


def _candidate_gap_driver_rows(candidate, limit=12):
    slices = (candidate or {}).get("slices") or {}
    sources = [
        ("market", slices.get("by_market") or []),
        ("cutoff_hour", slices.get("by_cutoff_hour") or []),
        ("band_type", slices.get("by_band_type") or []),
        ("settlement_distance", slices.get("by_settlement_distance") or []),
        ("clob_taxonomy", slices.get("by_clob_taxonomy") or []),
        ("source_freshness", slices.get("by_source_freshness") or []),
    ]
    rows = []
    for slice_name, items in sources:
        for item in items:
            delta_market = _slice_delta_vs_market(item)
            n = int(item.get("n") or item.get("rows") or 0)
            if delta_market is None or delta_market <= 0 or n <= 0:
                continue
            rows.append({
                "slice": slice_name,
                "group": item.get("group"),
                "rows": n,
                "brier": _slice_brier(item),
                "market_brier": item.get("market_brier"),
                "delta_vs_current": item.get("delta_vs_current"),
                "delta_vs_market": delta_market,
                "excess_brier_rows": delta_market * n,
            })
    rows.sort(key=lambda row: row["excess_brier_rows"], reverse=True)
    return rows[:limit]


def _gap_rule(slice_name, group):
    group_text = str(group if group is not None else "-")
    if slice_name == "settlement_distance" and group_text == "0":
        return {
            "owner": "settlement-distance winner catch-up",
            "roadmap_owner": "Item 70",
            "next_experiment": "settlement_distance_0_winner_catchup_daily_first",
            "experiment_artifact": "data/backtest/experiments/settlement_distance_0_winner_catchup_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if slice_name == "band_type" and group_text == "eq":
        return {
            "owner": "exact-band calibration",
            "roadmap_owner": "Item 48",
            "next_experiment": "exact_band_calibration_daily_first",
            "experiment_artifact": "data/backtest/experiments/exact_band_calibration_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if slice_name == "cutoff_hour" and group_text == "7":
        return {
            "owner": "07:00 cold-start calibration",
            "roadmap_owner": "Item 48",
            "next_experiment": "cutoff_07_cold_start_daily_first",
            "experiment_artifact": "data/backtest/experiments/cutoff_07_cold_start_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if slice_name == "market":
        return {
            "owner": f"{group_text} residual calibration",
            "roadmap_owner": "Item 48",
            "next_experiment": f"{group_text}_residual_calibration_daily_first",
            "experiment_artifact": f"data/backtest/experiments/{group_text}_residual_calibration_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if group_text == "wu_lag_catchup_miss":
        return {
            "owner": "WU lag catch-up repair",
            "roadmap_owner": "Item 115",
            "next_experiment": "wu_lag_catchup_repair_daily_first",
            "experiment_artifact": "data/backtest/experiments/wu_lag_catchup_repair_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if group_text == "boundary_rounding_error":
        return {
            "owner": "boundary-rounding repair",
            "roadmap_owner": "Item 115",
            "next_experiment": "boundary_rounding_repair_daily_first",
            "experiment_artifact": "data/backtest/experiments/boundary_rounding_repair_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if group_text in {"stale_source", "failed_source"} or slice_name == "source_freshness":
        return {
            "owner": "source freshness calibration",
            "roadmap_owner": "Items 17, 48",
            "next_experiment": "source_freshness_repair_daily_first",
            "experiment_artifact": "data/backtest/experiments/source_freshness_repair_daily_first.json",
            "claim_lane": "weather_only_core_model",
            "counts_toward_core_skill_claim": True,
        }
    if slice_name == "clob_taxonomy":
        return {
            "owner": "CLOB-informed overlay diagnostics",
            "roadmap_owner": "Item 47",
            "next_experiment": "clob_overlay_quote_gate_shadow",
            "experiment_artifact": "data/backtest/experiments/clob_overlay_quote_gate_shadow.json",
            "claim_lane": "market_informed_quote_risk",
            "counts_toward_core_skill_claim": False,
        }
    return {
        "owner": "market-skill triage",
        "roadmap_owner": "Item 48",
        "next_experiment": f"{slice_name}_{group_text}_daily_first".replace(":", "_").replace(" ", "_"),
        "experiment_artifact": (
            "data/backtest/experiments/"
            + f"{slice_name}_{group_text}_daily_first".replace(":", "_").replace(" ", "_")
            + ".json"
        ),
        "claim_lane": "weather_only_core_model",
        "counts_toward_core_skill_claim": True,
    }


def _positive_gap_markets(decisions):
    rows = []
    for item in (decisions or {}).get("markets") or []:
        metrics = item.get("metrics") or {}
        delta = _slice_delta_vs_market(metrics)
        if delta is None or delta <= 0:
            continue
        rows.append((item.get("market_id"), delta))
    rows.sort(key=lambda item: item[1], reverse=True)
    return [market for market, _delta in rows if market]


def build_gap_owner_table(gap_drivers, decisions=None, *, limit=12):
    positive_markets = _positive_gap_markets(decisions or {})
    rows = []
    for row in (gap_drivers or [])[:limit]:
        rule = _gap_rule(row.get("slice"), row.get("group"))
        if row.get("slice") == "market":
            affected = [str(row.get("group"))]
        else:
            affected = positive_markets[:6]
        rows.append({
            **row,
            **rule,
            "affected_markets": affected,
            "blocked_shadow_reason": (
                "aggregate or daily-first candidate-vs-market gap remains positive"
            ),
            "clearance_rule": (
                "Paired daily-first replay must improve this slice, aggregate delta_vs_market "
                "must be <= 0, and no promoted/shadow market may regress versus current or market."
            ),
        })
    return rows


def _operational_gate_rows(payload):
    rows = []
    freshness = payload.get("evidence_freshness") or {}
    for gate in freshness.get("gates") or []:
        rows.append([
            "Evidence freshness: " + str(gate.get("name") or "-"),
            gate.get("status") or "-",
            gate.get("detail") or gate.get("path") or "-",
        ])
    artifact_quarantine = payload.get("per_location_artifact_quarantine") or {}
    if artifact_quarantine:
        summary = artifact_quarantine.get("summary") or {}
        rows.append([
            "Per-location artifact quarantine",
            artifact_quarantine.get("status") or "-",
            (
                f"historical_only={summary.get('historical_only_count', 0)}, "
                f"active_violations={summary.get('active_candidate_violation_count', 0)}"
            ),
        ])
    early_hour = payload.get("early_hour_promotion_blocker") or {}
    if early_hour:
        current = early_hour.get("current_gates") or {}
        rows.append([
            "Early-hour promotion blocker",
            early_hour.get("status") or "-",
            (
                f"hourly={current.get('hourly_status') or '-'}, "
                f"ten_minute={current.get('ten_minute_status') or '-'}, "
                f"blockers={early_hour.get('blocker_count', 0)}"
            ),
        ])
    source_missingness = payload.get("source_missingness_location_gate") or {}
    if source_missingness:
        summary = source_missingness.get("summary") or {}
        first = source_missingness.get("first_blocker") or {}
        rows.append([
            "Source/missingness location gate",
            source_missingness.get("status") or "-",
            (
                f"market_source={summary.get('market_source_freshness_slice_count', 0)}, "
                f"market_count={summary.get('market_forecast_source_count_slice_count', 0)}, "
                f"missingness={summary.get('market_feature_missingness_slice_count', 0)}, "
                f"blockers={summary.get('blocker_count', 0)}"
                + (f"; first={first.get('detail')}" if first.get("detail") else "")
            ),
        ])
    source_family = payload.get("source_family_inventory") or {}
    if source_family:
        preflight = source_family.get("promotion_preflight") or {}
        rows.append([
            "Source family preflight",
            preflight.get("status") or source_family.get("status") or "-",
            ", ".join(preflight.get("blocked_families") or []) or "no blocked active input families",
        ])
    physical_ratchet = payload.get("physical_feature_family_ratchet") or {}
    if physical_ratchet:
        summary = physical_ratchet.get("summary") or {}
        first = physical_ratchet.get("first_blocker") or {}
        rows.append([
            "Physical family ratchet",
            physical_ratchet.get("status") or "-",
            (
                f"blocked={summary.get('blocking_family_count')}; "
                f"slices={summary.get('settlement_slice_row_count')}; "
                f"first={first.get('family_id') or '-'} {first.get('status') or ''}"
            ),
        ])
    fleet = payload.get("fleet_observability") or {}
    if fleet:
        summary = fleet.get("summary") or {}
        rows.append([
            "Live-forward SLO",
            summary.get("live_forward_slo_status") or "-",
            f"fleet status {fleet.get('status') or '-'}",
        ])
    hourly = payload.get("hourly_performance") or {}
    if hourly:
        gate = hourly.get("hourly_performance_gate") or {}
        first = gate.get("first_blocker") or next(iter(gate.get("blockers") or []), {})
        rows.append([
            "Current-serving hourly gate",
            gate.get("status") or "-",
            first.get("detail") or "no hourly blocker",
        ])
    candidate_hourly = payload.get("candidate_hourly_performance") or {}
    if candidate_hourly:
        gate = candidate_hourly.get("candidate_hourly_gate") or {}
        first = gate.get("first_blocker") or next(iter(gate.get("blockers") or []), {})
        rows.append([
            "Candidate hourly gate",
            gate.get("status") or "-",
            first.get("detail") or "no candidate-hourly blocker",
        ])
    ten_minute = payload.get("ten_minute_performance") or {}
    if ten_minute:
        gate = ten_minute.get("ten_minute_performance_gate") or {}
        first = gate.get("first_blocker") or next(iter(gate.get("blockers") or []), {})
        rows.append([
            "Current-serving 10-minute gate",
            gate.get("status") or "-",
            first.get("detail") or "no 10-minute blocker",
        ])
    candidate_ten_minute = payload.get("candidate_ten_minute_performance") or {}
    if candidate_ten_minute:
        gate = candidate_ten_minute.get("candidate_ten_minute_gate") or {}
        first = gate.get("first_blocker") or next(iter(gate.get("blockers") or []), {})
        rows.append([
            "Candidate 10-minute gate",
            gate.get("status") or "-",
            first.get("detail") or "no candidate 10-minute blocker",
        ])
    mitigation = (payload.get("readiness") or {}).get("hourly_performance_mitigation") or {}
    if mitigation:
        rows.append([
            "Hourly gate mitigation",
            "APPLIED" if mitigation.get("applied") else "NOT_APPLIED",
            (
                "candidate hourly gate passed and variant id matched"
                if mitigation.get("applied")
                else "candidate-hourly evidence did not mitigate current-serving gate"
            ),
        ])
    ten_minute_mitigation = (payload.get("readiness") or {}).get("ten_minute_performance_mitigation") or {}
    if ten_minute_mitigation:
        rows.append([
            "10-minute gate mitigation",
            "APPLIED" if ten_minute_mitigation.get("applied") else "NOT_APPLIED",
            (
                "candidate 10-minute gate passed and variant id matched"
                if ten_minute_mitigation.get("applied")
                else "candidate 10-minute evidence did not mitigate current-serving gate"
            ),
        ])
    return rows


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _diagnostic_markets_from_decisions(decisions):
    rows = []
    for row in (decisions or {}).get("markets") or []:
        market_id = row.get("market_id")
        if not market_id or row.get("action") == "PROMOTE_CANDIDATE":
            continue
        metrics = row.get("metrics") or {}
        delta_market = _slice_delta_vs_market(metrics)
        rows.append((
            market_id,
            row.get("action") == "BLOCK_CANDIDATE",
            float(delta_market) if delta_market is not None else -1.0,
        ))
    rows.sort(key=lambda item: (not item[1], -item[2], item[0]))
    return [market_id for market_id, _blocked, _delta in rows]


def market_skill_diagnostics(candidate, decisions, markets=None):
    by_market = {
        str(row.get("group")): row
        for row in ((candidate or {}).get("slices") or {}).get("by_market") or []
        if row.get("group") not in (None, "")
    }
    decision_by_market = {
        row.get("market_id"): row
        for row in (decisions or {}).get("markets") or []
        if row.get("market_id")
    }
    rows = []
    markets = list(markets) if markets is not None else _diagnostic_markets_from_decisions(decisions)
    for market_id in markets:
        slice_row = by_market.get(market_id) or {}
        decision = decision_by_market.get(market_id) or {}
        metrics = decision.get("metrics") or {}
        rule = _gap_rule("market", market_id)
        rows.append({
            "market_id": market_id,
            "slice": "market",
            "group": market_id,
            "action": decision.get("action") or "-",
            "reason": decision.get("reason") or "-",
            "candidate_brier": _first_present(metrics.get("candidate_brier"), slice_row.get("candidate_brier")),
            "current_brier": _first_present(metrics.get("current_brier"), slice_row.get("current_brier")),
            "market_brier": _first_present(metrics.get("market_brier"), slice_row.get("market_brier")),
            "delta_vs_current": _first_present(metrics.get("delta_vs_current"), slice_row.get("delta_vs_current")),
            "delta_vs_market": _first_present(metrics.get("delta_vs_market"), slice_row.get("delta_vs_market")),
            "excess_brier_rows": None,
            **rule,
            "affected_markets": [market_id],
            "clearance_rule": (
                "Paired daily-first replay must improve this market, aggregate "
                "delta_vs_market must be <= 0, and no promoted/shadow market may regress."
            ),
        })
    return rows


def model_skill_claims(candidate, gap_owner_table=None):
    aggregate = (candidate or {}).get("aggregate") or {}
    delta_market = aggregate.get("delta_vs_market")
    try:
        delta_market_value = float(delta_market)
    except (TypeError, ValueError):
        delta_market_value = None
    blocked_validation = (candidate or {}).get("blocked_validation") or {}
    daily_first_passed = blocked_validation.get("passed")
    if daily_first_passed is None:
        daily_first_passed = not blocked_validation
    core_allowed = bool(
        delta_market_value is not None
        and delta_market_value <= 0
        and daily_first_passed
    )
    owner_rows = gap_owner_table or []
    return {
        "weather_only_core_model": {
            "delta_vs_market": delta_market,
            "daily_first_passed": bool(daily_first_passed),
            "broad_market_skill_claim_allowed": core_allowed,
            "reason": (
                "core candidate clears aggregate and daily-first market-skill gates"
                if core_allowed
                else "core candidate still needs aggregate delta_vs_market <= 0 and daily-first clearance"
            ),
        },
        "market_informed_quote_risk": {
            "counts_toward_core_skill_claim": False,
            "may_support_quote_gating": True,
            "owner_row_count": sum(
                1 for row in owner_rows
                if row.get("claim_lane") == "market_informed_quote_risk"
            ),
            "reason": "CLOB-informed overlays are quote/permission evidence, not weather-only core-skill evidence.",
        },
    }


def write_gap_experiment_artifacts(rows, min_free_bytes=0):
    written = []
    seen = set()
    for row in rows or []:
        artifact = row.get("experiment_artifact")
        if not artifact:
            continue
        if artifact in seen:
            continue
        seen.add(artifact)
        payload = {
            "schema_version": "market_skill_gap_experiment_v0.1",
            "status": "OPEN",
            "generated_at_utc": _utc_now(),
            "owner": row.get("owner"),
            "roadmap_owner": row.get("roadmap_owner"),
            "slice": row.get("slice"),
            "group": row.get("group"),
            "weighted_gap": row.get("excess_brier_rows"),
            "affected_markets": row.get("affected_markets") or [],
            "claim_lane": row.get("claim_lane"),
            "counts_toward_core_skill_claim": row.get("counts_toward_core_skill_claim"),
            "next_experiment": row.get("next_experiment"),
            "clearance_rule": row.get("clearance_rule"),
            "required_replay": {
                "mode": "paired_daily_first",
                "baselines": ["current", "candidate", "market"],
                "aggregate_delta_vs_market_must_be_lte": 0,
                "no_promoted_or_shadow_market_regression": True,
            },
        }
        written_path = _write_json(
            artifact,
            payload,
            min_free_bytes=min_free_bytes,
            context="promotion refresh gap experiment manifest export",
        )
        row["experiment_artifact_exists"] = True
        written.append(str(written_path))
    return written


def _candidate_source_freshness_rows(candidate):
    slices = (candidate or {}).get("slices") or {}
    rows = []
    for item in slices.get("by_source_freshness") or []:
        delta_market = _slice_delta_vs_market(item)
        n = int(item.get("n") or item.get("rows") or 0)
        if delta_market is None or n <= 0:
            continue
        rows.append({
            "group": item.get("group"),
            "rows": n,
            "brier": _slice_brier(item),
            "market_brier": item.get("market_brier"),
            "delta_vs_current": item.get("delta_vs_current"),
            "delta_vs_market": delta_market,
            "excess_brier_rows": delta_market * n,
        })
    rows.sort(key=lambda row: row["excess_brier_rows"], reverse=True)
    return rows


def _gap_driver_table_rows(rows, include_slice=True):
    output = []
    for row in rows:
        cells = []
        if include_slice:
            cells.append(row.get("slice"))
        cells.extend([
            row.get("group") if row.get("group") not in (None, "") else "-",
            row.get("rows", 0),
            fmt_num(row.get("brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_signed(row.get("delta_vs_market"), 4),
            fmt_num(row.get("excess_brier_rows")),
        ])
        output.append(cells)
    if output:
        return output
    return [["-", "-", 0, "-", "-", "-", "-", "-"]] if include_slice else [["-", 0, "-", "-", "-", "-", "-"]]


def _gap_owner_table_rows(rows):
    return [
        [
            row.get("slice"),
            row.get("group") if row.get("group") not in (None, "") else "-",
            fmt_num(row.get("excess_brier_rows")),
            ", ".join(row.get("affected_markets") or []) or "-",
            row.get("owner"),
            row.get("roadmap_owner"),
            row.get("next_experiment"),
            row.get("experiment_artifact"),
            row.get("claim_lane"),
            row.get("counts_toward_core_skill_claim"),
            row.get("clearance_rule"),
        ]
        for row in rows or []
    ]


def _market_skill_diagnostic_rows(rows):
    return [
        [
            row.get("market_id"),
            row.get("action"),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_signed(row.get("delta_vs_market"), 4),
            row.get("next_experiment"),
            row.get("reason") or "-",
        ]
        for row in rows or []
    ]


def _model_skill_claim_rows(claims):
    rows = []
    for lane, item in (claims or {}).items():
        rows.append([
            lane,
            item.get("broad_market_skill_claim_allowed")
            if "broad_market_skill_claim_allowed" in item
            else item.get("counts_toward_core_skill_claim"),
            item.get("may_support_quote_gating", False),
            fmt_signed(item.get("delta_vs_market"), 4),
            item.get("reason"),
        ])
    return rows


def _serving_table_rows(serving):
    rows = []
    for row in (serving or {}).get("market_rows") or []:
        comp = row.get("comparison") or {}
        rows.append([
            row.get("market_id"),
            row.get("verdict"),
            row.get("rows", 0),
            fmt_num(comp.get("replayed_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            fmt_signed(comp.get("code_effect"), 4),
            row.get("reason") or "-",
        ])
    return rows


def _serving_blocking_source_freshness_rows(serving):
    rows = []
    blocking = ((serving or {}).get("decomposition") or {}).get("blocking_markets") or {}
    for market_id, slices in sorted(blocking.items()):
        for item in (slices or {}).get("by_source_freshness") or []:
            code_effect = item.get("code_effect")
            n = int(item.get("n") or 0)
            try:
                excess = float(code_effect) * n
            except (TypeError, ValueError):
                excess = None
            rows.append([
                market_id,
                item.get("group") if item.get("group") not in (None, "") else "-",
                n,
                fmt_num(item.get("replayed_brier")),
                fmt_num(item.get("recorded_brier")),
                fmt_num(item.get("market_brier")),
                fmt_signed(code_effect, 4),
                fmt_num(excess),
            ])
    return rows

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]

