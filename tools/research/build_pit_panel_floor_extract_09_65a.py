r"""Build the -09-65a panel-floor handback from the retained paired panel.

The paired panel is ignored workstation evidence.  It carries the exact B/C
snapshot roster and the repair/control realized-band probabilities, but it
does not carry any floor field.  This exporter therefore leaves
``floor_bucket`` and ``floor_source_field`` empty on every row.  It does not
reconstruct a floor and present that derived value as panel provenance.

Band identity is restored by an exact-key join to the retained repaired
``band-score-rows.csv`` from the same -09-44a run.  Only the ``outcome == 1``
row is used to identify the realized band; no outcome value is emitted.

The CSV is capped at 1,000,000 bytes.  Probabilities use nine significant
digits so all 12,289 rows fit without dropping any row.  The manifest reports
the maximum absolute serialization error rather than hiding the precision
choice.

Run from the repository root with the bundled Codex Python 3.12 runtime:

    C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe `
      .\tools\research\build_pit_panel_floor_extract_09_65a.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_PAIRED = (
    REPO
    / "scratch"
    / "runs"
    / "gap-remeasure-repaired-2026-09-44a"
    / "paired-band-rows.csv"
)
DEFAULT_BANDS = (
    REPO
    / "scratch"
    / "runs"
    / "gap-remeasure-repaired-2026-09-44a"
    / "band-score-rows.csv"
)
DEFAULT_OUTPUT = REPO / "docs" / "roadmap" / "pit-panel-floor-2026-09-65a.csv"
DEFAULT_MANIFEST = (
    REPO / "docs" / "roadmap" / "pit-panel-floor-2026-09-65a-manifest.json"
)
DEFAULT_SHA256 = REPO / "docs" / "roadmap" / "pit-panel-floor-2026-09-65a.sha256"

EXPECTED_PAIRED_SHA256 = "4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88"
EXPECTED_BANDS_SHA256 = "9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae"
EXPECTED_BAND_ROWS = 135_179
EXPECTED_SNAPSHOTS = 12_289
EXPECTED_BY_STRATUM = {"B": 4_636, "C": 7_653}
REGIME_BOUNDARY = "2026-07-31"
MAX_OUTPUT_BYTES = 1_000_000
PROBABILITY_SIGNIFICANT_DIGITS = 9

KEY_COLUMNS = [
    "snapshot_id",
    "record_hash",
    "target_date",
    "stratum",
    "market_id",
    "capture_hour",
    "effective_cutoff_hour",
    "band_index",
    "outcome",
]
OUTPUT_COLUMNS = [
    "stratum",
    "market_id",
    "target_date",
    "snapshot_id",
    "floor_bucket",
    "floor_source_field",
    "realized_band_kind",
    "realized_band_value",
    "realized_band_value_hi",
    "repair_probability",
    "control_probability",
]
RECOGNIZED_FLOOR_COLUMNS = {
    "floor_bucket",
    "observed_floor_bucket",
    "high_so_far",
    "feature_high_so_far",
    "printed_observed_floor_bucket",
}
RANGE_RE = re.compile(
    r"[-+]?\d+(?:\.\d+)?\s*(?:-|\N{EN DASH})\s*([-+]?\d+(?:\.\d+)?)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired", type=Path, default=DEFAULT_PAIRED)
    parser.add_argument("--bands", type=Path, default=DEFAULT_BANDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sha256", type=Path, default=DEFAULT_SHA256)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames is not None, f"missing CSV header: {path}")
        return list(reader.fieldnames), list(reader)


def key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "") for column in KEY_COLUMNS)


def compact_number(value: str) -> str:
    number = float(value)
    require(math.isfinite(number), f"non-finite band value: {value!r}")
    if abs(number - round(number)) < 1e-12:
        return str(int(round(number)))
    return format(number, ".12g")


def band_value_hi(row: dict[str, str]) -> str:
    explicit = str(row.get("bin_value_hi") or "").strip()
    if explicit:
        return compact_number(explicit)
    label = str(row.get("range_label") or "")
    match = RANGE_RE.search(label)
    if match:
        return compact_number(match.group(1))
    return compact_number(str(row.get("bin_value") or ""))


def probability(value: str) -> tuple[str, float]:
    original = float(value)
    require(math.isfinite(original) and 0.0 <= original <= 1.0, f"invalid probability: {value}")
    serialized = format(original, f".{PROBABILITY_SIGNIFICANT_DIGITS}g")
    return serialized, abs(float(serialized) - original)


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> int:
    args = parse_args()
    paired = args.paired.resolve()
    bands = args.bands.resolve()
    output = args.output.resolve()
    manifest_path = args.manifest.resolve()
    sha_path = args.sha256.resolve()

    require(paired.is_file(), f"paired panel not found: {paired}")
    require(bands.is_file(), f"repaired band rows not found: {bands}")
    paired_hash = sha256(paired)
    bands_hash = sha256(bands)
    require(paired_hash == EXPECTED_PAIRED_SHA256, f"paired panel hash drifted: {paired_hash}")
    require(bands_hash == EXPECTED_BANDS_SHA256, f"band rows hash drifted: {bands_hash}")

    paired_fields, paired_rows = read_rows(paired)
    band_fields, band_rows = read_rows(bands)
    require(len(paired_rows) == EXPECTED_BAND_ROWS, "paired band-row count drifted")
    require(len(band_rows) == EXPECTED_BAND_ROWS, "repaired band-row count drifted")
    require(set(KEY_COLUMNS) <= set(paired_fields), "paired panel lacks key/outcome columns")
    require(set(KEY_COLUMNS) <= set(band_fields), "repaired band rows lack key/outcome columns")
    require(
        {"repair_probability", "control_probability"} <= set(paired_fields),
        "paired panel lacks repair/control probabilities",
    )
    require(
        {"range_label", "bin_kind", "bin_value", "bin_value_hi"} <= set(band_fields),
        "repaired band rows lack band identity columns",
    )

    floor_columns = sorted(RECOGNIZED_FLOOR_COLUMNS & set(paired_fields))
    require(
        not floor_columns,
        "paired panel unexpectedly gained a floor column; audit and export it rather than leaving blanks",
    )

    bands_by_key: dict[tuple[str, ...], dict[str, str]] = {}
    for row in band_rows:
        row_key = key(row)
        require(row_key not in bands_by_key, f"duplicate repaired band key: {row_key}")
        bands_by_key[row_key] = row
    require(len(bands_by_key) == EXPECTED_BAND_ROWS, "repaired band key cardinality drifted")

    winners: list[dict[str, str]] = []
    winner_counts: Counter[tuple[str, str, str, str]] = Counter()
    max_probability_error = 0.0
    for row in paired_rows:
        require(str(row.get("target_date") or "") < REGIME_BOUNDARY, "post-boundary row entered panel")
        if str(row.get("outcome") or "") != "1":
            continue
        band = bands_by_key.get(key(row))
        require(band is not None, f"realized row missing from repaired band export: {key(row)}")
        require(str(band.get("outcome") or "") == "1", "paired/repaired outcome identity differs")
        repair, repair_error = probability(str(row["repair_probability"]))
        control, control_error = probability(str(row["control_probability"]))
        max_probability_error = max(max_probability_error, repair_error, control_error)
        snapshot_key = (
            str(row["stratum"]),
            str(row["market_id"]),
            str(row["target_date"]),
            str(row["snapshot_id"]),
        )
        winner_counts[snapshot_key] += 1
        winners.append(
            {
                "stratum": snapshot_key[0],
                "market_id": snapshot_key[1],
                "target_date": snapshot_key[2],
                "snapshot_id": snapshot_key[3],
                "floor_bucket": "",
                "floor_source_field": "",
                "realized_band_kind": str(band.get("bin_kind") or "eq").strip().lower(),
                "realized_band_value": compact_number(str(band.get("bin_value") or "")),
                "realized_band_value_hi": band_value_hi(band),
                "repair_probability": repair,
                "control_probability": control,
            }
        )

    require(len(winners) == EXPECTED_SNAPSHOTS, f"winner count drifted: {len(winners)}")
    require(all(count == 1 for count in winner_counts.values()), "snapshot lacks exactly one winner")
    require(len(winner_counts) == EXPECTED_SNAPSHOTS, "snapshot key cardinality drifted")
    support = Counter(row["stratum"] for row in winners)
    require(dict(support) == EXPECTED_BY_STRATUM, f"stratum support drifted: {dict(support)}")
    require(all(not row["floor_bucket"] for row in winners), "derived floor leaked into extract")
    require(all(not row["floor_source_field"] for row in winners), "derived floor source leaked into extract")

    winners.sort(
        key=lambda row: (
            row["stratum"],
            row["market_id"],
            row["target_date"],
            row["snapshot_id"],
        )
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(winners)
    payload = stream.getvalue().encode("utf-8")
    require(
        len(payload) < MAX_OUTPUT_BYTES,
        f"complete extract is {len(payload)} bytes, at/above the {MAX_OUTPUT_BYTES}-byte cap; refusing to trim rows",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    extract_hash = hashlib.sha256(payload).hexdigest()

    manifest: dict[str, Any] = {
        "artifact": "pit_panel_floor_v1",
        "built_for": "-09-65a panel-floor provenance audit",
        "extract_sha256": extract_hash,
        "extract_rows": len(winners),
        "extract_bytes": len(payload),
        "max_extract_bytes_exclusive": MAX_OUTPUT_BYTES,
        "columns": OUTPUT_COLUMNS,
        "input": {
            "paired_panel": {
                "relative_path": relative(paired),
                "sha256": paired_hash,
                "band_rows": len(paired_rows),
            },
            "repaired_band_rows": {
                "relative_path": relative(bands),
                "sha256": bands_hash,
                "band_rows": len(band_rows),
                "purpose": "restore the realized band's kind/value/value_hi by exact row-key join",
            },
        },
        "support": {
            "B": {"snapshots": support["B"]},
            "C": {"snapshots": support["C"]},
            "total_snapshots": len(winners),
            "strata_reported_separately": True,
            "pooled_across_2026_07_31": False,
            "latest_target_date": max(row["target_date"] for row in winners),
            "regime_boundary": REGIME_BOUNDARY,
        },
        "floor_provenance": {
            "panel_carries_floor_column": False,
            "recognized_floor_columns_checked": sorted(RECOGNIZED_FLOOR_COLUMNS),
            "recognized_floor_columns_present": floor_columns,
            "floor_bucket_output": "empty on all rows",
            "floor_source_field_output": "empty on all rows",
            "derived_floor_exported": False,
            "reason": (
                "The retained paired panel has no floor/high_so_far column. A later reconstruction "
                "from captured replay inputs would not be a floor carried by the panel."
            ),
        },
        "realized_band_identity": {
            "selection": "the sole paired row with outcome == 1 per snapshot",
            "outcome_value_emitted": False,
            "value_hi_rule": (
                "explicit bin_value_hi when present; otherwise parse the upper endpoint from "
                "range_label; otherwise use value, matching snapshot_band_key/band_identity"
            ),
        },
        "probability_serialization": {
            "significant_digits": PROBABILITY_SIGNIFICANT_DIGITS,
            "max_absolute_error": max_probability_error,
            "reason": "retain every snapshot below the explicit 1,000,000-byte artifact cap",
        },
        "contains_market_prices": False,
        "contains_fitted_quantities": False,
        "contains_outcomes_beyond_realized_band_identity": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sha_path.write_text(
        f"{extract_hash}  {output.name}\n",
        encoding="utf-8",
        newline="\n",
    )

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
