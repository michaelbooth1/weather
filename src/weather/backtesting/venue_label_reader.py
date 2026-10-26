"""Read built-in market labels as the venue resolves them (training, evaluation, B/MG-2 transfer).

The label of a built-in market-date is the venue's own label for that date
(owner 2026-10-25, "Switching to the venue's own labels"):

* before ``VENUE_RULE_CUTOVER_DATE`` the venue resolved on WU-equivalent data and
  paid the WU band on every measured market-day, so the label is the market's
  configured WU daily summary row (policy ``wu_history``);
* from the cutover the venue resolves on routine METAR, so the label is the
  market's venue-rule CSV row built by ``weather.backtesting.venue_rule_labels``
  (policy ``venue_rule``), or that CSV's own WU fallback row when the stream
  spans the date but holds no routine temperature (policy
  ``venue_rule_wu_fallback``). A missing or thin venue row is refused, never
  refilled from WU: the WU high disagrees with the venue rule on a few percent
  of days.

Denver from the cutover labels on KDEN and is unsupported for model scoring
(owner 2026-10-23), so ``model_scoring=True`` (the default) refuses it.

Every read names an explicit ``read_through`` date, and a ``read_through``
after ``DEVELOPMENT_READ_THROUGH`` needs ``allow_reserved_window=True``: rows
after it are dropped before they are parsed into labels. That keeps the
outcome embargo fail-closed for every caller. This module is research and
evaluation only; no capture loop or serving path imports it. Contract:
``docs/operations/venue-rule-labels.md`` ("Label reader").
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from weather.backtesting.settlement_ledger import COMPLETE_DAY_MIN_ROWS, daily_summary_path_for_spec
from weather.backtesting.venue_rule_labels import (
    BUILTIN_MARKET_IDS,
    DEFAULT_LABEL_ROOT,
    LABEL_SOURCE_METAR,
    LABEL_SOURCE_WU_FALLBACK,
    VENUE_RULE_CUTOVER_DATE,
    VENUE_RULE_VERSION,
    default_label_path,
    wu_station_icao,
)
from weather.market.market_registry import spec_for_id
from weather.schema_families import schema_version
from weather.sources.daily_summary import native_bucket, native_high

LABEL_RECORD_SCHEMA = schema_version("venue_label_record")

# The last date ordinary development reads may touch (the reserved window starts after it).
DEVELOPMENT_READ_THROUGH = date(2026, 9, 29)

POLICY_WU_HISTORY = "wu_history"
POLICY_VENUE_RULE = "venue_rule"
POLICY_VENUE_RULE_WU_FALLBACK = "venue_rule_wu_fallback"
VENUE_POLICY_BY_SOURCE = {
    LABEL_SOURCE_METAR: POLICY_VENUE_RULE,
    LABEL_SOURCE_WU_FALLBACK: POLICY_VENUE_RULE_WU_FALLBACK,
}

# market id -> first date it is unsupported for model scoring (Denver KDEN, owner 2026-10-23).
MODEL_SCORING_EXCLUDED_FROM = {"denver": VENUE_RULE_CUTOVER_DATE}

REFUSED_AFTER_READ_THROUGH = "after_read_through"
REFUSED_MODEL_SCORING_EXCLUDED = "market_unsupported_for_model_scoring"
REFUSED_NO_WU_ROW = "no_wu_row"
REFUSED_NO_VENUE_CSV = "no_venue_label_csv"
REFUSED_NO_VENUE_ROW = "no_venue_label_row"
REFUSED_THIN_VENUE_ROW = "venue_label_row_below_complete_day_rows"
REFUSED_BAD_VENUE_ROW = "venue_label_row_provenance_mismatch"


class LabelReadRefused(ValueError):
    """The read itself is not allowed (unknown market, embargo, malformed request)."""


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def _row_sha256(row):
    return _sha256_bytes(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _read_rows(path, read_through):
    """``(rows_by_date, file_sha256)`` for dates on or before ``read_through``; ``(None, None)`` if absent."""

    path = Path(path)
    if not path.is_file():
        return None, None
    payload = path.read_bytes()
    rows = {}
    for row in csv.DictReader(payload.decode("utf-8-sig").splitlines()):
        local_date = (row.get("local_date") or "").strip()
        if not local_date or date.fromisoformat(local_date) > read_through:
            continue
        rows[local_date] = row
    return rows, _sha256_bytes(payload)


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _record(spec, target, row, policy, path, file_sha256):
    high, bucket = native_high(row), native_bucket(row)
    if high is None or bucket is None:
        return None
    return {
        "schema_version": LABEL_RECORD_SCHEMA,
        "market_id": spec.id,
        "target_date": target.isoformat(),
        "unit": spec.display_unit,
        "label_high": float(high),
        "label_bucket": int(bucket),
        "label_policy": policy,
        "label_source": row.get("label_source") or POLICY_WU_HISTORY,
        "label_station": row.get("label_station") or wu_station_icao(spec),
        "label_station_basis": row.get("label_station_basis") or "",
        "label_rule_version": row.get("label_rule_version") or "",
        "label_cutover_date": VENUE_RULE_CUTOVER_DATE.isoformat(),
        "label_row_count": _int(row.get("row_count")),
        "source_path": str(path),
        "source_sha256": file_sha256,
        "source_row_sha256": _row_sha256(row),
    }


def read_venue_labels(
    market_id,
    target_dates,
    *,
    read_through,
    allow_reserved_window=False,
    model_scoring=True,
    label_root=DEFAULT_LABEL_ROOT,
    wu_daily_summary=None,
    venue_label_csv=None,
):
    """Return ``(records, refusals)`` for one built-in market.

    ``records`` maps ISO date -> ``venue_label_record`` dict; ``refusals`` maps
    ISO date -> reason for every requested date without a label. ``read_through``
    is required; no row dated after it is turned into a label.
    """

    if market_id not in BUILTIN_MARKET_IDS:
        raise LabelReadRefused(f"{market_id!r} is not a built-in market")
    if not isinstance(read_through, date):
        raise LabelReadRefused("read_through must be a datetime.date")
    if read_through > DEVELOPMENT_READ_THROUGH and not allow_reserved_window:
        raise LabelReadRefused(
            f"read_through {read_through.isoformat()} is after {DEVELOPMENT_READ_THROUGH.isoformat()}; "
            "pass allow_reserved_window=True only under an open reserved-window contract"
        )
    spec = spec_for_id(market_id)
    targets = sorted({date.fromisoformat(str(day)) for day in target_dates})
    wu_path = Path(wu_daily_summary or daily_summary_path_for_spec(spec))
    venue_path = Path(venue_label_csv or default_label_path(spec, label_root))
    wu_rows = wu_sha = venue_rows = venue_sha = None
    records, refusals = {}, {}
    excluded_from = MODEL_SCORING_EXCLUDED_FROM.get(spec.id) if model_scoring else None
    for target in targets:
        key = target.isoformat()
        if target > read_through:
            refusals[key] = REFUSED_AFTER_READ_THROUGH
            continue
        if excluded_from is not None and target >= excluded_from:
            refusals[key] = REFUSED_MODEL_SCORING_EXCLUDED
            continue
        if target < VENUE_RULE_CUTOVER_DATE:
            if wu_rows is None:
                wu_rows, wu_sha = _read_rows(wu_path, read_through)
                wu_rows = wu_rows or {}
            row = wu_rows.get(key)
            record = _record(spec, target, row, POLICY_WU_HISTORY, wu_path, wu_sha) if row else None
            if record is None:
                refusals[key] = REFUSED_NO_WU_ROW
            else:
                records[key] = record
            continue
        if venue_rows is None:
            venue_rows, venue_sha = _read_rows(venue_path, read_through)
        if venue_rows is None:
            refusals[key] = REFUSED_NO_VENUE_CSV
            continue
        row = venue_rows.get(key)
        if row is None:
            refusals[key] = REFUSED_NO_VENUE_ROW
            continue
        policy = VENUE_POLICY_BY_SOURCE.get(row.get("label_source"))
        if (
            policy is None
            or row.get("label_rule_version") != VENUE_RULE_VERSION
            or row.get("label_cutover_date") != VENUE_RULE_CUTOVER_DATE.isoformat()
        ):
            refusals[key] = REFUSED_BAD_VENUE_ROW
            continue
        if (_int(row.get("row_count")) or 0) < COMPLETE_DAY_MIN_ROWS:
            refusals[key] = REFUSED_THIN_VENUE_ROW
            continue
        record = _record(spec, target, row, policy, venue_path, venue_sha)
        if record is None:
            refusals[key] = REFUSED_BAD_VENUE_ROW
        else:
            records[key] = record
    return records, refusals
