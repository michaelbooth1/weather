"""No-refit external-secondary 2026 evaluation of the frozen residual models."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pickle
import subprocess
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from unittest.mock import patch

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from weather.calibration import multiyear_nwp_residual as frozen
from weather.sources.daily_summary import native_bucket


TRANSFER_SCHEMA = "multiyear_nwp_residual_external_transfer_v1"
AMENDMENT_SCHEMA = "multiyear_nwp_residual_external_amendment_v1"
ATTEMPT_SCHEMA = "multiyear_nwp_residual_external_attempt_v1"
RESULT_SCHEMA = "multiyear_nwp_residual_external_result_v1"
VERIFICATION_SCHEMA = "multiyear_nwp_residual_external_verification_v1"

SOURCE_BRANCH = "codex/workstation-multiyear-nwp-residual-2026-09-88a"
SOURCE_TIP = "798225bc200d2909fb32175e21d870f86877faef"
SOURCE_TREE = "c9bb99a756bb81d7f3458f0763e63b15ebebb894"
FROZEN_DESIGN_FILE_SHA256 = (
    "0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65"
)
FROZEN_DESIGN_SHA256 = (
    "bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb"
)
FROZEN_MODULE_SHA256 = (
    "8b513188aa5a123f29c3225d2a8efa435a56b46a07c1bcc0f8a96e756641e27f"
)
FROZEN_TRAINING_SHA256 = (
    "776d14ac8de61e04e8a5066ab4f78464dcc2cd45a046d79e32081dfde825415c"
)
FROZEN_MODEL_SHA256 = {
    "temperature_residual_baseline": (
        "c1ee07eef33016633ebf1ffdf847c7b55d90a2420b198eac7fb07ee88f5c2797"
    ),
    "eleven_field_residual_challenger": (
        "0ae3e67cfcda420a9c0103959b2c79cac6438d7fadf162b41f36a47919862ab5"
    ),
}
TRANSFER_MANIFEST_SHA256 = (
    "1794455e40f967411d05660ff4ac785e1fab48caccb8fbdfb3df7aa31438712a"
)
BOUNDARY_ANCHOR = "b77cfbed"
EXTERNAL_YEAR = 2026
COHORTS = {
    "pre_boundary": (date(2026, 6, 3), date(2026, 7, 30)),
    "post_boundary_directional": (date(2026, 7, 31), date(2026, 8, 9)),
}
SEGMENTS = {
    "front": {
        "suffix": "_previous_runs_long_front.csv",
        "start": date(2026, 6, 3),
        "end": date(2026, 6, 23),
    },
    "back": {
        "suffix": "_previous_runs_long.csv",
        "start": date(2026, 6, 24),
        "end": date(2026, 8, 9),
    },
}
FORECAST_COLUMNS = frozen.CSV_COLUMNS
EXPECTED_PAYLOAD_COUNT = 28
EXPECTED_CSV_COUNT = 24
EXPECTED_INPUT_ROWS = 1_645_056
EXPECTED_FEATURE_MARKET_DAYS = 12 * 68
EXPECTED_EXCLUDED_ROWS = 12 * 68 * 7 * 24
PREDICTION_KEYS = frozen.PREDICTION_KEYS
RECORD_COLUMNS = ("cohort", *frozen.EVALUATION_RECORD_COLUMNS)


IntegrityError = frozen.IntegrityError


def _load_json(path: Path) -> dict:
    return frozen._load_json(path)


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return frozen.self_hash(value, field)


def _exclusive_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise IntegrityError(f"create-only JSON already exists: {path}")
    encoded = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _git(*arguments: str, binary: bool = False):
    completed = subprocess.run(
        ["git", *arguments],
        check=False,
        capture_output=True,
        text=not binary,
    )
    if completed.returncode != 0:
        stderr = completed.stderr if not binary else completed.stderr.decode(errors="replace")
        raise IntegrityError(f"git {' '.join(arguments)} failed: {stderr.strip()}")
    return completed.stdout


def _git_identity() -> dict:
    return {
        "branch": str(_git("branch", "--show-current")).strip(),
        "commit": str(_git("rev-parse", "HEAD")).strip(),
        "tree": str(_git("rev-parse", "HEAD^{tree}")).strip(),
    }


def _committed_amendment_proof(path: Path) -> dict:
    root = Path(str(_git("rev-parse", "--show-toplevel")).strip()).resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise IntegrityError("evaluation amendment is outside the repository") from exc
    committed = _git("show", f"HEAD:{relative}", binary=True)
    working = resolved.read_bytes()
    if committed != working:
        raise IntegrityError("evaluation amendment is not committed byte-for-byte at HEAD")
    status = str(_git("status", "--porcelain", "--untracked-files=all"))
    if status.strip():
        raise IntegrityError("external evaluation requires a clean amendment commit")
    return {
        **_git_identity(),
        "relative_path": relative,
        "blob": str(_git("rev-parse", f"HEAD:{relative}")).strip(),
        "file_sha256": frozen.sha256_file(resolved),
        "worktree_clean": True,
    }


def _expected_csv_paths() -> set[str]:
    return {
        f"{segment}/{market}{spec['suffix']}"
        for segment, spec in SEGMENTS.items()
        for market in frozen.MARKETS
    }


def verify_transfer(corpus_root: Path) -> dict:
    root = corpus_root.resolve(strict=True)
    if not root.is_dir() or frozen._is_reparse_point(root):
        raise IntegrityError("2026 transfer root is absent or redirected")
    manifest_path = root / "transfer-manifest.json"
    manifest_hash = frozen.sha256_file(manifest_path)
    if manifest_hash != TRANSFER_MANIFEST_SHA256:
        raise IntegrityError("2026 transfer-manifest hash differs")
    declared_hash = (root / "transfer-manifest.sha256").read_text(
        encoding="ascii"
    ).strip()
    if declared_hash != f"{TRANSFER_MANIFEST_SHA256}  transfer-manifest.json":
        raise IntegrityError("2026 transfer checksum sidecar differs")
    manifest = _load_json(manifest_path)
    files = manifest.get("files") or []
    if (
        manifest.get("schema_version") != "pit_12field_transfer_manifest_v0.1"
        or manifest.get("required_file_count") != EXPECTED_PAYLOAD_COUNT
        or len(files) != EXPECTED_PAYLOAD_COUNT
        or manifest.get("total_source_bytes") != 171_401_140
        or manifest.get("combined_rows") != EXPECTED_INPUT_ROWS
        or manifest.get("market_count") != len(frozen.MARKETS)
        or manifest.get("field_count") != 12
        or tuple(manifest.get("leads") or ()) != frozen.LEADS_SENSITIVITY
    ):
        raise IntegrityError("2026 transfer-manifest contract differs")
    seen: set[str] = set()
    verified = []
    for record in files:
        relative = str(record.get("relative_path") or "")
        if relative in seen:
            raise IntegrityError(f"duplicate transfer payload: {relative}")
        seen.add(relative)
        path = (root / Path(relative)).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise IntegrityError("transfer payload escaped its root") from exc
        if not path.is_file() or frozen._is_reparse_point(path):
            raise IntegrityError(f"transfer payload is absent or redirected: {relative}")
        actual = {
            "relative_path": relative,
            "bytes": path.stat().st_size,
            "sha256": frozen.sha256_file(path),
        }
        if actual != {
            "relative_path": relative,
            "bytes": record.get("bytes"),
            "sha256": record.get("sha256"),
        }:
            raise IntegrityError(f"transfer payload hash/size differs: {relative}")
        verified.append(actual)
    if sum(item["bytes"] for item in verified) != manifest["total_source_bytes"]:
        raise IntegrityError("2026 transfer payload byte total differs")
    csv_records = [item for item in verified if item["relative_path"].endswith(".csv")]
    csv_paths = {item["relative_path"] for item in csv_records}
    if len(csv_records) != EXPECTED_CSV_COUNT or csv_paths != _expected_csv_paths():
        raise IntegrityError("2026 transfer does not contain the exact 24 forecast CSVs")
    for record in csv_records:
        with (root / record["relative_path"]).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            if tuple(next(csv.reader(handle), ())) != FORECAST_COLUMNS:
                raise IntegrityError(
                    f"forecast CSV header differs: {record['relative_path']}"
                )
    audit = {
        "schema_version": TRANSFER_SCHEMA,
        "status": "PASS",
        "root": str(root),
        "manifest_sha256": manifest_hash,
        "payload_count": len(verified),
        "payload_bytes": sum(item["bytes"] for item in verified),
        "payload_inventory_sha256": frozen.canonical_sha256(verified),
        "csv_count": len(csv_records),
        "csv_inventory_sha256": frozen.canonical_sha256(csv_records),
        "combined_rows": manifest["combined_rows"],
        "provider_contacted": False,
        "outcomes_read": False,
        "files": verified,
    }
    audit["transfer_sha256"] = _self_hash(audit, "transfer_sha256")
    return audit


def _load_model_payload(path: Path, arm: str, design: dict) -> dict:
    actual_hash = frozen.sha256_file(path)
    if actual_hash != FROZEN_MODEL_SHA256[arm]:
        raise IntegrityError(f"frozen {arm} model hash differs")
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    order = (
        frozen.BASELINE_FEATURES
        if arm == "temperature_residual_baseline"
        else frozen.CHALLENGER_FEATURES
    )
    if (
        payload.get("artifact_version") != "multiyear_nwp_residual_model_v1"
        or payload.get("arm") != arm
        or payload.get("design_sha256") != design["design_sha256"]
        or payload.get("estimator_configuration") != frozen.MODEL_CONFIG
        or tuple(payload.get("feature_order") or ()) != order
        or not isinstance(payload.get("estimator"), HistGradientBoostingRegressor)
    ):
        raise IntegrityError(f"frozen {arm} model contract differs")
    return payload


def verify_frozen_identity(design_path: Path, artifact_root: Path) -> tuple[dict, dict, dict]:
    if frozen.sha256_file(design_path) != FROZEN_DESIGN_FILE_SHA256:
        raise IntegrityError("frozen design file hash differs")
    if frozen.sha256_file(Path(frozen.__file__).resolve(strict=True)) != FROZEN_MODULE_SHA256:
        raise IntegrityError("frozen evaluator module hash differs")
    design = frozen._validate_design(design_path)
    if design.get("design_sha256") != FROZEN_DESIGN_SHA256:
        raise IntegrityError("frozen design self-hash differs")
    receipt = _load_json(artifact_root / "training-receipt.json")
    if (
        receipt.get("training_sha256") != FROZEN_TRAINING_SHA256
        or receipt.get("training_sha256")
        != _self_hash(receipt, "training_sha256")
        or receipt.get("models_fitted") != 2
        or receipt.get("terminal_evaluation_outcomes_accessed") is not False
    ):
        raise IntegrityError("frozen training receipt differs")
    artifact_records = {item["arm"]: item for item in receipt.get("artifacts") or []}
    if set(artifact_records) != set(FROZEN_MODEL_SHA256):
        raise IntegrityError("frozen model artifact set differs")
    bundles = {}
    for arm, expected_hash in FROZEN_MODEL_SHA256.items():
        record = artifact_records[arm]
        if record.get("sha256") != expected_hash:
            raise IntegrityError(f"training receipt model hash differs: {arm}")
        bundles[arm] = _load_model_payload(
            artifact_root / record["relative_path"], arm, design
        )
    feature_order_hashes = {
        "baseline": frozen.canonical_sha256(list(frozen.BASELINE_FEATURES)),
        "challenger": frozen.canonical_sha256(list(frozen.CHALLENGER_FEATURES)),
        "combined": frozen.canonical_sha256(
            {
                "baseline": list(frozen.BASELINE_FEATURES),
                "challenger": list(frozen.CHALLENGER_FEATURES),
            }
        ),
    }
    identity = {
        "source_branch": SOURCE_BRANCH,
        "source_tip": SOURCE_TIP,
        "source_tree": SOURCE_TREE,
        "design_file_sha256": frozen.sha256_file(design_path),
        "design_sha256": design["design_sha256"],
        "frozen_module_sha256": FROZEN_MODULE_SHA256,
        "training_receipt_file_sha256": frozen.sha256_file(
            artifact_root / "training-receipt.json"
        ),
        "training_sha256": receipt["training_sha256"],
        "model_sha256": FROZEN_MODEL_SHA256,
        "feature_order_sha256": feature_order_hashes,
        "model_count": 2,
        "models_refitted": 0,
        "probability_models_refitted": 0,
    }
    identity["identity_sha256"] = _self_hash(identity, "identity_sha256")
    return design, bundles, identity


def freeze_amendment(
    *, design_path: Path, artifact_root: Path, corpus_root: Path, output: Path
) -> dict:
    design, _, identity = verify_frozen_identity(design_path, artifact_root)
    transfer = verify_transfer(corpus_root)
    amendment = {
        "schema_version": AMENDMENT_SCHEMA,
        "status": "IMMUTABLE_BEFORE_2026_OUTCOME_ACCESS",
        "purpose": (
            "Predeclared no-refit 2026 external-secondary directional evaluation; "
            "not a new candidate, replication, or confirmation."
        ),
        "prepared_on": _git_identity(),
        "source_model_result": {
            "branch": SOURCE_BRANCH,
            "tip": SOURCE_TIP,
            "tree": SOURCE_TREE,
            "original_verdict": "INCONCLUSIVE_UNDERPOWERED",
            "original_verdict_must_remain_unchanged": True,
        },
        "frozen_identity": identity,
        "evaluator": {
            "relative_path": "src/weather/calibration/multiyear_nwp_residual_external.py",
            "module_sha256": frozen.sha256_file(Path(__file__).resolve(strict=True)),
        },
        "prepared_inputs": {
            "design_path": str(design_path.resolve(strict=True)),
            "artifact_root": str(artifact_root.resolve(strict=True)),
        },
        "input_binding": {
            "corpus_root": str(corpus_root.resolve(strict=True)),
            "transfer_manifest_sha256": TRANSFER_MANIFEST_SHA256,
            "transfer_sha256": transfer["transfer_sha256"],
            "payload_inventory_sha256": transfer["payload_inventory_sha256"],
            "csv_inventory_sha256": transfer["csv_inventory_sha256"],
            "payload_count": EXPECTED_PAYLOAD_COUNT,
            "csv_count": EXPECTED_CSV_COUNT,
            "mirror_root": design["input_binding"]["mirror_root"],
            "outcome_source_file_inventory": design["input_binding"][
                "outcome_support_file_inventory"
            ],
            "outcome_source_file_inventory_sha256": design["input_binding"][
                "outcome_support_file_inventory_sha256"
            ],
        },
        "cohorts": {
            name: {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "role": (
                    "external_secondary"
                    if name == "pre_boundary"
                    else "external_secondary_directional"
                ),
            }
            for name, (start, end) in COHORTS.items()
        },
        "provenance_boundary": {
            "anchor": BOUNDARY_ANCHOR,
            "first_post_boundary_date": "2026-07-31",
            "cohorts_must_never_be_pooled": True,
        },
        "methods": {
            "models": "apply the exact two already-fitted estimators; fit is runtime-forbidden",
            "model_refits": 0,
            "probability_model_refits": 0,
            "features": "exact frozen feature order and preprocessing",
            "primary_leads": list(frozen.LEADS_PRIMARY),
            "sensitivity_leads": list(frozen.LEADS_SENSITIVITY),
            "native_units": frozen.MARKET_UNITS,
            "outcome_authority": "configured WU daily-summary native settlement high",
            "outcome_support": "row_count >= 18; no imputation or market exclusion",
            "errors": "forecast minus outcome; improvement is baseline loss minus challenger loss",
            "bootstrap": {
                "method": "shared-weight crossed target-date x market pigeonhole bootstrap",
                "draws": frozen.BOOTSTRAP_DRAWS,
                "seed": frozen.BOOTSTRAP_SEED,
                "interval": "percentile 95%",
            },
        },
        "prior_inspection": {
            "2026_outcomes_previously_inspected_by_different_model_mission": True,
            "classification": "external-secondary and non-confirmatory",
            "can_authorize_distribution": False,
        },
        "disposition": {
            "EXTERNAL_DIRECTION_CONSISTENT": (
                "both primary cohorts and both cohort-specific all-leads sensitivities "
                "have positive MSE improvement points"
            ),
            "EXTERNAL_DIRECTION_MIXED": "the four MSE improvement signs disagree or include zero",
            "EXTERNAL_DIRECTION_ADVERSE": (
                "both primary cohorts and both cohort-specific all-leads sensitivities "
                "have negative MSE improvement points"
            ),
            "INTEGRITY_FAILURE": "any hash, cohort, outcome, unit, boundary, or no-refit failure",
        },
        "prohibited_actions": [
            "provider contact",
            "model retraining, recalibration, feature, imputation, market, month, or threshold change",
            "2025 outcome access",
            "pooling across the b77cfbed / 2026-07-31 provenance boundary",
            "market-data access",
            "corpus or mirror mutation",
            "production, Scheduler, exchange, or credential access",
            "release, distribution model, promotion, candidate freeze, alpha, confirmation, or serving action",
            "branch merge",
        ],
    }
    amendment["amendment_sha256"] = _self_hash(amendment, "amendment_sha256")
    _exclusive_json(output, amendment)
    return amendment


def _validate_amendment(path: Path, artifact_root: Path) -> tuple[dict, dict, dict]:
    amendment = _load_json(path)
    if (
        amendment.get("schema_version") != AMENDMENT_SCHEMA
        or amendment.get("status") != "IMMUTABLE_BEFORE_2026_OUTCOME_ACCESS"
        or amendment.get("amendment_sha256")
        != _self_hash(amendment, "amendment_sha256")
        or amendment.get("source_model_result", {}).get("original_verdict")
        != "INCONCLUSIVE_UNDERPOWERED"
    ):
        raise IntegrityError("external evaluation amendment identity differs")
    if frozen.sha256_file(Path(__file__).resolve(strict=True)) != amendment[
        "evaluator"
    ]["module_sha256"]:
        raise IntegrityError("external evaluator changed after amendment freeze")
    prepared = amendment.get("prepared_inputs") or {}
    design_path = Path(prepared.get("design_path") or "")
    if artifact_root.resolve(strict=True) != Path(
        prepared.get("artifact_root") or ""
    ).resolve(strict=True):
        raise IntegrityError("frozen artifact root differs from the amendment")
    design, bundles, identity = verify_frozen_identity(design_path, artifact_root)
    if frozen.canonical_sha256(identity) != frozen.canonical_sha256(
        amendment["frozen_identity"]
    ):
        raise IntegrityError("frozen model/design identity changed after amendment")
    transfer = verify_transfer(Path(amendment["input_binding"]["corpus_root"]))
    for field in ("transfer_sha256", "payload_inventory_sha256", "csv_inventory_sha256"):
        if transfer[field] != amendment["input_binding"][field]:
            raise IntegrityError(f"external transfer {field} changed after amendment")
    return amendment, design, bundles


def _date_range(start: date, end: date) -> list[str]:
    return [date.fromordinal(value).isoformat() for value in range(start.toordinal(), end.toordinal() + 1)]


def load_feature_surfaces(corpus_root: Path) -> tuple[dict, dict]:
    root = corpus_root.resolve(strict=True)
    accumulators: dict[tuple[str, str, int, str], frozen._Accumulator] = {}
    source_files = []
    row_count = 0
    excluded_rows = 0
    field_units: dict[str, set[str]] = defaultdict(set)
    for market in frozen.MARKETS:
        for segment, spec in SEGMENTS.items():
            relative = Path(segment) / f"{market}{spec['suffix']}"
            path = (root / relative).resolve(strict=True)
            source_files.append(
                {
                    "relative_path": relative.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": frozen.sha256_file(path),
                }
            )
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                if tuple(next(reader, ())) != FORECAST_COLUMNS:
                    raise IntegrityError(f"feature CSV header differs: {relative}")
                for line_number, row in enumerate(reader, start=2):
                    row_count += 1
                    if len(row) != len(FORECAST_COLUMNS) or row[0] != market:
                        raise IntegrityError(f"feature row shape/market differs: {relative}:{line_number}")
                    field = row[2]
                    if field == frozen.EXCLUDED_FIELD:
                        excluded_rows += 1
                        continue
                    if field not in frozen.FIELDS:
                        raise IntegrityError(f"unexpected feature field: {relative}:{line_number}")
                    try:
                        timestamp = datetime.fromisoformat(row[1])
                        lead = int(row[3])
                        value = float(row[4])
                    except ValueError as exc:
                        raise IntegrityError(f"invalid feature row: {relative}:{line_number}: {exc}") from None
                    if (
                        timestamp.date() < spec["start"]
                        or timestamp.date() > spec["end"]
                        or lead not in frozen.LEADS_SENSITIVITY
                        or not math.isfinite(value)
                        or row[6] != "fixed_lead_day_offset"
                        or row[7] != "open_meteo_previous_runs"
                    ):
                        raise IntegrityError(f"feature date/lead/value/provenance differs: {relative}:{line_number}")
                    field_units[field].add(row[5])
                    if field == "temperature_2m":
                        expected_unit = "celsius" if market == "toronto" else "fahrenheit"
                        if row[5] != expected_unit:
                            raise IntegrityError(f"temperature feature unit differs: {relative}:{line_number}")
                    for summary in frozen._summary_targets(field, timestamp.hour):
                        key = (market, timestamp.date().isoformat(), lead, summary)
                        accumulators.setdefault(key, frozen._Accumulator()).add(value)
    if row_count != EXPECTED_INPUT_ROWS or excluded_rows != EXPECTED_EXCLUDED_ROWS:
        raise IntegrityError("2026 feature row/excluded-field count differs")
    surfaces: dict[tuple[str, str], dict[int, dict[str, float]]] = defaultdict(dict)
    all_dates = _date_range(date(2026, 6, 3), date(2026, 8, 9))
    for market in frozen.MARKETS:
        for target_date in all_dates:
            for lead in frozen.LEADS_SENSITIVITY:
                summaries = {}
                for name in frozen.SUMMARY_NAMES:
                    key = (market, target_date, lead, name)
                    if key not in accumulators:
                        raise IntegrityError(f"external feature summary is absent: {key}")
                    summaries[name] = frozen._finish_accumulator(name, accumulators[key])
                surfaces[(market, target_date)][lead] = summaries
    if len(surfaces) != EXPECTED_FEATURE_MARKET_DAYS:
        raise IntegrityError("2026 feature market-day count differs")
    audit = {
        "year": EXTERNAL_YEAR,
        "source_file_count": len(source_files),
        "source_files": source_files,
        "source_files_sha256": frozen.canonical_sha256(source_files),
        "input_rows": row_count,
        "excluded_precipitation_probability_rows": excluded_rows,
        "precipitation_probability_feature_rows_used": 0,
        "market_days": len(surfaces),
        "field_units": {key: sorted(value) for key, value in sorted(field_units.items())},
        "feature_surface_sha256": frozen.canonical_sha256(
            [
                {"market": key[0], "target_date": key[1], "leads": surfaces[key]}
                for key in sorted(surfaces)
            ]
        ),
    }
    return dict(surfaces), audit


def _current_outcome_inventory(amendment: dict) -> dict:
    mirror = Path(amendment["input_binding"]["mirror_root"]).resolve(strict=True)
    expected = amendment["input_binding"]["outcome_source_file_inventory"]
    if frozen.canonical_sha256(expected) != amendment["input_binding"][
        "outcome_source_file_inventory_sha256"
    ]:
        raise IntegrityError("amended outcome inventory self-hash differs")
    actual = []
    for record in expected:
        path = (mirror / record["relative_path"]).resolve(strict=True)
        observed = {
            "market": record["market"],
            "station": record["station"],
            "relative_path": record["relative_path"],
            "bytes": path.stat().st_size,
            "sha256": frozen.sha256_file(path),
        }
        if observed != record:
            raise IntegrityError(f"WU source identity changed: {record['market']}")
        actual.append(observed)
    return {
        "mirror_root": str(mirror),
        "file_count": len(actual),
        "file_inventory_sha256": frozen.canonical_sha256(actual),
        "files": actual,
    }


def load_2026_outcomes(amendment: dict) -> tuple[dict, dict]:
    inventory = _current_outcome_inventory(amendment)
    mirror = Path(inventory["mirror_root"])
    required_dates = {
        value
        for start, end in COHORTS.values()
        for value in _date_range(start, end)
    }
    outcomes: dict[tuple[str, str], int] = {}
    exclusions = []
    semantic_access_by_year: dict[int, int] = defaultdict(int)
    ignored_non_2026_rows = 0
    for market, path in frozen._outcome_paths(mirror).items():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = tuple(next(reader, ()))
            required = {
                "schema_version",
                "local_date",
                "temperature_unit",
                "row_count",
                "max_temp_bucket_native",
            }
            if not required.issubset(header):
                raise IntegrityError(f"WU external outcome columns are incomplete: {market}")
            positions = {name: header.index(name) for name in required}
            for line_number, row in enumerate(reader, start=2):
                try:
                    raw_date = row[positions["local_date"]]
                    local_date = date.fromisoformat(raw_date)
                except (IndexError, ValueError):
                    continue
                if local_date.year != EXTERNAL_YEAR:
                    ignored_non_2026_rows += 1
                    continue
                if raw_date not in required_dates:
                    continue
                try:
                    row_count = int(row[positions["row_count"]])
                except (IndexError, ValueError):
                    row_count = 0
                if row_count < frozen.COMPLETE_DAY_MIN_ROWS:
                    exclusions.append(
                        {"market": market, "target_date": raw_date, "reason": "wu_row_count_below_18", "row_count": row_count}
                    )
                    continue
                unit = row[positions["temperature_unit"]].strip().upper()
                if unit != frozen.MARKET_UNITS[market]:
                    raise IntegrityError(f"WU native unit differs: {market}/{raw_date}")
                selected = {name: row[index] for name, index in positions.items()}
                outcome = native_bucket(selected)
                semantic_access_by_year[local_date.year] += 1
                if outcome is None:
                    raise IntegrityError(f"WU native outcome is absent: {market}/{raw_date}")
                key = (market, raw_date)
                if key in outcomes:
                    raise IntegrityError(f"duplicate WU external outcome: {market}/{raw_date}")
                outcomes[key] = int(outcome)
    expected = len(required_dates) * len(frozen.MARKETS)
    if len(outcomes) + len(exclusions) != expected:
        observed = set(outcomes) | {(item["market"], item["target_date"]) for item in exclusions}
        missing = sorted(
            (market, target_date)
            for market in frozen.MARKETS
            for target_date in required_dates
            if (market, target_date) not in observed
        )
        raise IntegrityError(f"WU external outcome coverage differs: {missing[:3]}")
    if semantic_access_by_year != {EXTERNAL_YEAR: len(outcomes)}:
        raise IntegrityError("non-2026 outcome value was accessed")
    admitted_markets = sorted({market for market, _ in outcomes})
    if admitted_markets != list(frozen.MARKETS):
        raise IntegrityError("external outcome support excluded a market")
    audit = {
        "year": EXTERNAL_YEAR,
        "authority": "WU daily-summary native settlement high",
        "minimum_row_count": frozen.COMPLETE_DAY_MIN_ROWS,
        "market_days": len(outcomes),
        "exclusions": exclusions,
        "excluded_count": len(exclusions),
        "semantic_outcome_value_access_by_year": {str(key): value for key, value in semantic_access_by_year.items()},
        "outcome_value_access_2025": 0,
        "ignored_non_2026_rows_without_outcome_value_access": ignored_non_2026_rows,
        "source_inventory": inventory,
        "keys_sha256": frozen.canonical_sha256(
            [f"{EXTERNAL_YEAR}|{market}|{target_date}" for market, target_date in sorted(outcomes)]
        ),
    }
    return outcomes, audit


@contextmanager
def _no_refit_guard() -> Iterator[dict]:
    audit = {"fit_calls_attempted": 0, "active": True}

    def forbidden_fit(*_args, **_kwargs):
        audit["fit_calls_attempted"] += 1
        raise IntegrityError("model refit attempted during no-refit evaluation")

    with patch.object(HistGradientBoostingRegressor, "fit", forbidden_fit):
        yield audit
    audit["active"] = False


def _predict_records(
    *, surfaces: dict, outcomes: dict, bundles: dict, cohort: str
) -> tuple[list[dict], dict]:
    start, end = COHORTS[cohort]
    keys = sorted(
        (market, target_date)
        for (market, target_date) in outcomes
        if start.isoformat() <= target_date <= end.isoformat()
    )
    records = []
    baseline_x = []
    challenger_x = []
    sensitivity_baseline_x = []
    sensitivity_challenger_x = []
    primary_anchors = []
    sensitivity_anchors = []
    for market, target_date in keys:
        surface = surfaces.get((market, target_date))
        if surface is None:
            raise IntegrityError(f"matched external feature row is absent: {market}/{target_date}")
        baseline, anchor = frozen.feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=frozen.LEADS_PRIMARY,
            challenger=False,
        )
        challenger, challenger_anchor = frozen.feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=frozen.LEADS_PRIMARY,
            challenger=True,
        )
        sens_base, sens_anchor = frozen.feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=frozen.LEADS_SENSITIVITY,
            challenger=False,
        )
        sens_challenger, sens_challenger_anchor = frozen.feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=frozen.LEADS_SENSITIVITY,
            challenger=True,
        )
        if anchor != challenger_anchor or sens_anchor != sens_challenger_anchor:
            raise IntegrityError("external baseline/challenger anchors differ")
        records.append(
            {
                "cohort": cohort,
                "market": market,
                "target_date": target_date,
                "month": int(target_date[5:7]),
                "native_unit": frozen.MARKET_UNITS[market],
                "outcome_native": outcomes[(market, target_date)],
            }
        )
        baseline_x.append(baseline)
        challenger_x.append(challenger)
        sensitivity_baseline_x.append(sens_base)
        sensitivity_challenger_x.append(sens_challenger)
        primary_anchors.append(anchor)
        sensitivity_anchors.append(sens_anchor)
    baseline_model = bundles["temperature_residual_baseline"]["estimator"]
    challenger_model = bundles["eleven_field_residual_challenger"]["estimator"]
    with _no_refit_guard() as guard:
        primary_baseline = baseline_model.predict(np.asarray(baseline_x, dtype=float))
        primary_challenger = challenger_model.predict(np.asarray(challenger_x, dtype=float))
        sensitivity_baseline = baseline_model.predict(np.asarray(sensitivity_baseline_x, dtype=float))
        sensitivity_challenger = challenger_model.predict(np.asarray(sensitivity_challenger_x, dtype=float))
    if guard["fit_calls_attempted"] != 0:
        raise IntegrityError("external evaluation attempted a model refit")
    for index, row in enumerate(records):
        row.update(
            {
                "raw_temperature_anchor_native": float(primary_anchors[index]),
                "temperature_residual_baseline_native": float(primary_anchors[index] + primary_baseline[index]),
                "eleven_field_residual_challenger_native": float(primary_anchors[index] + primary_challenger[index]),
                "all_leads_raw_temperature_anchor_native": float(sensitivity_anchors[index]),
                "all_leads_temperature_residual_baseline_native": float(sensitivity_anchors[index] + sensitivity_baseline[index]),
                "all_leads_eleven_field_residual_challenger_native": float(sensitivity_anchors[index] + sensitivity_challenger[index]),
            }
        )
    return records, {
        "guard": "HistGradientBoostingRegressor.fit runtime-forbidden during prediction",
        "fit_calls_attempted": guard["fit_calls_attempted"],
        "models_refitted": 0,
        "probability_models_refitted": 0,
        "predictions_per_model": len(records) * 2,
    }


def _effects(records: Sequence[dict], baseline_key: str, challenger_key: str) -> dict:
    baseline_errors = [
        frozen._celsius_error(
            float(row[baseline_key]) - float(row["outcome_native"]), row["native_unit"]
        )
        for row in records
    ]
    challenger_errors = [
        frozen._celsius_error(
            float(row[challenger_key]) - float(row["outcome_native"]), row["native_unit"]
        )
        for row in records
    ]
    return {
        "signed_error_difference_baseline_minus_challenger": float(
            np.mean(baseline_errors) - np.mean(challenger_errors)
        ),
        "mae_improvement": float(
            np.mean(np.abs(baseline_errors)) - np.mean(np.abs(challenger_errors))
        ),
        "squared_error_improvement": float(
            np.mean(np.square(baseline_errors)) - np.mean(np.square(challenger_errors))
        ),
    }


def _group_effects(records: Sequence[dict], key: str) -> dict:
    values = sorted({str(row[key]) for row in records})
    return {
        value: {
            "market_days": len(subset),
            "primary": _effects(
                subset,
                "temperature_residual_baseline_native",
                "eleven_field_residual_challenger_native",
            ),
            "all_leads_sensitivity": _effects(
                subset,
                "all_leads_temperature_residual_baseline_native",
                "all_leads_eleven_field_residual_challenger_native",
            ),
        }
        for value in values
        if (subset := [row for row in records if str(row[key]) == value])
    }


def evaluate_cohort(records: Sequence[dict], exclusions: Sequence[dict]) -> dict:
    if not records:
        raise IntegrityError("external cohort is empty")
    cohort_names = {row["cohort"] for row in records}
    if len(cohort_names) != 1:
        raise IntegrityError("provenance cohorts were pooled")
    cohort = next(iter(cohort_names))
    start, end = COHORTS[cohort]
    if any(not (start.isoformat() <= row["target_date"] <= end.isoformat()) for row in records):
        raise IntegrityError("external cohort crossed its provenance boundary")
    endpoints = frozen._endpoint_rows(records)
    bootstrap = frozen.crossed_bootstrap(
        endpoints, draws=frozen.BOOTSTRAP_DRAWS, seed=frozen.BOOTSTRAP_SEED
    )
    dates = sorted({row["target_date"] for row in records})
    markets = sorted({row["market"] for row in records})
    if markets != list(frozen.MARKETS):
        raise IntegrityError(f"external cohort omitted a market: {cohort}")
    cohort_exclusions = [
        item
        for item in exclusions
        if start.isoformat() <= item["target_date"] <= end.isoformat()
    ]
    expected = len(_date_range(start, end)) * len(frozen.MARKETS)
    if len(records) + len(cohort_exclusions) != expected:
        raise IntegrityError(f"external cohort matched-row accounting differs: {cohort}")
    evaluation = {
        "cohort": cohort,
        "support": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "admitted_dates": dates,
            "date_clusters": len(dates),
            "markets": markets,
            "market_days": len(records),
            "cohort_keys_sha256": frozen.canonical_sha256(
                [f"{EXTERNAL_YEAR}|{row['market']}|{row['target_date']}" for row in sorted(records, key=lambda item: (item["market"], item["target_date"]))]
            ),
        },
        "fleet_c_equivalent_metrics": {
            key: frozen._point_metrics(records, key) for key in PREDICTION_KEYS
        },
        "improvements": {
            "primary": _effects(
                records,
                "temperature_residual_baseline_native",
                "eleven_field_residual_challenger_native",
            ),
            "all_leads_sensitivity": _effects(
                records,
                "all_leads_temperature_residual_baseline_native",
                "all_leads_eleven_field_residual_challenger_native",
            ),
        },
        "per_market_native_metrics": frozen._native_market_metrics(records),
        "per_market_c_equivalent_effects": _group_effects(records, "market"),
        "per_month_c_equivalent_metrics": frozen._month_metrics(records),
        "per_month_c_equivalent_effects": _group_effects(records, "month"),
        "crossed_bootstrap": bootstrap,
        "market_contributions": frozen._market_contributions(records),
        "exclusions_and_missingness": {
            "expected_market_days": expected,
            "admitted_market_days": len(records),
            "excluded_for_wu_row_count_below_18": len(cohort_exclusions),
            "exclusions": cohort_exclusions,
            "missing_feature_rows": 0,
            "baseline_challenger_row_mismatch": 0,
            "precipitation_probability_feature_rows_used": 0,
            "markets_excluded": 0,
        },
        "integrity": {
            "cohort_boundary": "PASS",
            "native_units": "PASS",
            "matched_rows": "PASS",
            "no_imputation_change": "PASS",
            "no_market_exclusion": "PASS",
        },
    }
    return evaluation


def external_disposition(evaluations: Mapping[str, dict]) -> dict:
    signs = {}
    for cohort in COHORTS:
        endpoints = evaluations[cohort]["crossed_bootstrap"]["endpoints"]
        signs[f"{cohort}__primary"] = endpoints[
            "primary__squared_error_improvement"
        ]["point"]
        signs[f"{cohort}__all_leads_sensitivity"] = endpoints[
            "all_leads_sensitivity__squared_error_improvement"
        ]["point"]
    if all(value > 0 for value in signs.values()):
        disposition = "EXTERNAL_DIRECTION_CONSISTENT"
    elif all(value < 0 for value in signs.values()):
        disposition = "EXTERNAL_DIRECTION_ADVERSE"
    else:
        disposition = "EXTERNAL_DIRECTION_MIXED"
    return {
        "disposition": disposition,
        "mse_improvement_points": signs,
        "changes_original_verdict": False,
        "original_verdict": "INCONCLUSIVE_UNDERPOWERED",
        "can_authorize_distribution": False,
        "maximum_authorized_follow_up": (
            "prospective point-forecast shadow plan on genuinely new dates"
            if disposition == "EXTERNAL_DIRECTION_CONSISTENT"
            else "none"
        ),
    }


def _write_records(path: Path, records: Sequence[dict]) -> dict:
    if path.exists():
        raise IntegrityError(f"create-only external records already exist: {path}")
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RECORD_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "relative_path": path.name,
        "bytes": path.stat().st_size,
        "sha256": frozen.sha256_file(path),
        "rows": len(records),
    }


def _seal_attempt(output_root: Path, amendment_path: Path, commit_proof: dict) -> tuple[Path, dict]:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "external-evaluation-attempt.json"
    attempt = {
        "schema_version": ATTEMPT_SCHEMA,
        "status": "SEALED_BEFORE_2026_SOURCE_OUTCOME_ACCESS",
        "amendment_file_sha256": frozen.sha256_file(amendment_path),
        "amendment_commit": commit_proof,
        "cohorts": {
            key: {"start_date": value[0].isoformat(), "end_date": value[1].isoformat()}
            for key, value in COHORTS.items()
        },
        "model_refits_authorized": 0,
        "probability_model_refits_authorized": 0,
        "2025_outcome_access_authorized": 0,
        "rerun_authorized": False,
    }
    attempt["attempt_sha256"] = _self_hash(attempt, "attempt_sha256")
    _exclusive_json(path, attempt)
    return path, attempt


def run_evaluation(
    *, amendment_path: Path, artifact_root: Path, output_root: Path
) -> dict:
    amendment, _, bundles = _validate_amendment(amendment_path, artifact_root)
    commit_proof = _committed_amendment_proof(amendment_path)
    if output_root.exists():
        raise IntegrityError("external evaluation output root already exists")
    transfer_pre = verify_transfer(Path(amendment["input_binding"]["corpus_root"]))
    frozen_hashes_pre = {
        arm: frozen.sha256_file(artifact_root / (
            "temperature-residual-baseline.pkl" if arm == "temperature_residual_baseline" else "eleven-field-residual-challenger.pkl"
        ))
        for arm in FROZEN_MODEL_SHA256
    }
    surfaces, feature_audit = load_feature_surfaces(
        Path(amendment["input_binding"]["corpus_root"])
    )
    attempt_path, attempt = _seal_attempt(output_root, amendment_path, commit_proof)
    outcomes, outcome_audit = load_2026_outcomes(amendment)
    evaluations = {}
    record_artifacts = {}
    refit_audits = {}
    for cohort in COHORTS:
        records, refit_audit = _predict_records(
            surfaces=surfaces, outcomes=outcomes, bundles=bundles, cohort=cohort
        )
        record_artifacts[cohort] = _write_records(
            output_root / f"{cohort.replace('_', '-')}-records.csv", records
        )
        evaluations[cohort] = evaluate_cohort(records, outcome_audit["exclusions"])
        refit_audits[cohort] = refit_audit
    disposition = external_disposition(evaluations)
    transfer_post = verify_transfer(Path(amendment["input_binding"]["corpus_root"]))
    frozen_hashes_post = {
        arm: frozen.sha256_file(artifact_root / (
            "temperature-residual-baseline.pkl" if arm == "temperature_residual_baseline" else "eleven-field-residual-challenger.pkl"
        ))
        for arm in FROZEN_MODEL_SHA256
    }
    outcome_inventory_post = _current_outcome_inventory(amendment)
    if (
        transfer_pre["payload_inventory_sha256"] != transfer_post["payload_inventory_sha256"]
        or transfer_pre["csv_inventory_sha256"] != transfer_post["csv_inventory_sha256"]
        or frozen_hashes_pre != frozen_hashes_post
        or frozen_hashes_post != FROZEN_MODEL_SHA256
        or outcome_audit["source_inventory"]["file_inventory_sha256"]
        != outcome_inventory_post["file_inventory_sha256"]
    ):
        raise IntegrityError("external corpus/model/outcome source changed during evaluation")
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": "EXTERNAL_SECONDARY_2026_EVALUATION_COMPLETE",
        "disposition": disposition,
        "amendment": {
            "relative_path": commit_proof["relative_path"],
            "file_sha256": frozen.sha256_file(amendment_path),
            "amendment_sha256": amendment["amendment_sha256"],
            "commit_proof": commit_proof,
        },
        "terminal_attempt": {
            "relative_path": attempt_path.name,
            "file_sha256": frozen.sha256_file(attempt_path),
            "attempt_sha256": attempt["attempt_sha256"],
        },
        "frozen_identity": amendment["frozen_identity"],
        "feature_audit": feature_audit,
        "outcome_audit": outcome_audit,
        "record_artifacts": record_artifacts,
        "evaluations": evaluations,
        "no_refit_audit": {
            "cohorts": refit_audits,
            "models_refitted": 0,
            "probability_models_refitted": 0,
            "model_hashes_before": frozen_hashes_pre,
            "model_hashes_after": frozen_hashes_post,
        },
        "immutability_audit": {
            "transfer_pre_sha256": transfer_pre["transfer_sha256"],
            "transfer_post_sha256": transfer_post["transfer_sha256"],
            "payload_inventory_unchanged": True,
            "csv_inventory_unchanged": True,
            "model_artifacts_unchanged": True,
            "outcome_source_inventory_unchanged": True,
            "corpus_or_mirror_writes": 0,
        },
        "evidence_classification": {
            "2026_outcomes_previously_inspected_by_different_model_mission": True,
            "external_secondary": True,
            "replication": False,
            "confirmation": False,
            "can_change_original_verdict": False,
            "can_authorize_distribution": False,
        },
        "prohibited_actions_audit": {
            "provider_calls": 0,
            "model_refits": 0,
            "probability_model_refits": 0,
            "2025_outcome_value_accesses": 0,
            "pooled_cross_boundary_evaluations": 0,
            "market_data_reads": 0,
            "corpus_or_mirror_writes": 0,
            "production_scheduler_exchange_credential_accesses": 0,
            "release_distribution_promotion_candidate_alpha_confirmation_serving_actions": 0,
            "branch_merges": 0,
        },
    }
    result["result_sha256"] = _self_hash(result, "result_sha256")
    _exclusive_json(output_root / "result.json", result)
    return result


def _read_records(path: Path, expected_cohort: str) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RECORD_COLUMNS:
            raise IntegrityError("external evaluation-record column order differs")
        for row in reader:
            if row["cohort"] != expected_cohort:
                raise IntegrityError("external evaluation-record cohort differs")
            record = {
                "cohort": row["cohort"],
                "market": row["market"],
                "target_date": row["target_date"],
                "month": int(row["month"]),
                "native_unit": row["native_unit"],
                "outcome_native": int(row["outcome_native"]),
            }
            for key in PREDICTION_KEYS:
                record[key] = float(row[key])
            records.append(record)
    return records


def verify_result(
    *, amendment_path: Path, artifact_root: Path, output_root: Path
) -> dict:
    amendment, _, _ = _validate_amendment(amendment_path, artifact_root)
    result_path = output_root / "result.json"
    result = _load_json(result_path)
    if (
        result.get("schema_version") != RESULT_SCHEMA
        or result.get("result_sha256") != _self_hash(result, "result_sha256")
        or result.get("amendment", {}).get("amendment_sha256")
        != amendment["amendment_sha256"]
    ):
        raise IntegrityError("external result identity differs")
    attempt = _load_json(output_root / result["terminal_attempt"]["relative_path"])
    if (
        attempt.get("schema_version") != ATTEMPT_SCHEMA
        or attempt.get("attempt_sha256") != _self_hash(attempt, "attempt_sha256")
        or attempt.get("rerun_authorized") is not False
    ):
        raise IntegrityError("external attempt seal differs")
    reproduced = {}
    for cohort in COHORTS:
        record = result["record_artifacts"][cohort]
        path = output_root / record["relative_path"]
        if path.stat().st_size != record["bytes"] or frozen.sha256_file(path) != record["sha256"]:
            raise IntegrityError(f"external sealed records differ: {cohort}")
        rows = _read_records(path, cohort)
        reproduced[cohort] = evaluate_cohort(
            rows, result["outcome_audit"]["exclusions"]
        )
        if frozen.canonical_sha256(reproduced[cohort]) != frozen.canonical_sha256(
            result["evaluations"][cohort]
        ):
            raise IntegrityError(f"external deterministic reproduction differs: {cohort}")
    disposition = external_disposition(reproduced)
    if frozen.canonical_sha256(disposition) != frozen.canonical_sha256(result["disposition"]):
        raise IntegrityError("external disposition reproduction differs")
    verification = {
        "schema_version": VERIFICATION_SCHEMA,
        "status": "PASS",
        "result_file_sha256": frozen.sha256_file(result_path),
        "result_sha256": result["result_sha256"],
        "amendment_sha256": amendment["amendment_sha256"],
        "record_sha256": {
            cohort: result["record_artifacts"][cohort]["sha256"] for cohort in COHORTS
        },
        "reproduced_evaluation_sha256": {
            cohort: frozen.canonical_sha256(value) for cohort, value in reproduced.items()
        },
        "reproduced_disposition": disposition["disposition"],
        "bootstrap_reproduced": True,
        "source_outcomes_reopened": False,
        "outcome_value_access_2025": 0,
        "models_refitted": 0,
        "probability_models_refitted": 0,
        "cohorts_reproduced_separately": True,
    }
    verification["verification_sha256"] = _self_hash(
        verification, "verification_sha256"
    )
    return verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze-amendment")
    freeze.add_argument("--design", type=Path, required=True)
    freeze.add_argument("--artifact-root", type=Path, required=True)
    freeze.add_argument("--corpus-root", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--amendment", type=Path, required=True)
    evaluate.add_argument("--artifact-root", type=Path, required=True)
    evaluate.add_argument("--output-root", type=Path, required=True)

    verify = subparsers.add_parser("verify-result")
    verify.add_argument("--amendment", type=Path, required=True)
    verify.add_argument("--artifact-root", type=Path, required=True)
    verify.add_argument("--output-root", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "freeze-amendment":
        result = freeze_amendment(
            design_path=args.design,
            artifact_root=args.artifact_root,
            corpus_root=args.corpus_root,
            output=args.output,
        )
    elif args.command == "evaluate":
        result = run_evaluation(
            amendment_path=args.amendment,
            artifact_root=args.artifact_root,
            output_root=args.output_root,
        )
    else:
        result = verify_result(
            amendment_path=args.amendment,
            artifact_root=args.artifact_root,
            output_root=args.output_root,
        )
        _exclusive_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
