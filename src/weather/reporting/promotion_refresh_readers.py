"""End-to-end promotion refresh for family-pooled candidates.

This is the Item 33/37 bridge: when more settled market-days appear, one
command refreshes the pinned promotion corpus, location trust, pooled candidate
replay, and per-market promotion decisions.
"""
from __future__ import annotations

import argparse
import json
import shutil
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
DEFAULT_PROMOTION_ALLOWLIST = data_path() / "backtest" / "f_family_promotion_allowlist.json"
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
DEFAULT_SETTLED_DAY_FRESHNESS = data_path() / "backtest" / "settled_day_freshness.json"
DEFAULT_DATA_LAYER_AUDIT = data_path() / "backtest" / "data_layer_audit.json"
DEFAULT_INGEST_QUALITY_GATE = data_path() / "backtest" / "ingest_quality_gate.json"
DEFAULT_DAILY_LEARNING = data_path() / "backtest" / "daily_learning.json"
DEFAULT_PER_LOCATION_ARTIFACT_QUARANTINE = (
    data_path() / "backtest" / "per_location_artifact_quarantine.json"
)
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
    live_slo = payload.get("live_forward_slo") or {}
    clob = payload.get("clob") or {}
    clob_books = clob.get("books") or {}
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "live_forward_slo": {
            "status": "PASS" if live_slo.get("ok") else "BLOCK",
            "counts_toward_live_forward_gate": live_slo.get("counts_toward_live_forward_gate"),
            "reason": live_slo.get("reason"),
            "first_blocker": live_slo.get("first_blocker") or {},
        },
        "clob_books": {
            "status": "PASS" if clob_books.get("ok") else "BLOCK",
            "generated_at_utc": clob_books.get("generated_at_utc"),
            "max_gap_seconds_threshold": clob_books.get("max_gap_seconds_threshold"),
            "blocked_markets": [
                row.get("market_id")
                for row in clob_books.get("markets") or []
                if not row.get("ok")
            ],
        },
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


def _read_settled_day_freshness(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "summary": {},
            "repair_command": "python -m weather.operations.settled_day_freshness repair",
            "replay_status_repair_command": "python -m weather.operations.replay_status_backfill",
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "summary": payload.get("summary") or {},
        "repair_command": payload.get("repair_command"),
        "replay_status_repair_command": payload.get("replay_status_repair_command"),
    }


def _read_data_layer_audit(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "gate_summary": {"status": "MISSING"},
            "recommendation_count": 0,
            "p0_remediation_count": None,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    remediations = payload.get("remediation_manifest") or []
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": (payload.get("gate_summary") or {}).get("status") or payload.get("status"),
        "gate_summary": payload.get("gate_summary") or {},
        "recommendation_count": len(payload.get("recommendations") or []),
        "p0_remediation_count": sum(1 for row in remediations if row.get("priority") == "P0"),
        "remediation_manifest": remediations[:12],
    }


def _read_ingest_quality_gate(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "fail_reasons": ["ingest quality gate artifact is missing"],
            "warn_reasons": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "fail_reasons": payload.get("fail_reasons") or [],
        "warn_reasons": payload.get("warn_reasons") or [],
    }


def _read_daily_learning(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "summary": {"blocker_count": None},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "retrain_plan": payload.get("retrain_plan") or {},
    }


def _read_per_location_artifact_quarantine(path):
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "status": "MISSING",
            "summary": {
                "per_location_artifact_count": 0,
                "active_candidate_violation_count": 0,
            },
            "active_candidate_violations": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "active_feature_schema_version": payload.get("active_feature_schema_version"),
        "summary": payload.get("summary") or {},
        "active_candidate_violations": payload.get("active_candidate_violations") or [],
        "policy": payload.get("policy"),
    }


def _disk_headroom(path, min_free_bytes=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path.parent)
    min_free_bytes = int(min_free_bytes or 0)
    return {
        "path": str(path.parent),
        "status": "PASS" if usage.free >= min_free_bytes else "BLOCK",
        "free_bytes": int(usage.free),
        "min_free_bytes": min_free_bytes,
        "insufficient_bytes": max(0, min_free_bytes - int(usage.free)),
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

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
