"""Measure the captured-station local-meteorology routing repair.

This is a read-only research CLI.  It compares the repaired serving path with
an otherwise identical control whose station row history is hidden while its
trusted top-level temperature/max evidence remains available.  No source is
fetched, no candidate is fitted, and no output may be written under ``data``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
import subprocess
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable, Mapping, Sequence

from weather.backtesting.replay import (
    as_int_distribution,
    distribution_l1,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
)
from weather.experiment_contract import finalize_self_hash
from weather.market.market_config import market_id_from_slug
from weather.market.market_registry import all_specs
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import data_path
from weather.schema_registry import schema_version


try:
    REPORT_SCHEMA_VERSION = schema_version("blind_feature_repair_replay")
except KeyError:
    # The provenance-frozen pre-roll runtime predates this read-only receipt
    # family.  Keeping the literal here lets that exact runtime supply model
    # behavior while the current tool still owns and validates the receipt.
    REPORT_SCHEMA_VERSION = "blind_feature_repair_replay_v0.1"
REPORT_HASH_FIELD = "report_sha256"
PROVENANCE_ANCHOR = "b77cfbed"
FEATURES = (
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
)
REGIMES = ("pre_2026_07_31_artifact", "post_2026_07_31_artifact")
DEFAULT_REPLICATES = 10_000
DEFAULT_SEED = 20_260_943
POSITIVE_CONTROL_TOLERANCE = 1e-12


class BlindFeatureRepairError(RuntimeError):
    """The replay cannot produce interpretable evidence."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_first_jsonl(path: Path) -> dict[str, Any] | None:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line)
    return None


def _current_settlement_index(root: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], int]:
    selected: dict[tuple[str, str], tuple[tuple[int, int], dict[str, Any]]] = {}
    raw_count = 0
    for path in sorted(root.glob("*/ledger.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle):
                if not line.strip():
                    continue
                raw_count += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                market_id = str(row.get("market_id") or path.parent.name)
                target_date = str(row.get("target_date") or "")
                if not target_date:
                    continue
                try:
                    revision = int(row.get("revision_number") or 0)
                except (TypeError, ValueError):
                    revision = 0
                key = (market_id, target_date)
                rank = (revision, line_number)
                if key not in selected or rank >= selected[key][0]:
                    selected[key] = (rank, dict(row))
    return {key: row for key, (_, row) in selected.items()}, raw_count


def _git_is_ancestor(ancestor: str, descendant: str, *, cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise BlindFeatureRepairError(
            f"cannot classify runtime commit {descendant}: {result.stderr.strip()}"
        )
    return result.returncode == 0


def provenance_regime(record: Mapping[str, Any], *, repo_root: Path) -> str:
    commit = str(((record.get("runtime_identity") or {}).get("git_commit") or "")).strip()
    if not commit:
        raise BlindFeatureRepairError("captured record has no runtime git commit")
    if _git_is_ancestor(PROVENANCE_ANCHOR, commit, cwd=repo_root):
        return REGIMES[1]
    known_commit = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0
    if known_commit:
        # Runtime worktrees can sit on side branches.  If their commit does
        # not contain the rollout anchor, the rollout is absent from that
        # captured tree and the snapshot belongs to the pre-anchor regime.
        return REGIMES[0]
    raise BlindFeatureRepairError(f"captured runtime commit {commit} is unavailable locally")


def control_sources(sources: Mapping[str, Any]) -> dict[str, Any]:
    """Hide station history without changing trusted top-level floor evidence."""

    control = copy.deepcopy(dict(sources))
    for source in ("metar", "eccc_swob"):
        item = control.get(source)
        if not isinstance(item, dict):
            continue
        payload = item.get("data")
        if not isinstance(payload, dict):
            continue
        payload["rows"] = []
        payload["raw_payload"] = {}
        payload["latest"] = None
    station = control.get("station_observations")
    if isinstance(station, dict) and isinstance(station.get("data"), dict):
        station["data"].pop("rows", None)
        station["data"].pop("latest", None)
    return control


def _center_width(distribution: Mapping[Any, Any]) -> tuple[float, float]:
    values = as_int_distribution(distribution)
    total = sum(values.values())
    if total <= 0:
        raise BlindFeatureRepairError("empty replay distribution")
    normalized = {bucket: value / total for bucket, value in values.items()}
    center = sum(bucket * value for bucket, value in normalized.items())
    width = math.sqrt(
        sum(value * (bucket - center) ** 2 for bucket, value in normalized.items())
    )
    return center, width


def _brier(distribution: Mapping[Any, Any], settlement_bucket: int) -> float:
    values = as_int_distribution(distribution)
    total = sum(values.values())
    if total <= 0:
        raise BlindFeatureRepairError("empty replay distribution")
    support = set(values) | {int(settlement_bucket)}
    return sum(
        ((values.get(bucket, 0.0) / total) - (1.0 if bucket == settlement_bucket else 0.0)) ** 2
        for bucket in support
    )


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _daily_cells(rows: Sequence[Mapping[str, Any]], metric: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(metric)
        if value is not None:
            grouped[(str(row["target_date"]), str(row["market_id"]))].append(float(value))
    return [
        {"target_date": target_date, "market_id": market_id, metric: statistics.fmean(values)}
        for (target_date, market_id), values in sorted(grouped.items())
    ]


def crossed_summary(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    import numpy as np

    cells = _daily_cells(rows, metric)
    dates = sorted({row["target_date"] for row in cells})
    markets = sorted({row["market_id"] for row in cells})
    values = {(row["target_date"], row["market_id"]): row[metric] for row in cells}
    point = _mean(row[metric] for row in cells)
    draws: list[float] = []
    rng = np.random.default_rng(seed)
    for _ in range(replicates):
        date_draw = rng.choice(dates, size=len(dates), replace=True)
        market_draw = rng.choice(markets, size=len(markets), replace=True)
        sampled = [
            values[(str(target_date), str(market_id))]
            for target_date in date_draw
            for market_id in market_draw
            if (str(target_date), str(market_id)) in values
        ]
        if sampled:
            draws.append(statistics.fmean(sampled))
    se = statistics.stdev(draws) if len(draws) >= 2 else None
    interval = [_percentile(draws, 0.025), _percentile(draws, 0.975)]
    normal = NormalDist()
    power = None
    mde = None
    if se is not None and se > 0 and point is not None:
        z = abs(point) / se
        critical = normal.inv_cdf(0.975)
        power = normal.cdf(-critical - z) + 1.0 - normal.cdf(critical - z)
        mde = (critical + normal.inv_cdf(0.8)) * se
    return {
        "daily_first_point": point,
        "crossed_95_interval": interval,
        "crossed_standard_error": se,
        "observed_effect_plugin_power": power,
        "two_sided_80pct_power_mde": mde,
        "date_clusters": len(dates),
        "market_clusters": len(markets),
        "market_days": len(cells),
        "bootstrap_replicates": len(draws),
        "bootstrap_seed": seed,
    }


def _feature_counts_template() -> dict[str, dict[str, int]]:
    return {
        feature: {"rows": 0, "control_populated": 0, "repair_populated": 0}
        for feature in FEATURES
    }


def _finalize_feature_counts(counts: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    output = {}
    for feature, row in counts.items():
        total = int(row["rows"])
        output[feature] = {
            **row,
            "control_rate": row["control_populated"] / total if total else None,
            "repair_rate": row["repair_populated"] / total if total else None,
            "rate_delta": (
                (row["repair_populated"] - row["control_populated"]) / total
                if total else None
            ),
        }
    return output


def _folder_identity(path: Path) -> tuple[str, date, dict[str, Any]] | None:
    first = _read_first_jsonl(path / "replay_inputs.jsonl")
    if not first:
        return None
    target = record_target_date(first)
    market_id = market_id_from_slug(str(first.get("event_slug") or ""))
    if target is None or not market_id:
        return None
    return market_id, target, first


def run_replay(
    *,
    snapshots_root: Path,
    settlements_root: Path,
    repo_root: Path,
    start_date: date,
    end_date: date,
    replicates: int,
    seed: int,
    regime_filter: str | None = None,
) -> dict[str, Any]:
    labels, raw_ledger_rows = _current_settlement_index(settlements_root)
    feature_counts = {
        spec.id: _feature_counts_template()
        for spec in all_specs()
    }
    models: dict[str, TorontoHighTempModel] = {}
    metric_rows: list[dict[str, Any]] = []
    selected_hours: set[tuple[str, str, str, int]] = set()
    selected_keys: list[dict[str, Any]] = []
    positive_control_l1: list[float] = []
    completeness_rows = 0
    skipped_unlabelled_days: set[tuple[str, str]] = set()
    regime_commits: dict[str, set[str]] = defaultdict(set)
    commit_regimes: dict[str, str] = {}

    for folder in sorted(snapshots_root.glob("*/replay_inputs.jsonl")):
        identity = _folder_identity(folder.parent)
        if identity is None:
            continue
        market_id, target, _first = identity
        if target < start_date or target > end_date:
            continue
        label = labels.get((market_id, target.isoformat()))
        countable = bool(label and label.get("promotion_countable") is True)
        settlement_bucket = (label or {}).get("settlement_bucket")
        if not countable or settlement_bucket is None:
            skipped_unlabelled_days.add((market_id, target.isoformat()))
        model = models.setdefault(
            market_id,
            TorontoHighTempModel(target_date=target, market_id=market_id),
        )

        for record in load_replay_records(folder.parent):
            if is_reconstructed(record) or not record.get("sources"):
                continue
            runtime_commit = str(
                ((record.get("runtime_identity") or {}).get("git_commit") or "")
            ).strip()
            regime = commit_regimes.get(runtime_commit)
            if regime is None:
                regime = provenance_regime(record, repo_root=repo_root)
                commit_regimes[runtime_commit] = regime
            if regime_filter is not None and regime != regime_filter:
                continue
            built_at = parse_built_at(record)
            if built_at is None:
                continue
            model.set_target_date(target)
            history = model.source_data(record["sources"], "wu_history")
            cutoff_hour = model.effective_intraday_cutoff_hour(
                built_at,
                history.get("rows") or [],
            )
            if cutoff_hour < 7 or cutoff_hour > 20:
                continue
            control = control_sources(record["sources"])
            control_features = model.extract_live_features(control, cutoff_hour, now=built_at)
            repair_features = model.extract_live_features(record["sources"], cutoff_hour, now=built_at)
            if not isinstance(control_features, Mapping) or not isinstance(repair_features, Mapping):
                continue
            completeness_rows += 1
            for feature in FEATURES:
                counts = feature_counts[market_id][feature]
                counts["rows"] += 1
                counts["control_populated"] += control_features.get(feature) is not None
                counts["repair_populated"] += repair_features.get(feature) is not None

            hour_key = (regime, market_id, target.isoformat(), cutoff_hour)
            if hour_key in selected_hours or not countable or settlement_bucket is None:
                continue
            selected_hours.add(hour_key)
            control_distribution = model.estimate_distribution(control, now=built_at)
            repair_distribution = model.estimate_distribution(record["sources"], now=built_at)
            recorded_distribution = record.get("recorded_distribution") or {}
            positive_control_l1.append(
                distribution_l1(recorded_distribution, control_distribution)
            )
            control_center, control_width = _center_width(control_distribution)
            repair_center, repair_width = _center_width(repair_distribution)
            scale = 1.0 if model.spec.display_unit == "C" else 1.0 / 1.8
            row = {
                "regime": regime,
                "market_id": market_id,
                "target_date": target.isoformat(),
                "cutoff_hour": cutoff_hour,
                "snapshot_id": record.get("snapshot_id"),
                "center_delta_c_equivalent": (repair_center - control_center) * scale,
                "width_delta_c_equivalent": (repair_width - control_width) * scale,
                "brier_delta": (
                    _brier(repair_distribution, int(settlement_bucket))
                    - _brier(control_distribution, int(settlement_bucket))
                ),
                "distribution_l1": distribution_l1(control_distribution, repair_distribution),
            }
            metric_rows.append(row)
            regime_commits[regime].add(runtime_commit)
            selected_keys.append({
                "market_id": market_id,
                "target_date": target.isoformat(),
                "cutoff_hour": cutoff_hour,
                "snapshot_id": record.get("snapshot_id"),
                "captured_input_hash": record.get("captured_input_hash"),
                "regime": regime,
            })

    if not metric_rows:
        raise BlindFeatureRepairError("no promotion-countable captured replay rows were selected")
    max_control_l1 = max(positive_control_l1) if positive_control_l1 else None
    positive_control_pass = (
        max_control_l1 is not None and max_control_l1 <= POSITIVE_CONTROL_TOLERANCE
    )
    by_regime = {}
    for regime in REGIMES:
        regime_rows = [row for row in metric_rows if row["regime"] == regime]
        by_regime[regime] = {
            "snapshot_rows": len(regime_rows),
            "changed_distribution_rows": sum(row["distribution_l1"] > 0 for row in regime_rows),
            "mean_distribution_l1": _mean(row["distribution_l1"] for row in regime_rows),
            "max_distribution_l1": max((row["distribution_l1"] for row in regime_rows), default=None),
            "runtime_commits": sorted(regime_commits[regime]),
            "metrics": {
                metric: crossed_summary(
                    regime_rows,
                    metric,
                    replicates=replicates,
                    seed=seed + index,
                )
                for index, metric in enumerate((
                    "center_delta_c_equivalent",
                    "width_delta_c_equivalent",
                    "brier_delta",
                ))
            } if regime_rows else {},
        }

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": "blind_feature_repair_replay",
        "status": "PASS" if positive_control_pass else "BLOCK",
        "verdict": (
            "paired_replay_valid"
            if positive_control_pass
            else "positive_control_failed_measurement_invalid"
        ),
        "method": {
            "mode": "read_only_no_network_no_fit_no_candidate_no_release_action",
            "feature_completeness_population": "all captured replay rows with effective cutoff 07:00-20:00",
            "served_output_population": "first captured row per market/date/effective-cutoff with current promotion_countable ledger label",
            "daily_first": True,
            "uncertainty": "independent date-cluster and market-cluster resampling crossed by product weights",
            "bootstrap_replicates": replicates,
            "bootstrap_seed": seed,
            "provenance_anchor": PROVENANCE_ANCHOR,
            "provenance_regime_filter": regime_filter,
            "regime_classification": (
                "captured runtime commit contains the rollout anchor or it does not; "
                "never target-date age"
            ),
        },
        "inputs": {
            "snapshots_root": str(snapshots_root),
            "settlements_root": str(settlements_root),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "raw_ledger_rows": raw_ledger_rows,
            "deduplicated_market_date_labels": len(labels),
            "selected_replay_key_sha256": _canonical_sha256(selected_keys),
        },
        "support": {
            "feature_completeness_rows": completeness_rows,
            "served_output_rows": len(metric_rows),
            "promotion_countable_market_days": len({
                (row["market_id"], row["target_date"]) for row in metric_rows
            }),
            "skipped_unlabelled_market_days": len(skipped_unlabelled_days),
        },
        "positive_control": {
            "status": "PASS" if positive_control_pass else "BLOCK",
            "tolerance": POSITIVE_CONTROL_TOLERANCE,
            "rows": len(positive_control_l1),
            "exact_rows": sum(value == 0.0 for value in positive_control_l1),
            "mean_recorded_distribution_l1": _mean(positive_control_l1),
            "max_recorded_distribution_l1": max_control_l1,
        },
        "feature_completeness_by_market": {
            market: _finalize_feature_counts(counts)
            for market, counts in sorted(feature_counts.items())
        },
        "served_output_by_provenance_regime": by_regime,
    }
    return finalize_self_hash(report, hash_field=REPORT_HASH_FIELD)


def render_markdown(report: Mapping[str, Any]) -> str:
    support = report["support"]
    lines = [
        "# Blind local-meteorology repair replay",
        "",
        f"**{report['status']} — {report['verdict']}.**",
        "",
        (
            f"Completeness uses {support['feature_completeness_rows']:,} captured rows; paired served-output "
            f"replay uses {support['served_output_rows']:,} hourly rows across "
            f"{support['promotion_countable_market_days']} promotion-countable market-days."
        ),
        "",
        "## Positive control",
        "",
        "| Rows | Exact | Mean L1 | Max L1 | Verdict |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    control = report["positive_control"]
    lines.append(
        f"| {control['rows']} | {control['exact_rows']} | {control['mean_recorded_distribution_l1']} | "
        f"{control['max_recorded_distribution_l1']} | **{control['status']}** |"
    )
    lines.extend(["", "## Feature completeness", ""])
    for market, features in report["feature_completeness_by_market"].items():
        lines.extend([
            f"### {market}",
            "",
            "| Feature | Rows | Control | Repair | Delta |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for feature in FEATURES:
            row = features[feature]
            lines.append(
                f"| `{feature}` | {row['rows']} | {row['control_rate']:.2%} | "
                f"{row['repair_rate']:.2%} | {row['rate_delta']:+.2%} |"
            )
        lines.append("")
    lines.extend(["## Served-output delta", ""])
    for regime, payload in report["served_output_by_provenance_regime"].items():
        lines.extend([
            f"### {regime}",
            "",
            (
                f"{payload['snapshot_rows']} replay rows; {payload['changed_distribution_rows']} changed; "
                f"mean/max L1 {payload['mean_distribution_l1']} / {payload['max_distribution_l1']}."
            ),
            "",
            "| Metric | Daily-first point | Crossed 95% | Power | 80%-power MDE | D | M | MD |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for metric, row in payload.get("metrics", {}).items():
            lines.append(
                f"| `{metric}` | {row['daily_first_point']} | {row['crossed_95_interval']} | "
                f"{row['observed_effect_plugin_power']} | {row['two_sided_80pct_power_mde']} | "
                f"{row['date_clusters']} | {row['market_clusters']} | {row['market_days']} |"
            )
        lines.append("")
    lines.append(f"Report SHA-256: `{report[REPORT_HASH_FIELD]}`.")
    lines.append("")
    return "\n".join(lines)


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", default=str(data_path() / "snapshots"))
    parser.add_argument("--settlements-root", default=str(data_path() / "settlements"))
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start-date", type=_parse_date, default=date(2026, 7, 22))
    parser.add_argument("--end-date", type=_parse_date, default=date(2026, 8, 7))
    parser.add_argument("--bootstrap-replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--bootstrap-seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--provenance-regime", choices=REGIMES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root).resolve()
    protected = data_path().resolve()
    if output_root == protected or protected in output_root.parents:
        raise BlindFeatureRepairError("output root must be outside data")
    if args.bootstrap_replicates <= 0:
        raise BlindFeatureRepairError("bootstrap replicates must be positive")
    report = run_replay(
        snapshots_root=Path(args.snapshots_root).resolve(),
        settlements_root=Path(args.settlements_root).resolve(),
        repo_root=Path.cwd().resolve(),
        start_date=args.start_date,
        end_date=args.end_date,
        replicates=args.bootstrap_replicates,
        seed=args.bootstrap_seed,
        regime_filter=args.provenance_regime,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "blind-feature-repair-replay.json"
    markdown_path = output_root / "blind-feature-repair-replay.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "verdict": report["verdict"],
        "json": str(json_path),
        "markdown": str(markdown_path),
        REPORT_HASH_FIELD: report[REPORT_HASH_FIELD],
    }, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BlindFeatureRepairError",
    "FEATURES",
    "REPORT_SCHEMA_VERSION",
    "control_sources",
    "crossed_summary",
    "provenance_regime",
    "render_markdown",
    "run_replay",
]
