"""Shadow replay for the pooled F-family feature-model candidate.

This is the cutover guard for Roadmap item 33. It replays the pinned promotion
corpus with the current serving model, then scores the separate pooled-F
artifact against the same settled rows as a shadow candidate. Live serving is
not changed by this module.
"""
import argparse
import json
import math
import pickle
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (
    expected_calibration_error,
    fmt_num,
    fmt_pct,
    fmt_signed,
    group_sort_key,
    markdown_table,
    score_rows,
)
from feature_store import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION
from location_trust import score_all_markets
from market_registry import REGISTRY
from pooled_feature_model import (
    DEFAULT_BAND_ARTIFACT,
    add_city_features,
    band_prediction_record,
    market_climate_stats,
    market_source_reliability,
    predict_band_rows_for_bundle,
    predict_rows,
)
from promotion_corpus import DEFAULT_OUT as DEFAULT_CORPUS, entry_for_folder, folders_from_manifest, load_manifest
from replay import index_records_by_snapshot, is_reconstructed, load_replay_records, parse_built_at, record_target_date
from replay_backtest import FIDELITY_FAITHFUL_L1, run_replay_backtest
from settled_days import DEFAULT_SNAPSHOTS_ROOT, folder_market_id
from toronto_model import TorontoHighTempModel

DEFAULT_OUT = Path("data") / "backtest" / "pooled_candidate_replay_report.md"
DEFAULT_JSON_OUT = Path("data") / "backtest" / "pooled_candidate_replay.json"
DEFAULT_REPLAY_REPORT = Path("data") / "backtest" / "pooled_candidate_current_replay_report.md"


def load_artifact(path):
    path = Path(path)
    with path.open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, dict) or not artifact.get("models"):
        raise ValueError(f"{path} is not a pooled feature artifact")
    return artifact


def _valid_probability(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value)


def _clamp_probability(value):
    return max(0.0, min(1.0, float(value)))


def band_probability_from_distribution(distribution, kind, value, value_hi=None):
    """Map a native-unit bucket distribution to one Polymarket band."""
    if not distribution:
        return None
    try:
        lo = float(value)
        hi = float(value_hi) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None

    kind = str(kind or "eq").lower()
    total = 0.0
    for bucket, probability in distribution.items():
        try:
            bucket_value = float(bucket)
            probability = float(probability)
        except (TypeError, ValueError):
            continue
        if kind == "lte" and bucket_value <= lo:
            total += probability
        elif kind == "gte" and bucket_value >= lo:
            total += probability
        elif kind not in ("lte", "gte") and lo <= bucket_value <= hi:
            total += probability
    return _clamp_probability(total)


def probability_view(rows, probability_field):
    output = []
    for row in rows:
        probability = row.get(probability_field)
        if not _valid_probability(probability):
            continue
        copy = dict(row)
        copy["model_probability"] = _clamp_probability(probability)
        output.append(copy)
    return output


def candidate_comparison(rows):
    """Candidate vs current serving replay vs recorded tape vs market."""
    candidate_rows = probability_view(rows, "candidate_p")
    if not candidate_rows:
        return None
    current_rows = probability_view(candidate_rows, "replayed_p")
    recorded_rows = probability_view(candidate_rows, "recorded_p")
    candidate = score_rows(candidate_rows)
    current = score_rows(current_rows)
    recorded = score_rows(recorded_rows)
    if not candidate or not current or not recorded:
        return None
    ece = expected_calibration_error(candidate_rows, "model_probability")
    return {
        "n": candidate["n"],
        "candidate_brier": candidate["model_brier"],
        "current_brier": current["model_brier"],
        "recorded_brier": recorded["model_brier"],
        "market_brier": candidate["market_brier"],
        "candidate_logloss": candidate["model_logloss"],
        "current_logloss": current["model_logloss"],
        "recorded_logloss": recorded["model_logloss"],
        "market_logloss": candidate["market_logloss"],
        "candidate_skill": candidate["brier_skill_score"],
        "current_skill": current["brier_skill_score"],
        "recorded_skill": recorded["brier_skill_score"],
        "candidate_ece": ece,
        "delta_vs_current": candidate["model_brier"] - current["model_brier"],
        "delta_vs_recorded": candidate["model_brier"] - recorded["model_brier"],
        "delta_vs_market": candidate["model_brier"] - candidate["market_brier"],
        "base_rate": candidate["base_rate"],
    }


def grouped_candidate_comparison(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        comp = candidate_comparison(group_rows)
        if comp:
            output.append({"group": group, **comp})
    return output


def daily_first_candidate_comparison(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row.get("market_id"), row.get("target_date"))].append(row)
    comps = [candidate_comparison(group_rows) for group_rows in grouped.values()]
    comps = [comp for comp in comps if comp]
    if not comps:
        return None

    def avg(key):
        return sum(comp[key] for comp in comps) / len(comps)

    return {
        "n_days": len(comps),
        "n": sum(comp["n"] for comp in comps),
        "candidate_brier": avg("candidate_brier"),
        "current_brier": avg("current_brier"),
        "recorded_brier": avg("recorded_brier"),
        "market_brier": avg("market_brier"),
        "candidate_skill": avg("candidate_skill"),
        "current_skill": avg("current_skill"),
        "delta_vs_current": avg("candidate_brier") - avg("current_brier"),
        "delta_vs_market": avg("candidate_brier") - avg("market_brier"),
        "base_rate": avg("base_rate"),
    }


def _model_for_market(models, market_id):
    if market_id not in models:
        models[market_id] = TorontoHighTempModel(market_id=market_id)
    return models[market_id]


def _climate_for_market(climates, model, market_id):
    if market_id not in climates:
        climates[market_id] = market_climate_stats(model.historical_target_cache())
    return climates[market_id]


def _source_reliability_for_market(source_reliability, spec):
    if spec.id not in source_reliability:
        source_reliability[spec.id] = market_source_reliability(spec)
    return source_reliability[spec.id]


def _record_feature_row(model, spec, climate, record, source_reliability=None):
    now = parse_built_at(record)
    if now is None:
        raise ValueError("replay record is missing a parseable built_at/captured_at_local timestamp")
    target_date = record_target_date(record)
    if target_date is not None:
        model.set_target_date(target_date)
    sources = record.get("sources") or {}
    history = model.source_data(sources, "wu_history")
    cutoff_hour = model.effective_intraday_cutoff_hour(now, history.get("rows") or [])
    features = model.extract_live_features(sources, cutoff_hour, now=now)
    current = model.source_data(sources, "wu_current")
    metar = model.source_data(sources, "metar")
    support_values = [
        features.get("high_so_far"),
        current.get("temp_c"),
        metar.get("temp_c"),
    ]
    observed_support = model.max_value(*support_values)
    row = {column: features.get(column) for column in FEATURE_COLUMNS}
    row["cutoff_hour"] = int(cutoff_hour)
    row["target_date"] = target_date.isoformat() if target_date else record.get("target_date")
    row["observed_support_bucket"] = model.round_half_up(observed_support)
    add_city_features(row, spec, climate, source_reliability=source_reliability)
    return row


def build_candidate_features(manifest, snapshots_root, family_unit):
    """Return (market_id, snapshot_id) -> feature row for candidate scoring."""
    models = {}
    climates = {}
    source_reliability = {}
    diagnostics = {
        "family_unit": family_unit,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "candidate_snapshots": 0,
        "predicted_snapshots": 0,
        "excluded_non_family_snapshots": 0,
        "missing_replay_records": 0,
        "reconstructed_excluded": 0,
        "missing_hour_models": 0,
        "feature_errors": [],
        "hour_counts": {},
    }
    include_reconstructed = bool(manifest.get("include_reconstructed"))
    features = {}

    for folder in folders_from_manifest(manifest, snapshots_root):
        market_id = folder_market_id(folder)
        spec = REGISTRY.get(market_id)
        entry = entry_for_folder(manifest, folder)
        pinned_ids = [str(item) for item in (entry or {}).get("snapshot_ids") or []]
        if not spec:
            diagnostics["excluded_non_family_snapshots"] += len(pinned_ids)
            continue
        if spec.display_unit != family_unit:
            diagnostics["excluded_non_family_snapshots"] += len(pinned_ids)
            continue

        model = _model_for_market(models, market_id)
        climate = _climate_for_market(climates, model, market_id)
        reliability = _source_reliability_for_market(source_reliability, spec)
        records = index_records_by_snapshot(load_replay_records(folder))
        for snapshot_id in pinned_ids:
            record = records.get(snapshot_id)
            if not record:
                diagnostics["missing_replay_records"] += 1
                continue
            if is_reconstructed(record) and not include_reconstructed:
                diagnostics["reconstructed_excluded"] += 1
                continue
            diagnostics["candidate_snapshots"] += 1
            try:
                feature_row = _record_feature_row(model, spec, climate, record, source_reliability=reliability)
            except Exception as exc:  # noqa: BLE001 - diagnostics should survive bad rows
                if len(diagnostics["feature_errors"]) < 20:
                    diagnostics["feature_errors"].append({
                        "market_id": market_id,
                        "snapshot_id": snapshot_id,
                        "error": str(exc),
                })
                continue
            diagnostics["predicted_snapshots"] += 1
            diagnostics["hour_counts"][str(feature_row["cutoff_hour"])] = (
                diagnostics["hour_counts"].get(str(feature_row["cutoff_hour"]), 0) + 1
            )
            features[(market_id, snapshot_id)] = feature_row
    return features, diagnostics


def build_candidate_distributions(manifest, snapshots_root, artifact):
    """Return (market_id, snapshot_id) -> pooled candidate distribution."""
    family_unit = artifact.get("family_unit") or "F"
    models_by_hour = artifact.get("models") or {}
    support = artifact.get("support")
    feature_rows, diagnostics = build_candidate_features(manifest, snapshots_root, family_unit)
    by_hour = defaultdict(list)
    for (market_id, snapshot_id), feature_row in feature_rows.items():
        hour = str(feature_row["cutoff_hour"])
        if hour not in models_by_hour:
            diagnostics["missing_hour_models"] += 1
            continue
        by_hour[hour].append((market_id, snapshot_id, feature_row))

    predictions = {}
    for hour, items in sorted(by_hour.items(), key=lambda item: int(item[0])):
        bundle = models_by_hour[hour]
        rows = [item[2] for item in items]
        distributions = predict_rows(
            bundle["model"],
            bundle["imputer"],
            bundle["feature_names"],
            rows,
            support=support,
        )
        for (market_id, snapshot_id, feature_row), distribution in zip(items, distributions):
            predictions[(market_id, snapshot_id)] = {
                "distribution": distribution,
                "cutoff_hour": feature_row["cutoff_hour"],
            }
    diagnostics["predicted_snapshots"] = len(predictions)
    return predictions, diagnostics


def attach_candidate_probabilities(replay_results, predictions, family_unit):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not spec or spec.display_unit != family_unit:
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        candidate = predictions.get((market_id, str(row.get("snapshot_id"))))
        if candidate:
            copy["candidate_cutoff_hour"] = candidate.get("cutoff_hour")
            copy["candidate_p"] = band_probability_from_distribution(
                candidate.get("distribution"),
                row.get("bin_type"),
                row.get("bin_value_c"),
                row.get("bin_value_hi"),
            )
        else:
            copy["candidate_cutoff_hour"] = None
            copy["candidate_p"] = None
        if _valid_probability(copy.get("candidate_p")):
            coverage["candidate_rows"] += 1
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)
    return rows, coverage


def attach_band_candidate_probabilities(replay_results, feature_rows, artifact, family_unit):
    rows = []
    coverage = {
        "family_unit": family_unit,
        "total_replay_rows": len(replay_results.get("all_rows") or []),
        "family_rows": 0,
        "candidate_rows": 0,
        "excluded_non_family_rows": 0,
        "missing_candidate_rows": 0,
    }
    models_by_hour = artifact.get("models") or {}
    by_hour = defaultdict(list)
    for row in replay_results.get("all_rows") or []:
        market_id = row.get("market_id")
        spec = REGISTRY.get(market_id)
        if not spec or spec.display_unit != family_unit:
            coverage["excluded_non_family_rows"] += 1
            continue
        coverage["family_rows"] += 1
        copy = dict(row)
        copy["candidate_p"] = None
        copy["candidate_cutoff_hour"] = None
        feature_row = feature_rows.get((market_id, str(row.get("snapshot_id"))))
        if feature_row:
            band_row = band_prediction_record(
                feature_row,
                row.get("bin_type"),
                row.get("bin_value_c"),
                value_hi=row.get("bin_value_hi"),
            )
            hour = str(band_row.get("cutoff_hour"))
            copy["candidate_cutoff_hour"] = band_row.get("cutoff_hour")
            if hour in models_by_hour:
                by_hour[hour].append((len(rows), band_row))
            else:
                coverage["missing_candidate_rows"] += 1
        else:
            coverage["missing_candidate_rows"] += 1
        rows.append(copy)

    for hour, items in sorted(by_hour.items(), key=lambda item: int(item[0])):
        bundle = models_by_hour[hour]
        band_rows = [item[1] for item in items]
        probabilities = predict_band_rows_for_bundle(bundle, band_rows, postprocess=True)
        for (row_index, _), probability in zip(items, probabilities):
            rows[row_index]["candidate_p"] = probability

    postprocess = artifact.get("postprocess") or {}
    if postprocess.get("partition_normalization_enabled", True):
        normalize_partition_probabilities(
            rows,
            gamma=float(postprocess.get("partition_normalization_gamma", 1.25)),
        )
    if postprocess.get("current_blend_enabled", False):
        apply_current_blend_guardrail(rows, postprocess)

    candidate_rows = sum(1 for row in rows if _valid_probability(row.get("candidate_p")))
    coverage["candidate_rows"] = candidate_rows
    coverage["missing_candidate_rows"] = coverage["family_rows"] - candidate_rows
    return rows, coverage


def normalize_partition_probabilities(rows, gamma=1.25):
    """Normalize direct band probabilities across each snapshot's band partition."""
    gamma = max(0.1, float(gamma or 1.0))
    grouped = defaultdict(list)
    for idx, row in enumerate(rows):
        if _valid_probability(row.get("candidate_p")):
            grouped[(row.get("market_id"), row.get("snapshot_id"))].append(idx)
    for indexes in grouped.values():
        weights = [
            max(1e-12, float(rows[idx]["candidate_p"])) ** gamma
            for idx in indexes
        ]
        total = sum(weights)
        if total <= 0:
            continue
        for idx, weight in zip(indexes, weights):
            rows[idx]["candidate_p"] = weight / total
    return rows


def current_blend_alpha(row, config):
    market_alpha = config.get("current_blend_market_alpha") or {}
    market_id = row.get("market_id")
    if market_id in market_alpha:
        alpha = market_alpha[market_id]
    else:
        alpha = config.get("current_blend_default_alpha", 1.0)
    try:
        return max(0.0, min(1.0, float(alpha)))
    except (TypeError, ValueError):
        return 1.0


def apply_current_blend_guardrail(rows, config):
    """Blend pooled candidate probabilities with incumbent replay probabilities."""
    for row in rows:
        if not _valid_probability(row.get("candidate_p")):
            continue
        if not _valid_probability(row.get("replayed_p")):
            continue
        alpha = current_blend_alpha(row, config)
        if alpha >= 1.0:
            continue
        candidate = _clamp_probability(row["candidate_p"])
        incumbent = _clamp_probability(row["replayed_p"])
        row["candidate_p"] = (alpha * candidate) + ((1.0 - alpha) * incumbent)
    return rows


def market_verdict(comp, day_count, trust, current_tol, market_tol, min_days, min_trust):
    if not comp:
        return "BLOCK", ["no candidate rows scored"]
    reasons = []
    delta_current = comp.get("delta_vs_current")
    if delta_current is None or delta_current > current_tol:
        reasons.append(
            f"candidate regresses current by {delta_current:+.4f} > {current_tol:.4f}"
            if delta_current is not None else
            "missing candidate-vs-current delta"
        )
    if reasons:
        return "BLOCK", reasons

    shadow = []
    if delta_current is not None and delta_current >= 0:
        shadow.append("not proven better than current replay")
    if day_count < min_days:
        shadow.append(f"{day_count} settled day(s) < {min_days}")
    candidate_brier = comp.get("candidate_brier")
    market_brier = comp.get("market_brier")
    if candidate_brier is None or market_brier is None or candidate_brier > market_brier + market_tol:
        shadow.append("not proven better than market on pinned rows")
    trust_score = (trust or {}).get("trust_score")
    if trust_score is None or trust_score < min_trust:
        shadow.append(f"trust {trust_score if trust_score is not None else '-'} < {min_trust}")
    if shadow:
        return "SHADOW", shadow
    return "PASS", ["beats current replay and clears market/trust gates"]


def _per_market(rows, trust_by_market, args):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("market_id")].append(row)
    output = []
    for market_id in sorted(grouped):
        market_rows = grouped[market_id]
        comp = candidate_comparison(market_rows)
        day_count = len({
            row.get("target_date")
            for row in market_rows
            if row.get("target_date") and _valid_probability(row.get("candidate_p"))
        })
        snapshot_count = len({
            row.get("snapshot_id")
            for row in market_rows
            if row.get("snapshot_id") and _valid_probability(row.get("candidate_p"))
        })
        trust = trust_by_market.get(market_id) or {}
        verdict, reasons = market_verdict(
            comp,
            day_count,
            trust,
            args.current_tol,
            args.market_tol,
            args.min_days,
            args.min_trust,
        )
        spec = REGISTRY.get(market_id)
        output.append({
            "market_id": market_id,
            "city": spec.city_label if spec else market_id,
            "days": day_count,
            "snapshots": snapshot_count,
            "rows": (comp or {}).get("n", 0),
            "comparison": comp,
            "trust": trust,
            "verdict": verdict,
            "reason": "; ".join(reasons),
        })
    return output


def overall_verdict(market_rows, require_all_markets=False):
    blockers = [row for row in market_rows if row["verdict"] == "BLOCK"]
    passes = [row for row in market_rows if row["verdict"] == "PASS"]
    shadows = [row for row in market_rows if row["verdict"] == "SHADOW"]
    if require_all_markets and (blockers or shadows):
        return "BLOCK"
    if blockers and passes:
        return "PARTIAL_PASS"
    if blockers:
        return "BLOCK"
    if shadows and passes:
        return "PASS_WITH_SHADOWS"
    if shadows:
        return "SHADOW_ONLY"
    if passes:
        return "PASS"
    return "BLOCK"


def cutover_decision(verdict):
    if verdict == "PASS":
        return "CUTOVER_READY"
    if verdict in {"PARTIAL_PASS", "PASS_WITH_SHADOWS"}:
        return "PER_MARKET_ONLY"
    return "DO_NOT_CUT_OVER"


def replay_gate_status(replay_results, max_fidelity_l1=FIDELITY_FAITHFUL_L1, require_exact_identity=False):
    """Global replay safety gate for a candidate promotion run."""
    warnings = replay_results.get("corpus_warnings") or []
    fidelity = replay_results.get("fidelity") or {}
    same_n = fidelity.get("same_identity_n") or 0
    max_l1 = fidelity.get("same_identity_max_l1")

    corpus_ok = not warnings
    if corpus_ok:
        corpus_message = "PASS: all pinned tape/replay hashes matched"
    else:
        corpus_message = f"FAIL: {len(warnings)} corpus pin warning(s)"

    if same_n:
        fidelity_ok = max_l1 is not None and max_l1 <= max_fidelity_l1
        verdict = "PASS" if fidelity_ok else "FAIL"
        fidelity_message = (
            f"{verdict}: {same_n} exact-identity snapshot(s), "
            f"max L1 {max_l1:.5f} vs limit {max_fidelity_l1:.5f}"
        )
    elif require_exact_identity:
        fidelity_ok = False
        fidelity_message = "FAIL: no exact-identity snapshots in corpus"
    else:
        fidelity_ok = True
        fidelity_message = "WARN: no exact-identity snapshots yet; strict canary not required"

    return {
        "global_ok": bool(corpus_ok and fidelity_ok),
        "corpus_ok": bool(corpus_ok),
        "corpus_message": corpus_message,
        "corpus_warning_count": len(warnings),
        "fidelity_ok": bool(fidelity_ok),
        "fidelity_message": fidelity_message,
        "same_identity_n": same_n,
        "same_identity_max_l1": max_l1,
        "max_fidelity_l1": max_fidelity_l1,
        "require_exact_identity": bool(require_exact_identity),
    }


def _manifest_summary(manifest):
    summary = manifest.get("summary") or {}
    return {
        "path": manifest.get("_path"),
        "schema_version": manifest.get("schema_version"),
        "corpus_hash": manifest.get("corpus_hash"),
        "as_of": manifest.get("as_of"),
        "market_day_count": summary.get("market_day_count"),
        "snapshot_count": summary.get("snapshot_count"),
        "band_row_count": summary.get("band_row_count"),
        "quality_grades": manifest.get("quality_grades"),
    }


def run_pooled_candidate_replay(args):
    manifest = load_manifest(args.corpus)
    artifact = load_artifact(args.artifact)
    family_unit = artifact.get("family_unit") or "F"
    folders = [str(folder) for folder in folders_from_manifest(manifest, args.snapshots_root)]
    replay_results = run_replay_backtest(
        folders,
        daily_summary_path=None,
        overrides={},
        out_path=args.replay_report,
        include_reconstructed=manifest.get("include_reconstructed", False),
        write=bool(args.replay_report),
        corpus_manifest=manifest,
    )
    replay_gate = replay_gate_status(
        replay_results,
        max_fidelity_l1=getattr(args, "max_fidelity_l1", FIDELITY_FAITHFUL_L1),
        require_exact_identity=getattr(args, "require_exact_identity", False),
    )
    if artifact.get("prediction_mode") == "band_binary":
        feature_rows, diagnostics = build_candidate_features(manifest, args.snapshots_root, family_unit)
        candidate_rows, coverage = attach_band_candidate_probabilities(
            replay_results,
            feature_rows,
            artifact,
            family_unit,
        )
    else:
        predictions, diagnostics = build_candidate_distributions(manifest, args.snapshots_root, artifact)
        candidate_rows, coverage = attach_candidate_probabilities(replay_results, predictions, family_unit)

    trust_rows = score_all_markets(
        root=args.snapshots_root,
        as_of=manifest.get("as_of"),
    )
    trust_by_market = {row["market"]: row for row in trust_rows}
    market_rows = _per_market(candidate_rows, trust_by_market, args)
    aggregate = candidate_comparison(candidate_rows)
    daily_first = daily_first_candidate_comparison(candidate_rows)
    by_market = grouped_candidate_comparison(candidate_rows, "market_id")
    by_hour = grouped_candidate_comparison(candidate_rows, "candidate_cutoff_hour")
    by_bin_type = grouped_candidate_comparison(candidate_rows, "bin_type")
    by_settlement_distance = grouped_candidate_comparison(candidate_rows, "settlement_distance_bucket")
    market_verdict = overall_verdict(market_rows, require_all_markets=args.require_all_markets)
    verdict = market_verdict if replay_gate["global_ok"] else "BLOCK"
    postprocess = artifact.get("postprocess") or {}
    adjacent_calibration = postprocess.get("adjacent_calibration") or {}

    report = {
        "generated_at": datetime.now().isoformat(),
        "verdict": verdict,
        "candidate_market_verdict": market_verdict,
        "cutover_decision": cutover_decision(verdict),
        "artifact": {
            "path": str(args.artifact),
            "schema_version": artifact.get("schema_version"),
            "feature_schema_version": artifact.get("feature_schema_version"),
            "family_unit": family_unit,
            "prediction_mode": artifact.get("prediction_mode") or "bucket_distribution",
            "objective": artifact.get("objective"),
            "trained_at": artifact.get("trained_at"),
            "support_min": min(artifact.get("support") or []) if artifact.get("support") else None,
            "support_max": max(artifact.get("support") or []) if artifact.get("support") else None,
            "hour_models": sorted(int(hour) for hour in (artifact.get("models") or {})),
            "adjacent_calibration_contexts": adjacent_calibration.get("context_count"),
            "current_blend_default_alpha": postprocess.get("current_blend_default_alpha"),
            "current_blend_market_alpha": postprocess.get("current_blend_market_alpha") or {},
        },
        "corpus": _manifest_summary(manifest),
        "coverage": coverage,
        "diagnostics": diagnostics,
        "replay_gate": replay_gate,
        "aggregate": aggregate,
        "daily_first": daily_first,
        "market_rows": market_rows,
        "by_market": by_market,
        "by_hour": by_hour,
        "by_bin_type": by_bin_type,
        "by_settlement_distance": by_settlement_distance,
        "replay_summary": {
            "snaps_scored": replay_results.get("snaps_scored"),
            "total_rows": replay_results.get("total_rows"),
            "fidelity": replay_results.get("fidelity") or {},
            "corpus_warnings": replay_results.get("corpus_warnings") or [],
        },
    }
    write_report(report, args.out)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _fmt_delta(value):
    return fmt_signed(value, 4)


def _candidate_table_rows(items):
    rows = []
    for item in items:
        comp = item.get("comparison") if "comparison" in item else item
        trust = item.get("trust") or {}
        rows.append([
            item.get("market_id", item.get("group")),
            item.get("days", "-"),
            item.get("snapshots", "-"),
            comp.get("n", 0) if comp else 0,
            fmt_num((comp or {}).get("candidate_brier")),
            fmt_num((comp or {}).get("current_brier")),
            fmt_num((comp or {}).get("market_brier")),
            _fmt_delta((comp or {}).get("delta_vs_current")),
            _fmt_delta((comp or {}).get("delta_vs_market")),
            fmt_signed((comp or {}).get("candidate_skill"), 3),
            f"{trust.get('trust_score', '-')}/100 {trust.get('grade', '')}".strip() if trust else "-",
            item.get("verdict", "-"),
            item.get("reason", "-"),
        ])
    return rows


def _group_table_rows(items):
    return [
        [
            str(item.get("group")) if item.get("group") not in (None, "") else "-",
            item.get("n", 0),
            fmt_num(item.get("candidate_brier")),
            fmt_num(item.get("current_brier")),
            fmt_num(item.get("market_brier")),
            _fmt_delta(item.get("delta_vs_current")),
            _fmt_delta(item.get("delta_vs_market")),
            fmt_signed(item.get("candidate_skill"), 3),
            fmt_pct(item.get("base_rate")),
        ]
        for item in items
    ]


def _market_list(rows, verdict):
    return ", ".join(row["market_id"] for row in rows if row["verdict"] == verdict) or "-"


def _comparison_summary_rows(report):
    rows = []
    for label, comp in [
        ("All F-family rows", report.get("aggregate")),
        ("Daily-first equal-day average", report.get("daily_first")),
    ]:
        if not comp:
            continue
        rows.append([
            label,
            comp.get("n_days", "-"),
            comp.get("n", 0),
            fmt_num(comp.get("candidate_brier")),
            fmt_num(comp.get("current_brier")),
            fmt_num(comp.get("recorded_brier")),
            fmt_num(comp.get("market_brier")),
            _fmt_delta(comp.get("delta_vs_current")),
            _fmt_delta(comp.get("delta_vs_market")),
            fmt_signed(comp.get("candidate_skill"), 3),
            fmt_pct(comp.get("base_rate")),
        ])
    return rows


def _slice_markdown(title, items):
    lines = ["", f"### {title}", ""]
    lines += markdown_table(
        ["Group", "Rows", "Candidate Brier", "Current Brier", "Market Brier",
         "Delta vs Current", "Delta vs Market", "Candidate Skill", "Base Rate"],
        _group_table_rows(items),
    )
    return lines


def write_report(report, out_path):
    artifact = report.get("artifact") or {}
    corpus = report.get("corpus") or {}
    coverage = report.get("coverage") or {}
    diagnostics = report.get("diagnostics") or {}
    lines = [
        "# Pooled F-Family Candidate Replay",
        "",
        f"Generated: {report['generated_at']}",
        f"Validation verdict: **{report['verdict']}**",
        f"Market-only verdict: **{report.get('candidate_market_verdict')}**",
        f"Cutover decision: **{report['cutover_decision']}**",
        "",
        "> Candidate features are rebuilt from pinned `replay_inputs.jsonl` with",
        "> the current extractor. Archived `features_long.csv` vectors are not used",
        "> for candidate scoring, because older F-market tapes can carry stale",
        "> feature schema/unit names.",
        "",
        "## Artifact",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Path", artifact.get("path") or "-"],
            ["Schema", artifact.get("schema_version") or "-"],
            ["Feature schema", artifact.get("feature_schema_version") or "-"],
            ["Family unit", artifact.get("family_unit") or "-"],
            ["Prediction mode", artifact.get("prediction_mode") or "-"],
            ["Objective", artifact.get("objective") or "-"],
            ["Trained at", artifact.get("trained_at") or "-"],
            ["Support", f"{artifact.get('support_min')}-{artifact.get('support_max')}"],
            ["Hour models", ", ".join(str(hour) for hour in artifact.get("hour_models") or []) or "-"],
            ["Adjacent calibration contexts", artifact.get("adjacent_calibration_contexts") or 0],
            ["Current blend default alpha", fmt_num(artifact.get("current_blend_default_alpha"))],
            [
                "Current blend market alpha",
                json.dumps(artifact.get("current_blend_market_alpha") or {}, sort_keys=True),
            ],
        ],
    )
    lines += ["", "## Corpus And Coverage", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Corpus hash", corpus.get("corpus_hash") or "-"],
            ["As of", corpus.get("as_of") or "-"],
            ["Market days", corpus.get("market_day_count") or 0],
            ["Pinned snapshots", corpus.get("snapshot_count") or 0],
            ["Pinned band rows", corpus.get("band_row_count") or 0],
            ["Replay rows", coverage.get("total_replay_rows", 0)],
            ["F-family rows", coverage.get("family_rows", 0)],
            ["Candidate-scored rows", coverage.get("candidate_rows", 0)],
            ["Excluded non-F rows", coverage.get("excluded_non_family_rows", 0)],
            ["Missing candidate rows", coverage.get("missing_candidate_rows", 0)],
            ["Candidate snapshots", diagnostics.get("candidate_snapshots", 0)],
            ["Predicted snapshots", diagnostics.get("predicted_snapshots", 0)],
        ],
    )
    gate = report.get("replay_gate") or {}
    lines += ["", "## Global Replay Gate", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [
            ["Corpus pin", "PASS" if gate.get("corpus_ok") else "FAIL", gate.get("corpus_message") or "-"],
            ["Replay fidelity", "PASS" if gate.get("fidelity_ok") else "FAIL", gate.get("fidelity_message") or "-"],
        ],
    )
    lines += ["", "## Aggregate Replay", ""]
    lines += markdown_table(
        ["Scope", "Days", "Rows", "Candidate Brier", "Current Brier",
         "Recorded Brier", "Market Brier", "Delta vs Current",
         "Delta vs Market", "Candidate Skill", "Base Rate"],
        _comparison_summary_rows(report),
    )
    lines += [
        "",
        "## Per-Market Action",
        "",
    ]
    lines += markdown_table(
        ["Action", "Markets"],
        [
            ["Candidate cutover ready", _market_list(report["market_rows"], "PASS")],
            ["Continue shadow", _market_list(report["market_rows"], "SHADOW")],
            ["Blocked", _market_list(report["market_rows"], "BLOCK")],
        ],
    )
    lines += ["", "### Market Details", ""]
    lines += markdown_table(
        ["Market", "Days", "Snaps", "Rows", "Candidate Brier", "Current Brier",
         "Market Brier", "Delta vs Current", "Delta vs Market", "Candidate Skill",
         "Trust", "Verdict", "Reason"],
        _candidate_table_rows(report["market_rows"]),
    )
    lines += ["", "## Slices", ""]
    lines += _slice_markdown("By Market", report.get("by_market") or [])
    lines += _slice_markdown("By Candidate Cutoff Hour", report.get("by_hour") or [])
    lines += _slice_markdown("By Band Type", report.get("by_bin_type") or [])
    lines += _slice_markdown("By Settlement Distance", report.get("by_settlement_distance") or [])

    warnings = (report.get("replay_summary") or {}).get("corpus_warnings") or []
    if warnings:
        lines += ["", "## Corpus Warnings", ""]
        lines += [f"- {warning}" for warning in warnings[:50]]
        if len(warnings) > 50:
            lines.append(f"- ... {len(warnings) - 50} more")

    errors = diagnostics.get("feature_errors") or []
    if errors:
        lines += ["", "## Feature Rebuild Errors", ""]
        lines += [
            f"- {item.get('market_id')} {item.get('snapshot_id')}: {item.get('error')}"
            for item in errors
        ]

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Replay-score the pooled F-family candidate as a shadow model.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--replay-report", default=str(DEFAULT_REPLAY_REPORT),
                        help="Current-serving replay report path. Empty string disables it.")
    parser.add_argument("--current-tol", type=float, default=0.003,
                        help="Hard-block tolerance for candidate Brier regression vs current replay.")
    parser.add_argument("--market-tol", type=float, default=0.003,
                        help="Shadow threshold for candidate Brier gap versus Polymarket.")
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--max-fidelity-l1", type=float, default=FIDELITY_FAITHFUL_L1)
    parser.add_argument("--require-exact-identity", action="store_true",
                        help="Fail the candidate promotion gate if the corpus has no exact replay-identity canary rows.")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true",
                        help="Exit nonzero when the candidate is blocked.")
    args = parser.parse_args()
    if args.replay_report == "":
        args.replay_report = None
    if args.json_out == "":
        args.json_out = None

    report = run_pooled_candidate_replay(args)
    print(f"Pooled candidate replay: {report['verdict']} ({report['cutover_decision']})")
    print(f"Report written to {args.out}")
    if args.json_out:
        print(f"JSON written to {args.json_out}")
    if args.replay_report:
        print(f"Current replay report written to {args.replay_report}")
    if args.fail_on_block and report["verdict"] == "BLOCK":
        sys.exit(1)


if __name__ == "__main__":
    main()
