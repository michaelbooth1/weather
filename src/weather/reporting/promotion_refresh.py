"""End-to-end promotion refresh for family-pooled candidates.

This is the Item 33/37 bridge: when more settled market-days appear, one
command refreshes the pinned promotion corpus, location trust, pooled candidate
replay, and per-market promotion decisions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from weather.paths import data_path

from types import SimpleNamespace

from weather.reporting.formatting import (
    fmt_num,
    fmt_signed,
    markdown_table,
)
from weather.reporting.artifact_disk_budget import ensure_artifact_disk_headroom
from weather.reporting.location_trust import DEFAULT_OUT as DEFAULT_TRUST_OUT
from weather.reporting.location_trust import score_all_markets
from weather.market.market_registry import all_specs
from weather.calibration.pooled_candidate_replay import (
    DEFAULT_CASEBOOK,
    DEFAULT_MICROSTRUCTURE_ARTIFACT,
    DEFAULT_VARIANT_REGISTRY_PATH,
    DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
    run_pooled_candidate_replay,
)
from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.reporting.promotion_corpus import (
    DEFAULT_OUT as DEFAULT_CORPUS,
    DEFAULT_QUALITY_GRADES,
    build_promotion_corpus,
    parse_quality_grades,
    write_manifest,
)
from weather.reporting.promotion_gauntlet import DEFAULT_FORECAST_TRACKER, run_promotion_gauntlet
from weather.backtesting.replay_backtest import DEFAULT_BASELINE, FIDELITY_FAITHFUL_L1
from weather.backtesting.settled_days import DEFAULT_SNAPSHOTS_ROOT
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)


SCHEMA_VERSION = "promotion_refresh_v0.1"
DEFAULT_OUT = data_path() / "backtest" / "f_family_promotion_refresh.json"
DEFAULT_REPORT = data_path() / "backtest" / "f_family_promotion_refresh_report.md"
DEFAULT_CANDIDATE_REPORT = data_path() / "backtest" / "pooled_candidate_replay_latest_report.md"
DEFAULT_CANDIDATE_JSON = data_path() / "backtest" / "pooled_candidate_replay_latest.json"
DEFAULT_CURRENT_REPLAY_REPORT = data_path() / "backtest" / "pooled_candidate_current_replay_latest_report.md"
DEFAULT_SERVING_GAUNTLET_REPORT = data_path() / "backtest" / "promotion_gauntlet_latest_report.md"
DEFAULT_SERVING_REPLAY_REPORT = data_path() / "backtest" / "promotion_replay_latest_report.md"
DEFAULT_HOURLY_PERFORMANCE = data_path() / "backtest" / "hourly_model_performance.json"
DEFAULT_CANDIDATE_HOURLY_PERFORMANCE = ""
DEFAULT_TEN_MINUTE_PERFORMANCE = data_path() / "backtest" / "ten_minute_model_performance.json"
DEFAULT_CANDIDATE_TEN_MINUTE_PERFORMANCE = DEFAULT_TEN_MINUTE_PERFORMANCE
DEFAULT_SOURCE_FAMILY_INVENTORY = data_path() / "backtest" / "source_family_inventory.json"
DEFAULT_FLEET_OBSERVABILITY = data_path() / "backtest" / "fleet_observability.json"
DEFAULT_INCOMPLETE_MANIFEST = data_path() / "backtest" / "f_family_promotion_refresh_incomplete.json"
DEFAULT_FAMILY_UNIT = "F"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_json(path, payload, min_free_bytes=0, context="promotion refresh JSON export"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    ensure_artifact_disk_headroom(
        path,
        estimated_bytes=len(text.encode("utf-8")),
        min_free_bytes=min_free_bytes,
        context=context,
    )
    path.write_text(text, encoding="utf-8")
    return path


def _as_path(value):
    return str(Path(value)) if value is not None else None


def _family_specs(family_unit=DEFAULT_FAMILY_UNIT, specs=None):
    source = list(specs) if specs is not None else list(all_specs())
    if str(family_unit or "").lower() == "all":
        return source
    return [spec for spec in source if getattr(spec, "display_unit", None) == family_unit]


def _manifest_summary(manifest, corpus_path):
    summary = manifest.get("summary") or {}
    return {
        "path": str(corpus_path),
        "schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "as_of": manifest.get("as_of"),
        "market_day_count": summary.get("market_day_count", 0),
        "snapshot_count": summary.get("snapshot_count", 0),
        "band_row_count": summary.get("band_row_count", 0),
        "identity_record_count": summary.get("identity_record_count", 0),
        "by_market": summary.get("by_market") or {},
        "quality_grades": manifest.get("quality_grades") or [],
        "skipped_count": len(manifest.get("skipped") or []),
        "skipped_by_reason": dict(sorted(
            Counter(item.get("reason") or "unknown" for item in manifest.get("skipped") or []).items()
        )),
    }


def _trust_summary(trust_rows, trust_path, family_ids):
    trust_by_market = {row.get("market"): row for row in trust_rows if row.get("market")}
    family_scores = [
        trust_by_market.get(market_id, {}).get("trust_score")
        for market_id in family_ids
    ]
    family_scores = [score for score in family_scores if score is not None]
    return {
        "path": str(trust_path),
        "market_count": len(trust_rows),
        "family_market_count": len(family_ids),
        "family_min_trust": min(family_scores) if family_scores else None,
        "family_max_trust": max(family_scores) if family_scores else None,
        "by_market": trust_by_market,
    }


def _candidate_summary(candidate_report, candidate_json_path, candidate_report_path):
    aggregate = candidate_report.get("aggregate") or {}
    microstructure = candidate_report.get("microstructure") or {}
    micro_diag = microstructure.get("diagnostics") or {}
    micro_agg = microstructure.get("aggregate") or {}
    micro_gated = microstructure.get("gated") or {}
    micro_gated_agg = micro_gated.get("aggregate") or {}
    bridge = candidate_report.get("conservative_bridge") or {}
    bridge_diag = bridge.get("diagnostics") or {}
    bridge_agg = bridge.get("aggregate") or {}
    market_slices = []
    for row in candidate_report.get("market_rows") or []:
        comparison = row.get("comparison") or {}
        market_slices.append({
            "group": row.get("market_id"),
            "n": comparison.get("n") or row.get("rows") or 0,
            "candidate_brier": comparison.get("candidate_brier"),
            "current_brier": comparison.get("current_brier"),
            "recorded_brier": comparison.get("recorded_brier"),
            "market_brier": comparison.get("market_brier"),
            "delta_vs_current": comparison.get("delta_vs_current"),
            "delta_vs_market": comparison.get("delta_vs_market"),
            "blocked_validation": row.get("blocked_validation") or {},
        })
    evidence = _candidate_evidence_accounting(candidate_report)
    return {
        "json_path": _as_path(candidate_json_path),
        "report_path": _as_path(candidate_report_path),
        "verdict": candidate_report.get("verdict"),
        "candidate_market_verdict": candidate_report.get("candidate_market_verdict"),
        "cutover_decision": candidate_report.get("cutover_decision"),
        "artifact": candidate_report.get("artifact") or {},
        "corpus": candidate_report.get("corpus") or {},
        "coverage": candidate_report.get("coverage") or {},
        "replay_gate": candidate_report.get("replay_gate") or {},
        "blocked_validation": candidate_report.get("blocked_validation") or {},
        "candidate_shadow_variants": candidate_report.get("candidate_shadow_variants") or {},
        "evidence_accounting": evidence,
        "aggregate": {
            "rows": aggregate.get("n", 0),
            "candidate_brier": aggregate.get("candidate_brier"),
            "current_brier": aggregate.get("current_brier"),
            "recorded_brier": aggregate.get("recorded_brier"),
            "market_brier": aggregate.get("market_brier"),
            "delta_vs_current": aggregate.get("delta_vs_current"),
            "delta_vs_market": aggregate.get("delta_vs_market"),
            "candidate_skill": aggregate.get("candidate_skill"),
        },
        "microstructure": {
            "schema_version": microstructure.get("schema_version"),
            "eligible_rows": micro_diag.get("eligible_rows", 0),
            "predicted_rows": micro_diag.get("predicted_rows", 0),
            "fold_count": micro_diag.get("fold_count", 0),
            "casebook_matched_rows": micro_diag.get("casebook_matched_rows", 0),
            "gated_overlay_rows": micro_diag.get("gated_overlay_rows", 0),
            "gated_base_rows": micro_diag.get("gated_base_rows", 0),
            "artifact_path": micro_diag.get("artifact_path"),
            "gate": microstructure.get("gate") or {},
            "aggregate": {
                "rows": micro_agg.get("n", 0),
                "micro_brier": micro_agg.get("micro_brier"),
                "candidate_brier": micro_agg.get("candidate_brier"),
                "current_brier": micro_agg.get("current_brier"),
                "market_brier": micro_agg.get("market_brier"),
                "delta_vs_candidate": micro_agg.get("delta_vs_candidate"),
                "delta_vs_current": micro_agg.get("delta_vs_current"),
                "delta_vs_market": micro_agg.get("delta_vs_market"),
                "micro_skill": micro_agg.get("micro_skill"),
            },
            "gated_aggregate": {
                "rows": micro_gated_agg.get("n", 0),
                "micro_brier": micro_gated_agg.get("micro_brier"),
                "candidate_brier": micro_gated_agg.get("candidate_brier"),
                "current_brier": micro_gated_agg.get("current_brier"),
                "market_brier": micro_gated_agg.get("market_brier"),
                "delta_vs_candidate": micro_gated_agg.get("delta_vs_candidate"),
                "delta_vs_current": micro_gated_agg.get("delta_vs_current"),
                "delta_vs_market": micro_gated_agg.get("delta_vs_market"),
                "micro_skill": micro_gated_agg.get("micro_skill"),
            },
            "target_slices": microstructure.get("target_slices") or [],
            "gated_target_slices": micro_gated.get("target_slices") or [],
        },
        "conservative_bridge": {
            "schema_version": bridge.get("schema_version"),
            "policy": bridge.get("policy") or {},
            "shadow_variant_rows": bridge_diag.get("shadow_variant_rows", 0),
            "shadow_variant_path": bridge_diag.get("shadow_variant_path"),
            "aggregate": {
                "rows": bridge_agg.get("n", 0),
                "bridge_brier": bridge_agg.get("bridge_brier"),
                "candidate_brier": bridge_agg.get("candidate_brier"),
                "current_brier": bridge_agg.get("current_brier"),
                "market_brier": bridge_agg.get("market_brier"),
                "delta_vs_candidate": bridge_agg.get("delta_vs_candidate"),
                "delta_vs_current": bridge_agg.get("delta_vs_current"),
                "delta_vs_market": bridge_agg.get("delta_vs_market"),
                "bridge_skill": bridge_agg.get("bridge_skill"),
            },
            "by_market": bridge.get("by_market") or [],
        },
        "slices": {
            "by_market": market_slices,
            "by_cutoff_hour": candidate_report.get("by_hour") or [],
            "by_cutoff_regime": candidate_report.get("by_cutoff_regime") or [],
            "by_band_type": candidate_report.get("by_bin_type") or [],
            "by_settlement_distance": candidate_report.get("by_settlement_distance") or [],
            "by_clob_taxonomy": micro_gated.get("by_taxonomy") or microstructure.get("by_taxonomy") or [],
            "by_source_freshness": candidate_report.get("by_source_freshness") or [],
            "by_forecast_source_count": candidate_report.get("by_forecast_source_count") or [],
            "by_forecast_disagreement": candidate_report.get("by_forecast_disagreement") or [],
            "by_forecast_bucket_pressure": candidate_report.get("by_forecast_bucket_pressure") or [],
        },
        "forecast_profile_guardrails": candidate_report.get("forecast_profile_guardrails") or {},
    }


def load_precomputed_candidate_report(path, manifest):
    path = Path(path)
    candidate_report = json.loads(path.read_text(encoding="utf-8"))
    candidate_corpus = candidate_report.get("corpus") or {}
    candidate_hash = candidate_corpus.get("corpus_hash")
    manifest_hash = manifest.get("corpus_hash")
    if candidate_hash and manifest_hash and candidate_hash != manifest_hash:
        raise ValueError(
            "precomputed candidate corpus hash mismatch: "
            f"candidate={candidate_hash}, manifest={manifest_hash}"
        )
    return candidate_report


def _candidate_evidence_accounting(candidate_report):
    market_rows = candidate_report.get("market_rows") or []
    aggregate = candidate_report.get("aggregate") or {}
    scored_rows = int(aggregate.get("n") or sum(int(row.get("rows") or 0) for row in market_rows))
    snapshots = sum(int(row.get("snapshots") or 0) for row in market_rows)
    market_days = sum(int(row.get("days") or 0) for row in market_rows)
    markets = {row.get("market_id") for row in market_rows if row.get("market_id")}
    return {
        "scored_rows": scored_rows,
        "unique_observation_count": scored_rows,
        "snapshot_count": snapshots,
        "market_day_count": market_days,
        "market_count": len(markets),
        "row_multiplier": 1.0 if scored_rows else 0.0,
        "source": "candidate_replay_market_rows",
    }


def _serving_gauntlet_summary(report, report_path, replay_report_path):
    if not report:
        return None
    return {
        "report_path": _as_path(report_path),
        "replay_report_path": _as_path(replay_report_path),
        "verdict": report.get("verdict"),
        "corpus_ok": report.get("corpus_ok"),
        "fidelity_ok": report.get("fidelity_ok"),
        "baseline_ok": report.get("baseline_ok"),
        "forecast_tracker": report.get("forecast_tracker") or {},
        "market_rows": report.get("market_rows") or [],
        "decomposition": report.get("decomposition") or {},
    }


def _comparison_metrics(comp):
    comp = comp or {}
    return {
        "rows": comp.get("n", 0),
        "candidate_brier": comp.get("candidate_brier"),
        "current_brier": comp.get("current_brier"),
        "recorded_brier": comp.get("recorded_brier"),
        "market_brier": comp.get("market_brier"),
        "delta_vs_current": comp.get("delta_vs_current"),
        "delta_vs_market": comp.get("delta_vs_market"),
        "candidate_skill": comp.get("candidate_skill"),
        "candidate_ece": comp.get("candidate_ece"),
        "base_rate": comp.get("base_rate"),
    }


def _read_extra_location_transfer_report(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "promotion_gate": {
                "status": "MISSING",
                "serving_promotion_allowed": False,
                "reasons": ["extra-location transfer report is missing"],
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(payload)
    payload["path"] = str(path)
    payload["exists"] = True
    return payload


def _read_hourly_performance_report(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "hourly_performance_gate": {
                "status": "MISSING",
                "blockers": [
                    {
                        "gate": "hourly_performance_missing",
                        "detail": "hourly performance gate artifact is missing",
                        "remediation_command": "python -m weather.reporting.hourly_model_performance",
                    }
                ],
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(payload)
    payload["path"] = str(path)
    payload["exists"] = True
    return payload


def _read_candidate_hourly_performance_report(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "candidate_hourly_gate": {
                "status": "MISSING",
                "blockers": [
                    {
                        "gate": "candidate_hourly_performance_missing",
                        "detail": "candidate hourly performance artifact is missing",
                        "remediation_command": "python -m weather.reporting.candidate_hourly_performance",
                    }
                ],
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(payload)
    payload["path"] = str(path)
    payload["exists"] = True
    return payload


def _read_ten_minute_performance_report(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "ten_minute_performance_gate": {
                "status": "MISSING",
                "blockers": [
                    {
                        "gate": "ten_minute_performance_missing",
                        "detail": "10-minute performance gate artifact is missing",
                        "remediation_command": "python -m weather.reporting.ten_minute_model_performance",
                    }
                ],
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(payload)
    payload["path"] = str(path)
    payload["exists"] = True
    return payload


def _read_candidate_ten_minute_performance_report(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "candidate_ten_minute_gate": {
                "status": "MISSING",
                "blockers": [
                    {
                        "gate": "candidate_ten_minute_performance_missing",
                        "detail": "candidate 10-minute performance artifact is missing",
                        "remediation_command": "python -m weather.reporting.ten_minute_model_performance --item147-rows <candidate_rows.csv>",
                    }
                ],
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(payload)
    payload["path"] = str(path)
    payload["exists"] = True
    return payload


def _read_source_family_inventory(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "promotion_preflight": {
                "status": "MISSING",
                "blocked_families": [],
                "blocking_rows": [],
                "blocked_family_count": None,
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    preflight = payload.get("promotion_preflight") or {}
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "promotion_preflight": preflight,
    }


def _read_fleet_observability(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "summary": {
                "live_forward_slo_status": "MISSING",
                "tape_backup_status": "MISSING",
            },
            "tape_backup": {"status": "MISSING"},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    tape = payload.get("tape_backup") or {}
    capacity = tape.get("capacity_preflight") or {}
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "tape_backup": {
            "status": tape.get("status"),
            "backup_root": tape.get("backup_root"),
            "missing_critical_files": tape.get("missing_critical_files"),
            "restore_drill_sla_status": tape.get("restore_drill_sla_status"),
            "capacity_preflight": {
                "status": capacity.get("status"),
                "free_bytes": capacity.get("free_bytes"),
                "required_bytes": capacity.get("required_bytes"),
                "insufficient_bytes": capacity.get("insufficient_bytes"),
            },
        },
    }


def _action_for_verdict(verdict):
    if verdict == "PASS":
        return "PROMOTE_CANDIDATE"
    if verdict == "BLOCK":
        return "BLOCK_CANDIDATE"
    return "KEEP_SHADOW"


def _family_title(family_unit):
    if str(family_unit or "").lower() == "all":
        return "All-Market"
    return f"{family_unit or DEFAULT_FAMILY_UNIT}-Family"


def _market_scope_phrase(family_unit):
    if str(family_unit or "").lower() == "all":
        return "market(s)"
    return f"{family_unit or DEFAULT_FAMILY_UNIT} market(s)"


def build_family_decisions(
    manifest,
    trust_rows,
    candidate_report,
    family_unit=DEFAULT_FAMILY_UNIT,
    specs=None,
):
    """Return per-market promotion decisions for a unit family."""
    specs = _family_specs(family_unit, specs=specs)
    family_ids = {spec.id for spec in specs}
    corpus_counts = Counter(
        entry.get("market_id")
        for entry in manifest.get("entries") or []
        if entry.get("market_id") in family_ids
    )
    trust_by_market = {row.get("market"): row for row in trust_rows if row.get("market")}
    candidate_by_market = {
        row.get("market_id"): row
        for row in candidate_report.get("market_rows") or []
        if row.get("market_id")
    }
    replay_gate = candidate_report.get("replay_gate") or {"global_ok": True}
    global_ok = bool(replay_gate.get("global_ok", True))

    decisions = []
    for spec in sorted(specs, key=lambda item: item.id):
        row = candidate_by_market.get(spec.id)
        if row:
            verdict = row.get("verdict") or "BLOCK"
            reason = row.get("reason") or ""
            snapshots = row.get("snapshots", 0)
            band_rows = row.get("rows", 0)
            metrics = _comparison_metrics(row.get("comparison"))
            blocked_validation = row.get("blocked_validation") or {}
        else:
            verdict = "SHADOW"
            reason = "no pinned candidate rows for this family market"
            snapshots = 0
            band_rows = 0
            metrics = _comparison_metrics(None)
            blocked_validation = {}

        if verdict == "PASS" and not global_ok:
            verdict = "BLOCK"
            reason = f"global replay gate failed: {replay_gate.get('corpus_message') or replay_gate.get('fidelity_message')}"
        if verdict == "PASS" and blocked_validation and not blocked_validation.get("passed"):
            verdict = "BLOCK"
            detail = "; ".join(blocked_validation.get("reasons") or []) or "blocked validation failed"
            reason = f"blocked validation failed: {detail}"

        trust = trust_by_market.get(spec.id) or {}
        decisions.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "family_unit": family_unit,
            "action": _action_for_verdict(verdict),
            "verdict": verdict,
            "reason": reason,
            "settled_days_in_corpus": int(corpus_counts.get(spec.id, 0)),
            "candidate_days": row.get("days", 0) if row else 0,
            "candidate_snapshots": snapshots,
            "candidate_band_rows": band_rows,
            "trust_score": trust.get("trust_score"),
            "trust_grade": trust.get("grade"),
            "trust_settled_days": trust.get("settled_days"),
            "metrics": metrics,
            "blocked_validation": blocked_validation,
        })

    counts = Counter(item["action"] for item in decisions)
    return {
        "family_unit": family_unit,
        "family_market_count": len(specs),
        "global_replay_gate_ok": global_ok,
        "promote_markets": [item["market_id"] for item in decisions if item["action"] == "PROMOTE_CANDIDATE"],
        "shadow_markets": [item["market_id"] for item in decisions if item["action"] == "KEEP_SHADOW"],
        "blocked_markets": [item["market_id"] for item in decisions if item["action"] == "BLOCK_CANDIDATE"],
        "action_counts": dict(sorted(counts.items())),
        "markets": decisions,
    }


def _decision_table_rows(decisions):
    rows = []
    for item in decisions:
        metrics = item.get("metrics") or {}
        blocked = item.get("blocked_validation") or {}
        rows.append([
            item.get("market_id"),
            item.get("candidate_days"),
            item.get("candidate_snapshots"),
            item.get("candidate_band_rows"),
            f"{item.get('trust_score', '-')}/100 {item.get('trust_grade', '')}".strip(),
            fmt_num(metrics.get("candidate_brier")),
            fmt_num(metrics.get("current_brier")),
            fmt_num(metrics.get("market_brier")),
            fmt_signed(metrics.get("delta_vs_current"), 4),
            fmt_signed(metrics.get("delta_vs_market"), 4),
            blocked.get("verdict") or "-",
            item.get("action"),
            item.get("reason") or "-",
        ])
    return rows


def _readiness_market_details(decisions, action):
    market_rows = decisions.get("markets") or []
    details = []
    for item in market_rows:
        if item.get("action") != action:
            continue
        metrics = item.get("metrics") or {}
        details.append({
            "market_id": item.get("market_id"),
            "action": action,
            "reason": item.get("reason") or "-",
            "candidate_brier": metrics.get("candidate_brier"),
            "current_brier": metrics.get("current_brier"),
            "market_brier": metrics.get("market_brier"),
            "delta_vs_current": metrics.get("delta_vs_current"),
            "delta_vs_market": metrics.get("delta_vs_market"),
        })
    if details:
        return details
    fallback_key = "shadow_markets" if action == "KEEP_SHADOW" else "blocked_markets"
    return [
        {
            "market_id": market_id,
            "action": action,
            "reason": "-",
            "candidate_brier": None,
            "current_brier": None,
            "market_brier": None,
            "delta_vs_current": None,
            "delta_vs_market": None,
        }
        for market_id in decisions.get(fallback_key) or []
    ]


def _candidate_ten_minute_variant_ids(candidate_ten_minute_performance):
    payload = candidate_ten_minute_performance or {}
    ids = set()
    for value in payload.get("variant_ids") or []:
        if value not in (None, ""):
            ids.add(str(value))
    for key in ("candidate_ten_minute_performance", "candidate_item147"):
        nested = payload.get(key) or {}
        for value in nested.get("variant_ids") or []:
            if value not in (None, ""):
                ids.add(str(value))
    gate = payload.get("candidate_ten_minute_gate") or {}
    for value in gate.get("variant_ids") or []:
        if value not in (None, ""):
            ids.add(str(value))
    return ids


def promotion_readiness(
    candidate,
    serving,
    decisions,
    extra_location_transfer=None,
    hourly_performance=None,
    candidate_hourly_performance=None,
    ten_minute_performance=None,
    candidate_ten_minute_performance=None,
    source_family_inventory=None,
    fleet_observability=None,
):
    blockers = []
    market_scope = _market_scope_phrase(decisions.get("family_unit"))
    aggregate = candidate.get("aggregate") or {}
    candidate_shadow = candidate.get("candidate_shadow_variants") or {}
    if candidate_shadow.get("uses_market_features"):
        blockers.append({
            "category": "market_informed_candidate",
            "severity": "block",
            "detail": (
                "candidate variant uses market features; market-informed evidence may support "
                "quote/risk gates but cannot satisfy weather-only core promotion readiness"
            ),
            "evidence": candidate_shadow,
        })
    delta_vs_market = aggregate.get("delta_vs_market")
    if delta_vs_market is not None and delta_vs_market > 0:
        blockers.append({
            "category": "candidate_market_skill",
            "severity": "open",
            "detail": (
                f"aggregate candidate trails market Brier by {delta_vs_market:+.4f}; "
                "broad readiness requires aggregate delta_vs_market <= 0 and daily-first clearance"
            ),
        })
    blocked_validation = candidate.get("blocked_validation") or {}
    if blocked_validation and not blocked_validation.get("passed"):
        blockers.append({
            "category": "blocked_validation",
            "severity": "block",
            "detail": (
                "daily-first blocked validation failed: "
                + ("; ".join(blocked_validation.get("reasons") or []) or "inspect blocked validation gate")
            ),
            "evidence": blocked_validation,
        })
    shadow_details = _readiness_market_details(decisions, "KEEP_SHADOW")
    shadow_markets = [row.get("market_id") for row in shadow_details if row.get("market_id")]
    if shadow_markets:
        blockers.append({
            "category": "per_market_shadow",
            "severity": "open",
            "detail": (
                f"{len(shadow_markets)} {market_scope} remain shadow: "
                f"{', '.join(shadow_markets)}"
            ),
            "market_details": shadow_details,
        })
    blocked_details = _readiness_market_details(decisions, "BLOCK_CANDIDATE")
    blocked_markets = [row.get("market_id") for row in blocked_details if row.get("market_id")]
    if blocked_markets:
        blockers.append({
            "category": "per_market_block",
            "severity": "block",
            "detail": (
                f"{len(blocked_markets)} {market_scope} are blocked: "
                f"{', '.join(blocked_markets)}"
            ),
            "market_details": blocked_details,
        })
    if serving and serving.get("verdict") == "BLOCK":
        blockers.append({
            "category": "current_serving_gauntlet",
            "severity": "block",
            "detail": "current-serving gauntlet is BLOCK; inspect serving market rows before promotion",
        })
    source_preflight = (source_family_inventory or {}).get("promotion_preflight") or {}
    source_status = source_preflight.get("status")
    if source_family_inventory is not None and source_status != "PASS":
        blocked_families = source_preflight.get("blocked_families") or []
        blockers.append({
            "category": "source_family_preflight",
            "severity": "block",
            "detail": (
                f"source-family promotion preflight is {source_status or 'MISSING'}"
                + (f": {', '.join(blocked_families)}" if blocked_families else "")
            ),
            "evidence": source_preflight,
        })
    fleet_summary = (fleet_observability or {}).get("summary") or {}
    live_forward_status = fleet_summary.get("live_forward_slo_status")
    if fleet_observability is not None and live_forward_status not in {None, "OK", "PASS"}:
        blockers.append({
            "category": "live_forward_slo",
            "severity": "block" if live_forward_status in {"BLOCK", "CRITICAL", "MISSING"} else "open",
            "detail": f"live-forward collection SLO is {live_forward_status}; inspect fleet observability",
            "evidence": {
                "status": live_forward_status,
                "fleet_status": (fleet_observability or {}).get("status"),
                "path": (fleet_observability or {}).get("path"),
            },
        })
    tape = (fleet_observability or {}).get("tape_backup") or {}
    tape_status = tape.get("status") or fleet_summary.get("tape_backup_status")
    if fleet_observability is not None and tape_status not in {None, "OK", "PASS"}:
        capacity = tape.get("capacity_preflight") or {}
        insufficient = capacity.get("insufficient_bytes")
        detail = f"tape backup status is {tape_status}; promotion readiness requires current backup/restore evidence"
        if insufficient is not None:
            detail += f" ({insufficient} bytes short)"
        blockers.append({
            "category": "tape_backup_sla",
            "severity": "block" if tape_status not in {"WARN"} else "open",
            "detail": detail,
            "evidence": tape,
        })
    hourly_gate = (hourly_performance or {}).get("hourly_performance_gate") or {}
    hourly_status = hourly_gate.get("status")
    candidate_hourly_gate = (candidate_hourly_performance or {}).get("candidate_hourly_gate") or {}
    candidate_hourly_status = candidate_hourly_gate.get("status")
    candidate_variant_id = (candidate.get("candidate_shadow_variants") or {}).get("variant_id")
    candidate_hourly_variant_ids = {
        str(value)
        for value in (candidate_hourly_performance or {}).get("variant_ids") or []
        if value not in (None, "")
    }
    candidate_hourly_matches = bool(
        candidate_variant_id and str(candidate_variant_id) in candidate_hourly_variant_ids
    )
    hourly_mitigation = {
        "applied": bool(
            hourly_status in {"BLOCK", "MISSING"}
            and candidate_hourly_status == "PASS"
            and candidate_hourly_matches
        ),
        "current_hourly_status": hourly_status,
        "candidate_hourly_status": candidate_hourly_status,
        "candidate_variant_id": candidate_variant_id,
        "candidate_hourly_variant_ids": sorted(candidate_hourly_variant_ids),
        "candidate_hourly_matches": candidate_hourly_matches,
        "current_hourly_gate": hourly_gate,
        "candidate_hourly_gate": candidate_hourly_gate,
    }
    if hourly_status in {"BLOCK", "MISSING"} and not hourly_mitigation["applied"]:
        first = hourly_gate.get("first_blocker") or next(iter(hourly_gate.get("blockers") or []), {})
        blockers.append({
            "category": "hourly_performance_gate",
            "severity": "block" if hourly_status == "BLOCK" else "open",
            "detail": (
                f"hourly performance gate is {hourly_status}: "
                + (first.get("detail") or "inspect hourly model performance report")
            ),
            "evidence": hourly_gate,
        })
    ten_minute_gate = (ten_minute_performance or {}).get("ten_minute_performance_gate") or {}
    ten_minute_status = ten_minute_gate.get("status")
    candidate_ten_minute_gate = (candidate_ten_minute_performance or {}).get("candidate_ten_minute_gate") or {}
    candidate_ten_minute_status = candidate_ten_minute_gate.get("status")
    candidate_ten_minute_variant_ids = _candidate_ten_minute_variant_ids(candidate_ten_minute_performance)
    candidate_ten_minute_matches = bool(
        candidate_variant_id and str(candidate_variant_id) in candidate_ten_minute_variant_ids
    )
    ten_minute_mitigation = {
        "applied": bool(
            ten_minute_status in {"BLOCK", "MISSING"}
            and candidate_ten_minute_status == "PASS"
            and candidate_ten_minute_matches
        ),
        "current_ten_minute_status": ten_minute_status,
        "candidate_ten_minute_status": candidate_ten_minute_status,
        "candidate_variant_id": candidate_variant_id,
        "candidate_ten_minute_variant_ids": sorted(candidate_ten_minute_variant_ids),
        "candidate_ten_minute_matches": candidate_ten_minute_matches,
        "current_ten_minute_gate": ten_minute_gate,
        "candidate_ten_minute_gate": candidate_ten_minute_gate,
    }
    if ten_minute_status in {"BLOCK", "MISSING"} and not ten_minute_mitigation["applied"]:
        first = ten_minute_gate.get("first_blocker") or next(iter(ten_minute_gate.get("blockers") or []), {})
        blockers.append({
            "category": "ten_minute_performance_gate",
            "severity": "block" if ten_minute_status == "BLOCK" else "open",
            "detail": (
                f"10-minute performance gate is {ten_minute_status}: "
                + (first.get("detail") or "inspect 10-minute model performance report")
            ),
            "evidence": ten_minute_gate,
        })
    extra_gate = (extra_location_transfer or {}).get("promotion_gate") or {}
    extra_gate_status = extra_gate.get("status")
    if extra_gate_status in {"BLOCK", "BLOCKED", "MISSING"}:
        blockers.append({
            "category": "no_market_extra_location_shadow_lane",
            "severity": "block" if extra_gate_status != "MISSING" else "open",
            "detail": (
                "extra-location shadow lane gate is "
                f"{extra_gate_status}: "
                + ("; ".join(extra_gate.get("reasons") or []) or "inspect transfer report")
            ),
            "evidence": extra_gate,
        })
    elif extra_gate_status == "SHADOW_ONLY":
        blockers.append({
            "category": "no_market_extra_location_shadow_lane",
            "severity": "open",
            "detail": (
                "extra-location shadow lane is inconclusive and cannot affect serving: "
                + ("; ".join(extra_gate.get("reasons") or []) or "inspect transfer report")
            ),
            "evidence": extra_gate,
        })
    return {
        "status": "READY" if not blockers else "OPEN",
        "blockers": blockers,
        "shadow_market_details": shadow_details,
        "blocked_market_details": blocked_details,
        "hourly_performance_mitigation": hourly_mitigation,
        "ten_minute_performance_mitigation": ten_minute_mitigation,
    }


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
            "claim_lane": "market_informed_clob_overlay",
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
    source_family = payload.get("source_family_inventory") or {}
    if source_family:
        preflight = source_family.get("promotion_preflight") or {}
        rows.append([
            "Source family preflight",
            preflight.get("status") or source_family.get("status") or "-",
            ", ".join(preflight.get("blocked_families") or []) or "no blocked active input families",
        ])
    fleet = payload.get("fleet_observability") or {}
    if fleet:
        summary = fleet.get("summary") or {}
        tape = fleet.get("tape_backup") or {}
        rows.append([
            "Live-forward SLO",
            summary.get("live_forward_slo_status") or "-",
            f"fleet status {fleet.get('status') or '-'}",
        ])
        rows.append([
            "Tape backup SLA",
            tape.get("status") or summary.get("tape_backup_status") or "-",
            f"backup root {tape.get('backup_root') or '-'}",
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
        "market_informed_clob_overlay": {
            "counts_toward_core_skill_claim": False,
            "may_support_quote_gating": True,
            "owner_row_count": sum(
                1 for row in owner_rows
                if row.get("claim_lane") == "market_informed_clob_overlay"
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


def write_report(path, payload, min_free_bytes=0):
    path = Path(path)
    corpus = payload.get("corpus") or {}
    candidate = payload.get("candidate") or {}
    candidate_agg = candidate.get("aggregate") or {}
    replay_gate = candidate.get("replay_gate") or {}
    decisions = payload.get("decisions") or {}
    serving = payload.get("serving_gauntlet")
    readiness = payload.get("readiness") or {}

    lines = [
        f"# {_family_title(payload.get('family_unit'))} Promotion Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Family unit: `{payload.get('family_unit')}`",
        "",
        "## Decision Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Candidate verdict", candidate.get("verdict") or "-"],
            ["Candidate market-only verdict", candidate.get("candidate_market_verdict") or "-"],
            ["Cutover decision", candidate.get("cutover_decision") or "-"],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Readiness status", readiness.get("status") or "-"],
            ["Promote", ", ".join(decisions.get("promote_markets") or []) or "-"],
            ["Shadow", ", ".join(decisions.get("shadow_markets") or []) or "-"],
            ["Blocked", ", ".join(decisions.get("blocked_markets") or []) or "-"],
        ],
    )
    lines += [
        "",
        "## Promotion Readiness Blockers",
        "",
    ]
    lines += markdown_table(
        ["Category", "Severity", "Detail"],
        _readiness_table_rows(readiness),
    )
    readiness_details = _readiness_market_detail_rows(readiness)
    if readiness_details:
        lines += [
            "",
            "### Shadow/Block Explanation Detail",
            "",
        ]
        lines += markdown_table(
            [
                "Market",
                "Action",
                "Candidate Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Reason",
            ],
            readiness_details,
        )
    operational_gate_rows = _operational_gate_rows(payload)
    if operational_gate_rows:
        lines += [
            "",
            "## Operational Promotion Gates",
            "",
        ]
        lines += markdown_table(
            ["Gate", "Status", "Detail"],
            operational_gate_rows,
        )
    extra_transfer = payload.get("extra_location_transfer") or {}
    if extra_transfer:
        extra_gate = extra_transfer.get("promotion_gate") or {}
        extra_evidence = extra_transfer.get("evidence_accounting") or {}
        lines += [
            "",
            "## No-Market Extra-Location Shadow Lane",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Report", extra_transfer.get("path") or "-"],
                ["Exists", extra_transfer.get("exists")],
                ["Status", extra_transfer.get("status") or "-"],
                ["Gate", extra_gate.get("status") or "-"],
                ["Serving promotion allowed", extra_gate.get("serving_promotion_allowed")],
                ["Target market-days scored", extra_evidence.get("target_market_days_scored", 0)],
                ["Extra location-days", extra_evidence.get("extra_location_days", 0)],
                ["Row multiplier", fmt_num(extra_evidence.get("row_multiplier"))],
                ["Reasons", "; ".join(extra_gate.get("reasons") or []) or "-"],
            ],
        )
    lines += [
        "",
        "## Refresh Artifacts",
        "",
    ]
    lines += markdown_table(
        ["Artifact", "Path / Hash"],
        [
            ["Promotion corpus", f"{corpus.get('path')} / {corpus.get('corpus_hash')}"],
            ["Location trust", (payload.get("trust") or {}).get("path") or "-"],
            ["Candidate JSON", candidate.get("json_path") or "-"],
            ["Candidate report", candidate.get("report_path") or "-"],
            ["Serving gauntlet", (serving or {}).get("report_path") or "skipped"],
            ["Candidate hourly performance", (payload.get("candidate_hourly_performance") or {}).get("path") or "-"],
            ["10-minute performance", (payload.get("ten_minute_performance") or {}).get("path") or "-"],
            ["Candidate 10-minute performance", (payload.get("candidate_ten_minute_performance") or {}).get("path") or "-"],
            ["Source family inventory", (payload.get("source_family_inventory") or {}).get("path") or "-"],
            ["Fleet observability", (payload.get("fleet_observability") or {}).get("path") or "-"],
        ],
    )
    lines += [
        "",
        "## Corpus",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count", 0)],
            ["Pinned snapshots", corpus.get("snapshot_count", 0)],
            ["Band rows", corpus.get("band_row_count", 0)],
            ["Identity records", corpus.get("identity_record_count", 0)],
            ["Skipped folders", corpus.get("skipped_count", 0)],
        ],
    )
    lines += [
        "",
        "## Candidate Replay",
        "",
    ]
    candidate_evidence = candidate.get("evidence_accounting") or {}
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Rows", candidate_agg.get("rows", 0)],
            ["Unique observations", candidate_evidence.get("unique_observation_count", candidate_agg.get("rows", 0))],
            ["Snapshots", candidate_evidence.get("snapshot_count", 0)],
            ["Market-days", candidate_evidence.get("market_day_count", 0)],
            ["Row multiplier", fmt_num(candidate_evidence.get("row_multiplier"))],
            ["Blocked validation", (candidate.get("blocked_validation") or {}).get("verdict") or "-"],
            ["Blocked validation split", (candidate.get("blocked_validation") or {}).get("split_mode") or "-"],
            ["Candidate Brier", fmt_num(candidate_agg.get("candidate_brier"))],
            ["Current Brier", fmt_num(candidate_agg.get("current_brier"))],
            ["Recorded Brier", fmt_num(candidate_agg.get("recorded_brier"))],
            ["Market Brier", fmt_num(candidate_agg.get("market_brier"))],
            ["Delta vs current", fmt_signed(candidate_agg.get("delta_vs_current"), 4)],
            ["Delta vs market", fmt_signed(candidate_agg.get("delta_vs_market"), 4)],
        ],
    )
    candidate_artifact = candidate.get("artifact") or {}
    if candidate_artifact.get("feature_subset") == "forecast_profile":
        guardrails = candidate.get("forecast_profile_guardrails") or {}
        contract = candidate_artifact.get("feature_subset_contract") or {}
        lines += [
            "",
            "### Forecast-Profile Calibration Lane",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Subset", candidate_artifact.get("feature_subset")],
                ["Anchor", contract.get("anchor_feature") or "forecast_high"],
                ["Allowed families", ", ".join(contract.get("allowed_feature_families") or []) or "-"],
                ["Blocked high-disagreement markets", ", ".join(guardrails.get("blocked_markets") or []) or "-"],
                ["Promotion blocker", (candidate_artifact.get("forecast_profile_calibration") or {}).get("promotion_blocker") or "-"],
            ],
        )
        if (candidate.get("slices") or {}).get("by_cutoff_regime"):
            lines += ["", "#### Cutoff-Regime Replay", ""]
            lines += markdown_table(
                [
                    "Regime",
                    "Rows",
                    "Candidate Brier",
                    "Current Brier",
                    "Market Brier",
                    "Delta Current",
                    "Delta Market",
                ],
                [
                    [
                        row.get("group") or "-",
                        row.get("n", 0),
                        fmt_num(row.get("candidate_brier")),
                        fmt_num(row.get("current_brier")),
                        fmt_num(row.get("market_brier")),
                        fmt_signed(row.get("delta_vs_current"), 4),
                        fmt_signed(row.get("delta_vs_market"), 4),
                    ]
                    for row in (candidate.get("slices") or {}).get("by_cutoff_regime") or []
                ],
            )
    gap_drivers = _candidate_gap_driver_rows(candidate)
    lines += [
        "",
        "### Candidate Gap Drivers",
        "",
    ]
    lines += markdown_table(
        [
            "Slice",
            "Group",
            "Rows",
            "Candidate/Micro Brier",
            "Market Brier",
            "Delta Current",
            "Delta Market",
            "Excess Brier Rows",
        ],
        _gap_driver_table_rows(gap_drivers),
    )
    gap_owner_rows = payload.get("gap_owner_table") or build_gap_owner_table(gap_drivers, decisions)
    claims = payload.get("model_skill_claims") or model_skill_claims(candidate, gap_owner_rows)
    lines += [
        "",
        "### Model-Skill Claim Lanes",
        "",
    ]
    lines += markdown_table(
        ["Lane", "Core Claim Allowed / Counts", "Quote Gating", "Delta Market", "Reason"],
        _model_skill_claim_rows(claims),
    )
    if gap_owner_rows:
        lines += [
            "",
            "### Gap Owner Experiments",
            "",
        ]
        lines += markdown_table(
            [
                "Slice",
                "Group",
                "Weighted Gap",
                "Affected Markets",
                "Owner",
                "Roadmap",
                "Next Experiment",
                "Artifact",
                "Claim Lane",
                "Core Claim Credit",
                "Clearance Rule",
            ],
            _gap_owner_table_rows(gap_owner_rows),
        )
    market_diagnostics = payload.get("market_skill_diagnostics") or market_skill_diagnostics(candidate, decisions)
    if market_diagnostics:
        lines += [
            "",
            "### Market-Skill Diagnostics",
            "",
        ]
        lines += markdown_table(
            [
                "Market",
                "Action",
                "Candidate Brier",
                "Current Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Next Experiment",
                "Reason",
            ],
            _market_skill_diagnostic_rows(market_diagnostics),
        )
    source_freshness_rows = _candidate_source_freshness_rows(candidate)
    if source_freshness_rows:
        lines += [
            "",
            "### Source Freshness Slice",
            "",
        ]
        lines += markdown_table(
            [
                "Group",
                "Rows",
                "Candidate/Micro Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Excess Brier Rows",
            ],
            _gap_driver_table_rows(source_freshness_rows, include_slice=False),
        )
    else:
        lines += [
            "",
            "Source-freshness gap drivers are not available in the candidate replay rows yet.",
        ]
    micro = candidate.get("microstructure") or {}
    micro_agg = micro.get("aggregate") or {}
    micro_gated_agg = micro.get("gated_aggregate") or {}
    micro_gate = micro.get("gate") or {}
    if micro:
        lines += [
            "",
            "## Item 38 Microstructure Shadow Score",
            "",
        ]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Eligible CLOB rows", micro.get("eligible_rows", 0)],
                ["OOF predicted rows", micro.get("predicted_rows", 0)],
                ["OOF folds", micro.get("fold_count", 0)],
                ["Casebook-matched rows", micro.get("casebook_matched_rows", 0)],
                ["Gate allowed taxonomies", ", ".join(micro_gate.get("allowed_taxonomies") or []) or "-"],
                ["Gated overlay rows", micro.get("gated_overlay_rows", 0)],
                ["Gated base-fallback rows", micro.get("gated_base_rows", 0)],
                ["Artifact", micro.get("artifact_path") or "-"],
            ],
        )
        lines += ["", "### Aggregate", ""]
        lines += markdown_table(
            ["Scope", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    "Raw overlay",
                    micro_agg.get("rows", 0),
                    fmt_num(micro_agg.get("micro_brier")),
                    fmt_num(micro_agg.get("candidate_brier")),
                    fmt_num(micro_agg.get("market_brier")),
                    fmt_signed(micro_agg.get("delta_vs_candidate"), 4),
                    fmt_signed(micro_agg.get("delta_vs_market"), 4),
                ],
                [
                    "Taxonomy-gated overlay",
                    micro_gated_agg.get("rows", 0),
                    fmt_num(micro_gated_agg.get("micro_brier")),
                    fmt_num(micro_gated_agg.get("candidate_brier")),
                    fmt_num(micro_gated_agg.get("market_brier")),
                    fmt_signed(micro_gated_agg.get("delta_vs_candidate"), 4),
                    fmt_signed(micro_gated_agg.get("delta_vs_market"), 4),
                ],
            ],
        )
        lines += ["", "### Taxonomy Gate", ""]
        lines += markdown_table(
            ["Taxonomy", "Action", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market", "Reason"],
            [
                [
                    row.get("taxonomy") or "-",
                    "ALLOW" if row.get("allowed") else "BASE",
                    row.get("rows", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                    row.get("reason") or "-",
                ]
                for row in micro_gate.get("decisions") or []
            ],
        )
        lines += ["", "### Raw Target Slices", ""]
        lines += markdown_table(
            ["Taxonomy", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    row.get("group") or "-",
                    row.get("n", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                ]
                for row in micro.get("target_slices") or []
            ],
        )
        lines += ["", "### Gated Target Slices", ""]
        lines += markdown_table(
            ["Taxonomy", "Rows", "Micro Brier", "Base Brier", "Market Brier", "Delta Base", "Delta Market"],
            [
                [
                    row.get("group") or "-",
                    row.get("n", 0),
                    fmt_num(row.get("micro_brier")),
                    fmt_num(row.get("candidate_brier")),
                    fmt_num(row.get("market_brier")),
                    fmt_signed(row.get("delta_vs_candidate"), 4),
                    fmt_signed(row.get("delta_vs_market"), 4),
                ]
                for row in micro.get("gated_target_slices") or []
            ],
        )
    lines += [
        "",
        "## Global Replay Gate",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if replay_gate.get("corpus_ok") else "FAIL", replay_gate.get("corpus_message") or "-"],
            ["Replay fidelity", "PASS" if replay_gate.get("fidelity_ok") else "FAIL", replay_gate.get("fidelity_message") or "-"],
        ],
    )
    if serving:
        lines += [
            "",
            "## Current-Serving Gauntlet",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Verdict", serving.get("verdict") or "-"],
                ["Corpus OK", serving.get("corpus_ok")],
                ["Fidelity OK", serving.get("fidelity_ok")],
                ["Regression OK", serving.get("baseline_ok")],
                ["Forecast tracker", (serving.get("forecast_tracker") or {}).get("message") or "-"],
            ],
        )
        lines += ["", "### Serving Gauntlet Markets", ""]
        lines += markdown_table(
            [
                "Market", "Verdict", "Rows", "Replayed Brier", "Recorded Brier",
                "Market Brier", "Code Effect", "Reason",
            ],
            _serving_table_rows(serving),
        )
        blocking_source_rows = _serving_blocking_source_freshness_rows(serving)
        if blocking_source_rows:
            lines += ["", "### Serving Blocking Source Freshness", ""]
            lines += markdown_table(
                [
                    "Market",
                    "Group",
                    "Rows",
                    "Replayed Brier",
                    "Recorded Brier",
                    "Market Brier",
                    "Code Effect",
                    "Excess Brier Rows",
                ],
                blocking_source_rows,
            )
    lines += [
        "",
        "## Per-Market Decisions",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Days", "Snaps", "Rows", "Trust", "Candidate Brier",
            "Current Brier", "Market Brier", "Delta Current",
            "Delta Market", "Blocked Validation", "Action", "Reason",
        ],
        _decision_table_rows(decisions.get("markets") or []),
    )
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_artifact_disk_headroom(
        path,
        estimated_bytes=len(text.encode("utf-8")),
        min_free_bytes=min_free_bytes,
        context="promotion refresh Markdown report export",
    )
    path.write_text(text, encoding="utf-8")
    return path


def _serving_gauntlet_args(args, corpus_path):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        baseline=args.baseline,
        no_baseline=args.no_baseline,
        forecast_tracker=args.forecast_tracker,
        out=args.serving_gauntlet_report,
        replay_report=args.serving_replay_report,
        tol=args.tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
    )


def _candidate_args(args, corpus_path, long_job_guard_info=None):
    return SimpleNamespace(
        corpus=str(corpus_path),
        snapshots_root=args.snapshots_root,
        artifact=args.artifact,
        variant_registry=getattr(args, "variant_registry", str(DEFAULT_VARIANT_REGISTRY_PATH)),
        out=args.candidate_report,
        json_out=args.candidate_json,
        replay_report=args.current_replay_report,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
        min_days=args.min_days,
        min_trust=args.min_trust,
        max_fidelity_l1=args.max_fidelity_l1,
        clob_max_age_seconds=args.clob_max_age_seconds,
        casebook=args.casebook,
        candidate_variant_out=getattr(args, "candidate_variant_out", None) or None,
        candidate_variant_id=getattr(args, "candidate_variant_id", None) or None,
        candidate_variant_family=getattr(args, "candidate_variant_family", None) or None,
        candidate_variant_uses_market_features=bool(
            getattr(args, "candidate_variant_uses_market_features", False)
        ),
        candidate_variant_control=bool(getattr(args, "candidate_variant_control", False)),
        disable_candidate_variant_export=bool(getattr(args, "disable_candidate_variant_export", False)),
        microstructure_artifact=args.microstructure_artifact or None,
        microstructure_min_train_rows=args.microstructure_min_train_rows,
        skip_microstructure_overlay=args.skip_microstructure_overlay,
        min_artifact_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        require_exact_identity=args.require_exact_identity,
        require_all_markets=args.require_all_markets,
        long_job_guard_info=long_job_guard_info,
        fail_on_block=False,
    )


def run_promotion_refresh(args):
    with long_job_guard(
        "promotion_refresh",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=not getattr(args, "disable_long_job_guard", False),
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        try:
            _write_started_manifest(args, long_job_guard_info=guard)
            result = _run_promotion_refresh_guarded(args, long_job_guard_info=guard)
            payload, out_path, report_path = result
            _write_complete_manifest(
                args,
                payload,
                out_path,
                report_path,
                long_job_guard_info=guard,
            )
            return result
        except Exception as exc:
            _write_incomplete_manifest(args, exc, long_job_guard_info=guard)
            raise


def _incomplete_manifest_path(args):
    path = Path(getattr(args, "incomplete_manifest", DEFAULT_INCOMPLETE_MANIFEST) or DEFAULT_INCOMPLETE_MANIFEST)
    return path


def _manifest_paths(args):
    return {
        "out": _as_path(getattr(args, "out", None)),
        "report": _as_path(getattr(args, "report", None)),
        "corpus_out": _as_path(getattr(args, "corpus_out", None)),
        "trust_out": _as_path(getattr(args, "trust_out", None)),
        "candidate_json": _as_path(getattr(args, "candidate_json", None)),
        "candidate_report": _as_path(getattr(args, "candidate_report", None)),
    }


def _write_started_manifest(args, long_job_guard_info=None):
    path = _incomplete_manifest_path(args)
    payload = {
        "schema_version": "promotion_refresh_incomplete_v0.1",
        "status": "STARTED",
        "generated_at_utc": _utc_now(),
        "family_unit": getattr(args, "family_unit", DEFAULT_FAMILY_UNIT),
        "paths": _manifest_paths(args),
        "min_artifact_free_bytes": int(getattr(args, "min_artifact_free_bytes", 0) or 0),
        "long_job_guard": long_job_guard_info or {},
    }
    try:
        return _write_json(
            path,
            payload,
            min_free_bytes=0,
            context="promotion refresh started manifest export",
        )
    except OSError:
        return None


def _write_complete_manifest(args, payload, out_path, report_path, long_job_guard_info=None):
    path = _incomplete_manifest_path(args)
    readiness = payload.get("readiness") or {}
    decisions = payload.get("decisions") or {}
    summary = {
        "readiness_status": readiness.get("status"),
        "promote_count": len(decisions.get("promote_markets") or []),
        "shadow_count": len(decisions.get("shadow_markets") or []),
        "blocked_count": len(decisions.get("blocked_markets") or []),
    }
    manifest = {
        "schema_version": "promotion_refresh_incomplete_v0.1",
        "status": "COMPLETE",
        "generated_at_utc": _utc_now(),
        "family_unit": getattr(args, "family_unit", DEFAULT_FAMILY_UNIT),
        "paths": {
            **_manifest_paths(args),
            "written_out": _as_path(out_path),
            "written_report": _as_path(report_path),
        },
        "summary": summary,
        "min_artifact_free_bytes": int(getattr(args, "min_artifact_free_bytes", 0) or 0),
        "long_job_guard": long_job_guard_info or {},
    }
    try:
        return _write_json(
            path,
            manifest,
            min_free_bytes=0,
            context="promotion refresh completion manifest export",
        )
    except OSError:
        return None


def _write_incomplete_manifest(args, exc, long_job_guard_info=None):
    path = _incomplete_manifest_path(args)
    payload = {
        "schema_version": "promotion_refresh_incomplete_v0.1",
        "status": "INCOMPLETE",
        "generated_at_utc": _utc_now(),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "family_unit": getattr(args, "family_unit", DEFAULT_FAMILY_UNIT),
        "paths": _manifest_paths(args),
        "min_artifact_free_bytes": int(getattr(args, "min_artifact_free_bytes", 0) or 0),
        "long_job_guard": long_job_guard_info or {},
    }
    try:
        return _write_json(
            path,
            payload,
            min_free_bytes=0,
            context="promotion refresh incomplete manifest export",
        )
    except OSError:
        return None


def _run_promotion_refresh_guarded(args, long_job_guard_info=None):
    quality_grades = parse_quality_grades(args.quality_grades)
    manifest = build_promotion_corpus(
        folders=args.folders,
        snapshots_root=args.snapshots_root,
        as_of=args.as_of,
        quality_grades=quality_grades,
        include_reconstructed=args.include_reconstructed,
        allow_unsettled=args.allow_unsettled,
        market_id=None,
        min_snapshots=args.min_snapshots,
    )
    corpus_path = write_manifest(manifest, args.corpus_out)

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_path = _write_json(args.trust_out, trust_rows)

    precomputed_candidate_json = getattr(args, "precomputed_candidate_json", None)
    precomputed_candidate = None
    if precomputed_candidate_json:
        candidate_report = load_precomputed_candidate_report(
            precomputed_candidate_json,
            manifest,
        )
        candidate_json_path = precomputed_candidate_json
        candidate_report_path = (
            getattr(args, "precomputed_candidate_report", None)
            or args.candidate_report
        )
        precomputed_candidate = {
            "enabled": True,
            "json_path": _as_path(candidate_json_path),
            "report_path": _as_path(candidate_report_path),
            "corpus_hash": (candidate_report.get("corpus") or {}).get("corpus_hash"),
        }
    else:
        candidate_report = run_pooled_candidate_replay(
            _candidate_args(args, corpus_path, long_job_guard_info=long_job_guard_info)
        )
        candidate_json_path = args.candidate_json
        candidate_report_path = args.candidate_report

    serving_report = None
    if not args.skip_serving_gauntlet:
        serving_report = run_promotion_gauntlet(_serving_gauntlet_args(args, corpus_path))

    family_ids = [spec.id for spec in _family_specs(args.family_unit)]
    candidate_summary = _candidate_summary(
        candidate_report,
        candidate_json_path,
        candidate_report_path,
    )
    serving_summary = _serving_gauntlet_summary(
        serving_report,
        args.serving_gauntlet_report,
        args.serving_replay_report,
    )
    extra_location_transfer = _read_extra_location_transfer_report(
        getattr(args, "extra_location_transfer_report", None)
    )
    hourly_performance = _read_hourly_performance_report(
        getattr(args, "hourly_performance_report", DEFAULT_HOURLY_PERFORMANCE)
    )
    candidate_hourly_performance = _read_candidate_hourly_performance_report(
        getattr(args, "candidate_hourly_performance_report", DEFAULT_CANDIDATE_HOURLY_PERFORMANCE)
    )
    ten_minute_performance = _read_ten_minute_performance_report(
        getattr(args, "ten_minute_performance_report", DEFAULT_TEN_MINUTE_PERFORMANCE)
    )
    candidate_ten_minute_performance = _read_candidate_ten_minute_performance_report(
        getattr(args, "candidate_ten_minute_performance_report", DEFAULT_CANDIDATE_TEN_MINUTE_PERFORMANCE)
    )
    source_family_inventory = _read_source_family_inventory(
        getattr(args, "source_family_inventory", DEFAULT_SOURCE_FAMILY_INVENTORY)
    )
    fleet_observability = _read_fleet_observability(
        getattr(args, "fleet_observability_report", DEFAULT_FLEET_OBSERVABILITY)
    )
    decisions = build_family_decisions(
        manifest,
        trust_rows,
        candidate_report,
        family_unit=args.family_unit,
    )
    gap_drivers = _candidate_gap_driver_rows(candidate_summary)
    gap_owner_table = build_gap_owner_table(gap_drivers, decisions)
    claim_lanes = model_skill_claims(candidate_summary, gap_owner_table)
    market_diagnostics = market_skill_diagnostics(candidate_summary, decisions)
    gap_experiment_artifacts = write_gap_experiment_artifacts(
        [*gap_owner_table, *market_diagnostics],
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "family_unit": args.family_unit,
        "corpus": _manifest_summary(manifest, corpus_path),
        "trust": _trust_summary(trust_rows, trust_path, family_ids),
        "candidate": candidate_summary,
        "precomputed_candidate": precomputed_candidate or {"enabled": False},
        "serving_gauntlet": serving_summary,
        "decisions": decisions,
        "extra_location_transfer": extra_location_transfer,
        "hourly_performance": hourly_performance,
        "candidate_hourly_performance": candidate_hourly_performance,
        "ten_minute_performance": ten_minute_performance,
        "candidate_ten_minute_performance": candidate_ten_minute_performance,
        "source_family_inventory": source_family_inventory,
        "fleet_observability": fleet_observability,
        "readiness": promotion_readiness(
            candidate_summary,
            serving_summary,
            decisions,
            extra_location_transfer=extra_location_transfer,
            hourly_performance=hourly_performance,
            candidate_hourly_performance=candidate_hourly_performance,
            ten_minute_performance=ten_minute_performance,
            candidate_ten_minute_performance=candidate_ten_minute_performance,
            source_family_inventory=source_family_inventory,
            fleet_observability=fleet_observability,
        ),
        "gap_owner_table": gap_owner_table,
        "gap_experiment_artifacts": gap_experiment_artifacts,
        "market_skill_diagnostics": market_diagnostics,
        "model_skill_claims": claim_lanes,
        "long_job_guard": long_job_guard_info or {},
    }
    out_path = _write_json(
        args.out,
        payload,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
        context="promotion refresh summary JSON export",
    )
    report_path = write_report(
        args.report,
        payload,
        min_free_bytes=getattr(args, "min_artifact_free_bytes", 0),
    )
    return payload, out_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="Refresh promotion corpus, trust, pooled replay, and family promotion decisions."
    )
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders; defaults to discovered settled folders.")
    parser.add_argument("--family-unit", default=DEFAULT_FAMILY_UNIT, choices=["F", "all"])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--quality-grades", default=",".join(DEFAULT_QUALITY_GRADES))
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--min-snapshots", type=int, default=1)
    parser.add_argument("--corpus-out", default=str(DEFAULT_CORPUS))
    parser.add_argument("--trust-out", default=str(DEFAULT_TRUST_OUT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--variant-registry", default=str(DEFAULT_VARIANT_REGISTRY_PATH))
    parser.add_argument("--candidate-report", default=str(DEFAULT_CANDIDATE_REPORT))
    parser.add_argument("--candidate-json", default=str(DEFAULT_CANDIDATE_JSON))
    parser.add_argument(
        "--precomputed-candidate-json",
        default="",
        help="Use an existing pooled-candidate replay JSON instead of rerunning candidate replay.",
    )
    parser.add_argument(
        "--precomputed-candidate-report",
        default="",
        help="Optional Markdown report path paired with --precomputed-candidate-json.",
    )
    parser.add_argument("--current-replay-report", default=str(DEFAULT_CURRENT_REPLAY_REPORT))
    parser.add_argument("--serving-gauntlet-report", default=str(DEFAULT_SERVING_GAUNTLET_REPORT))
    parser.add_argument("--serving-replay-report", default=str(DEFAULT_SERVING_REPLAY_REPORT))
    parser.add_argument("--hourly-performance-report", default=str(DEFAULT_HOURLY_PERFORMANCE))
    parser.add_argument(
        "--candidate-hourly-performance-report",
        default=str(DEFAULT_CANDIDATE_HOURLY_PERFORMANCE),
        help="Optional candidate-hourly JSON that can mitigate a current-serving hourly gate for this candidate.",
    )
    parser.add_argument("--ten-minute-performance-report", default=str(DEFAULT_TEN_MINUTE_PERFORMANCE))
    parser.add_argument(
        "--candidate-ten-minute-performance-report",
        default=str(DEFAULT_CANDIDATE_TEN_MINUTE_PERFORMANCE),
        help="Optional candidate 10-minute JSON that can mitigate a current-serving weak-slot gate for this candidate.",
    )
    parser.add_argument("--source-family-inventory", default=str(DEFAULT_SOURCE_FAMILY_INVENTORY))
    parser.add_argument("--fleet-observability-report", default=str(DEFAULT_FLEET_OBSERVABILITY))
    parser.add_argument("--forecast-tracker", default=str(DEFAULT_FORECAST_TRACKER))
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--skip-serving-gauntlet", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--incomplete-manifest", default=str(DEFAULT_INCOMPLETE_MANIFEST))
    parser.add_argument("--current-tol", type=float, default=0.003)
    parser.add_argument("--tol", type=float, default=0.003)
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--clob-max-age-seconds", type=float, default=180.0)
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK))
    parser.add_argument("--candidate-variant-out", default=None,
                        help="Item-69-compatible candidate variant CSV. Defaults to the active registry contract when available.")
    parser.add_argument("--candidate-variant-id", default=None)
    parser.add_argument("--candidate-variant-family", default=None)
    parser.add_argument("--candidate-variant-uses-market-features", action="store_true")
    parser.add_argument("--candidate-variant-control", action="store_true")
    parser.add_argument("--disable-candidate-variant-export", action="store_true",
                        help="Disable registry-default candidate variant export.")
    parser.add_argument("--min-artifact-free-bytes", type=int, default=DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
                        help="Require this much free disk headroom after estimated variant CSV exports. Use 0 to disable.")
    parser.add_argument(
        "--extra-location-transfer-report",
        default="",
        help="Optional no-market target-vs-extra transfer JSON to surface as a promotion blocker.",
    )
    parser.add_argument("--microstructure-artifact", default=str(DEFAULT_MICROSTRUCTURE_ARTIFACT))
    parser.add_argument("--microstructure-min-train-rows", type=int, default=500)
    parser.add_argument("--skip-microstructure-overlay", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    payload, out_path, report_path = run_promotion_refresh(args)
    decisions = payload.get("decisions") or {}
    print(
        "Promotion refresh: "
        f"{len(decisions.get('promote_markets') or [])} promote, "
        f"{len(decisions.get('shadow_markets') or [])} shadow, "
        f"{len(decisions.get('blocked_markets') or [])} blocked"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    if args.fail_on_block and decisions.get("blocked_markets"):
        sys.exit(1)


if __name__ == "__main__":
    main()
