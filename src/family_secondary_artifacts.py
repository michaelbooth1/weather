"""Family-level secondary artifact trainer and trust gate.

Roadmap item 34 moves the Toronto-only calibration stack to the Fahrenheit
family. The existing secondary artifact modules already train one market at a
time; this module orchestrates the family run, records a manifest, and exposes a
small serving gate so unproven markets fall back to empirical probabilities.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import forecast_error_model as forecast_error  # noqa: E402
import probability_calibration as probability_calibration  # noqa: E402
import settlement_lag_model as settlement_lag  # noqa: E402
from backtest import DEFAULT_SNAPSHOTS_ROOT, markdown_table  # noqa: E402
from forecast_history import daily_path_for  # noqa: E402
from location_trust import score_all_markets  # noqa: E402
from market_registry import all_specs  # noqa: E402


SCHEMA_VERSION = "family_secondary_artifacts_v0.1"
DEFAULT_FAMILY_UNIT = "F"
DEFAULT_MANIFEST = Path("src") / "f_family_secondary_artifacts.json"
DEFAULT_REPORT = Path("data") / "backtest" / "f_family_secondary_artifacts_report.md"
DEFAULT_MIN_TRUST = 25
DEFAULT_MIN_SETTLED_DAYS = 2
DEFAULT_QUALITY_GRADES = "complete,manual_override"

ARTIFACT_KINDS = ("probability_calibration", "forecast_error", "settlement_lag")


def family_specs(unit=DEFAULT_FAMILY_UNIT):
    return [spec for spec in all_specs() if spec.display_unit == unit]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def artifact_paths(spec):
    return {
        "probability_calibration": {
            "artifact": Path("src") / f"probability_calibration{spec.artifact_suffix}.json",
            "report": Path("data") / "backtest" / f"probability_calibration_report{spec.artifact_suffix}.md",
        },
        "forecast_error": {
            "artifact": Path("src") / f"forecast_error_model{spec.artifact_suffix}.json",
            "report": Path("data") / "backtest" / f"forecast_error_report{spec.artifact_suffix}.md",
        },
        "settlement_lag": {
            "artifact": Path("src") / f"settlement_lag_model{spec.artifact_suffix}.json",
            "report": Path("data") / "backtest" / f"settlement_lag_report{spec.artifact_suffix}.md",
        },
    }


def family_artifact_paths(family_unit):
    suffix = family_unit.lower()
    return {
        "probability_calibration": {
            "artifact": Path("src") / f"probability_calibration_{suffix}_family.json",
            "report": Path("data") / "backtest" / f"probability_calibration_report_{suffix}_family.md",
        },
        "forecast_error": {
            "artifact": Path("src") / f"forecast_error_model_{suffix}_family.json",
            "report": Path("data") / "backtest" / f"forecast_error_report_{suffix}_family.md",
        },
        "settlement_lag": {
            "artifact": Path("src") / f"settlement_lag_model_{suffix}_family.json",
            "report": Path("data") / "backtest" / f"settlement_lag_report_{suffix}_family.md",
        },
    }


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _accepted_quality_grades(value):
    return [grade.strip() for grade in str(value).split(",") if grade.strip()]


def _relative(path):
    return Path(path).as_posix()


def _error_status(exc):
    return {"status": "error", "error": str(exc)}


def probability_training_rows(spec, snapshots_root, quality_grades):
    folders = probability_calibration.discover_default_folders(snapshots_root, market_id=spec.id)
    skipped = []
    if quality_grades != ["all"]:
        folders, skipped = probability_calibration.filter_folders_by_quality(folders, quality_grades)
    if not folders:
        return [], folders, skipped
    rows = probability_calibration.read_scored_rows(
        folders,
        daily_summary_path=spec.data_root / "daily" / "daily_summary.csv",
    )
    return rows, folders, skipped


def train_probability_artifact(spec, snapshots_root, quality_grades):
    paths = artifact_paths(spec)["probability_calibration"]
    rows, folders, skipped = probability_training_rows(spec, snapshots_root, quality_grades)
    if not folders:
        return {
            "status": "skipped",
            "reason": "no folders after quality filter",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": 0,
            "skipped_count": len(skipped),
        }
    if not rows:
        return {
            "status": "skipped",
            "reason": "no scored rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
            "skipped_count": len(skipped),
        }
    artifact = probability_calibration.build_artifact(rows, folders)
    artifact["training"]["quality_grades"] = quality_grades
    _write_json(paths["artifact"], artifact)
    probability_calibration.write_report(paths["report"], artifact)
    selected = artifact.get("selected_deployable_candidate") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "skipped_count": len(skipped),
        "row_count": len(rows),
        "baseline_brier": (artifact.get("training") or {}).get("baseline_brier"),
        "artifact_replay_brier": (artifact.get("training") or {}).get("artifact_replay_brier"),
        "selected_method": selected.get("method"),
        "selected_param": selected.get("param"),
    }


def train_family_probability_artifact(specs, family_unit, snapshots_root, quality_grades):
    paths = family_artifact_paths(family_unit)["probability_calibration"]
    rows = []
    folders = []
    market_rows = {}
    skipped_count = 0
    for spec in specs:
        spec_rows, spec_folders, skipped = probability_training_rows(spec, snapshots_root, quality_grades)
        rows.extend(spec_rows)
        folders.extend(spec_folders)
        skipped_count += len(skipped)
        market_rows[spec.id] = len(spec_rows)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no family probability rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = probability_calibration.build_artifact(rows, folders)
    artifact["family_unit"] = family_unit
    artifact["training"]["quality_grades"] = quality_grades
    artifact["training"]["market_rows"] = market_rows
    _write_json(paths["artifact"], artifact)
    probability_calibration.write_report(paths["report"], artifact)
    selected = artifact.get("selected_deployable_candidate") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "skipped_count": skipped_count,
        "row_count": len(rows),
        "market_rows": market_rows,
        "baseline_brier": (artifact.get("training") or {}).get("baseline_brier"),
        "artifact_replay_brier": (artifact.get("training") or {}).get("artifact_replay_brier"),
        "selected_method": selected.get("method"),
        "selected_param": selected.get("param"),
    }


def train_forecast_error_artifact(spec, snapshots_root):
    paths = artifact_paths(spec)["forecast_error"]
    folders = forecast_error.discover_default_folders(snapshots_root, market_id=spec.id)
    rows = forecast_error.read_training_rows(
        daily_path_for(spec),
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
    )
    if not rows:
        return {
            "status": "skipped",
            "reason": "no forecast error rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = forecast_error.build_artifact(rows, folders)
    _write_json(paths["artifact"], artifact)
    forecast_error.write_report(paths["report"], artifact)
    replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "row_count": len(rows),
        "learned_brier": replay.get("learned_brier"),
        "cap_brier": replay.get("cap_brier"),
    }


def forecast_error_training_rows(spec, snapshots_root):
    folders = forecast_error.discover_default_folders(snapshots_root, market_id=spec.id)
    rows = forecast_error.read_training_rows(
        daily_path_for(spec),
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
    )
    return rows, folders


def train_family_forecast_error_artifact(specs, family_unit, snapshots_root):
    paths = family_artifact_paths(family_unit)["forecast_error"]
    rows = []
    folders = []
    market_rows = {}
    for spec in specs:
        spec_rows, spec_folders = forecast_error_training_rows(spec, snapshots_root)
        rows.extend(spec_rows)
        folders.extend(spec_folders)
        market_rows[spec.id] = len(spec_rows)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no family forecast error rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = forecast_error.build_artifact(rows, folders)
    artifact["family_unit"] = family_unit
    artifact["training"]["market_rows"] = market_rows
    _write_json(paths["artifact"], artifact)
    forecast_error.write_report(paths["report"], artifact)
    replay = (artifact.get("evaluation") or {}).get("artifact_replay") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "row_count": len(rows),
        "market_rows": market_rows,
        "learned_brier": replay.get("learned_brier"),
        "cap_brier": replay.get("cap_brier"),
    }


def train_settlement_lag_artifact(spec, snapshots_root):
    paths = artifact_paths(spec)["settlement_lag"]
    folders = settlement_lag.discover_default_folders(snapshots_root, market_id=spec.id)
    rows = settlement_lag.read_training_rows(
        spec.data_root / "hourly",
        Path("data") / "metar" / spec.icao.lower() / "hourly",
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
    )
    if not rows:
        return {
            "status": "skipped",
            "reason": "no settlement lag rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = settlement_lag.build_artifact(rows, folders)
    _write_json(paths["artifact"], artifact)
    settlement_lag.write_report(paths["report"], artifact)
    global_context = (artifact.get("catchup_contexts") or {}).get("global") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "lead_rows": (artifact.get("training") or {}).get("lead_rows"),
        "revision_rows": (artifact.get("training") or {}).get("revision_rows"),
        "global_catchup_rate": global_context.get("catchup_rate"),
    }


def settlement_lag_training_rows(spec, snapshots_root):
    folders = settlement_lag.discover_default_folders(snapshots_root, market_id=spec.id)
    rows = settlement_lag.read_training_rows(
        spec.data_root / "hourly",
        Path("data") / "metar" / spec.icao.lower() / "hourly",
        spec.data_root / "daily" / "daily_summary.csv",
        folders,
    )
    return rows, folders


def train_family_settlement_lag_artifact(specs, family_unit, snapshots_root):
    paths = family_artifact_paths(family_unit)["settlement_lag"]
    rows = []
    folders = []
    market_rows = {}
    for spec in specs:
        spec_rows, spec_folders = settlement_lag_training_rows(spec, snapshots_root)
        rows.extend(spec_rows)
        folders.extend(spec_folders)
        market_rows[spec.id] = len(spec_rows)
    if not rows:
        return {
            "status": "skipped",
            "reason": "no family settlement lag rows",
            "artifact": _relative(paths["artifact"]),
            "report": _relative(paths["report"]),
            "folder_count": len(folders),
        }
    artifact = settlement_lag.build_artifact(rows, folders)
    artifact["family_unit"] = family_unit
    artifact["training"]["market_rows"] = market_rows
    _write_json(paths["artifact"], artifact)
    settlement_lag.write_report(paths["report"], artifact)
    global_context = (artifact.get("catchup_contexts") or {}).get("global") or {}
    return {
        "status": "ok",
        "artifact": _relative(paths["artifact"]),
        "report": _relative(paths["report"]),
        "folder_count": len(folders),
        "market_rows": market_rows,
        "lead_rows": (artifact.get("training") or {}).get("lead_rows"),
        "revision_rows": (artifact.get("training") or {}).get("revision_rows"),
        "global_catchup_rate": global_context.get("catchup_rate"),
    }


def gate_for_market(trust_row, artifacts, family_artifacts=None, min_trust=DEFAULT_MIN_TRUST,
                    min_settled_days=DEFAULT_MIN_SETTLED_DAYS):
    trust_score = (trust_row or {}).get("trust_score")
    settled_days = (trust_row or {}).get("settled_days", 0)
    reasons = []
    if trust_score is None or int(trust_score) < int(min_trust):
        reasons.append(f"trust {trust_score if trust_score is not None else '-'} < {min_trust}")
    if int(settled_days or 0) < int(min_settled_days):
        reasons.append(f"settled_days {settled_days or 0} < {min_settled_days}")
    missing = [
        kind for kind in ARTIFACT_KINDS
        if (artifacts.get(kind) or {}).get("status") != "ok"
    ]
    if missing:
        reasons.append("missing artifacts: " + ", ".join(missing))
    missing_family = [
        kind for kind in ARTIFACT_KINDS
        if family_artifacts is not None
        and (family_artifacts.get(kind) or {}).get("status") != "ok"
    ]
    if missing_family:
        reasons.append("missing family artifacts: " + ", ".join(missing_family))
    mode = "ml" if not reasons else "empirical"
    return {
        "mode": mode,
        "reason": "; ".join(reasons) if reasons else "trust and artifacts clear",
        "min_trust_score": int(min_trust),
        "min_settled_days": int(min_settled_days),
    }


def build_family_manifest(family_unit=DEFAULT_FAMILY_UNIT, snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
                          quality_grades=DEFAULT_QUALITY_GRADES,
                          min_trust=DEFAULT_MIN_TRUST,
                          min_settled_days=DEFAULT_MIN_SETTLED_DAYS):
    quality = _accepted_quality_grades(quality_grades)
    specs = family_specs(family_unit)
    family_artifacts = {}
    try:
        family_artifacts["probability_calibration"] = train_family_probability_artifact(
            specs,
            family_unit,
            snapshots_root,
            quality,
        )
    except Exception as exc:  # noqa: BLE001
        family_artifacts["probability_calibration"] = _error_status(exc)
    try:
        family_artifacts["forecast_error"] = train_family_forecast_error_artifact(
            specs,
            family_unit,
            snapshots_root,
        )
    except Exception as exc:  # noqa: BLE001
        family_artifacts["forecast_error"] = _error_status(exc)
    try:
        family_artifacts["settlement_lag"] = train_family_settlement_lag_artifact(
            specs,
            family_unit,
            snapshots_root,
        )
    except Exception as exc:  # noqa: BLE001
        family_artifacts["settlement_lag"] = _error_status(exc)
    trust_rows = {
        row["market"]: row
        for row in score_all_markets(root=snapshots_root)
        if row.get("market")
    }
    markets = {}
    for spec in specs:
        artifacts = {}
        try:
            artifacts["probability_calibration"] = train_probability_artifact(
                spec,
                snapshots_root,
                quality,
            )
        except Exception as exc:  # noqa: BLE001 - one market must not kill the family run
            artifacts["probability_calibration"] = _error_status(exc)
        try:
            artifacts["forecast_error"] = train_forecast_error_artifact(spec, snapshots_root)
        except Exception as exc:  # noqa: BLE001
            artifacts["forecast_error"] = _error_status(exc)
        try:
            artifacts["settlement_lag"] = train_settlement_lag_artifact(spec, snapshots_root)
        except Exception as exc:  # noqa: BLE001
            artifacts["settlement_lag"] = _error_status(exc)

        trust = trust_rows.get(spec.id) or {}
        gate = gate_for_market(
            trust,
            artifacts,
            family_artifacts=family_artifacts,
            min_trust=min_trust,
            min_settled_days=min_settled_days,
        )
        markets[spec.id] = {
            "city": spec.city_label,
            "unit": spec.display_unit,
            "artifact_suffix": spec.artifact_suffix,
            "trust": trust,
            "artifacts": artifacts,
            "serving_gate": gate,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "family_unit": family_unit,
        "snapshots_root": str(snapshots_root),
        "quality_grades": quality,
        "family_artifacts": family_artifacts,
        "gate": {
            "min_trust_score": int(min_trust),
            "min_settled_days": int(min_settled_days),
            "default_mode": "empirical",
            "policy": "serve feature ML only when trust and all secondary artifacts clear",
        },
        "markets": markets,
    }


def load_family_secondary_manifest(path=DEFAULT_MANIFEST):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - serving should fall back cleanly
        print(f"Error loading family secondary artifact manifest: {exc}")
        return None


def market_gate(manifest, market_id):
    if not manifest:
        return {"mode": "ml", "reason": "no family secondary manifest"}
    market = (manifest.get("markets") or {}).get(market_id)
    if not market:
        return {"mode": "ml", "reason": "market not governed by manifest"}
    return market.get("serving_gate") or {"mode": "empirical", "reason": "missing serving gate"}


def feature_model_allowed(manifest, market_id):
    return market_gate(manifest, market_id).get("mode") == "ml"


def _fmt(value, decimals=4):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def write_report(path, manifest):
    family_rows = []
    for kind, artifact in sorted((manifest.get("family_artifacts") or {}).items()):
        family_rows.append([
            kind,
            artifact.get("status"),
            artifact.get("artifact"),
            artifact.get("row_count") or artifact.get("lead_rows") or "-",
            _fmt(artifact.get("artifact_replay_brier")
                 or artifact.get("learned_brier")
                 or artifact.get("global_catchup_rate")),
        ])
    rows = []
    for market_id, market in sorted((manifest.get("markets") or {}).items()):
        artifacts = market.get("artifacts") or {}
        trust = market.get("trust") or {}
        gate = market.get("serving_gate") or {}
        rows.append([
            market_id,
            market.get("city"),
            trust.get("trust_score"),
            trust.get("settled_days"),
            gate.get("mode"),
            gate.get("reason"),
            (artifacts.get("probability_calibration") or {}).get("status"),
            _fmt((artifacts.get("probability_calibration") or {}).get("artifact_replay_brier")),
            (artifacts.get("forecast_error") or {}).get("status"),
            _fmt((artifacts.get("forecast_error") or {}).get("learned_brier")),
            (artifacts.get("settlement_lag") or {}).get("status"),
            (artifacts.get("settlement_lag") or {}).get("lead_rows"),
        ])
    lines = [
        "# F-Family Secondary Artifacts",
        "",
        f"Generated: {manifest.get('generated_at_utc')}",
        f"Schema: `{manifest.get('schema_version')}`",
        f"Family unit: `{manifest.get('family_unit')}`",
        "",
        "## Serving Gate",
        "",
        f"- Minimum trust score: `{(manifest.get('gate') or {}).get('min_trust_score')}`",
        f"- Minimum settled days: `{(manifest.get('gate') or {}).get('min_settled_days')}`",
        f"- Default mode: `{(manifest.get('gate') or {}).get('default_mode')}`",
        "",
        "## Family Artifacts",
        "",
    ]
    lines += markdown_table(
        ["Kind", "Status", "Artifact", "Rows/Lead Rows", "Headline Metric"],
        family_rows,
    )
    lines += [
        "",
        "## Markets",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "City", "Trust", "Days", "Mode", "Reason",
            "Probability Cal", "Cal Brier", "Forecast Error", "Forecast Brier",
            "Lag", "Lead Rows",
        ],
        rows,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_train(args):
    manifest = build_family_manifest(
        family_unit=args.family_unit,
        snapshots_root=Path(args.snapshots_root),
        quality_grades=args.quality_grades,
        min_trust=args.min_trust,
        min_settled_days=args.min_settled_days,
    )
    manifest_path = _write_json(args.out, manifest)
    report_path = write_report(args.report, manifest)
    modes = {}
    for market in (manifest.get("markets") or {}).values():
        mode = (market.get("serving_gate") or {}).get("mode")
        modes[mode] = modes.get(mode, 0) + 1
    print(f"Wrote family secondary manifest to {manifest_path}")
    print(f"Wrote family secondary report to {report_path}")
    print("Serving modes: " + ", ".join(f"{mode}={count}" for mode, count in sorted(modes.items())))


def build_parser():
    parser = argparse.ArgumentParser(description="Train family secondary artifacts and serving gate.")
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train")
    train.add_argument("--family-unit", default=DEFAULT_FAMILY_UNIT, choices=["F"])
    train.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    train.add_argument("--quality-grades", default=DEFAULT_QUALITY_GRADES)
    train.add_argument("--min-trust", type=int, default=DEFAULT_MIN_TRUST)
    train.add_argument("--min-settled-days", type=int, default=DEFAULT_MIN_SETTLED_DAYS)
    train.add_argument("--out", default=str(DEFAULT_MANIFEST))
    train.add_argument("--report", default=str(DEFAULT_REPORT))
    train.set_defaults(func=cmd_train)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
