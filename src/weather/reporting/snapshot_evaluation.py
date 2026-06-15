"""Continuous snapshot evaluation over durable local artifacts.

This module is intentionally artifact-driven.  It does not fetch data, train
models, or replay snapshots itself; the daily refresh has already done that
work.  The goal here is to keep one compact audit surface that answers:

* are snapshots still being collected and replay-seeded,
* do the latest replay/promotion gates validate the candidate/current model,
* which slices should drive the next model or data-quality change.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import fmt_num, fmt_signed, markdown_table  # noqa: E402
from settled_days import folder_market_id  # noqa: E402


SCHEMA_VERSION = "snapshot_evaluation_v0.1"
DEFAULT_BACKTEST_ROOT = Path("data") / "backtest"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "snapshot_evaluation.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "snapshot_evaluation_report.md"

SNAPSHOT_ARTIFACTS = {
    "snapshots_long": "snapshots_long.csv",
    "replay_inputs": "replay_inputs.jsonl",
    "replay_input_status": "replay_input_status_long.csv",
    "features": "features_long.csv",
    "components": "components_long.csv",
    "forecasts": "forecasts_long.csv",
    "source_status": "source_status_long.csv",
    "clob_features": "clob_features_long.csv",
    "order_books": "order_books_summary.csv",
}


def utc_now():
    return datetime.now(timezone.utc)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) else number
    try:
        number = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return None if math.isnan(number) else number


def safe_int(value):
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def age_seconds(value, now=None):
    if not value:
        return None
    now = now or utc_now()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())


def line_count(path):
    path = Path(path)
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def snapshot_folder_summary(folder):
    folder = Path(folder)
    tape_path = folder / SNAPSHOT_ARTIFACTS["snapshots_long"]
    snapshot_ids = set()
    band_labels = set()
    row_count = 0
    first_capture = None
    last_capture = None
    model_versions = Counter()
    market_id = folder_market_id(folder)
    read_error = None

    try:
        with tape_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row_count += 1
                snapshot_id = row.get("snapshot_id")
                if snapshot_id:
                    snapshot_ids.add(str(snapshot_id))
                label = row.get("range_label")
                if label:
                    band_labels.add(str(label))
                captured = row.get("captured_at_utc") or row.get("captured_at_local")
                if captured:
                    if first_capture is None or captured < first_capture:
                        first_capture = captured
                    if last_capture is None or captured > last_capture:
                        last_capture = captured
                version = row.get("model_version")
                if version:
                    model_versions[str(version)] += 1
    except OSError as exc:
        read_error = str(exc)

    artifacts = {
        key: (folder / filename).exists()
        for key, filename in SNAPSHOT_ARTIFACTS.items()
    }
    return {
        "folder": str(folder),
        "event_slug": folder.name,
        "market_id": market_id,
        "snapshot_count": len(snapshot_ids),
        "band_row_count": row_count,
        "band_count": len(band_labels),
        "first_capture": first_capture,
        "last_capture": last_capture,
        "latest_model_versions": [item[0] for item in model_versions.most_common(3)],
        "replay_input_record_count": line_count(folder / SNAPSHOT_ARTIFACTS["replay_inputs"]),
        "artifacts": artifacts,
        "read_error": read_error,
    }


def discover_snapshot_folders(root):
    root = Path(root)
    if not root.exists():
        return []
    return sorted(
        path for path in root.iterdir()
        if path.is_dir() and (path / SNAPSHOT_ARTIFACTS["snapshots_long"]).exists()
    )


def snapshot_inventory(snapshots_root=DEFAULT_SNAPSHOTS_ROOT):
    folders = [snapshot_folder_summary(folder) for folder in discover_snapshot_folders(snapshots_root)]
    artifact_counts = Counter()
    for row in folders:
        for key, present in (row.get("artifacts") or {}).items():
            if present:
                artifact_counts[key] += 1
    folder_count = len(folders)
    rates = {
        key: (artifact_counts.get(key, 0) / folder_count if folder_count else None)
        for key in SNAPSHOT_ARTIFACTS
    }
    by_market = {}
    for row in folders:
        market_id = row.get("market_id") or "unknown"
        item = by_market.setdefault(
            market_id,
            {
                "market_id": market_id,
                "folder_count": 0,
                "snapshot_count": 0,
                "band_row_count": 0,
                "latest_capture": None,
            },
        )
        item["folder_count"] += 1
        item["snapshot_count"] += row.get("snapshot_count") or 0
        item["band_row_count"] += row.get("band_row_count") or 0
        latest = row.get("last_capture")
        if latest and (item["latest_capture"] is None or latest > item["latest_capture"]):
            item["latest_capture"] = latest

    latest_capture = max(
        (row.get("last_capture") for row in folders if row.get("last_capture")),
        default=None,
    )
    return {
        "snapshots_root": str(Path(snapshots_root)),
        "folder_count": folder_count,
        "snapshot_count": sum(row.get("snapshot_count") or 0 for row in folders),
        "band_row_count": sum(row.get("band_row_count") or 0 for row in folders),
        "replay_input_record_count": sum(row.get("replay_input_record_count") or 0 for row in folders),
        "latest_capture": latest_capture,
        "latest_capture_age_seconds": age_seconds(latest_capture),
        "artifact_rates": rates,
        "by_market": sorted(by_market.values(), key=lambda item: item["market_id"]),
        "recent_folders": sorted(
            folders,
            key=lambda row: row.get("last_capture") or "",
            reverse=True,
        )[:12],
    }


def status_gate(name, status, detail, severity="fail", action=None):
    return {
        "name": name,
        "status": status,
        "severity": severity,
        "ok": status == "PASS",
        "detail": detail,
        "action": action,
    }


def gate_from_bool(name, passed, detail, severity="fail", action=None):
    return status_gate(name, "PASS" if passed else severity.upper(), detail, severity=severity, action=action)


def artifact_rate_gate(name, inventory, key, warn_threshold=0.95, fail_threshold=0.50):
    rate = (inventory.get("artifact_rates") or {}).get(key)
    if rate is None:
        return status_gate(name, "WARN", "no snapshot folders found", severity="warn")
    if rate >= warn_threshold:
        status = "PASS"
    elif rate >= fail_threshold:
        status = "WARN"
    else:
        status = "FAIL"
    return status_gate(
        name,
        status,
        f"{key} present on {rate * 100:.1f}% of snapshot folders",
        severity="fail",
        action="Backfill or regenerate missing replay-seed artifacts before training or promotion.",
    )


def promotion_summary(backtest_root):
    root = Path(backtest_root)
    refresh = read_json(root / "f_family_promotion_refresh.json", default={}) or {}
    candidate_replay = read_json(root / "pooled_candidate_replay_latest.json", default={}) or {}
    progress = read_json(root / "progress_audit.json", default={}) or {}
    casebook = read_json(root / "disagreement_casebook.json", default={}) or {}
    data_layer = read_json(root / "data_layer_audit.json", default={}) or {}
    fleet = read_json(root / "fleet_observability.json", default={}) or {}
    wu_validation = read_json(root / "wu_max_since_7_validation.json", default={}) or {}

    candidate = refresh.get("candidate") or {}
    if not candidate and candidate_replay:
        candidate = {
            "aggregate": candidate_replay.get("aggregate") or {},
            "coverage": candidate_replay.get("coverage") or {},
            "verdict": candidate_replay.get("verdict"),
            "candidate_market_verdict": candidate_replay.get("candidate_market_verdict"),
            "cutover_decision": candidate_replay.get("cutover_decision"),
            "slices": {
                "by_market": candidate_replay.get("market_rows") or [],
                "by_cutoff_hour": candidate_replay.get("by_hour") or [],
                "by_band_type": candidate_replay.get("by_bin_type") or [],
                "by_settlement_distance": candidate_replay.get("by_settlement_distance") or [],
                "by_source_freshness": candidate_replay.get("by_source_freshness") or [],
            },
        }

    return {
        "promotion_refresh": {
            "exists": bool(refresh),
            "generated_at_utc": refresh.get("generated_at_utc"),
            "family_unit": refresh.get("family_unit"),
            "corpus": refresh.get("corpus") or {},
            "candidate": candidate,
            "serving_gauntlet": refresh.get("serving_gauntlet") or {},
            "decisions": refresh.get("decisions") or {},
            "readiness": refresh.get("readiness") or {},
        },
        "candidate_replay": {
            "exists": bool(candidate_replay),
            "aggregate": candidate_replay.get("aggregate") or {},
            "coverage": candidate_replay.get("coverage") or {},
            "replay_gate": candidate_replay.get("replay_gate") or {},
        },
        "progress_audit": {
            "exists": bool(progress),
            "trend_assessment": progress.get("trend_assessment") or {},
            "current_backtest": progress.get("current_backtest") or {},
        },
        "casebook": {
            "exists": bool(casebook),
            "summary": casebook.get("summary") or {},
        },
        "data_layer_audit": {
            "exists": bool(data_layer),
            "gate_summary": data_layer.get("gate_summary") or {},
            "recommendations": data_layer.get("recommendations") or [],
        },
        "fleet_observability": {
            "exists": bool(fleet),
            "status": fleet.get("status"),
            "summary": fleet.get("summary") or {},
            "live_forward_slo": fleet.get("live_forward_slo") or {},
        },
        "wu_max_since_7_validation": {
            "exists": bool(wu_validation),
            "summary": wu_validation.get("summary") or {},
        },
    }


def build_gates(inventory, evidence):
    promotion = evidence["promotion_refresh"]
    candidate = promotion.get("candidate") or {}
    aggregate = candidate.get("aggregate") or {}
    corpus = promotion.get("corpus") or {}
    coverage = candidate.get("coverage") or evidence["candidate_replay"].get("coverage") or {}
    serving = promotion.get("serving_gauntlet") or {}
    data_gate = evidence["data_layer_audit"].get("gate_summary") or {}
    fleet = evidence["fleet_observability"] or {}
    slo = fleet.get("live_forward_slo") or {}
    casebook_summary = evidence["casebook"].get("summary") or {}

    gates = [
        gate_from_bool(
            "snapshot_inventory_present",
            inventory.get("folder_count", 0) > 0 and inventory.get("snapshot_count", 0) > 0,
            f"{inventory.get('folder_count', 0)} folders, {inventory.get('snapshot_count', 0)} snapshots",
            severity="warn",
            action="Start or repair the snapshot supervisor before treating model evidence as current.",
        ),
        artifact_rate_gate("replay_input_coverage", inventory, "replay_inputs"),
        artifact_rate_gate("feature_artifact_coverage", inventory, "features"),
    ]

    gates.append(gate_from_bool(
        "promotion_corpus_ready",
        safe_int(corpus.get("snapshot_count")) > 0 and safe_int(corpus.get("market_day_count")) > 0,
        (
            f"{safe_int(corpus.get('market_day_count'))} market-days, "
            f"{safe_int(corpus.get('snapshot_count'))} pinned snapshots"
        ),
        severity="fail",
        action="Run promotion_refresh after settlement labels are finalized.",
    ))

    candidate_rows = safe_int(aggregate.get("rows") or aggregate.get("n"))
    missing_candidate = safe_int(coverage.get("missing_candidate_rows"))
    gates.append(gate_from_bool(
        "candidate_replay_scored",
        candidate_rows > 0 and missing_candidate == 0,
        f"{candidate_rows} candidate rows, {missing_candidate} missing candidate rows",
        severity="fail",
        action="Inspect pooled candidate replay coverage before using candidate metrics.",
    ))

    delta_current = maybe_float(aggregate.get("delta_vs_current"))
    if delta_current is None:
        gates.append(status_gate("candidate_vs_current", "WARN", "missing delta_vs_current", severity="warn"))
    else:
        gates.append(status_gate(
            "candidate_vs_current",
            "PASS" if delta_current <= 0 else "FAIL",
            f"delta_vs_current {delta_current:+.4f}",
            severity="fail",
            action="Block promotion until replay improves or matches the current serving model.",
        ))

    delta_market = maybe_float(aggregate.get("delta_vs_market"))
    if delta_market is None:
        gates.append(status_gate("candidate_vs_market", "WARN", "missing delta_vs_market", severity="warn"))
    elif delta_market <= 0:
        gates.append(status_gate("candidate_vs_market", "PASS", f"delta_vs_market {delta_market:+.4f}", severity="warn"))
    else:
        gates.append(status_gate(
            "candidate_vs_market",
            "WARN",
            f"candidate trails market by {delta_market:+.4f} Brier",
            severity="warn",
            action="Use the improvement slices to target the largest market-skill gaps.",
        ))

    serving_verdict = serving.get("verdict")
    gates.append(status_gate(
        "current_serving_gauntlet",
        "PASS" if serving_verdict in {"PASS", "PASS_WITH_SHADOWS", "PARTIAL_PASS"} else ("WARN" if not serving_verdict else "FAIL"),
        f"serving gauntlet verdict {serving_verdict or 'missing'}",
        severity="fail",
        action="Inspect promotion_gauntlet_latest_report.md before changing serving behavior.",
    ))

    if casebook_summary:
        gates.append(status_gate(
            "disagreement_casebook_coverage",
            "PASS" if casebook_summary.get("threshold_coverage_ok") else "FAIL",
            (
                f"{casebook_summary.get('covered_threshold_snapshot_count', 0)} / "
                f"{casebook_summary.get('threshold_snapshot_count', 0)} threshold snapshots covered; "
                f"{casebook_summary.get('case_count', 0)} cases"
            ),
            severity="fail",
            action="Regenerate the disagreement casebook before trusting gap-driver slices.",
        ))
    else:
        gates.append(status_gate(
            "disagreement_casebook_coverage",
            "WARN",
            "disagreement casebook missing",
            severity="warn",
            action="Run disagreement_casebook so model-vs-market gaps become auditable cases.",
        ))

    layer_status = data_gate.get("status")
    gates.append(status_gate(
        "data_layer_audit",
        layer_status if layer_status in {"PASS", "WARN", "FAIL"} else "WARN",
        (
            f"{data_gate.get('pass_count', 0)} pass, "
            f"{data_gate.get('warn_count', 0)} warn, {data_gate.get('fail_count', 0)} fail"
        ) if data_gate else "data layer audit missing",
        severity="fail",
        action="Resolve fail gates before adding new training coverage.",
    ))

    if "counts_toward_live_forward_gate" in slo:
        slo_ok = bool(slo.get("counts_toward_live_forward_gate"))
        gates.append(status_gate(
            "live_forward_slo",
            "PASS" if slo_ok else "FAIL",
            slo.get("reason") or f"counts_toward_live_forward_gate={slo_ok}",
            severity="fail",
            action="Do not count live-forward evidence while collection SLOs are blocked.",
        ))
    else:
        fleet_status = fleet.get("status")
        gates.append(status_gate(
            "fleet_observability",
            "PASS" if fleet_status == "OK" else ("WARN" if fleet_status else "WARN"),
            f"fleet status {fleet_status or 'missing'}",
            severity="warn",
        ))

    return gates


def normalized_slice_rows(candidate):
    slices = candidate.get("slices") or {}
    rows = []
    for slice_name, items in slices.items():
        for item in items or []:
            comp = item.get("comparison") or {}
            group = item.get("group") or item.get("market_id") or item.get("taxonomy")
            n = safe_int(item.get("n") or item.get("rows") or comp.get("n"))
            delta_market = maybe_float(item.get("delta_vs_market") or comp.get("delta_vs_market"))
            delta_current = maybe_float(item.get("delta_vs_current") or comp.get("delta_vs_current"))
            candidate_brier = maybe_float(item.get("candidate_brier") or comp.get("candidate_brier"))
            market_brier = maybe_float(item.get("market_brier") or comp.get("market_brier"))
            if n <= 0:
                continue
            if delta_market is None and candidate_brier is not None and market_brier is not None:
                delta_market = candidate_brier - market_brier
            if delta_market is None and delta_current is None:
                continue
            rows.append({
                "source": "candidate_replay",
                "slice": slice_name.replace("by_", ""),
                "group": group if group not in (None, "") else "-",
                "rows": n,
                "delta_vs_market": delta_market,
                "delta_vs_current": delta_current,
                "excess_brier_rows": (delta_market or 0.0) * n,
            })
    return rows


def serving_blocker_rows(serving):
    output = []
    blocked = {
        row.get("market_id")
        for row in serving.get("market_rows") or []
        if row.get("verdict") == "BLOCK"
    }
    by_market = ((serving.get("decomposition") or {}).get("blocking_markets") or {})
    for market_id in sorted(item for item in blocked if item):
        slices = by_market.get(market_id) or {}
        for slice_name, rows in slices.items():
            for row in rows or []:
                n = safe_int(row.get("n"))
                code_effect = maybe_float(row.get("code_effect"))
                if n <= 0 or code_effect is None:
                    continue
                output.append({
                    "source": "serving_gauntlet",
                    "slice": slice_name.replace("by_", ""),
                    "group": f"{market_id}:{row.get('group') if row.get('group') not in (None, '') else '-'}",
                    "rows": n,
                    "code_effect": code_effect,
                    "excess_brier_rows": max(0.0, code_effect) * n,
                })
    return output


def recommendation_rows(evidence, limit=8):
    rows = []
    for item in (evidence["data_layer_audit"].get("recommendations") or [])[:limit]:
        rows.append({
            "source": "data_layer_audit",
            "priority": item.get("priority"),
            "area": item.get("area") or item.get("name") or "-",
            "detail": item.get("recommendation") or item.get("detail") or item.get("action") or "-",
        })
    return rows


def improvement_backlog(evidence, limit=12):
    promotion = evidence["promotion_refresh"]
    candidate = promotion.get("candidate") or {}
    serving = promotion.get("serving_gauntlet") or {}
    rows = normalized_slice_rows(candidate)
    rows.extend(serving_blocker_rows(serving))
    rows.sort(
        key=lambda row: (
            maybe_float(row.get("excess_brier_rows")) or 0.0,
            safe_int(row.get("rows")),
        ),
        reverse=True,
    )
    return {
        "top_slices": rows[:limit],
        "data_recommendations": recommendation_rows(evidence),
    }


def overall_status(gates):
    fail_count = sum(1 for gate in gates if gate.get("status") == "FAIL")
    warn_count = sum(1 for gate in gates if gate.get("status") == "WARN")
    if fail_count:
        status = "FAIL"
    elif warn_count:
        status = "WARN"
    else:
        status = "PASS"
    return {
        "status": status,
        "pass_count": sum(1 for gate in gates if gate.get("status") == "PASS"),
        "warn_count": warn_count,
        "fail_count": fail_count,
    }


def build_evaluation(backtest_root=DEFAULT_BACKTEST_ROOT, snapshots_root=DEFAULT_SNAPSHOTS_ROOT):
    inventory = snapshot_inventory(snapshots_root)
    evidence = promotion_summary(backtest_root)
    gates = build_gates(inventory, evidence)
    backlog = improvement_backlog(evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now().isoformat(),
        "snapshots_root": str(Path(snapshots_root)),
        "backtest_root": str(Path(backtest_root)),
        "status": overall_status(gates),
        "gates": gates,
        "snapshot_inventory": inventory,
        "evidence": evidence,
        "improvement_backlog": backlog,
    }


def fmt_count(value):
    return str(value) if value is not None else "-"


def fmt_rate(value):
    return "-" if value is None else f"{value * 100:.1f}%"


def render_report(payload):
    status = payload.get("status") or {}
    inventory = payload.get("snapshot_inventory") or {}
    evidence = payload.get("evidence") or {}
    promotion = (evidence.get("promotion_refresh") or {})
    candidate = promotion.get("candidate") or {}
    aggregate = candidate.get("aggregate") or {}
    corpus = promotion.get("corpus") or {}
    decisions = promotion.get("decisions") or {}
    serving = promotion.get("serving_gauntlet") or {}
    data_layer = evidence.get("data_layer_audit") or {}
    fleet = evidence.get("fleet_observability") or {}
    casebook = (evidence.get("casebook") or {}).get("summary") or {}
    wu_validation = (evidence.get("wu_max_since_7_validation") or {}).get("summary") or {}
    backlog = payload.get("improvement_backlog") or {}

    lines = [
        "# Continuous Snapshot Evaluation",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{status.get('status')}** "
        f"({status.get('pass_count', 0)} pass, {status.get('warn_count', 0)} warn, {status.get('fail_count', 0)} fail)",
        "",
        "## Snapshot Coverage",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Snapshot folders", fmt_count(inventory.get("folder_count"))],
            ["Snapshots", fmt_count(inventory.get("snapshot_count"))],
            ["Band rows", fmt_count(inventory.get("band_row_count"))],
            ["Replay input records", fmt_count(inventory.get("replay_input_record_count"))],
            ["Latest capture", inventory.get("latest_capture") or "-"],
            ["Replay input artifact rate", fmt_rate((inventory.get("artifact_rates") or {}).get("replay_inputs"))],
            ["Feature artifact rate", fmt_rate((inventory.get("artifact_rates") or {}).get("features"))],
            ["Source-status artifact rate", fmt_rate((inventory.get("artifact_rates") or {}).get("source_status"))],
        ],
    )

    lines += ["", "## Validation Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail", "Action"],
        [
            [
                gate.get("name"),
                gate.get("status"),
                gate.get("detail"),
                gate.get("action") if gate.get("status") != "PASS" else "-",
            ]
            for gate in payload.get("gates") or []
        ],
    )

    lines += ["", "## Replay And Promotion Evidence", ""]
    lines += markdown_table(
        ["Area", "Evidence"],
        [
            [
                "Promotion corpus",
                (
                    f"{fmt_count(corpus.get('market_day_count'))} market-days, "
                    f"{fmt_count(corpus.get('snapshot_count'))} snapshots, "
                    f"{fmt_count(corpus.get('band_row_count'))} band rows"
                ),
            ],
            [
                "Candidate replay",
                (
                    f"rows {fmt_count(aggregate.get('rows') or aggregate.get('n'))}; "
                    f"Brier candidate {fmt_num(aggregate.get('candidate_brier'))}, "
                    f"current {fmt_num(aggregate.get('current_brier'))}, "
                    f"market {fmt_num(aggregate.get('market_brier'))}"
                ),
            ],
            [
                "Candidate deltas",
                (
                    f"vs current {fmt_signed(aggregate.get('delta_vs_current'), 4)}; "
                    f"vs market {fmt_signed(aggregate.get('delta_vs_market'), 4)}"
                ),
            ],
            [
                "Promotion actions",
                (
                    f"promote {len(decisions.get('promote_markets') or [])}, "
                    f"shadow {len(decisions.get('shadow_markets') or [])}, "
                    f"blocked {len(decisions.get('blocked_markets') or [])}"
                ),
            ],
            ["Current serving gauntlet", serving.get("verdict") or "-"],
            [
                "Disagreement casebook",
                (
                    f"{fmt_count(casebook.get('case_count'))} cases; "
                    f"settled {fmt_count(casebook.get('settled_case_count'))}; "
                    f"threshold coverage {fmt_count(casebook.get('covered_threshold_snapshot_count'))} / "
                    f"{fmt_count(casebook.get('threshold_snapshot_count'))}"
                ),
            ],
            [
                "WU max-since-7 validation",
                (
                    f"{fmt_count(wu_validation.get('snapshots'))} snapshots; "
                    f"safe rate {fmt_rate(wu_validation.get('safe_rate'))}; "
                    f"missing current max {fmt_count(wu_validation.get('missing_current_max'))}"
                ),
            ],
            ["Data-layer audit", (data_layer.get("gate_summary") or {}).get("status") or "-"],
            ["Fleet observability", fleet.get("status") or "-"],
        ],
    )

    lines += ["", "## Improvement Backlog", ""]
    top_slices = backlog.get("top_slices") or []
    if top_slices:
        lines += markdown_table(
            ["Source", "Slice", "Group", "Rows", "Delta Vs Market", "Code Effect", "Weighted Gap"],
            [
                [
                    row.get("source"),
                    row.get("slice"),
                    row.get("group"),
                    row.get("rows"),
                    fmt_signed(row.get("delta_vs_market"), 4),
                    fmt_signed(row.get("code_effect"), 4),
                    fmt_num(row.get("excess_brier_rows"), 2),
                ]
                for row in top_slices
            ],
        )
    else:
        lines.append("No replay or serving-gauntlet gap slices were available.")

    recommendations = backlog.get("data_recommendations") or []
    if recommendations:
        lines += ["", "## Data Recommendations", ""]
        lines += markdown_table(
            ["Priority", "Area", "Detail"],
            [
                [row.get("priority"), row.get("area"), row.get("detail")]
                for row in recommendations
            ],
        )

    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a continuous evaluation report for snapshot/replay evidence.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)

    payload = build_evaluation(args.backtest_root, args.snapshots_root)
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    print(f"Continuous snapshot evaluation: {payload['status']['status']}")
    return 0 if payload["status"]["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
