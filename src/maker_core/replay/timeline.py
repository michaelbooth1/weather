"""Point-in-time record access; a provider receives a snapshot, not the future tape."""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime

from maker_core.contracts import utc_time
from maker_core.replay.bundle import Bundle, CapturedRecord


@dataclass(frozen=True)
class Snapshot:
    as_of: datetime
    records: tuple[CapturedRecord, ...]

    def latest(self, kind: str, condition_id: str) -> CapturedRecord | None:
        return next((row for row in reversed(self.records)
                     if row.kind == kind and row.condition_id == condition_id), None)


class Timeline:
    def __init__(self, bundle: Bundle):
        self._records = bundle.records
        self._times = tuple(row.captured_at for row in self._records)

    def at(self, as_of: datetime) -> Snapshot:
        utc_time(as_of)
        return Snapshot(as_of, self._records[:bisect_right(self._times, as_of)])
