"""Read retired snapshot CSV views from canonical JSONL without materializing tapes.

Existing CSVs win, preserving historical settlement hashes. New days use the
canonical file's real path and hash. This module never writes or removes data.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path

from weather.cold_archive_locations import resolve_local_path

PROJECTIONS = {
    "snapshots_long.csv": "snapshots.jsonl",
    "features_long.csv": "features.jsonl",
    "variant_predictions_long.csv": "variant_predictions.jsonl",
    "snapshot_explanations_long.csv": "snapshot_explanations.jsonl",
}


def _decode_record(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate canonical JSON object key: " + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def projection_source(path):
    """Resolve a logical CSV view to its existing historical or canonical source."""
    path = Path(path)
    local = resolve_local_path(path)
    if local.exists() or path.name not in PROJECTIONS:
        return local
    canonical = resolve_local_path(path.with_name(PROJECTIONS[path.name]))
    return canonical if canonical.exists() else path


def projection_glob(root, pattern):
    """Discover both representations, once per event folder, CSV first."""
    root = Path(root)
    name = Path(pattern).name
    paths = list(root.glob(pattern))
    if name in PROJECTIONS:
        other = pattern[:-len(name)] + PROJECTIONS[name]
        by_folder = {path.parent: path for path in paths}
        for path in root.glob(other):
            by_folder.setdefault(path.parent, path)
        paths = list(by_folder.values())
    return iter(sorted(paths))


def explanation_rows(base, explanation):
    """The capture writer and canonical reader share this flattening contract."""
    def row(section, key, subkey, value):
        number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        boolean = value if isinstance(value, bool) else None
        nested = isinstance(value, (dict, list))
        payload = json.dumps(value, sort_keys=True, default=str) if nested else ""
        return {**base, "section": section, "item_key": key, "item_subkey": subkey,
                "value_text": None if value is None or nested else str(value),
                "value_number": number, "value_bool": boolean, "payload_json": payload,
                "payload_hash": hashlib.sha1(payload.encode("utf-8")).hexdigest() if nested else ""}
    for section, value in sorted((explanation or {}).items()):
        if isinstance(value, dict):
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
                yield row(section, key, None, item)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                key = str(index)
                if isinstance(item, dict):
                    key = next((str(item[k]) for k in
                                ("source", "family", "name", "bucket", "Driver", "Question", "stage", "gate")
                                if item.get(k) not in (None, "")), key)
                yield row(section, key, None, item)
                if isinstance(item, dict):
                    for subkey, subvalue in sorted(item.items(), key=lambda pair: str(pair[0])):
                        if subvalue is None or isinstance(subvalue, (str, int, float, bool)):
                            yield row(section, key, subkey, subvalue)
        else:
            yield row(section, "value", None, value)


def project_record(name, record):
    if not isinstance(record, dict):
        raise ValueError("canonical projection record must be an object")
    if name == "snapshots.jsonl":
        rows = record.get("bands")
        if not isinstance(rows, list):
            raise ValueError("canonical snapshot is missing its bands array")
    elif name == "snapshot_explanations.jsonl":
        excluded = {"schema_version", "runtime_identity", "model_identity", "explanation_hash",
                    "sections", "row_count", "explanations"}
        if not isinstance(record.get("explanations"), dict):
            raise ValueError("canonical explanation is missing its explanations object")
        rows = explanation_rows({k: v for k, v in record.items() if k not in excluded}, record["explanations"])
    else:
        rows = [record]
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("canonical projected row must be an object")
        # csv.DictReader's scalar contract; preserve capture's unit spelling.
        yield {key: "" if value is None else str(value) for key, value in row.items()}


def canonical_rows(path):
    path = projection_source(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for line in stream:
            if not line.endswith("\n"):
                raise ValueError("incomplete canonical JSONL record")
            if line.strip():
                yield from project_record(path.name, _decode_record(line))


def projection_bytes_view(path, raw):
    """Parse one already bounded, hash-bound input without reopening its source."""
    if Path(path).name not in PROJECTIONS.values():
        return io.StringIO(raw.decode("utf-8-sig"), newline="")
    def rows():
        for line in io.BytesIO(raw):
            if not line.endswith(b"\n"):
                raise ValueError("incomplete canonical JSONL record")
            if line.strip():
                yield from project_record(Path(path).name, _decode_record(line))
    return _CsvView(rows())


class _CsvView(io.TextIOBase):
    """Streaming text view for legacy csv/Pandas parsers; no filesystem output."""
    def __init__(self, rows):
        super().__init__()
        self._rows = iter(rows)
        self._buffer = ""
        self._lines = self._generate()

    def _generate(self):
        first = next(self._rows, None)
        if first is None:
            return
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(first), extrasaction="raise")
        writer.writeheader()
        writer.writerow(first)
        yield buffer.getvalue()
        for row in self._rows:
            buffer.seek(0)
            buffer.truncate()
            writer.writerow(row)
            yield buffer.getvalue()

    def readable(self):
        return True

    def read(self, size=-1):
        while size < 0 or len(self._buffer) < size:
            chunk = next(self._lines, None)
            if chunk is None:
                break
            self._buffer += chunk
        result = self._buffer if size < 0 else self._buffer[:size]
        self._buffer = "" if size < 0 else self._buffer[size:]
        return result

    def readline(self, size=-1):
        while "\n" not in self._buffer:
            chunk = next(self._lines, None)
            if chunk is None:
                break
            self._buffer += chunk
        end = self._buffer.find("\n") + 1 or len(self._buffer)
        if size >= 0:
            end = min(end, size)
        result, self._buffer = self._buffer[:end], self._buffer[end:]
        return result

    def close(self):
        self._rows.close()
        super().close()


def open_projection(path, mode="r", *args, **kwargs):
    """Open a read-only CSV view; binary reads always bind the real source bytes."""
    if mode not in {"r", "rt", "rb"}:
        raise ValueError("projection views are read-only")
    source = projection_source(path)
    if mode in {"r", "rt"} and source.name in PROJECTIONS.values():
        return _CsvView(canonical_rows(source))
    return source.open(mode, *args, **kwargs)


def read_projection_frame(path, *args, **kwargs):
    import pandas as pd
    if isinstance(path, (str, Path)):
        source = projection_source(path)
        if source.name in PROJECTIONS.values():
            with open_projection(source) as stream:
                return pd.read_csv(stream, *args, **kwargs)
        path = source
    return pd.read_csv(path, *args, **kwargs)


def canonical_tail(path, *, max_bytes, diagnostics):
    """Read at most max_bytes of complete JSONL records; never scan for a header."""
    path = projection_source(path)
    rows = []
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            size = before.st_size
            start = max(0, size - max(1, int(max_bytes)))
            handle.seek(start)
            raw = handle.read(size - start)
            after = os.fstat(handle.fileno())
        diagnostics.update(file_size_bytes=size, captured_mtime_ns=before.st_mtime_ns,
                           read_bytes=len(raw), scanned_bytes=len(raw), reached_start=start == 0)
        stable = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        diagnostics["stable_during_read"] = stable
        if not stable:
            diagnostics["status"] = "changed_during_read"
            return [], diagnostics
        if raw and not raw.endswith(b"\n"):
            diagnostics["status"] = "incomplete_tail"
            return [], diagnostics
        if start:
            end = raw.find(b"\n") + 1
            diagnostics["boundary_discarded_bytes"] = end
            raw = raw[end:]
        for line in raw.decode("utf-8-sig").splitlines():
            if line.strip():
                rows.extend(project_record(path.name, _decode_record(line)))
        diagnostics.update(status="ok" if rows else "empty", row_count=len(rows),
                           fieldnames=list(rows[0]) if rows else [], source_path=str(path))
        return rows, diagnostics
    except (OSError, UnicodeError, ValueError) as exc:
        diagnostics.update(status="read_error", error=f"{type(exc).__name__}: {exc}")
        return [], diagnostics
