"""Remediation manifest assembly for the fleet data-layer audit."""

from __future__ import annotations


def missing_artifact_folders(snapshot, artifact):
    rows = []
    for folder in snapshot.get("folders") or []:
        if not folder.get("training_ready"):
            continue
        presence = folder.get("artifact_presence") or {}
        if presence.get(artifact):
            continue
        rows.append({
            "market_id": folder.get("market_id"),
            "target_date": folder.get("target_date"),
            "folder": folder.get("folder"),
        })
    return rows


def supplemental_gate_failures(historical):
    rows = []
    for market in historical.get("markets") or []:
        market_id = market.get("market_id")
        nearby = market.get("nearby_history") or {}
        for source_row in nearby.get("supplemental_sources") or []:
            gate_row = source_row.get("promotion_gate") or {}
            if gate_row.get("ok"):
                continue
            rows.append({
                "market_id": market_id,
                "source_id": source_row.get("source_id"),
                "station": source_row.get("station"),
                "promotion_state": gate_row.get("promotion_state"),
                "reason": gate_row.get("reason"),
                "artifact_path": gate_row.get("artifact_path"),
                "adopted_date_windows": source_row.get("adopted_date_windows") or [],
            })
    return rows


def gate_owner(name):
    if name == "snapshot_low_fill_fields":
        return "feature contract"
    if name.startswith("snapshot_artifact_replay") or name == "snapshot_artifact_replay_inputs":
        return "replay/backfill"
    if name.startswith("snapshot_artifact_source_status") or name == "source_status_stale_or_failed_rate":
        return "collection/source health"
    if name.startswith("snapshot_artifact_features") or name.startswith("snapshot_artifact_components"):
        return "feature pipeline"
    if name == "forecast_payload_artifact_rate":
        return "forecast capture"
    if name in {"supplemental_station_validation", "canonical_history_provenance"}:
        return "historical source owner"
    if name == "quarantined_impossible_observations":
        return "data auditor"
    return "data layer"


def gate_command(name):
    commands = {
        "snapshot_low_fill_fields": (
            "python -m weather.reporting.data_quality.data_layer_audit --out data\\backtest\\data_layer_audit.json "
            "--report data\\backtest\\data_layer_audit_report.md"
        ),
        "snapshot_artifact_replay_inputs": (
            "python -m weather.operations.replay_status_backfill --reconstruct-missing "
            "--json-out data\\backtest\\replay_status_backfill.json "
            "--report-out data\\backtest\\replay_status_backfill_report.md"
        ),
        "snapshot_artifact_replay_input_status": (
            "python -m weather.operations.replay_status_backfill --overwrite --reconstruct-missing "
            "--json-out data\\backtest\\replay_status_backfill.json "
            "--report-out data\\backtest\\replay_status_backfill_report.md"
        ),
        "snapshot_artifact_source_status": "python -m weather.operations.daily_refresh run",
        "snapshot_artifact_features": "python -m weather.operations.daily_refresh run",
        "snapshot_artifact_components": "python -m weather.operations.daily_refresh run",
        "forecast_payload_artifact_rate": "python -m weather.operations.daily_refresh run",
        "source_status_stale_or_failed_rate": "python -m weather.operations.daily_refresh run",
        "reanalysis_raw_only_days": "python -m weather.reporting.data_quality.data_layer_audit",
        "quarantined_impossible_observations": "python -m weather.reporting.data_quality.data_auditor",
        "supplemental_station_validation": (
            "python -m weather.sources.supplemental_station_validation --markets toronto "
            "--start 2000-01-01 --end 2012-12-31 "
            "--out data\\backtest\\supplemental_station_validation.json "
            "--report data\\backtest\\supplemental_station_validation_report.md --strict"
        ),
        "canonical_history_provenance": "python -m weather.sources.canonical_history_guardrails",
    }
    return commands.get(name, "python -m weather.reporting.data_quality.data_layer_audit")


def expected_artifact(name, snapshot_optional_artifacts, forecast_payload_artifact):
    if name.startswith("snapshot_artifact_"):
        artifact = name.replace("snapshot_artifact_", "", 1)
        return snapshot_optional_artifacts.get(artifact, artifact)
    expected = {
        "forecast_payload_artifact_rate": snapshot_optional_artifacts[forecast_payload_artifact],
        "supplemental_station_validation": "data/backtest/supplemental_station_validation.json",
        "canonical_history_provenance": "data/backtest/canonical_history_guardrails.json",
        "snapshot_low_fill_fields": "data/backtest/data_layer_audit.json",
        "source_status_stale_or_failed_rate": "source_status_long.csv",
        "quarantined_impossible_observations": "source manifest quarantine records",
        "reanalysis_raw_only_days": "normalized reanalysis daily rows",
    }
    return expected.get(name, "data/backtest/data_layer_audit.json")


def build_remediation_manifest(
    gates,
    snapshot,
    historical,
    *,
    low_fill_classifier,
    snapshot_optional_artifacts,
    forecast_payload_artifact,
):
    low_fill = snapshot.get("low_fill_field_classifications") or low_fill_classifier(
        snapshot.get("low_fill_fields") or []
    )
    rows = []
    for gate_row in gates or []:
        status = gate_row.get("status")
        if status not in {"FAIL", "WARN"}:
            continue
        name = gate_row.get("name") or "unknown_gate"
        artifact = name.replace("snapshot_artifact_", "", 1) if name.startswith("snapshot_artifact_") else None
        missing_folders = missing_artifact_folders(snapshot, artifact) if artifact else []
        affected_fields = low_fill if name == "snapshot_low_fill_fields" else []
        supplemental_sources = supplemental_gate_failures(historical) if name == "supplemental_station_validation" else []
        priority = "P0" if status == "FAIL" and gate_row.get("severity") == "fail" else "P1"
        rows.append({
            "id": f"data_layer:{name}",
            "gate": name,
            "status": status,
            "priority": priority,
            "owner": gate_owner(name),
            "evidence": gate_row.get("evidence"),
            "threshold": gate_row.get("threshold"),
            "command": gate_command(name),
            "expected_artifact": expected_artifact(
                name,
                snapshot_optional_artifacts,
                forecast_payload_artifact,
            ),
            "blocks_training": priority == "P0",
            "blocks_broad_promotion": True,
            "affected_folder_count": len(missing_folders),
            "affected_folders": missing_folders[:12],
            "affected_fields": affected_fields[:25],
            "supplemental_sources": supplemental_sources,
            "clearance": (
                "Cleared when the gate returns PASS, or when a waiver row with evidence is committed "
                "and the gate is downgraded intentionally."
            ),
        })
    return rows
