"""Markdown rendering for the workstation current-replay time frontier."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from weather.reporting.research.current_replay_time_frontier import (
    EVENING_HOURS,
    MAX_ALIGNMENT_KEYS,
    PREDAWN_HOURS,
    UNITS,
)


def _fmt(value: Any, digits: int = 5) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _labeled_extremes(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    if not rows:
        return []
    if len(rows) == 1:
        return [("only", rows[0])]
    if len(rows) < 4:
        return [("best", rows[0]), ("worst", rows[-1])]
    return [("best", row) for row in rows[:2]] + [
        ("worst", row) for row in rows[-2:]
    ]


def _summary_index(
    summaries: Sequence[Mapping[str, Any]], *, split: str
) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (str(row["unit"]), str(row["scope"])): row
        for row in summaries
        if row["split"] == split and row["market_id"] == "__fleet__"
    }


def _append_primary_score_tables(
    lines: list[str],
    primary: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    lines.extend(
        [
            "| Unit | Slice | Dates | Weight | Disposition | Current Brier | Selected Brier | Market Brier | Δ selected-current (95% CI) | Brier signs F/U/T | Current/selected/market winner P |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for scope in ("all_hours", "predawn_03_05", "evening_15_23"):
            row = primary.get((unit, scope))
            if not row:
                continue
            metrics = row["metrics"]
            comparison = row["selected_vs_current"]["brier"]
            ci = comparison["paired_fleet_date_bootstrap_95ci"]
            sign = comparison["paired_fleet_date_sign_test"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        unit,
                        scope,
                        str(row["fleet_dates"]),
                        _fmt(row["selected_weight"], 2),
                        str(row["selected_effect_disposition"]),
                        _fmt(metrics["current"]["brier"]),
                        _fmt(metrics["selected"]["brier"]),
                        _fmt(metrics["market"]["brier"]),
                        f"{_fmt(comparison['mean_delta'])} [{_fmt(ci['low'])}, {_fmt(ci['high'])}]",
                        f"{sign['favorable']}/{sign['unfavorable']}/{sign['ties']}",
                        "/".join(
                            _fmt(metrics[model]["winner_probability"])
                            for model in ("current", "selected", "market")
                        ),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "| Unit | Slice | Current/selected/market log loss | Δ log loss (95% CI) | Log-loss signs F/U/T | Δ winner P (95% CI) | Winner signs F/U/T |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for scope in ("all_hours", "predawn_03_05", "evening_15_23"):
            row = primary.get((unit, scope))
            if not row:
                continue
            metrics = row["metrics"]
            logloss = row["selected_vs_current"]["logloss"]
            winner = row["selected_vs_current"]["winner_probability"]
            logloss_ci = logloss["paired_fleet_date_bootstrap_95ci"]
            winner_ci = winner["paired_fleet_date_bootstrap_95ci"]
            logloss_sign = logloss["paired_fleet_date_sign_test"]
            winner_sign = winner["paired_fleet_date_sign_test"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        unit,
                        scope,
                        "/".join(
                            _fmt(metrics[model]["logloss"])
                            for model in ("current", "selected", "market")
                        ),
                        f"{_fmt(logloss['mean_delta'])} [{_fmt(logloss_ci['low'])}, {_fmt(logloss_ci['high'])}]",
                        f"{logloss_sign['favorable']}/{logloss_sign['unfavorable']}/{logloss_sign['ties']}",
                        f"{_fmt(winner['mean_delta'])} [{_fmt(winner_ci['low'])}, {_fmt(winner_ci['high'])}]",
                        f"{winner_sign['favorable']}/{winner_sign['unfavorable']}/{winner_sign['ties']}",
                    ]
                )
                + " |"
            )


def _append_decision_analysis(
    lines: list[str],
    payload: Mapping[str, Any],
    primary: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    c_predawn = primary.get(("C", "predawn_03_05"))
    f_all = primary.get(("F", "all_hours"))
    f_predawn = primary.get(("F", "predawn_03_05"))
    f_evening = primary.get(("F", "evening_15_23"))
    if not all((c_predawn, f_all, f_predawn, f_evening)):
        lines.extend(
            [
                "## Decision and interpretation",
                "",
                "Major-slice coverage is incomplete, so no aggregate decision is rendered.",
                "See the available rows and exact coverage diagnostics below.",
                "",
            ]
        )
        return
    strict_coverage = {
        (str(row["unit"]), str(row["scope"])): row
        for row in payload["complete_panel_sensitivity"]["coverage"]
        if row["split"] == "holdout"
    }
    mechanics = payload.get("sharpness_mechanics") or {}
    mechanics_index = {
        (str(row["unit"]), str(row["scope"])): row
        for row in mechanics.get("summaries") or []
        if row["market_id"] == "__fleet__" and row["split"] == "holdout"
    }
    mechanics_lines = []
    if all(
        (unit, scope) in mechanics_index
        for unit in UNITS
        for scope in ("all_hours", "predawn_03_05", "evening_15_23")
    ):
        c_shape = mechanics_index[("C", "all_hours")]
        f_shape = mechanics_index[("F", "all_hours")]
        mechanics_lines = [
            "- Exact final-distribution mechanics classify W1 as `DIFFUSER_ALL_THREE`",
            "  in all six major slices: entropy rises, maximum bucket mass falls, and",
            "  bucket-key standard deviation rises, with every paired interval in the",
            f"  diffusion direction. All-hours C changes are entropy {_fmt(c_shape['selected_vs_current']['shannon_entropy_nats']['mean_delta'])}, "
            f"max mass {_fmt(c_shape['selected_vs_current']['max_bucket_probability']['mean_delta'])}, "
            f"and spread {_fmt(c_shape['selected_vs_current']['std_native']['mean_delta'])}°C; "
            f"F changes are {_fmt(f_shape['selected_vs_current']['shannon_entropy_nats']['mean_delta'])}, "
            f"{_fmt(f_shape['selected_vs_current']['max_bucket_probability']['mean_delta'])}, and "
            f"{_fmt(f_shape['selected_vs_current']['std_native']['mean_delta'])}°F "
            f"({_fmt(f_shape['selected_vs_current']['std_c_equivalent']['mean_delta'])}°C-equivalent).",
        ]
    ten_minute_scopes = tuple(
        f"ten_minute_{hour:02d}{minute:02d}"
        for hour in PREDAWN_HOURS
        for minute in range(0, 60, 10)
    )
    strict = _summary_index(
        payload["complete_panel_sensitivity"]["summaries"], split="holdout"
    )
    ten_minute_rows = {
        unit: [
            primary[(unit, scope)]
            for scope in ten_minute_scopes
            if (unit, scope) in primary
        ]
        for unit in UNITS
    }
    strict_ten_minute_rows = {
        unit: [
            strict[(unit, scope)]
            for scope in ten_minute_scopes
            if (unit, scope) in strict
        ]
        for unit in UNITS
    }
    ten_minute_lines = []
    if all(
        len(ten_minute_rows[unit]) == len(ten_minute_scopes)
        and len(strict_ten_minute_rows[unit]) == len(ten_minute_scopes)
        for unit in UNITS
    ):
        point_better = {
            unit: {
                metric: sum(
                    row["selected_vs_current"][metric]["mean_delta"] < 0.0
                    for row in ten_minute_rows[unit]
                )
                for metric in ("brier", "logloss")
            }
            for unit in UNITS
        }
        interval_better = {
            unit: {
                metric: sum(
                    row["selected_vs_current"][metric][
                        "paired_fleet_date_bootstrap_95ci"
                    ]["high"]
                    < 0.0
                    for row in ten_minute_rows[unit]
                )
                for metric in ("brier", "logloss")
            }
            for unit in UNITS
        }
        winner_point_up = {
            unit: sum(
                row["selected_vs_current"]["winner_probability"]["mean_delta"]
                > 0.0
                for row in ten_minute_rows[unit]
            )
            for unit in UNITS
        }
        winner_interval_excludes_zero = sum(
            ci["low"] > 0.0 or ci["high"] < 0.0
            for unit in UNITS
            for row in ten_minute_rows[unit]
            for ci in (
                row["selected_vs_current"]["winner_probability"][
                    "paired_fleet_date_bootstrap_95ci"
                ],
            )
        )
        strict_f_winner_point_up = sum(
            row["selected_vs_current"]["winner_probability"]["mean_delta"] > 0.0
            for row in strict_ten_minute_rows["F"]
        )
        market_all_three_supported = sum(
            comparison["brier"]["paired_fleet_date_bootstrap_95ci"]["low"] > 0.0
            and comparison["logloss"]["paired_fleet_date_bootstrap_95ci"]["low"]
            > 0.0
            and comparison["winner_probability"][
                "paired_fleet_date_bootstrap_95ci"
            ]["high"]
            < 0.0
            for unit in UNITS
            for row in ten_minute_rows[unit]
            for comparison in (row["selected_vs_market_inference"],)
        )
        ten_minute_lines = [
            (
                "- Fixed ten-minute audit: W1 point Brier/log-loss is lower in "
                f"C {point_better['C']['brier']}/{len(ten_minute_scopes)} and "
                f"{point_better['C']['logloss']}/{len(ten_minute_scopes)} slots; "
                f"F {point_better['F']['brier']}/{len(ten_minute_scopes)} and "
                f"{point_better['F']['logloss']}/{len(ten_minute_scopes)}. "
                "Paired intervals support those directions for Brier C "
                f"{interval_better['C']['brier']}/{len(ten_minute_scopes)}, F "
                f"{interval_better['F']['brier']}/{len(ten_minute_scopes)} and "
                f"log loss C {interval_better['C']['logloss']}/"
                f"{len(ten_minute_scopes)}, F "
                f"{interval_better['F']['logloss']}/{len(ten_minute_scopes)}."
            ),
            (
                "- Winner probability rises at the point estimate in C "
                f"{winner_point_up['C']}/{len(ten_minute_scopes)} and F "
                f"{winner_point_up['F']}/{len(ten_minute_scopes)} slots, but "
                f"{winner_interval_excludes_zero}/"
                f"{len(ten_minute_scopes) * len(UNITS)} slot intervals exclude "
                "zero in either direction. Under the strict complete F panel, "
                f"only {strict_f_winner_point_up}/{len(ten_minute_scopes)} point "
                "estimates rise, exposing composition sensitivity."
            ),
            (
                "- Captured market is confidence-supported better than W1 on all "
                f"three metrics in {market_all_three_supported}/"
                f"{len(ten_minute_scopes) * len(UNITS)} unit-slots. These correlated, "
                "unadjusted holdout slices are descriptive and select no slot."
            ),
        ]
    lines.extend(
        [
            "## Decision and interpretation",
            "",
            "**Do not promote W1 as the under-sharpness fix.** It improves proper",
            "losses in useful slices, but untouched holdout does not support an",
            "all-three improvement in Brier, log loss, and realized-winner probability.",
            "",
            (
                "- F: Brier/log-loss improve with 95% paired fleet-date intervals "
                "below zero for all-hours, predawn, and evening. Yet winner probability "
                f"changes by {_fmt(f_all['selected_vs_current']['winner_probability']['mean_delta'])} "
                f"all-hours, {_fmt(f_predawn['selected_vs_current']['winner_probability']['mean_delta'])} "
                f"predawn, and {_fmt(f_evening['selected_vs_current']['winner_probability']['mean_delta'])} "
                "evening. The all-hours and evening decreases are confidence-supported."
            ),
            (
                "- C predawn is the only directional all-three slice: Brier "
                f"{_fmt(c_predawn['selected_vs_current']['brier']['mean_delta'])}, "
                f"log loss {_fmt(c_predawn['selected_vs_current']['logloss']['mean_delta'])}, "
                f"winner probability {_fmt(c_predawn['selected_vs_current']['winner_probability']['mean_delta'])}. "
                "Only the two proper-loss intervals exclude zero; winner probability does not."
            ),
            "- The market remains confidence-supported better than selected W1 on",
            "  Brier, log loss, and winner probability in all six C/F major holdout",
            "  slices. Smoothing narrows some loss gaps but does not close the frontier.",
            "- Neither incumbent nor W1 has joint three-metric edge at any observed",
            "  15:00-23:00 hour. Market catch-up is already present at 15:00; it is",
            "  confidence-supported from 16:00 for C W1 and 15:00 for F W1.",
            (
                "- Fixed-composition F coverage retains "
                f"{strict_coverage[('F', 'all_hours')]['complete_panel_fleet_dates']}/"
                f"{strict_coverage[('F', 'all_hours')]['available_case_fleet_dates']} all-hours, "
                f"{strict_coverage[('F', 'predawn_03_05')]['complete_panel_fleet_dates']}/"
                f"{strict_coverage[('F', 'predawn_03_05')]['available_case_fleet_dates']} predawn, and "
                f"{strict_coverage[('F', 'evening_15_23')]['complete_panel_fleet_dates']}/"
                f"{strict_coverage[('F', 'evening_15_23')]['available_case_fleet_dates']} evening dates "
                "and reproduces the same proper-loss/winner-probability tradeoff."
            ),
            *mechanics_lines,
            *ten_minute_lines,
            "",
            "### Useful next experiment",
            "",
            "Run a new, predeclared tune/holdout experiment—not a re-read of this",
            "holdout—with family-aware and time-conditioned candidates. H1 sigma=0.75",
            "uses raw native numeric bucket-key distance: 0.75°C for C, but 0.75°F",
            "(0.4167°C) for F, so it is not a common physical bandwidth. Compare",
            "physically equivalent C/F bandwidths and an early-hours-only C arm against",
            "weight zero. Require non-degradation in realized-winner probability as a",
            "constraint while ranking Brier/log-loss; correct any hourly or city search",
            "for multiplicity. The apparent C 00:00-06:00 opportunity and city extremes",
            "below are hypotheses only and cannot select a candidate from this holdout.",
            "",
        ]
    )


def _append_complete_panel_sensitivity(
    lines: list[str], payload: Mapping[str, Any]
) -> None:
    sensitivity = payload["complete_panel_sensitivity"]
    summaries = _summary_index(sensitivity["summaries"], split="holdout")
    coverage = {
        (str(row["unit"]), str(row["scope"])): row
        for row in sensitivity["coverage"]
        if row["split"] == "holdout"
    }
    configured = sensitivity["configured_markets_by_unit"]
    lines.extend(
        [
            "",
            "## Complete configured-market panel sensitivity",
            "",
            (
                "This secondary check holds city composition fixed at all 12 configured "
                "markets, evaluated inside native units: C requires "
                f"{len(configured['C'])} ({', '.join(configured['C'])}); F requires "
                f"{len(configured['F'])} ({', '.join(configured['F'])})."
            ),
            "A date/slot is retained only when every configured market for that unit is",
            "present. Missing cities are dropped and counted; no imputation or partial",
            "panel substitution is allowed. This sensitivity does not replace the",
            "aligned equal-market/equal-date primary result.",
            "",
            "| Unit | Slice | Available dates | Complete dates | Dropped | Δ Brier | Δ log loss | Δ winner P | Disposition |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for unit in UNITS:
        for scope in ("all_hours", "predawn_03_05", "evening_15_23"):
            audit = coverage[(unit, scope)]
            row = summaries.get((unit, scope))
            values = (
                [
                    _fmt(row["selected_vs_current"][metric]["mean_delta"])
                    for metric in ("brier", "logloss", "winner_probability")
                ]
                if row
                else ["unsupported", "unsupported", "unsupported"]
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        unit,
                        scope,
                        str(audit["available_case_fleet_dates"]),
                        str(audit["complete_panel_fleet_dates"]),
                        str(audit["dropped_incomplete_fleet_dates"]),
                        *values,
                        str(row["selected_effect_disposition"])
                        if row
                        else "NO_COMPLETE_DATES",
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "Focused hourly coverage and Brier sensitivity:",
            "",
            "| Unit | Hour | Available dates | Complete dates | Missing-panel dates | Δ selected-current Brier | Selected-market Brier Δ |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for unit in UNITS:
        for hour in (*PREDAWN_HOURS, *EVENING_HOURS):
            scope = f"hour_{hour:02d}"
            audit = coverage[(unit, scope)]
            row = summaries.get((unit, scope))
            lines.append(
                "| "
                + " | ".join(
                    [
                        unit,
                        f"{hour:02d}:00",
                        str(audit["available_case_fleet_dates"]),
                        str(audit["complete_panel_fleet_dates"]),
                        str(audit["dropped_incomplete_fleet_dates"]),
                        _fmt(row["selected_vs_current"]["brier"]["mean_delta"])
                        if row
                        else "unsupported",
                        _fmt(row["selected_vs_market"]["brier"])
                        if row
                        else "unsupported",
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "All 24 hourly coverage rows, exact retained/dropped dates, strict-panel",
            "summaries, and strict-panel breakpoints are preserved in the JSON and",
            "dedicated CSV/coverage artifacts. Slots with zero complete dates remain",
            "explicitly unsupported.",
        ]
    )


def _append_sharpness_mechanics(lines: list[str], payload: Mapping[str, Any]) -> None:
    mechanics = payload.get("sharpness_mechanics")
    if not mechanics:
        return
    summaries = {
        (str(row["unit"]), str(row["scope"])): row
        for row in mechanics["summaries"]
        if row["market_id"] == "__fleet__" and row["split"] == "holdout"
    }
    lines.extend(
        [
            "",
            "## Distribution-sharpness mechanics (descriptive holdout diagnostic)",
            "",
            "These are exact replay bucket distributions aligned W1-to-W0, then",
            "weighted snapshot -> market-date -> equal-market fleet-date -> equal date.",
            "Higher entropy, lower maximum-bucket probability, and higher standard",
            "deviation indicate diffusion. This post-selection diagnostic is not a new",
            "gate and did not select an arm. Entropy is compared only within unit; F",
            "standard deviation is also converted to C-equivalent width by multiplying",
            "by 5/9.",
            "",
            "| Unit | Slice | Dates | Entropy current/selected/Δ (95% CI) | Max bucket current/selected/Δ (95% CI) | Std native current/selected/Δ (95% CI) | Std C-equivalent current/selected/Δ | Shape |",
            "| --- | --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for scope in ("all_hours", "predawn_03_05", "evening_15_23"):
            row = summaries.get((unit, scope))
            if not row:
                continue
            cells = []
            for metric in (
                "shannon_entropy_nats",
                "max_bucket_probability",
                "std_native",
            ):
                comparison = row["selected_vs_current"][metric]
                ci = comparison["paired_fleet_date_bootstrap_95ci"]
                cells.append(
                    f"{_fmt(row['metrics']['current'][metric])}/"
                    f"{_fmt(row['metrics']['selected'][metric])}/"
                    f"{_fmt(comparison['mean_delta'])} "
                    f"[{_fmt(ci['low'])}, {_fmt(ci['high'])}]"
                )
            physical = row["selected_vs_current"]["std_c_equivalent"]
            cells.append(
                f"{_fmt(row['metrics']['current']['std_c_equivalent'])}/"
                f"{_fmt(row['metrics']['selected']['std_c_equivalent'])}/"
                f"{_fmt(physical['mean_delta'])}"
            )
            lines.append(
                f"| {unit} | {scope} | {row['fleet_dates']} | "
                + " | ".join(cells)
                + f" | {row['descriptive_shape_direction']} |"
            )
    lines.extend(
        [
            "",
            "Paired fleet-date sign counts, all 24 hourly slices, per-market rows,",
            "reader bounds, probability-mass error, and 10,000-replicate intervals",
            "are preserved in `sharpness_mechanics.json`.",
        ]
    )


def _append_predawn_ten_minute_evidence(
    lines: list[str], payload: Mapping[str, Any]
) -> None:
    primary = _summary_index(payload["summaries"], split="holdout")
    sensitivity = payload["complete_panel_sensitivity"]
    strict = _summary_index(sensitivity["summaries"], split="holdout")
    coverage = {
        (str(row["unit"]), str(row["scope"])): row
        for row in sensitivity["coverage"]
        if row["split"] == "holdout"
    }
    slots = [
        (hour, minute, f"ten_minute_{hour:02d}{minute:02d}")
        for hour in PREDAWN_HOURS
        for minute in range(0, 60, 10)
    ]
    lines.extend(
        [
            "",
            "## Fixed predawn ten-minute evidence (descriptive, multiplicity-sensitive)",
            "",
            "All 18 local slots from 03:00-03:09 through 05:50-05:59 are shown;",
            "none selected the arm or was selected after viewing holdout. The primary",
            "uses aligned snapshot -> market-date -> equal-market fleet-date -> equal",
            "date weighting. Strict-panel columns retain a slot/date only when every",
            "configured market in its native unit is present; missing cities are never",
            "imputed. With 18 correlated slot comparisons per unit and no multiplicity",
            "adjustment, these rows are descriptive and are not a ten-minute gate.",
            "",
            "| Unit | Slot | Available dates | Markets/date min-max | Strict complete/dropped | W1-W0 Brier/log-loss/winner-P | Strict W1-W0 Brier/log-loss/winner-P |",
            "| --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for hour, minute, scope in slots:
            row = primary.get((unit, scope))
            strict_row = strict.get((unit, scope))
            audit = coverage[(unit, scope)]
            if row:
                market_coverage = row["market_coverage_per_fleet_date"]
                market_range = (
                    f"{market_coverage['minimum']}-{market_coverage['maximum']}"
                )
                primary_values = "/".join(
                    _fmt(row["selected_vs_current"][metric]["mean_delta"])
                    for metric in ("brier", "logloss", "winner_probability")
                )
            else:
                market_range = "unsupported"
                primary_values = "unsupported"
            strict_values = (
                "/".join(
                    _fmt(strict_row["selected_vs_current"][metric]["mean_delta"])
                    for metric in ("brier", "logloss", "winner_probability")
                )
                if strict_row
                else "unsupported"
            )
            lines.append(
                f"| {unit} | {hour:02d}:{minute:02d}-{hour:02d}:{minute + 9:02d} | "
                f"{audit['available_case_fleet_dates']} | {market_range} | "
                f"{audit['complete_panel_fleet_dates']}/"
                f"{audit['dropped_incomplete_fleet_dates']} | {primary_values} | "
                f"{strict_values} |"
            )
    lines.extend(
        [
            "",
            "W1 versus captured-market deltas for the same fixed slots:",
            "",
            "| Unit | Slot | W1-market Brier | W1-market log loss | W1-market winner P |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for unit in UNITS:
        for hour, minute, scope in slots:
            row = primary.get((unit, scope))
            values = (
                [
                    _fmt(row["selected_vs_market_inference"][metric]["mean_delta"])
                    for metric in ("brier", "logloss", "winner_probability")
                ]
                if row
                else ["unsupported", "unsupported", "unsupported"]
            )
            lines.append(
                f"| {unit} | {hour:02d}:{minute:02d}-{hour:02d}:{minute + 9:02d} | "
                + " | ".join(values)
                + " |"
            )
    lines.extend(
        [
            "",
            "Every slot's 10,000-replicate paired fleet-date interval, sign counts,",
            "per-market row, and strict-panel counterpart is retained in the result",
            "JSON and primary/strict summary CSVs.",
        ]
    )


def _append_collision_audit(lines: list[str], payload: Mapping[str, Any]) -> None:
    lines.extend(
        [
            "",
            "## Snapshot identity collision handling",
            "",
            "The H1 identity contract keeps the first repeated key only when replayed",
            "probability, outcome, market quote, and native unit are canonically",
            "identical (NaN-safe). Any scoring-field conflict blocks; non-scoring",
            "`recorded_p` is ignored for current replay.",
            "",
            "| Split | Raw rows | Unique keys | Equivalent extras | Affected market-dates |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for split in payload["split"]["analyzed_splits"]:
        alignment = ((payload.get("reader_diagnostics") or {}).get(split) or {}).get(
            "alignment"
        ) or {}
        affected = ", ".join(
            f"{row['market_id']} {row['target_date']}"
            for row in alignment.get("duplicate_market_dates") or []
        ) or "none"
        lines.append(
            f"| {split} | {alignment.get('raw_rows', '-')} | "
            f"{alignment.get('unique_rows', '-')} | "
            f"{alignment.get('equivalent_duplicate_rows_collapsed', '-')} | "
            f"{affected} |"
        )


def _append_historical_context(lines: list[str], payload: Mapping[str, Any]) -> None:
    historical = payload.get("historical_context")
    if not historical:
        return
    lines.extend(
        [
            "",
            "## Dated historical comparator (post-hoc, noncomparable context)",
            "",
            f"The read-only `{historical['schema_version']}` artifact spans "
            f"{historical['date_min']} through {historical['date_max']} "
            f"({historical['scored_market_days']} market-days), gate "
            f"`{historical['gate_status']}`. {historical['methodology_difference']}. "
            "It is never pooled with H1 and cannot select or validate an H1 arm.",
            "",
            "| Hour | Days | Historical model/market Brier | Model-market Δ | Historical model/market winner P |",
            "| ---: | ---: | --- | ---: | --- |",
        ]
    )
    for row in historical["hours"]:
        lines.append(
            f"| {row['hour']:02d}:00 | {row['market_days']} | "
            f"{_fmt(row['model_brier'])}/{_fmt(row['market_brier'])} | "
            f"{_fmt(row['model_brier'] - row['market_brier'])} | "
            f"{_fmt(row['model_winner_probability'])}/"
            f"{_fmt(row['market_winner_probability'])} |"
        )
    lines.extend(["", "Directional reproduction against H1:", ""])
    for row in payload.get("historical_pattern_reproduction") or []:
        reproduced = row["predawn_direction_reproduced"]
        label = (
            "reproduced"
            if reproduced is True
            else "not reproduced"
            if reproduced is False
            else "not assessable (missing H1 predawn hour)"
        )
        lines.append(
            f"- {row['unit']}: predawn model-trails-market pattern {label}; "
            f"H1 selected-market Brier {_fmt(row['h1_selected_market_brier_delta'])}, "
            f"winner-P {_fmt(row['h1_selected_market_winner_probability_delta'])}."
        )
    lines.append(f"- Historical SHA-256: `{historical['sha256']}`.")


def _append_hourly_frontiers(
    lines: list[str], payload: Mapping[str, Any], primary: Mapping[tuple[str, str], Mapping[str, Any]]
) -> None:
    lines.extend(
        [
            "",
            "## Predawn hourly frontier (untouched holdout)",
            "",
            "| Unit | Hour | Dates | Markets/date min-max | Current/selected/market Brier | Current/selected/market winner P |",
            "| --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for hour in PREDAWN_HOURS:
            row = primary.get((unit, f"hour_{hour:02d}"))
            if not row:
                continue
            metrics = row["metrics"]
            coverage = row["market_coverage_per_fleet_date"]
            lines.append(
                f"| {unit} | {hour:02d}:00 | {row['fleet_dates']} | "
                f"{coverage['minimum']}-{coverage['maximum']} | "
                + "/".join(_fmt(metrics[m]["brier"]) for m in ("current", "selected", "market"))
                + " | "
                + "/".join(
                    _fmt(metrics[m]["winner_probability"])
                    for m in ("current", "selected", "market")
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Evening collapse, catch-up, and thresholds",
            "",
            "A sustained condition must hold through every later observed evening hour;",
            "confidence-supported catch-up additionally requires the paired fleet-date",
            "interval to support the market rather than only a point crossover.",
            "",
            "| Unit | Model | First joint failure | Sustained collapse | First catch-up | Sustained catch-up | Confidence-supported catch-up |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["breakpoints"]:
        if row["split"] == "holdout" and row["market_id"] == "__fleet__":
            lines.append(
                f"| {row['unit']} | {row['model']} | "
                f"{_fmt(row['first_joint_edge_failure_after_positive_hour'], 0)} | "
                f"{_fmt(row['sustained_joint_edge_collapse_hour'], 0)} | "
                f"{_fmt(row['first_market_catchup_hour'], 0)} | "
                f"{_fmt(row['sustained_market_catchup_hour'], 0)} | "
                f"{_fmt(row['sustained_confidence_supported_market_catchup_hour'], 0)} |"
            )
    lines.extend(["", "Exact selected-model hour sets:", ""])
    for row in payload["breakpoints"]:
        if (
            row["split"] == "holdout"
            and row["market_id"] == "__fleet__"
            and row["model"] == "selected"
        ):
            joint = ", ".join(f"{h:02d}:00" for h in row["joint_edge_hours"]) or "none"
            caught = ", ".join(f"{h:02d}:00" for h in row["market_catchup_hours"]) or "none"
            supported = ", ".join(
                f"{h:02d}:00" for h in row["confidence_supported_market_catchup_hours"]
            ) or "none"
            lines.append(
                f"- {row['unit']}: joint edge {joint}; catch-up {caught}; "
                f"confidence-supported catch-up {supported}."
            )
    lines.extend(
        [
            "",
            "| Unit | Series | ≥40% | ≥50% | ≥80% | ≥90% |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for unit in UNITS:
        unit_rows = [
            row
            for row in payload["breakpoints"]
            if row["split"] == "holdout"
            and row["market_id"] == "__fleet__"
            and row["unit"] == unit
        ]
        selected_row = next((row for row in unit_rows if row["model"] == "selected"), None)
        for model in ("current", "selected"):
            row = next((item for item in unit_rows if item["model"] == model), None)
            if not row:
                continue
            crossings = row["threshold_crossings"]
            values = [
                crossings[f"{model}_sustained_winner_probability_ge_{token}"]
                for token in ("0p4", "0p5", "0p8", "0p9")
            ]
            lines.append(
                f"| {unit} | {model} | " + " | ".join(_fmt(v, 0) for v in values) + " |"
            )
        if selected_row:
            crossings = selected_row["threshold_crossings"]
            values = [
                crossings[f"market_sustained_winner_probability_ge_{token}"]
                for token in ("0p4", "0p5", "0p8", "0p9")
            ]
            lines.append(
                f"| {unit} | market | " + " | ".join(_fmt(v, 0) for v in values) + " |"
            )
    lines.extend(
        [
            "",
            "### Evening hourly scores",
            "",
            "| Unit | Hour | Dates | Markets/date min-max | Current/selected/market Brier | Current/selected/market winner P |",
            "| --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for hour in EVENING_HOURS:
            row = primary.get((unit, f"hour_{hour:02d}"))
            if not row:
                continue
            metrics = row["metrics"]
            coverage = row["market_coverage_per_fleet_date"]
            lines.append(
                f"| {unit} | {hour:02d}:00 | {row['fleet_dates']} | "
                f"{coverage['minimum']}-{coverage['maximum']} | "
                + "/".join(_fmt(metrics[m]["brier"]) for m in ("current", "selected", "market"))
                + " | "
                + "/".join(
                    _fmt(metrics[m]["winner_probability"])
                    for m in ("current", "selected", "market")
                )
                + " |"
            )


def _append_tune_holdout_and_markets(
    lines: list[str], payload: Mapping[str, Any]
) -> None:
    summaries = payload["summaries"]
    index = {
        (row["split"], row["unit"], row["scope"]): row
        for row in summaries
        if row["market_id"] == "__fleet__"
    }
    lines.extend(
        [
            "",
            "## Tune-to-holdout selection check",
            "",
            "Tune is exploratory selection context. A tune sign that does not repeat",
            "on untouched holdout is not evidence for the selected arm.",
            "",
            "| Unit | Slice | Tune/holdout Δ Brier | Tune/holdout Δ log loss | Tune/holdout Δ winner P |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for unit in UNITS:
        for scope in ("all_hours", "predawn_03_05", "evening_15_23"):
            tune = index.get(("tune", unit, scope))
            holdout = index.get(("holdout", unit, scope))
            if not tune or not holdout:
                continue
            pairs = []
            for metric in ("brier", "logloss", "winner_probability"):
                pairs.append(
                    f"{_fmt(tune['selected_vs_current'][metric]['mean_delta'])}/"
                    f"{_fmt(holdout['selected_vs_current'][metric]['mean_delta'])}"
                )
            lines.append(f"| {unit} | {scope} | " + " | ".join(pairs) + " |")
    lines.extend(
        [
            "",
            "## Per-market holdout extremes",
            "",
            "Negative selected-minus-market Brier is better. These localize fleet",
            "results; they are not separately selected arms.",
            "",
            "| Unit | Slice | Side | Market | Dates | Selected-market Brier Δ | Selected-current Brier Δ |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for unit in UNITS:
        for scope in ("predawn_03_05", "evening_15_23", "all_hours"):
            candidates = [
                row
                for row in summaries
                if row["split"] == "holdout"
                and row["unit"] == unit
                and row["market_id"] != "__fleet__"
                and row["scope"] == scope
            ]
            candidates.sort(key=lambda row: row["selected_vs_market"]["brier"])
            for side, row in _labeled_extremes(candidates):
                lines.append(
                    f"| {unit} | {scope} | {side} | {row['market_id']} | "
                    f"{row['fleet_dates']} | {_fmt(row['selected_vs_market']['brier'])} | "
                    f"{_fmt(row['selected_vs_current']['brier']['mean_delta'])} |"
                )


def _append_provenance(lines: list[str], payload: Mapping[str, Any]) -> None:
    lines.extend(
        [
            "",
            "## Denver 2026-07-19 bounded case",
            "",
            payload["denver_2026_07_19_case"]["interpretation"],
            "",
            "## Provenance and safety",
            "",
            f"- H1 result: `{payload['selection']['h1_result_path']}`",
            f"- H1 result SHA-256: `{payload['selection']['h1_result_sha256']}`",
            f"- H1 corpus: `{(payload.get('inputs', {}).get('h1') or {}).get('corpus_path', '-')}`",
            f"- H1 corpus hash: `{(payload.get('inputs', {}).get('h1') or {}).get('corpus_hash', '-')}`",
            f"- Tune dates: {', '.join(payload['split']['tune_dates'])}",
            f"- Holdout dates: {', '.join(payload['split']['holdout_dates'])}",
            "- Raw caches were opened read-only with fixed streaming bounds; no full",
            f"  cache/replay array was loaded, and the identity index is capped at {MAX_ALIGNMENT_KEYS}.",
            "- Cache fingerprints, SHA-256 values, reader high-water marks, complete",
            "  panel coverage, and output hashes are preserved in machine artifacts.",
            "- Mirrored `data/` remained read only. No serving, release, promotion,",
            "  artifact, trading, or live state changed.",
            "",
        ]
    )


def render_blocked_report(payload: Mapping[str, Any]) -> str:
    blockers = payload.get("analysis_blockers") or ["input integrity gate blocked"]
    lines = [
        "# Workstation current-replay time frontier — 2026-07-22",
        "",
        "## Verdict",
        "",
        "**BLOCK — no time-frontier estimates are countable.** The bounded reader",
        "stopped on input integrity; no failed partial estimate is reported.",
        "",
        "Blockers:",
        "",
        *[f"- {value}" for value in blockers],
    ]
    _append_collision_audit(lines, payload)
    _append_provenance(lines, payload)
    return "\n".join(lines)


def render_tune_only_report(payload: Mapping[str, Any]) -> str:
    selected = payload["selection"]["selected_weights"]
    primary = _summary_index(payload["summaries"], split="tune")
    lines = [
        "# Workstation current-replay time frontier — 2026-07-22",
        "",
        "## Verdict",
        "",
        "**TUNE-ONLY EXPLORATORY — not holdout evidence.** H1 remained BLOCK and",
        "holdout stayed `NOT_TOUCHED`; no holdout cache path was constructed or",
        "opened. The rows below only diagnose finalized tune caches.",
        "",
        f"Tune-selected weights recorded by H1: C={selected['C']}, F={selected['F']}.",
        "",
    ]
    _append_primary_score_tables(lines, primary)
    _append_collision_audit(lines, payload)
    _append_historical_context(lines, payload)
    _append_provenance(lines, payload)
    return "\n".join(lines)


def render_complete_report(payload: Mapping[str, Any]) -> str:
    selected = payload["selection"]["selected_weights"]
    primary = _summary_index(payload["summaries"], split="holdout")
    lines = [
        "# Workstation current-replay time frontier — 2026-07-22",
        "",
        "## Verdict",
        "",
        "Research-only current-code replay evidence: H1 selected weights on tune",
        f"only (C={selected['C']}, F={selected['F']}); only those arms and the actual",
        "weight-zero incumbent were opened on untouched holdout. No unselected",
        "holdout arm was discovered or scored.",
        "",
        "The primary result averages snapshots within market-date, markets within",
        "fleet-date equally, then fleet dates equally. Raw band/cadence density cannot",
        "dominate. Captured market quotes remain raw and are not normalized post hoc.",
        "",
    ]
    _append_decision_analysis(lines, payload, primary)
    _append_primary_score_tables(lines, primary)
    _append_predawn_ten_minute_evidence(lines, payload)
    _append_sharpness_mechanics(lines, payload)
    _append_complete_panel_sensitivity(lines, payload)
    _append_collision_audit(lines, payload)
    _append_historical_context(lines, payload)
    _append_hourly_frontiers(lines, payload, primary)
    _append_tune_holdout_and_markets(lines, payload)
    _append_provenance(lines, payload)
    return "\n".join(lines)


def render_report(payload: Mapping[str, Any]) -> str:
    """Render the report matching the fail-closed analysis state."""

    if payload.get("analysis_status") == "BLOCKED_INPUT_INTEGRITY":
        return render_blocked_report(payload)
    if payload.get("analysis_status") == "COMPLETE_TUNE_ONLY_EXPLORATORY":
        return render_tune_only_report(payload)
    return render_complete_report(payload)


__all__ = [
    "render_blocked_report",
    "render_complete_report",
    "render_report",
    "render_tune_only_report",
]
