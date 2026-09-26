"""Approved storage-family scopes for the existing verified archive lane.

Path and age checks do not grant campaign approval, restore or reclaim authority.
"""
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath

from weather.cold_archive_locations import CatalogIntegrityError, ROTATED_DIAGNOSTIC_RE, source_layout
from weather.operations.storage_recovery_inventory import event_date

FAMILY_ORDER = ("rotated_diagnostics", "maker_quote_intents", "variant_tapes", "price_history_raw")
VARIANT_NAMES = {"variant_predictions.jsonl", "variant_predictions_long.csv",
                 "snapshot_explanations.jsonl", "snapshot_explanations_long.csv"}


def family_group(path):
    kind, scope = source_layout(path)
    name = PurePosixPath(path).name
    if kind == "rotated_diagnostics":
        stamp = ROTATED_DIAGNOSTIC_RE.fullmatch(name).group(1)
        return kind, scope + "/rotated_diagnostics/" + stamp[:6]
    if kind != "snapshot":
        return kind, scope
    if name in VARIANT_NAMES:
        return "variant_tapes", scope + "/" + name.removesuffix(".gz")
    raise ValueError("source is outside the four approved storage families")


def validate_cold_source(path, today, *, extended=False):
    """Protect the EF 8bb maker panel and retain the existing thirty-day window."""
    parts = PurePosixPath(path).parts
    try:
        kind, _ = source_layout(path)
    except CatalogIntegrityError as exc:
        raise ValueError("unsupported archive source layout") from exc
    if kind == "rotated_diagnostics":
        stamp = ROTATED_DIAGNOSTIC_RE.fullmatch(parts[1]).group(1)
        target = datetime.strptime(stamp, "%Y%m%d").date()
    elif kind == "maker_quote_intents":
        target = date.fromisoformat(parts[1])
        if date(2026, 7, 31) <= target <= date(2026, 8, 8):
            raise ValueError("EF 8bb maker quote-intent dates stay hot")
    else:
        target = event_date(parts[1])
    if target >= today - timedelta(days=30):
        raise ValueError("source event is inside the thirty-day hot window")
    if extended:
        family_group(path)
    elif kind != "snapshot":
        raise ValueError("extended source requires storage-family grouping")
    return target
