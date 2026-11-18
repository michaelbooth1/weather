"""Render the legacy tape calibration trainer report from its emitted artifact."""

from pathlib import Path


def write_report(path, artifact):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    training = artifact["training"]
    selected = artifact["selected_deployable_candidate"]
    market_config = artifact["market_bin"]
    exact = artifact["exact_distribution"]
    market_baseline = market_config.get("best_market_informed_baseline")
    if not market_config.get("enabled", True):
        serving_rule = "The market-bin transform is disabled. It returns its input probability."
    elif market_config.get("preserve_distribution_coherence", True):
        serving_rule = ("The market-bin transform applies hard support and otherwise returns "
                        "the band probability from the distribution.")
    else:
        method = market_config.get("method", "prior_shrink")
        supported = {"temperature", "platt", "prior_shrink", "market_shrink"}
        mapped = method if method in supported else "prior_shrink (default branch)"
        serving_rule = f"The market-bin transform applies hard support and its scalar mapping (`{mapped}`)."
    lines = [
        "# Probability Calibration Report",
        "",
        f"Generated: {artifact['generated_at_utc']}",
        "",
        "## Scope",
        "",
        f"- Training rows: {training['rows']}",
        f"- Target dates: {', '.join(training['target_dates'])}",
        f"- Baseline Brier: {training['baseline_brier']:.4f}",
        f"- Baseline log loss: {training['baseline_logloss']:.4f}",
        f"- Market Brier: {training['market_brier']:.4f}",
        f"- Market log loss: {training['market_logloss']:.4f}",
        f"- Baseline Brier skill vs market: {training['baseline_brier_skill_vs_market']:.3f}",
        f"- Binary candidate LOO Brier skill vs market: {training['selected_brier_skill_vs_market']:.3f}",
        f"- Market-bin replay Brier on training rows: {training['artifact_replay_brier']:.4f}",
        f"- Market-bin replay log loss on training rows: {training['artifact_replay_logloss']:.4f}",
        f"- Market-bin replay Brier skill vs market on training rows: {training['artifact_replay_brier_skill_vs_market']:.3f}",
        "",
        "## Highest-ranked weather-only binary candidate",
        "",
        f"- Method: `{selected['method']}`",
        f"- Parameter: `{selected['param']}`",
        f"- LOO Brier: {selected['brier']:.4f}",
        f"- LOO log loss: {selected['logloss']:.4f}",
        "",
    ]
    lines.extend([
        "## Emitted market-bin behavior",
        "",
        serving_rule,
        "",
        "Market-bin replay applies this rule to captured scalar band probabilities. "
        "A full calibration replay also needs each pre-calibration degree distribution.",
        "",
    ])
    if market_baseline:
        lines += [
            "## Market-Informed Baseline",
            "",
            f"- Method: `{market_baseline['method']}`",
            f"- Parameter: `{market_baseline['param']}`",
            f"- LOO Brier: {market_baseline['brier']:.4f}",
            f"- LOO log loss: {market_baseline['logloss']:.4f}",
            "",
        ]

    lines += [
        "## Candidate Comparison",
        "",
        "| Method | Param | LOO Brier | LOO Log Loss |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for row in artifact["candidate_scores"]:
        lines.append(
            f"| {row['method']} | {row['param'] if row['param'] is not None else '-'} "
            f"| {row['brier']:.4f} | {row['logloss']:.4f} |"
        )
    lines += [
        "",
        "## Exact Distribution Calibration",
        "",
        f"- Method: `{exact['method']}`",
        f"- Temperature (global fallback): `{exact['temperature']}`",
        f"- Temperature by cutoff hour: `{exact.get('temperature_by_hour', {})}`",
        f"- Exact-row count: {exact.get('exact_row_count', 0)}",
        "",
    ]
    if "max_deployment_temperature" in exact:
        lines.append(f"- Max deployment temperature: `{exact['max_deployment_temperature']}`")
    if "unconstrained_best_temperature" in exact:
        lines.append(f"- Unconstrained best temperature: `{exact['unconstrained_best_temperature']}`")
    lines += [
        "",
        "The trainer ranks temperatures on individual non-tail band rows using a binary logit. "
        "Serving scales eligible degree probabilities by a power and normalizes the resulting distribution.",
        "",
        "## Context Summaries",
        "",
        "The optional scalar prior-shrink mapping searches these context keys in order: "
        "`kind+hour+distance`, `kind+distance`, `kind+hour`, `kind`, `global`.",
        "",
        "| Context | N | Smoothed Base Rate |",
        "| :--- | :--- | :--- |",
    ]
    for key, row in artifact["market_bin"]["contexts"].items():
        if key == "global" or row["n"] >= artifact["market_bin"]["min_context_n"]:
            lines.append(f"| {key} | {row['n']} | {row['base_rate'] * 100:.1f}% |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
