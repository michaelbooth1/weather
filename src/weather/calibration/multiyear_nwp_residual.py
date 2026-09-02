"""Research-only multi-year NWP residual information test.

This module has no provider, serving, release, promotion, Scheduler, market, or
exchange entry point.  Heavy commands are admitted only through
``scripts/ops/workstation_heavy.ps1``.  The P0 support scan hash-binds complete
Weather Underground daily-summary files while semantically reading only date,
unit, schema, and row-count fields; settlement values remain sealed until the
design is committed and the explicit fit/evaluate commands are run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import pickle
import stat
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from weather.sources.daily_summary import native_bucket
from weather.sources.previous_runs_research_collection import (
    RetainedArtifactError,
    payload_sha256,
    verify_final,
    verify_plan,
)


P0_SCHEMA = "multiyear_nwp_residual_p0_v1"
DESIGN_SCHEMA = "multiyear_nwp_residual_design_v1"
TRAINING_SCHEMA = "multiyear_nwp_residual_training_v1"
ATTEMPT_SCHEMA = "multiyear_nwp_residual_terminal_attempt_v1"
RESULT_SCHEMA = "multiyear_nwp_residual_result_v1"
VERIFICATION_SCHEMA = "multiyear_nwp_residual_result_verification_v1"

SOURCE_BRANCH = (
    "origin/codex/workstation-collect-multiyear-pit-research-2026-09-87a"
)
SOURCE_TIP = "3f3367b29fee69965935170b32f6cc3b45d3e33a"
SOURCE_TREE = "3b64e4afee3b3abfafb584aac3355adedcc1ed3c"
EXPECTED_PLAN_SHA256 = (
    "20b45f3c0d98a57170a66a237de865374309da67371805fc15204d00f354b09e"
)
EXPECTED_PLAN_FILE_SHA256 = (
    "924ddd2f1ca5a85def80dcee1296752df3df167f8a37d9ae7566a8c5f7ec303a"
)
EXPECTED_CORPUS_MANIFEST_SHA256 = (
    "d41bd21efb7a62396851fe016a215db1ac8bea7de97f387333902aba7a35bb00"
)
EXPECTED_RETAINED_FILES = 745
COMPLETE_DAY_MIN_ROWS = 18
TRAIN_YEAR = 2024
EVALUATION_YEAR = 2025
WINDOW_START = (5, 10)
WINDOW_END = (8, 31)
BOOTSTRAP_DRAWS = 20_000
BOOTSTRAP_SEED = 8_802_026
MODEL_SEED = 42

MARKETS = (
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
MARKET_STATIONS = {
    "atlanta": "katl",
    "austin": "kaus",
    "chicago": "kord",
    "dallas": "kdal",
    "denver": "kbkf",
    "houston": "khou",
    "los-angeles": "klax",
    "miami": "kmia",
    "nyc": "klga",
    "san-francisco": "ksfo",
    "seattle": "ksea",
    "toronto": "cyyz",
}
MARKET_UNITS = {market: ("C" if market == "toronto" else "F") for market in MARKETS}
SEGMENTS = ("may10-jun30", "jul01-aug31")
LEADS_PRIMARY = tuple(range(2, 8))
LEADS_SENSITIVITY = tuple(range(1, 8))

FIELDS = (
    "temperature_2m",
    "cloud_cover",
    "shortwave_radiation",
    "wind_speed_10m",
    "cape",
    "direct_radiation",
    "diffuse_radiation",
    "wind_gusts_10m",
    "precipitation",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)
EXCLUDED_FIELD = "precipitation_probability"
CSV_COLUMNS = (
    "market",
    "target_datetime_local",
    "field",
    "lead_days",
    "value",
    "unit",
    "issue_time_basis",
    "source",
)

SUMMARY_NAMES = (
    "temperature_2m_daily_max",
    "cloud_cover_09_18_mean",
    "shortwave_radiation_07_20_integral",
    "wind_speed_10m_07_20_mean",
    "wind_speed_10m_07_20_max",
    "cape_daily_max",
    "direct_radiation_07_20_integral",
    "diffuse_radiation_07_20_integral",
    "wind_gusts_10m_daily_max",
    "precipitation_daily_total",
    "vapour_pressure_deficit_07_20_max",
    "et0_fao_evapotranspiration_daily_total",
)
CHALLENGER_SUMMARIES = SUMMARY_NAMES[1:]
MARKET_FEATURES = tuple(f"market_identity__{market}" for market in MARKETS)
BASELINE_FEATURES = MARKET_FEATURES + (
    "day_of_year_sine",
    "day_of_year_cosine",
    "temperature_anchor",
    "temperature_daily_max_interlead_std",
    "temperature_daily_max_lead2_minus_lead7",
)
CHALLENGER_ADDITIONS = tuple(
    feature
    for summary in CHALLENGER_SUMMARIES
    for feature in (f"{summary}__median", f"{summary}__interlead_std")
)
CHALLENGER_FEATURES = BASELINE_FEATURES + CHALLENGER_ADDITIONS

MODEL_CONFIG = {
    "loss": "squared_error",
    "learning_rate": 0.05,
    "max_iter": 120,
    "max_leaf_nodes": 31,
    "max_depth": None,
    "min_samples_leaf": 20,
    "l2_regularization": 0.0,
    "max_bins": 255,
    "early_stopping": False,
    "random_state": MODEL_SEED,
}


class IntegrityError(RuntimeError):
    """Raised when an immutable research input or receipt differs."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def self_hash(value: Mapping[str, object], field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return canonical_sha256(unsigned)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise IntegrityError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    os.replace(temporary, path)


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(os.stat(path), "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def _acl_proof(path: Path) -> dict:
    script = (
        "$ErrorActionPreference='Stop';"
        "$acl=Get-Acl -LiteralPath $env:WEATHER_NWP_ACL_PATH;"
        "$rules=@($acl.Access | Where-Object {"
        "$_.IdentityReference.Value -like '*\\CodexSandboxOffline' -and "
        "$_.AccessControlType -eq 'Deny' -and -not $_.IsInherited});"
        "[pscustomobject]@{Owner=$acl.Owner;Protected=$acl.AreAccessRulesProtected;"
        "Rules=@($rules | ForEach-Object {"
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
        env={**os.environ, "WEATHER_NWP_ACL_PATH": str(path)},
    )
    if completed.returncode != 0:
        raise IntegrityError(f"ACL query failed for {path}: {completed.stderr.strip()}")
    proof = json.loads(completed.stdout.strip())
    rules = proof.get("Rules") or []
    if isinstance(rules, dict):
        rules = [rules]
    qualifying = []
    for rule in rules:
        rights = {
            part.strip().casefold()
            for part in str(rule.get("Rights", "")).split(",")
        }
        if (
            str(rule.get("Type", "")).casefold() == "deny"
            and rule.get("Inherited") is False
            and "write" in rights
            and "delete" in rights
            and "deletesubdirectoriesandfiles" in rights
        ):
            qualifying.append(rule)
    if not qualifying:
        raise IntegrityError(
            f"explicit CodexSandboxOffline deny Write/Delete ACL is absent: {path}"
        )
    return {
        "owner": proof.get("Owner"),
        "access_rules_protected": bool(proof.get("Protected")),
        "qualifying_rules": qualifying,
    }


def _in_window(value: date, year: int) -> bool:
    return date(year, *WINDOW_START) <= value <= date(year, *WINDOW_END)


def _outcome_paths(mirror_root: Path) -> dict[str, Path]:
    return {
        market: mirror_root
        / "wunderground"
        / MARKET_STATIONS[market]
        / "daily"
        / "daily_summary.csv"
        for market in MARKETS
    }


def _scan_outcome_support(mirror_root: Path) -> dict:
    """Hash files and inspect support columns without accessing outcome columns."""
    inventory = []
    support: dict[int, dict[str, list[str]]] = {
        TRAIN_YEAR: {},
        EVALUATION_YEAR: {},
    }
    support_columns = {
        "schema_version",
        "local_date",
        "temperature_unit",
        "row_count",
    }
    for market, path in _outcome_paths(mirror_root).items():
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or _is_reparse_point(resolved):
            raise IntegrityError(f"WU daily summary is absent or redirected: {resolved}")
        inventory.append(
            {
                "market": market,
                "station": MARKET_STATIONS[market],
                "relative_path": resolved.relative_to(mirror_root).as_posix(),
                "bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
        dates_by_year = {TRAIN_YEAR: [], EVALUATION_YEAR: []}
        with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header or not support_columns.issubset(header):
                raise IntegrityError(f"WU support columns are incomplete: {resolved}")
            positions = {name: header.index(name) for name in support_columns}
            for line_number, row in enumerate(reader, start=2):
                try:
                    local_date = date.fromisoformat(row[positions["local_date"]])
                except (IndexError, ValueError) as exc:
                    raise IntegrityError(
                        f"invalid WU support date at {resolved}:{line_number}: {exc}"
                    ) from None
                if local_date.year not in dates_by_year or not _in_window(
                    local_date, local_date.year
                ):
                    continue
                try:
                    row_count = int(row[positions["row_count"]])
                except (IndexError, ValueError):
                    continue
                unit = row[positions["temperature_unit"]].strip().upper()
                schema = row[positions["schema_version"]].strip()
                if (
                    row_count >= COMPLETE_DAY_MIN_ROWS
                    and unit == MARKET_UNITS[market]
                    and schema
                ):
                    dates_by_year[local_date.year].append(local_date.isoformat())
        for year in (TRAIN_YEAR, EVALUATION_YEAR):
            values = sorted(dates_by_year[year])
            if len(values) != len(set(values)):
                raise IntegrityError(f"duplicate WU support date: {market}/{year}")
            support[year][market] = values

    inventory = sorted(inventory, key=lambda item: item["market"])
    cohorts = {}
    for year in (TRAIN_YEAR, EVALUATION_YEAR):
        keys = sorted(
            f"{year}|{market}|{target_date}"
            for market in MARKETS
            for target_date in support[year][market]
        )
        date_clusters = sorted(
            {target_date for market in MARKETS for target_date in support[year][market]}
        )
        admitted_markets = [market for market in MARKETS if support[year][market]]
        cohorts[str(year)] = {
            "market_days": len(keys),
            "date_clusters": len(date_clusters),
            "markets": admitted_markets,
            "minimum_market_days": min(len(support[year][market]) for market in MARKETS),
            "maximum_market_days": max(len(support[year][market]) for market in MARKETS),
            "keys_sha256": canonical_sha256(keys),
            "dates_sha256": canonical_sha256(date_clusters),
            "support_by_market_sha256": canonical_sha256(support[year]),
        }
        if len(admitted_markets) != len(MARKETS) or len(date_clusters) < 100:
            raise IntegrityError(
                f"insufficient authoritative WU support for {year}: "
                f"dates={len(date_clusters)}, markets={len(admitted_markets)}"
            )
    return {
        "outcome_values_accessed": False,
        "support_columns_accessed": sorted(support_columns),
        "minimum_rows": COMPLETE_DAY_MIN_ROWS,
        "file_inventory": inventory,
        "file_inventory_sha256": canonical_sha256(inventory),
        "cohorts": cohorts,
        "support": {str(year): support[year] for year in support},
    }


def _validate_coverage_matrix(corpus_root: Path) -> dict:
    path = corpus_root / "final" / "coverage-matrix.csv"
    expected_fields = set(FIELDS) | {EXCLUDED_FIELD}
    exact_cells = 0
    precipitation_probability_2024_missing = 0
    years_seen: dict[int, set[tuple[str, str, int, int]]] = defaultdict(set)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            year = int(row["year"])
            if year not in (TRAIN_YEAR, EVALUATION_YEAR):
                continue
            market = row["market"]
            field = row["field"]
            lead = int(row["lead_days"])
            month = int(row["month"])
            requested = int(row["requested"])
            non_null = int(row["non_null"])
            missing = int(row["missing"])
            if (
                market not in MARKETS
                or field not in expected_fields
                or lead not in LEADS_SENSITIVITY
                or month not in (5, 6, 7, 8)
                or requested <= 0
            ):
                raise IntegrityError("2024/2025 coverage cell is outside the frozen scope")
            years_seen[year].add((market, field, lead, month))
            if field in FIELDS:
                if non_null != requested or missing != 0:
                    raise IntegrityError(
                        f"required field coverage is incomplete: {year}/{market}/{field}/{lead}/{month}"
                    )
                exact_cells += 1
            elif year == TRAIN_YEAR:
                if non_null != 0 or missing != requested:
                    raise IntegrityError(
                        "precipitation_probability unexpectedly exists in training year"
                    )
                precipitation_probability_2024_missing += 1
            elif non_null != requested or missing != 0:
                raise IntegrityError(
                    "precipitation_probability evaluation-year coverage differs"
                )
    expected_per_year = len(MARKETS) * len(expected_fields) * 7 * 4
    if any(len(years_seen[year]) != expected_per_year for year in years_seen):
        raise IntegrityError("2024/2025 field/market/lead/month matrix is incomplete")
    if set(years_seen) != {TRAIN_YEAR, EVALUATION_YEAR}:
        raise IntegrityError("2024/2025 coverage years are incomplete")
    return {
        "status": "PASS",
        "required_fields": list(FIELDS),
        "excluded_field": EXCLUDED_FIELD,
        "exact_complete_required_cells": exact_cells,
        "training_year_excluded_field_missing_cells": (
            precipitation_probability_2024_missing
        ),
        "leads": list(LEADS_SENSITIVITY),
        "markets": list(MARKETS),
        "months": [5, 6, 7, 8],
        "date_window": "May 10 through August 31 inclusive",
    }


def verify_p0(
    *, corpus_root: Path, mirror_root: Path, plan_path: Path, phase: str
) -> dict:
    if phase not in {"pre", "post"}:
        raise IntegrityError("P0 phase must be pre or post")
    corpus = corpus_root.resolve(strict=True)
    mirror = mirror_root.resolve(strict=True)
    if _is_reparse_point(corpus) or _is_reparse_point(mirror):
        raise IntegrityError("corpus and mirror roots must not be reparse points")
    corpus_acl_before = _acl_proof(corpus)
    mirror_acl_before = _acl_proof(mirror)

    plan_file_sha = sha256_file(plan_path)
    plan = _load_json(plan_path)
    verify_plan(plan)
    if plan.get("plan_sha256") != EXPECTED_PLAN_SHA256:
        raise IntegrityError("canonical plan SHA-256 differs")
    if plan_file_sha != EXPECTED_PLAN_FILE_SHA256:
        raise IntegrityError("plan file SHA-256 differs")
    if payload_sha256({key: value for key, value in plan.items() if key != "plan_sha256"}) != EXPECTED_PLAN_SHA256:
        raise IntegrityError("reproduced canonical plan SHA-256 differs")

    try:
        final = verify_final(corpus)
    except RetainedArtifactError as exc:
        raise IntegrityError(f"retained corpus integrity failed: {exc}") from exc
    if final.get("corpus_manifest_sha256") != EXPECTED_CORPUS_MANIFEST_SHA256:
        raise IntegrityError("corpus-manifest canonical SHA-256 differs")
    verification = _load_json(corpus / "final" / "final-verification.json")
    inventory = verification.get("retained_inventory") or []
    if len(inventory) != EXPECTED_RETAINED_FILES:
        raise IntegrityError(f"retained corpus file count differs: {len(inventory)}")
    if verification.get("raw_projection_plan_receipt_manifest_rehash") != "PASS":
        raise IntegrityError("terminal corpus rehash did not pass")

    coverage = _validate_coverage_matrix(corpus)
    outcome_support = _scan_outcome_support(mirror)
    corpus_acl_after = _acl_proof(corpus)
    mirror_acl_after = _acl_proof(mirror)
    if corpus_acl_before != corpus_acl_after or mirror_acl_before != mirror_acl_after:
        raise IntegrityError("corpus or mirror ACL changed during read-only verification")

    receipt = {
        "schema_version": P0_SCHEMA,
        "phase": phase,
        "status": "PASS",
        "source": {"branch": SOURCE_BRANCH, "tip": SOURCE_TIP, "tree": SOURCE_TREE},
        "plan": {
            "path": str(plan_path.resolve(strict=True)),
            "canonical_sha256": EXPECTED_PLAN_SHA256,
            "file_sha256": plan_file_sha,
        },
        "corpus": {
            "root": str(corpus),
            "manifest_canonical_sha256": final["corpus_manifest_sha256"],
            "manifest_file_sha256": final["corpus_manifest_file_sha256"],
            "final_verification_file_sha256": final[
                "final_verification_file_sha256"
            ],
            "retained_inventory_sha256": verification[
                "retained_inventory_sha256"
            ],
            "retained_file_count": len(inventory),
            "integrity_errors": final["integrity_errors"],
            "rehash": "PASS",
            "acl": corpus_acl_after,
        },
        "coverage": coverage,
        "outcome_support": outcome_support,
        "mirror": {"root": str(mirror), "acl": mirror_acl_after},
        "prohibited_actions": {
            "provider_calls": 0,
            "market_data_reads": 0,
            "2026_data_reads": 0,
            "outcome_values_accessed": False,
            "corpus_writes": 0,
            "mirror_writes": 0,
        },
    }
    receipt["p0_sha256"] = self_hash(receipt, "p0_sha256")
    return receipt


def _git_value(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return completed.stdout.strip()


def freeze_design(*, p0_path: Path) -> dict:
    p0 = _load_json(p0_path)
    if p0.get("schema_version") != P0_SCHEMA or p0.get("status") != "PASS":
        raise IntegrityError("P0 PASS receipt is absent")
    if p0.get("p0_sha256") != self_hash(p0, "p0_sha256"):
        raise IntegrityError("P0 receipt self-hash differs")
    if (
        p0.get("corpus", {}).get("manifest_canonical_sha256")
        != EXPECTED_CORPUS_MANIFEST_SHA256
    ):
        raise IntegrityError("P0 receipt binds the wrong corpus")
    module_path = Path(__file__).resolve(strict=True)
    design = {
        "schema_version": DESIGN_SCHEMA,
        "status": "FROZEN_BEFORE_2025_OUTCOME_ACCESS",
        "purpose": (
            "Research-only point-forecast information test of ten additional "
            "PIT-honest NWP fields against a temperature residual baseline."
        ),
        "source": {"branch": SOURCE_BRANCH, "tip": SOURCE_TIP, "tree": SOURCE_TREE},
        "implementation": {
            "harness_commit": _git_value("rev-parse", "HEAD"),
            "harness_tree": _git_value("rev-parse", "HEAD^{tree}"),
            "module_relative_path": "src/weather/calibration/multiyear_nwp_residual.py",
            "module_sha256": sha256_file(module_path),
        },
        "input_binding": {
            "p0_receipt": str(p0_path.resolve(strict=True)),
            "p0_receipt_file_sha256": sha256_file(p0_path),
            "p0_sha256": p0["p0_sha256"],
            "corpus_root": p0["corpus"]["root"],
            "corpus_manifest_canonical_sha256": EXPECTED_CORPUS_MANIFEST_SHA256,
            "corpus_manifest_file_sha256": p0["corpus"]["manifest_file_sha256"],
            "retained_inventory_sha256": p0["corpus"][
                "retained_inventory_sha256"
            ],
            "mirror_root": p0["mirror"]["root"],
            "outcome_support_file_inventory": p0["outcome_support"][
                "file_inventory"
            ],
            "outcome_support_file_inventory_sha256": p0["outcome_support"][
                "file_inventory_sha256"
            ],
        },
        "cohorts": {
            "training": {
                "year": TRAIN_YEAR,
                **p0["outcome_support"]["cohorts"][str(TRAIN_YEAR)],
            },
            "terminal_evaluation": {
                "year": EVALUATION_YEAR,
                **p0["outcome_support"]["cohorts"][str(EVALUATION_YEAR)],
            },
            "date_window": "May 10 through August 31 inclusive",
            "admission": (
                "WU daily-summary row in the market native unit with row_count "
                f">= {COMPLETE_DAY_MIN_ROWS}; exact PIT feature coverage"
            ),
            "outcome_support_by_year": p0["outcome_support"]["support"],
        },
        "target": {
            "value": "authoritative WU daily settlement high",
            "reader": "weather.sources.daily_summary.native_bucket",
            "unit": "each market's native settlement unit",
            "residual": "native settlement high minus primary forecast anchor",
        },
        "forecast_anchor": {
            "daily_value": "target-day maximum temperature_2m per lead",
            "primary": "median across leads 2-7",
            "sensitivity": "median across leads 1-7",
        },
        "features": {
            "included_fields_in_order": list(FIELDS),
            "excluded_field": EXCLUDED_FIELD,
            "excluded_reason": (
                "unavailable in 2024; forbidden as a holdout-only feature"
            ),
            "primary_leads": list(LEADS_PRIMARY),
            "sensitivity_leads": list(LEADS_SENSITIVITY),
            "baseline_feature_order": list(BASELINE_FEATURES),
            "challenger_feature_order": list(CHALLENGER_FEATURES),
            "daily_summaries": {
                "cloud_cover": "arithmetic mean over local hours 09:00-18:00 inclusive",
                "shortwave_radiation": "hourly integral over local hours 07:00-20:00 inclusive (Wh/m^2)",
                "wind_speed_10m": "arithmetic mean and maximum over local hours 07:00-20:00 inclusive",
                "cape": "target-day maximum",
                "direct_radiation": "hourly integral over local hours 07:00-20:00 inclusive (Wh/m^2)",
                "diffuse_radiation": "hourly integral over local hours 07:00-20:00 inclusive (Wh/m^2)",
                "wind_gusts_10m": "target-day maximum",
                "precipitation": "target-day total",
                "vapour_pressure_deficit": "maximum over local hours 07:00-20:00 inclusive",
                "et0_fao_evapotranspiration": "target-day total",
            },
            "across_lead_summaries": (
                "median and population standard deviation (ddof=0)"
            ),
            "day_of_year_period": 365.2425,
            "missingness": (
                "no imputation; fail on any missing/non-finite feature; both arms "
                "use the exact matched cohort"
            ),
        },
        "model": {
            "model_count": 2,
            "arms": ["temperature_residual_baseline", "eleven_field_residual_challenger"],
            "estimator": "sklearn.ensemble.HistGradientBoostingRegressor",
            "configuration": MODEL_CONFIG,
            "weights": "one row per admitted market-day, sample_weight=1.0",
            "target": "identical primary-anchor residual in both arms",
            "post_fit_constraints": "none in either arm",
            "hyperparameter_or_architecture_search": False,
        },
        "sensitivity": {
            "description": (
                "No-refit input-surface perturbation: recompute every lead-derived "
                "feature and anchor over leads 1-7, then apply the same two fitted "
                "estimators. No third or fourth model is fitted."
            )
        },
        "evaluation": {
            "terminal_year": EVALUATION_YEAR,
            "single_access": (
                "write immutable attempt seal before any 2025 outcome value is read; "
                "a retained seal forbids another source evaluation"
            ),
            "fleet_metrics": (
                "signed error, MAE, and mean squared error after converting each "
                "row's native-unit error to Celsius-equivalent"
            ),
            "native_metrics": "retain signed error, MAE, and mean squared error by market",
            "bootstrap": {
                "method": (
                    "shared-weight crossed target-date x market pigeonhole bootstrap"
                ),
                "draws": BOOTSTRAP_DRAWS,
                "seed": BOOTSTRAP_SEED,
                "interval": "percentile 95%",
                "power": "two-sided normal plug-in at alpha=0.05",
                "mde_80": "(z_0.975 + z_0.8) * crossed bootstrap standard error",
            },
            "positive_improvement": "baseline loss minus challenger loss",
            "maximum_market_contribution": (
                "maximum signed market sum of C-equivalent squared-error improvement "
                "divided by the positive fleet sum"
            ),
        },
        "decision": {
            "go": "GO_TO_DISTRIBUTION_CHALLENGER only when all six commissioned conditions pass",
            "conditions": [
                "primary squared-error improvement > 0 and crossed 95% lower bound > 0",
                "primary MAE improvement >= 0 and crossed 95% lower bound >= -0.02 C-equivalent",
                "leads-1-7 no-refit sensitivity squared-error improvement > 0",
                "maximum one-market contribution <= 0.35",
                "at least 100 date clusters and all 12 markets admitted",
                "outcome isolation, native-unit handling, and corpus parity pass",
            ],
            "no_go": (
                "NO_GO when primary squared-error harm or MAE harm is statistically "
                "established (the corresponding improvement upper 95% bound < 0)"
            ),
            "otherwise": "INCONCLUSIVE_UNDERPOWERED",
        },
        "prohibited_actions": [
            "provider call",
            "2026 data or outcome read",
            "market data read",
            "production or Scheduler access",
            "release, promotion, pointer, alpha, or confirmation-window action",
            "corpus or frozen-mirror mutation",
            "probability distribution, candidate, or serving integration",
        ],
    }
    design["design_sha256"] = self_hash(design, "design_sha256")
    return design


@dataclass
class _Accumulator:
    total: float = 0.0
    count: int = 0
    maximum: float | None = None

    def add(self, value: float) -> None:
        self.total += value
        self.count += 1
        if self.maximum is None or value > self.maximum:
            self.maximum = value


SUMMARY_EXPECTED_COUNTS = {
    "temperature_2m_daily_max": 24,
    "cloud_cover_09_18_mean": 10,
    "shortwave_radiation_07_20_integral": 14,
    "wind_speed_10m_07_20_mean": 14,
    "wind_speed_10m_07_20_max": 14,
    "cape_daily_max": 24,
    "direct_radiation_07_20_integral": 14,
    "diffuse_radiation_07_20_integral": 14,
    "wind_gusts_10m_daily_max": 24,
    "precipitation_daily_total": 24,
    "vapour_pressure_deficit_07_20_max": 14,
    "et0_fao_evapotranspiration_daily_total": 24,
}
SUMMARY_MODES = {
    "temperature_2m_daily_max": "max",
    "cloud_cover_09_18_mean": "mean",
    "shortwave_radiation_07_20_integral": "sum",
    "wind_speed_10m_07_20_mean": "mean",
    "wind_speed_10m_07_20_max": "max",
    "cape_daily_max": "max",
    "direct_radiation_07_20_integral": "sum",
    "diffuse_radiation_07_20_integral": "sum",
    "wind_gusts_10m_daily_max": "max",
    "precipitation_daily_total": "sum",
    "vapour_pressure_deficit_07_20_max": "max",
    "et0_fao_evapotranspiration_daily_total": "sum",
}


def _summary_targets(field: str, hour: int) -> tuple[str, ...]:
    if field == "temperature_2m":
        return ("temperature_2m_daily_max",)
    if field == "cloud_cover":
        return ("cloud_cover_09_18_mean",) if 9 <= hour <= 18 else ()
    if field == "shortwave_radiation":
        return ("shortwave_radiation_07_20_integral",) if 7 <= hour <= 20 else ()
    if field == "wind_speed_10m":
        return (
            ("wind_speed_10m_07_20_mean", "wind_speed_10m_07_20_max")
            if 7 <= hour <= 20
            else ()
        )
    if field == "cape":
        return ("cape_daily_max",)
    if field == "direct_radiation":
        return ("direct_radiation_07_20_integral",) if 7 <= hour <= 20 else ()
    if field == "diffuse_radiation":
        return ("diffuse_radiation_07_20_integral",) if 7 <= hour <= 20 else ()
    if field == "wind_gusts_10m":
        return ("wind_gusts_10m_daily_max",)
    if field == "precipitation":
        return ("precipitation_daily_total",)
    if field == "vapour_pressure_deficit":
        return (
            ("vapour_pressure_deficit_07_20_max",) if 7 <= hour <= 20 else ()
        )
    if field == "et0_fao_evapotranspiration":
        return ("et0_fao_evapotranspiration_daily_total",)
    raise IntegrityError(f"unrecognised included field: {field}")


def _finish_accumulator(name: str, accumulator: _Accumulator) -> float:
    expected = SUMMARY_EXPECTED_COUNTS[name]
    if accumulator.count != expected:
        raise IntegrityError(
            f"summary {name} has {accumulator.count} hourly values, expected {expected}"
        )
    mode = SUMMARY_MODES[name]
    if mode == "max":
        value = accumulator.maximum
    elif mode == "mean":
        value = accumulator.total / accumulator.count
    else:
        value = accumulator.total
    if value is None or not math.isfinite(value):
        raise IntegrityError(f"summary {name} is not finite")
    return float(value)


def load_feature_surfaces(corpus_root: Path, *, year: int) -> tuple[dict, dict]:
    if year not in (TRAIN_YEAR, EVALUATION_YEAR):
        raise IntegrityError("feature surface year is outside the frozen design")
    root = corpus_root.resolve(strict=True)
    accumulators: dict[tuple[str, str, int, str], _Accumulator] = {}
    source_files = []
    row_count = 0
    excluded_rows = 0
    for market in MARKETS:
        for segment in SEGMENTS:
            relative_path = (
                Path("units")
                / f"{market}--{year}--{segment}"
                / "completed"
                / "normalized.csv"
            )
            path = (root / relative_path).resolve(strict=True)
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise IntegrityError("feature payload escaped the corpus root") from exc
            source_files.append(
                {
                    "relative_path": relative_path.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = tuple(next(reader, ()))
                if header != CSV_COLUMNS:
                    raise IntegrityError(f"feature CSV header differs: {relative_path}")
                for line_number, row in enumerate(reader, start=2):
                    row_count += 1
                    if len(row) != len(CSV_COLUMNS) or row[0] != market:
                        raise IntegrityError(
                            f"feature row shape/market differs: {relative_path}:{line_number}"
                        )
                    field = row[2]
                    if field == EXCLUDED_FIELD:
                        excluded_rows += 1
                        continue
                    if field not in FIELDS:
                        raise IntegrityError(
                            f"unexpected feature field: {relative_path}:{line_number}"
                        )
                    try:
                        timestamp = datetime.fromisoformat(row[1])
                        lead = int(row[3])
                        value = float(row[4])
                    except ValueError as exc:
                        raise IntegrityError(
                            f"invalid feature value: {relative_path}:{line_number}: {exc}"
                        ) from None
                    if timestamp.year != year or lead not in LEADS_SENSITIVITY:
                        raise IntegrityError(
                            f"feature year/lead differs: {relative_path}:{line_number}"
                        )
                    if not math.isfinite(value):
                        raise IntegrityError(
                            f"missing/non-finite feature: {relative_path}:{line_number}"
                        )
                    if row[6] != "fixed_lead_day_offset" or row[7] != "open_meteo_previous_runs":
                        raise IntegrityError(
                            f"non-PIT feature provenance: {relative_path}:{line_number}"
                        )
                    for summary in _summary_targets(field, timestamp.hour):
                        key = (market, timestamp.date().isoformat(), lead, summary)
                        accumulators.setdefault(key, _Accumulator()).add(value)

    surfaces: dict[tuple[str, str], dict[int, dict[str, float]]] = defaultdict(dict)
    for market in MARKETS:
        cursor = date(year, *WINDOW_START)
        end = date(year, *WINDOW_END)
        while cursor <= end:
            target_date = cursor.isoformat()
            for lead in LEADS_SENSITIVITY:
                summaries = {}
                for name in SUMMARY_NAMES:
                    key = (market, target_date, lead, name)
                    if key not in accumulators:
                        raise IntegrityError(f"feature summary is absent: {key}")
                    summaries[name] = _finish_accumulator(name, accumulators[key])
                surfaces[(market, target_date)][lead] = summaries
            cursor = date.fromordinal(cursor.toordinal() + 1)
    expected_market_days = len(MARKETS) * 114
    if len(surfaces) != expected_market_days:
        raise IntegrityError(
            f"feature market-day count differs: {len(surfaces)} != {expected_market_days}"
        )
    audit = {
        "year": year,
        "source_file_count": len(source_files),
        "source_files_sha256": canonical_sha256(source_files),
        "source_files": source_files,
        "input_rows": row_count,
        "excluded_precipitation_probability_rows": excluded_rows,
        "market_days": len(surfaces),
        "feature_surface_sha256": canonical_sha256(
            [
                {
                    "market": key[0],
                    "target_date": key[1],
                    "leads": surfaces[key],
                }
                for key in sorted(surfaces)
            ]
        ),
    }
    return dict(surfaces), audit


def _across_leads(values: Sequence[float]) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    if array.size == 0 or not np.isfinite(array).all():
        raise IntegrityError("lead summary is empty or non-finite")
    return float(np.median(array)), float(np.std(array, ddof=0))


def feature_vector(
    *, market: str, target_date: str, leads: Mapping[int, Mapping[str, float]], selected_leads: Sequence[int], challenger: bool
) -> tuple[list[float], float]:
    selected = tuple(int(value) for value in selected_leads)
    if selected not in (LEADS_PRIMARY, LEADS_SENSITIVITY):
        raise IntegrityError("lead surface is outside the frozen design")
    if set(leads) != set(LEADS_SENSITIVITY):
        raise IntegrityError("daily surface does not contain exactly leads 1-7")
    temperature = [leads[lead]["temperature_2m_daily_max"] for lead in selected]
    anchor, temperature_std = _across_leads(temperature)
    parsed_date = date.fromisoformat(target_date)
    angle = 2.0 * math.pi * (parsed_date.timetuple().tm_yday - 1) / 365.2425
    vector = [1.0 if candidate == market else 0.0 for candidate in MARKETS]
    vector.extend(
        [
            math.sin(angle),
            math.cos(angle),
            anchor,
            temperature_std,
            leads[2]["temperature_2m_daily_max"]
            - leads[7]["temperature_2m_daily_max"],
        ]
    )
    if challenger:
        for summary in CHALLENGER_SUMMARIES:
            median, standard_deviation = _across_leads(
                [leads[lead][summary] for lead in selected]
            )
            vector.extend([median, standard_deviation])
    expected = CHALLENGER_FEATURES if challenger else BASELINE_FEATURES
    if len(vector) != len(expected) or not np.isfinite(vector).all():
        raise IntegrityError("feature vector shape or finiteness differs")
    return [float(value) for value in vector], anchor


def _validate_design(design_path: Path) -> dict:
    design = _load_json(design_path)
    if design.get("schema_version") != DESIGN_SCHEMA:
        raise IntegrityError("design schema differs")
    if design.get("design_sha256") != self_hash(design, "design_sha256"):
        raise IntegrityError("design self-hash differs")
    if design.get("status") != "FROZEN_BEFORE_2025_OUTCOME_ACCESS":
        raise IntegrityError("design is not frozen before terminal outcomes")
    if design.get("source") != {
        "branch": SOURCE_BRANCH,
        "tip": SOURCE_TIP,
        "tree": SOURCE_TREE,
    }:
        raise IntegrityError("design source binding differs")
    implementation = design.get("implementation") or {}
    if sha256_file(Path(__file__).resolve(strict=True)) != implementation.get(
        "module_sha256"
    ):
        raise IntegrityError("frozen harness module hash differs")
    features = design.get("features") or {}
    if (
        tuple(features.get("included_fields_in_order") or ()) != FIELDS
        or features.get("excluded_field") != EXCLUDED_FIELD
        or tuple(features.get("baseline_feature_order") or ()) != BASELINE_FEATURES
        or tuple(features.get("challenger_feature_order") or ())
        != CHALLENGER_FEATURES
    ):
        raise IntegrityError("frozen field or feature order differs")
    model = design.get("model") or {}
    if model.get("model_count") != 2 or model.get("configuration") != MODEL_CONFIG:
        raise IntegrityError("frozen model count/configuration differs")
    inference = design.get("evaluation", {}).get("bootstrap", {})
    if inference.get("draws") != BOOTSTRAP_DRAWS or inference.get("seed") != BOOTSTRAP_SEED:
        raise IntegrityError("frozen bootstrap design differs")
    p0_path = Path(design["input_binding"]["p0_receipt"])
    if sha256_file(p0_path) != design["input_binding"]["p0_receipt_file_sha256"]:
        raise IntegrityError("P0 receipt file drifted after design freeze")
    p0 = _load_json(p0_path)
    if p0.get("p0_sha256") != design["input_binding"]["p0_sha256"]:
        raise IntegrityError("P0 receipt binding differs")
    return design


def _cohort_keys(design: dict, cohort: str) -> list[tuple[str, str]]:
    year = int(design["cohorts"][cohort]["year"])
    support = design["cohorts"]["outcome_support_by_year"][str(year)]
    keys = sorted(
        (market, target_date)
        for market in MARKETS
        for target_date in support[market]
    )
    encoded = [f"{year}|{market}|{target_date}" for market, target_date in keys]
    if canonical_sha256(encoded) != design["cohorts"][cohort]["keys_sha256"]:
        raise IntegrityError(f"{cohort} cohort key hash differs")
    return keys


def _outcome_inventory_map(design: dict) -> dict[str, dict]:
    records = design["input_binding"]["outcome_support_file_inventory"]
    if canonical_sha256(records) != design["input_binding"][
        "outcome_support_file_inventory_sha256"
    ]:
        raise IntegrityError("outcome support inventory self-hash differs")
    return {record["market"]: record for record in records}


def load_outcome_values(
    design: dict, *, year: int, cohort: str
) -> tuple[dict[tuple[str, str], int], dict]:
    if year not in (TRAIN_YEAR, EVALUATION_YEAR):
        raise IntegrityError("outcome year is outside the frozen design")
    expected_cohort = "training" if year == TRAIN_YEAR else "terminal_evaluation"
    if cohort != expected_cohort:
        raise IntegrityError("outcome cohort/year isolation differs")
    mirror = Path(design["input_binding"]["mirror_root"]).resolve(strict=True)
    inventory = _outcome_inventory_map(design)
    paths = _outcome_paths(mirror)
    for market, path in paths.items():
        record = inventory[market]
        if (
            path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise IntegrityError(f"outcome source drifted before access: {market}")
    required = set(_cohort_keys(design, cohort))
    outcomes: dict[tuple[str, str], int] = {}
    for market, path in paths.items():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for line_number, row in enumerate(csv.DictReader(handle), start=2):
                raw_date = row.get("local_date") or ""
                try:
                    local_date = date.fromisoformat(raw_date)
                except ValueError:
                    continue
                key = (market, raw_date)
                if local_date.year != year or key not in required:
                    continue
                if (
                    int(row.get("row_count") or 0) < COMPLETE_DAY_MIN_ROWS
                    or str(row.get("temperature_unit") or "").upper()
                    != MARKET_UNITS[market]
                ):
                    raise IntegrityError(
                        f"outcome support changed at {market}:{line_number}"
                    )
                outcome = native_bucket(row)
                if outcome is None:
                    raise IntegrityError(
                        f"authoritative native outcome is absent at {market}:{line_number}"
                    )
                if key in outcomes:
                    raise IntegrityError(f"duplicate authoritative outcome: {key}")
                outcomes[key] = int(outcome)
    if set(outcomes) != required:
        missing = sorted(required - set(outcomes))
        raise IntegrityError(f"authoritative outcome cohort differs: {missing[:3]}")
    return outcomes, {
        "year": year,
        "market_days": len(outcomes),
        "keys_sha256": canonical_sha256(
            [f"{year}|{market}|{target_date}" for market, target_date in sorted(outcomes)]
        ),
        "source_file_inventory_sha256": design["input_binding"][
            "outcome_support_file_inventory_sha256"
        ],
        "native_units": MARKET_UNITS,
    }


def _new_estimator() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(**MODEL_CONFIG)


def _celsius_error(error_native: float, unit: str) -> float:
    if unit == "C":
        return float(error_native)
    if unit == "F":
        return float(error_native) * 5.0 / 9.0
    raise IntegrityError(f"unexpected native unit: {unit}")


def _prediction_rows(
    *, design: dict, year: int, surfaces: dict, outcomes: dict
) -> tuple[list[dict], np.ndarray, np.ndarray, np.ndarray]:
    cohort = "training" if year == TRAIN_YEAR else "terminal_evaluation"
    keys = _cohort_keys(design, cohort)
    records = []
    baseline_matrix = []
    challenger_matrix = []
    residual_target = []
    for market, target_date in keys:
        surface = surfaces.get((market, target_date))
        if surface is None or (market, target_date) not in outcomes:
            raise IntegrityError(f"matched feature/outcome row is absent: {market}/{target_date}")
        baseline, anchor = feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=LEADS_PRIMARY,
            challenger=False,
        )
        challenger, challenger_anchor = feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=LEADS_PRIMARY,
            challenger=True,
        )
        if anchor != challenger_anchor:
            raise IntegrityError("baseline/challenger anchors differ")
        outcome = outcomes[(market, target_date)]
        records.append(
            {
                "market": market,
                "target_date": target_date,
                "month": int(target_date[5:7]),
                "native_unit": MARKET_UNITS[market],
                "outcome_native": outcome,
                "primary_anchor_native": anchor,
            }
        )
        baseline_matrix.append(baseline)
        challenger_matrix.append(challenger)
        residual_target.append(outcome - anchor)
    baseline_array = np.asarray(baseline_matrix, dtype=float)
    challenger_array = np.asarray(challenger_matrix, dtype=float)
    target_array = np.asarray(residual_target, dtype=float)
    if (
        baseline_array.shape != (len(keys), len(BASELINE_FEATURES))
        or challenger_array.shape != (len(keys), len(CHALLENGER_FEATURES))
        or target_array.shape != (len(keys),)
        or not np.isfinite(baseline_array).all()
        or not np.isfinite(challenger_array).all()
        or not np.isfinite(target_array).all()
    ):
        raise IntegrityError("matched training/evaluation matrices differ")
    return records, baseline_array, challenger_array, target_array


def _model_artifact(
    *, model: HistGradientBoostingRegressor, arm: str, feature_order: Sequence[str], design: dict
) -> tuple[bytes, dict]:
    payload = {
        "artifact_version": "multiyear_nwp_residual_model_v1",
        "arm": arm,
        "design_sha256": design["design_sha256"],
        "feature_order": list(feature_order),
        "estimator_configuration": MODEL_CONFIG,
        "estimator": model,
    }
    first = pickle.dumps(payload, protocol=5)
    second = pickle.dumps(payload, protocol=5)
    if first != second:
        raise IntegrityError(f"model serialization is not deterministic: {arm}")
    return first, payload


def _simple_metrics(records: Sequence[dict], prediction_key: str) -> dict:
    errors_native = [
        float(row[prediction_key]) - float(row["outcome_native"]) for row in records
    ]
    errors_c = [
        _celsius_error(error, row["native_unit"])
        for error, row in zip(errors_native, records)
    ]
    return {
        "signed_error_c_equivalent": float(np.mean(errors_c)),
        "mae_c_equivalent": float(np.mean(np.abs(errors_c))),
        "squared_error_c_equivalent": float(np.mean(np.square(errors_c))),
    }


def fit_models(
    *, design_path: Path, artifact_root: Path
) -> dict:
    design = _validate_design(design_path)
    if artifact_root.exists():
        raise IntegrityError(f"training artifact root already exists: {artifact_root}")
    corpus_root = Path(design["input_binding"]["corpus_root"])
    surfaces, feature_audit = load_feature_surfaces(corpus_root, year=TRAIN_YEAR)
    outcomes, outcome_audit = load_outcome_values(
        design, year=TRAIN_YEAR, cohort="training"
    )
    records, baseline_x, challenger_x, residual_y = _prediction_rows(
        design=design,
        year=TRAIN_YEAR,
        surfaces=surfaces,
        outcomes=outcomes,
    )
    sample_weight = np.ones(len(records), dtype=float)
    baseline_model = _new_estimator()
    challenger_model = _new_estimator()
    baseline_model.fit(baseline_x, residual_y, sample_weight=sample_weight)
    challenger_model.fit(challenger_x, residual_y, sample_weight=sample_weight)
    baseline_residual = baseline_model.predict(baseline_x)
    challenger_residual = challenger_model.predict(challenger_x)
    for index, row in enumerate(records):
        row["temperature_residual_baseline_native"] = float(
            row["primary_anchor_native"] + baseline_residual[index]
        )
        row["eleven_field_residual_challenger_native"] = float(
            row["primary_anchor_native"] + challenger_residual[index]
        )

    stage = artifact_root.with_name(artifact_root.name + ".publishing")
    if stage.exists():
        raise IntegrityError(f"training publishing root already exists: {stage}")
    stage.mkdir(parents=True)
    artifacts = []
    for model, arm, order, filename in (
        (
            baseline_model,
            "temperature_residual_baseline",
            BASELINE_FEATURES,
            "temperature-residual-baseline.pkl",
        ),
        (
            challenger_model,
            "eleven_field_residual_challenger",
            CHALLENGER_FEATURES,
            "eleven-field-residual-challenger.pkl",
        ),
    ):
        model_bytes, _ = _model_artifact(
            model=model, arm=arm, feature_order=order, design=design
        )
        path = stage / filename
        write_bytes(path, model_bytes)
        artifacts.append(
            {
                "arm": arm,
                "relative_path": filename,
                "bytes": len(model_bytes),
                "sha256": hashlib.sha256(model_bytes).hexdigest(),
            }
        )

    record_columns = (
        "market",
        "target_date",
        "month",
        "native_unit",
        "outcome_native",
        "primary_anchor_native",
        "temperature_residual_baseline_native",
        "eleven_field_residual_challenger_native",
    )
    records_path = stage / "training-records.csv"
    with records_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=record_columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    records_record = {
        "relative_path": records_path.name,
        "bytes": records_path.stat().st_size,
        "sha256": sha256_file(records_path),
    }
    receipt = {
        "schema_version": TRAINING_SCHEMA,
        "status": "PASS",
        "design_file_sha256": sha256_file(design_path),
        "design_sha256": design["design_sha256"],
        "year": TRAIN_YEAR,
        "models_fitted": 2,
        "model_configuration": MODEL_CONFIG,
        "sample_weight": "1.0 per market-day",
        "matched_market_days": len(records),
        "date_clusters": len({row["target_date"] for row in records}),
        "markets": sorted({row["market"] for row in records}),
        "cohort_keys_sha256": design["cohorts"]["training"]["keys_sha256"],
        "feature_audit": feature_audit,
        "outcome_audit": outcome_audit,
        "feature_orders": {
            "temperature_residual_baseline": list(BASELINE_FEATURES),
            "eleven_field_residual_challenger": list(CHALLENGER_FEATURES),
        },
        "artifacts": artifacts,
        "training_records": records_record,
        "training_metrics": {
            "raw_temperature_anchor": _simple_metrics(records, "primary_anchor_native"),
            "temperature_residual_baseline": _simple_metrics(
                records, "temperature_residual_baseline_native"
            ),
            "eleven_field_residual_challenger": _simple_metrics(
                records, "eleven_field_residual_challenger_native"
            ),
        },
        "terminal_evaluation_outcomes_accessed": False,
        "provider_or_market_data_accessed": False,
    }
    receipt["training_sha256"] = self_hash(receipt, "training_sha256")
    write_json(stage / "training-receipt.json", receipt)
    os.replace(stage, artifact_root)
    return receipt


def _load_model_bundle(path: Path, record: dict, design: dict) -> dict:
    if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
        raise IntegrityError(f"model artifact differs: {path}")
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if (
        payload.get("artifact_version") != "multiyear_nwp_residual_model_v1"
        or payload.get("arm") != record["arm"]
        or payload.get("design_sha256") != design["design_sha256"]
        or payload.get("estimator_configuration") != MODEL_CONFIG
    ):
        raise IntegrityError(f"model artifact contract differs: {path}")
    expected_order = (
        BASELINE_FEATURES
        if record["arm"] == "temperature_residual_baseline"
        else CHALLENGER_FEATURES
    )
    if tuple(payload.get("feature_order") or ()) != expected_order:
        raise IntegrityError(f"model feature order differs: {path}")
    return payload


def load_training(
    *, design: dict, artifact_root: Path
) -> tuple[dict, dict[str, dict]]:
    receipt_path = artifact_root / "training-receipt.json"
    receipt = _load_json(receipt_path)
    if (
        receipt.get("schema_version") != TRAINING_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("training_sha256") != self_hash(receipt, "training_sha256")
        or receipt.get("design_sha256") != design["design_sha256"]
        or receipt.get("models_fitted") != 2
    ):
        raise IntegrityError("training receipt contract differs")
    bundles = {}
    for record in receipt["artifacts"]:
        bundles[record["arm"]] = _load_model_bundle(
            artifact_root / record["relative_path"], record, design
        )
    if set(bundles) != {
        "temperature_residual_baseline",
        "eleven_field_residual_challenger",
    }:
        raise IntegrityError("training receipt does not bind exactly two models")
    return receipt, bundles


PREDICTION_KEYS = (
    "raw_temperature_anchor_native",
    "temperature_residual_baseline_native",
    "eleven_field_residual_challenger_native",
    "all_leads_raw_temperature_anchor_native",
    "all_leads_temperature_residual_baseline_native",
    "all_leads_eleven_field_residual_challenger_native",
)


def _exclusive_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode(
        "utf-8"
    ) + b"\n"
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _seal_terminal_attempt(
    *, terminal_root: Path, design: dict, training: dict
) -> tuple[Path, dict]:
    path = terminal_root / "terminal-evaluation-attempt.json"
    attempt = {
        "schema_version": ATTEMPT_SCHEMA,
        "status": "SEALED_BEFORE_2025_OUTCOME_ACCESS",
        "design_sha256": design["design_sha256"],
        "training_sha256": training["training_sha256"],
        "evaluation_year": EVALUATION_YEAR,
        "outcome_source_accesses_authorized": 1,
        "rerun_authorized": False,
    }
    attempt["attempt_sha256"] = self_hash(attempt, "attempt_sha256")
    try:
        _exclusive_json(path, attempt)
    except FileExistsError as exc:
        raise IntegrityError(
            "terminal evaluation attempt is already sealed; a second source read is forbidden"
        ) from exc
    return path, attempt


def _evaluation_predictions(
    *, design: dict, surfaces: dict, outcomes: dict, bundles: dict[str, dict]
) -> list[dict]:
    base_records, baseline_x, challenger_x, _ = _prediction_rows(
        design=design,
        year=EVALUATION_YEAR,
        surfaces=surfaces,
        outcomes=outcomes,
    )
    baseline_model = bundles["temperature_residual_baseline"]["estimator"]
    challenger_model = bundles["eleven_field_residual_challenger"]["estimator"]
    primary_baseline_residuals = baseline_model.predict(baseline_x)
    primary_challenger_residuals = challenger_model.predict(challenger_x)

    sensitivity_baseline_x = []
    sensitivity_challenger_x = []
    sensitivity_anchors = []
    for row in base_records:
        market = row["market"]
        target_date = row["target_date"]
        surface = surfaces[(market, target_date)]
        baseline, anchor = feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=LEADS_SENSITIVITY,
            challenger=False,
        )
        challenger, challenger_anchor = feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=LEADS_SENSITIVITY,
            challenger=True,
        )
        if anchor != challenger_anchor:
            raise IntegrityError("sensitivity baseline/challenger anchors differ")
        sensitivity_baseline_x.append(baseline)
        sensitivity_challenger_x.append(challenger)
        sensitivity_anchors.append(anchor)
    sensitivity_baseline_residuals = baseline_model.predict(
        np.asarray(sensitivity_baseline_x, dtype=float)
    )
    sensitivity_challenger_residuals = challenger_model.predict(
        np.asarray(sensitivity_challenger_x, dtype=float)
    )
    for index, row in enumerate(base_records):
        primary_anchor = float(row.pop("primary_anchor_native"))
        sensitivity_anchor = float(sensitivity_anchors[index])
        row.update(
            {
                "raw_temperature_anchor_native": primary_anchor,
                "temperature_residual_baseline_native": float(
                    primary_anchor + primary_baseline_residuals[index]
                ),
                "eleven_field_residual_challenger_native": float(
                    primary_anchor + primary_challenger_residuals[index]
                ),
                "all_leads_raw_temperature_anchor_native": sensitivity_anchor,
                "all_leads_temperature_residual_baseline_native": float(
                    sensitivity_anchor + sensitivity_baseline_residuals[index]
                ),
                "all_leads_eleven_field_residual_challenger_native": float(
                    sensitivity_anchor + sensitivity_challenger_residuals[index]
                ),
            }
        )
    return base_records


def _endpoint_rows(records: Sequence[dict]) -> dict[str, list[tuple[str, str, float]]]:
    endpoints: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for row in records:
        errors_c = {
            key: _celsius_error(
                float(row[key]) - float(row["outcome_native"]), row["native_unit"]
            )
            for key in PREDICTION_KEYS
        }
        for key, error in errors_c.items():
            endpoints[f"{key}__signed_error"].append(
                (row["target_date"], row["market"], error)
            )
            endpoints[f"{key}__mae"].append(
                (row["target_date"], row["market"], abs(error))
            )
            endpoints[f"{key}__squared_error"].append(
                (row["target_date"], row["market"], error * error)
            )
        for prefix, baseline_key, challenger_key in (
            (
                "primary",
                "temperature_residual_baseline_native",
                "eleven_field_residual_challenger_native",
            ),
            (
                "all_leads_sensitivity",
                "all_leads_temperature_residual_baseline_native",
                "all_leads_eleven_field_residual_challenger_native",
            ),
        ):
            baseline_error = errors_c[baseline_key]
            challenger_error = errors_c[challenger_key]
            endpoints[f"{prefix}__mae_improvement"].append(
                (
                    row["target_date"],
                    row["market"],
                    abs(baseline_error) - abs(challenger_error),
                )
            )
            endpoints[f"{prefix}__squared_error_improvement"].append(
                (
                    row["target_date"],
                    row["market"],
                    baseline_error * baseline_error
                    - challenger_error * challenger_error,
                )
            )
    return dict(endpoints)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def crossed_bootstrap(
    endpoints: Mapping[str, Sequence[tuple[str, str, float]]],
    *,
    draws: int,
    seed: int,
) -> dict:
    names = sorted(endpoints)
    if not names or draws < 1:
        raise IntegrityError("crossed bootstrap endpoint/draw contract is empty")
    reference_keys = {
        (target_date, market) for target_date, market, _ in endpoints[names[0]]
    }
    for name in names:
        keys = {(target_date, market) for target_date, market, _ in endpoints[name]}
        if keys != reference_keys or len(keys) != len(endpoints[name]):
            raise IntegrityError("bootstrap endpoints are not exactly matched")
    dates = sorted({key[0] for key in reference_keys})
    markets = sorted({key[1] for key in reference_keys})
    date_index = {value: index for index, value in enumerate(dates)}
    market_index = {value: index for index, value in enumerate(markets)}
    values = np.zeros((len(names), len(dates), len(markets)), dtype=float)
    support = np.zeros((len(dates), len(markets)), dtype=float)
    for endpoint_index, name in enumerate(names):
        for target_date, market, value in endpoints[name]:
            row = date_index[target_date]
            column = market_index[market]
            values[endpoint_index, row, column] = float(value)
            if endpoint_index == 0:
                support[row, column] = 1.0
    points = values.sum(axis=(1, 2)) / support.sum()
    rng = np.random.default_rng(seed)
    output = np.empty((draws, len(names)), dtype=float)
    date_probability = np.full(len(dates), 1.0 / len(dates))
    market_probability = np.full(len(markets), 1.0 / len(markets))
    for start in range(0, draws, 1000):
        count = min(1000, draws - start)
        date_weights = rng.multinomial(len(dates), date_probability, size=count)
        market_weights = rng.multinomial(
            len(markets), market_probability, size=count
        )
        numerator = np.einsum(
            "bi,eij,bj->be", date_weights, values, market_weights
        )
        denominator = np.einsum(
            "bi,ij,bj->b", date_weights, support, market_weights
        )
        if np.any(denominator <= 0):
            raise IntegrityError("crossed bootstrap produced an empty draw")
        output[start : start + count] = numerator / denominator[:, None]
    summaries = {}
    for index, name in enumerate(names):
        samples = output[:, index]
        standard_error = float(np.std(samples, ddof=1))
        point = float(points[index])
        lower, upper = (
            float(value) for value in np.quantile(samples, [0.025, 0.975])
        )
        if standard_error == 0.0:
            power = 1.0 if point != 0.0 else 0.05
        else:
            noncentrality = abs(point) / standard_error
            power = _normal_cdf(-1.959963984540054 - noncentrality) + 1.0 - _normal_cdf(
                1.959963984540054 - noncentrality
            )
        summaries[name] = {
            "point": point,
            "lower_95": lower,
            "upper_95": upper,
            "standard_error": standard_error,
            "achieved_power": float(power),
            "mde_80": float(
                (1.959963984540054 + 0.8416212335729143) * standard_error
            ),
        }
    return {
        "method": "shared-weight crossed target-date x market pigeonhole bootstrap",
        "draws": draws,
        "seed": seed,
        "date_clusters": len(dates),
        "market_clusters": len(markets),
        "effective_cluster_cells": int(support.sum()),
        "draw_matrix_sha256": hashlib.sha256(
            output.astype("<f8", copy=False).tobytes(order="C")
        ).hexdigest(),
        "endpoints": summaries,
    }


def _point_metrics(records: Sequence[dict], prediction_key: str) -> dict:
    return _simple_metrics(records, prediction_key)


def _native_market_metrics(records: Sequence[dict]) -> dict:
    result = {}
    for market in MARKETS:
        subset = [row for row in records if row["market"] == market]
        result[market] = {
            "unit": MARKET_UNITS[market],
            "market_days": len(subset),
            "models": {
                key: {
                    "signed_error": float(
                        np.mean(
                            [
                                float(row[key]) - float(row["outcome_native"])
                                for row in subset
                            ]
                        )
                    ),
                    "mae": float(
                        np.mean(
                            [
                                abs(float(row[key]) - float(row["outcome_native"]))
                                for row in subset
                            ]
                        )
                    ),
                    "squared_error": float(
                        np.mean(
                            [
                                (
                                    float(row[key])
                                    - float(row["outcome_native"])
                                )
                                ** 2
                                for row in subset
                            ]
                        )
                    ),
                }
                for key in PREDICTION_KEYS
            },
        }
    return result


def _month_metrics(records: Sequence[dict]) -> dict:
    return {
        str(month): {
            "market_days": len(subset),
            "models": {key: _point_metrics(subset, key) for key in PREDICTION_KEYS},
        }
        for month in (5, 6, 7, 8)
        if (subset := [row for row in records if int(row["month"]) == month])
    }


def _market_contributions(records: Sequence[dict]) -> dict:
    sums = {}
    for market in MARKETS:
        total = 0.0
        for row in records:
            if row["market"] != market:
                continue
            baseline = _celsius_error(
                float(row["temperature_residual_baseline_native"])
                - float(row["outcome_native"]),
                row["native_unit"],
            )
            challenger = _celsius_error(
                float(row["eleven_field_residual_challenger_native"])
                - float(row["outcome_native"]),
                row["native_unit"],
            )
            total += baseline * baseline - challenger * challenger
        sums[market] = total
    fleet_total = sum(sums.values())
    shares = {
        market: (value / fleet_total if fleet_total > 0 else None)
        for market, value in sums.items()
    }
    maximum = max(shares.values()) if fleet_total > 0 else None
    return {
        "market_sums_c_equivalent_squared_error_improvement": sums,
        "fleet_sum_c_equivalent_squared_error_improvement": fleet_total,
        "signed_market_shares": shares,
        "maximum_single_market_contribution": maximum,
    }


def _decision(evaluation: dict) -> dict:
    endpoints = evaluation["crossed_bootstrap"]["endpoints"]
    squared = endpoints["primary__squared_error_improvement"]
    mae = endpoints["primary__mae_improvement"]
    sensitivity = endpoints[
        "all_leads_sensitivity__squared_error_improvement"
    ]
    contribution = evaluation["market_contributions"][
        "maximum_single_market_contribution"
    ]
    checks = {
        "squared_error_positive_interval": squared["point"] > 0
        and squared["lower_95"] > 0,
        "mae_nonnegative_and_lower_within_tolerance": mae["point"] >= 0
        and mae["lower_95"] >= -0.02,
        "all_leads_sensitivity_favorable_direction": sensitivity["point"] > 0,
        "maximum_market_contribution_at_most_0_35": contribution is not None
        and contribution <= 0.35,
        "support_at_least_100_dates_and_all_markets": evaluation[
            "support"
        ]["date_clusters"]
        >= 100
        and evaluation["support"]["markets"] == list(MARKETS),
        "isolation_units_and_parity_pass": all(
            evaluation["integrity"][name] == "PASS"
            for name in (
                "outcome_isolation",
                "native_units",
                "corpus_parity",
                "matched_rows",
            )
        ),
    }
    if all(checks.values()):
        verdict = "GO_TO_DISTRIBUTION_CHALLENGER"
    elif squared["upper_95"] < 0 or mae["upper_95"] < 0:
        verdict = "NO_GO"
    else:
        verdict = "INCONCLUSIVE_UNDERPOWERED"
    return {
        "verdict": verdict,
        "checks": checks,
        "achieved_power": squared["achieved_power"],
        "mde_80_c_equivalent_squared_error": squared["mde_80"],
    }


def evaluate_records(records: Sequence[dict]) -> dict:
    endpoints = _endpoint_rows(records)
    bootstrap = crossed_bootstrap(
        endpoints, draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED
    )
    evaluation = {
        "support": {
            "market_days": len(records),
            "date_clusters": len({row["target_date"] for row in records}),
            "markets": sorted({row["market"] for row in records}),
            "cohort_keys_sha256": canonical_sha256(
                [
                    f"{EVALUATION_YEAR}|{row['market']}|{row['target_date']}"
                    for row in sorted(
                        records, key=lambda value: (value["market"], value["target_date"])
                    )
                ]
            ),
        },
        "fleet_c_equivalent_metrics": {
            key: _point_metrics(records, key) for key in PREDICTION_KEYS
        },
        "per_market_native_metrics": _native_market_metrics(records),
        "per_month_c_equivalent_metrics": _month_metrics(records),
        "crossed_bootstrap": bootstrap,
        "market_contributions": _market_contributions(records),
        "exclusions_and_missingness": {
            "excluded_for_wu_row_count_below_18": 12 * 114 - len(records),
            "missing_feature_rows": 0,
            "baseline_challenger_row_mismatch": 0,
            "precipitation_probability_feature_rows_used": 0,
        },
        "integrity": {
            "outcome_isolation": "PASS",
            "native_units": "PASS",
            "corpus_parity": "PASS",
            "matched_rows": "PASS",
        },
    }
    evaluation["decision"] = _decision(evaluation)
    return evaluation


EVALUATION_RECORD_COLUMNS = (
    "market",
    "target_date",
    "month",
    "native_unit",
    "outcome_native",
    *PREDICTION_KEYS,
)


def run_terminal_evaluation(
    *, design_path: Path, artifact_root: Path, terminal_root: Path
) -> dict:
    design = _validate_design(design_path)
    training, bundles = load_training(design=design, artifact_root=artifact_root)
    if (terminal_root / "terminal-evaluation-attempt.json").exists():
        raise IntegrityError(
            "terminal evaluation is already sealed; source outcomes may not be reopened"
        )
    corpus_root = Path(design["input_binding"]["corpus_root"])
    surfaces, feature_audit = load_feature_surfaces(
        corpus_root, year=EVALUATION_YEAR
    )
    feature_keys = sorted(surfaces)
    required_keys = _cohort_keys(design, "terminal_evaluation")
    if not set(required_keys).issubset(feature_keys):
        raise IntegrityError("terminal feature cohort is incomplete before attempt seal")

    attempt_path, attempt = _seal_terminal_attempt(
        terminal_root=terminal_root, design=design, training=training
    )
    outcomes, outcome_audit = load_outcome_values(
        design, year=EVALUATION_YEAR, cohort="terminal_evaluation"
    )
    records = _evaluation_predictions(
        design=design,
        surfaces=surfaces,
        outcomes=outcomes,
        bundles=bundles,
    )
    terminal_root.mkdir(parents=True, exist_ok=True)
    records_path = terminal_root / "evaluation-records.csv"
    if records_path.exists():
        raise IntegrityError("terminal evaluation records already exist")
    with records_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=EVALUATION_RECORD_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(records)
        handle.flush()
        os.fsync(handle.fileno())
    evaluation = evaluate_records(records)
    if (
        evaluation["support"]["cohort_keys_sha256"]
        != design["cohorts"]["terminal_evaluation"]["keys_sha256"]
    ):
        raise IntegrityError("terminal result cohort differs from frozen design")
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": "TERMINAL_2025_EVALUATION_COMPLETE",
        "design_file_sha256": sha256_file(design_path),
        "design_sha256": design["design_sha256"],
        "training_receipt_file_sha256": sha256_file(
            artifact_root / "training-receipt.json"
        ),
        "training_sha256": training["training_sha256"],
        "model_artifacts": training["artifacts"],
        "terminal_attempt": {
            "relative_path": attempt_path.name,
            "file_sha256": sha256_file(attempt_path),
            "attempt_sha256": attempt["attempt_sha256"],
        },
        "evaluation_records": {
            "relative_path": records_path.name,
            "bytes": records_path.stat().st_size,
            "sha256": sha256_file(records_path),
        },
        "feature_audit": feature_audit,
        "outcome_audit": outcome_audit,
        "evaluation": evaluation,
        "prohibited_actions_audit": {
            "provider_calls": 0,
            "2026_data_or_outcome_reads": 0,
            "market_data_reads": 0,
            "production_or_scheduler_access": 0,
            "release_promotion_pointer_alpha_confirmation_actions": 0,
            "corpus_or_mirror_writes": 0,
            "probability_distribution_or_serving_work": 0,
            "models_fitted": 2,
            "terminal_2025_source_evaluations": 1,
        },
    }
    result["result_sha256"] = self_hash(result, "result_sha256")
    result_path = terminal_root / "result.json"
    if result_path.exists():
        raise IntegrityError("terminal result already exists")
    _exclusive_json(result_path, result)
    return result


def _read_evaluation_records(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EVALUATION_RECORD_COLUMNS:
            raise IntegrityError("evaluation-record column order differs")
        for row in reader:
            record = {
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
    *, design_path: Path, artifact_root: Path, terminal_root: Path
) -> dict:
    design = _validate_design(design_path)
    training, _ = load_training(design=design, artifact_root=artifact_root)
    result_path = terminal_root / "result.json"
    result = _load_json(result_path)
    if (
        result.get("schema_version") != RESULT_SCHEMA
        or result.get("result_sha256") != self_hash(result, "result_sha256")
        or result.get("design_sha256") != design["design_sha256"]
        or result.get("training_sha256") != training["training_sha256"]
    ):
        raise IntegrityError("terminal result identity differs")
    attempt_path = terminal_root / result["terminal_attempt"]["relative_path"]
    attempt = _load_json(attempt_path)
    if (
        attempt.get("schema_version") != ATTEMPT_SCHEMA
        or attempt.get("attempt_sha256") != self_hash(attempt, "attempt_sha256")
        or sha256_file(attempt_path) != result["terminal_attempt"]["file_sha256"]
        or attempt.get("rerun_authorized") is not False
    ):
        raise IntegrityError("terminal attempt seal differs")
    records_path = terminal_root / result["evaluation_records"]["relative_path"]
    if (
        records_path.stat().st_size != result["evaluation_records"]["bytes"]
        or sha256_file(records_path) != result["evaluation_records"]["sha256"]
    ):
        raise IntegrityError("terminal evaluation records differ")
    records = _read_evaluation_records(records_path)
    reproduced = evaluate_records(records)
    if canonical_sha256(reproduced) != canonical_sha256(result["evaluation"]):
        raise IntegrityError("deterministic terminal result reproduction differs")
    verification = {
        "schema_version": VERIFICATION_SCHEMA,
        "status": "PASS",
        "result_file_sha256": sha256_file(result_path),
        "result_sha256": result["result_sha256"],
        "design_sha256": design["design_sha256"],
        "training_sha256": training["training_sha256"],
        "model_artifact_sha256": {
            record["arm"]: record["sha256"] for record in training["artifacts"]
        },
        "evaluation_records_sha256": result["evaluation_records"]["sha256"],
        "reproduced_evaluation_sha256": canonical_sha256(reproduced),
        "source_outcomes_reopened": False,
        "models_refitted": 0,
        "bootstrap_reproduced": True,
    }
    verification["verification_sha256"] = self_hash(
        verification, "verification_sha256"
    )
    return verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p0 = subparsers.add_parser("p0")
    p0.add_argument("--corpus-root", type=Path, required=True)
    p0.add_argument("--mirror-root", type=Path, required=True)
    p0.add_argument("--plan", type=Path, required=True)
    p0.add_argument("--phase", choices=("pre", "post"), required=True)
    p0.add_argument("--output", type=Path, required=True)

    freeze = subparsers.add_parser("freeze-design")
    freeze.add_argument("--p0", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)

    fit = subparsers.add_parser("fit")
    fit.add_argument("--design", type=Path, required=True)
    fit.add_argument("--artifact-root", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--design", type=Path, required=True)
    evaluate.add_argument("--artifact-root", type=Path, required=True)
    evaluate.add_argument("--terminal-root", type=Path, required=True)

    verify = subparsers.add_parser("verify-result")
    verify.add_argument("--design", type=Path, required=True)
    verify.add_argument("--artifact-root", type=Path, required=True)
    verify.add_argument("--terminal-root", type=Path, required=True)
    verify.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "p0":
        result = verify_p0(
            corpus_root=args.corpus_root,
            mirror_root=args.mirror_root,
            plan_path=args.plan,
            phase=args.phase,
        )
        write_json(args.output, result)
    elif args.command == "freeze-design":
        result = freeze_design(p0_path=args.p0)
        write_json(args.output, result)
    elif args.command == "fit":
        result = fit_models(design_path=args.design, artifact_root=args.artifact_root)
    elif args.command == "evaluate":
        result = run_terminal_evaluation(
            design_path=args.design,
            artifact_root=args.artifact_root,
            terminal_root=args.terminal_root,
        )
    else:
        result = verify_result(
            design_path=args.design,
            artifact_root=args.artifact_root,
            terminal_root=args.terminal_root,
        )
        write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
