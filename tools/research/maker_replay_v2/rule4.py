"""Rule 4 = option B (owner, 2026-10-05): fictional real-cadence views and the S5-style equivalence harness.

The real exporter re-stamps every outcome view at every evaluation: ``as_of_utc`` is the evaluation time,
and on the NBP path ``stdev = sqrt(p(1-p)) * (age since issue in days + 0.25)`` moves with it. W0's day and
the dense day refresh views only on content changes. ``restamped`` reproduces the real cadence on any
fictional day: after each of a condition's book records it re-emits the condition's latest available view
with ``as_of_utc`` = that capture time, and

- ``restamp``: nothing else changes (an as_of-only change);
- ``drift``: ``stdev`` also grows with the view's age as the NBP path's does (x(1 + 4 * age in days));
- ``pjump``: ``drift``, and every 7th re-stamp of a condition moves ``p_yes`` by 0.01 and keeps every other
  field, ``inputs_hash`` included (a content change that must wake).

Each row is labelled time-only or not, independently of the engine. ``lazy`` moves every time-only row to
the condition's next wake instant of a given run (dropping it after the last), which is how option B claims
to read it; a run under the registered rule (payload hash) on the lazy rows must then equal the option-B run
on the eager rows, decision for decision. ``WakeLog`` records a run's wake instants.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
import hashlib

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.v2.engine import EngineV2

MODES = ("restamp", "drift", "pjump")


def restamped(rows, mode="drift"):
    """``(row, time_only)`` pairs: exporter-ordered v0.1 rows plus re-stamped views, renumbered."""
    if mode not in MODES:
        raise ValueError("unknown mode")
    latest, issued, count, out = {}, {}, {}, []
    for row in rows:
        out.append((row, False))
        cid = row["condition_id"]
        if row["kind"] == "outcome_view":
            value = row["payload"].get("value")
            if row["payload"].get("available") is True and isinstance(value, dict):
                latest[cid], issued[cid] = dict(value), datetime.fromisoformat(value["as_of_utc"])
            else:
                latest.pop(cid, None)
            continue
        if row["kind"] != "book" or cid not in latest:
            continue
        at = datetime.fromisoformat(row["captured_at"])
        if not issued[cid] < at < datetime.fromisoformat(latest[cid]["valid_until_utc"]):
            continue
        value, time_only = dict(latest[cid], as_of_utc=at.isoformat()), True
        if mode in ("drift", "pjump"):
            age_days = (at - issued[cid]).total_seconds() / 86400
            value["stdev"] = round(float(latest[cid]["stdev"]) * (1 + 4 * age_days), 12)
        if mode == "pjump":
            count[cid] = count.get(cid, 0) + 1
            if count[cid] % 7 == 0:
                p = float(latest[cid]["p_yes"])
                latest[cid]["p_yes"] = value["p_yes"] = round(p + (.01 if p < .5 else -.01), 6)
                time_only = False
        payload = dict(available=True, value=value)
        out.append((dict(row, kind="outcome_view", payload=payload,
                         payload_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest()), time_only))
    return _numbered(out)


def _numbered(pairs):
    return [(dict(row, sequence=n), label) for n, (row, label) in enumerate(pairs)]


def lazy(pairs, wakes):
    """Move each time-only row to its condition's next wake instant (``wakes``: cid -> sorted instants)."""
    keyed = []
    for index, (row, time_only) in enumerate(pairs):
        at = datetime.fromisoformat(row["captured_at"])
        if time_only:
            instants = wakes.get(row["condition_id"], [])
            k = bisect_left(instants, at)
            if k == len(instants):
                continue  # never read again: no wake follows
            if instants[k] != at:
                at = instants[k]
                # Delivered before the instant's own rows: a newer view at that instant still wins.
                keyed.append(((at, 0, index), dict(row, captured_at=at.isoformat()), time_only))
                continue
        keyed.append(((at, 1, index), row, time_only))
    keyed.sort(key=lambda item: item[0])
    return _numbered([(row, label) for _, row, label in keyed])


class RealCadence:
    """A fictional day whose ``rows()`` carry re-stamped views; every other attribute is the day's."""

    def __init__(self, day, mode="drift"):
        self._day, self._mode = day, mode

    def __getattr__(self, name):
        return getattr(self._day, name)

    def rows(self):
        return [row for row, _ in restamped(self._day.rows(), self._mode)]


class WakeLog(EngineV2):
    """``EngineV2`` that records each condition's wake instants."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wake_log = {}

    def tick(self, cid, at):
        self.wake_log.setdefault(cid, []).append(at)
        return super().tick(cid, at)
