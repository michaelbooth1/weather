"""Outcome-isolated calendar-extension residual replication.

The implementation reuses the frozen feature/model/bootstrap primitives from
``multiyear_nwp_residual``.  It has no provider, market, production, Scheduler,
release, promotion, probability-distribution, or serving entry point.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from weather.calibration import multiyear_nwp_residual as prior
from weather.paths import REPO_ROOT
from weather.sources.daily_summary import native_bucket
from weather.sources.previous_runs_research_collection import (
    RetainedArtifactError,
    payload_sha256,
    verify_final,
    verify_plan,
)


P0_SCHEMA = "calendar_residual_replication_p0_v1"
DESIGN_SCHEMA = "calendar_residual_replication_design_v1"
TRAINING_SCHEMA = "calendar_residual_replication_training_v1"
ATTEMPT_SCHEMA = "calendar_residual_replication_terminal_attempt_v1"
RESULT_SCHEMA = "calendar_residual_replication_result_v1"
VERIFICATION_SCHEMA = "calendar_residual_replication_result_verification_v1"

SOURCE_BRANCH = (
    "origin/codex/workstation-collect-calendar-extension-2026-09-89a"
)
SOURCE_TIP = "7839340f252df3f908aa82dac2b6aaea861f8c0e"
SOURCE_TREE = "262648395c178d41bc869069e4329883f5cc9b02"

ORIGINAL_CORPUS_ROOT = (
    r"C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025"
)
EXTENSION_CORPUS_ROOT = (
    r"C:\Users\Michael\Documents\Codex\inputs\pit-11field-2024-2025-calendar-extension"
)
ORIGINAL_PLAN_SHA256 = (
    "20b45f3c0d98a57170a66a237de865374309da67371805fc15204d00f354b09e"
)
ORIGINAL_PLAN_FILE_SHA256 = (
    "924ddd2f1ca5a85def80dcee1296752df3df167f8a37d9ae7566a8c5f7ec303a"
)
ORIGINAL_MANIFEST_SHA256 = (
    "d41bd21efb7a62396851fe016a215db1ac8bea7de97f387333902aba7a35bb00"
)
EXTENSION_PLAN_SHA256 = (
    "ee9c39bdadf69a23c3a506bc75cbd3651ecd777318f06a5fd7e457f3c533cf66"
)
EXTENSION_PLAN_FILE_SHA256 = (
    "e31e8fcb7d08f4da7c714340e071f2af85ceabb70d22d0d5faf1c60f8f08270c"
)
EXTENSION_MANIFEST_SHA256 = (
    "501e5d0e22a0a21c9b0828e28dfa13b9ebc0043ab5c1e9335dda1d619689b448"
)
ORIGINAL_INVENTORY_FILES = 745
EXTENSION_INVENTORY_FILES = 580
ORIGINAL_REHASHED_FILES = 745
EXTENSION_REHASHED_FILES = 581

PRIOR_DESIGN_SHA256 = (
    "bd4bdb2ebcdd67a498e461b455f77bc9ca5a88f73bb19dae389e4bb28e26c0fb"
)
PRIOR_DESIGN_FILE_SHA256 = (
    "0667fdc204360122f44e35f2ef31dad5d6f7f53afd83bfd09ba0f0a50874bc65"
)

TRAIN_YEAR = 2024
EVALUATION_YEAR = 2025
BOOTSTRAP_DRAWS = prior.BOOTSTRAP_DRAWS
BOOTSTRAP_SEED = prior.BOOTSTRAP_SEED
MODEL_SEED = prior.MODEL_SEED
COMPLETE_DAY_MIN_ROWS = prior.COMPLETE_DAY_MIN_ROWS

MARKETS = prior.MARKETS
MARKET_STATIONS = prior.MARKET_STATIONS
MARKET_UNITS = prior.MARKET_UNITS
FIELDS = prior.FIELDS
EXCLUDED_FIELD = prior.EXCLUDED_FIELD
LEADS_PRIMARY = prior.LEADS_PRIMARY
LEADS_SENSITIVITY = prior.LEADS_SENSITIVITY
BASELINE_FEATURES = prior.BASELINE_FEATURES
CHALLENGER_FEATURES = prior.CHALLENGER_FEATURES
MODEL_CONFIG = prior.MODEL_CONFIG
CSV_COLUMNS = prior.CSV_COLUMNS
SUMMARY_NAMES = prior.SUMMARY_NAMES
PREDICTION_KEYS = prior.PREDICTION_KEYS

TRAIN_START = date(2024, 2, 1)
TRAIN_END = date(2024, 12, 31)
EVALUATION_EARLY_START = date(2025, 2, 1)
EVALUATION_EARLY_END = date(2025, 5, 9)
SPENT_START = date(2025, 5, 10)
SPENT_END = date(2025, 8, 31)
EVALUATION_LATE_START = date(2025, 9, 1)
EVALUATION_LATE_END = date(2025, 12, 31)


class IntegrityError(RuntimeError):
    """A frozen input, cohort, artifact, or isolation assertion differs."""


def canonical_sha256(value: object) -> str:
    return prior.canonical_sha256(value)


def self_hash(value: Mapping[str, object], field: str) -> str:
    return prior.self_hash(value, field)


def sha256_file(path: Path) -> str:
    return prior.sha256_file(path)


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise IntegrityError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    prior.write_json(path, value)


def _exclusive_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise IntegrityError(f"create-only artifact already exists: {path}") from exc


def _date_range(start: date, end: date) -> list[str]:
    return [
        date.fromordinal(ordinal).isoformat()
        for ordinal in range(start.toordinal(), end.toordinal() + 1)
    ]


TRAIN_DATES = tuple(_date_range(TRAIN_START, TRAIN_END))
EVALUATION_EARLY_DATES = tuple(
    _date_range(EVALUATION_EARLY_START, EVALUATION_EARLY_END)
)
EVALUATION_LATE_DATES = tuple(
    _date_range(EVALUATION_LATE_START, EVALUATION_LATE_END)
)
EVALUATION_DATES = EVALUATION_EARLY_DATES + EVALUATION_LATE_DATES


def _outcome_paths(mirror_root: Path) -> dict[str, Path]:
    return {
        market: mirror_root
        / "wunderground"
        / MARKET_STATIONS[market]
        / "daily"
        / "daily_summary.csv"
        for market in MARKETS
    }


def _cohort_summary(
    support: Mapping[str, Sequence[str]], *, year: int
) -> dict:
    keys = sorted(
        f"{year}|{market}|{target_date}"
        for market in MARKETS
        for target_date in support[market]
    )
    dates = sorted(
        {target_date for market in MARKETS for target_date in support[market]}
    )
    markets = [market for market in MARKETS if support[market]]
    return {
        "year": year,
        "market_days": len(keys),
        "date_clusters": len(dates),
        "markets": markets,
        "minimum_market_days": min(len(support[market]) for market in MARKETS),
        "maximum_market_days": max(len(support[market]) for market in MARKETS),
        "keys_sha256": canonical_sha256(keys),
        "dates_sha256": canonical_sha256(dates),
        "support_by_market_sha256": canonical_sha256(support),
    }


def _scan_outcome_support(mirror_root: Path) -> dict:
    """Hash WU files and inspect support metadata without outcome values."""
    support_columns = {
        "schema_version",
        "local_date",
        "temperature_unit",
        "row_count",
    }
    cohort_dates = {
        "training": set(TRAIN_DATES),
        "february_through_may09": set(EVALUATION_EARLY_DATES),
        "september_through_december": set(EVALUATION_LATE_DATES),
    }
    support = {
        name: {market: [] for market in MARKETS} for name in cohort_dates
    }
    inventory = []
    for market, path in _outcome_paths(mirror_root).items():
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or prior._is_reparse_point(resolved):
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
        with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header or not support_columns.issubset(header):
                raise IntegrityError(f"WU support columns are incomplete: {resolved}")
            positions = {name: header.index(name) for name in support_columns}
            for line_number, row in enumerate(reader, start=2):
                try:
                    raw_date = row[positions["local_date"]]
                    local_date = date.fromisoformat(raw_date)
                except (IndexError, ValueError) as exc:
                    raise IntegrityError(
                        f"invalid WU support date at {resolved}:{line_number}: {exc}"
                    ) from None
                names = [
                    name for name, dates in cohort_dates.items() if raw_date in dates
                ]
                if not names:
                    continue
                try:
                    row_count = int(row[positions["row_count"]])
                    unit = row[positions["temperature_unit"]].strip().upper()
                    schema = row[positions["schema_version"]].strip()
                except (IndexError, ValueError):
                    continue
                if (
                    row_count >= COMPLETE_DAY_MIN_ROWS
                    and unit == MARKET_UNITS[market]
                    and schema
                ):
                    for name in names:
                        support[name][market].append(local_date.isoformat())

    for cohort in support.values():
        for market, values in cohort.items():
            cohort[market] = sorted(values)
            if len(cohort[market]) != len(set(cohort[market])):
                raise IntegrityError(f"duplicate WU support date: {market}")
    combined = {
        market: sorted(
            support["february_through_may09"][market]
            + support["september_through_december"][market]
        )
        for market in MARKETS
    }
    support["terminal_evaluation"] = combined
    summaries = {
        "training": _cohort_summary(support["training"], year=TRAIN_YEAR),
        "february_through_may09": _cohort_summary(
            support["february_through_may09"], year=EVALUATION_YEAR
        ),
        "september_through_december": _cohort_summary(
            support["september_through_december"], year=EVALUATION_YEAR
        ),
        "terminal_evaluation": _cohort_summary(
            support["terminal_evaluation"], year=EVALUATION_YEAR
        ),
    }
    if summaries["training"]["markets"] != list(MARKETS):
        raise IntegrityError("training WU support does not admit all 12 markets")
    for name in ("february_through_may09", "september_through_december"):
        if summaries[name]["markets"] != list(MARKETS):
            raise IntegrityError(f"{name} WU support does not admit all 12 markets")
    if (
        summaries["terminal_evaluation"]["markets"] != list(MARKETS)
        or summaries["terminal_evaluation"]["date_clusters"] < 200
    ):
        raise IntegrityError(
            "insufficient authoritative WU evaluation support: "
            f"dates={summaries['terminal_evaluation']['date_clusters']}, "
            f"markets={len(summaries['terminal_evaluation']['markets'])}"
        )
    inventory = sorted(inventory, key=lambda item: item["market"])
    return {
        "outcome_values_accessed": False,
        "support_columns_accessed": sorted(support_columns),
        "minimum_rows": COMPLETE_DAY_MIN_ROWS,
        "file_inventory": inventory,
        "file_inventory_sha256": canonical_sha256(inventory),
        "cohorts": summaries,
        "support": support,
        "january_outcome_values_accessed": 0,
        "spent_2025_outcome_values_accessed": 0,
    }


def _verify_corpus(
    *, root: Path, plan_path: Path, expected: Mapping[str, object]
) -> dict:
    plan_file_hash = sha256_file(plan_path)
    plan = _load_json(plan_path)
    verify_plan(plan)
    if plan_file_hash != expected["plan_file_sha256"]:
        raise IntegrityError(f"{expected['name']} plan file hash differs")
    reproduced_plan_hash = payload_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    if (
        plan.get("plan_sha256") != expected["plan_sha256"]
        or reproduced_plan_hash != expected["plan_sha256"]
    ):
        raise IntegrityError(f"{expected['name']} canonical plan hash differs")
    try:
        final = verify_final(root)
    except RetainedArtifactError as exc:
        raise IntegrityError(
            f"{expected['name']} retained corpus integrity failed: {exc}"
        ) from exc
    verification = _load_json(root / "final" / "final-verification.json")
    inventory = verification.get("retained_inventory") or []
    if (
        final.get("corpus_manifest_sha256") != expected["manifest_sha256"]
        or len(inventory) != expected["inventory_files"]
        or final.get("integrity_errors") != []
        or verification.get("raw_projection_plan_receipt_manifest_rehash")
        != "PASS"
    ):
        raise IntegrityError(f"{expected['name']} terminal corpus identity differs")
    return {
        "root": str(root),
        "plan_sha256": plan["plan_sha256"],
        "plan_file_sha256": plan_file_hash,
        "manifest_canonical_sha256": final["corpus_manifest_sha256"],
        "manifest_file_sha256": final["corpus_manifest_file_sha256"],
        "final_verification_file_sha256": final[
            "final_verification_file_sha256"
        ],
        "retained_inventory_sha256": verification[
            "retained_inventory_sha256"
        ],
        "retained_inventory_file_count": len(inventory),
        "commissioned_rehashed_file_count": expected["rehashed_files"],
        "integrity_errors": final["integrity_errors"],
        "rehash": "PASS",
    }


def _validate_feature_coverage(
    original_root: Path, extension_root: Path
) -> dict:
    requested = {
        "original_2024_may_august": {
            "path": original_root / "final" / "coverage-matrix.csv",
            "year": 2024,
            "months": {5, 6, 7, 8},
        },
        "extension_2024_feb_december": {
            "path": extension_root / "final" / "coverage-matrix.csv",
            "year": 2024,
            "months": {2, 3, 4, 5, 9, 10, 11, 12},
        },
        "extension_2025_untouched": {
            "path": extension_root / "final" / "coverage-matrix.csv",
            "year": 2025,
            "months": {2, 3, 4, 5, 9, 10, 11, 12},
        },
    }
    results = {}
    for name, contract in requested.items():
        cells = []
        with contract["path"].open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            for row in csv.DictReader(handle):
                if (
                    int(row["year"]) != contract["year"]
                    or int(row["month"]) not in contract["months"]
                    or row["field"] not in FIELDS
                ):
                    continue
                if (
                    row["market"] not in MARKETS
                    or int(row["lead_days"]) not in LEADS_SENSITIVITY
                    or int(row["requested"]) <= 0
                    or int(row["non_null"]) != int(row["requested"])
                    or int(row["missing"]) != 0
                ):
                    raise IntegrityError(f"required feature coverage differs: {name}")
                cells.append(
                    (
                        row["market"],
                        row["field"],
                        int(row["lead_days"]),
                        int(row["month"]),
                    )
                )
        expected_cells = (
            len(MARKETS)
            * len(FIELDS)
            * len(LEADS_SENSITIVITY)
            * len(contract["months"])
        )
        if len(cells) != expected_cells or len(cells) != len(set(cells)):
            raise IntegrityError(f"required feature matrix is incomplete: {name}")
        results[name] = {
            "status": "PASS",
            "year": contract["year"],
            "months": sorted(contract["months"]),
            "complete_cells": len(cells),
            "cells_sha256": canonical_sha256(sorted(cells)),
        }
    return {
        "status": "PASS",
        "included_fields": list(FIELDS),
        "excluded_field": EXCLUDED_FIELD,
        "excluded_month": "January in both years",
        "leads": list(LEADS_SENSITIVITY),
        "surfaces": results,
    }


def verify_p0(
    *,
    original_root: Path,
    extension_root: Path,
    mirror_root: Path,
    original_plan_path: Path,
    extension_plan_path: Path,
    phase: str,
) -> dict:
    if phase not in {"pre", "post"}:
        raise IntegrityError("P0 phase must be pre or post")
    original = original_root.resolve(strict=True)
    extension = extension_root.resolve(strict=True)
    mirror = mirror_root.resolve(strict=True)
    if str(original).casefold() != ORIGINAL_CORPUS_ROOT.casefold():
        raise IntegrityError("original corpus root differs")
    if str(extension).casefold() != EXTENSION_CORPUS_ROOT.casefold():
        raise IntegrityError("extension corpus root differs")
    if any(prior._is_reparse_point(path) for path in (original, extension, mirror)):
        raise IntegrityError("corpus or mirror root is a reparse point")
    acl_before = {
        "original": prior._acl_proof(original),
        "extension": prior._acl_proof(extension),
        "mirror": prior._acl_proof(mirror),
    }
    corpora = {
        "original": _verify_corpus(
            root=original,
            plan_path=original_plan_path,
            expected={
                "name": "original",
                "plan_sha256": ORIGINAL_PLAN_SHA256,
                "plan_file_sha256": ORIGINAL_PLAN_FILE_SHA256,
                "manifest_sha256": ORIGINAL_MANIFEST_SHA256,
                "inventory_files": ORIGINAL_INVENTORY_FILES,
                "rehashed_files": ORIGINAL_REHASHED_FILES,
            },
        ),
        "extension": _verify_corpus(
            root=extension,
            plan_path=extension_plan_path,
            expected={
                "name": "extension",
                "plan_sha256": EXTENSION_PLAN_SHA256,
                "plan_file_sha256": EXTENSION_PLAN_FILE_SHA256,
                "manifest_sha256": EXTENSION_MANIFEST_SHA256,
                "inventory_files": EXTENSION_INVENTORY_FILES,
                "rehashed_files": EXTENSION_REHASHED_FILES,
            },
        ),
    }
    coverage = _validate_feature_coverage(original, extension)
    outcome_support = _scan_outcome_support(mirror)
    acl_after = {
        "original": prior._acl_proof(original),
        "extension": prior._acl_proof(extension),
        "mirror": prior._acl_proof(mirror),
    }
    if acl_before != acl_after:
        raise IntegrityError("corpus or mirror ACL changed during P0 verification")
    for name in corpora:
        corpora[name]["acl"] = acl_after[name]
    receipt = {
        "schema_version": P0_SCHEMA,
        "phase": phase,
        "status": "PASS",
        "source": {"branch": SOURCE_BRANCH, "tip": SOURCE_TIP, "tree": SOURCE_TREE},
        "corpora": corpora,
        "coverage": coverage,
        "outcome_support": outcome_support,
        "mirror": {"root": str(mirror), "acl": acl_after["mirror"]},
        "prohibited_actions": {
            "provider_calls": 0,
            "market_data_reads": 0,
            "2026_data_or_outcome_reads": 0,
            "outcome_values_accessed": False,
            "january_outcome_values_accessed": 0,
            "spent_2025_outcome_values_accessed": 0,
            "corpus_writes": 0,
            "mirror_writes": 0,
        },
    }
    receipt["p0_sha256"] = self_hash(receipt, "p0_sha256")
    return receipt


def _git_value(*arguments: str) -> str:
    return prior._git_value(*arguments)


def freeze_design(*, p0_path: Path, prior_design_path: Path) -> dict:
    p0 = _load_json(p0_path)
    if (
        p0.get("schema_version") != P0_SCHEMA
        or p0.get("status") != "PASS"
        or p0.get("p0_sha256") != self_hash(p0, "p0_sha256")
    ):
        raise IntegrityError("P0 PASS receipt is absent or changed")
    prior_design = _load_json(prior_design_path)
    if (
        sha256_file(prior_design_path) != PRIOR_DESIGN_FILE_SHA256
        or prior_design.get("design_sha256") != PRIOR_DESIGN_SHA256
        or prior_design.get("design_sha256")
        != prior.self_hash(prior_design, "design_sha256")
    ):
        raise IntegrityError("prior frozen design identity differs")
    if (
        tuple(prior_design["features"]["baseline_feature_order"])
        != BASELINE_FEATURES
        or tuple(prior_design["features"]["challenger_feature_order"])
        != CHALLENGER_FEATURES
        or prior_design["model"]["configuration"] != MODEL_CONFIG
    ):
        raise IntegrityError("prior frozen feature/model contract differs")
    module_path = Path(__file__).resolve(strict=True)
    design = {
        "schema_version": DESIGN_SCHEMA,
        "status": "FROZEN_BEFORE_UNTOUCHED_2025_OUTCOME_ACCESS",
        "purpose": (
            "Independent research-only point-forecast residual-information "
            "replication on untouched outside-window 2025 dates."
        ),
        "source": {"branch": SOURCE_BRANCH, "tip": SOURCE_TIP, "tree": SOURCE_TREE},
        "implementation": {
            "harness_commit": _git_value("rev-parse", "HEAD"),
            "harness_tree": _git_value("rev-parse", "HEAD^{tree}"),
            "module_relative_path": (
                "src/weather/calibration/calendar_residual_replication.py"
            ),
            "module_sha256": sha256_file(module_path),
        },
        "prior_frozen_contract": {
            "design_path": str(prior_design_path.resolve(strict=True)),
            "design_file_sha256": PRIOR_DESIGN_FILE_SHA256,
            "design_sha256": PRIOR_DESIGN_SHA256,
            "baseline_feature_order_sha256": canonical_sha256(
                list(BASELINE_FEATURES)
            ),
            "challenger_feature_order_sha256": canonical_sha256(
                list(CHALLENGER_FEATURES)
            ),
            "model_configuration_sha256": canonical_sha256(MODEL_CONFIG),
        },
        "input_binding": {
            "p0_receipt": str(p0_path.resolve(strict=True)),
            "p0_receipt_file_sha256": sha256_file(p0_path),
            "p0_sha256": p0["p0_sha256"],
            "corpora": p0["corpora"],
            "mirror_root": p0["mirror"]["root"],
            "outcome_support_file_inventory": p0["outcome_support"][
                "file_inventory"
            ],
            "outcome_support_file_inventory_sha256": p0["outcome_support"][
                "file_inventory_sha256"
            ],
        },
        "cohorts": {
            "training": p0["outcome_support"]["cohorts"]["training"],
            "february_through_may09": p0["outcome_support"]["cohorts"][
                "february_through_may09"
            ],
            "september_through_december": p0["outcome_support"]["cohorts"][
                "september_through_december"
            ],
            "terminal_evaluation": p0["outcome_support"]["cohorts"][
                "terminal_evaluation"
            ],
            "outcome_support": p0["outcome_support"]["support"],
            "training_dates": {
                "start": TRAIN_START.isoformat(),
                "end": TRAIN_END.isoformat(),
                "nominal_dates": len(TRAIN_DATES),
                "dates": list(TRAIN_DATES),
                "dates_sha256": canonical_sha256(list(TRAIN_DATES)),
            },
            "evaluation_segments": {
                "february_through_may09": {
                    "start": EVALUATION_EARLY_START.isoformat(),
                    "end": EVALUATION_EARLY_END.isoformat(),
                    "nominal_dates": len(EVALUATION_EARLY_DATES),
                    "dates": list(EVALUATION_EARLY_DATES),
                    "dates_sha256": canonical_sha256(
                        list(EVALUATION_EARLY_DATES)
                    ),
                },
                "september_through_december": {
                    "start": EVALUATION_LATE_START.isoformat(),
                    "end": EVALUATION_LATE_END.isoformat(),
                    "nominal_dates": len(EVALUATION_LATE_DATES),
                    "dates": list(EVALUATION_LATE_DATES),
                    "dates_sha256": canonical_sha256(
                        list(EVALUATION_LATE_DATES)
                    ),
                },
                "combined_nominal_dates": len(EVALUATION_DATES),
                "combined_dates": list(EVALUATION_DATES),
                "combined_dates_sha256": canonical_sha256(
                    list(EVALUATION_DATES)
                ),
            },
            "excluded": {
                "january_2024": "provider-history missingness; no imputation",
                "january_2025": "symmetric train/evaluation exclusion",
                "spent_2025_may10_aug31": "permanently excluded; no reopen, reuse, pool, or rescore",
            },
            "admission": (
                "WU daily-summary row in the market native unit with row_count "
                f">= {COMPLETE_DAY_MIN_ROWS}; exact eleven-field PIT coverage"
            ),
        },
        "target": {
            "value": "authoritative WU daily settlement high",
            "reader": "weather.sources.daily_summary.native_bucket",
            "unit": "each market's native settlement unit",
            "residual": "native settlement high minus primary forecast anchor",
            "substitution_allowed": False,
        },
        "forecast_anchor": {
            "daily_value": "target-day maximum temperature_2m per lead",
            "primary": "median across leads 2-7",
            "sensitivity": "median across leads 1-7",
        },
        "features": {
            "included_fields_in_order": list(FIELDS),
            "excluded_field": EXCLUDED_FIELD,
            "primary_leads": list(LEADS_PRIMARY),
            "sensitivity_leads": list(LEADS_SENSITIVITY),
            "baseline_feature_order": list(BASELINE_FEATURES),
            "challenger_feature_order": list(CHALLENGER_FEATURES),
            "feature_construction": prior_design["features"]["daily_summaries"],
            "across_lead_summaries": prior_design["features"][
                "across_lead_summaries"
            ],
            "day_of_year_period": prior_design["features"][
                "day_of_year_period"
            ],
            "missingness": "no imputation; fail on missing/non-finite feature; exact matched arms",
        },
        "model": {
            "model_count": 2,
            "arms": [
                "temperature_residual_baseline",
                "eleven_field_residual_challenger",
            ],
            "estimator": "sklearn.ensemble.HistGradientBoostingRegressor",
            "configuration": MODEL_CONFIG,
            "weights": "one row per admitted market-day, sample_weight=1.0",
            "target": "identical primary-anchor residual in both arms",
            "preprocessing": "identical prior design; no imputation or recalibration",
            "hyperparameter_or_feature_search": False,
        },
        "sensitivity": {
            "description": (
                "No-refit recomputation of all lead-derived inputs and anchor over "
                "leads 1-7 using the same two fitted estimators."
            )
        },
        "evaluation": {
            "single_access": (
                "create immutable terminal-attempt seal before any selected 2025 "
                "outcome value; retained seal forbids another source evaluation"
            ),
            "errors": "forecast minus WU outcome",
            "fleet_metrics": "native errors converted to Celsius-equivalent before aggregation",
            "native_metrics": "per-market signed error, MAE, and MSE stay in native units",
            "positive_improvement": "baseline loss minus challenger loss",
            "bootstrap": {
                "method": "shared-weight crossed target-date x market pigeonhole bootstrap",
                "draws": BOOTSTRAP_DRAWS,
                "seed": BOOTSTRAP_SEED,
                "interval": "percentile 95%",
                "power": "two-sided normal plug-in at alpha=0.05",
                "mde_80": "(z_0.975 + z_0.8) * crossed bootstrap standard error",
            },
            "maximum_market_contribution": (
                "maximum signed market sum of C-equivalent squared-error "
                "improvement divided by positive fleet sum"
            ),
        },
        "decision": {
            "go": "GO_TO_PROSPECTIVE_POINT_SHADOW only when all seven commissioned conditions pass",
            "conditions": [
                "combined primary MSE improvement > 0 and crossed lower 95% > 0",
                "combined primary MAE improvement >= 0 and crossed lower 95% >= -0.02 C-equivalent",
                "combined leads-1-7 sensitivity MSE improvement > 0",
                "both seasonal segments have primary MSE improvement > 0",
                "maximum one-market contribution <= 0.35",
                "at least 200 evaluation date clusters and all 12 markets admitted",
                "outcome isolation, native units, corpus integrity, and matched rows pass",
            ],
            "no_go": (
                "NO_GO if combined primary MSE or MAE harm is statistically "
                "established by an improvement upper 95% bound below zero"
            ),
            "otherwise": "INCONCLUSIVE_UNDERPOWERED",
            "authorization_limit": (
                "GO permits only prospective point-forecast shadow on genuinely "
                "new dates; never probability distribution, release, promotion, or serving"
            ),
        },
        "prohibited_actions": [
            "provider call",
            "2026 input or outcome read",
            "January outcome access",
            "May 10-August 31 2025 outcome access or record reuse",
            "market price or probability read",
            "production or Scheduler access",
            "corpus or mirror mutation",
            "hyperparameter or feature search",
            "release, promotion, pointer, serving, candidate freeze, alpha, or confirmation action",
        ],
    }
    design["design_sha256"] = self_hash(design, "design_sha256")
    return design


def _validate_design(design_path: Path) -> dict:
    design = _load_json(design_path)
    if (
        design.get("schema_version") != DESIGN_SCHEMA
        or design.get("status")
        != "FROZEN_BEFORE_UNTOUCHED_2025_OUTCOME_ACCESS"
        or design.get("design_sha256") != self_hash(design, "design_sha256")
        or design.get("source")
        != {"branch": SOURCE_BRANCH, "tip": SOURCE_TIP, "tree": SOURCE_TREE}
    ):
        raise IntegrityError("frozen design identity differs")
    if sha256_file(Path(__file__).resolve(strict=True)) != design[
        "implementation"
    ]["module_sha256"]:
        raise IntegrityError("frozen harness module hash differs")
    if (
        tuple(design["features"]["included_fields_in_order"]) != FIELDS
        or design["features"]["excluded_field"] != EXCLUDED_FIELD
        or tuple(design["features"]["baseline_feature_order"])
        != BASELINE_FEATURES
        or tuple(design["features"]["challenger_feature_order"])
        != CHALLENGER_FEATURES
        or design["model"]["model_count"] != 2
        or design["model"]["configuration"] != MODEL_CONFIG
        or design["evaluation"]["bootstrap"]["draws"] != BOOTSTRAP_DRAWS
        or design["evaluation"]["bootstrap"]["seed"] != BOOTSTRAP_SEED
    ):
        raise IntegrityError("frozen feature, model, or inference contract differs")
    p0_path = Path(design["input_binding"]["p0_receipt"])
    if sha256_file(p0_path) != design["input_binding"]["p0_receipt_file_sha256"]:
        raise IntegrityError("P0 receipt changed after design freeze")
    p0 = _load_json(p0_path)
    if p0.get("p0_sha256") != design["input_binding"]["p0_sha256"]:
        raise IntegrityError("P0 receipt binding differs")
    return design


def _assert_design_committed(design_path: Path, design: dict) -> None:
    resolved = design_path.resolve(strict=True)
    try:
        relative = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError as exc:
        raise IntegrityError("frozen design is outside the repository") from exc
    working_blob = _git_value("hash-object", str(resolved))
    try:
        committed_blob = _git_value("rev-parse", f"HEAD:{relative}")
        _git_value(
            "merge-base",
            "--is-ancestor",
            design["implementation"]["harness_commit"],
            "HEAD",
        )
    except Exception as exc:
        raise IntegrityError("frozen design is not committed in HEAD") from exc
    if working_blob != committed_blob:
        raise IntegrityError("working frozen design differs from committed HEAD")


@dataclass(frozen=True)
class CorpusSlice:
    corpus: str
    year: int
    segment: str
    start: date
    end: date


TRAINING_SLICES = (
    CorpusSlice("extension", 2024, "jan01-feb29", date(2024, 2, 1), date(2024, 2, 29)),
    CorpusSlice("extension", 2024, "mar01-may09", date(2024, 3, 1), date(2024, 5, 9)),
    CorpusSlice("original", 2024, "may10-jun30", date(2024, 5, 10), date(2024, 6, 30)),
    CorpusSlice("original", 2024, "jul01-aug31", date(2024, 7, 1), date(2024, 8, 31)),
    CorpusSlice("extension", 2024, "sep01-oct31", date(2024, 9, 1), date(2024, 10, 31)),
    CorpusSlice("extension", 2024, "nov01-dec31", date(2024, 11, 1), date(2024, 12, 31)),
)
EVALUATION_SLICES = (
    CorpusSlice("extension", 2025, "jan01-feb28", date(2025, 2, 1), date(2025, 2, 28)),
    CorpusSlice("extension", 2025, "mar01-may09", date(2025, 3, 1), date(2025, 5, 9)),
    CorpusSlice("extension", 2025, "sep01-oct31", date(2025, 9, 1), date(2025, 10, 31)),
    CorpusSlice("extension", 2025, "nov01-dec31", date(2025, 11, 1), date(2025, 12, 31)),
)


def load_feature_surfaces(
    design: dict, *, cohort: str
) -> tuple[dict, dict]:
    if cohort not in {"training", "terminal_evaluation"}:
        raise IntegrityError("feature cohort is outside the frozen design")
    roots = {
        name: Path(record["root"]).resolve(strict=True)
        for name, record in design["input_binding"]["corpora"].items()
    }
    slices = TRAINING_SLICES if cohort == "training" else EVALUATION_SLICES
    selected_dates = set(TRAIN_DATES if cohort == "training" else EVALUATION_DATES)
    accumulators: dict[tuple[str, str, int, str], prior._Accumulator] = {}
    source_files = []
    rows_scanned = 0
    selected_rows = 0
    excluded_date_rows = 0
    excluded_field_rows = 0
    for market in MARKETS:
        for item in slices:
            relative_path = (
                Path("units")
                / f"{market}--{item.year}--{item.segment}"
                / "completed"
                / "normalized.csv"
            )
            root = roots[item.corpus]
            path = (root / relative_path).resolve(strict=True)
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise IntegrityError("feature payload escaped its corpus root") from exc
            source_files.append(
                {
                    "corpus": item.corpus,
                    "relative_path": relative_path.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                if tuple(next(reader, ())) != CSV_COLUMNS:
                    raise IntegrityError(f"feature CSV header differs: {relative_path}")
                for line_number, row in enumerate(reader, start=2):
                    rows_scanned += 1
                    if len(row) != len(CSV_COLUMNS) or row[0] != market:
                        raise IntegrityError(
                            f"feature row shape/market differs: {relative_path}:{line_number}"
                        )
                    try:
                        timestamp = datetime.fromisoformat(row[1])
                    except ValueError:
                        raise IntegrityError(
                            f"feature timestamp differs: {relative_path}:{line_number}"
                        ) from None
                    target_date = timestamp.date()
                    if (
                        target_date.isoformat() not in selected_dates
                        or target_date < item.start
                        or target_date > item.end
                    ):
                        excluded_date_rows += 1
                        continue
                    field = row[2]
                    if field == EXCLUDED_FIELD:
                        excluded_field_rows += 1
                        continue
                    if field not in FIELDS:
                        raise IntegrityError(
                            f"unexpected feature field: {relative_path}:{line_number}"
                        )
                    try:
                        lead = int(row[3])
                        value = float(row[4])
                    except ValueError:
                        raise IntegrityError(
                            f"missing/invalid selected feature: {relative_path}:{line_number}"
                        ) from None
                    if (
                        timestamp.year != item.year
                        or lead not in LEADS_SENSITIVITY
                        or not math.isfinite(value)
                        or row[6] != "fixed_lead_day_offset"
                        or row[7] != "open_meteo_previous_runs"
                    ):
                        raise IntegrityError(
                            f"selected feature identity differs: {relative_path}:{line_number}"
                        )
                    if field == "temperature_2m":
                        expected_unit = "°C" if MARKET_UNITS[market] == "C" else "°F"
                        if row[5] != expected_unit:
                            raise IntegrityError(
                                f"native temperature unit differs: {relative_path}:{line_number}"
                            )
                    selected_rows += 1
                    for summary in prior._summary_targets(field, timestamp.hour):
                        key = (
                            market,
                            target_date.isoformat(),
                            lead,
                            summary,
                        )
                        accumulators.setdefault(key, prior._Accumulator()).add(value)

    surfaces: dict[tuple[str, str], dict[int, dict[str, float]]] = defaultdict(dict)
    ordered_dates = TRAIN_DATES if cohort == "training" else EVALUATION_DATES
    for market in MARKETS:
        for target_date in ordered_dates:
            for lead in LEADS_SENSITIVITY:
                summaries = {}
                for name in SUMMARY_NAMES:
                    key = (market, target_date, lead, name)
                    if key not in accumulators:
                        raise IntegrityError(f"feature summary is absent: {key}")
                    summaries[name] = prior._finish_accumulator(
                        name, accumulators[key]
                    )
                surfaces[(market, target_date)][lead] = summaries
    expected_market_days = len(MARKETS) * len(ordered_dates)
    if len(surfaces) != expected_market_days:
        raise IntegrityError("feature market-day denominator differs")
    source_files = sorted(
        source_files, key=lambda row: (row["corpus"], row["relative_path"])
    )
    return dict(surfaces), {
        "cohort": cohort,
        "source_file_count": len(source_files),
        "source_files": source_files,
        "source_files_sha256": canonical_sha256(source_files),
        "input_rows_scanned": rows_scanned,
        "selected_rows": selected_rows,
        "excluded_date_rows": excluded_date_rows,
        "excluded_precipitation_probability_rows": excluded_field_rows,
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


def _cohort_keys(design: dict, cohort: str) -> list[tuple[str, str]]:
    if cohort not in {"training", "terminal_evaluation"}:
        raise IntegrityError("outcome cohort differs")
    year = TRAIN_YEAR if cohort == "training" else EVALUATION_YEAR
    support = design["cohorts"]["outcome_support"][cohort]
    keys = sorted(
        (market, target_date)
        for market in MARKETS
        for target_date in support[market]
    )
    encoded = [f"{year}|{market}|{target_date}" for market, target_date in keys]
    if canonical_sha256(encoded) != design["cohorts"][cohort]["keys_sha256"]:
        raise IntegrityError(f"{cohort} cohort key hash differs")
    return keys


def load_outcome_values(
    design: dict, *, year: int, cohort: str
) -> tuple[dict[tuple[str, str], int], dict]:
    expected = "training" if year == TRAIN_YEAR else "terminal_evaluation"
    if year not in {TRAIN_YEAR, EVALUATION_YEAR} or cohort != expected:
        raise IntegrityError("outcome cohort/year isolation differs")
    mirror = Path(design["input_binding"]["mirror_root"]).resolve(strict=True)
    inventory_rows = design["input_binding"]["outcome_support_file_inventory"]
    if canonical_sha256(inventory_rows) != design["input_binding"][
        "outcome_support_file_inventory_sha256"
    ]:
        raise IntegrityError("outcome support inventory self-hash differs")
    inventory = {row["market"]: row for row in inventory_rows}
    paths = _outcome_paths(mirror)
    for market, path in paths.items():
        record = inventory[market]
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise IntegrityError(f"outcome source drifted before access: {market}")
    required = set(_cohort_keys(design, cohort))
    outcomes = {}
    accessed_dates = []
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
                if year == EVALUATION_YEAR and (
                    local_date.month == 1 or SPENT_START <= local_date <= SPENT_END
                ):
                    raise IntegrityError("forbidden 2025 outcome reached value access")
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
                        f"authoritative native outcome absent at {market}:{line_number}"
                    )
                if key in outcomes:
                    raise IntegrityError(f"duplicate authoritative outcome: {key}")
                outcomes[key] = int(outcome)
                accessed_dates.append(raw_date)
    if set(outcomes) != required:
        missing = sorted(required - set(outcomes))
        raise IntegrityError(f"authoritative outcome cohort differs: {missing[:3]}")
    return outcomes, {
        "year": year,
        "cohort": cohort,
        "market_days": len(outcomes),
        "date_clusters": len(set(accessed_dates)),
        "keys_sha256": canonical_sha256(
            [f"{year}|{market}|{target_date}" for market, target_date in sorted(outcomes)]
        ),
        "source_file_inventory_sha256": design["input_binding"][
            "outcome_support_file_inventory_sha256"
        ],
        "native_units": MARKET_UNITS,
        "outcome_value_accesses": len(outcomes),
        "january_outcome_value_accesses": 0,
        "spent_may10_aug31_2025_outcome_value_accesses": 0,
    }


def _prediction_rows(
    *, design: dict, cohort: str, surfaces: dict, outcomes: dict
) -> tuple[list[dict], np.ndarray, np.ndarray, np.ndarray]:
    keys = _cohort_keys(design, cohort)
    records = []
    baseline_matrix = []
    challenger_matrix = []
    residual_target = []
    for market, target_date in keys:
        surface = surfaces.get((market, target_date))
        if surface is None or (market, target_date) not in outcomes:
            raise IntegrityError(f"matched row absent: {market}/{target_date}")
        baseline, anchor = prior.feature_vector(
            market=market,
            target_date=target_date,
            leads=surface,
            selected_leads=LEADS_PRIMARY,
            challenger=False,
        )
        challenger, challenger_anchor = prior.feature_vector(
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
                "segment": (
                    "february_through_may09"
                    if target_date <= EVALUATION_EARLY_END.isoformat()
                    else "september_through_december"
                ) if cohort == "terminal_evaluation" else "training",
                "native_unit": MARKET_UNITS[market],
                "outcome_native": outcome,
                "primary_anchor_native": anchor,
            }
        )
        baseline_matrix.append(baseline)
        challenger_matrix.append(challenger)
        residual_target.append(outcome - anchor)
    baseline_x = np.asarray(baseline_matrix, dtype=float)
    challenger_x = np.asarray(challenger_matrix, dtype=float)
    residual_y = np.asarray(residual_target, dtype=float)
    if (
        baseline_x.shape != (len(keys), len(BASELINE_FEATURES))
        or challenger_x.shape != (len(keys), len(CHALLENGER_FEATURES))
        or residual_y.shape != (len(keys),)
        or not np.isfinite(baseline_x).all()
        or not np.isfinite(challenger_x).all()
        or not np.isfinite(residual_y).all()
    ):
        raise IntegrityError("matched model matrices differ")
    return records, baseline_x, challenger_x, residual_y


_new_estimator = prior._new_estimator


def fit_models(*, design_path: Path, artifact_root: Path) -> dict:
    design = _validate_design(design_path)
    _assert_design_committed(design_path, design)
    if artifact_root.exists():
        raise IntegrityError(f"training artifact root already exists: {artifact_root}")
    surfaces, feature_audit = load_feature_surfaces(design, cohort="training")
    outcomes, outcome_audit = load_outcome_values(
        design, year=TRAIN_YEAR, cohort="training"
    )
    records, baseline_x, challenger_x, residual_y = _prediction_rows(
        design=design,
        cohort="training",
        surfaces=surfaces,
        outcomes=outcomes,
    )
    sample_weight = np.ones(len(records), dtype=float)
    models = [
        ("temperature_residual_baseline", BASELINE_FEATURES, _new_estimator()),
        ("eleven_field_residual_challenger", CHALLENGER_FEATURES, _new_estimator()),
    ]
    matrices = [baseline_x, challenger_x]
    fit_count = 0
    for (_, _, model), matrix in zip(models, matrices):
        model.fit(matrix, residual_y, sample_weight=sample_weight)
        fit_count += 1
    if fit_count != 2:
        raise IntegrityError("exact two-fit assertion failed")
    predictions = [model.predict(matrix) for (_, _, model), matrix in zip(models, matrices)]
    for index, row in enumerate(records):
        row["temperature_residual_baseline_native"] = float(
            row["primary_anchor_native"] + predictions[0][index]
        )
        row["eleven_field_residual_challenger_native"] = float(
            row["primary_anchor_native"] + predictions[1][index]
        )

    stage = artifact_root.with_name(artifact_root.name + ".publishing")
    if stage.exists():
        raise IntegrityError(f"training publishing root already exists: {stage}")
    stage.mkdir(parents=True)
    artifacts = []
    for arm, order, model in models:
        model_bytes, _ = prior._model_artifact(
            model=model, arm=arm, feature_order=order, design=design
        )
        filename = arm.replace("_", "-") + ".pkl"
        path = stage / filename
        prior.write_bytes(path, model_bytes)
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
        "segment",
        "native_unit",
        "outcome_native",
        "primary_anchor_native",
        "temperature_residual_baseline_native",
        "eleven_field_residual_challenger_native",
    )
    records_path = stage / "training-records.csv"
    with records_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=record_columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    receipt = {
        "schema_version": TRAINING_SCHEMA,
        "status": "PASS",
        "design_file_sha256": sha256_file(design_path),
        "design_sha256": design["design_sha256"],
        "year": TRAIN_YEAR,
        "models_fitted": fit_count,
        "model_configuration": MODEL_CONFIG,
        "sample_weight": "1.0 per admitted market-day",
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
        "training_records": {
            "relative_path": records_path.name,
            "bytes": records_path.stat().st_size,
            "sha256": sha256_file(records_path),
        },
        "training_metrics": {
            "raw_temperature_anchor": prior._simple_metrics(
                records, "primary_anchor_native"
            ),
            "temperature_residual_baseline": prior._simple_metrics(
                records, "temperature_residual_baseline_native"
            ),
            "eleven_field_residual_challenger": prior._simple_metrics(
                records, "eleven_field_residual_challenger_native"
            ),
        },
        "terminal_2025_outcomes_accessed": False,
        "provider_or_market_data_accessed": False,
    }
    receipt["training_sha256"] = self_hash(receipt, "training_sha256")
    write_json(stage / "training-receipt.json", receipt)
    os.replace(stage, artifact_root)
    return receipt


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
        bundles[record["arm"]] = prior._load_model_bundle(
            artifact_root / record["relative_path"], record, design
        )
    if set(bundles) != {
        "temperature_residual_baseline",
        "eleven_field_residual_challenger",
    }:
        raise IntegrityError("training receipt does not bind exactly two models")
    return receipt, bundles


def _seal_terminal_attempt(
    *, terminal_root: Path, design: dict, training: dict
) -> tuple[Path, dict]:
    path = terminal_root / "terminal-evaluation-attempt.json"
    attempt = {
        "schema_version": ATTEMPT_SCHEMA,
        "status": "SEALED_BEFORE_UNTOUCHED_2025_OUTCOME_ACCESS",
        "design_sha256": design["design_sha256"],
        "training_sha256": training["training_sha256"],
        "evaluation_year": EVALUATION_YEAR,
        "evaluation_dates_sha256": canonical_sha256(list(EVALUATION_DATES)),
        "evaluation_segments": design["cohorts"]["evaluation_segments"],
        "outcome_source_accesses_authorized": 1,
        "spent_2025_outcome_accesses_authorized": 0,
        "january_outcome_accesses_authorized": 0,
        "rerun_authorized": False,
    }
    attempt["attempt_sha256"] = self_hash(attempt, "attempt_sha256")
    _exclusive_json(path, attempt)
    return path, attempt


def _evaluation_predictions(
    *, design: dict, surfaces: dict, outcomes: dict, bundles: dict[str, dict]
) -> list[dict]:
    records, baseline_x, challenger_x, _ = _prediction_rows(
        design=design,
        cohort="terminal_evaluation",
        surfaces=surfaces,
        outcomes=outcomes,
    )
    baseline_model = bundles["temperature_residual_baseline"]["estimator"]
    challenger_model = bundles["eleven_field_residual_challenger"]["estimator"]
    primary_baseline = baseline_model.predict(baseline_x)
    primary_challenger = challenger_model.predict(challenger_x)
    sensitivity_baseline_x = []
    sensitivity_challenger_x = []
    sensitivity_anchors = []
    for row in records:
        surface = surfaces[(row["market"], row["target_date"])]
        baseline, anchor = prior.feature_vector(
            market=row["market"],
            target_date=row["target_date"],
            leads=surface,
            selected_leads=LEADS_SENSITIVITY,
            challenger=False,
        )
        challenger, challenger_anchor = prior.feature_vector(
            market=row["market"],
            target_date=row["target_date"],
            leads=surface,
            selected_leads=LEADS_SENSITIVITY,
            challenger=True,
        )
        if anchor != challenger_anchor:
            raise IntegrityError("sensitivity anchors differ")
        sensitivity_baseline_x.append(baseline)
        sensitivity_challenger_x.append(challenger)
        sensitivity_anchors.append(anchor)
    sensitivity_baseline = baseline_model.predict(
        np.asarray(sensitivity_baseline_x, dtype=float)
    )
    sensitivity_challenger = challenger_model.predict(
        np.asarray(sensitivity_challenger_x, dtype=float)
    )
    for index, row in enumerate(records):
        primary_anchor = float(row.pop("primary_anchor_native"))
        sensitivity_anchor = float(sensitivity_anchors[index])
        row.update(
            {
                "raw_temperature_anchor_native": primary_anchor,
                "temperature_residual_baseline_native": float(
                    primary_anchor + primary_baseline[index]
                ),
                "eleven_field_residual_challenger_native": float(
                    primary_anchor + primary_challenger[index]
                ),
                "all_leads_raw_temperature_anchor_native": sensitivity_anchor,
                "all_leads_temperature_residual_baseline_native": float(
                    sensitivity_anchor + sensitivity_baseline[index]
                ),
                "all_leads_eleven_field_residual_challenger_native": float(
                    sensitivity_anchor + sensitivity_challenger[index]
                ),
            }
        )
    return records


def _model_metrics(records: Sequence[dict], key: str, *, celsius: bool) -> dict:
    errors = [float(row[key]) - float(row["outcome_native"]) for row in records]
    if celsius:
        errors = [
            prior._celsius_error(error, row["native_unit"])
            for error, row in zip(errors, records)
        ]
    return {
        "signed_error": float(np.mean(errors)),
        "mae": float(np.mean(np.abs(errors))),
        "mse": float(np.mean(np.square(errors))),
    }


def _effects(records: Sequence[dict], *, celsius: bool) -> dict:
    baseline = _model_metrics(
        records, "temperature_residual_baseline_native", celsius=celsius
    )
    challenger = _model_metrics(
        records, "eleven_field_residual_challenger_native", celsius=celsius
    )
    sensitivity_baseline = _model_metrics(
        records, "all_leads_temperature_residual_baseline_native", celsius=celsius
    )
    sensitivity_challenger = _model_metrics(
        records, "all_leads_eleven_field_residual_challenger_native", celsius=celsius
    )
    return {
        "primary_mae_improvement": baseline["mae"] - challenger["mae"],
        "primary_mse_improvement": baseline["mse"] - challenger["mse"],
        "all_leads_mae_improvement": (
            sensitivity_baseline["mae"] - sensitivity_challenger["mae"]
        ),
        "all_leads_mse_improvement": (
            sensitivity_baseline["mse"] - sensitivity_challenger["mse"]
        ),
    }


def _slice_metrics(records: Sequence[dict]) -> dict:
    fleet = {
        key: _model_metrics(records, key, celsius=True) for key in PREDICTION_KEYS
    }
    per_market = {}
    for market in MARKETS:
        subset = [row for row in records if row["market"] == market]
        per_market[market] = {
            "native_unit": MARKET_UNITS[market],
            "market_days": len(subset),
            "models": {
                key: _model_metrics(subset, key, celsius=False)
                for key in PREDICTION_KEYS
            },
            "effects": _effects(subset, celsius=False),
        }
    per_month = {}
    for month in sorted({int(row["month"]) for row in records}):
        subset = [row for row in records if int(row["month"]) == month]
        per_month[str(month)] = {
            "market_days": len(subset),
            "models": {
                key: _model_metrics(subset, key, celsius=True)
                for key in PREDICTION_KEYS
            },
            "effects": _effects(subset, celsius=True),
        }
    return {
        "fleet_c_equivalent_metrics": fleet,
        "effects_c_equivalent": _effects(records, celsius=True),
        "per_market_native_metrics": per_market,
        "per_month_c_equivalent_metrics": per_month,
    }


def _evaluate_partition(
    records: Sequence[dict], *, nominal_dates: int
) -> dict:
    if not records:
        raise IntegrityError("evaluation partition is empty")
    metrics = _slice_metrics(records)
    bootstrap = prior.crossed_bootstrap(
        prior._endpoint_rows(records), draws=BOOTSTRAP_DRAWS, seed=BOOTSTRAP_SEED
    )
    return {
        "support": {
            "market_days": len(records),
            "date_clusters": len({row["target_date"] for row in records}),
            "markets": sorted({row["market"] for row in records}),
            "cohort_keys_sha256": canonical_sha256(
                [
                    f"{EVALUATION_YEAR}|{row['market']}|{row['target_date']}"
                    for row in sorted(
                        records,
                        key=lambda value: (value["market"], value["target_date"]),
                    )
                ]
            ),
        },
        **metrics,
        "crossed_bootstrap": bootstrap,
        "market_contributions": prior._market_contributions(records),
        "exclusions_and_missingness": {
            "nominal_market_days": nominal_dates * len(MARKETS),
            "excluded_for_wu_row_count_below_18": (
                nominal_dates * len(MARKETS) - len(records)
            ),
            "missing_feature_rows": 0,
            "baseline_challenger_row_mismatch": 0,
            "precipitation_probability_feature_rows_used": 0,
            "january_rows_used": 0,
            "spent_2025_may10_aug31_rows_used": 0,
        },
        "integrity": {
            "outcome_isolation": "PASS",
            "native_units": "PASS",
            "corpus_integrity": "PASS",
            "matched_rows": "PASS",
        },
    }


def _decision(evaluation: dict) -> dict:
    combined = evaluation["combined"]
    endpoints = combined["crossed_bootstrap"]["endpoints"]
    mse = endpoints["primary__squared_error_improvement"]
    mae = endpoints["primary__mae_improvement"]
    sensitivity = endpoints[
        "all_leads_sensitivity__squared_error_improvement"
    ]
    contribution = combined["market_contributions"][
        "maximum_single_market_contribution"
    ]
    segment_directions = {
        name: payload["crossed_bootstrap"]["endpoints"][
            "primary__squared_error_improvement"
        ]["point"]
        > 0
        for name, payload in evaluation["segments"].items()
    }
    checks = {
        "combined_mse_positive_interval": mse["point"] > 0
        and mse["lower_95"] > 0,
        "combined_mae_nonnegative_and_lower_within_tolerance": mae["point"] >= 0
        and mae["lower_95"] >= -0.02,
        "all_leads_sensitivity_favorable_mse_direction": sensitivity["point"] > 0,
        "both_seasonal_segments_favorable_mse_direction": all(
            segment_directions.values()
        ),
        "maximum_market_contribution_at_most_0_35": contribution is not None
        and contribution <= 0.35,
        "support_at_least_200_dates_and_all_markets": combined["support"][
            "date_clusters"
        ]
        >= 200
        and combined["support"]["markets"] == list(MARKETS),
        "isolation_units_corpus_and_parity_pass": all(
            value == "PASS" for value in combined["integrity"].values()
        ),
    }
    if all(checks.values()):
        verdict = "GO_TO_PROSPECTIVE_POINT_SHADOW"
    elif mse["upper_95"] < 0 or mae["upper_95"] < 0:
        verdict = "NO_GO"
    else:
        verdict = "INCONCLUSIVE_UNDERPOWERED"
    return {
        "verdict": verdict,
        "checks": checks,
        "segment_mse_directions": segment_directions,
        "achieved_power": mse["achieved_power"],
        "mde_80_c_equivalent_squared_error": mse["mde_80"],
        "authorization_limit": (
            "prospective point-forecast shadow on genuinely new dates only; no "
            "probability-distribution, retraining, release, promotion, or serving"
        ),
    }


def evaluate_records(records: Sequence[dict]) -> dict:
    early = [
        row for row in records if row["segment"] == "february_through_may09"
    ]
    late = [
        row for row in records if row["segment"] == "september_through_december"
    ]
    evaluation = {
        "segments": {
            "february_through_may09": _evaluate_partition(
                early, nominal_dates=len(EVALUATION_EARLY_DATES)
            ),
            "september_through_december": _evaluate_partition(
                late, nominal_dates=len(EVALUATION_LATE_DATES)
            ),
        },
        "combined": _evaluate_partition(
            records, nominal_dates=len(EVALUATION_DATES)
        ),
    }
    evaluation["decision"] = _decision(evaluation)
    return evaluation


EVALUATION_RECORD_COLUMNS = (
    "market",
    "target_date",
    "month",
    "segment",
    "native_unit",
    "outcome_native",
    *PREDICTION_KEYS,
)


def run_terminal_evaluation(
    *, design_path: Path, artifact_root: Path, terminal_root: Path
) -> dict:
    design = _validate_design(design_path)
    _assert_design_committed(design_path, design)
    training, bundles = load_training(design=design, artifact_root=artifact_root)
    if terminal_root.exists():
        raise IntegrityError("terminal root already exists; source outcomes stay sealed")
    surfaces, feature_audit = load_feature_surfaces(
        design, cohort="terminal_evaluation"
    )
    required_keys = set(_cohort_keys(design, "terminal_evaluation"))
    if not required_keys.issubset(surfaces):
        raise IntegrityError("evaluation features are incomplete before attempt seal")
    attempt_path, attempt = _seal_terminal_attempt(
        terminal_root=terminal_root, design=design, training=training
    )
    outcomes, outcome_audit = load_outcome_values(
        design, year=EVALUATION_YEAR, cohort="terminal_evaluation"
    )
    records = _evaluation_predictions(
        design=design, surfaces=surfaces, outcomes=outcomes, bundles=bundles
    )
    records_path = terminal_root / "evaluation-records.csv"
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
        evaluation["combined"]["support"]["cohort_keys_sha256"]
        != design["cohorts"]["terminal_evaluation"]["keys_sha256"]
    ):
        raise IntegrityError("terminal result cohort differs from frozen design")
    result = {
        "schema_version": RESULT_SCHEMA,
        "status": "TERMINAL_UNTOUCHED_2025_EVALUATION_COMPLETE",
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
            "january_outcome_value_accesses": 0,
            "spent_2025_outcome_value_accesses": 0,
            "market_data_reads": 0,
            "production_or_scheduler_access": 0,
            "release_promotion_pointer_serving_candidate_alpha_confirmation_actions": 0,
            "corpus_or_mirror_writes": 0,
            "probability_distribution_work": 0,
            "models_fitted": 2,
            "terminal_2025_source_evaluations": 1,
        },
    }
    result["result_sha256"] = self_hash(result, "result_sha256")
    _exclusive_json(terminal_root / "result.json", result)
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
                "segment": row["segment"],
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
        or attempt.get("spent_2025_outcome_accesses_authorized") != 0
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
        "spent_2025_outcomes_reopened": False,
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
    p0.add_argument("--original-root", type=Path, required=True)
    p0.add_argument("--extension-root", type=Path, required=True)
    p0.add_argument("--mirror-root", type=Path, required=True)
    p0.add_argument("--original-plan", type=Path, required=True)
    p0.add_argument("--extension-plan", type=Path, required=True)
    p0.add_argument("--phase", choices=("pre", "post"), required=True)
    p0.add_argument("--output", type=Path, required=True)
    freeze = subparsers.add_parser("freeze-design")
    freeze.add_argument("--p0", type=Path, required=True)
    freeze.add_argument("--prior-design", type=Path, required=True)
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
            original_root=args.original_root,
            extension_root=args.extension_root,
            mirror_root=args.mirror_root,
            original_plan_path=args.original_plan,
            extension_plan_path=args.extension_plan,
            phase=args.phase,
        )
        write_json(args.output, result)
    elif args.command == "freeze-design":
        result = freeze_design(
            p0_path=args.p0, prior_design_path=args.prior_design
        )
        _exclusive_json(args.output, result)
    elif args.command == "fit":
        result = fit_models(
            design_path=args.design, artifact_root=args.artifact_root
        )
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
