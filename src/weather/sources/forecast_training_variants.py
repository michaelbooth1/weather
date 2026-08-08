"""Explicit honest, rich, and hybrid readers for forecast-training research.

The readers in this module never discover the active serving archive.  A caller
must supply a forecast-history root, and every selected file is validated before
the first training row is assembled.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime, time
from pathlib import Path

from weather.sources.forecast_history import load_forecast_daily, load_forecast_profiles
from weather.units import to_float


FORECAST_TRAINING_VARIANTS = ("honest", "rich", "hybrid")
PIT_SOURCE = "open_meteo_previous_runs"
PIT_ISSUE_BASIS = "fixed_lead_day_offset"


class ForecastTrainingVariantError(ValueError):
    """The explicit forecast-training input is missing or internally inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aware_datetime(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ForecastTrainingVariantError(f"{field} is not an ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForecastTrainingVariantError(f"{field} must be timezone-aware")
    return parsed


class ForecastTrainingVariantResolver:
    """Resolve one market's A/B/C forecast input from explicit CSV files."""

    def __init__(self, history_root, spec, *, variant: str, pit_lead_days: int = 1):
        variant = str(variant or "").strip().lower()
        if variant not in FORECAST_TRAINING_VARIANTS:
            raise ForecastTrainingVariantError(
                f"unknown forecast-training variant: {variant!r}"
            )
        pit_lead_days = int(pit_lead_days)
        if pit_lead_days <= 0:
            raise ForecastTrainingVariantError("pit_lead_days must be positive")

        root = Path(history_root).resolve()
        market_root = root / spec.icao.lower()
        if not market_root.is_dir():
            raise ForecastTrainingVariantError(
                f"explicit forecast-history market root is missing: {market_root}"
            )
        self.history_root = root
        self.market_root = market_root
        self.market_id = spec.id
        self.timezone = spec.tz
        self.variant = variant
        self.pit_lead_days = pit_lead_days
        self.uses_point_in_time_high = variant in {"honest", "hybrid"}
        self.uses_settled_forecast_high = variant == "rich"
        self.uses_settled_profiles = variant in {"rich", "hybrid"}

        self.daily_issue_path = market_root / "forecast_daily_by_issue.csv"
        self.rich_daily_path = market_root / "forecast_daily.csv"
        self.rich_long_path = market_root / "forecast_long.csv"
        self._pit_daily = (
            self._load_pit_daily(self.daily_issue_path, spec)
            if self.uses_point_in_time_high
            else {}
        )
        self._rich_daily = (
            load_forecast_daily(self.rich_daily_path)
            if self.uses_settled_forecast_high
            else {}
        )
        self._rich_profiles = (
            load_forecast_profiles(self.rich_long_path)
            if self.uses_settled_profiles
            else {}
        )

        if self.uses_settled_forecast_high and not self.rich_daily_path.is_file():
            raise ForecastTrainingVariantError(
                f"explicit rich daily forecast file is missing: {self.rich_daily_path}"
            )
        if self.uses_settled_profiles and not self.rich_long_path.is_file():
            raise ForecastTrainingVariantError(
                f"explicit rich profile file is missing: {self.rich_long_path}"
            )

        date_sets = []
        if self.uses_point_in_time_high:
            date_sets.append(set(self._pit_daily))
        if self.uses_settled_forecast_high:
            date_sets.append(set(self._rich_daily))
        if self.uses_settled_profiles:
            date_sets.append(set(self._rich_profiles))
        self.target_dates = frozenset(set.intersection(*date_sets) if date_sets else set())
        if not self.target_dates:
            raise ForecastTrainingVariantError(
                f"forecast-training variant {variant!r} has no complete target dates"
            )
        self.years = tuple(sorted({date.fromisoformat(value).year for value in self.target_dates}))
        self.file_receipt = self._file_receipt()

    def _load_pit_daily(self, path: Path, spec) -> dict[str, dict]:
        if not path.is_file():
            raise ForecastTrainingVariantError(
                f"explicit PIT daily-by-issue file is missing: {path}"
            )
        selected: dict[str, dict] = {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "market",
                "station",
                "source",
                "temperature_unit",
                "target_date",
                "issue_time",
                "issue_time_basis",
                "lead_days",
                "forecast_high_native",
                "hourly_rows",
            }
            missing = sorted(required - set(reader.fieldnames or ()))
            if missing:
                raise ForecastTrainingVariantError(
                    "PIT daily-by-issue header is missing: " + ", ".join(missing)
                )
            for row in reader:
                if (
                    row.get("source") != PIT_SOURCE
                    or row.get("issue_time_basis") != PIT_ISSUE_BASIS
                    or int(row.get("lead_days") or 0) != self.pit_lead_days
                ):
                    continue
                if row.get("market") != spec.id or row.get("station") != spec.icao:
                    raise ForecastTrainingVariantError(
                        "PIT daily-by-issue market/station identity is inconsistent"
                    )
                if row.get("temperature_unit") != spec.display_unit:
                    raise ForecastTrainingVariantError(
                        "PIT daily-by-issue temperature unit is inconsistent"
                    )
                try:
                    target = date.fromisoformat(str(row.get("target_date")))
                except (TypeError, ValueError) as exc:
                    raise ForecastTrainingVariantError(
                        "PIT daily-by-issue target_date is invalid"
                    ) from exc
                issue = _aware_datetime(row.get("issue_time"), field="issue_time")
                if (target - issue.astimezone(spec.tz).date()).days != self.pit_lead_days:
                    raise ForecastTrainingVariantError(
                        "PIT issue_time does not match its fixed lead-day offset"
                    )
                high = to_float(row.get("forecast_high_native"))
                if high is None or int(float(row.get("hourly_rows") or 0)) != 24:
                    raise ForecastTrainingVariantError(
                        "PIT daily-by-issue row lacks a complete 24-hour forecast high"
                    )
                key = target.isoformat()
                if key in selected:
                    raise ForecastTrainingVariantError(
                        f"duplicate PIT daily-by-issue row for {key} lead {self.pit_lead_days}"
                    )
                selected[key] = {
                    "forecast_high": high,
                    "issue_time": issue,
                    "source_model": row.get("source_model") or "best_match",
                }
        if not selected:
            raise ForecastTrainingVariantError(
                f"no PIT lead-{self.pit_lead_days} rows are present in {path}"
            )
        return selected

    def _file_receipt(self) -> dict:
        paths = {}
        if self.uses_point_in_time_high:
            paths["pit_daily_by_issue"] = self.daily_issue_path
        if self.uses_settled_forecast_high:
            paths["rich_daily"] = self.rich_daily_path
        if self.uses_settled_profiles:
            paths["rich_profiles"] = self.rich_long_path
        return {
            name: {
                "path": str(path),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for name, path in paths.items()
        }

    def resolve(self, target_date, cutoff_hour) -> dict:
        target = date.fromisoformat(str(target_date))
        target_text = target.isoformat()
        cutoff_hour = int(cutoff_hour)
        if cutoff_hour < 0 or cutoff_hour > 23:
            raise ForecastTrainingVariantError("cutoff_hour must be in [0, 23]")
        if target_text not in self.target_dates:
            raise ForecastTrainingVariantError(
                f"no complete {self.variant} forecast input for {self.market_id} {target_text}"
            )

        if self.uses_point_in_time_high:
            pit = self._pit_daily[target_text]
            cutoff = datetime.combine(
                target,
                time(cutoff_hour),
                tzinfo=self.timezone,
            )
            if pit["issue_time"] > cutoff:
                raise ForecastTrainingVariantError(
                    f"PIT forecast issue time is after cutoff for {target_text} {cutoff_hour:02d}:00"
                )
            forecast_high = pit["forecast_high"]
            issue_time = pit["issue_time"].isoformat()
            source_model = pit["source_model"]
        else:
            forecast_high = self._rich_daily[target_text]
            issue_time = ""
            source_model = "settled_best_match"

        return {
            "forecast_high": forecast_high,
            "profile_rows": (
                self._rich_profiles.get(target_text)
                if self.uses_settled_profiles
                else None
            ),
            "provenance": {
                "training_variant": self.variant,
                "market_id": self.market_id,
                "pit_lead_days": self.pit_lead_days if self.uses_point_in_time_high else None,
                "forecast_high_source": (
                    PIT_SOURCE if self.uses_point_in_time_high else "open_meteo_historical_forecast"
                ),
                "profile_source": (
                    "open_meteo_historical_forecast"
                    if self.uses_settled_profiles
                    else "excluded"
                ),
                "issue_time": issue_time,
                "source_model": source_model,
                "uses_settled_forecast_high": self.uses_settled_forecast_high,
                "uses_settled_profiles": self.uses_settled_profiles,
            },
        }
