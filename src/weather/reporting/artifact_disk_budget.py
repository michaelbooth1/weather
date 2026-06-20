"""Disk-headroom checks for generated reporting artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path


DEFAULT_ARTIFACT_EXPORT_MIN_FREE_BYTES = 1_000_000_000
DEFAULT_ROW_EXPORT_BYTES_PER_ROW = 1024


def ensure_artifact_disk_headroom(
    path: str | Path | None,
    estimated_bytes: int | float = 0,
    min_free_bytes: int | float = 0,
    context: str = "artifact export",
) -> dict[str, int | str] | None:
    """Fail before writing generated artifacts when the target volume is low."""
    if not path or not min_free_bytes:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path.parent)
    estimated = int(max(0, estimated_bytes))
    required_free = int(min_free_bytes) + estimated
    if usage.free < required_free:
        raise OSError(
            f"insufficient disk headroom for {context} {path}: "
            f"free_bytes={usage.free}, required_free_bytes={required_free}, "
            f"min_free_bytes={int(min_free_bytes)}, "
            f"estimated_export_bytes={estimated}"
        )
    return {
        "path": str(path),
        "free_bytes": int(usage.free),
        "required_free_bytes": int(required_free),
        "min_free_bytes": int(min_free_bytes),
        "estimated_export_bytes": int(estimated),
    }


def ensure_row_export_disk_headroom(
    path: str | Path | None,
    row_count: int | float,
    min_free_bytes: int | float = 0,
    bytes_per_row: int | float = DEFAULT_ROW_EXPORT_BYTES_PER_ROW,
    context: str = "row export",
) -> dict[str, int | str] | None:
    """Estimate row-oriented output size and require configured free headroom."""
    rows = int(max(0, row_count))
    estimated_bytes = rows * int(max(1, bytes_per_row))
    result = ensure_artifact_disk_headroom(
        path,
        estimated_bytes=estimated_bytes,
        min_free_bytes=min_free_bytes,
        context=context,
    )
    if result is not None:
        result["rows"] = rows
    return result
