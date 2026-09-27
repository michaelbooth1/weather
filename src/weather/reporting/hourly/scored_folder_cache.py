"""Rebuildable JSON cache shared by hourly and ten-minute scoring."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from weather.io import write_json_atomic


def input_signature(paths):
    result = []
    for path in paths:
        path = Path(path).resolve()
        stat = path.stat() if path.exists() else None
        result.append([str(path), stat.st_size if stat else None,
                       stat.st_mtime_ns if stat else None])
    return result


def cached_score(folder, label, thresholds, schema, score):
    folder = Path(folder)
    paths = [folder / "snapshots_long.csv", folder / "features_long.csv"]
    # Changes to scoring code invalidate warm caches without waiting for a
    # report-schema bump. The label and thresholds are inputs as well.
    import weather.backtesting.tape_scoring as tape_scoring
    import weather.scoring.metrics as metrics
    import weather.market.market_registry as registry
    import weather.units as units

    paths.extend([Path(score.__code__.co_filename), Path(tape_scoring.__file__),
                  Path(metrics.__file__), Path(registry.__file__), Path(units.__file__)])
    inputs = input_signature(paths)
    key = {"format": 1, "scorer_schema": schema, "inputs": inputs,
           "label": label, "thresholds": list(thresholds)}
    digest = hashlib.sha256(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()
    cache_path = folder / ".scored_rows_cache.json"
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        payload = cached["payload"]
        if (cached["key"] == digest and isinstance(payload, list) and len(payload) == 2
                and isinstance(payload[0], list) and isinstance(payload[1], dict)
                and all(isinstance(row, dict) for row in payload[0])
                and cached["sha256"] == hashlib.sha256(
                    json.dumps(payload, sort_keys=True, allow_nan=True).encode()).hexdigest()):
            return payload[0], payload[1]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    result = score(folder, label, thresholds)
    if input_signature(paths) == inputs:
        try:
            # No pickle or lossy default=str conversion of scored rows.
            encoded = json.dumps(result, sort_keys=True, allow_nan=True)
            write_json_atomic(cache_path, {"key": digest, "payload": json.loads(encoded),
                                          "sha256": hashlib.sha256(encoded.encode()).hexdigest()})
        except (OSError, TypeError, ValueError):
            pass  # A missing/unwritable cache never replaces a scoring result.
    return result
