"""Render and dispatch the sealed source-ablation synthesis.

The public entrypoint consumes one committed 22-treatment generation through
the hardened verifier, recomputes inference, and applies the sealed Holm
families.  It does not rerun replay, mutate inputs, or publish loose output
leaves.  A private historical reader remains solely to interpret pre-seal
multi-batch evidence; neither the CLI nor the public synthesis API exposes it.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from weather.backtesting.replay_ablation import (
    paired_inference_sensitivities,
    paired_market_inference,
)
from weather.backtesting.source_ablation_contract import ALL_VARIANTS, VARIANT_MEMBERS
from weather.reporting.research.source_ablation_hardened import (
    TERMINAL_FEASIBILITY_SHA256,
    TERMINAL_MARKET_IDS,
    TERMINAL_PREREGISTRATION_SHA256,
    TERMINAL_SUPPORT_SHA256,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("source_ablation_synthesis")
SOURCE_ARTIFACT_SCHEMA_VERSION = schema_version("source_family_ablation_research")
PRIMARY_SCOPE = "daily_summary_complete_exact_market_panel"
SECONDARY_SCOPE = "configured_daily_summary_only"
PRIMARY_SPLIT = "holdout"
METRICS = ("brier_delta", "logloss_delta")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
EXPECTED_ROBUSTNESS_CONTRACT = {
    "settlement_scope": "promotion_corpus settlement_source exactly equals daily_summary",
    "complete_panel_scope": (
        "corpus and variant-scored market-ID sets both exactly equal the sealed "
        "12-market set; support selected without outcomes"
    ),
    "cluster_unit": "fleet target date",
    "primary_market_ids": list(TERMINAL_MARKET_IDS),
    "per_market_action_scope": "holdout promotion-corpus daily_summary market-days only",
    "outcome_independent_scope_selection": True,
}


class SourceAblationSynthesisError(ValueError):
    """Raised when source-ablation inputs do not share one valid contract."""


def _sha256(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SourceAblationSynthesisError(
            f"source-ablation artifact changed while hashing: {path}"
        )
    return digest.hexdigest()


def _finite_probability(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    return parsed


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    return parsed


def _count(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}") from exc
    if parsed < 0 or parsed != value:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    return parsed


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Return Holm step-down family-wise adjusted p-values."""

    parsed = [
        _finite_probability(value, label=f"p_values[{index}]")
        for index, value in enumerate(p_values)
    ]
    count = len(parsed)
    adjusted = [0.0] * count
    running = 0.0
    for rank, (index, value) in enumerate(
        sorted(enumerate(parsed), key=lambda item: (item[1], item[0])),
        start=1,
    ):
        running = max(running, (count - rank + 1) * value)
        adjusted[index] = min(1.0, running)
    return adjusted


def validate_output_paths(
    *,
    read_only_data_root: str | Path,
    input_artifacts: Sequence[str | Path],
    output_json: str | Path,
    output_report: str | Path,
) -> tuple[Path, Path]:
    """Resolve outputs and reject aliases into inputs or ``data/``."""

    data_root = Path(read_only_data_root).expanduser().resolve(strict=True)
    if not data_root.is_dir():
        raise SourceAblationSynthesisError(
            f"read-only data root is not a directory: {data_root}"
        )
    if not input_artifacts:
        raise SourceAblationSynthesisError("at least one input artifact is required")
    resolved_inputs: list[Path] = []
    for raw_path in input_artifacts:
        try:
            input_path = Path(raw_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise SourceAblationSynthesisError(
                f"cannot resolve source-ablation artifact {raw_path}: {exc}"
            ) from exc
        if not input_path.is_file():
            raise SourceAblationSynthesisError(
                f"artifact is not a file: {input_path}"
            )
        resolved_inputs.append(input_path)
    outputs = []
    for label, raw_path in (
        ("output_json", output_json),
        ("output_report", output_report),
    ):
        target = Path(raw_path).expanduser().resolve(strict=False)
        try:
            target.relative_to(data_root)
        except ValueError:
            pass
        else:
            raise SourceAblationSynthesisError(
                f"{label} resolves inside the read-only data root: {target}"
            )
        for input_path in resolved_inputs:
            aliases_input = target == input_path
            if not aliases_input and target.exists():
                try:
                    aliases_input = target.samefile(input_path)
                except OSError:
                    aliases_input = False
            if aliases_input:
                raise SourceAblationSynthesisError(
                    f"{label} must not overwrite input artifact: {input_path}"
                )
        outputs.append(target)
    outputs_alias = outputs[0] == outputs[1]
    if not outputs_alias and outputs[0].exists() and outputs[1].exists():
        try:
            outputs_alias = outputs[0].samefile(outputs[1])
        except OSError:
            outputs_alias = False
    if outputs_alias:
        raise SourceAblationSynthesisError("JSON and report outputs must differ")
    return outputs[0], outputs[1]


def _load_artifact(path: str | Path) -> tuple[Path, dict[str, Any]]:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        before = resolved.stat()
    except OSError as exc:
        raise SourceAblationSynthesisError(
            f"cannot resolve source-ablation artifact {path}: {exc}"
        ) from exc
    if not resolved.is_file():
        raise SourceAblationSynthesisError(f"artifact is not a file: {resolved}")
    if before.st_size > MAX_ARTIFACT_BYTES:
        raise SourceAblationSynthesisError(
            f"source-ablation artifact exceeds {MAX_ARTIFACT_BYTES} bytes: {resolved}"
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceAblationSynthesisError(
            f"cannot read source-ablation artifact {resolved}: {exc}"
        ) from exc
    after = resolved.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SourceAblationSynthesisError(
            f"source-ablation artifact changed while reading: {resolved}"
        )
    if not isinstance(payload, dict):
        raise SourceAblationSynthesisError(
            f"artifact root must be an object: {resolved}"
        )
    if payload.get("schema_version") != SOURCE_ARTIFACT_SCHEMA_VERSION:
        raise SourceAblationSynthesisError(
            "unexpected source-ablation schema in "
            f"{resolved}: expected {SOURCE_ARTIFACT_SCHEMA_VERSION!r}"
        )
    return resolved, payload


def _variant_names(payload: Mapping[str, Any]) -> list[str]:
    requested = [str(value) for value in payload.get("requested_variants") or []]
    if not requested:
        requested = [
            str(row.get("variant") or "")
            for row in payload.get("variants") or []
        ]
    if not requested or any(not value for value in requested):
        raise SourceAblationSynthesisError("artifact has no valid variants")
    if requested != list(dict.fromkeys(requested)):
        raise SourceAblationSynthesisError("artifact contains duplicate variants")
    return requested


def _variant_membership(
    payload: Mapping[str, Any],
    *,
    variants: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    rows = payload.get("variants")
    if not isinstance(rows, list):
        raise SourceAblationSynthesisError(
            "artifact variants must preserve exact ablated_sources membership"
        )
    membership: dict[str, tuple[str, ...]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise SourceAblationSynthesisError("artifact variant row is not an object")
        variant = str(raw_row.get("variant") or "")
        sources = tuple(str(value) for value in raw_row.get("ablated_sources") or [])
        if not variant or not sources or any(not value for value in sources):
            raise SourceAblationSynthesisError(
                "artifact variant has blank variant or ablated_sources membership"
            )
        if variant in membership:
            raise SourceAblationSynthesisError(
                f"artifact has duplicate variant definition: {variant}"
            )
        if len(set(sources)) != len(sources):
            raise SourceAblationSynthesisError(
                f"artifact variant has duplicate ablated sources: {variant}"
            )
        membership[variant] = sources
    if set(membership) != set(variants):
        raise SourceAblationSynthesisError(
            "requested variants and ablated_sources definitions do not match"
        )
    return membership


def _iso_date(value: Any, *, label: str) -> str:
    text = str(value or "")
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}") from exc
    if parsed.isoformat() != text:
        raise SourceAblationSynthesisError(f"invalid {label}: {value!r}")
    return text


def _split_date_attestation(
    payload: Mapping[str, Any],
    *,
    variants: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    """Verify explicit tune/holdout allocation and supported daily-row subsets."""

    robustness_rows = payload.get("robustness_inference")
    if not isinstance(robustness_rows, list):
        raise SourceAblationSynthesisError(
            "artifact robustness_inference must be an array"
        )
    raw_attestation = payload.get("split_dates")
    if not isinstance(raw_attestation, Mapping) or set(raw_attestation) != {
        "tune",
        PRIMARY_SPLIT,
    }:
        raise SourceAblationSynthesisError(
            "artifact must explicitly attest tune and holdout date allocations"
        )
    attestation: dict[str, tuple[str, ...]] = {}
    for split in ("tune", PRIMARY_SPLIT):
        raw_dates = raw_attestation.get(split)
        if not isinstance(raw_dates, list):
            raise SourceAblationSynthesisError(
                f"explicit {split} date allocation must be an array"
            )
        dates = tuple(
            _iso_date(value, label=f"explicit {split} target_date")
            for value in raw_dates
        )
        if not dates or dates != tuple(sorted(set(dates))):
            raise SourceAblationSynthesisError(
                f"explicit {split} date allocation must be non-empty, sorted, and unique"
            )
        attestation[split] = dates

    for split in ("tune", PRIMARY_SPLIT):
        selected = [
            row
            for row in robustness_rows
            if isinstance(row, Mapping)
            and str(row.get("scope") or "") == "all_pinned"
            and str(row.get("split") or "") == split
        ]
        by_variant = {str(row.get("variant") or ""): row for row in selected}
        if len(selected) != len(by_variant) or set(by_variant) != set(variants):
            raise SourceAblationSynthesisError(
                f"all-pinned {split} rows do not map one-to-one to variants"
            )
        allowed_dates = set(attestation[split])
        for variant, row in by_variant.items():
            fleet_dates = _count(
                row.get("fleet_dates"), label=f"{variant}/{split} fleet_dates"
            )
            daily = row.get("daily")
            if not isinstance(daily, list) or len(daily) != fleet_dates:
                raise SourceAblationSynthesisError(
                    f"{variant}/{split} daily rows do not match fleet_dates"
                )
            row_dates = [
                _iso_date(
                    item.get("target_date") if isinstance(item, Mapping) else None,
                    label=f"{variant}/{split} target_date",
                )
                for item in daily
            ]
            if len(set(row_dates)) != len(row_dates):
                raise SourceAblationSynthesisError(
                    f"{variant}/{split} contains duplicate fleet dates"
                )
            outside = sorted(set(row_dates) - allowed_dates)
            if outside:
                raise SourceAblationSynthesisError(
                    f"{variant}/{split} contains dates outside its explicit allocation: "
                    + ", ".join(outside)
                )
    overlap = set(attestation["tune"]).intersection(attestation[PRIMARY_SPLIT])
    if overlap:
        raise SourceAblationSynthesisError(
            "tune and holdout date allocations overlap: " + ", ".join(sorted(overlap))
        )
    return attestation


def _metric_sign_p(row: Mapping[str, Any], metric: str) -> float:
    try:
        value = row[metric]["sign_test"]["two_sided_p"]
    except (KeyError, TypeError) as exc:
        raise SourceAblationSynthesisError(
            f"inference is missing {metric} sign-test p-value"
        ) from exc
    return _finite_probability(value, label=f"{metric} sign-test p-value")


def _validate_metric(
    metric_payload: Any,
    *,
    market: bool,
    observations: int,
    label: str,
) -> None:
    if not isinstance(metric_payload, Mapping):
        raise SourceAblationSynthesisError(f"{label} metric is not an object")
    _finite_number(metric_payload.get("mean"), label=f"{label} mean")
    low, high = _ci(metric_payload, market=market)
    if low > high:
        raise SourceAblationSynthesisError(f"{label} bootstrap interval is reversed")

    interval_key = "date_bootstrap_95ci" if market else "cluster_bootstrap_95ci"
    interval = metric_payload[interval_key]
    replicates = _count(
        interval.get("replicates"), label=f"{label} bootstrap replicates"
    )
    if replicates != 10_000:
        raise SourceAblationSynthesisError(
            f"{label} must preserve the 10000-replicate bootstrap contract"
        )
    _count(interval.get("seed"), label=f"{label} bootstrap seed")

    sign_test = metric_payload.get("sign_test")
    if not isinstance(sign_test, Mapping):
        raise SourceAblationSynthesisError(f"{label} sign_test is not an object")
    improvements = _count(
        sign_test.get("improvements"), label=f"{label} sign-test improvements"
    )
    regressions = _count(
        sign_test.get("regressions"), label=f"{label} sign-test regressions"
    )
    ties = _count(sign_test.get("ties"), label=f"{label} sign-test ties")
    non_ties = _count(
        sign_test.get("non_ties"), label=f"{label} sign-test non_ties"
    )
    if improvements + regressions != non_ties:
        raise SourceAblationSynthesisError(
            f"{label} sign-test non_ties is inconsistent"
        )
    if non_ties + ties != observations:
        raise SourceAblationSynthesisError(
            f"{label} sign-test counts do not match observations"
        )
    _finite_probability(
        sign_test.get("two_sided_p"), label=f"{label} sign-test p-value"
    )


def add_market_holm_adjustments(
    rows: Sequence[Mapping[str, Any]],
    *,
    split: str = PRIMARY_SPLIT,
) -> list[dict[str, Any]]:
    """Apply one correction family per score across all variant/market tests."""

    selected = [
        copy.deepcopy(dict(row))
        for row in rows
        if str(row.get("split") or "") == split
    ]
    selected.sort(
        key=lambda row: (str(row.get("variant")), str(row.get("market_id")))
    )
    for metric in METRICS:
        p_values = [_metric_sign_p(row, metric) for row in selected]
        adjusted = holm_adjust(p_values)
        for row, raw_p, adjusted_p in zip(selected, p_values, adjusted):
            row[metric]["multiplicity"] = {
                "method": "holm_family_wise_error_rate",
                "family": f"all_{split}_variant_market_{metric}_sign_tests",
                "tests": len(selected),
                "raw_p": raw_p,
                "adjusted_p": adjusted_p,
            }
    return selected


def add_primary_holm_adjustments(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Correct supported strict-panel variant tests separately per score."""

    output = [copy.deepcopy(dict(row)) for row in rows]
    supported = [row for row in output if int(row.get("fleet_dates") or 0) > 0]
    for metric in METRICS:
        p_values = [_metric_sign_p(row, metric) for row in supported]
        adjusted = holm_adjust(p_values)
        for row, raw_p, adjusted_p in zip(supported, p_values, adjusted):
            row[metric]["multiplicity"] = {
                "method": "holm_family_wise_error_rate",
                "family": f"all_{PRIMARY_SPLIT}_strict_variant_{metric}_sign_tests",
                "tests": len(supported),
                "raw_p": raw_p,
                "adjusted_p": adjusted_p,
            }
    return output


def _ci(metric_payload: Mapping[str, Any], *, market: bool) -> tuple[float, float]:
    key = "date_bootstrap_95ci" if market else "cluster_bootstrap_95ci"
    try:
        interval = metric_payload[key]
        if not isinstance(interval, Mapping):
            raise TypeError(f"{key} is not an object")
        return (
            _finite_number(interval["low"], label=f"{key} low"),
            _finite_number(interval["high"], label=f"{key} high"),
        )
    except (KeyError, TypeError) as exc:
        raise SourceAblationSynthesisError(
            f"metric is missing a valid {key}"
        ) from exc


def _market_disposition(row: Mapping[str, Any], *, alpha: float = 0.05) -> str:
    directions = []
    for metric in METRICS:
        payload = row[metric]
        mean = _finite_number(payload["mean"], label=f"market {metric} mean")
        low, high = _ci(payload, market=True)
        adjusted_p = _finite_probability(
            payload["multiplicity"]["adjusted_p"],
            label=f"market {metric} adjusted p-value",
        )
        if mean > 0.0 and low > 0.0 and adjusted_p <= alpha:
            directions.append("helps")
        elif mean < 0.0 and high < 0.0 and adjusted_p <= alpha:
            directions.append("harms")
        else:
            directions.append("inconclusive")
    if directions == ["helps", "helps"]:
        return "source_helps_both_scores_after_holm"
    if directions == ["harms", "harms"]:
        return "source_harms_both_scores_after_holm"
    return "no_city_action_after_holm"


def _overall_disposition(
    row: Mapping[str, Any], *, require_holm: bool
) -> str:
    if int(row.get("fleet_dates") or 0) <= 0:
        return (
            "unsupported_strict_panel"
            if require_holm
            else "unsupported_daily_summary_scope"
        )
    directions = []
    for metric in METRICS:
        payload = row[metric]
        mean = _finite_number(payload["mean"], label=f"overall {metric} mean")
        low, high = _ci(payload, market=False)
        clears_multiplicity = True
        if require_holm:
            clears_multiplicity = (
                _finite_probability(
                    payload["multiplicity"]["adjusted_p"],
                    label=f"overall {metric} adjusted p-value",
                )
                <= 0.05
            )
        if mean > 0.0 and low > 0.0 and clears_multiplicity:
            directions.append("helps")
        elif mean < 0.0 and high < 0.0 and clears_multiplicity:
            directions.append("harms")
        else:
            directions.append("inconclusive")
    if directions == ["helps", "helps"]:
        return (
            "source_helps_both_scores_after_holm"
            if require_holm
            else "descriptive_source_helps_both_scores"
        )
    if directions == ["harms", "harms"]:
        return (
            "source_harms_both_scores_after_holm"
            if require_holm
            else "descriptive_source_harms_both_scores"
        )
    return (
        "no_strict_action_after_holm"
        if require_holm
        else "descriptive_mixed_or_inconclusive"
    )


def _validate_fleet_row(
    row: Mapping[str, Any],
    *,
    scope: str,
    strict_panel: bool,
) -> None:
    variant = str(row.get("variant") or "")
    fleet_dates = _count(
        row.get("fleet_dates"), label=f"{variant}/{scope} fleet_dates"
    )
    market_days = _count(
        row.get("market_days"), label=f"{variant}/{scope} market_days"
    )
    no_op = _count(
        row.get("no_op_market_days"),
        label=f"{variant}/{scope} no_op_market_days",
    )
    if no_op > market_days:
        raise SourceAblationSynthesisError(
            f"{variant}/{scope} no-op count exceeds market-days"
        )
    daily = row.get("daily")
    if not isinstance(daily, list) or len(daily) != fleet_dates:
        raise SourceAblationSynthesisError(
            f"{variant}/{scope} daily rows do not match fleet_dates"
        )
    if fleet_dates == 0:
        if market_days != 0 or daily:
            raise SourceAblationSynthesisError(
                f"{variant}/{scope} unsupported row has scored observations"
            )
        return
    if market_days <= 0:
        raise SourceAblationSynthesisError(
            f"{variant}/{scope} supported row has no market-days"
        )
    seen_dates: set[str] = set()
    daily_market_days = 0
    for item in daily:
        if not isinstance(item, Mapping):
            raise SourceAblationSynthesisError(
                f"{variant}/{scope} daily row is not an object"
            )
        target_date = _iso_date(
            item.get("target_date"), label=f"{variant}/{scope} target_date"
        )
        if target_date in seen_dates:
            raise SourceAblationSynthesisError(
                f"{variant}/{scope} contains duplicate fleet dates"
            )
        seen_dates.add(target_date)
        count = _count(
            item.get("market_days"),
            label=f"{variant}/{scope}/{target_date} market_days",
        )
        if strict_panel and count != 12:
            raise SourceAblationSynthesisError(
                f"{variant}/{scope}/{target_date} is not an exact 12-market panel"
            )
        daily_market_days += count
        for metric in METRICS:
            _finite_number(
                item.get(metric), label=f"{variant}/{scope}/{target_date} {metric}"
            )
    if daily_market_days != market_days:
        raise SourceAblationSynthesisError(
            f"{variant}/{scope} daily market-days do not match aggregate"
        )
    for metric in METRICS:
        _validate_metric(
            row.get(metric),
            market=False,
            observations=fleet_dates,
            label=f"{variant}/{scope} {metric}",
        )


def _validate_market_row(row: Mapping[str, Any]) -> None:
    variant = str(row.get("variant") or "")
    market_id = str(row.get("market_id") or "")
    market_days = _count(
        row.get("market_days"), label=f"{variant}/{market_id} market_days"
    )
    if market_days <= 0:
        raise SourceAblationSynthesisError(
            f"{variant}/{market_id} has no holdout market-days"
        )
    no_op = _count(
        row.get("no_op_market_days"),
        label=f"{variant}/{market_id} no_op_market_days",
    )
    if no_op > market_days:
        raise SourceAblationSynthesisError(
            f"{variant}/{market_id} no-op count exceeds market-days"
        )
    for metric in METRICS:
        _validate_metric(
            row.get(metric),
            market=True,
            observations=market_days,
            label=f"{variant}/{market_id} {metric}",
        )


def _legacy_multi_batch_synthesize(
    artifact_paths: Iterable[str | Path],
) -> dict[str, Any]:
    """Retained private reader for historical pre-seal research artifacts."""

    loaded = [_load_artifact(path) for path in artifact_paths]
    if not loaded:
        raise SourceAblationSynthesisError("at least one artifact is required")

    corpus_identities: set[tuple[str, str, int, int]] = set()
    corpus_hashes: set[str] = set()
    for path, payload in loaded:
        corpus = payload.get("corpus")
        if not isinstance(corpus, Mapping):
            raise SourceAblationSynthesisError(
                f"artifact does not bind a pinned corpus: {path}"
            )
        corpus_hash = str(corpus.get("corpus_hash") or "")
        if corpus.get("input_verification") != "PASS":
            raise SourceAblationSynthesisError(
                f"artifact corpus input verification is not PASS: {path}"
            )
        as_of = _iso_date(corpus.get("as_of"), label=f"{path} corpus as_of")
        market_day_count = _count(
            corpus.get("market_day_count"), label=f"{path} corpus market_day_count"
        )
        snapshot_count = _count(
            corpus.get("snapshot_count"), label=f"{path} corpus snapshot_count"
        )
        if not corpus_hash or market_day_count <= 0 or snapshot_count <= 0:
            raise SourceAblationSynthesisError(
                f"artifact has incomplete pinned-corpus identity: {path}"
            )
        corpus_hashes.add(corpus_hash)
        corpus_identities.add(
            (corpus_hash, as_of, market_day_count, snapshot_count)
        )
    if "" in corpus_hashes or len(corpus_hashes) != 1:
        raise SourceAblationSynthesisError(
            "all artifacts must bind the same non-empty corpus hash"
        )
    if len(corpus_identities) != 1:
        raise SourceAblationSynthesisError(
            "source-ablation corpus identity fields differ"
        )
    if any(
        payload.get("robustness_contract") != EXPECTED_ROBUSTNESS_CONTRACT
        for _, payload in loaded
    ):
        raise SourceAblationSynthesisError(
            "source-ablation robustness contract is missing or non-canonical"
        )
    reconstructed_flags = [
        payload.get("include_reconstructed") for _, payload in loaded
    ]
    if any(type(value) is not bool for value in reconstructed_flags) or len(
        set(reconstructed_flags)
    ) != 1:
        raise SourceAblationSynthesisError(
            "source-ablation include_reconstructed contracts differ"
        )
    reconstructed_value = reconstructed_flags[0]

    seen_variants: set[str] = set()
    variant_membership: dict[str, tuple[str, ...]] = {}
    robustness_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    split_attestation: dict[str, tuple[str, ...]] | None = None
    inputs = []
    for path, payload in loaded:
        variants = _variant_names(payload)
        membership = _variant_membership(payload, variants=variants)
        artifact_attestation = _split_date_attestation(payload, variants=variants)
        if split_attestation is None:
            split_attestation = artifact_attestation
        elif split_attestation != artifact_attestation:
            raise SourceAblationSynthesisError(
                "source-ablation tune/holdout date allocations differ"
            )
        duplicates = seen_variants.intersection(variants)
        if duplicates:
            raise SourceAblationSynthesisError(
                "variants occur in multiple artifacts: "
                + ", ".join(sorted(duplicates))
            )
        seen_variants.update(variants)
        variant_membership.update(membership)
        artifact_robustness = payload.get("robustness_inference")
        artifact_markets = payload.get("market_inference")
        if not isinstance(artifact_robustness, list) or not all(
            isinstance(row, Mapping) for row in artifact_robustness
        ):
            raise SourceAblationSynthesisError(
                f"artifact robustness inference is malformed: {path}"
            )
        if not isinstance(artifact_markets, list) or not all(
            isinstance(row, Mapping) for row in artifact_markets
        ):
            raise SourceAblationSynthesisError(
                f"artifact market inference is malformed: {path}"
            )
        robustness_rows.extend(copy.deepcopy(artifact_robustness))
        market_rows.extend(copy.deepcopy(artifact_markets))
        inputs.append(
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "variants": variants,
                "variant_membership": {
                    variant: list(membership[variant]) for variant in variants
                },
            }
        )
    if split_attestation is None:
        raise SourceAblationSynthesisError("split-date attestation is missing")

    primary = [
        dict(row)
        for row in robustness_rows
        if str(row.get("scope") or "") == PRIMARY_SCOPE
        and str(row.get("split") or "") == PRIMARY_SPLIT
    ]
    by_variant = {str(row.get("variant") or ""): row for row in primary}
    if set(by_variant) != seen_variants or len(primary) != len(by_variant):
        missing = sorted(seen_variants - set(by_variant))
        extra = sorted(set(by_variant) - seen_variants)
        raise SourceAblationSynthesisError(
            "strict holdout rows do not map one-to-one to variants: "
            f"missing={missing}, extra={extra}"
        )
    for row in primary:
        _validate_fleet_row(row, scope=PRIMARY_SCOPE, strict_panel=True)
    primary = add_primary_holm_adjustments(primary)
    for row in primary:
        row["disposition"] = _overall_disposition(row, require_holm=True)
    primary.sort(
        key=lambda row: (
            -_finite_number(
                row["brier_delta"]["mean"], label="primary Brier mean"
            )
            if int(row.get("fleet_dates") or 0) > 0
            else math.inf,
            str(row.get("variant")),
        )
    )

    secondary = [
        dict(row)
        for row in robustness_rows
        if str(row.get("scope") or "") == SECONDARY_SCOPE
        and str(row.get("split") or "") == PRIMARY_SPLIT
    ]
    secondary_by_variant = {
        str(row.get("variant") or ""): row for row in secondary
    }
    if (
        set(secondary_by_variant) != seen_variants
        or len(secondary) != len(secondary_by_variant)
    ):
        raise SourceAblationSynthesisError(
            "daily-summary holdout rows do not map one-to-one to variants"
        )
    for row in secondary:
        _validate_fleet_row(row, scope=SECONDARY_SCOPE, strict_panel=False)
        row["disposition"] = _overall_disposition(row, require_holm=False)
        row["strict_12_market_supported"] = bool(
            int(by_variant[str(row["variant"])].get("fleet_dates") or 0) > 0
        )
    secondary.sort(key=lambda row: str(row.get("variant")))

    holdout_market_rows = [
        dict(row)
        for row in market_rows
        if str(row.get("split") or "") == PRIMARY_SPLIT
    ]
    market_sets: dict[str, set[str]] = {}
    market_keys: set[tuple[str, str]] = set()
    for row in holdout_market_rows:
        variant = str(row.get("variant") or "")
        market_id = str(row.get("market_id") or "")
        if not variant or not market_id:
            raise SourceAblationSynthesisError(
                "holdout market inference contains a blank variant or market"
            )
        if variant not in seen_variants:
            raise SourceAblationSynthesisError(
                f"holdout market inference has an unrequested variant: {variant}"
            )
        key = (variant, market_id)
        if key in market_keys:
            raise SourceAblationSynthesisError(
                f"duplicate holdout market inference: {variant}/{market_id}"
            )
        market_keys.add(key)
        market_sets.setdefault(variant, set()).add(market_id)
        _validate_market_row(row)
    if set(market_sets) != seen_variants:
        raise SourceAblationSynthesisError(
            "holdout market inference does not cover every requested variant"
        )
    corrected_markets = add_market_holm_adjustments(holdout_market_rows)
    for row in corrected_markets:
        row["disposition"] = _market_disposition(row)
    city_actions = [
        row
        for row in corrected_markets
        if row["disposition"] != "no_city_action_after_holm"
    ]
    supported_primary_count = sum(
        int(row.get("fleet_dates") or 0) > 0 for row in primary
    )
    strict_actions = [
        row
        for row in primary
        if row["disposition"]
        in {
            "source_helps_both_scores_after_holm",
            "source_harms_both_scores_after_holm",
        }
    ]
    split_dates_payload = {
        split: {
            "dates": list(values),
            "count": len(values),
            "sha256": hashlib.sha256(
                ("\n".join(values) + "\n").encode("utf-8")
            ).hexdigest(),
        }
        for split, values in split_attestation.items()
    }
    corpus_hash, corpus_as_of, corpus_market_days, corpus_snapshots = next(
        iter(corpus_identities)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "corpus_hash": corpus_hash,
        "corpus_identity": {
            "corpus_hash": corpus_hash,
            "as_of": corpus_as_of,
            "market_day_count": corpus_market_days,
            "snapshot_count": corpus_snapshots,
            "input_verification": "PASS",
        },
        "include_reconstructed": reconstructed_value,
        "split_date_attestation": split_dates_payload,
        "input_artifacts": sorted(inputs, key=lambda row: row["path"]),
        "variant_definitions": [
            {
                "variant": variant,
                "ablated_sources": list(variant_membership[variant]),
                "effect_interpretation": (
                    "single_source_removal"
                    if len(variant_membership[variant]) == 1
                    else "joint_group_removal_not_additive"
                ),
            }
            for variant in sorted(variant_membership)
        ],
        "contract": {
            "primary_split": PRIMARY_SPLIT,
            "primary_scope": PRIMARY_SCOPE,
            "primary_scope_reason": (
                "configured WU daily-summary settlement on exact 12-market "
                "variant-scored fleet dates"
            ),
            "primary_multiplicity": (
                "Holm family-wise correction separately for Brier and log-loss "
                "across every supported strict-panel holdout variant sign test"
            ),
            "per_market_multiplicity": (
                "Holm family-wise correction separately for Brier and log-loss "
                "across every holdout variant-market sign test"
            ),
            "secondary_scope": SECONDARY_SCOPE,
            "secondary_scope_reason": (
                "configured WU daily-summary settlements for the markets where "
                "the source ablation has support; used when a source is "
                "structurally regional"
            ),
            "group_variant_interpretation": (
                "multi-source variants are joint removals; their effects are "
                "not additive source coefficients"
            ),
            "positive_delta_meaning": "removing the source hurt; source helped",
        },
        "summary": {
            "artifact_count": len(inputs),
            "variant_count": len(seen_variants),
            "supported_primary_test_count": supported_primary_count,
            "strict_action_count_after_holm": len(strict_actions),
            "market_test_count": len(corrected_markets),
            "market_count_min": min(len(values) for values in market_sets.values()),
            "market_count_max": max(len(values) for values in market_sets.values()),
            "city_action_count_after_holm": len(city_actions),
        },
        "market_coverage_by_variant": [
            {
                "variant": variant,
                "market_count": len(markets),
                "market_ids": sorted(markets),
            }
            for variant, markets in sorted(market_sets.items())
        ],
        "primary_holdout": primary,
        "daily_summary_holdout": secondary,
        "per_market_holdout_holm": corrected_markets,
        "city_actions_after_holm": city_actions,
    }


def synthesize(
    artifact_paths: Iterable[str | Path],
    *,
    repo_root: str | Path,
    preregistration_path: str | Path,
    support_path: str | Path,
    feasibility_path: str | Path,
    runtime_support_correction_path: str | Path,
) -> dict[str, Any]:
    """Synthesize one complete sealed v0.2 source-ablation generation."""

    from weather.reporting.research.source_ablation_synthesis_hardened import (
        synthesize_hardened,
    )

    return synthesize_hardened(
        tuple(artifact_paths),
        repo_root=repo_root,
        preregistration_path=preregistration_path,
        support_path=support_path,
        feasibility_path=feasibility_path,
        runtime_support_correction_path=runtime_support_correction_path,
        helpers={
            "load_artifact": _load_artifact,
            "primary_scope": PRIMARY_SCOPE,
            "secondary_scope": SECONDARY_SCOPE,
            "validate_fleet": _validate_fleet_row,
            "validate_market": _validate_market_row,
            "add_primary_holm": add_primary_holm_adjustments,
            "add_market_holm": add_market_holm_adjustments,
            "overall_disposition": _overall_disposition,
            "market_disposition": _market_disposition,
            "schema_version": SCHEMA_VERSION,
            "sha256": _sha256,
        },
    )


def _fmt(value: Any, digits: int = 6) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(parsed):
        return "n/a"
    return f"{parsed:+.{digits}f}"


def render_report(payload: Mapping[str, Any]) -> str:
    """Render the compact decision report for a synthesis payload."""

    summary = payload["summary"]
    batch_word = "batch" if summary["artifact_count"] == 1 else "batches"
    lines = [
        "# Workstation Source-Ablation Synthesis",
        "",
        "## Outcome",
        "",
        (
            f"Combined {summary['variant_count']} source removals from "
            f"{summary['artifact_count']} replay {batch_word} on one pinned corpus. "
            "Positive deltas mean the removed source was useful."
        ),
        "",
        (
            f"After Holm correction across {summary['market_test_count']} "
            "holdout variant-market comparisons per score, "
            f"{summary['city_action_count_after_holm']} city-specific removals "
            "or keeps clear both Brier and log-loss criteria."
        ),
        "",
        (
            f"The strict panel separately corrects "
            f"{summary['supported_primary_test_count']} supported variant tests "
            f"per score; {summary['strict_action_count_after_holm']} clear both "
            "score intervals and adjusted sign tests."
        ),
        "",
        "## Ablation Definitions",
        "",
        (
            "Names identify replay variants, not necessarily one source. Group "
            "variants remove every listed source jointly; their effects are not "
            "additive source coefficients."
        ),
        "",
        "| Variant | Exact sources removed | Interpretation |",
        "| :--- | :--- | :--- |",
    ]
    for definition in payload["variant_definitions"]:
        lines.append(
            f"| {definition['variant']} "
            f"| {', '.join(definition['ablated_sources'])} "
            f"| {definition['effect_interpretation']} |"
        )
    lines += [
        "",
        "## Strict Holdout Panel",
        "",
        (
            "Primary scope is configured WU daily-summary settlement on exact "
            "12-market fleet dates. Intervals resample whole fleet dates; a "
            "disposition requires both interval directions and Holm-adjusted "
            "sign-test p-values at 0.05 or below."
        ),
        "",
        "| Source removal | Dates | Brier delta (95% CI; Holm p) | Log-loss delta (95% CI; Holm p) | Disposition |",
        "| :--- | ---: | ---: | ---: | :--- |",
    ]
    for row in payload["primary_holdout"]:
        dates = int(row.get("fleet_dates") or 0)
        if dates:
            brier = row["brier_delta"]
            logloss = row["logloss_delta"]
            b_low, b_high = _ci(brier, market=False)
            l_low, l_high = _ci(logloss, market=False)
            b_text = (
                f"{_fmt(brier['mean'])} [{_fmt(b_low)}, {_fmt(b_high)}]; "
                f"{brier['multiplicity']['adjusted_p']:.6g}"
            )
            l_text = (
                f"{_fmt(logloss['mean'])} [{_fmt(l_low)}, {_fmt(l_high)}]; "
                f"{logloss['multiplicity']['adjusted_p']:.6g}"
            )
        else:
            b_text = "unsupported"
            l_text = "unsupported"
        lines.append(
            f"| {row['variant']} | {dates} | {b_text} | {l_text} "
            f"| {row['disposition']} |"
        )

    lines += [
        "",
        "## Regional-Source Holdout Sensitivity",
        "",
        (
            "This secondary scope retains configured WU daily-summary labels but "
            "allows each source's structurally supported market set. It is the "
            "appropriate coverage sensitivity for regional sources that cannot "
            "form a 12-market panel."
        ),
        "",
        "| Source removal | Markets/dates | Brier delta (95% CI) | Log-loss delta (95% CI) | Strict panel? |",
        "| :--- | ---: | ---: | ---: | :--- |",
    ]
    for row in payload["daily_summary_holdout"]:
        dates = int(row.get("fleet_dates") or 0)
        if dates:
            brier = row["brier_delta"]
            logloss = row["logloss_delta"]
            b_low, b_high = _ci(brier, market=False)
            l_low, l_high = _ci(logloss, market=False)
            b_text = f"{_fmt(brier['mean'])} [{_fmt(b_low)}, {_fmt(b_high)}]"
            l_text = f"{_fmt(logloss['mean'])} [{_fmt(l_low)}, {_fmt(l_high)}]"
        else:
            b_text = "unsupported"
            l_text = "unsupported"
        lines.append(
            f"| {row['variant']} | {row.get('market_days', 0)}/{dates} "
            f"| {b_text} | {l_text} "
            f"| {'yes' if row['strict_12_market_supported'] else 'no'} |"
        )

    lines += [
        "",
        "## City-Level Multiplicity Audit",
        "",
    ]
    if payload["city_actions_after_holm"]:
        lines += [
            "| Source | Market | Brier mean / Holm p | Log-loss mean / Holm p | Disposition |",
            "| :--- | :--- | ---: | ---: | :--- |",
        ]
        for row in payload["city_actions_after_holm"]:
            brier = row["brier_delta"]
            logloss = row["logloss_delta"]
            lines.append(
                f"| {row['variant']} | {row['market_id']} "
                f"| {_fmt(brier['mean'])} / {brier['multiplicity']['adjusted_p']:.6g} "
                f"| {_fmt(logloss['mean'])} / {logloss['multiplicity']['adjusted_p']:.6g} "
                f"| {row['disposition']} |"
            )
    else:
        lines.append(
            "No city-specific source change clears both score directions, "
            "bootstrap intervals, and Holm-adjusted sign tests. Isolated "
            "uncorrected intervals remain exploratory."
        )

    lines += [
        "",
        "## Provenance and Limits",
        "",
        f"Pinned corpus hash: `{payload['corpus_hash']}`.",
        "",
        (
            f"Tune dates: {payload['split_date_attestation']['tune']['count']} "
            f"(SHA-256 `{payload['split_date_attestation']['tune']['sha256']}`); "
            f"holdout dates: "
            f"{payload['split_date_attestation']['holdout']['count']} "
            f"(SHA-256 "
            f"`{payload['split_date_attestation']['holdout']['sha256']}`)."
        ),
        "",
    ]
    for item in payload["input_artifacts"]:
        lines.append(
            f"- `{item['path']}` — SHA-256 `{item['sha256']}`, "
            f"variants: {', '.join(item['variants'])}."
        )
    lines += [
        "",
        (
            "This synthesis does not rerun replay, select variants, change "
            "configuration, or authorize serving/trading changes. The strict "
            "panel can be unsupported when a source is structurally absent "
            "from one market; missing source/market combinations are not tests "
            "and are not silently converted to zero effects. That is a coverage "
            "result, not evidence of no effect."
        ),
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    payload: Mapping[str, Any],
    *,
    output_json: Path,
    output_report: Path,
) -> None:
    del payload, output_json, output_report
    raise SourceAblationSynthesisError(
        "direct synthesis leaf publication is disabled; use one exclusive "
        "--generation-dir with COMPLETE.json commit semantics"
    )


def main(argv: Sequence[str] | None = None) -> int:
    from weather.reporting.research.source_ablation_synthesis_hardened import (
        build_parser,
        run_hardened_synthesis,
    )

    args = build_parser().parse_args(argv)
    payload, commit = run_hardened_synthesis(args)
    print(
        f"Source-ablation synthesis: {payload['summary']['variant_count']} variants; "
        f"{payload['summary']['city_action_count_after_holm']} Holm-cleared city actions; "
        f"generation {args.generation_dir}; "
        f"execution {commit['execution_identity']['start_digest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
