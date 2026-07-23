"""Fleet-date inference for the workstation morning forecast frontier.

This research-only aggregator consumes one canonical forecast-tracker JSON per
configured market.  It keeps the chronological tune/holdout boundary explicit,
normalizes point errors to Celsius, and averages markets within a fleet date
before bootstrap or sign-test inference.  It never mutates the source reports
or the supplied read-only data root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

from weather.io import write_json_atomic, write_text_atomic
from weather.market.market_registry import all_specs
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("workstation_morning_frontier")
DEFAULT_BOOTSTRAP_REPLICATES = 20_000
DEFAULT_BOOTSTRAP_SEED = 20_260_722
DEFAULT_CUTOFFS = (7, 9, 11, 13)
CITY_SELECTION_CUTOFF = 9
CALIBRATION_MARGIN = 0.15
EPSILON = 1e-12
METRICS = (
    "outcome_minus_model_reach",
    "outcome_minus_market_reach",
    "model_minus_market_brier",
    "model_minus_market_logloss",
    "model_minus_market_point_abs_error_c",
)
SCORE_METRICS = (
    "model_minus_market_brier",
    "model_minus_market_logloss",
)


class MorningFrontierError(ValueError):
    """Raised when the research input or isolation contract is not satisfied."""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_paths(
    *,
    read_only_data_root: str | Path,
    input_dir: str | Path,
    source_files: Iterable[str | Path],
    output_json: str | Path,
    output_report: str | Path,
) -> dict[str, Path]:
    """Resolve every path and reject output aliases below the mirror."""

    data_root = Path(read_only_data_root).resolve(strict=True)
    source_root = Path(input_dir).resolve(strict=True)
    if not data_root.is_dir():
        raise MorningFrontierError(f"read-only data root is not a directory: {data_root}")
    if not source_root.is_dir():
        raise MorningFrontierError(f"input directory is not a directory: {source_root}")
    sources = tuple(Path(path).resolve(strict=True) for path in source_files)
    if not sources:
        raise MorningFrontierError("at least one explicit source report is required")
    if any(not path.is_file() for path in sources):
        raise MorningFrontierError("every explicit source report must be a file")

    outputs = {
        "output_json": Path(output_json).resolve(strict=False),
        "output_report": Path(output_report).resolve(strict=False),
    }
    outputs_alias = outputs["output_json"] == outputs["output_report"]
    if not outputs_alias and all(path.exists() for path in outputs.values()):
        outputs_alias = outputs["output_json"].samefile(outputs["output_report"])
    if outputs_alias:
        raise MorningFrontierError("JSON and Markdown outputs must be distinct")
    for label, path in outputs.items():
        if _is_relative_to(path, data_root):
            raise MorningFrontierError(
                f"{label} must be outside the read-only data root: {path}"
            )
        if path.exists() and not path.is_file():
            raise MorningFrontierError(f"{label} is not a file path: {path}")
        for source in sources:
            if path == source or (path.exists() and path.samefile(source)):
                raise MorningFrontierError(
                    f"{label} must not overwrite a source report: {source}"
                )
    return {"data_root": data_root, "input_dir": source_root, **outputs}


def _finite_float(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MorningFrontierError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise MorningFrontierError(f"{field} is not finite: {value!r}")
    return number


def _probability(value: Any, *, field: str) -> float:
    number = _finite_float(value, field=field)
    if not 0.0 <= number <= 1.0:
        raise MorningFrontierError(f"{field} is outside [0, 1]: {number}")
    return number


def _logloss(probability: float, outcome: float) -> float:
    probability = min(1.0 - EPSILON, max(EPSILON, probability))
    return -(
        outcome * math.log(probability)
        + (1.0 - outcome) * math.log(1.0 - probability)
    )


def _two_sided_sign_p(values: Iterable[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in values if abs(float(value)) > 1e-15]
    positives = sum(value > 0.0 for value in nonzero)
    negatives = len(nonzero) - positives
    n = len(nonzero)
    if not n:
        return {
            "n_nonzero": 0,
            "positive": 0,
            "negative": 0,
            "p_value": 1.0,
        }
    smaller = min(positives, negatives)
    tail = sum(math.comb(n, index) for index in range(smaller + 1)) / (2**n)
    return {
        "n_nonzero": n,
        "positive": positives,
        "negative": negatives,
        "p_value": min(1.0, 2.0 * tail),
    }


def _holm_adjust(tests: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return Holm-adjusted copies of tests carrying a numeric ``raw_p``."""

    copied = [dict(row) for row in tests]
    ordered = sorted(
        enumerate(copied),
        key=lambda item: (
            _probability(item[1]["raw_p"], field="raw_p"),
            str(item[1].get("market") or ""),
            str(item[1].get("cutoff") or ""),
            str(item[1].get("metric") or ""),
        ),
    )
    running = 0.0
    family_size = len(ordered)
    adjusted: dict[int, float] = {}
    for rank, (original_index, row) in enumerate(ordered):
        candidate = min(
            1.0,
            (family_size - rank) * _probability(row["raw_p"], field="raw_p"),
        )
        running = max(running, candidate)
        adjusted[original_index] = running
    for index, row in enumerate(copied):
        row["holm_adjusted_p"] = adjusted[index]
    return copied


def _classify_reach_gap(gap: float | None) -> str:
    if gap is None:
        return "INSUFFICIENT DATA"
    if gap > CALIBRATION_MARGIN:
        return "SKEPTICISM IS COSTING"
    if gap < -CALIBRATION_MARGIN:
        return "SKEPTICISM IS JUSTIFIED"
    return "MODEL CALIBRATED"


def _bootstrap_ci(
    daily_rows: Sequence[Mapping[str, float]],
    metric: str,
    *,
    replicates: int,
    seed: int,
) -> list[float] | None:
    values = [float(row[metric]) for row in daily_rows]
    if not values:
        return None
    if replicates <= 0:
        raise MorningFrontierError("bootstrap replicates must be positive")
    rng = random.Random(int(seed))
    n = len(values)
    draws = sorted(
        mean(values[rng.randrange(n)] for _ in range(n))
        for _ in range(int(replicates))
    )
    return [
        draws[int(0.025 * (replicates - 1))],
        draws[int(0.975 * (replicates - 1))],
    ]


def summarize_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    """Average markets within dates, then infer over equal-weight fleet dates."""

    if not rows:
        return {"status": "BLOCK_NO_ROWS", "n_observations": 0, "n_fleet_dates": 0}
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)

    daily_rows: list[dict[str, Any]] = []
    for target_date, members in sorted(by_date.items()):
        daily_rows.append(
            {
                "date": target_date,
                "n_markets": len(members),
                **{
                    metric: mean(float(row[metric]) for row in members)
                    for metric in METRICS
                },
            }
        )

    summary: dict[str, Any] = {
        "status": "PRESENT",
        "n_observations": len(rows),
        "n_markets": len({str(row["market"]) for row in rows}),
        "n_fleet_dates": len(daily_rows),
        "date_range": [daily_rows[0]["date"], daily_rows[-1]["date"]],
        "mean_markets_per_date": mean(row["n_markets"] for row in daily_rows),
        "settlement_sources": dict(
            sorted(Counter(str(row["settlement_source"]) for row in rows).items())
        ),
        "equal_fleet_date": {},
        "daily_rows": daily_rows,
    }
    for index, metric in enumerate(METRICS):
        values = [float(row[metric]) for row in daily_rows]
        summary["equal_fleet_date"][metric] = {
            "mean": mean(values),
            "bootstrap_ci_95": _bootstrap_ci(
                daily_rows,
                metric,
                replicates=replicates,
                seed=int(seed) + index,
            ),
            "sign_test": _two_sided_sign_p(values),
        }

    by_market: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_market[str(row["market"])].append(row)
    summary["by_market"] = {
        market: {
            "n": len(members),
            "n_dates": len({str(row["date"]) for row in members}),
            **{
                metric: mean(float(row[metric]) for row in members)
                for metric in METRICS
            },
        }
        for market, members in sorted(by_market.items())
    }
    return summary


def _partition(
    rows: Sequence[Mapping[str, Any]],
    *,
    start: date | None,
    end: date | None,
) -> list[Mapping[str, Any]]:
    selected = []
    for row in rows:
        target_date = date.fromisoformat(str(row["date"]))
        if start is not None and target_date < start:
            continue
        if end is not None and target_date > end:
            continue
        selected.append(row)
    return selected


def _complete_panel_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_markets: Iterable[str],
) -> list[Mapping[str, Any]]:
    """Keep only fleet dates with exactly the configured market panel."""

    expected = {str(market) for market in expected_markets}
    by_date: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[str(row["date"])].append(row)
    selected: list[Mapping[str, Any]] = []
    for members in by_date.values():
        observed = {str(row["market"]) for row in members}
        if observed == expected and len(members) == len(expected):
            selected.extend(members)
    return selected


def _single_market_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    summary = summarize_rows(rows, replicates=replicates, seed=seed)
    summary.pop("by_market", None)
    return summary


def _group_holdout_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_markets: Sequence[str],
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    summary = summarize_rows(rows, replicates=replicates, seed=seed)
    daily_summary_rows = [
        row for row in rows if str(row["settlement_source"]) == "daily_summary"
    ]
    summary["sensitivities"] = {
        "complete_selected_market_panel": summarize_rows(
            _complete_panel_rows(rows, expected_markets=expected_markets),
            replicates=replicates,
            seed=seed + 10_000,
        ),
        "daily_summary_only": summarize_rows(
            daily_summary_rows,
            replicates=replicates,
            seed=seed + 20_000,
        ),
        "daily_summary_complete_selected_market_panel": summarize_rows(
            _complete_panel_rows(
                daily_summary_rows,
                expected_markets=expected_markets,
            ),
            replicates=replicates,
            seed=seed + 30_000,
        ),
    }
    return summary


def _build_city_analysis(
    rows: Sequence[Mapping[str, Any]],
    *,
    market_units: Mapping[str, str],
    reported_full_corpus_verdicts: Mapping[str, Mapping[str, Any]],
    tune_end: date,
    holdout_start: date,
    bootstrap_replicates: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    """Build a retrospective but date-split-respecting 09:00 city audit."""

    by_market: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_market[str(row["market"])].append(row)

    cities: list[dict[str, Any]] = []
    selected_markets: list[str] = []
    nonselected_markets: list[str] = []
    for market_index, market in enumerate(sorted(market_units)):
        market_rows = by_market.get(market, [])
        tune_rows = _partition(market_rows, start=None, end=tune_end)
        holdout_rows = _partition(market_rows, start=holdout_start, end=None)
        tune_summary = _single_market_summary(
            tune_rows,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed + 400_000 + market_index * 100,
        )
        holdout_summary = _single_market_summary(
            holdout_rows,
            replicates=bootstrap_replicates,
            seed=bootstrap_seed + 500_000 + market_index * 100,
        )
        tune_gap = None
        if tune_summary.get("status") == "PRESENT":
            tune_gap = float(
                tune_summary["equal_fleet_date"]["outcome_minus_model_reach"]["mean"]
            )
        classification = _classify_reach_gap(tune_gap)
        selected = classification == "SKEPTICISM IS COSTING"
        (selected_markets if selected else nonselected_markets).append(market)
        reported_verdict = dict(reported_full_corpus_verdicts.get(market) or {})
        cities.append(
            {
                "market": market,
                "unit": str(market_units[market]),
                "tune_classification": classification,
                "selected_by_tune_rule": selected,
                "tune": tune_summary,
                "holdout": holdout_summary,
                "reported_full_corpus_verdict_unused": reported_verdict,
                "reported_verdict_conflicts_with_tune_classification": (
                    bool(reported_verdict.get("headline"))
                    and str(reported_verdict["headline"]) != classification
                ),
            }
        )

    raw_tests: list[dict[str, Any]] = []
    for city in cities:
        holdout_summary = city["holdout"]
        for metric in SCORE_METRICS:
            if holdout_summary.get("status") != "PRESENT":
                metric_summary = None
                raw_p = 1.0
            else:
                metric_summary = holdout_summary["equal_fleet_date"][metric]
                raw_p = float(metric_summary["sign_test"]["p_value"])
            raw_tests.append(
                {
                    "market": city["market"],
                    "metric": metric,
                    "mean": (
                        None if metric_summary is None else float(metric_summary["mean"])
                    ),
                    "bootstrap_ci_95": (
                        None
                        if metric_summary is None
                        else list(metric_summary["bootstrap_ci_95"])
                    ),
                    "raw_p": raw_p,
                }
            )
    adjusted_tests = _holm_adjust(raw_tests)
    test_lookup = {
        (str(row["market"]), str(row["metric"])): row for row in adjusted_tests
    }
    for city in cities:
        city["holdout_multiplicity"] = {
            metric: test_lookup[(str(city["market"]), metric)]
            for metric in SCORE_METRICS
        }
        for metric in SCORE_METRICS:
            test = city["holdout_multiplicity"][metric]
            ci = test["bootstrap_ci_95"]
            test["holm_supported_adverse"] = bool(
                test["mean"] is not None
                and float(test["mean"]) > 0.0
                and ci is not None
                and float(ci[0]) > 0.0
                and float(test["holm_adjusted_p"]) <= 0.05
            )

    selected_set = set(selected_markets)
    selected_holdout_rows = [
        row
        for row in rows
        if str(row["market"]) in selected_set
        and date.fromisoformat(str(row["date"])) >= holdout_start
    ]
    nonselected_holdout_rows = [
        row
        for row in rows
        if str(row["market"]) not in selected_set
        and date.fromisoformat(str(row["date"])) >= holdout_start
    ]
    supported_both = [
        str(city["market"])
        for city in cities
        if all(
            city["holdout_multiplicity"][metric]["holm_supported_adverse"]
            for metric in SCORE_METRICS
        )
    ]
    return {
        "status": "RETROSPECTIVE_SPLIT_RESPECTING_NOT_CONFIRMATORY",
        "selection_cutoff_local_hour": CITY_SELECTION_CUTOFF,
        "calibration_margin": CALIBRATION_MARGIN,
        "selection_rule": (
            "select a market only when its tune-only mean "
            "outcome_minus_model_reach is strictly greater than 0.15"
        ),
        "selection_timing": (
            "retrospective after the holdout dates had already been opened; "
            "the split prevents direct label leakage but is not untouched confirmation"
        ),
        "reported_full_corpus_verdict_role": (
            "audit provenance only; never used for selection or inference"
        ),
        "selected_markets": selected_markets,
        "nonselected_markets": nonselected_markets,
        "cities": cities,
        "holdout_groups": {
            "tune_selected": _group_holdout_summary(
                selected_holdout_rows,
                expected_markets=selected_markets,
                replicates=bootstrap_replicates,
                seed=bootstrap_seed + 600_000,
            ),
            "not_tune_selected": _group_holdout_summary(
                nonselected_holdout_rows,
                expected_markets=nonselected_markets,
                replicates=bootstrap_replicates,
                seed=bootstrap_seed + 700_000,
            ),
        },
        "city_multiplicity": {
            "method": "Holm family-wise adjustment",
            "alpha": 0.05,
            "family_definition": (
                "all configured markets crossed with holdout Brier and log-loss deltas"
            ),
            "n_tests": len(adjusted_tests),
            "tests": adjusted_tests,
            "markets_supported_adverse_on_both_scores": supported_both,
        },
    }


def _build_fleet_holdout_multiplicity(
    analyses: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, Any]:
    raw_tests: list[dict[str, Any]] = []
    for cutoff in sorted(analyses, key=int):
        holdout = analyses[cutoff]["holdout"]
        for metric in SCORE_METRICS:
            if holdout.get("status") != "PRESENT":
                metric_summary = None
                raw_p = 1.0
            else:
                metric_summary = holdout["equal_fleet_date"][metric]
                raw_p = float(metric_summary["sign_test"]["p_value"])
            raw_tests.append(
                {
                    "cutoff": int(cutoff),
                    "metric": metric,
                    "mean": (
                        None if metric_summary is None else float(metric_summary["mean"])
                    ),
                    "bootstrap_ci_95": (
                        None
                        if metric_summary is None
                        else list(metric_summary["bootstrap_ci_95"])
                    ),
                    "raw_p": raw_p,
                }
            )
    adjusted_tests = _holm_adjust(raw_tests)
    for test in adjusted_tests:
        ci = test["bootstrap_ci_95"]
        test["holm_supported_adverse"] = bool(
            test["mean"] is not None
            and float(test["mean"]) > 0.0
            and ci is not None
            and float(ci[0]) > 0.0
            and float(test["holm_adjusted_p"]) <= 0.05
        )
    supported_both = [
        cutoff
        for cutoff in sorted({int(row["cutoff"]) for row in adjusted_tests})
        if all(
            row["holm_supported_adverse"]
            for row in adjusted_tests
            if int(row["cutoff"]) == cutoff
        )
    ]
    return {
        "method": "Holm family-wise adjustment",
        "alpha": 0.05,
        "family_definition": (
            "all requested holdout cutoffs crossed with Brier and log-loss deltas"
        ),
        "n_tests": len(adjusted_tests),
        "tests": adjusted_tests,
        "cutoffs_supported_adverse_on_both_scores": supported_both,
    }


def _load_market_payloads(
    input_dir: Path,
    market_units: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inputs: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for market, unit in sorted(market_units.items()):
        if unit not in {"C", "F"}:
            raise MorningFrontierError(f"unsupported native unit for {market}: {unit}")
        path = input_dir / f"{market}.json"
        if not path.is_file():
            raise MorningFrontierError(f"missing forecast-tracker input for {market}: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MorningFrontierError(f"invalid forecast-tracker JSON: {path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("per_cutoff"), dict):
            raise MorningFrontierError(f"forecast-tracker payload is malformed: {path}")
        inputs.append(
            {
                "market": market,
                "unit": unit,
                "path": str(path.resolve()),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
        payloads.append({"market": market, "unit": unit, "payload": payload})
    return inputs, payloads


def build_payload(
    input_dir: str | Path,
    *,
    market_units: Mapping[str, str],
    tune_end: date,
    holdout_start: date,
    cutoffs: Sequence[int] = DEFAULT_CUTOFFS,
    bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    read_only_data_root: str | Path | None = None,
) -> dict[str, Any]:
    if not market_units:
        raise MorningFrontierError("at least one configured market is required")
    if tune_end >= holdout_start:
        raise MorningFrontierError("tune_end must precede holdout_start")
    cutoffs = tuple(sorted({int(value) for value in cutoffs}))
    if not cutoffs or any(value < 0 or value > 23 for value in cutoffs):
        raise MorningFrontierError("cutoffs must be unique local hours from 0 through 23")
    if CITY_SELECTION_CUTOFF not in cutoffs:
        raise MorningFrontierError(
            f"cutoffs must include the fixed city-selection hour {CITY_SELECTION_CUTOFF}"
        )
    source_root = Path(input_dir).resolve(strict=True)
    inputs, market_payloads = _load_market_payloads(source_root, market_units)

    rows_by_cutoff: dict[int, list[dict[str, Any]]] = defaultdict(list)
    exclusions: Counter[str] = Counter()
    reported_full_corpus_verdicts: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, int, str]] = set()
    for item in market_payloads:
        market = str(item["market"])
        unit = str(item["unit"])
        payload = item["payload"]
        reported_full_corpus_verdicts[market] = dict(payload.get("verdict") or {})
        available = {int(value) for value in payload["per_cutoff"]}
        missing_cutoffs = sorted(set(cutoffs) - available)
        if missing_cutoffs:
            raise MorningFrontierError(
                f"{market} is missing required cutoffs: {missing_cutoffs}"
            )
        for cutoff in cutoffs:
            cutoff_payload = payload["per_cutoff"].get(str(cutoff))
            if cutoff_payload is None:
                cutoff_payload = payload["per_cutoff"].get(cutoff)
            if not isinstance(cutoff_payload, dict):
                raise MorningFrontierError(f"{market} cutoff {cutoff} is malformed")
            for position, record in enumerate(cutoff_payload.get("records") or []):
                if not isinstance(record, dict):
                    raise MorningFrontierError(
                        f"{market} cutoff {cutoff} record {position} is malformed"
                    )
                required = (
                    "model_reach",
                    "market_reach",
                    "settlement",
                    "model_median",
                    "market_median",
                )
                missing = [field for field in required if record.get(field) is None]
                if missing:
                    exclusions[
                        f"cutoff_{cutoff}:missing_{'+'.join(missing)}"
                    ] += 1
                    continue
                target_date = str(record.get("date") or "")
                try:
                    date.fromisoformat(target_date)
                except ValueError as exc:
                    raise MorningFrontierError(
                        f"{market} cutoff {cutoff} has invalid date: {target_date!r}"
                    ) from exc
                key = (market, cutoff, target_date)
                if key in seen:
                    raise MorningFrontierError(f"duplicate market/cutoff/date record: {key}")
                seen.add(key)
                if not isinstance(record.get("reached"), bool):
                    raise MorningFrontierError(f"{key} reached must be boolean")
                outcome = 1.0 if record["reached"] else 0.0
                model_probability = _probability(
                    record["model_reach"], field=f"{key}.model_reach"
                )
                market_probability = _probability(
                    record["market_reach"], field=f"{key}.market_reach"
                )
                settlement = _finite_float(record["settlement"], field=f"{key}.settlement")
                model_median = _finite_float(
                    record["model_median"], field=f"{key}.model_median"
                )
                market_median = _finite_float(
                    record["market_median"], field=f"{key}.market_median"
                )
                native_delta_to_c = 1.0 if unit == "C" else 5.0 / 9.0
                rows_by_cutoff[cutoff].append(
                    {
                        "market": market,
                        "unit": unit,
                        "date": target_date,
                        "settlement_source": str(
                            record.get("settlement_source") or "unknown"
                        ),
                        "outcome_minus_model_reach": outcome - model_probability,
                        "outcome_minus_market_reach": outcome - market_probability,
                        "model_minus_market_brier":
                            (model_probability - outcome) ** 2
                            - (market_probability - outcome) ** 2,
                        "model_minus_market_logloss":
                            _logloss(model_probability, outcome)
                            - _logloss(market_probability, outcome),
                        "model_minus_market_point_abs_error_c": native_delta_to_c
                        * (
                            abs(model_median - settlement)
                            - abs(market_median - settlement)
                        ),
                    }
                )

    splits = {
        "tune": (None, tune_end),
        "holdout": (holdout_start, None),
        "all": (None, None),
    }
    analyses: dict[str, Any] = {}
    for cutoff in cutoffs:
        rows = rows_by_cutoff.get(cutoff, [])
        split_payload: dict[str, Any] = {}
        for split_index, (name, (start, end)) in enumerate(splits.items()):
            selected = _partition(rows, start=start, end=end)
            daily_summary_only = [
                row
                for row in selected
                if str(row["settlement_source"]) == "daily_summary"
            ]
            primary = summarize_rows(
                selected,
                replicates=bootstrap_replicates,
                seed=bootstrap_seed + cutoff * 100 + split_index * 10,
            )
            primary["sensitivities"] = {
                "daily_summary_only": summarize_rows(
                    daily_summary_only,
                    replicates=bootstrap_replicates,
                    seed=bootstrap_seed + 100_000 + cutoff * 100 + split_index * 10,
                ),
                "complete_market_panel": summarize_rows(
                    _complete_panel_rows(
                        selected,
                        expected_markets=market_units,
                    ),
                    replicates=bootstrap_replicates,
                    seed=bootstrap_seed + 200_000 + cutoff * 100 + split_index * 10,
                ),
                "daily_summary_complete_market_panel": summarize_rows(
                    _complete_panel_rows(
                        daily_summary_only,
                        expected_markets=market_units,
                    ),
                    replicates=bootstrap_replicates,
                    seed=bootstrap_seed + 300_000 + cutoff * 100 + split_index * 10,
                ),
            }
            split_payload[name] = primary
        analyses[str(cutoff)] = split_payload

    city_analysis = _build_city_analysis(
        rows_by_cutoff[CITY_SELECTION_CUTOFF],
        market_units=market_units,
        reported_full_corpus_verdicts=reported_full_corpus_verdicts,
        tune_end=tune_end,
        holdout_start=holdout_start,
        bootstrap_replicates=bootstrap_replicates,
        bootstrap_seed=bootstrap_seed,
    )
    fleet_holdout_multiplicity = _build_fleet_holdout_multiplicity(analyses)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PRESENT" if inputs else "BLOCK_NO_INPUTS",
        "design": {
            "unit": "fleet date; markets averaged within date before inference",
            "bootstrap_replicates": int(bootstrap_replicates),
            "bootstrap_seed": int(bootstrap_seed),
            "tune_end": tune_end.isoformat(),
            "holdout_start": holdout_start.isoformat(),
            "selection_uses_holdout": False,
            "analysis_timing": (
                "retrospective after the holdout dates had already been opened; "
                "split-respecting diagnostic, not untouched confirmation"
            ),
            "metric_sign": "positive model-minus-market losses mean model is worse",
            "reach_gap_sign": "positive outcome-minus-probability means under-confidence",
            "point_error_unit": "Celsius; Fahrenheit native deltas multiplied by 5/9",
            "sensitivities": {
                "daily_summary_only": "exclude snapshot-high settlement fallback rows",
                "complete_market_panel": "retain only dates with all configured markets",
                "daily_summary_complete_market_panel": (
                    "require both configured-market completeness and daily-summary settlement"
                ),
            },
        },
        "provenance": {
            "read_only_data_root": (
                str(Path(read_only_data_root).resolve())
                if read_only_data_root is not None
                else None
            ),
            "input_dir": str(source_root),
        },
        "input_integrity": {
            "status": "PASS",
            "expected_markets": sorted(market_units),
            "market_count": len(inputs),
            "required_cutoffs": list(cutoffs),
            "duplicate_records": 0,
        },
        "inputs": inputs,
        "excluded_records": dict(sorted(exclusions.items())),
        "by_cutoff": analyses,
        "fleet_holdout_multiplicity": fleet_holdout_multiplicity,
        "city_analysis": city_analysis,
    }


def _fmt(value: Any, digits: int = 4) -> str:
    return "n/a" if value is None else f"{float(value):+.{digits}f}"


def render_report(payload: Mapping[str, Any]) -> str:
    design = payload.get("design") or {}
    lines = [
        "# Morning forecast frontier aggregate",
        "",
        f"Status: **{payload.get('status')}**",
        "",
        "This is a retrospective, split-respecting diagnostic. The evaluation dates had already been opened before the city rule was formalized, so none of the holdout language below means untouched confirmation.",
        "",
        "Inference is paired by fleet date: markets are averaged within a date, then whole dates are bootstrapped.",
        "Positive reach gaps mean the forecast-defined warm event occurred more often than the model or market probability implied.",
        "Positive loss deltas mean the model was worse than the market. Point-error deltas are normalized to Celsius.",
        "",
        f"Tune ends `{design.get('tune_end')}`; the separately reported evaluation split starts `{design.get('holdout_start')}`.",
        "",
        "| Cutoff | Split | Obs | Fleet dates | Outcome-model p | 95% CI | Model-market Brier | 95% CI | Model-market logloss | 95% CI | Point MAE delta C |",
        "| ---: | --- | ---: | ---: | ---: | --- | ---: | --- | ---: | --- | ---: |",
    ]
    for cutoff, cutoff_payload in (payload.get("by_cutoff") or {}).items():
        for split in ("tune", "holdout", "all"):
            row = cutoff_payload[split]
            if row.get("status") != "PRESENT":
                lines.append(
                    f"| {cutoff} | {split} | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
                )
                continue
            metrics = row["equal_fleet_date"]
            gap = metrics["outcome_minus_model_reach"]
            brier = metrics["model_minus_market_brier"]
            logloss = metrics["model_minus_market_logloss"]
            point = metrics["model_minus_market_point_abs_error_c"]
            lines.append(
                f"| {cutoff} | {split} | {row['n_observations']} | {row['n_fleet_dates']} | "
                f"{_fmt(gap['mean'])} | [{_fmt(gap['bootstrap_ci_95'][0])}, {_fmt(gap['bootstrap_ci_95'][1])}] | "
                f"{_fmt(brier['mean'])} | [{_fmt(brier['bootstrap_ci_95'][0])}, {_fmt(brier['bootstrap_ci_95'][1])}] | "
                f"{_fmt(logloss['mean'])} | [{_fmt(logloss['bootstrap_ci_95'][0])}, {_fmt(logloss['bootstrap_ci_95'][1])}] | "
                f"{_fmt(point['mean'])} |"
            )
    fleet_multiplicity = payload.get("fleet_holdout_multiplicity") or {}
    lines += [
        "",
        "## Fleet holdout score multiplicity",
        "",
        "The natural family contains every requested cutoff crossed with Brier and log-loss. Holm support requires a positive loss delta, a bootstrap interval above zero, and adjusted `p <= 0.05`.",
        "",
        "| Cutoff | Score | Mean delta | Raw sign p | Holm p | Holm-supported adverse |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in fleet_multiplicity.get("tests") or []:
        lines.append(
            f"| {int(row['cutoff']):02d}:00 | {str(row['metric']).removeprefix('model_minus_market_')} | "
            f"{_fmt(row.get('mean'))} | {float(row['raw_p']):.6f} | "
            f"{float(row['holm_adjusted_p']):.6f} | "
            f"{'yes' if row.get('holm_supported_adverse') else 'no'} |"
        )
    city_analysis = payload.get("city_analysis") or {}
    selected = list(city_analysis.get("selected_markets") or [])
    lines += [
        "",
        "## Retrospective tune-only 09:00 city selection",
        "",
        f"The fixed tune-only rule (`outcome_minus_model_reach > {float(city_analysis.get('calibration_margin', CALIBRATION_MARGIN)):.2f}`) selects: **{', '.join(selected) if selected else 'none'}**.",
        "This rule was written after the evaluation dates had been inspected. It respects the date split and does not read holdout outcomes for selection, but it is not a preregistered or untouched confirmation.",
        "The full-corpus verdict embedded in each source report is retained only as provenance and is never used here.",
        "",
        "### Separate holdout group evaluation",
        "",
        "| Group | Obs | Fleet dates | Outcome-model reach | 95% CI | Brier delta | 95% CI | Log-loss delta | 95% CI |",
        "| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | --- |",
    ]
    for label, key in (
        ("Tune-selected", "tune_selected"),
        ("Not tune-selected", "not_tune_selected"),
    ):
        row = (city_analysis.get("holdout_groups") or {}).get(key) or {}
        if row.get("status") != "PRESENT":
            lines.append(f"| {label} | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        metrics = row["equal_fleet_date"]
        reach = metrics["outcome_minus_model_reach"]
        brier = metrics["model_minus_market_brier"]
        logloss = metrics["model_minus_market_logloss"]
        lines.append(
            f"| {label} | {row['n_observations']} | {row['n_fleet_dates']} | "
            f"{_fmt(reach['mean'])} | [{_fmt(reach['bootstrap_ci_95'][0])}, {_fmt(reach['bootstrap_ci_95'][1])}] | "
            f"{_fmt(brier['mean'])} | [{_fmt(brier['bootstrap_ci_95'][0])}, {_fmt(brier['bootstrap_ci_95'][1])}] | "
            f"{_fmt(logloss['mean'])} | [{_fmt(logloss['bootstrap_ci_95'][0])}, {_fmt(logloss['bootstrap_ci_95'][1])}] |"
        )
    lines += [
        "",
        "### Exploratory city-level holdout tests",
        "",
        "All configured cities crossed with Brier and log-loss form one Holm family. A city is called supported only when both score deltas are adverse with positive intervals and adjusted `p <= 0.05`.",
        "",
        "| Market | Tune class | Tune reach gap | Holdout reach gap | Holdout Brier | Holm p | Holdout log-loss | Holm p | Both scores supported |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for city in city_analysis.get("cities") or []:
        tune = city.get("tune") or {}
        holdout = city.get("holdout") or {}
        tune_gap = (
            ((tune.get("equal_fleet_date") or {}).get("outcome_minus_model_reach") or {}).get("mean")
        )
        holdout_gap = (
            ((holdout.get("equal_fleet_date") or {}).get("outcome_minus_model_reach") or {}).get("mean")
        )
        tests = city.get("holdout_multiplicity") or {}
        brier = tests.get("model_minus_market_brier") or {}
        logloss = tests.get("model_minus_market_logloss") or {}
        supported = bool(
            brier.get("holm_supported_adverse")
            and logloss.get("holm_supported_adverse")
        )
        lines.append(
            f"| {city['market']} | {city['tune_classification']} | {_fmt(tune_gap)} | "
            f"{_fmt(holdout_gap)} | {_fmt(brier.get('mean'))} | "
            f"{float(brier.get('holm_adjusted_p', 1.0)):.6f} | "
            f"{_fmt(logloss.get('mean'))} | "
            f"{float(logloss.get('holm_adjusted_p', 1.0)):.6f} | "
            f"{'yes' if supported else 'no'} |"
        )
    lines += [
        "",
        "San Francisco reverses reach direction between tune and holdout. That instability is a direct warning against interpreting the selected group as a stable city policy.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(payload: Mapping[str, Any], json_path: Path, report_path: Path) -> None:
    write_json_atomic(json_path, payload)
    write_text_atomic(report_path, render_report(payload))


def _parse_cutoffs(value: str) -> tuple[int, ...]:
    try:
        values = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cutoffs must be comma-separated hours") from exc
    if not values or len(values) != len(set(values)) or any(item < 0 or item > 23 for item in values):
        raise argparse.ArgumentTypeError("cutoffs must be unique hours from 0 through 23")
    return tuple(sorted(values))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-data-root", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-report", required=True)
    parser.add_argument("--tune-end", type=date.fromisoformat, required=True)
    parser.add_argument("--holdout-start", type=date.fromisoformat, required=True)
    parser.add_argument("--cutoffs", type=_parse_cutoffs, default=DEFAULT_CUTOFFS)
    parser.add_argument(
        "--bootstrap-replicates", type=int, default=DEFAULT_BOOTSTRAP_REPLICATES
    )
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    args = parser.parse_args(argv)

    market_units = {spec.id: spec.display_unit for spec in all_specs()}
    paths = validate_paths(
        read_only_data_root=args.read_only_data_root,
        input_dir=args.input_dir,
        source_files=[
            Path(args.input_dir) / f"{market_id}.json"
            for market_id in market_units
        ],
        output_json=args.output_json,
        output_report=args.output_report,
    )
    payload = build_payload(
        paths["input_dir"],
        market_units=market_units,
        tune_end=args.tune_end,
        holdout_start=args.holdout_start,
        cutoffs=args.cutoffs,
        bootstrap_replicates=args.bootstrap_replicates,
        bootstrap_seed=args.bootstrap_seed,
        read_only_data_root=paths["data_root"],
    )
    write_outputs(payload, paths["output_json"], paths["output_report"])
    print(
        json.dumps(
            {
                "status": payload["status"],
                "market_count": payload["input_integrity"]["market_count"],
                "output_json": str(paths["output_json"]),
                "output_report": str(paths["output_report"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
