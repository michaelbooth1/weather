"""Outcome-blind capture tape for the MG-1 stage ``nbm_v2_guidance_read_v1``.

One row per served snapshot goes to ``snapshots/<event>/nbm_guidance_read_shadow.jsonl``
(owner Q3, 2026-10-08: a dedicated tape, never a ``live_variant_predictions``
variant). The row records the parser-v2 read, the captured 81a floor, the band
grid, the stage vector and the served vector it would replace, bound to the
stage id and the config and code hashes (owner Q1).

The tape is shadow-only. It never changes a served byte: the builder reads the
already-built served long rows and never mutates them. It never joins outcomes:
this module and ``weather.model.nbm_guidance_read`` import no settlement, panel,
or scoring loader, and an architecture ratchet keeps it that way. Scoring
against settlement is a later, separately pre-registered step (MG-1 §1, D0).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from weather.model import nbm_guidance_read as stage
from weather.schema_registry import schema_version

SCHEMA_NAME = "nbm_guidance_read_shadow"
SCHEMA_VERSION = schema_version(SCHEMA_NAME)
TAPE_FILENAME = "nbm_guidance_read_shadow.jsonl"
SOURCE_NAME = "nbm_probabilistic_tmax"

STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _date_text(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10] if value else None


def _unit(model_client: Any) -> str | None:
    spec = getattr(model_client, "spec", None)
    unit = getattr(spec, "display_unit", None)
    return str(unit).upper() if unit else None


def base_row(
    *,
    snapshot_id: str,
    captured_at: datetime,
    event_slug: str,
    market_id: Any,
    target_date: Any,
    unit: str | None,
    captured_input_hash: str,
    runtime_fields: Mapping[str, Any] | None,
    release_lineage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Identity and binding fields every row carries, including error rows."""

    runtime_fields = runtime_fields or {}
    release_lineage = release_lineage or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "captured_at_utc": _iso_utc(captured_at),
        "event_slug": event_slug,
        "market_id": market_id,
        "target_date": _date_text(target_date),
        "unit": unit,
        "captured_input_hash": captured_input_hash or "",
        "runtime_git_commit": runtime_fields.get("runtime_git_commit"),
        "runtime_source_fingerprint": runtime_fields.get("runtime_source_fingerprint"),
        "release_id": release_lineage.get("release_id") or "",
        "release_identity_status": release_lineage.get("release_identity_status"),
        "stage_id": stage.STAGE_ID,
        "stage_config_sha256": stage.stage_config_sha256(),
        "stage_code_sha256": stage.stage_code_sha256(),
    }


def build_row(
    *,
    snapshot_id: str,
    captured_at: datetime,
    event_slug: str,
    market_id: Any,
    target_date: Any,
    model: Mapping[str, Any],
    model_client: Any,
    band_rows: Sequence[Mapping[str, Any]],
    captured_input_hash: str,
    runtime_fields: Mapping[str, Any] | None = None,
    release_lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the single shadow row for one snapshot.

    Reads only captured inputs (the source item, the feature vector floor
    fields, the served long rows). Never mutates them. Raises only on a
    programming error; the caller turns any exception into an error row.
    """

    unit = _unit(model_client)
    row = base_row(
        snapshot_id=snapshot_id,
        captured_at=captured_at,
        event_slug=event_slug,
        market_id=market_id,
        target_date=target_date,
        unit=unit,
        captured_input_hash=captured_input_hash,
        runtime_fields=runtime_fields,
        release_lineage=release_lineage,
    )
    sources = model.get("sources") or {}
    features = model.get("feature_vector") or {}
    read = stage.read_v2(sources.get(SOURCE_NAME), captured_at, _date_text(target_date) or "")
    floor = stage.floor_value(features)
    row.update({
        "read": read.to_dict(),
        "pit_violation": bool(read.pit_violation),
        "floor_inputs": {name: features.get(name) for name in stage.FLOOR_FIELDS},
        "floor": floor,
    })

    band_dicts: list[dict[str, Any]] = []
    served: list[float | None] = []
    for band_row in band_rows:
        band_dicts.append({
            "kind": band_row.get("bin_kind"),
            "low": band_row.get("bin_value_c"),
            "high": band_row.get("bin_value_hi_c"),
            "label": band_row.get("range_label"),
        })
        value = band_row.get("model_probability")
        served.append(None if value is None else float(value))
    row["bands"] = band_dicts
    row["served_vector"] = served

    def skipped(reason: str) -> dict[str, Any]:
        row.update({
            "status": STATUS_SKIPPED,
            "reason": reason,
            "floor_bucket": None,
            "sigma": None,
            "stage_vector": None,
        })
        return row

    if not band_rows:
        return skipped("no_bands")
    if any(value is None for value in served):
        return skipped("served_vector_incomplete")
    try:
        bands = [stage.band_from_row(band_row) for band_row in band_rows]
    except ValueError as exc:
        return skipped(str(exc))

    result = stage.apply(bands, served, read, floor, unit=unit or "")
    row.update({
        "status": result.status,
        "reason": result.reason,
        "floor_bucket": result.floor_bucket,
        "sigma": result.sigma,
        "stage_vector": list(result.vector),
    })
    return row


def error_row(exc: BaseException, **identity: Any) -> dict[str, Any]:
    """A row recording that the builder failed; serving is never affected."""

    try:
        row = base_row(**identity)
    except Exception:  # noqa: BLE001 - the error row must always be writable
        row = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": identity.get("snapshot_id"),
            "stage_id": stage.STAGE_ID,
        }
    row.update({
        "status": STATUS_ERROR,
        "reason": f"{type(exc).__name__}: {exc}",
        "stage_vector": None,
    })
    return row
