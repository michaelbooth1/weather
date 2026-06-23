"""Current-max trust retrain and ablation evidence report."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.backtesting.replay_backtest import FIDELITY_FAITHFUL_L1, run_replay_backtest
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT
from weather.calibration.pooled_candidate_replay import (
    attach_band_candidate_probabilities,
    build_candidate_features,
    build_clob_feature_index,
    build_source_freshness_index,
    cutoff_regime,
    replay_gate_status,
)
from weather.calibration.pooled_candidate_scoring import (
    candidate_comparison,
    daily_first_candidate_comparison,
    load_artifact,
)
from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.paths import data_path
from weather.reporting.current_max_trust_retrain_gate import TRUST_FIELDS
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    entry_for_folder,
    folders_from_manifest,
    load_manifest,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("current_max_trust_retrain_evidence")
DEFAULT_OUT = data_path("backtest", "current_max_trust_retrain_evidence.json")
DEFAULT_REPORT = data_path("backtest", "current_max_trust_retrain_evidence_report.md")
MODES = ("no_current_max", "raw_current_max", "trust_weighted")
MAX_REGRESSION_TOLERANCE = 0.003
MIN_ABLATION_EFFECT = 1e-9
TRUST_VALUE_FIELDS = (
    "trusted_current_max",
    "support_only_current_max",
    "quarantined_current_max",
    "current_max_gap_to_history",
    "current_max_gap_to_current_temp",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def artifact_trust_field_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    models = artifact.get("models") or {}
    per_hour = []
    missing_by_hour: dict[str, list[str]] = {}
    hours_without_trust_value_statistics: dict[str, list[str]] = {}
    for hour, bundle in sorted(models.items(), key=lambda item: int(item[0])):
        names = set(bundle.get("feature_names") or [])
        ordered_names = list(bundle.get("feature_names") or [])
        imputer_statistics = getattr(bundle.get("imputer"), "statistics_", None)
        imputer_stats = list(imputer_statistics) if imputer_statistics is not None else []
        missing = [field for field in TRUST_FIELDS if field not in names]
        missing_value_statistics = []
        present_value_statistics = []
        for field in TRUST_VALUE_FIELDS:
            if field not in names:
                missing_value_statistics.append(field)
                continue
            index = ordered_names.index(field)
            value = imputer_stats[index] if index < len(imputer_stats) else None
            if finite_float(value) is None:
                missing_value_statistics.append(field)
            else:
                present_value_statistics.append(field)
        per_hour.append({
            "hour": int(hour),
            "feature_count": len(names),
            "trust_fields_present": [field for field in TRUST_FIELDS if field in names],
            "missing_trust_fields": missing,
            "trust_value_statistics_present": present_value_statistics,
            "missing_trust_value_statistics": missing_value_statistics,
        })
        if missing:
            missing_by_hour[str(hour)] = missing
        if not present_value_statistics:
            hours_without_trust_value_statistics[str(hour)] = missing_value_statistics
    return {
        "hour_model_count": len(models),
        "all_hours_have_trust_fields": not missing_by_hour and bool(models),
        "all_hours_have_trust_value_statistics": not hours_without_trust_value_statistics and bool(models),
        "missing_by_hour": missing_by_hour,
        "hours_without_trust_value_statistics": hours_without_trust_value_statistics,
        "per_hour": per_hour,
    }


def raw_current_max_value(row: dict[str, Any]) -> float | None:
    values = [
        finite_float(row.get("trusted_current_max")),
        finite_float(row.get("support_only_current_max")),
        finite_float(row.get("quarantined_current_max")),
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def feature_row_current_max_state(row: dict[str, Any]) -> str:
    if finite_float(row.get("quarantined_current_max")) is not None or row.get("current_max_quarantined_flag"):
        return "quarantined"
    if finite_float(row.get("support_only_current_max")) is not None or row.get("current_max_support_only_flag"):
        return "support_only"
    if finite_float(row.get("trusted_current_max")) is not None or row.get("current_max_trusted_flag"):
        return "trusted"
    return "missing"


def transform_current_max_row(row: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unknown current-max ablation mode: {mode}")
    copy_row = dict(row)
    if mode == "trust_weighted":
        return copy_row
    if mode == "no_current_max":
        for field in TRUST_FIELDS:
            copy_row[field] = None
        for flag in (
            "current_max_trusted_flag",
            "current_max_support_only_flag",
            "current_max_quarantined_flag",
        ):
            copy_row[flag] = 0.0
        copy_row["current_max_state"] = "missing_current_max"
        copy_row["current_max_disposition"] = "missing"
        copy_row["current_max_quarantine_reason"] = ""
        return copy_row

    raw_value = raw_current_max_value(row)
    copy_row["trusted_current_max"] = raw_value
    copy_row["support_only_current_max"] = None
    copy_row["quarantined_current_max"] = None
    copy_row["current_max_trusted_flag"] = 1.0 if raw_value is not None else 0.0
    copy_row["current_max_support_only_flag"] = 0.0
    copy_row["current_max_quarantined_flag"] = 0.0
    copy_row["current_max_state"] = (
        "raw_current_max_promoted" if raw_value is not None else "missing_current_max"
    )
    copy_row["current_max_disposition"] = "validated" if raw_value is not None else "missing"
    copy_row["current_max_quarantine_reason"] = ""
    return copy_row


def transformed_feature_rows(
    feature_rows: dict[tuple[str, str], dict[str, Any]],
    mode: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    return {key: transform_current_max_row(row, mode) for key, row in feature_rows.items()}


def current_max_state_index(feature_rows: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {key: feature_row_current_max_state(row) for key, row in feature_rows.items()}


def _candidate_rows_for_mode(
    *,
    replay_results: dict[str, Any],
    feature_rows: dict[tuple[str, str], dict[str, Any]],
    artifact: dict[str, Any],
    family_unit: str,
    clob_features: dict[Any, dict[str, Any]],
    source_freshness: dict[tuple[str, str], str],
    mode: str,
    state_index: dict[tuple[str, str], str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows, coverage = attach_band_candidate_probabilities(
        replay_results,
        transformed_feature_rows(feature_rows, mode),
        artifact,
        family_unit,
        clob_features=clob_features,
        source_freshness=source_freshness,
    )
    for row in rows:
        hour = row.get("candidate_cutoff_hour")
        row["candidate_cutoff_regime"] = cutoff_regime(hour)
        key = (row.get("market_id"), str(row.get("snapshot_id")))
        row["current_max_ablation_state"] = state_index.get(key, "missing")
    return rows, coverage


def _is_early(row: dict[str, Any]) -> bool:
    try:
        return int(float(row.get("candidate_cutoff_hour"))) <= 8
    except (TypeError, ValueError):
        return False


def _is_late_lock_in(row: dict[str, Any]) -> bool:
    try:
        return int(float(row.get("candidate_cutoff_hour"))) >= 17
    except (TypeError, ValueError):
        return False


def _is_warm_tail(row: dict[str, Any]) -> bool:
    if row.get("forecast_bucket_pressure") == "warm_side":
        return True
    try:
        return float(row.get("band_mid_minus_high_so_far") or 0.0) >= 2.0
    except (TypeError, ValueError):
        return False


def _is_risky_current_max(row: dict[str, Any]) -> bool:
    return row.get("current_max_ablation_state") in {"support_only", "quarantined"}


def _score_slice(rows: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    return candidate_comparison([row for row in rows if predicate(row)])


def score_mode_rows(rows: list[dict[str, Any]], coverage: dict[str, Any]) -> dict[str, Any]:
    state_counts = Counter(row.get("current_max_ablation_state") or "missing" for row in rows)
    return {
        "coverage": coverage,
        "state_counts": dict(sorted(state_counts.items())),
        "aggregate": candidate_comparison(rows),
        "daily_first": daily_first_candidate_comparison(rows),
        "early_hour": _score_slice(rows, _is_early),
        "warm_tail": _score_slice(rows, _is_warm_tail),
        "risky_current_max": _score_slice(rows, _is_risky_current_max),
        "late_lock_in": _score_slice(rows, _is_late_lock_in),
    }


def _brier(summary: dict[str, Any] | None) -> float | None:
    return (summary or {}).get("candidate_brier")


def _current_brier(summary: dict[str, Any] | None) -> float | None:
    return (summary or {}).get("current_brier")


def _logloss(summary: dict[str, Any] | None) -> float | None:
    return (summary or {}).get("candidate_logloss")


def _current_logloss(summary: dict[str, Any] | None) -> float | None:
    return (summary or {}).get("current_logloss")


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def current_max_trust_ablation_decision(
    mode_scores: dict[str, dict[str, Any]],
    *,
    tolerance: float = MAX_REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    trust = mode_scores.get("trust_weighted") or {}
    raw = mode_scores.get("raw_current_max") or {}
    no_current = mode_scores.get("no_current_max") or {}
    checks = []

    def add_pair_check(name: str, left: dict[str, Any] | None, right: dict[str, Any] | None, metric: str = "brier"):
        getter = _brier if metric == "brier" else _logloss
        left_value = getter(left)
        right_value = getter(right)
        delta = _delta(left_value, right_value)
        passed = delta is not None and delta <= tolerance
        checks.append({
            "check": name,
            "metric": metric,
            "trust_weighted": left_value,
            "comparison": right_value,
            "delta": delta,
            "tolerance": float(tolerance),
            "passed": passed,
        })

    def add_current_check(
        name: str,
        summary: dict[str, Any] | None,
        metric: str = "brier",
        *,
        max_delta: float = 0.0,
    ):
        candidate_getter = _brier if metric == "brier" else _logloss
        current_getter = _current_brier if metric == "brier" else _current_logloss
        candidate_value = candidate_getter(summary)
        current_value = current_getter(summary)
        delta = _delta(candidate_value, current_value)
        passed = delta is not None and delta <= max_delta
        checks.append({
            "check": name,
            "metric": metric,
            "trust_weighted": candidate_value,
            "comparison": current_value,
            "delta": delta,
            "tolerance": float(max_delta),
            "passed": passed,
        })

    add_pair_check("risky_current_max_brier_vs_raw", trust.get("risky_current_max"), raw.get("risky_current_max"))
    add_pair_check("warm_tail_brier_vs_raw", trust.get("warm_tail"), raw.get("warm_tail"))
    add_pair_check("early_hour_brier_vs_raw", trust.get("early_hour"), raw.get("early_hour"))
    add_pair_check("early_hour_logloss_vs_raw", trust.get("early_hour"), raw.get("early_hour"), metric="logloss")
    add_pair_check("late_lock_in_brier_vs_raw", trust.get("late_lock_in"), raw.get("late_lock_in"))
    add_pair_check("daily_first_brier_vs_no_current_max", trust.get("daily_first"), no_current.get("daily_first"))
    add_current_check("risky_current_max_brier_vs_current", trust.get("risky_current_max"))
    add_current_check("warm_tail_brier_vs_current", trust.get("warm_tail"))
    add_current_check("early_hour_brier_vs_current", trust.get("early_hour"), max_delta=tolerance)
    add_current_check("early_hour_logloss_vs_current", trust.get("early_hour"), metric="logloss", max_delta=tolerance)
    add_current_check("late_lock_in_brier_vs_current", trust.get("late_lock_in"), max_delta=tolerance)

    sensitivity_deltas = [
        delta
        for left, right, getter in (
            (trust.get("risky_current_max"), raw.get("risky_current_max"), _brier),
            (trust.get("warm_tail"), raw.get("warm_tail"), _brier),
            (trust.get("early_hour"), raw.get("early_hour"), _brier),
            (trust.get("early_hour"), raw.get("early_hour"), _logloss),
            (trust.get("late_lock_in"), raw.get("late_lock_in"), _brier),
            (trust.get("daily_first"), no_current.get("daily_first"), _brier),
        )
        for delta in [_delta(getter(left), getter(right))]
        if delta is not None
    ]
    max_effect = max((abs(delta) for delta in sensitivity_deltas), default=None)
    checks.append({
        "check": "current_max_ablation_mode_sensitivity",
        "metric": "max_abs_delta",
        "trust_weighted": max_effect,
        "comparison": MIN_ABLATION_EFFECT,
        "delta": max_effect,
        "tolerance": MIN_ABLATION_EFFECT,
        "passed": max_effect is not None and max_effect > MIN_ABLATION_EFFECT,
    })

    missing = [check["check"] for check in checks if check["delta"] is None]
    failed = [check for check in checks if not check["passed"]]
    return {
        "status": "PASS" if not failed else "BLOCK",
        "policy": "trust_weighted_must_improve_current_risky_and_warm_tail_without_regressing_raw_no_current_or_late_lockin",
        "tolerance": float(tolerance),
        "minimum_ablation_effect": MIN_ABLATION_EFFECT,
        "checks": checks,
        "missing_checks": missing,
        "failed_checks": failed,
        "trust_weighted_delta_vs_raw": _delta(
            _brier(trust.get("daily_first")),
            _brier(raw.get("daily_first")),
        ),
        "trust_weighted_delta_vs_no_current_max": _delta(
            _brier(trust.get("daily_first")),
            _brier(no_current.get("daily_first")),
        ),
    }


def _folder_list(manifest: dict[str, Any], snapshots_root: str | Path, max_snapshots: int | None = None) -> list[str]:
    folders = []
    remaining = int(max_snapshots) if max_snapshots else None
    for folder in folders_from_manifest(manifest, snapshots_root):
        if remaining is None:
            folders.append(str(folder))
            continue
        entry = entry_for_folder(manifest, folder)
        count = len((entry or {}).get("snapshot_ids") or [])
        if count <= 0:
            continue
        if remaining <= 0:
            break
        folders.append(str(folder))
        remaining -= count
    return folders


def build_payload(
    *,
    artifact_path: str | Path = DEFAULT_BAND_ARTIFACT,
    corpus_path: str | Path = DEFAULT_CORPUS,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    max_snapshots: int | None = None,
    tolerance: float = MAX_REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    artifact = load_artifact(artifact_path)
    manifest = load_manifest(corpus_path)
    family_unit = artifact.get("family_unit") or "F"
    folders = _folder_list(manifest, snapshots_root, max_snapshots=max_snapshots)
    replay_results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=None,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=False,
        corpus_manifest=manifest,
    )
    replay_gate = replay_gate_status(replay_results, max_fidelity_l1=FIDELITY_FAITHFUL_L1)
    feature_rows, diagnostics = build_candidate_features(
        manifest,
        snapshots_root,
        family_unit,
        artifact=artifact,
    )
    if max_snapshots:
        replay_keys = {
            (row.get("market_id"), str(row.get("snapshot_id")))
            for row in replay_results.get("all_rows") or []
        }
        feature_rows = {key: row for key, row in feature_rows.items() if key in replay_keys}
    clob_features, clob_diagnostics = build_clob_feature_index(
        manifest,
        snapshots_root,
        family_unit,
    )
    source_freshness, source_diagnostics = build_source_freshness_index(
        manifest,
        snapshots_root,
        family_unit,
    )
    diagnostics.update(clob_diagnostics)
    diagnostics.update(source_diagnostics)
    state_index = current_max_state_index(feature_rows)
    mode_scores = {}
    for mode in MODES:
        rows, coverage = _candidate_rows_for_mode(
            replay_results=replay_results,
            feature_rows=feature_rows,
            artifact=artifact,
            family_unit=family_unit,
            clob_features=clob_features,
            source_freshness=source_freshness,
            mode=mode,
            state_index=state_index,
        )
        mode_scores[mode] = score_mode_rows(rows, coverage)

    trust_summary = artifact_trust_field_summary(artifact)
    ablation = current_max_trust_ablation_decision(mode_scores, tolerance=tolerance)
    schema_ok = artifact.get("feature_schema_version") == FEATURE_SCHEMA_VERSION
    status = (
        "PASS"
        if (
            schema_ok
            and trust_summary["all_hours_have_trust_fields"]
            and trust_summary["all_hours_have_trust_value_statistics"]
            and ablation["status"] == "PASS"
        )
        else "BLOCK"
    )
    blockers = []
    if not schema_ok:
        blockers.append({
            "blocker": "artifact_feature_schema_version",
            "detail": (
                f"artifact schema {artifact.get('feature_schema_version')} != active "
                f"{FEATURE_SCHEMA_VERSION}"
            ),
        })
    if not trust_summary["all_hours_have_trust_fields"]:
        blockers.append({
            "blocker": "artifact_trust_fields",
            "detail": "one or more hour models are missing current-max trust fields",
            "missing_by_hour": trust_summary["missing_by_hour"],
        })
    if not trust_summary["all_hours_have_trust_value_statistics"]:
        blockers.append({
            "blocker": "artifact_trust_value_training_coverage",
            "detail": "one or more hour models have no non-null trainable current-max trust value statistics",
            "hours_without_trust_value_statistics": trust_summary["hours_without_trust_value_statistics"],
        })
    if ablation["status"] != "PASS":
        blockers.append({
            "blocker": "current_max_trust_ablation",
            "detail": "trust-weighted current-max treatment did not clear ablation checks",
            "failed_checks": ablation["failed_checks"],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "artifact": {
            "path": str(artifact_path),
            "schema_version": artifact.get("schema_version"),
            "feature_schema_version": artifact.get("feature_schema_version"),
            "trained_at": artifact.get("trained_at"),
            "family_unit": family_unit,
            "prediction_mode": artifact.get("prediction_mode"),
            "objective": artifact.get("objective"),
            "hour_models": sorted(int(hour) for hour in (artifact.get("models") or {})),
            "trust_fields": trust_summary,
        },
        "corpus": {
            "path": str(corpus_path),
            "snapshots_root": str(snapshots_root),
            "max_snapshots": max_snapshots,
            "folder_count": len(folders),
        },
        "replay_gate": replay_gate,
        "diagnostics": diagnostics,
        "mode_scores": mode_scores,
        "current_max_trust_ablation": ablation,
        "early_hour": mode_scores["trust_weighted"].get("early_hour"),
        "late_lock_in": mode_scores["trust_weighted"].get("late_lock_in"),
    }


def render_report(payload: dict[str, Any]) -> str:
    artifact = payload.get("artifact") or {}
    ablation = payload.get("current_max_trust_ablation") or {}
    lines = [
        "# Current-Max Trust Retrain Evidence",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Blockers", payload.get("blocker_count")],
            ["Feature schema", payload.get("feature_schema_version")],
            ["Artifact schema", artifact.get("feature_schema_version")],
            ["Hour models", len(artifact.get("hour_models") or [])],
            ["All hours have trust fields", (artifact.get("trust_fields") or {}).get("all_hours_have_trust_fields")],
            ["All hours have trainable trust values", (artifact.get("trust_fields") or {}).get("all_hours_have_trust_value_statistics")],
            ["Ablation status", ablation.get("status")],
            ["Daily-first trust vs raw", fmt_signed(ablation.get("trust_weighted_delta_vs_raw"), 4)],
            ["Daily-first trust vs no current-max", fmt_signed(ablation.get("trust_weighted_delta_vs_no_current_max"), 4)],
        ],
    )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Blocker", "Detail"],
            [[row.get("blocker"), row.get("detail")] for row in payload.get("blockers") or []],
        )
    lines += ["", "## Mode Scores", ""]
    rows = []
    for mode, scores in (payload.get("mode_scores") or {}).items():
        daily = scores.get("daily_first") or {}
        early = scores.get("early_hour") or {}
        risky = scores.get("risky_current_max") or {}
        late = scores.get("late_lock_in") or {}
        rows.append([
            mode,
            daily.get("n_days"),
            fmt_num(daily.get("candidate_brier"), 4),
            fmt_num(early.get("candidate_brier"), 4),
            fmt_num(risky.get("candidate_brier"), 4),
            fmt_num(late.get("candidate_brier"), 4),
        ])
    lines += markdown_table(
        ["Mode", "Days", "Daily-first Brier", "Early Brier", "Risky Current-Max Brier", "Late Lock-In Brier"],
        rows,
    )
    lines += ["", "## Ablation Checks", ""]
    lines += markdown_table(
        ["Check", "Metric", "Trust", "Comparison", "Delta", "Tolerance", "Pass"],
        [
            [
                row.get("check"),
                row.get("metric"),
                fmt_num(row.get("trust_weighted"), 4),
                fmt_num(row.get("comparison"), 4),
                fmt_signed(row.get("delta"), 4),
                fmt_num(row.get("tolerance"), 4),
                row.get("passed"),
            ]
            for row in ablation.get("checks") or []
        ],
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate current-max trust retrain ablation evidence.")
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--max-snapshots", type=int, default=None)
    parser.add_argument("--tolerance", type=float, default=MAX_REGRESSION_TOLERANCE)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        artifact_path=args.artifact,
        corpus_path=args.corpus,
        snapshots_root=args.snapshots_root,
        max_snapshots=args.max_snapshots,
        tolerance=args.tolerance,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Current-max trust retrain evidence: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
