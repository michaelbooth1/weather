"""HARNESS v3 outcome-free input layout. This module knows NO label or market file name.

A v3 layout directory holds ``manifest.json`` (schema ``harness_v3_layout/1``) plus files that the
manifest describes with sha256, row count and the exact list of target dates they contain. The
outcome-free files are read here; label and market files are read only by ``v3_outcomes`` and must
never be imported by the dry-run path (H2).

Every read goes through one Python ``open`` call on bytes that are sha256-checked against the
manifest, then parsed from memory, so an audit hook sees every file this module touches. A file is
opened only after the gate allows every date the manifest says it contains for the request's
(family, purpose); a refused date makes the whole file unreadable for that request.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

LAYOUT_SCHEMA = "harness_v3_layout/1"
MANIFEST = "manifest.json"
INPUT_FILES = {"snapshots": "inputs_snapshots.parquet", "bands": "inputs_bands.parquet"}
FLOOR_FIELDS = ("guidance_physical_floor", "high_so_far", "trusted_current_max")
BLOCKS = (("00-05", 0, 5), ("06-09", 6, 9), ("10-12", 10, 12), ("13-16", 13, 16), ("17-23", 17, 23))
AGGREGATES = (("00-16", 0, 16), ("all", 0, 23))
GROUPS = BLOCKS + AGGREGATES


class LayoutError(RuntimeError):
    pass


def read_manifest(root):
    root = Path(root)
    with open(root / MANIFEST, "rb") as stream:
        manifest = json.loads(stream.read().decode("utf-8"))
    if manifest.get("schema") != LAYOUT_SCHEMA:
        raise LayoutError(f"layout manifest schema {manifest.get('schema')!r}")
    return manifest


def read_verified(root, name, manifest):
    """Open ``name`` once, check its sha256 against the manifest, return the bytes."""
    entry = manifest["files"].get(name)
    if entry is None:
        raise LayoutError(f"{name} is not in the layout manifest")
    with open(Path(root) / name, "rb") as stream:
        data = stream.read()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise LayoutError(f"{name} does not match its manifest sha256")
    return data


def gate_file(gate, manifest, name, family, purpose, reads_nbm_guidance):
    """Every date a file holds must pass the gate before the file is opened."""
    return gate.require(family, manifest["files"][name]["dates"], purpose, reads_nbm_guidance)


def read_inputs(root, gate, family, reads_nbm_guidance, purpose="coverage"):
    """Allow-listed snapshot and band tables (no labels, no market). Gate-checked per file."""
    manifest = read_manifest(root)
    tables = {}
    for key, name in INPUT_FILES.items():
        gate_file(gate, manifest, name, family, purpose, reads_nbm_guidance)
        tables[key] = pd.read_parquet(io.BytesIO(read_verified(root, name, manifest)))
    snaps, bands = tables["snapshots"], tables["bands"]
    if snaps.row_key.duplicated().any():
        raise LayoutError("duplicate row_key in inputs_snapshots")
    n = snaps.n_bands.to_numpy()
    if len(bands) != int(n.sum()) or not (bands.row_key.to_numpy()[
            _offsets(n)] == snaps.row_key.to_numpy()).all():
        raise LayoutError("inputs_bands is not contiguous per snapshot in snapshot order")
    return snaps, bands, manifest


def _offsets(n):
    return np.concatenate([[0], np.cumsum(n)[:-1]]).astype(int)


def group_mask(local_hour, group):
    low, high = next((lo, hi) for name, lo, hi in GROUPS if name == group)
    return (local_hour >= low) & (local_hour <= high)
