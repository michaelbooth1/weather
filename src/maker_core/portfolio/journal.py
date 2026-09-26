"""Create-only per-run records with a verified hash chain; paths are explicit."""
import hashlib
import json
import os
from pathlib import Path

from maker_core.contracts.portfolio import LEDGER_SCHEMA
from maker_core.evidence.journal import canonical_bytes, digest


def verify_records(directory):
    previous, records = None, []
    for index, path in enumerate(sorted(Path(directory).glob("*.json"))):
        if path.is_symlink() or path.name != f"{index:08d}.json":
            raise ValueError("ledger_sequence_invalid")
        raw = path.read_bytes()
        row = json.loads(raw)
        if (row.get("schema_version") != LEDGER_SCHEMA or row.get("sequence") != index
                or row.get("previous_sha256") != previous or canonical_bytes(row) != raw
                or row.get("book_sha256") != digest(row.get("book"))):
            raise ValueError("ledger_chain_invalid")
        previous = hashlib.sha256(raw).hexdigest()
        records.append(row)
    return records, previous


def append_book(directory, book):
    """Release only this writer's lock, never another process's lock."""
    directory = Path(directory)
    # Acquire ownership by exclusive creation; never remove a pre-existing lock.
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("ledger_directory_redirected")
    lock = directory / ".writer.lock"
    handle = lock.open("xb")
    try:
        records, previous = verify_records(directory)
        book_hash = digest(book)
        if any(row["book_sha256"] == book_hash for row in records):
            raise FileExistsError("ledger_book_already_recorded")
        row = dict(schema_version=LEDGER_SCHEMA, sequence=len(records),
                   previous_sha256=previous, book_sha256=book_hash, book=book)
        raw = canonical_bytes(row)
        path = directory / f"{len(records):08d}.json"
        with path.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), book_sha256=book_hash)
    finally:
        handle.close()
        lock.unlink()
