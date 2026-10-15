"""Outcome-blind capture tape for the t3-r3 stage ``remaining_rise_floor_v1``.

One row per served snapshot goes to
``snapshots/<event>/remaining_rise_floor_shadow.jsonl``: a dedicated tape, never a
``live_variant_predictions`` variant, mirroring the MG-1 tape design. The row
records every stage input (the captured 81a floor inputs, the cell key, the METAR
stale flag and freshness, the band grid, the served vector it would replace),
the stage vector, and the bindings (stage id, config, code and artifact hashes,
release id) the pre-registration's validity conditions read.

The tape is shadow-only. It never changes a served byte: the builder reads the
already-built served long rows and never mutates them. It never joins outcomes:
this module and ``weather.model.remaining_rise_floor`` import no settlement,
panel or scoring loader. ``replay_row`` recomputes a stored row's stage vector
from the row alone and the frozen artifact (the §8 replay validity condition).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from weather.model import remaining_rise_floor as stage
from weather.schema_registry import schema_version

SCHEMA_NAME = "remaining_rise_floor_shadow"
SCHEMA_VERSION = schema_version(SCHEMA_NAME)
TAPE_FILENAME = "remaining_rise_floor_shadow.jsonl"
METAR_SOURCE = "metar"

STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _date_text(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10] if value else None


def _spec(model_client: Any) -> Any:
    return getattr(model_client, "spec", None)


def _unit(model_client: Any) -> str | None:
    unit = getattr(_spec(model_client), "display_unit", None)
    return str(unit).upper() if unit else None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def metar_state(item: Any, captured_at: datetime) -> dict[str, Any]:
    """Stale flag and freshness of the captured METAR source (outcome-blind diagnostics)."""

    item = item if isinstance(item, Mapping) else {}
    data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    times = [t for t in (_parse_utc(row.get("obs_time")) for row in rows if isinstance(row, Mapping)) if t]
    newest = max(times) if times else None
    age = (captured_at.astimezone(timezone.utc) - newest).total_seconds() / 60.0 if newest else None
    return {
        "present": bool(item),
        "ok": bool(item.get("ok")),
        "stale": bool(item.get("stale")),
        "rows": len(rows),
        "newest_obs_time_utc": newest.isoformat() if newest else None,
        "newest_age_minutes": age,
        "newest_after_capture": bool(age is not None and age < 0),
    }


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
        "artifact_id": stage.ARTIFACT_ID,
    }


def _bands_and_served(band_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict], list[float | None]]:
    bands, served = [], []
    for band_row in band_rows:
        bands.append({
            "kind": band_row.get("bin_kind"),
            "low": band_row.get("bin_value_c"),
            "high": band_row.get("bin_value_hi_c"),
            "label": band_row.get("range_label"),
        })
        value = band_row.get("model_probability")
        served.append(None if value is None else float(value))
    return bands, served


def _tape_band_rows(bands: Sequence[Mapping[str, Any]]) -> list[dict]:
    return [{"bin_kind": b.get("kind"), "bin_value_c": b.get("low"), "bin_value_hi_c": b.get("high")} for b in bands]


def _compute(row: dict[str, Any], table: stage.RiseTable | None) -> dict[str, Any]:
    """Fill status/reason/floor_bucket/stage_vector from the inputs already on ``row``."""

    def skipped(reason: str) -> dict[str, Any]:
        row.update({"status": STATUS_SKIPPED, "reason": reason, "floor_bucket": None, "stage_vector": None})
        return row

    served = row["served_vector"]
    if not row["bands"]:
        return skipped("no_bands")
    if any(value is None for value in served):
        return skipped("served_vector_incomplete")
    try:
        bands = [stage.band_from_row(band_row) for band_row in _tape_band_rows(row["bands"])]
    except ValueError as exc:
        return skipped(str(exc))
    key = row["cell_key"]
    cell = table.cell(key.get("station"), key.get("month"), key.get("hour")) if table is not None else None
    result = stage.apply(
        bands,
        served,
        floor=row["floor"],
        cell=cell,
        metar_stale=bool(row["metar"].get("stale")),
        on_target_date=bool(key.get("on_target_date")),
        artifact_sha256=row["artifact_sha256"],
        unit=row.get("unit") or "",
    )
    row.update({
        "cell": cell.key() if cell is not None else None,
        "status": result.status,
        "reason": result.reason,
        "floor_bucket": result.floor_bucket,
        "stage_vector": list(result.vector),
    })
    return row


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
    table: stage.RiseTable | None = None,
) -> dict[str, Any]:
    """Build the single shadow row for one snapshot.

    Reads only captured inputs (the floor fields, the METAR source item's stale
    flag and row times, the served long rows) and the frozen artifact. Never
    mutates them. Raises only on a programming error; the caller turns any
    exception into an error row.
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
    if table is None:
        try:
            table = stage.load_table()
        except (OSError, ValueError):
            table = None
    spec = _spec(model_client)
    features = model.get("feature_vector") or {}
    sources = model.get("sources") or {}
    key = stage.cell_key(
        getattr(spec, "icao", None),
        getattr(spec, "timezone", None),
        captured_at,
        _date_text(target_date) or "",
    )
    bands, served = _bands_and_served(band_rows)
    row.update({
        "artifact_sha256": table.sha256 if table is not None else None,
        "floor_inputs": {name: features.get(name) for name in stage.FLOOR_FIELDS},
        "floor": stage.floor_value(features),
        "metar": metar_state(sources.get(METAR_SOURCE), captured_at),
        "cell_key": key.to_dict(),
        "bands": bands,
        "served_vector": served,
    })
    return _compute(row, table)


def replay_row(row: Mapping[str, Any], table: stage.RiseTable) -> list[float] | None:
    """Recompute a stored row's stage vector from the row's own inputs and the artifact."""

    if row.get("status") in {STATUS_ERROR, None}:
        return None
    copy = {key: row.get(key) for key in (
        "unit", "artifact_sha256", "floor_inputs", "metar", "cell_key", "bands", "served_vector",
    )}
    copy["floor"] = stage.floor_value(copy["floor_inputs"])
    copy["metar"] = copy["metar"] or {}
    copy["cell_key"] = copy["cell_key"] or {}
    copy["bands"] = copy["bands"] or []
    copy["served_vector"] = copy["served_vector"] or []
    return _compute(copy, table).get("stage_vector")


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
