"""Materialize literal outcome-firewall corpora for the H1 cold replay.

This utility is intentionally separate from both experiment runners.  It may
open a broader source manifest only to publish one deterministic, exact-date
manifest.  The tune and confirmation runners accept the derived manifest only;
they never deserialize the broader source or filter it after loading outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.execution_identity import atomic_write_json_exclusive
from weather.market.market_registry import REGISTRY
from weather.reporting.promotion.promotion_corpus import (
    PROMOTION_CORPUS_SCHEMA_VERSION,
    corpus_hash,
    load_manifest,
    summarize_entries,
)
from weather.schema_registry import schema_version


MAX_SOURCE_BYTES = 64 * 1024**2
LITERAL_PANEL_SCHEMA_VERSION = schema_version("ordinal_smoothing_literal_panel")
TUNE_DATES = (
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-07",
    "2026-06-08",
    "2026-06-09",
    "2026-06-10",
    "2026-06-11",
    "2026-06-12",
    "2026-06-13",
    "2026-06-14",
    "2026-06-15",
    "2026-06-16",
    "2026-06-17",
    "2026-06-19",
    "2026-06-20",
    "2026-06-21",
)
FRESH_DATES = (
    "2026-07-15",
    "2026-07-16",
    "2026-07-17",
    "2026-07-18",
    "2026-07-19",
)


class PanelMaterializationError(RuntimeError):
    """A source manifest cannot produce the preregistered literal panel."""


@dataclass(frozen=True)
class MaterializationContract:
    kind: str
    dates: tuple[str, ...]
    expected_entries: int
    source_file_sha256: str
    source_corpus_hash: str


CONTRACTS = {
    "tune": MaterializationContract(
        kind="tune",
        dates=TUNE_DATES,
        expected_entries=143,
        source_file_sha256=(
            "4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5"
        ),
        source_corpus_hash=(
            "d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f"
        ),
    ),
    "fresh": MaterializationContract(
        kind="fresh",
        dates=FRESH_DATES,
        expected_entries=60,
        source_file_sha256=(
            "4ff50585a1b2cbdb7bd1a5f4be633b7b3cecf5bba6a42f4109080d4c98c6d180"
        ),
        source_corpus_hash=(
            "1117ad38a60ef128f4881dbf6d89db36034a15d93b12fec586af75cfd2f3c288"
        ),
    ),
}


def _stable_sha256(path: Path) -> tuple[str, int]:
    before = path.stat()
    if not path.is_file() or before.st_size <= 0 or before.st_size > MAX_SOURCE_BYTES:
        raise PanelMaterializationError(f"source manifest is missing or too large: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        opened_before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        opened_after = os.fstat(handle.fileno())
    after = path.stat()

    def identity(value):
        return (
            int(value.st_dev),
            int(value.st_ino),
            int(value.st_nlink),
            int(value.st_size),
            int(value.st_mtime_ns),
            int(value.st_ctime_ns),
        )

    if not identity(before) == identity(opened_before) == identity(opened_after) == identity(after):
        raise PanelMaterializationError("source manifest changed while hashing")
    return digest.hexdigest(), int(after.st_size)


def _validate_entries(
    entries: Sequence[Mapping[str, Any]], contract: MaterializationContract
) -> list[dict[str, Any]]:
    selected = [
        dict(entry)
        for entry in entries
        if str(entry.get("target_date") or "") in set(contract.dates)
    ]
    if len(selected) != contract.expected_entries:
        raise PanelMaterializationError(
            f"{contract.kind} panel has {len(selected)} entries, expected "
            f"{contract.expected_entries}"
        )
    keys = []
    for entry in selected:
        market_id = str(entry.get("market_id") or "")
        target_date = str(entry.get("target_date") or "")
        event_slug = str(entry.get("event_slug") or "")
        relative = str(entry.get("folder_relative_to_snapshots_root") or "")
        if market_id not in REGISTRY or not target_date or not event_slug:
            raise PanelMaterializationError("derived panel contains incomplete entry identity")
        if relative != event_slug:
            raise PanelMaterializationError(
                f"entry folder identity differs from event slug: {market_id}/{target_date}"
            )
        keys.append((market_id, target_date, event_slug))
    if len(keys) != len(set(keys)):
        raise PanelMaterializationError("derived panel contains duplicate entry identity")
    observed_dates = tuple(sorted({key[1] for key in keys}))
    if observed_dates != contract.dates:
        raise PanelMaterializationError(
            f"derived panel date tuple differs: {observed_dates!r}"
        )
    if {key[0] for key in keys} != set(REGISTRY):
        raise PanelMaterializationError("derived panel does not cover all market families")
    if contract.kind == "fresh":
        exact = {(date, market_id) for date in contract.dates for market_id in REGISTRY}
        observed = {(key[1], key[0]) for key in keys}
        if observed != exact or len(observed) != len(keys):
            raise PanelMaterializationError("fresh panel is not exact 5x12")
    return sorted(selected, key=lambda row: str(row["event_slug"]))


def materialize_panel(
    *, kind: str, source_manifest: Path, output: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if kind not in CONTRACTS:
        raise PanelMaterializationError(f"unsupported materialization kind: {kind!r}")
    contract = CONTRACTS[kind]
    source = Path(source_manifest).expanduser().resolve(strict=True)
    target = Path(output).expanduser().resolve(strict=False)
    source_sha, source_size = _stable_sha256(source)
    if source_sha != contract.source_file_sha256:
        raise PanelMaterializationError("source manifest file hash differs from contract")
    loaded = load_manifest(source, max_bytes=MAX_SOURCE_BYTES)
    if loaded.get("corpus_hash") != contract.source_corpus_hash:
        raise PanelMaterializationError("source manifest corpus hash differs from contract")
    source_entries = list(loaded.get("entries") or [])
    selected = _validate_entries(source_entries, contract)
    selected_hash = corpus_hash(selected)
    manifest = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "as_of": loaded.get("as_of"),
        "admit_promotion_countable": bool(loaded.get("admit_promotion_countable")),
        "include_reconstructed": bool(loaded.get("include_reconstructed")),
        "allow_unsettled": bool(loaded.get("allow_unsettled")),
        "quality_grades": list(loaded.get("quality_grades") or []),
        "entries": selected,
        "summary": summarize_entries(selected),
        "skipped": [],
        "corpus_hash": selected_hash,
        "materialization": {
            "schema_version": LITERAL_PANEL_SCHEMA_VERSION,
            "kind": contract.kind,
            "dates": list(contract.dates),
            "entry_count": len(selected),
            "source_manifest_name": source.name,
            "source_manifest_sha256": source_sha,
            "source_manifest_size_bytes": source_size,
            "source_corpus_hash": contract.source_corpus_hash,
            "source_entry_count": len(source_entries),
            "excluded_entry_count": len(source_entries) - len(selected),
            "outcome_firewall": (
                "experiment runner must load only this exact-date derived manifest"
            ),
        },
    }
    atomic_write_json_exclusive(target, manifest)
    output_sha, output_size = _stable_sha256(target)
    receipt = {
        "path": str(target),
        "sha256": output_sha,
        "size_bytes": output_size,
        "corpus_hash": selected_hash,
        "entry_count": len(selected),
        "dates": list(contract.dates),
    }
    return manifest, receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=tuple(CONTRACTS))
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _, receipt = materialize_panel(
            kind=args.kind,
            source_manifest=Path(args.source_manifest),
            output=Path(args.output),
        )
    except (PanelMaterializationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"literal panel materialization blocked: {exc}")
        return 2
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
