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
import stat
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path


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
    else:  # pragma: no cover
        raise AssertionError(args.command)
    write_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
