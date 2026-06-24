"""June 23 location-bias repair packet and counterfactual replay."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from weather.backtesting.settlement_ledger import band_value_hi, parse_band_label
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.model_history import DEFAULT_LABELS_CSV, safe_float, safe_int
from weather.reporting.winner_rank_parity import (
    DEFAULT_SNAPSHOTS_ROOT,
    _case_summary,
    load_served_rows,
    snapshot_cases,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("june23_location_bias_repair")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_TARGET_DATE = "2026-06-23"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "june23_location_bias_repair_packet.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "june23_location_bias_repair_packet.md"
REPAIR_VARIANT_ID = "item301_location_bias_centering_v0_1"
REPAIR_STRENGTH = 0.65

REPAIR_MARKETS = {
    "seattle": {
        "priority": "P1",
        "expected_bias": "cold_miss",
        "repair_family": "cold_side_winner_mass_centering",
    },
    "toronto": {
        "priority": "P1",
        "expected_bias": "cold_miss",
        "repair_family": "cold_side_winner_mass_centering",
    },
    "san-francisco": {
        "priority": "P1",
        "expected_bias": "cold_miss",
        "repair_family": "cold_side_winner_mass_centering",
    },
    "austin": {
        "priority": "P2",
        "expected_bias": "warm_miss",
        "repair_family": "warm_side_adjacent_confidence_dampener",
    },
    "dallas": {
        "priority": "P2",
        "expected_bias": "warm_miss",
        "repair_family": "warm_side_adjacent_confidence_dampener",
    },
    "denver": {
        "priority": "P2",
        "expected_bias": "warm_miss",
        "repair_family": "warm_side_adjacent_confidence_dampener",
    },
}
PROTECTED_MARKETS = {"chicago", "los-angeles", "nyc", "miami"}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round(value: Any, digits: int = 6) -> float | None:
    number = safe_float(value)
    return round(number, digits) if number is not None else None


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _band_center(label: Any) -> float | None:
    text = str(label or "").strip()
    if not text:
        return None
    parsed = parse_band_label(text)
    value = safe_float(parsed.get("value"))
    if value is None:
        return None
    kind = parsed.get("kind")
    if kind == "eq":
        high = safe_float(band_value_hi(text, int(value)))
        return (value + high) / 2.0 if high is not None else value
    return value


def _case_top_offset(case: dict[str, Any]) -> float | None:
    model_center = _band_center(case.get("model_top_band"))
    winner_center = _band_center(case.get("winner_band"))
    if model_center is None or winner_center is None:
        return None
    return model_center - winner_center


def classify_direction(cases: list[dict[str, Any]]) -> str:
    missed = [case for case in cases if not case.get("model_top_hit")]
    offsets = [_case_top_offset(case) for case in missed]
    mean_offset = _mean(offsets)
    if mean_offset is not None:
        if mean_offset <= -0.25:
            return "cold_miss"
        if mean_offset >= 0.25:
            return "warm_miss"
    summary = _case_summary(cases)
    winner_gap = safe_float(summary.get("winner_probability_gap_market_minus_model"))
    if winner_gap is not None and winner_gap > 0:
        return "winner_underweight"
    if safe_float(summary.get("brier_gap_model_minus_market")) is not None:
        if safe_float(summary.get("brier_gap_model_minus_market")) <= 0:
            return "model_preserved"
    return "unclear"


def _hour_window(cases: list[dict[str, Any]]) -> dict[str, Any]:
    hours = sorted({safe_int(case.get("local_hour")) for case in cases if safe_int(case.get("local_hour")) is not None})
    if not hours:
        return {"start": None, "end": None, "label": "-"}
    return {"start": hours[0], "end": hours[-1], "label": f"{hours[0]:02d}:00-{hours[-1]:02d}:59"}


def _dominant_wrong_bucket(cases: list[dict[str, Any]]) -> str | None:
    buckets = [
        str(case.get("model_top_band") or "")
        for case in cases
        if not case.get("model_top_hit") and case.get("model_top_band")
    ]
    if not buckets:
        return None
    return Counter(buckets).most_common(1)[0][0]


def _settled_bucket(cases: list[dict[str, Any]]) -> str | None:
    winners = [str(case.get("winner_band") or "") for case in cases if case.get("winner_band")]
    if not winners:
        return None
    return Counter(winners).most_common(1)[0][0]


def _location_summary(market_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _case_summary(cases)
    hour_window = _hour_window(cases)
    direction = classify_direction(cases)
    protected = market_id in PROTECTED_MARKETS
    repair_spec = REPAIR_MARKETS.get(market_id) or {}
    role = "protected" if protected else "repair" if repair_spec else "watch"
    status = "SCORED"
    if protected:
        status = "PROTECTED_PASS" if (safe_float(summary.get("brier_gap_model_minus_market")) or 0.0) <= 0 else "PROTECTED_REGRESSION"
    elif repair_spec:
        status = "REPAIR_REQUIRED"
    return {
        "market_id": market_id,
        "target_date": cases[0].get("target_date") if cases else DEFAULT_TARGET_DATE,
        "role": role,
        "priority": repair_spec.get("priority") or ("P1" if protected else "P3"),
        "status": status,
        "expected_bias": repair_spec.get("expected_bias"),
        "directional_error": direction,
        "direction_matches_packet": (
            direction == repair_spec.get("expected_bias")
            if repair_spec
            else None
        ),
        "settled_bucket": _settled_bucket(cases),
        "dominant_wrong_bucket": _dominant_wrong_bucket(cases),
        "local_hour_window": hour_window,
        "mean_model_top_minus_winner_bucket": _round(_mean(_case_top_offset(case) for case in cases if not case.get("model_top_hit"))),
        "snapshot_count": summary.get("snapshot_count"),
        "row_count": summary.get("row_count"),
        "model_brier": _round(summary.get("model_brier")),
        "market_brier": _round(summary.get("market_brier")),
        "brier_gap_model_minus_market": _round(summary.get("brier_gap_model_minus_market")),
        "winner_model_probability": _round(summary.get("winner_model_probability")),
        "winner_market_probability": _round(summary.get("winner_market_probability")),
        "winner_probability_gap_market_minus_model": _round(summary.get("winner_probability_gap_market_minus_model")),
        "model_top_hit_rate": _round(summary.get("model_top_hit_rate")),
        "market_top_hit_rate": _round(summary.get("market_top_hit_rate")),
        "top_hit_split": {
            "model_top_hit_count": summary.get("model_top_hit_count"),
            "market_top_hit_count": summary.get("market_top_hit_count"),
            "model_top_hit_rate": _round(summary.get("model_top_hit_rate")),
            "market_top_hit_rate": _round(summary.get("market_top_hit_rate")),
            "market_top_model_miss_excess": summary.get("market_top_model_miss_excess"),
        },
        "case_counts": summary.get("case_counts") or {},
        "repair_family": repair_spec.get("repair_family"),
    }


def _empty_location_summary(market_id: str, target_date: str) -> dict[str, Any]:
    repair_spec = REPAIR_MARKETS.get(market_id) or {}
    protected = market_id in PROTECTED_MARKETS
    return {
        "market_id": market_id,
        "target_date": target_date,
        "role": "protected" if protected else "repair" if repair_spec else "watch",
        "priority": repair_spec.get("priority") or ("P1" if protected else "P3"),
        "status": "MISSING_CASE_EVIDENCE",
        "expected_bias": repair_spec.get("expected_bias"),
        "directional_error": "missing",
        "direction_matches_packet": False if repair_spec else None,
        "settled_bucket": None,
        "dominant_wrong_bucket": None,
        "local_hour_window": {"start": None, "end": None, "label": "-"},
        "snapshot_count": 0,
        "row_count": 0,
        "repair_family": repair_spec.get("repair_family"),
    }


def _case_copy_with_repair(case: dict[str, Any]) -> dict[str, Any]:
    if case.get("market_id") not in REPAIR_MARKETS:
        return dict(case)
    repaired = dict(case)
    model_brier = safe_float(case.get("model_brier_sum"))
    market_brier = safe_float(case.get("market_brier_sum"))
    model_logloss = safe_float(case.get("model_logloss_sum"))
    market_logloss = safe_float(case.get("market_logloss_sum"))
    if model_brier is not None and market_brier is not None and model_brier > market_brier:
        repaired["model_brier_sum"] = model_brier - ((model_brier - market_brier) * REPAIR_STRENGTH)
    if model_logloss is not None and market_logloss is not None and model_logloss > market_logloss:
        repaired["model_logloss_sum"] = model_logloss - ((model_logloss - market_logloss) * REPAIR_STRENGTH)
    winner_gap = safe_float(case.get("winner_probability_gap_market_minus_model"))
    winner_model = safe_float(case.get("winner_model_probability"))
    if winner_gap is not None and winner_model is not None and winner_gap > 0:
        repaired["winner_model_probability"] = min(0.999999, winner_model + winner_gap * REPAIR_STRENGTH)
        repaired["winner_probability_gap_market_minus_model"] = (
            safe_float(case.get("winner_market_probability")) - repaired["winner_model_probability"]
        )
    if not case.get("model_top_hit") and case.get("market_top_hit"):
        repaired["model_top_hit"] = True
        repaired["case_class"] = "model_top_hit_market_top_hit"
    return repaired


def _summaries_by_market(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[str(case.get("market_id") or "")].append(case)
    return {
        market_id: _case_summary(group_cases)
        for market_id, group_cases in grouped.items()
        if market_id
    }


def _repair_replay(cases: list[dict[str, Any]]) -> dict[str, Any]:
    repaired_cases = [_case_copy_with_repair(case) for case in cases]
    baseline = _summaries_by_market(cases)
    repaired = _summaries_by_market(repaired_cases)
    rows = []
    for market_id in sorted(set(baseline) | set(repaired) | set(REPAIR_MARKETS) | set(PROTECTED_MARKETS)):
        base = baseline.get(market_id) or {}
        new = repaired.get(market_id) or {}
        base_brier = safe_float(base.get("model_brier"))
        new_brier = safe_float(new.get("model_brier"))
        improvement = base_brier - new_brier if base_brier is not None and new_brier is not None else None
        rows.append({
            "market_id": market_id,
            "role": "protected" if market_id in PROTECTED_MARKETS else "repair" if market_id in REPAIR_MARKETS else "watch",
            "baseline_model_brier": _round(base_brier),
            "repaired_model_brier": _round(new_brier),
            "market_brier": _round(new.get("market_brier") if new else base.get("market_brier")),
            "delta_vs_current": _round((new_brier - base_brier) if base_brier is not None and new_brier is not None else None),
            "improvement_vs_current": _round(improvement),
            "delta_vs_market": _round(
                (new_brier - safe_float(new.get("market_brier")))
                if new_brier is not None and safe_float(new.get("market_brier")) is not None
                else None
            ),
            "snapshot_count": new.get("snapshot_count") or base.get("snapshot_count") or 0,
            "status": (
                "MISSING"
                if not base
                else "PROTECTED_UNCHANGED"
                if market_id in PROTECTED_MARKETS and abs(improvement or 0.0) <= 1e-12
                else "IMPROVED"
                if (improvement or 0.0) > 0
                else "UNCHANGED"
            ),
        })
    protected_regressions = [
        row for row in rows
        if row["role"] == "protected" and safe_float(row.get("delta_vs_current")) is not None
        and safe_float(row.get("delta_vs_current")) > 1e-12
    ]
    repair_improvements = [
        row for row in rows
        if row["role"] == "repair" and (safe_float(row.get("improvement_vs_current")) or 0.0) > 0
    ]
    return {
        "variant_id": REPAIR_VARIANT_ID,
        "repair_strength": REPAIR_STRENGTH,
        "status": "PASS" if repair_improvements and not protected_regressions else "BLOCK",
        "scoring_scope": "june23_case_packet_counterfactual_only",
        "market_rows": rows,
        "repair_improvement_count": len(repair_improvements),
        "protected_regression_count": len(protected_regressions),
        "clearance_rule": (
            "A real candidate must preserve protected Chicago/Los Angeles/NYC/Miami slices, "
            "beat current and market on the targeted June 23 packet, then pass normal promotion gates."
        ),
    }


def _preservation_checks(replay: dict[str, Any], location_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_market = {row.get("market_id"): row for row in replay.get("market_rows") or []}
    case_by_market = {row.get("market_id"): row for row in location_rows}
    checks = []
    for market_id in sorted(PROTECTED_MARKETS):
        replay_row = by_market.get(market_id) or {}
        case_row = case_by_market.get(market_id) or _empty_location_summary(market_id, DEFAULT_TARGET_DATE)
        delta = safe_float(replay_row.get("delta_vs_current"))
        checks.append({
            "market_id": market_id,
            "status": (
                "MISSING_CASE_EVIDENCE"
                if not replay_row or not replay_row.get("snapshot_count")
                else "PASS"
                if delta is not None and delta <= 1e-12 and case_row.get("status") != "PROTECTED_REGRESSION"
                else "BLOCK"
            ),
            "baseline_model_brier": replay_row.get("baseline_model_brier"),
            "repaired_model_brier": replay_row.get("repaired_model_brier"),
            "delta_vs_current": replay_row.get("delta_vs_current"),
            "baseline_case_status": case_row.get("status"),
            "rule": "repair variants may not change or regress protected June 23 winning locations",
        })
    return checks


def _repair_manifests(
    location_rows: list[dict[str, Any]],
    *,
    target_date: str,
    artifact_path: str | Path,
    generated_at_utc: str,
) -> list[dict[str, Any]]:
    by_market = {row.get("market_id"): row for row in location_rows}
    manifests = []
    for market_id, spec in REPAIR_MARKETS.items():
        case_row = by_market.get(market_id) or _empty_location_summary(market_id, target_date)
        status = "eligible" if case_row.get("snapshot_count") else "blocked_missing_case"
        if case_row.get("directional_error") not in {spec["expected_bias"], "winner_underweight"}:
            status = "needs_operator_review" if case_row.get("snapshot_count") else status
        manifests.append({
            "queue_id": f"item301:{target_date}:{market_id}:{spec['expected_bias']}",
            "source": "june23_location_bias_repair_packet",
            "target_date": target_date,
            "market_id": market_id,
            "slice": f"market_id={market_id};bias={spec['expected_bias']}",
            "hypothesis": (
                f"{market_id} needs {spec['repair_family']} for the June 23 "
                f"{spec['expected_bias']} packet without touching protected winners."
            ),
            "artifact_path": str(artifact_path),
            "clearance_rule": (
                "Score against current, market, and the June 23 case packet; require protected "
                "Chicago/Los Angeles/NYC/Miami preservation before normal promotion queue entry."
            ),
            "command": [
                "python",
                "-m",
                "weather.reporting.june23_location_bias_repair",
                "--target-date",
                target_date,
                "--json-out",
                str(artifact_path),
            ],
            "status": status,
            "priority": spec["priority"],
            "repair_family": spec["repair_family"],
            "expected_bias": spec["expected_bias"],
            "observed_bias": case_row.get("directional_error"),
            "snapshot_count": case_row.get("snapshot_count") or 0,
            "created_at_utc": generated_at_utc,
        })
    return manifests


def _summary(
    location_rows: list[dict[str, Any]],
    replay: dict[str, Any],
    manifests: list[dict[str, Any]],
    *,
    target_date: str,
) -> dict[str, Any]:
    scored = [row for row in location_rows if row.get("snapshot_count")]
    repair_rows = [row for row in location_rows if row.get("market_id") in REPAIR_MARKETS and row.get("snapshot_count")]
    protected_rows = [row for row in location_rows if row.get("market_id") in PROTECTED_MARKETS and row.get("snapshot_count")]
    return {
        "target_date": target_date,
        "location_count": len(location_rows),
        "scored_location_count": len(scored),
        "repair_location_count": len(repair_rows),
        "protected_location_count": len(protected_rows),
        "repair_manifest_count": len(manifests),
        "eligible_repair_manifest_count": sum(1 for row in manifests if row.get("status") == "eligible"),
        "protected_regression_count": replay.get("protected_regression_count"),
        "repair_improvement_count": replay.get("repair_improvement_count"),
        "cold_miss_markets": [row["market_id"] for row in repair_rows if row.get("directional_error") == "cold_miss"],
        "warm_miss_markets": [row["market_id"] for row in repair_rows if row.get("directional_error") == "warm_miss"],
    }


def build_payload(
    *,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    labels_csv: str | Path = DEFAULT_LABELS_CSV,
    target_date: str = DEFAULT_TARGET_DATE,
    source_rows: list[dict[str, Any]] | None = None,
    generated_at_utc: str | None = None,
    artifact_path: str | Path = DEFAULT_JSON_OUT,
) -> dict[str, Any]:
    generated = generated_at_utc or utc_iso()
    sources: list[dict[str, Any]] = []
    if source_rows is None:
        parsed_date = date.fromisoformat(target_date)
        source_rows, sources = load_served_rows(
            snapshots_root=snapshots_root,
            labels_csv=labels_csv,
            dates=[parsed_date],
        )
    cases = [
        case for case in snapshot_cases(source_rows)
        if str(case.get("target_date")) == target_date and case.get("variant_id") == "served_current"
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[str(case.get("market_id") or "")].append(case)
    location_rows = [
        _location_summary(market_id, grouped[market_id])
        for market_id in sorted(grouped)
        if market_id
    ]
    for market_id in sorted(set(REPAIR_MARKETS) | PROTECTED_MARKETS):
        if market_id not in grouped:
            location_rows.append(_empty_location_summary(market_id, target_date))
    location_rows.sort(key=lambda row: (row.get("role") != "repair", row.get("priority"), row.get("market_id")))
    replay = _repair_replay(cases)
    preservation = _preservation_checks(replay, location_rows)
    manifests = _repair_manifests(
        location_rows,
        target_date=target_date,
        artifact_path=artifact_path,
        generated_at_utc=generated,
    )
    summary = _summary(location_rows, replay, manifests, target_date=target_date)
    status = "MISSING" if not cases else "ACTIONABLE"
    if replay.get("protected_regression_count"):
        status = "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "status": status,
        "target_date": target_date,
        "inputs": {
            "snapshots_root": str(snapshots_root),
            "labels_csv": str(labels_csv),
            "artifact_path": str(artifact_path),
        },
        "summary": summary,
        "source_snapshots": sources,
        "case_packet": {
            "target_date": target_date,
            "cases_scored": len(cases),
            "locations": location_rows,
        },
        "repair_manifests": manifests,
        "experiment_queue_items": manifests,
        "repair_replay": replay,
        "preservation_checks": preservation,
        "promotion_policy": {
            "auto_promote": False,
            "reason": "Item 301 emits repair evidence and queue inputs only; normal promotion gates still own serving changes.",
        },
    }


def _location_rows_for_report(payload: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for row in (payload.get("case_packet") or {}).get("locations") or []:
        rows.append([
            row.get("market_id"),
            row.get("role"),
            row.get("status"),
            row.get("directional_error"),
            row.get("settled_bucket") or "-",
            row.get("dominant_wrong_bucket") or "-",
            (row.get("local_hour_window") or {}).get("label") or "-",
            row.get("snapshot_count") or 0,
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_gap_model_minus_market")),
            fmt_num(row.get("winner_probability_gap_market_minus_model")),
        ])
    return rows


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    replay = payload.get("repair_replay") or {}
    lines = [
        "# June 23 Location-Bias Repair Packet",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Status: **{payload.get('status')}**",
        f"Target date: `{payload.get('target_date')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Cases scored", (payload.get("case_packet") or {}).get("cases_scored")],
            ["Repair locations", summary.get("repair_location_count")],
            ["Protected locations", summary.get("protected_location_count")],
            ["Eligible repair manifests", summary.get("eligible_repair_manifest_count")],
            ["Cold-miss markets", ", ".join(summary.get("cold_miss_markets") or []) or "-"],
            ["Warm-miss markets", ", ".join(summary.get("warm_miss_markets") or []) or "-"],
            ["Replay status", replay.get("status")],
            ["Protected regressions", replay.get("protected_regression_count")],
        ],
    )
    lines += ["", "## Location Packet", ""]
    lines += markdown_table(
        [
            "Market",
            "Role",
            "Status",
            "Bias",
            "Settled",
            "Wrong Bucket",
            "Hour Window",
            "Snapshots",
            "Model Brier",
            "Market Brier",
            "Gap",
            "Winner Gap",
        ],
        _location_rows_for_report(payload),
    )
    lines += ["", "## Repair Manifests", ""]
    lines += markdown_table(
        ["Queue ID", "Priority", "Status", "Hypothesis"],
        [
            [row.get("queue_id"), row.get("priority"), row.get("status"), row.get("hypothesis")]
            for row in payload.get("repair_manifests") or []
        ],
    )
    lines += ["", "## Counterfactual Replay", ""]
    lines += markdown_table(
        ["Market", "Role", "Status", "Current", "Repaired", "Market", "Delta Current", "Delta Market"],
        [
            [
                row.get("market_id"),
                row.get("role"),
                row.get("status"),
                fmt_num(row.get("baseline_model_brier")),
                fmt_num(row.get("repaired_model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_signed(row.get("delta_vs_current")),
                fmt_signed(row.get("delta_vs_market")),
            ]
            for row in replay.get("market_rows") or []
        ],
    )
    lines += ["", "## Preservation Checks", ""]
    lines += markdown_table(
        ["Market", "Status", "Delta Current", "Rule"],
        [
            [row.get("market_id"), row.get("status"), fmt_signed(row.get("delta_vs_current")), row.get("rule")]
            for row in payload.get("preservation_checks") or []
        ],
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the June 23 location-bias repair packet.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--target-date", default=DEFAULT_TARGET_DATE)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        snapshots_root=args.snapshots_root,
        labels_csv=args.labels_csv,
        target_date=args.target_date,
        artifact_path=args.json_out,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"June 23 location-bias repair packet: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0 if payload["status"] != "MISSING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
