"""Leakage-controlled conditional edge search for mission 2026-09-46a.

The ``prepare`` phase reads quote-time fields only and freezes a predictor
sidecar plus entropy cutpoints.  The ``analyze`` phase refuses to run until the
pre-registration, inputs, sidecar, and positive control all match their pinned
identities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm


BAND_ROWS_SHA256 = "9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae"
MEASUREMENT_MANIFEST_SHA256 = "cf21b67e3236395da800176c27e5c3a571a838e8cc28a491ec48e23e497e7c3e"
EXPECTED_BAND_ROWS = 135_179
EXPECTED_SNAPSHOTS = 12_289
EXPECTED_DATES = 50
EXPECTED_MARKETS = 12
EXPECTED_MARKET_DAYS = 524
MAX_TARGET_DATE = "2026-07-30"
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_946
FAMILY_ALPHA = 0.05

MARKETS = (
    "atlanta",
    "austin",
    "chicago",
    "dallas",
    "denver",
    "houston",
    "los-angeles",
    "miami",
    "nyc",
    "san-francisco",
    "seattle",
    "toronto",
)
HOUR_GROUPS = {
    "open_07_08": (7, 8),
    "primary_09_14": tuple(range(9, 15)),
    "afternoon_15_17": tuple(range(15, 18)),
    "lock_in_18_20": tuple(range(18, 21)),
}


@dataclass(frozen=True)
class Hypothesis:
    axis: str
    cell: str

    @property
    def key(self) -> str:
        return f"{self.axis}:{self.cell}"


def hypotheses() -> tuple[Hypothesis, ...]:
    items: list[Hypothesis] = []

    def add(axis: str, cells: Iterable[str]) -> None:
        items.extend(Hypothesis(axis, cell) for cell in cells)

    add("hour", (f"{hour:02d}" for hour in range(7, 21)))
    add("market", MARKETS)
    add("season", ("B", "C"))
    add(
        "forecast_distance",
        (
            "missing",
            "lt_-2.5",
            "-2.5_to_-1.5",
            "-1.5_to_-0.5",
            "-0.5_to_0.5",
            "0.5_to_1.5",
            "1.5_to_2.5",
            "gt_2.5",
        ),
    )
    for axis in ("model_entropy", "market_entropy", "entropy_gap"):
        add(axis, ("Q1", "Q2", "Q3", "Q4"))
    add(
        "forecast_disagreement_c_eq",
        ("missing", "le_0.5", "0.5_to_1", "1_to_2", "gt_2"),
    )
    add("forecast_source_count", ("missing_or_0", "1", "2", "3_plus"))
    add(
        "market_probability",
        (
            "0_to_0.02",
            "0.02_to_0.10",
            "0.10_to_0.25",
            "0.25_to_0.50",
            "0.50_to_0.75",
            "0.75_to_0.90",
            "0.90_to_0.98",
            "0.98_to_1",
        ),
    )
    add(
        "signed_probability_gap",
        ("lt_-0.20", "-0.20_to_-0.05", "-0.05_to_0.05", "0.05_to_0.20", "gt_0.20"),
    )
    add(
        "hour_x_probability_gap",
        (
            f"{hour_group}|{gap}"
            for hour_group in HOUR_GROUPS
            for gap in ("model_lower_10pp", "within_10pp", "model_higher_10pp")
        ),
    )
    add(
        "season_x_hour",
        (f"{season}|{hour_group}" for season in ("B", "C") for hour_group in HOUR_GROUPS),
    )
    add(
        "distance_x_hour",
        (
            f"{distance}|{hour_group}"
            for distance in ("near_abs_le_1", "middle_abs_1_to_3", "far_abs_gt_3")
            for hour_group in HOUR_GROUPS
        ),
    )
    add("book_spread", ("missing_or_invalid", "le_0.002", "0.002_to_0.01", "0.01_to_0.045", "gt_0.045"))
    add("liquidity", ("missing", "lt_25", "25_to_100", "100_to_500", "ge_500"))
    add("volume", ("missing", "lt_10000", "10000_to_30000", "30000_to_65000", "ge_65000"))
    result = tuple(items)
    if len(result) != 117 or len({item.key for item in result}) != 117:
        raise AssertionError(f"pre-registered family changed: {len(result)}")
    return result


HYPOTHESES = hypotheses()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _entropy(values: pd.Series) -> float:
    probabilities = values.to_numpy(dtype=float)
    total = float(probabilities.sum())
    if total <= 0.0 or len(probabilities) < 2:
        raise ValueError("entropy requires a positive multi-band distribution")
    probabilities = probabilities / total
    nonzero = probabilities[probabilities > 0.0]
    return float(-(nonzero * np.log(nonzero)).sum() / math.log(len(probabilities)))


def _band_midpoint(kind: str, value: Any, value_hi: Any) -> float | None:
    low = _safe_float(value)
    high = _safe_float(value_hi)
    if low is None:
        return None
    if kind in {"lte", "gte"} or high is None:
        return low
    return (low + high) / 2.0


def _validate_population(frame: pd.DataFrame) -> None:
    support = {
        "band_rows": len(frame),
        "snapshots": frame["snapshot_id"].nunique(),
        "dates": frame["target_date"].nunique(),
        "markets": frame["market_id"].nunique(),
        "market_days": frame[["target_date", "market_id"]].drop_duplicates().shape[0],
    }
    expected = {
        "band_rows": EXPECTED_BAND_ROWS,
        "snapshots": EXPECTED_SNAPSHOTS,
        "dates": EXPECTED_DATES,
        "markets": EXPECTED_MARKETS,
        "market_days": EXPECTED_MARKET_DAYS,
    }
    if support != expected:
        raise RuntimeError(f"sealed population changed: {support} != {expected}")
    if str(frame["target_date"].max()) > MAX_TARGET_DATE:
        raise RuntimeError("row crosses the frozen provenance/date ceiling")
    if tuple(sorted(frame["market_id"].unique())) != MARKETS:
        raise RuntimeError("market roster changed")


def _read_selected_records(
    path: Path,
    selected_ids: set[str],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            snapshot_id = str(payload.get("snapshot_id") or "")
            if snapshot_id in selected_ids:
                records[snapshot_id] = payload
    return records


def _extract_forecast_features(
    roster: pd.DataFrame,
    records: dict[str, dict[str, Any]],
    market_id: str,
    target_date: str,
) -> pd.DataFrame:
    from weather.backtesting.replay import parse_built_at
    from weather.model.toronto_model import TorontoHighTempModel
    from weather.release_serving import STATUS_RESEARCH_UNBOUND, VerifiedServingBundle

    bundle = VerifiedServingBundle(
        status=STATUS_RESEARCH_UNBOUND,
        reason="read-only quotable-edge predictor preparation",
        pointer_present=False,
    )
    model = TorontoHighTempModel(
        market_id=market_id,
        target_date=date.fromisoformat(target_date),
        serving_bundle=bundle,
    )
    output = []
    for row in roster.drop_duplicates("snapshot_id").itertuples(index=False):
        record = records.get(str(row.snapshot_id))
        if record is None:
            raise RuntimeError(f"missing replay input for {row.snapshot_id}")
        if canonical_hash(record) != str(row.record_hash):
            raise RuntimeError(f"replay record hash changed for {row.snapshot_id}")
        features = model.extract_live_features(
            record.get("sources") or {},
            int(row.effective_cutoff_hour),
            now=parse_built_at(record),
        )
        output.append(
            {
                "snapshot_id": str(row.snapshot_id),
                "forecast_high": features.get("forecast_high"),
                "forecast_disagreement": features.get("forecast_disagreement"),
                "forecast_source_count": features.get("forecast_source_count"),
            }
        )
    return pd.DataFrame(output)


def prepare_predictors(
    *,
    band_rows_path: Path,
    measurement_manifest_path: Path,
    snapshots_root: Path,
    preregistration_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    if sha256_file(band_rows_path) != BAND_ROWS_SHA256:
        raise RuntimeError("repaired band-row identity changed")
    if sha256_file(measurement_manifest_path) != MEASUREMENT_MANIFEST_SHA256:
        raise RuntimeError("measurement-manifest identity changed")
    output_root.mkdir(parents=True, exist_ok=True)
    sidecar_path = output_root / "predictor-sidecar.csv"
    thresholds_path = output_root / "predictor-thresholds.json"
    manifest_out = output_root / "predictor-manifest.json"
    for path in (sidecar_path, thresholds_path, manifest_out):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")

    # Keep model construction and feature extraction away from ambient mutable
    # runtime state.  All predictor inputs below come from the sealed replay
    # records and their identical captured tape rows.
    import weather.paths as weather_paths

    weather_paths.DATA_ROOT = output_root / "ambient-model-data-access-disabled"

    quote_columns = [
        "snapshot_id",
        "record_hash",
        "target_date",
        "stratum",
        "market_id",
        "capture_hour",
        "effective_cutoff_hour",
        "band_index",
        "range_label",
        "bin_kind",
        "bin_value",
        "bin_value_hi",
        "served_replay_probability",
        "market_probability",
    ]
    frame = pd.read_csv(
        band_rows_path,
        usecols=quote_columns,
        dtype={"snapshot_id": str, "record_hash": str, "target_date": str, "market_id": str},
        low_memory=False,
    ).rename(columns={"served_replay_probability": "repair_probability"})
    _validate_population(frame)

    snapshot_entropy = (
        frame.groupby("snapshot_id", sort=False)
        .agg(
            model_entropy=("repair_probability", _entropy),
            market_entropy=("market_probability", _entropy),
        )
        .reset_index()
    )
    snapshot_entropy["entropy_gap"] = (
        snapshot_entropy["model_entropy"] - snapshot_entropy["market_entropy"]
    )
    frame = frame.merge(snapshot_entropy, on="snapshot_id", validate="many_to_one")

    manifest = json.loads(measurement_manifest_path.read_text(encoding="utf-8"))
    admitted = {
        (str(item["market_id"]), str(item["target_date"])): str(item["event_slug"])
        for item in manifest.get("cell_receipts") or []
        if item.get("status") == "admitted"
    }
    feature_frames = []
    tape_frames = []
    for (market_id, target_date), roster in frame.groupby(["market_id", "target_date"], sort=True):
        event_slug = admitted.get((str(market_id), str(target_date)))
        if not event_slug:
            raise RuntimeError(f"missing admitted receipt: {market_id}:{target_date}")
        folder = snapshots_root / event_slug
        selected_ids = set(roster["snapshot_id"].astype(str))
        records = _read_selected_records(folder / "replay_inputs.jsonl", selected_ids)
        feature_frames.append(
            _extract_forecast_features(roster, records, str(market_id), str(target_date))
        )
        header = list(pd.read_csv(folder / "snapshots_long.csv", nrows=0).columns)
        desired = [
            "snapshot_id",
            "range_label",
            "bin_kind",
            "bin_value_c",
            "bin_value_hi_c",
            "best_bid",
            "best_ask",
            "volume",
            "liquidity",
        ]
        tape = pd.read_csv(
            folder / "snapshots_long.csv",
            usecols=[column for column in desired if column in header],
            dtype=str,
            low_memory=False,
        ).fillna("")
        tape = tape[tape["snapshot_id"].astype(str).isin(selected_ids)].copy()
        tape["band_index"] = tape.groupby("snapshot_id", sort=False).cumcount()
        for missing in ("bin_value_hi_c", "best_bid", "best_ask", "volume", "liquidity"):
            if missing not in tape:
                tape[missing] = ""
        tape_frames.append(
            tape[
                [
                    "snapshot_id",
                    "band_index",
                    "range_label",
                    "bin_kind",
                    "bin_value_c",
                    "bin_value_hi_c",
                    "best_bid",
                    "best_ask",
                    "volume",
                    "liquidity",
                ]
            ]
        )

    feature_frame = pd.concat(feature_frames, ignore_index=True)
    if feature_frame["snapshot_id"].nunique() != EXPECTED_SNAPSHOTS:
        raise RuntimeError("forecast sidecar snapshot roster changed")
    frame = frame.merge(feature_frame, on="snapshot_id", validate="many_to_one")
    tape_frame = pd.concat(tape_frames, ignore_index=True)
    frame = frame.merge(
        tape_frame,
        on=["snapshot_id", "band_index"],
        how="left",
        suffixes=("", "_tape"),
        validate="one_to_one",
    )
    for comparable in ("range_label", "bin_kind"):
        tape_column = f"{comparable}_tape"
        mismatch = frame[tape_column].notna() & (frame[comparable].astype(str) != frame[tape_column].astype(str))
        if mismatch.any():
            raise RuntimeError(f"tape band order changed: {comparable}")

    frame["band_midpoint_native"] = [
        _band_midpoint(kind, value, high)
        for kind, value, high in zip(frame["bin_kind"], frame["bin_value"], frame["bin_value_hi"])
    ]
    frame["forecast_distance_bands"] = frame["band_midpoint_native"] - pd.to_numeric(
        frame["forecast_high"], errors="coerce"
    )
    unit_factor = frame["market_id"].map(lambda value: 1.0 if value == "toronto" else 5.0 / 9.0)
    frame["forecast_disagreement_c_eq"] = pd.to_numeric(
        frame["forecast_disagreement"], errors="coerce"
    ) * unit_factor
    for column in ("best_bid", "best_ask", "volume", "liquidity"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    valid_book = (
        frame["best_bid"].between(0.0, 1.0, inclusive="both")
        & frame["best_ask"].between(0.0, 1.0, inclusive="both")
        & (frame["best_ask"] >= frame["best_bid"])
    )
    frame["book_spread"] = np.where(
        valid_book, frame["best_ask"] - frame["best_bid"], np.nan
    )
    output_columns = [
        "snapshot_id",
        "record_hash",
        "target_date",
        "stratum",
        "market_id",
        "capture_hour",
        "effective_cutoff_hour",
        "band_index",
        "repair_probability",
        "market_probability",
        "model_entropy",
        "market_entropy",
        "entropy_gap",
        "forecast_high",
        "forecast_disagreement_c_eq",
        "forecast_source_count",
        "band_midpoint_native",
        "forecast_distance_bands",
        "best_bid",
        "best_ask",
        "book_spread",
        "volume",
        "liquidity",
    ]
    frame[output_columns].to_csv(sidecar_path, index=False, lineterminator="\n")

    snapshot_values = frame.drop_duplicates("snapshot_id")
    thresholds = {
        "schema_version": "quotable_edge_predictor_thresholds_v1",
        "quantile_method": "numpy_linear",
        "ties": "lower_cell",
        "cutpoints": {
            column: [
                float(value)
                for value in np.quantile(
                    snapshot_values[column].to_numpy(dtype=float),
                    [0.25, 0.5, 0.75],
                    method="linear",
                )
            ]
            for column in ("model_entropy", "market_entropy", "entropy_gap")
        },
    }
    _write_json(thresholds_path, thresholds)
    prepared = {
        "schema_version": "quotable_edge_predictor_manifest_v1",
        "status": "PASS",
        "outcomes_read": False,
        "hypothesis_count": len(HYPOTHESES),
        "support": {
            "band_rows": len(frame),
            "snapshots": frame["snapshot_id"].nunique(),
            "date_clusters": frame["target_date"].nunique(),
            "market_clusters": frame["market_id"].nunique(),
            "market_days": frame[["target_date", "market_id"]].drop_duplicates().shape[0],
        },
        "inputs": {
            "band_rows_sha256": sha256_file(band_rows_path),
            "measurement_manifest_sha256": sha256_file(measurement_manifest_path),
            "preregistration_sha256": sha256_file(preregistration_path),
        },
        "outputs": {
            "predictor_sidecar_sha256": sha256_file(sidecar_path),
            "predictor_thresholds_sha256": sha256_file(thresholds_path),
        },
    }
    _write_json(manifest_out, prepared)
    return prepared


def _quartile(values: pd.Series, cutpoints: list[float], cell: str) -> pd.Series:
    q1, q2, q3 = cutpoints
    if cell == "Q1":
        return values <= q1
    if cell == "Q2":
        return (values > q1) & (values <= q2)
    if cell == "Q3":
        return (values > q2) & (values <= q3)
    if cell == "Q4":
        return values > q3
    raise KeyError(cell)


def _hour_group(values: pd.Series, name: str) -> pd.Series:
    return values.isin(HOUR_GROUPS[name])


def membership(
    frame: pd.DataFrame,
    thresholds: dict[str, Any],
    hypothesis: Hypothesis,
) -> pd.Series:
    axis, cell = hypothesis.axis, hypothesis.cell
    hour = frame["effective_cutoff_hour"].astype(int)
    if axis == "hour":
        return hour == int(cell)
    if axis == "market":
        return frame["market_id"] == cell
    if axis == "season":
        return frame["stratum"] == cell
    if axis == "forecast_distance":
        value = frame["forecast_distance_bands"]
        rules = {
            "missing": value.isna(),
            "lt_-2.5": value < -2.5,
            "-2.5_to_-1.5": (value >= -2.5) & (value < -1.5),
            "-1.5_to_-0.5": (value >= -1.5) & (value < -0.5),
            "-0.5_to_0.5": (value >= -0.5) & (value <= 0.5),
            "0.5_to_1.5": (value > 0.5) & (value <= 1.5),
            "1.5_to_2.5": (value > 1.5) & (value <= 2.5),
            "gt_2.5": value > 2.5,
        }
        return rules[cell]
    if axis in {"model_entropy", "market_entropy", "entropy_gap"}:
        return _quartile(frame[axis], thresholds["cutpoints"][axis], cell)
    if axis == "forecast_disagreement_c_eq":
        value = frame[axis]
        rules = {
            "missing": value.isna(),
            "le_0.5": value.notna() & (value <= 0.5),
            "0.5_to_1": (value > 0.5) & (value <= 1.0),
            "1_to_2": (value > 1.0) & (value <= 2.0),
            "gt_2": value > 2.0,
        }
        return rules[cell]
    if axis == "forecast_source_count":
        value = pd.to_numeric(frame[axis], errors="coerce")
        rules = {
            "missing_or_0": value.isna() | (value <= 0),
            "1": value == 1,
            "2": value == 2,
            "3_plus": value >= 3,
        }
        return rules[cell]
    if axis == "market_probability":
        value = frame["market_probability"]
        rules = {
            "0_to_0.02": (value >= 0.0) & (value < 0.02),
            "0.02_to_0.10": (value >= 0.02) & (value < 0.10),
            "0.10_to_0.25": (value >= 0.10) & (value < 0.25),
            "0.25_to_0.50": (value >= 0.25) & (value < 0.50),
            "0.50_to_0.75": (value >= 0.50) & (value < 0.75),
            "0.75_to_0.90": (value >= 0.75) & (value < 0.90),
            "0.90_to_0.98": (value >= 0.90) & (value < 0.98),
            "0.98_to_1": (value >= 0.98) & (value <= 1.0),
        }
        return rules[cell]
    probability_gap = frame["repair_probability"] - frame["market_probability"]
    if axis == "signed_probability_gap":
        rules = {
            "lt_-0.20": probability_gap < -0.20,
            "-0.20_to_-0.05": (probability_gap >= -0.20) & (probability_gap < -0.05),
            "-0.05_to_0.05": (probability_gap >= -0.05) & (probability_gap <= 0.05),
            "0.05_to_0.20": (probability_gap > 0.05) & (probability_gap <= 0.20),
            "gt_0.20": probability_gap > 0.20,
        }
        return rules[cell]
    if axis == "hour_x_probability_gap":
        hour_cell, gap_cell = cell.split("|", 1)
        gap_masks = {
            "model_lower_10pp": probability_gap <= -0.10,
            "within_10pp": (probability_gap > -0.10) & (probability_gap < 0.10),
            "model_higher_10pp": probability_gap >= 0.10,
        }
        return _hour_group(hour, hour_cell) & gap_masks[gap_cell]
    if axis == "season_x_hour":
        season, hour_cell = cell.split("|", 1)
        return (frame["stratum"] == season) & _hour_group(hour, hour_cell)
    if axis == "distance_x_hour":
        distance_cell, hour_cell = cell.split("|", 1)
        distance = frame["forecast_distance_bands"].abs()
        distance_masks = {
            "near_abs_le_1": distance.notna() & (distance <= 1.0),
            "middle_abs_1_to_3": (distance > 1.0) & (distance <= 3.0),
            "far_abs_gt_3": distance > 3.0,
        }
        return distance_masks[distance_cell] & _hour_group(hour, hour_cell)
    if axis == "book_spread":
        value = frame[axis]
        rules = {
            "missing_or_invalid": value.isna(),
            "le_0.002": value.notna() & (value <= 0.002),
            "0.002_to_0.01": (value > 0.002) & (value <= 0.01),
            "0.01_to_0.045": (value > 0.01) & (value <= 0.045),
            "gt_0.045": value > 0.045,
        }
        return rules[cell]
    if axis in {"liquidity", "volume"}:
        value = frame[axis]
        if axis == "liquidity":
            rules = {
                "missing": value.isna(),
                "lt_25": value.notna() & (value < 25),
                "25_to_100": (value >= 25) & (value < 100),
                "100_to_500": (value >= 100) & (value < 500),
                "ge_500": value >= 500,
            }
        else:
            rules = {
                "missing": value.isna(),
                "lt_10000": value.notna() & (value < 10_000),
                "10000_to_30000": (value >= 10_000) & (value < 30_000),
                "30000_to_65000": (value >= 30_000) & (value < 65_000),
                "ge_65000": value >= 65_000,
            }
        return rules[cell]
    raise KeyError(hypothesis.key)


def crossed_edge_draws(
    frame: pd.DataFrame,
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> np.ndarray:
    cells = (
        frame.groupby(["target_date", "market_id"], sort=True)
        .agg(row_count=("edge_row", "size"), edge_sum=("edge_row", "sum"))
        .reset_index()
    )
    dates = sorted(cells["target_date"].unique())
    markets = sorted(cells["market_id"].unique())
    date_map = {value: index for index, value in enumerate(dates)}
    market_map = {value: index for index, value in enumerate(markets)}
    date_index = np.asarray([date_map[value] for value in cells["target_date"]], dtype=int)
    market_index = np.asarray([market_map[value] for value in cells["market_id"]], dtype=int)
    counts = cells["row_count"].to_numpy(dtype=float)
    edge = cells["edge_sum"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates, dtype=float)
    chunk = 500
    for start in range(0, replicates, chunk):
        size = min(chunk, replicates - start)
        date_draw = rng.integers(0, len(dates), size=(size, len(dates)))
        market_draw = rng.integers(0, len(markets), size=(size, len(markets)))
        date_counts = np.stack(
            [np.bincount(row, minlength=len(dates)) for row in date_draw]
        )
        market_counts = np.stack(
            [np.bincount(row, minlength=len(markets)) for row in market_draw]
        )
        weights = date_counts[:, date_index] * market_counts[:, market_index]
        denominators = weights @ counts
        numerators = weights @ edge
        draws[start : start + size] = np.divide(
            numerators,
            denominators,
            out=np.full(size, np.nan),
            where=denominators > 0,
        )
    if np.isnan(draws).any():
        raise RuntimeError("crossed bootstrap produced an empty replicate")
    return draws


def holm_adjust(raw_p_values: list[float]) -> list[float]:
    count = len(raw_p_values)
    order = np.argsort(np.asarray(raw_p_values, dtype=float))
    adjusted = np.ones(count, dtype=float)
    running = 0.0
    for rank, original_index in enumerate(order):
        candidate = min(1.0, (count - rank) * raw_p_values[int(original_index)])
        running = max(running, candidate)
        adjusted[int(original_index)] = running
    return adjusted.tolist()


def _omission_stability(frame: pd.DataFrame, column: str) -> float | None:
    values = sorted(frame[column].unique())
    if len(values) <= 1:
        return None
    positive = 0
    for value in values:
        scoped = frame[frame[column] != value]
        positive += float(scoped["edge_row"].mean()) > 0.0
    return positive / len(values)


def break_even_grid() -> pd.DataFrame:
    rows = []
    for adverse_move in (0.005, 0.01, 0.02, 0.045, 0.10):
        for informed_fraction in (0.10, 0.25, 0.50, 0.75, 1.00):
            for spread_capture in (0.001, 0.002, 0.005, 0.01, 0.0225):
                for fill_rate in (0.05, 0.25, 0.50, 1.00):
                    for price in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95):
                        rebate = 0.25 * 0.05 * price * (1.0 - price)
                        for liquidity_reward in (0.0, 0.20, 1.00):
                            for quote_size in (20, 50):
                                reward_per_fill = liquidity_reward / (
                                    2.0 * quote_size * fill_rate
                                )
                                required_edge = max(
                                    0.0,
                                    adverse_move
                                    - (spread_capture + rebate + reward_per_fill)
                                    / informed_fraction,
                                )
                                required_brier = (
                                    2.0 * adverse_move * required_edge - required_edge**2
                                )
                                ev_without_edge = (
                                    2.0
                                    * quote_size
                                    * fill_rate
                                    * (
                                        spread_capture
                                        + rebate
                                        - informed_fraction * adverse_move
                                    )
                                    + liquidity_reward
                                )
                                rows.append(
                                    {
                                        "adverse_move": adverse_move,
                                        "informed_fraction": informed_fraction,
                                        "spread_capture": spread_capture,
                                        "fill_rate": fill_rate,
                                        "price": price,
                                        "maker_rebate_per_share": rebate,
                                        "liquidity_reward_per_band_day": liquidity_reward,
                                        "quote_size_per_side": quote_size,
                                        "required_probability_edge": required_edge,
                                        "required_brier_edge": required_brier,
                                        "daily_ev_without_model_edge": ev_without_edge,
                                    }
                                )
    frame = pd.DataFrame(rows)
    if len(frame) != 21_000:
        raise AssertionError(f"break-even grid changed: {len(frame)}")
    return frame


def _positive_control(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    control = payload.get("positive_control") or {}
    required = (
        payload.get("status") == "PASS"
        and control.get("status") == "PASS"
        and int(control.get("rows") or 0) == 840
        and int(control.get("exact_rows") or 0) == 840
        and float(control.get("max_recorded_distribution_l1") or 0.0) == 0.0
    )
    if not required:
        raise RuntimeError("840/840 exact positive control did not pass")
    return payload


def analyze(
    *,
    band_rows_path: Path,
    predictor_sidecar_path: Path,
    predictor_thresholds_path: Path,
    predictor_manifest_path: Path,
    preregistration_path: Path,
    positive_control_path: Path,
    output_root: Path,
    replicates: int = BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    if sha256_file(band_rows_path) != BAND_ROWS_SHA256:
        raise RuntimeError("repaired band-row identity changed")
    prepared = json.loads(predictor_manifest_path.read_text(encoding="utf-8"))
    if prepared.get("status") != "PASS" or prepared.get("outcomes_read") is not False:
        raise RuntimeError("predictor preparation did not remain outcome-blind")
    if prepared["inputs"]["preregistration_sha256"] != sha256_file(preregistration_path):
        raise RuntimeError("pre-registration changed after predictor freeze")
    if prepared["outputs"]["predictor_sidecar_sha256"] != sha256_file(predictor_sidecar_path):
        raise RuntimeError("predictor sidecar changed")
    if prepared["outputs"]["predictor_thresholds_sha256"] != sha256_file(predictor_thresholds_path):
        raise RuntimeError("predictor thresholds changed")
    _positive_control(positive_control_path)
    positive_control_sha256 = sha256_file(positive_control_path)

    outcome_columns = [
        "snapshot_id",
        "record_hash",
        "target_date",
        "stratum",
        "market_id",
        "capture_hour",
        "effective_cutoff_hour",
        "band_index",
        "outcome",
        "served_replay_probability",
        "market_probability",
    ]
    outcomes = pd.read_csv(
        band_rows_path,
        usecols=outcome_columns,
        dtype={"snapshot_id": str, "record_hash": str, "target_date": str, "market_id": str},
        low_memory=False,
    ).rename(columns={"served_replay_probability": "repair_probability"})
    _validate_population(outcomes)
    predictors = pd.read_csv(
        predictor_sidecar_path,
        dtype={"snapshot_id": str, "record_hash": str, "target_date": str, "market_id": str},
        low_memory=False,
    )
    keys = [
        "snapshot_id",
        "record_hash",
        "target_date",
        "stratum",
        "market_id",
        "capture_hour",
        "effective_cutoff_hour",
        "band_index",
    ]
    probability_columns = ["repair_probability", "market_probability"]
    outcomes = outcomes.sort_values(keys).reset_index(drop=True)
    predictors = predictors.sort_values(keys).reset_index(drop=True)
    if not outcomes[keys].equals(predictors[keys]):
        raise RuntimeError("outcome/predictor roster differs")
    for column in probability_columns:
        if not np.array_equal(
            outcomes[column].to_numpy(dtype=float),
            predictors[column].to_numpy(dtype=float),
        ):
            raise RuntimeError(f"outcome/predictor quote evidence differs: {column}")
    frame = predictors.copy()
    frame["outcome"] = outcomes["outcome"].to_numpy(dtype=int)
    frame["model_squared_error"] = (
        frame["repair_probability"] - frame["outcome"]
    ) ** 2
    frame["market_squared_error"] = (
        frame["market_probability"] - frame["outcome"]
    ) ** 2
    frame["edge_row"] = frame["market_squared_error"] - frame["model_squared_error"]
    thresholds = json.loads(predictor_thresholds_path.read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    for index, hypothesis in enumerate(HYPOTHESES):
        scoped = frame[membership(frame, thresholds, hypothesis)].copy()
        if scoped.empty:
            rows.append(
                {
                    "hypothesis": hypothesis.key,
                    "axis": hypothesis.axis,
                    "cell": hypothesis.cell,
                    "band_rows": 0,
                    "snapshots": 0,
                    "date_clusters": 0,
                    "market_clusters": 0,
                    "market_days": 0,
                    "population_share": 0.0,
                    "model_brier": None,
                    "market_brier": None,
                    "edge": None,
                    "ci_low": None,
                    "ci_high": None,
                    "standard_error": None,
                    "raw_p": 1.0,
                    "raw_power_abs_effect": 0.05,
                    "family_power_abs_effect": FAMILY_ALPHA / len(HYPOTHESES),
                    "raw_80pct_mde": None,
                    "family_80pct_mde": None,
                    "lodo_positive_share": None,
                    "lomo_positive_share": None,
                    "valid_book_share": None,
                    "reward_window_share": None,
                }
            )
            continue
        point = float(scoped["edge_row"].mean())
        draws = crossed_edge_draws(
            scoped,
            replicates=replicates,
            seed=BOOTSTRAP_SEED + index,
        )
        se = float(draws.std(ddof=1))
        z = abs(point) / se if se > 0.0 else math.inf
        raw_critical = norm.ppf(1.0 - FAMILY_ALPHA)
        family_critical = norm.ppf(1.0 - FAMILY_ALPHA / len(HYPOTHESES))
        z_power = norm.ppf(0.80)
        raw_p = float(1.0 - norm.cdf(point / se)) if se > 0.0 else float(point <= 0.0)
        valid_book = scoped["book_spread"].notna()
        rows.append(
            {
                "hypothesis": hypothesis.key,
                "axis": hypothesis.axis,
                "cell": hypothesis.cell,
                "band_rows": len(scoped),
                "snapshots": scoped["snapshot_id"].nunique(),
                "date_clusters": scoped["target_date"].nunique(),
                "market_clusters": scoped["market_id"].nunique(),
                "market_days": scoped[["target_date", "market_id"]].drop_duplicates().shape[0],
                "population_share": len(scoped) / len(frame),
                "model_brier": float(scoped["model_squared_error"].mean()),
                "market_brier": float(scoped["market_squared_error"].mean()),
                "edge": point,
                "ci_low": float(np.quantile(draws, 0.025)),
                "ci_high": float(np.quantile(draws, 0.975)),
                "standard_error": se,
                "raw_p": raw_p,
                "raw_power_abs_effect": float(1.0 - norm.cdf(raw_critical - z)),
                "family_power_abs_effect": float(1.0 - norm.cdf(family_critical - z)),
                "raw_80pct_mde": float((raw_critical + z_power) * se),
                "family_80pct_mde": float((family_critical + z_power) * se),
                "lodo_positive_share": _omission_stability(scoped, "target_date"),
                "lomo_positive_share": _omission_stability(scoped, "market_id"),
                "valid_book_share": float(valid_book.mean()),
                "reward_window_share": float(
                    ((scoped.loc[valid_book, "book_spread"] <= 0.045).sum() / len(scoped))
                ),
            }
        )

    adjusted = holm_adjust([float(row["raw_p"]) for row in rows])
    for row, adjusted_p in zip(rows, adjusted):
        row["holm_adjusted_p"] = adjusted_p
        support_ok = (
            row["date_clusters"] >= 20
            and row["snapshots"] >= 100
            and row["band_rows"] >= 500
            and row["population_share"] >= 0.01
            and (row["axis"] == "market" or row["market_clusters"] >= 6)
        )
        stability_ok = (
            (row["lodo_positive_share"] or 0.0) >= 0.80
            and (
                row["market_clusters"] == 1
                or (row["lomo_positive_share"] or 0.0) >= 0.80
            )
        )
        statistical_ok = (
            row["edge"] is not None
            and row["edge"] > 0.0
            and row["ci_low"] > 0.0
            and adjusted_p <= FAMILY_ALPHA
            and row["family_power_abs_effect"] >= 0.80
        )
        row["support_ok"] = support_ok
        row["stability_ok"] = stability_ok
        row["statistical_ok"] = statistical_ok
        row["skill_candidate"] = support_ok and stability_ok and statistical_ok
        row["min_size_evidence"] = "ABSENT"
        row["quotable_candidate"] = False

    result_frame = pd.DataFrame(rows)
    economics = break_even_grid()
    zero_reward_economics = economics[
        economics["liquidity_reward_per_band_day"] == 0.0
    ]
    result_frame["economic_all_scenarios_cleared_share"] = [
        (
            float((economics["required_brier_edge"] <= edge).mean())
            if candidate and edge is not None
            else None
        )
        for edge, candidate in zip(
            result_frame["edge"], result_frame["skill_candidate"]
        )
    ]
    result_frame["economic_zero_reward_scenarios_cleared_share"] = [
        (
            float((zero_reward_economics["required_brier_edge"] <= edge).mean())
            if candidate and edge is not None
            else None
        )
        for edge, candidate in zip(
            result_frame["edge"], result_frame["skill_candidate"]
        )
    ]
    output_root.mkdir(parents=True, exist_ok=True)
    partitions_path = output_root / "partition-results.csv"
    economics_path = output_root / "break-even-grid.csv"
    summary_path = output_root / "analysis.json"
    for path in (partitions_path, economics_path, summary_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite {path}")
    result_frame.to_csv(partitions_path, index=False, lineterminator="\n")
    economics.to_csv(economics_path, index=False, lineterminator="\n")
    raw_winners = result_frame[
        (result_frame["edge"] > 0.0)
        & (result_frame["ci_low"] > 0.0)
        & (result_frame["raw_p"] <= FAMILY_ALPHA)
    ]
    adjusted_winners = result_frame[
        (result_frame["edge"] > 0.0)
        & (result_frame["holm_adjusted_p"] <= FAMILY_ALPHA)
    ]
    candidates = result_frame[result_frame["skill_candidate"]]
    verdict = "NO_ADJUSTED_EDGE"
    if not adjusted_winners.empty and candidates.empty:
        verdict = "EDGE_NOT_STABLE_OR_LARGE"
    elif not candidates.empty:
        verdict = "EDGE_NOT_QUOTABLE"
    overall_point = float(frame["edge_row"].mean())
    overall_draws = crossed_edge_draws(
        frame,
        replicates=replicates,
        seed=BOOTSTRAP_SEED - 1,
    )
    overall_se = float(overall_draws.std(ddof=1))
    summary = {
        "schema_version": "quotable_edge_analysis_v1",
        "status": "PASS",
        "verdict": verdict,
        "method": {
            "edge": "market Brier minus repaired served model Brier",
            "hypothesis_count": len(HYPOTHESES),
            "multiplicity": "Holm one-sided family-wise alpha 0.05",
            "uncertainty": "crossed target_date x market pigeonhole bootstrap",
            "bootstrap_replicates": replicates,
            "bootstrap_seed_base": BOOTSTRAP_SEED,
        },
        "support": {
            "date_clusters": frame["target_date"].nunique(),
            "market_clusters": frame["market_id"].nunique(),
            "market_days": frame[["target_date", "market_id"]].drop_duplicates().shape[0],
            "snapshots": frame["snapshot_id"].nunique(),
            "band_rows": len(frame),
        },
        "results": {
            "overall_reference": {
                "model_brier": float(frame["model_squared_error"].mean()),
                "market_brier": float(frame["market_squared_error"].mean()),
                "edge": overall_point,
                "crossed_95_interval": [
                    float(np.quantile(overall_draws, 0.025)),
                    float(np.quantile(overall_draws, 0.975)),
                ],
                "standard_error": overall_se,
                "raw_one_sided_p": (
                    float(1.0 - norm.cdf(overall_point / overall_se))
                    if overall_se > 0.0
                    else float(overall_point <= 0.0)
                ),
            },
            "positive_point_cells": int((result_frame["edge"] > 0.0).sum()),
            "raw_winners": int(len(raw_winners)),
            "holm_winners": int(len(adjusted_winners)),
            "skill_candidates": int(len(candidates)),
            "quotable_candidates": 0,
            "empty_cells": int((result_frame["band_rows"] == 0).sum()),
            "edge_distribution": {
                key: float(value)
                for key, value in result_frame["edge"].dropna().quantile(
                    [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0]
                ).items()
            },
            "top_by_edge": result_frame.sort_values("edge", ascending=False)
            .head(10)[
                [
                    "hypothesis",
                    "edge",
                    "ci_low",
                    "ci_high",
                    "raw_p",
                    "holm_adjusted_p",
                    "family_power_abs_effect",
                    "band_rows",
                    "date_clusters",
                    "market_clusters",
                    "support_ok",
                    "stability_ok",
                ]
            ]
            .to_dict("records"),
        },
        "quoteability": {
            "min_size_evidence": "ABSENT",
            "reason": "sealed tape has aggregate liquidity but no contemporaneous per-side size",
        },
        "economics": {
            "scenario_count": len(economics),
            "informed_fraction_measured": False,
            "adverse_move_measured": False,
            "required_brier_edge_min": float(economics["required_brier_edge"].min()),
            "required_brier_edge_median": float(economics["required_brier_edge"].median()),
            "required_brier_edge_max": float(economics["required_brier_edge"].max()),
            "zero_reward_required_brier_edge_min": float(
                economics.loc[economics["liquidity_reward_per_band_day"] == 0.0, "required_brier_edge"].min()
            ),
            "zero_reward_required_brier_edge_median": float(
                economics.loc[economics["liquidity_reward_per_band_day"] == 0.0, "required_brier_edge"].median()
            ),
            "zero_reward_required_brier_edge_max": float(
                economics.loc[economics["liquidity_reward_per_band_day"] == 0.0, "required_brier_edge"].max()
            ),
        },
        "evidence": {
            "preregistration_sha256": sha256_file(preregistration_path),
            "band_rows_sha256": sha256_file(band_rows_path),
            "predictor_sidecar_sha256": sha256_file(predictor_sidecar_path),
            "predictor_thresholds_sha256": sha256_file(predictor_thresholds_path),
            "predictor_manifest_sha256": sha256_file(predictor_manifest_path),
            "positive_control_sha256": positive_control_sha256,
            "partition_results_sha256": sha256_file(partitions_path),
            "break_even_grid_sha256": sha256_file(economics_path),
        },
    }
    _write_json(summary_path, summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="freeze quote-time predictors without outcomes")
    prepare.add_argument("--band-rows", type=Path, required=True)
    prepare.add_argument("--measurement-manifest", type=Path, required=True)
    prepare.add_argument("--snapshots-root", type=Path, required=True)
    prepare.add_argument("--preregistration", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    analyze_parser = subparsers.add_parser("analyze", help="run the frozen outcome analysis")
    analyze_parser.add_argument("--band-rows", type=Path, required=True)
    analyze_parser.add_argument("--predictor-sidecar", type=Path, required=True)
    analyze_parser.add_argument("--predictor-thresholds", type=Path, required=True)
    analyze_parser.add_argument("--predictor-manifest", type=Path, required=True)
    analyze_parser.add_argument("--preregistration", type=Path, required=True)
    analyze_parser.add_argument("--positive-control", type=Path, required=True)
    analyze_parser.add_argument("--output-root", type=Path, required=True)
    analyze_parser.add_argument("--replicates", type=int, default=BOOTSTRAP_REPLICATES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        payload = prepare_predictors(
            band_rows_path=args.band_rows,
            measurement_manifest_path=args.measurement_manifest,
            snapshots_root=args.snapshots_root,
            preregistration_path=args.preregistration,
            output_root=args.output_root,
        )
    else:
        payload = analyze(
            band_rows_path=args.band_rows,
            predictor_sidecar_path=args.predictor_sidecar,
            predictor_thresholds_path=args.predictor_thresholds,
            predictor_manifest_path=args.predictor_manifest,
            preregistration_path=args.preregistration,
            positive_control_path=args.positive_control,
            output_root=args.output_root,
            replicates=args.replicates,
        )
    print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
