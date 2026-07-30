"""Generate fresh release-bound captured-input replay/serve parity rows.

The replay side is rebuilt from ``replay_inputs.jsonl`` plus the sibling
snapshot band context.  The served side is only a filtered projection of the
canonical live variant tape.  A served probability is never used to construct
a replay probability.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from weather.collection.live_variant_predictions import (
    build_live_variant_prediction_rows,
)
from weather.captured_input_hash import (
    CAPTURED_INPUT_HASH_ALGORITHM,
    captured_input_payload_sha256,
)
from weather.experiment_contract import finalize_self_hash
from weather.io import sha256_file, write_json_atomic
from weather.market.market_config import config_for_date
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import REPO_ROOT, data_path
from weather.release_artifacts import (
    DEFAULT_ACTIVE_RELEASE_POINTER,
    DEFAULT_RELEASES_ROOT,
    ReleaseArtifactVerificationError,
    canonical_payload_sha256,
    resolve_verified_active_release,
    strict_json_loads,
)
from weather.release_serving import (
    STATUS_BOUND,
    STATUS_RESEARCH_UNBOUND,
    ReleaseServingBindingError,
    VerifiedServingBundle,
    load_verified_active_serving_bundle,
)
from weather.reporting.scorecards.live_variant_settlement_scorecard import (
    authenticated_parity_envelope_rows,
    compare_replay_to_served,
)
from weather.schema_registry import schema_version


PARITY_SCHEMA_VERSION = schema_version("live_variant_settlement_scorecard")
REPLAY_INPUT_SCHEMA_VERSION = schema_version("replay_inputs")
EVIDENCE_HASH_FIELD = "evidence_sha256"
PARITY_BRANCH_SCENARIO = "captured_market_day"

DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_OUTPUT_ROOT = data_path("backtest", "captured_input_parity")
# Kept as compatibility aliases for callers that explicitly imported the
# original single-pair names.  New default writes use ``default_output_paths``
# so one market cannot replace another market's current evidence.
DEFAULT_SERVED_OUT = DEFAULT_OUTPUT_ROOT / "served_rows.json"
DEFAULT_REPLAY_OUT = DEFAULT_OUTPUT_ROOT / "replay_rows.json"

# One market-day is intentionally small.  The byte ceiling reserves at least
# four working copies (decoded input, normalized rows, replay rows, JSON output)
# inside a 768 MiB process budget on the 15.7 GiB capture host.
DEFAULT_MEMORY_CEILING_MIB = 768
MIN_MEMORY_CEILING_MIB = 256
MAX_MEMORY_CEILING_MIB = 2048
INPUT_MEMORY_FRACTION = 0.25
MAX_CAPTURED_RECORDS = 2_048
MAX_SNAPSHOT_RECORDS = 4_096
MAX_SERVED_ROWS = 65_536
MAX_REPLAY_ROWS = 65_536
MAX_BANDS_PER_SNAPSHOT = 256
MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_INPUT_AGE_HOURS = 48.0
FUTURE_CLOCK_SKEW_MINUTES = 5.0
BASE_DISTRIBUTION_L1_TOLERANCE = 1e-10


class CapturedInputParityEvidenceError(RuntimeError):
    """A fail-closed evidence-generation precondition was not satisfied."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        next_action: str,
        **context: Any,
    ) -> None:
        super().__init__(detail)
        self.code = str(code)
        self.detail = str(detail)
        self.next_action = str(next_action)
        self.context = dict(context)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "BLOCK",
            "code": self.code,
            "detail": self.detail,
            "next_action": self.next_action,
            **self.context,
        }


def default_output_paths(
    market_id: str,
    *,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> tuple[Path, Path]:
    """Return stable, non-overlapping current-evidence paths for one market."""

    market = str(market_id or "").strip()
    if (
        not market
        or market in {".", ".."}
        or "/" in market
        or "\\" in market
    ):
        raise ValueError("market_id is not safe for a stable evidence path")
    market_root = Path(output_root) / market
    return market_root / "served_rows.json", market_root / "replay_rows.json"


def _block(
    code: str,
    detail: str,
    *,
    next_action: str,
    **context: Any,
) -> CapturedInputParityEvidenceError:
    return CapturedInputParityEvidenceError(
        code,
        detail,
        next_action=next_action,
        **context,
    )


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(timezone.utc)


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise _block(
            "invalid_target_date",
            f"target date must be ISO YYYY-MM-DD: {value!r}",
            next_action="pass one explicit market-local target date",
        ) from exc


def _parse_timestamp(value: Any, *, field: str, source: str) -> datetime:
    if value in (None, ""):
        raise _block(
            "captured_input_timestamp_missing",
            f"{source} is missing required {field}",
            next_action="repair captured-input persistence before generating parity evidence",
            source=source,
            field=field,
        )
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _block(
            "captured_input_timestamp_invalid",
            f"{source} has invalid {field}: {value!r}",
            next_action="repair the malformed captured-input row; do not reconstruct it from served output",
            source=source,
            field=field,
        ) from exc
    if parsed.tzinfo is None:
        raise _block(
            "captured_input_timestamp_unzoned",
            f"{source} has timezone-naive {field}",
            next_action="persist an offset-aware captured timestamp before replay",
            source=source,
            field=field,
        )
    return parsed


def _require_fresh_timestamp(
    value: Any,
    *,
    now: datetime,
    max_age_hours: float,
    source: str,
) -> datetime:
    captured = _parse_timestamp(
        value,
        field="captured_at_utc",
        source=source,
    ).astimezone(timezone.utc)
    age_hours = (now - captured).total_seconds() / 3600.0
    if age_hours < -(FUTURE_CLOCK_SKEW_MINUTES / 60.0):
        raise _block(
            "captured_input_from_future",
            f"{source} is {abs(age_hours):.2f} hours in the future",
            next_action="repair host clock/capture timestamps, then recapture inputs",
            source=source,
            age_hours=age_hours,
        )
    if age_hours > max_age_hours:
        raise _block(
            "captured_inputs_stale",
            f"{source} is {age_hours:.2f} hours old (limit {max_age_hours:.2f})",
            next_action="run the bounded generator against fresh release-bound replay_inputs.jsonl",
            source=source,
            age_hours=age_hours,
            max_age_hours=float(max_age_hours),
        )
    return captured


def _require_regular_fresh_file(
    path: Path,
    *,
    now: datetime,
    max_age_hours: float,
    role: str,
) -> int:
    if not path.exists() or not path.is_file() or path.is_symlink():
        code = "captured_inputs_missing" if role == "captured inputs" else f"{role.replace(' ', '_')}_missing"
        raise _block(
            code,
            f"{role} must be an existing regular non-symlink file: {path}",
            next_action=(
                "wait for fresh replay_inputs.jsonl capture under the verified release"
                if role == "captured inputs"
                else f"restore the canonical {role} for this market-day"
            ),
            path=str(path),
        )
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age_hours = (now - modified).total_seconds() / 3600.0
    if age_hours < -(FUTURE_CLOCK_SKEW_MINUTES / 60.0):
        raise _block(
            f"{role.replace(' ', '_')}_from_future",
            f"{role} modification time is in the future: {path}",
            next_action="repair host clock/file timestamps before generating evidence",
            path=str(path),
            age_hours=age_hours,
        )
    if age_hours > max_age_hours:
        code = "captured_inputs_stale" if role == "captured inputs" else f"{role.replace(' ', '_')}_stale"
        raise _block(
            code,
            f"{role} file is {age_hours:.2f} hours old (limit {max_age_hours:.2f}): {path}",
            next_action=f"capture a fresh {role} file for this exact verified release",
            path=str(path),
            age_hours=age_hours,
            max_age_hours=float(max_age_hours),
        )
    return int(stat.st_size)


def _read_rows_strict(path: Path, *, role: str, max_rows: int) -> list[dict[str, Any]]:
    suffix = path.suffix.casefold()
    rows: list[dict[str, Any]] = []
    if suffix in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
                    raise _block(
                        f"{role.replace(' ', '_')}_line_too_large",
                        f"{role} line {line_number} exceeds the per-line byte ceiling",
                        next_action="repair or split the malformed source artifact",
                        path=str(path),
                        line_number=line_number,
                    )
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = strict_json_loads(
                        text,
                        label=f"{role} line {line_number}",
                    )
                except (json.JSONDecodeError, ReleaseArtifactVerificationError) as exc:
                    raise _block(
                        f"{role.replace(' ', '_')}_invalid_json",
                        f"{role} line {line_number} is invalid JSON: {exc}",
                        next_action="repair the canonical source artifact; do not skip malformed rows",
                        path=str(path),
                        line_number=line_number,
                    ) from exc
                if not isinstance(payload, Mapping):
                    raise _block(
                        f"{role.replace(' ', '_')}_invalid_row",
                        f"{role} line {line_number} is not a JSON object",
                        next_action="repair the canonical source artifact",
                        path=str(path),
                        line_number=line_number,
                    )
                rows.append(dict(payload))
                if len(rows) > max_rows:
                    raise _block(
                        "market_day_row_ceiling_exceeded",
                        f"{role} exceeds the one-market-day row ceiling ({max_rows})",
                        next_action="verify that the command targets exactly one market-day",
                        path=str(path),
                        max_rows=max_rows,
                    )
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(dict(row))
                if len(rows) > max_rows:
                    raise _block(
                        "market_day_row_ceiling_exceeded",
                        f"{role} exceeds the one-market-day row ceiling ({max_rows})",
                        next_action="verify that the command targets exactly one market-day",
                        path=str(path),
                        max_rows=max_rows,
                    )
    elif suffix == ".json":
        try:
            payload = strict_json_loads(
                path.read_text(encoding="utf-8-sig"),
                label=role,
            )
        except (json.JSONDecodeError, ReleaseArtifactVerificationError) as exc:
            raise _block(
                f"{role.replace(' ', '_')}_invalid_json",
                f"{role} is invalid JSON: {exc}",
                next_action="repair the canonical source artifact",
                path=str(path),
            ) from exc
        values = payload.get("rows") if isinstance(payload, Mapping) else payload
        if not isinstance(values, list) or any(not isinstance(row, Mapping) for row in values):
            raise _block(
                f"{role.replace(' ', '_')}_invalid_rows",
                f"{role} JSON must be an array or an object with a rows array",
                next_action="repair the canonical source artifact",
                path=str(path),
            )
        rows = [dict(row) for row in values]
        if len(rows) > max_rows:
            raise _block(
                "market_day_row_ceiling_exceeded",
                f"{role} exceeds the one-market-day row ceiling ({max_rows})",
                next_action="verify that the command targets exactly one market-day",
                path=str(path),
                max_rows=max_rows,
            )
    else:
        raise _block(
            f"{role.replace(' ', '_')}_format_unsupported",
            f"unsupported {role} format: {path}",
            next_action="use canonical JSONL, JSON, or CSV evidence",
            path=str(path),
        )
    return rows


def _plain_json(value: Any) -> Any:
    """Thaw verified mapping proxies without changing their values."""

    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(child) for child in value]
    return value


def _load_verified_bundle(
    *,
    pointer_path: Path,
    releases_root: Path,
    repo_root: Path,
    check_runtime: bool,
    bundle_loader: Callable[..., VerifiedServingBundle],
    binding_resolver: Callable[..., Mapping[str, Any]],
) -> tuple[VerifiedServingBundle, str]:
    try:
        bundle = bundle_loader(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=check_runtime,
        )
    except (ReleaseArtifactVerificationError, ReleaseServingBindingError, OSError) as exc:
        raise _block(
            "active_release_verification_failed",
            f"active release verification failed: {type(exc).__name__}: {exc}",
            next_action="repair the active pointer/release inventory and rerun verification",
            pointer_path=str(pointer_path),
        ) from exc
    if bundle.status == STATUS_RESEARCH_UNBOUND and not bundle.pointer_present:
        raise _block(
            "no_active_release_pointer",
            f"no active release pointer exists at {pointer_path}",
            next_action="promote a reviewed release through the existing release gates before generating evidence",
            pointer_path=str(pointer_path),
        )
    if bundle.status != STATUS_BOUND or not bundle.base_model_bound:
        raise _block(
            "active_release_verification_failed",
            f"active serving bundle is not fully bound: {bundle.status}: {bundle.reason}",
            next_action="repair and re-verify the complete active serving graph",
            pointer_path=str(pointer_path),
            bundle_status=bundle.status,
        )
    try:
        resolved = binding_resolver(
            pointer_path=pointer_path,
            releases_root=releases_root,
            repo_root=repo_root,
            check_runtime=check_runtime,
            served_artifact_paths=bundle.artifact_paths,
            served_route=_plain_json(bundle.route),
            require_served_bindings=True,
        )
    except (ReleaseArtifactVerificationError, OSError) as exc:
        raise _block(
            "serving_bundle_fingerprint_mismatch",
            f"verified serving bindings no longer match the active release: {type(exc).__name__}: {exc}",
            next_action="repair the serving role bindings and regenerate evidence from a freshly verified bundle",
        ) from exc
    if (
        str(resolved.get("release_id") or "") != bundle.release_id
        or str(resolved.get("manifest_sha256") or "") != bundle.manifest_sha256
    ):
        raise _block(
            "serving_bundle_fingerprint_mismatch",
            "bundle identity differs from the independently resolved served binding",
            next_action="restart with one unchanged verified active release pointer",
            bundle_release_id=bundle.release_id,
            resolved_release_id=resolved.get("release_id"),
        )
    fingerprint = str(resolved.get("served_binding_sha256") or "")
    if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
        raise _block(
            "serving_bundle_fingerprint_missing",
            "verified active release did not produce a valid served-binding SHA-256",
            next_action="repair release served-binding verification before generating parity evidence",
        )
    return bundle, fingerprint


def _verify_captured_record(
    row: Mapping[str, Any],
    *,
    source: str,
    event_slug: str,
    target_date: date,
    bundle: VerifiedServingBundle,
    serving_fingerprint: str,
    now: datetime,
    max_age_hours: float,
) -> dict[str, Any]:
    record = dict(row)
    if record.get("schema_version") != REPLAY_INPUT_SCHEMA_VERSION:
        raise _block(
            "captured_input_schema_not_release_bound",
            f"{source} uses {record.get('schema_version')!r}; {REPLAY_INPUT_SCHEMA_VERSION!r} is required",
            next_action="capture fresh v0.2 replay inputs under the verified active release",
            source=source,
        )
    if str(record.get("event_slug") or "") != event_slug or str(record.get("target_date") or "") != target_date.isoformat():
        raise _block(
            "mixed_market_day_captured_inputs",
            f"{source} does not belong to requested {event_slug} / {target_date.isoformat()}",
            next_action="point the command at exactly one market-day replay_inputs.jsonl",
            source=source,
            event_slug=record.get("event_slug"),
            target_date=record.get("target_date"),
        )
    _require_fresh_timestamp(
        record.get("captured_at_utc"),
        now=now,
        max_age_hours=max_age_hours,
        source=source,
    )
    expected_hash = captured_input_payload_sha256(record, persisted=True)
    if (
        record.get("captured_input_hash_algorithm") != CAPTURED_INPUT_HASH_ALGORITHM
        or str(record.get("captured_input_hash") or "") != expected_hash
    ):
        raise _block(
            "captured_input_self_hash_mismatch",
            f"{source} captured-input self-hash is missing or invalid",
            next_action="repair capture persistence and recapture; never derive this row from served predictions",
            source=source,
        )
    binding_checks = {
        "release_id": str(record.get("release_id") or "") == bundle.release_id,
        "release_manifest_sha256": str(record.get("release_manifest_sha256") or "") == bundle.manifest_sha256,
        "release_pointer_sha256": str(record.get("release_pointer_sha256") or "") == bundle.pointer_sha256,
        "release_sequence": record.get("release_sequence") == bundle.sequence,
        "release_identity_status": record.get("release_identity_status") == "verified_variant_serving_bundle",
        "base_model_release_bound": record.get("base_model_release_bound") is True,
        "serving_bundle_fingerprint_sha256": (
            not record.get("serving_bundle_fingerprint_sha256")
            or str(record.get("serving_bundle_fingerprint_sha256")) == serving_fingerprint
        ),
    }
    if not all(binding_checks.values()):
        raise _block(
            "serving_bundle_fingerprint_mismatch",
            f"{source} was not captured through the exact active verified serving bundle",
            next_action="collect fresh inputs after every worker is bound to the active release",
            source=source,
            failed_checks=sorted(name for name, passed in binding_checks.items() if not passed),
            expected_release_id=bundle.release_id,
            expected_manifest_sha256=bundle.manifest_sha256,
            expected_serving_bundle_fingerprint_sha256=serving_fingerprint,
        )
    if not isinstance(record.get("sources"), Mapping) or not record.get("sources"):
        raise _block(
            "captured_input_sources_missing",
            f"{source} contains no replayable captured sources",
            next_action="recapture the full serving inputs; do not substitute served prediction rows",
            source=source,
        )
    if not str(record.get("snapshot_id") or ""):
        raise _block(
            "captured_input_snapshot_id_missing",
            f"{source} has no snapshot_id",
            next_action="repair captured-input persistence before replay",
            source=source,
        )
    return record


def _index_snapshot_context(
    rows: Iterable[Mapping[str, Any]],
    *,
    snapshot_ids: set[str],
    event_slug: str,
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for raw in rows:
        snapshot_id = str(raw.get("snapshot_id") or "")
        if snapshot_id not in snapshot_ids:
            continue
        if str(raw.get("event_slug") or "") != event_slug:
            raise _block(
                "snapshot_context_market_day_mismatch",
                f"snapshot {snapshot_id} belongs to a different event slug",
                next_action="restore the exact sibling snapshots.jsonl for this replay corpus",
                snapshot_id=snapshot_id,
            )
        if snapshot_id in indexed:
            raise _block(
                "snapshot_context_duplicate",
                f"snapshots tape contains duplicate context for {snapshot_id}",
                next_action="repair the append-only snapshot tape before parity generation",
                snapshot_id=snapshot_id,
            )
        bands = raw.get("bands")
        if not isinstance(bands, list) or not bands or len(bands) > MAX_BANDS_PER_SNAPSHOT:
            raise _block(
                "snapshot_band_context_missing",
                f"snapshot {snapshot_id} has no bounded captured band context",
                next_action="restore the exact sibling snapshot row; never infer bands from served predictions",
                snapshot_id=snapshot_id,
                max_bands=MAX_BANDS_PER_SNAPSHOT,
            )
        if any(not isinstance(band, Mapping) for band in bands):
            raise _block(
                "snapshot_band_context_invalid",
                f"snapshot {snapshot_id} contains a non-object band row",
                next_action="repair the canonical snapshot tape",
                snapshot_id=snapshot_id,
            )
        indexed[snapshot_id] = dict(raw)
    missing = sorted(snapshot_ids - set(indexed))
    if missing:
        raise _block(
            "snapshot_context_missing",
            "captured replay inputs have no independent sibling snapshot band context",
            next_action="restore snapshots.jsonl for the captured inputs; do not copy bands or probabilities from the served tape",
            missing_snapshot_ids=missing[:20],
            missing_count=len(missing),
        )
    return indexed


def _distribution(recorded: Any) -> dict[int, float]:
    normalized: dict[int, float] = {}
    for bucket, probability in (recorded or {}).items():
        try:
            numeric_bucket = int(bucket)
            numeric_probability = float(probability)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric_probability):
            normalized[numeric_bucket] = numeric_probability
    return normalized


def _distribution_l1(left: Any, right: Any) -> float:
    first = _distribution(left)
    second = _distribution(right)
    return sum(abs(first.get(key, 0.0) - second.get(key, 0.0)) for key in set(first) | set(second))


def _build_model_payload(model_client: Any, record: Mapping[str, Any]) -> tuple[dict[str, Any], Any]:
    built_at = _parse_timestamp(
        record.get("built_at") or record.get("captured_at_local"),
        field="built_at",
        source=f"captured input {record.get('snapshot_id')}",
    )
    sources = dict(record.get("sources") or {})
    result = model_client.estimate_distribution_result(sources, now=built_at)
    distribution = dict(getattr(result, "distribution", {}) or {})
    recorded_distribution = record.get("recorded_distribution") or {}
    if not recorded_distribution:
        raise _block(
            "recorded_distribution_missing",
            f"captured input {record.get('snapshot_id')} has no serving fidelity canary",
            next_action="recapture complete release-bound replay inputs",
            snapshot_id=record.get("snapshot_id"),
        )
    l1 = _distribution_l1(distribution, recorded_distribution)
    if l1 > BASE_DISTRIBUTION_L1_TOLERANCE:
        raise _block(
            "serving_bundle_fingerprint_mismatch",
            f"verified-bundle base replay differs from the captured serving distribution (L1={l1:.12g})",
            next_action="verify worker code/release binding and recapture before generating parity evidence",
            snapshot_id=record.get("snapshot_id"),
            distribution_l1=l1,
            tolerance=BASE_DISTRIBUTION_L1_TOLERANCE,
        )
    history = model_client.source_data(sources, "wu_history") or {}
    cutoff_hour = model_client.effective_intraday_cutoff_hour(
        built_at,
        history.get("rows") or [],
    )
    model_version = model_client.get_model_version_string()
    feature_vector = model_client.live_feature_record(
        sources,
        cutoff_hour,
        captured_at=built_at,
        model_version=model_version,
    )
    model_payload = {
        "built_at": built_at.isoformat(),
        "sources": sources,
        "distribution": distribution,
        "distribution_components": dict(getattr(result, "component_payload", {}) or {}),
        "probability_calibration_context": dict(getattr(result, "calibration_context", {}) or {}),
        "active_model_kind": str(getattr(result, "active_model_kind", "") or "empirical"),
        "family_secondary_gate": dict(getattr(result, "family_secondary_gate", {}) or {}),
        "source_diagnostics": model_client.source_diagnostics(sources),
        "model_version": model_version,
        "feature_vector": dict(feature_vector or {}),
    }
    if not model_payload["feature_vector"]:
        raise _block(
            "captured_input_feature_replay_missing",
            f"verified serving replay produced no feature vector for {record.get('snapshot_id')}",
            next_action="repair exact release-bound feature replay before parity generation",
            snapshot_id=record.get("snapshot_id"),
        )
    return model_payload, built_at


def _number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return int(round(numeric)) if abs(numeric - round(numeric)) < 1e-9 else numeric


def _replayed_band_rows(
    model_client: Any,
    model_payload: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    calibration_context = model_payload.get("probability_calibration_context") or {}
    for raw in snapshot.get("bands") or []:
        band = dict(raw)
        value = _number(band.get("bin_value_c") if band.get("bin_value_c") not in (None, "") else band.get("bin_value"))
        value_hi = _number(
            band.get("bin_value_hi_c")
            if band.get("bin_value_hi_c") not in (None, "")
            else band.get("bin_value_hi")
        )
        if value_hi is None:
            value_hi = value
        kind = str(band.get("bin_kind") or "")
        if kind not in {"lte", "eq", "gte"} or value is None:
            raise _block(
                "snapshot_band_context_invalid",
                f"snapshot {snapshot.get('snapshot_id')} contains an invalid band identity",
                next_action="repair the canonical sibling snapshot band context",
                snapshot_id=snapshot.get("snapshot_id"),
            )
        bin_data = {
            "kind": kind,
            "value": value,
            "value_hi": value_hi,
            "label": band.get("range_label"),
            "market_yes": band.get("market_yes"),
            "market_no": band.get("market_no"),
        }
        probability = model_client.bin_probability(
            model_payload.get("distribution") or {},
            bin_data,
            calibration_context=calibration_context,
        )
        for field in (
            "variant_probability",
            "served_probability",
            "replay_probability",
            "artifact_hash",
            "postprocess_config_hash",
            "live_runtime",
        ):
            band.pop(field, None)
        band["bin_kind"] = kind
        band["bin_value_c"] = value
        band["bin_value_hi_c"] = value_hi
        band["model_probability"] = probability
        rows.append(band)
    return rows


def _trigger_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    trigger = record.get("trigger_context") or {}
    if not isinstance(trigger, Mapping):
        trigger = {}
    primary = trigger.get("primary_trigger") or {}
    if not isinstance(primary, Mapping):
        primary = {}
    previous_value = primary.get("previous_value")
    if previous_value is None:
        previous_value = trigger.get("previous_value")
    current_value = primary.get("current_value")
    if current_value is None:
        current_value = trigger.get("current_value")
    return {
        "trigger_reason": trigger.get("reason"),
        "trigger_source": primary.get("source") or trigger.get("source"),
        "trigger_previous_value": previous_value,
        "trigger_current_value": current_value,
        "trigger_observed_at": primary.get("observed_at") or trigger.get("observed_at"),
    }


def _runtime_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    identity = record.get("runtime_identity") or {}
    if not isinstance(identity, Mapping):
        identity = {}
    runtime_guard = record.get("runtime_guard") or {}
    if not isinstance(runtime_guard, Mapping):
        runtime_guard = {}
    return {
        "runtime_identity_schema_version": identity.get("schema_version"),
        "runtime_git_branch": identity.get("git_branch"),
        "runtime_git_commit": identity.get("git_commit"),
        "runtime_git_dirty": identity.get("git_dirty"),
        "runtime_dirty_fingerprint": identity.get("dirty_fingerprint"),
        "runtime_source_fingerprint": identity.get("source_fingerprint"),
        "runtime_code_state": runtime_guard.get("state"),
    }


def _verify_served_slice(
    rows: Iterable[Mapping[str, Any]],
    *,
    records_by_snapshot: Mapping[str, Mapping[str, Any]],
    event_slug: str,
    market_id: str,
    target_date: date,
    candidate_id: str,
    bundle: VerifiedServingBundle,
    serving_fingerprint: str,
    now: datetime,
    max_age_hours: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    by_snapshot: dict[str, int] = {snapshot_id: 0 for snapshot_id in records_by_snapshot}
    for raw in rows:
        snapshot_id = str(raw.get("snapshot_id") or "")
        if snapshot_id not in records_by_snapshot:
            continue
        source = f"served row {snapshot_id}/{raw.get('band_key') or raw.get('range_label')}"
        expected_input_hash = str(records_by_snapshot[snapshot_id].get("captured_input_hash") or "")
        checks = {
            "event_slug": str(raw.get("event_slug") or "") == event_slug,
            "market_id": str(raw.get("market_id") or "") == market_id,
            "target_date": str(raw.get("target_date") or "") == target_date.isoformat(),
            "candidate_id": str(raw.get("variant_id") or "") == candidate_id,
            "release_id": str(raw.get("release_id") or "") == bundle.release_id,
            "release_manifest_sha256": str(raw.get("release_manifest_sha256") or "") == bundle.manifest_sha256,
            "release_pointer_sha256": str(raw.get("release_pointer_sha256") or "") == bundle.pointer_sha256,
            "release_sequence": raw.get("release_sequence") == bundle.sequence,
            "release_identity_status": raw.get("release_identity_status") == "verified_variant_serving_bundle",
            "serving_model_binding_status": raw.get("serving_model_binding_status") == "verified_release_base_model",
            "captured_input_hash": str(raw.get("captured_input_hash") or "") == expected_input_hash,
            "serving_bundle_fingerprint_sha256": (
                not raw.get("serving_bundle_fingerprint_sha256")
                or str(raw.get("serving_bundle_fingerprint_sha256")) == serving_fingerprint
            ),
        }
        if not all(checks.values()):
            raise _block(
                "serving_bundle_fingerprint_mismatch",
                f"{source} does not bind the exact active serving graph/captured input",
                next_action="collect fresh served rows after all workers bind to the verified release",
                snapshot_id=snapshot_id,
                failed_checks=sorted(name for name, passed in checks.items() if not passed),
            )
        _require_fresh_timestamp(
            raw.get("captured_at_utc"),
            now=now,
            max_age_hours=max_age_hours,
            source=source,
        )
        row = dict(raw)
        row.update(
            {
                "parity_side": "served",
                "parity_branch_scenario": PARITY_BRANCH_SCENARIO,
                "serving_bundle_fingerprint_sha256": serving_fingerprint,
                "serving_bundle_fingerprint_evidence_source": (
                    "recomputed_verified_release_serving_bindings"
                ),
            }
        )
        selected.append(row)
        by_snapshot[snapshot_id] += 1
    missing = sorted(snapshot_id for snapshot_id, count in by_snapshot.items() if count == 0)
    if missing:
        raise _block(
            "served_tape_slice_missing",
            "captured inputs have no exact release-bound served prediction rows",
            next_action="wait for canonical served tape persistence; never fabricate served rows from replay",
            missing_snapshot_ids=missing[:20],
            missing_count=len(missing),
        )
    return selected


def _candidate_id(bundle: VerifiedServingBundle, market_id: str) -> str:
    markets = bundle.route.get("markets") if isinstance(bundle.route, Mapping) else None
    route = markets.get(market_id) if isinstance(markets, Mapping) else None
    candidate = str(route.get("candidate_variant_id") or "") if isinstance(route, Mapping) else ""
    if not candidate or route.get("decision") not in {"promote", "shadow"}:
        raise _block(
            "verified_release_market_route_missing",
            f"active verified release has no serving candidate route for {market_id!r}",
            next_action="repair the frozen market route and release verification",
            market_id=market_id,
        )
    return candidate


def _sort_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            str(row.get("snapshot_id") or ""),
            str(row.get("variant_id") or ""),
            str(row.get("band_key") or row.get("range_label") or ""),
        ),
    )


def _assert_output_paths_safe(
    *,
    served_out: Path,
    replay_out: Path,
    source_paths: Sequence[Path],
    bundle: VerifiedServingBundle,
    pointer_path: Path,
    releases_root: Path,
) -> None:
    resolved_served = served_out.expanduser().resolve(strict=False)
    resolved_replay = replay_out.expanduser().resolve(strict=False)
    resolved_sources = {path.expanduser().resolve(strict=False) for path in source_paths}
    resolved_pointer = pointer_path.expanduser().resolve(strict=False)
    if (
        resolved_served == resolved_replay
        or resolved_served in resolved_sources
        or resolved_replay in resolved_sources
        or resolved_served == resolved_pointer
        or resolved_replay == resolved_pointer
    ):
        raise _block(
            "evidence_output_collision",
            "served/replay outputs must be distinct and must not overwrite canonical input tapes or the active pointer",
            next_action="use dedicated captured-input parity evidence output paths",
        )
    release_dir = Path(bundle.release_dir).resolve(strict=False)
    protected_release_roots = {
        release_dir.parent,
        releases_root.expanduser().resolve(strict=False),
    }
    if any(
        resolved_served.is_relative_to(root)
        or resolved_replay.is_relative_to(root)
        for root in protected_release_roots
    ):
        raise _block(
            "serving_artifact_output_forbidden",
            "parity evidence outputs cannot be written inside the active-release store",
            next_action="write under data/backtest/captured_input_parity",
            releases_roots=sorted(str(root) for root in protected_release_roots),
        )


def _verify_bundle_files_unchanged(
    bundle: VerifiedServingBundle,
    *,
    pointer_path: Path,
) -> None:
    mismatches: list[str] = []
    try:
        if (
            not bundle.pointer_file_sha256
            or sha256_file(pointer_path) != bundle.pointer_file_sha256
        ):
            mismatches.append("active_release_pointer")
        for role, path in bundle.artifact_paths.items():
            expected = str(bundle.artifact_hashes.get(role) or "")
            if not expected or sha256_file(path) != expected:
                mismatches.append(str(role))
    except OSError as exc:
        raise _block(
            "serving_bundle_fingerprint_mismatch",
            f"serving binding became unreadable during generation: {type(exc).__name__}: {exc}",
            next_action="repair/re-verify the active release, then regenerate evidence",
        ) from exc
    if mismatches:
        raise _block(
            "serving_bundle_fingerprint_mismatch",
            "active pointer or serving artifact bytes changed during generation",
            next_action="restart with one stable verified active release and regenerate evidence",
            mismatched_roles=sorted(mismatches),
        )


def _envelope(
    *,
    side: str,
    rows: Sequence[Mapping[str, Any]],
    peer_rows_sha256: str,
    pair_sha256: str,
    generated_at_utc: str,
    market_id: str,
    target_date: date,
    event_slug: str,
    candidate_id: str,
    bundle: VerifiedServingBundle,
    serving_fingerprint: str,
    sources: Sequence[Mapping[str, str]],
    coverage_contract: Mapping[str, Any],
    memory_ceiling_mib: int,
    input_bytes: int,
) -> dict[str, Any]:
    row_set_sha256 = canonical_payload_sha256({"rows": list(rows)})
    return finalize_self_hash(
        {
            "schema_version": PARITY_SCHEMA_VERSION,
            "artifact_type": "captured_input_parity_evidence_rows",
            "status": "PASS",
            "side": side,
            "generated_at_utc": generated_at_utc,
            "market_id": market_id,
            "target_date": target_date.isoformat(),
            "event_slug": event_slug,
            "candidate_id": candidate_id,
            "release_id": bundle.release_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "release_pointer_sha256": bundle.pointer_sha256,
            "release_sequence": bundle.sequence,
            "serving_bundle_fingerprint_sha256": serving_fingerprint,
            "serving_bundle_fingerprint_evidence_source": (
                "recomputed_verified_release_serving_bindings"
            ),
            "captured_source_fingerprint_contract": (
                "optional_legacy_field_must_match_when_present; release_id_manifest_"
                "pointer_sequence_and_base_binding_are_required"
            ),
            "sources": [dict(source) for source in sources],
            "row_count": len(rows),
            "row_set_sha256": row_set_sha256,
            "peer_row_set_sha256": peer_rows_sha256,
            "pair_sha256": pair_sha256,
            "coverage_contract": dict(coverage_contract),
            "bounds": {
                "scope": "one_market_day",
                "memory_ceiling_mib": int(memory_ceiling_mib),
                "input_memory_fraction": INPUT_MEMORY_FRACTION,
                "input_bytes": int(input_bytes),
                "max_captured_records": MAX_CAPTURED_RECORDS,
                "max_snapshot_records": MAX_SNAPSHOT_RECORDS,
                "max_served_rows": MAX_SERVED_ROWS,
                "max_replay_rows": MAX_REPLAY_ROWS,
                "max_bands_per_snapshot": MAX_BANDS_PER_SNAPSHOT,
            },
            "rows": list(rows),
        },
        hash_field=EVIDENCE_HASH_FIELD,
    )


def generate_captured_input_parity_evidence(
    *,
    market_id: str,
    target_date: str | date,
    snapshots_root: str | Path = DEFAULT_SNAPSHOTS_ROOT,
    captured_inputs_path: str | Path | None = None,
    snapshot_tape_path: str | Path | None = None,
    served_tape_path: str | Path | None = None,
    served_out: str | Path | None = None,
    replay_out: str | Path | None = None,
    pointer_path: str | Path = DEFAULT_ACTIVE_RELEASE_POINTER,
    releases_root: str | Path = DEFAULT_RELEASES_ROOT,
    repo_root: str | Path = REPO_ROOT,
    check_runtime: bool = True,
    max_input_age_hours: float = DEFAULT_MAX_INPUT_AGE_HOURS,
    memory_ceiling_mib: int = DEFAULT_MEMORY_CEILING_MIB,
    now: datetime | None = None,
    bundle_loader: Callable[..., VerifiedServingBundle] = load_verified_active_serving_bundle,
    binding_resolver: Callable[..., Mapping[str, Any]] = resolve_verified_active_release,
    model_factory: Callable[..., Any] = TorontoHighTempModel,
) -> dict[str, Any]:
    """Generate one fresh, self-hashed replay/served evidence pair."""

    current = _utc_now(now)
    market = str(market_id or "").strip()
    if not market:
        raise _block(
            "market_id_missing",
            "one explicit market_id is required",
            next_action="pass --market-id for exactly one market-day",
        )
    day = _parse_date(target_date)
    if not math.isfinite(float(max_input_age_hours)) or max_input_age_hours <= 0 or max_input_age_hours > 48.0:
        raise ValueError("max_input_age_hours must be in (0, 48]")
    if not MIN_MEMORY_CEILING_MIB <= int(memory_ceiling_mib) <= MAX_MEMORY_CEILING_MIB:
        raise ValueError(
            f"memory_ceiling_mib must be between {MIN_MEMORY_CEILING_MIB} and {MAX_MEMORY_CEILING_MIB}"
        )

    config = config_for_date(day, market)
    event_slug = config.event_slug
    folder = Path(snapshots_root) / event_slug
    captured_path = Path(captured_inputs_path) if captured_inputs_path else folder / "replay_inputs.jsonl"
    snapshots_path = Path(snapshot_tape_path) if snapshot_tape_path else folder / "snapshots.jsonl"
    served_path = Path(served_tape_path) if served_tape_path else folder / "variant_predictions.jsonl"
    default_served, default_replay = default_output_paths(market)
    output_served = Path(served_out) if served_out is not None else default_served
    output_replay = Path(replay_out) if replay_out is not None else default_replay
    pointer = Path(pointer_path)
    releases = Path(releases_root)
    repository = Path(repo_root)

    bundle, serving_fingerprint = _load_verified_bundle(
        pointer_path=pointer,
        releases_root=releases,
        repo_root=repository,
        check_runtime=check_runtime,
        bundle_loader=bundle_loader,
        binding_resolver=binding_resolver,
    )
    candidate_id = _candidate_id(bundle, market)
    source_paths = (captured_path, snapshots_path, served_path)
    sizes = [
        _require_regular_fresh_file(
            path,
            now=current,
            max_age_hours=float(max_input_age_hours),
            role=role,
        )
        for path, role in zip(
            source_paths,
            ("captured inputs", "snapshot tape", "served tape"),
        )
    ]
    total_input_bytes = sum(sizes)
    input_byte_ceiling = int(memory_ceiling_mib * 1024 * 1024 * INPUT_MEMORY_FRACTION)
    if total_input_bytes > input_byte_ceiling:
        raise _block(
            "memory_input_ceiling_exceeded",
            f"one market-day inputs total {total_input_bytes} bytes (ceiling {input_byte_ceiling})",
            next_action="verify the target is one market-day or choose a reviewed larger bounded budget",
            total_input_bytes=total_input_bytes,
            input_byte_ceiling=input_byte_ceiling,
            memory_ceiling_mib=int(memory_ceiling_mib),
        )
    _assert_output_paths_safe(
        served_out=output_served,
        replay_out=output_replay,
        source_paths=source_paths,
        bundle=bundle,
        pointer_path=pointer,
        releases_root=releases,
    )
    source_hashes = {path: sha256_file(path) for path in source_paths}

    raw_captured = _read_rows_strict(
        captured_path,
        role="captured inputs",
        max_rows=MAX_CAPTURED_RECORDS,
    )
    if not raw_captured:
        raise _block(
            "captured_inputs_missing",
            f"captured-input file contains no rows: {captured_path}",
            next_action="wait for fresh release-bound replay input capture",
            path=str(captured_path),
        )
    records = [
        _verify_captured_record(
            row,
            source=f"{captured_path}:{line_number}",
            event_slug=event_slug,
            target_date=day,
            bundle=bundle,
            serving_fingerprint=serving_fingerprint,
            now=current,
            max_age_hours=float(max_input_age_hours),
        )
        for line_number, row in enumerate(raw_captured, start=1)
    ]
    records_by_snapshot: dict[str, dict[str, Any]] = {}
    for record in records:
        snapshot_id = str(record["snapshot_id"])
        if snapshot_id in records_by_snapshot:
            raise _block(
                "captured_input_snapshot_duplicate",
                f"captured inputs contain duplicate snapshot_id {snapshot_id}",
                next_action="repair the canonical replay input tape before parity generation",
                snapshot_id=snapshot_id,
            )
        records_by_snapshot[snapshot_id] = record

    raw_snapshots = _read_rows_strict(
        snapshots_path,
        role="snapshot tape",
        max_rows=MAX_SNAPSHOT_RECORDS,
    )
    snapshots_by_id = _index_snapshot_context(
        raw_snapshots,
        snapshot_ids=set(records_by_snapshot),
        event_slug=event_slug,
    )
    band_context_hashes = {
        snapshot_id: canonical_payload_sha256(
            {
                "snapshot_id": snapshot_id,
                "bands": snapshot.get("bands") or [],
            }
        )
        for snapshot_id, snapshot in snapshots_by_id.items()
    }
    raw_served = _read_rows_strict(
        served_path,
        role="served tape",
        max_rows=MAX_SERVED_ROWS,
    )
    served_rows = _verify_served_slice(
        raw_served,
        records_by_snapshot=records_by_snapshot,
        event_slug=event_slug,
        market_id=market,
        target_date=day,
        candidate_id=candidate_id,
        bundle=bundle,
        serving_fingerprint=serving_fingerprint,
        now=current,
        max_age_hours=float(max_input_age_hours),
    )
    for row in served_rows:
        row["captured_band_context_sha256"] = band_context_hashes[
            str(row.get("snapshot_id") or "")
        ]

    replay_rows: list[dict[str, Any]] = []
    try:
        model_client = model_factory(
            target_date=day,
            market_id=market,
            serving_bundle=bundle,
        )
    except Exception as exc:  # noqa: BLE001 - convert binding failure to an evidence block
        raise _block(
            "release_bound_model_construction_failed",
            f"cannot construct the exact release-bound base model: {type(exc).__name__}: {exc}",
            next_action="repair the verified base-model serving graph before replay",
            market_id=market,
        ) from exc
    for snapshot_id in sorted(records_by_snapshot):
        record = records_by_snapshot[snapshot_id]
        snapshot = snapshots_by_id[snapshot_id]
        try:
            model_payload, _built_at = _build_model_payload(model_client, record)
            captured_at = _parse_timestamp(
                record.get("captured_at_local") or record.get("captured_at_utc"),
                field="captured_at_local",
                source=f"captured input {snapshot_id}",
            )
            band_rows = _replayed_band_rows(model_client, model_payload, snapshot)
            generated = build_live_variant_prediction_rows(
                snapshot_id=snapshot_id,
                captured_at=captured_at,
                event={"updatedAt": snapshot.get("event_updated_at")},
                model=model_payload,
                model_client=model_client,
                band_rows=band_rows,
                event_slug=event_slug,
                market_id=market,
                target_date=day,
                serving_model_version=str(model_payload.get("model_version") or ""),
                captured_input_hash=str(record.get("captured_input_hash") or ""),
                runtime_fields=_runtime_fields(record),
                snapshot_cadence=str(record.get("snapshot_cadence") or "scheduled"),
                cadence_quality=(
                    dict(record.get("snapshot_cadence_quality") or {})
                    if isinstance(record.get("snapshot_cadence_quality"), Mapping)
                    else {}
                ),
                trigger_summary=_trigger_summary(record),
                serving_bundle=bundle,
            )
        except CapturedInputParityEvidenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert replay into an actionable block
            raise _block(
                "replay_execution_failed",
                f"exact verified-bundle replay failed for {snapshot_id}: {type(exc).__name__}: {exc}",
                next_action="repair the release-bound serving runtime/captured inputs, then retry this market-day",
                snapshot_id=snapshot_id,
            ) from exc
        if not generated:
            raise _block(
                "replay_prediction_rows_missing",
                f"verified serving bundle produced no replay rows for {snapshot_id}",
                next_action="repair the frozen market route/band context before parity generation",
                snapshot_id=snapshot_id,
            )
        for row in generated:
            row.update(
                {
                    "parity_side": "replay",
                    "parity_branch_scenario": PARITY_BRANCH_SCENARIO,
                    "serving_bundle_fingerprint_sha256": serving_fingerprint,
                    "serving_bundle_fingerprint_evidence_source": (
                        "recomputed_verified_release_serving_bindings"
                    ),
                    "captured_band_context_sha256": band_context_hashes[snapshot_id],
                }
            )
            replay_rows.append(row)
            if len(replay_rows) > MAX_REPLAY_ROWS:
                raise _block(
                    "market_day_row_ceiling_exceeded",
                    f"replay output exceeds the one-market-day row ceiling ({MAX_REPLAY_ROWS})",
                    next_action="verify that the command targets exactly one market-day",
                    max_rows=MAX_REPLAY_ROWS,
                )

    served_rows = _sort_rows(served_rows)
    replay_rows = _sort_rows(replay_rows)
    band_counts = {
        len({str(row.get("band_key") or row.get("range_label") or "") for row in rows})
        for rows in (
            [row for row in replay_rows if str(row.get("snapshot_id") or "") == snapshot_id]
            for snapshot_id in sorted(records_by_snapshot)
        )
    }
    if len(band_counts) != 1 or not band_counts or next(iter(band_counts)) <= 0:
        raise _block(
            "market_day_band_contract_inconsistent",
            "replayed snapshots do not share one complete market band contract",
            next_action="repair the market-day snapshot band context before generating parity evidence",
            observed_band_counts=sorted(band_counts),
        )
    expected_band_count = next(iter(band_counts))
    coverage_contract = finalize_self_hash(
        {
            "candidate_id": candidate_id,
            "expected_market_ids": [market],
            "expected_branch_scenarios": [PARITY_BRANCH_SCENARIO],
            "expected_band_count_by_market": {market: expected_band_count},
        },
        hash_field="coverage_contract_sha256",
    )
    for row in [*served_rows, *replay_rows]:
        row["parity_coverage_contract"] = dict(coverage_contract)
    generated_at_utc = current.isoformat()
    parity = compare_replay_to_served(
        served_rows,
        replay_rows,
        generated_at_utc=generated_at_utc,
        served_source=str(served_path),
        replay_source=str(captured_path),
    )
    if parity.get("status") != "PASS":
        first = parity.get("first_mismatch") or {}
        raise _block(
            "generated_parity_blocked",
            f"independently replayed rows do not match served tape: {first.get('code')}: {first.get('detail')}",
            next_action="inspect worker/release binding and capture fresh inputs; never copy served rows into replay evidence",
            parity_first_mismatch=first,
            parity_sha256=parity.get("parity_sha256"),
        )

    changed_sources = [
        str(path)
        for path, expected_sha256 in source_hashes.items()
        if sha256_file(path) != expected_sha256
    ]
    if changed_sources:
        raise _block(
            "captured_evidence_changed_during_generation",
            "one or more append-only input tapes changed while parity was generated",
            next_action="retry the bounded market-day command after the current capture write completes",
            changed_sources=changed_sources,
        )
    _verify_bundle_files_unchanged(bundle, pointer_path=pointer)

    served_row_sha = canonical_payload_sha256({"rows": served_rows})
    replay_row_sha = canonical_payload_sha256({"rows": replay_rows})
    pair_sha = canonical_payload_sha256(
        {
            "release_id": bundle.release_id,
            "release_manifest_sha256": bundle.manifest_sha256,
            "serving_bundle_fingerprint_sha256": serving_fingerprint,
            "market_id": market,
            "target_date": day.isoformat(),
            "served_row_set_sha256": served_row_sha,
            "replay_row_set_sha256": replay_row_sha,
        }
    )
    served_envelope = _envelope(
        side="served",
        rows=served_rows,
        peer_rows_sha256=replay_row_sha,
        pair_sha256=pair_sha,
        generated_at_utc=generated_at_utc,
        market_id=market,
        target_date=day,
        event_slug=event_slug,
        candidate_id=candidate_id,
        bundle=bundle,
        serving_fingerprint=serving_fingerprint,
        sources=(
            {"path": str(served_path), "sha256": source_hashes[served_path]},
        ),
        coverage_contract=coverage_contract,
        memory_ceiling_mib=int(memory_ceiling_mib),
        input_bytes=total_input_bytes,
    )
    replay_envelope = _envelope(
        side="replay",
        rows=replay_rows,
        peer_rows_sha256=served_row_sha,
        pair_sha256=pair_sha,
        generated_at_utc=generated_at_utc,
        market_id=market,
        target_date=day,
        event_slug=event_slug,
        candidate_id=candidate_id,
        bundle=bundle,
        serving_fingerprint=serving_fingerprint,
        sources=(
            {"path": str(captured_path), "sha256": source_hashes[captured_path]},
            {"path": str(snapshots_path), "sha256": source_hashes[snapshots_path]},
        ),
        coverage_contract=coverage_contract,
        memory_ceiling_mib=int(memory_ceiling_mib),
        input_bytes=total_input_bytes,
    )
    try:
        authenticated_parity = compare_replay_to_served(
            authenticated_parity_envelope_rows(
                served_envelope,
                source=f"in-memory served envelope for {market}/{day.isoformat()}",
            ),
            authenticated_parity_envelope_rows(
                replay_envelope,
                source=f"in-memory replay envelope for {market}/{day.isoformat()}",
            ),
            generated_at_utc=generated_at_utc,
            served_source=str(served_path),
            replay_source=str(captured_path),
        )
    except ValueError as exc:
        raise _block(
            "generated_parity_envelope_invalid",
            f"generated authenticated parity envelope is invalid: {exc}",
            next_action="repair generator envelope construction before publishing evidence",
        ) from exc
    if authenticated_parity.get("status") != "PASS":
        first = authenticated_parity.get("first_mismatch") or {}
        raise _block(
            "generated_authenticated_parity_blocked",
            (
                "generated pair fails the exact persisted comparator: "
                f"{first.get('code')}: {first.get('detail')}"
            ),
            next_action=(
                "repair served/replay metadata reconstruction and regenerate; "
                "do not publish a pair the parity preflight would block"
            ),
            parity_first_mismatch=first,
            parity_sha256=authenticated_parity.get("parity_sha256"),
        )
    # Both envelopes are complete and self-hashed before either stable path is
    # replaced.  A partial replace cannot pass comparison because pair/row hashes
    # and generated rows are release-bound independently.
    write_json_atomic(output_served, served_envelope, trailing_newline=True)
    write_json_atomic(output_replay, replay_envelope, trailing_newline=True)
    return {
        "status": "PASS",
        "market_id": market,
        "target_date": day.isoformat(),
        "event_slug": event_slug,
        "candidate_id": candidate_id,
        "release_id": bundle.release_id,
        "release_manifest_sha256": bundle.manifest_sha256,
        "serving_bundle_fingerprint_sha256": serving_fingerprint,
        "served_out": str(output_served),
        "replay_out": str(output_replay),
        "served_evidence_sha256": served_envelope[EVIDENCE_HASH_FIELD],
        "replay_evidence_sha256": replay_envelope[EVIDENCE_HASH_FIELD],
        "pair_sha256": pair_sha,
        "served_row_count": len(served_rows),
        "replay_row_count": len(replay_rows),
        "captured_input_count": len(records),
        "coverage_contract": coverage_contract,
        "memory_ceiling_mib": int(memory_ceiling_mib),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one bounded market-day of independently replayed and served "
            "captured-input parity evidence under a verified active release."
        )
    )
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--target-date", required=True, help="Market-local YYYY-MM-DD")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--captured-inputs", default="")
    parser.add_argument("--snapshot-tape", default="")
    parser.add_argument("--served-tape", default="")
    parser.add_argument(
        "--served-out",
        default="",
        help="Override the stable <output-root>/<market>/served_rows.json path",
    )
    parser.add_argument(
        "--replay-out",
        default="",
        help="Override the stable <output-root>/<market>/replay_rows.json path",
    )
    parser.add_argument("--active-release-pointer", default=str(DEFAULT_ACTIVE_RELEASE_POINTER))
    parser.add_argument("--releases-root", default=str(DEFAULT_RELEASES_ROOT))
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--max-input-age-hours", type=float, default=DEFAULT_MAX_INPUT_AGE_HOURS)
    parser.add_argument("--memory-ceiling-mib", type=int, default=DEFAULT_MEMORY_CEILING_MIB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = generate_captured_input_parity_evidence(
            market_id=args.market_id,
            target_date=args.target_date,
            snapshots_root=args.snapshots_root,
            captured_inputs_path=args.captured_inputs or None,
            snapshot_tape_path=args.snapshot_tape or None,
            served_tape_path=args.served_tape or None,
            served_out=args.served_out or None,
            replay_out=args.replay_out or None,
            pointer_path=args.active_release_pointer,
            releases_root=args.releases_root,
            repo_root=args.repo_root,
            check_runtime=True,
            max_input_age_hours=args.max_input_age_hours,
            memory_ceiling_mib=args.memory_ceiling_mib,
        )
    except CapturedInputParityEvidenceError as exc:
        print(json.dumps(exc.as_dict(), indent=2, sort_keys=True), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - operational CLI must fail closed
        print(
            json.dumps(
                {
                    "status": "BLOCK",
                    "code": "captured_input_parity_generation_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "next_action": (
                        "repair the reported verified-release/captured-input problem; "
                        "do not reuse this invocation as fresh parity evidence"
                    ),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CapturedInputParityEvidenceError",
    "DEFAULT_MEMORY_CEILING_MIB",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_REPLAY_OUT",
    "DEFAULT_SERVED_OUT",
    "default_output_paths",
    "generate_captured_input_parity_evidence",
    "main",
]
