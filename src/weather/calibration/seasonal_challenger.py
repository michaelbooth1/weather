"""Research-only twelve-field seasonal challenger.

This module deliberately has no serving, release, provider, or production-write
entry point.  Its commands are admitted only through ``workstation_heavy.ps1``.
The transfer verifier is fail-closed and never writes below the sealed corpus.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pickle
import re
import stat
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import numpy as np

from weather.calibration.pooled_band_training import (
    normalize_band_probabilities_for_rows,
    train_band_hour_model,
)
from weather.model.variant_prediction_runtime import (
    apply_band_postprocessing,
    predict_band_probabilities,
)


TRANSFER_FAILURE = "TRANSFER_INTEGRITY_FAILURE"
EXPECTED_MANIFEST_SHA256 = (
    "1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a"
)
EXPECTED_BYTES = 171_401_140
EXPECTED_ROWS = 1_645_056
EXPECTED_MARKETS = (
    "atlanta",
    "austin",
    "chicago",
    "dallas",
    "denver",
    "houston",
    "los-angeles",
    "miami",
    "nyc",
    "san-francisco",
    "seattle",
    "toronto",
)
EXPECTED_FIELDS = (
    "temperature_2m",
    "cloud_cover",
    "shortwave_radiation",
    "wind_speed_10m",
    "cape",
    "direct_radiation",
    "diffuse_radiation",
    "wind_gusts_10m",
    "precipitation_probability",
    "precipitation",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)
EXPECTED_LEADS = tuple(range(1, 8))
SEGMENTS = {
    "front": (date(2026, 6, 3), date(2026, 6, 23), 508_032, 42_336),
    "back": (date(2026, 6, 24), date(2026, 8, 9), 1_137_024, 94_752),
}
CSV_HEADER = (
    "market",
    "target_datetime_local",
    "field",
    "lead_days",
    "value",
    "unit",
    "issue_time_basis",
    "source",
)


def _fail(message: str) -> None:
    raise SystemExit(f"{TRANSFER_FAILURE}: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # pragma: no cover - exercised by fail-closed CLI
        _fail(f"cannot read JSON {path}: {type(exc).__name__}: {exc}")
    if not isinstance(value, dict):
        _fail(f"JSON root is not an object: {path}")
    return value


def _safe_payload_path(root: Path, relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        _fail(f"unsafe payload path: {relative_path!r}")
    candidate = (root / Path(relative_path)).resolve(strict=True)
    try:
        candidate.relative_to(root.resolve(strict=True))
    except ValueError:
        _fail(f"payload escapes corpus root: {relative_path!r}")
    if not candidate.is_file():
        _fail(f"payload is not a regular file: {relative_path!r}")
    return candidate


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(os.stat(path), "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _acl_proof(path: Path) -> dict:
    script = (
        "$ErrorActionPreference='Stop';"
        "$acl=Get-Acl -LiteralPath $env:WEATHER_SEASONAL_ACL_PATH;"
        "$rules=@($acl.Access | Where-Object {"
        "$_.IdentityReference.Value -like '*\\CodexSandboxOffline' -and "
        "$_.AccessControlType -eq 'Deny' -and -not $_.IsInherited});"
        "[pscustomobject]@{Owner=$acl.Owner;Rules=@($rules | ForEach-Object {"
        "[pscustomobject]@{Identity=$_.IdentityReference.Value;"
        "Type=$_.AccessControlType.ToString();Inherited=$_.IsInherited;"
        "Rights=$_.FileSystemRights.ToString()}})} | ConvertTo-Json -Depth 5 -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "WEATHER_SEASONAL_ACL_PATH": str(path)},
    )
    if completed.returncode != 0:
        _fail(f"ACL query failed: {completed.stderr.strip()}")
    try:
        proof = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        _fail(f"ACL query returned invalid JSON: {exc}")
    rules = proof.get("Rules") or []
    if isinstance(rules, dict):
        rules = [rules]
    qualifying = []
    for rule in rules:
        rights = {part.strip().casefold() for part in str(rule.get("Rights", "")).split(",")}
        if (
            str(rule.get("Type", "")).casefold() == "deny"
            and rule.get("Inherited") is False
            and "write" in rights
            and "delete" in rights
            and "deletesubdirectoriesandfiles" in rights
        ):
            qualifying.append(rule)
    if not qualifying:
        _fail("explicit CodexSandboxOffline deny Write/Delete ACL is absent")
    return {"owner": proof.get("Owner"), "qualifying_rules": qualifying}


def _csv_contract(
    path: Path,
    *,
    market_id: str,
    start_date: date,
    end_date: date,
) -> dict:
    row_count = 0
    fields: set[str] = set()
    leads: set[int] = set()
    dates: set[date] = set()
    hours_by_key: Counter[tuple[str, int, date]] = Counter()
    units: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_HEADER:
            _fail(f"unexpected CSV header: {path}")
        for row in reader:
            row_count += 1
            if row["market"] != market_id:
                _fail(f"market mismatch at {path}:{row_count + 1}")
            try:
                timestamp = datetime.fromisoformat(row["target_datetime_local"])
                lead = int(row["lead_days"])
                value = float(row["value"])
            except (TypeError, ValueError) as exc:
                _fail(f"invalid CSV value at {path}:{row_count + 1}: {exc}")
            if not math.isfinite(value):
                _fail(f"non-finite value at {path}:{row_count + 1}")
            target_date = timestamp.date()
            if not start_date <= target_date <= end_date:
                _fail(f"date outside segment at {path}:{row_count + 1}")
            if row["issue_time_basis"] != "fixed_lead_day_offset":
                _fail(f"non-PIT issue basis at {path}:{row_count + 1}")
            if row["source"] != "open_meteo_previous_runs":
                _fail(f"non-Previous-Runs source at {path}:{row_count + 1}")
            if not row["unit"]:
                _fail(f"empty unit at {path}:{row_count + 1}")
            fields.add(row["field"])
            leads.add(lead)
            dates.add(target_date)
            units.add(row["unit"])
            hours_by_key[(row["field"], lead, target_date)] += 1
    if fields != set(EXPECTED_FIELDS):
        _fail(f"field set mismatch in {path}")
    if leads != set(EXPECTED_LEADS):
        _fail(f"lead set mismatch in {path}")
    expected_dates = (end_date - start_date).days + 1
    if len(dates) != expected_dates or min(dates) != start_date or max(dates) != end_date:
        _fail(f"date coverage mismatch in {path}")
    expected_keys = expected_dates * len(EXPECTED_FIELDS) * len(EXPECTED_LEADS)
    if len(hours_by_key) != expected_keys or set(hours_by_key.values()) != {24}:
        _fail(f"hourly key coverage is not exactly 24 per field/lead/date in {path}")
    return {
        "rows": row_count,
        "date_count": len(dates),
        "start_date": min(dates).isoformat(),
        "end_date": max(dates).isoformat(),
        "fields": sorted(fields),
        "leads": sorted(leads),
        "units": sorted(units),
        "non_null_rows": row_count,
        "hourly_key_count": len(hours_by_key),
    }


def verify_corpus(corpus_root: Path, expected_manifest_sha256: str) -> dict:
    root = corpus_root.resolve(strict=True)
    if not root.is_dir():
        _fail(f"corpus root is not a directory: {root}")
    if _is_reparse_point(root):
        _fail(f"corpus root is a reparse point: {root}")

    receipt_path = root / "transfer-receipt.json"
    manifest_path = root / "transfer-manifest.json"
    receipt = _load_json(receipt_path)
    manifest = _load_json(manifest_path)
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != expected_manifest_sha256:
        _fail(f"manifest SHA-256 mismatch: {manifest_sha}")
    if expected_manifest_sha256 != EXPECTED_MANIFEST_SHA256:
        _fail("unexpected declared manifest SHA-256")
    expected_receipt = {
        "status": "PASS",
        "destination": str(root),
        "manifest_sha256": expected_manifest_sha256,
        "verified_file_count": 28,
        "verified_bytes": EXPECTED_BYTES,
        "combined_rows": EXPECTED_ROWS,
        "provider_contacted": False,
        "outcomes_read": False,
        "model_fitted": False,
    }
    for key, expected in expected_receipt.items():
        if receipt.get(key) != expected:
            _fail(f"transfer receipt mismatch for {key}: {receipt.get(key)!r}")

    declared = {
        "combined_rows": EXPECTED_ROWS,
        "market_count": len(EXPECTED_MARKETS),
        "field_count": len(EXPECTED_FIELDS),
        "leads": list(EXPECTED_LEADS),
        "required_file_count": 28,
        "total_source_bytes": EXPECTED_BYTES,
    }
    for key, expected in declared.items():
        if manifest.get(key) != expected:
            _fail(f"transfer manifest mismatch for {key}: {manifest.get(key)!r}")

    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 28:
        _fail("transfer manifest must declare exactly 28 payload files")
    relative_paths = [str(item.get("relative_path") or "") for item in files]
    if len(set(relative_paths)) != 28:
        _fail("transfer manifest has duplicate payload paths")
    before = {}
    verified_files = []
    total_bytes = 0
    for item in files:
        relative_path = str(item.get("relative_path") or "")
        path = _safe_payload_path(root, relative_path)
        file_stat = path.stat()
        before[relative_path] = (file_stat.st_size, file_stat.st_mtime_ns)
        actual_sha = sha256_file(path)
        if file_stat.st_size != int(item.get("bytes", -1)):
            _fail(f"payload byte mismatch: {relative_path}")
        if actual_sha != item.get("sha256"):
            _fail(f"payload SHA-256 mismatch: {relative_path}")
        total_bytes += file_stat.st_size
        verified_files.append(
            {"relative_path": relative_path, "bytes": file_stat.st_size, "sha256": actual_sha}
        )
    if total_bytes != EXPECTED_BYTES:
        _fail(f"verified byte total mismatch: {total_bytes}")

    csv_results = []
    combined_rows = 0
    for segment_name, (start_date, end_date, segment_rows, market_rows) in SEGMENTS.items():
        declared_segment = manifest.get("segments", {}).get(segment_name, {})
        if declared_segment != {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "rows": segment_rows,
        }:
            _fail(f"transfer segment declaration mismatch: {segment_name}")
        original_path = root / segment_name / "manifest.json"
        original = _load_json(original_path)
        if original.get("start_date") != start_date.isoformat() or original.get("end_date") != end_date.isoformat():
            _fail(f"original manifest date mismatch: {segment_name}")
        if tuple(original.get("fields") or ()) != EXPECTED_FIELDS:
            _fail(f"original manifest field order mismatch: {segment_name}")
        if tuple(original.get("leads") or ()) != EXPECTED_LEADS:
            _fail(f"original manifest lead mismatch: {segment_name}")
        if original.get("source") != "open_meteo_previous_runs":
            _fail(f"original manifest source mismatch: {segment_name}")
        if original.get("issue_time_basis") != "fixed_lead_day_offset":
            _fail(f"original manifest issue basis mismatch: {segment_name}")
        if original.get("stitched_source_used") is not False:
            _fail(f"stitched source declared in original manifest: {segment_name}")
        markets = original.get("markets") or {}
        if set(markets) != set(EXPECTED_MARKETS):
            _fail(f"original manifest market set mismatch: {segment_name}")
        actual_segment_rows = 0
        for market_id in EXPECTED_MARKETS:
            entry = markets[market_id]
            if (
                entry.get("status") != 200
                or entry.get("rows") != market_rows
                or entry.get("non_null") != market_rows
                or float(entry.get("coverage_pct", -1)) != 100.0
            ):
                _fail(f"original manifest coverage mismatch: {segment_name}/{market_id}")
            csv_path = _safe_payload_path(root, f"{segment_name}/{entry.get('file')}")
            csv_sha = sha256_file(csv_path)
            if csv_sha != entry.get("sha256"):
                _fail(f"original manifest CSV SHA-256 mismatch: {segment_name}/{market_id}")
            result = _csv_contract(
                csv_path,
                market_id=market_id,
                start_date=start_date,
                end_date=end_date,
            )
            if result["rows"] != market_rows:
                _fail(f"CSV row count mismatch: {segment_name}/{market_id}")
            result.update({"segment": segment_name, "market_id": market_id, "sha256": csv_sha})
            csv_results.append(result)
            actual_segment_rows += result["rows"]
        if actual_segment_rows != segment_rows:
            _fail(f"segment row total mismatch: {segment_name}")
        combined_rows += actual_segment_rows
    if combined_rows != EXPECTED_ROWS:
        _fail(f"combined row total mismatch: {combined_rows}")

    after = {
        relative_path: (_safe_payload_path(root, relative_path).stat().st_size, _safe_payload_path(root, relative_path).stat().st_mtime_ns)
        for relative_path in relative_paths
    }
    if before != after:
        _fail("a transferred payload changed during verification")
    acl = _acl_proof(root)
    free_bytes = os.statvfs(root).f_bavail * os.statvfs(root).f_frsize if hasattr(os, "statvfs") else None
    if os.name == "nt":
        import shutil

        free_bytes = shutil.disk_usage(root).free
    result = {
        "integrity_version": "pit_12field_p0_integrity_v1",
        "status": "PASS",
        "destination": str(root),
        "transfer_receipt_sha256": sha256_file(receipt_path),
        "transfer_manifest_sha256": manifest_sha,
        "original_manifest_sha256": {
            segment: sha256_file(root / segment / "manifest.json") for segment in SEGMENTS
        },
        "verified_file_count": len(verified_files),
        "verified_bytes": total_bytes,
        "verified_csv_count": len(csv_results),
        "declared_rows": combined_rows,
        "market_count": len(EXPECTED_MARKETS),
        "field_count": len(EXPECTED_FIELDS),
        "leads": list(EXPECTED_LEADS),
        "segments": {
            name: {
                "start_date": values[0].isoformat(),
                "end_date": values[1].isoformat(),
                "rows": values[2],
            }
            for name, values in SEGMENTS.items()
        },
        "source": "open_meteo_previous_runs",
        "issue_time_basis": "fixed_lead_day_offset",
        "stitched_source_used": False,
        "non_null_coverage_pct": 100.0,
        "destination_reparse_point": False,
        "acl": acl,
        "available_disk_bytes": free_bytes,
        "payloads_unchanged_during_verification": True,
        "payload_inventory_sha256": canonical_sha256(verified_files),
        "csv_contract_sha256": canonical_sha256(csv_results),
    }
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _inventory_hash(paths: list[Path], root: Path) -> tuple[list[dict], str]:
    inventory = []
    for path in sorted(paths, key=lambda item: str(item).casefold()):
        resolved = path.resolve(strict=True)
        inventory.append(
            {
                "relative_path": resolved.relative_to(root.resolve(strict=True)).as_posix(),
                "bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
    return inventory, canonical_sha256(inventory)


def freeze_design(
    *,
    corpus_root: Path,
    p0_receipt: Path,
    retained_rows: Path,
    mirror_root: Path,
) -> dict:
    p0 = _load_json(p0_receipt)
    if p0.get("status") != "PASS" or p0.get("transfer_manifest_sha256") != EXPECTED_MANIFEST_SHA256:
        _fail("P0 PASS receipt is absent or bound to the wrong transfer manifest")
    retained_sha = sha256_file(retained_rows)
    expected_retained_sha = "9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae"
    if retained_sha != expected_retained_sha:
        _fail(f"retained repaired-surface SHA-256 mismatch: {retained_sha}")
    mirror = mirror_root.resolve(strict=True)
    if _is_reparse_point(mirror):
        _fail("frozen mirror root is a reparse point")
    mirror_acl = _acl_proof(mirror)
    source_paths = [
        path
        for path in (mirror / "snapshots").iterdir()
        if path.is_dir()
        for path in (path / "snapshots_long.csv", path / "replay_inputs.jsonl")
        if path.exists()
        and any(marker in path.parent.name for marker in ("july-31-2026", "august-1-2026", "august-2-2026", "august-3-2026", "august-4-2026", "august-5-2026", "august-6-2026", "august-7-2026", "august-8-2026", "august-9-2026"))
    ]
    source_paths.extend(
        mirror / "settlements" / market / "ledger.jsonl" for market in EXPECTED_MARKETS
    )
    inventory, inventory_sha = _inventory_hash(source_paths, mirror)
    design = {
        "design_version": "seasonal_challenger_12field_v1",
        "status": "FROZEN_BEFORE_C_OUTCOMES",
        "purpose": "Research-only baseline-versus-twelve-field seasonal challenger.",
        "input_binding": {
            "corpus_root": str(corpus_root.resolve(strict=True)),
            "p0_receipt_sha256": sha256_file(p0_receipt),
            "transfer_manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "retained_repaired_surface": str(retained_rows.resolve(strict=True)),
            "retained_repaired_surface_sha256": retained_sha,
            "frozen_mirror_root": str(mirror),
            "frozen_mirror_reparse_point": False,
            "frozen_mirror_acl": mirror_acl,
            "post_boundary_source_inventory": inventory,
            "post_boundary_source_inventory_sha256": inventory_sha,
        },
        "cohorts": {
            "fit_B": {
                "source": "retained repaired surface",
                "selection": "stratum == in-season; promotion-countable rows only",
                "expected": {"date_clusters": 23, "markets": 12, "market_days": 204, "snapshots": 4636, "band_rows": 50996},
            },
            "C_pre": {
                "source": "retained repaired surface",
                "selection": "stratum == out-of-season; target_date <= 2026-07-30; promotion-countable rows only",
                "expected": {"date_clusters": 27, "markets": 12, "market_days": 320, "snapshots": 7653, "band_rows": 84183},
            },
            "C_post": {
                "source": "frozen workstation mirror only",
                "selection": "promotion_countable latest ledger label; target dates 2026-07-31 through 2026-08-09; target-day snapshots; cutoff hours 07-20; complete band partition with finite incumbent and market probabilities",
                "report_separately": True,
            },
            "provenance_boundary": {"anchor_commit": "b77cfbed", "date": "2026-07-31", "pooling_permitted": False},
        },
        "forecast_features": {
            "fields_in_order": list(EXPECTED_FIELDS),
            "primary_leads": list(EXPECTED_LEADS),
            "sensitivity_leads": list(range(2, 8)),
            "valid_local_hours_inclusive": [7, 20],
            "daily_aggregation": {
                "temperature_2m": "max",
                "cloud_cover": "mean",
                "shortwave_radiation": "sum",
                "wind_speed_10m": "mean",
                "cape": "max",
                "direct_radiation": "sum",
                "diffuse_radiation": "sum",
                "wind_gusts_10m": "max",
                "precipitation_probability": "max",
                "precipitation": "sum",
                "vapour_pressure_deficit": "max",
                "et0_fao_evapotranspiration": "sum",
            },
            "across_lead_aggregation": "arithmetic mean of each field's daily aggregate",
            "baseline_fields": ["temperature_2m"],
            "challenger_fields": list(EXPECTED_FIELDS),
            "provider_availability_limit": "Research evidence only; historical first-availability timestamps are insufficient for production qualification.",
        },
        "model": {
            "architecture": "repository pooled band HistGradientBoostingClassifier, one model per effective cutoff hour",
            "estimator": {"max_iter": 90, "max_leaf_nodes": 31, "learning_rate": 0.05, "random_state": 42},
            "imputer": {"strategy": "median", "keep_empty_features": True},
            "weights": "equal total weight per admitted market-day within cutoff-hour fit",
            "target": "one-hot realized band on B only",
            "hyperparameter_search": False,
            "common_features_in_order": ["band_value", "band_value_hi", "band_width", "band_mid", "band_mid_minus_forecast", "market_id one-hot", "band_kind one-hot"],
            "forecast_feature_column_order": {
                "temperature_2m": "forecast_high",
                "cloud_cover": "forecast_total_cloud_mean",
                "shortwave_radiation": "forecast_remaining_solar_sum",
                "wind_speed_10m": "wind_speed_kmh",
                "cape": "forecast_next_3h_cape_max",
                "direct_radiation": "forecast_remaining_direct_radiation_sum",
                "diffuse_radiation": "forecast_remaining_diffuse_radiation_sum",
                "wind_gusts_10m": "forecast_wind_gust_max",
                "precipitation_probability": "forecast_next_3h_precipitation_probability_max",
                "precipitation": "forecast_remaining_precipitation_sum",
                "vapour_pressure_deficit": "forecast_vapour_pressure_deficit_mean",
                "et0_fao_evapotranspiration": "forecast_et0_fao_evapotranspiration_sum",
            },
        },
        "probability_pipeline": {
            "temperature": 1.0,
            "postprocessing": {"support_floor_enabled": False, "late_lockin_enabled": False, "adjacent_calibration_enabled": False, "exact_winner_catchup_enabled": False, "forecast_centering_enabled": False, "market_bias_calibration_enabled": False},
            "normalization_gamma": 1.25,
            "incumbent_zero_support_preserved": True,
            "simplex_tolerance": 1e-12,
        },
        "evaluation": {
            "centre": "probability-weighted native band centre; lte tail=value-1, gte tail=value+1, closed interval midpoint otherwise",
            "signed_centre_error": "predicted centre minus settlement bucket",
            "centre_mae": "mean absolute signed centre error by snapshot",
            "centre_sse": "mean squared signed centre error by snapshot",
            "brier": "mean squared probability error over matched band rows",
            "severe_tail": "C rows frozen where incumbent squared error exceeds market squared error and abs(incumbent-market)>=0.30",
            "modal_hit": "fraction of snapshots whose maximum-probability band contains settlement",
            "market_benchmark_use": "evaluation only, loaded after design freeze",
        },
        "inference": {
            "method": "shared-weight crossed target-date by market pigeonhole bootstrap over fixed matched evaluation effects",
            "draws": 20000,
            "seed": 8602026,
            "interval": "percentile 95%",
            "power": "two-sided normal plug-in at alpha 0.05",
            "mde_80": "(z_0.975 + z_0.8) * crossed bootstrap standard error",
        },
        "decision_rule": {
            "accept": "GO_TO_SECOND_RESEARCH_REPLICATION only when all six commissioned C-pre conditions pass",
            "conditions": [
                "centre SSE improvement > 0 and crossed 95% interval excludes zero",
                "challenger-minus-baseline Brier <= 0 and crossed 95% upper <= +0.002",
                "lead-2-7 sensitivity centre SSE improvement > 0",
                "probability mass and captured-input parity pass exactly",
                "maximum one-market contribution <= 0.35 of total measured centre SSE improvement",
                "no C outcome, market price, or settlement-derived model input",
            ],
            "otherwise": "NO_GO if harm is established; INCONCLUSIVE_UNDERPOWERED when the centre interval crosses zero",
        },
        "prohibited_actions": ["provider call", "production write", "Scheduler access", "exchange access", "credential access", "release", "pointer", "promotion", "candidate freeze", "confirmation window", "serving change"],
    }
    design["design_sha256"] = canonical_sha256(design)
    return design


FIELD_TO_COLUMN = {
    "temperature_2m": "forecast_high",
    "cloud_cover": "forecast_total_cloud_mean",
    "shortwave_radiation": "forecast_remaining_solar_sum",
    "wind_speed_10m": "wind_speed_kmh",
    "cape": "forecast_next_3h_cape_max",
    "direct_radiation": "forecast_remaining_direct_radiation_sum",
    "diffuse_radiation": "forecast_remaining_diffuse_radiation_sum",
    "wind_gusts_10m": "forecast_wind_gust_max",
    "precipitation_probability": "forecast_next_3h_precipitation_probability_max",
    "precipitation": "forecast_remaining_precipitation_sum",
    "vapour_pressure_deficit": "forecast_vapour_pressure_deficit_mean",
    "et0_fao_evapotranspiration": "forecast_et0_fao_evapotranspiration_sum",
}
AGGREGATION = {
    "temperature_2m": "max",
    "cloud_cover": "mean",
    "shortwave_radiation": "sum",
    "wind_speed_10m": "mean",
    "cape": "max",
    "direct_radiation": "sum",
    "diffuse_radiation": "sum",
    "wind_gusts_10m": "max",
    "precipitation_probability": "max",
    "precipitation": "sum",
    "vapour_pressure_deficit": "max",
    "et0_fao_evapotranspiration": "sum",
}
POSTPROCESS = {
    "support_floor_enabled": False,
    "late_lockin_enabled": False,
    "adjacent_calibration_enabled": False,
    "exact_winner_catchup_enabled": False,
    "forecast_centering_enabled": False,
    "market_bias_calibration_enabled": False,
}
COMMON_FEATURES = (
    "band_value",
    "band_value_hi",
    "band_width",
    "band_mid",
    "band_mid_minus_forecast",
)
MARKET_FEATURES = tuple(f"market_id_{market}" for market in EXPECTED_MARKETS)
BAND_KIND_FEATURES = ("band_kind_eq", "band_kind_gte", "band_kind_lte")


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} is not numeric: {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite")
    return number


def _date_from_slug(slug: str) -> date | None:
    marker = "-on-"
    if marker not in slug:
        return None
    raw = slug.rsplit(marker, 1)[1]
    for fmt in ("%B-%d-%Y", "%b-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _market_from_slug(slug: str) -> str | None:
    for market_id in sorted(EXPECTED_MARKETS, key=len, reverse=True):
        if slug.startswith(f"highest-temperature-in-{market_id}-on-"):
            return market_id
    return None


def _validate_design(design_path: Path) -> dict:
    design = _load_json(design_path)
    declared = design.get("design_sha256")
    unsigned = dict(design)
    unsigned.pop("design_sha256", None)
    actual = canonical_sha256(unsigned)
    if declared != actual:
        raise SystemExit(f"DESIGN_INTEGRITY_FAILURE: canonical hash {actual}")
    if design.get("status") != "FROZEN_BEFORE_C_OUTCOMES":
        raise SystemExit("DESIGN_INTEGRITY_FAILURE: design is not frozen")
    binding = design.get("input_binding") or {}
    retained = Path(binding["retained_repaired_surface"])
    if sha256_file(retained) != binding.get("retained_repaired_surface_sha256"):
        raise SystemExit("DESIGN_INTEGRITY_FAILURE: retained surface drift")
    mirror = Path(binding["frozen_mirror_root"])
    current = []
    for entry in binding.get("post_boundary_source_inventory") or []:
        path = (mirror / entry["relative_path"]).resolve(strict=True)
        current.append(
            {
                "relative_path": entry["relative_path"],
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if canonical_sha256(current) != binding.get("post_boundary_source_inventory_sha256"):
        raise SystemExit("DESIGN_INTEGRITY_FAILURE: post-boundary source inventory drift")
    return design


def load_forecast_features(corpus_root: Path) -> tuple[dict, dict]:
    """Load the frozen PIT corpus into daily, per-lead field aggregates."""
    daily_values: dict[tuple[str, str, int, str], list[float]] = defaultdict(list)
    units: dict[tuple[str, str], set[str]] = defaultdict(set)
    admitted_rows = 0
    for segment in SEGMENTS:
        manifest = _load_json(corpus_root / segment / "manifest.json")
        for market_id in EXPECTED_MARKETS:
            path = corpus_root / segment / manifest["markets"][market_id]["file"]
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for line_number, row in enumerate(csv.DictReader(handle), start=2):
                    timestamp = datetime.fromisoformat(row["target_datetime_local"])
                    if not 7 <= timestamp.hour <= 20:
                        continue
                    field = row["field"]
                    lead = int(row["lead_days"])
                    value = _finite(row["value"], f"{path}:{line_number}")
                    key = (market_id, timestamp.date().isoformat(), lead, field)
                    daily_values[key].append(value)
                    units[(market_id, field)].add(row["unit"])
                    admitted_rows += 1
    daily = {}
    for key, values in daily_values.items():
        if len(values) != 14:
            raise SystemExit(f"FORECAST_FEATURE_FAILURE: expected 14 valid hours for {key}")
        mode = AGGREGATION[key[3]]
        if mode == "max":
            aggregate = max(values)
        elif mode == "sum":
            aggregate = sum(values)
        else:
            aggregate = sum(values) / len(values)
        daily[key] = aggregate
    expected = len(EXPECTED_MARKETS) * 68 * len(EXPECTED_LEADS) * len(EXPECTED_FIELDS)
    if len(daily) != expected:
        raise SystemExit(f"FORECAST_FEATURE_FAILURE: daily aggregate count {len(daily)} != {expected}")
    metadata = {
        "valid_hour_rows": admitted_rows,
        "daily_lead_field_aggregates": len(daily),
        "unit_sets": {f"{market}|{field}": sorted(values) for (market, field), values in sorted(units.items())},
        "aggregate_sha256": canonical_sha256(
            [{"key": list(key), "value": daily[key]} for key in sorted(daily)]
        ),
    }
    return daily, metadata


def feature_surface(
    daily: dict,
    *,
    market_id: str,
    target_date: str,
    leads: tuple[int, ...],
) -> dict[str, float]:
    output = {}
    for field in EXPECTED_FIELDS:
        values = [daily[(market_id, target_date, lead, field)] for lead in leads]
        output[FIELD_TO_COLUMN[field]] = sum(values) / len(values)
    return output


def _band_mid(kind: str, value: float, value_hi: float) -> float:
    if kind == "lte":
        return value - 1.0
    if kind == "gte":
        return value + 1.0
    return (value + value_hi) / 2.0


def _band_value_hi(kind: str, value: float, raw_value_hi: object, range_label: str) -> float:
    if raw_value_hi not in (None, ""):
        return _finite(raw_value_hi, "band_value_hi")
    if kind == "eq":
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)", range_label)
        if match:
            return float(match.group(2))
    return value


def _band_record(
    *,
    market_id: str,
    target_date: str,
    cutoff_hour: int,
    band_index: int,
    range_label: str,
    kind: str,
    value: float,
    value_hi: float,
    outcome: int,
    incumbent: float,
    market: float | None,
) -> dict:
    mid = _band_mid(kind, value, value_hi)
    return {
        "market_id": market_id,
        "target_date": target_date,
        "cutoff_hour": cutoff_hour,
        "band_index": band_index,
        "range_label": range_label,
        "band_kind": kind,
        "band_value": value,
        "band_value_hi": value_hi,
        "band_width": value_hi - value,
        "band_mid": mid,
        "outcome": int(outcome),
        "incumbent_probability": incumbent,
        "market_probability": market,
    }


def load_settlement_index(mirror_root: Path) -> dict[tuple[str, str], int]:
    latest = {}
    for market_id in EXPECTED_MARKETS:
        path = mirror_root / "settlements" / market_id / "ledger.jsonl"
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                target_date = str(row.get("target_date") or "")
                if row.get("market_id") == market_id and target_date:
                    latest[(market_id, target_date)] = row
    return {
        key: int(float(row["settlement_bucket"]))
        for key, row in latest.items()
        if row.get("promotion_countable") is True and row.get("settlement_bucket") is not None
    }


def load_retained_groups(path: Path, settlement_index: dict[tuple[str, str], int]) -> tuple[list[dict], list[dict]]:
    groups: dict[str, dict] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "snapshot_id", "record_hash", "target_date", "stratum", "market_id",
            "effective_cutoff_hour", "band_index", "range_label", "bin_kind",
            "bin_value", "bin_value_hi", "outcome", "served_replay_probability",
            "market_probability",
        }
        if not required.issubset(reader.fieldnames or []):
            raise SystemExit("EVALUATION_INPUT_FAILURE: retained row schema mismatch")
        for line_number, raw in enumerate(reader, start=2):
            source_snapshot_id = raw["snapshot_id"]
            snapshot_id = "|".join(
                (
                    raw["market_id"],
                    raw["target_date"],
                    source_snapshot_id,
                    raw["record_hash"],
                )
            )
            group = groups.setdefault(
                snapshot_id,
                {
                    "snapshot_id": snapshot_id,
                    "source_snapshot_id": source_snapshot_id,
                    "target_date": raw["target_date"],
                    "stratum": raw["stratum"],
                    "market_id": raw["market_id"],
                    "cutoff_hour": int(raw["effective_cutoff_hour"]),
                    "rows": [],
                    "source": "retained_pre_boundary",
                },
            )
            invariant = (raw["target_date"], raw["stratum"], raw["market_id"], int(raw["effective_cutoff_hour"]))
            if invariant != (group["target_date"], group["stratum"], group["market_id"], group["cutoff_hour"]):
                raise SystemExit(f"EVALUATION_INPUT_FAILURE: snapshot invariant mismatch at line {line_number}")
            value = _finite(raw["bin_value"], "bin_value")
            value_hi = _band_value_hi(
                raw["bin_kind"], value, raw["bin_value_hi"], raw["range_label"]
            )
            group["rows"].append(
                _band_record(
                    market_id=group["market_id"],
                    target_date=group["target_date"],
                    cutoff_hour=group["cutoff_hour"],
                    band_index=int(raw["band_index"]),
                    range_label=raw["range_label"],
                    kind=raw["bin_kind"],
                    value=value,
                    value_hi=value_hi,
                    outcome=int(raw["outcome"]),
                    incumbent=_finite(raw["served_replay_probability"], "served_replay_probability"),
                    market=_finite(raw["market_probability"], "market_probability"),
                )
            )
    fit_b = [group for group in groups.values() if group["stratum"] == "B"]
    c_pre = [
        group for group in groups.values()
        if group["stratum"] == "C" and group["target_date"] <= "2026-07-30"
    ]
    for group in [*fit_b, *c_pre]:
        key = (group["market_id"], group["target_date"])
        if key not in settlement_index:
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: no promotion-countable settlement for {key}")
        group["settlement_bucket"] = settlement_index[key]
        for row in group["rows"]:
            expected_outcome = int(
                group["settlement_bucket"] <= row["band_value"] if row["band_kind"] == "lte"
                else group["settlement_bucket"] >= row["band_value"] if row["band_kind"] == "gte"
                else row["band_value"] <= group["settlement_bucket"] <= row["band_value_hi"]
            )
            if row["outcome"] != expected_outcome:
                raise SystemExit(f"EVALUATION_INPUT_FAILURE: retained outcome/ledger mismatch for {key}")
    _validate_group_population(
        fit_b,
        expected={"dates": 23, "markets": 12, "market_days": 204, "snapshots": 4636, "rows": 50996},
        label="B",
    )
    _validate_group_population(
        c_pre,
        expected={"dates": 27, "markets": 12, "market_days": 320, "snapshots": 7653, "rows": 84183},
        label="C-pre",
    )
    return sorted(fit_b, key=_group_key), sorted(c_pre, key=_group_key)


def _group_key(group: dict) -> tuple:
    return (group["target_date"], group["market_id"], group["cutoff_hour"], group["snapshot_id"])


def _validate_group_population(groups: list[dict], *, expected: dict | None, label: str) -> dict:
    dates = {group["target_date"] for group in groups}
    markets = {group["market_id"] for group in groups}
    market_days = {(group["target_date"], group["market_id"]) for group in groups}
    band_rows = 0
    for group in groups:
        rows = sorted(group["rows"], key=lambda row: row["band_index"])
        group["rows"] = rows
        if len(rows) != 11 or sum(row["outcome"] for row in rows) != 1:
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: {label} incomplete/invalid partition {group['snapshot_id']}")
        if abs(sum(row["incumbent_probability"] for row in rows) - 1.0) > 1e-6:
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: {label} incumbent mass {group['snapshot_id']}")
        if any(row["market_probability"] is None for row in rows):
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: {label} market probability missing")
        market_mass = sum(row["market_probability"] for row in rows)
        if market_mass <= 0.0:
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: {label} market mass {group['snapshot_id']}")
        for row in rows:
            row["market_probability"] /= market_mass
        if abs(sum(row["market_probability"] for row in rows) - 1.0) > 1e-12:
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: {label} normalized market mass {group['snapshot_id']}")
        band_rows += len(rows)
    support = {
        "date_clusters": len(dates),
        "market_clusters": len(markets),
        "market_days": len(market_days),
        "snapshot_cutoff_rows": len(groups),
        "band_rows": band_rows,
        "effective_cluster_cells": len(market_days),
    }
    if expected:
        actual = {
            "dates": len(dates), "markets": len(markets), "market_days": len(market_days),
            "snapshots": len(groups), "rows": band_rows,
        }
        if actual != expected:
            raise SystemExit(f"EVALUATION_INPUT_FAILURE: {label} support {actual} != {expected}")
    return support


def _latest_post_labels(mirror_root: Path) -> tuple[dict[str, dict], dict]:
    latest = {}
    inspected = 0
    for market_id in EXPECTED_MARKETS:
        path = mirror_root / "settlements" / market_id / "ledger.jsonl"
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                inspected += 1
                if not line.strip():
                    continue
                row = json.loads(line)
                target = str(row.get("target_date") or "")
                if "2026-07-31" <= target <= "2026-08-09":
                    latest[str(row.get("event_slug") or "")] = row
    admitted = {
        slug: row for slug, row in latest.items()
        if row.get("promotion_countable") is True and row.get("settlement_bucket") is not None
    }
    return admitted, {"ledger_rows_inspected": inspected, "latest_labels": len(latest), "admitted_labels": len(admitted)}


def load_post_groups(mirror_root: Path) -> tuple[list[dict], dict]:
    labels, label_meta = _latest_post_labels(mirror_root)
    groups = []
    exclusions = Counter()
    snapshot_root = mirror_root / "snapshots"
    for folder in sorted(snapshot_root.iterdir(), key=lambda path: path.name):
        if not folder.is_dir():
            continue
        slug = folder.name
        target_date = _date_from_slug(slug)
        market_id = _market_from_slug(slug)
        if target_date is None or market_id is None or not date(2026, 7, 31) <= target_date <= date(2026, 8, 9):
            continue
        label = labels.get(slug)
        if label is None:
            exclusions["market_day_without_promotion_countable_label"] += 1
            continue
        tape = folder / "snapshots_long.csv"
        if not tape.exists():
            exclusions["market_day_without_tape"] += 1
            continue
        raw_groups: dict[str, list[dict]] = defaultdict(list)
        with tape.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            needed = {
                "snapshot_id", "captured_at_local", "event_slug", "range_label",
                "bin_kind", "bin_value_c", "bin_value_hi_c", "model_probability", "market_yes",
            }
            if not needed.issubset(reader.fieldnames or []):
                exclusions["market_day_schema_mismatch"] += 1
                continue
            for raw in reader:
                raw_groups[raw["snapshot_id"]].append(raw)
        for snapshot_id, raw_rows in raw_groups.items():
            try:
                captured = datetime.fromisoformat(raw_rows[0]["captured_at_local"])
            except ValueError:
                exclusions["snapshot_invalid_local_timestamp"] += 1
                continue
            if captured.date() != target_date:
                exclusions["snapshot_not_target_day"] += 1
                continue
            if not 7 <= captured.hour <= 20:
                exclusions["snapshot_outside_cutoff_hours"] += 1
                continue
            if len(raw_rows) != int(label.get("band_count") or 0):
                exclusions["snapshot_incomplete_band_partition"] += 1
                continue
            try:
                incumbents = [_finite(row["model_probability"], "model_probability") for row in raw_rows]
                market_raw = [_finite(row["market_yes"], "market_yes") for row in raw_rows]
            except ValueError:
                exclusions["snapshot_nonfinite_probability"] += 1
                continue
            if min(incumbents + market_raw) < 0 or max(incumbents + market_raw) > 1:
                exclusions["snapshot_probability_out_of_range"] += 1
                continue
            incumbent_mass = sum(incumbents)
            market_mass = sum(market_raw)
            if incumbent_mass <= 0 or market_mass <= 0:
                exclusions["snapshot_zero_probability_mass"] += 1
                continue
            incumbents = [value / incumbent_mass for value in incumbents]
            markets = [value / market_mass for value in market_raw]
            settlement = int(float(label["settlement_bucket"]))
            rows = []
            for band_index, (raw, incumbent, market_probability) in enumerate(zip(raw_rows, incumbents, markets)):
                value = _finite(raw["bin_value_c"], "bin_value_c")
                value_hi = _band_value_hi(
                    raw["bin_kind"], value, raw["bin_value_hi_c"], raw["range_label"]
                )
                kind = raw["bin_kind"]
                outcome = int(
                    settlement <= value if kind == "lte"
                    else settlement >= value if kind == "gte"
                    else value <= settlement <= value_hi
                )
                rows.append(
                    _band_record(
                        market_id=market_id,
                        target_date=target_date.isoformat(),
                        cutoff_hour=captured.hour,
                        band_index=band_index,
                        range_label=raw["range_label"],
                        kind=kind,
                        value=value,
                        value_hi=value_hi,
                        outcome=outcome,
                        incumbent=incumbent,
                        market=market_probability,
                    )
                )
            if sum(row["outcome"] for row in rows) != 1:
                exclusions["snapshot_settlement_outside_partition"] += 1
                continue
            canonical_snapshot_id = "|".join(
                (market_id, target_date.isoformat(), snapshot_id)
            )
            groups.append(
                {
                    "snapshot_id": canonical_snapshot_id,
                    "source_snapshot_id": snapshot_id,
                    "target_date": target_date.isoformat(),
                    "stratum": "out-of-season-post-boundary",
                    "market_id": market_id,
                    "cutoff_hour": captured.hour,
                    "rows": rows,
                    "settlement_bucket": settlement,
                    "source": "frozen_post_boundary_mirror",
                }
            )
    groups.sort(key=_group_key)
    support = _validate_group_population(groups, expected=None, label="C-post")
    metadata = {**label_meta, "exclusions": dict(sorted(exclusions.items())), "support": support}
    return groups, metadata


def _feature_names(fields: tuple[str, ...]) -> list[str]:
    return [FIELD_TO_COLUMN[field] for field in fields] + list(COMMON_FEATURES) + list(MARKET_FEATURES) + list(BAND_KIND_FEATURES)


def _decorate_groups(groups: list[dict], daily: dict, *, leads: tuple[int, ...], fields: tuple[str, ...]) -> list[dict]:
    decorated = []
    for group in groups:
        surface = feature_surface(
            daily,
            market_id=group["market_id"],
            target_date=group["target_date"],
            leads=leads,
        )
        rows = []
        for source in group["rows"]:
            row = dict(source)
            for field in fields:
                row[FIELD_TO_COLUMN[field]] = surface[FIELD_TO_COLUMN[field]]
            row["band_mid_minus_forecast"] = row["band_mid"] - surface["forecast_high"]
            rows.append(row)
        copy = dict(group)
        copy["rows"] = rows
        decorated.append(copy)
    return decorated


def _training_rows(groups: list[dict]) -> dict[int, list[dict]]:
    by_hour: dict[int, list[dict]] = defaultdict(list)
    counts = Counter()
    for group in groups:
        cell = (group["cutoff_hour"], group["target_date"], group["market_id"])
        counts[cell] += len(group["rows"])
    for group in groups:
        cell = (group["cutoff_hour"], group["target_date"], group["market_id"])
        for source in group["rows"]:
            row = dict(source)
            row["_sample_weight"] = 1.0 / counts[cell]
            by_hour[group["cutoff_hour"]].append(row)
    return dict(by_hour)


def _pickle_hash(value: object) -> tuple[bytes, str]:
    payload = pickle.dumps(value, protocol=5)
    return payload, hashlib.sha256(payload).hexdigest()


def fit_variant(
    groups: list[dict],
    *,
    daily: dict,
    leads: tuple[int, ...],
    fields: tuple[str, ...],
    artifact_root: Path,
    variant_id: str,
    write_artifacts: bool,
) -> tuple[dict, dict]:
    decorated = _decorate_groups(groups, daily, leads=leads, fields=fields)
    by_hour = _training_rows(decorated)
    names = _feature_names(fields)
    bundles = {}
    hashes = {}
    metrics = {}
    for hour in sorted(by_hour):
        model, imputer, trained_names, train_metrics = train_band_hour_model(
            by_hour[hour],
            feature_names=names,
        )
        if trained_names != names:
            raise SystemExit(f"MODEL_PARITY_FAILURE: feature order changed for {variant_id}/{hour}")
        payload, digest = _pickle_hash((model, imputer, trained_names))
        bundles[hour] = (model, imputer, trained_names)
        hashes[str(hour)] = digest
        metrics[str(hour)] = {
            "band_rows": len(by_hour[hour]),
            "market_days": len({(row["target_date"], row["market_id"]) for row in by_hour[hour]}),
            "matrix_rows": train_metrics["matrix_rows"],
            "matrix_columns": train_metrics["matrix_columns"],
        }
        if write_artifacts:
            target = artifact_root / variant_id / f"cutoff-{hour:02d}.pickle"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
    summary = {
        "variant_id": variant_id,
        "leads": list(leads),
        "fields": list(fields),
        "feature_names": names,
        "cutoff_model_sha256": hashes,
        "aggregate_model_sha256": canonical_sha256(hashes),
        "training": metrics,
    }
    return bundles, summary


def _predict_group(bundle: tuple, rows: list[dict]) -> list[float]:
    model, imputer, names = bundle
    raw = predict_band_probabilities(model, imputer, names, rows, temperature=1.0)
    processed = [apply_band_postprocessing(value, row, config=POSTPROCESS) for row, value in zip(rows, raw)]
    admitted_indexes = [index for index, row in enumerate(rows) if row["incumbent_probability"] > 0.0]
    if not admitted_indexes:
        raise SystemExit("PROBABILITY_PARITY_FAILURE: incumbent has zero total support")
    admitted_rows = [rows[index] for index in admitted_indexes]
    admitted_probabilities = [processed[index] for index in admitted_indexes]
    normalized = normalize_band_probabilities_for_rows(admitted_rows, admitted_probabilities, gamma=1.25)
    output = [0.0] * len(rows)
    for index, probability in zip(admitted_indexes, normalized):
        output[index] = float(probability)
    if abs(sum(output) - 1.0) > 1e-12:
        raise SystemExit("PROBABILITY_PARITY_FAILURE: candidate mass is invalid")
    if any(output[index] != 0.0 for index, row in enumerate(rows) if row["incumbent_probability"] == 0.0):
        raise SystemExit("PROBABILITY_PARITY_FAILURE: incumbent zero support was populated")
    return output


def predict_variant(groups: list[dict], bundles: dict, *, daily: dict, leads: tuple[int, ...], fields: tuple[str, ...]) -> dict[str, list[float]]:
    decorated = _decorate_groups(groups, daily, leads=leads, fields=fields)
    output = {}
    for group in decorated:
        if group["cutoff_hour"] not in bundles:
            raise SystemExit(f"MODEL_PARITY_FAILURE: no B model for cutoff {group['cutoff_hour']}")
        output[group["snapshot_id"]] = _predict_group(bundles[group["cutoff_hour"]], group["rows"])
    if set(output) != {group["snapshot_id"] for group in groups}:
        raise SystemExit("CAPTURED_INPUT_PARITY_FAILURE: prediction key mismatch")
    return output


def _centre(rows: list[dict], probabilities: list[float]) -> float:
    return sum(row["band_mid"] * probability for row, probability in zip(rows, probabilities))


def _snapshot_values(group: dict, predictions: dict[str, list[float]]) -> dict:
    rows = group["rows"]
    settlement = float(group["settlement_bucket"])
    vectors = {
        "incumbent": [row["incumbent_probability"] for row in rows],
        "market": [row["market_probability"] for row in rows],
        **{name: values[group["snapshot_id"]] for name, values in predictions.items()},
    }
    result = {"settlement": settlement, "vectors": vectors, "models": {}}
    for name, probabilities in vectors.items():
        centre = _centre(rows, probabilities)
        error = centre - settlement
        band_losses = [(probability - row["outcome"]) ** 2 for row, probability in zip(rows, probabilities)]
        modal = max(range(len(probabilities)), key=lambda index: (probabilities[index], -index))
        result["models"][name] = {
            "centre_error": error,
            "centre_abs_error": abs(error),
            "centre_squared_error": error * error,
            "brier_sum": sum(band_losses),
            "brier_count": len(band_losses),
            "modal_hit": float(rows[modal]["outcome"] == 1),
            "mass_error": abs(sum(probabilities) - 1.0),
            "band_losses": band_losses,
        }
    incumbent_losses = result["models"]["incumbent"]["band_losses"]
    market_losses = result["models"]["market"]["band_losses"]
    severe = [
        index for index, row in enumerate(rows)
        if incumbent_losses[index] > market_losses[index]
        and abs(row["incumbent_probability"] - row["market_probability"]) >= 0.30
    ]
    result["severe_indexes"] = severe
    return result


def _metric_summary(values: list[dict], model_name: str) -> dict:
    model_values = [value["models"][model_name] for value in values]
    severe_losses = [
        model_values[index]["band_losses"][band_index]
        for index, value in enumerate(values)
        for band_index in value["severe_indexes"]
    ]
    return {
        "signed_centre_error": sum(item["centre_error"] for item in model_values) / len(model_values),
        "centre_mae": sum(item["centre_abs_error"] for item in model_values) / len(model_values),
        "centre_sse": sum(item["centre_squared_error"] for item in model_values) / len(model_values),
        "brier": sum(item["brier_sum"] for item in model_values) / sum(item["brier_count"] for item in model_values),
        "severe_tail_sse": sum(severe_losses) / len(severe_losses) if severe_losses else None,
        "modal_hit_rate": sum(item["modal_hit"] for item in model_values) / len(model_values),
        "maximum_probability_mass_error": max(item["mass_error"] for item in model_values),
    }


def _crossed_draws(records: list[tuple[str, str, float, float]], *, draws: int, seed: int) -> dict:
    dates = sorted({record[0] for record in records})
    markets = sorted({record[1] for record in records})
    date_index = {value: index for index, value in enumerate(dates)}
    market_index = {value: index for index, value in enumerate(markets)}
    numerator = np.zeros((len(dates), len(markets)), dtype=float)
    denominator = np.zeros_like(numerator)
    for target_date, market_id, value, weight in records:
        row = date_index[target_date]
        column = market_index[market_id]
        numerator[row, column] += value
        denominator[row, column] += weight
    rng = np.random.default_rng(seed)
    output = np.empty(draws, dtype=float)
    batch_size = 1000
    date_prob = np.full(len(dates), 1.0 / len(dates))
    market_prob = np.full(len(markets), 1.0 / len(markets))
    for start in range(0, draws, batch_size):
        count = min(batch_size, draws - start)
        date_weights = rng.multinomial(len(dates), date_prob, size=count)
        market_weights = rng.multinomial(len(markets), market_prob, size=count)
        weighted_numerator = np.einsum("bi,ij,bj->b", date_weights, numerator, market_weights)
        weighted_denominator = np.einsum("bi,ij,bj->b", date_weights, denominator, market_weights)
        output[start:start + count] = weighted_numerator / weighted_denominator
    point = float(numerator.sum() / denominator.sum())
    standard_error = float(output.std(ddof=1))
    lower, upper = (float(value) for value in np.quantile(output, [0.025, 0.975]))
    if standard_error == 0.0:
        power = 1.0 if point != 0.0 else 0.05
    else:
        noncentrality = abs(point) / standard_error
        normal = lambda value: 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))
        power = normal(-1.959963984540054 - noncentrality) + 1.0 - normal(1.959963984540054 - noncentrality)
    mde = (1.959963984540054 + 0.8416212335729143) * standard_error
    return {
        "point": point,
        "lower_95": lower,
        "upper_95": upper,
        "standard_error": standard_error,
        "achieved_power": float(power),
        "mde_80": mde,
        "draws": draws,
        "date_clusters": len(dates),
        "market_clusters": len(markets),
        "effective_cluster_cells": int(np.count_nonzero(denominator)),
    }


def _effect_records(groups: list[dict], values: list[dict], first: str, second: str, metric: str) -> list[tuple[str, str, float, float]]:
    records = []
    for group, value in zip(groups, values):
        left = value["models"][first]
        right = value["models"][second]
        if metric == "brier_improvement":
            effect = left["brier_sum"] - right["brier_sum"]
            weight = left["brier_count"]
        elif metric == "brier_difference":
            effect = right["brier_sum"] - left["brier_sum"]
            weight = left["brier_count"]
        else:
            effect = left[metric] - right[metric]
            weight = 1.0
        records.append((group["target_date"], group["market_id"], effect, weight))
    return records


def _severe_effect_records(groups: list[dict], values: list[dict], first: str, second: str) -> list[tuple[str, str, float, float]]:
    records = []
    for group, value in zip(groups, values):
        indexes = value["severe_indexes"]
        if not indexes:
            continue
        left = value["models"][first]["band_losses"]
        right = value["models"][second]["band_losses"]
        records.append((group["target_date"], group["market_id"], sum(left[index] - right[index] for index in indexes), float(len(indexes))))
    return records


def evaluate_split(groups: list[dict], predictions: dict[str, dict[str, list[float]]], *, draws: int, seed: int) -> dict:
    values = [_snapshot_values(group, predictions) for group in groups]
    model_names = ["incumbent", "market", *predictions]
    metrics = {name: _metric_summary(values, name) for name in model_names}
    endpoints = {
        "primary_centre_bias_change": _crossed_draws(
            _effect_records(groups, values, "primary_baseline", "primary_challenger", "centre_error"), draws=draws, seed=seed
        ),
        "primary_centre_mae_improvement": _crossed_draws(
            _effect_records(groups, values, "primary_baseline", "primary_challenger", "centre_abs_error"), draws=draws, seed=seed
        ),
        "primary_centre_sse_improvement": _crossed_draws(
            _effect_records(groups, values, "primary_baseline", "primary_challenger", "centre_squared_error"), draws=draws, seed=seed
        ),
        "primary_brier_challenger_minus_baseline": _crossed_draws(
            _effect_records(groups, values, "primary_baseline", "primary_challenger", "brier_difference"), draws=draws, seed=seed
        ),
        "primary_severe_tail_sse_improvement": _crossed_draws(
            _severe_effect_records(groups, values, "primary_baseline", "primary_challenger"), draws=draws, seed=seed
        ),
        "primary_modal_hit_improvement": _crossed_draws(
            _effect_records(groups, values, "primary_challenger", "primary_baseline", "modal_hit"), draws=draws, seed=seed
        ),
        "sensitivity_centre_sse_improvement": _crossed_draws(
            _effect_records(groups, values, "sensitivity_baseline", "sensitivity_challenger", "centre_squared_error"), draws=draws, seed=seed
        ),
        "sensitivity_brier_challenger_minus_baseline": _crossed_draws(
            _effect_records(groups, values, "sensitivity_baseline", "sensitivity_challenger", "brier_difference"), draws=draws, seed=seed
        ),
    }
    by_market = {}
    total_centre_improvement = 0.0
    market_sums = {}
    for market_id in EXPECTED_MARKETS:
        indexes = [index for index, group in enumerate(groups) if group["market_id"] == market_id]
        if not indexes:
            continue
        centre_effects = [
            values[index]["models"]["primary_baseline"]["centre_squared_error"]
            - values[index]["models"]["primary_challenger"]["centre_squared_error"]
            for index in indexes
        ]
        brier_left = sum(values[index]["models"]["primary_baseline"]["brier_sum"] for index in indexes)
        brier_right = sum(values[index]["models"]["primary_challenger"]["brier_sum"] for index in indexes)
        brier_n = sum(values[index]["models"]["primary_baseline"]["brier_count"] for index in indexes)
        market_sum = sum(centre_effects)
        market_sums[market_id] = market_sum
        total_centre_improvement += market_sum
        by_market[market_id] = {
            "snapshots": len(indexes),
            "centre_sse_improvement": market_sum / len(indexes),
            "brier_challenger_minus_baseline": (brier_right - brier_left) / brier_n,
        }
    concentration = None
    if total_centre_improvement > 0:
        concentration = max(market_sums.values()) / total_centre_improvement
    severe_rows = sum(len(value["severe_indexes"]) for value in values)
    return {
        "support": _validate_group_population(groups, expected=None, label="evaluation"),
        "metrics": metrics,
        "paired_endpoints": endpoints,
        "severe_tail_band_rows": severe_rows,
        "per_market": by_market,
        "maximum_one_market_contribution": concentration,
        "probability_mass_valid": all(item["maximum_probability_mass_error"] <= 1e-12 for item in metrics.values()),
        "captured_input_parity": all(set(prediction) == {group["snapshot_id"] for group in groups} for prediction in predictions.values()),
    }


def _decision(c_pre: dict) -> dict:
    centre = c_pre["paired_endpoints"]["primary_centre_sse_improvement"]
    brier = c_pre["paired_endpoints"]["primary_brier_challenger_minus_baseline"]
    sensitivity = c_pre["paired_endpoints"]["sensitivity_centre_sse_improvement"]
    concentration = c_pre["maximum_one_market_contribution"]
    conditions = {
        "centre_improvement_positive_and_interval_excludes_zero": centre["point"] > 0 and centre["lower_95"] > 0,
        "brier_nonpositive_and_upper_no_worse_than_0.002": brier["point"] <= 0 and brier["upper_95"] <= 0.002,
        "lead_2_7_sensitivity_same_favorable_centre_direction": sensitivity["point"] > 0,
        "probability_mass_and_captured_input_parity": c_pre["probability_mass_valid"] and c_pre["captured_input_parity"],
        "maximum_one_market_contribution_at_most_0.35": concentration is not None and concentration <= 0.35,
        "no_prohibited_model_inputs": True,
    }
    if all(conditions.values()):
        verdict = "GO_TO_SECOND_RESEARCH_REPLICATION"
    elif centre["upper_95"] < 0 or brier["lower_95"] > 0.002:
        verdict = "NO_GO"
    elif centre["lower_95"] <= 0 <= centre["upper_95"]:
        verdict = "INCONCLUSIVE_UNDERPOWERED"
    else:
        verdict = "NO_GO"
    return {"verdict": verdict, "conditions": conditions}


def run_experiment(
    *,
    design_path: Path,
    output_root: Path,
) -> dict:
    design = _validate_design(design_path)
    binding = design["input_binding"]
    corpus_root = Path(binding["corpus_root"])
    p0_path = Path(output_root) / "p0-transfer-integrity.json"
    if not p0_path.exists():
        raise SystemExit("TRANSFER_INTEGRITY_FAILURE: scratch P0 receipt is absent")
    p0 = _load_json(p0_path)
    if p0.get("transfer_manifest_sha256") != EXPECTED_MANIFEST_SHA256 or p0.get("status") != "PASS":
        raise SystemExit("TRANSFER_INTEGRITY_FAILURE: scratch P0 receipt is invalid")

    daily, forecast_metadata = load_forecast_features(corpus_root)
    mirror_root = Path(binding["frozen_mirror_root"])
    settlement_index = load_settlement_index(mirror_root)
    fit_b, c_pre = load_retained_groups(Path(binding["retained_repaired_surface"]), settlement_index)
    c_post, post_metadata = load_post_groups(mirror_root)
    if not c_post:
        raise SystemExit("EVALUATION_INPUT_FAILURE: C-post has no admitted snapshots")

    specifications = {
        "primary_baseline": (tuple(EXPECTED_LEADS), ("temperature_2m",)),
        "primary_challenger": (tuple(EXPECTED_LEADS), tuple(EXPECTED_FIELDS)),
        "sensitivity_baseline": (tuple(range(2, 8)), ("temperature_2m",)),
        "sensitivity_challenger": (tuple(range(2, 8)), tuple(EXPECTED_FIELDS)),
    }
    artifact_root = output_root / "models"
    bundles = {}
    model_summaries = {}
    for variant_id, (leads, fields) in specifications.items():
        fitted, summary = fit_variant(
            fit_b,
            daily=daily,
            leads=leads,
            fields=fields,
            artifact_root=artifact_root,
            variant_id=variant_id,
            write_artifacts=True,
        )
        reproduced, reproduced_summary = fit_variant(
            fit_b,
            daily=daily,
            leads=leads,
            fields=fields,
            artifact_root=artifact_root,
            variant_id=variant_id,
            write_artifacts=False,
        )
        if summary["aggregate_model_sha256"] != reproduced_summary["aggregate_model_sha256"]:
            raise SystemExit(f"DETERMINISTIC_REFIT_FAILURE: {variant_id}")
        bundles[variant_id] = fitted
        model_summaries[variant_id] = {**summary, "deterministic_refit_pass": True}
        del reproduced

    def predict_all(groups: list[dict]) -> dict[str, dict[str, list[float]]]:
        return {
            variant_id: predict_variant(groups, bundles[variant_id], daily=daily, leads=leads, fields=fields)
            for variant_id, (leads, fields) in specifications.items()
        }

    c_pre_predictions = predict_all(c_pre)
    c_post_predictions = predict_all(c_post)
    c_pre_result = evaluate_split(c_pre, c_pre_predictions, draws=20_000, seed=8_602_026)
    c_post_result = evaluate_split(c_post, c_post_predictions, draws=20_000, seed=8_602_026)
    decision = _decision(c_pre_result)
    result = {
        "result_version": "seasonal_challenger_12field_result_v1",
        "status": "COMPLETE_RESEARCH_ONLY",
        "design_sha256": design["design_sha256"],
        "design_file_sha256": sha256_file(design_path),
        "corpus": {
            "transfer_manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "forecast_aggregate": forecast_metadata,
        },
        "fit_support": _validate_group_population(fit_b, expected=None, label="B"),
        "models": model_summaries,
        "C_pre": c_pre_result,
        "C_post": c_post_result,
        "C_post_admission": post_metadata,
        "decision": decision,
        "exclusions_and_missingness": {
            "B": {"excluded_after_canonical_admission": 0, "missing_forecast_features": 0},
            "C_pre": {"excluded_after_canonical_admission": 0, "missing_forecast_features": 0},
            "C_post": post_metadata["exclusions"],
        },
        "prohibited_actions_audit": {
            "provider_or_network_call": False,
            "production_or_mirror_write": False,
            "scheduler_access": False,
            "exchange_access": False,
            "credential_access": False,
            "release_or_pointer_or_promotion": False,
            "candidate_freeze_or_confirmation_window": False,
            "market_or_outcome_or_settlement_model_input": False,
            "cross_boundary_pooling": False,
        },
    }
    result["result_sha256"] = canonical_sha256(result)
    return result


def verify_result(*, result_path: Path, design_path: Path, artifact_root: Path) -> dict:
    design = _validate_design(design_path)
    result = _load_json(result_path)
    declared = result.get("result_sha256")
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    actual = canonical_sha256(unsigned)
    checks = {
        "canonical_result_hash": declared == actual,
        "design_binding": result.get("design_sha256") == design.get("design_sha256"),
        "design_file_binding": result.get("design_file_sha256") == sha256_file(design_path),
        "transfer_manifest_binding": result.get("corpus", {}).get("transfer_manifest_sha256") == EXPECTED_MANIFEST_SHA256,
        "B_support": result.get("fit_support") == {
            "band_rows": 50996,
            "date_clusters": 23,
            "effective_cluster_cells": 204,
            "market_clusters": 12,
            "market_days": 204,
            "snapshot_cutoff_rows": 4636,
        },
        "C_pre_support": result.get("C_pre", {}).get("support") == {
            "band_rows": 84183,
            "date_clusters": 27,
            "effective_cluster_cells": 320,
            "market_clusters": 12,
            "market_days": 320,
            "snapshot_cutoff_rows": 7653,
        },
        "boundary_not_pooled": result.get("prohibited_actions_audit", {}).get("cross_boundary_pooling") is False,
        "probability_mass": result.get("C_pre", {}).get("probability_mass_valid") is True and result.get("C_post", {}).get("probability_mass_valid") is True,
        "captured_input_parity": result.get("C_pre", {}).get("captured_input_parity") is True and result.get("C_post", {}).get("captured_input_parity") is True,
        "decision_reproduction": result.get("decision") == _decision(result["C_pre"]),
        "prohibited_actions_clear": all(value is False for value in result.get("prohibited_actions_audit", {}).values()),
    }
    artifact_checks = {}
    for variant_id, model in (result.get("models") or {}).items():
        for hour, expected in (model.get("cutoff_model_sha256") or {}).items():
            path = artifact_root / variant_id / f"cutoff-{int(hour):02d}.pickle"
            artifact_checks[f"{variant_id}/{hour}"] = path.is_file() and sha256_file(path) == expected
    checks["all_model_artifact_hashes"] = bool(artifact_checks) and all(artifact_checks.values())
    if not all(checks.values()):
        failed = sorted(key for key, passed in checks.items() if not passed)
        raise SystemExit("RESULT_VERIFICATION_FAILURE: " + ", ".join(failed))
    return {
        "verification_version": "seasonal_challenger_result_verification_v1",
        "status": "PASS",
        "result_file_sha256": sha256_file(result_path),
        "result_canonical_sha256": actual,
        "design_sha256": design["design_sha256"],
        "checks": checks,
        "model_artifact_checks": artifact_checks,
        "check_count": len(checks) + len(artifact_checks),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify-corpus")
    verify.add_argument("--corpus-root", type=Path, required=True)
    verify.add_argument("--expected-manifest-sha256", required=True)
    verify.add_argument("--output", type=Path, required=True)
    freeze = subparsers.add_parser("freeze-design")
    freeze.add_argument("--corpus-root", type=Path, required=True)
    freeze.add_argument("--p0-receipt", type=Path, required=True)
    freeze.add_argument("--retained-rows", type=Path, required=True)
    freeze.add_argument("--mirror-root", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--design", type=Path, required=True)
    run.add_argument("--output-root", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    verify_result_parser = subparsers.add_parser("verify-result")
    verify_result_parser.add_argument("--result", type=Path, required=True)
    verify_result_parser.add_argument("--design", type=Path, required=True)
    verify_result_parser.add_argument("--artifact-root", type=Path, required=True)
    verify_result_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-corpus":
        result = verify_corpus(args.corpus_root, args.expected_manifest_sha256)
    elif args.command == "freeze-design":
        result = freeze_design(
            corpus_root=args.corpus_root,
            p0_receipt=args.p0_receipt,
            retained_rows=args.retained_rows,
            mirror_root=args.mirror_root,
        )
    elif args.command == "run":
        result = run_experiment(design_path=args.design, output_root=args.output_root)
    elif args.command == "verify-result":
        result = verify_result(
            result_path=args.result,
            design_path=args.design,
            artifact_root=args.artifact_root,
        )
    else:  # pragma: no cover
        raise AssertionError(args.command)
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
