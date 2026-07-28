"""Fail-safe capture policy for storage-pressure feature flags."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from weather.paths import config_path
from weather.schema_registry import schema_version


POLICY_SCHEMA_VERSION = schema_version("storage_pressure_policy")
DEFAULT_POLICY_PATH = config_path("storage_pressure.json")
DEFAULT_WRITE_ORDER_BOOKS_LONG_CSV = True


@dataclass(frozen=True)
class StoragePressurePolicy:
    write_order_books_long_csv: bool = DEFAULT_WRITE_ORDER_BOOKS_LONG_CSV
    status: str = "default_preserve_current_behavior"
    path: str | None = None
    detail: str | None = None

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def _fail_safe(path: Path, detail: str) -> StoragePressurePolicy:
    """Preserve current capture when policy state is missing or ambiguous."""

    return StoragePressurePolicy(
        write_order_books_long_csv=DEFAULT_WRITE_ORDER_BOOKS_LONG_CSV,
        status="invalid_fail_safe_preserve_current_behavior",
        path=str(path),
        detail=detail,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def load_storage_pressure_policy(
    path: str | Path = DEFAULT_POLICY_PATH,
) -> StoragePressurePolicy:
    path = Path(path)
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except FileNotFoundError:
        return _fail_safe(path, "policy file is missing")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _fail_safe(path, f"{type(exc).__name__}: {exc}")
    if not isinstance(raw, dict):
        return _fail_safe(path, "policy root must be an object")
    if raw.get("schema_version") != POLICY_SCHEMA_VERSION:
        return _fail_safe(
            path,
            f"expected schema_version={POLICY_SCHEMA_VERSION}",
        )
    capture = raw.get("capture")
    if not isinstance(capture, dict):
        return _fail_safe(path, "capture policy must be an object")
    enabled = capture.get("write_order_books_long_csv")
    if not isinstance(enabled, bool):
        return _fail_safe(
            path,
            "capture.write_order_books_long_csv must be a boolean",
        )
    return StoragePressurePolicy(
        write_order_books_long_csv=enabled,
        status="configured",
        path=str(path),
    )
