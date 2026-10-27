"""Pinned-centre, explicit-corpus training inputs for the per-market feature trainer.

The per-market trainer (``python -m weather.calibration.feature_model``) fits
for the run date and reads the ambient May-June forecast archive. A frozen
research arm (retrain R0, memo ``docs/research/retrain-sizing-memo-2026-10-19.md``
"R0 run plan") needs three things the default path cannot give:

* ``--target-date``: pin the centre date the prior-year training window is built
  around, instead of the run date (R0 piece M5);
* ``--pit-forecast-corpus-manifest`` (repeatable): read ``forecast_high`` and the
  forecast profile per (target date, cutoff) from one or more published,
  verified PIT forecast corpora, with **no** fallback to the ambient archive
  (M3), several corpora unioned when their years do not overlap (M4);
* ``--training-years``: restrict training to an explicit set of prior years, so
  a later corpus (for example a 2024-2025 fetch, owner decision M6) drops in by
  adding its manifest and years, with no code change.

Everything here is training-only: serving never imports this module, and the
trainer accepts these options only with ``--output-root`` (base models only,
never ``artifacts/models``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from weather.calibration.forecast_training_contract import (
    FORECAST_RELATIVE_MARINE_FIELDS,
    preflight_pit_forecast_training_corpus,
)
from weather.sources.forecast_training_corpus import (
    CorpusVerificationError,
    PITForecastTrainingCorpus,
    verify_corpus_manifest,
)

# Research record, not a registered durable schema (no versioned schema literal).
TRAINING_INPUTS_RECORD = "feature_model_training_inputs"
TRAINING_INPUTS_RECORD_VERSION = 1
FORECAST_SOURCE_AMBIENT = "ambient_forecast_archive"
FORECAST_SOURCE_PIT = "pit_forecast_corpus"
# Manifest fields that must agree for two corpora to be one training input:
# mixing leads, models, normalizers, fields or cutoff matrices would make the
# forecast column mean different things in different years.
UNION_COMPATIBILITY_FIELDS = (
    "schema_version",
    "target_year",
    "source_fields",
    "cutoff_hours_local",
    "issue_contract",
    "normalizer_version",
)
_YEAR_TOKEN = re.compile(r"\A(\d{4})(?:-(\d{4}))?\Z")


class TrainingInputError(ValueError):
    """The requested training inputs cannot be honoured exactly."""


def _canonical_sha256(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def parse_target_date(value: str | date) -> date:
    """Parse an ISO ``YYYY-MM-DD`` centre date; anything else fails closed."""
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise TrainingInputError(f"--target-date must be YYYY-MM-DD: {value!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise TrainingInputError(f"--target-date is not a calendar date: {value!r}") from exc


def parse_training_years(value: str | Iterable[int]) -> tuple[int, ...]:
    """Parse ``2021,2022,2023`` or ``2021-2023`` (mixable) into sorted unique years.

    Fails closed on an empty set, a malformed token, a reversed range or a
    year outside 1900..2999.
    """
    if isinstance(value, str):
        tokens = [token.strip() for token in value.split(",")]
        years: set[int] = set()
        for token in tokens:
            match = _YEAR_TOKEN.fullmatch(token)
            if not match:
                raise TrainingInputError(
                    f"--training-years token must be YYYY or YYYY-YYYY: {token!r}"
                )
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if end < start:
                raise TrainingInputError(f"--training-years range is reversed: {token!r}")
            years.update(range(start, end + 1))
    else:
        years = {int(year) for year in value}
    if not years:
        raise TrainingInputError("--training-years names no year")
    if min(years) < 1900 or max(years) > 2999:
        raise TrainingInputError(f"--training-years outside 1900..2999: {sorted(years)}")
    return tuple(sorted(years))


class PITForecastCorpusUnion:
    """Several verified PIT corpora read as one, per market, with no fallback.

    Each manifest is verified and preflighted (training-only publish root,
    consumer dispositions, complete coverage). The corpora must agree on
    ``UNION_COMPATIBILITY_FIELDS`` and must not share a corpus id or a year for
    this market. ``resolve`` dispatches by the target date's year and raises
    ``CorpusVerificationError`` for any year no corpus covers.
    """

    def __init__(
        self,
        manifest_paths: Sequence[str | Path],
        market_id: str,
        *,
        target_year: int,
        required_cutoff_hours: Sequence[int],
        reader_factory=PITForecastTrainingCorpus,
        preflight=preflight_pit_forecast_training_corpus,
    ):
        paths = [Path(path) for path in manifest_paths or ()]
        if not paths:
            raise TrainingInputError("at least one PIT corpus manifest is required")
        self.market_id = str(market_id)
        self.target_year = int(target_year)
        self._by_year: dict[int, Any] = {}
        self.corpora: list[dict[str, Any]] = []
        reference: dict[str, Any] | None = None
        seen_ids: set[str] = set()
        for path in paths:
            manifest = verify_corpus_manifest(path)
            corpus_id = str(manifest["corpus_id"])
            if corpus_id in seen_ids:
                raise TrainingInputError(f"PIT corpus given twice: {corpus_id}")
            seen_ids.add(corpus_id)
            if self.market_id not in manifest.get("market_ids", []):
                raise TrainingInputError(
                    f"market {self.market_id} is absent from PIT corpus {corpus_id}"
                )
            compatibility = {field: manifest.get(field) for field in UNION_COMPATIBILITY_FIELDS}
            if reference is None:
                reference = compatibility
            elif compatibility != reference:
                differing = sorted(
                    field for field in UNION_COMPATIBILITY_FIELDS
                    if compatibility[field] != reference[field]
                )
                raise TrainingInputError(
                    f"PIT corpus {corpus_id} is incompatible with the first corpus: {differing}"
                )
            receipt = preflight(
                path,
                target_year=self.target_year,
                required_market_ids=sorted(manifest["market_ids"]),
                required_cutoff_hours=sorted(int(hour) for hour in required_cutoff_hours),
            )
            reader = reader_factory(path, self.market_id)
            years = sorted(int(year) for year in manifest["years"])
            overlap = sorted(set(years) & set(self._by_year))
            if overlap:
                raise TrainingInputError(
                    f"PIT corpora overlap in years {overlap} for market {self.market_id}"
                )
            for year in years:
                self._by_year[year] = reader
            self.corpora.append({
                "corpus_id": corpus_id,
                "manifest_sha256": manifest["manifest_sha256"],
                "manifest_file_sha256": receipt.get("manifest_file_sha256"),
                "preflight_sha256": receipt.get("preflight_sha256"),
                "years": years,
                "source_fields": list(manifest.get("source_fields") or []),
            })
        self.years = tuple(sorted(self._by_year))

    def resolve(self, target_date, cutoff_hour):
        year = int(str(target_date)[:4])
        reader = self._by_year.get(year)
        if reader is None:
            raise CorpusVerificationError(
                f"no PIT corpus covers {self.market_id} {target_date} (year {year}); "
                "ambient fallback is not allowed"
            )
        return reader.resolve(target_date, cutoff_hour)

    def record(self) -> dict[str, Any]:
        corpora = sorted(self.corpora, key=lambda row: min(row["years"]))
        return {
            "market_id": self.market_id,
            "centre_year": self.target_year,
            "years": list(self.years),
            "corpora": corpora,
            "union_sha256": _canonical_sha256(
                [[row["corpus_id"], row["manifest_sha256"]] for row in corpora]
            ),
        }


def select_training_days(
    daily: Mapping[date, Any],
    *,
    training_years: Sequence[int] | None = None,
    forecast_years: Sequence[int] | None = None,
    target_date: date | None = None,
) -> tuple[dict[date, Any], dict[str, int]]:
    """Restrict the labelled-day cache to the training years.

    * With PIT corpora (``forecast_years``) and no explicit years, the years are
      the corpora's years; with explicit years, every one must be covered by a
      corpus (no ambient fallback for the uncovered years).
    * Every selected year must be earlier than the centre year and must hold
      at least one labelled day in the window, or the run fails closed (a
      silently empty year would change the training population unrecorded).
    """
    if training_years is None and forecast_years is None:
        return dict(daily), {}
    selected = tuple(sorted(int(year) for year in (training_years or forecast_years)))
    if forecast_years is not None:
        uncovered = sorted(set(selected) - {int(year) for year in forecast_years})
        if uncovered:
            raise TrainingInputError(
                f"training years {uncovered} have no PIT corpus; add a manifest that "
                "covers them (the ambient archive is never a fallback)"
            )
    if target_date is not None:
        not_prior = [year for year in selected if year >= target_date.year]
        if not_prior:
            raise TrainingInputError(
                f"training years {not_prior} are not earlier than the centre year {target_date.year}"
            )
    kept = {day: row for day, row in daily.items() if day.year in selected}
    counts = {str(year): 0 for year in selected}
    for day in kept:
        counts[str(day.year)] += 1
    empty = sorted(int(year) for year, count in counts.items() if count == 0)
    if empty:
        raise TrainingInputError(
            f"training years {empty} have no labelled day in the window "
            "(check the data root and the centre date)"
        )
    return kept, counts


def null_forecast_relative_marine_fields(features):
    """Drop marine features computed against the ambient forecast (PIT parity).

    Same disposition as the pooled PIT consumer: those fields are
    ``forecast_relative_marine_fields`` in the corpus consumer contract.
    """
    if not features:
        return features
    cleaned = dict(features)
    for column in FORECAST_RELATIVE_MARINE_FIELDS:
        if column in cleaned:
            cleaned[column] = None
    return cleaned


def require_market_history(spec) -> Path:
    """Fail closed when the market's WU history is absent (worktree data root, M10).

    Without it the cache is silently empty and the trainer would fit nothing.
    """
    summary = Path(spec.data_root) / "daily" / "daily_summary.csv"
    if not summary.is_file():
        raise TrainingInputError(
            f"market history is absent: {summary}. In a worktree, link the main "
            "checkout's read-only training inputs first (docs/operations/"
            "PIT_FORECAST_TRAINING_CORPUS.md, 'Training from a worktree')."
        )
    return summary


def training_inputs_record(
    *,
    target_date: date | None,
    training_years: Sequence[int] | None,
    corpus_union: PITForecastCorpusUnion | None,
    day_counts: Mapping[str, int],
) -> dict[str, Any]:
    """The provenance block written into both artifacts and the report."""
    record = {
        "record": TRAINING_INPUTS_RECORD,
        "record_version": TRAINING_INPUTS_RECORD_VERSION,
        "centre_date": target_date.isoformat() if target_date else None,
        "centre_date_pinned": target_date is not None,
        "training_years": list(training_years) if training_years else None,
        "training_days_by_year": dict(sorted(day_counts.items())),
        "forecast_source": FORECAST_SOURCE_PIT if corpus_union else FORECAST_SOURCE_AMBIENT,
        "ambient_forecast_fallback": False if corpus_union else None,
        "pit_forecast_corpus": corpus_union.record() if corpus_union else None,
    }
    record["record_sha256"] = _canonical_sha256(record)
    return record
