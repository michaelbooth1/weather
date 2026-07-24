"""Fail-closed operational-evidence checks for source-ablation replay."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict

from weather.backtesting.source_ablation_contract import (
    SourceAblationContractError,
    exact_requested_variants,
    members_for_variant,
    variant_names_for_spec,
)
from weather.market.market_registry import REGISTRY
from weather.release_serving import STATUS_BOUND
from weather.reporting.promotion.promotion_corpus import (
    PROMOTION_CORPUS_SCHEMA_VERSION,
    corpus_hash,
)


INFERENCE_BOOTSTRAP_REPLICATES = 10_000
INFERENCE_BOOTSTRAP_SEED = 20260722


def applicable_market_ids_for_variant(variant):
    """Return the registry markets whose sealed live plan contains *variant*."""

    if variant == "reanalysis_synoptic":
        return tuple(sorted(REGISTRY))
    try:
        return tuple(
            sorted(
                market_id
                for market_id, spec in REGISTRY.items()
                if variant in variant_names_for_spec(spec, (variant,))
            )
        )
    except SourceAblationContractError:
        return ()


def _mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def _percentile(values, quantile):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _cluster_bootstrap(
    values,
    *,
    seed,
    replicates=INFERENCE_BOOTSTRAP_REPLICATES,
):
    values = [float(value) for value in values]
    if not values:
        return {
            "low": None,
            "high": None,
            "replicates": replicates,
            "seed": seed,
        }
    rng = random.Random(int(seed))
    n = len(values)
    estimates = [
        sum(values[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(int(replicates))
    ]
    return {
        "low": _percentile(estimates, 0.025),
        "high": _percentile(estimates, 0.975),
        "replicates": int(replicates),
        "seed": int(seed),
    }


def _sign_test(values):
    values = [float(value) for value in values]
    improvements = sum(value < 0.0 for value in values)
    regressions = sum(value > 0.0 for value in values)
    ties = len(values) - improvements - regressions
    n = improvements + regressions
    if n:
        tail = min(improvements, regressions)
        p_value = min(
            1.0,
            2.0
            * sum(math.comb(n, k) for k in range(tail + 1))
            / (2.0**n),
        )
    else:
        p_value = 1.0
    return {
        "improvements": improvements,
        "regressions": regressions,
        "ties": ties,
        "non_ties": n,
        "two_sided_p": p_value,
    }


def paired_day_inference(day_tables, split_dates=None):
    """Equal-fleet-date paired inference from per-market-day ablation deltas."""

    requested_splits = {"all": None, **(split_dates or {})}
    output = []
    for variant, rows in sorted(day_tables.items()):
        by_date = defaultdict(list)
        for row in rows:
            target_date = str(
                row.get("market_day") or row.get("day") or ""
            ).rsplit(" ", 1)[-1]
            by_date[target_date].append(row)
        for split, date_values in requested_splits.items():
            allowed = set(date_values) if date_values is not None else None
            selected = {
                target_date: market_days
                for target_date, market_days in by_date.items()
                if allowed is None or target_date in allowed
            }
            fleet_rows = []
            for target_date, market_days in sorted(selected.items()):
                fleet_rows.append(
                    {
                        "target_date": target_date,
                        "market_days": len(market_days),
                        "brier_delta": _mean(
                            row["brier_delta"] for row in market_days
                        ),
                        "logloss_delta": _mean(
                            row["logloss_delta"] for row in market_days
                        ),
                        "no_op_market_days": sum(
                            abs(float(row["brier_delta"])) <= 1e-15
                            and abs(float(row["logloss_delta"])) <= 1e-15
                            for row in market_days
                        ),
                    }
                )
            metric_payload = {}
            for metric in ("brier_delta", "logloss_delta"):
                values = [row[metric] for row in fleet_rows]
                digest = hashlib.sha256(
                    f"{variant}|{split}|{metric}".encode("utf-8")
                ).digest()
                seed = INFERENCE_BOOTSTRAP_SEED + int.from_bytes(
                    digest[:4], "big"
                )
                metric_payload[metric] = {
                    "mean": _mean(values),
                    "cluster_bootstrap_95ci": _cluster_bootstrap(
                        values,
                        seed=seed,
                    ),
                    "sign_test": _sign_test(values),
                }
            output.append(
                {
                    "variant": variant,
                    "split": split,
                    "fleet_dates": len(fleet_rows),
                    "market_days": sum(
                        row["market_days"] for row in fleet_rows
                    ),
                    "no_op_market_days": sum(
                        row["no_op_market_days"] for row in fleet_rows
                    ),
                    **metric_payload,
                    "daily": fleet_rows,
                }
            )
    return output


def target_date_from_day(day):
    return str(day or "").strip().rsplit(" ", 1)[-1]


def market_from_day(day):
    text = str(day or "").strip()
    return text.split()[0] if text else "unknown"


def paired_inference_sensitivities(
    day_tables,
    day_meta,
    *,
    split_dates=None,
    required_market_count=12,
    required_market_ids=None,
):
    """Repeat paired inference under outcome-independent sensitivity scopes."""

    meta_by_day = {
        str(row.get("market_day") or row.get("day") or ""): row
        for row in day_meta
    }
    markets_by_date = defaultdict(set)
    daily_markets_by_date = defaultdict(set)
    for day, row in meta_by_day.items():
        target_date = target_date_from_day(day)
        market_id = market_from_day(day)
        markets_by_date[target_date].add(market_id)
        if str(row.get("settlement_source") or "") == "daily_summary":
            daily_markets_by_date[target_date].add(market_id)

    exact_markets = (
        {str(value) for value in required_market_ids}
        if required_market_ids is not None
        else None
    )

    def complete(markets):
        if exact_markets is not None:
            return markets == exact_markets
        return len(markets) == int(required_market_count)

    complete_dates = {
        target_date
        for target_date, markets in markets_by_date.items()
        if complete(markets)
    }
    daily_complete_dates = {
        target_date
        for target_date, markets in daily_markets_by_date.items()
        if complete(markets)
    }
    all_days = set(meta_by_day)
    daily_days = {
        day
        for day, row in meta_by_day.items()
        if str(row.get("settlement_source") or "") == "daily_summary"
    }
    output = []
    for variant, rows in day_tables.items():
        variant_markets_by_date = defaultdict(set)
        for row in rows:
            day = str(row.get("market_day") or row.get("day") or "")
            variant_markets_by_date[target_date_from_day(day)].add(
                market_from_day(day)
            )
        variant_complete_dates = {
            target_date
            for target_date, markets in variant_markets_by_date.items()
            if complete(markets) and target_date in complete_dates
        }
        variant_daily_complete_dates = (
            variant_complete_dates & daily_complete_dates
        )
        scopes = {
            "all_pinned": all_days,
            "configured_daily_summary_only": daily_days,
            "complete_12_market_panel": {
                day
                for day in all_days
                if target_date_from_day(day) in variant_complete_dates
            },
            "daily_summary_complete_exact_market_panel": {
                day
                for day in all_days
                if target_date_from_day(day) in variant_daily_complete_dates
            },
        }
        for scope, allowed_days in scopes.items():
            scoped_rows = [
                row
                for row in rows
                if str(row.get("market_day") or row.get("day") or "")
                in allowed_days
            ]
            for inference_row in paired_day_inference(
                {variant: scoped_rows},
                split_dates,
            ):
                output.append({"scope": scope, **inference_row})
    return output


def paired_market_inference(day_tables, split_dates=None, *, day_meta=None):
    """Equal-date paired source effects within each market and split."""

    requested_splits = {"all": None, **(split_dates or {})}
    eligible_days = None
    if day_meta is not None:
        eligible_days = {
            str(row.get("market_day") or row.get("day") or "")
            for row in day_meta
            if str(row.get("settlement_source") or "") == "daily_summary"
        }
    output = []
    for variant, rows in sorted(day_tables.items()):
        for split, date_values in requested_splits.items():
            allowed = set(date_values) if date_values is not None else None
            by_market = defaultdict(list)
            for row in rows:
                day = str(row.get("market_day") or row.get("day") or "")
                if eligible_days is not None and day not in eligible_days:
                    continue
                market_day = row.get("market_day") or row.get("day")
                target_date = target_date_from_day(market_day)
                if allowed is not None and target_date not in allowed:
                    continue
                by_market[market_from_day(market_day)].append(row)
            for market_id, market_rows in sorted(by_market.items()):
                metric_payload = {}
                for metric in ("brier_delta", "logloss_delta"):
                    values = [float(row[metric]) for row in market_rows]
                    digest = hashlib.sha256(
                        f"{variant}|{split}|{market_id}|{metric}".encode(
                            "utf-8"
                        )
                    ).digest()
                    seed = INFERENCE_BOOTSTRAP_SEED + int.from_bytes(
                        digest[:4],
                        "big",
                    )
                    metric_payload[metric] = {
                        "mean": _mean(values),
                        "date_bootstrap_95ci": _cluster_bootstrap(
                            values,
                            seed=seed,
                        ),
                        "sign_test": _sign_test(values),
                    }
                output.append(
                    {
                        "variant": variant,
                        "split": split,
                        "scope": (
                            "configured_daily_summary_only"
                            if eligible_days is not None
                            else "all_pinned"
                        ),
                        "market_id": market_id,
                        "market_days": len(market_rows),
                        "no_op_market_days": sum(
                            abs(float(row["brier_delta"])) <= 1e-15
                            and abs(float(row["logloss_delta"])) <= 1e-15
                            for row in market_rows
                        ),
                        **metric_payload,
                    }
                )
    return output


def summary_day_effect_blockers(summaries, day_tables, *, label="operational"):
    """Cross-check pooled variant summaries against their market-day effects."""

    blockers = []
    summaries = summaries if isinstance(summaries, list) else []
    day_tables = day_tables if isinstance(day_tables, dict) else {}
    for summary in summaries:
        if not isinstance(summary, dict) or not summary.get("variant"):
            continue
        variant_id = summary["variant"]
        rows = day_tables.get(variant_id)
        if not isinstance(rows, list) or not rows:
            continue
        if any(not isinstance(row, dict) for row in rows):
            blockers.append(
                f"{label} {variant_id} day effects cannot be summarized"
            )
            continue
        try:
            weights = [int(row.get("n", row.get("rows"))) for row in rows]
            brier_deltas = [
                float(row.get("brier_delta", row.get("delta"))) for row in rows
            ]
        except (TypeError, ValueError):
            blockers.append(
                f"{label} {variant_id} day effects cannot be summarized"
            )
            continue
        total_support = sum(weights)
        if total_support <= 0:
            blockers.append(
                f"{label} {variant_id} day effects have no positive support"
            )
            continue
        if total_support != summary.get("n", summary.get("rows")):
            blockers.append(
                f"{label} {variant_id} row support differs from day effects"
            )
        if len(rows) != summary.get("market_days", summary.get("days")):
            blockers.append(
                f"{label} {variant_id} market-day support differs from day effects"
            )
        if total_support > 0:
            weighted_brier = sum(
                weight * delta for weight, delta in zip(weights, brier_deltas)
            ) / total_support
            try:
                summary_delta = float(summary.get("delta"))
            except (TypeError, ValueError):
                summary_delta = None
            if summary_delta is None or not math.isclose(
                weighted_brier,
                summary_delta,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                blockers.append(
                    f"{label} {variant_id} pooled delta differs from weighted day effects"
                )
        helped = sum(delta > 0.0001 for delta in brier_deltas)
        hurt = sum(delta < -0.0001 for delta in brier_deltas)
        if helped != summary.get(
            "market_days_source_helped",
            summary.get("days_source_helped"),
        ):
            blockers.append(
                f"{label} {variant_id} helped-day count differs from day effects"
            )
        if hurt != summary.get(
            "market_days_source_hurt",
            summary.get("days_source_hurt"),
        ):
            blockers.append(
                f"{label} {variant_id} hurt-day count differs from day effects"
            )
        brier_fields = (
            summary.get("base_brier"),
            summary.get("variant_brier"),
        )
        if any(value is not None for value in brier_fields):
            try:
                brier_relation = float(brier_fields[1]) - float(brier_fields[0])
                summary_delta = float(summary.get("delta"))
            except (TypeError, ValueError):
                blockers.append(
                    f"{label} {variant_id} Brier summary relation is malformed"
                )
            else:
                if not math.isclose(
                    brier_relation,
                    summary_delta,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    blockers.append(
                        f"{label} {variant_id} Brier summary relation is inconsistent"
                    )
        logloss_fields = (
            summary.get("base_logloss"),
            summary.get("variant_logloss"),
            summary.get("logloss_delta"),
        )
        if any(value is not None for value in logloss_fields):
            try:
                logloss_relation = float(logloss_fields[1]) - float(
                    logloss_fields[0]
                )
                logloss_delta = float(logloss_fields[2])
                day_logloss = [float(row["logloss_delta"]) for row in rows]
            except (KeyError, TypeError, ValueError):
                blockers.append(
                    f"{label} {variant_id} log-loss summary relation is malformed"
                )
            else:
                weighted_logloss = sum(
                    weight * delta
                    for weight, delta in zip(weights, day_logloss)
                ) / total_support
                if not math.isclose(
                    logloss_relation,
                    logloss_delta,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ) or not math.isclose(
                    weighted_logloss,
                    logloss_delta,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    blockers.append(
                        f"{label} {variant_id} log-loss summary differs from day effects"
                    )
    return blockers


SLICE_GROUP_FIELDS = {
    "market": ("market_id",),
    "cutoff_regime": ("cutoff_regime",),
    "market_cutoff_regime": ("market_id", "cutoff_regime"),
    "settlement_distance": ("settlement_distance",),
}


def slice_partition_blockers(
    summaries,
    day_tables,
    slice_effects,
    *,
    label="operational",
):
    """Require every published slice kind to be a complete row partition."""

    summaries = summaries if isinstance(summaries, list) else []
    day_tables = day_tables if isinstance(day_tables, dict) else {}
    slice_effects = slice_effects if isinstance(slice_effects, list) else []
    summary_by_variant = {
        row.get("variant"): row
        for row in summaries
        if isinstance(row, dict) and row.get("variant")
    }
    grouped = defaultdict(list)
    blockers = []
    for index, row in enumerate(slice_effects):
        if not isinstance(row, dict):
            continue
        variant = row.get("variant")
        kind = row.get("slice")
        if variant not in summary_by_variant or kind not in SLICE_GROUP_FIELDS:
            continue
        key_values = []
        malformed_key = False
        for field in SLICE_GROUP_FIELDS[kind]:
            value = row.get(field)
            if not isinstance(value, str) or not value:
                blockers.append(
                    f"{label} slice_effects[{index}].{field} must be non-empty"
                )
                malformed_key = True
            key_values.append(value)
        grouped[(variant, kind)].append((tuple(key_values), row))
        if malformed_key:
            continue
        try:
            base_brier = float(row["base_brier"])
            variant_brier = float(row["variant_brier"])
            delta = float(row["delta"])
        except (KeyError, TypeError, ValueError):
            blockers.append(
                f"{label} slice_effects[{index}] Brier metrics are malformed"
            )
        else:
            if not math.isclose(
                variant_brier - base_brier,
                delta,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                blockers.append(
                    f"{label} slice_effects[{index}] Brier relation is inconsistent"
                )

    for (variant, kind), keyed_rows in grouped.items():
        keys = [key for key, _row in keyed_rows]
        if len(keys) != len(set(keys)):
            blockers.append(
                f"{label} {variant}/{kind} slice grouping keys must be unique"
            )
        rows = [row for _key, row in keyed_rows]
        try:
            weights = [int(row.get("n", row.get("rows"))) for row in rows]
            total = sum(weights)
            summary = summary_by_variant[variant]
            expected_n = int(summary.get("n", summary.get("rows")))
            weighted_base = sum(
                weight * float(row["base_brier"])
                for weight, row in zip(weights, rows)
            ) / total
            weighted_variant = sum(
                weight * float(row["variant_brier"])
                for weight, row in zip(weights, rows)
            ) / total
            weighted_delta = sum(
                weight * float(row["delta"])
                for weight, row in zip(weights, rows)
            ) / total
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            blockers.append(
                f"{label} {variant}/{kind} slice partition cannot be summarized"
            )
            continue
        if total != expected_n:
            blockers.append(
                f"{label} {variant}/{kind} slice support differs from variant rows"
            )
        expected_metrics = (
            ("base Brier", weighted_base, summary.get("base_brier")),
            ("variant Brier", weighted_variant, summary.get("variant_brier")),
            ("delta", weighted_delta, summary.get("delta")),
        )
        for metric_label, observed, expected in expected_metrics:
            try:
                matches = math.isclose(
                    observed,
                    float(expected),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            except (TypeError, ValueError):
                matches = False
            if not matches:
                blockers.append(
                    f"{label} {variant}/{kind} weighted {metric_label} differs from variant summary"
                )
        if kind == "market":
            expected_markets = {
                _market_from_day(row.get("market_day") or row.get("day"))
                for row in (day_tables.get(variant) or [])
                if isinstance(row, dict)
                and (row.get("market_day") or row.get("day"))
            }
            if {key[0] for key in keys} != expected_markets:
                blockers.append(
                    f"{label} {variant}/market slice IDs differ from day effects"
                )
    return blockers


def _valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _receipt_blockers(receipt, label):
    blockers = []
    if not isinstance(receipt, dict):
        return [f"{label} receipt must be an object"]
    if receipt.get("status") != "PASS":
        blockers.append(f"{label} receipt status must be PASS")
    if not isinstance(receipt.get("path"), str) or not receipt.get("path"):
        blockers.append(f"{label} receipt path must be non-empty")
    if not _valid_sha256(receipt.get("sha256")):
        blockers.append(f"{label} receipt sha256 must be a 64-character hex digest")
    size_bytes = receipt.get("size_bytes")
    if (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes <= 0
    ):
        blockers.append(f"{label} receipt size_bytes must be a positive integer")
    if receipt.get("blockers") != []:
        blockers.append(f"{label} PASS receipt must have no blockers")
    return blockers


def _market_from_day(day):
    text = str(day or "").strip()
    return text.split()[0] if text else "unknown"


def _target_date_from_day(day):
    return str(day or "").strip().rsplit(" ", 1)[-1]


def audit_model_bindings(models):
    """Describe the exact serving bundle used by every replay model."""

    market_ids = sorted(str(value) for value in models)
    bundles = [
        getattr(models[market_id], "serving_bundle", None)
        for market_id in market_ids
    ]
    if not bundles or any(bundle is None for bundle in bundles):
        return {
            "status": "MISSING",
            "binding_kind": "verified_active_release",
            "pointer_present": False,
            "base_model_bound": False,
            "market_ids": market_ids,
            "model_count": len(models),
            "shared_explicit_bundle": False,
            "shared_verified_bundle": False,
            "serving_or_release_authorization": False,
        }

    def identity(bundle):
        return (
            getattr(bundle, "status", None),
            bool(getattr(bundle, "pointer_present", False)),
            bool(getattr(bundle, "base_model_bound", False)),
            str(getattr(bundle, "release_id", "") or ""),
            str(getattr(bundle, "manifest_sha256", "") or ""),
            str(getattr(bundle, "pointer_sha256", "") or ""),
            getattr(bundle, "sequence", None),
            str(getattr(bundle, "release_kind", "") or ""),
            bool(getattr(bundle, "production_capable", False)),
            tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in dict(
                        getattr(bundle, "artifact_hashes", {}) or {}
                    ).items()
                )
            ),
        )

    identities = {identity(bundle) for bundle in bundles}
    shared_verified_bundle = len(identities) == 1
    shared_explicit_bundle = len({id(bundle) for bundle in bundles}) == 1
    primary = bundles[0]
    statuses = {str(getattr(bundle, "status", "") or "") for bundle in bundles}
    status = next(iter(statuses)) if len(statuses) == 1 else "MIXED"
    pointer_present = all(
        bool(getattr(bundle, "pointer_present", False)) for bundle in bundles
    )
    base_model_bound = all(
        bool(getattr(bundle, "base_model_bound", False)) for bundle in bundles
    )
    release_id = str(getattr(primary, "release_id", "") or "")
    manifest_sha256 = str(getattr(primary, "manifest_sha256", "") or "")
    pointer_sha256 = str(getattr(primary, "pointer_sha256", "") or "")
    operationally_bound = (
        status == STATUS_BOUND
        and shared_verified_bundle
        and pointer_present
        and base_model_bound
        and bool(release_id)
        and bool(manifest_sha256)
        and bool(pointer_sha256)
    )
    return {
        "status": status,
        "binding_kind": "verified_active_release",
        "pointer_present": pointer_present,
        "base_model_bound": base_model_bound,
        "release_id": release_id,
        "release_manifest_sha256": manifest_sha256,
        "release_pointer_sha256": pointer_sha256,
        "release_sequence": getattr(primary, "sequence", None),
        "release_kind": str(getattr(primary, "release_kind", "") or ""),
        "release_production_capable": bool(
            getattr(primary, "production_capable", False)
        ),
        "artifact_hashes": dict(getattr(primary, "artifact_hashes", {}) or {}),
        "market_ids": market_ids,
        "model_count": len(models),
        "shared_explicit_bundle": shared_explicit_bundle,
        "shared_verified_bundle": shared_verified_bundle,
        "serving_or_release_authorization": operationally_bound,
    }


def _validate_model_binding(
    model_binding,
    day_meta,
    *,
    variant_ids,
    input_receipts,
):
    blockers = []
    if not isinstance(model_binding, dict):
        return ["operational model_binding must be an object"]
    if model_binding.get("binding_kind") == "candidate_artifact":
        blockers.append(
            "operational candidate-artifact binding is disabled until an "
            "independently anchored candidate trust root exists; use a "
            "verified_active_release binding"
        )
        if variant_ids != ["reanalysis_synoptic"]:
            blockers.append(
                "candidate-artifact binding is restricted to reanalysis_synoptic"
            )
        if model_binding.get("status") != "BOUND_CANDIDATE_ARTIFACT":
            blockers.append(
                "candidate model_binding.status must be BOUND_CANDIDATE_ARTIFACT"
            )
        if model_binding.get("promotion_evidence_binding") is not True:
            blockers.append(
                "candidate model_binding.promotion_evidence_binding must be true"
            )
        if model_binding.get("serving_or_release_authorization") is not False:
            blockers.append(
                "candidate model_binding.serving_or_release_authorization must be false"
            )
        if (
            not isinstance(model_binding.get("artifact_path"), str)
            or not model_binding.get("artifact_path")
        ):
            blockers.append("candidate model_binding.artifact_path must be non-empty")
        if not _valid_sha256(model_binding.get("artifact_sha256")):
            blockers.append(
                "candidate model_binding.artifact_sha256 must be a 64-character hex digest"
            )
        if model_binding.get("prediction_mode") != "band_binary":
            blockers.append(
                "candidate model_binding.prediction_mode must equal band_binary"
            )
        artifact_receipt = (
            input_receipts.get("artifact")
            if isinstance(input_receipts, dict)
            else None
        )
        blockers.extend(_receipt_blockers(artifact_receipt, "candidate artifact"))
        if isinstance(artifact_receipt, dict):
            if artifact_receipt.get("path") != model_binding.get("artifact_path"):
                blockers.append(
                    "candidate artifact receipt path differs from model binding"
                )
            if artifact_receipt.get("sha256") != model_binding.get(
                "artifact_sha256"
            ):
                blockers.append(
                    "candidate artifact receipt sha256 differs from model binding"
                )
        return blockers
    if model_binding.get("binding_kind") != "verified_active_release":
        blockers.append(
            "operational model_binding.binding_kind must be verified_active_release"
        )
    if model_binding.get("status") != STATUS_BOUND:
        blockers.append("operational model_binding.status must be BOUND")
    for field in (
        "pointer_present",
        "base_model_bound",
        "shared_explicit_bundle",
        "shared_verified_bundle",
        "serving_or_release_authorization",
    ):
        if model_binding.get(field) is not True:
            blockers.append(f"operational model_binding.{field} must be true")
    if not isinstance(model_binding.get("release_id"), str) or not model_binding.get(
        "release_id"
    ):
        blockers.append("operational model_binding.release_id must be non-empty")
    for field in ("release_manifest_sha256", "release_pointer_sha256"):
        if not _valid_sha256(model_binding.get(field)):
            blockers.append(
                f"operational model_binding.{field} must be a 64-character hex digest"
            )
    market_ids = model_binding.get("market_ids")
    if (
        not isinstance(market_ids, list)
        or not market_ids
        or any(not isinstance(value, str) or not value for value in market_ids)
        or market_ids != sorted(set(market_ids))
    ):
        blockers.append(
            "operational model_binding.market_ids must be a non-empty sorted unique list"
        )
        market_ids = []
    model_count = model_binding.get("model_count")
    if (
        not isinstance(model_count, int)
        or isinstance(model_count, bool)
        or model_count <= 0
        or model_count != len(market_ids)
    ):
        blockers.append(
            "operational model_binding.model_count must match bound market_ids"
        )
    scored_markets = sorted(
        {
            _market_from_day(row.get("market_day") or row.get("day"))
            for row in day_meta
            if isinstance(row, dict)
            and (row.get("market_day") or row.get("day"))
        }
    )
    if market_ids and market_ids != scored_markets:
        blockers.append(
            "operational model_binding.market_ids must match scored market-days"
        )
    return blockers


def validate_operational_evidence_inputs(
    summaries,
    day_tables,
    day_meta,
    include_reconstructed,
    corpus_manifest,
    paired_inference,
    robustness_inference,
    market_inference,
    split_dates,
    model_binding,
    input_receipts,
    requested_sources,
    slice_effects,
    *,
    normalize,
):
    """Validate every prerequisite before an operational schema can be emitted."""

    blockers = []
    if include_reconstructed is not False:
        blockers.append("operational evidence forbids reconstructed replay inputs")
    candidate_binding = (
        isinstance(model_binding, dict)
        and model_binding.get("binding_kind") == "candidate_artifact"
    )
    expected_requested_variants = ()
    if candidate_binding:
        blockers.append(
            "operational replay requires verified_active_release model bytes; "
            "candidate-artifact evidence remains research-only"
        )
    try:
        expected_requested_variants = exact_requested_variants(
            requested_sources or ()
        )
    except SourceAblationContractError as exc:
        blockers.append(
            "active-release operational replay must request the exact canonical "
            f"variant family: {exc}"
        )

    entries = []
    corpus_target_dates = set()
    corpus_market_ids = set()
    corpus_day_ids = []
    if not isinstance(corpus_manifest, dict):
        blockers.append("operational evidence requires a promotion corpus manifest")
    else:
        if "materialization" in corpus_manifest:
            blockers.append(
                "operational promotion corpus cannot be a research-derived materialization"
            )
        if (
            "research_only" in corpus_manifest
            and corpus_manifest.get("research_only") is not False
        ):
            blockers.append("operational promotion corpus cannot be research-only")
        if corpus_manifest.get("serving_or_release_authorization") is False:
            blockers.append(
                "operational promotion corpus cannot carry a non-authorizing marker"
            )
        if corpus_manifest.get("schema_version") != PROMOTION_CORPUS_SCHEMA_VERSION:
            blockers.append("operational promotion corpus schema is missing or stale")
        entries = corpus_manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            blockers.append("operational promotion corpus entries must be non-empty")
            entries = []
        if corpus_manifest.get("include_reconstructed") is not False:
            blockers.append(
                "operational promotion corpus must explicitly exclude reconstructed inputs"
            )
        if corpus_manifest.get("allow_unsettled") is not False:
            blockers.append(
                "operational promotion corpus must explicitly exclude unsettled inputs"
            )
        if corpus_manifest.get("market_filter") is not None:
            blockers.append("operational promotion corpus must not use a market filter")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                blockers.append(f"operational promotion corpus entry {index} is malformed")
                continue
            target_date = entry.get("target_date")
            market_id = entry.get("market_id")
            if not isinstance(target_date, str) or not target_date:
                blockers.append(
                    f"operational promotion corpus entry {index} lacks target_date"
                )
            else:
                corpus_target_dates.add(target_date)
            if not isinstance(market_id, str) or not market_id:
                blockers.append(
                    f"operational promotion corpus entry {index} lacks market_id"
                )
            else:
                corpus_market_ids.add(market_id)
            if (
                isinstance(target_date, str)
                and target_date
                and isinstance(market_id, str)
                and market_id
            ):
                corpus_day_ids.append(f"{market_id} {target_date}")
        if len(corpus_day_ids) != len(set(corpus_day_ids)):
            blockers.append(
                "operational promotion corpus market-days must be unique"
            )
        if sorted(corpus_market_ids) != sorted(REGISTRY):
            blockers.append(
                "operational promotion corpus markets must exactly match the registry"
            )
        expected_corpus_day_ids = {
            f"{market_id} {target_date}"
            for market_id in sorted(REGISTRY)
            for target_date in corpus_target_dates
        }
        if (
            set(corpus_day_ids) != expected_corpus_day_ids
            or len(corpus_day_ids) != len(expected_corpus_day_ids)
        ):
            blockers.append(
                "operational promotion corpus must exactly cover the registry/date panel"
            )
        try:
            expected_corpus_hash = corpus_hash(entries)
        except (KeyError, TypeError, ValueError):
            blockers.append("operational promotion corpus entries cannot be hashed")
        else:
            if corpus_manifest.get("corpus_hash") != expected_corpus_hash:
                blockers.append("operational promotion corpus hash is invalid")
        corpus_summary = corpus_manifest.get("summary")
        if not isinstance(corpus_summary, dict):
            blockers.append("operational promotion corpus summary must be an object")
        else:
            if corpus_summary.get("market_day_count") != len(entries):
                blockers.append(
                    "operational promotion corpus market-day count is inconsistent"
                )
            snapshot_count = corpus_summary.get("snapshot_count")
            if (
                not isinstance(snapshot_count, int)
                or isinstance(snapshot_count, bool)
                or snapshot_count <= 0
            ):
                blockers.append(
                    "operational promotion corpus snapshot count must be positive"
                )

    if not isinstance(input_receipts, dict):
        blockers.append("operational evidence input_receipts must be an object")
        input_receipts = {}
    for key, label in (
        ("corpus", "promotion corpus"),
        ("tune_dates", "tune dates"),
        ("holdout_dates", "holdout dates"),
    ):
        blockers.extend(_receipt_blockers(input_receipts.get(key), label))
    corpus_receipt = input_receipts.get("corpus")
    if (
        isinstance(corpus_manifest, dict)
        and isinstance(corpus_receipt, dict)
        and corpus_manifest.get("_path") != corpus_receipt.get("path")
    ):
        blockers.append("promotion corpus receipt path differs from the loaded corpus")

    if not isinstance(split_dates, dict) or set(split_dates) != {"tune", "holdout"}:
        blockers.append("operational split_dates must contain exactly tune and holdout")
        normalized_splits = {"tune": [], "holdout": []}
    else:
        normalized_splits = {}
        for split in ("tune", "holdout"):
            values = split_dates.get(split)
            if (
                not isinstance(values, list)
                or not values
                or any(not isinstance(value, str) or not value for value in values)
                or values != sorted(set(values))
            ):
                blockers.append(
                    f"operational {split} dates must be a non-empty sorted unique list"
                )
                normalized_splits[split] = []
            else:
                normalized_splits[split] = values
        if set(normalized_splits["tune"]) & set(normalized_splits["holdout"]):
            blockers.append("operational tune and holdout dates must be disjoint")
        if (
            corpus_target_dates
            and set(normalized_splits["tune"]) | set(normalized_splits["holdout"])
            != corpus_target_dates
        ):
            blockers.append(
                "operational tune and holdout dates must exactly partition corpus dates"
            )

    if not isinstance(day_meta, list) or not day_meta:
        blockers.append("operational market_days must be a non-empty list")
        day_ids = []
    else:
        day_ids = [
            str(row.get("market_day") or row.get("day") or "")
            if isinstance(row, dict)
            else ""
            for row in day_meta
        ]
        if any(not value for value in day_ids):
            blockers.append("operational market_days rows must identify a market-day")
        if len(day_ids) != len(set(day_ids)):
            blockers.append("operational market_days must contain unique market-days")
        if any(
            not isinstance(row, dict)
            or row.get("settlement_source") != "daily_summary"
            for row in day_meta
        ):
            blockers.append(
                "operational market-days must use daily_summary settlement provenance"
            )
        scored_dates = {_target_date_from_day(value) for value in day_ids if value}
        allocated_dates = set(normalized_splits["tune"]) | set(
            normalized_splits["holdout"]
        )
        if allocated_dates and not scored_dates.issubset(allocated_dates):
            blockers.append(
                "operational scored market-days must belong to the sealed date split"
            )
        if set(day_ids) != set(corpus_day_ids) or len(day_ids) != len(
            corpus_day_ids
        ):
            blockers.append(
                "operational scored market-days must exactly match promotion corpus entries"
            )

    variant_ids = [
        str(row.get("variant") or "")
        for row in summaries
        if isinstance(row, dict) and row.get("variant")
    ]
    candidate_reanalysis = candidate_binding and variant_ids == [
        "reanalysis_synoptic"
    ]
    if candidate_binding:
        if variant_ids != ["reanalysis_synoptic"]:
            blockers.append(
                "candidate-artifact scored variants must equal reanalysis_synoptic"
            )
    elif (
        len(variant_ids) != len(set(variant_ids))
        or set(variant_ids) != set(expected_requested_variants)
    ):
        blockers.append(
            "active-release scored variants must exactly equal the canonical requested family"
        )
    for index, row in enumerate(summaries):
        if not isinstance(row, dict):
            continue
        variant_id = row.get("variant")
        try:
            expected_members = list(members_for_variant(variant_id))
        except SourceAblationContractError:
            expected_members = (
                ["reanalysis_synoptic"]
                if candidate_reanalysis and variant_id == "reanalysis_synoptic"
                else None
            )
        if expected_members is None:
            blockers.append(
                f"operational variants[{index}].variant is not canonical"
            )
        elif row.get("ablated_sources") != expected_members:
            blockers.append(
                f"operational variants[{index}].ablated_sources differ from canonical membership"
            )
    if (
        not isinstance(day_tables, dict)
        or set(day_tables) != set(variant_ids)
        or not variant_ids
    ):
        blockers.append(
            "operational day_effects keys must exactly match non-empty scored variants"
        )
    else:
        for variant_id, rows in day_tables.items():
            expected_day_ids = {
                f"{market_id} {target_date}"
                for market_id in applicable_market_ids_for_variant(variant_id)
                for target_date in corpus_target_dates
            }
            observed_day_ids = [
                str(row.get("market_day") or row.get("day") or "")
                for row in rows
                if isinstance(row, dict)
            ]
            if len(observed_day_ids) != len(set(observed_day_ids)):
                blockers.append(
                    f"operational {variant_id} day effects contain duplicate market-days"
                )
            if (
                not set(observed_day_ids).issubset(expected_day_ids)
            ):
                blockers.append(
                    f"operational {variant_id} day effects exceed its sealed applicable market/date panel"
                )
    blockers.extend(
        summary_day_effect_blockers(
            summaries,
            day_tables,
            label="operational",
        )
    )
    blockers.extend(
        slice_partition_blockers(
            summaries,
            day_tables,
            slice_effects,
            label="operational",
        )
    )

    expected_paired = []
    expected_robustness = []
    expected_market = []
    try:
        expected_paired = paired_day_inference(day_tables, normalized_splits)
        expected_robustness = paired_inference_sensitivities(
            day_tables,
            day_meta,
            split_dates=normalized_splits,
            required_market_ids=tuple(sorted(REGISTRY)),
        )
        expected_market = paired_market_inference(
            day_tables,
            normalized_splits,
            day_meta=day_meta,
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        blockers.append(f"operational inference could not be recomputed: {exc}")
    else:
        if normalize(paired_inference or []) != normalize(expected_paired):
            blockers.append("operational paired inference differs from recomputation")
        if normalize(robustness_inference or []) != normalize(expected_robustness):
            blockers.append(
                "operational robustness inference differs from recomputation"
            )
        if normalize(market_inference or []) != normalize(expected_market):
            blockers.append("operational market inference differs from recomputation")
        for variant_id in variant_ids:
            for split in ("tune", "holdout"):
                row = next(
                    (
                        value
                        for value in expected_paired
                        if value.get("variant") == variant_id
                        and value.get("split") == split
                    ),
                    None,
                )
                if (
                    row is None
                    or int(row.get("fleet_dates") or 0) <= 0
                    or int(row.get("market_days") or 0) <= 0
                ):
                    blockers.append(
                        f"operational {variant_id}/{split} paired inference has no support"
                    )
            if not any(
                row.get("variant") == variant_id
                and row.get("split") == "holdout"
                and int(row.get("market_days") or 0) > 0
                for row in expected_market
            ):
                blockers.append(
                    f"operational {variant_id}/holdout market inference has no support"
                )

    blockers.extend(
        _validate_model_binding(
            model_binding,
            day_meta,
            variant_ids=variant_ids,
            input_receipts=input_receipts,
        )
    )
    if blockers:
        raise ValueError(
            "operational source-ablation evidence contract failed: "
            + "; ".join(blockers)
        )
