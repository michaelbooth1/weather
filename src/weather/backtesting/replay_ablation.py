"""Per-source ablation replays: measure each live source's marginal value.

For every captured snapshot in the replay corpus, re-run the current model on
(a) the sources exactly as captured (the baseline control) and (b) the same
sources with one live source terminally removed after captured collector
fallback/cache resolution. Both are scored
against realized settlement on the recorded market bands.

The matched-row Brier delta (ablated minus baseline) is the source's measured
END-TO-END value: positive means removing the source hurts (it was helping),
negative means the model scores better without it. Because ablation goes
through the full engine -- feature extraction, forecast fallbacks, live
signals, floors, pull, lock-in -- this measures what the source is worth to
the system, not to one component slot.

``all_forecasts`` knocks out Open-Meteo + disabled paid-provider + ECCC citypage together:
single-source forecast ablations are cushioned by fallback to the remaining
forecasts, so the combined variant is the honest value of the forecast layer.

CLI:
  python -m weather.backtesting.replay_ablation [folder ...]
      [--snapshots-root data/snapshots] [--market MARKET]
      [--sources open_meteo,weather_forecast,...] [--include-reconstructed]
      [--out data/backtest/replay_ablation_report.md]
"""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from weather.execution_identity import (
    atomic_write_json_exclusive,
    atomic_write_text_exclusive,
)
from weather.paths import data_path, repo_path
from weather.io import write_json_atomic, write_text_atomic
from weather.schema_registry import schema_version

import pandas as pd

from weather.backtesting.settlement_io import (
    DEFAULT_SNAPSHOTS_ROOT,
    band_value_hi,
    load_daily_summary,
    resolve_outcome,
    settlement_for_tape,
)
from weather.scoring.metrics import safe_float
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY
from weather.backtesting.replay import (
    band_model_probability,
    canonical_replay_record_sha256,
    index_records_by_pinned_hash,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    replay_distribution,
)
from weather.backtesting.source_ablation_contract import (
    ALL_VARIANTS,
    GROUP_VARIANTS,
    SINGLE_SOURCE_VARIANTS,
    ablate_variant_sources,
    exact_requested_variants,
    members_for_variant,
    variant_has_support,
    variant_names_for_spec as contract_variant_names_for_spec,
)
from weather.backtesting.source_ablation_evidence import (
    audit_model_bindings,
    market_from_day,
    paired_day_inference,
    paired_inference_sensitivities,
    paired_market_inference,
    target_date_from_day,
    validate_operational_evidence_inputs,
)
from weather.backtesting.settled_days import folder_market_id
from weather.model.toronto_model import TorontoHighTempModel
from weather.release_serving import (
    STATUS_RESEARCH_UNBOUND,
    VerifiedServingBundle,
)
from weather.reporting.promotion.promotion_corpus import (
    entry_for_folder,
    folders_from_manifest_strict,
    load_manifest,
    load_manifest_bytes,
    verify_entry_inputs,
)

DEFAULT_OUT = data_path() / "backtest" / "replay_ablation_report.md"
DEFAULT_JSON_OUT = data_path() / "backtest" / "source_family_ablation.json"
DEFAULT_RESEARCH_OUT = (
    repo_path("scratch") / "research-output" / "source-family-ablation" / "replay_ablation_report.md"
)
DEFAULT_RESEARCH_JSON_OUT = (
    repo_path("scratch")
    / "research-output"
    / "source-family-ablation"
    / "source_family_ablation_research.json"
)
SINGLE_SOURCES = SINGLE_SOURCE_VARIANTS
COMBINED_VARIANTS = dict(GROUP_VARIANTS)
EVIDENCE_MODE_RESEARCH = "research"
EVIDENCE_MODE_OPERATIONAL = "operational"
EVIDENCE_MODES = {EVIDENCE_MODE_RESEARCH, EVIDENCE_MODE_OPERATIONAL}


def _stable_file_identity(stat_result):
    return (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
        int(getattr(stat_result, "st_ctime_ns", 0)),
    )


def _stable_json_bytes(path, *, max_bytes=64 * 1024 * 1024):
    resolved = Path(path).expanduser().resolve(strict=True)
    before = resolved.stat()
    if not resolved.is_file() or before.st_size > int(max_bytes):
        raise ValueError(f"sealed JSON input is missing, non-file, or too large: {resolved}")
    raw = resolved.read_bytes()
    after = resolved.stat()
    if _stable_file_identity(before) != _stable_file_identity(after) or len(
        raw
    ) != after.st_size:
        raise ValueError(f"sealed JSON input changed while reading: {resolved}")
    return resolved, raw, hashlib.sha256(raw).hexdigest(), len(raw)


def _strict_json_object_from_bytes(raw, *, path):
    """Decode one JSON object without duplicate or non-finite values."""

    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"sealed JSON input is not valid UTF-8: {path}") from exc

    def reject_duplicate_keys(pairs):
        output = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"sealed JSON input contains duplicate key {key!r}: {path}")
            output[key] = value
        return output

    def reject_non_finite(value):
        raise ValueError(
            f"sealed JSON input contains non-finite constant {value!r}: {path}"
        )

    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"sealed JSON input is not valid JSON: {path}") from exc

    def require_finite(value, location="$"):
        if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(
                    f"sealed JSON input contains non-finite number at {location}: {path}"
                )
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                require_finite(item, f"{location}[{index}]")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                require_finite(item, f"{location}.{key}")

    if not isinstance(payload, dict):
        raise ValueError(f"sealed JSON input root must be an object: {path}")
    require_finite(payload)
    return payload


def _load_manifest_with_receipt(path):
    """Load and validate one stable promotion-corpus byte sequence."""

    resolved, raw, file_sha256, size_bytes = _stable_json_bytes(path)
    manifest = load_manifest_bytes(raw, path=resolved)
    return manifest, {
        "path": str(resolved),
        "status": "PASS",
        "sha256": file_sha256,
        "size_bytes": size_bytes,
        "blockers": [],
    }


def ablate_sources(sources, names):
    """The captured sources with ``names`` knocked out exactly as a failed
    fetch presents them. Shallow copy: estimate_distribution does not mutate
    source payloads, and untouched entries are shared, not copied."""
    out = dict(sources)
    for name in names:
        if name in out:
            out[name] = {"ok": False, "error": "ablated", "data": {}}
    return out


def variant_names_for_spec(spec, requested):
    return contract_variant_names_for_spec(spec, requested)


def clean_row_value(value):
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def clean_band_row(row):
    return {key: clean_row_value(value) for key, value in row.items()}


def _finite_probability(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and 0.0 <= parsed <= 1.0 else None


def _assert_probability_distribution(distribution, *, label):
    if not isinstance(distribution, dict) or not distribution:
        raise ValueError(f"{label} distribution is empty")
    values = []
    for value in distribution.values():
        parsed = _finite_probability(value)
        if parsed is None:
            raise ValueError(f"{label} distribution contains an invalid probability")
        values.append(parsed)
    if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"{label} distribution mass does not equal one")


def settlement_distance_bucket(band, settlement_bucket):
    bucket = safe_float(settlement_bucket)
    if bucket is None:
        return "unknown"
    value = safe_float(band.get("bin_value_c") or band.get("bin_value"))
    value_hi = band_value_hi(band.get("range_label"), band.get("bin_value_c") or band.get("bin_value"))
    kind = str(band.get("bin_kind") or "").lower()
    if kind == "eq" and value is not None:
        distance = abs(value - bucket)
    elif kind == "lte" and value is not None:
        distance = max(0.0, bucket - value)
    elif kind == "gte" and value is not None:
        distance = max(0.0, value - bucket)
    elif value is not None and value_hi is not None:
        if value <= bucket <= value_hi:
            distance = 0.0
        else:
            distance = min(abs(value - bucket), abs(value_hi - bucket))
    else:
        return "unknown"
    if distance < 0.5:
        return "exact"
    if distance <= 1.5:
        return "adjacent"
    return "far"


def cutoff_regime(hour):
    if hour is None:
        return "unknown"
    if hour < 10:
        return "early"
    if hour < 14:
        return "midday"
    return "late"


def verify_corpus_inputs(folders, corpus_manifest):
    """Verify every pinned tape/replay hash before any ablation is scored."""
    warnings = []
    for folder in folders:
        folder = Path(folder)
        entry = entry_for_folder(corpus_manifest, folder)
        if entry is None:
            warnings.append(f"{folder.name}: folder is absent from the pinned corpus")
            continue
        tape_path = folder / "snapshots_long.csv"
        if not tape_path.is_file():
            warnings.append(f"{folder.name}: snapshots_long.csv is missing")
            continue
        frame = pd.read_csv(tape_path)
        pinned_ids = {str(value) for value in entry.get("snapshot_ids") or []}
        expected_hashes = {
            str(key): str(value)
            for key, value in (entry.get("replay_record_hashes") or {}).items()
        }
        if set(expected_hashes) != pinned_ids:
            warnings.append(
                f"{folder.name}: pinned replay hash IDs do not equal snapshot IDs"
            )
            continue
        try:
            records = index_records_by_pinned_hash(
                load_replay_records(folder), expected_hashes
            )
        except ValueError as exc:
            warnings.append(f"{folder.name}: {exc}")
            continue
        warnings.extend(verify_entry_inputs(entry, folder, frame, records))
    return warnings


def _unit_digest(units):
    digest = hashlib.sha256()
    for unit in sorted(units):
        digest.update("\t".join(unit).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_runtime_support(
    support_manifest,
    runtime_units,
    scored_units,
    corpus_manifest,
    *,
    support_sha256=None,
    preregistration=None,
    preregistration_sha256=None,
    feasibility=None,
    model_binding_audit=None,
):
    if support_manifest.get("schema_version") != "captured_source_variant_support_audit_v0.4":
        raise ValueError("source support seal is not terminal v0.4")
    if support_manifest.get("corpus_hash") != corpus_manifest.get("corpus_hash"):
        raise ValueError("source support seal corpus hash does not match replay corpus")
    if preregistration is None or feasibility is None:
        raise ValueError("runtime support validation requires preregistration and feasibility seals")
    if preregistration.get("schema_version") != "workstation_source_ablation_preregistration_v0.3":
        raise ValueError("source preregistration is not terminal v0.3")
    if feasibility.get("schema_version") != "source_ablation_inference_feasibility_v0.2":
        raise ValueError("source feasibility seal is not terminal v0.2")
    support_provenance = support_manifest.get("provenance") or {}
    if (
        str((support_provenance.get("preregistration") or {}).get("sha256") or "")
        != str(preregistration_sha256 or "")
    ):
        raise ValueError("support seal is not bound to the supplied preregistration")
    feasibility_provenance = feasibility.get("provenance") or {}
    if str((feasibility_provenance.get("support") or {}).get("sha256") or "") != str(
        support_sha256 or ""
    ):
        raise ValueError("feasibility seal is not bound to the supplied support seal")
    if str((feasibility_provenance.get("preregistration") or {}).get("sha256") or "") != str(
        preregistration_sha256 or ""
    ):
        raise ValueError("feasibility seal is not bound to the supplied preregistration")
    rows = support_manifest.get("variants") or []
    if [str(row.get("variant") or "") for row in rows] != list(ALL_VARIANTS):
        raise ValueError("source support seal does not contain the exact 22 variants")
    expected_members = {
        **{
            str(name): [str(name)]
            for name in preregistration.get("single_source_variants") or []
        },
        **{
            str(name): [str(value) for value in values]
            for name, values in (preregistration.get("group_variants") or {}).items()
        },
    }
    if list(expected_members) != list(ALL_VARIANTS):
        raise ValueError("preregistration does not contain the exact ordered 22 variants")
    split_allocations = None
    for row in rows:
        variant = str(row.get("variant") or "")
        if list(row.get("members") or []) != expected_members[variant]:
            raise ValueError(f"support membership differs from preregistration: {variant}")
        allocations = {
            split: tuple(
                ((row.get("splits") or {}).get(split) or {}).get("allocated_dates") or []
            )
            for split in ("tune", "holdout")
        }
        if split_allocations is None:
            split_allocations = allocations
        elif allocations != split_allocations:
            raise ValueError("support rows do not share identical split allocations")
        for split, allocated in allocations.items():
            detail = ((row.get("splits") or {}).get(split) or {})
            supported = tuple(detail.get("supported_dates") or [])
            unsupported = tuple(detail.get("unsupported_dates") or [])
            if tuple(sorted(supported + unsupported)) != tuple(allocated):
                raise ValueError(f"support date partition is invalid: {variant}/{split}")
            if set(supported) & set(unsupported):
                raise ValueError(f"support date partition overlaps: {variant}/{split}")
    split_dates = {
        split: set(values) for split, values in (split_allocations or {}).items()
    }
    if not all(split_dates.values()) or split_dates["tune"] & split_dates["holdout"]:
        raise ValueError("source support seal has invalid tune/holdout allocations")
    audit = {"schema_version": "source_ablation_runtime_support_audit_v0.1", "variants": []}
    for row in rows:
        variant = str(row.get("variant") or "")
        if scored_units[variant] != runtime_units[variant]:
            missing = len(runtime_units[variant] - scored_units[variant])
            extra = len(scored_units[variant] - runtime_units[variant])
            raise ValueError(
                f"not every supported snapshot scored for {variant}: missing={missing}, extra={extra}"
            )
        split_audit = {}
        for split, dates in split_dates.items():
            actual = {unit for unit in runtime_units[variant] if unit[1] in dates}
            expected = (row.get("splits") or {}).get(split) or {}
            actual_market_days = {(unit[1], unit[2]) for unit in actual}
            expected_market_days = {
                (str(value.get("target_date") or ""), str(value.get("market_id") or ""))
                for value in expected.get("supported_market_days") or []
            }
            observed = {
                "supported_snapshot_count": len(actual),
                "supported_snapshot_units_sha256": _unit_digest(actual),
                "supported_market_day_count": len(actual_market_days),
            }
            for key, value in observed.items():
                if value != expected.get(key):
                    raise ValueError(
                        f"runtime support differs from seal for {variant}/{split}/{key}"
                    )
            if actual_market_days != expected_market_days:
                raise ValueError(
                    f"runtime market-day support differs from seal for {variant}/{split}"
                )
            split_audit[split] = observed
        audit["variants"].append({"variant": variant, "splits": split_audit})
    audit["support_sha256"] = support_sha256
    audit["preregistration_sha256"] = preregistration_sha256
    audit["feasibility_support_sha256"] = (
        feasibility_provenance.get("support") or {}
    ).get("sha256")
    return audit


def run_ablation(
    folders,
    requested_sources,
    include_reconstructed=False,
    *,
    corpus_manifest=None,
    support_manifest=None,
    support_audit=None,
    support_sha256=None,
    preregistration=None,
    preregistration_sha256=None,
    feasibility=None,
    model_binding_audit=None,
    model_factory=None,
    daily_summary_resolver=None,
):
    if corpus_manifest is not None:
        corpus_warnings = verify_corpus_inputs(folders, corpus_manifest)
        if corpus_warnings:
            preview = "; ".join(corpus_warnings[:5])
            suffix = "" if len(corpus_warnings) <= 5 else f"; +{len(corpus_warnings) - 5} more"
            raise ValueError(f"pinned corpus input verification failed: {preview}{suffix}")

    models = {}
    daily_indexes = {}
    rows = []
    day_meta = []
    runtime_support_units = {variant: set() for variant in ALL_VARIANTS}
    scored_support_units = {variant: set() for variant in ALL_VARIANTS}
    make_model = model_factory or (
        lambda market_id: TorontoHighTempModel(market_id=market_id)
    )
    research_bundle_ids = set()

    for folder in folders:
        folder = Path(folder)
        tape_path = folder / "snapshots_long.csv"
        if not tape_path.exists():
            continue
        market_id = folder_market_id(folder)
        if market_id is None:
            continue
        spec = REGISTRY[market_id]
        variants = variant_names_for_spec(spec, requested_sources)
        if not variants:
            continue
        if market_id not in models:
            models[market_id] = make_model(market_id)
        model = models[market_id]
        if support_manifest is not None:
            bundle = getattr(model, "serving_bundle", None)
            if (
                getattr(bundle, "status", None) != STATUS_RESEARCH_UNBOUND
                or getattr(bundle, "pointer_present", True) is not False
            ):
                raise ValueError(
                    "hardened source replay requires an explicit RESEARCH_UNBOUND model bundle"
                )
            research_bundle_ids.add(id(bundle))

        df = pd.read_csv(tape_path)
        if "snapshot_id" not in df:
            continue
        corpus_entry = (
            entry_for_folder(corpus_manifest, folder)
            if corpus_manifest is not None
            else None
        )
        loaded_records = load_replay_records(folder)
        if corpus_entry is not None:
            pinned_ids = {str(item) for item in corpus_entry.get("snapshot_ids") or []}
            expected_hashes = {
                str(key): str(value)
                for key, value in (corpus_entry.get("replay_record_hashes") or {}).items()
            }
            if set(expected_hashes) != pinned_ids:
                raise ValueError(
                    f"pinned replay hash IDs differ from snapshot IDs: {folder.name}"
                )
            records = index_records_by_pinned_hash(loaded_records, expected_hashes)
            df = df[df["snapshot_id"].astype(str).isin(pinned_ids)].copy()
            scoring_warnings = verify_entry_inputs(
                corpus_entry,
                folder,
                df,
                records,
            )
            if scoring_warnings:
                preview = "; ".join(scoring_warnings[:5])
                suffix = (
                    ""
                    if len(scoring_warnings) <= 5
                    else f"; +{len(scoring_warnings) - 5} more"
                )
                raise ValueError(
                    "exact scoring-frame input verification failed: "
                    f"{preview}{suffix}"
                )
        else:
            records = index_records_by_snapshot(loaded_records)
            records = {
                snapshot_id: record
                for snapshot_id, record in records.items()
                if include_reconstructed or not is_reconstructed(record)
            }
        if not records:
            continue
        target_date = date_from_event_slug(folder.name)
        pinned_bucket = corpus_entry.get("settlement_bucket") if corpus_entry else None
        if pinned_bucket is not None:
            bucket = int(float(pinned_bucket))
            source = str(corpus_entry.get("settlement_source") or "unknown")
            settlement_binding = "promotion_corpus"
        else:
            if market_id not in daily_indexes:
                summary_path = (
                    daily_summary_resolver(market_id)
                    if daily_summary_resolver is not None
                    else spec.data_root / "daily" / "daily_summary.csv"
                )
                daily_indexes[market_id] = load_daily_summary(summary_path)
            bucket, source, _ = settlement_for_tape(
                df, target_date, daily_indexes[market_id], {}
            )
            settlement_binding = "runtime_resolution"
        if bucket is None:
            print(f"  skip {folder.name}: no settlement")
            continue
        date_label = target_date.isoformat() if target_date else folder.name
        day_key = f"{market_id} {date_label}"
        family = "toronto" if market_id == "toronto" else "us_f"

        scored_snaps = 0
        relative_folder = str(
            (corpus_entry or {}).get("folder_relative_to_snapshots_root")
            or folder.name
        )
        for snapshot_id, group in df.groupby("snapshot_id"):
            record = records.get(str(snapshot_id))
            if not record or not record.get("sources"):
                continue
            record_hash = canonical_replay_record_sha256(record)
            support_unit = (
                relative_folder,
                date_label,
                market_id,
                str(snapshot_id),
                record_hash,
            )

            bands = []
            for _, band_series in group.iterrows():
                band = clean_band_row(band_series.to_dict())
                outcome = resolve_outcome(
                    band.get("bin_kind"), band.get("bin_value_c"), bucket,
                    value_hi=band_value_hi(band.get("range_label"), band.get("bin_value_c")),
                )
                if outcome is None:
                    continue
                bands.append((band, int(outcome)))
            if support_manifest is not None and len(bands) != len(group):
                raise ValueError(
                    f"not every pinned tape band has a valid outcome: {relative_folder}/{snapshot_id}"
                )
            if not bands:
                continue

            # Baseline first; band probabilities must be read immediately after
            # each replay because bin_probability uses the calibration context
            # estimate_distribution just set on the model.
            base_dist = replay_distribution(model, record)
            if not base_dist:
                continue
            base_probs = [band_model_probability(model, base_dist, band) for band, _ in bands]
            if support_manifest is not None:
                _assert_probability_distribution(
                    base_dist, label=f"baseline {relative_folder}/{snapshot_id}"
                )
                if any(_finite_probability(value) is None for value in base_probs):
                    raise ValueError(
                        f"baseline band probability is invalid: {relative_folder}/{snapshot_id}"
                    )

            hour = None
            captured = str(bands[0][0].get("captured_at_local") or "")
            if len(captured) >= 13:
                try:
                    hour = int(captured[11:13])
                except ValueError:
                    hour = None

            for variant in variants:
                if not variant_has_support(model, record["sources"], variant):
                    continue
                runtime_support_units[variant].add(support_unit)
                variant_record = dict(record)
                variant_record["sources"] = ablate_variant_sources(
                    model, record["sources"], variant
                )
                variant_dist = replay_distribution(model, variant_record)
                if not variant_dist:
                    continue
                if support_manifest is not None:
                    _assert_probability_distribution(
                        variant_dist,
                        label=f"{variant} {relative_folder}/{snapshot_id}",
                    )
                appended_count = 0
                for (band, outcome), base_p in zip(bands, base_probs):
                    variant_p = band_model_probability(model, variant_dist, band)
                    if variant_p is None or base_p is None:
                        if support_manifest is not None:
                            raise ValueError(
                                f"paired band probability is missing: {variant}/{relative_folder}/{snapshot_id}"
                            )
                        continue
                    if support_manifest is not None and (
                        _finite_probability(variant_p) is None
                        or _finite_probability(base_p) is None
                    ):
                        raise ValueError(
                            f"paired band probability is invalid: {variant}/{relative_folder}/{snapshot_id}"
                        )
                    rows.append({
                        "day": day_key,
                        "family": family,
                        "variant": variant,
                        "folder_relative_to_snapshots_root": relative_folder,
                        "snapshot_id": str(snapshot_id),
                        "canonical_replay_record_sha256": record_hash,
                        "hour": hour,
                        "cutoff_regime": cutoff_regime(hour),
                        "settlement_distance": settlement_distance_bucket(band, bucket),
                        "y": outcome,
                        "base_p": base_p,
                        "variant_p": variant_p,
                        "market_yes": safe_float(band.get("market_yes")),
                    })
                    appended_count += 1
                if support_manifest is not None and appended_count != len(group):
                    raise ValueError(
                        f"not every pinned tape band scored: {variant}/{relative_folder}/{snapshot_id}"
                    )
                if appended_count:
                    scored_support_units[variant].add(support_unit)
            scored_snaps += 1

        day_meta.append({
            "market_day": day_key, "settlement": bucket, "settlement_source": source,
            "settlement_binding": settlement_binding,
            "snapshots": scored_snaps,
        })
        print(f"  {folder.name}: settlement {bucket} {spec.display_unit} ({source}); "
              f"{scored_snaps} snapshots ablated over {len(variants)} variants")

    if support_manifest is not None:
        if corpus_manifest is None:
            raise ValueError("support validation requires a pinned corpus manifest")
        audit = _validate_runtime_support(
            support_manifest,
            runtime_support_units,
            scored_support_units,
            corpus_manifest,
            support_sha256=support_sha256,
            preregistration=preregistration,
            preregistration_sha256=preregistration_sha256,
            feasibility=feasibility,
        )
        if support_audit is not None:
            support_audit.clear()
            support_audit.update(audit)
        if len(research_bundle_ids) != 1:
            raise ValueError("hardened source replay models do not share one explicit bundle")
    if model_binding_audit is not None:
        model_binding_audit.clear()
        model_binding_audit.update(audit_model_bindings(models))
    return pd.DataFrame(rows), day_meta


def summarize(data):
    """Per-variant pooled scores plus per-day helped/hurt counts."""
    if data.empty:
        return [], {}
    summaries = []
    day_tables = {}

    def mean_logloss(frame, probability_column):
        values = []
        for probability, outcome in zip(frame[probability_column], frame["y"]):
            p = max(1e-15, min(1.0 - 1e-15, float(probability)))
            y = int(outcome)
            values.append(-(y * math.log(p) + (1 - y) * math.log(1.0 - p)))
        return sum(values) / len(values) if values else None

    for variant, sub in data.groupby("variant"):
        base_brier = ((sub["base_p"] - sub["y"]) ** 2).mean()
        variant_brier = ((sub["variant_p"] - sub["y"]) ** 2).mean()
        base_logloss = mean_logloss(sub, "base_p")
        variant_logloss = mean_logloss(sub, "variant_p")
        market_rows = sub.dropna(subset=["market_yes"])
        market_brier = (
            ((market_rows["market_yes"] - market_rows["y"]) ** 2).mean()
            if len(market_rows) else None
        )
        per_day = []
        for day, day_rows in sub.groupby("day"):
            day_base_brier = ((day_rows["base_p"] - day_rows["y"]) ** 2).mean()
            day_variant_brier = ((day_rows["variant_p"] - day_rows["y"]) ** 2).mean()
            day_base_logloss = mean_logloss(day_rows, "base_p")
            day_variant_logloss = mean_logloss(day_rows, "variant_p")
            per_day.append({
                "market_day": day,
                "delta": day_variant_brier - day_base_brier,
                "brier_delta": day_variant_brier - day_base_brier,
                "logloss_delta": day_variant_logloss - day_base_logloss,
                "base_brier": day_base_brier,
                "variant_brier": day_variant_brier,
                "base_logloss": day_base_logloss,
                "variant_logloss": day_variant_logloss,
                "n": len(day_rows),
            })
        per_day.sort(key=lambda row: row["delta"])
        day_tables[variant] = per_day
        helped = sum(1 for row in per_day if row["delta"] > 0.0001)
        hurt = sum(1 for row in per_day if row["delta"] < -0.0001)
        by_family = {}
        for family, fam_rows in sub.groupby("family"):
            by_family[family] = (
                ((fam_rows["variant_p"] - fam_rows["y"]) ** 2).mean()
                - ((fam_rows["base_p"] - fam_rows["y"]) ** 2).mean()
            )
        summaries.append({
            "variant": variant,
            "n": len(sub),
            "market_days": sub["day"].nunique(),
            "base_brier": base_brier,
            "variant_brier": variant_brier,
            "delta": variant_brier - base_brier,
            "base_logloss": base_logloss,
            "variant_logloss": variant_logloss,
            "logloss_delta": variant_logloss - base_logloss,
            "market_brier": market_brier,
            "market_days_source_helped": helped,
            "market_days_source_hurt": hurt,
            "by_family": by_family,
        })
    summaries.sort(key=lambda row: row["delta"], reverse=True)
    return summaries, day_tables


def resolve_outputs_outside_read_only_root(
    data_root,
    outputs,
    *,
    protected_inputs=(),
    protected_roots=(),
):
    """Resolve outputs and reject aliases into read-only inputs or roots."""

    root = Path(data_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"read-only data root is not a directory: {root}")
    protected_files = {
        Path(value).expanduser().resolve(strict=False)
        for value in protected_inputs
        if value is not None
    }
    protected_trees = [("supplied read-only data root", root)]
    for value in protected_roots:
        if value is None:
            continue
        candidate = Path(value).expanduser().resolve(strict=False)
        if all(candidate != existing for _, existing in protected_trees):
            protected_trees.append(("protected read-only root", candidate))
    resolved = {}
    for label, raw_path in outputs.items():
        target = Path(raw_path).expanduser().resolve(strict=False)
        for protected_label, protected_root in protected_trees:
            try:
                target.relative_to(protected_root)
            except ValueError:
                continue
            raise ValueError(
                f"{label} resolves inside the {protected_label}: {target}"
            )
        for protected_file in protected_files:
            aliases_input = target == protected_file
            if not aliases_input and target.exists() and protected_file.exists():
                try:
                    aliases_input = target.samefile(protected_file)
                except OSError:
                    aliases_input = False
            if aliases_input:
                raise ValueError(
                    f"{label} output aliases a protected input: {target}"
                )
        for other_label, other_target in resolved.items():
            aliases_other = target == other_target
            if not aliases_other and target.exists() and other_target.exists():
                try:
                    aliases_other = target.samefile(other_target)
                except OSError:
                    aliases_other = False
            if aliases_other:
                raise ValueError(
                    f"{label} and {other_label} outputs must not alias: {target}"
                )
        resolved[label] = target
    return root, resolved


def _parse_date_manifest(text, path):
    values = []
    for raw in text.splitlines():
        value = raw.split("#", 1)[0].strip()
        if value:
            values.append(value)
    if values != sorted(set(values)):
        raise ValueError(f"date manifest must be unique and sorted: {path}")
    return values


def read_date_manifest_with_receipt(path):
    resolved = Path(path).expanduser().resolve(strict=True)
    before = resolved.stat()
    raw = resolved.read_bytes()
    after = resolved.stat()
    if _stable_file_identity(before) != _stable_file_identity(after) or len(
        raw
    ) != after.st_size:
        raise ValueError(f"date manifest changed while reading: {resolved}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"date manifest is not valid UTF-8: {resolved}") from exc
    values = _parse_date_manifest(text, resolved)
    return values, {
        "path": str(resolved),
        "status": "PASS",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "blockers": [],
    }


def read_date_manifest(path):
    if not path:
        return []
    values, _receipt = read_date_manifest_with_receipt(path)
    return values


def summarize_slice_effects(data):
    if data.empty:
        return []
    rows = []
    slices = [
        ("market", ["market_id"]),
        ("cutoff_regime", ["cutoff_regime"]),
        ("market_cutoff_regime", ["market_id", "cutoff_regime"]),
        ("settlement_distance", ["settlement_distance"]),
    ]
    data = data.copy()
    data["market_id"] = data["day"].map(market_from_day)
    if "cutoff_regime" not in data:
        data["cutoff_regime"] = "unknown"
    else:
        data["cutoff_regime"] = data["cutoff_regime"].fillna("unknown")
    if "settlement_distance" not in data:
        data["settlement_distance"] = "unknown"
    else:
        data["settlement_distance"] = data["settlement_distance"].fillna("unknown")
    for variant, variant_rows in data.groupby("variant"):
        for slice_name, columns in slices:
            for key, sub in variant_rows.groupby(columns):
                if not isinstance(key, tuple):
                    key = (key,)
                base_brier = ((sub["base_p"] - sub["y"]) ** 2).mean()
                variant_brier = ((sub["variant_p"] - sub["y"]) ** 2).mean()
                row = {
                    "variant": variant,
                    "slice": slice_name,
                    "n": int(len(sub)),
                    "market_days": int(sub["day"].nunique()),
                    "base_brier": base_brier,
                    "variant_brier": variant_brier,
                    "delta": variant_brier - base_brier,
                }
                row.update({column: value for column, value in zip(columns, key)})
                rows.append(row)
    rows.sort(key=lambda row: (str(row["variant"]), str(row["slice"]), str(row.get("market_id", "")), str(row.get("cutoff_regime", ""))))
    return rows


def fmt(value, decimals=4):
    if value is None:
        return "-"
    return f"{value:.{decimals}f}"


def fmt_signed(value, decimals=4):
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}"


def render_report(
    summaries,
    day_tables,
    day_meta,
    include_reconstructed,
    robustness_inference=None,
    market_inference=None,
    generated=None,
):
    generated = generated or datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Per-Source Ablation Replay",
        "",
        f"Generated: {generated}",
        "",
        "Each captured snapshot is replayed with the bound research code on its",
        "captured sources (baseline) and again with a terminal source removal",
        "after captured collector fallback/cache resolution. Delta = ablated Brier",
        "minus baseline Brier on matched rows: **positive = the source was",
        "helping** (removing it hurts), negative = the model scored better",
        "without it.",
        "",
        f"Market-days scored: {len(day_meta)}  |  reconstructed records included: "
        f"{'yes' if include_reconstructed else 'no'}",
        "",
        "## Source Value Summary",
        "",
        "| Variant | Rows | Market-days | Baseline Brier | Ablated Brier | Brier delta | Log-loss delta | Market-days helped | Market-days hurt | Market Brier |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in summaries:
        lines.append(
            f"| {s['variant']} | {s['n']} | {s['market_days']} | {fmt(s['base_brier'])} "
            f"| {fmt(s['variant_brier'])} | {fmt_signed(s['delta'])} "
            f"| {fmt_signed(s['logloss_delta'])} "
            f"| {s['market_days_source_helped']} | {s['market_days_source_hurt']} "
            f"| {fmt(s['market_brier'])} |"
        )
    lines += [
        "",
        "## By Family (delta, positive = source helps)",
        "",
        "| Variant | toronto | us_f |",
        "| :--- | ---: | ---: |",
    ]
    for s in summaries:
        toronto = s["by_family"].get("toronto")
        us = s["by_family"].get("us_f")
        lines.append(
            f"| {s['variant']} | {fmt_signed(toronto) if toronto is not None else '-'} "
            f"| {fmt_signed(us) if us is not None else '-'} |"
        )
    lines += ["", "## Largest Per-Market-Day Effects", ""]
    for s in summaries:
        per_day = day_tables.get(s["variant"]) or []
        if not per_day:
            continue
        lines.append(f"### {s['variant']}")
        lines.append("")
        lines.append("| Market-day | Delta | Rows |")
        lines.append("| :--- | ---: | ---: |")
        extremes = per_day[:3] + ([] if len(per_day) <= 6 else per_day[-3:])
        for row in extremes:
            lines.append(f"| {row['market_day']} | {fmt_signed(row['delta'])} | {row['n']} |")
        lines.append("")
    if robustness_inference:
        lines += [
            "## Settlement and Panel Robustness",
            "",
            "Equal-weighted fleet-date deltas under pre-outcome support scopes. Positive means the source helps.",
            "",
            "| Scope | Variant | Split | Fleet dates | Market-days | Brier delta (95% CI) | Log-loss delta (95% CI) |",
            "| :--- | :--- | :--- | ---: | ---: | ---: | ---: |",
        ]
        for row in robustness_inference:
            brier = row["brier_delta"]
            logloss = row["logloss_delta"]
            brier_ci = brier["cluster_bootstrap_95ci"]
            logloss_ci = logloss["cluster_bootstrap_95ci"]
            lines.append(
                f"| {row['scope']} | {row['variant']} | {row['split']} "
                f"| {row['fleet_dates']} | {row['market_days']} "
                f"| {fmt_signed(brier['mean'])} [{fmt_signed(brier_ci['low'])}, {fmt_signed(brier_ci['high'])}] "
                f"| {fmt_signed(logloss['mean'])} [{fmt_signed(logloss_ci['low'])}, {fmt_signed(logloss_ci['high'])}] |"
            )
        lines.append("")
    if market_inference:
        preferred_split = (
            "holdout"
            if any(row.get("split") == "holdout" for row in market_inference)
            else "all"
        )
        lines += [
            f"## Per-Market Paired Effects ({preferred_split})",
            "",
            "Positive deltas mean removing the source hurt, so the source helped.",
            "",
            "| Variant | Market | Days | No-op days | Brier delta (95% date CI) | Log-loss delta (95% date CI) |",
            "| :--- | :--- | ---: | ---: | ---: | ---: |",
        ]
        for row in market_inference:
            if row.get("split") != preferred_split:
                continue
            brier = row["brier_delta"]
            logloss = row["logloss_delta"]
            brier_ci = brier["date_bootstrap_95ci"]
            logloss_ci = logloss["date_bootstrap_95ci"]
            lines.append(
                f"| {row['variant']} | {row['market_id']} | {row['market_days']} "
                f"| {row['no_op_market_days']} "
                f"| {fmt_signed(brier['mean'])} [{fmt_signed(brier_ci['low'])}, {fmt_signed(brier_ci['high'])}] "
                f"| {fmt_signed(logloss['mean'])} [{fmt_signed(logloss_ci['low'])}, {fmt_signed(logloss_ci['high'])}] |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def write_report(
    out_path,
    summaries,
    day_tables,
    day_meta,
    include_reconstructed,
    robustness_inference=None,
    market_inference=None,
):
    return write_text_atomic(
        out_path,
        render_report(
            summaries,
            day_tables,
            day_meta,
            include_reconstructed,
            robustness_inference,
            market_inference,
        ),
    )


def json_ready(value):
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if pd.isna(value) if not isinstance(value, (dict, list, tuple, str, bytes)) else False:
        return None
    return value


def build_payload(
    summaries,
    day_tables,
    day_meta,
    requested_sources,
    include_reconstructed,
    slice_effects=None,
    corpus_manifest=None,
    paired_inference=None,
    robustness_inference=None,
    market_inference=None,
    split_dates=None,
    runtime_support_audit=None,
    sealed_contracts=None,
    model_binding=None,
    execution_identity=None,
    input_receipts=None,
    evidence_mode=EVIDENCE_MODE_RESEARCH,
):
    if evidence_mode not in EVIDENCE_MODES:
        raise ValueError(
            "source-ablation evidence_mode must be one of: "
            + ", ".join(sorted(EVIDENCE_MODES))
        )
    research_only = evidence_mode == EVIDENCE_MODE_RESEARCH
    variants = []
    for summary in summaries:
        variant = summary.get("variant")
        variants.append({
            **json_ready(summary),
            "ablated_sources": list(COMBINED_VARIANTS.get(variant, (variant,))),
        })
    corpus_summary = (corpus_manifest or {}).get("summary") or {}
    corpus_entries = (corpus_manifest or {}).get("entries") or []
    corpus_receipt = (input_receipts or {}).get("corpus") or {}
    payload = {
        "schema_version": schema_version(
            "source_family_ablation_research" if research_only else "source_family_ablation"
        ),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "evidence_mode": evidence_mode,
        "include_reconstructed": bool(include_reconstructed),
        "research_only": bool(research_only),
        "promotion_preflight_evidence_authorization": not bool(research_only),
        "serving_or_release_authorization": False,
        "model_binding": json_ready(model_binding or {}),
        "source_semantics": (
            "terminal removal after captured collector fallback/cache resolution; "
            "not a byte-identical transient live-fetch outage"
        ),
        "corpus": ({
            "path": corpus_manifest.get("_path"),
            "manifest_sha256": corpus_receipt.get("sha256"),
            "schema_version": corpus_manifest.get("schema_version"),
            "corpus_hash": corpus_manifest.get("corpus_hash"),
            "as_of": corpus_manifest.get("as_of"),
            "market_day_count": corpus_summary.get("market_day_count"),
            "snapshot_count": corpus_summary.get("snapshot_count"),
            "target_dates": sorted(
                {
                    str(entry.get("target_date"))
                    for entry in corpus_entries
                    if isinstance(entry, dict) and entry.get("target_date")
                }
            ),
            "market_ids": sorted(
                {
                    str(entry.get("market_id"))
                    for entry in corpus_entries
                    if isinstance(entry, dict) and entry.get("market_id")
                }
            ),
            "input_verification": "PASS",
        } if corpus_manifest is not None else None),
        "input_receipts": json_ready(input_receipts or {}),
        "requested_variants": list(requested_sources),
        "split_dates": {
            str(split): list(values)
            for split, values in sorted((split_dates or {}).items())
        },
        "summary": {
            "variant_count": len(variants),
            "market_days_scored": len(day_meta),
            "rows_scored": int(sum(row.get("n", 0) for row in variants)),
            "slice_effect_count": len(slice_effects or []),
        },
        "variants": variants,
        "day_effects": json_ready(day_tables),
        "paired_inference": json_ready(paired_inference or []),
        "robustness_contract": {
            "settlement_scope": "promotion_corpus settlement_source exactly equals daily_summary",
            "complete_panel_scope": "corpus and variant-scored market-ID sets both exactly equal the sealed 12-market set; support selected without outcomes",
            "cluster_unit": "fleet target date",
            "primary_market_ids": sorted(REGISTRY),
            "per_market_action_scope": "holdout promotion-corpus daily_summary market-days only",
            "outcome_independent_scope_selection": True,
        },
        "robustness_inference": json_ready(robustness_inference or []),
        "market_inference": json_ready(market_inference or []),
        "runtime_support_audit": json_ready(runtime_support_audit or {}),
        "sealed_contracts": json_ready(sealed_contracts or {}),
        "execution_identity": json_ready(execution_identity or {}),
        "slice_effects": json_ready(slice_effects or []),
        "market_days": json_ready(day_meta),
    }
    if not research_only:
        validate_operational_evidence_inputs(
            variants,
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
            slice_effects or [],
            normalize=json_ready,
        )
    return payload


def write_json_report(out_path, payload):
    return write_json_atomic(out_path, payload, trailing_newline=True)


def add_robustness_to_existing_artifact(
    json_path,
    *,
    read_only_data_root,
    split_dates=None,
    expected_sha256=None,
    output_json_path=None,
    report_path=None,
):
    """Publish a receipted, exclusive robustness augmentation generation."""

    if set(split_dates or {}) != {"tune", "holdout"}:
        raise ValueError(
            "split_dates must explicitly provide tune and holdout allocations"
        )

    expected_sha256 = str(expected_sha256 or "").strip().lower()
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ValueError("expected_sha256 must be a trusted 64-character hex digest")
    if output_json_path is None or report_path is None:
        raise ValueError(
            "output_json_path and report_path are required; in-place augmentation is retired"
        )

    resolved_input, raw, observed_sha256, input_size = _stable_json_bytes(json_path)
    if observed_sha256 != expected_sha256:
        raise ValueError(
            "source-ablation artifact differs from its trusted receipt: "
            f"expected={expected_sha256}; observed={observed_sha256}"
        )
    payload = _strict_json_object_from_bytes(raw, path=resolved_input)

    requested_outputs = {
        "output_json_path": output_json_path,
        "report_path": report_path,
    }
    _, guarded_outputs = resolve_outputs_outside_read_only_root(
        read_only_data_root,
        requested_outputs,
        protected_inputs=(resolved_input,),
    )
    output_json_path = guarded_outputs["output_json_path"]
    report_path = guarded_outputs["report_path"]
    existing = [path for path in (output_json_path, report_path) if path.exists()]
    if existing:
        raise ValueError(
            "robustness augmentation refuses existing outputs: "
            + ", ".join(str(path) for path in existing)
        )
    robustness = paired_inference_sensitivities(
        payload.get("day_effects") or {},
        payload.get("market_days") or [],
        split_dates=split_dates,
        required_market_ids=tuple(sorted(REGISTRY)),
    )
    payload["robustness_contract"] = {
        "settlement_scope": "promotion_corpus settlement_source exactly equals daily_summary",
        "complete_panel_scope": "corpus and variant-scored market-ID sets both exactly equal the sealed 12-market set; support selected without outcomes",
        "cluster_unit": "fleet target date",
        "primary_market_ids": sorted(REGISTRY),
        "per_market_action_scope": "holdout promotion-corpus daily_summary market-days only",
        "outcome_independent_scope_selection": True,
    }
    payload["robustness_inference"] = json_ready(robustness)
    payload["split_dates"] = {
        str(split): list(values)
        for split, values in sorted(split_dates.items())
    }
    market_inference = paired_market_inference(
        payload.get("day_effects") or {},
        split_dates,
        day_meta=payload.get("market_days") or [],
    )
    payload["market_inference"] = json_ready(market_inference)
    payload["augmentation_input_receipt"] = {
        "path": str(resolved_input),
        "status": "PASS",
        "sha256": observed_sha256,
        "size_bytes": input_size,
        "blockers": [],
    }
    rendered_report = render_report(
        payload.get("variants") or [],
        payload.get("day_effects") or {},
        payload.get("market_days") or [],
        payload.get("include_reconstructed", False),
        robustness,
        market_inference,
    )
    json.dumps(payload, sort_keys=True, allow_nan=False)
    atomic_write_text_exclusive(report_path, rendered_report)
    # The JSON is the completion leaf and appears only after the companion report.
    atomic_write_json_exclusive(output_json_path, payload)
    return payload


def resolve_evidence_output_paths(*, operational_evidence, out=None, json_out=None):
    default_out = DEFAULT_OUT if operational_evidence else DEFAULT_RESEARCH_OUT
    default_json = (
        DEFAULT_JSON_OUT if operational_evidence else DEFAULT_RESEARCH_JSON_OUT
    )
    resolved_out = Path(out) if out is not None else default_out
    resolved_json = Path(json_out) if json_out is not None else default_json
    if not operational_evidence:
        forbidden = []
        if (
            resolved_out.expanduser().resolve(strict=False)
            == DEFAULT_OUT.expanduser().resolve(strict=False)
        ):
            forbidden.append("report")
        if (
            resolved_json.expanduser().resolve(strict=False)
            == DEFAULT_JSON_OUT.expanduser().resolve(strict=False)
        ):
            forbidden.append("JSON")
        if forbidden:
            raise ValueError(
                "the canonical operational "
                + " and ".join(forbidden)
                + " path requires --operational-evidence"
            )
    return resolved_out, resolved_json


def validate_operational_cli_args(args, *, requested_sources=None):
    required = {
        "corpus": args.corpus,
        "tune_dates_file": args.tune_dates_file,
        "holdout_dates_file": args.holdout_dates_file,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise ValueError(
            "Operational source replay requires: " + ", ".join(missing)
        )
    if args.folders or args.market or args.include_reconstructed:
        raise ValueError(
            "Operational source replay forbids folder/market subsets and "
            "reconstructed inputs"
        )
    if requested_sources is not None:
        exact_requested_variants(requested_sources)


def main():
    parser = argparse.ArgumentParser(
        description="Replay the corpus with each live source knocked out and "
                    "measure the per-source Brier effect.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders (default: all with tapes).")
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY),
                        help="Only this market's folders.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument(
        "--corpus",
        default=None,
        help="Optional pinned promotion-corpus manifest; hashes fail closed before scoring.",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="Optional explicit read-only model-data root for offline replay.",
    )
    parser.add_argument("--tune-dates-file", default=None)
    parser.add_argument("--holdout-dates-file", default=None)
    parser.add_argument("--hardened", action="store_true")
    parser.add_argument(
        "--operational-evidence",
        action="store_true",
        help=(
            "Explicitly request promotion-preflight evidence. Requires a full "
            "pinned corpus, tune/holdout manifests, and a verified active-release "
            "model binding."
        ),
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--preregistration", default=None)
    parser.add_argument("--support-seal", default=None)
    parser.add_argument("--feasibility-seal", default=None)
    parser.add_argument("--generation-dir", default=None)
    parser.add_argument("--sources", default=",".join(list(SINGLE_SOURCES) + list(COMBINED_VARIANTS)),
                        help="Comma list of sources/combined variants to ablate.")
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--json-out",
        default=None,
        help="Machine-readable source-family ablation artifact.",
    )
    args = parser.parse_args()

    requested = [item.strip() for item in args.sources.split(",") if item.strip()]
    unknown = [
        name for name in requested
        if name not in SINGLE_SOURCES and name not in COMBINED_VARIANTS
    ]
    if unknown:
        raise SystemExit(f"Unknown ablation sources: {', '.join(unknown)}")
    if args.hardened:
        if args.operational_evidence:
            raise SystemExit(
                "Hardened workstation replay is research-only and forbids "
                "--operational-evidence"
            )
        required = {
            "repo_root": args.repo_root,
            "data_root": args.data_root,
            "corpus": args.corpus,
            "preregistration": args.preregistration,
            "support_seal": args.support_seal,
            "feasibility_seal": args.feasibility_seal,
            "tune_dates_file": args.tune_dates_file,
            "holdout_dates_file": args.holdout_dates_file,
            "generation_dir": args.generation_dir,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise SystemExit(
                "Hardened source replay requires: " + ", ".join(missing)
            )
        if args.folders or args.market or args.include_reconstructed:
            raise SystemExit(
                "Hardened source replay forbids folder/market subsets and reconstructed inputs"
            )
        if args.out is not None or args.json_out is not None:
            raise SystemExit(
                "Hardened source replay publishes only through --generation-dir; --out/--json-out are forbidden"
            )
        exact_requested_variants(requested)
        from weather.reporting.research.source_ablation_hardened import run_hardened

        run_hardened(args)
        return

    try:
        if args.operational_evidence:
            validate_operational_cli_args(args, requested_sources=requested)
        args.out, args.json_out = resolve_evidence_output_paths(
            operational_evidence=args.operational_evidence,
            out=args.out,
            json_out=args.json_out,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        protected_input_paths = tuple(
            value
            for value in (
                args.corpus,
                args.tune_dates_file,
                args.holdout_dates_file,
            )
            if value
        )
        protected_roots = (args.snapshots_root, *args.folders)
        resolved_data_root, output_paths = resolve_outputs_outside_read_only_root(
            args.data_root or data_path(),
            {"out": args.out, "json_out": args.json_out},
            protected_inputs=protected_input_paths,
            protected_roots=protected_roots,
        )
        args.out = output_paths["out"]
        args.json_out = output_paths["json_out"]
        existing_outputs = [
            path
            for path in (args.out, args.json_out)
            if Path(path).exists()
        ]
        if existing_outputs:
            raise ValueError(
                "source replay generations refuse existing outputs: "
                + ", ".join(str(path) for path in existing_outputs)
            )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.data_root:
        import weather.paths as weather_paths

        weather_paths.DATA_ROOT = resolved_data_root
        TorontoHighTempModel._historical_target_cache.clear()

    input_receipts = {}
    if args.corpus and args.operational_evidence:
        corpus_manifest, input_receipts["corpus"] = _load_manifest_with_receipt(
            args.corpus
        )
    else:
        corpus_manifest = (
            load_manifest(args.corpus, max_bytes=64 * 1024 * 1024)
            if args.corpus
            else None
        )
    split_dates = {}
    if args.tune_dates_file:
        if args.operational_evidence:
            split_dates["tune"], input_receipts["tune_dates"] = (
                read_date_manifest_with_receipt(args.tune_dates_file)
            )
        else:
            split_dates["tune"] = read_date_manifest(args.tune_dates_file)
    if args.holdout_dates_file:
        if args.operational_evidence:
            split_dates["holdout"], input_receipts["holdout_dates"] = (
                read_date_manifest_with_receipt(args.holdout_dates_file)
            )
        else:
            split_dates["holdout"] = read_date_manifest(args.holdout_dates_file)
    folders = args.folders
    if corpus_manifest is not None and not folders:
        folders = [
            str(path)
            for path in folders_from_manifest_strict(
                corpus_manifest,
                args.snapshots_root,
            )
        ]
    if not folders:
        root = Path(args.snapshots_root)
        folders = sorted(str(p.parent) for p in root.glob("*/snapshots_long.csv"))
    if args.market:
        folders = [f for f in folders if folder_market_id(f) == args.market]
    if not folders:
        print("No snapshot tapes found.")
        return

    print(f"Ablating {len(requested)} variant(s) over {len(folders)} folder(s)...")
    model_binding = {}
    data, day_meta = run_ablation(
        folders,
        requested,
        include_reconstructed=args.include_reconstructed,
        corpus_manifest=corpus_manifest,
        model_binding_audit=model_binding,
    )
    if data.empty:
        print("No rows scored (no captured replay inputs?).")
        return
    summaries, day_tables = summarize(data)
    inference = paired_day_inference(day_tables, split_dates)
    robustness_inference = paired_inference_sensitivities(
        day_tables,
        day_meta,
        split_dates=split_dates,
        required_market_ids=tuple(sorted(REGISTRY)),
    )
    market_inference = paired_market_inference(
        day_tables, split_dates, day_meta=day_meta
    )
    json_payload = build_payload(
        summaries,
        day_tables,
        day_meta,
        requested,
        args.include_reconstructed,
        summarize_slice_effects(data),
        corpus_manifest,
        inference,
        robustness_inference,
        market_inference,
        split_dates,
        model_binding=model_binding,
        input_receipts=input_receipts,
        evidence_mode=(
            EVIDENCE_MODE_OPERATIONAL
            if args.operational_evidence
            else EVIDENCE_MODE_RESEARCH
        ),
    )
    rendered_report = render_report(
        summaries,
        day_tables,
        day_meta,
        args.include_reconstructed,
        robustness_inference,
        market_inference,
    )
    json.dumps(json_payload, sort_keys=True, allow_nan=False)
    atomic_write_text_exclusive(args.out, rendered_report)
    atomic_write_json_exclusive(args.json_out, json_payload)
    print(f"\nReport written to {args.out}\n")
    print(f"JSON written to {args.json_out}\n")
    print(f"{'variant':18s} {'rows':>7s} {'base':>8s} {'ablated':>8s} {'delta':>9s}  (positive = source helps)")
    for s in summaries:
        print(f"{s['variant']:18s} {s['n']:7d} {s['base_brier']:8.4f} "
              f"{s['variant_brier']:8.4f} {s['delta']:+9.4f}")


if __name__ == "__main__":
    main()
