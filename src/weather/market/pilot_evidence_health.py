"""Small physically reserved health banks, independent of chunk finalization."""
from __future__ import annotations

import json
import hashlib
import os

BANK_BYTES = 512 * 1024


def receipt_digest(receipt):
    body = {k: v for k, v in receipt.items() if k != "health_receipt_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


class HealthFile:
    """Overwrite existing allocated bytes; no rename/allocation on ENOSPC.

    Only these two small health banks are reserved, never the output budget.
    The previous bank retains the prior valid receipt if a write is torn. A
    hardware/filesystem failure can still make both unreadable: fail closed.
    """
    def __init__(self, root):
        self.streams = [(root / name).open("x+b", buffering=0)
                        for name in ("health.previous.json", "health.json")]
        self.last = {"final": False, "phase": "starting", "coverage_ready": False}
        self.failed = False
        for stream in self.streams:
            self.write_bank(stream, self.last)

    @classmethod
    def existing(cls, root):
        result = cls.__new__(cls)
        result.streams = [(root / name).open("r+b", buffering=0)
                          for name in ("health.previous.json", "health.json")]
        result.last = {"final": False, "coverage_ready": False}
        result.failed = False
        return result

    @staticmethod
    def write_bank(stream, receipt):
        checked = {**receipt, "health_receipt_sha256": receipt_digest(receipt)}
        raw = json.dumps(checked, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) >= BANK_BYTES:
            raise ValueError("health bank capacity; coverage cannot be certified")
        stream.seek(0)
        data = raw + b" " * (BANK_BYTES - len(raw) - 1) + b"\n"
        while data:
            written = stream.write(data)
            if not written:
                raise OSError("health write failed")
            data = data[written:]
        os.fsync(stream.fileno())

    def write(self, receipt):
        # The final receipt is written to canonical health BEFORE any chunk work.
        primary_ok = True
        try:
            self.write_bank(self.streams[1], receipt)
        except OSError:
            primary_ok = False
            self.failed = True
            receipt.update(success=False, storage_failed=True, health_bank_failure=True)
            receipt.setdefault("gaps", {})["health_bank_failure"] = 1
        try:
            # If canonical failed, the fallback must contain THIS receipt,
            # not merely an old non-final snapshot.
            self.write_bank(self.streams[0], self.last if primary_ok else receipt)
        except OSError:
            self.failed = True
            receipt.update(success=False, storage_failed=True, health_bank_failure=True)
            receipt.setdefault("gaps", {})["health_bank_failure"] = 1
            if not primary_ok:
                raise OSError("both reserved health banks unwritable") from None
            self.write_bank(self.streams[1], receipt)
        self.last = dict(receipt)

    def close(self):
        for stream in self.streams:
            stream.close()
