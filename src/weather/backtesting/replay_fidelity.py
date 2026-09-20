"""Numerical incumbent replay controls; runtime restoration is a separate proof."""

from collections import Counter
from collections.abc import Mapping
import math
import re

from weather.market.worker_release_binding import RECORDED_DISTRIBUTION_MASS_TOLERANCE
from weather.model.continuous_density import density_f_from_payload

FIDELITY_FAITHFUL_L1 = 0.01
SUPPORT_EXAMPLE_LIMIT = 20


def _finite_nonnegative(value):
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) and numeric >= 0 else None


def _distribution_points(distribution):
    if not isinstance(distribution, Mapping) or not distribution:
        return None, {}, "missing or empty distribution"
    density = density_f_from_payload(distribution)
    kind = "native_buckets" if density is None else "density_f"
    raw = distribution if density is None else density
    if not isinstance(raw, Mapping) or not raw:
        return kind, {}, "missing or empty distribution points"
    points = {}
    for raw_coordinate, raw_probability in raw.items():
        try:
            coordinate = float(raw_coordinate)
        except (TypeError, ValueError, OverflowError):
            return kind, {}, "non-numeric distribution coordinate"
        probability = _finite_nonnegative(raw_probability)
        if (
            isinstance(raw_coordinate, bool)
            or not math.isfinite(coordinate)
            or (kind == "native_buckets" and not coordinate.is_integer())
            or coordinate in points
            or probability is None
            or probability > 1
        ):
            return kind, {}, "invalid coordinate or probability"
        points[coordinate] = probability
    if abs(sum(points.values()) - 1.0) > RECORDED_DISTRIBUTION_MASS_TOLERANCE:
        return kind, {}, "distribution does not preserve probability mass"
    return kind, points, None


def distribution_fidelity(replayed, recorded):
    """Compare validated coordinates as captured, without rounding or rescaling."""
    replayed_kind, left, replayed_error = _distribution_points(replayed)
    recorded_kind, right, recorded_error = _distribution_points(recorded)
    errors = []
    if replayed_error:
        errors.append(f"replayed: {replayed_error}")
    if recorded_error:
        errors.append(f"recorded: {recorded_error}")
    if not errors and replayed_kind != recorded_kind:
        errors.append("distribution representations differ")
    if errors:
        return None, "; ".join(errors)
    return sum(abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in left.keys() | right.keys()), None


def fidelity_summary(fidelity_rows):
    """Keep identity cohorts separate and require every canary row to be valid."""
    cohorts = {"same_identity": [], "legacy_same_version": [], "changed_version": [], "reconstructed": []}
    for row in fidelity_rows:
        if row.get("reconstructed"):
            cohort = "reconstructed"
        elif (
            row.get("recorded_identity_hash")
            and row.get("recorded_identity_hash") == row.get("replayed_identity_hash")
        ):
            cohort = "same_identity"
        elif (
            not row.get("recorded_identity_hash")
            and row.get("recorded_version") == row.get("replayed_version")
        ):
            cohort = "legacy_same_version"
        else:
            cohort = "changed_version"
        cohorts[cohort].append(row)

    summary = {"l1_tolerance": FIDELITY_FAITHFUL_L1}
    for cohort, rows in cohorts.items():
        values = [
            value for row in rows
            if not row.get("distribution_error")
            and (value := _finite_nonnegative(row.get("l1"))) is not None
        ]
        summary.update({
            f"{cohort}_n": len(rows),
            f"{cohort}_valid_n": len(values),
            f"{cohort}_invalid_n": len(rows) - len(values),
            f"{cohort}_mean_l1": sum(values) / len(values) if values else None,
            f"{cohort}_max_l1": max(values, default=None),
            f"{cohort}_above_tolerance_n": sum(value > FIDELITY_FAITHFUL_L1 for value in values),
        })
    summary["same_identity_faithful"] = (
        summary["same_identity_n"] > 0
        and summary["same_identity_invalid_n"] == 0
        and summary["same_identity_above_tolerance_n"] == 0
    )
    # Existing callers used "same_version" for this exact-identity cohort.
    for suffix in ("n", "mean_l1", "max_l1", "faithful"):
        summary[f"same_version_{suffix}"] = summary[f"same_identity_{suffix}"]
    return summary


def pinned_settlement_problem(entry):
    """Check usable pinned values, without asserting settlement-source authority."""
    if not isinstance(entry, Mapping):
        return "missing settlement entry"
    raw_bucket = entry.get("settlement_bucket")
    try:
        bucket = int(raw_bucket)
        numeric_bucket = float(raw_bucket)
    except (TypeError, ValueError, OverflowError):
        return "missing or invalid pinned settlement bucket"
    if isinstance(raw_bucket, bool) or not math.isfinite(numeric_bucket) or numeric_bucket != bucket:
        return "pinned settlement bucket must be finite and integral"
    source = entry.get("settlement_source")
    if not isinstance(source, str) or not source.strip():
        return "missing pinned settlement source"
    return None


def fidelity_support(fidelity_rows, corpus_manifest, duplicate_replay_records=0):
    """Compare the full pinned snapshot population, retaining bounded examples."""
    expected = []
    pin_problems = []
    for entry in (corpus_manifest or {}).get("entries") or []:
        slug = entry.get("event_slug")
        snapshot_ids = entry.get("snapshot_ids") or []
        if not isinstance(slug, str) or not slug or not isinstance(snapshot_ids, list):
            pin_problems.append("invalid event slug or snapshot ID list")
            continue
        label_problem = pinned_settlement_problem(entry)
        if label_problem:
            pin_problems.append(f"{slug}: {label_problem}")
        ids = [str(value) for value in snapshot_ids]
        if any(not isinstance(value, str) or not value for value in snapshot_ids):
            pin_problems.append(f"{slug}: invalid snapshot ID")
        expected.extend((slug, value) for value in ids)
        for field in ("replay_record_hashes", "tape_row_hashes"):
            hashes = entry.get(field)
            if (
                not isinstance(hashes, Mapping)
                or set(hashes) != set(ids)
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in hashes.values())
            ):
                pin_problems.append(f"{slug}: incomplete or invalid {field}")
    observed = [(row.get("event_slug"), row.get("snapshot_id")) for row in fidelity_rows]
    expected_counts = Counter(expected)
    observed_counts = Counter(observed)
    missing = sorted(expected_counts.keys() - observed_counts.keys())
    unexpected = sorted(observed_counts.keys() - expected_counts.keys(), key=str)
    return {
        "pinned": bool((corpus_manifest or {}).get("corpus_hash")),
        "expected_snapshot_count": len(expected),
        "observed_snapshot_count": len(observed),
        "missing_snapshot_count": len(missing),
        "unexpected_snapshot_count": len(unexpected),
        "duplicate_expected_snapshot_count": len(expected) - len(expected_counts),
        "duplicate_observed_snapshot_count": len(observed) - len(observed_counts),
        "duplicate_replay_record_count": duplicate_replay_records,
        "manifest_pin_problem_count": len(pin_problems),
        "manifest_pin_problems": pin_problems[:SUPPORT_EXAMPLE_LIMIT],
        "missing_snapshots": missing[:SUPPORT_EXAMPLE_LIMIT],
        "unexpected_snapshots": unexpected[:SUPPORT_EXAMPLE_LIMIT],
    }


def incumbent_control_validation(results):
    """Validate only an explicitly requested incumbent numerical reproduction."""
    support = results.get("fidelity_support") or {}
    fid = fidelity_summary(results.get("fidelity_rows") or [])
    reasons = []
    if not support.get("pinned"):
        reasons.append("a pinned corpus is required")
    expected = support.get("expected_snapshot_count", 0)
    if expected <= 0:
        reasons.append("the pinned control population is empty")
    for field in (
        "missing_snapshot_count", "unexpected_snapshot_count",
        "duplicate_expected_snapshot_count", "duplicate_observed_snapshot_count",
        "duplicate_replay_record_count", "manifest_pin_problem_count",
    ):
        if support.get(field, 0):
            reasons.append(f"{field}={support[field]}")
    if results.get("corpus_warnings"):
        reasons.append(f"corpus_pin_warnings={len(results['corpus_warnings'])}")
    for cohort in ("legacy_same_version", "changed_version", "reconstructed"):
        if fid[f"{cohort}_n"]:
            reasons.append(f"{cohort}_excluded={fid[f'{cohort}_n']}")
    if fid["same_identity_n"] != expected:
        reasons.append(f"exact_identity_controls={fid['same_identity_n']} expected={expected}")
    if not fid["same_identity_faithful"]:
        reasons.append(
            f"unfaithful_control: invalid={fid['same_identity_invalid_n']}, "
            f"above_l1_tolerance={fid['same_identity_above_tolerance_n']}"
        )
    return {
        "requested": True,
        "status": "FAIL" if reasons else "PASS",
        "claim": "pinned_incumbent_distribution_reproduction",
        "l1_tolerance": FIDELITY_FAITHFUL_L1,
        "reasons": reasons,
        "support": support,
    }


def fidelity_diagnostic(results):
    fid = results.get("fidelity") or fidelity_summary(results.get("fidelity_rows") or [])
    if fid.get("same_identity_faithful"):
        return (
            f"numerical fidelity FAITHFUL for {fid['same_identity_n']} exact-identity snapshot(s); "
            "runtime restoration and candidate improvement are not established"
        )
    if fid.get("same_identity_n"):
        return (
            f"FIDELITY WARNING: {fid.get('same_identity_invalid_n', 0)} invalid and "
            f"{fid.get('same_identity_above_tolerance_n', 0)} above-tolerance exact-identity snapshot(s)"
        )
    return "FIDELITY UNAVAILABLE: no exact-identity controls; changed/legacy rows are diagnostic"
